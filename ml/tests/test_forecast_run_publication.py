from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml
from jsonschema import Draft202012Validator

from retail_ml.publish.run_artifacts import (
    ForecastPublicationError,
    derive_evaluation_predictions,
    derive_forecast_metrics,
    publish_forecast_run,
)
from retail_ml.policies.classification import load_classification_policy
from retail_ml.publish.verify import (
    ForecastRunVerificationError,
    verify_forecast_run,
)
from retail_ml.runtime.profile import resolve_ml_runtime_profile


def _full_schedule() -> pd.DataFrame:
    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        origin = first + timedelta(weeks=2 * origin_index)
        for horizon in range(1, 27):
            actual = float(10 + horizon % 3)
            rows.append(
                {
                    "forecast_origin": origin,
                    "target_week_start": origin + timedelta(weeks=horizon),
                    "market_id": "india-west",
                    "dept_id": "dept",
                    "category": "category",
                    "sku_id": "sku",
                    "store_id": "store",
                    "channel_id": "channel",
                    "horizon": horizon,
                    "actual_units": actual,
                    "yhat_p50": actual - 1,
                    "yhat_p90": actual + 2,
                    "confidence": 0.8,
                    "selected_model": "lightgbm_horizon_quantile",
                    "zero_share_52w": 0.1,
                    "naive_baseline": actual - 2,
                    "seasonal_naive_baseline": actual - 3,
                    "ma8_baseline": actual - 2,
                    "ma13_baseline": actual - 2,
                }
            )
    return pd.DataFrame(rows)


def _calibration() -> pd.DataFrame:
    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        scored_origin = first + timedelta(weeks=2 * origin_index)
        for horizon in range(1, 27):
            for scope, market_id in (
                ("global", ""),
                ("market", "india-west"),
            ):
                rows.append(
                    {
                        "scored_origin": scored_origin,
                        "scope": scope,
                        "market_id": market_id,
                        "horizon": horizon,
                        "sufficient": True,
                        "fallback": scope == "market",
                        "n_series": 100,
                        "n_origins": 8,
                        "n_rows": 800,
                        "actual_sum": 8000.0,
                        "p50_adjustment": 0.0,
                        "p90_adjustment": 0.0,
                    }
                )
    return pd.DataFrame(rows)


def _exceptions() -> pd.DataFrame:
    policy = _policies()["exceptions"]
    return pd.DataFrame(
        [
            {
                "sku_id": "sku",
                "store_id": "store",
                "channel_id": "channel",
                "exception_class": "new_product_sparse_history",
                "severity": "medium",
                "status": "open",
                "threshold": "zero_share_52w>0.60",
                "evidence": '{"policy":"fixture"}',
                "policy_id": policy["policyId"],
                "policy_semantic_fingerprint": policy[
                    "semanticFingerprint"
                ],
            }
        ]
    )


def _quality() -> pd.DataFrame:
    policy = _policies()["dataQuality"]
    return pd.DataFrame(
        [
            {
                "sku_id": "sku",
                "store_id": "store",
                "channel_id": "channel",
                "data_quality_class": "Good",
                "evidence": '{"policy":"fixture"}',
                "policy_id": policy["policyId"],
                "policy_semantic_fingerprint": policy[
                    "semanticFingerprint"
                ],
            }
        ]
    )


def _identity() -> dict[str, str]:
    return {
        "sourceSnapshotId": "a" * 64,
        "gateASemanticFingerprint": "b" * 64,
        "gateBSemanticFingerprint": "c" * 64,
        "publicationSemanticFingerprint": "d" * 64,
    }


def _policies() -> dict[str, dict[str, str]]:
    return load_classification_policy().bindings()


def _current_forecasts() -> pd.DataFrame:
    rows = []
    origin = date(2026, 1, 19)
    for horizon in range(1, 27):
        rows.append(
            {
                "forecast_origin": origin,
                "target_week_start": origin + timedelta(weeks=horizon),
                "market_id": "india-west",
                "dept_id": "dept",
                "category": "category",
                "sku_id": "sku",
                "store_id": "store",
                "channel_id": "channel",
                "horizon": horizon,
                "yhat_p50": 10.0,
                "yhat_p90": 12.0,
                "confidence": 0.8,
                "selected_model": "lightgbm_horizon_quantile",
                "shap_demand_trend": 1.0,
                "shap_seasonality": 0.5,
                "shap_price": -0.2,
                "shap_competitor_activity": 0.1,
                "shap_weather_local_events": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_additive_rows_and_fixed_metrics_agree() -> None:
    evaluation = _full_schedule()
    additive = derive_evaluation_predictions(evaluation)
    metrics = derive_forecast_metrics(evaluation)
    stored = metrics[
        (metrics["slice_type"] == "global")
        & (metrics["slice_id"] == "portfolio")
        & (metrics["horizon"] == 0)
        & (metrics["model_id"] == "champion")
    ].iloc[0]

    assert stored["abs_error_sum"] == additive["abs_error_sum"].sum()
    assert stored["actual_sum"] == additive["actual_sum"].sum()
    assert stored["coverage_hits"] == additive["coverage_hits"].sum()
    assert stored["n"] == additive["n"].sum()


def test_publisher_emits_schema_valid_rejected_candidate(tmp_path: Path) -> None:
    acceptance = {
        "schemaVersion": "retail-forecast-acceptance/v1",
        "passed": False,
        "global": {},
        "markets": {},
        "A5": {"passed": False},
    }
    output = tmp_path / "run"
    publication = publish_forecast_run(
        _full_schedule(),
        _calibration(),
        acceptance,
        _exceptions(),
        _quality(),
        output,
        current_forecasts=_current_forecasts(),
        classification_policies=_policies(),
        input_bundle=_identity(),
        feature_semantic_fingerprint="e" * 64,
        decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
        runtime_profile=resolve_ml_runtime_profile("safe"),
        stage_telemetry={"elapsedSeconds": "1.0"},
        mlflow_run_id="run-id",
    )
    manifest = json.loads(
        (output / "forecast-run-manifest.json").read_text(encoding="utf-8")
    )
    schema = yaml.safe_load(
        (
            Path(__file__).parents[2] / "contracts/ml/forecast-run.schema.yaml"
        ).read_text(encoding="utf-8")
    )

    Draft202012Validator(schema).validate(manifest)
    assert publication.lifecycle_status == "rejected"
    assert manifest["lifecycleStatus"] == "rejected"
    assert set(manifest["artifacts"]) == {
        "forecast_versions",
        "forecast_series",
        "forecast_drivers",
        "forecast_eval_predictions",
        "forecast_baseline_predictions",
        "forecast_metrics",
        "forecast_exceptions",
        "forecast_data_quality",
        "forecast_calibration",
        "forecast_acceptance",
    }
    verified = verify_forecast_run(output)
    assert verified.forecast_run_id == publication.forecast_run_id
    assert verified.lifecycle_status == "rejected"


def test_publisher_rejects_partial_schedule(tmp_path: Path) -> None:
    with pytest.raises(
        ForecastPublicationError,
        match="requires all horizons",
    ):
        publish_forecast_run(
            _full_schedule().query("horizon == 1"),
            _calibration(),
            {
                "schemaVersion": "retail-forecast-acceptance/v1",
                "passed": False,
            },
            _exceptions(),
            _quality(),
            tmp_path / "partial",
            current_forecasts=_current_forecasts(),
            classification_policies=_policies(),
            input_bundle=_identity(),
            feature_semantic_fingerprint="e" * 64,
            decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
            runtime_profile=resolve_ml_runtime_profile("safe"),
            stage_telemetry={},
            mlflow_run_id=None,
        )


def test_publisher_refuses_invalid_classification_policy_fingerprint(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ForecastPublicationError,
        match="invalid semanticFingerprint",
    ):
        publish_forecast_run(
            _full_schedule(),
            _calibration(),
            {
                "schemaVersion": "retail-forecast-acceptance/v1",
                "passed": False,
            },
            _exceptions(),
            _quality(),
            tmp_path / "ungoverned",
            current_forecasts=_current_forecasts(),
            classification_policies={
                **_policies(),
                "exceptions": {
                    "policyId": "fixture-exceptions/v1",
                    "semanticFingerprint": "not-a-fingerprint",
                },
            },
            input_bundle=_identity(),
            feature_semantic_fingerprint="e" * 64,
            decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
            runtime_profile=resolve_ml_runtime_profile("safe"),
            stage_telemetry={},
            mlflow_run_id=None,
        )


def test_verifier_rejects_mutated_artifact(tmp_path: Path) -> None:
    output = tmp_path / "run"
    publish_forecast_run(
        _full_schedule(),
        _calibration(),
        {
            "schemaVersion": "retail-forecast-acceptance/v1",
            "passed": False,
        },
        _exceptions(),
        _quality(),
        output,
        current_forecasts=_current_forecasts(),
        classification_policies=_policies(),
        input_bundle=_identity(),
        feature_semantic_fingerprint="e" * 64,
        decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
        runtime_profile=resolve_ml_runtime_profile("safe"),
        stage_telemetry={},
        mlflow_run_id=None,
    )
    target = output / "forecast_metrics.parquet"
    target.write_bytes(target.read_bytes() + b"mutation")

    with pytest.raises(
        ForecastRunVerificationError,
        match="byte size mismatch",
    ):
        verify_forecast_run(output)


def test_execution_profile_does_not_change_run_identity(tmp_path: Path) -> None:
    acceptance = {
        "schemaVersion": "retail-forecast-acceptance/v1",
        "passed": False,
    }
    common = {
        "classification_policies": _policies(),
        "input_bundle": _identity(),
        "feature_semantic_fingerprint": "e" * 64,
        "decision_as_of": datetime(2026, 1, 25, tzinfo=UTC),
        "mlflow_run_id": None,
    }
    safe = publish_forecast_run(
        _full_schedule(),
        _calibration(),
        acceptance,
        _exceptions(),
        _quality(),
        tmp_path / "safe",
        current_forecasts=_current_forecasts(),
        runtime_profile=resolve_ml_runtime_profile("safe"),
        stage_telemetry={"elapsed": "slow"},
        **common,
    )
    ultra = publish_forecast_run(
        _full_schedule(),
        _calibration(),
        acceptance,
        _exceptions(),
        _quality(),
        tmp_path / "ultra",
        current_forecasts=_current_forecasts(),
        runtime_profile=resolve_ml_runtime_profile("ultra-performance"),
        stage_telemetry={"elapsed": "fast"},
        **common,
    )

    assert safe.forecast_run_id == ultra.forecast_run_id
    assert safe.semantic_fingerprint == ultra.semantic_fingerprint
