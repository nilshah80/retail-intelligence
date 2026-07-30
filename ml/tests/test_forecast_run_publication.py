from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
import yaml
from jsonschema import Draft202012Validator

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.models.backtest import evaluate_acceptance
from retail_ml.models.confidence import forecast_confidence
from retail_ml.publish.run_artifacts import (
    ARTIFACT_SCHEMAS,
    RUN_VOLATILE_POINTERS,
    ForecastPublicationError,
    _frame_semantic_fingerprint,
    _json_semantic_fingerprint,
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
                    "confidence": float(
                        forecast_confidence(actual - 1, actual + 2)
                    ),
                    "selected_model": "lightgbm_horizon_quantile",
                    "zero_share_52w": 0.1,
                    "naive_baseline": actual - 2,
                    "seasonal_naive_baseline": actual - 3,
                    "ma8_baseline": actual - 2,
                    "ma13_baseline": actual - 2,
                }
            )
    return pd.DataFrame(rows)


def _accepted_schedule() -> pd.DataFrame:
    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        origin = first + timedelta(weeks=2 * origin_index)
        for horizon in range(1, 27):
            actual = float(10 + horizon % 3)
            for series_index in range(100):
                p50 = actual - 1
                p90 = actual + 2 if series_index % 10 else actual - 0.5
                rows.append(
                    {
                        "forecast_origin": origin,
                        "target_week_start": origin + timedelta(weeks=horizon),
                        "market_id": "india-west",
                        "dept_id": "dept",
                        "category": "category",
                        "sku_id": f"sku-{series_index:03d}",
                        "store_id": "store",
                        "channel_id": "channel",
                        "horizon": horizon,
                        "actual_units": actual,
                        "yhat_p50": p50,
                        "yhat_p90": p90,
                        "confidence": float(forecast_confidence(p50, p90)),
                        "selected_model": "lightgbm_horizon_quantile",
                        "zero_share_52w": 0.7,
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
                "confidence": float(forecast_confidence(10.0, 12.0)),
                "selected_model": "lightgbm_horizon_quantile",
                "shap_demand_trend": 1.0,
                "shap_seasonality": 0.5,
                "shap_price": -0.2,
                "shap_competitor_activity": 0.1,
                "shap_weather_local_events": 0.0,
            }
        )
    return pd.DataFrame(rows)


def _acceptance(evaluation: pd.DataFrame | None = None) -> dict[str, object]:
    return evaluate_acceptance(
        _full_schedule() if evaluation is None else evaluation
    )


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


def test_published_seasonal_improvement_uses_paired_champion_rows() -> None:
    evaluation = _full_schedule()
    missing_key = evaluation.index[0]
    evaluation.loc[missing_key, "seasonal_naive_baseline"] = float("nan")
    evaluation.loc[missing_key, "yhat_p50"] = 1000.0
    metrics = derive_forecast_metrics(evaluation)
    portfolio = metrics[
        metrics["slice_type"].eq("global")
        & metrics["slice_id"].eq("portfolio")
        & metrics["horizon"].eq(0)
    ].set_index("model_id")

    paired = portfolio.loc["champion_seasonal_paired"]
    seasonal = portfolio.loc["seasonal_naive"]
    expected = (
        (seasonal["wape"] - paired["wape"])
        / seasonal["wape"]
        * 100.0
    )

    assert portfolio.loc["champion", "n"] == len(evaluation)
    assert paired["n"] == len(evaluation) - 1
    assert portfolio.loc[
        "champion", "improvement_vs_seasonal_naive_pct"
    ] == expected


def test_publisher_emits_schema_valid_rejected_candidate(tmp_path: Path) -> None:
    acceptance = _acceptance()
    acceptance["global"]["metrics"]["champion"]["abs_error_sum"] = -1
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
    authoritative_acceptance = json.loads(
        (output / "forecast_acceptance.json").read_text(encoding="utf-8")
    )
    assert (
        authoritative_acceptance["global"]["metrics"]["champion"][
            "abs_error_sum"
        ]
        >= 0
    )
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


def test_publisher_emits_and_verifies_accepted_candidate(tmp_path: Path) -> None:
    evaluation = _accepted_schedule()
    acceptance = _acceptance(evaluation)
    assert acceptance["passed"] is True

    output = tmp_path / "accepted"
    publication = publish_forecast_run(
        evaluation,
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
        stage_telemetry={},
        mlflow_run_id=None,
    )

    assert publication.lifecycle_status == "accepted"
    verified = verify_forecast_run(output)
    assert verified.forecast_run_id == publication.forecast_run_id
    assert verified.lifecycle_status == "accepted"


def test_publisher_rejects_partial_schedule(tmp_path: Path) -> None:
    with pytest.raises(
        ForecastPublicationError,
        match="requires all horizons",
    ):
        publish_forecast_run(
            _full_schedule().query("horizon == 1"),
            _calibration(),
            _acceptance(),
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
            _acceptance(),
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
        _acceptance(),
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


def test_publisher_rejects_forged_acceptance_verdict(tmp_path: Path) -> None:
    forged = _acceptance()
    forged["passed"] = True

    with pytest.raises(
        ForecastPublicationError,
        match="does not match independently recomputed A1-A5",
    ):
        publish_forecast_run(
            _full_schedule(),
            _calibration(),
            forged,
            _exceptions(),
            _quality(),
            tmp_path / "forged",
            current_forecasts=_current_forecasts(),
            classification_policies=_policies(),
            input_bundle=_identity(),
            feature_semantic_fingerprint="e" * 64,
            decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
            runtime_profile=resolve_ml_runtime_profile("safe"),
            stage_telemetry={},
            mlflow_run_id=None,
        )


def test_publisher_rejects_confidence_not_derived_from_quantiles(
    tmp_path: Path,
) -> None:
    evaluation = _full_schedule()
    evaluation["confidence"] = 0.1234

    with pytest.raises(
        ForecastPublicationError,
        match="confidence violates decision #12",
    ):
        publish_forecast_run(
            evaluation,
            _calibration(),
            _acceptance(evaluation),
            _exceptions(),
            _quality(),
            tmp_path / "bad-confidence",
            current_forecasts=_current_forecasts(),
            classification_policies=_policies(),
            input_bundle=_identity(),
            feature_semantic_fingerprint="e" * 64,
            decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
            runtime_profile=resolve_ml_runtime_profile("safe"),
            stage_telemetry={},
            mlflow_run_id=None,
        )


def test_verifier_recomputes_acceptance_after_hashes_are_resigned(
    tmp_path: Path,
) -> None:
    output = tmp_path / "run"
    publish_forecast_run(
        _full_schedule(),
        _calibration(),
        _acceptance(),
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
    acceptance_path = output / "forecast_acceptance.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    acceptance["global"]["gates"]["A1"]["relativeWapeImprovementPct"] = 999.0
    acceptance_path.write_text(
        json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    manifest_path = output / "forecast-run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = manifest["artifacts"]["forecast_acceptance"]
    descriptor["bytes"] = acceptance_path.stat().st_size
    descriptor["sha256"] = hashlib.sha256(acceptance_path.read_bytes()).hexdigest()
    descriptor["semanticFingerprint"] = _json_semantic_fingerprint(
        acceptance,
        schema_version=ARTIFACT_SCHEMAS["forecast_acceptance"],
    )
    fingerprint_payload = dict(manifest)
    fingerprint_payload.pop("semanticFingerprint", None)
    manifest["semanticFingerprint"] = semantic_fingerprint(
        fingerprint_payload,
        volatile_pointers=RUN_VOLATILE_POINTERS,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ForecastRunVerificationError,
        match="does not match recomputed A1-A5",
    ):
        verify_forecast_run(output)


def test_verifier_recomputes_confidence_after_artifact_is_resigned(
    tmp_path: Path,
) -> None:
    output = tmp_path / "run"
    publish_forecast_run(
        _full_schedule(),
        _calibration(),
        _acceptance(),
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
    series_path = output / "forecast_series.parquet"
    series = pd.read_parquet(series_path)
    series.loc[series.index[0], "confidence"] = 0.1234
    series.to_parquet(series_path, index=False)

    manifest_path = output / "forecast-run-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    descriptor = manifest["artifacts"]["forecast_series"]
    descriptor["bytes"] = series_path.stat().st_size
    descriptor["sha256"] = hashlib.sha256(series_path.read_bytes()).hexdigest()
    descriptor["semanticFingerprint"] = _frame_semantic_fingerprint(
        series,
        schema_version=ARTIFACT_SCHEMAS["forecast_series"],
    )
    fingerprint_payload = dict(manifest)
    fingerprint_payload.pop("semanticFingerprint", None)
    manifest["semanticFingerprint"] = semantic_fingerprint(
        fingerprint_payload,
        volatile_pointers=RUN_VOLATILE_POINTERS,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ForecastRunVerificationError,
        match="confidence violates decision #12",
    ):
        verify_forecast_run(output)


def test_execution_profile_does_not_change_run_identity(tmp_path: Path) -> None:
    acceptance = _acceptance()
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
