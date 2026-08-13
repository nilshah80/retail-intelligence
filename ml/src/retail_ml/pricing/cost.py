"""Conditional client-actual cost resolution and the margin reason gate.

Generated pipeline data never carries ``client_actual`` provenance — ``build.py``
stamps ``generated_source_native`` — so it resolves to ``COST_NOT_CLIENT_ACTUAL``
and can never drive a margin number. Only a genuine external/client-owned cost
ledger (or a ``synthetic_test`` fixture that structurally mimics one, used to
exercise parsers and negative gates) carries ``client_actual`` provenance, and
even then it is admitted only after the full ownership → value → currency → scope
→ method → temporal gate frozen in ``contracts/pricing/cost-evidence.schema.json``
and the ``clientActualCost`` precedence in ``contracts/pricing/reason-codes.json``.

This module owns only the *arithmetic* gate. Whether a ``client_actual`` record is
genuinely client-owned (versus a synthetic test fixture) is an attestation/approval
concern enforced at the build and activation layers: the generated pipeline never
stamps ``client_actual``, and ``price_margin`` activation additionally requires
external approval evidence. Resolving a cost here does not by itself authorise an
active ``price_margin`` selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping

# The only provenance marker that makes a cost record eligible for the client
# margin capability. The generated pipeline must never emit this value.
CLIENT_ACTUAL_PROVENANCE = "client_actual"

# Genuine client ownership also requires the client evidence class and an explicit
# pricing-margin allowed-use attestation. `synthetic_test` records are structurally
# valid but never client-owned, so they can prove parsing and negative gates
# without ever producing a served margin.
CLIENT_EVIDENCE_CLASS = "client"
CLIENT_ALLOWED_USE = "pricing_margin"

# WAC is computable directly from the accepted cost ledger. FIFO additionally
# requires verified receipt-layer depletion (``cost_method_verified``); an
# unverified FIFO label is refused rather than trusted.
SUPPORTED_COST_METHODS = frozenset({"WAC", "FIFO"})

# Frozen freshness envelope until a policy value is bound. A client-actual
# observation older than this relative to the decision origin is refused as stale.
DEFAULT_COST_MAX_AGE_DAYS = 365


# Frozen precedence order for the client-actual cost gate, mirrored in
# contracts/pricing/reason-codes.json ("clientActualCost"). The primary
# reason_code is the first failing check in this order; every other failing
# check is retained as secondary evidence so a reviewer sees the complete
# picture, not only the first failure.
_CLIENT_ACTUAL_PRECEDENCE: tuple[str, ...] = (
    "COST_NOT_CLIENT_ACTUAL",
    "COST_OWNERSHIP_REVOKED",
    "COST_MISSING",
    "COST_NON_POSITIVE",
    "COST_CURRENCY_MISMATCH",
    "COST_SCOPE_MISMATCH",
    "COST_METHOD_UNSUPPORTED",
    "FIFO_NOT_VERIFIED",
    "COST_AFTER_DECISION_ORIGIN",
    "COST_STALE",
)


@dataclass(frozen=True)
class CostResolution:
    """Outcome of the client-actual cost gate for one pricing key.

    Exactly one of (``cost_minor``, ``reason_code``) is populated, which keeps the
    downstream ``margin_impact_minor`` null ⇔ ``margin_reason_code`` not-null
    invariant that the bundle verifier enforces. ``reason_code`` is the precedence-
    selected primary reason; ``secondary_reason_codes`` carries every other failing
    check in precedence order.
    """

    cost_minor: int | None
    reason_code: str | None
    method: str | None = None
    secondary_reason_codes: tuple[str, ...] = ()

    @property
    def is_client_actual(self) -> bool:
        return self.cost_minor is not None and self.reason_code is None

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Primary reason followed by the complete secondary set (empty if resolved)."""
        if self.reason_code is None:
            return ()
        return (self.reason_code, *self.secondary_reason_codes)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def resolve_client_cost(
    row: Mapping[str, Any],
    *,
    price_currency_code: str,
    market_id: str,
    store_id: str,
    decision_as_of: str | None = None,
    max_age_days: int = DEFAULT_COST_MAX_AGE_DAYS,
) -> CostResolution:
    """Resolve the client-actual cost for a pricing key, or every reason it is withheld.

    Each check is evaluated independently and its reason collected; the primary
    ``reason_code`` is the first failure in the frozen ``clientActualCost``
    precedence order and the rest are retained as secondary evidence. A generated
    or synthetic record fails ownership, so no non-client cost can ever leak into a
    margin number. Field names are the internal snake_case row; the external
    client-feed contract (cost-evidence.schema.json, camelCase) is mapped onto them
    by the (future) ingestion adapter.
    """

    failures: set[str] = set()

    # Ownership — generated, reference, and synthetic-native cost is never
    # client-actual. Genuine client ownership requires client_actual provenance,
    # the client evidence class, and an explicit pricing-margin allowed-use
    # attestation; a synthetic_test fixture can prove parsers and negative gates
    # but must never resolve to a served margin (P5-D6).
    if (
        row.get("cost_provenance") != CLIENT_ACTUAL_PROVENANCE
        or row.get("cost_evidence_class") != CLIENT_EVIDENCE_CLASS
        or row.get("cost_allowed_use") != CLIENT_ALLOWED_USE
    ):
        failures.add("COST_NOT_CLIENT_ACTUAL")
    if str(row.get("cost_ownership_status", "active")) == "revoked":
        failures.add("COST_OWNERSHIP_REVOKED")

    # Existence and positive value.
    raw = row.get("client_actual_cost_minor")
    cost_minor: int | None = None
    if raw is None:
        failures.add("COST_MISSING")
    else:
        try:
            cost_minor = int(raw)
        except (TypeError, ValueError):
            cost_minor = None
            failures.add("COST_MISSING")
        else:
            if cost_minor <= 0:
                failures.add("COST_NON_POSITIVE")

    # Currency — the cost ledger must be the operating price currency; never
    # silently converted.
    cost_currency = row.get("cost_currency_code") or row.get("currency_code")
    if cost_currency != price_currency_code:
        failures.add("COST_CURRENCY_MISMATCH")

    # Scope — the cost record must apply to this market and location. Absent
    # explicit scope fields the record is assumed keyed to this row.
    scope_market = row.get("cost_scope_market_id", market_id)
    scope_store = row.get("cost_scope_location_id", store_id)
    if str(scope_market) != str(market_id) or str(scope_store) != str(store_id):
        failures.add("COST_SCOPE_MISMATCH")

    # Method — WAC is computable; FIFO requires verified depletion.
    method = str(row.get("cost_method") or "")
    if method not in SUPPORTED_COST_METHODS:
        failures.add("COST_METHOD_UNSUPPORTED")
    elif method == "FIFO" and not bool(row.get("cost_method_verified", False)):
        failures.add("FIFO_NOT_VERIFIED")

    # Temporal — the observation must be no later than the decision origin and
    # within the freshness envelope. The manifest cutoff is only a fallback upper
    # bound; a genuine feed carries its own row-level observation time.
    origin = _parse_timestamp(decision_as_of) or _parse_timestamp(row.get("cost_as_of"))
    known = _parse_timestamp(row.get("cost_known_as_of"))
    if origin is not None:
        if known is None:
            failures.add("COST_STALE")
        elif known > origin:
            failures.add("COST_AFTER_DECISION_ORIGIN")
        elif known < origin - timedelta(days=max_age_days):
            failures.add("COST_STALE")

    ordered = tuple(code for code in _CLIENT_ACTUAL_PRECEDENCE if code in failures)
    if ordered:
        return CostResolution(
            None, ordered[0], secondary_reason_codes=ordered[1:]
        )
    return CostResolution(cost_minor, None, method=method)


def gross_margin_pct(price_minor: int, cost_minor: int) -> Decimal:
    """Gross margin percent ``(price - cost) / price * 100``, exact to 4 dp.

    The same unit is used by the min-margin candidate guard and by the
    Current/Expected Margin percentage fields, so they can never diverge.
    """

    price = Decimal(int(price_minor))
    if price <= 0:
        raise ValueError("price must be positive to compute margin percent")
    return ((price - Decimal(int(cost_minor))) / price * Decimal(100)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_EVEN
    )


__all__ = [
    "CLIENT_ACTUAL_PROVENANCE",
    "SUPPORTED_COST_METHODS",
    "DEFAULT_COST_MAX_AGE_DAYS",
    "CostResolution",
    "resolve_client_cost",
    "gross_margin_pct",
]
