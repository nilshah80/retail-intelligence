"""P4-6 net-new engines: analytics, optimizers and demand-at-risk."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from retail_ml.engines.analytics import (
    age_bucket,
    ageing_action,
    classify_health,
    days_of_supply,
    expiry_exposure,
    store_wac_minor,
    supplier_risk,
)
from retail_ml.engines.demand_risk import demand_at_risk
from retail_ml.engines.optimizers import (
    TransferCandidate,
    allocate_channels,
    recommend_transfers,
)
from retail_ml.engines.primitives import InventoryPosition


def _position(**overrides: int) -> InventoryPosition:
    values = dict(
        on_hand_units=100, committed_units=0, reserved_units=0,
        damaged_units=0, on_order_units=0, in_transit_units=0,
    )
    values.update(overrides)
    return InventoryPosition(**values)


# -- health and days of supply --------------------------------------------------

def test_dead_stock_is_a_class_not_an_infinite_cover_number() -> None:
    """A cell with stock and no demand has infinite cover; rendering a huge
    number invites sort artifacts, rendering zero inverts the meaning."""

    assert days_of_supply(
        position_units=50, trailing_avg_daily_units=Decimal("0")
    ) is None
    verdict = classify_health(
        position=_position(), trailing_avg_daily_units=Decimal("0"),
        assortment_active=False,
    )
    assert verdict["health_class"] == "dead"
    assert verdict["reason_code"] == "DEAD_STOCK_DEASSORTED"


def test_health_precedence_stockout_beats_understock_beats_overstock() -> None:
    stockout = classify_health(
        position=_position(on_hand_units=10, committed_units=10),
        trailing_avg_daily_units=Decimal("5"), assortment_active=True,
    )
    assert stockout["health_class"] == "stockout"
    understock = classify_health(
        position=_position(on_hand_units=10),
        trailing_avg_daily_units=Decimal("5"), assortment_active=True,
    )
    assert understock["health_class"] == "understock"
    overstock = classify_health(
        position=_position(on_hand_units=500),
        trailing_avg_daily_units=Decimal("5"), assortment_active=True,
    )
    assert overstock["health_class"] == "overstock"


# -- ageing ----------------------------------------------------------------------

def test_age_buckets_are_deterministic_edges() -> None:
    assert age_bucket(on_hand_age_days=0) == "0-30"
    assert age_bucket(on_hand_age_days=29) == "0-30"
    assert age_bucket(on_hand_age_days=30) == "30-60"
    assert age_bucket(on_hand_age_days=400) == "180-plus"


def test_the_action_ladder_escalates_and_dead_stock_skips_to_markdown() -> None:
    watch = ageing_action(
        on_hand_age_days=5, cover_days=Decimal("10"), hold_cover_days=14,
        markdown_cover_days=21, markdown_pct=Decimal("0.1"),
    )
    assert watch["action"] == "watch"
    hold = ageing_action(
        on_hand_age_days=15, cover_days=Decimal("20"), hold_cover_days=14,
        markdown_cover_days=21, markdown_pct=Decimal("0.1"),
    )
    assert hold["action"] == "hold"
    markdown = ageing_action(
        on_hand_age_days=30, cover_days=Decimal("40"), hold_cover_days=14,
        markdown_cover_days=21, markdown_pct=Decimal("0.1"),
    )
    assert markdown["action"] == "markdown_candidate"
    assert markdown["markdown_pct"] == "0.1"
    dead = ageing_action(
        on_hand_age_days=30, cover_days=None, hold_cover_days=14,
        markdown_cover_days=21, markdown_pct=Decimal("0.1"),
    )
    assert dead["action"] == "markdown_candidate"


# -- expiry and valuation ----------------------------------------------------------

def test_expiry_counts_only_shelf_life_batches() -> None:
    batches = [
        {"expiry_date": date(2026, 8, 10), "on_hand_units": 10,
         "unit_cost_minor": 100, "currency_code": "INR"},
        {"expiry_date": date(2026, 7, 20), "on_hand_units": 4,
         "unit_cost_minor": 100, "currency_code": "INR"},
        {"expiry_date": None, "on_hand_units": 500, "unit_cost_minor": 100,
         "currency_code": "INR"},
    ]
    exposure = expiry_exposure(batches, as_of=date(2026, 8, 1))
    assert exposure["expiring_units"] == 10
    assert exposure["expired_units"] == 4
    assert exposure["exposure_minor"] == 1000
    assert exposure["currency_code"] == "INR"


def test_store_wac_needs_store_evidence_and_never_borrows_silently() -> None:
    """P4-D6: no cost-carrying receipt means a reason code, not a DC WAC."""

    empty = store_wac_minor([])
    assert empty["wac_minor"] is None
    assert empty["reason_code"] == "STORE_COST_EVIDENCE_ABSENT"
    computed = store_wac_minor([
        {"qty": 10, "unit_cost_minor": 100, "currency_code": "INR"},
        {"qty": 10, "unit_cost_minor": 200, "currency_code": "INR"},
    ])
    assert computed["wac_minor"] == 150
    assert computed["method"] == "store_receipt_wac"
    with pytest.raises(ValueError, match="currencies"):
        store_wac_minor([
            {"qty": 1, "unit_cost_minor": 100, "currency_code": "INR"},
            {"qty": 1, "unit_cost_minor": 100, "currency_code": "USD"},
        ])


# -- supplier risk -----------------------------------------------------------------

def test_missing_lead_variability_is_a_finding_not_calm() -> None:
    verdict = supplier_risk(
        otd_rate=Decimal("0.97"), lead_time_std_days=None,
        capacity_confirmed_pct=Decimal("0.9"), capacity_floor_pct=Decimal("0.7"),
    )
    assert verdict["risk_class"] == "medium"
    assert "LEAD_TIME_VARIABILITY_UNAVAILABLE" in verdict["reason_codes"]
    calm = supplier_risk(
        otd_rate=Decimal("0.97"), lead_time_std_days=Decimal("1.5"),
        capacity_confirmed_pct=Decimal("0.9"), capacity_floor_pct=Decimal("0.7"),
    )
    assert calm["risk_class"] == "low"


# -- transfer optimizer --------------------------------------------------------------

def _candidate(**overrides: object) -> TransferCandidate:
    values: dict = dict(
        lane_id="l1", from_location_id="mumbai-dc", to_location_id="bandra",
        sku_id="sku-1", market_id="india-west", currency_code="INR",
        units=24, expected_benefit_minor=4800, transit_days=1,
    )
    values.update(overrides)
    return TransferCandidate(**values)


def test_transfers_respect_source_reserve_and_target_headroom() -> None:
    recommendations = recommend_transfers(
        [_candidate()],
        source_atp={("mumbai-dc", "sku-1"): 30},
        source_residual_cover_units={("mumbai-dc", "sku-1"): 10},
        target_headroom_units={("bandra", "sku-1"): 100},
    )
    assert len(recommendations) == 1
    assert recommendations[0]["units"] == 20, "30 ATP minus 10 reserve"


def test_transfer_tie_break_is_frozen_not_input_order() -> None:
    tie_a = _candidate(sku_id="sku-b", to_location_id="store-2")
    tie_b = _candidate(sku_id="sku-a", to_location_id="store-2")
    for ordering in ([tie_a, tie_b], [tie_b, tie_a]):
        result = recommend_transfers(
            ordering,
            source_atp={("mumbai-dc", "sku-a"): 100, ("mumbai-dc", "sku-b"): 100},
            source_residual_cover_units={},
            target_headroom_units={
                ("store-2", "sku-a"): 100, ("store-2", "sku-b"): 100,
            },
        )
        assert [row["sku_id"] for row in result] == ["sku-a", "sku-b"]


def test_cross_market_transfer_batches_are_refused() -> None:
    with pytest.raises(ValueError, match="cross markets"):
        recommend_transfers(
            [_candidate(), _candidate(market_id="us-new-york", currency_code="USD")],
            source_atp={}, source_residual_cover_units={},
            target_headroom_units={},
        )


# -- channel allocation ----------------------------------------------------------------

def _demand(channel: str, requested: int, *, rank: int = 1, value: int = 100) -> dict:
    return {
        "market_id": "india-west", "location_id": "bandra",
        "channel_id": channel, "sku_id": "sku-1",
        "requested_units": requested, "service_class_rank": rank,
        "value_weight_minor": value,
    }


def test_allocation_conserves_the_pool_and_no_channel_disappears() -> None:
    result = allocate_channels(
        node_atp_units=50,
        demands=[_demand("store", 40), _demand("online", 30, rank=2)],
    )
    allocated = sum(row["allocated_units"] for row in result["allocations"])
    assert allocated + result["residual_units"] == 50
    assert len(result["allocations"]) == 2, "a starved channel is returned at zero"
    by_channel = {row["channel_id"]: row for row in result["allocations"]}
    assert by_channel["store"]["allocated_units"] == 40
    assert by_channel["online"]["allocated_units"] == 10
    assert by_channel["online"]["shortfall_units"] == 20


def test_minimum_share_reserves_a_floor_before_priority_spends() -> None:
    result = allocate_channels(
        node_atp_units=20,
        demands=[_demand("store", 40), _demand("online", 40, rank=2)],
        minimum_share=Decimal("0.25"),
    )
    by_channel = {row["channel_id"]: row for row in result["allocations"]}
    assert by_channel["online"]["allocated_units"] >= 10, (
        "the floor holds even though store outranks online"
    )


def test_duplicate_channel_rows_in_one_pool_are_refused() -> None:
    with pytest.raises(ValueError, match="twice"):
        allocate_channels(
            node_atp_units=10,
            demands=[_demand("store", 5), _demand("store", 5)],
        )


# -- demand at risk -----------------------------------------------------------------------

def _risk_row(horizon: int, *, available: bool, p90: float | None = 30.0) -> dict:
    return {
        "sku_id": "sku-1", "store_id": "bandra", "channel_id": "store",
        "horizon_week": horizon, "interval_available": available,
        "yhat_p50": 10.0, "yhat_p90": p90 if available else None,
        "atp_units": 12, "unit_price_minor": 100, "currency_code": "INR",
    }


def test_risk_is_upper_quantile_excess_and_unassessed_is_disclosed() -> None:
    result = demand_at_risk(
        [_risk_row(1, available=True), _risk_row(5, available=False)]
    )
    assert result["riskUnits"] == pytest.approx(18.0)
    assert result["riskValueMinor"] == 1800
    assert result["unassessed"]["rows"] == 1
    assert result["unassessed"]["reasonCode"] == "COLD_START_INTERVAL_UNCALIBRATED"
    assert len(result["exceptions"]) == 1
    assert "not a stock-out probability" in result["interpretation"]


def test_a_withheld_interval_is_never_zero_risk() -> None:
    """The skipped row contributes nothing to the total AND appears in the
    unassessed disclosure -- absence with a name, not silent zero."""

    only_withheld = demand_at_risk([_risk_row(5, available=False)])
    assert only_withheld["riskUnits"] == 0.0
    assert only_withheld["unassessed"]["rows"] == 1
    assert only_withheld["marketSubCapabilityUnavailable"] is True


def test_available_flag_with_missing_p90_is_corruption_not_a_skip() -> None:
    with pytest.raises(ValueError, match="yhat_p90"):
        demand_at_risk([_risk_row(1, available=True, p90=None)])
