# Open decisions

Decisions to lock before or during the build. Status: **DECIDED**, **REC** (recommended default,
not yet confirmed), or **OPEN**. Spec refs are sections of `demand_forecast_poc_spec.md`.

## Locked

| # | Decision | Status | Value |
|---|---|---|---|
| 1 | Monorepo name | **DECIDED** | `retail-intelligence` |
| 2 | Data production vs consumption split | **DECIDED** | separate `datagen/` emits CSV/Parquet; PoC ingests |
| 3 | ML language / API language | **DECIDED** | Python ML pipelines, Go API |
| 4 | Money storage | **DECIDED** | integer minor units (paise), `minor_unit_exponent = 2`; FX display-only |
| 5 | Contract version | **DECIDED** | `retail_v2` (superset of M5 `retail_v1`) |

## Recommended (confirm)

| # | Decision | Status | Recommendation | Spec |
|---|---|---|---|---|
| 6 | Cost valuation method | **REC** | Moving Average Cost default; FIFO only where batch/expiry tracked | §10.5 |
| 7 | Who computes WAC | **REC** | generator emits `purchase_receipts` ledger; PoC computes `inventory_cost` WAC | §11.2 |
| 8 | Interactive scoring boundary | **REC** | Go computes closed-form projections from stored β/P50/P90; Python scoring service only for model-backed scoring + Copilot | Arch note |
| 9 | Migration ownership | **REC** | single owner = Alembic (Python); Go generates structs from schema | Arch note |
| 10 | Forecast horizon | **REC** | extend LightGBM horizons 8 → 26 wk (dashboard offers 13/26) | §3.1 |
| 11 | Accuracy definition | **REC** | `accuracy = 100·(1 − WAPE)`, stated in methodology | §3.8 |
| 12 | Confidence definition | **REC** | derive from P90−P50 spread relative to P50 | §2.3 |
| 13 | Driver attribution method | **REC** | SHAP on LightGBM as primary; keep transparent blend as fallback | §3.4 |

## Open

| # | Decision | Status | Notes | Spec |
|---|---|---|---|---|
| 14 | Competitor data source + SKU↔competitor match key | **OPEN** | scraped / panel / third-party; hardest new feed to source | §8.1, §11.3 |
| 15 | Weather granularity + forward-weather provider | **OPEN** | store vs region; provider with a real `known_as_of` | §11.5 |
| 16 | Fingerprint canonicalization spec | **OPEN** | must be byte-identical in Python + Go (key order, number format); needs golden vectors | Arch note |
| 17 | UI framework | **OPEN** | the `docs/` mockup is static HTML; pick the real stack | §8.4 (ui) |
| 18 | Copilot serving | **OPEN** | Go proxies to a Python copilot service vs Go calls the LLM directly; grounding from same artifacts | §8.4 |
| 19 | Customer/segment data depth | **OPEN** | segment mix only, or basket-level for cannibalisation/bundle models | §8.1, §11.4 |

## Do NOT carry over from the M5 PoC

- The M5-only `M5_POC_DEMONSTRATION_V1` pricing amendment (widened resample-IQR gate). A real
  retailer starts on the strict Plan v3 gates; any amendment must be separately justified,
  versioned, approved, and disclosed. (§4.6)
- Synthetic cost presented as real. A real margin objective requires non-synthetic,
  provenance-matched cost; generated cost = *labelled* margin scenario only. (§10.3)
