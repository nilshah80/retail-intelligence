from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd

from retail_ml.models.dataset import (
    BASE_MODEL_COLUMNS,
    eligible_recent_origins,
    eligible_scoring_origins,
    load_current_horizon,
)


def _current_feature(
    tmp_path: Path,
    *,
    scored_origin: date,
    source_known_as_of: datetime,
    exposure_days: int,
    origin_units: float,
    weekly_units_equivalent: float | None,
) -> Path:
    row: dict[str, object] = {column: 1.0 for column in BASE_MODEL_COLUMNS}
    row.update(
        {
            "sku_id": "sku",
            "market_id": "market",
            "store_id": "store",
            "channel_id": "channel",
            "dept_id": "dept",
            "category": "category",
            "sub_cat": "sub-category",
            "active_from": date(2020, 1, 1),
            "forecast_origin": scored_origin,
            "week_end": scored_origin + timedelta(days=6),
            "source_known_as_of": source_known_as_of,
            "exposure_days": exposure_days,
            "origin_units": origin_units,
            "weekly_units_equivalent": weekly_units_equivalent,
            "working_days_h1": 5.0,
        }
    )
    path = tmp_path / "weekly_features.parquet"
    pd.DataFrame([row]).to_parquet(path, index=False)
    return path


def test_complete_current_origin_keeps_its_seven_day_units(tmp_path: Path) -> None:
    origin = date(2026, 7, 20)
    feature_path = _current_feature(
        tmp_path,
        scored_origin=origin,
        source_known_as_of=datetime(2026, 7, 26, 12, tzinfo=UTC),
        exposure_days=7,
        origin_units=17.0,
        weekly_units_equivalent=17.0,
    )

    frame = load_current_horizon(
        feature_path,
        scored_origin=origin,
        horizon=1,
        decision_as_of=datetime(2026, 7, 26, 23, 59, tzinfo=UTC),
    )

    assert frame.loc[0, "origin_units"] == 17.0


def test_partial_current_origin_uses_weekly_units_equivalent(
    tmp_path: Path,
) -> None:
    origin = date(2026, 7, 27)
    feature_path = _current_feature(
        tmp_path,
        scored_origin=origin,
        source_known_as_of=datetime(2026, 7, 29, 9, tzinfo=UTC),
        exposure_days=2,
        origin_units=4.0,
        weekly_units_equivalent=14.0,
    )

    frame = load_current_horizon(
        feature_path,
        scored_origin=origin,
        horizon=1,
        decision_as_of=datetime(2026, 7, 29, 12, tzinfo=UTC),
    )

    assert frame.loc[0, "origin_units"] == 14.0


def test_null_weekly_equivalent_falls_back_to_observed_origin_units(
    tmp_path: Path,
) -> None:
    origin = date(2026, 7, 27)
    feature_path = _current_feature(
        tmp_path,
        scored_origin=origin,
        source_known_as_of=datetime(2026, 7, 29, 9, tzinfo=UTC),
        exposure_days=0,
        origin_units=4.0,
        weekly_units_equivalent=None,
    )

    frame = load_current_horizon(
        feature_path,
        scored_origin=origin,
        horizon=1,
        decision_as_of=datetime(2026, 7, 29, 12, tzinfo=UTC),
    )

    assert frame.loc[0, "origin_units"] == 4.0


def test_recent_origins_cannot_overlap_complete_acceptance_grid(
    tmp_path: Path,
) -> None:
    first = date(2025, 7, 7)
    rows = []
    for index in range(40):
        origin = first + timedelta(weeks=index)
        rows.append(
            {
                "forecast_origin": origin,
                "training_eligible": True,
                "units_lag_52": 1.0,
                "target_units_h4": 1.0,
                "target_units_h26": 1.0 if index < 27 else None,
            }
        )
    feature_path = tmp_path / "schedule_features.parquet"
    pd.DataFrame(rows).to_parquet(feature_path, index=False)

    complete = eligible_scoring_origins(feature_path)
    recent = eligible_recent_origins(feature_path)

    assert len(recent) == 13
    assert set(complete).isdisjoint(recent)
    assert max(complete) < min(recent)
