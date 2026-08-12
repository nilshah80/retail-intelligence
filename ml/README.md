# `ml/` — Python ML pipeline

**Purpose:** consume capability-complete curated `retail_v2` data and produce forecasts,
recommendations and inventory decisions:
`curated → features → models → engines → artifacts`.

**Language:** Python (LightGBM, statsmodels, pandas / DuckDB).

**Implemented contents** (copied/adapted and extended from the M5 PoC):
- `features/` — weekly point-in-time feature build (lags, rolling, seasonality, price/promo,
  market-local calendar and external drivers). Cross-market forecast features use
  dimensionless/local-normalized price signals rather than incomparable raw currency levels.
- `models/` — `forecasting` (LightGBM horizon-quantile P50/P90 + Croston routing), `price_response`
  (Poisson GLM + empirical-Bayes elasticity), `baselines`, `backtest`.
- `engines/` — reorder / safety-stock, pricing, policy, simulator, allocation, ageing/expiry.

The pricing implementation lives in `retail_ml.pricing`: point-in-time panels, response fitting and
strict acceptance, market-local recommendations and simulation, competitor matching, promotion
protection/refusal, immutable bundle publication, outside-set verification, PostgreSQL
materialization, prospective result-selection intent, and atomic activation preparation.
Expected record-level data defects are retained as reason-coded withheld/exception rows so an
unrelated series continues. Missing schemas, ambiguous authority, lineage mismatch, leakage,
artifact corruption, or an invalid policy remain run-level failures and abort publication.

**Market and money rule:** unit forecasting/reorder math may share code across markets, but
calendars, evaluation slices, price-response pools, pricing policies and monetary outputs are
market-scoped. Calendar, weather, event, macro, promotion and competitor features join through
`market_id` plus resolved `geo_scope_*` or the structured multi-axis promotion rows; free-form
region names never join across markets. Pricing
uses the location operating currency and never presentment currency. Pricing and margin never
mix currencies; cross-market inventory/value reporting requires the governed local/base→
reporting/quote conversion. The initial pricing round-trip is revenue-objective only until
accepted temporal cost-as-of unlocks margin.

**Evidence demos:** every market declared by the evaluated tenant must independently produce at
least 25 actually gated SKU×store price series per enabled department for the response-rich
audience. A separate non-active diagnostic preset must fail closed with `insufficient_evidence`.
ML owns that pass/fail decision; it must not infer coverage from store count, configured SKU count
or a generator preset name.

**Input rule:** only an `ingestion/` publication with full Gate-B pass and the capability mask
required by a model may enter `ml/`. A partial Shopify slice never reaches this package.
Feature/model/engine code cannot inspect or branch on retailer, source platform, source adapter
or datagen scenario.

**Output boundary:** reads curated data and writes immutable feature/model/decision artifacts
(Parquet/JSON) plus manifests and **semantic fingerprints**. After acceptance, a separate offline
Python materializer verifies the current input pin and all ten forecast artifacts, then projects
the serving subset transactionally into PostgreSQL. The Go `api/` reads only that active SQL
projection; it never calls Python in-process or scans forecast Parquet.

**Execution boundary:** ML installs the same neutral `execution/` resolver as datagen and
ingestion, then maps only the `ml` namespace into feature, fold, market/model and trainer thread
pools. Pools are budgeted to prevent nested oversubscription and bounded batching fails closed on
memory risk; it never shortens horizons or validation folds silently. Execution values and stage
telemetry are recorded in the artifact/run manifest but excluded from feature/model/policy
fingerprints. Fixed RNG/deterministic trainer settings must make safe/ultra-performance outcomes
equivalent within declared library tolerances.

**Portability gate:** Windows, macOS and Linux are required ML targets. Feature construction, a
small deterministic train/backtest, serialization and artifact publication must run on all three
using supported pinned wheels. Worker startup cannot rely on `fork`; paths use `pathlib`;
temporary/cache locations use platform APIs; native libraries and thread pools are bounded by the
execution profile. Keys, features and acceptance decisions must match across OSes, while any
allowed model floating-point tolerance is explicit and tested rather than assumed.
Evidence is produced with developer-run commands on supported hosts. Repository CI workflows are
prohibited by `contracts/validation-policy.yaml` and are not a present or future completion gate.

**Inventory and replenishment artifacts.** `ARTIFACT_COLUMNS` in
`inventory_publish/run_artifacts.py` is the only place each artifact's column contract is written
down, and `ARTIFACT_GRAIN` beside it declares the key. Both are enforced at publish time, and
migration 0016 now enforces the grain at the database boundary as well — the publisher's check and a
unique index are not redundant, because the check only sees one bundle.

Sixteen artifacts are published. Twelve are current-state or forecast-derived and belong to the
`inventory_replenishment_current_snapshot` capability; `inventory_replay_metrics` alone belongs to
`inventory_replenishment_replay`, which is scoped separately because it rests on different evidence
and fails independently. A network whose weekly stock cannot be reconstructed still serves its own
observed positions, which need no replay to be true.

Four of them exist because a screen was already trying to show something the run computed and threw
away:

| Artifact | Publishes | Was previously |
| --- | --- | --- |
| `inventory_warehouse_capacity` | The storage ceiling per node | Capacity Utilization had no denominator |
| `inventory_inbound_summary` | Open and late inbound per node | Delayed Receipts counted *open* orders as late |
| `inventory_market_policy` | The market budget ceilings | The read model cannot open a policy document |
| `replenishment_recommendations.lead_time_days` | The resolved supply-term lead time | Computed for the protection period, then discarded |

**Money in an artifact carries its currency.** A value column without one is how a multi-market
total ends up adding dollars to rupees — the single most common defect found across the inventory
screens. Where a quantity may be uncosted, the units and the value are published as separate
columns so the money understates rather than inventing a price, and a `costedCells` count travels
beside every money aggregate so a reader can see the coverage it rests on.

**The pin gates every stage.** `contracts/ml/expected-pin.json` names the source snapshot, both
gates and the publication — including the curated DuckDB's hash and byte length — so any change
below this layer fails the stages closed until it is re-established. Decision #89 makes that a
governed step with equivalence evidence, not a formality. The pin is the only thing the chain
consults to find its curated root: `features` takes no source argument, so `--source-root` on it is
silently ignored.

`tools/build_expected_pin.py --run run-<id>` moves it, `--list` reports what is pinned against what
has retained evidence, and the `repin` pipeline stage runs both it and the selection ledger in the
right order, so a rebuild does not need a manual gap. What stays manual is the *decision*: the pin
refuses while the active publication selection names a different snapshot, and that selection carries
an approver and a reason. Re-pin *before* running the chain; the reverse costs a full features and
backtest pass. See the root README §8a.

**Spec:** §3 (models), §4 (guardrails), §11 (schema). Data generation lives in `datagen/`;
landing and transformation live in `ingestion/`.

**Forecast Scenario Planning v1.** The checked-in assumption YAML is a synthetic, non-activatable
test fixture. A separately approved `serving_candidate` bundle can be materialized into an
*inactive* base context (and, when compatible, its optional inventory extension) with:

```powershell
python -m retail_ml.scenario.materialize --postgres-dsn <dsn> --curated-root <curated-root> --forecast-activation-scope-fingerprint <64-hex> --assumption-bundle <approved-yaml> --retailer-id <retailer> --tenant-id <tenant> --environment <environment>
```

The command refuses a bundle without one effective approval head and never activates a context.
Approval and activation remain explicit calls in `retail_ml.scenario.postgres`, so running an
offline publisher cannot make the production button live as a side effect.

For the checked-in Gulf India PoC only, the complete local demo can be reproduced with:

```powershell
python tools/dev.py scenario-demo-activate
```

This registers the visibly labelled local-demo bundle, records the local lifecycle event,
materializes the base and compatible inventory extension, and activates them under
`retailer-demo × tenant-demo × forecast_scenario_v1 × local`. The command refuses any environment
other than `local`; it is not product/quant or production approval.

The isolated package and import-boundary test are scaffolded. Model, feature and engine
implementation begins in Phase 3 after the required curated capability mask is accepted. The
current publication enables non-PIT demand work but does not claim point-in-time training
eligibility for backfilled availability evidence.
