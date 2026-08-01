"""P4-5 engine foundation: the plan's minimum unit/golden tests.

Each test pins a rule that inventory-policy/2.0.0 froze. When one of these
fails after an edit, the edit changed a contract, not a detail.
"""

from __future__ import annotations

from datetime import date, time, timezone

import pytest

from retail_ml.engines import (
    InventoryPosition,
    IntervalUnavailable,
    OrderConstraintError,
    PartialConsumerLedger,
    ResolutionError,
    apply_order_constraints,
    assign_cohort,
    classify_abc,
    monday_period_bounds,
    opening_snapshot_instant,
    order_up_to_level,
    reorder_point,
    require_interval_horizon,
    resolve_lane,
    resolve_supply_term,
    safety_stock_units,
    service_level_z,
)
from retail_ml.engines.primitives import required_horizon_weeks


# -- position and ATP ---------------------------------------------------------

def test_atp_buckets_are_disjoint_and_never_negative() -> None:
    position = InventoryPosition(
        on_hand_units=100, committed_units=30, reserved_units=10,
        damaged_units=5, on_order_units=40, in_transit_units=12,
    )
    assert position.atp_units == 55
    assert position.position_units == 55 + 40 + 12
    starved = InventoryPosition(
        on_hand_units=10, committed_units=30, reserved_units=0,
        damaged_units=0, on_order_units=0, in_transit_units=0,
    )
    assert starved.atp_units == 0, "ATP floors at zero; it is not a debt"


def test_negative_inventory_is_refused_not_computed_on() -> None:
    """Upstream emits it as a critical quality violation; an engine computing on
    it would launder the defect into a recommendation."""

    with pytest.raises(ValueError, match="on_hand_units"):
        InventoryPosition(
            on_hand_units=-1, committed_units=0, reserved_units=0,
            damaged_units=0, on_order_units=0, in_transit_units=0,
        )


# -- service level and safety stock -------------------------------------------

def test_service_level_z_accepts_policy_decimal_strings() -> None:
    assert service_level_z("0.96") == pytest.approx(1.7506860712521692)
    assert service_level_z("0.90") == pytest.approx(1.2815515655446004)
    for invalid in ("0.4", "0.999"):
        with pytest.raises(ValueError):
            service_level_z(invalid)


def test_safety_stock_scales_with_service_class() -> None:
    spreads = (4.0, 4.0, 4.0, 4.0)
    a_class = safety_stock_units(
        weekly_spreads=spreads, protection_days=14, service_level="0.96"
    )
    c_class = safety_stock_units(
        weekly_spreads=spreads, protection_days=14, service_level="0.80"
    )
    assert a_class > c_class > 0


def test_an_inverted_quantile_pair_is_refused_not_clamped() -> None:
    with pytest.raises(ValueError, match="negative"):
        safety_stock_units(
            weekly_spreads=(2.0, -0.5), protection_days=14, service_level="0.9"
        )


def test_fractional_protection_rounds_up_never_truncates() -> None:
    """5-day lead + 7-day review = 12 days = h2, and h2 is within the h4 gate.
    Truncation would read 12/7 -> h1 and under-protect every such series."""

    assert required_horizon_weeks(12) == 2
    assert required_horizon_weeks(14) == 2
    assert required_horizon_weeks(15) == 3
    assert required_horizon_weeks(1) == 1


# -- reorder and constraints ---------------------------------------------------

def test_reorder_point_and_order_up_to_compose() -> None:
    p50 = (10.0, 10.0, 10.0, 10.0)
    point = reorder_point(weekly_p50=p50, protection_days=14, safety_stock=6.0)
    assert point == pytest.approx(26.0)
    level = order_up_to_level(
        reorder_point_units=point, weekly_p50=p50, review_period_days=7
    )
    assert level == pytest.approx(36.0)


def test_moq_and_pack_round_up_within_the_cover_cap() -> None:
    quantity = apply_order_constraints(
        13.0, moq=12, pack_qty=6, inventory_position_units=10,
        avg_daily_demand=5.0, max_cover_days=30,
    )
    assert quantity == 18, "13 -> pack multiple above MOQ, never rounded down"


def test_a_moq_that_breaches_max_cover_is_refused_with_the_frozen_reason() -> None:
    """Policy v2 capConflictBehavior: refuse, never silently violate a cap."""

    with pytest.raises(OrderConstraintError) as caught:
        apply_order_constraints(
            5.0, moq=48, pack_qty=6, inventory_position_units=100,
            avg_daily_demand=4.0, max_cover_days=30,
        )
    assert caught.value.reason_code == "MOQ_EXCEEDS_MAX_COVER"


def test_zero_and_negative_demand_produce_no_order() -> None:
    assert apply_order_constraints(
        0.0, moq=12, pack_qty=6, inventory_position_units=0,
        avg_daily_demand=5.0, max_cover_days=30,
    ) == 0
    assert apply_order_constraints(
        20.0, moq=12, pack_qty=6, inventory_position_units=0,
        avg_daily_demand=-1.0, max_cover_days=30,
    ) == 0


# -- interval guards (P4-D17) --------------------------------------------------

def test_current_pin_lead_terms_resolve_h2_and_pass_the_gate() -> None:
    require_interval_horizon(
        consumer="reorder", required_horizon_weeks=required_horizon_weeks(5 + 7)
    )


def test_an_all_or_nothing_consumer_refuses_h5_before_rows_run() -> None:
    """A varied v13 term may resolve past h4; the refusal happens at startup."""

    with pytest.raises(IntervalUnavailable, match="h5"):
        require_interval_horizon(
            consumer="seasonal-buy",
            required_horizon_weeks=required_horizon_weeks(28 + 7),
        )


def _series_row(horizon: int, *, available: bool, p50: float = 10.0) -> dict:
    return {
        "sku_id": "sku-1", "store_id": "store-1", "channel_id": "online",
        "horizon_week": horizon, "interval_available": available,
        "yhat_p50": p50,
    }


def test_a_partial_consumer_skips_only_unavailable_rows_and_emits_one_exception() -> None:
    ledger = PartialConsumerLedger(consumer="cold_start_long_horizon_replenishment")
    computable = [ledger.observe(_series_row(h, available=h <= 4)) for h in range(1, 9)]
    assert computable == [True] * 4 + [False] * 4
    exceptions = ledger.exceptions()
    assert len(exceptions) == 1, "one record per SeriesKey, never one per horizon"
    assert exceptions[0]["unavailable_from_horizon"] == 5
    assert exceptions[0]["unavailable_through_horizon"] == 8
    assert exceptions[0]["withheld_horizon_count"] == 4
    summary = ledger.market_summary()
    assert summary["marketSubCapabilityUnavailable"] is False


def test_the_hundred_percent_skip_floor_marks_the_market_unavailable() -> None:
    ledger = PartialConsumerLedger(consumer="cold_start_long_horizon_replenishment")
    for horizon in range(5, 9):
        ledger.observe(_series_row(horizon, available=False))
    summary = ledger.market_summary()
    assert summary["marketSubCapabilityUnavailable"] is True
    assert summary["wholeConsumerUnavailable"] is True


def test_branching_on_p90_nullability_is_refused() -> None:
    ledger = PartialConsumerLedger(consumer="x")
    with pytest.raises(ValueError, match="interval_available"):
        ledger.observe({"sku_id": "s", "store_id": "st", "channel_id": "c",
                        "horizon_week": 5, "yhat_p50": 1.0})


# -- lane and term resolution ---------------------------------------------------

_LANES = [
    {"lane_id": "l1", "lane_type": "replenishment", "demand_location_id": "bandra",
     "channel_id": None, "supply_location_id": "mumbai-dc", "priority_rank": 1,
     "effective_from": date(2020, 1, 1), "effective_to": None},
    {"lane_id": "l2", "lane_type": "replenishment", "demand_location_id": "bandra",
     "channel_id": None, "supply_location_id": "pune-overflow", "priority_rank": 2,
     "effective_from": date(2020, 1, 1), "effective_to": None},
    {"lane_id": "l3", "lane_type": "customer_fulfillment", "demand_location_id": "bandra",
     "channel_id": "online", "supply_location_id": "mumbai-dc", "priority_rank": 1,
     "effective_from": date(2020, 1, 1), "effective_to": None},
]


def test_exact_channel_beats_the_null_channel_default() -> None:
    lane = resolve_lane(
        _LANES, demand_location_id="bandra", channel_id="online",
        on_date=date(2026, 7, 1), lane_type="customer_fulfillment",
    )
    assert lane["lane_id"] == "l3"


def test_rank_one_wins_and_missing_lane_fails_closed() -> None:
    lane = resolve_lane(
        _LANES, demand_location_id="bandra", channel_id=None,
        on_date=date(2026, 7, 1),
    )
    assert lane["supply_location_id"] == "mumbai-dc"
    with pytest.raises(ResolutionError) as caught:
        resolve_lane(_LANES, demand_location_id="unknown", channel_id=None,
                     on_date=date(2026, 7, 1))
    assert caught.value.reason_code == "NO_ACTIVE_SERVICE_LANE"


_TERMS = [
    {"destination_location_id": "mumbai-dc", "origin_kind": "external_supplier",
     "origin_id": "sup-1", "merch_scope_type": "category", "merch_scope_id": "FOODS",
     "effective_from": date(2020, 1, 1), "lead_time_days": 7},
    {"destination_location_id": "mumbai-dc", "origin_kind": "external_supplier",
     "origin_id": "sup-1", "merch_scope_type": "dept", "merch_scope_id": "FOODS_1",
     "effective_from": date(2020, 1, 1), "lead_time_days": 5},
    {"destination_location_id": "mumbai-dc", "origin_kind": "external_supplier",
     "origin_id": "sup-1", "merch_scope_type": "sku", "merch_scope_id": "sku-9",
     "effective_from": date(2020, 1, 1), "lead_time_days": 3},
]


def test_sku_beats_dept_beats_category() -> None:
    resolve = lambda sku: resolve_supply_term(  # noqa: E731
        _TERMS, destination_location_id="mumbai-dc",
        origin_kind="external_supplier", origin_id="sup-1",
        sku_id=sku, dept_id="FOODS_1", category="FOODS", on_date=date(2026, 7, 1),
    )
    assert resolve("sku-9")["lead_time_days"] == 3
    assert resolve("sku-other")["lead_time_days"] == 5


def test_a_null_origin_never_wildcard_matches() -> None:
    with pytest.raises(ResolutionError) as caught:
        resolve_supply_term(
            _TERMS, destination_location_id="mumbai-dc",
            origin_kind="external_supplier", origin_id="",
            sku_id="sku-9", dept_id="FOODS_1", category="FOODS",
            on_date=date(2026, 7, 1),
        )
    assert caught.value.reason_code == "SUPPLY_TERM_ORIGIN_REQUIRED"


def test_equal_precedence_ambiguity_fails_closed() -> None:
    duplicated = _TERMS + [dict(_TERMS[2], lead_time_days=9)]
    with pytest.raises(ResolutionError) as caught:
        resolve_supply_term(
            duplicated, destination_location_id="mumbai-dc",
            origin_kind="external_supplier", origin_id="sup-1",
            sku_id="sku-9", dept_id="FOODS_1", category="FOODS",
            on_date=date(2026, 7, 1),
        )
    assert caught.value.reason_code == "SUPPLY_TERM_AMBIGUOUS"


# -- ABC -------------------------------------------------------------------------

def test_abc_crossing_sku_stays_in_its_class_and_ties_are_frozen() -> None:
    rows = [
        {"sku_id": "a", "location_id": "dc", "market_id": "india-west",
         "trailing_avg_weekly_units": "100", "accepted_unit_cost_minor": 100},
        {"sku_id": "b", "location_id": "dc", "market_id": "india-west",
         "trailing_avg_weekly_units": "30", "accepted_unit_cost_minor": 100},
        {"sku_id": "c", "location_id": "dc", "market_id": "india-west",
         "trailing_avg_weekly_units": "5", "accepted_unit_cost_minor": 100},
    ]
    classes = classify_abc(rows)
    # a = 74% share-before 0 -> A; b crosses 80% with share-before 0.74 -> A is
    # wrong? share_before(b) = 0.7407 < 0.80 -> A. c share_before = 0.9629 -> C.
    assert classes[("a", "dc")]["abc_class"] == "A"
    assert classes[("b", "dc")]["abc_class"] == "A"
    assert classes[("c", "dc")]["abc_class"] == "C"


def test_abc_missing_cost_is_excluded_with_a_reason_never_ranked_at_zero() -> None:
    rows = [
        {"sku_id": "a", "location_id": "dc", "market_id": "india-west",
         "trailing_avg_weekly_units": "10", "accepted_unit_cost_minor": 100},
        {"sku_id": "b", "location_id": "dc", "market_id": "india-west",
         "trailing_avg_weekly_units": "10", "accepted_unit_cost_minor": None},
    ]
    classes = classify_abc(rows)
    assert classes[("b", "dc")]["abc_class"] is None
    assert classes[("b", "dc")]["reason_code"] == "ABC_UNIT_COST_UNAVAILABLE"


def test_abc_refuses_cross_market_ranking() -> None:
    rows = [
        {"sku_id": "a", "location_id": "dc", "market_id": "india-west",
         "trailing_avg_weekly_units": "10", "accepted_unit_cost_minor": 100},
        {"sku_id": "b", "location_id": "dc2", "market_id": "us-new-york",
         "trailing_avg_weekly_units": "10", "accepted_unit_cost_minor": 100},
    ]
    with pytest.raises(ValueError, match="market-local"):
        classify_abc(rows)


# -- cohorts ---------------------------------------------------------------------

def test_cohort_assignment_is_stable_and_roughly_five_percent() -> None:
    def assign(sku: str) -> str:
        return assign_cohort(
            retailer_id="retailer-demo", tenant_id="tenant-demo",
            market_id="india-west", location_id="bandra", sku_id=sku,
        )

    first = [assign(f"sku-{index}") for index in range(2000)]
    assert first == [assign(f"sku-{index}") for index in range(2000)]
    share = first.count("calibration") / len(first)
    assert 0.03 < share < 0.07, f"5% target, measured {share:.3f}"


def test_a_blank_key_field_is_refused() -> None:
    with pytest.raises(ValueError, match="market_id"):
        assign_cohort(retailer_id="r", tenant_id="t", market_id="",
                      location_id="l", sku_id="s")


# -- the weekly clock -------------------------------------------------------------

def test_monday_opening_uses_the_preceding_thursday_in_both_markets() -> None:
    for market_timezone in ("Asia/Kolkata", "America/New_York"):
        opening, closing = monday_period_bounds(date(2026, 7, 15), market_timezone)
        assert opening.weekday() == 0 and opening.time() == time(0)
        assert (closing - opening).days == 7
        snapshot = opening_snapshot_instant(opening, market_timezone)
        assert snapshot.weekday() == 3, "Thursday"
        assert snapshot.time() == time(23)
        assert snapshot < opening, "the snapshot precedes the period it seeds"
        # Compare in UTC: Python subtracts same-tzinfo datetimes in WALL time,
        # which silently ignores an offset change across the interval.
        elapsed = (
            opening.astimezone(timezone.utc) - snapshot.astimezone(timezone.utc)
        ).total_seconds()
        assert elapsed == 73 * 3600


def test_dst_transition_week_is_not_forced_to_73_hours() -> None:
    """US spring-forward (2026-03-08). Zoned local instants make the bridge 72
    elapsed hours that week; forcing 73 would shift the opening by an hour."""

    opening, _ = monday_period_bounds(date(2026, 3, 9), "America/New_York")
    snapshot = opening_snapshot_instant(opening, "America/New_York")
    elapsed = (
        opening.astimezone(timezone.utc) - snapshot.astimezone(timezone.utc)
    ).total_seconds()
    assert elapsed == 72 * 3600, "spring-forward removes one real hour"
    # The LOCAL instants stay at their declared cutoffs -- that is what "zoned
    # local instants" means: wall anchors hold, elapsed time moves.
    assert snapshot.time() == time(23)
    assert opening.time() == time(0)


def test_the_thursday_inside_the_target_week_is_never_used() -> None:
    opening, closing = monday_period_bounds(date(2026, 7, 15), "Asia/Kolkata")
    snapshot = opening_snapshot_instant(opening, "Asia/Kolkata")
    assert not (opening <= snapshot < closing), (
        "the seeding snapshot must be outside the period it opens"
    )
