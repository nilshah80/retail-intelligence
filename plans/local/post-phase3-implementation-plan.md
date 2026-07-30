# Post–Phase 3 Implementation Plan — Retailer onboarding, forecast quality and presentation

_Companion to `plans/local/plan.md` and the two deferred Post–Phase 3 sections in
`plans/local/tasks.md`._
_Ingestion authority: `ingestion/README.md`, `contracts/profiles/profile.schema.json`,
`contracts/staging/staging.yaml`, `contracts/retail_v2/schema.yaml`._
_Forecast authority: `docs/demand_forecast_poc_spec.md` §3.1–3.4, §3.9, §4.2–4.4 and §4.8;
`contracts/ml/*`; `contracts/screens/demand-forecast.parity.yaml`._
_Validation authority: `contracts/validation-policy.yaml`; repository CI is prohibited._

**Revision 7 — 2026-07-31. CONTEXT-FEED SWEEP COMPLETE; FORECAST NO-GO; W1+ NOT AUTHORIZED.**
The final adversarial review invalidates both the former v12 forecast and verifier-v2 run
`fr_92135aa7b5215b69`. The latter drops 102,804 harder rows from A1's seasonal-naive comparison,
so acceptance-v2 fails the spec's overall gate despite the paired subset exceeding 25%.
Feature-schema-v6, forecast-run-v2, verifier-v3 and migration 0005 repairs are implemented
locally. V6 removes the false h1 local-event availability indicator, its permanently-null future
features and the unavailable market-disruption feature under driver-semantics-v3. A full-column
invariant now rejects any structurally all-null feature. A new backtest/publication has not established
accepted evidence.
W0 therefore remains open for the full rerun, developer gate, listed manual Phase 3 gates,
known Forecast Health visual-parity disposition and retrospective. Track A/B
implementation begins only after the complete Phase 3 exit and a recorded retrospective
go-ahead. The plan deliberately orders
**retailer-source onboarding hardening before forecast-quality and presentation hardening**.
That order protects the central architecture promise: retailer variation is absorbed by
profiles/adapters and standardized staging roles; canonical transforms, ML, API and UI do not
gain retailer-specific branches.

The current user direction authorizes the W0 Phase 3 repairs and clean evidence rerun. Do not
begin W1 or later, create a new input pin, tune thresholds/models, change the UI, or modify
datagen until the applicable approval gate below is explicitly passed.

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

This document specifies Track B now so the whole program can be reviewed, but W10 and later do
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
| Review-#2 semantic repairs and focused tests | Passed locally | Full W0 rerun |
| Feature-schema-v6 build and characterization | Passed; `f3ff8725d36d78ff…`, 1,072,430 rows | Backtest |
| Short-history A1 comparator/eligibility policy (#82) | Open; strict decision #81 makes the current panel unacceptable | Backtest |
| Acceptance-v2 run independently recomputes and passes A1–A5 | Open; prior run fails A1 | W1 |
| Verifier-v3 run materialized/activated and `tools/dev.py verify` passes | Open | W1 |
| Phase 3 manual Windows feature/training/publication evidence | Open | W1 |
| Phase 3 manual Linux feature/training/publication evidence | Open | W1 |
| Full pinned-data 16-GB vs high-performance benchmark comparison | Open | W1 |
| Explicit user approval of the Demand Forecast UI | Open | W1 |
| Forecast Health four-row HTML-parity disposition | Open; correction planned in W16 | UI approval must explicitly accept deferral or authorize an earlier correction |
| Post–Phase 3 retrospective go/no-go and scope | Open | W1 |
| Track A contract/design review | Open | W2 |
| Track A client-shaped round-trip acceptance | Open | W9 / Track B |
| Track B diagnostic and candidate protocol review | Open | W10 |
| Track B UI target/parity review | Open | W16 |

### 0.4 Workstream states

| Workstream | Contents | State |
|---|---|---|
| W0 | Phase 3 repair, evidence rebaseline, closure and retrospective | **IN PROGRESS** |
| Track A / W1–W9 | neutral roles, mapped files, custom adapters, readiness, tenant pins | **AWAITING W0** |
| Track B / W10–W17 | diagnostics, candidate models, policy v2, presentation, publication | **AWAITING Track A** |
| Later productionization | connectors, CDC, secrets, IAM, managed orchestration | **OUT OF SCOPE** |

### 0.5 Non-negotiable invariants

1. The accepted v12 source publication remains the immutable input authority. The former v12
   forecast and `fr_92135aa7b5215b69` are rejected and must not be served. No C0 comparison
   authority exists until a forecast-run-v2/verifier-v3 candidate passes acceptance-v2.
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
| Rejected diagnostic run | `fr_92135aa7b5215b69` |
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
| Current SeriesKeys / rows | 2,034 / 52,884 |
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

### 1.2 Known Forecast Health visual-parity deviation

The original HTML always renders four rows — `1 week`, `4 weeks`, `8 weeks`, `13 weeks` — even
when the toolbar defaults to `Next 4 Weeks`. The current React implementation filters
`[1, 4, 8, 13, 26]` by the selected horizon, so the default renders only `Weeks 1–1` and
`Weeks 1–4`. The API already exposes all 26 additive horizon rows; this is not a data or serving
limitation.

The current implementation also cumulatively aggregates horizons `1..N` and derives status from
coverage alone, whereas the reference labels discrete checkpoints and shows the four-state
vocabulary `Strong / Healthy / Watch / Action`. Decision #64/Q6 and the current parity YAML
encoded the hiding behavior, so W16 must amend that authority before React changes.

The required W16 outcome is four rows in reference order through week 13, independent of the
selected operational horizon. Decision #80 must freeze exact-horizon versus cumulative
calculation and the governed status matrix; exact h1/h4/h8/h13 is recommended because it
preserves horizon deterioration instead of blending it away. h26 remains in diagnostic evidence
and may appear only in a separately approved drilldown, not as a fifth default reference row.

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
- production CDC/upsert/watermark semantics under open decision #26;
- a general transformation programming language;
- executing untrusted customer Python as an adapter;
- moving the immutable lake into PostgreSQL;
- changing Phase 4–8 inventory, pricing, workflow or admin scope;
- guaranteeing that every retailer has enough history or variation for ML;
- promising a universal 90% SeriesKey accuracy;
- adding CI workflows;
- auto-activating a candidate or sending operational actions.

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

The exact schemas are frozen in W2. The initial catalog must cover every standardized relation the
current canonical transform consumes.

| Group | Initial roles |
|---|---|
| Demand transactions | `merchandise`, `adjustment`, `fulfillment` |
| Core dimensions | `product`, `product_reference`, `location`, `channel`, `assortment`, `sell_price` |
| Inventory/procurement | `inventory`, `receipt`, `supplier_term`, `inventory_cost`, `inventory_batch`, `inbound_shipment`, `transfer_order`, `waste_event`, `warehouse_capacity`, `wms_comparison`, `supplier_performance` |
| Reconciliation controls | `invoice_sales_control`, `customer_segment_count` |
| Context | `holiday`, `fx_rate`, `market_disruption`, `customer_segment`, `weather_actual`, `weather_forecast`, `local_event`, `macro_index` |
| Competition/promotion | `competitor_price`, `competitor_match`, `promotion`, `promotion_target` |
| Allocation | `allocation_demand`, `allocation_supply` |

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

For the PoC, recommend **static in-repository registration with an explicit adapter manifest**.
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
new W0 independently verified accepted version (C0)
  ← former v12 retained only as rejected historical diagnostic
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

---

## 3 · Decisions to freeze before implementation

Numbers below are proposed placeholders. Record approved decisions in `docs/OPEN_DECISIONS.md`
before their consumers start.

| Proposed # | Decision | Recommended default | Consumer gate |
|---|---|---|---|
| 65 | Post–Phase 3 scope/order | Track A fully accepted before Track B implementation | W1 |
| 66 | Staging migration | versioned v2 dual-run; no in-place v1 rewrite | W2 |
| 67 | Role provider resolution | explicit exclusive/union/cross-validate/fallback | W2 |
| 68 | Mapped-files language | allowlisted non-Turing-complete operations only | W4 |
| 69 | Custom-adapter loading | static in-repo registry for PoC; external plugin deferred | W5 |
| 70 | Temporal evidence/readiness | five evidence grades; business date never proves availability | W6 |
| 71 | Zero-demand eligibility | completeness + dated assortment + cutoff availability | W6 |
| 72 | Capability vocabulary | separate readiness and statistical-sufficiency verdicts | W6 |
| 73 | Retailer pin lifecycle | explicit tenant/capability/environment selection; never latest | W7 |
| 74 | Candidate-selection protocol | pre-registered families; development vs confirmation origins | W10 |
| 75 | Improvement materiality | paired WAPE/bootstrap rule plus per-market non-regression | W10 |
| 76 | Quality policy v2 | separate publication/global limitations from row-local quality | W15 |
| 77 | Business target matrix | metric/grain/horizon-specific; no universal 90% assumption | W16 |
| 78 | Presentation policy | lead with contextual evidence; preserve weak slices and exact grain | W16 |
| 79 | Provenance vocabulary | source-neutral evidence/derivation classes; source identity stays separate | W2 |
| 80 | Forecast Health horizon semantics | four fixed h1/h4/h8/h13 rows; freeze exact/cumulative formula and status matrix; amend #64/Q6 | W16 |

### 3.1 Decisions that must remain unchanged

Do not reopen #10–#13, #16, #20, #29, #35, #38, #41, #46 or #49–#63 merely because this
workstream exists. Decision #64/Q6 is changed only through the explicitly proposed #80 amendment;
all other #64 parity decisions remain frozen. If evidence proves another decision is unsound,
stop and propose a separately versioned decision amendment with affected artifacts and replay
scope.

### 3.2 Required formulas for decision #75

Freeze the exact comparison before candidates are scored:

- `candidate_wape = SUM(candidate_abs_error_sum) / SUM(actual_sum)`;
- `active_wape = SUM(active_abs_error_sum) / SUM(actual_sum)`;
- paired keys include input publication, origin, horizon and SeriesKey;
- `delta_wape = candidate_wape − active_wape`; lower is better;
- use a seeded SeriesKey-clustered bootstrap interval over paired contributions;
- require a pre-declared material global improvement and no material supported-market regression;
- report market, store, category, channel, lifecycle/intermittency and h1/4/8/13/26 slices;
- do not accept Simpson’s-paradox improvement hidden by a changed row population;
- treat a zero `actual_sum` slice as `insufficient_evidence`.

The numeric materiality and non-regression tolerances must be chosen from operational relevance
before candidate results are visible. They cannot be tuned after scoring.

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
| Retailer retrospective go/no-go | W0 |
| Inventory/remove platform coupling | W1, W3 |
| Freeze standardized staging roles | W2 |
| Neutral quarantine/quality validation | W3 |
| Mapped-files default adapter | W4 |
| Versioned custom-retailer adapter path | W5 |
| Registration/packaging/conformance | W5 |
| Temporal-evidence policy/readiness report | W6 |
| Zero-demand eligibility | W6 |
| Capability-specific onboarding outcomes | W6 |
| Per-retailer/per-tenant publication pinning | W7 |
| Mapped and custom adapter fixtures | W4, W5, W8 |
| Separate statistical sufficiency | W6, W8 |
| Client-shaped unchanged-downstream round trip | W8 |
| Architecture/spec/guide reconciliation | W9 |
| Frozen forecast diagnostic baseline | W10, W11 |
| Under-forecast root-cause diagnosis | W12 |
| Market × horizon bias/calibration | W13 |
| Segmented champion candidates | W14 |
| Hierarchical reconciliation | W14 |
| Coverage-constrained interval sharpness | W13 |
| Optional origin-safe retailer signals | W15 |
| Quality policy v2 | W15 |
| Business metric/grain/horizon target matrix | W16 |
| Forecast Health fixed four-row parity and metric/status semantics | W16 |
| Demand Forecast presentation update | W16 |
| Full A1–A5 and immutable publication acceptance | W17 |

---

## 5 · Proposed file layout

Names are targets, not authorization to create them.

```text
contracts/
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
  reports/
    post-phase3/
  tests/
    test_diagnostic_baseline.py
    test_candidate_comparison.py
    test_reconciliation.py
    test_quality_policy_v2.py
```

Do not create retailer-specific modules outside `ingestion/adapters/` or test fixtures. Tenant
instance selections and credentials are runtime configuration, not committed contracts.

---

## 6 · Track A work packages — retailer-source onboarding hardening

### W0 · Close Phase 3 and authorize the workstream

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
8. Regenerate characterization, 13-origin H1–H26 backtest, current-cycle classifications and a
   new immutable forecast-run bundle. Never edit/re-sign the former v12 bundle.
9. Publish/activate only if the repaired verifier concludes accepted; otherwise retain an honest
   rejected candidate and keep the API fail-closed.
10. Replace superseded v11/v12 tracked reports with same-pin evidence, then pass the full stateful
   local gate.
11. Record manual Windows and Linux portability evidence.
12. Record the full pinned-data 16-GB/high-performance benchmark comparison.
13. Obtain explicit Demand Forecast visual approval.
14. Hold the Phase 3 retrospective.
15. Record go/no-go, scope, supported initial formats and whether custom adapter code is in scope.
16. Approve only W1–W3 first; later work remains gated.

**Exit:** a newly derived forecast bundle passes independent verification and the local phase-exit
gate (or Phase 3 is explicitly closed NO-GO with serving disabled), `tasks.md` Phase 3 exit is
complete, and decision #65 is recorded.

### W1 · Coupling inventory and boundary test

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
6. Fail on an unmapped consumer; do not create an “other” escape hatch.
7. Extend import/boundary checks with a reviewed allowlist.

**Evidence:** machine-readable occurrence report plus reviewed role map.

**Exit:** A-D1 approved; no v2 code starts with an unknown consumer.

### W2 · Freeze staging v2 and role bindings

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

### W3 · Build source-neutral assembly, validation and quarantine

**Purpose:** remove source names from shared staging behavior.

Tasks:

1. Make adapters publish role bindings rather than relying on fixed source table names.
2. Build role tables/views from bindings and provider-resolution policy.
3. Move row validation to role-schema-driven common checks.
4. Move semantic checks into role-specific neutral validators.
5. Replace source-named quarantine datasets with role id + provider/source provenance.
6. Build location/product/channel crosswalks from neutral roles.
7. Preserve raw-object lineage on every row and finding.
8. Produce a v2 staging manifest with role providers, counts, quarantine and fingerprints.
9. Keep transforms reading stable neutral names.
10. Dual-run v1/v2 on a small fixture, then the accepted v12 snapshot.

**Parity rules:**

- same canonical rows by complete business key and value;
- same source reconciliation totals;
- same Gate-B pass/fail and reason counts;
- same capability mask;
- any difference is explained and reviewed before cutover;
- accepted source-v12 artifacts are not overwritten.

**Exit:** A-D4/A-D11 pass; source-name scan is clean outside the allowlist.

### W4 · Implement mapped-files default adapter

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

### W5 · Implement bounded custom-adapter extension

**Purpose:** provision for real retailer semantics that mappings cannot express.

Tasks:

1. Freeze the custom-adapter protocol and manifest.
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

### W6 · Temporal evidence, zero demand and readiness

**Purpose:** make “safe for ML” a measured capability verdict.

Tasks:

1. Freeze decisions #70–#72.
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

### W7 · Retailer/tenant publication selection

**Purpose:** stop assuming one repository-committed demo pin.

Tasks:

1. Freeze decision #73 and selection schema.
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

### W8 · Client-shaped round trips and conformance gate

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

### W9 · Track A finalization

Tasks:

1. Review all Track A contracts, parity and negative evidence.
2. Decide whether staging v2 becomes current or remains a candidate.
3. If accepted, update architecture/spec/tasks/README/operations documentation.
4. Publish the onboarding guide and mapping/custom-adapter decision tree.
5. Record remaining source-specific connector/CDC/production-security work as later scope.
6. Freeze the exact readiness report consumed by Track B.

**Track A acceptance statement:**

> A new retailer can be landed through an approved mapping or bounded adapter, validated into
> standardized roles and transformed by unchanged shared canonical code. Each downstream
> capability is independently authorized or rejected from temporal/data/statistical evidence.

Do not claim “any retailer data works automatically.”

---

## 7 · Track B work packages — forecast quality and presentation

### W10 · Freeze diagnostic and candidate protocol

**Purpose:** prevent post-result threshold or candidate selection.

Tasks:

1. Freeze decisions #74/#75.
2. Freeze the next acceptance-v2/verifier-v3 accepted run as C0.
   `fr_92135aa7b5215b69` and the former v12 run are rejected historical evidence and are never
   comparators.
3. Freeze paired comparison keys and additive metrics.
4. Freeze development vs confirmation origin roles without changing the 13-origin acceptance
   schedule.
5. Register allowed candidate families and search budgets.
6. Freeze bootstrap seed, clustering unit and materiality/non-regression rules.
7. Freeze slices and exact display grain.
8. Define stop rules for leakage, changed population, coverage failure and market failure.

**Exit:** B-D3 is approved before any candidate result exists.

### W11 · Publish the immutable diagnostic baseline

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

The artifact includes input, feature, policy, schedule and active-version fingerprints.
It also binds `paired-seasonal-complete-recomputation/v3`,
`retail-forecast-verifier/v3`, feature schema v4 and canonical serialized row ordering. Candidate
and C0 metrics must be independently recomputed from identically paired finite rows; a changed
eligible population or reliance on a caller-supplied acceptance boolean is a hard failure.

Record the current A3 evidence margin: US New York has exactly 100 eligible slow-mover series,
the frozen minimum, with a minimum of 73 paired series per origin. A candidate may not improve
its display by dropping that population; falling below the frozen sufficiency rule produces
`insufficient_evidence`, not a pooled substitute.

**Exit:** B-D1 is immutable and reproducible.

### W12 · Diagnose root causes before selecting remedies

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

**Exit:** B-D2 ranks supported causes, rejects unsupported stories and maps each proposed candidate
to one cause.

### W13 · Bias correction and quantile calibration candidates

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

### W14 · Segmentation and hierarchical reconciliation

Candidate C3 — segmented champions:

- market;
- category/department where sufficient;
- lifecycle;
- governed demand behavior/intermittency;
- current LightGBM and Croston routes;
- transparent shrinkage/fallback to parent/global.

Freeze minimum rows, SeriesKeys and origins before scoring. No one-off segment model is allowed
because its displayed accuracy is weak.

Candidate C4 — hierarchy reconciliation:

- SeriesKey → store/category → market;
- preserve non-negativity and market separation;
- compare bottom-up, top-down and a reviewed reconciliation method;
- measure leaf and aggregate quality separately;
- do not relabel aggregate accuracy as SeriesKey accuracy.

**Exit:** B-D5/B-D6 identify a bounded champion composition or record no-go.

### W15 · Optional origin-safe signals and quality policy v2

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

### W16 · Business target matrix and presentation contract

Freeze targets by:

- metric;
- grain;
- horizon;
- market;
- operational use.

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

1. Amend decision #64/Q6 and the parity/data matrix before React code.
2. Always render exactly four default rows in reference order: `1 week`, `4 weeks`, `8 weeks`,
   `13 weeks`; the selected forecast cap must not hide diagnostic rows.
3. Freeze decision #80's row formula. Recommend the exact horizon's additive metrics at h1/h4/
   h8/h13 rather than cumulative `1..N`; labels must make the selected meaning unambiguous.
4. Keep h26 in the immutable diagnostic baseline, not the four-row reference table. A fifth row
   or drilldown requires separate visual approval.
5. Replace coverage-only status derivation with a governed matrix using the approved accuracy,
   bias and coverage targets at the displayed grain/horizon. Preserve the reference status
   vocabulary `Strong / Healthy / Watch / Action`; unavailable evidence remains unavailable.
6. Prove desktop and responsive row count/order, labels, live values, filter independence and
   status mapping. Changing market/store/category/channel may recompute the rows; changing the
   operational horizon cap may not remove them.

Update the parity/data matrix before React code. Review screenshots and wording before
implementation. Until this correction is implemented, Phase 3 visual approval must explicitly
record the known deviation if it is accepted for deferral.

**Exit:** decisions #77/#78/#80 and B-D9/B-D10 are approved.

### W17 · Full acceptance, publication, serving and UI activation

Run the unchanged fixed schedule and A1–A5:

1. ≥25% WAPE improvement over seasonal naive;
2. P90 coverage 0.85–0.95;
3. slow-mover WAPE no worse than seasonal naive under decision #52 sufficiency;
4. P90 ≥ P50 row-wise;
5. no supported-market failure hidden globally.

Also require:

- active-vs-candidate paired improvement gate from decision #75;
- additive-metric consistency;
- leakage checks;
- calibration sufficiency;
- deterministic profile invariance;
- role/readiness/input lineage;
- classification policy fingerprint;
- API projection mapping;
- UI data-value and parity tests;
- `retail-forecast-verifier/v3` materialization eligibility and request-time active-lineage
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
8. retain rollback through a new activation record only when a prior verifier-v3 accepted version
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
| OQ2 Pairing | candidate and active use identical eligible row keys |
| OQ3 Materiality | decision #75 paired improvement passes |
| OQ4 A1–A5 | all existing gates pass globally and per supported market |
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

- the W0 repaired acceptance/evidence gate or any Phase 3 exit item is incomplete;
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
W0 Phase 3 close
  ↓
W1 coupling inventory
  ↓
W2 role/adapter contracts
  ↓
W3 neutral staging + v1/v2 parity
  ├─→ W4 mapped-files adapter
  └─→ W5 custom-adapter protocol
          ↓
W6 temporal/readiness
  ↓
W7 tenant publication selection
  ↓
W8 client-shaped round trips
  ↓
W9 Track A review/acceptance
  ↓
W10 diagnostic/candidate protocol
  ↓
W11 baseline → W12 diagnosis
  ↓
W13 bias/calibration
  ↓
W14 segmentation/reconciliation
  ↓
W15 optional signals + quality policy v2
  ↓
W16 target matrix + UI contract
  ↓
W17 acceptance/publication/activation
```

W4 and W5 may be implemented in parallel only after W2/W3 contracts are frozen. Track B does not
start from a partially accepted Track A. Presentation design does not start before model evidence
and target semantics are frozen.

After this plan is approved, reconcile the order of the two deferred sections in `tasks.md` so
the executable ledger matches this sequence. Do not perform that reconciliation while the
current Phase 3 commit is under review.

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
| Candidate improves by changing repaired paired rows | bind evaluation/verifier contracts, canonical row ordering and identical finite C0/candidate keys |
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

---

## 13 · Questions requiring review before W1

Recommended answers are included for discussion; none is frozen by this document.

1. **Is Track A approved in full or only W1–W3?** Recommend approving W1–W3 first.
2. **Which client-shaped formats are required initially?** Recommend CSV and Parquet mandatory;
   JSONL/JSON supported by the same reader contract.
3. **Is the first retailer adapter expected in this repository?** Recommend yes for the PoC.
4. **Do we need external adapter packages now?** Recommend no; freeze protocol/conformance only.
5. **How many retailer/tenant environments must selection support initially?** Recommend schema
   supports many, implementation proves demo plus one retailer fixture.
6. **May a role have multiple providers?** Recommend yes only through explicit resolution modes.
7. **What extract-completeness evidence will a real retailer supply?** Must be answered per source.
8. **What assortment/listing history exists?** If absent, historical zeros and replay downgrade.
9. **Which capability is the minimum onboarding goal?** Recommend
   `current_descriptive_analytics` plus honest evaluation of `demand_forecast_non_pit`.
10. **Is broader PIT forecasting required?** Recommend no claim until every required temporal role
    passes.
11. **What PII may be landed?** Recommend only fields required by the approved canonical scope.
12. **What numeric improvement is materially useful versus the new W0 accepted forecast?** Freeze
    before W13; the former v12 forecast is not the comparator.
13. **How should the 13 origins be divided for development/confirmation?** Freeze before W11.
14. **Which grain/horizon targets matter to the demo stakeholders?** Freeze in decision #77.
15. **May the Demand Forecast wording change while layout remains fixed?** Only after a reviewed
    parity-contract amendment.
16. **Should quality policy v2 ship without a better model?** Recommend no; evaluate separately
    but activate only through a new accepted version/UI contract.
17. **Are Forecast Health rows exact h1/h4/h8/h13 or cumulative 1..N?** Recommend exact
    checkpoints, with the operational horizon selector unable to hide any of the four rows.

---

## 14 · Approval block

### Approval requested now

- complete W0 Phase 3 semantic repairs and the clean evidence rebaseline;
- review the ordering and architecture;
- review proposed decisions #65–#80;
- review work-package scope and acceptance gates;
- correct this plan.

### Not approved by plan creation

- implementation of W1–W17;
- changes to tracked contracts/tasks/specs;
- new retailer adapters;
- new source/publication pins;
- datagen changes;
- model experiments;
- policy/UI changes;
- materialization or activation of any run that does not pass the repaired verifier;
- commits or pushes.

### Final definition of done

Post–Phase 3 hardening is complete only when:

1. Phase 3 is formally closed;
2. a mapped-files retailer and a genuinely different custom adapter both reach neutral staging
   and unchanged canonical transforms;
3. temporal/readiness/statistical outcomes are explicit and fail-closed;
4. retailer/tenant publication selection replaces the one-demo-pin deployment assumption;
5. Track A round-trip and portability gates pass;
6. forecast candidates are compared against the immutable accepted C0 version using frozen
   evidence once C0 exists;
7. all unchanged A1–A5 and new improvement gates pass, or an honest no-go is published;
8. any policy/presentation change is versioned, reviewed and backed by live data;
9. activation is separate, auditable and reversible;
10. no repository CI, threshold tuning, fabricated data or downstream retailer branch was added.
