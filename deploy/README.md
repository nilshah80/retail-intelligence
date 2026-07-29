# `deploy/` — Infrastructure & local run

**Purpose:** how the pieces run together locally and in a controlled environment — service
orchestration and environment/config.

**Planned contents:**
- `docker-compose` for PostgreSQL, MLflow, the
  [Aarv](https://github.com/nilshah80/aarv)-based Go `api/`, and Python
  `datagen/`/`ingestion/`/`ml/` jobs.
- Local run instructions and environment/secret configuration.
- An explicit Python environment/lock strategy: `datagen/` is always isolated; whether
  independently deployed `ingestion/` and `ml/` use separate or shared governed environments is
  decision #38 and must be locked before scaffolding their package/workspace boundary. It does
  not block the independently isolated Phase-1 `datagen/` scaffold.
- Install the source-neutral `execution/` resolver into each Python job environment. It supplies
  bounded operational defaults and golden vectors only; it is not a reason to merge the datagen,
  ingestion and ML environments. The Go API implements the same JSON contract natively.
- Pin Aarv core and any optional Aarv plugin modules in `api/go.mod`; the container build must use
  that lock state rather than fetching `@latest`.
- Data-flow wiring: `datagen/` source outputs → `ingestion/` raw landing/Gates/transforms →
  curated lake → `ml/` artifacts → `api/`.
- Windows, macOS and Linux host instructions. Docker Desktop may run Linux containers on Windows
  or macOS, but host-side commands, environment-file handling, volume paths and health checks
  must be PowerShell/npm/Python compatible and must not require Bash, POSIX permissions or
  hard-coded `/var`/`/tmp` host paths. Container-internal Linux behavior is not evidence that the
  host workflow works on Windows; all three host workflows require smoke tests.

**Origin:** adapt the M5 PoC's `docker-compose.yml` + `infra/` (`[REUSE]`), split for the
Python-batch / Go-service topology.

**Spec:** Architecture note; §11.10 (end-to-end flow).

_No code yet — information only._
