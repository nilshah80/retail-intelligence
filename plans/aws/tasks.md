# Retail Intelligence — AWS Tasks

_Companion to `plans/aws/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_AWS is a deployment target **after** the local build (`plans/local/`) works. Synthetic data only._

## Phase A0 — Foundations
- [ ] Account/org guardrails; region choice; tagging + cost budgets.
- [ ] IaC skeleton (Terraform or CDK) in `deploy/` with remote state.
- [ ] VPC: private subnets, VPC endpoints (S3, ECR, SageMaker, Secrets), no public data paths.
- [ ] IAM least-privilege roles (datagen, ingestion, ML pipeline, API); no external price/PO
      egress.
- [ ] KMS CMKs; S3 buckets (raw/curated/features/artifacts) versioned + encrypted.
- [ ] RDS PostgreSQL (Multi-AZ, encrypted, private).
- [ ] Secrets Manager entries; CloudWatch log groups.
- [ ] CI/CD pipeline (build/test/deploy for `datagen/`, `ingestion/`, `ml/`, `api/`).
- [ ] Keep Terraform/CDK validation, image-build orchestration and deployment smoke-test commands
      callable from Windows PowerShell and macOS/Linux terminals without mandatory Bash. A Linux
      container runtime does not waive the three-OS application test gates locked by decision
      #47.
- [ ] Build Python job images from the dependency/environment topology locked locally under
      decision #38; never merge the isolated datagen environment into downstream images.
- [ ] Install the same versioned `execution/` package into each Python job image and run its
      golden vectors in CI. Map named profiles to explicit Batch/SageMaker CPU/memory requests;
      never auto-expand from instance size or put hardware controls in scenario/model configs.
- [ ] **Exit:** `apply` stands up an empty, private, encrypted environment.

## Phase A1 — Data landing & ingest
- [ ] Package `datagen/` as a job (AWS Batch or SageMaker Processing).
- [ ] Pass a separately stored execution-profile YAML to datagen/ingestion jobs; retain the
      resolved non-secret profile and stage telemetry in job/run manifests. Require the same
      source and Gate outcomes under safe/ultra-performance before changing the default instance class.
- [ ] Store the complete Config-Builder YAML/JSON artifact; publish Shopify-shaped, Business
      Central-shaped and companion snapshots plus source-run manifest to versioned S3 **raw**
      prefixes in their selected CSV/Parquet format; keep hidden truth and the single all-source
      `source-run.duckdb` mirror in a
      restricted evaluation prefix.
- [ ] Package `ingestion/` raw gate, profile-driven normalizer/adapters, standardized staging,
      source-neutral transforms, canonical gate and curated publisher as SageMaker Processing
      jobs.
- [ ] Build landing manifests/coverage/controls when upstream does not supply them; derive
      timestamps plus the entity's declared explicit version or observation identity from
      immutable source/landing evidence with provenance or quarantine.
- [ ] Persist lineage, reconciliation and quarantine artifacts; atomically publish passing
      canonical Parquet to S3 **curated**.
- [ ] Assert curated locations/stores retain `market_id`, operating `currency_code` and timezone;
      execute the ingestion-owned source-truth→canonical expected-control oracle in CI.
- [ ] Assert contextual feeds retain market-qualified `geo_scope_*` or structured promotion
      applicability, observation/reference identity follows the canonical temporal class,
      `merch_scope_*` precedence is deterministic, Shopify presentment money is audit-only and
      unsupported sales-currency mismatches quarantine.
- [ ] Run shared exact FX vectors for local/base→reporting/quote direction, decimal precision,
      exponent handling and per-fact `ROUND_HALF_EVEN`.
- [ ] Re-run the core Shopify+BC+companion round-trip in-cloud; validate detailed fulfillment,
      return/refund, inventory-state and HMAC conformance for every enabled v4 feature.
- [ ] **Exit:** Gate A passes every source; pure Shopify is `validated_partial` and unpromoted;
      the configured composite passes its required Gate-B capability mask and registers a curated
      run.

## Phase A2 — ML pipeline (features, forecast, elasticity)
- [ ] Market-local calendar and dimensionless/local-normalized price feature build job → S3
      features prefix (point-in-time).
- [ ] LightGBM forecast job (P50/P90, horizons → 26 wk, Croston routing).
- [ ] Market-scoped Poisson-EB elasticity job + gates; no raw price-tier pooling across currencies.
- [ ] Response-rich IN+US cloud run reaches ≥25 actually gated series per enabled department in
      each market; sparse preset emits reason-coded `insufficient_evidence`.
- [ ] Orchestrate with Step Functions / SageMaker Pipelines.
- [ ] Apply the shared ML execution namespace to feature/fold/model concurrency and trainer
      threads; prevent nested oversubscription against the explicit job CPU/memory request.
- [ ] Artifacts + manifests + fingerprints to S3; log MLflow + SageMaker Model Registry.
- [ ] Forecast acceptance/calibration enforced globally and per supported market in-pipeline.
- [ ] **Exit:** one-click run yields accepted, fingerprinted forecast artifacts.

## Phase A3 — Engines & batch decisioning
- [ ] Reorder/safety-stock, pricing, allocation, transfer, ageing engine jobs.
- [ ] Policy calibration (5%) + validation (95%).
- [ ] Resolve/fingerprint pricing rules by `market_id + currency_code`; require local absolute
      money/grid/ending rules and retain only dimensionless global defaults.
- [ ] Keep ABC/valuation market-local or apply an approved as-of reporting conversion before
      cross-market ranking; retain unit decisions independently and use the shared per-fact FX
      rounding contract.
- [ ] Publish revenue pricing without implying margin; enable margin only when accepted temporal
      cost-as-of is present in the recommendation currency.
- [ ] Write recommendations/drafts → RDS; artifacts → S3.
- [ ] **Exit:** replenishment + pricing artifacts published under guardrails.

## Phase A4 — Aarv-based Go API & workflow
- [ ] Containerize Go `api/` with exact pinned
      [Aarv](https://github.com/nilshah80/aarv) core/plugin modules; push to ECR. Keep
      `contracts/` OpenAPI authoritative and application logic framework-neutral.
- [ ] ECS Fargate service behind ALB / API Gateway.
- [ ] Implement the Go resolver against the shared execution schema/golden vectors; map it to
      `GOMAXPROCS`, HTTP/job concurrency and DB pools within the task CPU/memory allocation.
- [ ] RDS wiring (workflow, audit, recs); Alembic migrations applied.
- [ ] Cognito auth + RBAC; map roles/approval tiers.
- [ ] Serve S3 artifacts with explicit market/currency; re-resolve the same market guardrail
      payload at serve time; preserve reason-coded evidence blocks; staleness 409/503.
- [ ] Fingerprint parity with Python (shared golden vectors) in-cloud.
- [ ] **Exit:** API serves live artifacts; approve/override audited; auth enforced.

## Phase A5 — UI deployment
- [ ] Package and deploy the incrementally completed local UI; do not defer front-end
      implementation to this cloud phase. Host on S3 + CloudFront (or Amplify).
- [ ] Point at API Gateway/ALB; configure CORS/auth; FX display.
- [ ] **Exit:** all screens render live cloud data.

## Phase A6 — Orchestration & unattended run
- [ ] EventBridge schedule → Step Functions nightly (generate → ingest/transform → ML → engines → publish).
- [ ] Idempotent republication; alerting to CloudWatch/SNS.
- [ ] **Exit:** unattended scheduled run completes + republishes idempotently.

## Phase A7 — Security, residency, observability, cost, DR
- [ ] KMS at rest + TLS in transit everywhere; VPC endpoints (no public data egress).
- [ ] IAM least-privilege review; secrets rotation.
- [ ] CloudWatch dashboards/alarms + X-Ray traces.
- [ ] Cost budgets/tags; backup + retention; DR runbook.
- [ ] Document client-data residency boundary (separate account for any real data).
- [ ] **Exit:** security + cost reviews pass; residency boundary documented.
