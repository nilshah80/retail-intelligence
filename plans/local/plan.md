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
- The **Go API** (`api/`) serves those artifacts, owns **workflow/HITL** (approve / override /
  audit), re-validates guardrails at serve time, and enforces staleness (409/503) and RBAC.
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

## 3 · Phases (local)

Status markers: `[ ]` not started · `[~]` partial · `[x]` done. Task-level detail lives in
`plans/local/tasks.md`.

### Phase 1 — Config Builder and synthetic source generation `[FIRST]`

**Goal:** bring compatible code from `../retail-synthetic-data-generator` into `datagen/`, replace
its flat US-only scenario with a Config-Builder-authored multi-market source specification, and
publish source-shaped Shopify, Business Central and companion datasets without importing
`retail_v2`.

**Scope:**
- **Config Builder:** sole authoring surface; import/export equivalent YAML and JSON; no hidden
  preset-only values; browser validation and resolved preview.
- **Topology:** one retailer with explicit markets, stores, online channels, warehouses/DCs and
  store-to-warehouse service relationships. The demo config includes Mumbai plus New York and
  proves both single- and multi-warehouse cases.
- **Source instances:** explicit Shopify shop and Business Central company instances mapped to
  their markets/stores/warehouses and native currency/tax/legal context.
- **Locale packs:** IN and US first to prove inclusive-vs-exclusive tax behavior, then GB and DE.
  Each pack controls native currency/minor unit, price bands/endings, category tax, fiscal/timezone
  defaults, addresses/postcodes, holidays/sale seasons and climate. Reviewed date tables cover
  lunar holidays.
- **Demand model:** per-SKU×store latent demand, weekly and locale seasonality, holidays, trend,
  configured promotion lift, price elasticity, intermittency/new-product gates, weather,
  local-event, competitor and macro effects; enabled signals must actually influence demand.
- **Context and pricing-evidence presets:** companion signals and promotion targets carry
  generator-owned market plus structured region/store/channel scope. The primary Mumbai+New York
  scenario uses response-rich assortment/price dynamics; a separate sparse preset demonstrates
  downstream evidence blocking without embedding ML thresholds in datagen.
- **Source projections:** Shopify-shaped, Business Central-shaped and external/companion source
  datasets generated from the same causal run. Source-native currencies, tax behavior and
  timestamps are preserved.
- **Publication:** source-run manifest with resolved config/run identity, topology, outputs,
  row/control totals and hashes; hidden generator-vocabulary truth for evaluation; deterministic
  replay and honest declarations of the formats actually written.
- **Deferred fidelity:** exhaustive split/status/return/refund/HMAC conformance fixtures, every
  inventory state, and complete receipt/inbound/batch/supplier/competitor-match histories are
  config-driven screen-completeness extensions, not blockers for the first forecast/revenue-
  pricing round-trip. Margin-aware pricing remains unavailable until an enabled receipt/cost
  projection passes the cost capability gate.

**Deliverables:** Config Builder HTML, generator-owned schema and locale packs, CLI, Shopify/BC/
companion publishers, source-run manifest, hidden truth and deterministic tests.

**Exit criteria:** the page can create and re-open a multi-market scenario; YAML and JSON resolve
identically; IN/US/GB/DE locale tests pass; Mumbai and New York stores produce different correct
currency/tax/holiday/signal scope; response-rich and sparse-evidence presets are reproducible; the
same config/seed reproduces the same logical source run; Phase 2 can land every declared source
output. No generated file uses `retail_v2` vocabulary by design.

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
promotion scope; observation/reference facts
use natural-key/effective-time/`known_as_of` ordering while cumulative/correctable facts use
explicit versions. Sales/sell prices use location operating currency, supplier terms have typed
scope and exact origin semantics, and reporting FX uses the shared direction/precision/rounding
contract.

**Exit criteria:** Gate A passes every generated source snapshot; Shopify/BC/companion adapters
reconstruct their declared canonical slices and reconciliations; missing source metadata is
derived with visible provenance or quarantined; only capability-complete composites receive full
Gate-B `pass` and curated publication; golden controls match through the ingestion-owned oracle.
No model/engine code differs by source.

### Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)

**Goal:** weekly point-in-time features + the forecaster and its evaluation.

**Scope:** weekly PIT feature build (lags/rolling/seasonality, market-local price/promo/calendar
**+ new competitor/weather/event/macro drivers**) joined through market-qualified scope; use
dimensionless/local-normalized prices
for any cross-market forecast pool; LightGBM horizon-quantile **P50/P90, horizons to 26 weeks**,
Croston routing for intermittent; baselines + **Forecast Value Add** (WAPE, bias,
`accuracy = 100·(1−WAPE)`); rolling-origin backtest + global and per-market acceptance gates/
calibration; `forecast_versions`, SHAP-grouped `forecast_drivers` (incl. competitor + weather
groups), per-series confidence.

**Exit criteria:** forecast beats seasonal-naive ≥25%; P90 coverage ∈ [0.85, 0.95]; monotonic
P50≤P90 globally and for every supported market; artifacts include market/config fingerprints.
**Unlocks the Demand Forecast screen data.**

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
policy holdout passes. **Unlocks Inventory + Replenishment/Planner screens.**

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
`insufficient_evidence` state. **Unlocks Pricing, Competitor Monitor, Promotion Planner screens.**

### Phase 6 — Go API, workflow & governance (`api/`, `db/`)

**Goal:** serve artifacts and own the decision/governance layer in Go.

**Scope:** Alembic migrations (`db/`, reuse + new tables); Go API serving artifacts; workflow /
HITL (approvals, planner overrides, idempotency, audit); market/currency-scoped pricing
activations; **serve-time guardrail re-validation** over the same resolved market policy;
staleness 409/503; RBAC/auth; **fingerprint parity** (Python↔Go golden vectors); lineage/audit.

**Exit criteria:** an approve/override writes an audit row; stale artifact → 409, missing → 503;
Go and Python produce identical fingerprints on shared vectors. **Unlocks Governance + approvals.**

### Phase 7 — UI (`ui/`)

**Goal:** the dashboard screens against the real API.

**Scope:** implement the screens from the mockup; multi-currency display (FX); the interactive
what-ifs (scenario/simulation) wired to the API; rich capture forms where the mockup only stubs
them (§8.3 note).

**Exit criteria:** each screen renders live API data; no mock data paths.

### Phase 8 — Analytics, admin & hardening

**Goal:** the remaining screens + production-readiness.

**Scope:** model registry/drift, alerts + data-freshness, data-source management, reports;
adoption metrics / performance insights (AI-vs-control); disclosure guardrails; end-to-end
acceptance run + at least two synthetic client-shaped dialects proving onboarding is
configuration-only where existing transforms cover the semantics, or otherwise needs only a
bounded versioned adapter with no downstream changes.

**Exit criteria:** a full ingest→serve run passes fail-closed gates end to end; all screens live.

## 4 · Sequencing

Phases are largely sequential. The datagen source contract and the downstream `retail_v2`
contract evolve independently and meet only at the Phase-2 adapter boundary. `contracts/` is
frozen before Gate-B implementation, but it is not a datagen dependency. `db/` (Phase 6) can
start once workflow tables are known. UI (Phase 7) can start against stub API responses once the
API contract is fixed. Phase-1 `datagen/` scaffolding may start under its already locked isolated
boundary; lock Python environment topology (decision #38) before scaffolding the `ingestion/`/
`ml/` package boundary. Resolve fingerprint canonicalization (decision #16) during the Phase-2
contract freeze before Phase 3 publishes artifacts. Market/currency guardrail resolution is
already fixed by decision #39.

## 5 · Out of scope / deferred (local)

- Real client data (this PoC uses generated data only; client data is a governed, controlled-
  environment activity — never a laptop).
- Production auth hardening, HA, and scale.
- AWS deployment — see `plans/aws/plan.md`.
