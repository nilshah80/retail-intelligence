//! Python-compatible deterministic catalog construction.

use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;
use std::sync::OnceLock;

use anyhow::{Context, Result, ensure};
use chrono::{Duration, NaiveDate};
use rust_decimal::{Decimal, RoundingStrategy};
use serde::Serialize;
use serde_json::{Map, Value, json};

use crate::config::{Category, Department, LoadedConfig, Market, ProductTemplate};
use crate::deterministic::{PythonRandom, round_half_even_f64, stable_integer};

const PACKS_JSON: &str = include_str!("../contracts/catalog-packs-2026.6.json");

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct OptionValue {
    pub name: String,
    pub value: String,
    pub code: String,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Product {
    #[serde(skip)]
    pub market_id: String,
    pub product_key: String,
    pub product_code: String,
    pub title: String,
    pub description: String,
    pub brand: String,
    pub brand_code: String,
    pub department_id: String,
    pub category_id: String,
    pub catalog_family: String,
    pub tax_category: String,
    pub unit_of_measure: String,
    pub material: String,
    pub launch_date: NaiveDate,
    pub discontinue_date: Option<NaiveDate>,
    pub successor_of_product_code: String,
    pub successor_product_code: String,
    pub successor_launch_date: Option<NaiveDate>,
    pub launch_profile: String,
    pub lifecycle: Value,
    pub seasonality_peak_month: u32,
    #[serde(with = "rust_decimal::serde::str")]
    pub seasonality_strength: Decimal,
    pub costing_method: String,
    pub shelf_life_days: Option<i64>,
    pub country_of_origin: String,
    pub variants: Vec<Variant>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Variant {
    #[serde(skip)]
    pub market_id: String,
    #[serde(skip)]
    pub currency_code: String,
    pub variant_key: String,
    pub variant_code: String,
    pub sku: String,
    pub title: String,
    pub barcode: String,
    pub options: Vec<OptionValue>,
    pub position: usize,
    #[serde(with = "rust_decimal::serde::str")]
    pub base_price: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub base_cost: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub demand_weight: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub elasticity: Decimal,
    #[serde(with = "rust_decimal::serde::str")]
    pub return_probability: Decimal,
    pub unit_of_measure: String,
    #[serde(with = "rust_decimal::serde::str")]
    pub measurement_value: Decimal,
    pub measurement_unit: String,
    #[serde(with = "rust_decimal::serde::str")]
    pub weight: Decimal,
    pub weight_unit: String,
    pub launch_date: NaiveDate,
    pub discontinue_date: Option<NaiveDate>,
}

#[must_use]
pub fn active_on(variant: &Variant, day: NaiveDate) -> bool {
    variant.launch_date <= day && variant.discontinue_date.is_none_or(|end| day <= end)
}

pub fn build_catalog(config: &LoadedConfig) -> Result<Vec<Product>> {
    let mut result = Vec::new();
    let mode = config.scenario.catalog.generation.mode.as_str();
    for market in &config.scenario.markets {
        let pack = catalog_pack(market)?;
        let target_per_department = market.assortment.skus_per_department;
        let variants_per_product = market.assortment.variants_per_product;
        let market_templates = config
            .scenario
            .catalog
            .product_templates
            .iter()
            .filter(|row| row.market_id == market.market_id)
            .collect::<Vec<_>>();
        let mut market_products = Vec::new();
        let mut used_product_codes = BTreeSet::new();
        let mut used_skus = BTreeSet::new();
        for department in &config.scenario.catalog.departments {
            let department_templates = market_templates
                .iter()
                .copied()
                .filter(|row| row.department_id == department.department_id)
                .collect::<Vec<_>>();
            let mut sku_count = 0_usize;
            let mut sequence = 0_usize;
            if matches!(mode, "hybrid" | "explicit") {
                for definition in department_templates {
                    sequence += 1;
                    let category = department
                        .categories
                        .iter()
                        .find(|row| row.category_id == definition.category_id)
                        .with_context(|| format!("unknown category {}", definition.category_id))?;
                    let product = product_from_definition(
                        config,
                        market,
                        department,
                        category,
                        pack,
                        sequence,
                        variants_per_product,
                        Some(definition),
                        None,
                    )?;
                    register_product(&product, &mut used_product_codes, &mut used_skus)?;
                    sku_count += product.variants.len();
                    market_products.push(product);
                }
            }
            if mode == "explicit" {
                continue;
            }
            let remaining = target_per_department.saturating_sub(sku_count);
            let generated_total = remaining.div_ceil(variants_per_product);
            let mut generated_index = 0_usize;
            let mut generated_by_category = BTreeMap::<String, usize>::new();
            while sku_count < target_per_department {
                sequence += 1;
                generated_index += 1;
                let category = select_generated_category(
                    department,
                    sequence,
                    &market.assortment.category_assortment_weights,
                    &generated_by_category,
                )?;
                let product = product_from_definition(
                    config,
                    market,
                    department,
                    category,
                    pack,
                    sequence,
                    variants_per_product.min(target_per_department - sku_count),
                    None,
                    Some((generated_index, generated_total)),
                )?;
                if used_product_codes.contains(&product.product_code)
                    || product
                        .variants
                        .iter()
                        .any(|row| used_skus.contains(&row.sku))
                {
                    continue;
                }
                register_product(&product, &mut used_product_codes, &mut used_skus)?;
                sku_count += product.variants.len();
                *generated_by_category
                    .entry(category.category_id.clone())
                    .or_default() += 1;
                market_products.push(product);
            }
        }
        link_successors(config, market, &mut market_products)?;
        result.extend(market_products);
    }
    validate_catalog(config, &result)?;
    Ok(result)
}

fn register_product(
    product: &Product,
    product_codes: &mut BTreeSet<String>,
    skus: &mut BTreeSet<String>,
) -> Result<()> {
    ensure!(
        product_codes.insert(product.product_code.clone()),
        "duplicate product code {} in {}",
        product.product_code,
        product.market_id
    );
    for variant in &product.variants {
        ensure!(
            skus.insert(variant.sku.clone()),
            "duplicate sellable SKU {} in {}",
            variant.sku,
            product.market_id
        );
    }
    Ok(())
}

fn select_generated_category<'a>(
    department: &'a Department,
    sequence: usize,
    weights: &BTreeMap<String, f64>,
    generated: &BTreeMap<String, usize>,
) -> Result<&'a Category> {
    ensure!(
        !department.categories.is_empty(),
        "department has no categories"
    );
    if weights.is_empty() {
        return Ok(&department.categories[(sequence - 1) % department.categories.len()]);
    }
    department
        .categories
        .iter()
        .min_by(|left, right| {
            let left_weight = decimal_from_f64(*weights.get(&left.category_id).unwrap_or(&1.0));
            let right_weight = decimal_from_f64(*weights.get(&right.category_id).unwrap_or(&1.0));
            let left_score = (
                (Decimal::from(*generated.get(&left.category_id).unwrap_or(&0) as u64)
                    + dec("0.5"))
                    / left_weight,
                -left_weight,
                &left.category_id,
            );
            let right_score = (
                (Decimal::from(*generated.get(&right.category_id).unwrap_or(&0) as u64)
                    + dec("0.5"))
                    / right_weight,
                -right_weight,
                &right.category_id,
            );
            left_score.cmp(&right_score)
        })
        .context("department has no categories")
}

#[allow(clippy::too_many_arguments)]
fn product_from_definition(
    config: &LoadedConfig,
    market: &Market,
    department: &Department,
    category: &Category,
    pack: &Value,
    sequence: usize,
    variant_count: usize,
    definition: Option<&ProductTemplate>,
    generated_lifecycle_position: Option<(usize, usize)>,
) -> Result<Product> {
    let master_seed = config.scenario.identity.master_seed;
    let family = &pack["families"][&category.catalog_family];
    ensure!(
        family.is_object(),
        "catalog pack lacks family {}",
        category.catalog_family
    );
    let generation = &config.scenario.catalog.generation;
    let product_key = definition.map_or_else(
        || {
            format!(
                "{}-{}-{sequence:03}",
                market.market_id, category.category_id
            )
        },
        |row| row.product_id.clone(),
    );
    let category_position = department
        .categories
        .iter()
        .position(|row| row.category_id == category.category_id)
        .context("category not in department")?;
    let category_sequence =
        sequence.saturating_sub(1 + category_position) / department.categories.len();
    let references = family["products"]
        .as_array()
        .context("catalog family products")?;
    let reference = &references[category_sequence % references.len()];
    let brand = definition.map_or_else(
        || value_str(reference, "brand").to_owned(),
        |row| row.brand.clone(),
    );
    let brand_code = definition.map_or_else(
        || value_str(reference, "brandCode").to_owned(),
        |row| row.brand_code.clone(),
    );
    let title = definition.map_or_else(
        || value_str(reference, "name").to_owned(),
        |row| row.title.clone(),
    );
    let material = definition.map_or_else(
        || value_str(reference, "material").to_owned(),
        |row| {
            if row.material.is_empty() {
                value_str(reference, "material").to_owned()
            } else {
                row.material.clone()
            }
        },
    );
    let description = definition.map_or_else(
        || format!(
            "Synthetic retail listing for {title}; brand and product-line identity are real reference data, while price, demand and operations are simulated."
        ),
        |row| row.description.clone(),
    );
    let product_code = definition.map_or_else(
        || {
            format!(
                "{}-{}-{}-{sequence:03}",
                generation.sku_prefix,
                market.country_code,
                value_str(family, "categoryCode")
            )
        },
        |row| row.product_code.clone(),
    );
    let base_price = definition.map_or_else(
        || generated_price(master_seed, &product_key, family, market),
        |row| parse_decimal(&row.base_price),
    )?;
    let target_margin = decimal_from_f64(category.target_margin);
    let margin_delta = decimal_between(
        master_seed,
        "catalog-margin",
        &product_key,
        dec("-0.04"),
        dec("0.04"),
    );
    let base_cost = definition.map_or_else(
        || {
            Ok(quantize(
                base_price * (Decimal::ONE - target_margin - margin_delta),
                2,
            ))
        },
        |row| parse_decimal(&row.base_cost),
    )?;
    let start = config.scenario.time.start_date;
    let end = config.scenario.time.end_date;
    let horizon = (end - start).num_days().max(1);
    let launch_spread_days =
        round_half_even_f64(horizon as f64 * generation.launch_spread_pct) as i64;
    let launch_date = if let Some(row) = definition {
        row.launch_date
    } else {
        let (generated_index, generated_total) = generated_lifecycle_position
            .context("generated product requires lifecycle position")?;
        let incumbent_count =
            ((generated_total as f64) * generation.incumbent_product_pct).ceil() as usize;
        if generated_index <= incumbent_count {
            start
                - Duration::days(stable_seeded(
                    master_seed,
                    &["catalog-launch-history", &product_key],
                    u64::from(generation.launch_history_days) + 1,
                ) as i64)
        } else {
            (start
                + Duration::days(
                    1 + stable_seeded(
                        master_seed,
                        &["catalog-launch-forward", &product_key],
                        launch_spread_days.max(1) as u64,
                    ) as i64,
                ))
            .min(end)
        }
    };
    let mut discontinue_date = definition.and_then(|row| row.discontinue_date);
    if definition.is_none()
        && launch_date < end
        && PythonRandom::new(master_seed, &["catalog-discontinue", &product_key]).random()
            < generation.discontinue_rate
    {
        let life_days = u64::from(generation.min_product_life_days)
            + stable_seeded(
                master_seed,
                &["catalog-product-life", &product_key],
                u64::from(generation.max_product_life_days - generation.min_product_life_days) + 1,
            );
        let candidate = launch_date + Duration::days(life_days as i64);
        if candidate <= end {
            discontinue_date = Some(candidate);
        }
    }
    let dimensions = definition.map_or_else(
        || category.option_dimensions.as_slice(),
        |row| {
            if row.option_dimensions.is_empty() {
                category.option_dimensions.as_slice()
            } else {
                row.option_dimensions.as_slice()
            }
        },
    );
    let combinations = if let Some(row) = definition {
        if row.variant_definitions.is_empty() {
            partial_combinations(pack, dimensions, variant_count, master_seed, &product_key)?
        } else {
            explicit_combinations(pack, dimensions, row, variant_count)?
        }
    } else {
        partial_combinations(pack, dimensions, variant_count, master_seed, &product_key)?
    };
    ensure!(
        combinations.len() >= variant_count,
        "{} requests {} variants but its option matrix provides {}",
        product_key,
        variant_count,
        combinations.len()
    );
    let popularity = normalized_popularity(master_seed, &product_key, variant_count);
    let product_popularity = decimal_from_f64(
        PythonRandom::new(
            master_seed,
            &["product-popularity", &market.market_id, &product_key],
        )
        .gauss(0.0, 1.25)
        .exp(),
    );
    let launch_profile = definition.map_or_else(
        || value_str(&generation.lifecycle, "defaultLaunchProfile").to_owned(),
        |row| row.launch_profile.clone(),
    );
    let variant_launch_spread = definition.map_or(generation.variant_launch_spread_days, |row| {
        row.variant_launch_spread_days
    });
    let mut variants = Vec::with_capacity(variant_count);
    for (index, (options, demand_weight)) in combinations
        .into_iter()
        .zip(popularity)
        .enumerate()
        .take(variant_count)
    {
        let position = index + 1;
        let option_code = options
            .iter()
            .map(|row| row.code.as_str())
            .collect::<Vec<_>>()
            .join("-");
        let variant_code = option_code.chars().take(20).collect::<String>();
        let sku = format!("{product_code}-{option_code}");
        let variant_key = format!("{product_key}:{option_code}");
        let option_multiplier = option_price_multiplier(&options);
        let price = snap_price(
            base_price
                * option_multiplier
                * (Decimal::ONE
                    + decimal_between(
                        master_seed,
                        "variant-price",
                        &variant_key,
                        dec("-0.015"),
                        dec("0.015"),
                    )),
            market,
        )?;
        let cost = quantize(
            base_cost
                * option_multiplier
                * (Decimal::ONE
                    + decimal_between(
                        master_seed,
                        "variant-cost",
                        &variant_key,
                        dec("-0.03"),
                        dec("0.06"),
                    )),
            2,
        );
        let elasticity = quantize(
            decimal_between(
                master_seed,
                "variant-elasticity",
                &variant_key,
                decimal_from_f64(category.elasticity_min),
                decimal_from_f64(category.elasticity_max),
            ),
            4,
        );
        let return_delta = decimal_from_f64(
            PythonRandom::new(master_seed, &["variant-return", &variant_key]).gauss(0.0, 0.015),
        );
        let return_probability = quantize(
            (decimal_from_f64(category.base_return_rate) + return_delta)
                .clamp(Decimal::ZERO, dec("0.50")),
            4,
        );
        let mut variant_launch_date = launch_date;
        if position > 1 && variant_launch_spread > 0 {
            variant_launch_date = (launch_date
                + Duration::days(stable_seeded(
                    master_seed,
                    &["variant-launch", &variant_key],
                    u64::from(variant_launch_spread) + 1,
                ) as i64))
            .min(end);
        }
        if let Some(discontinue) = discontinue_date {
            variant_launch_date = variant_launch_date.min(discontinue);
        }
        let (unit_of_measure, measurement_value, measurement_unit) =
            measurement(&category.catalog_family, &options);
        variants.push(Variant {
            market_id: market.market_id.clone(),
            currency_code: market.currency_code.clone(),
            variant_key,
            variant_code,
            sku: sku.clone(),
            title: options
                .iter()
                .map(|row| row.value.as_str())
                .collect::<Vec<_>>()
                .join(" / "),
            barcode: barcode(value_str(pack, "barcodeFormat"), &sku),
            options,
            position,
            base_price: price,
            base_cost: cost,
            demand_weight: quantize(demand_weight * product_popularity, 6),
            elasticity,
            return_probability,
            unit_of_measure,
            measurement_value,
            measurement_unit: measurement_unit.clone(),
            weight: weight_grams(measurement_value, &measurement_unit),
            weight_unit: "g".to_owned(),
            launch_date: variant_launch_date,
            discontinue_date,
        });
    }
    let shelf_life_days = family["shelfLifeDays"].as_i64().map(|value| {
        round_half_even_f64(
            value as f64
                * (0.80
                    + stable_seeded(master_seed, &["shelf-life", &product_key], 41) as f64 / 100.0),
        )
        .max(1.0) as i64
    });
    Ok(Product {
        market_id: market.market_id.clone(),
        product_key,
        product_code,
        title,
        description,
        brand,
        brand_code,
        department_id: department.department_id.clone(),
        category_id: category.category_id.clone(),
        catalog_family: category.catalog_family.clone(),
        tax_category: category.tax_category.clone(),
        unit_of_measure: family_measurement(&category.catalog_family).0.to_owned(),
        material,
        launch_date,
        discontinue_date,
        successor_of_product_code: definition
            .map(|row| row.successor_of_product_code.clone())
            .unwrap_or_default(),
        successor_product_code: String::new(),
        successor_launch_date: None,
        launch_profile,
        lifecycle: generation.lifecycle.clone(),
        seasonality_peak_month: category.seasonality_peak_month,
        seasonality_strength: decimal_from_f64(category.seasonality_strength),
        costing_method: category.costing_method.clone(),
        shelf_life_days,
        country_of_origin: value_str(pack, "countryOfOrigin").to_owned(),
        variants,
    })
}

fn generated_price(
    master_seed: u64,
    key: &str,
    family: &Value,
    market: &Market,
) -> Result<Decimal> {
    let minimum = parse_decimal(value_str(&family["priceBand"], "min"))?;
    let maximum = parse_decimal(value_str(&family["priceBand"], "max"))?;
    let mut random = PythonRandom::new(master_seed, &["catalog-price", key]);
    let raw = minimum + (maximum - minimum) * decimal_from_f64(random.random().powf(1.7));
    let endings = price_endings(market)?;
    let ending = parse_decimal(&endings[stable_integer(&[key], endings.len() as u64) as usize])?
        / Decimal::from(100_u32);
    let whole = quantize(raw, 0);
    Ok(quantize((whole + ending).clamp(minimum, maximum), 2))
}

fn decimal_between(
    master_seed: u64,
    purpose: &str,
    key: &str,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal {
    let value = PythonRandom::new(master_seed, &[purpose, key]).random();
    minimum + (maximum - minimum) * decimal_from_f64(value)
}

fn snap_price(value: Decimal, market: &Market) -> Result<Decimal> {
    let endings = price_endings(market)?;
    let whole = value
        .trunc()
        .to_string()
        .parse::<i64>()
        .context("price major units")?;
    let mut candidates = Vec::new();
    for major in 0_i64.max(whole - 1)..=(whole + 1) {
        for ending in &endings {
            let candidate = Decimal::from(major) + parse_decimal(ending)? / Decimal::from(100_u32);
            if candidate > Decimal::ZERO {
                candidates.push(candidate);
            }
        }
    }
    let chosen = candidates
        .into_iter()
        .min_by_key(|candidate| ((candidate - value).abs(), *candidate))
        .context("no positive price ending")?;
    Ok(quantize(chosen, 2))
}

fn price_endings(market: &Market) -> Result<Vec<String>> {
    market.locale_pack["currency"]["priceEndings"]
        .as_array()
        .context("locale currency.priceEndings")?
        .iter()
        .map(|row| {
            row.as_str()
                .map(str::to_owned)
                .context("price ending must be a string")
        })
        .collect()
}

fn explicit_combinations(
    pack: &Value,
    dimensions: &[String],
    definition: &ProductTemplate,
    count: usize,
) -> Result<Vec<Vec<OptionValue>>> {
    definition
        .variant_definitions
        .iter()
        .take(count)
        .map(|variant| {
            dimensions
                .iter()
                .map(|dimension| {
                    let wanted = variant
                        .option_values
                        .get(dimension)
                        .with_context(|| format!("missing option {dimension}"))?;
                    option_values(pack, dimension)?
                        .iter()
                        .find(|row| value_str(row, "name") == wanted)
                        .map(|value| option_from_value(dimension, value))
                        .transpose()?
                        .with_context(|| format!("unknown {dimension} option {wanted}"))
                })
                .collect()
        })
        .collect()
}

fn partial_combinations(
    pack: &Value,
    dimensions: &[String],
    count: usize,
    master_seed: u64,
    product_key: &str,
) -> Result<Vec<Vec<OptionValue>>> {
    let lists = dimensions
        .iter()
        .map(|dimension| {
            option_values(pack, dimension)?
                .iter()
                .map(|value| option_from_value(dimension, value))
                .collect::<Result<Vec<_>>>()
        })
        .collect::<Result<Vec<_>>>()?;
    let mut combinations = vec![Vec::new()];
    for list in lists {
        let mut expanded = Vec::with_capacity(combinations.len() * list.len());
        for prefix in &combinations {
            for option in &list {
                let mut row = prefix.clone();
                row.push(option.clone());
                expanded.push(row);
            }
        }
        combinations = expanded;
    }
    PythonRandom::new(master_seed, &["variant-combinations", product_key])
        .shuffle(&mut combinations);
    combinations.truncate(count.min(combinations.len()));
    Ok(combinations)
}

fn option_values<'a>(pack: &'a Value, dimension: &str) -> Result<&'a Vec<Value>> {
    pack["optionValues"][dimension]
        .as_array()
        .with_context(|| format!("catalog pack lacks option dimension {dimension}"))
}

fn option_from_value(dimension: &str, value: &Value) -> Result<OptionValue> {
    Ok(OptionValue {
        name: dimension.to_owned(),
        value: value_str(value, "name").to_owned(),
        code: value_str(value, "code").to_owned(),
    })
}

fn normalized_popularity(master_seed: u64, product_key: &str, count: usize) -> Vec<Decimal> {
    let mut random = PythonRandom::new(master_seed, &["variant-popularity", product_key]);
    let draws = (0..count)
        .map(|_| decimal_from_f64(-random.random().max(1e-12).ln()))
        .collect::<Vec<_>>();
    let total = draws.iter().copied().sum::<Decimal>();
    draws
        .into_iter()
        .map(|value| quantize(value / total, 6))
        .collect()
}

fn option_price_multiplier(options: &[OptionValue]) -> Decimal {
    let mut multiplier = Decimal::ONE;
    for option in options {
        multiplier *= match option.name.as_str() {
            "storage" => match option.code.as_str() {
                "64G" => dec("0.86"),
                "128G" => Decimal::ONE,
                "256G" => dec("1.16"),
                "512G" => dec("1.375"),
                "1TB" => dec("1.65"),
                _ => Decimal::ONE,
            },
            "packSize" => Decimal::ONE + (pack_count(&option.code) - Decimal::ONE) * dec("0.82"),
            "power" => match option.code.as_str() {
                "750W" => Decimal::ONE,
                "1000W" => dec("1.08"),
                "1500W" => dec("1.18"),
                "2000W" => dec("1.28"),
                _ => Decimal::ONE,
            },
            "connectivity" => match option.code.as_str() {
                "CELL" => dec("1.22"),
                _ => Decimal::ONE,
            },
            "packVolume" | "packWeight" => pack_fill(&option.code).1,
            _ => Decimal::ONE,
        };
    }
    multiplier
}

fn measurement(family: &str, options: &[OptionValue]) -> (String, Decimal, String) {
    let (unit, nominal, measurement_unit) = family_measurement(family);
    if let Some(fill) = options
        .iter()
        .find(|row| matches!(row.name.as_str(), "packVolume" | "packWeight"))
    {
        return (
            unit.to_owned(),
            pack_fill(&fill.code).0,
            measurement_unit.to_owned(),
        );
    }
    let count = options
        .iter()
        .find(|row| row.name == "packSize")
        .map_or(Decimal::ONE, |row| pack_count(&row.code));
    (
        unit.to_owned(),
        nominal * count,
        measurement_unit.to_owned(),
    )
}

fn family_measurement(family: &str) -> (&'static str, Decimal, &'static str) {
    match family {
        "grocery-staples" => ("KG", dec("1000"), "g"),
        "grocery-snacks" => ("G", dec("150"), "g"),
        "grocery-beverages" => ("ML", dec("500"), "ml"),
        "grocery-dairy" => ("ML", dec("1000"), "ml"),
        "home-cleaning" => ("ML", dec("750"), "ml"),
        "beauty-skincare" => ("ML", dec("200"), "ml"),
        "beauty-haircare" => ("ML", dec("300"), "ml"),
        "beauty-cosmetics" => ("G", dec("30"), "g"),
        "beauty-grooming" => ("ML", dec("200"), "ml"),
        "health-vitamins" => ("EA", dec("30"), "count"),
        "health-otc" => ("EA", dec("20"), "count"),
        "health-first-aid" => ("EA", dec("10"), "count"),
        "baby-care" => ("EA", dec("24"), "count"),
        "baby-feeding" => ("G", dec("400"), "g"),
        "stationery-writing" => ("EA", dec("5"), "count"),
        "automotive-car-care" => ("ML", dec("500"), "ml"),
        "automotive-oils"
        | "lubricants-motorcycle"
        | "lubricants-pcmo"
        | "lubricants-diesel-engine"
        | "lubricants-tractor"
        | "lubricants-gear"
        | "lubricants-transmission"
        | "lubricants-coolant-brake"
        | "lubricants-hydraulic"
        | "lubricants-industrial"
        | "lubricants-adblue"
        | "lubricants-ev-fluids" => ("ML", dec("1000"), "ml"),
        "lubricants-grease" => ("G", dec("1000"), "g"),
        _ => ("EA", Decimal::ONE, "count"),
    }
}

fn pack_count(code: &str) -> Decimal {
    match code {
        "1PK" => Decimal::ONE,
        "2PK" => dec("2"),
        "6PK" => dec("6"),
        "FAM" => dec("4"),
        _ => Decimal::ONE,
    }
}

fn pack_fill(code: &str) -> (Decimal, Decimal) {
    match code {
        "500ML" => (dec("500"), dec("0.58")),
        "900ML" => (dec("900"), dec("0.95")),
        "1L" => (dec("1000"), Decimal::ONE),
        "3L5" => (dec("3500"), dec("3.25")),
        "5L" => (dec("5000"), dec("4.55")),
        "7L5" => (dec("7500"), dec("6.75")),
        "10L" => (dec("10000"), dec("8.80")),
        "20L" => (dec("20000"), dec("17")),
        "26L" => (dec("26000"), dec("21.80")),
        "50L" => (dec("50000"), dec("41")),
        "210L" => (dec("210000"), dec("168")),
        "500G" => (dec("500"), dec("0.58")),
        "1KG" => (dec("1000"), Decimal::ONE),
        "5KG" => (dec("5000"), dec("4.55")),
        "18KG" => (dec("18000"), dec("15.60")),
        "180KG" => (dec("180000"), dec("148")),
        _ => (Decimal::ONE, Decimal::ONE),
    }
}

fn weight_grams(value: Decimal, unit: &str) -> Decimal {
    match unit {
        "g" | "ml" => value,
        "kg" | "l" => value * Decimal::from(1000_u32),
        _ => Decimal::ZERO,
    }
}

fn barcode(format: &str, sku: &str) -> String {
    let body = if format == "UPCA" {
        format!("4{:010}", stable_integer(&["barcode", sku], 10_000_000_000))
    } else {
        format!("020{:09}", stable_integer(&["barcode", sku], 1_000_000_000))
    };
    let total = body
        .bytes()
        .enumerate()
        .map(|(index, byte)| {
            u32::from(byte - b'0') * if (body.len() - index) % 2 == 1 { 3 } else { 1 }
        })
        .sum::<u32>();
    format!("{body}{}", (10 - total % 10) % 10)
}

fn link_successors(config: &LoadedConfig, market: &Market, products: &mut [Product]) -> Result<()> {
    let explicit_codes = config
        .scenario
        .catalog
        .product_templates
        .iter()
        .filter(|row| row.market_id == market.market_id)
        .map(|row| row.product_code.clone())
        .collect::<BTreeSet<_>>();
    let mut by_family = BTreeMap::<String, Vec<usize>>::new();
    for (index, product) in products.iter().enumerate() {
        by_family
            .entry(product.catalog_family.clone())
            .or_default()
            .push(index);
    }
    for indexes in by_family.values_mut() {
        indexes.sort_by_key(|index| {
            (
                products[*index].launch_date,
                products[*index].product_code.clone(),
            )
        });
        for pair in indexes.windows(2) {
            let prior = pair[0];
            let current = pair[1];
            if explicit_codes.contains(&products[prior].product_code)
                || explicit_codes.contains(&products[current].product_code)
                || !products[current].successor_of_product_code.is_empty()
                || products[current].launch_date <= products[prior].launch_date
            {
                continue;
            }
            if PythonRandom::new(
                config.scenario.identity.master_seed,
                &[
                    "catalog-replacement",
                    &market.market_id,
                    &products[current].product_code,
                ],
            )
            .random()
                < config.scenario.catalog.generation.replacement_link_rate
            {
                products[current].successor_of_product_code = products[prior].product_code.clone();
            }
        }
    }
    let links = products
        .iter()
        .filter(|row| !row.successor_of_product_code.is_empty())
        .map(|row| {
            (
                row.successor_of_product_code.clone(),
                row.product_code.clone(),
                row.launch_date,
            )
        })
        .collect::<Vec<_>>();
    let runout_months = config.scenario.catalog.generation.lifecycle["runoutMonths"]
        .as_i64()
        .context("lifecycle.runoutMonths")?;
    for (predecessor_code, successor_code, successor_launch) in links {
        if let Some(predecessor) = products
            .iter_mut()
            .find(|row| row.product_code == predecessor_code)
        {
            let runout_end = successor_launch + Duration::days(30 * runout_months);
            if predecessor
                .discontinue_date
                .is_none_or(|end| end < runout_end)
            {
                predecessor.discontinue_date = Some(runout_end);
                for variant in &mut predecessor.variants {
                    variant.discontinue_date = Some(runout_end);
                }
            }
            predecessor.successor_product_code = successor_code;
            predecessor.successor_launch_date = Some(successor_launch);
        }
    }
    Ok(())
}

fn validate_catalog(config: &LoadedConfig, products: &[Product]) -> Result<()> {
    for market in &config.scenario.markets {
        let market_products = products
            .iter()
            .filter(|row| row.market_id == market.market_id);
        let mut product_codes = BTreeSet::new();
        let mut skus = BTreeSet::new();
        let mut barcodes = BTreeSet::new();
        let mut variants = 0_usize;
        for product in market_products {
            ensure!(
                product_codes.insert(&product.product_code),
                "duplicate product code"
            );
            for variant in &product.variants {
                variants += 1;
                ensure!(skus.insert(&variant.sku), "duplicate SKU {}", variant.sku);
                ensure!(
                    barcodes.insert(&variant.barcode),
                    "duplicate barcode {}",
                    variant.barcode
                );
                ensure!(
                    variant.base_cost >= Decimal::ZERO,
                    "negative cost for {}",
                    variant.sku
                );
                ensure!(
                    variant.base_price >= variant.base_cost,
                    "price below cost for {}",
                    variant.sku
                );
            }
        }
        ensure!(variants > 0, "market {} has no variants", market.market_id);
    }
    Ok(())
}

fn catalog_pack(market: &Market) -> Result<&'static Value> {
    static PACKS: OnceLock<Value> = OnceLock::new();
    let packs =
        PACKS.get_or_init(|| serde_json::from_str(PACKS_JSON).expect("embedded catalog packs"));
    let id = market.catalog_pack["id"]
        .as_str()
        .with_context(|| format!("market {} has no catalogPack.id", market.market_id))?;
    packs
        .get(id)
        .with_context(|| format!("unsupported catalog pack {id}"))
}

fn stable_seeded(master_seed: u64, parts: &[&str], modulo: u64) -> u64 {
    let seed = master_seed.to_string();
    let mut all = Vec::with_capacity(parts.len() + 1);
    all.push(seed.as_str());
    all.extend_from_slice(parts);
    stable_integer(&all, modulo)
}

fn parse_decimal(value: &str) -> Result<Decimal> {
    Decimal::from_str(value).with_context(|| format!("invalid decimal {value:?}"))
}

fn dec(value: &str) -> Decimal {
    Decimal::from_str(value).expect("constant decimal")
}

fn decimal_from_f64(value: f64) -> Decimal {
    Decimal::from_str(&value.to_string()).expect("finite decimal float")
}

fn quantize(value: Decimal, scale: u32) -> Decimal {
    let mut rounded = value.round_dp_with_strategy(scale, RoundingStrategy::MidpointNearestEven);
    rounded.rescale(scale);
    rounded
}

fn value_str<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}

/// Python's JSON comparison form: market dictionary and Decimal/date values rendered as strings.
#[must_use]
pub fn comparison_value(config: &LoadedConfig, catalog: &[Product]) -> Value {
    let mut markets = Map::new();
    for market in &config.scenario.markets {
        let rows = catalog
            .iter()
            .filter(|row| row.market_id == market.market_id)
            .map(product_comparison_value)
            .collect::<Vec<_>>();
        markets.insert(market.market_id.clone(), Value::Array(rows));
    }
    Value::Object(markets)
}

fn product_comparison_value(product: &Product) -> Value {
    json!({
        "productKey": product.product_key,
        "productCode": product.product_code,
        "title": product.title,
        "description": product.description,
        "brand": product.brand,
        "brandCode": product.brand_code,
        "departmentId": product.department_id,
        "categoryId": product.category_id,
        "catalogFamily": product.catalog_family,
        "taxCategory": product.tax_category,
        "unitOfMeasure": product.unit_of_measure,
        "material": product.material,
        "launchDate": product.launch_date.to_string(),
        "discontinueDate": product.discontinue_date.map_or_else(String::new, |value| value.to_string()),
        "successorOfProductCode": product.successor_of_product_code,
        "successorProductCode": product.successor_product_code,
        "successorLaunchDate": product.successor_launch_date.map_or_else(String::new, |value| value.to_string()),
        "launchProfile": product.launch_profile,
        "lifecycle": product.lifecycle,
        "seasonalityPeakMonth": product.seasonality_peak_month,
        "seasonalityStrength": product.seasonality_strength.to_string(),
        "costingMethod": product.costing_method,
        "shelfLifeDays": product.shelf_life_days,
        "countryOfOrigin": product.country_of_origin,
        "variants": product.variants.iter().map(|variant| json!({
            "variantKey": variant.variant_key,
            "variantCode": variant.variant_code,
            "sku": variant.sku,
            "title": variant.title,
            "barcode": variant.barcode,
            "options": variant.options,
            "position": variant.position,
            "basePrice": variant.base_price.to_string(),
            "baseCost": variant.base_cost.to_string(),
            "demandWeight": variant.demand_weight.to_string(),
            "elasticity": variant.elasticity.to_string(),
            "returnProbability": variant.return_probability.to_string(),
            "unitOfMeasure": variant.unit_of_measure,
            "measurementValue": variant.measurement_value.to_string(),
            "measurementUnit": variant.measurement_unit,
            "weight": variant.weight.to_string(),
            "weightUnit": variant.weight_unit,
            "launchDate": variant.launch_date.to_string(),
            "discontinueDate": variant.discontinue_date.map_or_else(String::new, |value| value.to_string()),
        })).collect::<Vec<_>>(),
    })
}

#[cfg(test)]
mod tests {
    use super::{build_catalog, comparison_value};
    use crate::config::LoadedConfig;
    use crate::deterministic::sha256_hex;

    fn digest(path: &str) -> (usize, usize, String) {
        let config = LoadedConfig::load(path).expect("load config");
        let products = build_catalog(&config).expect("build catalog");
        let variants = products.iter().map(|row| row.variants.len()).sum();
        let canonical = serde_json::to_string(&comparison_value(&config, &products))
            .expect("serialize comparison catalog");
        (products.len(), variants, sha256_hex(canonical.as_bytes()))
    }

    #[test]
    fn gulf_catalog_matches_python_canonical_digest() {
        assert_eq!(
            digest("../datagen/configs/gulf-oil-india-ten-year.yaml"),
            (
                73,
                292,
                "52ce41558460383b9392d1275bec3bade5efeb4a95375275576929af2a70afc3".to_owned(),
            )
        );
    }

    #[test]
    fn retail_showcase_catalog_matches_python_canonical_digest() {
        assert_eq!(
            digest("../datagen/configs/multi-market-showcase.yaml"),
            (
                240,
                720,
                "a1255e3b0816dd4d2531f890e651de9a6cb99ead9a1e76e7d311a50398d6c39b".to_owned(),
            )
        );
    }
}
