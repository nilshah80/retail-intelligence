# Phase 4 Implementation Plan — Inventory & Replenishment

_Companion to `plans/local/plan.md`, `plans/local/tasks.md`, and
`plans/local/post-phase3-implementation-plan.md`._
_Specification authority: `docs/demand_forecast_poc_spec.md` §3.3, §4.1, §4.5, §8.2,
§8.3, §10.2, §10.5, §11.1–11.2, and §11.8–11.10._
_Data authority: `contracts/retail_v2/schema.yaml`, `contracts/staging/staging-v2.yaml`,
`contracts/onboarding/temporal-evidence-policy.json`, and the explicitly selected immutable
publication._
_Presentation authority: `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` plus one
approved parity/data matrix per screen._
_Validation authority: `contracts/validation-policy.yaml`; repository CI remains prohibited._

**Revision 10 — 2026-07-31. DRAFT FOR REVIEW. POST-PHASE-3 INTERVAL PUBLICATION AND MIGRATION 0008 ARE NOW
LIVE; PHASE 4 MAY START AT `P4-0` ONLY. RESULT-BEARING PACKAGES REMAIN GATED.**

This plan turns the revised Phase 4 assessment into staged, testable work packages. Creating and
reviewing this plan is planning activity, not Phase 4 implementation. Decision #85 is now a hard,
fail-closed per-cohort P90 gate under acceptance-v5/verifier-v5. Migration
`0007_activation_and_coverage` created that boundary; the applied/current client head is now
`0008_nullable_withheld_interval`. The earlier completed suite totals remain historical evidence,
and the new 0008/publication/API changes require their own final stateful rerun. Decision #87
closed C6/C7 and Decision #91's stop path rejected C8 as the third full-range remedy; Decision #92 instead bounds the
cold-start interval capability to calibrated horizons H1–H4 while retaining P50 at every horizon.

The new implementation closes the former acceptance-versus-serving contradiction. Bundle
`forecast_run_final2` publishes 52,884 current rows, retains P50 everywhere, and withholds P90 and
confidence on exactly 8,756 H5–H26 cold-start rows covering 398 series. Migration 0008 stores the
null pair plus `interval_unavailable_reason`; PostgreSQL has the same counts, Go scans nullable
values and returns explicit availability/reason fields, and activation event 8 supersedes event 7
before event 9 activates the replacement with `prior_event_id = 8`. Exactly one authority is live.

Entry reconciliation is nevertheless incomplete: Go still selects the configured activation scope
without first proving the global active count, no Decision-#73 selection record is discoverable,
and the generated closure record still says migration 0007 even though DB/ML/Go/DB tests require
0008. The v2 closure format also needs an explicit disposition for Decision #93's retained
historical supersession/attestation ledger rather than silently dropping it. The interval contract
still lacks the versioned `cold_start_interval_unavailable` series exception and a fully enforced
availability/reason/nullability truth table: the Parquet row has no explicit availability/reason,
materialization derives the reason from manifest metadata, Go derives availability from P90
nullability, and migration 0008 does not forbid a reason on an available interval. Withholding also
left two served aggregates measuring a mixed population — §1.3.1 records the measurement: at a
26-week selection the workbench confidence for the 398 affected series reads 0.0814 where the
covered weeks give 0.5817, and 372 of them return an interval total below their own central total. It
applies at 8, 13 and 26 weeks, every selection except the 4-week default.
That one is already visible on screen rather than latent, and it is the only residue in this list
that misstates a number a planner can read. `P4-0` closes the authority/selection/closure residue;
`P4-1` completes the bounded contract, repairs the aggregates, and republishes on the final selected
Phase 4 pin. No result-bearing package may consume an interval before those exits pass.

The current immutable bundle is `ml/data/artifacts/forecast_run_final2`, run
`fr_357575f586905b11`, version `fv_3d66e3bd9939430d`. PostgreSQL migration 0008 is applied and the
active view returns exactly that verifier-v5 version. Events 5 and 6 retain retirement of the two
earlier authority-generation-1 scopes; event 7's null-predecessor incident remains immutable,
event 8 supersedes it, and event 9 continues the chain with the bounded replacement. The earlier
rebuilds and deleted C5 generations remain historical evidence, not paths Phase 4 may rediscover or
reconstruct. `P4-0` records this as-built Decision-#93 outcome, corrects closure/selection, and
completes global Go revalidation. `P4-1` finishes the exception and strict contract work and repeats
the frozen bounded publication after the Phase 4 source pin changes.

---

## 0 · Recommendation, status, and approval boundary

### 0.1 Recommended order

The recommended implementation order is:

1. Reconcile the completed Phase 3 implementation with its records: preserve the one live bounded
   v5 authority and events 7→8→9; create the missing source selection; correct the closure
   migration/head and historical-ledger disposition; and implement global Go authority counting.
2. Freeze both §1.3.1 presentation behaviors and clear the `P4-0P` gate: amend Decision #64 (likely
   Q19) and `contracts/screens/demand-forecast.parity.yaml` together, and record approval. This gate
   is small but it is on the critical path — no changed confidence response ships without it, in
   either direction.
3. Treat the former `P4-D0` ordering question as resolved by the implementation: the bounded
   current-pin publication already ran. Proceed with source-only contract/publication work after
   `P4-0`; no result-bearing Phase 4 work is authorized by that ordering.
4. Version the source/canonical contracts for store inventory, typed service lanes, historical
   inbound state, origin-safe supplier terms, and corrected event visibility; generate, publish,
   select, and pin the resulting source run without producing Phase 4 engine values.
5. Retain decision #87's C6/C7 and decision #91's C8 rejection evidence. On the final source pin,
   repeat the implemented decision-#92 withholding and complete the strict availability/reason
   contract plus versioned series exception without reviving C8 as a remedy.
6. Recompute the cold-start `A2_per_cohort` cell over published intervals only — whole-population A2
   keeps scoring all 708,708 rows under decision #92's scope limit — independently verify every
   withheld and published row/exception, and activate only a verifier-v5 bounded bundle whose P50
   remains complete at H1–H26.
7. Freeze the Phase 4 policy, run/acceptance/verifier contracts, OpenAPI, channel policy, replay
   clock, and all 14 screen matrices.
8. Port the reusable M5 engine modules and implement the net-new engines.
9. Run weekly replay plus 5% policy calibration and untouched 95% validation.
10. Publish, independently verify, materialize, and separately activate one inventory/replenishment
    bundle.
11. Deliver the PostgreSQL-only Go read models and 14 React pages, then complete per-page visual,
    DOM, data-value, portability, and human-review gates.

The current-pin bounded publication has already selected the strict branch that `P4-D0` formerly
asked the reviewer to choose. There is no remaining pre-start ordering decision: source-only work
may follow `P4-0`, and the frozen bounded publication must be repeated once on the final source pin.
No engine, replay, policy score, API value, or UI value may consume `yhat_p90` before that final-pin
`P4-1` pass.

### 0.2 Why source remediation precedes the inventory engines

The current pin is sufficient for a meaningful inventory assessment and for several current DC
analytics, but it is not sufficient for the promised multi-echelon replay:

- stock state exists at four DC/MFC nodes and not at the four stores;
- historical fulfillment proves seven store-to-DC service relationships, but those relationships
  are not typed, effective-dated canonical facts;
- current inbound status is visible, but historical `on_order`/`in_transit`/`received` state is not
  reconstructible at arbitrary origins;
- supplier terms are `landing_backfill`, category-only, null-origin, and constant;
- the inventory state is weekly, while the reusable M5 simulator is daily;
- the forecast is store × channel, while echelon-2 replenishment consumes downstream store orders
  or an independently accepted DC-withdrawal forecast.

Building first and fixing these facts later would create plausible but ungoverned reorder numbers.
The source publication, capability selection, accepted forecast, Phase 4 policy, and replay evidence
must form one fingerprinted lineage before any recommendation is trusted.

### 0.3 Current phase gates

| Gate | Current state | Required before |
|---|---|---|
| One current forecast authority | Verified live: exactly one active verifier-v5 row, `fr_357575f586905b11` / `fv_3d66e3bd9939430d`, with 52,884 rows and 8,756 withheld interval rows | Retain through `P4-0`; final-pin replacement in `P4-1` |
| Forecast activation authority scope | Migration 0007 established authority generation 2; current head 0008 is applied. Event 8 supersedes event 7 and event 9 points to 8. Go still reads only the configured scope instead of validating the global active count | `P4-0` |
| Decision-#73 selection for the rebuilt source pin | Still open: no candidate→approved→active source-selection record or selection id is discoverable for `e010c549…` / `fa1bf883…` | `P4-0` |
| Prior C5 generation supersession | The generated v2 closure no longer self-supersedes the current identity, but it drops the former historical supersession/attestation ledger instead of recording its governed disposition | `P4-0` closure reconciliation |
| Phase 3 implementation and suites | Earlier suite completion remains evidence. The v2 closure now derives v5/hard/current-run facts, but hard-codes `servingMigration: 0007_activation_and_coverage` while live DB/ML/Go/DB test pins are 0008 | `P4-0` pin regression and stateful rerun |
| Full safe/performance benchmark comparison | Satisfied: the closure record retains byte-identical Parquet/fingerprint evidence and the reviewed peak-RSS comparison | No remaining gate |
| Decision #85 per-cohort P90 coverage | Hard and active under acceptance-v5/verifier-v5. The scoped H1–H4 cells pass at 0.8603 global, 0.8641 India West, and 0.8571 US New York; the active artifact now performs the matching per-field withholding | Retain; complete exception/truth-table controls in `P4-1` before interval consumption |
| Decision #85 version boundary | Migration 0007 remains the v5 boundary and active-view authority. Migration 0008 inherits it and is the current required head; ML, Go and DB tests name 0008, while the closure generator/record still says 0007 | `P4-0` pin reconciliation, then retain |
| Decision #86 enforcement | Complete in the publication path: structural identity, leakage, display-cell, and bounded report-only criteria all refuse | Retain in every #92 publication |
| Decision #87 cold-start calibration | Closed: C6 and C7 rejected under their frozen criteria; neither may be rescued, retuned, or reused as the Phase 4 remedy | Historical evidence for `P4-1` |
| Decision #91 modelled cold-start P90 head | Decided; C8 is rejected as a full-range remedy after achieving 0.8063 cold-start coverage, below the 0.85 floor. Its outputs remain rejected evidence and are not the bounded H1–H4 serving producer | Historical and model-lineage evidence for `P4-1` |
| Decision #92 interval horizon limit | Decided on instruction and now live for serving fields: 8,756 current rows/398 series are withheld beyond H4; DB/API preserve null plus reason. Remaining gaps are the versioned series exception, exact availability/reason truth table, final-pin repeat, and consumer integration | `P4-1`, `P4-4`, `P4-5`, and every interval-consuming feature |
| Decision #93 Phase 3 closure and serving reconciliation | Decided on instruction. Events 8/9 now satisfy the append-only successor-chain invariant through an actual #92 replacement rather than the planned same-version reactivation. Global Go validation, #73 adoption, closure migration pin, and historical-ledger disposition remain | `P4-0` |
| Decision #88 neutral `location` fields | Decided and implemented as option (a): `location_source_key`, `name`, and `location_kind`; staging-v2 remains unchanged | `P4-2` verification only |
| Decision #89 source snapshot identity semantics | Decided and implemented; the rebuilt pin still matches snapshot, Gate A, Gate B, and publication evidence. Decision-#73 selection remains a separate missing authority step | `P4-0` selection, then retain in `P4-2` |
| Store-grain inventory | Missing | Store Inventory, Stock Health, store transfer/allocation, full replay |
| Typed service lanes | Missing | Multi-echelon resolution and DC dependent demand |
| Historical inbound status | Missing | Replay capability |
| Origin-safe, varied supplier terms | Missing | Replay capability and safety-stock lead-time variability |
| Phase 4 policy v2 and golden vectors | Missing | Engine implementation |
| Phase 4 run/acceptance/verifier contracts | Missing | Publication/materialization |
| Inventory/replenishment OpenAPI | Missing: current OpenAPI has 17 paths and zero inventory paths | API implementation |
| Fourteen frozen screen matrices | Missing: only Data Management and Demand Forecast contracts exist | UI implementation |

### 0.4 Workstream states

| Workstream | State at plan creation | Authorization rule |
|---|---|---|
| `P4-0` Phase 3 entry reconciliation | First authorized Phase 4 package | Finish decision #93 against the as-built events 7→8→9 without rewriting history or immutable bundles |
| `P4-0P` Demand Forecast parity amendment | Gate between `P4-0` and `P4-1`, not a package | Freeze both §1.3.1 presentation behaviors, amend Decision #64 (likely Q19) alongside the versioned amendment to the already-frozen `demand-forecast.parity.yaml`, and record approval before `P4-1` implements the repair; `P4-4` inherits it, and no changed confidence response ships without it |
| `P4-1` decision-#92 bounded interval completion/final-pin publication | Required before interval/result-bearing work | The current-pin field withholding is implemented; complete strict exception/truth-table coverage after the `P4-0P` approval, and repeat once after `P4-3` on the final source pin |
| `P4-2` source and canonical contract vNext | Planned | After `P4-0`; source-only and non-result-bearing |
| `P4-3` new source publication and selection | Planned | After reviewed `P4-2`; source-only before final-pin `P4-1` under the as-built ordering disposition |
| `P4-4` Phase 4 contract freeze | Planned | After `P4-1`; may use reviewed `P4-2` shapes |
| `P4-5` reusable engine foundation | Planned | After `P4-3` and `P4-4` |
| `P4-6` net-new engines | Planned | After foundation golden vectors pass |
| `P4-7` replay and policy acceptance | Planned | After all replay dependencies and engine tests pass |
| `P4-8` publication, DB, and API | Planned | After accepted replay/policy evidence |
| `P4-9` UI parity and Demo 4 | Planned | After read models are live and fail-closed |

### 0.5 Non-negotiable invariants

1. **No interval use before the hard gate.** No Phase 4 inventory/replenishment computation reads or
   derives from P90 until decision #85 is hard and every published-interval cohort cell passes;
   `P4-1` may read interval evidence only to implement and verify decision #92. A withheld interval
   is unavailable, never zero spread. P50 remains usable at every horizon only after the active
   bundle and the consuming feature's own contract authorize it.
2. **Immutable historical evidence.** Retained C5 bytes/manifests are never edited, and missing
   sibling hashes are never reconstructed. Supersession is a new record and activation rule, not
   retroactive mutation.
3. **One current authority, not one row per policy-derived hash.** Historical bundles may retain
   `lifecycleStatus: accepted`; exactly one run may be current, activatable, and active for the
   retailer × tenant × capability × environment × input bundle × feature fingerprint × markets
   authority scope, across every model/classification-policy fingerprint and legacy
   `activation_scope_fingerprint`. Its immutable bundle must exist and pass independent
   verification. A configured Go scope cannot hide a competing active row.
4. **Source-declared lanes.** Service lanes are effective-dated source facts reconciled to
   fulfillment evidence. They are not parsed from `allocations.priority`.
5. **Active-or-residual store coverage.** Store inventory is generated for origin-visible active
   SKU × store cells and for formerly assorted cells that still carry non-zero on-hand, committed,
   reserved, damaged, or in-transit stock. Inactive cells with zero residual state are omitted. A
   fixed 1,422 × 4 Cartesian product remains forbidden; stock existence and demand materialization
   are separate decisions.
6. **No daily interpolation.** Weekly stock evidence produces a weekly replay. A future daily replay
   requires daily source state or an independently approved state-reconstruction contract.
7. **Local-unit quantity math.** Units, MOQ, pack, capacity, cover, and reorder calculations never
   cross currencies. Money is market-local unless an approved as-of reporting conversion is used
   for presentation only.
8. **Cost-weighted ABC.** ABC is based on annualized consumption value
   (`trailing units × 52 × accepted unit cost`), not net revenue and not cross-market nominal money.
9. **No silent store-cost imputation.** Store WAC is computed from accepted store receipt/transfer
   cost evidence. A lane-imputed DC WAC is an explicitly labelled fallback only if separately
   approved.
10. **Current and replay capability are distinct.** Current-snapshot truth cannot be presented as
    historical replay readiness.
11. **PostgreSQL is the serving boundary.** Go handlers never read Parquet or DuckDB. Python verifies
    and materializes immutable bundles transactionally; activation is a separate append-only event.
12. **Read-only Phase 4 product behavior.** Approval, override, assignment, resolution, and ERP-send
    actions are disabled using the approved unavailable behavior. They are not removed and do not
    mutate workflow state.
13. **Element-level unavailable, never fabricated zero.** A screen may preserve an unavailable NRV,
    provision, workflow, or ERP element; it may not invent a value to satisfy visual parity.
14. **Source-neutral implementation.** Retailer/platform variation terminates at approved profiles,
    adapters, and staging roles. No retailer-specific branch enters canonical transforms, ML, API,
    or UI.
15. **Deterministic optimization.** Every tie-break, rounding rule, candidate ordering, seed, and
    cohort assignment is contractually fixed and covered by golden vectors.
16. **Channel is never silently discarded.** Demand and allocation preserve `channel_id` through
    replay. Node-level planning may aggregate only under the approved `P4-D16` contract, and an
    online channel may use DC ATP directly only through an explicit source-declared fulfillment
    lane.

---

## 1 · Verified starting point

### 1.1 What does not exist yet

At plan creation:

- `ml/src/retail_ml/engines/` does not exist;
- no inventory/replenishment run, acceptance, or verifier contract exists;
- database migrations end at `0008_nullable_withheld_interval.py` and contain forecast serving only;
- `contracts/api/openapi.yaml` has 17 paths and no inventory/replenishment path;
- `contracts/screens/` contains only Data Management and Demand Forecast contracts;
- React navigation contains the inventory/replenishment labels, but `App.tsx` supports only
  `demandForecast | dataManagement` pages;
- no current API read model or handler serves a Phase 4 screen.

Phase 4 is therefore a complete vertical build, not an extension of an existing hidden engine.

### 1.2 Forecast authority after Phase 3 completion

The clean-slate chain now publishes and serves one accepted verifier-v5 bundle. At this revision's
verification point:

| Field | Verified state |
|---|---|
| Serving bundle | `ml/data/artifacts/forecast_run_final2` |
| Backtest result | 708,708 rows, 13 origins, H1–H26, `passed: true` under hard acceptance-v5 |
| Current cycle | 52,884 rows at origin 2026-07-27 and 26 horizons |
| Rebuilt features | `ml/data/features/rebuild/weekly_features.parquet` plus manifest |
| Feature identity | `c72ebd9c679fbba4ff8e6f5a9c5f134b02733504ef3d73aa2a7629b9bf229e78` |
| Source snapshot | `e010c5499de1a53cb2d02edbed2c1b0fef350c12f1d30317f495415ecf7cdd09` |
| Curated publication | `fa1bf8834ee9db3111be35ffde5d6b77d4af79c9b4523475e35e462b7a2b02a0` |
| Feature horizons | Exactly integers 1–26 in the feature manifest |
| Forecast publication | run `fr_357575f586905b11`; version `fv_3d66e3bd9939430d`; lifecycle `accepted`; class `gate_remediation` |
| Forecast verification | Local independent `verify_forecast_run` completed without exception |
| Migration/client pins | Applied DB, ML, Go, and DB test name `0008_nullable_withheld_interval`; migration 0007 remains the inherited verifier-v5 boundary. The generated closure record is stale at 0007 |
| Historical activation evidence | Events 1/2 are the two null-predecessor authority-generation-1 activations; events 5/6 retire them; event 7 is the immutable null-predecessor incident; event 8 supersedes 7; event 9 activates the bounded replacement with `prior_event_id = 8` |
| Current local DB projection | Exactly one row: `fr_357575f586905b11` / `fv_3d66e3bd9939430d` |
| Decision-#92 acceptance evidence | The 86,636 rows are excluded from **one cell only** — the cold-start `A2_per_cohort` cohort, which scores 15,752 rows at 0.8603. Whole-population `A2` still scores the full 708,708-row frame at 0.8905 (verified: the scoped 622,072-row set would read 0.9036), and `established_history` keeps all 605,904 rows. The rows are excluded from that cell, not nulled: `forecast_eval_predictions` retains non-null P90/confidence on all 708,708 rows in both the bundle and the projection |
| Decision-#92 served-field evidence | 52,884 rows / 2,034 current served SeriesKeys; exactly 8,756 H5–H26 cold-start rows have null P90/confidence and a DB reason, covering 398 series. Parquet has no row-level availability/reason, Go infers availability from null, the DB allows a reason on a present interval, and the versioned series exception remains for `P4-1` |
| Source authority | Snapshot/publication pin matches, but no decision-#73 selection record is discoverable |
| Closure authority | Generated v2 record matches the active run and v5/hard evidence, but still hard-codes migration 0007 and omits the former historical supersession/attestation ledger without an explicit disposition |

The current bundle is genuinely accepted, independently verified, materialized, field-withheld, and
live. Those facts close the old zero-active, migration-0008 adoption, served-nullability, and event-7
successor-chain blockers. They do not create Decision-#73 source authority, global Go validation,
or a complete exception/closure contract. `P4-0` closes the remaining #93 authority and evidence
work. `P4-1` completes the bounded exception/truth-table contract and republishes it on the final
Phase 4 source pin.

Supersession must distinguish retained evidence from missing evidence:

- the pre-v2 closure ledger retained manifest and acceptance hashes for the older `pitfix_v12`,
  `pitfix_v14`, and `pitfix_v15` generations and for the separately rejected `v6_cohort82` bundle;
- it retained hashes for `forecast_run_v6_c5_final` only among the five C5 siblings;
- the `_c5` (`fr_463f53be6353e481`), `_v2` (`fr_f62041e95fe7c305`), `_grain`
  (`fr_b55046df351c1a65`), and `_gov` (`fr_8e73fb0f8d3c502c`) sibling bytes are gone without
  retained manifest/acceptance hashes.

The four unhashed siblings are superseded by retained run id when available, original directory,
generation label, and reason, with `hashesRetained: false`. A deterministic rerun must never be
used to fill those historical hashes: that would be a reconstruction presented as an original
record. No historical manifest is edited.

### 1.3 Hard coverage gate and bounded serving capability

The current acceptance-v5 bundle makes decision #85 hard. Full-range cold-start coverage remains
outside the band, while decision #92's calibrated H1–H4 published-interval scope passes:

| Scope | Cold-start H1–H26 diagnostic (not gate) | Cold-start published H1–H4 (gate) | Established published (gate) | Required band |
|---|---:|---:|---:|---:|
| Global | 0.784740 | 0.860335 | 0.904699 | 0.85–0.95 |
| India West | 0.805148 | 0.8641 | 0.905414 | 0.85–0.95 |
| US New York | 0.767311 | 0.8571 | 0.904024 | 0.85–0.95 |

Cold-start represents 14.45% of evaluation rows and 22.47% of actual demand volume. Coverage is
row-counted, so these facts establish material under-coverage and under-buffering risk; they do not
quantify a 22.47% stock-out rate or demand-volume miss.

The whole-population coverage passes because established history masks the cold-start failure.
Decision #87 rejected C6 after its frozen ceiling stop and rejected C7 after untouched US New York
confirmation over-covered at 0.9620 while mean cold-start confidence fell 46.9%. Decision #91's C8
dedicated cold-start P90 head then reached only 0.8063 full-range coverage and was also rejected as a
full-range remedy. Decision #92 records the actual capability boundary: the accepted forecast
interval is calibrated at H1–H4 (0.8603 global, 0.8641 India West, 0.8571 US New York) and is
unavailable at H5–H26, where measured coverage declines from 0.8433 to 0.7798. C8 remains rejected
evidence; it is not the H1–H4 serving producer.

Acceptance recomputes the bounded claim over 15,752 cold-start rows and excludes 86,636. Three
distinct operations are easy to conflate under the single word "withheld", and only the first one
changes what any consumer reads:

- **Withheld from publication** — the 8,756 current-cycle H5–H26 cold-start rows whose P90 and
  confidence are null in the artifact, the projection, and the API. This is what a planner and a
  Phase 4 engine consume.
- **Excluded from one gate cell** — the 86,636 evaluation rows removed from the cold-start
  `A2_per_cohort` cohort, which therefore scores 15,752 rows at 0.8603. Whole-population `A2` is
  unaffected today: it still scores the full 708,708-row frame at 0.8905, and `established_history`
  keeps all 605,904 rows. Verified — the scoped 622,072-row population would read 0.9036, and the
  removed 86,636 rows read 0.7965 on their own. Decision #92's scope limit is explicit that "the
  0.85-0.95 band, P50, the established cohort and every published accuracy figure are unchanged", and
  #85 keeps publishing the whole-population figure, so **whole-population A2 stays on all 708,708
  rows**. The 0.9036 published-interval figure may be published only as a separately named diagnostic
  — `published_interval_population_coverage` or equivalent — never as a replacement A2. Substituting
  it would silently raise an authoritative accuracy figure by scoping away the population that
  failed, which requires its own decision, not an implementation choice inside `P4-1`.
- **Not nulled anywhere in evaluation** — `forecast_eval_predictions` retains non-null
  P90/confidence on all 708,708 rows in both the bundle and the projection. The two consequences of
  changing that are different and both unacceptable: *removing* the rows would move A1, A3, A5 and
  the decision-#77 display cells, which score P50 error sums at every horizon, while *nulling* their
  P90/confidence would move A2 and A4, the two gates that read an interval.

PostgreSQL retains the null pair and reason for the published rows, and Go exposes explicit
availability. `P4-1` must still add/reconcile the one-per-series governed exception, enforce the exact
availability/reason/nullability truth table, repair the served interval aggregates in §1.3.1, and
repeat the verified contract on the final source pin. Phase 4 may start with `P4-0`, but no
interval-consuming feature may treat this partial implementation as the final Phase 4 interval
authority.

### 1.3.1 Withholding broke the served interval aggregates

Withholding P90 and confidence while retaining P50 changed the meaning of two aggregates that were
written when every row carried an interval. `api/internal/readmodel/forecast.go:787-794` computes the
workbench row over the selected window `series.horizon_week <= $2`:

```sql
SUM(series.yhat_p90) AS ai_forecast_p90,
SUM(series.confidence * GREATEST(series.yhat_p50, 1.0))
  / NULLIF(SUM(GREATEST(series.yhat_p50, 1.0)), 0) AS confidence
```

`SUM` skips nulls, so the confidence numerator now omits the withheld weeks while its denominator
still counts their retained P50 weight, and `SUM(yhat_p90)` covers only H1–H4 while `ai_forecast`
covers the whole selection. Measured on the live active version over the 398 affected series at
`horizon_week <= 26`:

| Metric | As served | Restricted to the weeks that carry an interval |
|---|---:|---:|
| Series whose `SUM(p90)` is below `SUM(p50)` | **372 of 398** | 0 |
| Mean weighted confidence | **0.0814** | **0.5817** |

`HorizonWeeks` defaults to 4 and is clamped to 26 (`forecast.go:365-369`), and the screen offers
`[4, 8, 13, 26]` (`ui/src/Forecast.tsx:963`). Withholding starts at H5, so only the default 4-week
selection is clean: **8, 13 and 26 weeks are all affected**, and the 8-week selection is one click
from the default. Confidence is rendered in the SKU view
(`ui/src/Forecast.tsx:486` and the export columns), so the understated figure is user-visible today;
the inverted quantile pair is currently API-only in that row.

This is the same defect family as the committed fix that scoped SKU-view accuracy and bias to the
displayed horizon window. Neither the aggregate paths nor their scan types were in `P4-1`'s scope
before this revision; both are now required there.

The two fields need different repairs, because only one of them is a mean. Both, however, need a
frozen presentation choice: a numerically correct number is not automatically an honest one.

- **Weighted confidence is numerically repairable in place, but not silently.** Decision #12 defines
  slice confidence as the `max(P50,1)`-weighted mean of per-row confidence after filters, so
  restricting both sides of the ratio to the weeks that carry an interval is that same formula applied
  to the population where confidence exists. That fixes the arithmetic and leaves a presentation
  problem: at 8, 13 or 26 weeks an affected row would show a column headed "Confidence" computed from
  H1–H4 only, beside forecast values covering the whole selection, and the table renders the number
  alone — publishing scope fields in the payload tells the API consumer nothing the planner can see.
  One of two behaviors must be frozen and parity-amended in the `P4-0P` gate, before `P4-1`
  implements anything:
  1. **Qualified in place**: render the covered horizon and withheld count beside confidence; or
  2. **Unavailable when mixed** (recommended): mark confidence unavailable through the approved
     element-level behavior whenever the selected window mixes published and withheld intervals. An
     unqualified H1–H4 number under a "Confidence" heading is the failure decision #78 exists to
     prevent, and the unavailable state already has an approved rendering.

  Both change what the screen shows, so both require the amendment in `P4-0P`.
- **The interval total is not repairable by filtering at all.** The horizons read model already states
  the governing principle: "a sum of P90 bounds is not the P90 of the sum." Confining
  `SUM(yhat_p90)` to H1–H4 removes the population mismatch but still labels a sum of weekly upper
  bounds as an interval for a multi-week total, which predates #92 and is not made true by scoping.
  Two admissible outcomes, and one must be frozen in the `P4-0P` gate before `P4-1` implements
  anything:
  1. **Unavailable when mixed** (recommended, and freezable immediately): omit the interval total with
     the governed reason whenever the selected window contains a withheld week. It matches the
     element-level convention `P4-D17` and decision #78 already apply, and it needs no parity
     amendment at all, because `aiForecastP90` is carried in the payload and rendered nowhere — it
     appears only in `ui/src/api.ts` and one test fixture. Freezing this one now leaves the confidence
     behavior as the single item needing screen review.
  2. **Renamed and comparable**: return it under a name that states what it is — a sum of weekly upper
     bounds over the covered window — alongside a same-window P50 comparator, and expose the covered
     window visibly. Because this puts a new labelled quantity on the screen, it requires the Demand
     Forecast parity review before any element renders it.

Silently blending two horizon populations in one cell is not among the admissible outcomes for either
field.

Related and in the same edit: `forecast.go` scans this aggregated `confidence` into a non-pointer
`float64`. It survives today only because the window is cumulative from H1 and therefore always
contains a calibrated week; any horizon-range filter — which the `P4-1` truth table and Phase 4
safety-stock work both invite — turns it into a request-time scan error. The row-level series path
already scans nullable values and returns the reason, so only the aggregate paths need the change.

No element may be added, relabelled, or turned into an unavailable state without the Demand Forecast
parity review. Every frozen option above except the interval total's option 1 changes what the screen
shows, so the parity review is on the critical path for this repair rather than optional to it.

The added scope fields are a contract change in their own right. `forecastWorkbenchSchema`
in `ui/src/api.ts` is a plain `z.object`, so Zod strips unknown item keys and any new field is
discarded before a component can read it. Covered-window, withheld-count and reason fields therefore
land in OpenAPI, the generated Python/Go/TypeScript types, and the Zod schema together — which is what
`P4-1`'s existing OpenAPI/types task already requires; this is the concrete list it must cover.

### 1.4 Current inventory and supply evidence

The repinned curated publication remains under logical run directory `run-c5eb1506ecd4c550`, but
the authorized clean-slate rebuild repinned its exact identities: source snapshot `e010c549…` and
publication fingerprint `fa1bf883…`. This was a file-level repin, not a decision-#73 selection: no
`selectionId` is present. The former `db3784fd…` / `681090ee…` pin bytes are gone even though the
logical directory name is unchanged. Equivalence therefore rests on the expected-pin record's
unchanged control totals and ordered row-digest evidence across all 40 entities / 36,224,122
published rows, not on retained old artifacts. `P4-0` must create the missing selection lifecycle
and record the prior pin as a `legacy_unselected_predecessor`; it must not fabricate a superseded
selection that never existed. `P4-1` may append a decision-#92 verifier-v5 activation only after
that adoption is active.

| Evidence | Verified state | Phase 4 use |
|---|---|---|
| `stock_snapshots` | 1,506,240 rows; 1,440 SKUs; four DC/MFC nodes; 522 Thursday snapshots plus 2026-07-28 cutoff | DC position, ATP, cover, weekly replay oracle |
| Store stock | Zero rows at all four stores | Missing prerequisite |
| `sales_fulfillments` | 15,815,976 rows; 1,422 SKUs; 3,653 daily dates / 523 weekly buckets; 100% `native_observed`, but 15,806,271 delivered rows are timestamped known before fulfillment | Diagnostic DC withdrawal/lane evidence only until the placement defect is repaired |
| Fulfilled SKU coverage | All 1,422 ever-fulfilled SKUs occur in stock snapshots | No SKU coverage gap; node gap remains |
| `inbound_shipments` | 196,981 received; 387 in transit; current cutoff split only | Current analytics; not origin replay |
| `suppliers_leadtimes` | 654 rows; category only; lead 5; MOQ 12; pack 6; null origin; `landing_backfill` | Current descriptive term display only; not replay eligible |
| `supplier_performance` | 17,829 rows; lead mean/std, OTD, capacity %, risk; `native_posted_available` | Lead variability and supplier planning |
| `inventory_batches` | 210,970 rows; 103,809 carry expiry | Ageing and expiry where supported |
| `inventory_cost` | 196,918 rows; WAC evidence | DC valuation and receipt-cost lineage |
| `wms_inventory_comparisons` | 1,506,240 rows, exactly matching DC/MFC stock scope | DC-only ERP↔WMS variance; store variance unavailable unless v13 adds reconciled store WMS facts |
| `warehouse_capacity_snapshots` | 2,092 rows | Warehouse capacity/utilization |
| `transfer_orders` | 12,055 DC→DC, all received; `[poc]` rows have no event date or `known_as_of` | Recommendation/output snapshot only; not historical movement evidence |
| `allocations` | 7,471,784 store rows with request/allocation/shortfall | Historical allocation evidence; not a typed lane authority |
| `waste_events` | 7,960 DC rows | Waste evidence; store waste missing |
| `quality_violations` | Governed Parquet and `canonical_data.quality_violations` each contain two published rows: B15 warning and B21 PIT capability downgrade. `publication-manifest.json` incorrectly reports `entityControls.quality_violations.rows = 0` with zero digests because the publisher copies candidate controls, then inserts Gate-B outcomes before export without recomputing controls | P4-2 must make controls cover every exported Gate-B/critical row, or explicitly version a control exemption with its own published count/digest; a 2-row artifact/0-row-control mismatch is forbidden |

At the cutoff, 1,097 SKUs have positive DC on-hand while only 573 SKUs are in current active store
assortment: 524 positive-stock SKUs sit outside the current active set. That is direct evidence that
stock can outlive assortment status. Store generation must therefore preserve analogous
de-assorted residual stock instead of making dead stock structurally impossible.

### 1.5 `sales_fulfillments` is useful but not origin-safe as stored

`sales_fulfillments` is not a pre-aggregated weekly fact. Its canonical grain is the cumulative-
versioned fulfillment line: `(fulfillment_line_id, fulfillment_version)`. The current pin contains
only version 1 rows, but every Phase 4 query must still use the latest origin-visible version under
the cumulative-versioned contract.

Its current placement is defective for Phase 4 replay. `known_as_of < fulfilled_at` on 15,806,271
of 15,815,976 rows—every row whose `carrier_status` is `DELIVERED`—by a median 32 hours and range
8–56 hours. The timestamp was inherited from the parent sale, so filtering only
`known_as_of <= origin` admits fulfillment events before they occurred. Current Gate B B05 checks
this placement class for `sales` only; no ML module reads `sales_fulfillments`, so Phase 3 is not
contaminated, but Phase 4 would be.

Source config v13 must correct the derivation and B05 must require
`known_as_of >= fulfilled_at`. Until that publication exists, diagnostic-only queries use
`effective_visibility_at = greatest(known_as_of, fulfilled_at)` and must label that conservative
derivation. The same rule generalizes to new inbound and transfer status facts:
`known_as_of >= status_effective_at`. The interim maximum is not a waiver that lets a failing source
publication become replay-ready.

After applying the conservative visibility rule, aggregation to week × SKU × supply node provides
a diagnostic DC withdrawal stream across 523 week buckets. It also proves seven observed service
relationships:

| Demand location | Supply location | Units | Share |
|---|---|---:|---:|
| Mumbai Bandra | Mumbai DC | 6,704,299 | 91.3% |
| Mumbai Bandra | Pune Overflow | 637,049 | 8.7% |
| Pune Koregaon | Pune Overflow | 3,665,022 | 91.3% |
| Pune Koregaon | Mumbai DC | 347,450 | 8.7% |
| NY Brooklyn | Brooklyn MFC | 2,879,037 | 90.8% |
| NY Brooklyn | Newark DC | 290,406 | 9.2% |
| NY Manhattan | Newark DC | 5,747,919 | 100% |

This resolves the quantile-aggregation problem without summing store P90s:

- store-echelon replenishment consumes the accepted store × channel forecast;
- DC-echelon operating demand is the downstream store-order stream generated inside replay;
- an independently fitted DC × SKU withdrawal quantile model on corrected, origin-visible
  `sales_fulfillments` is the
  validation cross-check;
- if that DC forecast is ever served or used as authority rather than validation, it becomes a new
  governed forecast artifact with its own acceptance gates.

The typed service-lane contract remains necessary. Fulfillment proves what occurred; it does not
declare the retailer's effective-dated planning relationship or priority order.

### 1.6 Capability status terminology

Two mechanisms currently stop replay:

1. Gate B hardcodes `replenishment.available = false` with
   `HISTORICAL_INBOUND_STATUS_NOT_VERSIONED`.
2. The temporal evidence policy requires `inventory_replenishment` roles at least
   `native_extracted`; `supplier_term` is `landing_backfill`, so the generic readiness evaluator
   returns `unavailable` with `EVIDENCE_GRADE_TOO_WEAK`.

The formal current label is therefore **unavailable**, not automatically **blocked**. The evaluator
uses **blocked** only when a temporal-policy violation such as promoting a business-effective date
into availability is present. Both labels set `consumerMayProceed = false`; the distinction must
remain accurate in evidence and UI.

The proposed v2 capability split does not make the current multi-echelon Phase 4 ready. At most,
the existing pin can show validated-partial DC current-snapshot analytics. Store state and typed
lanes are still absent.

### 1.7 Existing policy is a starting point, not the Phase 4 contract

`contracts/guardrails/policy.yaml` freezes inventory policy v1:

- service levels A/B/C = 0.96 / 0.90 / 0.80;
- review period = 7 days;
- max cover = 30 days;
- calibration = 5%; validation = 95%;
- hold/markdown thresholds.

Resolved-policy v1 vectors and fingerprints already exist, so the earlier statement that no
resolved fingerprint exists is too broad. They do not cover the Phase 4 requirements, and the
India vector uses the older `india-mumbai` market identifier rather than the live `india-west`
scope. This is an executable failure, not cosmetic vector staleness:
`resolve_guardrails("india-west", "INR")` currently raises `GuardrailContractError` because pricing
rules require exactly one market/currency match. The resolver also always returns inventory policy
from `globalDefaults`; it has no inventory market-override merge path. Phase 4 therefore requires a
side-by-side v2 contract and version-aware resolver implementation before policy freeze. V1
artifacts and vectors remain immutable.

Policy v2 must add at least:

- exact ABC basis and cumulative thresholds;
- market/currency resolution for current market ids;
- inventory-position and ATP semantics;
- lane resolution and fallback semantics;
- Monday forecast-week to Thursday snapshot bridge, per-market IANA timezone, and cutoff inclusion;
- channel-to-node demand aggregation, ATP allocation, and direct-DC eligibility;
- supplier-term precedence and null-origin behavior;
- lead-time variability method;
- MOQ/pack rounding and order-up-to caps;
- transfer/allocation objectives, constraints, and deterministic tie-breaks;
- budget ceilings in market-local money;
- replay incumbent identity and exact acceptance math;
- 5%/95% cohort identity;
- valuation basis and fallback labels;
- executable Python↔Go vectors and resolved fingerprints.

### 1.8 Reusable M5 code

Source pin: `../retail_ai @ df1e707f1e4756ec1501420b3f9b5bc4f4143efe`.

| M5 module | Lines | Phase 4 treatment |
|---|---:|---|
| `engines/reorder.py` | 295 | Port and re-contract for retail_v2, local units, policy v2, and weekly horizons |
| `engines/simulator.py` | 1,258 | Redesign daily/store replay into weekly store+DC replay |
| `engines/replenishment_inventory.py` | 653 | Port inventory-position/ATP/DoS primitives |
| `engines/policy_calibration.py` | 233 | Port deterministic 5% calibration with new cohort identity |
| `engines/policy_validation.py` | 169 | Port untouched 95% validation |
| `engines/replenishment_config.py` | 196 | Replace M5 config with policy-v2 resolver |
| `engines/policy_config.py` | 120 | Replace source-local loading with verified contracts |

Total reusable source is 2,924 lines, not a drop-in 2,700-line copy. Every module enters the ML
reuse audit with source hash, adaptation grade, dropped behavior, and covering tests.

No M5 source exists for the transfer optimizer, constrained allocation, ageing/markdown ladder,
expiry/waste engine, NRV/provisioning, ERP↔WMS reconciliation, demand-at-risk, lead-time-variability,
or supplier-risk/OTD logic.

### 1.9 Screen count and scope

The Phase 4 destination count is 14:

- Inventory Overview plus six inventory subpages = 7;
- Replenishment Planner plus five replenishment subpages = 6;
- Stock Health = 1.

`plans/local/tasks.md` currently enumerates only the first 13. The specification explicitly includes
Stock Health in the replenishment cluster. Its Phase 4 scope is the eight-column SKU × store triage
table only. AI-vs-Control and Model Performance belong to the separate Performance Insights page
in Phase 8.

---

## 2 · Authority, scope, and non-goals

### 2.1 Authority hierarchy

When documents conflict, use this order:

1. finalized decisions in `docs/OPEN_DECISIONS.md` and their decision documents;
2. versioned machine-readable contracts and immutable accepted evidence;
3. `docs/demand_forecast_poc_spec.md`;
4. this implementation plan and `plans/local/tasks.md`;
5. reference HTML for layout/presentation only;
6. M5 source as a reuse candidate, never as authority.

This plan records proposed decisions but does not finalize them. A proposed rule becomes executable
only after it is frozen in the applicable decision/contract before result-bearing work begins.

### 2.2 In scope

- source and canonical changes required by multi-echelon inventory/replenishment;
- decision-#91 C8 rejection retention, decision-#92 bounded interval publication, and enforcement of
  the existing decision-#85 hard-gate boundary;
- weekly store+DC inventory replay;
- inventory position, ATP, DoS, ABC, safety stock, reorder, suggested orders;
- transfer and constrained-allocation recommendations;
- ageing, expiry, waste, stock health, valuation, and ERP↔WMS variance;
- supplier capacity/OTD/risk and lead-time variability;
- demand-at-risk and engine-derived exceptions;
- policy calibration/validation and immutable acceptance evidence;
- one read-only inventory/replenishment serving bundle;
- 14 read-only API/UI destinations with approved unavailable behavior.

### 2.3 Explicit non-goals

- mutable approvals, overrides, assignments, notes, SLA clocks, or resolution workflows;
- sending purchase orders or transfers to ERP/WMS;
- daily replay without daily inventory-state evidence;
- pricing elasticity, price recommendations, or promotion optimization;
- AI-vs-Control stores, adoption, drift, or model-performance dashboards;
- cross-market unit math or nominal-money ABC ranking;
- live NRV/provision values without an approved markdown/pricing-floor contract;
- LLM-generated reorder, transfer, allocation, or exception decisions;
- production optimization scale beyond the PoC's accepted bounded scope;
- retailer-specific canonical/ML/API/UI branches.

### 2.4 Artifact retention

- The accepted source pin and every retained forecast/evidence object remain immutable. Already
  missing C5 sibling bytes are documented as missing and never reconstructed as original evidence.
- Candidate source runs, interval candidates, Phase 4 runs, and rejected bundles are retained with
  honest lifecycle status and reason codes.
- A version whose immutable bundle bytes are missing cannot remain active, be re-verified, or be
  used as a rollback target. Retained database descriptors are historical evidence, not a bundle.
- Directory names are never lifecycle authority.
- A supersession record names the old run/version, new authority, reason, decision/policy version,
  and timestamp.
- Materialization and activation records are append-only.
- Temporary work directories may be removed only after their immutable publication/evidence hashes
  are retained and the exact targets are verified.

---

## 3 · Target architecture

### 3.1 End-to-end flow

```text
source config v13 + source-declared lanes/status/terms/store state
  -> immutable landed objects + source controls
  -> adapter roles / staging v2
  -> retail_v2 canonical publication + Gate A/B + readiness v2
  -> active #73 capability selection
  -> hard-gated accepted forecast on the same publication fingerprint
  -> verified Phase 4 input bundle
  -> weekly inventory/replenishment engines
  -> replay + 5% calibration + untouched 95% validation
  -> immutable Phase 4 run + independent verifier verdict
  -> transactional PostgreSQL materialization
  -> separate append-only activation
  -> Go read models over active PostgreSQL views
  -> 14 React pages from frozen parity/data matrices
```

Every arrow is fail-closed and fingerprinted. No later layer discovers “latest.”

### 3.2 Phase 4 run identity

One run identity binds:

- retailer, tenant, environment, and supported markets;
- decision-#89 identity-policy id and byte-determinism exclusion contract;
- source snapshot id, its pinned-writer/execution-profile scope, and curated publication fingerprint;
- canonical schema/control totals and ordered row-digest fingerprints used to prove logical content
  equivalence;
- Gate A/B and readiness-policy fingerprints;
- active #73 selection record id;
- accepted forecast run/version and semantic fingerprint;
- forecast acceptance/recomputation/verifier ids;
- decision-#85 hard-gate mode and cell verdicts;
- service-lane contract/version/fingerprint;
- event-visibility derivation/B05 placement-policy version;
- inventory policy v2 id and resolved per-market fingerprints;
- channel-to-node aggregation/allocation policy and fulfillment-lane fingerprint;
- engine package/version and semantic configuration;
- replay schedule, event clock, incumbent policy id, and deterministic seeds;
- calibration/validation cohort key hashes;
- every output artifact hash and row count;
- execution profile and pinned writer identity; telemetry is evidence, not semantic identity.

A change to any semantic input creates a new run. No run is repointed to a new forecast or policy.
Run identity is not activation authority scope. Decision #90 has frozen the authority key and
supersession semantics before `P4-1` publishes another model policy. The decided authority key is
retailer/tenant/capability/environment + input bundle + feature fingerprint + markets; model and
classification policy fingerprints remain lineage/configuration that create a new run inside that
authority scope, not a permission for parallel active authorities. The active view and Go startup/
revalidation must count across every legacy policy-derived `activation_scope_fingerprint`, fail
closed on zero or more than one row, and require the current activation event to chain its
`prior_event_id` to the superseded event.

Decision #89 is frozen: source snapshot identity hashes every producer-declared byte-stable object,
including restricted objects, and excludes only objects declared `contentDeterminism: logical`, such
as the non-authoritative DuckDB mirror. Permission is not an identity discriminator, and an
inventory containing only excluded objects must fail. Exact source-id reproducibility is proved by
repeated generation under the pinned writer/profile. Safe/performance equivalence is proved
separately by canonical schema, control totals, and canonical ordered row digests—not by assuming
cross-profile byte or snapshot-id equality. The next landing must record the one-time old→new
identity adoption/re-pin before downstream use; host-specific mirror/telemetry hashes remain
regeneration evidence, not snapshot identity.

### 3.3 Capability split

Temporal-evidence policy v2 adds:

| Capability | Purpose | Minimum evidence |
|---|---|---|
| `inventory_replenishment_current_snapshot` | Current position, current order suggestions, descriptive screens | Current reconciled inventory/inbound/terms/lanes; landing evidence may be allowed only when explicitly current |
| `inventory_replenishment_replay` | Origin-safe historical replay and policy validation | `native_extracted` or stronger for every required temporal role plus reconciled demand/lead evidence |

Each publishes independent readiness and sufficiency. `validated_partial` or `unavailable` current
analytics never authorizes replay. Both must be `ready + sufficient` before Demo 4 because replay is
an exit criterion.

### 3.4 Multi-echelon demand

Store and DC demand have different meanings:

- **Store demand:** accepted P50/P90 at store × channel × horizon.
- **Store order demand:** the reorder engine's order stream generated from store state, policy,
  lead/review periods, and store demand.
- **DC dependent demand:** the sum of downstream store orders assigned to that DC through active
  typed lanes, at order-event grain inside replay.
- **Observed DC withdrawal:** latest origin-visible `sales_fulfillments`, using corrected
  `known_as_of` or the diagnostic-only `greatest(known_as_of, fulfilled_at)` fallback, aggregated
  to week × SKU × supply location. It validates the dependent-demand model and can train a
  separate governed DC quantile forecast if later approved.

Store P90s are never summed. An RSS assumption across stores/channels is not silently introduced.
Channel rows remain explicit through replay and are aggregated/allocated only under `P4-D16`.
This is required by current evidence: `allocations` carries store × channel demand while inventory
nodes do not carry `channel_id`, so one node ATP pool can serve multiple channel rows.

### 3.5 Weekly replay clock

The canonical demand/reorder period is the market-local ISO week: Monday 00:00 inclusive to the
next Monday 00:00 exclusive. Inventory snapshots remain Thursday state evidence and must not be
treated as the Monday opening merely because they fall in the same ISO week. For each target week,
derive opening state from the immediately preceding Thursday 23:00 local snapshot and apply every
origin-visible state-changing event between that instant and Monday 00:00. This is a 73-hour bridge
in an ordinary week; implementation uses zoned local instants so daylight-saving transitions are
not forced to 73 elapsed hours. India resolves in `Asia/Kolkata`; US New York resolves in
`America/New_York`.

The closing Monday state is compared to an independently constructed Monday oracle using the same
preceding-Thursday bridge. The raw next-Thursday snapshot remains a secondary reconciliation point.
If the v13 event history cannot construct those Monday openings/closings, replay readiness is not
sufficient; the engine may not instead use the Thursday inside the target week.

Each Monday period has a frozen ordering:

1. select the origin-visible opening snapshot and active policy/lane/term versions;
2. receive inbound/transfer events effective by the review cutoff;
3. expire/block/waste units whose events become effective in the interval;
4. fulfill origin-visible demand subject to available inventory and allocation rules;
5. compute lost units, stock-out state, fill, closing ATP, and financial exposure;
6. create candidate orders/transfers after the period's demand realization boundary;
7. schedule those recommendations using origin-visible lead time rounded under the frozen weekly
   arrival rule;
8. reconcile closing state to the next observed weekly snapshot for oracle runs.

Policy vectors freeze the IANA timezone, Thursday snapshot local cutoff, Monday opening, bridge
interval inclusivity, DST behavior, and whether receipts effective exactly at either cutoff are
opening or next-period events before replay code is scored.

### 3.6 Lane resolution

The canonical lane entity is source-owned and effective-dated:

```text
lane_id
market_id
lane_type                   # replenishment | customer_fulfillment
demand_location_id
channel_id?                  # optional default; exact channel wins
supply_location_id
priority_rank
transit_days
effective_from / effective_to?
known_as_of
known_as_of_evidence_grade
```

Resolution rules:

1. exact demand location + exact channel + effective window;
2. otherwise demand location + null-channel default;
3. exactly one active priority rank 1 per resolved scope;
4. ranks are unique and contiguous;
5. all nodes share market/currency and valid location roles;
6. no self-loop or cycle in the supported replenishment direction;
7. every fulfillment row resolves to an active lane at
   `greatest(known_as_of, fulfilled_at)` until v13's corrected placement is selected;
8. fulfillment from a non-declared lane fails Gate B;
9. observed volume shares validate the declared relation but do not become immutable routing
   targets—real spill behavior may legitimately vary with stock state.

### 3.7 Supply-term resolution

The resolver key is destination plus an explicit origin kind/value plus merchandise scope:

```text
destination_location_id
origin_kind                 # external_supplier | internal_location
supplier_id?                # required for external supplier
from_location_id?           # required for internal location
merch_scope_type            # sku | dept | category
merch_scope_id
effective_from
known_as_of
```

Resolution precedence is:

1. exact origin + SKU;
2. exact origin + department;
3. exact origin + category.

An external null location is a typed external origin, never a wildcard. Internal transfer terms
use an exact `from_location_id` and may reuse lane `transit_days`; ambiguity or multiple equal-
precedence matches fails closed.

### 3.8 Store valuation

Preferred store cost lineage is:

1. external or DC receipt/transfer line carries accepted unit cost;
2. canonical ingestion computes store WAC from those receipt-shaped facts under decisions #6/#7;
3. FIFO is permitted only for batch-tracked inventory with accepted batch lineage;
4. rank-1-lane DC WAC is a separately approved and visibly labelled `derived_lane_wac` fallback,
   never store-observed cost.

ABC uses node-local trailing consumption units × accepted node-local cost. Reporting conversion is
allowed only after node-level classes and values are computed.

Historical store replenishment uses a source-owned movement fact, not the `[poc]`
`transfer_orders` recommendation table. The contract review must either add
`inventory_transfer_events` or an equivalent source-owned entity carrying transfer id, SKU,
from/to location, quantity, status, status-effective time, unit cost/currency, and `known_as_of`.
The current `[poc]` entity has only `transfer_id, sku_id, from_location, to_location, qty, reason,
expected_benefit_minor, currency_code, status`; it has neither an event date nor `known_as_of`, so
it cannot represent historical status in principle. Runtime Phase 4 transfer recommendations
remain a separate output even when their columns look similar.

### 3.9 Publication and serving boundary

The proposed bundle schema is `retail-inventory-replenishment-run/v1`. Its minimum artifacts are:

- `run-manifest.json`;
- `inventory_positions.parquet`;
- `stock_health.parquet`;
- `demand_at_risk.parquet`;
- `inventory_ageing.parquet`;
- `inventory_expiry_waste.parquet`;
- `inventory_valuation.parquet`;
- `replenishment_recommendations.parquet`;
- `safety_stock_segments.parquet`;
- `transfer_recommendations.parquet`;
- `allocation_recommendations.parquet`;
- `supplier_planning.parquet`;
- `replenishment_exceptions.parquet`;
- `replay_metrics.parquet`;
- `replay_acceptance.json`;
- `policy_calibration.json`;
- `policy_holdout_validation.json`;
- `verification.json` or a separately retained verifier record bound to every artifact hash.

Only an independently verified accepted bundle may materialize. Materialization does not activate.
The active view returns exactly one lineage-matching version or nothing.

---

## 4 · Decisions, proposed decisions, and implementation bindings

Each subsection states whether it is already decided or remains a recommendation. A recommended
value is not decided merely because it appears here.

### P4-D0 · Decision-#85 non-interval/source-only carve-out

**Resolved by implementation order:** the current-pin Decision-#92 bounded publication and
migration 0008 have already run. Source contracts, source generation/ingestion, source publication/
selection, screen matrices, OpenAPI/read-model shapes, and inactive DB schema may therefore proceed
after `P4-0` without another ordering decision. The source-only path still forbids:

- reading P50/P90 artifacts in Phase 4 code;
- calculating safety stock/reorder/replay/policy results;
- publishing a Phase 4 run;
- materializing or serving a Phase 4 number;
- presenting sample/static values as live.

The source track may update `expected-pin.json` only after its own capability and selection gates
pass; it may not train, publish, materialize, or activate a forecast. `P4-1` then repeats the frozen
C5/Decision-#92 method once on the final pin, and that final fit may honestly fail a gate the current
pin passed.

### P4-D1 · Decisions #87/#91 rejections and decision #92 bounded interval capability

Decision #87 is historical evidence, not an available implementation choice. C6 was rejected
because 18/52 segments selected `k >= 2.40` and 14 pinned at the 2.50 ceiling. C7 was rejected
because untouched US New York confirmation coverage reached 0.9620 and mean cold-start confidence
fell 46.9%. Do not extend C6's grid, relax the band, refit C7 on confirmation data, or revive either
post-hoc calibration under a new label.

Decision #91's C8 dedicated LightGBM alpha-0.90 cold-start head is also rejected as a full-range
remedy: its untouched result is 0.8063, below the 0.85 floor. Preserve its training-side no-lag-52
cohort, unchanged shared P50, 2,000-row fallback, seeds, features, and per-horizon evidence as
rejected decision evidence. Decision #92 scopes the accepted C5 interval already measured in the
current acceptance-v5 bundle; it does not adopt C8's outputs. Do not describe C8 itself as passing,
bind it into the serving model policy, or refit it after the boundary was selected.

Decision #92 freezes `retail-forecast-interval-availability/v1`: cold-start P90 and confidence are
published only at H1–H4; at H5–H26 they are null with
`interval_available=false` and `interval_unavailable_reason=COLD_START_INTERVAL_UNCALIBRATED`.
P50 stays non-null and fully scored at H1–H26. Decision #85's 0.85–0.95 band applies to published
interval rows, while withheld evaluation/current rows, shares, series, and reason-code digests are
independently recomputed and disclosed. Extending the boundary requires a new preregistered
mechanism; changing 4 as a convenient configuration value is forbidden.

Decisions #92 and #93 were frozen on explicit user instruction. Phase 4 does not reopen either
because a source distribution or implementation detail changes. Decision #92 may be superseded only
by a new preregistered mechanism with untouched evaluation evidence that supports a longer range;
Decision #93 authority semantics require a new recorded decision to change. Recording the as-built
events 7→8→9 is reconciliation of its append-only invariant, not permission to rewrite event 7.

### P4-D2 · Capability policy v2

**Recommendation:** add `inventory_replenishment_current_snapshot` and
`inventory_replenishment_replay` to a new temporal-evidence-policy version. Current snapshot may
tolerate present-time landing evidence; replay requires `native_extracted` or stronger. Preserve
separate readiness and sufficiency fields.

### P4-D3 · Store inventory scope

**Recommendation:** generate weekly store inventory for every origin-visible active SKU × store
assortment cell and every formerly assorted cell with non-zero residual on-hand, committed,
reserved, damaged, or in-transit state at that origin. Prove time-qualified coverage of fulfilled
SKU × store pairs while they are active or still hold residual stock. Add ATP/method, store transfer
receipts/status, waste, and perishable batches where applicable. Do not generate inactive zero-state
cells or a blind full-catalog Cartesian product. A de-assorted cell may retain stock while its
demand materialization is zero under decision #71.

### P4-D4 · DC demand

**Recommendation:** use simulated downstream store orders as operating dependent demand. Use a
fitted DC × SKU withdrawal quantile model from corrected, origin-visible `sales_fulfillments` only
as a validation cross-check.
If that model becomes a served or decision-authoritative input, publish it as a separately accepted
forecast artifact.

### P4-D5 · Replay grain

**Recommendation:** market-local ISO Monday weeks, using the immediately preceding Thursday 23:00
local snapshot plus the origin-visible Thursday→Monday state bridge defined in §3.5. Freeze
`Asia/Kolkata` and `America/New_York` vectors, local cutoff inclusion, and DST behavior. Daily replay
is deferred until daily inventory-state evidence exists.

### P4-D6 · Store cost basis

**Recommendation:** compute store WAC from cost-carrying transfer/receipt facts. Permit rank-1-lane
DC WAC only as a decision-approved, screen-labelled fallback. Never present it as observed store
cost.

### P4-D7 · ABC basis

**Recommendation:** market-local annualized consumption value at both store and DC nodes:

```text
annualized_value_minor = trailing_avg_weekly_units × 52 × accepted_unit_cost_minor
A when share_before_current_sku < 0.80
B when 0.80 <= share_before_current_sku < 0.95
C when share_before_current_sku >= 0.95
```

The SKU that crosses 80% therefore remains A, and the SKU that crosses 95% remains B, matching the
specification and M5 `classify_abc`. Freeze value-tie ordering and missing-cost handling. Net
revenue is not the ABC basis.

### P4-D8 · Stock Health

**Recommendation:** include the SKU × store triage table as destination 14. Keep AI-vs-Control and
Model Performance in Phase 8 Performance Insights.

### P4-D9 · Exceptions

**Recommendation:** publish deterministic, engine-derived, read-only exception rows. Owner, SLA age,
assignment, resolution history, notes, and audit mutations wait for Phase 6. HTML action controls
remain visible and natively disabled.

### P4-D10 · NRV and provisions

**Recommendation:** gross value and ERP↔WMS variance are live in Phase 4. NRV and provision elements
remain unavailable unless an explicit Phase 4 markdown/pricing-floor policy is adopted before
engine implementation. Screen review must explicitly accept the element-level unavailable state.

### P4-D11 · Budget, capacity, and ERP status

**Recommendation:**

- budget ceiling is a market/currency-scoped inventory-policy-v2 field;
- supplier `capacity_confirmed_pct` is an input signal; converting it to a per-order confirmation
  requires a frozen threshold and reason code;
- ERP transmission is `shadow_not_sent` in Phase 4;
- no send path exists, including after action controls render.

### P4-D12 · C5 disclosure and naming

**Recommendation:** Phase 4 entry evidence records C5's target-correlation uplift 0.01402 against the
0.0000–0.0011 honest-candidate band and the 0.02 leakage threshold. Treat it as an accepted,
construction-explained margin, repeat the leakage battery for the new hard-gated run, and do not
misdescribe it as zero concern.

Decision #84's `cold_start_mean` and the historical manifest's `cold_start_baseline` refer to the
same comparator. Preserve historical bytes, publish one canonical name in new artifacts, and make
the verifier's compatibility alias explicit.

### P4-D13 · Replay acceptance math

**Recommendation:** freeze before the first candidate replay:

- one versioned incumbent policy id from the source simulator/config, not inferred from outcomes;
- identical origins, initial states, events, lanes, terms, costs, and cohort keys for incumbent and
  candidate;
- primary service gates globally and per supported market: fewer stock-out periods/lost units and
  fill rate no worse than incumbent;
- lower mean inventory units/value per supported market; any global value gate uses only an
  approved as-of reporting conversion or a frozen dimensionless weighted delta, never nominal INR
  plus USD;
- exact treatment of ties, zero denominators, insufficient cohorts, and missing costs;
- paired SKU × location weekly deltas and a seeded clustered interval published as supporting
  evidence;
- any materiality threshold or non-inferiority tolerance selected before result-bearing runs.

The current plan/task wording provides directions but not exact materiality. It must not be tuned
after observing a candidate.

### P4-D14 · Calibration/holdout identity

**Recommendation:** assign the stable key
`retailer_id × tenant_id × market_id × location_id × sku_id` wholly to calibration or holdout using
a versioned hash and seed. All weeks and channel rows governed by `P4-D16`, plus both incumbent/
candidate rows for a key, remain in the same cohort. Bind both records to the same forecast,
publication, lane, policy, and replay fingerprints.

### P4-D15 · One Phase 4 activation scope

**Recommendation:** one inventory/replenishment bundle owns all 14 read models and one activation
scope. Partial page activation is forbidden. Element-level unavailable state is allowed only where
the approved matrix permits it. This Phase 4 product-bundle scope does not override decision #90's
forecast authority uniqueness and supersession rules.

### P4-D16 · Channel-to-node demand and ATP allocation

**Recommendation:** preserve store × channel forecast rows through replay while inventory position
remains SKU × node. For a node planning scenario, sum channel P50 unit scenarios only as an
explicit additive central-demand scenario; do not call the sum a statistically aggregated P50 and
never sum channel P90. Compute node safety stock from accepted aggregate residual/variability
evidence under policy v2.

When ATP is constrained, allocate from the one node pool to channel rows under frozen priority,
minimum-share, service-class, value-weight, rounding, and tie-break rules. Assert
`allocated + residual = node ATP`, no channel double allocation, and no disappearance of channel
demand. Customer-facing online demand uses store ATP by default. It may draw directly from a DC
only when a source-owned, effective-dated `customer_fulfillment` lane explicitly authorizes the
market × demand location × channel × supply node relation; a replenishment lane or allocation
priority string is not sufficient.

### P4-D17 · Interval consumer degradation and systemic viability

**Decision:** do not constrain v13 supplier lead times merely to keep cold-start protection within
H4. Reorder/safety-stock remains a core feature for rows with an available interval, while
`cold_start_long_horizon_replenishment` is a declared partial sub-capability. Every consumer derives
its required horizon from the selected row's origin-safe lead time plus review period; the current
landing-backfill fixture's 5 + 7 days resolves to H2, but that is only a fact about the current pin,
not a generation constraint or a promise about v13.

For an H5+ cold-start row, skip only the interval-dependent recommendation, retain P50 where central
demand is independently authorized, and emit/project one governed
`cold_start_interval_unavailable` exception with horizon, consumer, and lineage evidence. Never
coerce null P90 or confidence to zero. If 100% of the cold-start SeriesKeys or cold-start demand in
any supported market is skipped, mark that market's cold-start replenishment sub-capability
`unavailable`; the broader replenishment capability remains explicitly partial for its supported
rows rather than silently passing. If no recommendation row remains for a market, the whole market
consumer is unavailable. P4-4 may freeze stricter pre-result count/share/demand-share limits, but it
may not weaken these floors after replay results are visible.

---

## 5 · Deliverables

### 5.1 Entry and source deliverables

| Deliverable | Owning layer |
|---|---|
| Reconciled authority target/retirement record, followed by one verifier-v5 current authority | contracts/evidence + ML/DB/API |
| Decision #90 completion: migration/client alignment, cross-scope activation chain, and Go fail-closed rule | docs + ML + DB + API |
| Decision #93 reconciliation: retained events 7→8→9, authority-wide Go validation, #73 selection lifecycle, migration-0008 closure pin, and historical attestation-ledger disposition | docs + contracts/evidence + ingestion + ML + DB + API |
| Decision #87/#91 rejection records, decision #92 interval-availability policy, strict nullable artifact contract, exception-policy v2, and hard-gate evidence | docs + contracts/ml + ML + DB + API |
| Source config/spec v13 | datagen |
| Typed `service_lanes` canonical entity and staging role | contracts + ingestion |
| Historical inbound status observations | datagen + staging + retail_v2 |
| Active-or-residual store inventory/receipt/waste/batch evidence | datagen + ingestion |
| Origin-safe, varied supplier terms | datagen + ingestion |
| Capability policy/readiness v2 | contracts/onboarding + ingestion |
| New immutable publication, selection, and expected pin | ingestion + contracts/ml |
| Refit, hard-gated accepted forecast | ML + DB + API evidence |

### 5.2 Phase 4 contract deliverables

| Deliverable | Minimum content |
|---|---|
| Inventory policy v2 | All `P4-D*` executable decisions, resolved fingerprints, golden vectors |
| Run schema v1 | Immutable identity, artifact inventory, lifecycle, PIT/capability state |
| Acceptance schema v1 | Replay, policy holdout, sufficiency, per-market verdicts |
| Verifier policy v1 | Independent recomputation and artifact checks |
| OpenAPI | Version/lineage endpoint plus 14 screen read models and 409/503 semantics |
| Screen contracts | 14 parity/data matrices with unavailable and action behavior |
| Evidence schemas/records | replay acceptance, policy calibration/holdout, readiness, activation |

### 5.3 Engine deliverables

- verified input-bundle loader;
- policy-v2 resolver;
- inventory position/ATP/reconciliation;
- ABC and valuation;
- weekly safety stock/reorder/order-up-to;
- MOQ/pack/cover/budget/capacity guards;
- weekly multi-echelon replay;
- 5% calibration and untouched 95% validation;
- transfer optimizer;
- constrained allocation optimizer;
- ageing/markdown, expiry/waste, and stock health;
- supplier risk/OTD and lead-time variability;
- demand-at-risk and read-only exceptions;
- artifact publication, independent verification, telemetry, and CLI commands.

### 5.4 Serving and UI deliverables

- Alembic projection/materialization/activation migrations;
- fail-closed active inventory/replenishment view;
- framework-neutral Go read models;
- PostgreSQL-only handlers;
- 14 React pages using the shared shell;
- desktop/mobile parity, DOM/token/data-value tests, and human sign-off per page.

### 5.5 Traceability to the Phase 4 task ledger

This table maps ledger requirements to work packages only. The authoritative artifact → screen →
endpoint mapping is frozen under `P4-4`.

| Task-ledger requirement | Work package |
|---|---|
| Reorder/safety stock | `P4-5`, `P4-7` |
| 5% calibration / 95% validation | `P4-5`, `P4-7` |
| Multi-echelon state, ATP, inbound, batches/ageing | `P4-2`, `P4-3`, `P4-5`, `P4-6` |
| Supplier term precedence and null-origin rule | `P4-2`, `P4-4`, `P4-5` |
| ABC/market-local valuation | `P4-4`, `P4-5`, `P4-6` |
| Transfer and allocation optimizers | `P4-6`, `P4-7` |
| Replay acceptance and demand-at-risk | `P4-6`, `P4-7` |
| Screen matrices and 14 pages | `P4-4`, `P4-9` |
| Read-only Go API | `P4-8` |
| Per-page parity and human review | `P4-9` |
| Demo 4 exit | `P4-9` and §15 |

---

## 6 · Proposed file layout

Names are proposed; schema/version ids are authoritative once frozen.

```text
docs/
  decision-85-per-cohort-coverage.md
  decision-87-cold-start-interval-calibration.md
  decision-88-neutral-location-role-fields.md
  decision-89-source-snapshot-identity.md
  decision-90-forecast-activation-authority-scope.md
  decision-91-modelled-cold-start-p90-head.md
  decision-92-cold-start-interval-horizon-limit.md
  decision-93-phase3-closure-and-serving-reconciliation.md
  OPEN_DECISIONS.md                      # amended in P4-0P: Decision #64 gains Q19 or a superseding entry

contracts/
  ml/
    forecast-classification-policy-v2.json
    forecast-run.schema.yaml
  onboarding/
    temporal-evidence-policy-v2.json
  guardrails/
    inventory-policy-v2.yaml
    resolved-inventory-policy-v2.json
  inventory/
    run.schema.yaml
    acceptance.schema.json
    verifier-policy.json
    golden-vectors.json
  screens/
    demand-forecast.parity.yaml          # amended in P4-0P, not created: frozen contract + versioned amendment
    inventory-overview.parity.yaml
    store-inventory.parity.yaml
    warehouse-inventory.parity.yaml
    inventory-ageing.parity.yaml
    stock-transfers.parity.yaml
    inventory-valuation.parity.yaml
    expiry-waste.parity.yaml
    replenishment-planner.parity.yaml
    suggested-orders.parity.yaml
    supplier-planning.parity.yaml
    safety-stock.parity.yaml
    allocation-fulfillment.parity.yaml
    replenishment-exceptions.parity.yaml
    stock-health.parity.yaml
  evidence/
    publication-selections/
      retailer-demo-demand-forecast-local-candidate.json
      retailer-demo-demand-forecast-local-approved.json
      retailer-demo-demand-forecast-local-active.json
    candidate-c6-result.json
    candidate-c7-result.json
    candidate-c8-result.json
    decision-92-bounded-interval-result.json
    phase4-entry-record.json
    inventory-readiness-record.json
    replay-acceptance-record.json
    policy-calibration-record.json
    policy-holdout-record.json
    inventory-serving-record.json
  api/openapi.yaml
  retail_v2/schema.yaml
  staging/staging-v2.yaml
  staging/role-map.yaml

datagen/
  configs/...
  src/retail_datagen/...

ingestion/src/retail_ingestion/
  readiness/...
  quality/gate_b.py
  transforms/...

ml/src/retail_ml/
  policies/
    interval_availability.py
  engines/
    abc.py
    allocation.py
    ageing.py
    demand_risk.py
    expiry_waste.py
    inventory_position.py
    lead_time.py
    policy_calibration.py
    policy_config.py
    policy_validation.py
    reorder.py
    replenishment_config.py
    simulator.py
    supplier_risk.py
    transfer.py
    valuation.py
  inventory_publish/
    artifacts.py
    verify.py
  serving/inventory_postgres.py

db/migrations/versions/
  0007_activation_and_coverage.py
  0008_nullable_withheld_interval.py
  0009_*_forecast_interval_contract_completion.py
  0010_*_inventory_replenishment_serving.py

api/internal/
  inventory/
  replenishment/
  readmodel/
  httpapi/

ui/src/
  inventory/
  replenishment/
```

Migration 0008 is applied and must not be rewritten to finish the stricter contract. `P4-1` uses
0009 for the explicit availability/reason truth table, so `P4-8` inventory serving begins at 0010.
If Alembic head changes again, later numbers advance; semantic migration purpose does not.

---

## 7 · Work packages

### P4-0 · Reconcile Phase 3 lineage and authorize Phase 4 prerequisites

**Entry:** completed Phase 3/Post-Phase-3 implementation and prior cross-stack suites; immutable
accepted bundle `forecast_run_final2`; one live verifier-v5 authority
`fr_357575f586905b11` / `fv_3d66e3bd9939430d`; applied migration 0008 aligned across DB/ML/Go/DB
test; retained duplicate-at-entry history; events 7→8→9 forming the current successor chain; no
discoverable Decision-#73 selection; configured-scope-only Go validation; and a generated v2
closure record whose migration pin and historical-ledger disposition remain incomplete.

**Tasks:**

1. Retain the full authority history: authority-generation-1 active events 1/2, their append-only
   supersession events 5/6, event 7's null-predecessor incident, event 8's supersession of 7, and
   event 9's bounded active replacement pointing to 8. Never edit event 7 to make history look clean.
2. Verify the current bundle, database row, and API configuration all identify
   `fr_357575f586905b11` / `fv_3d66e3bd9939430d`, publication `fa1bf883…`, feature
   `c72ebd9c…`, 52,884 current rows, 2,034 current served SeriesKeys, 708,708 evaluation rows, and
   exactly H1–H26.
3. Retain the completed suite totals and commands as linked evidence. Do not rerun Windows/Linux,
   visual, retrospective, Track-A, or safe/performance work merely because stale strings remain if
   their actual completion artifacts exist; if an artifact does not exist, the summary is not a
   substitute and that evidence remains open.
4. Create the three immutable decision-#73 candidate→approved→active documents decided by #93 for
   `retailer-demo × tenant-demo × demand_forecast_non_pit × local`. They share one derived
   `selectionId`, chain distinct lifecycle record ids, and bind the real retained readiness
   fingerprint. Record the prior pin as `legacy_unselected_predecessor`; do not fabricate a
   historical superseded selection.
5. Verify that those selection documents bind the rebuilt source
   snapshot `e010c549…` / publication `fa1bf883…` at the required demand capability and supported
   scope, Gate A `59456631…`, Gate B `cdb41e02…`, and object count 2,069. Bind the expected-pin
   control-total and row-digest equivalence evidence. File replacement is not activation.
6. Keep migration 0007 as the inherited verifier-v5/active-view boundary and require current head
   `0008_nullable_withheld_interval` across DB, ML, Go, DB test, closure generator, and closure
   record. Add an executable regression that fails on any cross-file pin disagreement or regression
   to 0007/0006 as the current required head.
7. Make Go count and validate the entire `active_forecast_versions` projection at startup and
   per request before resolving the configured fingerprint. Zero or more than one row fails closed;
   the configuration may select the one proven row, never hide another.
8. Reconcile Decision #93 to the append-only as-built result: event 8 superseded event 7 and event 9
   activated the real #92 replacement with a non-null predecessor. Do not append a redundant
   same-version reactivation now or reactivate the interval-incomplete version. Add regression
   coverage that every future replacement continues from the currently active event through a
   supersession event and never mints another null-predecessor authority-generation-2 chain.
9. Reconcile `forecast-closure-record.json` and its generator: current v5 verifier/acceptance ids and
   hashes; hard A2 mode; migration 0008; current materialization/activation; no stale
   `stillRequired`/`openEvidence` item without an explicit Decision-#93 disposition; no served
   run/version inside `supersededIdentities`; and an explicit retained reference or governed
   disposition for the historical supersession/attestation ledger removed by the v2 simplification.
10. Replace each former open item with a linked completion artifact, the explicit user attestation
    classification, or the decision-#85/#92 served-field transfer to `P4-1` exactly as decided in
    #93. Do not call attested Windows/Linux/Track-A evidence `locally_verified` unless its retained
    execution artifact exists.
11. Preserve all five earlier superseded run ids and four earlier version ids exactly once, including
   retained versus missing bundle/hash status. Never reconstruct deleted bytes or hashes.
12. Reconcile `candidate-c5-result.json`, the Post-Phase-3 plan, and Phase 4 entry evidence to the
    current served identity while retaining historical ids and the no-accuracy-improvement claim.
13. Record the implemented #92 state explicitly, keeping the two operations distinct: 8,756 of 52,884
    current rows across 398 cold-start series are **withheld from publication** with matching
    PostgreSQL null/reason counts, while 86,636 evaluation rows are **excluded from the cold-start
    `A2_per_cohort` cell only** — that cohort scores 15,752 rows at 0.8603, whole-population A2 still
    scores the full 708,708-row frame at 0.8905, and all 708,708 evaluation rows keep non-null
    P90/confidence. Also record the missing series exception, the §1.3.1 served-aggregate defect, and
    the strict truth-table work handed to `P4-1`.
14. Run the complete stateful local gate against migration 0008 and the selected one-live authority;
    confirm API `dataMode: live` and nullable interval serialization while Phase 4 interval
    consumers remain disabled until final-pin `P4-1`.

**Required evidence:**

- decided #90 record plus executable authority-scope, events-7→8→9 successor-chain, global-count, and
  concurrent-activation vectors;
- finalized migrations `0007_activation_and_coverage.py` and
  `0008_nullable_withheld_interval.py`, matching Python/Go/DB/closure required-head evidence,
  v5-only active-view evidence, nullable-interval constraints, and upgrade/downgrade evidence;
- retained before/after evidence for the duplicate active state and its repair;
- exactly one selected authority target across input bundle + feature fingerprint + markets,
  independent of model/classification-policy or legacy activation-scope hash;
- three immutable decision-#73 lifecycle documents sharing one selection id, chaining distinct
  record ids, and naming the prior pin only as `legacy_unselected_predecessor`;
- event 7's immutable null-predecessor incident plus events 8/9, ending in one bounded active event
  with a non-null predecessor;
- `fr_9aaa1d4431381570` / `fv_efcbbc03d991007f` recorded with
  `bundleBytesRetained: false`, non-current status, and activation/rollback refusal evidence;
- API live evidence on exactly one active row plus governed-unavailable evidence for zero/duplicate
  fixtures, using global-count rather than configured-scope-only validation;
- accepted final manifest with run `fr_357575f586905b11`, version
  `fv_3d66e3bd9939430d`, exactly 26 integer horizons, and no directory path as authority;
- retained independent-verifier success for the immutable final bundle;
- supersession records for every earlier C5 run, explicitly distinguishing retained and missing
  hashes;
- verifier/activation refusal evidence for every non-current C5 identity still presented;
- closure record with no current/superseded semantic collision;
- a closure record whose Phase 3 completed-evidence links and v5/hard metadata agree internally;
- a recorded decision-#92 served-field implementation plus its remaining exception/truth-table gap
  handed to `P4-1`;
- relevant authority changes committed and reviewable.

**Exit:** decision #93's authority/evidence invariant is fully reconciled: Phase 3 implementation,
closure evidence, source selection, and serving lineage agree on one live bounded v5 authority;
events 7/8/9 are retained; both authority-generation-1 activations remain retired; all required-head
clients and the closure record agree on 0008; Go validates globally; and the remaining #92
exception/truth-table work is gated to final-pin `P4-1`.

**Stop:** if migration clients disagree, more than one authority is active, global Go validation is
absent, events 7→8→9 do not verify, the final bundle fails verification, source selection is absent,
or claimed completed evidence has no artifact, keep result-bearing Phase 4 gated. Do not edit event
history, choose a configured winner, reactivate the interval-incomplete version/v4, reconstruct
deleted bytes, or clear evidence strings without linking the completion evidence.

### P4-0P · Demand Forecast parity amendment (gate, not a package)

**Entry:** `P4-0` complete; §1.3.1's measurement recorded.

This gate exists because the presentation repair touches an **already frozen** screen contract.
`P4-4` cannot ratify it: `P4-4` enters after `P4-1` and its scope is the 14 new Phase 4 matrices, not
`contracts/screens/demand-forecast.parity.yaml`. Freezing a behavior in `P4-1` and ratifying it in
`P4-4` would implement a screen change before its contract existed.

**Tasks:**

1. Freeze the interval-total behavior. The plan recommends §1.3.1 option 1 — absent with the governed
   reason whenever the window is mixed — which changes no rendered element and can be frozen here
   without a screen amendment.
2. Freeze the confidence behavior. The plan recommends *unavailable when mixed*: an unqualified
   H1–H4 number under a "Confidence" heading beside full-window forecast values is the failure decision
   #78 exists to prevent, and the approved element-level unavailable state already has a defined
   rendering.
3. Amend `contracts/screens/demand-forecast.parity.yaml` for the frozen confidence behavior — the
   affected cell, its unavailable rendering, the governed reason surface, and the 4/8/13/26 selection
   matrix — as a versioned amendment to a frozen contract, not a silent edit. The file's
   `reviewGate.resolvedDecision` block carries Q1–Q18 and `pendingDecisions: {}`, so the amendment
   lands as a new resolved entry rather than an edit to an existing answer.
4. **Amend the governing decision, not only the file.** Decision #64 freezes that YAML as the
   machine-readable UI authority with Q1–Q18 enumerated — including "selected-horizon workbench sums",
   which is precisely the semantics this repair changes. Record a dated Decision #64 amendment, most
   naturally Q19, or a new superseding decision, naming both the chosen confidence behavior and the
   chosen interval-total behavior. Amending the contract while its registry entry still freezes only
   the old semantics would leave the authority split between two documents.
5. Obtain and record explicit human approval of that amendment, naming the measured defect it repairs.
6. Record the decision/amendment id, the approval id, both frozen choices, and the amended contract's
   fingerprint in the Phase 4 entry record, and keep `docs/OPEN_DECISIONS.md` and the YAML
   synchronized — neither may carry a semantics the other does not.

**Required evidence:** the dated #64 amendment or superseding decision, the versioned parity
amendment, its approval record, the amended contract fingerprint, and both frozen choices bound into
the entry record before `P4-1` task 9 begins.

**Exit:** `P4-1` may implement the repair, and `P4-4` inherits an already-approved amendment instead
of ratifying a shipped change retrospectively.

**Stop:** if the decision amendment and parity approval are not both recorded, non-serving
implementation and isolated tests may proceed, but `P4-1` task 9 cannot reach its serving/activation
exit and **no changed confidence response may ship** — in either direction. Returning the corrected
value changes the number the screen shows; suppressing it changes that cell to an unavailable state.
Both are presentation changes, so neither is available as a fallback. The only shippable state without
the amendment is the one already live: the diluted number, which is why this gate is on the critical
path rather than beside it.

### P4-1 · Complete decision #92 and publish it on the final Phase 4 source pin

**Entry:** `P4-0` and the `P4-0P` parity-amendment gate complete, with both §1.3.1 presentation
choices frozen and the Demand Forecast amendment approved; the source-only `P4-2/3` track complete;
decisions #85, #86, #90, and #92
decided; decision #87 closed with C6/C7 rejected; decision #91's C8 rejected as a full-range remedy.
The current-pin bounded authority proves the publication/migration/API path and is the comparator;
it is not the final Phase 4 authority because the source pin will change and its series-exception/
truth-table contract is incomplete.

**Tasks:**

1. Retain executable C6, C7, and C8 rejection evidence. C8's 0.8063 full-range result remains a
   rejection and is not adopted for H1–H4 serving.
2. Bind `retail-forecast-interval-availability/v1`, maximum horizon 4, reason code
   `COLD_START_INTERVAL_UNCALIBRATED`, the accepted C5 model identity, the rejected #91/C8 evidence
   reference, and the unchanged P50 method into run/version lineage, manifest evidence, and the
   independent verifier.
3. On the existing selected pin, preserve the accepted C5 P50/P90 values byte-for-byte before field
   withholding. On a later Phase 4 source pin, refit only the frozen C5 base's 52 market × horizon
   weights as already authorized; do not fit or substitute the rejected #91 head, reopen decision
   #74's configuration cap, or reread confirmation to select a mechanism.
4. Retain and regression-test the now-live invocation of
   `withhold_uncalibrated_cold_start_intervals` before current-artifact canonicalization,
   fingerprinting, export, verification, and materialization; repeat it on the final source pin.
5. Version the current-forecast artifact/schema so `interval_available` and
   `interval_unavailable_reason` are required. Permit null P90/confidence only when availability is
   false with the exact reason; reject null with true/missing availability, non-null interval fields
   with false availability, P90 below P50 when available, and any null/non-finite P50. Add
   `0009_*_forecast_interval_contract_completion.py` to backfill/store the explicit availability
   field and enforce the two valid row states; do not edit already-applied migration 0008.
6. Keep evaluation rows for A1, A3, A4, A5 and display-cell scoring at every horizon. Scope **only**
   the cold-start `A2_per_cohort` cell to published intervals; whole-population A2 keeps scoring all
   708,708 rows, because decision #92's scope limit leaves every published accuracy figure unchanged
   and #85 keeps publishing that figure. The published-interval population may appear only as a
   separately named diagnostic, never as a replacement A2; substituting it needs its own decision.
   Independently publish total, cohort, market, horizon-band,
   withheld-row, withheld-series, share, and demand-share counts/digests so gate scoping cannot hide
   the withdrawn population.
7. Version the exception classification policy to add `cold_start_interval_unavailable`. Emit one
   source-of-truth forecast exception per affected series, not 22 horizon duplicates, because the
   existing table key has no horizon. Canonical evidence records `calibratedMaxHorizon: 4`,
   `unavailableFromHorizon: 5`, `unavailableThroughHorizon: 26`, reason code, decision/policy ids,
   and affected row count. `replenishment_exceptions` may project/link this record but must not mint
   a contradictory duplicate classification.
8. Version the forecast manifest/schema and policy fingerprints for the new exception and interval-
   availability contracts; update generated Python/Go/TypeScript types and refuse a bundle that
   advertises #92 without both artifacts and their reconciled controls.
9. Retain the migration-0008 PostgreSQL materialization and nullable Go/UI path, then complete the
   OpenAPI/types and exact availability/reason contract so it survives end to end. No layer may
   coalesce null P90/confidence to zero or compute spread/confidence/safety stock from a withheld
   interval.
   Repair the §1.3.1 served aggregates in the same change, because they are the one place where the
   withholding is already wrong on screen:
   - **freeze both presentation behaviors first**, before writing either the implementation or its
     tests. For the interval total: §1.3.1 option 1, absent with the governed reason whenever the
     window mixes published and withheld weeks, or option 2, renamed to a sum of weekly upper bounds
     with a same-window P50 comparator and a parity-reviewed visible window. For confidence: qualified
     in place with a visible covered horizon and withheld count, or unavailable through the approved
     element-level behavior whenever the window is mixed. Both freezes and the Demand Forecast parity
     amendment belong to the `P4-0P` gate and must be approved before this task starts; `P4-4` inherits
     that amendment rather than ratifying a shipped change. Filtering to H1–H4 without choosing
     is not a repair: it corrects the arithmetic while a column headed "Confidence" or an interval
     total still describes a window the screen never states;
   - restrict the P50-weighted confidence mean to the weeks that carry an interval on **both** sides
     of the ratio, so a retained P50 weight can no longer dilute a mean whose numerator skipped it.
     This is decision #12's formula on the population where confidence exists; it settles the
     arithmetic, not the presentation;
   - publish the covered interval window and the withheld week count with the interval aggregates;
   - scan every aggregated interval value as nullable, so a future horizon-range filter cannot turn a
     fully withheld window into a request-time error rather than a governed unavailable state;
   - carry the covered-window, withheld-count and reason fields through OpenAPI, the generated
     Python/Go/TypeScript types **and** the Zod item schema together; `forecastWorkbenchSchema` strips
     unknown keys, so a field added only server-side never reaches a component;
   - obtain the Demand Forecast parity review before implementing any frozen option that changes what
     the screen shows, which is every option except the interval total's option 1.
   Also correct the published `A2_per_cohort` note text, which still credits decision #87 with
   supplying the remedy that makes the band reachable. #87 is closed with both candidates rejected and
   #92 supplies the boundary; the sentence lives inside fingerprinted evidence, so this publication is
   the only place it can be fixed without editing an immutable artifact.
10. Publish under acceptance-v5/verifier-v5 and migration 0009. Prior v4 and
    interval-incomplete bundles remain immutable and ineligible rather than being reinterpreted.
11. Independently verify both sides of the contract: every published cold-start H1–H4 interval and
    every withheld cold-start H5–H26 field/reason/count/exception; recompute rather than trust stored
    booleans.
12. Publish, independently verify, materialize, and separately activate the bounded forecast under
    Decision #90's authority-generation-2 scope. Append a supersession of current event 9, then make
    the new active event point to that supersession; never mint another null-predecessor chain.
13. Record the exact current authority and bounded interval capability in the Phase 4 entry record.

**Acceptance:**

- every published cold-start and established-history cohort cell is in 0.85–0.95 globally and per
  market; whole-population A2 still scores all 708,708 evaluation rows, and any published-interval
  coverage figure appears under its own diagnostic name with its denominator disclosed;
- H1–H4 cold-start intervals are present; H5–H26 cold-start P90/confidence are absent with the exact
  false availability flag and reason, while P50 remains present at all 26 horizons;
- on the current measured pin, 8,756 of 52,884 current rows are withheld from publication and 86,636
  evaluation rows are excluded from the cold-start `A2_per_cohort` cell while keeping non-null
  intervals, and one series-level
  exception exists for each of the 398 affected current series; a later final
  pin must publish reviewed exact replacements rather than silently inherit these counts;
- the covered-week confidence reference value is computed for the 398 affected series and is not the
  diluted 0.0814 measured in §1.3.1; the covered/withheld window is published; and the served response
  matches the frozen §1.3.1 confidence behavior at 8, 13 and 26 weeks — under *qualified in place* the
  response value equals that reference and its visible scope is present, under *unavailable when
  mixed* the response value is absent with the approved reason and no numeric confidence is required.
  At 4 weeks confidence stays numeric and unaffected under either choice, and no row shows an
  unqualified H1–H4 confidence beside full-window forecast values;
- the served interval total follows the §1.3.1 frozen choice exactly: either absent with the governed
  reason whenever the window mixes published and withheld weeks, or present under a name that states
  what it is with its same-window P50 comparator. No response carries an unlabelled interval total
  beside a differently scoped central total;
- no insufficient-evidence cell is treated as pass, and no withheld row is removed from non-A2
  scoring;
- P50≤P90 for every available interval; nullable-domain invariants pass for every unavailable one;
- A1/A3/A5 and every decision-#77 P50 display cell remain byte-identical;
- all P50 and all available accepted-C5 P90 values remain byte-identical before withholding;
  established-history P90 remains complete and C8's full-range rejection is retained;
- all decision-#86 refusal criteria pass, C5 disclosure remains, and interval/exception controls
  reconcile across Parquet, DuckDB, manifest, PostgreSQL, API, and verifier evidence;
- the interval-incomplete v5 materialization remains immutable but is no longer active after the
  corrected version supersedes it;
- exactly one active authority remains across all policy/config fingerprints, and the new active
  event chains to the selected superseded event.

**Exit:** decision #85 is hard and passing for the decision-#92 published interval capability on one
independently verified verifier-v5 generation over the final Phase 4 source pin; P50 remains
complete; bounded availability and exceptions are servable; and exactly one Decision-#90
authority-generation-2 authority is active.

**Stop:** stop if the scoped bundle, nullable contract, withheld counts, series exceptions, or
cross-layer values do not reconcile. Do not return to C6/C7, describe C8 as a passing full-range
remedy, change the H4 boundary, coerce null to zero, drop withheld rows from non-A2 evaluation, or
retune after confirmation. Extending the calibrated range requires a new preregistered mechanism.

### P4-2 · Freeze source, staging, canonical, and readiness vNext

**Entry:** `P4-0` complete. The current-pin bounded publication has already resolved the former
`P4-D0` ordering question, so this package is source-only and authorizes no result-bearing Phase 4
engine work. Decision #88 option (a) is already decided and
implemented and must be verified unchanged. Decision #89's byte-determinism exclusion contract and
one-time next-landing adoption/re-pin evidence are mandatory inputs.

**Tasks:**

1. Verify decision #88 across the adapter, staging-role contract, crosswalk, fixtures, and every
   consumer. All new Phase 4 roles and adapters use `location_source_key`, `name`, and
   `location_kind`; no consumer may restore the interim dual-spelling workaround.
2. Implement and verify decision #89: exclude only producer-declared
   `contentDeterminism: logical` objects from snapshot identity, retain byte-stable restricted
   objects, reject an all-excluded object inventory, and keep mirror/telemetry hashes outside the
   authoritative identity. Version the identity method and retain canonical control-total and
   ordered-row-digest evidence.
3. Publish source config/spec v13 and bump generator identity according to release policy.
4. Add source-declared, effective-dated, typed replenishment/customer-fulfillment lanes and a
   source-neutral `service_lane` staging role.
5. Extend canonical `retail_v2` with `service_lanes` and generated Python/Go/TypeScript types.
6. Add status-effective inbound observations so each shipment's on-order, in-transit, received,
   cancelled, or exception state is reconstructible at any origin.
7. Add `status_effective_at` or an equivalent separately typed event time and require
   `known_as_of >= status_effective_at`; never use business date as availability.
8. Correct fulfillment availability derivation and extend B05 so every fulfillment line satisfies
   `known_as_of >= fulfilled_at`. Define `greatest(known_as_of, fulfilled_at)` only as the explicit
   interim diagnostic visibility for pre-v13 rows, never as replay-readiness evidence.
9. Generate store inventory snapshots on the weekly state grid for active assortment cells plus
   formerly assorted cells with non-zero residual stock state; omit inactive zero-state cells.
10. Add source-owned, cost-carrying store transfer order/shipment/receipt status history; do not
   overload the `[poc]` transfer recommendation table.
11. Compute store WAC canonically from completed cost-carrying transfer/receipt facts.
12. Generate store waste and perishable store batches only where product/shelf-life rules support
   them.
13. Publish external and internal supply terms at SKU/department/category scopes with real variation
   and origin-safe evidence.
14. Define exact external-origin versus internal-location term keys; null never wildcard-matches.
15. Extend temporal-evidence policy/readiness to the current-snapshot/replay capability split.
16. Replace Gate B's hardcoded replenishment result with evaluated rules.
17. Extend ATP/inventory-position reconciliation from cutoff-only to historical origins, including
    both external inbound and internal transfer state.
18. Add lane checks: type, active resolution, rank uniqueness/contiguity, market consistency, node
    role, cycle prevention, channel resolution, and 100% fulfillment-row coverage using the
    corrected effective visibility time.
19. Add store-state checks: active-or-residual time-qualified coverage, ATP formula, transfer
    receipt balance, waste/batch reconciliation, and cost completeness.
20. Repair the `quality_violations` publication-control lifecycle. Preferred: insert every Gate-B
    outcome and canonical critical row, then compute entity row count/hash controls from that final
    publication database before Parquet export and manifest fingerprinting. The only admissible
    alternative is a versioned contract that marks the entity control-exempt with a reason and
    publishes a separate count/digest over the exact exported rows. In either design, Parquet,
    DuckDB, and published controls must reconcile; the current 2-row/0-control defect is a failing
    regression fixture.
21. Emit negative inventory and missing required accepted cost into canonical
    `quality_violations` with `critical` outcome/severity semantics and the affected inventory
    capability before the repaired controls/export/fingerprint boundary. A promoted capability
    must have zero such rows, and engine exceptions must not replace this ingestion control home.
22. Add supplier-term checks: precedence coverage, grade floor, positive/varied lead/MOQ/pack,
    lead-time variability, and ambiguity refusal.

**Contract fixtures:**

- one primary + one spill lane;
- channel-specific lane overriding a null-channel default;
- overlapping rank-1 lanes rejected;
- missing priority rank rejected;
- cross-market lane rejected;
- lane cycle rejected;
- fulfillment outside an active lane rejected;
- fulfillment with `known_as_of < fulfilled_at` rejected;
- inbound/transfer status with `known_as_of < status_effective_at` rejected;
- external null origin not matching an internal lane;
- exact SKU term beating department and category;
- department beating category;
- equal-precedence ambiguity rejected;
- landing-backfill replay unavailable;
- business-date-as-availability replay blocked;
- inactive zero-residual store cell rejected;
- de-assorted non-zero residual stock retained while demand remains zero;
- negative inventory and missing required cost emitted as critical `quality_violations`;
- existing B15/B21 exported-row count/digests reconcile exactly across Parquet, DuckDB, and the
  publication manifest (or the approved versioned exemption record);
- a post-control quality-row insert or 2-row artifact/0-row control mismatch is rejected;
- decision-#88 exact neutral location spellings accepted and non-contract aliases refused for every
  new Phase 4 role/adapter path;
- decision-#89 vectors proving logical-mirror exclusion, byte-stable restricted-object retention,
  all-excluded refusal, repeated pinned-writer/profile identity, and cross-profile semantic
  equivalence;
- versioned inbound state reconstructible at multiple origins.

**Exit:** reviewed source/staging/canonical/readiness contracts and tests prove the new semantics
before a full source run is generated.

**Stop:** if the implementation requires platform-specific logic below staging roles, return to the
adapter/role contract; do not branch canonical transforms.

### P4-3 · Generate, ingest, publish, select, and re-pin

**Entry:** `P4-2` complete and `P4-0` closed. The current-pin bounded publication is the recorded
entry pass; the frozen Decision-#89 policy fingerprint and its accepted adoption evidence are
mandatory inputs.

**Tasks:**

1. Run a small deterministic fixture through generator → land → adapters → staging → transforms →
   Gate A/B → readiness → publication.
2. Prove exact source-id reproducibility across repeated generation under the same pinned writer/
   profile after excluded logical objects are removed. Prove safe/performance semantic equality
   separately with matching canonical schemas, control totals, and canonical ordered row digests;
   do not require cross-profile source-id equality.
3. Generate the full ten-year source candidate without overwriting the accepted pin.
4. Retain source controls, canonical ordered row digests, manifests, hashes, writer version,
   execution profile, peak memory, and row counts.
5. Run Gate A and Gate B, including historical ATP/inbound, lanes, store state, costs, and terms.
6. Reconcile declared lanes to every fulfillment line at corrected effective visibility; publish
   the seven current-pin relationships as the expected baseline, not hard-coded runtime logic.
7. Prove time-qualified store coverage for SKU × store cells that are active or hold non-zero
   residual state; reject inactive zero-state Cartesian rows. Preserve decision #71 zero demand for
   de-assorted residual-stock cells.
8. Publish independent current-snapshot and replay readiness/sufficiency verdicts.
9. Require both inventory capabilities `ready + sufficient` for the full Phase 4 pin.
10. Publish a new immutable curated publication and retained evidence.
11. Create candidate → approved → active #73 selections for the required capabilities.
12. Update the expected ML pin only after selection activation.
13. Stop the source track here and hand the final selected pin to `P4-1`; do not fit, publish,
    materialize, or activate a forecast inside this package.
14. `P4-1` repeats the frozen work on the new publication fingerprint using unchanged
    #82/#83/#84/#85/#92 semantics. It recomputes only the frozen C5 method's 52 market × horizon
    weights and preserves Decision #92's H1–H4 availability boundary; it does not reopen Decision
    #74's configuration cap, return to rejected #87/#91 mechanisms, or search a second mechanism.
15. `P4-1` re-runs all published-interval acceptance cells and withheld-population controls, then
    materializes/activates only if every gate passes. Apply Decision #90 and supersede the prior
    forecast authority; never leave the old and new source-pin forecasts active in parallel. A
    changed source fingerprint creates a new run even when forecast
    bytes happen to match.

**Expected source outcomes:**

- store stock, receipt/transfer, waste, cost, and batch rows are nonzero where applicable;
- service lanes are typed and origin-safe;
- fulfillment and status facts pass the event-placement rules with no pre-event availability;
- supplier terms reach `native_extracted` or stronger for replay;
- lead-time mean/std and term precedence are non-degenerate;
- inbound status history reconstructs positions at historical origins;
- current-snapshot and replay capabilities are both ready/sufficient;
- unrelated accepted-source controls remain within reviewed expected deltas.

**Exit:** one active source selection exists. After the subsequent single final-pin `P4-1` pass
(recommended sequence), or the strict task-14 repeat, one accepted hard-gated forecast shares that
publication fingerprint.

**Stop:** a source publication may pass global Gate B while inventory replay remains unavailable or
insufficient. Do not update `expected-pin.json` until the capability verdict itself passes.

### P4-4 · Freeze Phase 4 policy, run, verifier, OpenAPI, and screen matrices

**Entry:** `P4-1`; reviewed `P4-2` shapes; no result-bearing Phase 4 engine run.

**Tasks:**

1. Add inventory-policy v2 side-by-side with v1 and make guardrail resolution version-aware.
2. Implement an exact market/currency inventory-policy override merge path. Preserve fail-closed
   zero-match/duplicate-match behavior and do not inherit absolute market rules from another market.
3. Prove the current v1 call `resolve_guardrails("india-west", "INR")` fails, then prove v2 resolves
   exactly one India West and one US New York vector. Missing, duplicate, and wrong-currency
   negative tests must still raise. This package cannot freeze while either live market fails.
4. Freeze all `P4-D*` approved values, including replay acceptance exact math, `P4-D16` channel
   rules, and `P4-D17` core-versus-partial interval-consumer behavior and systemic thresholds.
5. Freeze the Monday/Thursday bridge vectors for `Asia/Kolkata` and `America/New_York`, including
   Thursday 23:00 local cutoff, Monday 00:00 opening, inclusivity, and DST-transition fixtures.
6. Publish resolved per-market canonical bytes/fingerprints using the live market ids.
7. Add Python golden vectors for policy resolution, inventory position, ABC, safety stock,
   lead-time scaling, MOQ/pack rounding, cover cap, lane/term resolution, channel allocation,
   transfer, and allocation.
8. Add equivalent Go vector execution for every API-side closed-form/read-model computation.
9. Freeze run, acceptance, verifier, lifecycle, artifact, and semantic-fingerprint schemas.
10. Freeze independently recomputable acceptance components; stored booleans alone are never
   verifier authority.
11. Extend OpenAPI using the existing envelope and governed 409/503 behavior.
12. Freeze 14 screen matrices before React implementation. Inherit the `P4-0P` Demand Forecast parity
    amendment as already approved: this package owns the 14 new matrices, not the existing
    `demand-forecast.parity.yaml`, and may not re-open or retrospectively ratify its amendment.
13. For every HTML element, record authority, grain, formula, filters, actions, availability,
    staleness, and approved unavailable rendering.
14. Freeze the artifact → screen → endpoint mapping below, including explicit homes for Stock
    Health and Demand at Risk.
15. Record Stock Health as destination 14 and keep Performance Insights out of Phase 4.
16. Record NRV/provision/workflow/ERP unavailable decisions explicitly and DC-only ERP↔WMS
    variance unless reviewed v13 store WMS evidence exists.
17. For every interval-consuming endpoint/screen/engine, record the declared horizon source,
    core-versus-partial capability, per-row skip behavior, exception projection, and the exact
    feature-level unavailable rule. A generic nullable P90 field is not a complete consumer
    contract.

**Proposed read endpoints:**

```text
GET /api/v1/inventory/versions
GET /api/v1/inventory/overview
GET /api/v1/inventory/stores
GET /api/v1/inventory/warehouses
GET /api/v1/inventory/ageing
GET /api/v1/inventory/transfers
GET /api/v1/inventory/valuation
GET /api/v1/inventory/expiry-waste
GET /api/v1/inventory/stock-health
GET /api/v1/replenishment/planner
GET /api/v1/replenishment/orders
GET /api/v1/replenishment/suppliers
GET /api/v1/replenishment/safety-stock
GET /api/v1/replenishment/allocations
GET /api/v1/replenishment/exceptions
```

| Screen | Authoritative artifact(s) | Read endpoint |
|---|---|---|
| Inventory Overview | `inventory_positions`, `stock_health`, `demand_at_risk`, `replay_metrics` | `/api/v1/inventory/overview` |
| Store Inventory | `inventory_positions`, `stock_health`, `demand_at_risk` | `/api/v1/inventory/stores` |
| Warehouse Inventory | `inventory_positions`, `inventory_valuation`, `supplier_planning` | `/api/v1/inventory/warehouses` |
| Inventory Ageing | `inventory_ageing` | `/api/v1/inventory/ageing` |
| Stock Transfers | `transfer_recommendations` | `/api/v1/inventory/transfers` |
| Inventory Valuation | `inventory_valuation` | `/api/v1/inventory/valuation` |
| Expiry & Waste | `inventory_expiry_waste` | `/api/v1/inventory/expiry-waste` |
| Replenishment Planner | `replenishment_recommendations`, `demand_at_risk` | `/api/v1/replenishment/planner` |
| Suggested Orders | `replenishment_recommendations` | `/api/v1/replenishment/orders` |
| Supplier Planning | `supplier_planning` | `/api/v1/replenishment/suppliers` |
| Safety Stock | `safety_stock_segments` | `/api/v1/replenishment/safety-stock` |
| Allocation & Fulfillment | `allocation_recommendations` | `/api/v1/replenishment/allocations` |
| Replenishment Exceptions | `replenishment_exceptions` | `/api/v1/replenishment/exceptions` |
| Stock Health | `stock_health`, `demand_at_risk` | `/api/v1/inventory/stock-health` |

Exact resource grouping may change at contract review, but each screen must have an explicit live
read model and lineage; a grouping change must update all three columns together.

**Exit:** policy/run/API/screen contracts are `frozen_approved_for_implementation`; Python↔Go
vectors pass.

**Stop:** no engine or page is implemented against an unreviewed matrix or threshold placeholder.

### P4-5 · Port and re-contract the reusable engine foundation

**Entry:** `P4-3` selected input and `P4-4` frozen contracts.

**Tasks:**

1. Extend `ml/REUSE_AUDIT.md` for all seven M5 modules with source hashes and adaptation grades.
2. Create `ml/src/retail_ml/engines/` with no dependency on M5 paths or reports.
3. Port pure inventory-position, service-level scale, RSS, reorder, order-up-to, pack/MOQ, and cover
   primitives first.
4. Replace M5 store-only keys with typed market/location/lane keys.
5. Replace source-local config with verified inventory-policy-v2 resolution.
6. Make weekly horizons and lead+review protection explicit.
7. Wrap every interval consumer with a shared horizon declaration and viability check. Derive the
   required horizon per selected row from origin-safe lead time plus review period. Use
   `require_cold_start_interval_horizon` only for a contractually all-or-nothing consumer; the
   declared partial cold-start replenishment path branches row-by-row and exposes aggregate status.
8. Add the shared row-level helper for explicitly partial consumers: branch on
   `interval_available`, skip only the interval-dependent output, retain allowed P50 use, and emit/
   link the governed `cold_start_interval_unavailable` exception. Never branch on `p90 IS NULL`
   alone and never turn null spread into zero.
9. Implement exact lane/term precedence and reason-coded missing/ambiguous states.
10. Implement market-local ABC using accepted cost lineage.
11. Port policy calibration/validation with `P4-D14` cohort identity.
12. Redesign simulator primitives around the weekly event clock; do not mechanically wrap the daily
    M5 simulator.
13. Add telemetry stages and CLI subcommands without making MLflow publication authority.

**Minimum unit/golden tests:**

- P50/P90 monotonic input refusal;
- RSS over weekly spreads;
- service-level scale A/B/C;
- fractional lead/review protection rule;
- current 5-day lead plus 7-day review resolves H2 and passes the H4 boundary for all 2,034 current
  served SeriesKeys; the separate evaluation population is 398 cold-start, 1,926 established, and
  16 ineligible keys and must not be substituted for the serving grain;
- a varied v13 fixture may resolve H5+ without being artificially capped; affected cold-start rows
  take the declared partial path, while an all-or-nothing consumer refuses before rows run;
- an optional partial consumer skips only unavailable interval-dependent rows, emits one governed
  series exception with an affected horizon range, retains P50 where authorized, and refuses when
  its frozen systemic threshold is breached;
- null P90/confidence cannot become zero spread, zero safety stock, or a numeric API value;
- inventory position with disjoint ATP/on-order/in-transit;
- missing or overlapping buckets refused;
- reorder threshold and order-up-to;
- MOQ/pack rounding without exceeding order-up-to/max cover;
- zero/negative demand and missing cost behavior;
- exact lane and term resolution;
- null external origin not wildcard;
- ABC ties and missing cost;
- market-local money isolation;
- stable 5%/95% cohort hash;
- Monday opening construction from the preceding Thursday in both market timezones, including DST;
- node-demand aggregation and channel ATP conservation under `P4-D16`;
- deterministic weekly event ordering.

**Exit:** reusable foundation passes unit tests, cross-language vectors, import boundaries, and a
small verified-input replay fixture.

**Stop:** any M5 behavior that assumes daily state, store-only inventory, untyped money, or mutable
report paths is redesigned or dropped; it is not preserved for reuse credit.

### P4-6 · Implement net-new inventory and optimization engines

**Entry:** `P4-5` complete.

**Inventory analytics tasks:**

1. Current and historical inventory-position reconciliation.
2. Days of supply, availability, stock turn, and health class.
3. Age buckets and deterministic action ladder.
4. Expiry-window exposure and waste actuals.
5. Gross valuation, store/DC WAC lineage, missing-cost evidence, and DC-only ERP↔WMS variance. Store
   variance stays unavailable unless the selected source pin contains reconciled store WMS rows.
6. Optional NRV/provision only if `P4-D10` is superseded by an approved policy.
7. Demand-at-risk using governed available P90 and cost, with exact interpretation labels; an
   unavailable interval produces the frozen per-row exception/unavailable state, never zero risk.
8. Supplier capacity/OTD/risk and lead-time mean/std model.

**Optimization tasks:**

1. Transfer candidate generation only over active typed lanes/allowed peer nodes.
2. Source residual-cover and target max-cover constraints.
3. Expected-benefit calculation in one market/currency.
4. Deterministic transfer objective and tie-breaking.
5. Allocation pool construction from origin-visible current inventory.
6. Demand/service/value priorities under frozen objective weights.
7. Capacity, inventory, lane, budget, and nonnegative constraints.
8. Conservation checks: allocated + residual = pool; no double allocation.
9. Read-only exception classification for constraint failures and unavailable inputs.

**Interval-consumer tasks:**

1. Reorder and safety stock derive the required horizon per row from resolved supplier lead time
   plus review period. On the current measured input, 5 + 7 days resolves to H2, within H4, so no
   cold-start row is skipped and all 2,034 current served SeriesKeys receive a calibrated reorder
   interval. This is a current-pin observation, not a cap on v13 terms.
2. Cold-start H5+ replenishment, long-horizon planning, seasonal-buy, and scenario features declare
   partial capability. They omit only the interval-dependent row/output, publish
   `cold_start_interval_unavailable`, and expose manual-judgment/unavailable status. They do not
   suppress the underlying forecast row or its P50.
3. Reconcile per-feature skipped-row, series, unit-demand, and actual-demand shares with the source
   forecast availability artifact and exception projection. Mark a supported market's cold-start
   replenishment sub-capability unavailable when 100% of its cold-start SeriesKeys or demand is
   skipped; mark the whole market consumer unavailable if no recommendation row remains. Apply any
   stricter pre-result P4-4 threshold without post-result weakening.

The current canonical `quality_violations` Parquet and DuckDB artifact contains B15/B21, but its
manifest controls incorrectly attest zero rows because the publisher inserts those outcomes after
copying candidate controls. `P4-2` repairs that boundary and emits critical negative-inventory/
missing-required-cost violations before final controls/export/fingerprinting. Engine exceptions may
reference governed violation ids but must not replace, downgrade, or hide them.

**Artifacts and telemetry:**

- every engine output includes run id, source/forecast/policy fingerprints, market/location/lane
  scope, decision timestamp, reason/status, and confidence/availability where applicable;
- deterministic row ordering and semantic fingerprints;
- stage timings and bounded-memory evidence;
- no accepted artifact produced on a failed invariant.

**Exit:** all net-new engines pass deterministic fixtures, property tests, conservation/reconciliation
checks, and full-pin bounded execution.

**Stop:** if a screen column lacks a governed formula/input, emit unavailable and open a contract
decision; do not derive a visually convenient proxy.

### P4-7 · Weekly replay, calibration, holdout, and independent acceptance

**Entry:** `P4-3` ready/sufficient pin, `P4-4` frozen acceptance, `P4-5/6` engines green.

**Tasks:**

1. Freeze the incumbent source-simulator policy id/fingerprint and replay schedule.
2. Select replay origins with sufficient origin-visible opening state, inbound history, lanes,
   terms, demand, cost, and closing oracle.
3. Run oracle reproduction before policy comparison; publish weekly state deltas/tolerance.
4. Stop if observed weekly stock cannot be reconstructed within the frozen tolerance.
5. Create the stable 5% calibration and 95% holdout cohorts once.
6. Run only pre-registered policy candidates on the 5% cohort.
7. Select exactly one policy under the frozen value/service rule.
8. Apply that policy once to the untouched 95% holdout.
9. Compare incumbent and candidate on identical rows/events.
10. Publish global, market, ABC, node-type, and sufficiency slices without letting pooled results
    hide a market failure.
11. Independently recompute replay gates, policy gates, cohort hashes, and artifact fingerprints.
12. Publish either an accepted immutable Phase 4 run or an honest rejected run.
13. Recompute interval-consumer viability at every replay origin from origin-visible terms. H5+
    cold-start rows follow the declared partial path with governed row skips and exception/share
    evidence; market sub-capability and whole-market refusal floors from `P4-D17` remain binding.

**Required replay evidence:**

- fewer stock-out periods and lost units under the frozen acceptance rule;
- lower mean inventory units/value per market under the frozen acceptance rule, with any global
  value comparison using only approved reporting FX or a frozen dimensionless aggregation;
- fill rate no worse than incumbent;
- no market hidden by global pooling;
- no policy/forecast/source/lane fingerprint mismatch;
- calibration and holdout key sets disjoint and collectively complete;
- holdout was not read during candidate selection;
- transfer/allocation conservation and budget/capacity constraints pass;
- all unavailable cells reason-coded.

**Exit:** immutable replay-acceptance and policy-holdout records both pass independent verification.

**Stop:** a calibration pass cannot compensate for a holdout fail. Do not change service levels,
thresholds, cohorts, incumbent, or tolerance after reading holdout.

### P4-8 · Publish, materialize, activate, and serve read-only API models

**Entry:** accepted `P4-7` run and frozen OpenAPI/DB contract.

**Tasks:**

1. Verify every run artifact before opening a PostgreSQL transaction.
2. Add `0010_*_inventory_replenishment_serving.py` after
   `0009_*_forecast_interval_contract_completion.py`; advance every exact-head DB/ML/Go/test/
   evidence pin to 0010 while preserving the inherited 0007/0008/0009 forecast constraints.
3. Create one version/materialization/activation lifecycle and normalized read projections.
4. Suggested serving tables:
   - inventory versions/materializations/activation events;
   - inventory positions/health/ageing/expiry/valuation;
   - replenishment recommendations and safety-stock segments;
   - transfer and allocation recommendations;
   - supplier planning metrics;
   - read-only replenishment exceptions;
   - lineage and policy fingerprints.
5. Enforce append-only activation and one active inventory/replenishment version per `P4-D15`
   product-bundle scope.
6. Build a fail-closed active view requiring run/verifier/source/forecast/policy lineage match and
   exactly one decision-#90 forecast authority across all model/config fingerprints.
7. Materialize the accepted bundle transactionally; retry exact duplicates idempotently.
8. Activate in a separate transaction/event.
9. Implement framework-neutral Go repositories/read models.
10. Implement handlers for the version endpoint and all 14 screens.
11. Apply market/location/lane/filter scope in SQL, not after unbounded reads.
12. Return 503 for missing/unavailable active capability and 409 for governed staleness/conflict.
13. Prove handlers never open Parquet/DuckDB or call Python at request time.
14. Add API smoke evidence bound to the active run/version/fingerprints.
15. Preserve interval availability/reason and the linked source exception through PostgreSQL and
    JSON. Omit nullable interval-derived numeric values when unavailable; never serialize them as
    zero. Core-consumer unavailability returns governed 503, while approved partial-row
    unavailability remains a successful response with explicit row/feature status and counts.

**Exit:** one independently verified accepted Phase 4 version is active and every endpoint returns
live lineage-matching PostgreSQL values or governed 409/503.

**Stop:** accepted-but-unmaterialized or materialized-but-inactive state remains 503. No fallback to
files, sample JSON, a prior verifier, or a stale active row.

### P4-9 · Build 14 React pages and complete Demo 4

**Entry:** live `P4-8` read models and 14 approved matrices.

**Tasks:**

1. Extend page routing/types for all 14 destinations.
2. Preserve common shell, navigation order, labels, filters, KPI/table/control positions, and design
   tokens from the reference HTML.
3. Bind every displayed value to its page contract and live API lineage.
4. Preserve units and percentages; apply approved reporting FX only to money displays.
5. Render current/replay readiness and element unavailable behavior exactly as approved.
6. Keep action controls visible but disabled; expose no mutation handler.
7. Add loading, empty, 409, 503, and stale states without phase/roadmap language.
8. Add desktop 1440×1100 and mobile 390×844 screenshot fixtures.
9. Add DOM order, labels, design-token, data-value, filter, modal, unavailable, and responsive tests
   per page.
10. Obtain separate human sign-off for every destination; no page approval stands in for another.
11. Run manual Windows/macOS/Linux developer evidence and the full stateful local gate.
12. Render `cold_start_interval_unavailable` as manual-judgment/unavailable for affected H5+
    cold-start rows. Do not show zero safety stock, zero risk, a collapsed row, or a fake confidence
    value; current-pin H2 rows remain normally available and varied-term H5+ rows remain visibly
    partial.

**Exit:** all 14 pages render live market/location/lane-scoped outputs, approved unavailable
elements, and no fabricated or mutable behavior. Demo checkpoint 4 is signed off.

**Stop:** a page cannot enter Demo 4 on navigation-shell presence, static samples, another page's
approval, or a global API smoke alone.

---

## 8 · Screen scope and data disposition

| # | Screen | Primary grain | Current evidence | Required Phase 4 disposition |
|---:|---|---|---|---|
| 1 | Inventory Overview | market/location | DC rows; current in-transit only | Full current store+DC position; replay-backed risk/turn |
| 2 | Store Inventory | store × SKU | None | Active-or-residual store state, availability, DoS, risk, transfer opportunity |
| 3 | Warehouse Inventory | DC | Capacity, receipts, allocations | Live value, utilization, fill, blocked, delayed receipts |
| 4 | Inventory Ageing | SKU × location × age bucket | Batch receipt dates | Store+DC ageing including de-assorted residual stock, with reason-coded non-batch scope |
| 5 | Stock Transfers | lane × SKU | DC→DC received only | Current recommendations over typed store/DC lanes |
| 6 | Inventory Valuation | category/location | Gross/WAC and DC-only ERP↔WMS variance | Gross live; DC variance live, store variance unavailable unless v13 adds evidence; NRV/provision per `P4-D10` |
| 7 | Expiry & Waste | batch | 49.2% of batches have expiry; DC waste | Store+DC supported perishables; non-expiring unavailable/not-applicable |
| 8 | Replenishment Planner | SKU → destination | DC state; weak terms | Full current suggestions with lane/term/capacity/budget guards |
| 9 | Suggested Orders | order/recommendation | Engine output absent | Read-only candidate orders; ERP status shadow-only |
| 10 | Supplier Planning | supplier × scope/period | 17,829 performance rows | Performance plus varied origin-safe terms and risk |
| 11 | Safety Stock | policy segment | Gated by decision #85 | Hard-gated interval input and accepted policy output |
| 12 | Allocation & Fulfillment | SKU × store × channel | Historical requests/allocation/shortfall | Forward constrained channel allocation using one node ATP pool + typed lanes |
| 13 | Replenishment Exceptions | exception | No Phase 4 engine rows | Stateless engine-derived rows; workflow fields unavailable |
| 14 | Stock Health | SKU × store | Store state absent | Eight-column triage over active plus de-assorted residual stock; Performance Insights excluded |

Every matrix records which KPI/column is live, derived, unavailable, or not applicable. “Partial
screen” is not a reason to remove an element or substitute a new panel.

---

## 9 · Acceptance gates

### 9.1 Entry gates

- `P4-0` lineage/migration integration and Phase 3 authorization complete;
- decision #90 fully implemented, including migration-client alignment, global Go revalidation,
  and the retained authority-generation-2 events 7→8→9 successor chain;
- decision #87's C6/C7 and decision #91's C8 full-range rejections retained; decision #92 is
  implemented without post-confirmation refit or boundary change;
- decision #85 hard-gate version boundary created;
- all six published-interval per-cohort coverage cells pass, while withheld row/series/share/demand-
  share evidence reconciles and P50 remains scored at all horizons;
- one hard-gated forecast active;
- the as-built `P4-D0` ordering disposition explicitly recorded.

### 9.2 Data and readiness gates

- decision #88 option (a) remains implemented, decision #89's implementation/adoption evidence is
  accepted, and both policy/contract fingerprints are in run identity;
- new immutable source publication and active #73 selection; decision #93 records the entry repin's
  prior pin as `legacy_unselected_predecessor`, while every future selected pin must carry a real
  supersession lifecycle event rather than file replacement as authority;
- every new Phase 4 role uses the decision-#88 neutral field spellings only;
- safe/performance profiles have equal canonical schemas, control totals, and canonical ordered row
  digests; exact source-id equality is required for repeated generation under the same pinned
  writer/profile, not across different execution profiles;
- fulfillment and status facts pass B05-class placement (`known_as_of >=` their observation/status
  event time), and no replay query uses the defective raw timestamp;
- typed lanes cover 100% of fulfillment rows at corrected effective visibility;
- store inventory is complete at each origin for active cells plus de-assorted cells carrying
  non-zero residual stock; inactive zero-state Cartesian cells are absent;
- historical inbound position reconstructible at replay origins;
- supplier terms origin-safe, varied, and precedence-complete;
- current-snapshot and replay capability both `ready + sufficient`;
- store/DC cost basis complete or reason-coded unavailable;
- governed critical rows are emitted into canonical `quality_violations` before the final
  control/exemption count, Parquet export, and publication fingerprinting, and the published
  artifact contains zero such rows for promoted inventory capabilities;
- `quality_violations` Parquet, DuckDB, and manifest controls/count-digests reconcile exactly, or the
  approved versioned control-exemption record covers the exact exported rows;
- new forecast accepted on the same publication fingerprint.

### 9.3 Contract gates

- inventory-policy v2 resolves and is fingerprinted for exactly `india-west`/INR and
  `us-new-york`/USD; negative market/currency cases fail closed;
- Monday/Thursday/timezone and `P4-D16` channel vectors pass;
- `P4-D17` consumer declarations, current-pin H2 viability, H5+ cold-start partial-row degradation,
  exception, market sub-capability refusal, no-remaining-row refusal, and any stricter frozen
  systemic-threshold vectors pass;
- run/acceptance/verifier schemas valid;
- exact replay acceptance and holdout rules frozen pre-result;
- Python↔Go golden vectors pass;
- OpenAPI validates and generated types are current;
- 14 matrices and the artifact → screen → endpoint mapping are approved for implementation.

### 9.4 Engine gates

- M5 reuse audit complete;
- weekly event clock deterministic;
- inventory-position/ATP/cost/lane/term reconciliation passes;
- reorder/MOQ/pack/cover constraints pass;
- every core interval consumer passes its resolved startup horizon assertion; every partial consumer
  reconciles skipped rows/exceptions and remains below its frozen systemic threshold;
- transfer/allocation conservation and deterministic tie-breaks pass;
- channel demand remains traceable and constrained channel allocation conserves node ATP;
- no cross-market unit/money contamination;
- engine semantics deterministic across supported profiles under the decision-#89 identity scope;
- import boundaries clean.

### 9.5 Replay and policy gates

- oracle weekly reproduction within frozen tolerance;
- candidate beats incumbent under all frozen replay gates;
- no hidden market failure;
- 5% and 95% cohorts disjoint/complete and fingerprint-bound;
- untouched 95% holdout passes;
- independent verifier recomputes every gate;
- rejected results remain rejected and unservable.

### 9.6 Serving gates

- all artifacts hash/row-count/schema verified before materialization;
- one transactional materialization and separate activation;
- exactly one active forecast per decision-#90 authority tuple across every model/classification-
  policy and legacy activation-scope fingerprint;
- the active forecast's immutable bundle exists, passes independent verification, and its active
  event has a valid supersession chain;
- active view refuses old verifier/policy/source/forecast lineage;
- Go reads PostgreSQL only and fails closed on duplicate authority regardless of configured legacy
  scope;
- exact 409/503 behavior tested;
- the weighted-confidence computation is confined to the weeks that carry an interval on both sides of
  its ratio and publishes its covered/withheld window; confidence and the interval total each follow
  their frozen §1.3.1 presentation choice at 8, 13 and 26 weeks — a served value equal to the
  covered-week reference with visible scope, or an absent value with the approved reason — so no
  response or screen carries an unqualified interval value beside a differently scoped central value;
  4-week responses stay numeric; no aggregated interval value
  is scanned into a non-nullable type; and the scope
  fields survive OpenAPI, generated types, and the Zod schema;
- API smoke matches active lineage and screen values.

### 9.7 UI/Demo gates

- 14 live destinations;
- desktop/mobile screenshot, DOM, token, and data-value assertions per page;
- unavailable/action behavior exactly matches matrix;
- no phase language, static samples, fabricated zero, or hidden limitation;
- separate human sign-off per page;
- manual Windows/macOS/Linux evidence;
- full stateful local verification passes.

### 9.8 No-go conditions

Stop and retain honest evidence when any occurs:

- any published-interval decision-#85 cell is outside 0.85–0.95 or insufficient, a withheld row is
  excluded from non-A2 scoring, or withheld population evidence is incomplete;
- any rejected #87/#91 mechanism, decision-#92 H4 boundary, feature/policy setting, or fallback is
  selected/tuned after confirmation origins were read;
- `interval_available` and its reason disagree with P90/confidence nullability, any layer coerces a
  withheld interval to zero, or the series-level exception projection does not reconcile;
- a served aggregate mixes withheld and published weeks — a P50-weighted mean whose denominator
  counts weeks its numerator skipped, an interval total covering fewer weeks than the central total
  it is displayed beside, or an unlabelled covered window — a §1.3.1 presentation behavior is
  implemented or tested before it is frozen, or whole-population A2 is rescoped to the
  published-interval population without its own decision;
- an all-or-nothing consumer requires H5+ but starts anyway; a partial consumer silently drops rows
  without exceptions/share evidence; a market remains cold-start-capable after 100% of its
  cold-start SeriesKeys or demand is skipped; or any stricter frozen threshold is breached;
- old verifier/materialization can satisfy the hard gate;
- Python/Go/DB/closure migration pins disagree with the required stage head (0008 at `P4-0`, 0009
  after `P4-1`, and 0010 after `P4-8`), zero or more than one forecast
  is active after `P4-1`, Go validates only a configured scope, an active version's immutable bundle
  is missing/unverifiable, events 7→8→9 do not verify, or a later replacement breaks the non-null
  successor chain;
- forecast/source/policy/lane fingerprints disagree within a run, cross-profile canonical control
  totals/ordered row digests disagree, or repeated generation under the same pinned writer/profile
  changes source id after logical-only objects are excluded;
- a new Phase 4 role restores dual location spellings or dialect-shaped fields, decision #89's
  adoption evidence is missing, a logical-only inventory is accepted, a byte-stable object is
  excluded, or implemented snapshot identity otherwise contradicts frozen decision #89;
- a source pin has no active decision-#73 selection, the decision-#93 adoption omits its
  `legacy_unselected_predecessor`, or any later selected pin lacks its real supersession event;
- current/replay readiness is unavailable, partial, insufficient, or not evaluated;
- an inactive zero-residual store cell is generated, or a de-assorted non-zero residual cell is
  omitted;
- any fulfillment/status row has availability before its event, or raw `known_as_of` is used to
  admit a fulfillment before `fulfilled_at`;
- a fulfillment row cannot resolve to an active typed lane;
- `india-west`/INR or `us-new-york`/USD cannot resolve exactly one inventory-policy-v2 vector;
- channel demand disappears in node aggregation, channel allocation exceeds node ATP, or direct DC
  fulfillment lacks an explicit `customer_fulfillment` lane;
- supplier terms require a null-origin wildcard or ambiguous precedence;
- exported `quality_violations` rows disagree with manifest controls/count-digests or an approved
  control-exemption record;
- a promoted inventory capability has a critical negative-inventory or missing-cost violation;
- weekly oracle state cannot reconcile within the frozen tolerance;
- replay or holdout fails any market/gate;
- optimizer violates inventory, capacity, budget, lane, or conservation constraints;
- materialization/activation lineage is ambiguous;
- an API reads files or serves a stale/legacy fallback;
- a UI value lacks a live authority or approved unavailable state.

---

## 10 · Test and evidence matrix

### 10.1 Contract tests

- source config/spec v13 validation;
- staging role/provider resolution, including exact decision-#88 neutral field spellings and
  rejection of non-contract aliases in new Phase 4 role paths;
- retail_v2 lane/inbound/store/cost/term schema validation;
- generated Python/Go/TypeScript type freshness;
- temporal-evidence policy v2 and capability split;
- policy-v2 exact-key/decimal/market/currency validation;
- v1 India West negative fixture; v2 exact India/US resolution plus missing/duplicate/wrong-currency
  refusal;
- resolved policy canonical bytes/fingerprints;
- Monday/Thursday bridge, market-timezone, DST, and channel-policy vectors;
- run/acceptance/verifier JSON/YAML schema tests;
- decision-#92 strict nullable truth table for `interval_available`, reason, P90, and confidence;
- forecast-exception-policy v2 class/evidence/fingerprint vectors and one-series-not-one-horizon
  grain;
- decision-#90 authority-scope, uniqueness, supersession-chain, and duplicate-refusal vectors;
- decision-#89 logical-mirror exclusion, byte-stable restricted-object retention, all-excluded
  refusal, and repeated pinned-writer/profile identity vectors;
- semantic-fingerprint vectors;
- OpenAPI validation and generated API types;
- 14 screen-contract structural tests and artifact → screen → endpoint completeness.

### 10.2 Datagen and ingestion tests

- deterministic small/full source identities;
- active assortment or non-zero residual stock controls store inventory emission;
- de-assorted residual stock remains visible while demand is zero; inactive zero-state cells are
  absent;
- store opening/receipt/transfer/sale/waste/closing balance;
- batch and expiry controls;
- store/DC WAC reconciliation;
- inbound status history at multiple cutoffs;
- lane exact/default resolution and negative cases;
- fulfillment `known_as_of >= fulfilled_at` and status `known_as_of >= status_effective_at` positive/
  negative placement fixtures;
- fulfillment-to-lane coverage at corrected effective visibility;
- supplier term grade/precedence/variation;
- Gate A/B positive and negative fixtures;
- negative inventory and missing required cost create critical `quality_violations` and prevent
  capability promotion;
- B15/B21 and critical-row counts/digests match across final DuckDB, Parquet, and manifest controls;
- post-control insertion and the current 2-row artifact/0-row-control defect fail publication;
- current/replay readiness states and reason codes;
- v1→vNext unaffected-domain parity;
- repeated pinned-writer/profile source-id equality plus safe/performance canonical schema,
  control-total, and ordered-row-digest equality;
- publication/retention/idempotent replay.

### 10.3 Forecast-entry tests

- decision-#87 C6/C7 and decision-#91 C8 rejection records, refused-remedy invariants, and
  confirmation isolation;
- decision-#91 cold-start training mask, alpha-0.90 head, 2,000-row fallback boundary,
  per-horizon fitted/fallback evidence, untouched confirmation, and retained 0.8063 full-range fail;
- all six published-interval coverage cells independently recomputed, plus withheld row/series/
  share/demand-share counts and band evidence;
- real publication-flow invocation of decision #92 before canonicalization/fingerprinting/export;
- H1–H4 cold-start P90/confidence present; H5–H26 unavailable with exact flag/reason/nulls; all-
  horizon P50 present and non-finite/mismatched combinations refused;
- `cold_start_interval_unavailable` emits once per affected series with H5–H26 evidence and
  reconciles to current/evaluation availability controls;
- decision-#85 absent-cohort `not_applicable`, present-but-insufficient refusal, and no-scored-cell
  population refusal;
- whole-population A2 and A4;
- old-generation activation refusal;
- two policy-derived activation scopes over one input/feature/market authority fail closed;
- refitting 52 weights creates a new run/version but supersedes rather than parallels the active
  authority; an active artifact-missing version is refused;
- `candidateClass: capability_scope_remediation`, targeted decision-#85/#92 scope, all-P50 byte identity,
  established-P90 byte identity, and cold-start-P90-only change verification;
- rejected decision-#91/C8 evidence plus accepted-C5 and decision-#92 availability/exception-policy
  run/version lineage and independent-verifier recomputation;
- rebuild manifest carries exactly integer horizons 1–26 with no empty element;
- frozen C5 method recomputes exactly 52 market × horizon weights without increasing decision #74's
  configuration count;
- C5 naming compatibility and leakage disclosure;
- one current authority/supersession lifecycle;
- new-pin forecast acceptance and activation.

### 10.4 Engine tests

- pure formula golden vectors;
- property tests for rounding/bounds/monotonicity;
- weekly state transition and lead-time arrival;
- position/ATP/bucket reconciliation;
- ABC cumulative/tie/missing-cost behavior;
- ageing/expiry/waste/valuation;
- supplier lead variability/risk;
- transfer feasibility/conservation/tie-breaking;
- allocation feasibility/conservation/channel priority and no silent channel aggregation;
- demand-at-risk and exception classification;
- resolved current-pin H2 pass, varied-term H5+ cold-start partial row skip, one-series exception,
  100%-cohort market-sub-capability refusal, no-remaining-row market refusal, all-or-nothing
  consumer startup refusal, any stricter systemic-threshold refusal, and no-null-to-zero properties;
- deterministic artifact bytes/semantic fingerprints;
- memory/profile invariance;
- import boundaries.

### 10.5 Replay and policy tests

- incumbent/candidate identical input keys;
- origin-visible latest-version event selection;
- per-origin resolved interval-horizon viability and partial-consumer exception/share reconciliation;
- Monday-opening oracle reproduction from the preceding Thursday bridge in both market timezones;
- stock-out/lost-unit/inventory/fill metric recomputation;
- global and per-market gates;
- calibration/holdout disjointness/completeness;
- untouched holdout enforcement;
- tampered artifact, policy, cohort, or stored verdict refused;
- failed replay cannot publish accepted lifecycle.

### 10.6 Database/API tests

- Alembic upgrade/downgrade and head assertion;
- materialization atomicity/idempotency;
- separate append-only activation;
- one-active-forecast constraint across decision-#90 authority tuple and all legacy scope hashes;
- supersession `prior_event_id` chain and rollback refusal when immutable bundle bytes are missing;
- fail-closed active view;
- Go startup and per-request revalidation refuse duplicate authority even when one legacy
  `activation_scope_fingerprint` is configured;
- stale/missing/lineage mismatch 409/503;
- filter/market/location/lane scope;
- screen KPI/table value recomputation;
- nullable interval/reason/exception round-trip, no numeric zero coercion, successful partial-row
  response, and governed core-feature 503;
- interval-aggregate regression at **4, 8, 13, and 26** selected weeks — every option the screen
  offers — over a fixture containing withheld weeks. Unconditional: 4 weeks is unaffected and stays
  numeric; the internal covered-week confidence reference is computed and asserted at 8/13/26 whatever
  the response then does with it; the covered/withheld
  window is published; the new fields survive OpenAPI/generated types/Zod rather than being stripped;
  and a fully withheld window returns the governed unavailable state instead of a scan error.
  Keyed to the frozen §1.3.1 choices: for the interval total, option 1 asserts it absent with its
  reason whenever the window is mixed while option 2 asserts the renamed field with a same-window P50
  comparator and never below it; for confidence, *qualified in place* asserts a served value equal to
  the reference plus its visible covered horizon and withheld count, while *unavailable when mixed*
  asserts an absent value with the approved reason and asserts **no** served numeric confidence. A test
  asserting one behavior while the contract froze the other is a failed gate, not a passing one;
- PostgreSQL-only import/I/O boundary;
- Go race tests and fingerprint vectors.

### 10.7 UI tests

- page routing/navigation for all 14 destinations;
- loading/empty/409/503/stale/unavailable states;
- labels/order/tokens/filters/modals/tables/KPIs per matrix;
- local money/unit/percentage formatting;
- disabled action controls and absence of mutations;
- exact API data-value binding;
- explicit cold-start interval unavailable/manual-judgment rendering with no zero safety stock/risk/
  confidence and no collapsed forecast row;
- desktop/mobile responsive behavior;
- no sample or roadmap language;
- screenshot diffs and accessibility basics.

### 10.8 Manual evidence

- Windows, macOS, and Linux contract/source/ML/DB/API/UI developer path;
- safe and performance profile comparison within the approved memory ceiling;
- per-page 1440×1100 and 390×844 visual review;
- 14 independent human approvals;
- final Demo 4 walkthrough using active live lineage;
- retrospective confirming no threshold/result-order violation.

---

## 11 · Security, privacy, and operational constraints

- No customer-level PII is required for Phase 4.
- Source/tenant/market scope is explicit in every selection, run, row, query, and activation.
- All money stays integer minor-unit through source, engine, DB, and API contracts.
- No optimizer or UI action sends to ERP/WMS.
- No uploaded executable adapter/plugin or dynamic code path is introduced.
- No shell-only portability requirement is added; developer flows remain cross-platform Python/Go/
  Node commands.
- Alembic remains the sole migration owner.
- MLflow records telemetry but never establishes acceptance or activation authority.
- PostgreSQL credentials and service configuration stay outside artifacts/screens.
- Evidence may contain aggregate business metrics but no secrets or raw restricted source payloads.
- Repository CI remains prohibited; manual supported-OS evidence is retained instead.

---

## 12 · Sequencing and review gates

### 12.1 Default strict sequence

```text
decision #90 + migration 0008 + decision #93 established
  -> current-pin decision-#92 bounded publication already completed (events 8/9)
  -> P4-0 residual #93 global-Go/selection/closure reconciliation
  -> P4-0P freeze both §1.3.1 presentation behaviors + Decision #64 amendment (Q19) + approved
          demand-forecast parity amendment
  -> P4-2 source/contracts only
  -> P4-3 source publication/selection only
  -> P4-1 append migration 0009, complete exception/truth-table contract, repair the served aggregates
          under the approved amendment, and repeat bounded publication on final pin
  -> P4-4
  -> P4-5
  -> P4-6
  -> P4-7
  -> P4-8 append inventory-serving migration 0010
  -> P4-9
```

### 12.2 `P4-D0` disposition

```text
resolved by as-built ordering:
  bounded current-pin publication happened first
  -> source-only P4-2/P4-3 may follow P4-0
  -> P4-0P parity amendment may run in parallel with the source track
  -> one required final-pin P4-1 publication remains, after P4-0P is approved
```

Decision #90 and migration 0007 retired the duplicate authority-generation-1 scopes; migration
0008 and events 8/9 now serve one bounded v5 authority. `P4-0` implements the remaining global Go
validation, selection lifecycle, migration-aware closure, and historical-ledger disposition.
Decisions #87/#91 retain the three rejected full-range remedies and Decision #92 is the active
bounded-capability contract. Source-only work cannot train a forecast, run interval-consuming
engines, or publish live Phase 4 values.

### 12.3 Review gates

1. **Entry review:** one-live bounded v5 authority, events 7→8→9, global Go validation, source
   selection, Phase 3 closure reconciliation, and migration-0008 alignment.
2. **Interval review:** decision-#87/#91 rejection integrity; decision-#92 publisher/schema/exception/
   verifier implementation; published-versus-withheld result after untouched confirmation.
3. **Source-contract review:** lane/store/inbound/term/capability semantics before generation.
4. **Publication review:** Gate A/B/readiness/selection/new-pin forecast evidence.
5. **Phase 4 contract review:** policy/run/verifier/OpenAPI/14 matrices before engines/pages.
6. **Engine review:** reusable foundation before optimizers; deterministic full-pin results.
7. **Replay review:** incumbent, cohorts, oracle, calibration, holdout, verifier.
8. **Serving review:** materialization/activation/API lineage and fail-closed behavior.
9. **Page reviews:** one review per destination plus final Demo 4 review.

---

## 13 · Risks and mitigations

| Risk | Consequence | Mitigation |
|---|---|---|
| Decision-#92 publication regresses or remains contract-incomplete | H5+ P90 reappears, or null rows lack an enforceable reason/series exception | Retain the live pre-export withholding regression; complete strict truth-table and exception controls; independently verify served and withheld rows |
| Withheld P90/confidence is coerced to zero | New and least predictable products receive zero safety stock or risk while appearing confidently served | Require availability+reason branching in schema, DB, API, UI, and engines; add no-null-to-zero properties |
| An aggregate written before withholding silently mixes populations | Already measured: at 26 weeks the served confidence for 398 cold-start series reads 0.0814 against a covered-week 0.5817, and 372 of them return an interval total below their central total. It applies at 8, 13 and 26 weeks — every selection except the 4-week default — and nothing coerces a null, so no null-handling check catches it | Confine interval aggregates to the weeks that carry an interval on both sides of a ratio, freeze one presentation behavior per field before implementing or testing, publish the covered/withheld window, scan aggregated interval values as nullable, and regression-test at 4/8/13/26 selected weeks |
| Row exceptions mask a systemic consumer mismatch | Varied v13 terms can remove an entire market's cold-start demand from reorder | Declare cold-start H5+ as partial, expose all skipped shares, mark the market sub-capability unavailable at 100% skipped SeriesKeys or demand, and permit stricter pre-result thresholds |
| Exception policy remains v1 while a new class is emitted | Artifact identity and downstream classification disagree | Version the policy/fingerprint/schema; emit one series-level H5–H26 record and reconcile its projection |
| Rejected C6/C7 calibration is revived because its aggregate number looked attractive | A preregistered stop rule is silently nullified | Keep both rejection records executable; refuse grid extension, band relaxation, and confirmation refit |
| Deleted prior forecast generation confuses authority | Wrong/nonexistent version selected | Rebuild becomes one authority; honest hashed/unhashed supersession ledger; no reconstruction |
| Model-policy refit mints a parallel or unchained authority-generation-2 authority | Multiple forecasts serve one audience or history splits at the scope-version boundary | Enforce decided #90 globally; serialize activation and require continuation from the selected predecessor |
| A serving/evidence pin disagrees with the stage head or 0008 is edited after application | Nullable rows are refused, strict truth is bypassed, or migration history diverges | Append 0009 for forecast-contract completion and 0010 for inventory; advance DB/ML/Go/tests/closure together and retain the v5 active-view assertion |
| Active version's immutable bundle is deleted | Servable projection cannot be independently re-verified or safely rolled back | Fail closed; set `bundleBytesRetained: false`; supersede it; never reconstruct original evidence |
| File replacement is mistaken for decision-#73 selection | Unapproved source pin becomes forecast authority | Implement #93's candidate→approved→active adoption and legacy-unselected disclosure; require real supersession for every later selection |
| Decision-#89 adoption changes the next source identity | Downstream lineage moves once even when the authoritative source content is unchanged | Record the old→new adoption/re-pin explicitly; exclude only declared logical objects; retain canonical control totals/ordered row digests as semantic evidence |
| A later adapter restores dual or dialect-shaped location fields | Source-neutral Phase 4 roles regress despite decided #88 | Keep exact option-(a) contract tests and reason-coded refusal for missing neutral fields |
| Quality findings are inserted after publication controls | Exported rows exist but manifest count/digests attest zero, making critical-row gates unfalsifiable | Compute controls after all inserts, or version an explicit exemption with a separate exported-row count/digest |
| New source pin changes forecast behavior | Hard gate regresses | Refit/re-accept on new fingerprint; no cosmetic re-pin |
| Final source repin changes a gate the current-pin bounded run passed | Final-pin Phase 4 forecast is rejected | Repeat the frozen method once on the selected pin and retain an honest rejection; do not tune against the result |
| Fulfillment availability precedes occurrence | Future fulfillment enters replay | V13 derivation + B05 placement; diagnostic max timestamp only before v13 |
| Store inventory overgenerated or residual stock omitted | False availability or impossible dead stock | Emit active-or-residual cells; omit inactive zero state; time-qualified reconciliation |
| Fulfillment occurrence mistaken for lane policy | Wrong planning routes | Source-declared lanes; occurrence used only for reconciliation |
| Store cost silently borrowed from DC | Misstated valuation/ABC | Cost-carrying transfer receipts and canonical store WAC; labelled fallback only |
| Monday/Thursday or timezone offset is implicit | Replay mismatch/future state | Preceding-Thursday bridge vectors per IANA timezone and oracle reproduction |
| India West cannot resolve policy v2 | One supported market cannot run | Version-aware inventory override resolver; exact India/US positive and negative vectors |
| Channel is aggregated away or double allocated | Wrong reorder/ATP by channel | `P4-D16`, explicit lane type, node-pool conservation, no direct DC default |
| Supplier terms pass schema but remain degenerate | Misleading safety stock | Sufficiency/variation gates and lead-time std requirements |
| Dependent demand double-counts store demand | Excess DC inventory | Store orders are the sole DC operating stream; fulfillment forecast is cross-check |
| Transfer/allocation objectives are tuned on outcome | Overfit optimizer | Freeze objectives/tie-breaks/materiality before replay |
| Five-percent calibration leaks into holdout | False policy acceptance | Stable key cohort hash, full-key isolation, independent verifier |
| NRV/provision scope leaks Phase 5 assumptions | Fabricated finance values | Explicit unavailable unless policy adopted pre-implementation |
| Screen parity pressures fabricated data | Untruthful UI | Element-level unavailable behavior and per-value authority matrix |
| Read-only actions accidentally mutate | Scope/security breach | No mutation endpoints/handlers; disabled controls; negative tests |
| Serving falls back to files/legacy version | Stale/ungoverned result | PostgreSQL-only handlers and fail-closed active view |
| Full run exceeds 16-GB target | Non-portable build | Small fixture, bounded batches, safe/performance logical-equivalence evidence under #89, stop on ceiling |

---

## 14 · Approval block

### 14.1 Remaining approvals and freezes

No design decision blocks starting `P4-0`. `P4-D0` is resolved by the as-built ordering; Decisions
#88, #89, #92, and #93 are frozen. The following actions/freezes gate their owning later package,
not Phase 4 entry:

1. Complete Decision #93's global Go revalidation, Decision-#73 lifecycle, migration-0008 closure
   reconciliation, and as-built events-7→8→9 evidence.
2. Complete Decision #92's versioned series exception and strict availability/reason truth table,
   append migration 0009 without rewriting applied 0008, then repeat the bounded publication on the
   final selected source pin. C8 remains rejected and H4 remains fixed unless a new preregistered
   mechanism supersedes #92.
3. **`P4-0P` gate — freeze both §1.3.1 presentation behaviors and approve the Demand Forecast parity
   amendment before `P4-1` implements the served-aggregate repair.** The plan recommends freezing the
   interval total as option 1 immediately, since it changes no rendered element and needs no
   amendment, which leaves confidence as the only item needing screen review; for confidence it
   recommends *unavailable when mixed*. `P4-4` inherits the approved amendment and does not ratify it
   retrospectively. The gate also carries the Decision #64 amendment — likely Q19 — because #64 freezes
   the parity contract's Q1–Q18 including the workbench-sum semantics this repair changes. Without both
   the amendment and the approval, non-serving implementation and isolated tests may proceed but `P4-1`
   task 9 cannot reach its serving/activation exit, and no changed confidence response ships in either
   direction: correcting the value and suppressing it are both presentation changes.
4. Retain Decision #88 option (a) without interim dual spelling and retain Decision #89's
   implementation/adoption evidence, including logical-mirror exclusion, byte-stable restricted-
   object retention, all-excluded refusal, and the one-time next-landing re-pin.
5. Capability split and temporal-evidence-policy v2.
6. Active-or-residual store inventory scope and cost-carrying store transfer receipts.
7. Source-declared typed replenishment/customer-fulfillment lanes and exact/default-channel
   resolution.
8. External/internal supply-term model and precedence; do not cap varied terms at H4.
9. ISO-Monday replay clock, preceding-Thursday local bridge, timezones, and lead-time arrival
   rounding.
10. DC dependent-demand operating method and validation-only withdrawal forecast.
11. Store WAC/ABC basis.
12. Exact replay acceptance math, incumbent identity, and materiality/tolerances.
13. Calibration/holdout key and seed.
14. NRV/provision unavailable scope.
15. Read-only exception/action/ERP behavior.
16. `P4-D16` channel-to-node aggregation, constrained allocation, and direct-DC rule.
17. `P4-D17` implementation: cold-start H5+ is partial; current H2 is pin-specific; 100%-skipped
    market cohort and no-remaining-row floors are fixed. P4-4 may approve stricter pre-result limits.
18. One bundle/activation for all 14 screens and the artifact → screen → endpoint mapping.
19. Work-package ordering and review gates.

### 14.2 Not approved by plan creation

Creating this file does not approve:

- any decision amendment or new decision;
- a new cold-start interval mechanism or any extension beyond decision #92's H4 boundary;
- source contract v13;
- a new source run or pin;
- Phase 4 policy thresholds/objective weights;
- engine, database, API, or UI implementation;
- NRV/provision values;
- any workflow or ERP mutation;
- activation of the final-pin forecast or any Phase 4 bundle beyond the already live bounded
  Post-Phase-3 authority.

### 14.3 Evidence required to authorize the next package

Each package begins only when its entry evidence is linked from an updated plan/task/evidence record.
A verbal “continue” does not substitute for a missing pre-result decision, contract fingerprint,
capability verdict, accepted artifact, or required human approval.

---

## 15 · Final definition of done

Phase 4 is complete only when all are true:

1. Phase 3 implementation and closure evidence agree; Decision #93 is implemented; Decision #90 is
   enforced across all policy-derived scope fingerprints; the staged migration chain is 0008 at
   entry, 0009 after forecast-contract completion, and 0010 after inventory serving, with every
   client/evidence pin advanced together; event 7's incident and events 8/9 are retained; and every
   later replacement continues the append-only non-null successor chain.
2. Decision #85 is a hard fail-closed acceptance-v5/verifier-v5 gate and no v4 materialization can
   satisfy it.
3. Decision #87's C6/C7 and decision #91's C8 full-range rejections remain immutable; the accepted
   C5 identity and decision #92 availability/exception policies are bound into run/version lineage;
   every published cold-start/established P90 cell passes 0.85–0.95 globally and in both markets;
   H5–H26 cold-start rows retain P50 and carry reconciled explicit interval unavailability; and every
   weighted-confidence computation covers only the weeks that carry an interval and publishes that
   window; whole-population A2 still scores all 708,708 rows; the `P4-0P` parity amendment is approved
   and inherited by `P4-4`; and confidence and the interval total each follow their frozen §1.3.1
   presentation choice at 8, 13 and 26 weeks — served with visible scope, or absent with the approved
   reason — with no unqualified interval value beside a differently scoped central value.
4. A new immutable source publication supplies active-or-residual store inventory, typed lanes,
   correctly placed fulfillment/status events, origin-safe inbound history, and replay-eligible
   varied supplier terms.
5. `inventory_replenishment_current_snapshot` and `inventory_replenishment_replay` are both
   `ready + sufficient` under an active #73 selection.
6. The forecast is refit, accepted, independently verified, materialized, and activated on the same
   new publication fingerprint.
7. Inventory-policy v2 resolves exactly for both live market/currency pairs; its Monday/Thursday,
   timezone, channel, and all run/acceptance/verifier/OpenAPI/screen contracts are frozen and
   fingerprinted.
8. Python and Go pass the same executable policy/golden vectors.
9. ISO-Monday weekly replay constructs opening/closing state from the preceding Thursday bridge in
   each market timezone and reproduces the observed oracle within frozen tolerance before scoring.
10. Candidate replay passes fewer stock-outs/lost units, lower inventory, and no-worse fill under
    the frozen global/per-market acceptance rules.
11. The deterministic 5% calibration and untouched 95% holdout both pass and are independently
    verified against the same lineage.
12. Transfer/allocation/valuation/ageing/expiry/risk outputs pass all conservation, channel, cost,
    capacity, budget, lane, critical-quality, and local-money constraints.
13. One immutable Phase 4 bundle is transactionally materialized and separately activated; exactly
    one version is active per scope and serving fails closed otherwise.
14. Go reads PostgreSQL only and all inventory/replenishment endpoints return lineage-matching live
    values or governed 409/503.
15. All 14 pages preserve approved HTML parity and show live market/location/lane-scoped evidence,
    with unavailable elements and disabled actions exactly as approved and nothing fabricated.
16. Every page has independent desktop/mobile parity and human sign-off.
17. Manual Windows/macOS/Linux and safe/performance evidence is retained; no repository CI is added.
18. Decision #88 is implemented as one neutral field vocabulary across every new Phase 4 role and
    adapter path; no new consumer depends on the interim dual-spelling workaround.
19. Decision #89's frozen identity semantics are enforced; the one-time adoption/re-pin is
    recorded; repeated pinned-writer/profile identity is stable; and cross-profile logical
    equivalence is evidenced by matching canonical schemas, control totals, and ordered row
    digests.
20. Every exported `quality_violations` row is covered by matching publication controls or the
    approved versioned exemption count/digest; the current 2-row/0-control defect cannot recur.
