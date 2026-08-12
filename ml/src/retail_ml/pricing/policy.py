"""Exact market/currency price grid and candidate guardrails."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable

import yaml


class PricingPolicyError(RuntimeError):
    """A market/currency has no unambiguous executable pricing rule."""


def load_pricing_policy(path: str | Path) -> dict[str, Any]:
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if document.get("schemaVersion") != "retail-pricing-rules/v1":
        raise PricingPolicyError("unsupported pricing-rule schema")
    return document


def resolve_market_rule(
    policy: dict[str, Any], market_id: str, currency_code: str
) -> dict[str, Any]:
    matches = [
        row
        for row in policy["marketCurrencyRules"]
        if row["marketId"] == market_id and row["currencyCode"] == currency_code
    ]
    if len(matches) != 1:
        raise PricingPolicyError(
            f"{market_id}/{currency_code} resolves to {len(matches)} pricing rules"
        )
    return {**policy["globalDefaults"], **matches[0]}


def scaled_change_cap(dominance: Decimal | float | str) -> Decimal:
    value = Decimal(str(dominance))
    if value < Decimal("0.70"):
        raise PricingPolicyError("dominance below 0.70 cannot produce an action")
    bounded = min(value, Decimal("1"))
    return Decimal("0.02") + (
        (bounded - Decimal("0.70")) / Decimal("0.30")
    ) * Decimal("0.03")


def _grid_values(lower: int, upper: int, rule: dict[str, Any]) -> Iterable[int]:
    step = int(rule["candidateStepMinor"])
    origin = int(rule["gridOriginMinor"])
    endings = sorted({int(value) for value in rule["preferredEndingMinor"]})
    start_bucket = (lower - origin) // step - 1
    end_bucket = (upper - origin) // step + 1
    for bucket in range(start_bucket, end_bucket + 1):
        base = origin + bucket * step
        for ending in endings:
            candidate = base + ending
            if lower <= candidate <= upper:
                yield candidate


def enumerate_candidates(
    *,
    current_price_minor: int,
    support_min_minor: int,
    support_max_minor: int,
    dominance: Decimal | float | str,
    rule: dict[str, Any],
    competitor_upper_bound_minor: int | None = None,
) -> tuple[int, ...]:
    if current_price_minor <= 0:
        raise PricingPolicyError("current price must be positive")
    cap = min(
        scaled_change_cap(dominance),
        Decimal(str(rule["maxChangePctPerCycle"])) / Decimal(100),
    )
    lower_by_cap = int(
        (Decimal(current_price_minor) * (Decimal(1) - cap)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    upper_by_cap = int(
        (Decimal(current_price_minor) * (Decimal(1) + cap)).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    lower = max(
        int(rule["minimumPriceMinor"]), support_min_minor, lower_by_cap
    )
    upper = min(
        int(rule["maximumPriceMinor"]), support_max_minor, upper_by_cap
    )
    values = set(_grid_values(lower, upper, rule))
    if lower <= current_price_minor <= upper:
        values.add(current_price_minor)
    if competitor_upper_bound_minor is not None:
        values = {
            value
            for value in values
            if value <= current_price_minor or value <= competitor_upper_bound_minor
        }
    # The rounded integer bounds are only an enumeration envelope. Half-even
    # rounding can move an endpoint one minor unit outside the exact decimal
    # cap, so revalidate each candidate and reject that candidate instead of
    # aborting every otherwise valid series in the build.
    return tuple(
        value
        for value in sorted(values)
        if abs(Decimal(value) / Decimal(current_price_minor) - Decimal(1)) <= cap
        and support_min_minor <= value <= support_max_minor
    )


__all__ = [
    "PricingPolicyError",
    "enumerate_candidates",
    "load_pricing_policy",
    "resolve_market_rule",
    "scaled_change_cap",
]
