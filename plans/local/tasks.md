# Retail Intelligence — Local Tasks

_Companion to `plans/local/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_All tasks below are **local**, on generated synthetic data, shadow-only._

## Phase 1 — Config Builder and synthetic source generation `[FIRST]`

**1.1 Reuse audit and isolation**
- [ ] Copy only compatible code from `../retail-synthetic-data-generator`; record reused,
      adapted and replaced modules.
- [ ] Reuse/adapt only the portable primitives first: deterministic seed partitioning,
      source-native Shopify/Business Central ID formats and namespaces, atomic
      checkpoint/replace, checksumming/manifest logic and the Typer/logging shell. Replace
      mutable counter-based ID allocation with stable-key allocation.
- [ ] Redesign the old `RunContext`/run identity, domain checkpoint state, writer dataset
      contract, controller orchestration and CLI commands against the new generator-owned
      config and source-data specification. Replace wall-clock-derived run identity with the
      content-derived identity in §9.3 before publishing reproducible runs.
- [ ] Do not port the old `IdFactory.canonical`, `features/ml_ready`,
      `crossSystemMapping`, `analyticalExtension`, `mlReady` or fixed authoritative
      `retail.duckdb` publication contract. Hidden truth remains restricted and source-shaped
      Shopify/Business Central/companion publications are authoritative.
- [ ] Give `datagen/` its own dependency file and generator-owned scenario/source schemas.
- [ ] Resolve Python environment topology decision #38 before creating ingestion/ML package
      lockfiles; `datagen/` remains isolated regardless of that choice.
- [ ] Enforce that `datagen/` imports no `contracts/`, `ingestion/`, `ml/` or `api/` module.
- [ ] Remove canonical `retail_v2` publication and canonical terminology from generator outputs.

**1.2 Config Builder — sole authoring surface**
- [ ] Move/adapt the existing Config Builder into `datagen/`.
- [ ] Replace scalar location/warehouse counts with explicit retailer → markets → stores /
      online channels → warehouses/DC topology and `serves_locations` relationships.
- [ ] Support add/edit/remove/reorder for products/categories, markets, legal entities, stores,
      warehouses, channels, source projections, signals, promotions and scenario events.
- [ ] Configure one or more Shopify shops and Business Central companies; map each source instance
      to explicit markets/stores/warehouses and its native currency/tax/legal context.
- [ ] Expose every config field; remove preset-only hidden `countries`, `currencies`, formats,
      overwrite, execution and event fields.
- [ ] Add import of builder-generated YAML/JSON and preserve lossless round trips.
- [ ] Make YAML and JSON semantically identical; display the resolved config and schema version.
- [ ] Materialize selected locale-pack versions and all resolved locale values into the exported
      run config; record overrides explicitly.
- [ ] Validate unique IDs, date ranges, topology references, locale availability, timezone/
      currency compatibility, numeric ranges, event scope, enabled output formats and required
      projection settings.
- [ ] Add presets for India, US and a primary response-rich multi-market Mumbai + New York
      retailer, a separate `pricing-evidence-sparse` market, plus smaller GB and DE locale
      validation presets.
- [ ] Ensure one warehouse may serve many stores and one store may have an approved fulfillment
      priority list across warehouses.

**1.3 Locale packs**
- [ ] Implement data-driven `IN`, `US`, `GB` and `DE` packs; label GB as UK and DE as the PoC
      European representative in the UI.
- [ ] Define currency/symbol/minor exponent, native price bands/endings, decimal/grouping display
      metadata and Faker locale.
- [ ] Define tax basis plus category/jurisdiction rates: India GST/split rule, US state/local
      sales tax, GB VAT and DE VAT.
- [ ] Define fiscal defaults, timezone choices, region/state and postcode formats.
- [ ] Add reviewed holiday/sale-season tables, including dated lunar festivals; never calculate
      Diwali/Eid by approximation.
- [ ] Define climate profiles and regional seasonality, including Indian monsoon.
- [ ] Test that locale selection alone resolves all mandatory locale-sensitive defaults, with
      explicit documented overrides only.

**1.4 Causal simulation**
- [ ] Deterministic RNG partitioned by stable business key/time; reproducible independent of
      processing order.
- [ ] Product/variant/category/assortment generation scoped by market/store.
- [ ] Per-SKU×store latent demand with day-of-week, trend, locale holiday/seasonality, promotion,
      price elasticity, intermittency and new-product effects.
- [ ] Expose generator-owned assortment size, price-event frequency, latent-response and noise
      controls; response-rich/sparse presets must not contain downstream ML gate thresholds.
- [ ] Weather, local events, competitor movement and macro factors affect demand when enabled;
      record hidden contribution truth for later driver evaluation.
- [ ] Inventory-constrained realized sales and a usable demand-location/supply-location link in
      source-native Shopify/BC shapes.
- [ ] Generate local-currency exact source amounts with locale-correct inclusive/exclusive tax;
      do not emit canonical paise fields.

**1.5 Source projections and companion feeds**
- [ ] Shopify-shaped products/variants, locations, orders/lines, basic fulfillment, prices and
      inventory observations per configured Shopify source instance/market scope.
- [ ] Business Central-shaped item/location, sales, inventory and finance records needed for the
      first forecast/revenue-pricing round-trip, partitioned by configured company/legal entity.
- [ ] Companion holiday, weather actual/forecast, local-event, promotion, competitor, macro and
      FX datasets; every contextual row carries a generator-owned market key and structured
      market/region/store/channel target, never unqualified `ALL` or a free-form promotion scope.
- [ ] Document source FX as exact local-currency→retailer-reporting-currency decimal text; do not
      emit binary-float money/rates or assume reporting→local direction.
- [ ] Source-run manifest: generator/source-spec version, full resolved-config hash, seed/run ID,
      topology, output inventory, row/control totals and content hashes.
- [ ] Hidden generator-vocabulary truth kept outside public source projections.
- [ ] Declare and test only formats/compression actually supported by the publisher; ingestion
      remains responsible for format normalization.

**1.6 Screen-completeness extensions — non-blocking for first round-trip**
- [ ] Detailed split fulfillment and fulfillment-status histories.
- [ ] Requested-vs-processed return evidence and successful/failed refund transactions.
- [ ] Webhook envelopes plus valid/invalid HMAC fixtures and ID-parity cases.
- [ ] Full Shopify inventory-state fixture matrix.
- [ ] Business Central/ERP purchase orders, receipts/cost layers, inbound shipments, batches/
      expiry and supplier performance.
- [ ] Warehouse capacity/utilization, fill rate, dock-to-stock, blocked stock and delayed-receipt
      observations.
- [ ] Waste events, inventory ageing inputs and optional ERP↔WMS comparison observations.
- [ ] Transfer request/order/shipment histories and lane/location evidence.
- [ ] Supplier capacity confirmation, OTD, lead-time variability, MOQ/pack and budget inputs.
- [ ] Promotion-SKU/customer-segment depth, basket/order-line histories for bundle/
      cannibalisation tests and realistic competitor-product matching.
- [ ] Allocation demand requests, supply pools and source fulfillment-location evidence.
- [ ] Expand publication formats to CSV/Parquet/JSONL/compression variants only when needed.
- [ ] Verify every dashboard row in `datagen/README.md` is either backed by generated source
      evidence or explicitly marked downstream-derived/runtime.

**1.7 Phase exit**
- [ ] Same config + seed produces identical logical source outputs and manifest hashes.
- [ ] Builder exports/re-imports equivalent YAML and JSON with no hidden fields.
- [ ] Mumbai and New York in one retailer produce correct independent money, tax, timezone,
      holiday, climate, companion-signal scope and warehouse relationships, including duplicate
      region labels that remain distinct by market.
- [ ] Response-rich and sparse-evidence presets reproduce their declared assortment, price-event
      and noise characteristics without importing or asserting ML acceptance thresholds.
- [ ] IN/US/GB/DE locale-pack tests pass.
- [ ] Shopify, BC and companion outputs land successfully in Phase 2.
- [ ] The first pricing milestone is explicitly revenue-only; no margin amount/objective is
      implied unless the optional receipt/cost projection is enabled.

## Phase 2 — Ingestion, transformation & data quality (`ingestion/`)

**2.1 Contracts — freeze before Gate B**
- [ ] Author `contracts/retail_v2` from spec §11 with entities, grains, columns and types.
- [ ] Define integer minor-unit money paired with currency; exact controls reconcile per currency;
      define tenant reporting conversion as exact local/base→reporting/quote `DECIMAL(38,18)`,
      exponent-aware per-fact `ROUND_HALF_EVEN`, then aggregate; publish Python/Go vectors.
- [ ] Require canonical `locations` and derived `stores` to carry `market_id`, operating
      `currency_code` and IANA `timezone`; sales/sell prices must match operating currency and
      Shopify presentment money is audit-only.
- [ ] Require contextual feeds and normalized promotion scopes to carry `market_id`; define typed
      `geo_scope_type + geo_scope_id` keys, market-namespaced region semantics and separate
      multi-axis promotion applicability rows.
- [ ] Define explicit integer versions only for cumulative/correctable facts; define natural key
      + effective/observation time + `known_as_of` for observation/reference facts and quarantine
      divergent duplicate complete keys.
- [ ] Define supplier terms and promotion merchandise targets with
      `merch_scope_type ∈ {sku, dept, category} + merch_scope_id` and
      `sku > dept > category`; define supplier destination and exact/null-external origin.
- [ ] Separate entity ownership (`[in]` / `[poc]` / `[cfg]` / `[test]`) from row provenance.
- [ ] Publish source-profile, coverage/capability, staging, transform, mapping/crosswalk,
      reconciliation and quarantine contracts.
- [ ] Seed guardrail YAMLs (`pricing_rules`, `policy`, `price_response`) and data dictionary;
      implement decision #39 global dimensionless defaults + deterministic market/currency
      resolution, with absolute price/grid/ending rules required per market.
- [ ] Resolve decision #16 and publish the canonical-JSON fingerprint specification plus shared
      golden vectors before any Phase-3 artifact is fingerprinted.
- [ ] Publish shared resolved-policy golden vectors for byte-identical Python/Go validation.

**2.2 Landing and Gate A**
- [ ] Immutable raw landing with landing time, content hashes and idempotent replay.
- [ ] Accept datagen/retailer-provided manifests when present; otherwise build the ingestion
      manifest, coverage inventory, controls and hashes from landed data/profile.
- [ ] Gate A validates files/objects, parseability, source keys, extract window, resolved mapping
      references, input/filter/reject totals and any authenticity evidence the profile requires.
- [ ] Treat format/compression as adapter concerns; support the declared source formats without
      demanding Parquet/JSONL from every retailer.

**2.3 Profiles, adapters and staging**
- [ ] Copy/adapt M5 `mapped_files` as the profile-driven default normalizer.
- [ ] Implement bounded Shopify, Business Central and companion-source adapters; all end at the
      same versioned staging envelopes.
- [ ] Profiles declare currency/minor unit, tax basis, business timezone/day, source grain,
      market/location mapping, timestamp evidence and derivation rules.
- [ ] Derive `observed_at` from trusted source timestamps or immutable landing time; create
      explicit versions from deterministic snapshot/event differences only for versioned
      cumulative/correctable facts; record provenance.
- [ ] Quarantine ambiguous keys, timestamps or semantics instead of manufacturing facts.

**2.4 Source-neutral transformations and Gate B**
- [ ] Build source-neutral transforms for joins/version selection; timezone/business-day;
      local-currency integer minor units; inclusive/exclusive tax; quantities; fulfilled sales;
      adjustments; aggregation and inventory snapshots.
- [ ] Map all calendar/event/weather/local-event/macro/promotion/competitor targets to
      market-qualified `geo_scope_*` or structured promotion applicability and prove
      `india/west` cannot join `us/west`.
- [ ] Map Shopify `shopMoney` to operating-currency sales and retain `presentmentMoney` as
      raw/staging audit evidence; quarantine unsupported mismatches.
- [ ] Implement shared `merch_scope_*` reference validation/precedence for supplier and promotion
      rows, supplier lane/origin resolution, and FX conversion using the exact shared contract.
- [ ] Build approved runtime crosswalks for product, store, warehouse, market and supplier keys.
- [ ] Attach source/profile/adapter/transform lineage and entity-specific `known_as_of`.
- [ ] Gate B validates schema/grain/keys, PIT, provenance, exact per-currency money controls,
      source-to-canonical reconciliation, capability dependencies, inventory invariants and
      referential integrity; reject divergent duplicate observations, unqualified/cross-market
      scopes, unsupported sales-currency mismatches and ambiguous supplier terms.
- [ ] Reason-coded quarantine; atomically publish only capability-complete curated
      Parquet/DuckDB.
- [ ] Put any direct canonical unit fixtures under ingestion/contract tests, never `datagen/`.
- [ ] Build the ingestion-test-owned, profile-versioned generator-vocabulary hidden-control →
      canonical expected-control oracle; production transforms and datagen must not import it.

**2.5 Acceptance tiers**
- [ ] Core round-trip: generated Shopify + BC + companion sources reconstruct the forecast/
      revenue-pricing canonical slice and pass the required Gate-B capability mask.
- [ ] Golden collision cases cover `West` in India and US, market-wide Diwali, similarly named
      cities/regions, scoped promotions and competitor observations; no feature row crosses market.
- [ ] Partial-source test: Shopify alone produces an honest `validated_partial` result and never
      reaches `ml/`.
- [ ] Extended tests are enabled with the matching Phase-1.6 fixture: fulfillment/return/refund
      histories, HMAC/ID parity, full inventory states, receipts/inbound/batches/suppliers,
      promotion depth and competitor matching.
- [ ] **Exit:** refs and controls hold; derivations are visible; curated capability-complete
      tables materialize; downstream code is source-neutral.

## Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)
- [ ] Weekly PIT feature build (+ competitor/weather/event/macro drivers).
- [ ] Join market-local calendars by market/calendar key; add market/country features and use
      dimensionless or local-normalized prices rather than raw cross-currency levels.
- [ ] Join weather/event/macro/promotion/competitor features only by `market_id` plus resolved
      `geo_scope_*` or structured promotion applicability; assert no unqualified region-only join.
- [ ] LightGBM horizon-quantile P50/P90, **horizons → 26 wk**; Croston routing.
- [ ] Baselines + FVA; metrics WAPE / bias / `accuracy = 100·(1−WAPE)`.
- [ ] Rolling-origin backtest + acceptance gates (≥25% vs seasonal-naive; P90 coverage 0.85–0.95; monotonic).
- [ ] Publish per-market WAPE/bias/P50/P90 coverage and require supported-market gates so a large
      market cannot hide a failure elsewhere; calibrate per market when evidence is sufficient.
- [ ] `forecast_versions`, SHAP `forecast_drivers` (+ competitor/weather groups), confidence.
- [ ] **Exit:** acceptance gates pass; artifacts fingerprinted. → Demand Forecast screen data.

## Phase 4 — Inventory & replenishment (`ml/engines`)
- [ ] Reorder / safety-stock (quantile-spread × service level).
- [ ] Service-level policy calibration (5%) + validation (95%); A/B/C.
- [ ] Multi-echelon `locations`, reconciled ATP, inbound/in-transit shipment state,
      batches/expiry and ageing.
- [ ] Resolve supplier/lead-time/MOQ/pack terms by destination or supply lane; do not apply one
      department-wide term across markets; test `sku > dept > category` precedence and prove null
      external origin never wildcard-matches an internal lane.
- [ ] Classify ABC and value inventory within market, or use an approved as-of reporting-currency
      conversion before any cross-market ranking/aggregation.
- [ ] Transfer optimizer; constrained allocation.
- [ ] Inventory-replay simulator + acceptance; demand-at-risk.
- [ ] **Exit:** replay + policy holdout pass. → Inventory + Replenishment screens.

## Phase 5 — Pricing & promotions (`ml/models`, `ml/engines`)
- [ ] Price-response elasticity (Poisson GLM + empirical-Bayes) + gates.
- [ ] On the primary response-rich preset, require ≥25 actually gated SKU×store series per
      enabled department independently in India and US; configured SKU/store counts are not proof.
- [ ] On `pricing-evidence-sparse`, publish a reason-coded `insufficient_evidence` state rather
      than empty or fabricated recommendations.
- [ ] Build price tiers, empirical-Bayes pools and acceptance coverage within market; never pool
      raw local-currency price levels across markets.
- [ ] Resolve price rules by `market_id + currency_code`; require market-local absolute floor/
      ceiling/step/grid/endings and share only dimensionless defaults.
- [ ] Publish revenue-objective price recommendations first under max-change/dominance rules.
- [ ] Enable margin objective/floor only when an accepted temporal cost ledger produces
      provenance-matched cost-as-of in the same local currency.
- [ ] Price simulation; scenario planning.
- [ ] Competitor monitor: product-matching + confidence gate + competitor-aware response.
- [ ] Promotion planner: uplift / cannibalisation / bundle / segment models.
- [ ] Resolve overlapping promotion merchandise targets by `sku > dept > category`; reject
      conflicting equal-precedence discounts and preserve promotion-scope AND/OR semantics.
- [ ] Cost-over-time margin (WAC default; FIFO for batch-tracked; cost-as-of).
- [ ] **Exit:** gates enforced per market; every rec carries market/currency and is guardrail-
      valid; unavailable margin is omitted, not synthesized. → Pricing / Competitor / Promotion.

## Phase 6 — Go API, workflow & governance (`api/`, `db/`)
- [ ] Alembic migrations (`db/`): reuse M5 workflow tables; add `retail_v2` domain/output tables
      plus `ingest_runs`, reconciliation, quality/quarantine, approved source-mapping config and
      runtime source-crosswalk tables.
- [ ] Go API serving artifacts (OpenAPI/proto in `contracts/`).
- [ ] Make pricing activation/recommendation market and currency explicit; keep consolidated
      reporting amounts separate from local recommendation amounts.
- [ ] Serve reporting conversions from the shared exact FX contract; never use Shopify
      presentment currency for recommendation math.
- [ ] Workflow/HITL: approvals, planner overrides (bounded + reason), idempotency, audit.
- [ ] Serve-time re-resolve and revalidate the same market policy as Python; staleness 409/503;
      RBAC/auth.
- [ ] **Fingerprint parity** — Python & Go pass shared golden vectors.
- [ ] **Exit:** approve/override audited; 409/503 correct; identical fingerprints. → Governance.

## Phase 7 — UI (`ui/`)
- [ ] Pick framework (see `docs/OPEN_DECISIONS.md` #17).
- [ ] Implement screens against the Go API; multi-currency (FX) display and explicit
      market/department `insufficient_evidence` pricing state.
- [ ] Wire interactive what-ifs (scenario/simulation) to the API.
- [ ] Build rich capture forms the mockup only stubs (§8.3).
- [ ] **Exit:** every screen renders live API data; no mock paths.

## Phase 8 — Analytics, admin & hardening
- [ ] Model registry / drift; alerts + data-freshness; data-source management; reports.
- [ ] Adoption metrics / performance insights (AI-vs-control cohort).
- [ ] Disclosure guardrails (projections not lift; observational elasticity; synthetic labelling).
- [ ] At least two client-shaped dialects proving config-only onboarding where existing transforms
      cover semantics; otherwise only a bounded versioned adapter, with no downstream changes.
- [ ] End-to-end acceptance run (ingest → serve) through all fail-closed gates.
- [ ] **Exit:** full run passes; all screens live.
