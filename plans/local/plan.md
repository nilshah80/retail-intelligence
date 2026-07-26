# Retail Intelligence — Local End-to-End Development Plan

_Cygnet.One · New product PoC for the `ai_retail_intelligence_dashboard_multicurrency_v6`
dashboard · Companion file: `plans/local/tasks.md` · Full spec: `docs/demand_forecast_poc_spec.md`_

## 1 · Goal — what "done locally" means

Take `retail-intelligence` from an empty scaffold to **one end-to-end Retail AI PoC running
locally on synthetic data**, populating the dashboard's screens through a real API. "Done
locally" means:

- An isolated, extract-ready **data generator** (`datagen/`) creates one deterministic Indian
  multi-category retail truth and publishes both exact canonical fixtures and source-shaped
  CSV/Parquet/JSONL test dialects (including a direct-identifier-free,
  protected-field-minimized Shopify-shaped example).
- The **Python ML pipeline** (`ml/`) lands and validates raw snapshots, maps and semantically
  transforms each source into canonical `retail_v2`, runs the canonical quality/PIT gate, builds
  features, and produces **demand forecasts (P50/P90 + drivers)**,
  **inventory/replenishment** decisions (safety stock, transfers, allocation), and
  **pricing/promotion** recommendations under guardrails — all as fingerprinted artifacts.
- The **Go API** (`api/`) serves those artifacts, owns **workflow/HITL** (approve / override /
  audit), re-validates guardrails at serve time, and enforces staleness (409/503) and RBAC.
- The **UI** implements the dashboard screens against the real API.
- Everything is **shadow-only** (no price/PO is ever executed) and **fail-closed**.

The prior **M5 PoC (`../retail_ai`)** is the reference implementation: its Python `data/`,
`features/`, `models/`, `engines/` are copied and adapted into `ml/`; its `api/` design is
re-implemented in Go.

## 2 · Guiding principles (carried over from the M5 PoC)

- **A human always decides.** The AI drafts orders/prices and explains them; a person approves
  every action. Nothing is auto-sent. The approve/override round-trip into `audit_log` is the
  governance proof.
- **Engines compute the numbers, not the LLM.** Every quantity/price/margin comes from
  deterministic, unit-tested engine code (Python) or the Go re-validation; the copilot only
  reads and explains.
- **Point-in-time everywhere.** Every temporal fact carries `known_as_of`; features/labels respect the
  embargo; a late fact never rewrites history.
- **Fail closed.** Missing required fields, stale lineage, mixed provenance, or unverifiable cost
  stop the pipeline / return 409/503 — never a silent guess.
- **One canonical contract.** `contracts/` defines canonical `retail_v2`, the source-profile/
  transform extension points and shared guardrails. Raw source schemas may differ; only the
  transformed canonical output is consumed downstream. Fingerprints must be byte-identical across
  Python and Go.
- **`datagen/` is isolated.** It depends on `contracts/` only, so it can be extracted later.

## 3 · Phases (local)

Status markers: `[ ]` not started · `[~]` partial · `[x]` done. Task-level detail lives in
`plans/local/tasks.md`.

### Phase 1 — Synthetic data generation `[FIRST]`

**Goal:** stand up `datagen/` with one internally canonical retail truth and two publishers:
`SYNTHETIC_CANONICAL_TEST` for component tests and `SYNTHETIC_CLIENT_SHAPED_TEST` for the real
raw→transform→canonical onboarding path, plus the contracts needed by both.

**Scope:**
- **Contracts (prerequisite):** lock canonical `retail_v2` (entities, grains, columns, types,
  `known_as_of`, minor-unit money, row provenance) from spec §11; publish the source-profile
  schema, coverage/capability and composite manifests, approved-mapping/runtime-crosswalk split,
  staging + adapter/transform interfaces, data dictionary and seed guardrail YAMLs.
- **Generator config:** 4 categories (Footwear / Apparel / Electronics / Beauty), 5 stores
  (Mumbai, Noida, Bengaluru, Kolkata, Chennai) + 2–3 DCs, N SKUs/category, ~3 years daily
  history, deterministic seed.
- **Demand/inventory model:** per-SKU×store latent demand, weekly seasonality (Fourier), **Indian
  festival/monsoon/EOSS calendar bumps**, day-of-week, trend, promo lift, price elasticity,
  intermittency / new-product launch gate, **weather** and **local-event** multipliers, macro
  drift; Poisson/neg-binomial draw; a supply/ATP event loop emits inventory-constrained realized
  sales with explicit versions/exact money, demand-to-supply `sales_fulfillments`, and versioned
  post-sale adjustments without rewriting earlier knowledge.
- **Money & operational streams:** regular/promo price series; **cost ledger
  (`purchase_receipts`) with the same SKU received at different costs over time** (§10.5);
  inventory snapshots with disjoint on-order/in-transit and committed/reserved/damaged buckets,
  explicit ATP method/reconciliation, **batches + expiry**, inbound shipments; suppliers +
  `supplier_performance` (OTD, lead-time variability).
- **New feeds:** competitor product/price/availability inputs plus test-only match truth (runtime
  matches remain a PoC output); weather actual + forecast (Indian cities); local events; macro
  index; FX rates; promotions + customer segments.
- **Publication dialects:** exact canonical Parquet; a full-coverage generic retailer-shaped
  snapshot; a direct-identifier-free, protected-field-minimized Shopify-shaped snapshot for the
  domains Shopify can supply; and synthetic PIM/ERP/WMS/external companion feeds for a complete
  Shopify-led test. Real Shopify data is never used locally.
- **Engineering discipline:** deterministic seeds, immutable publication (`run_id` from inputs),
  boundary validation, control totals, and `known_as_of` on every temporal fact.

**Deliverables:** `datagen/` CLI, internal canonical truth, canonical and client-shaped
publications (CSV/Parquet/JSONL as declared), source coverage/capability + composite manifests,
profiles, data dictionary, and tests for determinism, boundary, `known_as_of`, schema
conformance, protected-field exclusion and webhook-authentication failure.

**Exit criteria:** every `[in]` entity in §11 exists in the internal truth; canonical mode emits
correct columns/`known_as_of`; client-shaped snapshots have valid manifests/profiles; a re-run is
byte-identical; the cost ledger shows one SKU at multiple costs; Phase 2 can land the generic,
Shopify and companion snapshots.

### Phase 2 — Ingest & data quality (`ml/data`)

**Goal:** prove that differently shaped raw sources become the same clean canonical `retail_v2`
without source logic leaking downstream.

**Scope:** implement immutable raw landing; Gate A source/manifest/coverage/mapping validation; adapt M5
`mapped_files` as the profile-driven default normalizer and add a thin versioned adapter interface
for source-specific semantics; emit standardized staging; apply source-neutral domain transforms
(joins, filters, refunds/cancellations, money/unit/timezone conversion, aggregation, inventory
snapshots) into canonical `retail_v2`; attach PIT/provenance/lineage; run Gate B canonical
validation (coverage/capability status, exact sales-money and fulfillment reconciliation,
adjustment equations, monotonic version keys, inventory/ATP invariants, negative units,
non-positive price, date gaps, `known_as_of`, recomputed promo rule, cost-ledger completeness,
referential integrity and control totals); atomically publish curated Parquet + DuckDB and
reason-coded quarantine.

**Exit criteria:** Gate A passes for every snapshot; the pure Shopify fixture receives only
`validated_partial` after reconstructing its manifest-declared supported slice; the generic and
Shopify-plus-companion datasets reconstruct the full truth/control totals and receive full Gate-B
`pass` before curated promotion. References hold, curated full/capability-complete tables
materialize, and no model/engine code differs by source.

### Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)

**Goal:** weekly point-in-time features + the forecaster and its evaluation.

**Scope:** weekly PIT feature build (lags/rolling/seasonality/price/promo/calendar **+ new
competitor/weather/event/macro drivers**); LightGBM horizon-quantile **P50/P90, horizons to
26 weeks**, Croston routing for intermittent; baselines + **Forecast Value Add** (WAPE, bias,
`accuracy = 100·(1−WAPE)`); rolling-origin backtest + acceptance gates; `forecast_versions`,
SHAP-grouped `forecast_drivers` (incl. competitor + weather groups), per-series confidence.

**Exit criteria:** forecast beats seasonal-naive ≥25%; P90 coverage ∈ [0.85, 0.95]; monotonic
P50≤P90; artifacts fingerprinted. **Unlocks the Demand Forecast screen data.**

### Phase 4 — Inventory & replenishment (`ml/engines`)

**Goal:** turn forecasts into stock decisions.

**Scope:** reorder / safety-stock (quantile-spread × service level); **service-level policy
calibration on 5% + validation on 95%** (A/B/C); multi-echelon `locations`, reconciled ATP,
inbound/in-transit shipment state, **batches/expiry, ageing**; transfer optimizer; constrained
allocation; inventory-replay simulator + acceptance; demand-at-risk.

**Exit criteria:** replay passes acceptance (fewer stock-outs / less inventory / ≥ fill);
policy holdout passes. **Unlocks Inventory + Replenishment/Planner screens.**

### Phase 5 — Pricing & promotions (`ml/models`, `ml/engines`)

**Goal:** elasticity-driven pricing + promotion planning, cost-aware.

**Scope:** price-response elasticity (Poisson GLM + empirical-Bayes) + acceptance gates; price
recommendations under guardrails (margin floor, max change, dominance); price simulation;
scenario planning; **competitor monitor** (product-matching + competitor-aware response);
**promotion planner** (uplift, cannibalisation, bundle, segment models); **cost-over-time
margin** (WAC default / FIFO for batch-tracked; cost-as-of).

**Exit criteria:** elasticity gates enforced; every recommendation guardrail-valid; margins use
cost-as-of. **Unlocks Pricing, Competitor Monitor, Promotion Planner screens.**

### Phase 6 — Go API, workflow & governance (`api/`, `db/`)

**Goal:** serve artifacts and own the decision/governance layer in Go.

**Scope:** Alembic migrations (`db/`, reuse + new tables); Go API serving artifacts; workflow /
HITL (approvals, planner overrides, idempotency, audit); **serve-time guardrail re-validation**;
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

Phases are largely sequential (each unlocks the next's inputs), but **`contracts/` is authored in
Phase 1 and frozen early** because every later phase and both repos depend on it. `db/` (Phase 6)
can start in parallel once the workflow tables are known. UI (Phase 7) can start against stub API
responses once the API contract (OpenAPI) is fixed.

## 5 · Out of scope / deferred (local)

- Real client data (this PoC uses generated data only; client data is a governed, controlled-
  environment activity — never a laptop).
- Production auth hardening, HA, and scale.
- AWS deployment — see `plans/aws/plan.md`.
