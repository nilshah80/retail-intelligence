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

## BUG-1 · Slow movers under-forecast by 77%; Croston routed to only 4% `[open — diagnosing]`

**Where:** `ml/src/retail_ml/models/train_lgbm.py` — `_tail_replay_preferred_keys`
(originally suspected `models/intermittent.py` — `croston_beats_seasonal_naive`; ruled out below)

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

## BUG-2 · Replay oracle hard-codes a weekly source cadence `[open]`

**Where:** `ml/src/retail_ml/inventory_run/replay_driver.py`

**Symptom.** `inventory_replenishment_replay` is unavailable for Gulf. The weekly
reconstruction is off by **42.74 units per cell** against a **0.5** tolerance — ~85×
over, and ~86% of the mean store cell position (49.7 units), so not a scale artifact.
`inventory_replay_metrics.parquet` has 0 rows: oracle-first correctly stops before any
policy comparison is scored.

**Root cause (two hard-coded assumptions).**

```python
thursday = origin + timedelta(days=3)   # snapshot weekday assumed
for offset in (4, 5, 6):                # bridge span assumed
```

plus the documented premise that *"every arrival in this source lands Friday 23:00"*.
None of these are derived from the data.

Consequence already hit: Gulf's horizon originally started on a Monday, so all 522 weekly
snapshots landed on Mondays, no period found a Thursday snapshot, `weeksCompared` was 0,
and the oracle produced no measured delta at all — `NO_ORACLE_WEEKS_AVAILABLE`. Worked
around by moving the horizon start to a Thursday (`2016-08-04`), which cost a full
~6-hour regeneration. After that the oracle runs (`weeksCompared: 52`) but still fails
tolerance.

**Remaining hypothesis, NOT yet proven.** Gulf uses `reviewCycleDays: 14` where retail
uses 7; arrivals land in exactly **261 of 522 weeks (50%)**, dispatched Thursday and
received Sunday. A weekly reconstruction against a fortnightly replenishment cycle is the
leading explanation for the residual 42.74, but this has not been demonstrated.

**Proposed fix.** Derive both the snapshot date and the bridge span from the data — read
each period's actual snapshot date from `stock_snapshots` and bridge from it to period
close — so the oracle works for any snapshot cadence and any replenishment cycle.

**Diagnose before fixing.** Instrument the replay to emit per-period deltas and check
whether error concentrates in arrival weeks. Removing the coupling is correct regardless,
but it is not established that it resolves the 42.74 delta.

**Do not "fix" by changing the tenant.** Setting `reviewCycleDays: 7` would make the gate
pass by making the scenario less like Gulf's actual operation — lubricant distributors do
not take weekly depot deliveries. The engine's inability to express a non-weekly cycle is
the defect.

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

## BUG-6 · `retail_ingestion.cli run` replays cached gate verdicts `[open]`

After a Gate A failure, the work root retains `gate-a.json`. A subsequent run with a
*corrected* profile replays the stale `critical` verdict rather than re-running the gate —
Gate A passed standalone while the pipeline kept refusing. The work root must be cleared
by hand after any profile change.

**Proposed fix.** Fingerprint the gate inputs (profile + snapshot) into the cached report
and invalidate on mismatch, or expose `--rebuild` through `tools/dev.py pipeline`.

---

## BUG-7 · `sync_presets.py` strips YAML comments `[open]`

Running it rewrote `multi-market-10-year-demo.yaml` and deleted a P4-11 rationale comment
block explaining why the store replenishment policy was tightened. The tool round-trips
through `safe_load`/`safe_dump`, which is lossy for comments. Pre-existing; worked around
by restoring retail presets from `main` after each sync.
