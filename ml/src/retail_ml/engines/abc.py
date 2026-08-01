"""Cost-weighted ABC classification (P4-D7).

Ported from M5 `engines/reorder.py::classify_abc` and re-contracted: the basis is
annualized consumption VALUE in market-local minor units, the thresholds compare
the cumulative share BEFORE the current SKU, and cross-market ranking is refused
outright. Net revenue is not the basis, and nominal money across INR and USD
would order SKUs by exchange rate.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence


def classify_abc(
    rows: Sequence[Mapping[str, object]],
    *,
    a_below: Decimal = Decimal("0.80"),
    b_below: Decimal = Decimal("0.95"),
) -> dict[tuple[str, str], dict[str, object]]:
    """Classify SKU x node cells within ONE market.

    Each row carries `sku_id`, `location_id`, `market_id`,
    `trailing_avg_weekly_units` (Decimal-compatible) and
    `accepted_unit_cost_minor` (int, market-local) or None.

    The SKU that CROSSES 80% stays A and the one that crosses 95% stays B: the
    comparison is `share_before_current_sku < threshold`, which is what the
    specification and the M5 implementation both do. A missing cost excludes the
    cell with a reason code rather than ranking it at zero -- zero would place
    every uncosted SKU in C and call that a classification.
    """

    markets = {str(row["market_id"]) for row in rows}
    if len(markets) > 1:
        raise ValueError(
            f"ABC is market-local; got {sorted(markets)}. Rank each market "
            "separately or convert under an approved reporting FX policy first."
        )
    if not (Decimal("0") < a_below < b_below < Decimal("1")):
        raise ValueError("thresholds must satisfy 0 < a_below < b_below < 1")

    valued: list[tuple[Decimal, str, str]] = []
    results: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (str(row["sku_id"]), str(row["location_id"]))
        cost = row.get("accepted_unit_cost_minor")
        if cost is None:
            results[key] = {
                "abc_class": None,
                "reason_code": "ABC_UNIT_COST_UNAVAILABLE",
                "annualized_value_minor": None,
            }
            continue
        annualized = (
            Decimal(str(row["trailing_avg_weekly_units"]))
            * Decimal(52)
            * Decimal(int(cost))
        )
        valued.append((annualized, key[0], key[1]))

    # Frozen tie-break: value desc, then sku asc, then location asc. A tie broken
    # by dict order is a tie broken differently on the next run.
    valued.sort(key=lambda item: (-item[0], item[1], item[2]))
    total = sum((item[0] for item in valued), Decimal(0))
    cumulative = Decimal(0)
    for annualized, sku_id, location_id in valued:
        share_before = cumulative / total if total else Decimal(0)
        if share_before < a_below:
            abc_class = "A"
        elif share_before < b_below:
            abc_class = "B"
        else:
            abc_class = "C"
        results[(sku_id, location_id)] = {
            "abc_class": abc_class,
            "reason_code": None,
            "annualized_value_minor": annualized,
        }
        cumulative += annualized
    return results


__all__ = ["classify_abc"]
