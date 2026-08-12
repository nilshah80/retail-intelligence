"""Origin-visible promotion protection and explicit Planner disposition."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import duckdb
import pandas as pd


class PromotionFoundationError(RuntimeError):
    """Promotion safety evidence is missing, ambiguous, or invalid."""


PROMOTION_COLUMNS = (
    "market_id", "sku_id", "store_id", "channel_id", "department_id",
    "category", "guard_status", "first_failure_reason",
    "applicable_promotion_ids", "selected_precedence",
)


def load_promotion_policy(path: str | Path) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("schemaVersion") != "retail-promotion-protection/v1":
        raise PromotionFoundationError("unsupported promotion protection policy")
    precedence = policy.get("merchandisePrecedence")
    if precedence != ["sku", "dept", "category"]:
        raise PromotionFoundationError("promotion merchandise precedence changed")
    if policy.get("scopeLogic") != {"withinRow": "and", "acrossRows": "or"}:
        raise PromotionFoundationError("promotion scope logic changed")
    horizon = policy.get("protectionHorizonDays")
    if type(horizon) is not int or horizon < 0:
        raise PromotionFoundationError("promotion protection horizon is invalid")
    return policy


def _geography_matches(scope: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    checks = (
        ("region", "region"),
        ("location_id", "store_id"),
        ("channel_id", "channel_id"),
    )
    for candidate_key, scope_key in checks:
        expected = candidate.get(candidate_key)
        if expected is not None and not pd.isna(expected) and str(expected) != "":
            if str(scope.get(scope_key) or "") != str(expected):
                return False
    return True


def assess_promotion_protection(
    pricing_scopes: pd.DataFrame,
    promotions: pd.DataFrame,
    targets: pd.DataFrame,
    geographic_scopes: pd.DataFrame,
    *,
    policy: Mapping[str, Any],
    feed_available: bool = True,
) -> pd.DataFrame:
    required = {
        "market_id", "sku_id", "store_id", "channel_id", "department_id",
        "category",
    }
    missing = sorted(required - set(pricing_scopes.columns))
    if missing:
        raise PromotionFoundationError(
            "pricing scopes lack: " + ", ".join(missing)
        )
    precedence = {name: len(policy["merchandisePrecedence"]) - index for index, name in enumerate(policy["merchandisePrecedence"])}
    rows: list[dict[str, Any]] = []
    for scope in pricing_scopes.to_dict("records"):
        identity = {key: scope[key] for key in sorted(required)}
        if not feed_available:
            rows.append(
                {
                    **identity,
                    "guard_status": "missing",
                    "first_failure_reason": policy["missingSafetyFeed"],
                    "applicable_promotion_ids": "[]",
                    "selected_precedence": None,
                }
            )
            continue
        market_promotions = promotions[promotions["market_id"] == scope["market_id"]]
        applicable: list[tuple[int, str]] = []
        for promotion in market_promotions.to_dict("records"):
            promotion_id = promotion["promo_id"]
            if str(promotion.get("known_as_of_evidence_grade", "")) in {
                "landing_backfill", "unknown", ""
            }:
                continue
            merchandise = targets[
                (targets["market_id"] == scope["market_id"])
                & (targets["promo_id"] == promotion_id)
            ]
            matched_levels: list[int] = []
            for target in merchandise.to_dict("records"):
                target_type = str(target["merch_scope_type"])
                expected = {
                    "sku": scope["sku_id"],
                    "category": scope["category"],
                    "dept": scope["department_id"],
                }.get(target_type)
                if expected is not None and str(target["merch_scope_id"]) == str(expected):
                    matched_levels.append(precedence[target_type])
            if not matched_levels:
                continue
            geography = geographic_scopes[
                (geographic_scopes["market_id"] == scope["market_id"])
                & (geographic_scopes["promo_id"] == promotion_id)
            ]
            if geography.empty or not any(
                _geography_matches(scope, candidate)
                for candidate in geography.to_dict("records")
            ):
                continue
            applicable.append((max(matched_levels), str(promotion_id)))
        if not applicable:
            rows.append(
                {
                    **identity,
                    "guard_status": "no_overlap",
                    "first_failure_reason": None,
                    "applicable_promotion_ids": "[]",
                    "selected_precedence": None,
                }
            )
            continue
        highest = max(level for level, _ in applicable)
        selected = sorted(identifier for level, identifier in applicable if level == highest)
        conflict = len(selected) > 1
        rows.append(
            {
                **identity,
                "guard_status": "conflict" if conflict else "applicable",
                "first_failure_reason": policy["equalPrecedenceConflict"] if conflict else None,
                "applicable_promotion_ids": json.dumps(selected, separators=(",", ":")),
                "selected_precedence": next(
                    name for name, value in precedence.items() if value == highest
                ),
            }
        )
    if not rows:
        return pd.DataFrame(columns=PROMOTION_COLUMNS)
    return pd.DataFrame(rows).sort_values(
        ["market_id", "sku_id", "store_id", "channel_id"]
    ).reset_index(drop=True)


def build_promotion_foundation(
    curated_database: str | Path,
    pricing_scopes: pd.DataFrame,
    *,
    decision_as_of: datetime | str,
    policy: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    database = Path(curated_database)
    if not database.is_file():
        raise PromotionFoundationError(f"curated database is absent: {database}")
    feed_available = True
    protection_through = (
        pd.Timestamp(decision_as_of) + pd.Timedelta(
            days=int(policy["protectionHorizonDays"])
        )
    ).date()
    with duckdb.connect(str(database), read_only=True) as connection:
        try:
            promotions = connection.execute(
                """
                SELECT * FROM canonical_data.promotions
                WHERE known_as_of <= ?::TIMESTAMPTZ
                  AND start_date <= ?::DATE
                  AND end_date >= ?::DATE
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id
                """,
                [decision_as_of, protection_through, decision_as_of],
            ).fetch_df()
            targets = connection.execute(
                """
                SELECT * FROM canonical_data.promotion_merchandise_targets
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id, merch_scope_type,
                                 merch_scope_id
                    ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id, merch_scope_type, merch_scope_id
                """,
                [decision_as_of],
            ).fetch_df()
            geography = connection.execute(
                """
                SELECT * FROM canonical_data.promotion_scopes
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id, scope_row_id
                    ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id, scope_row_id
                """,
                [decision_as_of],
            ).fetch_df()
        except duckdb.Error:
            feed_available = False
            promotions = pd.DataFrame(columns=["market_id", "promo_id", "known_as_of_evidence_grade"])
            targets = pd.DataFrame(columns=["market_id", "promo_id", "merch_scope_type", "merch_scope_id"])
            geography = pd.DataFrame(columns=["market_id", "promo_id", "region", "location_id", "channel_id"])
    guard = assess_promotion_protection(
        pricing_scopes,
        promotions,
        targets,
        geography,
        policy=policy,
        feed_available=feed_available,
    )
    disposition = {
        "schemaVersion": "retail-promotion-package-disposition/v1",
        "decisionId": int(policy["decisionId"]),
        "decisionDisposition": policy["decisionDisposition"],
        "packageDisposition": "negative",
        "plannerAvailable": False,
        "firstFailureReason": policy["plannerFirstFailureReason"],
        "safetyGuardInternal": True,
        "forbiddenClaims": [
            "numeric_uplift", "promotion_margin", "promotion_simulation",
            "customer_targeting", "cannibalisation", "bundle_response",
        ],
    }
    return guard, disposition


__all__ = [
    "PROMOTION_COLUMNS", "PromotionFoundationError", "assess_promotion_protection",
    "build_promotion_foundation", "load_promotion_policy",
]
