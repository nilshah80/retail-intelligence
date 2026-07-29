# `api/` — Aarv-based Go API & serving layer

**Purpose:** serve the Python-produced artifacts to the UI and own the decision/governance layer:
workflow / HITL (approvals, planner overrides, idempotency, audit), **serve-time guardrail
re-validation**, staleness handling (409/503), RBAC / auth.

**Delivery:** introduce a thin, versioned read-only API alongside each demoable capability rather
than waiting for the governance phase: ingestion/quality in Phase 2, demand in Phase 3, inventory
and replenishment in Phase 4, and pricing/promotion in Phase 5. Deterministic UI stubs use the same
OpenAPI/read-model contracts. Phase 6 consolidates and hardens these reads and adds governed
write/workflow endpoints.

**Language and web framework:** Go with
[Aarv](https://github.com/nilshah80/aarv), imported from
`github.com/nilshah80/aarv`. The API scaffold must pin an exact Aarv version in `api/go.mod`;
it must not build against an unpinned `@latest`.

Aarv owns only the HTTP transport boundary: routing, request binding, middleware composition,
lifecycle and graceful shutdown. Handlers remain thin and delegate to `internal/` packages for
read models, workflow, fingerprints, execution profiles, guardrails and persistence. The
versioned OpenAPI documents in `contracts/` remain authoritative; framework-generated
documentation or an Aarv OpenAPI/UI plugin may expose that contract but must not become a second
semantic source of truth. Optional Aarv plugins are added à la carte and pinned independently
where they are separate Go modules.

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

**Portability:** the Aarv application and all middleware must use portable Go APIs and be tested
on Windows, macOS and Linux. Application paths use `filepath`; manifest identifiers remain
normalized logical `/` paths; shutdown, locking and process control must not depend on POSIX-only
signals or shell scripts. File-backed readers and DuckDB connections close before replacement,
and OS-specific signal adapters must preserve the same graceful-shutdown contract.

**Spec:** §4.7–4.8 (HITL, lineage), §8 (screens), Architecture note.

_No code yet — information only._
