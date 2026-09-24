# Disposable Castrol demo

This directory contains the standalone conversion and launcher. Existing UI,
API, pipeline, source configuration and the original PostgreSQL volume are not
modified. Runtime files and check results are generated in
`.serve-runtime/castrol-demo/`.

The demo uses PostgreSQL container `retail-castrol-demo-postgres`, volume
`retail-castrol-demo-data`, and local port **55432**. Its internal database name
remains `retail_intelligence`, satisfying the existing pricing startup contract.
The original Gulf database uses a different container/volume on port 5432.

## What the data means

- Castrol is the own brand. Both Castrol and Gulf are excluded as competitors.
- `product-map.json` maps all 73 source product names using official Castrol
  references. Six unsupported products (24 SKU variants) are excluded. The
  remaining 268 SKU variants use verified **family names**, with synthetic SKU
  codes, pack/grade variants, locations, prices, quantities and forecasts.
- Global product references are used for some industrial, AdBlue and EV families.
  This does not assert that every variant is currently sold in India or that
  products are technically interchangeable. Multiple original products can map
  to the same Castrol family; each retains a unique neutral SKU such as
  `castrol-india:CST-0001`.
- Distributor and depot identities are synthetic labels, not a claim about
  Castrol's actual distribution network.
- Original source-run and opaque model/evidence fingerprints remain provenance
  for reused synthetic model outputs. The conversion report separately records
  the demo adaptation. No new model training, source acceptance or official
  Castrol business results are claimed.
- Affected pricing is recalculated with the existing recommender after excluding
  self-competitor bounds. No replacement competitor is invented. Forecast and
  inventory aggregates are recomputed for retained products. Promotion estimates
  involving excluded products are removed instead of relabelled as recalculated.
- Physical warehouse capacity and its node-level blocked-stock snapshot remain
  source assumptions; they have no SKU decomposition.
- Inventory policy replay benefit tiles are deliberately unavailable. The eight
  original market/cohort replay rows covered the full source catalog and cannot
  be filtered by SKU. `postcheck.py` removes those derivative projections instead
  of presenting them as benefits for the smaller Castrol catalog. No new policy
  replay was run; the original evidence remains in the source artifacts and backup.
- Sanitized artifact paths in served metadata are display/provenance references,
  not newly generated files. The conversion does not rename or reproduce the
  raw/model artifacts they describe. Use the original input paths below or the
  backup manifest to locate actual source files.

Visible labels and identifiers do not contain Gulf identities or the word
"demo". The market is `Castrol India`, the online channel is `Castrol Online`,
and distributors use plain city labels. Categories use their friendly business
names. The two source-specific blending plants appear as `Chennai Distribution
Hub` and `Western Distribution Hub`. Existing provenance labels remain
`Synthetic`; removing temporary wording does not change the data's meaning.

`clean_labels.py` applies the same cleanup to linked database identifiers and
copied runtime metadata. The launcher supplies the matching `retailer-castrol`
and `tenant-castrol` audience. No UI overlay or application-source edits are
needed. Internal directory, container and schema names can retain `demo`, and
internal conversion reports retain original source identities for traceability.
The presentation policy applies to served API data and visible UI content.

## Restore an existing snapshot on another machine

Use [README-WINDOWS.md](README-WINDOWS.md) to restore the already converted
Castrol snapshot into one normal PostgreSQL database on port 5432. A second
persistent database is not required on the destination. Restore the database and
its matching runtime files together; do not run `prepare`, conversion, datagen,
training or activation after a snapshot restore. The existing `tools/dev.py serve`
launcher accepts the Castrol retailer/tenant settings without application changes.

The standalone verifier accepts `--postgres-dsn` for a local restored database.
It still requires the Castrol conversion marker and validates the served API
against that database. This option does not loosen the conversion script's fixed
isolated-database guard. The default verifier target remains port 55432.

Portable backups and optional source-run archives can be used after local disk
cleanup. The local original volume and rebuild inputs described below are only
available while retained; once removed, restore them from the external backup
instead of following the immediate local switch-back commands.

## Prepare a fresh conversion (once)

Use the repository's existing ML environment, Docker, Go and installed UI npm
dependencies. Run commands from the repository root. Preparation also needs the
retained original backtest Parquet and curated DuckDB, opened read-only by
`refresh.py`; the portable serving backup alone does not contain those files.
Keep these two files at their original relative paths:

- `ml/data/artifacts/backtest_gulf-rust-perf1/forecast_eval_predictions.parquet`
- `ingestion/data/curated/run-73ba460b02d63c40/retail_v2.duckdb`

Both inputs, the original runtime metadata and the existing ML/DB environments
were confirmed present on this machine after the earlier local backup cleanup.
Do not delete these source inputs while retaining the ability to rebuild the demo.

macOS/Linux:

```sh
ml/.venv/bin/python demos/castrol/manage.py prepare --backup /Volumes/ExpM2/retail-intelligence/run-73ba460b02d63c40/gulf-rust-perf1-20260924-182307-IST
```

Windows equivalent (adjust the backup drive):

```powershell
ml\.venv\Scripts\python.exe demos\castrol\manage.py prepare --backup D:\retail-intelligence\run-73ba460b02d63c40\gulf-rust-perf1-20260924-182307-IST
```

For another Windows machine, first follow the backup's `README-WINDOWS.md`
prerequisites and dependency setup: Python 3.12 or 3.13, Go 1.25+, Node.js 22.12+
and Docker Desktop with Linux containers. `py -3.12 tools\dev.py envs` creates
the ML and DB environments; `go mod download` in `api` and `npm ci` in `ui`
install their dependencies. Copy this current `demos/castrol/` recipe and the two
source inputs above into the checkout, preserving their relative paths. The old
backup's Git bundle predates this recipe. Its database dump and runtime metadata
can serve the original baseline alone, but cannot rebuild the Castrol aggregates
without those additional source inputs. Windows execution has not been tested.

Preparation verifies the dump checksum and restores only into the isolated demo
container. Re-running `prepare` on an already converted database leaves it alone.
Changing the mapping requires discarding/rebuilding the disposable instance.

The conversion is one transaction. It temporarily suspends triggers only in this
offline clone while rewriting linked identifiers, then explicitly audits foreign
keys and identities before commit. Constraints, indexes and original source
files are retained. Failed conversion transactions roll back.

## Start and verify

```sh
ml/.venv/bin/python demos/castrol/manage.py serve
```

On Windows use `ml\.venv\Scripts\python.exe demos\castrol\manage.py serve`.

UI: http://127.0.0.1:5173

API: http://127.0.0.1:8080

Keep that terminal open. The launcher supplies the demo DSN and copied metadata
only to its child processes; it does not edit `.env` or the original runtime.
It refuses occupied API/UI ports to avoid serving the wrong database.
It waits for a healthy database, then requires a healthy API, the Castrol market
and the Castrol adaptation marker before launching the UI. All four copied runtime
files must exist in `.serve-runtime/castrol-demo/runtime/`: `gate-a.json`,
`gate-b.json`, `publication-manifest.json` and `pricing-serving.json`.

In another terminal:

```sh
db/.venv/bin/python demos/castrol/verify.py
```

Windows: `db\.venv\Scripts\python.exe demos\castrol\verify.py`.

Verification binds the served API to the isolated database and checks the 268-SKU
catalog, API populations, Gulf identities and "demo" wording, excluded
competitors, filters, details, pricing and all five forecast scenario presets,
forecast export and inventory authority. Reports are under
`.serve-runtime/castrol-demo/validation/`.
`conversion.json` records exclusions, refreshed aggregates and database checks.

The original pricing CSV export SQL error is an acknowledged baseline defect.
The verifier reports it separately from conversion failures. Other original UI
limitations include the governance percentage placeholders, disabled unrelated
promotion category choices, unavailable authentication and disabled workflows.
Scoped competitor match IDs are made unique in the demo data, addressing the
baseline duplicate-row-key issue without changing the UI.

## Stop and return to the original Gulf setup

First press **Ctrl+C** in the Castrol serving terminal, which stops both child
process groups. Then stop only its database:

```sh
ml/.venv/bin/python demos/castrol/manage.py stop
```

To run the original setup again:

```sh
docker compose -f deploy/compose.yaml up -d postgres
docker compose -f deploy/compose.yaml exec -T postgres pg_isready -U retail -d retail_intelligence
ml/.venv/bin/python tools/dev.py serve --with-ui --run-id run-73ba460b02d63c40 --pricing-serving-config ml/data/artifacts/pricing_authority_gulf-rust-perf1/pricing-serving.json
```

Continue to `serve` only once `pg_isready` reports accepting connections. On
Windows, use `ml\.venv\Scripts\python.exe` in place of `ml/.venv/bin/python`.
MLflow is not required to serve this existing database baseline.

Use a normal terminal without a manually exported Castrol DSN. `manage.py serve`
does not export that variable into the parent shell. No reverse conversion or
backup restoration is required because the original volume was preserved.

The original launcher reads the active forecast authority using `ml/.venv`,
requires a matching publication fingerprint, and loads the original Gate A/B
reports plus pricing startup configuration. These files are currently intact:

- `ingestion/data/evidence/run-73ba460b02d63c40/gate-a.json`
- `ingestion/data/evidence/run-73ba460b02d63c40/gate-b.json`
- `ingestion/data/curated/run-73ba460b02d63c40/publication-manifest.json`
- `ml/data/artifacts/pricing_authority_gulf-rust-perf1/pricing-serving.json`

If a later cleanup removes that metadata, restore just the runtime files before
the original `serve` command; restoring the preserved original database is
unnecessary. On macOS/Linux, from the repository root:

```sh
backup_dir=/Volumes/ExpM2/retail-intelligence/run-73ba460b02d63c40/gulf-rust-perf1-20260924-182307-IST
mkdir -p ingestion/data/evidence/run-73ba460b02d63c40 ingestion/data/curated/run-73ba460b02d63c40 ml/data/artifacts/pricing_authority_gulf-rust-perf1
cp "$backup_dir/runtime/evidence/"*.json ingestion/data/evidence/run-73ba460b02d63c40/
cp "$backup_dir/runtime/curated/publication-manifest.json" ingestion/data/curated/run-73ba460b02d63c40/publication-manifest.json
cp "$backup_dir/runtime/pricing/pricing-serving.json" ml/data/artifacts/pricing_authority_gulf-rust-perf1/pricing-serving.json
```

For Windows, use the exact PowerShell file-copy commands in the backup's
`README-WINDOWS.md`, section **3. Copy runtime files**. Use this backup's pricing
configuration; the similarly named checked-in configuration targets a different
activation.

## Discard the demo

After stopping the serving terminal:

```sh
ml/.venv/bin/python demos/castrol/manage.py discard --confirm-discard
```

This removes only the Castrol container/volume and its generated runtime files.
The original database, original data/model artifacts, external backup and this
small recipe directory remain. Removing `demos/castrol/` afterward removes the
recipe itself.
