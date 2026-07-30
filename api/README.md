# `api/` — Aarv-based Go API & serving layer

For the complete source generation → ingestion → API → UI sequence on Windows, macOS and Linux,
start with the root `README.md`. This file documents API-specific behavior and commands.

**Purpose:** serve the Python-produced artifacts to the UI and own the decision/governance layer:
workflow / HITL (approvals, planner overrides, idempotency, audit), **serve-time guardrail
re-validation**, staleness handling (409/503), RBAC / auth.

**Delivery:** introduce a thin, versioned read-only API alongside each demoable capability rather
than waiting for the governance phase: ingestion/quality in Phase 2, demand in Phase 3, inventory
and replenishment in Phase 4, and pricing/promotion in Phase 5. Deterministic UI stubs use the same
OpenAPI/read-model contracts. Phase 6 consolidates and hardens these reads and adds governed
write/workflow endpoints.

**Language and web framework:** Go with
[Aarv](https://github.com/nilshah80/aarv), imported from
`github.com/nilshah80/aarv`. The API scaffold must pin an exact Aarv version in `api/go.mod`;
it must not build against an unpinned `@latest`.

Aarv owns only the HTTP transport boundary: routing, request binding, middleware composition,
lifecycle and graceful shutdown. Handlers remain thin and delegate to `internal/` packages for
read models, workflow, fingerprints, execution profiles, guardrails and persistence. The
versioned OpenAPI documents in `contracts/` remain authoritative; framework-generated
documentation or an Aarv OpenAPI/UI plugin may expose that contract but must not become a second
semantic source of truth. Optional Aarv plugins are added à la carte and pinned independently
where they are separate Go modules.

**Origin (`[REUSE-as-redesign]`):** the M5 PoC's `api/app.py` (FastAPI), `workflow_service.py`,
and `workflow_repository.py` establish the design and rules; the **code is re-implemented in Go**.

**Boundary:** reads PostgreSQL projections produced only from fully verified Python artifacts, plus
the shared guardrail YAMLs in `contracts/`. Parquet/JSON remains the immutable authority, but the
API process and its HTTP handlers never scan forecast Parquet. The offline materializer binds every
database row set to the accepted run, version, publication and policy fingerprints before an
explicit activation can make it serveable.
Two hard requirements:
- **Fingerprint parity** — SHA-256 over canonical JSON must be byte-identical to Python's
  (see `contracts/`), or lineage checks 409 spuriously. The Go implementation lives in
  `internal/fingerprint` and consumes the same semantic and invalid golden vectors as Python.
- **Single-sourced thresholds** — read guardrail numbers from `contracts/` YAMLs; never hard-code.
- **Market-scoped money** — resolve the same `market_id + currency_code` guardrail payload as
  Python; attach market/currency to price activations and recommendations, reject mismatches, and
  never price in presentment currency or sum local-currency amounts without the governed exact
  local/base→reporting/quote conversion and shared rounding vectors.
- **Evidence disclosure** — return a reason-coded `insufficient_evidence` capability/state for a
  market/department rather than an unexplained empty pricing result.

**Interactive scoring:** compute closed-form projections in Go from stored β / P50 / P90
(`units = p50·(price/price0)^β`, revenue/margin, safety stock); call a Python scoring service only
for model-backed scoring or the LLM copilot (OPEN — see `docs/OPEN_DECISIONS.md`).

**Execution boundary:** Go implements the shared `retail-execution-profile/v1` schema and golden
vectors natively; it does not import Python. Its adapter maps the `api` namespace into
`GOMAXPROCS`, HTTP/background concurrency and PostgreSQL/DuckDB pool limits. Resolved non-secret
values and saturation telemetry are operational metadata only and cannot alter response values,
authorization, idempotency, fingerprints or guardrail decisions.

**Portability:** the Aarv application and all middleware must use portable Go APIs and be tested
on Windows, macOS and Linux. Application paths use `filepath`; manifest identifiers remain
normalized logical `/` paths; shutdown, locking and process control must not depend on POSIX-only
signals or shell scripts. File-backed readers and DuckDB connections close before replacement,
and OS-specific signal adapters must preserve the same graceful-shutdown contract.

**Spec:** §4.7–4.8 (HITL, lineage), §8 (screens), Architecture note.

## Implemented read-only slices

`api/go.mod` pins `github.com/nilshah80/aarv` to `v0.9.6`. The initial server is deliberately
read-only: it loads accepted Gate A, Gate B and publication manifests, verifies that all three
refer to the same immutable source snapshot, and exposes:

- `GET /healthz`;
- `GET /api/v1/data-management/dashboard` — live original-screen KPI, source-table, footer and
  filter values;
- `GET /api/v1/fx/rates` — accepted as-of rates from each local/base currency into the retailer
  reporting currency, preserving exact decimal strings;
- `GET /api/v1/data-management/summary`;
- `GET /api/v1/data-management/gates`;
- `GET /api/v1/data-management/capabilities`;
- `GET /api/v1/data-management/reconciliation`;
- `GET /api/v1/data-management/quality-findings`;
- `GET /api/v1/forecast/{versions,summary,series,actuals,horizons,stores,drivers,signals,exceptions}`
  — live PostgreSQL-backed Phase 3 forecast read models for the lineage-matching active version.
  The routes return the same governed 503 envelope when the projection is absent, inactive or
  publication-mismatched;
- `GET /openapi.yaml` — the authoritative OpenAPI contract;
- `GET /docs` — interactive Swagger UI;
- `GET /redoc` — alternate ReDoc documentation.

The stable OpenAPI contract is `../contracts/api/openapi.yaml`; the Aarv OpenAPI UI plugin only
renders it and is not a second contract source. API execution profiles are read from the shared
`../execution/src/retail_execution/data/v1/profiles.json`; environment overrides are validated
before `GOMAXPROCS` and HTTP concurrency are applied.

```powershell
# Windows PowerShell
go test -race ./...
$env:RETAIL_POSTGRES_DSN = "postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence"
$env:RETAIL_FORECAST_ACTIVATION_SCOPE = (docker compose -f ..\deploy\compose.yaml exec -T postgres psql -U retail -d retail_intelligence -Atc "SELECT activation_scope_fingerprint FROM retail_serving.active_forecast_versions ORDER BY recorded_at DESC LIMIT 1").Trim()
if (-not $env:RETAIL_FORECAST_ACTIVATION_SCOPE) { throw "Materialize and activate a verifier-v3 forecast before starting the API." }
go run ./cmd/server -address :8080 -gate-a-report ..\ingestion\data\evidence\run-c5eb1506ecd4c550\gate-a.json -gate-b-report ..\ingestion\data\evidence\run-c5eb1506ecd4c550\gate-b.json -publication-manifest ..\ingestion\data\curated\run-c5eb1506ecd4c550\publication-manifest.json -execution-profiles ..\execution\src\retail_execution\data\v1\profiles.json -execution-profile safe -openapi-spec ..\contracts\api\openapi.yaml
```

```bash
# macOS / Linux
go test -race ./...
export RETAIL_POSTGRES_DSN='postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence'
export RETAIL_FORECAST_ACTIVATION_SCOPE="$(docker compose -f ../deploy/compose.yaml exec -T postgres psql -U retail -d retail_intelligence -Atc 'SELECT activation_scope_fingerprint FROM retail_serving.active_forecast_versions ORDER BY recorded_at DESC LIMIT 1')"
test -n "$RETAIL_FORECAST_ACTIVATION_SCOPE" || { echo "Materialize and activate a verifier-v3 forecast before starting the API." >&2; exit 1; }
go run ./cmd/server -address :8080 -gate-a-report ../ingestion/data/evidence/run-c5eb1506ecd4c550/gate-a.json -gate-b-report ../ingestion/data/evidence/run-c5eb1506ecd4c550/gate-b.json -publication-manifest ../ingestion/data/curated/run-c5eb1506ecd4c550/publication-manifest.json -execution-profiles ../execution/src/retail_execution/data/v1/profiles.json -execution-profile safe -openapi-spec ../contracts/api/openapi.yaml
```

Run these commands from `api/`. The server never substitutes sample values when accepted
artifacts are absent or inconsistent. After startup, open `http://127.0.0.1:8080/docs` for
Swagger, `http://127.0.0.1:8080/redoc` for ReDoc, and `http://127.0.0.1:5173` for the React UI.
Start and migrate the Docker Desktop services, materialize the accepted bundle and activate it as
documented in the root runbook before starting the server. Pass a PostgreSQL DSN only through the
configured secret/environment boundary. Missing,
unmaterialized, inactive, rejected or publication-mismatched versions remain unavailable and are
never exposed as live forecast data. The materialization command—not the API—opens the immutable
forecast-run directory and verifies all ten artifacts.
