use std::str::FromStr;

use chrono::{Duration, NaiveDate};

use crate::catalog::{Product, Variant};
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::lifecycle::offer_id;

#[derive(Debug, Clone)]
pub struct LifecycleEffect {
    pub launch_profile: String,
    pub launch_factor: Decimal,
    pub predecessor_factor: Decimal,
    pub substitution_factor: Decimal,
    pub offer_id: String,
    pub offer_type: String,
    pub offer_discount_pct: Decimal,
    pub offer_demand_factor: Decimal,
}

/// Python-Decimal-compatible lifecycle factors used by the causal demand lane.
/// The fixed-scale pricing projection has a separate `rust_decimal` facade.
#[must_use]
pub fn adjustment(
    product: &Product,
    variant: &Variant,
    day: NaiveDate,
    default_ramp_days: u32,
) -> LifecycleEffect {
    let age_days = (day - variant.launch_date).num_days().max(0);
    let profile = product.launch_profile.as_str();
    let controls = &product.lifecycle;
    let launch_factor = if profile == "flagship-spike-decay" {
        let spike_days = controls["launchSpikeDays"].as_i64().unwrap_or(14);
        let settle_days = controls["launchSettleDays"].as_i64().unwrap_or(76);
        let spike = decimal_value(&controls["launchSpikeMultiplier"]);
        if age_days <= spike_days {
            &spike
                - (&spike - dec("1.8")) * Decimal::from(age_days) / Decimal::from(spike_days.max(1))
        } else if age_days <= spike_days + settle_days {
            let progress = Decimal::from(age_days - spike_days) / Decimal::from(settle_days.max(1));
            Decimal::one() + dec("0.8") * (Decimal::one() - progress)
        } else {
            Decimal::one()
        }
    } else if profile == "evergreen" {
        Decimal::one()
    } else {
        Decimal::from_f64_text(
            (age_days as f64 / f64::from(default_ramp_days.max(1))).clamp(0.15, 1.0),
        )
    };

    let mut predecessor_factor = Decimal::one();
    let mut substitution_factor = Decimal::one();
    let mut discount = Decimal::zero();
    let mut current_offer_id = String::new();
    let mut current_offer_type = String::new();
    let mut offer_demand_factor = Decimal::one();
    if let Some(successor_launch) = product.successor_launch_date {
        let anticipation_days = controls["preLaunchAnticipationDays"].as_i64().unwrap_or(45);
        if successor_launch - Duration::days(anticipation_days) <= day && day < successor_launch {
            let progress = Decimal::from(
                (day - (successor_launch - Duration::days(anticipation_days))).num_days(),
            ) / Decimal::from(anticipation_days.max(1));
            let floor = decimal_value(&controls["preLaunchDemandMultiplier"]);
            predecessor_factor = Decimal::one() - (Decimal::one() - floor) * progress;
        } else if day >= successor_launch {
            let discontinue = product.discontinue_date.unwrap_or_else(|| {
                successor_launch
                    + Duration::days(30 * controls["runoutMonths"].as_i64().unwrap_or(18))
            });
            let total_runout_days = (discontinue - successor_launch).num_days().max(1);
            let elapsed = (day - successor_launch).num_days().max(0);
            let progress =
                (Decimal::from(elapsed) / Decimal::from(total_runout_days)).min(Decimal::one());
            predecessor_factor = dec("0.04").max(
                decimal_value(&controls["runoutDemandMultiplier"])
                    * (Decimal::one() - dec("0.85") * progress),
            );
            let fire_start =
                discontinue - Duration::days(controls["fireSaleFinalDays"].as_i64().unwrap_or(30));
            let clearance_start = successor_launch
                + Duration::days(
                    controls["clearanceStartDaysAfterSuccessor"]
                        .as_i64()
                        .unwrap_or(120),
                );
            if day >= fire_start {
                current_offer_type = "fire-sale".to_owned();
                discount = decimal_value(&controls["fireSaleDiscountPct"]);
                offer_demand_factor = decimal_value(&controls["fireSaleDemandMultiplier"]);
            } else if day >= clearance_start {
                current_offer_type = "clearance".to_owned();
                discount = decimal_value(&controls["clearanceDiscountPct"]);
                offer_demand_factor = decimal_value(&controls["clearanceDemandMultiplier"]);
            } else {
                current_offer_type = "runout-markdown".to_owned();
                discount = decimal_value(&controls["runoutMarkdownPct"]);
                offer_demand_factor = decimal_value(&controls["runoutMarkdownDemandMultiplier"]);
            }
            current_offer_id = offer_id(&current_offer_type, &product.product_code);
        }
    }

    if !product.successor_of_product_code.is_empty() && profile == "flagship-spike-decay" {
        let transfer_days = (controls["launchSpikeDays"].as_i64().unwrap_or(14)
            + controls["launchSettleDays"].as_i64().unwrap_or(76))
        .max(1);
        let remaining = (1.0 - age_days as f64 / transfer_days as f64).max(0.0);
        substitution_factor = substitution_factor
            + decimal_value(&controls["substitutionRate"]) * Decimal::from_f64_text(remaining);
    }

    LifecycleEffect {
        launch_profile: profile.to_owned(),
        launch_factor,
        predecessor_factor,
        substitution_factor,
        offer_id: current_offer_id,
        offer_type: current_offer_type,
        offer_discount_pct: discount,
        offer_demand_factor,
    }
}

fn decimal_value(value: &serde_json::Value) -> Decimal {
    let raw = value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned);
    Decimal::from_str(&raw).expect("validated lifecycle decimal")
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
}
