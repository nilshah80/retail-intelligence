"""Reusable origin-cutoff primitives for every external driver."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Final, Iterable

import pandas as pd
import yaml

DRIVER_NAMES: Final[tuple[str, ...]] = (
    "weather_actual",
    "weather_forecast",
    "local_events",
    "competitor_prices",
    "market_disruptions",
    "macro_index",
    "promotions",
)


class DriverAvailabilityError(ValueError):
    """A driver value is unavailable or would leak post-origin evidence."""


def load_driver_semantics(path: str | Path) -> dict[str, object]:
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DriverAvailabilityError("driver semantics root must be a mapping")
    if value.get("schemaVersion") != "retail-ml-driver-semantics/v3":
        raise DriverAvailabilityError("unsupported driver semantics schemaVersion")
    drivers = value.get("drivers")
    if not isinstance(drivers, dict) or set(drivers) != set(DRIVER_NAMES):
        raise DriverAvailabilityError(
            f"driver semantics must define exactly {DRIVER_NAMES}"
        )
    return value


def origin_visible_rows(
    rows: pd.DataFrame,
    *,
    fit_known_as_of: date | datetime | pd.Timestamp,
    known_as_of_column: str = "known_as_of",
) -> pd.DataFrame:
    if known_as_of_column not in rows:
        raise DriverAvailabilityError(
            f"driver rows are missing {known_as_of_column!r}"
        )
    cutoff = pd.Timestamp(fit_known_as_of)
    known = pd.to_datetime(rows[known_as_of_column], utc=True, errors="coerce")
    if cutoff.tzinfo is None:
        cutoff = cutoff.tz_localize("UTC")
    else:
        cutoff = cutoff.tz_convert("UTC")
    return rows.loc[known.notna() & (known <= cutoff)].copy()


def latest_origin_visible(
    rows: pd.DataFrame,
    *,
    key_columns: Iterable[str],
    fit_known_as_of: date | datetime | pd.Timestamp,
    known_as_of_column: str = "known_as_of",
) -> pd.DataFrame:
    visible = origin_visible_rows(
        rows,
        fit_known_as_of=fit_known_as_of,
        known_as_of_column=known_as_of_column,
    )
    if visible.empty:
        return visible
    keys = tuple(key_columns)
    missing = set(keys).difference(visible.columns)
    if missing:
        raise DriverAvailabilityError(f"driver rows are missing key columns {sorted(missing)}")
    return (
        visible.sort_values(known_as_of_column)
        .groupby(list(keys), observed=True, sort=False)
        .tail(1)
        .reset_index(drop=True)
    )


def origin_published_target_rows(
    rows: pd.DataFrame,
    *,
    target_date: date,
    fit_known_as_of: date | datetime | pd.Timestamp,
    target_date_column: str,
    known_as_of_column: str = "known_as_of",
) -> pd.DataFrame:
    if target_date_column not in rows:
        raise DriverAvailabilityError(
            f"driver rows are missing target-date column {target_date_column!r}"
        )
    visible = origin_visible_rows(
        rows,
        fit_known_as_of=fit_known_as_of,
        known_as_of_column=known_as_of_column,
    )
    effective = pd.to_datetime(visible[target_date_column], errors="coerce").dt.date
    return visible.loc[effective == target_date].copy()


def assert_no_promotion_features(columns: Iterable[str]) -> None:
    forbidden = [
        column
        for column in columns
        if "promo" in column.casefold() or "promotion" in column.casefold()
    ]
    if forbidden:
        raise DriverAvailabilityError(
            f"promotion features are unavailable on the accepted pin: {forbidden}"
        )


__all__ = [
    "DRIVER_NAMES",
    "DriverAvailabilityError",
    "assert_no_promotion_features",
    "latest_origin_visible",
    "load_driver_semantics",
    "origin_published_target_rows",
    "origin_visible_rows",
]
