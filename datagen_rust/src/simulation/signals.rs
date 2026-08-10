use anyhow::{Context, Result};
use bigdecimal::RoundingMode;
use chrono::{Datelike, Duration, NaiveDate};

use crate::config::Market;
use crate::deterministic::{PythonRandom, stable_integer};
use crate::simulation::decimal::PyDecimal as Decimal;

pub fn temperature(
    master_seed: u64,
    market: &Market,
    day: NaiveDate,
) -> Result<(Decimal, Decimal)> {
    let climate = &market.locale_pack["climate"];
    let summer = decimal_value(&climate["summerC"])?;
    let winter = decimal_value(&climate["winterC"])?;
    let profile = climate["profile"].as_str().context("climate.profile")?;
    let peak_day = if profile == "tropical-monsoon" {
        125
    } else {
        200
    };
    let seasonal = (&summer + &winter) / Decimal::from(2_u32)
        + ((&summer - &winter) / Decimal::from(2_u32))
            * Decimal::from_f64_text(
                ((f64::from(day.ordinal()) - f64::from(peak_day)) / 365.0 * std::f64::consts::TAU)
                    .cos(),
            );

    let anomaly_weights = (0..14)
        .map(|lag| (-(f64::from(lag)) / 4.0).exp())
        .collect::<Vec<_>>();
    let anomaly_weight_total = anomaly_weights.iter().sum::<f64>();
    let mut anomaly = 0.0;
    for (lag, weight) in anomaly_weights.iter().enumerate() {
        let lag_day = day - Duration::days(lag as i64);
        let lag_day = lag_day.to_string();
        anomaly += weight
            * PythonRandom::new(
                master_seed,
                &["weather-anomaly", &market.market_id, &lag_day],
            )
            .uniform(-3.5, 3.5);
    }
    anomaly /= anomaly_weight_total;

    let ordinal = i64::from(day.num_days_from_ce());
    let epoch = ordinal.div_euclid(14);
    let master = master_seed.to_string();
    for candidate_epoch in (epoch - 1)..=(epoch + 1) {
        let candidate = candidate_epoch.to_string();
        if fraction(&[
            &master,
            "temperature-spell-active",
            &market.market_id,
            &candidate,
        ]) >= 0.12
        {
            continue;
        }
        let anchor_ordinal = candidate_epoch * 14
            + i64::try_from(stable_integer(
                &[
                    &master,
                    "temperature-spell-anchor",
                    &market.market_id,
                    &candidate,
                ],
                14,
            ))?;
        let distance = ordinal - anchor_ordinal;
        let direction = if stable_integer(
            &[
                &master,
                "temperature-spell-direction",
                &market.market_id,
                &candidate,
            ],
            2,
        ) != 0
        {
            1.0
        } else {
            -1.0
        };
        let amplitude = 4.0
            + 3.0
                * fraction(&[
                    &master,
                    "temperature-spell-amplitude",
                    &market.market_id,
                    &candidate,
                ]);
        anomaly += direction * amplitude * (-0.5 * (distance as f64 / 3.5).powf(2.0)).exp();
    }
    let temperature = seasonal + Decimal::from_f64_text(anomaly);

    let day_text = day.to_string();
    let mut rain_random = PythonRandom::new(master_seed, &["rain", &market.market_id, &day_text]);
    let mut active_spell: Option<(NaiveDate, f64)> = None;
    for lag in 0..7_i64 {
        let spell_start = day - Duration::days(lag);
        let spell_text = spell_start.to_string();
        if fraction(&[&master, "rain-spell-start", &market.market_id, &spell_text]) >= 0.055 {
            continue;
        }
        let duration = 2 + i64::try_from(stable_integer(
            &[
                &master,
                "rain-spell-duration",
                &market.market_id,
                &spell_text,
            ],
            5,
        ))?;
        if lag >= duration {
            continue;
        }
        let intensity = 0.7
            + 1.3
                * fraction(&[
                    &master,
                    "rain-spell-intensity",
                    &market.market_id,
                    &spell_text,
                ]);
        if active_spell.is_none_or(|(_, current)| intensity > current) {
            active_spell = Some((spell_start, intensity));
        }
    }
    let wet_spell = active_spell.is_some();
    let precipitation = if profile == "tropical-monsoon" {
        let months = climate["monsoonMonths"]
            .as_array()
            .context("climate.monsoonMonths")?;
        let first_month = months
            .iter()
            .filter_map(serde_json::Value::as_u64)
            .min()
            .context("monsoon start")? as u32;
        let last_month = months
            .iter()
            .filter_map(serde_json::Value::as_u64)
            .max()
            .context("monsoon end")? as u32;
        let season_start =
            NaiveDate::from_ymd_opt(day.year(), first_month, 1).context("monsoon start date")?;
        let season_end = last_day_of_month(day.year(), last_month)?;
        let transition_days = 21.0;
        let intensity = if season_start <= day && day <= season_end {
            1.0
        } else if (1..=21).contains(&(season_start - day).num_days()) {
            let progress =
                (transition_days - (season_start - day).num_days() as f64) / transition_days;
            0.5 - 0.5 * (std::f64::consts::PI * progress).cos()
        } else if (1..=21).contains(&(day - season_end).num_days()) {
            let progress = (day - season_end).num_days() as f64 / transition_days;
            0.5 + 0.5 * (std::f64::consts::PI * progress).cos()
        } else {
            0.0
        };
        let probability = 0.03 + 0.55 * intensity + if wet_spell { 0.28 } else { 0.0 };
        if rain_random.random() < probability {
            Decimal::from_f64_text(rain_random.gammavariate(
                1.6,
                (3.0 + 12.0 * intensity) * active_spell.map_or(1.0, |(_, value)| value),
            ))
        } else {
            Decimal::zero()
        }
    } else if profile == "temperate-maritime" {
        let probability = if wet_spell { 0.78 } else { 0.22 };
        if rain_random.random() < probability {
            Decimal::from_f64_text(
                rain_random.gammavariate(1.4, 3.2 * active_spell.map_or(1.0, |(_, value)| value)),
            )
        } else {
            Decimal::zero()
        }
    } else {
        let probability = if wet_spell { 0.70 } else { 0.14 };
        if rain_random.random() < probability {
            Decimal::from_f64_text(
                rain_random.gammavariate(1.3, 3.6 * active_spell.map_or(1.0, |(_, value)| value)),
            )
        } else {
            Decimal::zero()
        }
    };
    Ok((
        temperature.quantize(1, RoundingMode::HalfEven),
        precipitation.quantize(1, RoundingMode::HalfEven),
    ))
}

fn last_day_of_month(year: i32, month: u32) -> Result<NaiveDate> {
    let (next_year, next_month) = if month == 12 {
        (year + 1, 1)
    } else {
        (year, month + 1)
    };
    Ok(
        NaiveDate::from_ymd_opt(next_year, next_month, 1).context("next month")?
            - Duration::days(1),
    )
}

fn decimal_value(value: &serde_json::Value) -> Result<Decimal> {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
        .parse()
        .context("signal decimal")
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

#[cfg(test)]
mod tests {
    use chrono::{Duration, NaiveDate};

    use super::temperature;
    use crate::config::LoadedConfig;

    #[test]
    fn gulf_mini_weather_matches_python_vectors() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let market = &config.scenario.markets[0];
        let start = NaiveDate::from_ymd_opt(2026, 7, 18).unwrap();
        let expected = [
            ("30.2", "0.0"),
            ("29.5", "41.7"),
            ("28.8", "37.5"),
            ("28.7", "83.6"),
            ("28.9", "0.0"),
            ("28.7", "35.3"),
            ("29.5", "0.0"),
            ("29.2", "6.0"),
            ("28.3", "16.0"),
            ("28.2", "0.0"),
            ("27.8", "9.9"),
            ("28.5", "41.3"),
            ("28.3", "0.0"),
            ("27.5", "0.0"),
        ];
        for (offset, expected) in expected.into_iter().enumerate() {
            let actual = temperature(
                config.scenario.identity.master_seed,
                market,
                start + Duration::days(offset as i64),
            )
            .expect("temperature");
            assert_eq!(
                (actual.0.fixed_string(1), actual.1.fixed_string(1)),
                (expected.0.to_owned(), expected.1.to_owned()),
                "weather day {offset}"
            );
        }
    }
}
