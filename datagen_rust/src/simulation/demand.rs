use std::collections::HashMap;
use std::str::FromStr;

use anyhow::{Context, Result};
use bigdecimal::RoundingMode;
use chrono::{Datelike, Duration, NaiveDate};

use crate::catalog::{Product, Variant};
use crate::config::{CustomerSegment, LoadedConfig, Market, Promotion, Store};
use crate::deterministic::stable_integer;
use crate::simulation::calendar::Holiday;
use crate::simulation::decimal::PyDecimal as Decimal;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Allocation {
    pub warehouse_id: String,
    pub quantity: i64,
    pub priority: usize,
}

#[derive(Debug, Clone)]
pub(crate) struct ChannelLayout {
    channels: Vec<ChannelLayoutEntry>,
}

#[derive(Debug, Clone)]
struct ChannelLayoutEntry {
    channel_id: String,
    online: bool,
    type_count: usize,
}

#[derive(Debug, Default)]
pub struct SeasonalityEngine {
    annual_means: HashMap<(u32, String, i32), Decimal>,
}

impl SeasonalityEngine {
    #[must_use]
    pub fn factor(&mut self, peak_month: u32, strength: Decimal, day: NaiveDate) -> Decimal {
        let raw = seasonality_raw(peak_month, strength.clone(), day);
        let mean = self.annual_mean(peak_month, strength, day.year());
        dec("0.05").max(raw / mean)
    }

    #[must_use]
    pub fn annual_mean(&mut self, peak_month: u32, strength: Decimal, year: i32) -> Decimal {
        let strength_text = strength.normalized_string();
        let key = (peak_month, strength_text, year);
        self.annual_means
            .entry(key)
            .or_insert_with(|| {
                let year_start = NaiveDate::from_ymd_opt(year, 1, 1).expect("valid year");
                let year_days = if leap_year(year) { 366 } else { 365 };
                (0..year_days)
                    .map(|offset| {
                        seasonality_raw(
                            peak_month,
                            strength.clone(),
                            year_start + Duration::days(i64::from(offset)),
                        )
                    })
                    .sum::<Decimal>()
                    / Decimal::from(year_days)
            })
            .clone()
    }
}

#[must_use]
pub fn active_sale_seasons(market: &Market, day: NaiveDate) -> Vec<String> {
    let month_day = day.format("%m-%d").to_string();
    market.locale_pack["saleSeasons"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|season| {
            let start = season["startMonthDay"].as_str().unwrap_or_default();
            let end = season["endMonthDay"].as_str().unwrap_or_default();
            if start <= end {
                start <= month_day.as_str() && month_day.as_str() <= end
            } else {
                month_day.as_str() >= start || month_day.as_str() <= end
            }
        })
        .filter_map(|season| season["id"].as_str().map(str::to_owned))
        .collect()
}

#[must_use]
pub fn seasonality_raw(peak_month: u32, strength: Decimal, day: NaiveDate) -> Decimal {
    let peak_day_of_month = if peak_month == 12 { 24 } else { 15 };
    let mut peak_day = NaiveDate::from_ymd_opt(day.year() - 1, peak_month, peak_day_of_month)
        .expect("valid seasonality peak");
    let mut distance = (day - peak_day).num_days().abs();
    for year in [day.year(), day.year() + 1] {
        let candidate = NaiveDate::from_ymd_opt(year, peak_month, peak_day_of_month)
            .expect("valid seasonality peak");
        let candidate_distance = (day - candidate).num_days().abs();
        if candidate_distance < distance {
            peak_day = candidate;
            distance = candidate_distance;
        }
    }
    let offset_days = (day - peak_day).num_days();
    let sigma_days = if peak_month == 12 {
        if offset_days < 0 { 30.0 } else { 5.0 }
    } else if offset_days < 0 {
        55.0
    } else {
        24.0
    };
    // Python's `** 2` follows the platform `pow` path; `powi(2)` can round the
    // intermediate one ulp differently and changes final Decimal text.
    let bump = (-0.5 * (offset_days as f64 / sigma_days).powf(2.0)).exp();
    let floor = dec("0.25").max(Decimal::one() - strength.clone() * dec("1.50"));
    floor + strength * Decimal::from(3_u32) * decimal_from_f64(bump)
}

#[must_use]
pub fn holiday_demand_factor(holidays: &[Holiday], channel_type: &str) -> Decimal {
    let mut closures = Vec::new();
    let mut factors = Vec::new();
    for holiday in holidays {
        if holiday.retail_behavior == "observance" {
            continue;
        }
        if holiday.retail_behavior == "closed" {
            closures.push(if channel_type == "online" {
                dec("0.55")
            } else {
                dec("0.05")
            });
        } else if holiday.retail_behavior == "retail-peak" && holiday.name == "Black Friday" {
            factors.push(dec("3.20"));
        } else if holiday.retail_behavior == "retail-peak" && holiday.name == "Cyber Monday" {
            factors.push(if channel_type == "online" {
                dec("2.80")
            } else {
                dec("1.35")
            });
        } else {
            factors.push(match holiday.name.as_str() {
                "Diwali" => dec("1.45"),
                "Boxing Day" => dec("2.20"),
                "Republic Day" => dec("1.22"),
                "Independence Day" => dec("1.18"),
                "Veterans Day" => dec("1.08"),
                _ => dec("1.15"),
            });
        }
    }
    closures
        .into_iter()
        .min()
        .unwrap_or_else(|| factors.into_iter().max().unwrap_or_else(Decimal::one))
}

pub fn tax_rate_for_line(
    market: &Market,
    tax_category: &str,
    unit_price: Decimal,
    day: NaiveDate,
) -> Result<Decimal> {
    if market.country_code == "IN" && day < NaiveDate::from_ymd_opt(2017, 7, 1).expect("GST start")
    {
        return Ok(match tax_category {
            "apparel" | "grocery" => dec("0.05"),
            "electronics" => dec("0.125"),
            _ => dec("0.125"),
        });
    }
    if market.country_code == "US"
        && market.region_code == "NY"
        && tax_category == "apparel"
        && unit_price < dec("110")
    {
        return Ok(Decimal::zero());
    }
    if market.country_code == "IN"
        && day >= NaiveDate::from_ymd_opt(2017, 7, 1).expect("GST start")
        && tax_category == "apparel"
        && unit_price <= dec("1000")
    {
        return Ok(dec("0.05"));
    }
    let value = market.locale_pack["tax"]["categoryRates"]
        .get(tax_category)
        .unwrap_or(&market.locale_pack["tax"]["defaultRate"]);
    decimal_value(value)
}

#[must_use]
pub fn tax_amounts(
    unit_price: Decimal,
    quantity: i64,
    rate: Decimal,
    basis: &str,
) -> (Decimal, Decimal, Decimal) {
    let listed_total = unit_price * Decimal::from(quantity);
    if basis == "inclusive" {
        let gross = listed_total;
        let net = (&gross / (Decimal::one() + rate)).quantize(2, RoundingMode::HalfEven);
        (net.clone(), &gross - &net, gross)
    } else {
        let net = listed_total;
        let tax = (&net * rate).quantize(2, RoundingMode::HalfEven);
        (net.clone(), tax.clone(), net + tax)
    }
}

#[must_use]
pub fn segment_for_event<'a>(config: &'a LoadedConfig, event_key: &str) -> &'a CustomerSegment {
    let master_seed = config.scenario.identity.master_seed.to_string();
    let position = fraction(&[&master_seed, "segment", event_key]);
    let mut cumulative = 0.0;
    for segment in &config.scenario.customer_segments {
        cumulative += segment.share;
        if position <= cumulative {
            return segment;
        }
    }
    config
        .scenario
        .customer_segments
        .last()
        .expect("validated customer segments")
}

pub fn channel_distribution(
    master_seed: u64,
    store: &Store,
    variant: &Variant,
    channel_types: &HashMap<String, String>,
    market: &Market,
    day: NaiveDate,
    start: NaiveDate,
    end: NaiveDate,
) -> Result<Vec<(String, Decimal)>> {
    let layout = channel_layout(store, channel_types)?;
    if layout.channels.len() == 1 {
        return Ok(vec![(
            layout.channels[0].channel_id.clone(),
            Decimal::one(),
        )]);
    }
    let configured_share = configured_online_share(market, day, start, end);
    let sku_offset = channel_sku_offset(master_seed, store, variant, market);
    Ok(channel_distribution_precomputed(
        &layout,
        &configured_share,
        &sku_offset,
    ))
}

pub(crate) fn channel_layout(
    store: &Store,
    channel_types: &HashMap<String, String>,
) -> Result<ChannelLayout> {
    let mut channels = store.channel_ids.clone();
    channels.sort();
    if channels.len() == 1 {
        return Ok(ChannelLayout {
            channels: vec![ChannelLayoutEntry {
                channel_id: channels[0].clone(),
                online: false,
                type_count: 1,
            }],
        });
    }

    let mut type_counts = HashMap::<String, usize>::new();
    for channel_id in &channels {
        *type_counts
            .entry(
                channel_types
                    .get(channel_id)
                    .with_context(|| format!("unknown channel {channel_id}"))?
                    .clone(),
            )
            .or_default() += 1;
    }
    Ok(ChannelLayout {
        channels: channels
            .into_iter()
            .map(|channel_id| {
                let channel_type = channel_types
                    .get(&channel_id)
                    .expect("channel layout was validated");
                ChannelLayoutEntry {
                    channel_id,
                    online: channel_type == "online",
                    type_count: type_counts[channel_type],
                }
            })
            .collect(),
    })
}

pub(crate) fn configured_online_share(
    market: &Market,
    day: NaiveDate,
    start: NaiveDate,
    end: NaiveDate,
) -> Decimal {
    let horizon_days = (end - start).num_days().max(1);
    let progress = Decimal::from((day - start).num_days()) / Decimal::from(horizon_days);
    decimal_from_f64(market.demand.online_share_start)
        + (decimal_from_f64(market.demand.online_share_end)
            - decimal_from_f64(market.demand.online_share_start))
            * progress
}

pub(crate) fn channel_sku_offset(
    master_seed: u64,
    store: &Store,
    variant: &Variant,
    market: &Market,
) -> Decimal {
    let master_seed = master_seed.to_string();
    let variation = decimal_from_f64(market.demand.online_share_sku_variation);
    variation
        * (Decimal::from(stable_integer(
            &[
                &master_seed,
                "channel-online-propensity",
                &store.store_id,
                &variant.sku,
            ],
            2_000_001,
        )) / Decimal::from(1_000_000_u32)
            - Decimal::one())
}

pub(crate) fn channel_distribution_precomputed(
    layout: &ChannelLayout,
    configured_share: &Decimal,
    sku_offset: &Decimal,
) -> Vec<(String, Decimal)> {
    if layout.channels.len() == 1 {
        return vec![(layout.channels[0].channel_id.clone(), Decimal::one())];
    }

    let online_share = (configured_share + sku_offset).clamp(dec("0.01"), dec("0.95"));
    let mut weights = Vec::with_capacity(layout.channels.len());
    for channel in &layout.channels {
        let type_share = if channel.online {
            online_share.clone()
        } else {
            Decimal::one() - online_share.clone()
        };
        weights.push(type_share / Decimal::from(channel.type_count));
    }
    let total = weights.iter().sum::<Decimal>();
    layout
        .channels
        .iter()
        .zip(weights)
        .map(|(channel, weight)| (channel.channel_id.clone(), weight / &total))
        .collect()
}

#[must_use]
pub fn promotion_applies(
    promotion: &Promotion,
    store: &Store,
    product: &Product,
    segment_id: &str,
    channel_id: &str,
) -> bool {
    (promotion.store_ids.is_empty() || promotion.store_ids.contains(&store.store_id))
        && (promotion.channel_ids.is_empty()
            || promotion.channel_ids.iter().any(|v| v == channel_id))
        && (promotion.department_ids.is_empty()
            || promotion.department_ids.contains(&product.department_id))
        && (promotion.category_ids.is_empty()
            || promotion.category_ids.contains(&product.category_id))
        && (promotion.customer_segment_ids.is_empty()
            || promotion
                .customer_segment_ids
                .iter()
                .any(|v| v == segment_id))
}

#[must_use]
pub fn portfolio_weight(product: &Product, variant: &Variant) -> Decimal {
    dec(&variant.demand_weight.to_string()) * family_purchase_frequency(&product.catalog_family)
}

#[must_use]
pub fn expected_units_per_line(product: &Product) -> Decimal {
    match product.catalog_family.as_str() {
        "grocery-dairy" => dec("2.72"),
        "grocery-beverages" | "grocery-snacks" => dec("1.90"),
        "grocery-staples" => dec("1.61"),
        "home-cleaning" | "baby-care" | "baby-feeding" | "health-otc" | "health-vitamins"
        | "stationery-writing" => dec("1.21"),
        _ => dec("1.03"),
    }
}

#[must_use]
pub fn average_active_portfolio_weight<'a>(
    variants: impl IntoIterator<Item = (&'a Product, &'a Variant)>,
    period_start: NaiveDate,
    period_end: NaiveDate,
) -> Decimal {
    let period_days = Decimal::from((period_end - period_start).num_days() + 1);
    let mut weighted_days = Decimal::zero();
    for (product, variant) in variants {
        let active_start = period_start.max(variant.launch_date);
        let active_end = period_end.min(variant.discontinue_date.unwrap_or(period_end));
        if active_end < active_start {
            continue;
        }
        let active_days = Decimal::from((active_end - active_start).num_days() + 1);
        weighted_days = weighted_days + portfolio_weight(product, variant) * active_days;
    }
    dec("0.0001").max(weighted_days / period_days)
}

#[must_use]
pub fn purchase_quantities(
    master_seed: u64,
    event_key: &str,
    product: &Product,
    units: i64,
) -> Vec<i64> {
    if units <= 0 {
        return Vec::new();
    }
    let choices: &[(i64, f64)] = match product.catalog_family.as_str() {
        "grocery-dairy" => &[(1, 0.40), (2, 0.30), (4, 0.16), (6, 0.10), (12, 0.04)],
        "grocery-beverages" | "grocery-snacks" => {
            &[(1, 0.48), (2, 0.30), (3, 0.12), (4, 0.07), (6, 0.03)]
        }
        "grocery-staples" => &[(1, 0.60), (2, 0.27), (3, 0.09), (5, 0.04)],
        "home-cleaning" | "baby-care" | "baby-feeding" | "health-otc" | "health-vitamins"
        | "stationery-writing" => &[(1, 0.82), (2, 0.15), (3, 0.03)],
        _ => &[(1, 0.97), (2, 0.03)],
    };
    let master_seed = master_seed.to_string();
    let mut result = Vec::new();
    let mut remaining = units;
    let mut purchase_index = 0_usize;
    while remaining > 0 {
        let index = purchase_index.to_string();
        let position = fraction(&[&master_seed, "purchase-quantity", event_key, &index]);
        let mut cumulative = 0.0;
        let mut selected = 1;
        for (quantity, share) in choices {
            cumulative += share;
            if position <= cumulative {
                selected = *quantity;
                break;
            }
        }
        let quantity = remaining.min(selected);
        result.push(quantity);
        remaining -= quantity;
        purchase_index += 1;
    }
    result
}

#[must_use]
pub fn split_allocations(allocations: &[Allocation], quantities: &[i64]) -> Vec<Vec<Allocation>> {
    let mut remaining = allocations.to_vec();
    let mut result = Vec::with_capacity(quantities.len());
    let mut allocation_index = 0_usize;
    for quantity in quantities {
        let mut needed = *quantity;
        let mut line_allocations = Vec::new();
        while needed > 0 {
            let allocation = &mut remaining[allocation_index];
            let take = needed.min(allocation.quantity);
            line_allocations.push(Allocation {
                warehouse_id: allocation.warehouse_id.clone(),
                quantity: take,
                priority: allocation.priority,
            });
            allocation.quantity -= take;
            needed -= take;
            if allocation.quantity == 0 {
                allocation_index += 1;
            }
        }
        result.push(line_allocations);
    }
    result
}

fn family_purchase_frequency(family: &str) -> Decimal {
    match family {
        "grocery-dairy" => dec("5.0"),
        "grocery-beverages" => dec("3.8"),
        "grocery-staples" => dec("3.4"),
        "grocery-snacks" => dec("3.0"),
        "home-cleaning" => dec("2.2"),
        "baby-care" => dec("2.0"),
        "baby-feeding" => dec("1.8"),
        "health-otc" => dec("1.7"),
        "health-vitamins" => dec("1.4"),
        "stationery-writing" => dec("1.3"),
        "books-fiction" => dec("0.55"),
        "books-nonfiction" => dec("0.50"),
        "electronics-laptops" => dec("0.55"),
        "electronics-tablets" => dec("0.65"),
        "home-appliances" => dec("0.60"),
        _ => Decimal::one(),
    }
}

fn decimal_value(value: &serde_json::Value) -> Result<Decimal> {
    let raw = value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned);
    Decimal::from_str(&raw).with_context(|| format!("invalid decimal {raw:?}"))
}

fn decimal_from_f64(value: f64) -> Decimal {
    Decimal::from_f64_text(value)
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
}

const fn leap_year(year: i32) -> bool {
    year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)
}

#[cfg(test)]
mod tests {
    use chrono::NaiveDate;
    use std::collections::HashMap;

    use super::{
        SeasonalityEngine, channel_distribution, purchase_quantities, seasonality_raw,
        segment_for_event, tax_amounts, tax_rate_for_line,
    };
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::simulation::assortment;
    use crate::simulation::decimal::PyDecimal as Decimal;

    #[test]
    fn gulf_demand_primitives_match_python_vectors() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let assortment = assortment::build(&config, &catalog).expect("assortment");
        let position = assortment.selected_by_store["mumbai-dist"][0];
        let product = &catalog[position.product_index];
        let variant = &product.variants[position.variant_index];
        assert_eq!(variant.sku, "GLF-ADBLUE-STD-210L");
        let day = NaiveDate::from_ymd_opt(2026, 7, 18).unwrap();
        for (raw_day, expected) in [
            ((2025, 1, 1), "0.766939165475853805"),
            ((2025, 6, 15), "0.475"),
            ((2025, 11, 24), "1.11185719269826507"),
            ((2025, 12, 1), "1.25762726977012942"),
            ((2025, 12, 24), "1.525"),
            ((2025, 12, 25), "1.504208606972093065"),
            ((2025, 12, 31), "0.8690766537939695485"),
        ] {
            assert_eq!(
                seasonality_raw(
                    12,
                    "0.35".parse().unwrap(),
                    NaiveDate::from_ymd_opt(raw_day.0, raw_day.1, raw_day.2).unwrap(),
                )
                .normalized_string(),
                expected,
                "raw seasonality {raw_day:?}"
            );
        }
        let mut seasonality = SeasonalityEngine::default();
        assert_eq!(
            seasonality
                .factor(
                    product.seasonality_peak_month,
                    product.seasonality_strength.to_string().parse().unwrap(),
                    day
                )
                .to_string(),
            "0.9311555752430770621302033697"
        );
        assert_eq!(
            SeasonalityEngine::default()
                .annual_mean(12, "0.35".parse().unwrap(), 2025,)
                .to_string(),
            "0.6011898479450830200487015918"
        );
        assert_eq!(
            SeasonalityEngine::default()
                .factor(
                    12,
                    "0.35".parse().unwrap(),
                    NaiveDate::from_ymd_opt(2025, 12, 24).unwrap(),
                )
                .to_string(),
            "2.536636314156962287241239956"
        );
        let store = &config.scenario.stores[0];
        let market = &config.scenario.markets[0];
        let channel_types = config
            .scenario
            .channels
            .iter()
            .map(|row| (row.channel_id.clone(), row.channel_type.clone()))
            .collect::<HashMap<_, _>>();
        let channels = channel_distribution(
            config.scenario.identity.master_seed,
            store,
            variant,
            &channel_types,
            market,
            day,
            day,
            NaiveDate::from_ymd_opt(2026, 7, 31).unwrap(),
        )
        .expect("channels");
        assert_eq!(
            channels
                .iter()
                .map(|(id, share)| format!("{id}:{share}"))
                .collect::<Vec<_>>(),
            [
                "bazaar-trade:0.4960058310915756699314770536",
                "gulf-marketplace:0.4960058310915756699314770536",
                "gulf-online:0.007988337816848660137045892812",
            ]
        );
        assert_eq!(
            segment_for_event(&config, "gulf-test-event").segment_id,
            "fleet-institutional"
        );
        assert_eq!(
            purchase_quantities(
                config.scenario.identity.master_seed,
                "gulf-test-event",
                product,
                17,
            ),
            [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2]
        );
        assert_eq!(
            tax_rate_for_line(
                market,
                &product.tax_category,
                "999.00".parse().unwrap(),
                day
            )
            .unwrap(),
            "0.18".parse::<Decimal>().unwrap()
        );
        assert_eq!(
            tax_amounts(
                "999.00".parse().unwrap(),
                3,
                "0.28".parse().unwrap(),
                "inclusive",
            ),
            (
                "2341.41".parse().unwrap(),
                "655.59".parse().unwrap(),
                "2997.00".parse().unwrap(),
            )
        );
    }
}
