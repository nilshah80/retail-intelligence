"""Versioned locale packs owned by the source generator.

The builder materializes one complete resolved pack into every market. The
generator validates that materialized values still match this version before it
uses them, so locale-sensitive behavior cannot silently drift between authoring
and generation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

LOCALE_PACK_VERSION = "2026.5"


def _holiday(
    date: str,
    name: str,
    kind: str = "public",
    retail_behavior: str = "public-holiday",
) -> dict[str, str]:
    return {
        "date": date,
        "name": name,
        "kind": kind,
        "retailBehavior": retail_behavior,
    }


def _fixed(
    name: str,
    month: int,
    day: int,
    kind: str = "public",
    retail_behavior: str = "public-holiday",
) -> dict[str, Any]:
    return {
        "type": "fixed",
        "name": name,
        "month": month,
        "day": day,
        "kind": kind,
        "retailBehavior": retail_behavior,
    }


def _nth(
    name: str,
    month: int,
    weekday: int,
    occurrence: int,
    kind: str = "public",
    retail_behavior: str = "public-holiday",
) -> dict[str, Any]:
    return {
        "type": "nth-weekday",
        "name": name,
        "month": month,
        "weekday": weekday,
        "occurrence": occurrence,
        "kind": kind,
        "retailBehavior": retail_behavior,
    }


def _nth_offset(
    name: str,
    month: int,
    weekday: int,
    occurrence: int,
    offset_days: int,
    kind: str = "retail-event",
    retail_behavior: str = "retail-peak",
) -> dict[str, Any]:
    return {
        "type": "nth-weekday-offset",
        "name": name,
        "month": month,
        "weekday": weekday,
        "occurrence": occurrence,
        "offsetDays": offset_days,
        "kind": kind,
        "retailBehavior": retail_behavior,
    }


def _last(
    name: str,
    month: int,
    weekday: int,
    kind: str = "public",
    retail_behavior: str = "public-holiday",
) -> dict[str, Any]:
    return {
        "type": "last-weekday",
        "name": name,
        "month": month,
        "weekday": weekday,
        "kind": kind,
        "retailBehavior": retail_behavior,
    }


def _easter(
    name: str,
    offset_days: int,
    kind: str = "public",
    retail_behavior: str = "public-holiday",
) -> dict[str, Any]:
    return {
        "type": "easter-offset",
        "name": name,
        "offsetDays": offset_days,
        "kind": kind,
        "retailBehavior": retail_behavior,
    }


LOCALE_PACKS: dict[str, dict[str, Any]] = {
    "IN": {
        "id": "IN",
        "version": LOCALE_PACK_VERSION,
        "label": "India",
        "currency": {
            "code": "INR",
            "symbol": "₹",
            "minorUnitExponent": 2,
            "decimalSeparator": ".",
            "groupSeparator": ",",
            "priceEndings": ["00", "49", "99"],
            "defaultPriceMin": "99.00",
            "defaultPriceMax": "9999.00",
        },
        "tax": {
            "basis": "inclusive",
            "defaultRate": "0.18",
            "categoryRates": {
                "apparel": "0.12",
                "automotive": "0.28",
                "baby": "0.05",
                "beauty": "0.18",
                "books": "0.00",
                "electronics": "0.18",
                "grocery": "0.05",
                "health": "0.12",
                "home": "0.18",
                # Lubricants are standard-rated at 18% GST, not the 28% demerit
                # rate the `automotive` class carries. Given as its own class so
                # the retail `automotive` rate stays exactly where it was.
                "lubricants": "0.18",
                "sports": "0.18",
                "stationery": "0.12",
                "toys": "0.12",
            },
            "jurisdiction": "GST",
            "components": {
                "intraRegion": [
                    {"code": "CGST", "share": "0.5"},
                    {"code": "SGST", "share": "0.5"},
                ],
                "interRegion": [{"code": "IGST", "share": "1.0"}],
            },
        },
        "fiscalYearStartMonth": 4,
        "timezones": ["Asia/Kolkata"],
        "fakerLocale": "en_IN",
        "postcodePattern": "^[1-9][0-9]{5}$",
        "calendarCoverage": {"startDate": "2005-01-01", "endDate": "2026-12-31"},
        "climate": {
            "profile": "tropical-monsoon",
            "summerC": 33,
            "winterC": 23,
            "monsoonMonths": [6, 7, 8, 9],
        },
        "holidayRules": [
            _fixed("Republic Day", 1, 26),
            _fixed("Independence Day", 8, 15),
            _fixed("Gandhi Jayanti", 10, 2),
            _fixed("Christmas", 12, 25),
        ],
        "holidays": [
            *[
                _holiday(day, "Holi", "reviewed-lunar")
                for day in (
                    "2005-03-25", "2006-03-15", "2007-03-04", "2008-03-22",
                    "2009-03-11", "2010-03-01", "2011-03-20", "2012-03-08",
                    "2013-03-27", "2014-03-17", "2015-03-06", "2016-03-24",
                    "2017-03-13", "2018-03-02", "2019-03-21", "2020-03-10",
                    "2021-03-29", "2022-03-18", "2023-03-08", "2024-03-25",
                    "2025-03-14", "2026-03-04",
                )
            ],
            *[
                _holiday(day, "Eid al-Fitr", "reviewed-lunar")
                for day in (
                    "2005-11-04", "2006-10-24", "2007-10-13", "2008-10-02",
                    "2009-09-21", "2010-09-11", "2011-08-31", "2012-08-20",
                    "2013-08-09", "2014-07-29", "2015-07-18", "2016-07-07",
                    "2017-06-26", "2018-06-16", "2019-06-05", "2020-05-25",
                    "2021-05-14", "2022-05-03", "2023-04-22", "2024-04-11",
                    "2025-03-31", "2026-03-20",
                )
            ],
            *[
                _holiday(day, "Diwali", "reviewed-lunar")
                for day in (
                    "2005-11-01", "2006-10-21", "2007-11-09", "2008-10-28",
                    "2009-10-17", "2010-11-05", "2011-10-26", "2012-11-13",
                    "2013-11-03", "2014-10-23", "2015-11-11", "2016-10-30",
                    "2017-10-19", "2018-11-07", "2019-10-27", "2020-11-14",
                    "2021-11-04", "2022-10-24", "2023-11-12", "2024-10-31",
                    "2025-10-20", "2026-11-08",
                )
            ],
        ],
        "saleSeasons": [
            {"id": "diwali-season", "startMonthDay": "10-01", "endMonthDay": "11-10"},
            {"id": "republic-day-sale", "startMonthDay": "01-20", "endMonthDay": "01-28"},
        ],
    },
    "US": {
        "id": "US",
        "version": LOCALE_PACK_VERSION,
        "label": "United States",
        "currency": {
            "code": "USD",
            "symbol": "$",
            "minorUnitExponent": 2,
            "decimalSeparator": ".",
            "groupSeparator": ",",
            "priceEndings": ["00", "49", "99"],
            "defaultPriceMin": "5.00",
            "defaultPriceMax": "499.00",
        },
        "tax": {
            "basis": "exclusive",
            "defaultRate": "0.08875",
            "categoryRates": {
                "apparel": "0.08875",
                "automotive": "0.08875",
                "baby": "0.08875",
                "beauty": "0.08875",
                "books": "0.08875",
                "electronics": "0.08875",
                "grocery": "0.00",
                "health": "0.00",
                "home": "0.08875",
                "lubricants": "0.08875",
                "sports": "0.08875",
                "stationery": "0.08875",
                "toys": "0.08875",
            },
            "jurisdiction": "NYC-sales-tax",
            "components": {
                "intraRegion": [
                    {"code": "NY-state", "share": "0.4507042254"},
                    {"code": "MCTD", "share": "0.0422535211"},
                    {"code": "NYC-local", "share": "0.5070422535"},
                ],
                "interRegion": [{"code": "destination-sales-tax", "share": "1.0"}],
            },
        },
        "fiscalYearStartMonth": 1,
        "timezones": [
            "America/New_York",
            "America/Chicago",
            "America/Denver",
            "America/Los_Angeles",
        ],
        "fakerLocale": "en_US",
        "postcodePattern": "^[0-9]{5}(-[0-9]{4})?$",
        "calendarCoverage": {"startDate": "2005-01-01", "endDate": "2026-12-31"},
        "climate": {
            "profile": "continental-four-season",
            "summerC": 27,
            "winterC": 3,
            "monsoonMonths": [],
        },
        "holidayRules": [
            _fixed("New Year's Day", 1, 1),
            _nth("Martin Luther King Jr. Day", 1, 0, 3),
            _last("Memorial Day", 5, 0),
            _fixed("Independence Day", 7, 4),
            _nth("Labor Day", 9, 0, 1),
            _fixed("Veterans Day", 11, 11),
            _nth(
                "Thanksgiving",
                11,
                3,
                4,
                retail_behavior="closed",
            ),
            _nth_offset("Black Friday", 11, 3, 4, 1),
            _nth_offset("Cyber Monday", 11, 3, 4, 4),
            _fixed("Christmas", 12, 25, retail_behavior="closed"),
        ],
        "holidays": [],
        "saleSeasons": [
            {"id": "holiday-season", "startMonthDay": "11-15", "endMonthDay": "12-31"},
            {"id": "back-to-school", "startMonthDay": "08-01", "endMonthDay": "09-10"},
        ],
    },
    "GB": {
        "id": "GB",
        "version": LOCALE_PACK_VERSION,
        "label": "United Kingdom",
        "currency": {
            "code": "GBP",
            "symbol": "£",
            "minorUnitExponent": 2,
            "decimalSeparator": ".",
            "groupSeparator": ",",
            "priceEndings": ["00", "50", "99"],
            "defaultPriceMin": "5.00",
            "defaultPriceMax": "399.00",
        },
        "tax": {
            "basis": "inclusive",
            "defaultRate": "0.20",
            "categoryRates": {
                "apparel": "0.20",
                "automotive": "0.20",
                "baby": "0.00",
                "beauty": "0.20",
                "books": "0.00",
                "electronics": "0.20",
                "grocery": "0.00",
                "health": "0.00",
                "home": "0.20",
                "lubricants": "0.20",
                "sports": "0.20",
                "stationery": "0.20",
                "toys": "0.20",
            },
            "jurisdiction": "UK-VAT",
            "components": {
                "intraRegion": [{"code": "VAT", "share": "1.0"}],
                "interRegion": [{"code": "VAT", "share": "1.0"}],
            },
        },
        "fiscalYearStartMonth": 4,
        "timezones": ["Europe/London"],
        "fakerLocale": "en_GB",
        "postcodePattern": "^[A-Z]{1,2}[0-9][A-Z0-9]? [0-9][A-Z]{2}$",
        "calendarCoverage": {"startDate": "2005-01-01", "endDate": "2026-12-31"},
        "climate": {
            "profile": "temperate-maritime",
            "summerC": 19,
            "winterC": 6,
            "monsoonMonths": [],
        },
        "holidayRules": [
            _fixed("New Year's Day", 1, 1),
            _easter("Good Friday", -2),
            _easter("Easter Monday", 1),
            _nth("Early May Bank Holiday", 5, 0, 1),
            _last("Spring Bank Holiday", 5, 0),
            _last("Summer Bank Holiday", 8, 0),
            _nth_offset("Black Friday", 11, 3, 4, 1),
            _nth_offset("Cyber Monday", 11, 3, 4, 4),
            _fixed("Christmas", 12, 25, retail_behavior="closed"),
            _fixed("Boxing Day", 12, 26),
        ],
        "holidays": [
            _holiday("2011-04-29", "Royal Wedding Bank Holiday", "special"),
            _holiday("2012-06-05", "Diamond Jubilee Bank Holiday", "special"),
            _holiday("2022-06-03", "Platinum Jubilee Bank Holiday", "special"),
            _holiday("2022-09-19", "State Funeral Bank Holiday", "special"),
            _holiday("2023-05-08", "Coronation Bank Holiday", "special"),
        ],
        "saleSeasons": [
            {"id": "boxing-day", "startMonthDay": "12-26", "endMonthDay": "01-10"},
            {"id": "summer-sale", "startMonthDay": "06-15", "endMonthDay": "07-31"},
        ],
    },
    "DE": {
        "id": "DE",
        "version": LOCALE_PACK_VERSION,
        "label": "Germany (Europe PoC)",
        "currency": {
            "code": "EUR",
            "symbol": "€",
            "minorUnitExponent": 2,
            "decimalSeparator": ",",
            "groupSeparator": ".",
            "priceEndings": ["00", "49", "99"],
            "defaultPriceMin": "5.00",
            "defaultPriceMax": "449.00",
        },
        "tax": {
            "basis": "inclusive",
            "defaultRate": "0.19",
            "categoryRates": {
                "apparel": "0.19",
                "automotive": "0.19",
                "baby": "0.07",
                "beauty": "0.19",
                "books": "0.07",
                "electronics": "0.19",
                "grocery": "0.07",
                "health": "0.07",
                "home": "0.19",
                "lubricants": "0.19",
                "sports": "0.19",
                "stationery": "0.19",
                "toys": "0.19",
            },
            "jurisdiction": "DE-VAT",
            "components": {
                "intraRegion": [{"code": "USt", "share": "1.0"}],
                "interRegion": [{"code": "USt", "share": "1.0"}],
            },
        },
        "fiscalYearStartMonth": 1,
        "timezones": ["Europe/Berlin"],
        "fakerLocale": "de_DE",
        "postcodePattern": "^[0-9]{5}$",
        "calendarCoverage": {"startDate": "2005-01-01", "endDate": "2026-12-31"},
        "climate": {
            "profile": "temperate-continental",
            "summerC": 22,
            "winterC": 2,
            "monsoonMonths": [],
        },
        "holidayRules": [
            _fixed("Neujahr", 1, 1, retail_behavior="closed"),
            _easter("Karfreitag", -2, retail_behavior="closed"),
            _easter("Ostermontag", 1, retail_behavior="closed"),
            _fixed("Tag der Arbeit", 5, 1, retail_behavior="closed"),
            _easter("Christi Himmelfahrt", 39, retail_behavior="closed"),
            _easter("Pfingstmontag", 50, retail_behavior="closed"),
            _fixed(
                "Tag der Deutschen Einheit",
                10,
                3,
                retail_behavior="closed",
            ),
            _nth_offset("Black Friday", 11, 3, 4, 1),
            _nth_offset("Cyber Monday", 11, 3, 4, 4),
            _fixed(
                "Erster Weihnachtstag",
                12,
                25,
                retail_behavior="closed",
            ),
            _fixed(
                "Zweiter Weihnachtstag",
                12,
                26,
                retail_behavior="closed",
            ),
        ],
        "holidays": [],
        "saleSeasons": [
            {"id": "winter-sale", "startMonthDay": "01-15", "endMonthDay": "02-15"},
            {"id": "christmas-season", "startMonthDay": "11-20", "endMonthDay": "12-24"},
        ],
    },
}


def resolve_locale(country_code: str) -> dict[str, Any]:
    """Return a defensive copy of a supported locale pack."""

    try:
        return deepcopy(LOCALE_PACKS[country_code])
    except KeyError as exc:
        supported = ", ".join(sorted(LOCALE_PACKS))
        raise ValueError(
            f"unsupported countryCode {country_code!r}; supported: {supported}"
        ) from exc
