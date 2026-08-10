use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

use anyhow::{Context, Result};
use bigdecimal::RoundingMode;
use chrono::{Datelike, Duration};

use crate::catalog::{Product, active_on};
use crate::config::{LoadedConfig, Market};
use crate::deterministic::{PythonRandom, stable_integer};
use crate::projection::LogicalDataset;
use crate::projection::catalog::local_iso_at;
use crate::simulation::causal_effects::pandemic_effect;
use crate::simulation::decimal::PyDecimal as Decimal;
use crate::simulation::signals::temperature;

/// Build the contextual market feeds that are independent of inventory and
/// customer-order state. They can be projected in parallel without changing
/// the deterministic causal lane.
pub fn build_signal_datasets(
    config: &LoadedConfig,
    catalog: &[Product],
) -> Result<Vec<LogicalDataset>> {
    let mut datasets = Vec::new();
    let mut competitor_truth = Vec::new();
    let mut markets = config.scenario.markets.iter().collect::<Vec<_>>();
    markets.sort_by(|left, right| left.market_id.cmp(&right.market_id));
    for market in markets {
        let prefix = format!("companion/{}", market.market_id);
        let rows = build_market_signals(config, catalog, market)?;
        if flag(&market.signals, "weather") {
            datasets.push(dataset(&prefix, "weatherActuals", rows.weather_actuals));
            datasets.push(dataset(&prefix, "weatherForecasts", rows.weather_forecasts));
        }
        if flag(&market.signals, "macro") {
            datasets.push(dataset(&prefix, "macroIndex", rows.macro_rows));
        }
        if flag(&market.signals, "competitor") {
            datasets.push(dataset(&prefix, "competitorPrices", rows.competitor_prices));
            competitor_truth.extend(rows.competitor_matches.iter().cloned());
            datasets.push(dataset(
                &prefix,
                "competitorMatches",
                rows.competitor_matches,
            ));
        }
        datasets.push(dataset(&prefix, "pandemicSignals", rows.pandemic_signals));
    }
    if config.scenario.output.write_hidden_truth {
        datasets.push(LogicalDataset {
            prefix: "_truth".to_owned(),
            source_system: "hiddenTruth".to_owned(),
            dataset: "competitorMatchTruth".to_owned(),
            restricted: true,
            rows: competitor_truth,
        });
    }
    Ok(datasets)
}

#[derive(Default)]
struct MarketSignals {
    weather_actuals: Vec<BTreeMap<String, String>>,
    weather_forecasts: Vec<BTreeMap<String, String>>,
    macro_rows: Vec<BTreeMap<String, String>>,
    competitor_prices: Vec<BTreeMap<String, String>>,
    competitor_matches: Vec<BTreeMap<String, String>>,
    pandemic_signals: Vec<BTreeMap<String, String>>,
}

fn build_market_signals(
    config: &LoadedConfig,
    catalog: &[Product],
    market: &Market,
) -> Result<MarketSignals> {
    let mut result = MarketSignals::default();
    let start = config.scenario.time.start_date;
    let end = config.scenario.time.end_date;
    let master_seed = config.scenario.identity.master_seed;
    let forecast_horizon = config.scenario.operations.supply_chain["weatherForecastHorizonDays"]
        .as_i64()
        .context("operations.supplyChain.weatherForecastHorizonDays")?;
    let market_products = catalog
        .iter()
        .filter(|product| product.market_id == market.market_id)
        .collect::<Vec<_>>();
    let first_store = config
        .scenario
        .stores
        .iter()
        .find(|store| store.market_id == market.market_id)
        .with_context(|| format!("market {} has no store", market.market_id))?;
    let mut competitor_match_keys = BTreeSet::new();

    let mut day = start;
    while day <= end {
        let (actual_temperature, actual_precipitation) = temperature(master_seed, market, day)?;
        let pandemic = pandemic_effect(config, day, &market.market_id, "", "", "", "")?;
        if !pandemic.phase_ids.is_empty() {
            result.pandemic_signals.push(row([
                ("marketKey", market.market_id.clone()),
                ("validDate", day.to_string()),
                ("observedAt", local_iso_at(day, 23, &market.timezone)?),
                ("pandemicIds", pandemic.pandemic_ids.join("|")),
                ("phaseIds", pandemic.phase_ids.join("|")),
                ("effectModes", pandemic.effect_modes.join("|")),
                ("demandMultiplier", pandemic.demand.to_string()),
                ("trafficMultiplier", pandemic.traffic.to_string()),
                ("costMultiplier", pandemic.cost.to_string()),
                ("leadTimeMultiplier", pandemic.lead_time.to_string()),
                ("inventoryLossPct", pandemic.inventory_loss.to_string()),
            ]));
        }

        if flag(&market.signals, "weather") {
            result.weather_actuals.push(row([
                ("marketKey", market.market_id.clone()),
                ("targetType", "market".to_owned()),
                ("targetId", market.market_id.clone()),
                ("observedAt", local_iso_at(day, 23, &market.timezone)?),
                ("validDate", day.to_string()),
                ("temperatureC", actual_temperature.fixed_string(1)),
                ("precipitationMm", actual_precipitation.fixed_string(1)),
                (
                    "condition",
                    if actual_precipitation >= dec("2") {
                        "rain"
                    } else {
                        "clear"
                    }
                    .to_owned(),
                ),
            ]));
            for horizon in 1..=forecast_horizon {
                let valid_day = day + Duration::days(horizon);
                let (future_temperature, future_precipitation) =
                    temperature(master_seed, market, valid_day)?;
                let day_text = day.to_string();
                let horizon_text = horizon.to_string();
                let error = Decimal::from_f64_text(
                    PythonRandom::new(
                        master_seed,
                        &[
                            "forecast-error",
                            &market.market_id,
                            &day_text,
                            &horizon_text,
                        ],
                    )
                    .uniform(-0.8 * horizon as f64, 0.8 * horizon as f64),
                );
                let mut precipitation_random = PythonRandom::new(
                    master_seed,
                    &[
                        "forecast-rain-error",
                        &market.market_id,
                        &day_text,
                        &horizon_text,
                    ],
                );
                let forecast_precipitation = if future_precipitation == Decimal::zero() {
                    if precipitation_random.random() < 0.08 * horizon as f64 {
                        Decimal::from_f64_text(
                            precipitation_random.uniform(0.1, 1.5 + 0.4 * horizon as f64),
                        )
                    } else {
                        Decimal::zero()
                    }
                } else {
                    let lower = (1.0 - 0.16 * horizon as f64).max(0.15);
                    Decimal::zero().max(
                        future_precipitation
                            * Decimal::from_f64_text(
                                precipitation_random.uniform(lower, 1.0 + 0.20 * horizon as f64),
                            ),
                    )
                };
                result.weather_forecasts.push(row([
                    ("marketKey", market.market_id.clone()),
                    ("targetType", "market".to_owned()),
                    ("targetId", market.market_id.clone()),
                    ("issuedAt", local_iso_at(day, 6, &market.timezone)?),
                    ("validDate", valid_day.to_string()),
                    ("horizonDays", horizon.to_string()),
                    (
                        "temperatureC",
                        (future_temperature + error)
                            .quantize(1, RoundingMode::HalfEven)
                            .to_string(),
                    ),
                    (
                        "precipitationMm",
                        forecast_precipitation
                            .quantize(1, RoundingMode::HalfEven)
                            .to_string(),
                    ),
                    ("provider", "synthetic-weather-service".to_owned()),
                ]));
            }
        }

        if flag(&market.signals, "macro") {
            let trend =
                Decimal::from_f64_text(1.02_f64.powf((day - start).num_days() as f64 / 365.2425));
            let value = (Decimal::from(100_u32) * trend * &pandemic.demand * &pandemic.traffic)
                .quantize(3, RoundingMode::HalfEven);
            result.macro_rows.push(row([
                ("marketKey", market.market_id.clone()),
                ("targetType", "market".to_owned()),
                ("targetId", market.market_id.clone()),
                ("observedAt", local_iso_at(day, 18, &market.timezone)?),
                ("validDate", day.to_string()),
                ("indexName", "consumer-demand-index".to_owned()),
                ("indexValue", value.to_string()),
            ]));
        }

        if flag(&market.signals, "competitor") && (day - start).num_days() % 7 == 0 {
            for product in &market_products {
                for variant in &product.variants {
                    if !active_on(variant, day) {
                        continue;
                    }
                    let match_key = format!("match:{}:{}", market.market_id, variant.sku);
                    let day_text = day.to_string();
                    let factor = Decimal::from_f64_text(
                        PythonRandom::new(
                            master_seed,
                            &["competitor", &market.market_id, &variant.sku, &day_text],
                        )
                        .uniform(0.90, 1.10),
                    );
                    let competitor_sku =
                        format!("CMP-{:08}", stable_integer(&[&match_key], 99_999_999));
                    let master_text = master_seed.to_string();
                    let available = fraction(&[
                        &master_text,
                        "competitor-availability",
                        &market.market_id,
                        &variant.sku,
                        &day_text,
                    ]) >= 0.08;
                    let base = Decimal::from_str(&variant.base_price.to_string())
                        .context("variant base price")?;
                    let inflation_rate = market.price_dynamics["annualInflationRate"]
                        .as_f64()
                        .context("priceDynamics.annualInflationRate")?;
                    let years = (day.year() - variant.launch_date.year()).max(0);
                    let inflation =
                        Decimal::from_f64_text((1.0 + inflation_rate).powf(f64::from(years)));
                    let competitor_price = snap_price_ending(base * inflation * &factor, market)?;
                    result.competitor_prices.push(row([
                        ("marketKey", market.market_id.clone()),
                        ("targetType", "store".to_owned()),
                        ("targetId", first_store.store_id.clone()),
                        ("observedAt", local_iso_at(day, 8, &market.timezone)?),
                        ("validDate", day.to_string()),
                        ("competitorId", format!("competitor-{}", market.market_id)),
                        ("competitorSku", competitor_sku.clone()),
                        (
                            "competitorProductTitle",
                            format!("Comparable {}", product.title),
                        ),
                        ("price", competitor_price.to_string()),
                        ("currencyCode", market.currency_code.clone()),
                        ("available", available.to_string()),
                        (
                            "promotionText",
                            if factor < Decimal::one() {
                                "weekly-price-check"
                            } else {
                                ""
                            }
                            .to_owned(),
                        ),
                    ]));
                    if competitor_match_keys.insert(match_key.clone()) {
                        let confidence = dec("0.82")
                            + Decimal::from(stable_integer(&[&match_key], 1700)) / dec("10000");
                        result.competitor_matches.push(row([
                            ("matchKey", match_key),
                            ("marketKey", market.market_id.clone()),
                            ("competitorId", format!("competitor-{}", market.market_id)),
                            ("competitorSku", competitor_sku),
                            ("ourSku", variant.sku.clone()),
                            ("matchMethod", "synthetic-attribute-match".to_owned()),
                            ("matchConfidence", confidence.to_string()),
                            ("effectiveFrom", start.to_string()),
                            ("effectiveTo", end.to_string()),
                        ]));
                    }
                }
            }
        }
        day += Duration::days(1);
    }
    Ok(result)
}

fn snap_price_ending(value: Decimal, market: &Market) -> Result<Decimal> {
    let endings = market.locale_pack["currency"]["priceEndings"]
        .as_array()
        .context("currency.priceEndings")?;
    let whole = value.trunc_i64().context("price whole units")?;
    let mut selected: Option<Decimal> = None;
    for major in 0_i64.max(whole - 1)..=(whole + 1) {
        for ending in endings {
            let raw = ending
                .as_str()
                .map_or_else(|| ending.to_string(), str::to_owned);
            let candidate =
                Decimal::from(major) + Decimal::from_str(&raw)? / Decimal::from(100_u32);
            if candidate <= Decimal::zero() {
                continue;
            }
            if selected.as_ref().is_none_or(|current| {
                let candidate_key = ((&candidate - &value).abs(), candidate.clone());
                let current_key = ((current - &value).abs(), current.clone());
                candidate_key < current_key
            }) {
                selected = Some(candidate);
            }
        }
    }
    selected
        .context("no positive price ending")
        .map(|value| value.quantize(2, RoundingMode::HalfEven))
}

fn flag(signals: &serde_json::Value, key: &str) -> bool {
    signals[key].as_bool().unwrap_or(false)
}

fn fraction(parts: &[&str]) -> f64 {
    stable_integer(parts, 1_000_000) as f64 / 1_000_000.0
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
}

fn dataset(prefix: &str, name: &str, rows: Vec<BTreeMap<String, String>>) -> LogicalDataset {
    LogicalDataset {
        prefix: prefix.to_owned(),
        source_system: "companion".to_owned(),
        dataset: name.to_owned(),
        restricted: false,
        rows,
    }
}

fn row<const N: usize>(values: [(&str, String); N]) -> BTreeMap<String, String> {
    values
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value))
        .collect()
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::build_signal_datasets;
    use crate::catalog::build_catalog;
    use crate::config::LoadedConfig;
    use crate::contracts;
    use crate::deterministic::sha256_hex;
    use crate::projection::LogicalDataset;

    fn sorted_digest(dataset: &LogicalDataset) -> String {
        let fields = contracts::fields(&dataset.source_system, &dataset.dataset).expect("fields");
        let mut rows = dataset
            .rows
            .iter()
            .map(|row| {
                fields
                    .iter()
                    .map(|field| row.get(field).filter(|value| !value.is_empty()).cloned())
                    .collect::<Vec<_>>()
            })
            .collect::<Vec<_>>();
        rows.sort_by(|left, right| {
            for (left, right) in left.iter().zip(right) {
                let ordering = match (left, right) {
                    (Some(left), Some(right)) => left.cmp(right),
                    (Some(_), None) => std::cmp::Ordering::Less,
                    (None, Some(_)) => std::cmp::Ordering::Greater,
                    (None, None) => std::cmp::Ordering::Equal,
                };
                if !ordering.is_eq() {
                    return ordering;
                }
            }
            std::cmp::Ordering::Equal
        });
        sha256_hex(serde_json::to_string(&rows).unwrap().as_bytes())
    }

    #[test]
    fn gulf_mini_context_signals_match_python_oracle() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let datasets = build_signal_datasets(&config, &catalog).expect("signals");
        let expected = BTreeMap::from([
            (
                "weatherActuals",
                (
                    14,
                    "4cbf10e388d1af02071a23e4f50fd9744d4d59764c55a876449d192caf8454cc",
                ),
            ),
            (
                "weatherForecasts",
                (
                    98,
                    "42588ed6f9656b1955a41c198f308e95dd142a6b4d715d46652b690bfc0fe961",
                ),
            ),
            (
                "macroIndex",
                (
                    14,
                    "4a0188422bb39941bdc0ab46b56e312a1e0899c1636fd42321b7ed184eb83a8a",
                ),
            ),
            (
                "competitorPrices",
                (
                    584,
                    "bf5b16e402cfcac0785a78012560eef563601076e9f1469878ec8db77bc532a2",
                ),
            ),
            (
                "competitorMatches",
                (
                    292,
                    "b82aa3cf44821e8912335eb036b1b042861df2e3cd28b003a214deabd98b1b71",
                ),
            ),
            (
                "pandemicSignals",
                (
                    0,
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
                ),
            ),
            (
                "competitorMatchTruth",
                (
                    292,
                    "b82aa3cf44821e8912335eb036b1b042861df2e3cd28b003a214deabd98b1b71",
                ),
            ),
        ]);
        for dataset in datasets {
            let (count, digest) = expected[dataset.dataset.as_str()];
            assert_eq!(dataset.rows.len(), count, "{} rows", dataset.dataset);
            assert_eq!(
                sorted_digest(&dataset),
                digest,
                "{} digest; first row {:?}",
                dataset.dataset,
                dataset.rows.first()
            );
        }
    }
}
