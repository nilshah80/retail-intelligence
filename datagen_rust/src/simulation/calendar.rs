use std::collections::{BTreeMap, BTreeSet};

use anyhow::{Context, Result, bail};
use chrono::{Datelike, Duration, NaiveDate, Weekday};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq)]
#[allow(clippy::struct_field_names)]
pub struct Holiday {
    pub date: String,
    pub name: String,
    pub kind: String,
    pub retail_behavior: String,
}

#[must_use]
pub fn easter_sunday(year: i32) -> NaiveDate {
    let a = year % 19;
    let b = year / 100;
    let c = year % 100;
    let d = b / 4;
    let e = b % 4;
    let f = (b + 8) / 25;
    let g = (b - f + 1) / 3;
    let h = (19 * a + b - d - g + 15) % 30;
    let i = c / 4;
    let k = c % 4;
    let l = (32 + 2 * e + 2 * i - h - k) % 7;
    let m = (a + 11 * h + 22 * l) / 451;
    let month = (h + l - 7 * m + 114) / 31;
    let day = ((h + l - 7 * m + 114) % 31) + 1;
    NaiveDate::from_ymd_opt(year, month as u32, day as u32).expect("valid Easter date")
}

fn integer(rule: &Value, field: &str) -> Result<i64> {
    rule[field]
        .as_i64()
        .with_context(|| format!("holiday rule lacks integer {field}"))
}

fn rule_date(rule: &Value, year: i32) -> Result<NaiveDate> {
    let rule_type = rule["type"].as_str().context("holiday rule type")?;
    if rule_type == "fixed" {
        return NaiveDate::from_ymd_opt(
            year,
            u32::try_from(integer(rule, "month")?)?,
            u32::try_from(integer(rule, "day")?)?,
        )
        .context("valid fixed holiday date");
    }
    if rule_type == "easter-offset" {
        return Ok(easter_sunday(year) + Duration::days(integer(rule, "offsetDays")?));
    }
    let month = u32::try_from(integer(rule, "month")?)?;
    let weekday = integer(rule, "weekday")?;
    if matches!(rule_type, "nth-weekday" | "nth-weekday-offset") {
        let first = NaiveDate::from_ymd_opt(year, month, 1).context("valid holiday month")?;
        let first_weekday = i64::from(first.weekday().num_days_from_monday());
        let offset = (weekday - first_weekday).rem_euclid(7);
        let occurrence = integer(rule, "occurrence")?;
        let mut result = first + Duration::days(offset + 7 * (occurrence - 1));
        if rule_type == "nth-weekday-offset" {
            result += Duration::days(integer(rule, "offsetDays")?);
        }
        return Ok(result);
    }
    if rule_type == "last-weekday" {
        let (next_year, next_month) = if month == 12 {
            (year + 1, 1)
        } else {
            (year, month + 1)
        };
        let last = NaiveDate::from_ymd_opt(next_year, next_month, 1)
            .context("valid next holiday month")?
            - Duration::days(1);
        let last_weekday = i64::from(last.weekday().num_days_from_monday());
        return Ok(last - Duration::days((last_weekday - weekday).rem_euclid(7)));
    }
    bail!("unsupported holiday rule type {rule_type:?}")
}

/// Expand a v13 locale pack exactly like Python `holidays_for_range`.
pub fn holidays_for_range(
    locale_pack: &Value,
    start: NaiveDate,
    end: NaiveDate,
) -> Result<Vec<Holiday>> {
    let rules = locale_pack["holidayRules"]
        .as_array()
        .context("localePack.holidayRules")?;
    let mut rows = BTreeMap::<(String, String), Holiday>::new();
    for year in start.year()..=end.year() {
        for rule in rules {
            let day = rule_date(rule, year)?;
            if start <= day && day <= end {
                let row = Holiday {
                    date: day.to_string(),
                    name: rule["name"].as_str().context("holiday name")?.to_owned(),
                    kind: rule["kind"].as_str().context("holiday kind")?.to_owned(),
                    retail_behavior: rule["retailBehavior"]
                        .as_str()
                        .context("holiday retailBehavior")?
                        .to_owned(),
                };
                rows.insert((row.date.clone(), row.name.clone()), row);
            }
        }
        let mut occupied = rows
            .values()
            .filter_map(|row| NaiveDate::parse_from_str(&row.date, "%Y-%m-%d").ok())
            .filter(|day| day.year() == year)
            .collect::<BTreeSet<_>>();
        for rule in rules {
            if rule["type"].as_str() != Some("fixed") {
                continue;
            }
            let holiday = rule_date(rule, year)?;
            let locale_id = locale_pack["id"].as_str().unwrap_or_default();
            let mut observed = match (locale_id, holiday.weekday()) {
                ("US", Weekday::Sat) => Some(holiday - Duration::days(1)),
                ("US", Weekday::Sun) => Some(holiday + Duration::days(1)),
                ("GB", Weekday::Sat | Weekday::Sun) => Some(
                    holiday
                        + Duration::days(7 - i64::from(holiday.weekday().num_days_from_monday())),
                ),
                _ => None,
            };
            if locale_id == "GB" {
                while observed.is_some_and(|day| occupied.contains(&day)) {
                    observed = observed.map(|day| day + Duration::days(1));
                }
            }
            if let Some(day) = observed.filter(|day| start <= *day && *day <= end) {
                let row = Holiday {
                    date: day.to_string(),
                    name: format!(
                        "{} (observed)",
                        rule["name"].as_str().context("holiday name")?
                    ),
                    kind: "observed".to_owned(),
                    retail_behavior: "observance".to_owned(),
                };
                occupied.insert(day);
                rows.insert((row.date.clone(), row.name.clone()), row);
            }
        }
    }
    for value in locale_pack["holidays"].as_array().into_iter().flatten() {
        let date = value["date"].as_str().context("reviewed holiday date")?;
        let day = NaiveDate::parse_from_str(date, "%Y-%m-%d")?;
        if start <= day && day <= end {
            let row = Holiday {
                date: date.to_owned(),
                name: value["name"]
                    .as_str()
                    .context("reviewed holiday name")?
                    .to_owned(),
                kind: value["kind"]
                    .as_str()
                    .context("reviewed holiday kind")?
                    .to_owned(),
                retail_behavior: value["retailBehavior"]
                    .as_str()
                    .context("reviewed holiday retailBehavior")?
                    .to_owned(),
            };
            rows.insert((row.date.clone(), row.name.clone()), row);
        }
    }
    Ok(rows.into_values().collect())
}

#[cfg(test)]
mod tests {
    use chrono::NaiveDate;

    use super::holidays_for_range;
    use crate::config::LoadedConfig;

    #[test]
    fn india_calendar_matches_python_golden_range() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let holidays = holidays_for_range(
            &config.scenario.markets[0].locale_pack,
            NaiveDate::from_ymd_opt(2025, 10, 1).unwrap(),
            NaiveDate::from_ymd_opt(2026, 11, 10).unwrap(),
        )
        .expect("holidays");
        let actual = holidays
            .iter()
            .map(|row| format!("{}:{}", row.date, row.name))
            .collect::<Vec<_>>();
        assert_eq!(
            actual,
            [
                "2025-10-02:Gandhi Jayanti",
                "2025-10-20:Diwali",
                "2025-12-25:Christmas",
                "2026-01-26:Republic Day",
                "2026-03-04:Holi",
                "2026-03-20:Eid al-Fitr",
                "2026-08-15:Independence Day",
                "2026-10-02:Gandhi Jayanti",
                "2026-11-08:Diwali",
            ]
        );
    }
}
