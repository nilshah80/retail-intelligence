"""PP3-B6: signal admissibility screens and decision #76 quality policy v2.

The v2 tests are written against the failure v1 actually exhibits -- three
publication-level scalars broadcast onto every row -- rather than against v2's
own structure, so a regression that reintroduces the broadcast fails here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from retail_ml.diagnostics.signals import (
    MIN_ADDRESSABLE_ERROR_SHARE_PCT,
    REASON_GRAIN_ABOVE_SERIESKEY,
    REASON_IMMATERIAL,
    REASON_NO_HISTORICAL_REPLAY,
    REASON_TARGET_DERIVED,
    SCREENS,
    VERDICT_ADMISSIBLE,
    VERDICT_REJECTED,
    SignalScreenError,
    disposition,
    screen_grain,
    screen_leakage,
    screen_materiality,
    screen_report,
    screen_temporal,
)
from retail_ml.policies.quality_v2 import (
    GOOD,
    ISSUE,
    POLICY_ID,
    PUBLICATION_SCOPED_CHECKS,
    ROW_DIMENSIONS,
    STATUS,
    WATCH,
    QualityPolicyV2Error,
    classify_publication,
    classify_row,
    present,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = REPO_ROOT / "contracts/ml/forecast-quality-policy-candidate.json"


def _clean_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "canonical_key_complete": True,
        "row_reconciliation_passed": True,
        "core_feature_missing_share": Decimal("0.00"),
        "latest_actual_age_days": 7,
        "observation_coverage_13w": Decimal("1.00"),
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Signal admissibility screens.
# ---------------------------------------------------------------------------
def test_a_landing_backfilled_grade_cannot_enter_a_historical_backtest() -> None:
    """Serving-eligible is not replay-eligible; the promotion family is both."""

    result = screen_temporal(["landing_backfill"], repository_root=REPO_ROOT)

    assert result["passed"] is False
    assert result["reasonCode"] == REASON_NO_HISTORICAL_REPLAY
    assert result["replayIneligibleGrades"] == ["landing_backfill"]


def test_a_natively_observed_grade_passes_the_temporal_screen() -> None:
    result = screen_temporal(
        ["native_observed", "native_extracted"], repository_root=REPO_ROOT
    )

    assert result["passed"] is True
    assert result["reasonCode"] is None


def test_an_unknown_grade_raises_rather_than_passing() -> None:
    """A grade the frozen policy does not define must not be assumed benign."""

    with pytest.raises(SignalScreenError, match="absent from the frozen policy"):
        screen_temporal(["invented_grade"], repository_root=REPO_ROOT)


def test_a_warehouse_grain_signal_cannot_describe_a_store() -> None:
    result = screen_grain(
        ["mkt:newark-dc", "mkt:brooklyn-mfc"],
        ["mkt:ny-manhattan", "mkt:ny-brooklyn"],
        label="store_id",
    )

    assert result["passed"] is False
    assert result["reasonCode"] == REASON_GRAIN_ABOVE_SERIESKEY
    assert result["overlappingKeys"] == 0


def test_a_matching_grain_passes() -> None:
    result = screen_grain(
        ["mkt:ny-manhattan"], ["mkt:ny-manhattan", "mkt:ny-brooklyn"], label="store_id"
    )

    assert result["passed"] is True
    assert result["overlappingKeys"] == 1


def test_a_field_that_reproduces_the_target_boundary_is_rejected() -> None:
    """The assortment exit date: agrees with the last observed sale."""

    last_sale = pd.to_datetime(
        ["2025-01-05", "2025-02-09", "2025-03-16", "2025-04-20"]
    )
    active_to = pd.to_datetime(
        ["2025-01-05", "2025-02-09", "2025-03-18", "2025-04-20"]
    )

    result = screen_leakage(active_to, last_sale)

    assert result["passed"] is False
    assert result["reasonCode"] == REASON_TARGET_DERIVED
    assert result["exactAgreementShare"] == pytest.approx(0.75)


def test_an_independent_date_passes_the_leakage_screen() -> None:
    last_sale = pd.to_datetime(["2025-01-05", "2025-02-09", "2025-03-16"])
    planned_exit = pd.to_datetime(["2025-06-30", "2025-09-30", "2025-12-31"])

    result = screen_leakage(planned_exit, last_sale)

    assert result["passed"] is True
    assert result["reasonCode"] is None


def test_a_signal_below_the_acceptance_floor_skips_its_ablation() -> None:
    """Decision #75's floor bounds the gain, so the retrain is not run."""

    frame = pd.DataFrame(
        {
            "actual_units": [100.0] * 100,
            "yhat_p50": [90.0] * 100,
        }
    )
    active = pd.Series([True] * 3 + [False] * 97)

    result = screen_materiality(frame, active=active)

    assert result["addressableErrorSharePct"] == pytest.approx(3.0)
    assert result["addressableErrorSharePct"] < MIN_ADDRESSABLE_ERROR_SHARE_PCT
    assert result["passed"] is False
    assert result["reasonCode"] == REASON_IMMATERIAL


def test_a_material_signal_passes_and_earns_an_ablation() -> None:
    frame = pd.DataFrame({"actual_units": [100.0] * 100, "yhat_p50": [90.0] * 100})
    active = pd.Series([True] * 30 + [False] * 70)

    material = screen_materiality(frame, active=active)
    verdict = disposition(
        "hypothetical",
        screens=[
            screen_temporal(["native_observed"], repository_root=REPO_ROOT),
            material,
        ],
    )

    assert material["passed"] is True
    assert verdict["verdict"] == VERDICT_ADMISSIBLE
    assert verdict["ablationRequired"] is True


def test_the_first_failed_screen_is_the_recorded_reason() -> None:
    """Cost order matters: a cheap terminal failure must not be overwritten."""

    verdict = disposition(
        "promotion_plan",
        screens=[
            screen_materiality(
                pd.DataFrame({"actual_units": [10.0], "yhat_p50": [1.0]}),
                active=pd.Series([True]),
            ),
            screen_temporal(["landing_backfill"], repository_root=REPO_ROOT),
        ],
    )

    assert verdict["verdict"] == VERDICT_REJECTED
    assert verdict["firstFailedScreen"] == "temporal"
    assert verdict["reasonCode"] == REASON_NO_HISTORICAL_REPLAY
    assert [item["screen"] for item in verdict["screens"]] == [
        screen for screen in SCREENS if screen in {"temporal", "materiality"}
    ]


def test_the_report_never_leaves_a_rejection_unexplained() -> None:
    report = screen_report(
        [
            disposition(
                "a", screens=[screen_temporal(["landing_backfill"], repository_root=REPO_ROOT)]
            ),
            disposition(
                "b", screens=[screen_temporal(["native_observed"], repository_root=REPO_ROOT)]
            ),
        ]
    )

    assert report["rejected"] == {"a": REASON_NO_HISTORICAL_REPLAY}
    assert report["admissible"] == ["b"]
    for signal_id, reason in report["rejected"].items():
        assert reason, f"{signal_id} was rejected without a reason code"


def test_the_shipped_screen_record_matches_the_module() -> None:
    """The emitted evidence must be readable by the same contract that made it."""

    path = REPO_ROOT / "contracts/evidence/optional-signal-admissibility.json"
    if not path.exists():
        pytest.skip("screen record not generated in this checkout")
    record = json.loads(path.read_text())

    assert record["screenOrder"] == list(SCREENS)
    assert record["acceptanceFloorPct"] == MIN_ADDRESSABLE_ERROR_SHARE_PCT
    for signal in record["signals"]:
        if signal["verdict"] == VERDICT_REJECTED:
            assert signal["reasonCode"], signal["signalId"]
            assert signal["firstFailedScreen"] in SCREENS


# ---------------------------------------------------------------------------
# Decision #76 quality policy v2.
# ---------------------------------------------------------------------------
def test_v2_is_active_and_supersedes_v1_without_erasing_it() -> None:
    """Promoted 2026-07-31; v1 stays immutable rather than being rewritten."""

    contract = json.loads(CANDIDATE.read_text())

    assert STATUS == "active"
    assert contract["status"] == "active"
    assert contract["activePolicyId"] == POLICY_ID
    assert contract["supersedes"] == "retail-forecast-data-quality/v1"
    # The promotion has to carry its evidence, or a later reader cannot tell a
    # reviewed promotion from a convenient one.
    assert "fr_463f53be6353e481" in contract["promotionEvidence"]
    assert "immutable" in contract["v1Disposition"]


def test_one_global_warning_does_not_degrade_a_clean_row() -> None:
    """The exact v1 defect decision #76 names."""

    row = classify_row(**_clean_row())
    publication = classify_publication(
        critical_count=0, warning_count=1, reconciliation_passed=True
    )
    combined = present(row, publication)

    assert row["row_quality_class"] == GOOD
    assert publication["publication_quality_class"] == WATCH
    assert combined["effective_display_class"] == WATCH
    assert combined["degradedBy"] == ["publication"]


def test_the_global_warning_is_never_dropped_to_protect_the_row() -> None:
    """The opposite failure, and the more dangerous one downstream."""

    publication = classify_publication(
        critical_count=2, warning_count=3, reconciliation_passed=False
    )
    combined = present(classify_row(**_clean_row()), publication)

    codes = {entry["code"] for entry in combined["global_limitations"]}
    assert codes == {
        "SOURCE_QUALITY_CRITICAL",
        "SOURCE_QUALITY_WARNING",
        "PUBLICATION_RECONCILIATION_FAILED",
    }
    assert combined["row_quality_class"] == GOOD
    assert combined["effective_display_class"] == ISSUE


def test_no_publication_scoped_check_appears_as_a_row_dimension() -> None:
    """Structural proof the broadcast cannot come back."""

    row = classify_row(**_clean_row())

    assert set(row["dimensions"]) == set(ROW_DIMENSIONS)
    for check in PUBLICATION_SCOPED_CHECKS:
        assert check not in row["dimensions"]


def test_a_stale_row_is_attributed_to_the_row_not_the_publication() -> None:
    row = classify_row(**_clean_row(latest_actual_age_days=30))
    publication = classify_publication(
        critical_count=0, warning_count=0, reconciliation_passed=True
    )
    combined = present(row, publication)

    assert row["row_quality_class"] == ISSUE
    assert row["degradedDimensions"] == ["freshness"]
    assert combined["degradedBy"] == ["row"]
    assert combined["global_limitations"] == []


def test_each_row_dimension_is_reported_separately() -> None:
    """One degraded dimension must not mask another."""

    row = classify_row(
        **_clean_row(
            core_feature_missing_share=Decimal("0.30"),
            observation_coverage_13w=Decimal("0.50"),
        )
    )

    assert row["dimensions"]["missingness"]["outcome"] == ISSUE
    assert row["dimensions"]["coverage"]["outcome"] == ISSUE
    assert row["dimensions"]["freshness"]["outcome"] == GOOD
    assert row["degradedDimensions"] == ["coverage", "missingness"]


def test_an_unevaluated_row_reconciliation_is_a_third_state() -> None:
    row = classify_row(**_clean_row(row_reconciliation_passed=None))
    dimension = row["dimensions"]["reconciliation"]

    assert dimension["state"] == "not_evaluated"
    assert dimension["observed"] is None
    assert row["row_quality_class"] == GOOD


def test_thresholds_are_unchanged_from_v1() -> None:
    """v2 changes grain, not strictness, so a v1/v2 diff measures one thing."""

    v1 = json.loads(
        (REPO_ROOT / "contracts/ml/forecast-classification-policy.json").read_text()
    )["dataQuality"]["checks"]
    v2 = json.loads(CANDIDATE.read_text())["rowDimensions"]

    assert v2["missingness"]["issue"] == v1["core_feature_missing_share"]["issue"]
    assert v2["missingness"]["watch"] == v1["core_feature_missing_share"]["watch"]
    assert v2["freshness"]["issue"] == v1["latest_actual_age_days"]["issue"]
    assert v2["freshness"]["watch"] == v1["latest_actual_age_days"]["watch"]
    assert v2["coverage"]["issue"] == v1["observation_coverage_13w"]["issue"]
    assert v2["coverage"]["watch"] == v1["observation_coverage_13w"]["watch"]


def test_the_candidate_test_vectors_hold() -> None:
    contract = json.loads(CANDIDATE.read_text())

    for vector in contract["testVectors"]:
        row_input = dict(vector["row"])
        row_input["core_feature_missing_share"] = Decimal(
            row_input["core_feature_missing_share"]
        )
        row_input["observation_coverage_13w"] = Decimal(
            row_input["observation_coverage_13w"]
        )
        row = classify_row(**row_input)
        publication = classify_publication(**vector["publication"])
        combined = present(row, publication)
        expected = vector["expected"]

        assert row["row_quality_class"] == expected["row_quality_class"], vector["id"]
        assert (
            publication["publication_quality_class"]
            == expected["publication_quality_class"]
        ), vector["id"]
        assert (
            combined["effective_display_class"] == expected["effective_display_class"]
        ), vector["id"]
        assert combined["degradedBy"] == expected["degradedBy"], vector["id"]
        assert (
            publication["limitationCount"] == expected["globalLimitationCount"]
        ), vector["id"]


def test_out_of_domain_quality_inputs_are_refused() -> None:
    with pytest.raises(QualityPolicyV2Error, match="outside \\[0, 1\\]"):
        classify_row(**_clean_row(observation_coverage_13w=Decimal("1.5")))
    with pytest.raises(QualityPolicyV2Error, match="negative"):
        classify_row(**_clean_row(latest_actual_age_days=-1))
    with pytest.raises(QualityPolicyV2Error, match="cannot be negative"):
        classify_publication(
            critical_count=-1, warning_count=0, reconciliation_passed=True
        )


def test_the_policy_id_is_stable_across_the_module_and_contract() -> None:
    contract = json.loads(CANDIDATE.read_text())

    assert POLICY_ID == contract["policyId"]
    assert POLICY_ID == contract["activePolicyId"]
