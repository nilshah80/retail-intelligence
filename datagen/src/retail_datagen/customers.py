"""Deterministic, multi-year customer population and acquisition model."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Iterable, Iterator
from zoneinfo import ZoneInfo

from .identity import stable_integer


def _fraction(*parts: Any) -> float:
    return stable_integer(*parts, modulo=1_000_000) / 1_000_000


class CustomerPopulation:
    """Allocate registered and guest orders from explicit market controls."""

    def __init__(
        self,
        config: dict[str, Any],
        start: date,
        end: date,
    ) -> None:
        self._seed = config["identity"]["masterSeed"]
        self._start = start
        self._end = end
        self._markets = {
            row["marketId"]: row
            for row in config["markets"]
        }
        self._segments = list(config["customerSegments"])
        total_share = sum(Decimal(str(row["share"])) for row in self._segments)
        self._shares = {
            row["segmentId"]: Decimal(str(row["share"])) / total_share
            for row in self._segments
        }
        self._daily_usage: dict[str, int] = {}
        self._usage_day: date | None = None
        self._active_cache: OrderedDict[
            tuple[str, str, int, int],
            bool,
        ] = OrderedDict()
        self._active_cache_limit = 50_000

    def _control(self, market_id: str) -> dict[str, Any]:
        return self._markets[market_id]["customerPopulation"]

    def _segment_count(
        self,
        total: int,
        segment_id: str,
    ) -> int:
        segment_index = next(
            index
            for index, row in enumerate(self._segments)
            if row["segmentId"] == segment_id
        )
        allocated_before = sum(
            int(
                (
                    Decimal(total) * self._shares[row["segmentId"]]
                ).to_integral_value(rounding=ROUND_FLOOR)
            )
            for row in self._segments[:segment_index]
        )
        if segment_index == len(self._segments) - 1:
            return total - allocated_before
        return int(
            (
                Decimal(total) * self._shares[segment_id]
            ).to_integral_value(rounding=ROUND_FLOOR)
        )

    def _population_total(self, market_id: str, day: date) -> int:
        control = self._control(market_id)
        elapsed_days = max(0, (day - self._start).days)
        acquired = int(
            Decimal(control["annualNewCustomers"])
            * Decimal(elapsed_days + 1)
            / Decimal("365.2425")
        )
        return control["openingRegisteredCustomers"] + acquired

    def _segment_population(
        self,
        market_id: str,
        segment_id: str,
        day: date,
    ) -> int:
        return max(
            1,
            self._segment_count(
                self._population_total(market_id, day),
                segment_id,
            ),
        )

    def _customer_key(
        self,
        market_id: str,
        segment_id: str,
        index: int,
    ) -> str:
        return f"customer:{market_id}:{segment_id}:{index:09d}"

    def created_date(
        self,
        market_id: str,
        segment_id: str,
        index: int,
    ) -> date:
        control = self._control(market_id)
        opening = self._segment_count(
            control["openingRegisteredCustomers"],
            segment_id,
        )
        key = self._customer_key(market_id, segment_id, index)
        if index < opening:
            history_days = control["openingCustomerHistoryYears"] * 365
            return self._start - timedelta(
                days=stable_integer(
                    self._seed,
                    "opening-customer-created",
                    key,
                    modulo=max(1, history_days),
                )
            )
        acquisition_index = index - opening
        segment_annual = max(
            1,
            self._segment_count(
                control["annualNewCustomers"],
                segment_id,
            ),
        )
        return self._start + timedelta(
            days=int(
                Decimal(acquisition_index)
                * Decimal("365.2425")
                / Decimal(segment_annual)
            )
        )

    def _is_active(
        self,
        market_id: str,
        segment_id: str,
        index: int,
        day: date,
    ) -> bool:
        created = self.created_date(market_id, segment_id, index)
        age_year = max(0, (day - created).days // 365)
        key = self._customer_key(market_id, segment_id, index)
        cache_key = (market_id, segment_id, index, age_year)
        cached = self._active_cache.get(cache_key)
        if cached is not None:
            self._active_cache.move_to_end(cache_key)
            return cached
        control = self._control(market_id)
        active = True
        for lifecycle_year in range(1, age_year + 1):
            if active:
                active = (
                    _fraction(
                        self._seed,
                        "customer-churn",
                        key,
                        lifecycle_year,
                    )
                    >= control["annualChurnRate"]
                )
            else:
                active = (
                    _fraction(
                        self._seed,
                        "customer-reactivation",
                        key,
                        lifecycle_year,
                    )
                    < control["annualReactivationRate"]
                )
        self._active_cache[cache_key] = active
        self._active_cache.move_to_end(cache_key)
        if len(self._active_cache) > self._active_cache_limit:
            self._active_cache.popitem(last=False)
        return active

    def allocate(
        self,
        market_id: str,
        segment_id: str,
        day: date,
        order_key: str,
    ) -> tuple[str, str]:
        """Return (customer key, created date); empty values mean guest checkout."""

        control = self._control(market_id)
        if (
            _fraction(self._seed, "guest-checkout", order_key)
            < control["guestCheckoutRate"]
        ):
            return "", ""
        if self._usage_day != day:
            self._daily_usage = {}
            self._usage_day = day
        population = self._segment_population(market_id, segment_id, day)
        first_index = stable_integer(
            self._seed,
            "customer-selection",
            order_key,
            modulo=population,
        )
        maximum = control["maxOrdersPerCustomerPerDay"]
        selected_key = ""
        selected_index = first_index
        for attempt in range(min(population, 128)):
            candidate = (first_index + attempt * 7919) % population
            key = self._customer_key(market_id, segment_id, candidate)
            if self.created_date(market_id, segment_id, candidate) > day:
                continue
            if self._daily_usage.get(key, 0) >= maximum:
                continue
            if not self._is_active(market_id, segment_id, candidate, day):
                continue
            selected_key = key
            selected_index = candidate
            break
        if not selected_key:
            # Exceptional peak days must still obey the configured daily cap.
            # The second deterministic scan relaxes lifecycle state, not capacity.
            for attempt in range(population):
                candidate = (first_index + attempt) % population
                key = self._customer_key(market_id, segment_id, candidate)
                if (
                    self.created_date(market_id, segment_id, candidate) <= day
                    and self._daily_usage.get(key, 0) < maximum
                ):
                    selected_key = key
                    selected_index = candidate
                    break
        if not selected_key:
            raise RuntimeError(
                f"customer population exhausted for {market_id}/{segment_id} "
                f"on {day}; increase the Config Builder population or daily cap"
            )
        self._daily_usage[selected_key] = self._daily_usage.get(selected_key, 0) + 1
        return (
            selected_key,
            self.created_date(
                market_id,
                segment_id,
                selected_index,
            ).isoformat(),
        )

    def records(
        self,
        market_ids: Iterable[str],
    ) -> Iterator[dict[str, Any]]:
        """Yield the complete customer master, including no-order customers."""

        for market_id in sorted(market_ids):
            market = self._markets[market_id]
            timezone = ZoneInfo(market["timezone"])
            for segment in self._segments:
                segment_id = segment["segmentId"]
                population = self._segment_population(
                    market_id,
                    segment_id,
                    self._end,
                )
                for index in range(population):
                    key = self._customer_key(market_id, segment_id, index)
                    created = self.created_date(
                        market_id,
                        segment_id,
                        index,
                    )
                    yield {
                        "customerKey": key,
                        "marketId": market_id,
                        "segmentId": segment_id,
                        "createdAt": datetime.combine(
                            created,
                            time(hour=0),
                            tzinfo=timezone,
                        ).isoformat(),
                        "state": (
                            "ENABLED"
                            if self._is_active(
                                market_id,
                                segment_id,
                                index,
                                self._end,
                            )
                            else "DISABLED"
                        ),
                    }

            # BC needs a source-native generic customer for Shopify guest orders.
            yield {
                "customerKey": f"walk-in:{market_id}",
                "marketId": market_id,
                "segmentId": "walk-in",
                "createdAt": datetime.combine(
                    self._start,
                    time(hour=0),
                    tzinfo=timezone,
                ).isoformat(),
                "state": "ENABLED",
            }
