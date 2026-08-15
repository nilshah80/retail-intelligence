# Decision #96 — Forecast Scenario Planning v1

**Status:** DECIDED 2026-08-11 on explicit instruction to start implementation.

## Decision

Build Demand Forecast Scenario Planning v1 as a standalone workstream after the accepted Forecast
and Inventory foundations and before Phase 5 Pricing & Promotions. It is not a Phase 5 compatibility
adapter and does not consume fitted price elasticity.

The v1 capability is a stateless, read-only assumption projection:

- additive demand and revenue-potential volume uses Decision #95 `expected_units`;
- P50/P90 remain quantiles and supply dispersion only;
- price, competitor and weather response values come from an immutable, explicitly approved and
  visibly assumption-based bundle, never from fitted evidence;
- Required Inventory scales the accepted node-grain order-up-to and is labelled analytical rather
  than an executable replenishment recommendation;
- stock-out output is a demand-weighted mean of per-series channel probabilities, not a node-event
  probability;
- the request pins the active forecast/scenario context and an explicit present-or-absent inventory
  extension; stale authority returns 409 and unavailable authority returns 503;
- missing row evidence produces reason-coded paired partial results rather than silent substitution;
- market-local money remains available independently of optional Decision #27/#44 reporting-FX
  aggregation; and
- GET/POST perform no database or domain writes.

Phase 5 retains the separately named Price Simulation capability, fitted observational price
response, statistical gates, candidate ranking, pricing recommendations and promotion modelling.
Any later fitted integration is a new Forecast Scenario Planning v2 contract, not an in-place
reinterpretation of v1.

## Engineering authority

This decision record freezes S1–S27; completion evidence is recorded in `plans/local/tasks.md`:
authority/version identity, grains, formulas, factor provenance, partial-result populations,
rounding/FX order, HTTP outcomes, approval lifecycle and the v1/v2 boundary.

Business values inside the assumption bundle remain activation-gated. Test-only placeholder values
must be labelled `synthetic_test`, cannot receive serving approval and cannot activate a live
scenario context.

## Local demonstration boundary

The user's explicit instruction to continue through a usable demo authorizes one labelled Gulf India
assumption bundle under `retailer-demo × tenant-demo × forecast_scenario_v1 × local`. Its values are
illustrative, assumption-based and not fitted evidence. The local activation command refuses every
non-local environment. This completes the PoC demonstration path without claiming product/quant
approval or changing the production rollout gate.

## Presentation amendment

The Demand Forecast screen contract remains top-level
`frozen_approved_for_implementation`. Amendment `FSP-V1-A1` changes only
`#forecastScenarioBtn` from `unavailable_phase_5` to `approved_pending_implementation`. A second
recorded amendment may mark the element `live_assumption_projection` only after the API/UI,
contract, accessibility, parity and human-review gates pass against an approved active context.

## Authorization

The user explicitly instructed implementation to start after reviewing revision 3.6. That
authorizes the pre-live authority amendment and implementation work. It does not fabricate
product/quant approval of assumption values, independent visual acceptance or deployment approval.
The later instruction to continue and complete the demo additionally authorizes the local-only
activation above; production approval remains outstanding.
