# Phase 5 Implementation Plan — Pricing & Promotions

_Companion to `plans/local/plan.md`, `plans/local/tasks.md`,
`plans/local/phase4-implementation-plan.md`, and `plans/local/post-phase3-implementation-plan.md`._
_Specification authority: `docs/demand_forecast_poc_spec.md` §§3.5–3.6, §§4.6–4.9,
§8.1, §§10.2–10.5, §§11.2–11.4, and §§11.8–11.10._
_Data authority: `contracts/retail_v2/schema.yaml`, `contracts/staging/staging-v2.yaml`,
`contracts/onboarding/temporal-evidence-policy-v2.json`,
`contracts/onboarding/publication-selection.schema.json`, the versioned Phase 5 selection/input-
authority successors frozen in `P5-1`, and explicitly selected immutable publications/selections._
_Policy authority: `contracts/guardrails/price_response.yaml`,
`contracts/guardrails/pricing_rules.yaml`, and finalized decisions in
`docs/OPEN_DECISIONS.md`._
_Presentation authority: `docs/ai_retail_intelligence_dashboard_multicurrency_v6.html`, the
approved Phase 5 parity/data matrices, and approved amendments to already-frozen screen matrices._
_Validation authority: `contracts/validation-policy.yaml`; repository CI remains prohibited._

**Revision 9 — 2026-08-05. DRAFT FOR REVIEW. PHASE 4 IS IMPLEMENTED, BUT PHASE 5 RESULT-BEARING
WORK MUST NOT START UNTIL `P5-0`, THE TEMPORAL-EVIDENCE GATES, AND `P5-1P` PASS. EXISTING UI
CHANGES MUST NOT START UNTIL THEIR `P5-0P` AMENDMENTS PASS.**

Revision 9 is still a plan, not implementation authorization. It closes the final review findings:
source selection precedes every pin; rich `local` and sparse diagnostic `dev` scopes cannot collide;
all downstream jobs receive explicit pin/authority paths; Phase 5 result-selection events and the
activation-set share one PostgreSQL transaction while post-commit JSON is evidence only; repository
paths follow the established `ml/src/retail_ml`, `db/migrations/versions`, `datagen/configs`, and
package-local test structure; selection identity exclusions are versioned and cross-language; local
serving configuration is secret-free; preview-only controls are distinct from business-live and hard-
disabled controls; the duplicate competitor-modal selector families have one explicit presentation
authority; and the Promotion Performance Forecast chart interpretation is decided. It also
records that the stale default run affects direct `build_expected_pin.py --check`, while the normal
`tools/dev.py` repin path already supplies `--run`. Phase 5 ends at independently verified bundles,
transactional materialization, a separate activation, and local read-only serving/smoke. Container
release, process drain/cutover, deployment authority, and cross-host database restore belong to
Phase 6–8 planning and are not Phase 5 deliverables. No historical artifact is retrofitted by plan
text.

This plan defines the implementation boundary for Phase 5. It is intentionally more explicit
than a feature checklist because the phase combines statistical acceptance, local-currency
pricing rules, cost capability, competitor evidence, promotion privacy, four new read-only pages,
and corrective work on the existing client demo. Creating or reviewing this plan does not approve
model results, source reinterpretation, screen deviations, workflow mutations, or deployment.

The original HTML is the exact presentation reference: navigation, page titles, subtitles,
controls, filter order, cards, tabs, table columns, action placement, modal surfaces, spacing,
responsive composition, and common shell remain recognizable and ordered as shown there. The
HTML's hard-coded sample values and JavaScript are not data, model, policy, accessibility, or
behavioral authority. Known duplicate handlers, incorrect table indexes, blanket currency
replacement, inert filters, and unsupported sample values must not be copied into React.

The client-demo objective is broad but governed: every materially different truthful data/model
state should be reachable from accepted deterministic rich/sparse publications, including both
markets, increase/reduce/hold recommendations, elasticity refusal, margin available/unavailable,
competitor match/availability, conditional promotion, exact zero, filtered empty, loading, partial
capability, and disabled workflow controls. Stale, missing/corrupt, and panel-failure behavior uses
separate non-mutating negative-state adapters, not a damaged accepted publication. Component
fixtures may prove rendering but must never be served as live demo facts.

---

## 0 · Recommendation, status, and approval boundary

### 0.1 Recommended order

The required implementation order is:

1. Reconcile the final Phase 4 authority: selected source publication, active forecast and
   inventory runs/selections, current capabilities, retained evidence, parity reviews, and carried
   unavailable reasons.
2. Run `P5-0P`, the whole-application UI audit and contract-amendment gate, alongside safe source
   planning. Freeze every approved change to the shell, Data Management, Demand Forecast, and the
   fourteen inventory/replenishment pages before changing those developed surfaces.
3. Freeze source-native availability semantics for sell prices, promotions, competitor
   observations/matches, and temporal cost. Wire the v2 readiness evaluator as an identity-safe
   retained sidecar without changing Gate B or the base publication manifest.
4. Clear `P5-1P`: state coverage, price-panel eligibility, model/baseline/candidate protocol,
   untouched confirmation, strict gates, promotion-uplift disposition, and competitor-match
   evaluation must be approved before response-rich results are inspected.
5. Produce and independently verify deterministic response-rich and pricing-evidence-sparse source
   publications. Append schema-valid Decision-#73 source candidate → approved → active records before
   generating either reviewed v1 pin: rich uses `retailer-demo × tenant-demo × <capability> × local`,
   while the non-public sparse diagnostic uses the same retailer/tenant/capabilities in `dev`. For the
   rich lineage, update the shared expected pin through the normal reviewed repin path before the
   mandatory feature → forecast → inventory rebuild. Pass the sparse pin and input-authority paths
   explicitly through every downstream job; never overwrite the shared rich/default pin. A source
   selection or pin change is never result activation.
6. Freeze the remaining Phase 5 run, acceptance, verifier, pricing-rule, cost, competitor,
   promotion, OpenAPI, export, modal, and screen contracts before reading result outputs.
7. Build market-local weekly price panels, fit the observational Poisson response model, apply
   department × price-tier shrinkage, run seeded episode-block resamples and rolling-origin
   holdouts, and enforce strict per-market gates.
8. Independently build and verify competitor and promotion foundations. Recommendation generation
   may consume them only by their accepted manifest and verifier-record hashes.
9. Generate revenue-objective candidates after all foundations pass. Apply market/currency policy,
   grid/endings, confidence-scaled action caps, support clamp, dominance, product protection, and
   evidence gates before ranking.
10. Keep generated-cost margin visibly labelled as a synthetic scenario. Client margin remains
    unavailable without client-actual, positive, provenance-matched, same-currency cost-as-of.
11. Publish and independently verify one immutable result bundle per rich/sparse lineage. Materialize
    each verified bundle in its own PostgreSQL transaction without activating it.
12. In one separate PostgreSQL transaction, append the verified rich Phase 5 result-selection v2
    lifecycle events and exactly one activation-set referencing their active IDs. Export any JSON
    activation receipt only after commit as derived evidence, never as a second authority or part of
    the atomicity claim. Then serve the activation locally through the existing Phase 3/4 process
    pattern against Compose PostgreSQL. Retain the sparse result bundle as non-active reproducibility
    and isolated API-integration evidence; naturally sparse cohorts within the rich bundle demonstrate
    refusal states in the client UI.
13. Implement the four Phase 5 React pages in exact original-HTML composition, apply only approved
    existing-UI amendments, and complete desktop/mobile, data-value, currency, accessibility,
    state-coverage, local browser, and human-review gates for Demo 5.

No result-bearing implementation may skip ahead because current canonical tables appear populated.
The present sell-price and promotion rows are landing-time backfills. Their volume and business
effective dates do not establish historical point-in-time availability.

### 0.2 Why source remediation precedes elasticity and promotion modelling

The current curated publication contains a large amount of useful price, promotion, competitor,
cost, sales, and inventory data. It is structurally promising but does not yet prove all required
decision-time facts:

- all 289,884 canonical sell-price rows are marked `landing_backfill` and share the current
  publication's known-as-of boundary;
- pricing readiness therefore reports `pricing_elasticity.available = false` with
  `PRICE_AVAILABILITY_BACKFILLED`;
- all 811 promotion rows are also landing-time backfills, so historical uplift cannot be admitted
  merely from their business-effective periods;
- competitor price observations are origin-visible, but product attributes are empty and the
  current matches use synthetic attribute-match evidence;
- cost has stronger posted evidence, but the current valuation artifact contains 68 unavailable
  rows across four stores and four DCs—including the Pune overflow and Brooklyn MFC nodes—and 73
  rows carry an unverified `FIFO` label over a WAC-derived value; any generated cost is suitable
  only for a clearly labelled synthetic-margin demonstration;
- the source price table is an event history, not automatically a complete weekly panel. Point-in-
  time last-observation carry-forward, observation coverage, price-level support, transition count,
  staleness, and leakage treatment must be frozen before eligibility is calculated.

Without this remediation the product could display plausible elasticities that were unknowable at
the claimed origin. The honest current state is temporal `unavailable` with
`PRICE_AVAILABILITY_BACKFILLED`, while statistical sufficiency remains `not_evaluated`; it is not
yet `insufficient_evidence`. A native-observed sparse panel may be source-ready while its separate
statistical disposition is `insufficient_evidence`. The response-rich preset must earn live
recommendations through new evidence; the sparse preset must demonstrate that latter refusal path.

### 0.3 Current phase gates

| Gate | State at plan creation | Required before |
|---|---|---|
| Phase 4 code and serving slice | Implemented on current `main` baseline through migration `0020_safety_stock_drivers.py` | Record and retain in `P5-0` |
| Active forecast authority | **Unresolved:** old smoke evidence names `fr_5f6fa2015d80eee5` / `fv_ba2791b4273e3b4f`, released history names current event 23 as `fr_a08dfd164b77ac34` / `fv_b0a75559c2a1fb40`, while the closure record and current manifests name `fr_953a83f76576103d` / `fv_ff2c77dce6410035`; the old smoke bytes are not retained | Reconcile artifact, selection, live PostgreSQL activation, API, and UI lineage in `P5-0`; no listed identity is adopted by plan text alone |
| Active inventory authority | **Unresolved:** old smoke evidence names `ir_b10bb797108e80a7` / `iv_b10bb797108e80a7`, while the current inventory manifest names `ir_1a51973dd1a17d32`; the released history's `inventoryAuthorityLedger` contains no inventory events and carries forecast-shaped identities | Reconcile committed ledgers, materialized source-selection links, and the live activation/current views in `P5-0`; retain current-vs-replay distinction and do not infer inventory authority from the malformed ledger |
| Source-selection authority | **Unresolved:** the measured §1.3 evidence is the on-disk `run-adac9e85dccb56e8` publication and the current inventory manifest names `sel_3c2c4db8b76109d9`, while old smoke evidence names `sel_2d3c5e156bedabd4` against a publication whose curated bytes are absent | Establish one coherent selected pin in `P5-0` before source/model work |
| V2 readiness authority | **Unwired:** `build_readiness_report()` is called only by tests; production selection generation binds Gate B's fingerprint and writes hard-coded `ready/sufficient` after its separate capability mask passes | `P5-D24`/`P5-1` must wire and persist the evaluator, freeze evidence-flag/sufficiency producers, reconcile Gate B, and bind selections to the actual v2 report before `P5-2` |
| ML expected-pin authority | **Direct check is stale and selection is under-scoped:** `contracts/ml/expected-pin.json` matches retained `run-adac9e85dccb56e8`, but `tools/build_expected_pin.py` defaults to absent `run-b847177c11ac724d`, so direct `python3 tools/build_expected_pin.py --check` exits 2. The normal `tools/dev.py` repin path passes `--run run_id` and bypasses that stale default; it is not currently broken for this reason. Current pin/selection helpers also collapse full scope to capability | `P5-0` records both the defect and bypass; `P5-D25`/`P5-1` require active source selections before pinning plus explicit run, pin/authority paths, job purpose, evidence root, retailer, tenant, environment, and separate rich-local/sparse-dev v1 pin artifacts |
| Runtime selection authority | **Unwired/incomplete:** `resolve_selection()` has no production consumer, does not derive the unique live ledger head, and does not itself verify schema, `recordId`, retained bytes, DuckDB, or the v2 report | `P5-D25`/`P5-1` freeze selection-v2/legacy-v1 parity, add one full-ledger preflight, and thread explicit selection/pin/authority paths through every model, verifier, publisher, materializer, activation, and serving job |
| Forecast temporal capability | Current accepted forecast evidence is `demand_forecast_non_pit`, declares `pitEligible: false`, and carries `LANDING_BACKFILL_DEPENDENCY` under Decision #49 | Preserve the disclosure at a current pricing origin; never use it to support a historical PIT claim; republish as non-PIT unless new evidence independently earns `point_in_time_forecasting` |
| Inventory replay acceptance | Not accepted: manifest-level `REPLAY_NO_CANDIDATE_IMPROVEMENT` plus cohort-level `REPLAY_GATE_FAILED`; current-snapshot outputs remain active | Replay-derived benefit claims remain unavailable and both evidence layers are retained |
| Price temporal availability | Unavailable: all 289,884 rows are `landing_backfill`; reason `PRICE_AVAILABILITY_BACKFILLED` | `P5-1` and `P5-2` |
| Structural price variation | Promising in both markets, but not yet an admissible weekly PIT panel | `P5-2`, `P5-4` |
| Response-rich acceptance preset | Config intent exists, but no accepted Phase 5 publication exists | `P5-2` through `P5-4` |
| `pricing-evidence-sparse` preset | Named locally but not yet a checked-in, selected acceptance profile | `P5-2` |
| Strict price-response policy | Existing `price_response.yaml`: negative beta, bounded magnitude, sign consistency, resample stability, holdout improvement, coverage, and minimum gated count | Freeze unchanged or approve a pre-result amendment in `P5-1P`; `P5-3` may only version that frozen protocol |
| Local pricing rules | Existing India West/INR and US New York/USD grid and ending rules; 5% maximum per-cycle change | Resolve and golden-test in `P5-3`/`P5-5` |
| Temporal cost | Generated PoC receipts/cost have posted temporal evidence but are not client-actual; current calculation is WAC, while 73 served valuation rows are incorrectly labelled FIFO and 68 rows are unavailable | Reconcile carried method labels/coverage in `P5-0`/`P5-0P`; freeze synthetic-margin labelling, real-cost provenance, and genuine FIFO refusal/implementation in `P5-1P`/`P5-3`/`P5-5` |
| Competitor observations | 300,611 origin-visible price rows | Source/freshness contract in `P5-1` |
| Competitor products/matches | 1,440 products and 1,440 active matches; brand/model/GTIN attributes are null and current matched attributes are synthetic | Match-quality remediation and gates in `P5-2`/`P5-6A/B` |
| Historical promotion evidence | 811 promotions and 19,527 merchandise targets, but promotion availability is landing-backfilled | `P5-1`, `P5-2`, `P5-7A/B` |
| Promotion privacy | Decision #19 permits aggregate segment counts/mix and defers customer PII, cannibalisation, and bundles | Retain unless separately reopened before `P5-7A/B` |
| Phase 5 run/acceptance/verifier contracts | Missing | `P5-3` |
| Phase 5 database migration and OpenAPI | Missing | `P5-3`, `P5-8` |
| Four Phase 5 parity/data matrices | Missing | `P5-3`, before page APIs or React work |
| Existing UI remediation register | Missing; audit findings are not yet approved contract amendments | `P5-0P` |
| Client-demo state coverage contract | Missing | `P5-1P`, before profile generation |
| Local serving selection | Missing: current Go startup and browser requests do not bind an explicit retailer × tenant × environment plus activation-set ID | Freeze a schema-valid, fingerprinted, secret-free local server configuration in `P5-3`/`P5-8`; load the DSN only from `RETAIL_POSTGRES_DSN`; browser labels never authorize data scope. Deployment-grade startup authority is deferred to Phase 6 |
| Config Builder parity for new profiles | Missing: Decision #32 makes `datagen/config-builder.html` the supported authoring surface, but current promotion rows lack the proposed lifecycle/mechanic fields | Add lossless builder/import/export/default/validation/preset-sync work in `P5-1`/`P5-2` before checking in profiles |
| Four Phase 5 pages | Pricing nav labels exist but are inert; no components, routes, schemas, or endpoints exist | `P5-8`, `P5-9` |
| Existing-page visual acceptance | Phase 4 ledger still leaves all fourteen desktop/mobile screenshot and human reviews open | `P5-0P`, `P5-9` |

### 0.4 Workstream states

| Workstream | State at plan creation | Authorization rule |
|---|---|---|
| `P5-0` entry reconciliation | First authorized package | Read-only reconciliation and evidence correction only |
| `P5-0P` existing UI/parity amendment | Gate, not a convenience backlog | Must approve each changed existing element before implementation |
| `P5-1` temporal source/readiness/input-authority contracts | Planned | After `P5-0`; operationalize `P5-D24`/`P5-D25`, non-statistical producers, identity-safe sidecars, stage dependency identities, and Config Builder contracts; no model results |
| `P5-1P` pre-result protocol/demo freeze | Gate before profile generation | After `P5-1`; freezes model/demo/matching/promotion evaluation and completes statistical-sufficiency producers before `P5-2` |
| `P5-2` rich/sparse source publication and mandatory upstream repin | Planned | After `P5-1P`; active rich-local/sparse-dev source selections before separate reviewed pins/input authorities, then mandatory explicit-path feature/forecast/inventory rebuild evidence |
| `P5-3` remaining artifact/API/screen contract freeze | Planned | After measurable source readiness, before model-result inspection |
| `P5-4` elasticity | Planned | After `P5-2` and `P5-3` |
| `P5-5` recommendations/simulation/cost | Planned | Only accepted elasticity rows; margin additionally requires cost |
| `P5-6A/B` competitor intelligence | Planned | Verified foundation before `P5-5`; monitor/integration after exact-hash consumption |
| `P5-7A/B` promotion planning | Planned/conditional | Safety plus amended/not-amended foundation before `P5-5`; model-derived package disposition after |
| `P5-8` publication/database/activation/local API | Planned | Independently verified bundles; transactional materialization; separate rich activation; sparse non-active integration evidence |
| `P5-9` exact UI and Demo 5 | Planned | After approved matrices and live read models |

### 0.5 Non-negotiable invariants

1. **Observational, not causal.** Elasticity and projected effects are model-implied associations.
   UI, API, exports, and evidence must not call them causal lift or guaranteed outcome.
2. **No effective-date substitution.** `effective_from`, promotion dates, or a price-history date do
   not prove that a record was available at a historical model origin.
3. **Market-local models and rules.** Raw INR and USD price levels never share a price tier,
   shrinkage pool, grid, floor, ceiling, or candidate comparison.
4. **Operating currency is not reporting currency.** Recommendation inputs, guards, competitor
   comparisons, cost, and margin remain in the market's operating currency. Approved FX may
   convert aggregate reporting values for display only and must retain as-of lineage.
5. **Revenue before margin.** Accepted beta, forecast, current price, and candidate price can
   support revenue projection. They never imply margin. Margin additionally requires positive,
   provenance-matched, same-currency cost-as-of.
6. **No synthetic client margin.** The current local PoC cost is generated even where its temporal
   grade is native-posted. It may support an explicitly labelled `synthetic margin scenario` only.
   Client margin requires separately supplied client-actual positive cost provenance; temporal
   grade alone is insufficient. The synthetic scenario never alters the primary revenue
   recommendation, price, guardrail, rank, KPI, promotion table, or chart.
7. **Strict response gates.** The Phase 5 plan does not inherit the M5 demonstration's relaxed
   resample-IQR threshold. The strict contract is enforced independently per market and enabled
   department.
8. **Sparse means reason-coded unavailable.** An ineligible series/department/market returns a
   stable reason and assessed denominator. It does not disappear and does not receive a neutral
   beta or zero recommendation.
9. **Competitor evidence is bounded.** Low-confidence, stale, rejected, ambiguous, or unmatched
   products cannot drive a price recommendation. Competitor response remains an input bound, not
   an automatic action.
10. **No scraping or provenance ambiguity.** Engagement competitor data comes from approved client/
    licensed extracts or APIs. Deterministic local competitor data uses the closed canonical
    `evidence_class = synthetic`, keeps `derivation_class` and exact source system/instance separate,
    and may display `Synthetic demo` only through a distinct use-purpose/disclosure field. It is
    never presented as observed client/market fact. The original HTML's web-collection option
    remains disabled or changes only through an approved amendment.
11. **Promotion scope is deterministic.** Conditions are AND within one scope row and OR across
    rows; merchandise precedence is `sku > department > category`; equal-precedence conflicting
    discounts fail closed.
12. **Decision #19 remains binding.** Aggregate segment mix is allowed. Customer-level PII,
    bundle modelling, and cannibalisation remain unavailable without a separately approved privacy
    decision and contract.
13. **Forecast and inventory authority remain explicit.** Every result carries consumed run and
    version identities. A Phase 5 publication cannot silently read whichever upstream bundle is
    current later.
14. **One immutable rich activation-set.** Rejected and accepted bundles are retained.
    Materialization is append-only/transactional; one later PostgreSQL transaction inserts the
    result-selection v2 lifecycle events and one rich activation-set referencing exactly one verified
    bundle and one valid active selection for each claimed closed capability. Any JSON receipt is
    post-commit evidence only. Sparse result materialization remains non-active.
15. **PostgreSQL-only serving.** Go never reads DuckDB, Parquet, or model files in a request path.
16. **Read-only Phase 5.** Approval, review assignment, owner changes, schedules, alert creation,
    competitor-link mutation, promotion creation, publish, rollback, and execution remain disabled
    and perform no network mutation. Phase 5 may support stateless non-persisting simulation.
17. **Exact UI structure.** Every original visible element and modal surface is represented in a
    reviewed matrix, in original order, even when its value/action is unavailable.
18. **No sample leakage.** Original HTML values are visual examples only. React production paths
    contain no hard-coded product, KPI, recommendation, promotion, match, workflow, or currency
    facts.
19. **Existing contracts change before code.** An existing Data Management, Demand Forecast, or
    inventory element changes only after its decision and matrix row are versioned and approved.
20. **Exact zero is zero.** Zero, filtered-empty, no source evidence, insufficient model evidence,
    stale, missing, corrupt, and partial capability are distinct states.
21. **Scope consistency.** The original shell has no Market control: market is derived from the
    reviewed local server scope and canonical Store/region selection. Visible global Store/Channel and page
    filters constrain every affected row, KPI, chart, summary, export, and modal consistently, or
    the element is labelled global/independent. Channel is disabled/labelled where grain is absent;
    adding a visible Market selector requires an explicit presentation amendment.
22. **Stable page composition.** Loading and panel failure preserve page structure with accessible
    skeletons or local error states; one unavailable panel does not destroy unrelated evidence.
23. **No enabled-looking inert control.** Every control either performs the reviewed read-only
    behavior or is natively disabled with a business prerequisite and no handler.
24. **Channel is explicit.** Price panels, response rows, recommendations, scenarios, filters, and
    lineage preserve `channel_id`. Any future channel collapse requires a frozen, independently
    reconciled policy; it is never an implicit aggregation.
25. **Demo breadth comes from governed data.** Deterministic generator profiles and accepted
    publications create varied demo states. Rendering fixtures remain confined to tests.
26. **Readiness must execute, not merely exist.** Every Phase 5 selection binds an operational,
    persisted v2 report derived from registered evidence producers. Gate B aliases, test-only
    calls, caller booleans, and hard-coded ready/sufficient values cannot establish capability.
27. **Source identity changes propagate.** Under current contracts a new source publication changes
    the expected pin, feature identity, forecast run/version, inventory run, and downstream
    activation lineage. Phase 5 rebuilds that chain, prepares explicit successor inputs, and
    selects only verified results in the separate activation step; logical-content similarity is not an
    identity shortcut.
28. **Semantic identity is not audit metadata.** Creation/publication/verification timestamps,
    physical paths, execution telemetry, and physical byte descriptors remain retained audit data
    under frozen volatile-pointer rules, not inputs to semantic run identity. An independent
    verification attempt binds a completed manifest; it is never an artifact inside the set it
    verifies.
29. **Historical selections are immutable.** Gate-B-bound legacy selection records remain
    reproducible historical ledger evidence. `P5-D24` applies prospectively: a v2 readiness binding
    creates a new selection identity/lifecycle and never rewrites an old record or uses released-
    evidence reconstruction to authorize a new Phase 5 selection.
30. **Serving audience is reviewed server context.** Retailer, tenant, environment, bundle, and
    activation IDs come from schema-valid, fingerprinted, secret-free local server configuration;
    the DSN comes only from the fixed environment boundary. Browser labels,
    query parameters, and cache collisions never establish or cross that authority.
31. **Negative demo evidence is isolated.** Missing/corrupt/stale/panel-failure screenshots use
    versioned, non-mutating API adapters/fixtures. They never corrupt or masquerade as the accepted
    rich audience, and they are not production UI mocks or hidden client toggles.

---

## 1 · Verified starting point

### 1.1 What Phase 5 does not yet have

At plan creation the repository has no Phase 5 pricing model package, pricing engine package,
immutable pricing bundle, acceptance/verifier schema, pricing database migration, pricing Go read
model/handler, generated TypeScript pricing schema, or React page for any of the four destinations.
`ui/src/App.tsx` displays the Pricing navigation labels but its `PageId` union, click handling,
content routing, URL validation, and mobile navigation omit those destinations.

The absence is useful: the phase can still freeze temporal, model, policy, API, and UI contracts
before result-bearing code creates accidental authority.

### 1.2 Conflicting upstream authority evidence and carryovers

The repository does not currently expose one self-consistent Phase 4 authority identity:

- old API smoke evidence records forecast `fr_5f6fa2015d80eee5` /
  `fv_ba2791b4273e3b4f`, inventory `ir_b10bb797108e80a7` /
  `iv_b10bb797108e80a7`, source selection `sel_2d3c5e156bedabd4`, and fifteen successful
  inventory/replenishment routes;
- released activation history records that forecast identity as superseded and names event 23 as
  current forecast `fr_a08dfd164b77ac34` / `fv_b0a75559c2a1fb40`;
- the forecast closure record, current forecast manifest, and current inventory manifest instead
  consume forecast `fr_953a83f76576103d` / `fv_ff2c77dce6410035`;
- the current inventory manifest names inventory run `ir_1a51973dd1a17d32` and source selection
  `sel_3c2c4db8b76109d9`;
- the committed `contracts/ml/expected-pin.json` matches the only retained
  `run-adac9e85dccb56e8` publication and currently hashes to
  `9b5928c270ccd8559af8f931b5761b4c07fe8e7e17eb83ebe9e4ebd614a9dab3`, but
  `tools/build_expected_pin.py` still declares
  `RUN = run-b847177c11ac724d`; its own `--check` exits 2 because that retained evidence is absent,
  so the pin is not presently reproducible through its declared check path;
- the old smoke forecast identity is explicitly listed without retained bytes, and its source pin
  does not match the only curated publication currently retained on disk;
- released history's `inventoryAuthorityLedger` has no inventory events and contains forecast-
  shaped identities, so it is not valid inventory authority evidence.

`P5-0` must therefore reconcile committed JSON selection ledgers to materialized
`source_selection_id` values and then to live PostgreSQL activation/current views, retained
artifacts, manifests, API evidence, OpenAPI, and UI lineage. It must not choose one of the
conflicting files merely because it is named `current` or `live`. The §1.3 measurements below are
explicitly measurements of curated publication `run-adac9e85dccb56e8`, not proof that it is the
active serving authority.

The inventory candidate preserves current-snapshot analytics but does not pass replay acceptance.
The run manifest records `REPLAY_NO_CANDIDATE_IMPROVEMENT`, while per-cohort acceptance evidence
records `REPLAY_GATE_FAILED` for calibration/holdout gates. Both reason layers are retained.
Replay-derived fill-rate, service, working-capital, revenue-benefit, and policy-superiority claims
remain unavailable in Phase 5.

The accepted forecast is explicitly non-PIT under Decision #49: capability
`demand_forecast_non_pit`, `pitEligible: false`, reason `LANDING_BACKFILL_DEPENDENCY`. A current
pricing decision may consume its accepted P50 with that disclosure, but it cannot support a claim
that a historical pricing origin had a point-in-time forecast. Republishing on a Phase 5 source pin
retains `demand_forecast_non_pit` unless new independent evidence earns
`point_in_time_forecasting`.

The Phase 5 publication must record the exact selected source, forecast, and inventory identities
it consumed. If native price/promotion evidence changes the selected source fingerprint or forecast
features, the feature build, accepted forecast, and inventory bundles must be regenerated,
republished, prepared as explicit successors, and selected only after verification in the separate
activation step rather than combined across incompatible pins. Current feature, forecast, and inventory identities bind the
complete source publication identity; Phase 5 has no implemented domain-subset equivalence that can
preserve them.

### 1.3 Current canonical evidence inventory

Curated DuckDB publication `run-adac9e85dccb56e8` contains the following measured Phase 5-relevant
rows. These are retained-file measurements, not an active-selection assertion:

| Canonical role | Rows | Current evidence disposition |
|---|---:|---|
| `sell_prices` | 289,884 | Structurally useful; all `landing_backfill`, therefore not PIT-admissible for elasticity |
| `competitor_products` | 1,440 | Product identities exist; descriptive attributes are empty |
| `competitor_prices` | 300,611 | `native_observed`; usable after freshness/scope verification |
| `competitor_matches` | 1,440 | All active with synthetic attribute-match explanation; not yet decision-grade matching evidence |
| `promotions` | 811 | Current/historical rows exist; all availability is landing-backfilled |
| `promotion_scopes` | 811 | Useful after origin and AND/OR semantics are verified |
| `promotion_merchandise_targets` | 19,527 | Useful after origin and precedence/conflict semantics are verified |
| `customer_segments` | 6 | Aggregate segment mix only under Decision #19 |
| `purchase_receipts` | 196,984 | Native posted evidence across India and US |
| `inventory_cost` | 196,918 | Generated PoC temporal cost rows; current transform computes WAC, while carried method labels do not prove FIFO |

The current sell-price distribution includes 150,976 India/INR rows and 138,908 US/USD rows,
covering 2,880 series in each market. Effective weeks span 2016-07-25 through 2026-07-20, but all
rows share a publication-era known-as-of timestamp. Those counts demonstrate potential variation,
not historical admissibility.

### 1.4 Structural price variation versus accepted panel eligibility

A source-only exploratory audit, deliberately ignoring temporal admissibility, found the following
potential populations with at least 52 raw observations, at least three raw price levels, and at
least five raw transitions. The first count preserves the fitted SKU × store × channel grain; the
second is the distinct SKU × store unit used by the ≥25 department gate and therefore cannot be
channel-doubled:

| Market | Department | Potential SKU × store × channel series | Potential distinct SKU × store pairs |
|---|---|---:|---:|
| India | Apparel | 104 | 52 |
| India | Automotive | 108 | 54 |
| India | Beauty | 108 | 54 |
| India | Books | 100 | 50 |
| India | Electronics | 96 | 48 |
| India | Groceries | 204 | 102 |
| India | Health | 112 | 56 |
| India | Home | 124 | 62 |
| India | Sports | 104 | 52 |
| India | Toys | 120 | 60 |
| United States | Apparel | 108 | 54 |
| United States | Automotive | 112 | 56 |
| United States | Beauty | 112 | 56 |
| United States | Books | 120 | 60 |
| United States | Electronics | 156 | 78 |
| United States | Groceries | 100 | 50 |
| United States | Health | 80 | 40 |
| United States | Home | 92 | 46 |
| United States | Sports | 132 | 66 |
| United States | Toys | 108 | 54 |

These numbers are discovery evidence only. They are neither temporally admissible nor accepted
model counts. Before any generated result is inspected, `P5-1P` freezes a rich-profile design
target of at least 50 potential distinct SKU × store pairs per intended enabled market/department,
twice the 25-pair acceptance minimum. That is a planning buffer, not a relaxed acceptance gate. A
scope below 50 must either receive origin-visible source enrichment before result inspection or be
predeclared disabled; no target may be changed after results. The retained audit currently places
three scopes below that design target: United States Health at 40 pairs, United States Home at 46,
and India Electronics at 48. `P5-1P` must record an explicit enrich-or-predeclare-disabled
disposition for each of those three scopes. The canonical table stores sparse price events rather
than one explicit row per week. `P5-3` must freeze event-to-week expansion and point-in-time last-
observation-carry-forward rules; `P5-4` must then independently calculate:

- at least 52 observed eligible weeks;
- at least 90% coverage over the assessment window;
- at least three supported price levels;
- at least five genuine transitions;
- at least two observations per price level;
- acceptable observation and decision-origin freshness;
- no future-known price, promotion, event, cost, forecast, or competitor input;
- a complete assessed-series denominator, including every reason-coded rejection.

### 1.5 Current cost and margin capability

Purchase receipts include 96,992 India rows and 99,992 US rows over the ten-year window. The
inventory-cost ledger contains 196,918 generated PoC rows with temporal evidence and currently
carries 129,778 `FIFO` versus 67,140 `WAC` method labels. The transform calculates quantity-
weighted WAC; a carried label does not prove receipt-layer FIFO depletion.

The current provenance path is also insufficient for the proposed client-actual gate. Generated
Business Central cost rows carry legacy `ERP_ACTUAL`; staging-v2 maps that dialect value to
`evidence_class = client`, and canonical `inventory_cost` drops the provenance fields while stamping
native-posted temporal evidence. `COST_NOT_CLIENT_ACTUAL` therefore cannot be inferred safely from
the current canonical row alone. Phase 5 must derive ownership/use-purpose from the governed source
run/profile, preserve closed evidence/derivation classes and exact source identity through canonical
cost/readiness, and explicitly refuse `ERP_ACTUAL` as proof that generated data is client-owned.

The current inventory-valuation artifact makes this a carried Phase 4 correctness issue, not only
a future Phase 5 rule: 73 valuation rows expose `cost_method = FIFO`, 32 expose `WAC`, 153 expose
`store_receipt_wac`, and 68 have `UNIT_COST_UNAVAILABLE`. The 68 unavailable rows span four
canonical `store` locations and four canonical `dc` locations; the Pune overflow and Brooklyn MFC
names are DC nodes, not separate canonical location types. The numeric values labelled FIFO are
WAC-derived, so read-only `P5-0` must record the exact repair set, `P5-0P` must approve the display
amendment, and `P5-2` must publish/materialize a successor rather than updating current rows in
place. Source method is audit input only, while computed method is `WAC` or unavailable until
genuine FIFO is implemented. The
inventory parity promise for `derived_lane_wac` must also reconcile to an actual artifact value or
remain absent; it cannot be implied by a nearby cost label.

Required Phase 5 distinction:

- client-actual, positive, same-currency, provenance-matched cost as of the decision origin may
  enable real/client margin fields;
- the current generated cost, even with native-posted temporal grade, may enable only a clearly
  labelled `synthetic margin scenario` that cannot alter primary pricing or promotion output;
- FIFO remains unavailable unless Phase 5 implements and verifies genuine receipt-layer/batch
  depletion rather than trusting a carried method label;
- reference product cost, future cost, cross-currency cost, stale cost, or missing cost leaves the
  margin objective, floor, and outputs unavailable while revenue remains eligible.

### 1.6 Current competitor capability

Competitor price history is stronger than sell-price history because its rows are
`native_observed`. However, all current competitor product brand/model/GTIN fields are null,
attributes are `{}`, and all matches carry a synthetic attribute-match explanation despite high
numeric confidence values from 0.82 through 0.9894.

Because this is locally generated PoC data, its source provenance must be classified
`evidence_class = synthetic` at the product/observation/match boundary, with
`derivation_class = native | derived` and exact source system/instance retained separately.
`Synthetic demo` is a use-purpose/presentation disclosure, not a new provenance enum or source
class. The data can demonstrate governed product behavior but must never be described as a live
client or independently observed market feed. Engagement capability remains unavailable until an
approved client/licensed source is supplied.

Phase 5 therefore needs an effective-dated match identity at tenant × retailer SKU × competitor ×
competitor SKU with method, compared attributes, confidence, review status, `observed_at`, and
`known_as_of`. Numeric confidence without auditable attributes cannot auto-accept a match. Matched,
needs-review, rejected, and no-match must all be first-class states.

### 1.7 Current promotion capability and privacy boundary

The canonical source contains 791 `historical` and 20 `active` promotion statuses. Its type field
contains 280 `clearance`, 262 `fire-sale`, 231 `runout-markdown`, and 38 `campaign` rows, plus scopes
and merchandise targets. These are current source vocabularies—not the original UI's Draft, Under
Review, Approved, Live, Completed lifecycle vocabulary, and not a complete Percentage Discount,
Fixed Price, Clearance offer-mechanic vocabulary. `historical` must not be silently mapped to
Completed, `active` to Live, or campaign class to offer mechanic. Because availability is landing-
backfilled, the current rows may support only the descriptive scope expressly approved by the
temporal contract and cannot support historical uplift training.

The task ledger's broad request for uplift, cannibalisation, bundle, and segment models conflicts
with finalized Decision #19. Decision #19 directly permits aggregate segment counts/mix and defers
customer/basket PII, cannibalisation, and bundles; `P5-D11` conservatively extends that boundary to
segment-specific response, offers, and targeting for this phase:

- in scope: origin-safe aggregate promotion uplift, applicability, overlap/conflict, inventory
  readiness, and descriptive aggregate segment count/mix only;
- unavailable unless the decision is reopened: segment-specific response, offer selection, or
  targeting at either aggregate or customer level; customer PII; basket modelling; bundle affinity;
  and cannibalisation.

The original HTML elements for deferred capabilities remain in place with explicit governed
unavailable presentation. Plan approval alone does not reopen the privacy decision.

### 1.8 Existing policy contracts

`contracts/guardrails/price_response.yaml` defines the strict response gate:

- beta must be negative;
- `0.30 <= abs(beta) <= 4.00`;
- sign consistency must be at least 0.90;
- resample-IQR ratio must be at most 0.80;
- at least 50 valid draws are required;
- rolling-holdout improvement must be positive;
- enabled-department accepted coverage must be at least 5%;
- each enabled department must contain at least 25 actually gated series.

`contracts/guardrails/pricing_rules.yaml` currently resolves shadow/revenue behavior, an absolute
5% maximum per-cycle change, `minActionCapPct = 2`, 12% margin floor where accepted client-actual
cost enables the primary margin capability, 0.70 dominance, nearest-step rounding, and market-local
grids/endings for India West/INR and US New York/USD. The specification defines
`minActionCapPct` as the lower endpoint of a **confidence-scaled maximum action cap** that rises
from 2% at dominance 0.70 to 5% at dominance 1.0; it is not a 2% minimum actionable change.
Candidates must also remain inside observed price support. `P5-1P`/`P5-3` freeze the exact
interpolation, clamping, rounding, and boundary order before results; these values are never
reinterpreted after results.

### 1.8.1 Required M5 reuse audit

The specification marks `price-response-poisson-eb-v1`, the pricing engine, and scenario core as
REUSE/REUSE+EXTEND, but compatible implementations are not presently checked into this repository.
Before reimplementation or porting, `P5-1P` must create the Phase 4-style reuse inventory:

- exact upstream repository and commit/tag;
- source file/module path and byte hash;
- dependency/runtime/license inventory;
- retained public behavior and golden vectors;
- assumptions coupled to the former schema, grain, currency, calendar, or artifact identity;
- adaptation grade: reuse unchanged, reuse+extend, redesign, or reject;
- reason for every rejected code path;
- target module and test/evidence mapping;
- proof that imported logic is pinned rather than rediscovered from a moving checkout.

The audit must explicitly cover the Poisson/EB response implementation, price-panel utilities,
candidate/pricing guardrails, closed-form scenario math, and any simulator/reorder integration. A
module is not called “reused” merely because the same algorithm is rewritten from memory.

### 1.8.2 Current readiness-authority wiring gap

The v2 capability definitions exist, but their evaluator is not an operational publication gate.
`build_readiness_report()` / `evaluate_capabilities()` in
`ingestion/src/retail_ingestion/readiness/evaluator.py` currently have callers only in tests. The
normal selection builder instead reads Gate B's separate `capabilityMask`, binds
`gate-b.json.semanticFingerprint` as `readiness.reportFingerprint`, and writes
`capabilityReadiness = ready` plus `capabilitySufficiency = sufficient` when that Gate B mask says
available. Gate B currently publishes different disclosure keys such as `pricing_elasticity` and
`competitor_intelligence`; it does not produce the closed v2 `price_revenue`, `price_margin`,
`promotion_aware_forecasting`, and `competitor_aware_forecasting` verdicts used by §3.3.

Phase 5 therefore cannot treat schema presence or test coverage as an executed capability gate.
Before any Phase 5 selection is approved or activated, `P5-1`/`P5-1P` must establish one
operational readiness authority with this non-circular order:

1. publish the immutable source publication under the existing Gate A/Gate B/publication identity;
2. evaluate readiness against that completed publication using an explicitly supplied policy
   path/id/hash and producer-registry path/hash—never “newest policy present” discovery;
3. persist `source_readiness_report.json`, evidence provenance, and Gate-B/v2 reconciliation as a
   post-publication retained sidecar that cites the source snapshot, Gate A/B fingerprints,
   publication semantic fingerprint and manifest SHA-256, governed market set, policy, and registry;
4. hash those sidecar files in a separate versioned readiness-retention manifest. Do not add them
   silently to `retail-ingestion-retained-evidence/v1`, whose current verifier requires exactly
   Gate A, Gate B, and publication-manifest files;
5. independently verify the publication and readiness sidecar, then create only the applicable
   source-input selection/pin authorization; result-bearing Phase 5 capability selections wait for
   their completed model/bundle verification; and
6. later copy the exact retained readiness bytes/hash into the Phase 5 bundle as lineage, never as
   the first or authoritative copy.

The readiness report cites the publication; neither Gate B nor the publication manifest cites the
report. Gate B's `capabilityMask`, Gate B semantic fingerprint, and publication manifest therefore
remain byte/identity-stable under readiness wiring. The JSON sidecar remains outside the curated
Parquet object enumeration, so it does not change publication `objectCount`, `/objects`, or DuckDB
bytes/hash. If reviewers instead approve a Gate-B mask
extension, publication-manifest reference, or any other identity-bearing change, that is an
explicit new source publication plus expected-pin, feature, forecast, inventory, selection, and
activation successor—not a side effect of wiring the evaluator.

`publication-selection.readiness.reportFingerprint` references the sidecar report's canonical
semantic fingerprint. The report must bind per-market/currency and applicable department coverage,
predeclared exclusions, and the deterministic aggregation from those scopes to the top-level
selection verdict. Every `ReadinessInputs.role_evidence`, `present_roles`, `evidence_flags`, and
`sufficiency` value comes from a versioned producer definition with canonical fields/queries,
threshold, source artifact, reason codes, producer, verifier, and fingerprint. `P5-1` freezes the
temporal/non-statistical producers and report mechanism; `P5-1P` freezes the price/promotion model
protocols first and then completes their statistical-sufficiency producers before `P5-2` executes
the final report. Source-level `demand_response_evidence` is never a proxy for later statistical
model sufficiency. Caller booleans and hard-coded `sufficient` remain prohibited.

Gate B → v2 reconciliation is asymmetric, not direct equality. Freeze a versioned crosswalk that
records source rule, target capability, direction, scope, and reason:

- Gate-B `pricing_elasticity.available = false` caps v2 `price_revenue`; `true` proves only the
  overlapping price-availability prerequisite and never proves v2 roles, demand-response evidence,
  or sufficiency;
- Gate-B `competitor_intelligence.available = false` caps v2
  `competitor_aware_forecasting`; `true` proves table presence only and is never sufficient;
- Gate B has no `price_margin` or `promotion_aware_forecasting` assertion, so the reconciliation
  records `not_asserted`, not pass or contradiction; and
- only an impossible combination under the frozen implication matrix is a contradiction. Missing
  counterparts and stricter v2 downgrades remain distinct reason-coded states.

Selection generation fails on a missing report/sidecar, unknown or unproven producer, wrong policy,
cross-market evidence leakage, Gate-B/v2 impossible combination, report/publication mismatch, or
`not_evaluated`/`insufficient_evidence` where an active lifecycle requires sufficient evidence.

The cost boundary deliberately remains two-stage. The existing v2 flag
`temporal_cost_ledger_matching_currency_scope` measures temporal/currency/scope evidence; generated
PoC cost may honestly satisfy that data-readiness predicate. `P5-D6` is a stricter business-claim
gate: generated cost can never authorize an active `price_margin` selection. If v2 reports the data
ready but provenance is generated, publish a reason-coded non-claim/rejected-candidate disposition
`COST_NOT_CLIENT_ACTUAL` and keep the primary margin capability unavailable; do not suppress the
flag or rewrite readiness as unavailable. Changing the v2 evidence flag itself to require client-
actual provenance would be a temporal-policy amendment requiring explicit pre-result approval.

### 1.8.3 Current expected-pin, selection, and resume-authority gaps

`contracts/ml/expected-pin.json` remains the exact v1 byte authority consumed by forecast and
inventory work. Two real defects must be fixed before Phase 5 source publication:

- `tools/build_expected_pin.py` defaults to stale `run-b847177c11ac724d`, while the committed pin
  and only retained publication are `run-adac9e85dccb56e8`. This breaks the direct/default
  `--check` path. It does **not** currently break the normal pipeline repin step:
  `tools/dev.py` passes `--run <run_id>`, which overrides the constant. `P5-0` records both the
  defect and that existing bypass so reviewers do not infer that generation or the phase-exit gate
  is failing for this reason.
- the helper resolves current selections by capability alone, dropping retailer, tenant, and
  environment. A capability match is therefore insufficient authority in a multi-audience ledger.

`P5-D25` repairs those mechanics without introducing Phase-6 release authority. The pin CLI takes
an explicit operation, run, pin path, input-authority path, job purpose, evidence root, retailer,
tenant, and environment; the authority record enumerates the complete capability scopes. A read-only
retained-entry check binds the exact `P5-0` entry record; build generation binds the reviewed rich or
sparse publication explicitly. Missing arguments, newest-file discovery, capability-only lookup,
zero/multiple current heads, schema mismatch, missing retained bytes, or report/publication mismatch
fail closed.

Both Phase 5 presets keep the existing three forecast/inventory capabilities in expected-pin/v1.
Before either pin is generated, the response-rich publication receives active source-selection v2
records in `local` and `pricing-evidence-sparse` receives active source-selection v2 records in the
non-public diagnostic `dev` scope. After rich source approval and pin derivation, the normal reviewed
repin step updates `contracts/ml/expected-pin.json` before the mandatory feature → forecast →
inventory rebuild and retains the predecessor pin/hash as evidence; this is an input-authority
transition, not runtime activation. The sparse pin remains explicit, is passed to every downstream
job, and never overwrites the shared rich/default pin.

Selection creation and validation are parameterized by the complete four-field scope and derive the
unique current supersedes-chain head from the whole applicable ledger. New result capabilities use
v2 `genesis | successor` proofs and insert candidate → approved → active database events only after
their bundle passes independent verification. Database materialization remains transactional and
separate from the later all-or-nothing PostgreSQL transaction that inserts those result-selection
events and one activation-set. Post-commit JSON is evidence only. A literal historical record marked
`active` is not current after a valid successor. No selection, materialization, or activation is
inferred from a filename containing `current`.

The client demo serves one reviewed response-rich activation containing intentionally sparse
series/departments so every reason-coded unavailable state is demonstrable. The full
`pricing-evidence-sparse` preset is retained as reproducibility/acceptance evidence and API
integration evidence against an isolated non-active materialization; Phase 5 does not invent a
second live tenant or a second runtime release procedure merely to demonstrate it.

Resume invalidation starts at the first stage that consumes a changed semantic dependency:

| Changed dependency | First invalidated stage and required successor |
|---|---|
| Source profile/schema, Gate A/B rule, canonical source bytes, or publication identity | New publication → reviewed expected pin → feature → forecast → inventory → Phase 5 downstream |
| Readiness policy/producer/crosswalk implementation only | New one-way readiness sidecar/retention → selection preparation → capability/model consumers; base publication and expected pin remain unchanged |
| Feature schema/code/policy | Feature → forecast → inventory and Phase 5 consumers |
| Forecast input/model/policy/acceptance | Forecast → inventory → Phase 5 consumers |
| Inventory input/policy/acceptance | Inventory → Phase 5 consumers |
| Phase 5 model/foundation/policy | First Phase 5 consumer only, then its dependent recommendations/API/UI |

Phase 5 ends at verified bundle → transactional PostgreSQL materialization → separate atomic database
result-selection/activation-set insert → derived receipt → local read-only serving/smoke, following
the already established Phase 3/4 pattern.
Container images, trusted-startup release records, process drain, cutover dossiers/receipts,
post-cutover serving authorization, deployment topology, and cross-host database dump/restore are
explicit Phase 6–8 release-hardening work. This plan neither requires nor authorizes them.

### 1.9 Existing UI implementation and demo debt

The current React application implements Data Management, Demand Forecast, and fourteen
inventory/replenishment pages. The final client-demo scope adds four pricing destinations for a
total of twenty pages.

The exact twenty-destination review inventory is:

1. Data Management;
2. Demand Forecast;
3. Inventory Overview;
4. Store Inventory;
5. Warehouse Inventory;
6. Inventory Ageing;
7. Stock Transfers;
8. Inventory Valuation;
9. Expiry & Waste;
10. Replenishment Planner;
11. Suggested Orders;
12. Supplier Planning;
13. Safety Stock;
14. Allocation & Fulfillment;
15. Replenishment Exceptions;
16. Stock Health;
17. Price Recommendations;
18. Price Simulation;
19. Competitor Monitor;
20. Promotion Planner.

The audit found these cross-page issues:

- the Pricing section is visible but inert, and the mobile menu exposes only Demand Forecast and
  Data Management;
- React renders enabled-looking inert buttons for Executive Overview, Performance Insights, Reports
  & Exports, Alerts & Notifications, Model Management, and Settings, while the original HTML also
  includes User Management and React omits it. `P5-0P` must disposition all seven individually,
  preserve their exact desktop/mobile group/order/icon/label, and prefer a visible native-disabled
  presentation with accessible business reason, no handler, and no history entry until their owning
  phase implements a real route. Any absence requires its own approved parity amendment;
- Data Management dashboard failure blocks unrelated pages at the application root;
- Data Management omits the contract/reference root `#dataManagement`, so title-only checks can
  pass while required DOM selector parity fails;
- browser back/forward is not handled because navigation uses `history.replaceState`, creates no
  push entries, and has no `popstate` handling;
- global Store and Channel filters affect Forecast but not Inventory, and Data Management scope is
  implicit;
- the currency selector changes shell text while Forecast hard-codes INR and Inventory uses the
  endpoint reporting currency; the shell overstates conversion coverage;
- the original selector/modal exposes INR, USD, EUR, GBP, and AED, while the current two-market
  generator produces only configured market-currency→reporting-currency pairs; EUR/GBP/AED have no
  frozen live-rate or disabled/unavailable contract;
- current Go startup and browser fetches bind no explicit retailer × tenant × environment plus
  activation-set ID, so local serving scope is not yet deterministic;
- no page-specific live-state minimum currently proves the varied Data Management, Forecast, and
  fourteen Inventory status/zero/unavailable possibilities; one default screenshot per page is not
  a demo-coverage contract;
- the footer uses dashboard-wide values regardless of page/filter and its forecast data is loaded
  only on the forecast page;
- loading/error states replace entire page composition rather than preserving cards and panels;
- API errors discard response reason codes, and inventory code infers stale state from an HTTP
  status string;
- several cards/tables render empty chrome instead of distinguishing exact zero, filtered-empty,
  no evidence, or unavailable;
- shared badges use free-text regular expressions rather than frozen field-specific enums;
- modal keyboard/focus behavior is inconsistent.

`P5-0P` converts this audit into versioned matrix amendments and regression evidence. Phase 5 is not
permission for an unreviewed visual redesign.

### 1.10 Existing page-specific corrections and unlocks

The audit identified the following concrete candidates:

1. Data Management omits the original toolbar positions for Add Data Source, Upload, and Run
   Validation. Existing read-only gates, capabilities, reconciliation, and quality-finding routes
   can make validation details live; writes remain disabled.
2. Data-source `lastRefreshAt` currently repeats a publication timestamp. It should derive each
   source's actual Gate A/manifest known-as-of and freshness evidence.
3. Demand Forecast summary is global while stores/workbench are filtered; it must be scoped or
   clearly labelled. Region must constrain valid stores.
4. Demand at Risk and Stock-out Risk are already implemented in Forecast, but two frozen matrix
   rows and the matrix prose still mark them unavailable; all stale contract references must be
   corrected before relying on either element.
5. Forecast Business Impact remains unavailable because no accepted comparable counterfactual
   exists; Phase 4 replay did not pass and Phase 5 must not invent one.
6. Forecast Scenario Planning may become a live stateless pricing scenario after accepted beta;
   save/apply remains disabled. Decision #53 keeps the existing Forecast promotion row unavailable
   with `NO_ORIGIN_VISIBLE_PROMOTION_PLAN`; new origin-visible evidence alone is insufficient to
   reverse it. Promotion elements become live only after the formal `P5-D23` amendment gate.
7. Forecast Compare Versions currently names a model and exposes only the active version. It must
   load compatible retained versions or present a governed unavailable state.
8. All user-facing phase/roadmap, package, policy-freeze, fingerprint, lineage-internal, and
   implementation explanations must be replaced with business prerequisites. Technical lineage
   remains available in governed detail/export surfaces, not primary business copy.
9. Inventory contract wrapper selectors are absent, and Demand Forecast panel IDs required by its
   matrix are absent.
10. Replenishment Planner omits the original select/checkbox column.
11. Inventory control order differs from the HTML because action and filter lists are extracted
    separately; ordered control groups are required.
12. Inventory button/status classes include names not defined in the React stylesheet.
13. Store Inventory hard-codes Lost Sales Exposure unavailable even though the accepted demand-at-
    risk artifact can provide a companion. It may be enabled only as projected demand-at-risk with
    assessed/withheld coverage, not realized lost sales.
14. Inventory Overview's “Accelerate replenishment” and ageing actions are currently bound to
    residual/dead cells rather than understock/urgent recommendations and ageing candidates.
15. Safety Stock renders SKU/store-cell rows, while the original contract requires policy-segment
    rows with SKU counts.
16. Allocation “Store Demand” uses a trailing-91-day requested-units basis; its label must state the
    period/basis or the data must be replaced with aligned demand.
17. Phase 5 accepted markdown/recovery policy plus temporal cost can potentially enable inventory
    NRV, markdown, obsolescence provision, category value, and expiry-recovery elements. Each needs
    an amended definition and cannot reuse a nearby metric.
18. Safety-stock promotion driver remains unavailable unless the versioned policy formula actually
    incorporates it; presence of a promotion model alone is insufficient.
19. Replay-dependent service, fill-rate, revenue, and working-capital benefits remain unavailable.
20. Safe exports and read-only drilldowns may be enabled with exact version/scope/currency lineage;
    mutation actions remain disabled.
21. Data Management source status needs a stable vocabulary covering Healthy, Delayed/Needs
    Attention, stale, missing, and validation failure. View Mapping may be read-only; Refresh and
    Retry remain disabled unless a separately authorized mutation route exists.
22. Demand Forecast Store View Priority Action needs its own deterministic mapping from accepted
    forecast exception, demand-at-risk, and inventory health, or must remain unavailable. The new
    Pricing Store View rule cannot be reused implicitly.
23. Inventory Waste Reduction is currently withheld only because no comparable prior period is
    supplied. Canonical history may enable it after freezing current/prior windows, scope, lineage,
    percent formula/sign/denominator, and lower/higher/exact-zero/no-prior behavior; it does not
    require a pricing-policy proxy.
24. Summary/cards must render from their own data even when the main table has zero rows. Existing
    Forecast Action Center and Store Drilldown modals need explicit explanatory empty states rather
    than blank bodies/tables.
25. Searchable existing and new tables need a frozen debounce duration, retained-previous-data
    behavior, request cancellation, out-of-order response protection, and predictable focus.
26. Phase 4 left screenshot/human review open for all fourteen inventory pages. Final Demo 5 visual
    acceptance therefore covers all twenty implemented destinations, even if a particular existing
    page receives no local Phase 5 code change.
27. Inventory Valuation currently carries unverified FIFO labels over WAC-derived values and lacks
    the separately promised `derived_lane_wac` value. Its method labels and unavailable coverage
    must be reconciled before any NRV/markdown/provision unlock is approved.

### 1.11 Original HTML behavior defects that are explicitly non-authoritative

The HTML's presentation is authoritative, but these behaviors must not be copied:

- global controls only display a toast rather than filtering data;
- page filters change some table rows while KPIs remain hard-coded;
- Price Recommendation actions and row handlers are registered more than once;
- the price-summary script reads wrong table-column indexes;
- a later competitor handler suppresses the earlier richer review workspace;
- calendar month/list buttons are inert;
- currency conversion uses fixed demo rates and blindly replaces currency-symbol text while
  leaving inputs unchanged;
- unsupported margin, workflow, privacy, and evidence fields are populated with sample numbers;
- AI Promotion Opportunities displays `8 recommendations` above only four sample rows; neither the
  count nor row count is data authority, and the React count must reconcile to filtered live rows;
- no pricing page defines loading, sparse, exact-zero, empty, stale, corrupt, missing, or partial-
  capability behavior.

---

## 2 · Authority, scope, and non-goals

### 2.1 Authority hierarchy

When sources conflict, apply this order:

1. finalized decisions and temporal/privacy/security contracts;
2. canonical/staging schemas, guardrail contracts, selected immutable source/acceptance evidence,
   and the exact ML input pin used by a job. Expected-pin/v1 proves forecast/inventory input bytes;
   it does not replace the Phase 5 full-scope input authority, readiness selection, verified result
   bundle, or activation-set;
3. `docs/demand_forecast_poc_spec.md` for product/model/data requirements;
4. approved Phase 5 decisions and frozen model, rule, run, acceptance, verifier, and API contracts,
   which may refine but not silently contradict higher authority;
5. `plans/local/plan.md` and `plans/local/tasks.md` for phase scope and completion ledger;
6. approved screen parity/data matrices and approved existing-screen amendments;
7. original HTML presentation;
8. HTML sample values and JavaScript, which are reference-only and never data authority.

A screen matrix may clarify how an unavailable value occupies its original position. It may not
override temporal evidence, cost capability, privacy, model acceptance, or phase ownership.

The following finalized-decision crosswalk is binding and prevents the Phase 5 proposals below
from silently reversing repository policy:

| Decision | Phase 5 binding |
|---|---|
| #6 | WAC is default; FIFO requires accepted batch/expiry and genuine layer depletion evidence |
| #14 | Competitor evidence is client/licensed; scraping is prohibited |
| #19 | Aggregate segment counts/mix only; customer/basket PII, cannibalisation, and bundles are deferred; `P5-D11` adds the conservative segment-response/offer/targeting boundary |
| #25 | Competitor matches are outputs; generator truth is evaluation-only and never served |
| #32 | `datagen/config-builder.html` is the supported generator authoring surface; checked-in presets, embedded presets, validation, and YAML/JSON import/export remain lossless and synchronized |
| #39 | Absolute pricing rules resolve per market × operating currency |
| #43 | Operating currency is separate from presentment/reporting currency |
| #44 | FX direction, precision, rounding, and aggregation follow the frozen contract |
| #45 | Each enabled market/department needs ≥25 actually gated distinct SKU × store pairs; sparse refusal is a separate demo |
| #46 | `channel_id` remains in canonical/fitted/served grain |
| #49 | Forecast capability remains `demand_forecast_non_pit` with `pitEligible: false` and `LANDING_BACKFILL_DEPENDENCY` unless new evidence earns PIT |
| #53 | Existing promotion feature remains unavailable with `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` until the explicit `P5-D23` amendment is approved |
| #70 | Business-effective dates never prove historical availability |
| #72 | Readiness and sufficiency vocabularies remain separate and closed |
| #73 | Selection scope, capability vocabulary, and candidate → approved → active lifecycle remain closed; legacy v1 bytes stay immutable and the Phase 5 v2 successor changes only identity-exclusion enforcement/storage portability |
| #74 | Candidate search uses a frozen development/untouched-confirmation protocol; `P5-D3` defines the pre-approved 13-origin Phase 5 extension |
| #79 | Provenance remains closed `client \| third_party \| synthetic` plus `native \| derived`; exact source identity and `Synthetic demo` use-purpose/disclosure stay separate |
| #92 | Forecast intervals/confidence beyond the calibrated cold-start horizon remain withheld and cannot be reconstructed in pricing |

### 2.2 In scope

- source-native price and promotion availability remediation;
- response-rich and sparse deterministic data profiles;
- market-local point-in-time weekly price panels;
- observational Poisson GLM price response with seasonality, trend, and approved events;
- department × price-tier empirical-Bayes shrinkage and strict per-market acceptance;
- revenue-objective price recommendations under local candidate/rule guards;
- optional cost-as-of margin and floor behavior;
- stateless non-mutating price simulation and Forecast scenario integration;
- effective-dated competitor matching, confidence, freshness, availability, and bounded response;
- promotion UI refusal states and, only after `P5-D23`, permitted origin-safe uplift,
  applicability, conflict, inventory readiness, and aggregate audience mix;
- immutable bundle publication, independent verification, PostgreSQL materialization/activation,
  Go read models, OpenAPI, generated types, strict Zod schemas, and four React pages;
- approved corrections to the shell and existing pages;
- deterministic demo-state coverage, visual/accessibility testing, and human review.

### 2.3 Explicit non-goals

- changing live prices, executing promotions, sending orders, or publishing to commerce systems;
- persistent approval, review, ownership, scheduling, override, alert, or audit workflows;
- scraping or unapproved web collection;
- causal claims from observational elasticity or uplift;
- result-bearing promotion logic before the formal Decision-#53/`P5-D23` amendment;
- cross-market pooling of local prices or cost;
- margin from reference, future, stale, cross-currency, missing, or silently generated cost;
- customer PII, basket-level affinity, bundle optimization, and cannibalisation without a new
  privacy approval;
- silently relaxing response gates to satisfy demo coverage;
- treating Phase 4 replay as accepted or publishing its withheld benefit claims;
- fabricating source rows, recommendation rows, margins, statuses, owners, approvals, or alert
  rules in the UI;
- redesigning accepted screens, changing original element order, or removing unavailable elements;
- using test fixtures as live client-demo data;
- allowing Go request paths to read files or recompute model-backed scores;
- API/UI containers, OCI/image release, deployment startup authority, process drain/cutover, and
  registry/origin publication assigned to Phase 6 release planning;
- PostgreSQL dump handoff, cross-host restore, and the blocking three-OS release-hardening matrix
  assigned to Phase 7/8;
- completing the full rich capture/workflow experience assigned to Phases 6–7.

### 2.4 Retention and evidence policy

Every source selection, model run, rejected candidate, accepted candidate, verifier result,
materialization, activation, screen contract, screenshot, and human review is immutable or
append-only. Rejection is evidence and cannot be overwritten by a later passing run. Missing
historical availability bytes may not be reconstructed from present-day landing timestamps.

---

## 3 · Target architecture and domain semantics

### 3.1 End-to-end flow

```text
approved origin-safe prices/promotions plus governed synthetic-evidence or approved client data
  -> staging/canonical validation + Gate A/Gate B + immutable publication
  -> retained v2 readiness/provenance/reconciliation sidecar
  -> full-scope source-selection v2 lifecycle (rich local / sparse diagnostic dev)
  -> explicit expected pin + reviewed full-scope input authority
  -> rebuilt feature, forecast and inventory publications with explicit pin/authority paths
  -> point-in-time market-local weekly price panels
  -> Poisson GLM + department/price-tier empirical-Bayes shrinkage
  -> episode-block resampling + rolling-origin holdout + strict market gates
  -> revenue candidate prices + local pricing rules + confidence/reason codes
  -> optional same-currency cost-as-of margin evaluation
  -> stateless scenarios + competitor bounds + permitted promotion planning
  -> immutable Phase 5 bundle + independent verification
  -> transactional PostgreSQL materialization
  -> separate atomic PostgreSQL rich result-selection-v2 + activation-set transaction
  -> deterministic post-commit evidence receipt (never serving authority)
  -> PostgreSQL-only Go read models/OpenAPI
  -> strict generated UI schemas
  -> four exact React pages + approved existing-page integrations
```

### 3.2 Phase 5 authority identity

The immutable **semantic** run identity must bind at least:

- tenant, retailer, environment, source publication, and exact source/capability selection IDs;
- forecast run/version and inventory run/version;
- bundle market set and canonical operating currencies; these are manifest lineage, not fields in
  the closed publication-selection scope;
- temporal-evidence, retail-v2, feature, price-panel, event, and cost fingerprints;
- model family/specification, shrinkage policy, seed, resample, holdout, and gate fingerprints;
- resolved pricing-rule fingerprint for every market/currency;
- competitor source/match-policy and promotion-policy/privacy fingerprints;
- run/acceptance schema versions and the required verifier-policy/schema identity;
- code revision and deterministic semantic execution contract;
- capability states by market, department, and element;
- output semantic fingerprints and logical row-count/control identities.

The manifest also retains physical object paths/bytes/SHA-256, execution profile/telemetry,
`createdAt`/`publishedAt`, and later verification timestamps, but the frozen fingerprint contract
excludes those non-semantic/audit fields exactly as versioned. The producer closes and hashes the
manifest before verification. Each independent verification attempt is a separate immutable record
that binds the completed manifest semantic fingerprint, manifest byte hash, artifact hashes,
verifier policy/code, verdict, and audit timestamp; it is never listed inside the artifact set it
verifies. Activation references the accepted verifier record/hash separately.

Activation uniqueness uses the separate activation-set scope from `P5-D12`, not an invented
publication-selection capability or added market-set field. Changing a market policy, source
selection, model acceptance contract, or consumed upstream version creates a successor in the same
audience and cannot leave two competing “current” authorities under different fingerprints.

### 3.3 Selection capabilities versus element capabilities

Legacy `contracts/onboarding/publication-selection.schema.json` bytes remain closed. `P5-1` freezes
the versioned selection-v2 successor solely to make the existing identity-exclusion semantics
schema-enforced and storage-independent; it preserves the exact
`scope = {retailerId, tenantId, capability, environment}` and existing capability enum. Phase 5 may
write new records only as schema-valid v2 events. Under `P5-D24`, each selection's readiness block
must bind the operational persisted v2 readiness report—not Gate B's separate capability mask.
Relevant top-level selection claims are:

- `price_revenue` only when the source pin meets the v2 temporal/readiness evidence for origin-safe
  prices and demand-response evidence; that selection alone does not bypass the later strict model
  gate for a recommendation;
- `price_margin` only when accepted client-actual cost supports the primary margin capability; a
  generated-cost pin may be temporally ready yet remains a reason-coded
  `COST_NOT_CLIENT_ACTUAL` non-claim rather than an active selection;
- `competitor_aware_forecasting` only when the source pin meets the v2 origin-visible match/price/
  availability evidence, not merely because the monitor page renders descriptive observations;
- `promotion_aware_forecasting` only after `P5-D23` and when the source pin meets the v2 origin-
  visible historical-and-future-plan evidence; numeric outputs additionally require the later
  frozen model gates;
- upstream `demand_forecast_non_pit`, retained unless `point_in_time_forecasting` is independently
  earned.

`P5-D24` is prospective. Existing Gate-B-bound selection JSON remains immutable historical
evidence and is verified under its original contract. A new v2 report fingerprint changes semantic
selection identity and therefore creates a new candidate/approved/active chain with an explicit
supersession; no historical readiness block is edited. A sparse `price_revenue` candidate whose
sufficiency is `insufficient_evidence` is rejected or no lifecycle is created; it is never approved
or active and cannot bypass sufficiency through `require_sufficient = false`.

Do not write `pricing_revenue`, `pricing_client_margin`, `phase5_pricing_intelligence`, or a page
name into `scope.capability`. Do not add market set or bundle identity to selection scope. Any new
selection capability requires an explicit schema/Decision-#72 amendment before generation.

Within a selected bundle, UI/API elements may still carry narrower independently reason-coded
element keys. These are explicitly **not** selection capabilities:

| Element capability key | Required top-level claim/evidence | Independent unavailable examples |
|---|---|---|
| `revenue_recommendation` | active `price_revenue`; accepted beta/P50, current price, local rule | insufficient response, stale price, missing policy, missing forecast |
| `client_margin` | active `price_revenue` and `price_margin`; client-actual accepted same-currency cost-as-of | cost missing/stale/synthetic/cross-currency/non-positive |
| `synthetic_margin_scenario` | derived element only; revenue inputs plus explicitly generated/demo same-currency cost-as-of | generated cost missing/stale/cross-currency/non-positive; never authorizes `price_margin` or a primary output |
| `price_simulation` | derived element only; active `price_revenue`, accepted beta, valid local candidate; margin optional | off-grid, out of range, max-change, insufficient response |
| `competitor_monitor` | descriptive element; an active forecast capability is claimed only if its stricter semantics pass | unmatched, review, rejected, stale, illegal source |
| `promotion_planner` | descriptive/derived element; `promotion_aware_forecasting` only after `P5-D23` and v2 source-evidence gates; numeric elements also require model gates | backfilled plan, missing lifecycle/mechanic, conflict, insufficient uplift, privacy-blocked result |

Element capability is never one bundle-wide boolean that hides mixed market, department,
SKU/store/channel, cost, match, or privacy states. Each assessed scope carries four independent
axes:

- `capabilityReadiness`: `ready | validated_partial | unavailable | blocked`;
- `capabilitySufficiency`: `sufficient | insufficient_evidence | not_evaluated`;
- nullable `modelGateStatus`: `accepted | rejected | not_applicable`, which is null before a model
  gate is applicable or run;
- `businessCapability`: `available | partial | unavailable`.

The first two vocabularies are the exact governing temporal-evidence and publication-selection
contract; do not add `stale`, `error`, gate outcomes, or aliases to either enum. Freshness and
serving failures use typed reason/transport state, while model acceptance stays in
`modelGateStatus`. For example, the current price rows are readiness-unavailable/sufficiency-not-
evaluated/model-gate-null/business-unavailable with `PRICE_AVAILABILITY_BACKFILLED`. The native
sparse profile is readiness-ready/sufficiency-insufficient/model-gate-null/business-unavailable.
API/UI may derive a concise display state only from this contracted tuple plus serving/freshness
state; it may not collapse or rewrite the axes in stored evidence.

### 3.4 Point-in-time price panel

The panel grain is tenant × retailer × market × store × channel × SKU × local week. Construction
must freeze:

- the decision origin and local calendar/week boundary;
- what counts as an observed price versus a carried price;
- point-in-time as-of lookup using `known_as_of <= origin` and business-effective applicability;
- maximum carry-forward age and explicit stale/gap states;
- gross/net/tax/discount semantics and promotion-price interaction;
- unit-of-measure and pack normalization;
- duplicate/conflicting price resolution;
- returns/cancellations and zero-demand exposure treatment;
- eligible sales exposure and stock-availability controls;
- event/promotion controls admitted at each origin;
- price-level tolerance after local grid normalization;
- transition counting that excludes data corrections and duplicate loads;
- observed-week coverage denominator and reason hierarchy.

Future-known rows and current-publication landing backfills are excluded. A sparse panel still emits
an assessed-series record with its first failing reason.

### 3.5 Elasticity model and shrinkage

The frozen model is a Poisson generalized linear model with log link. Its price coefficient is the
observational elasticity beta. Explanatory terms include log price, approved trend/seasonality, and
only origin-visible event/promotion controls. Exposure/offset semantics and zero-unit weeks must be
frozen in golden vectors.

No market shares raw price levels with another market. Within each market, eligible products are
assigned to pre-result price tiers using a frozen local-currency definition. SKU × store × channel
series are shrunk toward their department × price-tier cluster using the DerSimonian–Laird
empirical-Bayes rule. Sparse individual evidence may borrow only within that local pool; it cannot
borrow across market/currency or bypass minimum panel eligibility. Channel remains in every fitted
and served identity.

Uncertainty is estimated from 200 seeded price-episode block resamples. Episodes, blocks, seed
derivation, valid-draw definition, percentile/IQR method, and sign-consistency denominator are
contracted. The Phase 5 application of Decision #74 is an explicit extension that requires
`P5-1P` approval before results: predeclare exactly 13 chronological price-scoring origins, their
calendar spacing, training window, market alignment, and eligibility rule; use origins 1–8 for
development, freeze exactly one candidate, and evaluate origins 9–13 once as untouched
confirmation. If fewer than 13 eligible origins exist, evidence is insufficient. If more exist,
the deterministic rule selecting the 13 and excluding all others is frozen before inspection;
excluded origins cannot influence candidate choice and may be used only for separately labelled
post-acceptance diagnostics. Preregister candidate families and cap search at twenty
configurations. Tier boundaries, EB settings, control encodings, and regularization choices count
against that budget. The baseline is frozen before execution as the same exposure, seasonality,
trend, and event structure without the log-price response term (or a separately approved
alternative). Holdout improvement compares against that baseline. Training, resamples,
development origins, and confirmation origins may not overlap improperly.

### 3.6 Strict acceptance

Acceptance is independently recomputed, never trusted from a stored `accepted` flag. For each
SKU × store × channel series, verify negative beta, magnitude, sign consistency, IQR ratio, valid
draws, and positive holdout improvement. For each enabled department in each market, report channel-
level coverage and verify assessed count, accepted count, accepted coverage of at least 5%, and at
least 25 distinct actually gated SKU × store pairs with at least one contract-qualified channel;
channels cannot be double-counted to meet 25. Configured SKU/store counts are not proof.

Markets/departments that fail remain published as reason-coded evidence but cannot generate live
recommendations. A response-rich bundle may enable only passing scopes. The sparse bundle must be
accepted specifically for correct refusal behavior, not for recommendations.

### 3.7 Candidate price generation and decision ordering

Candidate prices come from the resolved local market/currency policy. Recommended ordering:

1. verify source, forecast, elasticity, scope, and freshness capability; the carried forecast may
   support a current decision only under its `demand_forecast_non_pit` /
   `LANDING_BACKFILL_DEPENDENCY` disclosure;
2. resolve current price and allowed local floor/ceiling/grid/endings;
3. enumerate deterministic candidates within observed support, the dominance-scaled maximum, and
   the absolute 5% per-cycle cap;
4. require the `P5-D10` origin-visible pricing-protection feed and apply its promotion overlap/
   conflict plus product protection, minimum/maximum price, and evidence constraints; D23-negative
   Planner refusal is not evidence that no active/planned promotion overlaps;
5. project units as `p50_units * (candidate_price / current_price) ^ beta`;
6. compute local revenue as candidate price × projected units;
7. only if accepted client-actual cost exists, compute primary local margin and apply the primary
   margin floor; generated PoC cost cannot change the primary candidate set, rank, guardrail
   result, or recommended price;
8. rank the configured objective with frozen dominance and tie-break rules;
9. round only at the contracted boundary and revalidate the rounded candidate;
10. label increase/decrease only when a distinct candidate is legal **and** beats current under the
    frozen objective/dominance/tie-break rule; otherwise label Hold and retain every rejected/non-
    dominating candidate reason.

The original HTML includes sample decreases larger than the 5% contract. Those samples must not be
used as data or golden recommendations.

### 3.8 Cost-as-of and margin

WAC is the implemented default method. FIFO is permitted only if Phase 5 implements genuine
receipt/batch-layer issue depletion with accepted quantity, batch, expiry, transfer, and as-of
lineage and independent golden reconciliation. A carried source `method = FIFO` label is not a FIFO
calculation; until that implementation passes, FIFO margin is unavailable. Cost is looked up as of
the pricing decision origin and must be positive, local-currency, source-qualified, and provenance-
compatible with the SKU/store/channel scope. Taxes, landed-cost components, transfers, and unit
conversions are frozen before calculation.

For a candidate with valid cost inside the capability that owns that cost class:

- gross margin value = `(candidate_price - unit_cost_as_of) * projected_units`;
- gross margin percent = `(candidate_price - unit_cost_as_of) / candidate_price`;
- margin impact compares candidate and current scenarios using the same origin and contracted unit
  forecast assumptions.

When client-actual cost is unavailable, the primary recommendation/API returns null plus reason and
the UI preserves every primary margin field in place as unavailable. Current generated WAC can
populate only the separately identified and visibly labelled `synthetic_margin_scenario`
capability. That scenario cannot change primary revenue recommendations, AI Price, Revenue
Opportunity, Margin Opportunity, margin guardrails, or promotion KPIs/tables/charts. Client margin
remains unavailable until client-actual provenance passes. Missing margin never becomes zero, and
synthetic/client-actual populations never aggregate under one margin label.

### 3.9 Stateless price simulation

Phase 5 supports a non-persisting calculation over an accepted SKU/store/channel context. Go may calculate
closed-form projections from stored beta, P50/P90, price, policy, and cost fields; it may not refit
or run arbitrary model code. The response includes input echo, local policy resolution, validation,
current/proposed/recommended scenarios, assumptions, uncertainty, source/run lineage, and
element-level capability.

No simulation is saved, approved, scheduled, or applied. Phase 7 may later add richer interactive
workflows without changing Phase 5's mathematical contract.

### 3.10 Competitor intelligence

Competitor matching is effective-dated and auditable. Each match retains both identities, method,
compared attributes, score components, confidence, status, reviewer provenance where applicable,
observed time, known-as-of, and source legality. Auto-accepted, needs-review, rejected, and no-match
thresholds are frozen before results.

`P5-1P` also freezes a matching evaluation contract: disjoint development/evaluation truth sets;
minimum evaluated positives/negatives per market/category; precision, recall, false-match, and
calibration gates; exact threshold-boundary treatment; confidence-bin reliability; attribute-
missingness cohorts; and first-failure reasons. Generator `competitor_match_truth` is test-only: it
may score the matcher but may never be copied into served match evidence.

Price comparison requires matching currency/unit normalization and freshness. Recommended response
is bounded by local price policy, accepted elasticity, inventory context, margin capability, match
confidence, and competitor availability. An out-of-stock competitor or large gap is context, not
permission to exceed guards. Low-confidence/review/rejected/stale matches are visible but cannot
drive the pricing engine.

### 3.11 Promotion planning

Decision #53 currently blocks a promotion feature on the accepted pin. Until `P5-D23` is formally
approved, the original Forecast promotion row and every Phase 5 result-bearing promotion surface
remain `NO_ORIGIN_VISIBLE_PROMOTION_PLAN`; a new source pin alone does not amend the decision.

Promotion applicability preserves AND within one scope row and OR across rows. Market-qualified
geography is mandatory. Merchandise overlap resolves `sku > department > category`; conflicting
equal-precedence discounts refuse rather than selecting arbitrarily.

Source contracts keep three different concepts separate: source campaign class; source-native
promotion lifecycle status (`Draft | Under Review | Approved | Live | Completed` when actually
provided); and offer mechanic (`Percentage Discount | Fixed Price | Clearance` for permitted
Phase 5 mechanics). The current `historical | active` status and
`campaign | clearance | fire-sale | runout-markdown` type vocabularies cannot be silently converted
to those UI fields. Missing lifecycle/mechanic remains reason-coded unavailable.

Only on `decisionDisposition = amended`, permitted Phase 5 outputs include:

- baseline and promoted unit/revenue projections from accepted origin-visible evidence;
- promotion depth/duration/scenario comparisons within policy;
- overlap and conflict detection;
- Phase 4 inventory readiness: fully available, transfer required, replenishment required, or
  insufficient/at risk;
- descriptive aggregate audience counts/mix without customer identity; these do not authorize a
  segment-specific response, offer, recommendation, or simulation;
- client-actual-cost-conditional local margin for primary outputs, plus an isolated visibly
  labelled synthetic-margin scenario that cannot alter them;
- reason-coded insufficient evidence.

Cannibalisation, basket affinity, bundle optimization, segment-specific response/offers, and
customer targeting remain present as unavailable UI elements under Decision #19. The page copy
must not claim that those outputs are live.

Promotion “uplift” is also observational. Before any numeric result, `P5-1P` must freeze one model
family and acceptance protocol. Recommended binding: SKU × store × channel × week Poisson panel
model with an accepted baseline-forecast offset, price, seasonality, trend, event, stock-availability,
and admissible competitor controls; explicit promotion-active/depth/mechanic terms; treatment
episodes and eligible non-promotion comparison windows constructed point-in-time; minimum treated
episodes, pre-period support, mechanic/depth variation, and control support; episode-block
uncertainty; the Decision-#74 development/final-confirmation split; and positive untouched-holdout
deviance improvement over the same model without promotion terms. Confounded, unsupported, or
non-improving scopes return `insufficient_evidence`/`rejected`. If reviewers do not approve the
estimator, thresholds, uncertainty, and holdout contract before generation, numeric promotion
uplift/revenue/margin/stock KPIs, charts, tables, opportunities, and simulations stay unavailable;
only amended-branch descriptive calendar/scope/conflict/audience and independently sourced
readiness may ship; not-amended still returns the Decision-#53 refusal and exposes none of those
Planner facts.

### 3.12 Publication and serving boundary

Python owns model fitting, model-backed scoring, bundle creation, and independent verification.
The verifier recomputes identities, gates, row counts, hashes, formulas, constraints, lineage, and
capability truth tables, including every `P5-D24` readiness input/report/selection binding rather
than trusting producer booleans. PostgreSQL materialization is transactional and does not activate.
Rich result-selection v2 events plus the activation-set are a later atomic PostgreSQL insert after
database/API reconciliation; any JSON receipt is generated only after commit.

Go validates exactly one active Phase 5 activation-set for the reviewed local audience plus its exact
active capability selections and reads PostgreSQL only. Stale
authority returns governed 409 with reason/remediation; missing/corrupt/incompatible authority
returns governed 503. A partial element remains HTTP 200 when the page authority is valid and the
contract defines element-level unavailability.

---

## 4 · Decisions, proposed decisions, and implementation bindings

Every recommended decision below must be accepted or replaced before the package that consumes it.
Implementation and observed results are not allowed to decide policy retrospectively.

### P5-D0 · Phase 4 entry authority and carryovers — proposed binding

Do not adopt any conflicting identity listed in §1.2 from plan text. `P5-0` must establish source
selection from the committed Decision-#73 JSON ledger, reconcile its `selectionId` to each database
materialization's `source_selection_id`, and establish forecast/inventory authority from the actual
PostgreSQL activation chains; no selection table is assumed to exist. It then verifies artifact,
database, API, OpenAPI, and UI lineage and retained bytes. Preserve current-snapshot
inventory outputs, both replay refusal reasons, non-PIT forecast disclosure, and replay-dependent
benefit unavailability. The new Phase 5 source identity requires ordered feature rebuild/
successor-input preparation, forecast rebuild/successor-input preparation, and inventory rebuild/
successor-input preparation followed by verified selection and separate activation; arbitrary mixing, equivalence
shortcuts, and in-place valuation correction are forbidden. `P5-0` is evidence-only.

### P5-D1 · Native availability and point-in-time semantics — proposed binding

Price, promotion, cost, competitor, and event inputs require source-native observed/posted/
extracted availability or a separately approved, conservative evidence class. Business-effective
dates never prove availability. Landing-time backfills remain unavailable for historical model
origins and retain their original reason code; they are not “fixed” by changing metadata in place.

### P5-D2 · Capability split and reason hierarchy — proposed binding

Use only the closed selection capabilities and lifecycle scope in §3.3, plus the separately named
six element keys and four independent element axes. Each narrowest relevant scope
returns `capabilityReadiness`, `capabilitySufficiency`, nullable `modelGateStatus`,
`businessCapability`, `reasonCode`, `reasonDetail`, `assessedAt`, `sourceKnownAsOf`, `validThrough`,
and remediation. Freeze a deterministic first-failure hierarchy so the same row cannot report
different reasons across artifacts, PostgreSQL, Go, and React. Never translate temporal-
unavailable into statistical-insufficient, or a stale/error serving condition into a readiness
enum value.

Minimum reason families include temporal evidence, insufficient observations/coverage/levels/
transitions, stale input, gate rejection, missing policy, missing forecast, missing cost, currency
mismatch, invalid competitor match, promotion conflict, privacy restricted, workflow unavailable,
stale authority, missing/corrupt authority, `LANDING_BACKFILL_DEPENDENCY`, non-PIT forecast
dependency, missing source-native promotion lifecycle/mechanic, Decision-#53 promotion refusal,
unproven readiness flag/report, Gate B/v2 contradiction, and `COST_NOT_CLIENT_ACTUAL`.

For D23-negative Forecast/Promotion Planner elements,
`NO_ORIGIN_VISIBLE_PROMOTION_PLAN` is the first-failure reason; Decision #19/privacy restrictions
remain secondary policy metadata and prohibited data stays absent. The separate pricing-safety
overlap guard uses `PROMOTION_PROTECTION_MISSING`/`PROMOTION_CONFLICT` and is never downgraded to the
Planner refusal reason.

Freeze first-failure precedence **per element family**, applying the first matching condition in
that row rather than one page-global reason:

| Element family | First-failure precedence |
|---|---|
| Price-recommendation promotion safety guard | missing/invalid safety-feed authority → `PROMOTION_PROTECTION_MISSING` → `PROMOTION_CONFLICT`; `P5-D23` is not consulted |
| Planner/Forecast feature presence on not-amended branch | `NO_ORIGIN_VISIBLE_PROMOTION_PLAN`; privacy/workflow restrictions are secondary metadata only and no internal safety-guard fact is exposed |
| Amended descriptive lifecycle/mechanic/scope/calendar/audience | temporal/source absence → missing source-native field → invalid scope/equal-precedence conflict → element-specific evidence/suppression reason |
| Amended numeric KPI/chart/opportunity | temporal/source absence → scope/conflict → readiness/sufficiency → `P5-D20` not-evaluated/insufficient/rejected → inventory requirement, where applicable → client-cost reason for primary-margin elements |
| Amended simulation control/result | temporal/source absence → scope/conflict → readiness/sufficiency → `P5-D20` model gate → `P5-D22` valid-draw/confidence gate → inventory requirement → client-cost reason for the primary-margin field |
| Privacy-deferred element | not-amended branch uses `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` first; amended branch uses `privacy_restricted` and emits no numeric/source proxy |
| Workflow/mutation element | not-amended branch uses `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` first with workflow secondary; amended branch uses `workflow_unavailable` and has no handler |

`P5-7A` verifies only safety/foundation/temporal/scope reasons knowable before recommendations.
`P5-7B` resolves model, simulation, inventory, cost, privacy, and workflow reasons after their
evidence exists; the final verifier recomputes the complete precedence row.

### P5-D3 · Price-panel eligibility and strict gates — proposed binding

Adopt the eligibility and acceptance values in §§3.4–3.6. The 0.80 resample-IQR maximum remains
strict. Department enablement requires both 5% accepted coverage and at least 25 actually gated
distinct SKU × store pairs independently in India and the US, with response fitting and
recommendations remaining SKU × store × channel and no double-counting channels. Apply
the approved Phase 5 extension of Decision #74: exactly 13 predeclared chronological scoring
origins with frozen spacing/window/market-alignment and selection rules, origins 1–8 for
development, maximum twenty preregistered configurations, one frozen candidate, and origins 9–13
for untouched confirmation. Fewer than 13 is insufficient; when more are eligible, the pre-result
rule selects 13 and excluded origins cannot affect candidate choice. Baseline/control/tier/EB
candidates are frozen in `P5-1P`. Any exception must be proposed before model results and version
the guardrail contract.

### P5-D4 · Market-local tiers, pools, and currency isolation — proposed binding

Construct tiers and shrinkage pools separately by market using local-currency prices and frozen
pre-result tier boundaries. No cross-market nominal price comparison or pooled beta prior is
allowed. Dimensionless policy defaults may be shared only where the resolved policy explicitly
permits it.

### P5-D5 · Revenue objective, candidate set, and guardrail order — proposed binding

Phase 5's default objective is revenue. Enumerate market-local candidates, enforce evidence and
hard rules, project demand/revenue, optionally enforce client-actual cost-capable margin, then apply
the frozen confidence-scaled maximum action cap, absolute 5% cap, observed-support clamp,
dominance, rounding/revalidation, and tie-breaks in the approved order. `minActionCapPct = 2` is the
lower endpoint of the maximum cap at dominance 0.70, not a minimum movement threshold; freeze the
exact interpolation to 5% at dominance 1.0 and every clamp/round boundary before results. Generated
PoC cost never changes the primary candidate, guardrail, rank, or recommendation; it is evaluated
only in the separate synthetic scenario. Hold is a valid dominance/no-better-legal-candidate
result. Do not invent a below-2%-means-Hold rule without a separately approved policy version.

### P5-D6 · Cost-as-of and synthetic-margin presentation — proposed binding

Use computed WAC by default. FIFO remains unavailable until genuine receipt/batch-layer depletion
is implemented and independently verified; a method label is insufficient. Real/client margin
requires client-actual, positive, provenance-matched, same-currency cost available at the origin.
The current generated cost may populate only an explicitly labelled `synthetic margin scenario`
under the derived `synthetic_margin_scenario` element key and must be separable by endpoint/field,
provenance discriminator, and the exact Price Simulation UI location in §8.3.2. It cannot populate
or alter the primary recommendation, recommended price,
revenue/margin KPIs, guardrails, rank, promotion portfolio metrics, or promotion charts. Mixed
client-actual/synthetic aggregates are forbidden; when both are shown, they remain separately
labelled assessed and available populations. Generated cost never authorizes an active
`price_margin` selection. If `P5-D24` reports the temporal cost evidence ready for generated cost,
the selection/claim layer records `COST_NOT_CLIENT_ACTUAL`; it does not falsify the data-readiness
verdict to enforce this business boundary.

### P5-D7 · Price Simulation phase boundary — proposed binding

Enable stateless, non-mutating simulation in Phase 5 using stored accepted model outputs and
closed-form rules. Its POST endpoint is not called a read endpoint: it is body-bounded, idempotent
for identical authority/input, and proven to write no database/domain state. Do not save, approve,
compare persisted drafts, schedule, publish, or execute. The original form and result locations
remain; unavailable inputs are disabled individually rather than removing the form.

### P5-D8 · Competitor source and match identity — proposed binding

Permit engagement claims only from approved client/licensed landed extracts or APIs. Local
generated evidence uses canonical `evidence_class = synthetic`, preserves its separate
`derivation_class` and source system/instance, and displays `Synthetic demo` only from an explicit
use-purpose/disclosure field. Scraping/web collection is not implemented. Match identity and
evidence follow §3.10 and matching must pass the pre-result
evaluation/calibration protocol in `P5-1P`. Test-only generator truth may score but never populate
served evidence. Low-confidence/review/rejected/no-match records remain visible for transparency
but are excluded from recommendation inputs.

### P5-D9 · Competitor response — proposed binding

Treat competitor price, availability, promotion, and freshness as bounded context. Never copy a
competitor price automatically. The candidate still must pass local evidence, response, price,
margin, inventory, protection, and promotion guards. “Recommended Response” must expose why a
competitor fact was included, excluded, or withheld.

### P5-D10 · Promotion applicability and conflict — proposed binding

Adopt AND/OR and merchandise precedence from §3.11. Equal-precedence conflicting discounts, invalid
scope combinations, currency mismatches, and overlapping protected-product rules fail closed and
surface a stable conflict record. Independently of `P5-D23`, every actionable price recommendation
requires an origin-visible, minimal **pricing-promotion protection** feed containing only active/
planned protected windows, applicable merchandise/location/channel scope, known/effective time,
and conflict terms. It authorizes no uplift, Planner/Forecast promotion feature, lifecycle/mechanic
display, audience, calendar, or numeric promotion claim. If that safety feed is missing/ambiguous,
all affected actionable price rows are withheld with `PROMOTION_PROTECTION_MISSING`; it is not safe
to treat the D23-negative Planner refusal as proof of no conflict.

### P5-D11 · Promotion privacy disposition — proposed binding

Keep Decision #19 closed for Phase 5. Implement descriptive aggregate segment counts/mix only.
On an amended promotion branch, render cannibalisation, bundle affinity/optimization, segment-
specific response, segment offer selection, and customer targeting as `privacy_restricted`. On a
not-amended branch, the Planner refusal remains first and privacy is secondary metadata. Descriptive aggregate mix cannot become
a targeting or response capability. Reopening requires a separate approved decision, privacy
review, source contract, estimator, acceptance rules, minimization/retention policy, and updated
parity rows before implementation.

### P5-D12 · Bundle, materialization, activation, and local serving scope — proposed binding

Publish one immutable Phase 5 bundle per rich/sparse source, upstream, model, and policy lineage.
Each manifest must carry its market/currency scope, source and upstream identities, model/policy/code
fingerprints, result artifacts, explicit unavailable rows, prospective result-selection IDs, and
acceptance evidence. Rich and sparse bundles have separate manifests and outside-set verifier
records; neither verifier attests the other.

Materialization and activation are different operations:

1. independently verify the closed bundle and recompute its referenced identities;
2. materialize that bundle in one PostgreSQL transaction, with rollback on any count, checksum,
   schema, foreign-key, or invariant failure;
3. confirm the materialized rows are queryable but not active;
4. in one separate PostgreSQL activation transaction, insert the verified rich Phase 5 result-
   selection v2 candidate, approved, and active events into the append-only result-selection ledger
   and insert one activation-set event referencing their exact active selection IDs;
5. resolve reads only from that explicit activation-set.

The existing file-backed source-selection ledger remains the batch input authority used by `P5-2`
before pin generation; it is not written during result activation and is not part of the atomicity
claim. Phase 5 introduces a versioned, storage-independent selection v2 contract plus a PostgreSQL
`result_selection_events` table for Phase 5 result capabilities. Each row stores the canonical,
schema-valid immutable event bytes/hash, full scope, stable selection ID, lifecycle record ID,
predecessor, reviewer evidence, and transaction ID. The activation-set table is the sole local
runtime authority. A serializable transaction or equivalent locked scope plus database uniqueness
constraints inserts every result lifecycle event and the activation-set together; any insert,
constraint, or verification failure rolls back all of them and leaves the prior current set intact.

After commit, an idempotent exporter may write a checked evidence receipt containing the transaction
ID, event IDs/hashes, activation-set ID/hash, and database reconciliation. That JSON receipt is a
derived review artifact only: it is never read to select serving, is never described as atomically
written with PostgreSQL, and can be regenerated byte-for-byte from the immutable database events.
This explicitly preserves legacy `publication-selection/v1` bytes while new Phase 5 selections use
the v2 identity contract; it does not invent a capability.

The activation-set event records retailer, tenant, environment, bundle ID/hash, exact active
selections, claimed/unavailable capabilities, predecessor event when one exists, author/reviewer
evidence, and timestamps. At most one activation-set may be current for a retailer × tenant ×
environment audience, and a successor must explicitly supersede its current predecessor.

The normal local-demo audience activates only the accepted response-rich bundle. That rich bundle
must include naturally sparse series/departments so insufficient-evidence, unavailable-margin, and
other element-level refusal states are demoable without changing audiences. The separately verified
sparse bundle is retained as non-active reproducibility and isolated API-integration evidence; it
must not create an active `price_revenue` selection or a second public live server.

The Go server receives one schema-valid, reviewed, secret-free local configuration binding
`retailerId`, `tenantId`, `environment`, `activationSetId`, expected bundle ID/hash, logical database
target, and `postgresDsnEnv = RETAIL_POSTGRES_DSN`. The retained configuration carries its canonical
fingerprint but no DSN, password, host credential, or token; PostgreSQL credentials are supplied only
through that environment variable/secret boundary and never enter evidence, logs, errors, or
screenshots. Startup validates configuration fingerprint, database identity, activation scope,
selection membership, and bundle hash before listening. Browser labels, query parameters, route
state, or display filters never choose a different authority. The server exposes only PostgreSQL-
backed read endpoints plus bounded, non-mutating stateless calculation endpoints; it never reads
MLflow or model files at request time.

Phase 5 does not define an OCI archive, API/UI container, trusted deployment startup record, process
drain, cutover dossier/authorization/receipt, post-cutover serving authorization, registry push,
database portability dump, or cross-host restore. Those are Phase 6–8 release-hardening concerns
and require their own plan, security review, and governing-authority amendment.

### P5-D13 · Read-only action behavior — proposed binding

In Phase 5, every control has exactly one matrix state: `business_live`, `read_only`, `preview_only`,
`hard_disabled`, or an explicitly rejected duplicate `structural_only`. Safe navigation, filtering,
sorting, local row selection, read-only detail, stateless simulation, and lineage-bearing export may
be `business_live` or `read_only`. Mutation controls retain their original placement as `hard_disabled`
with a business prerequisite, no click handler, and no mutation endpoint, except an explicitly
approved presentation-only `preview_only` surrogate described below; every actual submit remains
disabled. A preview trigger is intentionally clickable but is never classified as `business_live`. A
toast after clicking an enabled-looking disabled action is not acceptable. To make every
mandatory original modal inspectable for the client, approve a **preview-only** presentation
amendment for each §8.8 surface whose original trigger would otherwise be disabled. The original
trigger label remains first and is explicitly labelled/described `Preview only`; it opens a non-
submitting dialog, makes text/date inputs read-only, permits enumerated controls only to explore
local preview states, keeps prohibited options individually disabled, disables every submit/
mutation action, and performs no network, write, history, or audit operation. The trigger is a
presentation preview, never an enabled mutation. Every mandatory §8.8 modal must be reachable as
`business_live`, `read_only`, or `preview_only`; `hard_disabled` is permitted only where the surface
does not have a mandatory inspectable modal, and `structural_only` is permitted only for an
explicitly rejected duplicate/non-authoritative implementation artifact that is not a distinct
reference surface. If a
reference submit normally opens a result dialog, the original submit remains disabled on an
unavailable preview branch. A separately approved secondary `Preview Results` control may appear
immediately after that disabled primary and before Cancel; it performs only an in-memory dialog-state
replacement, carries its own preview badge/description, and renders the exact result composition with
typed unavailable values. It never reuses the original submit as an enabled-looking preview action.

### P5-D14 · Screen matrices and amendment policy — proposed binding

Create four versioned parity/data matrices for Price Recommendations, Price Simulation, Competitor
Monitor, and Promotion Planner. Create one whole-demo remediation register and versioned amendments
to Data Management, Demand Forecast, and inventory/replenishment matrices for approved corrections.
Every visible or modal-only element gets one row. No page endpoint or component work starts first.

### P5-D15 · Required client-demo state coverage — proposed binding

Freeze a deterministic demo-coverage contract in `P5-1P` before generation. The response-rich
profile creates the applicable **data/model/business** states in §9, including the page-specific
existing-destination matrix and naturally sparse cohorts with governed insufficient-evidence
states. The full sparse profile supplies non-active reproducibility and API-integration evidence.
Stale 409, missing/corrupt 503, and panel failure are operational states and cannot be manufactured
inside the accepted rich publication. Prove them through separately versioned non-mutating API
adapters and live UI evidence. Coverage is never satisfied by hidden client toggles or corrupting
the accepted audience.

### P5-D16 · Staleness, scope, and reporting display — proposed binding

Freeze source-, model-, price-, competitor-, cost-, forecast-, inventory-, and aggregate-FX
freshness independently. Global controls use canonical IDs, not labels, and affect every dependent
element. Local operating-price fields never change under the reporting-currency selector; only
approved aggregate reporting values do, with FX rate, as-of, source, rounding, and “reporting
currency” disclosure. Freeze a per-destination Store/Channel applicability matrix; location-grain
Inventory pages disable and label Channel unless an approved channel allocation exists, while the
few channel-grain projections may opt in with exact query evidence.

The reference retains all five reporting-currency options in order: INR, USD, EUR, GBP, AED. For
each option, freeze either complete governed cross-rate/source/as-of/direction/rounding coverage for
every exposed aggregate or an exact disabled/unavailable selector and modal row with reason. The
two-market INR/USD source is not evidence for EUR/GBP/AED. Pulling read-only reporting conversion
into Phase 5 is an explicit reviewed amendment to the Phase-6 task boundary; it never pulls forward
serve-time pricing-rule or workflow work.

### P5-D17 · Existing-page integration — proposed binding

Phase 5 may enable an existing unavailable element only when the new output exactly satisfies that
element's frozen definition. Accepted candidates include Forecast Scenario Planning, origin-safe
promotion panels, projected inventory demand-at-risk, source-specific freshness, read-only
validation detail, and cost/policy-backed inventory markdown/NRV. Nearby metrics, partial lineage,
or attractive substitutes do not qualify.

### P5-D18 · Promotion Performance Forecast chart semantics — proposed binding

The Promotion Performance Forecast HTML pairs bars named Baseline, Optimized, Current Plan, and Best
Case with axis labels Revenue, Demand, Margin, and Sell-through, which is semantically ambiguous.
Adopt four scenario bars measured on one preregistered normalized portfolio-outcome index with
Baseline fixed at 100. Preserve the visible bar order and inside labels Baseline, Optimized, Current
Plan, Best Case. Through the `P5-0P` parity clarification, replace the misleading four independent
bottom labels with one centered axis caption, `Normalized portfolio outcome index (Baseline = 100)`.
Place an accessible table directly with the chart containing Scenario, Revenue, Demand, Margin, and
Sell-through, their native units, exact values, availability reasons, and the normalized index.

`P5-1P` freezes the component definitions, direction, normalization, weights, missing-value/refusal
behavior, rounding, and index bounds before profile generation or result inspection. A scenario bar
is drawn only when all required components and the applicable promotion branch pass; otherwise the
bar position remains with a reason-coded unavailable treatment and the table preserves the component
facts. The original hard-coded heights are never used as values or targets. Any metric-group
alternative requires a later approved parity amendment; it is not a Phase 5 implementation choice.

### P5-D19 · Original product terminology — proposed binding

Preserve exact client-facing terminology required by the original HTML, including labels such as
“AI Price” and “AI Reason,” unless product owners approve a naming amendment. Internal phase names,
roadmap explanations, implementation package names, and authorship metadata never appear in the
business UI.

### P5-D20 · Promotion-uplift estimator and acceptance — proposed binding

Freeze and approve the observational Poisson panel protocol in §3.11 during `P5-1P` as a joint
prerequisite to the `P5-D23` amendment, but do not execute it or produce result-bearing output until
that amendment passes. Freeze treatment episode construction, comparison support, controls/confounder
exclusions, minimum episodes/pre-period/variation, episode-block uncertainty, baseline, and
positive untouched-holdout improvement before generation. Its Decision-#74 extension must either
reuse the exact approved 13 price origins with proven calendar compatibility or predeclare a
separate 13-origin promotion registry with the same 1–8 development/9–13 untouched, ≤20-candidate,
fewer-than-13 refusal, and surplus-origin exclusion rules before results. If any part remains
unapproved or fails,
every model-derived numeric promotion demand/revenue/margin/stock KPI, chart, table cell, opportunity
value, and simulation result is unavailable, and Run Simulation is disabled. Descriptive plan,
scope, conflict, audience, calendar, and independently sourced stock-requirement/readiness evidence
may remain live. Simulation additionally requires the independent confidence contract in
`P5-D22`; price-response confidence is not a substitute.

### P5-D21 · Confidence, priority, risk, and driver mapping — proposed binding

Use the reusable M5 resample sign-consistency definition as the displayed numeric response
confidence: `100 * P(shrunk beta < 0)`, using valid contracted draws and no rounding before filter
comparison. Never use the larger of the negative- and positive-sign probabilities because a stable
positive-price coefficient must fail, not appear highly confident. The original filter predicates
are exact and overlapping: `>=90%`, cumulative `>=80%`, and `<80%`. For reporting/demo cohorts,
split them as `>=90%`, `>=80% and <90%`, and `<80%`; this cohort split does not change the cumulative
`80% and above` control. Only rows at `>=90%` can pass the confidence gate, and they remain
actionable only when every other gate passes. Lower cohorts remain visible as withheld/manual-
review evidence and cannot carry an actionable price. Because displayed Confidence is the same
statistic as the hard sign-consistency gate, every `recordKind = recommendation` is necessarily
`>=90%`. This deliberate consequence is contracted, not treated as surprising demo behavior:

- `90% and above` may show recommendations plus high-confidence withheld assessments;
- cumulative `80% and above` adds 80–<90 withheld assessments;
- `Below 80%` contains withheld assessments only;
- Recommendation Mix Increase/Reduce/Hold rows are necessarily all high-confidence;
- Pricing Decision Quality `High confidence` uses **all filtered assessed workbench rows** as its
  denominator, so it can truthfully show less than 100%; it is not a recommendation-only rate.

The workbench endpoint may include those non-actionable assessed rows only with
`recordKind = withheld_assessment`, `actionAvailable = false`, stable reason codes, and null Action,
AI Price, Change, Revenue Impact, Margin Impact, Current Margin, and Expected Margin where the
corresponding facts are not independently available. A withheld assessment is not a Hold
recommendation—or any other recommendation. It appears only under All Actions, contributes to the
exact Manual review row, and is excluded from Open Recommendations and the table's
`N recommendations`. The workbench API separately exposes total, recommendation, and withheld
counts. Because the table may visibly contain both record kinds, the `P5-3` Price Recommendations
matrix must approve an adjacent
`M manual review` count while retaining the original `N recommendations` token; without that
terminology amendment, withheld assessments cannot share the recommendation table.

Recommended priority mapping is market-local and pre-result: High for an actionable row at/above
the market × department 80th percentile of absolute revenue opportunity or with an accepted high
stock/markdown risk; Medium from the 50th to <80th percentile or with a non-hard risk flag; Low for
the remaining actionable/Hold rows. The recommendation-labelled `Recommendations at Risk` KPI may
count only recommendations carrying a frozen **non-blocking accepted warning**. A hard guardrail,
protection rule, promotion conflict, missing required input, or other blocking failure produces a
`withheld_assessment` and appears in Manual review and the separately labelled At Risk waterfall;
it can never be counted as a recommendation. If no non-blocking warning enum is approved, an exact
zero recommendation-risk KPI is expected and must render honestly. Driver attribution chooses the
greatest absolute normalized contribution among admitted demand, markdown, competitor, inventory-
clearance, and margin-protection components, with that listed order as the tie-break. `P5-1P`
freezes exact percentile population, blocking versus non-blocking risk enums, normalization, tie
boundaries, missing-component behavior, and golden vectors before profile generation.

### P5-D22 · Promotion simulation confidence — proposed binding

This binding is dormant unless `P5-D23` passes. Promotion Confidence is independent of price-
response confidence and competitor-match confidence.
For a selected promotion/scope/scenario, attempt exactly 200 seeded promotion-episode block
resamples using the frozen `P5-D20` estimator and calculate
`100 * count(valid draw incremental units > 0) / count(valid draws)` against the same no-promotion
baseline and origin. Require at least 50 valid draws. Use the unrounded value for the proposed High
`>=90%`, Medium `>=80% and <90%`, and Low `<80%` bands; display may round only afterward.

Numeric promotion simulation and its Confidence value are available only when the displayed scope
passes every `P5-D20` gate and promotion confidence is at least 90%. Lower-confidence assessments
may appear only as reason-coded model evidence, never as a numeric recommendation/result modal. If
the model is unapproved, the scope is ineligible, fewer than 50 draws are valid, or confidence is
below threshold, Confidence is null with a stable reason and Run Simulation remains disabled.
`P5-1P` freezes block construction, valid-draw rules, seed derivation, exact boundary behavior,
aggregation across multi-SKU scopes, rounding, and golden vectors before profile generation.
Persist the accepted draw parameters required for deterministic scenario projection; the Go
handler evaluates the bounded request over those stored draws and never refits a model.

### P5-D23 · Decision-#53 promotion-feature amendment gate — proposed binding

Decision #53 remains authoritative at plan approval. The current accepted pin and existing Demand
Forecast promotion row stay unavailable with `NO_ORIGIN_VISIBLE_PROMOTION_PLAN`. Before `P5-2`
generates a result-bearing promotion profile or `P5-7A/B` implements positive outputs, reviewers must
formally amend Decision #53 and approve all of the following together:

- new origin-safe promotion plans/history with source-native known/effective times;
- distinct source-native lifecycle status and offer-mechanic fields required by the UI;
- the `P5-D20` estimator/acceptance protocol and `P5-D22` simulation-confidence protocol;
- temporal policy/readiness, selection-capability, API, and Forecast/Promotion Planner matrix
  amendments.

If that amendment does not pass, Phase 5 may render only the exact governed unavailable Promotion
Planner/Forecast surfaces; no numeric promotion KPI, model, opportunity value, simulation, status/
mechanic proxy, or Forecast promotion integration is authorized. The separate `P5-D10` pricing-
protection feed/guard remains mandatory but is never displayed/claimed as the disabled feature. New
rows or a new pin alone do not reverse Decision #53.

Keep the policy decision separate from the later package outcome:

- `decisionDisposition = amended` means the formal amendment and the pre-result `P5-D20`/`P5-D22`,
  source-field, temporal, scope/privacy, API, and screen contracts were approved. It authorizes
  execution; it does not assert that a model or simulation will pass.
- `decisionDisposition = not_amended` means every Planner/Forecast lifecycle, mechanic, response/model, opportunity,
  portfolio, readiness, audience, calendar, numeric artifact and active
  `promotion_aware_forecasting` claim is absent. The pricing-protection guard artifact remains
  present and verified but is not exposed as feature evidence. All relevant Planner/Forecast
  endpoints/elements return first-failure `NO_ORIGIN_VISIBLE_PROMOTION_PLAN`, with Decision #19 as
  secondary policy metadata; simulation is disabled/no-call. Conditional Planner applicability,
  confidence, lifecycle/mechanic, audience-mix, and chart requirements are non-applicable.

After execution, `P5-7B` records exactly one separate `packageDisposition`:

- `positive_numeric`: `decisionDisposition = amended` and at least one `P5-D20` scope passes;
  `P5-D22` remains a per-simulation-element gate and may still disable individual/all simulations;
- `positive_descriptive_only`: `decisionDisposition = amended`, the frozen `P5-D20` assessment
  pipeline ran, no numeric scope passed, and rejection/not-evaluated primitives are retained; or
- `negative`: `decisionDisposition = not_amended`, with the absence/refusal contract above.

An unapproved `P5-D20` protocol is not a valid descriptive branch after amendment; it blocks the
amendment/package. A runtime/model refusal is evidence and never gets relabelled as an approval gap.

### P5-D24 · Operational readiness authority and margin non-claim — proposed binding

Adopt the persisted, canonically fingerprinted v2 readiness report in §1.8.2 as the sole source of
`capabilityReadiness` and `capabilitySufficiency` for a Phase 5 selection. Gate B remains required
validation/disclosure evidence and must reconcile, but its capability mask or semantic fingerprint
cannot be copied into the selection's readiness block. Every role, evidence flag, and sufficiency
value must come from the frozen evidence-producer registry; missing/unproven inputs remain reason-
coded partial/unavailable/not-evaluated and cannot be hard-coded to ready/sufficient.

Keep temporal data readiness separate from claim authorization. Generated PoC cost may satisfy the
existing `temporal_cost_ledger_matching_currency_scope` predicate, but `P5-D6` still blocks an
active `price_margin` selection and requires `COST_NOT_CLIENT_ACTUAL` non-claim evidence. If
reviewers instead want client-actual provenance inside the v2 flag definition, they must approve a
versioned temporal-policy amendment before profile generation; implementation may not silently
change the meaning.

### P5-D25 · Identity-safe source authority and full-scope pinning — proposed binding

Keep `contracts/ml/expected-pin.json` as the v1 byte authority consumed by existing feature,
forecast, and inventory jobs. Do not add Phase 5 result capabilities to that schema. Repair
`build_expected_pin.py` so every generate/check operation receives explicit run ID, pin path, input-
authority path, job purpose, evidence root, retailer, tenant, and environment; remove correctness
dependence on mutable module-level defaults. The current stale default breaks a direct `--check`, but
`tools/dev.py` already passes `--run run_id`, so the normal repin pipeline and phase-exit gate are not
presently broken by that default.

Preserve historical `retail-publication-selection/v1` bytes and freeze
`retail-publication-selection/v2` before creating a Phase 5 selection. V2 makes the canonical ordered
semantic-identity exclusion vector normative and schema-enforced:
`approval`, `selectionId`, `semanticIdentityExcludes`, `lifecycle`. A legacy v1 record with the field
absent is interpreted using those existing Python semantics; an explicitly conflicting vector fails
closed. Python, Go, database payload verification, builders, and golden vectors must compute the same
selection and lifecycle record IDs.

Every source or result lookup is keyed by the complete
`{retailerId, tenantId, capability, environment}` scope. Capability-only maps, newest-record wins,
implicit directory discovery, ambiguous matches, and browser-selected scope fail closed. A selection
transition declares either:

- `genesis`: no prior record and no current head exist for the full scope; or
- `successor`: exactly one current predecessor exists and is explicitly superseded.

Rich and sparse source publications first receive schema-valid Decision-#73 source selection
lifecycles for every capability required by the v1 pin. Rich uses the exact `local` scope and may
supersede the measured local predecessor. Sparse uses the exact `dev` diagnostic scope and must prove
genesis or one dev predecessor; it never displaces the local source authority. Only after those
selections are active in their respective source ledgers may the builder emit separate immutable v1
pin artifacts and reviewed `retail-input-authority/v1` records. Those records bind the exact entry
record, selection event IDs/hashes, run ID, evidence root, publication/readiness hashes, job purpose,
complete four-field scopes, and genesis/successor proof. The rich pin becomes the shared expected pin
through the ordinary reviewed repin workflow before its feature → forecast → inventory rebuild. The
sparse diagnostic pin remains explicit and never overwrites the shared default. Sparse source
selection being active in `dev` authorizes only its batch input pin; no sparse Phase 5 result
selection, activation-set, or public server becomes active.

Every feature, forecast, inventory run, verifier, publisher, and materializer receives explicit pin
and input-authority paths. The rich reviewed startup path may point explicitly at the shared pin;
sparse always points at its non-default artifacts. A hard-coded read of
`contracts/ml/expected-pin.json`, fallback from sparse to rich, or an authority/pin scope mismatch
fails before work begins. Neither a source selection, pin change, nor input-authority record activates
Phase 5 serving.

Resume keys include the first consuming identity at every stage: source bytes and availability,
readiness sidecar, config/preset, feature inputs, forecast/inventory upstream identities,
model/policy/foundation fingerprints, bundle manifest, materialization, and activation-set ID.
A change restarts at its first consumer; a readiness-sidecar-only correction must not rewrite the
base publication/pin, while a source-identity correction requires republish, reviewed repin, and the
full downstream rebuild. Partial-key reuse is prohibited.

Prospective result-selection IDs are computed from schema-validated v2 intents before bundle
closure. The independent bundle verifier recomputes those IDs, proves the primitive capability
evidence, and proves the records are not already active. Only after successful verification and
materialization does the separate PostgreSQL activation transaction insert the exact rich v2 result-
selection lifecycle events and one activation-set atomically. Any later JSON is a post-commit receipt,
not a second ledger. Sparse result evidence remains non-active. Phase 5 has no live-authority,
release-manifest, cutover, drain, or deployment serving-authorization artifact; local serving
resolves the explicit reviewed database activation-set described in `P5-D12`.

---

## 5 · Deliverables and traceability

### 5.1 Entry and source deliverables

- one immutable `phase5-entry-record.json` reconciling retained Phase 4 source, forecast,
  inventory, activation, API, database, expected-pin, and UI authority;
- an approved existing-UI audit/amendment register covering the shell, Data Management, Demand
  Forecast, and every inventory/replenishment destination;
- versioned source/availability contracts for sell price, promotion, competitor observations and
  matches, and cost, including native known-as-of semantics;
- one identity-safe v2 readiness sidecar and retention record for each rich/sparse source
  publication, without changing Gate B or the base publication identity;
- a versioned selection-v2 identity contract, legacy-v1 compatibility vectors, and schema-valid
  source-selection lifecycles for the rich `local` and sparse diagnostic `dev` scopes;
- separate immutable rich and sparse v1 pins plus schema-valid reviewed full-scope input-authority
  records created only after those source selections are active;
- checked-in response-rich and pricing-evidence-sparse Config Builder presets with lossless
  YAML/JSON round trips and deterministic generation evidence;
- lineage-correct feature → forecast → inventory rebuild evidence for each source lineage that
  changes an identity-bearing input.

### 5.2 Model and policy deliverables

- frozen pre-result protocol, seeded folds/resamples, baseline/candidate rules, untouched
  confirmation split, and strict per-market acceptance gates;
- market-local weekly price panels with eligible/withheld membership and reason codes;
- observational Poisson response artifacts, shrinkage diagnostics, confidence, support, leakage,
  stability, and holdout evidence;
- local-currency price grids/endings, action caps, dominance/product-protection policy, and exact
  recommendation reason mapping;
- source-native cost-as-of evidence, corrected WAC/FIFO semantics, generated-cost disclosure, and
  explicit client-margin non-claim;
- competitor match-quality foundation, price eligibility/freshness, monitored observations,
  alerts, and read-only review details;
- promotion scope/conflict/privacy foundation and either accepted permitted outputs or exact
  governed refusal artifacts;
- stateless price-simulation request/result contract with bounded inputs and deterministic error
  behavior.

### 5.3 Bundle, materialization, activation, API, and UI deliverables

- one immutable response-rich bundle and one immutable sparse diagnostic bundle, each with its own
  manifest, acceptance, and independent verifier record;
- schema-validated prospective result-selection v2 intents and lifecycle evidence created only after
  verification;
- one idempotent PostgreSQL migration and transactional materializer for Phase 5 serving read
  models, with no activation side effect;
- one append-only PostgreSQL result-selection-event contract, one activation-set contract, and a
  single atomic rich local-demo activation transaction;
- one deterministic post-commit activation receipt that reconciles to PostgreSQL but is never a
  serving or atomicity authority;
- non-active sparse materialization/integration evidence and rich-bundle sparse cohorts for public
  refusal-state demonstration;
- Go read models, bounded queries, OpenAPI 3.1 contract, generated TypeScript contract, stateless
  simulation, direct export endpoints, and structured 409/503/unavailable responses;
- one schema-valid, fingerprinted, secret-free local server configuration binding the rich audience,
  bundle, logical database target, DSN environment-variable name, and activation-set ID;
- four exact React pages, shared shell integration, approved existing-UI corrections, all required
  modals/exports/states, desktop/mobile screenshots, accessibility results, and human review;
- Demo 5 script and retained evidence mapping every claim to selected source/model/bundle/
  activation/API/UI identities.

### 5.3.1 Minimum bundle-to-screen-to-endpoint inventory

| Capability/read model | Minimum artifact and lineage | API/UI consumer |
|---|---|---|
| price response | panel, fit, shrinkage, resample, holdout, gate, reason rows | Price Recommendations evidence and Price Simulation |
| revenue recommendations | accepted rows, withheld rows, current/proposed price, action, confidence, priority, warnings, explanations | Price Recommendations table/KPIs/detail/export |
| margin scenario | generated/client cost class, cost-as-of, currency, scenario outputs, non-claim reason | compact Scenario Comparison only when permitted |
| simulation | request limits, selected evidence, deterministic calculation, confidence/warnings | Price Simulation form/result/preview |
| competitor intelligence | observation, match, freshness, price-gap, review state, alert/read-only detail | Competitor Monitor |
| promotion planning | lifecycle/mechanic source truth, scope, conflict, uplift or refusal, simulation/calendar detail | Promotion Planner |
| readiness/capability | Gate B input plus v2 report fingerprint/verdict and element reasons | all page/panel state envelopes |
| activation | verified bundle ID/hash, full-scope selection IDs, predecessor/successor, active flag | local API startup and response lineage |
| list/export envelope | total/filtered/visible/selected counts, export ID, limit, eligibility/reason, scope revision | all live tables and direct exports |

The bundle verifier must operate outside the artifact set it verifies and must recompute checksums,
schemas, IDs, row counts, market/currency scope, source/upstream/model/policy fingerprints,
acceptance verdicts, unavailable membership, and prospective selection identity. Materialization
must verify the same manifest before writing and must leave no partial rows. Activation happens
later and references only a successfully materialized bundle.

### 5.4 UI and demo deliverables

The exact element-level source of truth is §8 plus the approved machine-readable matrices created
by `P5-D14`. §8 is the normative seed for those matrices; implementation, tests, screenshots,
and review assert matrix rows rather than re-copying every element into later checklists.

For every destination the matrix must map route/navigation, visible text, control order, component,
data field/source, format, state variants, the closed `accessMode` value from `P5-D13`, request or
local effect, responsive position, accessibility name/focus order, modal/export contract, test ID,
screenshot ID, and approved reference deviation. Sample HTML numbers are never an allowed data
source.

Demo evidence must cover response-rich, naturally sparse, exact-zero, filter-empty, loading,
partial capability, workflow unavailable, privacy unavailable, stale, corrupt/missing, and isolated
panel-failure behavior. Rich/sparse facts come from immutable verified artifacts and API responses;
operational negative states use separately identified, non-mutating negative-evidence fixtures.

### 5.5 Task-ledger traceability

`plans/local/tasks.md` is updated only after the corresponding evidence exists. Each Phase 5
checkbox must cite the contract, implementation/test evidence, selected artifact/bundle and
activation IDs where applicable, UI matrix/screenshot/human-review evidence, and any carried
unavailable reason. Plan approval alone closes no task.

---

## 6 · Proposed file layout

Names below are proposed and must be finalized during contract freeze. Paths are binding to the
established package structure: ML work stays under `ml/src/retail_ml`, generator presets stay under
`datagen/configs`, Alembic revisions stay under `db/migrations/versions`, and tests remain package-
local. Do not introduce a second router, styling system, serving service, release tree, or conceptual
top-level `features`/`forecasting`/`inventory`/`pricing` package.

```text
contracts/
  api/
    openapi.yaml
  onboarding/
    publication-selection.schema.json              # retained legacy v1 bytes
    publication-selection-v2.schema.json           # Phase 5 normative identity contract
    input-authority.schema.json                     # retail-input-authority/v1
  evidence/
    phase5-entry-record.json
    phase5-ui-audit.json
    input-authorities/
      phase5-rich-local.json
      phase5-sparse-dev.json
    publication-selections/
      ... rich-local and sparse-dev source-selection v2 lifecycle records ...
    result-selection-intents/
      phase5-rich.json
      phase5-sparse.json
    activation-receipts/
      phase5-rich.json                               # derived post-commit evidence only
    serving-configs/
      phase5-rich-local.json                        # reviewed secret-free startup scope
  guardrails/
    price_response.yaml
    pricing_rules.yaml
  ml/
    expected-pin.json
    expected-pin-phase5-rich.json
    expected-pin-phase5-sparse.json
    price-response-run.schema.yaml
    price-response-acceptance.schema.json
    price-response-verifier-policy.json
  pricing/
    price-panel.schema.json
    recommendation.schema.json
    simulation.schema.json
    cost-evidence.schema.json
    competitor-foundation.schema.json
    promotion-foundation.schema.json
    phase5-bundle.schema.json
    result-selection-intent.schema.json
    phase5-activation-set.schema.json
    phase5-activation-receipt.schema.json
  serving/
    local-serving-config.schema.json
  screens/
    price-recommendations.parity.yaml
    price-simulation.parity.yaml
    competitor-monitor.parity.yaml
    promotion-planner.parity.yaml
    existing-ui-phase5-amendments.yaml
  profiles/
    profile.schema.json                              # existing retailer-source profile contract

datagen/
  config-builder.html
  configs/
    phase5-response-rich.yaml
    phase5-pricing-evidence-sparse.yaml
  src/retail_datagen/
    ... source-native Phase 5 fields and deterministic generators ...

ingestion/
  src/retail_ingestion/
    ... availability-preserving adapters, selection-v2 support, readiness sidecar, and retention ...
  data/evidence/
    <rich-run-id>/
    <sparse-run-id>/

ml/src/retail_ml/
  features/
    ... weekly price panels and eligible/withheld membership ...
  models/
    ... response fitting, shrinkage, resampling, holdout, acceptance ...
  engines/
    ... recommendations, simulation, competitor, promotion, and policy resolution ...
  inventory_run/
    ... explicit pin/authority path and provenance-preserving consumers ...
  publish/
    ... Phase 5 bundle builder and outside-set verifier ...
  serving/
    ... PostgreSQL materializer, result-selection/activation writer, receipt exporter ...

db/migrations/versions/
  <next>_phase5_pricing_serving.py

api/
  cmd/server/main.go
  internal/
    execution/
      ... explicit local audience/activation selection ...
    httpapi/
      pricing.go
      competitor.go
      promotion.go
      exports.go
    readmodel/
      pricing.go
      competitor.go
      promotion.go

ui/src/
  App.tsx
  api.ts
  styles.css
  PriceRecommendations.tsx
  PriceRecommendations.test.tsx
  PriceSimulation.tsx
  PriceSimulation.test.tsx
  CompetitorMonitor.tsx
  CompetitorMonitor.test.tsx
  PromotionPlanner.tsx
  PromotionPlanner.test.tsx
  components/
    ... only shared components justified by repeated exact UI behavior ...
  generated/
    phase5ScreenContracts.ts
    phase5Api.ts

contracts/python/tests/                            # schema/fingerprint/golden vectors
datagen/tests/                                     # preset and Config Builder parity
ingestion/tests/                                   # temporal/readiness/selection source tests
ml/tests/                                          # model/policy/bundle/materialization tests
db/tests/                                          # migration/transaction/current-view tests
api/internal/**/*_test.go                          # startup/read-model/endpoint tests
ui/src/**/*.test.tsx                               # UI/state/accessibility/export tests
tools/tests/                                       # pin/authority/orchestration tests

tools/
  build_expected_pin.py
  build_publication_selection.py
  dev.py
```

Generated artifacts follow the existing ignored-artifact policy. Immutable evidence required for
review is retained only in the repository locations and formats approved during `P5-3`; bulky
intermediate model files remain outside Git with manifest checksums. No Phase 5 path may add a
Dockerfile, OCI archive, deployment startup authority, cutover record, or database portability
dump. Those belong to the later serving/release plan.

---

## 7 · Work packages

### P5-0 · Reconcile Phase 4 entry authority and carryovers

**Entry:** current Phase 4 repository, retained evidence, local database if available, and selected
publication history.

**Tasks**

1. Record branch, commit, dirty-state inventory, migration head, contract hashes, retained source
   publication bytes, and the current expected-pin SHA-256 before any Phase 5 work.
2. Reconcile source selection, forecast run/version/selection, inventory run/version/selection,
   activation records, PostgreSQL current views, API lineage, and retained UI evidence. Where
   retained evidence disagrees, record each candidate and reason; plan text chooses none.
3. Separate current-snapshot capability from replay acceptance. Preserve
   `demand_forecast_non_pit`, the forecast PIT disclosure, inventory replay rejection, and all
   carried cohort-level unavailable reasons.
4. Reconcile pricing/promotion landing-backfill facts, competitor synthetic-match evidence, cost
   provenance, the 73 WAC-derived/FIFO-labelled rows, and the 68 unavailable valuation rows.
5. Record every open Phase 4 parity, screenshot, mobile, and human-review gate. Do not infer visual
   approval from passing component tests.
6. Inspect publication-selection schema/builder/resolver semantics; record that the legacy schema's
   declared exclusion default omits `lifecycle` while Python excludes it; and prove the current full-
   scope ambiguity. Do not rewrite legacy bytes in this read-only package. All Phase 5 resolution must
   include retailer, tenant, capability, and environment, and `P5-1` owns the versioned correction.
7. Verify the current expected pin references retained `run-adac9e85dccb56e8` and record its
   immutable predecessor hash
   `9b5928c270ccd8559af8f931b5761b4c07fe8e7e17eb83ebe9e4ebd614a9dab3`.
8. Record the expected-pin CLI nuance precisely: direct
   `python3 tools/build_expected_pin.py --check` defaults to absent
   `run-b847177c11ac724d` and fails, but `tools/dev.py` supplies `--run run_id` at its normal
   repin call, so this stale default does not currently break that pipeline or phase-exit path.
9. Freeze the first-consumer/resume matrix for source bytes, readiness sidecar, configs, feature
   artifacts, upstream models, pricing foundations, bundles, materialization, and activation.
10. Produce one immutable Phase 5 entry record and a reviewer disposition for every contradiction;
    make no source, ledger, database, API, or UI mutation.

**Required evidence**

- exact paths, hashes, record IDs, run/version/selection IDs, database observations, and reasons for
  every reconciled authority;
- expected-pin direct-check failure plus the inspected `tools/dev.py --run` bypass;
- full-scope selection defect reproduction;
- current/replay, Gate B/v2 readiness, cost-method/provenance, and temporal-availability findings;
- open UI review inventory;
- approved entry record and resume/invalidation matrix.

**Exit**

There is one reviewed, read-only Phase 5 entry record; unresolved identities remain explicitly
unresolved; the expected-pin bytes are unchanged; and reviewers agree which inputs may proceed to
`P5-0P`, `P5-1`, and `P5-1P`. No implementation is authorized by this exit.

### P5-0P · Existing UI audit and parity-amendment gate

`P5-0P` is a gate, not a code-cleanup package. It governs changes to already-frozen screens.

**Entry:** `P5-0` entry identity is reviewed; original HTML, current React, OpenAPI, API responses,
and all three existing screen contracts are available.

**Tasks:**

1. Build a machine-readable remediation row for every original and currently rendered shell, Data
   Management, Demand Forecast, and inventory/replenishment element.
2. Each row records original selector/text/order, React selector/component, API field/formula,
   canonical grain, filters, time window, currency, format, current state, defect, legitimate Phase
   5 unlock, required decision/matrix amendment, and exact regression evidence.
3. Freeze and approve shared-shell corrections: the exact full navigation tree, the canonical
   `?page=<PageId>` URL/default/invalid/direct/refresh/push/replace/popstate/scroll/focus contract,
   complete mobile navigation, pricing routes, parent-submenu state, partial authority loading,
   global scope semantics, currency semantics,
   footer scope, modal accessibility, and disabled-action behavior. Record Executive Overview,
   Performance Insights, Reports & Exports, Alerts & Notifications, Model Management, User
   Management, and Settings as seven individual parity rows. Unless a destination has an approved
   real route/data contract in scope, preserve its exact reference position/icon/label on desktop
   and mobile as natively disabled with an accessible business reason, no handler, no request, and
   no URL/history entry. Any absence requires an individually approved amendment; none may look
   enabled or disappear from the register.
4. Freeze restoration of the contract/reference `#dataManagement` root plus Data Management
   toolbar positions, source-specific freshness, validation detail,
   Healthy/Delayed/Needs Attention/stale/missing/failure status-and-reason vocabulary, badge mapping,
   and exact action disposition. Preserve Add Data Source, Upload Sample Data, and `Run Validation`
   in their original order. Add Data Source uses the approved visibly labelled preview-only trigger
   from §8.8.5 while `Connect` remains disabled; Upload Sample Data and Run Validation remain natively
   disabled with accessible business reasons and no handler/network call because Phase 5 has no
   source/validation mutation. Expose the latest retained Validation Results composition only
   through the approved read-only source detail/View Mapping flow. Freeze View Mapping as read-only
   where evidence exists and Refresh/Retry as disabled. Record exact identity/user-card disposition
   and no-write behavior.
5. Freeze Demand Forecast scope consistency, region/store dependency, lazy/panel-local queries,
   Weekly/Daily/Monthly option disposition, prohibition on summing weekly P50/P90 into monthly
   quantiles, controlled row/select-all state, scoped-export behavior, filtered-empty export refusal,
   the stale Demand at Risk and Stock-out Risk matrix rows/prose, a deterministic Store Priority Action rule or explicit
   retained unavailability, Scenario Planning integration, promotion integration, version
   comparison, selection controls, Action Center/Store Drilldown empty states,
   business-prerequisite copy with no internal phase/policy/fingerprint jargon, and unavailable
   Business Impact. Promotion integration remains unavailable unless `P5-D23` passes.
6. Freeze inventory wrapper IDs, ordered control groups, controlled Replenishment row/select-all
   state plus its read-only detail/export consumer and filtered-empty refusal, filters/query
   keys, strict schemas, badge/date mappings, exact-zero handling, independent summary/card/table
   visibility, risk companion, action bindings, safety-stock segment grain, allocation demand
   basis, ranking criteria, canonical current/prior Waste Reduction comparison, safe export/
   drilldown, and policy/cost-dependent unlocks.
7. Explicitly retain unavailable replay benefits, workflow facts, dock-to-stock, transfer acceptance,
   and any source fact Phase 5 still does not produce.
8. Freeze the Inventory Valuation method-label correction, all 68 unavailable rows across four
   stores/four DCs, and `derived_lane_wac` present-or-absent truth before any cost-derived unlock.
9. Amend matrices and decisions together; record reviewer and approval timestamp.
10. Freeze shared searchable-table debounce, retained-previous-data, cancellation, stale-response,
   and focus behavior, then add request-count and out-of-order response assertions. Classify every
   card-header `.link`-styled value as accessible static metadata with non-pointer/no-handler
   semantics or as a real link/button; no `aria-hidden` pointer-looking count is allowed.
11. Freeze a destination-specific live-state matrix for Data Management, Demand Forecast, and each
    of the fourteen inventory/replenishment destinations; a generic shared-state list or one
    default screenshot does not establish client-demo breadth.
12. Freeze a per-destination Store/Channel applicability matrix. Where an Inventory projection has
    no channel grain, Channel is disabled in place with a business reason and excluded from query
    keys, rather than implying scope that the endpoint cannot honor.
13. Disposition all five reference currencies—INR, USD, EUR, GBP, AED—per destination and field as
    operating, governed reporting conversion, or visibly disabled/unavailable. A live selector
    option requires a retained rate/as-of/direction; otherwise `P5-0P` approves its disabled state
    and records the Phase 6 boundary amendment.
14. Add structural assertions covering all existing screens, not only titles/endpoints or one
    sample screen, and keep visual/human acceptance open for all twenty destinations until final
    evidence exists.
15. Freeze and approve the explicit §8.8.5 access contract for every original existing-page modal,
    including Add Data Source/Validation Results, all seven Demand Forecast dialogs, and every shared
    Inventory/Replenishment action dialog. A mutation trigger opens only a non-submitting preview
    with its visible `Preview only` treatment and accessible business prerequisite; text/date fields
    are read-only, enumerated controls change local preview state only, prohibited options remain
    disabled, every submit/mutation control is disabled, and the preview performs no request/write/
    history action. Every distinct original modal is reachable as `business_live`, `read_only`, or
    `preview_only` and has a capture ID; rejection or omission blocks Demo 5 rather than downgrading
    it to hidden structural evidence.
16. Freeze a surface-state capture manifest assigning stable capture/test IDs to every page, tab,
    non-default panel, `business_live`/`read_only`/`preview_only` modal, branch-specific refusal, and
    §9 state. Every tab/panel/modal gets desktop visual plus keyboard/human review; mobile/shared-
    modal sampling is allowed only through an explicit approved equivalence row.

**Required evidence:**

- complete deviation/remediation register with no orphan visible element;
- approved, versioned existing-screen matrix amendments;
- exact selector/control/column order assertions;
- destination-specific state, filter-applicability, five-currency, data-definition, and scope tests;
- before/target screenshots at 1440×1100 and 390×844;
- written disposition for every candidate unlock and every retained unavailable value;
- approved modal access inventory proving every mandatory surface is `business_live`, `read_only`,
  or `preview_only`, with any non-authoritative structural-only duplicate explicitly excluded, plus
  the complete
  surface-state capture manifest.

**Exit:** Every planned existing-UI change is either approved with a frozen definition or explicitly
deferred. `P5-9` may implement only approved rows.

**Stop:** No existing page changes if matrix/code disagree, if a proposed unlock uses a proxy, if
original sample values are treated as truth, or if review has not approved the amendment.

### P5-1 · Freeze temporal source, selection-v2/input-authority, and operational readiness contracts

**Entry:** approved `P5-0` entry record and the relevant source/readiness decisions.

**Tasks**

1. Freeze source-native business-effective and known-as-of fields for sell price, promotion plan,
   competitor observation/product/match, receipt/cost, and any generated amendment fields.
   Landing/import time is never historical evidence.
2. Extend staging and canonical contracts without weakening bitemporal invariants. Define stable
   natural keys, currency/market scope, provenance class, generation method, and reason codes.
3. Preserve generated/synthetic truth through raw → staging → canonical → derived layers. Legacy
   labels such as `ERP_ACTUAL`, `FIFO`, or attribute match never upgrade generated WAC cost or
   synthetic match evidence.
4. Implement the v2 readiness report as a one-way retained sidecar created after the base
   publication. It cites the source snapshot, Gate A/B fingerprints, publication fingerprint, and
   manifest hash; none of those artifacts cites or changes because of the sidecar.
5. Freeze a producer registry for every readiness role, evidence flag, and sufficiency field.
   Missing or unproven producers yield reason-coded partial/unavailable/not-evaluated, never
   hard-coded ready/sufficient values.
6. Keep temporal readiness separate from claim authorization. Generated cost may be data-ready but
   cannot activate client margin; structural price variation may exist while response sufficiency
   still fails.
7. Preserve legacy selection-v1 bytes and freeze `retail-publication-selection/v2` for every new
   Phase 5 source/result selection. Make the ordered identity-exclusion vector schema-enforced;
   implement the v1-omission compatibility rule; reject conflicting explicit v1 vectors; and prove
   Python/Go/database/builder ID parity with shared golden vectors.
8. Repair expected-pin generation/check so run ID, pin path, input-authority path, job purpose,
   evidence root, retailer, tenant, and environment are explicit. Preserve relative `$schema`
   resolution beside `input-bundle.schema.json`, deterministic v1 pin bytes, and existing consumers.
9. Replace capability-only selection lookup with exact retailer × tenant × capability × environment
   lookup, explicit ledger root, schema/selection/record-ID validation, zero/multiple-match refusal,
   and exact genesis/successor proof.
10. Freeze `retail-input-authority/v1` and separate rich-local/sparse-dev records binding the entry-
    record path/hash, source selection IDs/event hashes, run, evidence root, source/readiness hashes,
    job purpose, complete scopes, and reviewed pin bytes/hash.
11. Parameterize every feature, forecast, inventory run, verifier, publisher, and materializer entry
    point with explicit expected-pin and input-authority paths. Remove the inventory runner's hard-
    coded shared-pin read for explicit jobs; a sparse job may never fall back to the rich/default pin.
12. Extend Config Builder fields, defaults, validation, import/export, and checked-in presets under
    `datagen/configs` for all approved rich/sparse source-native inputs. Prove lossless deterministic
    round trips.
13. Add contract/golden/negative tests for availability, readiness identity direction, selection-v2/
    legacy-v1 compatibility, pin/authority paths, explicit run/scope behavior, provenance, downstream
    no-fallback behavior, and Config Builder parity.
14. Run the repaired direct retained-entry check against the unchanged predecessor pin and retain
    its evidence. Do not generate response-model results in this package.

**Exit**

Source/availability/readiness/pin/selection/input-authority/config contracts are approved; the
operational readiness sidecar is identity-safe and reproducible; selection v2 and legacy-v1 semantics
agree cross-language; direct pin checking no longer depends on a stale default; every downstream job
accepts explicit pin/authority paths; full-scope ambiguity fails closed; and no source publication,
model result, activation, or UI has been changed outside this package's explicitly approved fixtures
and contracts.

### P5-1P · Pre-result protocol, reuse, evaluation, and demo-coverage freeze gate

`P5-1P` is a gate before generator profile execution or result inspection.

**Entry:** `P5-1` temporal/source contracts are approved; no response-rich Phase 5 result has been
used to choose a protocol or desired state count.

**Tasks:**

1. Complete the exact M5 reuse inventory in §1.8.1 for response, pricing, scenario, and simulator
   modules, including source commit/hashes, adaptation grade, rejected paths, and golden vectors.
2. Freeze the SKU × store × channel panel/fitted/recommendation grain and the distinct SKU × store
   department-count rule with no channel double counting. Record enrich-or-predeclare-disabled
   dispositions for United States Health (40 potential pairs), United States Home (46), and India
   Electronics (48), the three retained scopes below the 50-pair design buffer.
3. Freeze price eligibility, baseline, candidate families, tier/EB choices, twenty-configuration
   cap, exactly 13 predeclared chronological scoring origins, their spacing/window/market alignment
   and surplus-origin selection rule, origins 1–8 for development, origins 9–13 for untouched
   confirmation, resampling, holdout, strict gates, and reason hierarchy. Fewer than 13 is frozen as
   insufficient and excluded origins cannot influence candidate choice. Freeze candidate support
   clamping/no-extrapolation and the confidence/dominance-scaled **maximum** change: 2% at dominance
   0.70, linearly increasing to 5% at 1.00, always bounded by the absolute 5% cycle cap and observed
   support. It is not a 2% minimum action; emit Hold when no distinct candidate both passes every
   hard guard and beats current under the frozen objective/dominance/tie-break rule.
4. Either approve the formal Decision-#53 amendment in `P5-D23`, then freeze the promotion
   estimator/treatment/comparison/confounder/minimum-evidence/uncertainty/holdout/acceptance protocol
   and separate `P5-D22` simulation-confidence definition, including exact reuse of the price
   13-origin registry or a separately predeclared compatible promotion 13-origin registry; or
   explicitly mark every result-bearing promotion element unavailable.
5. Freeze competitor matching truth split, minimum evaluation population, precision/recall/false-
   match/calibration gates, threshold boundaries, attribute-missing cohorts, and test-truth
   non-serving rule.
6. Freeze price-response confidence, priority, At Risk, and explanation-driver formulas and
   boundary vectors separately from promotion simulation confidence.
7. Freeze the complete §9 state/count matrix before the generator profile is executed, including
   destination-specific minimum live states for Data Management, Demand Forecast, and every one of
   the fourteen Inventory pages. Separate active-rich/naturally-sparse and non-active sparse-harness states from stale
   409, missing/corrupt 503, and panel-failure states produced by an isolated non-mutating negative-
   evidence adapter; a rich publication is not required to be both valid and corrupt.
8. Freeze `P5-D18` before generation: four ordered scenario bars use the preregistered normalized
   portfolio-outcome index with Baseline = 100; freeze component definitions, weights, direction,
   missing/refusal rules, bounds, and rounding, plus the exact accessible native-unit table and the
   approved single-axis-caption parity clarification.
9. Freeze primary-rich versus sparse selection/activation isolation and exact demo/startup procedure.
   Rich source selections use `local`; sparse diagnostic source selections use `dev`; only the rich
   Phase 5 result bundle may receive active result selections and an activation-set. Name every top-
   level closed capability each lineage may claim and freeze `genesis | successor` behavior. Source
   lifecycle records require accepted source/readiness evidence; result lifecycle records cannot be
   inserted before model/bundle verification. Genesis proves no prior scope, successor proves exactly
   one current predecessor.
10. Require an independent feature rebuild plus forecast and inventory rebuild and prospective
   successor-transition preparation on **each** final primary-rich and sparse-diagnostic input pin.
   These publications change identity-bearing price/promotion/cost provenance consumed by
   each source/feature chain, so no domain-subset-equivalence or cross-profile escape hatch applies.
11. Complete and independently verify the statistical-sufficiency producers in the v2 registry
    only after the price, match, and conditional promotion thresholds above are immutable; record
    their exact policy paths/hashes and scoped aggregation queries.
12. Freeze the prerequisite artifact protocols for `P5-6A` competitor eligibility/bounds and
    `P5-7A` pricing-protection plus promotion scope/refusal. Include completed foundation manifest,
    primitive acceptance, separate verifier attempt, close-before-verify order, and tamper rules.
    `P5-5` may consume only each manifest fingerprint paired with an accepted verifier-record hash;
    page/output integration remains in `P5-6B`/`P5-7B`.
13. Record reviewer approvals and immutable protocol fingerprints.

**Required evidence:**

- reuse inventory with source hashes and adaptation decisions;
- signed/fingerprinted price, promotion, and match evaluation protocols;
- frozen candidate registry and development/confirmation origin list;
- frozen channel/count and capability-state golden vectors;
- frozen price-response confidence/priority/risk/driver mappings and promotion-confidence vectors;
- frozen Promotion Performance Forecast index/table protocol and approved axis-caption clarification;
- frozen demo-state matrix and rich-active/sparse-result-non-active disposition;
- exact rich-local/sparse-dev source scopes and rich-only result-activation disposition;
- destination-specific existing-page state minima plus isolated operational-error procedure;
- completed statistical producer registry and `P5-6A`/`P5-7A` foundation protocols;
- mandatory per-audience final-pin feature/forecast/inventory rebuild and prospective-transition rule.

**Exit:** Profile generation, model fitting, matching evaluation, promotion results, and demo-state
verification can no longer change their success definitions after results are visible.

**Stop:** Any missing baseline, open candidate family, unread/flexible holdout, unbounded search,
unresolved channel collapse, unspecified promotion/match gate, incomplete statistical producer,
missing foundation protocol, or mutable demo target blocks `P5-2`.

### P5-2 · Generate, ingest, pin, and rebuild rich/sparse source lineages

**Entry:** `P5-1` and `P5-1P` approved; rich/sparse presets and success definitions are frozen.

**Tasks**

1. Generate the response-rich preset deterministically with source-native evidence that can
   truthfully exercise both markets, price increases/reductions/holds, varying evidence strength,
   competitor states, promotion states, exact zeros, and naturally sparse cohorts. Do not target
   post-hoc KPI values.
2. Generate the pricing-evidence-sparse preset independently. It must fail or withhold price
   response/recommendation eligibility through genuine missing/insufficient evidence, not altered
   acceptance thresholds.
3. Validate Config Builder CLI/UI/preset equivalence and retain seed, config, generator/version,
   source-file hashes, market/currency scope, and row-count evidence for both outputs.
4. Ingest each output through normal raw → staging → canonical publication flow. Run Gate A/B,
   produce the identity-safe v2 readiness sidecar afterward, and retain its separate manifest.
5. Verify temporal availability, provenance, reason codes, deterministic replay, money/currency,
   referential integrity, and no rich/sparse cross-contamination.
6. For every capability required by expected-pin/v1, append schema-valid source-selection v2
   candidate → approved → active records only after source/readiness verification. Rich uses the
   exact `retailer-demo × tenant-demo × <capability> × local` scope and explicit predecessor; sparse
   uses `retailer-demo × tenant-demo × <capability> × dev` and proves genesis or one dev predecessor.
7. Only after task 6 is active, generate one schema-valid reviewed input-authority record and
   immutable v1 pin for each run using the explicit builder interface. The rich pin is the candidate
   for the shared expected pin; the sparse pin remains an explicit diagnostic input.
8. Through the ordinary reviewed repin workflow, replace
   `contracts/ml/expected-pin.json` with the exact accepted rich candidate bytes before downstream
   rebuild. Preserve the measured predecessor bytes/hash for review and recovery evidence. Do not
   equate this repin with result selection or activation.
9. Run the repaired pin checks with explicit run, pin path, authority path, job purpose, evidence
   root, retailer, tenant, and environment. Negative-test stale run, mismatched evidence root, wrong
   scope, ambiguous records, inactive selection, bad schema path, and rich/sparse interchange.
10. Rebuild features → forecast → inventory in order for each final source lineage, passing that
    lineage's explicit pin and input-authority paths to every command. Assert the inventory runner and
    all later consumers never read the shared default during the sparse run. Retain exact upstream
    IDs/fingerprints and explicit genesis/successor intent; do not reuse rich identities for sparse or
    claim domain-subset equivalence.
11. Confirm the final publications and rebuilt upstream artifacts still meet the predeclared
    source/readiness/demo prerequisites. If a source or availability change is needed, issue a new
    immutable successor and repeat the affected pin/rebuild path.
12. Do not fit or inspect response-model results until the final accepted source/upstream identities
    are frozen for `P5-3` and `P5-4`.

**Required evidence**

- both checked-in presets and lossless Config Builder round trips;
- immutable rich/sparse source publications and readiness sidecars;
- independent source verification, row/count/state coverage, and deterministic replay;
- complete rich-local and sparse-dev source-selection v2 lifecycle records for every pin capability;
- separate reviewed full-scope input-authority records and v1 pin hashes;
- predecessor and promoted-rich expected-pin byte evidence;
- explicit rich/sparse feature, forecast, and inventory rebuild lineage;
- negative tests proving no implicit run, capability-only lookup, newest-record fallback, or
  cross-profile/default-pin reuse.

**Exit**

The final response-rich and sparse source/upstream lineages are immutable, independently checked,
and explicitly pinned. Rich-local and sparse-dev source selections are active only in their distinct
batch input scopes; the shared expected pin contains the reviewed rich bytes; the sparse pin is non-
default and was passed explicitly through every downstream job. No Phase 5 result bundle has been
selected, materialized, activated, or served.

### P5-3 · Freeze remaining Phase 5 artifact, policy, API, and screen contracts

**Entry:** final `P5-2` rich/sparse source and rebuilt-upstream identities.

**Tasks**

1. Freeze price-panel, response-run, acceptance, verifier-policy, recommendation, simulation,
   cost-evidence, competitor-foundation, promotion-foundation, bundle, result-selection-intent,
   activation-set, post-commit activation-receipt, and secret-free local-serving-config schemas.
2. Freeze primitive evidence and reason-code registries. Every availability, withholding, warning,
   priority, confidence, risk, lifecycle, mechanic, freshness, match, privacy, and workflow state
   must have exactly one source and deterministic precedence.
3. Freeze pricing policy resolution by market/currency: local grid, endings, minimum distinct
   action, maximum confidence/dominance-scaled change inside 5%, support clamp, tie-break,
   dominance, product protection, and hold behavior.
4. Freeze money semantics: integer minor units or declared decimal precision, currency on every
   monetary field, FX direction/source/as-of/scope, aggregation order, and prohibition on converting
   SKU/store operating prices through the reporting-currency selector.
5. Freeze cost capability and Scenario Comparison contracts. Generated cost permits only the
   labelled synthetic scenario; `price_margin` requires client-actual provenance and remains a
   separate lifecycle.
6. Freeze competitor match/observation/freshness/review contracts and promotion
   scope/conflict/privacy/uplift-or-refusal contracts, including amended/not-amended Decision-#53
   behavior.
7. Freeze the bundle manifest and outside-set verifier: closure order, hashes, counts, full lineage,
   primitive capability proof, explicit unavailable membership, prospective selection IDs, and
   tamper refusal.
8. Freeze PostgreSQL serving tables/views, append-only result-selection-event and activation-set
   tables, idempotent migration, transactional materializer, and separate atomic rich result-
   lifecycle/activation-set transaction. Materialization cannot activate; failed activation cannot
   alter the previously active set. Freeze the deterministic post-commit receipt exporter and prove
   the receipt is not a serving input.
9. Freeze local server selection as a schema-valid, canonically fingerprinted, secret-free reviewed
   configuration containing retailer, tenant, environment, activation-set ID, expected bundle ID/
   hash, logical database target, and the constant DSN environment-variable name. The DSN/credentials
   remain environment-managed; startup validates config/database/activation/bundle agreement before
   listening. Browser input cannot choose authority.
10. Extend OpenAPI 3.1 and generated TypeScript contracts for page, detail, filter metadata,
    stateless simulation, export eligibility/download, structured unavailability, 409 stale, and
    503 missing/corrupt/panel-failure responses. No mutation endpoint is added.
11. Freeze pagination, ordering, query caps, timeout/cancellation, cache/scope revision, server
    recount, and export limits/headers/bytes for every endpoint.
12. Transcribe §8 into four machine-readable screen matrices and the approved existing-UI amendment
    matrix. Every row includes the fields defined in §8.7 and is reviewed against the original HTML.
13. Freeze exact navigation/router, global/page filters, effective Store semantics, currency
    semantics, shared component behavior, modal trigger/title/body/footer/focus contracts, direct
    exports, responsive layout, accessibility behavior, and the approved `P5-D18` chart/index/table
    interpretation.
14. Generate golden vectors and contract tests before model result inspection or React/API
    implementation begins.

**Required evidence**

- schema-valid golden/negative fixtures for every contract;
- independent fingerprint/id/checksum vectors;
- API-generated type agreement and no-mutation route inventory;
- materialize-without-activate, atomic database result-lifecycle-plus-activation, rollback, and
  post-commit-receipt-not-authority tests;
- local-serving-config fingerprint/secret-absence/startup-binding vectors;
- approved four new-page matrices plus existing-page amendments;
- explicit reviewer record that OCI/container release, drain/cutover, deployment authorization,
  and cross-host dump/restore are deferred to Phase 6–8.

**Exit**

All Phase 5 artifact, policy, database, API, export, modal, navigation, responsive, accessibility,
and screen behavior is immutable before result-bearing implementation reads model outputs.

### P5-4 · Build price panels, response models, shrinkage, and acceptance

**Entry:** Unique rich/sparse full-scope input-authority records and explicit pin hashes exist;
`P5-3` contracts are approved; rebuilt upstream run identities are fixed.

**Tasks:**

1. Import/adapt only the `P5-1P`-approved response modules at their pinned source hashes, prove
   retained golden behavior, and record every local extension.
2. Build point-in-time weekly panels using only origin-visible facts and emit assessed-series rows
   for every SKU × store × channel candidate series.
3. Compute observation count, coverage, levels, transitions, support per level, freshness, exposure,
   exclusion counts, and first failure reason.
4. Create frozen market-local price-tier and department-pool assignments from development-only data.
5. Fit the contracted Poisson GLM independently per eligible SKU × store × channel series.
6. Emit convergence, coefficient, standard error, deviance, term, sample-window, and feature lineage.
7. Compute DerSimonian–Laird cluster parameters and shrunk beta without crossing market/currency.
8. Run exactly 200 deterministic episode-block resamples and retain valid/invalid draw diagnostics.
9. Execute the approved Phase 5 extension of Decision #74 over the exact 13-origin registry:
   origins 1–8 choose from at most twenty preregistered candidates, one candidate freezes, and
   origins 9–13 are evaluated exactly once. Prove the pre-result spacing/window/market-alignment
   and eligible-origin selection rule; excluded surplus origins did not influence selection.
10. Apply every per-series gate and then per-department/per-market/channel coverage and distinct-
    SKU×store count gate.
11. Produce explicit accepted, rejected, and insufficient-evidence records for rich and sparse pins.
12. Independently recompute gates from primitive artifacts in a verifier implementation that does
    not import or trust the producer's acceptance function; retain its attempt outside the verified
    artifact set and bind it to the completed manifest hash.
13. Compare serial/parallel and Windows/macOS/Linux runs for deterministic fingerprints/tolerances.

**Acceptance:**

- no future-known input appears in a training or evaluation origin;
- every assessed series has exactly one eligibility/acceptance disposition;
- beta is negative and within the strict magnitude bound for every accepted series;
- sign consistency, IQR ratio, valid draws, and holdout improvement match independent recomputation;
- each enabled department has ≥5% accepted coverage and ≥25 actually gated series in its market;
- the ≥25 count uses distinct SKU × store pairs and channel-level coverage remains disclosed;
- the 13 scoring origins and any excluded surplus origins match the frozen registry/rule exactly;
- raw INR/USD prices and priors never mix;
- sparse pin returns the frozen `insufficient_evidence` reasons and zero recommendation rows;
- rejected outputs remain immutable and discoverable.

**Exit:** Accepted response evidence exists for each enabled rich market/department and an accepted
refusal artifact exists for the sparse profile.

**Stop:** Convergence failures, leakage, cross-market pooling, post-result threshold changes,
unexplained producer/verifier mismatch, or incomplete assessed denominators block recommendations.

### P5-5 · Build recommendations, scenarios, cost-as-of, and explanations

**Entry:** `P5-4` accepted response rows and resolved `P5-3` policies exist; compatible forecast and
inventory identities are pinned; `P5-6A` competitor and `P5-7A` promotion foundation-manifest
semantic fingerprints plus their accepted verifier-record hashes are fixed.

**Tasks:**

1. Import/adapt only `P5-1P`-approved pricing/scenario modules at pinned source hashes and pass their
   retained golden behavior before local extensions.
2. Resolve current price, accepted beta, P50/P90 availability, inventory context, protection flags,
   and local market/currency rule for every assessed SKU/store/channel context. Preserve the
   consumed forecast capability, `pitEligible`, reason, and Decision-#92 interval availability;
   non-PIT P50 may support only the current decision origin and never a historical PIT claim.
3. Enumerate, normalize, and validate candidate prices deterministically. Clamp every candidate to
   observed support/no-extrapolation, then to the confidence/dominance-scaled maximum (2% at 0.70,
   linear to 5% at 1.00), then to the absolute 5% cap, local bounds, grid, and ending; revalidate
   after rounding. The 2% term is never a minimum required action. Emit Hold when no distinct
   candidate both remains legal and beats current under the frozen objective/dominance/tie-break
   rule—even if an on-grid/in-support non-dominating candidate passed all hard guards.
4. Project model-implied units and local revenue; preserve input precision and freeze output
   rounding at API/display boundaries.
5. Resolve computed WAC cost-as-of with source, timestamp, unit, currency, and method lineage. Build
   and verify receipt-layer FIFO only if separately approved; otherwise return FIFO unavailable.
6. Enable primary margin and its margin-floor guard only for separately supplied, accepted client-
   actual cost; otherwise emit null plus element-level reason.
7. Consume only the exact independently verified `P5-6A` competitor and `P5-7A` promotion
   foundation-manifest fingerprints **and** accepted verifier-record hashes. Apply the competitor
   bound and mandatory pricing-protection overlap/conflict guard, stock risk, scaled/absolute caps,
   client-margin guard where capable, dominance, protection, and tie-breaks in order; never
   recompute a foundation silently. D23-negative Planner refusal does not bypass or satisfy the
   pricing-protection guard.
8. Emit Increase, Decrease, and Hold recommendations plus accepted/rejected candidate details.
9. Build the workbench union with `recommendation` versus `withheld_assessment` identity and enforce
   the null, selection, action-filter, Manual review, and count rules in `P5-D21`.
10. Produce confidence, priority, reason/driver, risk/guardrail, revenue impact, optional client-
   actual margin impact, and stock-cover context using frozen mappings.
11. Build stateless Expected/Best/Worst price scenarios with Current/Proposed/Recommended columns.
12. Calculate a separately identified, visibly labelled synthetic-margin scenario for generated
    PoC cost only after the primary recommendation is fixed; prove it cannot alter primary
    candidates, guardrails, ranks, prices, KPIs, or aggregates.
13. Add a compatibility adapter for Demand Forecast Scenario Planning without persisting state.
14. Generate accessible explanation facts tied to model/policy/source lineage; never generate a
    causal or guaranteed-outcome statement.
15. Prove all formulas, grids, endings, max change, dominance, ties, cost truth tables, and null/
    reason truth tables through golden vectors.

**Acceptance:**

- every recommendation carries market and operating currency;
- every non-Hold price is inside observed support, on the local grid/ending, within the scaled
  dominance cap and absolute 5% cap after rounding; Hold results when no distinct candidate is both
  legal and dominant/objective-improving under the tie-break contract;
- every competitor/promotion guard cites the exact accepted `P5-6A`/`P5-7A` manifest fingerprint and
  verifier-record hash; no actionable recommendation exists with missing/ambiguous pricing-
  protection evidence, even on D23-negative;
- no recommendation exists without accepted beta and forecast;
- every recommendation discloses a non-PIT forecast dependency where applicable and no historical
  evaluation treats that forecast as origin-visible PIT evidence;
- revenue exists independently of margin; unavailable margin remains null plus reason;
- every displayed margin identifies client-actual or canonical synthetic provenance; real/client margin uses
  client-actual same-currency cost at/before origin, while generated cost is confined to the
  separately labelled synthetic scenario and cannot change any primary output;
- sample HTML changes beyond 5% never appear as live data;
- stateless simulation refuses invalid/off-grid/out-of-range/max-change/sparse requests precisely;
- repeat execution is byte/fingerprint deterministic.

**Exit:** Governed price recommendation and scenario artifacts are ready for bundle assembly.

**Stop:** Any current/candidate price currency mismatch, future cost, missing policy, unguarded
rounded price, fabricated margin, or recommendation from a rejected series blocks publication.

### P5-6A · Build competitor match, eligibility, and bound foundations

**Entry:** Approved `P5-3` competitor source/match/freshness/bound contracts and the fixed rich
input authority exist; `P5-5` has not consumed a competitor guard.

**Tasks:**

1. Ingest/populate auditable product attributes required by the approved matching policy.
2. Construct effective-dated match candidates and score frozen identity/attribute components.
3. Evaluate on the disjoint `P5-1P` truth set and enforce frozen precision, recall, false-match,
   calibration, cohort, and boundary gates. Test truth remains outside served artifacts.
4. Classify each candidate as auto-accepted/Matched, Needs Review, Rejected, or No Match.
5. Preserve manual-review state as read-only source evidence if present; do not create a Phase 5
   review mutation.
6. Normalize competitor price/unit/currency only under contracted conversions and retain original
   values.
7. Compute observation freshness, price difference, availability state, promotion state, and
   inclusion/exclusion reason.
8. Emit immutable assessed-match and competitor-eligibility/bound artifacts from primitives only.
   The latter identifies the admissible observation, local response bound inputs, exclusions,
   input authority, policy fingerprint, and upstream hash; it does not select or change a local
   recommended price.
9. Write `competitor-foundation-acceptance.json`, then close/hash
   `competitor-foundation-manifest.json` over the exact assessed/bound artifacts, acceptance,
   source/policy/code identities. Only afterward independently recompute it and retain
   `competitor-foundation-verification.json` outside the set, bound to the completed manifest hash.

**Acceptance:**

- every potentially driving competitor fact has approved client/licensed provenance or canonical
  synthetic evidence/derivation/source identity plus the “Synthetic demo” display purpose;
- low-confidence/review/rejected/no-match/stale rows are explicitly excluded from the bound;
- market/currency/unit comparisons, match gates, and every inclusion reason reconcile independently;
- the immutable foundation-manifest semantic fingerprint and accepted verifier-record hash are
  ready for exact consumption by `P5-5`; ordering/tamper checks pass.

**Exit:** One independently verified competitor eligibility/bound foundation is frozen before price
recommendations are built.

**Stop:** Empty match attributes disguised by a high score, prohibited collection source, stale
fact used as current, or an unverified/mutable bound blocks `P5-5`.

### P5-6B · Build competitor monitoring and recommendation integration

**Entry:** `P5-6A` has passed and `P5-5` recommendations cite its exact foundation-manifest and
accepted verifier-record hashes.

**Tasks:**

1. Join the immutable `P5-6A` assessed/bound artifacts and their manifest/verifier hashes to `P5-5`
   without recalculating eligibility.
2. Produce bounded recommended-response context only for admissible matches and accepted local
   pricing contexts; prove the local recommendation remains inside every local guard.
3. Aggregate page KPIs and match-quality metrics from the filtered assessed population.
4. Publish read-only existing alert-rule facts only where source evidence exists; otherwise retain
   the card/columns with an unavailable state.
5. Cover In Stock, Low Stock, Out of Stock, Unknown, fresh, near-threshold, stale, Matched, Needs
   Review, Rejected, and No Match states in governed rich data.

**Acceptance:**

- every displayed/driving row cites the exact `P5-6A` manifest/verifier and `P5-5` recommendation context;
- low-confidence/review/rejected/no-match/stale rows never enter recommendation candidate scoring;
- KPIs, table, filters, detail, and export use the same assessed population;
- Add Competitor, Create Alert, and match mutations have no Phase 5 endpoint or enabled handler.

**Exit:** Competitor Monitor artifacts are live for permitted evidence and transparent for all
excluded states.

**Stop:** Foundation-manifest/verifier drift, recommendation recomputation, stale evidence used as current, or a
competitor price copied outside local guards blocks acceptance.

### P5-7A · Build promotion scope, conflict, and refusal foundations

**Entry:** The `P5-D23` disposition and `P5-3` promotion/privacy contracts are recorded; `P5-5` has
not consumed a promotion guard.

**Tasks:**

1. On **both** branches, resolve only the `P5-D10` origin-visible active/planned pricing-protection
   feed at recommendation scope. Emit applicable/no-overlap/conflict/missing/ambiguous records and
   fail closed on equal-precedence conflicts. Produce the immutable guard consumed by pricing with
   exact input authority, policy, valid/known times, inclusion/refusal reasons, and upstream hashes.
   Missing protection evidence withholds actionable prices; D23-negative never means “no overlap.”
2. On the approved-amendment branch, additionally resolve full Planner scope using AND within row,
   OR across rows, market-qualified geography, and deterministic merchandise precedence. Bind
   lifecycle/mechanic only from dedicated source fields and reject status/class proxies.
3. On `decisionDisposition = not_amended`, skip all full Planner scope/lifecycle/mechanic/model logic and
   emit a separate `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` foundation disposition. It refuses Planner/
   Forecast feature claims while leaving the safety-only pricing guard usable and undisclosed as a
   promotion feature.
4. Write `promotion_foundation_disposition.json` with only the logical amended/not-amended
   foundation member types and reasons knowable at this stage; it cannot cite its own manifest or
   the future outside verifier and does not predict numeric/descriptive package outcome. Write
   `promotion-foundation-acceptance.json`, then close/hash
   `promotion-foundation-manifest.json` over the exact branch-permitted artifacts, safety guard,
   disposition, acceptance, source/policy/code identities. Only afterward independently verify
   foundation membership, foundation-level first/secondary reasons, and guard/conflict primitives; retain
   `promotion-foundation-verification.json` outside the set, bound to the manifest hash.

**Acceptance:**

- the pricing-protection guard passes overlap/no-overlap/conflict/missing vectors on both branches;
- approved branch full scope/conflict golden vectors pass across SKU/department/category overlap and
  ambiguous equal precedence always refuses;
- not-amended foundation contains no fabricated Planner lifecycle, mechanic, full-scope, model, or numeric
  value; its safety-conflict facts remain internal to the price guard;
- the immutable foundation-manifest semantic fingerprint, accepted verifier-record hash, and
  decision/foundation disposition are ready for exact `P5-5` consumption; ordering/tamper and no-
  self/future-reference checks pass.

**Exit:** One verified pricing-protection guard plus exactly one positive-Planner or negative-
refusal disposition is frozen before price recommendations are built.

**Stop:** Unresolved promotion origin, proxy lifecycle/mechanic, ambiguous conflict, branch drift,
or an unverified/mutable foundation blocks `P5-5`.

### P5-7B · Build permitted promotion planning outputs or exact refusal states

**Entry:** `P5-7A` has passed; `P5-5` cites its exact foundation-manifest and accepted verifier-
record hashes; pinned inventory and price/cost capabilities exist. The amended branch additionally requires the formal Decision-#53
amendment and origin-safe promotion evidence.

**Tasks:**

1. Join the exact `P5-7A` foundation without recalculating scope/conflict. On not-amended,
   keep its pricing-protection guard internal to recommendation lineage, publish only typed
   `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` Planner/Forecast artifact/API/UI states, retain Decision #19
   as secondary policy metadata, and skip all model, numeric opportunity, and executable simulation
   work below.
2. On `decisionDisposition = amended`, execute exactly the already approved frozen observational
   `P5-D20` assessment pipeline for every candidate scope. Retain accepted, rejected, insufficient,
   and not-evaluated assessment primitives. Emit numeric baseline/promoted projections only for
   accepted scopes; if none pass, use the descriptive-only package disposition. An unapproved
   protocol blocks the package and is not a valid descriptive outcome.
3. Only when the accepted `P5-D20` model and `P5-D22` confidence gate pass every rule, produce
   Expected/Best/Worst stateless promotion scenarios. Otherwise publish no numeric scenario and
   keep the exact control/result locations disabled with the stable reason.
4. When an accepted demand projection or independently governed source requirement exists, resolve
   required stock and pinned inventory readiness into fully available, transfer required,
   replenishment required, insufficient/at risk, and unavailable; otherwise keep requirement and
   readiness unavailable without substituting current stock.
5. Join descriptive aggregate segment counts/mix without customer identifiers; never use them as a
   model feature, selector, offer rule, or recommendation target.
6. Compute model-implied revenue only for accepted `P5-D20` rows. Compute primary promotion margin
   only with client-actual cost. Generated-cost margin remains unavailable throughout Promotion
   Planner with `COST_NOT_CLIENT_ACTUAL`; it is demonstrated only in the exact Price Simulation
   §8.3.2 synthetic panel and cannot populate promotion results, KPIs, portfolio cells,
   opportunities, modals, or charts.
7. Produce permitted descriptive scope/conflict/audience-mix/risk/calendar artifacts on the
   amended branch. Produce numeric opportunity, performance, scenario, and model-derived readiness
   only when their gates pass and use the frozen chart semantics.
8. On the amended branch, emit `privacy_restricted` for cannibalisation, bundle, basket, segment-
   specific response/offer, and customer-targeting fields; preserve their original UI locations and
   disable their controls. On not-amended, preserve the locations but use the Planner refusal first
   and retain privacy only as secondary metadata.
9. Keep Create Promotion, status/owner workflow mutation, approval route, and persistent schedule
   disabled; expose no mutation route.
10. After all model/element outcomes are known, write `promotion_package_disposition.json` with
    exactly one `positive_numeric | positive_descriptive_only | negative` value, its exact logical
    required/forbidden member inventory, and per-element first/secondary reasons. It cannot cite its
    enclosing Phase 5 manifest or future verifier; `P5-8` binds its hash and the already accepted
    foundation-manifest/verifier hashes separately.
11. On a passing numeric package, cover readiness, conflict, cost, aggregate-audience, privacy,
    rich, and sparse states; on descriptive-only or negative packages, cover every disabled control/
    result/KPI/chart location and the permitted descriptive/refusal states instead.

**Branch-specific acceptance:**

- **Positive numeric branch:** no landing-backfilled row trains the model; every response passes the
  frozen episode/support/uncertainty/development/final-confirmation/holdout gates; every live
  Confidence reconciles to `P5-D22`; inventory and cost lineage reconcile; page aggregates agree.
- **Positive descriptive-only branch:** the approved `P5-D20` assessment pipeline ran and retained
  every rejected/insufficient/not-evaluated primitive with zero accepted rows; every dependent
  numeric location is unavailable with its precedence-derived reason and no executable simulation
  path, while permitted scope/conflict/audience/calendar evidence remains truthful.
- **Negative `P5-D23` branch:** the exact refusal surfaces are complete, no source-derived/numeric
  Planner promotion output exists, the pricing-protection guard remains separately verified but is
  not exposed as feature evidence, `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` is the first failure, and
  conditional numeric/demo requirements are non-applicable rather than falsely failed.
- **All branches:** the final package disposition exactly matches physical membership without self/
  future-verifier references; no customer identifier or basket record enters artifact/log/API/UI;
  Decision #19 fields have no numeric proxy; generated cost never enters a primary promotion aggregate.

**Exit:** The selected branch's permitted promotion artifacts and explicit privacy/evidence refusal
artifacts are ready.

**Stop:** Package ambiguity, foundation-manifest/verifier drift, customer-level data, unaccepted inventory
lineage, fabricated numeric output, or cannibalisation/bundle proxy blocks publication.

### P5-8 · Publish, independently verify, materialize, activate, and serve locally

**Entry:** `P5-4`, `P5-5`, `P5-6A/B`, and the applicable `P5-7A/B` branch satisfy package
acceptance and the frozen `P5-3` bundle/database/API contracts.

**Tasks**

1. Assemble separate immutable response-rich and sparse bundles. Each binds its exact input pin/
   authority, readiness report, rebuilt upstream identities, response/recommendation/scenario/cost,
   competitor, branch-permitted promotion, capability, explanation, lineage, assessed-denominator,
   rejected/insufficient, and aggregate artifacts. No union bundle exists.
2. Close each manifest before verification. Bind the exact accepted `P5-6A` and `P5-7A`
   foundation-manifest/verifier hashes and the promotion package disposition without creating a
   circular identity.
3. Before manifest closure, schema-validate prospective result-selection v2 intents and derive their
   IDs from full scope plus semantic evidence using the shared identity vector. Bundle or verifier
   hashes, lifecycle state, and approval metadata must not participate in those selection IDs.
4. Independently verify every manifest outside the verified artifact set: schema, checksum, ID,
   row count, market/currency, source/upstream/model/policy/code lineage, formula, strict gate,
   money/cost truth table, competitor exclusion, promotion/privacy branch, state coverage,
   readiness fingerprint/verdict, unavailable membership, and prospective selection identity.
   Retain rejected attempts without changing producer bytes.
5. Apply the next idempotent serving migration after confirming the current migration head. Add
   normalized immutable version/run/output tables, indexes, current read views, append-only result-
   selection-event rows, append-only activation-set events, scope/predecessor constraints, and the
   database enforcement needed for one current rich local activation-set.
6. Materialize each verified bundle in its own PostgreSQL transaction. Recompute manifest hashes/
   counts/invariants inside the materializer, roll back on any mismatch, prove rich/sparse row
   separation, and do not activate as a side effect.
7. Prove both materializations are queryable while the prior active state is unchanged. From only
   the prebound accepted intents, prepare canonical rich v2 candidate, approved, and active event
   bytes off-database; recompute selection/record IDs, bind reviewer evidence, prove the exact current
   predecessor, and prepare no sparse active result event.
8. In one separate serializable/locked-scope PostgreSQL transaction, verify the prepared bytes again,
   insert the exact rich result-selection lifecycle events, and insert one activation-set referencing
   the verified rich bundle and exact active selection IDs. Database constraints enforce full-scope
   genesis/successor semantics and at most one current activation-set. Any failure rolls back every
   inserted lifecycle/activation row. The sparse bundle remains non-active and cannot activate
   `price_revenue`.
9. After commit, export and independently check the deterministic activation receipt against the
   immutable PostgreSQL rows. Prove deleting/regenerating the receipt cannot change serving and that
   the server never reads it. Do not claim filesystem/database atomicity.
10. Implement Go PostgreSQL stores/read models/handlers for page summaries, tables, filters, sort,
   bounded pagination, detail, calendar, governance, alerts, and exports. Implement the price
   simulation POST as bounded, deterministic, non-mutating calculation.
11. Promotion simulation returns numeric results only on the approved/accepted amendment branch;
    otherwise its contract returns typed unavailable and the UI does not call it.
12. Bind local startup to the schema-valid, canonically fingerprinted, secret-free reviewed config.
    Load the DSN only from its fixed `RETAIL_POSTGRES_DSN` environment boundary; validate logical
    database target, retailer, tenant, environment, bundle ID/hash, selection membership, and rich
    activation-set ID before listening. Do not accept browser-provided authority labels, config-path
    overrides from requests, or a DSN/credential inside the retained config.
13. Update OpenAPI 3.1 and regenerate strict Go/TypeScript/runtime schemas. Add query-plan/index,
    limit, timeout, cancellation, stale-scope, no-file-read, no-refit, and no-write tests.
14. Start the existing Go binary through the established Phase 3/4 local process convention against
    Compose PostgreSQL and retain live rich API smoke evidence. This is local serving, not a
    container or deployment release.
15. Exercise the separately materialized sparse bundle through an isolated non-public API
    integration harness using explicit non-active materialization scope. Prove refusal responses and
    zero activation changes; do not start a second public live server.
16. Produce stale 409, missing/corrupt 503, and panel-failure evidence through isolated
    non-mutating negative fixtures/adapters. Never damage or rewrite rich/sparse bundle or database
    bytes to demonstrate operational failure.

**Minimum proposed endpoints**

GETs are read-only. POSTs are bounded, non-mutating stateless calculations. Final paths freeze in
`P5-3`.

- `GET /api/v1/pricing/recommendations/summary`
- `GET /api/v1/pricing/recommendations`
- `GET /api/v1/pricing/recommendations/{id}`
- `GET /api/v1/pricing/recommendations/store-view`
- `GET /api/v1/pricing/recommendations/category-view`
- `GET /api/v1/pricing/recommendations/governance`
- `POST /api/v1/pricing/simulations:run`
- `GET /api/v1/competitors/summary`
- `GET /api/v1/competitors/matches`
- `GET /api/v1/competitors/matches/{id}`
- `GET /api/v1/competitors/alert-rules`
- `GET /api/v1/promotions/summary`
- `GET /api/v1/promotions/opportunities`
- `GET /api/v1/promotions/portfolio`
- `GET /api/v1/promotions/calendar`
- `POST /api/v1/promotions/simulations:run`
- `GET /api/v1/pricing/export`
- `GET /api/v1/direct-exports/{exportId}`

Pricing export supports only bounded `selected | filtered | all` with `csv | excel_csv`,
validated basename, canonical scope, server recount, exact lineage/count headers, safe filename,
formula neutralization, and no partial download. PDF/audit remain disabled. Direct exports use only
registered §8 trigger IDs, `selected_visible | current_filtered` scope, canonical filters/sort,
`expectedCount`, and opaque `scopeRevision`; 409 stale, 422 invalid scope/IDs, and typed
over-limit refusal never truncate or silently change scope.

**Acceptance**

- manifest, independent verifier, PostgreSQL materialization, result-selection events, rich
  activation-set, post-commit receipt, API, OpenAPI, generated clients, runtime schemas, and displayed
  values reconcile exactly;
- materialization and activation are separately testable/rollback-safe; result-selection events and
  activation-set roll back together; the receipt is demonstrably non-authoritative; sparse result
  evidence remains non-active;
- one rich activation-set is current for the explicit local audience;
- the reviewed secret-free local-serving config fingerprint, environment-provided DSN, database
  identity, bundle hash, and activation scope agree before the server listens;
- Go request paths read only PostgreSQL and perform no file/model/MLflow access or refit;
- stateless POSTs write no domain, audit, selection, or activation state;
- typed unavailable, 409, and 503 behavior preserves reason, capability, as-of, retry/remediation,
  and unaffected panel availability;
- pagination, sorting, filters, summaries, details, selection, and exports share one scope/count
  contract;
- rich live smoke and isolated sparse integration evidence both pass;
- no API/UI container, image/archive, drain/cutover, deployment authority, registry/origin push, or
  database dump/restore is created in Phase 5.

**Exit**

The four Phase 5 pages and stateless simulation can read the one verified, materialized, explicitly
activated rich local audience through the existing Go/Compose PostgreSQL pattern. Sparse and
negative behavior is proven respectively through the non-active sparse harness and non-mutating
adapters, while truthful naturally sparse rich-bundle cohorts supply client-facing refusal states.

**Stop**

Verifier mismatch, partial materialization, activation during materialization, ambiguous/full-scope
selection failure, non-atomic database result-selection/activation writes, receipt-as-authority,
credential-bearing retained config, two active sets, inactive claimed capability, schema drift,
unbounded query/export, request-time file/model access, database mutation, or any attempt to pull
Phase 6–8 release work into this package blocks exit.

### P5-9 · Implement exact React UI, approved remediations, and Demo 5

**Entry:** `P5-0P` amendments, four `P5-3` matrices, and the twenty-destination state/applicability
matrix are approved; `P5-8` rich live API, sparse integration harness, negative-state adapters,
and generated schemas pass.

**Tasks:**

1. Add four typed page IDs/routes and the exact §8.1 navigation tree, canonical `?page=` default/
   invalid/direct/refresh/push/replace/popstate/scroll/focus contract, working desktop/sidebar
   navigation, parent submenu behavior, and full mobile navigation. Apply the seven approved non-Phase-5 nav
   dispositions in exact desktop/mobile group/order/icon/label; every unimplemented entry is native-
   disabled with its reason and has no handler/request/history transition.
2. Decouple shell and page authorities so Data Management or one page/panel failure does not block
   unrelated destinations.
3. Implement authority/Store-derived market context plus the visible shared Store/Channel filters,
   operating/reporting currency behavior,
   scoped footer, typed API errors, structure-preserving skeletons, exact-zero/empty/unavailable/
   stale/missing states, and accessible modal primitives. Honor each destination's frozen Channel
   applicability and all-five-currency live-or-disabled disposition exactly. Use one canonical
   effective Store and enforce the Price Recommendations global/page Store synchronization/reset
   contract.
4. Implement only the approved existing-page remediation rows from `P5-0P`, including Forecast
   granularity refusal, Forecast/Replenishment controlled selection and empty-export behavior, and
   static-versus-action card-header metadata semantics. Implement every exact §8.8.5 Data/
   Forecast/Stock Health/Inventory/Replenishment `business_live`/`read_only`/`preview_only` modal and
   capture state; do
   not retain a simplified current Forecast body or conflate visible trigger labels with modal titles.
5. Build Price Recommendations exactly as §8.2, including all tabs/table columns and read-only
   detail/Compare Selected/Export surfaces. Pricing Action Center and workflow form bodies use only
   their approved preview-only access; their submit/mutation actions remain disabled.
6. Build Price Simulation exactly as §8.3 with local validation, the one approved synthetic-margin
   panel location, competitor Include/not-included execution truth, and live stateless results.
7. Build Competitor Monitor exactly as §8.4 with controlled read-only queue selection, match/filter/
   detail/rule surfaces, exact Review footer/in-place Link state, and approved Add Competitor preview;
   mutations remain disabled.
8. Build Promotion Planner exactly as §8.5 with the approved Create Promotion preview, permitted live values, accepted stateless
   simulation only when `P5-D23`, `P5-D20`, and `P5-D22` pass, distinct unavailable-result preview,
   read-only calendar, and explicit evidence/privacy/workflow unavailability everywhere else.
9. Make filters update all affected KPIs/charts/tables consistently. Apply the frozen debounce,
   retain prior data without flashing, cancel obsolete requests, prevent out-of-order response
   overwrite, and preserve predictable search focus.
10. Ensure every unavailable element remains in its original position with a concise business
    prerequisite, never internal phase/package language.
11. Remove production sample constants and scan bundles for original sample values.
12. Run structural DOM/order/text/ID assertions, data-value/formula assertions, currency/scope and
    byte-level export assertions, interaction tests, all new/existing preview zero-effect tests,
   deterministic modal focus/close/result/in-place-transition tests, static-metadata cursor/AT tests,
    loading/error tests, accessibility tests, and visual comparisons.
13. Execute the surface-state capture manifest: capture all twenty implemented destinations at
    1440×1100 and 390×844, including existing pages with no local Phase 5 code change, plus every
    tab/non-default panel and every `business_live`/`read_only`/`preview_only` modal at least once on
    desktop; run 1024
    breakpoint smoke and only the explicitly approved representative mobile-modal/browser/OS samples.
14. Walk the response-rich demo script, including its naturally sparse cohorts, and record the
    source/run/bundle/activation evidence on every page. Use the isolated sparse integration harness
    and non-mutating negative adapters to prove full refusal, stale 409, missing/corrupt 503, and
    panel failure without changing the active rich bundle or either materialization.
15. Obtain independent human approval per page and for the whole navigation/demo flow.

**Acceptance:**

- all twenty implemented destinations are reachable on desktop and mobile;
- Executive Overview, Performance Insights, Reports & Exports, Alerts & Notifications, Model
  Management, User Management, and Settings each match its approved exact routed/disabled/absent
  disposition; no unimplemented item looks enabled or changes URL/history;
- canonical query URL, Demand-Forecast fallback, browser back/forward, direct links, refresh,
  active submenu, route-change scroll/focus, and invalid page normalization work exactly;
- original titles, subtitles, action/filter/card/tab/table/modal order and required IDs match;
- no enabled-looking control is inert and no disabled control can mutate; approved preview-only
  triggers are visibly described, locally explorable only as contracted, and make zero request/
  write/history change;
- filter/scope/currency changes reconcile from UI to API and across summary/rows/export;
- Data Management exposes the approved `#dataManagement` root; Channel is disabled/labelled on
  destinations that lack channel grain; INR/USD/EUR/GBP/AED are each live with governed FX or
  visibly disabled/unavailable according to the approved matrix;
- Data Management preserves Add Data Source → Upload Sample Data → Run Validation; Add Data
  Source opens only its labelled preview with Connect disabled and no request/write/history, while
  Upload/Run remain disabled/no-handler and source detail/mapping exposes only retained Validation
  Results evidence;
- the shell adds no Market control; reviewed local server scope plus canonical Store/region derives market and
  any mixed all-store view obeys governed reporting-currency semantics;
- Price Recommendations has one effective Store across global/page controls; Forecast and
  Replenishment selections are controlled and filtered-empty export makes no request/download;
- all §8.8.5 Forecast, Stock Health, and shared existing-page modal compositions, exact visible-
  trigger/modal-title mappings, access modes, preview/result/in-place transitions, capture IDs, and
  deterministic title→X→body→footer focus/close/return behavior pass;
- Daily/Monthly Forecast options never synthesize quantiles by summing weekly P50/P90;
- the synthetic margin appears only in the approved §8.3.2 panel, and competitor excluded results
  never leave the visible field saying Include;
- competitor zero/one/many/select-all queue states and modal preview option states are live and
  mutation-free;
- local prices remain in operating currency while approved reporting aggregates convert visibly;
- one panel failure remains panel-local and structure does not jump during loading/error;
- exact zero, true no-results, sparse evidence, partial capability, 409, 503, and panel failure are
  distinct, with the latter three demonstrated only through isolated non-mutating adapters;
- no business UI contains phase/roadmap/package explanations;
- all live values come from selected APIs and accepted artifacts;
- every surface-state capture/test ID reconciles; screenshots, DOM, data, accessibility, local
  browser, and human-review gates pass.

**Exit:** Demo 5 truthfully demonstrates response-rich and sparse Phase 5 outcomes in the exact
original UI while the existing application remains coherent and corrected.

**Stop:** No page is demoable with sample/fallback data, failed visual review, stale contract,
missing mobile reachability, misleading currency, fabricated unavailable value, or unapproved
existing-screen change.

---

## 8 · Exact screen scope and element/data disposition

### 8.1 Shared application shell

The shell applies to every new and existing page. Preserve this visual and DOM order:

1. sidebar brand: cart mark, `AI Retail Intelligence`, and `Dynamic Pricing & Demand Forecasting`;
2. navigation in the exact reference tree, group-label, order, icon, and parent/submenu structure:
   ungrouped `⌂ Executive Overview`; `PRICING` → `🏷 Price Recommendations`, `◫ Price Simulation`,
   `◉ Competitor Monitor`, `▣ Promotion Planner`; `DEMAND & INVENTORY` → `▥ Demand Forecast`,
   parent `▤ Inventory Overview` (`#inventoryMenuToggle`) → `▥ Store Inventory`, `▦ Warehouse
   Inventory`, `◷ Inventory Ageing`, `⇄ Stock Transfers`, `₹ Inventory Valuation`, `⚠ Expiry &
   Waste` (`#inventorySubmenu`), then parent `⇄ Replenishment Planner`
   (`#replenishmentMenuToggle`) → `≣ Suggested Orders`, `▦ Supplier Planning`, `◉ Safety Stock`,
   `⇢ Allocation & Fulfillment`, `⚠ Exceptions` (`#replenishmentSubmenu`), then `◇ Stock Health`;
   `ANALYTICS` → `⌁ Performance Insights`, `□ Reports & Exports`, `♢ Alerts & Notifications`;
   `ADMIN` → `▦ Data Management`, `⚙ Model Management`, `♙ User Management`, `☼ Settings`;
3. user card in the original sidebar position (`EJ`, `Emma Johnson`, `Category Manager` are reference
   samples, not identity facts); identity/RBAC remains unavailable until authenticated evidence
   exists;
4. main topbar title/subtitle first, followed by controls in exact order: Channel, text date/as-of,
   Store, reporting Currency, FX, notification;
5. content-level currency/reporting strip;
6. page-specific actions and content;
7. footer KPI strip in order: Total SKUs, Active SKUs, Stores, Channels, Forecast Coverage, Data
   Freshness, Model Accuracy;
8. exact footer strings: `AI Retail Intelligence — Dynamic Pricing & Demand Forecasting` and
   `Powered by AI • Built for Retail`.

Do not add visible lineage copy to the footer without an approved amendment. Lineage belongs in FX
details, page/detail metadata, and exports while the footer retains its reference copy.
Seven non-Phase-5 shell entries require explicit remediation rows: Executive Overview, Performance
Insights, Reports & Exports, Alerts & Notifications, Model Management, User Management, and
Settings. Preserve their exact reference groups/order/icons/labels on desktop and mobile. Unless an
entry has a separately approved real route/data contract, show it natively disabled with an
accessible business reason, no handler/request/history entry, and no fake page. An individually
approved parity amendment is required to omit any one of them.

The navigation matrix must approve one canonical URL/state contract. Recommended binding preserves
the implemented React shape `?page=<PageId>` as the sole canonical route: valid user navigation
uses `pushState`, same-page activation creates no duplicate entry, and `popstate` restores page,
title/subtitle, active item, open parent submenu, request scope, scroll-to-top, and focus on the page
heading. Missing or invalid `page` normalizes with `replaceState` to `demandForecast` while
Executive Overview has no approved live route; this explicit deviation from the reference HTML's
`overview`/`#pageId` default belongs in `P5-0P`. A separately approved Executive Overview route is
required before changing that default. The reference hash is not a second silent router. Disabled
entries never change state, URL, history, scroll, or focus. Direct URL, refresh, and back/forward
tests use this one contract.

Inventory Overview and Replenishment Planner parent activation navigates to the parent page and
expands its submenu; a child destination keeps its parent expanded, caret state/`aria-expanded`
agree, and keyboard/mobile behavior preserves the same tree. Collapse is navigation-only local UI
state and never hides the active child. Any different parent-click behavior requires a matrix row.

Shared behavior requirements:

- Channel options remain All Channels, Store, E-commerce only on destinations whose approved API
  projection carries channel grain or a governed allocation. On location-grain Inventory pages
  without it, preserve the control position but disable it with an accessible business reason;
  exclude it from query/cache keys and never imply that it scopes the page.
- The original topbar date control is a text input. In Phase 5 it is a visibly read-only active
  reporting/decision window sourced from the selected publication authority, never an enabled
  inert field. It freezes the pricing decision origin/window, competitor observation cutoff,
  promotion KPI/portfolio window, and the as-of scope used by page summaries and exports. Page-
  specific simulation horizons and promotion calendar months remain separate controls. `P5-0P`
  freezes its timezone, inclusive/exclusive boundaries, display format, and affected-element matrix.
  Enabling historical date selection requires an approved parity amendment and versioned APIs that
  can reproduce every affected value for the chosen window.
- The original topbar has no Market selector and Phase 5 adds none. Market comes from the reviewed
  local server scope and the canonical Store/region identity; selecting a Store derives its market, while an
  all-store mixed-market view follows the governed reporting-currency contract. Store options use
  canonical IDs; original sample city labels remain visual reference only. Any visible Market
  control requires a `P5-0P` presentation amendment before code.
- Currency options and symbols remain `₹ INR`, `$ USD`, `€ EUR`, `£ GBP`, `د.إ AED`. Each option is
  individually governed: it is selectable only with a retained FX source, as-of, direction,
  decimal rate, rounding, and affected-field scope, otherwise it stays visible but disabled/
  unavailable with a business reason. Phase 5 must demonstrate all five dispositions; current/
  recommended/competitor prices and local rule inputs remain operating-currency values. Any
  ungoverned cross-market currency implementation remains an explicit Phase 6 boundary amendment.
- The original strip positions remain `Display Currency:`, the currency chip, rate/base text, and a
  behavior sentence. Because the original sentence `All monetary values update across dashboards,
  tables, modals and exports.` conflicts with local pricing rules, `P5-0P` must approve a replacement
  such as `Aggregate reporting values update; operating prices remain in each market's local
  currency.` before implementation.
- FX opens the exact `Multi-Currency Configuration` modal structure: a callout; table columns
  Currency and Configured Rate; rows INR, USD, EUR, GBP, AED in that order; Close footer button.
  Replace the original fixed-demo-rate callout/rates with governed FX source, as-of, direction,
  exact decimal rate, rounding, and converted-element scope through the same approved amendment.
- Notification stays disabled if no governed read-only notification source exists.
- Card-header counts/as-of/context currently styled with the reference `.link` treatment are
  classified individually as static metadata or real actions. Static metadata remains visible to
  assistive technology, has no tab stop/handler and a non-pointer cursor; a blue/pointer treatment
  is reserved for a semantic link/button with a real approved action. Computed cursor, role/name,
  handler presence, and keyboard behavior are contract-tested so an `aria-hidden` pointer-looking
  count cannot masquerade as an action.
- Every live export is bounded and declares its exact population before download. Let `L_direct` be
  the positive direct-export row limit frozen in the API/startup contract. Existing Forecast/
  Inventory/Replenishment buttons that have no reference format modal perform one governed UTF-8
  CSV download from `selected_visible` when at least one still-visible row is selected, otherwise
  from `current_filtered`; pages without selection always use `current_filtered`. Selection is
  current-page-only and clears on filter, scope, authority, sort, or pagination change, so
  `selected_visible` can never contain hidden/off-page IDs. `current_filtered` means the complete
  filtered population across every pagination page, not the current page. For the effective scope,
  `N = 0` disables the button with `No rows available to export`, `1 <= N <= L_direct` is live
  including `N = L_direct`, and `N > L_direct` disables it with
  `Export limit is {L_direct} rows; narrow filters or selection`. Disabled states perform no request
  or download. The server independently recomputes scope, population, and limit and returns a typed
  refusal for stale/tampered IDs or `N > L_direct`; it never silently truncates. These direct buttons
  do not invent a format chooser or claim Excel/PDF readiness. The server response emits exact
  `Content-Type: text/csv; charset=utf-8` and
  `Content-Disposition: attachment; filename="<exact-registry-filename>"` headers, no BOM, LF record
  separators, every field double-quoted with embedded quotes doubled, and no platform-dependent
  newline or terminal record separator after the last row. The client does not construct or rewrite
  CSV bytes; any browser Blob/object URL is a byte-for-byte transport of that attachment response. A
  text field beginning with
  `=`, `+`, `-`, `@`, tab, or carriage return is
  prefixed with one apostrophe before CSV quoting. A governed unavailable cell exports its exact
  visible business reason, never blank or zero. The filename is
  `<prefix>-<authorityShort>-<sourceAsOfUTC:YYYYMMDDTHHmmssZ>.csv`; prefix comes only from the closed
  registry below, authorityShort is the first 12 lowercase hex characters of the active rich
  bundle-manifest SHA-256, and timestamps are UTC. This closed pattern is already ASCII-safe and is
  the `<exact-registry-filename>` used in `Content-Disposition`; no `filename*` parameter or client-
  generated filename is emitted. Response headers, byte order, line endings, row count, and safe
  extension are tested.

  `sourceAsOfUTC` is not derived from the exported row set and there is no JSON envelope around the
  raw CSV attachment. The handler reads it directly as the checked active bundle's one frozen
  source-publication cutoff in UTC; the identical value drives the filename and is repeated in every
  row's `source_as_of` lineage column. `generated_at` is one response-wide UTC RFC 3339 timestamp at whole-second
  precision, frozen after authority/scope validation and before serialization; the same value is
  repeated in every row and never changes during streaming. Older field-level observations retain their own timestamps in registered data/
  detail fields and do not change the filename. If the authority cannot provide one unambiguous
  frozen source-publication cutoff, the export is unavailable rather than choosing row min/max or
  `generated_at`.

  Each direct CSV keeps the registered data columns first and then appends these lineage columns in
  this exact order: `export_scope`, `retailer_id`, `tenant_id`, `environment`, `authority_id`,
  `effective_store_id`, `channel_scope`, `currency`, `source_as_of`, `generated_at`. `export_scope`
  is exactly `selected_visible` or `current_filtered`; the other fields repeat on every row so a
  detached file remains attributable. The registry is closed—changing a source table, prefix, or
  column order is a contract amendment:

| Trigger ID / prefix | Exact source and data-column order before lineage |
|---|---|
| `exportForecastBtn` / `demand-forecast` | Forecast Workbench: `sku_id`, `product_name`, `store`, `channel`, `category`, `horizon_weeks`, `baseline`, `ai_forecast`, `last_actual`, `accuracy`, `bias`, `confidence`, `confidence_state`, `interval_covered_through_horizon`, `interval_withheld_weeks`, `primary_driver`, `data_quality`, `status` |
| `inventoryExportBtn` / `inventory-overview` | Location-Level Inventory Performance: Location, Type, Inventory Value, Availability, Days of Supply, Stock-out Risk, Overstock, Priority Action |
| `storeInventoryExportBtn` / `store-inventory` | Store Inventory Heatmap: Store, Availability, DoS, Overstock, Understock, Action |
| `warehouseExportBtn` / `warehouse-inventory` | Warehouse, Inventory Value, Capacity Utilization, Fill Rate, Blocked Stock, Delayed Receipts, Action |
| `ageingExportBtn` / `inventory-ageing` | SKU / Product, Category, Age, Units, Value, Sell-through, Recommended Action, Priority |
| `transferExportBtn` / `inventory-transfers` | SKU, From Location, To Location, Available Qty, Suggested Qty, Value, Expected Benefit, Status |
| `valuationExportBtn` / `inventory-valuation` | Valuation by Category: Category, Gross Value, NRV, Provision, Variance |
| `expiryExportBtn` / `expiry-waste` | Product, Location, Expiry Window, Units, Value, Sell-through, Recommended Action, Priority |
| `replenishmentExportBtn` / `replenishment-planner` | Priority Replenishment Recommendations, excluding Select: Priority, SKU / Product, Destination, Current Stock, Forecast Demand, Safety Stock, Suggested Qty, Source, Lead Time, Expected Receipt, Order Value, Service Impact, Confidence, Status |
| `suggestedExportBtn` / `suggested-orders` | Order, Type, Destination, Source, Items, Value, Need Date, Confidence, Status |
| `supplierExportBtn` / `supplier-planning` | Supplier, Category, Open PO Value, Capacity, Lead Time, OTD, Risk, Action |
| `safetyStockExportBtn` / `safety-stock` | Policy Segment, SKUs, Service Target, Current Value, Recommended Value, Impact |
| `allocationExportBtn` / `allocation-fulfillment` | Product, Available Pool, Store Demand, Allocated, Shortfall, Allocation Rule, Priority, Status |
| `exceptionExportBtn` / `replenishment-exceptions` | Exception, Order / SKU, Business Impact, Owner, Age, Priority, Recommended Resolution, Status |

- Footer values are either scoped consistently or labelled as enterprise-wide; they load
  independently of the current page.
- At widths ≤1200 use the reference three-column KPI/two-column panel behavior; at ≤1000 compact
  secondary cards; at ≤860 one-column content with a complete mobile navigation; at ≤650 one-column
  mini cards. Modal bounds are `min(720px, 96vw)` and no more than 88vh.
- Add focus-visible treatment. Skip navigation, landmarks, table captions/descriptions, dialog
  labelling, and live-region text are visually hidden except while focused/announced so they do not
  alter reference composition; any new always-visible accessibility copy needs `P5-0P` approval.
  All Phase 5 dialog close paths are safe because no dialog may commit a persistent write; exact
  initial focus, trap, X/Cancel/Close/Escape/backdrop, abort, result/in-place replacement, and focus-return
  behavior follows §8.8.5 rather than an implementation-dependent exception.

### 8.2 Price Recommendations

**Reference title:** `Price Recommendations`

**Reference subtitle:** `AI-generated SKU-level pricing actions with human approval`

The subtitle is presentation reference; Phase 5 must not imply an implemented approval workflow.
The matrix should approve a concise element-level disclosure or status treatment without moving the
subtitle.

#### 8.2.1 Toolbar and filters

Exact action order:

1. selected-row count (`0 selected` initial state);
2. Approve Selected;
3. Send for Review;
4. Schedule Price Change;
5. Compare Selected;
6. Export;
7. Pricing Action Center.

Phase 5 disposition:

- row selection is local and live;
- Compare is read-only and live for selected compatible rows;
- Export is read-only and live with scope/currency/version lineage;
- Pricing Action Center uses the approved preview-only trigger: its original Pending Decisions,
  Value Awaiting Approval, owner, and approval-queue locations show typed workflow-unavailable
  placeholders rather than sample facts, and no queue action exists. It may become data-bearing
  read-only only after an approved amendment redefines every value as a non-workflow policy-risk
  queue;
- Approve Selected, Send for Review, and Schedule Price Change use visibly labelled preview-only
  triggers so their exact forms/options are inspectable; every submit/mutation action remains
  disabled with its workflow prerequisite and no request/write;
- row/detail “Open Simulation” navigates with context and is live;
- no action changes recommendation status/owner or writes audit state.

Exact filter order and reference values:

1. Status: All Statuses, Pending, Under Review, Approved, Scheduled, Rejected;
2. Category: All Categories, Footwear, Apparel, Electronics, Beauty;
3. Store: All Stores, Mumbai, Noida, Bengaluru;
4. Action: All Actions, Increase Price, Reduce Price, Hold Price;
5. Confidence: All Confidence Levels, 90% and above, 80% and above, Below 80%;
6. search placeholder: `Search product, SKU or reason`.

Category/store options become live canonical values while preserving the original option placement;
any changed option list is a data-driven matrix row, not a silent redesign. The confidence filters
use `P5-D21` predicates exactly: 90% and above is `>=90`, 80% and above is cumulative `>=80`, and
Below 80% is `<80`. Mutually exclusive KPI/demo cohorts may split the middle group at `<90`, but
the visible 80% filter must still include rows at 90% and above.

The shared Store and this page Store control cannot express conflicting scopes. When global Store
is `All Stores`, the page Store remains enabled and may narrow the governed option set. When global
Store is specific, the page control stays in its exact position, synchronizes to that canonical ID,
and is disabled with `Set by global Store`; changing the global control clears row selection,
cancels obsolete requests, and resets the page value. Returning global Store to `All Stores`
resets the page Store to `All Stores` before re-enabling it. Requests and cache keys carry one
canonical `effectiveStoreId`, never two intersected labels; an option missing from the new authority
fails visibly instead of creating an accidental filtered-empty view. The same rule is asserted in
summary/table/tab/detail/export counts and browser back/forward restoration.

Workflow status may be unavailable in Phase 5. If so, keep the filter position disabled or define a
separate artifact evidence-status vocabulary through an approved matrix amendment; do not map model
acceptance to approval status silently. Every enabled filter updates KPIs, cards, tabs, table,
selection, detail availability, and export scope.

#### 8.2.1.1 Price Recommendations export contract

The reference export modal is fully demoable and has these closed behaviors:

- Scope remains Selected recommendations (`N`), Current filtered view (`N`), All recommendations
  (`N`) in that order. Let `L` be the positive server limit frozen in the API/startup contract. Each
  scope is eligible exactly when `1 ≤ N ≤ L`: `N = 0` is disabled, `N = L` remains live, and `N > L`
  is disabled with `Export limit is L rows; narrow filters or selection`. Current filtered counts the
  whole filtered result set, not merely the current pagination page. The modal defaults to the first
  eligible scope, recomputes every count/limit state under each filter/Store/Channel/authority change,
  and disables Export when no scope is eligible. The server repeats the same boundary and returns a
  typed refusal for any stale/tampered `N > L` request. Every scope contains only
  `recordKind = recommendation`; `withheld_assessment`, rejected/insufficient assessment, and
  historical/superseded rows are excluded even when they appear in the workbench's Manual review
  presentation. Selected exports the still-visible selected recommendation IDs. Current filtered
  applies Status, Category, Action, Confidence, Search, and every enabled page-table filter. All
  recommendations bypasses only those five named table filters; it still binds the reviewed local
  server authority, retailer/tenant/environment, `effectiveStoreId`, global Channel, currency disposition,
  and server limit. It never means all tenants, all stores outside `effectiveStoreId`, all channels
  outside global scope, or all assessed rows.
- Format remains CSV, Excel-compatible CSV, PDF / Print in that order. CSV is live as UTF-8 without
  BOM, RFC-4180 field escaping with every field double-quoted, embedded quotes doubled, and LF record
  separators; Excel-compatible CSV is live as UTF-8 with BOM and CRLF using identical quoting,
  columns, rows, units, and lineage. Neither format writes a terminal record separator after its
  final row. PDF / Print remains visible/natively disabled with the accessible reason
  `Governed print/PDF renderer not available` and makes no print dialog, API call, or download. It may
  become live only through an approved renderer/composition amendment. The controlled Format default
  is CSV, exactly as in the reference.
- Include AI explanation Yes/No is live only for the governed explanation field, defaults to Yes as
  in the reference, and never injects sample prose. Include audit history defaults to No; Yes remains
  visible-disabled until a governed audit dataset/API exists. Disabled choices do not enter query/
  cache keys.
- Both live formats freeze the original table's non-selection columns first in this exact order:
  Priority, SKU / Product, Category, Store, Action, Current, AI Price, Change, Competitor, Stock
  Cover, Forecast Demand, Current Margin, Expected Margin, Revenue Impact, Margin Impact, AI Reason,
  Confidence, Status, Owner. Channel remains the approved secondary line in Store for visible parity,
  and is also exported canonically in lineage. `Include AI explanation = No` retains the AI Reason
  header in place but writes an empty quoted field; it never changes later column positions. After
  Owner, append lineage in this exact order: `export_scope`, `record_id`, `selection_id`, `run_id`,
  `retailer_id`, `tenant_id`, `environment`, `authority_id`, `effective_store_id`, `channel_id`,
  `currency`, `source_as_of`, `generated_at`. `source_as_of` is exactly the checked authority's frozen
  source-publication cutoff used by §8.1 and is constant for the response. `generated_at` is computed
  once after authority/scope validation and before serialization as UTC RFC 3339 at whole-second
  precision, then repeated unchanged in every row. No audit columns exist while audit Yes is disabled.
- File Name is a controlled local basename with default `price_recommendations`, length 1–80, no
  path separators/control characters/dot segments/reserved device names, and only ASCII letters,
  digits, spaces, `_`, `-`, and `.`; trim outer whitespace, collapse internal whitespace to `_`, and
  append exactly one `.csv` extension for either live format. Invalid input disables Export with
  field-level help; the server independently applies the same validator/normalizer and returns a typed
  422 rather than silently choosing a different name.
- Selected/current/all requests carry the exact IDs or canonical filters plus authority, effective
  Store, Channel, currency, sort, and bounded row limit. The response count and ordered rows match
  the modal count and the selected or bounded filtered/all API population—not only the current page;
  stale authority returns 409, missing authority 503, limit excess a typed refusal, and cancellation
  creates no partial download.
- Both successful formats are attachment responses authored by the server, not CSV assembled by
  React. CSV returns exact `Content-Type: text/csv; charset=utf-8`; Excel-compatible CSV returns the
  same exact media type because it is CSV rather than XLSX. Both return exact
  `Content-Disposition: attachment; filename="<normalized-basename>.csv"` with no `filename*`
  parameter. Any client Blob/object URL is only a byte-for-byte transport of the server bytes and
  cannot alter BOM, line endings, quoting, filename, or lineage.
- Every text cell beginning with `=`, `+`, `-`, `@`, tab, or carriage return is neutralized for
  spreadsheet safety. Tests cover quotes, commas, CR/LF, Unicode currency/product text, BOM/no-BOM,
  line endings, explanation on/off, zero/one/many rows, extension handling, response media type,
  `Content-Disposition`, lineage columns, and exact modal focus/keyboard behavior.

#### 8.2.2 KPI row

Exact five-card order:

| KPI | Phase 5 definition/disposition |
|---|---|
| Open Recommendations | Count only current filtered `recordKind = recommendation` rows (Increase, Reduce, and Hold); exclude withheld assessments and historical/superseded rows; do not claim approval state |
| Revenue Opportunity | Sum of model-implied local revenue impact over assessed available rows; reporting conversion only for approved aggregate display |
| Margin Opportunity | Sum only over client-actual-cost-capable primary rows with assessed/available coverage; generated PoC cost cannot populate it and exposes `COST_NOT_CLIENT_ACTUAL`; unavailable if no qualifying rows, never zero by substitution |
| Recommendations at Risk | Frozen deduplicated count only of `recordKind = recommendation` rows carrying an approved non-blocking warning; exact reason breakdown required. Hard guard/protection/conflict/missing-input failures are withheld assessments in Manual review and the separately labelled At Risk waterfall, never this recommendation-labelled KPI. Exact zero is expected if no non-blocking warning enum is approved |
| Recommendation Adoption | Workflow/realized metric; unavailable until Phase 6 evidence exists |

KPI denominator, horizon, scope, local/reporting currency, and as-of are displayed or available in
details. “Open” must not imply workflow state unless that state actually exists.
Every KPI's secondary delta/note is also a matrix row: high-priority count and distinct stores/
channels; projected revenue percentage; margin-point potential; outside-guardrail/prerequisite
copy; adoption target. Workflow phrases such as `Require senior approval` and `Target: 80%` remain
unavailable or receive approved business-prerequisite copy rather than sample text.

#### 8.2.3 Summary cards

Exact card order:

1. **Recommendation Mix** — exact row labels Increase price, Reduce price, Hold price, Manual
   review. In Phase 5, Manual review counts non-actionable withheld/risk rows under a frozen reason
   mapping and does not imply an assigned reviewer. The first three rows reconcile to Open
   Recommendations; Manual review is a separate workbench population and is not added to that KPI.
   Because Confidence is the hard sign gate, every row in the first three action groups is
   necessarily ≥90%; middle/low confidence can occur only in Manual review. Preserve the exact
   visible label unless amended.
2. **Business Value by Driver** (`Projected`) — exact row labels Demand-led increases, Markdown
   optimization, Competitor response, Inventory clearance, Margin protection. Each driver requires
   a deterministic explanation code; margin protection is
   client-actual-cost-conditional and promotion/markdown drivers require admitted evidence.
3. **Approval Pipeline** (`This week`) — retain exact visual placement but render governed workflow unavailable
   unless source workflow facts already exist. Exact row labels remain Pending analyst review,
   Pending category manager, Pending finance approval, Approved, not scheduled, Scheduled for
   publishing. Do not populate sample stage counts.

`Recommendation Mix` retains the `Current filtered view` context label. Each context label is a
matrix row and becomes capability-sensitive if its original claim is not supportable.

The exact callout heading is `AI recommendation logic`. Its original text about demand, cost,
competitors, promotions, inventory, and customer response
must be capability-sensitive. It cannot claim customer response, cost, or promotion inputs where
the current filtered population lacks them.

#### 8.2.4 Tabs

Exact order: Overview, Store View, Category View, Governance.

**Overview — Pricing Opportunity Waterfall** (`Projected annualized impact`)

- Revenue: live model-implied aggregate where response/forecast/price pass.
- Margin: client-actual-cost-conditional with assessed coverage; the synthetic scenario is separate.
- Markdown: live only with accepted markdown/promotion policy.
- Inventory: live only with accepted Phase 4 context and frozen formula.
- At Risk: frozen withheld/risk definition.

The waterfall must define a common baseline, avoid adding overlapping effects, expose local/
reporting currency, and render unavailable segments without rescaling them as zero.

**Overview — Pricing Decision Quality** (`Current model`)

- score ring: formula must be frozen; replace both the HTML's hard-coded `82` conic-gradient stop
  and pseudo-element content with one DOM/CSS-custom-property value from the API, plus text,
  computed-style, and screenshot assertions;
- High confidence: numerator is filtered assessed workbench rows at `>=90%`; denominator is all
  filtered assessed workbench rows, not recommendations, because every recommendation already
  passed the same ≥90% hard gate;
- Within margin guardrail: client-actual-cost-capable assessed/available count;
- Predicted vs realized: unavailable without compatible realized-history evidence;
- Needing override: workflow unavailable unless defined as a non-workflow policy exception via
  approved amendment.

**Overview — decision cards**

- Margin Protection: high-demand/low-stock with client-actual cost and competitor context where available;
- Markdown Optimization: accepted markdown/promotion evidence only;
- Inventory Clearance: accepted ageing, seasonality, transfer, and local price guards.

**Store View**

Title: `Store-Level Pricing Performance`; action: `Open Store Drilldown`.

Exact table columns: Store, Recommendations, Approval Rate, Revenue Opportunity, Margin
Opportunity, Risk, Priority Action. Recommendations/revenue/risk/action can be Phase 5; margin is
client-actual-cost-conditional; Approval Rate is workflow/realized and remains unavailable. Priority Action must
use a frozen deterministic rule.

Read-only drilldown preserves Store and Period controls; Open Recommendations, Revenue Opportunity,
Margin Opportunity; Top Pricing Issues rows (overpriced vs competitor, underpriced high-demand,
ageing markdowns, promotion conflicts); Recommended Actions (approve price increases, reduce
targeted prices, clear ageing stock); and Open Store Recommendations. Wording/actions that imply
mutation are disabled or navigate only.

**Category View**

Exact table columns: Category, Revenue Uplift, Margin Uplift, Elasticity, Recommendation.
“Uplift” is displayed as model-implied change unless causal evidence is separately approved.
Elasticity includes accepted-series coverage and reasons; Low/Medium/High labels require frozen
thresholds.

Exact opportunity matrix tiles: High demand / Low stock, High stock / Low demand, Competitor
opportunity, Promotion conflict.

**Governance**

Approval SLA table columns: Approval Level, Open, Average Age, SLA, Status. Levels/values are Phase
6 workflow data and remain unavailable in Phase 5.

Audit & Control Coverage elements remain ordered: Recommendations with AI explanation; Price
changes with approval trail; Published prices with rollback record; Guardrail exceptions
documented; Model/version traceability. Phase 5 can populate explanation, guardrail-exception, and
model/version coverage; approval/published rollback stay unavailable.

#### 8.2.5 SKU-level recommendations table

Exact 20-column order:

1. Select
2. Priority
3. SKU / Product
4. Category
5. Store
6. Action
7. Current
8. AI Price
9. Change
10. Competitor
11. Stock Cover
12. Forecast Demand
13. Current Margin
14. Expected Margin
15. Revenue Impact
16. Margin Impact
17. AI Reason
18. Confidence
19. Status
20. Owner

Required binding details:

- each live row identity is SKU × store × channel. Because the reference table has no Channel
  column, `P5-3` must approve one presentation without adding/reordering columns: recommended is a
  secondary channel line inside the Store cell. Under All Channels, channel-distinct rows remain
  distinct; summaries may aggregate with disclosed denominators. An alternative may require a
  single channel selection before rows load. Silent channel collapse is forbidden;
- Current and AI Price are local operating-currency prices and never reporting-FX converted;
- Change is computed from unrounded canonical minor units and formatted consistently;
- Competitor includes match/freshness availability and is unavailable when inadmissible;
- Stock Cover states horizon and denominator;
- Forecast Demand states horizon/scenario and consumed forecast version;
- Forecast Demand preserves the reference categorical High/Medium/Low format. Recommended thresholds
  are market × department × horizon P50-unit percentiles: Low below the 33rd percentile, Medium from
  the 33rd to below the 67th, High at/above the 67th; `P5-1P` freezes the population, ties, sparse/
  missing behavior, and boundary vectors before generation;
- Current/Expected Margin and Margin Impact on the primary table are independently client-actual-
  cost-capable; generated PoC cost appears only in a separately labelled synthetic scenario while
  primary fields retain `COST_NOT_CLIENT_ACTUAL`;
- Revenue Impact is model-implied and carries horizon;
- AI Reason maps frozen explanation codes, not generated unsupported prose;
- Confidence maps `P5-D21` price-response confidence, not competitor-match or promotion confidence;
- a `withheld_assessment` retains product/category/store/channel identity, confidence, and stable
  evidence reasons, but is non-selectable for action and has no Action, AI Price, Change, Revenue
  Impact, Margin Impact, Current Margin, or Expected Margin unless an individual fact is
  independently available. It is never labelled Hold, appears under All Actions only, and cannot
  appear under Increase Price, Reduce Price, or Hold Price;
- Status and Owner remain in place but unavailable until workflow evidence exists.

Rows must demonstrate Increase, Decrease, Hold; High/Medium/Low priority; numeric confidence in the
exact ≥90%, 80–<90%, and <80% demo cohorts while preserving the cumulative visible ≥80% filter; margin
available/unavailable; competitor used/excluded; policy-valid/withheld/protected; INR/USD; rich/
sparse without copying original sample products or values.

Row detail modal: Product, Recommended Action, Confidence, Commercial Impact, Decision Context, explanation,
lineage/capability, and Open Simulation. It is read-only, deep-linkable where approved, keyboard
accessible, and uses the selected row's live identity. For a `withheld_assessment`, Recommended
Action and dependent impact fields remain unavailable, evidence reasons remain readable, and Open
Simulation is natively disabled because no accepted response/recommendation context exists.

#### 8.2.6 Bottom cards and modal inventory

`Price Elasticity & Scenario Insight` (`Selected portfolio`) exact columns: Scenario, Avg Price
Change, Demand Impact, Revenue Impact, Margin Impact. Original rows: Current approved plan, AI optimized plan,
Conservative plan. “Current approved plan” is unavailable unless Phase 6 produces it; the matrix may
approve “Current price baseline” as a truthful clarification while retaining layout.

`Pricing Risk & Governance` (`Exceptions`) preserves: Below minimum margin; Price change above 10%; Low-confidence
recommendation; Promotion conflict; Protected / strategic product. The 10% row can show rejected or
manual proposals only because active Phase 5 recommendations are capped at 5%.

Every original modal surface is included in the matrix even when disabled:

- Approve summary: selected products/stores, average/max change, revenue impact, exceptions,
  effective date, note, confirm;
- Send for Review: count/status, reviewer, priority, due date, reason, comments;
- Export: scope, format, explanation/audit options, file name;
- Schedule: date, time, channels, rollback rule;
- Compare: Product, Action, Price Change, Revenue Impact, Margin Impact, Confidence;
- Pricing Action Center: Pending Decisions, High Priority, Value Awaiting Approval, owners, and
  decision/approval queues.

Only Compare Selected and lineage-bearing Export are `business_live`/`read_only` actions in Phase 5.
Approve Selected, Send for Review, Schedule Price Change, and Pricing Action Center remain unavailable
as business actions but their explicitly labelled `Preview only` triggers are clickable presentation
surrogates under `P5-D13`; their dialog fields are read-only or local-only enumerations, every submit
is hard-disabled, and no request/write/history/audit effect occurs. A `hard_disabled` trigger has no
handler and opens nothing; it must never be confused with a `preview_only` trigger.

The recommendation table header count (`5 recommendations` in the reference) is a live filtered
recommendation-only count. When withheld assessments share the table, the approved adjacent
`M manual review` count explains the additional rows without calling them recommendations. The
original demo note about approve/review/compare/schedule is also a matrix row and must
be amended to explain selection, compare, export, detail, and disabled workflow without suggesting
that approval/scheduling is available.

### 8.3 Price Simulation

**Reference title:** `Price Simulation`

**Reference subtitle:** `Test price scenarios before applying them`

“Applying” is not implemented in Phase 5. The results are stateless and non-mutating.

#### 8.3.1 Scenario Builder

Preserve the exact card header first: `Price Scenario Builder` with `Run Simulation` as the header
action. The form then has exactly eight fields in this order:

1. **Product** — searchable governed SKU/product identity; dependent on authority/Store-derived
   market plus applicable Store/Channel scope; no new visible Market control.
2. **Current Price** — read-only accepted current local price with as-of/freshness.
3. **Proposed Price** — editable local-currency input; validate precision, range, local grid/ending,
   positive value, and maximum change.
4. **Simulation Period** — reference option is only Next 4 Weeks. Additional horizons require an
   approved parity amendment and must map to available forecast/interval capability.
5. **Minimum Margin** — local policy value; the primary guard is disabled/unavailable without
   accepted client-actual cost-as-of. Generated cost may be calculated only in the isolated,
   visibly labelled synthetic scenario and cannot constrain the primary recommendation.
6. **Competitor Response** — the reference option is only Include, so Phase 5 treats this location
   as a non-editable evidence status rather than an enabled one-option control. With an admissible
   fresh match it remains natively disabled showing `Include` plus an accessible as-of/confidence
   description. When the engine excludes missing, stale, or inadmissible evidence, the same location
   instead shows one selected disabled option `Not included — <business reason>` tied to the response
   reason; it must never continue to display Include. Adding a user-selectable Exclude option
   requires a separate parity/request amendment.
7. **Demand Assumption** — Expected, Best Case, Worst Case.
8. **Inventory Objective** — Margin Protection, Clearance; primary Margin Protection requires
   accepted client-actual cost, while Clearance requires accepted ageing/inventory context.

The original Product control is an ordinary select. Making it searchable is an explicit behavior/
parity amendment that must be approved in the `P5-3` Price Simulation matrix; without that approval it remains the original
select with governed dependent options. The original Current Price control appears editable.
Making it read-only is also an explicit behavior/parity amendment, recommended because the value is
an authority-sourced baseline rather than a scenario input. Its disabled/read-only styling must
still match the approved original-element treatment.

`Run Simulation` is enabled only when required inputs validate and invokes the stateless endpoint
from its original header position.

The global scope supplies authority/Store-derived market plus Store/Channel context, but the chosen Product must still bind one
unambiguous priced series. Changing any upstream selector clears obsolete results and cancels an
in-flight request.

Required field states include pristine, loading dependent options, valid, invalid numeric,
off-grid, disallowed ending, outside observed support, over 5% change, stale current price, missing
response, missing forecast, missing cost, missing/stale competitor, and unsupported horizon.

#### 8.3.2 Scenario Comparison

Exact columns: Measure, Current, Proposed, AI Optimal.

Exact rows:

- Units;
- Revenue;
- Gross Margin;
- Ending Stock.

Definitions:

- Current is the accepted price baseline at the same origin/horizon;
- Proposed uses the user's validated stateless input;
- AI Optimal uses the accepted Phase 5 recommendation under the same scope;
- Units are model-implied, not causal;
- Revenue is local operating currency unless an additional explicitly labelled reporting display is
  approved;
- Gross Margin in the primary comparison is element-level unavailable without client-actual cost;
  generated cost may populate only a separately labelled synthetic scenario and cannot change AI
  Optimal or the primary recommendation;
- Ending Stock consumes the accepted inventory position and forecast scenario and cannot imply
  replay-validated service.

Columns remain visible if one metric is unavailable. Do not collapse unavailable Gross Margin and
do not substitute zero.

The generated-cost demonstration requires one explicit presentation amendment and no other
location. Inside the `Scenario Comparison` card, immediately **after** the exact four-row table and
before the `AI Recommendation` card, add a visually separate compact panel headed `Synthetic demo
margin — not client actual`. In Current, Proposed, AI Optimal order, it shows only the synthetic
gross-margin values/units produced from the same scenario, then computed-WAC provenance, cost as-of,
and `Does not affect the recommendation`. It is bound to the
`synthetic_margin_scenario` discriminator and its own response fields. It never changes the eight
builder fields, the primary Gross Margin row, the primary four result metrics, AI Optimal price,
guardrails, or ranks. It is absent—not silently merged—when the response carries no synthetic
scenario; the primary margin location still shows its client-cost reason. Without approval of this
exact new position/order/copy, generated-cost values remain API/detail evidence only and cannot be
claimed as a live visual Demo 5 state.

#### 8.3.3 Recommendation panel and result modal

Preserve the recommended-price callout and explanation area. Replace the hard-coded reference price
with live local price. Exact metric order: Revenue, Margin, Stock-out Risk, Confidence.

- Revenue: proposed/recommended model-implied change over selected horizon;
- Margin: client-actual-cost-conditional in the primary result; synthetic margin is separate and
  visibly labelled;
- Stock-out Risk: accepted forecast/inventory definition with interval availability disclosed;
- Confidence: the selected series' `P5-D21` price-response confidence; it is not a scenario-success
  probability, competitor-match confidence, or promotion confidence.

The `competitor excluded` demo state means the simulation automatically excludes a stale,
inadmissible, or missing competitor observation and explains why. The field display, accessible
description, request input echo, and result reason must all say not included; a response is rejected
if the visible field still says Include. It is not a user-selectable Exclude option. Adding an
Include/Exclude choice requires the approved parity amendment identified in §8.3.1 and a versioned
request contract.

The original result modal contains the four metrics and recommendation callout. Adding visible input
echo, assumptions, policy checks, or lineage requires an approved modal amendment; otherwise those
details remain accessible metadata or export/detail content without changing the modal composition.
It adds no save/apply control. Required live examples cover Expected/Best/Worst,
Current/Proposed/AI Optimal, client margin available/unavailable and the separately labelled
§8.3.2 synthetic-margin panel, valid/invalid, low/high stock risk,
competitor included/excluded/stale, INR/USD, and active-rich/naturally-sparse behavior. Full-sparse
refusal is proven separately by the non-active API integration harness.

### 8.4 Competitor Monitor

**Reference title:** `Competitor Monitor`

**Reference subtitle:** `Track market prices, promotions and availability`

#### 8.4.1 Toolbar and filters

Exact action order:

1. Add Competitor;
2. Create Alert Rule;
3. Review Matches;
4. Match Status filter;
5. product/competitor search.

Match Status options: All Match Statuses, Matched, Needs Review, Rejected. “No Match” must also be
representable in data/detail and may be added to the filter only through an approved amendment.

Add Competitor and Create Alert Rule mutations remain disabled in Phase 5. The `P5-3` matrix must
approve `Review Matches` as the reference-labelled **read-only inspection queue** defined in
§8.4.3; it never accepts, rejects, relinks, comments, or writes. If that wording amendment is not
approved, the button and all table selection controls are natively disabled with one shared
accessible reason rather than left interactive/inert.

#### 8.4.2 KPIs and callout

Exact five-card order:

1. Products Monitored — distinct in-scope retailer products with an assessed competitor source;
2. Above Market — current local price above an admissible fresh competitor price under frozen
   tolerance;
3. Below Market — corresponding below-market count;
4. Competitor Out of Stock — fresh admissible competitor availability OOS count;
5. Matches Needing Review — assessed match records in review status.

All KPI denominators respond to authority/Store-derived market context, the shared Store/Channel
controls, plus the page's Match
Status and search filters, or are explicitly labelled otherwise. The original page has no Category
filter; adding one requires an approved parity amendment. The callout explains that competitor context is combined with
matching confidence, freshness, local price guards, optional margin, and inventory; it must not
promise automatic response.

#### 8.4.3 Match table

Exact 12-column order:

1. Select
2. Our Product
3. Competitor
4. Matched Product
5. Our Price
6. Competitor Price
7. Difference
8. Availability
9. Last Updated
10. Match Confidence
11. Match Status
12. Recommended Response

The Phase 5 selection contract is local and read-only. Each row checkbox selects that visible row
for the inspection queue; the header checkbox selects only current-filter-visible rows and exposes
checked/unchecked/indeterminate states. With selected rows, `Review Matches` opens them in current
visible table order. With zero selected, it opens the visible `Needs Review` rows in table order;
if none exist it is natively disabled with an accessible reason. Search, status, authority, Store,
Channel, page, or pagination changes clear all selection before new results render; selection never
survives as hidden state. `Review Matches` opens the first queued row and shows the original
`Review item` position/count. The reference modal has no Previous or Next control, so Phase 5 does
not invent one: because the original auto-advance occurs only after Accept/Reject mutations, the
preview closes with Cancel and the user selects another row to inspect it. Every Accept/Reject/
Comment/Save control remains present but disabled; Link performs only the in-place preview state
defined in §8.8.3. Selection creates no request, URL, export scope, audit event, or server state.
Tests cover zero/one/many, select-all-visible, indeterminate, filter reset, empty eligible queue,
exact footer order, absent Previous/Next controls, keyboard labels, and no mutation handler.

Bindings:

- both prices show comparable operating currency/unit; original value/currency is available in
  detail when normalization was required;
- Difference states direction and denominator;
- Availability enum includes In Stock, Low Stock, Out of Stock, Unknown/Stale;
- Last Updated uses a real observed time and accessible absolute timestamp, not only “minutes ago”;
- Match Confidence is distinct from price-response confidence;
- Match Status uses frozen enum-to-label/color mapping;
- Recommended Response is rule-bounded context and carries Included/Excluded/Unavailable reason.

Live rich data covers Matched, Needs Review, Rejected, No Match; In Stock, Low Stock, OOS, Unknown;
fresh and stale; high/boundary/low confidence; above/below/equal; response Hold/Increase/Decrease/
Validate/No action. Sparse/no-source states preserve the table structure.

`Competitor Product Matches` retains a live filtered count in the exact `N matches` position
(`5 matches` is reference-only). The original note stating that Review Matches can
accept/reject/relink
is a matrix row and must be amended to describe the Phase 5 read-only detail flow and disabled
mutations.

#### 8.4.4 Alert rules and Match Quality Summary

`Active Alert Rules` retains its `N active` context (`3 active` is reference-only) and exact columns:
Rule, Trigger, Scope, Recipients, Status. Display source-backed
configured rules read-only if they exist. If they do not, keep the card and render governed
unavailable; never copy the three HTML samples into production.

`Match Quality Summary` exact metrics: Auto-Accepted, Manual Review, Rejected, Average Confidence.
The summary callout states that low-confidence matches remain under review and cannot trigger
pricing response.

#### 8.4.5 Modal/detail surfaces

The Add Competitor form positions remain documented: Name, Type, Country/Region, URL, Data
Collection Method, Refresh Frequency, Categories, Currency, Notes, validation callout. Creation/
submission remains disabled; the approved §8.8 preview-only trigger is the sole live access path.
The `Approved Web Collection` option conflicts with no-scraping policy and must be
kept in its exact reference position but natively disabled/annotated with the approved legal-source
reason; it cannot be selected or submitted. Removal requires a separate approved parity amendment.

The Alert Rule form positions remain documented: Name, Trigger Type, Threshold, Comparison
Direction, Category Scope, Competitor Scope, Severity, Notify, Frequency, Recommended Action,
Description. It remains disabled.

The read-only Match Detail/Review workspace uses the richer original intent, subject to matrix
approval: our product and competitor product cards; brand/model/variant; price/availability;
brand, model number, title, category, colour, size, capacity, pack quantity, GTIN/UPC/EAN and image
comparison; confidence components; status; source/as-of. Reviewer Comment, Accept, Reject, Link
Different Product, alternate search, and Save New Match remain disabled. The later simplified HTML
handler is not behavioral authority.

### 8.5 Promotion Planner

**Reference title:** `Promotion Planner`

**Reference subtitle:** `Plan, simulate and optimize retail promotions`

Every live/result-bearing behavior in this section additionally requires the formal `P5-D23`
amendment. Without it, the exact composition remains visible only through governed
`NO_ORIGIN_VISIBLE_PROMOTION_PLAN` states.

#### 8.5.1 Toolbar and filters

Exact order:

1. Create Promotion;
2. Simulate Promotion;
3. Promotion Calendar;
4. Status filter;
5. Category filter;
6. promotion search.

Status options: All Statuses, Draft, Under Review, Approved, Live, Completed. Status is live only if
the dedicated source-native lifecycle field provides it; Phase 5 does not mutate it. The current
`historical | active` status cannot be mapped to Completed/Live. If the lifecycle field is absent,
the filter remains in place but is governed unavailable. Original Category options include
Footwear, Beauty, Electronics, Apparel; live options derive from canonical categories while
preserving placement/order expectations through the matrix.

Promotion creation/submission is disabled; the approved §8.8 preview-only trigger is the sole live
access path to that form. Simulate Promotion is stateless/live only when `P5-D23`, `P5-D20`, and `P5-D22`
are approved and the selected model/scope passes every acceptance gate; otherwise the control remains in its
exact position, natively disabled with the stable evidence prerequisite, and only the distinct local
Preview Results path may open the unavailable result composition. Promotion Calendar Month View and
month selection are read-only/live; List View stays visible/natively disabled with `Governed list-view
composition not approved`, no handler, and no active styling. Search/status/category update every affected KPI,
performance, opportunity, portfolio, readiness, targeting, risk, and calendar element, including
unavailable-state denominators.

#### 8.5.2 KPI row and callout

Exact five-card order:

1. Active Promotions — current valid-time active source plans;
2. Projected Revenue Uplift — available only for accepted `P5-D20` rows; display as model-implied
   revenue change, not causal uplift, with eligible coverage; otherwise unavailable;
3. Projected Margin Impact — available only for accepted `P5-D20` rows with client-actual cost and
   coverage. Generated PoC cost cannot populate this primary KPI;
4. Required Promotional Stock — available only from an accepted demand projection or an
   independently governed source requirement, with unit requirement and readiness coverage;
   otherwise unavailable;
5. Promotions Needing Review — unavailable in Phase 5 because no workflow-review authority exists.
   Do not repurpose model/policy risk or source status to populate it. Source `Under Review` remains
   a portfolio/filter fact, while model/policy risk remains in its separate risk surface. The
   original secondary `2 high risk` value is also unavailable rather than inferred.

The callout may always describe permitted product/depth, conflicts, descriptive aggregate segment scope, and
evidence readiness. It may describe projected demand/revenue, required stock, and client margin
only when their individual accepted capabilities pass. Generated-cost margin is unavailable here
with `COST_NOT_CLIENT_ACTUAL` and appears only in the Price Simulation §8.3.2 synthetic panel. The
callout must not claim live cannibalisation, bundle, or customer-level response under Decision #19.

#### 8.5.3 Promotion Performance Forecast

Header context remains `Next 30 days` where the selected horizon supports it.

Exact metric locations:

- Baseline Revenue;
- Promoted Revenue;
- Incremental Margin;
- Cannibalisation Risk.

Cannibalisation Risk remains present as `Not available — privacy-approved basket evidence required`.
Baseline/Promoted Revenue are model-implied and origin-safe only when `P5-D20` passes; Incremental
Margin additionally requires client-actual cost. If the model is unapproved or fails, all three
numeric locations remain present and unavailable. Generated cost cannot populate this primary
chart or any Promotion Planner secondary result; its only UI output is the Price Simulation §8.3.2
synthetic panel.

Preserve the four-bar visual locations and inside labels Baseline, Optimized, Current Plan, Best Case.
Under the approved `P5-D18` clarification, replace the misleading four bottom labels Revenue, Demand,
Margin, Sell-through with the single centered caption
`Normalized portfolio outcome index (Baseline = 100)`. Render the preregistered index only when its
required `P5-D20` branch/components pass. If a scenario is unavailable, preserve its bar location
with the reason-coded unavailable treatment rather than a placeholder height. The directly associated
accessible table exposes every scenario's native-unit Revenue, Demand, Margin, Sell-through,
availability reason, and index; do not bind unrelated numbers merely to reproduce the reference
heights.

#### 8.5.4 Promotion Opportunities

The exact heading is `AI Promotion Opportunities` with a live `N recommendations` context count
(`8 recommendations` is reference-only). Exact columns: Opportunity, Reason, Expected Value,
Priority.

Permitted opportunities include discount-depth adjustment, excluding a protected product,
inventory-aligned clearance, or conflict resolution. Aggregate-segment targeting, bundle, and
customer-specific examples remain privacy unavailable. Numeric Expected Value is populated only
for accepted `P5-D20` rows, states revenue/client-actual local margin/units explicitly, and does not
combine currencies. Otherwise the descriptive opportunity may remain but Expected Value is
unavailable; generated-cost value cannot populate the primary column.

#### 8.5.5 Promotion Portfolio

The header retains a live `N promotions` count (`5 promotions` is reference-only).

Exact 13-column order:

1. Promotion
2. Category
3. Period
4. Stores / Channels
5. Products
6. Offer
7. Expected Demand Uplift
8. Revenue Uplift
9. Margin Impact
10. Required Stock
11. Cannibalisation Risk
12. Status
13. Owner

Bindings:

- Period uses market-local valid time and accessible dates;
- scope preserves AND/OR rows and shows summarized scope with detail;
- Product count and offer resolve precedence/conflicts;
- “Uplift” labels require adjacent model-implied disclosure unless renamed by amendment and remain
  unavailable unless `P5-D20` passes for that row;
- Margin Impact additionally requires client-actual cost; generated cost stays unavailable across
  Promotion Planner and is never a portfolio or modal value;
- Required Stock reconciles to inventory readiness only when an accepted demand projection or an
  independently governed source requirement exists;
- Cannibalisation remains privacy unavailable;
- Status may be source-live/read-only;
- Owner is workflow unavailable unless a real source field exists and is explicitly governed.

Rich data should cover source statuses without fabricating approval workflow; sparse data produces
reason-coded unavailable forecasts while current descriptive plan rows may remain visible.
After `P5-D23`, the rich profile's required source-lifecycle examples are Draft, Under Review,
Approved, Live, and Completed. Without the dedicated source field, those values remain unavailable
and the current `historical | active` field is shown only under its own truthful label/detail.

#### 8.5.6 Bottom cards

Exact card/metric order:

1. **Inventory Readiness** — Fully available, Transfer required, Replenishment required, At-risk
   promotions. Live from the pinned inventory bundle only when joined to an accepted model-derived
   or independently governed source stock requirement; otherwise the four locations are
   unavailable rather than inferred from current stock alone.
2. **Audience Targeting** — Loyalty members, High-value customers, Lapsed customers, Broad
   audience. The title is presentation authority, but Phase 5 binds this card to descriptive
   aggregate audience composition only—not response, offer selection, recommendation, or targeting.
   Publish percentages with a defined eligible-population denominator and exact 100%
   reconciliation (plus rounding-remainder rule); counts may appear only in approved detail.
   Suppress small-cell or customer-identifying output per privacy contract.
3. **Approval & Risk** — Within margin guardrail, Finance review required, Insufficient stock,
   Promotion conflict. Margin uses only client-actual cost; Finance review is workflow conditional;
   insufficient stock requires an accepted/governed requirement, while conflicts can be live policy
   risks.

#### 8.5.7 Promotion modal surfaces

Create Promotion form positions remain in the matrix: Promotion Name, Objective, Type, Discount/
Offer, Category, Product Scope, dates, Stores/Channels, Customer Segment, Minimum Margin, Approval
Route, Business Rationale, validation callout, Create Draft. Creation is disabled; Bundle/BOGO and
Loyalty Member Price/segment-specific customer options are privacy-disabled; Approval Route is
workflow-disabled.

Promotion Simulation preserves: Promotion, Scenario (Expected/Best/Worst), Discount Depth, Duration
(3/7/14 Days), Store Scope, Customer Segment, Include Cannibalisation, Include Competitor Response,
Run Simulation. Customer Segment is fixed to All Customers; Loyalty Members and High-Value
Customers remain visible but disabled because descriptive aggregate mix is not a response model or
targeting authority. Cannibalisation control/result is visible but disabled/unavailable. Competitor
response requires fresh admissible match. When `P5-D23`, `P5-D20`, and `P5-D22` are accepted, results preserve Expected
Demand Uplift, Revenue Uplift, Gross Margin Impact, Required Stock, Sell-through Improvement,
Cannibalisation Risk; Current Plan versus AI Optimized rows for Discount, Revenue, Margin, Ending
Stock; recommendation, readiness, conflict, and Confidence. Confidence uses `P5-D22` only; it is
never copied from price-response or competitor-match confidence. Primary Gross Margin requires
client-actual cost; generated cost leaves Gross Margin and every promotion result reason-coded
unavailable and appears only in the Price Simulation §8.3.2 synthetic panel. If
`P5-D23`, `P5-D20`, or `P5-D22` is unapproved or fails, Run Simulation is disabled and every result location/modal is
available to parity tests only as a governed unavailable state. No result persists.

Promotion Calendar preserves Month View, List View, month selector, the literal weekday headings
`Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`, `Sun` in that order, the 35-cell grid, promotion
badges, and overlap/category/inventory/customer-fatigue callout. Month View retains the original
primary/active styling and is the only live view; List View remains in its original position but is
natively disabled with the reason above because the reference defines no list body. Month selection
retains Month View and fetches valid source plans; focus stays on the selector after render. No list
table, row, empty state, selector retention, or focus behavior is invented. Customer-fatigue output remains privacy unavailable
throughout Phase 5. Making it live requires reopening `P5-D11` with an approved source, aggregate-
fatigue definition/estimator, privacy/minimization contract, acceptance tests, and calendar-matrix
amendment; descriptive audience mix alone is insufficient. Calendar badges are live source rows,
never the HTML samples.

### 8.6 Existing UI remediation disposition

The following table defines what `P5-0P` must decide; it does not itself authorize code changes.

| Area | Required Phase 5 disposition | Must remain unavailable/unchanged |
|---|---|---|
| Desktop/mobile navigation | Wire four Phase 5 pages; make all twenty implemented destinations mobile reachable; freeze the exact tree plus canonical `?page=`/Demand-Forecast fallback/push/replace/popstate/scroll/focus behavior; preserve Executive Overview, Performance Insights, Reports & Exports, Alerts & Notifications, Model Management, User Management, and Settings in exact reference group/order/icon/label as native-disabled unless a separately approved real route exists | No enabled-looking inert item, dual hash/query router, fake route, handler/request/history entry, or blanket omission; each absent item requires its own approved parity amendment |
| Shell authority | Decouple Data Management bootstrap and support panel/page-local degradation | No cross-page fallback sample data |
| Global scope | Derive market from reviewed local server scope and canonical Store/region; preserve the original shell with no Market control; use visible Store plus per-destination Channel applicability, disabling Channel on location-grain projections | Do not add a Market control without presentation amendment, send/claim unsupported Channel, or pretend filters apply where API remains global |
| Currency | Separate local operating prices from convertible reporting aggregates; disposition INR/USD/EUR/GBP/AED individually with governed live rate/as-of/direction or visible disabled/unavailable behavior and a Phase 6 boundary record | Never FX-convert price-rule inputs, hide mixed currencies, or expose an enabled currency with no governed pair |
| Footer | Freeze enterprise vs filtered scope and load independently | Do not reuse stale current-page data |
| Data Management | Restore exact `#dataManagement` root and toolbar order: Add Data Source, Upload Sample Data, Run Validation; Add Data Source gets the §8.8.5 visibly labelled preview-only form; expose latest retained Validation Results in read-only source detail/mapping | `Connect`, Upload, and Run Validation remain disabled; Upload/Run have no handler/network call; preview has no request/write/history; no invented user identity |
| Data Management status/actions | Freeze Healthy/Delayed/Needs Attention/stale/missing/failure reasons and badge mapping; View Mapping is read-only only where governed evidence exists | Refresh/Retry stay natively disabled without an authorized mutation route; Run Validation never masquerades as a read action |
| Demand Forecast summary | Scope or label; lazy panel queries; region/store validity | Business Impact/replay superiority unavailable |
| Demand Forecast granularity | Preserve Weekly, Daily, Monthly in order with Weekly live; Phase 5 recommended disposition natively disables Daily and Monthly with accessible reasons until exact API-native daily/monthly distributions and quantiles exist | Never sum weekly P50/P90 values and label the result a monthly quantile; disabled options make no request/query-key change |
| Demand Forecast selection/export | Controlled row and select-all-visible/indeterminate state; selected rows drive scoped read-only export, zero selection exports current filtered rows; authority/filter/granularity/page changes clear selection | Filtered-empty export is natively disabled/reasoned with no silent return or empty file; selection never drives acceptance/workflow |
| Demand Forecast risk | Amend both stale Demand at Risk and Stock-out Risk matrix rows plus stale prose to match accepted Phase 4 output | Do not call projected risk realized lost sales |
| Demand Forecast scenario | Enable stateless price scenario when accepted response exists | Save/apply/approval remain disabled |
| Demand Forecast promotion | Enable only after the formal `P5-D23` Decision-#53 amendment and a new origin-safe pin | Current backfilled evidence and `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` remain unavailable; a new pin alone is insufficient |
| Demand Forecast versions | Load compatible retained versions or govern unavailable | Do not hard-code model/version labels |
| Demand Forecast Priority Action | Freeze mapping from accepted exception + demand-at-risk + inventory health, with missing-input fallback | Do not reuse Pricing Store View action rules silently |
| Forecast modal empty states | Action Center and Store Drilldown show governed explanatory content when rows/counts are empty | No blank modal body or empty table chrome |
| Existing copy | Replace internal phase/roadmap/package/policy-freeze/fingerprint explanations with business prerequisites; keep technical lineage in detail/export | Original approved business labels remain; no internal jargon in primary copy |
| Required selectors | Add `#dataManagement`, missing Forecast panel IDs, and inventory page wrapper IDs per contracts | Do not rename approved selectors casually |
| Inventory controls | Restore exact order, missing Replenishment checkbox, live supported filters, safe export/detail; Replenishment selection is controlled/select-all-visible/indeterminate, drives only selected-row detail/export, clears on scope/filter/page change, and disables export on filtered empty | Mutation/ERP/workflow controls remain disabled; no uncontrolled/no-op checkbox or silent empty export |
| Inventory schemas/states | Strict per-screen schemas; exact zero vs no evidence; typed API reasons; stable skeletons | No `record(unknown)` or status-string parsing |
| Inventory demand risk | Add accepted risk companion and assessed/withheld coverage | No realized lost-sales or replay-benefit claim |
| Inventory action bindings | Use understock/urgent recommendations and ageing candidates | Do not bind actions to residual/dead cells |
| Safety Stock | Materialize/display policy-segment grain and SKU count | Promo driver stays unavailable unless policy formula changes |
| Allocation demand | State trailing-91-day basis or publish aligned demand | Do not label requested-units proxy ambiguously |
| Inventory valuation/expiry | First correct 73 WAC-derived rows carrying FIFO, reconcile `derived_lane_wac`, and expose exact unavailable coverage; then may enable NRV/markdown/provision/recovery with accepted price policy + cost and amended formulas | 68 unavailable valuation rows across four stores/four DCs—including the Pune overflow and Brooklyn MFC nodes—and unsupported elements stay unavailable; source FIFO label never proves computed FIFO |
| Inventory Waste Reduction | Compare frozen canonical current/prior windows; state scope, lineage, percent sign/denominator and lower/higher/exact-zero/no-prior cases | Do not require or substitute Phase 5 price/cost policy for this historical comparison |
| Independent inventory blocks | Render summaries/cards/groups from their own payload even when the primary row table is empty | Do not suppress populated cards because `items` is empty |
| Inventory replay fields | Preserve current/replay capability split | Fill-rate/service/revenue/working-capital benefits remain withheld |
| UI styling/accessibility | Fix missing button/trend classes; field-specific badges; dates; focus/dialog/table behavior | Do not visually conceal unavailable states |
| Card-header metadata | Split static count/as-of/context from real actions; static values are AT-visible, non-focusable, non-pointer and handler-free | No `aria-hidden` count or pointer/link styling without an executable semantic action |
| Disabled modal inventory | Approve exact preview-only access where live demonstration is required; trigger carries visible/accessibly described preview treatment and dialog fields/submits are disabled/no-request | Without preview amendment, hidden modal rows are structural parity only and cannot satisfy live Demo 5 coverage |
| Search/refetch behavior | Freeze debounce duration, retain prior data, cancel obsolete work, reject stale responses, and retain focus | No per-keystroke page flash or late-response overwrite |
| Tests/review | Structural coverage, destination-specific live-state matrices, all-five-currency/filter-applicability evidence, and required-viewport screenshots for all twenty destinations | Existing open human-review gates cannot be declared complete by unit tests alone |

### 8.7 Required parity/data matrix fields

Every row in each new or amended screen contract includes:

- stable element ID and exact reference selector;
- original DOM order and exact visible text;
- component kind and responsive placement;
- HTML sample value marked `reference_sample_only`;
- live API field or governed calculation;
- formula, numerator, denominator, aggregation, rounding, and sign convention;
- canonical grain and join identity;
- global/page filter and sort behavior;
- time window, decision origin, valid time, known-as-of, freshness, and staleness;
- operating/reporting currency behavior and formatting;
- model/source/cost/privacy/workflow capability dependencies;
- loading, exact-zero, filter-empty, insufficient, unavailable, stale 409, corrupt/missing 503,
  and partial behavior;
- action ownership and exact enabled/disabled semantics;
- endpoint/schema/type field and export disposition;
- desktop/mobile DOM, screenshot, data-value, accessibility, and human-review status.

Contract tests assert exact page/nav/title/subtitle/control/filter/KPI/card/tab/table/modal order,
required IDs, unavailable element retention, disabled mutation behavior, local currency formatting,
and absence of reference sample values in production paths.

Styling rows inherit the original shared token authority explicitly: 245px desktop sidebar; sticky
full-height sidebar and sticky topbar; `Inter, Segoe UI, Arial, sans-serif`; palette
`#0f2238/#173a62/#2f80ed/#1fbf75/#f05a67/#ffae1a/#7c4dff`, text `#162033`, muted `#6b768c`, line
`#e6eaf0`, background `#f5f8fc`, white cards; 16px card radius; `0 8px 24px rgba(15,34,56,.08)`
card shadow; 14px primary grid gaps; original 10/12/14/16/20/22/24px control/content spacing;
sticky/z-index behavior; table/badge/card/callout/modal tokens; and breakpoints/modal bounds from
§8.1. Token screenshots and computed-style assertions prevent “same order” from masking visual
drift. Any token change requires an approved presentation amendment.

The Pricing Decision Quality ring requires a specific presentation amendment: both the original
CSS conic-gradient stop and pseudo-element `82 Score` content become one bound custom property/DOM
value. Tests assert API value = accessible text = computed gradient percentage at 0, boundary,
partial, and 100 states; freezing only the score formula is insufficient.

### 8.8 Exact reference contextual and modal inventory

The following reference inventory is mandatory matrix input. Sample names, dates, values, URLs,
counts, and selections are marked reference-only; labels, option order, control order, and modal
composition remain presentation authority unless an amendment is approved.

Every row below receives a stable `surfaceId`; `accessMode` is exactly one of `business_live`,
`read_only`, `preview_only`, `hard_disabled`, or `structural_only`. Each row also receives a trigger
selector, capture/test ID, and desktop/mobile review disposition. For a
`preview_only` mutation form, the trigger preserves its original label first and adds a small
`Preview only` treatment inside the trigger after that label; the dialog begins with one business-
prerequisite callout, uses read-only text/date fields, allows enumerated controls to change only
local preview state, leaves prohibited choices visible but natively disabled, and keeps the original
submit disabled. Cancel/Close remains live. No preview issues a request, changes URL/history, writes
state, or uses reference sample values. Every mandatory mutation/workflow modal below uses this mode
when it cannot be genuinely `business_live`/`read_only`: Approve Price Recommendations, Send
Recommendations for Review, Schedule Price Changes, Pricing Action Center, Add Competitor, Create
Competitor Alert Rule,
Link Different Product, and Create Promotion. This makes all reference fields/options inspectable,
including Approved Web Collection, Bundle/BOGO/Loyalty/customer-segment, and Approval Route. Review
Competitor Product Match is reachable read-only with all mutation footers disabled; Simulate
Promotion is governed-live when its gates pass and uses a preview-only unavailable-state fallback
when they do not. A mandatory row cannot be downgraded to `structural_only`; rejection of its preview
amendment blocks Demo 5. `structural_only` is reserved for an explicitly rejected duplicate/non-
authoritative implementation artifact that is not a distinct reference surface.

Mandatory page-visible headings/callouts, with exact original-HTML casing, include:

- `Category Pricing Effectiveness`;
- `Category Opportunity Matrix`;
- `Scenario Comparison`;
- `AI Recommendation`;
- `Competitor intelligence`;
- `Matching guardrail`;
- `AI promotion planning`.

These are DOM/text parity assertions, not optional descriptive aliases.

#### 8.8.1 Price Recommendations contextual rows and modals

Context rows that must not be omitted:

- Recommendation Mix — `Current filtered view`;
- Business Value by Driver — `Projected`;
- Approval Pipeline — `This week`;
- Pricing Opportunity Waterfall — `Projected annualized impact`;
- Pricing Decision Quality — `Current model`;
- SKU-Level Price Recommendations — live recommendation-only `N recommendations` count and, when
  withheld rows share the table, the approved adjacent `M manual review` count;
- recommendation-table instructional note;
- Price Elasticity & Scenario Insight — `Selected portfolio`;
- Pricing Risk & Governance — `Exceptions`.

Exact modal inventories:

| Modal | Body/control order | Reference options/content order | Footer/action disposition |
|---|---|---|---|
| Price Recommendation Detail | Product, Recommended Action, Confidence; Commercial Impact; Decision Context; AI explanation | Commercial Impact: Current price, AI price, Revenue impact, Margin impact. Context: Competitor price, Stock cover, Forecast demand, AI reason | `Open Simulation` live navigation; Cancel/close behavior |
| Approve Price Recommendations | Products selected, Stores affected, Average price change, Maximum price change, Estimated revenue impact, Higher approval exceptions; Approval validation; Effective Date; Approval Note | no sample value is live | preview-only access; `Confirm Approval` disabled, Cancel live; no request/write/history |
| Send Recommendations for Review | Selected recommendations, Current status, Target status; Reviewer, Priority, Due Date, Review Reason; Comments | Reviewer choices are reference-only/unavailable without governed identities. Priority: High, Medium, Low. Reason: Price movement exceeds approval limit; Margin impact requires review; Competitor data validation; Strategic product review | preview-only access; `Send for Review` disabled, Cancel live; no request/write/history |
| Export Price Recommendations | Scope, Format, Include AI explanation, Include audit history; File Name | Scope: Selected recommendations (N), Current filtered view (N), All recommendations (N). Format: CSV, Excel-compatible CSV, PDF / Print. Explanation: Yes/No. Audit: No/Yes | `Export`, Cancel; §8.2.1.1 governs counts/defaults/zero/limit, CSV encodings, filename, lineage, and errors; PDF/Print and audit Yes are visible-disabled/no-call |
| Schedule Price Changes | Recommendations, Stores, Status; Effective Date, Effective Time, Channels, Rollback Rule | Channels: All Channels, Stores Only, E-commerce Only. Rollback: Rollback on integration failure, Manual rollback only | preview-only access; `Schedule` disabled, Cancel live; no request/write/history |
| Compare Selected Recommendations | table columns Product, Action, Price Change, Revenue Impact, Margin Impact, Confidence | requires at least two selected rows; one selected receives accessible “select at least two” state | Close; read-only/live |
| Pricing Action Center | Pending Decisions, High Priority, Value Awaiting Approval; Decision Queue, Items, Owner, Value | original workflow queue labels remain, but every count/value/owner row is typed workflow-unavailable rather than sample data | preview-only access; all queue actions disabled, Close live; no request/write/history unless a later approved non-workflow read model makes it live |
| Store Pricing Drilldown | Store, Period; Open Recommendations, Revenue Opportunity, Margin Opportunity; Top Pricing Issues; Recommended Actions | Period: This Week, This Month, Quarter to Date. Issue/action order follows §8.2.4 | `Open Store Recommendations` read-only navigation; Cancel/close |

#### 8.8.2 Price Simulation modal

`Simulation Result` / approved equivalent preserves metric order Revenue, Margin, Stock Risk,
Confidence followed by `AI recommendation` callout. It has Close only and no apply/save action.
Any visible inputs, assumptions, policy checks, or lineage beyond that composition require the
amendment described in §8.3.3.

#### 8.8.3 Competitor modal inventories

| Modal | Exact fields/options in order | Footer/action disposition |
|---|---|---|
| Add Competitor | Competitor Name; Competitor Type: Direct Retailer, Marketplace, Brand Website, Regional Competitor; Country / Region: India, United States, Europe, GCC; Website URL; Data Collection Method: API Feed, Approved Web Collection, CSV / SFTP Feed, Manual Upload; Refresh Frequency: Hourly, Every 4 Hours, Daily, Weekly; Categories to Monitor: All Categories, Footwear, Apparel, Electronics, Beauty; Currency: INR, USD, EUR, AED; Notes; Connection validation callout | preview-only access; submit `Add Competitor` disabled, Cancel live, no request/write; Approved Web Collection remains visible and individually disabled with its approved-source reason |
| Create Competitor Alert Rule | Rule Name; Trigger Type: Competitor price changes, Price gap exceeds threshold, Competitor promotion detected, Competitor becomes out of stock, Competitor returns to stock, New competitor product detected; Threshold; Comparison Direction: Our price is higher, Our price is lower, Either direction; Category Scope: All Categories, Footwear, Apparel, Electronics, Beauty; Competitor Scope: All Competitors, Selected Competitor, Top 3 Competitors; Severity: High, Medium, Low; Notify: Pricing Manager, Category Manager, Pricing + Merchandising, Executive Team; Frequency: Immediately, Hourly Digest, Daily Digest; Recommended Action: Create price recommendation, Notify only, Send for manual review; Rule Description | preview-only access; `Create Rule` disabled, Cancel live; identity-dependent Notify choices disabled, no request/write/history |
| Review Competitor Product Match | Review item, Match confidence, Current status; Our Product card; Competitor Product card; Attributes used for matching callout; Reviewer Comment | read-only/live from the inspection queue; exact footer order is `Reject Match`, `Link Different Product`, `Accept Match`, `Cancel`. Reject/Accept are disabled; Link is a live local preview control with an adjacent visible/accessibility `Preview only` treatment; Cancel is live. No Previous/Next controls and no mutation |
| Review Competitor Product Match — Link Different Product state | In-place replacement under the unchanged `Review Competitor Product Match` title: Search competitor catalogue; columns Select, Candidate Product, Price, Confidence | preview-only state from Link; local search/selection may use only governed candidate rows already carried in the inspection payload, otherwise typed empty/unavailable; exact footer order `Save New Match`, `Cancel`, with Save disabled and Cancel live; no request/write/history |

Selector authority for the duplicated competitor forms is closed as follows:

- Add Competitor uses the richer original selector family `#newCompetitorName`,
  `#newCompetitorType`, `#newCompetitorRegion`, `#newCompetitorUrl`, `#newCompetitorMethod`,
  `#newCompetitorFrequency`, `#newCompetitorCategory`, `#newCompetitorCurrency`, and
  `#newCompetitorNotes`. The later `#fixCompetitorName`, `#fixCompetitorType`,
  `#fixCompetitorRegion`, `#fixCompetitorUrl`, `#fixCompetitorMethod`,
  `#fixCompetitorFrequency`, `#fixCompetitorCategory`, `#fixCompetitorCurrency`, and
  `#fixCompetitorNotes` implementation is a non-authoritative duplicate recorded by `P5-0P` as
  `structural_only`; it receives no runtime trigger/handler, modal, capture, or demo-coverage credit.
- Create Competitor Alert Rule uses the richer original selector family `#competitorRuleName`,
  `#competitorRuleTrigger`, `#competitorRuleThreshold`, `#competitorRuleDirection`,
  `#competitorRuleCategory`, `#competitorRuleScope`, `#competitorRuleSeverity`,
  `#competitorRuleNotify`, `#competitorRuleFrequency`, `#competitorRuleAction`, and
  `#competitorRuleDescription`. The later `#fixRuleName`, `#fixRuleTrigger`, `#fixRuleThreshold`,
  `#fixRuleDirection`, `#fixRuleCategory`, `#fixRuleSeverity`, `#fixRuleNotify`, and
  `#fixRuleAction` implementation is a reduced non-authoritative duplicate recorded by `P5-0P` as
  `structural_only`; it receives no runtime trigger/handler, modal, capture, or demo-coverage credit.

The Review workspace uses the richer modal above, not the later simplified duplicate JavaScript.
Missing brand/model/variant/GTIN/image attributes render per field as unavailable; they are not
filled with generic sample text. Link Different Product follows the original in-place body/footer
replacement and does not open a separately titled or stacked child dialog. The dialog title stays
`Review Competitor Product Match`; replacement refocuses that title, preserves the root Review
Matches trigger for final focus return, and has its own capture ID. A distinct `Link Different
Product` modal title requires an explicit presentation/accessibility amendment.

#### 8.8.4 Promotion modal inventories

| Modal | Exact fields/options in order | Footer/action disposition |
|---|---|---|
| Create Promotion | Promotion Name; Promotion Objective: Revenue Growth, Inventory Clearance, Customer Acquisition, Basket Size Growth, Loyalty Engagement; Promotion Type: Percentage Discount, Fixed Price, Bundle Offer, Buy One Get One, Loyalty Member Price, Clearance; Discount / Offer; Category: Footwear, Beauty, Electronics, Apparel; Product Scope: AI Recommended Products, Selected SKUs, Entire Category, Ageing Inventory; Start Date; End Date; Stores / Channels: All Stores, Selected Stores, Online Only, West Region + Online; Customer Segment: All Customers, Loyalty Members, High-Value Customers, Lapsed Customers; Minimum Margin; Approval Route: Category Manager, Pricing Manager, Finance + Business Head; Business Rationale; AI validation before creation callout | preview-only access; `Create Draft` disabled, Cancel live, no request/write. Bundle/BOGO, Loyalty Member Price, segment/customer targeting, customer-level objectives, and approval route remain visibly privacy/workflow-disabled |
| Simulate Promotion | Promotion; Scenario: Expected, Best Case, Worst Case; Discount Depth; Duration: 3 Days, 7 Days, 14 Days; Store Scope: All Stores, Selected Stores, Online Only; Customer Segment: All Customers, Loyalty Members, High-Value Customers; Include Cannibalisation: Yes, No; Include Competitor Response: Yes, No | `Run Simulation`, Cancel on the live branch. Customer Segment is fixed to All Customers and other options are privacy-disabled; Cannibalisation is disabled; stateless Run is live only when `P5-D23`, `P5-D20`, and promotion-confidence gates pass. On every unavailable branch, exact footer order is disabled `Run Simulation`, secondary `Preview Results` with visible/accessibility preview treatment, Cancel. Preview Results performs an in-memory replacement only and no request/write/history |
| Promotion Simulation Results | Expected Demand Uplift, Revenue Uplift, Gross Margin Impact, Required Stock, Sell-through Improvement, Cannibalisation Risk; Scenario Comparison columns Metric, Current Plan, AI Optimized and rows Discount, Revenue, Margin, Ending Stock; AI Recommendation callout; Stock readiness, Promotion conflict, Confidence | Close only. A live numeric result opens when `P5-D23`, `P5-D20`, and `P5-D22` pass. Otherwise the distinct Preview Results path opens the identical composition with every gated numeric value typed unavailable and its exact first business reason; no result request occurs. Confidence follows `P5-D22`; cannibalisation is null/reason; primary margin is client-actual or unavailable, and generated cost never appears in this modal or any Promotion Planner result |
| Promotion Calendar | Month View, List View, month selector July 2026/August 2026; headings `Mon`, `Tue`, `Wed`, `Thu`, `Fri`, `Sat`, `Sun`; 35-cell grid; event badges; Calendar controls callout | Month View is active/read-only-live and month selector is live; List View is visible/natively disabled with `Governed list-view composition not approved`, no handler/request/active style, because the reference has no list body; reference months/events become source-driven through an approved data row; Close-only footer |

Promotion mechanics that may be live in the permitted PoC are Percentage Discount, Fixed Price,
and Clearance, bound only from the dedicated offer-mechanic field and its depth/terms. Current
campaign classes (`campaign`, `clearance`, `fire-sale`, `runout-markdown`) are not silently mapped
to mechanics. Loyalty Member Price, Bundle Offer, and Buy One Get One remain visible/privacy-
disabled under Decision #19. Modal footer order, Close/Cancel behavior, callout presence, and
disabled-option reasons are asserted in DOM and keyboard tests.

#### 8.8.5 Existing-page modal inventories

These are mandatory `P5-0P` amendment targets, not optional hidden components. Current React bodies
that differ from the richer original HTML must be brought to this contract or receive a field-by-
field approved amendment. Every row has its own `surfaceId`, access/capture state, and governed/
unavailable value mapping; original sample names, values, comments, owners, and dates are never live.

**Data Management:**

| Modal | Exact composition | Access/footer disposition |
|---|---|---|
| Add Data Source | Source Name; Type in order API, Database, SFTP, CSV; Refresh in order 15 minutes, Hourly, Daily | preview-only from `Add Data Source — Preview only`; `Connect` disabled, Cancel live; local enum exploration only, no file/network/write/history |
| Validation Results | metric order Quality, Valid, Duplicates, Missing | read-only from the approved latest-validation/View Mapping path using retained evidence; Close only. `Run Validation` itself remains disabled/no-handler and cannot be the route |

`Upload Sample Data` remains a visible disabled control with accepted-type/prerequisite help and
does not open a native file chooser. It has no distinct reference application modal to fabricate.

**Demand Forecast:**

| Modal | Exact title/body order | Access/footer disposition |
|---|---|---|
| Accept Forecast | summary order Selected Forecasts, Average Confidence, Demand Value; Acceptance Comment | preview-only; selected count and any summary value are governed or unavailable; comment read-only; `Confirm Acceptance` disabled, Cancel live |
| Add Planner Adjustment | Product / SKU; Store; AI Forecast read-only; Planner Forecast; Adjustment Reason in order Local event, Promotion change, Competitor event, Operational constraint, Commercial judgement; Effective Period in order Next Week, Next 4 Weeks, Specific Date Range; Comment | preview-only; product/store options are governed, numeric/text inputs read-only, enums local-only; `Save Adjustment` disabled, Cancel live |
| Compare Forecast Versions | columns Version, Created By, Accuracy, Bias, Demand Units, Status | read-only/live for compatible retained versions; otherwise the same six-column body shows typed unavailable/empty evidence; Close only |
| Demand Scenario Planning | Scenario in order Expected Demand, High Demand, Low Demand, Promotion Upside, Supply-Constrained; Demand Adjustment; Price Change; Promotion Uplift; Competitor Availability in order Normal, Competitor Stock-out, Competitor Promotion; Weather / Event Impact in order Normal, Positive, Negative | preview-only until a separately approved API-native forecast-scenario contract exists; values are read-only/local enums; exact footer order is disabled `Run Scenario`, secondary `Preview Results` with visible/accessibility preview treatment, Cancel. Preview Results only replaces the dialog with the unavailable Scenario Results layout—no calculation/request/write/history |
| Scenario Results | summary order Demand Units, Revenue Potential, Required Inventory; table columns Metric, Current Forecast, Scenario, Impact; rows Demand, Stock-out Risk, Revenue | preview-only with every numeric value typed unavailable and its business reason unless an approved stateless scenario result exists; Close only; never aggregate weekly quantiles into scenario intervals |
| Forecast Action Center | summary order Open Exceptions, High Priority, Demand at Risk; columns Action Queue, Items, Owner, Business Exposure; row labels Under-forecast review, Over-forecast review, Data-quality correction, Model retraining | preview-only; workflow counts/owners/exposure are typed unavailable unless a governed read model is approved; Close only and no queue action |
| Store Forecast Drilldown | Store; Period in order Next 4 Weeks, Next 8 Weeks; Store Forecast Health rows Accuracy, Bias, Demand at risk, Planner override rate; Recommended Actions rows/action and priority; footer `Open Store Forecasts` | read-only/live from governed store/version data, with per-field unavailable states; footer performs read-only navigation only, Cancel/Close live |

**Stock Health:**

| Surface ID / exact React selector | Exact visible trigger → modal title | Exact body order | Access/footer disposition |
|---|---|---|---|
| `stock-health.assign-owner` / `[data-surface-id="stock-health.assign-owner"]` | `Assign Owner` → `Assign Owner` | Owner; Priority in order High, Medium, Low; Due Date | preview-only; Owner uses governed identities or a typed unavailable option—the original Emma Johnson/Rahul Mehta/Sara Khan values are samples and never render as live; date is read-only; exact footer `Save`, Cancel with Save disabled; no request/write/history |
| `stock-health.create-action` / `[data-surface-id="stock-health.create-action"]` | `Create Action` → `Create Stock Action` | Action in order Markdown, Transfer, Replenish, Stop Replenishment; Approval Route in order Category Manager, Pricing Manager, Business Head | preview-only local enum exploration; exact footer `Save`, Cancel with Save disabled; no request/write/history |

The reference Stock Health buttons have no HTML IDs, so the Phase 5 React port adds only the stable
non-visual `surfaceId`/test IDs above; visible labels, order, styling, and placement remain unchanged.

**Inventory shared action dialog:** every trigger below opens the same exact preview-only structure:
summary cells `<Metric>`, Priority, Decision; Owner options in order Inventory Manager, Supply Chain
Lead, Category Manager, Finance Controller; Action Note; footer `Create Action`, Cancel. Metric values
are governed/read-only or unavailable, Owner is local-only, note is read-only, `Create Action` is
disabled, and no request/write/history occurs.

| Exact selector | Exact visible trigger | Exact modal title | Metric label | Decision label |
|---|---|---|---|---|
| `#inventoryActionCenterBtn` | Inventory Action Center | Inventory Action Center | Value at Risk | Review enterprise actions |
| `#inventoryStoreDrilldownBtn` | Store Drilldown | Store Inventory Drilldown | Stores at Risk | Open store actions |
| `#inventoryWarehouseDrilldownBtn` | Warehouse Drilldown | Warehouse Inventory Drilldown | Blocked Inventory | Release or reallocate |
| `#inventoryScenarioBtn` | Run Inventory Scenario | Inventory Scenario | Working Capital Opportunity | Simulate inventory reduction |
| `#storeInventoryActionBtn` | Create Store Action | Create Store Action | Lost Sales Exposure | Assign store action |
| `#storeInventoryTransferBtn` | Create Transfer | Create Store Transfer | Transfer Opportunity | Create transfer |
| `#warehouseReleaseBtn` | Release Blocked Stock | Release Blocked Stock | Blocked Inventory | Release stock |
| `#warehouseReceiptBtn` | Review Delayed Receipts | Review Delayed Receipts | Delayed Receipts | Expedite receipts |
| `#ageingMarkdownBtn` | Create Markdown Plan | Create Markdown Plan | 90+ Day Inventory | Apply controlled markdown |
| `#ageingTransferBtn` | Create Transfer Plan | Create Ageing Transfer Plan | Transfer Opportunity | Rebalance inventory |
| `#createInventoryTransferBtn` | Create Transfer Request | Create Transfer Request | Open Transfer Value | Create transfer |
| `#optimizeTransferBtn` | Optimize Transfers | Optimize Transfers | Expected Recovery | Run optimization |
| `#valuationScenarioBtn` | Run Valuation Scenario | Run Valuation Scenario | Net Realizable Value | Recalculate provisions |
| `#valuationReconcileBtn` | Reconcile with ERP | Reconcile with ERP | Inventory Variance | Start reconciliation |
| `#expiryActionBtn` | Create Expiry Action | Create Expiry Action | Near-Expiry Inventory | Create expiry response |
| `#wasteReductionBtn` | Create Waste Reduction Plan | Create Waste Reduction Plan | Recovery Opportunity | Create recovery plan |

**Replenishment shared action dialog:** every trigger below opens the same exact preview-only
structure: summary cells `<Metric>`, Priority, Action; Comment; footer `Create Action`, Cancel.
Metric values are governed/read-only or unavailable, Comment is read-only, `Create Action` is
disabled, and no request/write/history occurs.

| Exact selector | Exact visible trigger | Exact modal title | Metric label | Action label |
|---|---|---|---|---|
| `#approveReplenishmentBtn` | Approve Selected Orders | Approve Replenishment Orders | Suggested Value | Approve selected orders |
| `#createTransferRequestsBtn` | Create Transfer Requests | Create Transfer Requests | Transfer Opportunity | Create optimized transfers |
| `#sendReplenishmentErpBtn` | Send to ERP | Send to ERP | Approved Orders | Transmit approved orders |
| `#replenishmentScenarioBtn` | Run Scenario | Replenishment Scenario | Working Capital Impact | Run service-level scenario |
| `#replenishmentActionCenterBtn` | Action Center | Replenishment Action Center | Open Exceptions | Review priority actions |
| `#suggestedApproveBtn` | Approve Orders | Approve Suggested Orders | Order Value | Approve order batch |
| `#suggestedModifyBtn` | Modify Quantity | Modify Suggested Quantity | Suggested Orders | Adjust order quantity |
| `#supplierCapacityBtn` | Request Capacity Confirmation | Supplier Capacity Confirmation | Unconfirmed Capacity | Request confirmation |
| `#supplierExpediteBtn` | Create Expedite Request | Create Expedite Request | Revenue at Risk | Expedite order |
| `#recalculateSafetyStockBtn` | Recalculate Safety Stock | Recalculate Safety Stock | Current Safety Stock | Recalculate policy |
| `#approveSafetyStockBtn` | Approve Policy | Approve Safety Stock Policy | Policy Coverage | Approve policy |
| `#optimizeAllocationBtn` | Optimize Allocation | Optimize Allocation | Allocation Pool | Run optimization |
| `#releaseAllocationBtn` | Release Allocation | Release Allocation | Fulfillment Rate | Release allocation |
| `#resolveReplenishmentExceptionBtn` | Resolve Selected | Resolve Exceptions | Open Exceptions | Resolve selected |
| `#assignReplenishmentExceptionBtn` | Assign Owner | Assign Exceptions | High Priority | Assign owner |

**Deterministic modal interaction contract:**

- Every dialog uses one labelled `role=dialog`, `aria-modal=true`, one visible title, one global X,
  the frozen body order, and its explicitly frozen footer order; the Review Match and preview-result
  exceptions above override the generic primary-then-Cancel/Close pattern. Initial focus is the
  dialog title (`tabindex=-1`, initial-only). The first Tab moves to the global X, then through enabled
  body controls in DOM order, then enabled footer controls in their displayed order. The last enabled
  footer/body control wraps to X; initial Shift+Tab from the title and later Shift+Tab from X both
  move to the last enabled footer/body control.
  If X is the only enabled control it cycles to itself. Disabled preview fields/options are skipped
  but remain named/described to assistive technology.
- Because Phase 5 dialogs never hold an authorized persistent write, X, Cancel/Close, Escape, and
  backdrop all close. If a live stateless request/export is in flight, close first aborts it and
  proves no late result/download is committed. Every close path restores focus to the exact visible
  trigger; if that trigger disappeared after a legitimate scope change, focus moves to the page H2
  and announces the reason.
- The three result paths are distinct and exact. Price Simulation's page-level `Run Simulation`
  opens `Simulation Result` directly—there is no parent dialog to retain. Forecast `Preview Results`
  replaces `Demand Scenario Planning` with `Scenario Results`. Promotion live `Run Simulation` or
  unavailable `Preview Results` replaces `Simulate Promotion` with `Promotion Simulation Results`.
  Each replacement uses one dialog, retains the root page trigger identity, and refocuses the new
  title. Link Different Product is instead a same-dialog body/footer state replacement under the
  unchanged Review title, not a child modal. Closing any result/state returns focus to the exact root
  page trigger. Read-only navigation actions close the dialog, route once, scroll to top, and focus
  the destination H2. No hidden parent remains focusable.
- Modal open/close never changes URL/history except an explicitly approved read-only navigation
  action. Each X/Cancel/Close/Escape/backdrop/replacement path has its own capture/keyboard assertion;
  backdrop dismissal is never left to an undefined `where safe` branch.

The capture manifest reserves these exact branch IDs in addition to each table row's base
`surfaceId`: `modal.stock-health.assign-owner.preview`,
`modal.stock-health.create-action.preview`,
`modal.forecast.scenario-results.unavailable-preview`,
`modal.promotion.simulation-results.unavailable-preview`,
`modal.competitor.review-match.default`, and
`modal.competitor.review-match.link-different-product-state`. A missing ID or one screenshot reused
for two states does not satisfy page review.

---

## 9 · Client-demo possibility and state-coverage matrix

The goal is not one attractive happy path. The verified deterministic rich and sparse publications
must make the governed **data/model/capability** states below demonstrable without editing code or
database rows. They do not manufacture operational corruption: stale 409, missing/corrupt 503, and
panel-failure demonstrations come from the isolated non-mutating negative-state adapters in §9.7.

### 9.1 Cross-market and currency

| State | Required live evidence |
|---|---|
| India / INR | Accepted rich market with local grid/endings and at least one live recommendation/simulation |
| United States / USD | Same, independently gated and modelled; tiers/pools constructed only within the US market |
| Reporting currencies | INR, USD, EUR, GBP, and AED each appear in the exact reference order; every option is either selectable with governed FX source/as-of/direction/rate/scope or visibly disabled/unavailable, and local prices never change |
| Mixed-market aggregate | Either approved reporting conversion with assessed coverage or explicit unavailable; never nominal sum |
| Channel | Store and E-commerce rows preserve distinct channel identity; All Channels never silently collapses conflicting recommendations |

### 9.2 Price response and recommendations

| State | Minimum demonstration |
|---|---|
| Increase | At least one guardrail-valid accepted recommendation in each enabled market |
| Decrease | At least one guardrail-valid accepted recommendation in each enabled market |
| Hold | At least one evidence-supported/dominance hold and one policy-withheld case |
| Priority | High, Medium, Low with frozen thresholds |
| Confidence/filter consequence | Live assessed rows in mutually exclusive demo cohorts ≥90%, 80–<90%, and <80%; every recommendation is necessarily ≥90%, so the 90+ filter may contain recommendations and withheld rows, cumulative 80+ adds only middle-confidence withheld rows, and Below 80 contains only withheld rows |
| Recommendation Mix confidence | Increase, Reduce, and Hold reconcile only to ≥90% recommendations; middle/low-confidence assessed rows reconcile to Manual review, never an action row |
| Decision Quality confidence | `High confidence = assessed rows >=90 / all filtered assessed workbench rows`; prove a non-100% mixed assessed view and a 100% recommendation-only view without changing the formula |
| Recommendations at Risk | Demonstrate an accepted non-blocking recommendation warning if the frozen enum has one; otherwise prove exact zero. Hard guard/protection/conflict/missing-input cases are withheld and reconcile to Manual review/At Risk waterfall |
| Elasticity | Accepted negative beta, gate-rejected beta, ineligible panel, enabled and disabled department |
| Guardrails | Valid, max-change rejected, off-grid rejected, protected product, promotion conflict, low-confidence withheld |
| Revenue/margin | Primary revenue recommendation unchanged by cost; separately labelled synthetic margin scenario; primary margin remains unavailable with `COST_NOT_CLIENT_ACTUAL` for generated cost; real/client margin remains unavailable unless separately supplied client-actual cost passes |
| Readiness vs claim | Generated temporal cost may show v2 data readiness while `price_margin` remains a reason-coded non-claim; a separate client-actual profile may activate it only if every provenance gate passes |
| Sparse | Market/department/series reason-coded `insufficient_evidence`; no recommendation rows |
| Workflow columns/filter | Status filter disabled/unavailable plus Status and Owner cells retained; no fabricated workflow values |
| Selection | zero selected, one selected with Compare Selected unavailable guidance, two selected comparison, select-all-visible reset on filter |
| Export/detail | Selected/current-filtered/all export scopes; audit option unavailable; row detail → simulation carries exact SKU/store/channel context |

### 9.3 Price Simulation

| State | Minimum demonstration |
|---|---|
| Scenario | Current, Proposed, AI Optimal across Expected/Best/Worst |
| Input validity | Valid, nonnumeric, non-positive, off-grid, disallowed ending, outside range, >5% change |
| Capability | Rich accepted, missing response, missing forecast, missing/stale cost, missing/stale competitor |
| Risk | Low and high stock-out risk with interval disclosure |
| Objective | Margin Protection available/unavailable; Clearance with/without accepted inventory context |
| Synthetic margin location | §8.3.2 compact panel available from generated WAC and absent when no synthetic scenario; primary Gross Margin/result metrics remain client-actual or unavailable in both states |
| Competitor execution truth | Eligible response shows non-editable Include plus matching input echo; stale/missing/inadmissible response shows `Not included — <reason>` in the same field and matching request/result/accessibility text, never visible Include with executed exclusion |

### 9.4 Competitor Monitor

| State | Minimum demonstration |
|---|---|
| Match | Matched, Needs Review, Rejected, No Match |
| Confidence | Above auto-accept, boundary/review, below threshold |
| Availability | In Stock, Low Stock, Out of Stock, Unknown |
| Freshness | Fresh, near threshold, stale |
| Price position | Above, Below, Equal/within tolerance, incomparable currency/unit |
| Response | Hold, Increase context, Decrease context, Validate, Excluded/No action |
| Source/rule | Approved source; Add Competitor preview opens with no request/write; Approved Web Collection is visibly present but disabled with reason; rules live or honestly unavailable |
| Selection | zero selected fallback to visible Needs Review queue; one/many selected queue order; select-all-visible checked/indeterminate; filter/scope/page reset; no mutation or server state |
| Detail flow | Read-only match detail for Matched/Review/Rejected/No Match with all mutation buttons disabled |
| Alert rules | Source-backed live rule and card-level unavailable/empty state |

### 9.5 Promotion Planner

| State | `decisionDisposition = amended` | `decisionDisposition = not_amended` |
|---|---|---|
| Decision #53/evidence | Origin-safe eligible promotion plus temporal/rejected evidence; package is explicitly `positive_numeric` or `positive_descriptive_only` after `P5-D20` assessment | Preserve every original Planner/Forecast location but expose no Planner fact; first failure is exactly `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` |
| Pricing-protection safety | Not presented as a Planner capability; Price Recommendations separately demonstrates overlap/no-overlap/conflict/missing guard outcomes | Remains internal to recommendation lineage and never leaks through Planner conflict, calendar, status, or scope UI; its demo stays in §9.2 |
| Scope | SKU, department, category, multiple OR rows, invalid/conflicting equal precedence | No scope artifact/value; exact Planner refusal in the preserved location |
| Numeric model gate | `positive_numeric` shows accepted and rejected model rows plus reconciled KPI/chart/table values; `positive_descriptive_only` retains assessment/refusal evidence but every numeric location is unavailable with its `P5-D2` reason | No model/assessment/numeric Planner artifact; exact Planner refusal, not `privacy_restricted` or an internal safety reason |
| Simulation confidence | Per scope, live Expected/Best/Worst only when `P5-D20` and `P5-D22` pass; otherwise Run Simulation/result remain disabled with precedence-derived reason while accepted descriptive/model facts remain | Disabled/no-call; exact Planner refusal is first and confidence is absent |
| Inventory readiness | With accepted/governed requirement: Fully available, transfer required, replenishment required, insufficient/at risk; otherwise requirement/readiness is unavailable with reason | No Planner readiness artifact/value; exact Planner refusal |
| Financial | Model-implied revenue only on accepted `P5-D20` rows; primary margin requires client-actual cost; generated cost leaves every Planner margin/result unavailable with `COST_NOT_CLIENT_ACTUAL` and is demoed only in Price Simulation §8.3.2 | No Planner revenue/margin/synthetic-scenario value; exact Planner refusal |
| Conflict | Full Planner scope demonstrates no-conflict and equal-precedence/refusal cases; the internal pricing-safety result is not substituted | No Planner conflict fact, including no exposed result from the internal pricing-protection feed; exact Planner refusal |
| Audience/privacy | Permitted descriptive aggregate segment mix may be live; segment response/offer/targeting and customer-level results use `privacy_restricted` | No audience artifact/value; `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` is first and Decision #19/privacy remains secondary metadata |
| Deferred models | Cannibalisation and bundle locations remain visibly `privacy_restricted` with no proxy | Preserved locations report the Planner refusal first, with privacy restriction only as secondary metadata |
| Calendar | Month View overlap/no-overlap and empty-month live states from origin-safe plans; List View remains visible-disabled because no approved body exists | No calendar artifact/badge/event fact; exact Planner refusal in the preserved calendar; List View remains visible-disabled |
| Source status | Draft, Under Review, Approved, Live, Completed from the dedicated source-native lifecycle field; missing field is unavailable. Never map `historical \| active` | No lifecycle value; exact Planner refusal |
| Offer mechanic | Percentage Discount, Fixed Price, Clearance from dedicated mechanic/depth/terms; Loyalty Member Price, Bundle Offer, and BOGO remain privacy-disabled. Never map campaign class | No mechanic value; exact Planner refusal, with Decision #19 secondary for privacy-prohibited mechanics |
| Audience mix | Loyalty/High-value/Lapsed/Broad aggregate percentages reconcile to exactly 100% after frozen rounding | No mix artifact or percentages; exact Planner refusal |
| Creation-form preview | Preview-only Create Promotion form exposes exact local option states; Bundle/BOGO/Loyalty/customer-segment choices and Approval Route are visibly disabled; Create Draft is disabled and no request/write occurs | Same preview contract, but no source/model value is populated and the Planner refusal callout remains first; preview structure is not feature evidence |

### 9.6 Existing-page live-state minimums

These are minimum active-rich/naturally-sparse and non-active sparse-harness data/capability
demonstrations, not merely component stories
or status enum unit tests. `P5-0P` freezes exact row identities/counts and whether each state is live
or an honest explicit unavailability before generation.

| Existing destination | Minimum live or explicit-unavailable demonstrations |
|---|---|
| Data Management | Exact `#dataManagement` root and Add Data Source → Upload Sample Data → Run Validation toolbar order; Healthy, Delayed/Needs Attention, validation failure, stale and missing source; source-specific freshness; Add Data Source preview-only form with disabled Connect; latest retained Validation Results in read-only mapping/detail; Upload/Run Validation/Refresh/Retry disabled; every preview/read path has no request mutation or write |
| Demand Forecast | Weekly live; Daily/Monthly visible and natively disabled with accessible reasons unless separately approved API-native distributions/quantiles exist; no summed-weekly quantile. Non-PIT P50 with `LANDING_BACKFILL_DEPENDENCY`; Decision-#92 interval withheld; exact-zero and non-zero demand/risk; Demand at Risk and Stock-out Risk; filtered empty with Export disabled/no-call; controlled zero/one/many/select-all-visible selection driving only scoped export; Store Priority Action mapped or unavailable; Action Center and Store Drilldown explanatory empty states; compatible-version or unavailable; promotion row follows `P5-D23` branch |
| Inventory Overview | Healthy, low/understock, urgent, and ageing candidate populations; exact-zero KPI; action bindings use understock/urgent/ageing facts; independent populated card survives an empty primary table |
| Store Inventory | In stock, low stock, out of stock, exact zero, filtered empty; projected demand-at-risk with assessed/withheld coverage and an unavailable companion case; Store applies and Channel follows the page applicability row |
| Warehouse Inventory | Healthy/low/out-of-stock location rows; DC/store-node distinction; transfer/replenishment context and an unavailable input; filters and totals reconcile at location grain |
| Inventory Ageing | Multiple approved age bands, fresh stock, ageing/markdown candidate, exact-zero exposure, filtered empty, and price/cost-dependent recovery live only when its amended formula is satisfied |
| Stock Transfers | Recommended/in-transit/completed or the exact source-backed statuses; transfer-required and no-transfer states; unavailable acceptance/workflow remains visible; safe detail/export only |
| Inventory Valuation | Correct computed-WAC method, genuine FIFO or explicit FIFO-unavailable, the immutable successor for 73 formerly mislabelled rows, all 68 reason-coded unavailable rows across four stores/four DCs, exact-zero value, and actual-or-absent `derived_lane_wac` |
| Expiry & Waste | No-expiry/exact-zero, approaching-expiry, expired/waste-risk, filtered empty, and governed markdown/recovery live-or-unavailable without a nearby-metric proxy |
| Replenishment Planner | Select-column parity with controlled zero/one/many/select-all-visible/indeterminate and scope/filter/page reset; selection drives only read-only detail/export, filtered-empty disables export/no-call; recommended, urgent, normal/hold, insufficient-input, exact-zero, and filtered-empty populations; no enabled order/workflow mutation |
| Suggested Orders | Suggested and withheld/insufficient rows, missing supplier/policy input, exact-zero quantity, filtered empty, read-only detail/export, and disabled create/submit action |
| Supplier Planning | Source-backed supplier/lead-time facts, delayed/stale/missing supplier evidence, exact-zero/empty population, and unavailable workflow/commitment fields |
| Safety Stock | Policy-segment rows with SKU counts, multiple risk/service states, exact zero, missing driver, and promotion driver unavailable unless its versioned formula actually consumes accepted promotion evidence |
| Allocation & Fulfillment | Trailing-91-day requested-units basis disclosed or replaced by aligned demand; allocated/short/withheld and exact-zero cases; filtered empty; Channel disabled where no governed allocation grain exists |
| Replenishment Exceptions | Multiple frozen exception severities/reasons, no-exception exact zero, filtered empty, missing prerequisite, and workflow resolution/owner fields unavailable unless source-backed read-only facts exist |
| Stock Health | Healthy, at risk, critical/stockout, excess/ageing, exact-zero, filtered-empty, and partial/unavailable companion metrics with totals/cards/table using one scoped population |

Every row also covers its approved Store/Channel applicability and INR/USD/EUR/GBP/AED reporting
disposition. The matrix must name immutable row IDs and API locations; a screenshot of the default
state is insufficient.

### 9.7 Isolated whole-application operational states

Across the active rich bundle, its naturally sparse cohorts, the non-active sparse harness, and
isolated negative-state adapters, every page or representative shared component must cover. Active
data supplies loading, zero, valid, filtered-empty, insufficient, partial, navigation, and export
states; only explicitly marked operational failures use the negative adapters:

- first load with structure-preserving skeleton;
- exact numeric zero;
- valid dataset with rows;
- enabled filters returning zero rows;
- element-level insufficient evidence and mixed/partial capability through rich sparse cohorts;
- stale scope 409 with as-of/remediation/retry guidance *(negative adapter)*;
- missing/corrupt/incompatible scope 503 *(negative adapter)*;
- one injected/read-model panel failure while other panels remain usable *(negative adapter)*;
- aborted/obsolete request after filter change;
- disabled workflow/privacy/source action with keyboard-readable reason;
- direct URL, refresh, browser back/forward, desktop nav, and mobile nav;
- safe export whose values and lineage match the visible scope.

The negative adapters are separately addressed and read-only. They may present retained stale,
missing, or deliberately incompatible activation/read-model evidence, or a bounded panel fault
approved in `P5-3`; they may not edit/corrupt rich or sparse artifacts, update database rows, or
accept browser-provided audience identity.

### 9.8 Coverage evidence rules

1. Minimum state counts and identities are checked from immutable artifact rows and live API
   responses.
2. A hidden component story, unit-test fixture, mock service worker, or original HTML row cannot
   satisfy live coverage.
3. Profiles may be designed before model execution to make useful variation likely. They may not
   be edited after results to manufacture specific accepted coefficients.
4. When a legitimate outcome is absent, the demo states that limitation; the UI is not patched with
   a value.
5. The rich UI demo script and sparse non-active integration script record source/run/version IDs,
   expected scope, values, and refusal states so both demonstrations are reproducible.
6. The negative-evidence script records its exact adapter/configuration and 409/503/panel-failure
   source; none of those states is counted as a property of a valid rich bundle.
7. The approved surface-state capture manifest maps every §8.8 modal and §9 state to a stable
   capture/test ID. Every tab, non-default panel, and `business_live`/`read_only`/`preview_only` modal
   receives at least
   one desktop visual plus keyboard/human review; any shared-mobile sampling names the exact
   equivalent surfaces and reviewer-approved rationale.
8. A preview-only modal counts as live UI coverage only when opened through its approved visible
   trigger in the running app with no fixtures, and evidence proves zero request/write/history
   effect. Every mandatory §8.8 modal must satisfy this rule or be genuinely `business_live`/
   `read_only`; a
   structural-only hidden modal never satisfies the demo inventory and is allowed only for an
   explicitly rejected non-authoritative duplicate that is not a distinct reference surface.

---

## 10 · Acceptance gates and no-go conditions

### 10.1 Entry gates

- `P5-0` resolves the §1.2 conflict through committed JSON selection ledger → materialized
  `source_selection_id` → live PostgreSQL activation/current view → API and proves one coherent
  retained source/forecast/inventory authority; nonexistent generic selection tables, the malformed
  released inventory ledger, and missing old bytes cannot satisfy the gate.
- Phase 4 current and replay capabilities are recorded separately.
- Every carried unavailable field has a reason and responsible future dependency.
- `P5-0P` approves every intended change before that existing frozen page is edited; its open final
  screenshot/human gate does not block independent source/model/API packages.
- No result-bearing implementation starts on an unknown or mixed upstream pin.
- The failing v1 expected-pin check, capability-only selection lookup, incomplete selection scope,
  legacy fallback, cost-provenance loss, and source-only resume match are recorded without mutation;
  the 73-row valuation correction is a successor task, not a `P5-0` edit.

### 10.2 Source and readiness gates

- Native availability is distinct from business-effective time and landing time.
- Price and promotion response inputs are origin-visible at every training/evaluation decision
  origin.
- The pricing-protection active/planned feed is origin-visible and mandatory independently of the
  D23 Planner branch; missing/ambiguous protection withholds affected actionable prices.
- Competitor observations have approved provenance (client/licensed with legal approval, or
  canonical synthetic evidence/derivation/source identity with “Synthetic demo” display purpose),
  observed/known times, and freshness.
- Competitor matches have auditable attributes/method/status, not only numeric confidence.
- Cost has method, unit, currency, provenance, observed/posted time, and origin-safe availability.
- Rich and sparse generator presets are checked in under `datagen/configs`, deterministic,
  immutable, and lifecycle-safe. `P5-2` appends source-selection v2 lifecycles in distinct rich-local/
  sparse-dev scopes before producing separate full-scope input-authority records, v1 pins, and
  lineage-correct downstream rebuild evidence. `P5-8` verifies and materializes both result bundles
  but activates only rich. Sparse has no active pricing result selection and is exercised only by the
  isolated non-active harness.
- Every claimed top-level capability has its own valid Decision-#73 lifecycle using the closed
  four-field scope; market set/page/element keys never enter `scope.capability`, and generated cost
  produces `COST_NOT_CLIENT_ACTUAL` rather than an active `price_margin` selection.
- A normal pipeline run persists the canonically fingerprinted v2 readiness report from the frozen
  evidence-producer registry. Selection readiness/sufficiency and `reportFingerprint` reproduce
  that report exactly; no Gate B fingerprint, caller boolean, or hard-coded sufficient default is
  substituted.
- Gate A, canonical validation, Gate B, v2 readiness, Gate-B/v2 reconciliation, and publication
  reconciliation pass according to the profile's intended capability; expected sparse refusal is
  explicit success, not a hidden failure, and any disagreement fails closed.
- The identity-safe readiness sidecar cites the completed base publication; Gate B and the base
  manifest do not cite the sidecar; readiness retention is separate; any base-identity change
  triggers successor publication and downstream repinning.
- Primary/sparse pins are generated and checked only after their required source selections are
  active, using explicit run, job-purpose, pin-path, authority-path, evidence-root, retailer, tenant,
  and environment values; no mutable run default, newest-record lookup, or implicit path is accepted.
- Config Builder matches both presets across supported OSes. Resume follows the first-consuming-
  stage matrix: source changes republish/repin, sidecar-only changes preserve base/pin, and later
  changes invalidate only declared consumers.
- Features, forecast, and inventory are rebuilt independently and in order for both final rich and
  sparse source lineages with explicit pin/authority paths at every consumer; no hard-coded sparse-
  to-rich fallback or domain-subset/cross-profile-equivalence exception applies.

### 10.3 Contract-freeze gates

- `P5-1P` froze price panel, response baseline/candidates, Decision-#74 split/budget, shrinkage,
  resample, holdout, gates, mappings, and reason hierarchy before profile generation.
- `P5-D24` froze the operational readiness producer, evidence-flag/sufficiency provenance,
  Gate-B/v2 reconciliation, selection fingerprint binding, and generated-cost non-claim semantics.
- `P5-D25` froze selection-v2/legacy-v1 identity parity, source-selection-before-pin ordering,
  explicit primary/sparse v1 pin/authority behavior, rich-local/sparse-dev full-scope resolution,
  genesis/successor semantics, sidecar/retention direction, and the first-consuming-stage
  invalidation matrix.
- Local pricing rules resolve for every enabled market/currency with no missing absolute term.
- Cost-as-of and real/synthetic/unavailable truth tables are frozen.
- Competitor match/source/freshness/response plus evaluation/calibration contracts are frozen.
- Pricing-protection versus Planner promotion applicability/conflict/privacy, the decided `P5-D18`
  normalized scenario index/native-unit table, numeric-uplift
  estimator/acceptance-or-unavailable, per-element reason precedence, foundation disposition, and
  later package-member contracts are frozen.
- Both pre-recommendation foundation manifest/acceptance/outside-verifier contracts are frozen.
- Semantic run/artifact identity, separate post-manifest verifier attempt, DB materialization, atomic
  result-selection-event/activation-set transaction, non-authoritative post-commit receipt, secret-
  free reviewed local serving config, OpenAPI, generated type, error, export, and pagination contracts
  are frozen.
- All four screen matrices contain one row per visible/modal element and are approved.
- Demo-state minimums are frozen before model execution.
- Destination-specific existing-page state minima, Store/Channel applicability, all-five-currency
  disposition, and isolated negative-evidence procedure are frozen before generation.
- Cross-language golden vectors pass before result-bearing integration.

### 10.4 Price-panel and elasticity gates

- Panel creation is point-in-time and contains no future-known input.
- Every assessed series has eligibility metrics and exactly one disposition.
- Eligible series meet ≥52 weeks, ≥90% coverage, ≥3 price levels, ≥5 transitions, ≥2 observations
  per level, and freshness requirements.
- Accepted series meet beta sign/magnitude, ≥0.90 sign consistency, ≤0.80 IQR ratio, ≥50 valid
  draws, and positive holdout deviance improvement.
- Each enabled department independently reaches ≥5% accepted coverage and ≥25 gated series in India
  and the US; fitting remains SKU × store × channel, the count is distinct SKU × store with a
  qualified channel, and channels cannot be double-counted.
- Candidate selection used exactly 13 predeclared origins under the frozen spacing/window/market-
  alignment and surplus-origin rule: origins 1–8 development, at most twenty preregistered
  configurations, one frozen candidate, and origins 9–13 untouched confirmation.
- Producer and independent verifier agree from primitive values.
- Sparse profile returns intended reasons and cannot yield recommendations.

### 10.5 Recommendation, cost, and simulation gates

- Every recommendation joins exactly one accepted response, forecast origin/horizon, current price,
  market/currency policy, and inventory context.
- Every candidate is local, positive, inside observed support, on grid/ending, within floors/
  ceilings, the 2%-at-0.70-to-5%-at-1.00 scaled maximum, and the absolute 5% per-cycle maximum;
  2% is never treated as a minimum action.
- Guardrail ordering and rounded-candidate revalidation match golden vectors.
- Projected units/revenue formulas reconcile independently.
- Generated PoC cost yields only a visibly labelled synthetic-margin scenario; real/client margin
  is null plus reason without client-actual positive same-currency cost-as-of.
- Generated cost cannot change primary candidate eligibility, guardrails, rank, recommended price,
  pricing KPI, promotion KPI/table, or chart.
- Computed WAC is distinct from genuine verified FIFO; a carried FIFO label cannot enable FIFO.
- Client-actual, synthetic, FIFO-unavailable, and missing-cost populations never combine silently.
- Increase, Decrease, and Hold all obey dominance and tie-break contracts.
- Every competitor/promotion guard consumed by recommendations cites the exact independently
  verified `P5-6A`/`P5-7A` foundation-manifest fingerprint and accepted verifier-record hash;
  origin-visible pricing protection passes even on D23-negative or the row is withheld.
- Stateless simulation rejects invalid requests, is idempotent for identical authority/input, has a
  bounded body, performs zero domain/database writes, and labels projections as model-implied.

### 10.6 Competitor gates

- `P5-6A` closes its acceptance/manifest before separate verification; `P5-5` consumes the exact
  manifest fingerprint + accepted verifier-record hash without recomputing eligibility.
- Match status/confidence/source/freshness truth table passes.
- Disjoint evaluation truth, precision/recall/false-match/calibration/cohort/boundary gates pass;
  generator truth is absent from served rows.
- Review/rejected/no-match/stale facts cannot affect price recommendations.
- Price and difference reconcile after unit/currency normalization.
- Availability states are source-observed and time-qualified.
- Response remains inside local recommendation guards.
- KPI/table/detail/export denominators agree under every filter.
- No scraping or enabled competitor/match/alert mutation exists.
- `P5-6B` display/response rows reconcile to both the foundation and the final recommendation.

### 10.7 Promotion gates

- `P5-7A` always proves the origin-visible pricing-protection overlap guard, then produces amended
  full scope only after `P5-D23` or a separate not-amended Planner refusal. It closes acceptance/
  manifest before separate verification; `P5-5` consumes the manifest fingerprint + accepted
  verifier-record hash without recomputing or bypassing the safety guard. Its foundation
  disposition contains no final package prediction, self-manifest hash, or future-verifier hash.
- `P5-D23` formally amended Decision #53 before any result-bearing promotion profile or positive
  package branch; otherwise every result-bearing surface remains
  `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` and positive numeric gates are non-applicable.
- Only origin-safe promotion evidence trains/evaluates numeric response.
- Lifecycle status and offer mechanic come from separate source-native fields; current status/type
  aliases are never converted silently.
- On the amended decision branch the approved assessment pipeline always retains accepted/rejected/
  insufficient/not-evaluated primitives. Numeric promotion output exists only if the frozen
  treatment/comparison/confounder/support/uncertainty/Decision-#74/final-holdout gates pass;
  otherwise descriptive outputs remain and numeric response is unavailable.
- Promotion Decision-#74 evaluation uses a frozen compatible 13-origin registry under the same
  development/confirmation/candidate/surplus-origin rules as `P5-D20`.
- Live promotion simulation additionally has exactly 200 attempted episode-block draws, at least
  50 valid draws, unrounded positive-incremental-unit confidence at least 90%, and independent
  `P5-D22` reconciliation; otherwise Confidence is null and Run Simulation is disabled.
- AND/OR, market geography, precedence, and equal-precedence refusal golden vectors pass.
- Baseline/promoted scenario semantics and chart definition are approved and reconcile.
- Inventory readiness joins the exact pinned Phase 4 authority.
- Primary margin is client-actual-cost-conditional; generated cost leaves every Promotion Planner
  margin/result unavailable with `COST_NOT_CLIENT_ACTUAL`, has no Planner scenario/modal output,
  and is shown only in the Price Simulation §8.3.2 synthetic panel.
- Aggregate audience output contains no customer identity and respects small-cell policy.
- Cannibalisation/bundle/customer-level elements are null plus `privacy_restricted` with no numeric
  proxy.
- Create/approve/owner/schedule actions have no enabled Phase 5 mutation path.
- `P5-7B` writes and passes the package-specific contract: `positive_numeric`,
  `positive_descriptive_only`, or `negative`. The descriptive-only package retains response and
  simulation assessment/refusal primitives but zero accepted numeric projection/opportunity rows;
  a valid negative package is never failed for lacking conditional numeric rows.
- `promotion_package_disposition.json` exactly governs required/forbidden physical members and
  per-element reasons without citing its enclosing manifest/future verifier. On not-amended, only
  the package disposition and internal protection artifact exist before the enclosing bundle adds
  foundation lineage; all Planner Parquets are absent, `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` is first,
  and Decision #19 is secondary metadata.

### 10.8 Bundle, materialization, activation, and local-serving gates

- Rich and sparse manifests are closed independently and bind exact source/upstream/model/policy/
  foundation identities, assessed denominators, unavailable membership, and prospective
  full-scope selection IDs.
- Independent verifier attempts are outside their bundle inventories, cite the completed manifest
  hashes, and recompute primitive evidence rather than importing producer acceptance logic.
- Producer/verifier disagreement rejects the bundle without changing its bytes.
- Migration is idempotent and pinned to the expected predecessor head.
- Each verified bundle materializes in its own all-or-nothing transaction; database counts,
  identities, hashes, aggregates, and lineage reconcile to that manifest.
- Materialization performs no selection or activation write. Both materializations are queryable
  before any new activation.
- Canonical rich result-selection v2 events are prepared only for independently accepted
  capabilities and preserve the prebound full-scope selection IDs.
- One separate PostgreSQL transaction inserts the exact candidate → approved → active result-
  selection events plus an activation-set referencing the verified rich bundle/selections. Database
  constraints preserve predecessor semantics and at most one current event for the local audience;
  any failure rolls back all lifecycle and activation rows.
- A deterministic JSON receipt is exported only after commit, reconciles to immutable database rows,
  and is never read as serving authority or described as cross-store atomic.
- Sparse remains non-active, has no active `price_revenue` selection, and is exercised only by the
  isolated integration harness.
- Local Go startup requires the schema-valid, fingerprinted, secret-free reviewed config plus the
  DSN from `RETAIL_POSTGRES_DSN`; database identity, retailer, tenant, environment, bundle hash, and
  rich activation-set ID must agree before listening. A secret-bearing config, mismatch, absence, or
  ambiguity refuses.
- Browser/query labels never select source, bundle, tenant, environment, or activation authority.
- Go request paths read PostgreSQL only; no file, MLflow, model loading, refit, or database mutation
  occurs at request time.
- Stateless POSTs are bounded, deterministic, idempotent, and non-persisting.
- 409/503/unavailable responses are typed, scoped, reason-coded, and panel-local where permitted.
- Queries, filters, sorts, pagination, summary counts, details, selection, and exports share the
  frozen scope/count/revision contract; limits refuse rather than truncate.
- Live rich smoke, isolated sparse integration, no-write, no-file-read, stale, missing/corrupt, and
  panel-failure evidence pass.
- Container/image release, deployment startup authority, process drain/cutover, registry/origin
  push, database dump, and cross-host restore are absent from Phase 5 artifacts and tasks.

### 10.9 UI and Demo 5 gates

- Four pricing destinations work via desktop, mobile, canonical query URL, exact fallback/
  normalization, direct URL, refresh, browser history, route-change scroll/focus, and parent-submenu state.
- Existing destinations remain reachable and implement only approved corrections.
- The seven non-Phase-5 shell entries each obey their individual approved disposition and exact
  desktop/mobile order; an unimplemented entry is natively disabled/reasoned with no handler,
  request, route, or history change, and no item is omitted under a blanket rule.
- Data Management failure does not block Forecast, Inventory, or Pricing.
- One optional endpoint/panel failure does not destroy whole-page structure.
- Original title/subtitle/control/filter/KPI/card/tab/table/modal order and selectors match matrices.
- The shell contains no visible Market control; reviewed local server scope plus canonical Store/region derives
  market, and all-store mixed-market behavior follows the reporting-currency contract.
- Every supported filter changes all dependent values consistently; invalid dependent values reset.
- Global and page Store controls yield one synchronized effective Store and cannot request
  contradictory scopes.
- Operating/reporting currency distinction is visible and data-tested.
- `#dataManagement` exists; every one of the sixteen existing destinations proves its §9.6 live-
  state minimum; Channel is disabled/labelled where the endpoint lacks channel grain; all five
  currencies are governed-live or explicitly disabled/unavailable in reference order.
- Exact zero, filtered empty, no evidence, insufficient model evidence, privacy unavailable, workflow
  unavailable, stale, missing, corrupt, and partial are distinct.
- Forecast Weekly/Daily/Monthly disposition is exact and no monthly quantile is formed by summing
  weekly P50/P90; Forecast/Replenishment selection is controlled and filtered-empty export is a
  disabled no-call state.
- Competitor selection/queue states and preview-only Add Competitor/Create Promotion options are
  live, local-only, and mutation-free; hidden structural modals do not count as live coverage.
- Synthetic margin appears only at the approved §8.3.2 position, while competitor exclusion updates
  visible field, request echo, result reason, and accessible text together.
- Static header metadata is AT-visible/non-pointer/no-handler; real link styling has a real action.
- No original reference sample facts or production mocks remain.
- No enabled-looking control is inert; no disabled control has a mutating handler.
- No internal phase, roadmap, package, or implementation wording appears in business UI.
- Keyboard, focus, screen-reader, contrast, responsive, table, modal, and live-region checks pass.
- All twenty destinations have 1440×1100 and 390×844 screenshots plus 1024 smoke matching approved
  references; every tab/non-default panel/live-read-only-preview modal has its required surface-
  state capture and approved mobile sampling.
- Supported browser/OS and independent human review pass for each page and whole-demo flow.
- Rich and naturally sparse UI states come from the active verified bundle; the non-active sparse
  harness and isolated stale/missing/panel-failure adapters leave artifact/database state unchanged.

### 10.10 No-go conditions

Phase 5 or Demo 5 cannot be accepted if any condition below is true. Element-level UI acceptance is
owned by the approved §8 matrices and §9 state matrix; this list does not duplicate every row.

1. Phase 4 source/forecast/inventory/activation authority remains contradictory or is chosen by
   assertion rather than retained evidence.
2. A result-bearing task starts before its required contract, pre-result protocol, or independent
   foundation gate is frozen.
3. Business-effective or landing time is treated as historical known-as-of evidence.
4. Gate B is rewritten by the v2 readiness sidecar, or the sidecar changes the base publication/pin.
5. A readiness role, flag, or sufficiency value comes from a caller boolean, hard-coded default, or
   missing producer.
6. Direct expected-pin checking still depends on the stale default run; any Phase 5 pin operation
   omits explicit run, pin/authority paths, job purpose, evidence root, retailer, tenant, or
   environment.
7. Selection resolution uses capability-only/newest/implicit lookup, accepts zero/multiple matches,
   or invents a predecessor for genesis.
8. Rich and sparse pins, evidence, rebuild lineage, manifests, verifiers, or materializations are
   mixed or substituted for one another.
9. A source-identity change reuses downstream feature/forecast/inventory bytes without the required
   rebuild, or a sidecar-only correction unnecessarily rewrites the base publication.
10. Price panels leak future-known facts, cross markets/currencies, double-count channel grain, or
    omit assessed/withheld membership and reason.
11. Model candidates, thresholds, folds, origins, confirmation data, or demo targets change after
    results are visible.
12. Producer acceptance is trusted without an outside-set verifier, or a mismatch is repaired by
    mutating the closed artifact.
13. Any recommendation lacks accepted response evidence, current forecast context, local pricing
    policy, support clamp, scaled/absolute cap, dominance/tie-break, or pricing-protection evidence.
14. Generated/synthetic cost is relabelled client-actual, changes primary recommendation logic, or
    activates `price_margin`.
15. Competitor match/price evidence lacks approved provenance, source-native attributes, evaluation,
    freshness, exclusion, or exact verified-foundation binding.
16. Promotion status/mechanic is inferred from the same field; scope/conflict/privacy rules drift;
    or the Decision-#53-negative branch emits Planner numeric/live claims.
17. Privacy-restricted targeting, segment response/offers, bundles, or cannibalisation becomes live
    without a separately reopened approved decision.
18. A bundle omits rejected/insufficient populations, has circular identity, is not independently
    verified, or its manifest/verifier/database facts disagree.
19. Materialization activates, activation rematerializes, result-selection events and activation-set
    are split across stores/transactions, a partial transaction survives, a JSON receipt becomes
    authority, more than one activation-set is current, or sparse becomes publicly active.
20. The Go server starts without the schema-valid secret-free local config, receives a DSN/credential
    from that retained config, fails to validate retailer/tenant/environment/bundle/activation scope,
    or accepts browser/query authority selection.
21. A request path reads files/MLflow/models, refits, mutates governed state, or executes an
    unbounded query/export.
22. 409, 503, unavailable, exact-zero, filtered-empty, and panel-failure states are conflated or
    require corrupting accepted data.
23. OpenAPI, Go/TypeScript/runtime schemas, PostgreSQL views, and UI values disagree.
24. Any original HTML sample number, production mock/fallback, fabricated margin, synthetic
    lifecycle/mechanic, or unsupported converted operating price appears as live data.
25. A visible element is omitted/reordered/renamed/repositioned or behaves differently from its
    approved §8 matrix row without a reviewed amendment.
26. An existing shell/Data Management/Forecast/Inventory surface changes without its approved
    `P5-0P` amendment, or an implemented destination becomes unreachable.
27. The exact navigation hierarchy/order/icon/label/query/history/focus contract drifts; an
    unavailable destination looks enabled or causes a request/history transition.
28. Store, Channel, market derivation, reporting currency, global/page filters, counts, details,
    selection, and export do not resolve one coherent scope.
29. A control appears enabled but is inert, or an unavailable/mutation control has a request,
    write, history, or active-state effect.
30. Required modal trigger/title/body/footer/order/focus/close/return, preview disclosure, result
    transition, or zero-effect behavior differs from §8.8.
31. Required export population, limits, headers, filename, encoding, formula neutralization,
    lineage, stale/count handling, or no-partial-download behavior differs from §8.
32. Responsive order, keyboard, focus, screen reader, contrast, live region, table semantics, or
    reduced-motion behavior fails its matrix/test.
33. Required rich, naturally sparse, exact-zero, filter-empty, loading, partial, privacy/workflow
    unavailable, stale, missing/corrupt, and panel-failure states lack immutable evidence.
34. Required desktop/mobile/breakpoint captures or independent per-page/whole-demo human review is
    missing; passing unit tests alone is insufficient.
35. `plans/local/tasks.md` marks work complete before its cited contract, artifact, API/UI,
    screenshot, accessibility, and reviewer evidence exists.
36. Phase 5 creates or requires an API/UI container, OCI archive, deployment startup authority,
    process drain/cutover, registry/origin push, PostgreSQL portability dump, or cross-host restore.
37. Production authentication, mutable workflow/governance state, high availability, scale, or
    release hardening is claimed as Phase 5 scope.
38. Any plan approval is treated as authorization to implement, stage, commit, push, deploy, or
    mutate external state before the explicit go-ahead and package gate.

---

## 11 · Test and evidence matrix

### 11.1 Contract tests

- validate every new/changed JSON Schema, YAML policy, OpenAPI document, screen matrix, and retained
  evidence record, including closed enums and `additionalProperties` rules;
- verify cross-language canonical fingerprints and IDs against shared golden vectors;
- prove the readiness sidecar points one-way to the base publication/Gate artifacts and cannot
  change their identities;
- prove every readiness value maps to a registered primitive producer and that missing producers
  fail closed;
- test expected-pin explicit run/pin-path/authority-path/job-purpose/evidence-root/retailer/tenant/
  environment inputs, deterministic bytes, relative `$schema`, rich/sparse isolation, stale-run
  refusal, and the existing `tools/dev.py --run` bypass regression;
- test selection-v2's schema-enforced identity exclusions, legacy-v1 omission compatibility,
  conflicting-vector refusal, and Python/Go/database/builder golden parity;
- test full retailer × tenant × capability × environment lookup, record-ID validation, rich-local/
  sparse-dev isolation, zero/multiple refusal, and exact genesis/successor proof;
- validate price panel, response run/acceptance/verifier, recommendation, simulation, cost,
  competitor, promotion, bundle, intent, and activation-set schemas with positive/negative vectors;
- prove source and result selection semantic identity excludes lifecycle/approval/selection-ID/
  declared-exclusion metadata while complete lifecycle record identity includes required approval
  evidence; bundle/verifier metadata is forbidden from the selection payload;
- verify bundle manifest closure and outside-set verifier ordering with cycle/tamper vectors;
- verify materializer and activation contracts are separate; result-selection events and the
  activation-set commit/rollback together; the post-commit receipt is deterministic but never read as
  authority; and one active set is enforced;
- validate the local-serving-config schema, canonical fingerprint, DSN-env-name constant, secret-
  absence, startup scope/bundle/database checks, and request-time authority refusal;
- validate OpenAPI ↔ generated Go/TypeScript/runtime types and reject unknown page payloads;
- assert the API route inventory contains only approved GETs and bounded non-mutating POSTs;
- validate pagination, query caps, error envelopes, export registry/scope/revision/count/headers/
  encoding, and exact no-truncate behavior;
- validate every §8 screen-matrix row and approved existing-page amendment against the original HTML
  selector/order/text/behavior inventory;
- prove modal trigger/title/body/footer/focus and direct-export registries have no missing,
  duplicate, or unreachable mandatory entry;
- assert the repository contains no Phase 5 release/container/cutover/dump contract or task.

### 11.2 Source, ingestion, and temporal tests

- raw → staging → canonical row/field lineage and deterministic repeat ingestion;
- native observed/posted/extracted versus landing-backfill, business-effective versus known-as-of,
  late arrival/correction, duplicate/conflict, and timezone/DST cases;
- unit, pack, tax, gross/net, promotion price, currency, category, store, and channel normalization;
- generated-cost provenance/derivation/source identity preservation; legacy `ERP_ACTUAL` cannot
  become client-actual;
- computed-WAC receipt chronology, method-label refusal for unimplemented FIFO, same-currency/unit,
  the 73 mislabelled rows, all 68 unavailable rows, and actual-or-absent `derived_lane_wac`;
- competitor source legality, source-native attributes, match/freshness evidence, and synthetic-demo
  disclosure;
- promotion scope-row AND/OR, geography, target precedence/conflict, and distinct source-native
  lifecycle/mechanic fields;
- normal pipeline creation of one deterministic v2 readiness sidecar after base publication
  retention, with unchanged Gate B/base identity and separate retention manifest;
- every readiness producer's explicit policy hash and scope; missing/unregistered/caller-invented/
  tampered producer inputs fail closed;
- Gate A/B/v2/selection positive, refusal, contradiction, fingerprint, and publication-mismatch
  fixtures;
- generated versus client-actual cost proves data-ready plus
  `COST_NOT_CLIENT_ACTUAL` non-claim versus eligible client margin;
- expected-pin generate/check requires prior active source selections plus explicit run, job purpose,
  pin path, authority path, evidence root, retailer, tenant, and environment; rich-local and sparse-
  dev paths pass independently;
- direct no-run check regression and normal `tools/dev.py --run` caller regression;
- wrong run/root/path/scope, missing/conflicting operation, implicit discovery, invalid relative
  `$schema`, capability-only lookup, false genesis, and ambiguous successor fail;
- each feature/forecast/inventory run, verify, publish, and materialize command consumes the explicit
  lineage pin/authority; sparse execution fails if any consumer reads the shared rich/default pin;
- Config Builder/default/validation/import/export/preset synchronization is lossless and
  deterministic on the available development host;
- every §1.8.3 resume row: source change fully republishes/repins, sidecar-only change preserves
  base/pin, and later changes restart at their first consumer.

### 11.3 Price-panel and model tests

- PIT last-observation carry-forward and maximum staleness;
- weekly coverage denominator and observed/carried distinction;
- price-level tolerance/support and real transition detection;
- stockout/censor/exposure and zero-demand handling;
- no future input leakage across every rolling origin;
- Poisson GLM terms/offset/convergence against frozen numerical examples;
- market-local tiers and no cross-market pool membership;
- DerSimonian–Laird shrinkage against hand-computed vectors;
- episode block construction, seed derivation, exactly 200 draws, valid-draw rules;
- rolling-holdout Poisson deviance and baseline comparison;
- Decision-#74 exact 13-origin registry, frozen spacing/window/market-alignment/surplus selection,
  origins 1–8 development, origins 9–13 untouched, ≤20 candidate registry, one frozen candidate,
  fewer-than-13 refusal, and proof confirmation/excluded surplus origins were not read during
  selection;
- boundary tests for every strict gate;
- department coverage/count assessment and sparse reason hierarchy;
- independent verifier deliberately perturbs primitives to prove refusal.

### 11.4 Recommendation, money, cost, and scenario tests

- candidate enumeration, observed-support/no-extrapolation, local grids/endings, floors/ceilings,
  2%-at-0.70-to-5%-at-1.00 scaled maximum, absolute 5% cap, and proof no minimum action exists;
- projected units/revenue formula including beta and price-ratio boundary cases;
- dominance, tie-break, rounding then revalidation;
- Hold golden case where a distinct on-grid/in-support candidate passes every hard guard but fails
  objective/dominance improvement, plus proof that below-2%-alone never forces Hold;
- protected product, conflict, missing/stale policy/price/forecast/response;
- current-origin non-PIT forecast disclosure and refusal to use
  `LANDING_BACKFILL_DEPENDENCY` evidence for historical PIT evaluation;
- WAC and genuine verified FIFO-or-unavailable cost at/before origin; stale/future/missing/non-
  positive/wrong-currency cost; client-actual versus generated temporal provenance;
- real/synthetic/unavailable aggregation truth table;
- gross margin value/percent and local minor-unit rounding;
- Expected/Best/Worst and Current/Proposed/Recommended scenario reconciliation;
- off-grid/range/max-change/unsupported horizon/competitor-unavailable refusals;
- no persistence side effect from simulation.
- confidence-filter population rules, assessed-denominator High confidence, ≥90-only action mix,
  non-blocking recommendation risk, and hard-failure withheld reconciliation.
- each foundation acceptance/manifest closes before its outside verifier; manifest/acceptance/
  verifier tampering or order reversal refuses. `P5-5` consumes both exact manifest fingerprints
  and accepted verifier-record hashes and does not recompute either foundation;
- pricing-protection overlap, no-overlap, conflict, missing, ambiguous, and D23-negative cases prove
  that Planner refusal never bypasses the mandatory recommendation guard.

### 11.5 Competitor tests

- match identity/effective dates and attribute score components;
- disjoint truth-set minimum populations, precision, recall, false-match, confidence calibration,
  missing-attribute cohorts, and exact threshold boundaries;
- generator truth can evaluate but cannot appear in the served match artifact;
- exact threshold boundaries for Matched/Review/Rejected/No Match;
- stale/fresh time boundary and availability enum mapping;
- unit/currency normalization, difference direction, equal tolerance;
- exclusion of inadmissible match from recommendation;
- bounded response respects all local guards;
- KPI/table/filter/detail/export reconciliation;
- disabled form controls and absence of mutation endpoints;
- prohibited source option cannot be selected or submitted.

### 11.6 Promotion tests

- Decision-#53 refusal before `P5-D23` and positive authorization only after the recorded amendment;
- package-completion tests for positive numeric, positive descriptive-only, and negative refusal;
  conditional numeric requirements are non-applicable on the valid negative package;
- exact package member inventory: positive numeric retains assessment plus accepted numeric outputs;
  positive descriptive retains rejected/insufficient/not-evaluated response/simulation assessments
  with zero accepted projection/opportunity rows; negative contains no Planner Parquet;
- foundation disposition is only amended/not-amended and closes before its outside verifier; final
  package disposition is written only after model assessment. Neither disposition may self-reference
  an enclosing manifest or future verifier, and the bundle binds foundation/package hashes separately;
- negative package first-failure is `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` for all Planner/Forecast
  elements while Decision #19 remains secondary metadata; amended privacy-only elements use
  `privacy_restricted`; every element family follows the frozen `P5-D2` precedence row;
- plan/history origin visibility and refusal of landing backfills for training;
- promotion episode/comparison construction, confounder exclusions, minimum treated/pre-period/
  mechanic support, episode uncertainty, compatible exact 13-origin Decision-#74 registry,
  baseline, and final holdout gates;
- promotion Confidence: exactly 200 seeded episode-block attempts, valid-draw denominator, positive-
  incremental-unit numerator, 50-draw minimum, unrounded 80/90 boundaries, aggregation, rounding,
  null/reason behavior, and proof it differs from pricing/match confidence;
- AND within scope row and OR across rows;
- market-qualified geography and SKU > department > category precedence;
- equal-precedence conflict refusal;
- baseline/promoted/scenario formulas; normalized portfolio-outcome component/weight/direction/
  missing/bound/rounding vectors; Baseline = 100; exact four-scenario order; single axis caption; and
  accessible native-unit table reconciliation;
- inventory readiness against pinned positions/recommendations/transfers;
- conditional numeric revenue and primary client-actual-cost margin; generated cost leaves every
  Promotion Planner margin/result unavailable and has no promotion synthetic scenario;
- disabled Run Simulation and unavailable KPI/chart/table/result assertions when `P5-D20` is
  unapproved or fails;
- disabled Run Simulation/null Confidence assertions when `P5-D22` is unapproved, under 50 valid
  draws, or below the 90% unrounded threshold;
- descriptive aggregate-audience mix only, small-cell/privacy rules, and proof it never enters
  response, offer, recommendation, or simulation inputs;
- privacy-restricted null/reason for cannibalisation/bundle/customer output;
- calendar Month View initial-active/live, month-change/overlap/no-overlap/empty cases, selector-focus
  retention, List View exact disabled reason/no handler/request/history/active style, and Close-only
  footer; no unapproved list body exists;
- no persistence side effect from simulation or disabled create form;
- aggregate audience percentages and rounding remainder reconcile to exactly 100%.

### 11.7 Bundle, database, activation, and API tests

- rich/sparse manifest schema, physical inventory, checksum, count, identity, lineage, and
  unavailable-membership verification;
- independent verifier implementation and close-before-verify ordering; tamper, cycle, missing
  member, producer/verifier mismatch, and cross-lineage substitution refusal;
- prospective selection-v2 intent ID recomputation, legacy-v1 compatibility, and proof that
  lifecycle/approval/declared-exclusion metadata cannot change semantic selection ID;
- migration upgrade from the Phase 4 head, rerun idempotency, constraints, indexes, and current-view
  correctness;
- each bundle materializes transactionally and independently; injected failure leaves no partial
  rows or activation change;
- materialization is queryable but non-active; rich activation is a separate transaction; injected
  failure at each result-selection/activation insert rolls back all new rows and preserves the prior
  current event;
- full-scope genesis/successor, one-current-event, exact bundle/selection membership, source-file-
  ledger versus result-database-ledger boundary, and sparse non-activation tests;
- activation receipt byte reproducibility, database reconciliation, delete/regenerate safety, and
  proof that no server/runtime path reads the receipt;
- local startup refuses missing/invalid/noncanonical/secret-bearing config, missing/wrong DSN env,
  database, retailer, tenant, environment, activation ID, bundle hash, inactive selection, or browser-
  supplied authority;
- every endpoint contract, filter, sort, pagination, summary denominator, detail, calendar,
  governance, alert, and structured error path;
- typed 409 stale; 503 missing/corrupt/incompatible; element-level unavailable and panel-local
  failure without unrelated page loss;
- request-time no-file/no-model/no-MLflow/no-refit/no-write assertions;
- stateless simulation limit, validation, deterministic response, cancellation, timeout, and
  zero-database-write tests;
- query plan/index/bounded-row tests and concurrent read consistency;
- Price Recommendations and direct-export `N=0`, `N=L`, `N>L`, stale revision, server recount,
  invalid IDs, selected-visible/current-filtered, safe filename, Content-Type/Disposition, UTF-8/
  Excel-compatible encoding, quoting, formula-neutralization, lineage, and no-partial-download
  golden bytes;
- OpenAPI ↔ Go ↔ TypeScript ↔ runtime schema agreement;
- live rich local smoke, isolated non-active sparse integration, and non-mutating negative-adapter
  smoke;
- repository/task scan proving Phase 5 did not introduce container, release, cutover, or dump
  implementation.

### 11.8 React unit/integration tests

- page ID/title/subtitle, exact reference navigation tree/parent-submenu state, and all desktop/
  mobile navigation routes;
- explicit individual parity disposition for Executive Overview, Performance Insights, Reports &
  Exports, Alerts & Notifications, Model Management, User Management, and Settings; exact desktop/
  mobile group/order/icon/label; native disabled state/reason and zero handler/request/history for
  every unimplemented item; any omission has its own approved amendment;
- exact `#dataManagement` root and destination-specific §9.6 live-state assertions for Data
  Management, Demand Forecast, and all fourteen Inventory destinations;
- exact Data Management toolbar order; Add Data Source has only the approved preview-only form with
  disabled Connect and zero request/write/history; Upload Sample Data and Run Validation remain
  disabled/accessibly reasoned with zero handler/network/write; latest retained Validation Results
  appears only in the approved read-only source detail/mapping flow;
- canonical `?page=` direct URL, Demand-Forecast no-route/invalid normalization, refresh, user
  `pushState`, initialization `replaceState`, same-page no-op, `popstate` back/forward, and exact
  active/submenu/scroll/focus restoration; hash is not a second router;
- shell/page authority decoupling and panel-local error boundaries;
- filter dependency, one-effective-Store global/page synchronization, query keys, request
  cancellation, and summary/table/export consistency;
- frozen search debounce request count, retained data/focus, and out-of-order response rejection;
- operating/reporting currency rendering and FX disclosure;
- INR/USD/EUR/GBP/AED reference-order coverage with each option governed-live or natively disabled;
  per-destination Store/Channel applicability and no Channel query/cache key where grain is absent;
- no visible Market control; Store selection plus reviewed local server scope derives market, browser-supplied
  market identity is ignored/refused, and mixed all-store rendering follows governed reporting FX;
- exact element/column/control/tab/card/modal order and required IDs;
- field-specific enum badge/label mapping;
- Pricing Decision Quality API value, DOM text, CSS custom property, pseudo-content removal, and
  computed conic-gradient percentage agree at 0/boundary/partial/100;
- exact zero vs empty/insufficient/unavailable/stale/missing/partial;
- structure-preserving skeletons and accessible error/remediation messages;
- Price Recommendations and Competitor zero/one/many/select-all-visible/indeterminate/reset
  selection; Forecast/Replenishment controlled selection and filtered-empty Export no-call;
- Forecast Weekly live plus accessible Daily/Monthly disabled dispositions; reject summed-weekly
  monthly P50/P90 and any disabled-option request/query-key change;
- local selection/Compare/Export/detail/stateless simulation; synthetic margin exists only in the
  approved panel and competitor Include/not-included UI/request/result truth agrees;
- Price Recommendations export covers exact selected/filtered/all counts/defaults/zero/limit states,
  recommendation-only population, the five filters All bypasses versus the authority/Store/Channel/
  currency scope it retains, withheld-assessment exclusion, CSV versus Excel-compatible encoding,
  disabled PDF/audit, controlled filename/extension, cancellation, response headers/lineage, and
  unsafe filename/formula-cell refusal; existing direct exports expose only the approved registered
  CSV route/metadata behavior, including full-filtered/current-page-selected scope, every
  `L_direct` boundary, stale revision/refusal, and no truncation;
- Promotion Calendar initially renders Month View active/live; List View remains natively disabled
  with `Governed list-view composition not approved`, no handler/request/history/active style or list
  body; a month change retains Month View and selector focus; the modal footer is Close only;
- every control has exactly one of `business_live`, `read_only`, `preview_only`, `hard_disabled`, or
  `structural_only` as its matrix state; hard-disabled workflow/privacy/source actions have no handler;
  every mandatory new/existing preview-only trigger shows its treatment, permits only local option
  exploration, keeps prohibited options/submits disabled, and makes zero request/write/history change;
- competitor modal parity targets only the authoritative `#newCompetitor*` and `#competitorRule*`
  selector families; every later `#fixCompetitor*` and `#fixRule*` duplicate is recorded as
  `structural_only` and has no runtime handler, rendered duplicate modal, capture, or demo credit;
- exact §8.8.5 Forecast titles, summaries, fields/options, six-column version table, scenario result
  summary/table, Action Center summary/four-column queue, Store Drilldown controls/cards/footer, and
  Data/Stock Health/Inventory/Replenishment modal mappings—including exact selectors, visible trigger
  labels, distinct modal titles, fields/options, footers, and access/capture states—match the contract;
- Forecast and Promotion unavailable branches expose distinct `Preview Results` controls while their
  original submits remain disabled; result layouts preserve exact composition with typed unavailable
  values and make no request. Price Simulation Result opens directly from its page trigger, Forecast
  and Promotion results replace their named parent dialogs, and no hidden parent remains. Review
  Match preserves Reject → Link → Accept → Cancel, adds no
  Previous/Next, and Link replaces body/footer without changing or stacking the modal title;
- card-header static metadata has non-pointer cursor, semantic text exposure, no handler/tab stop;
  real actions have semantic role, accessible name, focus, and handler;
- modal title-first focus, exact title → X → body → footer forward cycle and reverse wrap,
  X/Cancel/Close/Escape/backdrop equivalence, pending-request abort, result/in-place replacement,
  exact trigger/H2 focus return, live regions, tables/captions, labels/descriptions;
- strict schema rejection of wrong type/unit/currency/date/reason;
- no production sample constants or internal phase/policy/fingerprint wording.

### 11.9 Visual, accessibility, browser, and human evidence

For all twenty implemented destinations, including existing pages with no local Phase 5 change:

- capture 1440×1100 default rich state;
- capture 390×844 mobile rich state with navigation reachability;
- run 1024px breakpoint smoke;
- capture representative sparse, exact-zero/filtered-empty, partial, loading, 409, 503, and panel-
  failure composition states, proving unaffected panels retain their layout/data;
- execute the surface-state capture manifest so every tab/non-default panel and every live/read-
  only/preview modal has a desktop capture plus keyboard/human result; link every §8.8/§9 surface ID
  and document any approved representative mobile/shared-modal sampling;
- compare original layout, tokens, order, spacing, overflow, sticky behavior, and modal bounds;
- verify tables remain usable with horizontal scroll and headers/context;
- run automated accessibility checks plus manual keyboard/screen-reader/focus review;
- verify the supported local browsers available during Phase 5; the three-OS blocking matrix is a
  Phase 7/8 release-hardening gate, not a Phase 5 exit requirement;
- have an independent reviewer compare DOM text/order, live values, currency, and screenshots;
- record reviewer, date, run/version, viewport, environment, result, and approved deviation.

### 11.10 Demo evidence

- execute the rich client script, including naturally sparse cohorts, from a clean app start; run
  the full-sparse refusal script through the isolated non-active integration harness;
- record source, forecast, inventory, pricing run/version, bundle, and rich activation event;
- prove each §9 state by API identity and visible page location;
- verify no dev server mock, fixture toggle, or original sample fallback is enabled;
- export one scoped result and reconcile it to screen/API/artifact;
- exercise mobile navigation, direct link, back/forward, filter, currency disclosure, stateless
  simulation, read-only detail/queue, preview-only modal with zero side effects, disabled mutation,
  409, and 503;
- record unresolved limitations as client-facing unavailable behavior rather than hiding them.

### 11.11 Local phase-exit command and host evidence

The exact new Phase 5 materialize, activate, sparse-harness, and smoke command names/arguments freeze
in `P5-3` before implementation. They must expose explicit bundle/manifest/verifier, database,
audience, and activation identifiers; no default discovery or browser authority is allowed.

Run the existing repository gates on the designated local development host:

```bash
python3 tools/dev.py contracts
python3 tools/dev.py boundaries
python3 tools/dev.py test
python3 tools/dev.py db-test
python3 tools/dev.py api-test
python3 tools/dev.py ui-test
python3 tools/dev.py ui-build
python3 tools/dev.py wheels --offline
python3 tools/dev.py verify
```

The equivalent PowerShell syntax is:

```powershell
py -3 tools\dev.py contracts
py -3 tools\dev.py boundaries
py -3 tools\dev.py test
py -3 tools\dev.py db-test
py -3 tools\dev.py api-test
py -3 tools\dev.py ui-test
py -3 tools\dev.py ui-build
py -3 tools\dev.py wheels --offline
py -3 tools\dev.py verify
```

Before the normal rich repin/rebuild, direct expected-pin checks use the exact interface frozen by
`P5-1`; no required authority input is implicit:

```bash
python3 tools/build_expected_pin.py --check \
  --run <reviewed-run-id> \
  --pin-path <reviewed-pin-path> \
  --authority-path <reviewed-input-authority-path> \
  --job-purpose <reviewed-job-purpose> \
  --evidence-root <reviewed-evidence-root> \
  --retailer-id <reviewed-retailer-id> \
  --tenant-id <reviewed-tenant-id> \
  --environment <local-or-dev>
```

Phase-exit stateful order is evidence-bound and local:

1. verify both closed bundles outside their artifact sets;
2. apply the reviewed idempotent migration;
3. materialize rich and sparse independently without activation;
4. prove both are queryable and the prior active event is unchanged;
5. prepare and independently check canonical rich result-selection v2 event bytes;
6. insert those result-selection events and one activation-set in one PostgreSQL transaction;
7. export/reconcile the deterministic post-commit receipt and prove it is not a serving input;
8. validate the secret-free local config plus environment-managed DSN, then start
   `go run ./cmd/server` from `api/` using the reviewed local rich scope and the established
   Compose PostgreSQL convention;
9. execute rich HTTP/UI smoke, then stop the local process cleanly;
10. execute the sparse refusal suite through the isolated non-active integration harness;
11. run negative-state adapters and prove no artifact/database mutation;
12. run `tools/dev.py verify` once after final local state is established and retain command,
    versions, exit code, suite counts, IDs/hashes, and reviewer result.

Application-layer portability remains required: Python/Go/TypeScript paths and commands must avoid
POSIX-only assumptions, and both shell-family command forms stay documented. Evidence may be
collected on the development hosts available to the project. A blocking three-OS release matrix,
identical OCI-image import, PostgreSQL dump handoff, and logical cross-host restore belong to
Phase 7/8 release hardening and are not Phase 5 exit evidence.

No command in this section is authorized merely by plan review. It becomes executable only after
the corresponding implementation package and explicit user go-ahead.

---

## 12 · Security, privacy, and operational constraints

1. Phase 5 exposes read endpoints plus explicitly non-mutating stateless calculation POSTs that
   create no persistent domain state. Request bodies are bounded and not logged with sensitive
   contents; no-DB-write assertions are mandatory.
2. Retailer × tenant × environment plus bundle and activation IDs are bound by the schema-valid,
   canonically fingerprinted, secret-free reviewed local server configuration and partition queries,
   caches, exports, and detail IDs; market/store/channel/currency scopes are validated within it.
   The retained config names only the constant `RETAIL_POSTGRES_DSN` boundary and never contains a
   DSN, password, token, or host credential. Client-provided labels never establish or switch
   authority.
3. Engagement competitor collection uses approved client/licensed sources only. Local generated
   rows retain canonical `evidence_class = synthetic`, a versioned derivation class, and exact
   source identity; “Synthetic demo” is a display/use-purpose disclosure, not a provenance class.
   They are never represented as observed market/client facts. Credentials/URLs are secret-managed
   and not emitted in artifacts, API payloads, logs, or screenshots.
4. Customer identifiers, basket records, and customer-level predictions do not enter Phase 5
   artifacts. Aggregate audience output obeys minimization, suppression, and retention policy.
5. Money uses integer minor units or contracted exact decimals with ISO currency; float display
   never becomes calculation authority.
6. Simulation inputs have strict body, precision, range, time, and concurrency limits. There is no
   arbitrary expression/model execution.
7. Exports are bounded, scoped, lineage-bearing, and safe against spreadsheet formula injection.
8. Logs/telemetry contain IDs/reasons/timings, not customer PII, secrets, or full payloads.
9. Error responses disclose remediation and governed lineage without paths, SQL, stack traces, or
   credentials.
10. PostgreSQL migration/materialization/activation roles are separated. Serving credentials cannot
    mutate artifact/activation state.
11. Rejected/accepted artifacts and evidence follow repository retention; no destructive rewrite is
    used to “clean” failed runs.
12. Repository CI remains prohibited under the current validation policy. Required suites run in
    approved local/controlled environments and their evidence is checked in according to policy.

---

## 13 · Sequencing and review gates

### 13.1 Dependency graph

```text
P5-0 entry reconciliation
  +--> P5-0P existing-screen audit/amendments ---------------------------+
  |
  +--> P5-1 source + readiness + full-scope pin contracts
         -> P5-1P pre-result model/evaluation/demo freeze
              -> P5-2 rich/sparse publication + pin + upstream rebuild
                   -> P5-3 artifact/API/UI contract freeze
                        +--> P5-4 response models -----------------------+
                        +--> P5-6A competitor foundation ----------------+--> P5-5 recommendations
                        +--> P5-7A promotion foundation -----------------+        |
                                                                                +--> P5-6B monitor
                                                                                +--> P5-7B planner
                                                                                         |
                                                                                         v
                                                              P5-8 verify/materialize/
                                                              rich-activate/local API
                                                                                         |
                                                                                         v
                                                                      P5-9 exact UI + Demo 5
```

`P5-6A` and `P5-7A` are independently verified prerequisites to `P5-5`; the
not-amended promotion refusal foundation is a valid branch. `P5-6B` and the applicable `P5-7B`
consume the exact foundation/verifier hashes cited by `P5-5`. Static new-page structure may be
reviewed against generated contracts, but it is not live/demoable before `P5-8`, and no existing
screen changes before its `P5-0P` amendment.

Within `P5-8`, bundle verification precedes materialization; materialization precedes preparation of
result-lifecycle bytes; one database transaction inserts the verified rich lifecycle events and
activation-set; the non-authoritative receipt is exported after commit; config/database/activation
validation precedes local server smoke. Sparse never enters the public activation path.

### 13.2 Required review gates

| Review | Required decision/evidence | Authorizes next |
|---|---|---|
| Entry | coherent retained Phase 4 authority, expected-pin/direct-check nuance, full-scope defect, readiness/cost/resume findings | `P5-1` |
| Existing UI | exact audit, matrix amendments, navigation/modal/export/state dispositions | affected existing-screen changes |
| Temporal/source | native availability, sidecar identity, selection-v2/legacy-v1 parity, input-authority schema, explicit pin/full-scope/downstream-path contracts, Config Builder | `P5-2` generation |
| Pre-result protocol | frozen response/promotion/match protocol, mappings, seeds/origins, decided chart index/table, demo-state target | result inspection |
| Source/pin/rebuild | verified rich/sparse publications, active rich-local/sparse-dev source selections, explicit pins/input authorities, rich default repin, separate upstream rebuilds | `P5-3`/`P5-4` |
| Contract freeze | artifact/policy/database result-event/activation/receipt, secret-free serving config, API/export/screen contracts and golden vectors | model/API/UI implementation |
| Statistical | independent panel/model/shrinkage/resample/holdout/gate evidence | accepted response |
| Competitor/legal | source legality and independently verified foundation | recommendation consumption |
| Promotion/privacy | protection foundation plus amended numeric or not-amended refusal branch | recommendation/planner consumption |
| Recommendation/cost | local rules, candidate order, cost truth table, scenarios/explanations | bundle assembly |
| Bundle publication | separate closed manifests and outside-set verifier records | materialization |
| Materialization | per-bundle transaction reconciliation and no activation side effect | lifecycle/activation preparation |
| Local activation/API | one atomic PostgreSQL rich result-lifecycle/activation-set transaction, derived receipt proof, secret-free local config, OpenAPI/types, smoke and sparse non-active harness | React live integration |
| Page | matrix, DOM/data/state/visual/keyboard/accessibility/human evidence | individual page demoability |
| Demo 5 | whole-flow evidence and no-go audit | Phase 5 exit |

### 13.3 Suggested implementation slices

After contract approval:

1. readiness/full-scope pin and source profile foundation;
2. response panel/model/acceptance;
3. competitor and promotion foundations;
4. revenue recommendations and guarded scenarios;
5. verified bundles, database materialization, separate rich activation, and local API;
6. shared shell/routing/filter/error/modal/export primitives;
7. Price Recommendations and Price Simulation;
8. Competitor Monitor and Promotion Planner;
9. approved existing-page corrections;
10. whole-application state, accessibility, visual, and Demo 5 evidence.

Each slice lands only when its source/artifact → database → API/schema → React values reconcile.
A structural shell may be reviewed earlier but is never labelled live.

---

## 14 · Risks and mitigations

| Risk | Consequence | Enforceable mitigation |
|---|---|---|
| contradictory Phase 4 identities | mixed upstream truth | `P5-0` retained-evidence reconciliation; unresolved stays unresolved |
| stale expected-pin default is overstated or ignored | misleading status or broken direct check | record `tools/dev.py --run` bypass; require explicit run/pin/authority/job/evidence/scope inputs |
| capability-only selection lookup | cross-tenant/environment authority error | full four-field key; rich-local/sparse-dev scopes; zero/multiple refusal |
| pin generated before governed source selection | unapproved publication becomes downstream authority | source candidate → approved → active before each input-authority/pin build |
| selection schema and code exclude different identity fields | cross-language IDs diverge | immutable v1 compatibility plus schema-enforced v2 vector and shared golden IDs |
| readiness sidecar changes base identity | circular/non-reproducible publication | complete base first; one-way sidecar and separate retention |
| caller/hard-coded sufficiency | false capability claim | frozen primitive producer registry and independent recomputation |
| source change reuses downstream bytes | stale results | first-consumer invalidation and mandatory lineage rebuild |
| rich/sparse identity mixing or hard-coded default pin | false refusal/acceptance | separate local/dev source scopes; explicit pin/authority at every consumer; sparse result non-active |
| profile targets desired demo result | biased evaluation | freeze seeds/protocol/states before generation; retain failures |
| landing backfill becomes history | temporal leakage | source-native availability gate and origin-based tests |
| cross-market/currency pooling | biased prices | market-local panels/priors/policies and membership vectors |
| support/cap/rounding error | unsafe action | enumerate, round, then revalidate support/grid/scaled and 5% caps |
| revenue shown as margin | commercial misstatement | split capabilities; null/reason and copy/data tests |
| generated cost appears client-actual | misleading economics | canonical provenance and isolated labelled scenario only |
| WAC rows stay labelled FIFO | false valuation claim | immutable correction plus proof-or-unavailable FIFO |
| competitor score lacks evidence | wrong product drives response | auditable attributes, truth-set gates, freshness/exclusions |
| competitor source is prohibited | legal/privacy issue | allowlist; no scraping; explicit synthetic-demo provenance |
| promotion decision/privacy drift | unauthorized feature | `P5-D23` gate, Decision #19 enforcement, refusal branch |
| promotion status/mechanic fabrication | false workflow state | distinct native fields or unavailable |
| foundation changes during recommendation | silent guard drift | consume exact closed manifest plus accepted verifier hash |
| bundle/verifier identity cycle | unreproducible publication | close manifest first; verifier outside; prebound selection intents |
| partial materialization | inconsistent read model | one transaction with hashes/counts/invariants and rollback tests |
| activation during materialization | unreviewed data becomes current | separate operation/transaction and before/after assertions |
| file and database writes are called atomic | unrecoverable split authority | result lifecycle plus activation in one PostgreSQL transaction; JSON only post-commit receipt |
| sparse becomes public | misleading dual authority | one rich active event; sparse isolated harness only |
| browser chooses audience | authority leak | explicit secret-free server-side local config and activation ID |
| retained startup config contains DSN/credentials | secret disclosure | fixed DSN env boundary; schema/scan/fingerprint and no-secret evidence |
| request reads/refits/writes | non-determinism or phase breach | PostgreSQL-only handlers and no-file/no-write tests |
| filter/count/export drift | client contradictions | one scope revision/count contract and server recount |
| original sample values survive | fabricated demo facts | bundle/source scans and API-to-DOM reconciliation |
| UI parity work conflates preview with enabled/disabled | client demo failure | closed business-live/read-only/preview-only/hard-disabled state enum and zero-effect tests |
| promotion chart keeps contradictory scenario/metric axes | misleading client output | decided normalized scenario index, single caption, native-unit accessible table |
| existing UI regresses | damages Phase 4 work | `P5-0P` amendments plus all-page regression evidence |
| modal/export details are simplified | visible contract mismatch | exact §8 registries, byte/focus golden tests |
| screenshots replace truthful data review | false completion | DOM/data/API/artifact plus human review |
| plan grows beyond review capacity | rubber-stamp risk | §8 matrices own element rows; no-go/DoD stay outcome-level |
| release scope leaks into Phase 5 | contradicts governing plan/tasks | explicit deferral to Phase 6–8 and repository/task scan |

---

## 15 · Approval block

### 15.1 Approvals required before implementation packages

Explicit approval is required for:

- `P5-D0` through `P5-D25`, including source availability, readiness producers, selection-v2/
  legacy-v1 identity, source-selection-before-pin ordering, explicit full-scope pin/authority paths,
  statistical/chart protocol, pricing/cost, competitor, promotion/privacy, bundles, database result-
  selection/activation, secret-free serving config, read-only behavior, screens, states, errors,
  currency, and terminology;
- Config Builder rich/sparse fields, presets, and provenance;
- the four §8 machine-readable matrices and every existing-UI amendment;
- exact navigation, Store/Channel/currency applicability, modal, export, preview, responsive,
  accessibility, and surface-state capture contracts;
- competitor and promotion foundation acceptance/verifier protocols before recommendation
  consumption;
- one rich local database activation plus derived-receipt/secret-free-config proof and sparse non-
  active result harness disposition;
- each package's entry/exit evidence and independent review.

### 15.2 What approval of this plan does not authorize

Approval of this plan alone does not authorize implementation. It also does not authorize:

- rewriting immutable history, relaxing gates after results, or accepting a model;
- treating backfilled evidence as historical, generated cost as client-actual, or Gate B as the v2
  report;
- implicit/capability-only authority lookup or skipping downstream rebuilds;
- scraping, reopening Decision #19, or silently reversing Decision #53;
- any approval/review/schedule/owner/alert/match/promotion mutation;
- activating an unverified/unreconciled bundle or activating sparse;
- changing an existing UI outside an approved matrix amendment;
- creating/pushing/deploying code, branches, commits, images, data, or external resources;
- adding container release, process drain/cutover, deployment authority, database dump/restore,
  production authentication, HA, scale, or Phase 6 mutable workflow scope.

### 15.3 Evidence required to approve the next package

To authorize `P5-1`, reviewers need the complete `P5-0` authority/defect record. To authorize
generation, they need native-availability, readiness, explicit-pin/full-scope, Config Builder, and
`P5-1P` pre-result approvals. To authorize models, they need verified rich/sparse publications,
pins, rebuilt upstream identities, and frozen `P5-3` contracts. To authorize existing-UI changes,
they need the applicable `P5-0P` rows. To authorize new-page data integration, they additionally
need the approved §8 matrices and generated API schemas. To authorize rich activation, they need
verified bundles, successful separate materializations, lifecycle reconciliation, and the reviewed
local scope. Page screenshots/human reviews are Phase-exit evidence, not an implementation-entry
substitute. Verbal confirmation never replaces retained evidence.

---

## 16 · Final definition of done

Phase 5 is complete only when all applicable outcome-level conditions pass. The approved §8 screen
matrices own element-by-element UI acceptance, and §9 owns state coverage; those rows are not
duplicated here.

1. One reviewed `P5-0` entry record reconciles retained Phase 4 source, forecast, inventory,
   activation, database, API, expected-pin, and UI authority without rewriting history.
2. The stale direct-check default and existing `tools/dev.py --run` bypass are both documented and
   regression-tested; every Phase 5 pin operation is explicit.
3. V2 readiness runs in the normal pipeline as an identity-safe one-way sidecar with reproducible
   primitive producers; Gate B and base publication identity remain unchanged.
4. Selection v2 and legacy-v1 compatibility produce identical cross-language IDs; all selection/pin
   resolution uses exact retailer × tenant × capability × environment scope, validates IDs/bytes,
   and refuses zero, multiple, implicit, newest, conflicting-vector, or false-predecessor results.
5. Rich and sparse Config Builder presets round-trip losslessly and generate deterministic,
   source-native, independently verified publications.
6. Required rich-local and sparse-dev source selections are active before their input-authority/pin
   builds. The reviewed rich pin becomes the shared expected pin through the normal repin workflow;
   sparse remains an explicit non-default pin; every downstream command receives the correct explicit
   pin/authority, and both have lineage-correct feature → forecast → inventory rebuild evidence.
7. Price/promotion/competitor/cost availability and provenance remain truthful through every layer;
   the 73 WAC/FIFO rows and 68 unavailable rows have their approved successor disposition.
8. Statistical protocol, candidate registry, 13 origins, confirmation split, resampling, shrinkage,
   strict gates, mappings, the decided Promotion Performance Forecast index/table, and demo targets
   were frozen before results.
9. Market-local weekly panels have complete eligible/withheld denominators, no leakage, and
   independently verified response acceptance or exact refusal for every assessed series.
10. Recommendations exist only for accepted evidence and obey local grid/endings, support,
    dominance/tie-break, confidence-scaled and absolute caps, pricing protection, and currency rules.
11. Revenue works independently of margin. Client margin requires client-actual provenance;
    generated cost appears only in the approved visibly labelled Scenario Comparison and changes no
    primary output.
12. Price simulation is bounded, deterministic, stateless, currency-safe, reason-coded, and
    consistent with the stored recommendation inputs/policy.
13. Competitor source legality, matching, truth-set evaluation, freshness, inclusion/exclusion,
    alert facts, and read-only review states pass independent foundation verification.
14. Promotion protection is always enforced. The amended branch meets estimator/privacy/conflict
    gates, or the not-amended branch exposes exact refusal; no lifecycle/mechanic is fabricated.
15. Separate rich/sparse manifests close before their outside-set verifier records and include
    accepted, rejected, insufficient, lineage, foundation, and prospective-selection evidence.
16. Each verified bundle materializes in its own rollback-safe PostgreSQL transaction with no
    activation side effect and exact manifest/database reconciliation.
17. One later PostgreSQL transaction inserts the verified rich result-selection v2 lifecycle events
    and exactly one current rich activation-set event; injected failure rolls back all new rows,
    sparse results remain non-active, and any post-commit JSON is a reproducible receipt only.
18. The local Go server starts only from the canonically fingerprinted, secret-free reviewed rich
    config plus the environment-managed DSN, validates database/bundle/selection/activation agreement,
    reads PostgreSQL only, never reads the receipt, and cannot take browser-supplied authority.
19. All approved GET and stateless POST endpoints, OpenAPI, Go/TypeScript/runtime schemas, database
    views, error envelopes, limits, pagination, filters, sorting, counts, details, and exports agree.
20. Request-time no-file/no-model/no-MLflow/no-refit/no-write, query-bound, timeout, cancellation,
    stale 409, missing/corrupt 503, and panel-local failure tests pass.
21. Price and direct exports satisfy their exact §8 population, count/limit, scope-revision,
    filename/header/encoding/formula-neutralization/lineage/no-partial-download contracts.
22. Price Recommendations matches every approved §8.2 matrix row and demonstrates increase,
    decrease, hold, withheld, confidence/priority/risk, detail, comparison, export, zero, and empty
    behavior truthfully.
23. Price Simulation matches every approved §8.3 row, including competitor included/excluded truth,
    Current/Proposed/AI ordering, result/refusal states, and the sole synthetic-margin placement.
24. Competitor Monitor matches every approved §8.4 row, including KPIs, twelve columns, filters,
    zero/one/many controlled selection, queue/detail/rule states, and mutation-free previews.
25. Promotion Planner matches every approved §8.5 row, including KPIs, performance/opportunity/
    portfolio areas, thirteen columns, simulation/refusal, calendar Month/List disposition, and
    mutation-free preview.
26. Shared shell, navigation, global/page scope, currency, responsive behavior, accessibility,
    loading/error primitives, modal framework, and business wording match their approved §8.1 rows.
27. Data Management, Demand Forecast, and all fourteen inventory/replenishment destinations remain
    reachable and implement only approved §8.6/`P5-0P` amendments.
28. Every required §8.8 modal and contextual surface has an actual `business_live`/`read_only` or
    visibly disclosed zero-effect `preview_only` path, exact composition, deterministic focus/close/return, and
    no unauthorized network/write/history effect.
29. Every enabled filter/control scopes all dependent KPIs, panels, rows, details, selection, and
    export; every unavailable action is natively disabled with an accessible business reason and no
    mutation handler.
30. Operating prices remain in local currency; governed reporting aggregates disclose FX; Store,
    Channel, market derivation, and five-currency applicability match the destination matrices.
31. Rich and naturally sparse, exact-zero, filtered-empty, loading, partial, privacy/workflow
    unavailable, stale, missing/corrupt, and panel-failure states satisfy §9 with immutable evidence.
    Full-sparse refusal is additionally proven through the non-active integration harness.
32. Production React/API contains no original sample values, mock/fallback facts, internal phase/
    package copy, fake route, or enabled inert control.
33. All required 1440×1100 and 390×844 captures, 1024 breakpoint smoke, modal/tab/panel captures,
    automated/manual accessibility checks, and independent per-page/whole-demo reviews pass.
34. Contract, source, numerical, model, verifier, database, API, export, React, navigation,
    accessibility, visual, local smoke, sparse-harness, and negative-state suites pass with retained
    IDs/hashes/counts.
35. `tools/dev.py verify` passes once on the final governed local host, and application-layer
    commands remain portable without making a three-OS release/restore matrix a Phase 5 gate.
36. No container/OCI release, deployment startup authority, drain/cutover, registry/origin push,
    PostgreSQL portability dump, cross-host restore, mutable workflow, or production-hardening
    deliverable has entered Phase 5.
37. `plans/local/tasks.md` is updated only after each completed item cites its actual evidence; no
    checkbox is closed from plan text or verbal assertion.
38. Demo 5 truthfully shows the four new pages and approved existing-page possibilities, and every
    remaining limitation is visible, reason-coded, and client-safe.

Until every applicable item passes, Phase 5 remains in implementation/review and Demo 5 is not an
accepted client checkpoint.
