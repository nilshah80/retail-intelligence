# `ml/` — Python ML pipeline

**Purpose:** the batch pipeline that turns ingested data into forecasts, recommendations, and
inventory decisions: `ingest → quality → features → models → engines → artifacts`.

**Language:** Python (LightGBM, statsmodels, pandas / DuckDB).

**Planned contents** (copied/adapted from the M5 PoC — `[REUSE]`):
- `data/` — `mapped_files` ingest adapter, quality checks (fail-closed), warehouse.
- `features/` — weekly point-in-time feature build (lags, rolling, seasonality, price/promo, calendar).
- `models/` — `forecasting` (LightGBM horizon-quantile P50/P90 + Croston routing), `price_response`
  (Poisson GLM + empirical-Bayes elasticity), `baselines`, `backtest`.
- `engines/` — reorder / safety-stock, pricing, policy, simulator, allocation, ageing/expiry.

**Output boundary:** writes artifacts (Parquet/JSON) + manifests + **semantic fingerprints** to
the lake + PostgreSQL. The Go `api/` reads these — it never calls Python in-process.

**Spec:** §3 (models), §4 (guardrails), §11 (schema). *Note: data generation is NOT here — it
lives in `datagen/`.*

_No code yet — information only._
