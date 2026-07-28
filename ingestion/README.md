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

Planned contents:

- `landing/` — immutable snapshots, landing timestamps, hashes and idempotent replay;
- `profiles/` — declarative source schema, format, field, key, timezone, currency, tax and
  semantic policies for datagen, Shopify, Business Central and other retailer sources;
- `adapters/` — profile-driven default mapper plus bounded source-specific adapters, all ending at
  the same staging contract;
- `staging/` — versioned source-neutral envelopes;
- `transforms/` — source-neutral joins, filtering, code mapping, time/money/unit normalization,
  order/refund/fulfillment semantics, inventory rules, aggregation and provenance;
- `quality/` — Gate A, Gate B, capability evaluation, reconciliation and quarantine;
- `tests/oracles/` — profile-versioned translation from generator-vocabulary hidden controls to
  expected canonical controls for golden round-trip tests; never a runtime transform or datagen
  dependency;
- `warehouse/` — atomic curated Parquet/DuckDB publication.

## Source-tolerance rule

Actual retailers do not all supply `known_as_of`, availability versions, source manifests,
Parquet/JSONL, config hashes or complete capability declarations. These are therefore not
universal raw-source requirements.

The source profile/adapter must declare how each missing operational property is handled:

- use trusted native creation/update/observation timestamps when available;
- otherwise derive `observed_at` from immutable extraction/landing time and record the derivation;
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

Datagen v5 publishes one authoritative tabular format per run—CSV or Parquet—and a single
`source-run.duckdb` mirror. Gate A must support both authoritative formats. For the PoC it may
also use a dedicated datagen-DuckDB source profile to accelerate staging, provided it:

- lands the DuckDB and manifest immutably and validates them against the object/catalog hashes;
- selects datasets through `source_object_catalog`/`source_dataset_catalog`, never hard-coded
  table names;
- admits only `restricted=false` datasets into ordinary staging;
- prevents every `_truth/*`/`truth_*` dataset from entering transformations or ML features;
- records the authoritative CSV/Parquet logical path, format, compression and hash as lineage,
  even when rows were read from the DuckDB mirror.

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

_No code yet — information only._
