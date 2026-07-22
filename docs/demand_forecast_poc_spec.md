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
a fresh codebase that **copies the proven modules** from it (adapter, features, forecaster,
reorder/pricing engines, guardrails, workflow). File references point at the M5 repo so the
new build can lift the pattern rather than reinvent it.

### Architecture & data flow (read this first)

The new PoC has a **hard split between data production and data consumption**:

```
[ separate data-generation repo ]                 [ this new PoC ]
 generates CSV / Parquet files      ── files ──▶   ingest → transform → model → engines → workflow/API/UI
 (demand, prices, cost, inventory,                 (does NOT generate data)
  competitor, weather, events, …)
```

- **The generator repo owns "how the numbers are made"** — the demand/price/pandemic/weather
  logic described in §9 lives *there*, and it emits flat CSV/Parquet files per entity.
- **This PoC owns "ingest → decide → serve."** Its entry point is the **`mapped_files`
  adapter** (already proven in the M5 PoC): one profile YAML maps the generator's file/column
  names onto the canonical contract, quality checks run, features build, models score, engines
  recommend, and the UI serves. No data-generation code lives in the PoC.
- **The contract between the two repos is §11 (the schema).** The generator must emit files
  whose columns match §11; the PoC validates them at the ingest boundary and fails closed on a
  mismatch. This is exactly the `CLIENT_SHADOW` / `SYNTHETIC_CLIENT_SHAPED_TEST` adapter path —
  the generator plays the role of the "authorized client extract."

### Technology stack — Python ML pipelines + Go API

The new PoC is **polyglot**: **ML pipelines in Python, the API/serving layer in Golang.**

```
PYTHON (batch ML pipeline)                          GO (API / serving)
 ingest(mapped_files) → quality → features →         reads artifacts + PostgreSQL
 models(LightGBM P50/P90, Poisson-EB elasticity) →   serves REST/gRPC to the UI
 engines(reorder, pricing, allocation, ageing) →     owns workflow/HITL, guardrail
 writes ARTIFACTS (Parquet/JSON + manifests +   ──▶  re-validation, staleness 409/503,
 semantic fingerprints) to the lake + PostgreSQL      RBAC/auth, audit
```

What this means for the M5-PoC carry-over:
- **Python `[REUSE]` — copied ~as-is:** `data/` (ingest, quality, features), `models/`
  (forecasting, price_response, backtest), `engines/` (reorder, pricing, policy, simulator).
  These are LightGBM/statsmodels/DuckDB-native and stay Python.
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

Legend: **[REUSE]** = carry over the M5 PoC's proven design — copied as-is for the Python
ML/data/engine layers, **reimplemented in Go** for the API/serving/workflow layer;
**[NEW]** = build fresh (in the PoC, or — for data — in the generator repo).

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

### 2.1 Foundation: the canonical entities **[REUSE]**

The current PoC already defines a versioned, dataset-neutral contract `retail_v1`
(`data/contracts.py`, `docs/schema.md`). The new PoC should adopt it verbatim; a source
adapter maps client extracts into these once and everything downstream is unchanged.

| Entity | Grain | Required fields | Feeds on this screen |
|---|---|---|---|
| `sales` | SKU × store × **day** | `sku_id, store_id, date, units` (+ `net_price, promo_flag, known_as_of`) | Every KPI, Forecast-vs-Actual, workbench Baseline/Last-Actual, accuracy/bias |
| `products` | SKU | `sku_id, dept_id, category, sub_cat, cost, pack_size` (+ `product_name, brand, shelf_life_days`) | Category filter, SKU labels, margin/demand-at-risk (needs `cost`) |
| `stores` | store | `store_id, region` (+ `format, channel`) | Region/Store filters, Store View, Store Drilldown |
| `calendar` + `calendar_events` | day / event×date | `date, known_as_of` (+ event name/type) | Seasonality & event drivers, exception "New product / event" |
| `sell_prices` | SKU × store × **week** | `sku_id, store_id, effective week, net_price` | Price-movement driver, scenario price axis, pricing |
| `stock_snapshots` | SKU × store snapshot | `sku_id, store_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | Demand-at-risk, stock-out risk, required-inventory in scenarios |
| `suppliers_leadtimes` | dept | `dept_id, supplier_id, lead_time_days, moq, pack_qty, known_as_of` | Safety-stock / required-inventory, replenishment linkage |
| **pricing metadata** block | — | currency, `minor_unit_exponent`, price/cost unit & tax basis | Money semantics for all ₹ figures + multi-currency |

**History depth.** The feature set uses a 52-week seasonal lag, so **>52 complete weeks is
the technical minimum; 18–24 months is the practical pilot minimum; 2–3 years is preferred**
for the 13/26-week horizons and rolling evaluation the screen shows.

**Point-in-time discipline (critical) [REUSE].** Every temporal entity needs `known_as_of`
(when the fact became available to the decision process, not the transaction date). This is
mandatory for a real-client (`CLIENT_SHADOW`) profile — the adapter fails closed without it.
It is what makes the screen's accuracy/bias numbers honest rather than leaked.

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
| `fx_rates` | currency × date | `base_ccy (INR), quote_ccy, rate, as_of` | Multi-currency display only (see 2.4) |

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
| **KPI: Demand at Risk** | P50 forecast, on-hand+on-order, lead time, price/margin → lost-sales exposure ₹ |
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

### 4.1 Ingestion data-quality gate **[REUSE — `data/quality_checks.py`]**

`status = pass` iff **critical violations == 0**. Critical checks: negative units; non-positive
price; duplicate `(sku_id,store_id,date)` / product / store keys; department without supplier;
per-series **date gaps** (distinct-date vs span, so duplicates can't mask a missing day);
product field rules (cost > 0, `pack_size ∈ {1,6,12,24}`, `unit ∈ {each,pack}`, shelf-life);
stock-snapshot placement (`known_as_of` vs `snapshot_date`, `on_hand ≥ pack_qty`, positive
lead/MOQ/pack); and a **re-derived promo-rule check** (independently recomputes the 28-day
trailing median so a leaky ingest column can't alias past the gate). Warnings: stale/trailing-
stale prices > 180 days. → produces the per-SKU **Data Quality {Good/Watch/Issue}** class.

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
- Any synthetic fallback (cost, supplier, stock) must be **source-labeled `synthetic`** and never
  presented as a client fact; for a real-client profile, required fields cannot be synthetic.
- Shadow-only: no PO, price change, or ERP transaction is ever sent.

---

## 5. Part D — Reuse vs build-new summary

| Capability | Status |
|---|---|
| Canonical `retail_v1` contract + adapter boundary | **[REUSE]** |
| 7 core entities (sales/products/stores/calendar/prices/stock/suppliers) | **[REUSE]** |
| Point-in-time (`known_as_of`) + weekly feature build | **[REUSE]** |
| LightGBM horizon-quantile forecaster + Croston routing + blend | **[REUSE]** (extend to 26-wk horizon) |
| Baselines + Forecast Value Add | **[REUSE]** |
| Safety-stock / reorder / simulator | **[REUSE]** |
| SHAP driver attribution | **[REUSE]** (+2 new driver groups) |
| Price-response (Poisson GLM + EB) | **[REUSE]** |
| Data-quality battery, acceptance gates, service-level calibration | **[REUSE]** |
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
remaining screen is summarised by what it *adds*. The 7 canonical entities + the models in
§3 + the guardrails in §4 are assumed REUSE and not repeated; only the **new data points**,
**new models**, and **screen-specific guardrails** are called out. All money is base **INR**;
all actions are **shadow-only** (§4.9) — the dashboard's "Send to ERP", "Approve", "Publish"
etc. are demo toasts, and a real PoC keeps them shadow (reviewed ≠ executed).

### 8.1 Pricing cluster

**Price Recommendations** — SKU×store price-action workbench (Increase/Reduce/Hold) with tiered approval.
- Grain: one recommendation per SKU×store. Columns: Action, Current, AI Price, Change %, **Competitor price [NEW]**, Stock Cover, Forecast Demand, Current/Expected Margin, Revenue/Margin Impact, **AI Reason [NEW: explanation string]**, Confidence, Status, Owner.
- **NEW data:** competitor price; AI-reason string; priority tier; owner assignment; approval-SLA clock (open/avg-age/target per tier); adoption %; predicted-vs-realized variance; price-recommendation version records; a `channel` dimension (contract currently in-store only).
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

Overview + Store, Warehouse, Ageing, Transfers, Valuation, Expiry/Waste. These introduce a
**multi-echelon inventory domain** the current single-snapshot contract doesn't model.
- **NEW data domains:**
  - **Multi-echelon location master** — store vs **warehouse/DC** vs **in-transit** as first-class locations (current contract has stores only).
  - **In-transit / inbound shipments** — count, value, delayed flag, expected receipt; **dock-to-stock** time; warehouse **capacity/utilization**, **fill rate**, **blocked/quarantined stock**, **delayed receipts**.
  - **Inventory buckets** — **reserved**, **damaged/blocked**, **Available-to-Promise** (= on-hand − reservations).
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

**Data Management** — **NEW:** `data_sources` registry (type {API/Database/SFTP/CSV/External API}, refresh cadence, **field-mapping** = the adapter boundary, last-refresh, record count, per-source quality %, status). REUSE: the quality battery (`data/quality_checks.py`) + `quality_violations`. Guardrail: validation gate (critical-violations = 0), fail-closed on missing `known_as_of` for CLIENT_SHADOW, synthetic labelling.

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
| Multi-echelon location master (store/DC/in-transit) | All inventory + replenishment |
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

> **Where this runs:** in the **separate data-generation repo**, not in the PoC (see
> Architecture note). This section is the *reference approach* that repo should follow; its
> output is CSV/Parquet files matching §11, which the PoC then ingests. The M5 PoC generated
> data inline; the new split moves everything below into the generator repo.

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
| `products.cost` | `round(category_median_price × (1 − assumed_margin), 2)`; assumed margins FOODS 0.25 / HOUSEHOLD 0.35 / HOBBIES 0.45 — **i.e. cost is back-derived from price and an assumed category margin** |
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

1. **Fix the canonical target first.** Generate data that satisfies `data/contracts.py`
   `REQUIRED_COLUMNS` exactly (§10.1). Then every existing model/engine/UI runs unchanged.
2. **Localize the base demand model** for Indian multi-category retail: replace M5's borrowed
   template with an explicit seasonal profile (weekly Fourier + Indian festival/monsoon/EOSS
   bumps), per-category base levels, elasticity, and an intermittency/new-product gate.
3. **Reuse the operational-field synthesis** formulas in §9.2 (cost from assumed margin, pack/
   MOQ/lead-time hashes, 28-day burn-in stock seed, 28-day rolling-median `promo_flag`) — but
   swap category margins/shelf-life for Footwear/Apparel/Electronics/Beauty realities.
4. **Synthesize the NEW feeds with the same discipline** (determinism + `known_as_of`):
   - **Competitor prices/availability** — a small set of competitors per category, prices as a
     noisy function of your own price ± a gap, occasional OOS spells; plus a match table with a
     confidence score.
   - **Weather** — reuse `WeatherEngine` (region×day anomaly + product-type sensitivity), keyed
     to Indian cities; emit both actuals and a forward-weather series with a real `known_as_of`.
   - **Local events** — city×date festival/event calendar with demand multipliers.
   - **Macro index** — a slow region×week series (e.g. consumption index).
   - **FX rates** — an as-of-dated INR→USD/EUR/GBP series (display only).
   - **Promotions & segments** — explicit promo records (type/depth/period/scope) and a
     customer-segment mix, so the Promotion Planner and its uplift/cannibalisation models have inputs.
5. **Keep the same guardrail posture:** deterministic seeds, immutable publication, boundary
   validation, and the data-quality battery (§4.1) run over the synthetic output so it is
   provably clean before any model sees it.

---

## 10. Mandatory data elements & derived-metric dependencies

Your margin example generalises to a rule: **almost every headline number on the dashboard is
*derived*, and each derived metric has a hard list of upstream fields that must exist.** If an
upstream field is missing, the metric can't be computed honestly (and the PoC fails closed
rather than fake it). This section is the authoritative "what's mandatory" answer.

### 10.1 The canonical mandatory vs optional contract

Enforced by `data/contracts.py` — a NULL or missing REQUIRED column raises at ingestion:

| Entity | **REQUIRED** | Optional |
|---|---|---|
| `sales` | `sku_id, store_id, date, units` | `net_price, promo_flag, known_as_of`* |
| `products` | `sku_id, dept_id, category, sub_cat, `**`cost`**`, pack_size` | `product_name, brand, shelf_life_days` |
| `stores` | `store_id, region` | `format, channel` |
| `calendar` | `date, known_as_of` | event attributes |
| `suppliers_leadtimes` | `dept_id, supplier_id, lead_time_days, moq, pack_qty, known_as_of` | — |
| `stock_snapshots` | `sku_id, store_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | — |

\* For a real-client (`CLIENT_SHADOW`) profile, `sales.known_as_of` is **mandatory** (no same-day
fallback) and required fields **cannot** be filled by profile defaults.

Two nuances that surprise people:
- **`cost` is mandatory master data on `products`** even though `net_price` is only *optional*
  on `sales` — because margin, ABC value, and provisioning all need it.
- `sell_prices` and `calendar_events` aren't in the required set, but **pricing/elasticity
  screens need a real price panel** (see §10.2) — so they're mandatory *for those capabilities*.

### 10.2 Derived-metric dependency map

To your question — *"to calculate margin do we need purchase price?"* — **yes: margin needs unit
cost (your purchase price / landed cost) and selling price.** Here is the full map:

| Derived metric | Formula (as implemented) | Mandatory upstream fields |
|---|---|---|
| **Margin** | `margin_bp = ((price − cost) × 10000) // price` | `sell_prices.net_price` (or current price) **+ `products.cost`** |
| **Revenue (projected)** | `units = p50 × (price/price0)^beta` ; `revenue = units × price` | forecast **P50** + price + **elasticity β** |
| **Gross margin ₹** | `(price − cost) × units` | price + **cost** + units/forecast |
| **Markdown suggestion** | hold when `cover_days > 21`; `markdown_pct = 0.10` | forecast P50, `trailing_avg`, `cover_days` (= (on_hand+on_order)/avg_daily) |
| **Safety stock** | `RSS(P90−P50 over lead+review) × Φ⁻¹(SL)/Φ⁻¹(0.90)` | forecast **P50 & P90** + `lead_time_days` + `review_period` + `service_level` |
| **Reorder point / order-up-to** | `demand_over_lead(P50) + safety_stock (+ cycle_stock)` | above + on_hand + on_order + MOQ + pack_qty |
| **Demand at risk / stock-out proxy** | target = `P90`; risk when `actual > target`; exposure `= target × cost` | forecast **P90** + on-hand/actual demand + **cost** (to value it) |
| **ABC class** | `annualized_value = trailing_avg_weekly × 52 × cost`; A≤0.80, B≤0.95 cumulative | forecast trailing avg **+ cost** |
| **Price elasticity (β)** | Poisson GLM: `log E[units] = a + β·log(price) + controls` | **`sell_prices` panel with real variation** + `sales.units` |
| **Forecast (P50/P90)** | LightGBM horizon-quantile over the weekly feature set | `sales.units` with **≥52 wk** history + calendar + prices + `known_as_of` |
| **Forecast accuracy / bias / FVA** | WAPE, bias, vs-MA13 improvement over rolling origins | forecast + realized `units` + `known_as_of` (point-in-time) |
| **Stock cover / days-of-supply** | `inventory_position / avg_daily_demand` | on_hand + on_order + forecast |

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

| To populate… | You must supply (beyond the always-required sales/products/stores/calendar) |
|---|---|
| Demand Forecast, accuracy, bias | ≥52 wk (ideally 18–24 mo) daily `units` + `known_as_of` |
| Replenishment, safety stock, cover | `stock_snapshots` (on_hand, on_order) + `suppliers_leadtimes` (lead, MOQ, pack) + service-level policy |
| Margin, price recommendations | **actual `cost`** + `sell_prices` panel with real variation + pricing metadata (currency/unit/tax basis) |
| Price elasticity, simulation | the qualifying price panel above (levels/transitions/coverage) |
| Competitor Monitor, competitor driver | competitor price + availability feed + a product-match table |
| Promotion Planner | promotion records (type/depth/period/scope) + customer segments |
| Weather / local-event / macro drivers | weather (actual + forecast), local-event, macro feeds — each with `known_as_of` |
| Multi-echelon inventory, ageing, expiry | location master (store/DC/in-transit) + reserved/damaged/ATP + **lot/batch + receipt/expiry dates** |
| Valuation | actual cost + provision policy (+ ERP/WMS feeds for reconciliation) |
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
   date**, never a future cost. `products.cost` becomes a *derived current WAC snapshot*, not the
   source of truth; the **ledger is the source of truth**. Pricing/replenishment **Order Value**
   uses the **latest / replacement cost** (what the next PO will cost), which can differ from the
   WAC used for margin — so the schema keeps **both** (`inventory_cost.wac_cost` and
   `purchase_receipts.unit_cost`).

**Guardrail tie-ins:** point-in-time still applies — a receipt's `known_as_of` gates when its
cost enters the WAC, so a late-posted invoice can't retroactively rewrite a margin you already
reported. And §10.3's honesty rule holds: only a **non-synthetic, provenance-matched** cost
ledger unlocks a real margin objective; a generated cost ledger shows a *labelled* margin scenario.

---

## 11. Data schema (`retail_v2`)

This is the **contract between the generator repo and the PoC**. Every entity below is one
CSV/Parquet file the generator emits (or, where tagged `[poc]`, a table the PoC produces at
runtime). Column tables are compact; full field semantics for the reused core live in
`docs/schema.md`.

### 11.0 Conventions

- **Origin tag:** `[gen]` = a file produced by the generator repo and ingested; `[poc]` =
  produced by the PoC at runtime (forecasts, recommendations, audit); `[cfg]` = config/seed.
- **Keys:** `sku_id`, `store_id`/`location_id`, `supplier_id`, `comp_id` are stable strings.
- **Dates:** ISO `YYYY-MM-DD`. **Every temporal entity carries `known_as_of`** (availability
  date) — the ingest fails closed without it for a non-test profile.
- **Money:** base currency **INR**; decimals allowed in files, normalized to integer **minor
  units** (paise, `minor_unit_exponent = 2`) inside pricing per the pricing-metadata block.
  FX is display-only (`fx_rates`); never a model input.
- **Provenance:** generated fields carry a `*_source` label; a real engagement must not present
  synthetic values as client facts.
- **Grain** is stated per entity. `[gen]` files are the ingest surface; the `mapped_files`
  profile maps their column names → these canonical names (example in §11.10).

### 11.1 Core canonical entities `[gen]` — REUSE (`retail_v1`)

Copied unchanged from the M5 contract; only the *content* is Indian multi-category. One
sample row each (grain in parentheses).

| Entity (grain) | Key columns | Sample row |
|---|---|---|
| `sales` (SKU×store×day) | `sku_id, store_id, date, units, net_price, promo_flag, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 8, 10999, false, 2026-07-15` |
| `products` (SKU) | `sku_id, dept_id, category, sub_cat, cost, pack_size, product_name, brand, shelf_life_days` | `NK-AM270-BLK-09, FTW-RUN, Footwear, Running, 6300, 1, "Nike Air Max 270", Nike, null` |
| `stores` (store) | `store_id, region, format, channel, city` | `MUM01, West, Large-format, in-store, Mumbai` |
| `calendar` (day) | `date, known_as_of, weekday, month, year, working_day` | `2026-07-15, 2020-01-01, Wed, 7, 2026, true` |
| `calendar_events` (event×date) | `date, region, event_name, event_type, known_as_of` | `2026-11-08, ALL, Diwali, festival, 2020-01-01` |
| `sell_prices` (SKU×store×week) | `sku_id, store_id, week_start, net_price, regular_price, promo_price, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-13, 10999, 11999, 10999, 2026-07-13` |
| `stock_snapshots` (SKU×store snapshot) | `sku_id, store_id, snapshot_date, on_hand_units, on_order_units, known_as_of` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 48, 244, 2026-07-15` |
| `suppliers_leadtimes` (dept) | `dept_id, supplier_id, lead_time_days, moq, pack_qty, known_as_of` | `FTW-RUN, SUP_NIKE, 6, 24, 12, 2026-01-01` |

**Used in the PoC:** these feed the weekly feature build → LightGBM forecaster (§3.1),
reorder/safety-stock engine (§3.3), baselines/FVA, and every KPI in §2.5.

### 11.2 Cost & price history `[gen]` + `[poc]` — NEW (solves §10.5)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `purchase_receipts` `[gen]` (SKU×location×receipt) | `receipt_id, sku_id, location_id, supplier_id, receipt_date, qty, unit_cost, currency, known_as_of` | `RCP-0012, NK-AM270-BLK-09, MUM01, SUP_NIKE, 2026-03-10, 100, 6600, INR, 2026-03-12` |
| `inventory_cost` `[poc]` derived (SKU×location×as-of) | `sku_id, location_id, as_of_date, wac_cost, on_hand_qty, method` | `NK-AM270-BLK-09, MUM01, 2026-07-15, 6300, 148, WAC` |

**Used in the PoC:** `purchase_receipts` is the **cost ledger** (the source of truth for cost
over time); the PoC rolls it into `inventory_cost.wac_cost` (moving-average, cost-as-of the
decision date) for **margin** and **inventory valuation**, while pricing/replenishment Order
Value uses the latest `unit_cost` (replacement cost). This is what makes margin correct when the
same SKU is replenished at different costs.

### 11.3 Competitor `[gen]` + `[poc]` — NEW (Competitor Monitor, price responses)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `competitors` `[cfg]` (competitor) | `comp_id, name, type, region, collection_method, refresh, currency, compliance_ok` | `CMP_TW, TechWorld, Marketplace, ALL, api_feed, hourly, INR, true` |
| `competitor_prices` `[gen]` (comp-product×region×obs) | `comp_id, comp_product_id, region, observed_at, price, in_stock_flag, promo_flag, known_as_of` | `CMP_TW, TW-AIRPODS2, Bengaluru, 2026-07-15T09:12, 24499, true, false, 2026-07-15` |
| `competitor_matches` `[poc]` (our-SKU×comp-product) | `match_id, sku_id, comp_id, comp_product_id, match_confidence, match_status, matched_attributes` | `MTCH-081, APP-APP2-WHT, CMP_TW, TW-AIRPODS2, 0.96, matched, "brand;model;gtin"` |

**Used in the PoC:** the product-matching model (§8.1) links `competitor_prices` to `sku_id`
via `competitor_matches` (low-confidence stays in review, can't auto-trigger pricing); matched
competitor price/availability feeds the **competitor-availability demand driver** (§3.4) and the
price-recommendation competitor bound.

### 11.4 Promotions & customers `[gen]` — NEW (Promotion Planner)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `promotions` (promo) | `promo_id, name, type, objective, offer_value, start_date, end_date, scope, segment_id, min_margin_pct, approval_route, status, owner` | `PR-Monsoon, "Monsoon Footwear Event", pct, revenue, 12, 2026-07-20, 2026-07-31, "West+Online", SEG_ALL, 20, category_mgr, draft, Emma` |
| `promotion_skus` (promo×SKU/category) | `promo_id, sku_id_or_category, discount_pct` | `PR-Monsoon, Footwear, 12` |
| `customer_segments` (segment) | `segment_id, name, size, share_pct, description` | `SEG_LOYAL, "Loyalty members", 480000, 38, "Active loyalty base"` |

**Used in the PoC:** promotions feed the promo-uplift / cannibalisation / bundle models (§8.1)
and the promotion-overlap + inventory-readiness guardrails; `customer_segments` drive targeting
and the segment-response model.

### 11.5 External signals `[gen]` — NEW (Demand Drivers, scenarios, multi-currency)

| Entity (grain) | Columns | Sample |
|---|---|---|
| `weather_actual` (region/store×day) | `region, date, tavg_c, precip_mm, weather_code, known_as_of` | `Mumbai, 2026-07-15, 29.4, 62.0, rain, 2026-07-15` |
| `weather_forecast` (region×forecast×target) | `region, forecast_date, target_date, tavg_c, precip_prob, known_as_of` | `Mumbai, 2026-07-15, 2026-07-22, 30.1, 0.7, 2026-07-15` |
| `local_events` (region/store×date) | `region, date, event_name, event_type, expected_impact, known_as_of` | `Bengaluru, 2026-08-15, "City Marathon", civic, 1.2, 2026-07-01` |
| `macro_index` (region×week) | `region, week_start, index_name, value, known_as_of` | `West, 2026-07-13, consumption_index, 104.6, 2026-07-16` |
| `fx_rates` (currency×date) | `base_ccy, quote_ccy, rate, as_of` | `INR, USD, 0.01205, 2026-07-15` |

**Used in the PoC:** weather/local-event/macro become forecast features + the weather and
competitor driver groups (§3.4) and the Scenario-Planning axes (§3.6); `fx_rates` is display-only
conversion (§2.4). All respect `known_as_of` — a forecast weather value can't be "known" before
its issue date.

### 11.6 Multi-echelon inventory `[gen]` + `[poc]` — NEW

| Entity (grain) | Columns | Sample |
|---|---|---|
| `locations` `[gen]` (location) — supersedes `stores` | `location_id, name, type, region, city, parent_dc, active` | `WHDC-W, "West DC Ahmedabad", dc, West, Ahmedabad, null, true` |
| `stock_snapshots` (extended) `[gen]` | + `reserved_units, damaged_units, in_transit_units` (ATP = on_hand − reserved) | `NK-AM270-BLK-09, MUM01, 2026-07-15, 48, 244, 6, 0, 30, 2026-07-15` |
| `inventory_batches` `[gen]` (batch) | `batch_id, sku_id, location_id, batch_qty, mfg_date, expiry_date, receipt_date, unit_cost, known_as_of` | `BT-24A, BT-SERUM-30, MUM11, 320, 2026-05-01, 2026-08-05, 2026-05-04, 540, 2026-05-04` |
| `inbound_shipments` `[gen]` (shipment) | `shipment_id, sku_id, from_location, to_location, qty, dispatch_date, expected_receipt_date, status, known_as_of` | `SHP-3391, APP-APP2-WHT, WHDC-S, BLR03, 240, 2026-07-12, 2026-07-18, in_transit, 2026-07-12` |
| `transfer_orders` `[poc]` (transfer) | `transfer_id, sku_id, from_location, to_location, qty, reason, expected_benefit, status` | `TRF-0102, RUN-SHOE-9, KOL04, CHE06, 72, lost_sales_recovery, 320000, review` |
| `allocations` `[poc]` (SKU×location) | `allocation_id, sku_id, pool_qty, location_id, requested_qty, allocated_qty, shortfall, rule, priority, status` | `ALC-77, NK-AM270-BLK-09, 1240, MUM01, 1480, 1220, 260, revenue_service, high, review` |

**Used in the PoC:** `locations` makes store/DC/in-transit first-class (sales & stock key on
`location_id`); `inventory_batches` powers ageing/expiry + **FIFO costing**; `inbound_shipments`
powers in-transit value + ATP; `transfer_orders`/`allocations` are engine outputs surfaced on the
Transfers/Allocation screens.

### 11.7 Supplier performance `[gen]` — NEW

| Entity (grain) | Columns | Sample |
|---|---|---|
| `supplier_performance` (supplier×period) | `supplier_id, period, otd_pct, capacity_confirmed_pct, lead_time_mean_days, lead_time_std_days, risk` | `SUP_ELECA, 2026-Q2, 0.81, 0.82, 8.6, 2.4, high` |

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
| `data_sources` | `source_id, name, type, refresh, last_refresh, record_count, quality_pct, status, mapping_ref` | `[cfg]`/`[poc]` |
| `model_registry` | `model_id, family, version, coverage, accuracy, last_trained, status, fingerprint` | `[poc]` |
| `model_drift` | `model_id, as_of, drift_score, threshold, status` | `[poc]` |
| `alert_rules` | `rule_id, category, trigger, threshold, direction, owner, priority, active` | `[cfg]` |

**Reuse as-is from the M5 PoC (migration 001/002/003):** `workflow_sessions`, `draft_orders`,
`approvals`, `exceptions`, `exception_notes`, `exception_status_history`, `audit_log`,
`policy_edits`, `price_recs`, `price_rec_reviews`, `adoption_metrics`. These already implement
named-actor, idempotency, audit, and shadow-only semantics (§4.7) — copy the schema unchanged.

### 11.10 Which repo owns which file + ingest mapping

| Origin | Entities |
|---|---|
| **`[gen]`** (generator repo → files the PoC ingests) | sales, products, locations, calendar, calendar_events, sell_prices, stock_snapshots, inventory_batches, inbound_shipments, suppliers_leadtimes, supplier_performance, purchase_receipts, competitor_prices, promotions, promotion_skus, customer_segments, weather_actual, weather_forecast, local_events, macro_index, fx_rates |
| **`[poc]`** (produced at runtime) | inventory_cost, competitor_matches, transfer_orders, allocations, forecast_versions/series/drivers, planner_adjustments, model_registry, model_drift, + all workflow tables |
| **`[cfg]`** (seeded config, version-controlled) | competitors, users, roles, data_sources, alert_rules, guardrail config (`pricing_rules.yaml`, `policy.yaml`) |

**Ingest example** — the `mapped_files` profile maps the generator's file/column names onto the
canonical schema (only the columns differ; downstream code is unchanged):

```yaml
profile_id: retail_v2_synth
contract_version: retail_v2
adapter: mapped_files
source_classification: SYNTHETIC_CLIENT_SHAPED_TEST   # generated data = "client-shaped extract"
raw_dir: /data/generated/run_2026_07
entities:
  sales:
    path: sales.parquet
    columns: {sku_id: item_code, store_id: location_code, date: biz_date,
              units: qty, net_price: unit_price, known_as_of: available_on}
  purchase_receipts:
    path: purchase_receipts.csv
    columns: {sku_id: item_code, location_id: location_code, supplier_id: vendor,
              receipt_date: grn_date, qty: qty, unit_cost: landed_cost, known_as_of: posted_on}
  competitor_prices:
    path: competitor_prices.parquet
    columns: {comp_id: source, comp_product_id: ext_sku, region: geo,
              observed_at: captured_at, price: price, in_stock_flag: available, known_as_of: captured_on}
```

**End-to-end flow in the PoC** (all `[REUSE]` machinery from the M5 PoC):

1. Generator lands `[gen]` files in `raw_dir`.
2. `data.ingest_mapped` maps them → curated canonical `retail_v2` tables.
3. `data.quality_checks` runs the battery (§4.1) — **fails closed** on missing `known_as_of`,
   negative units, missing cost, duplicate keys, calendar gaps, etc.
4. `features.build` → weekly point-in-time features.
5. **(Python)** Models: `models.forecasting` (P50/P90) and `models.price_response` (elasticity).
6. **(Python)** Engines: reorder/safety-stock, pricing, allocation, transfer, ageing/expiry →
   write forecast/recommendation `[poc]` artifacts + manifests + semantic fingerprints to the
   lake + PostgreSQL.
7. **(Go)** The API serves those artifacts to the UI and owns workflow/HITL — approvals, planner
   overrides, audit — **re-validating guardrails and lineage on the way out** (stale → 409,
   missing → 503); every action stays shadow-only.

Steps 1–6 are the Python ML pipeline; step 7 is the Go API (see the Architecture note's
technology-stack subsection).

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
(1-wk cycle) = **371**. When inventory position (on-hand + on-order) drops to/below 271, the
engine proposes topping up to 371 — then rounds to MOQ/pack multiples and caps at `max_cover_days` (30).

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
