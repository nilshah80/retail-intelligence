"""Net-new inventory analytics: position health, days of supply, ageing,
expiry/waste exposure, valuation and supplier risk (P4-6).

No M5 source exists for any of these. They are pure functions over verified
inputs, like the rest of the package: every threshold comes from the resolved
policy, every tie-break is frozen, and a cell whose inputs cannot support a
number returns a reason code rather than a convenient proxy (P4-6 stop rule).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Sequence

from retail_ml.engines.primitives import InventoryPosition

#: Deterministic health classes, worst first. The order is the sort order the
#: read models serve, so it is part of the contract rather than presentation.
HEALTH_CLASSES = ("stockout", "understock", "healthy", "overstock", "dead")


def days_of_supply(
    *,
    position_units: int,
    trailing_avg_daily_units: Decimal,
) -> Decimal | None:
    """Position divided by trailing observed daily demand.

    None when trailing demand is zero: a cell with stock and no demand has
    INFINITE cover, and rendering a huge number invites sorting artifacts while
    rendering zero inverts the meaning entirely. The caller renders the governed
    unavailable state with DEAD_STOCK_NO_DEMAND context instead.
    """

    if position_units < 0:
        raise ValueError("position_units must be >= 0")
    if trailing_avg_daily_units < 0:
        raise ValueError("trailing demand must be >= 0")
    if trailing_avg_daily_units == 0:
        return None
    return Decimal(position_units) / trailing_avg_daily_units


def classify_health(
    *,
    position: InventoryPosition,
    trailing_avg_daily_units: Decimal,
    assortment_active: bool,
    understock_cover_days: Decimal = Decimal("7"),
    overstock_cover_days: Decimal = Decimal("45"),
) -> dict[str, Any]:
    """One deterministic class per SKU x location cell.

    The precedence is frozen: stockout beats understock beats overstock, and
    `dead` is reserved for stock without demand -- which includes every
    de-assorted residual cell, the population the ageing screen exists for.
    An active cell with no stock and no demand is `stockout` only when demand
    exists; with neither stock nor demand it is simply not emitted upstream.
    """

    cover = days_of_supply(
        position_units=position.position_units,
        trailing_avg_daily_units=trailing_avg_daily_units,
    )
    if trailing_avg_daily_units == 0:
        return {
            "health_class": "dead",
            "cover_days": None,
            "reason_code": (
                "DEAD_STOCK_DEASSORTED" if not assortment_active
                else "DEAD_STOCK_NO_DEMAND"
            ),
        }
    if position.atp_units == 0:
        return {"health_class": "stockout", "cover_days": cover, "reason_code": None}
    assert cover is not None
    if cover < understock_cover_days:
        return {"health_class": "understock", "cover_days": cover, "reason_code": None}
    if cover > overstock_cover_days:
        return {"health_class": "overstock", "cover_days": cover, "reason_code": None}
    return {"health_class": "healthy", "cover_days": cover, "reason_code": None}


#: P4-D7 ageing ladder. Bucket edges in days, then the frozen action per bucket
#: from inventory-policy/2.0.0 hold/markdown thresholds.
AGE_BUCKETS = ((0, 30), (30, 60), (60, 90), (90, 180), (180, None))


def age_bucket(*, on_hand_age_days: int) -> str:
    if on_hand_age_days < 0:
        raise ValueError("age must be >= 0")
    for lower, upper in AGE_BUCKETS:
        if upper is None or on_hand_age_days < upper:
            return f"{lower}-{upper if upper is not None else 'plus'}"
    raise AssertionError("unreachable: the last bucket is unbounded")


def ageing_action(
    *,
    on_hand_age_days: int,
    cover_days: Decimal | None,
    hold_cover_days: int,
    markdown_cover_days: int,
    markdown_pct: Decimal,
) -> dict[str, Any]:
    """The deterministic action ladder: watch -> hold -> markdown_candidate.

    `markdown_candidate` is a read-only classification, not a price change:
    pricing belongs to Phase 5, and P4-D10 keeps NRV unavailable. Cover of None
    (no demand) escalates straight to markdown_candidate once aged -- dead stock
    is not going to sell through on its own.
    """

    if cover_days is None:
        action = (
            "markdown_candidate" if on_hand_age_days >= markdown_cover_days
            else "hold"
        )
    elif on_hand_age_days >= markdown_cover_days and cover_days > markdown_cover_days:
        action = "markdown_candidate"
    elif on_hand_age_days >= hold_cover_days and cover_days > hold_cover_days:
        action = "hold"
    else:
        action = "watch"
    return {
        "action": action,
        "markdown_pct": str(markdown_pct) if action == "markdown_candidate" else None,
    }


def expiry_exposure(
    batches: Sequence[Mapping[str, Any]],
    *,
    as_of: date,
    window_days: int = 30,
) -> dict[str, Any]:
    """Units and cost expiring inside the window, for shelf-life batches only.

    A batch without an expiry date contributes nothing: inventing an expiry for
    a non-perishable would fabricate waste evidence (the same rule the store
    echelon applies at generation).
    """

    expiring_units = 0
    expired_units = 0
    exposure_minor = 0
    currencies: set[str] = set()
    for batch in batches:
        expiry = batch.get("expiry_date")
        if expiry is None:
            continue
        units = int(batch["on_hand_units"])
        if units <= 0:
            continue
        unit_cost = batch.get("unit_cost_minor")
        if expiry < as_of:
            expired_units += units
        elif (expiry - as_of).days <= window_days:
            expiring_units += units
            if unit_cost is not None:
                exposure_minor += units * int(unit_cost)
                currencies.add(str(batch["currency_code"]))
    if len(currencies) > 1:
        raise ValueError(
            f"expiry exposure crosses currencies {sorted(currencies)}; compute "
            "per market and convert only under approved reporting FX"
        )
    return {
        "expiring_units": expiring_units,
        "expired_units": expired_units,
        "exposure_minor": exposure_minor,
        "currency_code": next(iter(currencies), None),
        "window_days": window_days,
    }


def store_wac_minor(
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Store weighted-average cost from cost-carrying receipt/transfer facts.

    P4-D6: store WAC is computed from the store's OWN receipt evidence. When no
    cost-carrying receipt exists the result is a reason code -- a lane-imputed DC
    WAC is a separately approved, visibly labelled fallback that this function
    never silently performs.
    """

    total_units = 0
    total_cost = 0
    currencies: set[str] = set()
    for receipt in receipts:
        units = int(receipt["qty"])
        cost = receipt.get("unit_cost_minor")
        if units <= 0 or cost is None:
            continue
        total_units += units
        total_cost += units * int(cost)
        currencies.add(str(receipt["currency_code"]))
    if len(currencies) > 1:
        raise ValueError(
            f"store WAC crosses currencies {sorted(currencies)}"
        )
    if total_units == 0:
        return {
            "wac_minor": None,
            "method": None,
            "reason_code": "STORE_COST_EVIDENCE_ABSENT",
            "currency_code": None,
        }
    return {
        "wac_minor": total_cost // total_units,
        "method": "store_receipt_wac",
        "reason_code": None,
        "currency_code": next(iter(currencies)),
    }


def supplier_risk(
    *,
    otd_rate: Decimal,
    lead_time_std_days: Decimal | None,
    capacity_confirmed_pct: Decimal,
    capacity_floor_pct: Decimal,
) -> dict[str, Any]:
    """Deterministic supplier risk from OTD, variability and capacity.

    The classification is coarse on purpose -- high/medium/low from frozen
    thresholds -- because a finer score would imply a model nobody fitted.
    Missing variability is itself a finding (zero-variance terms were the v1
    defect), so it caps the class at medium rather than passing as calm.
    """

    reasons: list[str] = []
    if otd_rate < Decimal("0.90"):
        reasons.append("OTD_BELOW_FLOOR")
    if capacity_confirmed_pct < capacity_floor_pct:
        reasons.append("CAPACITY_UNCONFIRMED")
    if lead_time_std_days is None:
        reasons.append("LEAD_TIME_VARIABILITY_UNAVAILABLE")
    elif lead_time_std_days > Decimal("3"):
        reasons.append("LEAD_TIME_VOLATILE")

    if "OTD_BELOW_FLOOR" in reasons and len(reasons) >= 2:
        risk_class = "high"
    elif reasons:
        risk_class = "medium"
    else:
        risk_class = "low"
    return {"risk_class": risk_class, "reason_codes": reasons}


__all__ = [
    "AGE_BUCKETS",
    "HEALTH_CLASSES",
    "age_bucket",
    "ageing_action",
    "classify_health",
    "days_of_supply",
    "expiry_exposure",
    "store_wac_minor",
    "supplier_risk",
]
