use std::collections::HashMap;
use std::str::FromStr;

use anyhow::{Context, Result};
use bigdecimal::RoundingMode;
use chrono::{Datelike, NaiveDate};
use rust_decimal::{Decimal, RoundingStrategy};

use crate::catalog::{Product, Variant};
use crate::config::Market;
use crate::deterministic::{round_half_even_f64, stable_integer};
use crate::simulation::decimal::PyDecimal;
use crate::simulation::lifecycle;

#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct ScheduleKey {
    profile: String,
    events: usize,
    sku: String,
    year: i32,
    anchor_year: i32,
}

#[derive(Debug, Default)]
pub struct PriceEngine {
    schedules: HashMap<ScheduleKey, (Vec<u32>, Vec<Decimal>)>,
}

impl PriceEngine {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn extract_price(
        &mut self,
        product: &Product,
        variant: &Variant,
        market: &Market,
        start: NaiveDate,
        end: NaiveDate,
    ) -> Result<Decimal> {
        let effective_day = variant.discontinue_date.map_or(end, |day| day.min(end));
        self.effective_list_price(
            product,
            variant,
            market,
            effective_day,
            start,
            end,
            Decimal::ONE,
        )
        .map(|row| row.0)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn effective_list_price(
        &mut self,
        product: &Product,
        variant: &Variant,
        market: &Market,
        day: NaiveDate,
        start: NaiveDate,
        end: NaiveDate,
        cost_multiplier: Decimal,
    ) -> Result<(Decimal, String)> {
        let pricing_day = product
            .successor_launch_date
            .map_or(day, |value| day.min(value));
        let mut price = self.price_for_day(
            variant.base_price,
            market,
            &variant.sku,
            pricing_day,
            start,
            end,
            variant.launch_date,
        )?;
        let mut phase = String::new();
        if product.successor_launch_date.is_some() {
            let effect =
                lifecycle::adjustment(product, variant, day, market.demand.new_product_ramp_days);
            if !effect.offer_id.is_empty() {
                let exact_cost_multiplier = PyDecimal::from_str(&cost_multiplier.to_string())
                    .context("lifecycle cost multiplier")?;
                price = self.promotional_price(
                    product,
                    variant,
                    market,
                    price,
                    day,
                    start,
                    end,
                    effect.offer_discount_pct,
                    &effect.offer_id,
                    &effect.offer_type,
                    &exact_cost_multiplier,
                )?;
                phase = effect.offer_type;
            }
        }
        Ok((
            quantize(price, 2, RoundingStrategy::MidpointNearestEven),
            phase,
        ))
    }

    #[allow(clippy::too_many_arguments)]
    pub fn price_for_day(
        &mut self,
        base: Decimal,
        market: &Market,
        sku: &str,
        day: NaiveDate,
        start: NaiveDate,
        _end: NaiveDate,
        inflation_anchor: NaiveDate,
    ) -> Result<Decimal> {
        let profile = value_str(&market.price_dynamics, "profile");
        let events = market.price_dynamics["priceChangeEventsPerSkuPerYear"]
            .as_u64()
            .context("priceChangeEventsPerSkuPerYear")? as usize;
        let (event_days, adjustments) =
            self.schedule(profile, events, sku, day.year(), inflation_anchor.year());
        let bucket = event_days
            .partition_point(|value| *value <= day.ordinal())
            .saturating_sub(1);
        let years = (day.year() - inflation_anchor.year()).max(0);
        let inflation_rate = market.price_dynamics["annualInflationRate"]
            .as_f64()
            .context("annualInflationRate")?;
        let inflation = decimal_from_f64((1.0 + inflation_rate).powf(f64::from(years)));
        let nominal = base * inflation * (Decimal::ONE + adjustments[bucket]);
        self.retail_price(
            nominal,
            market,
            &[sku.to_owned(), day.year().to_string(), bucket.to_string()],
        )
        .or_else(|error| {
            let _ = start;
            Err(error)
        })
    }

    fn schedule(
        &mut self,
        profile: &str,
        events: usize,
        sku: &str,
        year: i32,
        anchor_year: i32,
    ) -> (Vec<u32>, Vec<Decimal>) {
        let key = ScheduleKey {
            profile: profile.to_owned(),
            events,
            sku: sku.to_owned(),
            year,
            anchor_year,
        };
        if let Some(value) = self.schedules.get(&key) {
            return value.clone();
        }
        let year_days = if is_leap(year) { 366_u32 } else { 365_u32 };
        let value = if events == 0 || profile == "stable" {
            (vec![1], vec![Decimal::ZERO])
        } else {
            let interval = f64::from(year_days) / events as f64;
            let mut event_days = vec![1_u32];
            let mut adjustment = if year <= anchor_year {
                Decimal::ZERO
            } else {
                self.schedule(profile, events, sku, year - 1, anchor_year)
                    .1
                    .last()
                    .copied()
                    .unwrap_or_default()
            };
            let mut adjustments = vec![adjustment];
            let mut prior_day = 1_i64;
            for event_index in 0..events {
                let centre = round_half_even_f64((event_index as f64 + 0.5) * interval) as i64;
                let jitter_span = round_half_even_f64(interval * 0.20).max(1.0) as i64;
                let year_text = year.to_string();
                let event_text = event_index.to_string();
                let jitter = stable_integer(
                    &["price-event-day", sku, &year_text, &event_text],
                    (2 * jitter_span + 1) as u64,
                ) as i64
                    - jitter_span;
                let event_day = (centre + jitter)
                    .max(prior_day + 1)
                    .min(i64::from(year_days));
                prior_day = event_day;
                let draw = stable_integer(&["price-event-step", sku, &year_text, &event_text], 100);
                if profile == "response-rich" {
                    let threshold = if adjustment >= dec("0.08") {
                        70
                    } else if adjustment <= dec("-0.04") {
                        20
                    } else {
                        46
                    };
                    let step = if draw < threshold / 3 {
                        dec("-0.025")
                    } else if draw < threshold {
                        dec("-0.0125")
                    } else if draw < threshold + 30 {
                        dec("0.010")
                    } else if draw < threshold + 48 {
                        dec("0.020")
                    } else {
                        dec("0.030")
                    };
                    adjustment = (adjustment + step).clamp(dec("-0.08"), dec("0.12"));
                } else {
                    let threshold = if adjustment >= dec("0.04") {
                        65
                    } else if adjustment <= dec("-0.02") {
                        30
                    } else {
                        48
                    };
                    let step = if draw < threshold {
                        dec("-0.010")
                    } else {
                        dec("0.010")
                    };
                    adjustment = (adjustment + step).clamp(dec("-0.04"), dec("0.06"));
                }
                event_days.push(event_day as u32);
                adjustments.push(adjustment);
            }
            (event_days, adjustments)
        };
        self.schedules.insert(key, value.clone());
        value
    }

    #[allow(clippy::too_many_arguments)]
    pub fn promotional_price(
        &mut self,
        _product: &Product,
        variant: &Variant,
        market: &Market,
        regular_price: Decimal,
        day: NaiveDate,
        start: NaiveDate,
        end: NaiveDate,
        discount_pct: Decimal,
        promotion_id: &str,
        promotion_type: &str,
        cost_multiplier: &PyDecimal,
    ) -> Result<Decimal> {
        let mut discounted = regular_price * (Decimal::ONE - discount_pct);
        let cost_floor = if promotion_type == "fire-sale" {
            None
        } else {
            let cost = self.price_for_day(
                variant.base_cost,
                market,
                &format!("{}:cost", variant.sku),
                day,
                start,
                end,
                variant.launch_date,
            )?;
            let exact_cost = PyDecimal::from_str(&cost.to_string())? * cost_multiplier;
            let exact_floor =
                (exact_cost * PyDecimal::from_str("1.02")?).quantize(2, RoundingMode::Ceiling);
            let floor =
                Decimal::from_str(&exact_floor.to_string()).context("promotional cost floor")?;
            discounted = discounted.max(floor);
            Some(floor)
        };
        let retail = self.retail_price(
            discounted,
            market,
            &[
                variant.sku.clone(),
                "promotion".to_owned(),
                promotion_id.to_owned(),
            ],
        )?;
        Ok(cost_floor.map_or(retail, |floor| retail.max(floor)))
    }

    fn retail_price(&self, value: Decimal, market: &Market, state: &[String]) -> Result<Decimal> {
        let adherence = market.price_dynamics["priceEndingAdherence"]
            .as_f64()
            .context("priceEndingAdherence")?;
        let mut parts = Vec::with_capacity(state.len() + 2);
        parts.push("price-ending-adherence");
        parts.push(market.market_id.as_str());
        parts.extend(state.iter().map(String::as_str));
        if stable_integer(&parts, 1_000_000) as f64 / 1_000_000.0 < adherence {
            snap_price(value, market)
        } else {
            Ok(quantize(value, 2, RoundingStrategy::MidpointNearestEven))
        }
    }
}

fn snap_price(value: Decimal, market: &Market) -> Result<Decimal> {
    let endings = market.locale_pack["currency"]["priceEndings"]
        .as_array()
        .context("currency.priceEndings")?;
    let whole = value
        .trunc()
        .to_string()
        .parse::<i64>()
        .context("price major")?;
    let mut candidates = Vec::new();
    for major in 0_i64.max(whole - 1)..=(whole + 1) {
        for ending in endings {
            let raw = ending
                .as_str()
                .map_or_else(|| ending.to_string(), str::to_owned);
            let candidate = Decimal::from(major) + dec(&raw) / Decimal::from(100_u32);
            if candidate > Decimal::ZERO {
                candidates.push(candidate);
            }
        }
    }
    let selected = candidates
        .into_iter()
        .min_by_key(|candidate| ((candidate - value).abs(), *candidate))
        .context("no positive price ending")?;
    Ok(quantize(selected, 2, RoundingStrategy::MidpointNearestEven))
}

fn quantize(value: Decimal, scale: u32, strategy: RoundingStrategy) -> Decimal {
    let mut result = value.round_dp_with_strategy(scale, strategy);
    result.rescale(scale);
    result
}

fn decimal_from_f64(value: f64) -> Decimal {
    value.to_string().parse().expect("finite pricing float")
}

fn dec(value: &str) -> Decimal {
    value.parse().expect("constant decimal")
}

fn value_str<'a>(value: &'a serde_json::Value, key: &str) -> &'a str {
    value
        .get(key)
        .and_then(serde_json::Value::as_str)
        .unwrap_or("")
}

fn is_leap(year: i32) -> bool {
    (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
}

#[cfg(test)]
mod tests {
    use std::str::FromStr;

    use chrono::NaiveDate;
    use rust_decimal::Decimal;

    use super::PriceEngine;
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::simulation::decimal::PyDecimal;

    #[test]
    fn gulf_extract_prices_match_python_vectors() {
        let config =
            LoadedConfig::load("../datagen/configs/gulf-oil-india-ten-year.yaml").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let market = &config.scenario.markets[0];
        let mut engine = PriceEngine::new();
        for (product_index, variant_index, expected) in [
            (0, 0, "705.99"),
            (0, 3, "3058.84"),
            (10, 0, "3877.55"),
            (10, 3, "141404.00"),
            (72, 0, "351.21"),
            (72, 3, "1850.99"),
        ] {
            let product = &catalog[product_index];
            let actual = engine
                .extract_price(
                    product,
                    &product.variants[variant_index],
                    market,
                    config.scenario.time.start_date,
                    config.scenario.time.end_date,
                )
                .expect("price");
            assert_eq!(actual.to_string(), expected);
        }
    }

    #[test]
    fn promotion_cost_floor_keeps_python_decimal_ceiling_result() {
        let config = LoadedConfig::load("configs/gulf-oil-india-ten-year.yaml").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let market = &config.scenario.markets[0];
        let product = catalog
            .iter()
            .find(|product| {
                product
                    .variants
                    .iter()
                    .any(|variant| variant.sku == "GLF-FORMULA-G-5W30-1L")
            })
            .expect("Formula G product");
        let variant = product
            .variants
            .iter()
            .find(|variant| variant.sku == "GLF-FORMULA-G-5W30-1L")
            .expect("Formula G variant");
        let day = NaiveDate::from_ymd_opt(2022, 5, 25).unwrap();
        let mut engine = PriceEngine::new();
        let regular = engine
            .price_for_day(
                variant.base_price,
                market,
                &variant.sku,
                day,
                config.scenario.time.start_date,
                config.scenario.time.end_date,
                variant.launch_date,
            )
            .expect("regular price");
        assert_eq!(regular.to_string(), "1018.49");
        let promotional = engine
            .promotional_price(
                product,
                variant,
                market,
                regular,
                day,
                config.scenario.time.start_date,
                config.scenario.time.end_date,
                Decimal::from_str("0.07").unwrap(),
                "gulf-monsoon-stocking-2022",
                "campaign",
                &PyDecimal::from_str("1.314814814814814814814814815").unwrap(),
            )
            .expect("promotional price");
        assert_eq!(promotional.to_string(), "1013.88");
    }
}
