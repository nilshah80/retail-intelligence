# `ml/` — Python ML pipeline

**Purpose:** consume capability-complete curated `retail_v2` data and produce forecasts,
recommendations and inventory decisions:
`curated → features → models → engines → artifacts`.

**Language:** Python (LightGBM, statsmodels, pandas / DuckDB).

**Planned contents** (copied/adapted and extended from the M5 PoC):
- `features/` — weekly point-in-time feature build (lags, rolling, seasonality, price/promo,
  market-local calendar and external drivers). Cross-market forecast features use
  dimensionless/local-normalized price signals rather than incomparable raw currency levels.
- `models/` — `forecasting` (LightGBM horizon-quantile P50/P90 + Croston routing), `price_response`
  (Poisson GLM + empirical-Bayes elasticity), `baselines`, `backtest`.
- `engines/` — reorder / safety-stock, pricing, policy, simulator, allocation, ageing/expiry.

**Market and money rule:** unit forecasting/reorder math may share code across markets, but
calendars, evaluation slices, price-response pools, pricing policies and monetary outputs are
market-scoped. Calendar, weather, event, macro, promotion and competitor features join through
`market_id` plus resolved `geo_scope_*` or the structured multi-axis promotion rows; free-form
region names never join across markets. Pricing
uses the location operating currency and never presentment currency. Pricing and margin never
mix currencies; cross-market inventory/value reporting requires the governed local/base→
reporting/quote conversion. The initial pricing round-trip is revenue-objective only until
accepted temporal cost-as-of unlocks margin.

**Evidence demos:** the primary India+US scenario must independently produce at least 25 actually
accepted SKU×store price series per enabled department in both markets. A separate sparse preset
must fail closed with `insufficient_evidence`. ML owns that pass/fail decision; it must not infer
coverage from store count, configured SKU count or a datagen preset name.

**Input rule:** only an `ingestion/` publication with full Gate-B pass and the capability mask
required by a model may enter `ml/`. A partial Shopify slice never reaches this package.
Feature/model/engine code cannot inspect or branch on retailer, source platform, source adapter
or datagen scenario.

**Output boundary:** reads curated data and writes feature/model/decision artifacts
(Parquet/JSON) plus manifests and **semantic fingerprints** to the lake + PostgreSQL. The Go
`api/` reads these — it never calls Python in-process.

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

**Spec:** §3 (models), §4 (guardrails), §11 (schema). Data generation lives in `datagen/`;
landing and transformation live in `ingestion/`.

_No code yet — information only._
