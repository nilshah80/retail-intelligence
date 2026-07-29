"""Versioned locale-calendar expansion for long-horizon source simulation."""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday using the Meeus/Jones/Butcher algorithm."""

    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _rule_date(rule: dict[str, Any], year: int) -> date:
    rule_type = rule["type"]
    if rule_type == "fixed":
        return date(year, rule["month"], rule["day"])
    if rule_type == "easter-offset":
        return _easter_sunday(year) + timedelta(days=rule["offsetDays"])
    month = rule["month"]
    weekday = rule["weekday"]
    if rule_type in {"nth-weekday", "nth-weekday-offset"}:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        result = first + timedelta(
            days=offset + 7 * (rule["occurrence"] - 1)
        )
        if rule_type == "nth-weekday-offset":
            result += timedelta(days=rule["offsetDays"])
        return result
    if rule_type == "last-weekday":
        last = date(year, month, calendar.monthrange(year, month)[1])
        return last - timedelta(days=(last.weekday() - weekday) % 7)
    raise ValueError(f"unsupported holiday rule type {rule_type!r}")


def holidays_for_range(
    locale_pack: dict[str, Any],
    start: date,
    end: date,
) -> list[dict[str, str]]:
    """Expand recurring rules and reviewed one-off/lunar dates for a date range."""

    by_date_and_name: dict[tuple[str, str], dict[str, str]] = {}
    for year in range(start.year, end.year + 1):
        for rule in locale_pack["holidayRules"]:
            holiday_day = _rule_date(rule, year)
            if start <= holiday_day <= end:
                row = {
                    "date": holiday_day.isoformat(),
                    "name": rule["name"],
                    "kind": rule["kind"],
                    "retailBehavior": rule["retailBehavior"],
                }
                by_date_and_name[(row["date"], row["name"])] = row
        occupied = {
            date.fromisoformat(row["date"])
            for row in by_date_and_name.values()
            if row["date"].startswith(f"{year:04d}-")
        }
        for rule in locale_pack["holidayRules"]:
            if rule["type"] != "fixed":
                continue
            holiday_day = _rule_date(rule, year)
            observed_day: date | None = None
            if locale_pack["id"] == "US":
                if holiday_day.weekday() == 5:
                    observed_day = holiday_day - timedelta(days=1)
                elif holiday_day.weekday() == 6:
                    observed_day = holiday_day + timedelta(days=1)
            elif locale_pack["id"] == "GB" and holiday_day.weekday() >= 5:
                observed_day = holiday_day + timedelta(
                    days=7 - holiday_day.weekday()
                )
                while observed_day in occupied:
                    observed_day += timedelta(days=1)
            if observed_day and start <= observed_day <= end:
                row = {
                    "date": observed_day.isoformat(),
                    "name": f"{rule['name']} (observed)",
                    "kind": "observed",
                    # The substitute bank/federal day is calendar evidence,
                    # not a second retailer closure or retail event.
                    "retailBehavior": "observance",
                }
                by_date_and_name[(row["date"], row["name"])] = row
                occupied.add(observed_day)
    for row in locale_pack["holidays"]:
        holiday_day = date.fromisoformat(row["date"])
        if start <= holiday_day <= end:
            by_date_and_name[(row["date"], row["name"])] = dict(row)
    return sorted(
        by_date_and_name.values(),
        key=lambda row: (row["date"], row["name"]),
    )


__all__ = ["holidays_for_range"]
