# UI Parity, Availability & Margin — Implementation Plan

**Status:** draft for review; **next implementation phase is Pricing demo-positive closure (§6.0)**
**Scope:** eliminate bare "Not available" states, restore original-HTML presentation, and make the complete governed state/value vocabulary visibly demonstrable across all 20 implemented client-demo destinations and their popups. The immediate execution scope is the four Pricing destinations only; Forecast, Inventory, Data Management and the remaining destinations resume after the Pricing phase passes its exit gate. This includes distribution quality: a populated field is not demo-complete when every visible row carries the same action, status, risk, category, confidence band, inventory state, or other enum value.
**Authority:** subordinate to `plans/local/phase5-implementation-plan.md`. All UI parity work routes through the **P5-0P** "Existing UI audit and parity-amendment gate"; margin routes through **P5-D6 / P5-D21 / P5-D24** and the bundle lifecycle. This plan proposes *bindings*; it does not override any frozen decision.

Evidence base: four full-stack traces (original HTML target spec; unavailable-state inventory with root-cause classification; color/format parity gap; margin-governance architecture), the checked-in screen contracts, and direct measurement of the currently activated artifacts. File references are anchors, not permanent line-number authority; implementation must resolve symbols again after intervening edits.

### Current measured baseline — why another distribution gate is required

The active rich Pricing artifact is not merely missing margin. Direct Parquet measurement shows:

- 9,603 assessed rows: 866 recommendations and 8,737 withheld assessments;
- of 866 recommendations, **855 Reduce, 6 Increase, and 5 Hold**;
- recommendation risk is 858 High, 2 Medium, and 6 Low;
- competitor price is populated on only 11 of 9,603 rows; Stock Cover and Forecast Demand on 866; primary margin on zero.

The default endpoint sorts High → Medium → Low priority and the UI currently requests 200 rows. In this artifact, the High cohort alone contains 287 Decrease rows and only one Increase row, while all five Holds are Low. The visible “all Reduce” result is therefore an upstream distribution-plus-business-sort failure, not merely a badge-label problem. The next phase changes the client-facing page size to 20 and replaces this population with a profit-positive, Hold-majority cohort; the current 200-row behavior is baseline evidence, not a retained requirement.

This proves that field reachability and total row counts are insufficient acceptance criteria. The replacement profile must pass an immutable state-distribution and default-viewport contract before activation; it may not be accepted merely because each enum appears once somewhere deep in an export.

---

## 0 · Read first — the governing principle

### 0.0 · PoC Data Principle — generated data IS the actual data (overrides all client-actual language in this plan)

**This is a proof-of-concept with no retailer/ERP integration. There is NO "client-actual" data of any kind — no client-actual cost, no client feed, no external cost ownership. The data produced by datagen IS the actual, authoritative data of record for every capability, cost included.** Consequently, for this PoC:

- The generated **weighted-average cost** is the **authoritative unit cost**. It is not "synthetic", "provisional", or "not client-actual" — those framings do not apply here. Margin (`price − cost`) is therefore a **first-class, always-available value** on every primary surface (Margin Opportunity KPI, Current/Expected Margin, Margin Impact, primary simulation Gross Margin), and both the Margin Protection objective and the minimum-margin floor are active on this cost basis.
- The generated Pricing profile is an explicitly designed **retailer-positive demonstration scenario**: a mostly well-priced catalog with a small number of profitable Increase and Reduce opportunities. On the default walkthrough, accepted actions may improve or preserve expected revenue and gross margin, but must not present a negative aggregate Margin Opportunity or an accepted action whose expected incremental gross margin is negative. This is achieved through source-native causal cohorts and a frozen profit guardrail—not by rewriting model outputs after inspection. Alternate refused/guardrail states remain deliberately reachable to demonstrate that the product protects the retailer from an unprofitable choice.
- The **client-actual cost gate** (`P5-D6`/`P5-D24`), the "no flag flips" cost-provenance rule in §0.1, the `Client cost required` GOVERNED-KEEP chip for margin, and the client-actual language in §A2/§A3 and §1's "remain blocked" list are **PRODUCTION-ONLY concerns kept for a future real-data deployment. They DO NOT gate any value in this PoC and MUST NOT withhold margin here.** Where the code still carries this machinery (the `cost.py` client-actual resolver, the `price_margin` selection-lifecycle path), it is **dormant** — retained for real data, never a PoC gate.
- User-facing labels must never imply a client/ERP source or carry a "synthetic / not-client-actual" disclaimer. The only honest cost label is **"weighted-average cost"** (method transparency), nothing more.

**Anti-drift rule (why this section exists):** margin was repeatedly withheld, and a review escalated it to P0, because the production client-actual gate was applied to a PoC that has no client. Do **not** re-introduce a client-actual/ownership gate, a "synthetic — not client actual" disclaimer, or a "generated cost cannot show margin" withholding for this PoC. If a future review flags generated-cost margin as a governance violation, that review is applying the production model to the PoC — the resolution is **this principle**, not withholding the value.

---

The single most important fact, and the one that reshapes the request:

> **The original HTML is a demo mock. Every number in it is fabricated. Its margin figures, NRV/provisions, forecast deltas, Demand-at-Risk, planner overrides, and promotion metrics are exactly the sample values that `phase5 §1.11` lists as a *non-authoritative defect that must not be copied*.**

The `Not available` string is **not** in the original HTML at all. It appears in the implemented app and its governed availability dispositions as the honest way to withhold a field that has no accepted evidence. That does not make the literal phrase the required presentation. So:

- **"Same as original HTML" is authoritative for _presentation_** — screen/nav order, tabs, table columns, labels, badge palette, token colors, chart shapes. This part of the request has **no governance tension** and we implement it fully.
- **"Same as original HTML" is _not_ authoritative for _values_.** We may not reproduce the mock's fabricated numbers. `phase5 §1.7`: *"the remedy for thin evidence is always an honest unavailable state."*

Therefore "I don't want 'Not available' anywhere" is delivered the **governed** way, not by printing invented numbers. Every unavailable site is driven into exactly one of four actions:

| Bucket | Meaning | Action | Result for the user |
|---|---|---|---|
| **UNLOCK** | The data already exists in an accepted artifact; the cell is withheld by a *defect* or stale contract reference (enumerated in `phase5 §1.10`). | Wire the real value; correct the matrix row. | Real number appears. |
| **DERIVE** | Required primitive data exists, but the exact governed projection/denominator is not yet materialized. | Freeze the definition, build and verify the projection, then publish it in a successor artifact. | A newly governed value appears; this is not a UI-only task. |
| **ENRICH** | The field is legitimately empty only because the demo data profile is sparse (root-cause **(b) data-absent** / **(d) conditional-null**). | Generate a **response-rich profile** (`P5-D15`) so the evidence legitimately exists. | Real number appears. |
| **GOVERNED-KEEP** | The exact value is not authorized on the active branch—for example replay/workflow/privacy evidence is absent, no compatible prior version exists, or a conditional margin/promotion/accounting gate has not passed. | **Do not fabricate.** Replace a bare missing token with a capability-specific business-reason chip, or a clearly labelled synthetic surface only where expressly permitted (`synthetic_margin_scenario`). | An informative, honest state; a number appears only after the owning evidence and approval pass. |

**Net promise:** the active-rich normal demo path contains no bare `Not available`, `N/A`, `null`, `undefined`, or unexplained em dash in a visible value location. UNLOCK, DERIVE, and ENRICH sites show accepted values. A governed residual shows a concise business-reason chip such as `Client cost required`, `Workflow not configured`, or `Replay evidence required`; the chip must not itself say only `Not available`. This is a presentation guarantee, not a false promise that every governed field becomes numeric.

### 0.1 Engineering standard — proper fixes only (no hacks, no patches)

Every item in this plan is a **root-cause fix**, not a symptom suppression. Concretely, the following are **prohibited** and appear nowhere in this plan:

- **No flag flips.** We do not set `cost_provenance = "client_actual"` on generated cost to make margin appear (`P5-D24` forbids it). Margin becomes available only via a genuine client-actual cost feed that *earns* the classification (§A3), or via the isolated, labelled synthetic surface (§A7). **[PoC override — §0.0: this PoC has no client-actual concept. The generated weighted-average cost is the authoritative cost and margin shows on it; this bullet is production-only and never withholds PoC margin. What still holds: we never *relabel* generated cost as "client-actual" — we label it honestly as "weighted-average cost".]**
- **No fabricated or sample values.** We never reproduce the mock's numbers, hardcode a plausible figure, or coerce `null → 0`. A cell shows a real value from an accepted artifact, or an honest governed state.
- **No in-place edits of immutable outputs.** Margin ships as a fresh immutable bundle + independent verification + **successor activation** (§A6) — never by mutating an activated bundle, a materialized row, or an authority file.
- **No metric substitution / relabelling.** We do not point a cell at "a nearby metric" (`phase5 §1.10 #17`). Each unlocked element satisfies its *own* frozen definition (`P5-D17`); e.g. Lost Sales Exposure is enabled only as *projected demand-at-risk* with an amended label, not by aliasing another number.
- **No cosmetic hiding.** Removing "Not available" is never done by blanking the cell, `display:none`, or a title-only parity trick. It is removed by producing the exact governed value (UNLOCK/DERIVE/ENRICH) or by a contract-declared withheld presentation (§2.3).
- **No unverified shortcuts.** Every change carries its contract/schema/fingerprint/migration/verifier update and tests; the datagen and ML changes are frozen (Stage A) and dry-run-proven (the dry-run gate) before the real run.
- **No post-result distribution editing.** Action/status/risk diversity is produced from frozen source-native cohorts and normal model logic. No recommendation row is relabelled, sampled away, or reordered after inspecting the final values merely to make a screenshot attractive.

The `core.py:349-353` correction (§4) and the guardrail correction (§A4) are included precisely because they are *proper* fixes of real defects — not because the demo needs them cosmetically. Where a proper fix requires a decision or a feed we don't yet have (§7), we surface it as a decision rather than papering over it.

---

## 1 · Workstream A — Margin (governed) — ✅ COMPLETED

> ### A0 · PoC amendment — COMPLETED & VERIFIED on the PoC cost model (supersedes A2–A10 where they differ)
>
> **Status: COMPLETE.** Margin is live end-to-end on the generated weighted-average cost basis and verified — Go / Python / UI test suites green (including WAC minimum-margin-floor regression tests: recommendation withhold, and Margin Protection sub-floor refusal in Python and Go) and confirmed on the running API + UI. Per the PoC Data Principle (§0.0), the client-actual / synthetic-scenario framing in the subsections below is **superseded** for this PoC. The margin workstream is implemented as follows; the older text is retained only as the future production design:
>
> - **Cost basis:** the generated weighted-average cost IS the authoritative unit cost; there is no client-actual cost and none is required. (Supersedes A2's "one decision", A3's client-actual feed as a *precondition*, and A10's "before external cost arrives" framing — the A3 adapter remains valid only for a future real-data deployment.)
> - **Primary margin is live:** Margin Opportunity, Current/Expected Margin, Margin Impact, and the primary simulation Gross Margin all show real values from the weighted-average cost. (Supersedes the "keep primary margin governed-unavailable" stance in A2/A7 and the GOVERNED-KEEP margin row in §0.)
> - **Minimum-margin floor is enforced** on the weighted-average cost basis in recommendation candidate eligibility (`recommendation.py`) and in the Margin Protection simulation (Go + Python). (Implements A4 on the WAC basis instead of gating it on client-actual cost.)
> - **`price_margin` authority:** `priceMarginActive` derives from the accepted cost basis (`priceMargin.available`) in the read model; a production deployment would instead require an active `price_margin` selection. (Supersedes A6's client-actual-selection activation.)
> - **The isolated `synthetic_margin_scenario` has been REMOVED**, not preserved: with WAC authoritative, a separate "synthetic — not client actual" surface is redundant and contradictory, so it was deleted from the producers, `simulation.schema.json`, `price-simulation.parity.yaml`, the Zod schema, the bundle capability, and tests. (Reverses A2 Path 2, A7, A10 #7, and the `synthetic_margin_scenario` mentions in §0's GOVERNED-KEEP row and D1.)
>
> **One residual (non-blocking):** the currently-active bundle was materialized before `build.py` dropped the `syntheticMarginScenario` capability, so the summary API still lists that dormant flag until the next governed pricing rebuild. Nothing reads it, and it is absent from the UI and the simulation response.

### A1. Root-cause recap (confirmed end-to-end)
Margin is wired through every layer but is structurally `null`:
- `ml/.../pricing/build.py:176-183` routes the generated unit cost into `synthetic_cost_minor`, hardcodes `cost_provenance = "generated_source_native"` and `client_actual_cost_minor = None`.
- The margin gate `recommendation.py:311-323` computes margin only when `client_cost is not None and cost_provenance == "client_actual"` → always false → `margin_impact_minor = None`, `margin_reason_code = "COST_NOT_CLIENT_ACTUAL"`.
- API `pricing.go:456-457` hardcodes `currentMarginPct` / `expectedMarginPct` to `NULL::numeric`; `pricing.go:500` sums margin only `WHERE margin_impact_minor IS NOT NULL` → KPI null.
- UI `Pricing.tsx:1050-1051` (Current/Expected Margin), `1236` (Min Margin input), `1239` (Margin Protection option) are **hardcoded unavailable** and never read data.

### A2. The one decision that shapes this workstream
Per `P5-D6`/`P5-D24`, **generated cost may never authorize a real `price_margin` claim.** So there are two legitimate ways to make margin appear, and they are not mutually exclusive:

- **Path 1 — genuine client-actual cost feed (recommended primary).** Introduce a real cost tier that satisfies the gate legitimately: positive, same-currency as `current_price_minor`, provenance = `client_actual`, method verified against receipts, observation/effective time no later than the decision origin, `known_as_of` no later than the decision origin, and freshness within the frozen policy. This unlocks **primary** Margin Opportunity / Margin Impact / Current & Expected Margin, the min-margin guardrail, and Margin Protection — the full capability.
- **Path 2 — preserve the isolated `synthetic_margin_scenario` (demo supplement).** Keep primary margin governed-unavailable, but retain labelled synthetic margin at the Price Simulation location only (`P5-D6` §8.3.2), so the demo shows margin numbers *somewhere*, explicitly marked "Synthetic demo margin — not client actual."

**Binding is conditional — §7 D1:** Path 1 may become the real capability only when a genuinely external/client-owned feed and approval evidence are supplied. A generated PoC record cannot earn `client_actual` by acquiring a new field, profile name, source instance, or policy amendment; ownership is an external fact. Until that authority exists, Path 2 remains the only numeric margin surface and every primary margin location uses the governed business-reason chip. The implementation must support both branches without rebuilding UI code.

### A3. Client-actual cost feed (Path 1)
The raw tiers already exist in `contracts/retail_v2/schema.yaml`: `inventory_receipts` (`unit_cost`, `currency_code`, `receipt_date`, `known_as_of` + grade) and `inventory_cost` (`wac_cost`, `method`, `as_of_date`, `known_as_of`). Work:
1. **External/client feed contract:** define the source registration, client/retailer attestation, allowed-use purpose, currency, cost method, effective/known-as-of timestamps, raw identity, and revocation semantics. Datagen may emit a structurally equivalent **synthetic test fixture** to exercise parsers and negative gates, but it must remain `synthetic_test` and cannot activate `price_margin`.
2. **Datagen/ingestion parity:** update both Rust and Python generators so schemas and fixtures stay in sync, while production/demo generation continues to use Rust only. Carry ownership and temporal provenance without translating legacy `ERP_ACTUAL` into client ownership. Fix `core.py`'s selling-price-as-`reference_cost` defect separately and prove no pricing consumer mistakes product reference cost for the store cost ledger.
3. **Temporal cost lineage:** preserve the selected contributing receipt/cost record identity and its row-level `known_as_of`/`as_of_date`; the inventory manifest decision cutoff is an upper bound, not a substitute for the cost observation time. Resolve WAC/FIFO method truth before asserting a method.
4. **Cost-reason contract:** version `contracts/pricing/reason-codes.json` before implementation. The current cost family has only `COST_NOT_CLIENT_ACTUAL`, `FIFO_NOT_VERIFIED`, `COST_CURRENCY_MISMATCH`, and `COST_AFTER_DECISION_ORIGIN`; it cannot express missing, non-positive, stale, scope-mismatched, revoked-ownership or unsupported-method evidence required by §A9. Add distinct codes, precedence and golden vectors rather than collapsing every failure into `COST_NOT_CLIENT_ACTUAL`.
5. **ML build:** derive `client_actual_cost_minor` only after ownership, positive-value, currency, scope, method, decision-origin, freshness and revocation checks pass; otherwise retain `None` with exactly one precedence-selected primary reason plus the complete secondary reason set.

### A4. Min-margin guardrail fix (correctness — independent of display)
`minMarginPct: "12"` is threaded into the resolved rule but is not applied by candidate enumeration or recommendation selection. Resolve cost **before** scoring candidates. Always retain the current-price baseline for impact comparison even when its margin is below the floor; do not drop it from baseline scoring. When valid client cost exists, compute each proposed candidate's gross-margin percent using the same `(price − cost) / price × 100` unit as §A5, reject sub-floor proposed candidates with a dedicated reason, then rank the remaining candidates under the frozen objective/tie-break. If no proposed candidate satisfies the active hard floor, emit a reason-coded withheld assessment—not a false Hold. When client cost is absent, preserve the independently authorized revenue recommendation and set only margin-dependent fields/capabilities to null + reason; do **not** withhold the whole recommendation solely because margin is unavailable. This preserves the approved rule that revenue exists independently of margin.

### A5. Tier-2 — Current & Expected Margin % (touchpoints)
Fields exist as NULL placeholders end-to-end; wiring them (only under the client-actual gate):
- **ML:** compute `current_margin_pct = (current - cost)/current × 100` and `expected_margin_pct = (proposed - cost)/proposed × 100`, with the exact unit frozen in the artifact schema and API. Add both fields to normal and withheld row schemas; withheld rows remain null unless an individual cost/price fact is independently authorized.
- **Artifact contract:** add both columns to `contracts/pricing/artifacts.schema.json:23-27` and **recompute the `contractFingerprint` at `:6`** (verified at `bundle.py:204-208`).
- **Postgres:** new migration adding the two numeric columns to `price_recommendations` (`0028:100-148`); **bump both revision guards** — `postgres.py:35` and Go `pricing.go:21`.
- **Materializer + verifier:** extend the `_copy` tuples (`postgres.py:383-420`); extend `_validate_artifacts` + the null↔reason invariant (`bundle.py:705-721`).
- **API + export:** replace the `NULL::numeric` literals (`pricing.go:456-457`), add the columns to the **detail** query (`pricing.go:585-635`, currently omits them), and fix export (`pricing_export.go:225` emits `'',''`).
- **UI:** un-hardcode `Pricing.tsx:1050-1051` to read `row.currentMarginPct`/`row.expectedMarginPct` (mirror the `marginImpactMinor` cell at `:1053`) + the detail modal; Zod already declares them (`pricingApi.ts:54-55`).

### A6. `price_margin` as an activatable capability (not a display flag)
Today `priceMargin` is an advisory bundle capability while selection is limited to `price_revenue`. To activate margin: add a `price_margin` selection capability to the schemas and lifecycle, define its own verified evidence projection, and create candidate → approved → active records plus a successor activation set containing both compatible selections for the **same pricing bundle**. A policy amendment can define proof requirements; it cannot convert generated ownership into client ownership. Append-only triggers reject in-place edits.

This is not only an enum edit: `bundle.schema.json` currently fixes `prospectiveResultSelections.maxItems = 1` and its intent/evidence shape is price-revenue-specific. Version the schema to support the exact compatible selection set, capability-discriminated evidence requirements, unique capability/scope membership, and deterministic ordering/identity. Update builder, outside-set verifier, selection preparation, database transaction, activation-set verifier and serving startup agreement together. The sparse audience must not accidentally acquire a margin selection.

### A7. Isolated synthetic margin (Path 2 — demo)
Already isolated correctly: `simulation.py:102-116` tags `discriminator: synthetic_margin_scenario`, label "Synthetic demo margin — not client actual", `doesNotAffectRecommendation: true` (const-enforced by `simulation.schema.json:46-53`); UI panel `Pricing.tsx:1142-1150`. Preserve rather than broaden it unless the owner contract is separately amended. It must **not** touch primary Margin Opportunity/Impact, Current/Expected Margin, the min-margin guardrail, price selection/ranking, or any promotion claim; mixed client-actual/synthetic aggregates are forbidden.

### A8. UI margin cells + color (ties into Workstream C)
Un-hardcode the four margin blocks (`1050`, `1051`, `1236`, `1239`); render `Margin Impact` with `.up/.down` sentiment color (see §3). Current Margin, Expected Margin and the Margin Protection objective become numeric/enabled only on an active `price_margin` branch; otherwise they render the exact governed reason/disabled state—never bare `Not available` and never synthetic cost under a primary label.

Minimum Margin is different: `minMarginPct` is an accepted policy fact, not a computed margin result. Project the resolved market/currency rule through the simulation contract/API and display its governed value (currently 12% for the applicable rule) even when client cost is absent, accompanied by `Not evaluated — client cost required`. Never copy the original HTML's sample 22%. The active `price_margin` gate controls whether the floor can be evaluated and whether Margin Protection can run; it does not hide the configured policy.

### A9. Tests
Add cost-gate fixtures for valid client-actual, missing, late/future-known, stale by the frozen freshness rule, non-positive, cross-currency, scope mismatch, unverified/unsupported method, generated, and revoked ownership. Assert primary/secondary reason precedence, revenue independence, preservation of the current baseline, sub-floor proposed-candidate rejection only when margin is active, no-eligible-candidate withholding, percent units, aggregate denominators, policy-value display independent of evaluation, and that synthetic cost never leaks into primary outputs.

### A10. Start boundary — what may proceed before external cost arrives

Margin engineering can start after this plan/contract delta is approved. Work that does **not** require a real client feed includes:

1. versioning the cost-evidence/reason-code, artifact, selection, activation-set, OpenAPI and screen contracts;
2. correcting `products.reference_cost` semantics without treating that field as Pricing's store-cost authority;
3. retaining receipt/cost record identity, `known_as_of`, effective/as-of time, currency and verified method through Inventory artifacts into Pricing context;
4. implementing a fail-closed client-cost resolver and full synthetic test matrix while keeping generated production/demo rows non-client;
5. implementing the conditional min-margin candidate guard, Current/Expected Margin %, database/API/export plumbing, nullable UI rendering, policy-floor display and capability-aware reason chips;
6. generalizing bundle verification, selection lifecycles, activation-set validation, materialization and startup agreement for compatible `price_revenue` + optional `price_margin` selections; and
7. ~~preserving the isolated `synthetic_margin_scenario`~~ — **superseded (§A0): it was removed; regression tests now assert it is absent and that the weighted-average-cost minimum-margin floor is enforced.**

The following remain blocked until genuine external evidence and approval exist: classifying a row as `client_actual`; accepting a client-cost scope; activating `price_margin`; showing primary numeric Margin Opportunity/Impact/Current/Expected values; enabling Margin Protection; or allowing the margin floor to change a served recommendation. The current generated inventory cost remains synthetic, and the measured FIFO label over WAC-derived values must be corrected before any method claim can pass. Implementation must leave the existing `price_revenue` activation valid throughout this work.

> **[PoC override — §0.0]** The clause above is the **production** model and is superseded for this PoC. This PoC has no client and no external evidence, so the generated **weighted-average cost is the actual authoritative cost**: primary numeric Margin Opportunity/Impact/Current/Expected values **do** show, Margin Protection **is** enabled, and the minimum-margin floor **is** active — all on the weighted-average cost basis. Only re-apply the blocked list if/when this becomes a real-data deployment with a genuine external cost feed.

---

## 2 · Workstream B — Availability (remove bare "Not available")

### 2.0 Method
The trace supplied approximate source-occurrence counts (**~90 Pricing, ~41 Inventory, ~24 Forecast, ~13 App**), not 168 independently visible elements; shared helpers, repeated call sites, conditional branches and modal-only sites make those counts unsuitable as a completion ledger.

Do **not** create a parallel register. Version and extend the existing `contracts/screens/client-demo-surface-state-capture-manifest.schema.json` and its populated instance at `contracts/evidence/client-demo-surface-state-capture-manifest.json`. They already own the 20 `pageId` values, `page | tab | panel | modal | state | structural_absence` kinds, access modes, capture classes, trigger/test/capture identities, external-owner fields, desktop/mobile evidence and keyboard status. Their existing invariants remain authoritative: `external_owned → reachability_only` with owner identity, and `structural_only → not_applicable`.

The versioned manifest becomes the single machine-readable surface/state register. Extend its `kind: state` rows to carry a stable element/state ID, label, current source/reason, UNLOCK/DERIVE/ENRICH/GOVERNED-KEEP disposition, target producer/artifact/API field, allowed-null conditions, rich/sparse expectation, distribution and default-viewport expectation, filter reachability and test ID. Approval requires 100% reconciliation: no source occurrence, original-HTML possibility or contract row unclassified, and no classified row without a test. Do not replace or weaken existing capture/access-mode fields while adding distribution evidence.

The tables below are priority summaries, not a claim that the exact register has already been completed.

### 2.1 UNLOCK / DERIVE — distinguish wiring from new computation
An UNLOCK site already has the exact accepted value. A DERIVE site has inputs but still needs a frozen formula, producer, artifact field, verifier, and API projection. It is unsafe to call both “wire it.”

| Screen / site | Field | Class | Required proof |
|---|---|---|---|
| Forecast Demand-at-Risk / Stock-out Risk | exact existing accepted fields | **UNLOCK** | API/matrix/UI reconciliation against the same active version |
| Inventory Lost Sales Exposure | projected demand-at-risk under an amended label | **UNLOCK only if the existing field exactly matches the amended definition; otherwise DERIVE** | grain, horizon, currency, denominator and coverage equality |
| Inventory Waste Reduction | current/prior comparison | **DERIVE** | frozen windows, formula, exact-zero behavior and new verified projection |
| Data Management Valid/Duplicates/Missing | validation measures | **DERIVE unless retained validation artifacts already carry all three** | source-row denominators, duplicate key, missing-field scope and last-run identity |
| Data Management Last Refresh | source-specific freshness | **DERIVE** | source observation/extract boundary, not publication time |
| Pricing Decision Quality | assessed confidence ratio | **DERIVE** | filtered assessed denominator including withheld rows; 0/0 behavior |
| Pricing Business Value by Driver | non-overlapping attribution | **DERIVE** | exclusive attribution or reconciled allocation; no double count; margin driver conditional on client cost |
| Pricing portfolio elasticity/scenarios | portfolio projections | **DERIVE** | aggregation semantics, horizon and uncertainty—not a direct reuse of row beta |
| Forecast Data-freshness compliance | source-specific compliance | **DERIVE** | required-source set, per-source SLA, denominator and timestamp lineage |

### 2.2 ENRICH — populate via the response-rich demo profile (`P5-D15`)
Root-cause **(b) data-absent / (d) conditional-null** — the field is empty only because the demo dataset is thin. `P5-D15` requires a frozen deterministic demo-coverage contract in `P5-1P` that *creates* the applicable states (and the naturally-sparse cohorts) legitimately. Targets:
- Pricing SKU table: Competitor price (`1047`), Stock Cover (`1048`), Forecast Demand (`1049`) — generate fresh admissible competitor bounds, inventory cover, and forecast cohorts. **Competitor price is not merely thin — it is scope-pinned**: fix the `first_store` geo-scope in datagen (§4, `signals.rs:288-289`) so eligible bounds exist market-wide, not only in `mumbai-dist`. Every row on the default 20-row recommendation page must carry a current, currency-compatible competitor price and approved display name; the page must contain above/equal/below price positions. An intentionally excluded comparison renders `Excluded`/`Not included by selection`, never `Not available`.
- Competitor Monitor: price-gap, match confidence, Match Quality Summary (`1426-1435`).
- Inventory conditional-null cells (ageing/receipt-date `823`, real-field KPIs) — generate receipt dates and the trailing windows so cells populate.
- Coverage is *never* satisfied by hidden toggles or by corrupting the accepted audience (`P5-D15`); it is a data-generation task in datagen/ingestion (§4).

### 2.2.1 Deterministic visible-state distribution contract

Draft the outer acceptance requirements before calibration and freeze them before authoritative generation in the extended capture manifest's `kind: state` rows—there is no second distribution-contract format. Calibration may tune causal cohorts to the declared target but may not widen a failing outer gate after seeing results. Each row declares: screen/element, source field, allowed vocabulary, required active-rich states, minimum count and share, maximum dominant-state share where appropriate, default-sort viewport requirement, filter reachability, sparse/withheld companion, producer, verifier and failure behavior. Requirements are evaluated **after ingestion and after every model/artifact build**, not only against source configuration.

For the normal client-demo activation:

- Price Recommendations deliberately models a **mostly well-priced catalog with bounded, profitable pockets of opportunity**. Hold-majority is a transparent PoC scenario choice, not a claim about a retailer's future production distribution. Freeze exact ranges before generation; the starting contract is **80–120 recommendations in total, 3–4 Increase, 3–4 Reduce, and every remaining recommendation Hold**. Thus only 6–8 actions exist and at least 90% of the full recommendation population remains Hold. The manifest—not this prose—owns the final frozen thresholds.
- The client-facing grid uses **exactly 20 rows per page**. The UI requests `limit=20`, the API reconciles `limit/offset/total`, and pagination/filtering never mounts 200 recommendation rows at once. Under the existing priority-first business sort, the first page must contain **12–14 Hold, 3–4 Increase and 3–4 Reduce, totalling exactly 20**. This works without artificial row ordering because the entire actionable population is capped at 6–8. Do not relabel Hold priority, add a screenshot-only tie-break, sample away rows, or reorder an inspected result.
- Every accepted Increase/Reduce recommendation in the active-rich PoC must have **strictly positive expected incremental gross margin and non-negative expected incremental revenue** on the authoritative weighted-average cost basis. Hold rows preserve price and have zero opportunity. Consequently `marginOpportunityMinor > 0` and `revenueOpportunityMinor > 0` at the default scope, with at least one positive contributor from both Increase and Reduce cohorts. A revenue-improving but margin-dilutive candidate is refused/withheld by a frozen `MARGIN_DILUTION` profit guardrail; it is never counted as a positive opportunity or silently turned into an action.
- The 80–120 total, 6–8 combined actionable, exact 20-row page and positive-profit constraints are load-bearing together. Changing total cardinality, page size, priority mapping, default sort, opportunity denominator or profit guardrail requires a pre-run manifest and screen-contract amendment—not a UI-only change after generation.
- Each category, store and channel shown in the demo must have at least two applicable action states; no single category/store/channel may accidentally become “all Reduce.”
- High/Medium/Low priority, High/Medium/Low risk, High/Medium/Low Forecast Demand, competitor included/excluded, and recommendation/withheld must all be visibly reachable. Priority and risk must remain semantically computed; coverage is achieved by upstream cohorts, never relabelling.
- Competitor Monitor must visibly cover Matched/Needs Review/Rejected/No Match; Fresh/Near threshold/Stale; In Stock/Low Stock/Out of Stock/Unknown; Above/Below/Equal/Incomparable; and response Hold/Increase context/Decrease context/Validate/Excluded.
- Forecast must visibly cover health/risk tiers, positive/negative/zero bias, high/medium/low demand, interval available/withheld, exact-zero and filtered-empty states, while never calling a non-PIT field PIT.
- Every Inventory page must declare its own status/risk/age/priority/source/workflow vocabulary and minimum state counts. At minimum the cross-page contract covers Healthy/At Risk/Understock/Overstock/Out of Stock, low/medium/high/urgent priority, age bands, transfer/order lifecycle states, supplier risk, exception reasons, exact zero, and filtered empty.
- Promotion's amended branch must cover lifecycle, mechanic, scope, conflict, inventory-readiness and accepted/rejected/insufficient model outcomes allowed by the governing plan; privacy-restricted states stay chips.

The verifier fails the rich bundle if a required state is absent, if a dominant-state ceiling is exceeded, if the default viewport lacks its required mix, or if API filters/counts do not reconcile. These are pre-result success criteria: failing them requires fixing the generator/model and creating a new immutable run, never editing artifacts or database rows.

### 2.2.2 Complete possibility inventory — no example-only acceptance

The extended capture manifest is the sole machine-readable source of truth for this inventory. The prose lists in §2.2.2 and §2.5 are review summaries and minimum-authority cross-checks only; implementations and tests consume the manifest, and any inconsistency blocks approval rather than being resolved by choosing one prose list.

The exact state register is built from the **union**, not the intersection, of:

1. every option/label/status/badge/table branch in the original HTML;
2. every checked-in screen-contract row and modal disposition;
3. every enum, reason code, availability/null branch and capability state in schemas and APIs;
4. every implemented React conditional, filter option and disabled-control state;
5. every generated/canonical/model field vocabulary.

For each member, the register records one of: `active_rich_visible`, `active_rich_naturally_sparse`, `non_active_sparse_harness`, `isolated_operational_adapter`, `structural_option_only`, or `governed_not_applicable`. `Structural_option_only` is valid for non-mutating form vocabularies whose values can be inspected but not executed. `Governed_not_applicable` requires a named decision/contract and visible reason; it is not a way to omit difficult states.

At minimum the register imports and specializes every state family already required by Phase 5 §9.1–§9.7:

- cross-market/currency/store/channel scope and reporting-currency dispositions;
- price actions, confidence, priority, risk, guardrails, competitor inclusion, margin branch, selection/export/detail and sparse assessments;
- simulation assumptions, validity/refusal cases, objectives, risk and competitor execution truth;
- competitor match/confidence/availability/freshness/price position/response/source/selection/detail/rules;
- promotion decision/package/model/scope/lifecycle/mechanic/status/calendar/readiness/privacy/conflict and simulation states;
- Data Management health/freshness/validation/source states;
- Forecast grain, health, bias, interval, demand/risk, exact-zero, version comparison, selection and empty states;
- all 14 Inventory page families listed in Phase 5 §9.6, including health, ageing, transfers, valuation method, expiry, replenishment, order, supplier, safety-stock, allocation, exception and stock-health states;
- loading, exact zero, normal value, filtered empty, naturally insufficient, partial panel, 409 stale and 503 unavailable states.

No page passes because one representative shared component was tested. Every page and every owned modal has its own state/register coverage row, DOM assertion, data-lineage assertion and desktop/mobile capture. Filters must reveal every data state without code/database edits; all controls and option vocabularies must be inspectable in their approved enabled/disabled state.

### 2.2.3 Display-label integrity — names are data, not UI guesses

Every governed dimension projected to a visible screen carries both stable identity and display label through source → canonical → artifact → serving table → API. Store, warehouse, category, department, channel, supplier, product and other business dimensions render their approved name/label; an internal ID may appear only where the reference explicitly presents a business identifier (for example SKU) or as secondary detail approved by the matrix. Missing labels enter the data-quality exception/reason path—they do not fall back to printing the raw ID. API and DOM tests assert the exact ID→label join for every filter, grouped row, table cell, detail modal, export and selected-item summary, including duplicate names and unknown/deleted dimensions.

### 2.2.4 Distribution validation layers

Each run emits one reconciliation report with counts and fingerprints at these boundaries:

`Rust source → raw files → staging → canonical publication → Forecast artifacts → Inventory artifacts → Pricing/Promotion artifacts → PostgreSQL serving → API responses → visible default/filter states`.

For each state family the report shows configured cohort count, observed count at every applicable boundary, dropped/merged count with reason, final API count and visible UI count. Grain-changing stages declare their expected reconciliation formula. Any silent loss, accidental many-to-one collapse, raw technical ID in a name field, unexpected null, all-one-value distribution, or default-page omission blocks activation.

### 2.3 GOVERNED-KEEP — cannot show a fabricated number
No accepted evidence exists on the active branch, so these sites must not print a number. Conditional workstreams may make them live only after their stated evidence and approval gates pass; otherwise they keep a capability-specific reason chip or an expressly authorized labelled-synthetic presentation.

| Site(s) | Why governed | Path to a real value (if you want one) |
|---|---|---|
| **Entire Promotion Planner** → **CONDITIONAL LIVE (D2)** | current contract is `governed_negative_branch` with `NO_ORIGIN_VISIBLE_PROMOTION_PLAN` / Decision #53 | Only after formal P5-D23 amendment approval, source-native lifecycle/mechanic fields, origin-safe plans/history, and P5-D20/P5-D22 gates. `positive_descriptive_only` does not authorize numeric KPI/chart/table values. PII/cannibalisation/bundle sub-elements stay `privacy_restricted` chips |
| **Forecast Business Impact** (`1359-1369` ×5) | No accepted counterfactual; Phase-4 replay did not pass | Requires accepted replay; §1.10 #5 — "must not invent one" |
| **Replay-dependent benefits** — Inventory `847/850/853/968/1047/1122/1129` (Revenue Protected, Working Capital, Service Level, Fill Rate, Fulfillment Rate) | `REPLAY_UNAVAILABLE` | Requires accepted replay (§1.10 #19) |
| **Planner-workflow** — Forecast `1806/1022-1025/1351/1356/400/1413/1515`; Pricing `980/1007/1056/1057/955/988`; Inventory owner/approval | Phase-6 workflow not in scope | Phase 6; relabel with the business prerequisite, not a phase tag (§1.10 #8) |
| **Primary margin** → **LIVE (PoC — §A0)** | — | RESOLVED: the generated weighted-average cost is the authoritative cost, so primary margin is served on every surface and the minimum-margin floor is enforced on it. Client-actual evidence plus an active `price_margin` selection are production-only and do not gate this PoC; the synthetic-margin scenario was removed. |
| **NRV / Provisions** → **CONDITIONAL LIVE (D4)** | `NRV_UNAVAILABLE` / `PROVISION_PENDING_MARKDOWN_POLICY` (P4-D10) | Accepted recovery-price evidence and separately approved NRV/provision definitions are required; markdown depth + acquisition cost alone is not NRV and cannot produce an accounting provision |
| **Competitor engagement bounds** — MatchReview `1354/1340`, alert rules `1430` | Match evaluation gated (P5-D8: disjoint truth set, precision/recall) | Requires the P5-1P matching-evaluation protocol |
| **Forecast KPI deltas** — `1779` etc. | No 2nd comparable accepted version (contract Q5) | Requires a second retained forecast version |
| Nav routes (App `42-145`), identity (`355-360`), notifications (`565`) | Owning phase hasn't implemented the route | `P5-0P` dispositions each: native-disabled with accessible business reason (§1.9) |

**Restyle spec for this bucket:** replace a bare literal `Not available` / unexplained em dash with a compact chip carrying (a) a short business reason, (b) a neutral/`b-gray` or `b-amber` badge, and (c) the exact state vocabulary owned by that capability. Do not apply Pricing's `assessed / withheld / manual-review` vocabulary to unrelated workflow, privacy, replay, identity, or source-connection states. Preserve the full reason and reason code accessibly. Global error messages such as “Live data is unavailable” remain valid operational copy and are tested separately; they are not disguised as normal data.

Formatters must format valid values only; they may not choose a generic availability fallback. Replace global literal fallbacks such as `const unavailable = "Not available"`, `value ?? unavailable`, and `String(value ?? unavailable)` with a shared typed value/reason renderer whose caller supplies the capability-owned reason. The same component enforces accessible reason text, badge semantics and zero-versus-missing distinction. A missing display label is handled by §2.2.3, not by rendering its ID.

### 2.4 Per-screen notes
- **App/shell + Data Management:** mostly UNLOCK (validation detail, real freshness) + `P5-0P` nav dispositions. KPI tiles already non-null in schema.
- **Demand Forecast:** UNLOCK Demand-at-Risk/Stock-out (§1.10 #4); GOVERNED-KEEP Business Impact, planner-workflow, deltas, promotion-exception row (#53). Compare-Versions must load retained versions or show governed state (§1.10 #7).
- **Inventory (14 pages):** centralize presentation in `SCREENS` + availability reason registry, but keep each metric's producer and definition independent. DERIVE Waste and any missing comparison; ENRICH ageing/receipt cohorts; NRV/provisions are conditional on D4 evidence; GOVERNED-KEEP replay + exception-owner. Safety Stock becomes policy-segment rows only after its API projection is frozen.
- **Pricing (4 pages):** Workstream A **COMPLETED** — primary margin is live on the weighted-average cost basis (§A0); DERIVE decision-quality/driver/portfolio projections; ENRICH competitor/stock/forecast; Promotion Planner is conditional on D2's formal amended branch; GOVERNED-KEEP approval workflow and privacy-restricted sub-elements.

### 2.5 Minimum destination-by-destination demo ledger

The extended capture manifest expands these rows to individual elements. This table does not define a second ledger; it is a human-readable reconciliation view of minimums from the parent plan and must be generated/checked against the manifest so the two cannot drift:

| Destination | Required normal-demo possibilities |
|---|---|
| Data Management | Healthy, delayed/needs-attention, stale, missing source, validation success/failure, duplicates/missing fields, source-specific freshness, latest retained validation detail, filtered/empty and disabled no-write actions |
| Demand Forecast | Exact zero and non-zero demand/risk, positive/negative/zero bias, high/medium/low demand, interval available/withheld, selected/unselected/export, filtered empty, compatible/incompatible version comparison, and owned-dialog states; external-owned Scenario surfaces remain reachability-only |
| Inventory Overview | Healthy, understock/low, urgent, ageing and exact-zero cohorts; complete health/position/risk/location cards with an independent populated card when another card is empty |
| Store Inventory | In stock, low stock, out of stock, exact zero, projected demand-at-risk assessed/withheld, transfer opportunity, multiple store names, and filtered empty |
| Warehouse Inventory | Healthy/low/out-of-stock locations, DC/store-node distinction, blocked stock, delayed receipt, transfer/replenishment context, missing prerequisite and filtered empty |
| Inventory Ageing | Fresh and every approved age band, ageing/markdown/transfer candidates, exact-zero exposure, missing receipt evidence and filtered empty |
| Stock Transfers | Recommended, in-transit, completed and no-transfer states; source-backed priority, missing workflow acceptance and safe detail/export |
| Inventory Valuation | Computed WAC, genuine FIFO or explicit FIFO-withheld, gross/NRV/provision/variance conditional branches, exact zero and every measured reason-coded unavailable cohort |
| Expiry & Waste | No-expiry zero, approaching expiry, expired/waste risk, recovery/markdown conditional branches and filtered empty |
| Replenishment Planner | Recommended, urgent, normal/Hold, insufficient-input, exact-zero and filtered-empty rows; zero/one/many/select-all-visible selection and no enabled mutation |
| Suggested Orders | Suggested and withheld/insufficient rows, missing supplier/policy, exact-zero quantity, filtered empty, read-only detail/export and disabled create/submit |
| Supplier Planning | Normal, delayed, stale and missing supplier/lead-time evidence, supplier-risk tiers, exact zero/empty and unavailable workflow commitments |
| Safety Stock | Multiple policy segments, service/risk tiers, SKU counts, exact zero, missing driver and conditional promotion driver |
| Allocation & Fulfillment | Allocated, short and withheld states, source/target/channel applicability, exact zero and filtered empty |
| Replenishment Exceptions | Every frozen severity and reason, no-exception exact zero, missing prerequisite, filtered empty and workflow owner/resolution conditionality |
| Stock Health | Healthy, at-risk, critical/stockout, excess/ageing, exact-zero, filtered-empty and mixed partial-metric states |
| Price Recommendations | Hold-majority plus material Increase/Reduce minorities; recommendation/withheld, priority/risk/confidence bands, competitor included/excluded, stock/forecast bands, category/store/channel diversity, exact zero, detail/export/selection and mixed default viewport |
| Price Simulation | Every governed product/price/period/assumption/objective/competitor option, valid/invalid/refused simulation, Expected/Best/Worst results, exact zero, primary Gross Margin on the weighted-average cost basis, and a sub-floor Margin Protection refusal (§A0 — the synthetic-margin panel was removed) |
| Competitor Monitor | Matched/Needs Review/Rejected/No Match; confidence bands; fresh/near-threshold/stale; availability states; above/below/equal/incomparable price position; response and exclusion states; detail/rule/modal paths |
| Promotion Planner | Negative, descriptive-only and numeric branches as authorized; lifecycle/mechanic/scope/conflict/readiness/model outcomes, calendar/list possibilities, privacy-restricted controls and every owned modal state |

Each row is validated under every applicable market/currency/store/channel selection. A page is not complete when its KPI cards are populated but its table, alternate tab, modal, filter result, empty state or export still lacks its contracted possibilities.

---

## 3 · Workstream C — Color & format parity (fully sanctioned — no governance tension)

The `:root` palette is already identical (`styles.css:2-13` == HTML `:10-12`). The gaps are in the **semantic layer**. Three systemic defects cause most of them.

### 3.1 Systemic fixes
1. **Add the missing delta classes.** `.up/.down/.warn` **do not exist** in `styles.css` (grep count 0); the original defines `.up{color:var(--green)}.down{color:var(--red)}.warn{color:var(--amber)}`. Every `className="delta up/down"` and `td.up/down` in the impl currently renders as **plain text**. Add these three rules — this single fix restores most delta coloring app-wide.
2. **Unify the badge helper.** Three inconsistent implementations exist and disagree: `Forecast.tsx:200-210` (3 colors, no blue), `Inventory.tsx:409-418` (regex, 5 colors), `Pricing.tsx:130-146` (4 colors). Replace all three with **one shared, per-context mapping** (the original chooses color per cell, not by string). Fix the specific mismatches:
   - **Pricing Priority "High" → b-red** (currently **b-green** at `Pricing.tsx:130-136` — the marquee bug; High priority shows green).
   - Pricing Action "Decrease" → b-amber (currently b-red).
   - Inventory: Mixed→amber (curr blue), Expiry Risk→red (curr amber), Understock→red (curr amber), Approved→green (curr blue), Review→amber (curr blue).
   - Forecast: Health "Action"→red (curr amber); workbench Low→blue (curr amber), Adjusted→blue (curr amber), Accepted→green (curr amber).
3. **Add chart/waterfall/ring classes.** `.bar/.bar.green/.bar.amber`, `.wf/.wf.green/.wf.red/.wf.amber`, `.score-ring` are all absent. Restores the Pricing Opportunity Waterfall (currently a plain list), the Decision-Quality ring (currently "—"), and the forecast deviation bar. (The inventory health **donut** already matches — `DONUT_COLOURS` == original. ✓)
4. **Align badge shades** to the original where they drift: `.b-red` (impl `#a82535/#ffe1e5` vs `#b83c49/#ffe4e7`), `.b-blue`, `.b-gray`.
5. **Restore KPI delta spans** dropped in `PricingKpi` (`Pricing.tsx:183-200`), `Inventory` KPI (hardcodes `delta up` at `1320/1328` regardless of sign), and Data-Management `Kpi` (`App.tsx:714-728`).

### 3.2 The critical coloring rule (must be encoded explicitly)
**Color = business sentiment, not arithmetic sign.** The original deliberately colors a *falling* Stock-out Loss green (good) and a *positive* below-plan regional growth red (bad); competitor price-gap inverts (cheaper-than-competitor = green). This cannot be derived from the number's sign or the label string — it must be per-cell/per-metric logic in the shared helper (a sentiment direction per field).

### 3.3 Format fixes
- **"pts" vs "%":** the original distinguishes percentage-*points* deltas ("↑ 9.5 pts") from percentages; the impl drops "pts" (`toFixed(1)+"%"` everywhere). Restore the "pts" vocabulary on point-change deltas (aligns with `P5` FVA rules: relative % vs pts).
- **Signed `+`:** many impl call sites omit `signed`, so positive deltas lose their `+`.
- **Minus glyph:** impl uses U+2212 `−` (`currencyFormat.ts:18,48`); confirm the parity matrix accepts it (cosmetic).
- **Dates:** original uses terse "18 Jul"; impl adds the year / uses `en-US medium`. Align to the reference format.
- **Currency Cr/Lakh:** already correct (`currencyFormat.ts:11-63`). ✓

### 3.4 Per-screen color gaps (summary — full table in the traces)
- **Dashboard/Executive Overview:** *not implemented* (nav hard-disabled, `App.tsx:41-44`; absent from `PageId`). Its color semantics (KPI deltas, heatmap up/down cells, health badges) have no counterpart. **Per §7 D3 it stays governed native-disabled (out of scope this phase)** — so its color parity is explicitly deferred; the systemic primitives (§3.1) are still authored so it needs no rework when its owning phase builds it.
- **Forecast:** delta classes missing; Exceptions render plain counts (no badges); Health "Action" mis-colored; workbench Status/Priority mis-colored.
- **Inventory:** KPI deltas hardcoded/plain; `badgeClass` regex mismatches (above); donut ✓.
- **Pricing:** all 5 KPI deltas dropped; Priority "High" green-not-red; waterfall & ring uncolored; competitor price-gap direction uncolored; Status badges dropped.

---

## 4 · Data-profile enrichment (datagen / ingestion / ML)

Supports Workstream B **ENRICH** and margin **Path 1**. Governed by `P5-D15` (frozen demo-coverage contract in `P5-1P` *before* generation):
- Generate fresh admissible **competitor observations/matches** (for Pricing competitor cells + Competitor Monitor), respecting `P5-D8` evidence classes (`synthetic`, never "live client").
  - **Confirmed root cause of the 11-of-866 competitor gap (2026-08-13):** `datagen_rust/src/projection/signals.rs:288-289` emits every competitor price observation with `targetType="store", targetId=first_store.store_id` — the market's *first* store (`mumbai-dist`) — so ingestion (`transforms/core.py:842-848`, `store→location`) scopes all competitor evidence to one district. The bound join (`recommendation.py:107-114`) admits a competitor only when `geo_scope_type="market"` **or** a `location` whose `geo_scope_id == row.store_id`; with all 93 eligible ("Matched", conf ≥ 0.90) bounds pinned to `mumbai-dist`, only ~11 of 866 recommendation rows across ~13 districts can bind one. This is a datagen coverage defect, not the governance gate (which correctly admits only review-cleared bounds). Competitor Monitor is unaffected because it lists all observations regardless of scope — hence the grid-vs-Monitor discrepancy the user reported.
  - **Fix:** emit competitor evidence at **market scope** (`targetType="market", targetId=market_id`) so the join applies it to every store in the market, or emit per-district observations for every store rather than only `first_store`. Mirror the change in the Python datagen with parity tests (Rust-authority bullet below). Decision on market-wide vs per-district scope is deferred to this task.
- Generate **inventory cover + receipt dates + trailing windows** so ageing, days-of-supply, waste, and stock-cover cells populate.
- Generate the frozen **state distributions**, not merely non-null fields: price-response regimes that naturally yield the approved Hold-majority/Increase/Reduce mix; category/store/channel diversity; inventory health/age/risk/lifecycle cohorts; forecast bands and exact-zero cohorts; competitor match/freshness/availability/price-position cohorts; promotion states on the formally amended branch.
- For pricing action diversity, vary genuine demand elasticity, observed support, current position inside that support, forecast demand, inventory state, competitor bounds and protection evidence. Do not insert an action target into ML or alter a recommendation after scoring. The source/config manifest records the causal cohort, while the outside verifier checks the resulting action distribution.
- (Path 1) Ingest a genuine external/client-authorized cost tier when supplied. Datagen emits only `synthetic_test` structural fixtures and can prove rejection; it cannot originate client ownership.
- Fix `ingestion/.../transforms/core.py:349-353` (price-as-`reference_cost` semantic defect) as a correctness cleanup.
- Rust is the execution authority for the real run; Python receives matching schema/fixture/code changes and parity tests so the two implementations cannot drift.
- After raw generation, assert the same contract at raw, staging, canonical, forecast, inventory, pricing artifact, PostgreSQL, API and default-viewport layers. A source state that disappears during ingestion is a failure, not a satisfied generator target.
- Treat recoverable record defects as data-quality outcomes, not run-wide crashes: quarantine the row in the existing exception/rejection channel with source identity, reason code, stage and retry disposition, then continue other independent rows. Freeze per-source/per-stage rejection ceilings before the run and reconcile `input = accepted + quarantined/rejected`; no required demo cohort may be lost entirely to quarantine. Schema/contract mismatch, broken authority or fingerprint, scope/version inconsistency, reconciliation loss, a breached rejection ceiling, or failure of a required demo cohort remains a hard scope/run failure. Never swallow an exception or convert a defective numeric value to zero.
- The active-rich profile includes mostly complete rows plus small, naturally sparse reason-coded cohorts. Do **not** create a second full sparse source run or retain another large sparse output tree. Exercise non-active sparse behavior with compact deterministic fixtures/retained evidence and isolated adapters; do not load thousands of withheld rows into the normal default page merely to prove sparse behavior.

---

## 5 · Contracts, schema, migrations, tests

- **Amend the four existing Pricing contracts:** `price-recommendations.parity.yaml`, `price-simulation.parity.yaml`, `competitor-monitor.parity.yaml`, and `promotion-planner.parity.yaml` already exist. Version and amend them; do not create a duplicate “new Pricing parity contract.” Remove the user-visible words `Preview Only` where already directed, but preserve internal access modes such as `preview_only_no_write` wherever they still truthfully govern behavior; presentation copy and machine control vocabulary are separate concerns. Record the exact live/conditional/governed dispositions.
- **Extend the existing capture manifest:** version `contracts/screens/client-demo-surface-state-capture-manifest.schema.json` and migrate the existing `contracts/evidence/client-demo-surface-state-capture-manifest.json` instance rather than adding a parallel register. Add the §2.2 state/distribution/default-viewport fields to `kind: state` rows and preserve its existing 20-page, access-mode, ownership, capture-class, desktop/mobile and keyboard invariants. The manifest maps screen-specific modes such as `preview_only_no_write` to its governed `preview_only` capture access mode without erasing the more specific owning-contract value.
- **Freeze expectations separately from later evidence:** the same manifest format carries pre-run expectations and post-run capture evidence, so bind an `expectationFingerprint` over an allowlisted canonical projection: original-HTML identity, viewports, surface identity/routing/access/ownership/test fields, and all state/distribution expectations. Exclude desktop/mobile capture status/path/hash, keyboard result, review result and notes. Retain the current v1 manifest bytes as predecessor evidence. Before authoritative generation, append an immutable pending-evidence v2 revision with this fingerprint; after execution, append an immutable captured successor revision with the identical recomputed expectation fingerprint. The stable current-manifest location may be an atomic pointer/copy but is not the retention authority; the exact append-only revision path and identity are frozen with the v2 schema. This satisfies the parent plan's retention rule, avoids a parallel register, and avoids the impossible requirement to hash post-run evidence into pre-run source bytes.
- **Artifact/schema:** `artifacts.schema.json` (+ fingerprint), `bundle.schema.json` capability enum, `result-selection*.schema.json` capability const (for `price_margin`).
- **Migrations:** margin-pct columns + dual revision-guard bump (`postgres.py:35`, `pricing.go:21`).
- **OpenAPI:** `contracts/api/openapi.yaml` has no pricing margin fields — add them to the pricing response schema (currently `additionalProperties: true` lets them pass untyped).
- **Screen matrices / `P5-0P`:** every parity change (color, unlocked element, restyled withheld state, disabled-route disposition) becomes a **versioned matrix amendment + regression evidence** — `phase5 §1.9`: "Phase 5 is not permission for an unreviewed visual redesign."
- **Tests:** margin gates (§A9); generator parity; raw→canonical state conservation; action/status/risk distribution and dominant-state ceilings; default-page mix; per-filter counts; badge/sentiment/format mapping; per-page live-state coverage; and 409/503 operational states. Tests assert meaningful visible values do not contain raw IDs, bare missing tokens, `NaN`, `null`, `undefined`, or unexplained em dashes.

---

## 6 · Phasing — feature-wise before the run, page-wise after, converging on **one authoritative run**

Two goals to reconcile: (a) units should be **feature- or page-shaped** so each is easy to target and validate in isolation; (b) the expensive datagen→ML pipeline should have **one authoritative source run**. These pull opposite ways — vertical feature slices normally each want their own run. The resolution is a **fan-in / fan-out around a single run boundary**:

- **Stage A (feature-wise, before the run):** each feature implements its producers, then the representative calibration loop proves and freezes the emit/distribution expectations. Data needs fan in to one source profile; downstream capabilities retain separate builds.
- **Run boundary:** ONE authoritative Rust datagen run followed by one dependency-ordered Forecast → Inventory → Pricing/Promotion orchestration with separate verification/activation authorities.
- **Stage B (page-wise, after the run):** each page consumes its applicable successor authorities and is wired + validated independently.

This is possible because source publications and downstream artifacts are immutable/content-addressed and activations are append-only. A field/state discovered missing after activation forces a successor artifact and possibly a new source run, so Stage A calibrates before freezing the complete extended capture manifest and the dry run proves every boundary first.

```
 Stage A · FEATURE-WISE               RUN BOUNDARY                     Stage B · PAGE-WISE
 A1 Margin producers ─────────┐    ┌─ ONE Rust source run ──────┐     ┌─ B1 Shell + Data Management
 A2 Enrichment/distribution ──┤ fan│ ingest/select/pin          │ fan │  B2 Demand Forecast
 A3 Derived projections ──────┤───▶│ Forecast → Inventory →    │─out▶│  B3 Inventory (14 pages)
 A4 Color/format primitives ──┤    │ Pricing/Promotion builds, │     │  B4 Pricing (4 pages)
 A5 Contracts/governance ─────┘    └─ verify/activate each ─────┘     └─ B5 Operational states
```

### Stage A — feature units (targetable, independently buildable, **no authoritative runs**)

| Unit | Scope | Run input it contributes | Validate by (pre-run) |
|---|---|---|---|
| **A1 · Margin** | external client-cost adapter/contract + synthetic rejection fixture; temporal lineage; ML margin calc, min-margin guardrail, Tier-2 %, optional `price_margin` capability/evidence | external feed only if supplied; otherwise no primary-margin activation | §A9 full gate matrix; revenue-independence and sub-floor tests; client-ownership approval record |
| **A2 · Demo enrichment & distribution** | rich + naturally sparse competitor/inventory/forecast/pricing/promotion cohorts; Rust/Python parity; `core.py` correctness fix; representative-scale calibration loop | Rust datagen profile cohorts | calibration seeds pass the safety band; raw→API conservation; per-state minimums; dominant-state ceilings; default-viewport mix; filter reconciliation |
| **A3 · Derived projections** | Pricing driver-attribution, portfolio elasticity/scenarios and decision quality; Forecast freshness; Data Management validation; Inventory current/prior comparisons | capability-owned artifact columns | formula/denominator golden vectors, exact-zero/null rules, non-overlap and API reconciliation |
| **A4 · Color/format primitives** | shared CSS `.up/.down/.warn`, `.bar/.wf/.score-ring`; **one** unified badge helper + sentiment map; restored KPI delta spans; format fixes (§3) | *none* (pure UI) | snapshot + unit tests immediately; validated per-page inside Stage B |
| **A5 · Schema/contract/governance** | artifact/distribution schemas (+fingerprints), optional margin capability, migration/OpenAPI fields, amendments to the four existing Pricing contracts, and only formally approved P5-D23/P5-D24/NRV bindings | *none* (enables the run) | schema validation, decision/approval evidence and **dry-run gate** below |
| **A6 · Promotion (aggregate)** | origin-safe aggregate promotion plans/history + `P5-D20` uplift estimator + `P5-D22` acceptance; ML promotion capability derivation; PII/cannibalisation/bundle kept `privacy_restricted` | datagen promotion cohorts **+** ML promotion outputs | estimator golden vectors; applicability AND/OR + equal-precedence conflict vectors; privacy-boundary test (restricted stays restricted) |
| **A7 · Inventory NRV/provisions** | recovery-price/disposal-cost evidence + accounting/obsolescence policy + eligible temporal acquisition cost, each with a frozen definition; external pricing-margin cost ownership is neither necessary nor sufficient by itself | Inventory valuation projections | per-definition golden vectors; accounting approval; no-nearby-metric alias |

A1–A3, A6, A7 fan into the orchestration; A4–A5 need no data run. Freeze the **emit manifest and extended capture-manifest expectation projection**—every column, capability, cohort, state, allowed null, expected count/share, default-viewport rule and evidence branch—as Stage A's exit gate.

### Representative-scale calibration loop — before the freeze

The Hold/Increase/Reduce mix is an emergent model result. A tiny contract fixture cannot establish that the full profile will land inside its distribution gates, while forcing labels or tuning after the authoritative result is forbidden. Make the legitimate calibration work explicit:

1. Before seeing calibration results, define the representative scope, reserve one authoritative seed plus at least three distinct fixed calibration seeds, and draft outer acceptance gates that cannot later be loosened to fit observations. Scope covers all intended markets, currencies, store/category/channel types, causal cohort proportions, the production model/policies, and enough rows to exercise the intended 250–400 recommendation cardinality and 200-row default viewport.
2. Use the Rust generator and complete ingestion → Forecast → Inventory → Pricing measurement path. Calibration outputs are temporary, never selected, approved, activated, used as serving input or described as an authoritative source publication. Python remains code/fixture parity-tested and does not produce calibration or authoritative data.
3. Iterate only documented source-native causal cohort parameters—elasticity, observed support, current price position, forecast demand, inventory state, competitor bounds and protection evidence. Never add action labels/targets, rewrite model outputs, modify serving rows or change the business sort.
4. Measure all reserved calibration seeds. Every seed must pass a narrower safety band inside the drafted outer thresholds, including the first-200 viewport, dimension diversity and all other state-family ceilings. This proves robustness rather than fitting one lucky seed.
5. Only then freeze cohort configuration, model/policy fingerprints, manifest expectation fingerprint, the already-reserved authoritative seed and the non-widened outer thresholds. Retain a compact calibration report containing configurations, fingerprints and aggregate measurements; delete each large temporary calibration output after its measurements are recorded.

Calibration may iterate; the promise is **one authoritative source run**, not zero pre-freeze experiments. If the later authoritative output misses a frozen gate, it fails closed and is not repaired in place. A successor attempt requires a diagnosed, versioned source/model/contract correction and is reported as an exception to the one-run target.

### DRY-RUN GATE (cheap, throwaway) — between Stage A and the run
Run generator contract tests and `ingest → build forecast/inventory/pricing → verify → materialize` on a bounded deterministic fixture that contains every required state family. This is an in-memory/temporary contract fixture, not a retained source publication or a second full datagen run; never activate it and remove its temporary output after evidence is captured. The dry run must execute ingestion and upstream ML; starting at Pricing build would not detect a field lost in raw/staging/canonical or a missing forecast/inventory cohort.

### Storage and authority preflight — before the authoritative run

Inventory every datagen (Rust and legacy Python), ingestion, Forecast, Inventory, Pricing/Promotion, PostgreSQL and DuckDB run/materialization and identify which immutable identities the current activation, rollback/predecessor chain, audit evidence and pending comparison still reference. Preserve those identities. Then delete only proven-unreferenced old outputs according to the repository retention contract, including obsolete Python outputs and superseded large sparse trees; compact/vacuum databases only through their supported transactional maintenance path. Record reclaimed size and the retained identity set. Never delete the active or required predecessor authority merely to meet disk pressure.

### Run boundary — one authoritative source run
1. **ONE authoritative Rust datagen run:** generate the frozen profile once, ingest it, pass Gate A/B, and select/pin the successor publication. Python does not produce the run; its equivalent code is parity-tested.
2. **One orchestrated upstream chain:** build, verify and independently select/activate successor Forecast and Inventory authorities in dependency order. Pricing cannot consume unaccepted upstream artifacts.
3. **One Pricing build/lifecycle:** build → verify → materialize → prepare selection(s) → approve → activate. The pricing bundle carries `price_revenue` and, only with external authority, `price_margin`; aggregate promotion is included only on a formally amended/passing branch.
4. **Inventory valuation is not part of the Pricing bundle.** NRV/provisions, if authorized and built, publish through a successor Inventory artifact/version and Inventory activation transaction before Pricing consumes that inventory authority.

### Stage B — page units (targetable, independently validatable, **no runs**)
Each unit does API + UI wiring **and** applies A4's color to that page, so a page is validated **once, holistically** (data + availability + color) against its matrix.

| Unit | Pages | Validate by (post-run, against the one bundle) |
|---|---|---|
| **B1 · Shell + Data Management** | 1 | nav/topbar/footer parity; validation/freshness derived where evidence passes; every source health/freshness/validation state; route dispositions |
| **B2 · Demand Forecast** | 1 (+ owned dialogs; external-owned surfaces reachability-only) | complete Forecast possibility register; Demand-at-Risk/Stock-out unlock; freshness derivation; governed chips; state distributions and colors |
| **B3 · Inventory** | 14 sub-pages | one matrix/register per sub-page; complete status/risk/age/lifecycle distributions; Lost-Sales/Waste; enriched cohorts; conditional NRV/provisions; replay chips |
| **B4 · Pricing** | 4 (Recs / Simulation / Competitor / Promotion) | amended existing matrices; approved action/risk/priority/default-page distribution; conditional margin; waterfall/ring colors; recommendation vs withheld assessment; competitor/stock/forecast enriched; conditional Promotion branch + privacy chips |
| **B5 · Operational states** | cross-page | 409-stale / 503-unavailable via separately-versioned **non-mutating adapters** — proven live, **without** touching the dataset (so no extra run) |

Stage B can be worked and shipped page-by-page in any order; none of it re-runs the pipeline.

### Final activation and demo-readiness gate

Do not activate the successor authorities or present the UI for sign-off until all of the following pass together:

1. authoritative Rust run and Python parity tests; no old Python output used as input;
2. raw/staging/canonical schema, provenance, temporal and state-distribution reconciliation;
3. accepted Forecast and Inventory successors, then verified Pricing/Promotion artifacts;
4. optional `price_margin`, Promotion amended branch and NRV/provision branches activated only with their separate approvals/evidence;
5. no bare missing token on the normal active-rich path; governed chips carry business reason + accessible code;
6. every required enum/state/filter/modal path from §2.2.2 is demonstrable without edits;
7. Price Recommendations passes Hold-majority, Increase/Reduce minority, category/store/channel diversity, dominant-state ceiling and mixed default-page gates;
8. all KPI/table/card counts reconcile to the same scoped population and currency semantics;
9. names—not internal IDs—appear for every governed dimension with a display field;
10. desktop/mobile DOM, keyboard, responsive table/modal, color/token and screenshot comparison pass for every implemented destination;
11. 409/503/loading/empty tests use isolated adapters and do not contaminate the active dataset;
12. the final immutable successor of `client-demo-surface-state-capture-manifest` records desktop/mobile hashes, keyboard results and the exact scripted filters/actions used to expose each possibility; its expectation fingerprint matches the frozen pre-run manifest and the walkthrough is replayed against the final activation.

### Run budget — one source run, one downstream orchestration
“Single run” means one authoritative source generation followed by one dependency-ordered orchestration, not literally one generic ML job or one artifact bundle. Forecast, Inventory, Pricing and Promotion retain separate builders, verifiers, immutable identities and activation authorities. Conditional capabilities absent at the freeze gate remain honestly governed; they are not forced live to protect the run-count target.

An additional **source** run is required only when source bytes/profile/contract change or source/ingestion validation fails. A downstream verifier/model failure may require rebuilding only the affected artifact and its successors if source bytes remain valid. A later genuine external client-cost feed necessarily creates a new source authority and successor chain.

---

## 7 · Proposed decisions and approval gates

These are proposed dispositions for review, not approvals created by this draft. A plan can select an implementation branch, but it cannot supply external client ownership, formally amend Decision #53, approve accounting definitions, or expand Phase-5 route authority by itself. Every item below has an explicit approval/evidence gate before the run freeze.

**D1 · Margin — RESOLVED for the PoC (§A0 / §0.0).** The generated weighted-average cost is the authoritative cost, so primary margin is live (Margin Opportunity/Impact, Current/Expected Margin, simulation Gross Margin) and the minimum-margin floor is enforced on it. The isolated `synthetic_margin_scenario` has been removed. The client-actual adapter (§A3) and a `price_margin` selection lifecycle remain production-only for a future real-data deployment; a generated PoC record still cannot assert external client ownership.

**D2 · Promotion Planner = request formal P5-D23 amendment; branch conditionally.** Origin-safe plans/history, lifecycle/mechanic fields, estimator protocol and P5-D20/P5-D22 gates must all be approved before result inspection. If approval or numeric acceptance fails, serve the exact governed negative/descriptive branch. Decision #19 remains closed: cannibalisation, bundles, segment response/targeting and PII stay `privacy_restricted`.

**D3 · Executive Overview (+ the six other analytics/admin routes) = governed native-disabled, out of implementation scope.** Keep them as visible, native-disabled nav entries with an accessible business reason (owning phase, per `phase5 §1.9`), exact order/label/icon preserved. *Rationale:* implementing seven more full screens exceeds this plan and Phase-5 authority; a native-disabled route with a stated business reason is the governed treatment and is not a data-cell "Not available". Color-parity work still targets the 20 in-scope destinations. (If you want Executive Overview built, it is a separate scoped addition — say so and I'll add a unit.)

**D4 · NRV / provisions = conditional accounting workstream; replay benefits remain withheld.** NRV needs expected recovery/selling price less completion/disposal costs, and provisions need an approved accounting/obsolescence policy; acquisition cost plus markdown depth is insufficient. Build and activate only after those definitions and inputs are approved. Replay-dependent benefits remain governed-withheld because Phase-4 replay did not pass.

**D5 · GOVERNED-KEEP presentation = capability-specific reason chip.** Pricing assessment vocabulary is used only for Pricing assessments. Workflow, privacy, replay, identity, source, and operational failures retain their own truthful vocabulary and accessible reason codes.

**Residual that still shows a governed (non-bare, informative) state rather than a number:** replay-dependent benefits; planner workflow; privacy-restricted promotion elements; unavailable competitor engagement evidence; forecast deltas until two compatible accepted versions exist; disabled routes; promotion until the amended branch passes; and NRV/provisions until accounting inputs and definitions pass. (Primary margin is **no longer** in this list — it is live on the weighted-average cost basis, §A0.)
