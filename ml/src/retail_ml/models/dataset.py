"""Bounded long-frame readers for horizon training and evaluation."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Final

import duckdb
import pandas as pd

from retail_ml.features.availability import HORIZONS, LABEL_EMBARGO_WEEKS
from retail_ml.models.backtest import TRAINING_ORIGINS, rolling_origin_schedule

BASE_MODEL_COLUMNS: Final[tuple[str, ...]] = (
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
    "weather_tavg_origin",
    "weather_precip_origin",
    "weather_tavg_climatology",
    "weather_precip_climatology",
    "weather_tavg_forecast_h1",
    "weather_precip_forecast_h1",
    "weather_forecast_coverage_days_h1",
    "macro_index_value",
    "competitor_price_ratio",
    "competitor_available",
    "competitor_in_stock",
    "competitor_age_days",
    "origin_year",
    "market_id",
    "store_id",
    "channel_id",
    "dept_id",
    "category",
    "sub_cat",
)
IDENTITY_COLUMNS: Final[tuple[str, ...]] = (
    "sku_id",
    "store_id",
    "channel_id",
    "market_id",
    "dept_id",
    "category",
    "sub_cat",
)


def _external_horizon_columns(horizon: int) -> str:
    return f"""
        CASE
            WHEN {horizon} = 1
             AND weather_forecast_coverage_days_h1 = 7
            THEN weather_tavg_forecast_h1
            ELSE weather_tavg_climatology
        END AS weather_tavg_horizon,
        CASE
            WHEN {horizon} = 1
             AND weather_forecast_coverage_days_h1 = 7
            THEN weather_precip_forecast_h1
            ELSE weather_precip_climatology
        END AS weather_precip_horizon,
        CASE
            WHEN {horizon} = 1
             AND weather_forecast_coverage_days_h1 = 7
            THEN 0 ELSE 1
        END AS weather_fallback_used
    """.strip()


def _escaped(path: Path) -> str:
    return str(path.resolve()).replace("'", "''")


def eligible_scoring_origins(feature_path: str | Path) -> list[date]:
    source = _escaped(Path(feature_path))
    connection = duckdb.connect()
    rows = connection.execute(
        f"""
        SELECT DISTINCT forecast_origin
        FROM read_parquet('{source}')
        WHERE training_eligible
          AND units_lag_52 IS NOT NULL
          AND target_units_h26 IS NOT NULL
        ORDER BY forecast_origin
        """
    ).fetchall()
    connection.close()
    return rolling_origin_schedule([row[0] for row in rows])


def load_training_horizon(
    feature_path: str | Path,
    *,
    scored_origin: date,
    horizon: int,
    train_origin_count: int = TRAINING_ORIGINS,
    threads: int = 1,
) -> pd.DataFrame:
    if horizon not in HORIZONS:
        raise ValueError(f"unsupported horizon {horizon}")
    source = _escaped(Path(feature_path))
    selected = ", ".join(BASE_MODEL_COLUMNS)
    connection = duckdb.connect()
    connection.execute(f"SET threads = {int(threads)}")
    frame = connection.execute(
        f"""
        WITH training_origins AS (
            SELECT forecast_origin
            FROM (
                SELECT DISTINCT forecast_origin
                FROM read_parquet('{source}')
                WHERE training_eligible
                  AND units_lag_52 IS NOT NULL
                  AND forecast_origin
                      <= DATE '{scored_origin.isoformat()}'
                         - INTERVAL {LABEL_EMBARGO_WEEKS} WEEK
                ORDER BY forecast_origin DESC
                LIMIT {int(train_origin_count)}
            )
        )
        SELECT
            sku_id,
            {selected},
            forecast_origin,
            {horizon} AS horizon,
            working_days_h{horizon} AS working_days_horizon,
            {_external_horizon_columns(horizon)},
            target_units_h{horizon} AS target_units,
            target_known_as_of_h{horizon} AS target_known_as_of
        FROM read_parquet('{source}')
        WHERE forecast_origin IN (SELECT forecast_origin FROM training_origins)
          AND training_eligible
          AND target_units_h{horizon} IS NOT NULL
          AND target_known_as_of_h{horizon}
              <= DATE '{scored_origin.isoformat()}' + INTERVAL 6 DAY
        ORDER BY market_id, store_id, channel_id, sku_id, forecast_origin
        """
    ).fetchdf()
    connection.close()
    return frame


def load_evaluation_horizon(
    feature_path: str | Path,
    *,
    scored_origin: date,
    horizon: int,
    threads: int = 1,
) -> pd.DataFrame:
    if horizon not in HORIZONS:
        raise ValueError(f"unsupported horizon {horizon}")
    source = _escaped(Path(feature_path))
    selected = ", ".join(BASE_MODEL_COLUMNS)
    connection = duckdb.connect()
    connection.execute(f"SET threads = {int(threads)}")
    frame = connection.execute(
        f"""
        SELECT
            sku_id,
            {selected},
            forecast_origin,
            CAST(
                forecast_origin + INTERVAL {horizon} WEEK
                AS DATE
            ) AS target_week_start,
            {horizon} AS horizon,
            working_days_h{horizon} AS working_days_horizon,
            {_external_horizon_columns(horizon)},
            target_units_h{horizon} AS actual_units
        FROM read_parquet('{source}')
        WHERE forecast_origin = DATE '{scored_origin.isoformat()}'
          AND training_eligible
          AND target_units_h{horizon} IS NOT NULL
        ORDER BY market_id, store_id, channel_id, sku_id
        """
    ).fetchdf()
    connection.close()
    return frame


def load_current_horizon(
    feature_path: str | Path,
    *,
    scored_origin: date,
    horizon: int,
    decision_as_of: datetime,
    threads: int = 1,
) -> pd.DataFrame:
    """Load one future-only scoring row per active SeriesKey.

    Current-cycle scoring deliberately does not require ``training_eligible``:
    the decision week may be a retained partial boundary week. Its first target
    week must nevertheless be wholly after the decision date, and every source
    value used by the feature row must be available by that decision.
    """

    if horizon not in HORIZONS:
        raise ValueError(f"unsupported horizon {horizon}")
    if decision_as_of.tzinfo is None:
        raise ValueError("decision_as_of must be timezone-aware")
    if pd.Timestamp(scored_origin) + pd.Timedelta(weeks=1) <= pd.Timestamp(
        decision_as_of.date()
    ):
        raise ValueError("current-cycle h1 must start after decision_as_of")
    decision_timestamp = decision_as_of.isoformat()
    source = _escaped(Path(feature_path))
    selected = ", ".join(BASE_MODEL_COLUMNS)
    connection = duckdb.connect()
    connection.execute(f"SET threads = {int(threads)}")
    frame = connection.execute(
        f"""
        SELECT
            sku_id,
            {selected},
            forecast_origin,
            week_end,
            source_known_as_of,
            exposure_days,
            CAST(
                forecast_origin + INTERVAL {horizon} WEEK
                AS DATE
            ) AS target_week_start,
            {horizon} AS horizon,
            working_days_h{horizon} AS working_days_horizon,
            {_external_horizon_columns(horizon)}
        FROM read_parquet('{source}')
        WHERE forecast_origin = DATE '{scored_origin.isoformat()}'
          AND source_known_as_of
              <= TIMESTAMPTZ '{decision_timestamp}'
        ORDER BY market_id, store_id, channel_id, sku_id
        """
    ).fetchdf()
    connection.close()
    if frame.empty:
        raise ValueError("no current-cycle rows are available at decision_as_of")
    duplicate = frame.duplicated(
        ["sku_id", "store_id", "channel_id"],
        keep=False,
    )
    if duplicate.any():
        raise ValueError("current-cycle feature rows duplicate a SeriesKey")
    return frame


__all__ = [
    "BASE_MODEL_COLUMNS",
    "IDENTITY_COLUMNS",
    "eligible_scoring_origins",
    "load_current_horizon",
    "load_evaluation_horizon",
    "load_training_horizon",
]
