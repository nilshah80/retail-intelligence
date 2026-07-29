"""First causal multi-market source generation slice.

The simulation vocabulary is generator-owned. Public output is projected only
into Shopify-, Business Central-, and companion-shaped datasets.
"""

from __future__ import annotations

import json
import re
import resource
import sys
import time as runtime_time
import unicodedata
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from heapq import merge as heap_merge
from itertools import chain, groupby
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from retail_execution import resolve_profile, validate_profile

from . import GENERATOR_VERSION
from .catalog_packs import build_catalog, catalog_controls
from .calendar import holidays_for_range
from .config import validate_config
from .customers import CustomerPopulation
from .extensions import (
    build_commerce_extensions,
    build_marketing_extensions,
    build_supply_extensions,
)
from .identity import (
    bc_document_number,
    bc_uuid,
    config_hash,
    run_id,
    shopify_gid,
    shopify_order_name,
    stable_integer,
)
from .lifecycle import lifecycle_adjustment, lifecycle_promotions
from .spool import RowSpool
from .writer import SourceWriter, file_sha256
from .simulation import (
    _event_effect,
    _pandemic_effect,
    _price_for_day,
    _promotional_price,
    simulate,
)

MONEY_QUANT = Decimal("0.01")

_SIMULATION_SEQUENCE_FIELDS = (
    "demandTruth",
    "inventoryObservations",
    "receiptEvents",
    "transferEvents",
    "inventoryLossEvents",
    "wasteEvents",
    "batchBalances",
    "allocationRequests",
    "supplyPools",
)
_SIMULATION_MARKET_STREAM_FIELDS = (
    "weatherActual",
    "weatherForecasts",
    "macroRows",
    "competitorPrices",
    "competitorMatches",
    "pandemicSignals",
)


class _ChainedRows:
    """Repeatable, bounded view over market-local row spools."""

    def __init__(self, streams: Iterable[RowSpool]) -> None:
        self._streams = tuple(streams)

    def __iter__(self) -> Iterable[dict[str, Any]]:
        return chain.from_iterable(self._streams)

    def __len__(self) -> int:
        return sum(len(stream) for stream in self._streams)

    def __bool__(self) -> bool:
        return any(bool(stream) for stream in self._streams)

    def __getitem__(self, index: int) -> dict[str, Any]:
        if index != -1:
            raise TypeError("_ChainedRows supports only [-1] random access")
        for stream in reversed(self._streams):
            if stream:
                return stream[-1]
        raise IndexError("_ChainedRows index out of range")


def _simulate_market(
    config: dict[str, Any],
    market_id: str,
    market: dict[str, Any],
    stores: dict[str, dict[str, Any]],
    warehouses: dict[str, dict[str, Any]],
    variants: list[dict[str, Any]],
    start: date,
    end: date,
    work_directory: str,
    spool_chunk_rows: int,
) -> tuple[str, dict[str, Any], list[RowSpool], dict[str, float | int]]:
    """Run one causally independent market in an isolated process."""

    started = runtime_time.perf_counter()
    cpu_started = resource.getrusage(resource.RUSAGE_SELF)
    created_spools: list[RowSpool] = []

    def new_spool(name: str) -> RowSpool:
        spool = RowSpool(
            Path(work_directory),
            f"{market_id}-{name}",
            chunk_rows=spool_chunk_rows,
        )
        created_spools.append(spool)
        return spool

    result = simulate(
        config,
        {market_id: market},
        stores,
        warehouses,
        {market_id: variants},
        start,
        end,
        spool_factory=new_spool,
        customer_population=CustomerPopulation(config, start, end),
    )
    for spool in created_spools:
        spool.flush()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return (
        market_id,
        result,
        created_spools,
        {
            "wallSeconds": round(runtime_time.perf_counter() - started, 6),
            "cpuSeconds": round(
                usage.ru_utime
                + usage.ru_stime
                - cpu_started.ru_utime
                - cpu_started.ru_stime,
                6,
            ),
            "peakRssBytes": (
                int(usage.ru_maxrss)
                if sys.platform == "darwin"
                else int(usage.ru_maxrss) * 1024
            ),
        },
    )


def _merge_market_simulations(
    results_by_market: dict[str, dict[str, Any]],
    writer: SourceWriter,
) -> dict[str, Any]:
    """Merge process-local results without loading run-sized rows into RAM."""

    ordered_results = [
        results_by_market[market_id]
        for market_id in sorted(results_by_market)
    ]
    merged: dict[str, Any] = {}
    for field in _SIMULATION_SEQUENCE_FIELDS:
        merged[field] = _ChainedRows(result[field] for result in ordered_results)

    orders = writer.new_spool("simulation-orders-merged")
    orders_by_day_and_key = heap_merge(
        *(iter(result["orders"]) for result in ordered_results),
        key=lambda row: (row["createdAt"][:10], row["orderKey"]),
    )
    source_sequence = 0
    for _, day_orders_iter in groupby(
        orders_by_day_and_key,
        key=lambda row: row["createdAt"][:10],
    ):
        day_orders = list(day_orders_iter)
        for order in sorted(
            day_orders,
            key=lambda row: (row["createdAt"], row["orderKey"]),
        ):
            source_sequence += 1
            order["sourceOrderSequence"] = source_sequence
            order["sourceOrderName"] = shopify_order_name(source_sequence)
        orders.extend(sorted(day_orders, key=lambda row: row["orderKey"]))
    merged["orders"] = orders

    # Stream-join the globally sequenced order headers back onto their lines.
    # The resulting dense number is collision-free at any run size while the
    # join remains bounded to one current header and line.
    order_lines = writer.new_spool("simulation-order-lines-merged")
    order_iterator = iter(orders)
    current_order = next(order_iterator, None)
    for line in heap_merge(
        *(iter(result["orderLines"]) for result in ordered_results),
        key=lambda row: (row["day"], row["orderKey"], row["lineNumber"]),
    ):
        line_key = (line["day"].isoformat(), line["orderKey"])
        while current_order is not None and (
            current_order["createdAt"][:10],
            current_order["orderKey"],
        ) < line_key:
            current_order = next(order_iterator, None)
        if current_order is None or (
            current_order["createdAt"][:10],
            current_order["orderKey"],
        ) != line_key:
            raise ValueError(
                f"order line {line['lineKey']!r} has no merged order header"
            )
        line["sourceOrderSequence"] = current_order["sourceOrderSequence"]
        order_lines.append(line)
    merged["orderLines"] = order_lines

    merged["storeAssortment"] = [
        row
        for result in ordered_results
        for row in result["storeAssortment"]
    ]
    for field in ("openingInventory", "finalInventory"):
        merged[field] = {
            key: value
            for result in ordered_results
            for key, value in result[field].items()
        }
    for field in _SIMULATION_MARKET_STREAM_FIELDS:
        merged[field] = {
            market_id: stream
            for result in ordered_results
            for market_id, stream in result[field].items()
        }
    return merged


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
    order_events: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    controls: dict[str, dict[str, Any]] = {}
    prior_order: dict[str, str] = {}
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
        if event["orderKey"] != prior_order.get(currency):
            control["orders"] += 1
            prior_order[currency] = event["orderKey"]
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
    *,
    spool_factory: Any | None = None,
) -> Any:
    """Project every simulated inventory movement into one BC register."""

    variants_by_sku = {
        variant["sku"]: variant
        for warehouse_id in company_warehouse_ids
        for variant in variants_by_market[warehouses[warehouse_id]["marketId"]]
    }
    rows = (
        spool_factory("business-central-item-ledger")
        if spool_factory
        else []
    )
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
                document_number=bc_document_number(
                    "WR",
                    (
                        f"{receipt['warehouseId']}:{receipt['expectedDate']}:"
                        f"{receipt['brandCode']}:{receipt['actualDate']}"
                    ),
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
                document_number=bc_document_number(
                    "TO",
                    transfer["transferKey"],
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
                document_number=bc_document_number(
                    "TO",
                    transfer["transferKey"],
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
                document_number=f"SI-{event['sourceOrderSequence']:014d}",
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
    sort_key = lambda row: (
        row["postingDate"],
        row["locationCode"],
        row["sku"],
        row["entryType"],
        row["id"],
    )
    ordered_rows: Iterable[dict[str, Any]]
    if isinstance(rows, RowSpool):
        ordered_rows = rows.iter_sorted(key=sort_key)
    else:
        ordered_rows = iter(sorted(rows, key=sort_key))

    def numbered_rows() -> Iterable[dict[str, Any]]:
        for entry_number, row in enumerate(ordered_rows, start=1):
            yield {**row, "entryNumber": entry_number}

    return numbered_rows()


def _price_history_rows(
    config: dict[str, Any],
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
            event_cost = _event_effect(
                config,
                day,
                market["marketId"],
                department_id=variant["_departmentId"],
                category_id=variant["_categoryId"],
            )["cost"]
            pandemic_cost = _pandemic_effect(
                config,
                day,
                market["marketId"],
                department_id=variant["_departmentId"],
                category_id=variant["_categoryId"],
                catalog_family=variant["_catalogFamily"],
            )["cost"]
            price, lifecycle_phase = _effective_list_price(
                variant,
                market,
                day,
                start,
                end,
                cost_multiplier=event_cost * pandemic_cost,
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
    *,
    cost_multiplier: Decimal = Decimal("1"),
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
            price = _promotional_price(
                price,
                variant,
                market,
                day,
                start,
                end,
                effect["offerDiscountPct"],
                effect["offerId"],
                effect["offerType"],
                cost_multiplier,
            )
            lifecycle_phase = effect["offerType"]
    return (
        price.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN),
        lifecycle_phase,
    )


def generate(
    config: dict[str, Any],
    output_root: str | None = None,
    *,
    execution_profile: dict[str, Any] | None = None,
    profile_name: str | None = None,
    market_workers: int | None = None,
    workers: int | None = None,
    duckdb_threads: int | None = None,
    memory_limit_gb: float | None = None,
    spool_chunk_rows: int | None = None,
) -> dict[str, Any]:
    """Generate and atomically publish one deterministic source run."""

    generation_started = runtime_time.perf_counter()
    cpu_started = resource.getrusage(resource.RUSAGE_SELF)
    stage_seconds: dict[str, float] = {}
    config = validate_config(config)
    if execution_profile is None:
        execution_profile = resolve_profile(
            profile_name,
            datagen_overrides={
                "marketWorkers": market_workers,
                "partitionWorkers": workers,
                "duckdbThreads": duckdb_threads,
                "memoryLimitGb": memory_limit_gb,
                "spoolChunkRows": spool_chunk_rows,
            },
            # Library callers get a hermetic default. The CLI resolves the
            # process environment explicitly before invoking generate().
            environment={},
        )
    else:
        execution_profile = dict(execution_profile)
        validate_profile(execution_profile)
    datagen_execution = execution_profile["datagen"]
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
        workers=datagen_execution["partitionWorkers"],
        duckdb_threads=datagen_execution["duckdbThreads"],
        memory_limit_gb=datagen_execution["memoryLimitGb"],
        spool_chunk_rows=datagen_execution["spoolChunkRows"],
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
        stage_started = runtime_time.perf_counter()
        catalog = build_catalog(config)
        stage_seconds["catalog"] = round(
            runtime_time.perf_counter() - stage_started,
            6,
        )
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
        stage_started = runtime_time.perf_counter()
        market_work_root = writer.work_directory / "market-processes"
        market_work_root.mkdir(parents=True, exist_ok=True)
        market_arguments = []
        for market_id in sorted(markets):
            market_work_directory = market_work_root / market_id
            market_work_directory.mkdir(parents=True, exist_ok=True)
            market_arguments.append(
                (
                    config,
                    market_id,
                    markets[market_id],
                    {
                        store_id: store
                        for store_id, store in stores.items()
                        if store["marketId"] == market_id
                    },
                    {
                        warehouse_id: warehouse
                        for warehouse_id, warehouse in warehouses.items()
                        if warehouse["marketId"] == market_id
                    },
                    variant_rows_by_market[market_id],
                    start,
                    end,
                    str(market_work_directory),
                    datagen_execution["spoolChunkRows"],
                )
            )
        market_results: list[
            tuple[
                str,
                dict[str, Any],
                list[RowSpool],
                dict[str, float | int],
            ]
        ] = []
        market_workers = datagen_execution["marketWorkers"]
        if market_workers == 1:
            market_results = [
                _simulate_market(*arguments)
                for arguments in market_arguments
            ]
        else:
            with ProcessPoolExecutor(max_workers=market_workers) as executor:
                futures = [
                    executor.submit(_simulate_market, *arguments)
                    for arguments in market_arguments
                ]
                market_results = [future.result() for future in futures]
        process_spools = [
            spool
            for _, _, spools, _ in market_results
            for spool in spools
        ]
        writer.adopt_spools(process_spools)
        simulation = _merge_market_simulations(
            {
                market_id: result
                for market_id, result, _, _ in market_results
            },
            writer,
        )
        customer_population = CustomerPopulation(config, start, end)
        stage_seconds["simulation"] = round(
            runtime_time.perf_counter() - stage_started,
            6,
        )
        order_events = simulation["orderLines"]
        order_headers = simulation["orders"]
        demand_truth = simulation["demandTruth"]
        stage_started = runtime_time.perf_counter()
        commerce_extensions = build_commerce_extensions(
            config,
            order_events,
            order_headers,
            spool_factory=writer.new_spool,
        )
        order_headers = commerce_extensions["orders"]
        supply_extensions = build_supply_extensions(
            config,
            markets,
            warehouses,
            variant_rows_by_market,
            simulation,
            spool_factory=writer.new_spool,
        )
        marketing_extensions = build_marketing_extensions(
            config,
            variant_rows_by_market,
            automatic_lifecycle_promotions,
        )
        stage_seconds["extensions"] = round(
            runtime_time.perf_counter() - stage_started,
            6,
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
                    config,
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
            shop_store_ids = set(shop["storeIds"])

            def shop_orders() -> Iterable[dict[str, Any]]:
                return (
                    event
                    for event in order_events
                    if event["marketId"] == market_id
                    and event["storeId"] in shop_store_ids
                )

            def shop_order_headers() -> Iterable[dict[str, Any]]:
                return (
                    order
                    for order in order_headers
                    if order["marketId"] == market_id
                    and order["storeId"] in shop_store_ids
                )

            writer.write_dataset(
                f"{shop_dir}/customers.csv",
                (
                    {
                        "id": shopify_gid("Customer", row["customerKey"]),
                        "syntheticCustomerKey": row["customerKey"],
                        "segmentId": row["segmentId"],
                        "createdAt": row["createdAt"],
                        "state": row["state"],
                        "email": "",
                        "phone": "",
                        "firstName": "",
                        "lastName": "",
                        "directIdentifiersPresent": "false",
                    }
                    for row in customer_population.records([market_id])
                    if row["segmentId"] != "walk-in"
                ),
                source_system="shopify",
                dataset="customers",
            )
            writer.write_dataset(
                f"{shop_dir}/orders.csv",
                (
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
                        "displayFinancialStatus": order["_financialStatus"],
                        "displayFulfillmentStatus": order[
                            "_fulfillmentStatus"
                        ],
                        "locationId": shopify_gid("Location", order["storeId"]),
                        "sourceName": "pos" if "store" in order["channelId"] else "web",
                        "customerSegmentId": order["customerSegmentId"],
                        "customerId": (
                            shopify_gid("Customer", order["customerKey"])
                            if order["customerKey"]
                            else ""
                        ),
                        "channelId": order["channelId"],
                        "lineCount": order["lineCount"],
                    }
                    for order in shop_order_headers()
                ),
                source_system="shopify",
                dataset="orders",
            )
            writer.write_dataset(
                f"{shop_dir}/order_lines.csv",
                (
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
                    for event in shop_orders()
                ),
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
                    (
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
                    ),
                    source_system="shopify",
                    dataset="inventoryQuantities",
                )
            def belongs_to_shop(row: dict[str, Any]) -> bool:
                return (
                    row.get("__marketId") == market_id
                    and row.get("__storeId") in shop_store_ids
                )

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
                    writer.write_dataset(
                        f"{shop_dir}/{filename}",
                        (
                            row
                            for row in commerce_extensions[key]
                            if belongs_to_shop(row)
                        ),
                        source_system="shopify",
                        dataset=dataset,
                    )
            writer.write_dataset(
                f"{shop_dir}/tax_lines.csv",
                (
                    row
                    for row in commerce_extensions["taxLines"]
                    if belongs_to_shop(row)
                ),
                source_system="shopify",
                dataset="taxLines",
            )
            if config["operations"]["features"]["returnsAndRefunds"]:
                for filename, dataset, rows in (
                    (
                        "returns.csv",
                        "returns",
                        (
                            row
                            for row in commerce_extensions["returns"]
                            if belongs_to_shop(row)
                        ),
                    ),
                    (
                        "return_lines.csv",
                        "returnLines",
                        (
                            row
                            for row in commerce_extensions["returnLines"]
                            if belongs_to_shop(row)
                        ),
                    ),
                    (
                        "refunds.csv",
                        "refunds",
                        (
                            row
                            for row in commerce_extensions["refunds"]
                            if belongs_to_shop(row)
                        ),
                    ),
                    (
                        "refund_transactions.csv",
                        "refundTransactions",
                        (
                            row
                            for row in commerce_extensions["refundTransactions"]
                            if belongs_to_shop(row)
                        ),
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
                    (
                        row
                        for row in commerce_extensions["webhookFixtures"]
                        if row["shopDomain"] == shop["shopDomain"]
                    ),
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
            def company_orders() -> Iterable[dict[str, Any]]:
                return (
                    event
                    for event in order_events
                    if event["marketId"] in company_markets
                )

            def company_order_headers() -> Iterable[dict[str, Any]]:
                return (
                    order
                    for order in order_headers
                    if order["marketId"] in company_markets
                )

            def company_customers() -> Iterable[dict[str, Any]]:
                for customer_sequence, row in enumerate(
                    customer_population.records(company_markets),
                    start=1,
                ):
                    yield {
                        "id": bc_uuid("Customer", row["customerKey"]),
                        # Business Central Customer No. is a natural key. A
                        # dense sequence over deterministic source order is
                        # collision-free, unlike the previous 9-digit hash.
                        "number": f"C{customer_sequence:014d}",
                        "displayName": (
                            "Walk-in synthetic customer"
                            if row["segmentId"] == "walk-in"
                            else "Registered synthetic customer"
                        ),
                        "marketCode": row["marketId"],
                        "segmentCode": row["segmentId"],
                        "createdAt": row["createdAt"],
                        "email": "",
                        "phoneNumber": "",
                        "blocked": str(row["state"] != "ENABLED").lower(),
                        "directIdentifiersPresent": "false",
                    }

            writer.write_dataset(
                f"{company_dir}/customers.csv",
                company_customers(),
                source_system="businessCentral",
                dataset="customers",
            )
            writer.write_dataset(
                f"{company_dir}/sales_invoices.csv",
                (
                    {
                        "id": bc_uuid("SalesInvoice", order["orderKey"]),
                        "number": f"SI-{order['sourceOrderSequence']:014d}",
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
                            order["bcCustomerKey"],
                        ),
                        "salesChannelCode": order["channelId"],
                    }
                    for order in company_order_headers()
                ),
                source_system="businessCentral",
                dataset="salesInvoices",
            )
            writer.write_dataset(
                f"{company_dir}/sales_invoice_lines.csv",
                (
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
                    for event in company_orders()
                    for allocation_index, allocation in enumerate(
                        event["allocations"]
                    )
                ),
                source_system="businessCentral",
                dataset="salesInvoiceLines",
            )
            writer.write_dataset(
                f"{company_dir}/item_ledger_entries.csv",
                _bc_item_ledger_rows(
                    company_warehouse_ids,
                    company_orders(),
                    warehouses,
                    variant_rows_by_market,
                    simulation,
                    start,
                    end,
                    spool_factory=writer.new_spool,
                ),
                source_system="businessCentral",
                dataset="itemLedgerEntries",
            )
            writer.write_dataset(
                f"{company_dir}/inventory_snapshots.csv",
                (
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
                ),
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
                    filtered: Iterable[dict[str, Any]] = (
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
                    )
                    if key == "vendorItemTerms":
                        filtered = (
                            row for row in rows if row["vendorId"] in allowed_vendor_ids
                        )
                    elif key == "purchaseOrderLines":
                        filtered = (
                            row for row in rows if row["documentId"] in allowed_po_ids
                        )
                    elif key == "inboundShipments":
                        filtered = (
                            row
                            for row in rows
                            if row["purchaseOrderId"] in allowed_po_ids
                        )
                    elif key == "warehouseReceiptLines":
                        filtered = (
                            row
                            for row in rows
                            if row["documentId"] in allowed_receipt_ids
                        )
                    elif key == "supplierPerformance":
                        filtered = (
                            row
                            for row in rows
                            if row["receiptLineId"] in allowed_receipt_line_ids
                        )
                    elif key == "transferOrderLines":
                        filtered = (
                            row
                            for row in rows
                            if row["documentId"] in allowed_transfer_ids
                        )
                    elif key == "transferShipments":
                        filtered = (
                            row
                            for row in rows
                            if row["transferOrderId"] in allowed_transfer_ids
                        )
                    filtered_iterator = iter(filtered)
                    first_filtered = next(filtered_iterator, None)
                    if first_filtered is not None:
                        writer.write_dataset(
                            f"{company_dir}/{filename}",
                            chain([first_filtered], filtered_iterator),
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
                        "skus": "|".join(promotion.get("_skus", [])),
                        "customerSegmentIds": "|".join(
                            promotion["customerSegmentIds"]
                        ),
                        "discountPct": promotion["discountPct"],
                        "discountBasis": "planned-offer",
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
                    "skus",
                    "customerSegmentIds",
                    "discountPct",
                    "discountBasis",
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
                    (
                        row
                        for row in simulation["allocationRequests"]
                        if row["marketKey"] == market_id
                    ),
                    source_system="companion",
                    dataset="allocationDemandRequests",
                )
                writer.write_dataset(
                    f"{companion_dir}/allocation_supply_pools.csv",
                    (
                        row
                        for row in simulation["supplyPools"]
                        if row["marketKey"] == market_id
                    ),
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
                (
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
                ),
                source_system="hiddenTruth",
                dataset="sourceEventCrosswalk",
                restricted=True,
            )
            writer.write_dataset(
                "_truth/inventory_constraint_truth.csv",
                (
                    {
                        "marketKey": row["marketKey"],
                        "storeKey": row["storeKey"],
                        "channelId": row["channelId"],
                        "date": row["date"],
                        "sku": row["sku"],
                        "latentDemandUnits": row["latentDemandUnits"],
                        "realizedSalesUnits": row["realizedSalesUnits"],
                        "lostSalesUnits": row["lostSalesUnits"],
                    }
                    for row in demand_truth
                ),
                source_system="hiddenTruth",
                dataset="inventoryConstraintTruth",
                restricted=True,
            )
            writer.write_dataset(
                "_truth/competitor_match_truth.csv",
                (
                    row
                    for market_rows in simulation["competitorMatches"].values()
                    for row in market_rows
                ),
                source_system="hiddenTruth",
                dataset="competitorMatchTruth",
                restricted=True,
            )

        writer.write_source_schema()
        writer.write_duckdb_mirror()
        stage_seconds["sourcePublication"] = float(
            writer.telemetry["sourcePublicationSeconds"]
        )
        stage_seconds["duckdbMirror"] = float(
            writer.telemetry["duckdbMirrorSeconds"]
        )
        latent_units = sum(row["latentDemandUnits"] for row in demand_truth)
        realized_units = sum(row["realizedSalesUnits"] for row in demand_truth)
        lost_units = sum(row["lostSalesUnits"] for row in demand_truth)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_parent_rss_bytes = (
            int(usage.ru_maxrss)
            if sys.platform == "darwin"
            else int(usage.ru_maxrss) * 1024
        )
        peak_child_rss_bytes = max(
            (
                int(telemetry["peakRssBytes"])
                for _, _, _, telemetry in market_results
            ),
            default=0,
        )
        elapsed_before_manifest = (
            runtime_time.perf_counter() - generation_started
        )
        cpu_seconds = (
            usage.ru_utime
            + usage.ru_stime
            - cpu_started.ru_utime
            - cpu_started.ru_stime
            + sum(
                float(telemetry["cpuSeconds"])
                for _, _, _, telemetry in market_results
                if datagen_execution["marketWorkers"] > 1
            )
        )
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
            "executionProfile": {
                "rowStorage": "bounded-disk-spool",
                "schemaVersion": execution_profile["schemaVersion"],
                "profile": execution_profile["profile"],
                **datagen_execution,
                "affectsRunIdentity": False,
            },
            "executionTelemetry": {
                "stageWallSeconds": stage_seconds,
                "elapsedBeforeManifestSeconds": round(elapsed_before_manifest, 6),
                "cpuProcessSeconds": round(cpu_seconds, 6),
                "cpuUtilizationPct": round(
                    cpu_seconds / max(elapsed_before_manifest, 0.000001) * 100,
                    2,
                ),
                "peakProcessRssBytes": max(
                    peak_parent_rss_bytes,
                    peak_child_rss_bytes,
                ),
                "peakParentRssBytes": peak_parent_rss_bytes,
                "peakMarketWorkerRssBytes": peak_child_rss_bytes,
                "datasetsPublished": writer.telemetry["datasetsPublished"],
                "publishedObjectBytes": sum(
                    int(source_object["bytes"])
                    for source_object in writer.objects
                ),
                "temporaryWorkBytesBeforeCleanup": writer.work_size_bytes(),
                "marketWorkerProcessesUsed": min(
                    datagen_execution["marketWorkers"],
                    len(markets),
                ),
                "marketWorkers": {
                    market_id: telemetry
                    for market_id, _, _, telemetry in market_results
                },
                "measurementScope": (
                    "parent and market-worker process metrics; peak RSS is the "
                    "largest observed process, not concurrent aggregate RSS; "
                    "operating-system cache is excluded"
                ),
            },
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
