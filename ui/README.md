# `ui/` — Dashboard front-end

**Purpose:** the real front-end that implements the screens shown in the mockup
`../docs/ai_retail_intelligence_dashboard_multicurrency_v6.html` (that HTML is the **target /
reference**, not production code).

**Framework:** React + Vite + TypeScript + Tailwind, with TanStack Query/Table, Recharts and Zod
(decision #17).

**Consumes:** the Go `api/`.

**Portability gate:** development, lint/typecheck, unit/component tests and production build must
run through npm scripts on Windows, macOS and Linux. Tooling cannot depend on Bash environment
assignment, shell glob expansion, `/` path concatenation, symlinks or case-only filename
differences. The browser output and API behavior remain identical across hosts.

## Incremental delivery

UI work does not wait for the final integration phase. After framework decision #17 and the first
versioned screen contract are fixed, build the shell and shared market/currency/status components
in parallel with Phase 2. Each capability phase delivers one demoable vertical slice:

1. Data Management and quality in Phase 2;
2. Demand Forecast in Phase 3;
3. Inventory and Replenishment in Phase 4;
4. Pricing, Competitor Monitor and Promotion Planner in Phase 5;
5. governed approval/override in Phase 6.

Deterministic stubs may lead implementation, but must be visibly labelled and use exactly the
same contract as the live endpoint. Phase 7 completes remaining core screens and removes stubs;
it is not the start of UI development.

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
