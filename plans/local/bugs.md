# Engine and tooling defects found during Gulf Oil India onboarding

_Companion to `plans/local/gulf-oil-india-implementation-plan.md` and `plans/local/tasks.md`._
_Status: `[open]` · `[fixing]` · `[fixed]` · `[wontfix]`_

These were all found by running a **second tenant** through a stack whose engines were
written against the first. That is the value of the exercise: each entry is logic tuned
to the retail tenant's data characteristics that degrades silently on a tenant with
different ones. None of them are Gulf-specific — they would bite any new tenant.

The `datagen`/`ingestion` entries are recorded for completeness; the `ml/` entries are
the substantive ones.

---

## BUG-1 · Cold-start cohort under-forecast by 74% — carries 86.7% of intermittent volume `[fixed — Decision #95 additive-volume gate passed]`

**Where:** `ml/src/retail_ml/models/cold_start_blend.py` (C5) — the cold-start cohort holds
86.7% of intermittent volume at −74.2%. Secondarily `models/train_lgbm.py` —
`_tail_replay_preferred_keys`, fixed and kept (+19 points on `established_history`).

_This entry is kept in the order the investigation actually ran, including two diagnoses
that were measured and overturned. The corrections are the useful part._

**Symptom.** Slow-moving series are under-forecast by **77%**. On the Gulf ten-year run,
`slow_mover` slice bias is **−71.6%** with WAPE 1.082, across 2,216 series.

**Evidence.** Bias measured over all evaluation rows, per selected model:

| selected_model | actual | predicted | bias |
|---|---|---|---|
| `lightgbm_horizon_quantile` | 36,551,398 | 41,051,569 | +12.3% |
| `lightgbm_intermittent_fallback` | 1,034,505 | 236,269 | **−77.2%** |
| `croston_sba_replay_selected` | 13,232 | 12,778 | **−3.4%** |

Croston is **essentially unbiased where it is routed**. It is routed to only
**31,574 of 745,888 sparse rows (4.2%)**; the other **714,314 (95.8%)** fall through to
`lightgbm_intermittent_fallback`, which is the −77.2% population.

**Root cause — CORRECTED after offline measurement.** The first hypothesis was that
`croston_beats_seasonal_naive` (a per-week WAPE comparison) rejects Croston on mostly-zero
series. **That is wrong.** Scored against the real sparse population, holding out the last
52 weeks:

| selection rule | routed | share | actual | pred | bias |
|---|---|---|---|---|---|
| `croston_beats_seasonal_naive` (current) | 1,249 | **66.8%** | 16,918 | 14,083 | −16.8% |
| cumulative-volume rule (proposed fix) | 157 | 8.4% | 1,349 | 1,184 | −12.2% |
| route every sparse series | 1,871 | 100.0% | 22,649 | 19,231 | −15.1% |
| LightGBM fallback (what ships today) | — | — | 22,649 | 4,776 | **−78.9%** |

Three findings overturn the original diagnosis:

1. The WAPE gate admits **66.8%** of sparse series, not 4.2%. It is not the bottleneck.
2. The proposed cumulative-volume replacement routes **8.4%** — a sixth of the current
   rule. Implementing it unmeasured would have shipped a regression as a fix.
3. Routing *everything* still leaves **−15.1%**. Croston's −3.4% in production does not
   transfer: that subset was selected precisely because Croston won on it.

**The actual bottleneck is the second gate**, `_tail_replay_preferred_keys` in
`ml/src/retail_ml/models/train_lgbm.py:442`:

```python
winners = grouped[
    (grouped["rows"] >= 8)
    & (grouped["actual_units"] > 0)
    & (grouped["croston_error"] <= grouped["lightgbm_error"])
    & (grouped["croston_error"] <= grouped["seasonal_error"])
]
```

Four conjunctive conditions on held-out calibration replay. This is where 66.8% eligible
collapses to 4.2% routed. `rows >= 8` alone will disqualify the sparsest series, whose
calibration window holds fewer than eight usable origins.

**Next step — instrument before changing.** Report how many series each of the four
conditions eliminates. Shapes a real fix might take, none yet supported by evidence:

- `rows >= 8` dominates → lower it for sparse series;
- `croston_error <= lightgbm_error` dominates → the same point-accuracy problem one level
  down, needing a volume or service basis;
- the predicate is selecting correctly → then Croston is not the answer, and the fix
  belongs in the LightGBM intermittent branch that serves 95.8% of these rows at −77%.

**Instrumentation result — the binding condition is the LightGBM comparison.**
Each condition's pass rate over the WAPE-eligible population, with "sole blocker"
counting series where that condition alone fails and the other three pass:

| condition | pass % | sole blocker |
|---|---|---|
| `rows >= 8` | 100.0% | 0 |
| `actual_units > 0` | 95.2% | 0 |
| `croston_error <= lightgbm_error` | **0.2%** | **777** |
| `croston_error <= seasonal_error` | 64.5% | 0 |

`rows >= 8` — the condition the original note guessed at — eliminates *nothing*.
The collapse is entirely `croston_error <= lightgbm_error`, and it is the same
point-accuracy trap one level down: summed per-origin absolute error rewards
forecasting near-zero on a mostly-zero series, so it selects for exactly the
downward bias it is supposed to detect. Served evidence:

| model | err/zero-week | err/nonzero-week | % zero weeks |
|---|---|---|---|
| `croston_sba_replay_selected` | 0.386 | 0.869 | 68.1% |
| `lightgbm_intermittent_fallback` | 0.115 | **5.255** | 76.3% |

LightGBM wins the 76% of weeks that are zero by predicting ~nothing, and loses
6× on the weeks that carry the volume. Summed, it wins — and Croston is rejected.

**Fix applied.** Compare the two on *cumulative volume* over the calibration
window rather than summed per-origin error, which is the quantity replenishment
depends on:

```python
croston_volume_gap  = |Σ croston_p50  − Σ actual|
lightgbm_volume_gap = |Σ lightgbm_p50 − Σ actual|
... & (croston_volume_gap <= lightgbm_volume_gap) & ...
```

The other three conditions are unchanged: two eliminate nothing, and
`croston_error <= seasonal_error` still removes a third of candidates on point
accuracy, which is real work. Offline replay of old vs new predicate on the same
population: **20.3% → 48.4% of eligible routed**, a 2.4× increase.

**MEASURED — the fix works mechanically and does not solve the problem.**
A/B on identical features and origins, `gulf` (pre-fix) vs `gulf2` (fixed):

| sparse population | routed rows | share | actual | pred | bias |
|---|---|---|---|---|---|
| `gulf` pre-fix | 31,574 | 4.2% | 13,232 | 12,778 | −3.4% |
| `gulf2` fixed | 139,681 | **18.7%** | 45,966 | 40,355 | −12.2% |
| overall `gulf` | — | — | 1,047,737 | 249,047 | **−76.2%** |
| overall `gulf2` | — | — | 1,047,737 | 276,137 | **−73.6%** |

Routing rose 4.4×, bias moved 2.6 points. The prediction stated before the run was
that ~−45% would confirm the model and ~−70% would refute it: **it refutes it.**

The fix moved *rows*, not *volume*. Croston now covers 45,966 of 1,047,737 sparse
units — 4.4% of the volume. The fallback still holds 95.6% at −76.5%, essentially
unchanged from −77.2%. Croston's own bias degraded −3.4% → −12.2%, as expected: the
original 4.2% was the subset it had been selected on.

**Counterfactual settles it.** `tail_candidate_p50` carries Croston's prediction on
rows where it was *not* selected, so full routing can be scored without a re-run:

| sparse population | actual | pred | bias |
|---|---|---|---|
| as shipped (18.7% routed) | 1,047,737 | 276,137 | −73.6% |
| **every sparse row routed to Croston** | 1,047,737 | 323,746 | **−69.1%** |

Maximum possible routing buys 4.5 points. **Croston is not the lever**, and the
earlier offline estimate of −15.1% for full routing was wrong — it used a crude
`0.23 × actual` stand-in for LightGBM rather than real per-origin predictions.

---

### The actual root cause: p50 is a median, and replenishment needs an expectation

Bias tracks `zero_share_52w` smoothly and monotonically, which model routing cannot
produce:

| zero-share band | actual | bias @ p50 | bias @ p90 | mean nonzero wk | median nonzero wk |
|---|---|---|---|---|---|
| 0.0–0.2 | 34,373,416 | +13.9% | +56.4% | 26.2 | 11.0 |
| 0.2–0.4 | 1,481,636 | +1.0% | +78.5% | 5.8 | 2.0 |
| 0.4–0.6 | 518,661 | −21.7% | +112.6% | 3.4 | 1.0 |
| 0.6–0.8 | 461,913 | −64.2% | +96.7% | 4.5 | 1.0 |
| 0.8–1.0 | 763,509 | **−83.8%** | **+119.3%** | 8.8 | 2.0 |

For a series that is zero 80–100% of weeks, the **median week is zero** while the mean
is not. Summing `yhat_p50` over a horizon therefore under-counts volume by
construction, and the shortfall grows with sparsity — exactly the observed gradient.
`p90` overshoots in every band (+119.3% where p50 gives −83.8%), so the correct
volume basis lies between the two: the **expected value**, which is what replenishment
consumes. Every model in the stack is being asked for a quantile and then summed as
though it were a mean.

**Proven:** the monotonic p50 gradient; p90 overshoot in all five bands; mean ≫ median
on nonzero weeks (8.8 vs 2.0 in the sparsest band); routing is not the lever (−69.1%).
**Inferred, not yet built or measured:** that an expectation-based volume basis closes
the gap.

**These are not slow movers.** Quintile 5 holds 84% of the sparse volume in 611 series
at 12.22 units/week — the top one, `GLF-EVOLT-DRIVE-2-PRM-20L`, runs 65.7 units/week at
89% zero weeks. They are 20L drums, 5L coolant packs and EV fluids: lumpy distributor
demand, nothing for weeks then a large batch order. The `slow_mover` label is itself a
mislabel, which is why BUG-3's cohort gate would not have caught this either.

**Status of the shipped change.** The volume-basis comparison is more defensible than
summed point error on its own merits — point accuracy demonstrably selects for the bias
it should detect — so it is kept, but it must be judged as a routing correction and
**not** as a fix for the bias.

---

### The dominant cause, found after the above: the seasonal-lag eligibility precondition

The p50/median analysis above is correct but governs only **13.3%** of sparse volume.
Splitting the population by how much history each series has:

| history band | series | rows | actual | % of sparse volume |
|---|---|---|---|---|
| 27–52 weeks | 1,062 | 122,278 | 907,985 | **86.7%** |
| > 52 weeks | 1,993 | 623,610 | 139,752 | 13.3% |

Of the sparse rows carrying no Croston candidate at all, **96.4% of the missing volume**
comes from series whose history is ≤ 52 origins — not from the WAPE gate, which accounts
for 3.6%. The cause is the first line of `croston_beats_seasonal_naive`:

```python
if len(observations) <= seasonal_lag:
    return False
```

A series younger than the 52-week lag has no seasonal baseline to compare against, so the
function abstains — and the caller reads that abstention as *ineligible*, sending the
series to `lightgbm_intermittent_fallback` by default. Those series are the twelve
lubricant lines launched inside the horizon (EVOLT EV fluids, ENDURANCE coolants,
36–46 weeks old). `GLF-EVOLT-DRIVE-2-PRM-20L`: 36 weeks of history, 210,037 units.

This is a **cold-start × intermittent gap** — past the cold-start estimator's window,
below the seasonal lag the intermittent path demands, covered by neither.

Measured on the engine's own `croston_sba`, all 1,062 series matched:

| basis | predicted | actual | bias |
|---|---|---|---|
| `lightgbm_intermittent_fallback` (ships) | 234,045 | 907,985 | **−74.2%** |
| croston candidate | 528,045 | 907,985 | **−41.8%** |

**Fix attempted (`gulf3`) and REVERTED — it was inert.** `seasonal_baseline_unavailable`
admitted series with 26–52 origins beside the seasonal test. The run produced
`forecast_eval_predictions.parquet` **byte-identical to `gulf2`** (same md5). Two hours,
zero change, `pct_with_candidate` still 0.0% in the target band.

**Why it was inert, and the error behind it.** The 36–46 week history lengths above were
measured over the *whole* feature file. The backtest scores origins **2025-08-04 →
2026-01-19**, and these lines launch 2025-11-24 — so *at every scored origin* they hold
0–8 origins of history, not 36–46. The `minimum_history=26` floor excluded them everywhere.
`_history(feature_path, origin)` filters `forecast_origin < origin`; history length must be
measured **as-of-origin**, never over the full file.

**The engine had already classified them correctly.** The `cohort` column says exactly
what the history-band split was re-deriving by hand:

| cohort | rows | actual | pred | bias |
|---|---|---|---|---|
| `cold_start` | 122,278 | 907,985 | 234,045 | **−74.2%** |
| `established_history` | 623,610 | 139,752 | 42,093 | −69.9% |

The 86.7%-of-volume population **is the cold-start cohort** — new products forecast at or
before launch. Croston cannot help: there is no history to fit. The intermittent path was
never the lever, and neither was the seasonal-lag precondition.

**Where the real fix belongs:** the cold-start estimator (C5, `models/cold_start_blend.py`),
which is fitted and active but leaves its cohort 74% under-forecast on this tenant. That is
a separate piece of work with its own measurement.

**Correction to this document.** Two claims above are wrong and are kept for the lesson.
`croston_beats_seasonal_naive` was ruled out as a *WAPE gate* — correct — and then blamed
for its *length precondition* — also wrong, because the affected series never reach that
code path at scoring time.

The single error behind every wrong diagnosis in this entry is **measuring the wrong
slice**:

1. bias filtered to `actual_units > 0` — wrong rows;
2. eligibility counted by **series** (66.8% admit) when the quantity of interest was
   **volume** (90% excluded);
3. full-history proxies for LightGBM (`0.23 × actual`) instead of real per-origin predictions;
4. history length over the **whole file** instead of **as-of-origin**.

Each produced a confident number that did not survive the run. The reliable instruments were
the served artifacts themselves — `tail_candidate_p50`, `cohort`, `zero_share_52w` — which
carry the engine's own verdict and needed no reimplementation.

Changing the volume basis from p50 to an expectation remains open for the
`established_history` cohort. It touches the serving contract and what a "forecast" means
downstream, so it needs its own decision record — and note that C1 ("P50 bias correction")
is a pre-registered candidate in `contracts/ml/forecast-improvement-policy.json` whose
implementation exists in `ml/src/retail_ml/models/bias_correction.py` but is **wired to
nothing**. Its materiality gate is relative WAPE, which a bias correction can worsen while
improving volume accuracy — the same trap as the routing predicate, one level up in the
governance.

**Decision for the combined run (2026-08-09): do not wire C1; implement Decision #95.** C1
is governed by relative WAPE, while the open question is expected volume, and BUG-17 proves the
portfolio has opposite-signed errors: scaling P50 upward for sparse rows while dense rows already
over-forecast has no valid single multiplier. P50 therefore remains a median. Decision #95 adds
the separately named `expected_units`: MA13 for established history and a dedicated conditional-
mean LightGBM head for cold start, with hard A6 non-negative-FVA, cold-bias-improvement and
no-fallback gates over all 13 and the final-five replay-confirmation origins. The final clean run
may close BUG-1's **operational additive-volume defect** only if A6 passes; it does not relabel the
P50 median itself as fixed or as an expectation.

**Closure from the clean run.** A6 passed on both frozen populations with no cold-head
fallback rows. Across all 13 origins, cold-start volume bias improved from **−53.63% at P50
to −9.56% in `expected_units`** and FVA versus MA13 was **+14.736%**. Across the final five
replay-confirmation origins, bias improved from **−49.22% to −18.48%** and FVA was
**+28.937%**. The accepted and served contract keeps `yhat_p50` as a median and gives
additive planning its own explicitly named expectation, so the operational defect is fixed
without falsifying quantile semantics.

**Two measurement errors made while diagnosing this, recorded so they are not repeated:**

1. Bias was first computed filtering `actual_units > 0`. That is invalid for intermittent
   demand: Croston forecasts a *rate*, so conditioning on weeks where demand arrived
   excludes every week the same rate correctly exceeded a zero. It produced a spurious
   "Croston is −66% biased" reading. Always measure intermittent bias over all rows.
2. `interval_level = first + 1` was hypothesised to inflate the initial inter-arrival
   interval via leading zeros. Tested against six real Gulf sparse series: aggregate
   predicted/true rate **1.184**, i.e. Croston slightly over-forecasts if anything. The
   hypothesis is **wrong** and the initialisation is not implicated.

---

## PRE-BUG-2 · Integrate the forecast branches, then validate once `[completed]`

**Required order.** Finish the current BUG-1 experiment, integrate the portable forecast
fixes, diagnose and repair BUG-2 with targeted replay work, and only then spend the time
on one authoritative clean end-to-end pipeline. BUG-2 must not be developed against a
forecast codebase that is still moving underneath it.

**Branches.**

- Destination/current Gulf branch: `feature/gulf-oil-india-datagen`.
- Source of the forecast fixes: `forecast-vs-actual-ragged-evaluation`.
- The user explicitly chose to perform the combination directly on
  `feature/gulf-oil-india-datagen`. Functional changes remain separate commits so a failed
  stage is still attributable without an extra integration branch.

### A. Freeze the current BUG-1 checkpoint

- [x] Let the in-progress BUG-1 run finish without changing code underneath it.
- [x] Retain the available pre/post evidence and record routing share, volume
      share, bias by `zero_share_52w`, portfolio regressions, acceptance results and run
      identities. (`gulf2` parquet was deleted in error; its recorded numbers and PostgreSQL
      row remain, while `gulf` and `gulf4` artifacts are retained.)
- [x] Commit the Gulf BUG-1 implementation and findings before starting branch
      integration. The current cumulative-volume change is a routing correction, not
      closure of the still-open P50-versus-expectation problem.

### B. Integrate all portable code in one batch

- [x] Bring the functional changes from `forecast-vs-actual-ragged-evaluation` into the
      integration branch in this order:
  1. `8d80b42` — recent h1-h4 ragged evaluation, run/verifier contracts, migration 0021,
     serving projection, API and UI comparison semantics.
  2. `55b8865` — normalize a partial current-origin week to its weekly equivalent before
     current-cycle scoring.
- [x] Do **not** import the source branch's retained demo authority as Gulf evidence:
  - exclude `a46b6ed`'s demo expected pin and r7/r8 publication-selection records;
  - exclude `e2c277f`'s demo forecast-closure and inventory-entry identities;
  - exclude unrelated local launch configuration and demo-only task prose.
- [x] Preserve the existing Gulf r7-r10 history. New Gulf pins, closure records and
      selection generations must be derived from the final integrated run rather than
      resolved by choosing the demo side of a merge conflict.
- [x] Keep BUG-1, ragged evaluation, weekly normalization and later BUG-2 work as
      separate commits even though they will share one final pipeline validation. This
      keeps a failing stage attributable without paying for multiple end-to-end runs.
- [x] Add focused tests before BUG-2 work starts:
  - seven-day current origin is unchanged;
  - partial current origin uses `weekly_units_equivalent`;
  - null weekly equivalent follows the explicit fallback;
  - recent origins cannot overlap the complete acceptance grid;
  - the recent artifact admits only the intended horizons and finite comparison values;
  - the weekly API selects one freshest horizon and reports per-series P90 coverage.

### C. Diagnose and fix BUG-2 without another full pipeline

- [x] Use the retained Gulf source, features and inventory artifacts for targeted replay
      diagnostics after the integrated forecast code is stable.
- [x] Instrument actual snapshot dates, bridge start/end, bridge length and reconstruction
      delta per replay period; split the evidence between arrival and non-arrival weeks.
- [x] Prove or refute the 14-day review-cycle hypothesis before changing the oracle.
- [x] Implement the data-derived snapshot/bridge correction and validate the replay stage
      directly. Do not change the Gulf tenant to a weekly delivery cycle to make it pass.

### D. Run the clean pipeline once, after all code is stable

- [x] Clean the generated work/artifact directories and rebuild the serving database only
      after BUG-2's targeted replay validation passes and every code change above is fixed.
      PostgreSQL/MLflow volumes and all prior datagen, ingestion, ML and DuckDB run state were
      removed; the fresh database was first brought to migration 0021. Gulf datagen then promoted
      `run-95b856f20766c9e1` under the `performance` profile in **2h 53m 25.3s**. The still-empty
      serving database was subsequently advanced to Decision #95 migration 0022 before the
      combined forecast run; no historical materialization was reinterpreted.
- [x] Rebuild ingestion and the reusable weekly-feature boundary from that source. The
      land-through-features chain completed in **7m 33.2s**, selected curated revision
      `run-95b856f20766c9e1-r2`, reproduced source snapshot `a88758a1…`, and promoted
      publication fingerprint `1b88e7f5…` as Gulf selection generation r11. The corrected
      curated dimensions now retain `gulf-marketplace` as `marketplace` (with
      `bazaar-trade` still `store` and `gulf-online` still `online`), proving BUG-2's
      ingestion half against the clean rebuild rather than only the retained counterfactual.
- [x] Run the full Gulf flow once from the agreed clean boundary: ingestion, feature build,
      complete plus recent backtest, normalized current-cycle score, classification,
      publication, migration/materialization/activation, inventory build and corrected
      replay. The complete backtest took **2h 27m 53.3s**; current-cycle scoring took
      **9m 34.0s**. The accepted bundle was republished after BUG-18, materialized and
      activated without repeating either stage. Inventory build through activation took
      **12.8s**. Replay completed its oracle and emitted all eight required metric rows; its
      policy candidate honestly lost the incumbent, which is a downstream policy verdict
      rather than an oracle failure.
- [x] Require migration `0023_marketplace_channel_type`, run schema v5 and verifier v7 to be
      active, and require both the forecast and inventory authorities to be unique. Active
      forecast is `fr_d2441088e0771b76` / `fv_e35461a7e76416bd`; active inventory is
      `ir_7eb687be5aef566c` / `iv_7eb687be5aef566c`.
- [x] Generate fresh Gulf expected pins, closure/entry records and publication-selection
      generations from that run. Retain earlier Gulf generations as superseded history;
      never overwrite them with the demo branch's identities. The expected pin resolves to
      source `a88758a1…`, publication `1b88e7f5…`; generation r11 is active and the generated
      closure/entry records name the live Decision #95 authorities.
- [x] Commit and validate the final clean-run authorities on
      `feature/gulf-oil-india-datagen`; no integration-branch merge is needed because the user
      elected to work directly on this branch. The generated records pass 333 contract tests,
      the developer contract command and the live authority drift check.

**Run-economy rule.** Unit tests, contract tests, migration tests and targeted replay runs
are expected during development; they are not substitutes for the final pipeline, but
they avoid paying for repeated ingestion and multi-hour backtests. There should be one
clean authoritative end-to-end run for the combined change set, not one per commit.

**Completion result.** Sections A–D completed in order. The published A6 record, retained
evaluation rows and served portfolio all pass, so BUG-1/12/17 close on the one clean run;
the older P50 gates alone were not used as proof.

---

## BUG-2 · Replay loses channel semantics and hard-codes snapshot cadence `[fixed]`

**Where:** `ml/src/retail_ml/inventory_run/replay_driver.py`

**Symptom.** `inventory_replenishment_replay` is unavailable for Gulf. The weekly
reconstruction is off by **42.74 units per cell** against a **0.5** tolerance — ~85×
over, and ~86% of the mean store cell position (49.7 units), so not a scale artifact.
`inventory_replay_metrics.parquet` has 0 rows: oracle-first correctly stops before any
policy comparison is scored.

**Original diagnosis — one real latent defect, but not the residual's cause.**

```python
thursday = origin + timedelta(days=3)   # snapshot weekday assumed
for offset in (4, 5, 6):                # bridge span assumed
```

plus the documented premise that *"every arrival in this source lands Friday 23:00"*.
None of these are derived from the data. Removing them is still required for a portable
replay, but instrumenting the retained Gulf run proved they do **not** explain the 42.74
residual: every one of the 52 observed snapshots is Thursday-dated and every bridge is
three days, exactly what the old code assumed.

Consequence already hit: Gulf's horizon originally started on a Monday, so all 522 weekly
snapshots landed on Mondays, no period found a Thursday snapshot, `weeksCompared` was 0,
and the oracle produced no measured delta at all — `NO_ORACLE_WEEKS_AVAILABLE`. Worked
around by moving the horizon start to a Thursday (`2016-08-04`), which cost a full
~6-hour regeneration. After that the oracle runs (`weeksCompared: 52`) but still fails
tolerance.

**Actual root cause — canonical collapsed `marketplace` into `store`.** The source config
correctly declares `gulf-marketplace.type: marketplace`, and the Config Builder carries the
same value. The canonical transform inferred channel type with `online -> online; everything
else -> store`, so the retained publication labels both `bazaar-trade` and
`gulf-marketplace` as store channels. The source's `StoreEchelon.sell()` consumes shelf stock
only for the true `store` channel; replay therefore charged the similarly sized marketplace
stream to the shelf a second time. This is why canonical weekly replay demand was roughly
double the stock movement visible between snapshots.

**The 14-day hypothesis is refuted.** Period instrumentation split the retained run into 26
arrival and 26 non-arrival weeks. Before correcting the channel type, mean absolute delta was
**49.90 units/cell** in arrival weeks and **35.87** in non-arrival weeks: large and one-sided
in both populations, not concentrated where fortnightly receipts land. Preserving only
`gulf-marketplace` as `marketplace` makes the same retained 52-week oracle reconcile at
**exactly 0 units** in both populations, across every compared week.

**Fix implemented.**

1. Ingestion now preserves `marketplace` before applying the existing online/store name
   inference, with a transform-version bump and a focused canonical-type test.
2. Replay now selects each cell's actual admitted snapshot, bridges from the following local
   day to period close, and exposes per-period snapshot dates, bridge bounds/length, arrival
   classification and reconstruction delta through a targeted diagnostic helper. A fixture
   proves Saturday, Tuesday and Friday snapshots without a Thursday assumption.

The retained source was first validated through a read-only corrected canonical view; no retained
artifact was mutated. The clean rebuild then preserved `gulf-marketplace` end to end, the replay
oracle completed, and all **8 cohort/market metric rows** were emitted. The fresh downstream
policy candidate still loses the incumbent on six service/stockout measures while winning both
mean-inventory measures, so `replayPassed` is false. That is an honest policy comparison after a
successful oracle, not the missing-channel/cadence defect tracked by BUG-2.

**Do not "fix" by changing the tenant.** `reviewCycleDays` remains 14. The replay must
reconcile the source actually supplied; changing Gulf to manufacture a pass is forbidden.

---

## BUG-3 · No acceptance gate can see slow-mover error `[open]`

**Where:** acceptance protocol / `contracts/ml/`

**Symptom.** BUG-1's −77% under-forecast passed every acceptance gate. The Gulf forecast
was accepted, materialized and activated with it.

**Root cause.** Acceptance scores cohorts as **cold-start vs established-history**. The
affected series are established — ten years of mostly-zeros. There is no slow-vs-fast
cohort gate. A `slow_mover` slice *is* computed and materialized (`forecast_metrics`)
but it is display-only, never gated.

**Proposed fix.** Add a slow-mover acceptance cell so a tenant whose assortment is
dominated by intermittent demand cannot pass on the strength of its dense series. Needs
its own decision record — it changes what "accepted" means.

---

## BUG-4 · `tools/dev.py` assumed a single tenant in three places `[fixed]`

Each made the stack refuse or silently mis-target a second tenant.

1. **datagen guard** globbed `output/*/run-*`, so any tenant's promoted run blocked every
   other tenant's generation. Now scoped to the scenario being generated.
2. **`pipeline` had no `--source-profile`**, hard-coding the retail profile regardless of
   the source run passed in. Added, with a fail-fast existence check.
3. **`pipeline` hard-coded `contracts/ml/expected-pin.json`**, so ML stages would validate
   a second tenant's publication against the first tenant's fingerprints. `--expected-pin`
   added and threaded into the four stages whose CLI declares it.

---

## BUG-5 · Config Builder carries an unguarded copy of the generator contract `[fixed]`

**Where:** `datagen/config-builder.html`, `datagen/tools/sync_presets.py`

The builder does not read `catalog_packs.py`; it embeds a serialized copy. Nothing
enforced that the two agreed — `sync_presets.py` appears in no README, Makefile, test or
`tools/dev.py` path. Two vocabularies had drifted or would have:

- the inline `optionDimensions` Set, which `sync_presets.py` does not touch because it
  only replaces JSON script elements;
- the Tax category dropdown, whose hand-copied 12-value list lacked `lubricants`, so a
  Gulf category rendered as `apparel` and **exporting would have silently rewritten the
  tax class**.

Fixed by hoisting `SUPPORTED_TAX_CATEGORIES`, hand-extending the inline Set, and adding
drift tests for both. The dimension drift test caught its target on first run.

---

## BUG-6 · `retail_ingestion.cli run` replays cached gate verdicts `[fixed]`

After a Gate A failure, the work root retains `gate-a.json`. A subsequent run with a
*corrected* profile replays the stale `critical` verdict rather than re-running the gate —
Gate A passed standalone while the pipeline kept refusing. The work root must be cleared
by hand after any profile change.

**Fixed** by the second route: `tools/dev.py pipeline` now takes `--rebuild` and threads it
to `retail_ingestion.cli run`. Input fingerprinting remains the better long-term answer —
it would invalidate automatically instead of relying on the operator remembering the flag —
but that belongs to the ingestion contract, not the dev harness.

---

## BUG-7 · `sync_presets.py` strips YAML comments `[fixed]`

Running it rewrote `multi-market-10-year-demo.yaml` and deleted a P4-11 rationale comment
block explaining why the store replenishment policy was tightened. The tool round-trips
through `safe_load`/`safe_dump`, which is lossy for comments. Pre-existing; worked around
by restoring retail presets from `main` after each sync.

**Fixed** by making the write conditional: `_sync_yaml` keeps the parsed original, deep-copies
it before stamping, and writes only when the semantic content actually moved. A preset already
in sync keeps its comments and its formatting. Verified — a full sync now leaves every preset
YAML byte-identical. This does not make `safe_dump` round-trip comments, so a preset that
genuinely changes still loses them; that would need `ruamel.yaml`, a new dependency for a
dev-only tool, and the unconditional rewrite was the whole of the observed harm.

---

## BUG-8 · Config Builder shipped a stale Gulf preset — the Thursday fix was not embedded `[fixed]`

**Where:** `datagen/config-builder.html`, `datagen/tests/test_gulf_catalog.py`

**Symptom.** The builder embedded the Gulf showcase with `startDate: 2025-08-01` — a
**Friday** — while the YAML had been corrected to `2025-08-07`, a **Thursday**. Exporting
the Gulf showcase from the Config Builder handed back a Friday-start config.

**Why it matters.** The Thursday start is not cosmetic. BUG-2's replay oracle looks for a
Thursday snapshot; a non-Thursday horizon start produces `weeksCompared: 0` and
`NO_ORACLE_WEEKS_AVAILABLE`. Correcting it the first time cost a full ~6-hour regeneration.
The builder would have silently reintroduced it.

**Root cause.** Same shape as BUG-5 — the builder carries a serialized copy — but BUG-5's
fix guarded the *vocabularies* (`catalogPacks`, `localePacks`, the dimension Set, the tax
dropdown) and not the embedded **presets**, which are the larger payload. Found only because
BUG-7's no-op guard made a sync's real changes visible instead of burying them in noise.

**Fixed.** Re-synced, and added `test_embedded_presets_match_their_yaml`, which asserts every
preset in `{**PRESETS, **EMBED_ONLY_PRESETS}` equals `load_config(path)` — covering all five
presets, not just Gulf, and failing with an instruction to re-run the sync.

**Rechecked after forecast integration (2026-08-08).** The Config Builder drift suite passes
23 tests plus 5 subtests, and a full `sync_presets.py` run produces zero Git diff across the
HTML and preset YAML. No additional Config Builder fix is required for this change set.

---

_BUG-9 … BUG-16 were all found in one pass, by serving the `gulf4` forecast through the API
and UI and reading what the screens actually showed. None of them were visible from the
pipeline logs or the artifacts — they needed the stack running and someone looking at it._

---

## BUG-9 · `forecast/summary` takes ~13 s and blocks the Forecast screen `[open]`

**Where:** the Go API's `/api/v1/forecast/summary` handler.

**Symptom.** Measured twice: **13.8 s and 13.1 s**. The Forecast screen renders
"Loading the accepted forecast…" for that whole time and its five KPI tiles read
`Not available`. Every other call on the screen — `horizons`, `stores`, `series`, `drivers`,
`signals`, `versions`, `actuals` — returns 200 in under a second, so the screen is gated on
one slow query.

**Why it matters.** It is the first screen a demo opens, and for thirteen seconds it looks
broken rather than slow. Not tenant-specific — the query would be slow for any tenant of this
size — but Gulf's grain is what made it visible.

**Not diagnosed.** No profiling was done; the handler was not read. Recorded as measured.

---

## BUG-10 · Inventory filters show the *other* tenant's categories `[open]`

**Where:** `ui/src/generated/inventoryScreenLayout.ts:34`, generated by
`tools/extract_reference_layout.py` from
`docs/ai_retail_intelligence_dashboard_multicurrency_v6.html`.

**Symptom.** On a lubricants tenant, Inventory Overview offers
`All Categories: Footwear, Apparel, Electronics, Beauty` and
`All Regions: West, North, South, East`. The Forecast screen, which builds its category list
from the API, correctly shows `gulf-adblue … gulf-tractor`.

**Root cause.** The generated file's own header states the contract it breaks:

> Structure only. Every VALUE on these screens comes from the live API — the reference's
> illustrative figures are deliberately not extracted, so sample data is never one import
> away from a screen.

The extractor honours that for *figures* and not for *filter option lists*, which are equally
illustrative. So the first tenant's sample categories are compiled into the second tenant's UI.

**Not fixed deliberately.** `GOI-11` says: *if a screen needs a code change to show Gulf data,
escalate — do not patch the UI.* The fix belongs in the extractor (emit option lists as
structure, populate from the API), not in a hand-edit of a generated file.

---

## BUG-11 · Every Gulf distributor is located in Mumbai `[open]`

**Where:** `datagen/configs/gulf-oil-india-ten-year.yaml` — store definitions.

**Symptom.** The UI renders "Chennai Distributor, Mumbai", "Guwahati Distributor, Mumbai",
and so on for all 13. Confirmed in curated data, not a display artifact:

```
store_id                     market_id   region  city
gulf-india:ahmedabad-dist    gulf-india  MH      Mumbai
gulf-india:chennai-dist      gulf-india  MH      Mumbai
gulf-india:guwahati-dist     gulf-india  MH      Mumbai   (all 13 identical)
```

**Why it matters.** Two ways. It is visibly wrong in a demo to an Indian client — Chennai is
not in Maharashtra. And it collapses the region dimension: `All Regions` offers exactly one
value, so any regional analysis is degenerate, and weather/local-event features resolve to a
single city for a country-wide distribution network.

**Fix.** Datagen config only — assign each distributor its real city and state. Cheap, but it
needs a regeneration to reach curated data, so it should ride along with the next full rebuild
rather than trigger one.

---

## BUG-12 · Forecast Value Add is negative — the model loses to a 13-week moving average `[fixed]`

**Symptom.** The Forecast screen reports **FVA −45.2%** ("relative improvement vs MA13").
It was −46.8% before any of the BUG-1 work, so two measured engine fixes moved it 1.6 points.

**Why it matters.** FVA is the honest summary of whether the model is worth running. A
negative FVA says a thirteen-week moving average would serve this tenant better. It is the
number a client will ask about first, and the answer today is unflattering and correct.

**Relationship to BUG-1 — corrected.** BUG-12 is **not** downstream of cold start. At the
actual `market_portfolio`, horizon-0 grain, the champion is 89.84% accurate at +10.00% bias;
MA13 is 93.00% accurate at −2.78% bias, producing FVA −45.21%. Cold start is only 3.9% of
portfolio volume and its −780,253-unit error currently offsets the opposite-signed error in
the rest of the portfolio. Removing cold start makes champion bias worse, +10.00% -> +12.56%,
and leaves the MA13 loss intact. The dominant model defect is tracked independently as
BUG-17.

**Closure from the clean run.** At the same `market_portfolio`, horizon-0 grain,
`expected_units` is **94.0326% accurate** versus MA13's **93.0013%**, for
**+14.7361% FVA** and **+0.465% bias**. This is the served additive-volume basis; P50 remains
a quantile and is not relabelled as the portfolio expectation.

---

## BUG-13 · P50–P90 interval covers the actual in 0 of the last 8 weeks `[fixed]`

**Symptom.** The Forecast-vs-Actual card states: *"Last 8 weeks · actual inside the P50–P90
forecast range in 0 of 8."* Zero of eight, not a marginal miss.

**Diagnosis.** This is a display/comparison-semantics defect, not evidence that the calibrated
series intervals suddenly failed. The chart summed `yhat_p90` across ~2,034 series and treated
that sum as the 90th percentile of the portfolio total; quantiles are not additive. Its caption
then counted weekly portfolio actuals against that non-interval. Per-series coverage is 90.8% on
recent h1-h4 and 89.9% on complete h19-h26, consistent with calibration.

**Why it matters.** The card presented a mathematically invalid aggregate as an interval and
turned it into a confident count. That can make a calibrated model look broken (“0 of 8”) or
perfect (“8 of 8”) depending on the portfolio, while neither statement measures coverage.

**Fix verified.** `8d80b42` adds disjoint ragged h1-h4 evaluation, migration 0021 and serving
semantics that report per-series coverage rather than claiming the summed band is an interval.
The source demo showed “8 of 8” while Gulf showed “0 of 8”; both are opposite symptoms of the
same invalid construction. On the clean served Gulf h1-h4 slice, coverage is
**73,513 / 76,824 = 95.6901%** at leaf grain. The UI no longer draws or captions a sum of
per-series quantiles as a portfolio interval. The redundant comparison-basis selector is removed;
the card is fixed to the comparable h1-h4 evaluation and now reads **“Last 8 comparable weeks ·
freshest forecast within h1–h4 · 95.7% P90 coverage across 76,824 series-weeks.”** The additive
bar is labelled **Forecast**, not Expected Value/Expected volume.

---

## BUG-14 · Stock Turn 84.2x does not reconcile with the curated data `[open]`

**Symptom.** The Inventory screen reports **84.2x**, labelled *"trailing demand over units on
hand, annualised"*. Computed directly from curated data:

| denominator | units on hand | implied turn |
|---|---|---|
| all locations | 480,152 | **12.4x** |
| warehouses only | 331,071 | 18.0x |
| stores only | 149,081 | 39.9x |

against 5,947,366 units sold in the trailing year. No denominator reaches 84.2x.

**Why it matters.** 12.4x is a plausible, healthy turn for a lubricants distributor. 84.2x is
not plausible for any physical-goods business — it implies the entire inventory turning over
every 4.3 days. A client who knows their own business will notice immediately.

**Not diagnosed.** Either the metric's definition differs from its label (a shorter trailing
window annualised, or a different scope) or it is a defect. The label is what makes it wrong
either way.

---

## BUG-15 · The Ageing Inventory card appears to be warehouse-only `[open]`

**Symptom.** The card's five buckets sum to **331,071 units**, which is *exactly* warehouse
on-hand at the latest snapshot (stores hold 149,081; the total is 480,152). An exact six-digit
match is not coincidence.

**Why it matters.** The card sits under a header reading "Enterprise inventory position, risk,
working capital and actions", and its recommended actions — "Markdown / clearance",
"Transfer / promote" — would be read as applying to the whole estate. Store-held ageing stock,
31% of units, is invisible.

**Not diagnosed.** The scoping may be deliberate; if so the heading is wrong. Either way the
card and its header disagree.

---

## BUG-16 · Pooled bias hides a cohort with the opposite sign `[open]`

**Symptom.** The Forecast screen reports **Forecast Bias +6.8%** at h1–h4 against a ±5%
target — over-forecasting, flagged `Watch`. The cold-start cohort in the same run is
**−53.6%** — under-forecasting by half.

Both are correct. The dense population dominates the volume-weighted pooled figure, so the
tile is over-forecasting and the cohort that carries the intermittent volume is severely
under-forecasting, and the screen shows only the first.

**Why it matters.** A planner reading +6.8% would trim orders — the exact wrong action for the
drum lines that are already short by half. The pooled tile does not merely omit the cohort, it
points the opposite way.

**Relationship to BUG-3.** BUG-3 says no acceptance gate can see slow-mover error. This is the
same blindness one layer up, in the display: `slow_mover` is computed and materialized but
never surfaced next to the headline. The fix for both is a cohort-aware view, which is why
they should be decided together.

---

## BUG-17 · Dense established-history forecast loses badly to MA13 `[fixed]`

**Symptom at the serving grain.** At `slice_type=market_portfolio, horizon=0`, the retained
`gulf4` champion is **89.84% accurate with +10.00% bias**. MA13 is **93.00% accurate with
−2.78% bias**, so FVA is **−45.21%**. This verifies BUG-12 as a real independent model
failure, not a consequence of BUG-1.

**The exact slices, without relabelling proxies as cohorts.**

- All non-cold-start rows are 96.1% of volume and over-forecast by **4,541,389 units
  (+12.56%)**. This is the arithmetic quoted during triage, but `non-cold-start` is a filter,
  not an engine cohort name.
- The actual dense slice (`zero_share_52w < 0.2`) is 34,373,416 units, 91.4% of portfolio
  volume, and over-forecasts by **4,769,106 units (+13.87%)**. At portfolio-week grain its
  champion accuracy is 86.01% versus MA13's 93.66%, with FVA **−120.52%**.
- Within `established_history`, `lightgbm_horizon_quantile` alone carries 35,826,713 actual
  units and over-forecasts by **4,803,399 (+13.41%)**. Sparse established-history rows have
  the opposite sign, so one pooled label would hide the mechanism again.

Cold start under-forecasts by 780,253 units; it partly cancels the much larger dense error.
Fixing BUG-1 cannot make BUG-12 recover and may make headline portfolio bias look worse while
improving the affected cohort.

**Decision revised before the expensive run at the user's instruction.** Decision #95 owns the
additive-volume defect without changing P50. `expected_units` uses MA13 for established history,
so the dominant dense population cannot lose to MA13 by construction, and a dedicated
conditional-mean head owns cold start. A new hard A6 gate requires non-negative FVA and improved
cold-start volume bias on all 13 and the final-five replay-confirmation origins.

**Closure from the clean run.** On the exact dense slice (`zero_share_52w < 0.2`) and the
same market/origin/target/horizon aggregation, expected-volume bias is **+1.4929%** and
accuracy is **93.6580%**, versus MA13's **93.6563%**. FVA is therefore **+0.0264%**, while
the unchanged P50 remains at **+13.8744% bias**, **86.0108% accuracy** and **−120.5198%
FVA**. The full portfolio has the larger +14.7361% FVA margin because the dedicated cold
conditional-mean head also repairs the other side of the offsetting error.

---

## BUG-18 · Forecast materialization rejects authoritative marketplace channels `[fixed]`

**Observed on the clean Decision #95 run.** Backtest, current scoring, classification and
forecast-run v5 publication all completed, but PostgreSQL materialization rejected
`channel_type = marketplace` under
`ck_forecast_series_dimension_channel_type`. The transaction rolled back before activation.

**Cause.** Datagen, Config Builder and ingestion agree on the domain
`store | online | marketplace`; migration 0003 retained the older two-value domain
`store | online`. Reclassifying marketplace as online or store would destroy a deliberate
business dimension, so this is a serving-schema defect rather than a source-data fix.

**Fix.** Migration `0023_marketplace_channel_type` expands the database constraint,
moves all serving pins together, and adds a live-schema assertion for all three values. The
OpenAPI enum and Go query normalizer now preserve marketplace filters, and the Forecast
workbench labels marketplace explicitly instead of collapsing it into Store. The
already-completed ML artifacts will be republished under the new migration identity and the
pipeline resumed from materialization; no datagen, feature build, backtest or current scoring
is repeated.

**Closure.** The republished bundle materialized and activated under migration 0023. The live
forecast client preserves `channelType=marketplace`, and the marketplace workbench filter returns
**3,201 rows** rather than collapsing them into Store. The pre-0023 accepted bundle is retained
separately as migration-0022 evidence; it is not an activation authority.

---

## BUG-19 · Relative publication root crashes pipeline after inventory activation `[fixed]`

**Observed on the clean inventory run.** Build, verification, materialization and activation
all succeeded, then `tools/dev.py pipeline` returned exit 1 while printing its closing API
hint. A relative `--publication-root` was passed unchanged to `Path.relative_to(REPO_ROOT)`,
which accepts only an absolute path under that absolute root.

**Fix.** Pipeline publication roots are expanded and resolved once before both stage commands
and closing hints use them. The regression test passes a relative `run-r2` override and the
pipeline slice test now correctly treats forecast activation as an intermediate boundary
rather than the end of the post-datagen stage list.

---

## BUG-20 · Explicit suffixed run ID is ignored beside source root `[fixed]`

**Observed in the same closing hint.** The resume command supplied both the deterministic
datagen `--source-root run-95…` and the authoritative ingestion generation
`--run-id run-95…-r2`. Pipeline resolution always preferred `source_root.name`, so evidence
and API hints pointed to the unsuffixed path even though inventory correctly read the explicit
r2 `--publication-root`.

**Fix.** An explicit run ID now wins over the source snapshot name. A regression test freezes
the required r2 result when both arguments are present.

---

## BUG-21 · Demand at Risk reuses ATP by week, drops two channels and values cost as sales `[fixed]`

**Observed on the active Decision #95 inventory projection.** The Forecast overview served
**1.6405 units / ₹23,039.68** of risk across 3,174 assessed SKU-store cells. Only Indore was
non-zero; the other 12 distributors all read ₹0. The UI reconciled exactly to the retained
artifact, so this was not a currency formatter or Store View join defect.

**Three binding causes.** The builder copied the same full node ATP onto every weekly horizon
and summed `max(P90[h] - ATP, 0)`, effectively replenishing the position at the start of every
future week. The served forecast loader omitted `channel_id`, so its `(market, store, SKU,
horizon)` index overwrote two of three authoritative channel rows with whichever PostgreSQL
returned last. Finally, the engine's `unit_price_minor` input was populated from accepted unit
cost while the screen labelled it potential lost-sales exposure.

**Fix.** Risk now stays at native SeriesKey grain during calculation. The one node ATP pool is
allocated through the governed channel allocator, each channel's upper demand is summed over
the exact fractional lead-time-plus-review window, and its ATP allocation is subtracted once.
Channel exposures are aggregated only after that leaf calculation; the result is not labelled
the statistical P90 of total demand. Value uses the latest origin-visible realised net selling
price at the SeriesKey, with a same-market/SKU median fallback and no cross-market or cost
substitution. The raw served forecast now retains `channel_id` explicitly.

**Closure.** Inventory run `ir_2c8feff1e1e9d917` / version `iv_2c8feff1e1e9d917` verified,
materialized and activated in **15.8 seconds** without datagen, ingestion, feature or forecast
replay. The live API serves **168,537.336 units / ₹176.83 Cr**, 3,174 assessed cells and
**13 of 13 distributors with non-zero risk**. The 13 per-distributor values sum exactly to the
overview value.

---

## BUG-22 · SKU View labels the MA13 expectation as AI and mixes estimator metrics `[fixed]`

**Observed.** The workbench's Baseline and AI Forecast were exactly equal on **8,019 of 9,081
evaluated SeriesKeys (88.3%)**. That was expected from Decision #95, not evidence that LightGBM
learned the moving average: the column used additive `expected_units`, whose established-history
head deliberately is MA13. The row accuracy/bias also used `model_id='champion'` (the same
expected-volume head), while Confidence was weighted from P50/P90. One row therefore described
two estimators under one set of headings.

**Fix.** SKU View now labels and sums the actual **AI Forecast (P50)**, and its accuracy, WAPE
and bias use the published `p50` metric rows. Confidence already derives from the same P50/P90
distribution and is now estimator-aligned. Missing P50 evaluation evidence returns the governed
`insufficient_evidence` state rather than failing the whole route.

**Closure.** Only **514 of 9,081 (5.7%)** evaluated rows now happen to equal MA13. The live
h1-h4 P50 slice has WAPE **33.9021%** (pooled leaf accuracy **66.0979%**) and bias **+6.7658%**.
Those lower leaf-grain accuracies remain visible because they are real; the fix aligns the
numbers rather than replacing them with the more flattering additive portfolio metric. A live
PostgreSQL regression independently recomputes each displayed P50 forecast, accuracy, bias and
confidence.
