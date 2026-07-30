# Retail Intelligence — AWS Deployment Plan

_Cygnet.One · Cloud deployment of the Retail Intelligence PoC · Companion: `plans/aws/tasks.md`
· Local plan (prerequisite): `plans/local/plan.md` · Spec: `docs/demand_forecast_poc_spec.md`_

## 1 · Goal — what "done on AWS" means

Deploy the **same** codebase that works locally onto AWS, running end-to-end on generated
synthetic data, in a **controlled, private, least-privilege** account, with the identical
shadow-only + fail-closed + point-in-time guarantees. AWS is a **deployment target after the
local build works** (not a prerequisite). Python datagen, ingestion and ML workloads run as
managed jobs; the Go API runs as a container service; artifacts + lineage live in S3;
workflow/audit in RDS.

AWS containers may use Linux images, but that deployment choice does not narrow the local support
contract: shared application code and developer/build commands remain required on Windows,
macOS and Linux. Container success cannot replace manually collected three-OS acceptance
evidence.

**Governance hard rule:** real client data (if ever used) runs only in an approved
**client-controlled account** with residency, encryption, retention, and access controls — never
mixed with the PoC's synthetic account. This PoC account uses generated data only.

## 2 · Local → AWS seam mapping

The design is built around config-switched seams so local and AWS run the same logic:

| Seam | Local | AWS |
|---|---|---|
| Execution profiles | versioned `execution/` safe/balanced/performance/ultra-performance YAML + layer adapters | same schema/golden vectors mapped to explicit Batch/SageMaker/ECS CPU and memory |
| Object storage (lake, artifacts) | raw source CSV + restricted single-run DuckDB; curated Parquet/DuckDB | **S3** (raw / restricted-evaluation / curated / features / artifacts prefixes) |
| Data generator | `datagen/` Config Builder artifact + CLI | `datagen` job (**AWS Batch** or **SageMaker Processing**) → S3 raw |
| Ingestion compute | `ingestion/` Python | **SageMaker Processing** (or ECS/Batch) |
| ML compute | `ml/` Python features/models/engines | **SageMaker Processing / Training jobs** (or ECS/Batch) |
| Pipeline orchestration | scripts / nightly | **Step Functions + EventBridge** (or SageMaker Pipelines) |
| Model tracking / registry | local MLflow | **MLflow on ECS** + **SageMaker Model Registry** |
| Relational DB (workflow, audit, recs) | Postgres (Docker) | **RDS PostgreSQL** (Multi-AZ) |
| API runtime | Aarv-based Go binary | **ECS Fargate** behind **ALB** / **API Gateway** |
| UI hosting | dev server | **S3 + CloudFront** (or Amplify) |
| Auth / RBAC | local dev users | **Cognito** |
| Secrets / keys | `.env` | **Secrets Manager** + **KMS** |
| Observability | logs | **CloudWatch** (+ X-Ray) |
| IaC / deployment | — | **Terraform/CDK**, invoked manually; repository CI/CD is prohibited |

## 3 · Phases (AWS)

Status: `[ ]` not started · `[~]` partial · `[x]` done. Detail in `plans/aws/tasks.md`.

### Phase A0 — Foundations
Account/org guardrails, VPC (private subnets, VPC endpoints, no public data paths), IAM
least-privilege roles, **KMS** CMKs, **S3** buckets (raw/curated/features/artifacts, versioned +
encrypted), **RDS PostgreSQL**, **Secrets Manager**, IaC skeleton (Terraform/CDK), and manual
build/test/deploy runbooks. **Exit:** `terraform apply` stands up an empty, private, encrypted
environment.
Each Python image installs the neutral `execution/` resolver; the Go image implements the same
schema/golden vectors natively. IaC maps a selected bounded profile to explicit service/job
resources rather than inferring unbounded concurrency from the instance.

### Phase A1 — Data landing & ingest
Upload a Config-Builder-generated scenario, run `datagen` to publish Shopify-shaped, Business
Central-shaped and companion CSV/Parquet sources to immutable S3 **raw**, and retain its source-run
manifest, hidden truth and all-source `source-run.duckdb` in a restricted evaluation prefix
outside curated paths. Package `ingestion/` as Python SageMaker Processing jobs:
landing manifest → Gate A → profile/adapter → staging → source-neutral transforms → Gate B →
curated. Missing source manifests/timestamps/versions are derived from immutable landing evidence
under the canonical entity's explicit-version or observation-identity policy, or quarantined.
**Exit:** core Shopify+BC+companion data receives the
required full Gate-B capability pass; partial Shopify stops before curated promotion.
Canonical locations/stores retain market, operating currency and timezone; in-cloud golden tests
use the same ingestion-owned source-truth→canonical control oracle as local. Contextual signals
retain market-qualified `geo_scope_*`, multi-axis promotion scope stays structured, Shopify
presentment money remains audit-only, `merch_scope_*` resolution is deterministic and FX uses the
shared exact local/base→reporting/quote arithmetic.

### Phase A2 — ML pipeline (features, forecast, elasticity)
Market-local calendar/normalized-price feature build + LightGBM forecast + market-scoped
Poisson-EB elasticity as SageMaker jobs; orchestrate with
**Step Functions / SageMaker Pipelines**; write fingerprinted artifacts to S3; log to MLflow +
**SageMaker Model Registry**; enforce global and supported-market forecast acceptance gates
in-pipeline. **Exit:** a one-click pipeline run produces accepted, market/config-fingerprinted
forecast artifacts in S3.
The cloud regression runs both pricing presets: the response-rich IN+US showcase must meet
per-market gated-series coverage, while the sparse preset must publish
`insufficient_evidence`.

### Phase A3 — Engines & batch decisioning
Reorder/safety-stock, pricing, allocation, transfer, ageing engines as jobs; policy calibration
(5%) + validation (95%); resolve pricing policies by market/currency and keep ABC/valuation
market-local unless approved reporting FX is applied; write recommendations/drafts to **RDS** +
artifacts to S3. Revenue pricing may publish without cost; margin remains unavailable until the
cost capability passes. Reporting conversion uses the same exponent-aware per-fact rounding as
local. **Exit:** replenishment + pricing artifacts are market-scoped and
published in-cloud under guardrails.

### Phase A4 — Aarv-based Go API & workflow
[Aarv](https://github.com/nilshah80/aarv)-based Go API on **ECS Fargate** behind **ALB/API
Gateway**; pin exact Aarv module versions in the image build and keep `contracts/` OpenAPI
authoritative. Use **RDS** for workflow/audit and **Cognito** for RBAC; serve S3 artifacts;
preserve local market/currency on recommendations; serve-time guardrail re-validation against
the same resolved market policy; staleness 409/503; fingerprint parity with the Python side;
reason-coded evidence blocks remain visible rather than becoming empty pricing results.
**Exit:** the API serves live artifacts; approve/override audited; auth enforced.

### Phase A5 — UI deployment
Deploy the front-end already delivered incrementally by the local vertical slices to **S3 +
CloudFront** (or Amplify), pointed at the API Gateway/ALB endpoint; this is not the start of UI
implementation. Configure FX display against the cloud API. **Exit:** all screens render live
cloud data.

### Phase A6 — Orchestration & unattended run
**EventBridge** schedule → **Step Functions** nightly (generate → ingest/transform → ML →
engines → publish); alerting to CloudWatch/SNS; idempotent re-runs. **Exit:** an unattended scheduled run
completes and republishes idempotently.

### Phase A7 — Security, residency, observability, cost, DR
KMS-encrypt everything at rest + TLS in transit; VPC endpoints (no public egress for data);
least-privilege IAM; CloudWatch dashboards/alarms + X-Ray; cost budgets/tags; backup/retention;
DR runbook; **client-data residency boundary** documented (separate account for any real data).
**Exit:** security review + cost review pass; residency boundary documented.

## 4 · Guiding principles (unchanged from local)

Human-decides / shadow-only; engines compute the numbers; point-in-time; fail-closed; one shared
`contracts/`; fingerprint parity Python↔Go. On AWS these are enforced additionally by IAM
(no principal can push a price/PO externally), private networking, and KMS.

## 5 · Out of scope / deferred (AWS PoC)

- Real client data (separate controlled account + engagement).
- Multi-region HA, production SLAs, and autoscaling beyond PoC needs.
- Marketplace/SaaS packaging.
