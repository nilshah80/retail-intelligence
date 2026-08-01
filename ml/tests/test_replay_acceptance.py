"""P4-7 replay and acceptance: the gates, and the two ways they can be cheated."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from retail_ml.engines.cohorts import assign_cohort
from retail_ml.engines.clock import monday_period_bounds
from retail_ml.engines.replay import (
    GATE_RULES,
    ReplayResult,
    evaluate_acceptance,
    replay_market,
    reproduce_oracle,
    split_cohorts,
)

TIMEZONE = "Asia/Kolkata"
MARKET = "india-west"
ORIGINS = [date(2026, 7, 6), date(2026, 7, 13), date(2026, 7, 20), date(2026, 7, 27)]
CELL = ("sku-1", "bandra")


def _period(origin: date) -> datetime:
    period_open, _ = monday_period_bounds(origin, TIMEZONE)
    return period_open


def _demand(units: int) -> dict:
    return {_period(origin): {CELL: units} for origin in ORIGINS}


def _run(policy, *, opening: int = 40, demand_units: int = 10, arrivals=None):
    return replay_market(
        policy_id="test",
        policy=policy,
        market_id=MARKET,
        timezone=TIMEZONE,
        origins=ORIGINS,
        opening_state={CELL: opening},
        demand_by_period=_demand(demand_units),
        arrivals_by_period=arrivals or {},
    )


def _order_to(level: int):
    return lambda row: max(
        0, level - int(row["on_hand_units"]) - int(row["in_transit_units"])
    )


# -- the loop ------------------------------------------------------------------

def test_every_period_is_a_market_local_iso_monday() -> None:
    result = _run(_order_to(0))
    assert len(result.periods) == len(ORIGINS)
    for period in result.periods:
        local = period.period_open.astimezone(ZoneInfo(TIMEZONE))
        assert local.weekday() == 0
        assert local.time() == time(0)


def test_demand_is_served_only_from_available_stock_and_shortfall_is_lost() -> None:
    """40 opening, 10/week, no replenishment: week 5 would starve. Over four
    weeks it serves exactly 40 and loses nothing."""

    result = _run(_order_to(0), opening=40, demand_units=10)
    assert sum(p.served_units for p in result.periods) == 40
    assert sum(p.lost_units for p in result.periods) == 0
    assert result.periods[-1].closing_units == 0

    starved = _run(_order_to(0), opening=15, demand_units=10)
    assert sum(p.lost_units for p in starved.periods) == 25
    assert sum(1 for p in starved.periods if p.stockout_cells > 0) == 3


def test_an_order_arrives_after_its_lead_time_never_within_its_own_period() -> None:
    """A replay whose orders arrive instantly is clairvoyant, and every policy
    looks good in it."""

    result = _run(_order_to(50), opening=10, demand_units=10)
    first, second = result.periods[0], result.periods[1]
    assert first.ordered_units > 0
    assert first.received_units == 0, "an order cannot arrive in the period that placed it"
    assert second.received_units == first.ordered_units


def test_stock_never_goes_negative() -> None:
    result = _run(_order_to(0), opening=5, demand_units=100)
    assert all(p.closing_units >= 0 for p in result.periods)


def test_fill_rate_with_no_demand_is_not_a_perfect_score() -> None:
    result = _run(_order_to(0), opening=10, demand_units=0)
    assert result.periods[0].fill_rate == Decimal(0)
    assert result.metric("fillRate") == Decimal(0)


# -- the oracle ------------------------------------------------------------------

def test_the_oracle_must_reproduce_before_anything_is_scored() -> None:
    result = _run(_order_to(0), opening=40, demand_units=10)
    observed = {p.period_open: p.closing_units for p in result.periods}
    verdict = reproduce_oracle(
        replay=result,
        observed_closing_units=observed,
        tolerance_mean_abs_unit_delta=Decimal("0.5"),
    )
    assert verdict["passed"] is True
    assert verdict["weeksCompared"] == len(ORIGINS)

    drifted = {key: value + 20 for key, value in observed.items()}
    failed = reproduce_oracle(
        replay=result,
        observed_closing_units=drifted,
        tolerance_mean_abs_unit_delta=Decimal("0.5"),
    )
    assert failed["passed"] is False


def test_no_oracle_weeks_is_a_failure_not_a_pass_by_absence() -> None:
    result = _run(_order_to(0))
    verdict = reproduce_oracle(
        replay=result,
        observed_closing_units={},
        tolerance_mean_abs_unit_delta=Decimal("1000"),
    )
    assert verdict["passed"] is False
    assert verdict["reasonCode"] == "NO_ORACLE_WEEKS_AVAILABLE"


def test_a_failing_oracle_blocks_the_gates_entirely() -> None:
    """A replay that cannot reproduce reality has no standing to compare
    policies against it, so acceptance refuses before scoring."""

    candidate = _run(_order_to(50), opening=10, demand_units=10)
    incumbent = _run(_order_to(20), opening=10, demand_units=10)
    verdict = evaluate_acceptance(
        candidate=candidate,
        incumbent=incumbent,
        markets=[MARKET],
        oracle={"passed": False, "reasonCode": "TOLERANCE_BREACHED"},
    )
    assert verdict["passed"] is False
    assert verdict["reasonCode"] == "ORACLE_REPRODUCTION_FAILED"
    assert verdict["replayGates"] == {}


# -- the gates --------------------------------------------------------------------

_PASSING_ORACLE = {"passed": True, "weeksCompared": 4}


def test_a_candidate_must_beat_the_incumbent_on_every_frozen_gate() -> None:
    """Service wins do not buy an inventory failure.

    The incumbent orders to 5 against demand of 10, so it starves and loses
    units. The candidate orders to 120 and serves everything -- and carries far
    more stock. Every service gate passes and the inventory gate fails, so the
    verdict fails: acceptance requires ALL four, which is what stops a candidate
    buying service with working capital.
    """

    candidate = _run(_order_to(120), opening=10, demand_units=10)
    incumbent = _run(_order_to(5), opening=10, demand_units=10)
    verdict = evaluate_acceptance(
        candidate=candidate, incumbent=incumbent,
        markets=[MARKET], oracle=_PASSING_ORACLE,
    )
    assert verdict["replayGates"]["lostUnits"]["passed"] is True
    assert verdict["replayGates"]["stockoutPeriods"]["passed"] is True
    assert verdict["replayGates"]["meanInventoryUnits"]["passed"] is False
    assert verdict["passed"] is False, (
        "winning on service while carrying more inventory is not acceptance"
    )


def test_a_tie_fails_the_gate() -> None:
    """Policy v2 tieBehavior: fails_the_gate. 'No worse' and 'better' are
    different claims and only one is being made."""

    identical = _run(_order_to(30), opening=20, demand_units=10)
    other = _run(_order_to(30), opening=20, demand_units=10)
    verdict = evaluate_acceptance(
        candidate=identical, incumbent=other,
        markets=[MARKET], oracle=_PASSING_ORACLE,
    )
    assert verdict["replayGates"]["lostUnits"]["passed"] is False
    assert verdict["replayGates"]["fillRate"]["passed"] is True, (
        "fill rate is 'no worse', so equality passes it"
    )
    assert verdict["passed"] is False


def test_a_pooled_pass_cannot_carry_a_failing_market() -> None:
    """The specific failure the per-market gates exist to catch."""

    strong = replay_market(
        policy_id="candidate", policy=_order_to(40), market_id="us-new-york",
        timezone="America/New_York", origins=ORIGINS,
        opening_state={CELL: 40},
        demand_by_period={
            _p: {CELL: 5} for _p in (
                monday_period_bounds(o, "America/New_York")[0] for o in ORIGINS
            )
        },
        arrivals_by_period={},
    )
    weak = replay_market(
        policy_id="candidate", policy=_order_to(0), market_id=MARKET,
        timezone=TIMEZONE, origins=ORIGINS,
        opening_state={CELL: 2},
        demand_by_period=_demand(10), arrivals_by_period={},
    )
    candidate = ReplayResult(policy_id="candidate")
    candidate.periods = strong.periods + weak.periods

    incumbent_strong = replay_market(
        policy_id="incumbent", policy=_order_to(20), market_id="us-new-york",
        timezone="America/New_York", origins=ORIGINS,
        opening_state={CELL: 40},
        demand_by_period={
            _p: {CELL: 5} for _p in (
                monday_period_bounds(o, "America/New_York")[0] for o in ORIGINS
            )
        },
        arrivals_by_period={},
    )
    incumbent_ok = replay_market(
        policy_id="incumbent", policy=_order_to(60), market_id=MARKET,
        timezone=TIMEZONE, origins=ORIGINS,
        opening_state={CELL: 60},
        demand_by_period=_demand(10), arrivals_by_period={},
    )
    incumbent = ReplayResult(policy_id="incumbent")
    incumbent.periods = incumbent_strong.periods + incumbent_ok.periods

    verdict = evaluate_acceptance(
        candidate=candidate, incumbent=incumbent,
        markets=["us-new-york", MARKET], oracle=_PASSING_ORACLE,
    )
    assert verdict["perMarket"][MARKET]["passed"] is False
    assert verdict["passed"] is False


def test_the_gate_rules_are_the_frozen_four() -> None:
    assert GATE_RULES == {
        "stockoutPeriods": "fewer_than_incumbent",
        "lostUnits": "fewer_than_incumbent",
        "fillRate": "no_worse_than_incumbent",
        "meanInventoryUnits": "lower_than_incumbent",
    }


# -- cohorts ------------------------------------------------------------------------

def test_cohorts_are_disjoint_and_collectively_complete() -> None:
    keys = [
        ("retailer-demo", "tenant-demo", MARKET, "bandra", f"sku-{index}")
        for index in range(500)
    ]
    cohorts = split_cohorts(keys, assign=assign_cohort)
    assert not (cohorts["calibration"] & cohorts["holdout"])
    assert cohorts["calibration"] | cohorts["holdout"] == set(keys)
    assert 0 < len(cohorts["calibration"]) < len(keys)


def test_an_overlapping_cohort_assignment_is_refused() -> None:
    """The leak this assertion exists to catch: one key in both cohorts means
    calibration state reaches the holdout through shared inventory."""

    keys = [("r", "t", "m", "l", "sku-1")]
    with pytest.raises(ValueError, match="only 'calibration' and 'holdout'"):
        split_cohorts(keys, assign=lambda **_: "neither")
