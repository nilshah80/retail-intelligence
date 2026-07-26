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
  is our **reference implementation** — we reuse/adapt its proven Python modules and re-implement
  its API layer in Go. Don't conflate the two.

## Architecture — two hard splits

**1. Data production vs consumption.** An isolated data-generation concern (`datagen/`, kept
extract-ready) creates one canonical synthetic truth and publishes canonical plus client-shaped
CSV/Parquet/JSONL fixtures. `ml/data` owns immutable raw landing, source validation, mapping +
semantic transformation, canonical validation and curated publication. No generation logic lives
outside `datagen/`; no retailer/platform logic lives in downstream models. Source manifests
declare entity/field and capability coverage: a pure Shopify slice can be validated, but only a
capability-complete composite may be promoted to models.

**2. Python ML + Go API.** ML pipelines are Python; the API/serving/workflow/guardrail layer is
Go. The boundary is the **artifact + fingerprint + PostgreSQL + shared-config contract**, not
in-process calls.

```
 Source-shaped path:
 datagen / retailer / Shopify → raw landing → Gate A → profile/adapter
   → standardized staging → shared transforms → canonical candidate

 Component-test bypass:
 canonical_test fixture → Gate B

 Canonical decision:
 candidate → Gate B ─┬→ partial coverage: validated_partial (stop)
                     └→ capability-complete pass → curated Parquet/DuckDB
                        → features/models/engines → artifacts/DB → Go API
                        → UI/workflow/audit
```

## Monorepo layout

| Folder | Purpose | Language | Origin |
|---|---|---|---|
| `docs/` | Specification, dashboard mockup, decisions | — | authored |
| `plans/` | Phased build plans + task checklists (`local/`, `aws/`) | — | authored |
| `ml/` | Raw landing, adapters/transforms, quality, features, models, engines | Python | reuse + extend M5 PoC |
| `api/` | API, workflow/HITL, serve-time guardrails, RBAC | Go | reimplement (M5 design) |
| `datagen/` | Synthetic truth + canonical/client-shaped publishers — **self-contained, extract-ready** | Python | new |
| `contracts/` | Canonical `retail_v2`, source-profile/transform spec, fingerprints, guardrails, proto/OpenAPI | — | new |
| `db/` | PostgreSQL migrations (single owner: Alembic) | — | copy/extend from M5 PoC |
| `ui/` | Dashboard front-end (the mockup in `docs/` is the target) | TBD | new |
| `deploy/` | docker-compose / infra | — | new |

**Extraction rule for `datagen/`:** it may depend on `contracts/` and nothing else in the repo,
so it can later be lifted into its own repo cleanly.

## Tech stack

- **Python** — `ml/` and `datagen/` (LightGBM, statsmodels, pandas/DuckDB). Adapt the M5
  `mapped_files`/quality patterns into a two-gate transform pipeline; copy/adapt its `features/`,
  `models/`, and `engines/`.
- **Go** — `api/` (serving, workflow/HITL, guardrail re-validation, staleness 409/503, RBAC).
  The M5 PoC's `api/` design carries over; the code is rewritten in Go.
- **PostgreSQL** — workflow, approvals, recommendations, audit. **Parquet/DuckDB** — lake +
  features. **MLflow** — run/metric tracking.
- **Contract version:** `retail_v2` (see `docs/demand_forecast_poc_spec.md` §11).

## Start here (reading order)

1. **This README** — orientation.
2. **`docs/demand_forecast_poc_spec.md`** — the full spec: data points, models, guardrails,
   synthetic-data approach, source transformation boundary, Shopify example, mandatory/derived
   elements, and the complete canonical `retail_v2` schema (§11). This is the source of truth.
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
