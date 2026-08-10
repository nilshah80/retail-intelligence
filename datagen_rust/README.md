# Rust retail datagen

This directory is an isolated Rust implementation of the source-shaped retail data generator.
It does not import, overwrite, delete, or publish into the Python generator, ingestion, ML, API,
database, or UI paths. Rust output is comparison evidence until an explicit later cutover.

The pinned compiler is Rust 1.97.1. `Cargo.lock` pins third-party dependencies after the first
successful dependency resolution.

## Commands

```bash
cargo run --release -- execution-profiles
cargo run --release -- validate --config configs/gulf-oil-india-ten-year.yaml
cargo run --release -- plan \
  --config configs/gulf-oil-india-ten-year.yaml \
  --execution-profile-file configs/safe.execution.yaml
cargo run --release -- generate \
  --config configs/gulf-oil-india-ten-year.yaml \
  --execution-profile performance
cargo run --release -- compare \
  --python-run ../datagen/output/gulf-oil-india-ten-year/gulf-oil-india-ten-year/run-1430a7ddabc5d4ff \
  --rust-run output/gulf-oil-india-ten-year/gulf-oil-india-ten-year/<rust-run-id>
```

## Standalone scenarios and execution profiles

`configs/` contains byte-for-byte copies of the checked-in Python YAML/JSON scenarios, so Rust
validation, planning, generation, and replay do not require a scenario path under `datagen/`.
The retained full Gulf comparison was generated from `gulf-oil-india-ten-year.yaml`, whose canonical
hash is `028fdbc5…`. Python's checked-in JSON is a distinct/stale resolved scenario (`d26b7da4…`),
so YAML and JSON must not be substituted in a matched benchmark unless their reported config hashes
are first shown equal.

The four `*.execution.yaml` files use Python's `retail-execution-profile/v1` datagen shape and
values. Named profiles and profile files resolve to the same manifest settings:

| Profile | Market workers | Simulation/partition workers | DuckDB threads | Memory limit | Spool rows |
|---|---:|---:|---:|---:|---:|
| `safe` | 1 | 2 | 1 | 4 GiB | 10,000 |
| `balanced` | 1 | 4 | 2 | 8 GiB | 25,000 |
| `performance` | 2 | 8 | 6 | 32 GiB | 50,000 |
| `ultra-performance` | 2 | 16 | 8 | 64 GiB | 100,000 |

`partitionWorkers` bounds both Rust's dedicated Rayon simulation pool and partition publication;
`spoolChunkRows` bounds in-memory row buffers; `duckdbThreads` and `memoryLimitGb` are applied to
DuckDB. The current deterministic causal engine processes market streams in one process, so
`marketWorkers` is retained for Python profile/manifest compatibility but effective market-process
parallelism is currently one (including the single-market Gulf scenario). This limitation affects
multi-market throughput, not rows. `--profile` remains an alias for `--execution-profile`.

The selected values are printed by `plan`, printed again in the completed `generate` result, and
recorded as `executionProfile` in `source-run-manifest.json`. The default is `safe`. Because a
runtime profile does not affect run identity, benchmark two profiles under different
`--output-root` containers; an existing run is intentionally never overwritten.

`generate` defaults to `output/<scenarioId>/<scenarioId>/<run-id>`, matching the retained
Python Gulf container/run hierarchy. Dataset directories, partition directories, and filenames
inside the run are the same source-shaped names as Python. `datagen_rust/output/` is ignored by
Git and generated comparison data must never be staged or pushed.

Generation stages into a sibling temporary directory and promotes by atomic rename. Existing
targets are never reused or overwritten unless the caller passes an explicit future-supported
replacement policy; the initial implementation refuses an existing target.

## Compatibility and acceptance policy

- Input contract: `retail-source-config/v13` YAML or JSON.
- Engine version: recorded independently in every comparison artifact; it does not relax source
  semantics.
- Exact logical parity is mandatory for an identical resolved config and master seed: the complete
  dataset set, schemas, partition membership, deterministic order, row counts, IDs, field values,
  relationships, controls, and normalized ordered semantic digests must match Python. Statistical
  or distribution-only similarity is not acceptance.
- Physical Parquet bytes are not required to match because the Rust Arrow writer and Python
  DuckDB writer can encode equivalent logical rows with different metadata, pages, or encodings.
- Runtime profile: changes scheduling and memory limits only, never logical rows.
