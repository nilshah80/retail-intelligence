"""Descriptive series characterization; never threshold selection."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


class CharacterizationError(RuntimeError):
    """The feature artifact is absent, corrupt, or incompatible."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def characterize_features(
    feature_dir: str | Path,
    report_path: str | Path,
    *,
    replace: bool = False,
) -> dict[str, Any]:
    source = Path(feature_dir).resolve()
    report = Path(report_path).resolve()
    manifest_path = source / "manifest.json"
    feature_path = source / "weekly_features.parquet"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CharacterizationError(f"invalid feature manifest: {exc}") from exc
    if manifest.get("schemaVersion") != "retail-weekly-features/v1":
        raise CharacterizationError("unsupported weekly feature schemaVersion")
    expected = manifest["objects"]["weeklyFeatures"]
    if (
        feature_path.stat().st_size != expected["bytes"]
        or _sha256_file(feature_path) != expected["sha256"]
    ):
        raise CharacterizationError("weekly feature object does not match its manifest")

    report.parent.mkdir(parents=True, exist_ok=True)
    series_path = report.with_name(f"{report.stem}-series.parquet")
    if report.exists() or series_path.exists():
        if not replace:
            raise FileExistsError("characterization output is immutable and already exists")
        report.unlink(missing_ok=True)
        series_path.unlink(missing_ok=True)
    escaped_source = str(feature_path).replace("'", "''")
    escaped_series = str(series_path).replace("'", "''")
    connection = duckdb.connect()
    connection.execute(
        f"""
        COPY (
            WITH panel AS (
                SELECT
                    *,
                    lag(origin_units) OVER (
                        PARTITION BY sku_id, store_id, channel_id
                        ORDER BY forecast_origin
                    ) AS prior_units
                FROM read_parquet('{escaped_source}')
            )
            SELECT
                market_id,
                sku_id,
                store_id,
                channel_id,
                min(forecast_origin) AS active_week_start,
                max(forecast_origin) AS active_week_end,
                count(*) AS observed_weeks,
                count(*) FILTER (WHERE training_eligible) AS full_exposure_weeks,
                CASE
                    WHEN count(*) < 52 THEN 'cold_start'
                    WHEN count(*) < 104 THEN 'developing'
                    ELSE 'established'
                END AS lifecycle_stage,
                avg(CASE WHEN origin_units = 0 THEN 1.0 ELSE 0.0 END)
                    AS lifetime_zero_share,
                arg_max(
                    zero_share_52w,
                    forecast_origin
                ) FILTER (WHERE training_eligible) AS current_zero_share_52w,
                arg_max(
                    zero_share_52w,
                    forecast_origin
                ) FILTER (WHERE training_eligible) > 0.60 AS slow_mover,
                avg(origin_units) AS mean_weekly_units,
                var_samp(origin_units) / nullif(avg(origin_units), 0)
                    AS overdispersion_ratio,
                corr(origin_units, prior_units) AS autocorrelation_lag1,
                avg(origin_units) FILTER (WHERE event_count_origin > 0)
                    / nullif(
                        avg(origin_units) FILTER (
                            WHERE coalesce(event_count_origin, 0) = 0
                        ),
                        0
                    ) AS event_peak_ratio
            FROM panel
            GROUP BY market_id, sku_id, store_id, channel_id
            ORDER BY market_id, store_id, channel_id, sku_id
        )
        TO '{escaped_series}'
        (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    rows = connection.execute(
        f"""
        SELECT
            market_id,
            count(*) AS series_count,
            count(*) FILTER (WHERE slow_mover) AS slow_mover_series,
            count(*) FILTER (WHERE lifecycle_stage = 'cold_start') AS cold_start_series,
            count(*) FILTER (WHERE lifecycle_stage = 'developing') AS developing_series,
            count(*) FILTER (WHERE lifecycle_stage = 'established') AS established_series,
            CAST(round(median(lifetime_zero_share), 8) AS VARCHAR),
            CAST(round(median(overdispersion_ratio), 8) AS VARCHAR),
            CAST(round(median(autocorrelation_lag1), 8) AS VARCHAR),
            CAST(round(median(event_peak_ratio), 8) AS VARCHAR)
        FROM read_parquet('{escaped_series}')
        GROUP BY market_id
        ORDER BY market_id
        """
    ).fetchall()
    connection.close()
    def optional_string(value: object) -> str | None:
        return None if value is None else str(value)

    markets = {
        str(row[0]): {
            "seriesCount": int(row[1]),
            "slowMoverSeries": int(row[2]),
            "lifecycleStages": {
                "coldStart": int(row[3]),
                "developing": int(row[4]),
                "established": int(row[5]),
            },
            "medianLifetimeZeroShare": optional_string(row[6]),
            "medianOverdispersionRatio": optional_string(row[7]),
            "medianAutocorrelationLag1": optional_string(row[8]),
            "medianEventPeakRatio": optional_string(row[9]),
        }
        for row in rows
    }
    result: dict[str, Any] = {
        "schemaVersion": "retail-series-characterization/v1",
        "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "featureSemanticFingerprint": manifest["semanticFingerprint"],
        "thresholdPolicy": {
            "slowMoverZeroShare52w": "0.60",
            "descriptiveOnly": True,
        },
        "markets": markets,
        "objects": {
            "series": {
                "path": series_path.name,
                "bytes": series_path.stat().st_size,
                "sha256": _sha256_file(series_path),
            }
        },
    }
    report.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return result


__all__ = ["CharacterizationError", "characterize_features"]
