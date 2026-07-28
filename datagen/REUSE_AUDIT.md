# Datagen reuse audit

Sources reviewed:

- `../../retail-synthetic-data-generator`;
- `../../retail_ai/scripts/generate_synthetic_extension.py` and its pandemic tests.

| Reference area | Decision | Phase-1 treatment |
|---|---|---|
| `core/identity.py` seed derivation | Adapt | SHA-256 stable-key RNG derivation retained; mutable counters removed |
| Shopify GID and Business Central UUID formats | Adapt | Source-native formats/namespaces retained with order-independent business-key allocation |
| `core/identity.py` `RunContext` | Replace | Run ID is content-derived from generator version, source-spec version and resolved-config hash; wall-clock time is not identity |
| `core/checkpoint.py` atomic replace | Adapt | Atomic temp-file/staging-directory promotion retained; old inventory/PO/return checkpoint state is not copied |
| `storage/writer.py` checksums/manifest pattern | Adapt | Per-object hashes, rows and controls retained; publication is source-shaped CSV, a single all-source DuckDB mirror and a JSON manifest |
| `storage/writer.py` fixed `retail.duckdb` contract | Replace | The authoritative canonical/ML-ready database was rejected. `source-run.duckdb` is instead a non-authoritative, all-text mirror of the run's selected CSV/Parquet source objects, including restricted truth when enabled |
| `core/controller.py` | Replace | New orchestration validates the generator-owned config and publishes Shopify/BC/companion sources only |
| `cli/main.py` command shape | Adapt | `validate-config`, `plan`, `generate`, `locales` and `catalogs` retained/extended conceptually; stdlib `argparse` keeps the first package dependency-light |
| `config-builder.html` standalone authoring model | Adapt | Standalone page retained; flat counts/US assumptions replaced by explicit multi-market topology and locale packs |
| `configs/baseline-20yr.yml` | Adapt | 2005–2024 preset, compound growth, GFC/tariff/supply/inflation shocks and COVID demand/supply phases retained as generator-owned multi-market settings; full preset execution, rather than only config parsing, is covered by acceptance evidence |
| chronological simulation partitions | Adapt | Causal state advances by day; all time-bearing source outputs are physically grouped by configured month/day and mirrored as one logical DuckDB table |
| `startingDailyOrders / active variants` demand calibration | Adapt | Opening order volume is distributed across the currently active store assortment by normalized deterministic variant popularity; explicit market/store scalars replace the old implicit single-location assumptions |
| monthly checkpoint/resume | Defer | Atomic run publication and completed-run reuse are retained. Mid-run monthly resume is not claimed: this implementation builds cross-source projections from one causal state in memory. The CLI plan reports the long-run memory boundary explicitly |
| `generators/master_data.py` product/variant model | Adapt | Product/variant separation, deliberately partial option matrices, independent product/variant release dates, lifecycle gating, replacements, per-variant price/cost, popularity, elasticity and returns retained; opening-incumbent share plus forward launch spread prevent a long history from starting with an empty catalog; NumPy/Faker, canonical keys, generic `Category Word N` titles and `SKU-P...-V...` identifiers are replaced by versioned IN/US/GB/DE real-brand reference packs, stable product codes, sellable SKUs and valid EAN-13/UPC-A checksums |
| `features/ml_ready.py` and public cross-system mapping | Do not reuse | Downstream features and mappings remain outside `datagen/`; only restricted generator-vocabulary truth is emitted |
| `retail_ai` `PANDEMICS`/`PandemicEngine` | Adapt | H1N1 waves and normalization, neutral Ebola/Zika/Mpox evidence, overlapping COVID early-stocking/panic/stockout/lockdown/home/supply/Delta/Omicron/inflation phases, specificity concepts and deterministic phase timing adapted to market/department/category/catalog-family/channel source config; daily signals and restricted SKU/store causal truth preserve the distinction between a declared timeline and a demand adjustment |
| `retail_ai` M5-specific pandemic targets | Do not copy | Walmart food/household item types, SNAP and real-M5 block behavior are dataset-specific; datagen uses its own apparel/electronics catalog families and source topology |

The new package imports no repository downstream module. Its automated isolation test rejects
imports from `contracts`, `ingestion`, `ml` or `api`.
