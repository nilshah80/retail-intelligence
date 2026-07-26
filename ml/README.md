# `ml/` — Python ML pipeline

**Purpose:** the batch pipeline that turns heterogeneous source data into forecasts,
recommendations and inventory decisions:
`raw landing → source gate → profile/adapter normalization → standardized staging → shared
domain transforms → canonical gate → curated → features → models → engines → artifacts`.

**Language:** Python (LightGBM, statsmodels, pandas / DuckDB).

**Planned contents** (copied/adapted and extended from the M5 PoC):
- `data/landing/` — immutable source snapshots, manifests, hashes and idempotent replay.
- `data/adapters/` — profile-driven `mapped_files` default plus thin versioned source adapters;
  both emit the same standardized staging entities.
- `data/transforms/` — source-neutral joins, filters, order/refund semantics, time/money/unit
  conversion, fulfillment bridge, exact-money aggregation, inventory/ATP semantics,
  PIT/provenance and reconciliation from staging to canonical `retail_v2`.
- `data/quality/` — raw/source gate, coverage/capability-aware canonical `retail_v2` gate and
  reason-coded quarantine.
- `data/warehouse/` — atomically published curated Parquet + DuckDB.
- `features/` — weekly point-in-time feature build (lags, rolling, seasonality, price/promo, calendar).
- `models/` — `forecasting` (LightGBM horizon-quantile P50/P90 + Croston routing), `price_response`
  (Poisson GLM + empirical-Bayes elasticity), `baselines`, `backtest`.
- `engines/` — reorder / safety-stock, pricing, policy, simulator, allocation, ageing/expiry.

**Source-neutrality rule:** the generic-retailer fixture must reproduce the full canonical truth;
the pure Shopify fixture must reproduce its declared supported slice with `validated_partial`
only, and Shopify plus synthetic PIM/ERP/WMS/external companion feeds must reproduce the full truth
and pass full Gate B. Partial slices are never promoted or sent to models. Downstream
feature/model/engine code cannot branch on retailer or platform.

**Output boundary:** writes curated data and artifacts (Parquet/JSON) + manifests + **semantic
fingerprints** to the lake + PostgreSQL. The Go `api/` reads these — it never calls Python
in-process.

**Spec:** §3 (models), §4 (guardrails), §11 (schema). *Note: data generation is NOT here — it
lives in `datagen/`.*

_No code yet — information only._
