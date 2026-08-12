from pathlib import Path

import duckdb
import pandas as pd

from retail_ml.pricing.promotion import (
    assess_promotion_protection,
    build_promotion_foundation,
    load_promotion_policy,
)


ROOT = Path(__file__).resolve().parents[2]


def _policy():
    return load_promotion_policy(
        ROOT / "contracts/pricing/promotion-protection-policy.json"
    )


def test_policy_freezes_active_and_planned_protection_horizon() -> None:
    policy = _policy()
    assert policy["protectionHorizonDays"] == 28
    assert policy["merchandisePrecedence"] == ["sku", "dept", "category"]


def test_foundation_includes_planned_promotions_inside_four_week_window(
    tmp_path: Path,
) -> None:
    database = tmp_path / "pricing.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA canonical_data")
        connection.execute(
            """
            CREATE TABLE canonical_data.promotions (
                market_id VARCHAR, promo_id VARCHAR, known_as_of TIMESTAMPTZ,
                start_date DATE, end_date DATE,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO canonical_data.promotions VALUES
              ('gulf-india', 'inside', '2026-07-01T00:00:00Z',
               '2026-08-28', '2026-09-05', 'source_native'),
              ('gulf-india', 'outside', '2026-07-01T00:00:00Z',
               '2026-08-29', '2026-09-05', 'source_native')
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.promotion_merchandise_targets (
                market_id VARCHAR, promo_id VARCHAR, merch_scope_type VARCHAR,
                merch_scope_id VARCHAR, known_as_of TIMESTAMPTZ
            )
            """
        )
        connection.execute(
            """
            INSERT INTO canonical_data.promotion_merchandise_targets VALUES
              ('gulf-india', 'inside', 'sku', 'sku-1', '2026-07-01T00:00:00Z'),
              ('gulf-india', 'outside', 'sku', 'sku-1', '2026-07-01T00:00:00Z')
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.promotion_scopes (
                market_id VARCHAR, promo_id VARCHAR, scope_row_id VARCHAR,
                known_as_of TIMESTAMPTZ, region VARCHAR, location_id VARCHAR,
                channel_id VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO canonical_data.promotion_scopes VALUES
              ('gulf-india', 'inside', 'scope-1', '2026-07-01T00:00:00Z',
               NULL, NULL, 'retail'),
              ('gulf-india', 'outside', 'scope-1', '2026-07-01T00:00:00Z',
               NULL, NULL, 'retail')
            """
        )

    guard, _ = build_promotion_foundation(
        database,
        _scope(),
        decision_as_of="2026-07-31T00:00:00Z",
        policy=_policy(),
    )

    assert guard.iloc[0]["guard_status"] == "applicable"
    assert guard.iloc[0]["applicable_promotion_ids"] == '["inside"]'


def _scope() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "market_id": "gulf-india", "sku_id": "sku-1",
            "store_id": "gulf-india:store-1", "channel_id": "retail",
            "department_id": "lubricants", "category": "Engine Oil",
            "region": "West",
        }
    ])


def _promotion(identifier: str) -> dict[str, object]:
    return {
        "market_id": "gulf-india", "promo_id": identifier,
        "known_as_of_evidence_grade": "source_native",
    }


def test_empty_but_present_origin_visible_feed_means_no_overlap() -> None:
    result = assess_promotion_protection(
        _scope(),
        pd.DataFrame(columns=["market_id", "promo_id", "known_as_of_evidence_grade"]),
        pd.DataFrame(columns=["market_id", "promo_id", "merch_scope_type", "merch_scope_id"]),
        pd.DataFrame(columns=["market_id", "promo_id", "region", "location_id", "channel_id"]),
        policy=_policy(),
        feed_available=True,
    )
    assert result.iloc[0]["guard_status"] == "no_overlap"
    assert result.iloc[0]["first_failure_reason"] is None


def test_absent_feed_fails_closed() -> None:
    result = assess_promotion_protection(
        _scope(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
        policy=_policy(), feed_available=False,
    )
    assert result.iloc[0]["guard_status"] == "missing"
    assert result.iloc[0]["first_failure_reason"] == "PROMOTION_PROTECTION_MISSING"


def test_equal_precedence_promotions_conflict() -> None:
    promotions = pd.DataFrame([_promotion("promo-1"), _promotion("promo-2")])
    targets = pd.DataFrame([
        {"market_id": "gulf-india", "promo_id": promotion,
         "merch_scope_type": "sku", "merch_scope_id": "sku-1"}
        for promotion in ("promo-1", "promo-2")
    ])
    geography = pd.DataFrame([
        {"market_id": "gulf-india", "promo_id": promotion,
         "region": None, "location_id": None, "channel_id": "retail"}
        for promotion in ("promo-1", "promo-2")
    ])
    result = assess_promotion_protection(
        _scope(), promotions, targets, geography, policy=_policy()
    )

    assert result.iloc[0]["guard_status"] == "conflict"
    assert result.iloc[0]["first_failure_reason"] == "PROMOTION_CONFLICT"


def test_department_target_beats_broader_category_target() -> None:
    promotions = pd.DataFrame([_promotion("category-promo"), _promotion("dept-promo")])
    targets = pd.DataFrame([
        {
            "market_id": "gulf-india", "promo_id": "category-promo",
            "merch_scope_type": "category", "merch_scope_id": "Engine Oil",
        },
        {
            "market_id": "gulf-india", "promo_id": "dept-promo",
            "merch_scope_type": "dept", "merch_scope_id": "lubricants",
        },
    ])
    geography = pd.DataFrame([
        {
            "market_id": "gulf-india", "promo_id": promotion,
            "region": None, "location_id": None, "channel_id": "retail",
        }
        for promotion in ("category-promo", "dept-promo")
    ])

    result = assess_promotion_protection(
        _scope(), promotions, targets, geography, policy=_policy()
    )

    assert result.iloc[0]["guard_status"] == "applicable"
    assert result.iloc[0]["selected_precedence"] == "dept"
    assert result.iloc[0]["applicable_promotion_ids"] == '["dept-promo"]'


def test_scope_row_is_and_and_rows_are_or() -> None:
    promotions = pd.DataFrame([_promotion("promo-1")])
    targets = pd.DataFrame([
        {"market_id": "gulf-india", "promo_id": "promo-1",
         "merch_scope_type": "category", "merch_scope_id": "Engine Oil"}
    ])
    geography = pd.DataFrame([
        {"market_id": "gulf-india", "promo_id": "promo-1", "region": "North",
         "location_id": None, "channel_id": "retail"},
        {"market_id": "gulf-india", "promo_id": "promo-1", "region": "West",
         "location_id": "gulf-india:store-1", "channel_id": "retail"},
    ])
    result = assess_promotion_protection(
        _scope(), promotions, targets, geography, policy=_policy()
    )

    assert result.iloc[0]["guard_status"] == "applicable"
    assert result.iloc[0]["selected_precedence"] == "category"
