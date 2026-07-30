# `deploy/` — Infrastructure & local run

**Purpose:** how the pieces run together locally and in a controlled environment — service
orchestration and environment/config.

**Timing:** decision #63 brings the first Compose slice into Phase 3. Docker Desktop runs a pinned
PostgreSQL service for the forecast API projection and a pinned shared MLflow tracking server.
Phase 6 extends the stack with mutable workflow/governance state, the API and UI; it is no longer
the first introduction of PostgreSQL or Compose.

**Current contents:**
- `compose.yaml` with PostgreSQL 17.10 and MLflow 3.14.0. PostgreSQL owns durable metadata and the
  `retail_serving` forecast projection; MLflow metadata shares the local database while artifacts
  use a separate named volume.
- `mlflow/Dockerfile`, which adds the pinned Psycopg driver to the official MLflow image.
- `.env.example` with local-only defaults. Copy it to `.env` for overrides; `.env` is ignored and
  must not be committed.

The services bind only to loopback by default. Start and inspect them with the portable developer
entry point:

```powershell
python tools/dev.py services up
python tools/dev.py db-env
python tools/dev.py db-upgrade
python tools/dev.py services status
python tools/dev.py db-current
python tools/dev.py services logs
python tools/dev.py services down
```

The default host endpoints are:

- PostgreSQL:
  `postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence`
- MLflow: `http://127.0.0.1:5000`

Named volumes survive `services down`. Destructive volume removal is deliberately not exposed by
the developer command; use an explicit reviewed Docker operation if a reset is genuinely needed.

After publishing an accepted immutable forecast bundle, materialization and activation are
deliberately separate:

```powershell
python tools/dev.py forecast-materialize --forecast-run ml/data/artifacts/<accepted-run>
python tools/dev.py forecast-activate --forecast-run-id <fr_...> --activation-scope-fingerprint <sha256> --actor <name>
```

The first command verifies the current curated input pin and all ten forecast artifacts before one
PostgreSQL transaction. It prints the activation-scope fingerprint needed by the second command.

**Later contents:**
- Add the [Aarv](https://github.com/nilshah80/aarv)-based Go `api/` and UI services in Phase 6.
- Keep `datagen/`, ingestion and ML execution as explicit batch jobs rather than long-running
  Compose services.
- Local run instructions and environment/secret configuration.
- The locked decision #38 Python topology: `datagen/`, `ingestion/` and `ml/` are separate
  environments/distributions; ingestion and ML both depend on the shared `retail-contracts` and
  `retail-intelligence-execution` packages. `contracts/` may change meaning, while `execution/`
  changes throughput only.
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

**Origin:** adapted from the M5 PoC Compose shape (`[REUSE-as-redesign]`) for the Python-batch /
Go-service topology.

**Spec:** Architecture note; §11.10 (end-to-end flow).
