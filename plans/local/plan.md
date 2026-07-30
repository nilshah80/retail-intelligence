# Retail Intelligence — Local End-to-End Development Plan

_Cygnet.One · New product PoC for the `ai_retail_intelligence_dashboard_multicurrency_v6`
dashboard · Companion file: `plans/local/tasks.md` · Full spec: `docs/demand_forecast_poc_spec.md`_

## 1 · Goal — what "done locally" means

Take `retail-intelligence` from an empty scaffold to **one end-to-end Retail AI PoC running
locally on synthetic data**, populating the dashboard's screens through a real API. "Done
locally" means:

- An isolated, extract-ready **data generator** (`datagen/`) uses an HTML Config Builder to define
  a deterministic multi-market retailer and publishes Shopify-shaped, Business Central-shaped and
  external/companion sources, a source-run manifest and hidden causal truth. It has no knowledge
  of `retail_v2`.
- The **Python ingestion pipeline** (`ingestion/`) lands and validates raw snapshots, maps and
  semantically transforms each source into canonical `retail_v2`, runs the canonical quality/PIT
  gate, and publishes curated Parquet/DuckDB.
- The **Python ML pipeline** (`ml/`) consumes only capability-complete curated data, builds
  features, and produces **demand forecasts (P50/P90 + drivers)**,
  **inventory/replenishment** decisions (safety stock, transfers, allocation), and
  **pricing/promotion** recommendations under guardrails — all as fingerprinted artifacts.
- The **Aarv-based Go API** (`api/`) serves those artifacts, owns **workflow/HITL** (approve /
  override / audit), re-validates guardrails at serve time, and enforces staleness (409/503) and
  RBAC. [Aarv](https://github.com/nilshah80/aarv) is the HTTP transport; application logic stays
  in framework-neutral internal packages.
- The **UI** implements the dashboard screens against the real API.
- Everything is **shadow-only** (no price/PO is ever executed) and **fail-closed**.

The prior **M5 PoC (`../retail_ai`)** is the reference implementation: its Python `data/`
patterns are adapted into `ingestion/`; `features/`, `models/` and `engines/` are adapted into
`ml/`; its `api/` design is re-implemented in Go.

## 2 · Guiding principles (carried over from the M5 PoC)

- **A human always decides.** The AI drafts orders/prices and explains them; a person approves
  every action. Nothing is auto-sent. The approve/override round-trip into `audit_log` is the
  governance proof.
- **Engines compute the numbers, not the LLM.** Every quantity/price/margin comes from
  deterministic, unit-tested engine code (Python) or the Go re-validation; the copilot only
  reads and explains.
- **Point-in-time after ingestion.** Every canonical temporal fact carries `known_as_of`;
  ingestion derives it from defensible source/observation/landing evidence when a source does not
  supply it, and records provenance. Features/labels respect the embargo; a late fact never
  rewrites history.
- **Fail closed.** Missing required fields, stale lineage, mixed provenance, or unverifiable cost
  stop the pipeline / return 409/503 — never a silent guess.
- **One downstream canonical contract.** `contracts/` defines canonical `retail_v2`, the
  ingestion profile/transform extension points and shared guardrails. Raw source schemas may
  differ; only transformed canonical output is consumed downstream. Fingerprints must be
  byte-identical across Python and Go.
- **`datagen/` is independent.** It owns its own source-data specification and imports no
  downstream package, so it can be extracted later without taking `retail_v2`.
- **Market-local money, reporting FX.** Locations carry market/currency/timezone; price, cost,
  margin and policy enforcement stay within one local currency. Cross-market monetary totals are
  separately derived under the reporting-FX policy and are never causal model inputs.
- **Demo by vertical slice.** The runtime UI and a thin read-only Go API start when the first
  versioned screen contract is frozen. Test fixtures may precede live artifacts in automated
  tests, but an incomplete/sample screen is not demoable. Each capability phase ports its
  reviewed original-HTML page to accepted live artifacts; Phases 6–7 add governed interactions
  and complete integration rather than starting API/UI work for the first time.
- **The agreed HTML is the UI contract, not a moodboard.**
  `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` fixes the visible application
  shell, navigation hierarchy/order, page titles/subtitles, top filters, currency strip, page
  composition, labels, table columns, footer KPIs, footer copy, colors, spacing and interaction
  locations. A phase may replace sample values with correctly defined live API values, but may
  not redesign, rename, remove or add visible product concepts without explicit review and
  approval. Engineering vocabulary such as phase numbers, Gate A/B, fingerprints and pipeline
  internals belongs in diagnostics/API evidence, not in the business UI unless the reference
  HTML explicitly presents it.
- **Every visible value has a reviewed data definition.** Before a screen is implemented, create
  a parity/data map from each HTML element to its live API field or governed calculation,
  including grain, filters, units/currency, time window, formatting and unavailable behavior.
  No sample number may be presented as live, and no convenient backend count may be substituted
  for a differently named business metric. Screenshot/DOM parity at agreed desktop and
  responsive viewports plus a data-value test is a demo acceptance gate.
- **Windows/macOS/Linux are equal local targets.** This applies to the Config Builder, contracts
  and code generation, execution resolver, datagen, ingestion, ML, database tooling, Aarv-based
  Go API, UI and developer/deployment commands. Python uses `pathlib`, `tempfile` and
  argument-list subprocesses; Go uses `filepath` and portable locking/process/shutdown APIs; UI
  workflows use cross-platform npm scripts. Make/Bash are optional. Logical manifest paths use
  `/`, physical paths are native, fingerprinted text uses UTF-8/LF, and open handles are closed
  before same-volume atomic promotion. Permission lanes preserve their semantics through native
  OS capabilities. Local capability work must remain portable; the three-OS blocking matrix is a
  manually collected Phase-7/8 release-hardening gate and never becomes repository CI.

## 3 · Phases (local)

Status markers: `[ ]` not started · `[~]` partial · `[x]` done. Task-level detail lives in
`plans/local/tasks.md`.

### Phase 1 — Config Builder and synthetic source generation `[~]`

**Goal:** bring compatible code from `../retail-synthetic-data-generator` into `datagen/`, replace
its flat US-only scenario with a Config-Builder-authored multi-market source specification, and
publish source-shaped Shopify, Business Central and companion datasets without importing
`retail_v2`.

**Scope:**
- **Config Builder:** sole authoring surface; conventional YAML is the default import/export and
  execution format, JSON remains supported and equivalent; no hidden preset-only values; browser
  validation and resolved preview.
- **Topology:** one retailer with explicit markets, stores, online channels, warehouses/DCs and
  store-to-warehouse service relationships. The demo config includes Mumbai plus New York and
  proves both single- and multi-warehouse cases.
- **Source instances:** explicit Shopify shop and Business Central company instances mapped to
  their markets/stores/warehouses and native currency/tax/legal context.
- **Locale packs:** IN and US first to prove inclusive-vs-exclusive tax behavior, then GB and DE.
  Each pack controls native currency/minor unit, price bands/endings, category tax, fiscal/timezone
  defaults, addresses/postcodes, holidays/sale seasons and climate. Reviewed date tables cover
  lunar holidays.
- **Rich catalog packs:** adapt the reusable product/variant behavior and partial option-matrix
  generation from the reference generator, but replace generic names/SKUs with versioned
  IN/US/GB/DE real-brand reference packs. The normalized default hierarchy contains 10
  departments and 41 categories, including Groceries. The builder controls generated/hybrid/explicit modes,
  exact sellable-SKU targets, opening-incumbent share, variants per product, category
  economics/behavior, lifecycle/replacement controls and explicit product definitions. Flagship
  profiles add spike/decay, anticipation, substitution, overlapping predecessor runout,
  markdown, clearance and fire sale; Shopify
  and BC receive their own product/item and variant/lifecycle projections.
- **Long history and disruption:** support at least the checked-in 2005–2024 run, with incumbent
  assortment at the opening boundary, later product/SKU introductions, monthly physical
  partitions, compound growth/inflation and config-owned H1N1/COVID/neutral-outbreak phases.
  Pandemic demand/channel semantics adapt `../retail_ai`; supplier/cost/inventory shock mechanics
  adapt the original source generator.
- **Demand model:** per-SKU×store latent demand, weekly and locale seasonality, holidays, trend,
  configured promotion lift, price elasticity, intermittency/new-product gates, weather,
  local-event, competitor and macro effects; `startingDailyOrders` controls real order headers
  through config-owned average basket lines; enabled signals must actually influence demand.
- **Customer population:** per-market opening registered customers, annual acquisition,
  churn/reactivation, guest checkout, opening history and a hard customer/day order cap are all
  authored in the Config Builder. Shopify guest orders remain source-native; BC uses an explicit
  market walk-in account. Direct identifiers remain blank by contract.
- **Context and pricing-evidence presets:** companion signals and promotion targets carry
  generator-owned market plus structured region/store/channel scope. The primary Mumbai+New York
  scenario uses response-rich assortment/price dynamics; a separate sparse preset demonstrates
  downstream evidence blocking without embedding ML thresholds in datagen.
- **Source projections:** Shopify-shaped, Business Central-shaped and external/companion source
  datasets generated from the same causal run. Source-native currencies, tax behavior and
  timestamps are preserved.
- **Publication:** one selected authoritative source CSV/Parquet format, one all-source
  `source-run.duckdb` browsing mirror,
  a generated source-field dictionary, and a manifest with resolved config/run identity,
  topology, capabilities, row/control totals and hashes; hidden generator-vocabulary truth for
  evaluation; deterministic replay. Long-horizon projections use bounded private row spools,
  trailing-window causal state and concurrent independent partition publication. Worker count,
  spool size and DuckDB memory are runtime-only controls and cannot alter the scenario/run ID.
- **Screen-completeness fidelity:** config-driven split/status/return/refund/HMAC fixtures, the
  named inventory-state matrix, and receipt/inbound/batch/supplier/competitor-match/warehouse/
  transfer/allocation evidence are included in source spec v11. Margin-aware pricing remains
  unavailable downstream until the enabled receipt/cost projection passes the ingestion cost
  capability gate.
- **Operational realism:** adaptive SKU/location replenishment closes the inventory loop using
  availability-normalized observed sales, pending supply, lead times, fill rates, MOQ and pack
  size without reading hidden demand truth. Orders reserve causal
  committed stock until fulfillment; receipt inspection creates causal quality-control/damaged
  states and later waste disposition. Every fulfillment-timed sale, receipt, transfer, waste and
  adjustment posts to a complete BC-shaped ledger that reconciles to current inventory. Explicit
  operation feature switches can remove an optional evidence domain cleanly.

**Deliverables:** Config Builder HTML, generator-owned schema and locale packs, CLI, Shopify/BC/
companion publishers, source-run manifest, authoritative CSV/Parquet selection, one DuckDB
mirror, generated source-field dictionary, hidden truth and deterministic tests.

**Exit criteria:** the page can create and re-open a multi-market scenario; YAML and JSON resolve
identically; IN/US/GB/DE locale tests pass; Mumbai and New York stores produce different correct
currency/tax/holiday/signal scope; response-rich and sparse-evidence presets are reproducible; the
same config/seed reproduces the same logical source run; Phase 2 can land every declared source
output. No generated file uses `retail_v2` vocabulary by design. **Demo checkpoint 1:** create,
re-open and generate the Mumbai + New York source run from the Config Builder. Code/test
acceptance is complete for v0.12.0/v11. The earlier v0.11.0 ten-year
`run-b8c4cceba05eb61a` was generated under the ultra-performance profile and measured at
1h26m50.27s and 17.56-GiB peak process RSS, but it predates the v0.12.0 source/realism
corrections and is benchmark evidence rather than the Phase-2 pin. The v0.11.0 execution-only extension adds a separate
Config-Builder execution YAML, one shared neutral resolver, deterministic per-market processes,
independent partition/DuckDB controls and manifest telemetry. Safe/performance/ultra-performance parity is proven
on the full 90-day showcase; full ten-year ultra evidence is recorded, while equivalent safe and
performance full runs remain optional comparison evidence. Phase 1 code is complete; a fresh
v0.12.0/v11 ten-year acceptance run must be pinned before Phase 2 landing begins.

Phase 3 acceptance later exposed a structural limit in that otherwise accepted pin: all
materialized zero-demand labels are landing-backfilled, so no historical forecast origin can
train on them. Generator v0.13.0/source contract v12 is therefore a controlled rebaseline
candidate. It adds native effective-dated `storeAssortment.observedAt` evidence and expands the
ten-year demo to 1,440 sellable SKUs so the frozen slow-mover sufficiency rule can be evaluated
without threshold tuning. The v12 run is now generated, landed and published with Gate A/Gate B
passes, exact reconciliation and all zero-demand/assortment rows `native_observed`; it is the
frozen ML input pin. Forecast activation remains separately gated by Phase 3 acceptance.

### Phase 2 — Ingestion, transformation & data quality (`ingestion/`)

**Goal:** prove that differently shaped raw sources become the same clean canonical `retail_v2`
without source logic leaking downstream.

**Scope:** implement immutable raw landing; construct landing/source manifests when upstream does
not provide them; run Gate A; adapt M5 `mapped_files` as the profile-driven default normalizer and
add bounded Shopify/BC adapters; emit standardized staging; apply source-neutral domain transforms
(joins, filters, refunds/cancellations, local-currency minor units, tax/unit/timezone conversion,
aggregation, inventory snapshots) into canonical `retail_v2`; derive and record the declared
explicit-version or observation identity plus `known_as_of` from defensible native or landing
evidence; attach provenance/lineage; run Gate B;
atomically publish curated Parquet + DuckDB and reason-coded quarantine. Canonical locations and
the derived stores view retain `market_id`, operating currency and timezone. Ingestion tests own
the versioned generator-truth→canonical expected-control oracle used by golden round trips.
Canonical contextual feeds preserve market-qualified `geo_scope_*` or structured multi-axis
promotion scope; public pandemic timeline/signal evidence maps to an explicit `[in]`
market-disruption observation contract rather than being discarded or confused with hidden
truth; observation/reference facts
use natural-key/effective-time/`known_as_of` ordering while cumulative/correctable facts use
explicit versions. Sales/sell prices use location operating currency, supplier terms have typed
scope and exact origin semantics, and reporting FX uses the shared direction/precision/rounding
contract. Ingestion installs the neutral `execution/` Python package and maps its ingestion
namespace into bounded scan/transform/write workers, DuckDB threads, memory/spill limits and
partition writers. The resolved profile is recorded in the ingest manifest but excluded from
landing/canonical fingerprints; safe and ultra-performance profiles must accept/quarantine identical
rows and controls. Freeze the first screen contract—common OpenAPI envelopes plus Data Management/quality
read models—and scaffold the runtime dashboard with the selected UI framework and its initial
read-only Go API slice.

**Exit criteria:** Gate A passes every generated source snapshot; Shopify/BC/companion adapters
reconstruct their declared canonical slices and reconciliations; missing source metadata is
derived with visible provenance or quarantined; only capability-complete composites receive full
Gate-B `pass` and curated publication; golden controls match through the ingestion-owned oracle.
No model/engine code differs by source. Phase 2 has three incremental UI checkpoints:
**2A** after landing/Gate A (live source inventory, controls and Gate A), **2B** after staging
(live coverage, reconciliation and quarantine) and **2C** after Gate B/publication (live
capability mask and curated status). UI work does not wait for Phase 3.

**Implemented status:** the accepted ten-year source pin runs through all governed boundaries. The
retained publication now post-dates the v1.2 corrections for fulfilled sales, financial refunds,
exact integer money, timezone-stable dates, ATP and current inbound-status splitting. Phase 3
consumes that publication only through the committed `contracts/ml/expected-pin.json` and the
fail-closed ML input-bundle verifier; a later republish requires an explicit reviewed pin change.
The stable source-profile filename is `retail_datagen.yaml`; `profileVersion` and
`sourceSchemaVersion` remain inside the document. Manifest-less retailer drops can be inventoried
from explicit profile globs, physical CSV/Parquet/JSONL/JSON parsing is shared, and source
semantics remain isolated in registered adapters. A composite missing Shopify, Business Central
or companion coverage terminates as `validated_partial` after Gate A and cannot publish or reach
ML. The Aarv API reads only accepted evidence. The first React Data Management implementation
proved API connectivity but is **not an accepted UI deliverable** because it diverges from the
agreed HTML shell, page structure and business data points. Phase 2 UI acceptance remains open
until the parity-recovery tasks in `plans/local/tasks.md` pass; this does not invalidate the
accepted ingestion publication.

### Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)

**Goal:** weekly point-in-time features + the forecaster and its evaluation.

**Scope:** weekly PIT feature build (lags/rolling/seasonality, market-local price/promo/calendar
**+ new competitor/weather/event/market-disruption/macro drivers**) joined through
market-qualified scope; use
dimensionless/local-normalized prices
for any cross-market forecast pool; LightGBM horizon-quantile **P50/P90, horizons to 26 weeks**,
Croston routing for intermittent; baselines + **Forecast Value Add** (WAPE, bias,
`accuracy = 100·(1−WAPE)`); rolling-origin backtest + global and per-market acceptance gates/
calibration; `forecast_versions`, SHAP-grouped `forecast_drivers` (incl. competitor + weather
groups), per-series confidence.
MLflow tracking begins with this first training/backtest slice. The first accepted run retains its
file-backed telemetry identity; decision #63 brings a shared Compose MLflow server backed by
PostgreSQL into Phase 3 for subsequent runs without making telemetry the publication authority.

**Exit criteria:** forecast beats seasonal-naive ≥25%; P90 coverage ∈ [0.85, 0.95]; monotonic
P50≤P90 globally and for every supported market; artifacts include market/config fingerprints.
The read-only API and Demand Forecast vertical slice are delivered with the model.
**Demo checkpoint 3:** the screen renders live Mumbai + New York P50/P90, accuracy, confidence
and drivers. The accepted v12 forecast, PostgreSQL read model and React vertical slice now meet
these code/data criteria locally. Strict phase sign-off remains pending only on manual
Windows/Linux portability evidence and explicit user visual approval of the running UI.

### Phase 4 — Inventory & replenishment (`ml/engines`)

**Goal:** turn forecasts into stock decisions.

**Scope:** reorder / safety-stock (quantile-spread × service level); **service-level policy
calibration on 5% + validation on 95%** (A/B/C); multi-echelon `locations`, reconciled ATP,
inbound/in-transit shipment state, **batches/expiry, ageing**; transfer optimizer; constrained
allocation; inventory-replay simulator + acceptance; demand-at-risk. Quantity decisions remain
local-unit math; ABC/valuation is market-local or uses an approved as-of reporting conversion,
and supply terms resolve by destination/location lane plus `sku > dept > category` merchandise
precedence rather than one department term alone.

**Exit criteria:** replay passes acceptance (fewer stock-outs / less inventory / ≥ fill);
policy holdout passes. The matching read-only API/UI slice is delivered in the phase.
**Demo checkpoint 4:** Inventory + Replenishment/Planner screens render live market/location
outputs.

### Phase 5 — Pricing & promotions (`ml/models`, `ml/engines`)

**Goal:** market-scoped elasticity-driven pricing + promotion planning, with cost-aware margin
enabled only when its canonical cost capability is proven.

**Scope:** price-response elasticity (Poisson GLM + empirical-Bayes) + per-market acceptance
gates; resolve pricing/response policy by `market_id + currency_code`; build price tiers and
shrinkage pools within market; revenue-objective price recommendations first under max-change,
dominance and local grid/ending guardrails; enable margin floor/objective only after cost-as-of
passes; price simulation; scenario planning; **competitor monitor** (product-matching +
competitor-aware response);
**promotion planner** (uplift, cannibalisation, bundle, segment models); **cost-over-time
margin** (WAC default / FIFO for batch-tracked; cost-as-of). Promotion applicability preserves
AND/OR scope-row semantics and merchandise overlap resolves `sku > dept > category`.

**Exit criteria:** elasticity gates enforced by market; every recommendation carries market/
currency and is guardrail-valid; revenue recommendations never imply margin, and any enabled
margin uses cost-as-of. The primary IN+US showcase produces at least 25 actually gated series per
enabled department in both markets; the sparse preset returns a reason-coded
`insufficient_evidence` state. The matching read-only API/UI slice is delivered in the phase.
**Demo checkpoint 5:** Pricing, Competitor Monitor and Promotion Planner render live
response-rich and sparse-evidence outcomes.

### Phase 6 — Aarv-based Go API, workflow & governance (`api/`, `db/`)

**Goal:** harden the incrementally delivered read-only API and add the decision/governance layer
in Go.

**Scope:** pin [Aarv](https://github.com/nilshah80/aarv) in `api/go.mod` and use it for HTTP
routing, binding, middleware and lifecycle; keep OpenAPI and application semantics outside the
framework. Add Alembic migrations (`db/`, reuse + new tables); consolidate the versioned read API
slices delivered in Phases 2–5; workflow/HITL (approvals, planner overrides, idempotency, audit);
market/currency-scoped pricing activations; **serve-time guardrail re-validation** over the same
resolved market policy; staleness 409/503; RBAC/auth; **fingerprint parity** (Python↔Go golden
vectors); lineage/audit.
PostgreSQL first enters in Phase 3 for the read-only forecast serving projection, and Docker
Compose first provides that database plus shared MLflow under decisions #62–#63. This phase extends
the same services with mutable workflow/governance state and later adds the API/UI containers;
neither service is a prerequisite for Phase-2 batch ingestion.

**Exit criteria:** an approve/override writes an audit row; stale artifact → 409, missing → 503;
Go and Python produce identical fingerprints on shared vectors. **Demo checkpoint 6:** a planner
reviews live evidence, approves/overrides a draft and sees its audit record in the UI.

### Phase 7 — UI completion and end-to-end integration (`ui/`)

**Goal:** complete the dashboard and remove remaining sample/test-only paths; UI work has already
advanced with every vertical slice since Phase 2.

**Scope:** complete remaining core screens and shared responsive/accessibility behavior; verify
multi-currency display (FX); wire interactive what-ifs (scenario/simulation) to the API; build
rich capture forms where the mockup only stubs them (§8.3 note).

**Exit criteria:** each Phase-2–6 core screen renders live API data and passes its original-HTML
parity/data gates; no core sample/mock path remains.

### Phase 8 — Analytics, admin & hardening

**Goal:** the remaining screens + production-readiness.

**Scope:** model registry/drift, alerts + data-freshness, data-source management, reports;
adoption metrics / performance insights (AI-vs-control); disclosure guardrails; end-to-end
acceptance run + at least two synthetic client-shaped dialects proving onboarding is
configuration-only where existing transforms cover the semantics, or otherwise needs only a
bounded versioned adapter with no downstream changes.

**Exit criteria:** a full ingest→serve run passes fail-closed gates end to end; all screens live.

## 4 · Sequencing

Capability phases are largely sequential, but API/UI delivery is an explicit parallel track. The
datagen source contract and downstream `retail_v2` contract evolve independently and meet only at
the Phase-2 adapter boundary. `contracts/` is frozen before Gate-B implementation, but it is not a
datagen dependency. Resolve UI framework decision #17 by the end of Phase 1. In Phase 2, freeze
the first screen contracts and start the dashboard shell plus thin read-only Go API; Phases 2–5
each deliver a demoable live vertical slice from a reviewed original-HTML parity/data matrix.
`db/` can start
once workflow tables are known. Phases 6–7 harden workflows and complete integration rather than
starting API/UI work. Phase-1 `datagen/` scaffolding may start under its already locked isolated
boundary; lock Python environment topology (decision #38) before scaffolding the `ingestion/`/
`ml/` package boundary. Resolve fingerprint canonicalization (decision #16) during the Phase-2
contract freeze before Phase 3 publishes artifacts. Market/currency guardrail resolution is
already fixed by decision #39.

## 5 · Out of scope / deferred (local)

- Real client data (this PoC uses generated data only; client data is a governed, controlled-
  environment activity — never a laptop).
- Production auth hardening, HA, and scale.
- AWS deployment — see `plans/aws/plan.md`.
