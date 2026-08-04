"""Pure inventory-position, protection and reorder primitives.

Ported from M5 `engines/reorder.py`
(sha256 9ff4697b00cc0ff1b7d96ab9ee6cb66d4a0ff51e81b155f5deab8bd18cc9125d) and
re-contracted for retail_v2, inventory-policy/2.0.0 and weekly horizons. Three
M5 behaviours were deliberately dropped rather than preserved for reuse credit:

* `service_level_scale` normalized z against z(0.90); policy v2's formula uses
  the raw z value, so the normalization is gone rather than silently kept.
* `cap_order_to_cover` rounded DOWN to a pack and silently returned 0 below MOQ;
  policy v2 freezes `capConflictBehavior: refuse_with_reason`, so a conflict
  raises with `MOQ_EXCEEDS_MAX_COVER` instead of vanishing an order.
* Store-only keys are replaced by explicit market/location typing at the caller.

The fractional-horizon helpers survive as-is: they are the load-bearing part of
the port, and their weekly-weight semantics are what the golden vectors pin.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

#: Policy v2 `reorder.capConflictBehavior` reason code.
CAP_CONFLICT_REASON = "MOQ_EXCEEDS_MAX_COVER"


class OrderConstraintError(ValueError):
    """MOQ, pack and cap constraints cannot all be satisfied."""

    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


@dataclass(frozen=True)
class InventoryPosition:
    """Disjoint buckets per the policy-v2 `inventoryPosition` contract."""

    on_hand_units: int
    committed_units: int
    reserved_units: int
    damaged_units: int
    on_order_units: int
    in_transit_units: int

    def __post_init__(self) -> None:
        for name in (
            "on_hand_units",
            "committed_units",
            "reserved_units",
            "damaged_units",
            "on_order_units",
            "in_transit_units",
        ):
            if getattr(self, name) < 0:
                # Negative inventory is a critical quality violation upstream;
                # an engine computing on it would launder the defect into a
                # recommendation.
                raise ValueError(f"{name} must be >= 0")

    @property
    def atp_units(self) -> int:
        return max(
            0,
            self.on_hand_units
            - self.committed_units
            - self.reserved_units
            - self.damaged_units,
        )

    @property
    def position_units(self) -> int:
        return self.atp_units + self.on_order_units + self.in_transit_units


def inventory_position(position: InventoryPosition) -> int:
    return position.position_units


def service_level_z(service_level: str | float) -> float:
    """z for a service level, bounded to the policy's meaningful domain.

    Accepts the canonical decimal STRING policy v2 stores ("0.96"), because a
    float that has already been through repr is how two languages disagree at
    the 15th digit.
    """

    value = float(service_level)
    if not 0.50 <= value <= 0.995:
        raise ValueError(
            f"service level {value} is outside [0.50, 0.995]; a level below "
            "0.5 asks for negative safety stock and above 0.995 is not a "
            "buffer, it is a warehouse"
        )
    return NormalDist().inv_cdf(value)


def protection_period_days(lead_time_days: int, review_period_days: int) -> int:
    """Lead plus review. The weekly horizon consumed is ceil(days / 7):
    truncating a fractional week would under-protect every non-multiple lead."""

    if lead_time_days < 0 or review_period_days < 0:
        raise ValueError("lead and review periods must be >= 0")
    return lead_time_days + review_period_days


def required_horizon_weeks(protection_days: int) -> int:
    return max(1, math.ceil(protection_days / 7))


def fractional_horizon_sum(values: tuple[float, ...], days: int) -> float:
    """Sum weekly values across a fractional window (M5-ported, unchanged)."""

    if days <= 0:
        return 0.0
    if not values:
        raise ValueError("forecast arrays must not be empty")
    remaining_weeks = days / 7.0
    total = 0.0
    for value in values:
        if remaining_weeks <= 0:
            break
        weight = min(1.0, remaining_weeks)
        total += float(value) * weight
        remaining_weeks -= weight
    if remaining_weeks > 0:
        total += float(values[-1]) * remaining_weeks
    return total


def fractional_horizon_rss(values: tuple[float, ...], days: int) -> float:
    """Root-sum-square weekly spreads across a fractional window (M5-ported).

    RSS assumes week-to-week independence. That assumption is declared by
    policy v2 (`safetyStock.formula`), not silently introduced here -- and it is
    applied to WEEKLY spreads for ONE series only. Summing across stores or
    channels with RSS is forbidden by P4-D16.
    """

    if days <= 0:
        return 0.0
    if not values:
        raise ValueError("forecast arrays must not be empty")
    remaining_weeks = days / 7.0
    squared = 0.0
    for value in values:
        if remaining_weeks <= 0:
            break
        weight = min(1.0, remaining_weeks)
        squared += (max(0.0, float(value)) * weight) ** 2
        remaining_weeks -= weight
    if remaining_weeks > 0:
        squared += (max(0.0, float(values[-1])) * remaining_weeks) ** 2
    return math.sqrt(squared)


@dataclass(frozen=True)
class SafetyStock:
    """A buffer and the two drivers policy v2 says it is made of.

    Returned instead of a bare float so the Safety Stock screen's driver
    decomposition has a source. The two components combine in QUADRATURE, so
    `demand_units + lead_time_units` deliberately does not equal `total_units`;
    presenting them as an additive split would be a different (and wrong) claim.
    """

    total_units: float
    demand_units: float
    lead_time_units: float
    #: Set when the lead-time term could not be computed, so the total is the
    #: demand driver alone. `None` means both drivers are real.
    lead_time_reason_code: str | None

    def __float__(self) -> float:
        return self.total_units


def safety_stock_units(
    *,
    weekly_spreads: tuple[float, ...],
    protection_days: int,
    service_level: str | float,
    weekly_p50: tuple[float, ...] = (),
    lead_time_variance_weeks: float | None = None,
    lead_time_reason_code: str | None = None,
) -> SafetyStock:
    """Safety stock from the accepted interval spread, and lead-time variability.

    `weekly_spreads` is (p90 - p50) per horizon week for ONE SeriesKey. Every
    element must be a real published interval: a withheld interval never reaches
    this function, because the interval guard skips the row first. A negative
    spread is an inverted quantile pair and is refused, not clamped -- clamping
    would hide upstream corruption inside a buffer.

    Policy v2 declares

        z * sqrt(protection_weeks * demand_variance_weekly
                 + mean_weekly_demand^2 * lead_time_variance_weeks)

    and until `P4-12g` only the first addend existed. The demand term is derived
    from the accepted interval rather than from a variance estimate, which
    `safetyStock.intervalSource` declares: dividing the P90-P50 spread by the 0.90
    normal quantile converts it to a one-sigma equivalent, and the RSS across the
    protection window is that window's sigma. The second addend was absent
    entirely, so `leadTime.variabilityMethod`, `leadTime.minimumObservations` and
    `leadTime.zeroVarianceBehavior` had no consumer and a supplier whose lead time
    swung by nine days got the same buffer as a metronomic one.

    `lead_time_variance_weeks` is None when the variability is not knowable -- an
    internal lane has no supplier performance, and an under-observed supplier has
    no admissible estimate. That is reason-coded rather than treated as zero
    variance, because policy v2's `zeroVarianceBehavior` is
    `reason_code_not_zero_buffer`: a zero-variance buffer is a misleading number
    rather than a missing one.
    """

    for index, spread in enumerate(weekly_spreads):
        if spread < 0:
            raise ValueError(
                f"weekly spread at h{index + 1} is negative; P50<=P90 must "
                "hold for every available interval"
            )
    if lead_time_variance_weeks is not None and lead_time_variance_weeks < 0:
        raise ValueError(
            "lead-time variance cannot be negative; a variance is a square"
        )
    z = service_level_z(service_level)
    demand_sigma = (
        fractional_horizon_rss(weekly_spreads, protection_days)
        / NormalDist().inv_cdf(0.90)
    )
    lead_time_sigma = 0.0
    if lead_time_variance_weeks:
        # mean_weekly_demand^2 * lead_time_variance_weeks, under the same root.
        # The mean is taken over the SAME protection window the demand term uses,
        # so the two drivers describe one horizon rather than two.
        weeks = protection_days / 7.0
        mean_weekly_demand = (
            fractional_horizon_sum(weekly_p50, protection_days) / weeks
            if weeks > 0 and weekly_p50
            else 0.0
        )
        lead_time_sigma = mean_weekly_demand * math.sqrt(lead_time_variance_weeks)
    return SafetyStock(
        total_units=z * math.sqrt(demand_sigma**2 + lead_time_sigma**2),
        demand_units=z * demand_sigma,
        lead_time_units=z * lead_time_sigma,
        lead_time_reason_code=(
            None if lead_time_variance_weeks else lead_time_reason_code
        ),
    )


def reorder_point(
    *,
    weekly_p50: tuple[float, ...],
    protection_days: int,
    safety_stock: float,
) -> float:
    return fractional_horizon_sum(weekly_p50, protection_days) + safety_stock


def order_up_to_level(
    *,
    reorder_point_units: float,
    weekly_p50: tuple[float, ...],
    review_period_days: int,
) -> float:
    return reorder_point_units + fractional_horizon_sum(
        weekly_p50, review_period_days
    )


def round_up_to_pack(value: float, pack_qty: int) -> int:
    """Round UP to a pack multiple. Rounding down orders less than the policy
    asked for, silently (M5-ported, direction preserved)."""

    if pack_qty <= 0:
        raise ValueError("pack_qty must be positive")
    if value <= 0:
        return 0
    return int(math.ceil(value / pack_qty) * pack_qty)


def apply_order_constraints(
    raw_quantity: float,
    *,
    moq: int,
    pack_qty: int,
    inventory_position_units: int,
    avg_daily_demand: float,
    max_cover_days: int,
) -> int:
    """MOQ, pack multiple and max-cover cap, in the frozen order.

    Policy v2 `reorder.rounding`: apply MOQ, then pack, then caps -- and when the
    constraints conflict, REFUSE with a reason rather than silently violating
    one of them. The M5 behaviour (round down, return 0 below MOQ) made a
    conflicted order indistinguishable from no demand.
    """

    if moq < 0 or pack_qty <= 0 or max_cover_days <= 0:
        raise ValueError("moq must be >= 0, pack_qty and max_cover_days positive")
    if raw_quantity <= 0:
        return 0
    quantity = max(float(moq), raw_quantity) if moq else raw_quantity
    quantity_units = round_up_to_pack(quantity, pack_qty)
    if avg_daily_demand < 0:
        # Policy v2 `reorder.negativeDemandBehavior`: treat as zero. With no
        # demand there is no cover cap to compute and no order to place.
        return 0
    cap_units = avg_daily_demand * max_cover_days - inventory_position_units
    if cap_units <= 0:
        return 0
    if quantity_units > cap_units and quantity_units == round_up_to_pack(
        float(moq), pack_qty
    ):
        raise OrderConstraintError(
            f"the minimum orderable quantity {quantity_units} exceeds the "
            f"max-cover headroom {cap_units:.1f}",
            reason_code=CAP_CONFLICT_REASON,
        )
    if quantity_units > cap_units:
        # Shrink to the largest pack multiple inside the cap, but never below
        # the MOQ -- crossing it lands in the refusal above on the next check.
        shrunk = int(math.floor(cap_units / pack_qty) * pack_qty)
        if shrunk < moq or shrunk <= 0:
            raise OrderConstraintError(
                f"no pack multiple satisfies MOQ {moq} within the max-cover "
                f"headroom {cap_units:.1f}",
                reason_code=CAP_CONFLICT_REASON,
            )
        quantity_units = shrunk
    return quantity_units


__all__ = [
    "CAP_CONFLICT_REASON",
    "InventoryPosition",
    "OrderConstraintError",
    "apply_order_constraints",
    "fractional_horizon_rss",
    "fractional_horizon_sum",
    "inventory_position",
    "order_up_to_level",
    "protection_period_days",
    "reorder_point",
    "required_horizon_weeks",
    "round_up_to_pack",
    "SafetyStock",
    "safety_stock_units",
    "service_level_z",
]
