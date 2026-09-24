# Restore Castrol on Windows using one PostgreSQL database

Use the complete Castrol snapshot package on the external drive. The package's
`backup-manifest.json` records its exact Git commit, branch, capture time, run ID
and database counts. The source run is `run-73ba460b02d63c40`.

Restore the converted snapshot directly. Do not run `manage.py prepare`, datagen,
ingestion, training, migrations, repinning or activation afterward. This is a
serving backup: PostgreSQL plus matching runtime metadata and committed source.
An optional `archive/` preserves local source-run files for later rebuilding;
it is not required to serve the snapshot. Machine-specific environments, build
caches and node_modules are recreated instead of copied across operating systems.

## 1. Prerequisites and integrity

Install Git, Python 3.12, Go 1.25+, Node.js 22.12+ and Docker Desktop with Linux
containers. Dependencies require internet access or an existing local cache.
Use one PostgreSQL 17.10 instance, one volume and database `retail_intelligence`.
The default port is 5432. MLflow is not required.

Adjust the external drive and repository paths. Use the new timestamped Castrol
folder, not the original Gulf package.

```powershell
$Package = 'D:\retail-intelligence\run-73ba460b02d63c40\castrol-YYYYMMDD-HHMMSS-IST'
$Repo = 'C:\retail-intelligence'
$RunId = 'run-73ba460b02d63c40'
$Manifest = Get-Content "$Package\backup-manifest.json" -Raw | ConvertFrom-Json

Get-Content "$Package\SHA256SUMS.txt" | ForEach-Object {
    $parts = $_ -split '  ', 2
    $file = Join-Path $Package $parts[1]
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $file).Hash.ToLowerInvariant() -ne $parts[0]) {
        throw "Checksum mismatch: $file"
    }
}
```

## 2. Exact source and serving dependencies

Use a fresh repository directory. The bundle contains the committed Castrol
recipe and this document; no uncommitted overlay is required.

```powershell
git clone --branch $Manifest.gitBranch "$Package\source\retail-intelligence.bundle" $Repo
if ($LASTEXITCODE -ne 0) { throw 'Git clone failed' }
Set-Location $Repo
git checkout $Manifest.gitCommit
if ($LASTEXITCODE -ne 0) { throw 'Exact commit checkout failed' }
git remote set-url origin https://github.com/nilshah80/retail-intelligence.git

py -3.12 -m venv ml\.venv
if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed' }
ml\.venv\Scripts\python.exe -m pip install 'psycopg[binary]==3.3.4'
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed' }
Push-Location api
go mod download
if ($LASTEXITCODE -ne 0) { throw 'Go dependency installation failed' }
Pop-Location
Push-Location ui
npm ci
if ($LASTEXITCODE -ne 0) { throw 'UI dependency installation failed' }
Pop-Location
```

The existing generic launcher expects `ml/.venv` for its database lookup. This
small environment is sufficient to serve and verify a restored snapshot; it is
not a full training environment. No model package is imported by that lookup.

## 3. Restore or replace the single application database

Stop the destination API/UI first, and stop MLflow if it is using this database.
If the destination database contains changes you want to keep, take a separate
backup first. The following reset deliberately replaces **all contents of this
application database**, including a previously restored Gulf or Castrol version.
It keeps the PostgreSQL container, volume and database name. Do not run these
commands against another application's database.

These commands use the default local credentials from `deploy/compose.yaml`.
Adjust the user, password and port consistently if `deploy/.env` overrides them.
Do not start the isolated `demos/castrol/compose.yaml` on this destination.

```powershell
Set-Location $Repo
docker compose -f deploy\compose.yaml up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed' }

docker compose -f deploy\compose.yaml cp "$Package\database\castrol.dump" postgres:/tmp/castrol.dump
if ($LASTEXITCODE -ne 0) { throw 'Dump copy failed' }
docker compose -f deploy\compose.yaml exec -T postgres dropdb -U retail --if-exists --force retail_intelligence
if ($LASTEXITCODE -ne 0) { throw 'Database reset failed' }
docker compose -f deploy\compose.yaml exec -T postgres createdb -U retail -O retail retail_intelligence
if ($LASTEXITCODE -ne 0) { throw 'Database creation failed' }
docker compose -f deploy\compose.yaml exec -T postgres pg_restore -U retail -d retail_intelligence --no-owner --no-acl --exit-on-error /tmp/castrol.dump
if ($LASTEXITCODE -ne 0) { throw 'Database restore failed; do not start the application' }
docker compose -f deploy\compose.yaml exec -T postgres psql -X -U retail -d retail_intelligence -v ON_ERROR_STOP=1 -c 'ANALYZE;'
if ($LASTEXITCODE -ne 0) { throw 'Database analyze failed' }
docker compose -f deploy\compose.yaml exec -T postgres rm /tmp/castrol.dump
```

A logical dump contains live rows, not unused table/index pages or PostgreSQL
transaction log files. A fresh restore therefore compacts the database without
changing its data. The database name must remain `retail_intelligence`, which
is checked by the copied pricing startup configuration.

## 4. Matching runtime metadata

```powershell
New-Item -ItemType Directory -Force "$Repo\ingestion\data\evidence\$RunId" | Out-Null
New-Item -ItemType Directory -Force "$Repo\ingestion\data\curated\$RunId" | Out-Null
New-Item -ItemType Directory -Force "$Repo\.serve-runtime\restored" | Out-Null
Copy-Item "$Package\runtime\evidence\gate-a.json" "$Repo\ingestion\data\evidence\$RunId\gate-a.json" -Force
Copy-Item "$Package\runtime\evidence\gate-b.json" "$Repo\ingestion\data\evidence\$RunId\gate-b.json" -Force
Copy-Item "$Package\runtime\curated\publication-manifest.json" "$Repo\ingestion\data\curated\$RunId\publication-manifest.json" -Force
Copy-Item "$Package\runtime\pricing\pricing-serving.json" "$Repo\.serve-runtime\restored\pricing-serving.json" -Force
```

Keep these files intact and paired with their database snapshot. Restoring only
the database is insufficient: the evidence and pricing identity also matter.

## 5. Start the unchanged API and UI

```powershell
$env:RETAIL_POSTGRES_DSN = 'postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence'
py -3.12 tools\dev.py serve `
  --with-ui `
  --run-id run-73ba460b02d63c40 `
  --pricing-serving-config .serve-runtime\restored\pricing-serving.json `
  --scenario-retailer retailer-castrol `
  --scenario-tenant tenant-castrol `
  --scenario-environment local
```

Keep this terminal open. UI: http://127.0.0.1:5173 .
API health: http://127.0.0.1:8080/healthz .

`demos/castrol/manage.py serve` is intentionally bound to the original isolated
conversion container on port 55432. Use the generic launcher above on this
single-database destination.

## 6. Verify

Open another PowerShell terminal in the repository:

```powershell
Set-Location $Repo
$env:RETAIL_POSTGRES_DSN = 'postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence'
ml\.venv\Scripts\python.exe demos\castrol\verify.py `
  --postgres-dsn $env:RETAIL_POSTGRES_DSN `
  --output .serve-runtime\restored\validation
if ($LASTEXITCODE -ne 0) { throw 'Castrol verification failed; inspect api-verification.json' }
```

In a newly opened terminal, assign `$Repo` again if needed. Expect 268 Castrol
SKU variants, no Gulf identities or the word "demo" in served content, and no
Castrol/Gulf competitors. Check the pricing, competitor, forecast, inventory,
replenishment, executive and data-management screens in the browser.

The verifier checks database/API identity, read routes, pagination, simulations,
forecast presets/export and inventory authority. It requires the Castrol audit
marker even when a different local database port is specified. It does not
convert or modify database rows.

The known pre-existing pricing CSV export SQL defect is separately classified
and does not count as a new restore failure. Source verification was 164/165
checks with that one known issue; see the package validation reports for the
fresh restore results. Inventory replay benefit tiles remain unavailable for
the reduced catalog, and other previously documented application limitations
are unchanged. A macOS restore test does not constitute an actual Windows test.

## 7. Stop or return to Gulf

Press Ctrl+C in the serving terminal. To stop PostgreSQL without deleting it:

```powershell
docker compose -f deploy\compose.yaml stop postgres
```

To return to Gulf, use the original timestamped Gulf package on the same drive:

1. Stop API/UI and any other database clients; preserve any later Castrol changes.
2. Verify the Gulf package checksums.
3. Reset this same application database using the reset steps above.
4. Restore the Gulf dump instead of `castrol.dump`, then run `ANALYZE`.
5. Copy the Gulf Gate A/B and publication manifest to the same run paths. Copy
   its pricing-serving.json to `.serve-runtime/restored/pricing-serving.json`.
6. Start `tools/dev.py serve` with the same DSN/run/pricing path but use
   `--scenario-retailer retailer-demo --scenario-tenant tenant-demo
   --scenario-environment local`, matching the original Gulf snapshot.

The original Gulf package has its own `README-WINDOWS.md` and exact source
revision if you want a separate checkout matching that snapshot. Both snapshots
use the same unchanged application code at the time of the Castrol adaptation.
No reverse conversion or second persistent database is required.

## Optional source-run archive

If `archive/source-run-files.tar.zst` is present, it preserves the generated
source, ingestion data and ML artifacts that were removed locally after backup.
It may also contain earlier feature variants from this project's local ML data;
consult `archive/source-files.json` for the exact inventory. These files retain
original Gulf provenance and are not served by the Castrol application.

Do not extract that archive for normal serving: it contains the original runtime
files and could overwrite the restored Castrol metadata. For rebuilding, extract
it into a separate source checkout using Zstandard and tar (for example, first
`zstd -d source-run-files.tar.zst -o source-run-files.tar`, then
`tar -xf source-run-files.tar -C C:\source-checkout`), recreate full project dependencies and use
the recipe's original-input instructions. The portable serving package alone
is sufficient for the destination presentation.
