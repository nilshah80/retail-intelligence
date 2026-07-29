# `ingestion/` — Source ingestion and canonical transformation

**Purpose:** own the complete boundary from immutable source data to curated `retail_v2`:

```text
immutable raw landing
  → Gate A
  → source profile or bounded adapter
  → standardized staging
  → source-neutral transformations
  → canonical retail_v2 candidate
  → Gate B
  → curated Parquet/DuckDB
```

**Language:** Python.

## Ownership

Owned contents:

- `landing/` — immutable snapshots, landing timestamps, hashes and idempotent replay;
- `profiles/` — declarative source schema, format, field, key, timezone, currency, tax and
  semantic policies for datagen, Shopify, Business Central and other retailer sources;
- `readers/` — physical Parquet/CSV/JSONL/JSON access without retailer semantics;
- `adapters/` — bounded source-specific semantic adapters, all ending at the same staging
  contract;
- `staging/` — versioned source-neutral envelopes;
- `transforms/` — source-neutral joins, filtering, code mapping, time/money/unit normalization,
  order/refund/fulfillment semantics, inventory rules, aggregation and provenance;
- `quality/` — Gate A, Gate B, capability evaluation, reconciliation and quarantine;
- an optional future `tests/oracles/` extension may translate generator-vocabulary hidden
  controls to expected canonical controls; it must never become a runtime transform or datagen
  dependency;
- `publication/` — atomic curated Parquet/DuckDB publication.

## Current implementation status

The Phase-2 implementation now includes:

- a Windows/macOS/Linux CLI and bounded runtime adapter using the shared execution resolver;
- streaming immutable landing with byte-count/SHA-256 verification;
- ingestion-owned RFC-8785 `source_snapshot_id`, separately retained native run ID, idempotent
  replay and corrupt native-ID reuse detection;
- atomic snapshot promotion into physically separate `public`, `restricted_truth` and
  `restricted_mirror` roots;
- portable logical-path validation, including Windows-invalid/reserved path rejection;
- A01–A13 Gate-A validation with machine-readable evidence and a public-lane-only reader;
- format readers for Parquet, CSV, JSONL and JSON, kept separate from source semantics;
- bounded Shopify, Business Central and companion adapters feeding one standardized staging
  contract;
- source-neutral canonical transforms for the revenue/forecasting slice plus inventory, supplier,
  promotion, competitor and external-signal evidence;
- B01–B21 Gate-B validation, reason-coded warnings/capability downgrades, exact per-currency
  reconciliation and critical-publication refusal;
- atomic publication to one curated DuckDB plus partitioned Parquet;
- resumable end-to-end and retained/disposable per-stage benchmark commands;
- real isolated-wheel and static import-boundary checks;
- the machine-readable 53-entity contract, exact money/FX/fingerprint utilities, guardrail
  resolver/vectors and generated Python/Go/TypeScript row types;
- an Aarv-based read-only Go API and React Data Management dashboard over accepted evidence.

The full pin is landed as snapshot
`dafa9d4228181c25a3562fef0362317f52675a6013669134285247e6179de5b4`: all 8,644 objects
were streamed through byte/SHA-256 verification into 8,398 public, 245 restricted-truth and one
restricted-mirror object. A repeat request under another execution profile was an idempotent replay.
The retained ultra-performance pipeline publishes 40 canonical entities, 1,314 Parquet objects
and one `retail_v2.duckdb`. It scanned 226,929,388 public rows, opened zero restricted objects and
reconciled INR and USD gross/net/tax/units with zero differences. Its measured wall time was
151.369044 seconds: Gate A 6.287349, staging 129.017609, transform 9.934884, Gate B 0.773671 and
publication 5.355531 seconds. Safe and ultra-performance runs produced the same candidate and
Gate-B semantic fingerprints. Physical Parquet object count may vary with writer concurrency and
is deliberately excluded from semantic identity.

The authoritative cross-platform entry point is:

```powershell
# Windows PowerShell
py -3 tools/dev.py contracts
py -3 tools/dev.py test
py -3 tools/dev.py land --source-root datagen\output\multi-market-10-year-demo\run-34b0ff729c8abe09 --landing-root ingestion\data\raw --execution-profile safe
```

```bash
# macOS / Linux
python3 tools/dev.py contracts
python3 tools/dev.py test
python3 tools/dev.py land --source-root datagen/output/multi-market-10-year-demo/run-34b0ff729c8abe09 --landing-root ingestion/data/raw --execution-profile safe
```

The `Makefile` is a POSIX convenience only. Windows does not require Make or a Unix shell.
Manifest/catalog paths are normalized logical `/` paths; physical access uses `pathlib`.
Landing and warehouse writers stage on the destination volume and close files, Arrow readers,
memory maps and DuckDB connections before promotion. Windows-invalid/reserved and
case-colliding paths fail before copying. Phase 2 is not portable-complete until landing, gates,
transforms and publication fixtures pass on Windows, macOS and Linux.

Run the retained snapshot through every governed stage:

```powershell
# Windows PowerShell
py -3 tools/dev.py run --snapshot-root ingestion\data\raw\snapshots\dafa9d4228181c25a3562fef0362317f52675a6013669134285247e6179de5b4 --work-root ingestion\data\work\run-34b0ff729c8abe09 --publication-root ingestion\data\curated\run-34b0ff729c8abe09 --execution-profile ultra-performance
```

```bash
# macOS / Linux
python3 tools/dev.py run --snapshot-root ingestion/data/raw/snapshots/dafa9d4228181c25a3562fef0362317f52675a6013669134285247e6179de5b4 --work-root ingestion/data/work/run-34b0ff729c8abe09 --publication-root ingestion/data/curated/run-34b0ff729c8abe09 --execution-profile ultra-performance
```

The checked-in datagen source profile has the stable filename
`src/retail_ingestion/profiles/retail_datagen.yaml`. Profile and upstream source-contract
versions are fields inside the document. Do not encode routine schema versions in filenames;
create a separate profile only when two semantically different contracts must coexist.

## Reader, profile and adapter boundary

A file format is not a retailer adapter. The layers are intentionally separate:

1. `readers/` opens declared Parquet, CSV, JSONL or JSON objects without interpreting retail
   meaning.
2. `profiles/` declares source instances, datasets, keys, grains, currencies, timezones, evidence
   policies and mapping references. Explicit `pathGlob` declarations let ingestion inventory a
   retailer drop that does not carry a generator-style manifest.
3. `adapters/` owns source semantics. Shopify, Business Central and companion adapters translate
   their native identifiers and fields into the common staging contract.
4. `staging/` and `transforms/` are source-neutral. They never branch on retailer names or import
   source-adapter modules.

Onboarding another retailer therefore adds a profile and, only when its semantics differ, one
bounded adapter registered in `adapters/registry.py`. CSV versus Parquet does not require another
adapter. Arbitrary columns cannot be inferred safely: an unrecognized retailer shape stops at
Gate A or is capability-downgraded until an explicit mapping/adapter exists. This keeps retailer
differences maintainable and prevents guessed business semantics from leaking into ML.

## Shared execution profiles

Ingestion installs the independent `execution/` Python package already used by datagen.
Its ingestion namespace resolves bounded scan, transform, partition-write and DuckDB
worker/thread counts plus memory/spill ceilings. A narrow ingestion adapter owns the actual pools
and cleanup; no datagen code is imported.

The selected execution YAML is operational input, not a source profile or canonical contract.
The resolved non-secret values and stage telemetry belong in the ingest manifest, but not in raw
content hashes, canonical fingerprints or capability decisions. Safe and ultra-performance runs over
the same landing snapshot must produce identical accepted/quarantined keys, controls, Gate A/B
outcomes and canonical hashes.

## Source-tolerance rule

Actual retailers do not all supply `known_as_of`, availability versions, source manifests,
Parquet/JSONL, config hashes or complete capability declarations. These are therefore not
universal raw-source requirements.

The source profile/adapter must declare how each missing operational property is handled:

- use trusted native observation/processing/extraction timestamps when they establish availability;
- otherwise derive `known_as_of` from immutable extraction/landing evidence and record
  `known_as_of_evidence_grade`; business/effective time never becomes availability by default;
- construct explicit monotonic versions by deterministic snapshot/event differencing only for
  canonical cumulative/correctable facts; reference/observation facts instead use their declared
  natural key + effective/observation time + `known_as_of`;
- build the ingestion manifest, hashes, coverage and control totals at landing when the source
  did not provide them;
- parse any explicitly supported source format and normalize it at staging;
- quarantine ambiguity rather than silently invent business facts.

Derived metadata always carries provenance and a quality policy. It can satisfy a synthetic PoC
profile when defensible, but a client-actual capability may impose stricter evidence.

## Datagen source-format and DuckDB profile

Datagen source contract v11 publishes one authoritative tabular format per run—CSV or
Parquet—and a single all-source `source-run.duckdb` mirror. Gate A must support both authoritative
formats.

**The all-source mirror is not a permission boundary.** It contains public source tables *and*
restricted `_truth` in one file, so filtering `restricted=false` in application code is a logical
filter only: any process able to open the database can query truth tables. Landing therefore uses
three permission lanes:

- **public lane** — public source objects plus public generator metadata. The **only** lane
  ordinary ingestion (landing → staging → transforms → gates → ML) may read.
- **restricted truth lane** — `_truth/*`, readable only by the test/evaluation oracle under
  oracle-admin permission.
- **all-source mirror lane** — `source-run.duckdb`, oracle/evaluation-admin only. Never an
  ingestion input. Note the restricted set is not coextensive with `_truth/`: the mirror is its own
  category, so a profile that refuses every `_truth/*` dataset while opening the whole mirror has
  not been prevented from reading truth.

When DuckDB speed is wanted for staging, ingestion builds its own **public-only** DuckDB cache from
landed public Parquet. Note that `source_object_catalog` and `source_dataset_catalog` live *inside*
the restricted all-source mirror, so the cache builder cannot use them to discover datasets — that
would require opening the prohibited file. It discovers datasets from **public manifest metadata**
instead:

1. read the public `source-run-manifest.json` and `source-schema.json`;
2. select manifest objects where `restricted == false`;
3. load those public Parquet/CSV objects, having validated them against the landing manifest hashes;
4. **build ingestion-owned `source_object_catalog` and `source_dataset_catalog` inside the derived
   public-only DuckDB** — the cache publishes its own catalogs rather than copying the mirror's;
5. preserve the manifest paths, hashes, formats and compression as lineage.

The result contains no `restricted=true`/`_truth/*`/`truth_*` dataset **by construction, not by
filter**, and remains a disposable derived cache that never becomes the lineage authority.

Reading the all-source mirror's own catalogs is legitimate only in the one-time run-acceptance
check, performed under oracle/evaluation-admin permission, that reconciles those catalogs against
the authoritative Parquet objects. That is an acceptance activity, not an ingestion path.

The DuckDB path is a synthetic-run convenience, not a requirement for real retailers. A retailer
may land CSV, Parquet, JSONL, API extracts or another declared format directly; its profile still
normalizes to the same staging contract.

## Locale and money normalization

Source amounts remain exact in their declared local currency. Ingestion converts decimal major
units to integer minor units using locale/currency metadata (`INR` paise, `USD` cents, `GBP`
pence, `EUR` cents), normalizes inclusive/exclusive tax while retaining tax separately, and
reconciles each source currency independently. Reporting-currency conversions are derived using
as-of FX and never replace source-money controls.

Canonical locations carry `market_id`, operating `currency_code` and IANA `timezone`; the
derived demand-only `stores` view preserves them. Canonical sales and sell prices must use the
location operating currency; Shopify `shopMoney` is authoritative and `presentmentMoney` remains
raw/staging audit evidence. An unsupported mismatch cannot satisfy the sales-money capability.
Pricing/margin capabilities are evaluated within one market currency, while cross-market value
reporting uses exact local/base→reporting/quote rates, exponent-aware `ROUND_HALF_EVEN` per fact
and the separately governed FX accounting policy.

Calendar/event, weather, local-event, macro and competitor mappings must preserve
`market_id + geo_scope_type + geo_scope_id`. Gate B rejects unqualified `ALL`, cross-market
geographic joins and unknown targets. Supplier terms and promotion merchandise targets normalize
to `merch_scope_type + merch_scope_id` with `sku > dept > category`; supplier destination/origin
remains explicit, and a null origin denotes an unmodelled external supplier origin rather than a
wildcard. Promotion applicability retains its separate multi-axis region/location/channel rows
with AND-within-row and OR-across-row semantics.

## Boundary rules

- Adapters know source systems but may not emit final canonical aggregates.
- Shared transforms operate on staging and may not branch on retailer/platform identity.
- Gate A validates the landed source and resolved ingestion metadata.
- Gate B validates canonical schema, point-in-time behavior, provenance, capability dependencies
  and reconciliations.
- `validated_partial` stops before curated publication.
- Only capability-complete Gate-B passes are available to `ml/`.
- Canonical component fixtures, if needed, are owned by ingestion/contract tests—not emitted by
  `datagen/`.
- Golden round-trip comparison uses an ingestion-test-owned, profile-versioned
  source-truth→canonical control oracle; production transforms do not read hidden truth.

**Spec:** §4.1 and §11.
