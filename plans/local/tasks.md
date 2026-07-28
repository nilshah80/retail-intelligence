# Retail Intelligence — Local Tasks

_Companion to `plans/local/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_All tasks below are **local**, on generated synthetic data, shadow-only._

## Cross-phase UI and demo track `[START EARLY]`

- [ ] Resolve UI framework decision #17 by the end of Phase 1; scaffold the runtime dashboard
      shell, routing, design tokens and shared market/currency/status components as soon as the
      first versioned screen/API contract is frozen.
- [ ] Maintain versioned OpenAPI/read-model contracts and deterministic stub fixtures ahead of
      each backend capability. Every screen must visibly identify stub data; a phase demo cannot
      claim a live capability until its accepted artifacts are served by the read-only Go API.
- [ ] Extend the thin read-only Go API and UI together in Phases 2–5; do not defer all API and UI
      work to Phases 6–7. Preserve one contract when a screen moves from stub to live data.
- [ ] Keep incomplete screens behind explicit demo feature flags; never fabricate unavailable
      metrics, pricing recommendations, margin or workflow state.
- [ ] Run incremental demo checkpoints:
      Phase 1 Config Builder → Phase 2 Data Management/quality → Phase 3 Demand Forecast →
      Phase 4 Inventory/Replenishment → Phase 5 Pricing/Competitor/Promotion → Phase 6 governed
      approval/override. Phase 7 completes integration and removes remaining core-screen stubs.

## Phase 1 — Config Builder and synthetic source generation `[FIRST]`

**1.1 Reuse audit and isolation**
- [x] Copy only compatible code from `../retail-synthetic-data-generator`; record reused,
      adapted and replaced modules.
- [x] Reuse/adapt only the portable primitives first: deterministic seed partitioning,
      source-native Shopify/Business Central ID formats and namespaces, atomic
      checkpoint/replace, checksumming/manifest logic and the CLI/logging shell where compatible.
      Replace mutable counter-based ID allocation with stable-key allocation.
- [x] Redesign the old `RunContext`/run identity, domain checkpoint state, writer dataset
      contract, controller orchestration and CLI commands against the new generator-owned
      config and source-data specification. Replace wall-clock-derived run identity with the
      content-derived identity in §9.3 before publishing reproducible runs.
- [x] Do not port the old `IdFactory.canonical`, `features/ml_ready`,
      `crossSystemMapping`, `analyticalExtension`, `mlReady` or fixed authoritative
      `retail.duckdb` publication contract. Hidden truth remains restricted and source-shaped
      Shopify/Business Central/companion publications are authoritative.
- [x] Give `datagen/` its own dependency file and generator-owned scenario/source schemas.
- [ ] Resolve Python environment topology decision #38 before creating ingestion/ML package
      lockfiles; `datagen/` remains isolated regardless of that choice.
- [x] Enforce that `datagen/` imports no `contracts/`, `ingestion/`, `ml/` or `api/` module.
- [x] Remove canonical `retail_v2` publication and canonical terminology from generator outputs.

**1.2 Config Builder — sole authoring surface**
- [x] Move/adapt the existing Config Builder into `datagen/`.
- [x] Replace scalar location/warehouse counts with explicit retailer → markets → stores /
      online channels → warehouses/DC topology and `serves_locations` relationships.
- [x] Support add/edit/remove/reorder for products/categories, markets, legal entities, stores,
      warehouses, channels, source projections, signals, promotions and scenario events.
- [x] Make rich catalog generation a first-class builder contract: generated/hybrid/explicit
      modes, country catalog-pack metadata, exact sellable-SKU targets, variants per product,
      SKU prefix/lifecycle controls, opening-incumbent share, category
      option/seasonality/cost/return/elasticity behavior and complete explicit-product fields.
- [x] Configure one or more Shopify shops and Business Central companies; map each source instance
      to explicit markets/stores/warehouses and its native currency/tax/legal context.
- [x] Expose every config field; remove preset-only hidden `countries`, `currencies`, formats,
      overwrite, execution and event fields.
- [x] Add import of builder-generated YAML/JSON and preserve lossless round trips.
- [x] Make YAML and JSON semantically identical; display the resolved config and schema version.
- [x] Materialize selected locale-pack versions and all resolved locale values into the exported
      run config; record overrides explicitly.
- [x] Validate unique IDs, date ranges, topology references, locale availability, timezone/
      currency compatibility, numeric ranges, event scope, enabled output formats and required
      projection settings.
- [x] Add India, US, primary response-rich multi-market Mumbai + New York and
      `pricing-evidence-sparse` presets; validate GB and DE through locale selection and
      generator tests without adding redundant one-button presets.
- [x] Ensure one warehouse may serve many stores and one store may have an approved fulfillment
      priority list across warehouses.

**1.3 Locale packs**
- [x] Implement data-driven `IN`, `US`, `GB` and `DE` packs; label GB as UK and DE as the PoC
      European representative in the UI.
- [x] Define currency/symbol/minor exponent, native price bands/endings, decimal/grouping display
      metadata and Faker locale.
- [x] Define tax basis plus category/jurisdiction rates: India GST/split rule, US state/local
      sales tax, GB VAT and DE VAT.
- [x] Define fiscal defaults, timezone choices, region/state and postcode formats.
- [x] Add reviewed holiday/sale-season tables, including dated lunar festivals; never calculate
      Diwali/Eid by approximation.
- [x] Define climate profiles and regional seasonality, including Indian monsoon.
- [x] Test that locale selection alone resolves all mandatory locale-sensitive defaults, with
      explicit documented overrides only.

**1.4 Causal simulation**
- [x] Deterministic RNG partitioned by stable business key/time; reproducible independent of
      processing order.
- [x] Adapt the reference master-data product/variant model and partial option matrices into
      versioned IN/US/GB/DE rich catalog packs with real brand/product-line reference identities,
      descriptions, materials, product codes, variant option combinations, sellable SKUs,
      valid EAN-13/UPC-A barcodes, prices/costs, popularity, elasticity, returns and lifecycle.
- [x] Expand the normalized default hierarchy to 10 departments and 41 categories, including
      groceries, and carry family-specific shelf life into receipt/batch expiry evidence.
- [x] Product/variant/category/assortment generation is market-scoped with exact sellable-SKU
      targets and deterministic store-specific assortment differences.
- [x] Support incumbent products at the history boundary plus independently dated later
      product/variant introductions, discontinuations and predecessor/successor chains; gate
      inventory, prices, demand and orders by SKU lifecycle.
- [x] Support flagship spike/decay launches, pre-launch anticipation, successor substitution,
      overlapping predecessor runout, markdown, clearance and fire-sale phases; never infer that
      a successor launch itself makes the predecessor unsellable.
- [x] Generate the full 2005–2024 multi-market preset and verify demand truth covers both
      boundaries, no order predates SKU launch, and CSV partitions reconcile to the one DuckDB.
- [x] Per-SKU×store latent demand with day-of-week, trend, locale holiday/seasonality, promotion,
      price elasticity, intermittency and new-product effects.
- [x] Adapt config-owned pandemic timelines from `../retail_ai`: H1N1 waves, timeline-only
      Ebola/Zika/Mpox and overlapping COVID demand/traffic/channel/cost/lead-time/inventory phases;
      publish timeline, daily signals and hidden causal factors.
- [x] Expose generator-owned assortment size, price-event frequency, latent-response and noise
      controls; response-rich/sparse presets must not contain downstream ML gate thresholds.
- [x] Expose optional per-market category-assortment weights in the Config Builder; omitted
      weights default to uniform and only explicit weights alter generated category depth.
- [x] Weather, local events, competitor movement and macro factors affect demand when enabled;
      record hidden contribution truth for later driver evaluation.
- [x] Inventory-constrained realized sales and a usable demand-location/supply-location link in
      source-native Shopify/BC shapes.
- [x] Generate local-currency exact source amounts with locale-correct inclusive/exclusive tax;
      do not emit canonical paise fields.

**1.5 Source projections and companion feeds**
- [x] Shopify-shaped products/variants, locations, orders/lines, detailed fulfillment, prices and
      inventory observations per configured Shopify source instance/market scope.
- [x] Business Central-shaped item/location, sales, inventory and finance records needed for the
      first forecast/revenue-pricing round-trip, partitioned by configured company/legal entity.
- [x] Close the inventory loop with adaptive SKU/location purchase orders using
      availability-normalized observed sales, inventory position, pending receipts,
      lead-time/fill behavior, a Config Builder-owned demand buffer, MOQ and pack size; seed the
      extraction boundary with optional velocity-weighted opening days of cover; post
      opening balance, purchase, sale, transfer, waste and adjustment entries to a complete
      company-scoped item ledger that reconciles to latest inventory.
- [x] Companion holiday, weather actual/forecast, local-event, promotion, competitor, macro and
      FX datasets; every contextual row carries a generator-owned market key and structured
      market/region/store/channel target, never unqualified `ALL` or a free-form promotion scope.
- [x] Document source FX as exact local-currency→retailer-reporting-currency decimal text; do not
      emit binary-float money/rates or assume reporting→local direction.
- [x] Source-run manifest: generator/source-spec version, full resolved-config hash, seed/run ID,
      topology, output inventory, row/control totals and content hashes.
- [x] Publish `source-schema.json` and the DuckDB `source_schema` table as a generator-owned
      field dictionary for every logical source dataset.
- [x] Hidden generator-vocabulary truth kept outside public source projections.
- [x] Declare and test exactly one authoritative tabular format per run: CSV/uncompressed or
      Parquet with none/snappy/zstd compression; mirror that selection into one DuckDB.
- [x] Make `startingDailyOrders` control real order headers by generating transactional unit
      lines and deterministic multi-line baskets; expose `averageLinesPerOrder` in HTML/config
      and test achieved daily volume rather than accepting one aggregate line per SKU/day.
- [x] Make conventional YAML the Config Builder/CLI default and checked-in config format while
      retaining equivalent JSON import, download and CLI loading.

**1.6 Screen-completeness extensions — non-blocking for first round-trip**
- [x] Detailed split fulfillment, open/closed fulfillment-order lines and fulfillment-status
      histories; open line quantities reconcile to causal committed inventory.
- [x] Requested-vs-processed return evidence and successful/failed refund transactions.
- [x] Webhook envelopes plus valid/invalid HMAC fixtures and ID-parity cases.
- [x] Full Shopify inventory-state fixture matrix.
- [x] Business Central/ERP purchase orders, receipts/cost layers, inbound shipments, batches/
      expiry and supplier performance.
- [x] Warehouse capacity/utilization, fill rate, dock-to-stock, blocked stock and delayed-receipt
      observations.
- [x] Waste events, inventory ageing inputs and optional ERP↔WMS comparison observations.
- [x] Transfer request/order/shipment histories and lane/location evidence.
- [x] Supplier capacity confirmation, OTD, lead-time variability, MOQ/pack and budget inputs.
- [x] Promotion-SKU/customer-segment depth, basket/order-line histories for bundle/
      cannibalisation tests and realistic competitor-product matching.
- [x] Allocation demand requests, supply pools and source fulfillment-location evidence.
- [x] Publish one selected authoritative CSV/Parquet format plus one all-source
      `source-run.duckdb` mirror; keep JSONL as an ingestion concern when a retailer supplies it.
- [x] Verify every dashboard row in `datagen/README.md` is either backed by generated source
      evidence or explicitly marked downstream-derived/runtime.

**1.7 Phase exit**
- [x] Same config + seed produces identical logical source outputs and manifest hashes.
- [x] Builder defaults to conventional YAML, retains JSON, and exports/re-imports equivalent
      configurations with no hidden fields.
- [x] Mumbai and New York in one retailer produce correct independent money, tax, timezone,
      holiday, climate, companion-signal scope and warehouse relationships, including duplicate
      region labels that remain distinct by market.
- [x] Response-rich and sparse-evidence presets reproduce their declared assortment, price-event
      and noise characteristics without importing or asserting ML acceptance thresholds.
- [x] IN/US/GB/DE locale-pack tests pass.
- [x] Execute the prior v7 YAML-first `2021-01-01`–`2026-07-27` high-volume scenario:
      1,181,043 actual order headers, 2,115,482 realized units, 241/581/2,106 combined
      min/average/max daily orders, 4,891 zstd-Parquet source objects, generated source schema and
      one verified DuckDB mirror; measured fill is 98.0191% and all 4,895 manifest objects verify.
- [x] Execute and verify the v8 real-brand/10-department replacement run for
      `2021-01-01`–`2026-07-27`, including lifecycle promotion rows and predecessor sales after
      successor launch: retained run `run-9b53e0a0490d3114` has 1,054,012 orders, 1,886,776
      units, 30,831,206 rows, 5,091 Parquet objects and one verified/reused DuckDB mirror.
- [x] Re-measure v8 high-volume realism at 36 SKUs/department across 10 departments
      (360 SKUs/market): median zero-day share 38.71% IN / 56.72% US; price endings
      82.44%/82.57%; lifecycle promotion coverage 21.93%/22.19%; post-successor predecessor
      sales proven for iPhone 13–16; committed quantities reconcile 70/96 to open fulfillment
      lines; all 315,360 BC snapshots reconcile to ledger movements.
- [x] Measure the v0.9.2 current-volume opening boundary with a valid disposable 90-day
      derivative: 28 main-DC opening days, no forced opening stockouts and a 25% observed-demand
      buffer produce 92.44% fill overall; the March dip is caused by 192 POs still in transit at
      the artificial extract boundary, not by cold start or the constant COVID step phase.
- [ ] Execute the complete v0.9.2 `2021-01-01`–`2026-07-27` current-volume run and measure
      long-horizon fill, elasticity recovery, lifecycle stages, holiday peaks, within-series
      overdispersion and autocorrelation; the disposable boundary slice is not a substitute.
- [ ] Shopify, BC and companion outputs land successfully in Phase 2.
- [x] The first pricing milestone is explicitly revenue-only; no margin amount/objective is
      implied unless the optional receipt/cost projection is enabled.
- [x] **Demo checkpoint 1:** use the Config Builder HTML to create, export, re-import and generate
      the Mumbai + New York scenario; show locale-correct source outputs and the run manifest.

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
- [ ] Add a datagen-DuckDB PoC profile that discovers tables through the source catalogs,
      preserves authoritative CSV/Parquet lineage, and excludes every `restricted=true`/`_truth`
      dataset from ordinary staging and ML.

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
- [ ] Freeze common API envelopes plus Data Management/quality read models; implement the initial
      read-only Go API slice over ingest runs, source coverage, reconciliation and quarantine.
- [ ] Scaffold the runtime UI using the selected framework and replace its Data Management stubs
      with the live Phase-2 API slice.
- [ ] **Demo checkpoint 2:** run Config Builder → source generation → ingestion and show live
      landing, Gate A/B, coverage, reconciliation and quarantine status in the dashboard.
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
- [ ] Extend the read-only Go API with versioned forecast-series, horizon, metric, confidence and
      driver endpoints; keep market/currency/config fingerprints explicit.
- [ ] Build the Demand Forecast UI vertical slice against the same contract used by its stub,
      then switch it to accepted live forecast artifacts without changing the screen contract.
- [ ] **Demo checkpoint 3 / exit:** acceptance gates pass; artifacts are fingerprinted and the
      Demand Forecast screen renders live Mumbai + New York P50/P90, accuracy and drivers.

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
- [ ] Extend the read-only Go API and UI with inventory, demand-at-risk, reorder, transfer and
      replenishment read models; unavailable extension-only evidence remains visibly unavailable.
- [ ] **Demo checkpoint 4 / exit:** replay and policy holdout pass; Inventory and Replenishment
      screens render live market/location-scoped outputs.

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
- [ ] Extend the read-only Go API and UI with pricing, price simulation, competitor and promotion
      read models, including market/department reason-coded `insufficient_evidence`.
- [ ] **Demo checkpoint 5 / exit:** gates are enforced per market; every recommendation carries
      market/currency and is guardrail-valid; Pricing/Competitor/Promotion screens render live
      response-rich and sparse-evidence outcomes; unavailable margin is omitted, not synthesized.

## Phase 6 — Go API, workflow & governance (`api/`, `db/`)
- [ ] Alembic migrations (`db/`): reuse M5 workflow tables; add `retail_v2` domain/output tables
      plus `ingest_runs`, reconciliation, quality/quarantine, approved source-mapping config and
      runtime source-crosswalk tables.
- [ ] Consolidate and harden the read-only Go API slices delivered in Phases 2–5; keep
      OpenAPI/proto contracts in `contracts/` and preserve their stub-to-live compatibility.
- [ ] Make pricing activation/recommendation market and currency explicit; keep consolidated
      reporting amounts separate from local recommendation amounts.
- [ ] Serve reporting conversions from the shared exact FX contract; never use Shopify
      presentment currency for recommendation math.
- [ ] Workflow/HITL: approvals, planner overrides (bounded + reason), idempotency, audit.
- [ ] Serve-time re-resolve and revalidate the same market policy as Python; staleness 409/503;
      RBAC/auth.
- [ ] **Fingerprint parity** — Python & Go pass shared golden vectors.
- [ ] Wire approval/override, governance and audit interactions into the already-live UI slices.
- [ ] **Demo checkpoint 6 / exit:** a planner reviews live demand/inventory/pricing evidence,
      approves or overrides a draft, and the UI shows the audit row; 409/503 and fingerprints pass.

## Phase 7 — UI completion and end-to-end integration (`ui/`)
- [ ] Complete the remaining core screens and shared responsive/accessibility behavior; do not
      rebuild the vertical slices already delivered in Phases 2–6.
- [ ] Verify multi-currency (FX) display and explicit market/department
      `insufficient_evidence` pricing state across all relevant screens.
- [ ] Wire interactive what-ifs (scenario/simulation) to the API.
- [ ] Build rich capture forms the mockup only stubs (§8.3).
- [ ] Remove all remaining core-screen stub paths and demo feature flags.
- [ ] **Exit:** every Phase-2–6 core screen renders live API data; no core mock paths.

## Phase 8 — Analytics, admin & hardening
- [ ] Model registry / drift; alerts + data-freshness; data-source management; reports.
- [ ] Adoption metrics / performance insights (AI-vs-control cohort).
- [ ] Disclosure guardrails (projections not lift; observational elasticity; synthetic labelling).
- [ ] At least two client-shaped dialects proving config-only onboarding where existing transforms
      cover semantics; otherwise only a bounded versioned adapter, with no downstream changes.
- [ ] End-to-end acceptance run (ingest → serve) through all fail-closed gates.
- [ ] **Exit:** full run passes; all screens live.
