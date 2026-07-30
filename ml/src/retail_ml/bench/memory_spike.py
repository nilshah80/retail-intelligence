"""Required W0.6 full-panel feature build plus one representative training fold."""

from __future__ import annotations

import json
import platform
import tempfile
import threading
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import duckdb
import lightgbm as lgb
import pandas as pd
import psutil

from retail_ml.features.availability import LABEL_EMBARGO_WEEKS
from retail_ml.features.build import build_features
from retail_ml.io.bundle import discover_input_bundle
from retail_ml.runtime.profile import resolve_ml_runtime_profile

NUMERIC_SPIKE_FEATURES = (
    "origin_units",
    "weekly_units_equivalent",
    "week_index",
    "units_lag_1",
    "units_lag_4",
    "units_lag_13",
    "units_lag_52",
    "units_roll_mean_4",
    "units_roll_std_4",
    "units_roll_mean_8",
    "units_roll_std_8",
    "units_roll_mean_13",
    "units_roll_std_13",
    "units_roll_mean_52",
    "units_roll_std_52",
    "zero_share_52w",
    "demand_trend_4v13",
    "price_ratio_13w",
    "local_category_price_index",
    "iso_week",
    "week_sin",
    "week_cos",
    "event_count_origin",
    "working_days_origin",
    "event_count_h1",
    "working_days_h1",
)
CATEGORICAL_SPIKE_FEATURES = (
    "market_id",
    "store_id",
    "channel_id",
    "dept_id",
    "category",
    "sub_cat",
)
SPIKE_FEATURES = NUMERIC_SPIKE_FEATURES + CATEGORICAL_SPIKE_FEATURES


class _PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.05) -> None:
        self._interval_seconds = interval_seconds
        self._process = psutil.Process()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self.peak_bytes = self._process.memory_info().rss

    def _sample(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            rss = self._process.memory_info().rss
            try:
                children = self._process.children(recursive=True)
            except (psutil.AccessDenied, PermissionError):
                children = ()
            for child in children:
                try:
                    rss += child.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            self.peak_bytes = max(self.peak_bytes, rss)

    def __enter__(self) -> "_PeakRssSampler":
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()
        self.peak_bytes = max(self.peak_bytes, self._process.memory_info().rss)


def _load_fold(feature_path: Path, threads: int) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    escaped = str(feature_path).replace("'", "''")
    connection = duckdb.connect()
    connection.execute(f"SET threads = {threads}")
    scored_origin = str(
        connection.execute(
            f"""
            SELECT max(forecast_origin)
            FROM read_parquet('{escaped}')
            WHERE training_eligible
              AND target_units_h26 IS NOT NULL
            """
        ).fetchone()[0]
    )[:10]
    selected_columns = ", ".join(SPIKE_FEATURES)
    training = connection.execute(
        f"""
        WITH eligible_origins AS (
            SELECT forecast_origin
            FROM (
                SELECT DISTINCT forecast_origin
                FROM read_parquet('{escaped}')
                WHERE training_eligible
                  AND units_lag_52 IS NOT NULL
                  AND forecast_origin
                      <= DATE '{scored_origin}' - INTERVAL {LABEL_EMBARGO_WEEKS} WEEK
                ORDER BY forecast_origin DESC
                LIMIT 104
            )
        )
        SELECT
            {selected_columns},
            target_units_h1 AS target_units
        FROM read_parquet('{escaped}')
        WHERE forecast_origin IN (SELECT forecast_origin FROM eligible_origins)
          AND training_eligible
          AND target_units_h1 IS NOT NULL
          AND target_known_as_of_h1
              <= DATE '{scored_origin}' + INTERVAL 6 DAY
        ORDER BY market_id, store_id, channel_id, sku_id, forecast_origin
        """
    ).fetchdf()
    evaluation = connection.execute(
        f"""
        SELECT
            {selected_columns},
            target_units_h1 AS target_units
        FROM read_parquet('{escaped}')
        WHERE forecast_origin = DATE '{scored_origin}'
          AND training_eligible
          AND target_units_h1 IS NOT NULL
        ORDER BY market_id, store_id, channel_id, sku_id
        """
    ).fetchdf()
    connection.close()
    if training.empty or evaluation.empty:
        raise RuntimeError("W0.6 could not construct a representative full-data fold")
    return training, evaluation, scored_origin


def _prepare(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    prepared = frame.copy()
    target = pd.to_numeric(prepared.pop("target_units"), errors="raise")
    for column in NUMERIC_SPIKE_FEATURES:
        prepared[column] = pd.to_numeric(
            prepared[column],
            errors="coerce",
        ).fillna(0.0)
    for column in CATEGORICAL_SPIKE_FEATURES:
        prepared[column] = prepared[column].fillna("unknown").astype("category")
    return prepared[list(SPIKE_FEATURES)], target


def run_memory_spike(
    repository_root: str | Path,
    report_path: str | Path,
) -> dict[str, Any]:
    """Build the full panel, fit one h1/P50 fold, and record native peak RSS."""

    root = Path(repository_root).resolve()
    report = Path(report_path).resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    runtime = resolve_ml_runtime_profile(
        "safe",
        overrides={"memoryLimitGb": 16},
        environment={},
    )
    stages: dict[str, str] = {}
    total_started = time.monotonic()
    with _PeakRssSampler() as sampler:
        verify_started = time.monotonic()
        bundle = discover_input_bundle(root).verify()
        stages["bundleVerificationSeconds"] = f"{time.monotonic() - verify_started:.6f}"

        with tempfile.TemporaryDirectory(prefix="retail-ml-w0-spike-") as temporary:
            feature_started = time.monotonic()
            temporary_root = Path(temporary)
            stats, feature_output = build_features(
                bundle,
                temporary_root / "features",
                runtime_profile=runtime,
            )
            feature_path = feature_output / "weekly_features.parquet"
            stages["featureBuildSeconds"] = f"{time.monotonic() - feature_started:.6f}"

            fold_load_started = time.monotonic()
            training, evaluation, scored_origin = _load_fold(
                feature_path,
                runtime.feature_workers,
            )
            train_x, train_y = _prepare(training)
            eval_x, eval_y = _prepare(evaluation)
            for column in CATEGORICAL_SPIKE_FEATURES:
                eval_x[column] = pd.Categorical(
                    eval_x[column],
                    categories=train_x[column].cat.categories,
                )
            stages["foldLoadSeconds"] = f"{time.monotonic() - fold_load_started:.6f}"

            train_started = time.monotonic()
            model = lgb.LGBMRegressor(
                objective="quantile",
                alpha=0.5,
                n_estimators=400,
                learning_rate=0.04,
                num_leaves=31,
                min_child_samples=30,
                subsample=1.0,
                colsample_bytree=1.0,
                random_state=20260730,
                deterministic=True,
                force_col_wise=True,
                n_jobs=runtime.threads_per_model,
                verbosity=-1,
            )
            model.fit(
                train_x,
                train_y,
                categorical_feature=list(CATEGORICAL_SPIKE_FEATURES),
            )
            predictions = model.predict(eval_x)
            denominator = float(eval_y.sum())
            wape = (
                float(abs(eval_y.to_numpy() - predictions).sum()) / denominator
                if denominator > 0
                else None
            )
            stages["oneFoldTrainingSeconds"] = f"{time.monotonic() - train_started:.6f}"

            feature_bytes = feature_path.stat().st_size
            fold = {
                "horizon": 1,
                "quantile": "0.50",
                "scoredOrigin": scored_origin,
                "trainingOrigins": 104,
                "trainingRows": len(training),
                "evaluationRows": len(evaluation),
                "trees": 400,
                "wapeDiagnostic": None if wape is None else f"{wape:.8f}",
            }

    peak_gib = sampler.peak_bytes / (1024**3)
    configured_gib = runtime.memory_limit_gb
    result: dict[str, Any] = {
        "schemaVersion": "retail-ml-memory-spike/v1",
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "inputBundle": bundle.identity,
        "executionProfile": runtime.as_manifest_dict(),
        "environment": {
            "platform": platform.platform(),
            "logicalCpuCount": psutil.cpu_count(logical=True),
            "physicalCpuCount": psutil.cpu_count(logical=False),
            "availableMemoryBytesAtReport": psutil.virtual_memory().available,
            "versions": {
                package: version(package)
                for package in (
                    "duckdb",
                    "lightgbm",
                    "numpy",
                    "pandas",
                    "pyarrow",
                    "psutil",
                    "scikit-learn",
                )
            },
        },
        "featureBuild": {
            **stats.__dict__,
            "parquetBytes": feature_bytes,
        },
        "representativeFold": fold,
        "stageTelemetry": stages,
        "totalSeconds": f"{time.monotonic() - total_started:.6f}",
        "peakRssBytes": sampler.peak_bytes,
        "peakRssGiB": f"{peak_gib:.6f}",
        "memoryLimitGiB": configured_gib,
        "memoryHeadroomGiB": f"{configured_gib - peak_gib:.6f}",
        "boundedBatchingRequired": peak_gib > configured_gib * 0.8,
        "verdict": "pass" if peak_gib <= configured_gib else "fail_oom_risk",
    }
    report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


__all__ = ["run_memory_spike"]
