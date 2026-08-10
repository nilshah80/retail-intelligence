use anyhow::{Context, Result};
use chrono::{
    DateTime, Duration, FixedOffset, NaiveDate, NaiveDateTime, NaiveTime, SecondsFormat, TimeZone,
};
use chrono_tz::Tz;
use std::str::FromStr;

use crate::config::LoadedConfig;
use crate::deterministic::stable_integer;

pub fn local_iso_at(
    day: NaiveDate,
    hour: u32,
    minute: u32,
    second: u32,
    timezone: &str,
) -> Result<String> {
    let timezone = Tz::from_str(timezone).with_context(|| format!("timezone {timezone}"))?;
    let local = NaiveDateTime::new(
        day,
        NaiveTime::from_hms_opt(hour.min(23), minute.min(59), second.min(59))
            .context("valid local time")?,
    );
    let value = timezone
        .from_local_datetime(&local)
        .single()
        .or_else(|| timezone.from_local_datetime(&local).earliest())
        .context("local timestamp")?;
    Ok(value.to_rfc3339_opts(SecondsFormat::Secs, false))
}

pub fn add_hours(timestamp: &str, hours: i64) -> Result<String> {
    let value = DateTime::<FixedOffset>::parse_from_rfc3339(timestamp)
        .with_context(|| format!("invalid operational timestamp {timestamp:?}"))?
        + Duration::hours(hours);
    Ok(value.to_rfc3339_opts(SecondsFormat::Secs, false))
}

pub fn fulfillment_timestamps(
    config: &LoadedConfig,
    order_key: &str,
    warehouse_id: &str,
    order_created_at: &str,
) -> Result<(String, String)> {
    let master_seed = config.scenario.identity.master_seed.to_string();
    let processing_hours = config.scenario.operations.fulfillment["processingDelayHours"]
        .as_i64()
        .context("operations.fulfillment.processingDelayHours")?;
    let fulfillment_key = format!("{order_key}:{warehouse_id}");
    let processing_jitter = i64::try_from(stable_integer(
        &[
            &master_seed,
            "fulfillment-processing-hours",
            &fulfillment_key,
        ],
        u64::try_from((processing_hours + 5).max(2))?,
    ))?;
    let created_at = add_hours(
        order_created_at,
        (processing_hours - 1 + processing_jitter).max(1),
    )?;
    let delivery_hours = 8 + i64::try_from(stable_integer(
        &[&master_seed, "fulfillment-delivery-hours", &fulfillment_key],
        49,
    ))?;
    let delivered_at = add_hours(&created_at, delivery_hours)?;
    Ok((created_at, delivered_at))
}

#[cfg(test)]
mod tests {
    use super::fulfillment_timestamps;
    use crate::config::LoadedConfig;

    #[test]
    fn timestamps_match_python_golden() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let actual = fulfillment_timestamps(
            &config,
            "order:gulf-india:mumbai-dist:2026-07-18:000000",
            "silvassa-plant",
            "2026-07-18T09:14:03+05:30",
        )
        .expect("timestamps");
        assert_eq!(actual.0, "2026-07-18T20:14:03+05:30");
        assert_eq!(actual.1, "2026-07-19T11:14:03+05:30");
    }
}
