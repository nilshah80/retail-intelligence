use std::collections::{BTreeMap, HashMap};
use std::str::FromStr;

use anyhow::{Context, Result};
use bigdecimal::RoundingMode;
use chrono::{Datelike, Duration, NaiveDate};
use rayon::prelude::*;
use rust_decimal::Decimal as MoneyDecimal;
use serde_json::Value;

use crate::catalog::{Product, Variant, active_on};
use crate::config::{LoadedConfig, Market, Store};
use crate::deterministic::{PythonRandom, shopify_gid, stable_integer};
use crate::simulation::assortment::{self, SelectedVariant, StoreAssortment};
use crate::simulation::calendar::{Holiday, holidays_for_range};
use crate::simulation::causal_effects::{ExternalEffect, event_effect, pandemic_effect};
use crate::simulation::causal_lifecycle;
use crate::simulation::customers::{CustomerPopulation, CustomerRecord};
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::demand::{
    Allocation, SeasonalityEngine, active_sale_seasons, average_active_portfolio_weight,
    channel_distribution_precomputed, channel_layout, channel_sku_offset, configured_online_share,
    expected_units_per_line, holiday_demand_factor, portfolio_weight, purchase_quantities,
    split_allocations, tax_amounts, tax_rate_for_line,
};
use crate::simulation::inventory::{InventoryKey, InventoryState, selected_variant};
use crate::simulation::model::FieldValues;
use crate::simulation::operations::{fulfillment_timestamps, local_iso_at};
use crate::simulation::pricing::PriceEngine;
use crate::simulation::signals::temperature;
use crate::simulation::store_inventory::{CoverageSummary, StoreEchelon};
use crate::simulation::supply::{SupplyEmissions, SupplyState};

#[derive(Debug, Clone)]
pub struct LineAllocation {
    pub warehouse_id: String,
    pub quantity: i64,
    pub priority: usize,
    pub fulfillment_created_at: String,
    pub fulfillment_delivered_at: String,
}

impl From<Allocation> for LineAllocation {
    fn from(value: Allocation) -> Self {
        Self {
            warehouse_id: value.warehouse_id,
            quantity: value.quantity,
            priority: value.priority,
            fulfillment_created_at: String::new(),
            fulfillment_delivered_at: String::new(),
        }
    }
}

#[derive(Debug, Clone)]
pub struct LineEvent {
    pub event_key: String,
    pub order_key: String,
    pub line_key: String,
    pub line_number: usize,
    pub source_order_sequence: u64,
    pub market_id: String,
    pub store_id: String,
    pub day: NaiveDate,
    pub created_at: String,
    pub product_index: usize,
    pub variant_index: usize,
    pub sku: String,
    pub variant_id: String,
    pub inventory_item_id: String,
    pub department_id: String,
    pub category_id: String,
    pub product_code: String,
    pub product_title: String,
    pub brand: String,
    pub variant_code: String,
    pub variant_title: String,
    pub barcode: String,
    pub quantity: i64,
    pub original_unit_price: Decimal,
    pub unit_price: Decimal,
    pub promotion_ids: Vec<String>,
    pub net: Decimal,
    pub tax: Decimal,
    pub gross: Decimal,
    pub tax_rate: Decimal,
    pub currency_code: String,
    pub taxes_included: bool,
    pub allocations: Vec<LineAllocation>,
    pub customer_segment_id: String,
    pub channel_id: String,
    pub return_probability: MoneyDecimal,
}

#[derive(Debug, Clone)]
pub struct OrderHeader {
    pub order_key: String,
    pub market_id: String,
    pub store_id: String,
    pub day: NaiveDate,
    pub created_at: String,
    pub currency_code: String,
    pub taxes_included: bool,
    pub net: Decimal,
    pub tax: Decimal,
    pub gross: Decimal,
    pub units: i64,
    pub line_count: usize,
    pub customer_segment_id: String,
    pub customer_key: String,
    pub customer_created_date: String,
    pub bc_customer_key: String,
    pub channel_id: String,
    pub source_order_sequence: u64,
    pub source_order_name: String,
}

pub trait CausalSink {
    fn demand_truth(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn allocation_request(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn store_transfer(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn store_observation(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn store_waste(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn store_stockout(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn receipt_event(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn transfer_event(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn inventory_loss_event(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn waste_event(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn inventory_observation(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn supply_pool(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn batch_balance(&mut self, _row: FieldValues) -> Result<()> {
        Ok(())
    }

    fn customer_record(&mut self, _row: CustomerRecord) -> Result<()> {
        Ok(())
    }

    fn day_orders(
        &mut self,
        _day: NaiveDate,
        _orders: Vec<OrderHeader>,
        _lines: Vec<LineEvent>,
    ) -> Result<()> {
        Ok(())
    }
}

#[derive(Default)]
pub struct NullSink;

impl CausalSink for NullSink {}

pub struct CausalFinalState {
    pub inventory: InventoryState,
    pub store_inventory_controls: CoverageSummary,
    pub order_count: u64,
    pub line_count: u64,
    pub unit_count: i64,
    pub net: Decimal,
    pub tax: Decimal,
    pub gross: Decimal,
}

#[derive(Debug, Clone)]
struct RawPromotion {
    promotion_id: String,
    promotion_type: String,
    market_id: String,
    start_date: NaiveDate,
    end_date: NaiveDate,
    store_ids: Vec<String>,
    channel_ids: Vec<String>,
    department_ids: Vec<String>,
    category_ids: Vec<String>,
    customer_segment_ids: Vec<String>,
    discount_pct: Decimal,
    demand_multiplier: Decimal,
}

#[derive(Debug, Clone)]
struct PromotionCandidate {
    promotion_id: String,
    promotion_type: String,
    discount_pct: Decimal,
    demand_multiplier: Decimal,
}

struct PendingDemandRow {
    position: SelectedVariant,
    event_key: String,
    channel_id: String,
    baseline: Decimal,
    expected: Decimal,
    latent_units: i64,
    realized_units: i64,
    lost_units: i64,
    intermittent: bool,
    seasonal_factor: Decimal,
    holiday_factor: Decimal,
    applied_promotions: Vec<String>,
    configured_promotion_lift: Decimal,
    effective_promotion_lift: Decimal,
    effective_promotion_discount: Decimal,
    promotion_elasticity_factor: Decimal,
    promotion_factor: Decimal,
    promotion_payback_factor: Decimal,
    event: ExternalEffect,
    event_factor: Decimal,
    pandemic: ExternalEffect,
    pandemic_factor: Decimal,
    weather_factor: Decimal,
    competitor_factor: Decimal,
    price_factor: Decimal,
    lifecycle: causal_lifecycle::LifecycleEffect,
    segment: RawSegment,
    random_noise: f64,
    total_factor: Decimal,
}

#[derive(Debug, Clone)]
struct Release {
    warehouse_id: String,
    sku: String,
    quantity: i64,
}

pub fn simulate<S: CausalSink>(
    config: &LoadedConfig,
    catalog: &[Product],
    sink: &mut S,
) -> Result<CausalFinalState> {
    let start = config.scenario.time.start_date;
    let end = config.scenario.time.end_date;
    let master_seed = config.scenario.identity.master_seed;
    let master_text = master_seed.to_string();
    let assortment = assortment::build(config, catalog)?;
    let annual_weights = annual_portfolio_weights(config, catalog, &assortment);
    let mut inventory = InventoryState::opening(config, catalog, &assortment)?;
    let store_variants = assortment.store_inventory_variants(catalog);
    let mut store_echelon = StoreEchelon::new(config, store_variants);
    let mut supply = SupplyState::new(config);
    let store_rates = inventory
        .opening_daily_rate
        .iter()
        .map(|(key, rate)| ((key.warehouse_id.clone(), key.sku.clone()), rate.clone()))
        .collect::<BTreeMap<_, _>>();
    store_echelon.seed_opening(&store_rates)?;
    let promotions = raw_promotions(config)?;
    let channel_types = config
        .scenario
        .channels
        .iter()
        .map(|channel| (channel.channel_id.clone(), channel.channel_type.clone()))
        .collect::<HashMap<_, _>>();
    let channel_layouts = config
        .scenario
        .stores
        .iter()
        .map(|store| {
            Ok((
                store.store_id.clone(),
                channel_layout(store, &channel_types)?,
            ))
        })
        .collect::<Result<HashMap<_, _>>>()?;
    let markets_by_id = config
        .scenario
        .markets
        .iter()
        .map(|market| (market.market_id.as_str(), market))
        .collect::<HashMap<_, _>>();
    let channel_sku_offsets = config
        .scenario
        .stores
        .iter()
        .map(|store| {
            let market = markets_by_id
                .get(store.market_id.as_str())
                .context("store market")?;
            let offsets = catalog
                .iter()
                .map(|product| {
                    product
                        .variants
                        .iter()
                        .map(|variant| channel_sku_offset(master_seed, store, variant, market))
                        .collect::<Vec<_>>()
                })
                .collect::<Vec<_>>();
            Ok((store.store_id.clone(), offsets))
        })
        .collect::<Result<HashMap<_, _>>>()?;
    let holidays = holiday_index(config)?;
    let mut customers = CustomerPopulation::new(config);
    let mut price_engine = PriceEngine::new();
    let mut seasonality = SeasonalityEngine::default();
    let mut fulfillment_releases = BTreeMap::<NaiveDate, Vec<Release>>::new();
    let mut source_order_sequence = 0_u64;
    let mut order_count = 0_u64;
    let mut line_count = 0_u64;
    let mut unit_count = 0_i64;
    let mut control_net = Decimal::zero();
    let mut control_tax = Decimal::zero();
    let mut control_gross = Decimal::zero();
    let variant_portfolio_weights = catalog
        .iter()
        .map(|product| {
            product
                .variants
                .iter()
                .map(|variant| portfolio_weight(product, variant))
                .collect::<Vec<_>>()
        })
        .collect::<Vec<_>>();
    let variant_elasticities = catalog
        .iter()
        .map(|product| {
            product
                .variants
                .iter()
                .map(|variant| {
                    variant
                        .elasticity
                        .to_string()
                        .parse::<f64>()
                        .context("elasticity")
                })
                .collect::<Result<Vec<_>>>()
        })
        .collect::<Result<Vec<_>>>()?;
    let product_expected_units = catalog
        .iter()
        .map(expected_units_per_line)
        .collect::<Vec<_>>();
    let product_seasonality_strengths = catalog
        .iter()
        .map(|product| Decimal::from_str(&product.seasonality_strength.to_string()))
        .collect::<std::result::Result<Vec<_>, _>>()?;

    let mut day = start;
    while day <= end {
        let day_text = day.to_string();
        let week_start = day - Duration::days(i64::from(day.weekday().num_days_from_monday()));
        let week_text = week_start.to_string();
        let observation_day = start + Duration::days(((day - start).num_days() / 7) * 7);
        let observation_text = observation_day.to_string();
        for release in fulfillment_releases.remove(&day).unwrap_or_default() {
            release_inventory(&mut inventory, &release)?;
        }
        emit_supply(
            sink,
            supply.begin_day(config, catalog, &mut inventory, day)?,
        )?;
        for row in store_echelon.receive(day)? {
            sink.store_transfer(row)?;
        }
        for row in store_echelon.expire(day)? {
            sink.store_waste(row)?;
        }
        emit_supply(sink, supply.plan_day(config, catalog, &mut inventory, day)?)?;
        supply.capture_availability(config, catalog, &inventory, day)?;

        let mut daily_lines = Vec::new();
        let mut event_cache =
            BTreeMap::<(String, String, String, String, String), ExternalEffect>::new();
        let mut pandemic_cache =
            BTreeMap::<(String, String, String, String, String, String), ExternalEffect>::new();
        let mut markets = config.scenario.markets.iter().collect::<Vec<_>>();
        markets.sort_by(|left, right| left.market_id.cmp(&right.market_id));
        for market in markets {
            let configured_online_share = configured_online_share(market, day, start, end);
            let (actual_temperature, precipitation) = temperature(master_seed, market, day)?;
            let midpoint = (decimal_value(&market.locale_pack["climate"]["summerC"])?
                + decimal_value(&market.locale_pack["climate"]["winterC"])? / Decimal::from(1_u32))
                / Decimal::from(2_u32);
            let holiday_rows = holidays
                .get(&(market.market_id.clone(), day))
                .cloned()
                .unwrap_or_default();
            let holiday_names = holiday_rows
                .iter()
                .map(|holiday| holiday.name.clone())
                .collect::<Vec<_>>();
            let sale_season_ids = active_sale_seasons(market, day);
            let active_promotions = promotions
                .iter()
                .filter(|promotion| {
                    promotion.market_id == market.market_id
                        && promotion.start_date <= day
                        && day <= promotion.end_date
                })
                .collect::<Vec<_>>();
            let recent_promotions = if signal(market, "promotions") {
                promotions
                    .iter()
                    .filter(|promotion| {
                        promotion.market_id == market.market_id
                            && promotion.end_date < day
                            && day <= promotion.end_date + Duration::days(7)
                    })
                    .collect::<Vec<_>>()
            } else {
                Vec::new()
            };
            let day_factors = market
                .demand
                .day_of_week_factors
                .iter()
                .map(|value| Decimal::from_f64_text(*value))
                .collect::<Vec<_>>();
            let day_factor_total = day_factors.iter().sum::<Decimal>();
            let day_of_week_factor = day_factors[day.weekday().num_days_from_monday() as usize]
                .clone()
                * Decimal::from(7_u32)
                / day_factor_total;
            let trend_factor = Decimal::from_f64_text(
                (1.0 + market.demand.annual_growth_rate)
                    .powf((day - start).num_days() as f64 / 365.2425),
            );
            let sale_season_factor = if sale_season_ids.is_empty() {
                Decimal::one()
            } else {
                dec("1.08")
            };
            let macro_factor = if signal(market, "macro") {
                Decimal::one() + Decimal::from((day - start).num_days()) / dec("10000")
            } else {
                Decimal::one()
            };
            let mut holiday_factors = HashMap::<String, Decimal>::new();
            for channel_type in channel_types.values() {
                holiday_factors
                    .entry(channel_type.clone())
                    .or_insert_with(|| {
                        if !holiday_names.is_empty() && signal(market, "holidays") {
                            holiday_demand_factor(&holiday_rows, channel_type)
                        } else {
                            Decimal::one()
                        }
                    });
            }
            let mut lifecycle_cache =
                HashMap::<(usize, usize), causal_lifecycle::LifecycleEffect>::new();
            let mut seasonality_cache = HashMap::<(usize, usize), Decimal>::new();
            let mut original_money_cache = HashMap::<(usize, usize), MoneyDecimal>::new();
            let mut inflated_reference_cache = HashMap::<(usize, usize), Decimal>::new();
            let mut competitor_observation_cache =
                HashMap::<(usize, usize), (Decimal, bool, Decimal)>::new();
            let mut stores = config
                .scenario
                .stores
                .iter()
                .filter(|store| store.market_id == market.market_id)
                .collect::<Vec<_>>();
            stores.sort_by(|left, right| left.store_id.cmp(&right.store_id));
            for store in stores {
                let channel_layout = channel_layouts
                    .get(&store.store_id)
                    .context("store channel layout")?;
                let store_channel_offsets = channel_sku_offsets
                    .get(&store.store_id)
                    .context("store channel SKU offsets")?;
                let positions = assortment
                    .selected_by_store
                    .get(&store.store_id)
                    .context("store assortment")?;
                let active_positions = positions
                    .iter()
                    .copied()
                    .filter(|position| active_on(selected_variant(catalog, *position).1, day))
                    .collect::<Vec<_>>();
                if active_positions.is_empty() {
                    continue;
                }
                let portfolio = annual_weights
                    .get(&(store.store_id.clone(), day.year()))
                    .context("annual portfolio weight")?;
                let baseline_prefix = Decimal::from_f64_text(market.demand.demand_level_scalar)
                    * Decimal::from_f64_text(store.demand_scale)
                    * Decimal::from_f64_text(market.demand.starting_daily_orders)
                    * Decimal::from_f64_text(market.demand.average_lines_per_order);
                let channel_distributions = active_positions
                    .par_iter()
                    .map(|position| {
                        channel_distribution_precomputed(
                            channel_layout,
                            &configured_online_share,
                            &store_channel_offsets[position.product_index][position.variant_index],
                        )
                    })
                    .collect::<Vec<_>>();
                let expected_demand_rows = channel_distributions.iter().map(Vec::len).sum();
                let mut pending_demand_rows = Vec::with_capacity(expected_demand_rows);
                let warehouse_priority = store.warehouse_priority.join("|");
                for (position, channels) in active_positions.into_iter().zip(channel_distributions)
                {
                    let (product, variant) = selected_variant(catalog, position);
                    let identity = (position.product_index, position.variant_index);
                    let lifecycle = lifecycle_cache
                        .entry(identity)
                        .or_insert_with(|| {
                            causal_lifecycle::adjustment(
                                product,
                                variant,
                                day,
                                market.demand.new_product_ramp_days,
                            )
                        })
                        .clone();
                    let seasonal_factor = seasonality_cache
                        .entry(identity)
                        .or_insert_with(|| {
                            seasonality.factor(
                                product.seasonality_peak_month,
                                product_seasonality_strengths[position.product_index].clone(),
                                day,
                            )
                        })
                        .clone();
                    let original_money = if let Some(value) = original_money_cache.get(&identity) {
                        *value
                    } else {
                        let pricing_day = product
                            .successor_launch_date
                            .map_or(day, |successor| day.min(successor));
                        let mut value = price_engine.price_for_day(
                            variant.base_price,
                            market,
                            &variant.sku,
                            pricing_day,
                            start,
                            end,
                            variant.launch_date,
                        )?;
                        value.rescale(2);
                        original_money_cache.insert(identity, value);
                        value
                    };
                    let inflated_reference = inflated_reference_cache
                        .entry(identity)
                        .or_insert_with(|| inflated_base_price(variant, market, day))
                        .clone();
                    let competitor_observation = if signal(market, "competitor") {
                        Some(
                            competitor_observation_cache
                                .entry(identity)
                                .or_insert_with(|| {
                                    (
                                        Decimal::from_f64_text(
                                            PythonRandom::new_with_master(
                                                &master_text,
                                                &[
                                                    "competitor",
                                                    &market.market_id,
                                                    &variant.sku,
                                                    &observation_text,
                                                ],
                                            )
                                            .uniform(0.90, 1.10),
                                        ),
                                        fraction(&[
                                            &master_text,
                                            "competitor-availability",
                                            &market.market_id,
                                            &variant.sku,
                                            &observation_text,
                                        ]) >= 0.08,
                                        inflated_base_price(variant, market, observation_day),
                                    )
                                })
                                .clone(),
                        )
                    } else {
                        None
                    };
                    let portfolio_weight =
                        &variant_portfolio_weights[position.product_index][position.variant_index];
                    let expected_units = &product_expected_units[position.product_index];
                    let elasticity =
                        variant_elasticities[position.product_index][position.variant_index];
                    let baseline_channel_prefix = &baseline_prefix * portfolio_weight / portfolio;
                    let original_price = decimal_from_money(original_money)?;
                    let regular_ratio = dec("0.01").max(&original_price / &inflated_reference);
                    let regular_price_factor = Decimal::from_f64_text(
                        (elasticity * regular_ratio.to_f64().context("regular price ratio")?.ln())
                            .exp(),
                    );
                    let intermittent_cluster = fraction(&[
                        &master_text,
                        "intermittency-cluster",
                        &store.store_id,
                        &variant.sku,
                        &week_text,
                    ]) < market.demand.intermittency_rate * 0.65;
                    let week_noise = PythonRandom::new_with_master(
                        &master_text,
                        &[
                            "demand-week-noise",
                            &store.store_id,
                            &variant.sku,
                            &week_text,
                        ],
                    )
                    .gauss(0.0, market.demand.noise);
                    for (channel_id, channel_share) in channels {
                        let event_key = format!(
                            "{}:{}:{}:{}",
                            store.store_id, day_text, variant.sku, channel_id
                        );
                        let segment = select_segment(config, &master_text, &event_key)?;
                        let event_cache_key = (
                            store.store_id.clone(),
                            product.department_id.clone(),
                            product.category_id.clone(),
                            channel_id.clone(),
                            day_text.clone(),
                        );
                        let event = event_cache
                            .entry(event_cache_key)
                            .or_insert_with(|| {
                                event_effect(
                                    config,
                                    day,
                                    &market.market_id,
                                    &store.store_id,
                                    &product.department_id,
                                    &product.category_id,
                                    &channel_id,
                                )
                            })
                            .clone();
                        let channel_type = channel_types
                            .get(&channel_id)
                            .context("channel type")?
                            .clone();
                        let pandemic_cache_key = (
                            market.market_id.clone(),
                            product.department_id.clone(),
                            product.category_id.clone(),
                            product.catalog_family.clone(),
                            channel_type.clone(),
                            day_text.clone(),
                        );
                        let pandemic = if let Some(value) = pandemic_cache.get(&pandemic_cache_key)
                        {
                            value.clone()
                        } else {
                            let value = pandemic_effect(
                                config,
                                day,
                                &market.market_id,
                                &product.department_id,
                                &product.category_id,
                                &product.catalog_family,
                                &channel_type,
                            )?;
                            pandemic_cache.insert(pandemic_cache_key, value.clone());
                            value
                        };

                        let mut unit_money = original_money;
                        let mut candidates = Vec::new();
                        if !lifecycle.offer_id.is_empty() {
                            candidates.push(PromotionCandidate {
                                promotion_id: lifecycle.offer_id.clone(),
                                promotion_type: lifecycle.offer_type.clone(),
                                discount_pct: lifecycle.offer_discount_pct.clone(),
                                demand_multiplier: lifecycle.offer_demand_factor.clone(),
                            });
                        }
                        if signal(market, "promotions") {
                            for promotion in &active_promotions {
                                if promotion_applies(
                                    promotion,
                                    store,
                                    product,
                                    &segment.segment_id,
                                    &channel_id,
                                ) {
                                    candidates.push(PromotionCandidate {
                                        promotion_id: promotion.promotion_id.clone(),
                                        promotion_type: promotion.promotion_type.clone(),
                                        discount_pct: promotion.discount_pct.clone(),
                                        demand_multiplier: promotion.demand_multiplier.clone(),
                                    });
                                }
                            }
                        }
                        let mut applied_promotions = Vec::new();
                        let mut configured_promotion_lift = Decimal::one();
                        let mut effective_promotion_lift = Decimal::one();
                        let mut effective_promotion_discount = Decimal::zero();
                        if let Some(selected) = candidates.into_iter().max_by(|left, right| {
                            (&left.discount_pct, &left.promotion_id)
                                .cmp(&(&right.discount_pct, &right.promotion_id))
                        }) {
                            applied_promotions.push(selected.promotion_id.clone());
                            configured_promotion_lift = selected.demand_multiplier.clone();
                            let cost_multiplier = &event.cost * &pandemic.cost;
                            unit_money = price_engine.promotional_price(
                                product,
                                variant,
                                market,
                                original_money,
                                day,
                                start,
                                end,
                                money_decimal(&selected.discount_pct)?,
                                &selected.promotion_id,
                                &selected.promotion_type,
                                &cost_multiplier,
                            )?;
                            let original = decimal_from_money(original_money)?;
                            let unit = decimal_from_money(unit_money)?;
                            effective_promotion_discount =
                                Decimal::zero().max((&original - &unit) / &original);
                            let realization = if selected.discount_pct > Decimal::zero() {
                                Decimal::one()
                                    .min(&effective_promotion_discount / &selected.discount_pct)
                            } else {
                                Decimal::one()
                            };
                            effective_promotion_lift = Decimal::one()
                                + (&configured_promotion_lift - Decimal::one()) * realization;
                        }
                        let mut promotion_payback_factor = Decimal::one();
                        for promotion in &recent_promotions {
                            if !promotion_applies(
                                promotion,
                                store,
                                product,
                                &segment.segment_id,
                                &channel_id,
                            ) {
                                continue;
                            }
                            let days_after = (day - promotion.end_date).num_days();
                            let remaining_share =
                                Decimal::from(8_i64 - days_after) / Decimal::from(7_u32);
                            let lift =
                                Decimal::zero().max(&promotion.demand_multiplier - Decimal::one());
                            let payback = dec("0.30").min(lift * dec("0.18")) * remaining_share;
                            promotion_payback_factor =
                                promotion_payback_factor * (Decimal::one() - payback);
                        }
                        let holiday_factor = holiday_factors
                            .get(&channel_type)
                            .context("holiday factor for channel type")?
                            .clone();
                        let event_factor = if signal(market, "localEvents") {
                            &event.demand * &event.traffic
                        } else {
                            Decimal::one()
                        };
                        let pandemic_factor = &pandemic.demand * &pandemic.traffic;
                        let mut weather_factor = Decimal::one();
                        if signal(market, "weather") {
                            let temperature_gap = dec("-1")
                                .max(dec("1").min(
                                    (&actual_temperature - &midpoint) / Decimal::from(15_u32),
                                ));
                            if product.catalog_family == "apparel-outerwear" {
                                weather_factor = weather_factor - &temperature_gap * dec("0.12");
                            } else if product.catalog_family == "apparel-tops" {
                                weather_factor = weather_factor + &temperature_gap * dec("0.06");
                            }
                            if precipitation > dec("2") {
                                let rain_effect =
                                    dec("0.15").min(&precipitation / Decimal::from(100_u32));
                                weather_factor = if channel_type == "online" {
                                    weather_factor + rain_effect * dec("0.35")
                                } else {
                                    weather_factor - rain_effect
                                };
                            }
                        }
                        let unit_price = decimal_from_money(unit_money)?;
                        let mut competitor_factor = Decimal::one();
                        if let Some((competitor_ratio, available, competitor_reference)) =
                            &competitor_observation
                        {
                            if *available {
                                let relative_gap = competitor_reference * competitor_ratio
                                    / &unit_price
                                    - Decimal::one();
                                competitor_factor = dec("0.90").max(
                                    dec("1.10").min(Decimal::one() + relative_gap * dec("0.50")),
                                );
                            }
                        }
                        let price_factor = if applied_promotions.is_empty() {
                            regular_price_factor.clone()
                        } else {
                            let price_ratio = dec("0.01").max(&unit_price / &inflated_reference);
                            Decimal::from_f64_text(
                                (elasticity * price_ratio.to_f64().context("price ratio")?.ln())
                                    .exp(),
                            )
                        };
                        let promotion_elasticity_factor = if applied_promotions.is_empty() {
                            Decimal::one()
                        } else {
                            &price_factor / &regular_price_factor
                        };
                        let promotion_factor = if applied_promotions.is_empty() {
                            Decimal::one()
                        } else {
                            &effective_promotion_lift / &promotion_elasticity_factor
                        };
                        let intermittent = intermittent_cluster
                            || fraction(&[&master_text, "intermittency-daily", &event_key])
                                < market.demand.intermittency_rate * 0.35;
                        let day_noise = PythonRandom::new_with_master(
                            &master_text,
                            &["demand-noise", &event_key],
                        )
                        .gauss(0.0, market.demand.noise);
                        let random_noise = (1.0 + 0.60 * week_noise + 0.40 * day_noise).max(0.05);
                        let baseline = &baseline_channel_prefix * channel_share * expected_units;
                        let total_factor = day_of_week_factor.clone()
                            * &trend_factor
                            * &seasonal_factor
                            * &holiday_factor
                            * &sale_season_factor
                            * &promotion_factor
                            * &promotion_payback_factor
                            * &event_factor
                            * &pandemic_factor
                            * &weather_factor
                            * &macro_factor
                            * &competitor_factor
                            * &price_factor
                            * &lifecycle.launch_factor
                            * &lifecycle.predecessor_factor
                            * &lifecycle.substitution_factor
                            * &segment.demand_multiplier
                            * Decimal::from_f64_text(random_noise);
                        let expected = Decimal::zero().max(&baseline * &total_factor);
                        let latent_units = if intermittent {
                            0
                        } else {
                            i64::try_from(
                                PythonRandom::new_with_master(
                                    &master_text,
                                    &["latent-demand", &event_key],
                                )
                                .poisson(expected.to_f64().context("expected demand")?),
                            )?
                        };
                        let allocations = inventory.allocate(
                            config,
                            store,
                            &variant.sku,
                            latent_units,
                            &event_key,
                        );
                        let realized_units = allocations
                            .iter()
                            .map(|allocation| allocation.quantity)
                            .sum::<i64>();
                        for allocation in &allocations {
                            supply.record_allocation(
                                &allocation.warehouse_id,
                                &variant.sku,
                                day,
                                allocation.quantity,
                            );
                        }
                        let lost_units = latent_units - realized_units;
                        if channel_type == "store" && realized_units > 0 {
                            let (served, short) = store_echelon.sell(
                                day,
                                &store.store_id,
                                &variant.sku,
                                realized_units,
                            );
                            if short > 0 {
                                sink.store_stockout(values([
                                    ("eventKey", format!("store-stockout:{event_key}")),
                                    ("marketKey", market.market_id.clone()),
                                    ("storeKey", store.store_id.clone()),
                                    ("channelId", channel_id.clone()),
                                    ("sku", variant.sku.clone()),
                                    ("eventDate", day.to_string()),
                                    ("demandUnits", realized_units.to_string()),
                                    ("servedFromStoreUnits", served.to_string()),
                                    ("shortfallUnits", short.to_string()),
                                    (
                                        "servedFromSupplyNode",
                                        allocations.first().map_or_else(String::new, |row| {
                                            row.warehouse_id.clone()
                                        }),
                                    ),
                                    ("observedAt", local_iso_at(day, 23, 0, 0, &market.timezone)?),
                                ]))?;
                            }
                        }
                        if realized_units > 0 {
                            let tax_rate = tax_rate_for_line(
                                market,
                                &product.tax_category,
                                unit_price.clone(),
                                day,
                            )?;
                            let quantities = purchase_quantities(
                                master_seed,
                                &event_key,
                                product,
                                realized_units,
                            );
                            let split = split_allocations(&allocations, &quantities);
                            for (purchase_index, (quantity, line_allocations)) in
                                quantities.into_iter().zip(split).enumerate()
                            {
                                let (net, tax, gross) = tax_amounts(
                                    unit_price.clone(),
                                    quantity,
                                    tax_rate.clone(),
                                    market.locale_pack["tax"]["basis"]
                                        .as_str()
                                        .context("tax basis")?,
                                );
                                let line_event_key =
                                    format!("{event_key}:purchase:{:05}", purchase_index + 1);
                                let hour = 9 + u32::try_from(stable_integer(
                                    &[&line_event_key, "hour"],
                                    11,
                                ))?;
                                let minute = u32::try_from(stable_integer(
                                    &[&line_event_key, "minute"],
                                    60,
                                ))?;
                                let second = u32::try_from(stable_integer(
                                    &[&line_event_key, "second"],
                                    60,
                                ))?;
                                let variant_identity =
                                    format!("{}:{}", market.market_id, variant.variant_key);
                                daily_lines.push(LineEvent {
                                    event_key: line_event_key,
                                    order_key: String::new(),
                                    line_key: String::new(),
                                    line_number: 0,
                                    source_order_sequence: 0,
                                    market_id: market.market_id.clone(),
                                    store_id: store.store_id.clone(),
                                    day,
                                    created_at: local_iso_at(
                                        day,
                                        hour,
                                        minute,
                                        second,
                                        &market.timezone,
                                    )?,
                                    product_index: position.product_index,
                                    variant_index: position.variant_index,
                                    sku: variant.sku.clone(),
                                    variant_id: shopify_gid("ProductVariant", &variant_identity),
                                    inventory_item_id: shopify_gid(
                                        "InventoryItem",
                                        &variant_identity,
                                    ),
                                    department_id: product.department_id.clone(),
                                    category_id: product.category_id.clone(),
                                    product_code: product.product_code.clone(),
                                    product_title: product.title.clone(),
                                    brand: product.brand.clone(),
                                    variant_code: variant.variant_code.clone(),
                                    variant_title: variant.title.clone(),
                                    barcode: variant.barcode.clone(),
                                    quantity,
                                    original_unit_price: original_price.clone(),
                                    unit_price: unit_price.clone(),
                                    promotion_ids: applied_promotions.clone(),
                                    net,
                                    tax,
                                    gross,
                                    tax_rate: tax_rate.clone(),
                                    currency_code: market.currency_code.clone(),
                                    taxes_included: market.locale_pack["tax"]["basis"].as_str()
                                        == Some("inclusive"),
                                    allocations: line_allocations
                                        .into_iter()
                                        .map(LineAllocation::from)
                                        .collect(),
                                    customer_segment_id: segment.segment_id.clone(),
                                    channel_id: channel_id.clone(),
                                    return_probability: variant.return_probability,
                                });
                            }
                        }
                        pending_demand_rows.push(PendingDemandRow {
                            position,
                            event_key,
                            channel_id,
                            baseline,
                            expected,
                            latent_units,
                            realized_units,
                            lost_units,
                            intermittent,
                            seasonal_factor: seasonal_factor.clone(),
                            holiday_factor,
                            applied_promotions,
                            configured_promotion_lift,
                            effective_promotion_lift,
                            effective_promotion_discount,
                            promotion_elasticity_factor,
                            promotion_factor,
                            promotion_payback_factor,
                            event,
                            event_factor,
                            pandemic,
                            pandemic_factor,
                            weather_factor,
                            competitor_factor,
                            price_factor,
                            lifecycle: lifecycle.clone(),
                            segment,
                            random_noise,
                            total_factor,
                        });
                    }
                }

                let emitted_rows = pending_demand_rows
                    .into_par_iter()
                    .map(|row| {
                        let (product, variant) = selected_variant(catalog, row.position);
                        let allocation = values([
                            ("requestKey", row.event_key.clone()),
                            ("marketKey", market.market_id.clone()),
                            ("storeKey", store.store_id.clone()),
                            ("channelId", row.channel_id.clone()),
                            ("requestDate", day_text.clone()),
                            ("sku", variant.sku.clone()),
                            ("requestedQuantity", row.latent_units.to_string()),
                            ("allocatedQuantity", row.realized_units.to_string()),
                            ("unallocatedQuantity", row.lost_units.to_string()),
                            ("warehousePriority", warehouse_priority.clone()),
                            (
                                "status",
                                if row.lost_units == 0 {
                                    "allocated"
                                } else {
                                    "partial"
                                }
                                .to_owned(),
                            ),
                        ]);
                        let demand = demand_truth_row(
                            market,
                            store,
                            product,
                            variant,
                            day,
                            &row.channel_id,
                            &row.baseline,
                            &row.expected,
                            row.latent_units,
                            row.realized_units,
                            row.lost_units,
                            row.intermittent,
                            &day_of_week_factor,
                            &trend_factor,
                            &row.seasonal_factor,
                            &holiday_names,
                            &row.holiday_factor,
                            &sale_season_ids,
                            &sale_season_factor,
                            &row.applied_promotions,
                            &row.configured_promotion_lift,
                            &row.effective_promotion_lift,
                            &row.effective_promotion_discount,
                            &row.promotion_elasticity_factor,
                            &row.promotion_factor,
                            &row.promotion_payback_factor,
                            &row.event,
                            &row.event_factor,
                            &row.pandemic,
                            &row.pandemic_factor,
                            &row.weather_factor,
                            &macro_factor,
                            &row.competitor_factor,
                            &row.price_factor,
                            &row.lifecycle,
                            &row.segment,
                            row.random_noise,
                            &row.total_factor,
                        );
                        (allocation, demand)
                    })
                    .collect::<Vec<_>>();
                for (allocation, demand) in emitted_rows {
                    sink.allocation_request(allocation)?;
                    sink.demand_truth(demand)?;
                }
            }
        }

        let mut daily_orders = group_baskets(config, &mut daily_lines, &mut customers, catalog)?;
        daily_orders.sort_by(|left, right| {
            (&left.created_at, &left.order_key).cmp(&(&right.created_at, &right.order_key))
        });
        for order in &mut daily_orders {
            source_order_sequence += 1;
            order.source_order_sequence = source_order_sequence;
            order.source_order_name = format!("#{}", 1000 + source_order_sequence);
        }
        let order_sequences = daily_orders
            .iter()
            .map(|order| (order.order_key.clone(), order.source_order_sequence))
            .collect::<BTreeMap<_, _>>();
        let order_created = daily_orders
            .iter()
            .map(|order| (order.order_key.clone(), order.created_at.clone()))
            .collect::<BTreeMap<_, _>>();
        for line in &mut daily_lines {
            line.source_order_sequence = order_sequences[&line.order_key];
            for allocation in &mut line.allocations {
                let (created, delivered) = fulfillment_timestamps(
                    config,
                    &line.order_key,
                    &allocation.warehouse_id,
                    &order_created[&line.order_key],
                )?;
                allocation.fulfillment_created_at = created.clone();
                allocation.fulfillment_delivered_at = delivered;
                let release = Release {
                    warehouse_id: allocation.warehouse_id.clone(),
                    sku: line.sku.clone(),
                    quantity: allocation.quantity,
                };
                let release_day = NaiveDate::parse_from_str(&created[..10], "%Y-%m-%d")?;
                if release_day <= day {
                    release_inventory(&mut inventory, &release)?;
                } else {
                    fulfillment_releases
                        .entry(release_day)
                        .or_default()
                        .push(release);
                }
            }
        }
        daily_orders.sort_by(|left, right| left.order_key.cmp(&right.order_key));
        daily_lines.sort_by(|left, right| {
            (&left.order_key, left.line_number).cmp(&(&right.order_key, right.line_number))
        });
        for order in &daily_orders {
            order_count += 1;
            unit_count += order.units;
            control_net = control_net + &order.net;
            control_tax = control_tax + &order.tax;
            control_gross = control_gross + &order.gross;
        }
        line_count += daily_lines.len() as u64;
        sink.day_orders(day, daily_orders, daily_lines)?;

        for row in store_echelon.review(day)? {
            sink.store_transfer(row)?;
        }
        for row in store_echelon.snapshot(day)? {
            sink.store_observation(row)?;
        }
        emit_supply(sink, supply.snapshot(config, catalog, &inventory, day)?)?;
        day += Duration::days(1);
    }
    inventory.reconcile()?;
    for row in SupplyState::batch_rows(&inventory) {
        sink.batch_balance(row)?;
    }
    let market_ids = config
        .scenario
        .markets
        .iter()
        .map(|market| market.market_id.clone())
        .collect::<Vec<_>>();
    for row in customers.records(market_ids)? {
        sink.customer_record(row)?;
    }
    Ok(CausalFinalState {
        inventory,
        store_inventory_controls: store_echelon.coverage_summary(),
        order_count,
        line_count,
        unit_count,
        net: control_net,
        tax: control_tax,
        gross: control_gross,
    })
}

fn emit_supply<S: CausalSink>(sink: &mut S, emissions: SupplyEmissions) -> Result<()> {
    for row in emissions.receipts {
        sink.receipt_event(row)?;
    }
    for row in emissions.transfers {
        sink.transfer_event(row)?;
    }
    for row in emissions.losses {
        sink.inventory_loss_event(row)?;
    }
    for row in emissions.waste {
        sink.waste_event(row)?;
    }
    for row in emissions.observations {
        sink.inventory_observation(row)?;
    }
    for row in emissions.pools {
        sink.supply_pool(row)?;
    }
    Ok(())
}

fn annual_portfolio_weights(
    config: &LoadedConfig,
    catalog: &[Product],
    assortment: &StoreAssortment,
) -> BTreeMap<(String, i32), Decimal> {
    let mut result = BTreeMap::new();
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
            result.insert(
                (store.store_id.clone(), year),
                average_active_portfolio_weight(variants, period_start, period_end),
            );
        }
    }
    result
}

fn group_baskets(
    config: &LoadedConfig,
    lines: &mut [LineEvent],
    customers: &mut CustomerPopulation<'_>,
    _catalog: &[Product],
) -> Result<Vec<OrderHeader>> {
    let mut groups = BTreeMap::<(String, NaiveDate, String, String), Vec<usize>>::new();
    for (index, line) in lines.iter().enumerate() {
        groups
            .entry((
                line.store_id.clone(),
                line.day,
                line.customer_segment_id.clone(),
                line.channel_id.clone(),
            ))
            .or_default()
            .push(index);
    }
    let mut orders = Vec::new();
    let mut sequence_by_store_day = BTreeMap::<(String, NaiveDate), usize>::new();
    let master_seed = config.scenario.identity.master_seed;
    let master_text = master_seed.to_string();
    for ((store_id, day, segment_id, channel_id), mut indices) in groups {
        let mut keyed_indices = indices
            .drain(..)
            .map(|index| {
                (
                    stable_integer(
                        &[&master_text, "basket-line-order", &lines[index].event_key],
                        i64::MAX as u64,
                    ),
                    index,
                )
            })
            .collect::<Vec<_>>();
        keyed_indices.sort_by(|(left_key, left), (right_key, right)| {
            (left_key, &lines[*left].event_key).cmp(&(right_key, &lines[*right].event_key))
        });
        indices.extend(keyed_indices.into_iter().map(|(_, index)| index));
        let market = config
            .scenario
            .markets
            .iter()
            .find(|market| market.market_id == lines[indices[0]].market_id)
            .context("basket market")?;
        let mut cursor = 0_usize;
        let day_text = day.to_string();
        let mut basket_index = *sequence_by_store_day
            .get(&(store_id.clone(), day))
            .unwrap_or(&0);
        while cursor < indices.len() {
            let basket_text = basket_index.to_string();
            let mut size = 1 + usize::try_from(
                PythonRandom::new_with_master(
                    &master_text,
                    &[
                        "basket-size",
                        &store_id,
                        &day_text,
                        &segment_id,
                        &channel_id,
                        &basket_text,
                    ],
                )
                .poisson((market.demand.average_lines_per_order - 1.0).max(0.0)),
            )?;
            size = size.clamp(1, 8).min(indices.len() - cursor);
            let basket = &indices[cursor..cursor + size];
            let order_key = format!("{store_id}:{day}:order:{basket_index:05}");
            for (line_position, index) in basket.iter().enumerate() {
                let line = &mut lines[*index];
                line.order_key = order_key.clone();
                line.line_key = format!("{order_key}:line:{:03}", line_position + 1);
                line.line_number = (line_position + 1) * 10_000;
            }
            let first = &lines[basket[0]];
            let net = basket
                .iter()
                .map(|index| lines[*index].net.clone())
                .sum::<Decimal>();
            let tax = basket
                .iter()
                .map(|index| lines[*index].tax.clone())
                .sum::<Decimal>();
            let gross = basket
                .iter()
                .map(|index| lines[*index].gross.clone())
                .sum::<Decimal>();
            let created_at = basket
                .iter()
                .map(|index| lines[*index].created_at.as_str())
                .min()
                .expect("basket line")
                .to_owned();
            let (customer_key, customer_created_date) = customers.allocate(
                &first.market_id,
                &first.customer_segment_id,
                day,
                &order_key,
            )?;
            orders.push(OrderHeader {
                order_key: order_key.clone(),
                market_id: first.market_id.clone(),
                store_id: store_id.clone(),
                day,
                created_at,
                currency_code: first.currency_code.clone(),
                taxes_included: first.taxes_included,
                net,
                tax,
                gross,
                units: basket.iter().map(|index| lines[*index].quantity).sum(),
                line_count: basket.len(),
                customer_segment_id: first.customer_segment_id.clone(),
                customer_key: customer_key.clone(),
                customer_created_date,
                bc_customer_key: if customer_key.is_empty() {
                    format!("walk-in:{}", first.market_id)
                } else {
                    customer_key
                },
                channel_id: first.channel_id.clone(),
                source_order_sequence: 0,
                source_order_name: String::new(),
            });
            cursor += size;
            basket_index += 1;
        }
        sequence_by_store_day.insert((store_id, day), basket_index);
    }
    Ok(orders)
}

#[allow(clippy::too_many_arguments)]
fn demand_truth_row(
    market: &Market,
    store: &Store,
    product: &Product,
    variant: &Variant,
    day: NaiveDate,
    channel_id: &str,
    baseline: &Decimal,
    expected: &Decimal,
    latent: i64,
    realized: i64,
    lost: i64,
    intermittent: bool,
    day_of_week: &Decimal,
    trend: &Decimal,
    seasonal: &Decimal,
    holiday_names: &[String],
    holiday: &Decimal,
    sale_seasons: &[String],
    sale_season: &Decimal,
    promotion_ids: &[String],
    configured_promotion_lift: &Decimal,
    effective_promotion_lift: &Decimal,
    effective_promotion_discount: &Decimal,
    promotion_elasticity: &Decimal,
    promotion: &Decimal,
    promotion_payback: &Decimal,
    event: &ExternalEffect,
    event_factor: &Decimal,
    pandemic: &ExternalEffect,
    pandemic_factor: &Decimal,
    weather: &Decimal,
    macro_factor: &Decimal,
    competitor: &Decimal,
    price: &Decimal,
    lifecycle: &causal_lifecycle::LifecycleEffect,
    segment: &RawSegment,
    noise: f64,
    total: &Decimal,
) -> FieldValues {
    values([
        ("marketKey", market.market_id.clone()),
        ("storeKey", store.store_id.clone()),
        ("channelId", channel_id.to_owned()),
        ("date", day.to_string()),
        ("sku", variant.sku.clone()),
        ("departmentId", product.department_id.clone()),
        ("categoryId", product.category_id.clone()),
        (
            "baselineDemand",
            baseline.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        (
            "expectedDemand",
            expected.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        ("latentDemandUnits", latent.to_string()),
        ("realizedSalesUnits", realized.to_string()),
        ("lostSalesUnits", lost.to_string()),
        ("intermittentZero", intermittent.to_string()),
        ("dayOfWeekFactor", day_of_week.to_string()),
        (
            "trendFactor",
            trend.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        (
            "seasonalityFactor",
            seasonal.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        ("holidayNames", holiday_names.join("|")),
        ("holidayFactor", holiday.to_string()),
        ("saleSeasonIds", sale_seasons.join("|")),
        ("saleSeasonFactor", sale_season.to_string()),
        ("promotionIds", promotion_ids.join("|")),
        (
            "configuredPromotionLift",
            configured_promotion_lift.to_string(),
        ),
        (
            "effectivePromotionLift",
            effective_promotion_lift.to_string(),
        ),
        (
            "effectivePromotionDiscountPct",
            effective_promotion_discount.to_string(),
        ),
        (
            "promotionElasticityFactor",
            promotion_elasticity.to_string(),
        ),
        ("promotionFactor", promotion.to_string()),
        ("promotionPaybackFactor", promotion_payback.to_string()),
        ("eventIds", event.event_ids.join("|")),
        ("eventFactor", event_factor.to_string()),
        ("pandemicIds", pandemic.pandemic_ids.join("|")),
        ("pandemicPhaseIds", pandemic.phase_ids.join("|")),
        ("pandemicDemandFactor", pandemic.demand.to_string()),
        ("pandemicTrafficFactor", pandemic.traffic.to_string()),
        ("pandemicFactor", pandemic_factor.to_string()),
        (
            "weatherFactor",
            weather.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        (
            "macroFactor",
            macro_factor.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        ("competitorFactor", competitor.to_string()),
        (
            "priceFactor",
            price.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
        ("newProductFactor", lifecycle.launch_factor.to_string()),
        ("launchProfile", lifecycle.launch_profile.clone()),
        (
            "predecessorFactor",
            lifecycle.predecessor_factor.to_string(),
        ),
        (
            "substitutionFactor",
            lifecycle.substitution_factor.to_string(),
        ),
        ("lifecycleOfferType", lifecycle.offer_type.clone()),
        (
            "lifecycleDiscountPct",
            lifecycle.offer_discount_pct.to_string(),
        ),
        ("segmentFactor", segment.demand_multiplier.to_string()),
        (
            "noiseFactor",
            Decimal::from_f64_text(noise)
                .quantize(6, RoundingMode::HalfEven)
                .to_string(),
        ),
        (
            "totalFactor",
            total.quantize(6, RoundingMode::HalfEven).to_string(),
        ),
    ])
}

fn release_inventory(inventory: &mut InventoryState, release: &Release) -> Result<()> {
    let key = InventoryKey::new(&release.warehouse_id, &release.sku);
    let quantity = release
        .quantity
        .min(InventoryState::value(&inventory.committed, &key))
        .min(InventoryState::value(&inventory.on_hand, &key));
    *inventory.committed.entry(key.clone()).or_default() -= quantity;
    *inventory.on_hand.entry(key.clone()).or_default() -= quantity;
    if quantity > 0 {
        inventory.batches.deplete(&key, quantity, None)?;
    }
    Ok(())
}

fn raw_promotions(config: &LoadedConfig) -> Result<Vec<RawPromotion>> {
    config.raw["promotions"]
        .as_array()
        .context("promotions")?
        .iter()
        .map(|value| {
            Ok(RawPromotion {
                promotion_id: text(value, "promotionId")?,
                promotion_type: value["promotionType"]
                    .as_str()
                    .unwrap_or("campaign")
                    .to_owned(),
                market_id: text(value, "marketId")?,
                start_date: raw_date(value, "startDate")?,
                end_date: raw_date(value, "endDate")?,
                store_ids: strings(&value["storeIds"]),
                channel_ids: strings(&value["channelIds"]),
                department_ids: strings(&value["departmentIds"]),
                category_ids: strings(&value["categoryIds"]),
                customer_segment_ids: strings(&value["customerSegmentIds"]),
                discount_pct: decimal_value(&value["discountPct"])?,
                demand_multiplier: decimal_value(&value["demandMultiplier"])?,
            })
        })
        .collect()
}

fn promotion_applies(
    promotion: &RawPromotion,
    store: &Store,
    product: &Product,
    segment_id: &str,
    channel_id: &str,
) -> bool {
    (promotion.store_ids.is_empty() || promotion.store_ids.contains(&store.store_id))
        && (promotion.channel_ids.is_empty()
            || promotion
                .channel_ids
                .iter()
                .any(|value| value == channel_id))
        && (promotion.department_ids.is_empty()
            || promotion.department_ids.contains(&product.department_id))
        && (promotion.category_ids.is_empty()
            || promotion.category_ids.contains(&product.category_id))
        && (promotion.customer_segment_ids.is_empty()
            || promotion
                .customer_segment_ids
                .iter()
                .any(|value| value == segment_id))
}

#[derive(Debug, Clone)]
struct RawSegment {
    segment_id: String,
    demand_multiplier: Decimal,
}

fn select_segment(config: &LoadedConfig, master_seed: &str, event_key: &str) -> Result<RawSegment> {
    let position = fraction(&[master_seed, "segment", event_key]);
    let raw = config.raw["customerSegments"]
        .as_array()
        .context("customerSegments")?;
    let mut cumulative = 0.0;
    for segment in raw {
        cumulative += segment["share"].as_f64().context("segment share")?;
        if position <= cumulative {
            return Ok(RawSegment {
                segment_id: text(segment, "segmentId")?,
                demand_multiplier: decimal_value(&segment["demandMultiplier"])?,
            });
        }
    }
    let segment = raw.last().context("customer segment")?;
    Ok(RawSegment {
        segment_id: text(segment, "segmentId")?,
        demand_multiplier: decimal_value(&segment["demandMultiplier"])?,
    })
}

fn holiday_index(config: &LoadedConfig) -> Result<BTreeMap<(String, NaiveDate), Vec<Holiday>>> {
    let mut result = BTreeMap::new();
    for market in &config.scenario.markets {
        for holiday in holidays_for_range(
            &market.locale_pack,
            config.scenario.time.start_date,
            config.scenario.time.end_date,
        )? {
            let day = NaiveDate::parse_from_str(&holiday.date, "%Y-%m-%d")?;
            result
                .entry((market.market_id.clone(), day))
                .or_insert_with(Vec::new)
                .push(holiday);
        }
    }
    Ok(result)
}

fn inflated_base_price(variant: &Variant, market: &Market, day: NaiveDate) -> Decimal {
    let years = (day.year() - variant.launch_date.year()).max(0);
    let rate = market.price_dynamics["annualInflationRate"]
        .as_f64()
        .expect("validated inflation rate");
    Decimal::from_str(&variant.base_price.to_string()).expect("base price")
        * Decimal::from_f64_text((1.0 + rate).powf(f64::from(years)))
}

fn decimal_from_money(value: MoneyDecimal) -> Result<Decimal> {
    Decimal::from_str(&value.to_string()).context("money decimal")
}

fn money_decimal(value: &Decimal) -> Result<MoneyDecimal> {
    MoneyDecimal::from_str(&value.normalized_string()).context("fixed money decimal")
}

fn raw_date(value: &Value, key: &str) -> Result<NaiveDate> {
    NaiveDate::parse_from_str(&text(value, key)?, "%Y-%m-%d")
        .with_context(|| format!("invalid {key}"))
}

fn text(value: &Value, key: &str) -> Result<String> {
    value[key]
        .as_str()
        .map(str::to_owned)
        .with_context(|| format!("missing {key}"))
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn decimal_value(value: &Value) -> Result<Decimal> {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
        .parse()
        .context("decimal value")
}

fn signal(market: &Market, name: &str) -> bool {
    market.signals[name].as_bool().unwrap_or(false)
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
}

fn values<const N: usize>(entries: [(&'static str, String); N]) -> FieldValues {
    entries.into_iter().collect()
}

#[cfg(test)]
mod tests {
    use sha2::{Digest, Sha256};

    use super::{CausalSink, LineEvent, OrderHeader, simulate};
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::contracts;
    use crate::simulation::model::FieldValues;

    struct DigestSink {
        demand: JsonRowsDigest,
        allocation: JsonRowsDigest,
        orders: u64,
        lines: u64,
        receipts: u64,
        transfers: u64,
        losses: u64,
        waste: u64,
        observations: u64,
        pools: u64,
        batches: u64,
    }

    impl DigestSink {
        fn new() -> Self {
            Self {
                demand: JsonRowsDigest::new("hiddenTruth", "demandFactors"),
                allocation: JsonRowsDigest::new("companion", "allocationDemandRequests"),
                orders: 0,
                lines: 0,
                receipts: 0,
                transfers: 0,
                losses: 0,
                waste: 0,
                observations: 0,
                pools: 0,
                batches: 0,
            }
        }
    }

    impl CausalSink for DigestSink {
        fn demand_truth(&mut self, row: FieldValues) -> anyhow::Result<()> {
            self.demand.push(&row);
            Ok(())
        }

        fn allocation_request(&mut self, row: FieldValues) -> anyhow::Result<()> {
            self.allocation.push(&row);
            Ok(())
        }

        fn day_orders(
            &mut self,
            _day: chrono::NaiveDate,
            orders: Vec<OrderHeader>,
            lines: Vec<LineEvent>,
        ) -> anyhow::Result<()> {
            self.orders += orders.len() as u64;
            self.lines += lines.len() as u64;
            Ok(())
        }

        fn receipt_event(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.receipts += 1;
            Ok(())
        }

        fn transfer_event(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.transfers += 1;
            Ok(())
        }

        fn inventory_loss_event(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.losses += 1;
            Ok(())
        }

        fn waste_event(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.waste += 1;
            Ok(())
        }

        fn inventory_observation(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.observations += 1;
            Ok(())
        }

        fn supply_pool(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.pools += 1;
            Ok(())
        }

        fn batch_balance(&mut self, _row: FieldValues) -> anyhow::Result<()> {
            self.batches += 1;
            Ok(())
        }
    }

    struct JsonRowsDigest {
        fields: Vec<String>,
        hasher: Sha256,
        first: bool,
        rows: u64,
    }

    impl JsonRowsDigest {
        fn new(source: &str, dataset: &str) -> Self {
            let mut hasher = Sha256::new();
            hasher.update(b"[");
            Self {
                fields: contracts::fields(source, dataset).expect("fields"),
                hasher,
                first: true,
                rows: 0,
            }
        }

        fn push(&mut self, row: &FieldValues) {
            if !self.first {
                self.hasher.update(b",");
            }
            self.first = false;
            let normalized = self
                .fields
                .iter()
                .map(|field| {
                    row.get(field.as_str())
                        .filter(|value| !value.is_empty())
                        .cloned()
                })
                .collect::<Vec<_>>();
            self.hasher
                .update(serde_json::to_vec(&normalized).expect("row JSON"));
            self.rows += 1;
        }

        fn finish(mut self) -> (u64, String) {
            self.hasher.update(b"]");
            (self.rows, hex::encode(self.hasher.finalize()))
        }
    }

    #[test]
    fn gulf_mini_demand_and_orders_match_python_oracle() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let mut sink = DigestSink::new();
        let result = simulate(&config, &catalog, &mut sink).expect("causal simulation");
        assert_eq!(sink.orders, 1_026);
        assert_eq!(sink.lines, 2_027);
        assert_eq!(result.order_count, 1_026);
        assert_eq!(result.line_count, 2_027);
        assert_eq!(result.unit_count, 2_030);
        assert_eq!(sink.receipts, 55);
        assert_eq!(sink.transfers, 0);
        assert_eq!(sink.losses, 0);
        assert_eq!(sink.waste, 1);
        assert_eq!(sink.observations, 5_256);
        assert_eq!(sink.pools, 5_256);
        assert_eq!(sink.batches, 1_749);
        assert_eq!(
            result
                .net
                .quantize(2, bigdecimal::RoundingMode::HalfEven)
                .to_string(),
            "20583481.57"
        );
        assert_eq!(
            result
                .tax
                .quantize(2, bigdecimal::RoundingMode::HalfEven)
                .to_string(),
            "3815856.15"
        );
        assert_eq!(
            result
                .gross
                .quantize(2, bigdecimal::RoundingMode::HalfEven)
                .to_string(),
            "24399337.72"
        );
        assert_eq!(
            sink.demand.finish(),
            (
                134_442,
                "f99e4103235ea0f2b671b6c01c1a6ae6e0e6c6309b565e6fc67dbc305096ff90".to_owned()
            )
        );
        assert_eq!(
            sink.allocation.finish(),
            (
                134_442,
                "500cce254972add3367c1dc5efaa35f98944892cd5bf19e4253a79351958ab23".to_owned()
            )
        );
    }
}
