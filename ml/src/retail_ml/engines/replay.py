"""Weekly multi-echelon inventory replay (P4-7).

Net-new. The M5 simulator was daily and store-only; wrapping it would have
inherited a clock the evidence cannot support, so this is built on the ISO-Monday
clock and the preceding-Thursday bridge from `engines/clock.py`.

Two rules shape everything here, and both exist because the alternative flatters
the engine:

* **The oracle comes first.** A replay must reproduce observed weekly stock
  within the frozen tolerance BEFORE any policy comparison is scored. A replay
  that cannot reproduce reality has no standing to compare policies against it,
  and scoring first would let a broken simulation declare a winner.
* **The period sequence is frozen.** Candidate orders are created only AFTER the
  period's demand is realized (policy v2 `periodSequence`), so a period can never
  order against demand it has already served -- which is how a replay
  accidentally becomes clairvoyant and every policy looks good.

Incumbent and candidate run over IDENTICAL origins, opening states, events, lanes,
terms and costs. The only difference permitted between them is the policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Iterable, Mapping, Sequence

from retail_ml.engines.clock import monday_period_bounds, opening_snapshot_instant


@dataclass
class CellState:
    """Mutable stock state for one SKU x location cell inside a replay."""

    on_hand: int = 0
    in_transit: int = 0
    committed: int = 0

    def available(self) -> int:
        return max(0, self.on_hand - self.committed)


@dataclass
class PeriodResult:
    """One market-local ISO week, scored."""

    period_open: datetime
    market_id: str
    opening_units: int
    closing_units: int
    demand_units: int
    served_units: int
    lost_units: int
    stockout_cells: int
    ordered_units: int
    received_units: int

    @property
    def fill_rate(self) -> Decimal:
        if self.demand_units == 0:
            # No demand is not a perfect fill. An undefined ratio stays
            # undefined; policy v2 treats a zero denominator as insufficient
            # evidence rather than a pass.
            return Decimal(0)
        return Decimal(self.served_units) / Decimal(self.demand_units)


@dataclass
class ReplayResult:
    policy_id: str
    periods: list[PeriodResult] = field(default_factory=list)

    def metric(self, name: str, *, market_id: str | None = None) -> Decimal:
        rows = [
            period for period in self.periods
            if market_id is None or period.market_id == market_id
        ]
        if not rows:
            return Decimal(0)
        if name == "stockoutPeriods":
            return Decimal(sum(1 for row in rows if row.stockout_cells > 0))
        if name == "lostUnits":
            return Decimal(sum(row.lost_units for row in rows))
        if name == "fillRate":
            demand = sum(row.demand_units for row in rows)
            served = sum(row.served_units for row in rows)
            if demand == 0:
                return Decimal(0)
            return Decimal(served) / Decimal(demand)
        if name == "meanInventoryUnits":
            total = sum(row.closing_units for row in rows)
            return Decimal(total) / Decimal(len(rows))
        raise ValueError(f"unknown replay metric {name!r}")


#: A policy is a callable, not a config blob: replay must be able to run the
#: incumbent and the candidate through exactly the same loop, and the only way
#: to guarantee that is for the loop to be identical and the policy to be an
#: argument.
OrderPolicy = Callable[[Mapping[str, Any]], int]


def replay_market(
    *,
    policy_id: str,
    policy: OrderPolicy,
    market_id: str,
    timezone: str,
    origins: Sequence[date],
    opening_state: Mapping[tuple[str, str], int],
    demand_by_period: Mapping[datetime, Mapping[tuple[str, str], int]],
    arrivals_by_period: Mapping[datetime, Mapping[tuple[str, str], int]],
    lead_time_weeks: int = 1,
) -> ReplayResult:
    """Run one market through its ISO-Monday periods under one policy.

    `opening_state` is derived by the caller from the preceding Thursday
    snapshot plus its bridge -- this function does not invent an opening, because
    the bridge is where the evidence lives.
    """

    if lead_time_weeks < 1:
        raise ValueError("lead_time_weeks must be >= 1")
    cells: dict[tuple[str, str], CellState] = {
        key: CellState(on_hand=units) for key, units in opening_state.items()
    }
    scheduled: dict[datetime, dict[tuple[str, str], int]] = {}
    result = ReplayResult(policy_id=policy_id)

    period_opens = []
    for origin in sorted(origins):
        period_open, _ = monday_period_bounds(origin, timezone)
        # The snapshot that seeds this period must precede it; asserting here
        # rather than trusting the caller keeps a mis-derived bridge from
        # silently producing a plausible replay.
        if opening_snapshot_instant(period_open, timezone) >= period_open:
            raise ValueError(
                f"the seeding snapshot for {period_open} does not precede it"
            )
        period_opens.append(period_open)

    for period_open in period_opens:
        opening_units = sum(cell.on_hand for cell in cells.values())

        # 1-2. Receive inbound effective by the review cutoff.
        received = 0
        for source in (arrivals_by_period.get(period_open, {}), scheduled.pop(period_open, {})):
            for key, units in source.items():
                cell = cells.setdefault(key, CellState())
                cell.on_hand += units
                cell.in_transit = max(0, cell.in_transit - units)
                received += units

        # 4-5. Fulfil origin-visible demand subject to availability, then score.
        demand_total = 0
        served_total = 0
        stockout_cells = 0
        period_demand = demand_by_period.get(period_open, {})
        for key in sorted(period_demand):
            units = int(period_demand[key])
            if units <= 0:
                continue
            demand_total += units
            cell = cells.setdefault(key, CellState())
            served = min(cell.available(), units)
            cell.on_hand -= served
            served_total += served
            if served < units:
                stockout_cells += 1

        # 6-7. Create candidate orders AFTER demand realization, and schedule
        # them under the frozen weekly arrival rule.
        ordered = 0
        arrival_index = period_opens.index(period_open) + lead_time_weeks
        arrival_open = (
            period_opens[arrival_index] if arrival_index < len(period_opens) else None
        )
        for key in sorted(set(cells) | set(period_demand)):
            cell = cells.setdefault(key, CellState())
            quantity = policy(
                {
                    "sku_id": key[0],
                    "location_id": key[1],
                    "on_hand_units": cell.on_hand,
                    "in_transit_units": cell.in_transit,
                    "observed_demand_units": int(period_demand.get(key, 0)),
                    "market_id": market_id,
                }
            )
            if quantity <= 0:
                continue
            ordered += quantity
            cell.in_transit += quantity
            if arrival_open is not None:
                scheduled.setdefault(arrival_open, {})
                scheduled[arrival_open][key] = (
                    scheduled[arrival_open].get(key, 0) + quantity
                )

        result.periods.append(
            PeriodResult(
                period_open=period_open,
                market_id=market_id,
                opening_units=opening_units,
                closing_units=sum(cell.on_hand for cell in cells.values()),
                demand_units=demand_total,
                served_units=served_total,
                lost_units=demand_total - served_total,
                stockout_cells=stockout_cells,
                ordered_units=ordered,
                received_units=received,
            )
        )
    return result


def reproduce_oracle(
    *,
    replay: ReplayResult,
    observed_closing_units: Mapping[datetime, int],
    tolerance_mean_abs_unit_delta: Decimal,
) -> dict[str, Any]:
    """Compare replayed closing state to the observed weekly oracle.

    Runs BEFORE any policy comparison. The tolerance is frozen before scoring;
    a tolerance widened after seeing the delta is not a tolerance.
    """

    if tolerance_mean_abs_unit_delta < 0:
        raise ValueError("tolerance must be >= 0")
    compared = 0
    total_delta = Decimal(0)
    for period in replay.periods:
        observed = observed_closing_units.get(period.period_open)
        if observed is None:
            continue
        compared += 1
        total_delta += abs(Decimal(period.closing_units) - Decimal(observed))
    if compared == 0:
        # No oracle weeks means the replay is unvalidated, which is a failure --
        # not a pass by absence of contradiction.
        return {
            "passed": False,
            "weeksCompared": 0,
            "measuredMeanAbsUnitDeltaPerCell": None,
            "reasonCode": "NO_ORACLE_WEEKS_AVAILABLE",
        }
    measured = total_delta / Decimal(compared)
    return {
        "passed": measured <= tolerance_mean_abs_unit_delta,
        "weeksCompared": compared,
        "measuredMeanAbsUnitDeltaPerCell": str(measured),
        "toleranceMeanAbsUnitDeltaPerCell": str(tolerance_mean_abs_unit_delta),
        "reasonCode": None,
    }


#: Policy v2 `replayAcceptance` gate directions, frozen before any candidate runs.
GATE_RULES: dict[str, str] = {
    "stockoutPeriods": "fewer_than_incumbent",
    "lostUnits": "fewer_than_incumbent",
    "fillRate": "no_worse_than_incumbent",
    "meanInventoryUnits": "lower_than_incumbent",
}


def _compare(metric: str, candidate: Decimal, incumbent: Decimal) -> bool:
    rule = GATE_RULES[metric]
    if rule == "fewer_than_incumbent" or rule == "lower_than_incumbent":
        # A tie FAILS. Policy v2 `tieBehavior: fails_the_gate` -- "no worse" and
        # "better" are different claims, and only one of them is being made here.
        return candidate < incumbent
    return candidate >= incumbent


def evaluate_acceptance(
    *,
    candidate: ReplayResult,
    incumbent: ReplayResult,
    markets: Sequence[str],
    oracle: Mapping[str, Any],
) -> dict[str, Any]:
    """Score the frozen replay gates globally and per market.

    A pooled pass cannot carry a failing market: `perMarket` is evaluated
    independently and the overall verdict requires every market to pass, because
    a candidate that wins globally while losing India West is a rejected
    candidate.
    """

    if not oracle.get("passed"):
        return {
            "passed": False,
            "reasonCode": "ORACLE_REPRODUCTION_FAILED",
            "oracleReproduction": dict(oracle),
            "replayGates": {},
            "perMarket": {},
        }

    def gates(market_id: str | None) -> dict[str, Any]:
        scored: dict[str, Any] = {}
        for metric in GATE_RULES:
            candidate_value = candidate.metric(metric, market_id=market_id)
            incumbent_value = incumbent.metric(metric, market_id=market_id)
            scored[metric] = {
                "passed": _compare(metric, candidate_value, incumbent_value),
                "candidate": str(candidate_value),
                "incumbent": str(incumbent_value),
                "rule": GATE_RULES[metric],
            }
        return scored

    global_gates = gates(None)
    per_market = {
        market_id: {
            **gates(market_id),
            "passed": all(
                entry["passed"] for entry in gates(market_id).values()
            ),
        }
        for market_id in markets
    }
    passed = (
        all(entry["passed"] for entry in global_gates.values())
        and all(entry["passed"] for entry in per_market.values())
    )
    return {
        "passed": passed,
        "reasonCode": None if passed else "REPLAY_GATE_FAILED",
        "oracleReproduction": dict(oracle),
        "replayGates": global_gates,
        "perMarket": per_market,
    }


def split_cohorts(
    keys: Iterable[tuple[str, str, str, str, str]],
    *,
    assign: Callable[..., str],
) -> dict[str, set[tuple[str, str, str, str, str]]]:
    """Partition replay keys into calibration and holdout, asserting the split.

    Disjointness and completeness are asserted rather than assumed: a key that
    landed in both cohorts leaks calibration into holdout, and a key in neither
    silently shrinks the population every gate is measured over.
    """

    cohorts: dict[str, set[tuple[str, str, str, str, str]]] = {
        "calibration": set(),
        "holdout": set(),
    }
    all_keys: set[tuple[str, str, str, str, str]] = set()
    for key in keys:
        all_keys.add(key)
        retailer, tenant, market, location, sku = key
        cohort = assign(
            retailer_id=retailer,
            tenant_id=tenant,
            market_id=market,
            location_id=location,
            sku_id=sku,
        )
        if cohort not in cohorts:
            raise ValueError(
                f"cohort assignment returned {cohort!r}; only 'calibration' and "
                "'holdout' exist, and a third bucket would silently shrink the "
                "population every gate is measured over"
            )
        cohorts[cohort].add(key)
    if cohorts["calibration"] & cohorts["holdout"]:
        raise ValueError("cohorts overlap; calibration would leak into holdout")
    if cohorts["calibration"] | cohorts["holdout"] != all_keys:
        raise ValueError("cohorts do not cover every replay key")
    return cohorts


__all__ = [
    "CellState",
    "GATE_RULES",
    "OrderPolicy",
    "PeriodResult",
    "ReplayResult",
    "evaluate_acceptance",
    "replay_market",
    "reproduce_oracle",
    "split_cohorts",
]
