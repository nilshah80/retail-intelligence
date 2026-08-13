"""Client-actual cost gate, min-margin guard, and revenue-independence tests.

Generated data can never satisfy the client-actual gate; these tests exercise the
positive arithmetic path and every negative reason through synthetic_test fixtures
that structurally mimic a client feed. No fixture here authorises an active
``price_margin`` selection — that remains an external-approval concern.
"""

from decimal import Decimal
from pathlib import Path

import pandas as pd

from retail_ml.pricing.cost import (
    CostResolution,
    gross_margin_pct,
    resolve_client_cost,
)
from retail_ml.pricing.policy import load_pricing_policy
from retail_ml.pricing.recommendation import build_recommendations
from retail_ml.pricing.simulation import (
    FORECAST_SCENARIO_SEMANTICS,
    SimulationError,
    run_price_simulation,
)


ROOT = Path(__file__).resolve().parents[2]
KEY = {
    "market_id": "gulf-india", "sku_id": "sku-1",
    "store_id": "gulf-india:store-1", "channel_id": "retail",
}
DECISION_AS_OF = "2026-07-31T00:00:00Z"


def _cost_row(**changes):
    """A fully valid client-actual cost record; override one field to fail a gate.

    A genuine client feed carries evidence_class="client" and an explicit
    pricing-margin allowed-use. A synthetic_test record is structurally valid but
    must never resolve to a served margin.
    """
    return {
        "cost_provenance": "client_actual",
        "cost_evidence_class": "client",
        "cost_allowed_use": "pricing_margin",
        "cost_ownership_status": "active",
        "client_actual_cost_minor": 12_000,
        "cost_currency_code": "INR",
        "cost_scope_market_id": KEY["market_id"],
        "cost_scope_location_id": KEY["store_id"],
        "cost_method": "WAC",
        "cost_method_verified": True,
        "cost_known_as_of": "2026-07-01T00:00:00Z",
        "cost_as_of": DECISION_AS_OF,
        **changes,
    }


def _resolve(**changes) -> CostResolution:
    return resolve_client_cost(
        _cost_row(**changes),
        price_currency_code="INR",
        market_id=KEY["market_id"],
        store_id=KEY["store_id"],
        decision_as_of=DECISION_AS_OF,
    )


# --- Resolver: the positive path and every precedence-ordered reason ----------

def test_valid_client_actual_cost_resolves() -> None:
    resolution = _resolve()
    assert resolution.is_client_actual
    assert resolution.cost_minor == 12_000
    assert resolution.reason_code is None
    assert resolution.method == "WAC"


def test_generated_cost_is_never_client_actual() -> None:
    resolution = _resolve(cost_provenance="generated_source_native")
    assert not resolution.is_client_actual
    assert resolution.cost_minor is None
    assert resolution.reason_code == "COST_NOT_CLIENT_ACTUAL"


def test_synthetic_test_evidence_never_resolves_to_a_served_margin() -> None:
    # Structurally valid but not client-owned: it must not produce a margin value.
    resolution = _resolve(cost_evidence_class="synthetic_test")
    assert not resolution.is_client_actual
    assert resolution.reason_code == "COST_NOT_CLIENT_ACTUAL"


def test_missing_pricing_margin_allowed_use_is_not_client_actual() -> None:
    assert _resolve(cost_allowed_use=None).reason_code == "COST_NOT_CLIENT_ACTUAL"
    assert _resolve(cost_allowed_use="analytics").reason_code == "COST_NOT_CLIENT_ACTUAL"


def test_each_negative_gate_reports_its_precedence_reason() -> None:
    cases = {
        "COST_OWNERSHIP_REVOKED": {"cost_ownership_status": "revoked"},
        "COST_MISSING": {"client_actual_cost_minor": None},
        "COST_NON_POSITIVE": {"client_actual_cost_minor": 0},
        "COST_CURRENCY_MISMATCH": {"cost_currency_code": "USD"},
        "COST_SCOPE_MISMATCH": {"cost_scope_location_id": "gulf-india:store-9"},
        "COST_METHOD_UNSUPPORTED": {"cost_method": "LIFO"},
        "FIFO_NOT_VERIFIED": {"cost_method": "FIFO", "cost_method_verified": False},
        "COST_AFTER_DECISION_ORIGIN": {"cost_known_as_of": "2026-08-15T00:00:00Z"},
        "COST_STALE": {"cost_known_as_of": "2024-01-01T00:00:00Z"},
    }
    for expected, change in cases.items():
        resolution = _resolve(**change)
        assert resolution.reason_code == expected, (expected, resolution)
        assert resolution.cost_minor is None


def test_verified_fifo_is_admitted() -> None:
    resolution = _resolve(cost_method="FIFO", cost_method_verified=True)
    assert resolution.is_client_actual
    assert resolution.method == "FIFO"


def test_missing_observation_time_is_stale() -> None:
    assert _resolve(cost_known_as_of=None).reason_code == "COST_STALE"


def test_gross_margin_pct_is_exact() -> None:
    assert gross_margin_pct(20_000, 12_000) == Decimal("40.0000")
    assert gross_margin_pct(20_000, 18_000) == Decimal("10.0000")


# --- Integration through build_recommendations --------------------------------

def _response(**changes):
    return {
        **KEY, "channel_type": "store", "department_id": "lubricants",
        "category": "Engine Oil", "category_label": "Engine Oil",
        "product_name": "Gulf Oil", "currency_code": "INR",
        "disposition": "accepted", "department_enabled": True,
        "first_failure_reason": None, "current_price_minor": 20_000,
        "support_min_minor": 19_000, "support_max_minor": 21_000,
        "shrunk_beta": -1.2, "confidence": 0.96, **changes,
    }


def _forecast():
    return pd.DataFrame([{**KEY, "expected_units": 100.0, "pit_eligible": True}])


def _inventory(**cost_changes):
    return pd.DataFrame([{
        **KEY, "atp_units": 500.0, "stock_cover_days": 35,
        "synthetic_cost_minor": 12_000, "synthetic_cost_method": "WAC",
        **_cost_row(**cost_changes),
    }])


def _build(inventory):
    return build_recommendations(
        pd.DataFrame([_response()]), _forecast(), inventory,
        pd.DataFrame(), pd.DataFrame([{**KEY, "guard_status": "no_overlap"}]),
        pricing_policy=load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
        evidence={"bundle": "test"}, decision_as_of=DECISION_AS_OF,
    )


def test_generated_cost_shows_computed_wac_margin() -> None:
    # Demo choice: the generated computed-WAC cost is the cost, so recommendation
    # rows carry real margin values (price - WAC), no client cost required. The
    # revenue action is unchanged.
    recommendations, _ = _build(_inventory(cost_provenance="generated_source_native"))
    row = recommendations.iloc[0]
    assert row["action"] == "Decrease"
    assert row["margin_impact_minor"] is not None
    assert row["margin_reason_code"] is None
    assert row["current_margin_pct"] == 40.0  # (20000 - 12000) / 20000


def test_valid_client_cost_produces_margin_number_and_percentages() -> None:
    recommendations, _ = _build(_inventory())
    row = recommendations.iloc[0]
    assert row["margin_impact_minor"] is not None
    assert row["margin_reason_code"] is None
    # Cost 12,000 against the 20,000 current price is a 40% current margin.
    assert row["current_margin_pct"] == 40.0
    assert row["expected_margin_pct"] is not None


def test_margin_floor_withholds_rather_than_reporting_a_false_hold() -> None:
    # Cost 18,000 vs a 20,000 price: current margin is 10% (< 12% floor) and the
    # elastic revenue-optimal move (a decrease) is blocked by the floor. The result
    # must be a reason-coded withheld assessment — not a false Hold — while the
    # candidate table still records the floor block and the current price stays
    # visible for comparison.
    recommendations, candidates = _build(_inventory(client_actual_cost_minor=18_000))
    assert "MARGIN_BELOW_FLOOR" in set(candidates["rejection_reason"].dropna())
    current = candidates[candidates["candidate_price_minor"] == 20_000]
    assert bool(current["eligible"].all())  # baseline stays eligible for comparison
    row = recommendations.iloc[0]
    assert row["record_kind"] == "withheld_assessment"
    assert row["action"] is None
    assert row["first_failure_reason"] == "MARGIN_BELOW_FLOOR"
    assert row["current_price_minor"] == 20_000  # current price preserved for comparison
    assert row["margin_reason_code"] is None  # cost is client-actual; margin was evaluated


def test_resolver_reports_primary_and_complete_secondary_reasons() -> None:
    # Client-owned but with two independent defects: currency mismatch and stale.
    resolution = _resolve(cost_currency_code="USD", cost_known_as_of="2024-01-01T00:00:00Z")
    assert resolution.reason_code == "COST_CURRENCY_MISMATCH"  # precedence-primary
    assert "COST_STALE" in resolution.secondary_reason_codes
    assert resolution.reason_codes[0] == "COST_CURRENCY_MISMATCH"


def test_invalid_client_cost_falls_back_to_computed_wac_margin() -> None:
    # A client cost that fails validation (currency mismatch here) is not used, but
    # the demo still shows the computed-WAC margin from the generated cost, and the
    # revenue recommendation is unchanged. The specific client-cost failure reason is
    # asserted at the resolver level (test_each_negative_gate...).
    recommendations, _ = _build(_inventory(cost_currency_code="USD"))
    row = recommendations.iloc[0]
    assert row["action"] == "Decrease"
    assert row["margin_impact_minor"] is not None  # computed-WAC fallback
    assert row["margin_reason_code"] is None


def test_wac_margin_populates_primary_gross_margin() -> None:
    # PoC (plan §0.0): the generated weighted-average cost is the authoritative cost,
    # so the primary Gross Margin carries a real value. The obsolete synthetic-margin
    # scenario is no longer produced.
    recommendations, candidates = _build(_inventory(cost_provenance="generated_source_native"))
    recommendation = recommendations.iloc[0].to_dict()
    legal = int(candidates[candidates["eligible"]]["candidate_price_minor"].iloc[0])
    result = run_price_simulation(
        response=_response(), recommendation=recommendation,
        forecast={"expected_units": 100, "best_case_units": 110, "worst_case_units": 90,
                  "forecast_scenario_semantics": FORECAST_SCENARIO_SEMANTICS},
        inventory={"atp_units": 500, "synthetic_cost_minor": 12_000,
                   "clearance_context_available": True, "cost_as_of": DECISION_AS_OF},
        proposed_price_minor=legal, demand_assumption="Expected",
        inventory_objective="Clearance",
        pricing_policy=load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
    )
    # Primary Gross Margin carries the weighted-average-cost value...
    assert result["columns"]["current"]["grossMarginMinor"] is not None
    assert result["columns"]["current"]["grossMarginReasonCode"] is None
    # ...and the obsolete synthetic-margin scenario is gone.
    assert "syntheticMarginScenario" not in result
    assert result["recommendation"]["marginImpactMinor"] is not None


def test_min_margin_floor_is_enforced_on_generated_wac_without_client_cost() -> None:
    # PoC (§0.0): with no client cost the generated weighted-average cost IS the cost,
    # and the minimum-margin floor is enforced on it. A 19,000 WAC against the 20,000
    # price grid is far under the 12% floor, so every non-current candidate is blocked
    # and the row is a reason-coded withheld assessment — exercising the WAC fallback
    # (not the client-actual path that the neighbouring floor test covers).
    inventory = _inventory(cost_provenance="generated_source_native")
    inventory.loc[0, "synthetic_cost_minor"] = 19_000
    recommendations, candidates = _build(inventory)
    assert "MARGIN_BELOW_FLOOR" in set(candidates["rejection_reason"].dropna())
    current = candidates[candidates["candidate_price_minor"] == 20_000]
    assert bool(current["eligible"].all())  # baseline stays eligible for comparison
    row = recommendations.iloc[0]
    assert row["record_kind"] == "withheld_assessment"
    assert row["first_failure_reason"] == "MARGIN_BELOW_FLOOR"
    assert row["margin_reason_code"] is None  # WAC cost present; the floor was evaluated


def test_margin_protection_simulation_refuses_a_sub_floor_price_on_wac() -> None:
    # PoC (§0.0): Margin Protection enforces the minimum-margin floor on the
    # weighted-average cost. A legal on-grid price whose WAC margin is below the 12%
    # floor is refused with MARGIN_BELOW_FLOOR (no client-actual cost involved).
    recommendations, candidates = _build(_inventory(cost_provenance="generated_source_native"))
    recommendation = recommendations.iloc[0].to_dict()
    legal = int(candidates[candidates["eligible"]]["candidate_price_minor"].iloc[0])
    try:
        run_price_simulation(
            response=_response(), recommendation=recommendation,
            forecast={"expected_units": 100, "best_case_units": 110, "worst_case_units": 90,
                      "forecast_scenario_semantics": FORECAST_SCENARIO_SEMANTICS},
            inventory={"atp_units": 500, "synthetic_cost_minor": 19_000,
                       "clearance_context_available": True, "cost_as_of": DECISION_AS_OF},
            proposed_price_minor=legal, demand_assumption="Expected",
            inventory_objective="Margin Protection",
            pricing_policy=load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
        )
    except SimulationError as error:
        assert error.reason_code == "MARGIN_BELOW_FLOOR"
    else:
        raise AssertionError("a sub-floor price was accepted under Margin Protection")
