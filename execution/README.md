# `execution/` — shared operational execution profiles

This independently installable, source-neutral package resolves hardware/runtime controls for
datagen, ingestion and ML. The [Aarv](https://github.com/nilshah80/aarv)-based Go API implements
the same versioned JSON contract and golden vectors in its own runtime; its adapter maps the
resolved API namespace to HTTP concurrency, queue, timeout and pool controls without letting the
web framework change business semantics.

Execution settings may change throughput, memory use and spill behavior only. They never change
retailer scenarios, canonical data, model/policy semantics, source-run IDs or business
fingerprints.

The datagen distribution packages this shared runtime from the same source so
`pip install -e datagen` remains standalone and never tries to resolve a private
package from PyPI. Install `execution/` independently for ingestion/ML development:

```powershell
# Windows PowerShell
.\datagen\.venv\Scripts\python.exe -m pip install -e datagen
.\ingestion\.venv\Scripts\python.exe -m pip install -e execution
```

```bash
# macOS / Linux
datagen/.venv/bin/python -m pip install -e datagen
ingestion/.venv/bin/python -m pip install -e execution
```

The resolver itself is platform-neutral: it handles values and validation only. Layer adapters
must use native path/process/pool primitives. Execution profiles cannot select a different
business result by OS, and the golden vectors must pass on Windows, macOS and Linux.

Resolution precedence is:

```text
explicit CLI/environment override > supplied profile document > named profile > safe
```

The package never auto-expands to all detected host CPU/RAM. Every profile is bounded and
validated before work starts.

The machine-readable contract is under
`src/retail_execution/data/v1/`:

- `profiles.json` contains the four named profiles and reserved layer namespaces;
- `schema.json` is the active portable validator for datagen, ingestion, ML and API blocks;
- `golden-vectors.json` locks resolution/override behavior for both the Python resolver and the
  native Go API resolver.

Phase 1 implements the `datagen` adapter; Phase 2 implements ingestion and API adapters.
`marketWorkers` runs independent markets in separate
processes; `partitionWorkers` controls authoritative CSV/Parquet publication;
`duckdbThreads` controls the single browsing mirror; `memoryLimitGb` bounds DuckDB operations;
and `spoolChunkRows` bounds each private stream buffer. In
`market/partition/DuckDB/memory-GiB/spool-rows` order, safe, balanced, performance and
ultra-performance resolve to `1/2/1/4/10000`, `1/4/2/8/25000`, `2/8/6/32/50000` and
`2/16/8/64/100000` respectively. Ultra keeps two market processes because the demo has two
causally independent markets; it spends the additional workstation capacity on publication,
DuckDB and larger bounded buffers.

Environment overrides are intentionally narrow:

```text
RETAIL_EXECUTION_PROFILE
RETAIL_DATAGEN_MARKET_WORKERS
RETAIL_DATAGEN_PARTITION_WORKERS
RETAIL_DATAGEN_DUCKDB_THREADS
RETAIL_DATAGEN_MEMORY_LIMIT_GB
RETAIL_DATAGEN_SPOOL_CHUNK_ROWS
```

The Config Builder emits a datagen-only document. The resolver fills the other reserved
namespaces from the selected named profile, so later ingestion/ML/API adapters can consume the
same version without scenario/config coupling.
