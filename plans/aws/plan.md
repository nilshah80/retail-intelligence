# Retail Intelligence — AWS Deployment Plan

_Cygnet.One · Cloud deployment of the Retail Intelligence PoC · Companion: `plans/aws/tasks.md`
· Local plan (prerequisite): `plans/local/plan.md` · Spec: `docs/demand_forecast_poc_spec.md`_

## 1 · Goal — what "done on AWS" means

Deploy the **same** codebase that works locally onto AWS, running end-to-end on generated
synthetic data, in a **controlled, private, least-privilege** account, with the identical
shadow-only + fail-closed + point-in-time guarantees. AWS is a **deployment target after the
local build works** (not a prerequisite). The Python ML pipeline runs as managed jobs; the Go
API runs as a container service; artifacts + lineage live in S3; workflow/audit in RDS.

**Governance hard rule:** real client data (if ever used) runs only in an approved
**client-controlled account** with residency, encryption, retention, and access controls — never
mixed with the PoC's synthetic account. This PoC account uses generated data only.

## 2 · Local → AWS seam mapping

The design is built around config-switched seams so local and AWS run the same logic:

| Seam | Local | AWS |
|---|---|---|
| Object storage (lake, artifacts) | Parquet/DuckDB on disk | **S3** (raw / curated / features / artifacts prefixes) |
| Data generator | `datagen/` CLI | `datagen` job (**AWS Batch** or **SageMaker Processing**) → S3 raw |
| ML compute (ingest, features, models, engines) | local Python | **SageMaker Processing / Training jobs** (or ECS/Batch) |
| Pipeline orchestration | scripts / nightly | **Step Functions + EventBridge** (or SageMaker Pipelines) |
| Model tracking / registry | local MLflow | **MLflow on ECS** + **SageMaker Model Registry** |
| Relational DB (workflow, audit, recs) | Postgres (Docker) | **RDS PostgreSQL** (Multi-AZ) |
| API runtime | Go binary | **ECS Fargate** behind **ALB** / **API Gateway** |
| UI hosting | dev server | **S3 + CloudFront** (or Amplify) |
| Auth / RBAC | local dev users | **Cognito** |
| Secrets / keys | `.env` | **Secrets Manager** + **KMS** |
| Observability | logs | **CloudWatch** (+ X-Ray) |
| IaC / CI-CD | — | **Terraform/CDK** + **CodePipeline** / GitHub Actions |

## 3 · Phases (AWS)

Status: `[ ]` not started · `[~]` partial · `[x]` done. Detail in `plans/aws/tasks.md`.

### Phase A0 — Foundations
Account/org guardrails, VPC (private subnets, VPC endpoints, no public data paths), IAM
least-privilege roles, **KMS** CMKs, **S3** buckets (raw/curated/features/artifacts, versioned +
encrypted), **RDS PostgreSQL**, **Secrets Manager**, IaC skeleton (Terraform/CDK), CI/CD
pipeline. **Exit:** `terraform apply` stands up an empty, private, encrypted environment.

### Phase A1 — Data landing & ingest
Run the `datagen` client-shaped publisher (Batch/SageMaker Processing) → immutable S3 **raw**.
Python SageMaker Processing jobs run Gate A; the profile-driven normalizer/adapter emits
standardized staging; shared transforms produce canonical data; Gate B promotes only passing
results to S3 **curated** and registers manifests, lineage and reconciliation. **Exit:** Gate A
passes every snapshot; pure Shopify reconstructs its declared slice with `validated_partial`
only; generic and Shopify-plus-companion reconstruct the full truth and pass full Gate B before
curated promotion in-cloud.

### Phase A2 — ML pipeline (features, forecast, elasticity)
Feature build + LightGBM forecast + Poisson-EB elasticity as SageMaker jobs; orchestrate with
**Step Functions / SageMaker Pipelines**; write fingerprinted artifacts to S3; log to MLflow +
**SageMaker Model Registry**; enforce the forecast acceptance gates in-pipeline. **Exit:** a
one-click pipeline run produces accepted, fingerprinted forecast artifacts in S3.

### Phase A3 — Engines & batch decisioning
Reorder/safety-stock, pricing, allocation, transfer, ageing engines as jobs; policy calibration
(5%) + validation (95%); write recommendations/drafts to **RDS** + artifacts to S3. **Exit:**
replenishment + pricing artifacts published in-cloud under guardrails.

### Phase A4 — Go API & workflow
Go API on **ECS Fargate** behind **ALB/API Gateway**; **RDS** for workflow/audit; **Cognito**
for RBAC; serve S3 artifacts; serve-time guardrail re-validation; staleness 409/503; fingerprint
parity with the Python side. **Exit:** the API serves live artifacts; approve/override audited;
auth enforced.

### Phase A5 — UI
Host the front-end on **S3 + CloudFront** (or Amplify), pointed at the API Gateway/ALB endpoint;
FX display. **Exit:** all screens render live cloud data.

### Phase A6 — Orchestration & unattended run
**EventBridge** schedule → **Step Functions** nightly (regenerate/ingest → pipeline → engines →
publish); alerting to CloudWatch/SNS; idempotent re-runs. **Exit:** an unattended scheduled run
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
