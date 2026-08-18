# CLAUDE.md — operating guide for this repo

Read this first, then `README.md` (§8 runbook) and `plans/local/ui-parity-availability-and-margin-plan.md`. These are the authoritative operational references — consult them before investigating pipeline mechanics from scratch.

## Golden rules

- **Gather every command/arg/path/pin BEFORE launching any long or expensive run** (datagen ≈ 90 min, full pipeline, cargo builds). Never launch-then-discover-then-relaunch. Verify conventions first.
- **This is a PoC.** Generated data IS the authoritative data of record — there is no client/ERP feed. See *PoC principles*.
- **No AI attribution anywhere** — commits, PRs, code, docs. No co-author trailers, no "generated with" footers.
- Keep this file updated as facts change (identities, migration head, phase status).

## Current state (as of 2026-08-16)

- Branch `feature/gulf-oil-india-datagen`.
- Active scenario **`gulf-oil-india-cost`** — config `datagen_rust/configs/pricing-response-cost.yaml` (extends `gulf-oil-india-cost-base.yaml`). The `pricing-response-rich`/`gulf-oil-india-ten-year` chain is **superseded**: the authoritative run was generated from the cost chain (verified in `resolved-config.json`).
- Active source run **`run-73ba460b02d63c40`** (label `gulf-auth3`), served since the 2026-08-17 authoritative run. Active serving versions: forecast `fr_d0c0ebafa8cb1db9`/`fv_f5a62cd4a0e41d5a`, inventory `iv_d7cbb24e99b0c89f`, pricing bundle `pb_8d1659aaf034c0349557` (activation set `pact_d8ded49e5a21f088`), scenario ctx `e9a7fc48…`. `decisionAsOf` `2026-07-31T18:30:00Z`; `environment=local`, `retailer-demo`/`tenant-demo`. This run bakes in the competitor model, per-unit Price Simulation, promotion positive branch, and inventory Bucket A/B; the prior `run-fc4d492700b127ce`/`gulf-auth1`/`gulf-auth2` bundle was purged after this run activated (filesystem + inactive PG serving versions; DB 23G→10G). Serve: `python3 tools/dev.py serve --with-ui --pricing-serving-config ml/data/artifacts/pricing_authority_gulf-auth3/pricing-serving.json`.
- Scale: 1 market (`gulf-india`), 13 stores, 4 departments, 16 categories, 73 products, 292 SKUs.
- Stack is UP (Docker Desktop): Postgres `127.0.0.1:5432` (db `retail_intelligence`, user `retail`), MLflow `127.0.0.1:5000`. **DB migration head `0035_executive_sales`** (adds the bounded, governed sales projection used by Executive Overview). Chain: `0032_pricing_unit_fields` (per-unit Price Simulation) → `0033_promotion_positive_branch` → `0034_expiry_waste_prior_window` → `0035`.
- Current work: **§6.0 Pricing demo-positive closure** (see *Current work*), the **Competitor model (named rivals)** below, and the **Inventory "Not available" elimination (Buckets A & B)** below.

## Inventory "Not available" elimination — Buckets A & B (implemented 2026-08-17; NOT committed)

Goal (owner): on the inventory/replenishment screens, show a REAL derived value instead of a bare "Not available" wherever one can be derived; where it genuinely cannot, show the governed why/when treatment, never a bare fallback or a fabricated number. All wiring done; **no datagen/pipeline run started** (a full authoritative re-run is pending and will repopulate the run-dependent tiles).

- **Bucket A — DONE and LIVE on the authoritative run** (inventory `iv_d7cbb24e99b0c89f`): #15 Provisions + NRV, #16 Ageing band on Stock Health (correlated subquery), #18 Exception Owner (governed role CASE → "Demand Planning"), #20 category-table NRV/Provision columns. **#17 Waste Reduction = +51.3% live.** Migration **`0034`** adds `prior_waste_units`/`prior_waste_minor`; loader `load_prior_waste` (`[as_of-181, as_of-91]`), `_build_expiry_waste` values prior waste at the accepted unit cost. **Read-model gotcha (fixed):** `wasteReductionPct` must sum over the WHOLE active version — the Expiry & Waste route's clauses filter to rows with CURRENT expiry/waste and drop prior-only cells (that gave a bogus -1893% from 15 of 614 prior units). It is now computed in a dedicated unfiltered `wasteReduction(ctx)` post-merge (`inventory.go`), NOT the `inventoryAggregates` block; NULL prior baseline → governed via `PRIOR_PERIOD_NOT_COMPARED`. (A datagen "recent waste decline" was explored and REVERTED — the data was already +51.3% at the network level; the bug was purely the read-model filter.)
- **Bucket B — DONE, live NOW on the current bundle.** Read-model `replayImpact` (`api/internal/readmodel/inventory.go`) reads `inventory_replay_metrics` for the active version, **gated PER METRIC** on the replay's own `bool_and(passed)` verdict, benefits from the holdout cohort. Merged into the `replenishment_recommendations` + `replenishment_safety_stock` summaries. The candidate (`candidate/forecast-reorder-point/v2`) clears `meanInventoryUnits` but not the no-regression service gates vs the ultra-buffered incumbent (`incumbent/fixed-cover-21d/v1`), so: **Working Capital Impact ₹172.01 Cr** and **Inventory turn improvement +193.3%** render as real values (meanInventoryUnits passed); Projected Service Level / Expected Fill Rate / Lost-sales reduction / Stock-out reduction stay governed-absent (their metrics failed acceptance — honest, not hidden). Revenue Protected + Lost Sales Exposure stay governed regardless (the replay publishes units, not a selling price). No migration (table already existed).
- **Migration 0034 landed fully:** all 7 runtime pins bumped `0033`→`0034`, guard-test `RETIRED_HEADS` floor extended with `0033`, both evidence records regenerated against the live DB (`closure-record` + `inventory-entry-record`), migration applied (`db-upgrade`) so DB head = pins = `0034`. Tests: ml inventory build/publish/serving/cli + migration-pin guard + contracts screen matrices all green; Go read-model green; API rebuilt + serving verified in-browser.

## Competitor model — named rivals (implemented 2026-08-16; pending authoritative run)

Gulf competes **cross-brand** (rival lubricant brands), not same-SKU-at-another-store. The generator now models named rivals whose prices sit in a tight band that **straddles** ours — some above, some below, never a blanket discount. Built as an **opt-in `competitors:` config block**, so scenarios without it (incl. the Python parity oracle) keep the legacy `Benchmark {brand}` path unchanged.

- **Config** (`datagen_rust/configs/pricing-response-cost.yaml`): `competitors.brands` = named rivals with `priceCenter` (multiplier vs our price) + the `categories` each claims as primary competitor; `competitors.band` = tight clamp (`0.94`–`1.06`) + `pairOffsetPct` (±2% stable per-SKU) + `weeklyNoisePct` (±1% stable drift). Gulf straddled: MNC premium **above** (Castrol 1.05, Shell/Mobil 1.03), PSU/value **below** (Servo 0.95, HP 0.96, Amaron 0.98), TotalEnergies parity, Veedol = catch-all. ~9 categories above / ~7 below.
- **Rust** — `config.rs`: `CompetitorConfig`/`CompetitorBrand`/`CompetitorBand`, `LoadedConfig::competitors()`, `CompetitorConfig::primary_for_category`. `signals.rs`: `straddle_multiplier` + a branch in the competitor loop. When `competitors()` is `Some`, each SKU's primary competitor (by category) is emitted with the real brand name, a stable straddling price, and a **cross-brand spec match** (`matchMethod=cross-brand-spec-match-v1`, confidence 0.86–0.97, category+options match, **brand deliberately not a match factor**). When `None`, the legacy path runs → parity intact.
  - **Price basis = our CURRENT list price, not static base.** The competitor price is `snap(price_for_day(day) × multiplier)` — the pure regime list walk via a per-market `PriceEngine` (`effective_list_price`'s lifecycle/promo branches are excluded so the basis is trivially shared with the Python datagen). The smoke test proved that pinning to `variant.base_price` let a decade of price-change events drift our *current* price ±20% away, so the band read wide (0.77–1.21) and **skewed below** us. Anchoring on the walked list price the recommendation actually compares against makes the band tight (~0.92–1.07) and balanced (≈55% above / 45% below). The legacy `else` branch keeps `base × inflation` so the oracle is byte-stable.
- **Python datagen — MIRRORED (in sync).** The named-rival path is mirrored in the Python generator: `config.py` `_validate_competitors` (+`_COMPETITOR_BAND_DEFAULTS`), and `simulation.py` `_straddle_multiplier`/`_primary_competitor_for_category` + the branch using `_price_for_day` as the basis. Verified **byte-identical** by a direct Rust↔Python comparison (competitorPrices 7592 + competitorMatches 292, matching SHAs) and frozen by a new oracle `gulf_mini_competitor_signals_match_python_oracle` over fixture `datagen_rust/contracts/gulf-mini-competitors-v13.json` (gulf-mini + pricingEvidence + the competitors block).
- **ML / serving / migration** — none. High datagen confidence + spec attributes → `Matched` + bound-eligible through the existing `competitor.py` + `contracts/pricing/competitor-policy.json`; the eval-gate truth (`build_competitor_truth`) is unchanged.
- **Tests** — `cd datagen_rust && cargo test`: 39/39 green, incl. both parity oracles (legacy `gulf_mini_context_signals_match_python_oracle` + new `gulf_mini_competitor_signals_match_python_oracle`) and `competitor_straddle_multiplier_is_tight_stable_and_positioned` / `gulf_cost_config_maps_named_competitors_by_category`. Python: `datagen/.venv/bin/python -m pytest datagen/tests/test_datagen.py -q` (legacy signal oracle green).
- **Smoke-verified** end-to-end (2026-08-16). To re-verify without the ~90-min run, create a throwaway 2-month config — `extends: pricing-response-cost.yaml`, override `identity.scenarioId: gulf-oil-india-cost-smoke` + `time` to 2026-06-01…2026-07-31 — datagen it (~90s), then inspect `companion/gulf-india/competitor_prices` joined to `competitor_matches` and `business-central/bc-gulf-in/item_variants` (compare the latest competitor obs to `unitPrice`). Last result: 8 named rivals, correct category→brand mapping (Castrol→2W, Servo→DEO/tractor/hydraulic, …), all `Matched` (0.86–0.97), and — after the price-basis fix — a tight straddle **0.92–1.07, ≈55% above / 45% below** our current list price. Clean up after: `rm -rf` the smoke config + `output/gulf-oil-india-cost-smoke` (immutable-output guard blocks re-running into an existing run dir).
- **Pending** — the authoritative datagen run (cost config) + full pipeline + pricing lifecycle to serve it. **Not committed** (awaiting owner go-ahead). The prior `matched 0.90→0.84` policy workaround is now redundant (real cross-brand matches score ≥0.86) but left as-is until measured.

## Verified commands

- **DB query:** `docker compose -f deploy/compose.yaml exec -T postgres psql -U retail -d retail_intelligence -Atc "<SQL>"`
- **Services:** `python3 tools/dev.py services up|status`
- **Python envs** (isolated per component): `ml/.venv/bin/python`, `datagen/.venv/bin/python`, `ingestion/.venv/bin/python`, `db/.venv/bin/python`. Create/refresh with `python3 tools/dev.py envs`.
- **Tests:** `python3 tools/dev.py test` (fast suites) · `python3 tools/dev.py contracts` · `python3 tools/dev.py verify` (stateful, needs Postgres) · targeted: `ml/.venv/bin/python -m pytest ml/tests/<file>.py -q`.
- **Rust datagen check:** `cd datagen_rust && cargo check`.

## The pipeline (source → serving)

Order: **datagen → land → ingest** (Gate A / staging / transform / Gate B / publish) **→ repin → forecast** (features…activate) **→ inventory** (build/verify/materialize/activate) **→ pricing** (build/verify/materialize/prepare/activate).

- `python3 tools/dev.py pipeline` chains `land`→…→`inventory-activate` + the two evidence records. **Pricing is NOT in that chain** — run the pricing lifecycle separately.
- Runbook detail: README §8b (forecast chain), §8c (inventory chain), **§8d (pricing chain — being added)**.

### Datagen (verified)

```
python3 tools/dev.py datagen --config datagen_rust/configs/pricing-response-cost.yaml --regenerate --execution-profile performance
```
- Output is **content-addressed** at `datagen_rust/output/<scenario>/run-<id>/`. A changed config/source → a NEW `run-<id>` subdir alongside existing runs (no clobber). **Use the default `output` folder** — the tooling discovers runs there (`tools/dev.py:2433`); a custom `--output` hides the run from the pipeline and forces `--source-root` overrides everywhere.
- Deterministic (seeded): identical config → identical run id. `--regenerate` forces a new run when content differs.
- ≈ 90 min at `performance`, plus a one-time Rust compile.

### Pricing bundle — build & measure without serving (calibration)

Pricing is a **separate manual lifecycle**, NOT part of `pipeline`. Full arg-by-arg detail: README §8d. Pricing consumes the **built + accepted** forecast/inventory *bundle directories*, not the serving DB — so a calibration measurement needs NO materialize/activate anywhere. Verified sequence (substitute `run-<NEWID>` = the promoted datagen run, e.g. `run-9af5586546feaaa8`; use a FRESH `<LABEL>`, e.g. `gulf-calib`, or the immutable-output guard refuses):

```bash
# 1. Ingest + register (repin) + forecast build — one call, DB-free, stops before serving.
python3 tools/dev.py pipeline --from land --to publish \
  --source-root datagen_rust/output/gulf-oil-india-cost/run-<NEWID> \
  --label <LABEL> --retailer retailer-demo --tenant tenant-demo --environment local \
  --decision-as-of 2026-07-31T18:30:00Z \
  --input-authority-reviewer <you> --input-authority-reason "<why>" \
  --repin-actor <you> --repin-reason "<why>"
# 2. Inventory build only (needs Postgres reachable, NOT activation).
python3 tools/dev.py services up && python3 tools/dev.py db-upgrade
python3 tools/dev.py pipeline --from inventory-build --to inventory-build \
  --source-root datagen_rust/output/gulf-oil-india-cost/run-<NEWID> \
  --label <LABEL> --retailer retailer-demo --tenant tenant-demo --environment local \
  --decision-as-of 2026-07-31T18:30:00Z
# 3. pricing-build — writes price_recommendations.parquet; no Postgres.
python3 tools/dev.py pricing-build --run-id run-<NEWID> \
  --input-authority contracts/evidence/input-authorities/gulf-oil-india-rich-local-run-<NEWID>.json \
  --job-purpose complete_lineage_rebuild --expected-pin contracts/ml/expected-pin.json \
  --retailer-id retailer-demo --tenant-id tenant-demo --environment local \
  --evidence-root ingestion/data/evidence/run-<NEWID> \
  --curated-database ingestion/data/curated/run-<NEWID>/retail_v2.duckdb \
  --decision-as-of 2026-07-31T18:30:00Z \
  --forecast-run ml/data/artifacts/forecast_run_<LABEL> \
  --inventory-run ml/data/artifacts/inventory_run_<LABEL> \
  --competitor-truth datagen_rust/output/gulf-oil-india-cost/run-<NEWID>/_truth/competitor_match_truth.parquet \
  --bundle-kind response_rich --output ml/data/artifacts/pricing_bundle_<LABEL>
# 4. Measure (read the parquet directly; do NOT verify/prepare/materialize/activate a throwaway).
ml/.venv/bin/python tools/measure_pricing.py ml/data/artifacts/pricing_bundle_<LABEL>/price_recommendations.parquet
```

- The **`repin` stage** (step 1) is the fail-closed source-authority gate: it moves `contracts/ml/expected-pin.json` to the new run and writes the v2 publication-selection records. The 4 reviewer/reason flags are REQUIRED for a brand-new run (no source edit needed on the v2 ledger).
- **`decision-as-of 2026-07-31T18:30:00Z`** = 2026-08-01 00:00 Asia/Kolkata = the end-of-day knowledge cutoff *after* the source period ends (`2026-07-31`; forecast origin `2026-07-27`). It gates scoring by `source_known_as_of <= decision_as_of` (`ml/src/retail_ml/models/dataset.py:304`) — it is NOT the pipeline execution date, and the retired `2026-08-02` was a landing-lag workaround, not this run's value. **Known bug:** the active *inventory* bundle records midnight (`2026-07-31T00:00:00Z`) instead of `18:30` (the `-cutoff-aligned` sibling is correct) — pass `18:30` to `inventory-build` and verify the bundle records it, so a rebuild keeps forecast+inventory+pricing on one instant.
- To actually SERVE a bundle (not calibration): `pricing-build → pricing-verify → pricing-materialize → pricing-prepare → pricing-activate`. Activation replaces the live demo — only for the frozen authoritative run, never a calibration seed.

## Critical footguns (verified — these WILL bite)

1. **Migration 7-pin rule.** A new Alembic migration must atomically bump **all seven** runtime head-equality guards, or the un-bumped ones 503:
   - 3 Go read models: `api/internal/readmodel/{forecast,inventory,pricing}.go` (`*MigrationRevision`);
   - 4 Python materializers: `MIGRATION_REVISION` in `ml/src/retail_ml/{pricing,serving,scenario,inventory_publish}/postgres.py`.
   - Also bump the publisher stamp `ml/src/retail_ml/publish/run_artifacts.py`, the DB test `db/tests/test_forecast_schema.py`, extend the guard test `contracts/python/tests/test_serving_migration_pin.py`, and **regenerate** the two evidence records against the live DB: `tools/dev.py closure-record --forecast-run <bundle>` and `tools/dev.py inventory-entry-record` (never hand-edit them).
   - **Trap:** the Go scenario read model reuses `ForecastMigrationRevision`, but `scenario/postgres.py` and `inventory_publish/postgres.py` carry their OWN pins — assuming they "inherit" is how they get missed.
2. **ML expected-pin / source-authority gate (decision #89).** A brand-new source run stops at the `repin` stage until it's registered as accepted source authority (with approver + reason) via `tools/build_publication_selection.py`. `features` takes no `--source-root` — it reads `contracts/ml/expected-pin.json`. README §8a. This is the most common mid-pipeline wall on a fresh run.
3. **Datagen output convention** — content-addressed, default `datagen_rust/output` (see above).
4. **Pricing is separate from `pipeline`** (see above).

## PoC principles (plan §0.0 — do not re-litigate)

- The generated **weighted-average cost** IS the authoritative unit cost. Margin (`price − cost`) shows on every primary surface; the minimum-margin floor is enforced on WAC. There is **no client-actual gate** in the PoC — that machinery is production-only/dormant. Never withhold PoC margin citing "not client-actual".
- Only honest cost label is **"weighted-average cost"**. Never imply a client/ERP source or add a "synthetic — not client actual" disclaimer.
- The formal Promotion `P5-D23` approval is likewise a production gate; in this PoC the owner directs the positive branch and it is engineering, not a wait-gate.

## Current work — §6.0 Pricing demo-positive closure

Plan: `plans/local/ui-parity-availability-and-margin-plan.md`. Target: retailer-positive Pricing demo — 20-row default page, strictly-positive Margin & Revenue Opportunity, complete competitor coverage, per-unit Price Simulation, positive Promotion branch — with no bare "Not available". **Distribution amended 2026-08-14 (screen contract PDP-6.0-A2):** the owner accepted run-2's measured distribution (~1093 recs, ~156 actions, ≥84% Hold) as demo-positive; the earlier 12–14-Hold / 6–8-action page-1 target was a pre-generation range and is superseded. Page 1 is action-dominant under the priority-first sort.

**STATUS 2026-08-18 — authoritative run DONE and SERVED (`run-73ba460b02d63c40` / `gulf-auth3`):** all four verticals active + demo-positive. Pricing 1093 recs / 932 Hold (85%) / +₹10.57L margin / +₹48.86L revenue; Competitor 66% Matched; Promotion positive branch live; Bucket A/B all live incl. Waste Reduction +51.3% and Working Capital ₹172 Cr; per-unit Simulation live. Backtest ran 2h27m (heavier config than the docs' 40m). Old `fc4d`/`gulf-auth1/2` bundle purged. Historical run-2 producer notes retained below for calibration reference:
- **Recommendations** ✅ run-2 (`gulf-cost2`, run-fc4d492700b127ce): 937 Hold / 146 Decrease / 10 Increase (86% Hold), Margin +₹4.6L, Revenue +₹47.4L — accepted. Cost seam + margin-protected-Hold reclassification (below).
- **Competitor** ✅ threshold fix (matched 0.90→0.84) → 11%→52% coverage.
- **P4 per-unit Simulation** ✅ full vertical: migration `0032_pricing_unit_fields` + ingestion `measurement_unit` (core.py:350) + `units.py` producer + materializer + Go read-model + contract + UI (distinct Current/Proposed/AI, Demand/Objective selectors). 8/13-wk Period + Competitor-Response selectors are client-side-only — full backend needs served multi-horizon forecast + Go handler (`pricing.go:1102` hardpins "Next 4 Weeks").
- **Promotion positive branch** ✅ estimator (`promotion.py`, episode/control bootstrap + support/holdout/dilution gates; policy `contracts/pricing/promotion-uplift-policy.json`) + bundle wiring (`build.py`/`bundle.py` verify relaxed to accept positive; `artifacts.schema.json` fingerprint `22f259c3…`; reason-codes registered). Live DB: 16 accepted, `packageDisposition=positive`. **Serving vertical (migration + materializer + read-model + Planner UI) still pending — post-run.**
- **Authoritative run — DONE** as `run-73ba460b02d63c40` (`gulf-auth3`), served 2026-08-18. Fresh datagen (competitor block in `pricing-response-cost.yaml`) → full pipeline (`land→inventory-entry-record`) → `scenario-demo-activate` → pricing lifecycle. **Footgun hit + fixed:** forecast `activate` failed decision-#90 "exactly one active forecast version; found 2" because the preserved old bundle was still active — resume with `pipeline --from materialize --to inventory-entry-record --retire-other-scopes` (`--from activate` fails: activate needs materialize's in-invocation run-id/scope). Inventory-activate self-retires its predecessor (no flag). Pricing predecessor for `pricing-prepare` = the CURRENT active `rselrec_` **record** id, not the `rsel_` selection id. The old chain (`run_authoritative*.sh`, run-2/-r2) is fully superseded.

**Root-cause mechanism (validated on an offline predictor that reproduces a bundle's exact action distribution — `scratchpad/predict_pricing.py`, reuses the real `enumerate_candidates`/`gross_margin_pct`):**
- The candidate grid is a **±2–5% band** around current price. A *genuine* `action=Hold` needs the most-recent price at the **exact** revenue-optimizing support edge — unreachable via the generator because the `responseStepScale=2` walk noise dominates any price trend, so an accepted elastic SKU almost always wants to Decrease (current above margin-optimal `p* = cost·β/(β+1)`) or is withheld (current ≤ p*, revenue-improving cut dilutes margin).
- **The Hold lever is COST + a reclassification, not price trend.** `ml/src/retail_ml/pricing/recommendation.py` now treats a well-priced SKU — one whose only revenue-improving candidate is margin-dilutive — as a genuine **Hold ("held to protect margin")**, NOT a withheld `MARGIN_DILUTION` row. Raising the WAC cost basis raises `p*` above current → more SKUs land in this well-priced Hold band. Cost is deterministic (no walk-noise, no exact-edge fragility). Offline sweep (cost/current): 0.62→46% Hold, 0.68→71%, **0.72→88%**, 0.78→99%; sub-floor blocks (cost>~0.85×current, margin<12%) still withhold. Opportunity stays strictly positive — no dilutive action is ever served. Floor-block withhold (§A5) is unchanged; only margin-dilution was reclassified.

**Seams built + tested (both engines):**
- **Per-variant cost** — a `VariantDefinition.cost` sets that variant's authoritative WAC directly (`catalog.rs` + `catalog_packs.py`, matched on option values; parity test in `test_gulf_catalog.py`). Seats the 3–4 profitable pockets at chosen margins.
- **Per-category price-trend** — explored (`Category.priceTrendAnnual`) then **REVERTED**: the `responseStepScale=2` walk noise dominates the trend over the 156-week fit window, so it can't land current at the exact support edge. The cost approach (market-flat inflation + high cost + reclassification) replaced it. Do not reintroduce.
- Competitor **per-store** scope (`signals.rs`) — reaches every store. The named-rival model (see *Competitor model* above) is **opt-in via config**, so the `gulf_mini_context_signals_match_python_oracle` parity path is unchanged and green — no oracle regeneration needed for that shared path.

**Cost-approach config** (`scratchpad/gen_cost_config.py` → `gulf-oil-india-cost-base.yaml`; `pricing-response-cost.yaml` extends it, `responseStepScale:2`): market `annualInflationRate: 0.0` (flat → current≈basePrice so `cost/current≈cost/basePrice`, headroom under `basePrice≥baseCost`).

**Run 1** (HOLD `[-2.3,-1.3]`@0.70; DECREASE whole `gulf-atf`@0.38; INCREASE `gulf-compressor-turbine`@inelastic; run-366425d2c5c5c06b, label gulf-cost1): **885 Hold / 362 Decrease / 2 Increase; Margin +₹21.7L, Revenue +₹127L, both POSITIVE.** Hold-majority + positive opportunity validated end-to-end. Gaps: 286 of 362 Decreases are Hold-cohort stragglers (fitted `shrunk_beta` amplified to −3.22 vs config −2.3, so `cost/current 0.63 < 1−1/|β|`); Increase only 2 (inelastic accepts ~2%); competitor coverage 11.8% (only 31 SKUs get competitor matches — a separate `signals.rs` matching-coverage issue); 1249 recs + 8354 withheld (scale/sparse-data, vs 80–120 target).

**Run 2 (in progress, label gulf-cost2)**: HOLD elasticity narrowed to LESS elastic `[-1.7,-1.2]`@`baseCost 0.73` (fitted β stays ~≤−2.5 → `cost/current∈[0.62,0.86]≥` threshold → Hold, kills the stragglers); DECREASE pocket = ONE variant `GLF-ATF-DX3-STD-1L` via the per-variant cost seam (`cost 0.40·basePrice`); INCREASE = two inelastic categories (`gulf-compressor-turbine`+`gulf-industrial-gear`). **Competitor coverage:** the assessment scores a legit cross-brand competitor at ~0.85 (held-out score = categoryId 0.35 + options 0.50; brand 0.15 misses because the competitor is "Benchmark {brand}", a different brand). The `matched: 0.90` gate wrongly required a same-brand match. Lowered `contracts/pricing/competitor-policy.json` matched→0.84 / needsReview→0.78 (policyVersion 1.1.0; tests updated) → **11%→~56% coverage** at the next pricing-build; the eval gate is safe (negatives score ~0). The sub-0.84 remainder (→~100%) needs a datagen observation-attribute-consistency follow-up.

**Owner directives (2026-08-14):**
- **Price Simulation shows real values or required governed text ONLY — never a guardrail *message* or "Not available" fallback.** The normal walkthrough's default SKU is actionable+profitable so every Current/Proposed/AI cell resolves to a real value; a value that genuinely cannot exist shows the required governed text, not a message.
- **Before the single authoritative run, DELETE older runs' data from ALL stores** — datagen output, ingestion (raw/curated/evidence/work), ML artifacts, DuckDB, PostgreSQL serving — preserving only active/predecessor authority (plan §B line 444). Also keep `/private/tmp/.../tasks` + tool-results clean of stale transcripts.

**P4 serving DONE (this session, 113 pricing tests green):** migration 0032 + 7-pin + ingestion `measurement_unit` carry (defensive) + producer (panel/build/recommendation) + materializer + artifact contract/fingerprint + `pricing/units.py` scaling helper + read-model per-unit SELECTs (`pricing.go`, Go builds). **Recommendations UI (P3) DONE** (20-row page, no-bare-"Not available", KPI deltas; 53/53). **Remaining:** P4 simulation UI (per-unit display + proposed→minor conversion + enabled selectors + distinct Proposed/AI — real values only); Promotion positive branch; parity-contract amendments; manifest freeze; dry-run gate; the authoritative run.

**Action-distribution / margin measurement query** (verified):
```sql
SELECT record_kind, action, count(*),
       sum(margin_impact_minor)  AS margin_opp_minor,
       sum(revenue_impact_minor) AS revenue_opp_minor
FROM retail_serving.price_recommendations
GROUP BY record_kind, action ORDER BY count(*) DESC;
```
For a throwaway calibration bundle, read the built `price_recommendations.parquet` directly instead of the serving table.

## Calibration runs (throwaway pricing iterations)

To measure a repriced/re-cohorted Pricing distribution WITHOUT touching the active demo. **Each iteration is a full governed pipeline (~2 hrs); there is no fast/forecast-reuse path** (see gotchas). All on main disk (the external volume can unmount mid-run — fall back + clean up after). Substitute `run-<NEWID>` (the promoted calib run) and `gulf-calibN` (fresh label).

1. **Config:** `scratchpad/gen_calib_config.py` writes `gulf-oil-india-calib-base.yaml` (per-category `targetMargin` + narrowed elasticity); `pricing-response-calib.yaml` extends it. `validate-config` first.
2. **Datagen:** `python3 tools/dev.py datagen --config datagen_rust/configs/pricing-response-calib.yaml --regenerate --execution-profile performance` (default output; ~70 min).
3. **Full pipeline in ONE command** (NEVER fragment `--from/--to`):
   `python3 tools/dev.py pipeline --from land --to publish --source-root datagen_rust/output/gulf-oil-india-calib/run-<NEWID> --source-profile ingestion/src/retail_ingestion/profiles/gulf_oil_india_ten_year.yaml --label gulf-calibN --retailer retailer-demo --tenant tenant-demo --environment local --decision-as-of 2026-07-31T18:30:00Z --input-authority contracts/evidence/input-authorities/gulf-oil-india-rich-local-run-<NEWID>.json --input-authority-reviewer <you> --input-authority-reason "..." --repin-actor <you> --repin-reason "..."`
4. **Inventory:** `ml/.venv/bin/python -m retail_ml.cli inventory-build --run-id run-<NEWID> --expected-pin contracts/ml/expected-pin.json --input-authority <...run-NEWID.json> --job-purpose complete_lineage_rebuild --retailer retailer-demo --tenant tenant-demo --environment local --evidence-root ingestion/data/evidence/run-<NEWID> --curated-root ingestion/data/curated/run-<NEWID> --bundle ml/data/artifacts/inventory_run_gulf-calibN --as-of 2026-07-31 --decision-as-of 2026-07-31T18:30:00Z --forecast-run ml/data/artifacts/forecast_run_gulf-calibN --postgres-dsn postgresql://retail:retail-local-only@127.0.0.1:5432/retail_intelligence --execution-profile performance`
5. **Pricing:** `pricing-build` (README §8d args) with `--forecast-run ml/data/artifacts/forecast_run_gulf-calibN --inventory-run ml/data/artifacts/inventory_run_gulf-calibN --competitor-truth datagen_rust/output/gulf-oil-india-calib/run-<NEWID>/_truth/competitor_match_truth.parquet --output ml/data/artifacts/pricing_bundle_gulf-calibN`.
6. **Measure:** `ml/.venv/bin/python tools/measure_pricing.py ml/data/artifacts/pricing_bundle_gulf-calibN/price_recommendations.parquet`.
7. **Clean up:** `git checkout contracts/ml/expected-pin.json`; delete untracked calib records (`git status --porcelain contracts/evidence/publication-selections/ | awk '/^\?\?/{print $2}' | xargs rm -f`); rm the calib input-authority; `rm -rf` the calib datagen run + `ingestion/data/{raw/snapshots/<snap>,curated,evidence,work}/…run-<NEWID>` + `ml/data/artifacts/*gulf-calibN*`.

### Calibration gotchas (each cost a failed run — do NOT relearn)
- **Competitor scope = PER-STORE.** `signals.rs` loops the market's stores → `targetType=store`. `first_store` scoped ~11/866 bounds; **market scope** binds the recommendation join but the weekly competitor FEATURES join at location grain → all-null → `features` fails.
- **Backtest REQUIRED; forecast can't be reused.** `inventory-build` enforces forecast lineage ("belongs to a different pinned input lineage"); a fresh source needs its own `features→backtest→publish` forecast. (pricing-build's `load_forecast_context` doesn't check — inventory-build does.)
- **Gulf `--source-profile`** (`gulf_oil_india_ten_year.yaml`): its `extractWindow` (2016-08-04/2026-07-31) matches; the default `retail_datagen.yaml` (2016-07-28/2026-07-28) fails Gate A **A03**. The profile is **baked into the landing at land time** — delete the landing to re-bake if landed with the wrong profile.
- **land→publish as ONE command.** Fragmenting drops threaded args (features needs `--input-authority`; repin only builds the input-authority on a non-resumed full run — else build it directly via `tools/build_input_authority.py`, see `tools/dev.py:3202`).
- **Don't redirect ingest roots.** `repin` reads curated at the default `ingestion/data/curated` regardless of `--publication-root`; redirecting breaks repin ("curated DuckDB absent"). Datagen `--output` to an external volume is fine; ingest is not redirectable cleanly.

## Where to look

- Runbook: `README.md` §8. · Active plan: `plans/local/ui-parity-availability-and-margin-plan.md`. · Stage timings/cost: `docs/pipeline-stage-timings.md`. · Open decisions: `docs/OPEN_DECISIONS.md`. · Spec + canonical schema: `docs/demand_forecast_poc_spec.md` (§11). · Component contracts: `datagen/README.md`, `ingestion/README.md`, `api/README.md`, `ui/README.md`.
