# `db/` — PostgreSQL migrations

**Purpose:** the operational database schema — the shared state between the Python pipeline
(writes forecasts, recommendations, activations) and the Go API (workflow, approvals, audit).

**Single owner:** **Alembic (Python)** is the one migration owner; the Go `api/` generates its
structs from the resulting schema. (Avoids two tools racing on one schema.)

**Phase 3 serving boundary:** PostgreSQL first enters as a read-optimized projection of an
accepted immutable forecast bundle. The offline materializer verifies every artifact and performs
one transaction; the Go API never reads forecast Parquet. Materialization and activation are
separate records, so acceptance does not silently become active. Phase 6 extends the same database
with mutable workflow/governance state.

**Portability gate:** migration authoring and local upgrade/downgrade commands must run from
PowerShell on Windows and a normal terminal on macOS/Linux without Bash wrappers. Paths and
subprocesses use platform-native APIs; migrations cannot depend on executable bits, symlinks or
case-only filename distinctions. Developer-run release validation applies the same migration
chain to PostgreSQL on all three host OS families before the database layer is complete;
repository CI is prohibited.

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

**Applied chain (head `0019_supplier_identity`).** Every client that names the required head must
name the same one; `contracts/python/tests/test_serving_migration_pin.py` derives the head from the
Alembic graph and fails until all six pins agree, so a migration is not complete until the ML
materializer, the ML publisher's manifest evidence, both Go read models, the schema test and the two
generated evidence records have moved together.

| Revision | What it publishes, and why the screen needed it |
| --- | --- |
| `0010_inventory_serving` | The inventory/replenishment projection surface. |
| `0011_inventory_sku_dimension` | Category and accepted unit cost. Without them every rupee caption could only render a unit count. |
| `0012_sku_dimension_trailing` | Trailing daily demand, for cover and sell-through. |
| `0013_sku_dimension_names` | Display names. Tables showed `india-west:mumbai-dc` where the reference reads "West DC". |
| `0014_warehouse_capacity` | The storage ceiling. Capacity Utilization had no denominator. |
| `0015_recommendation_lead_time` | The resolved lead time. The engine computed it to size the protection period and discarded it, so Lead Time and Expected Receipt had no fact behind them. |
| `0016_projection_grain_indexes` | A UNIQUE index on every projection's declared grain — see below. |
| `0017_inbound_summary` | Inbound reliability per node. Delayed Receipts had been counting open orders as late. |
| `0018_market_policy_scope` | The market budget ceilings, and the merchandise scope a supplier serves. |
| `0019_supplier_identity` | The supplier's name and its open purchase-order value. |

**Why 0016 is not an optimisation.** 0010 gave each projection one index on
`(inventory_version_id, market_id)` and no key. Every read-model join between projections matches on
the *full* grain, so each one hash joined the whole table — and that cost grows with every
activation, because a serving table holds every materialized version. At fifteen versions the
positions aggregate took 1.4s alone and 8.8s with the outbound-need roll-up joined, which put two
routes past the server's write timeout: they closed the connection rather than returning a governed
503, and the page sat on "Loading live retail data..." indefinitely. The indexes take those to 0.10s
and 0.02s.

They are UNIQUE rather than plain because `ARTIFACT_GRAIN` was checked at publish time and enforced
nowhere. A duplicate row would have silently multiplied every value it was joined into — exactly
what 0011 wrote a primary key to prevent for the dimension, which was the only table that had one.

Indexes alone are not sufficient: after a bulk load PostgreSQL's stale estimates will abandon them,
so the materializer `ANALYZE`s each table it writes. See the root README §8c.

**Revision ids are capped at 32 characters** — `alembic_version.version_num` is
`varchar(32)`, and a longer id fails the upgrade *after* the DDL has run, with a truncation error
that names the column rather than the id.

For the Docker Desktop Phase 3 stack:

```powershell
python tools/dev.py services up
python tools/dev.py db-env
python tools/dev.py db-upgrade
python tools/dev.py db-current
```

`RETAIL_POSTGRES_DSN` may override the local Compose connection. Alembic never owns MLflow's
tables; application tables live under `retail_serving`, while MLflow manages its own metadata in
the database's default schema. The migration ledgers are also isolated:
`retail_intelligence_alembic_version` belongs to this repository and MLflow retains its own
`alembic_version`.
