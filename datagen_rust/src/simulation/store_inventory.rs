use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Context, Result};
use chrono::{Duration, NaiveDate};
use rust_decimal::prelude::ToPrimitive;
use rust_decimal::{Decimal, RoundingStrategy};

use crate::catalog::{Product, Variant};
use crate::config::{LoadedConfig, Market, Store};
use crate::deterministic::stable_integer;
use crate::projection::catalog::local_iso_at;
use crate::simulation::decimal::PyDecimal;
use crate::simulation::model::FieldValues;

#[derive(Debug, Clone)]
pub struct StoreVariant {
    pub sku: String,
    pub launch_date: NaiveDate,
    pub discontinue_date: Option<NaiveDate>,
    pub shelf_life_days: Option<i64>,
    pub base_cost: Decimal,
}

impl StoreVariant {
    #[must_use]
    pub fn from_catalog(product: &Product, variant: &Variant) -> Self {
        Self {
            sku: variant.sku.clone(),
            launch_date: variant.launch_date,
            discontinue_date: variant.discontinue_date,
            shelf_life_days: product.shelf_life_days,
            base_cost: variant.base_cost,
        }
    }
}

#[derive(Debug, Clone, Default)]
struct Cell {
    on_hand: i64,
    committed: i64,
    damaged: i64,
    in_transit: i64,
    oldest_receipt_day: Option<NaiveDate>,
    residual_since: Option<NaiveDate>,
}

impl Cell {
    fn residual_state(&self) -> i64 {
        self.on_hand + self.committed + self.damaged + self.in_transit
    }
}

#[derive(Debug, Clone)]
struct Arrival {
    transfer_key: String,
    market_key: String,
    sku: String,
    from_location_key: String,
    to_location_key: String,
    store_key: String,
    quantity: i64,
    order_date: NaiveDate,
    expected_receipt_date: NaiveDate,
    unit_cost_minor: i64,
    currency_code: String,
    observed_at: String,
}

impl Arrival {
    fn row(&self, status: &str, effective_at: String, observed_at: String) -> FieldValues {
        values([
            ("transferKey", self.transfer_key.clone()),
            ("marketKey", self.market_key.clone()),
            ("sku", self.sku.clone()),
            ("fromLocationKey", self.from_location_key.clone()),
            ("toLocationKey", self.to_location_key.clone()),
            ("storeKey", self.store_key.clone()),
            ("quantity", self.quantity.to_string()),
            ("orderDate", self.order_date.to_string()),
            (
                "expectedReceiptDate",
                self.expected_receipt_date.to_string(),
            ),
            ("unitCostMinor", self.unit_cost_minor.to_string()),
            ("currencyCode", self.currency_code.clone()),
            ("observedAt", observed_at),
            ("status", status.to_owned()),
            ("statusEffectiveAt", effective_at),
        ])
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CoverageSummary {
    pub cells: usize,
    pub active_cells_at_end: usize,
    pub residual_cells_at_end: usize,
    pub stores_with_stock: usize,
}

/// Exact Rust port of Python's v13 store-grain inventory state machine.
pub struct StoreEchelon<'a> {
    config: &'a LoadedConfig,
    variants_by_store: BTreeMap<String, Vec<StoreVariant>>,
    start: NaiveDate,
    end: NaiveDate,
    master_seed: String,
    enabled: bool,
    snapshot_cadence: i64,
    review_cycle: i64,
    target_cover_days: i64,
    safety_stock: i64,
    pack_size: i64,
    opening_cover_days: i64,
    residual_workoff_weeks: i64,
    primary_transit: i64,
    spill_transit: i64,
    cells: BTreeMap<(String, String), Cell>,
    arrivals: BTreeMap<NaiveDate, Vec<Arrival>>,
    observed_demand: BTreeMap<(String, String), BTreeMap<NaiveDate, i64>>,
    assortment_window: BTreeMap<(String, String), (NaiveDate, Option<NaiveDate>)>,
    shelf_life: BTreeMap<String, i64>,
}

impl<'a> StoreEchelon<'a> {
    #[must_use]
    pub fn new(
        config: &'a LoadedConfig,
        variants_by_store: BTreeMap<String, Vec<StoreVariant>>,
    ) -> Self {
        let policy = &config.scenario.operations.store_inventory;
        let mut assortment_window = BTreeMap::new();
        let mut shelf_life = BTreeMap::new();
        for (store_id, variants) in &variants_by_store {
            for variant in variants {
                assortment_window.insert(
                    (store_id.clone(), variant.sku.clone()),
                    (variant.launch_date, variant.discontinue_date),
                );
                if let Some(days) = variant.shelf_life_days {
                    shelf_life.insert(variant.sku.clone(), days);
                }
            }
        }
        Self {
            config,
            variants_by_store,
            start: config.scenario.time.start_date,
            end: config.scenario.time.end_date,
            master_seed: config.scenario.identity.master_seed.to_string(),
            enabled: config
                .scenario
                .operations
                .features
                .get("storeInventory")
                .copied()
                .unwrap_or(false),
            snapshot_cadence: integer(policy, "snapshotCadenceDays", 7),
            review_cycle: integer(policy, "reviewCycleDays", 7),
            target_cover_days: integer(policy, "targetDaysOfCover", 14),
            safety_stock: integer(policy, "safetyStockUnits", 3),
            pack_size: integer(policy, "replenishmentPackSize", 6).max(1),
            opening_cover_days: integer(policy, "openingDaysOfCover", 10),
            residual_workoff_weeks: integer(policy, "residualWorkoffWeeks", 26),
            primary_transit: integer(policy, "primaryLaneTransitDays", 1),
            spill_transit: integer(policy, "spillLaneTransitDays", 2),
            cells: BTreeMap::new(),
            arrivals: BTreeMap::new(),
            observed_demand: BTreeMap::new(),
            assortment_window,
            shelf_life,
        }
    }

    pub fn lane_rows(&self) -> Result<Vec<FieldValues>> {
        let mut rows = Vec::new();
        for store in &self.config.scenario.stores {
            let market = self.market(&store.market_id)?;
            for (index, warehouse_id) in store.warehouse_priority.iter().enumerate() {
                let rank = index + 1;
                let base = if rank == 1 {
                    self.primary_transit
                } else {
                    self.spill_transit
                };
                let transit = base
                    + i64::try_from(stable_integer(
                        &["lane-transit", &store.store_id, warehouse_id],
                        4,
                    ))?;
                rows.push(values([
                    (
                        "laneKey",
                        format!("{}:{warehouse_id}:replenishment", store.store_id),
                    ),
                    ("marketKey", store.market_id.clone()),
                    ("laneType", "replenishment".to_owned()),
                    ("demandLocationKey", store.store_id.clone()),
                    ("channelKey", String::new()),
                    ("supplyLocationKey", warehouse_id.clone()),
                    ("priorityRank", rank.to_string()),
                    ("transitDays", transit.to_string()),
                    ("effectiveFrom", self.start.to_string()),
                    ("effectiveTo", String::new()),
                    (
                        "observedAt",
                        local_iso_at(self.start, 23, &market.timezone)?,
                    ),
                ]));
            }
        }
        rows.sort_by(|left, right| left["laneKey"].cmp(&right["laneKey"]));
        Ok(rows)
    }

    pub fn seed_opening(
        &mut self,
        opening_daily_rate: &BTreeMap<(String, String), PyDecimal>,
    ) -> Result<()> {
        if !self.enabled {
            return Ok(());
        }
        let stores = self.config.scenario.stores.clone();
        for store in &stores {
            let (warehouse_id, _) = self.lane_for(store)?;
            let variants = self
                .variants_by_store
                .get(&store.store_id)
                .cloned()
                .unwrap_or_default();
            for variant in variants {
                if !self.is_active(&store.store_id, &variant.sku, self.start) {
                    continue;
                }
                let daily = opening_daily_rate
                    .get(&(warehouse_id.clone(), variant.sku.clone()))
                    .cloned()
                    .unwrap_or_else(PyDecimal::zero);
                let planned = (PyDecimal::from(self.opening_cover_days) * daily)
                    .trunc_i64()
                    .context("store opening stock")?;
                let jitter = i64::try_from(stable_integer(
                    &[
                        &self.master_seed,
                        "store-opening-stock",
                        &store.store_id,
                        &variant.sku,
                    ],
                    u64::try_from(self.pack_size)?,
                ))?;
                let opening = (planned + jitter).max(0);
                if opening == 0 {
                    continue;
                }
                let start = self.start;
                let cell = self.cell_mut(&store.store_id, &variant.sku);
                cell.on_hand = opening;
                cell.oldest_receipt_day = Some(start);
            }
        }
        Ok(())
    }

    pub fn receive(&mut self, day: NaiveDate) -> Result<Vec<FieldValues>> {
        if !self.enabled {
            return Ok(Vec::new());
        }
        let arrivals = self.arrivals.remove(&day).unwrap_or_default();
        let mut rows = Vec::with_capacity(arrivals.len());
        for arrival in arrivals {
            let cell = self.cell_mut(&arrival.store_key, &arrival.sku);
            cell.in_transit = (cell.in_transit - arrival.quantity).max(0);
            cell.on_hand += arrival.quantity;
            cell.oldest_receipt_day.get_or_insert(day);
            let timestamp = local_iso_at(day, 23, &self.market(&arrival.market_key)?.timezone)?;
            rows.push(arrival.row("received", timestamp.clone(), timestamp));
        }
        Ok(rows)
    }

    pub fn sell(&mut self, day: NaiveDate, store_id: &str, sku: &str, units: i64) -> (i64, i64) {
        if !self.enabled || units <= 0 {
            return (0, 0);
        }
        *self
            .observed_demand
            .entry((store_id.to_owned(), sku.to_owned()))
            .or_default()
            .entry(day)
            .or_default() += units;
        let cell = self.cell_mut(store_id, sku);
        let available = (cell.on_hand - cell.damaged).max(0);
        let served = available.min(units);
        cell.on_hand -= served;
        if cell.on_hand == 0 {
            cell.oldest_receipt_day = None;
        }
        (served, units - served)
    }

    pub fn expire(&mut self, day: NaiveDate) -> Result<Vec<FieldValues>> {
        if !self.enabled {
            return Ok(Vec::new());
        }
        let keys = self.cells.keys().cloned().collect::<Vec<_>>();
        let mut rows = Vec::new();
        for (store_id, sku) in keys {
            let Some(shelf_life) = self.shelf_life.get(&sku).copied() else {
                continue;
            };
            let cell = self
                .cells
                .get_mut(&(store_id.clone(), sku.clone()))
                .expect("cell key");
            let Some(oldest) = cell.oldest_receipt_day else {
                continue;
            };
            if cell.on_hand <= 0 || (day - oldest).num_days() < shelf_life {
                continue;
            }
            let wasted = (cell.on_hand / 4).max(1).min(cell.on_hand);
            cell.on_hand -= wasted;
            cell.oldest_receipt_day = (cell.on_hand > 0).then_some(day);
            let store = self.store(&store_id)?;
            let market = self.market(&store.market_id)?;
            rows.push(values([
                ("eventKey", format!("store-waste:{store_id}:{sku}:{}", day)),
                ("marketKey", store.market_id.clone()),
                ("storeKey", store_id),
                ("sku", sku),
                ("eventDate", day.to_string()),
                ("units", wasted.to_string()),
                ("reasonCode", "expiry".to_owned()),
                ("observedAt", local_iso_at(day, 23, &market.timezone)?),
            ]));
        }
        Ok(rows)
    }

    pub fn review(&mut self, day: NaiveDate) -> Result<Vec<FieldValues>> {
        if !self.enabled || (day - self.start).num_days() % self.review_cycle != 0 {
            return Ok(Vec::new());
        }
        let window_start = day - Duration::days(self.review_cycle * 2);
        let mut stores = self.config.scenario.stores.clone();
        stores.sort_by(|left, right| left.store_id.cmp(&right.store_id));
        let mut rows = Vec::new();
        for store in stores {
            let (warehouse_id, transit) = self.lane_for(&store)?;
            let market = self.market(&store.market_id)?.clone();
            let store_id = store.store_id.clone();
            let pack_size = self.pack_size;
            let variants = self
                .variants_by_store
                .get(&store_id)
                .cloned()
                .unwrap_or_default();
            for variant in variants {
                if !self.is_active(&store_id, &variant.sku, day) {
                    continue;
                }
                let trailing = self
                    .observed_demand
                    .get(&(store_id.clone(), variant.sku.clone()))
                    .map_or(0, |observed| {
                        observed
                            .range(window_start..=day)
                            .map(|(_, units)| *units)
                            .sum()
                    });
                if trailing <= 0 {
                    continue;
                }
                let span_days = (day - self.start).num_days() + 1;
                let span_days = span_days.min(self.review_cycle * 2).max(1);
                let daily_rate = PyDecimal::from(trailing) / PyDecimal::from(span_days);
                let target = (daily_rate * PyDecimal::from(self.target_cover_days))
                    .trunc_i64()
                    .context("store replenishment target")?
                    + self.safety_stock;
                let position = {
                    let cell = self.cell_mut(&store_id, &variant.sku);
                    cell.on_hand + cell.in_transit - cell.damaged
                };
                if position >= target {
                    continue;
                }
                let shortfall = target - position;
                let quantity = ((shortfall + pack_size - 1) / pack_size) * pack_size;
                if quantity <= 0 {
                    continue;
                }
                self.cell_mut(&store_id, &variant.sku).in_transit += quantity;
                let receipt_day = day + Duration::days(transit);
                let timestamp = local_iso_at(day, 23, &market.timezone)?;
                let arrival = Arrival {
                    transfer_key: format!("{warehouse_id}:{}:{}:{}", store_id, variant.sku, day),
                    market_key: store.market_id.clone(),
                    sku: variant.sku,
                    from_location_key: warehouse_id.clone(),
                    to_location_key: store_id.clone(),
                    store_key: store_id.clone(),
                    quantity,
                    order_date: day,
                    expected_receipt_date: receipt_day,
                    unit_cost_minor: minor_units(variant.base_cost, &market.currency_code)?,
                    currency_code: market.currency_code.clone(),
                    observed_at: timestamp.clone(),
                };
                if receipt_day <= self.end {
                    self.arrivals
                        .entry(receipt_day)
                        .or_default()
                        .push(arrival.clone());
                }
                rows.push(arrival.row(
                    "dispatched",
                    timestamp.clone(),
                    arrival.observed_at.clone(),
                ));
            }
        }
        Ok(rows)
    }

    pub fn snapshot(&mut self, day: NaiveDate) -> Result<Vec<FieldValues>> {
        if !self.enabled
            || ((day - self.start).num_days() % self.snapshot_cadence != 0 && day != self.end)
        {
            return Ok(Vec::new());
        }
        let cutoff = Duration::weeks(self.residual_workoff_weeks);
        let keys = self.cells.keys().cloned().collect::<Vec<_>>();
        let mut rows = Vec::new();
        for (store_id, sku) in keys {
            let active = self.is_active(&store_id, &sku, day);
            let store = self.store(&store_id)?;
            let market_id = store.market_id.clone();
            let location_code = store.business_central_location_code.clone();
            let timezone = self.market(&market_id)?.timezone.clone();
            let cell = self
                .cells
                .get_mut(&(store_id.clone(), sku.clone()))
                .expect("cell key");
            if !active && cell.residual_state() == 0 {
                continue;
            }
            if active {
                cell.residual_since = None;
            } else if let Some(since) = cell.residual_since {
                let _held_past_workoff = day - since > cutoff;
            } else {
                cell.residual_since = Some(day);
            }
            let available = (cell.on_hand - cell.committed - cell.damaged).max(0);
            rows.push(values([
                ("marketKey", market_id),
                ("storeKey", store_id),
                ("locationCode", location_code),
                ("sku", sku),
                ("snapshotDate", day.to_string()),
                ("observedAt", local_iso_at(day, 23, &timezone)?),
                ("onHand", cell.on_hand.to_string()),
                ("available", available.to_string()),
                ("committed", cell.committed.to_string()),
                ("damaged", cell.damaged.to_string()),
                ("inTransit", cell.in_transit.to_string()),
                ("assortmentActive", active.to_string()),
                ("residualOnly", (!active).to_string()),
                (
                    "oldestReceiptDate",
                    cell.oldest_receipt_day
                        .map_or_else(String::new, |value| value.to_string()),
                ),
            ]));
        }
        Ok(rows)
    }

    #[must_use]
    pub fn coverage_summary(&self) -> CoverageSummary {
        let active_cells_at_end = self
            .cells
            .keys()
            .filter(|(store_id, sku)| self.is_active(store_id, sku, self.end))
            .count();
        let residual_cells_at_end = self
            .cells
            .iter()
            .filter(|((store_id, sku), cell)| {
                !self.is_active(store_id, sku, self.end) && cell.residual_state() > 0
            })
            .count();
        let stores_with_stock = self
            .cells
            .iter()
            .filter(|(_, cell)| cell.on_hand != 0)
            .map(|((store_id, _), _)| store_id)
            .collect::<BTreeSet<_>>()
            .len();
        CoverageSummary {
            cells: self.cells.len(),
            active_cells_at_end,
            residual_cells_at_end,
            stores_with_stock,
        }
    }

    #[must_use]
    pub fn is_active(&self, store_id: &str, sku: &str, day: NaiveDate) -> bool {
        self.assortment_window
            .get(&(store_id.to_owned(), sku.to_owned()))
            .is_some_and(|(launch, discontinue)| {
                day >= *launch && discontinue.is_none_or(|end| day <= end)
            })
    }

    fn cell_mut(&mut self, store_id: &str, sku: &str) -> &mut Cell {
        self.cells
            .entry((store_id.to_owned(), sku.to_owned()))
            .or_default()
    }

    fn lane_for(&self, store: &Store) -> Result<(String, i64)> {
        let warehouse_id = store
            .warehouse_priority
            .first()
            .with_context(|| format!("store {} has no warehousePriority", store.store_id))?;
        Ok((warehouse_id.clone(), self.primary_transit))
    }

    fn store(&self, store_id: &str) -> Result<&Store> {
        self.config
            .scenario
            .stores
            .iter()
            .find(|row| row.store_id == store_id)
            .with_context(|| format!("unknown store {store_id}"))
    }

    fn market(&self, market_id: &str) -> Result<&Market> {
        self.config
            .scenario
            .markets
            .iter()
            .find(|row| row.market_id == market_id)
            .with_context(|| format!("unknown market {market_id}"))
    }
}

fn integer(value: &serde_json::Value, key: &str, default: i64) -> i64 {
    value[key].as_i64().unwrap_or(default)
}

fn minor_units(amount: Decimal, currency: &str) -> Result<i64> {
    let exponent = match currency {
        "INR" | "USD" => 2_u32,
        _ => anyhow::bail!(
            "no minor-unit exponent declared for {currency:?}; extend the exact currency table"
        ),
    };
    let factor = Decimal::from(10_u64.pow(exponent));
    (amount * factor)
        .round_dp_with_strategy(0, RoundingStrategy::MidpointNearestEven)
        .to_i64()
        .context("minor-unit amount out of i64 range")
}

fn values<const N: usize>(entries: [(&'static str, String); N]) -> FieldValues {
    entries.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use chrono::{Duration, NaiveDate};
    use rust_decimal::Decimal;

    use super::{StoreEchelon, StoreVariant};
    use crate::config::LoadedConfig;
    use crate::contracts;
    use crate::deterministic::sha256_hex;

    #[test]
    fn gulf_service_lanes_match_python_oracle() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let echelon = StoreEchelon::new(&config, BTreeMap::new());
        let rows = echelon.lane_rows().expect("lanes");
        let fields = contracts::fields("companion", "serviceLanes").expect("fields");
        let normalized = rows
            .iter()
            .map(|row| {
                fields
                    .iter()
                    .map(|field| {
                        row.get(field.as_str())
                            .filter(|value| !value.is_empty())
                            .cloned()
                    })
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        assert_eq!(rows.len(), 26);
        assert_eq!(
            sha256_hex(serde_json::to_string(&normalized).unwrap().as_bytes()),
            "7fc480811aac6d826c329a9fe2baabd3e84f97db88b54a08351f7caefc81974f"
        );
    }

    #[test]
    fn historical_review_threshold_matches_python_decimal() {
        let config = LoadedConfig::load("configs/gulf-oil-india-ten-year.yaml").expect("config");
        let sku = "GLF-IND-GEAR-EP-VG150-20L";
        let store_id = "guwahati-dist";
        let mut variants = BTreeMap::new();
        variants.insert(
            store_id.to_owned(),
            vec![StoreVariant {
                sku: sku.to_owned(),
                launch_date: config.scenario.time.start_date,
                discontinue_date: None,
                shelf_life_days: None,
                base_cost: Decimal::ZERO,
            }],
        );
        let mut echelon = StoreEchelon::new(&config, variants);
        echelon.cell_mut(store_id, sku).on_hand = 11;
        let review_day = NaiveDate::from_ymd_opt(2016, 10, 13).unwrap();
        echelon
            .observed_demand
            .entry((store_id.to_owned(), sku.to_owned()))
            .or_default()
            .insert(review_day - Duration::days(20), 8);

        let rows = echelon.review(review_day).expect("review");
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0]["quantity"], "12");
        assert_eq!(
            rows[0]["transferKey"],
            "kolkata-depot:guwahati-dist:GLF-IND-GEAR-EP-VG150-20L:2016-10-13"
        );
    }
}
