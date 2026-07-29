from __future__ import annotations

import csv
import base64
import hashlib
import hmac
import io
import json
import re
import tempfile
import unittest
from copy import deepcopy
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from retail_execution import named_profiles, resolve_profile
from retail_datagen.catalog_packs import (
    CATALOG_PACK_METADATA,
    CATALOG_PACKS,
    _option_price_multiplier,
    barcode_is_valid,
    build_catalog,
)
from retail_datagen.config import ConfigError, load_config, validate_config
from retail_datagen.cli import main as cli_main
from retail_datagen.customers import CustomerPopulation
from retail_datagen.extensions import _allocate_tax_components
from retail_datagen.generator import _effective_list_price, generate
from retail_datagen.identity import (
    bc_uuid,
    shopify_gid,
    shopify_order_name,
)
from retail_datagen.locale_packs import LOCALE_PACKS
from retail_datagen.lifecycle import (
    lifecycle_adjustment,
    lifecycle_offer_id,
    lifecycle_promotions,
)
from retail_datagen.calendar import holidays_for_range
from retail_datagen.simulation import (
    _annual_price_schedule,
    _average_active_portfolio_weight,
    _channel_distribution,
    _holiday_demand_factor,
    _pandemic_effect,
    _portfolio_weight,
    _price_for_day,
    _promotional_price,
    _purchase_quantities,
    _recent_promotions,
    _seasonality_factor,
    _temperature,
)
from retail_datagen.spool import RowSpool
from retail_datagen.writer import SourceWriter

DATAGEN_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE = DATAGEN_ROOT / "configs" / "multi-market-showcase.yaml"
LONG_HISTORY = DATAGEN_ROOT / "configs" / "multi-market-20-year-history.yaml"
CURRENT_VOLUME = (
    DATAGEN_ROOT / "configs" / "multi-market-2021-current-volume.yaml"
)
DEMO_DECADE = DATAGEN_ROOT / "configs" / "multi-market-10-year-demo.yaml"


def dataset_rows(base: Path, logical_path: str) -> list[dict[str, str]]:
    stem = Path(logical_path).with_suffix("")
    direct_paths = [
        base / stem.with_suffix(".parquet"),
        base / stem.with_suffix(".csv"),
    ]
    paths = [path for path in direct_paths if path.is_file()]
    if not paths:
        dataset_root = base / stem
        paths = sorted(dataset_root.rglob("part.parquet"))
        if not paths:
            paths = sorted(dataset_root.rglob("part.csv"))
    rows: list[dict[str, str]] = []
    for path in paths:
        if path.suffix == ".csv":
            with path.open(encoding="utf-8", newline="") as handle:
                rows.extend(csv.DictReader(handle))
        else:
            relation = duckdb.connect()
            try:
                cursor = relation.execute(
                    "SELECT * FROM read_parquet(?)",
                    [str(path)],
                )
                columns = [item[0] for item in cursor.description]
                rows.extend(
                    dict(zip(columns, values, strict=True))
                    for values in cursor.fetchall()
                )
            finally:
                relation.close()
    return rows


def dataset_exists(base: Path, logical_path: str) -> bool:
    stem = Path(logical_path).with_suffix("")
    return any(
        (
            base / stem.with_suffix(f".{extension}")
        ).is_file()
        or any((base / stem).rglob(f"part.{extension}"))
        for extension in ("parquet", "csv")
    )


class ConfigTests(unittest.TestCase):
    def test_showcase_validates(self) -> None:
        config = load_config(SHOWCASE)
        self.assertEqual(config["output"]["publicFormats"], ["parquet", "duckdb"])
        self.assertEqual(config["output"]["compression"], "zstd")
        self.assertEqual(
            [market["countryCode"] for market in config["markets"]],
            ["IN", "US"],
        )
        self.assertEqual(config["stores"][0]["warehousePriority"], ["mumbai-dc", "pune-overflow"])
        factors_by_country = {
            market["countryCode"]: market["demand"]["dayOfWeekFactors"]
            for market in config["markets"]
        }
        self.assertEqual(
            {country: len(factors) for country, factors in factors_by_country.items()},
            {"IN": 7, "US": 7},
        )
        self.assertNotEqual(factors_by_country["IN"], factors_by_country["US"])
        self.assertEqual(
            {
                (
                    market["assortment"]["skusPerDepartment"],
                    market["demand"]["startingDailyOrders"],
                    market["priceDynamics"]["priceChangeEventsPerSkuPerYear"],
                )
                for market in config["markets"]
            },
            {(36, 420, 36)},
        )
        self.assertEqual(
            config["operations"]["inventory"]["replenishmentCycleDays"],
            7,
        )
        showcase_warehouses = {
            row["warehouseId"]: row for row in config["warehouses"]
        }
        self.assertEqual(
            showcase_warehouses["mumbai-dc"]["openingStockPerSku"],
            18,
        )
        self.assertEqual(
            showcase_warehouses["pune-overflow"]["openingStockPerSku"],
            10,
        )
        self.assertEqual(
            showcase_warehouses["newark-dc"]["openingStockPerSku"],
            18,
        )
        self.assertEqual(
            showcase_warehouses["mumbai-dc"]["openingStockDaysOfCover"],
            21,
        )
        self.assertEqual(
            showcase_warehouses["pune-overflow"]["openingStockDaysOfCover"],
            0,
        )
        self.assertEqual(
            showcase_warehouses["newark-dc"]["openingStockDaysOfCover"],
            21,
        )
        self.assertEqual(
            config["operations"]["inventory"]["stockoutSkuRate"],
            0,
        )
        self.assertEqual(
            config["operations"]["inventory"][
                "replenishmentDemandBufferPct"
            ],
            0.20,
        )
        self.assertTrue(
            all(
                "categoryAssortmentWeights" not in market["assortment"]
                for market in config["markets"]
            ),
            "uniform assortment must remain the omitted/default representation",
        )
        volume = load_config(CURRENT_VOLUME)
        self.assertEqual(
            {
                (
                    market["assortment"]["skusPerDepartment"],
                    market["demand"]["startingDailyOrders"],
                    market["priceDynamics"]["priceChangeEventsPerSkuPerYear"],
                )
                for market in volume["markets"]
            },
            {(36, 420, 12)},
        )
        volume_warehouses = {
            row["warehouseId"]: row for row in volume["warehouses"]
        }
        self.assertEqual(
            volume["operations"]["inventory"]["stockoutSkuRate"],
            0,
        )
        self.assertEqual(
            volume["operations"]["inventory"][
                "replenishmentDemandBufferPct"
            ],
            0.25,
        )
        self.assertEqual(
            volume_warehouses["mumbai-dc"]["openingStockDaysOfCover"],
            28,
        )
        self.assertEqual(
            volume_warehouses["pune-overflow"]["openingStockDaysOfCover"],
            0,
        )
        self.assertEqual(
            volume_warehouses["newark-dc"]["openingStockDaysOfCover"],
            28,
        )

    def test_country_controls_resolved_locale(self) -> None:
        config = load_config(SHOWCASE)
        config["markets"][0]["currencyCode"] = "USD"
        with self.assertRaises(ConfigError) as caught:
            validate_config(config)
        self.assertTrue(
            any("does not match country IN" in error for error in caught.exception.errors)
        )

    def test_category_assortment_weights_are_optional_and_validated(self) -> None:
        config = load_config(SHOWCASE)
        config["markets"][0]["assortment"]["categoryAssortmentWeights"] = {
            "grocery-staples": 5,
            "grocery-snacks": 0.5,
        }
        validated = validate_config(config)
        self.assertEqual(
            validated["markets"][0]["assortment"][
                "categoryAssortmentWeights"
            ],
            {"grocery-staples": 5, "grocery-snacks": 0.5},
        )

        config["markets"][0]["assortment"]["categoryAssortmentWeights"] = {
            "unknown-category": 1,
            "grocery-staples": 0,
        }
        with self.assertRaises(ConfigError) as caught:
            validate_config(config)
        self.assertTrue(
            any("unknown category" in error for error in caught.exception.errors)
        )
        self.assertTrue(
            any("must be a positive number" in error for error in caught.exception.errors)
        )

    def test_required_store_address_fails_validation_not_generation(self) -> None:
        config = load_config(SHOWCASE)
        del config["stores"][0]["addressLine1"]
        with self.assertRaises(ConfigError) as caught:
            validate_config(config)
        self.assertIn(
            "stores[0].addressLine1 is required",
            caught.exception.errors,
        )

    def test_generator_required_fields_fail_validation_not_generation(self) -> None:
        config = load_config(SHOWCASE)
        cases = (
            ("catalog.productTemplates", lambda row: row["catalog"].pop("productTemplates")),
            ("promotions[0].name", lambda row: row["promotions"][0].pop("name")),
            ("promotions[0].storeIds", lambda row: row["promotions"][0].pop("storeIds")),
            ("promotions[0].channelIds", lambda row: row["promotions"][0].pop("channelIds")),
            ("events[0].name", lambda row: row["events"][0].pop("name")),
            ("events[0].departmentIds", lambda row: row["events"][0].pop("departmentIds")),
            ("events[0].categoryIds", lambda row: row["events"][0].pop("categoryIds")),
            ("events[0].channelIds", lambda row: row["events"][0].pop("channelIds")),
        )
        for expected_path, mutate in cases:
            with self.subTest(expected_path=expected_path):
                candidate = deepcopy(config)
                mutate(candidate)
                with self.assertRaises(ConfigError) as caught:
                    validate_config(candidate)
                self.assertTrue(
                    any(
                        expected_path in error
                        for error in caught.exception.errors
                    ),
                    caught.exception.errors,
                )

    def test_all_locale_packs_define_tax_components_and_operational_defaults(self) -> None:
        for country, pack in LOCALE_PACKS.items():
            self.assertEqual(pack["version"], "2026.5")
            self.assertTrue(pack["tax"]["components"]["intraRegion"])
            self.assertTrue(pack["tax"]["components"]["interRegion"])
            for scope in ("intraRegion", "interRegion"):
                self.assertEqual(
                    sum(
                        Decimal(component["share"])
                        for component in pack["tax"]["components"][scope]
                    ),
                    Decimal("1.0"),
                    f"{country} {scope}",
                )
            expanded = holidays_for_range(pack, date(2005, 1, 1), date(2026, 12, 31))
            self.assertTrue(any(row["date"].startswith("2005-") for row in expanded))
            self.assertTrue(any(row["date"].startswith("2026-") for row in expanded))

    def test_long_history_preset_is_twenty_years_and_has_phased_pandemics(self) -> None:
        config = load_config(LONG_HISTORY)
        self.assertEqual(config["time"]["startDate"], "2005-01-01")
        self.assertEqual(config["time"]["endDate"], "2024-12-31")
        self.assertGreater(config["catalog"]["generation"]["incumbentProductPct"], 0)
        self.assertEqual(
            {row["pandemicId"] for row in config["pandemics"]},
            {
                "h1n1-2009",
                "ebola-2014",
                "zika-2016",
                "covid-19",
                "mpox-2022",
            },
        )
        self.assertGreaterEqual(
            sum(len(row["phases"]) for row in config["pandemics"]),
            9,
        )
        catalog = build_catalog(config)
        india_by_code = {
            row["productCode"]: row for row in catalog["india-mumbai"]
        }
        self.assertGreater(
            india_by_code["APL-IN-IPHONE13"]["discontinueDate"],
            india_by_code["APL-IN-IPHONE14"]["launchDate"],
        )
        self.assertEqual(
            india_by_code["APL-IN-IPHONE14"]["successorOfProductCode"],
            "APL-IN-IPHONE13",
        )
        self.assertEqual(
            [
                row["productCode"]
                for row in catalog["india-mumbai"]
                if row["successorOfProductCode"] == "APL-IN-IPHONE13"
            ],
            ["APL-IN-IPHONE14"],
        )
        self.assertEqual(
            {
                row["launchDate"]
                for row in india_by_code["APL-IN-IPHONE14"]["variants"]
            },
            {"2022-09-16"},
        )

    def test_demo_decade_preset_has_multistore_volume_and_disruptions(self) -> None:
        config = load_config(DEMO_DECADE)
        self.assertEqual(config["time"]["startDate"], "2016-07-28")
        self.assertEqual(config["time"]["endDate"], "2026-07-28")
        self.assertEqual(len(config["stores"]), 4)
        self.assertEqual(len(config["warehouses"]), 4)
        self.assertEqual(
            {market["demand"]["startingDailyOrders"] for market in config["markets"]},
            {1_200},
        )
        self.assertEqual(
            sum(
                market["demand"]["startingDailyOrders"]
                * sum(
                    store["demandScale"]
                    for store in config["stores"]
                    if store["marketId"] == market["marketId"]
                )
                for market in config["markets"]
            ),
            2400,
        )
        self.assertEqual(
            {row["pandemicId"] for row in config["pandemics"]},
            {"zika-2016", "covid-19", "mpox-2022"},
        )
        self.assertEqual(
            {
                row["marketId"]
                for row in config["events"]
                if row["eventId"].startswith("northstar-grand-opening-")
            },
            {"india-mumbai", "us-new-york"},
        )
        self.assertEqual(
            {
                warehouse["warehouseId"]: warehouse[
                    "openingStockDaysOfCover"
                ]
                for warehouse in config["warehouses"]
            },
            {
                "mumbai-dc": 42,
                "pune-overflow": 14,
                "newark-dc": 42,
                "brooklyn-mfc": 14,
            },
        )
        self.assertEqual(
            config["operations"]["inventory"]["stockoutSkuRate"],
            0.02,
        )

    def test_builder_locale_packs_match_python_contract(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        match = re.search(
            r'<script id="localePacks" type="application/json">\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), LOCALE_PACKS)

    def test_builder_catalog_packs_match_python_contract(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        match = re.search(
            r'<script id="catalogPacks" type="application/json">\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), CATALOG_PACK_METADATA)

    def test_builder_presets_match_checked_in_configs(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        for element_id, path in (
            ("showcasePreset", SHOWCASE),
            ("historyPreset", LONG_HISTORY),
            ("volumePreset", CURRENT_VOLUME),
            ("demoDecadePreset", DEMO_DECADE),
        ):
            match = re.search(
                rf'<script id="{element_id}" type="application/json">\s*(.*?)\s*</script>',
                html,
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            self.assertEqual(
                json.loads(match.group(1)),
                load_config(path),
            )

    def test_builder_execution_profiles_match_shared_contract(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        match = re.search(
            r'<script id="executionProfiles" type="application/json">\s*(.*?)\s*</script>',
            html,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        embedded = json.loads(match.group(1))
        expected = {
            profile_name: {
                "schemaVersion": "retail-execution-profile/v1",
                "profile": profile_name,
                "datagen": profile["datagen"],
            }
            for profile_name, profile in named_profiles().items()
        }
        self.assertEqual(embedded, expected)
        self.assertIn('id="downloadExecutionYaml"', html)
        self.assertIn("function executionYamlPayload()", html)
        self.assertIn(
            'if(next.schemaVersion==="retail-execution-profile/v1")',
            html,
        )
        self.assertIn(
            '["safe","balanced","performance","ultra-performance","custom"]',
            html,
        )

    def test_json_config_remains_supported(self) -> None:
        config = load_config(SHOWCASE)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scenario.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual(load_config(path), config)

    def test_builder_defaults_to_conventional_yaml_and_keeps_json(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        self.assertIn('class="button primary" id="downloadYaml"', html)
        self.assertIn('id="downloadJson"', html)
        self.assertIn('src="vendor/js-yaml.min.js"', html)
        self.assertIn("jsyaml.safeDump", html)
        self.assertIn("jsyaml.safeLoad", html)
        self.assertIn("let cfg = clone(DEMO_DECADE);", html)

    def test_builder_exposes_complete_catalog_and_lifecycle_contract(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        for path in (
            "catalog.generation.lifecycle.launchSpikeMultiplier",
            "catalog.generation.lifecycle.preLaunchAnticipationDays",
            "catalog.generation.lifecycle.substitutionRate",
            "catalog.generation.lifecycle.runoutMonths",
            "catalog.generation.lifecycle.clearanceDiscountPct",
            "catalog.generation.lifecycle.fireSaleDiscountPct",
            "catalog.productTemplates.${index}.launchProfile",
            "catalog.productTemplates.${index}.variantLaunchSpreadDays",
            "categoryAssortmentWeights",
            "demand.onlineShareStart",
            "demand.onlineShareEnd",
            "demand.onlineShareSkuVariation",
        ):
            self.assertIn(path, html)

    def test_builder_owns_customer_population_and_acquisition_controls(self) -> None:
        html = (DATAGEN_ROOT / "config-builder.html").read_text(encoding="utf-8")
        for field in (
            "openingRegisteredCustomers",
            "annualNewCustomers",
            "annualChurnRate",
            "annualReactivationRate",
            "guestCheckoutRate",
            "openingCustomerHistoryYears",
            "maxOrdersPerCustomerPerDay",
        ):
            self.assertIn(field, html)
        config = load_config(DEMO_DECADE)
        for market in config["markets"]:
            self.assertEqual(
                market["customerPopulation"]["openingRegisteredCustomers"],
                125_000,
            )
            self.assertEqual(
                market["customerPopulation"]["annualNewCustomers"],
                40_000,
            )

    def test_package_does_not_import_downstream_modules(self) -> None:
        banned = re.compile(r"^\s*(from|import)\s+(contracts|ingestion|ml|api)(\.|\s|$)")
        for path in (DATAGEN_ROOT / "src").rglob("*.py"):
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                self.assertIsNone(
                    banned.search(line),
                    f"downstream import in {path}:{line_number}",
                )


class IdentityTests(unittest.TestCase):
    def test_source_ids_are_stable_key_based(self) -> None:
        self.assertEqual(
            shopify_gid("Order", "store:2025-01-01:1"),
            shopify_gid("Order", "store:2025-01-01:1"),
        )
        self.assertNotEqual(
            shopify_gid("Order", "store:2025-01-01:1"),
            shopify_gid("Order", "store:2025-01-01:2"),
        )
        self.assertEqual(bc_uuid("Item", "sku-1"), bc_uuid("Item", "sku-1"))

    def test_high_volume_source_ids_and_order_names_do_not_collide(self) -> None:
        keys = (f"store:2025-01-01:order:{index:07d}" for index in range(100_000))
        gids: set[str] = set()
        names: set[str] = set()
        for source_sequence, key in enumerate(keys, start=1):
            gids.add(shopify_gid("Order", key))
            names.add(shopify_order_name(source_sequence))
        self.assertEqual(len(gids), 100_000)
        self.assertEqual(len(names), 100_000)
        self.assertEqual(shopify_order_name(1), "#1001")
        self.assertEqual(shopify_order_name(100_000), "#101000")


class DemandRealismTests(unittest.TestCase):
    def test_tax_component_allocation_reconciles_exactly(self) -> None:
        for country, total in (("IN", Decimal("53.39")), ("US", Decimal("8.87"))):
            components = LOCALE_PACKS[country]["tax"]["components"]["intraRegion"]
            allocations = _allocate_tax_components(total, components)
            self.assertEqual(sum(allocations, Decimal("0")), total)

    def test_annual_portfolio_denominator_removes_lifecycle_volume_ramp(self) -> None:
        variants = [
            {
                "_launchDate": "2025-01-01",
                "_discontinueDate": "2025-06-30",
                "_demandWeight": "1",
                "_catalogFamily": "toys-games",
            },
            {
                "_launchDate": "2025-07-01",
                "_discontinueDate": "",
                "_demandWeight": "1",
                "_catalogFamily": "toys-games",
            },
            {
                "_launchDate": "2025-01-01",
                "_discontinueDate": "",
                "_demandWeight": "2",
                "_catalogFamily": "toys-games",
            },
        ]
        period_start = date(2025, 1, 1)
        period_end = date(2025, 12, 31)
        denominator = _average_active_portfolio_weight(
            variants,
            period_start,
            period_end,
        )
        normalized_daily_totals = []
        for offset in range(365):
            day = period_start + timedelta(days=offset)
            normalized_daily_totals.append(
                sum(
                    (
                        _portfolio_weight(variant) / denominator
                        for variant in variants
                        if date.fromisoformat(variant["_launchDate"]) <= day
                        and (
                            not variant["_discontinueDate"]
                            or day
                            <= date.fromisoformat(
                                variant["_discontinueDate"]
                            )
                        )
                    ),
                    Decimal("0"),
                )
            )
        self.assertAlmostEqual(
            float(
                sum(normalized_daily_totals, Decimal("0"))
                / Decimal(365)
            ),
            1.0,
            places=12,
        )

    def test_retail_events_and_closed_holidays_have_opposite_effects(self) -> None:
        us_holidays = holidays_for_range(
            LOCALE_PACKS["US"],
            date(2025, 11, 27),
            date(2025, 12, 1),
        )
        self.assertEqual(
            {(row["date"], row["name"]) for row in us_holidays},
            {
                ("2025-11-27", "Thanksgiving"),
                ("2025-11-28", "Black Friday"),
                ("2025-12-01", "Cyber Monday"),
            },
        )
        self.assertLess(
            _holiday_demand_factor(
                [
                    {
                        "name": "Thanksgiving",
                        "retailBehavior": "closed",
                    }
                ],
                country_code="US",
                channel_type="store",
            ),
            Decimal("0.10"),
        )
        self.assertGreater(
            _holiday_demand_factor(
                [
                    {
                        "name": "Black Friday",
                        "retailBehavior": "retail-peak",
                    }
                ],
                country_code="US",
                channel_type="store",
            ),
            Decimal("3"),
        )
        christmas = holidays_for_range(
            LOCALE_PACKS["US"],
            date(2022, 12, 25),
            date(2022, 12, 26),
        )
        self.assertEqual(
            {
                row["name"]: row["retailBehavior"]
                for row in christmas
            },
            {
                "Christmas": "closed",
                "Christmas (observed)": "observance",
            },
        )
        german = holidays_for_range(
            LOCALE_PACKS["DE"],
            date(2025, 11, 28),
            date(2025, 12, 25),
        )
        self.assertIn(
            ("Black Friday", "retail-peak"),
            {
                (row["name"], row["retailBehavior"])
                for row in german
            },
        )
        self.assertIn(
            ("Erster Weihnachtstag", "closed"),
            {
                (row["name"], row["retailBehavior"])
                for row in german
            },
        )

    def test_seasonality_is_continuous_mean_one_and_peaks_in_december(self) -> None:
        year_start = date(2025, 1, 1)
        values = [
            (
                year_start + timedelta(days=offset),
                _seasonality_factor(
                    12,
                    Decimal("0.48"),
                    year_start + timedelta(days=offset),
                ),
            )
            for offset in range(365)
        ]
        self.assertAlmostEqual(
            float(sum((value for _, value in values), Decimal("0")) / 365),
            1.0,
            places=12,
        )
        monthly = {
            month: sum(
                (value for day, value in values if day.month == month),
                Decimal("0"),
            )
            / sum(1 for day, _ in values if day.month == month)
            for month in range(1, 13)
        }
        self.assertGreater(monthly[12], monthly[11] * Decimal("1.50"))
        self.assertLess(monthly[1], monthly[11] * Decimal("0.40"))
        daily_changes = [
            abs(later - earlier)
            for (_, earlier), (_, later) in zip(values, values[1:])
        ]
        self.assertLess(max(daily_changes), Decimal("0.45"))

    def test_price_changes_are_irregular_sticky_and_bounded(self) -> None:
        event_days, adjustments = _annual_price_schedule(
            "response-rich",
            12,
            "SKU-PRICE-001",
            2025,
            365,
            2020,
        )
        gaps = [
            later - earlier
            for earlier, later in zip(event_days, event_days[1:])
        ]
        self.assertGreater(len(set(gaps)), 2)
        self.assertTrue(
            all(
                Decimal("-0.08") <= Decimal(value) <= Decimal("0.12")
                for value in adjustments
            )
        )
        self.assertNotEqual(
            tuple(adjustments[:5]),
            ("-0.18", "-0.09", "0", "0.09", "0.18"),
        )
        _, next_adjustments = _annual_price_schedule(
            "response-rich",
            12,
            "SKU-PRICE-001",
            2026,
            365,
            2020,
        )
        self.assertEqual(next_adjustments[0], adjustments[-1])
        market = load_config(SHOWCASE)["markets"][1]
        december_price = _price_for_day(
            Decimal("100"),
            market,
            "SKU-PRICE-001",
            date(2025, 12, 31),
            date(2020, 1, 1),
            date(2026, 12, 31),
            inflation_anchor=date(2020, 1, 1),
        )
        january_price = _price_for_day(
            Decimal("100"),
            market,
            "SKU-PRICE-001",
            date(2026, 1, 1),
            date(2020, 1, 1),
            date(2026, 12, 31),
            inflation_anchor=date(2020, 1, 1),
        )
        self.assertGreater(january_price, december_price * Decimal("0.98"))

    def test_promotional_price_is_stable_and_respects_cost_floor(self) -> None:
        market = deepcopy(load_config(SHOWCASE)["markets"][1])
        market["priceDynamics"]["profile"] = "stable"
        variant = {
            "sku": "SKU-PROMO-001",
            "_baseCost": Decimal("70"),
            "_launchDate": "2024-01-01",
        }
        prices = {
            _promotional_price(
                Decimal("100"),
                variant,
                market,
                day,
                date(2025, 1, 1),
                date(2025, 12, 31),
                Decimal("0.50"),
                "fixed-window",
                "campaign",
            )
            for day in (
                date(2025, 11, 20),
                date(2025, 11, 24),
                date(2025, 11, 30),
            )
        }
        self.assertEqual(len(prices), 1)
        self.assertGreaterEqual(next(iter(prices)), Decimal("71.40"))
        self.assertLess(
            _promotional_price(
                Decimal("100"),
                variant,
                market,
                date(2025, 11, 24),
                date(2025, 1, 1),
                date(2025, 12, 31),
                Decimal("0.50"),
                "fire-sale",
                "fire-sale",
            ),
            Decimal("71.40"),
        )

    def test_disabled_promotion_signal_cannot_emit_phantom_payback(self) -> None:
        config = load_config(DEMO_DECADE)
        promotion = config["promotions"][0]
        market = next(
            row
            for row in config["markets"]
            if row["marketId"] == promotion["marketId"]
        )
        payback_day = date.fromisoformat(promotion["endDate"]) + timedelta(days=1)
        self.assertTrue(_recent_promotions(config, market, payback_day))
        market["signals"]["promotions"] = False
        self.assertEqual(_recent_promotions(config, market, payback_day), [])

    def test_channel_mix_is_persistent_and_responds_to_online_regimes(self) -> None:
        store = {
            "storeId": "store-1",
            "channelIds": ["online", "store"],
        }
        variant = {"sku": "SKU-CHANNEL-001"}
        channel_types = {"online": "online", "store": "store"}
        config = load_config(DEMO_DECADE)
        market = config["markets"][1]

        def distribution(day: date) -> dict[str, Decimal]:
            return dict(
                _channel_distribution(
                    2026,
                    store,
                    variant,
                    channel_types,
                    market,
                    day,
                    date.fromisoformat(config["time"]["startDate"]),
                    date.fromisoformat(config["time"]["endDate"]),
                )
            )

        opening = distribution(date.fromisoformat(config["time"]["startDate"]))
        closing = distribution(date.fromisoformat(config["time"]["endDate"]))
        self.assertEqual(sum(opening.values(), Decimal("0")), Decimal("1"))
        self.assertEqual(sum(closing.values(), Decimal("0")), Decimal("1"))
        self.assertTrue(all(weight > 0 for weight in opening.values()))
        self.assertLess(opening["online"], Decimal("0.15"))
        self.assertGreater(closing["online"], opening["online"] + Decimal("0.15"))
        shifted_online = _pandemic_effect(
            config,
            date(2020, 4, 15),
            "india-mumbai",
            channel_type="online",
        )["traffic"]
        shifted_store = _pandemic_effect(
            config,
            date(2020, 4, 15),
            "india-mumbai",
            channel_type="store",
        )["traffic"]
        self.assertGreater(
            shifted_online,
            shifted_store,
        )

    def test_weather_has_persistent_temperature_and_rain_spells(self) -> None:
        market = load_config(DEMO_DECADE)["markets"][0]
        days = [
            date(2024, 6, 1) + timedelta(days=offset)
            for offset in range(120)
        ]
        observations = [_temperature(2026, market, day) for day in days]
        temperatures = [float(row[0]) for row in observations]
        mean = sum(temperatures) / len(temperatures)
        numerator = sum(
            (left - mean) * (right - mean)
            for left, right in zip(temperatures, temperatures[1:])
        )
        denominator = sum((value - mean) ** 2 for value in temperatures)
        self.assertGreater(numerator / denominator, 0.70)
        wet = [row[1] > 0 for row in observations]
        self.assertTrue(
            any(
                wet[index] and wet[index + 1] and wet[index + 2]
                for index in range(len(wet) - 2)
            )
        )


class CustomerPopulationTests(unittest.TestCase):
    def test_population_grows_over_time_and_enforces_guest_and_daily_caps(self) -> None:
        config = deepcopy(load_config(SHOWCASE))
        start = date(2024, 1, 1)
        end = date(2025, 12, 31)
        population = CustomerPopulation(config, start, end)
        market_id = config["markets"][0]["marketId"]
        segment_id = config["customerSegments"][0]["segmentId"]
        allocations = [
            population.allocate(
                market_id,
                segment_id,
                start,
                f"order:{index:05d}",
            )
            for index in range(4_000)
        ]
        self.assertTrue(
            all(
                not key or date.fromisoformat(created) <= start
                for key, created in allocations
            )
        )
        assignments = [key for key, _ in allocations]
        guests = sum(not key for key in assignments)
        self.assertGreater(guests, 0)
        self.assertLess(guests, len(assignments))
        registered_counts: dict[str, int] = {}
        for key in assignments:
            if key:
                registered_counts[key] = registered_counts.get(key, 0) + 1
        self.assertLessEqual(
            max(registered_counts.values()),
            config["markets"][0]["customerPopulation"][
                "maxOrdersPerCustomerPerDay"
            ],
        )

        records = list(population.records([market_id]))
        registered = [
            row for row in records if row["segmentId"] != "walk-in"
        ]
        self.assertGreater(
            len(registered),
            config["markets"][0]["customerPopulation"][
                "openingRegisteredCustomers"
            ],
        )
        created_dates = {
            row["createdAt"][:10]
            for row in registered
        }
        self.assertLess(min(created_dates), start.isoformat())
        self.assertGreater(max(created_dates), start.isoformat())
        self.assertEqual(
            sum(row["segmentId"] == "walk-in" for row in records),
            1,
        )

    def test_row_spool_is_repeatable_and_deletes_private_work_state(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            spool = RowSpool(Path(root), "test", chunk_rows=7)
            same_name = RowSpool(Path(root), "test", chunk_rows=7)
            self.assertNotEqual(spool.path, same_name.path)
            expected = [{"value": index} for index in range(25)]
            spool.extend(expected)
            self.assertEqual(len(spool), 25)
            self.assertEqual(list(spool), expected)
            self.assertEqual(list(spool), expected)
            self.assertEqual(spool[-1], expected[-1])
            path = spool.path
            self.assertTrue(path.is_file())
            spool.close()
            self.assertFalse(path.exists())
            self.assertEqual(len(spool), 0)
            self.assertFalse(spool)
            with self.assertRaises(IndexError):
                _ = spool[-1]
            same_name.close()

    def test_row_spool_external_sort_is_bounded_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            spool = RowSpool(Path(root), "sort", chunk_rows=3)
            rows = [
                {"key": key, "sequence": sequence}
                for sequence, key in enumerate((9, 1, 7, 3, 8, 2, 6, 4, 5, 0))
            ]
            spool.extend(rows)
            self.assertEqual(
                list(spool.iter_sorted(key=lambda row: row["key"], max_open_runs=2)),
                sorted(rows, key=lambda row: row["key"]),
            )
            spool.close()


class CliAndWriterTests(unittest.TestCase):
    def test_plan_cli_accepts_the_same_execution_overrides_as_generate(self) -> None:
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            cli_main(
                [
                    "plan",
                    "-c",
                    str(SHOWCASE),
                    "--execution-profile",
                    "safe",
                    "--market-workers",
                    "1",
                    "--workers",
                    "3",
                    "--duckdb-threads",
                    "2",
                    "--memory-limit-gb",
                    "6",
                    "--spool-chunk-rows",
                    "12000",
                ]
            )
        self.assertEqual(
            json.loads(stdout.getvalue())["executionProfile"]["datagen"],
            {
                "marketWorkers": 1,
                "partitionWorkers": 3,
                "duckdbThreads": 2,
                "memoryLimitGb": 6.0,
                "spoolChunkRows": 12000,
            },
        )

    def test_cli_rejects_scenario_yaml_as_an_execution_profile(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as caught:
            cli_main(
                [
                    "plan",
                    "-c",
                    str(SHOWCASE),
                    "--execution-profile-file",
                    str(SHOWCASE),
                ]
            )
        self.assertEqual(caught.exception.code, 1)
        self.assertIn("unknown execution profile settings", stderr.getvalue())

    def test_streaming_writer_handles_many_and_blank_date_partitions(self) -> None:
        with tempfile.TemporaryDirectory() as output_root:
            writer = SourceWriter(
                output_root,
                "writer-test",
                "run-writer-test",
                generation_partition="day",
                source_format="csv",
                workers=2,
            )
            rows = [
                {
                    "id": str(offset),
                    "date": (
                        ""
                        if offset == 0
                        else (
                            date(2025, 1, 1) + timedelta(days=offset - 1)
                        ).isoformat()
                    ),
                }
                for offset in range(41)
            ]
            writer.write_dataset(
                "companion/test/events.csv",
                rows,
                source_system="companion",
                dataset="writerTestEvents",
                fieldnames=("id", "date"),
            )
            self.assertEqual(len(writer.objects), 41)
            self.assertTrue(
                any(
                    row["path"] == "companion/test/events.csv"
                    for row in writer.objects
                )
            )
            writer.abort()


class GenerationTests(unittest.TestCase):
    def _small_config(self) -> dict:
        config = deepcopy(load_config(SHOWCASE))
        config["identity"]["scenarioId"] = "test-multi-market"
        config["time"]["startDate"] = "2025-01-20"
        config["time"]["endDate"] = "2025-01-22"
        for market in config["markets"]:
            market["assortment"]["skusPerDepartment"] = 2
            market["demand"]["startingDailyOrders"] = 2
            market["demand"]["demandLevelScalar"] = 2.0
            market["demand"]["intermittencyRate"] = 0
            market["priceDynamics"]["priceChangeEventsPerSkuPerYear"] = 1
        return config

    def _executable_long_config(self) -> dict:
        config = deepcopy(load_config(LONG_HISTORY))
        target = "india-mumbai"
        config["identity"]["scenarioId"] = "test-20-year-history"
        config["retailer"]["reportingCurrency"] = "INR"
        config["markets"] = [
            row for row in config["markets"] if row["marketId"] == target
        ]
        market = config["markets"][0]
        market["fxRateToReporting"] = "1.000000000000000000"
        market["assortment"].update(
            skusPerDepartment=6,
            variantsPerProduct=1,
        )
        market["demand"].update(
            startingDailyOrders=1,
            demandLevelScalar=0.4,
            intermittencyRate=0.10,
        )
        market["priceDynamics"]["priceChangeEventsPerSkuPerYear"] = 2
        market["signals"].update(
            promotions=False,
            weather=False,
            localEvents=True,
            competitor=False,
            macro=True,
            fx=True,
        )
        config["legalEntities"] = [
            row for row in config["legalEntities"] if target in row["marketIds"]
        ]
        config["channels"] = [
            row for row in config["channels"] if row["marketId"] == target
        ]
        config["stores"] = [
            row for row in config["stores"] if row["marketId"] == target
        ]
        config["warehouses"] = [
            row for row in config["warehouses"] if row["marketId"] == target
        ]
        config["sourceInstances"]["shopify"] = [
            row
            for row in config["sourceInstances"]["shopify"]
            if row["marketId"] == target
        ]
        entity_ids = {
            row["legalEntityId"] for row in config["legalEntities"]
        }
        config["sourceInstances"]["businessCentral"] = [
            row
            for row in config["sourceInstances"]["businessCentral"]
            if row["legalEntityId"] in entity_ids
        ]
        config["catalog"]["productTemplates"] = [
            row
            for row in config["catalog"]["productTemplates"]
            if row["marketId"] == target
        ]
        config["promotions"] = [
            row for row in config["promotions"] if row["marketId"] == target
        ]
        config["events"] = [
            row for row in config["events"] if row["marketId"] == target
        ]
        for pandemic in config["pandemics"]:
            pandemic["marketIds"] = [target]
        config["operations"]["inventory"].update(
            snapshotCadenceDays=180,
            replenishmentCycleDays=180,
            supplierLeadTimeDays=14,
            supplierLeadTimeJitterDays=2,
        )
        config["operations"]["supplyChain"].update(
            transferCycleDays=365,
            transferSkuRate=0.10,
            wasteRate=0.01,
            weatherForecastHorizonDays=1,
        )
        config["operations"]["features"] = {
            key: False for key in config["operations"]["features"]
        }
        return validate_config(config)

    def test_rich_catalog_has_realistic_products_variants_and_barcodes(self) -> None:
        config = load_config(SHOWCASE)
        catalog = build_catalog(config)
        for market in config["markets"]:
            market_id = market["marketId"]
            products = catalog[market_id]
            variants = [
                variant for product in products for variant in product["variants"]
            ]
            expected_variants = (
                market["assortment"]["skusPerDepartment"]
                * len(config["catalog"]["departments"])
            )
            expected_products = (
                expected_variants
                // market["assortment"]["variantsPerProduct"]
            )
            self.assertEqual(len(products), expected_products)
            self.assertEqual(len(variants), expected_variants)
            self.assertEqual(
                len({product["title"] for product in products}),
                expected_products,
            )
            self.assertEqual(
                len({product["productCode"] for product in products}),
                expected_products,
            )
            self.assertEqual(
                len({variant["sku"] for variant in variants}),
                expected_variants,
            )
            self.assertTrue(
                all(
                    not re.fullmatch(r".+ (Apparel|Electronics) \d{3}", product["title"])
                    for product in products
                )
            )
            self.assertTrue(all(product["brand"] for product in products))
            self.assertTrue(all(product["description"] for product in products))
            self.assertTrue(all(variant["title"] != "Default" for variant in variants))
            self.assertTrue(all(barcode_is_valid(variant["barcode"]) for variant in variants))
            self.assertTrue(
                all(variant["baseCost"] < variant["basePrice"] for variant in variants)
            )
            represented_brands = {product["brand"] for product in products}
            brands_by_code: dict[str, set[str]] = {}
            for product in products:
                brands_by_code.setdefault(product["brandCode"], set()).add(
                    product["brand"]
                )
            self.assertTrue(
                all(len(names) == 1 for names in brands_by_code.values())
            )
            self.assertIn("Apple", represented_brands)
            self.assertIn("Nike", represented_brands)
            self.assertTrue(
                all(
                    brand and not brand.lower().startswith("synthetic")
                    for brand in represented_brands
                )
            )
            for family in {row["catalogFamily"] for row in products}:
                family_products = [
                    row for row in products if row["catalogFamily"] == family
                ]
                self.assertGreaterEqual(
                    len({row["brand"] for row in family_products}),
                    min(4, len(family_products)),
                )
            expected_length = (
                12 if CATALOG_PACKS[market["countryCode"]]["barcodeFormat"] == "UPCA" else 13
            )
            self.assertTrue(
                all(len(variant["barcode"]) == expected_length for variant in variants)
            )
            if market["countryCode"] == "US":
                self.assertTrue(
                    all(variant["barcode"].startswith("4") for variant in variants)
                )
            self.assertTrue(
                any(variant["unitOfMeasure"] != "EA" for variant in variants)
            )
            self.assertTrue(
                all(variant["measurementValue"] > 0 for variant in variants)
            )
            self.assertTrue(
                all(
                    variant["weight"] > 0
                    for variant in variants
                    if variant["measurementUnit"] in {"g", "kg", "ml", "l"}
                )
            )
            dairy_shelf_lives = {
                product["shelfLifeDays"]
                for product in products
                if product["catalogFamily"] == "grocery-dairy"
            }
            self.assertGreaterEqual(len(dairy_shelf_lives), 2)

    def test_category_assortment_weights_change_market_depth_only_when_set(
        self,
    ) -> None:
        config = load_config(SHOWCASE)
        market = config["markets"][0]
        market["assortment"]["categoryAssortmentWeights"] = {
            "grocery-staples": 5,
        }
        products = build_catalog(validate_config(config))[market["marketId"]]
        grocery_counts: dict[str, int] = {}
        for product in products:
            if product["departmentId"] == "groceries":
                grocery_counts[product["categoryId"]] = (
                    grocery_counts.get(product["categoryId"], 0)
                    + len(product["variants"])
                )
        self.assertEqual(
            sum(grocery_counts.values()),
            market["assortment"]["skusPerDepartment"],
        )
        self.assertGreater(
            grocery_counts["grocery-staples"],
            max(
                count
                for category_id, count in grocery_counts.items()
                if category_id != "grocery-staples"
            ),
        )

    def test_pack_pricing_and_grocery_purchase_frequency_are_not_unit_only(
        self,
    ) -> None:
        two_pack = _option_price_multiplier(
            [{"name": "packSize", "code": "2PK"}]
        )
        six_pack = _option_price_multiplier(
            [{"name": "packSize", "code": "6PK"}]
        )
        self.assertGreater(six_pack, two_pack)
        self.assertLess(
            six_pack / Decimal("6"),
            two_pack / Decimal("2"),
        )

        common = {"_demandWeight": Decimal("1")}
        dairy = {**common, "_catalogFamily": "grocery-dairy"}
        electronics = {**common, "_catalogFamily": "electronics-mobile"}
        self.assertGreater(
            _portfolio_weight(dairy),
            _portfolio_weight(electronics),
        )
        purchases = [
            quantity
            for index in range(100)
            for quantity in _purchase_quantities(
                20260101,
                f"dairy:{index}",
                dairy,
                12,
            )
        ]
        self.assertIn(1, purchases)
        self.assertTrue(any(quantity > 1 for quantity in purchases))

    def test_real_catalog_hierarchy_and_overlapping_flagship_lifecycle(self) -> None:
        config = load_config(CURRENT_VOLUME)
        self.assertGreaterEqual(len(config["catalog"]["departments"]), 10)
        self.assertGreaterEqual(
            sum(
                len(department["categories"])
                for department in config["catalog"]["departments"]
            ),
            40,
        )
        self.assertIn(
            "groceries",
            {row["departmentId"] for row in config["catalog"]["departments"]},
        )
        products = build_catalog(config)["india-mumbai"]
        by_code = {row["productCode"]: row for row in products}
        iphone_14 = by_code["APL-IN-IPHONE14"]
        iphone_15 = by_code["APL-IN-IPHONE15"]
        self.assertGreater(
            iphone_14["discontinueDate"],
            iphone_15["launchDate"],
        )
        old_variant = {
            **iphone_14["variants"][0],
            "_launchDate": iphone_14["variants"][0]["launchDate"],
            "_discontinueDate": iphone_14["variants"][0]["discontinueDate"],
            "_launchProfile": iphone_14["launchProfile"],
            "_lifecycle": iphone_14["lifecycle"],
            "_successorLaunchDate": iphone_14["successorLaunchDate"],
            "_predecessorProductCode": iphone_14["successorOfProductCode"],
            "_productCode": iphone_14["productCode"],
            "_productTitle": iphone_14["title"],
            "_departmentId": iphone_14["departmentId"],
            "_categoryId": iphone_14["categoryId"],
        }
        runout = lifecycle_adjustment(
            old_variant,
            date.fromisoformat(iphone_15["launchDate"]),
            90,
        )
        self.assertGreater(runout["predecessorFactor"], 0)
        self.assertLess(runout["predecessorFactor"], 1)
        self.assertEqual(runout["offerType"], "runout-markdown")
        self.assertGreater(runout["offerDiscountPct"], 0)
        offers = lifecycle_promotions(
            config,
            {"india-mumbai": [old_variant]},
        )
        self.assertEqual(
            {row["promotionType"] for row in offers},
            {"runout-markdown", "clearance", "fire-sale"},
        )
        self.assertTrue(
            all(row["_skus"] == [old_variant["sku"]] for row in offers)
        )
        self.assertEqual(
            runout["offerId"],
            lifecycle_offer_id(
                runout["offerType"],
                iphone_14["productCode"],
            ),
        )

    def test_flagship_option_matrices_prices_and_markdown_ladder_are_realistic(
        self,
    ) -> None:
        config = load_config(CURRENT_VOLUME)
        catalog = build_catalog(config)
        india = {
            row["productCode"]: row for row in catalog["india-mumbai"]
        }
        us = {
            row["productCode"]: row for row in catalog["us-new-york"]
        }

        def option_pairs(product: dict) -> set[tuple[tuple[str, str], ...]]:
            return {
                tuple((option["name"], option["value"]) for option in variant["options"])
                for variant in product["variants"]
            }

        self.assertEqual(
            option_pairs(india["APL-IN-IPHONE13"]),
            {
                (("color", "Black"), ("storage", "128 GB")),
                (("color", "Blue"), ("storage", "256 GB")),
                (("color", "White"), ("storage", "512 GB")),
            },
        )
        self.assertEqual(
            option_pairs(india["APL-IN-IPHONE17"]),
            {
                (("color", "Black"), ("storage", "256 GB")),
                (("color", "Blue"), ("storage", "512 GB")),
                (("color", "White"), ("storage", "1 TB")),
            },
        )
        self.assertNotIn(
            "Bluetooth",
            {
                option["value"]
                for product in us.values()
                if product["productCode"].startswith("APL-US-IPAD")
                for variant in product["variants"]
                for option in variant["options"]
            },
        )

        iphone_prices = [
            variant["basePrice"]
            for variant in india["APL-IN-IPHONE13"]["variants"]
        ]
        self.assertGreater(max(iphone_prices) / min(iphone_prices), Decimal("1.30"))
        ipad_air_4 = us["APL-US-IPADAIR4"]
        ipad_prices = {
            tuple(option["value"] for option in variant["options"]): variant["basePrice"]
            for variant in ipad_air_4["variants"]
        }
        self.assertGreater(
            ipad_prices[("256 GB", "Wi-Fi + Cellular")],
            ipad_prices[("256 GB", "Wi-Fi")] * Decimal("1.15"),
        )

        product = india["APL-IN-IPHONE14"]
        variant = {
            **product["variants"][0],
            "_basePrice": product["variants"][0]["basePrice"],
            "_launchDate": product["variants"][0]["launchDate"],
            "_discontinueDate": product["variants"][0]["discontinueDate"],
            "_successorLaunchDate": product["successorLaunchDate"],
            "_launchProfile": product["launchProfile"],
            "_lifecycle": product["lifecycle"],
            "_productCode": product["productCode"],
            "_productTitle": product["title"],
            "_predecessorProductCode": product["successorOfProductCode"],
        }
        market = next(
            row for row in config["markets"] if row["marketId"] == "india-mumbai"
        )
        start = date.fromisoformat(config["time"]["startDate"])
        end = date.fromisoformat(config["time"]["endDate"])
        successor = date.fromisoformat(product["successorLaunchDate"])
        discontinue = date.fromisoformat(product["discontinueDate"])
        runout = _effective_list_price(
            variant, market, successor, start, end
        )
        clearance = _effective_list_price(
            variant, market, successor + timedelta(days=150), start, end
        )
        fire_sale = _effective_list_price(
            variant, market, discontinue - timedelta(days=10), start, end
        )
        self.assertEqual(
            (runout[1], clearance[1], fire_sale[1]),
            ("runout-markdown", "clearance", "fire-sale"),
        )
        self.assertGreater(runout[0], clearance[0])
        self.assertGreater(clearance[0], fire_sale[0])

    def test_all_supported_country_catalog_packs_are_rich(self) -> None:
        self.assertEqual(set(CATALOG_PACKS), {"IN", "US", "GB", "DE"})
        for country, pack in CATALOG_PACKS.items():
            self.assertEqual(set(pack["families"]), set(CATALOG_PACK_METADATA[country]["familyIds"]))
            self.assertGreaterEqual(len(pack["brands"]), 6)
            for family in pack["families"].values():
                self.assertGreaterEqual(len(family["productNames"]), 4)
                self.assertGreaterEqual(len(family["materials"]), 1)
                self.assertTrue(family["optionDimensions"])
        self.assertNotEqual(
            CATALOG_PACKS["IN"]["families"]["grocery-dairy"]["productNames"],
            CATALOG_PACKS["US"]["families"]["grocery-dairy"]["productNames"],
        )
        self.assertNotEqual(
            CATALOG_PACKS["GB"]["families"]["grocery-staples"]["productNames"],
            CATALOG_PACKS["DE"]["families"]["grocery-staples"]["productNames"],
        )

    def test_all_supported_country_catalogs_generate_from_country_selection(self) -> None:
        base = load_config(SHOWCASE)
        postcodes = {
            "IN": "400050",
            "US": "10011",
            "GB": "SW1A 1AA",
            "DE": "10115",
        }
        for country in ("IN", "US", "GB", "DE"):
            config = deepcopy(base)
            market = config["markets"][0]
            market["countryCode"] = country
            market["currencyCode"] = LOCALE_PACKS[country]["currency"]["code"]
            market["timezone"] = LOCALE_PACKS[country]["timezones"][0]
            market["localePack"] = deepcopy(LOCALE_PACKS[country])
            market["catalogPack"] = deepcopy(CATALOG_PACK_METADATA[country])
            config["stores"][0]["postcode"] = postcodes[country]
            validated = validate_config(config)
            products = build_catalog(validated)[market["marketId"]]
            variants = [
                variant for product in products for variant in product["variants"]
            ]
            self.assertEqual(
                len(variants),
                market["assortment"]["skusPerDepartment"]
                * len(config["catalog"]["departments"]),
            )
            self.assertTrue(all(barcode_is_valid(row["barcode"]) for row in variants))
            self.assertTrue(
                all(
                    row["sku"].startswith(
                        f"{config['catalog']['generation']['skuPrefix']}-{country}-"
                    )
                    for row in variants
                )
            )

    def test_hybrid_catalog_respects_explicit_product_definition(self) -> None:
        config = self._small_config()
        config["catalog"]["generation"]["mode"] = "hybrid"
        config["catalog"]["productTemplates"] = [
            {
                "productId": "philips-airfryer",
                "marketId": "india-mumbai",
                "productCode": "PHL-IN-AIRFRYER",
                "title": "Philips Airfryer 3000 Series",
                "brand": "Philips",
                "brandCode": "PHL",
                "description": "Real product identity with synthetic retail economics.",
                "departmentId": "home",
                "categoryId": "home-appliances",
                "basePrice": "3499.00",
                "baseCost": "2140.00",
                "optionDimensions": ["color", "power"],
                "launchDate": "2024-10-01",
                "discontinueDate": "",
                "successorOfProductCode": "",
            }
        ]
        catalog = build_catalog(validate_config(config))
        product = next(
            row
            for row in catalog["india-mumbai"]
            if row["productKey"] == "philips-airfryer"
        )
        self.assertEqual(
            product["title"],
            "Philips Airfryer 3000 Series",
        )
        self.assertTrue(
            all(
                variant["sku"].startswith("PHL-IN-AIRFRYER-")
                for variant in product["variants"]
            )
        )
        self.assertTrue(
            all(barcode_is_valid(variant["barcode"]) for variant in product["variants"])
        )

    def test_generation_is_deterministic_and_source_shaped(self) -> None:
        config = self._small_config()
        with tempfile.TemporaryDirectory() as first_root, tempfile.TemporaryDirectory() as second_root:
            first = generate(config, first_root)
            second = generate(config, second_root)

            self.assertEqual(first["runId"], second["runId"])
            self.assertEqual(
                first["manifest"]["controlsByCurrency"],
                second["manifest"]["controlsByCurrency"],
            )
            first_objects = {
                row["path"]: row["sha256"]
                for row in first["manifest"]["objects"]
                if row["contentDeterminism"] == "byte"
            }
            second_objects = {
                row["path"]: row["sha256"]
                for row in second["manifest"]["objects"]
                if row["contentDeterminism"] == "byte"
            }
            self.assertEqual(first_objects, second_objects)
            first_duckdb = next(
                row
                for row in first["manifest"]["objects"]
                if row["dataset"] == "sourceRunDuckdb"
            )
            second_duckdb = next(
                row
                for row in second["manifest"]["objects"]
                if row["dataset"] == "sourceRunDuckdb"
            )
            self.assertEqual(
                first_duckdb["contentDeterminism"],
                second_duckdb["contentDeterminism"],
            )
            with (
                duckdb.connect(
                    str(Path(first["outputBase"]) / first_duckdb["path"]),
                    read_only=True,
                ) as first_connection,
                duckdb.connect(
                    str(Path(second["outputBase"]) / second_duckdb["path"]),
                    read_only=True,
                ) as second_connection,
            ):
                catalog_sql = (
                    "SELECT table_name, logical_path, source_system, dataset, "
                    "source_rows, partition_count, restricted "
                    "FROM source_dataset_catalog ORDER BY logical_path"
                )
                self.assertEqual(
                    first_connection.execute(catalog_sql).fetchall(),
                    second_connection.execute(catalog_sql).fetchall(),
                )

            first_base = Path(first["outputBase"])
            self.assertEqual(
                json.loads(
                    (first_base / "resolved-config.json").read_text(
                        encoding="utf-8"
                    )
                ),
                config,
            )

            self.assertEqual(
                load_config(first_base / "resolved-config.yaml"),
                config,
            )
            self.assertTrue(dataset_exists(first_base, "shopify/northstar-in/orders.csv"))
            self.assertTrue(
                (
                    first_base
                    / "business-central"
                    / "bc-northstar-us"
                    / "sales_invoices"
                ).is_dir()
            )
            self.assertTrue(
                dataset_exists(first_base, "companion/india-mumbai/fx_rates.csv")
            )
            self.assertTrue(dataset_exists(first_base, "_truth/demand_factors.csv"))
            self.assertTrue(dataset_exists(first_base, "_truth/catalog_truth.csv"))
            self.assertTrue(
                dataset_exists(
                    first_base,
                    "shopify/northstar-in/inventory_items.csv",
                )
            )
            self.assertTrue(
                dataset_exists(
                    first_base,
                    "business-central/bc-northstar-in/item_variants.csv",
                )
            )
            self.assertFalse((first_base / "retail.duckdb").exists())

            india_order = dataset_rows(first_base, "shopify/northstar-in/orders.csv")[0]
            us_order = dataset_rows(first_base, "shopify/northstar-us/orders.csv")[0]
            self.assertEqual(india_order["currencyCode"], "INR")
            self.assertEqual(india_order["taxesIncluded"], "true")
            self.assertEqual(us_order["currencyCode"], "USD")
            self.assertEqual(us_order["taxesIncluded"], "false")

            shopify_india = dataset_rows(first_base, "shopify/northstar-in/orders.csv")
            bc_india = dataset_rows(
                first_base,
                "business-central/bc-northstar-in/sales_invoices.csv",
            )
            self.assertEqual(len(shopify_india), len(bc_india))
            self.assertEqual(
                len({row["number"] for row in bc_india}),
                len(bc_india),
            )
            india_ledger_sales = {
                row["documentNumber"]
                for row in dataset_rows(
                    first_base,
                    "business-central/bc-northstar-in/item_ledger_entries.csv",
                )
                if row["entryType"] == "Sale"
            }
            self.assertLessEqual(
                india_ledger_sales,
                {row["number"] for row in bc_india},
            )
            self.assertEqual(
                sum(Decimal(row["totalPrice"]) for row in shopify_india),
                sum(Decimal(row["totalAmountIncludingTax"]) for row in bc_india),
            )
            all_shopify_orders = (
                shopify_india
                + dataset_rows(
                    first_base,
                    "shopify/northstar-us/orders.csv",
                )
            )
            source_numbers = sorted(
                int(row["name"][1:]) for row in all_shopify_orders
            )
            self.assertEqual(
                source_numbers,
                list(range(1001, 1001 + len(all_shopify_orders))),
            )
            shopify_variants = dataset_rows(
                first_base,
                "shopify/northstar-in/product_variants.csv",
            )
            shopify_products = dataset_rows(
                first_base,
                "shopify/northstar-in/products.csv",
            )
            self.assertTrue(
                all(
                    len((row["tags"] or "").split("|"))
                    == len(set((row["tags"] or "").split("|")))
                    for row in shopify_products
                )
            )
            self.assertTrue(
                any(Decimal(str(row["weight"])) > 0 for row in shopify_variants)
            )
            bc_variants = dataset_rows(
                first_base,
                "business-central/bc-northstar-in/item_variants.csv",
            )
            self.assertEqual(
                {row["sku"] for row in shopify_variants},
                {row["sku"] for row in bc_variants},
            )
            self.assertTrue(all(barcode_is_valid(row["barcode"]) for row in shopify_variants))

    def test_execution_profiles_preserve_authoritative_bytes(self) -> None:
        config = self._small_config()
        config["identity"]["scenarioId"] = "test-execution-profile-parity"
        config["time"]["endDate"] = config["time"]["startDate"]
        with (
            tempfile.TemporaryDirectory() as serial_root,
            tempfile.TemporaryDirectory() as parallel_root,
            tempfile.TemporaryDirectory() as ultra_root,
        ):
            serial = generate(
                config,
                serial_root,
                execution_profile=resolve_profile(
                    "safe",
                    datagen_overrides={"partitionWorkers": 1},
                    environment={},
                ),
            )
            parallel = generate(
                config,
                parallel_root,
                execution_profile=resolve_profile(
                    "performance",
                    datagen_overrides={
                        "memoryLimitGb": 8,
                        "partitionWorkers": 2,
                        "duckdbThreads": 2,
                        "spoolChunkRows": 1000,
                    },
                    environment={},
                ),
            )
            ultra = generate(
                config,
                ultra_root,
                execution_profile=resolve_profile(
                    "ultra-performance",
                    environment={},
                ),
            )
            self.assertEqual(serial["runId"], parallel["runId"])
            self.assertEqual(serial["runId"], ultra["runId"])
            serial_objects = {
                row["path"]: row["sha256"]
                for row in serial["manifest"]["objects"]
                if row["contentDeterminism"] == "byte"
            }
            parallel_objects = {
                row["path"]: row["sha256"]
                for row in parallel["manifest"]["objects"]
                if row["contentDeterminism"] == "byte"
            }
            ultra_objects = {
                row["path"]: row["sha256"]
                for row in ultra["manifest"]["objects"]
                if row["contentDeterminism"] == "byte"
            }
            self.assertEqual(serial_objects, parallel_objects)
            self.assertEqual(serial_objects, ultra_objects)
            self.assertEqual(
                serial["manifest"]["controlsByCurrency"],
                parallel["manifest"]["controlsByCurrency"],
            )
            self.assertEqual(
                serial["manifest"]["controlsByCurrency"],
                ultra["manifest"]["controlsByCurrency"],
            )
            self.assertEqual(
                1,
                serial["manifest"]["executionProfile"]["marketWorkers"],
            )
            self.assertEqual(
                2,
                parallel["manifest"]["executionProfile"]["marketWorkers"],
            )
            self.assertEqual(
                8,
                ultra["manifest"]["executionProfile"]["duckdbThreads"],
            )
            self.assertFalse(
                serial["manifest"]["executionProfile"]["affectsRunIdentity"]
            )
            self.assertGreater(
                serial["manifest"]["executionTelemetry"]["peakProcessRssBytes"],
                0,
            )

    def test_csv_is_retained_as_an_authoritative_output_option(self) -> None:
        config = self._small_config()
        config["identity"]["scenarioId"] = "test-csv-output"
        config["output"]["publicFormats"] = ["csv", "duckdb"]
        config["output"]["compression"] = "none"
        with tempfile.TemporaryDirectory() as output_root:
            result = generate(config, output_root)
            base = Path(result["outputBase"])
            source_objects = [
                row
                for row in result["manifest"]["objects"]
                if row["format"] in {"csv", "parquet"}
            ]
            self.assertTrue(source_objects)
            self.assertEqual({row["format"] for row in source_objects}, {"csv"})
            self.assertTrue(dataset_exists(base, "shopify/northstar-in/orders.csv"))
            self.assertTrue((base / "source-run.duckdb").is_file())

    def test_starting_daily_orders_controls_actual_order_headers(self) -> None:
        config = self._small_config()
        config["identity"]["scenarioId"] = "test-order-header-volume"
        config["time"]["startDate"] = "2025-02-01"
        config["time"]["endDate"] = "2025-02-01"
        for market in config["markets"]:
            market["demand"].update(
                startingDailyOrders=100,
                averageLinesPerOrder=1.8,
                demandLevelScalar=1,
                annualGrowthRate=0,
                noise=0,
                intermittencyRate=0,
            )
        for warehouse in config["warehouses"]:
            warehouse["openingStockPerSku"] = 500
            warehouse["replenishmentPackSize"] = 500
        with tempfile.TemporaryDirectory() as output_root:
            result = generate(config, output_root)
            base = Path(result["outputBase"])
            for shop_id in ("northstar-in", "northstar-us"):
                orders = dataset_rows(
                    base,
                    f"shopify/{shop_id}/orders.csv",
                )
                self.assertGreaterEqual(len(orders), 50)
                self.assertLessEqual(len(orders), 250)
                self.assertTrue(any(not row["customerId"] for row in orders))
                registered_daily_counts: dict[str, int] = {}
                for row in orders:
                    if row["customerId"]:
                        registered_daily_counts[row["customerId"]] = (
                            registered_daily_counts.get(row["customerId"], 0)
                            + 1
                        )
                self.assertLessEqual(max(registered_daily_counts.values()), 2)
                customers = dataset_rows(
                    base,
                    f"shopify/{shop_id}/customers.csv",
                )
                self.assertGreater(len(customers), 750)
                self.assertLess(
                    min(row["createdAt"][:10] for row in customers),
                    config["time"]["startDate"],
                )
                customer_ids = {row["id"] for row in customers}
                self.assertTrue(
                    all(
                        not row["customerId"]
                        or row["customerId"] in customer_ids
                        for row in orders
                    )
                )
            lines = dataset_rows(
                base,
                "shopify/northstar-in/order_lines.csv",
            )
            self.assertTrue(lines)
            self.assertIn("1", {row["quantity"] for row in lines})
            self.assertTrue(any(int(row["quantity"]) > 1 for row in lines))
            bc_customers = dataset_rows(
                base,
                "business-central/bc-northstar-in/customers.csv",
            )
            self.assertTrue(
                any(row["segmentCode"] == "walk-in" for row in bc_customers)
            )
            self.assertTrue(all(row["createdAt"] for row in bc_customers))

    def test_replenishment_bootstrap_does_not_use_latent_demand_floor(self) -> None:
        config = self._small_config()
        config["identity"]["scenarioId"] = "test-observed-replenishment-only"
        config["time"]["startDate"] = "2025-02-01"
        config["time"]["endDate"] = "2025-02-01"
        for market in config["markets"]:
            market["demand"].update(
                startingDailyOrders=10_000,
                demandLevelScalar=10,
                noise=0,
                intermittencyRate=0,
            )
        config["operations"]["inventory"].update(
            replenishmentCycleDays=1,
            stockoutSkuRate=1,
        )
        pack_by_location = {}
        for warehouse in config["warehouses"]:
            warehouse["openingStockPerSku"] = 0
            pack_by_location[
                warehouse["businessCentralLocationCode"]
            ] = warehouse["replenishmentPackSize"]

        with tempfile.TemporaryDirectory() as output_root:
            result = generate(config, output_root)
            base = Path(result["outputBase"])
            for shop in ("northstar-in", "northstar-us"):
                self.assertEqual(
                    dataset_rows(base, f"shopify/{shop}/orders.csv"),
                    [],
                )
                self.assertTrue(
                    dataset_exists(
                        base,
                        f"shopify/{shop}/fulfillment_order_lines.csv",
                    )
                )
            for company in ("bc-northstar-in", "bc-northstar-us"):
                po_lines = dataset_rows(
                    base,
                    f"business-central/{company}/purchase_order_lines.csv",
                )
                purchase_orders = {
                    row["id"]: row
                    for row in dataset_rows(
                        base,
                        f"business-central/{company}/purchase_orders.csv",
                    )
                }
                self.assertTrue(po_lines)
                self.assertTrue(
                    all(
                        int(row["orderedQuantity"])
                        == pack_by_location[
                            purchase_orders[row["documentId"]]["locationCode"]
                        ]
                        for row in po_lines
                    )
                )

    def test_existing_identical_run_is_reused(self) -> None:
        config = self._small_config()
        with tempfile.TemporaryDirectory() as output_root:
            first = generate(config, output_root)
            second = generate(config, output_root)
            self.assertFalse(first["reused"])
            self.assertTrue(second["reused"])
            self.assertEqual(first["manifest"], second["manifest"])

    def test_existing_run_is_reverified_before_reuse(self) -> None:
        config = self._small_config()
        config["identity"]["scenarioId"] = "test-corrupt-reuse"
        with tempfile.TemporaryDirectory() as output_root:
            first = generate(config, output_root)
            source_object = next(
                row
                for row in first["manifest"]["objects"]
                if row["format"] in {"csv", "parquet"}
            )
            object_path = Path(first["outputBase"]) / source_object["path"]
            object_path.write_bytes(object_path.read_bytes() + b"corrupt")
            with self.assertRaisesRegex(RuntimeError, "corrupt"):
                generate(config, output_root)

    def test_price_profile_and_nominal_inflation_are_separate(self) -> None:
        config = self._small_config()
        market = config["markets"][0]
        base = Decimal("1000")
        start = date(2021, 1, 1)
        rich = {
            **market,
            "priceDynamics": {
                **market["priceDynamics"],
                "profile": "response-rich",
                "annualInflationRate": 0.05,
                "priceChangeEventsPerSkuPerYear": 8,
            },
        }
        stable = {
            **rich,
            "priceDynamics": {
                **rich["priceDynamics"],
                "profile": "stable",
            },
        }
        rich_prices = {
            _price_for_day(
                base,
                rich,
                "SKU-1",
                start.replace(month=month),
                start,
                date(2021, 12, 31),
            )
            for month in range(1, 13)
        }
        stable_prices = {
            _price_for_day(
                base,
                stable,
                "SKU-1",
                start.replace(month=month),
                start,
                date(2021, 12, 31),
            )
            for month in range(1, 13)
        }
        self.assertGreater(len(rich_prices), len(stable_prices))
        self.assertEqual(len(stable_prices), 1)
        ending_base = Decimal("973.37")
        ending_prices = [
            _price_for_day(
                ending_base,
                rich,
                f"SKU-{index:04d}",
                date(2021, 7, 1),
                start,
                date(2021, 12, 31),
            )
            for index in range(500)
        ]
        configured_endings = set(market["localePack"]["currency"]["priceEndings"])
        ending_share = sum(
            f"{price:.2f}"[-2:] in configured_endings
            for price in ending_prices
        ) / len(ending_prices)
        self.assertGreater(ending_share, 0.75)
        self.assertLess(ending_share, 0.90)

    def test_twenty_year_generation_preserves_lifecycle_and_pandemic_evidence(
        self,
    ) -> None:
        config = self._executable_long_config()
        with tempfile.TemporaryDirectory() as output_root:
            result = generate(config, output_root)
            base = Path(result["outputBase"])
            self.assertEqual(
                [path.name for path in base.rglob("*.duckdb")],
                ["source-run.duckdb"],
            )

            catalog_events = dataset_rows(
                base,
                "shopify/northstar-in/catalog_events.csv",
            )
            introduced_years = {
                row["occurredAt"][:4]
                for row in catalog_events
                if row["eventType"] == "PRODUCT_INTRODUCED"
            }
            self.assertIn("2018", introduced_years)
            self.assertIn("2021", introduced_years)

            variants = dataset_rows(
                base,
                "shopify/northstar-in/product_variants.csv",
            )
            items = dataset_rows(
                base,
                "business-central/bc-northstar-in/items.csv",
            )
            self.assertTrue(all("vendorId" not in row for row in items))
            self.assertFalse(
                dataset_exists(
                    base,
                    "business-central/bc-northstar-in/vendors.csv",
                )
            )
            launch_by_sku = {row["sku"]: row["launchDate"] for row in variants}
            order_lines = dataset_rows(
                base,
                "shopify/northstar-in/order_lines.csv",
            )
            order_dates = {
                row["id"]: row["createdAt"][:10]
                for row in dataset_rows(
                    base,
                    "shopify/northstar-in/orders.csv",
                )
            }
            self.assertTrue(order_lines)
            self.assertTrue(
                all(
                    order_dates[row["orderId"]] >= launch_by_sku[row["sku"]]
                    for row in order_lines
                )
            )
            self.assertTrue(
                all("sourcePartitionDate" not in row for row in order_lines)
            )

            price_history = dataset_rows(
                base,
                "shopify/northstar-in/price_history.csv",
            )
            self.assertTrue(
                all(
                    row["effectiveDate"] >= launch_by_sku[row["sku"]]
                    for row in price_history
                )
            )
            self.assertLess(
                len(price_history),
                6 * len(config["catalog"]["departments"]) * 2 * 21 + 100,
            )

            demand_truth = dataset_rows(base, "_truth/demand_factors.csv")
            self.assertEqual(
                min(row["date"] for row in demand_truth),
                config["time"]["startDate"],
            )
            self.assertEqual(
                max(row["date"] for row in demand_truth),
                config["time"]["endDate"],
            )

            pandemic = dataset_rows(
                base,
                "companion/india-mumbai/pandemic_signals.csv",
            )
            pandemic_ids = {
                item
                for row in pandemic
                for item in row["pandemicIds"].split("|")
                if item
            }
            self.assertEqual(
                pandemic_ids,
                {
                    "h1n1-2009",
                    "ebola-2014",
                    "zika-2016",
                    "covid-19",
                    "mpox-2022",
                },
            )
            april_2020 = next(
                row for row in pandemic if row["validDate"] == "2020-04-10"
            )
            self.assertIn("covid-stockouts", april_2020["phaseIds"])
            self.assertIn("covid-lockdown-lifestyle", april_2020["phaseIds"])
            self.assertIn("covid-supply-disruption", april_2020["phaseIds"])
            self.assertNotEqual(april_2020["leadTimeMultiplier"], "1")
            neutral_ebola = next(
                row for row in pandemic if row["validDate"] == "2014-10-15"
            )
            self.assertEqual(neutral_ebola["effectModes"], "observed-no-adjustment")
            self.assertEqual(neutral_ebola["demandMultiplier"], "1")
            self.assertEqual(neutral_ebola["trafficMultiplier"], "1")
            self.assertEqual(neutral_ebola["costMultiplier"], "1")
            self.assertEqual(neutral_ebola["leadTimeMultiplier"], "1")

            pandemic_truth_factors = {
                row["pandemicDemandFactor"]
                for row in demand_truth
                if row["date"] == "2020-04-10"
            }
            self.assertGreaterEqual(
                len(pandemic_truth_factors),
                3,
                "department/catalog-family pandemic targeting must affect SKU truth",
            )

            connection = duckdb.connect(
                str(base / "source-run.duckdb"),
                read_only=True,
            )
            try:
                demand_catalog = connection.execute(
                    """
                    SELECT source_rows, partition_count
                    FROM source_dataset_catalog
                    WHERE logical_path = '_truth/demand_factors.parquet'
                    """
                ).fetchone()
                self.assertGreater(demand_catalog[0], 1_000)
                self.assertGreater(demand_catalog[1], 100)
            finally:
                connection.close()

    def test_complete_operational_evidence_and_single_duckdb_mirror(self) -> None:
        config = self._small_config()
        config["identity"]["scenarioId"] = "test-complete-operations"
        config["time"]["endDate"] = "2025-02-22"
        for market in config["markets"]:
            market["assortment"]["skusPerDepartment"] = 10
        config["operations"]["inventory"]["replenishmentCycleDays"] = 5
        config["operations"]["inventory"]["supplierLeadTimeDays"] = 2
        config["operations"]["inventory"]["supplierLeadTimeJitterDays"] = 1
        config["operations"]["inventory"]["stockoutSkuRate"] = 0.35
        config["operations"]["fulfillment"]["splitRate"] = 1
        config["operations"]["returns"]["refundFailureRate"] = 0.5
        config["operations"]["supplyChain"]["transferCycleDays"] = 5
        config["operations"]["supplyChain"]["transferSkuRate"] = 1
        config["operations"]["supplyChain"]["wasteRate"] = 1
        for warehouse in config["warehouses"]:
            if "overflow" in warehouse["warehouseId"]:
                # Exercise FEFO expiry with deliberate slow-moving overflow
                # stock while the main DC remains inventory-constrained.
                warehouse["openingStockPerSku"] = 200
        with tempfile.TemporaryDirectory() as output_root:
            result = generate(config, output_root)
            base = Path(result["outputBase"])

            duckdb_paths = list(base.rglob("*.duckdb"))
            self.assertEqual(
                [path.name for path in duckdb_paths],
                ["source-run.duckdb"],
            )
            connection = duckdb.connect(str(duckdb_paths[0]), read_only=True)
            try:
                source_objects = [
                    row
                    for row in result["manifest"]["objects"]
                    if row["format"] == config["output"]["publicFormats"][0]
                ]
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM source_object_catalog"
                    ).fetchone()[0],
                    len(source_objects),
                )
                orders_table = connection.execute(
                    """
                    SELECT table_name
                    FROM source_object_catalog
                    WHERE logical_path = 'shopify/northstar-in/orders.parquet'
                    """
                ).fetchone()[0]
                source_order_count = sum(
                    row["rows"]
                    for row in source_objects
                    if row["logicalPath"] == "shopify/northstar-in/orders.parquet"
                )
                self.assertEqual(
                    connection.execute(
                        f'SELECT COUNT(*) FROM "{orders_table}"'
                    ).fetchone()[0],
                    source_order_count,
                )
                self.assertGreater(
                    connection.execute(
                        "SELECT COUNT(*) FROM source_object_catalog WHERE restricted"
                    ).fetchone()[0],
                    0,
                )
                self.assertGreater(
                    connection.execute(
                        "SELECT COUNT(*) FROM source_schema"
                    ).fetchone()[0],
                    100,
                )
            finally:
                connection.close()

            demand = dataset_rows(base, "_truth/demand_factors.csv")
            grains = {
                (
                    row["marketKey"],
                    row["storeKey"],
                    row["channelId"],
                    row["date"],
                    row["sku"],
                )
                for row in demand
            }
            self.assertEqual(len(grains), len(demand))
            self.assertTrue(
                all(
                    int(row["latentDemandUnits"])
                    == int(row["realizedSalesUnits"]) + int(row["lostSalesUnits"])
                    for row in demand
                )
            )
            self.assertGreater(
                sum(int(row["lostSalesUnits"]) for row in demand),
                0,
            )
            promoted_demand = [
                row for row in demand if row["promotionIds"]
            ]
            self.assertTrue(promoted_demand)
            self.assertTrue(
                all(
                    abs(
                        Decimal(row["promotionFactor"])
                        * Decimal(row["promotionElasticityFactor"])
                        - Decimal(row["effectivePromotionLift"])
                    )
                    < Decimal("0.00000000000000000001")
                    for row in promoted_demand
                )
            )
            self.assertTrue(
                all(
                    Decimal(row["effectivePromotionLift"])
                    <= Decimal(row["configuredPromotionLift"])
                    for row in promoted_demand
                )
            )

            order_lines = dataset_rows(base, "shopify/northstar-in/order_lines.csv")
            self.assertTrue(
                all("sourcePartitionDate" not in row for row in order_lines)
            )
            self.assertEqual(
                len(order_lines),
                len({row["id"] for row in order_lines}),
            )
            order_line_counts: dict[str, int] = {}
            for row in order_lines:
                order_line_counts[row["orderId"]] = (
                    order_line_counts.get(row["orderId"], 0) + 1
                )
            self.assertTrue(any(count > 1 for count in order_line_counts.values()))

            fulfillments = dataset_rows(base, "shopify/northstar-in/fulfillments.csv")
            fulfillment_counts: dict[str, int] = {}
            for row in fulfillments:
                fulfillment_counts[row["orderId"]] = (
                    fulfillment_counts.get(row["orderId"], 0) + 1
                )
            self.assertTrue(any(count > 1 for count in fulfillment_counts.values()))
            statuses = {
                row["status"]
                for row in dataset_rows(
                    base,
                    "shopify/northstar-in/fulfillment_status_history.csv",
                )
            }
            self.assertEqual(
                statuses,
                {"SUBMITTED", "IN_PROGRESS", "DELIVERED", "CLOSED"},
            )

            refund_statuses = {
                row["status"]
                for row in dataset_rows(
                    base,
                    "shopify/northstar-in/refund_transactions.csv",
                )
            }
            self.assertEqual(refund_statuses, {"SUCCESS", "FAILURE"})

            secret = config["operations"]["webhook"]["fixtureSecret"].encode()
            fixtures = dataset_rows(
                base,
                "shopify/northstar-in/webhook_hmac_fixtures.csv",
            )
            self.assertEqual(
                {row["validExpected"] for row in fixtures},
                {"true", "false"},
            )
            for fixture in fixtures:
                expected = base64.b64encode(
                    hmac.new(
                        secret,
                        fixture["body"].encode(),
                        hashlib.sha256,
                    ).digest()
                ).decode()
                self.assertEqual(
                    hmac.compare_digest(expected, fixture["hmacHeader"]),
                    fixture["validExpected"] == "true",
                )
            order_names = {
                row["id"]: row["name"]
                for row in dataset_rows(
                    base,
                    "shopify/northstar-in/orders.csv",
                )
            }
            for fixture in fixtures:
                payload = json.loads(fixture["body"])
                self.assertEqual(payload["name"], order_names[payload["id"]])

            states = {
                row["name"]
                for row in dataset_rows(
                    base,
                    "shopify/northstar-in/inventory_quantities.csv",
                )
            }
            self.assertEqual(
                states,
                {
                    "on_hand",
                    "available",
                    "committed",
                    "reserved",
                    "damaged",
                    "quality_control",
                    "safety_stock",
                    "incoming",
                },
            )
            inventory_quantities = dataset_rows(
                base,
                "shopify/northstar-in/inventory_quantities.csv",
            )
            state_rows: dict[tuple[str, str, str], dict[str, int]] = {}
            for row in inventory_quantities:
                key = (
                    row["inventoryItemId"],
                    row["locationId"],
                    row["observedAt"],
                )
                state_rows.setdefault(key, {})[row["name"]] = int(row["quantity"])
            self.assertTrue(any(row["committed"] > 0 for row in state_rows.values()))
            self.assertTrue(all(row["reserved"] == 0 for row in state_rows.values()))
            self.assertTrue(
                all(
                    row["on_hand"]
                    == row["available"]
                    + row["committed"]
                    + row["reserved"]
                    + row["damaged"]
                    + row["quality_control"]
                    + row["safety_stock"]
                    for row in state_rows.values()
                )
            )
            latest_available = {
                (item_id, location_id): row["available"]
                for (item_id, location_id, observed_at), row in state_rows.items()
                if observed_at
                == max(
                    key[2]
                    for key in state_rows
                    if key[:2] == (item_id, location_id)
                )
            }
            inventory_levels = dataset_rows(
                base,
                "shopify/northstar-in/inventory_levels.csv",
            )
            self.assertTrue(
                all(
                    int(row["available"])
                    == latest_available[(row["inventoryItemId"], row["locationId"])]
                    for row in inventory_levels
                )
            )

            for shop, company in (
                ("northstar-in", "bc-northstar-in"),
                ("northstar-us", "bc-northstar-us"),
            ):
                expected_market = (
                    "india-mumbai" if shop == "northstar-in" else "us-new-york"
                )
                shop_orders = dataset_rows(
                    base,
                    f"shopify/{shop}/orders.csv",
                )
                self.assertEqual(
                    len(shop_orders),
                    len({row["id"] for row in shop_orders}),
                )
                self.assertEqual(
                    len(shop_orders),
                    len({row["name"] for row in shop_orders}),
                )
                shop_order_lines = dataset_rows(
                    base,
                    f"shopify/{shop}/order_lines.csv",
                )
                self.assertEqual(
                    len(shop_order_lines),
                    len({row["id"] for row in shop_order_lines}),
                )
                for dataset in (
                    "fulfillment_lines.csv",
                    "fulfillment_order_lines.csv",
                ):
                    rows = dataset_rows(base, f"shopify/{shop}/{dataset}")
                    self.assertEqual(
                        len(rows),
                        len({row["id"] for row in rows}),
                    )

                promotion_rows = dataset_rows(
                    base,
                    f"companion/{expected_market}/promotions.csv",
                )
                published_promotions = {
                    row["promotionId"] for row in promotion_rows
                }
                self.assertTrue(
                    all(
                        row["discountBasis"] == "planned-offer"
                        for row in promotion_rows
                    )
                )
                self.assertTrue(
                    all(
                        row["discountBasis"] == "planned-offer"
                        for row in dataset_rows(
                            base,
                            f"companion/{expected_market}/promotion_skus.csv",
                        )
                    )
                )
                lifecycle_promotion_rows = [
                    row
                    for row in promotion_rows
                    if row["promotionType"]
                    in {"runout-markdown", "clearance", "fire-sale"}
                ]
                self.assertTrue(
                    all(row["skus"] for row in lifecycle_promotion_rows)
                )
                referenced_promotions = {
                    promotion_id
                    for row in shop_order_lines
                    for promotion_id in (row.get("promotionIds") or "").split("|")
                    if promotion_id
                }
                self.assertTrue(
                    referenced_promotions.issubset(published_promotions)
                )
                return_lines = dataset_rows(
                    base,
                    f"shopify/{shop}/return_lines.csv",
                )
                self.assertTrue(
                    all(
                        row["restockType"] == "NO_RESTOCK"
                        and not row.get("restockLocationId")
                        for row in return_lines
                    )
                )

                variants = dataset_rows(
                    base,
                    f"shopify/{shop}/product_variants.csv",
                )
                sku_by_inventory_item = {
                    row["inventoryItemId"]: row["sku"] for row in variants
                }
                fulfillment_orders = {
                    row["id"]: row
                    for row in dataset_rows(
                        base,
                        f"shopify/{shop}/fulfillment_orders.csv",
                    )
                }
                fulfilled_at = {
                    row["fulfillmentOrderId"]: row["createdAt"]
                    for row in dataset_rows(
                        base,
                        f"shopify/{shop}/fulfillments.csv",
                    )
                }
                fulfillment_order_lines = dataset_rows(
                    base,
                    f"shopify/{shop}/fulfillment_order_lines.csv",
                )
                for state in dataset_rows(
                    base,
                    f"shopify/{shop}/inventory_quantities.csv",
                ):
                    if state["name"] != "committed":
                        continue
                    observed_at = state["observedAt"]
                    observed_date = observed_at[:10]
                    sku = sku_by_inventory_item[state["inventoryItemId"]]
                    expected_committed = sum(
                        int(line["totalQuantity"])
                        for line in fulfillment_order_lines
                        if line["sku"] == sku
                        and fulfillment_orders[line["fulfillmentOrderId"]][
                            "destinationLocationId"
                        ]
                        == state["locationId"]
                        and fulfillment_orders[line["fulfillmentOrderId"]][
                            "createdAt"
                        ][:10]
                        <= observed_date
                        and (
                            line["fulfillmentOrderId"] not in fulfilled_at
                            or fulfilled_at[line["fulfillmentOrderId"]][:10]
                            > observed_date
                        )
                    )
                    self.assertEqual(
                        int(state["quantity"]),
                        expected_committed,
                        (
                            shop,
                            observed_at,
                            state["locationId"],
                            sku,
                        ),
                    )

                open_fulfillment_order_ids = {
                    row["id"]
                    for row in dataset_rows(
                        base,
                        f"shopify/{shop}/fulfillment_orders.csv",
                    )
                    if row["status"] == "OPEN"
                }
                open_units = sum(
                    int(row["remainingQuantity"])
                    for row in dataset_rows(
                        base,
                        f"shopify/{shop}/fulfillment_order_lines.csv",
                    )
                    if row["fulfillmentOrderId"]
                    in open_fulfillment_order_ids
                )
                bc_snapshots = dataset_rows(
                    base,
                    f"business-central/{company}/inventory_snapshots.csv",
                )
                latest_observed_at = max(
                    row["observedAt"] for row in bc_snapshots
                )
                self.assertEqual(
                    sum(
                        int(row["committedInventory"])
                        for row in bc_snapshots
                        if row["observedAt"] == latest_observed_at
                    ),
                    open_units,
                )

            bc_dir = base / "business-central" / "bc-northstar-in"
            for filename in (
                "purchase_orders.csv",
                "warehouse_receipts.csv",
                "inbound_shipments.csv",
                "item_batches.csv",
                "item_cost_layers.csv",
                "transfer_orders.csv",
                "supplier_performance.csv",
                "supplier_capacity_confirmations.csv",
                "purchasing_budgets.csv",
                "warehouse_capacity.csv",
                "waste_events.csv",
                "wms_inventory_comparisons.csv",
            ):
                logical = f"business-central/bc-northstar-in/{filename}"
                self.assertTrue(dataset_exists(base, logical), filename)
                self.assertGreater(len(dataset_rows(base, logical)), 0, filename)
            self.assertFalse(
                dataset_exists(
                    base,
                    "business-central/bc-northstar-us/transfer_orders.csv",
                )
            )
            for company in ("bc-northstar-in", "bc-northstar-us"):
                vendors = dataset_rows(
                    base,
                    f"business-central/{company}/vendors.csv",
                )
                vendor_ids = {row["id"] for row in vendors}
                vendors_by_id = {row["id"]: row for row in vendors}
                self.assertTrue(vendor_ids)
                expected_market = (
                    "india-mumbai"
                    if company == "bc-northstar-in"
                    else "us-new-york"
                )
                expected_country = (
                    "IN" if company == "bc-northstar-in" else "US"
                )
                self.assertEqual(
                    {row["marketCode"] for row in vendors},
                    {expected_market},
                )
                self.assertTrue(
                    all(
                        row["displayName"].startswith(
                            "Synthetic Approved Distributor "
                        )
                        for row in vendors
                    )
                )
                items = dataset_rows(
                    base,
                    f"business-central/{company}/items.csv",
                )
                self.assertTrue(
                    all(row["vendorId"] in vendor_ids for row in items)
                )
                self.assertTrue(
                    all(
                        vendors_by_id[row["vendorId"]]["brandName"]
                        == row["brandName"]
                        for row in items
                    )
                )
                self.assertTrue(
                    all(
                        f"-{expected_country}-" in row["number"]
                        for row in items
                    )
                )
                purchase_orders = dataset_rows(
                    base,
                    f"business-central/{company}/purchase_orders.csv",
                )
                self.assertTrue(
                    all(row["vendorId"] in vendor_ids for row in purchase_orders)
                )
                po_lines = dataset_rows(
                    base,
                    f"business-central/{company}/purchase_order_lines.csv",
                )
                self.assertTrue(
                    all(
                        int(row["orderedQuantity"])
                        == int(row["receivedQuantity"])
                        + int(row["outstandingQuantity"])
                        for row in po_lines
                    )
                )
                items_by_number = {row["number"]: row for row in items}
                self.assertTrue(
                    all(
                        vendors_by_id[row["vendorId"]]["brandName"]
                        == items_by_number[row["itemNumber"]]["brandName"]
                        for row in po_lines
                    )
                )
                self.assertEqual(
                    len(po_lines),
                    len(
                        {
                            (row["documentId"], row["lineNumber"])
                            for row in po_lines
                        }
                    ),
                )
                ledger = dataset_rows(
                    base,
                    f"business-central/{company}/item_ledger_entries.csv",
                )
                self.assertIn("Positive Adjmt.", {row["entryType"] for row in ledger})
                self.assertIn("Purchase", {row["entryType"] for row in ledger})
                self.assertEqual(len(ledger), len({row["id"] for row in ledger}))
                self.assertEqual(
                    len(ledger),
                    len({row["entryNumber"] for row in ledger}),
                )
                ledger_by_entry = sorted(
                    ledger,
                    key=lambda row: int(row["entryNumber"]),
                )
                self.assertEqual(
                    [int(row["entryNumber"]) for row in ledger_by_entry],
                    list(range(1, len(ledger_by_entry) + 1)),
                )
                self.assertEqual(
                    [row["postingDate"] for row in ledger_by_entry],
                    sorted(row["postingDate"] for row in ledger_by_entry),
                )
                receipt_numbers = {
                    row["number"]
                    for row in dataset_rows(
                        base,
                        f"business-central/{company}/warehouse_receipts.csv",
                    )
                }
                self.assertTrue(
                    {
                        row["documentNumber"]
                        for row in ledger
                        if row["entryType"] == "Purchase"
                    }.issubset(receipt_numbers)
                )
                bc_customers = dataset_rows(
                    base,
                    f"business-central/{company}/customers.csv",
                )
                self.assertEqual(
                    len(bc_customers),
                    len({row["number"] for row in bc_customers}),
                )
                supplier_performance = dataset_rows(
                    base,
                    f"business-central/{company}/supplier_performance.csv",
                )
                self.assertTrue(
                    all(
                        int(row["orderedQuantity"])
                        >= int(row["receivedQuantity"])
                        for row in supplier_performance
                    )
                )
                snapshots = dataset_rows(
                    base,
                    f"business-central/{company}/inventory_snapshots.csv",
                )
                latest_snapshots: dict[tuple[str, str], dict[str, str]] = {}
                for row in snapshots:
                    key = (row["locationCode"], row["sku"])
                    if (
                        key not in latest_snapshots
                        or row["observedAt"]
                        > latest_snapshots[key]["observedAt"]
                    ):
                        latest_snapshots[key] = row
                ledger_balance: dict[tuple[str, str], int] = {}
                for row in ledger:
                    key = (row["locationCode"], row["sku"])
                    ledger_balance[key] = ledger_balance.get(key, 0) + int(
                        row["quantity"]
                    )
                self.assertTrue(
                    all(
                        int(row["inventory"]) == ledger_balance.get(key, 0)
                        for key, row in latest_snapshots.items()
                    )
                )

                running_balance: dict[tuple[str, str], int] = {}
                ledger_cursor = 0
                ledger_by_date = sorted(
                    ledger,
                    key=lambda row: (
                        row["postingDate"],
                        int(row["entryNumber"]),
                    ),
                )
                for snapshot in sorted(
                    snapshots,
                    key=lambda row: (
                        row["observedAt"],
                        row["locationCode"],
                        row["sku"],
                    ),
                ):
                    observed_date = snapshot["observedAt"][:10]
                    while (
                        ledger_cursor < len(ledger_by_date)
                        and ledger_by_date[ledger_cursor]["postingDate"]
                        <= observed_date
                    ):
                        entry = ledger_by_date[ledger_cursor]
                        key = (entry["locationCode"], entry["sku"])
                        running_balance[key] = (
                            running_balance.get(key, 0)
                            + int(entry["quantity"])
                        )
                        ledger_cursor += 1
                    key = (snapshot["locationCode"], snapshot["sku"])
                    self.assertEqual(
                        int(snapshot["inventory"]),
                        running_balance.get(key, 0),
                        (company, snapshot["observedAt"], key),
                    )

                company_warehouse_ids = {
                    warehouse["warehouseId"]
                    for warehouse in config["warehouses"]
                    if warehouse["businessCentralLocationCode"]
                    in {row["locationCode"] for row in snapshots}
                }
                location_by_warehouse = {
                    warehouse["warehouseId"]:
                    warehouse["businessCentralLocationCode"]
                    for warehouse in config["warehouses"]
                    if warehouse["warehouseId"] in company_warehouse_ids
                }
                batch_balance: dict[tuple[str, str], int] = {}
                for batch in dataset_rows(
                    base,
                    f"business-central/{company}/item_batches.csv",
                ):
                    self.assertEqual(
                        batch["locationCode"],
                        location_by_warehouse[batch["warehouseId"]],
                    )
                    key = (
                        batch["locationCode"],
                        batch["sku"],
                    )
                    batch_balance[key] = (
                        batch_balance.get(key, 0)
                        + int(batch["quantityRemainingAtExtract"])
                    )
                self.assertTrue(
                    all(
                        int(snapshot["inventory"])
                        == batch_balance.get(key, 0)
                        for key, snapshot in latest_snapshots.items()
                    )
                )

            waste_reasons = {
                row["reason"]
                for company in ("bc-northstar-in", "bc-northstar-us")
                for row in dataset_rows(
                    base,
                    f"business-central/{company}/waste_events.csv",
                )
            }
            self.assertIn("expired", waste_reasons)

            companion_dir = base / "companion" / "india-mumbai"
            for filename in (
                "weather_actuals.csv",
                "weather_forecasts.csv",
                "promotion_skus.csv",
                "competitor_matches.csv",
                "allocation_demand_requests.csv",
                "allocation_supply_pools.csv",
                "store_assortment.csv",
            ):
                self.assertTrue(
                    dataset_exists(base, f"companion/india-mumbai/{filename}"),
                    filename,
                )
            forecasts = dataset_rows(
                base,
                "companion/india-mumbai/weather_forecasts.csv",
            )
            actual_weather = {
                row["validDate"]: (
                    row["temperatureC"],
                    row["precipitationMm"],
                )
                for row in dataset_rows(
                    base,
                    "companion/india-mumbai/weather_actuals.csv",
                )
            }
            comparable = [
                row for row in forecasts if row["validDate"] in actual_weather
            ]
            differing = [
                row
                for row in comparable
                if (
                    row["temperatureC"],
                    row["precipitationMm"],
                )
                != actual_weather[row["validDate"]]
            ]
            self.assertGreater(
                len(differing) / len(comparable),
                0.80,
            )
            self.assertTrue((base / "source-schema.json").is_file())


if __name__ == "__main__":
    unittest.main()
