# `db/` — PostgreSQL migrations

**Purpose:** the operational database schema — the shared state between the Python pipeline
(writes forecasts, recommendations, activations) and the Go API (workflow, approvals, audit).

**Single owner:** **Alembic (Python)** is the one migration owner; the Go `api/` generates its
structs from the resulting schema. (Avoids two tools racing on one schema.)

**Portability gate:** migration authoring and local upgrade/downgrade commands must run from
PowerShell on Windows and a normal terminal on macOS/Linux without Bash wrappers. Paths and
subprocesses use platform-native APIs; migrations cannot depend on executable bits, symlinks or
case-only filename distinctions. CI applies the same migration chain to PostgreSQL on all three
host OS families before the database layer is complete.

**Planned tables:**
- **Reused and extended from the M5 PoC (`[REUSE + EXTEND]`, migrations 001/002/003):** `workflow_sessions`,
  `draft_orders`, `approvals`, `exceptions` (+ notes, status history), `audit_log`, `policy_edits`,
  `pricing_activations`, `price_recs`, `price_rec_reviews`, `adoption_metrics`. Preserve workflow
  semantics, but add explicit market/currency/resolved-policy identity to pricing records and
  demand/supply location or warehouse/lane context to replenishment drafts.
- **New for `retail_v2` (`[NEW]`):** `forecast_versions` / `forecast_series` / `forecast_drivers`,
  `planner_adjustments`, `inventory_cost`, `competitor_matches`, `transfer_orders`, `allocations`,
  `model_registry`, `model_drift`, `users` / `roles`, `alert_rules`, `data_sources`,
  `source_mapping_configs`,
  `ingest_runs`, `reconciliation_results`, `quality_violations`, `quarantine_records`, and
  `source_crosswalks`.

**Spec:** §11.8–11.10 (new tables + ingest lineage),
`../retail_ai/docs/schema.md` (M5 workflow tables to copy).

_No code yet — information only._
