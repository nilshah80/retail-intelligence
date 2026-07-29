# `datagen/` — Independent synthetic source generator

**Purpose:** simulate a retailer and publish realistic **source-shaped** data. The generator owns
its own scenario contract and must not know the PoC's canonical `retail_v2` schema, Gate A/B,
canonical versions, canonical `known_as_of` rules or transformation logic.

## Config Builder is the authoring contract

The HTML Config Builder is the only supported way to create a run configuration. It must:

- expose every supported setting, validate it in the browser and export equivalent YAML and JSON;
- support one retailer with multiple markets, legal entities, stores and warehouses in the same
  scenario;
- make every store and warehouse explicit rather than accepting only aggregate counts;
- define one or more Shopify/Business Central source instances and map each instance to its
  markets, stores, warehouses and legal/company context;
- derive locale-sensitive defaults from the selected market, while allowing documented overrides;
- import a previously generated YAML/JSON config for lossless editing;
- show the resolved configuration before download and never keep preset-only hidden fields;
- embed each locale pack ID/version and the complete resolved locale values used by the run, so
  generation does not depend on an unrecorded future pack revision.

Supported locale packs for the PoC are:

- `IN` — India;
- `US` — United States;
- `GB` — United Kingdom (the UI may label it “UK”);
- `DE` — Germany, the PoC representative for Europe. “Europe” is not a tax or holiday
  jurisdiction; additional EU countries are later data-only locale packs.

A locale pack owns currency/minor-unit metadata, native price bands and endings, tax basis and
category rates, fiscal defaults, timezone choices, address/postcode/Faker locale, holiday tables,
sale seasons and climate profile. Lunar festivals such as Diwali and Eid use reviewed date
tables, not guessed formulas.

Each country also resolves a versioned, generator-owned **catalog pack**. Catalog packs contain
real brand and product-line reference identities, market-local price bands, materials, option
values and EAN-13/UPC-A behavior. Transactions, inventory, prices, costs and demand remain
synthetic; the generator never claims that a simulated observation came from the named brand.
The rich catalog generator adapts the reference
generator's product/variant split and deliberately partial option matrices, then emits distinct
product codes and sellable variant SKUs. Per-category controls cover option dimensions,
seasonality, costing method, target margin, return rate and elasticity. `generated`, `hybrid`
and `explicit` modes are first-class Config Builder settings; no fallback publishes
`Market Department 001` or product-as-SKU placeholders.

`catalogFamily` is a generator behavior-pack key (purchase frequency, shelf life and option
defaults), not a third reporting-hierarchy level. The checked-in presets intentionally map one
behavior family to each category; Shopify tag publication removes duplicates when those keys are
equal.

The default hierarchy contains 10 departments and 41 categories: Apparel, Electronics,
Groceries, Home & Kitchen, Beauty & Personal Care, Health & Wellness, Sports & Outdoors,
Toys & Baby, Books & Stationery and Automotive. Each department contains multiple categories,
and perishable grocery/health/baby families carry shelf-life rules into receipt batches and
expiry evidence. The hierarchy is deliberately retailer-wide and normalized across markets;
market catalog packs vary product lines and native prices (including country-specific grocery
and dairy assortments) rather than inventing incompatible category trees for each country.

Catalog history is temporal rather than a run-start snapshot. Generated products can launch
through a configured fraction of the scenario horizon; `incumbentProductPct` controls how much
generated assortment is already active at the start and `launchHistoryDays` controls how far
before that boundary those incumbents were introduced. Variants may launch later than their
parent product; minimum/maximum product life, discontinuation rate and replacement-link rate are
explicit controls. Hybrid/explicit templates accept a launch date, optional discontinue date and
predecessor product code. The projections publish Shopify `catalog_events`, Business Central
`item_lifecycle_events`, effective-dated price changes and hidden lifecycle truth. A SKU cannot
receive inventory, demand, an order or a price before its own launch, and it stops trading after
discontinuation. Explicit Config Builder lineages are authoritative; automatic predecessor/
successor links are created only between generated products and cannot rewrite an explicit
retirement date. A successor does not hard-stop its predecessor: the configured runout window
overlaps both generations and applies pre-launch anticipation, demand substitution, a sharply
reduced predecessor tail, an initial markdown, clearance and a final fire sale. Flagship
templates use a launch spike that decays to a stable level instead of the normal cold-start ramp,
and their storage variants launch together unless the template explicitly overrides that rule.
The checked-in presets contain real Apple iPhone 13–17 and iPad Air generation identities and
public availability dates; their generated transactions and economics are synthetic. The
checked-in multi-market preset deliberately demonstrates different regional assortments
(iPhones in India and iPads in the US). Config Builder product templates can publish either or
both families in any configured market; equal Apple coverage is not forced across regions.

The explicit Apple availability dates are traceable to Apple Newsroom: [iPhone 13
availability](https://www.apple.com/newsroom/2021/09/apple-offers-more-ways-to-shop-for-the-iphone-13-lineup-ipad-and-ipad-mini/),
[iPhone 14](https://www.apple.com/newsroom/2022/09/apple-introduces-iphone-14-and-iphone-14-plus/),
[iPhone 15](https://www.apple.com/newsroom/2023/09/apple-debuts-iphone-15-and-iphone-15-plus/),
[iPhone 16](https://www.apple.com/newsroom/2024/09/get-ready-to-upgrade-to-the-new-iphone-16-apple-watch-and-airpods-lineups/),
[iPhone 17](https://www.apple.com/newsroom/2025/09/apple-debuts-iphone-17/) and
[iPad Air (M3)](https://www.apple.com/newsroom/2025/03/apple-introduces-ipad-air-with-powerful-m3-chip-and-new-magic-keyboard/).
Brand and model names remain their owners' trademarks and are used only as recognizable
reference catalog identities in synthetic fixtures.

## Long-horizon and pandemic scenarios

Source spec v11 supports the locale-pack range `2005-01-01` through `2026-12-31`: up to 22
complete calendar years in one run. `configs/multi-market-20-year-history.yaml` is the executable
2005–2024 preset. It uses monthly physical partitions, compound annual demand growth, discrete
annual inflation, effective price-change episodes, recurring/reviewed holidays, catalog
introductions/replacements, the financial crisis, electronics/supply shocks, tariffs and
inflation. The preset's smaller long-history assortment is intentional; the response-rich
90-day showcase remains the pricing-coverage preset.

Pandemics are config-owned phased events, not hard-coded year checks. Each pandemic declares an
effect mode (`synthetic-shock`, `observed-no-adjustment` or
`documented-no-adjustment`), markets, pathogen, note and one or more possibly overlapping phases.
A phase can use `step`, `linear`, `ramp` or `triangle` timing and can alter market demand, traffic,
cost, supplier lead time and inventory loss, plus department, category, catalog-family and
store/online/marketplace channel multipliers. The 20-year preset includes:

- two H1N1 waves and normalization;
- neutral Ebola, Zika and Mpox timeline evidence where no broad retail adjustment is justified;
- overlapping COVID early-stocking, panic-buying, stockout, lockdown/channel-shift,
  home-baseline, supply-disruption, Delta, Omicron and inflation-drag phases.

The phase structure and neutral-outbreak distinction adapt the well-tested
`../retail_ai/scripts/generate_synthetic_extension.py` model. Supplier delay, cost and inventory
loss coupling also adapts the original `../retail-synthetic-data-generator` scenario mechanics.
The generator emits both `pandemic_timeline.csv` (the declared source scenario) and daily
`pandemic_signals.csv`; the hidden demand factors record the active pandemic/phase multipliers.

`startingDailyOrders` is a market/store opening **order-header** target, not a SKU/day row count
or unit alias. `averageLinesPerOrder` converts that target into causal SKU demand; realized units
are emitted at transactional line grain and deterministically basketed back into actual orders.
Store `demandScale` and market `demandLevelScalar` are explicit multiplicative scenario controls.
Growth, lifecycle, intermittency, holidays, prices, promotions, inventory constraints and
disruptions move realized volume away from that opening target; the CLI plan reports the
pre-factor order estimate. Tests assert actual daily order headers scale with the configured
target so a high-volume setting cannot silently collapse to one line per SKU/day.

## Source-data contract

The generator produces, from the same causal simulation:

- Shopify-shaped products, variants, direct-identifier-free registered customers plus guest
  checkouts, locations, multi-line orders, tax
  lines, split fulfillments and status histories, returns/refunds, webhook/HMAC fixtures and the
  named inventory-state matrix at the fidelity enabled by config;
- Business Central-shaped items, locations, direct-identifier-free registered/walk-in
  customers and synthetic vendors, sales, inventory,
  purchase/receipt/cost, inbound/batch, transfer, supplier-planning and warehouse-operation
  extracts at the fidelity enabled by config;
- external/companion datasets for holidays, weather, local events, promotions, competitors,
  macro, FX, allocation evidence and store assortment;
- a `source-run-manifest` containing generator/spec version, resolved config hash, seed/run
  identity, market/location topology, generated source objects/files, row/control totals and
  hashes;
- a generated `source-schema.json` field dictionary, also available as the DuckDB
  `source_schema` table, so ingestion authors do not need to infer source fields from Python;
- hidden synthetic truth used only to evaluate causal recovery and source-to-canonical
  reconciliation. Hidden truth uses generator vocabulary and is never a `retail_v2` fixture.

Shopify order display names use a source-wide monotonic sequence (`#1001`, `#1002`, …), while
source IDs remain stable content-derived identifiers. Business Central batches publish both the
generator warehouse key and the native BC location code so consumers can join them directly to
snapshots and ledger entries.

The v11 PoC return policy deliberately publishes every processed return as `NO_RESTOCK`; no
returned unit silently re-enters inventory. Modelling sellable-versus-damaged return disposition
and the corresponding inventory/ledger postings is a future configurable extension, not implied
by the current fixtures.

### Restricted `_truth/` evaluation artifacts

`_truth/` contains the synthetic answers known only because datagen created the world:

- `catalog_truth` records latent SKU behavior, lifecycle, demand weight, elasticity, return
  probability and base economics;
- `demand_factors` records the per-SKU×store×day causal decomposition, latent demand, realized
  sales and lost sales;
- `inventory_constraint_truth` isolates latent, fulfilled and stock-constrained units;
- `source_event_crosswalk` connects synthetic Shopify and Business Central events for
  reconciliation scoring;
- `competitor_match_truth` records the correct synthetic competitor matches.

These files are not retailer-shaped inputs, are never model features, and must not enter normal
ingestion or transformation. They may be read only by test/evaluation oracles. Setting
`output.writeHiddenTruth: false` omits them. When enabled, they are also present in
`source-run.duckdb`, with `restricted=true` in both source catalogs; therefore the entire DuckDB
file is handled as restricted.

Each run selects exactly one authoritative tabular source format: partitioned Parquet (the
default, with `zstd`, `snappy` or no compression) or partitioned CSV (uncompressed). JSON config
support remains available, but conventional YAML is the default authoring format. Every selected
source object is also mirrored into one `source-run.duckdb` at the run root for convenient
browsing and SQL. The database contains public source data and, when enabled, restricted hidden
truth; it is therefore permissioned as a restricted artifact. `source_object_catalog` maps each
DuckDB table to its authoritative path, format, compression, row count, content hash and access
class. It is a lossless, all-text mirror—not a canonical analytical database—and never replaces
the selected CSV/Parquet source contract.

The run also writes both `resolved-config.yaml` and `resolved-config.json`. YAML is the primary
human-authored/replay artifact; JSON is the retained compatibility mirror required by the
YAML+JSON contract. Both are serialized from the same fully resolved in-memory configuration,
manifest-hashed and expected to be semantically identical. They are run evidence, not retailer
source datasets, and the JSON file does not create a second scenario or change configuration
precedence.

Time-bearing datasets are physically partitioned as
`<logical-dataset>/year=YYYY/month=MM/part.<format>` (or day partitions when selected). The
manifest keeps both physical `path` and stable `logicalPath`; DuckDB's
`source_object_catalog` records every part while `source_dataset_catalog` provides one logical
table, total rows and partition count.
Long-horizon generation uses bounded private row spools rather than retaining source/truth
projections as Python lists. Only causal state, the current business day, trailing 28-day
replenishment evidence and bounded row buffers remain resident. Causally independent markets can
run in separate processes; their order/customer streams are deterministically merged and globally
renumbered before source projection. Independent month partitions are published concurrently;
the single DuckDB mirror is assembled in stable source-path order with explicit thread and memory
ceilings. Runtime controls do not change the config hash, run ID or logical business data:

```bash
retail-datagen generate -c scenario.yaml \
  --execution-profile safe
```

The Config Builder downloads a separate
`<scenario-id>.execution.yaml` with schema `retail-execution-profile/v1`. The scenario YAML/JSON
never contains hardware settings. CLI precedence is explicit overrides, then the supplied
execution document, then its named profile, then `safe`; bounded environment overrides use the
`RETAIL_DATAGEN_*` variables documented in `execution/README.md`.

`safe` is the default for the 16-GB-available demo machine: one market process, two partition
workers, one DuckDB thread, a 4-GiB DuckDB ceiling and 10,000-row spools. `balanced` stays on one
market process with 4/2 workers/threads and an 8-GiB ceiling. `performance` is for the larger
workstation: two market processes, 8 partition workers, 6 DuckDB threads, a 32-GiB ceiling and
50,000-row spools. `ultra-performance` targets this 16-core/128-GB workstation with two market
processes, 16 partition workers, 8 DuckDB threads, a 64-GiB ceiling and 100,000-row spools. It
does not raise market processes above two because this demo has only two independent markets.
No profile auto-expands to detected CPU/RAM, and impossible values fail before generation.
Fine-grained CLI overrides remain available:

```bash
retail-datagen generate -c scenario.yaml \
  --execution-profile-file scenario.execution.yaml \
  --market-workers 1 --workers 2 --duckdb-threads 1 \
  --memory-limit-gb 4 --spool-chunk-rows 10000
```

A complete 90-day showcase benchmark generated 78,818 orders plus Parquet and DuckDB in 47.02
seconds with 648,462,336-byte peak process RSS. A disposable Jan–Mar 2026 derivative of the
larger 720-SKU/125k-opening-customers-per-market ten-year preset, including its configured
grand-opening event, generated 123,491 orders in 76.88 seconds with 850,034,688-byte peak RSS.
The retained ten-year v10 run completed in 6,028.55 seconds with 7,810,482,176-byte
(7.27-GiB) peak process RSS. This is measured end-to-end, including causal simulation,
two-worker Parquet publication and the 12,839,563,264-byte DuckDB build; it leaves more than
8 GiB of the stated 16-GB available budget for the OS and demo services.

Customer behavior is also Config Builder-owned. Each market defines opening registered
customers, annual acquisition, churn/reactivation, guest-checkout share, opening history years
and a hard orders-per-customer-per-day cap. The customer master therefore spans pre-run history
through the extract date instead of creating 750 reusable identities in the first week.
Shopify guest orders carry an empty customer ID; Business Central projects them to an explicit
market walk-in account.

## What locale and topology drive

Market/store/warehouse configuration must drive:

- native currency amounts, price bands/endings and tax-inclusive vs tax-exclusive source fields;
- holiday and retail-event calendars, day-of-week effects, climate/weather and seasonal demand;
- fiscal defaults, timezone, addresses, postcodes and region/state codes;
- store/channel demand, assortment and promotion scope;
- warehouse stock, store-to-warehouse service relationships and fulfillment origin;
- Shopify shop/market currency and `taxes_included` behavior;
- Business Central company/legal entity, country/region, tax/VAT area and fiscal setup;
- external signals keyed to the applicable market/region/store.

Signals are not decorative: enabled holiday, promotion, weather, local-event, competitor and
macro factors must affect the latent-demand process so downstream driver pages can recover them.
The v11 demand process uses a cross-year, mean-reverting regular-price path instead of a repeating
price sawtooth, mean-normalized weekday and continuous annual-seasonality factors, multi-day
weather spells, and Config Builder-owned secular online-share growth. Black Friday and Cyber
Monday are explicit retail events; original-date closures are locale-pack flags and substitute
observance days do not create duplicate closures. One best-price
promotion applies at a time, its configured lift is not counted again through elasticity, the
ending decision remains stable for the offer window, ordinary campaigns respect the same
price-path and disruption-adjusted cost basis recorded on receipts, and a seven-day payback period
represents demand pulled forward only when the configured promotion signal is enabled.
Promotion and promotion-SKU feeds label configured `discountPct` as `planned-offer`; effective
prices remain observable in public price history and order lines, while hidden truth records the
effective discount and scales demand lift when a cost floor prevents the full planned reduction.
Every companion row carries the generator's own stable market key plus a structured
market/region/store target; `ALL`, `West` or a city name is never published without its market
namespace. Promotion targeting is structured (market plus optional region/store/channel
qualifiers), not a free-form expression. The FX projection documents an exact local-currency →
retailer-reporting-currency direction and emits decimal text rather than a binary float;
ingestion maps these source fields to the canonical FX contract.

## Pricing-evidence scenarios

Store count is not an elasticity-coverage proxy: one store with many SKU price histories can
produce many SKU×store series. The Config Builder therefore exposes generator-owned assortment,
price-event frequency, latent response and noise settings.

- `multi-market-showcase` uses a response-rich profile in both India and US (36 SKUs
  per department, 420 starting order headers per market-day and 36 configured price-change
  opportunities per SKU-year, yielding at least eight changes in the 90-day window). Its opening
  inventory covers the supplier-lead/review window, deliberate opening stockouts are disabled,
  and its seven-day replenishment cycle avoids making the 90-day demo primarily a cold-start
  transient. Dynamic stockouts can still arise from realized demand, supplier fill/delay,
  disruption and inventory loss. Reorder rates divide observed sales by days the SKU/location
  was available to sell rather than treating known stockout days as zero demand; no hidden
  latent-demand or `_truth/` field is used. The showcase uses a 21-day velocity-weighted opening
  cover and a Config Builder-owned 20% replenishment demand buffer. A verified 90-day v0.9.2
  scratch run reached 93.42% fill overall (India 94.30%, US 92.60%) while peak warehouse
  snapshots remained below configured capacity.
- `pricing-evidence-sparse` deliberately uses too little assortment and/or price movement so the
  downstream UI can demonstrate a reason-coded evidence block.

These presets do not contain or import ML gate thresholds. Datagen generates source evidence;
`ml/` alone determines how many series pass its configured acceptance policy.

## PoC priority

**Core acceptance:**

- deterministic config-driven runs;
- explicit multi-market store/warehouse topology;
- products/variants, demand, orders/sales, prices/promotions and usable inventory observations;
- Shopify-shaped, Business Central-shaped and companion projections;
- locale-correct IN/US/GB/DE amounts, taxes, holidays and climate;
- source-run manifest, controls and hidden causal truth;
- no direct dependency on `contracts/`, `ingestion/`, `ml/` or `api/`.

The first pricing round-trip is revenue-objective only. Temporal receipt/cost layers remain an
extension; until enabled and accepted by ingestion, datagen does not imply decision-grade
margin, margin-floor enforcement or margin optimization.

**Config-driven screen-completeness evidence implemented by source spec v11:**

- split-fulfillment/status histories and requested-vs-processed return evidence;
- successful/failed refund transactions and valid/invalid webhook HMAC fixtures;
- the complete Shopify inventory-state matrix, with committed quantities derived from open
  fulfillment-order lines and damaged/quality-control quantities derived from receipt handling;
- PO/receipt/cost-layer, inbound-shipment, batch/expiry, supplier performance/capacity, warehouse
  operation, transfer, waste and ERP↔WMS comparison projections;
- promotion-SKU/customer-segment, multi-line basket, allocation and realistic competitor-match
  evidence, with restricted match truth.

These remain generator-source features controlled by `operations.features`; canonical
interpretation and capability acceptance belong to `ingestion/`. Selectable CSV/Parquet plus the
single DuckDB mirror is the complete v11 publication matrix; JSONL remains an ingestion adapter
concern when a retailer supplies it.

## Dashboard source-coverage map

Datagen supplies source evidence only where a dashboard capability needs upstream retail facts.
It does not manufacture forecasts, recommendations, approvals, alerts, users, model registry or
audit rows—those are PoC runtime outputs/configuration.

| Dashboard area | Datagen source evidence | Delivery tier |
|---|---|---|
| Demand Forecast / Overview / Drivers | orders/lines or sales transactions, products, stores, price/promo history, holiday/calendar, weather, local event, macro, inventory availability | Core |
| Price Recommendations / Simulation | local-currency price history, tax, inventory and optional temporal cost/competitor inputs | Revenue pricing core; margin/cost and competitor depth as enabled |
| Competitor Monitor | competitor product attributes, observations, availability/promos and hidden match truth | Config-driven v8 source evidence |
| Promotion Planner | configured campaigns plus automatic runout/clearance/fire-sale promotion and promotion-SKU history; segment assignment; basket/order-line history for bundle/cannibalisation tests | Config-driven v8 source evidence |
| Inventory Overview / Store | explicit nodes, inventory observations and enabled committed/reserved/damaged/ATP states | Core + config-driven full state matrix |
| Warehouse Inventory | DC master, capacity/utilization, blocked stock, receipts, inbound status, fill and dock-to-stock observations | Config-driven v8 source evidence |
| Ageing / Expiry / Waste / Valuation | receipt/cost layers, batch/lot, family-specific shelf-life, manufacture/receipt/expiry dates, waste events and optional ERP↔WMS comparison observations | Config-driven v8 source evidence |
| Transfers | transfer request/order/shipment status and lane/location evidence | Config-driven v8 source evidence |
| Replenishment / Suggested Orders | supplier/item terms, MOQ/pack, lead times, open PO/receipts, capacity and budget source inputs | Config-driven v8 source evidence |
| Supplier Planning / Safety Stock | supplier OTD, capacity confirmation and lead-time history/variability | Config-driven v8 source evidence |
| Allocation & Fulfillment | demand requests, supply pools and source fulfillment locations; allocation recommendation remains a PoC output | Config-driven v8 source evidence |
| Exceptions / Stock Health | no separate source feed; derived downstream from forecast, inventory, cost, supplier and policy facts | Derived |
| Performance / Model Management | no datagen facts beyond hidden evaluation truth; model runs/metrics are produced by `ml/` | Runtime |
| Governance / Approvals / Users / Settings / Alerts / Reports | none; owned by API/DB/UI configuration and workflow | Runtime |
| Data Management | source-run manifest, file/object inventory, row/control totals and hashes | Core |

## Isolation rule

`datagen/` is self-contained and extract-ready. Consumers adapt to its versioned source-data
specification; the generator never imports downstream schemas. Real Shopify/client data never
belongs in `datagen/` or on a developer laptop.

**Reference implementation:** reuse locale-agnostic code from
`../retail-synthetic-data-generator` where compatible, then inject the new topology and locale
packs into its config, master-data, calendar/signal, simulation and Shopify/Business Central
projection seams.

Reuse is at the primitive/seam level, not a wholesale orchestration port. Deterministic seed
partitioning, source-native ID formats/namespaces, atomic checkpoint/replace,
checksumming/manifest logic and compatible CLI behavior may be adapted; the implementation
remains a small standard-library `argparse` CLI, and mutable counter-based ID allocation becomes
stable-key allocation. The old run identity, domain checkpoint state, writer dataset registry,
controller and CLI orchestration are redesigned around the generator-owned config and source-data
specification. Old canonical/ML-ready publication concepts and the fixed authoritative
`retail.duckdb` layout are not part of the new generator contract.

**Spec:** §9.

## Implemented source-spec v11

The Phase-1 generator is runnable:

- browser-based `config-builder.html` with structured add/edit/remove/reorder controls and its
  checked-in `vendor/js-yaml.min.js` dependency;
- complete IN/US/GB/DE locale packs materialized into every exported market;
- versioned IN/US/GB/DE rich catalog packs with real brand/product-line reference identities,
  10 departments, 41 categories, descriptions,
  retailer-valid explicit option matrices where required, deterministic partial option matrices
  elsewhere, stable product codes, sellable SKUs, reserved-range synthetic barcodes,
  category-appropriate units/weights, opening-incumbent
  assortment and independently dated product/variant launches;
- response-rich Mumbai + New York and sparse-evidence presets;
- conventional YAML-first import/export and config execution, with lossless JSON retained;
- generator-owned config validation, content-derived run identity and stable source IDs;
- optional Config Builder-owned per-market `categoryAssortmentWeights`, with omitted categories
  retaining weight `1` and an entirely omitted map preserving the uniform catalog exactly;
- SKU×store×day latent demand and inventory-constrained realized/lost sales with store assortment,
  locale, price, promotion, weather, event, competitor, macro, launch-profile, successor
  substitution, predecessor runout and intermittency effects;
- realistic multi-line/multi-unit baskets, portfolio-ranked demand, grocery purchase-frequency
  weighting and higher event peaks while preserving `startingDailyOrders` as the explicit
  order-header target;
- per-brand neutral synthetic distributors, availability-normalized observed-sales
  replenishment forecasts, one-pack launch/stockout bootstrap buys, and FEFO batch depletion
  with expiry write-offs that reconcile exactly to inventory on hand;
- effective-dated runout, clearance and fire-sale list-price reductions after successor launch,
  in addition to order-line promotion evidence;
- deterministic Shopify, Business Central and companion projections covering the config-driven
  operational evidence listed above;
- restricted catalog behavior, demand-factor, inventory-constraint, source-event and competitor
  match truth;
- source-run manifest with resolved-config hash, topology, capabilities, object hashes and
  per-currency/reconciliation controls;
- generated source field dictionary plus the same schema inventory in DuckDB;
- one selected authoritative CSV/Parquet source format plus exactly one `source-run.duckdb`
  mirror per run.
- executable short and 20-year generation tests, including product/SKU lifecycle gating,
  overlapping pandemic phases, both authoritative format choices and monthly source/DuckDB
  partition reconciliation.

The checked-in full 20-year preset was also executed end to end during Phase 1: it produced
2,194,234 source/truth rows across 133 logical datasets and 15,209 CSV partitions, with demand
truth covering `2005-01-01` through `2024-12-31`, 35,937 Shopify orders / 57,729 units, no order
before its SKU launch and exactly one DuckDB mirror. These figures are acceptance evidence for
the prior v4 CSV publisher, not fixed limits for custom Config Builder scenarios.

The prior v7 YAML-first high-volume preset was executed after the retail-physics, causal-inventory and
source-integrity corrections. Generator `0.7.1` run `run-2560a23a028b39ab` covers
`2021-01-01`–`2026-07-27` and produced 1,181,043 real order headers, 2,115,482 realized units and
33,109,277 source/truth rows across 134 logical datasets. Combined daily order volume was 241
minimum, 581 average, 2,106 maximum (936 at p95). It published 4,891 zstd-Parquet source objects,
the resolved YAML/JSON configs, `source-schema.json`, and one 1.1 GB DuckDB mirror; all 4,895
manifest objects re-verified by byte count and SHA-256.

The same run measured 98.0191% inventory fill (42,752 lost of 2,158,234 latent units), an 80.55%
top-SKU-quintile sales share and realistic median zero-day shares of 21.83% for India and 19.51%
for the US. Price-ending adherence is 83.08%/83.19%; promotions cover 4.07%/4.43% of SKU-days
with maximum configured demand multipliers of 2.10/1.95. The final 101 India and 90 US committed
units reconcile exactly to open fulfillment-order lines. Every one of 315,360 BC snapshots
reconciles to its opening, purchase, fulfillment-timed sale, transfer, waste and adjustment
ledger movements with zero error; all damaged snapshot quantities map to future disposal events.
The run also carries 24 open PO lines and 1,201 transfer lines at the extraction boundary/history.

The retained v8 run is
`output/multi-market-2021-current-volume/run-9b53e0a0490d3114`. Generator `0.8.0` and source
contract `retail-source-config/v8` produced 1,054,012 order headers, 1,886,776 realized units and
30,831,206 source/truth rows across 134 logical datasets. It contains 5,091 zstd-Parquet objects,
one 1.0 GB DuckDB mirror and 5,095 manifest objects in a 1.6 GB run directory; an identical rerun
re-verified and reused the immutable run.

That immutable v8 run predates the v9 barcode, vendor, multi-unit basket, FEFO expiry/batch,
realized-history replenishment, exact flagship-variant and lifecycle list-price corrections. It
remains reproducible historical evidence, but it must not be used to measure those v9 behaviors;
generate a new v9 run for current demonstrations.

Each market has 120 products, 360 sellable SKUs, 10 departments, 41 categories, 103 represented
brands and no legacy fictional product/brand token. Combined daily order volume is 214 minimum,
518.20 average, 757 p95 and 1,159 maximum. Inventory fill is 99.3844% (11,687 lost of 1,898,463
latent units). Median SKU-series zero-day share is 38.71% in India and 56.72% in the US, reflecting
the broader long-tail assortment; price-ending adherence is 82.44%/82.57%.

Lifecycle evidence is causal and published: both markets contain configured campaigns plus
runout-markdown, clearance and fire-sale promotion rows with exact SKU scopes. India order lines
include 20,535 runout, 78,828 clearance and 5,654 fire-sale units; US includes 16,633, 56,007 and
2,935 respectively. Apple iPhone 14 records 286 units after the iPhone 15 launch, iPhone 15
records 582 after iPhone 16, and iPhone 16 records 670 after iPhone 17. iPhone 15 produced 112
units in its first 14 days versus 46 in days 75–90, proving the flagship launch shape is now a
spike/decay rather than a trough/ramp.

All 315,360 Business Central inventory snapshots reconcile exactly to cumulative ledger
movements. The final committed quantities also reconcile exactly to open fulfillment-order
lines (70 India, 96 US). Of 4,356 receipt batches, 2,169 have family-derived expiry dates across
17 categories.

## Cross-platform operation

The Config Builder and generator are required to work on Windows, macOS and Linux. Source
manifests always record `/`-separated logical paths; native filesystem access uses `pathlib`.
Multiprocessing must use spawn-safe entry points, temporary work uses `tempfile`, and publication
must close CSV/Parquet/DuckDB handles before a same-volume atomic replace. No generator code may
require `fork`, `flock`, symlinks, POSIX mode bits, `/tmp` or shell expansion. The full
unit/config-builder suite and a small CSV/Parquet/DuckDB run are required on all three OS
families; importing the wheel alone is not sufficient.

Create the isolated datagen environment and run it from the repository root.

Windows PowerShell:

```powershell
py -3 -m venv datagen\.venv
.\datagen\.venv\Scripts\python.exe -m pip install -e datagen

.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli validate-config `
  -c datagen\configs\multi-market-showcase.yaml

.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli plan `
  -c datagen\configs\multi-market-showcase.yaml

.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli generate `
  -c datagen\configs\multi-market-showcase.yaml
```

macOS/Linux:

```bash
python3 -m venv datagen/.venv
datagen/.venv/bin/python -m pip install -e datagen

datagen/.venv/bin/python -m retail_datagen.cli validate-config \
  -c datagen/configs/multi-market-showcase.yaml

datagen/.venv/bin/python -m retail_datagen.cli plan \
  -c datagen/configs/multi-market-showcase.yaml

datagen/.venv/bin/python -m retail_datagen.cli generate \
  -c datagen/configs/multi-market-showcase.yaml
```

Later examples use the shorter POSIX entry point
`datagen/.venv/bin/retail-datagen`. On Windows, use
`.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli` with the same arguments.

Generate the 20-year preset with:

```bash
datagen/.venv/bin/retail-datagen plan \
  -c datagen/configs/multi-market-20-year-history.yaml

datagen/.venv/bin/retail-datagen generate \
  -c datagen/configs/multi-market-20-year-history.yaml
```

The Config Builder also exposes a first-class **10-year demo preset** for the retained
ingestion/ML dataset. It covers `2016-07-28` through `2026-07-28`, uses four stores and four
warehouse/fulfillment nodes across India and the US, carries 720 sellable SKUs across 10
departments, and publishes authoritative zstd-Parquet plus one DuckDB mirror. Its configured
ordinary baseline is 2,400 orders/day across both markets. A planned, pre-stocked regional
grand-opening event supplies a single extreme-volume day for ingestion and UI testing without
making every day artificially large.

The preset is the exact YAML contract embedded behind the Config Builder's **10-year demo
preset** button. `test_builder_presets_match_checked_in_configs` prevents the HTML and YAML from
drifting:

Its main DCs open with 42 days of node-level cover and the secondary nodes with 14 days. Because
demand is distributed across the two serving nodes, this is roughly four weeks of network cover,
not the previous 240-day overstock. A 2% per-node constrained-SKU rate supplies explicit opening
censoring evidence while ordinary replenishment, disruption and supplier behavior create
additional dynamic stockouts.

```bash
datagen/.venv/bin/retail-datagen validate-config \
  -c datagen/configs/multi-market-10-year-demo.yaml

datagen/.venv/bin/retail-datagen plan \
  -c datagen/configs/multi-market-10-year-demo.yaml

datagen/.venv/bin/retail-datagen generate \
  -c datagen/configs/multi-market-10-year-demo.yaml \
  -o datagen/output \
  --execution-profile safe
```

The v0.11.0/v10 run was generated and accepted as benchmark evidence, then its local output folder
was removed after v0.12.0/v11 superseded it. The measurements and hashes below are retained for
historical comparison; **the artifacts are no longer present locally.** The run remains reproducible
from its recorded config and generator/spec versions:

```
run id:        run-b8c4cceba05eb61a          (local output folder deleted)
config hash:   d52f5b629cd43243407618e9884ef25d6ac595933d317dcd6bae63fb83a89f50
manifest hash: 901741cfac7b94e2208ccbbc0a34e0fd5e298efe31aae7d81805c3054568f6c1
```

It is not the Phase-2 pin after the v0.12.0/v11 correctness and realism
corrections. Generate and accept a fresh ten-year run before Phase 2 lands
source data; do not mix artifacts from the two source contracts.

It completed in 1h26m50.27s using `--execution-profile ultra-performance`
(`2` market workers, `16` partition writers, `8` DuckDB threads, a `64`-GB DuckDB ceiling and
`100000`-row spools), with 18,853,019,648-byte (17.56-GiB) peak process RSS. The run
contains 137 logical datasets, 10,198 authoritative Parquet objects, 297,619,898
source/truth rows and one 12,938,129,408-byte DuckDB mirror; the complete folder occupied
19.45 GiB of allocated disk before it was deleted. Its source totals were Shopify 211,284,407 rows,
Business Central 57,623,146, companion 3,154,540 and restricted truth 25,557,805.

Each Shopify market has 525,062 direct-identifier-free registered customers with creation
dates spanning 2011-07-31 through 2026-07-28; each BC company has the same registered
population plus one explicit walk-in account. India has 464,835 purchasing registered
customers and 1,066,591 guest orders (18.03%); the US has 462,176 purchasing registered
customers and 1,041,129 guest orders (18.02%). Registered-customer order-count quantiles
`p25/p50/p75/p90/p99` are `3/7/14/25/51` in India and `3/7/14/24/50` in the US. The
maximum is two orders per registered customer per local day, as configured. Shopify and BC
both have zero orphan customer references, and no customer row contains a direct identifier.

The DuckDB catalogs reconcile 137 datasets, 10,198 Parquet objects and 297,619,898 rows with
zero mismatch. Restricted artifacts were 365 restricted truth Parquet objects under `_truth/` plus
one separately restricted all-source DuckDB mirror; no truth object is public, and the mirror is its
own restricted category rather than part of the `_truth/` set.
An identical invocation reverified all manifest sizes/hashes and returned `reused: true` in
7.52 seconds. No private `.work`, staging directory, temporary DuckDB or WAL remains.

The full v0.11.0 ultra run used 63,820,489,478 temporary work bytes before cleanup and published
20,848,092,042 bytes across 10,202 manifest objects (10,198 Parquet objects plus four
generator-owned run artifacts). Its measured stages were 1,126.320 seconds for simulation,
1,028.355 for extensions, 2,190.984 for source publication, 542.298 for DuckDB and 0.129 for
catalog finalization. Against the earlier v0.10.0 two-worker/4-GiB full-run measurement of
1h40m28.55s, ultra reduced wall time by 13m38.28s (13.6%) but raised peak per-process RSS from
7.27 GiB to 17.56 GiB. Use `safe` on the 16-GB-available demo target; reserve ultra for the
64-GB-or-larger workstation class.

The v0.9.2/v9 run is historical measurement evidence only:

```
historical run: run-98abf242ff98ddc0
config hash: dd4b0d905b3bbe9c8ec0f9a3d8a9cc80d945bc6e41556ad34d518edca0f4874f
```

Its obsolete local run folder was removed after the v10 replacement passed acceptance. It
completed in 1h37m43s and contained 137 logical datasets, 9,480 authoritative Parquet
partitions, 295,522,648 source/truth rows and one 12,614,119,424-byte DuckDB mirror (about 19 GB
for the complete run). It produced 11,692,994 Shopify orders and 30,761,542 realized units.
Daily orders have median 2,942, mean 3,200.93, p95 4,961 and a declared grand-opening stress
maximum of 161,370. The minimum is 410 during the configured April–June 2020 COVID
lockdown/stockout period, not ordinary baseline traffic. Overall fill is 93.4571% (India 94.30%,
US 92.65%). Warehouse peak totals remain within capacity: Mumbai 332,131/750,000, Pune
331,130/500,000, Newark 526,769/750,000 and Brooklyn 117,244/500,000.

The run has 369 published promotion rows, 7 local events, 24 pandemic-phase rows, 162 holidays,
7,306 weather actuals and 51,142 weather forecasts. All 137 source-schema datasets match the
DuckDB catalog; the 9,480 catalog objects reconcile to 295,522,648 rows with zero mismatch.
Real successor tails are present: iPhone 13/14/15/16 sell 14,967/11,057/7,873/3,447 units after
their successor launches instead of stopping at handover. An identical rerun reverified hashes
and returned `reused: true` in 9.8 seconds.

It must **not** be pinned for Phase 2: its Shopify/BC customer masters contain only 750 reused
registered identities per market, all first observed in the opening week, and the old
non-streaming simulation peaked near 88.5 GB RSS. Generator v0.10.0/source contract v10 changed
the deterministic run ID, added the explicit population/acquisition model and bounded execution.
Generator v0.12.0/source contract v11 then superseded that candidate with source-reconciliation
and forecasting-realism corrections. The next Phase-2 pin must therefore be a fresh accepted
v11 run, not an in-place repair or rename of either historical run.

The preset fixes `identity.masterSeed`. The generator is deterministic: the same resolved config
and generator version produce the same config hash, run ID, logical rows and authoritative
CSV/Parquet object hashes, and an immutable rerun is verified and reused. DuckDB is explicitly a
non-authoritative mirror: its table/catalog contents are deterministic, while its internal
physical layout is classified as logical rather than byte determinism. Change `masterSeed`,
scenario configuration or generator version only when a genuinely different synthetic run is
required.

The checked-in high-volume scenario covers `2021-01-01` through `2026-07-27`, uses 36 SKUs per
department across 10 departments (360 per market), starts at 420 orders per store/day
(840 across the two stores before causal lift), and
plans about 1,708,560 orders before holidays, promotions, growth, lifecycle and disruption
factors. Its extraction boundary uses 28 velocity-weighted opening days at the main DCs, no
forced-empty opening SKUs and a 25% observed-demand replenishment buffer. A disposable
January–March 2021 derivative measured 92.44% fill overall (India 93.20%, US 91.70%) with
monthly fill of 94.73%, 93.60% and 88.70%. The March reduction is a truncation artifact of the
disposable derivative: 192 March purchase orders remain in transit at its hard extract boundary.
It is neither a cold-start failure nor a COVID attribution—the configured COVID supply phase is
a step active across all three months. Those POs can land in April in the full run. Peak
inventory remained far below capacity. This slice validates the boundary policy; the selected
full v0.10.0 ten-year run above is the long-horizon acceptance result:

```bash
datagen/.venv/bin/retail-datagen plan \
  -c datagen/configs/multi-market-2021-current-volume.yaml

datagen/.venv/bin/retail-datagen generate \
  -c datagen/configs/multi-market-2021-current-volume.yaml \
  -o datagen/output
```

To use the sole authoring surface, open `datagen/config-builder.html` in a browser, configure the
scenario, and download YAML (default) or JSON. A bundled, locally served YAML runtime provides
conventional block-style YAML import/export without a network dependency. PyYAML is a required
datagen dependency, so the CLI consumes the same YAML directly; `.json` configs remain supported.

The generated database is a single-file view of the same run. The heredoc below is a POSIX
convenience; on Windows, run the same Python body from PowerShell using
`.\datagen\.venv\Scripts\python.exe -` or save it as a `.py` file.

```bash
datagen/.venv/bin/python - <<'PY'
import duckdb
db = "datagen/output/multi-market-showcase/<run-id>/source-run.duckdb"
con = duckdb.connect(db, read_only=True)
print(con.execute("select * from source_object_catalog order by source_path").fetchall())
PY
```

Use `source_object_catalog.table_name` to discover the table corresponding to a source path. All
mirrored source columns intentionally remain text so viewing the database cannot introduce
different inference or rounding from the authoritative CSV/Parquet object.

`retail_intelligence_datagen.egg-info` is not source code and is not needed in the repository.
It is setuptools metadata generated by `pip install -e datagen`; it was removed from `src/` and
`*.egg-info/` is ignored. The active virtual environment may regenerate it locally at any time.

Run the execution-contract and datagen test suites.

Windows PowerShell:

```powershell
$env:PYTHONPATH = "execution\src;datagen\src"
.\datagen\.venv\Scripts\python.exe -m unittest discover -s execution\tests -v
.\datagen\.venv\Scripts\python.exe -m unittest discover -s datagen\tests -v
```

macOS/Linux:

```bash
PYTHONPATH=execution/src:datagen/src \
  datagen/.venv/bin/python -m unittest discover -s execution/tests -v
PYTHONPATH=execution/src:datagen/src \
  datagen/.venv/bin/python -m unittest discover -s datagen/tests -v
```

Re-run the disposable profile benchmark.

Windows PowerShell:

```powershell
$env:PYTHONPATH = "execution\src;datagen\src"
.\datagen\.venv\Scripts\python.exe datagen\tools\benchmark_execution_profiles.py
```

macOS/Linux:

```bash
PYTHONPATH=execution/src:datagen/src \
  datagen/.venv/bin/python datagen/tools/benchmark_execution_profiles.py
```

On the 16-core/128-GB M4 Max, the comparable v0.11.0 90-day showcase measured 47.325 seconds
under `safe`, 41.778 under `performance` and 41.612 under `ultra-performance`. Ultra was 12.1%
faster than safe but only 0.4% faster than performance. Simulation measured
10.519/6.440/6.116 seconds; source publication measured 23.889/21.472/21.542 seconds, showing
that this two-market run is publication/serial-stage constrained once performance is selected.
All profiles produced the same run ID, 534 byte-deterministic object hashes and reconciliation
controls. Largest observed per-process RSS was 582,336,512 / 1,065,992,192 / 1,398,489,088
bytes; this is not concurrent aggregate RSS. CPU utilization was 110.39% / 144.57% / 164.07%.
The benchmark removed all disposable outputs. The v0.11.0 ultra run documented above remains
the comparable full-run benchmark. The next Phase-2 input must be generated by v0.12.0/v11;
changing only an execution profile will not change that new run's scenario config hash or
logical source contract.

What remains outside datagen Phase 1 is downstream landing/adaptation, canonical transformations,
ML outputs and runtime/UI workflows. Datagen does not generate forecasts, recommendations,
exceptions, approvals or users.
