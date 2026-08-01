from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from retail_ml.cli import main
from retail_ml.policies.classification import (
    ClassificationPolicyError,
    classify_current_cycle,
    load_classification_policy,
)


DECISION_AS_OF = datetime(2026, 7, 30, tzinfo=UTC)


def _series_row() -> dict[str, object]:
    return {
        "sku_id": "sku",
        "store_id": "store",
        "channel_id": "channel",
        "canonical_key_complete": True,
        "core_feature_missing_share": "0",
        "latest_actual_age_days": 0,
        "observation_coverage_13w": "1",
        "reconciliation_passed": True,
        "source_quality_critical_count": 0,
        "source_quality_warning_count": 0,
        "yhat_p50": "10",
        "yhat_p90": "12",
        "ma13_baseline": "10",
        "history_weeks": 52,
        "zero_share_52w": "0.10",
        "promotion_plan_available": False,
        "planned_promotion_uplift_pct": "0",
        "forecast_uplift_vs_ma13_pct": "0",
    }


def test_decision_60_policy_fingerprints_and_bindings_are_live() -> None:
    """The exceptions policy is unchanged; data quality now binds to promoted v2."""

    policy = load_classification_policy()

    assert policy.bindings() == {
        "exceptions": {
            "policyId": "retail-forecast-exceptions/v1",
            "semanticFingerprint": (
                "6a061db92136264217b8b3225b5f6dbb"
                "68a579c40333dcaf16f021e98d853fc8"
            ),
        },
        "dataQuality": {
            "policyId": "retail-forecast-data-quality/v2",
            "semanticFingerprint": (
                "e0baf3ef64568e0c7ad55bb6ca5d9157"
                "ba1a5238f64405d7a432b08bc2b1d0e5"
            ),
        },
    }


#: Which v1 vectors were triggered by a publication-scoped input rather than by
#: anything about the SeriesKey. Decision #76 promoted v2 on 2026-07-31, so these
#: no longer degrade a row: the finding stays visible in `global_limitations`.
#: Only this one. The v1 `watch` vector also sets three row-local triggers
#: (missing share 0.10, age 15 days, coverage 0.85), so v2 keeps it `Watch` on its
#: own evidence -- which is the point: the promotion narrowed the grain without
#: blunting the row-local battery.
V1_VECTORS_TRIGGERED_BY_PUBLICATION_SCOPE = {
    "critical-source-finding-dominates": "source_quality_critical_count",
}


def test_data_quality_vectors_run_under_the_promoted_grain() -> None:
    """v1's vectors still execute; two of them intentionally changed outcome.

    v1 is immutable and its vectors are kept, but the active path is now v2. A
    vector whose only non-Good input was publication-scoped must now leave the row
    `Good`, and one driven by row-local evidence must still degrade it. Asserting
    both directions is what stops the promotion from being read as a blanket
    downgrade of the quality battery.
    """

    policy = load_classification_policy()
    for vector in policy.data_quality["testVectors"]:
        row = _series_row()
        row.update(vector["input"])
        exceptions, quality, _ = classify_current_cycle(
            pd.DataFrame([row]),
            decision_as_of=DECISION_AS_OF,
            policy=policy,
        )
        observed = quality.iloc[0]["data_quality_class"]
        if vector["id"] in V1_VECTORS_TRIGGERED_BY_PUBLICATION_SCOPE:
            assert observed == "Good", vector["id"]
            evidence = json.loads(quality.iloc[0]["evidence"])
            assert evidence["global_limitations"], vector["id"]
            assert evidence["publication_quality_class"] != "Good", vector["id"]
        else:
            assert observed == vector["expectedClass"], vector["id"]
        expected_exception = (
            {"data_quality_exception"} if observed == "Issue" else set()
        )
        assert set(exceptions["exception_class"]) == expected_exception


def test_exception_vectors_are_executable() -> None:
    policy = load_classification_policy()
    for vector in policy.exceptions["testVectors"]:
        row = _series_row()
        row.update(vector["input"])
        if vector["input"]["data_quality_class"] == "Issue":
            # Under the promoted v2 grain a publication-scoped critical finding no
            # longer degrades a row, so force the Issue through row-local evidence
            # instead. The vector is exercising the exception battery, not the
            # quality grain.
            row["canonical_key_complete"] = False
        exceptions, _, _ = classify_current_cycle(
            pd.DataFrame([row]),
            decision_as_of=DECISION_AS_OF,
            policy=policy,
        )
        actual = [
            {
                "exceptionClass": item.exception_class,
                "severity": item.severity,
            }
            for item in exceptions.itertuples(index=False)
        ]
        assert actual == vector["expected"]


def test_unavailable_promotion_never_becomes_a_conflict() -> None:
    row = _series_row()
    row.update(
        {
            "promotion_plan_available": False,
            "planned_promotion_uplift_pct": "0.50",
            "forecast_uplift_vs_ma13_pct": "-0.50",
        }
    )
    exceptions, _, _ = classify_current_cycle(
        pd.DataFrame([row]),
        decision_as_of=DECISION_AS_OF,
    )

    assert "promotion_uplift_conflict" not in set(
        exceptions["exception_class"]
    )


def test_policy_tampering_fails_closed(tmp_path: Path) -> None:
    policy = load_classification_policy().document
    policy["exceptions"]["classes"]["high_under_forecast_risk"][
        "trigger"
    ] = "always"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(
        ClassificationPolicyError,
        match="exceptions policy fingerprint mismatch",
    ):
        load_classification_policy(path)


def test_duplicate_series_keys_fail_closed() -> None:
    row = _series_row()
    with pytest.raises(
        ClassificationPolicyError,
        match="one row per SeriesKey",
    ):
        classify_current_cycle(
            pd.DataFrame([row, row]),
            decision_as_of=DECISION_AS_OF,
        )


def test_classification_cli_writes_publisher_inputs(tmp_path: Path) -> None:
    source = tmp_path / "current-cycle.parquet"
    output = tmp_path / "classified"
    pd.DataFrame([_series_row()]).to_parquet(source, index=False)

    assert (
        main(
            [
                "classify",
                "--current-cycle",
                str(source),
                "--output-dir",
                str(output),
                "--decision-as-of",
                "2026-07-30T00:00:00Z",
            ]
        )
        == 0
    )
    assert (output / "forecast_exceptions.parquet").is_file()
    assert len(
        pd.read_parquet(output / "forecast_data_quality.parquet")
    ) == 1
    assert json.loads(
        (output / "classification-policies.json").read_text(encoding="utf-8")
    ) == load_classification_policy().bindings()


# --------------------------------------------------------------------------
# Exception policy v2 / decision #92. `P4-1` task 7.
# --------------------------------------------------------------------------

V2_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "ml"
    / "forecast-classification-policy-v2.json"
)


def _v2_policy():
    return load_classification_policy(V2_POLICY_PATH)


def _withheld_row() -> dict[str, object]:
    """A cold-start series whose interval stops at the calibrated boundary."""

    return {
        **_series_row(),
        "cohort": "cold_start",
        "interval_withheld_horizon_count": 22,
        "interval_unavailable_from_horizon": 5,
        "interval_unavailable_through_horizon": 26,
        "interval_unavailable_reason": "COLD_START_INTERVAL_UNCALIBRATED",
    }


def test_v2_loads_and_supersedes_v1_without_rewriting_it() -> None:
    policy = _v2_policy()
    assert policy.exceptions["policyId"] == "retail-forecast-exceptions/v2"
    assert policy.exceptions["supersedes"]["policyId"] == (
        "retail-forecast-exceptions/v1"
    )
    # v1 must remain loadable and unchanged: it is bound into every bundle
    # published before v2, and rewriting it would retroactively alter what those
    # bundles claim to have applied.
    v1 = load_classification_policy()
    assert v1.exceptions["policyId"] == "retail-forecast-exceptions/v1"
    assert "cold_start_interval_unavailable" not in v1.exceptions["classes"]


def test_the_interval_exception_emits_once_per_series_not_once_per_horizon() -> None:
    """22 withheld horizons produce one record, because the table has no horizon.

    forecast_exceptions is keyed on (version_id, sku_id, store_id, channel_id,
    exception_class). Per-horizon records would collide on that key rather than
    accumulate, so the range travels in the evidence instead.
    """

    exceptions, _, _ = classify_current_cycle(
        pd.DataFrame([_withheld_row()]),
        decision_as_of=DECISION_AS_OF,
        policy=_v2_policy(),
    )
    interval = exceptions[
        exceptions["exception_class"] == "cold_start_interval_unavailable"
    ]
    assert len(interval) == 1, "the withheld interval must emit exactly one record"
    evidence = json.loads(interval.iloc[0]["evidence"])
    observed = evidence["observed"]
    assert observed["unavailableFromHorizon"] == 5
    assert observed["unavailableThroughHorizon"] == 26
    assert observed["withheldHorizonCount"] == 22
    assert observed["calibratedMaxHorizon"] == 4
    assert observed["reasonCode"] == "COLD_START_INTERVAL_UNCALIBRATED"
    assert evidence["policy_id"] == "retail-forecast-exceptions/v2"


def test_a_series_with_a_full_range_interval_emits_no_interval_exception() -> None:
    row = {
        **_series_row(),
        "cohort": "established_history",
        "interval_withheld_horizon_count": 0,
        "interval_unavailable_from_horizon": None,
        "interval_unavailable_through_horizon": None,
        "interval_unavailable_reason": None,
    }
    exceptions, _, _ = classify_current_cycle(
        pd.DataFrame([row]),
        decision_as_of=DECISION_AS_OF,
        policy=_v2_policy(),
    )
    assert "cold_start_interval_unavailable" not in set(
        exceptions["exception_class"]
    )


def test_a_frame_without_interval_columns_classifies_exactly_as_before() -> None:
    """A pre-#92 frame must not be read as asserting a full-range interval."""

    exceptions, _, _ = classify_current_cycle(
        pd.DataFrame([_series_row()]),
        decision_as_of=DECISION_AS_OF,
        policy=_v2_policy(),
    )
    assert "cold_start_interval_unavailable" not in set(
        exceptions["exception_class"]
    )


def test_a_withheld_range_inside_the_calibrated_band_is_refused() -> None:
    """h4 and below is calibrated, so a withholding there is a different defect.

    Publishing it under #92's class would make the h4 boundary unfalsifiable: any
    coverage failure could be relabelled as a governed capability limit.
    """

    row = {**_withheld_row(), "interval_unavailable_from_horizon": 3}
    with pytest.raises(ClassificationPolicyError, match="calibrated"):
        classify_current_cycle(
            pd.DataFrame([row]),
            decision_as_of=DECISION_AS_OF,
            policy=_v2_policy(),
        )


def test_an_ungoverned_reason_code_is_refused() -> None:
    row = {**_withheld_row(), "interval_unavailable_reason": "SOMETHING_ELSE"}
    with pytest.raises(ClassificationPolicyError, match="reason code"):
        classify_current_cycle(
            pd.DataFrame([row]),
            decision_as_of=DECISION_AS_OF,
            policy=_v2_policy(),
        )


def test_an_inverted_withheld_range_is_refused() -> None:
    row = {
        **_withheld_row(),
        "interval_unavailable_from_horizon": 26,
        "interval_unavailable_through_horizon": 5,
    }
    with pytest.raises(ClassificationPolicyError):
        classify_current_cycle(
            pd.DataFrame([row]),
            decision_as_of=DECISION_AS_OF,
            policy=_v2_policy(),
        )
