# `ui/` — Dashboard front-end

**Purpose:** the real front-end that implements the screens shown in the mockup
`../docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` (that HTML is the **target /
reference**, not production code).

**Framework:** TBD — see `docs/OPEN_DECISIONS.md` (#17).

**Consumes:** the Go `api/`.

**Separate config surface:** the synthetic-scenario Config Builder belongs to `datagen/` and
exports generator YAML/JSON. It is not part of this runtime dashboard. Runtime Settings,
guardrails, users and workflow configuration remain API/DB/UI-owned and audited.

Runtime guardrail editing is market-aware: dimensionless defaults may be global, but absolute
price floors/ceilings, steps, grids and endings are shown and edited only with an explicit
market/currency scope.

Pricing pages must distinguish “no recommendations because evidence is insufficient” from an
empty/error state and display the API's market/department reason code. Monetary controls and
recommendations use the store operating currency; presentment currency is display/audit context
only, while consolidated reporting views use the governed FX conversion.

**Note:** in the mockup, the inventory/replenishment popups are lightweight placeholders. Rich
capture forms (transfer-qty editor, markdown-depth slider, allocation-rule picker, PO override)
are **new UI work**, not just data wiring (spec §8.3 note).

**Spec:** §1 (screen inventory), §8 (all screens).

_No code yet — information only._
