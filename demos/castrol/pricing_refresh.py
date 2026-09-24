"""Re-score affected demo pricing scopes after removing competitor evidence.

``prepare(conn, excluded_skus)`` reads the unmodified disposable database and
calculates new rows in memory. ``apply(conn, prepared, transform)`` writes them
after the caller's identity rewrite. Neither function commits or changes source
artifacts. The caller owns the disposable-database guard and transaction.

The accepted price-response models, source authority, forecast and inventory
evidence are reused. No model is fitted and no substitute competitor is made up.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any, Callable, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "contracts/guardrails/pricing_rules.yaml"
KEYS = ("market_id", "sku_id", "store_id", "channel_id")
ADAPTATION = {
    "kind": "disposable_demo_competitor_context_removed",
    "method": "existing_recommender_with_empty_competitor_bounds",
    "responseModelRefit": False,
    "sourceAuthorityRetained": True,
}
RECOMMENDATION_COLUMNS = (
    "bundle_id", "recommendation_id", *KEYS, "record_kind", "selectable",
    "action", "disposition", "first_failure_reason", "current_price_minor",
    "proposed_price_minor", "currency_code", "expected_units_current",
    "expected_units_proposed", "revenue_impact_minor", "margin_impact_minor",
    "margin_reason_code", "current_margin_pct", "expected_margin_pct",
    "pricing_unit_label", "base_unit_quantity", "pricing_pack_label",
    "confidence", "priority", "risk", "stock_cover_days",
    "competitor_price_minor", "details",
)
CANDIDATE_COLUMNS = (
    "bundle_id", *KEYS, "candidate_price_minor", "expected_units",
    "expected_revenue_minor", "eligible", "rejection_reason", "details",
)
INTEGER_COLUMNS = {
    "current_price_minor", "proposed_price_minor", "revenue_impact_minor",
    "margin_impact_minor", "competitor_price_minor", "candidate_price_minor",
    "expected_revenue_minor",
}


def _dependencies():
    # Use the repository's existing ML environment; no new dependency is needed.
    ml_source = str(ROOT / "ml/src")
    if ml_source not in sys.path:
        sys.path.insert(0, ml_source)
    import pandas as pd
    from retail_ml.pricing.policy import load_pricing_policy
    from retail_ml.pricing.postgres import _details, _field, _integer_field
    from retail_ml.pricing.recommendation import build_recommendations
    return pd, load_pricing_policy, _details, _field, _integer_field, build_recommendations


def _query(conn: Any, statement: str, parameters: tuple = ()) -> list[dict]:
    from psycopg.rows import dict_row
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(statement, parameters)
        return cursor.fetchall()


def _object(value: Any) -> dict:
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping):
        raise ValueError("Expected an existing pricing JSON object")
    return dict(value)


def _key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(row[key]) for key in KEYS)


def _forecast_context(conn: Any, evidence: Mapping[str, Any], pd: Any):
    """Mirror load_forecast_context's four-week aggregation from serving rows."""
    run_id = evidence.get("forecastRunId")
    if not run_id:
        raise ValueError("Affected pricing bundle has no source forecast run")
    frame = pd.DataFrame(_query(conn, """
        SELECT market_id, sku_id, store_id, channel_id, version_id,
               horizon_week, expected_units, yhat_p50, yhat_p90, confidence
        FROM retail_serving.forecast_series
        WHERE forecast_run_id = %s AND horizon_week BETWEEN 1 AND 4
    """, (run_id,)))
    if frame.empty:
        return pd.DataFrame(columns=[*KEYS, "expected_units", "pit_eligible"])
    spread = (frame["yhat_p90"] - frame["yhat_p50"]).clip(lower=0)
    frame["weekly_low_planning_bound"] = (frame["yhat_p50"] - spread).clip(lower=0)
    rows = []
    for identity, group in frame.groupby(list(KEYS), sort=True, dropna=False):
        if set(group["horizon_week"].astype(int)) != {1, 2, 3, 4}:
            continue
        versions = sorted(set(group["version_id"].astype(str)))
        if len(versions) != 1 or len(group) != 4:
            raise ValueError("Ambiguous original four-week forecast context")
        available = bool(group[["yhat_p50", "yhat_p90", "weekly_low_planning_bound"]].notna().all().all())
        confidence = pd.to_numeric(group["confidence"], errors="coerce").dropna()
        rows.append({
            **dict(zip(KEYS, map(str, identity), strict=True)),
            "expected_units": float(group["expected_units"].sum()),
            "best_case_units": float(group["yhat_p90"].sum()) if available else None,
            "worst_case_units": float(group["weekly_low_planning_bound"].sum()) if available else None,
            "yhat_p50": None, "yhat_p90": None,
            "confidence": float(confidence.min()) if not confidence.empty else None,
            "pit_eligible": False, "forecast_reason": "CURRENT_ORIGIN_NON_PIT",
            "forecast_horizon_weeks": 4,
            "forecast_scenario_semantics": "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles",
            "version_id": versions[0],
        })
    return pd.DataFrame(rows, columns=[*KEYS, "expected_units", "best_case_units", "worst_case_units", "yhat_p50", "yhat_p90", "confidence", "pit_eligible", "forecast_reason", "forecast_horizon_weeks", "forecast_scenario_semantics", "version_id"])


def _inventory_context(conn: Any, evidence: Mapping[str, Any], pd: Any):
    """Mirror load_inventory_context using the original accepted DB version."""
    run_id = evidence.get("inventoryRunId")
    versions = _query(conn, """
        SELECT inventory_version_id, decision_as_of
        FROM retail_serving.inventory_versions WHERE inventory_run_id = %s
    """, (run_id,))
    if len(versions) != 1:
        raise ValueError("Affected pricing bundle has no unique source inventory version")
    version = versions[0]
    rows = _query(conn, """
        SELECT p.market_id, p.sku_id, p.location_id AS store_id, p.atp_units,
               d.unit_cost_minor AS synthetic_cost_minor,
               d.cost_method AS synthetic_cost_method, d.currency_code,
               h.cover_days AS stock_cover_days,
               COALESCE(h.health_class IN ('stockout', 'critical', 'out_of_stock'), FALSE)
                   AS stock_risk_blocked,
               EXISTS (
                   SELECT 1 FROM retail_serving.inventory_ageing a
                   WHERE a.inventory_version_id = p.inventory_version_id
                     AND a.market_id = p.market_id AND a.location_id = p.location_id
                     AND a.sku_id = p.sku_id
               ) AS clearance_context_available
        FROM retail_serving.inventory_positions p
        LEFT JOIN retail_serving.inventory_sku_dimension d
          ON d.inventory_version_id = p.inventory_version_id
         AND d.market_id = p.market_id AND d.location_id = p.location_id AND d.sku_id = p.sku_id
        LEFT JOIN retail_serving.inventory_stock_health h
          ON h.inventory_version_id = p.inventory_version_id
         AND h.market_id = p.market_id AND h.location_id = p.location_id AND h.sku_id = p.sku_id
        WHERE p.inventory_version_id = %s AND p.location_kind = 'store'
    """, (version["inventory_version_id"],))
    cutoff = version["decision_as_of"].isoformat()
    for row in rows:
        row.update(cost_as_of=cutoff, cost_provenance="generated_source_native", client_actual_cost_minor=None)
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["market_id", "sku_id", "store_id"])
    if frame.duplicated(["market_id", "sku_id", "store_id"]).any():
        raise ValueError("Ambiguous original inventory context")
    return frame


def prepare(conn: Any, excluded_skus: Iterable[str]) -> dict[str, Any]:
    """Read and calculate before any brand rewrite; never write or commit."""
    pd, load_policy, details, _field, _integer_field, build = _dependencies()
    affected = _query(conn, """
        SELECT r.*, a.assessment, m.decision_as_of
        FROM retail_serving.price_recommendations r
        JOIN retail_serving.pricing_response_assessments a
          USING (bundle_id, market_id, sku_id, store_id, channel_id)
        JOIN retail_serving.pricing_materializations m USING (bundle_id)
        WHERE NOT (r.sku_id = ANY(%s::text[]))
          AND EXISTS (
              SELECT 1 FROM retail_serving.pricing_competitor_assessments c
              WHERE c.bundle_id = r.bundle_id AND c.market_id = r.market_id
                AND c.sku_id = r.sku_id AND c.competitor_id ~* %s
                AND (c.geo_scope_type = 'market'
                     OR (c.geo_scope_type = 'location' AND c.geo_scope_id = r.store_id))
          )
        ORDER BY r.bundle_id, r.market_id, r.sku_id, r.store_id, r.channel_id
    """, (sorted(set(excluded_skus)), "castrol|gulf"))
    grouped: dict[str, list[dict]] = {}
    for row in affected:
        grouped.setdefault(row["bundle_id"], []).append(row)
    prepared = {"bundles": [], "affectedScopeCount": len(affected), "policyPath": str(POLICY_PATH)}
    policy = load_policy(POLICY_PATH)
    for bundle_id, old_rows in grouped.items():
        old_by_key = {_key(row): row for row in old_rows}
        if len(old_by_key) != len(old_rows):
            raise ValueError("Duplicate original recommendation scopes")
        first_details = _object(old_rows[0]["details"])
        evidence = _object(first_details["lineage"])
        # Source fingerprints remain provenance. Row-specific competitor evidence
        # must not be inherited by a newly scored row or a withheld assessment.
        for name in ("competitorMatchId", "promotionGuardStatus", "forecastPitEligible"):
            evidence.pop(name, None)
        evidence["competitorMatchId"] = None
        evidence["demoAdaptation"] = ADAPTATION
        responses = []
        units = {}
        for old in old_rows:
            assessment = _object(old["assessment"])
            for key in KEYS:
                if str(assessment.get(key)) != str(old[key]):
                    raise ValueError("Stored response and recommendation identities differ")
            responses.append(assessment)
            original = _object(old["details"])
            row_lineage = _object(original["lineage"])
            for key in ("forecastRunId", "inventoryRunId", "sourceRunId", "publicationSemanticFingerprint"):
                if row_lineage.get(key) != evidence.get(key):
                    raise ValueError("Pricing bundle mixes original source authorities")
            units[_key(old)] = tuple(original.get(name, old.get(name)) for name in ("pricing_unit_label", "base_unit_quantity", "pricing_pack_label"))
        forecast = _forecast_context(conn, evidence, pd)
        inventory = _inventory_context(conn, evidence, pd)
        # Preserve original unrounded display/context values wherever they were
        # captured in recommendation JSON, rather than introducing SQL numeric
        # projection rounding into a rebuild. Previously withheld scopes obtain
        # their original contexts directly from the serving source tables above.
        for index, row in forecast.iterrows():
            old = old_by_key.get(_key(row))
            if old:
                original = _object(old["details"])
                for column, stored in (("expected_units", "forecast_expected_units"), ("best_case_units", "forecast_best_case_units"), ("worst_case_units", "forecast_worst_case_units")):
                    if original.get(stored) is not None:
                        forecast.at[index, column] = original[stored]
        old_inventory = {}
        for old in old_rows:
            original = _object(old["details"])
            if original.get("synthetic_cost_minor") is not None:
                old_inventory[tuple(str(old[k]) for k in KEYS[:3])] = original
        for index, row in inventory.iterrows():
            original = old_inventory.get(tuple(str(row[k]) for k in KEYS[:3]))
            if original:
                for column in ("synthetic_cost_minor", "synthetic_cost_method", "cost_as_of", "stock_cover_days", "atp_units", "clearance_context_available"):
                    if original.get(column) is not None:
                        inventory.at[index, column] = original[column]
        guards = [_object(row["details"]) for row in _query(conn, """
            SELECT details FROM retail_serving.pricing_promotion_protection WHERE bundle_id = %s
        """, (bundle_id,))]
        guard_frame = pd.DataFrame(guards) if guards else pd.DataFrame(columns=[*KEYS, "guard_status"])
        recommendations, candidates = build(
            pd.DataFrame(responses), forecast, inventory, pd.DataFrame(), guard_frame,
            pricing_policy=policy, evidence=evidence,
            decision_as_of=old_rows[0]["decision_as_of"].isoformat(), unit_basis=units,
        )
        new_rows = []
        for row in recommendations.to_dict("records"):
            old = old_by_key[_key(row)]
            if row["recommendation_id"] != old["recommendation_id"]:
                raise ValueError("Re-scoring changed an existing recommendation identifier")
            row["demo_adaptation"] = ADAPTATION
            new_rows.append(details(row))
        if len(new_rows) != len(old_rows):
            raise ValueError("Re-scoring failed to cover every affected scope")
        candidate_rows = []
        for row in candidates.to_dict("records"):
            row["demo_adaptation"] = ADAPTATION
            candidate_rows.append(details(row))
        prepared["bundles"].append({"bundle_id": bundle_id, "recommendations": new_rows, "candidates": candidate_rows})
    return prepared


def _rewrite(value: Any, transform: Callable[[Any], Any]) -> Any:
    """Apply the caller's string mapping, including JSON stored as a string."""
    if isinstance(value, dict):
        return {key: _rewrite(item, transform) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, transform) for item in value]
    if isinstance(value, str):
        if value.lstrip().startswith(("{", "[")):
            try:
                nested = json.loads(value)
            except (ValueError, TypeError):
                pass
            else:
                return json.dumps(_rewrite(nested, transform), sort_keys=True, separators=(",", ":"))
        return transform(value)
    return value


def apply(conn: Any, prepared: Mapping[str, Any], transform: Callable[[Any], Any]) -> dict[str, int]:
    """Replace only prepared scopes after identity rewrite; never commit."""
    from psycopg import sql
    from psycopg.types.json import Jsonb
    _pd, _load_policy, details, field, integer, _build = _dependencies()
    counts = {"recommendationsRefreshed": 0, "candidatesRebuilt": 0}
    with conn.cursor() as cursor:
        for bundle in prepared["bundles"]:
            # Bundle IDs are opaque retained source lineage, not brand identities.
            bundle_id = bundle["bundle_id"]
            recommendations = [_rewrite(row, transform) for row in bundle["recommendations"]]
            candidates = [_rewrite(row, transform) for row in bundle["candidates"]]
            cursor.executemany("""
                DELETE FROM retail_serving.pricing_price_candidates
                WHERE bundle_id = %s AND market_id = %s AND sku_id = %s
                  AND store_id = %s AND channel_id = %s
            """, [(bundle_id, *_key(row)) for row in recommendations])
            for table, columns, rows in (
                ("price_recommendations", RECOMMENDATION_COLUMNS, recommendations),
                ("pricing_price_candidates", CANDIDATE_COLUMNS, candidates),
            ):
                if not rows:
                    continue
                statement = sql.SQL("INSERT INTO retail_serving.{} ({}) VALUES ({})").format(
                    sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                )
                if table == "price_recommendations":
                    updates = sql.SQL(", ").join(sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name)) for name in columns if name not in ("bundle_id", "recommendation_id"))
                    statement += sql.SQL(" ON CONFLICT (bundle_id, recommendation_id) DO UPDATE SET ") + updates
                parameters = []
                for row in rows:
                    record = {**row, "bundle_id": bundle_id}
                    parameters.append(tuple(
                        Jsonb(details(row)) if name == "details" else
                        integer(record, name) if name in INTEGER_COLUMNS else
                        field(record, name)
                        for name in columns
                    ))
                cursor.executemany(statement, parameters)
            counts["recommendationsRefreshed"] += len(recommendations)
            counts["candidatesRebuilt"] += len(candidates)
    return counts
