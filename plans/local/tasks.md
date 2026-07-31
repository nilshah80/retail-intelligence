# Retail Intelligence — Local Tasks

_Companion to `plans/local/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_All tasks below are **local**, on generated synthetic data, shadow-only._
_Status reconciled 2026-07-30: Phases 1–3 reflect implemented evidence and explicit remaining
manual/human/evidence gates; Phases 4–8 remain future work unless a line says otherwise._

## Cross-phase UI and demo track `[START EARLY]`

- [x] UI framework decision #17 is implemented with React + Vite + TypeScript, TanStack
      Query/Table, Recharts and Zod. The rejected Phase-2 connectivity prototype has been replaced
      by the shared HTML-faithful shell used by Data Management and Demand Forecast.
- [~] Treat `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` as a strict,
      review-controlled UI contract—not visual inspiration. Preserve its application width,
      navy/light color system, typography hierarchy, left-navigation groups/order/icons/
      submenus, top title/subtitle and filter order, display-currency strip, page composition,
      labels, table columns, bottom KPI strip and branded footer. Any deviation requires explicit
      approval before implementation. Data Management and Demand Forecast are contracted; future
      screens must repeat the same freeze.
- [x] Record the only currently approved omissions: **Add Data Source**, **Upload Sample Data**
      and **Run Validation** may be omitted for now, and the sidebar user card/User Management
      navigation/destination may be omitted until users/RBAC are implemented. These exceptions do not permit
      changing any other navigation, header, content, footer, color or spacing contract.
- [~] Remove internal delivery language from the product UI: no “Phase 2”, “Phase 3”, “Phase 4”,
      “Phase 5”, “governed ingestion”, source snapshot hashes, implementation status or roadmap
      badges in the normal business experience. Keep such evidence in API/Swagger, tests,
      development diagnostics or a separately approved technical view. Current live screens pass;
      enforce this again for every future screen.
- [~] Before coding each page, produce a parity/data matrix with one row per visible HTML element:
      reference selector/text, required behavior, API field or governed calculation, canonical
      grain, filter context, unit/currency, time window, formatting, loading/error/empty behavior
      and implementation/test status. Data Management and Demand Forecast matrices are frozen;
      remaining destinations are future work.
- [~] Never reuse a nearby backend count under a reference UI label. Implement the exact business
      definition or mark the element unavailable in the reviewed data matrix; never invent,
      relabel or silently approximate data. Current screens pass; retain the rule for future work.
- [x] Build the shared HTML shell once before the next vertical slice: full left navigation,
      topbar filters, currency strip, common content container, seven-item footer KPI strip and
      page footer. Data Management and Demand Forecast reuse it; future phases may not redesign it.
- [~] Add automated parity gates: reference and React screenshots at agreed desktop and
      responsive viewports, DOM assertions for navigation/order/text/table columns, design-token
      assertions for the approved palette/layout, and API fixture assertions for every displayed
      value. Automated gates exist for Data Management and Demand Forecast; explicit human
      approval and equivalent future-screen gates remain.
- [~] Maintain internally versioned OpenAPI/read-model contracts and deterministic fixtures ahead
      of each backend capability. Fixtures are for tests only and cannot make a demo screen look
      live. A phase demo cannot claim a live capability until accepted artifacts are served by
      the read-only Go API and every visible value passes its data-map assertion.
- [~] Extend the thin read-only [Aarv](https://github.com/nilshah80/aarv)-based Go API and UI
      together in Phases 2–5; do not defer all API and UI work to Phases 6–7. Preserve one
      contract when a screen moves from test fixture to live data. Phase-2 Data Management and
      Phase-3 Demand Forecast code/data gates pass; explicit human approvals remain.
- [~] Keep incomplete destination pages non-demoable without altering or annotating the agreed
      navigation. Never fabricate unavailable metrics, pricing recommendations, margin or
      workflow state, and never place phase/roadmap labels beside future navigation items. Current
      navigation follows this rule; retain it as new pages land.
- [~] Run incremental demo checkpoints:
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
- [x] Give every implemented layer a narrow adapter from the resolved shared profile into its
      native engine. Datagen, ingestion scan/transform/write/DuckDB/memory, ML feature/fold/model
      and API goroutine/connection-pool adapters are complete. Keep future engine ownership and
      cleanup within its layer.
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
      boundary, Phase-2 unit and real isolated-wheel checks locally. Record decision #47; collect
      supported-OS evidence through developer-run commands, never repository CI.
- [x] Apply decision #47 to the Phase-2 local layers: the Aarv-based Go API uses
      `filepath` and portable lock/process primitives; React tooling uses cross-platform npm
      scripts; the shared developer entry point dispatches Python/Go/Node without Bash. Local
      Go race/unit/build and Node typecheck/test/build checks exist. Decision #61 and
      `contracts/validation-policy.yaml` prohibit adding those checks to repository CI now or
      later; future layers add portable developer commands when they land.
- [ ] At Phase-7/8 hardening, collect manual supported-OS evidence for every completed layer using
      `tools/dev.py` and component commands. Do not add GitHub Actions or another repository CI
      system. Evidence covers datagen and Config Builder tests, contract/code generation,
      execution, ingestion, ML native dependencies and deterministic small training fixture,
      database migration upgrade/downgrade, Aarv API and UI. Document any intentionally unsupported
      optional dependency and provide a portable fallback before acceptance.
- [~] Enforce the portable storage/process contract in review and tests: Phase-2
      manifests/catalogs use
      normalized `/` logical paths while I/O uses native `Path`/`filepath`; reject
      case-colliding and Windows-reserved names; normalize fingerprinted text to UTF-8/LF; use
      `tempfile` rather than `/tmp`; never require `fork`, `flock`, symlinks, mode bits or shell
      expansion; close files/readers/DuckDB connections before same-volume atomic replacement.
      ML and database serving code follow the same contract locally; manual supported-OS evidence
      and future layers remain.
- [x] Add and validate a root `.gitattributes` policy before more generated/API/UI code lands:
      contract/vector/generated source files use deterministic UTF-8/LF on every checkout, while
      Windows-native scripts are explicitly CRLF. Developer-run cross-platform checks verify code
      generation and fingerprints.
- [~] Emit per-stage wall time, peak RSS, CPU utilization, worker/thread counts, spill/temp bytes
      and output bytes in every layer. Datagen telemetry and its disposable safe/performance/
      ultra-performance benchmark are complete; ingestion and ML record stage evidence, while
      complete API saturation telemetry and future-layer benchmarks remain.

## Phase 1 — Config Builder and synthetic source generation `[FIRST]`

**1.1 Reuse audit and isolation**
- [x] Copy only compatible code from `../retail-synthetic-data-generator`; record reused,
      adapted and replaced modules.
- [x] Reuse/adapt only the portable primitives first: deterministic seed partitioning,
      source-native Shopify/Business Central ID formats and namespaces, atomic
      checkpoint/replace, checksumming/manifest logic and the CLI/logging shell where compatible.
      Replace mutable counter-based ID allocation with stable-key allocation.
- [~] Run the full datagen unit/config-builder/pack-contract suite plus a small deterministic
      CSV/Parquet/DuckDB generation fixture on `windows-latest`, `ubuntu-latest` and
      `macos-latest`. Verify native virtualenv entry points, multiprocessing startup, worker
      cleanup, handle closure before promotion, logical-path/hash equality and browser YAML/JSON
      round-trip parity. Do not mark Phase 1 cross-platform complete from wheel-import checks
      alone. **macOS third done 2026-07-31**: full datagen suite passes (52 tests, 8 subtests,
      130s) on macOS 26.5 / Darwin arm64 with the native `datagen/.venv` entry point.
      **Static portability audit done 2026-07-31; one hard Windows blocker found and fixed.**
      `generator.py` imported the POSIX-only `resource` module at module scope, so on Windows the
      import alone would raise `ModuleNotFoundError` and datagen would not run at all. Replaced by
      `datagen/src/retail_datagen/process_usage.py`: the POSIX reading is byte-identical (asserted
      against `getrusage` directly, including the macOS-bytes vs Linux-kibibytes `ru_maxrss`
      difference) and Windows uses stdlib `ctypes` against `GetProcessMemoryInfo` and
      `GetProcessTimes`, adding no dependency. Suite still 52 passed, 8 subtests after the change.
      The rest of the audit is clean: no POSIX signals or `fork`, no `shell=True` or `/bin/sh`, no
      hardcoded POSIX paths, no symlinks, no case-colliding tracked filenames, `.gitattributes`
      normalises all text to LF with CRLF reserved for `.bat`/`.cmd`, the CSV writer sets
      `encoding` and `newline` explicitly, and both `tools/dev.py` and `tools/check_isolated_wheels.py`
      resolve `Scripts/python.exe` when `os.name == "nt"`. The Go tree has no build tags or syscalls.
      **Linux risk is now low on evidence, not assumption:** the three real macOS/Linux divergences
      are checkable statically and all check out — no case collisions (the APFS-insensitive vs
      ext4-sensitive hazard), no BSD-vs-GNU CLI dependence, and `ProcessPoolExecutor` already runs
      under macOS's `spawn` default, which is the stricter start method Windows also uses, so worker
      payload picklability is proven and Linux's `fork` default is the more permissive path.
      **STILL OPEN — a static audit is not a run.** It cannot catch behavioural divergence, and
      decision #61 forbids repository CI, so actual Windows and Linux suite runs stay open. Same
      blocker as the Phase 3 manual Windows/Linux portability rows.
- [x] Redesign the old `RunContext`/run identity, domain checkpoint state, writer dataset
      contract, controller orchestration and CLI commands against the new generator-owned
      config and source-data specification. Replace wall-clock-derived run identity with the
      content-derived identity in §9.3 before publishing reproducible runs.
- [x] Do not port the old `IdFactory.canonical`, `features/ml_ready`,
      `crossSystemMapping`, `analyticalExtension`, `mlReady` or fixed authoritative
      `retail.duckdb` publication contract. Hidden truth remains restricted and source-shaped
      Shopify/Business Central/companion publications are authoritative.
- [x] Give `datagen/` its own dependency file and generator-owned scenario/source schemas.
- [x] Resolve Python environment topology decision #38: datagen, ingestion, ML and database
      tooling use isolated environments/distributions, with contracts and execution shared only
      through independently installable packages.
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
- [~] Run equivalent full ten-year v0.11.0 safe and performance measurements only when two
      additional ~19-GB disposable outputs and multi-hour runs are scheduled. The 90-day parity
      benchmark already proves logical equivalence; this is optional performance evidence, not a
      blocker to using the accepted v0.12.0/v11 source run. **DECLINED 2026-07-31**: the source
      pin in use is v0.13.0/v12, so v0.11.0 performance numbers would describe a superseded
      generator. Two ~19-GB disposable outputs and multi-hour runs buy no evidence about the
      accepted pin. Reopen only if v0.11.0 is ever reinstated.
- [x] Rebaseline the Phase-3 forecast input on generator v0.13.0/source contract v12 without
      weakening acceptance gates. Publish native effective-dated `storeAssortment.observedAt`,
      expand the ten-year demo to 72 SKUs per department per market (1,440 total), generate the
      immutable `run-c5eb1506ecd4c550`, then require Gate A, Gate B, exact reconciliation and a
      reviewed pin before replacing v0.12.0/v11. Snapshot `681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b`
      and publication fingerprint `db3784fdcc4cb8334c2e17d6ae7e0216d05597659df4e9565a99f2b21b8d6fff`
      pass the ten-check ML bundle verifier.
- [x] Shopify, BC and companion outputs land successfully in Phase 2; the immutable v12 source
      pin passes landing, both gates and curated publication.
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
- [x] Accept and pin the immutable Phase-2 input `run-c5eb1506ecd4c550`, config hash
      `ae0f74be19d850079934ee8f87858d10b46ac9d3ec93baea8e97a58b989f57e9` and manifest-file
      SHA-256 `3ca63c09ce220c1606a1c73b6d1c8a74268cf437cc1ab620fcd49776747665a9`
      (generator `0.13.0`, source contract `retail-source-config/v12`, profile
      `performance`). The promoted manifest confirms the pre-generation config hash and run ID.
      Acceptance measured: 137 logical datasets; 8,726 manifest objects
      (8,477 public source Parquet + 245 restricted `_truth` Parquet + 3 public generator
      metadata + 1 restricted all-source DuckDB) all re-verified by byte count and SHA-256 with
      zero failures; 252,864,055 source/truth rows; 16,521,861,406 published object bytes;
      10,341,855,232-byte DuckDB mirror; DuckDB catalogs reconcile to the manifest with zero
      mismatch and zero public `_truth` leakage; INR 4,590,902 orders / 11,354,448 units and
      USD 4,209,420 orders / 8,917,814 units; fill rate 0.976855;
      4,594.755 s elapsed at 13,915,750,400-byte peak process RSS. Never select “latest” or silently
      regenerate with another seed. `run-b8c4cceba05eb61a` is benchmark evidence only and
      `run-98abf242ff98ddc0` remains ineligible; neither is the Phase-2 input.
- [x] Land that exact run folder into immutable raw snapshot
      `681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b`.
      All 8,726 objects were streamed through byte/SHA-256 verification; the landing records
      8,480 public objects, 245 restricted truth objects and one restricted mirror.
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
- [x] Replace the initial React connectivity prototype with the original HTML shell and
      Data Management composition, backed only by the live Phase-2 API and without fallback
      values.
- [x] Freeze the **Data Management parity matrix** from the original `#dataManagement` page:
      title `Data Management`, subtitle `Monitor source systems, data freshness and data quality`;
      five KPI positions/labels (`Data Freshness`, `Quality Score`, `Connected Sources`,
      `Rejected Records`, `Last Refresh`); and source table columns (`Source`, `Type`,
      `Last Refresh`, `Records`, `Quality`, `Status`, `Action`). The three approved toolbar
      buttons may remain omitted.
- [x] Define and review exact live computations for those five KPIs before implementation:
      freshness observation/cutoff and denominator; quality-score formula and rule weighting;
      connected-source grain; rejected/quarantined record count and scope; and last-refresh
      timestamp/relative-time policy. Define source-table row grain, record counts, quality and
      status from accepted evidence. Do not map source-dataset count, canonical-entity count,
      curated-object count or capability count into unrelated original labels.
- [x] Extend the Data Management OpenAPI/read model only where the reviewed original data points
      require it. Preserve Gate A/B, reconciliation, capability and fingerprint evidence in the
      API/Swagger and tests; do not force those engineering panels into the reference business
      page when the HTML does not contain them.
- [x] Rebuild the shared shell to HTML parity before rebuilding Data Management: all reference
      navigation groups/items and inventory/replenishment submenus in their original order;
      exact topbar title/subtitle plus Channel, Date, Store, Currency, FX and notification
      controls; display-currency strip; original content spacing; seven bottom KPI slots; and
      original page-footer copy. User card/User Management navigation/destination is the only current user
      exception.
- [x] Normalize the retained source-native `india-mumbai` identity through the datagen adapter
      profile to canonical market `india-west`; retain `us-new-york`. Expose Mumbai Bandra, Pune
      Koregaon Park, Brooklyn and Manhattan as four market-qualified stores, keep native channel
      instances internal, expose only `E-commerce` and `Store` as the two global channel types,
      and prove Store + Channel selections intersect (for example Pune Koregaon Park +
      E-commerce). Footer `Channels` counts distinct channel types and therefore equals 2.
- [x] Populate the bottom KPIs (`Total SKUs`, `Active SKUs`, `Stores`, `Channels`,
      `Forecast Coverage`, `Data Freshness`, `Model Accuracy`) only from reviewed live
      definitions. Before forecast models exist, do not show mock `Forecast Coverage` or `Model
      Accuracy`; agree the unavailable presentation without adding phase labels or fabricated
      values.
- [x] Implement the original `Multi-Currency Configuration` FX modal from accepted,
      as-of-dated `fx_rates` controls. Preserve rates as exact decimal strings, state the
      local/base → reporting-currency direction, and never substitute the original fixed demo
      rates. Cross-screen monetary conversion remains owned by the later reporting/API and UI
      integration tasks.
- [x] **Demo 2A parity gate:** live landing/source evidence is represented only through the
      reviewed original Data Management KPI/table vocabulary; shared chrome matches the HTML
      screenshot/DOM baseline.
- [x] **Demo 2B parity gate:** live quality, rejection and source-status values reconcile to API
      evidence and every visible number has a tested definition; no source hashes or Gate jargon
      are inserted into the business page.
- [~] **Demo 2C / UI exit:** Data Management plus shared top/left/bottom shell pass desktop and
      responsive parity screenshots, DOM/text/column assertions, live-data tests and explicit
      human visual approval. Automated checks and side-by-side renders pass; final human visual
      approval remains. The evaluation-admin oracle remains test-only.
- [~] **Phase-2 exit:** ingestion, exact controls and source-neutral transforms are implemented;
      the corrected ten-year curated republish is accepted. Final human approval of the UI parity
      exit remains before the phase is demo-complete.
- [x] Correct the Phase-2 semantic defects found in the deep review: derive realized sales from
      successful fulfillment lines; reconcile sales units to `sales_fulfillments`; publish
      physical returns separately from successful financial refunds; use the closed minor-unit
      map without silent rounding; remove binary-float WAC; pin DuckDB UTC and preserve
      market-local business dates; reconcile source ATP; and split current on-order/in-transit
      units from inbound status.
- [x] Republish the accepted ten-year pin with Shopify/BC adapter v1.1 and transform v1.2, retain
      the new Gate/publication evidence, and only then update the API/UI accepted-evidence paths.
      The durable accepted publication and retained evidence now post-date the corrected code;
      rebuildable staging/candidate work and superseded publication copies were removed.

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
- [x] Scope the first diagnostic model to the accepted `demand_forecast_non_pit` capability.
      Every run must
      declare `pitEligible: false` + `LANDING_BACKFILL_DEPENDENCY`; never relabel business
      effective dates or landing-time backfills as historically PIT-accurate.
- [x] Complete the selected origin-safe target-availability follow-on: generate and ingest the v12 source run
      with native effective-dated assortment observations; prove materialized zero labels become
      available only after local business-day close; freeze a new immutable input pin; then
      rebuild features and rerun the 13-origin H1 diagnostic before the full H1–H26 battery.
      Do not claim the broader `point_in_time_forecasting` capability if unrelated core entities
      remain landing-backfilled.
- [x] Verify the immutable ML input bundle against `contracts/ml/expected-pin.json` before opening
      data: recompute Gate A/Gate B/publication fingerprints, require both gates to pass, verify
      retained evidence and all publication object/DuckDB hashes, bind Gate B/publication masks,
      and require `demand_forecast_non_pit`.
- [x] Start MLflow run/metric/artifact tracking with the first deterministic demand
      training/backtest. The initial candidate used the governed local file store; decision #63
      now brings a shared MLflow 3.14.0 server and PostgreSQL into the Phase 3 serving stack through
      Docker Desktop. Repoint future runs to `MLFLOW_TRACKING_URI` without changing run identity;
      tracking URI and run id remain excluded from semantic fingerprints.
- [~] Run feature construction, one deterministic training/backtest fixture and artifact
      publication manually on Windows, macOS and Linux using supported pinned ML wheels. Require
      identical keys/features/acceptance decisions and declared numeric tolerances for model
      outputs; use bounded portable worker startup rather than relying on `fork`. Do not add
      repository CI; decision #61 makes developer-run evidence authoritative.
- [x] Implement ML execution profiles for feature-build workers, rolling-origin/fold workers,
      market/model workers, threads per model, memory ceilings and spill/cache paths. Schedule
      independent markets, series groups and backtest folds concurrently without multiplying
      nested thread pools beyond the resolved CPU/memory budget; consume the same common Python
      resolver used by datagen and ingestion.
- [x] Separate execution tuning from feature/model/policy specifications and artifact identity.
      Fix every RNG seed; enable deterministic trainer settings; require equivalent features,
      predictions, metrics, SHAP group totals and acceptance decisions across safe and
      ultra-performance profiles (byte-identical artifacts where the library supports it, otherwise
      declared numeric tolerances).
- [~] Record stage-level ML telemetry and benchmark the full pinned-data feature build,
      rolling-origin backtest and training run on both the 16-GB-available demo profile and a
      high-performance profile. Fail closed on OOM risk and fall back to bounded batching rather
      than silently reducing horizons, markets, series or validation folds.
- [x] Characterize the retained curated demand series before fitting: lifecycle stages,
      holiday/event peak ratios, weekly zero share, overdispersion and autocorrelation. Treat these
      as model-routing/evaluation evidence, not as a reason to regenerate the pinned source run.
- [x] Weekly non-PIT feature build with origin-safe labels and external drivers. Promotion features
      are unavailable on this pin and must remain absent from the model matrix.
- [x] Join market-local calendars by market/calendar key; add `market_id` (no derived `country`)
      and use
      dimensionless or local-normalized prices rather than raw cross-currency levels.
- [x] Join weather/event/market-disruption/macro/competitor features only by `market_id` plus
      resolved `geo_scope_*`; enforce `contracts/ml/driver-semantics.yaml`, explicit future
      fallback/missingness, and no unqualified region-only join.
- [x] LightGBM horizon-quantile P50/P90, **horizons → 26 wk**; Croston routing.
- [x] Baselines + FVA; metrics WAPE / bias / `accuracy = 100·(1−WAPE)`.
- [x] Run the fixed rolling-origin schedule (26-week window, step 2, 13 scoring origins,
      104 training origins) and all five acceptance gates: ≥25% WAPE improvement over
      seasonal-naive, P90 coverage 0.85–0.95, slow-mover WAPE no worse than seasonal-naive,
      P90 ≥ P50 row-wise, and no supported-market failure hidden by the global result.
      The v11 H1 diagnostic remains a rejected baseline. The former v12 forecast is structurally
      incompatible with the repaired policy/verifier and is unservable; do not claim that its old
      bundle was independently recomputed. Review #2 also rejects
      `fr_92135aa7b5215b69`: its 53.47% seasonal-naive improvement uses 605,904 paired rows while
      dropping 102,804 harder champion rows, so acceptance-v2 fails the complete-overall A1
      comparison globally and in both markets. No forecast is currently authorized.
- [x] Store filter-scoped metrics as additive `abs_error_sum`, `signed_error_sum`, `actual_sum`,
      `coverage_hits`, `n`; prove every fixed pre-aggregate equals SUM-then-divide results.
- [x] Publish per-market WAPE/bias/P50/P90 coverage and require supported-market gates so a large
      market cannot hide a failure elsewhere; calibrate per market when evidence is sufficient.
- [x] Publish `forecast_versions`, SHAP `forecast_drivers` (+ competitor/weather groups),
      confidence and the seven evaluation/governance artifacts in one accepted immutable bundle.
- [x] Extend the read-only Go API with versioned forecast-series, horizon, metric, confidence and
      driver endpoints; keep market/currency/config fingerprints explicit. Per decision #62,
      request handlers never scan Parquet: first verify all ten immutable run artifacts, load the
      serving projection transactionally through the Alembic-owned PostgreSQL schema, then create
      a separate activation record. The Go repository serves only the lineage-matching active
      version; accepted-but-unmaterialized and accepted-but-inactive states remain governed 503s.
      PostgreSQL 17.10 and MLflow 3.14.0 run under Docker Desktop Compose. Stale publication or
      superseded request-time activation lineage returns 409; missing, invalid, unmigrated or
      unavailable projection state returns 503. Only a future accepted run materialized under
      the currently implemented `retail-forecast-verifier/v3` policy may activate after migration
      0005; the finalized decision #82 requires acceptance-v3/verifier-v4 and migration 0006
      before the next candidate can activate.
- [x] Before Demand Forecast React work, freeze the parity/data matrix from the original
      `#demandForecast` page: preserve its toolbar/search/filter positions, KPI labels/order,
      Forecast vs Actual and driver/quality panels, store-performance section, SKU/store forecast
      table columns/actions and common top/left/bottom shell. Map every visible value to the
      accepted forecast artifact grain and filter context.
- [x] Build the Demand Forecast vertical slice as a faithful port of that reviewed HTML page,
      replacing only its sample values with accepted live P50/P90, accuracy, bias, confidence,
      actuals and drivers. Do not add Phase 3 badges, model-engineering cards or an alternative
      layout. Screenshot/DOM/live-data parity passes locally at 1440×1100 and 390×844; explicit
      user visual approval remains the PP3-P0 task-13 handoff.
- [x] Repair the Phase 3 publication trust boundary: both `publish_forecast_run` and
      `verify_forecast_run` independently recompute A1–A5 from the evaluation and
      seasonal-naive artifacts; a caller-supplied or re-signed false verdict fails closed.
- [x] Repair unavailable contextual feeds with `retail-weekly-features/v6`: preserve origin-observed
      `event_count_origin`, remove unavailable future calendar-event columns from the model/data
      contract, remove the false horizon-derived local-event availability indicator and its two
      permanently-null model columns, and remove the permanently-null market-disruption feature.
      Keep working-day availability independent and bind the Parquet descriptor into feature
      identity. The manifest declares calendar, local-event and disruption futures unavailable
      with reason codes. Build and consumer checks now reject every structurally all-null feature
      column. Behavioral tests and a full 1,072,430-row v6 build prove origin events across all
      523 origins, zero unavailable future-feed columns and zero all-null columns. The complete
      feed sweep is bound to expected-pin `run-c5eb1506ecd4c550` / `db3784fd…` / 1,509 objects:
      promotions 811, calendar events 182, local events 2,266 and disruptions 24 are unavailable;
      macro 7,306, competitor prices 300,611, weather actual 7,306, weather forecast 51,142 and
      calendar 7,306 retain origin-visible evidence.
- [x] Restore execution-profile feature invariance: deterministically round the three
      order-sensitive aggregate floats, bind the normalized feature SQL hash into semantic
      identity, and prove safe/performance Parquet objects have zero logical row differences.
- [x] Preserve missing lag-52 seasonal-naive predictions as unavailable and compute canonical
      pairing-key hashes instead of hardcoding `pairedRowsIdentical`. Acceptance-v2 publishes
      full, paired and dropped champion WAPE plus row/actual shares. Decision #81 requires a
      complete overall A1 comparison; any dropped row makes A1 fail rather than allowing a
      post-result floor.
- [x] Recompute decision-#12 confidence after intermittent/Croston routing changes P50/P90, and
      independently reject evaluation/current artifacts whose stored confidence is not reproduced
      from their own quantiles.
- [~] Restore spec §4.8 serving semantics: startup and request-time stale lineage map to 409;
      missing/invalid/unmaterialized state maps to 503. The API now asserts the exact migration
      revision before reading and workbench confidence uses decision #12's P50-weighted aggregate.
      Typed runtime-lineage and HTTP status-mapping tests pass; a router-level test that mutates
      an initially valid activation during a live request remains open.
- [x] Bind PostgreSQL materializations under the decision-#81 policy to
      `retail-forecast-verifier/v3`. Migration 0005
      excludes verifier-v2 materializations and prevents the rejected run from silently returning
      through old activation events. Code/tests and the local migration are applied. No accepted
      verifier-v3 materialization exists; finalized decision #82 requires verifier-v4/migration
      0006 rather than retrofitting v3/0005.
- [~] Make PostgreSQL integration prove first-call plus repeated-call idempotency. Repeated-call
      coverage is real, but the first-call assertion remains state-dependent and is an explicit
      open test-hardening item. Datagen, PostgreSQL, uncached Go race tests and UI remain in the
      developer-run gate; no repository CI is allowed. The gate no longer accepts a silent skip on
      the NO-GO branch: `tools/dev.py verify` runs in governed NO-GO mode, and both
      `ml/tests/test_serving_postgres.py::test_rejected_candidate_keeps_serving_fail_closed` and
      `api/internal/readmodel::TestForecastServesGovernedUnavailableOnNoGo` execute rather than
      skip, asserting an empty active view, refused materialization and a governed 503.
- [x] Build feature-schema-v6 characterization, run the full 13-origin H1–H26 backtest and publish
      current-cycle classifications plus an immutable forecast-run bundle. Completed 2026-07-31 as
      `retail-forecast-run/v3`: backtest `accepted: false`, current-cycle 52,884 rows / 2,034
      series, 643 exceptions, and the independently verified rejected candidate
      `fr_2f4c50d1d7717b23`. The v4/v5 builds
      were superseded after revealing false local-event availability and a dead disruption
      feature. The corrected v6 build is complete at semantic fingerprint
      `f3ff8725d36d78ff…`: 1,072,430 rows preserve origin event counts across all 523 origins,
      expose no unavailable future-feed or all-null columns and have a self-contained
      characterization summary in the reassessment evidence. The full backtest is intentionally
      blocked pending implementation of decision #82
      because decision #81's strict complete comparison cannot accept the unchanged short-history
      population. Publish/activate only if the decision-#82 acceptance/verifier authority
      concludes accepted; otherwise retain a rejected candidate and keep the API fail-closed.
- [x] Implement decided #82 before that rerun: use an origin-visible
      `forecast_origin × horizon × SeriesKey` lag-52 cohort with complete A1 pairing; place every
      other row in a cold-start cohort compared with the mean of its last
      `min(13, history_weeks)` complete origin-visible weeks; require at least one prior week and
      global/per-market non-inferiority with complete keys. On the historical v15 bundle, 102,804
      rows across 402 SeriesKeys move to the cold-start cohort; remeasure on v6 and never let a row
      disappear from both cohorts. Implemented in `ml/src/retail_ml/models/cohorts.py` and
      `models/backtest.py` as acceptance-v3 with `A1_established` and `A1_cold_start` gates, a
      total cohort partition with reason codes, canonical `forecast_origin × horizon × SeriesKey`
      key hashes, and A3 restricted to established-history slow movers.
- [x] Before the expensive v6 backtest, recompute decision #82's exact cold-start comparator as a
      cheap preflight. Done 2026-07-31 against feature-schema-v6: the established cohort passes
      everywhere (+53.47% global, +54.54% India, +52.00% US) but the cold-start cohort fails
      US New York at −2.93% (champion 0.3692 versus comparator 0.3586), worse than the MA13 proxy.
      A second independent blocker was measured: 54 `forecast_origin × SeriesKey` pairs (1,404
      rows) have no complete prior week, so the cold-start gate returns `insufficient_evidence`.
      Every one of those pairs has exactly one *partial* prior week and none has zero history, so
      #82's "complete origin-visible weeks" wording makes acceptance structurally unreachable —
      recorded as proposed decision #83, to be frozen before results are re-read. #82 is not
      retuned. See plan §3.1.1.
- [~] Re-run safe/high-performance invariance and the 16-GB memory evidence against the repaired
      feature/run semantics. The old feature-schema-v3 safe/performance builds were byte-identical
      at semantic fingerprint `1edd93f17b01fa8b…`, and its 16-GB spike passed at 7.148 GiB peak
      RSS, but neither is feature-schema-v6 acceptance evidence. Full v6 pinned-data
      safe/high-performance comparison and Windows/Linux evidence remain open.
- [x] Implement decision #82 as immutable acceptance-v3/verifier-v4 and v4-only migration 0006
      rather than mutating acceptance-v2/verifier-v3 or migration 0005. Contracts are implemented:
      acceptance-v3, `cohorted-seasonal-cold-start-recomputation/v4`, verifier-v4, migration
      0006 (v4-only active view) and `retail-forecast-run/v3` — the run envelope was bumped under
      invariant 11 because it now carries a fifth baseline (`cold_start_mean`) and cohorted
      acceptance; no bundle was ever published under run-v2, so nothing accepted is invalidated.
      Migration `0006_cohorted_verifier_v4` is applied; the live active view requires
      `retail-forecast-verifier/v4`. The full chain ran end to end on 2026-07-31: backtest →
      `score-current` (52,884 rows / 2,034 series / origin 2026-07-27) → `classify` (643
      exceptions, 2,034 quality rows) → `publish` → verify. Published immutable rejected candidate
      `fr_2f4c50d1d7717b23`, `lifecycleStatus: rejected`, semantic fingerprint
      `22e9e91d0018c1b7…`, ten artifacts, 3,543,540 baseline rows (five baselines including the new
      `cold_start_mean`). Verifier-v4 independently recomputed A1–A5 from bundle contents and
      matched the published document. The stateful `tools/dev.py verify` gate now runs in governed
      NO-GO mode against that candidate and **passed end to end** on macOS: contracts valid,
      migration 0006 applied, import boundaries clean (86 files), execution 12, contracts 90,
      datagen 52, ingestion 77, database 1, ML 79 (1 skipped), uncached Go race tests green, UI
      tests/typecheck/build green. The former green counts are historical verifier-v2 evidence and
      do not authorize a forecast.
- [~] **Demo checkpoint 3 / exit:** forecast authorization is **explicit NO-GO**, now on real
      evidence rather than pending work. Decision #82 is implemented and the complete v6 cohorted
      rerun finished 2026-07-31 with `accepted: false` (708,708 rows, 13 origins, 26 horizons,
      65,021,190 training rows, 2,074 s). The established-history cohort passes A1 everywhere
      (+53.48% global, +54.55% India, +52.03% US) and A2/A3/A4 pass, but the cold-start cohort
      returns `insufficient_evidence` in every scope because 1,820 launch-week rows have no
      comparator, which also masks a real −3.07% US New York non-inferiority deficit. A5 fails both
      markets. Proposed decision #83 must be frozen before those numbers are re-read. The historical screen rendered live
      verifier-v2 Mumbai + New York values, but visual
      parity is not yet approved: Forecast Health currently hides h8/h13 at the default four-week
      cap and uses cumulative labels/statuses that differ from the original four-row table.
      Visual approval must explicitly accept that deferred deviation or move its correction
      earlier. Manual Windows/Linux evidence and the full pinned-data 16-GB/high-performance
      benchmark comparison also remain open.
- [ ] If Phase 3 closes explicit NO-GO, still require decision-#82 implementation, the complete
      decision-#82
      verifier rejection/D0 record, stateful local gate, manual Windows/Linux evidence, v6
      safe/high-performance and memory evidence, empty active-version proof, governed API 503 and
      retrospective. UI approval then covers only the governed-unavailable state and must state
      that live four-row Forecast Health parity was not exercised or accepted and remains
      PP3-B7 work.

## Post–Phase 3 repository and artifact retention `[CROSS-WORKSTREAM RULE]`

- [ ] Keep schemas, contracts, policies, migrations, code, tests and small deterministic golden
      vectors in Git. Keep Parquet/DuckDB data, model binaries, MLflow artifacts, complete
      immutable bundles and all retailer extracts outside Git in the configured artifact root or
      object store.
- [ ] Treat generated report JSON as untracked by default. Commit only an explicitly reviewed
      compact evidence index needed for a decision, acceptance/no-go record or reproducibility
      handoff under `contracts/evidence/`; it must reference external artifacts by immutable
      path/URI, byte count, SHA-256 and semantic fingerprint. `ml/reports/` is generated-only and
      intentionally ignored.
- [x] Apply the current report disposition: remove the historical accepted-publication and
      serving-stack reports; temporarily retain the Review-#2 reassessment until PP3-P0 replaces
      it; redirect the `tools/dev.py` memory-report default to the ignored external-artifact tree,
      then remove the obsolete v3 memory and profile-invariance reports.
- [x] Record an interim external rejection/supersession ledger in the retained reassessment for v1
      runs
      `fr_b2f18d0e2999a36d`, `fr_ab5be7296a2c416e` and `fr_92135aa7b5215b69`. Preserve their
      original self-declared-accepted manifests and bytes; bind hashes and rejection reasons
      externally instead of rewriting/re-signing historical bundles. PP3-P0 must carry this
      inventory into its schema-governed compact acceptance/no-go index.
- [ ] Never commit retailer data, credentials, secrets or unminimized quarantine payloads.
      Superseded full evidence remains in artifact storage and is referenced by its replacement
      rather than copied forward into Git.

## Post–Phase 3 retailer-source onboarding hardening `[DEFERRED]`

**Do not start this work before the complete Phase 3 exit above.** The accepted synthetic source
publication remains valid input evidence for the demo pin; the former v12 forecast does not.
Neither is evidence that an arbitrary
retailer extract is retailer-ready. Decision #65 fixes the Track-A-first scope and staged
PP3-A1–A3 authorization boundary. Implementation still waits for Demo checkpoint 3 and explicit
go-ahead; these tasks do not change the Phase 3 acceptance result or make Track A a Phase 3
blocker.

- [ ] At the Phase 3 retrospective, record the PP3-A1–A3 implementation go-ahead under decided
      #65. Keep three claims separate: source data can be parsed, a
      capability-complete canonical publication can be produced, and the retailer has enough
      origin-safe/statistically sufficient evidence for a particular ML capability. Never infer
      the latter two from `retail_v2` schema conformance alone.
- [x] Produce the PP3-A1 coupling inventory and boundary allowlist (A-D1):
      `contracts/staging/role-map.yaml` plus `ingestion/tests/test_coupling_inventory.py` (10
      tests). Findings: 36 neutral relations (21 direct passthrough, 15 derived) all mapped;
      `dimension_signal` has **no runtime consumer** and is retired rather than decomposed;
      `transforms/core.py:851,1073` join `location_crosswalk` on the literal
      `x.source_system = 'companion'`, a prohibited-class violation the original §1.4 inventory
      missed, now frozen in a known-violation register that PP3-A3 must clear; `pandemicSignals`
      is a second `market_disruption` provider needing an explicit decision-#67 mode.
- [x] Inventory and remove platform coupling below the adapter boundary. The current staging
      builder and quarantine rules directly reference `shopify_*`, `bc_*` and `companion_*`
      relations; document every occurrence and replace it, if this workstream is approved, with
      source-neutral staging roles such as merchandise, fulfillment, products, locations, prices,
      inventory, receipts, assortment and contextual signals.
- [x] Produce both relation→role and role→provider/disposition maps. Preserve `channel` as a
      canonical transform derived from `merchandise.channel_source_key`, mark
      `allocation_supply` as supplied through
      `dimension_signal.entity_kind=allocationSupplyPools` until it becomes a typed role, and
      require every proposed role to name a v1 provider or an explicit `derived_in_transform`,
      `absent_in_demo_source` or rejected disposition.
- [x] Enumerate every accepted-pin `dimension_signal.entity_kind`, payload schema, provider, row
      count and consumer. Replace supported kinds with typed v2 roles and reconcile every typed
      role to the opaque v1 payload by complete business key/value; do not retain an untyped
      “other” escape hatch.
- [x] Implement the decided machine-readable standardized-staging role contract before
      refactoring. Define each role's grain, required/optional fields, types, money/time semantics,
      provenance fields, evidence-grade requirements and quarantine rules. Adapters publish role
      bindings; shared staging validation and canonical transforms consume roles and must not
      know the retailer or platform name.
- [x] **PP3-A3 done 2026-07-31.** Remove platform coupling from shared staging behaviour: nine
      hardcoded dialect literals cleared from `transforms/core.py` and `quality/gate_b.py`, the
      location crosswalk rebuilt from the standardized `location` role, and `source_system` added to
      the ten staged relations that omitted it despite `retail-staging/v1` requiring it. Full-snapshot
      parity is exact: publication, Gate-B, candidate and staging semantic fingerprints, all 21
      Gate-B rules, the capability mask, reconciliation, entity controls and all 36,224,122 canonical
      rows are identical to the accepted publication. Physical file layout differs (1,499 vs 1,509
      objects) which `determinism.yaml` makes secondary. See plan §1.4.1 and §1.4.2.
- [x] Move quarantine and staging-quality validation from platform table names to the frozen role
      schemas. Require the same invalid-row, money-precision, key, temporal and provenance checks
      for every adapter that supplies a role; a new adapter must not bypass or duplicate shared
      validation.
- [x] **PP3-A4 done 2026-07-31.** `contracts/adapters/mapped-files.schema.json` freezes the
      decision-#68 allowlist (10 operations, no loops/IO/dynamic SQL/uploaded code) and
      `ingestion/src/retail_ingestion/adapters/mapped_files.py` compiles it. 34 tests: a generic
      non-Shopify/non-BC retailer reaches `stage_data.merchandise` through configuration alone in
      all four formats with exact minor-unit money; negative fixtures cover unlisted operations,
      missing required role fields, unknown roles, path escape, unsupported formats,
      landing-time evidence without the capability downgrade, row filters without a reason code,
      SQL smuggled through a field name, value_map default branches, duplicate datasets, and
      money-precision quarantine that accounts for every row. Includes a dry-run report and a
      mapping fingerprint carried into staging lineage.
- [x] Implement the documented profile-driven `mapped_files` default adapter for client CSV,
      Parquet, JSONL and JSON drops whose semantics are fully expressible by approved mappings.
      Column renames and physical formats should require profile/mapping changes only, not a new
      platform adapter.
- [x] **PP3-A5 done 2026-07-31.** `contracts/adapters/adapter-manifest.schema.json` freezes the
      manifest; `ingestion/tests/fixtures/custom_ledger_adapter.py` is a deliberately different
      bounded adapter whose append-only header/line/revision ledger needs an ordering join and a
      status machine. 11 conformance tests prove the gap is real (the decision-#68 allowlist has no
      join, window or ordering operation), that it reaches `merchandise` with no downstream branch,
      that no Shopify/BC copy was needed, that it reuses shared helpers, that duplicate registration
      and external loading fail closed, that no adapter imports transforms/ML/API/UI, and that it
      cannot bypass required role or provenance fields.
- [x] Define and implement a versioned retailer-adapter extension path for semantics that cannot be
      expressed by `mapped_files`. Shopify and Business Central remain optional adapters, not
      prerequisites. A retailer ERP/WMS, custom commerce source or governed flat-file dialect may
      add one bounded adapter that emits standardized roles; it must not add retailer branches to
      shared transforms, ML, API or UI. Prefer shared mapping/normalization helpers over copied
      Shopify/BC adapter implementations.
- [x] **PP3-A5 done 2026-07-31.** Registration is static and deterministic; `loading` accepts only
      `static_in_repository_registry`, so a manifest declaring an entry point, plugin discovery, a
      pip package or a URL fails validation. Duplicate `sourceSystem` raises rather than replacing.
- [x] Implement decision #69's static in-repository adapter registration rules and conformance
      tests. Registration must declare
      source-system id, adapter version, supported source schema/profile versions, supplied roles
      and required source capabilities; duplicate ids or ambiguous role ownership fail closed.
      External/installable adapter plugins remain deferred.
- [x] **PP3-A6 done 2026-07-31.** `contracts/onboarding/temporal-evidence-policy.json` freezes the
      five grades, the never-availability field list and the nine capability definitions;
      `ingestion/src/retail_ingestion/readiness/evaluator.py` implements them. A business date used
      as availability does not merely downgrade — it **blocks** every replay-dependent capability,
      because a silently origin-unsafe capability is worse than an unavailable one.
- [x] Implement the decided retailer temporal-evidence policy and readiness report. For each
      canonical temporal entity, record the native observation/posted/extracted timestamp,
      immutable snapshot/CDC evidence or reviewed landing-time derivation, plus
      `known_as_of_evidence_grade`. Business effective dates never become historical availability
      by default; unsupported derivations
      quarantine or capability-downgrade.
- [x] **PP3-A6 done 2026-07-31.** Zero demand is derived from five conditions; any failure yields
      an `unknown` cell with one of six reason codes, never a zero. Negative fixtures cover
      incomplete extracts, unknown and inactive assortment, cutoff availability, partial boundary
      weeks, incomplete channel coverage, and a current-catalog backfill attempting to manufacture
      2018 history.
- [x] Treat zero demand as a derived fact requiring both extract completeness and
      SKU × store × channel assortment/listing coverage at the business date. Map native
      assortment, item-location, planogram, catalog snapshot, CDC or equivalent retailer evidence
      when available. If it is absent, do not manufacture historical zeros from a current catalog;
      report the affected replay/PIT capability as unavailable or collect evidence prospectively.
- [x] **PP3-A6 done 2026-07-31.** Nine capabilities each publish a readiness verdict
      (`ready`/`validated_partial`/`unavailable`/`blocked`) and a **separate** sufficiency verdict
      (`sufficient`/`insufficient_evidence`/`not_evaluated`), with role and evidence reason codes.
      `consumerMayProceed` requires both, so ready-but-insufficient and not-yet-evaluated are
      distinct reportable states rather than a pass. 20 tests.
- [x] Define capability-specific onboarding outcomes rather than one global "safe" flag: current
      descriptive analytics, current/non-PIT forecasting, origin-safe historical replay, broader
      point-in-time forecasting, inventory/replenishment and price/margin capabilities each publish
      their own dependency, coverage and evidence verdict. `validated_partial` stops before any
      consumer whose required capability is incomplete.
- [x] **PP3-A7 done 2026-07-31.** `contracts/onboarding/publication-selection.schema.json` plus
      `ingestion/src/retail_ingestion/readiness/selection.py`, 22 tests. Selection identity is
      content-addressed over retailer x tenant x capability x environment and the publication
      fingerprints; approval metadata is excluded so re-approving cannot mint a new selection.
      Authoring this surfaced a modelling error my own test caught: lifecycle state was inside
      identity, so approving a selection appeared to change *what* was selected. Split into a stable
      `selectionId` plus a per-event `lifecycle.recordId`, with `supersedes` chaining record ids.
      Resolution takes one explicit path and fails closed on absent, scope-mismatched, non-active,
      under-capable, insufficient or moved publications; an AST check proves no glob, scan or
      newest-wins path exists. Rollback emits new records and never edits history.
- [ ] **NOT DONE — the claim was premature and is corrected here.** Replace the single demo
      `contracts/ml/expected-pin.json` deployment assumption with a reviewed
      per-retailer/per-tenant publication-selection and pinning mechanism before
      multi-retailer use.
      The library contract exists and is tested: `resolve_selection()` checks scope,
      lifecycle, declared readiness and path existence, and `verify_against_publication()`
      checks the real publication fingerprint. But **neither has a caller outside its own
      definition**, and nor does `build_readiness_report()`. Features, training,
      publication, materialisation and activation all still resolve through
      `contracts/ml/expected-pin.json`, so the architectural onboarding boundary is
      designed and unit-tested, not operational. Marking this complete described the
      library rather than the runtime. Each selected publication must still pass the same Gate A/Gate B,
      reconciliation, capability, object-hash and lineage checks; changing retailer data must not
      require ML source-code changes.
- [x] **PP3-A8 done 2026-07-31, corrected 2026-07-31 after review.** Both fixtures exist and
      round-trip: a generic mapped-files retailer (renamed, reordered, DD/MM/YYYY CSV with a
      value-mapped channel) and the ledger-ERP custom adapter. 19 round-trip tests assert the
      *unchanged* half of the promise with a SHA-256 digest over every `.py`/`.go`/`.ts`/`.tsx`/`.sql`
      file in transforms, quality, ML, API and UI, plus a scan proving no retailer name leaked
      downstream and that both sources converge on one standardized column set. Negative paths:
      missing temporal evidence, ambiguous mapping, landing-only downgrade, absent assortment
      coverage, statistical insufficiency, mixed tenant lineage and an unregistered adapter.
      **The original claim was overstated and an external review was right to challenge it.** The
      tests drove `MappedFilesAdapter.materialize_staging` through a hand-built context, so they
      proved the adapter and not the pipeline. Driving the real `build_staging()` entrypoint found
      six couplings, each of which failed a mapped-files-only run *after* the retailer's rows were
      already staged:
      1. `_create_standardized_views` overwrote an adapter-supplied role with a view over the
         absent platform relation, discarding the retailer's data, and required dialect relations
         that a mapped-files source never has.
      2. `_build_quarantine` queried those same platform relations unconditionally.
      3. `contracts/profiles/profile.schema.json` is `additionalProperties: false` and had no
         `mappedFiles` key, so the adapter's own required mapping could not survive profile
         validation — the adapter was unreachable through the real entrypoint by construction, not
         merely untested. The frozen `roleCatalog` is now injected by the builder from
         `staging-v2.yaml` rather than accepted from the profile, so a retailer cannot redefine a
         platform role in a file they own.
      4. `build_location_crosswalk` read the generator's `source-run-manifest.json`
         unconditionally, despite a docstring promising retailers could replace the resolver. Now
         selected by a declared `locationResolution.mode`; absent still means `upstream_topology`,
         so a lost topology manifest cannot silently promote a retailer's keys to canonical
         identity.
      5. Its coverage check unioned thirteen consumer relations that no single retailer supplies;
         the union is now built from the relations that exist, and an empty union fails closed.
      6. The staging manifest required `upstreamManifest.sha256`, evidence about a generator run
         the retailer does not have. Now optional; `landingSemanticFingerprint` stays required.
      Neutral relation names are also no longer inferred: `relationRoleMap` in
      `contracts/staging/role-map.yaml` is read, so the `location` role is visible under the
      `locations` name a source-neutral consumer imports. `test_a_mapped_retailer_completes_the_whole_builder`
      now runs the real entrypoint end to end and
      `test_identity_resolution_must_be_declared_not_inferred` pins the fail-closed default.
      **Decision #88 is now closed** (option (a): the Shopify adapter emits the frozen
      contract's `name`/`location_kind`, the canonical transform and crosswalk follow, and
      staging-v2 was not amended). Retained for history — the frozen `location` role declares `name`/`location_kind`
      while the Shopify adapter emits `location_name`/`location_type`, so the neutral relation has
      never presented its contract's field names. The crosswalk accepts both spellings as an
      interim measure. Readiness and selection (`resolve_selection`, `verify_against_publication`)
      remain library-only with no runtime consumer; `resolve_selection` checks path existence only.
- [x] **Corrected 2026-07-31.** Add at least one fully non-Shopify/non-Business-Central
      retailer fixture that reaches the same canonical roles through `mapped_files`, and one
      fixture whose genuinely different semantics require a bounded custom adapter.
      The mapped-files fixture is proven through the real `build_staging()` entrypoint. The
      custom ledger-ERP fixture reaches the standardized role, but its money handling
      encoded the same 100x double-conversion that was fixed in `mapped_files`: it applied
      `exact_minor_sql` and stored the result in `net_amount_major`, which the canonical
      transform converts again, so EUR 24.00 became 240000 minor units. Fixed, and the two
      tests that asserted the defective 2400 now assert Decimal("24.00"). The earlier
      "both fixtures reach shared transforms" claim was true of the column shape and false
      of the values. Prove both reach shared transforms without
      platform-named staging tables or downstream branches; also include missing-temporal-evidence,
      ambiguous-mapping and incomplete-capability negative fixtures.
- [x] **PP3-A6/A8 done 2026-07-31.** Sufficiency is a separate field from readiness and
      `consumerMayProceed` requires both, so a ready-but-insufficient retailer produces an honest
      no-go rather than a silent pass. Nothing expands, duplicates or synthesizes series.
- [x] Keep statistical sufficiency independent from ingestion success. Real retailer data may
      legitimately produce `insufficient_evidence`; never expand, duplicate or synthesize client
      series to pass an ML gate. Any alternative cold-start, hierarchical/pooling method or gate
      amendment requires its own versioned model-policy decision and untouched holdout evidence.
- [x] **PP3-A8 done 2026-07-31.** The synthetic v12 path is proven byte-identical (plan §1.4.2);
      the mapped-files and custom-adapter paths reach standardized roles with lineage to the raw
      object on every row, and adding either changed no shared transform, ML, API or UI source.
- [x] Before declaring retailer onboarding complete, run a client-shaped round trip:
      immutable landing → Gate A → profile/mapped adapter or custom adapter → neutral staging roles
      → shared transforms → Gate B → per-retailer pin → unchanged feature/ML code. Publish the
      readiness/capability report and prove that adding the adapter changed no shared transform,
      ML, API or UI source behavior.
- [x] **PP3-A9 done 2026-07-31.** `ingestion/ONBOARDING.md` publishes the decision tree, the
      fail-closed table, temporal-evidence grades, the derived zero-demand rule, capability
      outcomes, selection semantics and an onboarding checklist. The Track A acceptance statement is
      stated without overclaiming: unchanged shared code for a new retailer, with each capability
      independently authorized or rejected. Staging v2 remains `frozen_not_cut_over` — v1 is still
      the runtime contract, so the cutover decision is deliberately left open for review.
- [ ] If implementation is approved, reconcile the architecture/specification, ingestion README,
      decision registry, source-profile contract, conformance kit and operational onboarding guide
      with the delivered behavior. Until then, describe the current result precisely as
      "accepted synthetic demo pin", not universal retailer-data authorization.

## Post–Phase 3 forecast quality and presentation hardening `[DEFERRED AFTER RETAILER ONBOARDING]`

**Do not start this work before the complete Phase 3 exit, retrospective approval and acceptance
of the retailer-source onboarding workstream above.** The former v12 run and
`fr_92135aa7b5215b69` remain rejected historical diagnostics and are neither C0 nor D0. A new
PP3-P0 complete-population decision-#82 acceptance/verifier result becomes accepted comparison
authority C0 if it passes. If it fails, it may become diagnostic-only D0 when it still satisfies
feature-schema-v6, decision #82, the fixed schedule and independent recomputation. D0 never
authorizes accepted/canonical publication, materialization, activation or serving, although its
immutable diagnostic evidence is retained. These tasks improve forecast usefulness and
communication; they do not authorize threshold tuning, relabelling, hiding weak slices or
changing datagen merely to manufacture greener metrics.

- [x] **PP3-B1/B2 done 2026-07-31.** `contracts/ml/forecast-improvement-policy.json` freezes
      decisions #74/#75 before any candidate exists (8 development origins, 5 untouched confirmation
      origins, 20-configuration cap, one candidate advanced, >=5% relative WAPE, seeded SeriesKey
      clustered bootstrap upper bound below zero, 1% per-market non-regression, identical cohort
      keys, six stop rules, all three superseded runs permanently excluded).
      `ml/src/retail_ml/diagnostics/baseline.py` publishes D0 from the rejected run with market,
      store, category, channel, model-route, cohort and exact-horizon slices plus cohort key hashes;
      14 tests prove an accepted run cannot be published as D0, a rejected one cannot be promoted to
      C0, a run outside the current authority is refused, and a zero-actual slice is
      `insufficient_evidence` rather than a pass. See plan §3.1.5 for the three findings.
- [x] Publish a frozen diagnostic baseline before changing models: global, market, store,
      category, channel, lifecycle/intermittency segment and horizons 1/4/8/13/26. Include WAPE,
      accuracy, signed bias, P90 coverage, interval width/confidence, FVA versus MA13 and
      seasonal-naive lift. Preserve governed complete comparison keys so every claimed improvement
      is comparable.
- [x] **PP3-B3 done 2026-07-31.** `ml/src/retail_ml/diagnostics/causes.py` ranks the ten registered
      hypotheses by share of absolute error rather than by WAPE, with 8 tests. The ranking rejected
      my own first reading: the intermittent routes have the worst WAPE (0.86 and 1.35) but carry
      only 0.91% of recoverable error, so H3/H8 are `rejected_immaterial_error_share`. Supported
      causes are H7 feature fallback at long horizons, H2 category composition, H1 market x horizon
      under-bias and H4 lifecycle/cold-start. H5/H6/H9/H10 need controlled ablations and are
      labelled untestable rather than claimed. 26 of 41 categories under-biased vs 10 over-biased,
      so C1 must be segmented, never a global shift. See plan §3.1.6.
- [x] Diagnose the current under-forecast pattern explicitly. Rejected diagnostic run
      `fr_92135aa7b5215b69` is 71.82% accurate with −6.72% bias globally, 72.99% with −4.75%
      bias in India and 70.35% with −9.17% bias in US New York; exact-horizon accuracy declines
      from 78.16% at h1 to 69.51% at h26. Identify whether the causes are calibration,
      category mix, intermittent routing, censored sales, lifecycle, signal fallback or model
      pooling before selecting a remedy.
- [x] Register the v15 US cold-start proxy deficit as the first lifecycle/cold-start hypothesis:
      champion WAPE 37.13% versus MA13 proxy 36.60%, with MA8 at 36.63% and naive at 37.39%.
      Recompute using decision #82's exact comparator on v6 and test lifecycle, pooling and
      intermittent-routing causes. Do not amend the comparator or threshold from this result.
- [x] **PP3-B4 done 2026-07-31, no accepted candidate.** C1/C2/C1+C2 implemented in
      `ml/src/retail_ml/models/bias_correction.py` with the decision-#75 gate in
      `ml/src/retail_ml/diagnostics/comparison.py`; 17 tests. All three rejected. C1 eliminates
      global bias (−6.72% → +0.62%) but *worsens* WAPE by 0.96% and breaches the per-market
      tolerance, because P50 is a median forecast and WAPE is a median-optimal loss — the
      under-bias is real but not recoverable accuracy. C2 sharpens intervals 14% at compliant
      coverage yet scores +0.000% because #75 is WAPE-only and blind to sharpness; that gap is
      recorded as a pre-result amendment rather than fixed, since adding a criterion after seeing
      the result would be tuning to admit a candidate. See plan §3.1.7.
- [x] Evaluate market × horizon bias correction and quantile calibration on held-out origins.
      Any correction must improve paired WAPE/bias while keeping P90 coverage inside 0.85–0.95,
      preserving P90 ≥ P50 and passing every supported-market gate. Never tune against the
      future-only active cycle or optimize a display value directly.
- [x] **PP3-B5 done 2026-07-31, no accepted candidate, and one leakage defect found in my own
      work.** C3/C4 are in `ml/src/retail_ml/models/reconciliation.py` with 15 tests. C3 is scoped
      to the causes B3 ranked material (H2 category, H4 cold-start) and deliberately not to H3/H8
      at 0.91% of error mass; its sufficiency rule (500 rows, 25 SeriesKeys, 8 origins) is frozen
      before scoring and insufficient segments shrink to parent. C3 rejected: all-13 −0.149%,
      final-5 −12.285%. C4 measures leaf and aggregate separately — leaf WAPE 0.281798,
      market×category 0.178674, market 0.083486, so the aggregate is 3.4× easier and decision #78's
      prohibition is load-bearing rather than theoretical. **My first `top_down` draft
      disaggregated the parent total by each leaf's share of `actual_units` and the gate returned
      +59.2% relative WAPE with `accepted: true`.** Decision #75 lists LEAKAGE as a stop rule but
      nothing implemented it. `reconcile()` now refuses to split without an origin-safe
      `share_column`, and `detect_leakage()` in `comparison.py` implements the stop rule on
      improvement size, correlation uplift over the authority and row-wise target reproduction.
      Calibrated on the 708,708-row bundle: honest candidates move correlation by 0.0000–0.0011,
      the leak by 0.0590 and using the target outright by 0.0728, so the 0.02 threshold sits an
      order of magnitude above the honest ceiling. The leak now scores `accepted: false`. An
      absolute correlation ceiling was tried first and discarded — it flagged an honest rescale,
      because a competent forecast already correlates 0.9272 with its target.
- [x] Compare segmented champion candidates by market, category and governed demand behavior:
      LightGBM configuration, intermittent-demand routing, lifecycle-specific treatment and
      shrinkage back to sufficiently evidenced parent pools. Freeze minimum sample/origin rules;
      insufficient segments fall back transparently rather than receiving bespoke overfit models.
- [x] Evaluate hierarchical reconciliation across SeriesKey → store/category → market totals so
      operational aggregates and leaf forecasts are coherent. Measure leaf and aggregate accuracy
      separately; never present an easier aggregate score as SKU×store×channel accuracy.
- [x] Improve actual uncertainty, not merely the displayed confidence number. The current median
      confidence is about 0.56 because the governed formula reflects relative P50–P90 width.
      Test interval sharpness only under unchanged empirical-coverage gates; artificial interval
      narrowing that raises confidence while reducing coverage is an automatic rejection.
- [x] **PP3-B6 done 2026-07-31: all five signals screened, none admissible, and the reasons are
      properties of the source rather than of the modelling.** `ml/src/retail_ml/diagnostics/signals.py`
      runs four screens in cost order — temporal evidence grade, grain, leakage, materiality — and
      the first failure is terminal, so no ablation is spent on a signal that cannot reach decision
      #75's 5% floor. `tools/screen_optional_signals.py` regenerates
      `contracts/evidence/optional-signal-admissibility.json` from the live publication, so a later
      source fix changes the verdict without anyone editing prose. Results:
      **future promotion plan** — the whole promotion family carries one `known_as_of`, the landing
      stamp 2026-07-30, against start dates back to 2016; grade `landing_backfill` is
      `knownAsOfEligible` but not `supportsHistoricalReplay`, and every acceptance origin is
      historical, so nothing is origin-visible to fit. `promotion_plan_available = False` in
      `current_cycle.py` is therefore correct, not a stub.
      **weather forecast beyond available leads** — the source issues 1–7 day leads only, against a
      182-day h26 window, so h1 is the sole coverable horizon and the shipped `_h1` features already
      consume the entire lead. 96.96% of evaluation rows fall back to climatology, capping any gain
      at 3.04% of error mass, below the floor.
      **competitor availability** — already in the feature set (`competitor_price_ratio`,
      `_available`, `_in_stock`, `_age_days`); SHAP attributes 0.38% of decision mass to it, and the
      source carries observed prices only, so there is no forward plan to admit.
      **stock-out / censored demand** — `stock_snapshots` is keyed on 4 DC/MFC locations with zero
      overlap against the 4 demand stores the SeriesKey forecasts. Store-grain on-hand does not
      exist in the publication, so censoring cannot attach to a forecast row at all. This is the
      same fact the Gate-B mask records as `replenishment: HISTORICAL_INBOUND_STATUS_NOT_VERSIONED`.
      **lifecycle/assortment** — the only signal that cleared materiality, at 14.31% of error mass
      within 90 days of an exit, and it fails leakage instead: `active_to` equals the last observed
      positive sale exactly on 34.52% of keys and within 7 days on 69.24% (median 2 days), while
      `known_as_of` precedes `active_to` on 100% of rows by 186–3,652 days. The field is the
      target's own boundary back-stamped as foreknowledge, so `days_to_exit` would leak. Launch-phase
      mass is only 1.03%, so the cold-start gate failure is not an assortment-visibility problem.
- [x] Prioritize origin-safe information that a real retailer can supply through ingestion
      profiles/adapters: future promotion plans, longer-horizon weather outlooks, competitor
      availability/plans, stock-out/censored-demand evidence and lifecycle/assortment changes.
      Declare each capability optional and reason-coded. Do not add downstream retailer branches,
      and do not change datagen unless correcting the source contract or modelling evidence a real
      source is expected to provide.
- [x] **PP3-B6 quality policy v2 done 2026-07-31 as a candidate; v1 stays active.**
      `contracts/ml/forecast-quality-policy-candidate.json` and
      `ml/src/retail_ml/policies/quality_v2.py`, 23 tests covering both signals and policy.
      The mechanism behind all 2,034 series being `Watch` is `current_cycle.py:193-195`: three
      publication-level scalars (`source_quality_critical_count`, `source_quality_warning_count`,
      `reconciliation_passed`) are broadcast onto every row, then reduced worst-of with the
      row-local checks. v1's own contract already forbids this — `inputSemantics.sourceFindings`
      requires findings bound to the same SeriesKey — so the broadcast contradicts the active
      contract rather than merely being coarse. v2 publishes `row_quality_class` from the five
      row-local dimensions only, `publication_quality_class` from `global_limitations` alone, and
      `effective_display_class` as the worst of the two with a `degradedBy` list naming which grain
      set it, so the combined state stays available but can no longer be read as a row-local
      measurement. Every threshold is carried over from v1 unchanged and a test asserts it, so a
      v1/v2 comparison measures grain and nothing else. Both failure directions are tested: one
      global warning must not degrade a clean row, and the warning must not be dropped to protect
      it. An unevaluated row-scoped reconciliation is recorded as a third state rather than
      collapsed into pass or fail. **This is a candidate — reviewing it does not promote it, and
      decision #76 requires an accepted candidate first.**
- [x] Implement decision #76 as a versioned quality-policy-v2 candidate. All 2,034 current
      series are `Watch` because a publication-level source warning is inherited by every row,
      while most row-local checks are `Good`. Separate global capability limitations from
      row-specific completeness/freshness findings without hiding either; require policy review,
      new fingerprints, executable vectors and a newly accepted run before changing labels.
- [x] **Done 2026-07-31.** Implement decision #77's exact-horizon accuracy targets at h1/h4/h8/h13/h26:
      market/portfolio 90/88/85/82/78, store/category 85/82/78/75/70 and SeriesKey
      80/78/75/72/68. Every cell also requires absolute bias ≤5% and P90 coverage 0.85–0.95;
      insufficient denominators remain unavailable. The screen must label the exact grain and
      never substitute an aggregate score. Consume
      `contracts/ml/forecast-health-policy.json` for target-grain resolution, unit conventions,
      ordered all-condition status evaluation and executable vectors.
- [x] **Done 2026-07-31.** Correct the known Forecast Health parity deviation. Decision #64/Q6 and the screen contract
      now carry the finalized policy; React must always render the original four default rows in
      order — `1 week`, `4 weeks`, `8 weeks`, `13 weeks` — independent of the selected
      operational forecast cap.
      Per decision #80, use exact h1/h4/h8/h13 values, not cumulative 1..N, so deterioration is
      not averaged away. Keep h26 in diagnostics or a separately approved drilldown, not as a
      fifth default row.
- [x] **Done 2026-07-31.** Replace the current coverage-only Forecast Health badge with decision #80's target-relative
      matrix at the displayed grain/horizon: `Strong` means accuracy ≥ target+5, absolute bias
      ≤3% and coverage 0.87–0.93; `Healthy` means accuracy ≥ target, absolute bias ≤5% and
      coverage 0.85–0.95; `Watch` means accuracy ≥ target−10, absolute bias ≤10% and coverage
      0.80–0.98; otherwise `Action`. Any unavailable metric is unavailable, not a badge. Add
      desktop/responsive DOM, data-value, order and horizon-filter-independence tests.
      Remove `PP3_B7_REACT_IMPLEMENTATION_PENDING` only when those tests prove React consumes the
      fingerprinted policy. Visual approval must record that the HTML sample coverage/badges are
      placeholders superseded by #80, while the HTML remains layout authority.
      Python, Go and React must execute the same policy vectors with the declared
      percentage-point and ratio units.
- [x] **Decision #84 framed and frozen, C5 built, scored and adopted under #86 2026-07-31.** Measured on `fr_a5b88c2ef23091ee`, the sole failing gate is concentrated rather than
      diffuse: us-new-york x cold_start is 55,224 rows carrying **17.053% of global absolute error**
      (942,576 of 5,527,232) on 12.93% of volume. Two bars, far apart: A5 non-inferiority needs the
      champion to shed only **22,085 error units (2.34% of the cohort's own error, 0.400% of global)**,
      while decision #75 needs **5% global** to let any candidate change the champion — which means
      shedding **29.3% of this cohort's error**. A perfect fix would give 17.053%, so the #75 floor
      sits inside the ceiling, not above it. There is no catch-22.
      Five candidates already failed (C1, C2, C1+C2, C3, C4) and every one of them rescales or
      re-intervals; none replaces the estimator. The champion losing to a mean-of-last-13-weeks on
      thin-history series is an estimator problem, so a sixth scale factor is not the next
      experiment. Untried: `p50 = w * lgbm_p50 + (1-w) * cold_start_mean` with `w` fitted on the 8
      development origins only, segmented at most by market x horizon, shrunk to parent on the frozen
      sufficiency rule. Both inputs are origin-safe so it cannot leak, and non-inferiority is
      reachable by construction as `w` approaches 0.
      **Governance first:** the sufficiency bullet above already requires any alternative cold-start
      or pooling method to carry its own versioned model-policy decision plus untouched holdout
      evidence. Decision #84 must be framed and frozen **before** C5 is built and scored, or the
      result is unusable however well it performs. Quantified basis in
      `contracts/evidence/forecast-closure-record.json` under `remainingDistance`.
- [ ] Prepare a reviewed Demand Forecast presentation update that keeps truth visible. The
      rejected run's +30.61% FVA and 88.85% P90 coverage may be shown only as labelled diagnostic
      evidence; its +53.47% seasonal-naive result is paired-subset evidence, not an accepted
      strength. Lead with metrics only after the next complete-pairing run is accepted. Explain
      confidence as calibrated uncertainty, show horizon/market context and distinguish global
      limitations from row quality. Update the parity contract and obtain UI approval before
      changing React.
- [x] **Decision-#83 acceptance run done 2026-07-31: `fr_a5b88c2ef23091ee`, published rejected,
      independently verified.** The full 13-origin/26-horizon schedule re-run on
      `features_db3784fdcc4cb833_review4_v6` (708,708 evaluation rows, 65,021,190 training rows,
      38m44s, performance profile), then scored, classified, published and verified end to end.
      **All five global gates now pass**, including the cold-start comparison at **+1.481%** where
      every scope previously returned `insufficient_evidence`; `rowsWithoutComparator` is 0
      everywhere, which is decision #83 doing exactly what it was decided for. Of the 1,820
      previously-blocked rows, 1,404 entered the cold-start comparison and 416 are true
      zero-observation residue at 0.0587% against the 1% cap. A5 fails on **one market**:
      us-new-york cold-start non-inferiority at **-2.399%** (champion 0.371740 vs comparator
      0.363030). india-west passes at +5.586%; established history passes at +53.481% globally.
      **That single margin is the entire remaining distance to Phase 3 acceptance.**
      Two properties worth keeping: `forecast_eval_predictions.parquet` is byte-identical to the
      pre-#83 bundle (`dc81e841...`, 27,146,170 bytes), proving #83 changed evaluation semantics and
      not one forecast; and the superseded cohort82 bundle now **fails** `verify_forecast_run` with
      "acceptance document does not match recomputed A1-A5 gates", so the stale evidence is
      fail-closed rather than silently readable. Recorded in
      `contracts/evidence/forecast-closure-record.json`.
- [x] **PP3-B8 done 2026-07-31 on the required-gate-failed branch.** The closure record now carries
      a 20-item `requiredChecks` matrix: 12 pass, 2 fail (us-new-york cold-start, and A5 itself),
      1 `no_candidate_passed` (five candidates evaluated across B4 and B5, none met the 5% floor on
      both populations), 1 `correctly_withheld` (materialization refused because the run is
      rejected — the required behaviour, not a failure), 1 `not_eligible`
      (`pitEligibility.reasonCode = LANDING_BACKFILL_DEPENDENCY`), 1 `partial_with_static_audit`
      (supported-OS), and 2 `not_run` that need a person. A check that never ran carries a reason
      rather than a blank, so it cannot be misread as a pass. Actions taken: rejected immutable
      candidate published with full evidence; **no** materialization, **no** activation record, **no**
      serving authorization, serving left fail-closed. The stateful local gate ran in
      `governed_no_go` mode against `forecast_run_v6_d83` — discovered by manifest rather than
      directory name, so it correctly preferred the new bundle over the superseded one — and
      passed every stage: contracts 122, datagen 52 + 8 subtests, execution 12 + 17 subtests,
      ingestion 170, ml 158/1 skipped, Go race-uncached all four packages, UI 11 tests plus
      typecheck and production build, import boundaries clean across 98 files.
- [x] Accept an improvement only when the same immutable comparison schedule passes A1–A5,
      additive-metric consistency, leakage checks, both supported markets, calibration,
      deterministic profile invariance and live-screen mapping. Bind comparison to
      `retail-weekly-features/v6`, the decision-#82 evaluation/verifier ids
      (`cohorted-seasonal-cold-start-recomputation/v4` and `retail-forecast-verifier/v4`),
      canonical serialized row ordering and identical governed complete rows. Decision #82's
      established-history and cold-start cohorts must both be complete and pass their separate
      gates; paired WAPE cannot compensate for an omitted cold-start row. US New York currently
      sits exactly at the frozen 100 slow-mover-series
      minimum, so a smaller candidate population is `insufficient_evidence`, not an improved
      result. Candidate selection/configuration uses only the first 8 origins and freezes one
      candidate before reading the final 5. Publish decision #75's full materiality battery for
      both all 13 origins and the untouched final 5, and require both windows to pass. Publish a
      new immutable candidate; never overwrite or cosmetically reclassify prior evidence.

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
- [~] Extend the Alembic-owned PostgreSQL schema. Phase 3 already supplies the independent
      migration ledger and read-only `retail_serving` forecast projection; Phase 6 must add the
      reviewed workflow, approval, override, idempotency, RBAC and audit tables without turning
      immutable raw/curated/features into database-owned lake storage.
- [~] Extend the PostgreSQL service introduced in Phase 3 for mutable approvals, overrides,
      recommendation state, idempotency, RBAC and audit. The Compose/RDS-compatible serving
      foundation exists; all mutable workflow semantics remain Phase-6 work.
- [~] Extend the Phase-3 Docker Compose base rather than introducing Compose here. PostgreSQL and
      shared MLflow already run under decision #63; Phase 6 adds the Aarv API/UI services, mutable
      workflow/governance state and production-like secret/network settings. Keep batch data jobs
      explicit rather than turning them into idle services.
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
- [ ] Retain the accepted Data Management matrix/screen and freeze equivalent matrices for the
      original Performance Insights, Reports & Exports, Alerts & Notifications and Model
      Management destinations before adding their live analytics/admin data. User Management
      remains omitted until users/RBAC scope is explicitly reopened.
- [ ] Model registry / drift; alerts + data-freshness; data-source management; reports, rendered
      through those approved original screens rather than new admin layouts.
- [ ] Adoption metrics / performance insights (AI-vs-control cohort).
- [ ] Disclosure guardrails (projections not lift; observational elasticity; synthetic labelling).
- [ ] Complete the approved portions, if any, of the deferred post–Phase 3 retailer-source
      onboarding workstream. Its two client-shaped dialects must prove config-only onboarding
      where mappings cover semantics and a bounded versioned adapter where they do not, with no
      platform-named staging dependency or downstream retailer branch.
- [ ] End-to-end acceptance run (ingest → serve) through all fail-closed gates.
- [ ] Run the small end-to-end smoke path from Windows, macOS and Linux developer hosts; the
      production-scale benchmark may run once on the designated machine, but its orchestration
      and artifact semantics must not be host-specific.
- [ ] **Exit:** full run passes; all screens live.

- [x] **Decision #92 closed end to end 2026-08-01.** Cold-start intervals are published only
      within the calibrated horizon and withheld beyond it, and the withholding now reaches
      serving rather than stopping at the bundle.
      Three candidates failed to calibrate the full range first (#87 C6 pinned at its grid
      ceiling, C7 overshot to 0.9620 on held-out origins and cost 46.9% of confidence, #91's
      dedicated cold-start quantile head reached 0.8063 while preserving confidence), and
      the failure is monotonic in horizon: 0.8603 h1-h4, 0.8433 h5-h8, 0.8024 h9-h13,
      0.7798 h14-h26. Reorder is unaffected because every `suppliers_leadtimes` row carries
      `lead_time_days = 5`, which resolves to h2.
      **A review caught that the withholding helper was written, tested and never called**,
      so the gate measured h1-h4 while every served row still carried an h5-h26 interval --
      the gate telling the truth about a number nobody reads. Wiring it then exposed that it
      could not be stored at all: `forecast_series.yhat_p90` and `confidence` were NOT NULL,
      and the Go read model scanned them as non-pointer `float64`, which fails outright on a
      NULL. All three layers are now done: migration `0008_nullable_withheld_interval` with
      CHECK constraints pairing the interval to its confidence and requiring a reason, Go
      scanning `*float64` and surfacing `intervalAvailable`, and a nullable UI schema.
      Measured in PostgreSQL: 8,756 withheld, 202,780 served, one reason code, **zero P50
      nulls**. Null was chosen over a sentinel deliberately -- safety stock is quantile
      spread x service level, so a placeholder is consumed arithmetically and a zero would
      return zero safety stock on the least predictable products.
      Serving `fr_357575f586905b11` / `fv_3d66e3bd9939430d`. `tools/dev.py verify` exit 0.
      **Still bounded, not solved:** cold-start P90 covers 17.9% of series and 22.47% of
      demand and is calibrated only to h4. Extending the range needs a new mechanism with
      its own preregistered protocol.

- [x] **Post-Phase 3 review findings fixed 2026-08-01.** An external review of the two
      unpushed commits found several guarantees overstated; all are corrected.
      The custom ledger-ERP fixture still encoded the 100x money defect that was fixed in
      `mapped_files` -- it applied `exact_minor_sql` and stored the result in
      `net_amount_major`, which the canonical transform converts again, so EUR 24.00 became
      240000 minor units. Adapter-level rejects reached no governed quarantine: the mapped
      adapter recorded them in `<role>_candidate` and excluded them, while `_build_quarantine`
      only inspected dialect relations, so an invalid row was neither served nor traceable.
      A generic `_drain_adapter_rejects` pass now moves every adapter's rejects into
      `stage_data.adapter_quarantine`, proven through the real builder.
      The closure record mixed several generations of evidence -- stale artifact hashes, a
      stale fingerprint, a materialization action naming a superseded version, an A5 line
      reporting a fixed failure, and the current run listed as superseded by itself -- and no
      validator checked it, so the gate passed on a record that contradicted the run it
      described. It is now generated by `tools/build_closure_record.py` from the bundle and
      the live activation, with five contract tests.
      Decision #86's display protection covered only `market_portfolio` of three governed
      grains and the verifier never replayed it; it now covers all three, a skipped grain
      blocks the gate, and the verifier replays the evidence instead of reading it back.
      Snapshot identity trusted a producer-controlled `contentDeterminism` string, so a
      source could label an authoritative object `logical` and change its bytes freely; the
      exclusion is now gated on the governed mirror's dataset, format and path.
      Also fixed from my own review: `location_role_identity` wrongly enforced name
      uniqueness, refusing two distinct stores that share a display name even though
      identity resolution never reads the name; `interval_calibration.py` was 400 lines of
      unreachable rejected-candidate code, removed after checking imports, dynamic loading,
      contracts and `__init__`; `_free_port` was never called; the horizon limit did not
      validate against its own measured bands and now asserts at import; and the pipeline
      orchestration had no tests, now nine.
