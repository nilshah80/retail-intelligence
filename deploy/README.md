# `deploy/` — Infrastructure & local run

**Purpose:** how the pieces run together locally and in a controlled environment — service
orchestration and environment/config.

**Planned contents:**
- `docker-compose` for PostgreSQL, MLflow, the Go `api/`, and the Python `ml/` batch jobs.
- Local run instructions and environment/secret configuration.
- Data-flow wiring: `datagen/` output dir → `ml/` ingest `raw_dir` → curated lake → `api/`.

**Origin:** adapt the M5 PoC's `docker-compose.yml` + `infra/` (`[REUSE]`), split for the
Python-batch / Go-service topology.

**Spec:** Architecture note; §11.10 (end-to-end flow).

_No code yet — information only._
