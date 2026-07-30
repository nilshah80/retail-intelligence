"""Assortment coverage and explicit partial-boundary-week policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

PARTIAL_BOUNDARY_POLICY: Final[str] = (
    "retain_for_reconciliation_exclude_from_training"
)


@dataclass(frozen=True, slots=True)
class WeekExposure:
    week_start: date
    week_end: date
    active_days: int

    @property
    def weight(self) -> float:
        return self.active_days / 7.0

    @property
    def training_eligible(self) -> bool:
        return self.active_days == 7


def week_exposure(
    week_start: date,
    active_from: date,
    active_to: date,
) -> WeekExposure:
    week_end = week_start + timedelta(days=6)
    overlap_start = max(week_start, active_from)
    overlap_end = min(week_end, active_to)
    active_days = max(0, (overlap_end - overlap_start).days + 1)
    return WeekExposure(
        week_start=week_start,
        week_end=week_end,
        active_days=active_days,
    )


__all__ = ["PARTIAL_BOUNDARY_POLICY", "WeekExposure", "week_exposure"]
