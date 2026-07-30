"""Build the immutable, schema-controlled forecast-run artifact bundle.

The publisher derives only facts with frozen formulas. Exception and data-quality
classifications are required inputs because their business policies are not model
metrics and must not be invented during serialization.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ml.features.availability import HORIZONS, LABEL_EMBARGO_WEEKS
from retail_ml.keys import SeriesKey
from retail_ml.models.backtest import (
    ACCEPTANCE_SCHEMA_VERSION,
    EVALUATION_WINDOW_WEEKS,
    ORIGIN_STEP_WEEKS,
    SCORING_ORIGINS,
    SLOW_MOVER_THRESHOLD,
    TRAINING_ORIGINS,
    evaluate_acceptance,
)
from retail_ml.models.drivers import aggregate_driver_rows
from retail_ml.models.confidence import forecast_confidence
from retail_ml.policies.classification import load_classification_policy
from retail_ml.runtime.profile import MLRuntimeProfile

RUN_SCHEMA_VERSION: Final[str] = "retail-forecast-run/v2"
ACCEPTANCE_EVALUATION_VERSION: Final[str] = (
    "paired-seasonal-complete-recomputation/v3"
)
ARTIFACT_SCHEMAS: Final[dict[str, str]] = {
    "forecast_versions": "retail-v2-forecast-versions/v1",
    "forecast_series": "retail-v2-forecast-series/v1",
    "forecast_drivers": "retail-v2-forecast-drivers/v1",
    "forecast_eval_predictions": "retail-forecast-eval-predictions/v1",
    "forecast_baseline_predictions": "retail-forecast-baseline-predictions/v1",
    "forecast_metrics": "retail-forecast-metrics/v1",
    "forecast_exceptions": "retail-forecast-exceptions/v1",
    "forecast_data_quality": "retail-forecast-data-quality/v1",
    "forecast_calibration": "retail-forecast-calibration/v1",
    "forecast_acceptance": ACCEPTANCE_SCHEMA_VERSION,
}
RUN_VOLATILE_POINTERS: Final[tuple[str, ...]] = (
    "/createdAt",
    "/executionProfile",
    "/stageTelemetry",
    "/mlflowRunId",
    *tuple(
        f"/artifacts/{name}/{field}"
        for name in ARTIFACT_SCHEMAS
        for field in ("path", "bytes", "sha256")
    ),
)
SERIES_COLUMNS: Final[tuple[str, ...]] = (
    "sku_id",
    "store_id",
    "channel_id",
)
EVALUATION_KEY_COLUMNS: Final[tuple[str, ...]] = (
    "forecast_origin",
    "target_week_start",
    "market_id",
    "sku_id",
    "store_id",
    "channel_id",
    "horizon",
)
BASELINE_COLUMNS: Final[dict[str, str]] = {
    "naive": "naive_baseline",
    "seasonal_naive": "seasonal_naive_baseline",
    "ma8": "ma8_baseline",
    "ma13": "ma13_baseline",
}


class ForecastPublicationError(RuntimeError):
    """A candidate cannot satisfy the immutable run-bundle contract."""


def model_policy() -> dict[str, Any]:
    """Return the exact semantic model and acceptance policy for this publisher."""

    return {
        "horizonWeeks": list(HORIZONS),
        "evaluationWindowWeeks": EVALUATION_WINDOW_WEEKS,
        "scoringOriginStepWeeks": ORIGIN_STEP_WEEKS,
        "scoringOrigins": SCORING_ORIGINS,
        "trainingOrigins": TRAINING_ORIGINS,
        "labelEmbargoWeeks": LABEL_EMBARGO_WEEKS,
        "slowMoverZeroShareThreshold": "0.60",
        "seriesKeyFields": list(SERIES_COLUMNS),
        "marketFeature": "market_id",
        "metricAggregation": "additive_components",
        "promotionFeature": "unavailable",
        "acceptanceEvaluation": ACCEPTANCE_EVALUATION_VERSION,
    }


@dataclass(frozen=True)
class ForecastRunPublication:
    forecast_run_id: str
    semantic_fingerprint: str
    lifecycle_status: str
    output_dir: str
    row_counts: dict[str, int]


def _require_columns(
    frame: pd.DataFrame,
    required: set[str],
    *,
    label: str,
) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ForecastPublicationError(
            f"{label} is missing required columns: {', '.join(missing)}"
        )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        timestamp = pd.Timestamp(value)
        return timestamp.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        if not math.isfinite(numeric):
            return None
        if numeric == 0:
            return "0"
        return format(numeric, ".17g")
    return str(value)


def _frame_semantic_fingerprint(
    frame: pd.DataFrame,
    *,
    schema_version: str,
) -> str:
    """Hash canonical logical rows, independent of Parquet encoding metadata."""

    digest = hashlib.sha256()
    header = {
        "schemaVersion": schema_version,
        "columns": list(frame.columns),
        "rowCount": len(frame),
    }
    digest.update(
        json.dumps(header, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        .encode("utf-8")
    )
    digest.update(b"\n")
    for row in frame.itertuples(index=False, name=None):
        normalized = [_normalized_scalar(value) for value in row]
        digest.update(
            json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        digest.update(b"\n")
    return digest.hexdigest()


def _json_semantic_fingerprint(
    document: dict[str, Any],
    *,
    schema_version: str,
) -> str:
    frame = pd.DataFrame(
        [
            {
                "schemaVersion": schema_version,
                "document": json.dumps(
                    document,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            }
        ]
    )
    return _frame_semantic_fingerprint(frame, schema_version=schema_version)


def _validate_complete_schedule(frame: pd.DataFrame) -> None:
    _require_columns(
        frame,
        {"forecast_origin", "horizon"},
        label="evaluation predictions",
    )
    horizons = tuple(sorted(pd.to_numeric(frame["horizon"]).astype(int).unique()))
    if horizons != HORIZONS:
        raise ForecastPublicationError(
            "forecast-run publication requires all horizons h1..h26"
        )
    origins = tuple(sorted(pd.to_datetime(frame["forecast_origin"]).dt.date.unique()))
    if len(origins) != SCORING_ORIGINS:
        raise ForecastPublicationError(
            "forecast-run publication requires exactly 13 scoring origins"
        )
    observed = {
        (pd.Timestamp(origin).date(), int(horizon))
        for origin, horizon in frame[["forecast_origin", "horizon"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }
    expected = {(origin, horizon) for origin in origins for horizon in HORIZONS}
    if observed != expected:
        raise ForecastPublicationError(
            "forecast-run evaluation is missing an origin/horizon pair"
        )


def derive_evaluation_predictions(evaluation: pd.DataFrame) -> pd.DataFrame:
    required = {
        *EVALUATION_KEY_COLUMNS,
        "dept_id",
        "category",
        "actual_units",
        "yhat_p50",
        "yhat_p90",
        "confidence",
        "selected_model",
        "zero_share_52w",
    }
    _require_columns(evaluation, required, label="evaluation predictions")
    _validate_complete_schedule(evaluation)
    columns = [
        *EVALUATION_KEY_COLUMNS,
        "dept_id",
        "category",
        "actual_units",
        "yhat_p50",
        "yhat_p90",
        "confidence",
        "selected_model",
        "zero_share_52w",
    ]
    result = evaluation[columns].copy()
    if result.duplicated(list(EVALUATION_KEY_COLUMNS), keep=False).any():
        raise ForecastPublicationError(
            "evaluation predictions duplicate the canonical evaluation key"
        )
    actual = pd.to_numeric(result["actual_units"], errors="coerce")
    prediction = pd.to_numeric(result["yhat_p50"], errors="coerce")
    upper = pd.to_numeric(result["yhat_p90"], errors="coerce")
    confidence = pd.to_numeric(result["confidence"], errors="coerce")
    if (
        actual.isna().any()
        or prediction.isna().any()
        or upper.isna().any()
        or confidence.isna().any()
        or not np.isfinite(actual).all()
        or not np.isfinite(prediction).all()
        or not np.isfinite(upper).all()
    ):
        raise ForecastPublicationError(
            "evaluation actual/P50/P90/confidence values must all be finite numbers"
        )
    expected_confidence = forecast_confidence(prediction, upper)
    if not np.allclose(
        confidence.to_numpy(dtype=float),
        expected_confidence,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ForecastPublicationError(
            "evaluation confidence violates decision #12"
        )
    result["abs_error_sum"] = (prediction - actual).abs()
    result["signed_error_sum"] = prediction - actual
    result["actual_sum"] = actual
    result["coverage_hits"] = (actual <= upper).astype("int64")
    result["n"] = np.int64(1)
    return result.sort_values(list(EVALUATION_KEY_COLUMNS)).reset_index(drop=True)


def derive_baseline_predictions(evaluation: pd.DataFrame) -> pd.DataFrame:
    required = {*EVALUATION_KEY_COLUMNS, *BASELINE_COLUMNS.values()}
    _require_columns(evaluation, required, label="baseline predictions")
    result = evaluation[
        [*EVALUATION_KEY_COLUMNS, *BASELINE_COLUMNS.values()]
    ].melt(
        id_vars=list(EVALUATION_KEY_COLUMNS),
        value_vars=list(BASELINE_COLUMNS.values()),
        var_name="baseline_column",
        value_name="prediction",
    )
    inverse = {column: name for name, column in BASELINE_COLUMNS.items()}
    result["baseline_id"] = result.pop("baseline_column").map(inverse)
    return result[
        [*EVALUATION_KEY_COLUMNS, "baseline_id", "prediction"]
    ].sort_values(
        [*EVALUATION_KEY_COLUMNS, "baseline_id"]
    ).reset_index(drop=True)


def _scope_key(values: tuple[Any, ...], *, default: str) -> str:
    if not values:
        return default
    if len(values) == 1:
        return str(values[0])
    return json.dumps(
        [_normalized_scalar(value) for value in values],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _metric_rows_for_scope(
    frame: pd.DataFrame,
    *,
    prediction_column: str,
    model_id: str,
    scope_type: str,
    scope_columns: tuple[str, ...],
    default_scope_key: str = "portfolio",
) -> list[dict[str, Any]]:
    working = frame.copy()
    actual = pd.to_numeric(working["actual_units"], errors="coerce")
    prediction = pd.to_numeric(working[prediction_column], errors="coerce")
    valid = actual.notna() & prediction.notna()
    if model_id == "champion":
        upper = pd.to_numeric(working["yhat_p90"], errors="coerce")
        valid &= upper.notna()
    working = working.loc[valid].copy()
    actual = actual.loc[valid]
    prediction = prediction.loc[valid]
    working["_abs"] = (prediction - actual).abs()
    working["_signed"] = prediction - actual
    working["_actual"] = actual
    working["_hits"] = (
        actual <= pd.to_numeric(working["yhat_p90"], errors="coerce")
    ).astype("int64") if model_id == "champion" else 0
    working["_n"] = 1
    rows: list[dict[str, Any]] = []
    for include_horizon in (False, True):
        grouping = [*scope_columns]
        if include_horizon:
            grouping.append("horizon")
        if grouping:
            grouped: Any = working.groupby(
                grouping,
                sort=True,
                observed=True,
                dropna=False,
            )
        else:
            grouped = [((), working)]
        iterator = grouped if isinstance(grouped, list) else grouped
        for raw_key, group in iterator:
            if grouping:
                values = raw_key if isinstance(raw_key, tuple) else (raw_key,)
            else:
                values = ()
            if include_horizon:
                horizon = int(values[-1])
                scope_values = values[:-1]
            else:
                horizon = 0
                scope_values = values
            abs_error_sum = float(group["_abs"].sum())
            signed_error_sum = float(group["_signed"].sum())
            actual_sum = float(group["_actual"].sum())
            coverage_hits = int(group["_hits"].sum())
            n = int(group["_n"].sum())
            wape = abs_error_sum / actual_sum if actual_sum > 0 else None
            rows.append(
                {
                    "slice_type": scope_type,
                    "slice_id": _scope_key(
                        tuple(scope_values),
                        default=default_scope_key,
                    ),
                    "horizon": horizon,
                    "model_id": model_id,
                    "abs_error_sum": abs_error_sum,
                    "signed_error_sum": signed_error_sum,
                    "actual_sum": actual_sum,
                    "coverage_hits": coverage_hits,
                    "n": n,
                    "wape": wape,
                    "bias": signed_error_sum / actual_sum if actual_sum > 0 else None,
                    "accuracy": 100.0 * (1.0 - wape) if wape is not None else None,
                    "p90_coverage": (
                        coverage_hits / n if model_id == "champion" and n else None
                    ),
                }
            )
    return rows


def derive_forecast_metrics(evaluation: pd.DataFrame) -> pd.DataFrame:
    required = {
        *EVALUATION_KEY_COLUMNS,
        "dept_id",
        "category",
        "actual_units",
        "yhat_p50",
        "yhat_p90",
        "zero_share_52w",
        *BASELINE_COLUMNS.values(),
    }
    _require_columns(evaluation, required, label="forecast metrics")
    scopes: tuple[tuple[str, tuple[str, ...], pd.DataFrame], ...] = (
        ("global", (), evaluation),
        ("market", ("market_id",), evaluation),
        ("store", ("store_id",), evaluation),
        ("category", ("market_id", "category"), evaluation),
        ("department", ("market_id", "dept_id"), evaluation),
        ("channel", ("channel_id",), evaluation),
        ("series", SERIES_COLUMNS, evaluation),
        (
            "slow_mover",
            (),
            evaluation[
                pd.to_numeric(
                    evaluation["zero_share_52w"],
                    errors="coerce",
                ).fillna(0.0)
                > SLOW_MOVER_THRESHOLD
            ],
        ),
        (
            "slow_mover_market",
            ("market_id",),
            evaluation[
                pd.to_numeric(
                    evaluation["zero_share_52w"],
                    errors="coerce",
                ).fillna(0.0)
                > SLOW_MOVER_THRESHOLD
            ],
        ),
    )
    models = (("champion", "yhat_p50"), *BASELINE_COLUMNS.items())
    rows: list[dict[str, Any]] = []
    for model_id, prediction_column in models:
        for scope_type, scope_columns, scoped in scopes:
            if scoped.empty:
                continue
            rows.extend(
                _metric_rows_for_scope(
                    scoped,
                    prediction_column=prediction_column,
                    model_id=model_id,
                    scope_type=scope_type,
                    scope_columns=scope_columns,
                )
            )
    for scope_type, scope_columns, scoped in scopes:
        if scoped.empty:
            continue
        seasonal = pd.to_numeric(
            scoped["seasonal_naive_baseline"],
            errors="coerce",
        )
        paired = scoped.loc[seasonal.notna() & np.isfinite(seasonal)].copy()
        if paired.empty:
            continue
        rows.extend(
            _metric_rows_for_scope(
                paired,
                prediction_column="yhat_p50",
                model_id="champion_seasonal_paired",
                scope_type=scope_type,
                scope_columns=scope_columns,
            )
        )
    result = pd.DataFrame(rows)
    index_columns = ["slice_type", "slice_id", "horizon"]
    lookup = result.set_index([*index_columns, "model_id"])["wape"]
    result["fva_vs_ma13_pct"] = np.nan
    result["improvement_vs_seasonal_naive_pct"] = np.nan
    champion = result["model_id"].eq("champion")
    for index in result.index[champion]:
        key = tuple(result.loc[index, column] for column in index_columns)
        champion_wape = result.at[index, "wape"]
        paired_champion_wape = lookup.get(
            (*key, "champion_seasonal_paired")
        )
        ma13_wape = lookup.get((*key, "ma13"))
        seasonal_wape = lookup.get((*key, "seasonal_naive"))
        if pd.notna(champion_wape) and pd.notna(ma13_wape) and ma13_wape != 0:
            result.at[index, "fva_vs_ma13_pct"] = (
                (ma13_wape - champion_wape) / ma13_wape * 100.0
            )
        if (
            pd.notna(paired_champion_wape)
            and pd.notna(seasonal_wape)
            and seasonal_wape != 0
        ):
            result.at[index, "improvement_vs_seasonal_naive_pct"] = (
                (seasonal_wape - paired_champion_wape)
                / seasonal_wape
                * 100.0
            )
    return result.sort_values(
        [*index_columns, "model_id"]
    ).reset_index(drop=True)


def _validated_governed_frame(
    frame: pd.DataFrame,
    *,
    label: str,
    required: set[str],
    sort_columns: list[str],
) -> pd.DataFrame:
    _require_columns(frame, required, label=label)
    duplicate = frame.duplicated(sort_columns, keep=False)
    if duplicate.any():
        raise ForecastPublicationError(
            f"{label} contains duplicate canonical keys"
        )
    return frame.sort_values(sort_columns).reset_index(drop=True).copy()


def _validated_current_forecasts(
    frame: pd.DataFrame,
    *,
    decision_as_of: datetime,
) -> pd.DataFrame:
    required = {
        *SERIES_COLUMNS,
        "forecast_origin",
        "target_week_start",
        "horizon",
        "yhat_p50",
        "yhat_p90",
        "confidence",
        "selected_model",
    }
    _require_columns(frame, required, label="current forecasts")
    if "actual_units" in frame and frame["actual_units"].notna().any():
        raise ForecastPublicationError(
            "current forecasts must not contain observed actual labels"
        )
    result = frame.copy()
    duplicate = result.duplicated(
        [*SERIES_COLUMNS, "horizon"],
        keep=False,
    )
    if duplicate.any():
        raise ForecastPublicationError(
            "current forecasts duplicate the canonical series/horizon key"
        )
    origins = pd.to_datetime(result["forecast_origin"]).dt.date.unique()
    if len(origins) != 1:
        raise ForecastPublicationError(
            "current forecasts must contain exactly one forecast origin"
        )
    horizons = tuple(
        sorted(pd.to_numeric(result["horizon"], errors="raise").astype(int).unique())
    )
    if horizons != HORIZONS:
        raise ForecastPublicationError(
            "current forecasts require all horizons h1..h26"
        )
    target_dates = pd.to_datetime(result["target_week_start"]).dt.date
    if not (target_dates > decision_as_of.date()).all():
        raise ForecastPublicationError(
            "current forecasts must contain only future target weeks"
        )
    keys_by_horizon = {
        horizon: {
            tuple(str(value) for value in row)
            for row in group[list(SERIES_COLUMNS)].itertuples(
                index=False,
                name=None,
            )
        }
        for horizon, group in result.groupby("horizon", observed=True)
    }
    first_keys = keys_by_horizon[HORIZONS[0]]
    if any(keys != first_keys for keys in keys_by_horizon.values()):
        raise ForecastPublicationError(
            "every current horizon must contain the same SeriesKey set"
        )
    p50 = pd.to_numeric(result["yhat_p50"], errors="coerce")
    p90 = pd.to_numeric(result["yhat_p90"], errors="coerce")
    confidence = pd.to_numeric(result["confidence"], errors="coerce")
    if (
        p50.isna().any()
        or p90.isna().any()
        or confidence.isna().any()
        or (p50 < 0).any()
        or (p90 < p50).any()
        or ((confidence < 0) | (confidence > 1)).any()
    ):
        raise ForecastPublicationError(
            "current P50/P90/confidence values violate the canonical domain"
        )
    if not np.allclose(
        confidence.to_numpy(dtype=float),
        forecast_confidence(p50, p90),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ForecastPublicationError(
            "current confidence violates decision #12"
        )
    return result.sort_values(
        [*SERIES_COLUMNS, "horizon"]
    ).reset_index(drop=True)


def _canonical_current_artifacts(
    current: pd.DataFrame,
    evaluation: pd.DataFrame,
    *,
    acceptance: dict[str, Any],
    input_bundle: dict[str, str],
    feature_semantic_fingerprint: str,
    classification_policies: dict[str, dict[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    current_fingerprint = _frame_semantic_fingerprint(
        current,
        schema_version="retail-forecast-current-predictions/v1",
    )
    origin = pd.Timestamp(current["forecast_origin"].iloc[0]).date()
    version_seed = {
        "schemaVersion": "retail-forecast-version/v1",
        "originDate": origin.isoformat(),
        "horizonWeeks": len(HORIZONS),
        "inputBundle": input_bundle,
        "featureSemanticFingerprint": feature_semantic_fingerprint,
        "currentForecastSemanticFingerprint": current_fingerprint,
        "classificationPolicies": classification_policies,
    }
    version_fingerprint = semantic_fingerprint(
        version_seed,
        volatile_pointers=(),
    )
    version_id = "fv_" + version_fingerprint[:16]
    metrics = derive_forecast_metrics(evaluation)
    global_metric = metrics[
        metrics["slice_type"].eq("global")
        & metrics["slice_id"].eq("portfolio")
        & metrics["horizon"].eq(0)
        & metrics["model_id"].eq("champion")
    ]
    if len(global_metric) != 1:
        raise ForecastPublicationError(
            "accepted evaluation must contain one global champion metric"
        )
    metric = global_metric.iloc[0]
    lifecycle = "accepted" if acceptance["passed"] else "rejected"
    versions = pd.DataFrame(
        [
            {
                "version_id": version_id,
                "kind": "ai",
                "origin_date": origin,
                "horizon_weeks": len(HORIZONS),
                "created_by": "DemandSenseAI",
                "accuracy": metric["accuracy"],
                "bias": metric["bias"],
                "demand_units": int(
                    round(
                        float(
                            pd.to_numeric(
                                current["yhat_p50"],
                                errors="coerce",
                            ).sum()
                        )
                    )
                ),
                "semantic_fingerprint": version_fingerprint,
                "status": lifecycle,
            }
        ]
    )
    series = current[
        [
            *SERIES_COLUMNS,
            "horizon",
            "yhat_p50",
            "yhat_p90",
            "confidence",
        ]
    ].rename(columns={"horizon": "horizon_week"})
    series.insert(0, "version_id", version_id)
    drivers = aggregate_driver_rows(current, include_series=True)[
        [
            "scope",
            "driver",
            "contribution_pct",
            "direction",
            "confidence",
        ]
    ]
    drivers.insert(0, "version_id", version_id)
    return (
        versions,
        series.sort_values(
            [*SERIES_COLUMNS, "horizon_week"]
        ).reset_index(drop=True),
        drivers.sort_values(["scope", "driver"]).reset_index(drop=True),
    )


def _validate_classification_binding(
    current: pd.DataFrame,
    exceptions: pd.DataFrame,
    data_quality: pd.DataFrame,
    *,
    policies: dict[str, dict[str, str]],
) -> None:
    current_keys = {
        tuple(str(value) for value in row)
        for row in current[list(SERIES_COLUMNS)]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    }
    quality_keys = {
        tuple(str(value) for value in row)
        for row in data_quality[list(SERIES_COLUMNS)].itertuples(
            index=False,
            name=None,
        )
    }
    exception_keys = {
        tuple(str(value) for value in row)
        for row in exceptions[list(SERIES_COLUMNS)].itertuples(
            index=False,
            name=None,
        )
    }
    if quality_keys != current_keys:
        raise ForecastPublicationError(
            "data-quality classifications must cover every current SeriesKey"
        )
    if not exception_keys <= current_keys:
        raise ForecastPublicationError(
            "forecast exceptions contain a non-current SeriesKey"
        )
    for frame, policy_name, label in (
        (exceptions, "exceptions", "forecast exceptions"),
        (data_quality, "dataQuality", "forecast data quality"),
    ):
        expected = policies[policy_name]
        if frame.empty:
            continue
        if (
            set(frame["policy_id"].astype(str)) != {expected["policyId"]}
            or set(frame["policy_semantic_fingerprint"].astype(str))
            != {expected["semanticFingerprint"]}
        ):
            raise ForecastPublicationError(
                f"{label} is not bound to frozen decision #60"
            )


def _validated_classification_policies(
    policies: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    if set(policies) != {"exceptions", "dataQuality"}:
        raise ForecastPublicationError(
            "classification_policies must contain exceptions and dataQuality"
        )
    result: dict[str, dict[str, str]] = {}
    for name in ("exceptions", "dataQuality"):
        policy = policies[name]
        if set(policy) != {"policyId", "semanticFingerprint"}:
            raise ForecastPublicationError(
                f"classification policy {name} has an invalid shape"
            )
        policy_id = policy["policyId"]
        fingerprint = policy["semanticFingerprint"]
        if not policy_id:
            raise ForecastPublicationError(
                f"classification policy {name} requires policyId"
            )
        if (
            len(fingerprint) != 64
            or any(character not in "0123456789abcdef" for character in fingerprint)
        ):
            raise ForecastPublicationError(
                f"classification policy {name} has an invalid semanticFingerprint"
            )
        result[name] = dict(policy)
    expected = load_classification_policy().bindings()
    if result != expected:
        raise ForecastPublicationError(
            "classification policies differ from frozen decision #60"
        )
    return result


def _validate_calibration_schedule(
    calibration: pd.DataFrame,
    evaluation: pd.DataFrame,
) -> None:
    origins = tuple(
        sorted(pd.to_datetime(evaluation["forecast_origin"]).dt.date.unique())
    )
    markets = tuple(sorted(evaluation["market_id"].astype(str).unique()))
    actual: set[tuple[date, int, str, str]] = set()
    for scored_origin, horizon, scope, market_id in calibration[
        ["scored_origin", "horizon", "scope", "market_id"]
    ].itertuples(index=False, name=None):
        actual.add(
            (
                pd.Timestamp(scored_origin).date(),
                int(horizon),
                str(scope),
                "" if pd.isna(market_id) else str(market_id),
            )
        )
    expected = {
        (origin, horizon, "global", "")
        for origin in origins
        for horizon in HORIZONS
    }
    expected.update(
        (origin, horizon, "market", market)
        for origin in origins
        for horizon in HORIZONS
        for market in markets
    )
    if actual != expected:
        raise ForecastPublicationError(
            "forecast calibration does not cover every scoring origin, horizon, "
            "and supported market exactly once"
        )


def _write_frame(
    staging: Path,
    *,
    name: str,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    path = staging / f"{name}.parquet"
    frame.to_parquet(path, index=False)
    schema_version = ARTIFACT_SCHEMAS[name]
    return {
        "schemaVersion": schema_version,
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "semanticFingerprint": _frame_semantic_fingerprint(
            frame,
            schema_version=schema_version,
        ),
        "rowCount": len(frame),
    }


def _write_acceptance(
    staging: Path,
    acceptance: dict[str, Any],
) -> dict[str, Any]:
    if acceptance.get("schemaVersion") != ARTIFACT_SCHEMAS["forecast_acceptance"]:
        raise ForecastPublicationError(
            "acceptance document has an unsupported schemaVersion"
        )
    if not isinstance(acceptance.get("passed"), bool):
        raise ForecastPublicationError("acceptance document must contain boolean passed")
    path = staging / "forecast_acceptance.json"
    path.write_text(
        json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    schema_version = ARTIFACT_SCHEMAS["forecast_acceptance"]
    return {
        "schemaVersion": schema_version,
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256_file(path),
        "semanticFingerprint": _json_semantic_fingerprint(
            acceptance,
            schema_version=schema_version,
        ),
        "rowCount": 1,
    }


def publish_forecast_run(
    evaluation: pd.DataFrame,
    calibration: pd.DataFrame,
    acceptance: dict[str, Any],
    exceptions: pd.DataFrame,
    data_quality: pd.DataFrame,
    output_dir: str | Path,
    *,
    current_forecasts: pd.DataFrame,
    classification_policies: dict[str, dict[str, str]],
    input_bundle: dict[str, str],
    feature_semantic_fingerprint: str,
    decision_as_of: datetime,
    runtime_profile: MLRuntimeProfile,
    stage_telemetry: dict[str, Any],
    mlflow_run_id: str | None,
    random_seeds: dict[str, int] | None = None,
) -> ForecastRunPublication:
    """Atomically publish a full-schedule accepted or rejected candidate bundle."""

    if decision_as_of.tzinfo is None:
        raise ForecastPublicationError("decision_as_of must be timezone-aware")
    expected_identity = {
        "sourceSnapshotId",
        "gateASemanticFingerprint",
        "gateBSemanticFingerprint",
        "publicationSemanticFingerprint",
    }
    if set(input_bundle) != expected_identity:
        raise ForecastPublicationError(
            "input_bundle must contain exactly the four verified identity fields"
        )
    governed_policies = _validated_classification_policies(classification_policies)
    current_artifact = _validated_current_forecasts(
        current_forecasts,
        decision_as_of=decision_as_of,
    )
    evaluation_artifact = derive_evaluation_predictions(evaluation)
    baseline_artifact = derive_baseline_predictions(evaluation)
    seasonal = baseline_artifact[
        baseline_artifact["baseline_id"].astype(str).eq("seasonal_naive")
    ][[*EVALUATION_KEY_COLUMNS, "prediction"]].rename(
        columns={"prediction": "seasonal_naive_baseline"}
    )
    acceptance_frame = evaluation_artifact.merge(
        seasonal,
        on=list(EVALUATION_KEY_COLUMNS),
        how="left",
        validate="one_to_one",
    )
    derived_acceptance = evaluate_acceptance(acceptance_frame)
    if (
        acceptance.get("schemaVersion")
        != ARTIFACT_SCHEMAS["forecast_acceptance"]
        or not isinstance(acceptance.get("passed"), bool)
        or acceptance["passed"] != derived_acceptance["passed"]
    ):
        raise ForecastPublicationError(
            "supplied acceptance verdict does not match independently "
            "recomputed A1-A5 gates"
        )
    acceptance = derived_acceptance
    metrics_artifact = derive_forecast_metrics(evaluation)
    exception_artifact = _validated_governed_frame(
        exceptions,
        label="forecast exceptions",
        required={
            *SERIES_COLUMNS,
            "exception_class",
            "severity",
            "status",
            "threshold",
            "evidence",
            "policy_id",
            "policy_semantic_fingerprint",
        },
        sort_columns=[*SERIES_COLUMNS, "exception_class"],
    )
    quality_artifact = _validated_governed_frame(
        data_quality,
        label="forecast data quality",
        required={
            *SERIES_COLUMNS,
            "data_quality_class",
            "evidence",
            "policy_id",
            "policy_semantic_fingerprint",
        },
        sort_columns=list(SERIES_COLUMNS),
    )
    _validate_classification_binding(
        current_artifact,
        exception_artifact,
        quality_artifact,
        policies=governed_policies,
    )
    (
        version_artifact,
        series_artifact,
        driver_artifact,
    ) = _canonical_current_artifacts(
        current_artifact,
        evaluation,
        acceptance=acceptance,
        input_bundle=input_bundle,
        feature_semantic_fingerprint=feature_semantic_fingerprint,
        classification_policies=governed_policies,
    )
    calibration_artifact = _validated_governed_frame(
        calibration,
        label="forecast calibration",
        required={
            "scored_origin",
            "scope",
            "market_id",
            "horizon",
            "sufficient",
            "fallback",
            "n_series",
            "n_origins",
            "n_rows",
            "actual_sum",
            "p50_adjustment",
            "p90_adjustment",
        },
        sort_columns=["scored_origin", "scope", "market_id", "horizon"],
    )
    _validate_calibration_schedule(calibration_artifact, evaluation)

    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"forecast-run output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            dir=output.parent,
            prefix=f".{output.name}.staging-",
        )
    )
    try:
        artifacts = {
            "forecast_versions": _write_frame(
                staging,
                name="forecast_versions",
                frame=version_artifact,
            ),
            "forecast_series": _write_frame(
                staging,
                name="forecast_series",
                frame=series_artifact,
            ),
            "forecast_drivers": _write_frame(
                staging,
                name="forecast_drivers",
                frame=driver_artifact,
            ),
            "forecast_eval_predictions": _write_frame(
                staging,
                name="forecast_eval_predictions",
                frame=evaluation_artifact,
            ),
            "forecast_baseline_predictions": _write_frame(
                staging,
                name="forecast_baseline_predictions",
                frame=baseline_artifact,
            ),
            "forecast_metrics": _write_frame(
                staging,
                name="forecast_metrics",
                frame=metrics_artifact,
            ),
            "forecast_exceptions": _write_frame(
                staging,
                name="forecast_exceptions",
                frame=exception_artifact,
            ),
            "forecast_data_quality": _write_frame(
                staging,
                name="forecast_data_quality",
                frame=quality_artifact,
            ),
            "forecast_calibration": _write_frame(
                staging,
                name="forecast_calibration",
                frame=calibration_artifact,
            ),
            "forecast_acceptance": _write_acceptance(staging, acceptance),
        }
        artifacts["forecast_eval_predictions"]["additiveMetricColumns"] = [
            "abs_error_sum",
            "signed_error_sum",
            "actual_sum",
            "coverage_hits",
            "n",
        ]
        run_seed = {
            "inputBundle": input_bundle,
            "featureSemanticFingerprint": feature_semantic_fingerprint,
            "decisionAsOf": decision_as_of.astimezone(UTC).isoformat(),
            "artifactSemanticFingerprints": {
                name: descriptor["semanticFingerprint"]
                for name, descriptor in artifacts.items()
            },
            "classificationPolicies": governed_policies,
        }
        forecast_run_id = "fr_" + hashlib.sha256(
            json.dumps(
                run_seed,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()[:16]
        lifecycle_status = "accepted" if acceptance["passed"] else "rejected"
        manifest: dict[str, Any] = {
            "schemaVersion": RUN_SCHEMA_VERSION,
            "forecastRunId": forecast_run_id,
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "decisionAsOf": (
                decision_as_of.astimezone(UTC).isoformat().replace("+00:00", "Z")
            ),
            "inputBundle": input_bundle,
            "featureSemanticFingerprint": feature_semantic_fingerprint,
            "modelPolicy": model_policy(),
            "randomSeeds": random_seeds or {"model": 20260730, "bootstrap": 20260730},
            "pitEligibility": {
                "eligible": False,
                "reasonCode": "LANDING_BACKFILL_DEPENDENCY",
            },
            "lifecycleStatus": lifecycle_status,
            "classificationPolicies": governed_policies,
            "executionProfile": runtime_profile.as_manifest_dict(),
            "stageTelemetry": stage_telemetry,
            "mlflowRunId": mlflow_run_id,
            "fingerprintContract": {
                "schemaVersion": "semantic-fingerprint/v1",
                "volatilePointers": list(RUN_VOLATILE_POINTERS),
            },
            "artifacts": artifacts,
        }
        manifest["semanticFingerprint"] = semantic_fingerprint(
            manifest,
            volatile_pointers=RUN_VOLATILE_POINTERS,
        )
        (staging / "forecast-run-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, output)
    except BaseException:
        if staging.exists():
            for path in sorted(staging.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            staging.rmdir()
        raise
    return ForecastRunPublication(
        forecast_run_id=forecast_run_id,
        semantic_fingerprint=manifest["semanticFingerprint"],
        lifecycle_status=lifecycle_status,
        output_dir=str(output),
        row_counts={
            name: int(descriptor["rowCount"])
            for name, descriptor in artifacts.items()
        },
    )


def series_key_from_row(row: pd.Series) -> SeriesKey:
    """Keep publisher callers on the shared channel-aware key type."""

    return SeriesKey(
        str(row["sku_id"]),
        str(row["store_id"]),
        str(row["channel_id"]),
    )


__all__ = [
    "ACCEPTANCE_EVALUATION_VERSION",
    "ARTIFACT_SCHEMAS",
    "ForecastPublicationError",
    "ForecastRunPublication",
    "RUN_SCHEMA_VERSION",
    "RUN_VOLATILE_POINTERS",
    "derive_baseline_predictions",
    "derive_evaluation_predictions",
    "derive_forecast_metrics",
    "model_policy",
    "publish_forecast_run",
    "series_key_from_row",
]
