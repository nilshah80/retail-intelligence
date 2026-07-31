# Post–Phase 3 Implementation Plan — Retailer onboarding, forecast quality and presentation

_Companion to `plans/local/plan.md` and the two deferred Post–Phase 3 sections in
`plans/local/tasks.md`._
_Ingestion authority: `ingestion/README.md`, `contracts/profiles/profile.schema.json`,
`contracts/staging/staging.yaml`, `contracts/retail_v2/schema.yaml`._
_Forecast authority: `docs/demand_forecast_poc_spec.md` §3.1–3.4, §3.9, §4.2–4.4 and §4.8;
`contracts/ml/*`; `contracts/screens/demand-forecast.parity.yaml`._
_Validation authority: `contracts/validation-policy.yaml`; repository CI is prohibited._

**Revision 11 — 2026-07-31. FORECAST ACCEPTED under decisions #84/#86; PP3-A1+ IMPLEMENTED,
AUTHORIZATION STILL PENDING THE RETROSPECTIVE.**
Accepted run `fr_b2ef3d33f398095b` (`candidateClass: gate_remediation`, version
`fv_23722eff8e3b8995`) passes A1-A5 and is verified, materialized and activated. C5 repairs the
us-new-york cold-start gate from -2.399% to +4.446%; decision #75 is published at +1.754% against
its 5% floor and is **not** satisfied, so C5 carries no accuracy claim. Decision #85 per-cohort
coverage is now a HARD gate (acceptance-v5 / verifier-v5, migration 0007) and the accepted run
passes it over published intervals under decision #92.

**Superseded status text, corrected 2026-07-31.** The paragraph below said the builder still binds
standardized views to Shopify/Business Central sources and that a mapped-files-only retailer cannot
complete an end-to-end run. That is no longer true and was left contradicting the rest of this
document: `build_staging()` now completes for a mapped-files-only retailer, proven by
`test_a_mapped_retailer_completes_the_whole_builder`, after six couplings were fixed (standardized
views, the quarantine pass, the profile schema and injected role catalog, the location crosswalk's
topology dependency, its coverage union, and the upstream manifest requirement). Adapter-level
rejects now also reach the shared quarantine through a generic drain pass.

What remains genuinely unwired is **readiness and tenant selection**: `resolve_selection()`,
`verify_against_publication()` and `build_readiness_report()` have no caller outside their own
definitions, so every ML stage still resolves through `contracts/ml/expected-pin.json`. That is a
designed and unit-tested library, not an operational onboarding boundary, and the task ledger now
says so rather than claiming the pin assumption was replaced.

Historical text follows, retained for provenance rather than as current state: readiness and tenant
selection have no runtime callers. PP3-A1-A3 go-ahead still requires the retrospective.

**Revision 10 — superseded 2026-07-31. DECISIONS FINALIZED; FORECAST NO-GO; PP3-A1+ NOT AUTHORIZED.**
The final adversarial review invalidates both the former v12 forecast and verifier-v2 run
`fr_92135aa7b5215b69`. The latter drops 102,804 harder rows from A1's seasonal-naive comparison,
so acceptance-v2 fails the spec's overall gate despite the paired subset exceeding 25%.
Feature-schema-v6, forecast-run-v2, verifier-v3 and migration 0005 repairs are implemented
and committed on `main`. V6 removes the false h1 local-event availability indicator, its permanently-null future
features and the unavailable market-disruption feature under driver-semantics-v3. A full-column
invariant now rejects any structurally all-null feature. A new backtest/publication has not established
accepted evidence.
PP3-P0 therefore remains open for the full rerun, developer gate, listed manual Phase 3 gates,
known Forecast Health visual-parity disposition and retrospective. Track A/B
implementation begins only after the complete Phase 3 exit and a recorded retrospective
go-ahead. The plan deliberately orders
**retailer-source onboarding hardening before forecast-quality and presentation hardening**.
That order protects the central architecture promise: retailer variation is absorbed by
profiles/adapters and standardized staging roles; canonical transforms, ML, API and UI do not
gain retailer-specific branches.

The PP3-P0 repair implementation is committed. Decision #82 is now finalized; its
acceptance-v3/verifier-v4/migration-0006 implementation and the other PP3-P0 exit evidence remain
open. Do not begin PP3-A1 or later, create a new input pin, tune thresholds/models, change the UI,
modify datagen or run a new full backtest until the applicable implementation gate below is
passed.

---

## 0 · Recommendation, status and approval boundary

### 0.1 Recommended order

The requested order is correct:

1. **Close Phase 3 completely.**
2. **Track A — retailer-source onboarding hardening.**
3. Review a real client-shaped readiness report and accept/reject the new ingestion boundary.
4. **Track B — forecast-quality and presentation hardening.**
5. Publish and activate a new forecast version only if the unchanged acceptance battery and the
   additional improvement-comparison gates pass.

This document specifies Track B now so the whole program can be reviewed, but PP3-B1 and later do
not start until Track A is accepted. Otherwise a quality change could accidentally depend on the
synthetic Shopify/Business Central/companion layout that Track A exists to remove.

### 0.2 Why Track A must come first

Schema conformance is necessary but not sufficient for ML authorization. A retailer extract can:

- parse successfully but omit a required business role;
- populate canonical columns but lack defensible historical `known_as_of` evidence;
- contain sales but not prove SKU × store × channel assortment coverage needed to interpret a
  missing sale as zero demand;
- support descriptive analytics but not origin-safe historical replay;
- support non-PIT forecasting but lack promotion plans, future weather or competitor evidence;
- pass ingestion while remaining statistically insufficient for a particular ML gate.

Improving the model before these outcomes are explicit would optimize against the demo platform
shape instead of the canonical business contract. Track A makes readiness capability-specific,
then Track B consumes only the capabilities that are actually available.

### 0.3 Current phase gates

| Gate | Current state | Required before |
|---|---|---|
| Review-#2 semantic repairs and focused tests | Passed and committed | Full PP3-P0 rerun |
| Feature-schema-v6 build and characterization | Passed; `f3ff8725d36d78ff…`, 1,072,430 rows | Backtest |
| Short-history A1 comparator/eligibility policy (#82) | Decided; acceptance-v3/verifier-v4/migration-0006 implementation open | Backtest |
| Decision-#82 acceptance/verifier run independently recomputes and passes its A1–A5 battery | Open; prior acceptance-v2 run fails A1 | PP3-A1 |
| Decision-#82 verifier result and `tools/dev.py verify` pass | Open; activation is required only on the accepted branch | PP3-A1 |
| Phase 3 manual Windows feature/training/publication-or-rejection evidence | Open | PP3-A1 |
| Phase 3 manual Linux feature/training/publication-or-rejection evidence | Open | PP3-A1 |
| Full pinned-data 16-GB vs high-performance benchmark comparison | Open | PP3-A1 |
| Explicit user approval of the Demand Forecast live or governed-unavailable UI state | Open | PP3-A1 |
| Forecast Health four-row HTML-parity disposition | Open; correction planned in PP3-B7 | UI approval must explicitly accept deferral or authorize an earlier correction |
| Post–Phase 3 retrospective go/no-go and scope | Open | PP3-A1 |
| Track A contract/design review | Open | PP3-A2 |
| Track A client-shaped round-trip acceptance | Open | PP3-A9 / Track B |
| Track B diagnostic and candidate protocol review | Open | PP3-B1 |
| Track B UI target/parity review | Open | PP3-B7 |

### 0.3.1 PP3-P0 accepted and NO-GO closure branches

Decision #82, a new complete-population decision-#82 verifier-v4 run, the
stateful local gate, manual Windows/Linux evidence, the full v6 profile/memory comparison and the
retrospective survive on both branches.

| Exit item | Accepted branch | Explicit NO-GO branch |
|---|---|---|
| Acceptance evidence | independently verified A1–A5 pass | independently verified rejection with complete reason-coded diagnostics; eligible for D0 only if it meets §2.9 |
| PostgreSQL | decision-#82 verifier materialization plus separate activation | zero materialization/activation for the rejected run; prove `active_forecast_versions` is empty |
| API | live accepted lineage and governed 409/503 behavior | governed 503 unavailable behavior and no fallback to verifier-v2 |
| UI review | live accepted values plus known parity disposition | governed-unavailable state, with no stale forecast values presented as live |
| Forecast Health | approve the corrected four-row state, or use the accepted-live deferral record below | use the governed-unavailable deferral record below; four-row live-value parity remains a PP3-B7 obligation |
| Portability/performance | full required evidence | full required evidence for feature build, rejected backtest/publication path and fail-closed serving |

Required accepted-live deferral text when an accepted forecast is served before the four-row
correction:

> Phase 3 UI approval covers the live accepted Demand Forecast values and current layout. The
> reviewer was informed that Forecast Health currently shows only h1/h4 under the default
> four-week operational cap and uses cumulative, coverage-only semantics instead of the reference
> exact h1/h4/h8/h13 rows and decision-#80 statuses. Forecast serving is authorized, but this
> deviation is not accepted as HTML parity and remains PP3-B7 work.

Required governed-unavailable deferral text on the explicit NO-GO branch:

> Phase 3 UI approval covers the governed-unavailable Demand Forecast state only. The reviewer was
> informed that the current live-data implementation would show only h1/h4 under the default
> four-week operational cap and uses cumulative, coverage-only health semantics instead of the
> reference h1/h4/h8/h13 rows with governed Strong/Healthy/Watch/Action statuses. No live forecast
> is authorized. Decision #80 is final, but its PP3-B7 implementation remains open; this state was
> not accepted as HTML parity.

### 0.4 Workstream states

| Workstream | Contents | State |
|---|---|---|
| PP3-P0 | Phase 3 repair, evidence rebaseline, closure and retrospective | **IN PROGRESS** |
| Track A / PP3-A1–PP3-A9 | neutral roles, mapped files, custom adapters, readiness, tenant pins | **AWAITING PP3-P0** |
| Track B / PP3-B1–PP3-B8 | diagnostics, candidate models, policy v2, presentation, publication | **AWAITING Track A** |
| Later productionization | connectors, CDC, secrets, IAM, managed orchestration | **OUT OF SCOPE** |

### 0.5 Non-negotiable invariants

1. The accepted v12 source publication remains the immutable input authority. Forecast v1 runs
   `fr_b2f18d0e2999a36d`, `fr_ab5be7296a2c416e` and `fr_92135aa7b5215b69` are rejected and must
   not be served. No accepted C0 serving
   or publication authority exists until a versioned decision-#82
   acceptance-v3/verifier-v4 candidate passes. A separately governed complete-population diagnostic
   baseline may be used only for model comparison under §2.9 and PP3-B1; it never authorizes
   publication or serving.
2. Do not modify acceptance thresholds to make a candidate pass.
3. Do not change datagen to manufacture greener forecast metrics.
4. A datagen change is allowed only for a reviewed source-contract correction or to model
   evidence a real retailer source is expected to supply; it produces a new immutable source run.
5. Track A may change the shared ingestion framework once. After Track A is accepted, onboarding
   a new retailer may add only landing configuration, profiles/mappings, a bounded adapter when
   necessary, conformance fixtures and an explicit publication selection. It must not change
   shared landing/staging/transform behavior or introduce retailer branches in ML, API or UI.
6. `known_as_of` is derived only from native observation/posting/extract/snapshot evidence or an
   explicitly downgraded landing-time rule. Business-effective dates never prove availability.
7. Missing sales do not become zero demand without extract completeness and assortment/listing
   evidence at SKU × store × channel × business date.
8. Ingestion readiness and statistical sufficiency are separate verdicts.
9. Parquet/JSON bundles remain immutable ML authority; PostgreSQL remains the API serving
   projection. Request handlers do not read Parquet or DuckDB.
10. No repository CI is added now or later. Supported-OS evidence is developer-run and recorded.
11. No accepted artifact, policy or publication is overwritten. Every material semantic change
    receives a new version and semantic fingerprint.
12. No presentation change may hide weak slices, relabel a metric or substitute an easier
    aggregate for SeriesKey accuracy.
13. The original HTML remains the visual authority until explicitly amended. A known deviation
    may be deferred only when the visual-approval record names it; browser smoke or live-data
    correctness alone is not HTML parity.
14. Generated artifacts are not source code. Parquet datasets, model binaries and complete
    forecast bundles stay outside Git. Generated report JSON is untracked by default; only an
    explicitly reviewed compact evidence index may be committed under the retention policy in
    §1.7.

---

## 1 · Verified starting point

### 1.1 Accepted source and rejected forecast evidence

The source pin remains accepted. Both forecast generations are rejected under the current
authority. The table records the latest verifier-v2 run only as reproducible diagnostic evidence;
migration 0005 excludes it from the active view.

| Item | Value / status |
|---|---|
| Source snapshot | `681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b` |
| Curated publication fingerprint | `db3784fdcc4cb8334c2e17d6ae7e0216d05597659df4e9565a99f2b21b8d6fff` |
| Curated publication root / objects | `run-c5eb1506ecd4c550` / 1,509; exact `expected-pin.json` match |
| Rejected diagnostic bundle generation | v15: `forecast_run_accepted_db3784fdcc4cb833_pitfix_v15` / `fr_92135aa7b5215b69` |
| Other rejected v1 bundles | v12: `fr_b2f18d0e2999a36d`; v14: `fr_ab5be7296a2c416e` |
| Historical version | `fv_7d29221dc70dea90` |
| Forecast semantic fingerprint | `8932650d0b1b956eb821e5933ca8462dba6f87fc1a58b50348fe54273026d04f` |
| Activation scope | `b38c230b63728dc9c4d16648415b70547c04553cfd7fb53161e56683f73da2e7` |
| Feature semantic fingerprint | `1edd93f17b01fa8ba9d7fde51df0f9124954fed2658c9b345e93fbf7d4bc7f58` |
| Superseded v4 feature fingerprint | `defa5a48a6f9a1bf72064c669d251e7d3428747abd493c79abcfe0b80dbd6943`; rejected because its horizon-derived local-event indicator falsely reported h1 availability |
| Superseded v5 feature fingerprint | `b0ca33309f04e9f6b4ad47e827e588e97813b388a033e3b28e1c1f1249126072`; rejected because its market-disruption feature was all-null |
| Repaired v6 feature fingerprint | `f3ff8725d36d78fff9422155d2e4362bcdac174af8e39f383040e7c587de42c5` |
| Repaired v6 context evidence | origin count non-null on 1,072,430 rows / 523 origins; zero unavailable future-feed columns; zero all-null columns |
| Correct-pin feed sweep | unavailable: promotions 811, calendar events 182, local events 2,266, disruptions 24; origin-visible: macro 7,306, competitor 300,611, weather actual 7,306, weather forecast 51,142, calendar 7,306 |
| Evaluation schedule | 26-week window, step 2, 13 scoring origins, 104 training origins |
| Evaluation rows | 708,708 |
| Current-cycle SeriesKeys / rows | 2,034 / 52,884 |
| Historical v15-bundle evaluation SeriesKeys | 2,228 distinct across all origins; 2,118–2,166 per origin |
| Paired-only seasonal-naive WAPE improvement | 53.47% global; 54.54% India; 52.00% US |
| A1 pairing | 605,904 / 708,708 rows; 77.51% of actual units; incomplete → fail |
| P90 coverage | 88.85% global; 89.22% India; 88.51% US |
| Slow-mover evidence | 218 global; 118 India; 100 US; all 13 origins |
| Current-cycle policy | decision #60 / classification policy v1 |

The rejected run remains diagnostic evidence only: global accuracy is 71.82% with
−6.72% bias; India is 72.99% with −4.75% bias; US New York is 70.35% with −9.17% bias; and
exact-horizon accuracy declines from 78.16% at h1 to 69.51% at h26. Its descriptive relative
evidence is +30.61% FVA versus MA13 and 88.85% P90 coverage; the 53.47% seasonal-naive number is
paired-subset evidence and not a passing overall A1 claim. Neither rejected run may be presented
as active or used as the Track B comparator.

The v15 bundle's evaluation Parquet is byte-identical to the v14 invalid bundle payload
(`96d8db758983cdb9…`), but the bundle generation and run id are v15. The 194-SeriesKey difference
between the historical evaluation union and the 2,034 current cycle
is lifecycle/origin dependent but must not be hidden behind aggregate arithmetic. The 102,804
missing seasonal-naive comparisons affect 402 distinct SeriesKeys and vary by origin/horizon cell
(276–324 rows), so decision #82's eligibility unit is the complete
`forecast_origin × horizon × SeriesKey` evaluation row, not a one-time series exclusion. These are
historical v15-bundle diagnostics and must be remeasured on the v6 PP3-P0 run.

All three historical bundles are `retail-forecast-run/v1` and self-declare `accepted` under the
superseded v1 acceptance policy. Their bytes and manifests must not be edited or re-signed.
PP3-P0 publishes one external rejection/supersession ledger that binds each run id, original
directory, manifest/artifact hashes, superseded policy, rejection reason and the decision-#81/#82
authority. The misleading directory labels may be moved only as a byte-preserving artifact-store
operation with an old→new logical-path alias; the rejection ledger—not a rewritten manifest—is
the lifecycle authority. Migration 0005 already blocks verifier-v2 serving, and migration 0006
must admit only verifier-v4.

### 1.2 Known Forecast Health visual-parity deviation

The original HTML always renders four rows — `1 week`, `4 weeks`, `8 weeks`, `13 weeks` — even
when the toolbar defaults to `Next 4 Weeks`. The current React implementation filters
`[1, 4, 8, 13, 26]` by the selected horizon, so the default renders only `Weeks 1–1` and
`Weeks 1–4`. The API already exposes all 26 additive horizon rows; this is not a data or serving
limitation.

The current implementation also cumulatively aggregates horizons `1..N` and derives status from
coverage alone, whereas the reference labels discrete checkpoints and shows the four-state
vocabulary `Strong / Healthy / Watch / Action`. Decision #64/Q6 and the parity YAML previously
encoded the hiding behavior. This correction pass amends that authority to decision #80's final
four-row policy; PP3-B7 must implement it in React and prove live-data parity.

**PP3-B7's React correction is implemented (2026-07-31).** `ui/src/Forecast.tsx` renders exactly
four exact-horizon rows labelled `1 week`, `4 weeks`, `8 weeks`, `13 weeks`, in reference order,
independent of the operational horizon cap, with decision #80's ordered status matrix and decision
#77's resolved target grain. Governed thresholds are not hand-copied: they are generated into
`ui/src/generated/forecastHealthPolicy.ts` by `tools/generate_contract_types.py`, so
`tools/dev.py contracts` fails when the policy contract and the screen diverge — verified by
editing a target and watching the check go stale. Three UI tests cover row count, reference labels
and order, `data-horizon` attributes, absence of a fifth h26 row, absence of cumulative
`Weeks 1–N` labelling, cap-change independence, and four-state status derivation. `knownDeviation`
is now `status: resolved`. Live-value and screenshot parity remain unexercised because serving is
fail-closed under the NO-GO closure; that is recorded as the remaining obligation.

The required PP3-B7 outcome is frozen by decision #80: four exact-horizon rows in reference order
through h13, independent of the selected operational horizon, using its governed status matrix.
This preserves horizon deterioration instead of blending it away. h26 remains in diagnostic
evidence and may appear only in a separately approved drilldown, not as a fifth default reference
row. `contracts/ml/forecast-health-policy.json` is the cross-language authority for target-grain
resolution, units, ordered all-condition status evaluation, h26 diagnostic targets and executable
vectors. The parity contract carries `PP3_B7_REACT_IMPLEMENTATION_PENDING` until React consumes
that policy.

The original HTML remains layout authority, but its four sample coverage/badge values are
non-authoritative placeholders superseded by decision #80: its 99.6% and 98.7% coverages exceed
the accepted interval and would correctly classify as `Action` under the finalized policy.
The PP3-B7 visual-approval record must state this explicitly so screenshot comparison preserves
the layout and labels without treating sample badge colors as governed truth.

### 1.3 What is already source-neutral

The current design has a sound intended boundary:

```text
immutable landing
  → Gate A
  → profile / adapter
  → standardized staging
  → source-neutral transforms
  → retail_v2 candidate
  → Gate B
  → curated publication
  → unchanged ML / API / UI
```

Positive existing foundations:

- `SourceAdapter` separates raw-view registration from staging materialization.
- physical readers support Parquet, CSV, JSONL and JSON without owning retailer semantics;
- the profile schema records source instances, formats, keys, grain, money, quantity,
  availability and capability declarations;
- canonical transforms import standardized `stage_data.*` view names and are protected by import
  boundary tests;
- Gate A, Gate B, publication, ML input verification and immutable forecast publication are
  already fail-closed;
- the API serving projection is already separated from immutable ML artifacts.

Track A extends these foundations; it does not replace the whole ingestion pipeline.

### 1.4 Verified coupling that prevents a universal retailer claim

The current staging contract defines exactly six envelopes plus one supporting assortment
dataset. The runtime needs many more standardized relations, and currently creates them by
hard-coded source-table selection:

- `merchandise`, `adjustment`, `fulfillment`, products, locations and prices bind directly to
  `shopify_*` relations;
- inventory, receipts, product references, supplier terms and operational roles bind directly to
  `bc_*` relations;
- assortment, calendar, FX, weather, event, macro, competitor, promotion and allocation roles
  select directly from `companion_*` relations;
- shared quarantine rules name those same platform tables;
- location crosswalk construction reads `stage_data.shopify_locations`;
- the registry imports only the three built-in adapter modules;
- the profile schema has dataset declarations but no machine-readable mapping from arbitrary
  source fields into standardized role fields;
- the staging `row_provenance` vocabulary contains platform-shaped values such as
  `SHOPIFY_ACTUAL`/`SHOPIFY_DERIVED`, rather than keeping source identity separate from a neutral
  actual/derived/synthetic provenance class;
- `contracts/ml/expected-pin.json` is one committed demo selection, not a retailer/tenant
  publication-selection mechanism.

Source-specific names inside an adapter are correct. Source-specific names in shared staging
assembly, quarantine, crosswalk or consumers are the coupling Track A must remove.

**PP3-A1 correction (2026-07-31).** Two further facts were measured and are now frozen in
`contracts/staging/role-map.yaml`:

1. The canonical transform is **not** source-neutral today. `transforms/core.py:851` and
   `:1073` join `location_crosswalk` on the literal predicate `x.source_system = 'companion'`.
   The list above claimed the transform layer consumed only standardized relation names; that is
   true of relation names but not of this predicate. Neither join fails closed: the
   competitor-price join is a LEFT JOIN, so a retailer whose competitor evidence arrives under a
   different `source_system` silently resolves every location to NULL, and the allocation join is
   an inner JOIN, so the same mismatch silently drops every allocation row. PP3-A3 must resolve the
   crosswalk by role and declared provider identity, with a negative fixture whose context evidence
   arrives under a non-companion `source_system`.
2. The `dimension_signal` envelope has **no runtime consumer**. No canonical transform, Gate-B
   check, crosswalk or mapping reads `stage_data.dimension_signal`; all 16 payload kinds already
   reach transforms through the 15 typed derived relations. §2.3's earlier assessment of it as the
   largest typing change in PP3-A2 and the hardest PP3-A3 parity case was wrong in the opposite
   direction: it is dead weight to retire, not an opaque payload to reconcile. Its only references
   are `ingestion/tests/test_adapters.py` and the six-envelope assertion in
   `contracts/python/src/retail_contracts/entities.py:337`.

### 1.4.1 PP3-A3 findings — the platform literals were a symptom

Removing the coupling surfaced its root cause, which §1.4 had not identified.

**Nine prohibited joins, not two.** The PP3-A1 scan reported two occurrences of
`x.source_system = 'companion'`. The real count of hardcoded dialect literals in the prohibited
trees was **nine**: eight in `transforms/core.py` and one in `quality/gate_b.py`, all joining
`location_crosswalk` on the literal `'businessCentral'`. My own boundary regex missed them —
`businessCentral` is camelCase with no underscore, so neither `companion|shopify` nor
`\bbc_[a-z_]+` matched it. The detector now lists dialect names explicitly, and a scan of every
prohibited tree returns clean.

**Why the literals existed.** `retail-staging/v1` declares `source_system` a required common field,
but **8 of 13 Business Central staged relations never emitted it**: `bc_sales_control`,
`bc_inventory_batches`, `bc_inbound_shipments`, `bc_transfer_orders`, `bc_waste_events`,
`bc_warehouse_capacity`, `bc_wms_comparisons` and `bc_supplier_performance`. With no column to join
on, a consumer had no option but to hardcode the dialect name. The coupling was a *symptom of an
unenforced contract*, so PP3-A3 fixes the cause at the adapter boundary — where dialect knowledge
is legitimate — rather than papering over it downstream.

**The neutral resolution.** Every crosswalk join now resolves column-to-column on the minting
authority — `x.source_system = <relation>.source_system` — so no consumer names a dialect and
onboarding one needs no downstream change. The crosswalk is built from the standardized `location`
role instead of `stage_data.shopify_locations`, and it carries a descriptive `key_space`
(`source_native` or `canonical_identity`) recording what each row's key *is*.

**`key_space` is a label, not a predicate — and getting that wrong cost two failed runs.** Two
earlier attempts filtered joins on it and both broke, because a single relation legitimately carries
keys from *both* spaces: Business Central rows reference warehouses by their own location code **and**
by the canonical id. Filtering on key space silently drops resolvable rows. A boundary test now
asserts `x.key_space =` appears in no join, in either the transforms or the crosswalk builder.

The first attempt also set `canonical_identity` rows to `source_system = '*'`, which broke Gate B's
own column-to-column joins and took B03 from `positiveSalesOutsideAssortment: 0` to **3,196,131
positive rows outside assortment** — caught only by diffing the run's `gate-b.json` against the
accepted baseline's. Crosswalk row identity is therefore left exactly as it was; only the additional
descriptive column and the consumer predicates changed.

**What fixture tests could not prove.** The ingestion suite passed on fixtures while the real
pipeline failed immediately at the crosswalk with a binder error, because the fixtures never
exercised the BC relations missing `source_system`. Contract-level parity for PP3-A3 has to run the
real snapshot; a green unit suite is not evidence.

#### 1.4.2 PP3-A3 parity evidence — 2026-07-31, exact

The full pipeline ran against the accepted v12 snapshot into a disposable work and publication root.
Every governed identity is **byte-identical** to the accepted publication, which is stronger than
§2.2's requirement of equivalence:

| Identity | Accepted | PP3-A3 rerun | |
|---|---|---|---|
| Publication semantic fingerprint | `db3784fdcc4cb833…` | `db3784fdcc4cb833…` | identical, and matches `expected-pin.json` |
| Gate-B semantic fingerprint | `e4bd23a1b4b4e28a…` | `e4bd23a1b4b4e28a…` | identical |
| Candidate semantic fingerprint | — | — | identical |
| Staging semantic fingerprint | `b4bcc0e0685b6fb4…` | `b4bcc0e0685b6fb4…` | identical |
| Gate-B rules | 21 | 21 | 0 outcome or evidence diffs |
| Capability mask | — | — | identical |
| Reconciliation | zero difference | zero difference | identical |
| Entity counts | 36,224,122 rows | 36,224,122 rows | identical |
| Business and entity controls | — | — | identical |

The accepted publication was never touched: its mtime predates this work and `expected-pin.json`
still resolves.

**Physical layout legitimately differs.** The rerun published 1,499 objects against the accepted
1,509 — different year/month partitions and different `data_N` splits — while every semantic
identity above matches. `contracts/retail_v2/determinism.yaml` sets
`byteEquality.acceptanceRole: secondary_unless_writer_fully_pinned`, so writer-level file splitting
is explicitly not part of acceptance unless the writer is fully pinned. This is the contract working
as designed, and it is worth stating because an object-count comparison alone would read as a
regression when the canonical content is identical row for row.

**One coverage gap noticed.** Adding `source_system` to ten platform-specific staged relations did
not change the staging semantic fingerprint. Staging identity therefore covers the standardized
surface, not the columns of the intermediate `shopify_*`/`bc_*`/`companion_*` relations. That made
this parity result cleaner, but it also means a future change to a platform relation's columns would
be invisible to the staging fingerprint. Recorded for PP3-A9 rather than changed here, because
widening staging identity now would invalidate the accepted pin.

### 1.5 Authority hierarchy after this plan

This plan is a workbench, not a runtime authority. If documents conflict, use:

1. machine-readable schemas, policies and fingerprints under `contracts/`;
2. accepted immutable manifests and artifacts;
3. `docs/OPEN_DECISIONS.md`;
4. `docs/demand_forecast_poc_spec.md`;
5. `plans/local/tasks.md`;
6. this implementation plan.

An approved implementation must reconcile higher authorities before code consumes a new rule.

### 1.6 Explicit non-goals

- building production Shopify, Business Central or arbitrary ERP API connectors;
- choosing a customer’s final cloud file-transfer mechanism;
- implementing production CDC/upsert/watermark semantics decided in #26;
- a general transformation programming language;
- executing untrusted customer Python as an adapter;
- moving the immutable lake into PostgreSQL;
- changing Phase 4–8 inventory, pricing, workflow or admin scope;
- guaranteeing that every retailer has enough history or variation for ML;
- promising a universal 90% SeriesKey accuracy;
- adding CI workflows;
- auto-activating a candidate or sending operational actions.

### 1.7 Repository and artifact-retention policy

Git contains definitions and compact review authority, not generated data warehouses:

- commit schemas, contracts, policies, migrations, source code, tests and small deterministic
  golden vectors;
- keep Parquet datasets, DuckDB files, model binaries, MLflow artifacts and complete immutable
  source/forecast bundles in the configured local artifact root or object store, outside Git;
- keep generated report JSON untracked by default;
- commit a report only when it is a reviewed compact evidence index required for a decision,
  acceptance/no-go record or reproducibility handoff; place it under `contracts/evidence/` and
  have it reference external artifacts by immutable URI/logical path, byte count, SHA-256 and
  semantic fingerprint;
- never commit raw or transformed retailer data, client extracts, credentials, secrets or
  unminimized quarantine payloads;
- superseded evidence is retained in artifact storage and referenced from its replacement. It is
  not copied forward as another collection of tracked generated files.

Immutability describes the artifact store and lineage contract; it does not require large or
generated artifacts to be committed to Git.

Current tracked-report disposition for PP3-P0:

| File | Disposition | Reason / prerequisite |
|---|---|---|
| `phase3-accepted-publication-db3784fdcc4cb833.json` | Remove from Git | historical verifier-v2 acceptance is false authority and is superseded by the reassessment |
| `phase3-serving-stack-db3784fdcc4cb833.json` | Remove from Git | describes a disabled verifier-v2 materialization and is superseded |
| `review2-acceptance-reassessment-db3784fdcc4cb833.json` | Removed 2026-07-31 | superseded by `contracts/evidence/forecast-closure-record.json`, which carries the three-run rejection ledger with its manifest/acceptance hashes and the superseded v15 diagnostic reference forward |
| `w0-memory-spike-safe-16gb.json` | Remove from Git | self-declared non-authoritative v3 evidence; first redirect the `tools/dev.py` default output to the external artifact root |
| `w7-profile-invariance-local.json` | Remove from Git | self-declared non-authoritative v3 evidence; v6 rerun belongs in external artifact storage |

Removal from Git does not destroy the immutable artifact-store copy. The replacement compact index
must link to retained external history by hash.

`ml/reports/` is now empty and ignored. The single reviewed index for the PP3-P0 closure record is
`contracts/evidence/forecast-closure-record.json`.

---

## 2 · Target architecture

### 2.1 End-to-end target

```text
retailer extract / immutable snapshot
  │
  ├─ physical readers
  │    CSV · Parquet · JSONL · JSON
  │
  ├─ adapter selection
  │    mapped_files adapter OR one bounded custom adapter
  │
  ├─ adapter-owned raw normalization
  │    source fields → declared standardized roles
  │
  ├─ role binding and provider resolution
  │    exclusive · union · cross_validate · fallback
  │
  ├─ shared role-schema validation and quarantine
  │    grain · keys · money · time · provenance · evidence grade
  │
  ├─ standardized staging v2
  │    no retailer/platform names
  │
  ├─ unchanged source-neutral canonical transforms
  │
  ├─ Gate B + reconciliation + capability/readiness report
  │
  ├─ reviewed retailer/tenant publication selection
  │
  └─ unchanged features/models/API/UI
       │
       └─ Track B may use only declared origin-safe capabilities
```

### 2.2 Staging v2, not an in-place v1 mutation

**PP3-A2 is implemented.** `contracts/staging/staging-v2.yaml` freezes 35 typed roles at
`retail-staging/v2` with `status: frozen_not_cut_over`, validated by 19 executable tests in
`contracts/python/tests/test_staging_v2_contract.py` and by `validate_contract_tree`, which now
reports `stagingV2Roles` and fails when the catalog and the reviewed role map disagree. Authoring it
surfaced two defects in my own draft that the tests caught: `merchandise`, `fulfillment` and
`adjustment` used key columns that were never declared as fields, and `inventory` carried an
undeclared quantity column.

Introduce a new `retail-staging/v2` contract and preserve v1 until parity is proven. The v2
contract contains:

- a role catalog;
- common lineage/evidence fields;
- one schema per role;
- required and optional role fields;
- role grain and stable key;
- allowed provider-resolution modes;
- field-level money/time/quantity semantics;
- allowed evidence grades and capability effect;
- common quarantine rules;
- role-level controls and reconciliation requirements.

Staging v2 must also make provenance source-neutral. `source_system`/`source_instance` retain the
exact platform or retailer dialect, while orthogonal provenance fields state whether evidence is
client/third-party/synthetic and native/derived. Do not extend a shared enum with one value per
new retailer.

Run v1 and v2 side by side against the accepted v12 source snapshot. The staging fingerprints will
legitimately differ because the contract changed, but the canonical business rows, controls,
Gate-B outcome and capability mask must be equivalent before cutover. Never rewrite the accepted
v12 publication; publish only disposable candidate evidence during parity.

### 2.3 Role catalog

The exact schemas are frozen in PP3-A2. The initial catalog must cover every standardized relation the
current canonical transform consumes.

| Group | Initial roles |
|---|---|
| Demand transactions | `merchandise`, `adjustment`, `fulfillment` |
| Core dimensions | `product`, `product_reference`, `location`, `assortment`, `sell_price` |
| Inventory/procurement | `inventory`, `receipt`, `supplier_term`, `inventory_cost`, `inventory_batch`, `inbound_shipment`, `transfer_order`, `waste_event`, `warehouse_capacity`, `wms_comparison`, `supplier_performance` |
| Reconciliation controls | `invoice_sales_control`, `customer_segment_count` |
| Context | `holiday`, `fx_rate`, `market_disruption`, `customer_segment`, `weather_actual`, `weather_forecast`, `local_event`, `macro_index` |
| Competition/promotion | `competitor_price`, `competitor_match`, `promotion`, `promotion_target` |
| Allocation | `allocation_demand`, `allocation_supply` |

The catalog is not permission to move canonical derivation upstream. `channel` is
`derived_in_transform` from `merchandise.channel_source_key`, exactly as v1 builds
`canonical_data.channels`; it is not a staging role. `allocation_supply` does have a demo-pin
provider inside `dimension_signal` (`allocationSupplyPools`) even though no
typed `stage_data.allocation_supply` relation exists today, so PP3-A2 must type it rather than mark
it absent. Every proposed role must name at least one v1 provider relation/entity kind or carry an
explicit `derived_in_transform`, `absent_in_demo_source` or rejected disposition. PP3-A1 records
both relation→role and role→provider/disposition mappings before PP3-A2 freezes the catalog.

The v1 `dimension_signal` envelope is **retired, not decomposed**. PP3-A1 measured that no
canonical transform, Gate-B check, crosswalk or mapping reads `stage_data.dimension_signal`; the
adapter's 16 declared kinds — `allocationDemandRequests`, `allocationSupplyPools`,
`competitorMatches`, `competitorPrices`, `customerSegments`, `fxRates`, `holidays`,
`localEvents`, `macroIndex`, `pandemicSignals`, `pandemicTimeline`, `promotionSkus`,
`promotions`, `storeAssortment`, `weatherActuals` and `weatherForecasts` — already reach
transforms through the 15 typed derived relations. `contracts/staging/role-map.yaml` binds each
kind to its role and typed relation. PP3-A2 therefore drops the envelope and updates its only two
references (`ingestion/tests/test_adapters.py` and the six-envelope assertion in
`contracts/python/src/retail_contracts/entities.py:337`), and PP3-A3 parity has no opaque payload
to reconcile. Two kinds have no typed relation yet and must gain one: `allocationSupplyPools`
(role `allocation_supply`) and `pandemicSignals` (a second `market_disruption` provider that
decision #67 must resolve explicitly — `exclusive` on `pandemicTimeline` preserves current
behaviour).

Every role descriptor must state:

- role id and semantic version;
- canonical business purpose;
- row grain and complete key;
- required/optional fields and types;
- nullability and controlled enums;
- money unit, currency source and rounding rule;
- business/effective/observation/posting/extract/landing time semantics;
- `known_as_of` derivation eligibility and evidence grade;
- source instance, snapshot, native record and raw object provenance;
- provider-resolution mode;
- invalid-row and ambiguous-row outcomes;
- capability dependencies and downgrade reason codes;
- reconciliation controls.

### 2.4 Provider-resolution semantics

A retailer may supply the same business role from more than one source. The profile must choose
one explicit mode:

- `exclusive`: exactly one provider owns the role; multiple providers fail closed;
- `union`: providers own disjoint declared partitions with collision checks;
- `cross_validate`: one provider is authoritative and another supplies reconciliation evidence;
- `fallback`: a precedence order is declared, with reason-coded use of a lower-priority provider.

Implicit “first source wins”, row-level coalescing across providers and source-name precedence are
forbidden. Role ownership and resolution are part of the profile fingerprint.

### 2.5 Adapter types

#### Mapped-files adapter

Use when semantics are expressible declaratively:

- physical path/dataset selection;
- field rename/select;
- typed parse;
- constant or profile-derived value;
- allowlisted value map;
- timezone/date normalization;
- exact major/minor money conversion under the shared money contract;
- quantity normalization;
- controlled row filter;
- stable key composition;
- approved `known_as_of` derivation;
- role binding.

The mapping language is deliberately non-Turing-complete. It cannot run arbitrary SQL/Python,
call the network, read undeclared files or silently drop invalid rows.

#### Bounded custom adapter

Use only when source semantics cannot be represented by approved mappings—for example, an ERP
requires joining header/line/version events, interpreting a source-specific status machine or
resolving a proprietary inventory ledger.

The adapter may know the retailer/platform source. Its primary identity should be the reusable
source dialect/version—not a retailer brand—unless the source is genuinely retailer-specific.
It may use shared mapping/normalization helpers. It must emit standardized roles and pass the
same conformance suite. It may not import canonical transforms, ML, API or UI code.

For the PoC, use the decision-#69 **static in-repository registry with an explicit adapter
manifest**.
Design the protocol and conformance kit so an externally packaged adapter can be added later, but
do not enable arbitrary plugin discovery or untrusted code loading without a separate security
decision.

### 2.6 Temporal evidence and zero-demand boundary

For every temporal role/field, the adapter declares:

| Evidence | Allowed meaning |
|---|---|
| `native_observed` | source recorded the observation time |
| `native_processed` | source recorded deterministic processing availability |
| `native_posted_available` | source posting rule proves availability; rule is retained |
| `native_extracted` | immutable snapshot/CDC extract time is the earliest defensible availability |
| `landing_backfill` | only landing time is known; historical replay capability is downgraded |

The readiness evaluator must never promote `effective_date`, `transaction_date`, `start_date` or
`end_date` into historical availability without separate evidence.

A weekly zero-demand label is available only when:

1. the extract is complete for the business interval;
2. SKU × store × channel was actively listed/assorted for the interval;
3. the observation was known by the model fit cutoff;
4. partial boundary-week exposure is handled by decision #56;
5. no unresolved source gap or channel omission applies.

Otherwise the row is unknown/unavailable, not zero.

### 2.7 Capability-specific readiness

Publish separate data-readiness verdicts:

| Capability | Example minimum dependencies |
|---|---|
| `current_descriptive_analytics` | current products, locations and transactions with reconciliation |
| `demand_forecast_non_pit` | demand grain, assortment/availability, sufficient history, accepted fallback semantics |
| `historical_replay` | origin-visible targets/features and temporal evidence |
| `point_in_time_forecasting` | all required temporal entities origin-safe, not merely demand labels |
| `inventory_replenishment` | inventory, inbound, lead-time/supplier evidence and reconciled demand |
| `price_revenue` | origin-safe sell prices and demand response evidence |
| `price_margin` | accepted temporal cost ledger in matching currency/scope |
| `promotion_aware_forecasting` | origin-visible historical and future promotion plans |
| `competitor_aware_forecasting` | origin-visible match/price/availability evidence |

Each verdict is one of `ready`, `validated_partial`, `unavailable` or `blocked`, with role/field
coverage and reason codes. Statistical sufficiency is a separate field:
`sufficient`, `insufficient_evidence` or `not_evaluated`.

### 2.8 Retailer/tenant publication selection

Replace “discover the committed demo pin” as a deployment assumption with:

- a machine-readable publication-selection schema;
- an immutable selection document per retailer/tenant/environment;
- explicit source snapshot, Gate A, Gate B and publication fingerprints;
- required capability and readiness-report fingerprint;
- object hashes and lineage;
- approval identity/time/reason outside semantic identity;
- lifecycle `candidate → approved → active → superseded/rejected`;
- one active selection per retailer/tenant/capability/environment;
- no “latest publication” resolution.

`contracts/ml/expected-pin.json` remains the demo fixture. Runtime commands accept an explicit
selection path/id and fail closed when it is absent, mismatched or under-capable.

### 2.9 Forecast-quality target architecture

Track B uses an evidence ladder:

```text
new PP3-P0 complete-population decision-#82 verifier result
  ├─ accepted → accepted comparison authority C0
  └─ rejected → diagnostic comparison authority D0 only
       (retained as diagnostic evidence; never accepted/canonical publication, activation or serving authority)
  ← former v12 and fr_92135aa7b5215b69 remain rejected historical diagnostics, never C0/D0
  → frozen diagnostic baseline
  → registered root-cause hypotheses
  → bounded candidate families
  → development-origin comparison
  → untouched confirmation-origin comparison
  → unchanged A1–A5 full schedule
  → immutable candidate publication
  → separate materialization and activation
  → reviewed UI presentation update
```

Accuracy remains `100·(1−WAPE)`. WAPE/additive components are the comparison authority.
Confidence remains a governed transform of actual P50–P90 spread; it is not optimized directly.
If PP3-P0 closes NO-GO, D0 must still use feature-schema-v6, the decision-#82 comparator/eligibility
rule, the full fixed schedule, complete governed evaluation rows and independent decision-#82 verifier
recomputation. Track B candidates compare with D0 for diagnostic improvement, but they must pass
unchanged A1–A5 before they can become the first accepted C0.

---

## 3 · Finalized decisions and implementation bindings

Decisions #65–#80 and #82 are finalized in `docs/OPEN_DECISIONS.md`. Their implementation and
evidence gates remain open; closing a decision does not waive a consumer gate.

| # | Decision | Final policy summary | Consumer gate |
|---|---|---|---|
| 65 | Post–Phase 3 scope/order | Track A fully accepted before Track B implementation | PP3-A1 |
| 66 | Staging migration | versioned v2 dual-run; no in-place v1 rewrite | PP3-A2 |
| 67 | Role provider resolution | explicit exclusive/union/cross-validate/fallback | PP3-A2 |
| 68 | Mapped-files language | allowlisted non-Turing-complete operations only | PP3-A4 |
| 69 | Custom-adapter loading | static in-repo registry for PoC; external plugin deferred | PP3-A5 |
| 70 | Temporal evidence/readiness | five evidence grades; business date never proves availability | PP3-A6 |
| 71 | Zero-demand eligibility | completeness + dated assortment + cutoff availability | PP3-A6 |
| 72 | Capability vocabulary | separate readiness and statistical-sufficiency verdicts | PP3-A6 |
| 73 | Retailer pin lifecycle | explicit tenant/capability/environment selection; never latest | PP3-A7 |
| 74 | Candidate-selection protocol | first 8 origins development; ≤20 configurations; freeze one candidate before reading final 5 confirmation origins | PP3-B1 |
| 75 | Improvement materiality | all-13 and final-5 must each pass ≥5% relative WAPE, clustered 95% upper bound <0, market regression ≤1% and identical keys | PP3-B1 |
| 76 | Quality policy v2 | separate publication/global limitations from row-local quality | PP3-B6 |
| 77 | Business target matrix | `retail-forecast-health/v1` market/store/SeriesKey targets for h1/h4/h8/h13/h26; bias ≤5%; coverage 0.85–0.95 | PP3-B7 |
| 78 | Presentation policy | lead with contextual evidence; preserve weak slices and exact grain | PP3-B7 |
| 79 | Provenance vocabulary | source-neutral evidence/derivation classes; source identity stays separate | PP3-A2 |
| 80 | Forecast Health horizon semantics | `retail-forecast-health/v1`: four exact h1/h4/h8/h13 rows with resolved target grain and ordered target-relative Strong/Healthy/Watch/Action evaluation | PP3-B7 |
| 82 | Short-history A1 eligibility | Established lag-52 cohort plus complete available-history-mean cold-start cohort; zero-history is insufficient | PP3-P0 |

### 3.1 Final decision #82

Use the spec-amendment branch, not a synthetic “seasonal” value where lag-52 evidence does not
exist:

1. Define established-history A1 eligibility per
   `forecast_origin × horizon × SeriesKey` using only origin-visible history availability. A row
   enters established A1 only when its lag-52 seasonal-naive input is available; every such
   champion/actual/baseline key must pair 100%, and the unchanged ≥25% gate applies globally and
   per supported market.
2. Keep every remaining champion row in a separately published cold-start cohort. Its comparator
   is the arithmetic mean of the last `min(13, history_weeks)` complete origin-visible weekly
   actuals. Require at least one prior week; a zero-history row is `insufficient_evidence` and
   leaves the version unaccepted. Cold-start champion WAPE must be no worse than this comparator
   globally and in every supported market with 100% champion/actual/comparator key completeness.
3. Publish cohort membership reason codes, row/actual shares, SeriesKey counts, canonical key
   hashes and full/paired/dropped metrics. A row may not disappear from both cohorts. A3 remains
   a seasonal-naive gate over established-history slow movers under decision #52; cold-start slow
   movers remain in the cold-start A1 cohort and never receive a synthetic seasonal value.
4. Amend spec §4.3 and publish immutable acceptance-v3/verifier-v4 plus migration 0006. Migration
   0006 is v4-only: verifier-v3 and all older materializations remain ineligible for new
   activation. Do not mutate acceptance-v2/verifier-v3 or migration 0005. Decision #81 remains the
   completeness rule inside each declared cohort.

On the rejected v15 bundle, this policy would move 102,804 of 708,708 rows (14.51% of rows,
22.49% of actual units, 402 distinct SeriesKeys) from established seasonal comparison into the
cold-start cohort. The established paired subset's 53.47% point estimate suggests A1 could pass
there, but that is not acceptance evidence and cannot set the policy. The cold-start cohort has
40.03% champion WAPE and must pass its own predeclared gate; it cannot borrow the established
cohort's result. Remeasure every figure on v6.

A direct v15 preflight shows that NO-GO is a credible outcome, not an exceptional fallback.
Using the bundle's MA13 baseline only as a proxy for decision #82's exact short-history mean, the
cold-start champion passes globally (40.03% versus 40.88% WAPE) and in India (43.94% versus
46.67%) but fails in US New York (37.13% versus 36.60%, a −1.44% relative result). It also loses
to MA8 there (36.63%) and only narrowly beats naive (37.39%). This is not acceptance evidence:
the bundle predates feature-v6, and MA13 can differ from
`mean(last min(13, history_weeks) complete origin-visible weeks)` for very short histories.
PP3-P0 task 8 must cheaply recompute the exact comparator before the full backtest, preserve #82
unchanged, and treat a confirmed supported-market failure as NO-GO. Register the deficit as a
PP3-B3 lifecycle/cold-start hypothesis feeding PP3-B5; never tune the comparator or threshold
from this result.

On v15 the cold-start membership happens to be horizon-invariant: 3,954
`forecast_origin × SeriesKey` pairs produce 3,954 rows at each of 26 horizons. A compact pair-key
hash may supplement the evidence for this historical diagnostic only after that invariance is
proved. Acceptance-v3 still publishes the canonical
`forecast_origin × horizon × SeriesKey` row-key hash because a future cohort must not assume
horizon invariance.

#### 3.1.1 Exact-comparator preflight result — 2026-07-31

The PP3-P0 preflight is complete. The comparator was recomputed exactly from
feature-schema-v6 (`f3ff8725d36d78ff…`) as the mean of the last `min(13, N)` complete
(`exposure_days = 7`) origin-visible weeks strictly before each origin, then joined to the v15
champion predictions. This is diagnostic evidence: the champion columns still predate v6, so the
figures below must be replaced by the v6 rerun.

| Cohort | Scope | Rows | Champion WAPE | Comparator WAPE | Margin | Verdict |
|---|---|---|---|---|---|---|
| established | global | 605,904 | 0.2475 | 0.5318 | +53.47% | pass |
| established | india-west | 294,368 | 0.2348 | 0.5166 | +54.54% | pass |
| established | us-new-york | 311,536 | 0.2658 | 0.5538 | +52.00% | pass |
| cold-start | global | 100,984 | 0.3984 | 0.4030 | +1.13% | pass |
| cold-start | india-west | 46,592 | 0.4380 | 0.4629 | +5.38% | pass |
| **cold-start** | **us-new-york** | **54,392** | **0.3692** | **0.3586** | **−2.93%** | **fail** |

The exact comparator makes the US New York deficit worse than the MA13 proxy (−1.44% → −2.93%),
so the supported-market cold-start leg fails and **PP3-P0 is expected to close explicit NO-GO**.
Decision #82 is not retuned. The deficit is registered as the first PP3-B3 lifecycle/cold-start
hypothesis.

Two independent blockers exist, and only the first is a model-quality problem:

1. the US New York cold-start non-inferiority failure above;
2. 54 `forecast_origin × SeriesKey` pairs (1,404 rows) have **no complete** prior week, so they
   receive no comparator and force `insufficient_evidence`.

Measured composition of the second blocker: every one of those 54 pairs has exactly **one partial
prior week**, and **no pair has zero prior weeks at all**. They are mid-week launches, not
genuinely unobserved series. As written, decision #82's "complete origin-visible weeks" therefore
makes acceptance structurally unreachable for any rolling-origin panel that contains a series'
launch week — which this ten-year panel always will.

That is a specification defect, not a threshold to tune, and it is **not** resolved here. The
implementation follows #82 exactly and reports `insufficient_evidence`. A follow-up pre-result
decision (proposed **#83**) must choose between:

- admitting the exposure-normalised `weekly_units_equivalent` of a partial week when no complete
  week exists — the feature contract already computes it for exactly this purpose; or
- declaring launch-week rows evaluation-ineligible with a published reason code, count and share
  cap, so they neither score nor block acceptance.

Either option must be frozen before the numbers are read again. Fixing it after seeing a result
would be threshold tuning under invariant 2.

**The two blockers are sequenced, not parallel.** Acceptance-v3 was dry-run over the full 708,708-row
v15 population with the exact comparator. The cohort partition is total (0 unassigned), the
established leg passes everywhere with complete pairing (53.47% global, 54.54% India, 52.00% US),
and A2/A3/A4 all pass — but every scope returns `A1_cold_start: insufficient_evidence`, because
completeness is evaluated before the comparison. The 1,820 launch-week rows therefore **mask** the
US New York non-inferiority failure: the gate never reaches the `fail` verdict that the −2.93%
deficit would produce. Decision #83 must be resolved before the model-quality deficit is even
observable through the gate, and resolving #83 will not by itself produce an acceptance.

| Scope | Established | Cold-start | A2 | A3 | A4 | Scope |
|---|---|---|---|---|---|---|
| global | pass, +53.47% | insufficient_evidence (1,820 rows) | pass | pass | pass | fail |
| india-west | pass, +54.54% | insufficient_evidence (884 rows) | pass | pass | pass | fail |
| us-new-york | pass, +52.00% | insufficient_evidence (936 rows) | pass | pass | pass | fail |

A5 fails with both supported markets listed.

#### 3.1.2 Implemented artifact versions

| Contract | Before | After | Reason |
|---|---|---|---|
| acceptance | `retail-forecast-acceptance/v2` | `retail-forecast-acceptance/v3` | cohorted gates |
| evaluation recomputation | `paired-seasonal-complete-recomputation/v3` | `cohorted-seasonal-cold-start-recomputation/v4` | cohort partition |
| verifier | `retail-forecast-verifier/v3` | `retail-forecast-verifier/v4` | recomputes both cohorts |
| run bundle | `retail-forecast-run/v2` | `retail-forecast-run/v3` | envelope now carries a fifth baseline and cohorted acceptance |
| serving migration | `0005` | `0006_cohorted_verifier_v4` | v4-only active view; applied and asserted as head |

The run-bundle bump is required by invariant 11: the envelope's meaning changed materially. No
bundle was ever published under `retail-forecast-run/v2` — all three superseded bundles are
schema v1 — so nothing accepted is invalidated and v2 is not mutated. `A1` is replaced in the
acceptance document by `A1_established` and `A1_cold_start`; A2–A5 are unchanged.

#### 3.1.3 Completed v6 cohorted backtest — 2026-07-31, NO-GO

The full pinned-data rerun is complete and **rejected**: `accepted: false`. Feature-schema-v6
`f3ff8725d36d78ff…`, 13 scoring origins, 26 horizons, 708,708 evaluation rows, 65,021,190 training
rows, full schedule, `performance` profile, 2,074 s wall clock. Artifacts live outside Git at
`ml/data/artifacts/forecast_h1_h26_origins13_v6_cohort82/`.

| Scope | Established A1 | Cold-start A1 | A2 coverage | A3 | A4 | Scope |
|---|---|---|---|---|---|---|
| global | pass, +53.4808% | `insufficient_evidence`; 0.398545 vs 0.402994 (+1.10%), 1,820 rows without comparator | pass, 0.8887 | pass | pass | **fail** |
| india-west | pass, +54.5534% | `insufficient_evidence`; 0.437596 vs 0.462916 (+5.47%), 884 rows | pass, 0.8925 | pass | pass | **fail** |
| us-new-york | pass, +52.0268% | `insufficient_evidence`; 0.369632 vs 0.358627 (**−3.07%**), 936 rows | pass, 0.8851 | pass | pass | **fail** |

A5 fails with both supported markets listed. Cohort reason codes:
`LAG52_UNAVAILABLE_SHORT_HISTORY` 100,984 and `COLD_START_NO_PRIOR_COMPLETE_WEEK` 1,820; zero rows
unassigned in every scope. Global champion accuracy is 71.8202% with −6.717% bias, essentially
unchanged from the superseded runs — v6 repaired feature *availability semantics*, not accuracy.

The preflight was accurate: predicted −2.93% for the US cold-start leg, measured −3.07%. Both
blockers reproduced on real v6 evidence, so **Phase 3 closes explicit NO-GO** and this run is
eligible only as diagnostic authority D0 under §2.9. Neither #82 nor any threshold was changed
after seeing this result.

#### 3.1.4 Published rejected candidate and governed NO-GO gate

| Item | Value |
|---|---|
| Forecast run id | `fr_2f4c50d1d7717b23` |
| Lifecycle status | `rejected` |
| Run semantic fingerprint | `22e9e91d0018c1b7d1854a5935d573229338d5bdbcefab8bce6ce34aebfa6c4a` |
| Bundle schema | `retail-forecast-run/v3` |
| Acceptance evaluation | `cohorted-seasonal-cold-start-recomputation/v4` |
| Artifacts | 10; 3,543,540 baseline rows across five baselines |
| Independently verified | yes — verifier-v4 recomputed A1–A5 from bundle contents and matched |
| Reviewed compact index | `contracts/evidence/forecast-closure-record.json` |

Baseline null counts prove the cohort boundary from the bundle alone: `seasonal_naive` is non-null
on 605,904 of 708,708 rows and `cold_start_mean` on 706,888, leaving exactly the 102,804 cold-start
rows and the 1,820 launch-week rows.

`tools/dev.py verify` gained a governed NO-GO mode. Discovery now keys on the manifest rather than
the `forecast_run_accepted_*` directory glob — three superseded bundles still carry that prefix
with a rejected verdict, so a name-based glob would resurrect them. When no accepted candidate
carries the v4 evaluation version, the gate runs against the rejected candidate and asserts that
materialization refuses it, `active_forecast_versions` is empty and no materialization row exists.
Without this the plan's NO-GO branch was unreachable: the gate previously raised outright when no
accepted run existed, so the branch §0.3.1 requires could never produce its evidence.

The Go read model needed the same treatment. `TestForecastPostgresProjectionIntegration` discovered
an active version and failed hard when the view was empty, which is precisely the NO-GO state. It
now skips on that branch, and a new `TestForecastServesGovernedUnavailableOnNoGo` asserts the
positive evidence instead: the active view is empty, the store reports unavailable, the reason maps
to 503 rather than 409 — a 409 would wrongly imply an activated version exists — and the payload
exposes no run id or fingerprint.

The gate then passed end to end in that mode on 2026-07-31 (macOS 26.5, Darwin arm64, 16 logical
CPUs): contracts valid with generated types current, migration `0006_cohorted_verifier_v4` applied,
import boundaries clean across 86 files, execution 12, contract tests 90, datagen 52, ingestion 77,
database 1, ML 79 with 1 skipped, uncached Go race tests green across all packages, and UI tests,
typecheck and production build green. Both fail-closed tests executed rather than skipped. Windows
and Linux evidence remains open under decision #61.

#### 3.1.5 PP3-B2 D0 baseline findings — 2026-07-31

D0 is frozen from the rejected v6 run `fr_2f4c50d1d7717b23`, fingerprint
`15db972bfb076b79…`, at `ml/data/artifacts/diagnostics/d0-baseline.json`. It authorizes nothing.
Three facts in it shape Track B:

**Horizon deterioration is a bias gradient, not noise.** Accuracy falls 78.27% → 75.54% → 72.83% →
70.77% → 69.52% across h1/h4/h8/h13/h26 while bias worsens monotonically from −0.24% to −9.11%. The
champion is close to unbiased at h1 and badly under-forecasting by h26, which makes market × horizon
bias correction (candidate C1) the best-supported first remedy.

**Cold-start is 61.9% worse than established history** — 0.4004 WAPE against 0.2474. Combined with
§3.1.1's finding that the champion has no skill over a trailing mean there, this is a distinct
failure mode from the horizon gradient and needs its own candidate (C6), not a shared fix.

**The confirmation origins are systematically easier, by 3.03 accuracy points** — 73.68% against
70.66% on development. That direction matters: a candidate tuned on the first 8 origins and read on
the final 5 will look *better* than it is, so a confirmation-only improvement is not evidence.
Decision #75 already requires both all-13 and final-5 to pass independently, which is what makes
this survivable, but the asymmetry must be stated wherever a confirmation number is quoted.
Recorded here rather than changing #74, because re-splitting the origins after measuring this would
be selection on the outcome.

#### 3.1.6 PP3-B3 root-cause ranking — 2026-07-31, and a correction

`ml/data/artifacts/diagnostics/root-cause-report.json`, fingerprint `84de4ad12e064d5b…`, ranks the
ten registered hypotheses against D0. The ranking rule is deliberate: **share of total absolute
error, not WAPE.**

That rule overturned my own first reading of the same data. By WAPE the intermittent routes look
like the dominant problem — `lightgbm_intermittent_fallback` at 0.8622 and
`croston_sba_replay_selected` at 1.3462, against 0.2801 for the main route, with −34.5% bias on the
fallback. Ranking by error mass says the opposite:

| Route | Rows | Row share | Absolute error | Error share |
|---|---|---|---|---|
| `lightgbm_horizon_quantile` | 642,664 | 90.68% | 5,477,027 | **99.09%** |
| `lightgbm_intermittent_fallback` | 61,857 | 8.73% | 48,036 | 0.87% |
| `croston_sba_replay_selected` | 4,187 | 0.59% | 2,169 | 0.04% |

The intermittent routes carry 9.32% of rows and **0.91% of the recoverable error**, because their
volumes are tiny. Fixing them perfectly could improve global WAPE by at most ~0.9% relative — far
under decision #75's 5% floor. H3 and H8 are therefore **rejected as immaterial**, not left as
plausible stories. They remain a presentation concern for weak-slice display, not a route to
acceptance.

Supported causes, by addressable error share: **H7** feature fallback at longer horizons (95.7%),
**H2** category composition (88.6%), **H1** market × horizon under-bias (46.9%), **H4**
lifecycle/cold-start (32.0%). H5, H6, H9 and H10 are labelled `not_testable_from_this_artifact` —
they need controlled ablations, and calling them supported from a slice would be exactly the
correlation-as-causation error the plan forbids.

**A global bias correction would be actively harmful.** Of 41 categories, 26 are under-biased, 10
are over-biased and 5 near-neutral, with extremes from `apparel-outerwear` at −22.5% to
`toys-building` at +7.7%. Candidate C1 must therefore be segmented and shrunk to a sufficient
parent, never applied as one global shift. The bias-sign split is published so this cannot be
overlooked.

#### 3.1.7 PP3-B4 candidate results — 2026-07-31, all three rejected

C1, C2 and C1+C2 were fitted on the 8 development origins and scored against D0 under decision #75.
Evidence at `ml/data/artifacts/diagnostics/b4-candidates.json`.

| Candidate | all-13 rel WAPE | final-5 | P90 coverage | Verdict |
|---|---|---|---|---|
| C1 P50 bias correction | **−0.964%** | −0.821% | 0.8898 | **reject** |
| C2 P90 calibration | +0.000% | +0.000% | 0.8563 | **reject** |
| C1+C2 | −0.964% | −0.821% | 0.8588 | **reject** |

C1 also breaches the per-market tolerance: india-west −1.136% against a −1.0% floor.

**Bias and WAPE are in tension, and this is the important finding.** C1 works exactly as intended —
global bias moves from **−6.72% to +0.62%**, essentially eliminated — yet WAPE *worsens* by 0.96%.
That is not a bug. P50 is a median forecast and WAPE is a median-optimal loss, so on a right-skewed
demand distribution scaling a near-median predictor upward to zero the *mean* bias necessarily adds
absolute error. The −6.72% under-bias in §3.1.3 is therefore **not recoverable accuracy**; treating
it as a free win would have been the mistake. §3.1.6's H1 remains a real cause of the bias, but the
remedy costs accuracy under the current loss, so any future C1 variant has to target conditional
quantiles rather than rescale the mean.

**Decision #75 structurally cannot accept a calibration-only candidate.** C2 sharpens intervals by
14% — median P90−P50 gap 4.420 → 3.790 — while coverage stays at 0.8563, inside the governed
0.85–0.95 band. That is a genuine improvement in uncertainty quality. But #75's materiality gate is
expressed purely as relative WAPE, and C2 does not touch P50, so it scores exactly +0.000% and
fails. The gate is blind to sharpness by construction.

That is a gap in #75, not a defect in C2, and it is **not** fixed here: adding a sharpness criterion
after seeing C2's result would be tuning a threshold to admit a candidate, which invariant 2 and
#75's own text forbid. It is recorded as a pre-result amendment for review — a companion criterion
such as "coverage stays in band and median relative interval width falls by at least X%" must be
frozen *before* C2 is re-scored. Note also that C2 leaves coverage at 0.8563, only 0.0063 above the
floor, so the available sharpening headroom is nearly exhausted.

The gate is satisfiable: a synthetic 60%-error-reduction candidate passes both populations, the
clustered interval and the market tolerance, so these rejections reflect the candidates rather than
an unpassable gate.

#### 3.1.8 Decision #83 decided and measured — 2026-07-31

Frozen as option (a) plus an explicit residue class, then measured. **It did not change the failing
verdict, which is the point.**

| Measure | Before #83 | After #83 |
|---|---|---|
| US New York cold-start margin | −3.07% **fail** | −2.40% **fail** |
| Rows with no comparator | 1,820 (70 SeriesKeys) | 416 (16 SeriesKeys) |
| Residue share of panel | 0.257% | **0.0587%** |

Partial launch weeks are admitted at exposure-normalised `weekly_units_equivalent`, which recovered
1,404 of the 1,820 rows. The remaining 416 have no prior observation of any kind at their first
origin: there is no defensible comparator and no skill claim is possible either, so they are
`evaluation_ineligible` with reason code `NO_PRIOR_OBSERVATION_AT_FIRST_ORIGIN`, counted, and capped
at 1% of rows. The cap is set from principle rather than from the measurement — above 1% the residue
would indicate a systemic evidence problem and must fail closed — and the measured 0.0587% sits two
orders of magnitude below it.

I initially rejected the ineligible class as violating "a row may not disappear from both cohorts".
On re-reading, that invariant forbids a *silent* disappearance; an explicitly reason-coded, counted,
capped class is not one. The correction is recorded rather than hidden.

**This is not tuning to pass.** The US New York deficit was measured before the decision and still
fails after it. #83 removes an unsatisfiability defect; it does not make the run acceptable, and the
direction scorecard still reports Phase 3 blocked.

### 3.2 Decisions that must remain unchanged

Do not reopen #10–#13, #16, #20, #29, #35, #38, #41, #46 or #49–#63 merely because this
workstream exists. Decision #64/Q6 is changed only through decided #80;
all other #64 parity decisions remain frozen. If evidence proves another decision is unsound,
stop and propose a separately versioned decision amendment with affected artifacts and replay
scope.

### 3.3 Final formulas for decision #75

- `candidate_wape = SUM(candidate_abs_error_sum) / SUM(actual_sum)`;
- `authority_wape = SUM(authority_abs_error_sum) / SUM(actual_sum)`, where authority is the
  frozen repaired C0 or diagnostic-only D0;
- paired keys include input publication, origin, horizon and SeriesKey;
- `delta_wape = candidate_wape − authority_wape`; lower is better;
- `relative_improvement = (authority_wape − candidate_wape) / authority_wape` must be at least
  `0.05`;
- use 10,000 SeriesKey-clustered bootstrap replicates with seed `20260731`; the 95% interval's
  upper bound for `delta_wape` must be `< 0`;
- for every supported market, `candidate_wape / authority_wape − 1 <= 0.01`;
- report market, store, category, channel, lifecycle/intermittency and h1/4/8/13/26 slices;
- do not accept Simpson’s-paradox improvement hidden by a changed row population;
- treat a zero `actual_sum` slice as `insufficient_evidence`.

Compute and publish the complete materiality battery twice: once over all 13 scoring origins and
once over the final 5 untouched confirmation origins. Candidate-family/configuration selection
uses only the first 8 origins, and exactly one frozen candidate advances before the final 5 are
read. The ≥5% relative improvement, clustered upper-bound `<0`, identical-key and ≤1%
supported-market-regression requirements must pass in both windows. A1–A5 continues to run over
the fixed all-13 acceptance schedule; the confirmation result is an additional improvement gate,
not a replacement acceptance population.

These values are frozen before PP3-B candidate scoring and cannot be tuned afterward.

---

## 4 · Deliverables

### 4.1 Track A deliverables

| ID | Deliverable |
|---|---|
| A-D1 | approved coupling inventory and boundary allowlist |
| A-D2 | `retail-staging/v2` role schema and executable validators |
| A-D3 | role-binding/provider-resolution profile schema |
| A-D4 | source-neutral role assembly, quarantine and crosswalk |
| A-D5 | profile-driven mapped-files adapter |
| A-D6 | bounded custom-adapter protocol, manifest, registry and conformance kit |
| A-D7 | temporal-evidence policy and zero-demand eligibility evaluator |
| A-D8 | capability-specific readiness report and schema |
| A-D9 | retailer/tenant publication-selection schema and lifecycle |
| A-D10 | mapped-files retailer fixture, custom-adapter fixture and negative fixtures |
| A-D11 | v1→v2 accepted-pin parity evidence |
| A-D12 | client-shaped unchanged-downstream round-trip evidence |
| A-D13 | onboarding and operations guide |

### 4.2 Track B deliverables

| ID | Deliverable |
|---|---|
| B-D1 | immutable forecast diagnostic baseline |
| B-D2 | root-cause report with registered hypotheses |
| B-D3 | candidate registry and comparison protocol |
| B-D4 | bias/calibration candidate evidence |
| B-D5 | segmented champion/fallback candidate evidence |
| B-D6 | hierarchical reconciliation candidate evidence |
| B-D7 | optional-signal readiness/ablation evidence |
| B-D8 | quality policy v2 proposal, vectors and fingerprint |
| B-D9 | business target matrix |
| B-D10 | revised Demand Forecast parity/data contract, fixed four-row horizon health and reviewed screenshots |
| B-D11 | immutable accepted/rejected candidate bundle |
| B-D12 | materialization, activation or no-go record |

### 4.3 Traceability to `tasks.md`

| Deferred task | Plan coverage |
|---|---|
| Retailer retrospective go/no-go | PP3-P0 |
| Inventory/remove platform coupling | PP3-A1, PP3-A3 |
| Freeze standardized staging roles | PP3-A2 |
| Neutral quarantine/quality validation | PP3-A3 |
| Mapped-files default adapter | PP3-A4 |
| Versioned custom-retailer adapter path | PP3-A5 |
| Registration/packaging/conformance | PP3-A5 |
| Temporal-evidence policy/readiness report | PP3-A6 |
| Zero-demand eligibility | PP3-A6 |
| Capability-specific onboarding outcomes | PP3-A6 |
| Per-retailer/per-tenant publication pinning | PP3-A7 |
| Mapped and custom adapter fixtures | PP3-A4, PP3-A5, PP3-A8 |
| Separate statistical sufficiency | PP3-A6, PP3-A8 |
| Client-shaped unchanged-downstream round trip | PP3-A8 |
| Architecture/spec/guide reconciliation | PP3-A9 |
| Frozen forecast diagnostic baseline | PP3-B1, PP3-B2 |
| Under-forecast root-cause diagnosis | PP3-B3 |
| Market × horizon bias/calibration | PP3-B4 |
| Segmented champion candidates | PP3-B5 |
| Hierarchical reconciliation | PP3-B5 |
| Coverage-constrained interval sharpness | PP3-B4 |
| Optional origin-safe retailer signals | PP3-B6 |
| Quality policy v2 | PP3-B6 |
| Business metric/grain/horizon target matrix | PP3-B7 |
| Forecast Health fixed four-row parity and metric/status semantics | PP3-B7 |
| Demand Forecast presentation update | PP3-B7 |
| Full A1–A5 and immutable publication acceptance | PP3-B8 |

### 4.4 Relative size bands for staged approval

These are scope bands, not calendar commitments: **S** is a narrow decision/contract package;
**M** crosses several files in one subsystem; **L** crosses contracts, implementation and
full-data evidence; **XL** changes multiple subsystems and requires staged parity/round-trip
review.

| Package | Band | Principal cost driver |
|---|---|---|
| PP3-P0 | XL | acceptance-v3/verifier-v4, migration 0006, first v6/run-v2 end-to-end rerun, portability/performance, serving/UI evidence and phase exit |
| PP3-A1 | M | roughly 70 staging/consumer relations, reverse mapping and `dimension_signal` inventory |
| PP3-A2 | L | 35 typed roles plus provider/provenance contracts and vectors (**done**: `contracts/staging/staging-v2.yaml`, 19 tests) |
| PP3-A3 | XL | neutral assembly, quality relocation and full v1/v2 parity |
| PP3-A4 | L | declarative mapping language, four readers and conformance fixtures |
| PP3-A5 | M | bounded adapter protocol, registry and negative conformance |
| PP3-A6 | L | temporal/zero-demand policies and capability evaluator |
| PP3-A7 | M | tenant selection lifecycle and lineage binding |
| PP3-A8 | XL | two client-shaped full round trips plus negative fixtures and portability |
| PP3-A9 | S | review, cutover decision and documentation reconciliation |
| PP3-B1 | S | protocol/decision freeze |
| PP3-B2 | M | reproducible multi-slice baseline |
| PP3-B3 | M | registered diagnostics and ablations |
| PP3-B4 | L | bias/quantile candidates with held-out evidence |
| PP3-B5 | XL | segmented champions plus hierarchical reconciliation |
| PP3-B6 | L | optional signals and quality-policy v2 |
| PP3-B7 | M | target/status matrix, parity amendment and responsive UI |
| PP3-B8 | L | full acceptance, materialization, activation/no-go and final review |

---

## 5 · Proposed file layout

Names are targets, not authorization to create them.

```text
contracts/
  evidence/
    phase3-exit.schema.json
    post-phase3-comparison.schema.json
  staging/
    staging-v2.yaml
    role-contract.schema.json
  adapters/
    adapter-manifest.schema.json
    mapped-files.schema.json
  onboarding/
    readiness-report.schema.json
    publication-selection.schema.json
    temporal-evidence-policy.json
  ml/
    forecast-health-policy.json         # existing decision-#77/#80 authority
    forecast-improvement-policy.json
    forecast-classification-policy-v2.json
  screens/
    demand-forecast.parity.yaml

ingestion/
  src/retail_ingestion/
    adapters/
      mapped_files.py
      protocol.py
      registry.py
      conformance.py
    staging/
      roles.py
      binding.py
    quality/
      validation.py
      quarantine.py
    readiness/
      evaluator.py
      temporal.py
      capabilities.py
      selection.py
    profiles/
      fixtures/
        mapped-retailer.yaml
        custom-retailer.yaml
  tests/
    fixtures/retailers/
    test_role_contract.py
    test_mapped_files_adapter.py
    test_custom_adapter_conformance.py
    test_temporal_readiness.py
    test_retailer_round_trip.py

ml/
  src/retail_ml/
    diagnostics/
      baseline.py
      slices.py
      comparison.py
    models/
      bias_correction.py
      reconciliation.py
      candidate_registry.py
    policies/
      quality_v2.py
  tests/
    test_diagnostic_baseline.py
    test_candidate_comparison.py
    test_reconciliation.py
    test_quality_policy_v2.py
```

Do not create retailer-specific modules outside
`ingestion/src/retail_ingestion/adapters/` or test fixtures. Tenant
instance selections and credentials are runtime configuration, not committed contracts. Generated
reports and immutable bundles follow §1.7 and are not placed under a tracked `ml/reports/`
directory by default.

---

## 6 · Track A work packages — retailer-source onboarding hardening

### PP3-P0 · Close Phase 3 and authorize the workstream

**Purpose:** repair the confirmed Phase 3 semantic defects, replace invalid evidence and prevent
deferred hardening from silently becoming a Phase 3 amendment.

Tasks:

1. Enforce independent A1–A5 recomputation in publication and verification, with forged and
   re-signed acceptance regression tests.
2. Build `retail-weekly-features/v6`: preserve origin-observed events, remove unavailable future
   calendar-event, local-event and market-disruption features, publish explicit unavailable
   reason codes, reject any structurally all-null feature, keep working-day availability
   independent and bind the Parquet descriptor plus SQL semantics into identity.
3. Preserve unavailable lag-52 rows; publish full/paired/dropped population diagnostics and
   canonical key hashes. Enforce decision #81 complete overall A1 pairing and decision #52 A3.
4. Recompute decision-#12 confidence after Croston routing.
5. Implement spec §4.8 stale-lineage 409 and missing/invalid/unmaterialized 503 contracts.
6. Bind forecast-run-v2 serving to `retail-forecast-verifier/v3`; migration 0005 excludes every
   verifier-v2 or legacy-unverified materialization from the active view.
7. Fix clean-database idempotency tests and make `tools/dev.py verify` exercise datagen,
   PostgreSQL, Go and UI rather than accepting skips.
8. Implement decided #82 as acceptance-v3/verifier-v4 and v4-only migration 0006, then regenerate
   the exact cold-start comparator as a cheap preflight. Record the v15 MA13-proxy US-market
   deficit without changing #82; if the exact v6 preflight fails, plan the honest NO-GO path and
   still produce complete evidence. Then regenerate characterization, the 13-origin H1–H26
   backtest, current-cycle
   classifications and a new immutable forecast-run bundle. Never edit/re-sign the former v12
   bundle or the acceptance-v2/verifier-v3 authority.
9. Publish/activate only if the repaired verifier concludes accepted; otherwise retain an honest
   rejected candidate and keep the API fail-closed.
10. Apply §1.7: verify and carry the reassessment's interim external rejection/supersession ledger
    for all three v1 bundles into the schema-governed PP3-P0 acceptance/no-go index, preserve their
    original bytes, keep full/superseded artifacts outside Git, remove obsolete tracked generated
    evidence and commit at most one reviewed compact index for the new run. Write that index to
    `contracts/evidence/` — `ml/reports/` is now ignored — and retire the interim
    `ml/reports/review2-acceptance-reassessment-db3784fdcc4cb833.json` in the same change by
    relocating its still-current ledger content into the new index. Then pass the full
    stateful local gate.
11. Record manual Windows and Linux portability evidence.
12. Record the full pinned-data 16-GB/high-performance benchmark comparison.
13. Obtain explicit Demand Forecast visual approval using the accepted-live or
    governed-unavailable wording in §0.3.1.
14. Hold the Phase 3 retrospective.
15. Record go/no-go, scope, supported initial formats and whether custom adapter code is in scope.
16. Approve only PP3-A1–PP3-A3 first; later work remains gated.

**Exit:** a newly derived forecast bundle passes independent verification and the local phase-exit
gate (or Phase 3 is explicitly closed NO-GO with serving disabled), `tasks.md` Phase 3 exit is
complete, and the retrospective records whether decided #65's PP3-A1–A3 authorization begins.

### PP3-A1 · Coupling inventory and boundary test

**Purpose:** establish the exact source-specific code that may remain.

Tasks:

1. Scan Python, SQL, contracts, profiles and tests for platform/retailer identifiers.
2. Classify each occurrence:
   - allowed inside adapter/profile/fixture;
   - migration-only compatibility;
   - prohibited in shared staging, validation, transform, ML, API or UI.
3. Inventory every `stage_data.*` relation consumed by canonical transforms and Gate B.
4. Inventory all quarantine predicates, key crosswalks and reconciliation controls.
5. Map each current relation to one proposed role.
6. Produce the reverse map: every proposed role names at least one v1 provider or an explicit
   `derived_in_transform`, `absent_in_demo_source` or rejected disposition. Confirm `channel` is
   derived from merchandise and `allocation_supply` is supplied by the
   `allocationSupplyPools` dimension-signal kind.
7. Enumerate every accepted-pin `dimension_signal.entity_kind`, payload schema, provider, row
   count and consumer; map each to a typed role or explicit disposition.
8. Fail on an unmapped consumer or role; do not create an “other” escape hatch.
9. Extend import/boundary checks with a reviewed allowlist.

**Evidence:** machine-readable occurrence report plus reviewed role map.

**Exit:** A-D1 approved; no v2 code starts with an unknown consumer.

### PP3-A2 · Freeze staging v2 and role bindings

**Purpose:** make the adapter output contract complete and executable.

Tasks:

1. Define `retail-staging/v2` common fields and every role schema.
2. Define grain/key/money/time/evidence/provenance for every role.
3. Replace platform-shaped row-provenance values with orthogonal source-neutral provenance and
   derivation classes while retaining exact source-system/instance lineage.
4. Define required role controls and invalid-row reason codes.
5. Define provider-resolution modes and collision behavior.
6. Add role bindings to the source-profile schema.
7. Define adapter manifest fields:
   - source-system id;
   - adapter version;
   - supported source profile/schema versions;
   - supplied roles;
   - required source capabilities;
   - provider-resolution compatibility.
8. Add semantic fingerprint rules and golden vectors.
9. Preserve v1 validators and fixtures during migration.
10. Generate/update Python contract types.
11. Review schema examples for demo, mapped retailer and custom retailer.

**Tests:**

- unknown roles/fields fail;
- missing keys and ambiguous provider ownership fail;
- money/time/evidence enums are closed;
- role schema and adapter manifest fingerprints are deterministic;
- v1 remains valid until cutover.

**Exit:** decisions #66–#68 and #79 are frozen and A-D2/A-D3 are approved.

### PP3-A3 · Build source-neutral assembly, validation and quarantine

**Purpose:** remove source names from shared staging behavior.

Tasks:

1. Make adapters publish role bindings rather than relying on fixed source table names.
2. Build role tables/views from bindings and provider-resolution policy.
3. Move row validation to role-schema-driven common checks.
4. Move semantic checks into role-specific neutral validators.
5. Replace source-named quarantine datasets with role id + provider/source provenance.
6. Build location/product crosswalks from neutral roles and preserve canonical channel derivation
   from the neutral merchandise channel key.
7. Preserve raw-object lineage on every row and finding.
8. Produce a v2 staging manifest with role providers, counts, quarantine and fingerprints.
9. Keep transforms reading stable neutral names.
10. Dual-run v1/v2 on a small fixture, then the accepted v12 snapshot.

**Parity rules:**

- same canonical rows by complete business key and value, including per-entity-kind reconciliation
  from the v1 opaque `dimension_signal.payload` to typed v2 roles;
- same source reconciliation totals;
- same Gate-B pass/fail and reason counts;
- same capability mask;
- any difference is explained and reviewed before cutover;
- accepted source-v12 artifacts are not overwritten.

**Exit:** A-D4/A-D11 pass; source-name scan is clean outside the allowlist.

### PP3-A4 · Implement mapped-files default adapter

**Purpose:** onboard ordinary client extracts through configuration instead of copied code.

Tasks:

1. Freeze the mapped-files schema and allowlisted operations.
2. Support CSV, Parquet, JSONL and JSON via existing physical readers.
3. Bind one or more datasets to standardized roles.
4. Implement typed field selection/rename, constants, maps, parsing and exact conversions.
5. Require explicit source keys, grain, timezone, currency, quantity and null policy.
6. Require explicit temporal-evidence derivation for every temporal role.
7. Quarantine mapping failures with source row/object provenance.
8. Fingerprint the approved mapping and include it in staging/publication lineage.
9. Prevent path escape, undeclared reads, arbitrary SQL/functions and silent row dropping.
10. Add a dry-run mapping report before full ingestion.

**Fixtures:**

- a non-Shopify/non-BC retailer expressed fully by mappings;
- renamed/reordered CSV columns;
- equivalent Parquet/JSONL/JSON representations;
- missing required field;
- ambiguous key;
- invalid money precision;
- invalid timezone/date;
- unavailable temporal evidence.

**Exit:** A-D5 and the mapped-retailer positive/negative conformance evidence pass.

### PP3-A5 · Implement bounded custom-adapter extension

**Purpose:** provision for real retailer semantics that mappings cannot express.

Tasks:

1. Implement decided #69's static custom-adapter protocol and manifest.
2. Require adapters to use shared readers and normalization helpers where possible.
3. Require role output only; adapters cannot publish canonical entities.
4. Keep registration explicit and deterministic.
5. Reject duplicate source-system ids and ambiguous role ownership.
6. Enforce import boundaries.
7. Build one deliberately different custom-retailer fixture requiring semantic joins/state
   interpretation that mapped files cannot express.
8. Prove no Shopify/BC adapter copy was needed.
9. Prove a custom adapter cannot bypass shared role validation/quarantine.
10. Document the later external-package decision without enabling it now.

**Exit:** A-D6 and the custom-retailer conformance fixture pass.

### PP3-A6 · Temporal evidence, zero demand and readiness

**Purpose:** make “safe for ML” a measured capability verdict.

Tasks:

1. Implement decisions #70–#72.
2. Evaluate evidence per temporal role/field.
3. Publish coverage by evidence grade and business interval.
4. Implement extract-completeness controls.
5. Implement dated assortment/listing coverage at SKU × store × channel.
6. Implement zero-demand eligibility and unknown-row accounting.
7. Separate readiness from statistical sufficiency.
8. Publish capability dependency/coverage/reason-code detail.
9. Verify `validated_partial` cannot reach an under-supported consumer.
10. Add negative fixtures for business-date-as-availability, current-catalog backfill, incomplete
    channel coverage and landing-only temporal evidence.

**Exit:** A-D7/A-D8 pass and the accepted demo pin reproduces its declared
`demand_forecast_non_pit` status without being relabelled PIT.

### PP3-A7 · Retailer/tenant publication selection

**Purpose:** stop assuming one repository-committed demo pin.

Tasks:

1. Implement decision #73 and its selection schema.
2. Keep demo `expected-pin.json` as a fixture/compatibility selection.
3. Add explicit selection input to verification, feature, scoring, materialization and activation
   commands.
4. Bind selection to readiness-report and capability fingerprints.
5. Implement lifecycle and one-active-selection rules.
6. Fail closed on missing/moved publication, object mismatch, capability downgrade or tenant
   mismatch.
7. Keep approval metadata out of semantic identity but inside audit evidence.
8. Never resolve “latest”.
9. Add rollback by new selection/activation record, not mutation.
10. Document local-file configuration now and AWS secret/config placement later.

**Exit:** A-D9 passes; commands can run demo and retailer fixtures without ML source changes.

### PP3-A8 · Client-shaped round trips and conformance gate

**Purpose:** prove the architectural promise end to end.

Run three positive paths:

1. accepted synthetic v12 through v2 compatibility;
2. generic mapped-files retailer;
3. semantically different custom-adapter retailer.

Run negative paths:

- missing temporal evidence;
- ambiguous mapping;
- duplicate role ownership;
- incomplete extract;
- absent assortment coverage;
- invalid money precision/currency;
- mixed tenant/publication lineage;
- statistically insufficient forecasting evidence;
- plugin/unregistered adapter attempt.

For each positive path execute:

```text
immutable landing
→ Gate A
→ adapter
→ role validation/quarantine
→ neutral staging v2
→ unchanged canonical transform
→ Gate B/reconciliation
→ readiness report
→ explicit publication selection
→ unchanged feature/ML code when capability allows
```

Required proof:

- no retailer/platform branches outside adapters/profiles/fixtures;
- transforms, ML, API and UI source files are unchanged for the new retailer;
- all row lineage reaches raw object/native record;
- unsupported capability is reason-coded, not fabricated;
- statistical insufficiency produces an honest no-go;
- safe/high-performance profiles produce equivalent semantic results;
- developer-run macOS plus manual Windows/Linux portability evidence pass.

**Exit:** A-D10/A-D12 pass.

### PP3-A9 · Track A finalization

Tasks:

1. Review all Track A contracts, parity and negative evidence.
2. Decide whether staging v2 becomes current or remains a candidate.
3. If accepted, update architecture/spec/tasks/README/operations documentation.
4. Publish the onboarding guide and mapping/custom-adapter decision tree.
5. Record remaining source-specific connector/CDC/production-security work as later scope.
6. Approve and fingerprint the exact readiness report consumed by Track B.

**PP3-A9 status (2026-07-31).** `ingestion/ONBOARDING.md` is published and the full stateful gate
passes in governed NO-GO mode with zero failures: contracts 122, execution 12, datagen 52,
ingestion 153, database 1, ML 93, uncached Go race tests green, UI 11 plus typecheck and build,
import boundaries clean across 92 files. Track A code is complete and verified.

Two things are deliberately **not** decided here. `retail-staging/v2` stays
`frozen_not_cut_over`: v1 remains the runtime contract, so PP3-A3's exact parity proves v2 *could*
cut over without proving it *should*, and that call is a review decision rather than an
implementation one. And the staging-fingerprint coverage gap in §1.4.2 is recorded rather than
fixed, because widening staging identity would invalidate the accepted pin.

**Track A acceptance statement:**

> A new retailer can be landed through an approved mapping or bounded adapter, validated into
> standardized roles and transformed by unchanged shared canonical code. Each downstream
> capability is independently authorized or rejected from temporal/data/statistical evidence.

Do not claim “any retailer data works automatically.”

---

## 7 · Track B work packages — forecast quality and presentation

### PP3-B1 · Implement the finalized diagnostic and candidate protocol

**Purpose:** prevent post-result threshold or candidate selection.

Tasks:

1. Confirm decided #82 is implemented in the PP3-P0 C0/D0 authority; Track B cannot start before
   that implementation passes.
2. Implement decisions #74/#75 without changing their frozen origin split, budget or thresholds.
3. Bind the new PP3-P0 complete-population decision-#82 acceptance/verifier result:
   - if accepted, it becomes accepted comparison authority C0;
   - if rejected, it becomes diagnostic comparison authority D0 only; retain its immutable
     diagnostic evidence, but never accepted/canonical-publish, materialize, activate or serve it;
   - `fr_92135aa7b5215b69` and the former v12 run remain rejected historical evidence and are
     neither C0 nor D0 because they do not satisfy the repaired comparison authority.
4. Materialize the finalized comparison keys, cohort membership keys and additive metrics.
5. Require every candidate to publish both decision-#82 cohorts and pass the cold-start gate; no
   paired-WAPE improvement can compensate for missing cohort completeness.
6. Use the finalized first-8 development and final-5 untouched confirmation origin roles without
   changing the 13-origin acceptance schedule.
7. Register allowed candidate families and search budgets.
8. Use 10,000 SeriesKey-clustered replicates, seed `20260731`, the 95% upper-bound `<0`
   materiality rule and the ≤1% supported-market regression bound.
9. Publish the finalized market, store, category, channel, lifecycle/intermittency and
   h1/h4/h8/h13/h26 slices at their exact grains.
10. Define stop rules for leakage, changed population, coverage failure and market failure.

**Exit:** B-D3 is approved before any candidate result exists.

### PP3-B2 · Publish the immutable diagnostic baseline

Publish global and sliced evidence for:

- market;
- store;
- category/department;
- channel;
- lifecycle;
- intermittency/zero-share band;
- model route;
- history length;
- h1, h4, h8, h13 and h26;
- source/readiness limitation.

Metrics:

- `abs_error_sum`, `signed_error_sum`, `actual_sum`, `coverage_hits`, `n`;
- WAPE and accuracy;
- signed bias;
- P90 coverage;
- P50–P90 absolute and relative width;
- governed confidence;
- FVA versus MA13;
- improvement versus seasonal naive;
- paired SeriesKey/origin counts;
- bootstrap intervals where declared.

The artifact includes input, feature, policy, schedule and comparison-authority fingerprints.
It also binds the new decision-#82 evaluation/verifier policy ids
(`cohorted-seasonal-cold-start-recomputation/v4` and `retail-forecast-verifier/v4`),
`retail-weekly-features/v6` and canonical serialized row ordering.
Candidate and C0/D0 metrics must be independently recomputed from identically governed complete
rows under decision #82; a changed eligible population or reliance on a caller-supplied
acceptance boolean is a hard failure.

Record the current A3 evidence margin: US New York has exactly 100 eligible slow-mover series,
the frozen minimum, with a minimum of 73 paired series per origin. A candidate may not improve
its display by dropping that population; falling below the frozen sufficiency rule produces
`insufficient_evidence`, not a pooled substitute.

**Exit:** B-D1 is immutable and reproducible.

### PP3-B3 · Diagnose root causes before selecting remedies

Test registered hypotheses:

1. market/horizon systematic under-bias;
2. category/store/channel composition;
3. intermittent routing and fallback behavior;
4. lifecycle/cold-start treatment;
5. censored sales/stock-out effects;
6. insufficient assortment/exposure evidence;
7. feature fallback at longer horizons;
8. model pooling across heterogeneous segments;
9. calibration fallback;
10. optional-signal absence.

Use attribution, residual slices, calibration curves and ablations. Correlation is not causation;
do not claim a source limitation caused forecast error without controlled evidence.
The first registered cold-start hypothesis is the v15 US-market proxy deficit in §3.1; test
whether lifecycle treatment, pooling or intermittent routing explains it without changing
decision #82.

**Exit:** B-D2 ranks supported causes, rejects unsupported stories and maps each proposed candidate
to one cause.

### PP3-B4 · Bias correction and quantile calibration candidates

Candidate C1 — P50 bias correction:

- learn only from origin-safe calibration rows;
- start at market × horizon;
- shrink insufficient cells to a sufficient parent;
- never learn from active future-only predictions;
- preserve non-negative domain rules.

Candidate C2 — P90 calibration:

- preserve decision #58 sufficiency/fallback;
- calibrate per market × horizon where sufficient;
- report fallback use;
- require P90 ≥ P50 row-wise;
- improve sharpness only while coverage remains 0.85–0.95.

Evaluate C1, C2 and C1+C2 separately. Do not hide a P50 degradation behind improved confidence.

**Exit:** B-D4 records accepted/rejected candidates and paired evidence.

### PP3-B5 · Segmentation and hierarchical reconciliation

Candidate C3 — segmented champions:

- market;
- category/department where sufficient;
- lifecycle;
- governed demand behavior/intermittency;
- current LightGBM and Croston routes;
- transparent shrinkage/fallback to parent/global.

The US cold-start slice is an explicit candidate diagnostic. A lifecycle/cold-start candidate
must improve it on untouched confirmation origins without degrading established-history rows or
weakening the complete per-market cold-start gate.

Freeze minimum rows, SeriesKeys and origins before scoring. No one-off segment model is allowed
because its displayed accuracy is weak.

Candidate C4 — hierarchy reconciliation:

- SeriesKey → store/category → market;
- preserve non-negativity and market separation;
- compare bottom-up, top-down and a reviewed reconciliation method;
- measure leaf and aggregate quality separately;
- do not relabel aggregate accuracy as SeriesKey accuracy.

**Exit:** B-D5/B-D6 identify a bounded champion composition or record no-go.

### PP3-B6 · Optional origin-safe signals and quality policy v2

Signal work is capability-gated by Track A:

- future promotion plan;
- weather forecast beyond currently available leads;
- competitor availability/plan;
- stock-out/censored-demand evidence;
- lifecycle/assortment change.

For each signal:

1. require role/readiness coverage;
2. freeze origin/target-date semantics;
3. add explicit missing/fallback indicators;
4. run an ablation against identical paired rows;
5. reject leakage or post-origin actuals;
6. keep the signal optional with reason-coded unavailability.

Quality policy v2 proposal:

- keep publication/global capability limitations visible;
- classify row-local key, reconciliation, missingness, freshness and coverage separately;
- do not make all rows `Watch` solely because one global warning exists;
- do not hide that warning by dropping it;
- publish separate fields such as `global_limitations` and `row_quality_class`;
- require new vectors, policy ids/fingerprints and an accepted candidate.

**Exit:** B-D7/B-D8 are reviewed. Policy v1 remains active unless the candidate passes.

### PP3-B7 · Business target matrix and presentation contract

Implement decision #77's exact-horizon accuracy targets:

| Display grain | h1 | h4 | h8 | h13 | h26 |
|---|---:|---:|---:|---:|---:|
| Market / portfolio | 90% | 88% | 85% | 82% | 78% |
| Store / category | 85% | 82% | 78% | 75% | 70% |
| SeriesKey | 80% | 78% | 75% | 72% | 68% |

Every cell also requires absolute bias ≤5% and P90 coverage in `[0.85, 0.95]`. An insufficient
denominator is unavailable, never a passing status.

Do not assume one 90% threshold. A portfolio/category target may differ from a
SKU × store × channel target, but every UI value must label its exact grain.

Presentation update principles:

- preserve the original HTML layout unless explicitly approved;
- show accuracy with market/horizon context;
- lead with FVA, seasonal-naive lift and calibrated coverage where helpful;
- explain confidence as uncertainty/spread, not model correctness;
- distinguish global capability limitations from row-local data quality;
- retain weak slices and unavailable signal states;
- never add a “green” label not backed by the target matrix;
- render governed unavailable state until a new accepted version activates.

Forecast Health correction:

1. Consume the amended decision #64/Q6 parity/data matrix; do not reinterpret it in React.
2. Always render exactly four default rows in reference order: `1 week`, `4 weeks`, `8 weeks`,
   `13 weeks`; the selected forecast cap must not hide diagnostic rows.
3. Implement decision #80's exact-horizon additive metrics at h1/h4/h8/h13 rather than cumulative
   `1..N`; labels must make the meaning unambiguous.
4. Keep h26 in the immutable diagnostic baseline, not the four-row reference table. A fifth row
   or drilldown requires separate visual approval.
5. Replace coverage-only status derivation with decision #80's target-relative matrix at the
   displayed grain/horizon: `Strong` requires accuracy ≥ target+5, absolute bias ≤3% and coverage
   0.87–0.93; `Healthy` requires accuracy ≥ target, absolute bias ≤5% and coverage 0.85–0.95;
   `Watch` requires accuracy ≥ target−10, absolute bias ≤10% and coverage 0.80–0.98; otherwise
   use `Action`. Any unavailable metric yields unavailable, not a badge.
6. Prove desktop and responsive row count/order, labels, live values, filter independence and
   status mapping. Changing market/store/category/channel may recompute the rows; changing the
   operational horizon cap may not remove them.
7. Execute the same fingerprinted grain-resolution and status vectors in Python, Go and React;
   percentage points and coverage ratios must not be converted implicitly by any layer.

Update the parity/data matrix before React code. Review screenshots and wording before
implementation. Until this correction is implemented, Phase 3 visual approval must explicitly
record the known deviation if it is accepted for deferral.

**Exit:** decisions #77/#78/#80 and B-D9/B-D10 are approved.

### PP3-B8 · Full acceptance, publication, serving and UI activation

Run the unchanged fixed schedule and the decision-#82 versioned A1–A5 battery:

1. established-history A1: ≥25% WAPE improvement over seasonal naive with complete cohort pairing;
   cold-start A1: complete cohort comparison and the separately frozen non-inferiority gate;
2. P90 coverage 0.85–0.95;
3. slow-mover WAPE no worse than seasonal naive under decision #52 sufficiency;
4. P90 ≥ P50 row-wise;
5. no supported-market failure hidden globally.

Also require:

- C0-or-D0/candidate paired improvement gate from decision #75;
- additive-metric consistency;
- leakage checks;
- calibration sufficiency;
- deterministic profile invariance;
- role/readiness/input lineage;
- classification policy fingerprint;
- API projection mapping;
- UI data-value and parity tests;
- decision-#82 verifier materialization eligibility and request-time active-lineage
  revalidation;
- developer-run supported-OS evidence.

If any required gate fails:

- publish a rejected immutable candidate and evidence;
- do not materialize/activate it;
- keep forecast serving fail-closed when no accepted active version exists.

If all gates pass:

1. publish a new immutable accepted run/version;
2. verify all artifacts;
3. materialize transactionally into PostgreSQL;
4. create a separate activation record;
5. verify all API routes and fail-closed states;
6. deploy the reviewed presentation update;
7. obtain final human visual approval;
8. retain rollback through a new activation record only when a prior decision-#82-verifier accepted version
   exists.

**Exit:** B-D11/B-D12 and the Post–Phase 3 retrospective are complete.

---

## 8 · Acceptance gates

### 8.1 Track A gates

| Gate | Pass condition |
|---|---|
| OA1 Boundary | platform/retailer identifiers occur only in approved adapters/profiles/fixtures |
| OA2 Contract | every transform consumer maps to a complete v2 role |
| OA3 Provider | ownership/collision policy is explicit and deterministic |
| OA4 Validation | shared role checks cannot be bypassed by either adapter type |
| OA5 Mapped files | non-platform fixture reaches canonical publication without custom code |
| OA6 Custom adapter | genuinely different fixture reaches the same roles without downstream branch |
| OA7 Temporal | evidence grades and zero eligibility fail closed on negative fixtures |
| OA8 Readiness | capability and statistical verdicts are separate and reason-coded |
| OA9 Selection | tenant/capability pin is immutable, explicit and lineage-complete |
| OA10 Parity | accepted v12 v1/v2 canonical results and controls reconcile |
| OA11 Round trip | new retailer reaches unchanged transforms/ML when capability allows |
| OA12 Portability | developer-run macOS/Windows/Linux evidence passes; no CI added |

### 8.2 Track B gates

| Gate | Pass condition |
|---|---|
| OQ1 Baseline | immutable, reproducible, independently recomputed and filter/additive-consistent |
| OQ2 Pairing | candidate and C0/D0 use identical decision-#82 cohort membership and complete eligible row keys |
| OQ3 Materiality | decision #75 paired improvement passes |
| OQ4 A1–A5 | decision-#82 established and cold-start gates plus A2–A5 pass globally and per supported market |
| OQ5 Bias | signed/absolute bias is reported; no hidden material slice regression |
| OQ6 Coverage | 0.85–0.95 with monotonic quantiles |
| OQ7 Sharpness | any confidence improvement comes from valid sharper intervals |
| OQ8 Leakage | all features/corrections/calibration are origin-safe |
| OQ9 Determinism | safe/high-performance outputs agree within frozen tolerances |
| OQ10 Policy | policy/version/fingerprints and vectors are complete |
| OQ11 Serving | immutable bundle verifies; PostgreSQL lineage matches activation |
| OQ12 UI | exact grain/wording/data mapping; fixed h1/h4/h8/h13 health rows; governed statuses; human parity review pass |

### 8.3 No-go conditions

Stop the affected work package when:

- the PP3-P0 repaired acceptance/evidence gate or any Phase 3 exit item is incomplete;
- a role consumer has no defensible source-neutral schema;
- the mapping language would need arbitrary executable code;
- historical availability is inferred only from business dates;
- zero demand lacks extract/assortment evidence;
- a retailer fixture requires a downstream branch;
- a capability is statistically insufficient;
- candidate selection used confirmation/future-only rows;
- candidate pairing changes the evaluation population;
- a supported market or existing A1–A5 gate fails;
- interval narrowing breaks coverage;
- a UI improvement requires relabelling or hiding evidence;
- tenant/source lineage cannot be proven.

---

## 9 · Test and evidence matrix

### 9.1 Contract tests

- staging v2 schema and role completeness;
- adapter manifest and mapping schema;
- provider-resolution vectors;
- temporal-evidence vectors;
- readiness-report schema;
- publication-selection schema;
- improvement-comparison policy;
- quality policy v2;
- screen parity contract;
- generated types current;
- repository-CI prohibition.

### 9.2 Ingestion tests

- all four physical formats;
- profile/mapping fingerprint determinism;
- role binding and collision modes;
- common key/type/money/time validation;
- quarantine provenance;
- neutral crosswalks;
- mapped-files fixture;
- custom-adapter fixture;
- negative temporal/assortment/completeness fixtures;
- v1/v2 canonical parity;
- full client-shaped round trip;
- import/source-name boundaries;
- safe/high-performance equivalence.

### 9.3 ML tests

- baseline additive metrics;
- paired comparison keys;
- origin-role enforcement;
- bias correction fit cutoff;
- calibration sufficiency/fallback;
- P90/P50 monotonicity;
- segment sufficiency/shrinkage;
- hierarchical totals and leaf preservation;
- optional-signal leakage/ablation;
- quality policy v2 vectors;
- A1–A5 unchanged;
- immutable publication and verification;
- profile invariance.

### 9.4 API/database/UI tests

- only active lineage-matching version is served;
- accepted-but-unmaterialized/inactive states return governed 503 and stale lineage returns 409;
- activation remains separate;
- market/store/category/channel/horizon intersections use additive metrics;
- global limitations and row-local quality map correctly;
- no Parquet/DuckDB request-path access;
- Forecast Health always has four h1/h4/h8/h13 rows in reference order, independent of the
  operational horizon selector, with decision-#80 metrics and statuses;
- desktop/responsive DOM, screenshot and live-data parity;
- modal and unavailable-state behavior;
- rollback activation.

### 9.5 Manual evidence

Record commands, versions, OS, hardware profile, duration, peak memory, object hashes and result
for macOS, Windows and Linux. Do not represent a skipped platform as passed and do not create CI.

---

## 10 · Security, privacy and operational constraints

1. Profiles/mappings contain no credentials.
2. Logical paths are normalized and cannot escape the declared landing root.
3. Readers enforce declared file type, size/row limits and decompression bounds.
4. JSON/CSV parsing does not evaluate formulas or code.
5. Mapped expressions use an allowlist.
6. Custom adapters are reviewed application code; arbitrary uploaded Python is prohibited.
7. Tenant ids and publication lineage cannot mix within one run.
8. Raw customer identifiers are minimized/quarantined according to canonical scope.
9. Quarantine payloads avoid copying unnecessary PII; hashes/provenance remain sufficient.
10. Immutable source/curated/ML artifacts remain outside PostgreSQL workflow ownership.
11. AWS migration uses the same contracts: object storage for immutable data, RDS-compatible
    PostgreSQL serving projection and environment-based secrets.
12. Local Docker Compose remains loopback-only with pinned services and health checks.
13. No write action reaches a retailer system; the PoC remains shadow-only.

---

## 11 · Sequencing and review gates

```text
PP3-P0 Phase 3 close
  ↓
PP3-A1 coupling inventory
  ↓
PP3-A2 role/adapter contracts
  ↓
PP3-A3 neutral staging + v1/v2 parity
  ├─→ PP3-A4 mapped-files adapter
  └─→ PP3-A5 custom-adapter protocol
          ↓
PP3-A6 temporal/readiness
  ↓
PP3-A7 tenant publication selection
  ↓
PP3-A8 client-shaped round trips
  ↓
PP3-A9 Track A review/acceptance
  ↓
PP3-B1 diagnostic/candidate protocol
  ↓
PP3-B2 baseline → PP3-B3 diagnosis
  ↓
PP3-B4 bias/calibration
  ↓
PP3-B5 segmentation/reconciliation
  ↓
PP3-B6 optional signals + quality policy v2
  ↓
PP3-B7 target matrix + UI contract
  ↓
PP3-B8 acceptance/publication/activation
```

PP3-A4 and PP3-A5 may be implemented in parallel only after PP3-A2/PP3-A3 contracts are frozen.
Track B does not start from a partially accepted Track A. Presentation design does not start
before model evidence and target semantics are frozen.

The two deferred sections in `tasks.md` must remain in this same execution order: retailer-source
onboarding hardening first, forecast-quality and presentation hardening second.

---

## 12 · Risks and mitigations

| Risk | Mitigation |
|---|---|
| Role contract becomes a second canonical model | Roles stop at source-normalized staging semantics; canonical business derivation stays in transforms |
| Mapping language becomes arbitrary ETL code | allowlisted non-Turing-complete operations; custom adapter for true semantics |
| Every retailer gets copied Shopify/BC code | shared helpers + role conformance; custom adapters implement only source-specific interpretation |
| Source names leak downstream again | boundary/source-name tests and reviewed allowlist |
| Multiple sources silently conflict | explicit provider-resolution modes and collision failures |
| Business dates masquerade as availability | evidence policy, vectors and readiness downgrade |
| Missing sales become false zeros | completeness + dated assortment + channel evidence |
| “Pipeline passed” is sold as “ML ready” | separate capability readiness and statistical sufficiency |
| One demo pin is accidentally global | explicit retailer/tenant/capability selection lifecycle |
| Model work overfits known accepted origins | pre-registered candidates and development/confirmation separation |
| Candidate improves by changing repaired paired rows | bind evaluation/verifier contracts, canonical row ordering and identical governed C0-or-D0/candidate keys |
| Phase 3 closes NO-GO and Track B has no accepted C0 | freeze a repaired complete-population D0 for diagnostic comparison only; require every candidate to pass unchanged A1–A5 before creating the first accepted C0 |
| US slow-mover evidence silently becomes insufficient | retain the frozen ≥100-series/all-origin rule; publish insufficient evidence if the current exact-minimum slice shrinks |
| Better aggregate hides worse leaf forecasts | leaf and aggregate metrics reported separately |
| Confidence is cosmetically increased | coverage-constrained sharpness; confidence not an objective |
| Every row turns green by policy | global limitations retained separately from row quality |
| New UI hides weak accuracy | target matrix, exact grain, parity/data review and human approval |
| Horizon selector hides long-range health | fixed four-row h1/h4/h8/h13 diagnostic table; selector changes operational scope, not row visibility |
| Coverage-only badge looks healthier than accuracy/bias | decision-#80 multi-metric status matrix and executable vectors |
| Client data exposes PII/secrets | minimization, quarantine policy, configuration/secret separation |
| External plugin introduces code-execution risk | static in-repo registration initially; external loading deferred |
| Accepted demo becomes unreproducible | v1 retained through parity; immutable artifacts never overwritten |
| Generated data bloats or leaks through Git | §1.7 allowlists definitions and compact evidence indexes; full artifacts and all retailer data remain outside Git |

---

## 13 · Finalized implementation inputs

1. Track A is staged: authorize PP3-A1–PP3-A3 first; later packages require their listed gates.
2. CSV and Parquet are mandatory initial client formats; JSONL/JSON use the same reader contract.
3. The PoC includes the first bounded retailer adapter in this repository.
4. External adapter packages are deferred; use decided #69's static registry.
5. The selection schema supports many tenants/environments; implementation proves the demo plus
   one mapped retailer and one custom-adapter retailer.
6. Multiple providers are allowed only through decision #67's explicit modes.
7. Extract completeness is mandatory per source and must bind native control totals, partition
   coverage and cutoff evidence; absence downgrades the dependent capability.
8. Dated assortment/listing history is mandatory for historical zeros; absence prevents zero
   materialization and downgrades replay/PIT capability.
9. Minimum onboarding is `current_descriptive_analytics` plus an honest evaluation of
   `demand_forecast_non_pit`.
10. Broader PIT forecasting is unavailable until every required temporal role passes.
11. Land only fields required by approved canonical scope; customer/basket PII is excluded by
    decision #19.
12. Decision #75 fixes useful candidate improvement at ≥5% relative WAPE with its bootstrap and
    market non-regression gates. None of the three v1 runs is a comparator.
13. Decision #74 uses the first 8 origins for development, freezes one candidate, then reads the
    final 5 for untouched confirmation; decision #75 must pass on both all 13 and final 5.
14. Decision #77 fixes the market/portfolio, store/category and SeriesKey horizon targets.
15. Demand Forecast wording may change only through a reviewed parity-contract amendment.
16. Quality policy v2 may be evaluated independently but activates only with a newly accepted
    version and reviewed UI contract.
17. Forecast Health uses exact h1/h4/h8/h13 checkpoints; the operational horizon selector never
    hides them.

---

## 14 · Approval block

### Approval requested now

- retain the decision-finalization correction set already present in the working tree: decision
  registry/spec/tasks updates, the Forecast Health policy/parity contract and tests, the external
  rejection ledger, report retention cleanup and documentation corrections;
- implement decided #82, then complete the remaining PP3-P0 evidence rebaseline and Phase 3 exit;
- review the ordering and architecture;
- implement finalized decisions #65–#80 at their consumer gates;
- review work-package scope and acceptance gates;
- review the §1.7 repository/artifact-retention policy.

### Not approved by plan creation

- implementation of PP3-A1–PP3-B8;
- additional tracked contract/task/spec changes beyond the decision-finalization correction set
  above and changes explicitly required by an approved consumer gate;
- new retailer adapters;
- new source/publication pins;
- datagen changes;
- model experiments;
- runtime policy or UI implementation changes; the finalized machine-readable contracts above do
  not authorize React/model/serving behavior until their consumer gates;
- materialization or activation of any run that does not pass the repaired verifier;
- implementation commits or pushes for PP3-A1–PP3-B8.

### Final definition of done

Post–Phase 3 hardening is complete only when:

1. Phase 3 is formally closed;
2. a mapped-files retailer and a genuinely different custom adapter both reach neutral staging
   and unchanged canonical transforms;
3. temporal/readiness/statistical outcomes are explicit and fail-closed;
4. retailer/tenant publication selection replaces the one-demo-pin deployment assumption;
5. Track A round-trip and portability gates pass;
6. forecast candidates are compared against the immutable repaired C0 or diagnostic-only D0 using
   frozen complete-population evidence; D0 never authorizes accepted/canonical publication or
   serving;
7. all unchanged A1–A5 and new improvement gates pass, or an honest no-go is published;
8. any policy/presentation change is versioned, reviewed and backed by live data;
9. activation is separate, auditable and reversible;
10. no repository CI, threshold tuning, fabricated data or downstream retailer branch was added.
