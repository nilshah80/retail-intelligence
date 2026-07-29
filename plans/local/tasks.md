# Retail Intelligence — Local Tasks

_Companion to `plans/local/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_All tasks below are **local**, on generated synthetic data, shadow-only._

## Cross-phase UI and demo track `[START EARLY]`

- [~] UI framework decision #17 is recorded (React + Vite + TypeScript + Tailwind). The initial
      Phase-2 screen proved live API connectivity, but its shell/design is rejected as a demo
      baseline because it does not follow the agreed HTML. Do not describe Phase-2 UI as
      complete until the parity gates below pass.
- [ ] Treat `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` as a strict,
      review-controlled UI contract—not visual inspiration. Preserve its application width,
      navy/light color system, typography hierarchy, left-navigation groups/order/icons/
      submenus, top title/subtitle and filter order, display-currency strip, page composition,
      labels, table columns, bottom KPI strip and branded footer. Any deviation requires explicit
      approval before implementation.
- [ ] Record the only currently approved omissions: **Add Data Source**, **Upload Sample Data**
      and **Run Validation** may be omitted for now, and the sidebar user card/User Management
      navigation/destination may be omitted until users/RBAC are implemented. These exceptions do not permit
      changing any other navigation, header, content, footer, color or spacing contract.
- [ ] Remove internal delivery language from the product UI: no “Phase 2”, “Phase 3”, “Phase 4”,
      “Phase 5”, “governed ingestion”, source snapshot hashes, implementation status or roadmap
      badges in the normal business experience. Keep such evidence in API/Swagger, tests,
      development diagnostics or a separately approved technical view.
- [ ] Before coding each page, produce a parity/data matrix with one row per visible HTML element:
      reference selector/text, required behavior, API field or governed calculation, canonical
      grain, filter context, unit/currency, time window, formatting, loading/error/empty behavior
      and implementation/test status. Review that matrix before changing React code.
- [ ] Never reuse a nearby backend count under a reference UI label. Implement the exact business
      definition or mark the element unavailable in the reviewed data matrix; never invent,
      relabel or silently approximate data. Sample/stub values must not appear in a live demo.
- [ ] Build the shared HTML shell once before the next vertical slice: full left navigation,
      topbar filters, currency strip, common content container, seven-item footer KPI strip and
      page footer. All phase screens reuse this shell; phases may not independently redesign it.
- [ ] Add automated parity gates: reference and React screenshots at agreed desktop and
      responsive viewports, DOM assertions for navigation/order/text/table columns, design-token
      assertions for the approved palette/layout, and API fixture assertions for every displayed
      value. Require a human screenshot review before each demo checkpoint.
- [~] Maintain internally versioned OpenAPI/read-model contracts and deterministic fixtures ahead
      of each backend capability. Fixtures are for tests only and cannot make a demo screen look
      live. A phase demo cannot claim a live capability until accepted artifacts are served by
      the read-only Go API and every visible value passes its data-map assertion.
- [~] Extend the thin read-only [Aarv](https://github.com/nilshah80/aarv)-based Go API and UI
      together in Phases 2–5; do not defer all API and UI work to Phases 6–7. Preserve one
      contract when a screen moves from test fixture to live data. The ingestion/API portion of
      Phase 2 is complete; the Phase-2 UI parity correction remains open.
- [ ] Keep incomplete destination pages non-demoable without altering or annotating the agreed
      navigation. Never fabricate unavailable metrics, pricing recommendations, margin or
      workflow state, and never place phase/roadmap labels beside future navigation items.
- [ ] Run incremental demo checkpoints:
      Phase 1 Config Builder → Phase 2 Data Management/quality → Phase 3 Demand Forecast →
      Phase 4 Inventory/Replenishment → Phase 5 Pricing/Competitor/Promotion → Phase 6 governed
      approval/override. A checkpoint passes only after HTML parity, live-data mapping and human
      visual review; Phase 7 completes integration rather than redesigning accepted screens.

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
- [x] Implement a thin Go resolver in `api/` against the same schema, precedence rules and golden
      vectors. Share the contract and behavior across Python/Go, not Python runtime code or
      layer-specific worker/pool implementations.
- [~] Give every layer a narrow adapter from the resolved shared profile into its native engine.
      The datagen, ingestion scan/transform/write/DuckDB/memory and API
      goroutine/connection-pool adapters are complete; ML feature/fold/model adapters land in
      Phase 3. Keep engine ownership and cleanup within that layer.
- [~] Make the resolved execution profile visible in each run/build/deployment manifest. Datagen
      and ingestion record it without affecting identity, and the API exposes its resolved
      profile through health evidence; ML and production deployment manifests remain. Exclude hardware tuning from
      source-run identity, canonical fingerprints and business/model semantics.
- [x] Establish override precedence (`explicit CLI/env > profile document > selected named
      profile > safe default`), validate impossible/oversubscribed datagen combinations before
      work starts, and never infer an unbounded setting from total host RAM/CPU.
- [x] Make the Phase-2 Python foundation and authoritative developer commands portable across
      Windows, macOS and Linux: use `pathlib`, platform-aware virtualenv executables, subprocess
      argument lists and `tools/dev.py`; keep `Makefile`/shell wrappers optional. Run contract,
      boundary, Phase-2 unit and real isolated-wheel checks locally. Record decision #47; the
      three-OS CI enforcement remains the explicit Phase-7/8 hardening task below.
- [x] Apply decision #47 to the Phase-2 local layers: the Aarv-based Go API uses
      `filepath` and portable lock/process primitives; React tooling uses cross-platform npm
      scripts; the shared developer entry point dispatches Python/Go/Node without Bash. Local
      Go race/unit/build and Node typecheck/test/build checks exist; adding those checks to a
      Windows/macOS/Linux CI matrix is intentionally deferred. Future ML/DB layers add their own
      portable checks when they land.
- [ ] At Phase-7/8 hardening, make the three-OS matrix a blocking Definition of Done for **every**
      completed layer. Do not add or expand GitHub workflows during the current local capability
      build merely to represent unfinished phases; use `tools/dev.py` and component tests until the
      corresponding runtime exists. The eventual matrix includes the
      existing datagen suite and Config Builder tests, contract/code generation, execution,
      ingestion, ML native dependencies and deterministic small training fixture, database
      migration upgrade/downgrade, Aarv API and UI. Linux/macOS-only evidence cannot close a
      phase; document any intentionally unsupported optional dependency and provide a portable
      fallback before acceptance.
- [~] Enforce the portable storage/process contract in review and tests: Phase-2
      manifests/catalogs use
      normalized `/` logical paths while I/O uses native `Path`/`filepath`; reject
      case-colliding and Windows-reserved names; normalize fingerprinted text to UTF-8/LF; use
      `tempfile` rather than `/tmp`; never require `fork`, `flock`, symlinks, mode bits or shell
      expansion; close files/readers/DuckDB connections before same-volume atomic replacement.
      Carry the same gate into future ML/DB code.
- [x] Add and validate a root `.gitattributes` policy before more generated/API/UI code lands:
      contract/vector/generated source files use deterministic UTF-8/LF on every checkout, while
      Windows-native scripts are explicitly CRLF. Cross-platform CI verifies code generation and
      fingerprints.
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
- [ ] Run the full datagen unit/config-builder/pack-contract suite plus a small deterministic
      CSV/Parquet/DuckDB generation fixture on `windows-latest`, `ubuntu-latest` and
      `macos-latest`. Verify native virtualenv entry points, multiprocessing startup, worker
      cleanup, handle closure before promotion, logical-path/hash equality and browser YAML/JSON
      round-trip parity. Do not mark Phase 1 cross-platform complete from wheel-import checks
      alone.
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
- [x] Generate and accept the full v0.11.0 ten-year configuration under ultra-performance as
      benchmark evidence: `run-b8c4cceba05eb61a`, 1h26m50.27s, 17.56-GiB peak process RSS,
      63,820,489,478 temporary work bytes before cleanup, 10,198 Parquet objects, 297,619,898
      source rows and a 12,938,129,408-byte DuckDB mirror (365 restricted truth Parquet objects
      plus one separately restricted all-source mirror). Immutable reuse verification completed in
      7.52s. Its local output folder was then removed after v0.12.0/v11 superseded it: these
      measurements and hashes are retained for historical comparison, the artifacts are no longer
      present locally, and the run stays reproducible from its recorded config/version. It is
      benchmark evidence only and is not the Phase-2 pin.
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
- [x] Generate, accept and pin the full v0.12.0/v11 ten-year configuration before Phase 2
      landing starts. Record the new run/config/manifest hashes, row/object totals, runtime,
      process RSS, reconciliation checks and forecast-realism acceptance measurements.
- [ ] Run equivalent full ten-year v0.11.0 safe and performance measurements only when two
      additional ~19-GB disposable outputs and multi-hour runs are scheduled. The 90-day parity
      benchmark already proves logical equivalence; this is optional performance evidence, not a
      blocker to using the accepted v0.12.0/v11 source run.
- [ ] Shopify, BC and companion outputs land successfully in Phase 2.
- [x] The first pricing milestone is explicitly revenue-only; no margin amount/objective is
      implied unless the optional receipt/cost projection is enabled.
- [x] **Demo checkpoint 1:** use the Config Builder HTML to create, export, re-import and generate
      the Mumbai + New York scenario; show locale-correct source outputs and the run manifest.

## Phase 2 — Ingestion, transformation & data quality (`ingestion/`)

**2.0 Scaffolding and boundaries**
- [x] Scaffold independently installable `retail-contracts`, ingestion and ML distributions
      around the shared execution package, with decision #38 recorded.
- [x] Enforce source-boundary and source-neutral-transform imports through AST analysis that
      resolves absolute and relative imports.
- [x] Build and import datagen, execution, contracts, ingestion and ML as real isolated wheels;
      expose the same check through `tools/dev.py` on Windows/macOS/Linux and optional POSIX
      Make targets.
- [x] Bind ingestion execution settings to the shared resolver and expose scan, transform, write,
      DuckDB-thread and memory overrides through CLI, environment and profile documents.

**2.1 Contracts — freeze before Gate B**
- [x] Author the 53-entity `contracts/retail_v2` foundation from spec §11 with entities, grains,
      keys, columns, types, ownership, tiers and temporal classes.
- [x] Define integer minor-unit money paired with currency; exact controls reconcile per currency;
      define tenant reporting conversion as exact local/base→reporting/quote `DECIMAL(38,18)`,
      exponent-aware per-fact `ROUND_HALF_EVEN`, then aggregate. Python primitives and tests are
      complete; the Phase-2 Go read API transports already-normalized controls and performs no
      independent money conversion.
- [x] Require canonical `locations` and derived `stores` to carry `market_id`, operating
      `currency_code` and IANA `timezone`; sales/sell prices must match operating currency and
      Shopify presentment money is audit-only.
- [x] Require contextual feeds and normalized promotion scopes to carry `market_id`; define typed
      `geo_scope_type + geo_scope_id` keys, market-namespaced region semantics and separate
      multi-axis promotion applicability rows.
- [x] Define explicit integer versions only for cumulative/correctable facts; define natural key
      + effective/observation time + `known_as_of` for observation/reference facts and quarantine
      divergent duplicate complete keys.
- [x] Define supplier terms and promotion merchandise targets with
      `merch_scope_type ∈ {sku, dept, category} + merch_scope_id` and
      `sku > dept > category`; define supplier destination and exact/null-external origin.
- [x] Separate entity ownership (`[in]` / `[poc]` / `[cfg]` / `[test]`) from row provenance.
- [x] Publish source-profile, coverage/capability, staging, transform, mapping/crosswalk,
      reconciliation and quarantine contracts.
- [x] Add a canonical `[in]` market-disruption observation contract for public pandemic
      timeline/signal evidence so Phase-3 features do not discard configured COVID effects;
      hidden `_truth` demand factors remain test-only.
- [x] Preserve channel as an orthogonal dimension in canonical sales, sell prices, assortment and
      forecast series; retain channel in adjustments/fulfilments/planner adjustments and retain
      `source_price_path_id` when shop-wide prices fan out so copies are not independent evidence.
- [x] Seed guardrail YAMLs (`pricing_rules`, `policy`, `price_response`) and data dictionary;
      implement decision #39 global dimensionless defaults + deterministic market/currency
      resolution, with absolute price/grid/ending rules required per market.
- [x] Resolve decision #16 and publish RFC-8785 canonical JSON, the safe-integer/decimal-string
      policy, exact volatile JSON Pointers and shared
      golden vectors before any Phase-3 artifact is fingerprinted.
- [x] Publish shared resolved-policy canonical-byte/fingerprint golden vectors; Python validation
      is live and Go consumes the same vectors when its resolver lands.
- [x] Require `known_as_of_evidence_grade` physically on every canonical temporal row and bind it
      to the closed availability-evidence enum.
- [x] Publish the machine-readable profile-invariance/determinism contract: semantic row/control/
      capability/hash equality is mandatory across execution profiles; Parquet byte equality is
      mandatory only with a fully pinned writer.
- [x] Generate deterministic Python, Go and TypeScript row types from `schema.yaml`; keep browser
      int64 values as decimal strings to avoid JavaScript precision loss and verify generated
      artifacts in the cross-platform contract command.

**2.2 Landing and Gate A**
- [x] Accept and pin the immutable Phase-2 input `run-34b0ff729c8abe09`, config hash
      `3abbb96147c99c55e36e989a6eb6ba79305aab2caf0e1aa0cc200c1521853728` and manifest-file
      SHA-256 `9edb5a7b5d931cd43a0333ce156404c93b0caa2c6b448e33d398e8425003598b`
      (generator `0.12.0`, source contract `retail-source-config/v11`, profile
      `ultra-performance`). The promoted manifest confirms the pre-generation config hash and
      run ID. Acceptance measured: 137 logical datasets; 8,644 manifest objects
      (8,395 public source Parquet + 245 restricted `_truth` Parquet + 3 public generator
      metadata + 1 restricted all-source DuckDB) all re-verified by byte count and SHA-256 with
      zero failures over 16.00 GiB; 253,192,804 source/truth rows; 16.10 GiB run folder;
      10,687,361,024-byte DuckDB mirror; DuckDB catalogs reconcile to the manifest with zero
      mismatch and zero public `_truth` leakage; INR 4,827,543 orders / 12,395,915 units and
      USD 4,720,243 orders / 12,764,658 units; fill rate 0.972567 (IN 0.980525, US 0.964961);
      4,430.1 s elapsed at 13.8-GiB peak parent RSS. Never select “latest” or silently
      regenerate with another seed. `run-b8c4cceba05eb61a` is benchmark evidence only and
      `run-98abf242ff98ddc0` remains ineligible; neither is the Phase-2 input.
- [x] Land that exact run folder into immutable raw snapshot
      `dafa9d4228181c25a3562fef0362317f52675a6013669134285247e6179de5b4`.
      All 8,644 objects were streamed through byte/SHA-256 verification; the landing records
      8,398 public objects, 245 restricted truth objects and one restricted mirror.
- [x] Immutable raw landing with landing time, content hashes and idempotent replay; land public
      source objects and restricted `_truth`/all-source DuckDB into separate permission lanes.
- [x] Implement and small-fixture-test cross-platform immutable landing: streaming byte/SHA-256
      verification, ingestion-owned RFC-8785 snapshot identity, native-ID reuse detection,
      Windows-portable paths, atomic promotion and physically separate public, restricted-truth
      and restricted-mirror roots. The full pin and a second idempotent replay are verified.
- [x] Accept datagen/retailer-provided manifests when present; otherwise build the ingestion
      manifest, coverage inventory, controls and hashes from landed data/profile.
- [x] Gate A validates files/objects, parseability, source keys, extract window, resolved mapping
      references, input/filter/reject totals and any authenticity evidence the profile requires.
- [x] Keep physical format in a shared reader layer rather than source semantics; support
      Parquet, CSV, JSONL and JSON without demanding one format from every retailer.
- [x] Ordinary ingestion reads public source objects only. The all-source `source-run.duckdb` is
      oracle/evaluation-admin only and is never an ingestion input: filtering `restricted=false`
      in application code is a logical filter, not a permission boundary, because any process that
      can open the file can query `_truth`. If DuckDB speed is wanted, build an ingestion-owned
      **public-only** DuckDB cache from landed public Parquet as an optional derived artifact that
      records authoritative Parquet lineage and never becomes the lineage authority.

**2.3 Profiles, adapters and staging**
- [x] Implement the reusable M5-style boundary as a format-neutral reader catalog plus
      profile-declared path/key/grain policies. File type never selects business semantics.
- [x] Implement bounded Shopify, Business Central and companion-source adapters; all end at the
      same versioned staging envelopes.
- [x] Profiles declare currency/minor unit, tax basis, business timezone/day, source grain,
      market/location mapping, timestamp evidence and derivation rules.
- [x] Derive `observed_at` from trusted source timestamps or immutable landing time; create
      explicit versions from deterministic snapshot/event differences only for versioned
      cumulative/correctable facts; record provenance.
- [x] Quarantine ambiguous keys, timestamps or semantics instead of manufacturing facts.
- [x] Use the stable profile filename `retail_datagen.yaml`; keep `profileVersion` and
      `sourceSchemaVersion` inside the document so ordinary contract evolution does not create
      version-numbered filenames.

**2.4 Source-neutral transformations and Gate B**
- [x] Build source-neutral transforms for joins/version selection; timezone/business-day;
      local-currency integer minor units; inclusive/exclusive tax; quantities; fulfilled sales;
      adjustments; aggregation and inventory snapshots.
- [x] Map all calendar/event/weather/local-event/macro/promotion/competitor targets to
      market-qualified `geo_scope_*` or structured promotion applicability and prove
      `india/west` cannot join `us/west`.
- [x] Map Shopify `shopMoney` to operating-currency sales and retain `presentmentMoney` as
      raw/staging audit evidence; quarantine unsupported mismatches.
- [x] Implement shared `merch_scope_*` reference validation/precedence for supplier and promotion
      rows, supplier lane/origin resolution, and FX conversion using the exact shared contract.
- [x] Build approved runtime mappings for product, store, warehouse, market and supplier keys.
- [x] Attach source/profile/adapter/transform lineage and entity-specific `known_as_of`.
- [x] Gate B validates schema/grain/keys, PIT, provenance, exact per-currency money controls,
      source-to-canonical reconciliation, capability dependencies, inventory invariants and
      referential integrity; reject divergent duplicate observations, unqualified/cross-market
      scopes, unsupported sales-currency mismatches and ambiguous supplier terms.
- [x] In B01, interpret `required` as column/key presence independently from `nullable`.
      Add a canonical supplier fixture where `from_location_id` is present and NULL: it must pass
      as an unmodelled external origin. The same fixture with the column absent must fail. Reuse
      this distinction for every required-nullable field; never implement B01 as blanket
      `required ⇒ non-null`.
- [x] Reason-coded quarantine; atomically publish only Gate-B-approved curated
      Parquet/DuckDB.
- [x] Put direct canonical unit fixtures under ingestion/contract tests, never `datagen/`.

**2.5 Acceptance tiers**
- [x] Core round-trip: generated Shopify + BC + companion sources reconstruct the forecast/
      revenue-pricing canonical slice and pass the required Gate-B capability mask.
- [x] Partial-source test: Shopify alone produces an honest `validated_partial` result and never
      reaches `ml/`.
- [x] Benchmark the full pin by stage (wall time, rows scanned and output bytes) and retain the
      accepted report; incremental-month pruning measurement remains Phase-3 operational
      hardening once rolling refresh semantics exist.
- [x] Apply the shared execution-profile contract to ingestion scan workers, transform workers,
      DuckDB threads, memory/spill ceilings and partition-write concurrency. Prove safe and
      ultra-performance profiles produce identical accepted/quarantined row sets, controls, hashes
      and Gate A/B outcomes; use the common Python resolver rather than an ingestion-only parser.
- [x] Freeze common API envelopes plus Data Management/quality read models; scaffold `api/` with
      a pinned `github.com/nilshah80/aarv` dependency and implement the initial read-only Go API
      slice over ingest runs, source coverage, reconciliation and quarantine. Keep handlers thin
      and the `contracts/` OpenAPI/read-model definitions authoritative.
- [~] The initial React screen is connected to the live Phase-2 API without fake fallback values,
      but it is not an accepted UI implementation. Replace its invented dark control-room layout
      only after the reviewed parity/data matrices below are approved; do not patch individual
      colors or labels onto the rejected structure.
- [ ] Freeze the **Data Management parity matrix** from the original `#dataManagement` page:
      title `Data Management`, subtitle `Monitor source systems, data freshness and data quality`;
      five KPI positions/labels (`Data Freshness`, `Quality Score`, `Connected Sources`,
      `Rejected Records`, `Last Refresh`); and source table columns (`Source`, `Type`,
      `Last Refresh`, `Records`, `Quality`, `Status`, `Action`). The three approved toolbar
      buttons may remain omitted.
- [ ] Define and review exact live computations for those five KPIs before implementation:
      freshness observation/cutoff and denominator; quality-score formula and rule weighting;
      connected-source grain; rejected/quarantined record count and scope; and last-refresh
      timestamp/relative-time policy. Define source-table row grain, record counts, quality and
      status from accepted evidence. Do not map source-dataset count, canonical-entity count,
      curated-object count or capability count into unrelated original labels.
- [ ] Extend the Data Management OpenAPI/read model only where the reviewed original data points
      require it. Preserve Gate A/B, reconciliation, capability and fingerprint evidence in the
      API/Swagger and tests; do not force those engineering panels into the reference business
      page when the HTML does not contain them.
- [ ] Rebuild the shared shell to HTML parity before rebuilding Data Management: all reference
      navigation groups/items and inventory/replenishment submenus in their original order;
      exact topbar title/subtitle plus Channel, Date, Store, Currency, FX and notification
      controls; display-currency strip; original content spacing; seven bottom KPI slots; and
      original page-footer copy. User card/User Management navigation/destination is the only current user
      exception.
- [ ] Populate the bottom KPIs (`Total SKUs`, `Active SKUs`, `Stores`, `Channels`,
      `Forecast Coverage`, `Data Freshness`, `Model Accuracy`) only from reviewed live
      definitions. Before forecast models exist, do not show mock `Forecast Coverage` or `Model
      Accuracy`; agree the unavailable presentation without adding phase labels or fabricated
      values.
- [ ] **Demo 2A parity gate:** live landing/source evidence is represented only through the
      reviewed original Data Management KPI/table vocabulary; shared chrome matches the HTML
      screenshot/DOM baseline.
- [ ] **Demo 2B parity gate:** live quality, rejection and source-status values reconcile to API
      evidence and every visible number has a tested definition; no source hashes or Gate jargon
      are inserted into the business page.
- [ ] **Demo 2C / UI exit:** Data Management plus shared top/left/bottom shell pass desktop and
      responsive parity screenshots, DOM/text/column assertions, live-data tests and explicit
      human visual approval. The evaluation-admin oracle remains test-only.
- [~] **Phase-2 exit:** ingestion, exact controls and source-neutral transforms are implemented;
      the corrected ten-year curated republish and the UI parity exit below remain before the
      phase is demo-complete.
- [x] Correct the Phase-2 semantic defects found in the deep review: derive realized sales from
      successful fulfillment lines; reconcile sales units to `sales_fulfillments`; publish
      physical returns separately from successful financial refunds; use the closed minor-unit
      map without silent rounding; remove binary-float WAC; pin DuckDB UTC and preserve
      market-local business dates; reconcile source ATP; and split current on-order/in-transit
      units from inbound status.
- [ ] Republish the accepted ten-year pin with Shopify/BC adapter v1.1 and transform v1.2, retain
      the new Gate/publication evidence, and only then update the API/UI accepted-evidence paths.
      The disposable validation candidate in `/private/tmp` proves the code but is not a durable
      accepted publication.

**Post-exit evaluation extensions — useful, but not Phase-3 blockers**
- [x] Add golden collision fixtures for the literal region label `West` in India and US,
      similarly named cities, scoped promotions and competitor observations. Gate B already
      enforces market-qualified geographic scope and the accepted pin proves market-wide Diwali;
      this item adds adversarial fixture depth.
- [x] Add the evaluation-admin-only, profile-versioned generator hidden-control → canonical
      expected-control oracle. Production transforms, ordinary acceptance and datagen must never
      import it.
- [x] Add extension fixtures for webhook/HMAC parity and exhaustive fulfillment/return/refund
      status histories. The PoC source pin already covers inventory states,
      receipts/inbound/batches/suppliers, promotions and competitor matching; these fixtures are
      deliberately not required for the core Data Management/revenue/demand publication.

## Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)
- [x] Land Go/Python `semantic-fingerprint/v1` parity against the shared RFC-8785 golden
      vectors before Phase 3 emits fingerprinted artifacts.
- [ ] Resolve the accepted publication's B21 `LANDING_BACKFILL_DEPENDENCY` before enabling
      point-in-time training. Either ingest native/versioned availability observations for the
      affected historical sales-zero, assortment, price and supplier facts, or explicitly scope
      the first model to the already-available non-PIT demand capability. Never relabel business
      effective dates or landing-time backfills as historically PIT-accurate.
- [ ] Start MLflow run/metric/artifact tracking with the first deterministic demand
      training/backtest. A local file-backed store is sufficient in Phase 3; do not require
      PostgreSQL, a shared MLflow server or Docker Compose for the initial model slice.
- [ ] Run feature construction, one deterministic training/backtest fixture and artifact
      publication on Windows, macOS and Linux using supported pinned ML wheels. Require identical
      keys/features/acceptance decisions and declared numeric tolerances for model outputs; use
      bounded portable worker startup rather than relying on `fork`.
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
- [ ] Before Demand Forecast React work, freeze the parity/data matrix from the original
      `#demandForecast` page: preserve its toolbar/search/filter positions, KPI labels/order,
      Forecast vs Actual and driver/quality panels, store-performance section, SKU/store forecast
      table columns/actions and common top/left/bottom shell. Map every visible value to the
      accepted forecast artifact grain and filter context.
- [ ] Build the Demand Forecast vertical slice as a faithful port of that reviewed HTML page,
      replacing only its sample values with accepted live P50/P90, accuracy, bias, confidence,
      actuals and drivers. Do not add Phase 3 badges, model-engineering cards or an alternative
      layout. Pass screenshot/DOM/data parity and human review before Demo 3.
- [ ] **Demo checkpoint 3 / exit:** acceptance gates pass; artifacts are fingerprinted and the
      HTML-faithful Demand Forecast screen renders live Mumbai + New York P50/P90, accuracy and
      drivers with no mock or relabelled values.

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
- [ ] Freeze reviewed parity/data matrices for the original Inventory Overview and its Store
      Inventory, Warehouse Inventory, Inventory Ageing, Stock Transfers, Inventory Valuation and
      Expiry & Waste submenu pages, plus Replenishment Planner and its Suggested Orders, Supplier
      Planning, Safety Stock, Allocation & Fulfillment and Exceptions submenu pages. Preserve
      every original KPI/table/control position and the common shell; map each value to
      location/warehouse/lane-scoped live evidence.
- [ ] Extend the read-only Go API and build those UI slices from their reviewed matrices with
      inventory, demand-at-risk, reorder, transfer and replenishment read models. Unavailable
      evidence follows the approved element-level unavailable behavior; it is not replaced by a
      new capability panel, phase message or fabricated zero.
- [ ] Require screenshot/DOM/data parity and human review for each Inventory/Replenishment page
      before it is included in Demo 4; one accepted page cannot be used as evidence for the other
      navigation destinations.
- [ ] **Demo checkpoint 4 / exit:** replay and policy holdout pass; Inventory and Replenishment
      screens preserve the original HTML and render live market/location-scoped outputs.

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
- [ ] Freeze separate reviewed parity/data matrices for the original Price Recommendations,
      Price Simulation, Competitor Monitor and Promotion Planner pages before extending their
      APIs. Preserve original navigation, filters, KPIs, tabs, charts, tables, action placement,
      currency formatting and common shell; map every revenue/margin/uplift/stock figure to a
      governed definition.
- [ ] Extend the read-only Go API and build each pricing page from its approved matrix, including
      market/department reason-coded `insufficient_evidence` through the agreed element-level
      empty/unavailable state. Do not redesign the page around capability metadata, expose Phase
      5 labels or synthesize margin when cost-as-of is unavailable.
- [ ] Require screenshot/DOM/data parity and human review for each Pricing/Competitor/Promotion
      page before Demo 5; exact local-currency symbols/formatting and global display-currency
      behavior are part of the acceptance test.
- [ ] **Demo checkpoint 5 / exit:** gates are enforced per market; every recommendation carries
      market/currency and is guardrail-valid; Pricing/Competitor/Promotion screens render live
      response-rich and sparse-evidence outcomes in the original UI; unavailable margin follows
      the reviewed presentation and is not synthesized.

## Phase 6 — Aarv-based Go API, workflow & governance (`api/`, `db/`)
- [ ] Keep [Aarv](https://github.com/nilshah80/aarv) limited to the HTTP boundary: pin exact core
      and optional plugin module versions, compose routing/binding/middleware/lifecycle there,
      and keep read models, workflow, fingerprints, execution profiles, guardrails and
      persistence in framework-neutral `internal/` packages. Framework-generated OpenAPI/docs
      may expose but never replace the contract under `contracts/`.
- [ ] Build and test the Aarv server on Windows, macOS and Linux: route/OpenAPI parity,
      middleware ordering, timeout/body/concurrency limits, database path handling, graceful
      shutdown and portable file locks. Use OS-specific signal adapters where needed; no
      POSIX-only signal, `flock`, path or shell assumption may sit in shared API code.
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
- [ ] Introduce PostgreSQL here for mutable approvals, overrides, recommendation state,
      idempotency, RBAC and audit. Keep immutable raw/curated/features in Parquet/DuckDB rather
      than moving the lake into PostgreSQL.
- [ ] Add Docker Compose at the Phase-6 integration checkpoint, when PostgreSQL, the shared MLflow
      tracking service, Aarv API and UI must run together. Do not containerize batch-only Phase-2
      work solely to create infrastructure early.
- [ ] Consolidate and harden the read-only Go API slices delivered in Phases 2–5; keep
      OpenAPI/proto contracts in `contracts/` and preserve their stub-to-live compatibility.
- [ ] Make pricing activation/recommendation market and currency explicit; keep consolidated
      reporting amounts separate from local recommendation amounts.
- [ ] Serve reporting conversions from the shared exact FX contract; never use Shopify
      presentment currency for recommendation math.
- [ ] Workflow/HITL: approvals, planner overrides (bounded + reason), idempotency, audit.
- [ ] Serve-time re-resolve and revalidate the same market policy as Python; staleness 409/503;
      RBAC/auth.
- [x] **Fingerprint parity** — Python & Go pass shared golden vectors; landed as a Phase-3
      prerequisite rather than being deferred to this hardening phase.
- [ ] Add approval/override, governance and audit interactions only at the controls/modals/actions
      defined by the original HTML parity matrices. If a required governance interaction has no
      reference location, obtain explicit UI approval before adding it; do not redesign accepted
      screens or expose implementation-phase language.
- [ ] **Demo checkpoint 6 / exit:** a planner reviews live demand/inventory/pricing evidence,
      approves or overrides a draft, and the UI shows the audit row; 409/503 and fingerprints pass.

## Phase 7 — UI completion and end-to-end integration (`ui/`)
- [ ] Run install, lint/typecheck, unit/component tests and production build on Windows, macOS and
      Linux through npm scripts only. Do not use Bash environment assignment, `/` path
      concatenation or case-only filename differences in UI tooling.
- [ ] Audit every original HTML navigation destination against a checked-in parity/data matrix;
      complete remaining core screens and shared responsive/accessibility behavior without
      redesigning accepted Phase-2–6 slices.
- [ ] Run a whole-application visual audit of the exact left navigation, topbar filters,
      currency strip, shared content widths, palette, typography, cards/tables, bottom KPI strip
      and footer across every screen. No page-specific implementation may drift the shared shell.
- [ ] Verify multi-currency (FX) display and explicit market/department
      `insufficient_evidence` pricing state across all relevant screens using the reviewed
      original element locations, not new global banners or phase cards.
- [ ] Wire interactive what-ifs (scenario/simulation) to the API.
- [ ] Build rich capture forms the mockup only stubs (§8.3).
- [ ] Remove all remaining core-screen sample/stub data and demo-only code paths. Navigation may
      not advertise phase numbers or implementation status.
- [ ] **Exit:** every Phase-2–6 core screen renders correctly defined live API data, matches the
      approved HTML screenshots/DOM contract and has explicit human visual acceptance.

## Phase 8 — Analytics, admin & hardening
- [ ] Freeze and implement parity/data matrices for the original Performance Insights, Reports &
      Exports, Alerts & Notifications, Data Management and Model Management destinations before
      adding their live analytics/admin data. User Management remains omitted until users/RBAC
      scope is explicitly reopened.
- [ ] Model registry / drift; alerts + data-freshness; data-source management; reports, rendered
      through those approved original screens rather than new admin layouts.
- [ ] Adoption metrics / performance insights (AI-vs-control cohort).
- [ ] Disclosure guardrails (projections not lift; observational elasticity; synthetic labelling).
- [ ] At least two client-shaped dialects proving config-only onboarding where existing transforms
      cover semantics; otherwise only a bounded versioned adapter, with no downstream changes.
- [ ] End-to-end acceptance run (ingest → serve) through all fail-closed gates.
- [ ] Run the small end-to-end smoke path from Windows, macOS and Linux developer hosts; the
      production-scale benchmark may run once on the designated machine, but its orchestration
      and artifact semantics must not be host-specific.
- [ ] **Exit:** full run passes; all screens live.
