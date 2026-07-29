# `execution/` — shared operational execution profiles

This independently installable, source-neutral package resolves hardware/runtime controls for
datagen, ingestion and ML. The Go API implements the same versioned JSON contract and golden
vectors in its own runtime.

Execution settings may change throughput, memory use and spill behavior only. They never change
retailer scenarios, canonical data, model/policy semantics, source-run IDs or business
fingerprints.

The datagen distribution packages this shared runtime from the same source so
`pip install -e datagen` remains standalone and never tries to resolve a private
package from PyPI. Install `execution/` independently for ingestion/ML development:

```bash
datagen/.venv/bin/pip install -e datagen
ingestion/.venv/bin/pip install -e execution
```

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
- `golden-vectors.json` locks resolution/override behavior for Python now and Go later.

Phase 1 implements the `datagen` adapter. `marketWorkers` runs independent markets in separate
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
