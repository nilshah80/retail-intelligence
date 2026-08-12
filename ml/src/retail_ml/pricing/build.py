"""End-to-end construction of governed pricing artifact frames."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from retail_ml.pricing.competitor import (
    build_competitor_foundation,
    load_competitor_policy,
)
from retail_ml.pricing.panel import build_weekly_panel, load_response_policy
from retail_ml.pricing.policy import load_pricing_policy
from retail_ml.pricing.promotion import (
    build_promotion_foundation,
    load_promotion_policy,
)
from retail_ml.pricing.recommendation import KEYS, build_recommendations
from retail_ml.pricing.response import run_response_assessment
from retail_ml.publish.verify import verify_forecast_run


class PricingBuildError(RuntimeError):
    """Upstream artifacts cannot support the pricing build."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_artifact(root: Path, record: Mapping[str, Any]) -> Path:
    name = record.get("path")
    if not isinstance(name, str) or Path(name).name != name:
        raise PricingBuildError("upstream artifact path is unsafe")
    path = root / name
    if not path.is_file() or _sha256_file(path) != record.get("sha256"):
        raise PricingBuildError(f"upstream artifact is absent or corrupt: {name}")
    return path


def load_forecast_context(path: str | Path | None) -> tuple[pd.DataFrame, dict[str, str]]:
    if path is None:
        return pd.DataFrame(columns=[*KEYS, "expected_units", "pit_eligible"]), {}
    verified = verify_forecast_run(path)
    if verified.lifecycle_status != "accepted":
        raise PricingBuildError("pricing requires an accepted forecast run")
    frame = pd.read_parquet(verified.artifact_paths["forecast_series"])
    # The reference scenario is explicitly a four-week decision. Expected
    # volume is additive, so horizons 1..4 can be summed. Weekly P50/P90 values
    # are not additive quantiles; the high/low columns below are therefore
    # planning envelopes (sums of weekly bounds), with an explicit semantic
    # discriminator, and yhat_p50/yhat_p90 are deliberately withheld at the
    # four-week grain.
    frame = frame[frame["horizon_week"].isin([1, 2, 3, 4])].copy()
    frame["market_id"] = frame["sku_id"].astype(str).str.split(":", n=1).str[0]
    spread = (frame["yhat_p90"] - frame["yhat_p50"]).clip(lower=0)
    frame["weekly_low_planning_bound"] = (frame["yhat_p50"] - spread).clip(lower=0)
    rows: list[dict[str, Any]] = []
    for identity, group in frame.groupby(list(KEYS), sort=True, dropna=False):
        if set(group["horizon_week"].astype(int)) != {1, 2, 3, 4}:
            continue
        versions = sorted(set(group["version_id"].astype(str)))
        if len(versions) != 1:
            raise PricingBuildError("four-week forecast context spans multiple versions")
        intervals_available = bool(
            group[["yhat_p50", "yhat_p90", "weekly_low_planning_bound"]]
            .notna()
            .all()
            .all()
        )
        confidence = pd.to_numeric(group["confidence"], errors="coerce").dropna()
        rows.append(
            {
                **dict(zip(KEYS, (str(value) for value in identity), strict=True)),
                "expected_units": float(group["expected_units"].sum()),
                "best_case_units": (
                    float(group["yhat_p90"].sum()) if intervals_available else None
                ),
                "worst_case_units": (
                    float(group["weekly_low_planning_bound"].sum())
                    if intervals_available
                    else None
                ),
                "yhat_p50": None,
                "yhat_p90": None,
                "confidence": float(confidence.min()) if not confidence.empty else None,
                "pit_eligible": False,
                "forecast_reason": "CURRENT_ORIGIN_NON_PIT",
                "forecast_horizon_weeks": 4,
                "forecast_scenario_semantics": (
                    "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
                ),
                "version_id": versions[0],
            }
        )
    context = pd.DataFrame(rows)
    if context.empty:
        context = pd.DataFrame(
            columns=[
                *KEYS, "expected_units", "best_case_units", "worst_case_units",
                "yhat_p50", "yhat_p90", "confidence", "pit_eligible",
                "forecast_reason", "forecast_horizon_weeks",
                "forecast_scenario_semantics", "version_id",
            ]
        )
    return context, {
        "forecastRunId": verified.forecast_run_id,
        "forecastSemanticFingerprint": verified.semantic_fingerprint,
    }


def load_inventory_context(path: str | Path | None) -> tuple[pd.DataFrame, dict[str, str]]:
    if path is None:
        return pd.DataFrame(columns=["market_id", "sku_id", "store_id"]), {}
    root = Path(path).resolve()
    manifest_path = root / "inventory-run-manifest.json"
    if not manifest_path.is_file():
        raise PricingBuildError("inventory manifest is absent")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    capability = (manifest.get("capabilities") or {}).get(
        "inventory_replenishment_current_snapshot", {}
    )
    if capability.get("available") is not True:
        raise PricingBuildError("inventory current-snapshot capability is unavailable")
    objects = manifest.get("artifacts") or {}
    required = {
        "inventory_positions", "inventory_sku_dimension",
        "inventory_stock_health", "inventory_ageing",
    }
    if not required <= set(objects):
        raise PricingBuildError("inventory context artifact inventory is incomplete")
    decision_as_of = manifest.get("decisionAsOf")
    if not isinstance(decision_as_of, str) or not decision_as_of:
        raise PricingBuildError("inventory context has no decision-as-of cutoff")
    positions = pd.read_parquet(_safe_artifact(root, objects["inventory_positions"]))
    dimension = pd.read_parquet(_safe_artifact(root, objects["inventory_sku_dimension"]))
    health = pd.read_parquet(_safe_artifact(root, objects["inventory_stock_health"]))
    ageing = pd.read_parquet(_safe_artifact(root, objects["inventory_ageing"]))
    positions = positions[positions["location_kind"] == "store"].copy()
    dimension = dimension[dimension["location_kind"] == "store"].copy()
    context = positions.merge(
        dimension[
            [
                "market_id", "location_id", "sku_id", "unit_cost_minor",
                "cost_method", "currency_code", "product_name", "category",
            ]
        ],
        on=["market_id", "location_id", "sku_id"],
        how="left",
        validate="one_to_one",
    ).merge(
        health[["market_id", "location_id", "sku_id", "health_class", "cover_days"]],
        on=["market_id", "location_id", "sku_id"], how="left", validate="one_to_one",
    )
    clearance = set(
        zip(
            ageing["market_id"].astype(str), ageing["location_id"].astype(str),
            ageing["sku_id"].astype(str), strict=True,
        )
    )
    context["clearance_context_available"] = [
        (str(row.market_id), str(row.location_id), str(row.sku_id)) in clearance
        for row in context.itertuples()
    ]
    context["stock_risk_blocked"] = context["health_class"].astype(str).isin(
        {"stockout", "critical", "out_of_stock"}
    )
    context["synthetic_cost_minor"] = context["unit_cost_minor"]
    context["synthetic_cost_method"] = context["cost_method"]
    context["cost_provenance"] = "generated_source_native"
    # The inventory dimension does not carry the contributing receipt timestamp.
    # Its manifest cutoff is the exact latest time the accepted snapshot permits,
    # so expose that bounded snapshot date rather than inventing a row-level time.
    context["cost_as_of"] = decision_as_of
    context["client_actual_cost_minor"] = None
    context["stock_cover_days"] = context["cover_days"]
    context = context.rename(columns={"location_id": "store_id"})
    return context, {
        "inventoryRunId": str(manifest.get("inventoryRunId")),
        "inventorySemanticFingerprint": str(manifest.get("semanticFingerprint")),
    }


def build_pricing_artifacts(
    curated_database: str | Path,
    *,
    decision_as_of: str,
    response_policy_path: str | Path,
    pricing_policy_path: str | Path,
    competitor_policy_path: str | Path,
    competitor_truth_path: str | Path | None,
    promotion_policy_path: str | Path,
    forecast_run: str | Path | None,
    inventory_run: str | Path | None,
    bundle_kind: str,
    lineage: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], dict[str, Any]]:
    response_policy = load_response_policy(response_policy_path)
    pricing_policy = load_pricing_policy(pricing_policy_path)
    competitor_policy = load_competitor_policy(competitor_policy_path)
    promotion_policy = load_promotion_policy(promotion_policy_path)
    if bundle_kind not in {"response_rich", "evidence_sparse"}:
        raise PricingBuildError("bundle kind must be response_rich or evidence_sparse")
    panel = build_weekly_panel(
        curated_database,
        decision_as_of=decision_as_of,
        allow_empty=bundle_kind == "evidence_sparse",
    )
    response = run_response_assessment(panel, response_policy)
    pricing_scopes = panel[
        [*KEYS, "department_id", "category", "category_label", "region"]
    ].drop_duplicates(list(KEYS)).reset_index(drop=True)
    competitor_assessments, competitor_bounds, competitor_evaluation = (
        build_competitor_foundation(
            curated_database,
            decision_as_of=decision_as_of,
            policy=competitor_policy,
            truth_path=competitor_truth_path,
        )
    )
    promotion_guard, promotion_disposition = build_promotion_foundation(
        curated_database, pricing_scopes, decision_as_of=decision_as_of,
        policy=promotion_policy,
    )
    forecast, forecast_lineage = load_forecast_context(forecast_run)
    inventory, inventory_lineage = load_inventory_context(inventory_run)
    competitor_lineage = {
        "competitorTruthSha256": competitor_evaluation["truthSha256"],
        "competitorEvaluationProtocol": competitor_evaluation["protocolVersion"],
    }
    combined_lineage = {
        **lineage,
        **forecast_lineage,
        **inventory_lineage,
        **competitor_lineage,
    }
    recommendations, candidates = build_recommendations(
        response, forecast, inventory, competitor_bounds, promotion_guard,
        pricing_policy=pricing_policy, evidence=combined_lineage,
    )
    policy_paths = {
        "response": Path(response_policy_path), "pricing": Path(pricing_policy_path),
        "competitor": Path(competitor_policy_path), "promotion": Path(promotion_policy_path),
        "artifacts": Path(response_policy_path).resolve().parent / "artifacts.schema.json",
    }
    policy_identities = {
        name: _sha256_file(path.resolve()) for name, path in policy_paths.items()
    }
    accepted = int((response["disposition"] == "accepted").sum())
    actionable = int(recommendations["action"].isin(["Increase", "Decrease"]).sum())
    competitor_rows = len(competitor_assessments)
    eligible_competitor_bounds = int(competitor_assessments["bound_eligible"].sum())
    capabilities = {
        "priceResponse": {"available": accepted > 0, "acceptedRows": accepted},
        "priceRevenue": {"available": actionable > 0, "actionableRows": actionable},
        "priceMargin": {
            "available": bool(recommendations["margin_impact_minor"].notna().any()),
            "reasonCode": None if recommendations["margin_impact_minor"].notna().any() else "COST_NOT_CLIENT_ACTUAL",
        },
        "promotionPlanner": {
            "available": False,
            "reasonCode": promotion_disposition["firstFailureReason"],
        },
        "competitorMonitor": {
            "available": competitor_rows > 0,
            "descriptiveRows": competitor_rows,
            "syntheticDisclosureRequired": bool(
                competitor_rows
                and competitor_assessments["synthetic_label"].notna().any()
            ),
        },
        "competitorResponse": {
            "available": eligible_competitor_bounds > 0,
            "eligibleBounds": eligible_competitor_bounds,
            "reasonCode": (
                None
                if eligible_competitor_bounds > 0
                else competitor_evaluation.get("firstFailureReason")
                or "COMPETITOR_BOUND_UNAVAILABLE"
            ),
        },
        "syntheticMarginScenario": {
            "available": bool(recommendations["synthetic_cost_minor"].notna().any()),
            "displayLabel": "Synthetic demo margin — not client actual",
        },
    }
    artifacts: dict[str, Any] = {
        "pricing_panel": panel,
        "response_assessments": response,
        "price_candidates": candidates,
        "price_recommendations": recommendations,
        "competitor_assessments": competitor_assessments,
        "competitor_bounds": competitor_bounds,
        "competitor_evaluation": competitor_evaluation,
        "promotion_protection": promotion_guard,
        "promotion_disposition": promotion_disposition,
    }
    return artifacts, combined_lineage, policy_identities, capabilities


__all__ = [
    "PricingBuildError", "build_pricing_artifacts", "load_forecast_context",
    "load_inventory_context",
]
