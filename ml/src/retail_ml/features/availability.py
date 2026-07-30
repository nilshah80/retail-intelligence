"""Fixed embargo and per-horizon label-availability rules."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final, Mapping

HORIZONS: Final[tuple[int, ...]] = tuple(range(1, 27))
LABEL_EMBARGO_WEEKS: Final[int] = 8
TARGET_COLUMNS: Final[tuple[str, ...]] = tuple(
    f"target_units_h{horizon}" for horizon in HORIZONS
)
TARGET_AVAILABILITY_COLUMNS: Final[tuple[str, ...]] = tuple(
    f"target_known_as_of_h{horizon}" for horizon in HORIZONS
)
FUTURE_CALENDAR_COLUMNS: Final[tuple[str, ...]] = tuple(
    f"working_days_h{horizon}" for horizon in HORIZONS
)


def latest_training_origin(scored_origin: date) -> date:
    return scored_origin - timedelta(weeks=LABEL_EMBARGO_WEEKS)


def training_origin_is_eligible(candidate: date, scored_origin: date) -> bool:
    return candidate <= latest_training_origin(scored_origin)


def label_is_available(
    target_known_as_of: date | datetime | None,
    fit_known_as_of: date | datetime,
) -> bool:
    if target_known_as_of is None:
        return False
    if isinstance(target_known_as_of, datetime) and isinstance(fit_known_as_of, date):
        if not isinstance(fit_known_as_of, datetime):
            return target_known_as_of.date() <= fit_known_as_of
    if isinstance(fit_known_as_of, datetime) and isinstance(target_known_as_of, date):
        if not isinstance(target_known_as_of, datetime):
            return target_known_as_of <= fit_known_as_of.date()
    return target_known_as_of <= fit_known_as_of


def horizon_labels_available(
    row: Mapping[str, date | datetime | None],
    fit_known_as_of: date | datetime,
) -> dict[int, bool]:
    return {
        horizon: label_is_available(
            row.get(f"target_known_as_of_h{horizon}"),
            fit_known_as_of,
        )
        for horizon in HORIZONS
    }


__all__ = [
    "FUTURE_CALENDAR_COLUMNS",
    "HORIZONS",
    "LABEL_EMBARGO_WEEKS",
    "TARGET_AVAILABILITY_COLUMNS",
    "TARGET_COLUMNS",
    "horizon_labels_available",
    "label_is_available",
    "latest_training_origin",
    "training_origin_is_eligible",
]
