use std::collections::HashMap;
use std::str::FromStr;

use anyhow::{Context, Result};
use chrono::{Duration, NaiveDate};
use rust_decimal::{Decimal, RoundingStrategy};

use crate::config::{CustomerPopulation as PopulationControls, LoadedConfig, Market};
use crate::deterministic::stable_integer;
use crate::projection::catalog::local_iso_at;

#[derive(Debug, Clone)]
pub struct CustomerRecord {
    pub customer_key: String,
    pub market_id: String,
    pub segment_id: String,
    pub created_at: String,
    pub state: String,
}

pub struct CustomerPopulation<'a> {
    config: &'a LoadedConfig,
    start: NaiveDate,
    end: NaiveDate,
    shares: HashMap<String, Decimal>,
    daily_usage: HashMap<String, u32>,
    usage_day: Option<NaiveDate>,
    active_cache: HashMap<(String, String, usize, i64), bool>,
}

impl<'a> CustomerPopulation<'a> {
    #[must_use]
    pub fn new(config: &'a LoadedConfig) -> Self {
        let total = config
            .scenario
            .customer_segments
            .iter()
            .map(|row| decimal_from_f64(row.share))
            .sum::<Decimal>();
        let shares = config
            .scenario
            .customer_segments
            .iter()
            .map(|row| (row.segment_id.clone(), decimal_from_f64(row.share) / total))
            .collect();
        Self {
            config,
            start: config.scenario.time.start_date,
            end: config.scenario.time.end_date,
            shares,
            daily_usage: HashMap::new(),
            usage_day: None,
            active_cache: HashMap::new(),
        }
    }

    pub fn records(
        &mut self,
        market_ids: impl IntoIterator<Item = String>,
    ) -> Result<Vec<CustomerRecord>> {
        let mut market_ids = market_ids.into_iter().collect::<Vec<_>>();
        market_ids.sort();
        let mut rows = Vec::new();
        for market_id in market_ids {
            let timezone = self.market(&market_id)?.timezone.clone();
            let segments = self.config.scenario.customer_segments.clone();
            for segment in &segments {
                let population =
                    self.segment_population(&market_id, &segment.segment_id, self.end)?;
                for index in 0..population {
                    let key = customer_key(&market_id, &segment.segment_id, index);
                    let created = self.created_date(&market_id, &segment.segment_id, index)?;
                    let active =
                        self.is_active(&market_id, &segment.segment_id, index, self.end)?;
                    rows.push(CustomerRecord {
                        customer_key: key,
                        market_id: market_id.clone(),
                        segment_id: segment.segment_id.clone(),
                        created_at: local_iso_at(created, 0, &timezone)?,
                        state: if active { "ENABLED" } else { "DISABLED" }.to_owned(),
                    });
                }
            }
            rows.push(CustomerRecord {
                customer_key: format!("walk-in:{market_id}"),
                market_id: market_id.clone(),
                segment_id: "walk-in".to_owned(),
                created_at: local_iso_at(self.start, 0, &timezone)?,
                state: "ENABLED".to_owned(),
            });
        }
        Ok(rows)
    }

    pub fn allocate(
        &mut self,
        market_id: &str,
        segment_id: &str,
        day: NaiveDate,
        order_key: &str,
    ) -> Result<(String, String)> {
        let guest_checkout_rate = self.controls(market_id)?.guest_checkout_rate;
        let max_orders_per_customer_per_day =
            self.controls(market_id)?.max_orders_per_customer_per_day;
        let seed = self.config.scenario.identity.master_seed.to_string();
        if fraction(&[&seed, "guest-checkout", order_key]) < guest_checkout_rate {
            return Ok((String::new(), String::new()));
        }
        if self.usage_day != Some(day) {
            self.daily_usage.clear();
            self.usage_day = Some(day);
        }
        let population = self.segment_population(market_id, segment_id, day)?;
        let population_u64 = u64::try_from(population).context("customer population")?;
        let first_index =
            stable_integer(&[&seed, "customer-selection", order_key], population_u64) as usize;
        let mut selected = None;
        for attempt in 0..population.min(128) {
            let candidate = (first_index + attempt * 7919) % population;
            let key = customer_key(market_id, segment_id, candidate);
            if self.created_date(market_id, segment_id, candidate)? > day
                || self.daily_usage.get(&key).copied().unwrap_or(0)
                    >= max_orders_per_customer_per_day
                || !self.is_active(market_id, segment_id, candidate, day)?
            {
                continue;
            }
            selected = Some((key, candidate));
            break;
        }
        if selected.is_none() {
            for attempt in 0..population {
                let candidate = (first_index + attempt) % population;
                let key = customer_key(market_id, segment_id, candidate);
                if self.created_date(market_id, segment_id, candidate)? <= day
                    && self.daily_usage.get(&key).copied().unwrap_or(0)
                        < max_orders_per_customer_per_day
                {
                    selected = Some((key, candidate));
                    break;
                }
            }
        }
        let (key, index) = selected.with_context(|| {
            format!("customer population exhausted for {market_id}/{segment_id} on {day}")
        })?;
        *self.daily_usage.entry(key.clone()).or_default() += 1;
        Ok((
            key,
            self.created_date(market_id, segment_id, index)?.to_string(),
        ))
    }

    pub fn created_date(
        &self,
        market_id: &str,
        segment_id: &str,
        index: usize,
    ) -> Result<NaiveDate> {
        let control = self.controls(market_id)?;
        let opening = self.segment_count(
            usize::try_from(control.opening_registered_customers).context("opening customers")?,
            segment_id,
        )?;
        let key = customer_key(market_id, segment_id, index);
        if index < opening {
            let history_days = u64::from(control.opening_customer_history_years) * 365;
            let seed = self.config.scenario.identity.master_seed.to_string();
            return Ok(self.start
                - Duration::days(stable_integer(
                    &[&seed, "opening-customer-created", &key],
                    history_days.max(1),
                ) as i64));
        }
        let acquisition_index = index - opening;
        let segment_annual = self
            .segment_count(
                usize::try_from(control.annual_new_customers).context("annual customers")?,
                segment_id,
            )?
            .max(1);
        let days = (Decimal::from(acquisition_index as u64) * dec("365.2425")
            / Decimal::from(segment_annual as u64))
        .trunc()
        .to_string()
        .parse::<i64>()
        .context("acquisition date")?;
        Ok(self.start + Duration::days(days))
    }

    fn is_active(
        &mut self,
        market_id: &str,
        segment_id: &str,
        index: usize,
        day: NaiveDate,
    ) -> Result<bool> {
        let created = self.created_date(market_id, segment_id, index)?;
        let age_year = ((day - created).num_days() / 365).max(0);
        let cache_key = (market_id.to_owned(), segment_id.to_owned(), index, age_year);
        if let Some(value) = self.active_cache.get(&cache_key) {
            return Ok(*value);
        }
        let control = self.controls(market_id)?;
        let key = customer_key(market_id, segment_id, index);
        let seed = self.config.scenario.identity.master_seed.to_string();
        let mut active = true;
        for lifecycle_year in 1..=age_year {
            let year = lifecycle_year.to_string();
            if active {
                active =
                    fraction(&[&seed, "customer-churn", &key, &year]) >= control.annual_churn_rate;
            } else {
                active = fraction(&[&seed, "customer-reactivation", &key, &year])
                    < control.annual_reactivation_rate;
            }
        }
        if self.active_cache.len() >= 50_000 {
            // Cache eviction cannot affect logical output; values are content-derived.
            self.active_cache.clear();
        }
        self.active_cache.insert(cache_key, active);
        Ok(active)
    }

    fn population_total(&self, market_id: &str, day: NaiveDate) -> Result<usize> {
        let control = self.controls(market_id)?;
        let elapsed = (day - self.start).num_days().max(0) + 1;
        let acquired = (Decimal::from(control.annual_new_customers) * Decimal::from(elapsed)
            / dec("365.2425"))
        .trunc()
        .to_string()
        .parse::<u64>()
        .context("acquired customer count")?;
        usize::try_from(control.opening_registered_customers + acquired).context("customer total")
    }

    fn segment_population(
        &self,
        market_id: &str,
        segment_id: &str,
        day: NaiveDate,
    ) -> Result<usize> {
        Ok(self
            .segment_count(self.population_total(market_id, day)?, segment_id)?
            .max(1))
    }

    fn segment_count(&self, total: usize, segment_id: &str) -> Result<usize> {
        let index = self
            .config
            .scenario
            .customer_segments
            .iter()
            .position(|row| row.segment_id == segment_id)
            .with_context(|| format!("unknown customer segment {segment_id}"))?;
        let allocated_before = self.config.scenario.customer_segments[..index]
            .iter()
            .map(|row| {
                (Decimal::from(total as u64) * self.shares[&row.segment_id])
                    .round_dp_with_strategy(0, RoundingStrategy::ToNegativeInfinity)
                    .to_string()
                    .parse::<usize>()
                    .expect("customer segment allocation")
            })
            .sum::<usize>();
        if index == self.config.scenario.customer_segments.len() - 1 {
            Ok(total - allocated_before)
        } else {
            Ok((Decimal::from(total as u64) * self.shares[segment_id])
                .round_dp_with_strategy(0, RoundingStrategy::ToNegativeInfinity)
                .to_string()
                .parse::<usize>()
                .context("customer segment count")?)
        }
    }

    fn controls(&self, market_id: &str) -> Result<&PopulationControls> {
        Ok(&self.market(market_id)?.customer_population)
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

fn customer_key(market_id: &str, segment_id: &str, index: usize) -> String {
    format!("customer:{market_id}:{segment_id}:{index:09}")
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

fn decimal_from_f64(value: f64) -> Decimal {
    Decimal::from_str(&value.to_string()).expect("finite customer float")
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
}
