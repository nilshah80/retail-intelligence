"""Lane and supply-term resolution (§3.6, §3.7), fail-closed.

Net-new: no M5 source exists. Resolution never guesses -- a demand with no active
lane and a term lookup with no unambiguous match are reason-coded refusals, not
fallbacks, because a wrong route or a wrong lead time becomes a wrong order with
nobody accountable for it.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping, Sequence


class ResolutionError(RuntimeError):
    def __init__(self, message: str, *, reason_code: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def active_lanes(
    lanes: Sequence[Mapping[str, Any]],
    *,
    demand_location_id: str,
    channel_id: str | None,
    on_date: date,
    lane_type: str = "replenishment",
) -> list[Mapping[str, Any]]:
    """Every active lane serving this demand, in priority-rank order.

    Exact channel first, then the null-channel default. A NULL channel is a
    declared default, never a wildcard that competes with an exact row.

    The rank validation lives here rather than in `resolve_lane` because a caller
    reading the ALTERNATES needs the same guarantee the winner gets: ranks that
    are not unique and contiguous from 1 mean the declared network disagrees with
    itself, and "second choice" is then undefined regardless of which lane is
    being asked for.
    """

    def active(lane: Mapping[str, Any]) -> bool:
        if lane["lane_type"] != lane_type:
            return False
        if lane["demand_location_id"] != demand_location_id:
            return False
        effective_from = lane["effective_from"]
        effective_to = lane.get("effective_to")
        if on_date < effective_from:
            return False
        return effective_to is None or on_date <= effective_to

    exact = [
        lane
        for lane in lanes
        if active(lane) and lane.get("channel_id") == channel_id
    ] if channel_id is not None else []
    candidates = exact or [
        lane for lane in lanes if active(lane) and lane.get("channel_id") is None
    ]
    if not candidates:
        raise ResolutionError(
            f"no active {lane_type} lane for {demand_location_id} "
            f"(channel={channel_id!r}) on {on_date}",
            reason_code="NO_ACTIVE_SERVICE_LANE",
        )
    ranks = sorted(int(lane["priority_rank"]) for lane in candidates)
    if len(set(ranks)) != len(ranks) or ranks != list(range(1, len(ranks) + 1)):
        raise ResolutionError(
            f"lane ranks for {demand_location_id} are not unique and contiguous "
            f"from 1: {ranks}",
            reason_code="LANE_RANKS_INVALID",
        )
    return sorted(candidates, key=lambda lane: int(lane["priority_rank"]))


def resolve_lane(
    lanes: Sequence[Mapping[str, Any]],
    *,
    demand_location_id: str,
    channel_id: str | None,
    on_date: date,
    lane_type: str = "replenishment",
) -> Mapping[str, Any]:
    """Resolve the rank-1 active lane."""

    winner = active_lanes(
        lanes,
        demand_location_id=demand_location_id,
        channel_id=channel_id,
        on_date=on_date,
        lane_type=lane_type,
    )[0]
    if winner["supply_location_id"] == demand_location_id:
        raise ResolutionError(
            f"lane {winner.get('lane_id')} is a self-loop",
            reason_code="LANE_SELF_LOOP",
        )
    return winner


#: §3.7 precedence. Exact origin always; SKU beats department beats category.
_PRECEDENCE = (("sku",), ("dept",), ("category",))


def resolve_supply_term(
    terms: Sequence[Mapping[str, Any]],
    *,
    destination_location_id: str,
    origin_kind: str,
    origin_id: str,
    sku_id: str,
    dept_id: str,
    category: str,
    on_date: date,
) -> Mapping[str, Any]:
    """Resolve one term under sku > dept > category precedence.

    The origin is part of the KEY: an external supplier term can never satisfy an
    internal-location lookup, and a null origin is not a legal term at all --
    the v1 rows' null origin is exactly the wildcard this resolver exists to
    refuse.
    """

    if not origin_id:
        raise ResolutionError(
            "an empty origin_id is not an origin that matches everything",
            reason_code="SUPPLY_TERM_ORIGIN_REQUIRED",
        )
    scope_ids = {"sku": sku_id, "dept": dept_id, "category": category}

    def matches(term: Mapping[str, Any], scope_type: str) -> bool:
        if term["destination_location_id"] != destination_location_id:
            return False
        if term["origin_kind"] != origin_kind or term["origin_id"] != origin_id:
            return False
        if term["merch_scope_type"] != scope_type:
            return False
        if term["merch_scope_id"] != scope_ids[scope_type]:
            return False
        effective_from = term["effective_from"]
        effective_to = term.get("effective_to")
        if on_date < effective_from:
            return False
        return effective_to is None or on_date <= effective_to

    for (scope_type,) in _PRECEDENCE:
        candidates = [term for term in terms if matches(term, scope_type)]
        if len(candidates) > 1:
            # Prefer the most recently effective; a genuine tie is ambiguity and
            # ambiguity fails closed rather than picking by list order.
            candidates.sort(key=lambda term: term["effective_from"], reverse=True)
            if candidates[0]["effective_from"] == candidates[1]["effective_from"]:
                raise ResolutionError(
                    f"{len(candidates)} equal-precedence {scope_type} terms for "
                    f"{destination_location_id} from {origin_kind}:{origin_id}",
                    reason_code="SUPPLY_TERM_AMBIGUOUS",
                )
        if candidates:
            return candidates[0]
    raise ResolutionError(
        f"no supply term for {destination_location_id} from "
        f"{origin_kind}:{origin_id} at any precedence level",
        reason_code="SUPPLY_TERM_ABSENT",
    )


__all__ = [
    "ResolutionError",
    "active_lanes",
    "resolve_lane",
    "resolve_supply_term",
]
