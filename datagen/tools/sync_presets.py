#!/usr/bin/env python3
"""Synchronize checked-in YAML presets and config-builder embedded contracts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from retail_datagen import SOURCE_SPEC_VERSION
from retail_datagen.catalog_packs import CATALOG_PACK_METADATA, CATALOG_PACK_VERSION
from retail_datagen.config import _ConfigYamlLoader, load_config
from retail_datagen.hierarchy import default_departments
from retail_datagen.locale_packs import LOCALE_PACKS


ROOT = Path(__file__).resolve().parents[1]
PRESETS = {
    "showcasePreset": ROOT / "configs" / "multi-market-showcase.yaml",
    "historyPreset": ROOT / "configs" / "multi-market-20-year-history.yaml",
    "volumePreset": ROOT / "configs" / "multi-market-2021-current-volume.yaml",
}

LIFECYCLE = {
    "defaultLaunchProfile": "linear-ramp",
    "launchSpikeMultiplier": 4.0,
    "launchSpikeDays": 14,
    "launchSettleDays": 76,
    "preLaunchAnticipationDays": 45,
    "preLaunchDemandMultiplier": 0.55,
    "substitutionRate": 0.65,
    "runoutMonths": 18,
    "runoutDemandMultiplier": 0.35,
    "runoutMarkdownPct": 0.10,
    "runoutMarkdownDemandMultiplier": 1.08,
    "clearanceStartDaysAfterSuccessor": 120,
    "clearanceDiscountPct": 0.25,
    "clearanceDemandMultiplier": 1.35,
    "fireSaleFinalDays": 30,
    "fireSaleDiscountPct": 0.45,
    "fireSaleDemandMultiplier": 2.1,
}


def _migrate_category_references(value: Any) -> Any:
    """Carry legacy category scopes into the expanded hierarchy."""

    replacements = {"electronics-home": "home-appliances"}
    if isinstance(value, dict):
        return {
            replacements.get(key, key): _migrate_category_references(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_migrate_category_references(item) for item in value]
    if isinstance(value, str):
        return replacements.get(value, value)
    return value


def _product(
    *,
    product_id: str,
    market_id: str,
    product_code: str,
    title: str,
    brand: str,
    brand_code: str,
    description: str,
    category_id: str,
    price: str,
    cost: str,
    launch_date: str,
    predecessor: str = "",
) -> dict[str, Any]:
    if category_id == "electronics-mobile":
        storage_values = (
            ["256 GB", "512 GB", "1 TB"]
            if product_code.endswith("IPHONE17")
            else ["128 GB", "256 GB", "512 GB"]
        )
        variant_definitions = [
            {
                "optionValues": {
                    "color": color,
                    "storage": storage,
                }
            }
            for color, storage in zip(
                ["Black", "Blue", "White"],
                storage_values,
                strict=True,
            )
        ]
    elif product_code.endswith("IPADAIR4"):
        variant_definitions = [
            {"optionValues": {"storage": "64 GB", "connectivity": "Wi-Fi"}},
            {"optionValues": {"storage": "256 GB", "connectivity": "Wi-Fi"}},
            {
                "optionValues": {
                    "storage": "256 GB",
                    "connectivity": "Wi-Fi + Cellular",
                }
            },
        ]
    else:
        variant_definitions = [
            {"optionValues": {"storage": "128 GB", "connectivity": "Wi-Fi"}},
            {"optionValues": {"storage": "256 GB", "connectivity": "Wi-Fi"}},
            {"optionValues": {"storage": "512 GB", "connectivity": "Wi-Fi"}},
        ]
    return {
        "productId": product_id,
        "marketId": market_id,
        "productCode": product_code,
        "title": title,
        "brand": brand,
        "brandCode": brand_code,
        "description": description,
        "departmentId": "electronics",
        "categoryId": category_id,
        "basePrice": price,
        "baseCost": cost,
        "optionDimensions": (
            ["color", "storage"]
            if category_id == "electronics-mobile"
            else ["storage", "connectivity"]
        ),
        "variantDefinitions": variant_definitions,
        "launchDate": launch_date,
        "discontinueDate": "",
        "successorOfProductCode": predecessor,
        "launchProfile": "flagship-spike-decay",
        "variantLaunchSpreadDays": 0,
    }


def _real_lifecycle_templates(end_date: str) -> list[dict[str, Any]]:
    candidates = [
        _product(
            product_id="apple-iphone-13-in",
            market_id="india-mumbai",
            product_code="APL-IN-IPHONE13",
            title="Apple iPhone 13",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic India retail economics and demand.",
            category_id="electronics-mobile",
            price="79900.00",
            cost="61000.00",
            launch_date="2021-09-24",
        ),
        _product(
            product_id="apple-iphone-14-in",
            market_id="india-mumbai",
            product_code="APL-IN-IPHONE14",
            title="Apple iPhone 14",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic India retail economics and demand.",
            category_id="electronics-mobile",
            price="79900.00",
            cost="60500.00",
            launch_date="2022-09-16",
            predecessor="APL-IN-IPHONE13",
        ),
        _product(
            product_id="apple-iphone-15-in",
            market_id="india-mumbai",
            product_code="APL-IN-IPHONE15",
            title="Apple iPhone 15",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic India retail economics and demand.",
            category_id="electronics-mobile",
            price="79900.00",
            cost="59800.00",
            launch_date="2023-09-22",
            predecessor="APL-IN-IPHONE14",
        ),
        _product(
            product_id="apple-iphone-16-in",
            market_id="india-mumbai",
            product_code="APL-IN-IPHONE16",
            title="Apple iPhone 16",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic India retail economics and demand.",
            category_id="electronics-mobile",
            price="79900.00",
            cost="59200.00",
            launch_date="2024-09-20",
            predecessor="APL-IN-IPHONE15",
        ),
        _product(
            product_id="apple-iphone-17-in",
            market_id="india-mumbai",
            product_code="APL-IN-IPHONE17",
            title="Apple iPhone 17",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic India retail economics and demand.",
            category_id="electronics-mobile",
            price="82900.00",
            cost="61400.00",
            launch_date="2025-09-19",
            predecessor="APL-IN-IPHONE16",
        ),
        _product(
            product_id="apple-ipad-air-4-us",
            market_id="us-new-york",
            product_code="APL-US-IPADAIR4",
            title="Apple iPad Air (4th generation)",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic US retail economics and demand.",
            category_id="electronics-tablets",
            price="599.99",
            cost="455.00",
            launch_date="2020-10-23",
        ),
        _product(
            product_id="apple-ipad-air-m2-us",
            market_id="us-new-york",
            product_code="APL-US-IPADAIRM2",
            title="Apple iPad Air 11-inch (M2)",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic US retail economics and demand.",
            category_id="electronics-tablets",
            price="599.99",
            cost="452.00",
            launch_date="2024-05-15",
            predecessor="APL-US-IPADAIR4",
        ),
        _product(
            product_id="apple-ipad-air-m3-us",
            market_id="us-new-york",
            product_code="APL-US-IPADAIRM3",
            title="Apple iPad Air 11-inch (M3)",
            brand="Apple",
            brand_code="APL",
            description="Real Apple product identity; synthetic US retail economics and demand.",
            category_id="electronics-tablets",
            price="599.99",
            cost="448.00",
            launch_date="2025-03-12",
            predecessor="APL-US-IPADAIRM2",
        ),
    ]
    return [row for row in candidates if row["launchDate"] <= end_date]


def _sync_yaml(path: Path) -> None:
    config = _migrate_category_references(
        yaml.load(path.read_text(encoding="utf-8"), Loader=_ConfigYamlLoader)
    )
    config["specVersion"] = SOURCE_SPEC_VERSION
    generation = config["catalog"]["generation"]
    generation["catalogPackVersion"] = CATALOG_PACK_VERSION
    generation["lifecycle"] = LIFECYCLE.copy()
    config["catalog"]["departments"] = default_departments()
    for market in config["markets"]:
        market["catalogPack"] = CATALOG_PACK_METADATA[market["countryCode"]]
        market["localePack"] = LOCALE_PACKS[market["countryCode"]]
        market["assortment"]["skusPerDepartment"] = (
            12 if "20-year-history" in path.name else 36
        )
        if "multi-market-showcase" in path.name:
            market["demand"]["startingDailyOrders"] = 420
            market["priceDynamics"]["priceChangeEventsPerSkuPerYear"] = 36
        elif "2021-current-volume" in path.name:
            market["demand"]["startingDailyOrders"] = 420
            market["priceDynamics"]["priceChangeEventsPerSkuPerYear"] = 12
    for warehouse in config["warehouses"]:
        warehouse["openingStockDaysOfCover"] = 0
    config["operations"]["inventory"]["replenishmentDemandBufferPct"] = 0.05
    if "multi-market-showcase" in path.name:
        config["operations"]["inventory"]["replenishmentCycleDays"] = 7
        config["operations"]["inventory"]["stockoutSkuRate"] = 0
        config["operations"]["inventory"]["replenishmentDemandBufferPct"] = 0.20
        for warehouse in config["warehouses"]:
            warehouse["openingStockPerSku"] = (
                10 if "overflow" in warehouse["warehouseId"] else 18
            )
            warehouse["capacityUnits"] = (
                15_000 if "overflow" in warehouse["warehouseId"] else 45_000
            )
            warehouse["openingStockDaysOfCover"] = (
                0 if "overflow" in warehouse["warehouseId"] else 21
            )
    if "2021-current-volume" in path.name:
        config["operations"]["inventory"]["safetyStockUnits"] = 6
        config["operations"]["inventory"]["stockoutSkuRate"] = 0
        config["operations"]["inventory"]["replenishmentDemandBufferPct"] = 0.25
        for warehouse in config["warehouses"]:
            warehouse["openingStockPerSku"] = (
                24 if "overflow" in warehouse["warehouseId"] else 40
            )
            warehouse["replenishmentPackSize"] = (
                12 if "overflow" in warehouse["warehouseId"] else 24
            )
            warehouse["openingStockDaysOfCover"] = (
                0 if "overflow" in warehouse["warehouseId"] else 28
            )
    if generation["mode"] == "hybrid":
        config["catalog"]["productTemplates"] = _real_lifecycle_templates(
            config["time"]["endDate"]
        )
    path.write_text(
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )


def _replace_json_script(html: str, element_id: str, value: Any) -> str:
    payload = json.dumps(value, indent=2, ensure_ascii=False)
    pattern = re.compile(
        rf'(<script id="{re.escape(element_id)}" type="application/json">)\s*.*?\s*(</script>)',
        re.DOTALL,
    )
    replaced, count = pattern.subn(rf"\1\n{payload}\n\2", html, count=1)
    if count != 1:
        raise RuntimeError(f"could not find config-builder script {element_id}")
    return replaced


def main() -> None:
    for path in PRESETS.values():
        _sync_yaml(path)
    html_path = ROOT / "config-builder.html"
    html = html_path.read_text(encoding="utf-8")
    html = _replace_json_script(html, "localePacks", LOCALE_PACKS)
    html = _replace_json_script(html, "catalogPacks", CATALOG_PACK_METADATA)
    for element_id, path in PRESETS.items():
        html = _replace_json_script(html, element_id, load_config(path))
    html = re.sub(
        r"generator-owned contract · retail-source-config/v\d+",
        f"generator-owned contract · {SOURCE_SPEC_VERSION}",
        html,
    )
    html = re.sub(
        r'cfg\.specVersion!==\"[^\"]+\"',
        f'cfg.specVersion!=="{SOURCE_SPEC_VERSION}"',
        html,
    )
    html = re.sub(
        r"specVersion must be retail-source-config/v\d+",
        f"specVersion must be {SOURCE_SPEC_VERSION}",
        html,
    )
    html = re.sub(
        r'cfg\.catalog\.generation\.catalogPackVersion!==\"[^\"]+\"',
        (
            "cfg.catalog.generation.catalogPackVersion!=="
            f'"{CATALOG_PACK_VERSION}"'
        ),
        html,
    )
    html = re.sub(
        r"catalog pack version must be \d{4}\.\d+",
        f"catalog pack version must be {CATALOG_PACK_VERSION}",
        html,
    )
    html_path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
