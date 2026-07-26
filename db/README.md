# `db/` — PostgreSQL migrations

**Purpose:** the operational database schema — the shared state between the Python pipeline
(writes forecasts, recommendations, activations) and the Go API (workflow, approvals, audit).

**Single owner:** **Alembic (Python)** is the one migration owner; the Go `api/` generates its
structs from the resulting schema. (Avoids two tools racing on one schema.)

**Planned tables:**
- **Reused from the M5 PoC (`[REUSE]`, migrations 001/002/003):** `workflow_sessions`,
  `draft_orders`, `approvals`, `exceptions` (+ notes, status history), `audit_log`, `policy_edits`,
  `price_recs`, `price_rec_reviews`, `adoption_metrics`.
- **New for `retail_v2` (`[NEW]`):** `forecast_versions` / `forecast_series` / `forecast_drivers`,
  `planner_adjustments`, `inventory_cost`, `competitor_matches`, `transfer_orders`, `allocations`,
  `model_registry`, `model_drift`, `users` / `roles`, `alert_rules`, `data_sources`,
  `source_mapping_configs`,
  `ingest_runs`, `reconciliation_results`, `quality_violations`, `quarantine_records`, and
  `source_crosswalks`.

**Spec:** §11.8–11.10 (new tables + ingest lineage),
`../retail_ai/docs/schema.md` (M5 workflow tables to copy).

_No code yet — information only._
