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

## Cross-phase execution profiles `[HARDWARE-SCALED, LOGIC-STABLE]`

- [x] Define a versioned operational execution-profile contract with named `safe`, `balanced`,
      `performance`, `ultra-performance` and `custom` profiles for datagen, ingestion, ML and API. Keep CPU/thread/
      process counts, memory ceilings, buffers, connection pools and temporary-work locations
      separate from scenario, canonical-data, model/policy and API-contract configuration.
- [x] Put the shared schema, named-profile definitions, override/validation rules and golden
      vectors under the neutral independently installable `execution/` package—not canonical
      `contracts/`. Use layer
      namespaces (`datagen`, `ingestion`, `ml`, `api`) so common fields are consistent without
      pretending that a process pool, model trainer and Go connection pool have the same
      lifecycle.
- [x] Implement one small source-neutral Python execution-profile resolver package now and make
      datagen consume it. Decision #38 still governs whether ingestion/ML have separate
      environments, not whether they reuse this independently installable package. Keep it free
      of retail schema/business logic; do not copy three drifting parsers.
- [ ] Implement a thin Go resolver in `api/` against the same schema, precedence rules and golden
      vectors. Share the contract and behavior across Python/Go, not Python runtime code or
      layer-specific worker/pool implementations.
- [ ] Give every layer a narrow adapter from the resolved shared profile into its native engine.
      The Phase-1 datagen adapter is complete for market/partition/DuckDB workers, memory and
      spools; ingestion scan/transform/write, ML feature/fold/model and API goroutine/replica/
      connection-pool adapters land in their owning phases. Keep engine ownership and cleanup
      within that layer.
- [ ] Make the resolved execution profile visible in each run/build/deployment manifest. Datagen
      now records its resolved profile and telemetry without affecting run identity; ingestion,
      ML and API manifests still need the same rule. Exclude hardware tuning from
      source-run identity, canonical fingerprints and business/model semantics.
- [x] Establish override precedence (`explicit CLI/env > profile document > selected named
      profile > safe default`), validate impossible/oversubscribed datagen combinations before
      work starts, and never infer an unbounded setting from total host RAM/CPU.
- [ ] Emit per-stage wall time, peak RSS, CPU utilization, worker/thread counts, spill/temp bytes
      and output bytes in every layer. Datagen telemetry and its disposable safe/performance/
      ultra-performance
      benchmark are complete; ingestion, ML and API add their metrics/benchmarks in their phases.

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
- [x] Measure the v0.9.2 `2016-07-28`–`2026-07-28` Config-Builder run as historical
      performance/source evidence only, then remove its obsolete local folder after v10
      acceptance:
      `run-98abf242ff98ddc0`: 137 datasets, 9,480 authoritative Parquet objects,
      295,522,648 rows, 11,692,994 orders, 30,761,542 realized units and one verified
      12,614,119,424-byte DuckDB mirror. Measured fill is 93.4571%; identical regeneration
      reverified hashes and returned `reused: true`.
- [x] Replace run-sized Python projection lists with private bounded row spools; prune
      replenishment evidence to its causal trailing 28-day window; publish independent month
      partitions with deterministic worker parity; cap DuckDB through runtime controls that do
      not affect run identity.
- [x] Replace the 750-identities-per-market order hash with Config Builder-owned opening
      population, annual acquisition, churn/reactivation, guest checkout, opening history and
      max-orders-per-customer/day controls. Publish multi-year direct-identifier-free Shopify/BC
      customer masters and explicit BC walk-in accounts.
- [x] Verify the v0.10.0 two-worker/4-GiB execution path on the complete 90-day showcase:
      78,818 orders, 47.02 seconds and 648,462,336-byte peak process RSS, with authoritative
      bytes equal between one- and two-worker publication.
- [x] Exercise the larger 720-SKU/125k-opening-customers-per-market profile over Jan–Mar 2026,
      including its grand-opening event: 123,491 orders, 76.88 seconds and 850,034,688-byte
      peak RSS with disposable output cleaned automatically.
- [x] Generate and measure the corrected v0.10.0/v10 predecessor on the
      16-GB-available demo profile: 1h40m28.55s, 7.27-GiB peak RSS, 10,198 Parquet objects,
      297,619,898 rows and a 12,839,563,264-byte DuckDB mirror. Customer creation spans
      2011–2026; guest share is 18.03% IN / 18.02% US; registered-customer order-count
      `p25/p50/p75/p90/p99` is `3/7/14/25/51` IN and `3/7/14/24/50` US; max customer/day
      is two and both Shopify/BC orphan counts are zero. This run was superseded and removed
      when the v0.11.0 ultra run passed acceptance.
- [x] Extend datagen execution scaling beyond the existing partition workers: add independent
      `marketWorkers`, `partitionWorkers` and `duckdbThreads` controls while retaining the
      memory ceiling and spool-chunk limit. Run causally independent markets in separate
      processes; do not parallelize state transitions within one market/day.
- [x] Add an **Execution profile** panel to the Config Builder and export a separate
      execution-profile YAML using the shared contract alongside the scenario YAML. Changing
      hardware settings must not change the scenario config hash, run ID, logical rows or
      authoritative Parquet hashes.
- [x] Add deterministic parity tests across one-worker and multi-process profiles, including
      stable order/customer/source IDs, object catalogs and reconciliation totals. Prevent nested
      oversubscription by stage-separating the market process pool, partition thread pool and
      DuckDB thread pool rather than multiplying all three concurrently.
- [x] Benchmark the same disposable 90-day showcase under safe, performance and
      ultra-performance profiles. The comparable three-way run measured 47.325s / 41.778s /
      41.612s on the 16-core M4 Max: ultra is 12.1% faster than safe but only 0.4% faster than
      performance for this two-market workload. All 534 authoritative hashes and controls
      matched, and temporary outputs were removed.
- [x] Generate and retain the full v0.11.0 ten-year configuration under ultra-performance:
      `run-b8c4cceba05eb61a`, 1h26m50.27s, 17.56-GiB peak process RSS, 63,820,489,478 temporary
      work bytes before cleanup, 10,198 Parquet objects, 297,619,898 source rows and a
      12,938,129,408-byte DuckDB mirror. Immutable reuse verification completed in 7.52s. This
      run is now benchmark evidence only because it predates v0.12.0/v11 corrections.
- [x] Resolve the pre-Phase-2 datagen review blockers in v0.12.0/v11: reconcile source tax/PO/
      receipt/customer/ledger identities, bound partition and batch working state, enforce strict
      execution profiles, replace periodic price and symmetric-season artifacts, correct retail
      calendars and promotion attribution/payback, emit true multi-channel SKU-day demand, and
      keep the Config Builder/YAML presets synchronized. Carry regular-price state across years;
      normalize continuous annual seasonality to mean one; normalize volume against the annual
      live assortment; publish collision-free BC invoice numbers; drive online-share start/end/SKU
      variation from HTML-authored market controls; validate every execution-profile layer from
      the packaged schema; and keep standalone `pip install -e datagen` working by packaging the
      shared runtime from its single source. Replace the 10-year preset's 240-day overstock with
      42/14-day node cover and 2% constrained-SKU evidence.
- [ ] Generate, accept and pin the full v0.12.0/v11 ten-year configuration before Phase 2
      landing starts. Record the new run/config/manifest hashes, row/object totals, runtime,
      process RSS, reconciliation checks and forecast-realism acceptance measurements.
- [ ] Run equivalent full ten-year v0.11.0 safe and performance measurements only when two
      additional ~19-GB disposable outputs and multi-hour runs are scheduled. The 90-day parity
      benchmark already proves logical equivalence; this is optional performance evidence, not a
      blocker to generating the replacement v0.12.0/v11 source run.
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
- [ ] Add a canonical `[in]` market-disruption observation contract for public pandemic
      timeline/signal evidence so Phase-3 features do not discard configured COVID effects;
      hidden `_truth` demand factors remain test-only.
- [ ] Seed guardrail YAMLs (`pricing_rules`, `policy`, `price_response`) and data dictionary;
      implement decision #39 global dimensionless defaults + deterministic market/currency
      resolution, with absolute price/grid/ending rules required per market.
- [ ] Resolve decision #16 and publish the canonical-JSON fingerprint specification plus shared
      golden vectors before any Phase-3 artifact is fingerprinted.
- [ ] Publish shared resolved-policy golden vectors for byte-identical Python/Go validation.

**2.2 Landing and Gate A**
- [x] Select the immutable Phase-2 input as `run-b8c4cceba05eb61a`, config hash
      `d52f5b629cd43243407618e9884ef25d6ac595933d317dcd6bae63fb83a89f50` and
      manifest-file SHA-256
      `901741cfac7b94e2208ccbbc0a34e0fd5e298efe31aae7d81805c3054568f6c1`;
      never select “latest” or silently regenerate with another seed.
- [ ] Land that exact run folder into an immutable raw/object-store prefix. Keep public source
      objects separate from restricted `_truth` and the all-source DuckDB permission lane.
      `run-98abf242ff98ddc0` remains ineligible because it predates the v10
      customer-population and bounded-memory contract.
- [ ] Immutable raw landing with landing time, content hashes and idempotent replay; land public
      source objects and restricted `_truth`/all-source DuckDB into separate permission lanes.
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
- [ ] Benchmark full-pin and incremental-month ingestion by stage (wall time, peak RSS,
      rows/partitions scanned and output bytes); lock performance SLAs from measured evidence,
      and fail accidental full-history scans where partition pruning is expected.
- [ ] Apply the shared execution-profile contract to ingestion scan workers, transform workers,
      DuckDB threads, memory/spill ceilings and partition-write concurrency. Prove safe and
      ultra-performance profiles produce identical accepted/quarantined row sets, controls, hashes
      and Gate A/B outcomes; use the common Python resolver rather than an ingestion-only parser.
- [ ] Freeze common API envelopes plus Data Management/quality read models; implement the initial
      read-only Go API slice over ingest runs, source coverage, reconciliation and quarantine.
- [ ] Scaffold the runtime UI as soon as the screen contract is frozen; use visibly labelled
      deterministic stubs, then replace panels independently with the matching live Phase-2 API
      slice.
- [ ] **Demo 2A:** after Gate A, show the retained source run, landing inventory, source
      controls/hashes and Gate-A results live in the dashboard.
- [ ] **Demo 2B:** after adapters/staging, add live coverage, reconciliation and reason-coded
      quarantine while Gate B remains visibly pending.
- [ ] **Demo 2C / Phase-2 exit:** add live Gate B, capability mask, curated publication and
      oracle-control status. Do not wait for Demand Forecasting or Pricing to begin this UI work.
- [ ] **Exit:** refs and controls hold; derivations are visible; curated capability-complete
      tables materialize; downstream code is source-neutral.

## Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)
- [ ] Implement ML execution profiles for feature-build workers, rolling-origin/fold workers,
      market/model workers, threads per model, memory ceilings and spill/cache paths. Schedule
      independent markets, series groups and backtest folds concurrently without multiplying
      nested thread pools beyond the resolved CPU/memory budget; consume the same common Python
      resolver used by datagen and ingestion.
- [ ] Separate execution tuning from feature/model/policy specifications and artifact identity.
      Fix every RNG seed; enable deterministic trainer settings; require equivalent features,
      predictions, metrics, SHAP group totals and acceptance decisions across safe and
      ultra-performance profiles (byte-identical artifacts where the library supports it, otherwise
      declared numeric tolerances).
- [ ] Record stage-level ML telemetry and benchmark the full pinned-data feature build,
      rolling-origin backtest and training run on both the 16-GB-available demo profile and a
      high-performance profile. Fail closed on OOM risk and fall back to bounded batching rather
      than silently reducing horizons, markets, series or validation folds.
- [ ] Characterize the retained curated demand series before fitting: lifecycle stages,
      holiday/event peak ratios, zero-day share, overdispersion and autocorrelation. Treat these
      as model-routing/evaluation evidence, not as a reason to regenerate the pinned source run.
- [ ] Weekly PIT feature build (+ competitor/weather/event/market-disruption/macro drivers).
- [ ] Join market-local calendars by market/calendar key; add market/country features and use
      dimensionless or local-normalized prices rather than raw cross-currency levels.
- [ ] Join weather/event/market-disruption/macro/promotion/competitor features only by
      `market_id` plus resolved `geo_scope_*` or structured promotion applicability; assert no
      unqualified region-only join.
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
- [ ] Implement API execution profiles for `GOMAXPROCS`, replica count, HTTP concurrency,
      PostgreSQL/DuckDB connection pools, background-job workers, queue depth, request/body
      limits, timeouts and memory budgets. Resolve them from deployment config/environment,
      never from retailer business configuration or request payloads; use the Go resolver that
      passes the shared execution-profile golden vectors.
- [ ] Prevent pool/thread oversubscription across replicas and keep scarce DuckDB writers
      serialized while allowing bounded concurrent readers. Expose the resolved non-secret
      profile and saturation/queue/pool metrics through operations telemetry.
- [ ] Load-test safe, balanced, performance and ultra-performance profiles with the same read, simulation and
      approval workloads. Require identical response values, fingerprints, authorization,
      idempotency and guardrail decisions; performance tuning may change latency/throughput only.
      Publish p50/p95/p99 latency, throughput, error rate, peak RSS/CPU and pool saturation, then
      set explicit demo and production-like acceptance budgets.
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
