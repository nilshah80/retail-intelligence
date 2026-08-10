# Engine and tooling defects found during Gulf Oil India onboarding

_Companion to `plans/local/gulf-oil-india-implementation-plan.md` and `plans/local/tasks.md`._
_Status: `[open]` · `[fixing]` · `[fixed]` · `[wontfix]`_

These were all found by running a **second tenant** through a stack whose engines were
written against the first. That is the value of the exercise: each entry is logic tuned
to the retail tenant's data characteristics that degrades silently on a tenant with
different ones. None of them are Gulf-specific — they would bite any new tenant.

The entries now span `datagen`, ingestion, ML, API and UI. Each is retained with the
measured evidence, implementation boundary and closure condition that would make a fix
reviewable rather than anecdotal.

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

**Closure from the final clean run.** A6 passed on both frozen populations with no cold-head
fallback rows. Across all 13 origins, cold-start volume bias improved from **−53.9610% at P50
to −9.4591% in `expected_units`** and FVA versus MA13 was **+14.7505%**. Across the final five
replay-confirmation origins, bias improved from **−49.4577% to −18.3846%** and FVA was
**+28.7034%**. The accepted and served contract keeps `yhat_p50` as a median and gives
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

## BUG-3 · No acceptance gate can see slow-mover error `[fixed]`

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

**Closure.** Decision #82 is implemented in acceptance schema v6. `slow_mover_diagnostics`
evaluates established-history slow movers at the market/origin grain and is wired as hard gate
**A3**, with explicit series/origin sufficiency checks rather than a display-only slice. The
accepted closure record carries `A3: true`; model-primitives fixtures prove pass,
`insufficient_evidence` and fail outcomes, including the case where only one origin lacks enough
series. Cold-start slow movers remain owned by A1, so the same cells are not gated twice.

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

## BUG-9 · `forecast/summary` takes ~13 s and blocks the Forecast screen `[fixed]`

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

**Diagnosis and closure.** The handler counted coverage by scanning the multi-million-row
evaluation prediction table even though the accepted `forecast_metrics` authority already carries
the evaluated series count. Reusing that governed aggregate removes the full scan without changing
the number or its grain. The retained live route improved from approximately **12.5 seconds to
0.55 seconds**. On the final authority it returns in **0.435 seconds**; Go unit and
live-PostgreSQL route tests pass.

---

## BUG-10 · Inventory filters show the *other* tenant's categories `[fixed]`

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

**Closure.** The extractor now emits only each selector's structural caption (`All Regions`,
`All Categories`, and so on); it never compiles illustrative option values. The active API derives
regions, categories, health classes and location kinds from the selected forecast/inventory
authorities, and the UI fills the reference-structure selectors from that response. A component
fixture proves Gulf options appear while `Footwear` and `West` do not, and extractor `--check`,
the Inventory component suite and the production build pass.

---

## BUG-11 · Every Gulf distributor is located in Mumbai `[fixed]`

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

**Implemented.** Store geography is now an optional, pair-validated city/region override in the
generator contract and Config Builder. All thirteen Gulf distributors carry their real city/state
pair (Mumbai/Pune Maharashtra, Ahmedabad Gujarat, Indore Madhya Pradesh, Faridabad Haryana,
Jaipur Rajasthan, Ludhiana Punjab, Chennai/Coimbatore Tamil Nadu, Bengaluru Karnataka,
Hyderabad Telangana, Kolkata West Bengal and Guwahati Assam). Location generation uses the
override with market geography only as a complete fallback. Config/preset drift tests pass.

**Final-run verification.** The regenerated source, curated dimensions, live API and rendered UI
all expose thirteen distributors across eleven states/regions: Ahmedabad/GJ, Bengaluru/KA,
Chennai and Coimbatore/TN, Faridabad/HR, Guwahati/AS, Hyderabad/TS, Indore/MP, Jaipur/RJ,
Kolkata/WB, Ludhiana/PB, and Mumbai and Pune/MH. The region selector offers those eleven codes;
the Mumbai-only defect is gone and no additional pipeline run is required.

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

**Closure from the final clean run.** At the same `market_portfolio`, horizon-0 grain,
`expected_units` is **94.0338% accurate** versus MA13's **93.0015%**, for
**+14.7505% FVA** and **+0.4533% bias**. This is the served additive-volume basis; P50 remains
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
same invalid construction. On the final served Gulf h1-h4 slice, coverage is
**73,583 / 76,824 = 95.7813%** at leaf grain. The UI no longer draws or captions a sum of
per-series quantiles as a portfolio interval. The redundant comparison-basis selector is removed;
the card is fixed to the comparable h1-h4 evaluation and now reads **“Last 8 comparable weeks ·
freshest forecast within h1–h4 · 95.8% P90 coverage across 76,824 series-weeks.”** The additive
bar is labelled **Forecast**, not Expected Value/Expected volume.

---

## BUG-14 · Stock Turn 84.2x does not reconcile with the curated data `[fixed]`

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

**Diagnosis and closure.** The SKU dimension correctly attributes the sum of supplied-store
demand to each warehouse for that warehouse's own cover display. The enterprise aggregate then
summed those attributed rates again: on the retained artifact, 16,709.703 daily store units became
116,967.923 after six warehouse copies, yielding **84.178x** over 507,178 units. Enterprise turn
now filters the numerator to customer/store demand once and keeps all physical on-hand in the
denominator, yielding **12.025x** on the same artifact. Enterprise category cover uses the same
basis; location-level warehouse cover keeps its intended attributed rate. The tile now names its
exact 91-day annualisation window, and unit plus live-SQL tests pass. The final activated projection
serves **11.9878x** over **508,800** enterprise on-hand units, rendered as **12.0x**.

---

## BUG-15 · The Ageing Inventory card appears to be warehouse-only `[fixed]`

**Symptom.** The card's five buckets sum to **331,071 units**, which is *exactly* warehouse
on-hand at the latest snapshot (stores hold 149,081; the total is 480,152). An exact six-digit
match is not coincidence.

**Why it matters.** The card sits under a header reading "Enterprise inventory position, risk,
working capital and actions", and its recommended actions — "Markdown / clearance",
"Transfer / promote" — would be read as applying to the whole estate. Store-held ageing stock,
31% of units, is invisible.

**Diagnosis and closure.** The builder read only `inventory_batches`; Gulf batch lineage is
warehouse-scoped even though every positive store snapshot already carries
`oldestReceiptDate`. That source field was discarded by the Business Central adapter. It now
flows through staging and optional canonical `stock_snapshots.oldest_receipt_date`; ageing uses
it only for holding not already covered by a batch, so no cell is counted twice. Any remaining
uncovered holding is retained in an explicit **Age evidence unavailable** bucket with no invented
age or markdown action. A conservation test requires the ageing partition to sum to positive
on-hand, source tests cover the receipt field, and API/UI semantics render unavailable lineage
honestly. The final projection partitions all **508,800** enterprise units into 310,470 / 47,793 /
31,718 / 43,027 / 57,553 across the five measured buckets plus **18,239** explicitly unavailable;
the six rendered cards reconcile exactly to enterprise on-hand.

---

## BUG-16 · Pooled bias hides a cohort with the opposite sign `[fixed]`

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

**Closure.** The forecast summary now reads the accepted `slow_mover` slice at the same additive
market/horizon grain as the headline and serves its bias, actual share and evidence state. The UI
keeps pooled bias visible but places the slow/intermittent cohort beside it, so opposite signs can
no longer imply one action for both populations. API, component and demand-forecast parity tests
cover the cohort fields and unavailable handling. On the final rendered h1-h4 view, pooled bias is
**+1.3268%** while the slow/intermittent cohort is **−22.1252%** and carries **1.3755%** of
actual volume; both signs and the cohort's materiality are visible together.

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

**Closure from the final clean run.** On the exact dense slice (`zero_share_52w < 0.2`) and the
same market/origin/target/horizon aggregation, expected-volume bias is **+1.4778%** and
accuracy is **93.6717%**, versus MA13's **93.6701%**. FVA is therefore **+0.0250%**, while
the unchanged P50 remains at **+13.8317% bias**, **86.0562% accuracy** and **−120.2858%
FVA**. The full portfolio has the larger **+14.7505%** FVA margin because the dedicated cold
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

**Closure.** The retained-data repair first verified without retraining. The final clean authority
`ir_5f4ab51f0677dca7` / `iv_5f4ab51f0677dca7` independently serves
**169,662.3906 units / ₹177.71 Cr**, 3,174 assessed cells and **13 of 13 distributors with
non-zero risk**. The 13 per-distributor values sum exactly to the overview value and are rendered
in crore/lakh-aware currency formatting rather than as the misleading raw ₹23,040-scale figure.

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

**Closure.** Only **514 of 9,081 (5.7%)** evaluated rows now match MA13 at API display precision.
The final live h1-h4 P50 slice has WAPE **33.8853%** (pooled leaf accuracy **66.1147%**) and
bias **+6.7173%**.
Those lower leaf-grain accuracies remain visible because they are real; the fix aligns the
numbers rather than replacing them with the more flattering additive portfolio metric. A live
PostgreSQL regression independently recomputes each displayed P50 forecast, accuracy, bias and
confidence.

---

## Python datagen throughput defects found from the full Gulf run

The common baseline for BUG-23 through BUG-28 is the promoted
`run-95b856f20766c9e1`: **509,417,156 Parquet rows**, 4,814 manifest objects and
**2h53m25.3s** wall time under `performance`. Its pre-manifest telemetry was 3,984.707 s
simulation, 1,357.744 s extensions, 4,163.034 s source publication and 336.016 s DuckDB
mirror; average process CPU was only **110.24%**. The parent peaked at 23,569,793,024
bytes RSS, the market worker at 1,180,909,568 bytes, private temporary work reached
105,844,728,653 bytes and published objects totalled 31,432,437,655 bytes.

These entries do **not** treat the number of `Decimal` call sites or seeded-random calls as
profiling evidence, and they do not pre-authorize a Rust/Go rewrite. Decimal arithmetic,
SHA-256 seed derivation, `random.Random` construction and row-dictionary allocation remain
simulation hypotheses until BUG-28 supplies measurements. The defects below are observable in
the current Python execution path independently of that language decision.

## BUG-23 · Internal partition dates are discarded, leaving 336.6 million rows in seven serial files `[fixed]`

**Where:** `datagen/src/retail_datagen/writer.py:22-49,377-417`; producers including
`generator.py:1361,1857,2634` and `extensions.py:186,229,307,368`.

**Observed.** Seven populated ten-year datasets were each emitted as one Parquet object:

| dataset | rows | objects |
|---|---:|---:|
| `taxLines` | 79,591,427 | 1 |
| `fulfillmentStatusHistory` | 52,792,637 | 1 |
| `salesInvoiceLines` | 40,854,259 | 1 |
| `fulfillmentOrderLines` | 40,854,259 | 1 |
| `fulfillmentLines` | 40,853,500 | 1 |
| `sourceEventCrosswalk` | 40,834,524 | 1 |
| `orderLines` | 40,834,524 | 1 |
| **total** | **336,615,130** | **7** |

That is **66.1% of every Parquet row in the run**. Each `write_dataset` therefore gives
its eight-worker partition pool only one work item for these datasets.

**Root cause.** `resolved_fieldnames` deliberately removes all names beginning with `__`,
then partition selection searches `PARTITION_DATE_FIELDS` only inside that already-filtered
set. `INTERNAL_PARTITION_FIELD = "__partitionDate"` is consequently unreachable even though
the producers populate it. `fulfillmentStatusHistory` has the second form of the defect: its
public time field is `occurredAt`, which is absent from `PARTITION_DATE_FIELDS`, and it has no
internal marker.

**Why it matters.** The configured month partition is not merely failing to use available
parallelism; the physical result contradicts the generator's documented rule that time-bearing
datasets are partitioned. One 40–80-million-row CSV is encoded by Python and converted by one
single-threaded DuckDB connection, which is a credible contributor to the 69-minute publication
stage and the worse NTFS result.

**Required fix.** Resolve the partition key from the original first row before constructing the
public schema. Prefer `__partitionDate` when present, never publish it, and cover every public
time-field spelling (including `occurredAt`) deliberately rather than by accidental fall-through.
Do not make configured worker count affect row membership or order.

**Closure.** A focused writer test proves an internal-only partition key creates the expected
year/month paths while remaining absent from schema and payload. A status-history test covers
`occurredAt`. The Gulf-shaped fixture and a full profile-parity test retain identical logical
rows, controls and ordered row digests across worker counts. The physical object change requires
a generator-version bump/new immutable run rather than reuse of `run-95b856f20766c9e1`; report
before/after per-dataset publication time on macOS and Windows.

**Implemented and measured.** Partition selection now inspects the original first row before
private fields are removed, and `occurredAt` is an explicit public spelling. Generator version
**0.17.0** forces a new immutable run. Internal-marker and status-history fixtures produce the
expected month paths without leaking the marker, and profile parity remains byte-identical. In a
bounded 1,000,000-row benchmark, partitioned and unpartitioned layouts had the same row count and
semantic digest; four-worker conversion wall time improved from **0.3315s to 0.1233s (2.69x)**.
The small fixture's total time was 1.76s versus 1.64s because Python projection still dominates.

**Final full-run measurement.** The seven affected datasets now contain **336,563,988 rows** in
**120 monthly partitions each (840 objects instead of seven)**, with all eight configured
partition workers used. Source publication fell from **4,163.034s to 3,633.529s** (529.5s,
**12.7% faster**). The complete Gulf datagen command took **2h43m07.7s**, versus the authoritative
Gulf baseline's 2h53m25.3s: **10m17.6s / 5.9% faster** end to end. It published 509,349,149
logical rows in 5,842 objects / 31,623,440,797 bytes. Projection remains the dominant substage
and average process CPU is still only 117.72%, which is why BUG-24/25/26 and the aggregate-resource
part of BUG-27 remain explicit performance deferrals rather than being claimed as fixed here.

## BUG-24 · Shopify, Business Central, companion and truth projections are serialized after causal simulation `[deferred — measured no-go for this run]`

**Where:** the blocking source-system loops in
`datagen/src/retail_datagen/generator.py:1167-2671`; `SourceWriter.write_dataset` in
`writer.py:365-584`.

**Observed.** Once simulation and extensions are complete, the generator publishes all Shopify
datasets, then all Business Central datasets, then companion datasets, then hidden truth. The
Gulf run projected 300,237,650 Shopify rows, 96,594,816 Business Central rows, 24,623,470
companion rows and 87,961,220 truth rows through that serial control flow. `write_dataset`
creates a partition thread pool, waits for the entire dataset, destroys the pool, and only then
allows the next dataset to begin. Source publication alone consumed **4,163.034 seconds** while
whole-run CPU averaged 1.10 cores.

**Safe parallelism boundary.** Shopify, Business Central, companion and truth are not independent
business simulations: they must be projections of the same globally sequenced order/inventory
event streams. They become causally independent *sinks only after* those shared events, source
order numbers, allocation results and extension outcomes are fixed. Parallelizing the market/day
state machine or letting projections mint identifiers independently is forbidden.

**Why the existing writer cannot simply be shared between threads.** `SourceWriter.objects`,
`schemas`, `telemetry` and `_spools` are mutable shared collections, dataset CSV names derive from
shared staging state, and several lanes reread the same pickle spools. Naive concurrent calls can
race metadata, oversubscribe disk/memory or multiply full-spool reads without improving throughput.

**Required fix.** Introduce a bounded projection/publication scheduler with isolated lane or
dataset sinks and deterministic parent-side merging of schemas, object registrations and
telemetry. Prefer one-pass partition-local fan-out from the immutable common event stream where
it avoids repeated decoding. Apply one global concurrency/memory budget across lanes and Parquet
workers; the execution profile must cap total work, not grant every lane its own full pool.

**Closure.** Failure remains atomic, object paths and logical row order are deterministic, and
safe/performance/custom profiles produce the same controls and ordered row digests. Race tests
exercise isolated writer ownership and deterministic metadata merge. A representative Gulf
benchmark demonstrates actual overlap and higher aggregate CPU without increasing peak RSS or
temporary bytes beyond the declared budget; retain separate macOS and Windows measurements.

**Decision for the authoritative run.** No implementation joins this run. BUG-28 shows the
bounded writer fixture spends about **93%** of wall time in serial projection/CSV, but it does not
prove that concurrently replaying shared pickle spools improves throughput under one disk and
memory budget. The required isolated-sink scheduler changes failure atomicity and metadata
ownership; landing it without the prescribed race/resource benchmark would trade a measured
performance issue for an unmeasured correctness risk. The new telemetry will supply the full-Gulf
lane evidence for a separate change set.

## BUG-25 · Parquet publication round-trips every row through CSV and then rereads Parquet for the mirror `[deferred — measured no-go for this run]`

**Where:** `datagen/src/retail_datagen/writer.py:422-622,724-879`.

**Observed path.** For Parquet output the writer currently performs:

```text
Python dict -> csv.DictWriter -> staged CSV -> DuckDB read_csv_auto(all_varchar)
            -> DuckDB table -> COPY Parquet -> later read_parquet -> DuckDB mirror table
```

The Python side also allocates a new `public_row` dictionary for every row and calls `fsync`
whenever a staged partition handle is closed. The run retained 31.43 GB of published objects but
reported 105.84 GB of private work at the final measurement point—a **3.37x ratio** that does not
include staged CSV files already deleted after conversion. BUG-28 is needed to separate spool,
sort, CSV and DuckDB contributions, so this ratio is evidence of amplification, not an assertion
that CSV alone owns all 105.84 GB.

**Why it matters.** DuckDB's compression is native, but the publication stage as a whole is not:
Python still filters, copies and text-encodes every value, DuckDB parses that text back into
VARCHAR vectors, and the mirror reads all emitted Parquet again. The extra bytes and parsing are
especially relevant on the measured Windows/NTFS host.

**Required fix.** Prototype fixed-size, schema-pinned columnar batches written directly to
Parquet (or bulk-appended to a bounded native staging engine) without an intermediate CSV when
Parquet is selected. Keep CSV as a supported explicit output mode. Pin row order, row-group size,
writer/version, encoding and compression; either build the mirror from the same bounded staging
representation or retain the Parquet readback until a measured replacement proves safer.

**Closure.** CSV and Parquet modes retain schema and semantic parity, empty datasets remain
schema-complete, and pinned writer/profile tests define the intended byte-determinism scope.
Telemetry proves lower Python CPU, temporary bytes and publication wall time on a representative
fixture and the full Gulf shape. Any writer/layout change receives a generator-version bump and
a fresh immutable run.

**Decision for the authoritative run.** Deferred. The direct writer is not available in the
pinned datagen environment (no Arrow/columnar dependency), and substituting DuckDB row-by-row
append would be a different unbenchmarked bottleneck. The new telemetry quantifies staged CSV,
parse, Parquet, hash and mirror bytes/times separately; BUG-23 removes the proven serial
conversion constraint now. A schema-pinned columnar prototype remains warranted, but not inside
the only full source run before it has CSV/Parquet semantic and cross-platform determinism proof.

## BUG-26 · Pickled row spools are decoded repeatedly, and 41 million ledger rows undergo a Python external sort `[deferred — instrumented, rewrite not authorized by evidence yet]`

**Where:** `datagen/src/retail_datagen/spool.py:14-173`;
`datagen/src/retail_datagen/extensions.py:89-390`;
`datagen/src/retail_datagen/generator.py:345-529,1265-1367,1741-1872,2594-2641,2778`.

**Observed.** `RowSpool` serializes chunks of `list[dict[str, Any]]` with pickle and reconstructs
all dictionaries on every iteration. The 40,834,524-row order-line stream is replayed for commerce
extensions, Shopify lines, Business Central invoice lines/item-ledger projection, hidden-truth
crosswalk and final controls; commerce extensions themselves make separate fulfillment and
tax/return passes. These are repeatable bounded scans, but they are not free or shared.

Business Central adds a distinct amplification. `_bc_item_ledger_rows` appends opening, receipt,
transfer, sale, loss and waste rows by source class, then externally sorts all **41,055,516**
result rows through pickle runs. `RowSpool.iter_sorted` sorts 50,000-row buffers, writes them back
in 1,024-row pickle chunks and performs multi-pass 16-way merges before the writer can partition
or encode the first output row.

**Required fix.** Measure read/write/sort bytes first under BUG-28. Then replace repeated
row-dictionary replay with a typed, partition-addressable spool or a bounded columnar event store
that can feed multiple projections without reconstructing each Python dictionary for every lane.
For item-ledger numbering, prefer a deterministic k-way merge of already date-ordered component
streams; if an unrestricted sort is still necessary, execute it in a measured native external-sort
path with an explicit memory/spill budget.

**Closure.** `entryNumber` and the complete ledger ordering key remain identical when exact logical
compatibility is intended; every downstream projection and manifest control matches ordered row
digests. Telemetry shows how many full spool passes, decoded rows and sort bytes were removed and
demonstrates lower temporary work and wall time without unbounded memory.

**Decision for the authoritative run.** Instrumented and deferred. Every `RowSpool` now reports
flushes, spill bytes, iteration passes/decoded rows/read bytes and time; external sort reports
input bytes, spill bytes, peak temporary bytes, merge passes and time. Those counters are
execution-only and their shape is fixture-tested. Replacing the spool or the 41-million-row
ledger order without first seeing these counters on the corrected partition path would violate
the entry's own measure-first condition, so the rewrite remains a separate benchmarked change.

## BUG-27 · Execution controls bound each spool and configured pool, not aggregate Python resources or effective topology `[partially fixed — topology fixed, aggregate budget deferred]`

**Where:** `datagen/src/retail_datagen/spool.py:21-68`;
`datagen/src/retail_datagen/writer.py:250-310`;
`datagen/src/retail_datagen/generator.py:1061-1110,2715-2754`.

**Observed.** `spoolChunkRows=50,000` is a limit on *each* live `RowSpool`. Simulation, commerce
and supply construction keep many spools alive concurrently, so aggregate buffered Python rows
can be a multiple of that setting with no byte-level coordinator. `memoryLimitGb` is passed to
DuckDB, not enforced as a Python-process/spool ceiling. On this run the parent reached 23.57 GB
RSS while the market worker reached only 1.18 GB.

The same configured-versus-effective mismatch exists for market processes. The Gulf topology has
one market, but `performance` configures `marketWorkers=2`; the branch tests the configured value
and enters `ProcessPoolExecutor` even though telemetry correctly reports only one market worker
can do useful work. On spawn-based macOS and Windows this adds a process boundary and payload
serialization without market parallelism.

**Required fix.** Derive `effective_market_workers = min(configured_workers, market_count)` and
use the direct path when it is one, while retaining configured and effective values separately in
telemetry. Replace independent per-spool row limits with a shared byte-oriented buffer budget or
coordinated flush policy. Define explicitly whether the profile memory value covers DuckDB only or
the complete datagen process tree; if the latter, enforce and measure aggregate rather than
largest-single-process RSS.

**Closure.** One-market fixtures never enter a process pool and remain byte/semantic equivalent;
two-market fixtures still demonstrate real market overlap. Stress tests with many simultaneous
spools stay inside the documented aggregate budget, and safe/balanced/performance settings report
configured workers, effective workers, parent/child RSS and aggregate measurement scope without
changing run identity.

**Partial closure and explicit remainder.** Effective workers are now
`min(configured, market_count)`; a one-market Gulf run takes the direct path and reports configured
workers, effective workers and actual spawned worker-process count separately. Profile parity
passes. Per-spool byte/pass/sort telemetry and a constant-time conservative temporary-disk bound
landed under BUG-28. A shared aggregate Python buffer/RSS governor did **not**: the current
cross-platform process API cannot sample concurrent process-tree RSS, so that field is null with
`CONCURRENT_PROCESS_TREE_RSS_SAMPLING_UNAVAILABLE`. The final run must report the new evidence;
the aggregate-budget redesign remains open rather than pretending DuckDB's limit governs Python.

## BUG-28 · Aggregate publication telemetry cannot identify the dataset, sort or I/O bottleneck `[fixed]`

**Where:** `datagen/src/retail_datagen/writer.py:267-273,576-583,879-881` and
`datagen/src/retail_datagen/generator.py:2673-2754`.

**Observed.** The manifest reports one accumulated `sourcePublicationSeconds=4163.034027`, one
`duckdbMirrorSeconds`, final private-work bytes and per-process CPU/RSS. It cannot answer how much
time or I/O belongs to Python row projection, pickle decode, external sort, CSV emission, handle
flush/fsync, DuckDB CSV parsing, Parquet encoding, hashing or queue wait, nor which dataset owns
the cost. Staged CSV files are deleted before `temporaryWorkBytesBeforeCleanup`, so the retained
105.84-GB measurement is not a peak or a component breakdown. This prevents an evidence-based
choice between Python fixes, native batching and a compiled rewrite.

**Required fix.** Add execution-only telemetry by dataset and substage: logical rows, partitions,
input/spill/output bytes, spool passes, sort time/bytes, projection/CSV-or-batch time, Parquet time,
hash time, queue wait and worker concurrency. Record peak temporary-disk usage and aggregate
process-tree RSS where the OS supports them; use explicit unavailable reason codes elsewhere.
Keep the telemetry out of run identity and semantic fingerprints.

**Closure.** A small deterministic test asserts telemetry shape without asserting unstable wall
times. A representative benchmark reconciles dataset timings to the aggregate stage, accounts for
temporary-byte components, and exposes enough evidence to accept or reject BUG-23 through BUG-27
independently on macOS and Windows.

**Implemented.** Every dataset now reports logical rows, partitions, staged/published/mirror
bytes, projection/CSV, fsync, CSV parse, Parquet encode, partition wall, hash and mirror seconds,
queue basis and effective worker concurrency. Spools and external sorts report their passes,
decoded rows, I/O and spill counters. Peak temporary disk is a constant-time conservative upper
bound from live spool backing, staged CSV, measured sort peak and concurrent output workers; an
early full-tree-rescan implementation was rejected because measurement itself slowed long tests.
Aggregate process-tree RSS is explicitly unavailable/reason-coded rather than misreported as the
largest process. `/executionTelemetry` remains excluded from semantic identity. Telemetry-shape,
writer, profile-parity and the complete **107-test + 17-subtest** datagen suite pass.

---

## Retention and inventory-screen defects found after the clean Gulf run

The historical diagnosis below started from inventory run `ir_2c8feff1e1e9d917`. Final closure
evidence is from `ir_5f4ab51f0677dca7` / `iv_5f4ab51f0677dca7`, built at the
**2026-07-30** inventory origin from clean source run `run-1430a7ddabc5d4ff`. These are
artifact/source reconciliations plus live-SQL/API/rendered-UI checks, not readings inferred from
formatted UI values alone.

## BUG-29 · Combined pipeline retains disposable ingestion work after finalization `[fixed]`

**Where:** `tools/dev.py:2747-2758`; `ingestion/src/retail_ingestion/retention.py:78-151`.

**Observed.** The accepted Gulf publication currently occupies approximately **29 GB raw**,
**16 GB work** and **4.4 GB curated**. The work directory retains `staging.duckdb`,
`retail_v2-candidate.duckdb` and gate copies after the small evidence bundle has already been
finalized. The standalone finalize command supports `--prune-work`, safely writes/verifies the
retention manifest first and has focused retention tests, but the combined pipeline's finalize
step never passes or exposes that option.

**Retention decision.** The immutable raw landing is replay/audit input and must not be silently
deleted at ingestion completion. The work directory is disposable after successful finalization,
provided the curated publication and retained evidence/retention manifest have verified. Thus the
answer is **keep raw; prune work after finalize**. Old raw runs may be removed only under an
explicit run-retention decision, not as an incidental pipeline cleanup.

**Required fix.** Expose a pipeline `--prune-work` control and thread it only into successful
finalization. The final clean run must use it after evidence verification. A failure before that
point must retain work for diagnosis, and pruning must remain scoped to the resolved run directory.

**Run impact.** No datagen, ingestion or ML replay is needed to implement/test this wiring. It
affects cleanup at the end of the one final run and should recover the disposable work footprint.

**Implemented and verified.** `tools/dev.py pipeline` now exposes `--prune-work` and passes it only to the
successful ingestion-finalize step. Finalization still writes and verifies the retention evidence
before removing the resolved run's disposable `work` directory; failures retain work for
diagnosis. The final pipeline used the flag: immutable raw remains **29 GB**, accepted curated data
is **4.5 GB**, retained evidence is 552 KB, and the disposable work root is only its **12 KB**
empty structure. Focused retention and pipeline-command tests pass.

## BUG-30 · In-transit inventory is zeroed for every snapshot except the publication boundary `[fixed]`

**Where:** `ingestion/src/retail_ingestion/transforms/core.py:514-589`.

**Observed at the inventory origin.** The served position contains **188,967 on-order units and
0 in-transit units**. Yet the origin-visible inbound lifecycle has six latest `in_transit` lines
totalling **182 units**; five cells align to the 2026-07-30 inventory snapshot and support at least
**134 in-transit units** after capping by that cell's `incoming_units`.

**Root cause.** `current_in_transit` is reconstructed once from latest shipment status, then the
transform assigns it only where `inventory.snapshot_date = max(snapshot_date)` for the entire
publication. The publication extends to **2026-07-31**, while the inventory decision is
**2026-07-30**. Consequently the selected decision snapshot is treated as historical and every
cell is forced to `in_transit_units = 0`; the same units are moved into `on_order_units`. Every
earlier snapshot has the same forced-zero defect.

**Required fix.** Reconstruct shipment state **as of each inventory snapshot**, bounded by both
`status_effective_at` and `known_as_of`, then split that snapshot's incoming quantity into disjoint
on-order and in-transit buckets. Do not apply today's latest status backwards and do not admit a
future status to an earlier origin. Preserve `on_order + in_transit = incoming` at every cell.

**Closure.** Focused transform fixtures cover dispatched, received and changed-status shipments at
multiple snapshots, including a decision date before the publication maximum. The 2026-07-30 Gulf
rebuild reports the origin-visible aligned transit instead of zero and the position totals
reconcile exactly.

**Run impact.** No datagen is required: the status history already exists in raw/staging. The fix
requires ingestion transform/publication replay and then inventory build/materialize/activate; it
should ride in the one final end-to-end run.

**Implemented and verified.** Transform v1.2.3 reconstructs inbound lifecycle state for
each snapshot using both `status_effective_at` and `known_as_of`, caps it by that cell's incoming
quantity, and preserves `on_order + in_transit = incoming`. Multi-snapshot fixtures cover dispatch,
receipt and late-known status transitions. The final clean projection serves **186,292 on-order +
135 in-transit** units, with transit present in five cells, and preserves the per-cell incoming
identity. Inventory Overview and Warehouse Inventory both render the same ₹59,213.24 transit value.

## BUG-31 · “Damaged / blocked” drops the quality-control bucket `[fixed]`

**Where:** `ingestion/src/retail_ingestion/transforms/core.py:558-579`;
`ml/src/retail_ml/inventory_run/load.py:738-767`;
`db/migrations/versions/0014_warehouse_capacity.py`;
`api/internal/readmodel/inventory.go:2518-2541`.

**What is and is not wrong today.** The 2026-07-30 source snapshot genuinely contains
**0 damaged + 0 quality-control units**, and its warehouse-capacity rows genuinely contain
**0 blocked units**. A correct current-origin screen may therefore still show zero. This is not a
formatter defect and a semantic repair must not invent non-zero stock.

There is nevertheless a real cross-layer defect. On 2026-07-09 the same source contains
**2 damaged + 44 quality-control = 46 blocked units**; on 2026-07-23 it contains
**2 + 51 = 53**. Canonical stock folds `quality_control_units` into `reserved_units`, while the
API's `damagedValueMinor` and warehouse card value only `damaged_units`. Separately, the capacity
loader and serving table publish `capacity_units` but discard source `blocked_units`. The screen
contract explicitly defines blocked stock as **damaged + quality-control**, so the current model
cannot report that measure correctly when it is non-zero.

**Required fix.** Preserve a disjoint blocked/quality-control measure through canonical and
serving semantics, or deliberately map `damaged + quality_control` into the served blocked bucket
while removing quality control from reserved. In either design, ATP and the total unavailable
stock must remain invariant and no unit may be counted in both Reserved and Damaged/blocked.
Warehouse and overview values must share the same definition.

**Scenario decision before the final run.** Correctness does not require a synthetic non-zero at
every origin. If the showcase specifically requires current blocked stock, the Gulf generator must
be given a deterministic final-origin coverage condition; that is a separate datagen scenario
change and must still represent a plausible damage/quality-control event. Otherwise zero is the
truthful current result after this bug is fixed.

**Run impact.** The semantic repair can use existing raw data and needs ingestion plus inventory
rebuild, not datagen. Only the optional decision to guarantee a non-zero final-origin example
requires regeneration.

**Implemented and verified.** Canonical inventory now maps source damaged plus
quality-control stock into one disjoint blocked bucket, keeps safety/reserved stock separate, and
preserves the ATP identity. Warehouse capacity retains its independent source blocked measure.
The Gulf source configuration now uses a deterministic, plausible five-day quality-control hold,
so the final origin demonstrates non-zero blocked stock without inventing UI values. The final
projection serves **42 blocked units / ₹210,777.38**, distributed non-zero across all six
warehouses (7, 8, 11, 6, 5 and 5 units). Overview, warehouse cards, focused transforms and live-SQL
route tests all reconcile, with ATP and unavailable-stock identities preserved.

## BUG-32 · Warehouse Fill Rate is computed from current reorder suggestions, not fulfillment `[fixed]`

**Where:** `api/internal/readmodel/inventory.go:1088-1116,1165-1212`;
`contracts/screens/inventory-replenishment.parity.yaml:143-151`.

**Observed.** The active recommendation artifact has no positive internal recommendation for
Bengaluru, Chennai, Delhi, Kolkata or Mumbai. Silvassa has exactly **one four-unit** positive line.
The API treats those positive recommendations as outbound need and reports how much current stock
could fill them, so five warehouses return `NULL`/Not available and Silvassa alone reports 100%.

**Why it is wrong.** A reorder proposal is neither demand served nor an actual/replay fill-rate
denominator. The screen contract says the measure comes from replay fill by DC. Origin-visible
`store_shortfall_events` already has demand and served units for all six supply nodes over the
trailing 91 days:

| warehouse | demand | served | fill rate |
|---|---:|---:|---:|
| Bengaluru | 2,625 | 626 | 23.85% |
| Chennai | 2,457 | 496 | 20.19% |
| Delhi | 4,046 | 881 | 21.77% |
| Kolkata | 1,940 | 372 | 19.18% |
| Mumbai | 3,228 | 697 | 21.59% |
| Silvassa | 2,536 | 497 | 19.60% |

Those low rates need product interpretation, but they are supported fulfillment evidence; the
served 100%/unavailable pattern is not.

**Required fix.** Freeze the intended window and whether the screen means realised or replayed
service, materialize `demand_units`, `served_units` and fill rate at market × supply-location grain,
and make both the warehouse KPI and rows read that governed projection. A zero denominator must be
Not available with a reason; it must not become 0% or 100%.

**Run impact.** No datagen, ingestion or forecast training is required. Existing curated events
are sufficient; this needs an inventory artifact/serving migration plus API/UI tests and a new
inventory materialization. The final full run will naturally rebuild it.

**Implemented and verified.** Inventory artifact schema v2 now publishes exact
trailing-91-day fulfillment demand and served units by supply node. Migration 0024 carries those
measures to serving, and the API computes `SUM(served) / SUM(demand)` with a null result and reason
for a zero denominator. The final activation exposes non-null rates for all six warehouses:
Delhi **975/4,109 = 23.73%**, Mumbai **685/3,135 = 21.85%**, Bengaluru
**637/2,528 = 25.20%**, Silvassa **510/2,585 = 19.73%**, Chennai
**473/2,513 = 18.82%**, and Kolkata **348/1,940 = 17.94%**. The aggregate is
**3,628/16,810 = 21.58%**. The rendered caption now states the same semantics—“Served units ÷
demand · trailing 91 days”—and focused ML, migration, API and UI tests pass.

## BUG-33 · Expiry & Waste rows value the near-expiry quantity even for realised waste `[fixed]`

**Where:** `ml/src/retail_ml/inventory_run/load.py:230-257`;
`ml/src/retail_ml/inventory_run/build.py:915-986`;
`api/internal/readmodel/inventory.go:1543-1552,1628-1663`;
`ui/src/Inventory.tsx:674-708`.

**Observed.** The active artifact has **1,792 rows**, **0 expiring units**, **332 expired units**
and **396 waste units**. All 332 expired units are already a subset of waste; 64 are other waste.
Accepted unit cost is available for every realised row, valuing expired waste at **₹10.91 lakh**
and all waste at **₹17.10 lakh**. The API correctly admits rows having any of those three facts,
but the table always displays and values `expiring_units`, so every admitted Expired/Written-off
row shows **0 units and ₹0**.

**A second semantic mismatch.** The KPI is labelled “Waste This Month”, while `load_waste` uses a
fixed **91-day trailing window**. The number can be valued, but it is not a monthly number under
the current contract.

**Required fix.** Give each displayed row an explicit fact/status basis. Near-expiry exposure uses
`expiring_units` and its forward exposure value; realised waste uses `waste_units` and accepted
cost, with `expired_units` identified as a cause-specific subset rather than added again. Either
split fact types into separate rows/columns or publish an unambiguous display quantity and value;
do not use status-priority logic that silently drops the other fact. Rename the KPI to the frozen
91-day window or change the loader to a calendar-month window, and retain currency/cost lineage for
realised waste even when there is no expiring exposure.

**Closure.** Artifact, API and UI tests cover near-expiry-only, expiry-caused waste, other waste and
a cell carrying both facts. Row units/value reconcile to the chosen fact, expired is never double
counted inside waste, and the KPI caption matches its exact time window. On the retained Gulf data,
realised waste is non-zero without manufacturing new source rows.

**Run impact.** No datagen, ingestion or forecast run is required. This is inventory build,
serving/API and UI work against retained curated facts; the final full run will rebuild the same
projection once.

**Implemented and verified.** The API ranks cells by the larger of near-expiry
exposure and realised waste while returning separate near-expiry, expired-waste and other-waste
facts and their own accepted-cost valuations. The UI renders those facts in separate columns and
labels the KPI **Waste · Last 91 Days**. Artifact/API/UI fixtures cover every fact combination and
prevent expired units from being added twice. The final artifact has 1,793 rows; the scoped live
view contains **0 near-expiry, 341 expired and 406 waste units across 114 cells**, valued at
**₹17.14 lakh**. Zero near-expiry remains visible as a truthful zero while realised waste renders
non-zero units and value.

## BUG-34 · A region filter blocks the whole Forecast page on the SKU workbench query `[deferred — user-directed]`

**Found during final rendered-UI verification.** The Forecast region selector correctly exposes
eleven Gulf state codes, so BUG-11's Mumbai-only data defect is fixed. However, selecting `TN`
replaces the whole screen with **“Loading the accepted forecast…”** and does not settle in a
reasonable interaction window.

**Exact isolation.** The four filtered routes issued by the React page were timed independently:

| route | result |
|---|---:|
| `forecast/actuals` | 200 in 0.243s |
| `forecast/horizons` | 200 in 0.291s |
| `forecast/stores` | 200 in 0.117s |
| `forecast/series?view=workbench` | no response before the 30s client timeout |

The PostgreSQL workbench statement remained CPU-active after **73 seconds**, with two parallel
workers blocked sending rows. The page makes every forecast query eagerly and treats any one
pending query as a page-wide loading state, so a SKU View dependency prevents even Overview and
Store View from rendering after a filter change.

**Attempt measured and not retained.** Scoping the evaluation and metric CTEs through the already
filtered current-SeriesKey CTE was tested against the live final authority. It still exceeded a
10-second integration deadline, so the speculative rewrite was removed rather than checked in as
a fix. The activated data, API identities and pipeline artifacts were not changed.

**Required diagnosis/fix later.** Capture `EXPLAIN (ANALYZE, BUFFERS)` for the exact bound query and
decide the durable boundary from evidence: an index/access path for SeriesKey actual context,
materialized latest-13-week context, or another governed serving projection. Independently, make
the SKU workbench query tab-scoped so Overview/Store View are not globally gated by data they do
not render. Do not merely extend the request timeout.

**Run impact.** No datagen, ingestion, feature, backtest or inventory run is required. This is an
API SQL/index and UI query-lifecycle fix; a serving migration may be required only if profiling
selects a new index or materialized projection. Closure requires a non-Mumbai region interaction
to render Overview and Store View promptly, the filtered SKU workbench to complete inside a frozen
latency budget, and a live-PostgreSQL regression to prove both scope and timing.

## BUG-35 · Rust accepted product lifecycle dates that Python rejects `[fixed]`

**Found during Rust historical-parity testing.** A deliberately shortened Gulf scenario was
rejected by Python because catalog products launched after the scenario end, while Rust reported
the same document as valid. Rust had decoded the ISO dates but did not enforce Python's three
product lifecycle bounds: launch on/before scenario end, discontinuation on/after launch, and
discontinuation on/after scenario start.

**Impact.** The retained ten-year Gulf config is valid and unaffected, but accepting an invalid
document violates the complete-migration contract and could let Rust generate a different active
catalog rather than fail at the same boundary as Python.

**Implemented and verified.** Rust now enforces all three lifecycle bounds during config loading.
A focused regression shortens the Gulf horizon to 2016-10-20 and proves Rust rejects its future
catalog launches. The standalone checked-in YAML/JSON scenarios remain valid and byte-identical to
their Python counterparts.

### Ruled out in this pass: a small Stock Transfer result set

The original retained artifact genuinely contained three rows. The final clean optimizer produces
**4 rows / 4 SKUs / 294 units across 3 lanes**, with **₹43.49 lakh** transfer value and
**₹35.41 lakh** expected benefit. This remains the accepted output of the governed
optimizer, not an API limit or missing SKU join. Candidate rows must use a declared alternate lane,
the primary DC must be unable to cover the destination, and the alternate donor must retain its
own cover. Several apparent destination opportunities compete for the same donor ATP at the same
SKU; after source conservation, only one can consume it. No bug is logged merely to inflate the
row count. A future UX improvement may expose “3 accepted from N feasible candidates” and rejection
reasons, but widening transfers requires a network/policy or source-data decision, not bypassing
the optimizer.

---

## Re-prioritized order and completion result

This sequence kept the user's Demand Forecast-first decision, resolved every change that could
alter generated/curated/model facts before activation, and left the expensive full Gulf run as
the single final verification rather than a development loop.

1. **Demand Forecast correctness first:** decide and implement BUG-3 + BUG-16 together, then fix
   BUG-9. BUG-3 changes acceptance and therefore must be stable before the final ML run; BUG-16 is
   its served cohort view. BUG-9 is API profiling/optimization and needs no pipeline replay.
2. **Freeze source and inventory semantics:** fix BUG-11, BUG-30 and BUG-31, then BUG-32 and
   BUG-33. Decide at BUG-31 whether a truthful current zero is acceptable or the synthetic scenario
   must guarantee a plausible final-origin blocked event. This is the last point at which datagen
   source semantics may change.
3. **Close the remaining inventory display defects:** BUG-10, BUG-14 and BUG-15. Each must be
   reconciled against retained artifact/curated evidence before changing code.
4. **Instrument before optimizing datagen:** BUG-28 first; then the already-proven partition defect
   BUG-23. Use focused Gulf-shaped benchmarks to decide BUG-24 through BUG-27 individually. Do not
   put an unmeasured projection rewrite or compiled-engine migration into the authoritative run;
   only targeted changes that pass deterministic parity and resource limits may join it.
5. **Make cleanup part of the run:** fix BUG-29 and verify scoped work pruning on a fixture. Keep
   the final raw landing and accepted curated/evidence artifacts; prune disposable ingestion work
   only after successful finalization.
6. **One clean end-to-end run:** after all above code/config/contract changes and focused tests are
   complete, remove the specifically resolved prior run state under the already-approved cleanup
   plan, generate once, ingest once, train/backtest/accept/materialize/activate once, build and
   activate inventory once, run cross-screen/API reconciliations, record stage and total elapsed
   times, then finalize with work pruning. Do not start this run while any source-, acceptance- or
   artifact-shaping decision above remains open.

**Completed 2026-08-09.** The sequence was followed once against clean runtime state. Datagen took
**2h43m07.7s** and the land-through-inventory-entry pipeline took **3h19m03.7s**. Forecast
`fr_546a32b4b120fd7a` / `fv_fe8e951c1f54b89e` and inventory
`ir_5f4ab51f0677dca7` / `iv_5f4ab51f0677dca7` are the unique live authorities. The originally
reported functional/data defects reconcile at PostgreSQL, API and rendered-UI layers. BUG-34 was
then discovered by exercising a non-Mumbai filter and is explicitly deferred at the user's
direction. BUG-24, BUG-25, BUG-26 and the aggregate-resource portion of BUG-27 remain deliberately
deferred performance work; none was smuggled into the authoritative run.
