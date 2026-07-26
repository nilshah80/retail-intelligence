# `contracts/` — the shared contract

**Purpose:** the single source of truth shared across the repo. `datagen/` builds an internal truth
against it, `ml/data` transforms raw sources into it, and `api/` serves artifacts derived from it.
Raw retailer/platform schemas do not have to match it. This folder prevents source, language and
cross-repo drift.

**Planned contents:**
- **`retail_v2` schema** — canonical entity/grain/column definitions (the authoritative version
  of spec §11): versioned sales, exact money, adjustments and demand-to-supply fulfillment facts;
  cost/price history; competitor; promotions/segments; external signals; multi-echelon inventory;
  supplier performance; outputs/governance.
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
- **Guardrail config** — `pricing_rules.yaml`, `policy.yaml`, `price_response.yaml` (read by both
  the Python engines and the Go serve-time re-validation — never duplicated in code).
- **API contract** — proto / OpenAPI for the Go ↔ UI (and Go ↔ Python scoring service) surface.

**Spec:** Architecture/data flow, §4.1 (two gates), §11 (canonical schema and source adapters).

_No code yet — information only._
