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
            "policyId": "retail-forecast-data-quality/v1",
            "semanticFingerprint": (
                "3c80b69f40b268be64b2f9068d5c366"
                "bd192cebd878c8fbd179b8ea95b4df81c"
            ),
        },
    }


def test_data_quality_vectors_are_executable() -> None:
    policy = load_classification_policy()
    for vector in policy.data_quality["testVectors"]:
        row = _series_row()
        row.update(vector["input"])
        exceptions, quality, _ = classify_current_cycle(
            pd.DataFrame([row]),
            decision_as_of=DECISION_AS_OF,
            policy=policy,
        )
        assert quality.iloc[0]["data_quality_class"] == vector["expectedClass"]
        expected_exception = (
            {"data_quality_exception"}
            if vector["expectedClass"] == "Issue"
            else set()
        )
        assert set(exceptions["exception_class"]) == expected_exception


def test_exception_vectors_are_executable() -> None:
    policy = load_classification_policy()
    for vector in policy.exceptions["testVectors"]:
        row = _series_row()
        row.update(vector["input"])
        if vector["input"]["data_quality_class"] == "Issue":
            row["source_quality_critical_count"] = 1
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
