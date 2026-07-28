# Retail AI PoC — Data, Model & Guardrail Specification

**Target UI:** the `ai_retail_intelligence_dashboard_multicurrency_v6.html` dashboard.
Sections 1–7 anchor on the *Demand Forecast* screen (the reference screen); **section 8
extends the same analysis to every other screen** (Pricing, Competitor Monitor, Promotion
Planner, Inventory + sub-screens, Replenishment/Planner, Analytics, Admin/Settings).
**Section 9** covers synthetic-data generation, **section 10** the mandatory data
elements + derived-metric dependencies (incl. cost-over-time in §10.5), and **section 11
is the full data schema** (every entity, sample rows, and how each is used). **Appendix A**
explains the service-level policy.

**Scope note.** This document specifies a **new, separately-built** retail-AI PoC for the
dashboard above. The demo tenant is an India-led multi-category retailer, but one generated
scenario may include explicit stores and warehouses across India, the United States, the United
Kingdom and Germany (the PoC representative for Europe), with local transaction currencies and
INR tenant reporting. The **prior PoC ran on the public M5 dataset**; the new PoC is a fresh
codebase that **reuses and adapts proven modules** from it (adapter, features, forecaster,
reorder/pricing engines, guardrails, workflow). File references point at the M5 repo so the new
build can lift the pattern rather than reinvent it.

### Architecture & data flow (read this first)

The new PoC has three hard boundaries: independent source generation, ingestion/transformation,
and ML consumption:

```
[ datagen / retailer / Shopify / BC / external sources ]
             source-shaped files/objects
                         │
                         ▼
[ ingestion/ ]
 immutable raw landing → Gate A → profile/adapter → standardized staging
       → source-neutral transforms → canonical retail_v2 candidate → Gate B
                                      ├── validated_partial (stop)
                                      └── capability-complete pass
                                                   │
                                                   ▼
                                        curated Parquet/DuckDB
                                                   │
                                                   ▼
[ ml/ ] features → models → engines → artifacts → Go API → UI/workflow/audit
```

- **`datagen/` owns "how synthetic source reality is made."** The demand/price/weather/inventory
  logic described in §9 lives there. It follows its own scenario and source-data specification
  and publishes Shopify-shaped, Business Central-shaped and external/companion sources, a
  source-run manifest and hidden causal truth. It never imports or emits `retail_v2`, Gate A/B
  rules, canonical versions or canonical `known_as_of`.
- **A retailer or platform owns its source semantics.** Raw files are landed immutably and never
  edited in place. A source is not required to contain a config hash, manifest, canonical
  version, `known_as_of`, availability history or a preferred physical format. A versioned
  ingestion profile declares how available source evidence and immutable landing metadata are
  normalized or derived.
- **`ingestion/` owns "land → canonical → curated."** It applies a declarative profile through
  the default `mapped_files` normalizer or, where necessary, a thin platform adapter; both emit
  standardized staging. Reusable source-neutral domain transforms then produce canonical grains
  and semantics. It owns Gate A, Gate B, provenance, reconciliation and curated publication.
- **`ml/` owns "curated → decide."** Features/models/engines receive only capability-complete
  curated data and never contain retailer-, Shopify-, Business Central- or datagen-specific code.
- **§11 is the canonical output contract of ingestion, not necessarily the physical raw-file
  contract.** Only transformed canonical tables must match `retail_v2`. Generated and authorized
  client sources travel through the same transformation/quality boundary. Direct canonical unit
  fixtures, when useful, belong to ingestion/contract tests and are not generator outputs.
- **Fail closed twice.** A raw-source gate validates extract completeness, parsing, keys and
  reconciliation; a canonical gate validates schema, point-in-time semantics, provenance,
  business rules and referential integrity before anything is promoted to curated storage.

### Technology stack — Python ML pipelines + Go API

The new PoC is **polyglot**: **ML pipelines in Python, the API/serving layer in Golang.**

```
 PYTHON                                                GO (API / serving)
 ingestion/: Gate A → staging → transform → Gate B    reads artifacts + PostgreSQL
             → curated                                serves REST/gRPC to the UI
 ml/: features → models(LightGBM/Poisson-EB) →         owns workflow/HITL, guardrail
      engines(reorder, pricing, allocation, ageing) →  re-validation, staleness 409/503,
      artifacts + semantic fingerprints          ──▶  RBAC/auth, audit
```

What this means for the M5-PoC carry-over:
- **Python `[REUSE + EXTEND]` — reuse where contract-compatible:** adapt the proven feature,
  model and engine implementations rather than rewriting them. The M5 `data/` patterns are a
  starting point for top-level `ingestion/`, but raw landing, two validation gates, source
  profiles/adapters, semantic transforms and reconciliation are material `retail_v2` extensions
  rather than an as-is copy.
- **Go `[REUSE-as-redesign]` — reimplemented in Go:** the current Python `api/app.py`
  (FastAPI), `api/workflow_service.py`/`workflow_repository.py` (approvals, planner overrides,
  idempotency, audit), the **serve-time guardrail re-validation** (`validate_recommendation`,
  pricing-graph validation), the **staleness 409/503** logic, and RBAC. The *design and rules*
  carry over; the *code* is rewritten in Go.

**The Python↔Go boundary is deliberately the artifact + DB contract** (not in-process calls),
which is exactly how the M5 PoC already separates "pipeline produces validated artifacts" from
"API validates + serves them." The interface is: **artifact manifests + semantic fingerprints
(`reports/artifact_identity.py`) + the PostgreSQL schema + the shared guardrail YAMLs.** Engineer
for four cross-language risks:
1. **Fingerprint parity** — SHA-256 over canonical JSON must be **byte-identical** in Python and
   Go (fixed key order, number formatting, volatile-key stripping). Define one canonicalization
   spec and test both against shared golden vectors, or lineage 409s will fire spuriously.
2. **Money precision** — integer **minor units** paired with `currency_code` on both sides
   (`INR` paise, `USD/EUR` cents, `GBP` pence); no float drift in margin/price math.
3. **Single-sourced, market-resolved guardrail thresholds** — Python (enforce in engine) and Go
   (re-enforce at serve) both read the *same* `pricing_rules.yaml` / `policy.yaml` /
   `price_response.yaml`; never duplicate the numbers as Go constants. Both implementations use
   the same deterministic global-default → market-override resolution and fingerprint the
   resolved market policy.
4. **Migrations ownership** — the PostgreSQL schema is one shared asset. Recommend keeping
   **Alembic (Python)** as the single migration owner and generating Go structs from it.

**Interactive scoring** (the one real design fork): batch forecasts/recommendations are
precomputed by Python and served by Go, but the interactive screens — Price Simulation "Run",
Scenario Planning "Run", Promotion Simulation, Copilot — need on-demand computation. Recommended
split: **Go computes the closed-form projections itself** from stored coefficients (e.g.
`units = p50·(price/price0)^β`, revenue/margin, safety stock — all cheap arithmetic on stored
β / P50 / P90), and **calls a small Python scoring service (gRPC/REST) only when it needs the
actual fitted model** (re-scoring LightGBM/GLM) or the LLM copilot. Keep all *training* in Python
batch. Decide this explicitly — it determines whether Go needs any Python at request time.

Legend: **[REUSE]** = carry over a proven M5 design or compatible implementation;
**[REUSE + EXTEND]** = retain that foundation but make material `retail_v2` changes;
**[REUSE-as-redesign]** = preserve behavior while reimplementing it in Go; **[NEW]** = build
fresh (in the PoC, or — for data — in the generator repo).

---

## 1. The screen at a glance

| Area | Contents |
|---|---|
| **KPIs (5)** | Forecast Accuracy 87.6% (target 90%); Forecast Bias −2.8% (±5%); Demand at Risk ₹3.84 Cr (342 SKU-store combos); Planner Overrides 184 (71% accepted); Forecast Value Add +11.2% (WAPE improvement) |
| **Filters (6)** | Region, Store, Category, Horizon (4/8/13/26 wk), Granularity (Weekly/Daily/Monthly), free-text search |
| **Tabs (5)** | Overview · Store View · SKU View (workbench) · Demand Drivers · Governance |
| **Toolbar modals (6)** | Accept Forecast · Add Planner Adjustment · Compare Versions · Scenario Planning · Forecast Action Center · Export |
| **Currency** | Exact local-currency facts (INR/USD/GBP/EUR); tenant reporting base INR; display switch uses governed as-of FX |

The screen is a **decision-support + governance workbench** on top of a demand forecast:
it shows AI vs baseline vs planner-adjusted numbers, exception queues, driver attribution,
external-signal readiness, approval SLAs, and lets planners accept/override forecasts and
run demand scenarios.

---

## 2. Part A — Data points required

### 2.1 Foundation: the canonical entities **[REUSE + EXTEND]**

The current PoC already defines a versioned, dataset-neutral contract `retail_v1`
(`data/contracts.py`, `../retail_ai/docs/schema.md`). The new PoC reuses its core but versions it to
`retail_v2` for locations, post-sale adjustments, temporal cost and explicit point-in-time
semantics. The profile/adapter normalization layer and shared domain transforms map client
extracts into these once; everything downstream is source-neutral.

| Entity | Grain | Required fields | Feeds on this screen |
|---|---|---|---|
| `sales` | SKU × demand location × **day × availability version** | `sku_id, store_id, date, sales_version, units, net_sales_amount, currency_code, known_as_of` (+ `net_price, promo_flag`) | Every KPI, Forecast-vs-Actual, workbench Baseline/Last-Actual, accuracy/bias |
| `sales_adjustments` | post-sale event × availability version | `adjustment_id, adjustment_version, sku_id, store_id, sale_date, event_date, event_type, known_as_of` (+ conditional `units` or `amount`) | Physical returns/post-fulfilment cancellations and financial refunds without rewriting fulfilled-sales history |
| `sales_fulfillments` | fulfillment line × availability version | `fulfillment_line_id, fulfillment_version, source_sale_id, sku_id, demand_location_id, supply_location_id, sale_date, fulfilled_at, units, known_as_of` | Bridges online/POS demand to the physical supply node; split-fulfillment and inventory reconciliation |
| `products` | SKU | `sku_id, dept_id, category, sub_cat, pack_size` (+ `product_name, brand, shelf_life_days, reference_cost`) | Category filter, SKU labels, pack rounding, expiry |
| `locations` | store/online/DC/3PL | `location_id, type ∈ {store, online, dc, 3pl}, market_id, currency_code, timezone, region, active` (+ `format, channel, parent_dc`) | Authoritative market/location hierarchy; its currency governs canonical sales/sell prices while other money domains follow their declared capability policy; derives the demand-only `stores` compatibility view |
| `calendar` | market×day | `market_id, date, known_as_of` (+ day attributes) | Market-local business day and seasonality |
| `calendar_events` | market×geographic scope×event×date | `market_id, geo_scope_type, geo_scope_id, date, event_name, event_type, known_as_of` | Event drivers, exception "New product / event" |
| `sell_prices` | SKU × store × **week × known-as-of observation** | `sku_id, store_id, effective week, net_price, currency_code, known_as_of` | Price-movement driver, scenario price axis, pricing |
| `stock_snapshots` | SKU × location snapshot | `sku_id, location_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | Demand-at-risk, stock-out risk, required-inventory in scenarios |
| `suppliers_leadtimes` | supplier × merchandise scope × destination/origin × effective date × known-as-of observation | `supplier_id, destination_location_id, merch_scope_type, merch_scope_id, effective_from, lead_time_days, moq, pack_qty, known_as_of` (+ `from_location_id`) | Market/location-specific safety-stock, required-inventory and replenishment linkage |
| **pricing metadata** block | market | `market_id, currency_code, minor_unit_exponent`, price/cost unit & tax basis | Market-local money semantics; reporting conversion remains separate |

**History depth.** The feature set uses a 52-week seasonal lag, so **>52 complete weeks is
the technical minimum; 18–24 months is the practical pilot minimum; 2–3 years is preferred**
for the 13/26-week horizons and rolling evaluation the screen shows.

**Point-in-time discipline (critical) [REUSE].** Every temporal entity needs `known_as_of`
(when the fact became available to the decision process, not the transaction date). This is
mandatory for every temporal canonical output. A profile may resolve it from a trusted native
observation/update timestamp, immutable extraction time or landing time and must record that
derivation. It cannot use an arbitrary same-day fallback; unresolved evidence fails closed. This
is what makes the screen's accuracy/bias numbers honest rather than leaked.

### 2.2 NEW external-signal feeds the screen demands **[NEW]**

The **Demand Drivers** tab shows an *External Signal Readiness* panel and a driver-contribution
table with **Competitor availability (8%)** and **Weather & local events (7%)** — signals the
current `retail_v1` contract does **not** carry (M5 only has national calendar events + SNAP +
prices). These are the biggest data gap. Proposed new canonical entities:

| New feed | Suggested grain | Key fields | Drives |
|---|---|---|---|
| `competitor_prices` | market × competitor product × geographic scope × observation | `market_id, comp_id, comp_product_id, geo_scope_type, geo_scope_id, observed_at, price, currency_code, in_stock_flag, known_as_of` | "Competitor availability" & "Competitor stock-out" drivers; scenario *Competitor Availability* axis; pricing competitor bound |
| `weather_actual` / `weather_forecast` | market × geographic scope × day/forecast target | `market_id, geo_scope_type, geo_scope_id, date/forecast_date/target_date, temp, precip, weather_code, known_as_of` | "Weather & local events" driver; scenario *Weather/Event Impact* axis |
| `local_events` | market × geographic scope × event/date | `market_id, geo_scope_type, geo_scope_id, date, event_name, event_type, expected_impact, known_as_of` | "Local event anomaly" primary driver; store-level exceptions |
| `macro_index` | market × geographic scope × week | `market_id, geo_scope_type, geo_scope_id, week_start, index_name, value, known_as_of` | Macroeconomic external signal (weekly) |
| `fx_rates` | base currency × reporting currency × rate date | `base_ccy, quote_ccy, rate, rate_date, known_as_of` | Local→reporting-currency display only (see 2.4) |

All must respect the same `known_as_of` rule (a **forecast** weather value or a promo-calendar
entry must not be "known" before its real publication date, or it leaks).
For every geographically contextual feed (all rows above except FX), `market_id` is mandatory.
`geo_scope_type ∈ {market, region, location}`
and `geo_scope_id` form a typed key; a region identifier is namespaced within its market, so
`(india, region, west)` and `(us, region, west)` are distinct. A market-wide signal uses
`geo_scope_type=market, geo_scope_id=market_id`, never a global free-form value such as `ALL`.

### 2.3 Product/analytics data the screen introduces **[NEW]**

These are outputs/records the screen renders that the current PoC either doesn't persist or
persists differently. They should become first-class tables in the new PoC:

| Data object | Fields | Screen element |
|---|---|---|
| **Forecast versions** | `version_id, kind {baseline\|ai\|planner_adjusted}, created_by, accuracy, bias, demand_units, status, semantic_fingerprint` | *Compare Versions* modal; Forecast Value Add table |
| **Planner adjustments/overrides** | `sku_id, store_id, ai_forecast, planner_forecast, reason_code {Local event, Promotion change, Competitor event, Operational constraint, Commercial judgement}, effective_period, comment, actor, value_added_flag` | *Add Planner Adjustment* modal; "Planner Overrides 184 / 71% accepted / 62% adding value" KPI |
| **Per-series confidence** | `confidence_pct` derived from P90–P50 spread relative to P50 | Workbench *Confidence* column; Accept-Forecast avg confidence |
| **Per-series data-quality class** | `data_quality {Good, Watch, Issue}` from the quality battery per SKU-store | Workbench *Data Quality* column; "Data-quality exception" count |
| **Driver attribution** | per-driver `contribution_pct, direction, confidence` at portfolio **and** SKU level | Demand Drivers table; workbench *Primary Driver* |
| **Demand-at-risk (₹)** | under-forecast/stock-gap units × price/margin, gated by stock cover | "Demand at Risk" KPI, Store View, Action Center |
| **Governance/SLA records** | workflow stage, open count, avg age, SLA target, status; model-drift %; data-freshness % | Governance tab |

### 2.4 Multi-currency **[NEW, local facts + reporting conversion]**

Each transaction/price/cost fact retains its exact **local currency** and integer minor-unit
amount. The dashboard aggregates in the tenant reporting currency (**INR** for this PoC) using an
as-of-dated `fx_rates` table; it may then display INR/USD/EUR/GBP views. Reporting conversion is
derived and never replaces or participates in the source-money reconciliation.

The FX direction is fixed: `base_ccy` is the fact/local currency, `quote_ccy` is the tenant
reporting currency, and `rate` is **quote major-currency units per one base major-currency unit**.
`rate` is an exact `DECIMAL(38,18)` value, never binary floating point. For base/quote minor-unit
exponents `b` and `q`, conversion of one canonical fact is
`round(amount_minor × rate × 10^(q-b))` using `ROUND_HALF_EVEN`; converted facts are then summed.
For realized facts, use the greatest `rate_date ≤ fact business date`; for future forecast/
recommendation amounts, use the greatest `rate_date ≤ decision_as_of`. In either case select the
latest observation for that rate date whose `known_as_of` is at or before the decision cutoff;
absence fails the reporting conversion rather than using a future rate. Identity rates use
`base_ccy=quote_ccy, rate=1`. Python and Go must pass the same conversion vectors. Decision #27
remains open only for the production FX provider, rate type and approved accounting-date
overrides—not direction, numeric representation or default rounding.

Demand forecasting remains unit-based. Pricing and margin math run within a single local
currency for a market/store; FX is not a causal model input. Cross-market monetary aggregation
uses the separately governed reporting conversion policy.

Every demand and supply location therefore carries `market_id`, operating `currency_code` and
IANA `timezone`, including before its first sale. In the initial PoC, canonical
`sales.currency_code` and `sell_prices.currency_code` must equal the demand location's operating
currency. Shopify `shopMoney` is the canonical sales-money authority; `presentmentMoney` stays
in raw/staging audit evidence and never drives pricing, margin or source-money controls. A source
that supplies only a mismatched transaction/presentment currency without an authoritative
operating-currency amount cannot satisfy the sales-money capability and is quarantined rather
than silently FX-converted. Cross-currency procurement cost requires a separately approved
cost-conversion policy before it can enter operating-currency WAC/margin.

### 2.5 Element → data map (the core mapping)

| Screen element | Concrete inputs required |
|---|---|
| **KPI: Forecast Accuracy** | Pooled WAPE over the rolling-origin evaluation → `accuracy ≈ 100 − WAPE·100` (define explicitly; see 4.8) |
| **KPI: Forecast Bias** | Pooled bias = Σ(pred−actual)/Σactual over evaluation origins |
| **KPI: Demand at Risk** | P50 forecast, inventory position (ATP + disjoint on-order/in-transit), lead time, price/margin → lost-sales exposure ₹ |
| **KPI: Planner Overrides** | Count/accept-rate/value-added from planner-adjustment records (2.3) |
| **KPI: Forecast Value Add** | (baseline WAPE − AI WAPE)/baseline WAPE, baseline = MA13 |
| **Overview: Forecast vs Actual** | Weekly forecast (P50) vs realized `units`, last 8 weeks |
| **Overview: Health by Horizon** | Per-horizon (1/4/8/13 wk) accuracy, bias, coverage |
| **Overview: Exceptions** | Counts by rule: under/over-forecast risk, sparse-history/new-product, promo conflict, data-quality |
| **Overview: FVA table** | Statistical baseline, AI, planner-adjusted accuracy + net FVA + %overrides-adding-value |
| **Overview: Business Impact** | Inventory-replay deltas: stock-out ↓, excess inventory ↓, markdown ↓, working-capital release, service-level ↑ |
| **Store View** | Per-store accuracy, bias, demand-at-risk ₹, stock-out risk, override rate, priority action |
| **SKU Workbench** | Per SKU-store: baseline, AI (P50), planner forecast, last actual, accuracy, bias, confidence, primary driver, data-quality, status |
| **Demand Drivers** | Driver contribution %/direction/confidence (SHAP + new competitor/weather groups); external-signal connection status + freshness |
| **Governance** | Approval-stage queues + SLA ages; version traceability, override-comment %, data-freshness %, model-drift %, back-test coverage |
| **Modal: Scenario Planning** | Scenario inputs (demand adj, price change, promo uplift, competitor availability, weather/event) → demand units, revenue ₹, required inventory ₹, stock-out-risk delta |
| **Modal: Compare Versions** | Forecast-version records (2.3) |
| **Modal: Accept / Adjust / Action Center** | Selected rows, confidence, demand value ₹; adjustment reason codes; exception queue with owners + exposure ₹ |

---

## 3. Part B — Models to use

### 3.1 Primary demand forecaster **[REUSE — `lightgbm-horizon-quantile-replay-routed-v5`]**

Carry over the current champion (`models/forecasting.py`, `models/train_lgbm.py`):

- **LightGBM quantile regression, one model per (horizon × quantile)** — objective `quantile`,
  α = 0.50 and 0.90, ~400 trees, lr 0.04, deterministic seed. Produces **P50 and P90** for
  **8 weekly horizons (h1–h8)**. Out-of-time conformal-style bias offset on a calibration slice,
  monotonicity enforced (`p90 ≥ p50 + 1`).
- **Routing ("routed") [REUSE]** — series with `zero_share_52w > 0.60` (intermittent/slow) route
  to **Croston's SBA** when it historically beats seasonal-naive *and* its replay error ≤ LightGBM's;
  otherwise a LightGBM intermittent fallback. This directly serves the screen's "slow mover /
  sparse history" exceptions.
- **Replay retraining ("replay") [REUSE]** — fit at the first replay origin, retrain at each
  formal evaluation origin, reuse for interleaving weekly origins.
- **Horizon coverage.** The screen's 4/13/26-week horizon filter exceeds the current 8-week
  build. **Extend `HORIZONS` to cover 26 weeks** (or add a monthly/13-week aggregation path).
  This is the one substantive modeling extension for the forecaster.
- **Multi-market adaptation [EXTEND].** Retain SKU×store unit targets, but join market-local
  calendars by market/calendar key and add market/country categorical context. A pooled model
  may use dimensionless or local-normalized price features (`price_ratio`, discount %, local
  category index), never incomparable raw INR/USD/GBP/EUR levels. Publish global and per-market
  metrics; calibrate within market when evidence is sufficient and fall back to the fingerprinted
  global calibration otherwise.

### 3.2 Baselines & Forecast Value Add **[REUSE]**

`models/baselines.py` already produces `naive` (lag-1), `seasonal_naive` (lag-52), `ma8`, and
**MA13** (the incumbent "current method"). FVA on the screen = relative WAPE improvement of the
AI champion vs MA13; a vs-seasonal-naive number is also computed. This gives the "Statistical
baseline / AI / Planner-adjusted" rows directly.

### 3.3 Quantiles → safety stock & demand-at-risk **[REUSE]**

`engines/reorder.py`: safety stock = RSS of weekly (P90−P50) spreads over `lead_time + review`
days × `Φ⁻¹(service_level)/Φ⁻¹(0.90)`; reorder point, order-up-to, cover days follow. This is
exactly what powers Demand-at-Risk, Stock-out Risk, Required Inventory, and the Business-Impact
inventory deltas (via the daily replay simulator `engines/simulator.py`).

### 3.4 Driver attribution **[REUSE + EXTEND]**

`models/train_lgbm.py` already defines SHAP-style `DRIVER_FEATURE_GROUPS`:
`demand_trend, seasonality, price, promo, event_snap`, and a transparent deterministic **blend**
(`0.42·roll_mean_13 + 0.24·lag_52 + 0.22·lag_1 + 0.12·roll_mean_4` × price/promo/calendar factors)
used for explainability. That covers 5 of the screen's 6 drivers. **Add two driver groups —
`competitor_availability` and `weather_local_events` — fed by the new feeds (2.2).**

### 3.5 Price elasticity / price-response **[REUSE — `price-response-poisson-eb-v1`]**

`models/price_response.py`: observational **Poisson GLM (log link)** estimating β (log-price
elasticity) with seasonality/trend/event controls, then **empirical-Bayes shrinkage
(DerSimonian–Laird τ²)** toward department×price-tier clusters, uncertainty via **200 seeded
price-episode block resamples**, validated by rolling-origin holdout Poisson deviance. This powers
the **Price Change axis** of Scenario Planning and the price-movement driver. **Label it
observational, not causal** (see guardrails 5.9).

For multiple currencies, the within-series log-price coefficient remains valid only while a
SKU×store series stays in one local currency. Price tiers, shrinkage pools, evidence coverage and
calendar controls are therefore market-scoped; raw local-currency price levels are never pooled
across markets, and FX changes are never introduced as price-response variation.

### 3.6 Scenario & uplift engine **[REUSE core + EXTEND inputs]**

Scenario Planning takes demand-adjustment, price-change, promo-uplift, competitor-availability,
and weather/event inputs and returns demand units, revenue ₹, required inventory ₹, and stock-out
risk. Build it on the existing simulator + elasticity:

- Price change → demand via the price-response β **[REUSE]**.
- Demand delta → required inventory & stock-out risk via reorder/simulator **[REUSE]**.
- **Promotion-uplift model, competitor-availability sensitivity, weather/event sensitivity
  [NEW]** — new response coefficients fed by the new feeds.

### 3.7 Cold-start / new products **[REUSE]**

Hard gate: LightGBM path requires `units_lag_52 IS NOT NULL` (~1 yr history). Sparse series
route to Croston; the coalescing blend/MA13 gives thin series a number. New-product SKUs surface
in the "New product / sparse history" exception bucket and via the `cold_start` exception rule.

### 3.8 Metrics — and one important caveat

- **WAPE** = Σ|actual−pred| / Σactual · **Bias** = Σ(pred−actual)/Σactual (signed; + = over-forecast).
- **P90 coverage** must sit in [0.85, 0.95]; P50/P90 monotonic.
- **Caveat:** "Accuracy" is **not** a distinct metric in the current code — the screen's 87.6%
  is a narrative transform of WAPE. Define it explicitly for the new PoC, e.g.
  `accuracy = 100·(1 − WAPE)`, and state it in the methodology so the KPI is reproducible.

### 3.9 Training cadence, versioning, registry **[REUSE]**

Rolling-origin: 26-week evaluation window, step-2 → **13 formal scoring origins**, 104 training
origins, 8-week label embargo. MLflow experiment tracking (`registry.mlflow_uri`) + **content-
addressed artifact manifests / semantic fingerprints** (`reports/artifact_identity.py`) as the
authoritative, tamper-evident lineage. The *Train Model* modal (Demand Forecast / Price Elasticity
/ Stock-out Risk; 12/24-month window) maps to these three model families + training-window param.

**Model-by-screen summary**

| Screen model need | Model to use |
|---|---|
| Demand forecast (P50/P90, 1–26 wk) | LightGBM horizon-quantile + Croston routing (extend horizons) |
| Baseline / FVA | MA13 (incumbent), seasonal-naive, naive, MA8 |
| Safety stock / demand-at-risk | Quantile-spread RSS reorder engine |
| Driver attribution | SHAP groups + deterministic blend (+ competitor/weather groups) |
| Price elasticity (scenario price axis) | Poisson GLM + empirical-Bayes (observational) |
| Scenario / uplift | Elasticity + simulator + new promo/competitor/weather sensitivities |
| Stock-out risk | Reorder + daily replay simulator |

---

## 4. Part C — Guardrails required

The current PoC's guardrail philosophy should be carried over wholesale, because it is exactly
what the Governance tab and the Accept/Approve flows visualize: **every numeric guardrail is
validated at load time (fail-closed on unknown/missing keys), re-enforced by an independent
validator at publish time, and bound into a semantic fingerprint so mismatched lineage surfaces
as a 409/503 rather than silently serving bad output.**

### 4.1 Two-stage ingestion data-quality gate **[REUSE + EXTEND — `ingestion/quality/`]**

A promotable full/capability publication receives `status = pass` iff **both gates have zero
critical violations**. A passing raw gate never implies that the source has canonical meaning,
and a canonical gate is never allowed to hide discarded or unreconciled source rows. A partial
source such as Shopify may receive `status = validated_partial` after its declared canonical
slice passes the applicable Gate-B rules; that status is adapter evidence only and cannot feed
models or masquerade as a complete curated publication.

**Gate A — raw/source-profile validation (before transformation):**

- the ingestion-owned landing manifest and content hashes match; if the source supplies its own
  manifest it is retained and reconciled, otherwise ingestion constructs one from immutable
  landing metadata;
- expected files/tables and extract window are present; an event/API connector supplies
  authenticity or pre-landing field-projection evidence only when its approved profile requires
  that evidence;
- entity/field coverage, capability claims, companion expectations and approved mapping
  references are resolved by the ingestion profile; they are not mandatory fields in every
  retailer export;
- source schema is parseable and required source keys exist; duplicate source rows and a
  conflicting reuse of a snapshot ID are rejected, while an exact replay of the same
  snapshot-ID/content-hash pair is an idempotent no-op linked to the prior result;
- timezone, currency, tax basis, quantity unit and source grain are either supplied or resolved
  by an approved source profile;
- input, filtered, rejected and accepted row counts reconcile, with reason-coded quarantine rows;
- source control totals (quantity and money where supplied) are recorded before transformation.

**Gate B — canonical `retail_v2` validation (after transformation):**

- required columns/types, non-null fields, canonical grain and unique business keys; cumulative/
  correctable entities must have explicit monotonic version keys, while observational/reference
  entities use their declared natural key + effective/observation time + `known_as_of` ordering;
  divergent duplicate observations at the same complete key are critical;
- negative units; non-positive price; per-series **date gaps** after resolving the applicable
  availability version (distinct-date vs span, so duplicates cannot mask a missing day); and
  product/pack/shelf-life rules;
- `known_as_of` placement, no future knowledge at an earlier decision cutoff, and source/
  transformation provenance on every derived or synthetic value;
- stock/receipt placement, non-negative inventory, ATP-method equation, disjoint
  on-order/in-transit reconciliation, positive lead/MOQ/pack, cost-ledger completeness when a
  cost-dependent capability is enabled, and cross-entity referential integrity;
- every contextual calendar/signal/competitor row resolves its `geo_scope_*` inside `market_id`;
  promotion applicability follows its declared multi-axis scope rows; unqualified `ALL`, unknown
  region/location scope and cross-market joins are critical;
- supplier and promotion merchandise rows resolve valid `merch_scope_*` references and
  deterministic `sku > dept > category` precedence; conflicting equal-precedence matches are
  critical;
- canonical sales/sell-price currency equals the demand location's operating currency; source
  presentment money remains audit-only, and any unsupported mismatch is quarantined;
- an independently **re-derived promo-rule check** (28-day trailing median) so a leaky source
  column cannot alias past the gate; stale prices over 180 days remain warnings;
- canonical fulfilled and fulfillment-bridge quantities plus exact `net_sales_amount`/discount/
  tax totals reconcile to raw controls after explicitly declared filters, returns,
  cancellations, aggregation and unit/currency conversion; adjustment type/nullability and
  as-of net-view equations hold.

Only a double-pass is atomically promoted to curated Parquet/DuckDB and receives the per-SKU
**Data Quality {Good/Watch/Issue}** class. Any unexplained reconciliation difference is critical.

### 4.2 Point-in-time / anti-leakage **[REUSE]**

`known_as_of` on every temporal fact; **8-week label embargo** plus a per-horizon
`target_known_as_of ≤ fit_known_as_of` cutoff; origin-aware late-sales handling so delayed
transactions enter their correct historical week and never leak earlier; weekly calendar/event
features published only when every contributing daily row was known. This is what keeps the
accuracy/bias KPIs defensible.

### 4.3 Forecast acceptance gates **[REUSE — `models/backtest.py`]**

A forecast is publishable only if **all** hold:
- Champion WAPE beats seasonal-naive by **≥ 25%** overall.
- Empirical **P90 coverage ∈ [0.85, 0.95]**.
- Slow-mover slice (`zero_share_52w > 0.60`) champion WAPE **≤** seasonal-naive.
- **P90 ≥ P50** on every row.
- The same WAPE/bias/P50/P90 diagnostics are published for each supported market, and no
  supported market may fail its declared minimum gate while a larger market masks it in the
  pooled result. Insufficient-evidence markets remain explicitly unaccepted/cold-start rather
  than borrowing an unlabelled pass.

### 4.4 Bias, drift & freshness tolerances **[REUSE + surface]**

Map directly to the Governance/KPIs: **Forecast Bias target ±5%** (KPI); **model-drift within
tolerance** and **data-freshness compliance** metrics (Governance tab). Freshness is measured
against the accepted forecast's `decision_as_of`, **never wall-clock** — carry that over.

### 4.5 Inventory service-level policy **[REUSE — `config/policy.yaml`, `engines/policy_*`]**

Per-ABC service levels **A 0.96 / B 0.90 / C 0.80** (bounded [0.5, 0.999]); review 7 d; max
cover 30 d; hold/markdown thresholds. Governed by **calibration on a deterministic 5% cohort +
validation on the untouched 95% holdout**, both bound to the same forecast fingerprint. This
governs the safety-stock / demand-at-risk numbers.

Dimensionless defaults may be shared globally, but any market override is resolved before
calibration/publication and becomes part of the policy fingerprint. Cross-market value ranking
or inventory valuation requires approved reporting-currency conversion; unit reorder math does
not.

### 4.6 Pricing guardrails **[REUSE — for the price axis; `config/pricing_rules.yaml` + `engines/pricing.py`]**

For the scenario price axis and any pricing linkage: category `floor`/`ceiling`;
**`max_change_pct_per_cycle` = 5%**; **`min_margin_pct` = 12%** (margin floor, repairable only by
a legal price increase — never by relaxing the floor); confidence-scaled action cap (2% → 5% as
dominance 0.70 → 1.0); price endings/step; candidates clamped to observed price range (no
extrapolation). Statistical acceptance gates (`config/price_response.yaml`, strict "Plan v3"):
**require negative β, 0.30 ≤ |β| ≤ 4.00, sign-consistency ≥ 0.90, resample-IQR ratio ≤ 0.80,
≥ 50 draws, holdout improvement > 0**, plus per-department coverage ≥ 5% and ≥ 25 gated series.
**Do NOT inherit the M5-only `M5_POC_DEMONSTRATION_V1` amendment** (it widened only the IQR ratio
to 1.50 for the M5 demo) — a real retailer starts on the strict gates; any amendment must be
separately justified, versioned, approved, and disclosed.

Guardrails resolve at `market_id + currency_code`. Currency-neutral percentages and statistical
evidence gates may inherit a versioned global default; absolute `floor`/`ceiling`,
`candidate_step`, `grid_origin`, preferred endings and any other money/locale convention must be
declared for the market or fail closed. A store recommendation must match the resolved market
currency and cannot be optimized or summed with another currency. Python and Go validate the
same resolved payload and shared golden vectors byte-for-byte.

The number of stores does not determine evidence coverage: one store with many eligible SKUs may
produce more than 25 SKU×store series in a department. The primary multi-market showcase must
therefore be sized and tested to produce at least 25 **actually gated** series per enabled
department in both India and US; it may not assume that configured SKU count equals accepted
coverage. A separate sparse-evidence preset intentionally produces an unpriced market and the UI
must show the reason-coded `insufficient_evidence` state. Datagen controls only its own assortment,
price-event and noise parameters; the ML acceptance test—not the generator—owns these thresholds.

### 4.7 Human-in-the-loop **[REUSE — `api/workflow_service.py`]**

- **Approval tiers** (dashboard Settings): price change ≤5% → Category Manager; 5–10% → Pricing
  Manager; >10% → Business Head; replenishment order → Demand Planner + Manager. Role-gated
  actions (planner/lead/admin).
- **Planner override rules:** quantity/forecast edits require a **non-empty reason** and are
  bounded (positive, pack-multiple, ≥ MOQ, ≤ engine order-up-to); every edit writes an audit row
  with old/new value + reason + recommendation version. → the Add-Planner-Adjustment reason codes.
- **Idempotency keys** scoped to one record + actor; replay with different draft/decision/actor →
  409, exact replay is a no-op (no double-apply).
- **"Reviewed", not "approved":** the review action explicitly never changes a price/quantity
  anywhere — pure shadow. Carry this language over.
- **Staleness:** a review/accept against a superseded artifact → 409.

### 4.8 Governance & lineage **[REUSE — `reports/artifact_identity.py`, `pipeline/receipt.py`, `api/app.py`]**

Semantic fingerprints (volatile keys stripped so identical rebuilds keep identity) bind
forecast ↔ backtest ↔ policy ↔ replenishment ↔ pricing; publication is an **atomic staged
directory swap** under a cross-process lock with rollback. Serving paths validate the full graph;
**stale → HTTP 409, missing/corrupt → 503**. → the Governance tab's "version traceability 100%",
"back-testing coverage 100%", and the Action Center's retraining queue.

### 4.9 Disclosure / honesty guardrails **[REUSE — non-negotiable]**

- Backtests are **historical replay**, scenarios are **model-implied projections** — never
  labeled as observed experimental lift.
- Pricing is **observational**, not causal elasticity.
- Any synthetic fallback (cost, supplier, stock) must be provenance-labelled and never presented
  as a client fact. It may power only a separately gated, visibly synthetic demo/scenario;
  it cannot satisfy a client-actual required-field gate or enter client metrics/decisions.
- Shadow-only: no PO, price change, or ERP transaction is ever sent.

---

## 5. Part D — Reuse vs build-new summary

| Capability | Status |
|---|---|
| Canonical `retail_v1` core + adapter patterns, versioned as `retail_v2` | **[REUSE + EXTEND]** |
| Core entities (versioned sales/money/adjustments/fulfillments, products, locations, calendar, prices, stock, suppliers) | **[REUSE + EXTEND]** |
| Point-in-time (`known_as_of`) + weekly feature build | **[REUSE]** |
| LightGBM horizon-quantile forecaster + Croston routing + blend | **[REUSE]** (extend to 26-wk horizon) |
| Baselines + Forecast Value Add | **[REUSE]** |
| Safety-stock / reorder / simulator | **[REUSE]** |
| SHAP driver attribution | **[REUSE]** (+2 new driver groups) |
| Price-response (Poisson GLM + EB) | **[REUSE]** |
| Data-quality battery, acceptance gates, service-level calibration | **[REUSE + EXTEND]** |
| HITL approval/override/audit/idempotency, lineage fingerprints, 409/503 | **[REUSE]** |
| Competitor price/availability feed | **[NEW]** |
| Weather feed (actual + forecast) | **[NEW]** |
| Local-event feed (sub-national) | **[NEW]** |
| Macroeconomic index | **[NEW]** |
| FX rates (reporting/display conversion) | **[NEW]** |
| Forecast-version records + Compare-Versions | **[NEW]** (fingerprints exist; add version table) |
| Planner-adjustment records with reason codes + value-added flag | **[NEW]** |
| Per-series confidence % + data-quality class surfacing | **[NEW]** (compute from existing) |
| Competitor/weather driver groups + uplift sensitivities | **[NEW]** |
| Governance SLA tracking + drift/freshness metrics surfacing | **[NEW]** (governance exists; add SLA clock) |
| Longer horizons (13/26 wk) | **[NEW]** (extend existing forecaster) |

---

## 6. Part E — Recommended pilot data extract

Mirror the existing client-data guidance (`../retail_ai/docs/retailer_data_poc_guide.md`) for the new PoC:
20–50 SKUs across several categories; 2–5 stores; **18–24 months** of daily history; a mix of
fast / slow / intermittent / new products; promoted and non-promoted periods; genuine posted-
price changes; actual current stock, open orders, cost, and supplier terms for the same universe;
**plus the new feeds** — competitor prices/availability, weather (with forecast), local events,
macro index — for the same stores and window, each with a defined `known_as_of`. Add a data
dictionary defining units, currency, tax basis, and availability semantics per entity.

---

## 7. What to decide before build

1. **Horizon strategy** — extend the LightGBM horizon set to 26 weeks vs add a weekly→monthly
   aggregation layer for the 13/26-week views.
2. **Competitor data source** — scraped/panel/third-party, and the SKU↔competitor match key
   (this is the hardest new feed to source reliably).
3. **Weather granularity** — store vs region, and the forward-weather provider (with `known_as_of`).
4. **Driver attribution method** — SHAP on the LightGBM model vs the transparent blend
   decomposition (the PoC keeps both; pick the primary for the UI).
5. **Confidence definition** — the exact P90–P50-spread → confidence-% formula for the workbench.
6. **Accuracy definition** — lock `accuracy = 100·(1 − WAPE)` (or chosen variant) in methodology.

---

## 8. Other screens — data, models & guardrails

Sections 1–7 establish the canonical spine and the REUSE/NEW convention. Below, each
remaining screen is summarised by what it *adds*. The foundation entities in §2.1 + the models
in §3 + the guardrails in §4 are assumed and not repeated; only the **new data points**,
**new models**, and **screen-specific guardrails** are called out. Dashboard aggregates use the
tenant reporting currency (**INR** for this PoC); source facts retain exact local currency and
cross-market reporting conversion is derived separately. All actions are **shadow-only**
(§4.9) — the dashboard's "Send to ERP", "Approve", "Publish" etc. are demo toasts, and a real
PoC keeps them shadow (reviewed ≠ executed).

### 8.1 Pricing cluster

All rows carry `market_id` and local `currency_code`. Revenue-based columns can be populated from
price history and elasticity alone; current/expected margin, margin impact, margin floors and
margin optimization remain unavailable until the temporal cost capability passes for that
market/currency.

**Price Recommendations** — SKU×store price-action workbench (Increase/Reduce/Hold) with tiered approval.
- Grain: one recommendation per SKU×store. Columns: Action, Current, AI Price, Change %, **Competitor price [NEW]**, Stock Cover, Forecast Demand, Current/Expected Margin, Revenue/Margin Impact, **AI Reason [NEW: explanation string]**, Confidence, Status, Owner.
- **NEW data:** competitor price; AI-reason string; priority tier; owner assignment; approval-SLA clock (open/avg-age/target per tier); adoption %; predicted-vs-realized variance; price-recommendation version records; a `channel` dimension (new relative to the M5 `retail_v1` contract; `retail_v2.locations` includes it).
- **Guardrails:** margin floor 12%; max change 5%/cycle; tiered approval (≤5% Category Mgr / 5–10% Pricing Mgr / >10% Business Head); confidence gate; protected/strategic SKUs = manual-approval-only; promotion-overlap block; SLA-breach tracking; rollback record + full audit; candidates clamped to observed price range.
- **Models:** REUSE elasticity (`price-response-poisson-eb-v1`), forecast, reorder; **NEW** competitor-response model, markdown/clearance-response, predicted-vs-realized variance (drift) monitor.

**Price Simulation** — single-product what-if (Current / Proposed / AI-Optimal on units, revenue, margin, ending stock).
- **NEW data:** proposed-price input; competitor-response toggle; best/worst-case demand band; AI-optimal price output object; inventory-objective switch (Margin Protection vs Clearance).
- **Guardrails:** minimum-margin constraint on the optimizer; stock-out risk must stay "Low"; scenarios labelled model-implied projections, not lift.
- **Models:** REUSE elasticity + simulator + reorder; **NEW** best/worst demand banding + a margin/revenue optimizer subject to margin + stock constraints.

**Competitor Monitor** — ingest, product-match, and respond to competitor prices/promos/availability. **Almost entirely NEW.**
- **NEW data (core):** `competitor_prices` feed — competitor name, matched product, competitor price, **availability {In/Out/Low}**, last-updated, **match-confidence %**, **match-status {Matched/Review/Rejected}**, difference %, match key; competitor promotion detection; the match attribute set (**brand, model #, title, category, colour, size, capacity, pack qty, GTIN/UPC/EAN, images**); alert-rule records (trigger, threshold, direction, scope, severity, recipients, action); per-competitor connection config (type, URL, collection method {API / approved web / CSV-SFTP / manual}, refresh, currency, compliance flag).
- **Guardrails:** match-confidence threshold — **low-confidence matches stay in review and cannot auto-trigger a price action**; legal/compliance validation on competitor-data acquisition; alert thresholds (gap >5%, new discount >10%, →OOS); competitor price feeds a *bound*, not an automatic price change.
- **Models:** **NEW** product-matching model (attribute + confidence scoring); competitor-response recommendation logic; availability-signal → the "Competitor availability" demand driver (§3.4).

**Promotion Planner** — plan/simulate/optimize promotions (which products, depth, uplift, required stock, margin, cannibalisation, target segment).
- Grain: one promotion. Columns: type, objective, offer/depth, period, scope, segment, uplift, revenue, margin, required stock, **cannibalisation risk [NEW]**, status, owner.
- **NEW data:** promotion records + mechanics (**type {%, Fixed, Bundle, BOGO, Member price, Clearance}**, objective, discount depth, scope, customer segment, approval route); expected uplift %, revenue uplift ₹, margin-impact pts, cannibalisation %, sell-through improvement; **customer-segment mix (Loyalty / High-value / Lapsed / Broad) [NEW — needs a customer/segment feed]**; bundle/complementary relationships; promotion-calendar + conflict/overlap records.
- **Guardrails:** margin floor on promo depth; cannibalisation-risk ceiling; **inventory-readiness gate** (can't go live without stock coverage); promotion-overlap/conflict + customer-fatigue checks; tiered approval (Category Mgr / Pricing Mgr / Finance + Business Head); customer-eligibility validation.
- **Models:** **NEW** promo-uplift, cannibalisation, bundle/complementary-demand, and segment/conversion models; REUSE forecast (baseline), reorder/simulator (required stock, sell-through).

### 8.2 Inventory cluster (Overview + 6 sub-screens)

Overview + Store, Warehouse, Ageing, Transfers, Valuation, Expiry/Waste. These extend the M5
`retail_v1` single-snapshot model into a **multi-echelon inventory domain**.
- **NEW data domains:**
  - **Multi-echelon location master** — store, online, **warehouse/DC** and 3PL as first-class
    locations (`retail_v1` had stores only). **In-transit is a shipment/inventory state on a
    lane or destination, not a location type.**
  - **In-transit / inbound shipments** — count, value, delayed flag, expected receipt; **dock-to-stock** time; warehouse **capacity/utilization**, **fill rate**, **blocked/quarantined stock**, **delayed receipts**.
  - **Inventory buckets** — **committed, reserved, damaged/blocked** and
    **Available-to-Promise**. ATP is either an authoritative source state or a profile-declared,
    reconciled bucket formula; there is no universal subtraction rule across platforms.
  - **Lot/batch + expiry** — batch id, expiry date/window, **inventory age from receipt date** (current `stock_snapshots` has no receipt/lot date), waste ₹ actuals.
  - **Valuation** — Net Realizable Value, markdown provision, obsolescence provision, **ERP↔WMS variance**, cost-missing / negative-inventory control flags.
  - Derived: Days-of-Supply, availability %, overstock %, stock turn, health class {Healthy/At-Risk/Overstock/Understock/Out-of-Stock}.
- **Guardrails:** stock-turn target; ageing action ladder (0–30 monitor → 90+ markdown); **overstock 60-day / dead-stock 120-day** thresholds; **negative inventory & missing cost = critical data-quality violations** (§4.1); NRV ≤ gross + provision-posting requirement; ERP/WMS reconciliation tolerance; controlled-markdown depth bounded by pricing floors (§4.6).
- **Models:** REUSE Days-of-Supply (reorder + P50 forecast), stock-out/inventory-reduction scenarios (simulator), ABC/health classifier; **NEW** ageing/markdown engine, expiry/waste engine, provisioning/NRV model, ERP-reconciliation, ATP/inventory-position, warehouse-ops KPIs.

### 8.3 Replenishment / Planner cluster

Replenishment Planner + Suggested Orders, Supplier Planning, Safety Stock, Allocation & Fulfillment, Exceptions, Stock Health.
- **Replenishment Planner** (core): grain = one suggested order per SKU→destination. Columns: Current Stock, Forecast Demand, **Safety Stock**, Suggested Qty, Source, Lead Time, Expected Receipt, Order Value, Service Impact, Confidence, Status. This is the direct UI over the existing reorder engine (§3.3).
  - **NEW data:** source typing {DC / Supplier PO / warehouse transfer / inter-store / expedited}; expected-receipt date; **service-impact pts**; per-row confidence %; **budget ceiling**; supplier-capacity-confirmed flag; **ERP transmission status/failure**.
  - **Guardrails:** approval tiers (planner → supply-chain → finance; replenishment order → Demand Planner + Manager); **MOQ / pack-multiple** compliance; **within-budget** cap; approved-forecast-coverage gate; supplier-capacity confirmation; suggested qty bounded ≥MOQ, pack-multiple, ≤ order-up-to; **shadow-only "Send to ERP"** (no PO actually sent).
- **Supplier Planning:** **NEW** supplier capacity / capacity-confirmed %, **On-Time-Delivery history**, **lead-time variability**, supplier-risk score, alternate-source mapping → feeds the lead-time-variability component of safety stock (28% of the driver mix).
- **Safety Stock:** policy-segment records (current vs recommended value + impact). UI shows targets A 98% / B 95% — **the config point** vs the PoC's audited `policy.yaml` A 0.96 / B 0.90 / C 0.80 (§4.5, calibration 5% + holdout 95%). "Approve Policy" = lead/admin-gated `policy_edits` (audited).
- **Allocation & Fulfillment:** **NEW** allocation pool, store demand/requests, allocated qty, shortfall, **allocation rule {Revenue+service-level, Demand-weighted}**, priority tier → **NEW** constrained-allocation optimizer.
- **Exceptions:** REUSE `exceptions`/`exception_notes`/`exception_status_history`/`audit_log`; **NEW** enrichment: exception types (budget-overrun, supplier-capacity, ERP-failure), business-impact ₹, owner role, SLA age clock, recommended resolution.
- **Stock Health:** SKU×store triage {Overstock/Understock/Near-Expiry} with financial exposure + action {Markdown, Transfer, Replenish, **Stop Replenishment**} and approval route.
- **NEW model across cluster:** transfer/network-rebalancing optimizer, supplier-risk/OTD model, lead-time-variability model.

### 8.4 Analytics & Admin

**Performance Insights** — adoption + value + model quality. **NEW:** AI-vs-control-store cohort tagging; **drift score**. REUSE: `adoption_metrics`, WAPE/bias, FVA.

**Reports & Exports** — REUSE all report content (over `retail_v1` + backtest + `price_recs` + audit/lineage); **NEW:** report templates, schedules, recipient lists, delivery frequency. Guardrail: RBAC on who can schedule/export; audit the export of governance/audit data.

**Alerts & Notifications** — **NEW:** alert-rule records (name, category, trigger, threshold, owner, priority, ack/assign state) + **data-freshness clock**. Triggers REUSE the reorder engine + `exceptions`. Thresholds: 60-day overstock, 7-day stock-out window, 3-hour feed staleness.

**Data Management** — **NEW:** immutable `data_sources` configuration (type
{API/Database/SFTP/CSV/Parquet/JSONL/External API}, refresh cadence and
profile/adapter/transform versions) plus runtime `ingest_runs` (raw/curated manifests,
reconciliation totals, last refresh, record counts, per-gate quality %, capability mask and
status). REUSE and extend the quality battery (`ingestion/quality/`) +
`quality_violations`. Guardrail: any promoted capability has zero critical violations in its
full two-gate run; fail closed when `known_as_of` cannot be defensibly derived from native,
extract or immutable landing evidence; synthetic labelling is never hidden.

**Model Management** — three model families map exactly to §3 (Demand Forecast, Price Elasticity, Stock-out Risk). REUSE MLflow + artifact fingerprints. **NEW:** model-drift/monitoring records + **drift threshold 0.15**, deployment status {Production/Review}, retraining schedule {Weekly / Monthly / On-Drift}. Governance callout enforces: min margin, max price move, protected SKUs, human approvals, explainability, audit — all before "Production".

**User Management** — **NEW: full RBAC** (users, roles, scope {category/region/store/enterprise}, approval limit, status {Active/Restricted/Invited}). The named-**actor** plumbing (`approvals`, `audit_log`, `policy_edits`, `price_rec_reviews`) is REUSE; identity/role/scope management is new. Approval limits map to §4.7 tiers.

**Settings** — this screen **is the guardrail-config surface**: Minimum Margin, Maximum Discount, Maximum Price Increase, Min Days Between Changes, Forecast Horizon, Service Level Target, Overstock/Dead-Stock thresholds, Approval-Workflow tiers, currency/timezone/fiscal-year. **NEW:** persisted, versioned, **audited** global dimensionless defaults plus explicit market/currency policy overrides; each value maps to an existing REUSE config (`pricing_rules.yaml`, `policy.yaml`, `HORIZONS`, `workflow_service.py`). Absolute prices, steps and endings are edited only in a selected market/currency context. Every edit → `policy_edits` (lead/admin-gated). *Note the UI demo values differ from the strict PoC values (20% vs 12% margin floor, 10% vs 5% max move, flat 95% vs A/B/C, 12-wk vs 26-wk horizon) — treat the UI numbers as demo defaults, not the enforced policy.*

### 8.5 Consolidated NEW data domains (whole dashboard)

Beyond the demand-forecast feeds in §2.2–2.3, the other screens require:

| Domain | Used by |
|---|---|
| Competitor prices + availability + product-match | Competitor Monitor, Price Rec, drivers, scenarios |
| Promotion records + mechanics + cannibalisation | Promotion Planner, promo driver |
| Customer / loyalty segments | Promotion Planner (targeting) |
| Multi-echelon node master (store/online/DC/3PL) + in-transit shipment state | All inventory + replenishment |
| Warehouse inventory & ops (capacity, fill, dock-to-stock, blocked) | Warehouse Inventory |
| In-transit / inbound shipments | Inventory Overview, Warehouse |
| Reserved / damaged / ATP buckets | Inventory Overview, Store Inventory |
| Lot/batch + expiry + receipt-date age | Ageing, Expiry/Waste, Stock Health |
| Transfer orders | Transfers, Replenishment |
| Allocation pool + rules | Allocation & Fulfillment |
| Valuation / provisions + ERP↔WMS variance | Inventory Valuation |
| Supplier capacity / OTD / lead-time variability | Supplier Planning, Safety Stock |
| Budget ceilings + ERP transmission status | Replenishment, Suggested Orders, Exceptions |
| RBAC (users/roles/scope/approval limits) | User Management, every approval |
| Data-source connection registry + field mapping | Data Management |
| Model-drift records + retraining schedule | Model Management, Performance Insights |
| Alert rules + data-freshness clock | Alerts |
| Report templates / schedules / recipients | Reports |
| Editable + versioned guardrail-config object | Settings |
| FX rates (reporting/display conversion) | All cross-market money figures |

---

## 9. Synthetic data generation

> **Where this runs:** initially in the isolated, extract-ready `datagen/` package; it may later
> move to a separate repo. It owns its own scenario/source-data specification and imports no
> `contracts/`, `ingestion/`, `ml/` or `api/` code.
>
> **What it publishes:** Shopify-shaped, Business Central-shaped and external/companion source
> datasets in one selected authoritative CSV/Parquet format, exactly one all-source
> `source-run.duckdb` browsing mirror, a
> generator-owned source-run manifest and hidden causal truth. It never publishes canonical
> `retail_v2` fixtures.

The M5 PoC generated realistic retail data in two layers that remain useful **implementation
references**, not downstream contracts:

1. **Demand/price/calendar generator** (`scripts/generate_synthetic_extension.py`) — produces
   the raw sales curve, prices, and calendar, with **pandemic and weather demand models**.
2. **Business-entity synthesis** (`data/ingest_m5.py`) — where the *operational master data*
   the dashboards actually consume (`cost`, `pack_size`, suppliers, stock, `promo_flag`) is
   synthesized on top of the sales data. **This is where the "what's mandatory" answer lives.**

### 9.1 How demand is synthesized

Per SKU×store×day units are a **Poisson draw** around a mean built from multiplicative factors:

```
units ~ Poisson( base × level × trend × gate × pandemic_mult × weather_mult )
```

- **base (seasonality + day-of-week):** *borrowed from a real template year* — each synthetic
  date maps onto a real historical date (same month/day, weekday-aligned) so weekly and annual
  shape are realistic without hand-coding seasonality. For a greenfield PoC with no real base,
  you'd replace this with an explicit seasonal profile (e.g. weekly Fourier terms + festival
  bumps for the Indian calendar — Diwali, Holi, EOSS, monsoon, wedding season).
- **level:** per-series scale anchor.
- **trend:** per-department deterministic growth (decline into the past, growth forward).
- **gate:** launch/retirement + intermittency. Ordinary products use a configurable cold-start
  ramp. Flagship successors use a launch spike/decay plus substitution, while the predecessor
  remains sellable at sharply reduced demand through markdown, clearance and final fire-sale
  runout. A series stays zero only before launch or after actual discontinuation.
- **pandemic_mult / weather_mult:** see §9.4.

Prices are a separate stream: real anchor × cumulative inflation index × **promo dips**
(≈10% of weeks get a 0.75–0.90 price multiplier). `promo_flag` is then *derived*, not drawn.

### 9.2 How the reference operational master data was synthesized

In `data/ingest_m5.py`, the following values were generated deterministically. These formulas can
inform source-native Shopify/Business Central fields, but the new generator must not emit these
canonical names as its public contract:

| Canonical field | Synthesis rule (M5 reference) |
|---|---|
| `products.reference_cost` | M5 reference only: `round(category_median_price × (1 − assumed_margin), 2)`; this is a labelled synthetic scenario value, not temporal cost authority |
| `products.pack_size` / `unit` | `hash(sku_id) % 4 → {1,6,12,24}`; `unit = each` iff pack_size = 1 |
| `products.shelf_life_days` | FOODS 21 / HOUSEHOLD 365 / HOBBIES 730 |
| `sales.promo_flag` | `net_price < 0.95 × median(net_price over 28 trailing days)` (**derived from price**, not an input) |
| `sales.known_as_of` | same-day for M5 (a real feed maps its true availability date) |
| `suppliers_leadtimes` | M5 was department-scoped only: `supplier_id = SUP_<dept>`, `lead_time_days = 2 + hash%6` (2–7), `moq = hash%4 → {12,24,36,48}`, `pack_qty = hash%3 → {6,12,24}`. The new source simulation adds category/SKU scope plus explicit destination/origin context; ingestion resolves it to the merchandise-scope and lane grain in §11.1. |
| `stock_snapshots.on_hand_units` | `max(pack_qty, ceil(avg_weekly_units_over_first_28_days × 1.5))`; `on_order = 0`; snapshot at **dataset start + 27 days (28-day burn-in)** so seeded stock never peeks at future demand |

### 9.3 Determinism & safety (carry these patterns over)

- Global integer seeds; per-day RNG seeded by `[seed, date.ordinal]`; all non-random values
  hash-based (md5) — fully reproducible and order-independent.
- **Immutable publication:** staged to a nonce dir, atomically promoted, `run_id = sha256(version + CLI + raw-input-hashes)`; identical reruns reuse the run, changed inputs get a new identity; cross-process lock; inputs re-verified before activation.
- **Boundary validation** on date ranges + a table-coverage guard so a generated calendar can
  never silently miss a lookup-driven event. 68 tests cover calendar ground-truth, the
  pandemic/weather coupling math, determinism, and 8-point publication-failure recovery.

### 9.4 Pandemic & weather demand models (directly relevant to the weather driver)

Both modulate the demand mean via a single multiplier, on synthetic days only:

- **Pandemic** — a declarative registry of events (SARS, H1N1, COVID-19 with 13 phases) →
  per-phase `{selector: multiplier}` where selectors are all/category/dept/product-type and
  the most specific wins; shapes are `spike` (triangle), `plateau`, or `linear`. E.g. COVID
  panic-buying multiplies Toilet Paper ×5, Hand Sanitizer ×7, staples ×1.25–1.5, and
  discretionary ×0.45; later phases add stimulus bumps and an inflation drag.
- **Weather** — per-region daily temperature (climate normal + multi-sine anomaly + noise),
  precipitation/snow, and 15 named extreme events (hurricanes, polar vortex, heat dome). It
  couples to demand by **product type**: warm-weather items (ice cream, cold drinks) scale up
  with positive temperature anomaly (capped ~+45%), cold-weather items (oats, coffee) with
  negative anomaly; storm events drive a prep window (batteries, candles, water ×1.3–1.7) then
  a disruption window (all ×0.85). This is the reference implementation for the dashboard's
  **weather driver** — the new PoC can reuse the anomaly + product-type-sensitivity structure.

### 9.5 How to generate synthetic data for the new PoC

1. **Fix the generator-owned scenario and source contract first.** Its internal simulation state
   uses generator vocabulary. Publishers render the same causal run into Shopify, Business
   Central and companion source objects; ingestion alone maps those objects to §11.
2. **Build dimensions and drivers before demand:** products, locations/DC hierarchy, suppliers,
   calendar/events, regular/promo prices, explicit promotions, competitor observations, weather,
   local events and macro. This preserves the causal relationships the models are expected to
   rediscover.
3. **Localize the base demand model** for Indian multi-category retail: replace M5's borrowed
   template with an explicit seasonal profile (weekly Fourier + Indian festival/monsoon/EOSS
   bumps), per-category base levels, elasticity, and an intermittency/new-product gate.
4. **Use one inventory-consistent event loop.** Draw internal latent demand, receive/dispatch
   supply, compute sellable availability, then render realized non-negative transactions and
   source-native demand/supply-location evidence. Keep lost demand as hidden generator truth and
   a control total rather than allowing orders and stock to contradict each other. Seed opening
   inventory from a burn-in that does not inspect future demand.
5. **Reuse operational synthesis patterns** from §9.2 (stable pack/MOQ/lead-time hashes and the
   independently derived 28-day rolling-median `promo_flag`), localized for Footwear/Apparel/
   Electronics/Beauty. When the valuation/procurement extension is enabled, do **not** use
   price-derived assumed cost as a temporal cost ledger: generate Business Central/ERP
   receipt-shaped events at changing costs and let ingestion/the PoC compute WAC/FIFO as of time.
6. **Synthesize the NEW companion feeds with the same deterministic discipline.** Emit native
   event/observation timestamps where the simulated source naturally has them; ingestion derives
   canonical `known_as_of` plus the entity's declared explicit version or observation identity:
   - **Competitor products/prices/availability** — a market-keyed set per category with matchable
     brand/model/GTIN-like attributes, prices as a noisy function of your own price ± a gap, and
     occasional OOS spells. If the generator keeps match ground truth for evaluation, publish it
     as a test-only artifact; canonical `competitor_matches` remains a PoC output.
   - **Weather** — reuse the anomaly + product-sensitivity shape, keyed to configured market and
     locale/region/store; emit actual and forecast observations and make them affect demand.
   - **Local events** — market×city×date festival/event calendar with demand multipliers.
   - **Macro index** — a slow market×region×week series (e.g. consumption index).
   - **FX rates** — as-of-dated local-currency→tenant-reporting-currency observations.
   - **Promotions & segments** — explicit market-qualified promo records
     (type/depth/period/structured scope) and a customer-segment mix, so the Promotion Planner and
     its uplift/cannibalisation models have inputs.
7. **Publish only source-shaped outputs from one run identity:** Shopify-shaped, Business
   Central-shaped and external/companion datasets in the formats the generator actually supports,
   plus the source-run manifest and hidden truth. Physical format/compression is not a semantic
   hard requirement; ingestion owns supported format adapters.
8. **Golden round-trip acceptance:** land the projections and transform them through
   `ingestion/`. Shopify alone may produce `validated_partial`; a configured Shopify+BC+companion
   composite must produce the capability slice needed by the selected dashboard pages. Compare
   canonical controls and model-relevant outcomes with hidden source/causal truth without making
   the generator understand canonical columns. The generator-vocabulary → canonical expected-
   control translator/oracle is an ingestion-test artifact, versioned with the profile/transform
   under test; it is not imported by or published from `datagen/`.
9. **Keep the same guardrail posture:** deterministic seeds, immutable publication, boundary
   validation and per-output content hashes. Every generated source snapshot passes Gate A; only
   capability-complete data that also passes Gate B may reach `ml/` (§4.1).

### 9.6 Config Builder and multi-market configuration

The HTML Config Builder is the sole supported scenario-authoring surface. Every executable
setting must be visible/editable, conventional YAML is the default import/export and execution
format, and retained JSON exports must resolve to the same object. The
builder must import its own exports for lossless editing and must not hide preset-only country,
currency, format, execution or event fields. The export records each locale-pack ID/version and
materializes the full resolved values and explicit overrides, so a run never changes because a
pack was revised later.

The configuration hierarchy is:

```yaml
specVersion: retail-source-config/v9
identity: {scenarioId: multi-market-demo, scenarioVersion: 1.0.0, masterSeed: 20260101}
time: {startDate: 2025-01-01, endDate: 2025-03-31, generationPartition: month}
retailer: {retailerId: retailer-001, name: Example Retail, reportingCurrency: INR}
markets:
  - marketId: india
    countryCode: IN
    currencyCode: INR
    timezone: Asia/Kolkata
    localePack: "<fully materialized versioned IN pack>"
    catalogPack: "<fully materialized versioned IN catalog pack>"
    assortment: {skusPerDepartment: 36, variantsPerProduct: 3,
                 categoryAssortmentWeights: {grocery-staples: 2.0}}
    demand: {startingDailyOrders: 420, averageLinesPerOrder: 1.8,
             dayOfWeekFactors: [0.90, 0.93, 0.97, 1.02, 1.12, 1.28, 1.24]}
    priceDynamics: {profile: response-rich, priceChangeEventsPerSkuPerYear: 36,
                    annualInflationRate: 0.055, priceEndingAdherence: 0.82}
  - marketId: us
    countryCode: US
    currencyCode: USD
    timezone: America/New_York
    localePack: "<fully materialized versioned US pack>"
    catalogPack: "<fully materialized versioned US catalog pack>"
    assortment: {skusPerDepartment: 36, variantsPerProduct: 3}
    demand: {startingDailyOrders: 420, averageLinesPerOrder: 1.8,
             dayOfWeekFactors: [0.94, 0.97, 1.00, 1.04, 1.15, 1.22, 1.12]}
    priceDynamics: {profile: response-rich, priceChangeEventsPerSkuPerYear: 36,
                    annualInflationRate: 0.032, priceEndingAdherence: 0.82}
stores:
  - {storeId: mumbai-01, marketId: india, city: Mumbai,
     warehousePriority: [india-wh-01]}
  - {storeId: new-york-01, marketId: us, city: New York,
     warehousePriority: [us-wh-01]}
warehouses:
  - {warehouseId: india-wh-01, marketId: india, servesLocations: [mumbai-01],
     openingStockPerSku: 18, openingStockDaysOfCover: 21}
  - {warehouseId: us-wh-01, marketId: us, servesLocations: [new-york-01],
     openingStockPerSku: 18, openingStockDaysOfCover: 21}
sourceInstances:
  shopify:
    - {shopId: shopify-in, marketId: india, storeIds: [mumbai-01]}
    - {shopId: shopify-us, marketId: us, storeIds: [new-york-01]}
  businessCentral:
    - {companyId: bc-india, legalEntityId: india-co, warehouseIds: [india-wh-01]}
    - {companyId: bc-us, legalEntityId: us-co, warehouseIds: [us-wh-01]}
catalog:
  generation: {mode: generated, incumbentProductPct: 1.0, launchHistoryDays: 365,
               launchSpreadPct: 0.0, variantLaunchSpreadDays: 14,
               discontinueRate: 0.03, replacementLinkRate: 0.0,
               lifecycle: {defaultLaunchProfile: linear-ramp,
                           launchSpikeMultiplier: 4.0, launchSpikeDays: 14,
                           preLaunchAnticipationDays: 45, substitutionRate: 0.65,
                           runoutMonths: 18, clearanceDiscountPct: 0.25,
                           fireSaleFinalDays: 30, fireSaleDiscountPct: 0.45}}
pandemics: [] # phased H1N1/COVID/etc. entries are available in the 20-year preset
operations:
  inventory: {replenishmentCycleDays: 7, supplierLeadTimeDays: 7,
              replenishmentDemandBufferPct: 0.20, stockoutSkuRate: 0.0}
  features: "<all source-fidelity feature switches are explicit>"
output: {rootDirectory: output, publicFormats: [parquet, duckdb],
         compression: zstd, writeHiddenTruth: true, overwrite: false}
```

This is an abbreviated, readable excerpt; the Config Builder's resolved v9 YAML/JSON—including
the complete locale/catalog packs and every operations field—is the executable contract.

`categoryAssortmentWeights` is an optional per-market map owned by the Config Builder. Values
are relative category-depth weights; unspecified categories use `1`. Omitting the map preserves
the uniform catalog and current presets exactly. Explicit product templates remain mandatory
catalog rows; the weights distribute the generated remainder.

`openingStockDaysOfCover` is an optional warehouse boundary control. A positive value derives
opening stock from the configured store assortment and velocity plan, with
`openingStockPerSku` retained as the minimum floor. It represents retailer history before the
extract begins; it is not reused as a replenishment truth floor. In-run purchase decisions use
observed sales divided by days the SKU/location was available to sell, multiplied by the
explicit `replenishmentDemandBufferPct`; hidden lost sales and `_truth/` are never inputs.

Store and warehouse objects—not aggregate counts—are authoritative. A store may have an approved
warehouse priority list; one warehouse may serve multiple stores; a scenario may also use a
single warehouse. Source-system instances are also explicit: the builder maps Shopify shops and
Business Central companies to the markets/locations they publish instead of assuming one global
shop, company, currency or tax context.

The `response_rich` profile is generator vocabulary: it controls assortment size, price-event
frequency, latent price response and noise, but it does not encode or import downstream
`retail_v2`/ML gate thresholds. The primary showcase uses it in both markets and Phase 5 verifies
the resulting eligible-series count. A separate `pricing-evidence-sparse` preset uses a small
assortment and/or too few price changes so the UI can demonstrate a reason-coded fail-closed
market without making the main multi-market pricing round-trip empty.

Supported packs are `IN`, `US`, `GB` and `DE`. `GB` may be labelled “UK” in the UI. `DE` is the
initial European representative because Europe itself is not a tax, holiday, timezone or postal
jurisdiction. Additional EU member-state packs are data additions, not generator-code branches.

Each locale pack owns:

- currency symbol/code/minor-unit exponent, native price bands/endings and display grouping;
- tax-inclusive/exclusive basis and category/jurisdiction rate tables;
- fiscal defaults, valid timezones, address/postcode/Faker locale;
- reviewed fixed and lunar holiday/sale-period date tables;
- climate profile and locale/category seasonality.

Country selection also resolves a versioned **rich catalog pack** owned by `datagen/`. These packs
contain real brand and product-line reference identities, source price bands, materials, option
values and barcode behavior; all generated transactions, inventory, prices, costs and demand
remain synthetic. The normalized default hierarchy has 10 departments and 41 categories,
including Groceries and family-specific shelf-life behavior. The generator adapts the reusable product/variant
model and deliberately partial option matrices from `../retail-synthetic-data-generator`, while
replacing its generic `Category Word N` titles and `SKU-P...-V...` identifiers. A product has a
stable product code; each sellable variant has a distinct stable SKU, valid EAN-13/UPC-A barcode,
option combination, price/cost, popularity, elasticity, return propensity and lifecycle. The
Config Builder exposes generated/hybrid/explicit catalog modes, exact sellable-SKU targets,
variants per product, SKU prefix/lifecycle controls, per-category behavior and complete explicit
product definitions. These remain generator/source concepts and do not import canonical product
or SKU rules. The opening-incumbent share is explicit: long histories start with products already
on sale, then introduce other products and independently dated variants during the run. Product
replacement links and lifecycle gates prevent inventory, prices or orders before a SKU launch or
after its discontinuation. A successor launch does not itself discontinue its predecessor: the
builder exposes spike/decay, anticipation, substitution, runout, markdown, clearance and
fire-sale controls.

Source spec v9 accepts complete date ranges within the materialized locale-pack coverage. The
current packs cover `2005-01-01` through `2026-12-31` (22 complete years), and the checked-in
2005–2024 preset exercises the minimum 20-year requirement with monthly partitions, compound
growth/inflation, ongoing catalog launches/replacements and phased pandemic/supply disruption.
Pandemics are config data: an effect mode distinguishes synthetic shocks from timeline-only
outbreak evidence; overlapping phases can alter demand, traffic, costs, supplier lead times,
inventory loss and department/category/catalog-family/channel response. The model adapts the
H1N1/COVID phase semantics from `../retail_ai` and the supply-shock mechanics from
`../retail-synthetic-data-generator`.

Locale selection must drive Shopify `taxes_included`, shop/market currency and tax lines;
Business Central country/region, VAT/tax area and fiscal setup; source amounts; holidays; weather;
and demand. A flat global `taxRate`, first-country lookup or one global timezone is invalid.

Reuse the existing builder's card layout, presets, category/event editors, timeline, run estimate,
preflight panel and download flow. Replace its flat scenario object and manual YAML serializer:
currently countries/currencies/formats are hidden preset values, locations/warehouses are counts,
“Holiday peak” is only a generic dated multiplier, YAML/JSON are not equivalent, and the Python
signal generator uses the first country with hard-coded US holidays. The new builder contract
must eliminate those behaviors rather than preserve them for compatibility.

### 9.7 Required versus screen-completeness generator scope

The first forecast/revenue-pricing round-trip requires products/variants, explicit locations, demand/
orders, prices/promotions, usable inventory observations, locale-aware Shopify/BC projections,
external signals that affect demand, a source-run manifest and hidden truth.

That first pricing round-trip is **revenue-objective only** unless a temporal receipt/cost
projection is explicitly enabled and passes the cost capability gate. Margin amounts,
margin-floor enforcement and margin optimization remain unavailable—not silently synthetic—
until canonical cost-as-of exists. A generated cost ledger may later enable a clearly labelled
synthetic margin scenario; only provenance-matched client cost can enable a client-actual margin
objective.

Source spec v9 implements the following as config-driven source fidelity. They remain
**non-blocking capabilities** for a consumer that only needs the first forecast/revenue-pricing
round-trip:

- detailed split fulfillment, status histories and processed-return evidence;
- successful/failed refund transactions and webhook/HMAC conformance fixtures;
- every named Shopify inventory state;
- complete PO/receipt, inbound-shipment, batch/expiry and supplier-performance histories;
- full promotion-SKU/customer-segment history and realistic competitor-product matching;
- warehouse capacity/fill/dock-to-stock/blocked-stock, ageing/waste/valuation comparison,
  transfer-lane, allocation-pool and supplier-capacity/budget source evidence;
- one selected authoritative CSV/Parquet source format plus exactly one all-source
  `source-run.duckdb` browsing mirror.

The v8 simulation is closed-loop: purchase orders use SKU/location demand, inventory position,
pending receipts, supplier lead-time/fill behavior, MOQ and pack size to replenish stock over
time; receipts, sales, transfers, waste and adjustments post a complete Business Central-shaped
item ledger that reconciles to the latest inventory quantities. Nominal prices inflate from each
SKU's launch-era price while demand elasticity compares against its inflation-adjusted reference,
so inflation does not accidentally cancel real demand growth. Each operation capability is
controlled by its explicit `operations.features` switch.

The DuckDB file contains public source tables and restricted hidden truth when truth is enabled,
so the whole file is permissioned as restricted. `source_object_catalog` maps tables back to
authoritative CSV/Parquet paths, formats, compression, hashes, row counts and access classes. It
is an all-text convenience mirror, not a canonical or ML-ready database. A generated
`source-schema.json` field dictionary (also exposed as DuckDB table `source_schema`) documents
the published source fields without importing downstream schemas. Ingestion supports both
authoritative choices and may use a datagen-DuckDB profile for the PoC only when restricted truth
is excluded and authoritative object lineage is preserved. JSONL remains an ingestion adapter
concern when a retailer supplies it.

Datagen does not create forecast/model records, recommendations, transfers/allocations proposed
by the engines, exceptions, approvals, users, alerts, model registry, reports or audit rows.
Those HTML-page records are derived or runtime-owned by `ml/`, `api/`, `db/` and `ui/`.

Likewise, a retailer source is not rejected merely because it lacks a config hash, native
`known_as_of`, availability versions, observation timestamps or capability manifest. The
versioned ingestion profile derives defensible metadata from source/extract/landing evidence and
records provenance, or quarantines ambiguity. Those are ingestion responsibilities.

---

## 10. Mandatory data elements & derived-metric dependencies

Your margin example generalises to a rule: **almost every headline number on the dashboard is
*derived*, and each derived metric has a hard list of upstream fields that must exist.** If an
upstream field is missing, the metric can't be computed honestly (and the PoC fails closed
rather than fake it). This section is the authoritative capability-dependency answer; §11 and
the future machine-readable `contracts/retail_v2` definition are authoritative for entity
schemas.

### 10.1 The canonical mandatory vs optional contract

These requirements apply **after source transformation**, at the canonical boundary. Raw-source
requirements live in the versioned dataset profile because a Shopify order export, a retailer POS
file and an ingestion-owned canonical unit fixture have different physical schemas and grains.
Enforced by `ingestion/quality/contracts.py` — a NULL or missing REQUIRED canonical column raises
at ingestion:

| Entity | **REQUIRED** | Optional |
|---|---|---|
| `sales` | `sku_id, store_id, date, sales_version, units, net_sales_amount, currency_code, known_as_of` | `net_price, gross_sales_amount, discount_amount, tax_amount, promo_flag` |
| `sales_adjustments` | `adjustment_id, adjustment_version, sku_id, store_id, sale_date, event_date, event_type, known_as_of` | conditional `units` or `amount + currency_code`; `source_sale_id, source_parent_event_id, reason_code` |
| `sales_fulfillments` | `fulfillment_line_id, fulfillment_version, source_sale_id, sku_id, demand_location_id, supply_location_id, sale_date, fulfilled_at, units, known_as_of` | `shipment_id, carrier_status` |
| `products` | `sku_id, dept_id, category, sub_cat, pack_size` | `product_name, brand, shelf_life_days, reference_cost` |
| `locations` | `location_id, type, market_id, currency_code, timezone, region, active` | `name, city, parent_dc, format, channel` |
| `calendar` | `market_id, date, known_as_of` | day attributes |
| `calendar_events` | `market_id, geo_scope_type, geo_scope_id, date, event_name, event_type, known_as_of` | event attributes |
| `suppliers_leadtimes` | `supplier_id, destination_location_id, merch_scope_type, merch_scope_id, effective_from, lead_time_days, moq, pack_qty, known_as_of` | `from_location_id` (null means unmodelled external supplier origin, not wildcard) |
| `stock_snapshots` | `sku_id, location_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | `committed_units, reserved_units, damaged_units, in_transit_units, atp_units, atp_method` |

For every profile, canonical temporal entities require `known_as_of`. A deliberately named
ingestion unit fixture may opt into a same-day assumption. Generated and client-shadow sources
instead use the profile's defensible native/extract/landing-time derivation; client-actual
required business facts cannot be filled by arbitrary profile defaults.

Four nuances that surprise people:
- `sales.units` and `net_sales_amount` are cumulative **fulfilled/realized merchandise quantity
  and exact net merchandise value for the sale date as known at that availability version**.
  Select the latest version at or before the decision cutoff, never sum availability versions.
  `net_sales_amount` is the money-reconciliation authority; aggregated `units × net_price` may
  differ because the row can contain multiple line prices and discounts. Pre-fulfilment
  cancellations never enter `sales`.
  Later physical returns/post-fulfilment cancellations and financial refunds append
  `sales_adjustments`. `sales_adjustments.units` and `.amount` are non-negative reversal
  magnitudes (integer minor units in `currency_code` for amount), never signed values; each event
  has at least one positive
  measure. Coupled source records are decomposed into stable physical and financial child events
  so net-unit and net-revenue views cannot double count them. Any legacy
  `gross_units/cancelled_units/returned_units` columns are derived views, not canonical inputs.
- `products.reference_cost` is optional descriptive master data, **not** the temporal margin
  authority. Cost-dependent capabilities require `purchase_receipts` (or an approved equivalent
  cost ledger) and the derived as-of `inventory_cost`; otherwise they remain unavailable or are
  explicitly labelled synthetic scenarios.
- `locations` is authoritative. For reused demand-model code, ingestion derives a compatibility
  `stores` view for `type ∈ {store, online}` with `store_id = location_id` and carries
  `market_id`, `currency_code` and `timezone`; sales/sell-price demand grains continue to use
  that alias, while inventory/cost/shipment grains use `location_id`. Sales and sell-price
  currency must equal this operating currency; source presentment money is audit-only.
- `sell_prices` isn't in the universal required set, but **pricing/elasticity
  screens need a real price panel** (see §10.2) — so they're mandatory *for those capabilities*.

### 10.2 Derived-metric dependency map

To your question — *"to calculate margin do we need purchase price?"* — **yes: margin needs unit
cost (your purchase price / landed cost) and selling price.** Here is the full map:

| Derived metric | Formula (as implemented) | Mandatory upstream fields |
|---|---|---|
| **Historical net units / revenue (as-of)** | latest fulfilled units/value minus latest typed unit/refund reversals (§11.0) | versioned `sales.units/net_sales_amount` + versioned `sales_adjustments` |
| **Margin** | `margin_bp = ((price − cost) × 10000) // price` | `sell_prices.net_price` (or current price) **+ as-of `inventory_cost`** |
| **Revenue (projected)** | `units = p50 × (price/price0)^beta` ; `revenue = units × price` | forecast **P50** + price + **elasticity β** |
| **Gross margin ₹** | `(price − cost) × units` | price + **cost** + units/forecast |
| **Markdown suggestion** | hold when `cover_days > 21`; `markdown_pct = 0.10` | forecast P50, `trailing_avg`, `cover_days = (atp+on_order+in_transit)/avg_daily` |
| **Safety stock** | `RSS(P90−P50 over lead+review) × Φ⁻¹(SL)/Φ⁻¹(0.90)` | forecast **P50 & P90** + `lead_time_days` + `review_period` + `service_level` |
| **Reorder point / order-up-to** | `demand_over_lead(P50) + safety_stock (+ cycle_stock)` | above + ATP + disjoint on_order/in_transit + MOQ + pack_qty |
| **Demand at risk / stock-out proxy** | target = `P90`; risk when `actual > target`; exposure `= target × cost` | forecast **P90** + reconciled inventory position/actual demand + **cost** (to value it) |
| **ABC class** | `annualized_value = trailing_avg_weekly × 52 × cost`; A≤0.80, B≤0.95 cumulative | forecast trailing avg **+ cost** |
| **Price elasticity (β)** | Poisson GLM: `log E[units] = a + β·log(price) + controls` | **`sell_prices` panel with real variation** + `sales.units` |
| **Forecast (P50/P90)** | LightGBM horizon-quantile over the weekly feature set | `sales.units` with **≥52 wk** history + calendar + prices + `known_as_of` |
| **Forecast accuracy / bias / FVA** | WAPE, bias, vs-MA13 improvement over rolling origins | forecast + realized `units` + `known_as_of` (point-in-time) |
| **Stock cover / days-of-supply** | `inventory_position / avg_daily_demand` | ATP + disjoint on_order/in_transit + forecast |

**The elasticity/pricing price panel is itself gated** — per usable series the PoC needs
≥52 observed price weeks, ≥90% coverage, ≥3 distinct price levels, ≥5 transitions, ≥2 obs per
level, prices within the freshness limit, and ≥20 qualified series overall. Flat or sparse
prices legitimately yield **no** recommendations.

### 10.3 The cost / margin rule (important for a client PoC)

- Margin is only as trustworthy as `cost`. In the M5 PoC cost is *synthetic* (back-derived from
  an assumed category margin), so **every margin figure is explicitly labelled a "synthetic
  margin scenario," never a client margin.**
- For a real engagement, the pricing capability **refuses a margin objective unless cost is
  non-synthetic**, is 100% positive, comes from a single declared source, and the declared
  `cost_source_label` matches the physical provenance. Mixed/unverifiable cost fails closed.
- So: to show *real* margin on this dashboard you must supply **actual unit cost** (purchase /
  landed cost, on a declared basis — per-each or per-pack, net or gross, matching the price
  basis). Without it you can still forecast, replenish and optimize revenue. A *labelled*
  synthetic margin scenario additionally requires an accepted generated temporal cost ledger;
  it is never a client-true margin.
- Revenue-objective pricing is independently available when its price/elasticity gates pass.
  Without accepted temporal cost, margin columns and margin-floor/objective enforcement are
  omitted; a reference product cost is never silently promoted to decision-grade cost.

### 10.4 What you must supply to light up each capability

| To populate… | You must supply (beyond the always-required sales/products/locations/calendar) |
|---|---|
| Demand Forecast, accuracy, bias | ≥52 wk (ideally 18–24 mo) daily `units` + `known_as_of` |
| Replenishment, safety stock, cover | `stock_snapshots` with reconciled `atp_units/atp_method`, disjoint on-order/in-transit + destination/lane-scoped `suppliers_leadtimes` (lead, MOQ, pack) + service-level policy |
| Revenue price recommendations / simulation | qualifying `sell_prices` panel + market pricing metadata/rules + price-response evidence |
| Margin fields/objective/floor | actual `purchase_receipts` (or approved temporal cost ledger) → same-currency as-of `inventory_cost`, in addition to revenue-pricing dependencies |
| Price elasticity | the qualifying price panel above (levels/transitions/coverage), evaluated within market |
| Competitor Monitor, competitor driver | `competitor_products` match attributes + competitor price/availability; the PoC produces governed `competitor_matches` |
| Promotion Planner | promotion records (type/depth/period/scope) + customer segments |
| Weather / local-event / macro drivers | weather (actual + forecast), local-event, macro feeds — each with `known_as_of` |
| Multi-echelon inventory, ageing, expiry | location nodes (store/online/DC/3PL) + inbound-shipment state + disjoint inventory buckets/reconciled ATP + **lot/batch + receipt/expiry dates** |
| Valuation | approved temporal cost ledger → as-of `inventory_cost` + provision policy (+ ERP/WMS reconciliation feeds) |
| Multi-market reporting/display | Local-currency facts + as-of FX into tenant reporting currency (INR for this PoC) |
| RBAC, approvals, governance | users/roles/scope/approval-limits + named actors |

### 10.5 Handling cost that changes over time (replenishment at different costs)

Real replenishment buys the same SKU repeatedly at **different costs**, so "unit cost" is not
one number — it's a **time series of purchase layers**, and margin depends on which layer a sale
is attributed to. The M5 PoC sidesteps this: the canonical contract carries a **single current
`cost`** (`schema.md`: "current cost, not temporal cost history"), used as a documented
shadow-margin assumption. **The new PoC must model cost over time** to show a trustworthy margin.

**Worked example — Nike Air Max 270 (NK-AM270-BLK-09), Mumbai:**
- 12 Jan: receive 100 units @ **₹6,000** cost (PO-1)
- 10 Mar: supplier raises price; receive 100 units @ **₹6,600** cost (PO-2)
- April: you sell at ₹10,999. On-hand is a blend of both layers — which cost applies?

| Costing method | Cost applied to an April sale | Margin at ₹10,999 |
|---|---|---|
| **Weighted Average Cost** (moving average) | (100×6000 + 100×6600)/200 = **₹6,300** | 42.7% |
| **FIFO** (oldest layer first) | ₹6,000 until layer 1 empties, then ₹6,600 | 45.4% → 40.0% |
| **Latest / replacement cost** | ₹6,600 | 40.0% |
| Standard cost | fixed planned cost; variance tracked separately | (planned) |

Same sale, three different margins. So the new PoC needs three things:

1. **A cost ledger** — `purchase_receipts` (one row per SKU × location × receipt, with `unit_cost`,
   `qty`, `receipt_date`, `known_as_of`); see §11.2. This is the raw temporal cost history.
2. **A chosen valuation method** — default to **Moving Average Cost** (simple, Ind AS 2 / IFRS
   acceptable, needs no lot tracking); use **FIFO** only where you already track batches/expiry
   (Beauty / perishables), since FIFO falls out of the batch ledger for free.
3. **Cost-as-of resolution** — margin uses the WAC (or FIFO layer) **as of the sale/decision
   date**, never a future cost. `inventory_cost.wac_cost` is the derived current snapshot;
   `products.reference_cost` is descriptive only, and the **receipt ledger is the source of
   truth**. Pricing/replenishment **Order Value** uses the **latest / replacement cost** (what the
   next PO will cost), which can differ from the WAC used for margin — so the schema keeps both
   `inventory_cost.wac_cost` and `purchase_receipts.unit_cost`.

**Guardrail tie-ins:** point-in-time still applies — a receipt's `known_as_of` gates when its
cost enters the WAC, so a late-posted invoice can't retroactively rewrite a margin you already
reported. And §10.3's honesty rule holds: only a **non-synthetic, provenance-matched** cost
ledger unlocks a real margin objective; a generated cost ledger shows a *labelled* margin scenario.

---

## 11. Data schema (`retail_v2`)

This is the **canonical contract produced by `ingestion/` and consumed downstream**. The
generator never materializes it. Retailer/platform/generated source files and objects are
transformed into these entities under a versioned profile and adapter. Direct canonical unit
fixtures, when needed, are owned by ingestion/contract tests. Column tables are compact; full
field semantics will live in the machine-readable contract and data dictionary under
`contracts/`.

### 11.0 Conventions

- **Entity ownership tag:** `[in]` = canonical input produced by ingestion from generated or
  authorized source data; `[poc]` = produced by the PoC at runtime; `[cfg]` = version-controlled
  configuration; `[test]` = evaluation-only truth never exposed as a client fact. Historical
  `[gen]` labels in earlier sections mean `[in]` transformed from locally generated sources.
- **Row provenance is separate from entity ownership.** Use controlled labels such as
  `SYNTHETIC`, `SHOPIFY_ACTUAL`, `SHOPIFY_DERIVED`, `ERP_ACTUAL`, `EXTERNAL_ACTUAL`; a real
  engagement must never present synthetic values as client facts.
- **Keys:** `sku_id`, `store_id`/`location_id`, `supplier_id`, `comp_id` are stable strings.
  `locations` is authoritative. `stores` is a curated compatibility view over demand locations
  (`store_id = location_id` for `type ∈ {store, online}`).
- **Location market context:** every location has `market_id`, operating `currency_code` and
  IANA `timezone`; the stores view preserves them. Canonical sales and sell-price facts use that
  operating currency. Shopify presentment money is audit/display-only; it does not create a
  second pricing currency for a location. Other money domains retain their declared currency and
  must satisfy the capability-specific market/cost conversion policy rather than being inferred
  from location sales history.
- **Dates/times:** business dates are ISO `YYYY-MM-DD`; source events/observations may be
  timestamps. **Every temporal entity carries `known_as_of`**, the earliest defensible
  availability timestamp/date for that fact. It may be later than the business/effective date.
  A late correction appends an adjustment/version and never rewrites what an earlier cutoff knew.
- **Temporal identity has two explicit classes.** Cumulative/correctable facts (`sales`,
  `sales_adjustments`, `sales_fulfillments`) use positive monotonic integer version columns.
  Observational/reference facts use the entity's stable natural key plus its effective or
  observation time and `known_as_of`; at a cutoff, select the latest eligible observation
  declared by that entity. Exact duplicate complete keys are idempotent; divergent payloads at
  the same complete key are quarantined. The word “version” is not used in an entity grain unless
  an explicit version column exists.
- **Scope-field conventions are domain-specific and must not be collapsed into one enum.**
  Single-axis geographic observations (calendar event, weather, local event, macro and
  competitor price) use `market_id + geo_scope_type + geo_scope_id`, where
  `geo_scope_type ∈ {market, region, location}`; region/location IDs resolve inside the market,
  and market-wide means `(market, market_id)`, never unqualified `ALL`. Merchandise rules
  (supplier terms and promotion merchandise targets) use
  `merch_scope_type ∈ {sku, dept, category} + merch_scope_id`, with precedence
  `sku > dept > category`. Promotion applicability is intentionally multi-axis and instead uses
  `promotion_scopes` rows with explicit nullable `region/location/channel` qualifiers:
  qualifiers within a row are ANDed and rows are ORed. RBAC/workflow scope is a separate
  configuration domain named `rbac_scope_type`; it is not a data-scope enum.
- **Sales semantics and key:** `(sku_id, store_id, date, sales_version)` is unique;
  `sales_version` is a positive, strictly increasing integer within the first three fields and
  `known_as_of` is non-decreasing with it.
  `units` and `net_sales_amount` are cumulative non-negative fulfilled/realized merchandise
  quantity and exact merchandise value after discounts but before later refunds for that
  business date/version. At a decision cutoff,
  select the row with greatest `(known_as_of, sales_version)` where `known_as_of ≤ cutoff`;
  never sum versions. `net_price` is a rounded/display unit value and is not the money
  reconciliation authority. Pre-fulfilment cancellations produce no sale; later reversals use
  `sales_adjustments`. Each source profile declares fulfillment and date-attribution policy.
- **Adjustment semantics:** `(adjustment_id, adjustment_version)` is unique and corrections append
  a higher version with non-decreasing `known_as_of`; at a decision cutoff select the latest
  known version per `adjustment_id`,
  ordered by `(known_as_of, adjustment_version)`; never sum versions of the same event.
  `physical_return` and `post_fulfilment_cancellation` require `units > 0, amount = null` and
  reduce net units only. `financial_refund` requires `amount > 0, units = null` and reduces net
  revenue only. Combined source events are decomposed into stable physical and financial child
  IDs under one `source_parent_event_id`; Gate B rejects duplicate measure-kind reversals.
  Values are non-negative magnitudes (amount in the declared currency's integer minor units),
  never signed.
- **As-of net views:** `net_units_as_of` is
  `latest sales.units - sum(latest unit reversals)` for
  `{physical_return, post_fulfilment_cancellation}`; `net_revenue_as_of` is
  `latest sales.net_sales_amount - sum(latest financial_refund.amount)`. Gate B rejects either
  result below zero. This deliberately prevents one return/refund pair from reducing both
  measures twice.
- **Fulfillment bridge:** `(fulfillment_line_id, fulfillment_version)` is unique and versioned
  under the same cutoff rule. At each cutoff, latest `sales_fulfillments.units` grouped by
  SKU+demand-location+sale-date must reconcile to latest `sales.units`. `supply_location_id`
  records the physical node; it never replaces the demand location used by forecasting.
- **Money:** every canonical money fact is an integer **minor-unit** value paired with
  `currency_code` and the contract's currency metadata (`INR` paise, `USD/EUR` cents, `GBP`
  pence for the initial packs). Raw sources may use decimal major units only when the profile
  declares currency/unit/tax basis and an exact decimal conversion. Source-money controls
  reconcile independently per currency. `net_sales_amount` is always exact; when
  gross/discount components are supplied they must satisfy
  `gross_sales_amount - discount_amount = net_sales_amount` on the declared exclude-tax basis,
  while `tax_amount` reconciles separately. When one exact source amount spans multiple canonical
  rows, the profile names the allocation basis and the transform allocates integer minor units
  with a largest-remainder method plus a stable business-key tie-break. At every version/cutoff,
  canonical children plus an explicit not-yet-fulfilled/filtered/quarantined residual must sum
  exactly to the source control total; rounded unit prices are never used for the allocation.
  Tenant reporting amounts (INR for this PoC) are separately derived with as-of `fx_rates`;
  conversion never replaces the local-currency fact or its source reconciliation. FX stores
  exact decimal quote-major-units per base-major-unit and converts each canonical fact using the
  exponent-aware `ROUND_HALF_EVEN` formula in §2.4 before aggregation.
- **Grain** is stated per entity. Source profiles may declare different raw grains; mapping,
  joins and semantic transformations produce these canonical grains (§11.10).
- **Publication lineage:** every curated run records `source_system`, `source_schema_version`,
  `source_snapshot_id` and raw hashes, profile/adapter/transform versions, ingest run/time,
  coverage/composite-manifest hashes and capability mask, `known_as_of` rules,
  input/filtered/rejected/output counts and quantity/money reconciliations.

### 11.1 Core canonical entities `[in]` — REUSE + TEMPORAL CONTRACT (from `retail_v1`)

The M5 fields are retained where useful, but `retail_v2` makes point-in-time availability,
location ownership, money and post-sale adjustments explicit. One sample row each (grain in
parentheses).

| Entity (grain) | Key columns | Sample row |
|---|---|---|
| `sales` (SKU×demand-location×day×availability version) | `sku_id, store_id, date, sales_version, units, net_sales_amount, currency_code, net_price, promo_flag, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 1, 8, 8799200, INR, 1099900, false, 2026-07-15T23:59:00+05:30` |
| `sales_adjustments` (post-sale event×availability version) | `adjustment_id, adjustment_version, source_parent_event_id, sku_id, store_id, sale_date, event_date, event_type, units, amount, currency_code, known_as_of` | `ADJ-R44-PHYS, 1, RET-R44, NK-AM270-BLK-09, MUM01, 2026-07-15, 2026-07-28, physical_return, 1, null, null, 2026-07-28T15:02:00+05:30` |
| `sales_fulfillments` (fulfillment line×availability version) | `fulfillment_line_id, fulfillment_version, source_sale_id, sku_id, demand_location_id, supply_location_id, sale_date, fulfilled_at, units, known_as_of` | `FUL-L44, 1, ORD-44, NK-AM270-BLK-09, VIRTUAL_ONLINE, WHDC-W, 2026-07-15, 2026-07-16T10:20:00+05:30, 8, 2026-07-16T10:22:00+05:30` |
| `products` (SKU) | `sku_id, dept_id, category, sub_cat, pack_size, product_name, brand, shelf_life_days, reference_cost` | `NK-AM270-BLK-09, FTW-RUN, Footwear, Running, 1, "Nike Air Max 270", Nike, null, 630000` |
| `stores` (curated compatibility view; not a source entity) | `store_id, market_id, currency_code, timezone, region, format, channel, city` | `MUM01, india, INR, Asia/Kolkata, West, Large-format, in-store, Mumbai` |
| `calendar` (market×day) | `market_id, date, known_as_of, weekday, month, year, working_day` | `india, 2026-07-15, 2020-01-01, Wed, 7, 2026, true` |
| `calendar_events` (market×geographic-scope×event×date) | `market_id, geo_scope_type, geo_scope_id, date, event_name, event_type, known_as_of` | `india, market, india, 2026-11-08, Diwali, festival, 2020-01-01` |
| `sell_prices` (SKU×store×week×known-as-of observation) | `sku_id, store_id, week_start, net_price, regular_price, promo_price, currency_code, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-13, 1099900, 1199900, 1099900, INR, 2026-07-13` |
| `stock_snapshots` (SKU×location snapshot) | `sku_id, location_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 48, 244, 2026-07-15T23:59:00+05:30` |
| `suppliers_leadtimes` (supplier×merchandise-scope×destination/origin×effective-date×known-as-of observation) | `supplier_id, destination_location_id, merch_scope_type, merch_scope_id, from_location_id, effective_from, lead_time_days, moq, pack_qty, known_as_of` | `SUP_NIKE, MUM01, dept, FTW-RUN, WHDC-W, 2026-01-01, 6, 24, 12, 2026-01-01` |

**Used in the PoC:** these feed the weekly feature build → LightGBM forecaster (§3.1),
reorder/safety-stock engine (§3.3), baselines/FVA, and every KPI in §2.5.

Supplier resolution is deterministic. `merch_scope_type` is exactly `sku`, `dept` or `category`;
`merch_scope_id` must reference the corresponding product dimension. For the same supplier/
destination/origin and cutoff, precedence is `sku > dept > category`. This allows a broad
category default, a governed procurement-department override and an exact item contract without
conflating merchandise with geography. `from_location_id=NULL` denotes external supplier origin
not represented as a canonical location and is **not** a wildcard; a known internal origin
requires an exact location match. The selected row is the latest
`effective_from ≤ decision date` known by the cutoff. Ambiguous equal-precedence rows fail Gate B.

### 11.2 Cost & price history `[in]` + `[poc]` — NEW (solves §10.5)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `purchase_receipts` `[in]` (SKU×location×receipt) | `receipt_id, sku_id, location_id, supplier_id, receipt_date, qty, unit_cost, currency_code, known_as_of` | `RCP-0012, NK-AM270-BLK-09, MUM01, SUP_NIKE, 2026-03-10, 100, 660000, INR, 2026-03-12` |
| `inventory_cost` `[poc]` derived (SKU×location×as-of) | `sku_id, location_id, as_of_date, wac_cost, currency_code, on_hand_qty, method, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 630000, INR, 148, WAC, 2026-07-15T23:59:00+05:30` |

**Used in the PoC:** `purchase_receipts` is the **cost ledger** (the source of truth for cost
over time); the PoC rolls it into `inventory_cost.wac_cost` (moving-average, cost-as-of the
decision date) for **margin** and **inventory valuation**, while pricing/replenishment Order
Value uses the latest `unit_cost` (replacement cost). This is what makes margin correct when the
same SKU is replenished at different costs.

### 11.3 Competitor `[in]` + `[poc]` — NEW (Competitor Monitor, price responses)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `competitors` `[cfg]` (market×competitor) | `market_id, comp_id, name, type, collection_method, refresh, currency_code, compliance_ok` | `india, CMP_TW, TechWorld, Marketplace, api_feed, hourly, INR, true` |
| `competitor_products` `[in]` (market×competitor-product×known-as-of observation) | `market_id, comp_id, comp_product_id, observed_at, title, brand, model, gtin, attributes, known_as_of` | `india, CMP_TW, TW-AIRPODS2, 2026-07-15T09:00, "AirPods Pro 2", Apple, MTJV3HN/A, null, "colour=white", 2026-07-15T09:05` |
| `competitor_prices` `[in]` (market×competitor-product×geographic-scope×observation) | `market_id, comp_id, comp_product_id, geo_scope_type, geo_scope_id, observed_at, price, currency_code, in_stock_flag, promo_flag, known_as_of` | `india, CMP_TW, TW-AIRPODS2, location, BLR03, 2026-07-15T09:12, 2449900, INR, true, false, 2026-07-15T09:15` |
| `competitor_matches` `[poc]` (market×our-SKU×competitor-product) | `match_id, market_id, sku_id, comp_id, comp_product_id, match_confidence, match_status, matched_attributes` | `MTCH-081, india, APP-APP2-WHT, CMP_TW, TW-AIRPODS2, 0.96, matched, "brand;model;gtin"` |

**Used in the PoC:** the product-matching model (§8.1) links `competitor_prices` to `sku_id`
via `competitor_matches` (low-confidence stays in review, can't auto-trigger pricing); matched
competitor price/availability feeds the **competitor-availability demand driver** (§3.4) and the
price-recommendation competitor bound.

### 11.4 Promotions & customers `[in]` — NEW (Promotion Planner)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `promotions` (market×promo×known-as-of observation) | `market_id, promo_id, name, type, objective, offer_value, currency_code, start_date, end_date, segment_id, min_margin_pct, approval_route, status, owner, known_as_of` | `india, PR-Monsoon, "Monsoon Footwear Event", pct, revenue, 12, null, 2026-07-20, 2026-07-31, SEG_ALL, 20, category_mgr, draft, Emma, 2026-07-01` |
| `promotion_scopes` (market×promo×scope-row×known-as-of observation) | `market_id, promo_id, scope_row_id, region, location_id, channel, known_as_of` | `india, PR-Monsoon, S1, West, null, online, 2026-07-01` |
| `promotion_merchandise_targets` (market×promo×merchandise-scope×known-as-of observation) | `market_id, promo_id, merch_scope_type, merch_scope_id, discount_pct, known_as_of` | `india, PR-Monsoon, category, Footwear, 12, 2026-07-01` |
| `customer_segments` (market×segment snapshot) | `market_id, segment_id, name, size, share_pct, description, as_of_date, known_as_of` | `india, SEG_LOYAL, "Loyalty members", 480000, 38, "Active loyalty base", 2026-07-01, 2026-07-02` |

**Used in the PoC:** promotions feed the promo-uplift / cannibalisation / bundle models (§8.1)
and the promotion-overlap + inventory-readiness guardrails; `customer_segments` drive targeting
and the segment-response model.

Promotion scope is structured, never a free-form expression. Non-null qualifiers on one
`promotion_scopes` row are ANDed (`region=West` and `channel=online`); multiple rows are ORed.
All-null optional qualifiers mean the whole stated market. `region` is resolved only inside
`market_id`. Amount-based offers require the promotion market's `currency_code`; percentage
offers keep it null. `promotion_merchandise_targets` uses the same
`merch_scope_type ∈ {sku, dept, category} + merch_scope_id` convention as supplier terms. When
one product matches overlapping promotion merchandise rows, precedence is
`sku > dept > category`; conflicting equal-precedence discounts fail Gate B. This supports broad
commercial categories, narrower departments and exact SKUs without a variable-shaped key.

### 11.5 External signals `[in]` — NEW (Demand Drivers, scenarios, multi-currency)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `weather_actual` (market×geographic-scope×day) | `market_id, geo_scope_type, geo_scope_id, date, tavg_c, precip_mm, weather_code, known_as_of` | `india, location, MUM01, 2026-07-15, 29.4, 62.0, rain, 2026-07-15` |
| `weather_forecast` (market×geographic-scope×forecast×target) | `market_id, geo_scope_type, geo_scope_id, forecast_date, target_date, tavg_c, precip_prob, known_as_of` | `india, location, MUM01, 2026-07-15, 2026-07-22, 30.1, 0.7, 2026-07-15` |
| `local_events` (market×geographic-scope×event×date) | `market_id, geo_scope_type, geo_scope_id, date, event_name, event_type, expected_impact, known_as_of` | `india, location, BLR03, 2026-08-15, "City Marathon", civic, 1.2, 2026-07-01` |
| `macro_index` (market×geographic-scope×week) | `market_id, geo_scope_type, geo_scope_id, week_start, index_name, value, known_as_of` | `india, region, West, 2026-07-13, consumption_index, 104.6, 2026-07-16` |
| `fx_rates` (base-currency×reporting-currency×rate-date observation) | `base_ccy, quote_ccy, rate DECIMAL(38,18), rate_date, known_as_of` | `USD, INR, 83.000000000000000000, 2026-07-15, 2026-07-15` |

**Used in the PoC:** weather/local-event/macro become forecast features + the weather and
competitor driver groups (§3.4) and the Scenario-Planning axes (§3.6); `fx_rates` supports
reporting/display conversion (§2.4). All respect `known_as_of` — a forecast weather value can't
be "known" before its issue date.

The geographic scope key is interpreted only inside `market_id`; no signal row can leak from one
market to another because two regions/cities share a label. FX follows the
local/base→reporting/quote direction and exact conversion rule in §2.4.

### 11.6 Multi-echelon inventory `[in]` + `[poc]` — NEW

| Entity (grain) | Columns | Sample |
|---|---|---|
| `locations` `[in]` (location; authoritative) | `location_id, name, type, market_id, currency_code, timezone, region, city, parent_dc, active` | `WHDC-W, "West DC Ahmedabad", dc, india, INR, Asia/Kolkata, West, Ahmedabad, null, true` |
| `stock_snapshots` (extended) `[in]` | + `committed_units, reserved_units, damaged_units, in_transit_units, atp_units, atp_method` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 48, 244, 4, 2, 0, 30, 42, derived_buckets, 2026-07-15` |
| `inventory_batches` `[in]` (batch) | `batch_id, sku_id, location_id, batch_qty, mfg_date, expiry_date, receipt_date, unit_cost, currency_code, known_as_of` | `BT-24A, BT-SERUM-30, MUM11, 320, 2026-05-01, 2026-08-05, 2026-05-04, 54000, INR, 2026-05-04` |
| `inbound_shipments` `[in]` (shipment) | `shipment_id, sku_id, from_location, to_location, qty, dispatch_date, expected_receipt_date, status, known_as_of` | `SHP-3391, APP-APP2-WHT, WHDC-S, BLR03, 240, 2026-07-12, 2026-07-18, in_transit, 2026-07-12` |
| `transfer_orders` `[poc]` (transfer) | `transfer_id, sku_id, from_location, to_location, qty, reason, expected_benefit_minor, currency_code, status` | `TRF-0102, RUN-SHOE-9, KOL04, CHE06, 72, lost_sales_recovery, 320000, INR, review` |
| `allocations` `[poc]` (SKU×location) | `allocation_id, sku_id, pool_qty, location_id, requested_qty, allocated_qty, shortfall, rule, priority, status` | `ALC-77, NK-AM270-BLK-09, 1240, MUM01, 1480, 1220, 260, revenue_service, high, review` |

Canonical inventory bucket semantics are fixed:

- `on_hand_units` is total physical stock at the node. `committed_units` (allocated to accepted
  demand), `reserved_units` (other holds) and `damaged_units` (unsellable/blocked) are
  non-overlapping subsets.
- `atp_method = derived_buckets` requires
  `atp_units = max(0, on_hand_units - committed_units - reserved_units - damaged_units)`.
  `atp_method = source_observed` preserves an authoritative sellable/available source state and
  records the component equation as a reconciliation control; ingestion never subtracts the
  components from that observed ATP again.
- ATP excludes inbound supply. Canonical `on_order_units` is confirmed open quantity not yet
  dispatched; `in_transit_units` is dispatched but not received. They are disjoint and reconcile
  to `inbound_shipments` by status. A source `incoming` bucket that spans both must be split from
  shipment/PO detail or the replenishment capability is unavailable.
- Replenishment uses `inventory_position = atp_units + on_order_units + in_transit_units`.
  Gate B rejects negative buckets, overlaps/double counting and violations of the selected ATP
  method.

**Used in the PoC:** `locations` makes store/online/DC/3PL nodes first-class. In-transit remains
a shipment/inventory state on `inbound_shipments` or a destination snapshot, not a location type.
Inventory keys on `location_id`; the derived demand-location view supplies the reused
`sales.store_id` alias. `inventory_batches` powers ageing/expiry + **FIFO costing**;
`inbound_shipments` powers in-transit value + inventory position; `transfer_orders`/`allocations` are engine
outputs surfaced on the Transfers/Allocation screens.

### 11.7 Supplier performance `[in]` — NEW

| Entity (grain) | Columns | Sample |
|---|---|---|
| `supplier_performance` (supplier×period×known-as-of observation) | `supplier_id, period, otd_pct, capacity_confirmed_pct, lead_time_mean_days, lead_time_std_days, risk, known_as_of` | `SUP_ELECA, 2026-Q2, 0.81, 0.82, 8.6, 2.4, high, 2026-07-10` |

**Used in the PoC:** `lead_time_std_days` sharpens safety stock (lead-time variability is ~28% of
the driver mix); OTD/capacity/risk drive Supplier Planning + expedite/alternate-source guardrails.

### 11.8 Forecast & planner outputs `[poc]` — produced at runtime (NOT ingested)

These are the PoC's own outputs, bound by semantic fingerprints (§4.8), not generator files.

| Entity (grain) | Columns | Sample |
|---|---|---|
| `forecast_versions` (version) | `version_id, kind, origin_date, horizon_weeks, created_by, accuracy, bias, demand_units, semantic_fingerprint, status` | `v28, ai, 2026-07-13, 26, DemandSenseAI, 87.6, -2.8, 1316420, sha…, current` |
| `forecast_series` (version×SKU×store×horizon) | `version_id, sku_id, store_id, horizon_week, yhat_p50, yhat_p90, confidence` | `v28, NK-AM270-BLK-09, MUM01, 1, 510, past-591, 0.93` |
| `forecast_drivers` (version×scope×driver) | `version_id, scope, driver, contribution_pct, direction, confidence` | `v28, portfolio, seasonality, 18, positive, 0.91` |
| `planner_adjustments` (adjustment) | `adj_id, sku_id, store_id, origin_date, ai_forecast, planner_forecast, reason_code, effective_period, comment, actor, status, value_added_flag` | `ADJ-44, LV-501-BLU-32, NOI08, 2026-07-13, 246, 260, promotion_change, next_4_weeks, "local promo", Rahul, accepted, true` |

**Used in the PoC:** Compare Versions modal, SKU workbench, Demand Drivers tab, and the
Planner-Overrides KPI.

### 11.9 Governance & admin `[cfg]`/`[poc]` — NEW + reused workflow tables

| Entity | Columns | Origin |
|---|---|---|
| `users` | `user_id, name, role, scope, approval_limit_pct, status` | `[cfg]` |
| `roles` | `role_id, name, approval_limit, rbac_scope_type` | `[cfg]` |
| `data_sources` | `source_id, name, type, source_schema_version, refresh, profile_ref, adapter_version, transform_bundle_version, enabled` | `[cfg]` |
| `source_mapping_configs` | `mapping_config_id, source_id, entity, source_key, canonical_key, effective_from, effective_to, version, approved_by, approved_at, status` | `[cfg]` |
| `ingest_runs` | `ingest_run_id, source_id, source_snapshot_id, raw_manifest_hash, coverage_manifest_hash, composite_manifest_hash, profile_version, adapter_version, transform_version, started_at, completed_at, status, raw_quality_pct, canonical_quality_pct, capability_mask, curated_fingerprint` | `[poc]` |
| `reconciliation_results` | `reconciliation_id, ingest_run_id, entity, metric, raw_value, filtered_value, canonical_value, difference, tolerance, status` | `[poc]` |
| `quality_violations` | `violation_id, ingest_run_id, gate, entity, source_record_id, rule_id, severity, reason, observed_at` | `[poc]` |
| `quarantine_records` | `quarantine_id, ingest_run_id, gate, entity, source_record_id, reason_code, raw_record_ref, payload_hash, quarantined_at` | `[poc]` |
| `source_crosswalks` | `crosswalk_id, ingest_run_id, mapping_config_id, source_id, entity, source_key, canonical_key, resolution_status, known_as_of` | `[poc]` |
| `model_registry` | `model_id, family, version, coverage, accuracy, last_trained, status, fingerprint` | `[poc]` |
| `model_drift` | `model_id, as_of, drift_score, threshold, status` | `[poc]` |
| `alert_rules` | `rule_id, category, trigger, threshold, direction, owner, priority, active` | `[cfg]` |

The ingest, reconciliation, quality, quarantine and crosswalk rows above are operational
`[poc]` lineage/control tables. They describe how canonical data was produced but are not
canonical `[in]` retailer facts.

An authorized admin owns and approves immutable versions of `data_sources` and
`source_mapping_configs`. Ingestion only materializes the approved mappings it used into
`source_crosswalks`; it cannot silently create or change a canonical key. An unmapped or
multiply-mapped required source key is quarantined until a new mapping version is approved.

**Reuse and extend the M5 PoC workflow design (migration 001/002/003):**
`workflow_sessions`, `draft_orders`, `approvals`, `exceptions`, `exception_notes`,
`exception_status_history`, `audit_log`, `policy_edits`, `price_recs`, `price_rec_reviews`,
`adoption_metrics`. Preserve named-actor, idempotency, audit and shadow-only semantics (§4.7),
but do not copy the schema unchanged: pricing activations/recommendations require explicit
`market_id`, local `currency_code` and resolved-policy fingerprint; replenishment drafts require
demand/supply location or selected warehouse/lane context.

### 11.10 Source profiles, transformations and ownership

| Ownership | Entities / artifacts |
|---|---|
| **`[in]`** canonical input produced by ingestion from generated/authorized sources | sales, sales_adjustments, sales_fulfillments, products, locations, calendar, calendar_events, sell_prices, stock_snapshots, inventory_batches, inbound_shipments, suppliers_leadtimes, supplier_performance, purchase_receipts, competitor_products, competitor_prices, promotions, promotion_scopes, promotion_merchandise_targets, customer_segments, weather_actual, weather_forecast, local_events, macro_index, fx_rates |
| **Curated compatibility/derived during ingest** | `stores` view from demand locations carrying market/currency/timezone; normalized market business calendars |
| **`[poc]`** produced at runtime | ingest_runs, reconciliation_results, quality_violations/quarantine_records, source_crosswalks, inventory_cost, competitor_matches, transfer_orders, allocations, forecast_versions/series/drivers, planner_adjustments, model_registry, model_drift, + all workflow tables |
| **`[cfg]`** version-controlled | competitors, users, roles, data_sources, source_mapping_configs, alert_rules, source-profile schema, guardrail config (`pricing_rules.yaml`, `policy.yaml`) |
| **`[test]`** never served as client fact | generator hidden causal/source truth; ingestion-owned canonical fixtures; ingestion-owned, profile-versioned source-truth→canonical expected-control oracle; optional competitor-match truth and round-trip golden results |

Physical source files do not have to mirror this list. One order platform might supply order
headers, lines, refunds and fulfillments that collectively produce canonical `sales`,
`sales_adjustments` and `sales_fulfillments`; inventory observations or ERP/WMS snapshots are
still required to produce `stock_snapshots`.

#### Transformation extension points

1. **Declarative profile** — paths/tables, formats, source schema version, columns/types, code
   maps, keys, timezone/business-day cutoff, money unit/currency/tax basis and named source
   policies. It is configuration consumed by the normalization adapter, not executable
   downstream model logic.
2. **Profile-driven normalization adapter** — `mapped_files` is the default. A thin versioned
   platform adapter is permitted only for nested or source-specific semantics that the default
   mapper cannot express safely. Either route converts raw records into the same standardized
   staging entities.
3. **Reusable domain transforms** — operate only on standardized staging to join, deduplicate/
   select versions, apply declared order/refund/inventory policies, convert units/money, attach
   PIT/provenance and aggregate to canonical `retail_v2`. They cannot branch on retailer name.

The staging interface is source-neutral and versioned separately from `retail_v2`:

| Staging entity | Minimum normalized envelope |
|---|---|
| `stg_merchandise_lines` | source record/sale IDs, SKU and demand-location source keys, event time, fulfilled units, exact gross/discount/tax/net amounts, currency, normalized status, source timestamps, `observed_at` |
| `stg_adjustment_events` | source parent/child event IDs, source sale ID, SKU/location keys, physical units or financial amount, normalized event kind, event/source timestamps, `observed_at` |
| `stg_fulfillment_lines` | fulfillment/source sale IDs, SKU key, demand- and supply-location source keys, fulfilled units/time, source version, `observed_at` |
| `stg_inventory_observations` | SKU/location keys, named source states, observation time, source semantics/version |
| `stg_receipt_lines` | receipt/SKU/location/supplier keys, quantity, exact unit cost/currency, receipt/posting times |
| `stg_dimensions_signals` | stable source key, normalized attributes/value, effective/event time, source version, `observed_at` |

Profile `normalization` directives (paths, field/type/code maps and raw policy names) are executed
by the default mapper or thin source adapter. Profile `domain_transforms` entries are only
versioned registry references plus parameters; the shared transform runner executes them after
staging. Adapters may not emit canonical aggregates, and domain transforms may not inspect a
retailer/platform identifier.

Configuration-only onboarding is therefore a capability, not a blanket promise: it applies when
existing transforms cover the source semantics; otherwise a bounded adapter is added without
changing downstream code.

#### Coverage and capability manifest

Every ingestion run produces machine-readable coverage; absence is never inferred merely from
missing files. It may consume source-supplied declarations, but the ingestion-owned manifest is
authoritative for Gate A/B. The manifest contract contains:

- `coverage.mode: full | partial`, source window and snapshot identity;
- for each canonical entity, `completeness: complete | partial_fields`, covered fields/grain,
  source controls and whether zero rows are a valid observation;
- `capability_claims` with separate `availability ∈ {enabled, requires_companion, unavailable}`
  and `evidence ∈ {client_actual, synthetic_test, synthetic_scenario}`, evaluated against §10.4
  dependencies;
- the approved composite/merge policy, source precedence and expected companion source IDs.

Gate B applies type, key, PIT, provenance and reconciliation rules to every declared field. A
declared-but-missing field is critical. `completeness: complete` additionally enforces the whole
canonical entity contract; `partial_fields` proves only the adapter's declared projection and
cannot satisfy a capability that requires the complete entity. A capability claiming
`availability: enabled, evidence: client_actual` with any missing dependency is critical. An
entity explicitly outside a partial source's coverage is reported as unsupported, not defaulted
and not counted as a quality pass.
The partial result is `validated_partial` and remains in the validation/staging zone.

A **composite ingest manifest** unions approved source slices (for example Shopify +
ERP/WMS + external feeds), defines conflict precedence at entity/field grain and recomputes the
capability mask. Only a composite/full dataset that satisfies every dependency of an enabled
capability may receive full Gate-B `pass`, be atomically promoted to curated storage and enter
features/models. This is how a pure Shopify adapter test and a complete Shopify-led PoC can both
be honest.

**Source-profile example** — this profile declares both structural mapping and semantic policy:

```yaml
profile_id: retailer_a_orders_v1
contract_version: retail_v2
adapter: mapped_files
source_classification: SYNTHETIC_SOURCE
source_system: retailer_a_pos
source_schema_version: v1
raw_dir: /data/raw/retailer_a/snapshot_2026_07
manifest: manifest.json
business_timezone: Asia/Kolkata
money: {currency: INR, source_unit: major_decimal, canonical_unit: minor_unit, tax_basis: exclude_tax}
coverage:
  mode: partial
  canonical_entities:
    sales: {completeness: complete,
            fields: [sku_id, store_id, date, sales_version, units, net_sales_amount,
                     currency_code, known_as_of],
            zero_rows_valid: false}
    sales_adjustments: {completeness: complete,
                        fields: [adjustment_id, adjustment_version, sku_id, store_id, sale_date,
                                 event_date, event_type, units, amount, known_as_of],
                        zero_rows_valid: true}
    sales_fulfillments: {completeness: complete,
                         fields: [fulfillment_line_id, fulfillment_version, source_sale_id,
                                  sku_id, demand_location_id, supply_location_id, sale_date,
                                  fulfilled_at, units, known_as_of],
                         zero_rows_valid: false}
    purchase_receipts: {completeness: complete,
                        fields: [receipt_id, sku_id, location_id, supplier_id, receipt_date,
                                 qty, unit_cost, currency_code, known_as_of],
                        zero_rows_valid: true}
  capability_claims:
    demand_forecast: {availability: requires_companion, evidence: synthetic_test}
    replenishment: {availability: requires_companion, evidence: synthetic_test}
normalization:
  order_lines:
    path: transactions.parquet
    source_grain: order_line
    keys: [transaction_id, line_id]
    emits: [stg_merchandise_lines, stg_fulfillment_lines]
    fields: {source_sale_id: transaction_id, source_line_id: line_id, sku_source_key: item_code,
             demand_location_source_key: branch_code, supply_location_source_key: branch_code,
             event_at: transaction_ts, fulfilled_units: quantity,
             gross_amount: line_gross, discount_amount: line_discount, tax_amount: line_tax,
             net_amount: line_net, status_code: line_status, source_updated_at: updated_ts}
  adjustment_events:
    path: sales_adjustments.parquet
    source_grain: adjustment_event
    keys: [adjustment_id, adjustment_version]
    emits: [stg_adjustment_events]
    fields: {source_event_id: adjustment_id, source_event_version: adjustment_version,
             source_parent_event_id: parent_event_id, source_sale_id: transaction_id,
             sku_source_key: item_code, demand_location_source_key: branch_code,
             event_kind: adjustment_type, physical_units: reversed_qty,
             financial_amount: refund_amount, event_at: adjustment_ts,
             source_updated_at: posted_on}
  purchase_receipts:
    path: goods_receipts.csv
    source_grain: receipt_line
    emits: [stg_receipt_lines]
    fields: {receipt_source_key: grn_line_id, sku_source_key: item_code,
             location_source_key: location_code, supplier_source_key: vendor,
             receipt_at: grn_date, quantity: qty, unit_cost: landed_cost,
             source_updated_at: posted_on}
domain_transforms:
  - transform_id: merchandise_sales_v2
    version: 2
    inputs: [stg_merchandise_lines, stg_fulfillment_lines, stg_adjustment_events]
    parameters:
      quantity_basis: fulfilled
      pre_fulfilment_cancellation: exclude_with_control
      post_fulfilment_reversals: sales_adjustments
      aggregate_to: [sku_id, store_id, business_date, sales_version]
  - transform_id: purchase_receipts_v1
    version: 1
    inputs: [stg_receipt_lines]
```

The profile, adapter, staging-interface and transform versions are part of the curated identity.
`CLIENT_SHADOW` profiles cannot default mandatory business facts. They may derive
`known_as_of`/versions from trusted source, extraction or immutable landing observations only
under an explicit versioned rule with provenance; otherwise the rows are quarantined.
`SYNTHETIC_CALIBRATED` values may enter only a separately declared demo/scenario capability;
they do not satisfy a client-actual required-field gate and cannot be mixed into client-actual
metrics or decisions.

#### End-to-end ingestion flow

1. Connector/generator writes a source snapshot to immutable raw landing; an upstream manifest is
   retained when present, and ingestion always writes the authoritative landing manifest/hashes.
2. Gate A validates raw hashes, schema, keys, extract window and available/derived source control
   totals under the source profile.
3. The default `mapped_files` adapter, or a bounded platform adapter when required, applies the
   versioned profile and emits standardized staging frames.
4. Source-neutral domain transforms join/filter/version/aggregate staging into canonical
   `retail_v2` and attach entity-specific `known_as_of`.
5. The pipeline records row provenance plus profile/adapter/transform lineage.
6. Gate B validates the declared canonical scope, capability dependencies, referential integrity
   and reconciliations; a partial scope stops at `validated_partial`.
7. Only a capability-complete double-pass is atomically promoted to curated Parquet + DuckDB;
   failed/rejected rows remain reason-coded in quarantine and no previous curated publication is
   disturbed.
8. `features.build` creates weekly point-in-time features; Python models/engines write
   fingerprinted forecast/recommendation `[poc]` artifacts.
9. The Go API serves those artifacts and owns workflow/HITL, guardrail/lineage re-validation,
   staleness 409/503 and audit. Everything remains shadow-only.

For the local PoC, source snapshots are immutable full runs. Incremental/API ingestion may land
additional immutable snapshots, but production change-data-capture semantics are deferred until
the full-run path and reconciliation gates pass.

### 11.11 Shopify Admin API source-adapter example

Shopify is an example of the same boundary, not a special downstream data path. A retailer
normally authorizes the GraphQL Admin API or supplies an authorized export/warehouse copy; the
PoC does not expect direct access to Shopify's production database. For a large initial load,
GraphQL [bulk operations](https://shopify.dev/docs/api/usage/bulk-operations/queries) can land
immutable JSONL. For ongoing changes, use version-pinned
[webhooks plus periodic reconciliation](https://shopify.dev/docs/apps/build/webhooks), because
delivery and ordering are not guaranteed. Request only the required
[access scopes](https://shopify.dev/docs/api/usage/access-scopes); historical orders beyond
Shopify's default recent-order window require the applicable all-orders access. The actual
connector runs only in a client-controlled environment; locally, `datagen` publishes a
synthetic Shopify-shaped source projection from its own source contract.

The rules below define the **adapter's full conformance target**, not the minimum first datagen
milestone. The core generated fixture may initially cover products/variants, locations,
orders/lines, basic fulfillment, prices and inventory observations. Detailed split/status
history, processed-return proof, refund-transaction outcomes, all inventory states, signed
webhook envelopes and protected-field rejection fixtures are enabled later with the matching
§9.7 screen/connector acceptance. Real connectors must still obey every applicable rule.

```text
Shopify bulk JSONL / webhook request
                 ↓
 client-edge auth + approved field projection
                 ↓
  immutable approved Shopify raw landing
                 ↓
     Shopify profile + source adapter
                 ↓
          standardized staging
                 ↓
      shared source-neutral transforms
                 ↓
           canonical retail_v2
                 ↓
       canonical quality/PIT gate
```

Illustrative client-controlled profile policy (the local golden fixture uses the same semantics
with `source_classification: SYNTHETIC_SOURCE`—a provenance label independent of the retired
canonical/source generator publication modes—and
`capability_claims.*.evidence: synthetic_test`):

```yaml
profile_id: shopify_admin_v1
contract_version: retail_v2
adapter: shopify_admin
source_classification: CLIENT_SHADOW
source:
  bootstrap: graphql_bulk_jsonl
  incremental: webhooks_plus_reconciliation
  api_version: pinned_and_recorded
  webhook_auth: hmac_verified_before_projection_and_landing
business_timezone: from_approved_location_market_mapping
timestamps:
  demand_date: {primary: order.processedAt, fallback: order.createdAt,
                fallback_requires: retailer_approval}
  fulfillment_time: {live: first_success_source_event_at,
                     backfill: fulfillment.createdAt,
                     backfill_requires: retailer_confirmation}
  adjustment_event_time:
    physical: timestamped_processed_reverse_disposition_event
    financial: {primary: orderTransaction.processedAt, fallback: refund.processedAt,
                fallback_requires: successful_linked_refund_transaction}
money:
  currency: from_shop_market_context
  require_location_operating_currency: true
  canonical_unit: minor_unit
  source_tax_basis: from_order_taxes_included
  canonical_tax_basis: exclude_tax
  order_refund_money_bag: shopMoney
  presentment_money: audit_only
  catalog_price_scalar: Money
  inventory_unit_cost_scalar: MoneyV2
keys:
  sku_id: product_variant_gid
  normalize: shopify_gid_v1
  accepted_raw_forms: [graphql_gid, admin_graphql_api_id, typed_numeric_id]
  unresolved_variant: approved_historical_crosswalk_or_quarantine
demand_location:
  classify_channel_first: true
  pos: order.retailLocation.id
  ecommerce: VIRTUAL_ONLINE
  virtual_node: {materialize_in: locations, type: online, region: approved_market_region,
                 active: true, provenance: SHOPIFY_DERIVED}
price_scope:
  catalog_default_location: VIRTUAL_ONLINE
  market_context: approved_market_to_location_mapping
  physical_replication: retailer_confirmation_required
supply_location:
  primary: fulfillment.location.id
  fallback: fulfillmentOrder.assignedLocation.location.id
  fallback_requires: retailer_confirmation
returns_policy: separate_versioned_events
coverage:
  mode: partial
  canonical_entities:
    products: {completeness: partial_fields, fields: [sku_id, product_name, brand]}
    locations: {completeness: complete,
                fields: [location_id, type, market_id, currency_code, timezone, region, active],
                condition: approved_location_mapping_and_virtual_node}
    sales: {completeness: complete,
            fields: [sku_id, store_id, date, sales_version, units, net_sales_amount,
                     currency_code, known_as_of],
            condition: complete_sales_domain_resolution_and_history}
    sales_adjustments: {completeness: complete,
                        fields: [adjustment_id, adjustment_version, sku_id, store_id, sale_date,
                                 event_date, event_type, units, amount, known_as_of],
                        zero_rows_valid: true,
                        condition: complete_sales_domain_resolution_and_history}
    sales_fulfillments: {completeness: complete,
                         fields: [fulfillment_line_id, fulfillment_version, source_sale_id,
                                  sku_id, demand_location_id, supply_location_id, sale_date,
                                  fulfilled_at, units, known_as_of],
                         condition: complete_sales_domain_resolution_and_history}
    sell_prices: {completeness: partial_fields,
                  fields: [sku_id, store_id, week_start, net_price, currency_code, known_as_of],
                  history: prospective_or_proven_versions,
                  condition: approved_price_scope_mapping}
    stock_snapshots: {completeness: partial_fields,
                      fields: [sku_id, location_id, snapshot_date, on_hand_units, atp_units,
                               atp_method, known_as_of],
                      condition: approved_shopify_state_mapping}
  capability_claims:
    demand_forecast: {availability: requires_companion, evidence: client_actual}
    replenishment: {availability: requires_companion, evidence: client_actual}
    pricing_margin: {availability: requires_companion, evidence: client_actual}
    competitor_monitor: {availability: unavailable, evidence: client_actual}
domain_transforms:
  - {transform_id: merchandise_sales_v2, version: 2,
     parameters: {quantity_basis: fulfilled, demand_date: order_business_date}}
  - {transform_id: typed_sales_adjustments_v1, version: 1,
     parameters: {physical_and_financial_child_ids: separate}}
  - {transform_id: inventory_snapshot_v2, version: 2,
     parameters: {atp_method: source_observed, incoming_requires_state_split: true}}
protected_customer_data:
  resource_access: retailer_approved_least_scope
  operational_field_allowlist: profile_versioned
  pre_landing_projection: required
  reject_fields_not_allowlisted: true
  direct_identifiers:
    mode: deny_by_default
    allow: []
    deny: [name, email, phone, addresses, notes]
```

Profile conditions are resolved when ingestion builds its landing/coverage manifest, retaining
any upstream source manifest as evidence. A condition-false entity is
omitted from declared coverage, never emitted with defaults. For example, an unapproved location
mapping or missing materialized virtual node removes complete `locations` coverage; unresolved
historical/custom merchandise or adjustment lines, or insufficient fulfillment/return/refund
transition history, remove complete sales-domain coverage; and an unproven inventory-state
mapping removes the declared Shopify stock projection. Dependent capabilities remain
`requires_companion`. A missing price-scope mapping removes `sell_prices` rather than replicating
a shop-level price across physical stores by assumption.

| Shopify raw objects | Canonical treatment |
|---|---|
| `Product` + `ProductVariant` + `InventoryItem` | partial `products` projection; immutable variant GID is `sku_id` because merchant SKU may be blank/duplicated; deleted-variant/custom historical lines require a preserved immutable key or approved crosswalk, otherwise they are quarantined and completeness is reduced; approved taxonomy/pack fields may require PIM or mapping companion data |
| `Location` + approved virtual demand node | physical `locations` through a versioned, retailer-approved `source_mapping_configs` crosswalk for store/DC/3PL, market, operating currency, timezone, region and city; materialize `VIRTUAL_ONLINE` as a canonical `type=online` location with `SHOPIFY_DERIVED` provenance; record resolved mappings in `source_crosswalks` |
| `Order` + `LineItem` + `Fulfillment` + `FulfillmentLineItem` | filter test/non-merchandise lines and apply the explicit fulfillment-status policy; emit versioned `sales_fulfillments`; aggregate only successfully fulfilled merchandise into cumulative `sales` versions at SKU×demand-location×business-day, preserving exact net merchandise amount |
| `Return` + `ReturnLineItem` + return-processing evidence + `Refund` + `RefundLineItem` + `OrderTransaction` | a return request is intent only; emit a cumulative/versioned `physical_return` child only from processed return quantity, and a separate `financial_refund` child only from a successful refund transaction with exact merchandise amount; a late event never rewrites an earlier forecast origin |
| `Fulfillment` location + `FulfillmentOrder.assignedLocation` | actual supply location first, retailer-confirmed assigned-location fallback second, into `sales_fulfillments`; never use the warehouse as online demand origin |
| Variant price/compare-at price + order-line money | catalog `Money` scalars and order/refund `MoneyBag.shopMoney` follow separate mappings; timestamped `sell_prices` use an approved online/market/location scope, while exact order-line money produces `sales.net_sales_amount` and rounded display `sales.net_price`; never infer store scope or unobserved historical prices from the current catalog |
| `InventoryLevel.quantities` | profile-mapped named inventory states and source controls for timestamped `stock_snapshots`; a current snapshot is never backdated into historical daily stock |
| Discount allocations/definitions + tax lines | exact line/order attribution across split/partial fulfillments using the canonical integer-allocation rule; tax remains a separate control; `net_price` is display-only; promotion linkage is emitted where definitions exist |

Shopify-specific transformation rules:

- Retain `event_at`, source created/updated timestamps, `observed_at`, source record ID,
  snapshot/webhook ID and payload hash. Canonical `known_as_of` is the webhook observation time
  for a live event, or extraction time for a mutable backfill snapshot unless complete historical
  versions prove an earlier availability; `source_updated_at` alone does not prove when the PoC
  knew the fact.
- Verify every webhook HMAC against the unmodified request body at the client edge before trust,
  projection or landing; reject failed signatures and record only the verification metadata plus
  approved projected payload/hash. Deduplicate on the authenticated webhook identity and retain
  periodic API reconciliation because authentication does not guarantee delivery or ordering.
- Normalize GraphQL bulk GIDs, webhook `admin_graphql_api_id` values and typed numeric IDs to the
  same validated Shopify GID namespace before staging; an entity-type map and round-trip golden
  tests prevent bootstrap/incremental key drift. A nullable historical `LineItem.variant`
  requires a preserved source variant GID or approved immutable crosswalk. Custom merchandise or
  deleted-variant lines without one are quarantined, included in source rejection controls and
  reduce the declared completeness instead of being keyed by mutable SKU text.
- Classify the order channel from explicit source evidence before choosing a demand location; a
  null `Order.retailLocation` is not, by itself, proof of ecommerce. POS demand then uses the
  approved retail location, while ecommerce demand uses the approved `VIRTUAL_ONLINE` row that is
  materialized in canonical `locations`/`stores`. Only successfully fulfilled quantity enters
  canonical `sales`; accepted but unfulfilled quantity may remain a staging/control measure.
  Split fulfillment is allocated from
  fulfillment-order/fulfillment line data into `sales_fulfillments`, retaining both demand and
  physical supply locations. Latest bridge units must reconcile to latest sales units at every
  cutoff. `sales.date` uses the retailer-approved business date from `Order.processedAt`, with
  `createdAt` only as an approved fallback. `fulfilled_at` is the first trusted source event that
  proves success; a backfill may use `Fulfillment.createdAt` only when the retailer confirms that
  it represents realization. Otherwise the line is quarantined. `known_as_of` cannot precede
  the successful fulfillment observation.
- Apply a versioned fulfillment-status transition policy before aggregation. Only a line observed
  as `SUCCESS` can create fulfilled sales/bridge units; every other status remains a control
  until success. If a previously accepted successful line later becomes `CANCELLED`, retain the
  immutable base fulfilled-sale history and emit a versioned `post_fulfilment_cancellation` unit
  adjustment
  (or quarantine it when the retailer cannot prove that semantic). A line produces no sale or
  adjustment only when source event/history evidence proves cancellation preceded any success.
  A mutable backfill showing only current `CANCELLED` status is ambiguous: quarantine it and
  reduce completeness rather than infer an unobserved sequence. Replays of the same transition
  are idempotent.
- The actual fulfillment location takes precedence over an assigned fulfillment-order location.
  Assigned location is a fallback only when the retailer confirms it represents physical issue;
  an unresolved supply location is quarantined rather than attributed to `VIRTUAL_ONLINE`.
- Treat `Return` as request/intent, never receipt. For a stable ReturnLineItem child ID, versions
  carry cumulative `processedQuantity` (or equivalent approved processed reverse-disposition
  evidence); requested, declined or cancelled quantities do not reduce units. A financial child
  requires a successful `OrderTransaction` of refund kind and exact SKU-level merchandise amount
  from the refund/return line. Shipping, duties and tax remain separate. One source parent may
  therefore produce neither, either or both child kinds at different `known_as_of` cutoffs.
  Physical `event_date` comes from timestamped processing/reverse-disposition evidence; current
  `processedQuantity` alone cannot establish when it happened. Financial `event_date` uses the
  successful refund transaction's `processedAt`, with linked `Refund.processedAt` only as the
  declared fallback. Missing or contradictory event-time evidence quarantines the adjustment and
  reduces sales-domain completeness.
- Merchandise money uses exact decimal `shopMoney` conversion to integer minor units in the shop
  currency; shipping, duties and tax remain separate. Canonical `net_sales_amount` is the exact
  aggregated merchandise amount
  after allocated discounts on the declared tax basis; `net_price` is never used to rederive the
  control total. Use Shopify line allocations when authoritative. If an order-level amount spans
  lines or a line spans partial/split fulfillments, allocate integer minor units by fulfilled-unit
  basis using largest remainder and stable line/fulfillment GID ordering; recompute cumulative
  availability versions from the same rule. At each cutoff, fulfilled child minor units plus the
  explicit unfulfilled/filtered/quarantined remainder must equal the source line/order control;
  when every in-scope merchandise amount is resolved and fulfilled, final children sum to that
  in-scope source amount with no penny drift. Refund allocations follow the same exact rule.
  Transformed gross/discount/net/tax totals reconcile to source orders plus declared residuals.
  `presentmentMoney` is audit/display-only. Each shop currency remains explicit; cross-market
  reporting conversion is a separately governed derived value.
- Catalog `price`/`compareAtPrice` Money scalars and `InventoryItem.unitCost` MoneyV2 values use
  their own typed mappings; they are not read through the order/refund MoneyBag path. Current
  catalog price maps to the approved online virtual node or contextual market/location. It may be
  copied to physical stores only under an explicit retailer-confirmed uniform-price policy.
- Current variant price and inventory cannot reconstruct past unsold-week price or daily stock;
  build those histories prospectively from timestamped snapshots/events or ingest a historical
  warehouse source.
- Inventory state mapping is explicit and retailer-approved: preserve Shopify `on_hand`,
  `available`, `committed`, `reserved`, `damaged`, `quality_control`, `safety_stock` and
  `incoming` as separate raw controls. Map buckets only when their definitions reconcile to the
  disjoint canonical meanings; an approved derived mapping may classify non-order
  `reserved`/`quality_control`/`safety_stock` holds into canonical `reserved_units` without
  overlap. Shopify `available` maps to `atp_units` with
  `atp_method = source_observed`, so none of those components is subtracted from it again.
  Shopify-only coverage is `partial_fields`: `incoming` is an aggregate signal and cannot prove
  canonical `on_order_units` versus `in_transit_units`. PO/shipment detail from ERP/WMS must
  provide that disjoint split before replenishment can be capability-complete.
- `InventoryItem.unitCost` is a current observation, not a purchase-receipt ledger. Trustworthy
  WAC/FIFO still requires ERP/WMS/accounting receipts.
- Order, refund, transaction, return, shipping and fulfillment access is governed by Shopify's
  [protected-customer-data requirements](https://shopify.dev/docs/apps/launch/protected-customer-data)
  even when names/email are not selected. Resource access therefore requires retailer approval
  and least-privilege scopes; this is separate from the direct-identifier deny list. Apply
  GraphQL field selection plus a webhook field allow-list (`includeFields` where supported, or an
  equivalent trusted client-side projection) **before** the PoC's immutable raw landing.
  Unexpected denied fields reject the snapshot; adapter-stage deletion is too late. Names,
  emails, phones, addresses and notes are unnecessary. If an approved use case later needs
  continuity, use only a tenant-scoped
  pseudonymous key under the retailer's protected-data approval.

Shopify does not, by default, complete the PoC's historical receipt-cost layers, supplier
performance, batches/expiry, procurement history, competitor, weather, event, macro or footfall
domains. Integrate approved PIM/ERP/WMS/external sources or leave the dependent client capability
unavailable. A separately gated `SYNTHETIC_CALIBRATED` demo/scenario may illustrate that
capability, but it does not satisfy the client-actual gate and cannot be mixed into client
metrics or decisions. Provenance values such as `SHOPIFY_ACTUAL`, `SHOPIFY_DERIVED`,
`ERP_ACTUAL`, `EXTERNAL_ACTUAL` and `SYNTHETIC_CALIBRATED` must remain explicit.

---

## Appendix A — Service-level policy explained

### What it is
A **service level** is the target probability that you do **not** run out of stock during the
**protection period** = `lead_time + review_period`. Service level 0.96 means: "over the lead
time + review cycle we want ~96% confidence that on-hand stock covers demand; we accept a ~4%
stock-out chance." It is the single dial that trades **stock-out risk** (lost sales) against
**holding cost** (working capital). It is **not** forecast accuracy — even a perfect forecast of
*average* demand stocks out ~half the time if you only stock the average, because demand varies.

### How it becomes safety stock (`engines/reorder.py`)
```
safety_stock  = RSS(weekly P90−P50 spreads over the protection period) × service_level_scale(SL)
service_level_scale(SL) = Φ⁻¹(SL) / Φ⁻¹(0.90)          # Φ⁻¹ = inverse-normal z-score
reorder_point = demand_during_lead_time (P50) + safety_stock
order_up_to   = reorder_point + cycle_stock (P50 over the review period)
```
- `P90 − P50` is the model's own uncertainty band (wider for volatile/intermittent SKUs).
- **Why anchor at 0.90?** Holding to P90 already gives ~90% service (a ~1.28σ buffer);
  `service_level_scale` rescales that band to the chosen target — higher target → bigger buffer.
- `RSS` (root-sum-square) combines weekly spreads assuming weeks are independent, so buffer
  grows with √(weeks), not linearly.

### Worked example — same SKU, three service levels
Lead 2 wk + review 1 wk = 3-week protection; weekly P50 = 100, P90 = 130 (spread 30/wk).
RSS of the three weekly spreads = √(30²+30²+30²) ≈ **51.96**.

| Class | Service level | z = Φ⁻¹(SL) | scale = z / Φ⁻¹(0.90) | Safety stock = 51.96 × scale |
|---|---|---|---|---|
| A | 0.96 | 1.751 | 1.366 | **≈ 71 units** |
| B | 0.90 | 1.282 | 1.000 | **≈ 52 units** |
| C | 0.80 | 0.842 | 0.657 | **≈ 34 units** |

Same demand & uncertainty, but the A item carries ~71 units of buffer and the C item only ~34.
A-item reorder point = 200 (P50 over the 2-wk lead) + 71 = **271**; order-up-to = 271 + 100
(1-wk cycle) = **371**. When inventory position
(`atp_units + on_order_units + in_transit_units`) drops to/below 271, the engine proposes
topping up to 371 — then rounds to MOQ/pack multiples and caps at `max_cover_days` (30).

### Why A/B/C differ (0.96 / 0.90 / 0.80)
ABC is a **value** classification (A ≈ top 80% of annualized value = `avg_weekly × 52 × cost`,
B next 15%, C last 5%). You protect high-value **A** items hardest (a stock-out there costs the
most margin) and accept more risk on cheap, slow **C** items to avoid tying up working capital.

### Why "calibrate on 5% + validate on 95%"
The A/B/C numbers are chosen empirically then proven out-of-sample — like train/test for a model:
1. **Calibration** (`engines/policy_calibration.py`) runs candidate sets (`balanced` 0.96/0.90/0.80,
   `high_service` 0.98/0.92/0.85, …) through the inventory replay on a **deterministic 5% sample**
   and picks the highest value-weighted service level that still passes every acceptance check
   (fewer stock-out days, fewer lost units, fill ≥ incumbent, inventory value ≤ incumbent).
2. **Validation** (`engines/policy_validation.py`) applies that policy **once** to the untouched
   **95% holdout** (cohorts enforced disjoint, bound to the same forecast fingerprint); accepted
   only if the holdout also passes.

This prevents over-fitting the service levels to the tuning sample. The selected policy is
versioned and audited (`balanced`, `R-POLICY-796d076c97bf`) so any later change is traceable.
