"""Generator-owned scenario/source configuration and validation."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from . import SOURCE_SPEC_VERSION
from .catalog_packs import (
    CATALOG_PACK_METADATA,
    CATALOG_PACKS,
    CATALOG_PACK_VERSION,
    SUPPORTED_CATALOG_MODES,
    SUPPORTED_LAUNCH_PROFILES,
    SUPPORTED_OPTION_DIMENSIONS,
)
from .locale_packs import LOCALE_PACKS, resolve_locale

ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
PRODUCT_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9-]{2,39}$")
SKU_PREFIX_PATTERN = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
SUPPORTED_COMPRESSION = {"none", "snappy", "zstd"}
SUPPORTED_CHANNEL_TYPES = {"store", "online", "marketplace"}
SUPPORTED_EVENT_TYPES = {"local-event", "supply-disruption", "demand-shock"}
SUPPORTED_COSTING_METHODS = {"FIFO", "WAC"}
SUPPORTED_FEATURES = {
    "detailedFulfillment",
    "returnsAndRefunds",
    "webhookFixtures",
    "inventoryStateMatrix",
    "supplyChain",
    "warehouseOperations",
    "transfers",
    "supplierPlanning",
    "promotionPlanning",
    "allocationEvidence",
}


class _ConfigYamlLoader(yaml.SafeLoader):
    """Safe YAML loader that keeps ISO dates as source-contract strings."""


_ConfigYamlLoader.yaml_implicit_resolvers = {
    key: [
        resolver
        for resolver in resolvers
        if resolver[0] != "tag:yaml.org,2002:timestamp"
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class ConfigError(ValueError):
    """Raised when a source configuration is invalid."""

    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def _required(mapping: dict[str, Any], key: str, path: str, errors: list[str]) -> Any:
    value = mapping.get(key)
    if value is None or value == "":
        errors.append(f"{path}.{key} is required")
    return value


def _valid_id(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        errors.append(f"{path} must match {ID_PATTERN.pattern}")


def _unique_ids(
    rows: Any,
    key: str,
    path: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> set[str]:
    if not isinstance(rows, list):
        errors.append(f"{path} must be an array")
        return set()
    if not rows and not allow_empty:
        errors.append(f"{path} must contain at least one row")
    result: set[str] = set()
    for index, row in enumerate(rows):
        row_path = f"{path}[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{row_path} must be an object")
            continue
        value = _required(row, key, row_path, errors)
        _valid_id(value, f"{row_path}.{key}", errors)
        if isinstance(value, str):
            if value in result:
                errors.append(f"{path} contains duplicate {key} {value!r}")
            result.add(value)
    return result


def _references(
    values: Any,
    allowed: set[str],
    path: str,
    errors: list[str],
    *,
    required: bool = True,
) -> None:
    if not isinstance(values, list):
        errors.append(f"{path} must be an array")
        return
    if required and not values:
        errors.append(f"{path} must contain at least one reference")
    for value in values:
        if value not in allowed:
            errors.append(f"{path} references unknown id {value!r}")


def _positive_int(value: Any, path: str, errors: list[str], minimum: int = 1) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        errors.append(f"{path} must be an integer >= {minimum}")


def _decimal_text(value: Any, path: str, errors: list[str]) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+(\.[0-9]+)?", value):
        errors.append(f"{path} must be a non-negative decimal string")


def _number_between(
    value: Any,
    path: str,
    errors: list[str],
    minimum: float,
    maximum: float,
) -> None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not minimum <= value <= maximum
    ):
        errors.append(f"{path} must be a number in [{minimum}, {maximum}]")


def _validate_locale(market: dict[str, Any], path: str, errors: list[str]) -> None:
    country = market.get("countryCode")
    if country not in LOCALE_PACKS:
        errors.append(
            f"{path}.countryCode must be one of {', '.join(sorted(LOCALE_PACKS))}"
        )
        return
    expected = resolve_locale(country)
    actual = market.get("localePack")
    if actual != expected:
        errors.append(
            f"{path}.localePack must equal the complete resolved {country} "
            f"locale pack version {expected['version']}"
        )
    currency = market.get("currencyCode")
    if currency != expected["currency"]["code"]:
        errors.append(
            f"{path}.currencyCode {currency!r} does not match country {country} "
            f"currency {expected['currency']['code']}"
        )
    timezone = market.get("timezone")
    if timezone not in expected["timezones"]:
        errors.append(
            f"{path}.timezone {timezone!r} is not allowed by the {country} locale pack"
        )
    try:
        ZoneInfo(str(timezone))
    except ZoneInfoNotFoundError:
        errors.append(f"{path}.timezone {timezone!r} is not a valid IANA timezone")


def _validate_catalog_pack(
    market: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    country = market.get("countryCode")
    if country not in CATALOG_PACK_METADATA:
        return
    expected = CATALOG_PACK_METADATA[country]
    actual = market.get("catalogPack")
    if actual != expected:
        errors.append(
            f"{path}.catalogPack must equal the {country} catalog pack metadata "
            f"version {CATALOG_PACK_VERSION}"
        )


def validate_config(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a defensive copy of the complete source config."""

    if not isinstance(raw, dict):
        raise ConfigError(["configuration root must be an object"])
    config = deepcopy(raw)
    errors: list[str] = []

    if config.get("specVersion") != SOURCE_SPEC_VERSION:
        errors.append(f"specVersion must equal {SOURCE_SPEC_VERSION!r}")

    identity = config.get("identity")
    if not isinstance(identity, dict):
        errors.append("identity must be an object")
        identity = {}
    scenario_id = _required(identity, "scenarioId", "identity", errors)
    _valid_id(scenario_id, "identity.scenarioId", errors)
    _required(identity, "scenarioVersion", "identity", errors)
    _required(identity, "scenarioName", "identity", errors)
    _positive_int(identity.get("masterSeed"), "identity.masterSeed", errors, 0)

    time = config.get("time")
    if not isinstance(time, dict):
        errors.append("time must be an object")
        time = {}
    scenario_start: date | None = None
    scenario_end: date | None = None
    try:
        scenario_start = date.fromisoformat(str(time.get("startDate")))
        scenario_end = date.fromisoformat(str(time.get("endDate")))
        if scenario_end < scenario_start:
            errors.append("time.endDate must not be before time.startDate")
    except ValueError:
        errors.append("time.startDate and time.endDate must be ISO dates")
    if time.get("generationPartition") not in {"day", "month"}:
        errors.append("time.generationPartition must be 'day' or 'month'")

    retailer = config.get("retailer")
    if not isinstance(retailer, dict):
        errors.append("retailer must be an object")
        retailer = {}
    retailer_id = _required(retailer, "retailerId", "retailer", errors)
    _valid_id(retailer_id, "retailer.retailerId", errors)
    _required(retailer, "name", "retailer", errors)
    _required(retailer, "reportingCurrency", "retailer", errors)

    configured_catalog = config.get("catalog")
    if not isinstance(configured_catalog, dict):
        configured_catalog = {}
    configured_category_ids = {
        category.get("categoryId")
        for department in configured_catalog.get("departments", [])
        if isinstance(department, dict)
        for category in department.get("categories", [])
        if isinstance(category, dict)
        and isinstance(category.get("categoryId"), str)
    }
    markets = config.get("markets")
    market_ids = _unique_ids(markets, "marketId", "markets", errors)
    market_by_id = {
        row["marketId"]: row
        for row in markets or []
        if isinstance(row, dict) and isinstance(row.get("marketId"), str)
    }
    if isinstance(markets, list):
        for index, market in enumerate(markets):
            if not isinstance(market, dict):
                continue
            path = f"markets[{index}]"
            _required(market, "name", path, errors)
            _required(market, "regionCode", path, errors)
            _required(market, "city", path, errors)
            _validate_locale(market, path, errors)
            _validate_catalog_pack(market, path, errors)
            coverage = market.get("localePack", {}).get("calendarCoverage", {})
            if scenario_start and scenario_end and coverage:
                try:
                    coverage_start = date.fromisoformat(coverage["startDate"])
                    coverage_end = date.fromisoformat(coverage["endDate"])
                    if scenario_start < coverage_start or scenario_end > coverage_end:
                        errors.append(
                            f"{path}.localePack calendar coverage does not contain "
                            "the complete scenario range"
                        )
                except (KeyError, ValueError, TypeError):
                    errors.append(f"{path}.localePack.calendarCoverage is invalid")
            _decimal_text(market.get("fxRateToReporting"), f"{path}.fxRateToReporting", errors)
            assortment = market.get("assortment", {})
            if not isinstance(assortment, dict):
                errors.append(f"{path}.assortment must be an object")
            else:
                _positive_int(
                    assortment.get("skusPerDepartment"),
                    f"{path}.assortment.skusPerDepartment",
                    errors,
                )
                _positive_int(
                    assortment.get("variantsPerProduct"),
                    f"{path}.assortment.variantsPerProduct",
                    errors,
                )
                category_weights = assortment.get(
                    "categoryAssortmentWeights"
                )
                if category_weights is not None:
                    if not isinstance(category_weights, dict):
                        errors.append(
                            f"{path}.assortment.categoryAssortmentWeights "
                            "must be an object"
                        )
                    else:
                        for category_id, weight in category_weights.items():
                            weight_path = (
                                f"{path}.assortment."
                                f"categoryAssortmentWeights.{category_id}"
                            )
                            if category_id not in configured_category_ids:
                                errors.append(
                                    f"{weight_path} references unknown "
                                    f"category {category_id!r}"
                                )
                            if (
                                not isinstance(weight, (int, float))
                                or isinstance(weight, bool)
                                or not Decimal(str(weight)).is_finite()
                                or weight <= 0
                            ):
                                errors.append(
                                    f"{weight_path} must be a positive number"
                                )
            demand = market.get("demand", {})
            if not isinstance(demand, dict):
                errors.append(f"{path}.demand must be an object")
            else:
                _positive_int(
                    demand.get("startingDailyOrders"),
                    f"{path}.demand.startingDailyOrders",
                    errors,
                )
                _number_between(
                    demand.get("averageLinesPerOrder"),
                    f"{path}.demand.averageLinesPerOrder",
                    errors,
                    1,
                    5,
                )
                for field in ("demandLevelScalar", "annualGrowthRate", "noise"):
                    value = demand.get(field)
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                        errors.append(f"{path}.demand.{field} must be a non-negative number")
                for field in (
                    "onlineShareStart",
                    "onlineShareEnd",
                    "onlineShareSkuVariation",
                ):
                    _number_between(
                        demand.get(field),
                        f"{path}.demand.{field}",
                        errors,
                        0,
                        1,
                    )
                _number_between(
                    demand.get("intermittencyRate"),
                    f"{path}.demand.intermittencyRate",
                    errors,
                    0,
                    1,
                )
                _positive_int(
                    demand.get("newProductRampDays"),
                    f"{path}.demand.newProductRampDays",
                    errors,
                )
                day_of_week_factors = demand.get("dayOfWeekFactors")
                if (
                    not isinstance(day_of_week_factors, list)
                    or len(day_of_week_factors) != 7
                    or any(
                        not isinstance(value, (int, float))
                        or isinstance(value, bool)
                        or value <= 0
                        for value in day_of_week_factors
                    )
                ):
                    errors.append(
                        f"{path}.demand.dayOfWeekFactors must contain seven "
                        "positive Monday-to-Sunday numbers"
                    )
            customer_population = market.get("customerPopulation")
            if not isinstance(customer_population, dict):
                errors.append(f"{path}.customerPopulation must be an object")
            else:
                for field in (
                    "openingRegisteredCustomers",
                    "annualNewCustomers",
                    "openingCustomerHistoryYears",
                    "maxOrdersPerCustomerPerDay",
                ):
                    _positive_int(
                        customer_population.get(field),
                        f"{path}.customerPopulation.{field}",
                        errors,
                    )
                for field in (
                    "annualChurnRate",
                    "annualReactivationRate",
                    "guestCheckoutRate",
                ):
                    _number_between(
                        customer_population.get(field),
                        f"{path}.customerPopulation.{field}",
                        errors,
                        0,
                        1,
                    )
            dynamics = market.get("priceDynamics", {})
            if not isinstance(dynamics, dict):
                errors.append(f"{path}.priceDynamics must be an object")
            else:
                if dynamics.get("profile") not in {"response-rich", "sparse", "stable"}:
                    errors.append(
                        f"{path}.priceDynamics.profile must be response-rich, sparse or stable"
                    )
                _positive_int(
                    dynamics.get("priceChangeEventsPerSkuPerYear"),
                    f"{path}.priceDynamics.priceChangeEventsPerSkuPerYear",
                    errors,
                    0,
                )
                _number_between(
                    dynamics.get("annualInflationRate"),
                    f"{path}.priceDynamics.annualInflationRate",
                    errors,
                    -0.25,
                    1,
                )
                _number_between(
                    dynamics.get("priceEndingAdherence"),
                    f"{path}.priceDynamics.priceEndingAdherence",
                    errors,
                    0,
                    1,
                )
            signals = market.get("signals")
            if not isinstance(signals, dict):
                errors.append(f"{path}.signals must be an object")
            else:
                for signal in (
                    "holidays",
                    "promotions",
                    "weather",
                    "localEvents",
                    "competitor",
                    "macro",
                    "fx",
                ):
                    if not isinstance(signals.get(signal), bool):
                        errors.append(f"{path}.signals.{signal} must be boolean")

    legal_entities = config.get("legalEntities")
    entity_ids = _unique_ids(
        legal_entities, "legalEntityId", "legalEntities", errors
    )
    if isinstance(legal_entities, list):
        for index, entity in enumerate(legal_entities):
            if not isinstance(entity, dict):
                continue
            path = f"legalEntities[{index}]"
            _required(entity, "name", path, errors)
            _references(entity.get("marketIds"), market_ids, f"{path}.marketIds", errors)

    channels = config.get("channels")
    channel_ids = _unique_ids(channels, "channelId", "channels", errors)
    channel_by_id = {
        row["channelId"]: row
        for row in channels or []
        if isinstance(row, dict) and isinstance(row.get("channelId"), str)
    }
    entity_by_id = {
        row["legalEntityId"]: row
        for row in legal_entities or []
        if isinstance(row, dict) and isinstance(row.get("legalEntityId"), str)
    }
    if isinstance(channels, list):
        for index, channel in enumerate(channels):
            if not isinstance(channel, dict):
                continue
            path = f"channels[{index}]"
            if channel.get("marketId") not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            if channel.get("type") not in SUPPORTED_CHANNEL_TYPES:
                errors.append(
                    f"{path}.type must be one of {', '.join(sorted(SUPPORTED_CHANNEL_TYPES))}"
                )

    warehouses = config.get("warehouses")
    warehouse_ids = _unique_ids(warehouses, "warehouseId", "warehouses", errors)
    stores = config.get("stores")
    store_ids = _unique_ids(stores, "storeId", "stores", errors)
    warehouse_by_id = {
        row["warehouseId"]: row
        for row in warehouses or []
        if isinstance(row, dict) and isinstance(row.get("warehouseId"), str)
    }
    store_by_id = {
        row["storeId"]: row
        for row in stores or []
        if isinstance(row, dict) and isinstance(row.get("storeId"), str)
    }

    if isinstance(stores, list):
        for index, store in enumerate(stores):
            if not isinstance(store, dict):
                continue
            path = f"stores[{index}]"
            if store.get("marketId") not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            if store.get("legalEntityId") not in entity_ids:
                errors.append(f"{path}.legalEntityId references an unknown legal entity")
            _references(store.get("channelIds"), channel_ids, f"{path}.channelIds", errors)
            _references(
                store.get("warehousePriority"),
                warehouse_ids,
                f"{path}.warehousePriority",
                errors,
            )
            _required(store, "name", path, errors)
            _required(store, "addressLine1", path, errors)
            _required(store, "postcode", path, errors)
            market = market_by_id.get(store.get("marketId"))
            postcode_pattern = (
                market.get("localePack", {}).get("postcodePattern")
                if market
                else None
            )
            if (
                isinstance(postcode_pattern, str)
                and isinstance(store.get("postcode"), str)
                and not re.fullmatch(postcode_pattern, store["postcode"])
            ):
                errors.append(
                    f"{path}.postcode does not match the resolved market locale pattern"
                )
            _number_between(
                store.get("assortmentCoverage"),
                f"{path}.assortmentCoverage",
                errors,
                0.05,
                1,
            )
            _number_between(
                store.get("demandScale"),
                f"{path}.demandScale",
                errors,
                0.1,
                10,
            )
            entity = entity_by_id.get(store.get("legalEntityId"))
            if entity and store.get("marketId") not in entity.get("marketIds", []):
                errors.append(
                    f"{path}.legalEntityId does not cover market {store.get('marketId')!r}"
                )
            for channel_id in store.get("channelIds", []):
                channel = channel_by_id.get(channel_id)
                if channel and channel.get("marketId") != store.get("marketId"):
                    errors.append(
                        f"{path}.channelIds contains {channel_id!r} from another market"
                    )
            for warehouse_id in store.get("warehousePriority", []):
                warehouse = warehouse_by_id.get(warehouse_id)
                if warehouse and warehouse.get("marketId") != store.get("marketId"):
                    errors.append(
                        f"{path}.warehousePriority contains {warehouse_id!r} from another market"
                    )

    if isinstance(warehouses, list):
        for index, warehouse in enumerate(warehouses):
            if not isinstance(warehouse, dict):
                continue
            path = f"warehouses[{index}]"
            if warehouse.get("marketId") not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            if warehouse.get("legalEntityId") not in entity_ids:
                errors.append(f"{path}.legalEntityId references an unknown legal entity")
            _references(
                warehouse.get("servesLocations"),
                store_ids,
                f"{path}.servesLocations",
                errors,
            )
            _required(warehouse, "name", path, errors)
            _required(
                warehouse,
                "businessCentralLocationCode",
                path,
                errors,
            )
            _positive_int(
                warehouse.get("capacityUnits"),
                f"{path}.capacityUnits",
                errors,
            )
            _positive_int(
                warehouse.get("openingStockPerSku"),
                f"{path}.openingStockPerSku",
                errors,
                0,
            )
            _positive_int(
                warehouse.get("openingStockDaysOfCover", 0),
                f"{path}.openingStockDaysOfCover",
                errors,
                0,
            )
            _positive_int(
                warehouse.get("replenishmentPackSize"),
                f"{path}.replenishmentPackSize",
                errors,
            )
            entity = entity_by_id.get(warehouse.get("legalEntityId"))
            if entity and warehouse.get("marketId") not in entity.get("marketIds", []):
                errors.append(
                    f"{path}.legalEntityId does not cover market {warehouse.get('marketId')!r}"
                )
            for store_id in warehouse.get("servesLocations", []):
                store = store_by_id.get(store_id)
                if store and store.get("marketId") != warehouse.get("marketId"):
                    errors.append(
                        f"{path}.servesLocations contains {store_id!r} from another market"
                    )

    catalog = config.get("catalog")
    if not isinstance(catalog, dict):
        errors.append("catalog must be an object")
        catalog = {}
    generation = catalog.get("generation")
    if not isinstance(generation, dict):
        errors.append("catalog.generation must be an object")
        generation = {}
    if generation.get("mode") not in SUPPORTED_CATALOG_MODES:
        errors.append(
            "catalog.generation.mode must be generated, hybrid or explicit"
        )
    if generation.get("catalogPackVersion") != CATALOG_PACK_VERSION:
        errors.append(
            f"catalog.generation.catalogPackVersion must equal "
            f"{CATALOG_PACK_VERSION!r}"
        )
    sku_prefix = generation.get("skuPrefix")
    if not isinstance(sku_prefix, str) or not SKU_PREFIX_PATTERN.fullmatch(sku_prefix):
        errors.append(
            f"catalog.generation.skuPrefix must match {SKU_PREFIX_PATTERN.pattern}"
        )
    _positive_int(
        generation.get("launchHistoryDays"),
        "catalog.generation.launchHistoryDays",
        errors,
        0,
    )
    _number_between(
        generation.get("incumbentProductPct"),
        "catalog.generation.incumbentProductPct",
        errors,
        0,
        1,
    )
    _number_between(
        generation.get("discontinueRate"),
        "catalog.generation.discontinueRate",
        errors,
        0,
        1,
    )
    _number_between(
        generation.get("launchSpreadPct"),
        "catalog.generation.launchSpreadPct",
        errors,
        0,
        1,
    )
    _positive_int(
        generation.get("variantLaunchSpreadDays"),
        "catalog.generation.variantLaunchSpreadDays",
        errors,
        0,
    )
    _number_between(
        generation.get("replacementLinkRate"),
        "catalog.generation.replacementLinkRate",
        errors,
        0,
        1,
    )
    _positive_int(
        generation.get("minProductLifeDays"),
        "catalog.generation.minProductLifeDays",
        errors,
    )
    _positive_int(
        generation.get("maxProductLifeDays"),
        "catalog.generation.maxProductLifeDays",
        errors,
    )
    if (
        isinstance(generation.get("minProductLifeDays"), int)
        and isinstance(generation.get("maxProductLifeDays"), int)
        and generation["maxProductLifeDays"] < generation["minProductLifeDays"]
    ):
        errors.append(
            "catalog.generation.maxProductLifeDays must be at least "
            "minProductLifeDays"
        )
    lifecycle = generation.get("lifecycle")
    if not isinstance(lifecycle, dict):
        errors.append("catalog.generation.lifecycle must be an object")
        lifecycle = {}
    if lifecycle.get("defaultLaunchProfile") not in SUPPORTED_LAUNCH_PROFILES:
        errors.append(
            "catalog.generation.lifecycle.defaultLaunchProfile is unsupported"
        )
    for field in (
        "launchSpikeDays",
        "launchSettleDays",
        "preLaunchAnticipationDays",
        "runoutMonths",
        "clearanceStartDaysAfterSuccessor",
        "fireSaleFinalDays",
    ):
        _positive_int(
            lifecycle.get(field),
            f"catalog.generation.lifecycle.{field}",
            errors,
            0,
        )
    for field, minimum, maximum in (
        ("launchSpikeMultiplier", 1, 20),
        ("preLaunchDemandMultiplier", 0, 1),
        ("substitutionRate", 0, 1),
        ("runoutDemandMultiplier", 0, 1),
        ("runoutMarkdownPct", 0, .95),
        ("runoutMarkdownDemandMultiplier", .1, 10),
        ("clearanceDiscountPct", 0, .95),
        ("clearanceDemandMultiplier", .1, 10),
        ("fireSaleDiscountPct", 0, .95),
        ("fireSaleDemandMultiplier", .1, 10),
    ):
        _number_between(
            lifecycle.get(field),
            f"catalog.generation.lifecycle.{field}",
            errors,
            minimum,
            maximum,
        )
    departments = catalog.get("departments")
    department_ids = _unique_ids(
        departments, "departmentId", "catalog.departments", errors
    )
    category_ids: set[str] = set()
    department_by_category: dict[str, str] = {}
    configured_family_sets = [
        set(CATALOG_PACK_METADATA[market["countryCode"]]["familyIds"])
        for market in markets or []
        if isinstance(market, dict)
        and market.get("countryCode") in CATALOG_PACK_METADATA
    ]
    supported_families = (
        set.intersection(*configured_family_sets) if configured_family_sets else set()
    )
    if isinstance(departments, list):
        for index, department in enumerate(departments):
            if not isinstance(department, dict):
                continue
            path = f"catalog.departments[{index}]"
            _required(department, "name", path, errors)
            categories = department.get("categories")
            ids = _unique_ids(categories, "categoryId", f"{path}.categories", errors)
            overlap = category_ids.intersection(ids)
            for category_id in sorted(overlap):
                errors.append(f"catalog contains duplicate categoryId {category_id!r}")
            category_ids.update(ids)
            if isinstance(categories, list):
                for category_index, category in enumerate(categories):
                    if not isinstance(category, dict):
                        continue
                    category_path = f"{path}.categories[{category_index}]"
                    _required(category, "name", category_path, errors)
                    category_id = category.get("categoryId")
                    if isinstance(category_id, str):
                        department_by_category[category_id] = department.get(
                            "departmentId", ""
                        )
                    if category.get("taxCategory") not in {
                        "apparel",
                        "automotive",
                        "baby",
                        "beauty",
                        "books",
                        "electronics",
                        "grocery",
                        "health",
                        "home",
                        "sports",
                        "stationery",
                        "toys",
                    }:
                        errors.append(
                            f"{category_path}.taxCategory is not a supported retail tax class"
                        )
                    family = category.get("catalogFamily")
                    if family not in supported_families:
                        errors.append(
                            f"{category_path}.catalogFamily {family!r} is not available "
                            "for every configured market"
                        )
                    option_dimensions = category.get("optionDimensions")
                    if not isinstance(option_dimensions, list) or not option_dimensions:
                        errors.append(
                            f"{category_path}.optionDimensions must contain at least one dimension"
                        )
                    else:
                        for dimension in option_dimensions:
                            if dimension not in SUPPORTED_OPTION_DIMENSIONS:
                                errors.append(
                                    f"{category_path}.optionDimensions contains unsupported "
                                    f"value {dimension!r}"
                                )
                    peak_month = category.get("seasonalityPeakMonth")
                    if (
                        not isinstance(peak_month, int)
                        or isinstance(peak_month, bool)
                        or not 1 <= peak_month <= 12
                    ):
                        errors.append(
                            f"{category_path}.seasonalityPeakMonth must be an integer in [1, 12]"
                        )
                    _number_between(
                        category.get("seasonalityStrength"),
                        f"{category_path}.seasonalityStrength",
                        errors,
                        0,
                        2,
                    )
                    if category.get("costingMethod") not in SUPPORTED_COSTING_METHODS:
                        errors.append(
                            f"{category_path}.costingMethod must be FIFO or WAC"
                        )
                    _number_between(
                        category.get("targetMargin"),
                        f"{category_path}.targetMargin",
                        errors,
                        0.01,
                        0.95,
                    )
                    _number_between(
                        category.get("baseReturnRate"),
                        f"{category_path}.baseReturnRate",
                        errors,
                        0,
                        0.50,
                    )
                    elasticity_min = category.get("elasticityMin")
                    elasticity_max = category.get("elasticityMax")
                    if (
                        not isinstance(elasticity_min, (int, float))
                        or isinstance(elasticity_min, bool)
                        or not isinstance(elasticity_max, (int, float))
                        or isinstance(elasticity_max, bool)
                        or elasticity_min >= elasticity_max
                        or elasticity_max > 0
                    ):
                        errors.append(
                            f"{category_path}.elasticityMin must be less than "
                            "elasticityMax and both must be non-positive"
                        )
    product_templates = catalog.get("productTemplates")
    _unique_ids(
        product_templates,
        "productId",
        "catalog.productTemplates",
        errors,
        allow_empty=True,
    )
    mode = generation.get("mode")
    if mode == "generated" and product_templates:
        errors.append(
            "catalog.productTemplates must be empty when generation.mode is generated"
        )
    if mode == "explicit" and not product_templates:
        errors.append(
            "catalog.productTemplates must contain products when generation.mode is explicit"
        )
    seen_product_codes: set[tuple[str, str]] = set()
    if isinstance(product_templates, list):
        for index, product in enumerate(product_templates):
            if not isinstance(product, dict):
                continue
            path = f"catalog.productTemplates[{index}]"
            _required(product, "title", path, errors)
            _required(product, "brand", path, errors)
            brand_code = _required(product, "brandCode", path, errors)
            if (
                not isinstance(brand_code, str)
                or not re.fullmatch(r"[A-Z0-9]{2,8}", brand_code)
            ):
                errors.append(f"{path}.brandCode must be 2-8 uppercase letters/digits")
            _required(product, "description", path, errors)
            market_id = product.get("marketId")
            if market_id not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            if product.get("departmentId") not in department_ids:
                errors.append(f"{path}.departmentId references an unknown department")
            if product.get("categoryId") not in category_ids:
                errors.append(f"{path}.categoryId references an unknown category")
            elif department_by_category.get(product.get("categoryId")) != product.get(
                "departmentId"
            ):
                errors.append(f"{path}.categoryId belongs to another department")
            product_code = product.get("productCode")
            if (
                not isinstance(product_code, str)
                or not PRODUCT_CODE_PATTERN.fullmatch(product_code)
            ):
                errors.append(
                    f"{path}.productCode must match {PRODUCT_CODE_PATTERN.pattern}"
                )
            elif isinstance(market_id, str):
                code_key = (market_id, product_code)
                if code_key in seen_product_codes:
                    errors.append(
                        f"catalog.productTemplates contains duplicate productCode "
                        f"{product_code!r} in market {market_id!r}"
                    )
                seen_product_codes.add(code_key)
            _decimal_text(product.get("basePrice"), f"{path}.basePrice", errors)
            _decimal_text(product.get("baseCost"), f"{path}.baseCost", errors)
            try:
                if Decimal(str(product.get("baseCost"))) >= Decimal(
                    str(product.get("basePrice"))
                ):
                    errors.append(f"{path}.baseCost must be less than basePrice")
            except Exception:
                pass
            option_dimensions = product.get("optionDimensions")
            if not isinstance(option_dimensions, list):
                errors.append(f"{path}.optionDimensions must be an array")
            else:
                for dimension in option_dimensions:
                    if dimension not in SUPPORTED_OPTION_DIMENSIONS:
                        errors.append(
                            f"{path}.optionDimensions contains unsupported value "
                            f"{dimension!r}"
                        )
            variant_definitions = product.get("variantDefinitions", [])
            if not isinstance(variant_definitions, list):
                errors.append(f"{path}.variantDefinitions must be an array")
            elif variant_definitions:
                market = market_by_id.get(market_id)
                expected_count = (
                    market.get("assortment", {}).get("variantsPerProduct")
                    if market
                    else None
                )
                if (
                    isinstance(expected_count, int)
                    and len(variant_definitions) < expected_count
                ):
                    errors.append(
                        f"{path}.variantDefinitions must contain at least "
                        f"{expected_count} rows for its market"
                    )
                seen_option_sets: set[tuple[tuple[str, str], ...]] = set()
                allowed_values = (
                    CATALOG_PACKS[market["countryCode"]]["optionValues"]
                    if market
                    and market.get("countryCode") in CATALOG_PACKS
                    else {}
                )
                for variant_index, variant_definition in enumerate(
                    variant_definitions
                ):
                    variant_path = (
                        f"{path}.variantDefinitions[{variant_index}]"
                    )
                    if not isinstance(variant_definition, dict):
                        errors.append(f"{variant_path} must be an object")
                        continue
                    values = variant_definition.get("optionValues")
                    if not isinstance(values, dict):
                        errors.append(
                            f"{variant_path}.optionValues must be an object"
                        )
                        continue
                    dimensions = (
                        set(option_dimensions)
                        if isinstance(option_dimensions, list)
                        else set()
                    )
                    if set(values) != dimensions:
                        errors.append(
                            f"{variant_path}.optionValues keys must exactly match "
                            f"{sorted(dimensions)}"
                        )
                    for dimension, value in values.items():
                        names = {
                            row["name"]
                            for row in allowed_values.get(dimension, [])
                        }
                        if value not in names:
                            errors.append(
                                f"{variant_path}.optionValues.{dimension} "
                                f"contains unsupported value {value!r}"
                            )
                    option_set = tuple(sorted(values.items()))
                    if option_set in seen_option_sets:
                        errors.append(
                            f"{path}.variantDefinitions contains a duplicate "
                            "option combination"
                        )
                    seen_option_sets.add(option_set)
            launch_profile = product.get(
                "launchProfile",
                lifecycle.get("defaultLaunchProfile"),
            )
            if launch_profile not in SUPPORTED_LAUNCH_PROFILES:
                errors.append(f"{path}.launchProfile is unsupported")
            if "variantLaunchSpreadDays" in product:
                _positive_int(
                    product.get("variantLaunchSpreadDays"),
                    f"{path}.variantLaunchSpreadDays",
                    errors,
                    0,
                )
            product_dates: dict[str, date] = {}
            try:
                product_dates["launchDate"] = date.fromisoformat(
                    str(product.get("launchDate"))
                )
            except ValueError:
                errors.append(f"{path}.launchDate must be an ISO date")
            if product.get("discontinueDate"):
                try:
                    product_dates["discontinueDate"] = date.fromisoformat(
                        str(product["discontinueDate"])
                    )
                except ValueError:
                    errors.append(f"{path}.discontinueDate must be empty or an ISO date")
            if (
                product_dates.get("launchDate")
                and product_dates.get("discontinueDate")
                and product_dates["discontinueDate"] < product_dates["launchDate"]
            ):
                errors.append(f"{path}.discontinueDate must not be before launchDate")
            if (
                scenario_end
                and product_dates.get("launchDate")
                and product_dates["launchDate"] > scenario_end
            ):
                errors.append(f"{path}.launchDate must not be after the scenario end")
            if (
                scenario_start
                and product_dates.get("discontinueDate")
                and product_dates["discontinueDate"] < scenario_start
            ):
                errors.append(
                    f"{path}.discontinueDate must not be before the scenario start"
                )
            predecessor = product.get("successorOfProductCode")
            if predecessor and (
                not isinstance(predecessor, str)
                or not PRODUCT_CODE_PATTERN.fullmatch(predecessor)
            ):
                errors.append(
                    f"{path}.successorOfProductCode must be empty or match "
                    f"{PRODUCT_CODE_PATTERN.pattern}"
                )
    if isinstance(product_templates, list):
        templates_by_market_and_code = {
            (row["marketId"], row["productCode"]): row
            for row in product_templates
            if isinstance(row, dict)
            and isinstance(row.get("marketId"), str)
            and isinstance(row.get("productCode"), str)
        }
        for index, product in enumerate(product_templates):
            if not isinstance(product, dict) or not product.get(
                "successorOfProductCode"
            ):
                continue
            path = f"catalog.productTemplates[{index}]"
            predecessor = templates_by_market_and_code.get(
                (
                    product.get("marketId"),
                    product["successorOfProductCode"],
                )
            )
            if predecessor is None:
                errors.append(
                    f"{path}.successorOfProductCode must reference an explicit "
                    "product in the same market"
                )
                continue
            try:
                if date.fromisoformat(predecessor["launchDate"]) >= date.fromisoformat(
                    product["launchDate"]
                ):
                    errors.append(
                        f"{path}.successorOfProductCode must reference a product "
                        "launched earlier"
                    )
            except (KeyError, TypeError, ValueError):
                pass

    customer_segments = config.get("customerSegments")
    segment_ids = _unique_ids(
        customer_segments,
        "segmentId",
        "customerSegments",
        errors,
    )
    if isinstance(customer_segments, list):
        total_share = Decimal("0")
        for index, segment in enumerate(customer_segments):
            if not isinstance(segment, dict):
                continue
            path = f"customerSegments[{index}]"
            _required(segment, "name", path, errors)
            _number_between(segment.get("share"), f"{path}.share", errors, 0, 1)
            _number_between(
                segment.get("demandMultiplier"),
                f"{path}.demandMultiplier",
                errors,
                0.1,
                10,
            )
            if isinstance(segment.get("share"), (int, float)):
                total_share += Decimal(str(segment["share"]))
        if customer_segments and abs(total_share - Decimal("1")) > Decimal("0.000001"):
            errors.append("customerSegments shares must sum to 1")

    sources = config.get("sourceInstances")
    if not isinstance(sources, dict):
        errors.append("sourceInstances must be an object")
        sources = {}
    shopify = sources.get("shopify")
    _unique_ids(shopify, "shopId", "sourceInstances.shopify", errors)
    if isinstance(shopify, list):
        for index, shop in enumerate(shopify):
            if not isinstance(shop, dict):
                continue
            path = f"sourceInstances.shopify[{index}]"
            if shop.get("marketId") not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            _required(shop, "shopDomain", path, errors)
            _references(shop.get("storeIds"), store_ids, f"{path}.storeIds", errors)
            for store_id in shop.get("storeIds", []):
                store = store_by_id.get(store_id)
                if store and store.get("marketId") != shop.get("marketId"):
                    errors.append(
                        f"{path}.storeIds contains {store_id!r} from another market"
                    )
    business_central = sources.get("businessCentral")
    _unique_ids(
        business_central,
        "companyId",
        "sourceInstances.businessCentral",
        errors,
    )
    if isinstance(business_central, list):
        for index, company in enumerate(business_central):
            if not isinstance(company, dict):
                continue
            path = f"sourceInstances.businessCentral[{index}]"
            if company.get("legalEntityId") not in entity_ids:
                errors.append(f"{path}.legalEntityId references an unknown legal entity")
            _required(company, "companyName", path, errors)
            _references(
                company.get("warehouseIds"),
                warehouse_ids,
                f"{path}.warehouseIds",
                errors,
            )
            for warehouse_id in company.get("warehouseIds", []):
                warehouse = warehouse_by_id.get(warehouse_id)
                if warehouse and warehouse.get("legalEntityId") != company.get(
                    "legalEntityId"
                ):
                    errors.append(
                        f"{path}.warehouseIds contains {warehouse_id!r} from another legal entity"
                    )

    promotions = config.get("promotions")
    _unique_ids(promotions, "promotionId", "promotions", errors, allow_empty=True)
    if isinstance(promotions, list):
        for index, promotion in enumerate(promotions):
            if not isinstance(promotion, dict):
                continue
            path = f"promotions[{index}]"
            _required(promotion, "name", path, errors)
            if promotion.get("marketId") not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            for field in (
                "storeIds",
                "channelIds",
                "departmentIds",
                "categoryIds",
                "customerSegmentIds",
            ):
                _required(promotion, field, path, errors)
            _references(
                promotion.get("storeIds"),
                store_ids,
                f"{path}.storeIds",
                errors,
                required=False,
            )
            _references(
                promotion.get("channelIds"),
                channel_ids,
                f"{path}.channelIds",
                errors,
                required=False,
            )
            _references(
                promotion.get("departmentIds"),
                department_ids,
                f"{path}.departmentIds",
                errors,
                required=False,
            )
            _references(
                promotion.get("categoryIds"),
                category_ids,
                f"{path}.categoryIds",
                errors,
                required=False,
            )
            _references(
                promotion.get("customerSegmentIds"),
                segment_ids,
                f"{path}.customerSegmentIds",
                errors,
                required=False,
            )
            for store_id in (
                promotion.get("storeIds")
                if isinstance(promotion.get("storeIds"), list)
                else []
            ):
                store = store_by_id.get(store_id)
                if store and store.get("marketId") != promotion.get("marketId"):
                    errors.append(
                        f"{path}.storeIds contains {store_id!r} from another market"
                    )
            for channel_id in (
                promotion.get("channelIds")
                if isinstance(promotion.get("channelIds"), list)
                else []
            ):
                channel = channel_by_id.get(channel_id)
                if channel and channel.get("marketId") != promotion.get("marketId"):
                    errors.append(
                        f"{path}.channelIds contains {channel_id!r} from another market"
                    )
            promotion_dates: dict[str, date] = {}
            for field in ("startDate", "endDate"):
                try:
                    promotion_dates[field] = date.fromisoformat(
                        str(promotion.get(field))
                    )
                except ValueError:
                    errors.append(f"{path}.{field} must be an ISO date")
            if (
                promotion_dates.get("endDate")
                and promotion_dates.get("startDate")
                and promotion_dates["endDate"] < promotion_dates["startDate"]
            ):
                errors.append(f"{path}.endDate must not be before startDate")
            discount = promotion.get("discountPct")
            if not isinstance(discount, (int, float)) or not 0 <= discount < 1:
                errors.append(f"{path}.discountPct must be in [0,1)")
            multiplier = promotion.get("demandMultiplier")
            if not isinstance(multiplier, (int, float)) or multiplier <= 0:
                errors.append(f"{path}.demandMultiplier must be > 0")

    events = config.get("events")
    _unique_ids(events, "eventId", "events", errors, allow_empty=True)
    if isinstance(events, list):
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            path = f"events[{index}]"
            _required(event, "name", path, errors)
            if event.get("marketId") not in market_ids:
                errors.append(f"{path}.marketId references an unknown market")
            if event.get("type") not in SUPPORTED_EVENT_TYPES:
                errors.append(
                    f"{path}.type must be one of {', '.join(sorted(SUPPORTED_EVENT_TYPES))}"
                )
            event_store_id = event.get("storeId")
            if event_store_id:
                if event_store_id not in store_ids:
                    errors.append(f"{path}.storeId references an unknown store")
                elif store_by_id[event_store_id].get("marketId") != event.get("marketId"):
                    errors.append(f"{path}.storeId belongs to another market")
            for field in ("departmentIds", "categoryIds", "channelIds"):
                _required(event, field, path, errors)
            event_dates: dict[str, date] = {}
            for field in ("startDate", "endDate"):
                try:
                    event_dates[field] = date.fromisoformat(str(event.get(field)))
                except ValueError:
                    errors.append(f"{path}.{field} must be an ISO date")
            if (
                event_dates.get("endDate")
                and event_dates.get("startDate")
                and event_dates["endDate"] < event_dates["startDate"]
            ):
                errors.append(f"{path}.endDate must not be before startDate")
            multiplier = event.get("demandMultiplier")
            if not isinstance(multiplier, (int, float)) or multiplier <= 0:
                errors.append(f"{path}.demandMultiplier must be > 0")
            for field in ("trafficMultiplier", "costMultiplier", "leadTimeMultiplier"):
                value = event.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    errors.append(f"{path}.{field} must be > 0")
            _number_between(
                event.get("inventoryLossPct"),
                f"{path}.inventoryLossPct",
                errors,
                0,
                1,
            )
            if event.get("recoveryShape") not in {
                "step",
                "linear",
                "ramp",
                "triangle",
            }:
                errors.append(
                    f"{path}.recoveryShape must be step, linear, ramp or triangle"
                )
            _references(
                event.get("departmentIds"),
                department_ids,
                f"{path}.departmentIds",
                errors,
                required=False,
            )
            _references(
                event.get("categoryIds"),
                category_ids,
                f"{path}.categoryIds",
                errors,
                required=False,
            )
            _references(
                event.get("channelIds"),
                channel_ids,
                f"{path}.channelIds",
                errors,
                required=False,
            )

    pandemics = config.get("pandemics")
    _unique_ids(
        pandemics,
        "pandemicId",
        "pandemics",
        errors,
        allow_empty=True,
    )
    if isinstance(pandemics, list):
        for pandemic_index, pandemic in enumerate(pandemics):
            if not isinstance(pandemic, dict):
                continue
            path = f"pandemics[{pandemic_index}]"
            _required(pandemic, "name", path, errors)
            _required(pandemic, "pathogen", path, errors)
            _required(pandemic, "note", path, errors)
            if pandemic.get("effectMode") not in {
                "synthetic-shock",
                "documented-no-adjustment",
                "observed-no-adjustment",
            }:
                errors.append(
                    f"{path}.effectMode must be synthetic-shock, "
                    "documented-no-adjustment or observed-no-adjustment"
                )
            _references(
                pandemic.get("marketIds"),
                market_ids,
                f"{path}.marketIds",
                errors,
            )
            pandemic_dates: dict[str, date] = {}
            for field in ("startDate", "endDate"):
                try:
                    pandemic_dates[field] = date.fromisoformat(
                        str(pandemic.get(field))
                    )
                except ValueError:
                    errors.append(f"{path}.{field} must be an ISO date")
            if (
                pandemic_dates.get("endDate")
                and pandemic_dates.get("startDate")
                and pandemic_dates["endDate"] < pandemic_dates["startDate"]
            ):
                errors.append(f"{path}.endDate must not be before startDate")
            phases = pandemic.get("phases")
            phase_ids = _unique_ids(
                phases,
                "phaseId",
                f"{path}.phases",
                errors,
            )
            if isinstance(phases, list):
                for phase_index, phase in enumerate(phases):
                    if not isinstance(phase, dict):
                        continue
                    phase_path = f"{path}.phases[{phase_index}]"
                    _required(phase, "name", phase_path, errors)
                    phase_dates: dict[str, date] = {}
                    for field in ("startDate", "endDate"):
                        try:
                            phase_dates[field] = date.fromisoformat(
                                str(phase.get(field))
                            )
                        except ValueError:
                            errors.append(f"{phase_path}.{field} must be an ISO date")
                    if (
                        phase_dates.get("startDate")
                        and phase_dates.get("endDate")
                        and phase_dates["endDate"] < phase_dates["startDate"]
                    ):
                        errors.append(
                            f"{phase_path}.endDate must not be before startDate"
                        )
                    if (
                        pandemic_dates.get("startDate")
                        and pandemic_dates.get("endDate")
                        and phase_dates.get("startDate")
                        and phase_dates.get("endDate")
                        and (
                            phase_dates["startDate"] < pandemic_dates["startDate"]
                            or phase_dates["endDate"] > pandemic_dates["endDate"]
                        )
                    ):
                        errors.append(
                            f"{phase_path} must fall within its pandemic date range"
                        )
                    if phase.get("recoveryShape") not in {
                        "step",
                        "linear",
                        "ramp",
                        "triangle",
                    }:
                        errors.append(
                            f"{phase_path}.recoveryShape must be step, linear, "
                            "ramp or triangle"
                        )
                    for field in (
                        "demandMultiplier",
                        "trafficMultiplier",
                        "costMultiplier",
                        "leadTimeMultiplier",
                    ):
                        value = phase.get(field)
                        if (
                            not isinstance(value, (int, float))
                            or isinstance(value, bool)
                            or value <= 0
                        ):
                            errors.append(f"{phase_path}.{field} must be > 0")
                    _number_between(
                        phase.get("inventoryLossPct"),
                        f"{phase_path}.inventoryLossPct",
                        errors,
                        0,
                        1,
                    )
                    multiplier_targets = (
                        (
                            "departmentMultipliers",
                            department_ids,
                        ),
                        (
                            "categoryMultipliers",
                            category_ids,
                        ),
                        (
                            "channelTypeMultipliers",
                            SUPPORTED_CHANNEL_TYPES,
                        ),
                        (
                            "catalogFamilyMultipliers",
                            supported_families,
                        ),
                    )
                    for field, allowed in multiplier_targets:
                        values = phase.get(field)
                        if not isinstance(values, dict):
                            errors.append(f"{phase_path}.{field} must be an object")
                            continue
                        unknown = set(values).difference(allowed)
                        if unknown:
                            errors.append(
                                f"{phase_path}.{field} references unknown values "
                                f"{sorted(unknown)}"
                            )
                        for target, value in values.items():
                            if (
                                not isinstance(value, (int, float))
                                or isinstance(value, bool)
                                or value <= 0
                            ):
                                errors.append(
                                    f"{phase_path}.{field}.{target} must be > 0"
                                )

    operations = config.get("operations")
    if not isinstance(operations, dict):
        errors.append("operations must be an object")
        operations = {}
    inventory = operations.get("inventory")
    if not isinstance(inventory, dict):
        errors.append("operations.inventory must be an object")
        inventory = {}
    else:
        # Backward-compatible resolution for early configs authored before this
        # Config Builder control was exposed. New exports always carry it.
        inventory.setdefault("replenishmentDemandBufferPct", 0.05)
    for field in (
        "snapshotCadenceDays",
        "replenishmentCycleDays",
        "supplierLeadTimeDays",
    ):
        _positive_int(
            inventory.get(field),
            f"operations.inventory.{field}",
            errors,
        )
    for field in ("supplierLeadTimeJitterDays", "safetyStockUnits"):
        _positive_int(
            inventory.get(field),
            f"operations.inventory.{field}",
            errors,
            0,
        )
    _number_between(
        inventory.get("stockoutSkuRate"),
        "operations.inventory.stockoutSkuRate",
        errors,
        0,
        1,
    )
    _number_between(
        inventory.get("replenishmentDemandBufferPct"),
        "operations.inventory.replenishmentDemandBufferPct",
        errors,
        0,
        1,
    )
    fulfillment = operations.get("fulfillment")
    if not isinstance(fulfillment, dict):
        errors.append("operations.fulfillment must be an object")
        fulfillment = {}
    _number_between(
        fulfillment.get("splitRate"),
        "operations.fulfillment.splitRate",
        errors,
        0,
        1,
    )
    _positive_int(
        fulfillment.get("processingDelayHours"),
        "operations.fulfillment.processingDelayHours",
        errors,
        0,
    )
    returns = operations.get("returns")
    if not isinstance(returns, dict):
        errors.append("operations.returns must be an object")
        returns = {}
    for field in ("processingRate", "refundFailureRate"):
        _number_between(
            returns.get(field),
            f"operations.returns.{field}",
            errors,
            0,
            1,
        )
    supply = operations.get("supplyChain")
    if not isinstance(supply, dict):
        errors.append("operations.supplyChain must be an object")
        supply = {}
    for field in ("transferCycleDays", "weatherForecastHorizonDays"):
        _positive_int(
            supply.get(field),
            f"operations.supplyChain.{field}",
            errors,
        )
    for field in ("transferSkuRate", "wasteRate", "supplierDelayRate"):
        _number_between(
            supply.get(field),
            f"operations.supplyChain.{field}",
            errors,
            0,
            1,
        )
    webhook = operations.get("webhook")
    if not isinstance(webhook, dict):
        errors.append("operations.webhook must be an object")
        webhook = {}
    _required(webhook, "fixtureSecret", "operations.webhook", errors)
    _number_between(
        webhook.get("invalidFixtureRate"),
        "operations.webhook.invalidFixtureRate",
        errors,
        0,
        1,
    )
    features = operations.get("features")
    if not isinstance(features, dict):
        errors.append("operations.features must be an object")
        features = {}
    else:
        missing_features = SUPPORTED_FEATURES.difference(features)
        extra_features = set(features).difference(SUPPORTED_FEATURES)
        if missing_features:
            errors.append(f"operations.features is missing {sorted(missing_features)}")
        if extra_features:
            errors.append(
                f"operations.features contains unsupported values {sorted(extra_features)}"
            )
        for feature in sorted(SUPPORTED_FEATURES):
            if feature in features and not isinstance(features[feature], bool):
                errors.append(f"operations.features.{feature} must be boolean")

    output = config.get("output")
    if not isinstance(output, dict):
        errors.append("output must be an object")
        output = {}
    _required(output, "rootDirectory", "output", errors)
    formats = output.get("publicFormats")
    if formats not in (["csv", "duckdb"], ["parquet", "duckdb"]):
        errors.append(
            "output.publicFormats must be exactly ['csv', 'duckdb'] or "
            "['parquet', 'duckdb'] in source spec v12"
        )
    compression = output.get("compression")
    if compression not in SUPPORTED_COMPRESSION:
        errors.append(
            "output.compression must be one of 'none', 'snappy', or 'zstd'"
        )
    elif formats == ["csv", "duckdb"] and compression != "none":
        errors.append("CSV source output requires output.compression='none'")
    for field in ("writeHiddenTruth", "overwrite"):
        if not isinstance(output.get(field), bool):
            errors.append(f"output.{field} must be boolean")

    if errors:
        raise ConfigError(errors)
    return config


def load_config(path: str | Path) -> dict[str, Any]:
    """Load a conventional YAML config by default, or a JSON config explicitly."""

    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8")
    try:
        if config_path.suffix.lower() == ".json":
            raw = json.loads(text)
        else:
            raw = yaml.load(text, Loader=_ConfigYamlLoader)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        try:
            raw = (
                yaml.load(text, Loader=_ConfigYamlLoader)
                if config_path.suffix.lower() == ".json"
                else json.loads(text)
            )
        except (json.JSONDecodeError, yaml.YAMLError) as fallback_exc:
            raise ConfigError(
                [f"{config_path} is not valid YAML or JSON: {fallback_exc}"]
            ) from exc
    if not isinstance(raw, dict):
        raise ConfigError([f"{config_path} must contain a mapping/object at its root"])
    return validate_config(raw)
