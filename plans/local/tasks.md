# Retail Intelligence — Local Tasks

_Companion to `plans/local/plan.md`. Status: `[ ]` not started · `[~]` partial · `[x]` done._
_All tasks below are **local**, on generated synthetic data, shadow-only._

## Phase 1 — Synthetic data generation `[FIRST]`

**1.1 Contracts (prerequisite — freeze early)**
- [ ] Author `contracts/` `retail_v2` schema from spec §11 (all entities, columns, types).
- [ ] Define `known_as_of` per temporal entity; money as integer minor units (`exponent = 2`).
- [ ] Separate entity ownership (`[in]` / `[poc]` / `[cfg]` / `[test]`) from row provenance.
- [ ] Publish the source-profile schema: formats, paths/objects, source/canonical grains, keys,
      joins, filters, code maps, timezone, currency/unit/tax basis, PIT rules, transforms and
      reconciliation controls.
- [ ] Publish coverage/capability and composite-manifest schemas: entity/field coverage,
      valid-zero policy, companion/precedence rules and `validated_partial` vs promotable status.
- [ ] Define the profile-driven `mapped_files`/thin-adapter → standardized-staging interface and
      the staging → canonical reusable-domain-transform interface.
- [ ] Define versioned staging envelopes and approved mapping config vs runtime-crosswalk ownership.
- [ ] Seed guardrail YAMLs (`pricing_rules`, `policy`, `price_response`) — strict values (no M5 amendment).
- [ ] Write the data dictionary (units, currency, tax basis, availability, sales/fulfillment,
      exact sales money, adjustment reduction equations and inventory/ATP semantics).

**1.2 Generator scaffold (`datagen/`, Python, isolated)**
- [ ] Own dependency file; imports only from `contracts/`.
- [ ] Config: categories, stores (5 cities) + DCs, SKUs/category, date range (~3y), seed.
- [ ] Deterministic RNG (per-day seeding) + hash-based non-random values.
- [ ] One internal canonical truth with `canonical_test` and `client_shaped_test` publishers.

**1.3 Demand model**
- [ ] Base level per SKU×store; weekly seasonality (Fourier).
- [ ] Indian festival / monsoon / EOSS calendar bumps; day-of-week.
- [ ] Trend; promo lift; price elasticity; intermittency + new-product launch gate.
- [ ] Weather multiplier + local-event multiplier + macro drift.
- [ ] Poisson / neg-binomial unit draw.
- [ ] Inventory-consistent event loop: latent demand → ATP-constrained realized sales.
- [ ] Emit explicit `sales_version`, exact `net_sales_amount` and `sales_fulfillments` linking
      demand nodes to physical supply nodes; reconcile at every cutoff.
- [ ] Exclude/reconcile pre-fulfilment cancellations; emit versioned `sales_adjustments` for
      post-fulfilment physical/financial reversals with no historical rewrite.

**1.4 Money & operational streams**
- [ ] Regular/promo price series; promo dips.
- [ ] **Cost ledger `purchase_receipts`** — same SKU received at different costs over time.
- [ ] Inventory snapshots with disjoint on-hand/committed/reserved/damaged/on-order/in-transit,
      explicit `atp_method`, reconciled ATP; **batches + expiry**; inbound shipments.
- [ ] Suppliers + `supplier_performance` (OTD, lead-time mean/std).

**1.5 New feeds**
- [ ] Competitor product attributes + `competitor_prices` + availability.
- [ ] `weather_actual` + `weather_forecast` (Indian cities); `local_events`; `macro_index`; `fx_rates`.
- [ ] `promotions` + `promotion_skus` + `customer_segments`.
- [ ] Test-only competitor-match ground truth; canonical `competitor_matches` remains a PoC output.

**1.6 Discipline & output**
- [ ] Immutable publication (`run_id` from generator version + config + input hashes).
- [ ] Boundary validation (date ranges, lookup coverage).
- [ ] Emit canonical Parquet plus source-shaped CSV/Parquet/JSONL as each dialect declares.
- [ ] Publish a full-coverage generic retailer fixture, a direct-identifier-free,
      protected-field-minimized Shopify-supported fixture (bulk plus signed webhook envelopes)
      and synthetic PIM/ERP/WMS/external companion feeds with source manifests/profiles; never
      use production Shopify data locally.
- [ ] Record canonical/source control totals, entity/field coverage, capability evidence,
      companion precedence, schemas and per-output hashes in manifests.
- [ ] Tests: determinism, boundary, `known_as_of`, schema, causal stock/sales consistency,
      protected-field exclusion and valid/invalid test webhook signatures.
- [ ] **Exit:** cost ledger shows one SKU at multiple costs; generic, Shopify and companion
      snapshots land in Phase 2.

## Phase 2 — Ingest & data quality (`ml/data`)
- [ ] Immutable raw landing with snapshot manifests, content hashes and idempotent replay.
- [ ] Gate A: files/objects, hashes, schema/parseability, source keys, extract window and source
      coverage/capability + approved-mapping references, event/API authenticity and pre-landing
      projection attestations, input/filter/reject/control-total reconciliation.
- [ ] Copy/adapt M5 `mapped_files` as the profile-driven default normalizer; it emits
      standardized staging frames.
- [ ] Add a versioned source-adapter registry; bounded adapters handle only source-specific
      normalization and emit those same standardized staging frames.
- [ ] Build source-neutral transforms from staging to canonical: joins/version selection;
      business-day/timezone; exact money/paise, quantity and tax basis; fulfilled-sales and
      adjustment semantics; aggregation; inventory snapshots.
- [ ] Implement generic retailer and synthetic Shopify profiles/adapters over the Phase-1 fixtures.
- [ ] Attach source/profile/adapter/transform lineage and entity-specific `known_as_of`.
- [ ] Gate B canonical battery: coverage/capability status; monotonic versions and unique keys;
      exact sales-money and fulfillment-bridge reconciliation; adjustment equations; negatives,
      non-positive price, date gaps, PIT, promo-rule recompute, ATP/inbound invariants,
      cost-ledger completeness and referential integrity.
- [ ] Reason-coded quarantine; atomically publish passing curated Parquet + DuckDB.
- [ ] Golden tests: generic reconstructs the full truth and passes full Gate B; pure Shopify
      reconstructs its declared slice with `validated_partial` only; Shopify plus companion feeds
      reconstruct the full truth/control totals and pass full Gate B.
- [ ] Shopify tests cover GraphQL/webhook ID parity; deleted/custom variant resolution; explicit
      POS/ecommerce classification plus materialized `VIRTUAL_ONLINE`; split fulfillment;
      `SUCCESS`→`CANCELLED` and failed-fulfillment transitions; requested-vs-processed returns;
      adjustment event-time fallbacks/quarantine; failed-vs-successful refunds; exact
      split-discount/tax penny allocation; `on_hand` controls including
      `quality_control`/`safety_stock`; incoming-vs-ERP inbound separation; idempotent webhook
      replay; HMAC failure; timestamp and catalog-price scope policy; and protected-field
      exclusion before immutable landing.
- [ ] **Exit:** Gate A passes all snapshots; generic/composite full Gate B passes with 0 critical;
      the pure Shopify slice is not promoted or sent to models; refs/reconciliations hold;
      curated capability-complete tables materialize; downstream code is source-neutral.

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
- [ ] Multi-echelon `locations`, reconciled ATP, inbound/in-transit shipment state,
      batches/expiry and ageing.
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
- [ ] Alembic migrations (`db/`): reuse M5 workflow tables; add `retail_v2` domain/output tables
      plus `ingest_runs`, reconciliation, quality/quarantine, approved source-mapping config and
      runtime source-crosswalk tables.
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
- [ ] At least two client-shaped dialects proving config-only onboarding where existing transforms
      cover semantics; otherwise only a bounded versioned adapter, with no downstream changes.
- [ ] End-to-end acceptance run (ingest → serve) through all fail-closed gates.
- [ ] **Exit:** full run passes; all screens live.
