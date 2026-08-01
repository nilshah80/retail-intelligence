"""Source-shaped operational fixtures derived from the causal simulation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_EVEN
from itertools import groupby
from typing import Any

from .identity import (
    bc_document_number,
    bc_uuid,
    shopify_gid,
    stable_integer,
)
from .operations import add_hours, fulfillment_timestamps

MONEY_QUANT = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN))


def _fraction(*parts: Any) -> float:
    return stable_integer(*parts, modulo=1_000_000) / 1_000_000


def _allocate_tax_components(
    total_tax: Decimal,
    components: list[dict[str, Any]],
) -> list[Decimal]:
    """Allocate rounded tax components with an exact final-slice residual."""

    allocated = Decimal("0")
    result: list[Decimal] = []
    for index, component in enumerate(components):
        amount = (
            total_tax - allocated
            if index == len(components) - 1
            else (
                total_tax * Decimal(component["share"])
            ).quantize(MONEY_QUANT, rounding=ROUND_HALF_EVEN)
        )
        result.append(amount)
        allocated += amount
    return result


def build_commerce_extensions(
    config: dict[str, Any],
    order_lines: Any,
    orders: Any,
    *,
    spool_factory: Any | None = None,
) -> dict[str, Any]:
    """Build fulfillment, return/refund, tax, and webhook evidence."""

    master_seed = config["identity"]["masterSeed"]
    return_policy = config["operations"]["returns"]
    def rows(name: str) -> Any:
        return spool_factory(name) if spool_factory else []

    markets = {row["marketId"]: row for row in config["markets"]}
    extract_end = date.fromisoformat(config["time"]["endDate"])
    fulfillment_orders = rows("commerce-fulfillment-orders")
    fulfillment_order_lines = rows("commerce-fulfillment-order-lines")
    fulfillments = rows("commerce-fulfillments")
    fulfillment_lines = rows("commerce-fulfillment-lines")
    fulfillment_history = rows("commerce-fulfillment-history")
    tax_lines = rows("commerce-tax-lines")
    returns = rows("commerce-returns")
    return_lines = rows("commerce-return-lines")
    refunds = rows("commerce-refunds")
    refund_transactions = rows("commerce-refund-transactions")
    fulfillment_summaries = rows("commerce-fulfillment-summaries")
    line_sequence_by_market: dict[str, int] = defaultdict(int)
    refund_sequence_by_market: dict[str, int] = defaultdict(int)

    fixture_orders_by_market: dict[
        str,
        list[tuple[dict[str, Any], list[dict[str, Any]]]],
    ] = defaultdict(list)
    grouped_lines = iter(groupby(order_lines, key=lambda row: row["orderKey"]))
    for order in orders:
        try:
            line_order_key, line_group = next(grouped_lines)
        except StopIteration as exc:
            raise RuntimeError(
                f"missing order lines for {order['orderKey']}"
            ) from exc
        if line_order_key != order["orderKey"]:
            raise RuntimeError(
                "order/line stream alignment failed: "
                f"{order['orderKey']} != {line_order_key}"
            )
        order_lines_for_order = list(line_group)
        if len(fixture_orders_by_market[order["marketId"]]) < 12:
            fixture_orders_by_market[order["marketId"]].append(
                (order, order_lines_for_order)
            )
        extract_timestamp = datetime.combine(
            extract_end,
            datetime.max.time(),
            tzinfo=datetime.fromisoformat(order["createdAt"]).tzinfo,
        )
        by_warehouse: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for line in order_lines_for_order:
            for allocation in line["allocations"]:
                by_warehouse[allocation["warehouseId"]].append((line, allocation))
        created_fulfillment_count = 0
        for warehouse_id, allocated_lines in sorted(by_warehouse.items()):
            fulfillment_order_key = (
                f"{order['orderKey']}:{warehouse_id}:fulfillment-order"
            )
            fulfillment_key = f"{order['orderKey']}:{warehouse_id}"
            fulfillment_id = shopify_gid("Fulfillment", fulfillment_key)
            created_at, delivered_at = fulfillment_timestamps(
                config,
                order["orderKey"],
                warehouse_id,
                order["createdAt"],
            )
            created_by_extract = (
                datetime.fromisoformat(created_at) <= extract_timestamp
            )
            delivered_by_extract = (
                datetime.fromisoformat(delivered_at) <= extract_timestamp
            )
            fulfillment_orders.append(
                {
                    "id": shopify_gid(
                        "FulfillmentOrder",
                        fulfillment_order_key,
                    ),
                    "orderId": shopify_gid("Order", order["orderKey"]),
                    "status": "CLOSED" if created_by_extract else "OPEN",
                    "requestStatus": (
                        "SUBMITTED" if created_by_extract else "UNSUBMITTED"
                    ),
                    "createdAt": order["createdAt"],
                    "updatedAt": (
                        delivered_at
                        if delivered_by_extract
                        else (
                            created_at
                            if created_by_extract
                            else order["createdAt"]
                        )
                    ),
                    "deliveryMethod": "SHIPPING",
                    "destinationLocationId": shopify_gid(
                        "Location",
                        warehouse_id,
                    ),
                    "__marketId": order["marketId"],
                    "__storeId": order["storeId"],
                }
            )
            for line, allocation in allocated_lines:
                fulfillment_order_lines.append(
                    {
                        "id": shopify_gid(
                            "FulfillmentOrderLineItem",
                            f"{fulfillment_order_key}:{line['lineKey']}",
                        ),
                        "fulfillmentOrderId": shopify_gid(
                            "FulfillmentOrder",
                            fulfillment_order_key,
                        ),
                        "orderLineId": shopify_gid(
                            "OrderLine",
                            line["lineKey"],
                        ),
                        "sku": line["sku"],
                        "totalQuantity": allocation["quantity"],
                        "remainingQuantity": (
                            0 if created_by_extract else allocation["quantity"]
                        ),
                        "warehouseKey": warehouse_id,
                        "__partitionDate": line["createdAt"][:10],
                        "__marketId": order["marketId"],
                        "__storeId": order["storeId"],
                    }
                )
            if not created_by_extract:
                continue
            created_fulfillment_count += 1
            fulfillments.append(
                {
                    "id": fulfillment_id,
                    "orderId": shopify_gid("Order", order["orderKey"]),
                    "fulfillmentOrderId": shopify_gid(
                        "FulfillmentOrder",
                        fulfillment_order_key,
                    ),
                    "locationId": shopify_gid("Location", warehouse_id),
                    "status": "SUCCESS",
                    "shipmentStatus": (
                        "DELIVERED" if delivered_by_extract else "IN_TRANSIT"
                    ),
                    "createdAt": created_at,
                    "deliveredAt": delivered_at if delivered_by_extract else "",
                    "trackingCompany": "Synthetic Parcel Network",
                    "trackingNumber": (
                        f"SPN{stable_integer(fulfillment_key, modulo=10**12):012d}"
                    ),
                    "__marketId": order["marketId"],
                    "__storeId": order["storeId"],
                }
            )
            for line, allocation in allocated_lines:
                fulfillment_lines.append(
                    {
                        "id": shopify_gid(
                            "FulfillmentLineItem",
                            f"{fulfillment_key}:{line['lineKey']}",
                        ),
                        "fulfillmentId": fulfillment_id,
                        "orderLineId": shopify_gid("OrderLine", line["lineKey"]),
                        "sku": line["sku"],
                        "quantity": allocation["quantity"],
                        "warehouseKey": warehouse_id,
                        "__partitionDate": line["createdAt"][:10],
                        "__marketId": order["marketId"],
                        "__storeId": order["storeId"],
                    }
                )
            status_events = [
                ("SUBMITTED", order["createdAt"]),
                ("IN_PROGRESS", created_at),
                ("DELIVERED", delivered_at),
                ("CLOSED", add_hours(delivered_at, 1)),
            ]
            for sequence, (status, timestamp) in enumerate(
                [
                    event
                    for event in status_events
                    if datetime.fromisoformat(event[1]) <= extract_timestamp
                ],
                start=1,
            ):
                fulfillment_history.append(
                    {
                        "fulfillmentId": fulfillment_id,
                        "sequence": sequence,
                        "status": status,
                        "occurredAt": timestamp,
                        "warehouseKey": warehouse_id,
                        "__marketId": order["marketId"],
                        "__storeId": order["storeId"],
                    }
                )
        fulfillment_summaries.append(
            {
                "orderKey": order["orderKey"],
                "expected": len(by_warehouse),
                "created": created_fulfillment_count,
            }
        )

    successful_refunds_by_order: dict[str, Decimal] = defaultdict(
        lambda: Decimal("0")
    )
    for line in order_lines:
        market = markets[line["marketId"]]
        line_sequence_by_market[line["marketId"]] += 1
        forced_fixture_return = line_sequence_by_market[line["marketId"]] <= 2
        components = (
            [{"code": "Maharashtra-VAT", "share": "1.0"}]
            if (
                market["countryCode"] == "IN"
                and date.fromisoformat(line["createdAt"][:10])
                < date(2017, 7, 1)
            )
            else market["localePack"]["tax"]["components"]["intraRegion"]
        )
        jurisdiction = (
            "Maharashtra-VAT"
            if (
                market["countryCode"] == "IN"
                and date.fromisoformat(line["createdAt"][:10])
                < date(2017, 7, 1)
            )
            else market["localePack"]["tax"]["jurisdiction"]
        )
        for component, component_tax in zip(
            components,
            _allocate_tax_components(line["tax"], components),
            strict=True,
        ):
            tax_lines.append(
                {
                    "orderLineId": shopify_gid("OrderLine", line["lineKey"]),
                    "orderId": shopify_gid("Order", line["orderKey"]),
                    "title": component["code"],
                    "rate": str(line["taxRate"]),
                    "shareOfTax": component["share"],
                    "price": _money(component_tax),
                    "currencyCode": line["currencyCode"],
                    "jurisdiction": jurisdiction,
                    "__partitionDate": line["createdAt"][:10],
                    "__marketId": line["marketId"],
                    "__storeId": line["storeId"],
                }
            )
        if (
            not forced_fixture_return
            and _fraction(master_seed, "return-request", line["lineKey"])
            >= float(line["returnProbability"])
        ):
            continue
        return_key = f"{line['lineKey']}:return"
        requested_at = add_hours(line["createdAt"], 24 * 7)
        target_processed_at = add_hours(requested_at, 48)
        request_by_extract = (
            date.fromisoformat(requested_at[:10]) <= extract_end
        )
        if not request_by_extract:
            continue
        decision_by_extract = (
            date.fromisoformat(target_processed_at[:10]) <= extract_end
        )
        selected_for_processing = forced_fixture_return or (
            _fraction(master_seed, "return-processed", line["lineKey"])
            < return_policy["processingRate"]
        )
        processed = decision_by_extract and selected_for_processing
        processed_quantity = 1 if processed else 0
        return_status = (
            "CLOSED"
            if processed
            else ("DECLINED" if decision_by_extract else "OPEN")
        )
        returns.append(
            {
                "id": shopify_gid("Return", return_key),
                "orderId": shopify_gid("Order", line["orderKey"]),
                "name": f"RET-{stable_integer(return_key, modulo=10**9):09d}",
                "status": return_status,
                "requestedAt": requested_at,
                "processedAt": target_processed_at if decision_by_extract else "",
                "reason": ["SIZE_TOO_SMALL", "NOT_AS_DESCRIBED", "UNWANTED"][
                    stable_integer(return_key, modulo=3)
                ],
                "__marketId": line["marketId"],
                "__storeId": line["storeId"],
            }
        )
        return_lines.append(
            {
                "id": shopify_gid("ReturnLineItem", return_key),
                "returnId": shopify_gid("Return", return_key),
                "orderLineId": shopify_gid("OrderLine", line["lineKey"]),
                "sku": line["sku"],
                "requestedQuantity": 1,
                "processedQuantity": processed_quantity,
                # Returns are refunded but intentionally not restocked unless
                # the inventory simulation also posts the corresponding stock
                # movement. This keeps Shopify and BC inventory evidence aligned.
                "restockType": "NO_RESTOCK",
                "restockLocationId": "",
                "__partitionDate": requested_at[:10],
                "__marketId": line["marketId"],
                "__storeId": line["storeId"],
            }
        )
        if not processed:
            continue
        refund_key = f"{line['lineKey']}:refund"
        refund_amount = line["gross"] / Decimal(line["quantity"])
        refund_sequence_by_market[line["marketId"]] += 1
        fixture_sequence = refund_sequence_by_market[line["marketId"]]
        if fixture_sequence == 1:
            succeeded = True
        elif fixture_sequence == 2:
            succeeded = False
        else:
            succeeded = (
                _fraction(master_seed, "refund-success", line["lineKey"])
                >= return_policy["refundFailureRate"]
            )
        refunds.append(
            {
                "id": shopify_gid("Refund", refund_key),
                "orderId": shopify_gid("Order", line["orderKey"]),
                "returnId": shopify_gid("Return", return_key),
                "createdAt": add_hours(requested_at, 49),
                "totalRefunded": _money(refund_amount if succeeded else Decimal("0")),
                "currencyCode": line["currencyCode"],
                "status": "SUCCESS" if succeeded else "FAILED",
                "__marketId": line["marketId"],
                "__storeId": line["storeId"],
            }
        )
        if succeeded:
            successful_refunds_by_order[
                shopify_gid("Order", line["orderKey"])
            ] += refund_amount
        refund_transactions.append(
            {
                "id": shopify_gid("OrderTransaction", refund_key),
                "refundId": shopify_gid("Refund", refund_key),
                "orderId": shopify_gid("Order", line["orderKey"]),
                "kind": "REFUND",
                "gateway": "synthetic-payments",
                "status": "SUCCESS" if succeeded else "FAILURE",
                "amount": _money(refund_amount),
                "currencyCode": line["currencyCode"],
                "processedAt": add_hours(requested_at, 49),
                "errorCode": "" if succeeded else "PROCESSING_ERROR",
                "__marketId": line["marketId"],
                "__storeId": line["storeId"],
            }
        )

    enriched_orders = rows("commerce-enriched-orders")
    for order, summary in zip(
        orders,
        fulfillment_summaries,
        strict=True,
    ):
        if summary["orderKey"] != order["orderKey"]:
            raise RuntimeError(
                "order/fulfillment summary alignment failed: "
                f"{order['orderKey']} != {summary['orderKey']}"
            )
        order_id = shopify_gid("Order", order["orderKey"])
        refunded = successful_refunds_by_order.get(
            order_id,
            Decimal("0"),
        )
        expected = summary["expected"]
        created = summary["created"]
        enriched_orders.append(
            {
                **order,
                "_financialStatus": (
                    "REFUNDED"
                    if refunded >= order["gross"]
                    else ("PARTIALLY_REFUNDED" if refunded > 0 else "PAID")
                ),
                "_fulfillmentStatus": (
                    "FULFILLED"
                    if expected and created == expected
                    else ("PARTIALLY_FULFILLED" if created else "UNFULFILLED")
                ),
            }
        )

    webhook_fixtures = rows("commerce-webhook-fixtures")
    secret = config["operations"]["webhook"]["fixtureSecret"].encode("utf-8")
    invalid_rate = config["operations"]["webhook"]["invalidFixtureRate"]
    fixture_orders = [
        order_and_lines
        for market_id in sorted(fixture_orders_by_market)
        for order_and_lines in fixture_orders_by_market[market_id]
    ]
    webhook_sequence_by_market: dict[str, int] = defaultdict(int)
    for index, (order, fixture_lines) in enumerate(fixture_orders):
        payload = {
            "id": shopify_gid("Order", order["orderKey"]),
            "name": order["sourceOrderName"],
            "created_at": order["createdAt"],
            "currency": order["currencyCode"],
            "total_price": _money(order["gross"]),
            "line_items": [
                {
                    "id": shopify_gid("OrderLine", line["lineKey"]),
                    "sku": line["sku"],
                    "quantity": line["quantity"],
                }
                for line in fixture_lines
            ],
        }
        body = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        valid_hmac = base64.b64encode(
            hmac.new(secret, body.encode("utf-8"), hashlib.sha256).digest()
        ).decode("ascii")
        webhook_sequence_by_market[order["marketId"]] += 1
        fixture_sequence = webhook_sequence_by_market[order["marketId"]]
        if fixture_sequence == 1:
            valid_expected = True
        elif fixture_sequence == 2:
            valid_expected = False
        else:
            valid_expected = (
                _fraction(master_seed, "webhook-validity", order["orderKey"])
                >= invalid_rate
            )
        supplied_hmac = (
            valid_hmac
            if valid_expected
            else base64.b64encode(
                hmac.new(
                    secret,
                    (body + "-tampered").encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("ascii")
        )
        webhook_fixtures.append(
            {
                "fixtureId": f"orders-create-{index + 1:03d}",
                "topic": "orders/create",
                "shopDomain": next(
                    row["shopDomain"]
                    for row in config["sourceInstances"]["shopify"]
                    if row["marketId"] == order["marketId"]
                ),
                "webhookId": (
                    f"{stable_integer('webhook', order['orderKey'], modulo=10**16):016d}"
                ),
                "apiVersion": "2026-07",
                "body": body,
                "hmacHeader": supplied_hmac,
                "validExpected": str(valid_expected).lower(),
                "idParityOrderId": shopify_gid("Order", order["orderKey"]),
            }
        )

    return {
        "orders": enriched_orders,
        "fulfillmentOrders": fulfillment_orders,
        "fulfillmentOrderLines": fulfillment_order_lines,
        "fulfillments": fulfillments,
        "fulfillmentLines": fulfillment_lines,
        "fulfillmentStatusHistory": fulfillment_history,
        "taxLines": tax_lines,
        "returns": returns,
        "returnLines": return_lines,
        "refunds": refunds,
        "refundTransactions": refund_transactions,
        "webhookFixtures": webhook_fixtures,
    }


def _bc_iso(day: date, hour: int, timezone: str) -> str:
    from zoneinfo import ZoneInfo
    from datetime import time as _time

    return datetime.combine(
        day, _time(hour=min(23, max(0, hour))), tzinfo=ZoneInfo(timezone)
    ).isoformat()


def build_supply_extensions(
    config: dict[str, Any],
    markets: dict[str, dict[str, Any]],
    warehouses: dict[str, dict[str, Any]],
    variants_by_market: dict[str, list[dict[str, Any]]],
    simulation: dict[str, Any],
    *,
    spool_factory: Any | None = None,
) -> dict[str, Any]:
    """Build supplier, receipt, batch, transfer, warehouse, and WMS evidence."""

    def rows(name: str) -> Any:
        return spool_factory(name) if spool_factory else []

    master_seed = config["identity"]["masterSeed"]
    end = date.fromisoformat(config["time"]["endDate"])
    vendors: list[dict[str, Any]] = []
    vendor_terms: list[dict[str, Any]] = []
    vendor_seen: set[tuple[str, str]] = set()
    term_seen: set[tuple[str, str, str]] = set()
    for market_id, variants in sorted(variants_by_market.items()):
        for variant in variants:
            vendor_identity = (market_id, variant["_brandCode"])
            vendor_key = f"supplier:{market_id}:{variant['_brandCode']}"
            if vendor_identity not in vendor_seen:
                vendor_seen.add(vendor_identity)
                vendor_number = (
                    f"V{stable_integer(vendor_key, modulo=10**7):07d}"
                )
                vendors.append(
                    {
                        "id": bc_uuid("Vendor", vendor_key),
                        "number": vendor_number,
                        # Keep recognizable product brands in the catalog without
                        # fabricating delivery-performance claims about the brand
                        # owner or one of its competitors.
                        "displayName": (
                            f"Synthetic Approved Distributor {market_id.upper()} "
                            f"{vendor_number}"
                        ),
                        "brandName": variant["_brand"],
                        "brandCode": variant["_brandCode"],
                        "marketCode": market_id,
                        "currencyCode": markets[market_id]["currencyCode"],
                        "blocked": "false",
                    }
                )
            term_identity = (
                market_id,
                variant["_brandCode"],
                variant["_categoryId"],
            )
            if term_identity in term_seen:
                continue
            term_seen.add(term_identity)
            vendor_terms.append(
                {
                    "vendorId": bc_uuid("Vendor", vendor_key),
                    "marketCode": market_id,
                    "categoryId": variant["_categoryId"],
                    "minimumOrderQuantity": 12,
                    "orderMultiple": 6,
                    "leadTimeDays": config["operations"]["inventory"][
                        "supplierLeadTimeDays"
                    ],
                    "leadTimeStdDevDays": config["operations"]["inventory"][
                        "supplierLeadTimeJitterDays"
                    ],
                    "capacityUnitsPerMonth": 2000
                    + stable_integer(vendor_key, modulo=3000),
                    "paymentTermsCode": "NET30",
                }
            )

    # ------------------------------------------------------------------
    # Source contract v13: origin-safe, varied supply terms.
    #
    # The v1 `vendorItemTerms` above are deliberately retained -- they are what
    # the accepted pin ingested, and rewriting them would rebaseline v12
    # consumers. Their defects are exactly why `supplyTerms` exists beside them:
    # every row carries lead 5 / MOQ 12 / pack 6, category scope only, and no
    # destination or origin, which reads as a wildcard downstream. Terms that
    # never vary produce a zero-variance safety stock, and a null origin let an
    # external supplier term match an internal transfer lane by accident.
    #
    # v13 terms are destination-scoped, carry an explicit external origin, vary
    # deterministically by (vendor, destination, scope), and exercise the
    # sku > dept > category precedence the resolver must implement: category is
    # the base, roughly a third of vendor x dept pairs carry an override, and a
    # twelfth of SKUs carry an exact term.
    # ------------------------------------------------------------------
    supply_terms = rows("supply-terms")
    start = date.fromisoformat(config["time"]["startDate"])

    def _term_values(*identity: str) -> dict[str, Any]:
        lead = 4 + stable_integer("term-lead", *identity, modulo=6)          # 4..9
        std_tenths = 5 + stable_integer("term-std", *identity, modulo=21)   # 0.5..2.5
        moq = (6, 12, 24, 48)[stable_integer("term-moq", *identity, modulo=4)]
        pack = (4, 6, 12)[stable_integer("term-pack", *identity, modulo=3)]
        return {
            "leadTimeDays": lead,
            "leadTimeStdDevDays": f"{std_tenths / 10:.1f}",
            "minimumOrderQuantity": moq,
            "orderMultiple": pack,
        }

    if config["operations"]["features"].get("storeInventory"):
        term_scope_seen: set[tuple[str, ...]] = set()
        for market_id, variants in sorted(variants_by_market.items()):
            market_warehouses = sorted(
                warehouse["warehouseId"]
                for warehouse in warehouses.values()
                if warehouse["marketId"] == market_id
            )
            for variant in variants:
                vendor_key = f"supplier:{market_id}:{variant['_brandCode']}"
                for warehouse_id in market_warehouses:
                    scopes: list[tuple[str, str]] = [
                        ("category", variant["_categoryId"])
                    ]
                    if stable_integer(
                        "term-dept-override",
                        vendor_key,
                        warehouse_id,
                        variant["_departmentId"],
                        modulo=3,
                    ) == 0:
                        scopes.append(("dept", variant["_departmentId"]))
                    if stable_integer(
                        "term-sku-override",
                        vendor_key,
                        warehouse_id,
                        variant["sku"],
                        modulo=12,
                    ) == 0:
                        scopes.append(("sku", variant["sku"]))
                    for scope_type, scope_id in scopes:
                        identity = (
                            vendor_key,
                            warehouse_id,
                            scope_type,
                            scope_id,
                        )
                        if identity in term_scope_seen:
                            continue
                        term_scope_seen.add(identity)
                        timezone = markets[market_id]["timezone"]
                        supply_terms.append(
                            {
                                "vendorId": bc_uuid("Vendor", vendor_key),
                                "destinationLocationCode": warehouses[
                                    warehouse_id
                                ]["businessCentralLocationCode"],
                                "originKind": "external_supplier",
                                "merchScopeType": scope_type,
                                "merchScopeId": scope_id,
                                "effectiveFrom": start.isoformat(),
                                **_term_values(*identity),
                                "capacityUnitsPerMonth": 2000
                                + stable_integer(
                                    "term-capacity", *identity, modulo=3000
                                ),
                                "paymentTermsCode": "NET30",
                                "observedAt": _bc_iso(start, 8, timezone),
                            }
                        )

    po_headers: dict[str, dict[str, Any]] = {}
    po_lines = rows("supply-purchase-order-lines")
    inbound_shipments: dict[str, dict[str, Any]] = {}
    # v13: status history per shipment. `inboundShipments` above keeps only the
    # CURRENT status, so a position was reconstructible at the cutoff and nowhere
    # else. Each transition is timed by when it became true (statusEffectiveAt)
    # and separately by when it became knowable (observedAt, strictly later):
    # Gate B B05 requires known_as_of >= status_effective_at.
    inbound_status_events = rows("supply-inbound-status-events")
    inbound_status_seen: set[str] = set()
    receipt_headers: dict[str, dict[str, Any]] = {}
    receipt_lines = rows("supply-warehouse-receipt-lines")
    cost_layers = rows("supply-item-cost-layers")
    supplier_performance = rows("supply-supplier-performance")
    po_line_sequence: dict[str, int] = defaultdict(int)
    for receipt in simulation["receiptEvents"]:
        vendor_key = f"supplier:{receipt['marketId']}:{receipt['brandCode']}"
        po_key = (
            f"{receipt['warehouseId']}:{receipt['expectedDate']}:"
            f"{receipt['brandCode']}"
        )
        po_headers.setdefault(
            po_key,
            {
                "id": bc_uuid("PurchaseOrder", po_key),
                "number": f"PO-{stable_integer(po_key, modulo=10**8):08d}",
                "warehouseId": receipt["warehouseId"],
                "locationCode": warehouses[receipt["warehouseId"]][
                    "businessCentralLocationCode"
                ],
                "orderDate": receipt["orderDate"],
                "expectedReceiptDate": receipt["expectedDate"],
                "vendorId": bc_uuid("Vendor", vendor_key),
                "status": (
                    "Released"
                    if date.fromisoformat(receipt["actualDate"]) > end
                    else "Received"
                ),
                "currencyCode": receipt["currencyCode"],
            },
        )
        po_line_sequence[po_key] += 10_000
        received_quantity = (
            receipt["quantity"] if receipt["status"] == "Received" else 0
        )
        po_lines.append(
            {
                "id": bc_uuid("PurchaseOrderLine", receipt["receiptKey"]),
                "documentId": bc_uuid("PurchaseOrder", po_key),
                "lineNumber": po_line_sequence[po_key],
                "vendorId": bc_uuid("Vendor", vendor_key),
                "itemNumber": receipt["productCode"],
                "variantCode": receipt["variantCode"],
                "sku": receipt["sku"],
                "orderedQuantity": receipt["orderedQuantity"],
                "receivedQuantity": received_quantity,
                "outstandingQuantity": (
                    receipt["orderedQuantity"] - received_quantity
                ),
                "directUnitCost": _money(receipt["unitCost"]),
                "currencyCode": receipt["currencyCode"],
            }
        )
        if (
            config["operations"]["features"].get("storeInventory")
            and po_key not in inbound_status_seen
        ):
            inbound_status_seen.add(po_key)
            shipment_id = bc_uuid("InboundShipment", po_key)
            timezone = markets[
                warehouses[receipt["warehouseId"]]["marketId"]
            ]["timezone"]
            order_day = date.fromisoformat(receipt["orderDate"])
            actual_day = (
                date.fromisoformat(receipt["actualDate"])
                if receipt["status"] == "Received"
                else None
            )
            # Dispatch the day after ordering, clamped so a fast receipt can
            # never dispatch after it arrived.
            dispatch_day = order_day + timedelta(days=1)
            if actual_day is not None and dispatch_day > actual_day:
                dispatch_day = order_day
            transitions: list[tuple[str, date]] = [
                ("on_order", order_day),
                ("in_transit", dispatch_day),
            ]
            if actual_day is not None:
                transitions.append(("received", actual_day))
            for status_name, status_day in transitions:
                inbound_status_events.append(
                    {
                        "shipmentId": shipment_id,
                        "sku": receipt["sku"],
                        "locationCode": warehouses[receipt["warehouseId"]][
                            "businessCentralLocationCode"
                        ],
                        "quantity": receipt["quantity"],
                        "status": status_name,
                        # Effective at 08:00 local; knowable at 10:00 the same
                        # day. Two hours of processing delay keeps B05's
                        # known_as_of >= status_effective_at strict rather than
                        # degenerate-equal.
                        "statusEffectiveAt": _bc_iso(status_day, 8, timezone),
                        "observedAt": _bc_iso(status_day, 10, timezone),
                        "expectedReceiptDate": receipt["expectedDate"],
                    }
                )
        inbound_shipments.setdefault(
            po_key,
            {
                "shipmentId": bc_uuid("InboundShipment", po_key),
                "purchaseOrderId": bc_uuid("PurchaseOrder", po_key),
                "warehouseId": receipt["warehouseId"],
                "expectedArrivalDate": receipt["expectedDate"],
                "actualArrivalDate": (
                    receipt["actualDate"] if receipt["status"] == "Received" else ""
                ),
                "status": receipt["status"],
                "carrier": "Synthetic Freight Network",
                "trackingNumber": (
                    f"SFN{stable_integer('inbound', po_key, modulo=10**12):012d}"
                ),
            },
        )
        if receipt["status"] != "Received":
            continue
        receipt_key = f"{po_key}:{receipt['actualDate']}"
        receipt_headers.setdefault(
            receipt_key,
            {
                "id": bc_uuid("WarehouseReceipt", receipt_key),
                "number": bc_document_number("WR", receipt_key),
                "purchaseOrderId": bc_uuid("PurchaseOrder", po_key),
                "locationCode": warehouses[receipt["warehouseId"]][
                    "businessCentralLocationCode"
                ],
                "postingDate": receipt["actualDate"],
                "status": "Posted",
            },
        )
        receipt_lines.append(
            {
                "id": bc_uuid("WarehouseReceiptLine", receipt["receiptKey"]),
                "documentId": bc_uuid("WarehouseReceipt", receipt_key),
                "itemNumber": receipt["productCode"],
                "variantCode": receipt["variantCode"],
                "sku": receipt["sku"],
                "quantity": receipt["quantity"],
                "unitCost": _money(receipt["unitCost"]),
                "currencyCode": receipt["currencyCode"],
            }
        )
        cost_layers.append(
            {
                "costLayerId": bc_uuid("ItemCostLayer", receipt["receiptKey"]),
                "sku": receipt["sku"],
                "warehouseId": receipt["warehouseId"],
                "effectiveDate": receipt["actualDate"],
                "costingMethod": receipt["costingMethod"],
                "quantity": receipt["quantity"],
                "unitCost": _money(receipt["unitCost"]),
                "currencyCode": receipt["currencyCode"],
                "sourceReceiptId": bc_uuid("WarehouseReceipt", receipt_key),
            }
        )
        supplier_performance.append(
            {
                "vendorId": bc_uuid("Vendor", vendor_key),
                "receiptLineId": bc_uuid("WarehouseReceiptLine", receipt["receiptKey"]),
                "marketCode": receipt["marketId"],
                "expectedDate": receipt["expectedDate"],
                "actualDate": receipt["actualDate"],
                "onTime": str(
                    date.fromisoformat(receipt["actualDate"])
                    <= date.fromisoformat(receipt["expectedDate"])
                ).lower(),
                "leadTimeDays": (
                    date.fromisoformat(receipt["actualDate"])
                    - date.fromisoformat(receipt["orderDate"])
                ).days,
                "orderedQuantity": receipt["orderedQuantity"],
                "receivedQuantity": receipt["quantity"],
                "fillRate": str(
                    (
                        Decimal(receipt["quantity"])
                        / Decimal(receipt["orderedQuantity"])
                    ).quantize(Decimal("0.0001"))
                ),
            }
        )

    batches = rows("supply-item-batches")
    for row in simulation["batchBalances"]:
        batches.append(
            {
                "batchId": bc_uuid("ItemBatch", row["batchKey"]),
                "lotNumber": (
                    f"LOT-{stable_integer(row['batchKey'], modulo=10**10):010d}"
                ),
                "sku": row["sku"],
                "warehouseId": row["warehouseId"],
                "locationCode": warehouses[row["warehouseId"]][
                    "businessCentralLocationCode"
                ],
                "manufactureDate": row["manufactureDate"],
                "receiptDate": row["receiptDate"],
                "expiryDate": row["expiryDate"],
                "quantityReceived": row["quantityReceived"],
                "quantityRemainingAtExtract": row[
                    "quantityRemainingAtExtract"
                ],
                "sourceType": row["sourceType"],
                "sourceReference": row["sourceReference"],
            }
        )

    transfer_orders = rows("supply-transfer-orders")
    transfer_lines = rows("supply-transfer-lines")
    transfer_shipments = rows("supply-transfer-shipments")
    for transfer in simulation["transferEvents"]:
        transfer_orders.append(
            {
                "id": bc_uuid("TransferOrder", transfer["transferKey"]),
                "number": bc_document_number(
                    "TO",
                    transfer["transferKey"],
                ),
                "fromLocationCode": warehouses[transfer["fromWarehouseId"]][
                    "businessCentralLocationCode"
                ],
                "toLocationCode": warehouses[transfer["toWarehouseId"]][
                    "businessCentralLocationCode"
                ],
                "requestDate": transfer["requestDate"],
                "orderDate": transfer["orderDate"],
                "status": transfer["status"],
            }
        )
        transfer_lines.append(
            {
                "id": bc_uuid("TransferOrderLine", transfer["transferKey"]),
                "documentId": bc_uuid("TransferOrder", transfer["transferKey"]),
                "itemNumber": transfer["productCode"],
                "variantCode": transfer["variantCode"],
                "sku": transfer["sku"],
                "requestedQuantity": transfer["requestedQuantity"],
                "shippedQuantity": transfer["shippedQuantity"],
                "receivedQuantity": transfer["receivedQuantity"],
            }
        )
        transfer_shipments.append(
            {
                "id": bc_uuid("TransferShipment", transfer["transferKey"]),
                "transferOrderId": bc_uuid("TransferOrder", transfer["transferKey"]),
                "shipmentDate": transfer["shipmentDate"],
                "receiptDate": transfer["receiptDate"],
                "status": transfer["status"],
                "quantity": transfer["receivedQuantity"],
            }
        )

    warehouse_capacity = rows("supply-warehouse-capacity")
    wms_comparisons = rows("supply-wms-comparisons")
    observations_by_warehouse_time: dict[
        tuple[str, str],
        dict[str, int],
    ] = defaultdict(lambda: {"onHand": 0, "blocked": 0})
    for observation in simulation["inventoryObservations"]:
        totals = observations_by_warehouse_time[
            (observation["warehouseKey"], observation["observedAt"])
        ]
        totals["onHand"] += observation["onHand"]
        totals["blocked"] += observation["blocked"]
        variance = (
            -1
            if _fraction(
                master_seed,
                "wms-variance",
                observation["warehouseKey"],
                observation["sku"],
                observation["observedAt"],
            )
            < 0.02
            else 0
        )
        wms_comparisons.append(
            {
                "warehouseId": observation["warehouseKey"],
                "observedAt": observation["observedAt"],
                "sku": observation["sku"],
                "erpOnHand": observation["onHand"],
                "wmsOnHand": observation["onHand"] + variance,
                "varianceQuantity": variance,
                "comparisonStatus": "mismatch" if variance else "matched",
            }
        )
    for (warehouse_id, observed_at), totals in sorted(
        observations_by_warehouse_time.items()
    ):
        capacity = warehouses[warehouse_id]["capacityUnits"]
        on_hand = totals["onHand"]
        blocked = totals["blocked"]
        warehouse_capacity.append(
            {
                "warehouseId": warehouse_id,
                "observedAt": observed_at,
                "capacityUnits": capacity,
                "onHandUnits": on_hand,
                "blockedUnits": blocked,
                "utilizationPct": str(
                    (Decimal(on_hand) / Decimal(capacity)).quantize(Decimal("0.0001"))
                ),
                "dockToStockHours": 4
                + stable_integer(warehouse_id, observed_at, modulo=18),
            }
        )

    waste_events = [
        {
            "wasteEventId": bc_uuid("WasteEvent", row["wasteEventKey"]),
            "warehouseId": row["warehouseId"],
            "sku": row["sku"],
            "batchId": bc_uuid("ItemBatch", row["batchKey"]),
            "eventDate": row["eventDate"],
            "quantity": row["quantity"],
            "reason": row["reason"],
        }
        for row in simulation["wasteEvents"]
    ]

    supplier_capacity: list[dict[str, Any]] = []
    purchasing_budgets: list[dict[str, Any]] = []
    scenario_start = date.fromisoformat(config["time"]["startDate"])
    cursor = date(scenario_start.year, scenario_start.month, 1)
    last_month = date(end.year, end.month, 1)
    while cursor <= last_month:
        period = cursor.strftime("%Y-%m")
        for vendor in vendors:
            requested = 1400 + stable_integer(
                vendor["id"],
                period,
                "requested-capacity",
                modulo=1000,
            )
            confirmed = min(
                requested,
                1600
                + stable_integer(
                    vendor["id"],
                    period,
                    "confirmed-capacity",
                    modulo=1200,
                ),
            )
            supplier_capacity.append(
                {
                    "vendorId": vendor["id"],
                    "marketCode": vendor["marketCode"],
                    "periodMonth": period,
                    "requestedCapacityUnits": requested,
                    "confirmedCapacityUnits": confirmed,
                    "confirmationStatus": (
                        "fully-confirmed" if confirmed == requested else "constrained"
                    ),
                    "confirmedAt": cursor.isoformat(),
                }
            )
        for market_id, market in sorted(markets.items()):
            amount = Decimal("250000") + Decimal(
                stable_integer(
                    master_seed,
                    "purchasing-budget",
                    market_id,
                    period,
                    modulo=250_000,
                )
            )
            purchasing_budgets.append(
                {
                    "marketCode": market_id,
                    "periodMonth": period,
                    "budgetAmount": _money(amount),
                    "currencyCode": market["currencyCode"],
                    "budgetStatus": "Approved",
                }
            )
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )

    return {
        "vendors": vendors,
        "vendorItemTerms": vendor_terms,
        "supplyTerms": supply_terms,
        "purchaseOrders": list(po_headers.values()),
        "purchaseOrderLines": po_lines,
        "inboundShipments": list(inbound_shipments.values()),
        "inboundStatusEvents": inbound_status_events,
        "warehouseReceipts": list(receipt_headers.values()),
        "warehouseReceiptLines": receipt_lines,
        "itemCostLayers": cost_layers,
        "itemBatches": batches,
        "supplierPerformance": supplier_performance,
        "supplierCapacityConfirmations": supplier_capacity,
        "purchasingBudgets": purchasing_budgets,
        "transferOrders": transfer_orders,
        "transferOrderLines": transfer_lines,
        "transferShipments": transfer_shipments,
        "warehouseCapacity": warehouse_capacity,
        "wmsInventoryComparisons": wms_comparisons,
        "wasteEvents": waste_events,
    }


def build_marketing_extensions(
    config: dict[str, Any],
    variants_by_market: dict[str, list[dict[str, Any]]],
    automatic_promotions: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Resolve campaign and lifecycle-promotion merchandise scopes."""

    promotion_skus: list[dict[str, Any]] = []
    for promotion in config["promotions"] + (automatic_promotions or []):
        for variant in variants_by_market[promotion["marketId"]]:
            if promotion.get("_skus") and variant["sku"] not in promotion["_skus"]:
                continue
            department_match = (
                not promotion["departmentIds"]
                or variant["_departmentId"] in promotion["departmentIds"]
            )
            category_match = (
                not promotion["categoryIds"]
                or variant["_categoryId"] in promotion["categoryIds"]
            )
            if not department_match or not category_match:
                continue
            promotion_skus.append(
                {
                    "marketKey": promotion["marketId"],
                    "promotionId": promotion["promotionId"],
                    "sku": variant["sku"],
                    "departmentId": variant["_departmentId"],
                    "categoryId": variant["_categoryId"],
                    "discountPct": promotion["discountPct"],
                    "discountBasis": "planned-offer",
                    "effectiveFrom": promotion["startDate"],
                    "effectiveTo": promotion["endDate"],
                }
            )
    return {
        "promotionSkus": promotion_skus,
        "customerSegments": [
            {
                "segmentId": row["segmentId"],
                "name": row["name"],
                "scenarioShare": row["share"],
                "demandMultiplier": row["demandMultiplier"],
            }
            for row in config["customerSegments"]
        ],
    }
