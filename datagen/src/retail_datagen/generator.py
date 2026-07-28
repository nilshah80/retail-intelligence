"""First causal multi-market source generation slice.

The simulation vocabulary is generator-owned. Public output is projected only
into Shopify-, Business Central-, and companion-shaped datasets.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from . import GENERATOR_VERSION
from .catalog_packs import build_catalog, catalog_controls
from .calendar import holidays_for_range
from .config import validate_config
from .extensions import (
    build_commerce_extensions,
    build_marketing_extensions,
    build_supply_extensions,
)
from .identity import (
    bc_uuid,
    config_hash,
    run_id,
    shopify_gid,
    shopify_order_name,
    stable_integer,
)
from .lifecycle import lifecycle_adjustment, lifecycle_promotions
from .writer import SourceWriter, file_sha256
from .simulation import _price_for_day, simulate

MONEY_QUANT = Decimal("0.01")


def _days(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN))


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower().replace("&", " and ")).strip("-")


def _iso_at(local_day: date, hour: int, timezone: str) -> str:
    local = datetime.combine(local_day, time(hour=hour), tzinfo=ZoneInfo(timezone))
    return local.isoformat()


def _allocation_amount(
    total: Decimal,
    allocations: list[dict[str, Any]],
    index: int,
) -> Decimal:
    total_quantity = sum(row["quantity"] for row in allocations)
    if index == len(allocations) - 1:
        prior = sum(
            (
                total
                * Decimal(row["quantity"])
                / Decimal(total_quantity)
            ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)
            for row in allocations[:index]
        )
        return total - prior
    return (
        total
        * Decimal(allocations[index]["quantity"])
        / Decimal(total_quantity)
    ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def _manifest_controls(
    order_events: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    controls: dict[str, dict[str, Any]] = {}
    seen_orders: dict[str, set[str]] = defaultdict(set)
    for event in order_events:
        currency = event["currencyCode"]
        control = controls.setdefault(
            currency,
            {
                "orders": 0,
                "units": 0,
                "netAmount": Decimal("0"),
                "taxAmount": Decimal("0"),
                "grossAmount": Decimal("0"),
            },
        )
        if event["orderKey"] not in seen_orders[currency]:
            control["orders"] += 1
            seen_orders[currency].add(event["orderKey"])
        control["units"] += event["quantity"]
        control["netAmount"] += event["net"]
        control["taxAmount"] += event["tax"]
        control["grossAmount"] += event["gross"]
    return {
        currency: {
            **values,
            "netAmount": _money(values["netAmount"]),
            "taxAmount": _money(values["taxAmount"]),
            "grossAmount": _money(values["grossAmount"]),
        }
        for currency, values in sorted(controls.items())
    }


def _bc_item_ledger_rows(
    company_warehouse_ids: set[str],
    company_orders: list[dict[str, Any]],
    warehouses: dict[str, dict[str, Any]],
    variants_by_market: dict[str, list[dict[str, Any]]],
    simulation: dict[str, Any],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Project every simulated inventory movement into one BC register."""

    variants_by_sku = {
        variant["sku"]: variant
        for warehouse_id in company_warehouse_ids
        for variant in variants_by_market[warehouses[warehouse_id]["marketId"]]
    }
    rows: list[dict[str, Any]] = []

    def append(
        *,
        business_key: str,
        posting_date: str,
        entry_type: str,
        sku: str,
        warehouse_id: str,
        quantity: int,
        document_number: str,
        product_code: str | None = None,
        variant_code: str | None = None,
    ) -> None:
        if quantity == 0:
            return
        variant = variants_by_sku[sku]
        rows.append(
            {
                "id": bc_uuid("ItemLedgerEntry", business_key),
                "postingDate": posting_date,
                "entryType": entry_type,
                "itemNumber": product_code or variant["_productCode"],
                "variantCode": variant_code or variant["_variantCode"],
                "sku": sku,
                "locationCode": warehouses[warehouse_id][
                    "businessCentralLocationCode"
                ],
                "quantity": quantity,
                "documentNumber": document_number,
            }
        )

    for (warehouse_id, sku), quantity in simulation["openingInventory"].items():
        if warehouse_id in company_warehouse_ids:
            append(
                business_key=f"opening:{warehouse_id}:{sku}:{start}",
                posting_date=start.isoformat(),
                entry_type="Positive Adjmt.",
                sku=sku,
                warehouse_id=warehouse_id,
                quantity=quantity,
                document_number=(
                    f"OPEN-{stable_integer(warehouse_id, sku, start, modulo=99_999_999):08d}"
                ),
            )
    for receipt in simulation["receiptEvents"]:
        if (
            receipt["warehouseId"] in company_warehouse_ids
            and date.fromisoformat(receipt["actualDate"]) <= end
        ):
            append(
                business_key=f"purchase:{receipt['receiptKey']}",
                posting_date=receipt["actualDate"],
                entry_type="Purchase",
                sku=receipt["sku"],
                warehouse_id=receipt["warehouseId"],
                quantity=receipt["quantity"],
                document_number=(
                    f"WR-{stable_integer(receipt['warehouseId'], receipt['actualDate'], modulo=99_999_999):08d}"
                ),
                product_code=receipt["productCode"],
                variant_code=receipt["variantCode"],
            )
    for transfer in simulation["transferEvents"]:
        if transfer["fromWarehouseId"] in company_warehouse_ids:
            append(
                business_key=f"transfer-out:{transfer['transferKey']}",
                posting_date=transfer["shipmentDate"],
                entry_type="Transfer",
                sku=transfer["sku"],
                warehouse_id=transfer["fromWarehouseId"],
                quantity=-transfer["shippedQuantity"],
                document_number=(
                    f"TO-{stable_integer(transfer['transferKey'], modulo=99_999_999):08d}"
                ),
                product_code=transfer["productCode"],
                variant_code=transfer["variantCode"],
            )
        if (
            transfer["toWarehouseId"] in company_warehouse_ids
            and transfer["receivedQuantity"]
        ):
            append(
                business_key=f"transfer-in:{transfer['transferKey']}",
                posting_date=transfer["receiptDate"],
                entry_type="Transfer",
                sku=transfer["sku"],
                warehouse_id=transfer["toWarehouseId"],
                quantity=transfer["receivedQuantity"],
                document_number=(
                    f"TO-{stable_integer(transfer['transferKey'], modulo=99_999_999):08d}"
                ),
                product_code=transfer["productCode"],
                variant_code=transfer["variantCode"],
            )
    for event in company_orders:
        for allocation in event["allocations"]:
            if allocation["warehouseId"] not in company_warehouse_ids:
                continue
            fulfilled_at = allocation.get("fulfillmentCreatedAt", "")
            if not fulfilled_at or date.fromisoformat(fulfilled_at[:10]) > end:
                continue
            append(
                business_key=(
                    f"sale:{event['lineKey']}:{allocation['warehouseId']}"
                ),
                posting_date=fulfilled_at[:10],
                entry_type="Sale",
                sku=event["sku"],
                warehouse_id=allocation["warehouseId"],
                quantity=-allocation["quantity"],
                document_number=(
                    f"SI-{stable_integer(event['orderKey'], modulo=99_999_999):08d}"
                ),
                product_code=event["productCode"],
                variant_code=event["variantCode"],
            )
    for loss in simulation["inventoryLossEvents"]:
        if loss["warehouseId"] in company_warehouse_ids:
            append(
                business_key=(
                    f"inventory-loss:{loss['warehouseId']}:"
                    f"{loss['sku']}:{loss['eventDate']}"
                ),
                posting_date=loss["eventDate"],
                entry_type="Negative Adjmt.",
                sku=loss["sku"],
                warehouse_id=loss["warehouseId"],
                quantity=-loss["lostQuantity"],
                document_number=(
                    f"LOSS-{stable_integer(loss['causeIds'], loss['eventDate'], modulo=99_999_999):08d}"
                ),
                product_code=loss["productCode"],
                variant_code=loss["variantCode"],
            )
    for waste in simulation["wasteEvents"]:
        if waste["warehouseId"] in company_warehouse_ids:
            append(
                business_key=f"waste:{waste['wasteEventKey']}",
                posting_date=waste["eventDate"],
                entry_type="Negative Adjmt.",
                sku=waste["sku"],
                warehouse_id=waste["warehouseId"],
                quantity=-waste["quantity"],
                document_number=(
                    f"WASTE-{stable_integer(waste['wasteEventKey'], modulo=99_999_999):08d}"
                ),
                product_code=waste["productCode"],
                variant_code=waste["variantCode"],
            )
    rows.sort(
        key=lambda row: (
            row["postingDate"],
            row["locationCode"],
            row["sku"],
            row["entryType"],
            row["id"],
        )
    )
    for entry_number, row in enumerate(rows, start=1):
        row["entryNumber"] = entry_number
    return rows


def _price_history_rows(
    variants: list[dict[str, Any]],
    market: dict[str, Any],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Emit effective-dated changes, including each SKU's first active price."""

    rows: list[dict[str, Any]] = []
    for variant in variants:
        launch = max(start, date.fromisoformat(variant["_launchDate"]))
        discontinue = (
            min(end, date.fromisoformat(variant["_discontinueDate"]))
            if variant["_discontinueDate"]
            else end
        )
        prior: Decimal | None = None
        for day in _days(launch, discontinue):
            price, lifecycle_phase = _effective_list_price(
                variant,
                market,
                day,
                start,
                end,
            )
            if price == prior:
                continue
            rows.append(
                {
                    "variantId": variant["id"],
                    "sku": variant["sku"],
                    "effectiveDate": day.isoformat(),
                    "price": _money(price),
                    "currencyCode": market["currencyCode"],
                    "priceList": "market-retail",
                    "priceReason": lifecycle_phase or "regular",
                }
            )
            prior = price
    return rows


def _variant_extract_price(
    variant: dict[str, Any],
    market: dict[str, Any],
    start: date,
    end: date,
    product: dict[str, Any] | None = None,
) -> Decimal:
    effective_day = (
        min(end, date.fromisoformat(variant["discontinueDate"]))
        if variant.get("discontinueDate")
        else end
    )
    enriched = (
        variant
        if "_basePrice" in variant
        else {
            **variant,
            "_basePrice": variant["basePrice"],
            "_launchDate": variant["launchDate"],
            "_discontinueDate": variant.get("discontinueDate", ""),
            "_successorLaunchDate": (
                product.get("successorLaunchDate", "") if product else ""
            ),
            "_launchProfile": (
                product.get("launchProfile", "linear-ramp")
                if product
                else "linear-ramp"
            ),
            "_lifecycle": (
                product.get("lifecycle", {}) if product else {}
            ),
            "_productCode": (
                product.get("productCode", variant["sku"]) if product else variant["sku"]
            ),
            "_productTitle": (
                product.get("title", variant["sku"]) if product else variant["sku"]
            ),
            "_predecessorProductCode": (
                product.get("successorOfProductCode", "") if product else ""
            ),
        }
    )
    return _effective_list_price(
        enriched,
        market,
        effective_day,
        start,
        end,
    )[0]


def _effective_list_price(
    variant: dict[str, Any],
    market: dict[str, Any],
    day: date,
    start: date,
    end: date,
) -> tuple[Decimal, str]:
    """Return the effective list price and lifecycle reason for one day."""

    successor_text = variant.get("_successorLaunchDate", "")
    pricing_day = (
        min(day, date.fromisoformat(successor_text))
        if successor_text
        else day
    )
    price = _price_for_day(
        variant["_basePrice"],
        market,
        variant["sku"],
        pricing_day,
        start,
        end,
        inflation_anchor=date.fromisoformat(variant["_launchDate"]),
    )
    lifecycle_phase = ""
    if successor_text:
        effect = lifecycle_adjustment(
            variant,
            day,
            market["demand"]["newProductRampDays"],
        )
        if effect["offerId"]:
            price *= Decimal("1") - effect["offerDiscountPct"]
            lifecycle_phase = effect["offerType"]
    return (
        price.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN),
        lifecycle_phase,
    )


def generate(config: dict[str, Any], output_root: str | None = None) -> dict[str, Any]:
    """Generate and atomically publish one deterministic source run."""

    config = validate_config(config)
    config_digest = config_hash(config)
    resolved_run_id = run_id(config, GENERATOR_VERSION)
    root = output_root or config["output"]["rootDirectory"]
    writer = SourceWriter(
        root,
        config["identity"]["scenarioId"],
        resolved_run_id,
        overwrite=config["output"]["overwrite"],
        generation_partition=config["time"]["generationPartition"],
        source_format=config["output"]["publicFormats"][0],
        compression=config["output"]["compression"],
    )
    if writer.reused:
        manifest_path = writer.target / "source-run-manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError(f"existing run is incomplete: {writer.target}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("configHash") != config_digest:
            raise RuntimeError(f"run identity collision at {writer.target}")
        for source_object in manifest.get("objects", []):
            object_path = writer.target / source_object["path"]
            if not object_path.is_file():
                raise RuntimeError(
                    f"existing run is incomplete; missing {source_object['path']}"
                )
            if object_path.stat().st_size != source_object["bytes"]:
                raise RuntimeError(
                    f"existing run is corrupt; byte count differs for "
                    f"{source_object['path']}"
                )
            if file_sha256(object_path) != source_object["sha256"]:
                raise RuntimeError(
                    f"existing run is corrupt; checksum differs for "
                    f"{source_object['path']}"
                )
        return {
            "runId": resolved_run_id,
            "outputBase": str(writer.target),
            "manifest": manifest,
            "reused": True,
        }

    try:
        writer.write_yaml(
            "resolved-config.yaml",
            config,
            source_system="generator",
            dataset="resolvedConfig",
        )
        writer.write_json(
            "resolved-config.json",
            config,
            source_system="generator",
            dataset="resolvedConfigJsonCompatibility",
        )
        catalog = build_catalog(config)
        markets = {market["marketId"]: dict(market) for market in config["markets"]}
        for market in markets.values():
            market["_endDate"] = config["time"]["endDate"]
        stores = {store["storeId"]: store for store in config["stores"]}
        warehouses = {row["warehouseId"]: row for row in config["warehouses"]}
        master_seed = config["identity"]["masterSeed"]
        start = date.fromisoformat(config["time"]["startDate"])
        end = date.fromisoformat(config["time"]["endDate"])

        product_rows_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
        variant_rows_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
        catalog_event_rows_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
        catalog_truth: list[dict[str, Any]] = []
        for market_id, products in catalog.items():
            market = markets[market_id]
            for product in products:
                product_key = f"{market_id}:{product['productKey']}"
                product_id = shopify_gid("Product", product_key)
                product_rows_by_market[market_id].append(
                    {
                        "id": product_id,
                        "title": product["title"],
                        "handle": _slug(product["title"]) + "-" + product["productCode"].lower(),
                        "descriptionHtml": f"<p>{product['description']}</p>",
                        "status": (
                            "ARCHIVED"
                            if product["discontinueDate"]
                            and product["discontinueDate"] <= end.isoformat()
                            else "ACTIVE"
                        ),
                        "vendor": product["brand"],
                        "productType": product["categoryId"],
                        "tags": "|".join(
                            dict.fromkeys(
                                [
                                    product["departmentId"],
                                    product["categoryId"],
                                    product["catalogFamily"],
                                    product["material"],
                                ]
                            )
                        ),
                        "createdAt": _iso_at(
                            date.fromisoformat(product["launchDate"]),
                            9,
                            market["timezone"],
                        ),
                        "publishedAt": _iso_at(
                            max(start, date.fromisoformat(product["launchDate"])),
                            9,
                            market["timezone"],
                        ),
                        "predecessorProductCode": product[
                            "successorOfProductCode"
                        ],
                        "successorProductCode": product["successorProductCode"],
                        "launchProfile": product["launchProfile"],
                        "launchDate": product["launchDate"],
                        "discontinueDate": product["discontinueDate"],
                    }
                )
                catalog_event_rows_by_market[market_id].append(
                    {
                        "eventKey": f"{product_key}:introduced",
                        "eventType": "PRODUCT_INTRODUCED",
                        "occurredAt": _iso_at(
                            date.fromisoformat(product["launchDate"]),
                            9,
                            market["timezone"],
                        ),
                        "productCode": product["productCode"],
                        "sku": "",
                        "predecessorProductCode": product[
                            "successorOfProductCode"
                        ],
                        "status": "ACTIVE",
                    }
                )
                if product["discontinueDate"]:
                    catalog_event_rows_by_market[market_id].append(
                        {
                            "eventKey": f"{product_key}:discontinued",
                            "eventType": "PRODUCT_DISCONTINUED",
                            "occurredAt": _iso_at(
                                date.fromisoformat(product["discontinueDate"]),
                                18,
                                market["timezone"],
                            ),
                            "productCode": product["productCode"],
                            "sku": "",
                            "predecessorProductCode": product[
                                "successorOfProductCode"
                            ],
                            "status": "ARCHIVED",
                        }
                    )
                for variant in product["variants"]:
                    variant_key = f"{market_id}:{variant['variantKey']}"
                    options = variant["options"]
                    variant_rows_by_market[market_id].append(
                        {
                            "id": shopify_gid("ProductVariant", variant_key),
                            "productId": product_id,
                            "inventoryItemId": shopify_gid("InventoryItem", variant_key),
                            "sku": variant["sku"],
                            "barcode": variant["barcode"],
                            "title": variant["title"],
                            "position": variant["position"],
                            "weight": variant["weight"],
                            "weightUnit": variant["weightUnit"],
                            "measurementValue": variant["measurementValue"],
                            "measurementUnit": variant["measurementUnit"],
                            "price": _money(
                                _variant_extract_price(
                                    variant,
                                    market,
                                    start,
                                    end,
                                    product,
                                )
                            ),
                            "currencyCode": market["currencyCode"],
                            "taxable": "true",
                            "inventoryManagement": "SHOPIFY",
                            "inventoryPolicy": "DENY",
                            "option1Name": options[0]["name"] if options else "",
                            "option1Value": options[0]["value"] if options else "",
                            "option2Name": options[1]["name"] if len(options) > 1 else "",
                            "option2Value": options[1]["value"] if len(options) > 1 else "",
                            "option3Name": options[2]["name"] if len(options) > 2 else "",
                            "option3Value": options[2]["value"] if len(options) > 2 else "",
                            "createdAt": _iso_at(
                                date.fromisoformat(variant["launchDate"]),
                                9,
                                market["timezone"],
                            ),
                            "publishedAt": _iso_at(
                                date.fromisoformat(variant["launchDate"]),
                                9,
                                market["timezone"],
                            ),
                            "status": (
                                "ARCHIVED"
                                if variant["discontinueDate"]
                                and variant["discontinueDate"] <= end.isoformat()
                                else "ACTIVE"
                            ),
                            "launchDate": variant["launchDate"],
                            "discontinueDate": variant["discontinueDate"],
                            "predecessorProductCode": product[
                                "successorOfProductCode"
                            ],
                            "_departmentId": product["departmentId"],
                            "_categoryId": product["categoryId"],
                            "_catalogFamily": product["catalogFamily"],
                            "_taxCategory": product["taxCategory"],
                            "_basePrice": variant["basePrice"],
                            "_baseCost": variant["baseCost"],
                            "_productCode": product["productCode"],
                            "_productTitle": product["title"],
                            "_brand": product["brand"],
                            "_brandCode": product["brandCode"],
                            "_variantCode": variant["variantCode"],
                            "_countryOfOrigin": product["countryOfOrigin"],
                            "_launchDate": variant["launchDate"],
                            "_discontinueDate": variant["discontinueDate"],
                            "_predecessorProductCode": product[
                                "successorOfProductCode"
                            ],
                            "_successorProductCode": product[
                                "successorProductCode"
                            ],
                            "_successorLaunchDate": product[
                                "successorLaunchDate"
                            ],
                            "_launchProfile": product["launchProfile"],
                            "_lifecycle": product["lifecycle"],
                            "_shelfLifeDays": product["shelfLifeDays"],
                            "_demandWeight": variant["demandWeight"],
                            "_elasticity": variant["elasticity"],
                            "_returnProbability": variant["returnProbability"],
                            "_seasonalityPeakMonth": product["seasonalityPeakMonth"],
                            "_seasonalityStrength": product["seasonalityStrength"],
                            "_costingMethod": product["costingMethod"],
                        }
                    )
                    catalog_event_rows_by_market[market_id].append(
                        {
                            "eventKey": f"{variant_key}:introduced",
                            "eventType": "SKU_INTRODUCED",
                            "occurredAt": _iso_at(
                                date.fromisoformat(variant["launchDate"]),
                                10,
                                market["timezone"],
                            ),
                            "productCode": product["productCode"],
                            "sku": variant["sku"],
                            "predecessorProductCode": product[
                                "successorOfProductCode"
                            ],
                            "status": "ACTIVE",
                        }
                    )
                    if variant["discontinueDate"]:
                        catalog_event_rows_by_market[market_id].append(
                            {
                                "eventKey": f"{variant_key}:discontinued",
                                "eventType": "SKU_DISCONTINUED",
                                "occurredAt": _iso_at(
                                    date.fromisoformat(
                                        variant["discontinueDate"]
                                    ),
                                    18,
                                    market["timezone"],
                                ),
                                "productCode": product["productCode"],
                                "sku": variant["sku"],
                                "predecessorProductCode": product[
                                    "successorOfProductCode"
                                ],
                                "status": "ARCHIVED",
                            }
                        )
                    catalog_truth.append(
                        {
                            "marketKey": market_id,
                            "productKey": product["productKey"],
                            "productCode": product["productCode"],
                            "productTitle": product["title"],
                            "brand": product["brand"],
                            "variantKey": variant["variantKey"],
                            "variantCode": variant["variantCode"],
                            "sku": variant["sku"],
                            "basePrice": _money(variant["basePrice"]),
                            "baseCost": _money(variant["baseCost"]),
                            "currencyCode": market["currencyCode"],
                            "demandWeight": str(variant["demandWeight"]),
                            "elasticity": str(variant["elasticity"]),
                            "returnProbability": str(variant["returnProbability"]),
                            "launchDate": variant["launchDate"],
                            "discontinueDate": variant["discontinueDate"],
                            "predecessorProductCode": product[
                                "successorOfProductCode"
                            ],
                            "successorProductCode": product[
                                "successorProductCode"
                            ],
                            "successorLaunchDate": product[
                                "successorLaunchDate"
                            ],
                            "launchProfile": product["launchProfile"],
                            "shelfLifeDays": (
                                product["shelfLifeDays"]
                                if product["shelfLifeDays"] is not None
                                else ""
                            ),
                            "seasonalityPeakMonth": product["seasonalityPeakMonth"],
                            "seasonalityStrength": str(product["seasonalityStrength"]),
                        }
                    )

        automatic_lifecycle_promotions = lifecycle_promotions(
            config,
            variant_rows_by_market,
        )
        simulation = simulate(
            config,
            markets,
            stores,
            warehouses,
            variant_rows_by_market,
            start,
            end,
        )
        order_events = simulation["orderLines"]
        order_headers = simulation["orders"]
        for source_sequence, order in enumerate(
            sorted(
                order_headers,
                key=lambda row: (row["createdAt"], row["orderKey"]),
            ),
            start=1,
        ):
            order["sourceOrderName"] = shopify_order_name(source_sequence)
        demand_truth = simulation["demandTruth"]
        commerce_extensions = build_commerce_extensions(
            config,
            order_events,
            order_headers,
        )
        supply_extensions = build_supply_extensions(
            config,
            markets,
            warehouses,
            variant_rows_by_market,
            simulation,
        )
        marketing_extensions = build_marketing_extensions(
            config,
            variant_rows_by_market,
            automatic_lifecycle_promotions,
        )
        successful_refunds_by_order: dict[str, Decimal] = defaultdict(
            lambda: Decimal("0")
        )
        for refund in commerce_extensions["refunds"]:
            if refund["status"] == "SUCCESS":
                successful_refunds_by_order[refund["orderId"]] += Decimal(
                    refund["totalRefunded"]
                )
        fulfillment_orders_by_order: dict[str, int] = defaultdict(int)
        created_fulfillments_by_order: dict[str, int] = defaultdict(int)
        for fulfillment_order in commerce_extensions["fulfillmentOrders"]:
            fulfillment_orders_by_order[fulfillment_order["orderId"]] += 1
        for fulfillment in commerce_extensions["fulfillments"]:
            created_fulfillments_by_order[fulfillment["orderId"]] += 1
        financial_status_by_order: dict[str, str] = {}
        fulfillment_status_by_order: dict[str, str] = {}
        for order in order_headers:
            order_id = shopify_gid("Order", order["orderKey"])
            refunded = successful_refunds_by_order[order_id]
            financial_status_by_order[order_id] = (
                "REFUNDED"
                if refunded >= order["gross"]
                else ("PARTIALLY_REFUNDED" if refunded > 0 else "PAID")
            )
            expected = fulfillment_orders_by_order[order_id]
            fulfilled = created_fulfillments_by_order[order_id]
            fulfillment_status_by_order[order_id] = (
                "FULFILLED"
                if expected and fulfilled == expected
                else ("PARTIALLY_FULFILLED" if fulfilled else "UNFULFILLED")
            )
        latest_inventory_observation: dict[
            tuple[str, str],
            dict[str, Any],
        ] = {}
        for observation in simulation["inventoryObservations"]:
            key = (observation["warehouseKey"], observation["sku"])
            prior = latest_inventory_observation.get(key)
            if prior is None or observation["observedAt"] > prior["observedAt"]:
                latest_inventory_observation[key] = observation

        for shop in config["sourceInstances"]["shopify"]:
            market_id = shop["marketId"]
            market = markets[market_id]
            shop_dir = f"shopify/{shop['shopId']}"
            public_variants = [
                {key: value for key, value in row.items() if not key.startswith("_")}
                for row in variant_rows_by_market[market_id]
            ]
            writer.write_dataset(
                f"{shop_dir}/products.csv",
                product_rows_by_market[market_id],
                source_system="shopify",
                dataset="products",
            )
            writer.write_dataset(
                f"{shop_dir}/product_variants.csv",
                public_variants,
                source_system="shopify",
                dataset="productVariants",
            )
            writer.write_dataset(
                f"{shop_dir}/catalog_events.csv",
                catalog_event_rows_by_market[market_id],
                source_system="shopify",
                dataset="catalogEvents",
            )
            writer.write_dataset(
                f"{shop_dir}/price_history.csv",
                _price_history_rows(
                    variant_rows_by_market[market_id],
                    market,
                    start,
                    end,
                ),
                source_system="shopify",
                dataset="priceHistory",
            )
            writer.write_dataset(
                f"{shop_dir}/inventory_items.csv",
                [
                    {
                        "id": variant["inventoryItemId"],
                        "sku": variant["sku"],
                        "tracked": "true",
                        "requiresShipping": "true",
                        "countryCodeOfOrigin": variant["_countryOfOrigin"],
                        "unitCostAmount": _money(variant["_baseCost"]),
                        "unitCostCurrencyCode": market["currencyCode"],
                    }
                    for variant in variant_rows_by_market[market_id]
                ],
                source_system="shopify",
                dataset="inventoryItems",
            )
            shop_stores = [stores[store_id] for store_id in shop["storeIds"]]
            shop_warehouses = [
                warehouse
                for warehouse in warehouses.values()
                if set(warehouse["servesLocations"]).intersection(shop["storeIds"])
            ]
            writer.write_dataset(
                f"{shop_dir}/locations.csv",
                [
                    {
                        "id": shopify_gid("Location", store["storeId"]),
                        "name": store["name"],
                        "active": "true",
                        "address1": store["addressLine1"],
                        "city": market["city"],
                        "provinceCode": market["regionCode"],
                        "countryCode": market["countryCode"],
                        "zip": store["postcode"],
                        "timezone": market["timezone"],
                        "locationType": "STORE",
                    }
                    for store in shop_stores
                ]
                + [
                    {
                        "id": shopify_gid("Location", warehouse["warehouseId"]),
                        "name": warehouse["name"],
                        "active": "true",
                        "address1": "",
                        "city": market["city"],
                        "provinceCode": market["regionCode"],
                        "countryCode": market["countryCode"],
                        "zip": "",
                        "timezone": market["timezone"],
                        "locationType": "WAREHOUSE",
                    }
                    for warehouse in shop_warehouses
                ],
                source_system="shopify",
                dataset="locations",
            )
            shop_orders = [
                event
                for event in order_events
                if event["marketId"] == market_id and event["storeId"] in shop["storeIds"]
            ]
            shop_order_headers = [
                order
                for order in order_headers
                if order["marketId"] == market_id
                and order["storeId"] in shop["storeIds"]
            ]
            customer_headers: dict[str, dict[str, Any]] = {}
            for order in shop_order_headers:
                customer_headers.setdefault(
                    order["customerKey"],
                    {
                        "id": shopify_gid("Customer", order["customerKey"]),
                        "syntheticCustomerKey": order["customerKey"],
                        "segmentId": order["customerSegmentId"],
                        "createdAt": order["createdAt"],
                        "state": "ENABLED",
                        "email": "",
                        "phone": "",
                        "firstName": "",
                        "lastName": "",
                        "directIdentifiersPresent": "false",
                    },
                )
            writer.write_dataset(
                f"{shop_dir}/customers.csv",
                list(customer_headers.values()),
                source_system="shopify",
                dataset="customers",
            )
            writer.write_dataset(
                f"{shop_dir}/orders.csv",
                [
                    {
                        "id": shopify_gid("Order", order["orderKey"]),
                        "name": order["sourceOrderName"],
                        "createdAt": order["createdAt"],
                        "processedAt": order["createdAt"],
                        "currencyCode": order["currencyCode"],
                        "taxesIncluded": str(order["taxesIncluded"]).lower(),
                        "subtotalPrice": _money(
                            order["gross"]
                            if order["taxesIncluded"]
                            else order["net"]
                        ),
                        "totalTax": _money(order["tax"]),
                        "totalPrice": _money(order["gross"]),
                        "displayFinancialStatus": financial_status_by_order[
                            shopify_gid("Order", order["orderKey"])
                        ],
                        "displayFulfillmentStatus": fulfillment_status_by_order[
                            shopify_gid("Order", order["orderKey"])
                        ],
                        "locationId": shopify_gid("Location", order["storeId"]),
                        "sourceName": "pos" if "store" in order["channelId"] else "web",
                        "customerSegmentId": order["customerSegmentId"],
                        "customerId": shopify_gid(
                            "Customer",
                            order["customerKey"],
                        ),
                        "channelId": order["channelId"],
                        "lineCount": order["lineCount"],
                    }
                    for order in shop_order_headers
                ],
                source_system="shopify",
                dataset="orders",
            )
            writer.write_dataset(
                f"{shop_dir}/order_lines.csv",
                [
                    {
                        "id": shopify_gid("OrderLine", event["lineKey"]),
                        "orderId": shopify_gid("Order", event["orderKey"]),
                        "variantId": event["variantId"],
                        "sku": event["sku"],
                        "productTitle": event["productTitle"],
                        "variantTitle": event["variantTitle"],
                        "vendor": event["brand"],
                        "productCode": event["productCode"],
                        "barcode": event["barcode"],
                        "quantity": event["quantity"],
                        "originalUnitPrice": _money(event["originalUnitPrice"]),
                        "discountedUnitPrice": _money(event["unitPrice"]),
                        "promotionIds": "|".join(event["promotionIds"]),
                        "currencyCode": event["currencyCode"],
                        "taxRate": str(event["taxRate"]),
                        "lineNumber": event["lineNumber"],
                        "customerSegmentId": event["customerSegmentId"],
                        "channelId": event["channelId"],
                        "__partitionDate": event["day"].isoformat(),
                    }
                    for event in shop_orders
                ],
                source_system="shopify",
                dataset="orderLines",
            )
            writer.write_dataset(
                f"{shop_dir}/inventory_levels.csv",
                [
                    {
                        "inventoryItemId": variant["inventoryItemId"],
                        "locationId": shopify_gid(
                            "Location",
                            warehouse["warehouseId"],
                        ),
                        "available": latest_inventory_observation.get(
                            (warehouse["warehouseId"], variant["sku"]),
                            {"available": 0},
                        )["available"],
                        "updatedAt": latest_inventory_observation.get(
                            (warehouse["warehouseId"], variant["sku"]),
                            {
                                "observedAt": _iso_at(
                                    end,
                                    23,
                                    market["timezone"],
                                )
                            },
                        )["observedAt"],
                    }
                    for warehouse in shop_warehouses
                    for variant in public_variants
                ],
                source_system="shopify",
                dataset="inventoryLevels",
            )
            if config["operations"]["features"]["inventoryStateMatrix"]:
                writer.write_dataset(
                    f"{shop_dir}/inventory_quantities.csv",
                    [
                        {
                            "inventoryItemId": next(
                                variant["inventoryItemId"]
                                for variant in public_variants
                                if variant["sku"] == observation["sku"]
                            ),
                            "locationId": shopify_gid(
                                "Location",
                                observation["warehouseKey"],
                            ),
                            "observedAt": observation["observedAt"],
                            "name": state_name,
                            "quantity": observation[source_name],
                        }
                        for observation in simulation["inventoryObservations"]
                        if observation["marketKey"] == market_id
                        and observation["warehouseKey"]
                        in {row["warehouseId"] for row in shop_warehouses}
                        for state_name, source_name in (
                            ("on_hand", "onHand"),
                            ("available", "available"),
                            ("committed", "committed"),
                            ("reserved", "reserved"),
                            ("damaged", "damaged"),
                            ("quality_control", "qualityControl"),
                            ("safety_stock", "safetyStock"),
                            ("incoming", "incoming"),
                        )
                    ],
                    source_system="shopify",
                    dataset="inventoryQuantities",
                )
            allowed_order_ids = {
                shopify_gid("Order", order["orderKey"])
                for order in shop_order_headers
            }
            if config["operations"]["features"]["detailedFulfillment"]:
                for filename, dataset, key in (
                    ("fulfillment_orders.csv", "fulfillmentOrders", "fulfillmentOrders"),
                    (
                        "fulfillment_order_lines.csv",
                        "fulfillmentOrderLines",
                        "fulfillmentOrderLines",
                    ),
                    ("fulfillments.csv", "fulfillments", "fulfillments"),
                    ("fulfillment_lines.csv", "fulfillmentLines", "fulfillmentLines"),
                    (
                        "fulfillment_status_history.csv",
                        "fulfillmentStatusHistory",
                        "fulfillmentStatusHistory",
                    ),
                ):
                    rows = commerce_extensions[key]
                    if key == "fulfillmentOrderLines":
                        fulfillment_order_ids = {
                            row["id"]
                            for row in commerce_extensions["fulfillmentOrders"]
                            if row["orderId"] in allowed_order_ids
                        }
                        rows = [
                            row
                            for row in rows
                            if row["fulfillmentOrderId"] in fulfillment_order_ids
                        ]
                    elif key == "fulfillmentStatusHistory":
                        fulfillment_ids = {
                            row["id"]
                            for row in commerce_extensions["fulfillments"]
                            if row["orderId"] in allowed_order_ids
                        }
                        rows = [
                            row
                            for row in rows
                            if row["fulfillmentId"] in fulfillment_ids
                        ]
                    elif key == "fulfillmentLines":
                        fulfillment_ids = {
                            row["id"]
                            for row in commerce_extensions["fulfillments"]
                            if row["orderId"] in allowed_order_ids
                        }
                        rows = [
                            row for row in rows if row["fulfillmentId"] in fulfillment_ids
                        ]
                    else:
                        rows = [
                            row for row in rows if row["orderId"] in allowed_order_ids
                        ]
                    writer.write_dataset(
                        f"{shop_dir}/{filename}",
                        rows,
                        source_system="shopify",
                        dataset=dataset,
                    )
            writer.write_dataset(
                f"{shop_dir}/tax_lines.csv",
                [
                    row
                    for row in commerce_extensions["taxLines"]
                    if row["orderId"] in allowed_order_ids
                ],
                source_system="shopify",
                dataset="taxLines",
            )
            if config["operations"]["features"]["returnsAndRefunds"]:
                allowed_return_ids = {
                    row["id"]
                    for row in commerce_extensions["returns"]
                    if row["orderId"] in allowed_order_ids
                }
                allowed_refund_ids = {
                    row["id"]
                    for row in commerce_extensions["refunds"]
                    if row["orderId"] in allowed_order_ids
                }
                for filename, dataset, rows in (
                    (
                        "returns.csv",
                        "returns",
                        [
                            row
                            for row in commerce_extensions["returns"]
                            if row["orderId"] in allowed_order_ids
                        ],
                    ),
                    (
                        "return_lines.csv",
                        "returnLines",
                        [
                            row
                            for row in commerce_extensions["returnLines"]
                            if row["returnId"] in allowed_return_ids
                        ],
                    ),
                    (
                        "refunds.csv",
                        "refunds",
                        [
                            row
                            for row in commerce_extensions["refunds"]
                            if row["orderId"] in allowed_order_ids
                        ],
                    ),
                    (
                        "refund_transactions.csv",
                        "refundTransactions",
                        [
                            row
                            for row in commerce_extensions["refundTransactions"]
                            if row["refundId"] in allowed_refund_ids
                        ],
                    ),
                ):
                    writer.write_dataset(
                        f"{shop_dir}/{filename}",
                        rows,
                        source_system="shopify",
                        dataset=dataset,
                    )
            if config["operations"]["features"]["webhookFixtures"]:
                writer.write_dataset(
                    f"{shop_dir}/webhook_hmac_fixtures.csv",
                    [
                        row
                        for row in commerce_extensions["webhookFixtures"]
                        if row["shopDomain"] == shop["shopDomain"]
                    ],
                    source_system="shopify",
                    dataset="webhookHmacFixtures",
                )

        entities = {
            row["legalEntityId"]: row for row in config["legalEntities"]
        }
        for company in config["sourceInstances"]["businessCentral"]:
            entity = entities[company["legalEntityId"]]
            company_markets = {
                market_id
                for market_id in entity["marketIds"]
            }
            company_warehouse_ids = set(company["warehouseIds"])
            company_dir = f"business-central/{company['companyId']}"
            company_products = [
                (market_id, product)
                for market_id in sorted(company_markets)
                for product in catalog[market_id]
            ]
            writer.write_dataset(
                f"{company_dir}/items.csv",
                [
                    {
                        **(
                            {
                                "vendorId": next(
                                    row["id"]
                                    for row in supply_extensions["vendors"]
                                    if row["marketCode"] == market_id
                                    and row["brandCode"] == product["brandCode"]
                                ),
                                "vendorNumber": next(
                                    row["number"]
                                    for row in supply_extensions["vendors"]
                                    if row["marketCode"] == market_id
                                    and row["brandCode"] == product["brandCode"]
                                ),
                                "vendorName": next(
                                    row["displayName"]
                                    for row in supply_extensions["vendors"]
                                    if row["marketCode"] == market_id
                                    and row["brandCode"] == product["brandCode"]
                                ),
                            }
                            if config["operations"]["features"]["supplyChain"]
                            else {}
                        ),
                        "id": bc_uuid(
                            "Item", f"{market_id}:{product['productCode']}"
                        ),
                        "number": product["productCode"],
                        "displayName": product["title"],
                        "description": product["description"],
                        "brandName": product["brand"],
                        "type": "Inventory",
                        "itemCategoryCode": product["categoryId"],
                        "baseUnitOfMeasureCode": product["unitOfMeasure"],
                        "costingMethod": product["costingMethod"],
                        "countryRegionOfOriginCode": product["countryOfOrigin"],
                        "blocked": (
                            "true"
                            if product["discontinueDate"]
                            and product["discontinueDate"] <= end.isoformat()
                            else "false"
                        ),
                        "introducedDate": product["launchDate"],
                        "discontinuedDate": product["discontinueDate"],
                        "predecessorItemNumber": product[
                            "successorOfProductCode"
                        ],
                    }
                    for market_id, product in company_products
                ],
                source_system="businessCentral",
                dataset="items",
            )
            writer.write_dataset(
                f"{company_dir}/item_variants.csv",
                [
                    {
                        "id": bc_uuid(
                            "ItemVariant",
                            f"{market_id}:{product['productCode']}:{variant['variantCode']}",
                        ),
                        "itemId": bc_uuid(
                            "Item", f"{market_id}:{product['productCode']}"
                        ),
                        "itemNumber": product["productCode"],
                        "code": variant["variantCode"],
                        "description": variant["title"],
                        "sku": variant["sku"],
                        "barcode": variant["barcode"],
                        "unitCost": _money(variant["baseCost"]),
                        "unitOfMeasureCode": variant["unitOfMeasure"],
                        "measurementValue": variant["measurementValue"],
                        "measurementUnit": variant["measurementUnit"],
                        "unitPrice": _money(
                            _variant_extract_price(
                                variant,
                                markets[market_id],
                                start,
                                end,
                                product,
                            )
                        ),
                        "currencyCode": markets[market_id]["currencyCode"],
                        "blocked": (
                            "true"
                            if variant["discontinueDate"]
                            and variant["discontinueDate"] <= end.isoformat()
                            else "false"
                        ),
                        "introducedDate": variant["launchDate"],
                        "discontinuedDate": variant["discontinueDate"],
                        "predecessorItemNumber": product[
                            "successorOfProductCode"
                        ],
                    }
                    for market_id, product in company_products
                    for variant in product["variants"]
                ],
                source_system="businessCentral",
                dataset="itemVariants",
            )
            writer.write_dataset(
                f"{company_dir}/item_lifecycle_events.csv",
                [
                    {
                        **row,
                        "marketCode": market_id,
                    }
                    for market_id in sorted(company_markets)
                    for row in catalog_event_rows_by_market[market_id]
                ],
                source_system="businessCentral",
                dataset="itemLifecycleEvents",
            )
            writer.write_dataset(
                f"{company_dir}/locations.csv",
                [
                    {
                        "id": bc_uuid("Location", warehouse_id),
                        "code": warehouse["businessCentralLocationCode"],
                        "displayName": warehouse["name"],
                        "marketCode": warehouse["marketId"],
                        "countryRegionCode": markets[warehouse["marketId"]]["countryCode"],
                        "taxAreaCode": markets[warehouse["marketId"]]["localePack"][
                            "tax"
                        ]["jurisdiction"],
                    }
                    for warehouse_id in company["warehouseIds"]
                    for warehouse in [warehouses[warehouse_id]]
                ],
                source_system="businessCentral",
                dataset="locations",
            )
            writer.write_dataset(
                f"{company_dir}/company_market_configuration.csv",
                [
                    {
                        "companyId": company["companyId"],
                        "companyName": company["companyName"],
                        "legalEntityId": company["legalEntityId"],
                        "marketCode": market_id,
                        "countryRegionCode": markets[market_id]["countryCode"],
                        "localCurrencyCode": markets[market_id]["currencyCode"],
                        "fiscalYearStartMonth": markets[market_id]["localePack"][
                            "fiscalYearStartMonth"
                        ],
                        "taxBasis": markets[market_id]["localePack"]["tax"]["basis"],
                        "taxJurisdiction": markets[market_id]["localePack"]["tax"][
                            "jurisdiction"
                        ],
                    }
                    for market_id in sorted(company_markets)
                ],
                source_system="businessCentral",
                dataset="companyMarketConfiguration",
            )
            company_orders = [
                event
                for event in order_events
                if event["marketId"] in company_markets
            ]
            company_order_headers = [
                order
                for order in order_headers
                if order["marketId"] in company_markets
            ]
            company_customers: dict[str, dict[str, Any]] = {}
            for order in company_order_headers:
                company_customers.setdefault(
                    order["customerKey"],
                    {
                        "id": bc_uuid("Customer", order["customerKey"]),
                        "number": (
                            f"C{stable_integer(order['customerKey'], modulo=10**9):09d}"
                        ),
                        "displayName": "Anonymous synthetic customer",
                        "marketCode": order["marketId"],
                        "segmentCode": order["customerSegmentId"],
                        "email": "",
                        "phoneNumber": "",
                        "blocked": "false",
                        "directIdentifiersPresent": "false",
                    },
                )
            writer.write_dataset(
                f"{company_dir}/customers.csv",
                list(company_customers.values()),
                source_system="businessCentral",
                dataset="customers",
            )
            writer.write_dataset(
                f"{company_dir}/sales_invoices.csv",
                [
                    {
                        "id": bc_uuid("SalesInvoice", order["orderKey"]),
                        "number": f"SI-{stable_integer(order['orderKey'], modulo=99_999_999):08d}",
                        "externalDocumentNumber": order["sourceOrderName"],
                        "invoiceDate": order["day"].isoformat(),
                        "postingDate": order["day"].isoformat(),
                        "currencyCode": order["currencyCode"],
                        "totalAmountExcludingTax": _money(order["net"]),
                        "totalTaxAmount": _money(order["tax"]),
                        "totalAmountIncludingTax": _money(order["gross"]),
                        "status": "Paid",
                        "customerSegmentCode": order["customerSegmentId"],
                        "customerId": bc_uuid(
                            "Customer",
                            order["customerKey"],
                        ),
                        "salesChannelCode": order["channelId"],
                    }
                    for order in company_order_headers
                ],
                source_system="businessCentral",
                dataset="salesInvoices",
            )
            writer.write_dataset(
                f"{company_dir}/sales_invoice_lines.csv",
                [
                    {
                        "id": bc_uuid(
                            "SalesInvoiceLine",
                            f"{event['lineKey']}:{allocation['warehouseId']}",
                        ),
                        "documentId": bc_uuid("SalesInvoice", event["orderKey"]),
                        "lineNumber": event["lineNumber"] + allocation_index,
                        "itemId": bc_uuid(
                            "Item",
                            f"{event['marketId']}:{event['productCode']}",
                        ),
                        "itemNumber": event["productCode"],
                        "variantCode": event["variantCode"],
                        "sku": event["sku"],
                        "description": event["productTitle"],
                        "locationCode": warehouses[allocation["warehouseId"]][
                            "businessCentralLocationCode"
                        ],
                        "quantity": allocation["quantity"],
                        "unitPrice": _money(event["unitPrice"]),
                        "netAmount": _money(
                            _allocation_amount(
                                event["net"],
                                event["allocations"],
                                allocation_index,
                            )
                        ),
                        "taxAmount": _money(
                            _allocation_amount(
                                event["tax"],
                                event["allocations"],
                                allocation_index,
                            )
                        ),
                        "amountIncludingTax": _money(
                            _allocation_amount(
                                event["gross"],
                                event["allocations"],
                                allocation_index,
                            )
                        ),
                        "currencyCode": event["currencyCode"],
                        "__partitionDate": event["day"].isoformat(),
                    }
                    for event in company_orders
                    for allocation_index, allocation in enumerate(
                        event["allocations"]
                    )
                ],
                source_system="businessCentral",
                dataset="salesInvoiceLines",
            )
            writer.write_dataset(
                f"{company_dir}/item_ledger_entries.csv",
                _bc_item_ledger_rows(
                    company_warehouse_ids,
                    company_orders,
                    warehouses,
                    variant_rows_by_market,
                    simulation,
                    start,
                    end,
                ),
                source_system="businessCentral",
                dataset="itemLedgerEntries",
            )
            writer.write_dataset(
                f"{company_dir}/inventory_snapshots.csv",
                [
                    {
                        "locationCode": warehouses[observation["warehouseKey"]][
                            "businessCentralLocationCode"
                        ],
                        "observedAt": observation["observedAt"],
                        "sku": observation["sku"],
                        "inventory": observation["onHand"],
                        "availableInventory": observation["available"],
                        "committedInventory": observation["committed"],
                        "reservedInventory": observation["reserved"],
                        "damagedInventory": observation["damaged"],
                        "qualityControlInventory": observation["qualityControl"],
                        "safetyStockInventory": observation["safetyStock"],
                        "incomingInventory": observation["incoming"],
                    }
                    for observation in simulation["inventoryObservations"]
                    if observation["warehouseKey"] in company_warehouse_ids
                ],
                source_system="businessCentral",
                dataset="inventorySnapshots",
            )
            if config["operations"]["features"]["supplyChain"]:
                company_location_codes = {
                    warehouses[warehouse_id]["businessCentralLocationCode"]
                    for warehouse_id in company_warehouse_ids
                }
                allowed_vendor_ids = {
                    row["id"]
                    for row in supply_extensions["vendors"]
                    if row["marketCode"] in company_markets
                }
                allowed_po_ids = {
                    row["id"]
                    for row in supply_extensions["purchaseOrders"]
                    if row["warehouseId"] in company_warehouse_ids
                }
                allowed_receipt_ids = {
                    row["id"]
                    for row in supply_extensions["warehouseReceipts"]
                    if row["locationCode"]
                    in company_location_codes
                }
                allowed_receipt_line_ids = {
                    row["id"]
                    for row in supply_extensions["warehouseReceiptLines"]
                    if row["documentId"] in allowed_receipt_ids
                }
                allowed_transfer_ids = {
                    row["id"]
                    for row in supply_extensions["transferOrders"]
                    if row["fromLocationCode"]
                    in company_location_codes
                    and row["toLocationCode"] in company_location_codes
                }
                supply_dataset_files = (
                    ("vendors.csv", "vendors", "vendors", None),
                    (
                        "vendor_item_terms.csv",
                        "vendorItemTerms",
                        "vendorItemTerms",
                        None,
                    ),
                    (
                        "purchase_orders.csv",
                        "purchaseOrders",
                        "purchaseOrders",
                        None,
                    ),
                    (
                        "purchase_order_lines.csv",
                        "purchaseOrderLines",
                        "purchaseOrderLines",
                        None,
                    ),
                    (
                        "inbound_shipments.csv",
                        "inboundShipments",
                        "inboundShipments",
                        None,
                    ),
                    (
                        "warehouse_receipts.csv",
                        "warehouseReceipts",
                        "warehouseReceipts",
                        None,
                    ),
                    (
                        "warehouse_receipt_lines.csv",
                        "warehouseReceiptLines",
                        "warehouseReceiptLines",
                        None,
                    ),
                    (
                        "item_cost_layers.csv",
                        "itemCostLayers",
                        "itemCostLayers",
                        None,
                    ),
                    ("item_batches.csv", "itemBatches", "itemBatches", None),
                    (
                        "supplier_performance.csv",
                        "supplierPerformance",
                        "supplierPerformance",
                        "supplierPlanning",
                    ),
                    (
                        "supplier_capacity_confirmations.csv",
                        "supplierCapacityConfirmations",
                        "supplierCapacityConfirmations",
                        "supplierPlanning",
                    ),
                    (
                        "purchasing_budgets.csv",
                        "purchasingBudgets",
                        "purchasingBudgets",
                        "supplierPlanning",
                    ),
                    (
                        "transfer_orders.csv",
                        "transferOrders",
                        "transferOrders",
                        "transfers",
                    ),
                    (
                        "transfer_order_lines.csv",
                        "transferOrderLines",
                        "transferOrderLines",
                        "transfers",
                    ),
                    (
                        "transfer_shipments.csv",
                        "transferShipments",
                        "transferShipments",
                        "transfers",
                    ),
                    (
                        "warehouse_capacity.csv",
                        "warehouseCapacity",
                        "warehouseCapacity",
                        "warehouseOperations",
                    ),
                    (
                        "wms_inventory_comparisons.csv",
                        "wmsInventoryComparisons",
                        "wmsInventoryComparisons",
                        "warehouseOperations",
                    ),
                    (
                        "waste_events.csv",
                        "wasteEvents",
                        "wasteEvents",
                        "warehouseOperations",
                    ),
                )
                for filename, dataset, key, feature in supply_dataset_files:
                    if (
                        feature is not None
                        and not config["operations"]["features"][feature]
                    ):
                        continue
                    rows = supply_extensions[key]
                    warehouse_fields = (
                        "warehouseId",
                        "warehouseKey",
                        "fromWarehouseId",
                        "toWarehouseId",
                    )
                    filtered = [
                        row
                        for row in rows
                        if (
                            not any(field in row for field in warehouse_fields)
                            or any(
                                row.get(field) in company_warehouse_ids
                                for field in warehouse_fields
                            )
                        )
                        and (
                            "marketCode" not in row
                            or row["marketCode"] in company_markets
                        )
                        and (
                            "locationCode" not in row
                            or row["locationCode"] in company_location_codes
                        )
                        and (
                            "fromLocationCode" not in row
                            or (
                                row["fromLocationCode"] in company_location_codes
                                and row.get("toLocationCode")
                                in company_location_codes
                            )
                        )
                    ]
                    if key == "vendorItemTerms":
                        filtered = [
                            row for row in rows if row["vendorId"] in allowed_vendor_ids
                        ]
                    elif key == "purchaseOrderLines":
                        filtered = [
                            row for row in rows if row["documentId"] in allowed_po_ids
                        ]
                    elif key == "inboundShipments":
                        filtered = [
                            row
                            for row in rows
                            if row["purchaseOrderId"] in allowed_po_ids
                        ]
                    elif key == "warehouseReceiptLines":
                        filtered = [
                            row
                            for row in rows
                            if row["documentId"] in allowed_receipt_ids
                        ]
                    elif key == "supplierPerformance":
                        filtered = [
                            row
                            for row in rows
                            if row["receiptLineId"] in allowed_receipt_line_ids
                        ]
                    elif key == "transferOrderLines":
                        filtered = [
                            row
                            for row in rows
                            if row["documentId"] in allowed_transfer_ids
                        ]
                    elif key == "transferShipments":
                        filtered = [
                            row
                            for row in rows
                            if row["transferOrderId"] in allowed_transfer_ids
                        ]
                    if filtered:
                        writer.write_dataset(
                            f"{company_dir}/{filename}",
                            filtered,
                            source_system="businessCentral",
                            dataset=dataset,
                        )

        for market_id, market in markets.items():
            companion_dir = f"companion/{market_id}"
            in_range_holidays = [
                {
                    "marketKey": market_id,
                    "targetType": "market",
                    "targetId": market_id,
                    **holiday,
                }
                for holiday in holidays_for_range(
                    market["localePack"],
                    start,
                    end,
                )
            ]
            if market["signals"]["holidays"]:
                writer.write_dataset(
                    f"{companion_dir}/holidays.csv",
                    in_range_holidays,
                    source_system="companion",
                    dataset="holidays",
                    fieldnames=[
                        "marketKey",
                        "targetType",
                        "targetId",
                        "date",
                        "name",
                        "kind",
                    ],
                )
            if market["signals"]["weather"]:
                writer.write_dataset(
                    f"{companion_dir}/weather_actuals.csv",
                    simulation["weatherActual"][market_id],
                    source_system="companion",
                    dataset="weatherActuals",
                )
                writer.write_dataset(
                    f"{companion_dir}/weather_forecasts.csv",
                    simulation["weatherForecasts"][market_id],
                    source_system="companion",
                    dataset="weatherForecasts",
                )
            if market["signals"]["macro"]:
                writer.write_dataset(
                    f"{companion_dir}/macro_index.csv",
                    simulation["macroRows"][market_id],
                    source_system="companion",
                    dataset="macroIndex",
                )
            writer.write_dataset(
                f"{companion_dir}/pandemic_timeline.csv",
                [
                    {
                        "marketKey": market_id,
                        "pandemicId": pandemic["pandemicId"],
                        "pandemicName": pandemic["name"],
                        "pathogen": pandemic["pathogen"],
                        "effectMode": pandemic["effectMode"],
                        "note": pandemic["note"],
                        "phaseId": phase["phaseId"],
                        "phaseName": phase["name"],
                        "startDate": phase["startDate"],
                        "endDate": phase["endDate"],
                        "recoveryShape": phase["recoveryShape"],
                        "demandMultiplier": phase["demandMultiplier"],
                        "trafficMultiplier": phase["trafficMultiplier"],
                        "costMultiplier": phase["costMultiplier"],
                        "leadTimeMultiplier": phase["leadTimeMultiplier"],
                        "inventoryLossPct": phase["inventoryLossPct"],
                        "departmentMultipliers": json.dumps(
                            phase["departmentMultipliers"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "categoryMultipliers": json.dumps(
                            phase["categoryMultipliers"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "catalogFamilyMultipliers": json.dumps(
                            phase["catalogFamilyMultipliers"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "channelTypeMultipliers": json.dumps(
                            phase["channelTypeMultipliers"],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                    for pandemic in config["pandemics"]
                    if market_id in pandemic["marketIds"]
                    for phase in pandemic["phases"]
                ],
                source_system="companion",
                dataset="pandemicTimeline",
                fieldnames=[
                    "marketKey",
                    "pandemicId",
                    "pandemicName",
                    "pathogen",
                    "effectMode",
                    "note",
                    "phaseId",
                    "phaseName",
                    "startDate",
                    "endDate",
                    "recoveryShape",
                    "demandMultiplier",
                    "trafficMultiplier",
                    "costMultiplier",
                    "leadTimeMultiplier",
                    "inventoryLossPct",
                    "departmentMultipliers",
                    "categoryMultipliers",
                    "catalogFamilyMultipliers",
                    "channelTypeMultipliers",
                ],
            )
            writer.write_dataset(
                f"{companion_dir}/pandemic_signals.csv",
                simulation["pandemicSignals"][market_id],
                source_system="companion",
                dataset="pandemicSignals",
                fieldnames=[
                    "marketKey",
                    "validDate",
                    "observedAt",
                    "pandemicIds",
                    "phaseIds",
                    "effectModes",
                    "demandMultiplier",
                    "trafficMultiplier",
                    "costMultiplier",
                    "leadTimeMultiplier",
                    "inventoryLossPct",
                ],
            )
            if market["signals"]["competitor"]:
                writer.write_dataset(
                    f"{companion_dir}/competitor_prices.csv",
                    simulation["competitorPrices"][market_id],
                    source_system="companion",
                    dataset="competitorPrices",
                )
                writer.write_dataset(
                    f"{companion_dir}/competitor_matches.csv",
                    simulation["competitorMatches"][market_id],
                    source_system="companion",
                    dataset="competitorMatches",
                )
            if market["signals"]["fx"]:
                writer.write_dataset(
                    f"{companion_dir}/fx_rates.csv",
                    [
                        {
                            "marketKey": market_id,
                            "rateDate": day.isoformat(),
                            "baseCurrency": market["currencyCode"],
                            "quoteCurrency": config["retailer"]["reportingCurrency"],
                            "rateType": "scenario-daily-close",
                            "quotePerBase": market["fxRateToReporting"],
                        }
                        for day in _days(start, end)
                    ],
                    source_system="companion",
                    dataset="fxRates",
                )
            writer.write_dataset(
                f"{companion_dir}/promotions.csv",
                [
                    {
                        "marketKey": market_id,
                        "promotionId": promotion["promotionId"],
                        "name": promotion["name"],
                        "startDate": promotion["startDate"],
                        "endDate": promotion["endDate"],
                        "storeIds": "|".join(promotion["storeIds"]),
                        "channelIds": "|".join(promotion["channelIds"]),
                        "departmentIds": "|".join(promotion["departmentIds"]),
                        "categoryIds": "|".join(promotion["categoryIds"]),
                        "customerSegmentIds": "|".join(
                            promotion["customerSegmentIds"]
                        ),
                        "discountPct": promotion["discountPct"],
                        "demandMultiplier": promotion["demandMultiplier"],
                        "promotionType": promotion.get(
                            "promotionType",
                            "campaign",
                        ),
                    }
                    for promotion in (
                        config["promotions"] + automatic_lifecycle_promotions
                    )
                    if promotion["marketId"] == market_id
                ],
                source_system="companion",
                dataset="promotions",
                fieldnames=[
                    "marketKey",
                    "promotionId",
                    "name",
                    "startDate",
                    "endDate",
                    "storeIds",
                    "channelIds",
                    "departmentIds",
                    "categoryIds",
                    "customerSegmentIds",
                    "discountPct",
                    "demandMultiplier",
                    "promotionType",
                ],
            )
            if config["operations"]["features"]["promotionPlanning"]:
                writer.write_dataset(
                    f"{companion_dir}/promotion_skus.csv",
                    [
                        row
                        for row in marketing_extensions["promotionSkus"]
                        if row["marketKey"] == market_id
                    ],
                    source_system="companion",
                    dataset="promotionSkus",
                )
                writer.write_dataset(
                    f"{companion_dir}/customer_segments.csv",
                    marketing_extensions["customerSegments"],
                    source_system="companion",
                    dataset="customerSegments",
                )
            writer.write_dataset(
                f"{companion_dir}/store_assortment.csv",
                [
                    row
                    for row in simulation["storeAssortment"]
                    if row["marketKey"] == market_id
                ],
                source_system="companion",
                dataset="storeAssortment",
            )
            if config["operations"]["features"]["allocationEvidence"]:
                writer.write_dataset(
                    f"{companion_dir}/allocation_demand_requests.csv",
                    [
                        row
                        for row in simulation["allocationRequests"]
                        if row["marketKey"] == market_id
                    ],
                    source_system="companion",
                    dataset="allocationDemandRequests",
                )
                writer.write_dataset(
                    f"{companion_dir}/allocation_supply_pools.csv",
                    [
                        row
                        for row in simulation["supplyPools"]
                        if row["marketKey"] == market_id
                    ],
                    source_system="companion",
                    dataset="allocationSupplyPools",
                )
            writer.write_dataset(
                f"{companion_dir}/local_events.csv",
                [
                    {
                        "marketKey": market_id,
                        "eventId": event["eventId"],
                        "type": event["type"],
                        "name": event["name"],
                        "startDate": event["startDate"],
                        "endDate": event["endDate"],
                        "targetType": "store" if event.get("storeId") else "market",
                        "targetId": event.get("storeId") or market_id,
                        "demandMultiplier": event["demandMultiplier"],
                        "trafficMultiplier": event["trafficMultiplier"],
                        "costMultiplier": event["costMultiplier"],
                        "leadTimeMultiplier": event["leadTimeMultiplier"],
                        "inventoryLossPct": event["inventoryLossPct"],
                        "recoveryShape": event["recoveryShape"],
                        "departmentIds": "|".join(event["departmentIds"]),
                        "categoryIds": "|".join(event["categoryIds"]),
                        "channelIds": "|".join(event["channelIds"]),
                    }
                    for event in config["events"]
                    if event["marketId"] == market_id
                ],
                source_system="companion",
                dataset="localEvents",
                fieldnames=[
                    "marketKey",
                    "eventId",
                    "type",
                    "name",
                    "startDate",
                    "endDate",
                    "targetType",
                    "targetId",
                    "demandMultiplier",
                    "trafficMultiplier",
                    "costMultiplier",
                    "leadTimeMultiplier",
                    "inventoryLossPct",
                    "recoveryShape",
                    "departmentIds",
                    "categoryIds",
                    "channelIds",
                ],
            )

        if config["output"]["writeHiddenTruth"]:
            writer.write_dataset(
                "_truth/catalog_truth.csv",
                catalog_truth,
                source_system="hiddenTruth",
                dataset="catalogTruth",
                restricted=True,
            )
            writer.write_dataset(
                "_truth/demand_factors.csv",
                demand_truth,
                source_system="hiddenTruth",
                dataset="demandFactors",
                restricted=True,
            )
            writer.write_dataset(
                "_truth/source_event_crosswalk.csv",
                [
                    {
                        "eventKey": event["eventKey"],
                        "lineKey": event["lineKey"],
                        "orderKey": event["orderKey"],
                        "shopifyOrderId": shopify_gid("Order", event["orderKey"]),
                        "shopifyOrderLineId": shopify_gid(
                            "OrderLine",
                            event["lineKey"],
                        ),
                        "businessCentralInvoiceId": bc_uuid(
                            "SalesInvoice",
                            event["orderKey"],
                        ),
                        "businessCentralInvoiceLineIds": "|".join(
                            bc_uuid(
                                "SalesInvoiceLine",
                                f"{event['lineKey']}:{allocation['warehouseId']}",
                            )
                            for allocation in event["allocations"]
                        ),
                        "marketKey": event["marketId"],
                        "storeKey": event["storeId"],
                        "__partitionDate": event["day"].isoformat(),
                    }
                    for event in order_events
                ],
                source_system="hiddenTruth",
                dataset="sourceEventCrosswalk",
                restricted=True,
            )
            writer.write_dataset(
                "_truth/inventory_constraint_truth.csv",
                [
                    {
                        "marketKey": row["marketKey"],
                        "storeKey": row["storeKey"],
                        "date": row["date"],
                        "sku": row["sku"],
                        "latentDemandUnits": row["latentDemandUnits"],
                        "realizedSalesUnits": row["realizedSalesUnits"],
                        "lostSalesUnits": row["lostSalesUnits"],
                    }
                    for row in demand_truth
                ],
                source_system="hiddenTruth",
                dataset="inventoryConstraintTruth",
                restricted=True,
            )
            writer.write_dataset(
                "_truth/competitor_match_truth.csv",
                [
                    row
                    for market_rows in simulation["competitorMatches"].values()
                    for row in market_rows
                ],
                source_system="hiddenTruth",
                dataset="competitorMatchTruth",
                restricted=True,
            )

        writer.write_source_schema()
        writer.write_duckdb_mirror()
        latent_units = sum(row["latentDemandUnits"] for row in demand_truth)
        realized_units = sum(row["realizedSalesUnits"] for row in demand_truth)
        lost_units = sum(row["lostSalesUnits"] for row in demand_truth)
        manifest = {
            "manifestVersion": "source-run-manifest/v3",
            "generatorVersion": GENERATOR_VERSION,
            "sourceSpecVersion": config["specVersion"],
            "scenarioId": config["identity"]["scenarioId"],
            "scenarioVersion": config["identity"]["scenarioVersion"],
            "runId": resolved_run_id,
            "runIdentityMethod": "sha256(generatorVersion+sourceSpecVersion+configHash)",
            "configHash": config_digest,
            "masterSeed": config["identity"]["masterSeed"],
            "logicalStartDate": config["time"]["startDate"],
            "logicalEndDate": config["time"]["endDate"],
            "retailer": config["retailer"],
            "topology": {
                "markets": [
                    {
                        "marketId": market["marketId"],
                        "countryCode": market["countryCode"],
                        "currencyCode": market["currencyCode"],
                        "timezone": market["timezone"],
                        "localePackId": market["localePack"]["id"],
                        "localePackVersion": market["localePack"]["version"],
                        "catalogPackId": market["catalogPack"]["id"],
                        "catalogPackVersion": market["catalogPack"]["version"],
                    }
                    for market in config["markets"]
                ],
                "stores": config["stores"],
                "warehouses": config["warehouses"],
                "sourceInstances": config["sourceInstances"],
            },
            "catalogControlsByMarket": catalog_controls(catalog),
            "controlsByCurrency": _manifest_controls(order_events),
            "simulationControls": {
                "skuStoreDays": len(demand_truth),
                "latentDemandUnits": latent_units,
                "realizedSalesUnits": realized_units,
                "lostSalesUnits": lost_units,
                "fillRate": (
                    str(
                        (
                            Decimal(realized_units) / Decimal(latent_units)
                        ).quantize(Decimal("0.000001"))
                    )
                    if latent_units
                    else "1.000000"
                ),
                "orders": len(order_headers),
                "orderLines": len(order_events),
                "fulfillments": len(commerce_extensions["fulfillments"]),
                "returns": len(commerce_extensions["returns"]),
                "purchaseOrderLines": len(supply_extensions["purchaseOrderLines"]),
                "transferLines": len(supply_extensions["transferOrderLines"]),
            },
            "capabilities": {
                "features": config["operations"]["features"],
                "publicFormats": config["output"]["publicFormats"],
                "authoritativeSourceFormat": config["output"]["publicFormats"][0],
                "sourceCompression": config["output"]["compression"],
                "duckdbRole": (
                    "non-authoritative mirror of generated source objects; "
                    "source_object_catalog.restricted must be enforced by consumers"
                ),
                "hiddenTruthIncluded": config["output"]["writeHiddenTruth"],
            },
            "objects": sorted(writer.objects, key=lambda row: row["path"]),
        }
        writer.write_json(
            "source-run-manifest.json",
            manifest,
            source_system="generator",
            dataset="sourceRunManifest",
            register=False,
        )
        output_base = writer.promote()
        return {
            "runId": resolved_run_id,
            "outputBase": str(output_base),
            "manifest": manifest,
            "reused": False,
        }
    except Exception:
        writer.abort()
        raise
