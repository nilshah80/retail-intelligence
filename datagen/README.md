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

## Source-data contract

The generator produces, from the same causal simulation:

- Shopify-shaped products, variants, locations, orders/lines, fulfillment and inventory
  observations at the fidelity enabled by config;
- Business Central-shaped items, locations, customers/vendors, sales and inventory/finance
  extracts at the fidelity enabled by config;
- external/companion datasets for holidays, weather, local events, promotions, competitors,
  macro and FX;
- a `source-run-manifest` containing generator/spec version, resolved config hash, seed/run
  identity, market/location topology, generated source objects/files, row/control totals and
  hashes;
- hidden synthetic truth used only to evaluate causal recovery and source-to-canonical
  reconciliation. Hidden truth uses generator vocabulary and is never a `retail_v2` fixture.

Formats and compression are publication choices, not source-semantic requirements. The first
working publisher may emit the formats supported by the reused generator; `ingestion/` owns
format adapters. YAML and JSON config exports must nevertheless be equivalent and honestly
declare the formats actually written.

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

- `multi-market-showcase` uses a response-rich profile in both India and US (for example, 60 SKUs
  per department and at least eight price-change events per SKU) so downstream tests can
  demonstrate pricing in both currencies.
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

**Config-driven screen-completeness extensions, not blockers for the first forecast/revenue-
pricing round-trip:**

- exhaustive split-fulfillment/status histories and requested-vs-processed return evidence;
- successful/failed refund-transaction and webhook/HMAC conformance fixtures;
- every Shopify named inventory state;
- complete PO/receipt, inbound-shipment, batch/expiry and supplier-performance projections;
- realistic competitor-product matching and richer customer/segment histories;
- full CSV/Parquet/JSONL/compression matrix.

These extensions are added when their corresponding inventory, supplier, promotion, competitor
or connector-conformance screens enter acceptance. They remain generator-source features;
canonical derivation belongs to `ingestion/`.

## Dashboard source-coverage map

Datagen supplies source evidence only where a dashboard capability needs upstream retail facts.
It does not manufacture forecasts, recommendations, approvals, alerts, users, model registry or
audit rows—those are PoC runtime outputs/configuration.

| Dashboard area | Datagen source evidence | Delivery tier |
|---|---|---|
| Demand Forecast / Overview / Drivers | orders/lines or sales transactions, products, stores, price/promo history, holiday/calendar, weather, local event, macro, inventory availability | Core |
| Price Recommendations / Simulation | local-currency price history, tax, inventory and optional temporal cost/competitor inputs | Revenue pricing core; margin/cost and competitor depth as enabled |
| Competitor Monitor | competitor product attributes, observations, availability/promos and hidden match truth | Extension |
| Promotion Planner | promotion + promotion-SKU history; segment assignment; basket/order-line history for bundle/cannibalisation tests | Extension |
| Inventory Overview / Store | explicit nodes, inventory observations and enabled committed/reserved/damaged/ATP states | Core observations; full state matrix extension |
| Warehouse Inventory | DC master, capacity/utilization, blocked stock, receipts, inbound status, fill and dock-to-stock observations | Extension |
| Ageing / Expiry / Waste / Valuation | receipt/cost layers, batch/lot, manufacture/receipt/expiry dates, waste events and optional ERP↔WMS comparison observations | Extension |
| Transfers | transfer request/order/shipment status and lane/location evidence | Extension |
| Replenishment / Suggested Orders | supplier/item terms, MOQ/pack, lead times, open PO/receipts, capacity and budget source inputs | Extension |
| Supplier Planning / Safety Stock | supplier OTD, capacity confirmation and lead-time history/variability | Extension |
| Allocation & Fulfillment | demand requests, supply pools and source fulfillment locations; allocation recommendation remains a PoC output | Extension |
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
checksumming/manifest logic and the Typer/logging shell may be adapted; mutable counter-based
ID allocation must become stable-key allocation. The old run identity, domain checkpoint state,
writer dataset registry, controller and CLI must be redesigned after the generator-owned config
and source-data specification are fixed. Old canonical/ML-ready publication concepts and the
fixed authoritative `retail.duckdb` layout are not part of the new generator contract.

**Spec:** §9.

_No code yet — information only._
