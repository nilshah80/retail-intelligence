"""Bounded, deterministic and non-mutating price scenario calculation."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping

from retail_ml.pricing.policy import enumerate_candidates, resolve_market_rule


class SimulationError(ValueError):
    """A simulation request is invalid or lacks accepted evidence."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


FORECAST_SCENARIO_SEMANTICS = (
    "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
)


def _integer(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def run_price_simulation(
    *,
    response: Mapping[str, Any],
    recommendation: Mapping[str, Any],
    forecast: Mapping[str, Any],
    inventory: Mapping[str, Any],
    proposed_price_minor: int,
    demand_assumption: str,
    inventory_objective: str,
    pricing_policy: Mapping[str, Any],
) -> dict[str, Any]:
    if response.get("disposition") != "accepted":
        raise SimulationError("MISSING_ACCEPTED_RESPONSE", "response is not accepted")
    if demand_assumption not in {"Expected", "Best Case", "Worst Case"}:
        raise SimulationError("INVALID_DEMAND_ASSUMPTION", "unsupported demand assumption")
    if inventory_objective not in {"Margin Protection", "Clearance"}:
        raise SimulationError("INVALID_INVENTORY_OBJECTIVE", "unsupported inventory objective")
    if inventory_objective == "Margin Protection" and inventory.get("client_actual_cost_minor") is None:
        raise SimulationError("COST_NOT_CLIENT_ACTUAL", "margin protection needs client-actual cost")
    if inventory_objective == "Clearance" and not inventory.get("clearance_context_available", False):
        raise SimulationError("INVENTORY_CONTEXT_UNAVAILABLE", "clearance needs ageing evidence")
    if forecast.get("forecast_scenario_semantics") != FORECAST_SCENARIO_SEMANTICS:
        raise SimulationError(
            "FORECAST_SCENARIO_SEMANTICS_INVALID",
            "four-week demand assumptions lack the approved planning-bound semantics",
        )
    current = int(response["current_price_minor"])
    rule = resolve_market_rule(
        dict(pricing_policy), str(response["market_id"]), str(response["currency_code"])
    )
    legal = enumerate_candidates(
        current_price_minor=current,
        support_min_minor=int(response["support_min_minor"]),
        support_max_minor=int(response["support_max_minor"]),
        dominance=float(response["confidence"]),
        rule=rule,
        competitor_upper_bound_minor=recommendation.get("competitor_price_minor"),
    )
    if proposed_price_minor not in legal:
        raise SimulationError(
            "PROPOSED_PRICE_OUTSIDE_GUARDRAIL",
            "proposed price is off-grid, unsupported, or exceeds its change cap",
        )
    demand_key = {
        "Expected": "expected_units",
        "Best Case": "best_case_units",
        "Worst Case": "worst_case_units",
    }[demand_assumption]
    if forecast.get(demand_key) is None:
        raise SimulationError("FORECAST_SCENARIO_UNAVAILABLE", f"{demand_assumption} forecast is unavailable")
    base_units = Decimal(str(forecast[demand_key]))
    beta = Decimal(str(response["shrunk_beta"]))

    def scenario(price: int) -> dict[str, Any]:
        ratio = Decimal(price) / Decimal(current)
        units = Decimal(str(float(base_units) * float(ratio) ** float(beta)))
        revenue = units * Decimal(price)
        cost = inventory.get("client_actual_cost_minor")
        margin = None if cost is None else _integer(units * (Decimal(price) - Decimal(str(cost))))
        stock = inventory.get("atp_units")
        ending = None if stock is None else float(Decimal(str(stock)) - units)
        return {
            "priceMinor": price,
            "units": float(units),
            "revenueMinor": _integer(revenue),
            "grossMarginMinor": margin,
            "grossMarginReasonCode": None if margin is not None else "COST_NOT_CLIENT_ACTUAL",
            "endingStockUnits": ending,
        }

    optimal = int(recommendation["proposed_price_minor"])
    current_result = scenario(current)
    proposed_result = scenario(proposed_price_minor)
    optimal_result = scenario(optimal)
    synthetic = None
    synthetic_cost = inventory.get("synthetic_cost_minor")
    if synthetic_cost is not None:
        cost = Decimal(str(synthetic_cost))
        synthetic = {
            "discriminator": "synthetic_margin_scenario",
            "label": "Synthetic demo margin — not client actual",
            "currentMinor": _integer(Decimal(str(current_result["units"])) * (Decimal(current) - cost)),
            "proposedMinor": _integer(Decimal(str(proposed_result["units"])) * (Decimal(proposed_price_minor) - cost)),
            "aiOptimalMinor": _integer(Decimal(str(optimal_result["units"])) * (Decimal(optimal) - cost)),
            "currencyCode": response["currency_code"],
            "costMethod": inventory.get("synthetic_cost_method", "computed_wac"),
            "costAsOf": inventory.get("cost_as_of"),
            "doesNotAffectRecommendation": True,
        }
    revenue_change = proposed_result["revenueMinor"] - current_result["revenueMinor"]
    return {
        "schemaVersion": "retail-price-simulation/v1",
        "scope": {key: response[key] for key in ("market_id", "sku_id", "store_id", "channel_id")},
        "currencyCode": response["currency_code"],
        "simulationPeriod": "Next 4 Weeks",
        "demandAssumption": demand_assumption,
        "demandScenarioSemantics": FORECAST_SCENARIO_SEMANTICS,
        "inventoryObjective": inventory_objective,
        "columns": {
            "current": current_result,
            "proposed": proposed_result,
            "aiOptimal": optimal_result,
        },
        "metricOrder": ["Units", "Revenue", "Gross Margin", "Ending Stock"],
        "recommendation": {
            "priceMinor": optimal,
            "revenueImpactMinor": revenue_change,
            "marginImpactMinor": None,
            "marginReasonCode": "COST_NOT_CLIENT_ACTUAL" if inventory.get("client_actual_cost_minor") is None else None,
            "stockOutRisk": "High" if proposed_result["endingStockUnits"] is not None and proposed_result["endingStockUnits"] < 0 else "Low",
            "confidence": response["confidence"],
        },
        "competitorEvidence": {
            "included": recommendation.get("competitor_price_minor") is not None,
            "reasonCode": None if recommendation.get("competitor_price_minor") is not None else "COMPETITOR_BOUND_UNAVAILABLE",
        },
        "syntheticMarginScenario": synthetic,
        "mutated": False,
    }


__all__ = [
    "FORECAST_SCENARIO_SEMANTICS", "SimulationError", "run_price_simulation"
]
