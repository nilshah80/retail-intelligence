"""The market-local ISO-Monday replay clock and its Thursday bridge (§3.5).

Net-new: the M5 simulator was daily and store-only; wrapping it would have
inherited a clock the evidence cannot support. Weekly stock evidence produces a
weekly replay -- interpolation is forbidden -- and the opening state of a Monday
period is derived from the IMMEDIATELY PRECEDING Thursday 23:00 local snapshot,
never the Thursday inside the target week: that Thursday is three days of the
period's own future.

All arithmetic uses zoned local instants, so a daylight-saving transition week is
not forced to 73 elapsed hours; 73 is the consequence in an ordinary week, not
the rule.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SNAPSHOT_LOCAL_TIME = time(hour=23)


def monday_period_bounds(
    any_date: date, timezone: str
) -> tuple[datetime, datetime]:
    """[Monday 00:00 local, next Monday 00:00 local) for the ISO week of a date.

    Inclusivity is frozen by policy v2 `replayClock`: the opening instant is
    inside the period, the closing instant is not. An event effective exactly at
    Monday 00:00 belongs to the opening period.
    """

    zone = ZoneInfo(timezone)
    monday = any_date - timedelta(days=any_date.weekday())
    opening = datetime.combine(monday, time(0), tzinfo=zone)
    closing = datetime.combine(monday + timedelta(days=7), time(0), tzinfo=zone)
    return opening, closing


def opening_snapshot_instant(period_open: datetime, timezone: str) -> datetime:
    """The snapshot that seeds a Monday opening: the preceding Thursday 23:00.

    For a Monday opening, the immediately preceding Thursday is always 4 days
    back -- the Thursday INSIDE the target week (3 days forward) is the wrong
    one, and using it is the specific mistake §3.5 calls out. The bridge from
    this instant to the opening applies every origin-visible state-changing
    event in between.
    """

    zone = ZoneInfo(timezone)
    if period_open.tzinfo is None:
        raise ValueError("period_open must be timezone-aware")
    local_open = period_open.astimezone(zone)
    if local_open.weekday() != 0 or local_open.time() != time(0):
        raise ValueError("period_open must be a Monday 00:00 local instant")
    thursday = local_open.date() - timedelta(days=4)
    return datetime.combine(thursday, SNAPSHOT_LOCAL_TIME, tzinfo=zone)


def bridge_interval(
    period_open: datetime, timezone: str
) -> tuple[datetime, datetime]:
    """(snapshot instant, period open]. Events effective exactly AT the snapshot
    are already inside the snapshot; events at the opening belong to the period
    (policy v2: receiptExactlyAtOpeningCutoff = opening_period)."""

    snapshot = opening_snapshot_instant(period_open, timezone)
    return snapshot, period_open


__all__ = [
    "SNAPSHOT_LOCAL_TIME",
    "bridge_interval",
    "monday_period_bounds",
    "opening_snapshot_instant",
]
