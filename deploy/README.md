# `deploy/` — Infrastructure & local run

**Purpose:** how the pieces run together locally and in a controlled environment — service
orchestration and environment/config.

**Planned contents:**
- `docker-compose` for PostgreSQL, MLflow, the Go `api/`, and Python
  `datagen/`/`ingestion/`/`ml/` jobs.
- Local run instructions and environment/secret configuration.
- An explicit Python environment/lock strategy: `datagen/` is always isolated; whether
  independently deployed `ingestion/` and `ml/` use separate or shared governed environments is
  decision #38 and must be locked before scaffolding their package/workspace boundary. It does
  not block the independently isolated Phase-1 `datagen/` scaffold.
- Data-flow wiring: `datagen/` source outputs → `ingestion/` raw landing/Gates/transforms →
  curated lake → `ml/` artifacts → `api/`.

**Origin:** adapt the M5 PoC's `docker-compose.yml` + `infra/` (`[REUSE]`), split for the
Python-batch / Go-service topology.

**Spec:** Architecture note; §11.10 (end-to-end flow).

_No code yet — information only._
