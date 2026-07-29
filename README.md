# Retail Intelligence

New Retail AI PoC — **Dynamic Pricing & Demand Forecasting** for a multi-category retailer that
may operate stores and warehouses in more than one market. The demo tenant is India-led, while
synthetic scenarios may combine India, the United States, the United Kingdom and the PoC's
European representative market (Germany). This monorepo is where the PoC behind the
`ai_retail_intelligence_dashboard_multicurrency_v6` dashboard will be built.

> **Status:** Phase 1 datagen v0.12.0/source contract v11 is implemented. It corrects source
> reconciliation and forecasting-realism defects found after the measured v0.11.0 ten-year run,
> so that older run is benchmark evidence rather than the Phase-2 pin. A fresh v0.12.0 ten-year
> run must pass acceptance and be pinned before ingestion implementation starts. The shared
> safe/balanced/performance/ultra-performance profiles change execution only; they do not change
> scenario semantics. Downstream ingestion/ML/API/UI remain planned or scaffolded.

## What this is (and is not)

- **Is:** a fresh, product-oriented PoC targeting the v6 dashboard — 10 retail departments
  spanning Apparel, Electronics, Groceries, Home, Beauty, Health, Sports, Toys & Baby,
  Books & Stationery and Automotive; explicit store and warehouse topology; tenant reporting currency INR,
  and local transaction currencies INR/USD/GBP/EUR.
- **Is not:** the earlier **M5-based PoC**, which lives separately at `../retail_ai`. That PoC
  is our **reference implementation** — we reuse/adapt its proven Python modules and re-implement
  its API layer in Go. Don't conflate the two.

## Architecture — three hard ownership boundaries

**1. Source production vs ingestion.**

- `datagen/` owns its own scenario and source-data specification. Its HTML Config Builder is the
  only supported authoring surface and exports conventional YAML by default while retaining the
  complete JSON configuration. The
  generator publishes Shopify-shaped, Business Central-shaped and external/companion source
  datasets in one selected authoritative CSV/Parquet format, one all-source
  `source-run.duckdb` browsing mirror, a
  source-run manifest and hidden synthetic truth. The single DuckDB contains restricted truth
  when truth is enabled and is permissioned accordingly. Datagen never imports or emits
  `retail_v2`, Gate A/B rules, canonical `known_as_of` rules or ingestion transforms. Its v11
  contract includes a tested 2005–2024 preset, opening-incumbent and later product/SKU launches,
  overlapping predecessor/successor runout with lifecycle promotions, config-owned phased
  pandemic/supply disruption, and a Config Builder-owned customer population/acquisition model.
  Long-horizon rows use bounded disk spools, causally independent market processes, concurrent
  partition publication and bounded DuckDB settings. The Config Builder exports execution YAML
  separately from scenario YAML/JSON, and execution tuning does not alter scenario identity or
  business data.
- `ingestion/` owns immutable raw landing, Gate A, source profiles/adapters, standardized staging,
  source-neutral transformations, canonical `retail_v2`, Gate B and curated Parquet/DuckDB.
  Missing source timestamps, versions, formats or manifest details are handled or derived here
  under an explicit adapter/profile policy; they are not universal source requirements.

**2. Ingestion vs ML.**

- `ml/` consumes only capability-complete curated data. No source, retailer, Shopify or Business
  Central branching is allowed in features, models or decision engines.

**3. Python ML + Go API.** ML pipelines are Python; the API/serving/workflow/guardrail layer is
Go. The boundary is the **artifact + fingerprint + PostgreSQL + shared-config contract**, not
in-process calls.

```
 datagen / retailer / Shopify / BC / external sources
                    │
                    ▼
 ingestion: immutable raw landing → Gate A → profile/adapter
          → standardized staging → source-neutral transforms
          → canonical retail_v2 candidate → Gate B
                    ├── validated_partial (stop)
                    └── capability-complete pass
                               │
                               ▼
                    curated Parquet/DuckDB
                               │
                               ▼
 ml: features → models → engines → artifacts/DB
                               │
                               ▼
                    Go API → UI/workflow/audit
```

## Monorepo layout

| Folder | Purpose | Language | Origin |
|---|---|---|---|
| `docs/` | Specification, dashboard mockup, decisions | — | authored |
| `plans/` | Phased build plans + task checklists (`local/`, `aws/`) | — | authored |
| `ingestion/` | Raw landing, gates, source profiles/adapters, staging, transforms, canonical + curated publication | Python | new + adapt M5 data patterns |
| `ml/` | Curated-data consumers: features, models, engines and artifacts | Python | reuse + extend M5 PoC |
| `api/` | API, workflow/HITL, serve-time guardrails, RBAC | Go | reimplement (M5 design) |
| `datagen/` | Config Builder + source-isolated simulator and Shopify/BC/companion publishers — **extract-ready** | Python | reuse + extend generator PoC |
| `execution/` | Versioned source-neutral safe/balanced/performance/ultra-performance profile schema, Python resolver and golden vectors shared by Python jobs | Python + JSON | new |
| `contracts/` | Canonical `retail_v2`, source-profile/transform spec, fingerprints, guardrails, proto/OpenAPI | — | new |
| `db/` | PostgreSQL migrations (single owner: Alembic) | — | copy/extend from M5 PoC |
| `ui/` | Dashboard front-end (the mockup in `docs/` is the target) | TBD | new |
| `deploy/` | docker-compose / infra | — | new |

**Extraction rule for `datagen/`:** it does not import `contracts/`, `ingestion/`, `ml/` or
`api/`. Its only monorepo-level dependency is the independently installable, business-neutral
`execution/` package. Ingestion depends on the published datagen source contract, never the
reverse, so `datagen/` can later be lifted with that small operational package without taking
`retail_v2` with it.

## Tech stack

- **Python** — `execution/`, `datagen/`, `ingestion/` and `ml/` (LightGBM, statsmodels,
  pandas/DuckDB). Adapt
  the M5 `mapped_files`/quality patterns into `ingestion/`; copy/adapt its `features/`, `models/`,
  and `engines/` into `ml/`.
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
5. **`datagen/README.md`** + **`execution/README.md`** + **`ingestion/README.md`** — the exact
   source-generation, operational-profile and source-to-canonical ownership boundaries.
6. **`plans/local/plan.md`** + **`plans/local/tasks.md`** — the phased local build (Phase 1 =
   source generator and Config Builder; Phase 2 = ingestion/transformation).
   **`plans/local/phase2-implementation-plan.md`** is the detailed Phase-2 proposal for review.
   **`plans/aws/`** is the cloud deployment plan (after local works).

## Reference implementations

The spec's `[REUSE]` tags point at `../retail_ai` modules to copy or re-implement for downstream
phases. The datagen implementation separately adapts portable primitives and the rich
product/variant approach from `../retail-synthetic-data-generator`; its exact reuse decisions are
recorded in `datagen/REUSE_AUDIT.md`. The remaining plan is: M5 data-quality/mapping patterns →
`ingestion/`; `retail_ai/{features,models,engines}` → `ml/`; `retail_ai/api` design → Go `api/`;
`retail_ai/migrations` (Alembic) → `db/`.
