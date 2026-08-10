use chrono::{Duration, NaiveDate};
use rust_decimal::Decimal;

use crate::catalog::{Product, Variant};

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

#[must_use]
pub fn offer_id(offer_type: &str, product_code: &str) -> String {
    format!("{offer_type}-{}", safe_id(product_code))
}

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
            spike
                - (spike - dec("1.8")) * Decimal::from(age_days) / Decimal::from(spike_days.max(1))
        } else if age_days <= spike_days + settle_days {
            let progress = Decimal::from(age_days - spike_days) / Decimal::from(settle_days.max(1));
            Decimal::ONE + dec("0.8") * (Decimal::ONE - progress)
        } else {
            Decimal::ONE
        }
    } else if profile == "evergreen" {
        Decimal::ONE
    } else {
        decimal_from_f64((age_days as f64 / f64::from(default_ramp_days.max(1))).clamp(0.15, 1.0))
    };

    let mut predecessor_factor = Decimal::ONE;
    let mut substitution_factor = Decimal::ONE;
    let mut discount = Decimal::ZERO;
    let mut current_offer_id = String::new();
    let mut offer_type = String::new();
    let mut offer_demand_factor = Decimal::ONE;

    if let Some(successor_launch) = product.successor_launch_date {
        let anticipation_days = controls["preLaunchAnticipationDays"].as_i64().unwrap_or(45);
        if successor_launch - Duration::days(anticipation_days) <= day && day < successor_launch {
            let progress = Decimal::from(
                (day - (successor_launch - Duration::days(anticipation_days))).num_days(),
            ) / Decimal::from(anticipation_days.max(1));
            let floor = decimal_value(&controls["preLaunchDemandMultiplier"]);
            predecessor_factor = Decimal::ONE - (Decimal::ONE - floor) * progress;
        } else if day >= successor_launch {
            let discontinue = product.discontinue_date.unwrap_or_else(|| {
                successor_launch
                    + Duration::days(30 * controls["runoutMonths"].as_i64().unwrap_or(18))
            });
            let total_runout_days = (discontinue - successor_launch).num_days().max(1);
            let elapsed = (day - successor_launch).num_days().max(0);
            let progress =
                (Decimal::from(elapsed) / Decimal::from(total_runout_days)).min(Decimal::ONE);
            let initial_tail = decimal_value(&controls["runoutDemandMultiplier"]);
            predecessor_factor =
                dec("0.04").max(initial_tail * (Decimal::ONE - dec("0.85") * progress));
            let fire_start =
                discontinue - Duration::days(controls["fireSaleFinalDays"].as_i64().unwrap_or(30));
            let clearance_start = successor_launch
                + Duration::days(
                    controls["clearanceStartDaysAfterSuccessor"]
                        .as_i64()
                        .unwrap_or(120),
                );
            if day >= fire_start {
                offer_type = "fire-sale".to_owned();
                discount = decimal_value(&controls["fireSaleDiscountPct"]);
                offer_demand_factor = decimal_value(&controls["fireSaleDemandMultiplier"]);
            } else if day >= clearance_start {
                offer_type = "clearance".to_owned();
                discount = decimal_value(&controls["clearanceDiscountPct"]);
                offer_demand_factor = decimal_value(&controls["clearanceDemandMultiplier"]);
            } else {
                offer_type = "runout-markdown".to_owned();
                discount = decimal_value(&controls["runoutMarkdownPct"]);
                offer_demand_factor = decimal_value(&controls["runoutMarkdownDemandMultiplier"]);
            }
            current_offer_id = offer_id(&offer_type, &product.product_code);
        }
    }

    if !product.successor_of_product_code.is_empty() && profile == "flagship-spike-decay" {
        let transfer_days = (controls["launchSpikeDays"].as_i64().unwrap_or(14)
            + controls["launchSettleDays"].as_i64().unwrap_or(76))
        .max(1);
        let remaining = (1.0 - age_days as f64 / transfer_days as f64).max(0.0);
        substitution_factor +=
            decimal_value(&controls["substitutionRate"]) * decimal_from_f64(remaining);
    }

    LifecycleEffect {
        launch_profile: profile.to_owned(),
        launch_factor,
        predecessor_factor,
        substitution_factor,
        offer_id: current_offer_id,
        offer_type,
        offer_discount_pct: discount,
        offer_demand_factor,
    }
}

fn safe_id(value: &str) -> String {
    let mut result = String::new();
    let mut separator = false;
    for character in value.chars().flat_map(char::to_lowercase) {
        if character.is_ascii_alphanumeric() {
            result.push(character);
            separator = false;
        } else if !separator && !result.is_empty() {
            result.push('-');
            separator = true;
        }
    }
    result.trim_matches('-').to_owned()
}

fn decimal_value(value: &serde_json::Value) -> Decimal {
    let raw = value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned);
    raw.parse().expect("validated lifecycle decimal")
}

fn decimal_from_f64(value: f64) -> Decimal {
    value.to_string().parse().expect("finite lifecycle float")
}

fn dec(value: &str) -> Decimal {
    value.parse().expect("constant decimal")
}
