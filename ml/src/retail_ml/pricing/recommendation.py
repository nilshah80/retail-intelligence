"""Deterministic revenue recommendations and withheld-assessment workbench."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Mapping

import pandas as pd

from retail_ml.pricing.cost import gross_margin_pct, resolve_client_cost
from retail_ml.pricing.policy import enumerate_candidates, resolve_market_rule


KEYS = ("market_id", "sku_id", "store_id", "channel_id")
CANDIDATE_COLUMNS = (
    *KEYS,
    "candidate_price_minor",
    "expected_units",
    "expected_revenue_minor",
    "eligible",
    "rejection_reason",
)
RECOMMENDATION_COLUMNS = (
    *KEYS,
    "product_name",
    "category",
    "category_label",
    "department_id",
    "channel_type",
    "recommendation_id",
    "record_kind",
    "selectable",
    "action",
    "disposition",
    "first_failure_reason",
    "current_price_minor",
    "proposed_price_minor",
    "currency_code",
    "expected_units_current",
    "expected_units_proposed",
    "expected_revenue_current_minor",
    "expected_revenue_proposed_minor",
    "revenue_impact_minor",
    "margin_impact_minor",
    "margin_reason_code",
    "current_margin_pct",
    "expected_margin_pct",
    "confidence",
    "confidence_label",
    "priority",
    "risk",
    "drivers",
    "stock_cover_days",
    "atp_units",
    "clearance_context_available",
    "competitor_price_minor",
    "competitor_evidence_label",
    "synthetic_cost_minor",
    "synthetic_cost_method",
    "cost_as_of",
    "pricing_unit_label",
    "base_unit_quantity",
    "pricing_pack_label",
    "forecast_expected_units",
    "forecast_best_case_units",
    "forecast_worst_case_units",
    "forecast_horizon_weeks",
    "forecast_scenario_semantics",
    "lineage",
    "forecast_demand_label",
)


class RecommendationError(RuntimeError):
    """Recommendation inputs or guard ordering are invalid."""


def _identifier(values: Mapping[str, Any]) -> str:
    payload = "|".join(str(values[key]) for key in KEYS).encode("utf-8")
    return "pr_" + hashlib.sha256(payload).hexdigest()[:20]


def _confidence_label(value: float | None) -> str:
    if value is None:
        return "Unavailable"
    if value >= 0.95:
        return "Very High"
    if value >= 0.90:
        return "High"
    if value >= 0.80:
        return "Medium"
    return "Low"


def _risk_label(change: Decimal, confidence: float) -> str:
    if abs(change) <= Decimal("0.015") and confidence >= 0.95:
        return "Low"
    if abs(change) <= Decimal("0.035") and confidence >= 0.90:
        return "Medium"
    return "High"


def _competitor_bound(
    bounds: pd.DataFrame, row: Mapping[str, Any]
) -> tuple[int | None, Mapping[str, Any] | None]:
    if bounds.empty:
        return None, None
    candidates = bounds[
        (bounds["market_id"] == row["market_id"])
        & (bounds["sku_id"] == row["sku_id"])
        & (
            (bounds["geo_scope_type"] == "market")
            | (
                (bounds["geo_scope_type"] == "location")
                & (bounds["geo_scope_id"] == row["store_id"])
            )
        )
    ]
    if candidates.empty:
        return None, None
    chosen = candidates.sort_values(
        ["competitor_upper_bound_minor", "match_id"]
    ).iloc[0]
    return int(chosen["competitor_upper_bound_minor"]), chosen.to_dict()


def _withheld(
    row: Mapping[str, Any], reason: str, *, evidence: Mapping[str, Any],
    margin_reason: str | None = "COST_NOT_CLIENT_ACTUAL",
) -> dict[str, Any]:
    base = {key: str(row[key]) for key in KEYS}
    return {
        **base,
        "product_name": row.get("product_name"),
        "category": row.get("category"),
        "category_label": row.get("category_label"),
        "department_id": row.get("department_id"),
        "channel_type": row.get("channel_type"),
        "recommendation_id": _identifier(base),
        "record_kind": "withheld_assessment",
        "selectable": False,
        # Manual review is the presentation cohort, not a pricing action.  A
        # withheld row must keep the Action cell unavailable so it can never be
        # mistaken for Hold or exported as a recommendation.
        "action": None,
        "disposition": "withheld",
        "first_failure_reason": reason,
        "current_price_minor": row.get("current_price_minor"),
        "proposed_price_minor": None,
        "currency_code": row.get("currency_code"),
        "expected_units_current": None,
        "expected_units_proposed": None,
        "expected_revenue_current_minor": None,
        "expected_revenue_proposed_minor": None,
        "revenue_impact_minor": None,
        "margin_impact_minor": None,
        "margin_reason_code": margin_reason,
        "current_margin_pct": None,
        "expected_margin_pct": None,
        "confidence": row.get("confidence"),
        "confidence_label": _confidence_label(row.get("confidence")),
        "priority": "Manual review",
        "risk": "Unavailable",
        "drivers": json.dumps([reason], separators=(",", ":")),
        # Keep the artifact shape stable when an evaluated scope is withheld
        # before forecast, inventory, competitor, or promotion enrichment. A
        # response-rich build can truthfully contain only withheld assessments;
        # downstream capability checks and PostgreSQL projection must still see
        # the same nullable columns as a mixed recommendation bundle.
        "stock_cover_days": None,
        "atp_units": None,
        "clearance_context_available": None,
        "competitor_price_minor": None,
        "competitor_evidence_label": None,
        "synthetic_cost_minor": None,
        "synthetic_cost_method": None,
        "cost_as_of": None,
        "pricing_unit_label": None,
        "base_unit_quantity": None,
        "pricing_pack_label": None,
        "forecast_expected_units": None,
        "forecast_best_case_units": None,
        "forecast_worst_case_units": None,
        "forecast_horizon_weeks": None,
        "forecast_scenario_semantics": None,
        "lineage": json.dumps(evidence, sort_keys=True, separators=(",", ":")),
    }


def build_recommendations(
    response: pd.DataFrame,
    forecast: pd.DataFrame,
    inventory: pd.DataFrame,
    competitor_bounds: pd.DataFrame,
    promotion_guard: pd.DataFrame,
    *,
    pricing_policy: Mapping[str, Any],
    evidence: Mapping[str, Any],
    decision_as_of: str | None = None,
    unit_basis: Mapping[tuple[str, ...], tuple[Any, Any, Any]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build recommendations in the frozen safety/guardrail ordering."""

    unit_basis = unit_basis or {}
    missing = sorted(set(KEYS) - set(response.columns))
    if missing:
        raise RecommendationError("response rows lack: " + ", ".join(missing))
    if response.empty:
        return (
            pd.DataFrame(columns=RECOMMENDATION_COLUMNS),
            pd.DataFrame(columns=CANDIDATE_COLUMNS),
        )
    forecast_by_key = {
        tuple(str(row[key]) for key in KEYS): row
        for row in forecast.to_dict("records")
    }
    inventory_by_key = {
        (str(row["market_id"]), str(row["sku_id"]), str(row["store_id"])): row
        for row in inventory.to_dict("records")
    }
    guard_by_key = {
        tuple(str(row[key]) for key in KEYS): row
        for row in promotion_guard.to_dict("records")
    }
    output: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    for response_row in response.sort_values(list(KEYS)).to_dict("records"):
        identity = tuple(str(response_row[key]) for key in KEYS)
        if response_row.get("disposition") != "accepted" or not response_row.get("department_enabled", True):
            output.append(
                _withheld(
                    response_row,
                    response_row.get("first_failure_reason") or "MISSING_ACCEPTED_RESPONSE",
                    evidence=evidence,
                )
            )
            continue
        forecast_row = forecast_by_key.get(identity)
        if forecast_row is None or forecast_row.get("expected_units") is None:
            output.append(_withheld(response_row, "MISSING_FORECAST", evidence=evidence))
            continue
        guard = guard_by_key.get(identity)
        if guard is None or guard.get("guard_status") == "missing":
            output.append(_withheld(response_row, "PROMOTION_PROTECTION_MISSING", evidence=evidence))
            continue
        if guard.get("guard_status") == "conflict":
            output.append(_withheld(response_row, "PROMOTION_CONFLICT", evidence=evidence))
            continue
        current = int(response_row["current_price_minor"])
        currency = str(response_row["currency_code"])
        market_rule = resolve_market_rule(
            dict(pricing_policy), str(response_row["market_id"]), currency
        )
        confidence = float(response_row["confidence"])
        # Resolve cost and the margin floor once per key, before candidate scoring,
        # so the guardrail can gate candidate eligibility rather than only annotate
        # the winner after the fact.
        inventory_row = inventory_by_key.get(
            (identity[0], identity[1], identity[2]), {}
        )
        cost = resolve_client_cost(
            inventory_row,
            price_currency_code=currency,
            market_id=identity[0],
            store_id=identity[2],
            decision_as_of=decision_as_of,
        )
        min_margin_pct = Decimal(str(market_rule.get("minMarginPct", "0")))
        client_cost_minor = cost.cost_minor if cost.is_client_actual else None
        # PoC cost-of-record: the generated weighted-average cost is the authoritative
        # unit cost, so the minimum-margin floor is evaluated AND enforced on it. A
        # client-actual cost is preferred only if one is ever supplied. See plan §0.0.
        wac_minor = inventory_row.get("synthetic_cost_minor")
        margin_cost_minor = (
            client_cost_minor
            if client_cost_minor is not None
            else (int(wac_minor) if wac_minor is not None else None)
        )
        competitor_upper, competitor_row = _competitor_bound(
            competitor_bounds, response_row
        )
        candidates = enumerate_candidates(
            current_price_minor=current,
            support_min_minor=int(response_row["support_min_minor"]),
            support_max_minor=int(response_row["support_max_minor"]),
            dominance=confidence,
            rule=market_rule,
            competitor_upper_bound_minor=competitor_upper,
        )
        beta = Decimal(str(response_row["shrunk_beta"]))
        baseline_units = Decimal(str(forecast_row["expected_units"]))
        # Baseline for the incremental-profit guard (plan §6.0 P2), on the WAC basis.
        current_revenue = baseline_units * Decimal(current)
        scored: list[tuple[int, Decimal, Decimal]] = []
        # Candidates blocked *only* by the margin floor (not promotion/stock), kept
        # so a Hold forced by the floor can be withheld rather than reported as a
        # genuine Hold recommendation.
        margin_blocked_scored: list[tuple[int, Decimal, Decimal]] = []
        # Candidates blocked *only* by the incremental-profit (margin-dilution) guard,
        # kept for the same reason: a Hold forced by dilution is a withheld assessment,
        # not a genuine Hold.
        dilution_blocked_scored: list[tuple[int, Decimal, Decimal]] = []
        for candidate in candidates:
            ratio = Decimal(candidate) / Decimal(current)
            expected_units = Decimal(
                str(float(baseline_units) * float(ratio) ** float(beta))
            )
            revenue = expected_units * Decimal(candidate)
            protected = guard.get("guard_status") == "applicable" and candidate != current
            stock_blocked = bool(
                inventory_row.get("stock_risk_blocked", False)
            ) and expected_units > baseline_units
            # Minimum-margin guard, evaluated on the weighted-average cost basis. It
            # never blocks the current price, so the baseline stays available for
            # comparison even when it is itself below the floor.
            margin_blocked = (
                margin_cost_minor is not None
                and candidate != current
                and gross_margin_pct(candidate, margin_cost_minor) < min_margin_pct
            )
            # Incremental-profit guard (MARGIN_DILUTION) — plan §6.0 P2. An actionable
            # candidate must strictly improve expected gross margin AND not reduce
            # expected revenue, both on the WAC basis. This refuses the revenue-
            # maximising price cut that dilutes margin — the root cause of the
            # all-Reduce / negative-opportunity profile — instead of serving it. The
            # current price is never dilution-blocked; a floor-blocked candidate is
            # already excluded, so the two guards never double-label the same row.
            margin_dilutive = False
            if (
                margin_cost_minor is not None
                and candidate != current
                and not margin_blocked
            ):
                unit_cost = Decimal(margin_cost_minor)
                candidate_margin = expected_units * (Decimal(candidate) - unit_cost)
                baseline_margin = baseline_units * (Decimal(current) - unit_cost)
                margin_dilutive = (
                    candidate_margin <= baseline_margin
                    or revenue < current_revenue
                )
            eligible = (
                not protected
                and not stock_blocked
                and not margin_blocked
                and not margin_dilutive
            )
            candidate_rows.append(
                {
                    **dict(zip(KEYS, identity, strict=True)),
                    "candidate_price_minor": candidate,
                    "expected_units": float(expected_units),
                    "expected_revenue_minor": int(
                        revenue.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
                    ),
                    "eligible": eligible,
                    "rejection_reason": (
                        "ACTIVE_PROMOTION_PROTECTED" if protected
                        else "STOCK_RISK_BLOCKED" if stock_blocked
                        else "MARGIN_BELOW_FLOOR" if margin_blocked
                        else "MARGIN_DILUTION" if margin_dilutive else None
                    ),
                }
            )
            if eligible:
                scored.append((candidate, expected_units, revenue))
            elif margin_blocked and not protected and not stock_blocked:
                margin_blocked_scored.append((candidate, expected_units, revenue))
            elif (
                margin_dilutive
                and not protected
                and not stock_blocked
                and not margin_blocked
            ):
                dilution_blocked_scored.append((candidate, expected_units, revenue))
        current_score = next((item for item in scored if item[0] == current), None)
        if current_score is None:
            output.append(_withheld(response_row, "NO_BETTER_LEGAL_CANDIDATE", evidence=evidence))
            continue
        # Highest revenue, then smallest absolute change, then lower price.
        chosen = max(
            scored,
            key=lambda item: (
                item[2], -abs(item[0] - current), -item[0]
            ),
        )
        minimum_gain = current_score[2] * Decimal("0.0005")
        if chosen[2] <= current_score[2] + minimum_gain:
            chosen = current_score
        # A Hold forced by the margin floor is a withheld assessment, not a
        # recommendation: if the only reason no move is chosen is that a
        # revenue-improving candidate was blocked by the floor, withhold with
        # MARGIN_BELOW_FLOOR rather than report a false Hold. The current price
        # remains visible on the withheld row for comparison. Cost is client-actual
        # here, so the margin reason is None (margin was evaluated, not unavailable).
        if chosen[0] == current and any(
            revenue > current_score[2] + minimum_gain
            for _price, _units, revenue in margin_blocked_scored
        ):
            output.append(
                _withheld(
                    response_row, "MARGIN_BELOW_FLOOR",
                    evidence=evidence, margin_reason=None,
                )
            )
            continue
        # A revenue-improving move refused ONLY because it would dilute gross margin is
        # never served — the guardrail protects the retailer from an unprofitable price.
        # But such a SKU is *well-priced*: no margin-accretive action is due, so it is a
        # genuine Hold ("held to protect margin"), NOT a withheld "Not available" row.
        # This is §2.2.1's mostly-well-priced catalog with bounded, profitable pockets:
        # opportunity stays strictly positive because no dilutive action is ever served,
        # and raising the (weighted-average) cost basis moves more SKUs into this
        # well-priced Hold band. Sub-floor blocks above remain withheld (plan §A5); this
        # branch only reclassifies the margin-dilution case from withheld to Hold.
        margin_protected_hold = chosen[0] == current and any(
            revenue > current_score[2] + minimum_gain
            for _price, _units, revenue in dilution_blocked_scored
        )
        proposed, proposed_units, proposed_revenue = chosen
        action = "Hold"
        if proposed > current:
            action = "Increase"
        elif proposed < current:
            action = "Decrease"
        change = Decimal(proposed) / Decimal(current) - Decimal(1)
        impact = proposed_revenue - current_score[2]
        # Reuse the weighted-average margin cost basis resolved above (plan §0.0):
        # the same cost that the minimum-margin floor is enforced on drives display.
        cost_minor = margin_cost_minor
        margin_impact: int | None = None
        margin_reason: str | None = None if cost_minor is not None else cost.reason_code
        current_margin_pct: float | None = None
        expected_margin_pct: float | None = None
        if cost_minor is not None:
            unit_cost = Decimal(cost_minor)
            margin_impact = int(
                (
                    proposed_units * (Decimal(proposed) - unit_cost)
                    - baseline_units * (Decimal(current) - unit_cost)
                ).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            )
            margin_reason = None
            current_margin_pct = float(gross_margin_pct(current, cost_minor))
            expected_margin_pct = float(gross_margin_pct(proposed, cost_minor))
        driver = (
            "Elastic demand supports a lower price" if action == "Decrease"
            else "Inelastic demand supports a higher price" if action == "Increase"
            else "Current price protects gross margin; no accretive action"
            if margin_protected_hold
            else "No distinct legal candidate is sufficiently better"
        )
        unit_label, unit_quantity, unit_pack_label = unit_basis.get(
            identity, (None, None, None)
        )
        base = {key: value for key, value in zip(KEYS, identity, strict=True)}
        lineage = {
            **evidence,
            "competitorMatchId": competitor_row.get("match_id") if competitor_row else None,
            "promotionGuardStatus": guard.get("guard_status"),
            "forecastPitEligible": forecast_row.get("pit_eligible"),
        }
        output.append(
            {
                **base,
                "product_name": response_row.get("product_name"),
                "category": response_row.get("category"),
                "category_label": response_row.get("category_label"),
                "department_id": response_row.get("department_id"),
                "channel_type": response_row.get("channel_type"),
                "recommendation_id": _identifier(base),
                "record_kind": "recommendation",
                "selectable": True,
                "action": action,
                "disposition": "recommended",
                "first_failure_reason": None if action != "Hold" else "NO_BETTER_LEGAL_CANDIDATE",
                "current_price_minor": current,
                "proposed_price_minor": proposed,
                "currency_code": currency,
                "expected_units_current": float(baseline_units),
                "expected_units_proposed": float(proposed_units),
                "expected_revenue_current_minor": int(current_score[2].quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)),
                "expected_revenue_proposed_minor": int(proposed_revenue.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)),
                "revenue_impact_minor": int(impact.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)),
                "margin_impact_minor": margin_impact,
                "margin_reason_code": margin_reason,
                "current_margin_pct": current_margin_pct,
                "expected_margin_pct": expected_margin_pct,
                "confidence": confidence,
                "confidence_label": _confidence_label(confidence),
                "priority": "Unassigned",
                "risk": _risk_label(change, confidence),
                "drivers": json.dumps([driver], separators=(",", ":")),
                "stock_cover_days": inventory_row.get("stock_cover_days"),
                "atp_units": inventory_row.get("atp_units"),
                "clearance_context_available": inventory_row.get(
                    "clearance_context_available"
                ),
                "competitor_price_minor": competitor_upper,
                "competitor_evidence_label": competitor_row.get("synthetic_label") if competitor_row else None,
                "synthetic_cost_minor": inventory_row.get("synthetic_cost_minor"),
                "synthetic_cost_method": inventory_row.get("synthetic_cost_method"),
                "cost_as_of": inventory_row.get("cost_as_of"),
                "pricing_unit_label": unit_label,
                "base_unit_quantity": (
                    float(unit_quantity) if unit_quantity is not None else None
                ),
                "pricing_pack_label": unit_pack_label,
                "forecast_expected_units": forecast_row.get("expected_units"),
                "forecast_best_case_units": forecast_row.get("best_case_units"),
                "forecast_worst_case_units": forecast_row.get("worst_case_units"),
                "forecast_horizon_weeks": forecast_row.get("forecast_horizon_weeks"),
                "forecast_scenario_semantics": forecast_row.get(
                    "forecast_scenario_semantics"
                ),
                "lineage": json.dumps(lineage, sort_keys=True, separators=(",", ":")),
            }
        )
    recommendations = pd.DataFrame(output)
    actionable = recommendations[
        (recommendations["record_kind"] == "recommendation")
        & (recommendations["action"] != "Hold")
    ]
    if not actionable.empty:
        ranks = actionable["revenue_impact_minor"].rank(method="first", pct=True)
        priorities = pd.Series("Low", index=actionable.index)
        priorities[ranks >= (2 / 3)] = "High"
        priorities[(ranks >= (1 / 3)) & (ranks < (2 / 3))] = "Medium"
        recommendations.loc[priorities.index, "priority"] = priorities
    recommendations.loc[recommendations["action"] == "Hold", "priority"] = "Low"
    recommendations["forecast_demand_label"] = None
    recommendation_mask = recommendations["record_kind"] == "recommendation"
    for _, indices in recommendations[recommendation_mask].groupby(
        ["market_id", "department_id"], dropna=False
    ).groups.items():
        values = pd.to_numeric(
            recommendations.loc[indices, "forecast_expected_units"], errors="coerce"
        )
        available = values.dropna()
        if available.empty:
            continue
        lower = float(available.quantile(1 / 3, interpolation="linear"))
        upper = float(available.quantile(2 / 3, interpolation="linear"))
        for index, value in values.items():
            if pd.isna(value):
                continue
            label = "Low" if value < lower else "Medium" if value < upper else "High"
            recommendations.at[index, "forecast_demand_label"] = label
    candidates_frame = pd.DataFrame(candidate_rows)
    if candidates_frame.empty:
        candidates_frame = pd.DataFrame(columns=CANDIDATE_COLUMNS)
    else:
        candidates_frame = candidates_frame.loc[:, list(CANDIDATE_COLUMNS)]
        candidates_frame = candidates_frame.sort_values(
            [*KEYS, "candidate_price_minor"]
        ).reset_index(drop=True)
    return (
        recommendations.sort_values(list(KEYS)).reset_index(drop=True),
        candidates_frame,
    )


__all__ = [
    "KEYS", "RECOMMENDATION_COLUMNS", "RecommendationError",
    "build_recommendations",
]
