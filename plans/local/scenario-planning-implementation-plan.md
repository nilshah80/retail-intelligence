# Forecast Scenario Planning v1 — Implementation Plan (rev 3.11)

_Feature: the **Demand Forecast → "Scenario Planning"** interactive what-if.
Presentation authority: `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html`
(`#forecastScenarioBtn`, handler at lines 2621–2638).
Spec authority: `docs/demand_forecast_poc_spec.md` locations enumerated by §0/S27.
Cross-authorities: #27 (reporting FX), #44 (FX arithmetic), #46 (channel grain), #73/#90
(activation authority scope), #95 (expected volume)._

Status: **local demo complete; production activation pending** — authority amendments, contracts,
migrations, shared price resolver/provenance, approval-gated materializer, bootstrap/POST calculation
API, React modal, and a reproducible local-only activation command are implemented. The local
`retailer-demo × tenant-demo × forecast_scenario_v1 × local` authority has an active labelled demo
bundle, base context, and matching inventory extension. A browser-run High Demand scenario returns
Demand Units, Revenue Potential, Required Inventory, and Stock-out Risk with paired partial coverage,
using the reference summary-plus-comparison-table presentation and Demand Forecast Cr/L money format.
Product/quant-approved production values, production active-tuple accessibility/human review, and
the production rollout amendment remain open.
**All engineering decisions remain resolved in §10 (S1–S27).**

**Rev 3.11 implementation review:** retains S1–S27, the completed local demo boundary, and the
FSP-V1-A3 presentation. The adversarial hardening pass separates `channelType` from native
`channelId`, bounds request-body allocation before reading, preserves bundle lineage under partial
coefficient coverage, restores inventory's numeric-only price behavior, normalizes decision dates
to UTC, enforces required business-scope members, sanitizes decoder errors, and adds database tier
coverage validation at bundle seal in migration `0027_scenario_hardening`. None changes a scenario
formula or production status.

---

## 0 · Positioning & governance boundary (do first)

Standalone **pre–Phase-5 workstream**; fitted elasticity stays in Phase 5. Amend **all** conflicting
authorities before implementation:

- **`docs/demand_forecast_poc_spec.md` (S27):** Architecture & data flow interactive-scoring
  paragraph; §2.5 Scenario row; §3.3, §3.5, §3.6 and §3.9 model table; §4.6 and §4.9; §5; §10.2
  and §10.4; §11.8; Appendix A. Freeze `expected_units` as additive volume, assumption-based v1
  ahead of fitted v2, scenario-only guardrails, scaled accepted order-up-to, the new risk label,
  potential-revenue/non-executable-inventory semantics, and the no-write disclosure. Do not leave
  the stale P50/fitted-β/simulator/margin-gate rows.
- **`plans/local/plan.md:342` + `plans/local/tasks.md:2059`** — add the standalone pre–Phase-5
  workstream and its activation gates.
- **`plans/local/phase5-implementation-plan.md:791`** plus its integration/tests — distinguish v1
  assumption projection from fitted Phase 5 Price Simulation/v2.
- **`docs/OPEN_DECISIONS.md`** — append the v1 decision, S1–S27 boundary, and v1↔v2 transition.

**Parity contract (S19):** `contracts/screens/demand-forecast.parity.yaml` top-level
`status: frozen_approved_for_implementation` is **test-enforced** (`test_screen_contracts.py:20`) and
**does not change**. Only the **`#forecastScenarioBtn` element status** transitions
`unavailable_phase_5` → **`approved_pending_implementation`** → `live_assumption_projection`, each
via a **recorded amendment** (amendmentId + decisionIds + approval + contract tests). The rollout
transition is **appended** as amendment/status evidence, never a rewrite of the earlier approval.

Resolved: D1 build v1 before Phase 5 · D2 versioned and **approved assumption bundle** · D3
stateless · fitted β = Phase 5 · later integration = new **v2**.

---

## 1 · What the feature is
Modal, six inputs + **Run Scenario** (`…v6.html:2626`): preset · Demand Adjustment · Price Change ·
Promotion Uplift · Competitor Availability · Weather/Event → Demand Units · Revenue Potential ·
Required Inventory · Stock-out Risk + current→scenario→impact. On-demand interactive scoring; demo
values hardcoded.

---

## 2 · Ground-truth audit (verified)

### 2.1 Already built ✅
`forecast_series` P50/P90/**expected_units** · versioning/activation (`active_forecast_versions`) ·
Demand-at-Risk **exposure** + **categorical** stock-health risk (`forecast.go:2164–2167`) · inventory
position `atp_units` (`0010:154`) · channel-allocated ATP (`0010:284`, **no residual published**) ·
accepted `reorder_point_units`/`order_up_to_units` **node grain** (`0010:239–240`) ·
`unit_cost_minor` (`0011:50`) · `load_unit_prices()` (`load.py:443`) · **Decision #44 FX**
(`fx.convert_and_sum`) · Go serving + Aarv v0.9.6 + fingerprints + UI plumbing.
**Do not reuse** Go `fxMoneySum` (`inventory.go:132`, multiplies inside SUM — violates #44).

### 2.2 Must be built for v1
Approved assumption bundle + append-only approval events (§3/S26) · complete price-provenance
publishing (S25) · four-record split context + materializer · **versioned scenario-context
bootstrap GET** (S20) · `POST /api/v1/forecast/scenario` · Go `readmodel/scenario.go` (pure calc +
**#44** money helper) + `httpapi/scenario.go` · UI bootstrap query + `post()`/`useMutation` + modal.

### 2.3 Context authority — selection, lifecycle, cardinality (S14)
Materialized offline, published as immutable manifests via append-only activation (#90 pattern).
Identity binds dependency identities **and** canonical content; bare ids/as-of dates are insufficient:
```
base_context_version = fingerprint(
    authority_scope + forecast_version + scenario_decision_as_of
  + approved_assumption_bundle_fingerprint + assumption_approval_semantic_fingerprint
  + price_snapshot_content_fingerprint
  + context_schema_version + materializer_version + base_output_content_fingerprint )
inventory_extension_version = fingerprint( base_context_version + inventory_version
  + inventory_extension_schema_version + materializer_version
  + inventory_output_content_fingerprint )
```
Every content fingerprint uses a versioned canonical serializer over deterministically sorted,
normalized business/provenance records and excludes its own version/fingerprint plus activation,
load-time, and audit-only columns. Decimal, timestamp, null, and Unicode normalization are frozen in
the contract and shared by Python/Go golden vectors; a content fingerprint is never self-referential.
`scenario_decision_as_of` is the active forecast's governed `decision_as_of`; price and reporting-FX
selection use that same cutoff. A compatible inventory extension must be bound to that forecast
version/cutoff. A dependency correction or changed materializer/output always mints a new context id.

Reporting FX is **not** in base identity (§4.3, S2). **Authority scope** is evaluated per
**retailer × tenant × capability × environment** (Decisions #73/#90). **Cardinality (fail-closed
active views):** active base exactly one (0/>1 → 503); inventory extension 0 → 200-partial, 1 →
available, >1 → 503; a client-pinned version **stale on arrival or mid-request → 409**.

**Bootstrap contract (S20):**

- `GET /api/v1/forecast/scenario/context?expectedForecastVersion=...` (query is required)
- schema `retail-forecast-scenario-context-bootstrap/v1`, `Cache-Control: no-store`;
- request authority comes from the server-configured retailer/tenant/capability/environment, not
  from user-supplied tenancy fields and not from the later business filter scope. The present PoC
  API is single-authority and has no request-auth middleware; production authentication/RBAC stays
  in the already-deferred Phase 6/deployment boundary rather than being fabricated here;
- `200` returns one compatible tuple:
  `{forecastVersion, scenarioContextVersion, inventory: null | {inventoryVersion,
  inventoryExtensionVersion}, scenarioDecisionAsOf}`;
- `409` when `expectedForecastVersion` is no longer the tuple's forecast; `503` for missing/
  ambiguous base or >1 compatible extension; malformed query → `400`.

POST carries that tuple as a **required** `expectedAuthority` object. `inventory` is required but
nullable: explicit `null` pins absence, so `null → newly active` and `active → null/different` both
return `409`. A structurally incomplete tuple is `422`; individually well-formed but mutually
incompatible/stale identities are `409`. Revalidate the exact tuple before calculation and again
before response commit; `ScenarioStale` returns expected and current tuples.

No datagen/ingestion/ML-training run; **zero pipeline invocation at request time**.

---

## 3 · Assumption bundle (one fingerprinted artifact; multi-grain children)
`forecast_scenario_assumption_sets`: **manifest/identity** (`assumption_set_id, version,
semantic_fingerprint, disclosure`; `projectionBasis: assumption_set`, `evidenceClass:
synthetic_scenario`, `statisticalGateStatus: not_applicable`) · **market × currency** guardrail
bounds + price-grid/rounding (single-sourced, #39) · **market × dept × baseline-price-tier** assumed
**β** + competitor stock-out/promotion + positive/negative weather sensitivities · **preset
definitions** (§4.5). No `gated` boolean.

**Approval authority (S26):** immutable bundle values enter append-only
`forecast_scenario_assumption_approval_events` states `candidate`, `approved`, `superseded`, or
`rejected`, scoped by retailer×tenant×capability×environment and bound to the exact bundle
fingerprint. An event records its id, bundle identity/fingerprint, event type, actor, timestamp,
prior event, decision reference, and a canonical approval semantic fingerprint. Changed values
always mint a new version/fingerprint and require new approval. Approval validation covers schema,
complete preset vectors, unique grains, tier-band coverage, finite inputs, `β<0`, positive factors
throughout permitted request bounds, and valid market/currency grid rules. A materializer invocation
pins one exact bundle fingerprint and refuses zero or multiple **effective approval heads for that
fingerprint**, or a superseded/rejected/unapproved head. Distinct approved fingerprints may coexist
while an inactive replacement context is built; the exactly-one active base context remains serving
selection authority. Replacement activation and supersession of the prior approval/context occur in
one transaction. If an active context's approval is otherwise superseded, the fail-closed active view
excludes it. The base context identity binds the approval semantic fingerprint and its manifest
retains the event id for lineage. Test-only placeholder bundles are explicitly `synthetic_test`,
cannot receive an approved serving event, and cannot publish or activate a serving context.

---

## 4 · Scenario context & the math

### 4.1 Four record types (residual ATP is a single node balance)
All shorthand grains below are inside the authenticated authority scope and include `market_id`;
every monetary row binds its local `currency_code` in the immutable context. Serving never borrows
market/currency from a mutable dimension join.

- **Base forecast-horizon rows** — `SKU×store×channel×horizon_week`: `p50/p90/expected_units`,
  `interval_available` + reason. The context retains the maximum horizon needed by the requested UI
  horizon, every protection period, and every accepted order-up-to window; it never silently emits a
  shortened policy-window metric.
- **Base series-commercial rows** — exactly one row per base `SKU×store×channel`, even when price
  evidence is absent. Price-dependent fields are nullable with explicit reason codes; a missing
  or non-positive price never removes the SeriesKey from the base population. Present rows carry
  positive unit price + currency; `price_basis` in {`latest_realized_exact`,
  `market_sku_latest_median`}; exact source-row identity/version, observation date, `known_as_of`, and
  content fingerprint, or fallback population count/date range/max-`known_as_of`/member-set content
  fingerprint; source cutoff; freshness status/reason; observed-support low/high/window/content
  fingerprint; `dept_id`, `baseline_price_tier` + resolution reason, and resolved coefficients. The
  context manifest carries the full `price_snapshot_content_fingerprint` (S25).
- **Inventory series rows** (extension) — `SKU×store×channel`: allocated ATP, requested units.
- **Inventory node rows** (extension) — `SKU×location`: `order_up_to_units`, `reorder_point_units`,
  `node_atp_units`, **`residual_atp_units`** (once), `unit_cost_minor` + provenance,
  `currency_code`, `inventory_version`, lead-time, review, `protection_days`.

Price selection is origin-visible at `scenario_decision_as_of`: latest realized exact SeriesKey
positive price first, otherwise the existing deterministic same-market/SKU fallback from
`_index_unit_prices`: sort latest positive minor-unit prices; choose the middle value for odd count,
or integer-floor the mean of the two middle values for even count. The materializer extends
`load_unit_prices()` to publish observation/availability fields and the full fallback member set; it
never describes a derived median as one observed transaction. Extract the resolver into one shared,
tested helper used by both the existing inventory builder and scenario materializer; preserve the
existing inventory outputs with regression vectors. The approved freshness window and
observed-support window come from the bundle and are evaluated before serving.

`baseline_price_tier` is derived **only from `price0`**, never from the applied scenario price. The
approved market/dept tier bands are non-overlapping half-open `[lower_minor, upper_minor)` ranges;
the final band has `upper_minor=null`. Approval validation rejects overlaps, gaps inside the approved
positive-price domain, or ambiguous bands. Missing dept/price or no unique match yields
`price_tier_unresolved`; freshness-invalid price does the same. It propagates only when S8 says the
tier is actually needed.

The extension computes `residual_atp_units = node_atp_units − Σ allocated_units` over all sibling
channels and enforces exact `Σallocated + residual = node_atp` with non-negative residual. A failed
conservation check prevents that extension from activating; the valid base still serves without an
inventory extension.

### 4.2 Factors & frozen applied-price order (S15 neutral no-op)
```
requestedRatio = requestedPriceChangePct / 100                         # API uses percentage points
appliedPrice[s] = unavailable                       if price0 missing/non-positive/freshness-invalid
                = price0[s]                         if requestedRatio == 0  # S15 exact no-op
                = gridRound(price0[s]·(1+requestedRatio)) otherwise
appliedPriceChangePct[s] = unavailable              if appliedPrice unavailable
                         = 100·(appliedPrice[s]/price0[s] − 1) otherwise
priceGuardrail[s] = not_applicable_neutral          if appliedPrice[s] == price0[s]
                  = validate_grid_min_max_support(appliedPrice[s]) otherwise
f_price[s]      = 1                                 if requestedRatio == 0
                = unavailable                       if appliedPrice unavailable
                = 1                                 if appliedPrice[s] == price0[s]
                = unavailable                       if priceGuardrail or β unresolved
                = (appliedPrice[s]/price0[s]) ^ β[s] otherwise             # β<0
F[s]            = f_demand · f_price[s] · f_promo · f_competitor · f_weather
expected'=F·expected  p50'=F·p50  p90'=F·p90
spread0=p90−p50       spread1=F·spread0                              # distribution_scale_v1
```
`promoUplift` is **incremental non-price** uplift. **Golden invariant:** the fully neutral vector
(all zero / normal) ⇒ `scenario == current`, `impact == 0` for every available metric.

Factor dependency is resolved **per series after price-grid application** (S24). β is required only
when `appliedPrice != price0`; normal competitor and weather states require no sensitivity. A
non-neutral required coefficient or per-series price guardrail that cannot resolve makes `F[s]`
unavailable with a reason — it is never replaced by `1` for an in-scope series.

A requested price change of exactly zero is semantically price-neutral even when valid baseline-price
evidence is missing: `f_price=1` and demand-only metrics may proceed, while applied-price and revenue
facts remain unavailable. Any non-zero price request requires a fresh positive `price0`, grid result,
tier when β is consumed, and—only when grid rounding produces an actual movement—per-series
min/max/support guardrails. The response still returns a rejected numeric applied candidate and its
reason; rejection makes the affected scenario facts unavailable rather than clamping the candidate.

There is no universal portfolio applied-price percentage. For each market/currency return the
baseline-value-weighted Laspeyres summary over paired price-assessed SeriesKeys, using complete
requested-horizon baseline demand `q0[s]`:
```
baseline_value_weighted_applied_price_change_pct =
    100·(Σ(q0[s]·appliedPrice[s]) / Σ(q0[s]·price0[s]) − 1)
```
Zero denominator ⇒ unavailable; return S11 coverage. Never combine currencies or substitute an
unweighted average of per-series percentages.

### 4.3 Outputs — volume = `expected_units` (#95); node calcs over all sibling channels (S16)

Node-level metrics are computed over **all sibling channels sharing the node**, with `F[s]=1` for
channels outside the requested scope, then filtered into the response. Protection/order-up-to windows
are **never truncated** to the UI horizon.

**Paired partial-result rule (S22):** for each metric, define the denominator population at its
canonical in-scope grain **before** evidence/guardrail exclusions, then form the paired assessed
population for which both current and scenario facts are available. The response's `current`,
`scenario`, and `impact` are all computed over that same paired population; it never subtracts a
partial scenario from a fuller current value. Zero paired facts ⇒ the aggregate is `unavailable`,
not numeric zero. Every metric returns shared `coverage={numerator,denominator,grain,pct}`; each
`current`, `scenario`, and `impact` component has
`availability: available|partial|unavailable`, nullable value, and `reasonCodes[]`. A numeric partial
value is explicitly labelled partial, and impact is unavailable whenever either input state is.
Demand/revenue admit a SeriesKey only with its complete requested horizon; risk admits it only with
the complete protection-window evidence. A shorter surviving horizon is never relabelled as the
requested metric.

**Typed impact convention:** `impact` is always the signed absolute delta in the metric's native
unit (units or integer minor money). Demand and Required Inventory units additionally return
`impactPct = 100·impact/current`; when both are zero, `impactPct=0` (`both_zero`), and when current is
zero but scenario is not, `impactPct` is unavailable (`zero_current`). The reference screen's Demand
impact uses this `impactPct`. Stock-out risk returns current/scenario in percentage points and an
`impactPoints` difference; it never labels a relative percent as a point delta or vice versa.

1. **Demand Units** over paired assessed in-scope SeriesKeys/horizons:
   `current=Σexpected`, `scenario=Σexpected'`, `impact=scenario−current`. *(no money; never blocked
   by FX)*
2. **Revenue Potential** — unconstrained expected-demand value, not fulfilled or realized revenue;
   stock-out loss is not netted in v1. Canonical money fact
   **per `SKU×store×channel×horizon_week`** (S17); `RHE` means
   `ROUND_HALF_EVEN` to integer local minor units:
   ```
   rev_current_local[s,h]  = RHE(expected[s,h]  · price0[s])
   rev_scenario_local[s,h] = RHE(expected'[s,h] · appliedPrice[s])
   local_current/scenario  = Σ paired rounded facts within market
   local_impact            = local_scenario − local_current
   ```
   **Reporting revenue** follows #44 separately on the current and scenario fact sets: convert each
   rounded local fact to reporting minor with per-fact `ROUND_HALF_EVEN`, sum, then
   `reporting_impact = reporting_scenario − reporting_current` (port `fx.convert_and_sum`; **not**
   `fxMoneySum`, and never convert an already-subtracted local impact). Missing a required FX rate
   makes the cross-market reporting aggregate `unavailable`—no incomplete nominal total—while
   market-local figures remain.
3. **Required Inventory (units):** `current=order_up_to_units`, `scenario=order_up_to_units ·
   F̄_node`, `impact=scenario−current`, where
   **`F̄_node = Σ(expected·F)/Σ(expected)`** over the node's **order-up-to window** and **all sibling
   channels** — i.e. **baseline-expected-weighted F** = scenario demand ÷ baseline demand over that
   window. Method `scaled_accepted_order_up_to_v1` (coarse: accepted value bundles protection +
   review demand + safety stock; decomposition deferred to v2). `Σexpected==0` ⇒ metric
   `unavailable` (`zero_baseline_demand`), never fabricated. This is an analytical projection, not
   an executable replenishment recommendation: v1 does not re-run MOQ/pack/capacity/budget caps, so
   the scaled value may sit outside operational ordering constraints.
4. **Required Inventory (value)** — one local-money fact **per `SKU×location` node**:
   ```
   inv_current_local[n]  = RHE(order_up_to_units[n] · unit_cost_minor[n])
   inv_scenario_local[n] = RHE(order_up_to_units[n] · F̄_node[n] · unit_cost_minor[n])
   inv_local_impact      = Σ paired inv_scenario_local − Σ paired inv_current_local
   ```
   Sum local facts only within their market/currency; never form a nominal cross-market total. Cost
   provenance remains attached; synthetic cost is labelled. Reporting current/scenario facts are
   converted separately per #44 and reporting impact is their aggregate difference.
5. **`demand_weighted_series_stockout_risk_pct`** — `normal_approximation_v1`:
   ```
   z90 = 1.2815515655446004
   μ0[s] = fractional_horizon_sum(expected[s,·],  protection_days)
   μ1[s] = fractional_horizon_sum(expected'[s,·], protection_days)
   σ0[s] = fractional_horizon_rss(spread0[s,·], protection_days)/z90
   σ1[s] = fractional_horizon_rss(spread1[s,·], protection_days)/z90
   ATP0[s] = allocated[s] + residual_node·μ0[s]/Σ_all_sibling μ0
   ATP1_base[s] = allocated[s] + residual_node·μ1[s]/Σ_all_sibling μ1
   ATP1[s] = max(0, ATP1_base[s]·(1+atpAdjustment))                    # ∈ [-1,0]
   risk_k[s] = 1 − Φ((ATP_k[s] − μk[s]) / σk[s])                      # k∈{0,1}; S9/S10
   value_k = protection-period-μk-weighted mean of paired in-scope risk_k[s]
   ```
   `Φ(x)=0.5·(1+erf(x/√2))`; clamp only floating-point tail noise to `[0,1]`. Negative/non-finite
   spread is invalid interval evidence, never coerced to zero.
   Disclosed as a demand-weighted mean of per-series channel stock-out probabilities — **not** a
   node-event probability. Residual ATP is allocated independently for current (`μ0`) and scenario
   (`μ1`); governed channel allocations remain fixed, and `atpAdjustment` applies only to scenario.
   When `residual_node==0`, set `ATP0=ATP1_base=allocated` without requiring an all-sibling μ
   denominator; this is why S21 can retain valid sibling risks in that case.
   Both aggregates use the same paired SeriesKeys but their own state-specific μ weights; impact is
   scenario minus current. `risk_k` is a `[0,1]` probability internally; the API returns
   `100·value_k` in percentage points and `impact` as a percentage-point difference, never a relative
   percent change.

**Two zero-demand denominator roles, each evaluated for current and scenario (S23):** residual
allocation uses `Σ_all_sibling μk` per node; risk aggregation uses `Σ_paired_in_scope μk`. If a
state's first denominator is zero, do not divide or fabricate a channel allocation: retain residual
at node grain for that state, mark allocation `not_applicable_zero_demand`, and apply S10's
per-series rule. If a state's second denominator is zero, that state's aggregate is `unavailable`
(`zero_demand`) and impact is unavailable; the other state may remain independently available over
the same paired SeriesKeys. Out-of-scope demand never supplies the in-scope aggregation denominator.

**Tier dependency (S8 truth table):** an unresolved `baseline_price_tier` blocks **only** the
metrics whose **non-neutral, tier-dependent** factor needs a bundle coefficient — neutral price
change needs no β, `normal` competitor needs no competitor sensitivity, `normal` weather needs no
weather sensitivity. Price neutrality is evaluated per series from `appliedPrice == price0`, so a
non-zero request that grid-rounds back to baseline also needs no β. If all active factors are
neutral/normal, the tier is not required.

**Cross-grain propagation (S21):** apply failures before aggregation/coverage:

| Missing/invalid dependency | Demand / revenue | Required Inventory | Stock-out risk |
|---|---|---|---|
| In-scope `F[s]` unresolved (coefficient or price guardrail) | affected SeriesKey scenario fact unavailable; revenue also needs price | whole affected node unavailable because `F̄_node` is incomplete | affected series unavailable; when node residual >0, all sibling risks unavailable because residual allocation needs every sibling μ; with residual=0, valid siblings remain assessable |
| Price missing/non-positive/stale with requested price change `0` and no non-neutral tier-dependent competitor/weather factor | direct demand/promo factors may remain available; applied price and revenue unavailable | units not blocked solely by price; value still needs cost | not blocked solely by price |
| P90/spread unavailable | demand/revenue unaffected | does not independently block scaling; the accepted order-up-to's own availability still controls | affected series only; sibling μ remains known |
| Complete protection/order-up-to window unavailable | requested-horizon demand/revenue unaffected when complete | affected node unavailable for scaling | affected series/node unavailable for risk |
| Order-up-to unavailable | demand/revenue unaffected | affected node units/value unavailable | risk may remain available if ATP evidence exists |
| Inventory extension absent | demand/revenue unaffected | all inventory metrics unavailable | all risk unavailable |
| ATP/allocation/residual evidence unavailable but order-up-to exists | demand/revenue unaffected | required-inventory units/value unaffected | affected node risk unavailable |
| Unit cost unavailable | unaffected | node value unavailable; units remain | unaffected |
| FX unavailable | demand/local revenue unaffected; reporting revenue unavailable | units/local value unaffected; reporting value unavailable | unit/percentage risk unaffected |

An out-of-scope sibling always uses governed baseline `F=1`; an **in-scope failed** factor never does.

"Each degrades independently" holds **after required base authority passes**; reporting-currency
money additionally needs the FX extension.

### 4.4 Per-factor provenance — dynamic (preset vs override)
`{demandAdjustment, promotionUplift, priceResponse, competitorSensitivity, weatherSensitivity,
atpAdjustment}` → `{valueSource: preset|user_override, coefficientSource:
not_applicable_direct_input|assumption_bundle|not_used_neutral|unavailable,
coefficientFingerprint?, reasonCode?}`. Demand/promotion inputs and preset-only ATP adjustment report
`not_applicable_direct_input`; β, competitor, and weather carry the bundle fingerprint only when
actually consumed. Applied-neutral/normal coefficient-bearing factors report `not_used_neutral`, and
unresolved required coefficients report `unavailable`. `valueSource` is determined by override-key
presence, not by comparing its value with the preset; the UI sends only fields the user actually
overrode and clears those keys when the preset is reset.

### 4.5 Five presets (server-owned, frozen; user field overrides preset field)
Public `*Pct` fields are **percentage points** (`2` means 2%); normalize exactly once by `/100`.
Thus `f_demand=1+demandAdjustmentPct/100`;
`f_price=(appliedPrice/price0)^β`; `f_promo=1+promotionUpliftPct/100` (non-price);
`f_competitor`=1/`1+stockoutSens`/`1−promoSens`; `f_weather`=1/`1+posSens`/`1−negSens`;
`atpAdjustment ∈ [-1,0]` (preset-only, no modal field).
```
                    demandAdj  priceChange  promoUplift  competitor  weather    atpAdj
Expected Demand      0          0            0           normal      normal      0
High Demand         +hi         0            0           normal      positive    0
Low Demand          −lo         0            0           normal      negative    0
Promotion Upside     0         −promoDisc   +promoLift   normal      normal      0
Supply-Constrained   0          0            0           normal      normal     −supplyCut
```

---

## 5 · Guardrails & HTTP outcome matrix (S18 request vs per-series)
Bounds/grid rules in the bundle (not Phase 5 gates): public percent values are percentage points;
`priceChangePct ∈ [-5,5]`; positive resulting prices/factors; market min/max; observed-support;
**no 12% margin floor on generated cost**; return `requestedPriceChangePct` + per-series
`appliedPriceChangePct`; never silent-clamp.
Missing/non-positive/stale baseline price is row-level unavailable evidence, not a request-level 422.
All inputs/intermediates must be finite. Local/reporting minor-unit facts and aggregates must fit
signed int64; overflow/non-finite governed arithmetic makes the affected row or aggregate
`unavailable` (`arithmetic_out_of_range`) and is never wrapped, saturated, or converted to zero.
Disclosure: `assumption_based_projection`; not fitted/causal/experimental lift; shadow-only;
stateless. Revenue is unconstrained potential; Required Inventory is a coarse scaled analytical
need, not a feasible order or recommendation.

| Condition | Status |
|---|---|
| Base-context authority missing/ambiguous (0 or >1 active base; forecast/assumptions/price authority) | **503** |
| >1 active inventory extension | **503** |
| Bootstrap `expectedForecastVersion` is no longer active | **409** with expected/current tuples |
| POST pinned tuple stale/incompatible, including explicit inventory `null ↔ active`, on arrival or mid-request | **409** with expected/current tuples |
| Base OK, no inventory extension | **200 partial** — demand + local revenue (+ reporting revenue when FX-complete); inventory/risk `unavailable` |
| FX extension missing/stale | **200 partial** — demand + market-local money; **reporting** aggregates `unavailable` |
| **Request-level** semantic error (override outside allowed input bounds) | **422** |
| Structurally incomplete `expectedAuthority` tuple | **422** |
| **Per-series** grid/min/max/observed-support failure | **200 partial** — S21 propagation + paired metric coverage; never substitute `F=1` |
| Row-level missing evidence (P90/ATP/price/cost) | **200 partial** — S21 propagation + paired metric coverage |
| Required FX rate missing | **200 partial** — local money remains; affected cross-market reporting aggregate `unavailable` with FX coverage/reason |
| Malformed JSON body / unsupported content-type | **400 / 415** |
| Declared or streamed body exceeds 4 MB | **413** before JSON allocation/decoding |

422 is reserved for **request-level** semantic errors; per-series bound failures never fail the
whole request and are never silently clamped.

**Outcome precedence:** media type → bounded body size → JSON/query decoding →
intrinsic structure/type/finite-value validation → current-authority cardinality (no unique current
authority is 503) → pinned-tuple comparison (409) → bundle-dependent request semantics (422) →
row calculation/partial availability → pre-commit tuple revalidation (409). Reporting-FX change at
the final check is the explicit exception: it drops reporting aggregates to 200-partial because FX
is not in the pinned base tuple.

---

## 6 · Contract identity

- **Bootstrap:** `GET /api/v1/forecast/scenario/context` with required
  `expectedForecastVersion`, schema
  `retail-forecast-scenario-context-bootstrap/v1`; statuses `200/400/409/503`; response is
  the S20 compatible tuple, not scenario data.
- **Calculation:** `POST /api/v1/forecast/scenario`, schema
  `retail-forecast-scenario-assumption/v1`; statuses `200/400/409/413/415/422/503`.
- Bootstrap and calculation success/error responses set `Cache-Control: no-store`.
- **POST request:** `presetId` + `userOverrides` + business scope + required `expectedAuthority =
  {forecastVersion, scenarioContextVersion, inventory: null | {inventoryVersion,
  inventoryExtensionVersion}}`. `presetId` is required. `userOverrides` may contain only the five
  modal fields; omitted fields inherit the complete server preset, while explicit nulls, unknown
  fields, and any ATP-adjustment override are 422. No pre-resolved factors and no user-supplied
  authority scope. Business-scope keys are structurally required even when their empty-string value
  means "all". `channelId` is the native channel identity; optional `channelType` carries the
  topbar's `online|store|marketplace` dimension and is matched through the pinned forecast version.
- **Response:** expected/current authority tuple; `scenarioDecisionAsOf`; approved assumption id,
  fingerprint and approval-event identity; complete S25 price provenance; resolved preset vector;
  dynamic S24 `factorBasis`; requested price change, per-series applied price changes, and the
  market/currency Laspeyres applied-price summary with coverage; paired
  `current`/`scenario` plus typed absolute/relative/point impacts from §4.3; market-local money;
  reporting money only when FX-complete; per-metric
  component-level `availability`, `reasonCodes[]`, and shared
  `coverage={numerator,denominator,grain,pct}`.
- **FX identity:** tenant reporting currency; `decision_as_of=scenarioDecisionAsOf`; greatest
  accepted-publication `rate_date ≤ decision_as_of`; the publication's point-in-time gate and
  semantic fingerprint pin the admitted observation set, and the resolved map receives its own
  content fingerprint. The source is immutable for the server process, so it cannot change during
  one request. Missing = no admissible rate for a required local currency. Reporting becomes
  unavailable; local facts remain.
- `409` → **`ScenarioStale`** with full expected/current tuples and dependency reason;
  `503` → **`ScenarioUnavailable`** with nullable current context identity and reason.

Phase 5 Price Simulation = different endpoint/schema; fitted β later ⇒ **v2**.

---

## 7 · Build order
1. Boundary + **formal parity amendment** (element status only; top-level stays frozen); amend the
   complete S27 authority surface in §0.
2. Freeze contract schemas + **§10 (S1–S27)** + golden vectors. Test fixtures use a non-activatable
   `synthetic_test` bundle; no business value is disguised as approved.
3. Add assumption/bundle-approval + four-record context migrations; update every migration-head pin.
4. Build price-provenance extraction (S25), extract the shared exact/fallback resolver with inventory
   regression parity, then build the approval-gated offline materializer, append-only base/extension
   manifests, fail-closed active views, and the S20 bootstrap GET.
5. Build the pure Go calc package: applied factors, S21 propagation, S22 pairing, S23 zero cases,
   exact local fact rounding, and the #44 reporting helper; pass golden vectors.
6. Add the tuple-pinned POST endpoint, frozen HTTP matrix, and scenario-specific error schemas.
7. Build the React modal: bootstrap query, required nullable authority tuple, mutation states,
   dirty-key-only overrides, S24 provenance in collapsed Projection details, applied-price summary,
   paired partial coverage, and local/reporting money with the Forecast Cr/L INR convention.
8. Verify: #44 Py↔Go parity; neutral no-op; off-grid-to-baseline; explicit absence→presence 409;
   tuple incompatibility; canonical fingerprint parity/non-self-reference; exact/fallback/tier price
   cases; all-sibling current/scenario ATP math; S21 cascades; paired-population equality; complete
   policy windows; no per-horizon ATP summing; zero-spread/both denominator roles/zero-baseline;
   market-local price summary; non-finite/overflow refusal; unapproved-bundle refusal; and **zero
   database/domain writes** on GET/POST.
9. **Activation gate:** product/quant supplies and signs the business values; validate/fingerprint the
   bundle, append its S26 approval event, materialize an inactive governed base plus zero/one
   compatible inventory extension, then atomically activate the replacement and supersede any prior
   approval/context. Run integration/parity/accessibility/human review against the active tuple.
   Production builds keep `VITE_FORECAST_SCENARIO_ENABLED` false until this dossier is complete.
10. Only after 6–9, append the rollout amendment flipping the **button** status to
    `live_assumption_projection`.

---

## 8 · Files touched
New: `contracts/scenarios/forecast_scenario_assumptions.yaml` ·
`db/migrations/versions/0025_forecast_scenario_assumptions.py` (bundle + approval events) ·
`0026_forecast_scenario_context.py` (four record types) · `0027_scenario_hardening.py` (database
tier-coverage seal guard) · context materializer + bootstrap read
under `ml/src/retail_ml/` / `api/` · `api/internal/readmodel/scenario.go` (incl. #44 money helper) ·
`api/internal/httpapi/scenario.go` (+ `_test.go`).
Edited: `ml/src/retail_ml/inventory_run/load.py` (price observation/availability lineage) +
`ml/src/retail_ml/inventory_run/build.py` (shared resolver extraction with output parity) ·
materializer tests · migration/schema tests · `contracts/api/openapi.yaml` ·
`api/internal/httpapi/app.go` · `api/cmd/server/main.go` · `ui/src/api.ts` ·
`ui/src/Forecast.tsx` · `ui/src/Forecast.test.tsx` · contract tests ·
`contracts/screens/demand-forecast.parity.yaml` (element amendments) · every S27 authority in §0.

---

## 9 · Out of scope (Phase 5)
Fitted price-response (`models/price_response.py`, Poisson-GLM + empirical-Bayes), `price_response.yaml`
gates, persisted fitted β, the separate **Price Simulation** capability.

---

## 10 · Resolved decisions (frozen for build; product/quant sign-off pending on values only)

| # | Decision | Resolution |
|---|---|---|
| S1 | FX arithmetic | #44: round each local current/scenario fact, convert each fact with exact exponent-aware `ROUND_HALF_EVEN`, then sum; reporting impact is the difference of the two reporting aggregates. Port `fx.convert_and_sum`; **not** `fxMoneySum`; never convert a pre-subtracted local impact. |
| S2 | Reporting FX scope | Serve-time optional aggregation extension; demand + market-local money never blocked. |
| S3 | Stock-out interpretation | `demand_weighted_series_stockout_risk_pct`; per-series channel probabilities, not a node event. `normal_approximation_v1` freezes `z90=1.2815515655446004`, erf CDF, invalid negative/non-finite spread, and numerical-tail-only `[0,1]` clamping. |
| S4 | Residual ATP | Store `node_atp−Σallocated` once on the node and enforce non-negative exact conservation before extension activation. Allocate residual independently ∝ `μ0` for current and `μ1` for scenario over all sibling channels when each denominator is positive; when residual is zero, use governed allocations directly without a sibling denominator (S16/S21/S23). |
| S5 | Promotion uplift | Incremental **non-price** uplift. |
| S6 | ATP adjustment bound | `[-1, 0]`, preset-only. |
| S7 | `F̄_node` | `Σ(expected·F)/Σ(expected)` = **baseline-expected-weighted F** over the order-up-to window & all sibling channels. Scaling the accepted order-up-to is coarse and non-executable; v1 does not reapply MOQ/pack/capacity/budget constraints. `Σexpected=0` → `unavailable` (`zero_baseline_demand`). |
| S8 | Tier derivation/dependency | Derive from positive baseline `price0` only through approved non-overlapping half-open market/dept bands (final upper null); never re-tier from applied price. Missing/no-unique tier blocks only a consumed non-neutral β/competitor/weather coefficient and propagates via S21. Applied-neutral price and normal competitor/weather need no tier. |
| S9 | Zero-spread (`σk=0`) | Per state, deterministic step `risk_k=1 if μk>ATP_k else 0`, `zero_spread_deterministic`. |
| S10 | Zero-demand (per series) | Per state, `μk=0` → series risk `0`, excluded from that state's risk weighting. Aggregate zero-denominator behavior is S23. |
| S11 | Coverage — **paired and by metric grain** | Denominator is the complete canonical in-scope population before exclusions; numerator is the paired current+scenario assessed population. Demand/risk/applied-price summary: SeriesKeys; Required Inventory: `SKU×location` nodes; money: canonical horizon/node money facts. Return `{numerator,denominator,grain,pct}` with `pct=100·n/d` when `d>0`; `d=0` returns null pct/`empty_scope`. Zero numerator means aggregate unavailable. |
| S12 | Extension cardinality | Base exactly one (0/>1 → 503); extension 0 → 200 partial, 1 → available, >1 → 503; pinned-superseded → 409. |
| S13 | Bundle grains | One bundle, four children: market×currency grid/freshness/support rules; market×dept×baseline-tier bands and coefficients; presets; manifest. Approval rejects band gaps/overlaps/ambiguity in the approved positive-price domain. |
| **S14** | **Context version pinning** | Bootstrap and POST bind one compatible authority tuple per retailer×tenant×capability×environment (#73/#90); POST uses S20's required nullable `expectedAuthority`; stale returns expected/current tuples. Versioned canonical fingerprints sort and normalize business/provenance records and exclude self-referential version plus activation/load/audit-only fields. |
| **S15** | **Neutral no-op** | For requested 0%, `appliedPrice=price0` without gridRound when valid price exists; when valid price evidence is absent, `f_price=1` but applied-price/revenue facts stay unavailable. Golden invariant: neutral vector ⇒ `scenario==current`, `impact==0` for every available metric. |
| **S16** | **Shared-node channel scope** | Node metrics use all sibling channels (`F=1` out-of-scope), residual allocation precedes response filtering, and policy windows ignore UI-horizon truncation. Current and scenario allocate residual separately using `μ0`/`μ1`; S21/S23 own failure and zero-denominator behavior. |
| **S17** | **Money-fact grain + FX/price-summary identity** | Revenue current/scenario are separately RHE-rounded `SKU×store×channel×horizon_week` facts; inventory value uses separately rounded `SKU×location` facts; local/reporting impacts are aggregate differences. FX follows #27/#44 at `scenarioDecisionAsOf`. Applied-price summary is a baseline-value-weighted Laspeyres ratio per market/currency only—never a universal cross-currency percent. |
| **S18** | **Request vs per-series validation** | Public `*Pct` fields use percentage points (`2` = 2%) and normalize once. Risk impact is points, not relative change. 422 = request-level semantics/structural tuple errors; per-series grid/min/max/support failure → 200 partial, S21 propagation, S22 pairing, reason and coverage; never silent-clamp. |
| **S19** | **Parity status scope** | Top-level `status: frozen_approved_for_implementation` unchanged (test-enforced); only `#forecastScenarioBtn` element status transitions, via appended amendments. |
| **S20** | **Bootstrap + absence pin** | `GET /api/v1/forecast/scenario/context` requires `expectedForecastVersion` and returns one compatible versioned tuple. POST requires `expectedAuthority.inventory` as explicit null or a complete version pair; absence/presence changes and incompatible tuples return 409; malformed POST structures return 422. |
| **S21** | **Cross-grain propagation** | Failed in-scope factors never become `F=1`. Series failures propagate to node Required Inventory and, when residual allocation needs the missing μ, sibling risks according to §4.3's table; unrelated dependencies remain independently available. |
| **S22** | **Comparable partial populations + typed impact** | Every aggregate's current/scenario/absolute impact uses the same paired assessed facts; coverage denominator is pre-exclusion scope. Unit metrics may also return relative `impactPct`; risk uses `impactPoints`. Demand/revenue never shorten the requested horizon; inventory/risk never shorten their full policy windows. Numeric partials are labelled; zero paired facts are unavailable. Missing required FX makes the cross-market reporting aggregate unavailable rather than nominally incomplete. |
| **S23** | **Two zero-demand denominator roles** | Evaluate both roles per state: `Σ_all_sibling μk=0` skips residual allocation and retains residual at node for state `k`; `Σ_paired_in_scope μk=0` makes that state's aggregate and impact unavailable, independently of out-of-scope demand. The other state may remain available over the same paired keys. |
| **S24** | **Applied-factor dependency/provenance** | Coefficient need is evaluated per series after price rounding; an exact-zero request is price-neutral even when valid price evidence is absent. Provenance is `not_applicable_direct_input`, `assumption_bundle`, `not_used_neutral`, or `unavailable`, with fingerprint/reason when applicable. |
| **S25** | **Price provenance** | Require positive, fresh price for price/revenue facts; freshness failure is row-level unavailable evidence. Publish exact source identity/version/date/known-as-of/fingerprint or full fallback member-set lineage, source cutoff, freshness result, support window/range, and content fingerprints. Fallback reuses `_index_unit_prices` sorted median with integer-floor even midpoint and is never labelled an observed transaction. |
| **S26** | **Assumption approval lifecycle** | Each bundle fingerprint has append-only candidate/approved/superseded/rejected events and one effective head. Materialization pins that head; changed values require new approval. Distinct approved fingerprints may overlap while a replacement is staged, but replacement activation plus prior supersession is atomic; unapproved/test contexts cannot activate. |
| **S27** | **Authority amendment surface** | Amend every spec/plan/decision/parity location enumerated in §0; specifically retire stale P50/fitted-β/simulator/pricing-gate claims for v1 while preserving them for Phase 5/v2. |

These are engineering-frozen. The S27 authority amendments are complete. Remaining activation gates
for production are external to the arithmetic design: **product/quant sign-off** on the entire resolved
bundle—especially
`hi/lo/promoDisc/promoLift/supplyCut`, assumed β/sensitivities, request/price guardrails, tier bands,
grid rules and freshness/support windows—recorded through S26; publication and activation of the
governed base context plus optional inventory extension; active-tuple accessibility/human review;
and the distinct production rollout amendment. The explicitly labelled Gulf India local-demo bundle
is separately activated only under `environment=local`; its command refuses every other environment
and does not satisfy or bypass the production gates. Non-activatable test fixtures remain test-only.
