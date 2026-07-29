# `contracts/` — the shared contract

**Purpose:** the single source of truth for ingestion output, downstream artifacts and API
behavior. `ingestion/` transforms raw sources into it, `ml/` consumes it, and `api/` serves
artifacts derived from it. Raw retailer/platform/datagen schemas do not have to match it.

`datagen/` deliberately does **not** depend on this folder. It owns a separate source-data
specification and source-run manifest; the profile/adapter in `ingestion/` is the boundary between
that source contract and this canonical contract.

Hardware/runtime tuning is also deliberately outside this canonical contract. The neutral
`execution/` package owns versioned execution-profile definitions and Python golden vectors;
it contains no retailer, source or canonical schema.

**Planned contents:**
- **`retail_v2` schema** — canonical entity/grain/column definitions (the authoritative version
  of spec §11): versioned sales, exact money, adjustments and demand-to-supply fulfillment facts;
  cost/price history; competitor; promotions/segments; external signals; multi-echelon inventory;
  supplier performance; outputs/governance. Single-axis geography uses market-qualified
  `geo_scope_*`; supplier/promotion merchandise rules use `merch_scope_*` with
  `sku > dept > category`; promotion applicability keeps its explicit multi-axis qualifier rows.
- **Temporal identity rules** — explicit monotonic integers for cumulative/correctable facts;
  stable natural key + effective/observation time + `known_as_of` for observation/reference facts,
  with deterministic cutoff selection and divergent-duplicate quarantine.
- **Money/FX rules** — sales and sell prices use location operating currency; presentment money is
  audit-only. Reporting FX is exact local/base→reporting/quote `DECIMAL(38,18)` with
  exponent-aware per-fact `ROUND_HALF_EVEN` and shared Python/Go golden vectors.
- **Source-profile schema** — source system/schema/snapshot, formats and paths/objects, source and
  canonical grains, keys, mappings, joins, filters, code maps, timezone/business day, currency/
  unit/tax basis, `known_as_of`, event/API authenticity, pre-landing field-projection policy,
  transform versions and reconciliation controls.
- **Coverage/capability manifest** — full vs partial entity/field coverage, valid-zero policy,
  source controls, companion/merge precedence and the capability mask; partial slices can be
  `validated_partial` but never promoted as complete data.
- **Transformation extension contract** — a declarative profile drives the default
  `mapped_files` normalizer or a thin versioned source adapter; both emit standardized staging,
  after which source-neutral domain transforms produce canonical `retail_v2`.
- **Staging schemas + executor boundary** — normalized merchandise, adjustment, fulfillment,
  inventory, receipt and dimension/signal envelopes; adapters end at staging and named shared
  transforms alone create canonical aggregates.
- **Approved source-mapping contract** — immutable, authorized mapping configuration separated
  from runtime resolved crosswalk/audit rows.
- **Lineage/reconciliation schema** — raw hashes, profile/adapter/transform versions, ingest run,
  input/filter/reject/output counts, control totals and reason-coded quarantine.
- **Fingerprint canonicalization spec** — exact canonical-JSON rules (key ordering, number
  formatting, volatile-key stripping) so SHA-256 is **byte-identical in Python and Go**, plus
  shared golden vectors.
- **Guardrail config** — `pricing_rules.yaml`, `policy.yaml`, `price_response.yaml` with
  deterministic global-default → `market_id + currency_code` resolution. Currency-neutral
  percentages/evidence gates may inherit defaults; absolute money, grid/step and price-ending
  conventions must be market-scoped. Python engines and Go serve-time re-validation read and
  fingerprint the same resolved payload—never duplicated in code.
- **API contract** — proto / OpenAPI for the Go ↔ UI (and Go ↔ Python scoring service) surface.

**Spec:** Architecture/data flow, §4.1 (two gates), §11 (canonical schema and source adapters).

_No code yet — information only._
