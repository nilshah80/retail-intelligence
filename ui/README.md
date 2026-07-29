# `ui/` — Dashboard front-end

For the complete environment setup, accepted-data pipeline and API startup sequence, start with
the root `README.md`. This file documents UI-specific behavior and commands.

**Purpose:** the real front-end that ports
`../docs/ai_retail_intelligence_dashboard_multicurrency_v6.html`. That HTML is the authoritative,
review-controlled visible UI contract—not a moodboard. React may replace sample values with live
API values, but it must preserve the shell, navigation hierarchy/order, top filters, currency
strip, page composition, labels, columns, bottom KPIs, footer, palette and spacing unless a
deviation is explicitly approved.

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

Deterministic fixtures may lead API/component tests, but they are not demo data. Before coding a
screen, its original HTML elements must be mapped to reviewed live data definitions and API
fields. A screen becomes demoable only after screenshot/DOM parity, live-value tests and human
visual approval. Phase 7 completes remaining core screens; it is not permission to redesign the
vertical slices delivered earlier.

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

## Phase-2 UI status

The current React screen proves live Aarv API connectivity, TanStack Query/Zod validation and
fail-closed behavior, but it is **not an accepted UI deliverable**. Its dark control-room shell,
reduced navigation and engineering-oriented panels diverge from the agreed HTML and its Data
Management data points. The parity-recovery tasks are recorded in `../plans/local/tasks.md`; UI
implementation must not continue until the Data Management parity/data matrix is reviewed.

The only approved temporary omissions are **Add Data Source**, **Upload Sample Data**, **Run
Validation**, and user/User Management UI until that scope is implemented. Product UI must not
show phase numbers, roadmap labels, “governed ingestion,” source hashes or other delivery
language. Gate/fingerprint/capability evidence remains available through API/Swagger and tests
unless an original screen explicitly requires a business-facing representation.

All original KPI positions are supported by the completed PoC plan, but they do not all exist in
Phase 2 and must never be filled with nearby technical counts:

| KPI family | Data/owning phase |
|---|---|
| Data Management: Connected Sources, Rejected Records, Last Refresh | Phase-2 landing, profile, quarantine and ingest evidence |
| Data Management: Data Freshness, Quality Score | Phase 2, after the reviewed freshness cutoff/denominator and quality-weight formula are frozen |
| Footer: Total SKUs, Active SKUs, Stores, Channels | Phase-2 curated product/location/channel facts |
| Footer: Forecast Coverage, Model Accuracy | Phase 3 forecast/backtest artifacts; show the approved unavailable state before models exist |
| Demand Forecast KPIs | Phase 3 |
| Inventory/Replenishment KPIs | Phase 4 |
| Pricing/Competitor/Promotion KPIs | Phase 5 |
| Approval/workflow/audit KPIs | Phase 6 |
| Model registry/drift and remaining analytics/admin KPIs | Phase 8 |

Thus “data exists in datagen” is not itself enough to display a KPI. Each visible value still needs
its reviewed business formula, filter grain, currency/time-window semantics and API field.

The package and script names are cross-platform and contain no shell-specific environment syntax:

```text
npm ci
npm run typecheck
npm test
npm run build
npm run dev
```

During local development Vite proxies `/api` and `/healthz` to `http://127.0.0.1:8080`. Start the
Go server first, then run `npm run dev` from `ui/` and open `http://127.0.0.1:5173`.
