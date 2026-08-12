from pathlib import Path

import pandas as pd

from retail_ml.pricing.policy import load_pricing_policy
from retail_ml.pricing.recommendation import build_recommendations
from retail_ml.pricing.simulation import SimulationError, run_price_simulation


ROOT = Path(__file__).resolve().parents[2]
KEY = {
    "market_id": "gulf-india", "sku_id": "sku-1",
    "store_id": "gulf-india:store-1", "channel_id": "retail",
}
SCENARIO_SEMANTICS = (
    "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
)


def _response(**changes):
    return {
        **KEY, "channel_type": "store", "department_id": "lubricants", "category": "Engine Oil",
        "product_name": "Gulf Oil", "currency_code": "INR",
        "disposition": "accepted", "department_enabled": True,
        "first_failure_reason": None, "current_price_minor": 20_000,
        "support_min_minor": 19_000, "support_max_minor": 21_000,
        "shrunk_beta": -1.2, "confidence": 0.96,
        **changes,
    }


def _forecast():
    return pd.DataFrame([{**KEY, "expected_units": 100.0, "pit_eligible": True}])


def _inventory(**changes):
    return pd.DataFrame([{**KEY, "atp_units": 500.0, "stock_cover_days": 35,
                          "synthetic_cost_minor": 12_000,
                          "cost_provenance": "generated_source_native", **changes}])


def _guard(status="no_overlap"):
    return pd.DataFrame([{**KEY, "guard_status": status}])


def _build(response=None, guard=None, inventory=None):
    return build_recommendations(
        pd.DataFrame([response or _response()]), _forecast(),
        inventory if inventory is not None else _inventory(),
        pd.DataFrame(), guard if guard is not None else _guard(),
        pricing_policy=load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
        evidence={"bundle": "test"},
    )


def test_negative_elastic_response_can_produce_decrease_and_synthetic_cost_is_separate() -> None:
    recommendations, candidates = _build()
    row = recommendations.iloc[0]

    assert row["action"] == "Decrease"
    assert row["proposed_price_minor"] < row["current_price_minor"]
    assert row["margin_impact_minor"] is None
    assert row["margin_reason_code"] == "COST_NOT_CLIENT_ACTUAL"
    assert row["synthetic_cost_minor"] == 12_000
    assert candidates["eligible"].all()


def test_active_promotion_preserves_current_price_as_hold() -> None:
    recommendations, candidates = _build(guard=_guard("applicable"))

    assert recommendations.iloc[0]["action"] == "Hold"
    protected = candidates[candidates["candidate_price_minor"] != 20_000]
    assert set(protected["rejection_reason"]) == {"ACTIVE_PROMOTION_PROTECTED"}


def test_rejected_response_remains_visible_as_withheld_assessment() -> None:
    recommendations, _ = _build(
        response=_response(disposition="rejected", first_failure_reason="BETA_SIGN_REJECTED")
    )

    assert recommendations.iloc[0]["record_kind"] == "withheld_assessment"
    assert not recommendations.iloc[0]["selectable"]
    assert recommendations.iloc[0]["first_failure_reason"] == "BETA_SIGN_REJECTED"
    assert {
        "synthetic_cost_minor",
        "stock_cover_days",
        "competitor_price_minor",
        "forecast_expected_units",
        "forecast_scenario_semantics",
    } <= set(recommendations.columns)
    assert recommendations.iloc[0]["synthetic_cost_minor"] is None


def test_stateless_simulation_preserves_primary_and_synthetic_margin_boundaries() -> None:
    recommendations, candidates = _build(
        inventory=_inventory(client_actual_cost_minor=13_000, cost_provenance="client_actual")
    )
    recommendation = recommendations.iloc[0].to_dict()
    legal_proposed = int(candidates[candidates["eligible"]]["candidate_price_minor"].iloc[0])
    result = run_price_simulation(
        response=_response(), recommendation=recommendation,
        forecast={"expected_units": 100, "best_case_units": 110, "worst_case_units": 90,
                  "forecast_scenario_semantics": SCENARIO_SEMANTICS},
        inventory={"atp_units": 500, "client_actual_cost_minor": 13_000,
                   "synthetic_cost_minor": 12_000, "clearance_context_available": True,
                   "cost_as_of": "2026-07-31T00:00:00Z"},
        proposed_price_minor=legal_proposed, demand_assumption="Expected",
        inventory_objective="Margin Protection",
        pricing_policy=load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
    )

    assert result["mutated"] is False
    assert result["metricOrder"] == ["Units", "Revenue", "Gross Margin", "Ending Stock"]
    assert result["columns"]["current"]["grossMarginMinor"] is not None
    assert result["syntheticMarginScenario"]["doesNotAffectRecommendation"] is True


def test_simulation_refuses_off_grid_price() -> None:
    recommendations, _ = _build()
    try:
        run_price_simulation(
            response=_response(), recommendation=recommendations.iloc[0].to_dict(),
            forecast={"expected_units": 100, "best_case_units": 110, "worst_case_units": 90,
                      "forecast_scenario_semantics": SCENARIO_SEMANTICS},
            inventory={"atp_units": 500, "clearance_context_available": True},
            proposed_price_minor=20_042, demand_assumption="Expected",
            inventory_objective="Clearance",
            pricing_policy=load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
        )
    except SimulationError as error:
        assert error.reason_code == "PROPOSED_PRICE_OUTSIDE_GUARDRAIL"
    else:
        raise AssertionError("off-grid price was accepted")
