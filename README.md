# Retail Intelligence

New Retail AI PoC — **Dynamic Pricing & Demand Forecasting** for a multi-category retailer that
may operate stores and warehouses in more than one market. The demo tenant is India-led, while
synthetic scenarios may combine India, the United States, the United Kingdom and the PoC's
European representative market (Germany). This monorepo is where the PoC behind the
`ai_retail_intelligence_dashboard_multicurrency_v6` dashboard will be built.

> **Status:** Phase 1 datagen v0.13.0/source contract v12 and the Phase 2 governed ingestion
> vertical slice are implemented. The accepted ten-year input is
> `run-c5eb1506ecd4c550` (2016-07-28 through 2026-07-28), landed as immutable snapshot
> `681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b`. Gate A, bounded
> Shopify/Business Central/companion adapters, standardized staging, source-neutral transforms,
> Gate B, exact reconciliation and atomic curated Parquet/DuckDB publication run end to end.
> The initial Aarv-based Go API exposes the accepted evidence. The first React screen proved API
> connectivity but is not an accepted UI deliverable; it must be rebuilt against the strict v6
> HTML parity/data gates recorded in `plans/local/tasks.md`.
> Shared safe/balanced/performance/ultra-performance profiles change execution only; they do not
> change source interpretation, canonical meaning or governed semantic fingerprints.
>
> **Phase 3 status:** the v12 source rebaseline is accepted and frozen as the ML input pin.
> Native effective-dated `storeAssortment.observedAt` makes all 4,275,653 materialized
> zero-demand rows origin-safe after local business-day close. Forecast authorization is
> **NO-GO** after Review #2: run `fr_92135aa7b5215b69` reports a 53.47% paired seasonal-naive
> improvement but drops 102,804 systematically harder champion rows, so acceptance-v2 fails A1's
> complete overall comparison. Feature schema v4 preserves origin-observed events, removes
> unavailable future calendar-event features and binds the Parquet descriptor into identity.
> Forecast-run v2/verifier v3 and migration 0005 prevent the former verifier-v2 materialization
> from serving. A new feature build, backtest, immutable publication and activation are required;
> no accepted Phase 3 forecast currently exists under the repaired authority.

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
  `retail_v2`, Gate A/B rules, canonical `known_as_of` rules or ingestion transforms. Its v12
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
  under an explicit adapter/profile policy; they are not universal source requirements. Source
  contract v12 adds a native assortment observation timestamp so origin-safe zero-demand labels
  can be derived after each covered business day; older v11 inputs retain their explicit
  point-in-time capability downgrade.

**2. Ingestion vs ML.**

- `ml/` consumes only capability-complete curated data. No source, retailer, Shopify or Business
  Central branching is allowed in features, models or decision engines.

**3. Python ML + Go API.** ML pipelines are Python; the API/serving/workflow/guardrail layer is
Go, with [Aarv](https://github.com/nilshah80/aarv) as the HTTP web framework. The boundary is the
**artifact + fingerprint + PostgreSQL + shared-config contract**, not in-process calls. Immutable
ML bundles remain the publication authority; a verified offline materializer projects accepted
forecast data into PostgreSQL before the Go API can serve it. Request handlers never scan Parquet.

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
| `api/` | Aarv-based API, workflow/HITL, serve-time guardrails, RBAC | Go | reimplement (M5 design) |
| `datagen/` | Config Builder + source-isolated simulator and Shopify/BC/companion publishers — **extract-ready** | Python | reuse + extend generator PoC |
| `execution/` | Source-neutral safe/balanced/performance/ultra-performance profile schema, Python resolver and golden vectors shared with the native Go resolver | Python + Go + JSON | new |
| `contracts/` | Canonical `retail_v2`, source-profile/transform spec, fingerprints, guardrails, proto/OpenAPI | — | new |
| `db/` | PostgreSQL migrations (single owner: Alembic) | — | copy/extend from M5 PoC |
| `ui/` | Dashboard front-end (the mockup in `docs/` is the target) | React + TypeScript | new |
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
- **Go + [Aarv](https://github.com/nilshah80/aarv)** — `api/` (serving, workflow/HITL,
  guardrail re-validation, staleness 409/503, RBAC). Aarv owns HTTP routing, binding,
  middleware and lifecycle only; the M5 PoC's API behavior carries over into framework-neutral
  internal packages. The versioned OpenAPI contract remains under `contracts/`.
- **PostgreSQL** — read-optimized API projections plus workflow, approvals, recommendations and
  audit. **Parquet/DuckDB** — immutable lake, analytical build and features. **MLflow** —
  run/metric tracking.
- **Contract version:** `retail_v2` (see `docs/demand_forecast_poc_spec.md` §11).

### When stateful infrastructure is introduced

| Component | First required phase | Why it is not required earlier |
|---|---|---|
| PostgreSQL | **Phase 3 serving** | Phase 3 uses an Alembic-owned, read-only forecast projection so the API does not scan Parquet and the same schema can move to AWS RDS. Phase 6 adds mutable workflow state: approvals, overrides, recommendations, idempotency, RBAC and audit. |
| MLflow tracking | **Phase 3** | Demand training/backtests need run parameters, metrics, model artifacts and lineage. Historical candidate telemetry remains in its original file store, while the repaired rerun and future runs use the shared Compose MLflow server backed by PostgreSQL. MLflow remains telemetry; immutable governed forecast artifacts remain authoritative. |
| Docker Compose | **Phase 3 serving** | Docker Desktop provides PostgreSQL for the forecast API projection and a shared MLflow server. Phase 6 extends the same stack with mutable workflow state and API/UI services; batch data jobs remain explicit commands. |

Do not add GitHub Actions or another repository CI workflow during this PoC or later hardening.
Use the authoritative `tools/dev.py` commands and component tests; collect required portability
evidence manually on supported operating-system hosts. `contracts/validation-policy.yaml` is the
committed authority, and contract validation rejects repository workflow files.
`python3 tools/dev.py verify` is the single stateful local phase-exit gate; it requires the
Compose PostgreSQL service and an activated verified forecast projection.

## End-to-end local runbook

Run commands from the repository root unless a step explicitly says otherwise. The commands below
use the accepted deterministic ten-year demo:

| Item | Value |
|---|---|
| Source dates | `2016-07-28` through `2026-07-28` |
| Source run | `run-c5eb1506ecd4c550` |
| Config | `datagen/configs/multi-market-10-year-demo.yaml` |
| Immutable snapshot | `681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b` |
| Source output | `datagen/output/multi-market-10-year-demo/run-c5eb1506ecd4c550/` |
| Raw landing | `ingestion/data/raw/snapshots/681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b/` |
| Curated output | `ingestion/data/curated/run-c5eb1506ecd4c550/` |
| Accepted evidence | `ingestion/data/evidence/run-c5eb1506ecd4c550/` |
| Curated database | `ingestion/data/curated/run-c5eb1506ecd4c550/retail_v2.duckdb` |

The data directories are intentionally gitignored. A fresh clone therefore contains the code and
configuration, not the 34+ GiB accepted local artifacts. Generate and ingest the run, or restore
the exact accepted artifacts from governed storage, before starting the API.

### 1. Prerequisites

- Python 3.12 or 3.13 for the pinned ML/database stack;
- Go 1.25 or newer;
- Node.js 22 and npm;
- Docker Desktop with Docker Compose v2 for the local PostgreSQL and MLflow services;
- at least 60 GiB free disk for source, immutable landing, rebuildable work and curated output;
- at least 16 GiB available RAM when using `safe`. Reserve `ultra-performance` for a machine with
  approximately 64 GiB available to the job.

The four execution profiles alter only resource use and runtime. `safe`, `balanced`,
`performance` and `ultra-performance` must produce the same governed semantic result.

### 2. Install the local environments

Windows PowerShell:

```powershell
py -3 -m venv datagen\.venv
.\datagen\.venv\Scripts\python.exe -m pip install --upgrade pip
.\datagen\.venv\Scripts\python.exe -m pip install -e datagen
py -3 tools\dev.py envs

Set-Location api
go mod download
Set-Location ..\ui
npm ci
Set-Location ..
```

macOS/Linux:

```bash
python3 -m venv datagen/.venv
datagen/.venv/bin/python -m pip install --upgrade pip
datagen/.venv/bin/python -m pip install -e datagen
python3 tools/dev.py envs

(cd api && go mod download)
(cd ui && npm ci)
```

`tools/dev.py envs` creates isolated `ingestion/.venv`, `ml/.venv` and `db/.venv` environments.
Datagen stays independently isolated because it owns a different source contract.

### 3. Build or review the generator configuration

The Config Builder is the only supported scenario-authoring surface. YAML is its default export;
JSON import/export remains supported. Open `datagen/config-builder.html` directly, or serve it
locally:

Windows PowerShell:

```powershell
py -3 -m http.server 8000 --directory datagen
```

macOS/Linux:

```bash
python3 -m http.server 8000 --directory datagen
```

Open `http://127.0.0.1:8000/config-builder.html`, choose **10-year demo preset**, review every
market/store/warehouse, assortment, demand, calendar, pandemic, lifecycle and execution control,
then download YAML. The checked-in demo YAML is protected by a builder-parity test and is the
configuration used below.

Validate and plan before generating:

Windows PowerShell:

```powershell
.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli validate-config -c datagen\configs\multi-market-10-year-demo.yaml
.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli plan -c datagen\configs\multi-market-10-year-demo.yaml
```

macOS/Linux:

```bash
datagen/.venv/bin/python -m retail_datagen.cli validate-config \
  -c datagen/configs/multi-market-10-year-demo.yaml
datagen/.venv/bin/python -m retail_datagen.cli plan \
  -c datagen/configs/multi-market-10-year-demo.yaml
```

### 4. Generate the ten-year source run

Use `safe` on the 16-GiB-available demo machine:

Windows PowerShell:

```powershell
.\datagen\.venv\Scripts\python.exe -m retail_datagen.cli generate `
  -c datagen\configs\multi-market-10-year-demo.yaml `
  -o datagen\output `
  --execution-profile safe
py -3 tools\dev.py run-status
```

macOS/Linux:

```bash
datagen/.venv/bin/python -m retail_datagen.cli generate \
  -c datagen/configs/multi-market-10-year-demo.yaml \
  -o datagen/output \
  --execution-profile safe
python3 tools/dev.py run-status
```

The seed, resolved scenario and generator version make this preset deterministic: rerunning the
same contract verifies and reuses `run-c5eb1506ecd4c550`; it does not silently create different
business data. Change the seed or scenario only when a new synthetic history is intended.
`source-run.duckdb` is a restricted browsing mirror, not the ingestion permission boundary and
not the authoritative source format. Ordinary ingestion reads only manifest-declared public
Parquet/CSV objects.

### 5. Land the immutable source snapshot

Windows PowerShell:

```powershell
py -3 tools\dev.py land `
  --source-root datagen\output\multi-market-10-year-demo\run-c5eb1506ecd4c550 `
  --landing-root ingestion\data\raw `
  --execution-profile safe
```

macOS/Linux:

```bash
python3 tools/dev.py land \
  --source-root datagen/output/multi-market-10-year-demo/run-c5eb1506ecd4c550 \
  --landing-root ingestion/data/raw \
  --execution-profile safe
```

Landing verifies every declared byte count and SHA-256, separates public and restricted lanes,
and promotes immutable snapshot
`681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b`.
Repeating the command is an idempotent verification, not a second copy.

### 6. Run the governed ingestion pipeline

The normal command runs Gate A, adapters/staging, source-neutral transforms, Gate B and atomic
publication in order:

Windows PowerShell:

```powershell
py -3 tools\dev.py run `
  --snapshot-root ingestion\data\raw\snapshots\681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b `
  --work-root ingestion\data\work\run-c5eb1506ecd4c550 `
  --publication-root ingestion\data\curated\run-c5eb1506ecd4c550 `
  --execution-profile safe
```

macOS/Linux:

```bash
python3 tools/dev.py run \
  --snapshot-root ingestion/data/raw/snapshots/681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b \
  --work-root ingestion/data/work/run-c5eb1506ecd4c550 \
  --publication-root ingestion/data/curated/run-c5eb1506ecd4c550 \
  --execution-profile safe
```

For inspection or debugging, the exact same pipeline can be run one stage at a time.

Windows PowerShell:

```powershell
py -3 tools\dev.py gate-a `
  --snapshot-root ingestion\data\raw\snapshots\681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b `
  --report-path ingestion\data\work\run-c5eb1506ecd4c550\gate-a.json `
  --execution-profile safe

py -3 tools\dev.py stage `
  --snapshot-root ingestion\data\raw\snapshots\681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b `
  --output-database ingestion\data\work\run-c5eb1506ecd4c550\staging.duckdb `
  --execution-profile safe

py -3 tools\dev.py transform `
  --staging-database ingestion\data\work\run-c5eb1506ecd4c550\staging.duckdb `
  --candidate-database ingestion\data\work\run-c5eb1506ecd4c550\retail_v2-candidate.duckdb `
  --execution-profile safe

py -3 tools\dev.py gate-b `
  --staging-database ingestion\data\work\run-c5eb1506ecd4c550\staging.duckdb `
  --candidate-database ingestion\data\work\run-c5eb1506ecd4c550\retail_v2-candidate.duckdb `
  --gate-a-report ingestion\data\work\run-c5eb1506ecd4c550\gate-a.json `
  --report-path ingestion\data\work\run-c5eb1506ecd4c550\gate-b.json `
  --execution-profile safe

py -3 tools\dev.py publish `
  --candidate-database ingestion\data\work\run-c5eb1506ecd4c550\retail_v2-candidate.duckdb `
  --gate-b-report ingestion\data\work\run-c5eb1506ecd4c550\gate-b.json `
  --publication-root ingestion\data\curated\run-c5eb1506ecd4c550 `
  --execution-profile safe
```

macOS/Linux:

```bash
python3 tools/dev.py gate-a \
  --snapshot-root ingestion/data/raw/snapshots/681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b \
  --report-path ingestion/data/work/run-c5eb1506ecd4c550/gate-a.json \
  --execution-profile safe

python3 tools/dev.py stage \
  --snapshot-root ingestion/data/raw/snapshots/681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b \
  --output-database ingestion/data/work/run-c5eb1506ecd4c550/staging.duckdb \
  --execution-profile safe

python3 tools/dev.py transform \
  --staging-database ingestion/data/work/run-c5eb1506ecd4c550/staging.duckdb \
  --candidate-database ingestion/data/work/run-c5eb1506ecd4c550/retail_v2-candidate.duckdb \
  --execution-profile safe

python3 tools/dev.py gate-b \
  --staging-database ingestion/data/work/run-c5eb1506ecd4c550/staging.duckdb \
  --candidate-database ingestion/data/work/run-c5eb1506ecd4c550/retail_v2-candidate.duckdb \
  --gate-a-report ingestion/data/work/run-c5eb1506ecd4c550/gate-a.json \
  --report-path ingestion/data/work/run-c5eb1506ecd4c550/gate-b.json \
  --execution-profile safe

python3 tools/dev.py publish \
  --candidate-database ingestion/data/work/run-c5eb1506ecd4c550/retail_v2-candidate.duckdb \
  --gate-b-report ingestion/data/work/run-c5eb1506ecd4c550/gate-b.json \
  --publication-root ingestion/data/curated/run-c5eb1506ecd4c550 \
  --execution-profile safe
```

Source profiles declare capabilities (`commerce`, `operations`, `external_signals`), not required
vendor names. Shopify and Business Central are the current bounded adapters. SAP, Oracle, another
ERP/WMS or governed flat files can replace Business Central once their profile and adapter emit
the same staging contract. A source set missing a capability required by the selected publication
tier terminates honestly as `validated_partial`; it is not mislabeled as a complete ML input.

### 7. Retain evidence and release rebuildable work

After Gate A, Gate B and publication are accepted, copy the small evidence bundle and delete only
rebuildable staging/candidate work:

Windows PowerShell:

```powershell
py -3 tools\dev.py finalize `
  --work-root ingestion\data\work\run-c5eb1506ecd4c550 `
  --publication-root ingestion\data\curated\run-c5eb1506ecd4c550 `
  --evidence-root ingestion\data\evidence\run-c5eb1506ecd4c550 `
  --prune-work
```

macOS/Linux:

```bash
python3 tools/dev.py finalize \
  --work-root ingestion/data/work/run-c5eb1506ecd4c550 \
  --publication-root ingestion/data/curated/run-c5eb1506ecd4c550 \
  --evidence-root ingestion/data/evidence/run-c5eb1506ecd4c550 \
  --prune-work
```

Keep immutable raw landing, curated Parquet/DuckDB, evidence and benchmark summaries according to
the environment's retention policy. `finalize` never deletes source data, raw snapshots or curated
data.

### 8. Start PostgreSQL and MLflow; activate only a new verifier-v3 forecast

Docker Desktop must be running. From the repository root:

```text
python3 tools/dev.py services up
python3 tools/dev.py db-upgrade
python3 tools/dev.py forecast-materialize \
  --forecast-run <accepted-forecast-run-v2-directory>
python3 tools/dev.py forecast-activate \
  --forecast-run-id <forecastRunId-from-materialize-output> \
  --activation-scope-fingerprint <activationScopeFingerprint-from-materialize-output> \
  --actor <your-name>
python3 tools/dev.py services status
```

The commands are cross-platform Python commands; replace `python3` with `py -3` on Windows when
that is the installed launcher. Materialization independently verifies A1–A5, every immutable
artifact and current curated lineage before one PostgreSQL transaction; activation is a separate
append-only event. Both commands are safe to repeat for the same identity. Review #2 leaves no
currently accepted verifier-v3 run, so the placeholders must not be replaced with the rejected
v12 or `fr_92135aa7b5215b69` identities. Until a new run passes, forecast API routes intentionally
return unavailable. The local endpoints are PostgreSQL at `127.0.0.1:5432` and MLflow at
`http://127.0.0.1:5000`.

### 9. Start the API

From `api/`:

Windows PowerShell:

```powershell
$env:RETAIL_POSTGRES_DSN = "postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence"
$env:RETAIL_FORECAST_ACTIVATION_SCOPE = (docker compose -f deploy/compose.yaml exec -T postgres psql -U retail -d retail_intelligence -Atc "SELECT activation_scope_fingerprint FROM retail_serving.active_forecast_versions ORDER BY recorded_at DESC LIMIT 1").Trim()
if (-not $env:RETAIL_FORECAST_ACTIVATION_SCOPE) { throw "Materialize and activate a verifier-v3 forecast before starting the API." }
go run ./cmd/server `
  -address 127.0.0.1:8080 `
  -gate-a-report ..\ingestion\data\evidence\run-c5eb1506ecd4c550\gate-a.json `
  -gate-b-report ..\ingestion\data\evidence\run-c5eb1506ecd4c550\gate-b.json `
  -publication-manifest ..\ingestion\data\curated\run-c5eb1506ecd4c550\publication-manifest.json `
  -execution-profiles ..\execution\src\retail_execution\data\v1\profiles.json `
  -execution-profile safe `
  -openapi-spec ..\contracts\api\openapi.yaml
```

macOS/Linux:

```bash
export RETAIL_POSTGRES_DSN='postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence'
export RETAIL_FORECAST_ACTIVATION_SCOPE="$(docker compose -f deploy/compose.yaml exec -T postgres psql -U retail -d retail_intelligence -Atc 'SELECT activation_scope_fingerprint FROM retail_serving.active_forecast_versions ORDER BY recorded_at DESC LIMIT 1')"
test -n "$RETAIL_FORECAST_ACTIVATION_SCOPE" || { echo "Materialize and activate a verifier-v3 forecast before starting the API." >&2; exit 1; }
go run ./cmd/server \
  -address 127.0.0.1:8080 \
  -gate-a-report ../ingestion/data/evidence/run-c5eb1506ecd4c550/gate-a.json \
  -gate-b-report ../ingestion/data/evidence/run-c5eb1506ecd4c550/gate-b.json \
  -publication-manifest ../ingestion/data/curated/run-c5eb1506ecd4c550/publication-manifest.json \
  -execution-profiles ../execution/src/retail_execution/data/v1/profiles.json \
  -execution-profile safe \
  -openapi-spec ../contracts/api/openapi.yaml
```

Available URLs:

- API health: `http://127.0.0.1:8080/healthz`
- Live Data Management payload: `http://127.0.0.1:8080/api/v1/data-management/dashboard`
- Live accepted FX rates: `http://127.0.0.1:8080/api/v1/fx/rates`
- Forecast summary (503 until a verifier-v3 run is accepted and active):
  `http://127.0.0.1:8080/api/v1/forecast/summary`
- Swagger UI: `http://127.0.0.1:8080/docs`
- ReDoc: `http://127.0.0.1:8080/redoc`
- OpenAPI YAML: `http://127.0.0.1:8080/openapi.yaml`

The server fails closed when Gate A, Gate B and the publication manifest do not identify the same
accepted snapshot, or when PostgreSQL has no active forecast matching both the publication and
requested activation scope. Each forecast read revalidates that the activation is still current
and was materialized under `retail-forecast-verifier/v3`; a legacy or superseded process therefore
fails closed without relying on a restart.

### 10. Start the UI

In another terminal, from `ui/`:

```text
npm run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` and `/healthz` to the Go service at
`http://127.0.0.1:8080`; start the API first. Data Management follows the strict v6 HTML shell
and screen-data contract, with live accepted-publication values. The three source-management
buttons and user/User Management UI are the approved current omissions. Forecast Coverage remains
`Not available` pending its frozen business formula. Accepted Model Accuracy is now available from
the forecast API, but it must not be added to React until the relevant parity/data matrix is
approved. Inventory/Replenishment and Pricing/Promotion arrive with their owning capability phases,
using the same approved shell.

The live filter model uses canonical markets `india-west` and `us-new-york`, with Mumbai Bandra,
Pune Koregaon Park, Brooklyn and Manhattan stores. The global Channel filter exposes two
business types (`E-commerce` and `Store`); market-qualified source/canonical channel instances
remain internal. Store and Channel selections intersect, so Pune Koregaon Park + E-commerce is a
valid filter context. Footer `Channels` therefore reports 2, not the four internal instances.

### 11. Inspect the curated data

The accepted publication contains 40 canonical entities and 7,471,784 daily
SKU×store×channel sales rows. To list tables without requiring a separate DuckDB CLI:

Windows PowerShell:

```powershell
.\ingestion\.venv\Scripts\python.exe -c "import duckdb; c=duckdb.connect('ingestion/data/curated/run-c5eb1506ecd4c550/retail_v2.duckdb', read_only=True); print(c.execute('select table_name from information_schema.tables order by table_name').fetchall())"
```

macOS/Linux:

```bash
ingestion/.venv/bin/python -c "import duckdb; c=duckdb.connect('ingestion/data/curated/run-c5eb1506ecd4c550/retail_v2.duckdb', read_only=True); print(c.execute('select table_name from information_schema.tables order by table_name').fetchall())"
```

The retained publication currently enables data management, revenue reporting, accepted non-PIT
demand forecasting and competitor analysis. Native assortment observation makes zero-demand
labels origin-safe, but the broader point-in-time capability remains downgraded because several
reference facts and signals are still landing-backfilled. Pricing and replenishment remain closed
until their Phase-2 evidence requirements and later model phases are satisfied.

### 12. Verify the repository

Windows PowerShell:

```powershell
py -3 tools\dev.py contracts
py -3 tools\dev.py test
py -3 tools\dev.py verify
py -3 tools\dev.py wheels --offline
```

macOS/Linux:

```bash
python3 tools/dev.py contracts
python3 tools/dev.py test
python3 tools/dev.py verify
python3 tools/dev.py wheels --offline
```

See `datagen/README.md`, `ingestion/README.md`, `api/README.md` and `ui/README.md` for
component-specific contracts, troubleshooting and deeper implementation details.

## Cross-platform development

Windows, macOS and Linux are equal, required local runtime targets for the Config Builder,
contract/code-generation tooling, `execution/`, `datagen/`, `ingestion/`, `ml/`, the Go API,
database migrations and the Node/React UI. Windows support is a release gate, not a best-effort
follow-up. The shared authoritative entry point is Python: it resolves virtual-environment
executables as `Scripts/python.exe` on Windows and `bin/python` elsewhere, uses `pathlib`,
`tempfile` and subprocess argument lists, and never constructs shell command strings. Go code
must use `filepath` and portable lock/process/shutdown APIs; UI workflows must be cross-platform
npm scripts without Bash syntax.

```text
# Windows PowerShell
py -3 tools/dev.py envs
py -3 tools/dev.py contracts
py -3 tools/dev.py test
py -3 tools/dev.py wheels

# macOS / Linux
python3 tools/dev.py envs
python3 tools/dev.py contracts
python3 tools/dev.py test
python3 tools/dev.py wheels
```

The root `Makefile` and `tools/check_isolated_wheels.sh` are optional POSIX wrappers only.
Phase-2 code and the authoritative developer commands are designed for Windows, macOS and Linux
and are exercised locally with component and isolated-wheel tests. The eventual hardening matrix
must run these checks on all three OS families before production acceptance; no active GitHub
workflow is claimed today. Runtime permission lanes mean Windows ACLs/locking or POSIX
permissions/locking as appropriate; ingestion never relies on a POSIX mode bit as its security
boundary.

Portable storage has two path forms: manifests and fingerprints use normalized `/`-separated
logical paths, while filesystem access uses native `Path`/`filepath` objects. Code must not assume
`/tmp`, `fork`, `flock`, symlinks, executable mode bits, case-sensitive filenames or that an open
file can be replaced on Windows. Writers close every file/DuckDB handle before atomic promotion,
use same-volume staging, and normalize contract text to UTF-8/LF where bytes are fingerprinted.
No phase is production-hardened until its supported commands and tests pass on
Windows, Linux and macOS hosts. Collect and review that evidence manually through
`tools/dev.py` and component commands; repository CI remains prohibited during release
hardening.

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
   **`plans/aws/`** is the cloud deployment plan (after local works).

## Reference implementations

The spec's `[REUSE]` tags point at `../retail_ai` modules to copy or re-implement. Datagen adapts
portable primitives and the rich product/variant approach from
`../retail-synthetic-data-generator`; its exact reuse decisions are recorded in
`datagen/REUSE_AUDIT.md`. Phase 2 has already adapted the relevant data-quality/mapping patterns
into `ingestion/` and reimplemented the first read-only API slice in Go. The remaining reuse is
primarily `retail_ai/{features,models,engines}` → `ml/` and `retail_ai/migrations` (Alembic) →
`db/`, with later API endpoints reimplemented behind the existing Aarv transport boundary.
