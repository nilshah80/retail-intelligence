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
                    "cold_start_baseline": actual - 2,
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
                        "cold_start_baseline": actual - 2,
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
    acceptance["global"]["gates"]["A1_established"]["relativeWapeImprovementPct"] = 999.0
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


def _remediation_record() -> dict:
    """A minimal decision #84 record shaped as the schema requires."""

    return {
        "candidateId": "C5",
        "decisionIds": [84],
        "blendTarget": "cold_start_baseline",
        "segmentColumns": ["market_id", "horizon"],
        "segments": {"m1|1": {"weight": 0.5}},
        "fitOrigins": ["2025-08-04"],
        "confirmationOriginsHeldOut": ["2026-01-19"],
        "appliesToCohort": "cold_start",
    }


def test_a_remediation_bundle_does_not_share_an_identity_with_a_champion(
    tmp_path: Path,
) -> None:
    """Decision #86 governance has to be visible to the identity.

    Both run and version identity originally excluded modelPolicy, so a remediation
    bundle and a champion bundle over byte-identical forecasts hashed to the same
    forecast_run_id AND the same version_id. The governance that distinguishes them
    was invisible, and a corrected bundle could not be materialised beside the
    mislabelled one it replaced -- the unique constraint refused it.
    """

    evaluation = _full_schedule()
    evaluation["champion_p50"] = evaluation["yhat_p50"]
    evaluation["champion_p90"] = evaluation["yhat_p90"]
    evaluation["cohort"] = "established_history"

    common = {
        "classification_policies": _policies(),
        "input_bundle": _identity(),
        "feature_semantic_fingerprint": "e" * 64,
        "decision_as_of": datetime(2026, 1, 25, tzinfo=UTC),
        "mlflow_run_id": None,
        "runtime_profile": resolve_ml_runtime_profile("safe"),
        "stage_telemetry": {"elapsed": "x"},
        "current_forecasts": _current_forecasts(),
    }
    champion = publish_forecast_run(
        _full_schedule(),
        _calibration(),
        _acceptance(),
        _exceptions(),
        _quality(),
        tmp_path / "champion",
        **common,
    )
    remediation = publish_forecast_run(
        evaluation,
        _calibration(),
        _acceptance(),
        _exceptions(),
        _quality(),
        tmp_path / "remediation",
        remediation=_remediation_record(),
        **common,
    )

    assert champion.forecast_run_id != remediation.forecast_run_id
    champion_versions = pd.read_parquet(
        tmp_path / "champion" / "forecast_versions.parquet"
    )
    remediation_versions = pd.read_parquet(
        tmp_path / "remediation" / "forecast_versions.parquet"
    )
    assert (
        champion_versions.iloc[0]["version_id"]
        != remediation_versions.iloc[0]["version_id"]
    ), "a remediation version must be distinguishable in the serving tables"


def test_both_documents_declare_the_same_candidate_class(tmp_path: Path) -> None:
    """Decision #86 §3 names the acceptance document, not only the manifest.

    Publication recomputes acceptance independently and replaces what was supplied.
    Recomputing with the default silently relabelled every remediation bundle as
    `champion` while its manifest said `gate_remediation`.
    """

    evaluation = _full_schedule()
    evaluation["champion_p50"] = evaluation["yhat_p50"]
    evaluation["champion_p90"] = evaluation["yhat_p90"]
    evaluation["cohort"] = "established_history"

    publish_forecast_run(
        evaluation,
        _calibration(),
        _acceptance(),
        _exceptions(),
        _quality(),
        tmp_path / "bundle",
        current_forecasts=_current_forecasts(),
        classification_policies=_policies(),
        input_bundle=_identity(),
        feature_semantic_fingerprint="e" * 64,
        decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
        runtime_profile=resolve_ml_runtime_profile("safe"),
        stage_telemetry={"elapsed": "x"},
        mlflow_run_id=None,
        remediation=_remediation_record(),
    )

    manifest = json.loads(
        (tmp_path / "bundle" / "forecast-run-manifest.json").read_text()
    )
    acceptance = json.loads(
        (tmp_path / "bundle" / "forecast_acceptance.json").read_text()
    )

    assert manifest["modelPolicy"]["candidateClass"] == "gate_remediation"
    assert acceptance["candidateClass"] == "gate_remediation"


def test_a_remediation_bundle_must_publish_its_replay_columns(tmp_path: Path) -> None:
    """Without them `independentlyVerified` would only mean the publisher said so."""

    with pytest.raises(ForecastPublicationError, match="replayed"):
        publish_forecast_run(
            _full_schedule(),
            _calibration(),
            _acceptance(),
            _exceptions(),
            _quality(),
            tmp_path / "bundle",
            current_forecasts=_current_forecasts(),
            classification_policies=_policies(),
            input_bundle=_identity(),
            feature_semantic_fingerprint="e" * 64,
            decision_as_of=datetime(2026, 1, 25, tzinfo=UTC),
            runtime_profile=resolve_ml_runtime_profile("safe"),
            stage_telemetry={"elapsed": "x"},
            mlflow_run_id=None,
            remediation=_remediation_record(),
        )


def test_display_cell_integrity_is_computed_not_asserted() -> None:
    """Decision #86 §2.4 must produce numbers, not a claim in a document.

    §2.3 and §2.5 were made to refuse a bundle earlier; §2.4 and §2.7 were still
    satisfied by hand in the decision text. A criterion nobody computes cannot notice a
    regression, so the comparison is now published for every display horizon.
    """

    from retail_ml.publish.run_artifacts import _decision_86_display_evidence

    evaluation = _full_schedule()
    evaluation["champion_p50"] = evaluation["yhat_p50"]
    evaluation["champion_p90"] = evaluation["yhat_p90"]
    evaluation["cohort"] = "established_history"

    evidence = _decision_86_display_evidence(evaluation)

    assert evidence["metricSemantics"] == "exact_horizon_additive"
    assert evidence["tolerancePct"] == 0.1
    assert evidence["cells"], "no display cell was measured"
    # Candidate equals champion here, so every cell must be a measured zero delta rather
    # than an absent comparison.
    assert all(abs(cell["deltaPct"]) < 1e-9 for cell in evidence["cells"])
    # Portfolio grain, not row level: the additive components are summed to the
    # portfolio before the metric is read, so offsetting SeriesKey errors cancel and
    # the number is materially higher than a row-level WAPE accuracy would be.
    assert all(cell["grain"] == "market_portfolio" for cell in evidence["cells"])
    assert evidence["passed"] is True
    assert evidence["violations"] == []
    for cell in evidence["cells"]:
        assert cell["championPasses"] == cell["candidatePasses"]
        assert cell["horizon"] in {1, 4, 8, 13, 26}
        assert cell["targetPct"] > 0


def test_a_display_cell_regression_is_detected() -> None:
    """Degrading the candidate must surface as a violation, not vanish."""

    from retail_ml.publish.run_artifacts import _decision_86_display_evidence

    evaluation = _full_schedule()
    evaluation["champion_p50"] = evaluation["yhat_p50"]
    evaluation["champion_p90"] = evaluation["yhat_p90"]
    evaluation["cohort"] = "established_history"
    # Move the served p50 away from the actual so accuracy falls well past the 0.1pp
    # display-rounding bound at every horizon.
    evaluation["yhat_p50"] = evaluation["yhat_p50"] * 1.5

    evidence = _decision_86_display_evidence(evaluation)

    assert evidence["passed"] is False
    assert evidence["violations"], "a 50% inflation produced no violation"
    assert any(cell["regressionBeyondRounding"] for cell in evidence["cells"])
    assert all(cell["deltaPct"] < 0 for cell in evidence["violations"])


def test_display_targets_are_read_from_the_frozen_policy() -> None:
    """The targets must come from the contract the UI also reads.

    Restating decision #77's numbers in Python would create a second source of truth
    that could drift from what users see on screen.
    """

    import json
    from pathlib import Path as _Path

    from retail_ml.publish.run_artifacts import _health_accuracy_targets

    targets = _health_accuracy_targets()
    contract = json.loads(
        (
            _Path(__file__).resolve().parents[2]
            / "contracts"
            / "ml"
            / "forecast-health-policy.json"
        ).read_text(encoding="utf-8")
    )
    for grain, horizons in contract["accuracyTargetsPct"].items():
        for horizon, target in horizons.items():
            assert targets[grain][int(horizon)] == float(target)


def test_display_cell_metric_reproduces_the_served_grain() -> None:
    """§2.4 must measure the cell the UI shows, not a nearby number.

    This got wrong three times in a row, each plausible and each off by enough to
    matter: per-row absolute error gives leaf accuracy, collapsing origin and week lets
    errors cancel across time, and dropping market_id lets India and the US cancel
    against each other. The served handler groups cells by the grain columns plus
    horizon, forecast_origin and target_week_start, and market_portfolio's grain column
    is market_id (`resolveHealthGrain` in api/internal/readmodel/forecast.go).

    So the property under test is the grouping, asserted against a frame built so that
    the wrong groupings give visibly different answers: the two markets carry
    offsetting errors, which cancel unless market_id is part of the cell key.
    """

    from retail_ml.publish.run_artifacts import _portfolio_horizon_accuracy

    frame = pd.DataFrame(
        {
            "market_id": ["in", "us", "in", "us"],
            "forecast_origin": ["2026-01-05"] * 4,
            "target_week_start": ["2026-01-12", "2026-01-12", "2026-01-19", "2026-01-19"],
            "actual_units": [100.0, 100.0, 100.0, 100.0],
            # +20 in one market, -20 in the other, in both weeks.
            "yhat_p50": [120.0, 80.0, 120.0, 80.0],
        }
    )

    accuracy = _portfolio_horizon_accuracy(frame, "yhat_p50")
    # Per market-week cell: |20| each, four cells -> 80 absolute error on 400 actual.
    assert accuracy == pytest.approx(80.0)
    # Had market_id been dropped from the cell key the errors would cancel exactly and
    # this would read 100.0 -- a perfect score built out of two wrong forecasts.
    assert accuracy != pytest.approx(100.0)


def test_a_broken_display_cell_now_refuses_the_bundle() -> None:
    """§2.4 stopped being advisory; prove it blocks rather than annotates.

    It shipped report-only because the metric had to be shown to reproduce the served
    display cell first -- three earlier formulations each produced a plausible number the
    UI does not show. Once a real C5 bundle reported five clean cells, leaving it
    advisory meant a criterion that could see a regression and let it through.
    """

    from retail_ml.publish.run_artifacts import (
        DECISION_86_DISPLAY_GATE_MODE,
        ForecastPublicationError,
        _validate_remediation_candidate,
    )

    assert DECISION_86_DISPLAY_GATE_MODE == "refusing"

    evaluation = _full_schedule()
    evaluation["champion_p50"] = evaluation["yhat_p50"]
    evaluation["champion_p90"] = evaluation["yhat_p90"]
    evaluation["cohort"] = "cold_start"
    # Degrade only the served p50, so the untargeted-rows and leakage checks stay clean
    # and §2.4 is unambiguously the criterion that fires.
    evaluation["yhat_p50"] = evaluation["yhat_p50"] * 1.5

    with pytest.raises(ForecastPublicationError) as excinfo:
        _validate_remediation_candidate(evaluation, {"candidateId": "C-test"})

    message = str(excinfo.value)
    assert "§2.4" in message
    # The refusal names the cells, so the failure is actionable without re-deriving it.
    assert "target" in message


def test_uncalibrated_cold_start_intervals_are_withheld_not_served() -> None:
    """Decision #92: the gate may only be scoped to published intervals if the
    unpublished ones are genuinely not served.

    Without this the gate measures h1-h4 at 0.8603 while the screen shows an h13 interval
    measured at 0.8024 -- telling the truth about a number nobody reads and staying silent
    about the one they do.
    """

    from retail_ml.policies.interval_availability import (
        COLD_START_CALIBRATED_MAX_HORIZON,
        UNCALIBRATED_REASON_CODE,
    )
    from retail_ml.publish.run_artifacts import (
        withhold_uncalibrated_cold_start_intervals,
    )

    evaluation = _full_schedule()
    evaluation["cohort"] = "cold_start"
    current = _current_forecasts()

    served, evidence = withhold_uncalibrated_cold_start_intervals(evaluation, evaluation)

    beyond = pd.to_numeric(served["horizon"], errors="coerce") > (
        COLD_START_CALIBRATED_MAX_HORIZON
    )
    within = ~beyond
    # Withheld beyond the calibrated range...
    assert served.loc[beyond, "yhat_p90"].isna().all()
    assert served.loc[beyond, "confidence"].isna().all()
    assert (
        served.loc[beyond, "interval_unavailable_reason"] == UNCALIBRATED_REASON_CODE
    ).all()
    # ...and untouched within it.
    assert served.loc[within, "yhat_p90"].notna().all()
    assert served.loc[within, "interval_available"].all()
    # P50 survives at EVERY horizon. This withdraws a distribution claim, never a
    # forecast, which is the whole basis for scoping the gate.
    assert served["yhat_p50"].notna().all()
    assert evidence["withheldRows"] == int(beyond.sum())
    assert evidence["reasonCode"] == UNCALIBRATED_REASON_CODE


def test_established_intervals_are_never_withheld() -> None:
    """The limit is cold-start only; the established cohort passes at every horizon."""

    from retail_ml.publish.run_artifacts import (
        withhold_uncalibrated_cold_start_intervals,
    )

    evaluation = _full_schedule()
    evaluation["cohort"] = "established_history"

    served, evidence = withhold_uncalibrated_cold_start_intervals(evaluation, evaluation)

    assert evidence["withheldRows"] == 0
    assert served["yhat_p90"].notna().all()
    assert served["interval_available"].all()


def test_a_consumer_needing_a_longer_horizon_fails_closed() -> None:
    """The h1-h4 boundary is load-bearing, so it is asserted rather than assumed.

    Reorder currently reads about h1 because every suppliers_leadtimes row carries
    lead_time_days = 5. A new overseas supplier would push the required horizon past the
    calibrated range, and silently reading past it is how an under-covered interval becomes
    an under-stocked order.
    """

    from retail_ml.policies.interval_availability import (
        IntervalHorizonUnavailableError,
        horizon_for_lead_time,
        require_cold_start_interval_horizon,
    )

    # 5-day lead time plus a weekly review cycle: inside the calibrated range.
    assert horizon_for_lead_time(5) == 2
    require_cold_start_interval_horizon(
        horizon_for_lead_time(5), consumer="phase4-reorder"
    )

    # A 60-day overseas lead time is refused, and the error carries the measurement.
    with pytest.raises(IntervalHorizonUnavailableError) as excinfo:
        require_cold_start_interval_horizon(
            horizon_for_lead_time(60), consumer="phase4-reorder"
        )
    assert "0.7798" in str(excinfo.value) or "h14-h26" in str(excinfo.value)
