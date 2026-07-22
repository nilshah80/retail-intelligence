# `contracts/` — the shared contract

**Purpose:** the single source of truth shared across the repo — `datagen/` **emits** to it,
`ml/` **ingests** against it, `api/` **serves** against it. This folder is what prevents
cross-language and cross-repo drift.

**Planned contents:**
- **`retail_v2` schema** — canonical entity/column definitions (the authoritative version of
  spec §11): core canonical, cost/price history, competitor, promotions/segments, external
  signals, multi-echelon inventory, supplier performance, forecast/planner outputs, governance.
- **Ingest profile template** — the `mapped_files` profile mapping generator file/column names →
  canonical names (spec §11.10).
- **Fingerprint canonicalization spec** — exact canonical-JSON rules (key ordering, number
  formatting, volatile-key stripping) so SHA-256 is **byte-identical in Python and Go**, plus
  shared golden vectors.
- **Guardrail config** — `pricing_rules.yaml`, `policy.yaml`, `price_response.yaml` (read by both
  the Python engines and the Go serve-time re-validation — never duplicated in code).
- **API contract** — proto / OpenAPI for the Go ↔ UI (and Go ↔ Python scoring service) surface.

**Spec:** §11 (schema), Architecture note (cross-language risks).

_No code yet — information only._
