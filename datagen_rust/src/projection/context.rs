use std::collections::BTreeMap;

use anyhow::{Context, Result};
use chrono::{Duration, NaiveDate};
use serde_json::Value;

use crate::catalog::Product;
use crate::config::{LoadedConfig, Market};
use crate::deterministic::stable_integer;
use crate::projection::LogicalDataset;
use crate::projection::catalog::local_iso_at;
use crate::simulation::assortment;
use crate::simulation::calendar::holidays_for_range;
use crate::simulation::lifecycle;
use crate::simulation::store_inventory::StoreEchelon;

/// Build source relations that are declarations derived from resolved config,
/// catalog lifecycle, and store-assortment policy rather than transactional
/// simulation state.
pub fn build_context_datasets(
    config: &LoadedConfig,
    catalog: &[Product],
) -> Result<Vec<LogicalDataset>> {
    let assortment = assortment::build(config, catalog)?;
    let lanes = StoreEchelon::new(config, BTreeMap::new()).lane_rows()?;
    let promotions = promotion_plans(config, catalog)?;
    let mut datasets = Vec::new();

    for market in &config.scenario.markets {
        let prefix = format!("companion/{}", market.market_id);
        if flag(&market.signals, "holidays") {
            datasets.push(dataset(
                &prefix,
                "holidays",
                holidays_for_range(
                    &market.locale_pack,
                    config.scenario.time.start_date,
                    config.scenario.time.end_date,
                )?
                .into_iter()
                .map(|holiday| {
                    row([
                        ("marketKey", market.market_id.clone()),
                        ("targetType", "market".to_owned()),
                        ("targetId", market.market_id.clone()),
                        ("date", holiday.date),
                        ("name", holiday.name),
                        ("kind", holiday.kind),
                        ("retailBehavior", holiday.retail_behavior),
                    ])
                })
                .collect(),
            ));
        }
        if flag(&market.signals, "fx") {
            datasets.push(dataset(
                &prefix,
                "fxRates",
                days(
                    config.scenario.time.start_date,
                    config.scenario.time.end_date,
                )
                .map(|day| {
                    row([
                        ("marketKey", market.market_id.clone()),
                        ("rateDate", day.to_string()),
                        ("baseCurrency", market.currency_code.clone()),
                        (
                            "quoteCurrency",
                            config.scenario.retailer.reporting_currency.clone(),
                        ),
                        ("rateType", "scenario-daily-close".to_owned()),
                        ("quotePerBase", market.fx_rate_to_reporting.clone()),
                    ])
                })
                .collect(),
            ));
        }
        datasets.push(dataset(
            &prefix,
            "pandemicTimeline",
            pandemic_timeline(config, market)?,
        ));
        datasets.push(dataset(
            &prefix,
            "promotions",
            promotions
                .iter()
                .filter(|plan| plan.market_id == market.market_id)
                .map(|plan| plan.promotion_row(config, market))
                .collect::<Result<Vec<_>>>()?,
        ));
        if config
            .scenario
            .operations
            .features
            .get("promotionPlanning")
            .copied()
            .unwrap_or(false)
        {
            datasets.push(dataset(
                &prefix,
                "promotionSkus",
                promotion_sku_rows(config, &promotions, catalog, &market.market_id)?,
            ));
            datasets.push(dataset(
                &prefix,
                "customerSegments",
                customer_segment_rows(config)?,
            ));
        }
        datasets.push(dataset(
            &prefix,
            "storeAssortment",
            assortment
                .rows
                .iter()
                .filter(|values| values["marketKey"] == market.market_id)
                .map(|values| {
                    values
                        .iter()
                        .map(|(field, value)| ((*field).to_owned(), value.clone()))
                        .collect()
                })
                .collect(),
        ));
        if config
            .scenario
            .operations
            .features
            .get("storeInventory")
            .copied()
            .unwrap_or(false)
        {
            datasets.push(dataset(
                &prefix,
                "serviceLanes",
                lanes
                    .iter()
                    .filter(|values| values["marketKey"] == market.market_id)
                    .map(|values| {
                        values
                            .iter()
                            .map(|(field, value)| ((*field).to_owned(), value.clone()))
                            .collect()
                    })
                    .collect(),
            ));
        }
        datasets.push(dataset(
            &prefix,
            "localEvents",
            local_event_rows(config, market)?,
        ));
    }
    Ok(datasets)
}

#[derive(Debug, Clone)]
struct PromotionPlan {
    promotion_id: String,
    name: String,
    promotion_type: String,
    market_id: String,
    start_date: NaiveDate,
    end_date: NaiveDate,
    store_ids: Vec<String>,
    channel_ids: Vec<String>,
    department_ids: Vec<String>,
    category_ids: Vec<String>,
    customer_segment_ids: Vec<String>,
    skus: Vec<String>,
    discount_pct: String,
    demand_multiplier: String,
}

impl PromotionPlan {
    fn from_config(value: &Value) -> Result<Self> {
        Ok(Self {
            promotion_id: string(value, "promotionId")?,
            name: string(value, "name")?,
            promotion_type: value["promotionType"]
                .as_str()
                .unwrap_or("campaign")
                .to_owned(),
            market_id: string(value, "marketId")?,
            start_date: date(value, "startDate")?,
            end_date: date(value, "endDate")?,
            store_ids: strings(&value["storeIds"]),
            channel_ids: strings(&value["channelIds"]),
            department_ids: strings(&value["departmentIds"]),
            category_ids: strings(&value["categoryIds"]),
            customer_segment_ids: strings(&value["customerSegmentIds"]),
            skus: strings(&value["_skus"]),
            discount_pct: scalar(&value["discountPct"]),
            demand_multiplier: scalar(&value["demandMultiplier"]),
        })
    }

    fn promotion_row(
        &self,
        config: &LoadedConfig,
        market: &Market,
    ) -> Result<BTreeMap<String, String>> {
        let mut values = row([
            ("marketKey", self.market_id.clone()),
            ("promotionId", self.promotion_id.clone()),
            ("name", self.name.clone()),
            ("startDate", self.start_date.to_string()),
            ("endDate", self.end_date.to_string()),
            ("storeIds", self.store_ids.join("|")),
            ("channelIds", self.channel_ids.join("|")),
            ("departmentIds", self.department_ids.join("|")),
            ("categoryIds", self.category_ids.join("|")),
            ("skus", self.skus.join("|")),
            ("customerSegmentIds", self.customer_segment_ids.join("|")),
            ("discountPct", self.discount_pct.clone()),
            ("discountBasis", "planned-offer".to_owned()),
            ("demandMultiplier", self.demand_multiplier.clone()),
            ("promotionType", self.promotion_type.clone()),
        ]);
        if let Some(evidence) = config.pricing_evidence() {
            let known_day = self
                .start_date
                .checked_sub_signed(Duration::days(i64::from(
                    evidence.promotion_planning_lead_days,
                )))
                .context("promotion known-as-of date overflow")?;
            let extract_day = config.scenario.time.end_date;
            let lifecycle_status = if self.end_date < extract_day {
                "Completed"
            } else if self.start_date <= extract_day && extract_day <= self.end_date {
                "Live"
            } else {
                ["Draft", "Under Review", "Approved"]
                    [stable_integer(&[&self.promotion_id, "lifecycle"], 3) as usize]
            };
            values.insert(
                "knownAsOf".to_owned(),
                local_iso_at(known_day, 9, &market.timezone)?,
            );
            values.insert("lifecycleStatus".to_owned(), lifecycle_status.to_owned());
            values.insert(
                "provenanceClass".to_owned(),
                "generated_source_native".to_owned(),
            );
            values.insert(
                "generationMethod".to_owned(),
                evidence.generation_method.clone(),
            );
        }
        Ok(values)
    }
}

fn promotion_plans(config: &LoadedConfig, catalog: &[Product]) -> Result<Vec<PromotionPlan>> {
    let configured = config.raw["promotions"]
        .as_array()
        .context("promotions array")?
        .iter()
        .map(PromotionPlan::from_config)
        .collect::<Result<Vec<_>>>()?;
    let start = config.scenario.time.start_date;
    let end = config.scenario.time.end_date;
    let mut automatic = Vec::new();
    for product in catalog {
        let Some(successor_launch) = product.successor_launch_date else {
            continue;
        };
        let controls = &product.lifecycle;
        let discontinue = product.discontinue_date.unwrap_or(
            successor_launch + Duration::days(30 * controls["runoutMonths"].as_i64().unwrap_or(18)),
        );
        let clearance_start = successor_launch
            + Duration::days(
                controls["clearanceStartDaysAfterSuccessor"]
                    .as_i64()
                    .unwrap_or(120),
            );
        let fire_start =
            discontinue - Duration::days(controls["fireSaleFinalDays"].as_i64().unwrap_or(30));
        let mut product_skus = product
            .variants
            .iter()
            .map(|variant| variant.sku.clone())
            .collect::<Vec<_>>();
        product_skus.sort();
        for (offer_type, phase_start, phase_end, discount_key, demand_key) in [
            (
                "runout-markdown",
                successor_launch,
                (clearance_start - Duration::days(1)).min(discontinue),
                "runoutMarkdownPct",
                "runoutMarkdownDemandMultiplier",
            ),
            (
                "clearance",
                clearance_start,
                (fire_start - Duration::days(1)).min(discontinue),
                "clearanceDiscountPct",
                "clearanceDemandMultiplier",
            ),
            (
                "fire-sale",
                fire_start,
                discontinue,
                "fireSaleDiscountPct",
                "fireSaleDemandMultiplier",
            ),
        ] {
            let effective_start = start.max(phase_start);
            let effective_end = end.min(phase_end);
            if effective_end < effective_start {
                continue;
            }
            automatic.push(PromotionPlan {
                promotion_id: lifecycle::offer_id(offer_type, &product.product_code),
                name: format!("{} {}", product.title, title_case(offer_type)),
                promotion_type: offer_type.to_owned(),
                market_id: product.market_id.clone(),
                start_date: effective_start,
                end_date: effective_end,
                store_ids: Vec::new(),
                channel_ids: Vec::new(),
                department_ids: vec![product.department_id.clone()],
                category_ids: vec![product.category_id.clone()],
                customer_segment_ids: Vec::new(),
                skus: product_skus.clone(),
                discount_pct: scalar(&controls[discount_key]),
                demand_multiplier: scalar(&controls[demand_key]),
            });
        }
    }
    automatic.sort_by(|left, right| {
        (&left.market_id, left.start_date, &left.promotion_id).cmp(&(
            &right.market_id,
            right.start_date,
            &right.promotion_id,
        ))
    });
    Ok(configured.into_iter().chain(automatic).collect())
}

fn promotion_sku_rows(
    config: &LoadedConfig,
    promotions: &[PromotionPlan],
    catalog: &[Product],
    market_id: &str,
) -> Result<Vec<BTreeMap<String, String>>> {
    let mut rows = Vec::new();
    for promotion in promotions
        .iter()
        .filter(|promotion| promotion.market_id == market_id)
    {
        for product in catalog
            .iter()
            .filter(|product| product.market_id == market_id)
        {
            if !promotion.department_ids.is_empty()
                && !promotion.department_ids.contains(&product.department_id)
            {
                continue;
            }
            if !promotion.category_ids.is_empty()
                && !promotion.category_ids.contains(&product.category_id)
            {
                continue;
            }
            for variant in &product.variants {
                if !promotion.skus.is_empty() && !promotion.skus.contains(&variant.sku) {
                    continue;
                }
                let mut values = row([
                    ("marketKey", promotion.market_id.clone()),
                    ("promotionId", promotion.promotion_id.clone()),
                    ("sku", variant.sku.clone()),
                    ("departmentId", product.department_id.clone()),
                    ("categoryId", product.category_id.clone()),
                    ("discountPct", promotion.discount_pct.clone()),
                    ("discountBasis", "planned-offer".to_owned()),
                    ("effectiveFrom", promotion.start_date.to_string()),
                    ("effectiveTo", promotion.end_date.to_string()),
                ]);
                if let Some(evidence) = config.pricing_evidence() {
                    let known_day = promotion
                        .start_date
                        .checked_sub_signed(Duration::days(i64::from(
                            evidence.promotion_planning_lead_days,
                        )))
                        .context("promotion SKU known-as-of date overflow")?;
                    values.insert(
                        "knownAsOf".to_owned(),
                        format!("{}T00:00:00Z", known_day.format("%Y-%m-%d")),
                    );
                    values.insert(
                        "provenanceClass".to_owned(),
                        "generated_source_native".to_owned(),
                    );
                    values.insert(
                        "generationMethod".to_owned(),
                        evidence.generation_method.clone(),
                    );
                }
                rows.push(values);
            }
        }
    }
    Ok(rows)
}

fn customer_segment_rows(config: &LoadedConfig) -> Result<Vec<BTreeMap<String, String>>> {
    config.raw["customerSegments"]
        .as_array()
        .context("customerSegments array")?
        .iter()
        .map(|segment| {
            Ok(row([
                ("segmentId", string(segment, "segmentId")?),
                ("name", string(segment, "name")?),
                ("scenarioShare", scalar(&segment["share"])),
                ("demandMultiplier", scalar(&segment["demandMultiplier"])),
            ]))
        })
        .collect()
}

fn pandemic_timeline(
    config: &LoadedConfig,
    market: &Market,
) -> Result<Vec<BTreeMap<String, String>>> {
    let mut rows = Vec::new();
    for pandemic in &config.scenario.pandemics {
        if !strings(&pandemic["marketIds"]).contains(&market.market_id) {
            continue;
        }
        for phase in pandemic["phases"].as_array().into_iter().flatten() {
            rows.push(row([
                ("marketKey", market.market_id.clone()),
                ("pandemicId", string(pandemic, "pandemicId")?),
                ("pandemicName", string(pandemic, "name")?),
                ("pathogen", string(pandemic, "pathogen")?),
                ("effectMode", string(pandemic, "effectMode")?),
                ("note", string(pandemic, "note")?),
                ("phaseId", string(phase, "phaseId")?),
                ("phaseName", string(phase, "name")?),
                ("startDate", string(phase, "startDate")?),
                ("endDate", string(phase, "endDate")?),
                ("recoveryShape", string(phase, "recoveryShape")?),
                ("demandMultiplier", scalar(&phase["demandMultiplier"])),
                ("trafficMultiplier", scalar(&phase["trafficMultiplier"])),
                ("costMultiplier", scalar(&phase["costMultiplier"])),
                ("leadTimeMultiplier", scalar(&phase["leadTimeMultiplier"])),
                ("inventoryLossPct", scalar(&phase["inventoryLossPct"])),
                (
                    "departmentMultipliers",
                    compact_json(&phase["departmentMultipliers"]),
                ),
                (
                    "categoryMultipliers",
                    compact_json(&phase["categoryMultipliers"]),
                ),
                (
                    "catalogFamilyMultipliers",
                    compact_json(&phase["catalogFamilyMultipliers"]),
                ),
                (
                    "channelTypeMultipliers",
                    compact_json(&phase["channelTypeMultipliers"]),
                ),
            ]));
        }
    }
    Ok(rows)
}

fn local_event_rows(
    config: &LoadedConfig,
    market: &Market,
) -> Result<Vec<BTreeMap<String, String>>> {
    config.raw["events"]
        .as_array()
        .context("events array")?
        .iter()
        .filter(|event| event["marketId"].as_str() == Some(&market.market_id))
        .map(|event| {
            let store_id = event["storeId"].as_str().unwrap_or_default();
            Ok(row([
                ("marketKey", market.market_id.clone()),
                ("eventId", string(event, "eventId")?),
                ("type", string(event, "type")?),
                ("name", string(event, "name")?),
                ("startDate", string(event, "startDate")?),
                ("endDate", string(event, "endDate")?),
                (
                    "targetType",
                    if store_id.is_empty() {
                        "market"
                    } else {
                        "store"
                    }
                    .to_owned(),
                ),
                (
                    "targetId",
                    if store_id.is_empty() {
                        market.market_id.clone()
                    } else {
                        store_id.to_owned()
                    },
                ),
                ("demandMultiplier", scalar(&event["demandMultiplier"])),
                ("trafficMultiplier", scalar(&event["trafficMultiplier"])),
                ("costMultiplier", scalar(&event["costMultiplier"])),
                ("leadTimeMultiplier", scalar(&event["leadTimeMultiplier"])),
                ("inventoryLossPct", scalar(&event["inventoryLossPct"])),
                ("recoveryShape", string(event, "recoveryShape")?),
                ("departmentIds", strings(&event["departmentIds"]).join("|")),
                ("categoryIds", strings(&event["categoryIds"]).join("|")),
                ("channelIds", strings(&event["channelIds"]).join("|")),
            ]))
        })
        .collect()
}

fn days(start: NaiveDate, end: NaiveDate) -> impl Iterator<Item = NaiveDate> {
    (0..=(end - start).num_days()).map(move |offset| start + Duration::days(offset))
}

fn date(value: &Value, key: &str) -> Result<NaiveDate> {
    NaiveDate::parse_from_str(&string(value, key)?, "%Y-%m-%d")
        .with_context(|| format!("invalid {key}"))
}

fn string(value: &Value, key: &str) -> Result<String> {
    value[key]
        .as_str()
        .map(str::to_owned)
        .with_context(|| format!("missing string {key}"))
}

fn strings(value: &Value) -> Vec<String> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect()
}

fn scalar(value: &Value) -> String {
    value
        .as_str()
        .map_or_else(|| value.to_string(), str::to_owned)
}

fn compact_json(value: &Value) -> String {
    serde_json::to_string(value).expect("JSON value")
}

fn title_case(value: &str) -> String {
    value
        .split('-')
        .map(|word| {
            let mut characters = word.chars();
            characters.next().map_or_else(String::new, |first| {
                first.to_uppercase().chain(characters).collect()
            })
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn flag(signals: &Value, key: &str) -> bool {
    signals[key].as_bool().unwrap_or(false)
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

    use super::build_context_datasets;
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
    fn gulf_mini_context_declarations_match_python_oracle() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json").expect("config");
        let catalog = build_catalog(&config).expect("catalog");
        let datasets = build_context_datasets(&config, &catalog).expect("context");
        let expected = BTreeMap::from([
            (
                "holidays",
                (
                    0,
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
                ),
            ),
            (
                "fxRates",
                (
                    14,
                    "c1975b845e88e382631929328e5aa50d4b52e5c9ac2afe3f342551fb62dda5e7",
                ),
            ),
            (
                "pandemicTimeline",
                (
                    0,
                    "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
                ),
            ),
            (
                "promotions",
                (
                    40,
                    "59c7f0eb44b56ea8f0e379abbe0515fbfad56ae35def0a0097a5d44636a60518",
                ),
            ),
            (
                "promotionSkus",
                (
                    1440,
                    "3513bc8854f64923db8cf91cdd29a8ce0cb4f200dd6c1cfb3bb78f75b987137f",
                ),
            ),
            (
                "customerSegments",
                (
                    3,
                    "588486879df94d66d3dea67aa498a50dd590e7561e0dc5fba249e0bf96351b8b",
                ),
            ),
            (
                "storeAssortment",
                (
                    3201,
                    "9639b3c34697bc63b73d05b2787fba403ce1c7a6423a1ca406cebb83126a076c",
                ),
            ),
            (
                "serviceLanes",
                (
                    26,
                    "7fc480811aac6d826c329a9fe2baabd3e84f97db88b54a08351f7caefc81974f",
                ),
            ),
            (
                "localEvents",
                (
                    52,
                    "85a944190cb95d517f7ed1ae74ef2f1178af69cc653a4b74eb00c14b8d0cfe83",
                ),
            ),
        ]);
        assert_eq!(datasets.len(), expected.len());
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
