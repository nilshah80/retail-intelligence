"""Origin-safe materialization of the serving forecast cycle."""

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
from typing import Any, Final

import duckdb
import pandas as pd

from retail_ml.features.availability import HORIZONS
from retail_ml.io.bundle import VerifiedInputBundle
from retail_ml.models.baselines import attach_baselines
from retail_ml.models.dataset import (
    load_current_horizon,
    load_training_horizon,
)
from retail_ml.models.forecasting import _history, _verified_feature_path
from retail_ml.models.intermittent import route_intermittent_forecasts
from retail_ml.models.train_lgbm import fit_horizon_model, score_horizon_model
from retail_ml.runtime.profile import MLRuntimeProfile, model_worker_budget
from retail_ml.runtime.telemetry import MLStageTelemetry

CURRENT_CYCLE_SCHEMA: Final[str] = "retail-forecast-current-cycle/v1"
CORE_QUALITY_FEATURES: Final[tuple[str, ...]] = (
    "origin_units",
    "weekly_units_equivalent",
    "units_lag_1",
    "units_lag_4",
    "units_lag_13",
    "units_lag_52",
    "units_roll_mean_4",
    "units_roll_mean_8",
    "units_roll_mean_13",
    "units_roll_mean_52",
    "zero_share_52w",
    "price_ratio_13w",
)


@dataclass(frozen=True)
class CurrentCycleStats:
    forecast_origin: str
    horizons: int
    series: int
    forecast_rows: int
    training_rows: int
    elapsed_seconds: str
    output_dir: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_origin(feature_path: Path, decision_as_of: datetime) -> date:
    escaped = str(feature_path.resolve()).replace("'", "''")
    connection = duckdb.connect()
    value = connection.execute(
        f"""
        SELECT max(forecast_origin)
        FROM read_parquet('{escaped}')
        WHERE forecast_origin <= DATE '{decision_as_of.date().isoformat()}'
          AND forecast_origin + INTERVAL 1 WEEK
              > DATE '{decision_as_of.date().isoformat()}'
        """
    ).fetchone()[0]
    connection.close()
    if value is None:
        raise ValueError(
            "no feature origin has an entirely future h1 at decision_as_of"
        )
    return value


def _history_summary(
    feature_path: Path,
    *,
    origin: date,
    decision_as_of: datetime,
) -> pd.DataFrame:
    escaped = str(feature_path.resolve()).replace("'", "''")
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        WITH current_keys AS (
            SELECT sku_id, store_id, channel_id
            FROM read_parquet('{escaped}')
            WHERE forecast_origin = DATE '{origin.isoformat()}'
        )
        SELECT
            f.sku_id,
            f.store_id,
            f.channel_id,
            count(*) FILTER (
                WHERE f.forecast_origin <= DATE '{origin.isoformat()}'
                  AND f.exposure_days > 0
            )::BIGINT AS history_weeks,
            count(*) FILTER (
                WHERE f.forecast_origin
                    BETWEEN DATE '{origin.isoformat()}' - INTERVAL 12 WEEK
                        AND DATE '{origin.isoformat()}'
                  AND f.exposure_days > 0
            )::DOUBLE / 13.0 AS observation_coverage_13w,
            max(
                f.forecast_origin + (f.exposure_days - 1) * INTERVAL 1 DAY
            ) FILTER (
                WHERE f.forecast_origin <= DATE '{origin.isoformat()}'
                  AND f.exposure_days > 0
            ) AS latest_actual_date
        FROM read_parquet('{escaped}') f
        INNER JOIN current_keys k USING (sku_id, store_id, channel_id)
        GROUP BY f.sku_id, f.store_id, f.channel_id
        ORDER BY f.sku_id, f.store_id, f.channel_id
        """
    ).fetchdf()
    connection.close()
    latest = pd.to_datetime(frame.pop("latest_actual_date")).dt.date
    frame["latest_actual_age_days"] = [
        (decision_as_of.date() - value).days for value in latest
    ]
    return frame


def _source_quality(
    bundle: VerifiedInputBundle,
) -> tuple[bool, int, int]:
    gate_b = json.loads(
        bundle.paths.gate_b_report.read_text(encoding="utf-8")
    )
    reconciliation_passed = any(
        rule.get("ruleId") == "B16" and rule.get("outcome") == "pass"
        for rule in gate_b.get("rules", [])
    )
    quality_path = (
        bundle.paths.curated_root
        / "parquet"
        / "quality_violations"
        / "data.parquet"
    )
    quality = pd.read_parquet(quality_path, columns=["outcome"])
    outcomes = quality["outcome"].fillna("").astype(str)
    return (
        reconciliation_passed,
        int(outcomes.eq("critical").sum()),
        int(outcomes.eq("warning").sum()),
    )


def _classification_input(
    scored: pd.DataFrame,
    *,
    feature_path: Path,
    origin: date,
    decision_as_of: datetime,
    bundle: VerifiedInputBundle,
) -> pd.DataFrame:
    h1 = scored[scored["horizon"].eq(1)].copy()
    if h1.empty:
        raise ValueError("current-cycle classification requires h1 forecasts")
    summary = _history_summary(
        feature_path,
        origin=origin,
        decision_as_of=decision_as_of,
    )
    result = h1.merge(
        summary,
        on=["sku_id", "store_id", "channel_id"],
        how="left",
        validate="one_to_one",
    )
    missing = result[list(CORE_QUALITY_FEATURES)].isna().sum(axis=1)
    result["core_feature_missing_share"] = (
        missing / len(CORE_QUALITY_FEATURES)
    )
    reconciliation, critical, warnings = _source_quality(bundle)
    result["canonical_key_complete"] = result[
        ["sku_id", "store_id", "channel_id"]
    ].notna().all(axis=1)
    result["reconciliation_passed"] = reconciliation
    result["source_quality_critical_count"] = critical
    result["source_quality_warning_count"] = warnings
    result["promotion_plan_available"] = False
    result["planned_promotion_uplift_pct"] = 0.0
    ma13 = pd.to_numeric(result["ma13_baseline"], errors="coerce").fillna(0.0)
    result["forecast_uplift_vs_ma13_pct"] = (
        pd.to_numeric(result["yhat_p50"], errors="coerce") - ma13
    ) / ma13.clip(lower=1.0)
    columns = [
        "sku_id",
        "store_id",
        "channel_id",
        "canonical_key_complete",
        "core_feature_missing_share",
        "latest_actual_age_days",
        "observation_coverage_13w",
        "reconciliation_passed",
        "source_quality_critical_count",
        "source_quality_warning_count",
        "yhat_p50",
        "yhat_p90",
        "ma13_baseline",
        "history_weeks",
        "zero_share_52w",
        "promotion_plan_available",
        "planned_promotion_uplift_pct",
        "forecast_uplift_vs_ma13_pct",
    ]
    return result[columns].sort_values(
        ["sku_id", "store_id", "channel_id"]
    ).reset_index(drop=True)


def run_current_cycle(
    feature_dir: str | Path,
    output_dir: str | Path,
    *,
    verified_bundle: VerifiedInputBundle,
    decision_as_of: datetime,
    runtime_profile: MLRuntimeProfile,
) -> CurrentCycleStats:
    """Fit at the decision origin and atomically emit future-only predictions."""

    if decision_as_of.tzinfo is None:
        raise ValueError("decision_as_of must be timezone-aware")
    source_dir = Path(feature_dir).resolve()
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"current-cycle output already exists: {output}")
    feature_path, feature_manifest = _verified_feature_path(source_dir)
    if feature_manifest.get("sourceInput") != verified_bundle.identity:
        raise ValueError("feature artifact is not bound to the verified input bundle")
    origin = _current_origin(feature_path, decision_as_of)
    history = _history(feature_path, origin)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(dir=output.parent, prefix=f".{output.name}.staging-")
    )
    telemetry = MLStageTelemetry()
    started = time.monotonic()
    training_rows = 0
    calibration_records: list[dict[str, Any]] = []
    try:
        def fit_score(
            horizon: int,
        ) -> tuple[pd.DataFrame, list[dict[str, Any]], int]:
            with telemetry.measure("load_training"):
                training = load_training_horizon(
                    feature_path,
                    scored_origin=origin,
                    horizon=horizon,
                    threads=runtime_profile.threads_per_model,
                )
            with telemetry.measure("load_current"):
                current = load_current_horizon(
                    feature_path,
                    scored_origin=origin,
                    horizon=horizon,
                    decision_as_of=decision_as_of,
                    threads=runtime_profile.threads_per_model,
                )
            with telemetry.measure("fit_models"):
                model = fit_horizon_model(
                    training,
                    horizon=horizon,
                    threads_per_model=runtime_profile.threads_per_model,
                )
            with telemetry.measure("score_and_tree_shap"):
                scored = score_horizon_model(current, model)
            scored = attach_baselines(scored)
            scored = route_intermittent_forecasts(scored, history)
            records = [
                {"scored_origin": origin.isoformat(), **asdict(record)}
                for record in (
                    model.global_calibration,
                    *model.market_calibrations.values(),
                )
            ]
            return scored, records, len(training)

        with ThreadPoolExecutor(
            max_workers=model_worker_budget(runtime_profile)
        ) as executor:
            results = list(executor.map(fit_score, HORIZONS))
        scored = pd.concat([result[0] for result in results], ignore_index=True)
        scored = scored.sort_values(
            [
                "market_id",
                "store_id",
                "channel_id",
                "sku_id",
                "horizon",
            ]
        ).reset_index(drop=True)
        training_rows = sum(result[2] for result in results)
        calibration_records = [
            record for result in results for record in result[1]
        ]
        classification = _classification_input(
            scored,
            feature_path=feature_path,
            origin=origin,
            decision_as_of=decision_as_of,
            bundle=verified_bundle,
        )
        forecast_path = staging / "current_forecast_predictions.parquet"
        classification_path = staging / "current_cycle_classification_input.parquet"
        calibration_path = staging / "current_cycle_calibration.parquet"
        scored.to_parquet(forecast_path, index=False)
        classification.to_parquet(classification_path, index=False)
        pd.DataFrame(calibration_records).to_parquet(
            calibration_path,
            index=False,
        )
        elapsed = f"{time.monotonic() - started:.6f}"
        stats = CurrentCycleStats(
            forecast_origin=origin.isoformat(),
            horizons=len(HORIZONS),
            series=len(classification),
            forecast_rows=len(scored),
            training_rows=training_rows,
            elapsed_seconds=elapsed,
            output_dir=str(output),
        )
        manifest = {
            "schemaVersion": CURRENT_CYCLE_SCHEMA,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "decisionAsOf": decision_as_of.astimezone(UTC).isoformat().replace(
                "+00:00", "Z"
            ),
            "featureSemanticFingerprint": feature_manifest[
                "semanticFingerprint"
            ],
            "sourceInput": verified_bundle.identity,
            "stats": asdict(stats),
            "stageTelemetry": {
                **telemetry.snapshot(),
                "wallClockElapsedSeconds": elapsed,
            },
            "objects": {
                path.name: {
                    "bytes": path.stat().st_size,
                    "sha256": _sha256_file(path),
                }
                for path in (
                    forecast_path,
                    classification_path,
                    calibration_path,
                )
            },
        }
        (staging / "current-cycle-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
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
    "CORE_QUALITY_FEATURES",
    "CURRENT_CYCLE_SCHEMA",
    "CurrentCycleStats",
    "run_current_cycle",
]
