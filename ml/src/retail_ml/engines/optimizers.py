"""Transfer and constrained-allocation optimizers (P4-6, net-new).

Both are deterministic greedy optimizers with frozen objectives, constraints and
tie-breaks from inventory-policy/2.0.0. Greedy is a deliberate choice, not a
shortcut: a solver whose result can change with library version or thread count
cannot satisfy invariant 15, and the PoC's accepted scope is bounded.

Conservation is asserted, not assumed. `allocated + residual = pool` and
`no channel allocated twice` are properties the verifier recomputes, so the
optimizer computes them the same way and refuses its own output when they fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence


class ConservationError(RuntimeError):
    """An optimizer produced output that violates its own invariants."""


@dataclass(frozen=True)
class TransferCandidate:
    lane_id: str
    from_location_id: str
    to_location_id: str
    sku_id: str
    market_id: str
    currency_code: str
    units: int
    expected_benefit_minor: int
    transit_days: int


def recommend_transfers(
    candidates: Sequence[TransferCandidate],
    *,
    source_atp: Mapping[tuple[str, str], int],
    source_residual_cover_units: Mapping[tuple[str, str], int],
    target_headroom_units: Mapping[tuple[str, str], int],
) -> list[dict[str, Any]]:
    """Select transfers greedily under the frozen objective and tie-break.

    Objective: maximize expected benefit in ONE market-local currency per row.
    Constraints: the source keeps its residual cover, the target respects its
    max-cover headroom, and units never exceed source ATP. Tie-break (policy v2
    `transferOptimizer.deterministicTieBreak`): benefit desc, transit asc,
    from, to, sku -- so two equal candidates order identically on every run.
    """

    markets = {candidate.market_id for candidate in candidates}
    if len(markets) > 1:
        raise ValueError(
            f"transfer candidates cross markets {sorted(markets)}; optimize "
            "each market separately"
        )
    ordered = sorted(
        candidates,
        key=lambda c: (
            -c.expected_benefit_minor,
            c.transit_days,
            c.from_location_id,
            c.to_location_id,
            c.sku_id,
        ),
    )
    remaining_atp = dict(source_atp)
    remaining_headroom = dict(target_headroom_units)
    recommendations: list[dict[str, Any]] = []
    for candidate in ordered:
        if candidate.units <= 0 or candidate.expected_benefit_minor <= 0:
            continue
        source_key = (candidate.from_location_id, candidate.sku_id)
        target_key = (candidate.to_location_id, candidate.sku_id)
        atp = remaining_atp.get(source_key, 0)
        reserve = source_residual_cover_units.get(source_key, 0)
        headroom = remaining_headroom.get(target_key, 0)
        movable = min(candidate.units, max(0, atp - reserve), headroom)
        if movable <= 0:
            continue
        remaining_atp[source_key] = atp - movable
        remaining_headroom[target_key] = headroom - movable
        recommendations.append(
            {
                "lane_id": candidate.lane_id,
                "from_location_id": candidate.from_location_id,
                "to_location_id": candidate.to_location_id,
                "sku_id": candidate.sku_id,
                "market_id": candidate.market_id,
                "currency_code": candidate.currency_code,
                "units": movable,
                "expected_benefit_minor": candidate.expected_benefit_minor
                * movable
                // max(1, candidate.units),
                "transit_days": candidate.transit_days,
            }
        )
    for (location, sku), atp in remaining_atp.items():
        if atp < 0:
            raise ConservationError(
                f"source {location}/{sku} went negative: {atp}"
            )
    return recommendations


def allocate_channels(
    *,
    node_atp_units: int,
    demands: Sequence[Mapping[str, Any]],
    minimum_share: Decimal = Decimal("0"),
) -> dict[str, Any]:
    """Allocate one node ATP pool across channel rows (P4-D16).

    Priority: service class asc (1 first), then value weight desc, then the
    frozen tie-break (market, location, channel, sku). A minimum-share guarantee
    reserves a floor for every demand row before priority spends the rest.

    Conservation is asserted on the way out: allocated + residual = pool, no
    channel allocated twice, and no demand row disappears -- a row that gets
    nothing is returned with zero, because a vanished channel is exactly the
    silent aggregation P4-D16 forbids.
    """

    if node_atp_units < 0:
        raise ValueError("node ATP must be >= 0")
    keys = [
        (
            str(row["market_id"]),
            str(row["location_id"]),
            str(row["channel_id"]),
            str(row["sku_id"]),
        )
        for row in demands
    ]
    if len(set(keys)) != len(keys):
        raise ValueError("a channel demand row appears twice in one pool")

    ordered = sorted(
        range(len(demands)),
        key=lambda index: (
            int(demands[index]["service_class_rank"]),
            -int(demands[index]["value_weight_minor"]),
            keys[index],
        ),
    )
    allocations = [0] * len(demands)
    remaining = node_atp_units

    if minimum_share > 0:
        for index in ordered:
            requested = int(demands[index]["requested_units"])
            floor_units = int(Decimal(requested) * minimum_share)
            granted = min(floor_units, remaining)
            allocations[index] = granted
            remaining -= granted

    for index in ordered:
        requested = int(demands[index]["requested_units"])
        top_up = min(requested - allocations[index], remaining)
        if top_up > 0:
            allocations[index] += top_up
            remaining -= top_up

    allocated_total = sum(allocations)
    if allocated_total + remaining != node_atp_units:
        raise ConservationError(
            f"allocated {allocated_total} + residual {remaining} != pool "
            f"{node_atp_units}"
        )
    for index, allocation in enumerate(allocations):
        if allocation > int(demands[index]["requested_units"]):
            raise ConservationError(
                f"row {keys[index]} allocated above its own request"
            )
    return {
        "allocations": [
            {
                "market_id": keys[index][0],
                "location_id": keys[index][1],
                "channel_id": keys[index][2],
                "sku_id": keys[index][3],
                "requested_units": int(demands[index]["requested_units"]),
                "allocated_units": allocations[index],
                "shortfall_units": int(demands[index]["requested_units"])
                - allocations[index],
            }
            for index in range(len(demands))
        ],
        "residual_units": remaining,
        "pool_units": node_atp_units,
    }


__all__ = [
    "ConservationError",
    "TransferCandidate",
    "allocate_channels",
    "recommend_transfers",
]
