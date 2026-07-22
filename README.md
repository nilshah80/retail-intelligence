# Retail Intelligence

New Retail AI PoC — **Dynamic Pricing & Demand Forecasting** for an Indian multi-category,
multi-store, multi-currency retailer. This monorepo is where the PoC behind the
`ai_retail_intelligence_dashboard_multicurrency_v6` dashboard will be built.

> **Status:** planning / scaffolding. **No application code yet** — this repo currently holds
> the specification and orientation docs only. Application code (Python ML, Go API, data
> generator) will be added into the folders below as we start building.

## What this is (and is not)

- **Is:** a fresh, product-oriented PoC targeting the v6 dashboard — Indian retail
  (Footwear / Apparel / Electronics / Beauty; Mumbai, Noida, Bengaluru, Kolkata, Chennai;
  base currency INR with USD/EUR/GBP display).
- **Is not:** the earlier **M5-based PoC**, which lives separately at `../retail_ai`. That PoC
  is our **reference implementation** — we copy its proven Python modules and re-implement its
  API layer in Go. Don't conflate the two.

## Architecture — two hard splits

**1. Data production vs consumption.** A separate data-generation concern (`datagen/`, kept
extract-ready) produces CSV/Parquet files; the rest of the PoC only ingests → transforms →
models → serves. No data-generation code lives outside `datagen/`.

**2. Python ML + Go API.** ML pipelines are Python; the API/serving/workflow/guardrail layer is
Go. The boundary is the **artifact + fingerprint + PostgreSQL + shared-config contract**, not
in-process calls.

```
 datagen/ (separable)          ml/ (Python)                         api/ (Go)
 CSV/Parquet files   ──▶  ingest → quality → features →   ──▶  reads artifacts + PostgreSQL
 per §11 schema           models (LightGBM, Poisson-EB) →       serves UI, owns workflow/HITL,
                          engines (reorder/pricing/alloc) →     guardrail re-validation, 409/503,
                          writes artifacts + fingerprints        RBAC, audit
```

## Monorepo layout

| Folder | Purpose | Language | Origin |
|---|---|---|---|
| `docs/` | Specification, dashboard mockup, decisions | — | authored |
| `plans/` | Phased build plans + task checklists (`local/`, `aws/`) | — | authored |
| `ml/` | Batch ML pipeline: ingest, features, models, engines | Python | copy from M5 PoC |
| `api/` | API, workflow/HITL, serve-time guardrails, RBAC | Go | reimplement (M5 design) |
| `datagen/` | Synthetic data generator — **self-contained, extract-ready** | Python | new |
| `contracts/` | `retail_v2` schema, fingerprint spec, guardrail YAMLs, proto/OpenAPI — the shared contract | — | new |
| `db/` | PostgreSQL migrations (single owner: Alembic) | — | copy/extend from M5 PoC |
| `ui/` | Dashboard front-end (the mockup in `docs/` is the target) | TBD | new |
| `deploy/` | docker-compose / infra | — | new |

**Extraction rule for `datagen/`:** it may depend on `contracts/` and nothing else in the repo,
so it can later be lifted into its own repo cleanly.

## Tech stack

- **Python** — `ml/` and `datagen/` (LightGBM, statsmodels, pandas/DuckDB). Copy `data/`,
  `features/`, `models/`, `engines/` from the M5 PoC.
- **Go** — `api/` (serving, workflow/HITL, guardrail re-validation, staleness 409/503, RBAC).
  The M5 PoC's `api/` design carries over; the code is rewritten in Go.
- **PostgreSQL** — workflow, approvals, recommendations, audit. **Parquet/DuckDB** — lake +
  features. **MLflow** — run/metric tracking.
- **Contract version:** `retail_v2` (see `docs/demand_forecast_poc_spec.md` §11).

## Start here (reading order)

1. **This README** — orientation.
2. **`docs/demand_forecast_poc_spec.md`** — the full spec: data points, models, guardrails,
   synthetic-data approach, mandatory/derived elements, and the complete `retail_v2` schema
   (§11). This is the source of truth.
3. **`docs/ai_retail_intelligence_dashboard_multicurrency_v6.html`** — the target UI; open in a
   browser to see every screen the PoC must populate.
4. **`docs/OPEN_DECISIONS.md`** — decisions to lock before/while building.
5. **`plans/local/plan.md`** + **`plans/local/tasks.md`** — the phased local build (Phase 1 =
   synthetic data). **`plans/aws/`** — the cloud deployment plan (after local works).

## Reference: the M5 PoC (`../retail_ai`)

The spec's `[REUSE]` tags point at modules in `../retail_ai` to copy or re-implement. **We have
not copied any code yet** — this repo is information-only for now. When we start building, the
plan is: `retail_ai/{data,features,models,engines}` → `ml/`; `retail_ai/api` design → Go `api/`;
`retail_ai/migrations` (Alembic) → `db/`.
