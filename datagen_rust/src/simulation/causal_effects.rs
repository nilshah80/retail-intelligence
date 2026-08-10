use std::collections::BTreeSet;

use anyhow::{Context, Result};
use chrono::NaiveDate;

use crate::config::LoadedConfig;
use crate::simulation::decimal::PyDecimal as Decimal;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExternalEffect {
    pub event_ids: Vec<String>,
    pub pandemic_ids: Vec<String>,
    pub phase_ids: Vec<String>,
    pub effect_modes: Vec<String>,
    pub demand: Decimal,
    pub traffic: Decimal,
    pub cost: Decimal,
    pub lead_time: Decimal,
    pub inventory_loss: Decimal,
}

impl Default for ExternalEffect {
    fn default() -> Self {
        Self {
            event_ids: Vec::new(),
            pandemic_ids: Vec::new(),
            phase_ids: Vec::new(),
            effect_modes: Vec::new(),
            demand: Decimal::one(),
            traffic: Decimal::one(),
            cost: Decimal::one(),
            lead_time: Decimal::one(),
            inventory_loss: Decimal::zero(),
        }
    }
}

#[allow(clippy::too_many_arguments)]
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
        result.event_ids.push(event.event_id.clone());
        result.demand = result.demand
            * shaped(
                Decimal::from_f64_text(event.demand_multiplier),
                event.start_date,
                event.end_date,
                day,
                &event.recovery_shape,
            );
        result.traffic = result.traffic
            * shaped(
                Decimal::from_f64_text(event.traffic_multiplier),
                event.start_date,
                event.end_date,
                day,
                &event.recovery_shape,
            );
        result.cost = result.cost
            * shaped(
                Decimal::from_f64_text(event.cost_multiplier),
                event.start_date,
                event.end_date,
                day,
                &event.recovery_shape,
            );
        result.lead_time = result.lead_time
            * shaped(
                Decimal::from_f64_text(event.lead_time_multiplier),
                event.start_date,
                event.end_date,
                day,
                &event.recovery_shape,
            );
        result.inventory_loss = result
            .inventory_loss
            .max(Decimal::from_f64_text(event.inventory_loss_pct));
    }
    result
}

#[allow(clippy::too_many_arguments)]
pub fn pandemic_effect(
    config: &LoadedConfig,
    day: NaiveDate,
    market_id: &str,
    department_id: &str,
    category_id: &str,
    catalog_family: &str,
    channel_type: &str,
) -> Result<ExternalEffect> {
    let mut result = ExternalEffect::default();
    for pandemic in &config.scenario.pandemics {
        if !pandemic["marketIds"]
            .as_array()
            .into_iter()
            .flatten()
            .any(|value| value.as_str() == Some(market_id))
        {
            continue;
        }
        let start = date_value(&pandemic["startDate"])?;
        let end = date_value(&pandemic["endDate"])?;
        if day < start || day > end {
            continue;
        }
        for phase in pandemic["phases"].as_array().into_iter().flatten() {
            let phase_start = date_value(&phase["startDate"])?;
            let phase_end = date_value(&phase["endDate"])?;
            if day < phase_start || day > phase_end {
                continue;
            }
            let shape = phase["recoveryShape"]
                .as_str()
                .context("pandemic recoveryShape")?;
            result.pandemic_ids.push(
                pandemic["pandemicId"]
                    .as_str()
                    .context("pandemicId")?
                    .to_owned(),
            );
            result.phase_ids.push(
                phase["phaseId"]
                    .as_str()
                    .context("pandemic phaseId")?
                    .to_owned(),
            );
            result.effect_modes.push(
                pandemic["effectMode"]
                    .as_str()
                    .context("pandemic effectMode")?
                    .to_owned(),
            );
            let mut demand = decimal_value(&phase["demandMultiplier"])?;
            if let Some(value) = phase["departmentMultipliers"].get(department_id) {
                demand = demand * decimal_value(value)?;
            }
            if let Some(value) = phase["categoryMultipliers"].get(category_id) {
                demand = demand * decimal_value(value)?;
            }
            if let Some(value) = phase["catalogFamilyMultipliers"].get(catalog_family) {
                demand = demand * decimal_value(value)?;
            }
            result.demand = result.demand * shaped(demand, phase_start, phase_end, day, shape);
            let mut traffic = decimal_value(&phase["trafficMultiplier"])?;
            if let Some(value) = phase["channelTypeMultipliers"].get(channel_type) {
                traffic = traffic * decimal_value(value)?;
            }
            result.traffic = result.traffic * shaped(traffic, phase_start, phase_end, day, shape);
            result.cost = result.cost
                * shaped(
                    decimal_value(&phase["costMultiplier"])?,
                    phase_start,
                    phase_end,
                    day,
                    shape,
                );
            result.lead_time = result.lead_time
                * shaped(
                    decimal_value(&phase["leadTimeMultiplier"])?,
                    phase_start,
                    phase_end,
                    day,
                    shape,
                );
            result.inventory_loss = result
                .inventory_loss
                .max(decimal_value(&phase["inventoryLossPct"])?);
        }
    }
    sort_unique(&mut result.pandemic_ids);
    sort_unique(&mut result.phase_ids);
    sort_unique(&mut result.effect_modes);
    Ok(result)
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
        "linear" => Decimal::one() - progress,
        "ramp" => progress,
        "triangle" => Decimal::one() - (Decimal::from(2_u32) * progress - Decimal::one()).abs(),
        _ => panic!("unsupported recovery shape {shape:?}"),
    };
    Decimal::one() + (target - Decimal::one()) * weight
}

fn sort_unique(values: &mut Vec<String>) {
    *values = values
        .drain(..)
        .collect::<BTreeSet<_>>()
        .into_iter()
        .collect();
}

fn date_value(value: &serde_json::Value) -> Result<NaiveDate> {
    NaiveDate::parse_from_str(value.as_str().context("date value")?, "%Y-%m-%d")
        .context("pandemic date")
}

fn decimal_value(value: &serde_json::Value) -> Result<Decimal> {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
        .parse()
        .context("pandemic decimal")
}

#[cfg(test)]
mod tests {
    use chrono::NaiveDate;

    use super::{event_effect, pandemic_effect};
    use crate::config::LoadedConfig;

    #[test]
    fn gulf_kharif_event_matches_python_scale_and_value() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let day = NaiveDate::from_ymd_opt(2026, 7, 18).unwrap();
        let effect = event_effect(
            &config,
            day,
            "gulf-india",
            "mumbai-dist",
            "",
            "gulf-tractor",
            "bazaar-trade",
        );
        assert_eq!(effect.event_ids, ["gulf-kharif-sowing-2026"]);
        assert_eq!(effect.demand.to_string(), "1.4988");
        assert_eq!(effect.traffic.to_string(), "1.000");
        assert_eq!((&effect.demand * &effect.traffic).to_string(), "1.4988000");
        let pandemic = pandemic_effect(
            &config,
            day,
            "gulf-india",
            "",
            "gulf-tractor",
            "lubricants-tractor",
            "store",
        )
        .expect("pandemic");
        assert!(pandemic.pandemic_ids.is_empty());
        assert_eq!(pandemic.demand.to_string(), "1");
    }
}
