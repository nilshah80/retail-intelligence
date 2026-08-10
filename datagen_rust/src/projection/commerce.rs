//! Dynamic source projections derived from the immutable causal event stream.

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;
use std::str::FromStr;

use anyhow::{Context, Result};
use base64::Engine as _;
use bigdecimal::RoundingMode;
use chrono::{DateTime, FixedOffset, NaiveDate};
use hmac::{Hmac, Mac};
use sha2::Sha256;

use crate::catalog::Product;
use crate::config::{BusinessCentralInstance, LoadedConfig, Market, ShopifyInstance};
use crate::deterministic::{bc_uuid, shopify_gid, stable_integer};
use crate::projection::LogicalDataset;
use crate::simulation::causal::{CausalSink, LineAllocation, LineEvent, OrderHeader};
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::model::FieldValues;
use crate::simulation::operations::add_hours;
use crate::spool::{LedgerSpool, ProjectionSpool, ProjectionSpoolOutput};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct DatasetKey {
    prefix: String,
    source_system: String,
    dataset: String,
    restricted: bool,
}

#[derive(Debug, Clone)]
struct WebhookFixture {
    order: OrderHeader,
    lines: Vec<LineEvent>,
}

#[derive(Debug, Clone)]
struct CurrencyControl {
    orders: u64,
    units: i64,
    net: Decimal,
    tax: Decimal,
    gross: Decimal,
}

impl Default for CurrencyControl {
    fn default() -> Self {
        Self {
            orders: 0,
            units: 0,
            net: Decimal::zero(),
            tax: Decimal::zero(),
            gross: Decimal::zero(),
        }
    }
}

pub struct DynamicProjectionResult {
    pub datasets: Vec<LogicalDataset>,
    pub projection_spool: Option<ProjectionSpoolOutput>,
    pub simulation_controls: serde_json::Value,
    pub controls_by_currency: serde_json::Value,
}

/// Correctness-first collector used by the differential fixture and by the
/// publication adapter. The full-run adapter drains completed date partitions
/// so this logical representation does not imply run-sized RAM residency.
pub struct CommerceProjection<'a> {
    config: &'a LoadedConfig,
    catalog: &'a [Product],
    rows: BTreeMap<DatasetKey, Vec<FieldValues>>,
    projection_spool: Option<ProjectionSpool>,
    ledger_spool: Option<LedgerSpool>,
    buffered_rows: usize,
    flush_threshold: usize,
    deferred_spool_error: Option<anyhow::Error>,
    line_sequence_by_market: BTreeMap<String, u64>,
    refund_sequence_by_market: BTreeMap<String, u64>,
    webhook_candidates: BTreeMap<String, Vec<WebhookFixture>>,
    latest_inventory: BTreeMap<(String, String), FieldValues>,
    raw_receipts: Vec<FieldValues>,
    raw_transfers: Vec<FieldValues>,
    raw_losses: Vec<FieldValues>,
    raw_waste: Vec<FieldValues>,
    raw_batches: Vec<FieldValues>,
    raw_observations: Vec<FieldValues>,
    raw_sales_ledger: Vec<FieldValues>,
    warehouse_capacity_totals: BTreeMap<(String, String), (i64, i64)>,
    sku_store_days: u64,
    latent_units: i64,
    realized_units: i64,
    lost_units: i64,
    order_count: u64,
    order_line_count: u64,
    fulfillment_count: u64,
    return_count: u64,
    currency_controls: BTreeMap<String, CurrencyControl>,
}

impl<'a> CommerceProjection<'a> {
    #[must_use]
    pub fn new(config: &'a LoadedConfig, catalog: &'a [Product]) -> Self {
        let mut value = Self {
            config,
            catalog,
            rows: BTreeMap::new(),
            projection_spool: None,
            ledger_spool: None,
            buffered_rows: 0,
            flush_threshold: usize::MAX,
            deferred_spool_error: None,
            line_sequence_by_market: BTreeMap::new(),
            refund_sequence_by_market: BTreeMap::new(),
            webhook_candidates: BTreeMap::new(),
            latest_inventory: BTreeMap::new(),
            raw_receipts: Vec::new(),
            raw_transfers: Vec::new(),
            raw_losses: Vec::new(),
            raw_waste: Vec::new(),
            raw_batches: Vec::new(),
            raw_observations: Vec::new(),
            raw_sales_ledger: Vec::new(),
            warehouse_capacity_totals: BTreeMap::new(),
            sku_store_days: 0,
            latent_units: 0,
            realized_units: 0,
            lost_units: 0,
            order_count: 0,
            order_line_count: 0,
            fulfillment_count: 0,
            return_count: 0,
            currency_controls: BTreeMap::new(),
        };
        value.declare_core_datasets();
        value
    }

    pub fn new_spooling(
        config: &'a LoadedConfig,
        catalog: &'a [Product],
        run_base: &Path,
        flush_threshold: usize,
        max_open_writers: usize,
    ) -> Result<Self> {
        let mut value = Self::new(config, catalog);
        let mut spool = ProjectionSpool::create(run_base, config, max_open_writers)?;
        for key in value.rows.keys() {
            spool.declare(
                &key.prefix,
                &key.source_system,
                &key.dataset,
                key.restricted,
            );
        }
        value.projection_spool = Some(spool);
        if feature(config, "supplyChain") {
            value.ledger_spool = Some(LedgerSpool::create(run_base, max_open_writers)?);
        }
        value.flush_threshold = flush_threshold.max(1_000);
        Ok(value)
    }

    fn declare_core_datasets(&mut self) {
        let shops = self.config.scenario.source_instances.shopify.clone();
        for shop in shops {
            let prefix = format!("shopify/{}", shop.shop_id);
            for dataset in ["orders", "orderLines", "taxLines", "inventoryLevels"] {
                self.ensure(&prefix, "shopify", dataset, false);
            }
            if feature(self.config, "inventoryStateMatrix") {
                self.ensure(&prefix, "shopify", "inventoryQuantities", false);
            }
            if feature(self.config, "detailedFulfillment") {
                for dataset in [
                    "fulfillmentOrders",
                    "fulfillmentOrderLines",
                    "fulfillments",
                    "fulfillmentLines",
                    "fulfillmentStatusHistory",
                ] {
                    self.ensure(&prefix, "shopify", dataset, false);
                }
            }
            if feature(self.config, "returnsAndRefunds") {
                for dataset in ["returns", "returnLines", "refunds", "refundTransactions"] {
                    self.ensure(&prefix, "shopify", dataset, false);
                }
            }
            if feature(self.config, "webhookFixtures") {
                self.ensure(&prefix, "shopify", "webhookHmacFixtures", false);
            }
        }
        let companies = self
            .config
            .scenario
            .source_instances
            .business_central
            .clone();
        for company in companies {
            let prefix = format!("business-central/{}", company.company_id);
            for dataset in ["salesInvoices", "salesInvoiceLines", "inventorySnapshots"] {
                self.ensure(&prefix, "businessCentral", dataset, false);
            }
            if feature(self.config, "storeInventory") {
                for dataset in [
                    "storeInventorySnapshots",
                    "storeTransferEvents",
                    "storeWasteEvents",
                    "storeStockoutEvents",
                ] {
                    self.ensure(&prefix, "businessCentral", dataset, false);
                }
            }
        }
        let markets = self
            .config
            .scenario
            .markets
            .iter()
            .map(|row| row.market_id.clone())
            .collect::<Vec<_>>();
        if feature(self.config, "allocationEvidence") {
            for market_id in markets {
                let prefix = format!("companion/{market_id}");
                self.ensure(&prefix, "companion", "allocationDemandRequests", false);
                self.ensure(&prefix, "companion", "allocationSupplyPools", false);
            }
        }
        if self.config.scenario.output.write_hidden_truth {
            for dataset in [
                "demandFactors",
                "inventoryConstraintTruth",
                "sourceEventCrosswalk",
            ] {
                self.ensure("_truth", "hiddenTruth", dataset, true);
            }
        }
    }

    fn ensure(&mut self, prefix: &str, source: &str, dataset: &str, restricted: bool) {
        let key = DatasetKey {
            prefix: prefix.to_owned(),
            source_system: source.to_owned(),
            dataset: dataset.to_owned(),
            restricted,
        };
        self.rows.entry(key.clone()).or_default();
        if let Some(spool) = self.projection_spool.as_mut() {
            spool.declare(prefix, source, dataset, restricted);
        }
    }

    fn emit(
        &mut self,
        prefix: &str,
        source: &str,
        dataset: &str,
        restricted: bool,
        row: FieldValues,
    ) {
        if self.deferred_spool_error.is_some() {
            return;
        }
        let key = DatasetKey {
            prefix: prefix.to_owned(),
            source_system: source.to_owned(),
            dataset: dataset.to_owned(),
            restricted,
        };
        if let Some(spool) = self.projection_spool.as_mut() {
            spool.declare(prefix, source, dataset, restricted);
        }
        self.rows.entry(key).or_default().push(row);
        if self.projection_spool.is_some() {
            self.buffered_rows += 1;
            if self.buffered_rows >= self.flush_threshold {
                if let Err(error) = self.flush_pending_rows() {
                    self.deferred_spool_error = Some(error);
                }
            }
        }
    }

    fn flush_pending_rows(&mut self) -> Result<()> {
        let Some(spool) = self.projection_spool.as_mut() else {
            return Ok(());
        };
        let mut batches = Vec::new();
        for (key, rows) in &mut self.rows {
            if !rows.is_empty() {
                batches.push((key.clone(), std::mem::take(rows)));
            }
        }
        self.buffered_rows = 0;
        for (key, rows) in batches {
            spool.append_rows(
                &key.prefix,
                &key.source_system,
                &key.dataset,
                key.restricted,
                rows,
            )?;
        }
        Ok(())
    }

    pub fn finish(mut self) -> Result<DynamicProjectionResult> {
        self.emit_inventory_levels()?;
        self.emit_webhook_fixtures()?;
        let raw_receipts = std::mem::take(&mut self.raw_receipts);
        let raw_transfers = std::mem::take(&mut self.raw_transfers);
        let raw_losses = std::mem::take(&mut self.raw_losses);
        let raw_waste = std::mem::take(&mut self.raw_waste);
        let raw_batches = std::mem::take(&mut self.raw_batches);
        let raw_observations = std::mem::take(&mut self.raw_observations);
        let raw_sales_ledger = std::mem::take(&mut self.raw_sales_ledger);
        if self.projection_spool.is_some() {
            self.emit_streamed_warehouse_capacity()?;
        }
        let config = self.config;
        let catalog = self.catalog;
        let include_item_ledger = self.ledger_spool.is_none();
        crate::projection::supply::build_supply_datasets(
            config,
            catalog,
            &raw_receipts,
            &raw_transfers,
            &raw_losses,
            &raw_waste,
            &raw_batches,
            &raw_observations,
            &raw_sales_ledger,
            include_item_ledger,
            &mut |prefix, source, dataset, restricted, row| {
                self.emit(prefix, source, dataset, restricted, row);
            },
        )?;
        if let Some(mut ledger_spool) = self.ledger_spool.take() {
            for (company_id, row) in crate::projection::supply::non_sales_item_ledger_rows(
                config,
                &raw_batches,
                &raw_receipts,
                &raw_transfers,
                &raw_losses,
                &raw_waste,
            )? {
                ledger_spool.append(&company_id, &row)?;
            }
            ledger_spool.finish(|company_id, row| {
                self.emit(
                    &format!("business-central/{company_id}"),
                    "businessCentral",
                    "itemLedgerEntries",
                    false,
                    row,
                );
                Ok(())
            })?;
        }
        if let Some(error) = self.deferred_spool_error.take() {
            return Err(error);
        }
        self.flush_pending_rows()?;
        let purchase_order_lines = raw_receipts.len();
        let transfer_lines = raw_transfers.len();
        let fill_rate = if self.latent_units == 0 {
            "1.000000".to_owned()
        } else {
            (Decimal::from(self.realized_units) / Decimal::from(self.latent_units))
                .quantize(6, RoundingMode::HalfEven)
                .to_string()
        };
        let simulation_controls = serde_json::json!({
            "skuStoreDays": self.sku_store_days,
            "latentDemandUnits": self.latent_units,
            "realizedSalesUnits": self.realized_units,
            "lostSalesUnits": self.lost_units,
            "fillRate": fill_rate,
            "orders": self.order_count,
            "orderLines": self.order_line_count,
            "fulfillments": self.fulfillment_count,
            "returns": self.return_count,
            "purchaseOrderLines": purchase_order_lines,
            "transferLines": transfer_lines,
        });
        let controls_by_currency = serde_json::Value::Object(
            self.currency_controls
                .iter()
                .map(|(currency, control)| {
                    (
                        currency.clone(),
                        serde_json::json!({
                            "orders": control.orders,
                            "units": control.units,
                            "netAmount": money(&control.net),
                            "taxAmount": money(&control.tax),
                            "grossAmount": money(&control.gross),
                        }),
                    )
                })
                .collect(),
        );
        let (datasets, projection_spool) = if let Some(spool) = self.projection_spool.take() {
            (Vec::new(), Some(spool.finish()?))
        } else {
            (
                self.rows
                    .into_iter()
                    .map(|(key, rows)| LogicalDataset {
                        prefix: key.prefix,
                        source_system: key.source_system,
                        dataset: key.dataset,
                        restricted: key.restricted,
                        rows: rows
                            .into_iter()
                            .map(|row| {
                                row.into_iter()
                                    .map(|(field, value)| (field.to_owned(), value))
                                    .collect()
                            })
                            .collect(),
                    })
                    .collect(),
                None,
            )
        };
        Ok(DynamicProjectionResult {
            datasets,
            projection_spool,
            simulation_controls,
            controls_by_currency,
        })
    }

    fn emit_inventory_levels(&mut self) -> Result<()> {
        let shops = self.config.scenario.source_instances.shopify.clone();
        for shop in shops {
            let market = market(self.config, &shop.market_id)?;
            let prefix = format!("shopify/{}", shop.shop_id);
            let warehouse_ids = shop_warehouse_ids(self.config, &shop);
            let variants = self
                .catalog
                .iter()
                .filter(|product| product.market_id == shop.market_id)
                .flat_map(|product| product.variants.iter())
                .collect::<Vec<_>>();
            for warehouse_id in warehouse_ids {
                for variant in &variants {
                    let latest = self
                        .latest_inventory
                        .get(&(warehouse_id.clone(), variant.sku.clone()));
                    self.emit(
                        &prefix,
                        "shopify",
                        "inventoryLevels",
                        false,
                        values([
                            (
                                "inventoryItemId",
                                shopify_gid(
                                    "InventoryItem",
                                    &format!("{}:{}", shop.market_id, variant.variant_key),
                                ),
                            ),
                            ("locationId", shopify_gid("Location", &warehouse_id)),
                            (
                                "available",
                                latest
                                    .and_then(|row| row.get("available"))
                                    .cloned()
                                    .unwrap_or_else(|| "0".to_owned()),
                            ),
                            (
                                "updatedAt",
                                latest
                                    .and_then(|row| row.get("observedAt"))
                                    .cloned()
                                    .unwrap_or(crate::simulation::operations::local_iso_at(
                                        self.config.scenario.time.end_date,
                                        23,
                                        0,
                                        0,
                                        &market.timezone,
                                    )?),
                            ),
                        ]),
                    );
                }
            }
        }
        Ok(())
    }

    fn project_streamed_wms_observation(&mut self, observation: &FieldValues) -> Result<()> {
        if !feature(self.config, "warehouseOperations") {
            return Ok(());
        }
        let entry = self
            .warehouse_capacity_totals
            .entry((
                observation["warehouseKey"].clone(),
                observation["observedAt"].clone(),
            ))
            .or_default();
        entry.0 += observation["onHand"].parse::<i64>()?;
        entry.1 += observation["blocked"].parse::<i64>()?;
        let master = self.config.scenario.identity.master_seed.to_string();
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
                (observation["onHand"].parse::<i64>()? + variance).to_string(),
            ),
            ("varianceQuantity", variance.to_string()),
            (
                "comparisonStatus",
                if variance == 0 { "matched" } else { "mismatch" }.to_owned(),
            ),
        ]);
        let companies = companies_for_warehouse(self.config, &observation["warehouseKey"])
            .into_iter()
            .map(|company| company.company_id.clone())
            .collect::<Vec<_>>();
        for company_id in companies {
            self.emit(
                &format!("business-central/{company_id}"),
                "businessCentral",
                "wmsInventoryComparisons",
                false,
                row.clone(),
            );
        }
        Ok(())
    }

    fn emit_streamed_warehouse_capacity(&mut self) -> Result<()> {
        let totals = std::mem::take(&mut self.warehouse_capacity_totals);
        for ((warehouse_id, observed_at), (on_hand, blocked)) in totals {
            let capacity = self
                .config
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
            let companies = companies_for_warehouse(self.config, &warehouse_id)
                .into_iter()
                .map(|company| company.company_id.clone())
                .collect::<Vec<_>>();
            for company_id in companies {
                self.emit(
                    &format!("business-central/{company_id}"),
                    "businessCentral",
                    "warehouseCapacity",
                    false,
                    row.clone(),
                );
            }
        }
        Ok(())
    }

    fn emit_webhook_fixtures(&mut self) -> Result<()> {
        if !feature(self.config, "webhookFixtures") {
            return Ok(());
        }
        let secret = self.config.scenario.operations.webhook["fixtureSecret"]
            .as_str()
            .context("webhook fixtureSecret")?
            .as_bytes();
        let invalid_rate = self.config.scenario.operations.webhook["invalidFixtureRate"]
            .as_f64()
            .context("webhook invalidFixtureRate")?;
        let mut fixture_index = 0_usize;
        let candidates = std::mem::take(&mut self.webhook_candidates);
        for (market_id, fixtures) in candidates {
            for (market_sequence, fixture) in fixtures.into_iter().enumerate() {
                fixture_index += 1;
                let order = fixture.order;
                let payload = serde_json::json!({
                    "created_at": order.created_at,
                    "currency": order.currency_code,
                    "id": shopify_gid("Order", &order.order_key),
                    "line_items": fixture.lines.iter().map(|line| serde_json::json!({
                        "id": shopify_gid("OrderLine", &line.line_key),
                        "quantity": line.quantity,
                        "sku": line.sku,
                    })).collect::<Vec<_>>(),
                    "name": order.source_order_name,
                    "total_price": money(&order.gross),
                });
                let body = serde_json::to_string(&payload)?;
                let valid_hmac = hmac(secret, body.as_bytes())?;
                let fixture_sequence = market_sequence + 1;
                let valid = if fixture_sequence == 1 {
                    true
                } else if fixture_sequence == 2 {
                    false
                } else {
                    fraction(&[
                        &self.config.scenario.identity.master_seed.to_string(),
                        "webhook-validity",
                        &order.order_key,
                    ]) >= invalid_rate
                };
                let supplied = if valid {
                    valid_hmac
                } else {
                    hmac(secret, format!("{body}-tampered").as_bytes())?
                };
                let shop = self
                    .config
                    .scenario
                    .source_instances
                    .shopify
                    .iter()
                    .find(|row| row.market_id == market_id)
                    .context("webhook shop")?;
                self.emit(
                    &format!("shopify/{}", shop.shop_id),
                    "shopify",
                    "webhookHmacFixtures",
                    false,
                    values([
                        ("fixtureId", format!("orders-create-{fixture_index:03}")),
                        ("topic", "orders/create".to_owned()),
                        ("shopDomain", shop.shop_domain.clone()),
                        (
                            "webhookId",
                            format!(
                                "{:016}",
                                stable_integer(&["webhook", &order.order_key], 10_u64.pow(16))
                            ),
                        ),
                        ("apiVersion", "2026-07".to_owned()),
                        ("body", body),
                        ("hmacHeader", supplied),
                        ("validExpected", valid.to_string()),
                        ("idParityOrderId", shopify_gid("Order", &order.order_key)),
                    ]),
                );
            }
        }
        Ok(())
    }

    fn project_day_orders(
        &mut self,
        orders: Vec<OrderHeader>,
        lines: Vec<LineEvent>,
    ) -> Result<()> {
        let mut lines_by_order = BTreeMap::<String, Vec<LineEvent>>::new();
        for line in lines {
            lines_by_order
                .entry(line.order_key.clone())
                .or_default()
                .push(line);
        }
        for order in orders {
            let order_lines = lines_by_order
                .remove(&order.order_key)
                .with_context(|| format!("missing lines for {}", order.order_key))?;
            if self
                .webhook_candidates
                .entry(order.market_id.clone())
                .or_default()
                .len()
                < 12
            {
                self.webhook_candidates
                    .entry(order.market_id.clone())
                    .or_default()
                    .push(WebhookFixture {
                        order: order.clone(),
                        lines: order_lines.clone(),
                    });
            }
            self.project_order(&order, &order_lines)?;
        }
        anyhow::ensure!(lines_by_order.is_empty(), "unmatched order line groups");
        Ok(())
    }

    fn project_order(&mut self, order: &OrderHeader, lines: &[LineEvent]) -> Result<()> {
        self.order_count += 1;
        self.order_line_count += lines.len() as u64;
        let control = self
            .currency_controls
            .entry(order.currency_code.clone())
            .or_default();
        control.orders += 1;
        control.units += order.units;
        control.net = control.net.clone() + &order.net;
        control.tax = control.tax.clone() + &order.tax;
        control.gross = control.gross.clone() + &order.gross;
        let shops = shops_for_order(self.config, order);
        let companies = companies_for_market(self.config, &order.market_id)?;
        let extract_end = self.config.scenario.time.end_date;
        let mut by_warehouse = BTreeMap::<String, Vec<(&LineEvent, &LineAllocation)>>::new();
        for line in lines {
            for allocation in &line.allocations {
                by_warehouse
                    .entry(allocation.warehouse_id.clone())
                    .or_default()
                    .push((line, allocation));
            }
        }
        let mut created_fulfillments = 0_usize;
        if feature(self.config, "detailedFulfillment") {
            for (warehouse_id, allocated_lines) in &by_warehouse {
                let fulfillment_order_key =
                    format!("{}:{warehouse_id}:fulfillment-order", order.order_key);
                let fulfillment_key = format!("{}:{warehouse_id}", order.order_key);
                let fulfillment_id = shopify_gid("Fulfillment", &fulfillment_key);
                let first_allocation = allocated_lines[0].1;
                let created_at = &first_allocation.fulfillment_created_at;
                let delivered_at = &first_allocation.fulfillment_delivered_at;
                let created = timestamp_day(created_at)? <= extract_end;
                let delivered = timestamp_day(delivered_at)? <= extract_end;
                let fulfillment_order = values([
                    (
                        "id",
                        shopify_gid("FulfillmentOrder", &fulfillment_order_key),
                    ),
                    ("orderId", shopify_gid("Order", &order.order_key)),
                    ("status", if created { "CLOSED" } else { "OPEN" }.to_owned()),
                    (
                        "requestStatus",
                        if created { "SUBMITTED" } else { "UNSUBMITTED" }.to_owned(),
                    ),
                    ("createdAt", order.created_at.clone()),
                    (
                        "updatedAt",
                        if delivered {
                            delivered_at.clone()
                        } else if created {
                            created_at.clone()
                        } else {
                            order.created_at.clone()
                        },
                    ),
                    ("deliveryMethod", "SHIPPING".to_owned()),
                    (
                        "destinationLocationId",
                        shopify_gid("Location", warehouse_id),
                    ),
                ]);
                self.emit_to_shops(&shops, "fulfillmentOrders", &fulfillment_order);
                for (line, allocation) in allocated_lines {
                    let mut row = values([
                        (
                            "id",
                            shopify_gid(
                                "FulfillmentOrderLineItem",
                                &format!("{fulfillment_order_key}:{}", line.line_key),
                            ),
                        ),
                        (
                            "fulfillmentOrderId",
                            shopify_gid("FulfillmentOrder", &fulfillment_order_key),
                        ),
                        ("orderLineId", shopify_gid("OrderLine", &line.line_key)),
                        ("sku", line.sku.clone()),
                        ("totalQuantity", allocation.quantity.to_string()),
                        (
                            "remainingQuantity",
                            if created { 0 } else { allocation.quantity }.to_string(),
                        ),
                        ("warehouseKey", warehouse_id.clone()),
                    ]);
                    row.insert("__partitionDate", line.day.to_string());
                    self.emit_to_shops(&shops, "fulfillmentOrderLines", &row);
                }
                if !created {
                    continue;
                }
                created_fulfillments += 1;
                self.fulfillment_count += 1;
                let fulfillment = values([
                    ("id", fulfillment_id.clone()),
                    ("orderId", shopify_gid("Order", &order.order_key)),
                    (
                        "fulfillmentOrderId",
                        shopify_gid("FulfillmentOrder", &fulfillment_order_key),
                    ),
                    ("locationId", shopify_gid("Location", warehouse_id)),
                    ("status", "SUCCESS".to_owned()),
                    (
                        "shipmentStatus",
                        if delivered { "DELIVERED" } else { "IN_TRANSIT" }.to_owned(),
                    ),
                    ("createdAt", created_at.clone()),
                    (
                        "deliveredAt",
                        if delivered {
                            delivered_at.clone()
                        } else {
                            String::new()
                        },
                    ),
                    ("trackingCompany", "Synthetic Parcel Network".to_owned()),
                    (
                        "trackingNumber",
                        format!(
                            "SPN{:012}",
                            stable_integer(&[&fulfillment_key], 10_u64.pow(12))
                        ),
                    ),
                ]);
                self.emit_to_shops(&shops, "fulfillments", &fulfillment);
                for (line, allocation) in allocated_lines {
                    let mut row = values([
                        (
                            "id",
                            shopify_gid(
                                "FulfillmentLineItem",
                                &format!("{fulfillment_key}:{}", line.line_key),
                            ),
                        ),
                        ("fulfillmentId", fulfillment_id.clone()),
                        ("orderLineId", shopify_gid("OrderLine", &line.line_key)),
                        ("sku", line.sku.clone()),
                        ("quantity", allocation.quantity.to_string()),
                        ("warehouseKey", warehouse_id.clone()),
                    ]);
                    row.insert("__partitionDate", line.day.to_string());
                    self.emit_to_shops(&shops, "fulfillmentLines", &row);
                }
                let statuses = [
                    ("SUBMITTED", order.created_at.clone()),
                    ("IN_PROGRESS", created_at.clone()),
                    ("DELIVERED", delivered_at.clone()),
                    ("CLOSED", add_hours(delivered_at, 1)?),
                ];
                for (index, (status, occurred_at)) in statuses
                    .into_iter()
                    .filter(|(_, timestamp)| {
                        timestamp_day(timestamp).is_ok_and(|day| day <= extract_end)
                    })
                    .enumerate()
                {
                    self.emit_to_shops(
                        &shops,
                        "fulfillmentStatusHistory",
                        &values([
                            ("fulfillmentId", fulfillment_id.clone()),
                            ("sequence", (index + 1).to_string()),
                            ("status", status.to_owned()),
                            ("occurredAt", occurred_at),
                            ("warehouseKey", warehouse_id.clone()),
                        ]),
                    );
                }
            }
        }

        let mut successful_refunds = Decimal::zero();
        for line in lines {
            self.project_order_line(order, line, &shops, &companies, &mut successful_refunds)?;
        }
        let financial = if successful_refunds >= order.gross {
            "REFUNDED"
        } else if successful_refunds > Decimal::zero() {
            "PARTIALLY_REFUNDED"
        } else {
            "PAID"
        };
        let fulfillment = if !by_warehouse.is_empty() && created_fulfillments == by_warehouse.len()
        {
            "FULFILLED"
        } else if created_fulfillments > 0 {
            "PARTIALLY_FULFILLED"
        } else {
            "UNFULFILLED"
        };
        let shopify_order = values([
            ("id", shopify_gid("Order", &order.order_key)),
            ("name", order.source_order_name.clone()),
            ("createdAt", order.created_at.clone()),
            ("processedAt", order.created_at.clone()),
            ("currencyCode", order.currency_code.clone()),
            ("taxesIncluded", order.taxes_included.to_string()),
            (
                "subtotalPrice",
                money(if order.taxes_included {
                    &order.gross
                } else {
                    &order.net
                }),
            ),
            ("totalTax", money(&order.tax)),
            ("totalPrice", money(&order.gross)),
            ("displayFinancialStatus", financial.to_owned()),
            ("displayFulfillmentStatus", fulfillment.to_owned()),
            ("locationId", shopify_gid("Location", &order.store_id)),
            (
                "sourceName",
                if order.channel_id.contains("store") {
                    "pos"
                } else {
                    "web"
                }
                .to_owned(),
            ),
            ("customerSegmentId", order.customer_segment_id.clone()),
            (
                "customerId",
                if order.customer_key.is_empty() {
                    String::new()
                } else {
                    shopify_gid("Customer", &order.customer_key)
                },
            ),
            ("channelId", order.channel_id.clone()),
            ("lineCount", order.line_count.to_string()),
        ]);
        self.emit_to_shops(&shops, "orders", &shopify_order);

        for company in companies {
            let prefix = format!("business-central/{}", company.company_id);
            self.emit(
                &prefix,
                "businessCentral",
                "salesInvoices",
                false,
                values([
                    ("id", bc_uuid("SalesInvoice", &order.order_key)),
                    ("number", format!("SI-{:014}", order.source_order_sequence)),
                    ("externalDocumentNumber", order.source_order_name.clone()),
                    ("invoiceDate", order.day.to_string()),
                    ("postingDate", order.day.to_string()),
                    ("currencyCode", order.currency_code.clone()),
                    ("totalAmountExcludingTax", money(&order.net)),
                    ("totalTaxAmount", money(&order.tax)),
                    ("totalAmountIncludingTax", money(&order.gross)),
                    ("status", "Paid".to_owned()),
                    ("customerSegmentCode", order.customer_segment_id.clone()),
                    ("customerId", bc_uuid("Customer", &order.bc_customer_key)),
                    ("salesChannelCode", order.channel_id.clone()),
                ]),
            );
        }
        Ok(())
    }

    fn project_order_line(
        &mut self,
        order: &OrderHeader,
        line: &LineEvent,
        shops: &[&ShopifyInstance],
        companies: &[&BusinessCentralInstance],
        successful_refunds: &mut Decimal,
    ) -> Result<()> {
        let mut shopify_line = values([
            ("id", shopify_gid("OrderLine", &line.line_key)),
            ("orderId", shopify_gid("Order", &line.order_key)),
            ("variantId", line.variant_id.clone()),
            ("sku", line.sku.clone()),
            ("productTitle", line.product_title.clone()),
            ("variantTitle", line.variant_title.clone()),
            ("vendor", line.brand.clone()),
            ("productCode", line.product_code.clone()),
            ("barcode", line.barcode.clone()),
            ("quantity", line.quantity.to_string()),
            ("originalUnitPrice", money(&line.original_unit_price)),
            ("discountedUnitPrice", money(&line.unit_price)),
            ("promotionIds", line.promotion_ids.join("|")),
            ("currencyCode", line.currency_code.clone()),
            ("taxRate", line.tax_rate.to_string()),
            ("lineNumber", line.line_number.to_string()),
            ("customerSegmentId", line.customer_segment_id.clone()),
            ("channelId", line.channel_id.clone()),
        ]);
        shopify_line.insert("__partitionDate", line.day.to_string());
        self.emit_to_shops(shops, "orderLines", &shopify_line);

        for company in companies {
            let prefix = format!("business-central/{}", company.company_id);
            for (allocation_index, allocation) in line.allocations.iter().enumerate() {
                let mut row = values([
                    (
                        "id",
                        bc_uuid(
                            "SalesInvoiceLine",
                            &format!("{}:{}", line.line_key, allocation.warehouse_id),
                        ),
                    ),
                    ("documentId", bc_uuid("SalesInvoice", &line.order_key)),
                    (
                        "lineNumber",
                        (line.line_number + allocation_index).to_string(),
                    ),
                    (
                        "itemId",
                        bc_uuid("Item", &format!("{}:{}", line.market_id, line.product_code)),
                    ),
                    ("itemNumber", line.product_code.clone()),
                    ("variantCode", line.variant_code.clone()),
                    ("sku", line.sku.clone()),
                    ("description", line.product_title.clone()),
                    (
                        "locationCode",
                        warehouse_location(self.config, &allocation.warehouse_id)?.to_owned(),
                    ),
                    ("quantity", allocation.quantity.to_string()),
                    ("unitPrice", money(&line.unit_price)),
                    (
                        "netAmount",
                        money(&allocation_amount(
                            &line.net,
                            &line.allocations,
                            allocation_index,
                        )),
                    ),
                    (
                        "taxAmount",
                        money(&allocation_amount(
                            &line.tax,
                            &line.allocations,
                            allocation_index,
                        )),
                    ),
                    (
                        "amountIncludingTax",
                        money(&allocation_amount(
                            &line.gross,
                            &line.allocations,
                            allocation_index,
                        )),
                    ),
                    ("currencyCode", line.currency_code.clone()),
                ]);
                row.insert("__partitionDate", line.day.to_string());
                self.emit(&prefix, "businessCentral", "salesInvoiceLines", false, row);
            }
        }
        for allocation in &line.allocations {
            let sale = values([
                ("warehouseId", allocation.warehouse_id.clone()),
                ("sku", line.sku.clone()),
                ("lineKey", line.line_key.clone()),
                (
                    "postingDate",
                    allocation.fulfillment_created_at[..10].to_owned(),
                ),
                ("fulfilledAt", allocation.fulfillment_created_at.clone()),
                ("quantity", allocation.quantity.to_string()),
                (
                    "sourceOrderSequence",
                    line.source_order_sequence.to_string(),
                ),
                ("productCode", line.product_code.clone()),
                ("variantCode", line.variant_code.clone()),
            ]);
            if let Some(ledger_spool) = self.ledger_spool.as_mut() {
                if !sale["fulfilledAt"].is_empty()
                    && NaiveDate::parse_from_str(&sale["postingDate"], "%Y-%m-%d")?
                        <= self.config.scenario.time.end_date
                {
                    let ledger_row =
                        crate::projection::supply::sales_item_ledger_row(self.config, &sale)?;
                    let company_ids =
                        companies_for_warehouse(self.config, &allocation.warehouse_id)
                            .into_iter()
                            .map(|company| company.company_id.clone())
                            .collect::<Vec<_>>();
                    for company_id in company_ids {
                        ledger_spool.append(&company_id, &ledger_row)?;
                    }
                }
            } else {
                self.raw_sales_ledger.push(sale);
            }
        }

        if self.config.scenario.output.write_hidden_truth {
            let mut row = values([
                ("eventKey", line.event_key.clone()),
                ("lineKey", line.line_key.clone()),
                ("orderKey", line.order_key.clone()),
                ("shopifyOrderId", shopify_gid("Order", &line.order_key)),
                (
                    "shopifyOrderLineId",
                    shopify_gid("OrderLine", &line.line_key),
                ),
                (
                    "businessCentralInvoiceId",
                    bc_uuid("SalesInvoice", &line.order_key),
                ),
                (
                    "businessCentralInvoiceLineIds",
                    line.allocations
                        .iter()
                        .map(|allocation| {
                            bc_uuid(
                                "SalesInvoiceLine",
                                &format!("{}:{}", line.line_key, allocation.warehouse_id),
                            )
                        })
                        .collect::<Vec<_>>()
                        .join("|"),
                ),
                ("marketKey", line.market_id.clone()),
                ("storeKey", line.store_id.clone()),
            ]);
            row.insert("__partitionDate", line.day.to_string());
            self.emit("_truth", "hiddenTruth", "sourceEventCrosswalk", true, row);
        }

        self.emit_tax_lines(line, shops)?;
        if feature(self.config, "returnsAndRefunds") {
            self.emit_return_rows(order, line, shops, successful_refunds)?;
        }
        Ok(())
    }

    fn emit_tax_lines(&mut self, line: &LineEvent, shops: &[&ShopifyInstance]) -> Result<()> {
        let market = market(self.config, &line.market_id)?;
        let legacy_vat = market.country_code == "IN"
            && line.day < NaiveDate::from_ymd_opt(2017, 7, 1).expect("GST date");
        let components = if legacy_vat {
            vec![("Maharashtra-VAT".to_owned(), dec("1.0"))]
        } else {
            market.locale_pack["tax"]["components"]["intraRegion"]
                .as_array()
                .context("tax components")?
                .iter()
                .map(|component| {
                    Ok((
                        component["code"].as_str().context("tax code")?.to_owned(),
                        decimal_json(&component["share"])?,
                    ))
                })
                .collect::<Result<Vec<_>>>()?
        };
        let jurisdiction = if legacy_vat {
            "Maharashtra-VAT"
        } else {
            market.locale_pack["tax"]["jurisdiction"]
                .as_str()
                .context("tax jurisdiction")?
        };
        let mut allocated = Decimal::zero();
        let component_count = components.len();
        for (index, (code, share)) in components.into_iter().enumerate() {
            let amount = if index + 1 == component_count {
                &line.tax - &allocated
            } else {
                (&line.tax * &share).quantize(2, RoundingMode::HalfEven)
            };
            allocated = allocated + &amount;
            let mut row = values([
                ("orderLineId", shopify_gid("OrderLine", &line.line_key)),
                ("orderId", shopify_gid("Order", &line.order_key)),
                ("title", code),
                ("rate", line.tax_rate.to_string()),
                ("shareOfTax", share.to_string()),
                ("price", money(&amount)),
                ("currencyCode", line.currency_code.clone()),
                ("jurisdiction", jurisdiction.to_owned()),
            ]);
            row.insert("__partitionDate", line.day.to_string());
            self.emit_to_shops(shops, "taxLines", &row);
        }
        Ok(())
    }

    fn emit_return_rows(
        &mut self,
        _order: &OrderHeader,
        line: &LineEvent,
        shops: &[&ShopifyInstance],
        successful_refunds: &mut Decimal,
    ) -> Result<()> {
        let sequence = self
            .line_sequence_by_market
            .entry(line.market_id.clone())
            .or_default();
        *sequence += 1;
        let forced = *sequence <= 2;
        let return_probability = line
            .return_probability
            .to_string()
            .parse::<f64>()
            .context("return probability")?;
        let master_text = self.config.scenario.identity.master_seed.to_string();
        if !forced
            && fraction(&[&master_text, "return-request", &line.line_key]) >= return_probability
        {
            return Ok(());
        }
        let return_key = format!("{}:return", line.line_key);
        let requested_at = add_hours(&line.created_at, 24 * 7)?;
        let target_processed_at = add_hours(&requested_at, 48)?;
        let extract_end = self.config.scenario.time.end_date;
        if timestamp_day(&requested_at)? > extract_end {
            return Ok(());
        }
        let decision_by_extract = timestamp_day(&target_processed_at)? <= extract_end;
        let processing_rate = self.config.scenario.operations.returns["processingRate"]
            .as_f64()
            .context("returns processingRate")?;
        let selected = forced
            || fraction(&[&master_text, "return-processed", &line.line_key]) < processing_rate;
        let processed = decision_by_extract && selected;
        let status = if processed {
            "CLOSED"
        } else if decision_by_extract {
            "DECLINED"
        } else {
            "OPEN"
        };
        let return_id = shopify_gid("Return", &return_key);
        self.emit_to_shops(
            shops,
            "returns",
            &values([
                ("id", return_id.clone()),
                ("orderId", shopify_gid("Order", &line.order_key)),
                (
                    "name",
                    format!("RET-{:09}", stable_integer(&[&return_key], 1_000_000_000)),
                ),
                ("status", status.to_owned()),
                ("requestedAt", requested_at.clone()),
                (
                    "processedAt",
                    if decision_by_extract {
                        target_processed_at.clone()
                    } else {
                        String::new()
                    },
                ),
                (
                    "reason",
                    ["SIZE_TOO_SMALL", "NOT_AS_DESCRIBED", "UNWANTED"]
                        [stable_integer(&[&return_key], 3) as usize]
                        .to_owned(),
                ),
            ]),
        );
        self.return_count += 1;
        let mut return_line = values([
            ("id", shopify_gid("ReturnLineItem", &return_key)),
            ("returnId", return_id.clone()),
            ("orderLineId", shopify_gid("OrderLine", &line.line_key)),
            ("sku", line.sku.clone()),
            ("requestedQuantity", "1".to_owned()),
            (
                "processedQuantity",
                if processed { "1" } else { "0" }.to_owned(),
            ),
            ("restockType", "NO_RESTOCK".to_owned()),
            ("restockLocationId", String::new()),
        ]);
        return_line.insert("__partitionDate", requested_at[..10].to_owned());
        self.emit_to_shops(shops, "returnLines", &return_line);
        if !processed {
            return Ok(());
        }
        let refund_key = format!("{}:refund", line.line_key);
        let refund_amount = &line.gross / Decimal::from(line.quantity);
        let refund_sequence = self
            .refund_sequence_by_market
            .entry(line.market_id.clone())
            .or_default();
        *refund_sequence += 1;
        let failed_rate = self.config.scenario.operations.returns["refundFailureRate"]
            .as_f64()
            .context("returns refundFailureRate")?;
        let succeeded = if *refund_sequence == 1 {
            true
        } else if *refund_sequence == 2 {
            false
        } else {
            fraction(&[&master_text, "refund-success", &line.line_key]) >= failed_rate
        };
        let refund_id = shopify_gid("Refund", &refund_key);
        let refunded_amount = if succeeded {
            refund_amount.clone()
        } else {
            Decimal::zero()
        };
        self.emit_to_shops(
            shops,
            "refunds",
            &values([
                ("id", refund_id.clone()),
                ("orderId", shopify_gid("Order", &line.order_key)),
                ("returnId", return_id),
                ("createdAt", add_hours(&requested_at, 49)?),
                ("totalRefunded", money(&refunded_amount)),
                ("currencyCode", line.currency_code.clone()),
                (
                    "status",
                    if succeeded { "SUCCESS" } else { "FAILED" }.to_owned(),
                ),
            ]),
        );
        if succeeded {
            *successful_refunds = successful_refunds.clone() + &refund_amount;
        }
        self.emit_to_shops(
            shops,
            "refundTransactions",
            &values([
                ("id", shopify_gid("OrderTransaction", &refund_key)),
                ("refundId", refund_id),
                ("orderId", shopify_gid("Order", &line.order_key)),
                ("kind", "REFUND".to_owned()),
                ("gateway", "synthetic-payments".to_owned()),
                (
                    "status",
                    if succeeded { "SUCCESS" } else { "FAILURE" }.to_owned(),
                ),
                ("amount", money(&refund_amount)),
                ("currencyCode", line.currency_code.clone()),
                ("processedAt", add_hours(&requested_at, 49)?),
                (
                    "errorCode",
                    if succeeded { "" } else { "PROCESSING_ERROR" }.to_owned(),
                ),
            ]),
        );
        Ok(())
    }

    fn emit_to_shops(&mut self, shops: &[&ShopifyInstance], dataset: &str, row: &FieldValues) {
        for shop in shops {
            self.emit(
                &format!("shopify/{}", shop.shop_id),
                "shopify",
                dataset,
                false,
                row.clone(),
            );
        }
    }
}

impl CausalSink for CommerceProjection<'_> {
    fn demand_truth(&mut self, row: FieldValues) -> Result<()> {
        self.sku_store_days += 1;
        self.latent_units += row["latentDemandUnits"].parse::<i64>()?;
        self.realized_units += row["realizedSalesUnits"].parse::<i64>()?;
        self.lost_units += row["lostSalesUnits"].parse::<i64>()?;
        if self.config.scenario.output.write_hidden_truth {
            self.emit("_truth", "hiddenTruth", "demandFactors", true, row.clone());
            self.emit(
                "_truth",
                "hiddenTruth",
                "inventoryConstraintTruth",
                true,
                values([
                    ("marketKey", row["marketKey"].clone()),
                    ("storeKey", row["storeKey"].clone()),
                    ("channelId", row["channelId"].clone()),
                    ("date", row["date"].clone()),
                    ("sku", row["sku"].clone()),
                    ("latentDemandUnits", row["latentDemandUnits"].clone()),
                    ("realizedSalesUnits", row["realizedSalesUnits"].clone()),
                    ("lostSalesUnits", row["lostSalesUnits"].clone()),
                ]),
            );
        }
        Ok(())
    }

    fn allocation_request(&mut self, row: FieldValues) -> Result<()> {
        if feature(self.config, "allocationEvidence") {
            self.emit(
                &format!("companion/{}", row["marketKey"]),
                "companion",
                "allocationDemandRequests",
                false,
                row,
            );
        }
        Ok(())
    }

    fn supply_pool(&mut self, row: FieldValues) -> Result<()> {
        if feature(self.config, "allocationEvidence") {
            self.emit(
                &format!("companion/{}", row["marketKey"]),
                "companion",
                "allocationSupplyPools",
                false,
                row,
            );
        }
        Ok(())
    }

    fn day_orders(
        &mut self,
        _day: NaiveDate,
        orders: Vec<OrderHeader>,
        lines: Vec<LineEvent>,
    ) -> Result<()> {
        self.project_day_orders(orders, lines)
    }

    fn inventory_observation(&mut self, row: FieldValues) -> Result<()> {
        self.latest_inventory.insert(
            (row["warehouseKey"].clone(), row["sku"].clone()),
            row.clone(),
        );
        if self.projection_spool.is_some() {
            self.project_streamed_wms_observation(&row)?;
        } else {
            self.raw_observations.push(row.clone());
        }
        let companies = companies_for_warehouse(self.config, &row["warehouseKey"]);
        for company in companies {
            self.emit(
                &format!("business-central/{}", company.company_id),
                "businessCentral",
                "inventorySnapshots",
                false,
                values([
                    (
                        "locationCode",
                        warehouse_location(self.config, &row["warehouseKey"])?.to_owned(),
                    ),
                    ("observedAt", row["observedAt"].clone()),
                    ("sku", row["sku"].clone()),
                    ("inventory", row["onHand"].clone()),
                    ("availableInventory", row["available"].clone()),
                    ("committedInventory", row["committed"].clone()),
                    ("reservedInventory", row["reserved"].clone()),
                    ("damagedInventory", row["damaged"].clone()),
                    ("qualityControlInventory", row["qualityControl"].clone()),
                    ("safetyStockInventory", row["safetyStock"].clone()),
                    ("incomingInventory", row["incoming"].clone()),
                ]),
            );
        }
        if feature(self.config, "inventoryStateMatrix") {
            let shops = shops_for_warehouse(self.config, &row["warehouseKey"]);
            let variant = self
                .catalog
                .iter()
                .flat_map(|product| {
                    product
                        .variants
                        .iter()
                        .map(move |variant| (product, variant))
                })
                .find(|(_, variant)| variant.sku == row["sku"])
                .context("inventory observation SKU")?;
            for shop in shops {
                let inventory_item_id = shopify_gid(
                    "InventoryItem",
                    &format!("{}:{}", shop.market_id, variant.1.variant_key),
                );
                for (name, source) in [
                    ("on_hand", "onHand"),
                    ("available", "available"),
                    ("committed", "committed"),
                    ("reserved", "reserved"),
                    ("damaged", "damaged"),
                    ("quality_control", "qualityControl"),
                    ("safety_stock", "safetyStock"),
                    ("incoming", "incoming"),
                ] {
                    self.emit(
                        &format!("shopify/{}", shop.shop_id),
                        "shopify",
                        "inventoryQuantities",
                        false,
                        values([
                            ("inventoryItemId", inventory_item_id.clone()),
                            ("locationId", shopify_gid("Location", &row["warehouseKey"])),
                            ("observedAt", row["observedAt"].clone()),
                            ("name", name.to_owned()),
                            ("quantity", row[source].clone()),
                        ]),
                    );
                }
            }
        }
        Ok(())
    }

    fn store_observation(&mut self, row: FieldValues) -> Result<()> {
        if !feature(self.config, "storeInventory") {
            return Ok(());
        }
        let companies = companies_for_store(self.config, &row["storeKey"]);
        for company in companies {
            self.emit(
                &format!("business-central/{}", company.company_id),
                "businessCentral",
                "storeInventorySnapshots",
                false,
                values([
                    ("locationCode", row["locationCode"].clone()),
                    ("observedAt", row["observedAt"].clone()),
                    ("sku", row["sku"].clone()),
                    ("inventory", row["onHand"].clone()),
                    ("availableInventory", row["available"].clone()),
                    ("committedInventory", row["committed"].clone()),
                    ("reservedInventory", "0".to_owned()),
                    ("damagedInventory", row["damaged"].clone()),
                    ("qualityControlInventory", "0".to_owned()),
                    ("safetyStockInventory", "0".to_owned()),
                    ("incomingInventory", row["inTransit"].clone()),
                    ("assortmentActive", row["assortmentActive"].clone()),
                    ("residualOnly", row["residualOnly"].clone()),
                    ("oldestReceiptDate", row["oldestReceiptDate"].clone()),
                ]),
            );
        }
        Ok(())
    }

    fn store_transfer(&mut self, row: FieldValues) -> Result<()> {
        if !feature(self.config, "storeInventory") {
            return Ok(());
        }
        let companies = companies_for_store(self.config, &row["toLocationKey"]);
        for company in companies {
            self.emit(
                &format!("business-central/{}", company.company_id),
                "businessCentral",
                "storeTransferEvents",
                false,
                values([
                    ("transferId", row["transferKey"].clone()),
                    ("sku", row["sku"].clone()),
                    (
                        "fromLocationCode",
                        warehouse_location(self.config, &row["fromLocationKey"])?.to_owned(),
                    ),
                    (
                        "toLocationCode",
                        store_location(self.config, &row["toLocationKey"])?.to_owned(),
                    ),
                    ("quantity", row["quantity"].clone()),
                    ("status", row["status"].clone()),
                    ("statusEffectiveAt", row["statusEffectiveAt"].clone()),
                    ("observedAt", row["observedAt"].clone()),
                    ("unitCostAmountMinor", row["unitCostMinor"].clone()),
                    ("currencyCode", row["currencyCode"].clone()),
                ]),
            );
        }
        Ok(())
    }

    fn store_waste(&mut self, row: FieldValues) -> Result<()> {
        let companies = companies_for_store(self.config, &row["storeKey"]);
        for company in companies {
            self.emit(
                &format!("business-central/{}", company.company_id),
                "businessCentral",
                "storeWasteEvents",
                false,
                values([
                    ("eventId", row["eventKey"].clone()),
                    ("sku", row["sku"].clone()),
                    (
                        "locationCode",
                        store_location(self.config, &row["storeKey"])?.to_owned(),
                    ),
                    ("eventDate", row["eventDate"].clone()),
                    ("quantity", row["units"].clone()),
                    ("reasonCode", row["reasonCode"].clone()),
                    ("observedAt", row["observedAt"].clone()),
                ]),
            );
        }
        Ok(())
    }

    fn store_stockout(&mut self, row: FieldValues) -> Result<()> {
        let companies = companies_for_store(self.config, &row["storeKey"]);
        for company in companies {
            self.emit(
                &format!("business-central/{}", company.company_id),
                "businessCentral",
                "storeStockoutEvents",
                false,
                values([
                    ("eventId", row["eventKey"].clone()),
                    ("sku", row["sku"].clone()),
                    (
                        "locationCode",
                        store_location(self.config, &row["storeKey"])?.to_owned(),
                    ),
                    ("channelId", row["channelId"].clone()),
                    ("eventDate", row["eventDate"].clone()),
                    ("demandUnits", row["demandUnits"].clone()),
                    ("servedFromStoreUnits", row["servedFromStoreUnits"].clone()),
                    ("shortfallUnits", row["shortfallUnits"].clone()),
                    (
                        "servedFromLocationCode",
                        warehouse_location(self.config, &row["servedFromSupplyNode"])?.to_owned(),
                    ),
                    ("observedAt", row["observedAt"].clone()),
                ]),
            );
        }
        Ok(())
    }

    fn receipt_event(&mut self, row: FieldValues) -> Result<()> {
        self.raw_receipts.push(row);
        Ok(())
    }

    fn transfer_event(&mut self, row: FieldValues) -> Result<()> {
        self.raw_transfers.push(row);
        Ok(())
    }

    fn inventory_loss_event(&mut self, row: FieldValues) -> Result<()> {
        self.raw_losses.push(row);
        Ok(())
    }

    fn waste_event(&mut self, row: FieldValues) -> Result<()> {
        self.raw_waste.push(row);
        Ok(())
    }

    fn batch_balance(&mut self, row: FieldValues) -> Result<()> {
        self.raw_batches.push(row);
        Ok(())
    }
}

fn shops_for_order<'a>(config: &'a LoadedConfig, order: &OrderHeader) -> Vec<&'a ShopifyInstance> {
    config
        .scenario
        .source_instances
        .shopify
        .iter()
        .filter(|shop| {
            shop.market_id == order.market_id && shop.store_ids.contains(&order.store_id)
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

fn companies_for_store<'a>(
    config: &'a LoadedConfig,
    store_id: &str,
) -> Vec<&'a BusinessCentralInstance> {
    let legal_id = config
        .scenario
        .stores
        .iter()
        .find(|store| store.store_id == store_id)
        .map(|store| store.legal_entity_id.as_str());
    config
        .scenario
        .source_instances
        .business_central
        .iter()
        .filter(|company| Some(company.legal_entity_id.as_str()) == legal_id)
        .collect()
}

fn shops_for_warehouse<'a>(
    config: &'a LoadedConfig,
    warehouse_id: &str,
) -> Vec<&'a ShopifyInstance> {
    let Some(warehouse) = config
        .scenario
        .warehouses
        .iter()
        .find(|row| row.warehouse_id == warehouse_id)
    else {
        return Vec::new();
    };
    config
        .scenario
        .source_instances
        .shopify
        .iter()
        .filter(|shop| {
            shop.market_id == warehouse.market_id
                && warehouse
                    .serves_locations
                    .iter()
                    .any(|store_id| shop.store_ids.contains(store_id))
        })
        .collect()
}

fn shop_warehouse_ids(config: &LoadedConfig, shop: &ShopifyInstance) -> Vec<String> {
    config
        .scenario
        .warehouses
        .iter()
        .filter(|warehouse| {
            warehouse
                .serves_locations
                .iter()
                .any(|store_id| shop.store_ids.contains(store_id))
        })
        .map(|warehouse| warehouse.warehouse_id.clone())
        .collect()
}

fn market<'a>(config: &'a LoadedConfig, market_id: &str) -> Result<&'a Market> {
    config
        .scenario
        .markets
        .iter()
        .find(|row| row.market_id == market_id)
        .with_context(|| format!("unknown market {market_id}"))
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

fn store_location<'a>(config: &'a LoadedConfig, store_id: &str) -> Result<&'a str> {
    config
        .scenario
        .stores
        .iter()
        .find(|row| row.store_id == store_id)
        .map(|row| row.business_central_location_code.as_str())
        .with_context(|| format!("unknown store {store_id}"))
}

fn allocation_amount(total: &Decimal, allocations: &[LineAllocation], index: usize) -> Decimal {
    let total_quantity = allocations.iter().map(|row| row.quantity).sum::<i64>();
    if index + 1 == allocations.len() {
        let prior = allocations[..index]
            .iter()
            .map(|row| {
                (total * Decimal::from(row.quantity) / Decimal::from(total_quantity))
                    .quantize(2, RoundingMode::HalfEven)
            })
            .sum::<Decimal>();
        total - prior
    } else {
        (total * Decimal::from(allocations[index].quantity) / Decimal::from(total_quantity))
            .quantize(2, RoundingMode::HalfEven)
    }
}

fn money(value: &Decimal) -> String {
    value.quantize(2, RoundingMode::HalfEven).to_string()
}

fn timestamp_day(value: &str) -> Result<NaiveDate> {
    Ok(DateTime::<FixedOffset>::parse_from_rfc3339(value)
        .with_context(|| format!("invalid timestamp {value:?}"))?
        .date_naive())
}

fn hmac(secret: &[u8], body: &[u8]) -> Result<String> {
    let mut mac = Hmac::<Sha256>::new_from_slice(secret).context("HMAC key")?;
    mac.update(body);
    Ok(base64::engine::general_purpose::STANDARD.encode(mac.finalize().into_bytes()))
}

fn decimal_json(value: &serde_json::Value) -> Result<Decimal> {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
        .parse()
        .context("decimal JSON")
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
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

#[cfg(test)]
mod tests {
    use sha2::{Digest, Sha256};

    use super::CommerceProjection;
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::contracts;
    use crate::projection::LogicalDataset;
    use crate::simulation::causal::simulate;

    #[test]
    fn gulf_mini_commerce_rows_match_python_oracle() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let mut projection = CommerceProjection::new(&config, &catalog);
        simulate(&config, &catalog, &mut projection).expect("simulation");
        let result = projection.finish().expect("dynamic projections");
        let datasets = result.datasets;
        for (source, dataset, rows, digest) in [
            (
                "shopify",
                "orders",
                1_026,
                "af42eb9f9c2ea148ae388f85a1982a23586e5d6dd725dba80bee26045a216ad2",
            ),
            (
                "shopify",
                "orderLines",
                2_027,
                "02dc90131e558af5028f4826c5207d7eb9a45686d2a76bad82675669e94ef194",
            ),
            (
                "shopify",
                "fulfillmentOrders",
                1_080,
                "b6f562d59f8efc024ab1f16c67874a74acc7809f8c0dc3490138670f599928bd",
            ),
            (
                "shopify",
                "fulfillmentOrderLines",
                2_027,
                "917504a7b7737afbc75570c4c0158121a12231e0545242b3f8fb0a5d00062ede",
            ),
            (
                "shopify",
                "fulfillments",
                1_064,
                "7295a1a9ea7d547e3962b5d7496a141f28489a0675be439bf77fa65d41ebeaac",
            ),
            (
                "shopify",
                "fulfillmentLines",
                2_004,
                "d265f87edd07eb7bbbe157723160f0bf68c85af337a055e8482a5463cf49f2de",
            ),
            (
                "shopify",
                "fulfillmentStatusHistory",
                4_005,
                "c9c3dcfcc280b54bc912660d7ee15b0e0ffb0bb4b76b2e1f7669ffa33dc2c9c3",
            ),
            (
                "shopify",
                "taxLines",
                4_054,
                "784631bee934010371a0facffc9a066576863776be7d51b294e056dcaf723794",
            ),
            (
                "shopify",
                "returns",
                8,
                "a77951d86d83ccd3b9dc446792556021135f8c11563b6e3fc72ae9560033581a",
            ),
            (
                "shopify",
                "returnLines",
                8,
                "26ddef7c1eea89d1c526eae5fc28baf1748aafb1f5670e0e6956edc37234f85a",
            ),
            (
                "shopify",
                "refunds",
                4,
                "ef5cf4cc4a8767650c95af120cc3db439d709c237c61f2376878f91c66b2aea5",
            ),
            (
                "shopify",
                "refundTransactions",
                4,
                "87bb237a16d3dfbfa6debd7fe72be6d28674f643119a4e21968d92240ed629a0",
            ),
            (
                "shopify",
                "webhookHmacFixtures",
                12,
                "771661d12efa6015d09dd471fef6cd6df7b9e580142252efa3864d9dfe36b7f6",
            ),
            (
                "businessCentral",
                "salesInvoices",
                1_026,
                "431e50079c9e7f4b08be04a6963a59825882cf9f30732dd48bbc3e59710a0cc5",
            ),
            (
                "businessCentral",
                "salesInvoiceLines",
                2_027,
                "3e6e0781f804df6ddedba75fe2d6ffce8ddd8aa78f0d562df8049b5a29dce390",
            ),
            (
                "hiddenTruth",
                "sourceEventCrosswalk",
                2_027,
                "1e36c16bc079d725b1327451fd62845a694e6a7900ac20e2443c92a1a567239c",
            ),
            (
                "businessCentral",
                "inventorySnapshots",
                5_256,
                "6000ce5e8691cf884cf5068dcdde8b107fcd55bddf772980d1cfdd03c6764d44",
            ),
            (
                "businessCentral",
                "storeInventorySnapshots",
                9_151,
                "c81764d0d53e038356ace18741a88b098d961ea36b73b75a7307cbbdea6268e4",
            ),
            (
                "businessCentral",
                "storeTransferEvents",
                158,
                "a76bdee18939ab72cf2f0725f7de140076d8f2ea04da9fbef7c71a4af013f204",
            ),
            (
                "businessCentral",
                "storeStockoutEvents",
                14,
                "ede384b7623c50a85bd0617ced7821e5cb2ce9fde6f4326a20faa445723589fc",
            ),
            (
                "businessCentral",
                "itemLedgerEntries",
                3_754,
                "aab85d0178b6612ad79092175f5b3770d383b5a6e5936e1fec8c43ae4021624a",
            ),
            (
                "businessCentral",
                "purchaseOrders",
                6,
                "fe28ee46846b551c7cc31c5180be172b8b6cf312dee1e4e70ff014f13f65bfd7",
            ),
            (
                "businessCentral",
                "purchaseOrderLines",
                55,
                "a5524e19e5fa331068f9e91aa7aba28a6b766a3268e12beae84a4b444cf13c53",
            ),
            (
                "businessCentral",
                "inboundShipments",
                6,
                "d8060c204ca22cb9457f4cb6115c6cbdbe09d4ac3297ff56f48d1c1e4e40bd49",
            ),
            (
                "businessCentral",
                "inboundStatusEvents",
                18,
                "1abe7ca140438c71931a6310819ebdca0dfb73ed22b077a4f0aadcac4e1fe6c3",
            ),
            (
                "businessCentral",
                "warehouseReceipts",
                27,
                "2b0fd56ff4438597d3aff63f500306ab0ad304dbac46d1b28ffac10695c0a216",
            ),
            (
                "businessCentral",
                "warehouseReceiptLines",
                52,
                "8b9b1c0ea032ee605d56e8d80e87c07ed66bd9076f7449521ffdfa3309f24ce3",
            ),
            (
                "businessCentral",
                "itemCostLayers",
                52,
                "d44f3df81e97764d886eedc3862fedc87247b64d2956ad90cccabc3bba3fdaa5",
            ),
            (
                "businessCentral",
                "itemBatches",
                1_749,
                "8ecce11e66401b3b57a860b357b2aa21096a34950c4727f5f500d9ce1b8655c0",
            ),
            (
                "businessCentral",
                "supplierPerformance",
                52,
                "3b14a3a41adad6815ce0f47a95040eb1489bb482faafc07a8dfa09e23dc28484",
            ),
            (
                "businessCentral",
                "supplierCapacityConfirmations",
                1,
                "40009b92b3d9ba777efbef5cf73ac07fe332bb7140d53a7745ca932d26ec3683",
            ),
            (
                "businessCentral",
                "purchasingBudgets",
                1,
                "c6bf544992eec81ebd08d3b631eaf6557b18c3819a1217829f1643d931ec4595",
            ),
            (
                "businessCentral",
                "supplyTerms",
                247,
                "48a20a218f771c91d7bf77eb85ec3d87ff890e829f2eaff366f670f9c34c3066",
            ),
            (
                "businessCentral",
                "warehouseCapacity",
                18,
                "b790690192136bb277281a6c55e70d9273388eea51c4cd22ebfc4b8642cd26df",
            ),
            (
                "businessCentral",
                "wmsInventoryComparisons",
                5_256,
                "079b3c1bd2e3736e85020632b594858e0b87b362dd03eaabec39d2acf87e3bfb",
            ),
            (
                "businessCentral",
                "wasteEvents",
                1,
                "3c5da96db2fa5d90ce35c8ad0139e9d9e8123b0025e635c96d44c21f8f1b1bea",
            ),
            (
                "companion",
                "allocationSupplyPools",
                5_256,
                "2066b54671cb4f140c47d0fb36f70581ffbf7c8d274c3ff96def414968fe2434",
            ),
            (
                "shopify",
                "inventoryLevels",
                1_752,
                "bea8b6372ff26b9778dac0813cd4dd9eaa8cf5b943f6d6e3be3b362f21f4b424",
            ),
            (
                "shopify",
                "inventoryQuantities",
                42_048,
                "72c629328a55f96660e5c7f8dbb4b3bfdee490890682b040e6a5ffb02b316237",
            ),
        ] {
            let selected = datasets
                .iter()
                .find(|row| row.source_system == source && row.dataset == dataset)
                .unwrap_or_else(|| panic!("missing {source}/{dataset}"));
            assert_eq!(
                ordered_digest(selected),
                (rows, digest.to_owned()),
                "{source}/{dataset}"
            );
        }
        let mut all = Vec::new();
        all.extend(
            datasets
                .iter()
                .map(|row| format!("{}/{}", row.source_system, row.dataset)),
        );
        all.extend(
            crate::projection::catalog::build_catalog_datasets(&config, &catalog)
                .expect("catalog projections")
                .into_iter()
                .map(|row| format!("{}/{}", row.source_system, row.dataset)),
        );
        all.extend(
            crate::projection::context::build_context_datasets(&config, &catalog)
                .expect("context projections")
                .into_iter()
                .map(|row| format!("{}/{}", row.source_system, row.dataset)),
        );
        all.extend(
            crate::projection::signals::build_signal_datasets(&config, &catalog)
                .expect("signal projections")
                .into_iter()
                .map(|row| format!("{}/{}", row.source_system, row.dataset)),
        );
        all.sort();
        let before_dedup = all.len();
        all.dedup();
        assert_eq!(
            all.len(),
            before_dedup,
            "duplicate logical dataset projections"
        );
        let mut expected_keys = contracts::dataset_keys();
        // Python publishes transfer relations only when at least one transfer
        // exists; this 14-day oracle is shorter than the configured cycle.
        expected_keys.retain(|key| {
            !matches!(
                key.as_str(),
                "businessCentral/transferOrders"
                    | "businessCentral/transferOrderLines"
                    | "businessCentral/transferShipments"
            )
        });
        assert_eq!(all, expected_keys, "complete Gulf-mini dataset set");
    }

    fn ordered_digest(dataset: &LogicalDataset) -> (usize, String) {
        let fields = contracts::fields(&dataset.source_system, &dataset.dataset).expect("fields");
        let mut hasher = Sha256::new();
        hasher.update(b"[");
        for (index, row) in dataset.rows.iter().enumerate() {
            if index > 0 {
                hasher.update(b",");
            }
            let normalized = fields
                .iter()
                .map(|field| row.get(field).filter(|value| !value.is_empty()).cloned())
                .collect::<Vec<_>>();
            hasher.update(serde_json::to_vec(&normalized).expect("JSON"));
        }
        hasher.update(b"]");
        (dataset.rows.len(), hex::encode(hasher.finalize()))
    }
}
