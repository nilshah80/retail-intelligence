# Open decisions

Decisions to lock before or during the build. Status: **DECIDED**, **REC** (recommended default,
not yet confirmed), or **OPEN**. Spec refs are sections of `demand_forecast_poc_spec.md`.

## Locked

| # | Decision | Status | Value |
|---|---|---|---|
| 1 | Monorepo name | **DECIDED** | `retail-intelligence` |
| 2 | Data production vs consumption split | **DECIDED** | isolated `datagen/` publishes immutable source/canonical fixtures; `ml/data` owns raw→transform→canonical |
| 3 | ML language / API language | **DECIDED** | Python ML pipelines, Go API |
| 4 | Money storage | **DECIDED** | integer minor units (paise), `minor_unit_exponent = 2`; FX display-only |
| 5 | Contract version | **DECIDED** | `retail_v2` (superset of M5 `retail_v1`) |
| 20 | Source transformation extension points | **DECIDED** | profile-driven default mapper or thin source adapter → standardized staging → shared source-neutral transforms → canonical; no source logic downstream |
| 21 | Generator acceptance dialects | **DECIDED** | one internal truth; `canonical_test`, full generic dialect, Shopify-supported dialect and companion PIM/ERP/WMS/external feeds |
| 22 | Location keys | **DECIDED** | `locations.location_id` authoritative; demand-only `stores` view uses `store_id = location_id` |
| 23 | Sales/returns semantics | **DECIDED** | explicit cumulative sales versions carry fulfilled units + exact net amount; fulfillment lines bridge demand/supply nodes; pre-fulfilment cancellations are excluded; later unit/revenue reversals are typed, versioned adjustments |
| 24 | Shopify local scope | **DECIDED** | documented adapter + fully synthetic golden fixture only; real Shopify runs client-controlled |
| 25 | Competitor-match ownership | **DECIDED** | `competitor_matches` is a PoC output; generator match truth is test-only |
| 29 | Partial-source acceptance | **DECIDED** | manifest-declared entity/field/capability coverage; pure Shopify may be `validated_partial` only; only capability-complete full Gate-B runs are promoted |
| 30 | Source mapping ownership | **DECIDED** | admins approve immutable mapping config; ingestion writes resolved runtime crosswalks and quarantines unknown/ambiguous keys |
| 31 | ATP and inbound semantics | **DECIDED** | source-observed or fixed bucket formula; on-order and in-transit are disjoint; ATP excludes inbound |

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
| 26 | Incremental ingestion semantics | **OPEN** | local path is immutable full snapshots; define CDC/upsert/watermark rules after round-trip acceptance | §11.10 |
| 27 | Non-INR source accounting conversion | **OPEN** | separate from display FX; fail closed until an approved accounting/tax policy exists | §11.11 |
| 28 | Production Shopify connector scope | **OPEN** | after local PoC: connector deliverable vs client-provided landed export | §11.11 |

## Do NOT carry over from the M5 PoC

- The M5-only `M5_POC_DEMONSTRATION_V1` pricing amendment (widened resample-IQR gate). A real
  retailer starts on the strict Plan v3 gates; any amendment must be separately justified,
  versioned, approved, and disclosed. (§4.6)
- Synthetic cost presented as real. A real margin objective requires non-synthetic,
  provenance-matched cost; generated cost = *labelled* margin scenario only. (§10.3)
