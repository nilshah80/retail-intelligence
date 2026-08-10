//! Exact daily distribution-centre inventory and replenishment state machine.
//!
//! This module deliberately follows the ordering in Python source contract v13.
//! Replenishment may consult only source-observable sales and availability; it
//! never uses latent demand from hidden truth.

use std::collections::BTreeMap;
use std::str::FromStr;

use anyhow::{Context, Result};
use chrono::{Duration, NaiveDate};
use rust_decimal::{Decimal as MoneyDecimal, RoundingStrategy};

use crate::catalog::{Product, Variant};
use crate::config::{LoadedConfig, Market, Warehouse};
use crate::deterministic::{PythonRandom, round_half_even_f64, stable_integer};
use crate::simulation::causal_effects::{event_effect, pandemic_effect};
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::inventory::{Batch, BatchPiece, InventoryKey, InventoryState};
use crate::simulation::model::FieldValues;
use crate::simulation::operations::local_iso_at;
use crate::simulation::pricing::PriceEngine;

#[derive(Debug, Default)]
pub struct SupplyEmissions {
    pub receipts: Vec<FieldValues>,
    pub transfers: Vec<FieldValues>,
    pub losses: Vec<FieldValues>,
    pub waste: Vec<FieldValues>,
    pub observations: Vec<FieldValues>,
    pub pools: Vec<FieldValues>,
}

impl SupplyEmissions {
    pub fn append(&mut self, mut other: Self) {
        self.receipts.append(&mut other.receipts);
        self.transfers.append(&mut other.transfers);
        self.losses.append(&mut other.losses);
        self.waste.append(&mut other.waste);
        self.observations.append(&mut other.observations);
        self.pools.append(&mut other.pools);
    }
}

#[derive(Debug, Clone)]
struct Receipt {
    receipt_key: String,
    market_id: String,
    warehouse_id: String,
    sku: String,
    product_code: String,
    variant_code: String,
    category_id: String,
    brand: String,
    brand_code: String,
    shelf_life_days: Option<i64>,
    costing_method: String,
    order_date: NaiveDate,
    expected_date: NaiveDate,
    actual_date: NaiveDate,
    ordered_quantity: i64,
    quantity: i64,
    unit_cost: MoneyDecimal,
    currency_code: String,
    delayed: bool,
    status: String,
    event_ids: Vec<String>,
    pandemic_ids: Vec<String>,
    pandemic_phase_ids: Vec<String>,
    lead_time_multiplier: Decimal,
    cost_multiplier: Decimal,
    inventory_loss_pct: Decimal,
}

impl Receipt {
    fn row(&self) -> FieldValues {
        values([
            ("receiptKey", self.receipt_key.clone()),
            ("marketId", self.market_id.clone()),
            ("warehouseId", self.warehouse_id.clone()),
            ("sku", self.sku.clone()),
            ("productCode", self.product_code.clone()),
            ("variantCode", self.variant_code.clone()),
            ("categoryId", self.category_id.clone()),
            ("brand", self.brand.clone()),
            ("brandCode", self.brand_code.clone()),
            (
                "shelfLifeDays",
                self.shelf_life_days
                    .map_or_else(String::new, |value| value.to_string()),
            ),
            ("costingMethod", self.costing_method.clone()),
            ("orderDate", self.order_date.to_string()),
            ("expectedDate", self.expected_date.to_string()),
            ("actualDate", self.actual_date.to_string()),
            ("orderedQuantity", self.ordered_quantity.to_string()),
            ("quantity", self.quantity.to_string()),
            ("unitCost", self.unit_cost.to_string()),
            ("currencyCode", self.currency_code.clone()),
            ("delayed", self.delayed.to_string()),
            ("status", self.status.clone()),
            ("eventIds", self.event_ids.join("|")),
            ("pandemicIds", self.pandemic_ids.join("|")),
            ("pandemicPhaseIds", self.pandemic_phase_ids.join("|")),
            ("leadTimeMultiplier", self.lead_time_multiplier.to_string()),
            ("costMultiplier", self.cost_multiplier.to_string()),
            ("inventoryLossPct", self.inventory_loss_pct.to_string()),
        ])
    }
}

#[derive(Debug, Clone)]
struct Transfer {
    transfer_key: String,
    market_id: String,
    sku: String,
    product_code: String,
    variant_code: String,
    from_warehouse_id: String,
    to_warehouse_id: String,
    request_date: NaiveDate,
    order_date: NaiveDate,
    shipment_date: NaiveDate,
    receipt_date: Option<NaiveDate>,
    requested_quantity: i64,
    shipped_quantity: i64,
    received_quantity: i64,
    status: String,
    batch_transfers: Vec<BatchPiece>,
}

impl Transfer {
    fn row(&self) -> FieldValues {
        values([
            ("transferKey", self.transfer_key.clone()),
            ("marketId", self.market_id.clone()),
            ("sku", self.sku.clone()),
            ("productCode", self.product_code.clone()),
            ("variantCode", self.variant_code.clone()),
            ("fromWarehouseId", self.from_warehouse_id.clone()),
            ("toWarehouseId", self.to_warehouse_id.clone()),
            ("requestDate", self.request_date.to_string()),
            ("orderDate", self.order_date.to_string()),
            ("shipmentDate", self.shipment_date.to_string()),
            (
                "receiptDate",
                self.receipt_date
                    .map_or_else(String::new, |value| value.to_string()),
            ),
            ("requestedQuantity", self.requested_quantity.to_string()),
            ("shippedQuantity", self.shipped_quantity.to_string()),
            ("receivedQuantity", self.received_quantity.to_string()),
            ("status", self.status.clone()),
        ])
    }
}

#[derive(Debug, Clone)]
struct QualityRelease {
    warehouse_id: String,
    sku: String,
    quantity: i64,
}

#[derive(Debug, Clone)]
struct Disposal {
    waste_event_key: String,
    receipt_key: String,
    warehouse_id: String,
    market_id: String,
    sku: String,
    product_code: String,
    variant_code: String,
    event_date: NaiveDate,
    quantity: i64,
    reason: String,
}

pub struct SupplyState {
    start: NaiveDate,
    end: NaiveDate,
    master_seed: u64,
    receipts_by_date: BTreeMap<NaiveDate, Vec<Receipt>>,
    transfer_receipts_by_date: BTreeMap<NaiveDate, Vec<Transfer>>,
    quality_releases_by_date: BTreeMap<NaiveDate, Vec<QualityRelease>>,
    waste_disposals_by_date: BTreeMap<NaiveDate, Vec<Disposal>>,
    receipt_cycle_by_sku: BTreeMap<InventoryKey, i64>,
    realized_demand_by_day: BTreeMap<InventoryKey, BTreeMap<NaiveDate, Decimal>>,
    available_to_sell_by_day: BTreeMap<InventoryKey, BTreeMap<NaiveDate, bool>>,
    price_engine: PriceEngine,
}

impl SupplyState {
    #[must_use]
    pub fn new(config: &LoadedConfig) -> Self {
        Self {
            start: config.scenario.time.start_date,
            end: config.scenario.time.end_date,
            master_seed: config.scenario.identity.master_seed,
            receipts_by_date: BTreeMap::new(),
            transfer_receipts_by_date: BTreeMap::new(),
            quality_releases_by_date: BTreeMap::new(),
            waste_disposals_by_date: BTreeMap::new(),
            receipt_cycle_by_sku: BTreeMap::new(),
            realized_demand_by_day: BTreeMap::new(),
            available_to_sell_by_day: BTreeMap::new(),
            price_engine: PriceEngine::new(),
        }
    }

    pub fn begin_day(
        &mut self,
        config: &LoadedConfig,
        catalog: &[Product],
        inventory: &mut InventoryState,
        day: NaiveDate,
    ) -> Result<SupplyEmissions> {
        let mut emitted = SupplyEmissions::default();

        for release in self
            .quality_releases_by_date
            .remove(&day)
            .unwrap_or_default()
        {
            let key = InventoryKey::new(&release.warehouse_id, &release.sku);
            let current = InventoryState::value(&inventory.quality_control, &key);
            inventory
                .quality_control
                .insert(key, (current - release.quantity).max(0));
        }

        for disposal in self
            .waste_disposals_by_date
            .remove(&day)
            .unwrap_or_default()
        {
            let key = InventoryKey::new(&disposal.warehouse_id, &disposal.sku);
            let quantity = disposal
                .quantity
                .min(InventoryState::value(&inventory.damaged, &key))
                .min(InventoryState::value(&inventory.on_hand, &key));
            if quantity == 0 {
                continue;
            }
            *inventory.damaged.entry(key.clone()).or_default() -= quantity;
            *inventory.on_hand.entry(key.clone()).or_default() -= quantity;
            let consumed = inventory.batches.deplete(&key, quantity, None)?;
            let batch_key = consumed
                .first()
                .context("waste disposal consumed no batch")?
                .batch
                .batch_key
                .clone();
            emitted.waste.push(values([
                ("wasteEventKey", disposal.waste_event_key),
                ("receiptKey", disposal.receipt_key),
                ("batchKey", batch_key),
                ("warehouseId", disposal.warehouse_id),
                ("marketId", disposal.market_id),
                ("sku", disposal.sku),
                ("productCode", disposal.product_code),
                ("variantCode", disposal.variant_code),
                ("eventDate", disposal.event_date.to_string()),
                ("quantity", quantity.to_string()),
                ("reason", disposal.reason),
            ]));
        }

        for batch_key in inventory.batches.expiry_keys(day) {
            let Some(batch) = inventory.batches.batch(&batch_key).cloned() else {
                continue;
            };
            if batch.quantity_remaining_at_extract <= 0 {
                continue;
            }
            let key = InventoryKey::new(&batch.warehouse_id, &batch.sku);
            let free_inventory = inventory.free_inventory(&key);
            let quantity = free_inventory.min(batch.quantity_remaining_at_extract);
            if quantity == 0 {
                inventory
                    .batches
                    .reschedule_expiry(day + Duration::days(1), batch_key);
                continue;
            }
            inventory
                .batches
                .deplete(&key, quantity, Some(&batch_key))?;
            *inventory.on_hand.entry(key).or_default() -= quantity;
            emitted.waste.push(values([
                ("wasteEventKey", format!("expiry:{}:{day}", batch.batch_key)),
                ("receiptKey", batch.source_reference),
                ("batchKey", batch.batch_key.clone()),
                ("warehouseId", batch.warehouse_id.clone()),
                (
                    "marketId",
                    warehouse(config, &batch.warehouse_id)?.market_id.clone(),
                ),
                ("sku", batch.sku.clone()),
                ("productCode", batch.product_code),
                ("variantCode", batch.variant_code),
                ("eventDate", day.to_string()),
                ("quantity", quantity.to_string()),
                ("reason", "expired".to_owned()),
            ]));
            if inventory
                .batches
                .batch(&batch.batch_key)
                .is_some_and(|row| row.quantity_remaining_at_extract > 0)
            {
                inventory
                    .batches
                    .reschedule_expiry(day + Duration::days(1), batch.batch_key);
            }
        }

        let mut losses = BTreeMap::<InventoryKey, (Decimal, Vec<String>)>::new();
        for warehouse in &config.scenario.warehouses {
            for product in catalog
                .iter()
                .filter(|row| row.market_id == warehouse.market_id)
            {
                for variant in &product.variants {
                    let event = event_effect(
                        config,
                        day,
                        &warehouse.market_id,
                        "",
                        &product.department_id,
                        &product.category_id,
                        "",
                    );
                    let pandemic = pandemic_effect(
                        config,
                        day,
                        &warehouse.market_id,
                        &product.department_id,
                        &product.category_id,
                        &product.catalog_family,
                        "",
                    )?;
                    let starts_today =
                        config.scenario.events.iter().any(|row| {
                            row.start_date == day && event.event_ids.contains(&row.event_id)
                        }) || pandemic_phase_starts_today(config, &pandemic.phase_ids, day);
                    let rate = event
                        .inventory_loss
                        .clone()
                        .max(pandemic.inventory_loss.clone());
                    if starts_today && rate > Decimal::zero() {
                        let mut causes = event.event_ids;
                        causes.extend(pandemic.phase_ids);
                        losses.insert(
                            InventoryKey::new(&warehouse.warehouse_id, &variant.sku),
                            (rate, causes),
                        );
                    }
                }
            }
        }
        for (key, (rate, mut causes)) in losses {
            let exposed = inventory.free_inventory(&key);
            let lost = i64::try_from(round_half_even_f64(
                exposed as f64 * rate.to_f64().context("inventory loss rate")?,
            ) as i128)?
            .min(exposed);
            if lost == 0 {
                continue;
            }
            *inventory.on_hand.entry(key.clone()).or_default() -= lost;
            inventory.batches.deplete(&key, lost, None)?;
            causes.sort();
            let (product, variant) = catalog_variant(catalog, &key.sku)?;
            emitted.losses.push(values([
                ("warehouseId", key.warehouse_id.clone()),
                ("sku", key.sku.clone()),
                (
                    "marketId",
                    warehouse(config, &key.warehouse_id)?.market_id.clone(),
                ),
                ("productCode", product.product_code.clone()),
                ("variantCode", variant.variant_code.clone()),
                ("eventDate", day.to_string()),
                ("lostQuantity", lost.to_string()),
                ("inventoryLossPct", rate.to_string()),
                ("causeIds", causes.join("|")),
            ]));
        }

        for receipt in self.receipts_by_date.remove(&day).unwrap_or_default() {
            let key = InventoryKey::new(&receipt.warehouse_id, &receipt.sku);
            *inventory.on_hand.entry(key.clone()).or_default() += receipt.quantity;
            let (product, variant) = catalog_variant(catalog, &receipt.sku)?;
            inventory.batches.add(
                format!("batch:{}", receipt.receipt_key),
                "purchase-receipt",
                receipt.receipt_key.clone(),
                &receipt.warehouse_id,
                product,
                variant,
                day,
                receipt.quantity,
                None,
                None,
                None,
            );
            let mut damaged = 0_i64;
            if feature(config, "warehouseOperations")
                && receipt.quantity > 0
                && fraction(&[
                    &self.master_seed.to_string(),
                    "receipt-waste",
                    &receipt.receipt_key,
                ]) < number(&config.scenario.operations.supply_chain, "wasteRate")?
            {
                damaged = 1;
                *inventory.damaged.entry(key.clone()).or_default() += damaged;
                let lag = 1 + i64::try_from(stable_integer(
                    &[
                        &self.master_seed.to_string(),
                        "waste-disposal-lag",
                        &receipt.receipt_key,
                    ],
                    3,
                ))?;
                let disposal_day = day + Duration::days(lag);
                self.waste_disposals_by_date
                    .entry(disposal_day)
                    .or_default()
                    .push(Disposal {
                        waste_event_key: format!("waste:{}", receipt.receipt_key),
                        receipt_key: receipt.receipt_key.clone(),
                        warehouse_id: receipt.warehouse_id.clone(),
                        market_id: receipt.market_id.clone(),
                        sku: receipt.sku.clone(),
                        product_code: receipt.product_code.clone(),
                        variant_code: receipt.variant_code.clone(),
                        event_date: disposal_day,
                        quantity: damaged,
                        reason: "damage-in-handling".to_owned(),
                    });
            }
            if feature(config, "warehouseOperations") && receipt.quantity > damaged {
                let quality = (1 + i64::try_from(stable_integer(
                    &[
                        &self.master_seed.to_string(),
                        "receipt-quality-control",
                        &receipt.receipt_key,
                    ],
                    3,
                ))?)
                .min(receipt.quantity - damaged);
                *inventory.quality_control.entry(key).or_default() += quality;
                let hold = integer_or(
                    &config.scenario.operations.inventory,
                    "qualityControlHoldDays",
                    1,
                );
                self.quality_releases_by_date
                    .entry(day + Duration::days(hold))
                    .or_default()
                    .push(QualityRelease {
                        warehouse_id: receipt.warehouse_id,
                        sku: receipt.sku,
                        quantity: quality,
                    });
            }
        }

        for transfer in self
            .transfer_receipts_by_date
            .remove(&day)
            .unwrap_or_default()
        {
            let key = InventoryKey::new(&transfer.to_warehouse_id, &transfer.sku);
            *inventory.on_hand.entry(key).or_default() += transfer.received_quantity;
            let (product, variant) = catalog_variant(catalog, &transfer.sku)?;
            for (index, source) in transfer.batch_transfers.iter().enumerate() {
                inventory.batches.add(
                    format!(
                        "transfer:{}:{:03}:{}",
                        transfer.transfer_key,
                        index + 1,
                        source.batch.batch_key
                    ),
                    "transfer-receipt",
                    transfer.transfer_key.clone(),
                    &transfer.to_warehouse_id,
                    product,
                    variant,
                    day,
                    source.quantity,
                    Some(source.batch.manufacture_date),
                    source.batch.expiry_date,
                    Some(day + Duration::days(1)),
                );
            }
        }
        Ok(emitted)
    }

    pub fn plan_day(
        &mut self,
        config: &LoadedConfig,
        catalog: &[Product],
        inventory: &mut InventoryState,
        day: NaiveDate,
    ) -> Result<SupplyEmissions> {
        let mut emitted = SupplyEmissions::default();
        let inventory_policy = &config.scenario.operations.inventory;
        let supply_policy = &config.scenario.operations.supply_chain;
        let cycle = integer(inventory_policy, "replenishmentCycleDays")?;
        let lead = integer(inventory_policy, "supplierLeadTimeDays")?;
        let jitter = integer(inventory_policy, "supplierLeadTimeJitterDays")?;
        if (day - self.start).num_days() % cycle == 0 {
            let mut warehouses = config.scenario.warehouses.iter().collect::<Vec<_>>();
            warehouses.sort_by(|left, right| left.warehouse_id.cmp(&right.warehouse_id));
            for warehouse in warehouses {
                let market = market(config, &warehouse.market_id)?;
                for product in catalog
                    .iter()
                    .filter(|row| row.market_id == warehouse.market_id)
                {
                    for variant in &product.variants {
                        if variant.launch_date > day + Duration::days(lead)
                            || variant.discontinue_date.is_some_and(|end| end < day)
                        {
                            continue;
                        }
                        let key = InventoryKey::new(&warehouse.warehouse_id, &variant.sku);
                        let history_days = 28_i64.min((day - self.start).num_days());
                        let observed_rate = if history_days == 0 {
                            Decimal::zero()
                        } else {
                            let history = (1..=history_days)
                                .map(|offset| day - Duration::days(offset))
                                .collect::<Vec<_>>();
                            let observable = history
                                .iter()
                                .copied()
                                .filter(|history_day| {
                                    self.available_to_sell_by_day
                                        .get(&key)
                                        .and_then(|rows| rows.get(history_day))
                                        .copied()
                                        .unwrap_or(false)
                                })
                                .collect::<Vec<_>>();
                            let rate_days = if observable.is_empty() {
                                &history
                            } else {
                                &observable
                            };
                            let total = rate_days
                                .iter()
                                .map(|history_day| {
                                    self.realized_demand_by_day
                                        .get(&key)
                                        .and_then(|rows| rows.get(history_day))
                                        .cloned()
                                        .unwrap_or_else(Decimal::zero)
                                })
                                .sum::<Decimal>();
                            total / Decimal::from(rate_days.len())
                        };
                        let buffer =
                            decimal_value(&inventory_policy["replenishmentDemandBufferPct"])?;
                        let daily_rate = observed_rate * (Decimal::one() + buffer);
                        let pending = self
                            .receipts_by_date
                            .range((day + Duration::days(1))..)
                            .flat_map(|(_, rows)| rows)
                            .filter(|row| {
                                row.warehouse_id == warehouse.warehouse_id && row.sku == variant.sku
                            })
                            .map(|row| row.quantity)
                            .sum::<i64>();
                        let position = InventoryState::value(&inventory.on_hand, &key)
                            - InventoryState::value(&inventory.committed, &key)
                            - InventoryState::value(&inventory.damaged, &key)
                            + pending;
                        let safety = integer(inventory_policy, "safetyStockUnits")?;
                        let mut target = (daily_rate * Decimal::from(lead + cycle + jitter + 2)
                            + Decimal::from(safety))
                        .ceil_i64()
                        .context("replenishment target")?;
                        let pack = i64::from(warehouse.replenishment_pack_size);
                        if position < pack {
                            target = target.max(pack);
                        }
                        let required = (target - position).max(0);
                        if required == 0 {
                            continue;
                        }
                        let ordered = pack.max(((required + pack - 1) / pack) * pack);
                        let cycle_index = {
                            let value = self.receipt_cycle_by_sku.entry(key).or_default();
                            *value += 1;
                            *value
                        };
                        let expected = variant.launch_date.max(day + Duration::days(lead));
                        let event = event_effect(
                            config,
                            expected,
                            &warehouse.market_id,
                            "",
                            &product.department_id,
                            &product.category_id,
                            "",
                        );
                        let pandemic = pandemic_effect(
                            config,
                            expected,
                            &warehouse.market_id,
                            &product.department_id,
                            &product.category_id,
                            &product.catalog_family,
                            "",
                        )?;
                        let lead_multiplier = &event.lead_time * &pandemic.lead_time;
                        let cost_multiplier = &event.cost * &pandemic.cost;
                        let inventory_loss = event
                            .inventory_loss
                            .clone()
                            .max(pandemic.inventory_loss.clone());
                        let cycle_text = cycle_index.to_string();
                        let master_text = self.master_seed.to_string();
                        let delayed = fraction(&[
                            &master_text,
                            "supplier-delay",
                            &warehouse.warehouse_id,
                            &variant.sku,
                            &cycle_text,
                        ]) < number(supply_policy, "supplierDelayRate")?;
                        let mut delay_days = if jitter == 0 {
                            0
                        } else {
                            i64::try_from(stable_integer(
                                &[
                                    &master_text,
                                    "supplier-jitter",
                                    &warehouse.warehouse_id,
                                    &variant.sku,
                                    &cycle_text,
                                ],
                                u64::try_from(jitter + 1)?,
                            ))?
                        };
                        if delayed {
                            delay_days += jitter.max(1);
                        }
                        if lead_multiplier > Decimal::one() {
                            delay_days += (round_half_even_f64(
                                lead as f64
                                    * (&lead_multiplier - Decimal::one())
                                        .to_f64()
                                        .context("lead multiplier")?,
                            ) as i64)
                                .max(1);
                        }
                        let actual = expected + Duration::days(delay_days);
                        let fill_rate = Decimal::from_f64_text(
                            PythonRandom::new(
                                self.master_seed,
                                &[
                                    "supplier-fill-rate",
                                    &warehouse.warehouse_id,
                                    &variant.sku,
                                    &cycle_text,
                                ],
                            )
                            .uniform(0.86, 1.0),
                        );
                        let quantity = (round_half_even_f64(
                            ordered as f64
                                * fill_rate.to_f64().context("fill rate")?
                                * (Decimal::one() - &inventory_loss)
                                    .to_f64()
                                    .context("inventory loss")?,
                        ) as i64)
                            .max(0);
                        let regular_cost = self.price_engine.price_for_day(
                            variant.base_cost,
                            market,
                            &format!("{}:cost", variant.sku),
                            expected,
                            self.start,
                            self.end,
                            variant.launch_date,
                        )?;
                        let cost = quantize_money(regular_cost * money_decimal(&cost_multiplier)?);
                        let receipt = Receipt {
                            receipt_key: format!(
                                "{}:{}:{}",
                                warehouse.warehouse_id, variant.sku, expected
                            ),
                            market_id: warehouse.market_id.clone(),
                            warehouse_id: warehouse.warehouse_id.clone(),
                            sku: variant.sku.clone(),
                            product_code: product.product_code.clone(),
                            variant_code: variant.variant_code.clone(),
                            category_id: product.category_id.clone(),
                            brand: product.brand.clone(),
                            brand_code: product.brand_code.clone(),
                            shelf_life_days: product.shelf_life_days,
                            costing_method: product.costing_method.clone(),
                            order_date: day,
                            expected_date: expected,
                            actual_date: actual,
                            ordered_quantity: ordered,
                            quantity,
                            unit_cost: cost,
                            currency_code: market.currency_code.clone(),
                            delayed: actual > expected,
                            status: if actual <= self.end {
                                "Received".to_owned()
                            } else {
                                "In Transit".to_owned()
                            },
                            event_ids: event.event_ids,
                            pandemic_ids: pandemic.pandemic_ids,
                            pandemic_phase_ids: pandemic.phase_ids,
                            lead_time_multiplier: lead_multiplier,
                            cost_multiplier,
                            inventory_loss_pct: inventory_loss,
                        };
                        emitted.receipts.push(receipt.row());
                        self.receipts_by_date
                            .entry(actual)
                            .or_default()
                            .push(receipt);
                    }
                }
            }
        }

        let transfer_cycle = integer(supply_policy, "transferCycleDays")?;
        if feature(config, "transfers")
            && (day - self.start).num_days() != 0
            && (day - self.start).num_days() % transfer_cycle == 0
        {
            let mut market_ids = config
                .scenario
                .markets
                .iter()
                .map(|row| row.market_id.clone())
                .collect::<Vec<_>>();
            market_ids.sort();
            for market_id in market_ids {
                let mut warehouses = config
                    .scenario
                    .warehouses
                    .iter()
                    .filter(|row| row.market_id == market_id)
                    .collect::<Vec<_>>();
                warehouses.sort_by(|left, right| left.warehouse_id.cmp(&right.warehouse_id));
                if warehouses.len() < 2 {
                    continue;
                }
                let source = warehouses[0];
                let destination = warehouses[1];
                for product in catalog.iter().filter(|row| row.market_id == market_id) {
                    for variant in &product.variants {
                        let day_text = day.to_string();
                        let master_text = self.master_seed.to_string();
                        if fraction(&[
                            &master_text,
                            "transfer",
                            &market_id,
                            &variant.sku,
                            &day_text,
                        ]) >= number(supply_policy, "transferSkuRate")?
                        {
                            continue;
                        }
                        let source_key = InventoryKey::new(&source.warehouse_id, &variant.sku);
                        let safety = integer(inventory_policy, "safetyStockUnits")?;
                        let available = (inventory.free_inventory(&source_key) - safety).max(0);
                        let quantity = available.min(
                            2 + i64::try_from(stable_integer(
                                &[
                                    &master_text,
                                    "transfer-quantity",
                                    &market_id,
                                    &variant.sku,
                                    &day_text,
                                ],
                                5,
                            ))?,
                        );
                        if quantity == 0 {
                            continue;
                        }
                        *inventory.on_hand.entry(source_key.clone()).or_default() -= quantity;
                        let pieces = inventory.batches.deplete(&source_key, quantity, None)?;
                        let transit = 1 + i64::try_from(stable_integer(
                            &[
                                &master_text,
                                "transfer-transit",
                                &market_id,
                                &variant.sku,
                                &day_text,
                            ],
                            3,
                        ))?;
                        let receipt_day = day + Duration::days(transit);
                        let transfer = Transfer {
                            transfer_key: format!(
                                "{}:{}:{}:{day}",
                                source.warehouse_id, destination.warehouse_id, variant.sku
                            ),
                            market_id: market_id.clone(),
                            sku: variant.sku.clone(),
                            product_code: product.product_code.clone(),
                            variant_code: variant.variant_code.clone(),
                            from_warehouse_id: source.warehouse_id.clone(),
                            to_warehouse_id: destination.warehouse_id.clone(),
                            request_date: day - Duration::days(2),
                            order_date: day - Duration::days(1),
                            shipment_date: day,
                            receipt_date: (receipt_day <= self.end).then_some(receipt_day),
                            requested_quantity: quantity,
                            shipped_quantity: quantity,
                            received_quantity: if receipt_day <= self.end { quantity } else { 0 },
                            status: if receipt_day <= self.end {
                                "Received".to_owned()
                            } else {
                                "In Transit".to_owned()
                            },
                            batch_transfers: pieces,
                        };
                        emitted.transfers.push(transfer.row());
                        if receipt_day <= self.end {
                            self.transfer_receipts_by_date
                                .entry(receipt_day)
                                .or_default()
                                .push(transfer);
                        }
                    }
                }
            }
        }
        Ok(emitted)
    }

    pub fn capture_availability(
        &mut self,
        config: &LoadedConfig,
        catalog: &[Product],
        inventory: &InventoryState,
        day: NaiveDate,
    ) -> Result<()> {
        let expired = day - Duration::days(29);
        let safety = integer(&config.scenario.operations.inventory, "safetyStockUnits")?;
        for warehouse in &config.scenario.warehouses {
            for product in catalog
                .iter()
                .filter(|row| row.market_id == warehouse.market_id)
            {
                for variant in &product.variants {
                    let key = InventoryKey::new(&warehouse.warehouse_id, &variant.sku);
                    self.available_to_sell_by_day
                        .entry(key.clone())
                        .or_default()
                        .remove(&expired);
                    self.realized_demand_by_day
                        .entry(key.clone())
                        .or_default()
                        .remove(&expired);
                    let available = InventoryState::value(&inventory.on_hand, &key)
                        - InventoryState::value(&inventory.committed, &key)
                        - InventoryState::value(&inventory.damaged, &key)
                        - InventoryState::value(&inventory.quality_control, &key)
                        - safety
                        > 0;
                    self.available_to_sell_by_day
                        .entry(key)
                        .or_default()
                        .insert(day, available);
                }
            }
        }
        Ok(())
    }

    pub fn record_allocation(&mut self, warehouse_id: &str, sku: &str, day: NaiveDate, units: i64) {
        let key = InventoryKey::new(warehouse_id, sku);
        let prior = self
            .realized_demand_by_day
            .entry(key)
            .or_default()
            .get(&day)
            .cloned()
            .unwrap_or_else(Decimal::zero);
        self.realized_demand_by_day
            .entry(InventoryKey::new(warehouse_id, sku))
            .or_default()
            .insert(day, prior + Decimal::from(units));
    }

    pub fn snapshot(
        &self,
        config: &LoadedConfig,
        catalog: &[Product],
        inventory: &InventoryState,
        day: NaiveDate,
    ) -> Result<SupplyEmissions> {
        let cadence = integer(&config.scenario.operations.inventory, "snapshotCadenceDays")?;
        if (day - self.start).num_days() % cadence != 0 && day != self.end {
            return Ok(SupplyEmissions::default());
        }
        let horizon = integer(
            &config.scenario.operations.supply_chain,
            "weatherForecastHorizonDays",
        )?;
        let configured_safety = integer(&config.scenario.operations.inventory, "safetyStockUnits")?;
        let mut emitted = SupplyEmissions::default();
        let mut warehouses = config.scenario.warehouses.iter().collect::<Vec<_>>();
        warehouses.sort_by(|left, right| left.warehouse_id.cmp(&right.warehouse_id));
        for warehouse in warehouses {
            let market = market(config, &warehouse.market_id)?;
            for product in catalog
                .iter()
                .filter(|row| row.market_id == warehouse.market_id)
            {
                for variant in &product.variants {
                    let key = InventoryKey::new(&warehouse.warehouse_id, &variant.sku);
                    let on_hand = InventoryState::value(&inventory.on_hand, &key);
                    let mut remaining = on_hand;
                    let committed =
                        remaining.min(InventoryState::value(&inventory.committed, &key));
                    remaining -= committed;
                    let reserved = 0_i64;
                    let damaged = remaining.min(InventoryState::value(&inventory.damaged, &key));
                    remaining -= damaged;
                    let quality =
                        remaining.min(InventoryState::value(&inventory.quality_control, &key));
                    remaining -= quality;
                    let safety = remaining.min(configured_safety);
                    let available = remaining - safety;
                    let incoming_receipts = self
                        .receipts_by_date
                        .range((day + Duration::days(1))..=(day + Duration::days(horizon)))
                        .flat_map(|(_, rows)| rows)
                        .filter(|row| {
                            row.warehouse_id == warehouse.warehouse_id && row.sku == variant.sku
                        })
                        .map(|row| row.quantity)
                        .sum::<i64>();
                    let incoming_transfers = self
                        .transfer_receipts_by_date
                        .range((day + Duration::days(1))..=(day + Duration::days(horizon)))
                        .flat_map(|(_, rows)| rows)
                        .filter(|row| {
                            row.to_warehouse_id == warehouse.warehouse_id && row.sku == variant.sku
                        })
                        .map(|row| row.received_quantity)
                        .sum::<i64>();
                    let incoming = incoming_receipts + incoming_transfers;
                    let observed_at = local_iso_at(day, 23, 0, 0, &market.timezone)?;
                    emitted.observations.push(values([
                        ("marketKey", warehouse.market_id.clone()),
                        ("warehouseKey", warehouse.warehouse_id.clone()),
                        ("observedAt", observed_at),
                        ("sku", variant.sku.clone()),
                        ("onHand", on_hand.to_string()),
                        ("available", available.to_string()),
                        ("committed", committed.to_string()),
                        ("reserved", reserved.to_string()),
                        ("damaged", damaged.to_string()),
                        ("qualityControl", quality.to_string()),
                        ("safetyStock", safety.to_string()),
                        ("incoming", incoming.to_string()),
                        ("blocked", (damaged + quality).to_string()),
                    ]));
                    emitted.pools.push(values([
                        (
                            "poolKey",
                            format!("{}:{}:{day}", warehouse.warehouse_id, variant.sku),
                        ),
                        ("marketKey", warehouse.market_id.clone()),
                        ("warehouseKey", warehouse.warehouse_id.clone()),
                        ("snapshotDate", day.to_string()),
                        ("sku", variant.sku.clone()),
                        ("availableQuantity", available.to_string()),
                        ("incomingQuantity", incoming.to_string()),
                        ("safetyStockQuantity", safety.to_string()),
                    ]));
                }
            }
        }
        Ok(emitted)
    }

    #[must_use]
    pub fn batch_rows(inventory: &InventoryState) -> Vec<FieldValues> {
        inventory
            .batches
            .finalized_batches()
            .iter()
            .chain({
                let mut active = inventory.batches.active_batches().collect::<Vec<_>>();
                active.sort_by(|left, right| {
                    (
                        &left.warehouse_id,
                        &left.sku,
                        left.receipt_date,
                        &left.batch_key,
                    )
                        .cmp(&(
                            &right.warehouse_id,
                            &right.sku,
                            right.receipt_date,
                            &right.batch_key,
                        ))
                });
                active
            })
            .map(batch_row)
            .collect()
    }
}

fn batch_row(batch: &Batch) -> FieldValues {
    values([
        ("batchKey", batch.batch_key.clone()),
        ("sourceType", batch.source_type.clone()),
        ("sourceReference", batch.source_reference.clone()),
        ("warehouseId", batch.warehouse_id.clone()),
        ("sku", batch.sku.clone()),
        ("productCode", batch.product_code.clone()),
        ("variantCode", batch.variant_code.clone()),
        ("manufactureDate", batch.manufacture_date.to_string()),
        ("receiptDate", batch.receipt_date.to_string()),
        (
            "expiryDate",
            batch
                .expiry_date
                .map_or_else(String::new, |value| value.to_string()),
        ),
        ("quantityReceived", batch.quantity_received.to_string()),
        (
            "quantityRemainingAtExtract",
            batch.quantity_remaining_at_extract.to_string(),
        ),
    ])
}

fn pandemic_phase_starts_today(
    config: &LoadedConfig,
    phase_ids: &[String],
    day: NaiveDate,
) -> bool {
    config.scenario.pandemics.iter().any(|pandemic| {
        pandemic["phases"].as_array().is_some_and(|phases| {
            phases.iter().any(|phase| {
                phase["startDate"].as_str() == Some(&day.to_string())
                    && phase_ids
                        .iter()
                        .any(|id| phase["phaseId"].as_str() == Some(id))
            })
        })
    })
}

fn warehouse<'a>(config: &'a LoadedConfig, warehouse_id: &str) -> Result<&'a Warehouse> {
    config
        .scenario
        .warehouses
        .iter()
        .find(|row| row.warehouse_id == warehouse_id)
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

fn catalog_variant<'a>(catalog: &'a [Product], sku: &str) -> Result<(&'a Product, &'a Variant)> {
    for product in catalog {
        if let Some(variant) = product.variants.iter().find(|row| row.sku == sku) {
            return Ok((product, variant));
        }
    }
    anyhow::bail!("unknown SKU {sku}")
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

fn integer(value: &serde_json::Value, key: &str) -> Result<i64> {
    value[key]
        .as_i64()
        .with_context(|| format!("missing integer {key}"))
}

fn integer_or(value: &serde_json::Value, key: &str, default: i64) -> i64 {
    value[key].as_i64().unwrap_or(default)
}

fn number(value: &serde_json::Value, key: &str) -> Result<f64> {
    value[key]
        .as_f64()
        .with_context(|| format!("missing number {key}"))
}

fn decimal_value(value: &serde_json::Value) -> Result<Decimal> {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
        .parse()
        .context("decimal value")
}

fn money_decimal(value: &Decimal) -> Result<MoneyDecimal> {
    MoneyDecimal::from_str(&value.normalized_string()).context("fixed money decimal")
}

fn quantize_money(value: MoneyDecimal) -> MoneyDecimal {
    let mut result = value.round_dp_with_strategy(2, RoundingStrategy::MidpointNearestEven);
    result.rescale(2);
    result
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

fn values<const N: usize>(entries: [(&'static str, String); N]) -> FieldValues {
    entries.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use rust_decimal::Decimal;

    use super::quantize_money;

    #[test]
    fn receipt_cost_uses_python_half_even_money_rounding() {
        let value = Decimal::from_str("782.50").unwrap() * Decimal::from_str("1.170").unwrap();
        assert_eq!(value.to_string(), "915.52500");
        assert_eq!(quantize_money(value).to_string(), "915.52");
    }
}
