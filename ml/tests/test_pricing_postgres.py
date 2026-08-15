from datetime import datetime, timezone
import math

import pandas as pd
import pytest

from retail_ml.pricing.postgres import (
    PricingServingError,
    _accepted_promotions,
    _details,
    _integer_field,
    _market_currency_map,
)


def _uplift_frame() -> pd.DataFrame:
    """A two-row promotion-uplift frame: one accepted, one withheld."""

    return pd.DataFrame(
        [
            {
                "market_id": "gulf-india", "promo_id": "gulf-diwali-trade-2016",
                "promo_name": "Diwali distributor trade scheme 2016",
                "promo_type": "campaign", "episode_weeks": 7, "control_weeks": 7,
                "expected_demand_uplift": 3.6608552346257266,
                "uplift_low": 2.1898560413065637, "uplift_high": 5.898107481151053,
                "revenue_uplift_minor": 5735451880.0,
                "margin_impact_minor": 1874982330.0, "margin_reason_code": None,
                "baseline_revenue_minor": 1566697264.0,
                "required_stock_units": 30706.0,
                "cannibalisation_risk": "PRIVACY_RESTRICTED", "confidence": 1.0,
                "valid_draws": 200, "numeric_result_rate": 1.0,
                "acceptance_status": "accepted", "first_failure_reason": None,
                "period_start": pd.Timestamp("2016-09-25"),
                "period_end": pd.Timestamp("2016-11-05"),
                "offer_value": 0.09, "objective": "demand_generation",
                "status": "Completed",
                "category_labels": "Motorcycle Oils, Passenger Car Motor Oils",
                "category_count": 2, "product_count": 48,
                "channel_count": 3, "all_stores": True,
            },
            {
                "market_id": "gulf-india", "promo_id": "gulf-weak-2017",
                "promo_name": "Low-support scheme", "promo_type": "campaign",
                "episode_weeks": 2, "control_weeks": 3,
                "expected_demand_uplift": None, "uplift_low": None,
                "uplift_high": None, "revenue_uplift_minor": None,
                "margin_impact_minor": None,
                "margin_reason_code": "PROMOTION_UPLIFT_UNSUPPORTED",
                "baseline_revenue_minor": None, "required_stock_units": None,
                "cannibalisation_risk": "PRIVACY_RESTRICTED", "confidence": 0.0,
                "valid_draws": 0, "numeric_result_rate": 0.0,
                "acceptance_status": "withheld",
                "first_failure_reason": "insufficient_episode_support",
                "period_start": pd.Timestamp("2017-01-01"),
                "period_end": pd.Timestamp("2017-01-31"),
                "offer_value": 0.05, "objective": "demand_generation",
                "status": "Completed",
                "category_labels": "Greases", "category_count": 1,
                "product_count": 6, "channel_count": 1, "all_stores": True,
            },
        ]
    )


def test_market_currency_map_reads_market_currency_from_any_frame() -> None:
    frames = {
        "price_recommendations": pd.DataFrame(
            [{"market_id": "gulf-india", "currency_code": "INR"}]
        ),
        "promotion_uplift": _uplift_frame(),  # carries no currency column
    }
    assert _market_currency_map(frames) == {"gulf-india": "INR"}


def test_accepted_promotions_embeds_only_accepted_rows_with_currency() -> None:
    summaries = _accepted_promotions(_uplift_frame(), {"gulf-india": "INR"})

    assert len(summaries) == 1
    item = summaries[0]
    assert item["promoId"] == "gulf-diwali-trade-2016"
    assert item["promoName"] == "Diwali distributor trade scheme 2016"
    assert item["promoType"] == "campaign"
    assert item["expectedDemandUplift"] == pytest.approx(3.6608552346257266)
    assert item["upliftLow"] == pytest.approx(2.1898560413065637)
    assert item["upliftHigh"] == pytest.approx(5.898107481151053)
    # Monetary minor units are carried as integers, never floats.
    assert item["revenueUpliftMinor"] == 5_735_451_880
    assert item["marginImpactMinor"] == 1_874_982_330
    assert isinstance(item["revenueUpliftMinor"], int)
    assert isinstance(item["marginImpactMinor"], int)
    assert item["confidence"] == pytest.approx(1.0)
    # cannibalisation risk is forwarded as the literal restricted string.
    assert item["cannibalisationRisk"] == "PRIVACY_RESTRICTED"
    assert item["currencyCode"] == "INR"
    # Source metadata is forwarded verbatim so the Planner grid shows real values.
    assert item["marketId"] == "gulf-india"
    assert item["objective"] == "demand_generation"
    assert item["status"] == "Completed"
    assert item["periodStart"] == "2016-09-25"
    assert item["periodEnd"] == "2016-11-05"
    assert item["offerValue"] == pytest.approx(0.09)
    assert item["categoryLabels"] == "Motorcycle Oils, Passenger Car Motor Oils"
    assert item["categoryCount"] == 2
    assert item["productCount"] == 48
    assert item["channelCount"] == 3
    assert item["allStores"] is True
    # Baseline revenue and required stock are integer minor/units, never floats.
    assert item["baselineRevenueMinor"] == 1_566_697_264
    assert item["requiredStockUnits"] == 30_706
    assert isinstance(item["baselineRevenueMinor"], int)
    assert isinstance(item["requiredStockUnits"], int)
    assert set(item) == {
        "promoId", "promoName", "promoType", "marketId", "objective", "status",
        "periodStart", "periodEnd", "offerValue", "categoryLabels",
        "categoryCount", "productCount", "channelCount", "allStores",
        "expectedDemandUplift", "upliftLow", "upliftHigh",
        "revenueUpliftMinor", "marginImpactMinor",
        "baselineRevenueMinor", "requiredStockUnits",
        "confidence", "cannibalisationRisk", "currencyCode",
    }


def test_accepted_promotions_empty_when_absent_or_none_accepted() -> None:
    assert _accepted_promotions(None, {}) == []
    assert _accepted_promotions(pd.DataFrame(), {}) == []
    withheld_only = _uplift_frame()
    withheld_only = withheld_only[withheld_only["acceptance_status"] == "withheld"]
    assert _accepted_promotions(withheld_only, {"gulf-india": "INR"}) == []


def test_nullable_integer_field_preserves_integral_float_from_pandas() -> None:
    assert _integer_field({"amount": 114_799.0}, "amount") == 114_799
    assert _integer_field({"amount": math.nan}, "amount") is None


def test_nullable_integer_field_refuses_fractional_value() -> None:
    with pytest.raises(PricingServingError, match="amount is not an integer"):
        _integer_field({"amount": 114_799.5}, "amount")


def test_details_are_json_safe_recursively() -> None:
    observed = datetime(2026, 7, 31, 18, 30, tzinfo=timezone.utc)

    assert _details(
        {
            "observed": observed,
            "available": True,
            "nested": {"values": [observed, math.nan, False]},
        }
    ) == {
        "observed": "2026-07-31T18:30:00+00:00",
        "available": True,
        "nested": {"values": ["2026-07-31T18:30:00+00:00", None, False]},
    }
