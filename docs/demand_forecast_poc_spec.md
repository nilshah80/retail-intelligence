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
dashboard above, for an Indian multi-category, multi-store, multi-currency retailer
(Footwear / Apparel / Electronics / Beauty across Mumbai, Noida, Bengaluru, Kolkata,
Chennai; base currency INR). The **prior PoC ran on the public M5 dataset**; the new PoC is
a fresh codebase that **reuses and adapts proven modules** from it (adapter, features, forecaster,
reorder/pricing engines, guardrails, workflow). File references point at the M5 repo so the
new build can lift the pattern rather than reinvent it.

### Architecture & data flow (read this first)

The new PoC has a **hard split between data production and data consumption**, with an explicit
source-normalization boundary inside ingestion:

```
[ generator / retailer / Shopify ]                         [ this new PoC ]
 source-shaped files ──▶ raw landing ──▶ Gate A ──▶ profile/adapter ──▶ standard staging
                                                                             │
                                                                             ▼
                                                                    shared transforms
                                                                             │
                                                                             ▼
                                                                  canonical candidate
                                                                             │
                                                                             ▼
                                                        Gate B: canonical quality/PIT
                                                               ┌─────────────┴─────────────┐
                                                               ▼                           ▼
                                                   validated_partial (stop)     capability-complete pass
                                                                                           │
 workflow/API/UI ◀── artifacts ◀── engines/models/features ◀── curated Parquet/DuckDB ◀────┘
```

- **The generator repo owns "how synthetic reality is made."** The demand/price/weather/
  inventory logic described in §9 lives there. It supports two publishers: an exact canonical
  fixture for component tests and a source-shaped publisher for end-to-end onboarding tests.
- **A retailer or platform owns its source semantics.** Raw files are landed immutably and never
  edited in place. A versioned dataset profile declares paths, source columns, grains, keys,
  currency/tax/timezone rules, `known_as_of` derivation, joins, filters and named transforms.
- **This PoC owns "land → transform → decide → serve."** `ml/data` applies a declarative
  profile through the default `mapped_files` normalizer or, where necessary, a thin platform
  adapter; both emit standardized staging. Reusable source-neutral domain transforms then produce
  canonical grains and semantics. Downstream features/models never contain retailer-specific
  code.
- **§11 is the canonical output contract of ingestion, not necessarily the physical raw-file
  contract.** Only the transformed canonical tables must match `retail_v2` exactly. A generated
  `SYNTHETIC_CLIENT_SHAPED_TEST` and an authorized `CLIENT_SHADOW` extract travel through the same
  transformation and quality boundary; `SYNTHETIC_CANONICAL_TEST` may bypass raw Gate A and
  transformation only for component tests, but it never bypasses canonical Gate B.
- **Fail closed twice.** A raw-source gate validates extract completeness, parsing, keys and
  reconciliation; a canonical gate validates schema, point-in-time semantics, provenance,
  business rules and referential integrity before anything is promoted to curated storage.

### Technology stack — Python ML pipelines + Go API

The new PoC is **polyglot**: **ML pipelines in Python, the API/serving layer in Golang.**

```
 PYTHON (batch ML pipeline)                           GO (API / serving)
 Gate A → normalize → staging → transform → Gate B   reads artifacts + PostgreSQL
 → features → models(LightGBM/Poisson-EB) →          serves REST/gRPC to the UI
 engines(reorder, pricing, allocation, ageing) →      owns workflow/HITL, guardrail
 writes ARTIFACTS (Parquet/JSON + manifests +    ──▶  re-validation, staleness 409/503,
 semantic fingerprints) to lake + PostgreSQL          RBAC/auth, audit
```

What this means for the M5-PoC carry-over:
- **Python `[REUSE + EXTEND]` — reuse where contract-compatible:** adapt the proven feature,
  model and engine implementations rather than rewriting them. The M5 `data/` patterns are a
  starting point, but raw landing, two validation gates, source profiles/adapters, semantic
  transforms and reconciliation are material `retail_v2` extensions rather than an as-is copy.
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
2. **Money precision** — integer **minor units** (paise) on both sides; same `minor_unit_exponent`;
   no float drift in margin/price math.
3. **Single-sourced guardrail thresholds** — Python (enforce in engine) and Go (re-enforce at
   serve) both read the *same* `pricing_rules.yaml` / `policy.yaml` / `price_response.yaml`; never
   duplicate the numbers as Go constants.
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
| **Currency** | Base INR; live display switch to USD/EUR/GBP via FX rates (display-only) |

The screen is a **decision-support + governance workbench** on top of a demand forecast:
it shows AI vs baseline vs planner-adjusted numbers, exception queues, driver attribution,
external-signal readiness, approval SLAs, and lets planners accept/override forecasts and
run demand scenarios.

---

## 2. Part A — Data points required

### 2.1 Foundation: the canonical entities **[REUSE + EXTEND]**

The current PoC already defines a versioned, dataset-neutral contract `retail_v1`
(`data/contracts.py`, `docs/schema.md`). The new PoC reuses its core but versions it to
`retail_v2` for locations, post-sale adjustments, temporal cost and explicit point-in-time
semantics. The profile/adapter normalization layer and shared domain transforms map client
extracts into these once; everything downstream is source-neutral.

| Entity | Grain | Required fields | Feeds on this screen |
|---|---|---|---|
| `sales` | SKU × demand location × **day × availability version** | `sku_id, store_id, date, sales_version, units, net_sales_amount, known_as_of` (+ `net_price, promo_flag`) | Every KPI, Forecast-vs-Actual, workbench Baseline/Last-Actual, accuracy/bias |
| `sales_adjustments` | post-sale event × availability version | `adjustment_id, adjustment_version, sku_id, store_id, sale_date, event_date, event_type, known_as_of` (+ conditional `units` or `amount`) | Physical returns/post-fulfilment cancellations and financial refunds without rewriting fulfilled-sales history |
| `sales_fulfillments` | fulfillment line × availability version | `fulfillment_line_id, fulfillment_version, source_sale_id, sku_id, demand_location_id, supply_location_id, sale_date, fulfilled_at, units, known_as_of` | Bridges online/POS demand to the physical supply node; split-fulfillment and inventory reconciliation |
| `products` | SKU | `sku_id, dept_id, category, sub_cat, pack_size` (+ `product_name, brand, shelf_life_days, reference_cost`) | Category filter, SKU labels, pack rounding, expiry |
| `locations` | store/online/DC/3PL | `location_id, type ∈ {store, online, dc, 3pl}, region, active` (+ `format, channel, parent_dc`) | Authoritative location hierarchy; derives the demand-only `stores` compatibility view |
| `calendar` + `calendar_events` | day / event×date | `date, known_as_of` (+ event name/type) | Seasonality & event drivers, exception "New product / event" |
| `sell_prices` | SKU × store × **week** | `sku_id, store_id, effective week, net_price` | Price-movement driver, scenario price axis, pricing |
| `stock_snapshots` | SKU × location snapshot | `sku_id, location_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | Demand-at-risk, stock-out risk, required-inventory in scenarios |
| `suppliers_leadtimes` | dept | `dept_id, supplier_id, lead_time_days, moq, pack_qty, known_as_of` | Safety-stock / required-inventory, replenishment linkage |
| **pricing metadata** block | — | currency, `minor_unit_exponent`, price/cost unit & tax basis | Money semantics for all ₹ figures + multi-currency |

**History depth.** The feature set uses a 52-week seasonal lag, so **>52 complete weeks is
the technical minimum; 18–24 months is the practical pilot minimum; 2–3 years is preferred**
for the 13/26-week horizons and rolling evaluation the screen shows.

**Point-in-time discipline (critical) [REUSE].** Every temporal entity needs `known_as_of`
(when the fact became available to the decision process, not the transaction date). This is
mandatory for every temporal canonical output from a client-shaped profile — the adapter fails
closed without it.
`CLIENT_SHADOW` can never use a same-day fallback. It is what makes the screen's accuracy/bias
numbers honest rather than leaked.

### 2.2 NEW external-signal feeds the screen demands **[NEW]**

The **Demand Drivers** tab shows an *External Signal Readiness* panel and a driver-contribution
table with **Competitor availability (8%)** and **Weather & local events (7%)** — signals the
current `retail_v1` contract does **not** carry (M5 only has national calendar events + SNAP +
prices). These are the biggest data gap. Proposed new canonical entities:

| New feed | Suggested grain | Key fields | Drives |
|---|---|---|---|
| `competitor_prices` | SKU/product-match × store-or-region × week | `match_key, comp_name, region/store, week_start, comp_price, in_stock_flag, known_as_of` | "Competitor availability" & "Competitor stock-out" drivers; scenario *Competitor Availability* axis; pricing competitor bound |
| `weather` | store/region × day | `region/store, date, temp, precip, weather_code`; **plus forward forecast** `forecast_date, target_date, …` | "Weather & local events" driver; scenario *Weather/Event Impact* axis |
| `local_events` | store/region × date | `region/store, date, event_name, event_type, expected_impact, known_as_of` | "Local event anomaly" primary driver; store-level exceptions |
| `macro_index` | region × week | `region, week_start, index_name, value, known_as_of` | Macroeconomic external signal (weekly) |
| `fx_rates` | currency × rate date | `base_ccy (INR), quote_ccy, rate, rate_date, known_as_of` | Multi-currency display only (see 2.4) |

All must respect the same `known_as_of` rule (a **forecast** weather value or a promo-calendar
entry must not be "known" before its real publication date, or it leaks).

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

### 2.4 Multi-currency **[NEW, display-only]**

The dashboard stores figures in **base currency INR** and converts at display time using
fixed demo FX rates (`₹1 = rate`, 5-dp), explicitly flagged as replaceable "with a live FX API
or ERP rates." So the data requirement is: **store all money in base-currency minor units**
(already the PoC convention — integer minor units) and add an **as-of-dated `fx_rates` table
or a live FX feed** used purely for presentation. FX is **not** a model input and must never
enter forecasting/pricing math (which stays in base currency).

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

### 4.1 Two-stage ingestion data-quality gate **[REUSE + EXTEND — `data/quality_checks.py`]**

A promotable full/capability publication receives `status = pass` iff **both gates have zero
critical violations**. A passing raw gate never implies that the source has canonical meaning,
and a canonical gate is never allowed to hide discarded or unreconciled source rows. A partial
source such as Shopify may receive `status = validated_partial` after its declared canonical
slice passes the applicable Gate-B rules; that status is adapter evidence only and cannot feed
models or masquerade as a complete curated publication.

**Gate A — raw/source-profile validation (before transformation):**

- manifest and content hashes match; expected files/tables and extract window are present; an
  event/API connector supplies its required authenticity attestation and proves that the approved
  field projection happened before immutable landing;
- declared entity/field coverage, capability claims, companion expectations and approved mapping
  configuration references are present and version-resolvable;
- source schema is parseable and required source keys exist; duplicate source rows and a
  conflicting reuse of a snapshot ID are rejected, while an exact replay of the same
  snapshot-ID/content-hash pair is an idempotent no-op linked to the prior result;
- declared timezone, currency, tax basis, quantity unit and source grain are available;
- input, filtered, rejected and accepted row counts reconcile, with reason-coded quarantine rows;
- source control totals (quantity and money where supplied) are recorded before transformation.

**Gate B — canonical `retail_v2` validation (after transformation):**

- required columns/types, non-null fields, canonical grain, explicit monotonic version keys and
  unique business keys;
- negative units; non-positive price; per-series **date gaps** after resolving the applicable
  availability version (distinct-date vs span, so duplicates cannot mask a missing day); and
  product/pack/shelf-life rules;
- `known_as_of` placement, no future knowledge at an earlier decision cutoff, and source/
  transformation provenance on every derived or synthetic value;
- stock/receipt placement, non-negative inventory, ATP-method equation, disjoint
  on-order/in-transit reconciliation, positive lead/MOQ/pack, cost-ledger completeness when a
  cost-dependent capability is enabled, and cross-entity referential integrity;
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

### 4.4 Bias, drift & freshness tolerances **[REUSE + surface]**

Map directly to the Governance/KPIs: **Forecast Bias target ±5%** (KPI); **model-drift within
tolerance** and **data-freshness compliance** metrics (Governance tab). Freshness is measured
against the accepted forecast's `decision_as_of`, **never wall-clock** — carry that over.

### 4.5 Inventory service-level policy **[REUSE — `config/policy.yaml`, `engines/policy_*`]**

Per-ABC service levels **A 0.96 / B 0.90 / C 0.80** (bounded [0.5, 0.999]); review 7 d; max
cover 30 d; hold/markdown thresholds. Governed by **calibration on a deterministic 5% cohort +
validation on the untouched 95% holdout**, both bound to the same forecast fingerprint. This
governs the safety-stock / demand-at-risk numbers.

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
| FX rates (display) | **[NEW]** |
| Forecast-version records + Compare-Versions | **[NEW]** (fingerprints exist; add version table) |
| Planner-adjustment records with reason codes + value-added flag | **[NEW]** |
| Per-series confidence % + data-quality class surfacing | **[NEW]** (compute from existing) |
| Competitor/weather driver groups + uplift sensitivities | **[NEW]** |
| Governance SLA tracking + drift/freshness metrics surfacing | **[NEW]** (governance exists; add SLA clock) |
| Longer horizons (13/26 wk) | **[NEW]** (extend existing forecaster) |

---

## 6. Part E — Recommended pilot data extract

Mirror the existing client-data guidance (`docs/retailer_data_poc_guide.md`) for the new PoC:
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
**new models**, and **screen-specific guardrails** are called out. All money is base **INR**;
all actions are **shadow-only** (§4.9) — the dashboard's "Send to ERP", "Approve", "Publish"
etc. are demo toasts, and a real PoC keeps them shadow (reviewed ≠ executed).

### 8.1 Pricing cluster

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
status). REUSE and extend the quality battery (`data/quality_checks.py`) +
`quality_violations`. Guardrail: any promoted capability has zero critical violations in its
full two-gate run; fail closed on missing `known_as_of`; synthetic labelling is never hidden.

**Model Management** — three model families map exactly to §3 (Demand Forecast, Price Elasticity, Stock-out Risk). REUSE MLflow + artifact fingerprints. **NEW:** model-drift/monitoring records + **drift threshold 0.15**, deployment status {Production/Review}, retraining schedule {Weekly / Monthly / On-Drift}. Governance callout enforces: min margin, max price move, protected SKUs, human approvals, explainability, audit — all before "Production".

**User Management** — **NEW: full RBAC** (users, roles, scope {category/region/store/enterprise}, approval limit, status {Active/Restricted/Invited}). The named-**actor** plumbing (`approvals`, `audit_log`, `policy_edits`, `price_rec_reviews`) is REUSE; identity/role/scope management is new. Approval limits map to §4.7 tiers.

**Settings** — this screen **is the guardrail-config surface**: Minimum Margin, Maximum Discount, Maximum Price Increase, Min Days Between Changes, Forecast Horizon, Service Level Target, Overstock/Dead-Stock thresholds, Approval-Workflow tiers, currency/timezone/fiscal-year. **NEW:** a persisted, versioned, **audited** config object; each value maps to an existing REUSE config (`pricing_rules.yaml`, `policy.yaml`, `HORIZONS`, `workflow_service.py`). Every edit → `policy_edits` (lead/admin-gated). *Note the UI demo values differ from the strict PoC values (20% vs 12% margin floor, 10% vs 5% max move, flat 95% vs A/B/C, 12-wk vs 26-wk horizon) — treat the UI numbers as demo defaults, not the enforced policy.*

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
| FX rates (display-only) | All money figures |

---

## 9. Synthetic data generation

> **Where this runs:** initially in the isolated, extract-ready `datagen/` package; it may later
> move to a separate repo. It depends only on `contracts/`, never on `ml/` or `api/`.
>
> **What it publishes:** one deterministic internal retail truth in two publication modes:
> `SYNTHETIC_CANONICAL_TEST` (exact §11 fixtures for component tests) and
> `SYNTHETIC_CLIENT_SHAPED_TEST` (multiple retailer/platform-shaped source dialects for the real
> landing, transformation and quality path). Only the first uses canonical filenames/columns.

The M5 PoC generates realistic synthetic retail data in **two distinct layers** the generator
repo should mirror. Understanding the split is the key to knowing what to synthesize:

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
- **gate:** launch/retirement + intermittency (new-product ramp over ~6 weeks; dead/retired
  series stay zero) — this is what produces the "new product / sparse history" cohort.
- **pandemic_mult / weather_mult:** see §9.4.

Prices are a separate stream: real anchor × cumulative inflation index × **promo dips**
(≈10% of weeks get a 0.75–0.90 price multiplier). `promo_flag` is then *derived*, not drawn.

### 9.2 How the operational master data is synthesized (the mandatory fields)

In `data/ingest_m5.py`, each canonical field is generated deterministically (all labelled
`*_source = synthetic`). These formulas are the template for the new PoC's generator:

| Canonical field | Synthesis rule (M5 reference) |
|---|---|
| `products.reference_cost` | M5 reference only: `round(category_median_price × (1 − assumed_margin), 2)`; this is a labelled synthetic scenario value, not temporal cost authority |
| `products.pack_size` / `unit` | `hash(sku_id) % 4 → {1,6,12,24}`; `unit = each` iff pack_size = 1 |
| `products.shelf_life_days` | FOODS 21 / HOUSEHOLD 365 / HOBBIES 730 |
| `sales.promo_flag` | `net_price < 0.95 × median(net_price over 28 trailing days)` (**derived from price**, not an input) |
| `sales.known_as_of` | same-day for M5 (a real feed maps its true availability date) |
| `suppliers_leadtimes` | `supplier_id = SUP_<dept>`, `lead_time_days = 2 + hash%6` (2–7), `moq = hash%4 → {12,24,36,48}`, `pack_qty = hash%3 → {6,12,24}` |
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

1. **Fix the canonical semantic target first.** The generator's internal truth satisfies §11,
   including grains, keys, point-in-time availability, provenance and integer-minor-unit money.
   A publisher may then render that truth as canonical files or as a source-shaped dialect.
2. **Build dimensions and drivers before demand:** products, locations/DC hierarchy, suppliers,
   calendar/events, regular/promo prices, explicit promotions, competitor observations, weather,
   local events and macro. This preserves the causal relationships the models are expected to
   rediscover.
3. **Localize the base demand model** for Indian multi-category retail: replace M5's borrowed
   template with an explicit seasonal profile (weekly Fourier + Indian festival/monsoon/EOSS
   bumps), per-category base levels, elasticity, and an intermittency/new-product gate.
4. **Use one inventory-consistent event loop.** Draw internal `latent_demand`, receive/dispatch
   supply, compute ATP, then emit realized non-negative `sales.units = min(latent_demand, ATP)`
   plus `sales_fulfillments` linking every realized unit to its physical supply location. Emit
   exact `net_sales_amount` independently of rounded unit price. Keep lost demand as a generator
   diagnostic/control total rather than silently allowing sales and stock to contradict each
   other. Seed opening inventory from a 28-day burn-in that does not inspect future demand.
5. **Reuse operational synthesis patterns** from §9.2 (stable pack/MOQ/lead-time hashes and the
   independently derived 28-day rolling-median `promo_flag`), localized for Footwear/Apparel/
   Electronics/Beauty. Do **not** use price-derived assumed cost as a temporal cost ledger:
   generate `purchase_receipts` at changing costs and let the PoC compute WAC/FIFO as of time.
6. **Synthesize the NEW feeds with the same discipline** (determinism + `known_as_of`):
   - **Competitor products/prices/availability** — a small set per category with matchable
     brand/model/GTIN-like attributes, prices as a noisy function of your own price ± a gap, and
     occasional OOS spells. If the generator keeps match ground truth for evaluation, publish it
     as a test-only artifact; canonical `competitor_matches` remains a PoC output.
   - **Weather** — reuse `WeatherEngine` (region×day anomaly + product-type sensitivity), keyed
     to Indian cities; emit both actuals and a forward-weather series with a real `known_as_of`.
   - **Local events** — city×date festival/event calendar with demand multipliers.
   - **Macro index** — a slow region×week series (e.g. consumption index).
   - **FX rates** — an as-of-dated INR→USD/EUR/GBP series (display only).
   - **Promotions & segments** — explicit promo records (type/depth/period/scope) and a
     customer-segment mix, so the Promotion Planner and its uplift/cannibalisation models have inputs.
7. **Publish canonical and source-shaped outputs from the same run identity:**
   - `canonical_test/` — exact `retail_v2` Parquet for contract/unit/model tests;
   - `client_shaped_test/<dialect>/` — source-style CSV/Parquet/JSONL plus a source manifest and
     versioned profile. At minimum provide a generic retailer dialect and a privacy-safe
     `shopify_shaped` dialect. The generic dialect covers every `[in]` domain. The pure Shopify
     dialect intentionally covers only Shopify-supported entities/fields; publish separate
     synthetic `pim_erp_wms_external` companion feeds for product taxonomy/pack data,
     receipts/cost, suppliers, batches, procurement and external signals when testing a complete
     Shopify-led PoC.
8. **Golden round-trip acceptance:** land each client-shaped dialect and transform it through
   `ml/data`. The generic dialect must equal the full internal canonical truth. The pure Shopify
   dialect receives `validated_partial` only after matching its manifest-declared canonical
   coverage; it is not a model input. The Shopify-plus-companion suite must equal the full truth
   and control totals and receive full Gate-B `pass`. End-to-end acceptance must not use the
   canonical bypass.
9. **Keep the same guardrail posture:** deterministic seeds, immutable publication, boundary
   validation and per-output content hashes. Every source-shaped snapshot passes Gate A; only a
   capability-complete dataset that also passes full Gate B may reach a model (§4.1). A canonical
   component fixture bypasses Gate A/transformation but still passes Gate B.

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
file and a canonical test fixture have different physical schemas and grains. Enforced by
`data/contracts.py` — a NULL or missing REQUIRED canonical column raises at ingestion:

| Entity | **REQUIRED** | Optional |
|---|---|---|
| `sales` | `sku_id, store_id, date, sales_version, units, net_sales_amount, known_as_of` | `net_price, gross_sales_amount, discount_amount, tax_amount, promo_flag` |
| `sales_adjustments` | `adjustment_id, adjustment_version, sku_id, store_id, sale_date, event_date, event_type, known_as_of` | conditional `units, amount`; `source_sale_id, source_parent_event_id, reason_code` |
| `sales_fulfillments` | `fulfillment_line_id, fulfillment_version, source_sale_id, sku_id, demand_location_id, supply_location_id, sale_date, fulfilled_at, units, known_as_of` | `shipment_id, carrier_status` |
| `products` | `sku_id, dept_id, category, sub_cat, pack_size` | `product_name, brand, shelf_life_days, reference_cost` |
| `locations` | `location_id, type, region, active` | `name, city, parent_dc, format, channel` |
| `calendar` | `date, known_as_of` | event attributes |
| `suppliers_leadtimes` | `dept_id, supplier_id, lead_time_days, moq, pack_qty, known_as_of` | — |
| `stock_snapshots` | `sku_id, location_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | `committed_units, reserved_units, damaged_units, in_transit_units, atp_units, atp_method` |

For every profile, canonical temporal entities require `known_as_of`. A deliberately named unit
test fixture may opt into a same-day assumption, but `SYNTHETIC_CLIENT_SHAPED_TEST` and
`CLIENT_SHADOW` may not. `CLIENT_SHADOW` required fields cannot be filled by profile defaults.

Four nuances that surprise people:
- `sales.units` and `net_sales_amount` are cumulative **fulfilled/realized merchandise quantity
  and exact net merchandise value for the sale date as known at that availability version**.
  Select the latest version at or before the decision cutoff, never sum availability versions.
  `net_sales_amount` is the money-reconciliation authority; aggregated `units × net_price` may
  differ because the row can contain multiple line prices and discounts. Pre-fulfilment
  cancellations never enter `sales`.
  Later physical returns/post-fulfilment cancellations and financial refunds append
  `sales_adjustments`. `sales_adjustments.units` and `.amount` are non-negative reversal
  magnitudes (INR paise for amount), never signed values; each event has at least one positive
  measure. Coupled source records are decomposed into stable physical and financial child events
  so net-unit and net-revenue views cannot double count them. Any legacy
  `gross_units/cancelled_units/returned_units` columns are derived views, not canonical inputs.
- `products.reference_cost` is optional descriptive master data, **not** the temporal margin
  authority. Cost-dependent capabilities require `purchase_receipts` (or an approved equivalent
  cost ledger) and the derived as-of `inventory_cost`; otherwise they remain unavailable or are
  explicitly labelled synthetic scenarios.
- `locations` is authoritative. For reused demand-model code, ingestion derives a compatibility
  `stores` view for `type ∈ {store, online}` with `store_id = location_id`; sales/sell-price
  demand grains continue to use that alias, while inventory/cost/shipment grains use
  `location_id`.
- `sell_prices` and `calendar_events` aren't in the required set, but **pricing/elasticity
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
  basis). Without it you can still forecast, replenish, and show a *labelled* margin scenario,
  but not a client-true margin.

### 10.4 What you must supply to light up each capability

| To populate… | You must supply (beyond the always-required sales/products/locations/calendar) |
|---|---|
| Demand Forecast, accuracy, bias | ≥52 wk (ideally 18–24 mo) daily `units` + `known_as_of` |
| Replenishment, safety stock, cover | `stock_snapshots` with reconciled `atp_units/atp_method`, disjoint on-order/in-transit + `suppliers_leadtimes` (lead, MOQ, pack) + service-level policy |
| Margin, price recommendations | actual `purchase_receipts` (or approved temporal cost ledger) → as-of `inventory_cost` + qualifying `sell_prices` panel + pricing metadata |
| Price elasticity, simulation | the qualifying price panel above (levels/transitions/coverage) |
| Competitor Monitor, competitor driver | `competitor_products` match attributes + competitor price/availability; the PoC produces governed `competitor_matches` |
| Promotion Planner | promotion records (type/depth/period/scope) + customer segments |
| Weather / local-event / macro drivers | weather (actual + forecast), local-event, macro feeds — each with `known_as_of` |
| Multi-echelon inventory, ageing, expiry | location nodes (store/online/DC/3PL) + inbound-shipment state + disjoint inventory buckets/reconciled ATP + **lot/batch + receipt/expiry dates** |
| Valuation | approved temporal cost ledger → as-of `inventory_cost` + provision policy (+ ERP/WMS reconciliation feeds) |
| Multi-currency display | FX rate table (INR→USD/EUR/GBP, as-of dated) |
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

This is the **canonical contract produced by ingestion and consumed downstream**. A canonical
generator fixture may materialize these entities directly; retailer/platform/client-shaped
sources normally do not. Their raw files/objects are transformed into these entities under a
versioned profile and adapter. Column tables are compact; full field semantics will live in the
machine-readable contract and data dictionary under `contracts/`.

### 11.0 Conventions

- **Entity ownership tag:** `[in]` = canonical input produced by ingestion from a generator or
  authorized source; `[poc]` = produced by the PoC at runtime; `[cfg]` = version-controlled
  configuration; `[test]` = evaluation-only truth never exposed as a client fact. Historical
  `[gen]` labels in earlier sections mean `[in]` from the local generator.
- **Row provenance is separate from entity ownership.** Use controlled labels such as
  `SYNTHETIC`, `SHOPIFY_ACTUAL`, `SHOPIFY_DERIVED`, `ERP_ACTUAL`, `EXTERNAL_ACTUAL`; a real
  engagement must never present synthetic values as client facts.
- **Keys:** `sku_id`, `store_id`/`location_id`, `supplier_id`, `comp_id` are stable strings.
  `locations` is authoritative. `stores` is a curated compatibility view over demand locations
  (`store_id = location_id` for `type ∈ {store, online}`).
- **Dates/times:** business dates are ISO `YYYY-MM-DD`; source events/observations may be
  timestamps. **Every temporal entity carries `known_as_of`**, the earliest defensible
  availability timestamp/date for that fact. It may be later than the business/effective date.
  A late correction appends an adjustment/version and never rewrites what an earlier cutoff knew.
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
  Values are non-negative magnitudes (amount in INR paise), never signed.
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
- **Money:** canonical base currency is **INR** and all canonical monetary values are integer
  **minor units** (paise, `minor_unit_exponent = 2`). Raw sources may use decimal major units only
  when the profile declares currency/unit/tax basis and an exact decimal conversion. Generator
  canonical mode emits paise. `net_sales_amount` is always exact; when gross/discount components
  are supplied they must satisfy
  `gross_sales_amount - discount_amount = net_sales_amount` on the declared exclude-tax basis,
  while `tax_amount` reconciles separately. When one exact source amount spans multiple canonical
  rows, the profile names the allocation basis and the transform allocates integer paise with a
  largest-remainder method plus a stable business-key tie-break. At every version/cutoff,
  canonical children plus an explicit not-yet-fulfilled/filtered/quarantined residual must sum
  exactly to the source control total; rounded unit prices are never used for the allocation.
  FX is display-only (`fx_rates`); never a model input.
- **Grain** is stated per entity. Source profiles may declare different raw grains; mapping,
  joins and semantic transformations produce these canonical grains (§11.10).
- **Publication lineage:** every curated run records `source_system`, `source_schema_version`,
  `source_snapshot_id` and raw hashes, profile/adapter/transform versions, ingest run/time,
  coverage/composite-manifest hashes and capability mask, `known_as_of` rules,
  input/filtered/rejected/output counts and quantity/money reconciliations.

### 11.1 Core canonical entities `[in]` — REUSE + VERSION (from `retail_v1`)

The M5 fields are retained where useful, but `retail_v2` makes point-in-time availability,
location ownership, money and post-sale adjustments explicit. One sample row each (grain in
parentheses).

| Entity (grain) | Key columns | Sample row |
|---|---|---|
| `sales` (SKU×demand-location×day×availability version) | `sku_id, store_id, date, sales_version, units, net_sales_amount, net_price, promo_flag, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 1, 8, 8799200, 1099900, false, 2026-07-15T23:59:00+05:30` |
| `sales_adjustments` (post-sale event×availability version) | `adjustment_id, adjustment_version, source_parent_event_id, sku_id, store_id, sale_date, event_date, event_type, units, amount, known_as_of` | `ADJ-R44-PHYS, 1, RET-R44, NK-AM270-BLK-09, MUM01, 2026-07-15, 2026-07-28, physical_return, 1, null, 2026-07-28T15:02:00+05:30` |
| `sales_fulfillments` (fulfillment line×availability version) | `fulfillment_line_id, fulfillment_version, source_sale_id, sku_id, demand_location_id, supply_location_id, sale_date, fulfilled_at, units, known_as_of` | `FUL-L44, 1, ORD-44, NK-AM270-BLK-09, VIRTUAL_ONLINE, WHDC-W, 2026-07-15, 2026-07-16T10:20:00+05:30, 8, 2026-07-16T10:22:00+05:30` |
| `products` (SKU) | `sku_id, dept_id, category, sub_cat, pack_size, product_name, brand, shelf_life_days, reference_cost` | `NK-AM270-BLK-09, FTW-RUN, Footwear, Running, 1, "Nike Air Max 270", Nike, null, 630000` |
| `stores` (curated compatibility view; not a source entity) | `store_id, region, format, channel, city` | `MUM01, West, Large-format, in-store, Mumbai` |
| `calendar` (day) | `date, known_as_of, weekday, month, year, working_day` | `2026-07-15, 2020-01-01, Wed, 7, 2026, true` |
| `calendar_events` (event×date) | `date, region, event_name, event_type, known_as_of` | `2026-11-08, ALL, Diwali, festival, 2020-01-01` |
| `sell_prices` (SKU×store×week×availability version) | `sku_id, store_id, week_start, net_price, regular_price, promo_price, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-13, 1099900, 1199900, 1099900, 2026-07-13` |
| `stock_snapshots` (SKU×location snapshot) | `sku_id, location_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 48, 244, 2026-07-15T23:59:00+05:30` |
| `suppliers_leadtimes` (dept) | `dept_id, supplier_id, lead_time_days, moq, pack_qty, known_as_of` | `FTW-RUN, SUP_NIKE, 6, 24, 12, 2026-01-01` |

**Used in the PoC:** these feed the weekly feature build → LightGBM forecaster (§3.1),
reorder/safety-stock engine (§3.3), baselines/FVA, and every KPI in §2.5.

### 11.2 Cost & price history `[in]` + `[poc]` — NEW (solves §10.5)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `purchase_receipts` `[in]` (SKU×location×receipt) | `receipt_id, sku_id, location_id, supplier_id, receipt_date, qty, unit_cost, currency, known_as_of` | `RCP-0012, NK-AM270-BLK-09, MUM01, SUP_NIKE, 2026-03-10, 100, 660000, INR, 2026-03-12` |
| `inventory_cost` `[poc]` derived (SKU×location×as-of) | `sku_id, location_id, as_of_date, wac_cost, on_hand_qty, method, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 630000, 148, WAC, 2026-07-15T23:59:00+05:30` |

**Used in the PoC:** `purchase_receipts` is the **cost ledger** (the source of truth for cost
over time); the PoC rolls it into `inventory_cost.wac_cost` (moving-average, cost-as-of the
decision date) for **margin** and **inventory valuation**, while pricing/replenishment Order
Value uses the latest `unit_cost` (replacement cost). This is what makes margin correct when the
same SKU is replenished at different costs.

### 11.3 Competitor `[in]` + `[poc]` — NEW (Competitor Monitor, price responses)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `competitors` `[cfg]` (competitor) | `comp_id, name, type, region, collection_method, refresh, currency, compliance_ok` | `CMP_TW, TechWorld, Marketplace, ALL, api_feed, hourly, INR, true` |
| `competitor_products` `[in]` (competitor product version) | `comp_id, comp_product_id, title, brand, model, gtin, attributes, known_as_of` | `CMP_TW, TW-AIRPODS2, "AirPods Pro 2", Apple, MTJV3HN/A, null, "colour=white", 2026-07-15` |
| `competitor_prices` `[in]` (comp-product×region×obs) | `comp_id, comp_product_id, region, observed_at, price, in_stock_flag, promo_flag, known_as_of` | `CMP_TW, TW-AIRPODS2, Bengaluru, 2026-07-15T09:12, 2449900, true, false, 2026-07-15` |
| `competitor_matches` `[poc]` (our-SKU×comp-product) | `match_id, sku_id, comp_id, comp_product_id, match_confidence, match_status, matched_attributes` | `MTCH-081, APP-APP2-WHT, CMP_TW, TW-AIRPODS2, 0.96, matched, "brand;model;gtin"` |

**Used in the PoC:** the product-matching model (§8.1) links `competitor_prices` to `sku_id`
via `competitor_matches` (low-confidence stays in review, can't auto-trigger pricing); matched
competitor price/availability feeds the **competitor-availability demand driver** (§3.4) and the
price-recommendation competitor bound.

### 11.4 Promotions & customers `[in]` — NEW (Promotion Planner)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `promotions` (promo) | `promo_id, name, type, objective, offer_value, start_date, end_date, scope, segment_id, min_margin_pct, approval_route, status, owner, known_as_of` | `PR-Monsoon, "Monsoon Footwear Event", pct, revenue, 12, 2026-07-20, 2026-07-31, "West+Online", SEG_ALL, 20, category_mgr, draft, Emma, 2026-07-01` |
| `promotion_skus` (promo×SKU/category) | `promo_id, sku_id_or_category, discount_pct, known_as_of` | `PR-Monsoon, Footwear, 12, 2026-07-01` |
| `customer_segments` (segment snapshot) | `segment_id, name, size, share_pct, description, as_of_date, known_as_of` | `SEG_LOYAL, "Loyalty members", 480000, 38, "Active loyalty base", 2026-07-01, 2026-07-02` |

**Used in the PoC:** promotions feed the promo-uplift / cannibalisation / bundle models (§8.1)
and the promotion-overlap + inventory-readiness guardrails; `customer_segments` drive targeting
and the segment-response model.

### 11.5 External signals `[in]` — NEW (Demand Drivers, scenarios, multi-currency)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `weather_actual` (region/store×day) | `region, date, tavg_c, precip_mm, weather_code, known_as_of` | `Mumbai, 2026-07-15, 29.4, 62.0, rain, 2026-07-15` |
| `weather_forecast` (region×forecast×target) | `region, forecast_date, target_date, tavg_c, precip_prob, known_as_of` | `Mumbai, 2026-07-15, 2026-07-22, 30.1, 0.7, 2026-07-15` |
| `local_events` (region/store×date) | `region, date, event_name, event_type, expected_impact, known_as_of` | `Bengaluru, 2026-08-15, "City Marathon", civic, 1.2, 2026-07-01` |
| `macro_index` (region×week) | `region, week_start, index_name, value, known_as_of` | `West, 2026-07-13, consumption_index, 104.6, 2026-07-16` |
| `fx_rates` (currency×rate date) | `base_ccy, quote_ccy, rate, rate_date, known_as_of` | `INR, USD, 0.01205, 2026-07-15, 2026-07-15` |

**Used in the PoC:** weather/local-event/macro become forecast features + the weather and
competitor driver groups (§3.4) and the Scenario-Planning axes (§3.6); `fx_rates` is display-only
conversion (§2.4). All respect `known_as_of` — a forecast weather value can't be "known" before
its issue date.

### 11.6 Multi-echelon inventory `[in]` + `[poc]` — NEW

| Entity (grain) | Columns | Sample |
|---|---|---|
| `locations` `[in]` (location; authoritative) | `location_id, name, type, region, city, parent_dc, active` | `WHDC-W, "West DC Ahmedabad", dc, West, Ahmedabad, null, true` |
| `stock_snapshots` (extended) `[in]` | + `committed_units, reserved_units, damaged_units, in_transit_units, atp_units, atp_method` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 48, 244, 4, 2, 0, 30, 42, derived_buckets, 2026-07-15` |
| `inventory_batches` `[in]` (batch) | `batch_id, sku_id, location_id, batch_qty, mfg_date, expiry_date, receipt_date, unit_cost, known_as_of` | `BT-24A, BT-SERUM-30, MUM11, 320, 2026-05-01, 2026-08-05, 2026-05-04, 54000, 2026-05-04` |
| `inbound_shipments` `[in]` (shipment) | `shipment_id, sku_id, from_location, to_location, qty, dispatch_date, expected_receipt_date, status, known_as_of` | `SHP-3391, APP-APP2-WHT, WHDC-S, BLR03, 240, 2026-07-12, 2026-07-18, in_transit, 2026-07-12` |
| `transfer_orders` `[poc]` (transfer) | `transfer_id, sku_id, from_location, to_location, qty, reason, expected_benefit, status` | `TRF-0102, RUN-SHOE-9, KOL04, CHE06, 72, lost_sales_recovery, 320000, review` |
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
| `supplier_performance` (supplier×period version) | `supplier_id, period, otd_pct, capacity_confirmed_pct, lead_time_mean_days, lead_time_std_days, risk, known_as_of` | `SUP_ELECA, 2026-Q2, 0.81, 0.82, 8.6, 2.4, high, 2026-07-10` |

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
| `roles` | `role_id, name, approval_limit, scope_type` | `[cfg]` |
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

**Reuse as-is from the M5 PoC (migration 001/002/003):** `workflow_sessions`, `draft_orders`,
`approvals`, `exceptions`, `exception_notes`, `exception_status_history`, `audit_log`,
`policy_edits`, `price_recs`, `price_rec_reviews`, `adoption_metrics`. These already implement
named-actor, idempotency, audit, and shadow-only semantics (§4.7) — copy the schema unchanged.

### 11.10 Source profiles, transformations and ownership

| Ownership | Entities / artifacts |
|---|---|
| **`[in]`** canonical input (generator or authorized source → ingestion) | sales, sales_adjustments, sales_fulfillments, products, locations, calendar, calendar_events, sell_prices, stock_snapshots, inventory_batches, inbound_shipments, suppliers_leadtimes, supplier_performance, purchase_receipts, competitor_products, competitor_prices, promotions, promotion_skus, customer_segments, weather_actual, weather_forecast, local_events, macro_index, fx_rates |
| **Curated compatibility/derived during ingest** | `stores` view from demand locations; normalized business calendar |
| **`[poc]`** produced at runtime | ingest_runs, reconciliation_results, quality_violations/quarantine_records, source_crosswalks, inventory_cost, competitor_matches, transfer_orders, allocations, forecast_versions/series/drivers, planner_adjustments, model_registry, model_drift, + all workflow tables |
| **`[cfg]`** version-controlled | competitors, users, roles, data_sources, source_mapping_configs, alert_rules, source-profile schema, guardrail config (`pricing_rules.yaml`, `policy.yaml`) |
| **`[test]`** never served as client fact | generator internal canonical truth, optional competitor-match truth and source-dialect golden results |

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

Every source snapshot declares machine-readable coverage; absence is never inferred from missing
files. The manifest contract contains:

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
source_classification: SYNTHETIC_CLIENT_SHAPED_TEST
source_system: retailer_a_pos
source_schema_version: v1
raw_dir: /data/raw/retailer_a/snapshot_2026_07
manifest: manifest.json
business_timezone: Asia/Kolkata
money: {currency: INR, source_unit: major_decimal, canonical_unit: paise, tax_basis: exclude_tax}
coverage:
  mode: partial
  canonical_entities:
    sales: {completeness: complete,
            fields: [sku_id, store_id, date, sales_version, units, net_sales_amount, known_as_of],
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
                                 qty, unit_cost, currency, known_as_of], zero_rows_valid: true}
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
`CLIENT_SHADOW` profiles cannot default mandatory facts or manufacture `known_as_of`.
`SYNTHETIC_CALIBRATED` values may enter only a separately declared demo/scenario capability;
they do not satisfy a client-actual required-field gate and cannot be mixed into client-actual
metrics or decisions.

#### End-to-end ingestion flow

1. Connector/generator writes an immutable source snapshot and manifest to the raw landing zone.
2. Gate A validates raw hashes, schema, keys, extract window and source control totals.
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
connector runs only in a client-controlled environment; locally, `datagen` publishes a fully
synthetic, direct-identifier-free and protected-field-minimized `shopify_shaped` fixture.

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
with `source_classification: SYNTHETIC_CLIENT_SHAPED_TEST` and
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
business_timezone: Asia/Kolkata
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
  currency: INR
  canonical_unit: paise
  tax_basis: exclude_tax
  order_refund_money_bag: shopMoney
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
    locations: {completeness: complete, fields: [location_id, type, region, active],
                condition: approved_location_mapping_and_virtual_node}
    sales: {completeness: complete,
            fields: [sku_id, store_id, date, sales_version, units, net_sales_amount, known_as_of],
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
                  fields: [sku_id, store_id, week_start, net_price, known_as_of],
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

Profile conditions are resolved when the source manifest is written. A condition-false entity is
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
| `Location` + approved virtual demand node | physical `locations` through a versioned, retailer-approved `source_mapping_configs` crosswalk for store/DC/3PL, region and city; materialize `VIRTUAL_ONLINE` as a canonical `type=online` location with `SHOPIFY_DERIVED` provenance; record resolved mappings in `source_crosswalks` |
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
- Merchandise money uses exact decimal `shopMoney` conversion to INR paise; shipping, duties and
  tax remain separate. Canonical `net_sales_amount` is the exact aggregated merchandise amount
  after allocated discounts on the declared tax basis; `net_price` is never used to rederive the
  control total. Use Shopify line allocations when authoritative. If an order-level amount spans
  lines or a line spans partial/split fulfillments, allocate integer paise by fulfilled-unit
  basis using largest remainder and stable line/fulfillment GID ordering; recompute cumulative
  availability versions from the same rule. At each cutoff, fulfilled child paise plus the
  explicit unfulfilled/filtered/quarantined remainder must equal the source line/order control;
  when every in-scope merchandise amount is resolved and fulfilled, final children sum to that
  in-scope source amount with no penny drift. Refund allocations follow the same exact rule.
  Transformed gross/discount/net/tax totals reconcile to source orders plus declared residuals.
  `presentmentMoney` is audit/display-only. A non-INR shop fails until an accounting conversion
  policy is approved.
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
