"""Bounded rolling-origin forecast orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.features.build import (
    FEATURE_MANIFEST_VOLATILE_POINTERS,
    all_null_feature_columns,
    weekly_features_sql,
)
from retail_ml.features.availability import HORIZONS
from retail_ml.models.backtest import (
    CANDIDATE_CLASS_REMEDIATION,
    evaluate_acceptance,
)
from retail_ml.models.baselines import attach_baselines, metric_for_column
from retail_ml.models.cohorts import attach_cold_start_baseline
from retail_ml.models.cold_start_blend import (
    BLEND_MODEL_FILENAME,
    remediate_cold_start,
)
from retail_ml.models.dataset import (
    eligible_scoring_origins,
    load_evaluation_horizon,
    load_training_horizon,
)
from retail_ml.models.intermittent import (
    replay_preferred_tail_keys,
    route_intermittent_forecasts,
)
from retail_ml.models.train_lgbm import fit_horizon_model, score_horizon_model
from retail_ml.runtime.profile import MLRuntimeProfile, model_worker_budget
from retail_ml.runtime.telemetry import MLStageTelemetry
from retail_ml.telemetry.mlflow import log_artifact, log_metrics, tracked_mlflow_run


@dataclass(frozen=True)
class BacktestStats:
    scoring_origins: int
    horizons: int
    forecast_rows: int
    training_rows: int
    elapsed_seconds: str
    full_schedule: bool
    accepted: bool
    output_dir: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_feature_path(feature_dir: Path) -> tuple[Path, dict[str, Any]]:
    manifest_path = feature_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != "retail-weekly-features/v6":
        raise ValueError("unsupported weekly feature artifact")
    fingerprint_payload = dict(manifest)
    recorded_fingerprint = fingerprint_payload.pop(
        "semanticFingerprint",
        None,
    )
    if (
        recorded_fingerprint
        != semantic_fingerprint(
            fingerprint_payload,
            volatile_pointers=FEATURE_MANIFEST_VOLATILE_POINTERS,
        )
        or manifest.get("featurePolicy", {}).get("featureSqlSha256")
        != hashlib.sha256(weekly_features_sql().encode("utf-8")).hexdigest()
    ):
        raise ValueError("weekly feature semantic identity does not match its policy")
    feature_path = feature_dir / manifest["objects"]["weeklyFeatures"]["path"]
    expected = manifest["objects"]["weeklyFeatures"]
    if (
        feature_path.stat().st_size != expected["bytes"]
        or _sha256_file(feature_path) != expected["sha256"]
    ):
        raise ValueError("weekly feature object does not match its manifest")
    connection = duckdb.connect()
    try:
        all_null_columns = all_null_feature_columns(connection, feature_path)
    finally:
        connection.close()
    if (
        manifest.get("featurePolicy", {}).get("allNullFeatureColumns") != []
        or all_null_columns
    ):
        raise ValueError(
            "weekly feature artifact contains structurally all-null columns: "
            + ", ".join(all_null_columns)
        )
    return feature_path, manifest


def verified_backtest_artifacts(
    backtest_dir: Path,
    *,
    feature_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Verify every backtest object before the publisher reads it."""

    root = backtest_dir.resolve()
    manifest = json.loads(
        (root / "backtest-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schemaVersion") != "retail-forecast-backtest/v1":
        raise ValueError("unsupported forecast backtest artifact")
    if (
        manifest.get("featureSemanticFingerprint")
        != feature_manifest.get("semanticFingerprint")
    ):
        raise ValueError("backtest does not match the verified feature artifact")
    expected_names = {
        "forecast_eval_predictions.parquet",
        "forecast_calibration.parquet",
        "acceptance.json",
        # Decision #84's fitted blend weights. Part of the frozen contract because
        # the serving cycle must apply the same estimator the gate scored, and a
        # bundle that omitted them could only be served by refitting.
        BLEND_MODEL_FILENAME,
    }
    objects = manifest.get("objects")
    if not isinstance(objects, dict) or set(objects) != expected_names:
        raise ValueError("backtest objects do not match the frozen contract")
    paths: dict[str, Path] = {}
    for name in sorted(expected_names):
        descriptor = objects[name]
        path = (root / name).resolve()
        if (
            path.parent != root
            or not path.is_file()
            or not isinstance(descriptor, dict)
            or path.stat().st_size != descriptor.get("bytes")
            or _sha256_file(path) != descriptor.get("sha256")
        ):
            raise ValueError(f"backtest object does not match its manifest: {name}")
        paths[name] = path
    return manifest, paths


def _partial_history(feature_path: Path, origin: date) -> pd.DataFrame:
    """Decision #83: origin-visible *partial* weeks, exposure-normalised.

    Used only where a SeriesKey has no complete prior week, so a launch week no
    longer forces the cold-start gate to `insufficient_evidence` forever.
    """

    escaped = str(feature_path).replace("'", "''")
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        SELECT
            sku_id,
            store_id,
            channel_id,
            forecast_origin,
            weekly_units_equivalent AS origin_units
        FROM read_parquet('{escaped}')
        WHERE forecast_origin < DATE '{origin.isoformat()}'
          AND NOT training_eligible
          AND exposure_days BETWEEN 1 AND 6
        ORDER BY sku_id, store_id, channel_id, forecast_origin
        """
    ).fetchdf()
    connection.close()
    return frame


def _history(feature_path: Path, origin: date) -> pd.DataFrame:
    escaped = str(feature_path).replace("'", "''")
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        SELECT
            sku_id,
            store_id,
            channel_id,
            forecast_origin,
            origin_units
        FROM read_parquet('{escaped}')
        WHERE forecast_origin < DATE '{origin.isoformat()}'
          AND training_eligible
        ORDER BY sku_id, store_id, channel_id, forecast_origin
        """
    ).fetchdf()
    connection.close()
    return frame


def run_backtest(
    feature_dir: str | Path,
    output_dir: str | Path,
    *,
    runtime_profile: MLRuntimeProfile,
    tracking_uri: str | Path,
    horizons: tuple[int, ...] = HORIZONS,
    origin_count: int = 13,
) -> BacktestStats:
    """Fit/retrain at each selected origin and publish diagnostic evaluation rows."""

    source_dir = Path(feature_dir).resolve()
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"backtest output already exists: {output}")
    feature_path, feature_manifest = _verified_feature_path(source_dir)
    available_origins = eligible_scoring_origins(feature_path)
    origins = available_origins[-int(origin_count) :]
    if not origins:
        raise ValueError("no eligible scoring origins")
    unsupported = set(horizons).difference(HORIZONS)
    if unsupported:
        raise ValueError(f"unsupported horizons: {sorted(unsupported)}")
    full_schedule = len(origins) == 13 and tuple(horizons) == HORIZONS

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            dir=output.parent,
            prefix=f".{output.name}.staging-",
        )
    )
    started = time.monotonic()
    telemetry = MLStageTelemetry()
    all_scored: list[pd.DataFrame] = []
    calibration_records: list[dict[str, Any]] = []
    replay_history = pd.DataFrame()
    total_training_rows = 0
    parameters = {
        "feature_semantic_fingerprint": feature_manifest["semanticFingerprint"],
        "horizons": list(horizons),
        "scoring_origins": len(origins),
        "training_origins": 104,
        "label_embargo_weeks": 8,
        "seed": 20260730,
        "execution_profile": runtime_profile.profile,
    }
    try:
        with tracked_mlflow_run(
            tracking_uri,
            experiment_name="phase3-demand-forecast",
            run_name=f"backtest-{origins[-1].isoformat()}",
            parameters=parameters,
        ) as mlflow_run_id:
            for origin_index, origin in enumerate(origins):
                def fit_score(horizon: int) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
                    with telemetry.measure("load_training"):
                        training = load_training_horizon(
                            feature_path,
                            scored_origin=origin,
                            horizon=horizon,
                            threads=runtime_profile.threads_per_model,
                        )
                    with telemetry.measure("load_evaluation"):
                        evaluation = load_evaluation_horizon(
                            feature_path,
                            scored_origin=origin,
                            horizon=horizon,
                            threads=runtime_profile.threads_per_model,
                        )
                    with telemetry.measure("fit_models"):
                        model = fit_horizon_model(
                            training,
                            horizon=horizon,
                            threads_per_model=runtime_profile.threads_per_model,
                        )
                    with telemetry.measure("score_and_tree_shap"):
                        scored = score_horizon_model(evaluation, model)
                    return scored, [
                        {
                            "scored_origin": origin.isoformat(),
                            **record,
                        }
                        for record in (
                            asdict(model.global_calibration),
                            *(
                                asdict(value)
                                for value in model.market_calibrations.values()
                            ),
                        )
                    ], len(training)

                with ThreadPoolExecutor(
                    max_workers=model_worker_budget(runtime_profile)
                ) as executor:
                    results = list(executor.map(fit_score, horizons))
                scored_origin = pd.concat(
                    [result[0] for result in results],
                    ignore_index=True,
                )
                calibration_records.extend(
                    record for result in results for record in result[1]
                )
                total_training_rows += sum(result[2] for result in results)
                with telemetry.measure("intermittent_history"):
                    intermittent_history = _history(feature_path, origin)
                    partial_history = _partial_history(feature_path, origin)
                with telemetry.measure("baselines"):
                    scored_origin = attach_baselines(scored_origin)
                    scored_origin = attach_cold_start_baseline(
                        scored_origin,
                        intermittent_history,
                        partial_history,
                    )
                with telemetry.measure("intermittent_routing"):
                    replay_preferred = replay_preferred_tail_keys(
                        replay_history,
                        known_before=origin,
                    )
                    scored_origin = route_intermittent_forecasts(
                        scored_origin,
                        intermittent_history,
                        replay_preferred_keys=replay_preferred,
                    )
                all_scored.append(scored_origin)
                candidates = scored_origin[
                    [
                        "sku_id",
                        "store_id",
                        "channel_id",
                        "target_week_start",
                        "actual_units",
                        "lightgbm_p50",
                        "tail_candidate_p50",
                    ]
                ].copy()
                replay_history = pd.concat(
                    [replay_history, candidates],
                    ignore_index=True,
                )
                diagnostic = metric_for_column(
                    scored_origin,
                    "yhat_p50",
                    upper_column="yhat_p90",
                )
                if diagnostic.wape is not None:
                    log_metrics(
                        {
                            "origin_wape": diagnostic.wape,
                            "origin_p90_coverage": diagnostic.coverage or 0.0,
                        },
                        step=origin_index,
                    )

            evaluation = pd.concat(all_scored, ignore_index=True)
            evaluation = evaluation.sort_values(
                [
                    "forecast_origin",
                    "market_id",
                    "store_id",
                    "channel_id",
                    "sku_id",
                    "horizon",
                ]
            ).reset_index(drop=True)
            # Decision #84 candidate C5, adopted as a decision #86 remediation
            # candidate. Applied before acceptance so the gate scores what will
            # actually be served, and before serialization so the published
            # artifacts carry the blend rather than a post-hoc adjustment.
            with telemetry.measure("cold_start_remediation"):
                evaluation, blend_model = remediate_cold_start(evaluation)
            with telemetry.measure("acceptance"):
                acceptance = evaluate_acceptance(
                    evaluation,
                    candidate_class=CANDIDATE_CLASS_REMEDIATION,
                )
                acceptance["remediation"] = {
                    "candidateId": blend_model["candidateId"],
                    "decisionIds": blend_model["decisionIds"],
                    "blendTarget": blend_model["blendTarget"],
                    "segmentColumns": blend_model["segmentColumns"],
                    "globalWeight": blend_model["globalWeight"],
                    "marketWeights": blend_model["marketWeights"],
                    "segmentsShrunkToParent": blend_model["segmentsShrunkToParent"],
                    "fitOrigins": blend_model["fitOrigins"],
                    "confirmationOriginsHeldOut": blend_model[
                        "confirmationOriginsHeldOut"
                    ],
                    "appliesToCohort": blend_model["appliesToCohort"],
                    "notAnAccuracyImprovement": (
                        "Decision #86 §3 forbids presenting this as an accuracy "
                        "improvement. It repairs the us-new-york cold-start "
                        "non-inferiority gate."
                    ),
                }
            if not full_schedule:
                acceptance["passed"] = False
                acceptance["diagnosticOnly"] = True
                acceptance["reasonCode"] = "INCOMPLETE_BACKTEST_SCHEDULE"
            blend_path = staging / BLEND_MODEL_FILENAME
            blend_path.write_text(
                json.dumps(blend_model, indent=2, sort_keys=True, default=str),
                encoding="utf-8",
            )
            eval_path = staging / "forecast_eval_predictions.parquet"
            calibration_path = staging / "forecast_calibration.parquet"
            with telemetry.measure("serialize_diagnostics"):
                evaluation.to_parquet(eval_path, index=False)
                pd.DataFrame(calibration_records).to_parquet(
                    calibration_path,
                    index=False,
                )
                acceptance_path = staging / "acceptance.json"
                acceptance_path.write_text(
                    json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
            log_artifact(acceptance_path)

            stats = BacktestStats(
                scoring_origins=len(origins),
                horizons=len(horizons),
                forecast_rows=len(evaluation),
                training_rows=total_training_rows,
                elapsed_seconds=f"{time.monotonic() - started:.6f}",
                full_schedule=full_schedule,
                accepted=bool(acceptance["passed"]),
                output_dir=str(output),
            )
            summary = {
                "schemaVersion": "retail-forecast-backtest/v1",
                "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "featureSemanticFingerprint": feature_manifest["semanticFingerprint"],
                "mlflowRunId": mlflow_run_id,
                "stats": asdict(stats),
                "stageTelemetry": {
                    **telemetry.snapshot(),
                    "wallClockElapsedSeconds": stats.elapsed_seconds,
                },
                "objects": {
                    path.name: {
                        "bytes": path.stat().st_size,
                        "sha256": _sha256_file(path),
                    }
                    for path in (
                        eval_path,
                        calibration_path,
                        acceptance_path,
                        blend_path,
                    )
                },
            }
            (staging / "backtest-manifest.json").write_text(
                json.dumps(summary, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
        os.replace(staging, output)
        return stats
    except BaseException:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()
        raise


__all__ = [
    "BacktestStats",
    "run_backtest",
    "verified_backtest_artifacts",
]
