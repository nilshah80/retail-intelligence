# Retail Intelligence — Local Tasks

_Companion to `plans/local/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_All tasks below are **local**, on generated synthetic data, shadow-only._

## Phase 1 — Synthetic data generation `[FIRST]`

**1.1 Contracts (prerequisite — freeze early)**
- [ ] Author `contracts/` `retail_v2` schema from spec §11 (all entities, columns, types).
- [ ] Define `known_as_of` per temporal entity; money as integer minor units (`exponent = 2`).
- [ ] Add `*_source` provenance convention; mark `[gen]` / `[poc]` / `[cfg]` origin per entity.
- [ ] Publish the `mapped_files` ingest-profile template (generator columns → canonical).
- [ ] Seed guardrail YAMLs (`pricing_rules`, `policy`, `price_response`) — strict values (no M5 amendment).
- [ ] Write the data dictionary (units, currency, tax basis, availability semantics).

**1.2 Generator scaffold (`datagen/`, Python, isolated)**
- [ ] Own dependency file; imports only from `contracts/`.
- [ ] Config: categories, stores (5 cities) + DCs, SKUs/category, date range (~3y), seed.
- [ ] Deterministic RNG (per-day seeding) + hash-based non-random values.

**1.3 Demand model**
- [ ] Base level per SKU×store; weekly seasonality (Fourier).
- [ ] Indian festival / monsoon / EOSS calendar bumps; day-of-week.
- [ ] Trend; promo lift; price elasticity; intermittency + new-product launch gate.
- [ ] Weather multiplier + local-event multiplier + macro drift.
- [ ] Poisson / neg-binomial unit draw.

**1.4 Money & operational streams**
- [ ] Regular/promo price series; promo dips.
- [ ] **Cost ledger `purchase_receipts`** — same SKU received at different costs over time.
- [ ] Inventory snapshots (on-hand/on-order, reserved/damaged); **batches + expiry**; inbound shipments.
- [ ] Suppliers + `supplier_performance` (OTD, lead-time mean/std).

**1.5 New feeds**
- [ ] `competitor_prices` + availability + seed `competitor_matches`.
- [ ] `weather_actual` + `weather_forecast` (Indian cities); `local_events`; `macro_index`; `fx_rates`.
- [ ] `promotions` + `promotion_skus` + `customer_segments`.

**1.6 Discipline & output**
- [ ] Immutable publication (`run_id` from generator version + config + input hashes).
- [ ] Boundary validation (date ranges, lookup coverage).
- [ ] Emit CSV/Parquet per entity to an output dir; write a run manifest.
- [ ] Tests: determinism (byte-identical rerun), boundary, `known_as_of`, schema conformance.
- [ ] **Exit:** cost ledger shows one SKU at multiple costs; Phase-2 adapter reads without error.

## Phase 2 — Ingest & data quality (`ml/data`)
- [ ] Copy/adapt M5 `mapped_files` adapter into `ml/`.
- [ ] Author the ingest profile mapping `datagen` columns → canonical `retail_v2`.
- [ ] Quality battery (fail-closed): negatives, non-positive price, dup keys, date gaps, `known_as_of`, promo-rule recompute, cost completeness, referential integrity.
- [ ] Curated Parquet + DuckDB warehouse.
- [ ] **Exit:** `status = pass` (0 critical); refs hold; curated tables materialize.

## Phase 3 — Features & demand forecast (`ml/features`, `ml/models`)
- [ ] Weekly PIT feature build (+ competitor/weather/event/macro drivers).
- [ ] LightGBM horizon-quantile P50/P90, **horizons → 26 wk**; Croston routing.
- [ ] Baselines + FVA; metrics WAPE / bias / `accuracy = 100·(1−WAPE)`.
- [ ] Rolling-origin backtest + acceptance gates (≥25% vs seasonal-naive; P90 coverage 0.85–0.95; monotonic).
- [ ] `forecast_versions`, SHAP `forecast_drivers` (+ competitor/weather groups), confidence.
- [ ] **Exit:** acceptance gates pass; artifacts fingerprinted. → Demand Forecast screen data.

## Phase 4 — Inventory & replenishment (`ml/engines`)
- [ ] Reorder / safety-stock (quantile-spread × service level).
- [ ] Service-level policy calibration (5%) + validation (95%); A/B/C.
- [ ] Multi-echelon `locations`, ATP, in-transit, batches/expiry, ageing.
- [ ] Transfer optimizer; constrained allocation.
- [ ] Inventory-replay simulator + acceptance; demand-at-risk.
- [ ] **Exit:** replay + policy holdout pass. → Inventory + Replenishment screens.

## Phase 5 — Pricing & promotions (`ml/models`, `ml/engines`)
- [ ] Price-response elasticity (Poisson GLM + empirical-Bayes) + gates.
- [ ] Price recommendations under guardrails (margin floor, max change, dominance).
- [ ] Price simulation; scenario planning.
- [ ] Competitor monitor: product-matching + confidence gate + competitor-aware response.
- [ ] Promotion planner: uplift / cannibalisation / bundle / segment models.
- [ ] Cost-over-time margin (WAC default; FIFO for batch-tracked; cost-as-of).
- [ ] **Exit:** gates enforced; recs guardrail-valid. → Pricing / Competitor / Promotion screens.

## Phase 6 — Go API, workflow & governance (`api/`, `db/`)
- [ ] Alembic migrations (`db/`): reuse M5 workflow tables + new `retail_v2` tables.
- [ ] Go API serving artifacts (OpenAPI/proto in `contracts/`).
- [ ] Workflow/HITL: approvals, planner overrides (bounded + reason), idempotency, audit.
- [ ] Serve-time guardrail re-validation; staleness 409/503; RBAC/auth.
- [ ] **Fingerprint parity** — Python & Go pass shared golden vectors.
- [ ] **Exit:** approve/override audited; 409/503 correct; identical fingerprints. → Governance.

## Phase 7 — UI (`ui/`)
- [ ] Pick framework (see `docs/OPEN_DECISIONS.md` #17).
- [ ] Implement screens against the Go API; multi-currency (FX) display.
- [ ] Wire interactive what-ifs (scenario/simulation) to the API.
- [ ] Build rich capture forms the mockup only stubs (§8.3).
- [ ] **Exit:** every screen renders live API data; no mock paths.

## Phase 8 — Analytics, admin & hardening
- [ ] Model registry / drift; alerts + data-freshness; data-source management; reports.
- [ ] Adoption metrics / performance insights (AI-vs-control cohort).
- [ ] Disclosure guardrails (projections not lift; observational elasticity; synthetic labelling).
- [ ] Synthetic "client-shaped" dataset proving config-only onboarding.
- [ ] End-to-end acceptance run (ingest → serve) through all fail-closed gates.
- [ ] **Exit:** full run passes; all screens live.
