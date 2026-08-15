"""P5-D20 / P5-D22 observational promotion-uplift estimator and disposition."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from retail_ml.pricing.promotion import (
    PromotionFoundationError,
    build_promotion_disposition,
    build_promotion_uplift,
    estimate_promotion_uplift,
    load_promotion_policy,
    load_promotion_uplift_policy,
)

ROOT = Path(__file__).resolve().parents[2]
UPLIFT_POLICY_PATH = ROOT / "contracts/pricing/promotion-uplift-policy.json"
PROTECTION_POLICY_PATH = ROOT / "contracts/pricing/promotion-protection-policy.json"


def _uplift_policy() -> dict:
    return load_promotion_uplift_policy(UPLIFT_POLICY_PATH)


def _protection_policy() -> dict:
    return load_promotion_policy(PROTECTION_POLICY_PATH)


def _weekly(
    control_units: list[int],
    control_revenue: list[int],
    episode_units: list[int],
    episode_revenue: list[int],
    *,
    wac_unit_cost_minor: float | None = 700.0,
    promo_id: str = "promo-x",
) -> pd.DataFrame:
    """A tidy weekly episode/control panel for one promotion (deterministic)."""

    monday = pd.Timestamp("2025-01-06")  # a Monday
    rows: list[dict] = []
    for index, (units, revenue) in enumerate(zip(control_units, control_revenue)):
        rows.append(
            {
                "market_id": "gulf-india", "promo_id": promo_id,
                "promo_name": "Trade scheme", "promo_type": "campaign",
                "role": "control", "week_start": monday + pd.Timedelta(weeks=index),
                "units": units, "net_sales_minor": revenue,
                "wac_unit_cost_minor": wac_unit_cost_minor,
            }
        )
    for index, (units, revenue) in enumerate(zip(episode_units, episode_revenue)):
        rows.append(
            {
                "market_id": "gulf-india", "promo_id": promo_id,
                "promo_name": "Trade scheme", "promo_type": "campaign",
                "role": "episode", "week_start": monday + pd.Timedelta(weeks=30 + index),
                "units": units, "net_sales_minor": revenue,
                "wac_unit_cost_minor": wac_unit_cost_minor,
            }
        )
    return pd.DataFrame(rows)


def _well_supported() -> pd.DataFrame:
    # 8 clean control weeks at ₹1000/unit, 4 episode weeks at ₹900/unit (10%
    # realised discount) with a clean +34% demand lift, WAC ₹700/unit.
    return _weekly(
        [100] * 8, [100_000] * 8, [134] * 4, [134 * 900] * 4,
    )


# --------------------------------------------------------------------------
# Policy load + fingerprint
# --------------------------------------------------------------------------


def test_uplift_policy_loads_and_freezes_estimator_contract() -> None:
    policy = _uplift_policy()
    assert policy["schemaVersion"] == "retail-promotion-uplift/v1"
    assert policy["horizonWeeks"] == 4
    assert policy["estimator"]["seed"] == 20260731
    assert policy["acceptance"]["minEpisodeWeeks"] == 3
    assert policy["acceptance"]["minControlWeeks"] == 6


def test_uplift_policy_rejects_tampered_fingerprint(tmp_path: Path) -> None:
    document = json.loads(UPLIFT_POLICY_PATH.read_text(encoding="utf-8"))
    document["acceptance"]["minEpisodeWeeks"] = 1  # tamper without re-fingerprinting
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PromotionFoundationError):
        load_promotion_uplift_policy(path)


# --------------------------------------------------------------------------
# 1 · Golden-vector estimator test (deterministic)
# --------------------------------------------------------------------------


def test_estimator_golden_vector_is_positive_and_deterministic() -> None:
    policy = _uplift_policy()
    weekly = _well_supported()
    result = estimate_promotion_uplift(weekly, policy=policy)
    assert len(result) == 1
    row = result.iloc[0]

    assert row["acceptance_status"] == "accepted"
    assert row["first_failure_reason"] is None
    # closed-form: uplift = 134/100 - 1 = 0.34
    assert row["expected_demand_uplift"] == pytest.approx(0.34)
    # constant series ⇒ every resample draw reproduces the point estimate
    assert row["uplift_low"] == pytest.approx(0.34)
    assert row["uplift_high"] == pytest.approx(0.34)
    assert row["confidence"] == pytest.approx(1.0)
    assert row["valid_draws"] == policy["estimator"]["resampleDraws"]
    assert row["numeric_result_rate"] == pytest.approx(1.0)
    # revenue uplift = 0.34 × ₹100,000 baseline weekly revenue × 4-week horizon
    assert row["revenue_uplift_minor"] == 136_000
    # margin = 136 incremental units × (₹900 promo price − ₹700 WAC)
    assert row["margin_impact_minor"] == 27_200
    assert row["margin_reason_code"] is None
    # All headline figures are strictly positive for a well-supported promotion.
    assert row["expected_demand_uplift"] > 0
    assert row["revenue_uplift_minor"] > 0
    assert row["margin_impact_minor"] > 0

    # deterministic: the frozen seed reproduces byte-identical output.
    again = estimate_promotion_uplift(weekly, policy=policy)
    pd.testing.assert_frame_equal(result, again)


def test_estimator_interval_brackets_the_point_under_noise() -> None:
    policy = _uplift_policy()
    # Noisy but consistently-positive episode weeks vs a stable baseline.
    control_units = [100, 98, 102, 101, 99, 100, 103, 97, 100, 101]
    episode_units = [150, 140, 160, 145, 155, 148]
    weekly = _weekly(
        control_units,
        [u * 1000 for u in control_units],
        episode_units,
        [u * 900 for u in episode_units],
    )
    row = estimate_promotion_uplift(weekly, policy=policy).iloc[0]
    assert row["acceptance_status"] == "accepted"
    assert row["uplift_low"] <= row["expected_demand_uplift"] <= row["uplift_high"]
    assert row["uplift_low"] > 0  # the whole interval stays positive
    assert 0.0 <= row["confidence"] <= 1.0


# --------------------------------------------------------------------------
# 2 · Acceptance-gate test (support + holdout)
# --------------------------------------------------------------------------


def test_under_supported_episodes_are_withheld_without_a_number() -> None:
    policy = _uplift_policy()
    weekly = _weekly([100] * 8, [100_000] * 8, [134] * 2, [134 * 900] * 2)
    row = estimate_promotion_uplift(weekly, policy=policy).iloc[0]
    assert row["acceptance_status"] == "withheld"
    assert row["first_failure_reason"] == "PROMOTION_UPLIFT_INSUFFICIENT_EPISODES"
    # No fabricated numeric claim survives a failed gate.
    assert pd.isna(row["expected_demand_uplift"])
    assert pd.isna(row["revenue_uplift_minor"])
    assert pd.isna(row["margin_impact_minor"])
    assert pd.isna(row["confidence"])


def test_under_supported_controls_are_withheld() -> None:
    policy = _uplift_policy()
    weekly = _weekly([100] * 4, [100_000] * 4, [134] * 4, [134 * 900] * 4)
    row = estimate_promotion_uplift(weekly, policy=policy).iloc[0]
    assert row["acceptance_status"] == "withheld"
    assert row["first_failure_reason"] == "PROMOTION_UPLIFT_INSUFFICIENT_CONTROLS"


def test_flat_promotion_is_withheld_as_non_positive() -> None:
    policy = _uplift_policy()
    # Episode demand equals baseline ⇒ no lift ⇒ no numeric claim.
    weekly = _weekly([100] * 8, [100_000] * 8, [100] * 4, [100 * 900] * 4)
    row = estimate_promotion_uplift(weekly, policy=policy).iloc[0]
    assert row["acceptance_status"] == "withheld"
    assert row["first_failure_reason"] == "PROMOTION_UPLIFT_NOT_POSITIVE"


def test_margin_dilutive_promotion_is_withheld_even_when_well_supported() -> None:
    policy = _uplift_policy()
    # Strong, well-supported +34% lift, but the promo price (₹650) sits below the
    # ₹700 WAC, so the incremental gross margin is negative — the profit guard
    # withholds it rather than counting a margin-dilutive lift as an opportunity.
    weekly = _weekly(
        [100] * 8, [100_000] * 8, [134] * 4, [134 * 650] * 4,
        wac_unit_cost_minor=700.0,
    )
    row = estimate_promotion_uplift(weekly, policy=policy).iloc[0]
    assert row["acceptance_status"] == "withheld"
    assert row["first_failure_reason"] == "PROMOTION_UPLIFT_MARGIN_DILUTION"
    # a withheld promotion exposes no numeric claim, positive or negative.
    assert pd.isna(row["expected_demand_uplift"])
    assert pd.isna(row["revenue_uplift_minor"])
    assert pd.isna(row["margin_impact_minor"])


def test_missing_cost_basis_withholds_margin_only_not_uplift() -> None:
    policy = _uplift_policy()
    weekly = _weekly(
        [100] * 8, [100_000] * 8, [134] * 4, [134 * 900] * 4,
        wac_unit_cost_minor=None,
    )
    row = estimate_promotion_uplift(weekly, policy=policy).iloc[0]
    assert row["acceptance_status"] == "accepted"
    assert row["revenue_uplift_minor"] == 136_000  # revenue survives
    assert pd.isna(row["margin_impact_minor"])
    assert row["margin_reason_code"] == "PROMOTION_MARGIN_COST_BASIS_MISSING"


def test_disposition_flips_positive_on_one_accepted_promotion() -> None:
    policy = _uplift_policy()
    protection = _protection_policy()
    accepted = estimate_promotion_uplift(_well_supported(), policy=policy)
    disposition = build_promotion_disposition(
        accepted, protection_policy=protection, uplift_policy=policy
    )
    assert disposition["packageDisposition"] == "positive"
    assert disposition["plannerAvailable"] is True
    assert disposition["firstFailureReason"] is None
    assert disposition["acceptedPromotionCount"] == 1
    assert disposition["allowedClaims"] == [
        "numeric_uplift", "promotion_margin", "promotion_simulation",
    ]
    # Frozen estimator parameters travel with the disposition for the Go layer.
    params = disposition["estimatorParameters"]
    assert params["seed"] == 20260731
    assert params["policyFingerprint"] == policy["policyFingerprint"]
    assert params["acceptance"]["minEpisodeWeeks"] == 3


def test_disposition_stays_negative_when_nothing_is_accepted() -> None:
    policy = _uplift_policy()
    protection = _protection_policy()
    withheld = estimate_promotion_uplift(
        _weekly([100] * 8, [100_000] * 8, [134] * 2, [134 * 900] * 2), policy=policy
    )
    disposition = build_promotion_disposition(
        withheld, protection_policy=protection, uplift_policy=policy
    )
    assert disposition["packageDisposition"] == "negative"
    assert disposition["plannerAvailable"] is False
    assert disposition["firstFailureReason"] == "PROMOTION_UPLIFT_INSUFFICIENT_EPISODES"
    assert disposition["allowedClaims"] == []


def test_empty_panel_yields_negative_planner_unsupported() -> None:
    policy = _uplift_policy()
    protection = _protection_policy()
    empty = estimate_promotion_uplift(
        pd.DataFrame(
            columns=[
                "market_id", "promo_id", "role", "week_start", "units",
                "net_sales_minor",
            ]
        ),
        policy=policy,
    )
    disposition = build_promotion_disposition(
        empty, protection_policy=protection, uplift_policy=policy
    )
    assert disposition["packageDisposition"] == "negative"
    assert disposition["firstFailureReason"] == "NO_ACCEPTED_PROMOTION_UPLIFT"


# --------------------------------------------------------------------------
# 3 · Privacy-boundary test (restricted stays restricted)
# --------------------------------------------------------------------------


def test_privacy_restricted_fields_stay_restricted_on_both_branches() -> None:
    policy = _uplift_policy()
    protection = _protection_policy()
    restricted = {"customer_targeting", "cannibalisation", "bundle_response", "pii"}

    accepted = estimate_promotion_uplift(_well_supported(), policy=policy)
    withheld = estimate_promotion_uplift(
        _weekly([100] * 8, [100_000] * 8, [134] * 2, [134 * 900] * 2), policy=policy
    )

    # cannibalisation is always an explicit privacy state, never a number/omission.
    assert (accepted["cannibalisation_risk"] == "PRIVACY_RESTRICTED").all()
    assert (withheld["cannibalisation_risk"] == "PRIVACY_RESTRICTED").all()

    for result in (accepted, withheld):
        disposition = build_promotion_disposition(
            result, protection_policy=protection, uplift_policy=policy
        )
        assert set(disposition["restrictedClaims"]) == restricted
        # even on the positive branch, no privacy field is ever an allowed claim.
        assert set(disposition["allowedClaims"]).isdisjoint(restricted)


# --------------------------------------------------------------------------
# 4 · End-to-end build against a curated fixture (scope + WAC + flip)
# --------------------------------------------------------------------------


def _seed_curated(database: Path) -> None:
    known = "2026-01-01T00:00:00Z"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA canonical_data")
        connection.execute(
            """
            CREATE TABLE canonical_data.promotions (
                market_id VARCHAR, promo_id VARCHAR, name VARCHAR, type VARCHAR,
                objective VARCHAR, offer_value DECIMAL(18,8), currency_code VARCHAR,
                start_date DATE, end_date DATE, segment_id VARCHAR, status VARCHAR,
                provenance_class VARCHAR, generation_method VARCHAR,
                known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.promotions VALUES "
            "('gulf-india','p1','Kharif trade','campaign',NULL,0.1,'INR',"
            "'2026-05-04','2026-05-31',NULL,'Completed','in',NULL,?,'native_observed')",
            [known],
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.promotion_merchandise_targets (
                market_id VARCHAR, promo_id VARCHAR, merch_scope_type VARCHAR,
                merch_scope_id VARCHAR, discount_pct DECIMAL(18,8),
                provenance_class VARCHAR, generation_method VARCHAR,
                known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.promotion_merchandise_targets VALUES "
            "('gulf-india','p1','sku','gulf-india:SKU-1',0.1,'in',NULL,?,'native_observed')",
            [known],
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.promotion_scopes (
                market_id VARCHAR, promo_id VARCHAR, scope_row_id VARCHAR,
                region VARCHAR, location_id VARCHAR, channel_id VARCHAR,
                known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.promotion_scopes VALUES "
            "('gulf-india','p1','s1',NULL,NULL,'retail',?,'native_observed')",
            [known],
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.products (
                sku_id VARCHAR, dept_id VARCHAR, category VARCHAR,
                known_as_of TIMESTAMPTZ
            )
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.products VALUES "
            "('gulf-india:SKU-1','lubricants','Engine Oil',?)",
            [known],
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.stores (
                store_id VARCHAR, market_id VARCHAR, region VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.stores VALUES "
            "('gulf-india:store-1','gulf-india','West')"
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.inventory_cost (
                sku_id VARCHAR, location_id VARCHAR, as_of_date DATE,
                wac_cost BIGINT, currency_code VARCHAR, on_hand_qty BIGINT,
                method VARCHAR, known_as_of TIMESTAMPTZ
            )
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.inventory_cost VALUES "
            "('gulf-india:SKU-1','gulf-india:store-1','2026-04-01',700,'INR',10,'WAC',?)",
            [known],
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.sales (
                sku_id VARCHAR, store_id VARCHAR, channel_id VARCHAR, date DATE,
                sales_version INTEGER, units BIGINT, net_sales_amount BIGINT,
                promo_flag BOOLEAN, known_as_of TIMESTAMPTZ
            )
            """
        )
        # 12 clean control weeks (Jan–Mar, baseline) + 4 lifted episode weeks (May).
        control_mondays = pd.date_range("2026-01-05", periods=12, freq="7D")
        episode_mondays = pd.date_range("2026-05-04", periods=4, freq="7D")
        rows = []
        for monday in control_mondays:
            rows.append(
                (
                    "gulf-india:SKU-1", "gulf-india:store-1", "retail",
                    monday.date(), 1, 100, 100_000, False, known,
                )
            )
        for monday in episode_mondays:
            rows.append(
                (
                    "gulf-india:SKU-1", "gulf-india:store-1", "retail",
                    monday.date(), 1, 150, 135_000, True, known,
                )
            )
        connection.executemany(
            "INSERT INTO canonical_data.sales VALUES (?,?,?,?,?,?,?,?,?)", rows
        )


def test_build_promotion_uplift_end_to_end_flips_positive(tmp_path: Path) -> None:
    database = tmp_path / "curated.duckdb"
    _seed_curated(database)
    uplift, disposition = build_promotion_uplift(
        database,
        decision_as_of="2026-07-31T18:30:00Z",
        protection_policy=_protection_policy(),
        uplift_policy=_uplift_policy(),
    )
    assert len(uplift) == 1
    row = uplift.iloc[0]
    assert row["promo_id"] == "p1"
    assert row["acceptance_status"] == "accepted"
    # observed lift = 150/100 - 1 = 0.5, recovered from the sales panel alone.
    assert row["expected_demand_uplift"] == pytest.approx(0.5)
    assert row["revenue_uplift_minor"] > 0
    assert row["margin_impact_minor"] > 0  # WAC join resolved the cost basis
    assert row["margin_reason_code"] is None

    assert disposition["packageDisposition"] == "positive"
    assert disposition["plannerAvailable"] is True
    assert disposition["acceptedPromotionCount"] == 1


def test_build_promotion_uplift_negative_when_feed_absent(tmp_path: Path) -> None:
    database = tmp_path / "empty.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA canonical_data")
    uplift, disposition = build_promotion_uplift(
        database,
        decision_as_of="2026-07-31T18:30:00Z",
        protection_policy=_protection_policy(),
        uplift_policy=_uplift_policy(),
    )
    assert uplift.empty
    assert disposition["packageDisposition"] == "negative"
    assert disposition["plannerAvailable"] is False
