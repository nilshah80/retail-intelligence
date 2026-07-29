# `api/` — Go API & serving layer

**Purpose:** serve the Python-produced artifacts to the UI and own the decision/governance layer:
workflow / HITL (approvals, planner overrides, idempotency, audit), **serve-time guardrail
re-validation**, staleness handling (409/503), RBAC / auth.

**Delivery:** introduce a thin, versioned read-only API alongside each demoable capability rather
than waiting for the governance phase: ingestion/quality in Phase 2, demand in Phase 3, inventory
and replenishment in Phase 4, and pricing/promotion in Phase 5. Deterministic UI stubs use the same
OpenAPI/read-model contracts. Phase 6 consolidates and hardens these reads and adds governed
write/workflow endpoints.

**Language:** Go.

**Origin (`[REUSE-as-redesign]`):** the M5 PoC's `api/app.py` (FastAPI), `workflow_service.py`,
and `workflow_repository.py` establish the design and rules; the **code is re-implemented in Go**.

**Boundary:** reads Python artifacts + PostgreSQL + the shared guardrail YAMLs in `contracts/`.
Two hard requirements:
- **Fingerprint parity** — SHA-256 over canonical JSON must be byte-identical to Python's
  (see `contracts/`), or lineage checks 409 spuriously.
- **Single-sourced thresholds** — read guardrail numbers from `contracts/` YAMLs; never hard-code.
- **Market-scoped money** — resolve the same `market_id + currency_code` guardrail payload as
  Python; attach market/currency to price activations and recommendations, reject mismatches, and
  never price in presentment currency or sum local-currency amounts without the governed exact
  local/base→reporting/quote conversion and shared rounding vectors.
- **Evidence disclosure** — return a reason-coded `insufficient_evidence` capability/state for a
  market/department rather than an unexplained empty pricing result.

**Interactive scoring:** compute closed-form projections in Go from stored β / P50 / P90
(`units = p50·(price/price0)^β`, revenue/margin, safety stock); call a Python scoring service only
for model-backed scoring or the LLM copilot (OPEN — see `docs/OPEN_DECISIONS.md`).

**Execution boundary:** Go implements the shared `retail-execution-profile/v1` schema and golden
vectors natively; it does not import Python. Its adapter maps the `api` namespace into
`GOMAXPROCS`, HTTP/background concurrency and PostgreSQL/DuckDB pool limits. Resolved non-secret
values and saturation telemetry are operational metadata only and cannot alter response values,
authorization, idempotency, fingerprints or guardrail decisions.

**Spec:** §4.7–4.8 (HITL, lineage), §8 (screens), Architecture note.

_No code yet — information only._
