"""Drive the P4-7 weekly replay over real canonical history.

The engine replays one market against one policy. This loads what it needs from
the curated publication, runs the candidate against a named incumbent, reproduces
the oracle, scores acceptance per cohort and per market, and emits the
`inventory_replay_metrics` artifact.

Three things are frozen before any number is computed, and the order matters:

* the incumbent policy is NAMED, not inferred. An incumbent derived from observed
  outcomes is a second candidate wearing a baseline's label, and every gate would
  then be comparing the candidate to itself;
* the oracle tolerance is fixed here and recorded as frozen. A tolerance widened
  after seeing the delta is not a tolerance;
* cohorts are assigned by `assign_cohort`'s stable hash, so the 5% calibration
  split does not move between runs and cannot be chosen after the fact.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Final, Mapping, Sequence

import pandas as pd

from retail_ml.engines.clock import monday_period_bounds
from retail_ml.engines.cohorts import assign_cohort
from retail_ml.engines.replay import (
    ReplayResult,
    evaluate_acceptance,
    replay_market,
    reproduce_oracle,
    split_cohorts,
)
from retail_ml.inventory_publish.run_artifacts import ARTIFACT_COLUMNS
from retail_ml.inventory_run.load import connect

#: Frozen BEFORE scoring, and expressed PER CELL because that is the unit
#: `reproduce_oracle` names in `measuredMeanAbsUnitDeltaPerCell`.
#:
#: The engine compares one value per period against `PeriodResult.closing_units`,
#: which is the market TOTAL across every cell. So the caller must scale: a
#: tolerance of 0.5 units per cell over N cells is a tolerance of 0.5*N on the
#: total. Passing 0.5 against a market total, which this driver did first, asserts
#: that 1,238 cells must jointly reconcile to within half a unit -- and reported a
#: 4,700-unit total gap as "4,700 per cell" instead of 3.8.
#:
#: P4-D13 forbids widening a tolerance after seeing the delta, so this value has
#: not moved. Only the grain it is applied at is corrected.
ORACLE_TOLERANCE_PER_CELL: Final[Decimal] = Decimal("0.5")

#: The named baseline. A fixed cover target is what the network was doing before
#: any forecast-driven policy existed, and it is the honest thing to beat.
INCUMBENT_POLICY_ID: Final[str] = "incumbent/fixed-cover-21d/v1"
INCUMBENT_COVER_DAYS: Final[int] = 21

CANDIDATE_POLICY_ID: Final[str] = "candidate/forecast-reorder-point/v2"

RETAILER_ID: Final[str] = "retailer-demo"
TENANT_ID: Final[str] = "tenant-demo"


class ReplayDriverError(RuntimeError):
    """Canonical history cannot support a replay at this window."""


@dataclass(frozen=True)
class MarketHistory:
    """One market's replayable history, already bucketed to ISO Mondays."""

    market_id: str
    timezone: str
    origins: list[date]
    opening_state: dict[tuple[str, str], int]
    demand_by_period: dict[datetime, dict[tuple[str, str], int]]
    arrivals_by_period: dict[datetime, dict[tuple[str, str], int]]
    observed_closing_units: dict[datetime, int]
    cells: list[tuple[str, str]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReplayDriverError(message)


def load_market_history(
    curated_root: str | Path,
    *,
    market_id: str,
    timezone: str,
    as_of: date,
    weeks: int,
) -> MarketHistory:
    """Bucket demand, arrivals and observed closing stock onto ISO Mondays.

    The window ends at the Monday BEFORE `as_of`'s own period, so the last
    replayed week is complete. Including a partial week would make its fill rate
    and closing stock a function of when the run happened.
    """

    period_open, _ = monday_period_bounds(as_of, timezone)
    last_open = period_open - timedelta(days=7)
    origins = [
        (last_open - timedelta(days=7 * offset)).date()
        for offset in reversed(range(weeks))
    ]
    _require(weeks >= 2, "a replay needs at least two periods to compare anything")
    window_start = origins[0]
    window_end = origins[-1] + timedelta(days=6)

    connection = connect(curated_root)
    try:
        # Store-channel demand only. An online order recorded against a store id
        # is not demand the store's own stock served -- policy v2's
        # `directDcFulfillmentRequires` makes DC fulfilment a declared lane, and
        # the numbers say so plainly: over 52 weeks india-west stores sold
        # 1,365,486 store-channel units against 43,932 opening plus 1,395,522
        # observed arrivals, while including the 369,203 online units pushed
        # demand 275,419 above everything the stores could possibly have had. The
        # replay then drained to zero every week and the oracle could never
        # reproduce an observed closing balance that stays near 44,000.
        demand_rows = connection.execute(
            """
            SELECT sales.store_id, sales.sku_id, sales.date, SUM(sales.units) AS units
            FROM sales
            JOIN locations ON locations.location_id = sales.store_id
            JOIN channels ON channels.channel_id = sales.channel_id
            WHERE locations.market_id = ?
              AND channels.type = 'store'
              AND sales.date BETWEEN ? AND ?
              AND sales.known_as_of <= ?
            GROUP BY 1, 2, 3
            """,
            [market_id, window_start, window_end, window_end],
        ).fetchall()
        # Kept explicit rather than folded into the aggregate above: the replay
        # buckets by market-local ISO week in Python, so daily rows are the grain
        # this needs and a SQL-side weekly bucket would use UTC boundaries.
        arrival_rows = connection.execute(
            """
            SELECT transfers.to_location_id, transfers.sku_id,
                   CAST(transfers.status_effective_at AS DATE) AS arrived_on,
                   SUM(transfers.qty) AS units
            FROM inventory_transfer_events AS transfers
            JOIN locations ON locations.location_id = transfers.to_location_id
            WHERE locations.market_id = ?
              AND transfers.status = 'received'
              AND CAST(transfers.status_effective_at AS DATE) BETWEEN ? AND ?
              AND transfers.known_as_of <= ?
            GROUP BY 1, 2, 3
            """,
            [market_id, window_start, window_end, window_end],
        ).fetchall()
        opening_rows = connection.execute(
            """
            SELECT DISTINCT ON (stock.location_id, stock.sku_id)
                stock.location_id, stock.sku_id, stock.on_hand_units
            FROM stock_snapshots AS stock
            JOIN locations ON locations.location_id = stock.location_id
            WHERE locations.market_id = ?
              AND locations.type = 'store'
              AND stock.snapshot_date <= ?
              AND stock.known_as_of <= ?
            ORDER BY stock.location_id, stock.sku_id, stock.snapshot_date DESC
            """,
            [market_id, window_start, window_start],
        ).fetchall()
        # The oracle: what the source says was actually on hand at each period
        # close. Compared against, never used to drive, the replay.
        observed_rows = connection.execute(
            """
            SELECT stock.snapshot_date, SUM(stock.on_hand_units) AS units
            FROM stock_snapshots AS stock
            JOIN locations ON locations.location_id = stock.location_id
            WHERE locations.market_id = ?
              AND locations.type = 'store'
              AND stock.snapshot_date BETWEEN ? AND ?
              AND stock.known_as_of <= ?
            GROUP BY 1
            """,
            [market_id, window_start, window_end, window_end],
        ).fetchall()
    finally:
        connection.close()

    _require(
        bool(opening_rows),
        f"{market_id}: no store-grain opening stock at {window_start}; the replay "
        "would start from a state nothing observed",
    )

    def period_for(day: date) -> datetime:
        return monday_period_bounds(day, timezone)[0]

    demand: dict[datetime, dict[tuple[str, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for store, sku, day, units in demand_rows:
        demand[period_for(day)][(str(sku), str(store))] += int(units)
    arrivals: dict[datetime, dict[tuple[str, str], int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for store, sku, day, units in arrival_rows:
        arrivals[period_for(day)][(str(sku), str(store))] += int(units)

    # Closing stock per period is the snapshot on the LAST day of that period, so
    # it is comparable to the replay's own closing state. Averaging the week would
    # compare a mean to an instant.
    closing_by_period: dict[datetime, dict[date, int]] = defaultdict(dict)
    for day, units in observed_rows:
        day_value = day if isinstance(day, date) else pd.Timestamp(day).date()
        closing_by_period[period_for(day_value)][day_value] = int(units)
    observed: dict[datetime, int] = {}
    for period, by_day in closing_by_period.items():
        observed[period] = by_day[max(by_day)]

    opening = {
        (str(sku), str(store)): int(units)
        for store, sku, units in opening_rows
    }
    return MarketHistory(
        market_id=market_id,
        timezone=timezone,
        origins=origins,
        opening_state=opening,
        demand_by_period={
            period: dict(cells) for period, cells in demand.items()
        },
        arrivals_by_period={
            period: dict(cells) for period, cells in arrivals.items()
        },
        observed_closing_units=observed,
        cells=sorted(opening),
    )


def incumbent_policy(
    *, trailing: Mapping[tuple[str, str], Decimal]
) -> Callable[[Mapping[str, Any]], int]:
    """Order up to a fixed cover target. The named baseline, not a derived one."""

    def policy(row: Mapping[str, Any]) -> int:
        key = (str(row["sku_id"]), str(row["location_id"]))
        target = int(trailing.get(key, Decimal(0)) * INCUMBENT_COVER_DAYS)
        position = int(row["on_hand_units"]) + int(row["in_transit_units"])
        return max(0, target - position)

    return policy


def candidate_policy(
    *,
    reorder_points: Mapping[tuple[str, str], Decimal],
    order_up_to: Mapping[tuple[str, str], Decimal],
) -> Callable[[Mapping[str, Any]], int]:
    """Order to the published order-up-to level, but only below the reorder point.

    Reads the SAME levels the bundle publishes. A replay against levels computed
    differently from the served ones would score a policy nobody is running.

    A cell with no published level orders nothing rather than falling back to a
    cover heuristic: the withheld-interval cells are exactly the ones a fallback
    would quietly re-include, and the replay would then credit the candidate for
    decisions the served bundle refuses to make.
    """

    def policy(row: Mapping[str, Any]) -> int:
        key = (str(row["sku_id"]), str(row["location_id"]))
        point = reorder_points.get(key)
        level = order_up_to.get(key)
        if point is None or level is None:
            return 0
        position = int(row["on_hand_units"]) + int(row["in_transit_units"])
        if Decimal(position) > point:
            return 0
        return max(0, int(level) - position)

    return policy


def run_replay(
    histories: Sequence[MarketHistory],
    *,
    trailing_by_market: Mapping[str, Mapping[tuple[str, str], Decimal]],
    reorder_points: Mapping[str, Mapping[tuple[str, str], Decimal]],
    order_up_to: Mapping[str, Mapping[tuple[str, str], Decimal]],
) -> dict[str, Any]:
    """Replay candidate and incumbent across markets and cohorts, then score.

    Cohorts are replayed as separate passes over the same history rather than as a
    post-hoc filter on one pass, because inventory is shared state: a calibration
    cell and a holdout cell drawing from the same node would leak the calibration
    policy's decisions into the holdout's availability.
    """

    _require(bool(histories), "no market history to replay")
    all_keys = [
        (RETAILER_ID, TENANT_ID, history.market_id, location, sku)
        for history in histories
        for sku, location in history.cells
    ]
    cohorts = split_cohorts(all_keys, assign=assign_cohort)
    cohort_of = {
        (market, location, sku): name
        for name, keys in cohorts.items()
        for _, _, market, location, sku in keys
    }

    metric_rows: list[dict[str, Any]] = []
    per_cohort: dict[str, dict[str, Any]] = {}
    oracle_records: dict[str, dict[str, Any]] = {}

    for cohort in ("calibration", "holdout"):
        candidate = ReplayResult(policy_id=CANDIDATE_POLICY_ID)
        incumbent = ReplayResult(policy_id=INCUMBENT_POLICY_ID)
        markets: list[str] = []
        for history in histories:
            cells = [
                (sku, location)
                for sku, location in history.cells
                if cohort_of.get((history.market_id, location, sku)) == cohort
            ]
            if not cells:
                continue
            markets.append(history.market_id)
            scoped = _scope(history, cells)
            candidate_run = replay_market(
                policy_id=CANDIDATE_POLICY_ID,
                policy=candidate_policy(
                    reorder_points=reorder_points.get(history.market_id, {}),
                    order_up_to=order_up_to.get(history.market_id, {}),
                ),
                market_id=history.market_id,
                timezone=history.timezone,
                origins=history.origins,
                opening_state=scoped.opening_state,
                demand_by_period=scoped.demand_by_period,
                arrivals_by_period=scoped.arrivals_by_period,
            )
            incumbent_run = replay_market(
                policy_id=INCUMBENT_POLICY_ID,
                policy=incumbent_policy(
                    trailing=trailing_by_market.get(history.market_id, {})
                ),
                market_id=history.market_id,
                timezone=history.timezone,
                origins=history.origins,
                opening_state=scoped.opening_state,
                demand_by_period=scoped.demand_by_period,
                arrivals_by_period=scoped.arrivals_by_period,
            )
            candidate.periods.extend(candidate_run.periods)
            incumbent.periods.extend(incumbent_run.periods)

        _require(
            bool(markets),
            f"cohort {cohort} has no cells in any market; a cohort nobody "
            "replayed proves nothing about the split",
        )
        # The oracle runs on the FULL market state, not the cohort subset: the
        # source's observed closing stock covers every cell, so a cohort-scoped
        # replay cannot be expected to reproduce it. Reproduction is therefore
        # established once per market on the whole population and gates both
        # cohorts, which is what makes it a check on the mechanism rather than on
        # the split.
        oracle = _market_oracle(histories)
        oracle_records[cohort] = oracle
        verdict = evaluate_acceptance(
            candidate=candidate,
            incumbent=incumbent,
            markets=sorted(set(markets)),
            oracle=oracle,
        )
        per_cohort[cohort] = verdict
        for market_id, gates in verdict["perMarket"].items():
            for metric, scored in gates.items():
                if metric == "passed":
                    continue
                metric_rows.append(
                    {
                        "market_id": market_id,
                        "metric": metric,
                        "cohort": cohort,
                        "candidate_value": str(scored["candidate"]),
                        "incumbent_value": str(scored["incumbent"]),
                        "passed": bool(scored["passed"]),
                    }
                )

    frame = pd.DataFrame(
        metric_rows, columns=list(ARTIFACT_COLUMNS["inventory_replay_metrics"])
    )
    passed = all(verdict["passed"] for verdict in per_cohort.values())
    return {
        "metrics": frame,
        "passed": passed,
        "replay": {
            "incumbentPolicyId": INCUMBENT_POLICY_ID,
            "candidatePolicyId": CANDIDATE_POLICY_ID,
            "periodsPerMarket": len(histories[0].origins),
            "cohortSplit": {
                name: len(keys) for name, keys in sorted(cohorts.items())
            },
            "oracle": oracle_records["holdout"],
            "oracleTolerance": {
                "frozenBeforeScoring": True,
                "meanAbsUnitDeltaPerCell": str(ORACLE_TOLERANCE_PER_CELL),
            },
            "perCohort": {
                name: {
                    "passed": verdict["passed"],
                    "reasonCode": verdict["reasonCode"],
                }
                for name, verdict in sorted(per_cohort.items())
            },
        },
    }


#: The oracle's policy: order nothing. Not a placeholder -- see `_market_oracle`.
def _no_order_policy(_row: Mapping[str, Any]) -> int:
    return 0


def _market_oracle(histories: Sequence[MarketHistory]) -> dict[str, Any]:
    """Reproduce observed closing stock across every market's full population.

    The oracle validates the replay MECHANISM, which is why it orders nothing.
    Observed arrivals are already the ground truth of what the real network
    ordered, so letting a policy generate orders on top of them counts the same
    inbound units twice -- and worse, it turns a mechanism check into a check of
    whether the candidate policy happens to match whatever the source simulator
    ran. It never will, so the oracle could never pass and P4-D13's oracle-first
    rule would block every run forever.

    With no ordering, the replay reduces to the accounting identity the source
    data must satisfy on its own: closing = opening + observed arrivals - served
    demand - shrink. If that does not reproduce, the mechanism or the input scope
    is wrong, which is exactly the finding the oracle exists to surface.

    Every market must reproduce independently. A pooled tolerance would let a
    market that reconstructs badly hide behind one that reconstructs well, and the
    point is that the mechanism works where it will be used.
    """

    worst: dict[str, Any] | None = None
    per_market: dict[str, Any] = {}
    for history in histories:
        run = replay_market(
            policy_id="oracle/no-order-mechanism-check",
            policy=_no_order_policy,
            market_id=history.market_id,
            timezone=history.timezone,
            origins=history.origins,
            opening_state=history.opening_state,
            demand_by_period=history.demand_by_period,
            arrivals_by_period=history.arrivals_by_period,
        )
        # Scale the per-cell tolerance to the total grain the engine compares at.
        cells = max(1, len(history.cells))
        verdict = reproduce_oracle(
            replay=run,
            observed_closing_units=history.observed_closing_units,
            tolerance_mean_abs_unit_delta=ORACLE_TOLERANCE_PER_CELL * cells,
        )
        measured = verdict.get("measuredMeanAbsUnitDeltaPerCell")
        verdict = {
            **verdict,
            "cellsCompared": cells,
            # Both grains reported, so a reader never has to work out which the
            # number is in. The engine's key is the total; this is per cell.
            "measuredMeanAbsUnitDeltaTotal": measured,
            "measuredMeanAbsUnitDeltaPerCell": (
                str(Decimal(measured) / cells) if measured is not None else None
            ),
            "tolerancePerCell": str(ORACLE_TOLERANCE_PER_CELL),
        }
        per_market[history.market_id] = verdict
        if not verdict["passed"] and worst is None:
            worst = verdict
    if worst is not None:
        return {**worst, "perMarket": per_market}
    return {
        "passed": True,
        "weeksCompared": min(
            int(verdict.get("weeksCompared", 0)) for verdict in per_market.values()
        ),
        "perMarket": per_market,
    }


def _scope(history: MarketHistory, cells: Sequence[tuple[str, str]]) -> MarketHistory:
    """Restrict a history to one cohort's cells."""

    wanted = set(cells)
    return MarketHistory(
        market_id=history.market_id,
        timezone=history.timezone,
        origins=history.origins,
        opening_state={
            key: units
            for key, units in history.opening_state.items()
            if key in wanted
        },
        demand_by_period={
            period: {
                key: units for key, units in by_cell.items() if key in wanted
            }
            for period, by_cell in history.demand_by_period.items()
        },
        arrivals_by_period={
            period: {
                key: units for key, units in by_cell.items() if key in wanted
            }
            for period, by_cell in history.arrivals_by_period.items()
        },
        observed_closing_units=dict(history.observed_closing_units),
        cells=sorted(wanted),
    )


__all__ = [
    "CANDIDATE_POLICY_ID",
    "INCUMBENT_COVER_DAYS",
    "INCUMBENT_POLICY_ID",
    "ORACLE_TOLERANCE_PER_CELL",
    "MarketHistory",
    "ReplayDriverError",
    "candidate_policy",
    "incumbent_policy",
    "load_market_history",
    "run_replay",
]
