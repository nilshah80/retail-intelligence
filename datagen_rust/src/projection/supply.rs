//! Business Central supply-chain projections.

use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

use anyhow::{Context, Result};
use bigdecimal::RoundingMode;
use chrono::{Datelike, Duration, NaiveDate};

use crate::catalog::{Product, Variant};
use crate::config::{BusinessCentralInstance, LoadedConfig, Market};
use crate::deterministic::{bc_document_number, bc_uuid, stable_integer};
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::model::FieldValues;
use crate::simulation::operations::local_iso_at;

type Emit<'a> = &'a mut dyn FnMut(&str, &str, &str, bool, FieldValues);

#[derive(Debug, Clone)]
struct Vendor {
    id: String,
    market_id: String,
    brand_code: String,
}

#[allow(clippy::too_many_arguments)]
pub fn build_supply_datasets(
    config: &LoadedConfig,
    catalog: &[Product],
    receipts: &[FieldValues],
    transfers: &[FieldValues],
    losses: &[FieldValues],
    waste: &[FieldValues],
    batches: &[FieldValues],
    observations: &[FieldValues],
    sales_ledger: &[FieldValues],
    include_item_ledger: bool,
    emit: Emit<'_>,
) -> Result<()> {
    if !feature(config, "supplyChain") {
        return Ok(());
    }
    let vendors = vendors(config, catalog);
    if feature(config, "storeInventory") {
        emit_supply_terms(config, catalog, emit)?;
    }
    emit_purchase_and_receipt_rows(config, receipts, emit)?;
    emit_batches(config, batches, emit)?;
    if feature(config, "transfers") {
        emit_transfers(config, transfers, emit)?;
    }
    if feature(config, "warehouseOperations") {
        emit_warehouse_rows(config, observations, waste, emit)?;
    }
    if feature(config, "supplierPlanning") {
        emit_supplier_planning(config, &vendors, emit)?;
    }
    if include_item_ledger {
        emit_item_ledger(
            config,
            batches,
            receipts,
            transfers,
            losses,
            waste,
            sales_ledger,
            emit,
        )?;
    }
    Ok(())
}

fn emit_supply_terms(config: &LoadedConfig, catalog: &[Product], emit: Emit<'_>) -> Result<()> {
    let mut seen = BTreeSet::<(String, String, String, String)>::new();
    let mut market_ids = config
        .scenario
        .markets
        .iter()
        .map(|row| row.market_id.clone())
        .collect::<Vec<_>>();
    market_ids.sort();
    for market_id in market_ids {
        let market = market(config, &market_id)?;
        let mut warehouses = config
            .scenario
            .warehouses
            .iter()
            .filter(|row| row.market_id == market_id)
            .collect::<Vec<_>>();
        warehouses.sort_by(|left, right| left.warehouse_id.cmp(&right.warehouse_id));
        for product in catalog.iter().filter(|row| row.market_id == market_id) {
            for variant in &product.variants {
                let vendor_key = format!("supplier:{market_id}:{}", product.brand_code);
                for warehouse in &warehouses {
                    let mut scopes = vec![("category", product.category_id.as_str())];
                    if stable_integer(
                        &[
                            "term-dept-override",
                            &vendor_key,
                            &warehouse.warehouse_id,
                            &product.department_id,
                        ],
                        3,
                    ) == 0
                    {
                        scopes.push(("dept", product.department_id.as_str()));
                    }
                    if stable_integer(
                        &[
                            "term-sku-override",
                            &vendor_key,
                            &warehouse.warehouse_id,
                            &variant.sku,
                        ],
                        12,
                    ) == 0
                    {
                        scopes.push(("sku", variant.sku.as_str()));
                    }
                    for (scope_type, scope_id) in scopes {
                        let identity = (
                            vendor_key.clone(),
                            warehouse.warehouse_id.clone(),
                            scope_type.to_owned(),
                            scope_id.to_owned(),
                        );
                        if !seen.insert(identity.clone()) {
                            continue;
                        }
                        let parts = [
                            identity.0.as_str(),
                            identity.1.as_str(),
                            identity.2.as_str(),
                            identity.3.as_str(),
                        ];
                        let lead = 4 + stable_integer(
                            &["term-lead", parts[0], parts[1], parts[2], parts[3]],
                            6,
                        );
                        let std_tenths = 5 + stable_integer(
                            &["term-std", parts[0], parts[1], parts[2], parts[3]],
                            21,
                        );
                        let moq = [6, 12, 24, 48][stable_integer(
                            &["term-moq", parts[0], parts[1], parts[2], parts[3]],
                            4,
                        ) as usize];
                        let pack = [4, 6, 12][stable_integer(
                            &["term-pack", parts[0], parts[1], parts[2], parts[3]],
                            3,
                        ) as usize];
                        let row = values([
                            ("vendorId", bc_uuid("Vendor", &vendor_key)),
                            (
                                "destinationLocationCode",
                                warehouse.business_central_location_code.clone(),
                            ),
                            ("originKind", "external_supplier".to_owned()),
                            ("merchScopeType", scope_type.to_owned()),
                            ("merchScopeId", scope_id.to_owned()),
                            ("effectiveFrom", config.scenario.time.start_date.to_string()),
                            ("leadTimeDays", lead.to_string()),
                            (
                                "leadTimeStdDevDays",
                                format!("{}.{:01}", std_tenths / 10, std_tenths % 10),
                            ),
                            ("minimumOrderQuantity", moq.to_string()),
                            ("orderMultiple", pack.to_string()),
                            (
                                "capacityUnitsPerMonth",
                                (2000
                                    + stable_integer(
                                        &["term-capacity", parts[0], parts[1], parts[2], parts[3]],
                                        3000,
                                    ))
                                .to_string(),
                            ),
                            ("paymentTermsCode", "NET30".to_owned()),
                            (
                                "observedAt",
                                local_iso_at(
                                    config.scenario.time.start_date,
                                    8,
                                    0,
                                    0,
                                    &market.timezone,
                                )?,
                            ),
                        ]);
                        for company in companies_for_warehouse(config, &warehouse.warehouse_id) {
                            emit_company(emit, company, "supplyTerms", row.clone());
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

fn emit_purchase_and_receipt_rows(
    config: &LoadedConfig,
    receipts: &[FieldValues],
    emit: Emit<'_>,
) -> Result<()> {
    let end = config.scenario.time.end_date;
    let mut po_headers = Vec::<(String, FieldValues)>::new();
    let mut po_index = BTreeMap::<String, usize>::new();
    let mut po_sequences = BTreeMap::<String, i64>::new();
    let mut inbound_shipments = Vec::<(String, FieldValues)>::new();
    let mut inbound_seen = BTreeSet::<String>::new();
    let mut receipt_headers = Vec::<(String, FieldValues)>::new();
    let mut receipt_header_seen = BTreeSet::<String>::new();

    for receipt in receipts {
        let vendor_key = format!("supplier:{}:{}", receipt["marketId"], receipt["brandCode"]);
        let po_key = format!(
            "{}:{}:{}",
            receipt["warehouseId"], receipt["expectedDate"], receipt["brandCode"]
        );
        if !po_index.contains_key(&po_key) {
            po_index.insert(po_key.clone(), po_headers.len());
            po_headers.push((
                receipt["warehouseId"].clone(),
                values([
                    ("id", bc_uuid("PurchaseOrder", &po_key)),
                    (
                        "number",
                        format!("PO-{:08}", stable_integer(&[&po_key], 100_000_000)),
                    ),
                    ("warehouseId", receipt["warehouseId"].clone()),
                    (
                        "locationCode",
                        warehouse_location(config, &receipt["warehouseId"])?.to_owned(),
                    ),
                    ("orderDate", receipt["orderDate"].clone()),
                    ("expectedReceiptDate", receipt["expectedDate"].clone()),
                    ("vendorId", bc_uuid("Vendor", &vendor_key)),
                    (
                        "status",
                        if parse_date(&receipt["actualDate"])? > end {
                            "Released"
                        } else {
                            "Received"
                        }
                        .to_owned(),
                    ),
                    ("currencyCode", receipt["currencyCode"].clone()),
                ]),
            ));
        }
        let sequence = po_sequences.entry(po_key.clone()).or_default();
        *sequence += 10_000;
        let received = if receipt["status"] == "Received" {
            integer(receipt, "quantity")?
        } else {
            0
        };
        let po_line = values([
            ("id", bc_uuid("PurchaseOrderLine", &receipt["receiptKey"])),
            ("documentId", bc_uuid("PurchaseOrder", &po_key)),
            ("lineNumber", sequence.to_string()),
            ("vendorId", bc_uuid("Vendor", &vendor_key)),
            ("itemNumber", receipt["productCode"].clone()),
            ("variantCode", receipt["variantCode"].clone()),
            ("sku", receipt["sku"].clone()),
            ("orderedQuantity", receipt["orderedQuantity"].clone()),
            ("receivedQuantity", received.to_string()),
            (
                "outstandingQuantity",
                (integer(receipt, "orderedQuantity")? - received).to_string(),
            ),
            ("directUnitCost", money_text(&receipt["unitCost"])?),
            ("currencyCode", receipt["currencyCode"].clone()),
        ]);
        for company in companies_for_warehouse(config, &receipt["warehouseId"]) {
            emit_company(emit, company, "purchaseOrderLines", po_line.clone());
        }

        if feature(config, "storeInventory") && inbound_seen.insert(po_key.clone()) {
            let shipment_id = bc_uuid("InboundShipment", &po_key);
            let market_id = warehouse_market(config, &receipt["warehouseId"])?;
            let timezone = &market(config, market_id)?.timezone;
            let order_day = parse_date(&receipt["orderDate"])?;
            let actual_day = (receipt["status"] == "Received")
                .then(|| parse_date(&receipt["actualDate"]))
                .transpose()?;
            let mut dispatch_day = order_day + Duration::days(1);
            if actual_day.is_some_and(|actual| dispatch_day > actual) {
                dispatch_day = order_day;
            }
            let mut transitions = vec![("on_order", order_day), ("in_transit", dispatch_day)];
            if let Some(actual) = actual_day {
                transitions.push(("received", actual));
            }
            for (status, status_day) in transitions {
                let row = values([
                    ("shipmentId", shipment_id.clone()),
                    ("sku", receipt["sku"].clone()),
                    (
                        "locationCode",
                        warehouse_location(config, &receipt["warehouseId"])?.to_owned(),
                    ),
                    ("quantity", receipt["quantity"].clone()),
                    ("status", status.to_owned()),
                    (
                        "statusEffectiveAt",
                        local_iso_at(status_day, 8, 0, 0, timezone)?,
                    ),
                    ("observedAt", local_iso_at(status_day, 10, 0, 0, timezone)?),
                    ("expectedReceiptDate", receipt["expectedDate"].clone()),
                ]);
                for company in companies_for_warehouse(config, &receipt["warehouseId"]) {
                    emit_company(emit, company, "inboundStatusEvents", row.clone());
                }
            }
        }

        if !inbound_shipments.iter().any(|(key, _)| key == &po_key) {
            inbound_shipments.push((
                po_key.clone(),
                values([
                    ("shipmentId", bc_uuid("InboundShipment", &po_key)),
                    ("purchaseOrderId", bc_uuid("PurchaseOrder", &po_key)),
                    ("warehouseId", receipt["warehouseId"].clone()),
                    ("expectedArrivalDate", receipt["expectedDate"].clone()),
                    (
                        "actualArrivalDate",
                        if receipt["status"] == "Received" {
                            receipt["actualDate"].clone()
                        } else {
                            String::new()
                        },
                    ),
                    ("status", receipt["status"].clone()),
                    ("carrier", "Synthetic Freight Network".to_owned()),
                    (
                        "trackingNumber",
                        format!(
                            "SFN{:012}",
                            stable_integer(&["inbound", &po_key], 10_u64.pow(12))
                        ),
                    ),
                ]),
            ));
        }

        if receipt["status"] != "Received" {
            continue;
        }
        let receipt_header_key = format!("{po_key}:{}", receipt["actualDate"]);
        if receipt_header_seen.insert(receipt_header_key.clone()) {
            receipt_headers.push((
                receipt["warehouseId"].clone(),
                values([
                    ("id", bc_uuid("WarehouseReceipt", &receipt_header_key)),
                    ("number", bc_document_number("WR", &receipt_header_key)),
                    ("purchaseOrderId", bc_uuid("PurchaseOrder", &po_key)),
                    (
                        "locationCode",
                        warehouse_location(config, &receipt["warehouseId"])?.to_owned(),
                    ),
                    ("postingDate", receipt["actualDate"].clone()),
                    ("status", "Posted".to_owned()),
                ]),
            ));
        }
        let receipt_line_id = bc_uuid("WarehouseReceiptLine", &receipt["receiptKey"]);
        let receipt_line = values([
            ("id", receipt_line_id.clone()),
            (
                "documentId",
                bc_uuid("WarehouseReceipt", &receipt_header_key),
            ),
            ("itemNumber", receipt["productCode"].clone()),
            ("variantCode", receipt["variantCode"].clone()),
            ("sku", receipt["sku"].clone()),
            ("quantity", receipt["quantity"].clone()),
            ("unitCost", money_text(&receipt["unitCost"])?),
            ("currencyCode", receipt["currencyCode"].clone()),
        ]);
        let cost_layer = values([
            (
                "costLayerId",
                bc_uuid("ItemCostLayer", &receipt["receiptKey"]),
            ),
            ("sku", receipt["sku"].clone()),
            ("warehouseId", receipt["warehouseId"].clone()),
            ("effectiveDate", receipt["actualDate"].clone()),
            ("costingMethod", receipt["costingMethod"].clone()),
            ("quantity", receipt["quantity"].clone()),
            ("unitCost", money_text(&receipt["unitCost"])?),
            ("currencyCode", receipt["currencyCode"].clone()),
            (
                "sourceReceiptId",
                bc_uuid("WarehouseReceipt", &receipt_header_key),
            ),
        ]);
        let fill_rate = (Decimal::from(integer(receipt, "quantity")?)
            / Decimal::from(integer(receipt, "orderedQuantity")?))
        .quantize(4, RoundingMode::HalfEven)
        .to_string();
        let performance = values([
            ("vendorId", bc_uuid("Vendor", &vendor_key)),
            ("receiptLineId", receipt_line_id),
            ("marketCode", receipt["marketId"].clone()),
            ("expectedDate", receipt["expectedDate"].clone()),
            ("actualDate", receipt["actualDate"].clone()),
            (
                "onTime",
                (parse_date(&receipt["actualDate"])? <= parse_date(&receipt["expectedDate"])?)
                    .to_string(),
            ),
            (
                "leadTimeDays",
                (parse_date(&receipt["actualDate"])? - parse_date(&receipt["orderDate"])?)
                    .num_days()
                    .to_string(),
            ),
            ("orderedQuantity", receipt["orderedQuantity"].clone()),
            ("receivedQuantity", receipt["quantity"].clone()),
            ("fillRate", fill_rate),
        ]);
        for company in companies_for_warehouse(config, &receipt["warehouseId"]) {
            emit_company(emit, company, "warehouseReceiptLines", receipt_line.clone());
            emit_company(emit, company, "itemCostLayers", cost_layer.clone());
            if feature(config, "supplierPlanning") {
                emit_company(emit, company, "supplierPerformance", performance.clone());
            }
        }
    }

    for (warehouse_id, row) in po_headers {
        for company in companies_for_warehouse(config, &warehouse_id) {
            emit_company(emit, company, "purchaseOrders", row.clone());
        }
    }
    for (_, row) in inbound_shipments {
        let warehouse_id = row["warehouseId"].clone();
        for company in companies_for_warehouse(config, &warehouse_id) {
            emit_company(emit, company, "inboundShipments", row.clone());
        }
    }
    for (warehouse_id, row) in receipt_headers {
        for company in companies_for_warehouse(config, &warehouse_id) {
            emit_company(emit, company, "warehouseReceipts", row.clone());
        }
    }
    Ok(())
}

fn emit_batches(config: &LoadedConfig, batches: &[FieldValues], emit: Emit<'_>) -> Result<()> {
    for batch in batches {
        let row = values([
            ("batchId", bc_uuid("ItemBatch", &batch["batchKey"])),
            (
                "lotNumber",
                format!(
                    "LOT-{:010}",
                    stable_integer(&[&batch["batchKey"]], 10_u64.pow(10))
                ),
            ),
            ("sku", batch["sku"].clone()),
            ("warehouseId", batch["warehouseId"].clone()),
            (
                "locationCode",
                warehouse_location(config, &batch["warehouseId"])?.to_owned(),
            ),
            ("manufactureDate", batch["manufactureDate"].clone()),
            ("receiptDate", batch["receiptDate"].clone()),
            ("expiryDate", batch["expiryDate"].clone()),
            ("quantityReceived", batch["quantityReceived"].clone()),
            (
                "quantityRemainingAtExtract",
                batch["quantityRemainingAtExtract"].clone(),
            ),
            ("sourceType", batch["sourceType"].clone()),
            ("sourceReference", batch["sourceReference"].clone()),
        ]);
        for company in companies_for_warehouse(config, &batch["warehouseId"]) {
            emit_company(emit, company, "itemBatches", row.clone());
        }
    }
    Ok(())
}

fn emit_transfers(config: &LoadedConfig, transfers: &[FieldValues], emit: Emit<'_>) -> Result<()> {
    for transfer in transfers {
        let order = values([
            ("id", bc_uuid("TransferOrder", &transfer["transferKey"])),
            ("number", bc_document_number("TO", &transfer["transferKey"])),
            (
                "fromLocationCode",
                warehouse_location(config, &transfer["fromWarehouseId"])?.to_owned(),
            ),
            (
                "toLocationCode",
                warehouse_location(config, &transfer["toWarehouseId"])?.to_owned(),
            ),
            ("requestDate", transfer["requestDate"].clone()),
            ("orderDate", transfer["orderDate"].clone()),
            ("status", transfer["status"].clone()),
        ]);
        let line = values([
            ("id", bc_uuid("TransferOrderLine", &transfer["transferKey"])),
            (
                "documentId",
                bc_uuid("TransferOrder", &transfer["transferKey"]),
            ),
            ("itemNumber", transfer["productCode"].clone()),
            ("variantCode", transfer["variantCode"].clone()),
            ("sku", transfer["sku"].clone()),
            ("requestedQuantity", transfer["requestedQuantity"].clone()),
            ("shippedQuantity", transfer["shippedQuantity"].clone()),
            ("receivedQuantity", transfer["receivedQuantity"].clone()),
        ]);
        let shipment = values([
            ("id", bc_uuid("TransferShipment", &transfer["transferKey"])),
            (
                "transferOrderId",
                bc_uuid("TransferOrder", &transfer["transferKey"]),
            ),
            ("shipmentDate", transfer["shipmentDate"].clone()),
            ("receiptDate", transfer["receiptDate"].clone()),
            ("status", transfer["status"].clone()),
            ("quantity", transfer["receivedQuantity"].clone()),
        ]);
        for company in companies_for_transfer(
            config,
            &transfer["fromWarehouseId"],
            &transfer["toWarehouseId"],
        ) {
            emit_company(emit, company, "transferOrders", order.clone());
            emit_company(emit, company, "transferOrderLines", line.clone());
            emit_company(emit, company, "transferShipments", shipment.clone());
        }
    }
    Ok(())
}

fn emit_warehouse_rows(
    config: &LoadedConfig,
    observations: &[FieldValues],
    waste: &[FieldValues],
    emit: Emit<'_>,
) -> Result<()> {
    let master = config.scenario.identity.master_seed.to_string();
    let mut totals = BTreeMap::<(String, String), (i64, i64)>::new();
    for observation in observations {
        let entry = totals
            .entry((
                observation["warehouseKey"].clone(),
                observation["observedAt"].clone(),
            ))
            .or_default();
        entry.0 += integer(observation, "onHand")?;
        entry.1 += integer(observation, "blocked")?;
        let variance = if fraction(&[
            &master,
            "wms-variance",
            &observation["warehouseKey"],
            &observation["sku"],
            &observation["observedAt"],
        ]) < 0.02
        {
            -1
        } else {
            0
        };
        let row = values([
            ("warehouseId", observation["warehouseKey"].clone()),
            ("observedAt", observation["observedAt"].clone()),
            ("sku", observation["sku"].clone()),
            ("erpOnHand", observation["onHand"].clone()),
            (
                "wmsOnHand",
                (integer(observation, "onHand")? + variance).to_string(),
            ),
            ("varianceQuantity", variance.to_string()),
            (
                "comparisonStatus",
                if variance == 0 { "matched" } else { "mismatch" }.to_owned(),
            ),
        ]);
        for company in companies_for_warehouse(config, &observation["warehouseKey"]) {
            emit_company(emit, company, "wmsInventoryComparisons", row.clone());
        }
    }
    for ((warehouse_id, observed_at), (on_hand, blocked)) in totals {
        let capacity = config
            .scenario
            .warehouses
            .iter()
            .find(|row| row.warehouse_id == warehouse_id)
            .context("capacity warehouse")?
            .capacity_units;
        let utilization = (Decimal::from(on_hand) / Decimal::from(capacity))
            .quantize(4, RoundingMode::HalfEven)
            .to_string();
        let row = values([
            ("warehouseId", warehouse_id.clone()),
            ("observedAt", observed_at.clone()),
            ("capacityUnits", capacity.to_string()),
            ("onHandUnits", on_hand.to_string()),
            ("blockedUnits", blocked.to_string()),
            ("utilizationPct", utilization),
            (
                "dockToStockHours",
                (4 + stable_integer(&[&warehouse_id, &observed_at], 18)).to_string(),
            ),
        ]);
        for company in companies_for_warehouse(config, &warehouse_id) {
            emit_company(emit, company, "warehouseCapacity", row.clone());
        }
    }
    for event in waste {
        let row = values([
            (
                "wasteEventId",
                bc_uuid("WasteEvent", &event["wasteEventKey"]),
            ),
            ("warehouseId", event["warehouseId"].clone()),
            ("sku", event["sku"].clone()),
            ("batchId", bc_uuid("ItemBatch", &event["batchKey"])),
            ("eventDate", event["eventDate"].clone()),
            ("quantity", event["quantity"].clone()),
            ("reason", event["reason"].clone()),
        ]);
        for company in companies_for_warehouse(config, &event["warehouseId"]) {
            emit_company(emit, company, "wasteEvents", row.clone());
        }
    }
    Ok(())
}

fn emit_supplier_planning(config: &LoadedConfig, vendors: &[Vendor], emit: Emit<'_>) -> Result<()> {
    let mut cursor = NaiveDate::from_ymd_opt(
        config.scenario.time.start_date.year(),
        config.scenario.time.start_date.month(),
        1,
    )
    .expect("start month");
    let last = NaiveDate::from_ymd_opt(
        config.scenario.time.end_date.year(),
        config.scenario.time.end_date.month(),
        1,
    )
    .expect("end month");
    let master = config.scenario.identity.master_seed.to_string();
    while cursor <= last {
        let period = cursor.format("%Y-%m").to_string();
        for vendor in vendors {
            let requested =
                1400 + stable_integer(&[&vendor.id, &period, "requested-capacity"], 1000);
            let confirmed = requested
                .min(1600 + stable_integer(&[&vendor.id, &period, "confirmed-capacity"], 1200));
            let row = values([
                ("vendorId", vendor.id.clone()),
                ("marketCode", vendor.market_id.clone()),
                ("periodMonth", period.clone()),
                ("requestedCapacityUnits", requested.to_string()),
                ("confirmedCapacityUnits", confirmed.to_string()),
                (
                    "confirmationStatus",
                    if confirmed == requested {
                        "fully-confirmed"
                    } else {
                        "constrained"
                    }
                    .to_owned(),
                ),
                ("confirmedAt", cursor.to_string()),
            ]);
            for company in companies_for_market(config, &vendor.market_id)? {
                emit_company(emit, company, "supplierCapacityConfirmations", row.clone());
            }
        }
        let mut markets = config.scenario.markets.iter().collect::<Vec<_>>();
        markets.sort_by(|left, right| left.market_id.cmp(&right.market_id));
        for market in markets {
            let amount = Decimal::from(250_000_i64)
                + Decimal::from(stable_integer(
                    &[&master, "purchasing-budget", &market.market_id, &period],
                    250_000,
                ));
            let row = values([
                ("marketCode", market.market_id.clone()),
                ("periodMonth", period.clone()),
                ("budgetAmount", money(&amount)),
                ("currencyCode", market.currency_code.clone()),
                ("budgetStatus", "Approved".to_owned()),
            ]);
            for company in companies_for_market(config, &market.market_id)? {
                emit_company(emit, company, "purchasingBudgets", row.clone());
            }
        }
        cursor = if cursor.month() == 12 {
            NaiveDate::from_ymd_opt(cursor.year() + 1, 1, 1).expect("next year")
        } else {
            NaiveDate::from_ymd_opt(cursor.year(), cursor.month() + 1, 1).expect("next month")
        };
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
fn emit_item_ledger(
    config: &LoadedConfig,
    batches: &[FieldValues],
    receipts: &[FieldValues],
    transfers: &[FieldValues],
    losses: &[FieldValues],
    waste: &[FieldValues],
    sales: &[FieldValues],
    emit: Emit<'_>,
) -> Result<()> {
    for company in &config.scenario.source_instances.business_central {
        let mut rows = item_ledger_rows_for_company(
            config, company, batches, receipts, transfers, losses, waste, sales,
        )?;
        rows.sort_by(|left, right| {
            (
                &left["postingDate"],
                &left["locationCode"],
                &left["sku"],
                &left["entryType"],
                &left["id"],
            )
                .cmp(&(
                    &right["postingDate"],
                    &right["locationCode"],
                    &right["sku"],
                    &right["entryType"],
                    &right["id"],
                ))
        });
        for (index, mut row) in rows.into_iter().enumerate() {
            row.insert("entryNumber", (index + 1).to_string());
            emit_company(emit, company, "itemLedgerEntries", row);
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub fn non_sales_item_ledger_rows(
    config: &LoadedConfig,
    batches: &[FieldValues],
    receipts: &[FieldValues],
    transfers: &[FieldValues],
    losses: &[FieldValues],
    waste: &[FieldValues],
) -> Result<Vec<(String, FieldValues)>> {
    let mut result = Vec::new();
    for company in &config.scenario.source_instances.business_central {
        for row in item_ledger_rows_for_company(
            config,
            company,
            batches,
            receipts,
            transfers,
            losses,
            waste,
            &[],
        )? {
            result.push((company.company_id.clone(), row));
        }
    }
    Ok(result)
}

pub fn sales_item_ledger_row(config: &LoadedConfig, sale: &FieldValues) -> Result<FieldValues> {
    ledger_row(
        &format!("sale:{}:{}", sale["lineKey"], sale["warehouseId"]),
        &sale["postingDate"],
        "Sale",
        sale,
        &sale["warehouseId"],
        -integer(sale, "quantity")?,
        &format!("SI-{:014}", integer(sale, "sourceOrderSequence")?),
        config,
    )
}

#[allow(clippy::too_many_arguments)]
fn item_ledger_rows_for_company(
    config: &LoadedConfig,
    company: &BusinessCentralInstance,
    batches: &[FieldValues],
    receipts: &[FieldValues],
    transfers: &[FieldValues],
    losses: &[FieldValues],
    waste: &[FieldValues],
    sales: &[FieldValues],
) -> Result<Vec<FieldValues>> {
    let warehouse_ids = company
        .warehouse_ids
        .iter()
        .map(String::as_str)
        .collect::<BTreeSet<_>>();
    let mut rows = Vec::<FieldValues>::new();
    for batch in batches.iter().filter(|row| {
        row["sourceType"] == "opening-balance"
            && warehouse_ids.contains(row["warehouseId"].as_str())
    }) {
        let business_key = format!(
            "opening:{}:{}:{}",
            batch["warehouseId"], batch["sku"], config.scenario.time.start_date
        );
        rows.push(ledger_row(
            &business_key,
            &config.scenario.time.start_date.to_string(),
            "Positive Adjmt.",
            batch,
            &batch["warehouseId"],
            integer(batch, "quantityReceived")?,
            &format!(
                "OPEN-{:08}",
                stable_integer(
                    &[
                        &batch["warehouseId"],
                        &batch["sku"],
                        &config.scenario.time.start_date.to_string(),
                    ],
                    99_999_999,
                )
            ),
            config,
        )?);
    }
    for receipt in receipts.iter().filter(|row| {
        warehouse_ids.contains(row["warehouseId"].as_str())
            && parse_date(&row["actualDate"]).is_ok_and(|day| day <= config.scenario.time.end_date)
    }) {
        let document_key = format!(
            "{}:{}:{}:{}",
            receipt["warehouseId"],
            receipt["expectedDate"],
            receipt["brandCode"],
            receipt["actualDate"]
        );
        rows.push(ledger_row(
            &format!("purchase:{}", receipt["receiptKey"]),
            &receipt["actualDate"],
            "Purchase",
            receipt,
            &receipt["warehouseId"],
            integer(receipt, "quantity")?,
            &bc_document_number("WR", &document_key),
            config,
        )?);
    }
    for transfer in transfers {
        if warehouse_ids.contains(transfer["fromWarehouseId"].as_str()) {
            rows.push(ledger_row(
                &format!("transfer-out:{}", transfer["transferKey"]),
                &transfer["shipmentDate"],
                "Transfer",
                transfer,
                &transfer["fromWarehouseId"],
                -integer(transfer, "shippedQuantity")?,
                &bc_document_number("TO", &transfer["transferKey"]),
                config,
            )?);
        }
        if warehouse_ids.contains(transfer["toWarehouseId"].as_str())
            && integer(transfer, "receivedQuantity")? != 0
        {
            rows.push(ledger_row(
                &format!("transfer-in:{}", transfer["transferKey"]),
                &transfer["receiptDate"],
                "Transfer",
                transfer,
                &transfer["toWarehouseId"],
                integer(transfer, "receivedQuantity")?,
                &bc_document_number("TO", &transfer["transferKey"]),
                config,
            )?);
        }
    }
    for sale in sales.iter().filter(|row| {
        warehouse_ids.contains(row["warehouseId"].as_str())
            && !row["fulfilledAt"].is_empty()
            && parse_date(&row["postingDate"]).is_ok_and(|day| day <= config.scenario.time.end_date)
    }) {
        rows.push(sales_item_ledger_row(config, sale)?);
    }
    for loss in losses
        .iter()
        .filter(|row| warehouse_ids.contains(row["warehouseId"].as_str()))
    {
        rows.push(ledger_row(
            &format!(
                "inventory-loss:{}:{}:{}",
                loss["warehouseId"], loss["sku"], loss["eventDate"]
            ),
            &loss["eventDate"],
            "Negative Adjmt.",
            loss,
            &loss["warehouseId"],
            -integer(loss, "lostQuantity")?,
            &format!(
                "LOSS-{:08}",
                stable_integer(&[&loss["causeIds"], &loss["eventDate"]], 99_999_999)
            ),
            config,
        )?);
    }
    for event in waste
        .iter()
        .filter(|row| warehouse_ids.contains(row["warehouseId"].as_str()))
    {
        rows.push(ledger_row(
            &format!("waste:{}", event["wasteEventKey"]),
            &event["eventDate"],
            "Negative Adjmt.",
            event,
            &event["warehouseId"],
            -integer(event, "quantity")?,
            &format!(
                "WASTE-{:08}",
                stable_integer(&[&event["wasteEventKey"]], 99_999_999)
            ),
            config,
        )?);
    }
    Ok(rows)
}

#[allow(clippy::too_many_arguments)]
fn ledger_row(
    business_key: &str,
    posting_date: &str,
    entry_type: &str,
    source: &FieldValues,
    warehouse_id: &str,
    quantity: i64,
    document_number: &str,
    config: &LoadedConfig,
) -> Result<FieldValues> {
    Ok(values([
        ("id", bc_uuid("ItemLedgerEntry", business_key)),
        ("postingDate", posting_date.to_owned()),
        ("entryType", entry_type.to_owned()),
        (
            "itemNumber",
            source
                .get("productCode")
                .cloned()
                .or_else(|| catalog_identity(config, &source["sku"]).map(|row| row.0))
                .context("ledger product")?,
        ),
        (
            "variantCode",
            source
                .get("variantCode")
                .cloned()
                .or_else(|| catalog_identity(config, &source["sku"]).map(|row| row.1))
                .context("ledger variant")?,
        ),
        ("sku", source["sku"].clone()),
        (
            "locationCode",
            warehouse_location(config, warehouse_id)?.to_owned(),
        ),
        ("quantity", quantity.to_string()),
        ("documentNumber", document_number.to_owned()),
    ]))
}

fn catalog_identity(config: &LoadedConfig, sku: &str) -> Option<(String, String)> {
    // Explicit product templates cover the current Gulf config. Generated-pack
    // rows always carry productCode/variantCode on non-opening movements; the
    // opening path is resolved by the caller's batch fields.
    config
        .scenario
        .catalog
        .product_templates
        .iter()
        .find_map(|product| {
            product
                .variant_definitions
                .iter()
                .enumerate()
                .find_map(|(index, variant)| {
                    (variant.sku.as_deref() == Some(sku))
                        .then(|| (product.product_code.clone(), format!("V{:03}", index + 1)))
                })
        })
}

fn vendors(config: &LoadedConfig, catalog: &[Product]) -> Vec<Vendor> {
    let mut result = Vec::new();
    let mut seen = BTreeSet::new();
    let mut market_ids = config
        .scenario
        .markets
        .iter()
        .map(|row| row.market_id.clone())
        .collect::<Vec<_>>();
    market_ids.sort();
    for market_id in market_ids {
        for product in catalog.iter().filter(|row| row.market_id == market_id) {
            for _variant in &product.variants {
                if !seen.insert((market_id.clone(), product.brand_code.clone())) {
                    continue;
                }
                let key = format!("supplier:{market_id}:{}", product.brand_code);
                result.push(Vendor {
                    id: bc_uuid("Vendor", &key),
                    market_id: market_id.clone(),
                    brand_code: product.brand_code.clone(),
                });
            }
        }
    }
    result
}

fn emit_company(
    emit: Emit<'_>,
    company: &BusinessCentralInstance,
    dataset: &str,
    row: FieldValues,
) {
    emit(
        &format!("business-central/{}", company.company_id),
        "businessCentral",
        dataset,
        false,
        row,
    );
}

fn companies_for_warehouse<'a>(
    config: &'a LoadedConfig,
    warehouse_id: &str,
) -> Vec<&'a BusinessCentralInstance> {
    config
        .scenario
        .source_instances
        .business_central
        .iter()
        .filter(|company| {
            company
                .warehouse_ids
                .iter()
                .any(|value| value == warehouse_id)
        })
        .collect()
}

fn companies_for_transfer<'a>(
    config: &'a LoadedConfig,
    from: &str,
    to: &str,
) -> Vec<&'a BusinessCentralInstance> {
    config
        .scenario
        .source_instances
        .business_central
        .iter()
        .filter(|company| {
            company.warehouse_ids.iter().any(|value| value == from)
                && company.warehouse_ids.iter().any(|value| value == to)
        })
        .collect()
}

fn companies_for_market<'a>(
    config: &'a LoadedConfig,
    market_id: &str,
) -> Result<Vec<&'a BusinessCentralInstance>> {
    let legal_ids = config
        .scenario
        .legal_entities
        .iter()
        .filter(|legal| legal.market_ids.iter().any(|value| value == market_id))
        .map(|legal| legal.legal_entity_id.as_str())
        .collect::<BTreeSet<_>>();
    Ok(config
        .scenario
        .source_instances
        .business_central
        .iter()
        .filter(|company| legal_ids.contains(company.legal_entity_id.as_str()))
        .collect())
}

fn warehouse_location<'a>(config: &'a LoadedConfig, warehouse_id: &str) -> Result<&'a str> {
    config
        .scenario
        .warehouses
        .iter()
        .find(|row| row.warehouse_id == warehouse_id)
        .map(|row| row.business_central_location_code.as_str())
        .with_context(|| format!("unknown warehouse {warehouse_id}"))
}

fn warehouse_market<'a>(config: &'a LoadedConfig, warehouse_id: &str) -> Result<&'a str> {
    config
        .scenario
        .warehouses
        .iter()
        .find(|row| row.warehouse_id == warehouse_id)
        .map(|row| row.market_id.as_str())
        .with_context(|| format!("unknown warehouse {warehouse_id}"))
}

fn market<'a>(config: &'a LoadedConfig, market_id: &str) -> Result<&'a Market> {
    config
        .scenario
        .markets
        .iter()
        .find(|row| row.market_id == market_id)
        .with_context(|| format!("unknown market {market_id}"))
}

fn integer(row: &FieldValues, field: &str) -> Result<i64> {
    row[field]
        .parse()
        .with_context(|| format!("invalid integer {field}"))
}

fn parse_date(value: &str) -> Result<NaiveDate> {
    NaiveDate::parse_from_str(value, "%Y-%m-%d").with_context(|| format!("invalid date {value}"))
}

fn money_text(value: &str) -> Result<String> {
    Ok(Decimal::from_str(value)?
        .quantize(2, RoundingMode::HalfEven)
        .to_string())
}

fn money(value: &Decimal) -> String {
    value.quantize(2, RoundingMode::HalfEven).to_string()
}

fn feature(config: &LoadedConfig, key: &str) -> bool {
    config
        .scenario
        .operations
        .features
        .get(key)
        .copied()
        .unwrap_or(false)
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

fn values<const N: usize>(entries: [(&'static str, String); N]) -> FieldValues {
    entries.into_iter().collect()
}
