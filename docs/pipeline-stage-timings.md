# Pipeline stage timings — full from-scratch run

Measured on one host, one run, from an empty state: no generated source, no landed snapshot, no
curated database, no ML artifacts, and the `retail_serving` schema dropped. Recorded so the cost of
a rebuild is a known quantity before someone commits to one, and so a stage that suddenly costs
twice what it used to is visible rather than merely irritating.

**Host.** macOS (Darwin 25.5.0), Apple silicon, execution profile `performance`. PostgreSQL and
MLflow in Docker Desktop on the same machine. Numbers from a different profile or a machine with
fewer cores are not comparable — `execution/` scales pool sizes to the host, which is the point of
it, and `safe` deliberately trades wall-clock for headroom.

**What "from scratch" means here.** The wipe covers generated and derived data only, never code or
committed contracts:

| Removed | Kept |
| --- | --- |
| `datagen/output/<scenario>/run-*` | `contracts/evidence/*.json` (rewritten in place) |
| `ingestion/data/{raw,curated,evidence,work}` | `contracts/ml/expected-pin.json` (re-established) |
| `ml/data/{artifacts,features}` | MLflow's tables in the `public` schema |
| `ml/reports/<label>-characterization.*` | MLflow's `public.alembic_version` ledger |
| `retail_serving` schema | earlier labels' reports, kept as history |
| `public.retail_intelligence_alembic_version` | |

Two rows above are easy to get wrong, and both were.

**`ml/reports` is not under `ml/data`.** An earlier version of this table omitted it, so a full
single-command run re-landed 15 GB, re-ingested, re-pinned and rebuilt features before dying at
`characterize` on a stale report from the previous run. The pipeline now preflights every immutable
output in the slice and names all of them before writing anything, which turns four wasted minutes
into one second — but the wipe still has to cover this path.

**There are two Alembic ledgers in one database, and only one of them is ours.**
`public.alembic_version` belongs to **MLflow**; ours is `public.retail_intelligence_alembic_version`
(the name is set by `VERSION_TABLE` in `db/migrations/env.py`). Searching for a table named
`alembic_version` finds MLflow's and not ours, so dropping "the alembic ledger" by that name destroys
the experiment tracking history and leaves our chain at head. Drop ours by its full name, and verify
afterwards that `public.runs` still has rows.

MLflow is excluded deliberately: the forecast stage logs to it, and dropping its schema mid-rebuild
costs the run for no pipeline benefit. Clearing experiment history is a separate, safe operation.

## Timings

<!-- Populated from the run; each figure is wall-clock for that stage alone. -->

| # | Stage | Command | Wall clock | Notes |
| --- | --- | --- | --- | --- |
| 0 | Wipe + migrate | `db-upgrade` on an empty schema | <1s | 34 tables to head `0019_supplier_identity` |
| 1 | Generate source | `dev.py datagen --regenerate` | 79 min 44 s | ten-year, two markets; `run-adac9e85dccb56e8` |
| 2 | Land snapshot | `dev.py land` | 10 s | 9,938 objects; no copy of the 15 GB payload |
| 3 | Gate A | `dev.py gate-a` | 7 s | A01–A13 over 146 declared datasets |
| 4 | Stage | `dev.py stage` | 2 min 48 s | the dominant cost of the ingest slice |
| 5 | Transform | `dev.py transform` | 41 s | builds the candidate DuckDB |
| 6 | Gate B | `dev.py gate-b` | 4 s | B01–B21 |
| 7 | Publish + finalize | `dev.py publish`, `finalize` | 8 s + <1 s | promotes curated, retains evidence |
| 8 | Re-pin (decision #89) | `pipeline` stage `repin` | 1 s | selections + pin; stops only if no chain names the run |
| 9 | Features | `pipeline` stage `features` | 8 s | 1,072,430 weekly rows; a single DuckDB aggregate |
| 10 | Characterize | `characterize` | 1 s | descriptive only |
| 11 | Backtest | `backtest` | **40 min 10 s** | the long pole: 26 horizons × 13 origins, 65,021,190 training rows, 708,708 forecast rows, `accepted: true` |
| 12 | Score current | `score-current` | 3 min 16 s | 52,884 rows over 2,034 series at origin 2026-07-27 |
| 13 | Classify | `classify` | 1 s | |
| 14 | Forecast publish | `publish` | 3 min 49 s | mints `fr_…` / `fv_…` |
| 15 | Forecast materialize | `materialize` | 2 min 3 s | projects into `retail_serving` |
| 16 | Forecast activate | `activate` | 3 s | |
| 17 | Inventory build | `inventory-build` | 8 s | 17 artifacts; oracle 0.094 / 0.305 against a frozen 0.5 |
| 18 | Inventory verify | `inventory-verify` | 2 s | independent re-derivation |
| 19 | Inventory materialize | `inventory-materialize` | 1 s | includes the per-table `ANALYZE` |
| 20 | Inventory activate | `inventory-activate` | 1 s | |
| | **Pipeline total (stages 2–20, one command)** | | **53 min 36 s** | `exit=0`, zero error lines |
| 21 | Evidence records | `closure-record`, `inventory-entry-record` | 2 s | governed step, outside the chain |
| 22 | Test suites | `contracts`, `test`, `api-test`, `ui-test`, `db-test` | ~4 min | 202 + 187 + 335 + 77 + 12 passed |
| | **Total including datagen** | | **~2 h 20 min** | 79 min 44 s of that is datagen |

Stage 2's 10 s is a cold land. The single-command run measured under a second there because a prior
probe had already landed that snapshot and `land` correctly detected the idempotent replay — worth
knowing before reading a fast land as a fast pipeline.

## Disk

| Stage | Footprint |
| --- | --- |
| Generated source, one run | 16 GB promoted (~54 GB staging peak) |
| Landed snapshot | 15 GB |
| Work (staging + candidate DuckDB) | 6.5 GB, prunable after `finalize --prune-work` |
| Curated DuckDB + Parquet | 2.1 GB |
| Retained evidence, one run | 448 KB |
| ML features | 160 MB |
| ML artifacts | 352 MB |
| **Repository after a complete run** | **42 GB** |

42 GB is the honest steady state, and most of it is prunable: `ingestion/data/raw` (15 GB) is the
landed snapshot, `ingestion/data/work` (6.5 GB) is staging plus the candidate DuckDB that
`finalize --prune-work` exists to remove, and `datagen/output` holds 15 GB per generated run. Two
generated runs plus one un-pruned rebuild is how this repository reaches 39 GB and looks broken.
Check `datagen/output` first — it is easy to miss because it is not named `data`.

Two runs of the ten-year demo are ~30 GB, which is why `datagen/output` is the first thing to check
when the repository looks larger than it should. It is easy to miss because it is not named `data`.

## Things worth knowing before starting

- **The pin gates everything below ML.** Any change under the ML layer — a generator bump *or* an
  ingestion transform alone — moves the publication fingerprint and the curated DuckDB hash, so the
  ML stages fail closed until the pin is re-established. The `repin` stage does it in place, between
  `finalize` and `features`; running the ML stages before the pin moves costs a full features and
  backtest pass for nothing.
- **The pin cannot move before the selection ledger does.** `build_expected_pin.py` refuses while the
  active selection for a capability names a different snapshot — *"the active
  demand_forecast_non_pit selection names snapshot 0634b079… but this pin would name cd20ca5a…"*. The
  ledger is the authority on which publication is the active source; the pin follows it, never the
  other way round. That is why the `repin` stage writes selections first.
- **What each fingerprint actually covers, because guessing it wrong is easy.**

  | Fingerprint | Covers | Does NOT cover |
  | --- | --- | --- |
  | Gate A | rule outcomes, dataset inventory, snapshot id | row-level controls |
  | Gate B | `rules`, `capabilityMask`, `reconciliation`, `status` | `entityCounts`, `entityControls` |
  | Candidate (transform manifest) | `entityCounts`, `entityControls` (row count + row-hash XOR/SUM per entity) | `databaseSha256`, timings |
  | Publication | the candidate's controls, recomputed on the published DB | `/objects`, `/duckdb`, `/publishedAt` |

  So **Gate B agreeing is not proof that the data reproduced.** It proves the same gate verdicts and
  the same money reconciliation. Row-level equality lives in the candidate and publication
  `entityControls`, and those are the only place to look for it.

- **`publish` is semantically deterministic; its artifacts are not.** Publishing twice from one fixed
  candidate produced the identical `semanticFingerprint` (`894db90b…`) and different physical output
  every time — Parquet object counts of 1663, 1626, 1509 and 1533 across four publishes of the same
  data, and a different curated DuckDB sha256 each time at identical byte length. `/objects` and
  `/duckdb` are excluded from the fingerprint precisely for this reason, so **object count is noise
  and must never be read as a data difference.**

- **A wall clock used to reach the publication fingerprint, and that is fixed.** Two full runs of the
  same landed snapshot once produced publication fingerprints `f5c6ec3f…` and `894db90b…` with no
  change to any code the transform reads. Bisecting it by layer:

  | Layer | Measured |
  | --- | --- |
  | `land` | same source → same snapshot id; content addressed, correct |
  | `stage` | **the leak.** `landingTime` — a wall clock — sat inside the fingerprinted payload |
  | `transform` | deterministic: two runs from one staging DB gave identical `entityControls` |
  | `publish` | deterministic: two runs from one candidate gave one fingerprint |

  Each layer correctly excluded its *own* volatile fields and correctly inherited the layer above, so
  no single layer looked wrong: staging's fingerprint flows into the transform manifest's
  `stagingSemanticFingerprint`, into the candidate's identity, into the publication's. A clock at the
  top therefore meant the pin moved on rebuilds that changed nothing, and no publication selection
  record could ever be re-derived — the fingerprint it named had already stopped existing.

  `/landingTime` is now in `STAGING_VOLATILE_POINTERS`, so the instant is still recorded as
  provenance but no longer claims to describe what the staging database contains — the same treatment
  `/completedAt` always had. `ingestion/tests/test_staging_fingerprint_determinism.py` asserts both
  directions: that the clock cannot move the fingerprint, and that content still can, so the volatile
  set cannot quietly grow until the fingerprint means nothing.

- **A selection record cannot survive a re-publish of the artifact it names,** whatever the cause. Its
  fingerprints stop existing. `build_publication_selection.py --no-clobber` refuses to restate such a
  record and asks for a new generation, because choosing a different artifact is a governed act.
  Without that flag the writer silently re-aligned committed records to the newest publication and
  `--check` then passed against its own output — a check that cannot fail. The pipeline's `repin`
  stage passes `--no-clobber` for exactly this reason.
- **`repin` is idempotent, and it fails before it writes.** Re-running it against an already-governed
  run reproduces `expected-pin.json` byte for byte. Against a published run with no selection chain it
  stops at the verify step — *"published runs with retained evidence and no selection record: run-…"* —
  and because verification precedes the pin write, a bad state leaves the pin untouched rather than
  half-moved. Both behaviours are exercised rather than assumed; the second was checked by staging a
  publication manifest for a run no chain names.
- **A new canonical entity must be declared in three places or it publishes unvalidated.** The
  transform's own return tuple (which is the candidate's declared control set), `retail_v2/schema.yaml`
  and `retail_v2/tiers.yaml`. Gate B validates only `present & set(schema["entities"])`, so an
  undeclared table gets no nullability and no key check — and the publisher refuses the candidate
  outright for containing an entity it never declared. `suppliers` was caught by exactly that refusal.
- **Immutability guards are per stage.** `publish`, `characterize` and the inventory publisher each
  refuse to overwrite prior artifacts, so a re-run needs the previous bundle cleared first.
- **Activation is separate from materialization,** and refuses a second active version for one
  scope. Pass `--retire-other-scopes` when an earlier version is still active.
- **`tools/dev.py contracts` fails between the wipe and the new publish, and that is correct.**
  The publication selection records under `contracts/` are validated against the run evidence they
  derive from, so once `ingestion/data/evidence/<run>/publication-manifest.json` is gone the check
  raises `FileNotFoundError` on it. It passes again once the new run has published and its selection
  record is derived. Do not "fix" it by restoring the old evidence — that would pin the contracts to
  a run that no longer exists.
- **`tools/dev.py test` fails on the closure-record head check between a migration bump and the
  next closure-record regeneration, and that is also correct.**
  `test_the_generated_closure_record_names_the_required_head` compares the committed record against
  the Alembic graph, and regenerating the record needs a forecast bundle
  (`--forecast-run <bundle>`). During a rebuild that bundle does not exist yet, so the check stays
  red until stage 17. Do not edit the record by hand to silence it — the generator derives the head
  and the test exists to catch exactly that edit.
- **Backtest is ~40 minutes and that is normal.** Ten runs of this stage recorded in MLflow fall
  between 37.6 and 40.9 minutes; this one took 39 min 55 s. It writes nothing until it finishes, so
  an empty `ml/data/artifacts` partway through is expected rather than a sign of a stall. To tell a
  working backtest from a hung one, check CPU (it sits near 1000% on this host) or query MLflow for
  the `RUNNING` run rather than watching the filesystem.
- **A ten-second `features` stage is not a skipped one.** It builds 1,072,430 weekly rows with one
  DuckDB aggregate. The 65 million rows backtest reports are its own origin×horizon training
  expansion, not the feature table. If you need to confirm which publication a feature set came
  from, `ml/data/features/<label>/manifest.json` embeds `sourceInput` — the snapshot id, both gate
  fingerprints and the publication fingerprint — which is what binds a forecast to its lineage.
- **Staging is larger than the promoted run.** The in-flight
  `.run-<id>.staging-*` directory reached ~50 GB while the promoted run it becomes is ~15 GB;
  intermediates are compacted on promotion. Size the disk for the staging figure, not the final one.
- **Regenerate the two evidence records last.** `tools/dev.py verify` compares them against the
  Alembic graph and fails when they name a head that has moved.
