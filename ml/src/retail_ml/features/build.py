"""Build the canonical weekly Phase-3 feature panel from a verified bundle."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.features.assortment import PARTIAL_BOUNDARY_POLICY
from retail_ml.features.availability import (
    FUTURE_CALENDAR_COLUMNS,
    HORIZONS,
    LABEL_EMBARGO_WEEKS,
    TARGET_AVAILABILITY_COLUMNS,
    TARGET_COLUMNS,
)
from retail_ml.io.bundle import VerifiedInputBundle
from retail_ml.io.curated import CuratedReader
from retail_ml.keys import SERIES_KEY_FIELDS
from retail_ml.runtime.profile import MLRuntimeProfile

FEATURE_SCHEMA_VERSION: Final[str] = "retail-weekly-features/v6"
FEATURE_MANIFEST_VOLATILE_POINTERS: Final[tuple[str, ...]] = (
    "/createdAt",
    "/executionProfile",
    "/outputPath",
)


@dataclass(frozen=True)
class FeatureBuildStats:
    feature_rows: int
    training_eligible_rows: int
    series_count: int
    min_forecast_origin: str
    max_forecast_origin: str
    weekly_units: int
    zero_week_share: str
    per_market: dict[str, dict[str, int | str]]


def _window_expression(expression: str, window: int, alias: str) -> str:
    return f"""
        {expression} OVER (
            PARTITION BY sku_id, store_id, channel_id
            ORDER BY week_start
            ROWS BETWEEN {window} PRECEDING AND 1 PRECEDING
        ) AS {alias}
    """.strip()


def weekly_features_sql() -> str:
    """Return the source-neutral `retail_v2` feature query."""

    lag_expressions = ",\n            ".join(
        (
            f"lag(weekly_units_equivalent, {lag}) OVER series_window "
            f"AS units_lag_{lag}"
        )
        for lag in (1, 4, 13, 52)
    )
    rolling_expressions = ",\n            ".join(
        item
        for window in (4, 8, 13, 52)
        for item in (
            _window_expression(
                "avg(weekly_units_equivalent)",
                window,
                f"units_roll_mean_{window}",
            ),
            _window_expression(
                "stddev_samp(weekly_units_equivalent)",
                window,
                f"units_roll_std_{window}",
            ),
        )
    )
    target_expressions = ",\n            ".join(
        f"""
            CASE
                WHEN lead(exposure_days, {horizon}) OVER series_window = 7
                THEN lead(units, {horizon}) OVER series_window
                ELSE NULL
            END AS target_units_h{horizon}
        """.strip()
        for horizon in HORIZONS
    )
    availability_expressions = ",\n            ".join(
        f"""
            CASE
                WHEN lead(exposure_days, {horizon}) OVER series_window = 7
                THEN lead(source_known_as_of, {horizon}) OVER series_window
                ELSE NULL
            END AS target_known_as_of_h{horizon}
        """.strip()
        for horizon in HORIZONS
    )
    calendar_leads = ",\n            ".join(
        f"""
            lead(working_days, {horizon}) OVER market_calendar_window
                AS working_days_h{horizon},
            lead(working_days_known_as_of, {horizon})
                OVER market_calendar_window
                AS working_days_known_as_of_h{horizon}
        """.strip()
        for horizon in HORIZONS
    )
    future_calendar_select = ",\n        ".join(
        f"""
        CASE
            WHEN calendar.working_days_known_as_of_h{horizon} <= features.week_end
            THEN calendar.working_days_h{horizon}
            ELSE NULL
        END AS working_days_h{horizon}
        """.strip()
        for horizon in HORIZONS
    )
    return f"""
    WITH latest_sales AS (
        SELECT *
        FROM sales
        QUALIFY row_number() OVER (
            PARTITION BY sku_id, store_id, channel_id, date
            ORDER BY sales_version DESC, known_as_of DESC
        ) = 1
    ),
    covered_daily AS (
        SELECT
            sales.sku_id,
            sales.store_id,
            sales.channel_id,
            locations.market_id,
            products.dept_id,
            products.category,
            products.sub_cat,
            sales.date,
            CAST(date_trunc('week', sales.date) AS DATE) AS week_start,
            assortment.active_from,
            assortment.active_to,
            sales.units,
            sales.net_price,
            sales.known_as_of
        FROM latest_sales AS sales
        INNER JOIN assortment_calendar AS assortment
            USING (sku_id, store_id, channel_id)
        INNER JOIN locations
            ON locations.location_id = sales.store_id
        INNER JOIN products
            USING (sku_id)
        WHERE sales.date BETWEEN assortment.active_from AND assortment.active_to
    ),
    weekly_raw AS (
        SELECT
            sku_id,
            store_id,
            channel_id,
            market_id,
            dept_id,
            category,
            sub_cat,
            week_start,
            CAST(week_start + INTERVAL 6 DAY AS DATE) AS week_end,
            any_value(active_from) AS active_from,
            any_value(active_to) AS active_to,
            CAST(
                date_diff(
                    'day',
                    greatest(week_start, any_value(active_from)),
                    least(
                        CAST(week_start + INTERVAL 6 DAY AS DATE),
                        any_value(active_to)
                    )
                ) + 1
                AS INTEGER
            ) AS exposure_days,
            sum(units) AS units,
            avg(net_price) FILTER (WHERE units > 0 AND net_price IS NOT NULL)
                AS observed_net_price,
            max(known_as_of) AS source_known_as_of
        FROM covered_daily
        GROUP BY
            sku_id,
            store_id,
            channel_id,
            market_id,
            dept_id,
            category,
            sub_cat,
            week_start
    ),
    weekly_normalized AS (
        SELECT
            *,
            CAST(exposure_days AS DOUBLE) / 7.0 AS exposure_weight,
            CASE
                WHEN exposure_days > 0
                THEN CAST(units AS DOUBLE) * 7.0 / exposure_days
                ELSE NULL
            END AS weekly_units_equivalent,
            CASE WHEN exposure_days = 7 THEN true ELSE false END AS training_eligible,
            observed_net_price / nullif(
                avg(observed_net_price) OVER (
                    PARTITION BY market_id, category, week_start
                ),
                0
            ) AS category_price_index
        FROM weekly_raw
        WHERE exposure_days BETWEEN 1 AND 7
    ),
    market_timezones AS (
        SELECT market_id, any_value(timezone) AS timezone
        FROM locations
        GROUP BY market_id
    ),
    origin_weeks AS (
        SELECT DISTINCT
            weekly.market_id,
            weekly.week_start,
            weekly.week_end,
            zones.timezone,
            timezone(
                zones.timezone,
                CAST(weekly.week_end + INTERVAL 1 DAY AS TIMESTAMP)
            ) AS origin_cutoff
        FROM weekly_normalized AS weekly
        INNER JOIN market_timezones AS zones USING (market_id)
    ),
    weather_weekly_visible AS (
        SELECT
            weather.market_id,
            CAST(date_trunc('week', weather.date) AS DATE) AS week_start,
            avg(CAST(weather.tavg_c AS DOUBLE)) AS weather_tavg_origin,
            sum(CAST(weather.precip_mm AS DOUBLE)) AS weather_precip_origin
        FROM weather_actual AS weather
        INNER JOIN origin_weeks AS origins
            ON origins.market_id = weather.market_id
           AND origins.week_start = CAST(date_trunc('week', weather.date) AS DATE)
        WHERE weather.known_as_of < origins.origin_cutoff
        GROUP BY weather.market_id, date_trunc('week', weather.date)
    ),
    weather_history AS (
        SELECT
            *,
            avg(weather_tavg_origin) OVER (
                PARTITION BY market_id
                ORDER BY week_start
                ROWS BETWEEN 52 PRECEDING AND 1 PRECEDING
            ) AS weather_tavg_climatology,
            avg(weather_precip_origin) OVER (
                PARTITION BY market_id
                ORDER BY week_start
                ROWS BETWEEN 52 PRECEDING AND 1 PRECEDING
            ) AS weather_precip_climatology
        FROM weather_weekly_visible
    ),
    weather_forecast_ranked AS (
        SELECT
            forecast.market_id,
            origins.week_start AS origin_week,
            forecast.target_date,
            CAST(forecast.tavg_c AS DOUBLE) AS tavg_c,
            CAST(forecast.precip_prob AS DOUBLE) AS precip_prob,
            row_number() OVER (
                PARTITION BY
                    forecast.market_id,
                    origins.week_start,
                    forecast.target_date
                ORDER BY forecast.known_as_of DESC, forecast.forecast_date DESC
            ) AS preference
        FROM weather_forecast AS forecast
        INNER JOIN origin_weeks AS origins
            ON origins.market_id = forecast.market_id
           AND forecast.forecast_date BETWEEN origins.week_start AND origins.week_end
           AND forecast.target_date BETWEEN
               CAST(origins.week_start + INTERVAL 1 WEEK AS DATE)
               AND CAST(origins.week_start + INTERVAL 13 DAY AS DATE)
        WHERE forecast.known_as_of < origins.origin_cutoff
    ),
    weather_forecast_h1 AS (
        SELECT
            market_id,
            origin_week,
            avg(tavg_c) AS weather_tavg_forecast_h1,
            avg(precip_prob) AS weather_precip_forecast_h1,
            count(*) AS weather_forecast_coverage_days_h1
        FROM weather_forecast_ranked
        WHERE preference = 1
        GROUP BY market_id, origin_week
    ),
    macro_visible AS (
        SELECT
            macro.market_id,
            macro.week_start,
            avg(CAST(macro.value AS DOUBLE)) AS macro_index_value
        FROM macro_index AS macro
        INNER JOIN origin_weeks AS origins
            ON origins.market_id = macro.market_id
           AND origins.week_start = macro.week_start
        WHERE macro.known_as_of < origins.origin_cutoff
        GROUP BY macro.market_id, macro.week_start
    ),
    competitor_ranked AS (
        SELECT
            matches.market_id,
            matches.sku_id,
            prices.geo_scope_id AS store_id,
            CAST(date_trunc('week', prices.observed_at) AS DATE) AS week_start,
            prices.price,
            prices.in_stock_flag,
            date_diff(
                'day',
                CAST(prices.observed_at AS DATE),
                origins.week_end
            ) AS competitor_age_days,
            row_number() OVER (
                PARTITION BY
                    matches.market_id,
                    matches.sku_id,
                    prices.geo_scope_id,
                    date_trunc('week', prices.observed_at)
                ORDER BY prices.known_as_of DESC, prices.observed_at DESC
            ) AS preference
        FROM competitor_matches AS matches
        INNER JOIN competitor_prices AS prices
            USING (market_id, comp_id, comp_product_id)
        INNER JOIN origin_weeks AS origins
            ON origins.market_id = prices.market_id
           AND origins.week_start
               = CAST(date_trunc('week', prices.observed_at) AS DATE)
        WHERE matches.match_status = 'active'
          AND prices.geo_scope_type = 'location'
          AND prices.known_as_of < origins.origin_cutoff
    ),
    competitor_weekly AS (
        SELECT
            market_id,
            sku_id,
            store_id,
            week_start,
            price AS competitor_price,
            in_stock_flag AS competitor_in_stock,
            competitor_age_days
        FROM competitor_ranked
        WHERE preference = 1
    ),
    weekly_with_external AS (
        SELECT
            weekly.*,
            weather.weather_tavg_origin,
            weather.weather_precip_origin,
            weather.weather_tavg_climatology,
            weather.weather_precip_climatology,
            forecast.weather_tavg_forecast_h1,
            forecast.weather_precip_forecast_h1,
            forecast.weather_forecast_coverage_days_h1,
            macro.macro_index_value,
            competitor.competitor_price / nullif(weekly.observed_net_price, 0)
                AS competitor_price_ratio,
            CASE
                WHEN competitor.competitor_price IS NULL THEN 0 ELSE 1
            END AS competitor_available,
            CAST(competitor.competitor_in_stock AS INTEGER) AS competitor_in_stock,
            competitor.competitor_age_days
        FROM weekly_normalized AS weekly
        LEFT JOIN weather_history AS weather
            ON weather.market_id = weekly.market_id
           AND weather.week_start = weekly.week_start
        LEFT JOIN weather_forecast_h1 AS forecast
            ON forecast.market_id = weekly.market_id
           AND forecast.origin_week = weekly.week_start
        LEFT JOIN macro_visible AS macro
            ON macro.market_id = weekly.market_id
           AND macro.week_start = weekly.week_start
        LEFT JOIN competitor_weekly AS competitor
            ON competitor.market_id = weekly.market_id
           AND competitor.sku_id = weekly.sku_id
           AND competitor.store_id = weekly.store_id
           AND competitor.week_start = weekly.week_start
    ),
    weekly_calendar AS (
        SELECT
            calendar.market_id,
            CAST(date_trunc('week', calendar.date) AS DATE) AS week_start,
            sum(CASE WHEN calendar.working_day THEN 1 ELSE 0 END) AS working_days,
            count(events.event_name) AS event_count,
            max(calendar.known_as_of) AS working_days_known_as_of
        FROM calendar
        LEFT JOIN calendar_events AS events
            ON events.market_id = calendar.market_id
           AND events.date = calendar.date
        GROUP BY
            calendar.market_id,
            date_trunc('week', calendar.date)
    ),
    calendar_future AS (
        SELECT
            *,
            {calendar_leads}
        FROM weekly_calendar
        WINDOW market_calendar_window AS (
            PARTITION BY market_id ORDER BY week_start
        )
    ),
    feature_windows AS (
        SELECT
            *,
            row_number() OVER series_window AS week_index,
            {lag_expressions},
            {rolling_expressions},
            sum(
                CASE WHEN units = 0 THEN exposure_weight ELSE 0 END
            ) OVER (
                PARTITION BY sku_id, store_id, channel_id
                ORDER BY week_start
                ROWS BETWEEN 52 PRECEDING AND 1 PRECEDING
            ) / nullif(
                sum(exposure_weight) OVER (
                    PARTITION BY sku_id, store_id, channel_id
                    ORDER BY week_start
                    ROWS BETWEEN 52 PRECEDING AND 1 PRECEDING
                ),
                0
            ) AS zero_share_52w,
            lag(observed_net_price, 1) OVER series_window
                / nullif(
                    median(observed_net_price) OVER (
                        PARTITION BY sku_id, store_id, channel_id
                        ORDER BY week_start
                        ROWS BETWEEN 13 PRECEDING AND 1 PRECEDING
                    ),
                    0
                ) AS price_ratio_13w,
            lag(category_price_index, 1) OVER series_window
                AS local_category_price_index,
            {target_expressions},
            {availability_expressions}
        FROM weekly_with_external
        WINDOW series_window AS (
            PARTITION BY sku_id, store_id, channel_id ORDER BY week_start
        )
    ),
    selected_features AS (
        SELECT
            sku_id,
            store_id,
            channel_id,
            market_id,
            dept_id,
            category,
            sub_cat,
            week_start AS forecast_origin,
            week_end,
            source_known_as_of,
            active_from,
            active_to,
            exposure_days,
            exposure_weight,
            training_eligible,
            units AS origin_units,
            weekly_units_equivalent,
            week_index,
            units_lag_1,
            units_lag_4,
            units_lag_13,
            units_lag_52,
            units_roll_mean_4,
            units_roll_std_4,
            units_roll_mean_8,
            units_roll_std_8,
            units_roll_mean_13,
            units_roll_std_13,
            units_roll_mean_52,
            units_roll_std_52,
            zero_share_52w,
            (
                units_roll_mean_4 - units_roll_mean_13
            ) / nullif(abs(units_roll_mean_13), 0) AS demand_trend_4v13,
            price_ratio_13w,
            round(local_category_price_index, 8)
                AS local_category_price_index,
            weather_tavg_origin,
            weather_precip_origin,
            weather_tavg_climatology,
            weather_precip_climatology,
            round(weather_tavg_forecast_h1, 12)
                AS weather_tavg_forecast_h1,
            round(weather_precip_forecast_h1, 12)
                AS weather_precip_forecast_h1,
            weather_forecast_coverage_days_h1,
            macro_index_value,
            competitor_price_ratio,
            competitor_available,
            competitor_in_stock,
            competitor_age_days,
            CAST(strftime(week_start, '%V') AS INTEGER) AS iso_week,
            sin(
                2 * pi() * CAST(strftime(week_start, '%V') AS DOUBLE) / 52.1775
            ) AS week_sin,
            cos(
                2 * pi() * CAST(strftime(week_start, '%V') AS DOUBLE) / 52.1775
            ) AS week_cos,
            CAST(strftime(week_start, '%G') AS INTEGER) AS origin_year,
            {", ".join(TARGET_COLUMNS)},
            {", ".join(TARGET_AVAILABILITY_COLUMNS)}
        FROM feature_windows
    )
    SELECT
        features.*,
        calendar.event_count AS event_count_origin,
        CASE
            WHEN calendar.working_days_known_as_of <= features.week_end
            THEN calendar.working_days
            ELSE NULL
        END AS working_days_origin,
        {future_calendar_select}
    FROM selected_features AS features
    INNER JOIN calendar_future AS calendar
        ON calendar.market_id = features.market_id
       AND calendar.week_start = features.forecast_origin
    ORDER BY
        features.market_id,
        features.store_id,
        features.channel_id,
        features.sku_id,
        features.forecast_origin
    """


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def all_null_feature_columns(connection: Any, feature_path: Path) -> list[str]:
    """Return columns that contain no observed value in the full artifact."""

    sql_path = str(feature_path).replace("'", "''")
    columns = [
        str(row[0])
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{sql_path}')"
        ).fetchall()
    ]
    counts = connection.execute(
        "SELECT "
        + ", ".join(f'count("{column}")' for column in columns)
        + f" FROM read_parquet('{sql_path}')"
    ).fetchone()
    return [
        column
        for column, count in zip(columns, counts, strict=True)
        if int(count) == 0
    ]


def _stats(connection: Any, feature_path: Path) -> FeatureBuildStats:
    sql_path = str(feature_path).replace("'", "''")
    row = connection.execute(
        f"""
        SELECT
            count(*),
            count(*) FILTER (WHERE training_eligible),
            count(DISTINCT (sku_id, store_id, channel_id)),
            min(forecast_origin),
            max(forecast_origin),
            CAST(sum(origin_units) AS BIGINT),
            CAST(
                round(
                    avg(CASE WHEN origin_units = 0 THEN 1.0 ELSE 0.0 END),
                    8
                )
                AS VARCHAR
            )
        FROM read_parquet('{sql_path}')
        """
    ).fetchone()
    per_market_rows = connection.execute(
        f"""
        SELECT
            market_id,
            count(*) AS feature_rows,
            count(*) FILTER (WHERE training_eligible) AS training_eligible_rows,
            count(DISTINCT (sku_id, store_id, channel_id)) AS series_count,
            CAST(sum(origin_units) AS BIGINT) AS weekly_units,
            CAST(
                round(
                    avg(CASE WHEN origin_units = 0 THEN 1.0 ELSE 0.0 END),
                    8
                )
                AS VARCHAR
            ) AS zero_week_share
        FROM read_parquet('{sql_path}')
        GROUP BY market_id
        ORDER BY market_id
        """
    ).fetchall()
    per_market = {
        str(market_id): {
            "featureRows": int(feature_rows),
            "trainingEligibleRows": int(training_rows),
            "seriesCount": int(series_count),
            "weeklyUnits": int(weekly_units),
            "zeroWeekShare": str(zero_share),
        }
        for (
            market_id,
            feature_rows,
            training_rows,
            series_count,
            weekly_units,
            zero_share,
        ) in per_market_rows
    }
    return FeatureBuildStats(
        feature_rows=int(row[0]),
        training_eligible_rows=int(row[1]),
        series_count=int(row[2]),
        min_forecast_origin=str(row[3]),
        max_forecast_origin=str(row[4]),
        weekly_units=int(row[5]),
        zero_week_share=str(row[6]),
        per_market=per_market,
    )


def build_features(
    bundle: VerifiedInputBundle,
    output_dir: str | Path,
    *,
    runtime_profile: MLRuntimeProfile,
) -> tuple[FeatureBuildStats, Path]:
    """Atomically publish one immutable weekly feature artifact."""

    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(f"feature output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            dir=output.parent,
            prefix=f".{output.name}.staging-",
        )
    )
    feature_path = staging / "weekly_features.parquet"
    try:
        reader = CuratedReader(bundle)
        feature_sql = weekly_features_sql()
        with reader.connect_duckdb() as connection:
            connection.execute(f"SET threads = {runtime_profile.feature_workers}")
            connection.execute(
                f"SET memory_limit = '{runtime_profile.memory_limit_gb}GB'"
            )
            spill = staging / "duckdb-spill"
            spill.mkdir()
            escaped_spill = str(spill).replace("'", "''")
            connection.execute(f"SET temp_directory = '{escaped_spill}'")
            escaped_output = str(feature_path).replace("'", "''")
            connection.execute(
                f"""
                COPY ({feature_sql})
                TO '{escaped_output}'
                (
                    FORMAT PARQUET,
                    COMPRESSION ZSTD,
                    ROW_GROUP_SIZE 100000
                )
                """
            )
            stats = _stats(connection, feature_path)
            all_null_columns = all_null_feature_columns(connection, feature_path)
            if all_null_columns:
                raise ValueError(
                    "weekly feature artifact contains structurally all-null "
                    f"columns: {', '.join(all_null_columns)}"
                )
        spill.rmdir()
        feature_bytes = feature_path.stat().st_size
        manifest: dict[str, Any] = {
            "schemaVersion": FEATURE_SCHEMA_VERSION,
            "sourceInput": bundle.identity,
            "featurePolicy": {
                "seriesKeyFields": list(SERIES_KEY_FIELDS),
                "horizonWeeks": list(HORIZONS),
                "labelEmbargoWeeks": LABEL_EMBARGO_WEEKS,
                "partialBoundaryWeeks": PARTIAL_BOUNDARY_POLICY,
                "promotionFeature": "unavailable",
                "calendarEventFutureFeature": "unavailable",
                "localEventFutureFeature": "unavailable",
                "marketDisruptionFutureFeature": "unavailable",
                "pitEligible": False,
                "reasonCode": "LANDING_BACKFILL_DEPENDENCY",
                "calendarEventFutureReasonCode": (
                    "NO_ORIGIN_VISIBLE_CALENDAR_EVENT_SNAPSHOT"
                ),
                "localEventFutureReasonCode": (
                    "NO_ORIGIN_VISIBLE_LOCAL_EVENT_PLAN"
                ),
                "marketDisruptionFutureReasonCode": (
                    "NO_ORIGIN_VISIBLE_MARKET_DISRUPTION_PLAN"
                ),
                "allNullFeatureColumns": [],
                "priceFeatures": [
                    "price_ratio_13w",
                    "local_category_price_index",
                ],
                "driverSemantics": "retail-ml-driver-semantics/v3",
                "featureSqlSha256": hashlib.sha256(
                    feature_sql.encode("utf-8")
                ).hexdigest(),
            },
            "stats": asdict(stats),
            "objects": {
                "weeklyFeatures": {
                    "path": feature_path.name,
                    "bytes": feature_bytes,
                    "sha256": _sha256_file(feature_path),
                }
            },
            "executionProfile": runtime_profile.as_manifest_dict(),
            "outputPath": str(output),
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        manifest["semanticFingerprint"] = semantic_fingerprint(
            manifest,
            volatile_pointers=FEATURE_MANIFEST_VOLATILE_POINTERS,
        )
        (staging / "manifest.json").write_text(
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
    return stats, output


__all__ = [
    "FEATURE_MANIFEST_VOLATILE_POINTERS",
    "FEATURE_SCHEMA_VERSION",
    "FeatureBuildStats",
    "all_null_feature_columns",
    "build_features",
    "weekly_features_sql",
]
