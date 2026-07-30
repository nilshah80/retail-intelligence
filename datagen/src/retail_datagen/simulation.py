"""Deterministic SKU/store demand and inventory-constrained retail simulation.

This module uses only generator vocabulary.  It intentionally knows nothing
about downstream canonical entities, features, gates, or model thresholds.
"""

from __future__ import annotations

import math
import calendar
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_EVEN
from functools import lru_cache
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from .calendar import holidays_for_range
from .customers import CustomerPopulation
from .identity import rng, shopify_order_name, stable_integer
from .lifecycle import lifecycle_adjustment
from .operations import fulfillment_timestamps

MONEY_QUANT = Decimal("0.01")

# Relative purchase frequency is normalized across the active assortment, so
# these values redistribute the configured store/day volume instead of changing
# the meaning of startingDailyOrders. Staples become fast movers while books and
# durable discretionary categories retain a realistic intermittent tail.
FAMILY_PURCHASE_FREQUENCY = {
    "grocery-dairy": Decimal("5.0"),
    "grocery-beverages": Decimal("3.8"),
    "grocery-staples": Decimal("3.4"),
    "grocery-snacks": Decimal("3.0"),
    "home-cleaning": Decimal("2.2"),
    "baby-care": Decimal("2.0"),
    "baby-feeding": Decimal("1.8"),
    "health-otc": Decimal("1.7"),
    "health-vitamins": Decimal("1.4"),
    "stationery-writing": Decimal("1.3"),
    "books-fiction": Decimal("0.55"),
    "books-nonfiction": Decimal("0.50"),
    "electronics-laptops": Decimal("0.55"),
    "electronics-tablets": Decimal("0.65"),
    "home-appliances": Decimal("0.60"),
}


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN))


def _iso_at(
    day: date,
    hour: int,
    timezone: str,
    minute: int = 0,
    second: int = 0,
) -> str:
    return datetime.combine(
        day,
        time(
            hour=min(23, max(0, hour)),
            minute=min(59, max(0, minute)),
            second=min(59, max(0, second)),
        ),
        tzinfo=ZoneInfo(timezone),
    ).isoformat()


def _fraction(*parts: Any) -> float:
    return stable_integer(*parts, modulo=1_000_000) / 1_000_000


def _poisson(mean: float, *seed_parts: Any) -> int:
    if mean <= 0:
        return 0
    random = rng(*seed_parts)
    if mean > 25:
        return max(0, round(random.gauss(mean, math.sqrt(mean))))
    threshold = math.exp(-mean)
    product = 1.0
    count = 0
    while product > threshold:
        count += 1
        product *= random.random()
    return count - 1


def _active(
    rows: list[dict[str, Any]],
    day: date,
    market_id: str,
) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row["marketId"] == market_id
        and date.fromisoformat(row["startDate"]) <= day
        and date.fromisoformat(row["endDate"]) >= day
    ]


def _recent_promotions(
    config: dict[str, Any],
    market: dict[str, Any],
    day: date,
) -> list[dict[str, Any]]:
    """Return post-campaign payback inputs only when the signal is enabled."""

    if not market["signals"]["promotions"]:
        return []
    market_id = market["marketId"]
    return [
        promotion
        for promotion in config["promotions"]
        if promotion["marketId"] == market_id
        and date.fromisoformat(promotion["endDate"]) < day
        <= date.fromisoformat(promotion["endDate"]) + timedelta(days=7)
    ]


def _shaped_multiplier(
    configured: float | int,
    start: date,
    end: date,
    day: date,
    shape: str,
) -> Decimal:
    target = Decimal(str(configured))
    if shape == "step" or end <= start:
        return target
    progress = Decimal((day - start).days) / Decimal((end - start).days)
    if shape == "linear":
        weight = Decimal("1") - progress
    elif shape == "ramp":
        weight = progress
    elif shape == "triangle":
        weight = Decimal("1") - abs(Decimal("2") * progress - Decimal("1"))
    else:
        raise ValueError(f"unsupported recovery shape {shape!r}")
    return Decimal("1") + (target - Decimal("1")) * weight


def _event_effect(
    config: dict[str, Any],
    day: date,
    market_id: str,
    *,
    store_id: str = "",
    department_id: str = "",
    category_id: str = "",
    channel_id: str = "",
) -> dict[str, Any]:
    result = {
        "eventIds": [],
        "demand": Decimal("1"),
        "traffic": Decimal("1"),
        "cost": Decimal("1"),
        "leadTime": Decimal("1"),
        "inventoryLoss": Decimal("0"),
    }
    for event in _active(config["events"], day, market_id):
        if event.get("storeId") and event["storeId"] != store_id:
            continue
        if event["departmentIds"] and department_id not in event["departmentIds"]:
            continue
        if event["categoryIds"] and category_id not in event["categoryIds"]:
            continue
        if event["channelIds"] and channel_id not in event["channelIds"]:
            continue
        start = date.fromisoformat(event["startDate"])
        end = date.fromisoformat(event["endDate"])
        shape = event["recoveryShape"]
        result["eventIds"].append(event["eventId"])
        for source, target in (
            ("demandMultiplier", "demand"),
            ("trafficMultiplier", "traffic"),
            ("costMultiplier", "cost"),
            ("leadTimeMultiplier", "leadTime"),
        ):
            result[target] *= _shaped_multiplier(
                event[source],
                start,
                end,
                day,
                shape,
            )
        result["inventoryLoss"] = max(
            result["inventoryLoss"],
            Decimal(str(event["inventoryLossPct"])),
        )
    return result


def _pandemic_effect(
    config: dict[str, Any],
    day: date,
    market_id: str,
    *,
    department_id: str = "",
    category_id: str = "",
    catalog_family: str = "",
    channel_type: str = "",
) -> dict[str, Any]:
    result = {
        "pandemicIds": [],
        "phaseIds": [],
        "effectModes": [],
        "demand": Decimal("1"),
        "traffic": Decimal("1"),
        "cost": Decimal("1"),
        "leadTime": Decimal("1"),
        "inventoryLoss": Decimal("0"),
    }
    for pandemic in config["pandemics"]:
        if market_id not in pandemic["marketIds"]:
            continue
        if not (
            date.fromisoformat(pandemic["startDate"])
            <= day
            <= date.fromisoformat(pandemic["endDate"])
        ):
            continue
        for phase in pandemic["phases"]:
            phase_start = date.fromisoformat(phase["startDate"])
            phase_end = date.fromisoformat(phase["endDate"])
            if not phase_start <= day <= phase_end:
                continue
            shape = phase["recoveryShape"]
            result["pandemicIds"].append(pandemic["pandemicId"])
            result["phaseIds"].append(phase["phaseId"])
            result["effectModes"].append(pandemic["effectMode"])
            demand = Decimal(str(phase["demandMultiplier"]))
            if department_id in phase["departmentMultipliers"]:
                demand *= Decimal(
                    str(phase["departmentMultipliers"][department_id])
                )
            if category_id in phase["categoryMultipliers"]:
                demand *= Decimal(str(phase["categoryMultipliers"][category_id]))
            if catalog_family in phase["catalogFamilyMultipliers"]:
                demand *= Decimal(
                    str(phase["catalogFamilyMultipliers"][catalog_family])
                )
            result["demand"] *= _shaped_multiplier(
                demand,
                phase_start,
                phase_end,
                day,
                shape,
            )
            traffic = Decimal(str(phase["trafficMultiplier"]))
            if channel_type in phase["channelTypeMultipliers"]:
                traffic *= Decimal(
                    str(phase["channelTypeMultipliers"][channel_type])
                )
            result["traffic"] *= _shaped_multiplier(
                traffic,
                phase_start,
                phase_end,
                day,
                shape,
            )
            for source, target in (
                ("costMultiplier", "cost"),
                ("leadTimeMultiplier", "leadTime"),
            ):
                result[target] *= _shaped_multiplier(
                    phase[source],
                    phase_start,
                    phase_end,
                    day,
                    shape,
                )
            result["inventoryLoss"] = max(
                result["inventoryLoss"],
                Decimal(str(phase["inventoryLossPct"])),
            )
    result["pandemicIds"] = sorted(set(result["pandemicIds"]))
    result["phaseIds"] = sorted(set(result["phaseIds"]))
    result["effectModes"] = sorted(set(result["effectModes"]))
    return result


def _active_sale_seasons(market: dict[str, Any], day: date) -> list[str]:
    month_day = day.strftime("%m-%d")
    active: list[str] = []
    for season in market["localePack"]["saleSeasons"]:
        start = season["startMonthDay"]
        end = season["endMonthDay"]
        applies = (
            start <= month_day <= end
            if start <= end
            else month_day >= start or month_day <= end
        )
        if applies:
            active.append(season["id"])
    return active


def _temperature(
    master_seed: int,
    market: dict[str, Any],
    day: date,
) -> tuple[Decimal, Decimal]:
    climate = market["localePack"]["climate"]
    summer = Decimal(str(climate["summerC"]))
    winter = Decimal(str(climate["winterC"]))
    peak_day = 125 if climate["profile"] == "tropical-monsoon" else 200
    seasonal = (summer + winter) / 2 + (summer - winter) / 2 * Decimal(
        str(
            math.cos(
                (day.timetuple().tm_yday - peak_day)
                / 365
                * math.tau
            )
        )
    )
    anomaly_weights = tuple(math.exp(-lag / 4.0) for lag in range(14))
    anomaly_weight_total = sum(anomaly_weights)
    temperature_anomaly = sum(
        weight
        * rng(
            master_seed,
            "weather-anomaly",
            market["marketId"],
            day - timedelta(days=lag),
        ).uniform(-3.5, 3.5)
        for lag, weight in enumerate(anomaly_weights)
    ) / anomaly_weight_total
    # Deterministic Gaussian pulses create a few genuine multi-day heat/cold
    # waves each year instead of independent daily jitter.
    epoch = day.toordinal() // 14
    for candidate_epoch in range(epoch - 1, epoch + 2):
        if (
            _fraction(
                master_seed,
                "temperature-spell-active",
                market["marketId"],
                candidate_epoch,
            )
            >= 0.12
        ):
            continue
        anchor_ordinal = candidate_epoch * 14 + stable_integer(
            master_seed,
            "temperature-spell-anchor",
            market["marketId"],
            candidate_epoch,
            modulo=14,
        )
        distance = day.toordinal() - anchor_ordinal
        direction = (
            1
            if stable_integer(
                master_seed,
                "temperature-spell-direction",
                market["marketId"],
                candidate_epoch,
                modulo=2,
            )
            else -1
        )
        amplitude = 4.0 + 3.0 * _fraction(
            master_seed,
            "temperature-spell-amplitude",
            market["marketId"],
            candidate_epoch,
        )
        temperature_anomaly += (
            direction
            * amplitude
            * math.exp(-0.5 * (distance / 3.5) ** 2)
        )
    temperature = seasonal + Decimal(str(temperature_anomaly))
    rain_random = rng(master_seed, "rain", market["marketId"], day)
    active_spell: tuple[date, float] | None = None
    for lag in range(7):
        spell_start = day - timedelta(days=lag)
        if (
            _fraction(
                master_seed,
                "rain-spell-start",
                market["marketId"],
                spell_start,
            )
            >= 0.055
        ):
            continue
        duration = 2 + stable_integer(
            master_seed,
            "rain-spell-duration",
            market["marketId"],
            spell_start,
            modulo=5,
        )
        if lag >= duration:
            continue
        intensity = 0.7 + 1.3 * _fraction(
            master_seed,
            "rain-spell-intensity",
            market["marketId"],
            spell_start,
        )
        if active_spell is None or intensity > active_spell[1]:
            active_spell = (spell_start, intensity)
    wet_spell = active_spell is not None
    profile = climate["profile"]
    if profile == "tropical-monsoon":
        months = climate["monsoonMonths"]
        season_start = date(day.year, min(months), 1)
        season_end = date(
            day.year,
            max(months),
            calendar.monthrange(day.year, max(months))[1],
        )
        transition_days = 21
        if season_start <= day <= season_end:
            monsoon_intensity = 1.0
        elif 0 < (season_start - day).days <= transition_days:
            progress = (
                transition_days - (season_start - day).days
            ) / transition_days
            monsoon_intensity = 0.5 - 0.5 * math.cos(math.pi * progress)
        elif 0 < (day - season_end).days <= transition_days:
            progress = (day - season_end).days / transition_days
            monsoon_intensity = 0.5 + 0.5 * math.cos(math.pi * progress)
        else:
            monsoon_intensity = 0.0
        rain_probability = (
            0.03
            + 0.55 * monsoon_intensity
            + (0.28 if wet_spell else 0.0)
        )
        precipitation = (
            Decimal(
                str(
                    rain_random.gammavariate(
                        1.6,
                        (3.0 + 12.0 * monsoon_intensity)
                        * (active_spell[1] if active_spell else 1.0),
                    )
                )
            )
            if rain_random.random() < rain_probability
            else Decimal("0")
        )
    elif profile == "temperate-maritime":
        rain_probability = 0.78 if wet_spell else 0.22
        precipitation = (
            Decimal(
                str(
                    rain_random.gammavariate(
                        1.4,
                        3.2 * (active_spell[1] if active_spell else 1.0),
                    )
                )
            )
            if rain_random.random() < rain_probability
            else Decimal("0")
        )
    else:
        rain_probability = 0.70 if wet_spell else 0.14
        precipitation = (
            Decimal(
                str(
                    rain_random.gammavariate(
                        1.3,
                        3.6 * (active_spell[1] if active_spell else 1.0),
                    )
                )
            )
            if rain_random.random() < rain_probability
            else Decimal("0")
        )
    return (
        temperature.quantize(Decimal("0.1")),
        precipitation.quantize(Decimal("0.1")),
    )


def _inflation_factor(
    market: dict[str, Any],
    day: date,
    anchor: date,
) -> Decimal:
    years = max(0, day.year - anchor.year)
    return Decimal(
        str((1 + market["priceDynamics"]["annualInflationRate"]) ** years)
    )


def _snap_price_ending(value: Decimal, market: dict[str, Any]) -> Decimal:
    endings = market["localePack"]["currency"]["priceEndings"]
    candidates: list[Decimal] = []
    whole = int(value)
    for major in range(max(0, whole - 1), whole + 2):
        for ending in endings:
            candidates.append(
                Decimal(major) + Decimal(str(ending)) / Decimal("100")
            )
    return min(
        (candidate for candidate in candidates if candidate > 0),
        key=lambda candidate: (abs(candidate - value), candidate),
    ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def _retail_price(
    value: Decimal,
    market: dict[str, Any],
    *price_state: Any,
) -> Decimal:
    """Apply locale price endings at the configured, non-universal rate."""

    adherence = float(market["priceDynamics"]["priceEndingAdherence"])
    if (
        _fraction(
            "price-ending-adherence",
            market["marketId"],
            *price_state,
        )
        < adherence
    ):
        return _snap_price_ending(value, market)
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def _promotional_price(
    regular_price: Decimal,
    variant: dict[str, Any],
    market: dict[str, Any],
    day: date,
    start: date,
    end: date,
    discount_pct: Decimal,
    promotion_id: str,
    promotion_type: str,
    cost_multiplier: Decimal = Decimal("1"),
) -> Decimal:
    """Apply one best-price promotion with stable ending and cost guardrails."""

    discounted = regular_price * (Decimal("1") - discount_pct)
    cost_floor: Decimal | None = None
    if promotion_type != "fire-sale":
        base_cost = (
            variant["_baseCost"]
            if "_baseCost" in variant
            else variant["baseCost"]
        )
        launch_date = (
            variant["_launchDate"]
            if "_launchDate" in variant
            else variant["launchDate"]
        )
        current_cost = _price_for_day(
            base_cost,
            market,
            f"{variant['sku']}:cost",
            day,
            start,
            end,
            inflation_anchor=date.fromisoformat(launch_date),
        ) * cost_multiplier
        cost_floor = (current_cost * Decimal("1.02")).quantize(
            MONEY_QUANT,
            rounding=ROUND_CEILING,
        )
        discounted = max(discounted, cost_floor)
    retail_price = _retail_price(
        discounted,
        market,
        variant["sku"],
        "promotion",
        promotion_id,
    )
    return (
        max(retail_price, cost_floor)
        if cost_floor is not None
        else retail_price
    )


def _inflated_base_price(
    base: Decimal,
    market: dict[str, Any],
    day: date,
    anchor: date,
) -> Decimal:
    return base * _inflation_factor(market, day, anchor)


@lru_cache(maxsize=200_000)
def _annual_price_schedule(
    profile: str,
    events: int,
    sku: str,
    year: int,
    year_days: int,
    anchor_year: int,
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    """Return one continuous, irregular price-list path for a SKU/year."""

    if events <= 0 or profile == "stable":
        return ((1,), ("0",))
    interval = year_days / events
    event_days: list[int] = [1]
    if year <= anchor_year:
        adjustment = Decimal("0")
    else:
        prior_year_days = 366 if calendar.isleap(year - 1) else 365
        _, prior_adjustments = _annual_price_schedule(
            profile,
            events,
            sku,
            year - 1,
            prior_year_days,
            anchor_year,
        )
        adjustment = Decimal(prior_adjustments[-1])
    adjustments: list[str] = [str(adjustment)]
    prior_day = 1
    for event_index in range(events):
        centre = round((event_index + 0.5) * interval)
        jitter_span = max(1, round(interval * 0.20))
        jitter = (
            stable_integer(
                "price-event-day",
                sku,
                year,
                event_index,
                modulo=2 * jitter_span + 1,
            )
            - jitter_span
        )
        event_day = min(
            year_days,
            max(prior_day + 1, centre + jitter),
        )
        prior_day = event_day
        draw = stable_integer(
            "price-event-step",
            sku,
            year,
            event_index,
            modulo=100,
        )
        if profile == "response-rich":
            # Inflation owns the long-run trend. Regular price-list changes
            # therefore mean-revert instead of accumulating at the upper
            # clamp and synchronously falling back every January.
            downward_threshold = (
                70
                if adjustment >= Decimal("0.08")
                else 20
                if adjustment <= Decimal("-0.04")
                else 46
            )
            if draw < downward_threshold // 3:
                step = Decimal("-0.025")
            elif draw < downward_threshold:
                step = Decimal("-0.0125")
            elif draw < downward_threshold + 30:
                step = Decimal("0.010")
            elif draw < downward_threshold + 48:
                step = Decimal("0.020")
            else:
                step = Decimal("0.030")
            adjustment = max(
                Decimal("-0.08"),
                min(Decimal("0.12"), adjustment + step),
            )
        else:
            downward_threshold = (
                65
                if adjustment >= Decimal("0.04")
                else 30
                if adjustment <= Decimal("-0.02")
                else 48
            )
            step = Decimal("-0.010") if draw < downward_threshold else Decimal("0.010")
            adjustment = max(
                Decimal("-0.04"),
                min(Decimal("0.06"), adjustment + step),
            )
        event_days.append(event_day)
        adjustments.append(str(adjustment))
    return (tuple(event_days), tuple(adjustments))


def _price_for_day(
    base: Decimal,
    market: dict[str, Any],
    sku: str,
    day: date,
    start: date,
    end: date,
    *,
    inflation_anchor: date | None = None,
) -> Decimal:
    dynamics = market["priceDynamics"]
    profile = dynamics["profile"]
    events = dynamics["priceChangeEventsPerSkuPerYear"]
    year_days = 366 if calendar.isleap(day.year) else 365
    event_days, adjustments = _annual_price_schedule(
        profile,
        events,
        sku,
        day.year,
        year_days,
        (inflation_anchor or start).year,
    )
    bucket = max(
        0,
        bisect_right(event_days, day.timetuple().tm_yday) - 1,
    )
    adjustment = Decimal(adjustments[bucket])
    # Retail price lists carry discrete effective prices. Inflation therefore
    # steps at calendar-year boundaries instead of changing the amount daily.
    nominal = _inflated_base_price(
        base,
        market,
        day,
        inflation_anchor or start,
    )
    return _retail_price(
        nominal * (Decimal("1") + adjustment),
        market,
        sku,
        day.year,
        bucket,
    )


def _seasonality_raw(
    peak_month: int,
    strength: Decimal,
    day: date,
) -> Decimal:
    """Return a continuous asymmetric seasonal curve before normalization."""

    peak_day_of_month = 24 if peak_month == 12 else 15
    candidate_peaks = [
        date(year, peak_month, peak_day_of_month)
        for year in (day.year - 1, day.year, day.year + 1)
    ]
    peak_day = min(
        candidate_peaks,
        key=lambda candidate: abs((day - candidate).days),
    )
    offset_days = (day - peak_day).days
    if peak_month == 12:
        # Gift demand builds through 22–24 December, then releases quickly
        # without the old rectangular, fixed-date step.
        sigma_days = 30.0 if offset_days < 0 else 5.0
    else:
        sigma_days = 55.0 if offset_days < 0 else 24.0
    bump = math.exp(-0.5 * (offset_days / sigma_days) ** 2)
    floor = max(
        Decimal("0.25"),
        Decimal("1") - strength * Decimal("1.50"),
    )
    return floor + strength * Decimal("3") * Decimal(str(bump))


@lru_cache(maxsize=2_048)
def _seasonality_annual_mean(
    peak_month: int,
    strength_text: str,
    year: int,
) -> Decimal:
    """Numerically normalize each configured curve to mean one per year."""

    strength = Decimal(strength_text)
    year_start = date(year, 1, 1)
    year_days = 366 if calendar.isleap(year) else 365
    return sum(
        (
            _seasonality_raw(
                peak_month,
                strength,
                year_start + timedelta(days=offset),
            )
            for offset in range(year_days)
        ),
        Decimal("0"),
    ) / Decimal(year_days)


def _seasonality_factor(
    peak_month: int,
    strength: Decimal,
    day: date,
) -> Decimal:
    """Return a continuous asymmetric factor whose annual mean is one."""

    raw = _seasonality_raw(peak_month, strength, day)
    mean = _seasonality_annual_mean(
        peak_month,
        str(strength.normalize()),
        day.year,
    )
    return max(Decimal("0.05"), raw / mean)


def _holiday_demand_factor(
    holidays: list[dict[str, str]],
    *,
    country_code: str,
    channel_type: str,
) -> Decimal:
    """Apply locale-owned closure/retail behavior without name matching."""

    closure_factors: list[Decimal] = []
    factors: list[Decimal] = []
    for holiday in holidays:
        name = holiday["name"]
        behavior = holiday.get("retailBehavior", "public-holiday")
        if behavior == "observance":
            continue
        if behavior == "closed":
            closure_factors.append(
                Decimal("0.55")
                if channel_type == "online"
                else Decimal("0.05")
            )
        elif behavior == "retail-peak" and name == "Black Friday":
            factors.append(Decimal("3.20"))
        elif behavior == "retail-peak" and name == "Cyber Monday":
            factors.append(
                Decimal("2.80")
                if channel_type == "online"
                else Decimal("1.35")
            )
        else:
            factors.append(
                {
                    "Diwali": Decimal("1.45"),
                    "Boxing Day": Decimal("2.20"),
                    "Republic Day": Decimal("1.22"),
                    "Independence Day": Decimal("1.18"),
                    "Veterans Day": Decimal("1.08"),
                }.get(name, Decimal("1.15"))
            )
    if closure_factors:
        return min(closure_factors)
    return max(factors, default=Decimal("1"))


def _tax_rate_for_line(
    market: dict[str, Any],
    tax_category: str,
    unit_price: Decimal,
    day: date,
) -> Decimal:
    """Apply the current locale pack plus material PoC threshold rules."""

    if market["countryCode"] == "IN" and day < date(2017, 7, 1):
        return {
            "apparel": Decimal("0.05"),
            "electronics": Decimal("0.125"),
            "grocery": Decimal("0.05"),
        }.get(tax_category, Decimal("0.125"))
    if (
        market["countryCode"] == "US"
        and market["regionCode"] == "NY"
        and tax_category == "apparel"
        and unit_price < Decimal("110")
    ):
        return Decimal("0")
    if (
        market["countryCode"] == "IN"
        and day >= date(2017, 7, 1)
        and tax_category == "apparel"
        and unit_price <= Decimal("1000")
    ):
        return Decimal("0.05")
    return Decimal(
        market["localePack"]["tax"]["categoryRates"].get(
            tax_category,
            market["localePack"]["tax"]["defaultRate"],
        )
    )


def _tax_amounts(
    unit_price: Decimal,
    quantity: int,
    rate: Decimal,
    basis: str,
) -> tuple[Decimal, Decimal, Decimal]:
    listed_total = unit_price * quantity
    if basis == "inclusive":
        gross = listed_total
        net = (gross / (Decimal("1") + rate)).quantize(
            MONEY_QUANT,
            rounding=ROUND_HALF_EVEN,
        )
        tax = gross - net
    else:
        net = listed_total
        tax = (net * rate).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)
        gross = net + tax
    return net, tax, gross


def _store_assortment(
    master_seed: int,
    store: dict[str, Any],
    variants: list[dict[str, Any]],
    start: date,
    end: date,
    timezone_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for variant in variants:
        by_category[variant["_categoryId"]].append(variant)
    for category_id, category_variants in sorted(by_category.items()):
        ordered = sorted(
            category_variants,
            key=lambda row: stable_integer(
                master_seed,
                "store-assortment",
                store["storeId"],
                row["sku"],
            ),
        )
        target = max(1, round(len(ordered) * store["assortmentCoverage"]))
        for variant in ordered[:target]:
            valid_from = max(
                start,
                date.fromisoformat(variant["_launchDate"]),
            )
            selected.append(variant)
            rows.append(
                {
                    "marketKey": store["marketId"],
                    "storeKey": store["storeId"],
                    "sku": variant["sku"],
                    "productCode": variant["_productCode"],
                    "departmentId": variant["_departmentId"],
                    "categoryId": category_id,
                    "validFrom": valid_from.isoformat(),
                    "validTo": min(
                        end,
                        (
                            date.fromisoformat(variant["_discontinueDate"])
                            if variant["_discontinueDate"]
                            else end
                        ),
                    ).isoformat(),
                    # Native effective-dated availability evidence. Ingestion
                    # uses this observation to make an absent sale knowable
                    # after each covered business day, instead of assigning
                    # every materialized zero to the final landing timestamp.
                    "observedAt": _iso_at(valid_from, 0, timezone_name),
                    "active": "true",
                    "assortmentReason": "deterministic-store-coverage",
                }
            )
    return selected, rows


def _segment_for_event(
    config: dict[str, Any],
    master_seed: int,
    event_key: str,
) -> dict[str, Any]:
    position = _fraction(master_seed, "segment", event_key)
    cumulative = 0.0
    for segment in config["customerSegments"]:
        cumulative += float(segment["share"])
        if position <= cumulative:
            return segment
    return config["customerSegments"][-1]


def _channel_distribution(
    master_seed: int,
    store: dict[str, Any],
    variant: dict[str, Any],
    channel_types: dict[str, str],
    market: dict[str, Any],
    day: date,
    start: date,
    end: date,
) -> list[tuple[str, Decimal]]:
    """Return positive channel shares with configured secular online growth."""

    channels = sorted(store["channelIds"])
    if len(channels) == 1:
        return [(channels[0], Decimal("1"))]
    demand = market["demand"]
    horizon_days = max(1, (end - start).days)
    progress = Decimal((day - start).days) / Decimal(horizon_days)
    configured_share = (
        Decimal(str(demand["onlineShareStart"]))
        + (
            Decimal(str(demand["onlineShareEnd"]))
            - Decimal(str(demand["onlineShareStart"]))
        )
        * progress
    )
    variation = Decimal(str(demand["onlineShareSkuVariation"]))
    sku_offset = variation * (
        Decimal(
            stable_integer(
                master_seed,
                "channel-online-propensity",
                store["storeId"],
                variant["sku"],
                modulo=2_000_001,
            )
        )
        / Decimal("1000000")
        - Decimal("1")
    )
    online_share = max(
        Decimal("0.01"),
        min(Decimal("0.95"), configured_share + sku_offset),
    )
    type_counts: dict[str, int] = defaultdict(int)
    for channel_id in channels:
        type_counts[channel_types[channel_id]] += 1
    weights: list[Decimal] = []
    for channel_id in channels:
        channel_type = channel_types[channel_id]
        type_share = (
            online_share
            if channel_type == "online"
            else Decimal("1") - online_share
        )
        weights.append(
            type_share
            / Decimal(type_counts[channel_type])
        )
    total = sum(weights, Decimal("0"))
    return [
        (channel_id, weight / total)
        for channel_id, weight in zip(channels, weights, strict=True)
    ]

def _promotion_applies(
    promotion: dict[str, Any],
    store: dict[str, Any],
    variant: dict[str, Any],
    segment_id: str,
    channel_id: str,
) -> bool:
    if promotion["storeIds"] and store["storeId"] not in promotion["storeIds"]:
        return False
    if promotion["channelIds"] and channel_id not in promotion["channelIds"]:
        return False
    if promotion["departmentIds"] and variant["_departmentId"] not in promotion["departmentIds"]:
        return False
    if promotion["categoryIds"] and variant["_categoryId"] not in promotion["categoryIds"]:
        return False
    if (
        promotion["customerSegmentIds"]
        and segment_id not in promotion["customerSegmentIds"]
    ):
        return False
    return True


def _portfolio_weight(variant: dict[str, Any]) -> Decimal:
    return Decimal(str(variant["_demandWeight"])) * FAMILY_PURCHASE_FREQUENCY.get(
        variant["_catalogFamily"],
        Decimal("1"),
    )


def _expected_units_per_line(variant: dict[str, Any]) -> Decimal:
    family = variant["_catalogFamily"]
    if family == "grocery-dairy":
        return Decimal("2.72")
    if family in {"grocery-beverages", "grocery-snacks"}:
        return Decimal("1.90")
    if family == "grocery-staples":
        return Decimal("1.61")
    if family in {
        "home-cleaning",
        "baby-care",
        "baby-feeding",
        "health-otc",
        "health-vitamins",
        "stationery-writing",
    }:
        return Decimal("1.21")
    return Decimal("1.03")


def _weighted_factor(
    variant: dict[str, Any],
    mean_weight: Decimal,
) -> Decimal:
    return _portfolio_weight(variant) / mean_weight


def _average_active_portfolio_weight(
    variants: list[dict[str, Any]],
    period_start: date,
    period_end: date,
) -> Decimal:
    """Return average live assortment weight over one bounded period."""

    period_days = Decimal((period_end - period_start).days + 1)
    weighted_days = Decimal("0")
    for variant in variants:
        active_start = max(
            period_start,
            date.fromisoformat(variant["_launchDate"]),
        )
        active_end = min(
            period_end,
            (
                date.fromisoformat(variant["_discontinueDate"])
                if variant["_discontinueDate"]
                else period_end
            ),
        )
        if active_end < active_start:
            continue
        active_days = Decimal((active_end - active_start).days + 1)
        weighted_days += _portfolio_weight(variant) * active_days
    return max(Decimal("0.0001"), weighted_days / period_days)


def _purchase_quantities(
    master_seed: int,
    event_key: str,
    variant: dict[str, Any],
    units: int,
) -> list[int]:
    """Split daily SKU units into realistic customer purchase quantities."""

    if units <= 0:
        return []
    family = variant["_catalogFamily"]
    if family == "grocery-dairy":
        choices = ((1, .40), (2, .30), (4, .16), (6, .10), (12, .04))
    elif family in {"grocery-beverages", "grocery-snacks"}:
        choices = ((1, .48), (2, .30), (3, .12), (4, .07), (6, .03))
    elif family == "grocery-staples":
        choices = ((1, .60), (2, .27), (3, .09), (5, .04))
    elif family in {
        "home-cleaning",
        "baby-care",
        "baby-feeding",
        "health-otc",
        "health-vitamins",
        "stationery-writing",
    }:
        choices = ((1, .82), (2, .15), (3, .03))
    else:
        choices = ((1, .97), (2, .03))

    result: list[int] = []
    remaining = units
    purchase_index = 0
    while remaining:
        position = _fraction(
            master_seed,
            "purchase-quantity",
            event_key,
            purchase_index,
        )
        cumulative = 0.0
        selected = 1
        for quantity, share in choices:
            cumulative += share
            if position <= cumulative:
                selected = quantity
                break
        result.append(min(remaining, selected))
        remaining -= result[-1]
        purchase_index += 1
    return result


def _split_allocations(
    allocations: list[dict[str, Any]],
    quantities: list[int],
) -> list[list[dict[str, Any]]]:
    """Distribute warehouse allocations across customer purchase lines."""

    remaining = [
        {
            "warehouseId": row["warehouseId"],
            "quantity": row["quantity"],
            "priority": row["priority"],
        }
        for row in allocations
    ]
    result: list[list[dict[str, Any]]] = []
    allocation_index = 0
    for quantity in quantities:
        needed = quantity
        line_allocations: list[dict[str, Any]] = []
        while needed:
            allocation = remaining[allocation_index]
            take = min(needed, allocation["quantity"])
            line_allocations.append(
                {
                    "warehouseId": allocation["warehouseId"],
                    "quantity": take,
                    "priority": allocation["priority"],
                }
            )
            allocation["quantity"] -= take
            needed -= take
            if allocation["quantity"] == 0:
                allocation_index += 1
        result.append(line_allocations)
    return result


def _add_batch(
    batches_by_inventory_key: dict[tuple[str, str], list[dict[str, Any]]],
    batch_by_key: dict[str, dict[str, Any]],
    *,
    batch_key: str,
    source_type: str,
    source_reference: str,
    warehouse_id: str,
    variant: dict[str, Any],
    receipt_day: date,
    quantity: int,
    manufacture_day: date | None = None,
    expiry_day: date | None = None,
) -> dict[str, Any] | None:
    if quantity <= 0:
        return None
    shelf_life = variant["_shelfLifeDays"]
    if manufacture_day is None:
        manufacture_day = receipt_day - timedelta(
            days=3 if shelf_life and int(shelf_life) <= 30 else 30
        )
    if expiry_day is None and shelf_life:
        expiry_day = receipt_day + timedelta(days=int(shelf_life))
    row = {
        "batchKey": batch_key,
        "sourceType": source_type,
        "sourceReference": source_reference,
        "warehouseId": warehouse_id,
        "sku": variant["sku"],
        "productCode": variant["_productCode"],
        "variantCode": variant["_variantCode"],
        "manufactureDate": manufacture_day.isoformat(),
        "receiptDate": receipt_day.isoformat(),
        "expiryDate": expiry_day.isoformat() if expiry_day else "",
        "quantityReceived": quantity,
        "quantityRemainingAtExtract": quantity,
    }
    batch_by_key[batch_key] = row
    batches_by_inventory_key[(warehouse_id, variant["sku"])].append(row)
    return row


def _deplete_batches(
    batches_by_inventory_key: dict[tuple[str, str], list[dict[str, Any]]],
    inventory_key: tuple[str, str],
    quantity: int,
    *,
    batch_key: str = "",
    on_exhausted: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """Deplete batch balances in FEFO order and return the consumed lot pieces."""

    if quantity <= 0:
        return []
    all_candidates = batches_by_inventory_key[inventory_key]
    candidates = all_candidates
    if batch_key:
        candidates = [row for row in candidates if row["batchKey"] == batch_key]
    ordered = sorted(
        candidates,
        key=lambda row: (
            row["expiryDate"] == "",
            row["expiryDate"] or "9999-12-31",
            row["receiptDate"],
            row["batchKey"],
        ),
    )
    remaining = quantity
    consumed: list[dict[str, Any]] = []
    for row in ordered:
        available = row["quantityRemainingAtExtract"]
        if available <= 0:
            continue
        take = min(remaining, available)
        row["quantityRemainingAtExtract"] -= take
        consumed.append({**row, "quantity": take})
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise RuntimeError(
            f"batch balance underflow for {inventory_key}: "
            f"requested {quantity}, missing {remaining}"
        )
    exhausted = [
        row
        for row in all_candidates
        if row["quantityRemainingAtExtract"] <= 0
    ]
    if exhausted:
        batches_by_inventory_key[inventory_key] = [
            row
            for row in all_candidates
            if row["quantityRemainingAtExtract"] > 0
        ]
        if on_exhausted:
            for row in exhausted:
                on_exhausted(row)
    return consumed


def _allocate_inventory(
    config: dict[str, Any],
    master_seed: int,
    store: dict[str, Any],
    sku: str,
    requested: int,
    event_key: str,
    inventory: dict[tuple[str, str], int],
    committed_inventory: dict[tuple[str, str], int],
    damaged_inventory: dict[tuple[str, str], int],
    quality_control_inventory: dict[tuple[str, str], int],
) -> list[dict[str, Any]]:
    if requested <= 0:
        return []
    priorities = store["warehousePriority"]
    safety_stock = config["operations"]["inventory"]["safetyStockUnits"]
    split = (
        requested >= 2
        and len(priorities) >= 2
        and _fraction(master_seed, "split-fulfillment", event_key)
        < config["operations"]["fulfillment"]["splitRate"]
    )
    allocations: list[dict[str, Any]] = []
    remaining = requested
    for index, warehouse_id in enumerate(priorities):
        key = (warehouse_id, sku)
        usable = max(
            0,
            inventory[key]
            - committed_inventory[key]
            - damaged_inventory[key]
            - quality_control_inventory[key]
            - safety_stock,
        )
        if usable <= 0:
            continue
        desired = remaining
        if split and index == 0:
            desired = max(1, requested // 2)
        quantity = min(usable, desired)
        if quantity:
            committed_inventory[key] += quantity
            allocations.append(
                {
                    "warehouseId": warehouse_id,
                    "quantity": quantity,
                    "priority": index + 1,
                }
            )
            remaining -= quantity
        if remaining <= 0:
            break
    return allocations


def _group_baskets(
    config: dict[str, Any],
    master_seed: int,
    line_events: list[dict[str, Any]],
    customer_population: CustomerPopulation,
) -> list[dict[str, Any]]:
    by_store_day: dict[
        tuple[str, date, str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    for event in line_events:
        by_store_day[
            (
                event["storeId"],
                event["day"],
                event["customerSegmentId"],
                event["channelId"],
            )
        ].append(event)
    order_headers: list[dict[str, Any]] = []
    order_sequence_by_store_day: dict[tuple[str, date], int] = defaultdict(int)
    for (store_id, day, segment_id, channel_id), rows in sorted(
        by_store_day.items()
    ):
        ordered = sorted(
            rows,
            key=lambda row: (
                stable_integer(
                    master_seed,
                    "basket-line-order",
                    row["eventKey"],
                ),
                row["eventKey"],
            ),
        )
        cursor = 0
        basket_index = order_sequence_by_store_day[(store_id, day)]
        market = next(
            row
            for row in config["markets"]
            if row["marketId"] == ordered[0]["marketId"]
        )
        average_lines = float(market["demand"]["averageLinesPerOrder"])
        while cursor < len(ordered):
            # A shifted Poisson retains the configured mean without limiting an
            # average of 1.8 to only one- or two-line baskets.
            size = 1 + _poisson(
                max(0, average_lines - 1),
                master_seed,
                "basket-size",
                store_id,
                day,
                segment_id,
                channel_id,
                basket_index,
            )
            size = max(1, min(8, size))
            size = min(
                size,
                len(ordered) - cursor,
            )
            basket = ordered[cursor : cursor + size]
            order_key = f"{store_id}:{day}:order:{basket_index:05d}"
            for line_number, event in enumerate(basket, start=1):
                event["orderKey"] = order_key
                event["lineKey"] = f"{order_key}:line:{line_number:03d}"
                event["lineNumber"] = line_number * 10_000
            net = sum((event["net"] for event in basket), Decimal("0"))
            tax = sum((event["tax"] for event in basket), Decimal("0"))
            gross = sum((event["gross"] for event in basket), Decimal("0"))
            market_id = basket[0]["marketId"]
            customer_key, customer_created_date = customer_population.allocate(
                market_id,
                basket[0]["customerSegmentId"],
                day,
                order_key,
            )
            order_headers.append(
                {
                    "orderKey": order_key,
                    "marketId": market_id,
                    "storeId": store_id,
                    "day": day,
                    "createdAt": min(event["createdAt"] for event in basket),
                    "currencyCode": basket[0]["currencyCode"],
                    "taxesIncluded": basket[0]["taxesIncluded"],
                    "net": net,
                    "tax": tax,
                    "gross": gross,
                    "units": sum(event["quantity"] for event in basket),
                    "lineCount": len(basket),
                    "customerSegmentId": basket[0]["customerSegmentId"],
                    "customerKey": customer_key,
                    "customerCreatedDate": customer_created_date,
                    "bcCustomerKey": (
                        customer_key or f"walk-in:{market_id}"
                    ),
                    "channelId": basket[0]["channelId"],
                }
            )
            cursor += size
            basket_index += 1
        order_sequence_by_store_day[(store_id, day)] = basket_index
    return order_headers


def simulate(
    config: dict[str, Any],
    markets: dict[str, dict[str, Any]],
    stores: dict[str, dict[str, Any]],
    warehouses: dict[str, dict[str, Any]],
    variants_by_market: dict[str, list[dict[str, Any]]],
    start: date,
    end: date,
    *,
    spool_factory: Any | None = None,
    customer_population: CustomerPopulation | None = None,
) -> dict[str, Any]:
    """Generate demand, constrained sales, inventory, and contextual source evidence."""

    master_seed = config["identity"]["masterSeed"]
    customer_population = customer_population or CustomerPopulation(
        config,
        start,
        end,
    )

    def row_stream(name: str) -> Any:
        return spool_factory(name) if spool_factory else []
    operations = config["operations"]
    inventory_policy = operations["inventory"]
    supply_policy = operations["supplyChain"]
    channel_types = {
        row["channelId"]: row["type"]
        for row in config["channels"]
    }
    holiday_by_market_and_date: dict[
        str,
        dict[str, list[dict[str, str]]],
    ] = {
        market_id: {
            holiday["date"]: []
            for holiday in holidays_for_range(market["localePack"], start, end)
        }
        for market_id, market in markets.items()
    }
    for market_id, market in markets.items():
        for holiday in holidays_for_range(market["localePack"], start, end):
            holiday_by_market_and_date[market_id][holiday["date"]].append(holiday)
    inventory: dict[tuple[str, str], int] = defaultdict(int)
    variants_by_inventory_key = {
        (warehouse["warehouseId"], variant["sku"]): variant
        for warehouse in warehouses.values()
        for variant in variants_by_market[warehouse["marketId"]]
    }
    batches_by_inventory_key: dict[
        tuple[str, str],
        list[dict[str, Any]],
    ] = defaultdict(list)
    batch_by_key: dict[str, dict[str, Any]] = {}
    batch_balances = row_stream("simulation-batch-balances")
    expiry_batches_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)

    def finalize_batch(batch: dict[str, Any]) -> None:
        if batch_by_key.pop(batch["batchKey"], None) is not None:
            batch_balances.append(dict(batch))

    def schedule_expiry(
        batch: dict[str, Any] | None,
        *,
        earliest: date | None = None,
    ) -> None:
        if batch is None or not batch["expiryDate"]:
            return
        expiry_event_day = date.fromisoformat(
            batch["expiryDate"]
        ) + timedelta(days=1)
        if earliest is not None:
            expiry_event_day = max(expiry_event_day, earliest)
        expiry_batches_by_date[expiry_event_day].append(batch)
    store_variants: dict[str, list[dict[str, Any]]] = {}
    assortment_rows: list[dict[str, Any]] = []
    for store in stores.values():
        selected, rows = _store_assortment(
            master_seed,
            store,
            variants_by_market[store["marketId"]],
            start,
            end,
            markets[store["marketId"]]["timezone"],
        )
        store_variants[store["storeId"]] = selected
        assortment_rows.extend(rows)
    annual_portfolio_weight: dict[tuple[str, int], Decimal] = {}
    for store in stores.values():
        for year in range(start.year, end.year + 1):
            period_start = max(start, date(year, 1, 1))
            period_end = min(end, date(year, 12, 31))
            annual_portfolio_weight[(store["storeId"], year)] = (
                _average_active_portfolio_weight(
                    store_variants[store["storeId"]],
                    period_start,
                    period_end,
                )
            )

    # A source extract normally begins with inventory bought from demand
    # observed before the requested data window. Model that boundary explicitly
    # when the Config Builder asks for opening days of cover. This is a
    # merchandising-plan bootstrap only: after the first day, replenishment
    # uses source-observable sales and availability from the generated run.
    opening_daily_rate: dict[tuple[str, str], Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for store in stores.values():
        active_variants = [
            variant
            for variant in store_variants[store["storeId"]]
            if date.fromisoformat(variant["_launchDate"]) <= start
            and (
                not variant["_discontinueDate"]
                or date.fromisoformat(variant["_discontinueDate"]) >= start
            )
        ]
        cover_warehouses = [
            warehouse_id
            for warehouse_id in store["warehousePriority"]
            if warehouses[warehouse_id].get("openingStockDaysOfCover", 0) > 0
        ]
        if not active_variants or not cover_warehouses:
            continue
        market = markets[store["marketId"]]
        portfolio_weight = annual_portfolio_weight[
            (store["storeId"], start.year)
        ]
        for variant in active_variants:
            planned_rate = (
                Decimal(str(market["demand"]["demandLevelScalar"]))
                * Decimal(str(store["demandScale"]))
                * Decimal(str(market["demand"]["startingDailyOrders"]))
                * Decimal(str(market["demand"]["averageLinesPerOrder"]))
                * _portfolio_weight(variant)
                / portfolio_weight
                * _expected_units_per_line(variant)
            )
            rate_share = planned_rate / Decimal(len(cover_warehouses))
            for warehouse_id in cover_warehouses:
                opening_daily_rate[(warehouse_id, variant["sku"])] += rate_share

    for warehouse in warehouses.values():
        for variant in variants_by_market[warehouse["marketId"]]:
            active_at_start = (
                date.fromisoformat(variant["_launchDate"]) <= start
                and (
                    not variant["_discontinueDate"]
                    or date.fromisoformat(variant["_discontinueDate"]) >= start
                )
            )
            constrained = (
                _fraction(master_seed, "constrained-sku", warehouse["warehouseId"], variant["sku"])
                < inventory_policy["stockoutSkuRate"]
            )
            opening = 0
            if active_at_start and not constrained:
                configured_floor = warehouse["openingStockPerSku"]
                cover_days = warehouse.get("openingStockDaysOfCover", 0)
                planned_opening = math.ceil(
                    float(
                        opening_daily_rate[
                            (warehouse["warehouseId"], variant["sku"])
                        ]
                        * Decimal(cover_days)
                    )
                )
                opening = max(configured_floor, planned_opening) + stable_integer(
                    master_seed,
                    "opening-stock",
                    warehouse["warehouseId"],
                    variant["sku"],
                    modulo=max(1, warehouse["replenishmentPackSize"]),
                )
            inventory[(warehouse["warehouseId"], variant["sku"])] = opening
            if opening:
                schedule_expiry(
                    _add_batch(
                        batches_by_inventory_key,
                        batch_by_key,
                        batch_key=(
                            f"opening:{warehouse['warehouseId']}:{variant['sku']}"
                        ),
                        source_type="opening-balance",
                        source_reference="",
                        warehouse_id=warehouse["warehouseId"],
                        variant=variant,
                        receipt_day=start,
                        quantity=opening,
                    )
                )

    opening_inventory = dict(inventory)
    receipts_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    receipt_events = row_stream("simulation-receipt-events")
    cycle = inventory_policy["replenishmentCycleDays"]
    lead = inventory_policy["supplierLeadTimeDays"]
    jitter = inventory_policy["supplierLeadTimeJitterDays"]
    receipt_cycle_by_sku: dict[tuple[str, str], int] = defaultdict(int)
    realized_demand_by_day: dict[
        tuple[str, str],
        dict[date, Decimal],
    ] = defaultdict(lambda: defaultdict(lambda: Decimal("0")))
    available_to_sell_by_day: dict[
        tuple[str, str],
        dict[date, bool],
    ] = defaultdict(dict)

    line_events = row_stream("simulation-order-lines")
    order_headers = row_stream("simulation-orders")
    demand_truth = row_stream("simulation-demand-truth")
    inventory_observations = row_stream("simulation-inventory-observations")
    committed_inventory: dict[tuple[str, str], int] = defaultdict(int)
    damaged_inventory: dict[tuple[str, str], int] = defaultdict(int)
    quality_control_inventory: dict[tuple[str, str], int] = defaultdict(int)
    fulfillment_releases_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    quality_releases_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    waste_disposals_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    transfer_events = row_stream("simulation-transfer-events")
    transfer_receipts_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
    inventory_loss_events = row_stream("simulation-inventory-loss-events")
    waste_events = row_stream("simulation-waste-events")
    allocation_requests = row_stream("simulation-allocation-requests")
    supply_pools = row_stream("simulation-supply-pools")
    weather_actual = {
        market_id: row_stream(f"simulation-weather-actual-{market_id}")
        for market_id in markets
    }
    weather_forecasts = {
        market_id: row_stream(f"simulation-weather-forecasts-{market_id}")
        for market_id in markets
    }
    macro_rows = {
        market_id: row_stream(f"simulation-macro-{market_id}")
        for market_id in markets
    }
    competitor_prices = {
        market_id: row_stream(f"simulation-competitor-prices-{market_id}")
        for market_id in markets
    }
    competitor_matches = {
        market_id: row_stream(f"simulation-competitor-matches-{market_id}")
        for market_id in markets
    }
    competitor_match_keys: dict[str, set[str]] = {
        market_id: set()
        for market_id in markets
    }
    pandemic_signals = {
        market_id: row_stream(f"simulation-pandemic-signals-{market_id}")
        for market_id in markets
    }
    forecast_horizon = supply_policy["weatherForecastHorizonDays"]

    for day in _days(start, end):
        daily_lines: list[dict[str, Any]] = []
        for release in fulfillment_releases_by_date.pop(day, []):
            key = (release["warehouseId"], release["sku"])
            quantity = min(
                release["quantity"],
                committed_inventory[key],
                inventory[key],
            )
            committed_inventory[key] -= quantity
            inventory[key] -= quantity
            if quantity:
                _deplete_batches(
                    batches_by_inventory_key,
                    key,
                    quantity,
                    on_exhausted=finalize_batch,
                )
        for release in quality_releases_by_date.pop(day, []):
            key = (release["warehouseId"], release["sku"])
            quality_control_inventory[key] = max(
                0,
                quality_control_inventory[key] - release["quantity"],
            )
        for disposal in waste_disposals_by_date.pop(day, []):
            key = (disposal["warehouseId"], disposal["sku"])
            quantity = min(
                disposal["quantity"],
                damaged_inventory[key],
                inventory[key],
            )
            if not quantity:
                continue
            damaged_inventory[key] -= quantity
            inventory[key] -= quantity
            consumed_batches = _deplete_batches(
                batches_by_inventory_key,
                key,
                quantity,
                on_exhausted=finalize_batch,
            )
            waste_events.append(
                {
                    **disposal,
                    "batchKey": consumed_batches[0]["batchKey"],
                    "quantity": quantity,
                }
            )

        # Sell-through and transfers consume the earliest-expiring lots first.
        # Anything still free after its sell-by date is posted as expiry waste.
        for batch in sorted(
            expiry_batches_by_date.pop(day, []),
            key=lambda row: row["batchKey"],
        ):
            if batch["quantityRemainingAtExtract"] <= 0:
                continue
            key = (batch["warehouseId"], batch["sku"])
            free_inventory = max(
                0,
                inventory[key]
                - committed_inventory[key]
                - damaged_inventory[key]
                - quality_control_inventory[key],
            )
            quantity = min(
                free_inventory,
                batch["quantityRemainingAtExtract"],
            )
            if not quantity:
                expiry_batches_by_date[day + timedelta(days=1)].append(batch)
                continue
            _deplete_batches(
                batches_by_inventory_key,
                key,
                quantity,
                batch_key=batch["batchKey"],
                on_exhausted=finalize_batch,
            )
            inventory[key] -= quantity
            waste_events.append(
                {
                    "wasteEventKey": (
                        f"expiry:{batch['batchKey']}:{day.isoformat()}"
                    ),
                    "receiptKey": batch["sourceReference"],
                    "batchKey": batch["batchKey"],
                    "warehouseId": batch["warehouseId"],
                    "marketId": warehouses[batch["warehouseId"]]["marketId"],
                    "sku": batch["sku"],
                    "productCode": batch["productCode"],
                    "variantCode": batch["variantCode"],
                    "eventDate": day.isoformat(),
                    "quantity": quantity,
                    "reason": "expired",
                }
            )
            if batch["quantityRemainingAtExtract"] > 0:
                expiry_batches_by_date[day + timedelta(days=1)].append(batch)

        losses: dict[tuple[str, str], tuple[Decimal, list[str]]] = {}
        for warehouse in warehouses.values():
            for variant in variants_by_market[warehouse["marketId"]]:
                event_loss = _event_effect(
                    config,
                    day,
                    warehouse["marketId"],
                    department_id=variant["_departmentId"],
                    category_id=variant["_categoryId"],
                )
                pandemic_loss = _pandemic_effect(
                    config,
                    day,
                    warehouse["marketId"],
                    department_id=variant["_departmentId"],
                    category_id=variant["_categoryId"],
                    catalog_family=variant["_catalogFamily"],
                )
                starts_today = any(
                    row["startDate"] == day.isoformat()
                    for row in config["events"]
                    if row["eventId"] in event_loss["eventIds"]
                ) or any(
                    phase["startDate"] == day.isoformat()
                    for pandemic in config["pandemics"]
                    for phase in pandemic["phases"]
                    if phase["phaseId"] in pandemic_loss["phaseIds"]
                )
                loss_rate = max(
                    event_loss["inventoryLoss"],
                    pandemic_loss["inventoryLoss"],
                )
                if starts_today and loss_rate > 0:
                    losses[(warehouse["warehouseId"], variant["sku"])] = (
                        loss_rate,
                        event_loss["eventIds"] + pandemic_loss["phaseIds"],
                    )
        for key, (loss_rate, cause_ids) in losses.items():
            prior = inventory[key]
            exposed = max(
                0,
                prior
                - committed_inventory[key]
                - damaged_inventory[key]
                - quality_control_inventory[key],
            )
            lost = min(exposed, round(exposed * float(loss_rate)))
            if lost:
                inventory[key] -= lost
                _deplete_batches(
                    batches_by_inventory_key,
                    key,
                    lost,
                    on_exhausted=finalize_batch,
                )
                inventory_loss_events.append(
                    {
                        "warehouseId": key[0],
                        "sku": key[1],
                        "marketId": warehouses[key[0]]["marketId"],
                        "productCode": next(
                            row["_productCode"]
                            for row in variants_by_market[
                                warehouses[key[0]]["marketId"]
                            ]
                            if row["sku"] == key[1]
                        ),
                        "variantCode": next(
                            row["_variantCode"]
                            for row in variants_by_market[
                                warehouses[key[0]]["marketId"]
                            ]
                            if row["sku"] == key[1]
                        ),
                        "eventDate": day.isoformat(),
                        "lostQuantity": lost,
                        "inventoryLossPct": str(loss_rate),
                        "causeIds": "|".join(sorted(cause_ids)),
                    }
                )
        for receipt in receipts_by_date.pop(day, []):
            key = (receipt["warehouseId"], receipt["sku"])
            inventory[key] += receipt["quantity"]
            schedule_expiry(
                _add_batch(
                    batches_by_inventory_key,
                    batch_by_key,
                    batch_key=f"batch:{receipt['receiptKey']}",
                    source_type="purchase-receipt",
                    source_reference=receipt["receiptKey"],
                    warehouse_id=receipt["warehouseId"],
                    variant=variants_by_inventory_key[key],
                    receipt_day=day,
                    quantity=receipt["quantity"],
                )
            )
            damaged_quantity = 0
            if (
                operations["features"]["warehouseOperations"]
                and receipt["quantity"] > 0
                and _fraction(master_seed, "receipt-waste", receipt["receiptKey"])
                < supply_policy["wasteRate"]
            ):
                damaged_quantity = 1
                damaged_inventory[key] += damaged_quantity
                disposal_day = day + timedelta(
                    days=1
                    + stable_integer(
                        master_seed,
                        "waste-disposal-lag",
                        receipt["receiptKey"],
                        modulo=3,
                    )
                )
                waste_disposals_by_date[disposal_day].append(
                    {
                        "wasteEventKey": f"waste:{receipt['receiptKey']}",
                        "receiptKey": receipt["receiptKey"],
                        "warehouseId": receipt["warehouseId"],
                        "marketId": receipt["marketId"],
                        "sku": receipt["sku"],
                        "productCode": receipt["productCode"],
                        "variantCode": receipt["variantCode"],
                        "eventDate": disposal_day.isoformat(),
                        "quantity": damaged_quantity,
                        "reason": "damage-in-handling",
                    }
                )
            if (
                operations["features"]["warehouseOperations"]
                and receipt["quantity"] > damaged_quantity
            ):
                quality_quantity = min(
                    receipt["quantity"] - damaged_quantity,
                    1
                    + stable_integer(
                        master_seed,
                        "receipt-quality-control",
                        receipt["receiptKey"],
                        modulo=3,
                    ),
                )
                quality_control_inventory[key] += quality_quantity
                quality_releases_by_date[day + timedelta(days=1)].append(
                    {
                        "warehouseId": receipt["warehouseId"],
                        "sku": receipt["sku"],
                        "quantity": quality_quantity,
                    }
                )
        for transfer in transfer_receipts_by_date.pop(day, []):
            inventory[(transfer["toWarehouseId"], transfer["sku"])] += transfer[
                "receivedQuantity"
            ]
            destination_key = (transfer["toWarehouseId"], transfer["sku"])
            for index, source_batch in enumerate(
                transfer["_batchTransfers"],
                start=1,
            ):
                schedule_expiry(
                    _add_batch(
                        batches_by_inventory_key,
                        batch_by_key,
                        batch_key=(
                            f"transfer:{transfer['transferKey']}:{index:03d}:"
                            f"{source_batch['batchKey']}"
                        ),
                        source_type="transfer-receipt",
                        source_reference=transfer["transferKey"],
                        warehouse_id=transfer["toWarehouseId"],
                        variant=variants_by_inventory_key[destination_key],
                        receipt_day=day,
                        quantity=source_batch["quantity"],
                        manufacture_day=date.fromisoformat(
                            source_batch["manufactureDate"]
                        ),
                        expiry_day=(
                            date.fromisoformat(source_batch["expiryDate"])
                            if source_batch["expiryDate"]
                            else None
                        ),
                    ),
                    earliest=day + timedelta(days=1),
                )

        if (day - start).days % cycle == 0:
            for warehouse in sorted(
                warehouses.values(),
                key=lambda row: row["warehouseId"],
            ):
                market_id = warehouse["marketId"]
                for variant in variants_by_market[market_id]:
                    launch_day = date.fromisoformat(variant["_launchDate"])
                    discontinue_day = (
                        date.fromisoformat(variant["_discontinueDate"])
                        if variant["_discontinueDate"]
                        else None
                    )
                    if launch_day > day + timedelta(days=lead):
                        continue
                    if discontinue_day and discontinue_day < day:
                        continue
                    key = (warehouse["warehouseId"], variant["sku"])
                    history_days = min(28, (day - start).days)
                    observed_daily_rate = Decimal("0")
                    if history_days:
                        history_dates = [
                            day - timedelta(days=offset)
                            for offset in range(1, history_days + 1)
                        ]
                        observable_dates = [
                            history_day
                            for history_day in history_dates
                            if available_to_sell_by_day[key].get(
                                history_day,
                                False,
                            )
                        ]
                        # Calendar-day averages interpret a known stockout as
                        # zero demand and make the next purchase order smaller.
                        # Normalize by days on which this location could
                        # actually sell the SKU. Both sales and availability
                        # are ordinary source-observable retailer evidence.
                        rate_dates = observable_dates or history_dates
                        observed_daily_rate = (
                            sum(
                                (
                                    realized_demand_by_day[key].get(
                                        history_day,
                                        Decimal("0"),
                                    )
                                    for history_day in rate_dates
                                ),
                                Decimal("0"),
                            )
                            / Decimal(len(rate_dates))
                        )
                    daily_rate = observed_daily_rate * (
                        Decimal("1")
                        + Decimal(
                            str(
                                inventory_policy[
                                    "replenishmentDemandBufferPct"
                                ]
                            )
                        )
                    )
                    pending = sum(
                        receipt["quantity"]
                        for receipt_day, receipts in receipts_by_date.items()
                        if receipt_day > day
                        for receipt in receipts
                        if (
                            receipt["warehouseId"] == warehouse["warehouseId"]
                            and receipt["sku"] == variant["sku"]
                        )
                    )
                    inventory_position = (
                        inventory[key]
                        - committed_inventory[key]
                        - damaged_inventory[key]
                        + pending
                    )
                    target = math.ceil(
                        float(
                            daily_rate
                            * Decimal(lead + cycle + jitter + 2)
                            + Decimal(inventory_policy["safetyStockUnits"])
                        )
                    )
                    # A pack-level reorder point lets recently stocked-out SKUs
                    # recover even when their trailing realized-sales history is
                    # censored. The forecast itself still uses observed sales
                    # only; latent/configured demand never becomes a floor.
                    if inventory_position < warehouse["replenishmentPackSize"]:
                        target = max(
                            target,
                            warehouse["replenishmentPackSize"],
                        )
                    required = max(0, target - inventory_position)
                    if required == 0:
                        continue
                    pack = warehouse["replenishmentPackSize"]
                    ordered_quantity = max(
                        pack,
                        math.ceil(required / pack) * pack,
                    )
                    receipt_cycle_by_sku[key] += 1
                    cycle_index = receipt_cycle_by_sku[key]
                    expected = max(launch_day, day + timedelta(days=lead))
                    event_supply = _event_effect(
                        config,
                        expected,
                        market_id,
                        department_id=variant["_departmentId"],
                        category_id=variant["_categoryId"],
                    )
                    pandemic_supply = _pandemic_effect(
                        config,
                        expected,
                        market_id,
                        department_id=variant["_departmentId"],
                        category_id=variant["_categoryId"],
                        catalog_family=variant["_catalogFamily"],
                    )
                    lead_time_multiplier = (
                        event_supply["leadTime"] * pandemic_supply["leadTime"]
                    )
                    cost_multiplier = (
                        event_supply["cost"] * pandemic_supply["cost"]
                    )
                    inventory_loss = max(
                        event_supply["inventoryLoss"],
                        pandemic_supply["inventoryLoss"],
                    )
                    delayed = (
                        _fraction(
                            master_seed,
                            "supplier-delay",
                            warehouse["warehouseId"],
                            variant["sku"],
                            cycle_index,
                        )
                        < supply_policy["supplierDelayRate"]
                    )
                    delay_days = (
                        stable_integer(
                            master_seed,
                            "supplier-jitter",
                            warehouse["warehouseId"],
                            variant["sku"],
                            cycle_index,
                            modulo=jitter + 1,
                        )
                        if jitter
                        else 0
                    )
                    if delayed:
                        delay_days += max(1, jitter)
                    if lead_time_multiplier > Decimal("1"):
                        delay_days += max(
                            1,
                            round(
                                lead
                                * float(lead_time_multiplier - Decimal("1"))
                            ),
                        )
                    actual = expected + timedelta(days=delay_days)
                    fill_rate = Decimal(
                        str(
                            rng(
                                master_seed,
                                "supplier-fill-rate",
                                warehouse["warehouseId"],
                                variant["sku"],
                                cycle_index,
                            ).uniform(0.86, 1.0)
                        )
                    )
                    quantity = max(
                        0,
                        round(
                            ordered_quantity
                            * float(fill_rate)
                            * float(Decimal("1") - inventory_loss)
                        ),
                    )
                    receipt_key = (
                        f"{warehouse['warehouseId']}:{variant['sku']}:"
                        f"{expected.isoformat()}"
                    )
                    row = {
                        "receiptKey": receipt_key,
                        "marketId": market_id,
                        "warehouseId": warehouse["warehouseId"],
                        "sku": variant["sku"],
                        "productCode": variant["_productCode"],
                        "variantCode": variant["_variantCode"],
                        "categoryId": variant["_categoryId"],
                        "brand": variant["_brand"],
                        "brandCode": variant["_brandCode"],
                        "shelfLifeDays": (
                            variant["_shelfLifeDays"]
                            if variant["_shelfLifeDays"] is not None
                            else ""
                        ),
                        "costingMethod": variant["_costingMethod"],
                        "orderDate": day.isoformat(),
                        "expectedDate": expected.isoformat(),
                        "actualDate": actual.isoformat(),
                        "orderedQuantity": ordered_quantity,
                        "quantity": quantity,
                        "unitCost": (
                            _price_for_day(
                                variant["_baseCost"],
                                markets[market_id],
                                f"{variant['sku']}:cost",
                                expected,
                                start,
                                end,
                                inflation_anchor=launch_day,
                            )
                            * cost_multiplier
                        ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN),
                        "currencyCode": markets[market_id]["currencyCode"],
                        "delayed": actual > expected,
                        "status": "Received" if actual <= end else "In Transit",
                        "eventIds": "|".join(event_supply["eventIds"]),
                        "pandemicIds": "|".join(
                            pandemic_supply["pandemicIds"]
                        ),
                        "pandemicPhaseIds": "|".join(
                            pandemic_supply["phaseIds"]
                        ),
                        "leadTimeMultiplier": str(lead_time_multiplier),
                        "costMultiplier": str(cost_multiplier),
                        "inventoryLossPct": str(inventory_loss),
                    }
                    receipt_events.append(row)
                    receipts_by_date[actual].append(row)

        if (
            operations["features"]["transfers"]
            and (day - start).days
            and (day - start).days % supply_policy["transferCycleDays"] == 0
        ):
            for market_id in sorted(markets):
                market_warehouses = sorted(
                    [
                        row
                        for row in warehouses.values()
                        if row["marketId"] == market_id
                    ],
                    key=lambda row: row["warehouseId"],
                )
                if len(market_warehouses) < 2:
                    continue
                source, destination = market_warehouses[0], market_warehouses[1]
                for variant in variants_by_market[market_id]:
                    if (
                        _fraction(master_seed, "transfer", market_id, variant["sku"], day)
                        >= supply_policy["transferSkuRate"]
                    ):
                        continue
                    source_key = (source["warehouseId"], variant["sku"])
                    available = max(
                        0,
                        inventory[source_key]
                        - committed_inventory[source_key]
                        - damaged_inventory[source_key]
                        - quality_control_inventory[source_key]
                        - inventory_policy["safetyStockUnits"],
                    )
                    quantity = min(available, 2 + stable_integer(
                        master_seed,
                        "transfer-quantity",
                        market_id,
                        variant["sku"],
                        day,
                        modulo=5,
                    ))
                    if not quantity:
                        continue
                    inventory[source_key] -= quantity
                    batch_transfers = _deplete_batches(
                        batches_by_inventory_key,
                        source_key,
                        quantity,
                        on_exhausted=finalize_batch,
                    )
                    transit_days = 1 + stable_integer(
                        master_seed,
                        "transfer-transit",
                        market_id,
                        variant["sku"],
                        day,
                        modulo=3,
                    )
                    receipt_day = day + timedelta(days=transit_days)
                    received_quantity = quantity if receipt_day <= end else 0
                    transfer_events.append(
                        {
                            "transferKey": (
                                f"{source['warehouseId']}:{destination['warehouseId']}:"
                                f"{variant['sku']}:{day}"
                            ),
                            "marketId": market_id,
                            "sku": variant["sku"],
                            "productCode": variant["_productCode"],
                            "variantCode": variant["_variantCode"],
                            "fromWarehouseId": source["warehouseId"],
                            "toWarehouseId": destination["warehouseId"],
                            "requestDate": (day - timedelta(days=2)).isoformat(),
                            "orderDate": (day - timedelta(days=1)).isoformat(),
                            "shipmentDate": day.isoformat(),
                            "receiptDate": (
                                receipt_day.isoformat()
                                if receipt_day <= end
                                else ""
                            ),
                            "requestedQuantity": quantity,
                            "shippedQuantity": quantity,
                            "receivedQuantity": received_quantity,
                            "status": (
                                "Received" if receipt_day <= end else "In Transit"
                            ),
                            "_batchTransfers": batch_transfers,
                        }
                    )
                    if receipt_day <= end:
                        transfer_receipts_by_date[receipt_day].append(
                            transfer_events[-1]
                        )

        # Capture the daily selling exposure after receipts, losses and
        # transfers, immediately before demand is allocated. Replenishment on
        # later review dates can then distinguish a true zero-sale day from a
        # day censored by unavailable inventory without consulting `_truth/`.
        expired_history_day = day - timedelta(days=29)
        for key in variants_by_inventory_key:
            # Replenishment consults a trailing 28-day window only. Retaining
            # the entire horizon here previously consumed hundreds of MB on a
            # ten-year run without changing a single decision.
            available_to_sell_by_day[key].pop(
                expired_history_day,
                None,
            )
            realized_demand_by_day[key].pop(
                expired_history_day,
                None,
            )
            available_to_sell_by_day[key][day] = (
                inventory[key]
                - committed_inventory[key]
                - damaged_inventory[key]
                - quality_control_inventory[key]
                - inventory_policy["safetyStockUnits"]
                > 0
            )

        for market_id, market in sorted(markets.items()):
            temperature, precipitation = _temperature(master_seed, market, day)
            pandemic_market_effect = _pandemic_effect(
                config,
                day,
                market_id,
            )
            if pandemic_market_effect["phaseIds"]:
                pandemic_signals[market_id].append(
                    {
                        "marketKey": market_id,
                        "validDate": day.isoformat(),
                        "observedAt": _iso_at(day, 23, market["timezone"]),
                        "pandemicIds": "|".join(
                            pandemic_market_effect["pandemicIds"]
                        ),
                        "phaseIds": "|".join(
                            pandemic_market_effect["phaseIds"]
                        ),
                        "effectModes": "|".join(
                            pandemic_market_effect["effectModes"]
                        ),
                        "demandMultiplier": str(
                            pandemic_market_effect["demand"]
                        ),
                        "trafficMultiplier": str(
                            pandemic_market_effect["traffic"]
                        ),
                        "costMultiplier": str(pandemic_market_effect["cost"]),
                        "leadTimeMultiplier": str(
                            pandemic_market_effect["leadTime"]
                        ),
                        "inventoryLossPct": str(
                            pandemic_market_effect["inventoryLoss"]
                        ),
                    }
                )
            if market["signals"]["weather"]:
                weather_actual[market_id].append(
                    {
                        "marketKey": market_id,
                        "targetType": "market",
                        "targetId": market_id,
                        "observedAt": _iso_at(day, 23, market["timezone"]),
                        "validDate": day.isoformat(),
                        "temperatureC": str(temperature),
                        "precipitationMm": str(precipitation),
                        "condition": "rain" if precipitation >= Decimal("2") else "clear",
                    }
                )
                for horizon in range(1, forecast_horizon + 1):
                    valid_day = day + timedelta(days=horizon)
                    future_temperature, future_precipitation = _temperature(
                        master_seed,
                        market,
                        valid_day,
                    )
                    error = Decimal(
                        str(
                            rng(
                                master_seed,
                                "forecast-error",
                                market_id,
                                day,
                                horizon,
                            ).uniform(-0.8 * horizon, 0.8 * horizon)
                        )
                    )
                    precipitation_random = rng(
                        master_seed,
                        "forecast-rain-error",
                        market_id,
                        day,
                        horizon,
                    )
                    if future_precipitation == 0:
                        forecast_precipitation = (
                            Decimal(
                                str(
                                    precipitation_random.uniform(
                                        0.1,
                                        1.5 + 0.4 * horizon,
                                    )
                                )
                            )
                            if precipitation_random.random() < 0.08 * horizon
                            else Decimal("0")
                        )
                    else:
                        forecast_precipitation = max(
                            Decimal("0"),
                            future_precipitation
                            * Decimal(
                                str(
                                    precipitation_random.uniform(
                                        max(0.15, 1 - 0.16 * horizon),
                                        1 + 0.20 * horizon,
                                    )
                                )
                            ),
                        )
                    weather_forecasts[market_id].append(
                        {
                            "marketKey": market_id,
                            "targetType": "market",
                            "targetId": market_id,
                            "issuedAt": _iso_at(day, 6, market["timezone"]),
                            "validDate": valid_day.isoformat(),
                            "horizonDays": horizon,
                            "temperatureC": str(
                                (future_temperature + error).quantize(Decimal("0.1"))
                            ),
                            "precipitationMm": str(
                                forecast_precipitation.quantize(Decimal("0.1"))
                            ),
                            "provider": "synthetic-weather-service",
                        }
                    )
            if market["signals"]["macro"]:
                macro_rows[market_id].append(
                    {
                        "marketKey": market_id,
                        "targetType": "market",
                        "targetId": market_id,
                        "observedAt": _iso_at(day, 18, market["timezone"]),
                        "validDate": day.isoformat(),
                        "indexName": "consumer-demand-index",
                        "indexValue": str(
                            (
                                Decimal("100")
                                * Decimal(
                                    str(
                                        1.02
                                        ** (
                                            (day - start).days
                                            / 365.2425
                                        )
                                    )
                                )
                                * pandemic_market_effect["demand"]
                                * pandemic_market_effect["traffic"]
                            ).quantize(Decimal("0.001"))
                        ),
                    }
                )
            if market["signals"]["competitor"] and (day - start).days % 7 == 0:
                market_stores = [
                    row for row in stores.values() if row["marketId"] == market_id
                ]
                active_competitor_variants = [
                    variant
                    for variant in variants_by_market[market_id]
                    if date.fromisoformat(variant["_launchDate"]) <= day
                    and (
                        not variant["_discontinueDate"]
                        or date.fromisoformat(variant["_discontinueDate"]) >= day
                    )
                ]
                for variant in active_competitor_variants:
                    match_key = f"match:{market_id}:{variant['sku']}"
                    factor = Decimal(
                        str(
                            rng(
                                master_seed,
                                "competitor",
                                market_id,
                                variant["sku"],
                                day,
                            ).uniform(0.90, 1.10)
                        )
                    )
                    competitor_sku = f"CMP-{stable_integer(match_key, modulo=99_999_999):08d}"
                    competitor_available = (
                        _fraction(
                            master_seed,
                            "competitor-availability",
                            market_id,
                            variant["sku"],
                            day,
                        )
                        >= 0.08
                    )
                    competitor_prices[market_id].append(
                        {
                            "marketKey": market_id,
                            "targetType": "store",
                            "targetId": market_stores[0]["storeId"],
                            "observedAt": _iso_at(day, 8, market["timezone"]),
                            "validDate": day.isoformat(),
                            "competitorId": f"competitor-{market_id}",
                            "competitorSku": competitor_sku,
                            "competitorProductTitle": f"Comparable {variant['_productTitle']}",
                            "price": _money(
                                _snap_price_ending(
                                    _inflated_base_price(
                                        variant["_basePrice"],
                                        market,
                                        day,
                                        date.fromisoformat(
                                            variant["_launchDate"]
                                        ),
                                    )
                                    * factor,
                                    market,
                                )
                            ),
                            "currencyCode": market["currencyCode"],
                            "available": str(competitor_available).lower(),
                            "promotionText": "weekly-price-check" if factor < 1 else "",
                        }
                    )
                    if match_key not in competitor_match_keys[market_id]:
                        competitor_match_keys[market_id].add(match_key)
                        competitor_matches[market_id].append(
                            {
                                "matchKey": match_key,
                                "marketKey": market_id,
                                "competitorId": f"competitor-{market_id}",
                                "competitorSku": competitor_sku,
                                "ourSku": variant["sku"],
                                "matchMethod": "synthetic-attribute-match",
                                "matchConfidence": str(
                                    Decimal("0.82")
                                    + Decimal(
                                        stable_integer(match_key, modulo=1700)
                                    )
                                    / Decimal("10000")
                                ),
                                "effectiveFrom": start.isoformat(),
                                "effectiveTo": end.isoformat(),
                            }
                        )

            market_stores = sorted(
                [row for row in stores.values() if row["marketId"] == market_id],
                key=lambda row: row["storeId"],
            )
            holiday_rows = holiday_by_market_and_date[market_id].get(
                day.isoformat(),
                [],
            )
            holiday_names = [holiday["name"] for holiday in holiday_rows]
            sale_season_ids = _active_sale_seasons(market, day)
            active_promotions = _active(config["promotions"], day, market_id)
            recent_promotions = _recent_promotions(config, market, day)
            midpoint = (
                Decimal(str(market["localePack"]["climate"]["summerC"]))
                + Decimal(str(market["localePack"]["climate"]["winterC"]))
            ) / 2
            for store in market_stores:
                reference_variants = store_variants[store["storeId"]]
                variants = [
                    variant
                    for variant in reference_variants
                    if day >= date.fromisoformat(variant["_launchDate"])
                    and (
                        not variant["_discontinueDate"]
                        or day <= date.fromisoformat(variant["_discontinueDate"])
                    )
                ]
                if not variants:
                    continue
                portfolio_weight = annual_portfolio_weight[
                    (store["storeId"], day.year)
                ]
                variant_channels = [
                    (variant, channel_id, channel_share)
                    for variant in variants
                    for channel_id, channel_share in _channel_distribution(
                        master_seed,
                        store,
                        variant,
                        channel_types,
                        market,
                        day,
                        start,
                        end,
                    )
                ]
                for variant, channel_id, channel_share in variant_channels:
                    launch_day = date.fromisoformat(variant["_launchDate"])
                    event_key = (
                        f"{store['storeId']}:{day}:{variant['sku']}:{channel_id}"
                    )
                    segment = _segment_for_event(config, master_seed, event_key)
                    event_effect = _event_effect(
                        config,
                        day,
                        market_id,
                        store_id=store["storeId"],
                        department_id=variant["_departmentId"],
                        category_id=variant["_categoryId"],
                        channel_id=channel_id,
                    )
                    pandemic_effect = _pandemic_effect(
                        config,
                        day,
                        market_id,
                        department_id=variant["_departmentId"],
                        category_id=variant["_categoryId"],
                        catalog_family=variant["_catalogFamily"],
                        channel_type=channel_types[channel_id],
                    )
                    successor_launch_text = variant.get(
                        "_successorLaunchDate",
                        "",
                    )
                    pricing_day = (
                        min(day, date.fromisoformat(successor_launch_text))
                        if successor_launch_text
                        else day
                    )
                    original_price = _price_for_day(
                        variant["_basePrice"],
                        market,
                        variant["sku"],
                        pricing_day,
                        start,
                        end,
                        inflation_anchor=launch_day,
                    )
                    unit_price = original_price
                    applied_promotions: list[str] = []
                    lifecycle_effect = lifecycle_adjustment(
                        variant,
                        day,
                        market["demand"]["newProductRampDays"],
                    )
                    promotion_candidates: list[dict[str, Any]] = []
                    if lifecycle_effect["offerId"]:
                        promotion_candidates.append(
                            {
                                "promotionId": lifecycle_effect["offerId"],
                                "promotionType": lifecycle_effect["offerType"],
                                "discountPct": lifecycle_effect[
                                    "offerDiscountPct"
                                ],
                                "demandMultiplier": lifecycle_effect[
                                    "offerDemandFactor"
                                ],
                            }
                        )
                    for promotion in active_promotions:
                        if (
                            market["signals"]["promotions"]
                            and _promotion_applies(
                                promotion,
                                store,
                                variant,
                                segment["segmentId"],
                                channel_id,
                            )
                        ):
                            promotion_candidates.append(
                                {
                                    "promotionId": promotion["promotionId"],
                                    "promotionType": promotion.get(
                                        "promotionType",
                                        "campaign",
                                    ),
                                    "discountPct": Decimal(
                                        str(promotion["discountPct"])
                                    ),
                                    "demandMultiplier": Decimal(
                                        str(promotion["demandMultiplier"])
                                    ),
                                }
                            )
                    configured_promotion_lift = Decimal("1")
                    effective_promotion_lift = Decimal("1")
                    effective_promotion_discount = Decimal("0")
                    if promotion_candidates:
                        selected_promotion = max(
                            promotion_candidates,
                            key=lambda promotion: (
                                promotion["discountPct"],
                                promotion["promotionId"],
                            ),
                        )
                        applied_promotions = [
                            selected_promotion["promotionId"]
                        ]
                        configured_promotion_lift = selected_promotion[
                            "demandMultiplier"
                        ]
                        unit_price = _promotional_price(
                            original_price,
                            variant,
                            market,
                            day,
                            start,
                            end,
                            selected_promotion["discountPct"],
                            selected_promotion["promotionId"],
                            selected_promotion["promotionType"],
                            (
                                event_effect["cost"]
                                * pandemic_effect["cost"]
                            ),
                        )
                        effective_promotion_discount = max(
                            Decimal("0"),
                            (original_price - unit_price) / original_price,
                        )
                        requested_discount = selected_promotion["discountPct"]
                        realization = (
                            min(
                                Decimal("1"),
                                effective_promotion_discount
                                / requested_discount,
                            )
                            if requested_discount > 0
                            else Decimal("1")
                        )
                        effective_promotion_lift = Decimal("1") + (
                            configured_promotion_lift - Decimal("1")
                        ) * realization
                    promotion_payback_factor = Decimal("1")
                    for promotion in recent_promotions:
                        if not _promotion_applies(
                            promotion,
                            store,
                            variant,
                            segment["segmentId"],
                            channel_id,
                        ):
                            continue
                        days_after = (
                            day - date.fromisoformat(promotion["endDate"])
                        ).days
                        remaining_share = Decimal(8 - days_after) / Decimal(7)
                        lift = max(
                            Decimal("0"),
                            Decimal(str(promotion["demandMultiplier"]))
                            - Decimal("1"),
                        )
                        payback = min(
                            Decimal("0.30"),
                            lift * Decimal("0.18"),
                        ) * remaining_share
                        promotion_payback_factor *= Decimal("1") - payback
                    day_factors = [
                        Decimal(str(value))
                        for value in market["demand"]["dayOfWeekFactors"]
                    ]
                    day_of_week_factor = (
                        day_factors[day.weekday()]
                        * Decimal(7)
                        / sum(day_factors, Decimal("0"))
                    )
                    trend_factor = Decimal(
                        str(
                            (
                                1 + market["demand"]["annualGrowthRate"]
                            )
                            ** ((day - start).days / 365.2425)
                        )
                    )
                    peak = variant["_seasonalityPeakMonth"]
                    strength = Decimal(str(variant["_seasonalityStrength"]))
                    seasonal_factor = _seasonality_factor(
                        peak,
                        strength,
                        day,
                    )
                    holiday_factor = Decimal("1")
                    if holiday_names and market["signals"]["holidays"]:
                        holiday_factor = _holiday_demand_factor(
                            holiday_rows,
                            country_code=market["countryCode"],
                            channel_type=channel_types[channel_id],
                        )
                    sale_season_factor = (
                        Decimal("1.08") if sale_season_ids else Decimal("1")
                    )
                    event_factor = (
                        event_effect["demand"] * event_effect["traffic"]
                        if market["signals"]["localEvents"]
                        else Decimal("1")
                    )
                    pandemic_factor = (
                        pandemic_effect["demand"]
                        * pandemic_effect["traffic"]
                    )
                    weather_factor = Decimal("1")
                    if market["signals"]["weather"]:
                        temperature_gap = max(
                            Decimal("-1"),
                            min(
                                Decimal("1"),
                                (temperature - midpoint) / Decimal("15"),
                            ),
                        )
                        if variant["_catalogFamily"] == "apparel-outerwear":
                            weather_factor -= temperature_gap * Decimal("0.12")
                        elif variant["_catalogFamily"] == "apparel-tops":
                            weather_factor += temperature_gap * Decimal("0.06")
                        if precipitation > Decimal("2"):
                            rain_effect = min(
                                Decimal("0.15"),
                                precipitation / Decimal("100"),
                            )
                            weather_factor += (
                                rain_effect * Decimal("0.35")
                                if channel_types[channel_id] == "online"
                                else -rain_effect
                            )
                    macro_factor = (
                        Decimal("1")
                        + Decimal((day - start).days) / Decimal("10000")
                        if market["signals"]["macro"]
                        else Decimal("1")
                    )
                    competitor_factor = Decimal("1")
                    if market["signals"]["competitor"]:
                        observation_day = start + timedelta(
                            days=((day - start).days // 7) * 7
                        )
                        competitor_price_ratio = Decimal(
                            str(
                                rng(
                                    master_seed,
                                    "competitor",
                                    market_id,
                                    variant["sku"],
                                    observation_day,
                                ).uniform(0.90, 1.10)
                            )
                        )
                        competitor_available = (
                            _fraction(
                                master_seed,
                                "competitor-availability",
                                market_id,
                                variant["sku"],
                                observation_day,
                            )
                            >= 0.08
                        )
                        if competitor_available:
                            relative_gap = (
                                _inflated_base_price(
                                    variant["_basePrice"],
                                    market,
                                    observation_day,
                                    launch_day,
                                )
                                * competitor_price_ratio
                                / unit_price
                            ) - Decimal("1")
                            competitor_factor = max(
                                Decimal("0.90"),
                                min(
                                    Decimal("1.10"),
                                    Decimal("1")
                                    + relative_gap * Decimal("0.50"),
                                ),
                            )
                    inflated_reference_price = _inflated_base_price(
                        variant["_basePrice"],
                        market,
                        day,
                        launch_day,
                    )
                    price_ratio = max(
                        Decimal("0.01"),
                        unit_price / inflated_reference_price,
                    )
                    price_factor = Decimal(
                        str(
                            math.exp(
                                float(variant["_elasticity"])
                                * math.log(float(price_ratio))
                            )
                        )
                    )
                    regular_price_ratio = max(
                        Decimal("0.01"),
                        original_price / inflated_reference_price,
                    )
                    regular_price_factor = Decimal(
                        str(
                            math.exp(
                                float(variant["_elasticity"])
                                * math.log(float(regular_price_ratio))
                            )
                        )
                    )
                    promotion_elasticity_factor = (
                        price_factor / regular_price_factor
                        if applied_promotions
                        else Decimal("1")
                    )
                    promotion_factor = (
                        effective_promotion_lift
                        / promotion_elasticity_factor
                        if applied_promotions
                        else Decimal("1")
                    )
                    new_product_factor = lifecycle_effect["launchFactor"]
                    predecessor_factor = lifecycle_effect["predecessorFactor"]
                    substitution_factor = lifecycle_effect["substitutionFactor"]
                    intermittency_rate = market["demand"]["intermittencyRate"]
                    week_start = day - timedelta(days=day.weekday())
                    intermittent = (
                        _fraction(
                            master_seed,
                            "intermittency-cluster",
                            store["storeId"],
                            variant["sku"],
                            week_start,
                        )
                        < intermittency_rate * 0.65
                        or _fraction(master_seed, "intermittency-daily", event_key)
                        < intermittency_rate * 0.35
                    )
                    week_noise = rng(
                        master_seed,
                        "demand-week-noise",
                        store["storeId"],
                        variant["sku"],
                        week_start,
                    ).gauss(0, market["demand"]["noise"])
                    day_noise = rng(
                        master_seed,
                        "demand-noise",
                        event_key,
                    ).gauss(0, market["demand"]["noise"])
                    random_noise = max(
                        0.05,
                        1 + 0.60 * week_noise + 0.40 * day_noise,
                    )
                    baseline = (
                        Decimal(str(market["demand"]["demandLevelScalar"]))
                        * Decimal(str(store["demandScale"]))
                        * Decimal(str(market["demand"]["startingDailyOrders"]))
                        * Decimal(str(market["demand"]["averageLinesPerOrder"]))
                        * _portfolio_weight(variant)
                        / portfolio_weight
                        * channel_share
                        * _expected_units_per_line(variant)
                    )
                    total_factor = (
                        day_of_week_factor
                        * trend_factor
                        * seasonal_factor
                        * holiday_factor
                        * sale_season_factor
                        * promotion_factor
                        * promotion_payback_factor
                        * event_factor
                        * pandemic_factor
                        * weather_factor
                        * macro_factor
                        * competitor_factor
                        * price_factor
                        * new_product_factor
                        * predecessor_factor
                        * substitution_factor
                        * Decimal(str(segment["demandMultiplier"]))
                        * Decimal(str(random_noise))
                    )
                    expected = max(
                        Decimal("0"),
                        baseline * total_factor,
                    )
                    latent_units = (
                        0
                        if intermittent
                        else _poisson(
                            float(expected),
                            master_seed,
                            "latent-demand",
                            event_key,
                        )
                    )
                    allocations = _allocate_inventory(
                        config,
                        master_seed,
                        store,
                        variant["sku"],
                        latent_units,
                        event_key,
                        inventory,
                        committed_inventory,
                        damaged_inventory,
                        quality_control_inventory,
                    )
                    realized_units = sum(row["quantity"] for row in allocations)
                    lost_units = latent_units - realized_units
                    for allocation in allocations:
                        realized_demand_by_day[
                            (allocation["warehouseId"], variant["sku"])
                        ][day] += Decimal(allocation["quantity"])
                    allocation_requests.append(
                        {
                            "requestKey": event_key,
                            "marketKey": market_id,
                            "storeKey": store["storeId"],
                            "channelId": channel_id,
                            "requestDate": day.isoformat(),
                            "sku": variant["sku"],
                            "requestedQuantity": latent_units,
                            "allocatedQuantity": realized_units,
                            "unallocatedQuantity": lost_units,
                            "warehousePriority": "|".join(store["warehousePriority"]),
                            "status": "allocated" if lost_units == 0 else "partial",
                        }
                    )
                    demand_truth.append(
                        {
                            "marketKey": market_id,
                            "storeKey": store["storeId"],
                            "channelId": channel_id,
                            "date": day.isoformat(),
                            "sku": variant["sku"],
                            "departmentId": variant["_departmentId"],
                            "categoryId": variant["_categoryId"],
                            "baselineDemand": str(baseline.quantize(Decimal("0.000001"))),
                            "expectedDemand": str(expected.quantize(Decimal("0.000001"))),
                            "latentDemandUnits": latent_units,
                            "realizedSalesUnits": realized_units,
                            "lostSalesUnits": lost_units,
                            "intermittentZero": str(intermittent).lower(),
                            "dayOfWeekFactor": str(day_of_week_factor),
                            "trendFactor": str(trend_factor.quantize(Decimal("0.000001"))),
                            "seasonalityFactor": str(
                                seasonal_factor.quantize(Decimal("0.000001"))
                            ),
                            "holidayNames": "|".join(holiday_names),
                            "holidayFactor": str(holiday_factor),
                            "saleSeasonIds": "|".join(sale_season_ids),
                            "saleSeasonFactor": str(sale_season_factor),
                            "promotionIds": "|".join(applied_promotions),
                            "configuredPromotionLift": str(
                                configured_promotion_lift
                            ),
                            "effectivePromotionLift": str(
                                effective_promotion_lift
                            ),
                            "effectivePromotionDiscountPct": str(
                                effective_promotion_discount
                            ),
                            "promotionElasticityFactor": str(
                                promotion_elasticity_factor
                            ),
                            "promotionFactor": str(promotion_factor),
                            "promotionPaybackFactor": str(
                                promotion_payback_factor
                            ),
                            "eventIds": "|".join(event_effect["eventIds"]),
                            "eventFactor": str(event_factor),
                            "pandemicIds": "|".join(
                                pandemic_effect["pandemicIds"]
                            ),
                            "pandemicPhaseIds": "|".join(
                                pandemic_effect["phaseIds"]
                            ),
                            "pandemicDemandFactor": str(
                                pandemic_effect["demand"]
                            ),
                            "pandemicTrafficFactor": str(
                                pandemic_effect["traffic"]
                            ),
                            "pandemicFactor": str(pandemic_factor),
                            "weatherFactor": str(
                                weather_factor.quantize(Decimal("0.000001"))
                            ),
                            "macroFactor": str(
                                macro_factor.quantize(Decimal("0.000001"))
                            ),
                            "competitorFactor": str(competitor_factor),
                            "priceFactor": str(price_factor.quantize(Decimal("0.000001"))),
                            "newProductFactor": str(new_product_factor),
                            "launchProfile": lifecycle_effect["launchProfile"],
                            "predecessorFactor": str(predecessor_factor),
                            "substitutionFactor": str(substitution_factor),
                            "lifecycleOfferType": lifecycle_effect["offerType"],
                            "lifecycleDiscountPct": str(
                                lifecycle_effect["offerDiscountPct"]
                            ),
                            "segmentFactor": str(segment["demandMultiplier"]),
                            "noiseFactor": str(
                                Decimal(str(random_noise)).quantize(Decimal("0.000001"))
                            ),
                            "totalFactor": str(total_factor.quantize(Decimal("0.000001"))),
                        }
                    )
                    if not realized_units:
                        continue
                    rate = _tax_rate_for_line(
                        market,
                        variant["_taxCategory"],
                        unit_price,
                        day,
                    )
                    purchase_quantities = _purchase_quantities(
                        master_seed,
                        event_key,
                        variant,
                        realized_units,
                    )
                    purchase_allocations = _split_allocations(
                        allocations,
                        purchase_quantities,
                    )
                    for purchase_index, (
                        purchase_quantity,
                        line_allocations,
                    ) in enumerate(
                        zip(
                            purchase_quantities,
                            purchase_allocations,
                            strict=True,
                        ),
                        start=1,
                    ):
                        net, tax, gross = _tax_amounts(
                            unit_price,
                            purchase_quantity,
                            rate,
                            market["localePack"]["tax"]["basis"],
                        )
                        line_event_key = (
                            f"{event_key}:purchase:{purchase_index:05d}"
                        )
                        daily_lines.append(
                            {
                                "eventKey": line_event_key,
                                "marketId": market_id,
                                "storeId": store["storeId"],
                                "day": day,
                                "createdAt": _iso_at(
                                    day,
                                    9
                                    + stable_integer(
                                        line_event_key,
                                        "hour",
                                        modulo=11,
                                    ),
                                    market["timezone"],
                                    stable_integer(
                                        line_event_key,
                                        "minute",
                                        modulo=60,
                                    ),
                                    stable_integer(
                                        line_event_key,
                                        "second",
                                        modulo=60,
                                    ),
                                ),
                                "sku": variant["sku"],
                                "variantId": variant["id"],
                                "inventoryItemId": variant["inventoryItemId"],
                                "departmentId": variant["_departmentId"],
                                "categoryId": variant["_categoryId"],
                                "productCode": variant["_productCode"],
                                "productTitle": variant["_productTitle"],
                                "brand": variant["_brand"],
                                "variantCode": variant["_variantCode"],
                                "variantTitle": variant["title"],
                                "barcode": variant["barcode"],
                                "quantity": purchase_quantity,
                                "originalUnitPrice": original_price,
                                "unitPrice": unit_price,
                                "promotionIds": applied_promotions,
                                "net": net,
                                "tax": tax,
                                "gross": gross,
                                "taxRate": rate,
                                "currencyCode": market["currencyCode"],
                                "taxesIncluded": (
                                    market["localePack"]["tax"]["basis"]
                                    == "inclusive"
                                ),
                                "allocations": line_allocations,
                                "customerSegmentId": segment["segmentId"],
                                "channelId": channel_id,
                                "returnProbability": variant[
                                    "_returnProbability"
                                ],
                            }
                        )

        daily_orders = _group_baskets(
            config,
            master_seed,
            daily_lines,
            customer_population,
        )
        source_name_start = len(order_headers)
        for source_offset, order in enumerate(
            sorted(
                daily_orders,
                key=lambda row: (row["createdAt"], row["orderKey"]),
            ),
            start=1,
        ):
            order["sourceOrderSequence"] = source_name_start + source_offset
            order["sourceOrderName"] = shopify_order_name(
                order["sourceOrderSequence"]
            )
        order_by_key = {row["orderKey"]: row for row in daily_orders}
        for line in daily_lines:
            order = order_by_key[line["orderKey"]]
            for allocation in line["allocations"]:
                created_at, delivered_at = fulfillment_timestamps(
                    config,
                    line["orderKey"],
                    allocation["warehouseId"],
                    order["createdAt"],
                )
                allocation["fulfillmentCreatedAt"] = created_at
                allocation["fulfillmentDeliveredAt"] = delivered_at
                release = {
                    "warehouseId": allocation["warehouseId"],
                    "sku": line["sku"],
                    "quantity": allocation["quantity"],
                }
                release_day = date.fromisoformat(created_at[:10])
                if release_day <= day:
                    key = (allocation["warehouseId"], line["sku"])
                    quantity = min(
                        allocation["quantity"],
                        committed_inventory[key],
                        inventory[key],
                    )
                    committed_inventory[key] -= quantity
                    inventory[key] -= quantity
                    if quantity:
                        _deplete_batches(
                            batches_by_inventory_key,
                            key,
                            quantity,
                            on_exhausted=finalize_batch,
                        )
                else:
                    fulfillment_releases_by_date[release_day].append(release)
        # Both streams use the same deterministic order-key ordering. Commerce
        # extensions can therefore merge them without a run-sized line lookup.
        daily_orders.sort(key=lambda row: row["orderKey"])
        daily_lines.sort(
            key=lambda row: (row["orderKey"], row["lineNumber"])
        )
        order_headers.extend(daily_orders)
        line_events.extend(daily_lines)

        if (day - start).days % inventory_policy["snapshotCadenceDays"] == 0 or day == end:
            for warehouse in sorted(warehouses.values(), key=lambda row: row["warehouseId"]):
                market_id = warehouse["marketId"]
                for variant in variants_by_market[market_id]:
                    key = (warehouse["warehouseId"], variant["sku"])
                    on_hand = inventory[key]
                    remaining = on_hand
                    committed = min(remaining, committed_inventory[key])
                    remaining -= committed
                    reserved = 0
                    remaining -= reserved
                    damaged = min(remaining, damaged_inventory[key])
                    remaining -= damaged
                    quality_control = min(
                        remaining,
                        quality_control_inventory[key],
                    )
                    remaining -= quality_control
                    safety_stock = min(
                        remaining,
                        inventory_policy["safetyStockUnits"],
                    )
                    available = remaining - safety_stock
                    incoming = sum(
                        row["quantity"]
                        for receipt_day, rows in receipts_by_date.items()
                        if day < receipt_day <= day + timedelta(days=forecast_horizon)
                        for row in rows
                        if row["warehouseId"] == warehouse["warehouseId"]
                        and row["sku"] == variant["sku"]
                    )
                    incoming += sum(
                        row["receivedQuantity"]
                        for receipt_day, rows in transfer_receipts_by_date.items()
                        if day < receipt_day <= day + timedelta(days=forecast_horizon)
                        for row in rows
                        if row["toWarehouseId"] == warehouse["warehouseId"]
                        and row["sku"] == variant["sku"]
                    )
                    observation = {
                        "marketKey": market_id,
                        "warehouseKey": warehouse["warehouseId"],
                        "observedAt": _iso_at(day, 23, markets[market_id]["timezone"]),
                        "sku": variant["sku"],
                        "onHand": on_hand,
                        "available": available,
                        "committed": committed,
                        "reserved": reserved,
                        "damaged": damaged,
                        "qualityControl": quality_control,
                        "safetyStock": safety_stock,
                        "incoming": incoming,
                        "blocked": damaged + quality_control,
                    }
                    inventory_observations.append(observation)
                    supply_pools.append(
                        {
                            "poolKey": (
                                f"{warehouse['warehouseId']}:{variant['sku']}:{day}"
                            ),
                            "marketKey": market_id,
                            "warehouseKey": warehouse["warehouseId"],
                            "snapshotDate": day.isoformat(),
                            "sku": variant["sku"],
                            "availableQuantity": available,
                            "incomingQuantity": incoming,
                            "safetyStockQuantity": safety_stock,
                        }
                    )

    for inventory_key, on_hand in inventory.items():
        batch_balance = sum(
            row["quantityRemainingAtExtract"]
            for row in batches_by_inventory_key[inventory_key]
        )
        if batch_balance != on_hand:
            raise RuntimeError(
                f"batch/on-hand reconciliation failed for {inventory_key}: "
                f"{batch_balance} != {on_hand}"
            )
    for batch in sorted(
        batch_by_key.values(),
        key=lambda row: (
            row["warehouseId"],
            row["sku"],
            row["receiptDate"],
            row["batchKey"],
        ),
    ):
        batch_balances.append(dict(batch))

    return {
        "orderLines": line_events,
        "orders": order_headers,
        "demandTruth": demand_truth,
        "storeAssortment": assortment_rows,
        "inventoryObservations": inventory_observations,
        "openingInventory": opening_inventory,
        "receiptEvents": receipt_events,
        "transferEvents": transfer_events,
        "inventoryLossEvents": inventory_loss_events,
        "wasteEvents": waste_events,
        "batchBalances": batch_balances,
        "allocationRequests": allocation_requests,
        "supplyPools": supply_pools,
        "weatherActual": weather_actual,
        "weatherForecasts": weather_forecasts,
        "macroRows": macro_rows,
        "competitorPrices": competitor_prices,
        "competitorMatches": competitor_matches,
        "pandemicSignals": pandemic_signals,
        "finalInventory": dict(inventory),
    }
