# Retail Intelligence — AWS Tasks

_Companion to `plans/aws/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_AWS is a deployment target **after** the local build (`plans/local/`) works. Synthetic data only._

## Phase A0 — Foundations
- [ ] Account/org guardrails; region choice; tagging + cost budgets.
- [ ] IaC skeleton (Terraform or CDK) in `deploy/` with remote state.
- [ ] VPC: private subnets, VPC endpoints (S3, ECR, SageMaker, Secrets), no public data paths.
- [ ] IAM least-privilege roles (pipeline, api, datagen); no external price/PO egress.
- [ ] KMS CMKs; S3 buckets (raw/curated/features/artifacts) versioned + encrypted.
- [ ] RDS PostgreSQL (Multi-AZ, encrypted, private).
- [ ] Secrets Manager entries; CloudWatch log groups.
- [ ] CI/CD pipeline (build/test/deploy for `ml/`, `api/`, `datagen/`).
- [ ] **Exit:** `apply` stands up an empty, private, encrypted environment.

## Phase A1 — Data landing & ingest
- [ ] Package `datagen/` as a job (AWS Batch or SageMaker Processing).
- [ ] Run generator → S3 **raw** prefix (with run manifest + `known_as_of`).
- [ ] Package `ml/` ingest + quality as a SageMaker Processing job.
- [ ] Ingest (mapped_files) → curated S3; fail-closed quality gate in-cloud.
- [ ] **Exit:** dataset in S3 passes quality gate; run registered.

## Phase A2 — ML pipeline (features, forecast, elasticity)
- [ ] Feature build job → S3 features prefix (point-in-time).
- [ ] LightGBM forecast job (P50/P90, horizons → 26 wk, Croston routing).
- [ ] Poisson-EB elasticity job + gates.
- [ ] Orchestrate with Step Functions / SageMaker Pipelines.
- [ ] Artifacts + manifests + fingerprints to S3; log MLflow + SageMaker Model Registry.
- [ ] Forecast acceptance gates enforced in-pipeline.
- [ ] **Exit:** one-click run yields accepted, fingerprinted forecast artifacts.

## Phase A3 — Engines & batch decisioning
- [ ] Reorder/safety-stock, pricing, allocation, transfer, ageing engine jobs.
- [ ] Policy calibration (5%) + validation (95%).
- [ ] Write recommendations/drafts → RDS; artifacts → S3.
- [ ] **Exit:** replenishment + pricing artifacts published under guardrails.

## Phase A4 — Go API & workflow
- [ ] Containerize Go `api/`; push to ECR.
- [ ] ECS Fargate service behind ALB / API Gateway.
- [ ] RDS wiring (workflow, audit, recs); Alembic migrations applied.
- [ ] Cognito auth + RBAC; map roles/approval tiers.
- [ ] Serve S3 artifacts; serve-time guardrail re-validation; staleness 409/503.
- [ ] Fingerprint parity with Python (shared golden vectors) in-cloud.
- [ ] **Exit:** API serves live artifacts; approve/override audited; auth enforced.

## Phase A5 — UI
- [ ] Build UI; host on S3 + CloudFront (or Amplify).
- [ ] Point at API Gateway/ALB; configure CORS/auth; FX display.
- [ ] **Exit:** all screens render live cloud data.

## Phase A6 — Orchestration & unattended run
- [ ] EventBridge schedule → Step Functions nightly (regen/ingest → pipeline → engines → publish).
- [ ] Idempotent republication; alerting to CloudWatch/SNS.
- [ ] **Exit:** unattended scheduled run completes + republishes idempotently.

## Phase A7 — Security, residency, observability, cost, DR
- [ ] KMS at rest + TLS in transit everywhere; VPC endpoints (no public data egress).
- [ ] IAM least-privilege review; secrets rotation.
- [ ] CloudWatch dashboards/alarms + X-Ray traces.
- [ ] Cost budgets/tags; backup + retention; DR runbook.
- [ ] Document client-data residency boundary (separate account for any real data).
- [ ] **Exit:** security + cost reviews pass; residency boundary documented.
