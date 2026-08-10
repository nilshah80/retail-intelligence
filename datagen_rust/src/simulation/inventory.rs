use anyhow::{Context, Result, ensure};
use chrono::{Datelike, Duration, NaiveDate};
use std::collections::BTreeMap;

use crate::catalog::{Product, Variant, active_on};
use crate::config::{LoadedConfig, Store};
use crate::deterministic::stable_integer;
use crate::simulation::assortment::{SelectedVariant, StoreAssortment};
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::demand::{
    Allocation, average_active_portfolio_weight, expected_units_per_line, portfolio_weight,
};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct InventoryKey {
    pub warehouse_id: String,
    pub sku: String,
}

impl InventoryKey {
    #[must_use]
    pub fn new(warehouse_id: impl Into<String>, sku: impl Into<String>) -> Self {
        Self {
            warehouse_id: warehouse_id.into(),
            sku: sku.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Batch {
    pub batch_key: String,
    pub source_type: String,
    pub source_reference: String,
    pub warehouse_id: String,
    pub sku: String,
    pub product_code: String,
    pub variant_code: String,
    pub manufacture_date: NaiveDate,
    pub receipt_date: NaiveDate,
    pub expiry_date: Option<NaiveDate>,
    pub quantity_received: i64,
    pub quantity_remaining_at_extract: i64,
}

#[derive(Debug, Clone)]
pub struct BatchPiece {
    pub batch: Batch,
    pub quantity: i64,
}

#[derive(Debug, Default)]
pub struct BatchBook {
    by_key: BTreeMap<String, Batch>,
    keys_by_inventory: BTreeMap<InventoryKey, Vec<String>>,
    expiry_by_date: BTreeMap<NaiveDate, Vec<String>>,
    finalized: Vec<Batch>,
}

impl BatchBook {
    #[allow(clippy::too_many_arguments)]
    pub fn add(
        &mut self,
        batch_key: String,
        source_type: &str,
        source_reference: String,
        warehouse_id: &str,
        product: &Product,
        variant: &Variant,
        receipt_day: NaiveDate,
        quantity: i64,
        manufacture_day: Option<NaiveDate>,
        expiry_day: Option<NaiveDate>,
        earliest_expiry_event: Option<NaiveDate>,
    ) -> Option<&Batch> {
        if quantity <= 0 {
            return None;
        }
        let manufacture_date = manufacture_day.unwrap_or_else(|| {
            receipt_day
                - Duration::days(if product.shelf_life_days.is_some_and(|days| days <= 30) {
                    3
                } else {
                    30
                })
        });
        let expiry_date = expiry_day.or_else(|| {
            product
                .shelf_life_days
                .map(|days| receipt_day + Duration::days(days))
        });
        let batch = Batch {
            batch_key: batch_key.clone(),
            source_type: source_type.to_owned(),
            source_reference,
            warehouse_id: warehouse_id.to_owned(),
            sku: variant.sku.clone(),
            product_code: product.product_code.clone(),
            variant_code: variant.variant_code.clone(),
            manufacture_date,
            receipt_date: receipt_day,
            expiry_date,
            quantity_received: quantity,
            quantity_remaining_at_extract: quantity,
        };
        let key = InventoryKey::new(warehouse_id, &variant.sku);
        self.keys_by_inventory
            .entry(key)
            .or_default()
            .push(batch_key.clone());
        if let Some(expiry) = expiry_date {
            let event_day =
                (expiry + Duration::days(1)).max(earliest_expiry_event.unwrap_or(NaiveDate::MIN));
            self.expiry_by_date
                .entry(event_day)
                .or_default()
                .push(batch_key.clone());
        }
        self.by_key.insert(batch_key.clone(), batch);
        self.by_key.get(&batch_key)
    }

    pub fn deplete(
        &mut self,
        inventory_key: &InventoryKey,
        quantity: i64,
        only_batch_key: Option<&str>,
    ) -> Result<Vec<BatchPiece>> {
        if quantity <= 0 {
            return Ok(Vec::new());
        }
        let mut candidates = self
            .keys_by_inventory
            .get(inventory_key)
            .cloned()
            .unwrap_or_default()
            .into_iter()
            .filter(|key| only_batch_key.is_none_or(|only| key == only))
            .filter(|key| {
                self.by_key
                    .get(key)
                    .is_some_and(|batch| batch.quantity_remaining_at_extract > 0)
            })
            .collect::<Vec<_>>();
        candidates.sort_by(|left, right| {
            let left = &self.by_key[left];
            let right = &self.by_key[right];
            (
                left.expiry_date.is_none(),
                left.expiry_date.unwrap_or(NaiveDate::MAX),
                left.receipt_date,
                &left.batch_key,
            )
                .cmp(&(
                    right.expiry_date.is_none(),
                    right.expiry_date.unwrap_or(NaiveDate::MAX),
                    right.receipt_date,
                    &right.batch_key,
                ))
        });
        let mut remaining = quantity;
        let mut consumed = Vec::new();
        for batch_key in candidates {
            let batch = self.by_key.get_mut(&batch_key).expect("candidate batch");
            let take = remaining.min(batch.quantity_remaining_at_extract);
            batch.quantity_remaining_at_extract -= take;
            consumed.push(BatchPiece {
                batch: batch.clone(),
                quantity: take,
            });
            remaining -= take;
            if remaining == 0 {
                break;
            }
        }
        ensure!(
            remaining == 0,
            "batch balance underflow for {}/{}: requested {quantity}, missing {remaining}",
            inventory_key.warehouse_id,
            inventory_key.sku
        );
        self.finalize_exhausted(inventory_key);
        Ok(consumed)
    }

    fn finalize_exhausted(&mut self, inventory_key: &InventoryKey) {
        let keys = self
            .keys_by_inventory
            .get(inventory_key)
            .cloned()
            .unwrap_or_default();
        let exhausted = keys
            .iter()
            .filter(|key| {
                self.by_key
                    .get(*key)
                    .is_some_and(|batch| batch.quantity_remaining_at_extract <= 0)
            })
            .cloned()
            .collect::<Vec<_>>();
        if exhausted.is_empty() {
            return;
        }
        self.keys_by_inventory
            .entry(inventory_key.clone())
            .and_modify(|keys| keys.retain(|key| !exhausted.iter().any(|row| row == key)));
        for key in exhausted {
            if let Some(batch) = self.by_key.remove(&key) {
                self.finalized.push(batch);
            }
        }
    }

    #[must_use]
    pub fn expiry_keys(&mut self, day: NaiveDate) -> Vec<String> {
        let mut keys = self.expiry_by_date.remove(&day).unwrap_or_default();
        keys.sort();
        keys
    }

    pub fn reschedule_expiry(&mut self, day: NaiveDate, batch_key: String) {
        self.expiry_by_date.entry(day).or_default().push(batch_key);
    }

    #[must_use]
    pub fn batch(&self, batch_key: &str) -> Option<&Batch> {
        self.by_key.get(batch_key)
    }

    #[must_use]
    pub fn active_batches(&self) -> impl Iterator<Item = &Batch> {
        self.by_key.values()
    }

    #[must_use]
    pub fn finalized_batches(&self) -> &[Batch] {
        &self.finalized
    }

    #[must_use]
    pub fn balance(&self, inventory_key: &InventoryKey) -> i64 {
        self.keys_by_inventory
            .get(inventory_key)
            .into_iter()
            .flatten()
            .filter_map(|key| self.by_key.get(key))
            .map(|batch| batch.quantity_remaining_at_extract)
            .sum()
    }
}

pub struct InventoryState {
    pub on_hand: BTreeMap<InventoryKey, i64>,
    pub committed: BTreeMap<InventoryKey, i64>,
    pub damaged: BTreeMap<InventoryKey, i64>,
    pub quality_control: BTreeMap<InventoryKey, i64>,
    pub opening_on_hand: BTreeMap<InventoryKey, i64>,
    pub opening_daily_rate: BTreeMap<InventoryKey, Decimal>,
    pub batches: BatchBook,
}

impl InventoryState {
    pub fn opening(
        config: &LoadedConfig,
        catalog: &[Product],
        assortment: &StoreAssortment,
    ) -> Result<Self> {
        let start = config.scenario.time.start_date;
        let master_seed = config.scenario.identity.master_seed.to_string();
        let inventory_policy = &config.scenario.operations.inventory;
        let stockout_rate = inventory_policy["stockoutSkuRate"]
            .as_f64()
            .context("inventory.stockoutSkuRate")?;
        let annual_weights = annual_portfolio_weights(config, catalog, assortment);
        let mut opening_daily_rate = BTreeMap::<InventoryKey, Decimal>::new();

        for store in &config.scenario.stores {
            let selected = &assortment.selected_by_store[&store.store_id];
            let active = selected
                .iter()
                .copied()
                .filter(|position| active_on(selected_variant(catalog, *position).1, start))
                .collect::<Vec<_>>();
            let cover_warehouses = store
                .warehouse_priority
                .iter()
                .filter(|warehouse_id| {
                    config
                        .scenario
                        .warehouses
                        .iter()
                        .find(|warehouse| warehouse.warehouse_id.as_str() == warehouse_id.as_str())
                        .is_some_and(|warehouse| warehouse.opening_stock_days_of_cover > 0)
                })
                .collect::<Vec<_>>();
            if active.is_empty() || cover_warehouses.is_empty() {
                continue;
            }
            let market = config
                .scenario
                .markets
                .iter()
                .find(|market| market.market_id == store.market_id)
                .context("store market")?;
            let portfolio = annual_weights[&(store.store_id.clone(), start.year())].clone();
            for position in active {
                let (product, variant) = selected_variant(catalog, position);
                let planned_rate = Decimal::from_f64_text(market.demand.demand_level_scalar)
                    * Decimal::from_f64_text(store.demand_scale)
                    * Decimal::from_f64_text(market.demand.starting_daily_orders)
                    * Decimal::from_f64_text(market.demand.average_lines_per_order)
                    * portfolio_weight(product, variant)
                    / &portfolio
                    * expected_units_per_line(product);
                let share = planned_rate / Decimal::from(cover_warehouses.len());
                for warehouse_id in &cover_warehouses {
                    let key = InventoryKey::new((*warehouse_id).clone(), &variant.sku);
                    let prior = opening_daily_rate
                        .get(&key)
                        .cloned()
                        .unwrap_or_else(Decimal::zero);
                    opening_daily_rate.insert(key, prior + &share);
                }
            }
        }

        let mut on_hand = BTreeMap::new();
        let mut batches = BatchBook::default();
        for warehouse in &config.scenario.warehouses {
            for product in catalog
                .iter()
                .filter(|product| product.market_id == warehouse.market_id)
            {
                for variant in &product.variants {
                    let key = InventoryKey::new(&warehouse.warehouse_id, &variant.sku);
                    let constrained = fraction(&[
                        &master_seed,
                        "constrained-sku",
                        &warehouse.warehouse_id,
                        &variant.sku,
                    ]) < stockout_rate;
                    let mut opening = 0_i64;
                    if active_on(variant, start) && !constrained {
                        let cover_days = Decimal::from(warehouse.opening_stock_days_of_cover);
                        let planned = (opening_daily_rate
                            .get(&key)
                            .cloned()
                            .unwrap_or_else(Decimal::zero)
                            * cover_days)
                            .ceil_i64()
                            .context("planned opening stock")?;
                        let floor = i64::try_from(warehouse.opening_stock_per_sku)?;
                        let jitter = i64::try_from(stable_integer(
                            &[
                                &master_seed,
                                "opening-stock",
                                &warehouse.warehouse_id,
                                &variant.sku,
                            ],
                            u64::from(warehouse.replenishment_pack_size.max(1)),
                        ))?;
                        opening = floor.max(planned) + jitter;
                    }
                    on_hand.insert(key.clone(), opening);
                    if opening > 0 {
                        batches.add(
                            format!("opening:{}:{}", warehouse.warehouse_id, variant.sku),
                            "opening-balance",
                            String::new(),
                            &warehouse.warehouse_id,
                            product,
                            variant,
                            start,
                            opening,
                            None,
                            None,
                            None,
                        );
                    }
                }
            }
        }
        Ok(Self {
            opening_on_hand: on_hand.clone(),
            on_hand,
            committed: BTreeMap::new(),
            damaged: BTreeMap::new(),
            quality_control: BTreeMap::new(),
            opening_daily_rate,
            batches,
        })
    }

    #[must_use]
    pub fn value(values: &BTreeMap<InventoryKey, i64>, key: &InventoryKey) -> i64 {
        values.get(key).copied().unwrap_or(0)
    }

    #[must_use]
    pub fn free_inventory(&self, key: &InventoryKey) -> i64 {
        (Self::value(&self.on_hand, key)
            - Self::value(&self.committed, key)
            - Self::value(&self.damaged, key)
            - Self::value(&self.quality_control, key))
        .max(0)
    }

    pub fn allocate(
        &mut self,
        config: &LoadedConfig,
        store: &Store,
        sku: &str,
        requested: i64,
        event_key: &str,
    ) -> Vec<Allocation> {
        if requested <= 0 {
            return Vec::new();
        }
        let safety_stock = config.scenario.operations.inventory["safetyStockUnits"]
            .as_i64()
            .unwrap_or(0);
        let split_rate = config.scenario.operations.fulfillment["splitRate"]
            .as_f64()
            .unwrap_or(0.0);
        let master_seed = config.scenario.identity.master_seed.to_string();
        let split = requested >= 2
            && store.warehouse_priority.len() >= 2
            && fraction(&[&master_seed, "split-fulfillment", event_key]) < split_rate;
        let mut allocations = Vec::new();
        let mut remaining = requested;
        for (index, warehouse_id) in store.warehouse_priority.iter().enumerate() {
            let key = InventoryKey::new(warehouse_id, sku);
            let usable = (Self::value(&self.on_hand, &key)
                - Self::value(&self.committed, &key)
                - Self::value(&self.damaged, &key)
                - Self::value(&self.quality_control, &key)
                - safety_stock)
                .max(0);
            if usable <= 0 {
                continue;
            }
            let desired = if split && index == 0 {
                (requested / 2).max(1)
            } else {
                remaining
            };
            let quantity = usable.min(desired);
            if quantity > 0 {
                *self.committed.entry(key).or_default() += quantity;
                allocations.push(Allocation {
                    warehouse_id: warehouse_id.clone(),
                    quantity,
                    priority: index + 1,
                });
                remaining -= quantity;
            }
            if remaining <= 0 {
                break;
            }
        }
        allocations
    }

    pub fn reconcile(&self) -> Result<()> {
        for (key, on_hand) in &self.on_hand {
            ensure!(
                self.batches.balance(key) == *on_hand,
                "batch/on-hand reconciliation failed for {}/{}: {} != {}",
                key.warehouse_id,
                key.sku,
                self.batches.balance(key),
                on_hand
            );
        }
        Ok(())
    }
}

pub fn annual_portfolio_weights(
    config: &LoadedConfig,
    catalog: &[Product],
    assortment: &StoreAssortment,
) -> BTreeMap<(String, i32), Decimal> {
    let mut weights = BTreeMap::new();
    for store in &config.scenario.stores {
        for year in config.scenario.time.start_date.year()..=config.scenario.time.end_date.year() {
            let period_start = config
                .scenario
                .time
                .start_date
                .max(NaiveDate::from_ymd_opt(year, 1, 1).expect("year start"));
            let period_end = config
                .scenario
                .time
                .end_date
                .min(NaiveDate::from_ymd_opt(year, 12, 31).expect("year end"));
            let variants = assortment.selected_by_store[&store.store_id]
                .iter()
                .map(|position| selected_variant(catalog, *position));
            weights.insert(
                (store.store_id.clone(), year),
                average_active_portfolio_weight(variants, period_start, period_end),
            );
        }
    }
    weights
}

#[must_use]
pub fn selected_variant(catalog: &[Product], position: SelectedVariant) -> (&Product, &Variant) {
    let product = &catalog[position.product_index];
    (product, &product.variants[position.variant_index])
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

#[cfg(test)]
mod tests {
    use super::InventoryState;
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::deterministic::sha256_hex;
    use crate::simulation::assortment;

    #[test]
    fn gulf_mini_opening_inventory_matches_python_batches() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let assortment = assortment::build(&config, &catalog).expect("assortment");
        let inventory = InventoryState::opening(&config, &catalog, &assortment).expect("opening");
        let mut rows = inventory
            .batches
            .active_batches()
            .filter(|batch| batch.source_type == "opening-balance")
            .map(|batch| {
                vec![
                    batch.warehouse_id.clone(),
                    batch.sku.clone(),
                    batch.manufacture_date.to_string(),
                    batch.receipt_date.to_string(),
                    batch
                        .expiry_date
                        .map_or_else(String::new, |date| date.to_string()),
                    batch.quantity_received.to_string(),
                ]
            })
            .collect::<Vec<_>>();
        rows.sort();
        assert_eq!(rows.len(), 1_697);
        assert_eq!(
            rows.iter()
                .map(|row| row[5].parse::<i64>().unwrap())
                .sum::<i64>(),
            172_792
        );
        assert_eq!(
            sha256_hex(serde_json::to_string(&rows).unwrap().as_bytes()),
            "1aa3fe2a48711c3049291480341d3507a1602d670fc1c4f6da0029d633889838"
        );
        inventory.reconcile().expect("batch reconciliation");
    }
}
