# Open decisions

Decisions to lock before or during the build. Status: **DECIDED**, **REC** (recommended default,
not yet confirmed), or **OPEN**. Spec refs are sections of `demand_forecast_poc_spec.md`.

## Locked

| # | Decision | Status | Value |
|---|---|---|---|
| 1 | Monorepo name | **DECIDED** | `retail-intelligence` |
| 2 | Data production vs ingestion vs ML split | **DECIDED** | `datagen/` owns only its source spec and source-shaped publications; top-level `ingestion/` owns raw→Gate A→staging→transform→`retail_v2`→Gate B→curated; `ml/` consumes curated only |
| 3 | ML language / API language | **DECIDED** | Python ML pipelines, Go API |
| 4 | Money storage | **DECIDED** | integer minor units paired with `currency_code` (`INR` paise, `USD/EUR` cents, `GBP` pence); exact source reconciliation is per currency; tenant reporting conversion is derived with as-of FX |
| 5 | Contract version | **DECIDED** | `retail_v2` (superset of M5 `retail_v1`) |
| 20 | Source transformation extension points | **DECIDED** | profile-driven default mapper or thin source adapter → standardized staging → shared source-neutral transforms → canonical; no source logic downstream |
| 21 | Generator outputs | **DECIDED** | Shopify-shaped, Business Central-shaped and external/companion sources, plus source-run manifest and hidden source/causal truth; no canonical publisher |
| 22 | Location keys | **DECIDED** | `locations.location_id` authoritative; demand-only `stores` view uses `store_id = location_id` |
| 23 | Sales/returns semantics | **DECIDED** | explicit cumulative sales versions carry fulfilled units + exact net amount; fulfillment lines bridge demand/supply nodes; pre-fulfilment cancellations are excluded; later unit/revenue reversals are typed, versioned adjustments |
| 24 | Shopify local scope | **DECIDED** | documented adapter + synthetic source projection; exhaustive connector-conformance fixtures are a later tier; real Shopify runs client-controlled |
| 25 | Competitor-match ownership | **DECIDED** | `competitor_matches` is a PoC output; generator match truth is test-only |
| 29 | Partial-source acceptance | **DECIDED** | ingestion-manifest entity/field/capability coverage; pure Shopify may be `validated_partial` only; only capability-complete full Gate-B runs are promoted |
| 30 | Source mapping ownership | **DECIDED** | admins approve immutable mapping config; ingestion writes resolved runtime crosswalks and quarantines unknown/ambiguous keys |
| 31 | ATP and inbound semantics | **DECIDED** | source-observed or fixed bucket formula; on-order and in-transit are disjoint; ATP excludes inbound |
| 32 | Generator configuration | **DECIDED** | Config Builder HTML is the only supported authoring surface; YAML and JSON are losslessly equivalent and contain every resolved run setting |
| 33 | Multi-market topology | **DECIDED** | one retailer scenario may contain multiple explicit markets, stores and warehouses; every node carries market/locale and service relationships |
| 34 | Initial locale packs | **DECIDED** | IN, US, GB and DE; UI may label GB as UK and DE as the PoC European representative; “Europe” is not used as a country code |
| 35 | Missing source metadata | **DECIDED** | source `known_as_of`, versions, manifests, formats and capability declarations are not universal hard requirements; ingestion derives defensible metadata under versioned profile policy or quarantines ambiguity |
| 36 | Datagen isolation | **DECIDED** | `datagen/` imports no downstream `contracts/`, `ingestion/`, `ml/` or `api/` code; ingestion adapts to the published datagen source spec |
| 37 | Generator fidelity tiers | **DECIDED** | exhaustive Shopify lifecycle/HMAC fixtures and full procurement/batch/supplier projections are screen/compliance extensions, not blockers for the first forecast/revenue-pricing round-trip; margin waits for accepted temporal cost |
| 39 | Guardrail config scoping | **DECIDED** | resolve global dimensionless defaults plus explicit `market_id + currency_code` overrides; absolute money, step/grid and price-ending rules are mandatory per market; Python and Go fingerprint and validate the same resolved policy |
| 40 | Contextual feed scope | **DECIDED** | single-axis calendar/signal/competitor geography uses `market_id + geo_scope_type + geo_scope_id`; region/location identifiers are namespaced within market; unqualified `ALL` is invalid; multi-axis promotion applicability uses explicit qualifier rows |
| 41 | Canonical temporal identity | **DECIDED** | cumulative/correctable facts use explicit monotonic integer versions; observation/reference facts use stable natural key + effective/observation time + `known_as_of`; divergent duplicate complete keys quarantine |
| 42 | Merchandise-scope resolution | **DECIDED** | supplier terms and promotion merchandise targets use `merch_scope_type ∈ {sku, dept, category} + merch_scope_id`, with `sku > dept > category`; supplier origin is exact and nullable only for unmodelled external origin, never a wildcard |
| 43 | Operating vs presentment currency | **DECIDED** | canonical sales/sell prices equal the demand location operating currency; Shopify `shopMoney` is authoritative and `presentmentMoney` is audit/display-only; unsupported mismatches quarantine |
| 44 | FX direction and arithmetic | **DECIDED** | `base_ccy` local → `quote_ccy` reporting at exact `DECIMAL(38,18)` quote-per-base rate; exponent-aware per-fact `ROUND_HALF_EVEN`, then aggregate; shared Python/Go vectors |
| 45 | Pricing evidence demos | **DECIDED** | primary IN+US showcase is sized and tested for ≥25 actually gated series per enabled department in both markets; a separate sparse preset demonstrates reason-coded fail-closed behavior; datagen owns scenario knobs, not ML thresholds |

## Recommended (confirm)

| # | Decision | Status | Recommendation | Spec |
|---|---|---|---|---|
| 6 | Cost valuation method | **REC** | Moving Average Cost default; FIFO only where batch/expiry tracked | §10.5 |
| 7 | Who computes WAC | **REC** | when the BC/ERP companion projection is enabled it emits receipt-shaped source rows; ingestion derives canonical receipts and the PoC computes `inventory_cost` WAC | §11.2 |
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
| 15 | Production weather granularity + provider | **OPEN** | synthetic data is market/region/store configurable; choose the client-actual provider and timestamp evidence later | §11.5 |
| 16 | Fingerprint canonicalization spec | **OPEN** | must be byte-identical in Python + Go (key order, number format); resolve and publish golden vectors in Phase 2 before Phase 3 emits fingerprinted artifacts | Arch note |
| 17 | UI framework | **OPEN** | the `docs/` mockup is static HTML; pick the real stack | §8.4 (ui) |
| 18 | Copilot serving | **OPEN** | Go proxies to a Python copilot service vs Go calls the LLM directly; grounding from same artifacts | §8.4 |
| 19 | Customer/segment data depth | **OPEN** | segment mix only, or basket-level for cannibalisation/bundle models | §8.1, §11.4 |
| 26 | Incremental ingestion semantics | **OPEN** | local path is immutable full snapshots; define CDC/upsert/watermark rules after round-trip acceptance | §11.10 |
| 27 | Tenant reporting-currency accounting policy | **OPEN** | direction/precision/rounding are locked by #44; choose the production FX source, rate type and any accounting-date override for cross-market reporting aggregates | §2.4, §11.0 |
| 28 | Production Shopify connector scope | **OPEN** | after local PoC: connector deliverable vs client-provided landed export | §11.11 |
| 38 | Python environment topology | **OPEN** | `datagen/` is independently isolated and may start; decide whether `ingestion/` and `ml/` use separate distributions/environments or a shared governed workspace before scaffolding those two package boundaries | Architecture note |

## Do NOT carry over from the M5 PoC

- The M5-only `M5_POC_DEMONSTRATION_V1` pricing amendment (widened resample-IQR gate). A real
  retailer starts on the strict Plan v3 gates; any amendment must be separately justified,
  versioned, approved, and disclosed. (§4.6)
- Synthetic cost presented as real. A real margin objective requires non-synthetic,
  provenance-matched cost; generated cost = *labelled* margin scenario only. (§10.3)
