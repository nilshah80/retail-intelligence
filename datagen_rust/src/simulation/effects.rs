use chrono::NaiveDate;
use rust_decimal::Decimal;

use crate::config::LoadedConfig;

#[derive(Debug, Clone)]
pub struct ExternalEffect {
    pub ids: Vec<String>,
    pub demand: Decimal,
    pub traffic: Decimal,
    pub cost: Decimal,
    pub lead_time: Decimal,
    pub inventory_loss: Decimal,
}

impl Default for ExternalEffect {
    fn default() -> Self {
        Self {
            ids: Vec::new(),
            demand: Decimal::ONE,
            traffic: Decimal::ONE,
            cost: Decimal::ONE,
            lead_time: Decimal::ONE,
            inventory_loss: Decimal::ZERO,
        }
    }
}

#[must_use]
pub fn event_effect(
    config: &LoadedConfig,
    day: NaiveDate,
    market_id: &str,
    store_id: &str,
    department_id: &str,
    category_id: &str,
    channel_id: &str,
) -> ExternalEffect {
    let mut result = ExternalEffect::default();
    for event in &config.scenario.events {
        if event.market_id != market_id || day < event.start_date || day > event.end_date {
            continue;
        }
        if !event.store_id.is_empty() && event.store_id != store_id {
            continue;
        }
        if !event.department_ids.is_empty()
            && !event
                .department_ids
                .iter()
                .any(|value| value == department_id)
        {
            continue;
        }
        if !event.category_ids.is_empty()
            && !event.category_ids.iter().any(|value| value == category_id)
        {
            continue;
        }
        if !event.channel_ids.is_empty()
            && !event.channel_ids.iter().any(|value| value == channel_id)
        {
            continue;
        }
        result.ids.push(event.event_id.clone());
        result.demand *= shaped(
            decimal_from_f64(event.demand_multiplier),
            event.start_date,
            event.end_date,
            day,
            &event.recovery_shape,
        );
        result.traffic *= shaped(
            decimal_from_f64(event.traffic_multiplier),
            event.start_date,
            event.end_date,
            day,
            &event.recovery_shape,
        );
        result.cost *= shaped(
            decimal_from_f64(event.cost_multiplier),
            event.start_date,
            event.end_date,
            day,
            &event.recovery_shape,
        );
        result.lead_time *= shaped(
            decimal_from_f64(event.lead_time_multiplier),
            event.start_date,
            event.end_date,
            day,
            &event.recovery_shape,
        );
        result.inventory_loss = result
            .inventory_loss
            .max(decimal_from_f64(event.inventory_loss_pct));
    }
    result
}

#[must_use]
pub fn pandemic_cost_effect(
    config: &LoadedConfig,
    day: NaiveDate,
    market_id: &str,
    department_id: &str,
    category_id: &str,
    catalog_family: &str,
) -> Decimal {
    let mut result = Decimal::ONE;
    for pandemic in &config.scenario.pandemics {
        let markets = pandemic["marketIds"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        if !markets
            .iter()
            .any(|value| value.as_str() == Some(market_id))
        {
            continue;
        }
        let start = parse_date(&pandemic["startDate"]);
        let end = parse_date(&pandemic["endDate"]);
        if day < start || day > end {
            continue;
        }
        for phase in pandemic["phases"].as_array().into_iter().flatten() {
            let phase_start = parse_date(&phase["startDate"]);
            let phase_end = parse_date(&phase["endDate"]);
            if day < phase_start || day > phase_end {
                continue;
            }
            // Cost currently has no merchandise-specific override in v13. Demand overrides are
            // handled by the causal simulation port.
            let _ = (department_id, category_id, catalog_family);
            result *= shaped(
                decimal_value(&phase["costMultiplier"]),
                phase_start,
                phase_end,
                day,
                phase["recoveryShape"].as_str().unwrap_or("step"),
            );
        }
    }
    result
}

#[must_use]
pub fn shaped(
    target: Decimal,
    start: NaiveDate,
    end: NaiveDate,
    day: NaiveDate,
    shape: &str,
) -> Decimal {
    if shape == "step" || end <= start {
        return target;
    }
    let progress =
        Decimal::from((day - start).num_days()) / Decimal::from((end - start).num_days());
    let weight = match shape {
        "linear" => Decimal::ONE - progress,
        "ramp" => progress,
        "triangle" => Decimal::ONE - (Decimal::from(2_u32) * progress - Decimal::ONE).abs(),
        _ => panic!("unsupported recovery shape {shape}"),
    };
    Decimal::ONE + (target - Decimal::ONE) * weight
}

fn parse_date(value: &serde_json::Value) -> NaiveDate {
    NaiveDate::parse_from_str(value.as_str().unwrap_or_default(), "%Y-%m-%d")
        .expect("validated pandemic date")
}

fn decimal_value(value: &serde_json::Value) -> Decimal {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
        .parse()
        .expect("validated effect decimal")
}

fn decimal_from_f64(value: f64) -> Decimal {
    value.to_string().parse().expect("finite effect float")
}
