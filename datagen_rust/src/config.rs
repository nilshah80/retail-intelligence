use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::str::FromStr;

use anyhow::{Context, Result, bail, ensure};
use chrono::NaiveDate;
use chrono_tz::Tz;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::SOURCE_SPEC_VERSION;
use crate::deterministic::sha256_hex;

#[derive(Debug, Clone)]
pub struct LoadedConfig {
    pub source_path: PathBuf,
    pub raw: Value,
    pub scenario: Scenario,
    pub canonical_json: String,
    pub config_hash: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Scenario {
    pub spec_version: String,
    pub identity: Identity,
    pub retailer: Retailer,
    pub time: TimeRange,
    pub markets: Vec<Market>,
    #[serde(default)]
    pub legal_entities: Vec<LegalEntity>,
    #[serde(default)]
    pub stores: Vec<Store>,
    #[serde(default)]
    pub warehouses: Vec<Warehouse>,
    #[serde(default)]
    pub channels: Vec<Channel>,
    #[serde(default)]
    pub customer_segments: Vec<CustomerSegment>,
    pub source_instances: SourceInstances,
    pub catalog: Catalog,
    #[serde(default)]
    pub events: Vec<Event>,
    #[serde(default)]
    pub promotions: Vec<Promotion>,
    #[serde(default)]
    pub pandemics: Vec<Value>,
    #[serde(default)]
    pub pricing_evidence: Option<PricingEvidence>,
    pub operations: Operations,
    pub output: Output,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct PricingEvidence {
    pub enabled: bool,
    pub price_known_as_of_lag_days: u32,
    pub promotion_planning_lead_days: u32,
    pub response_step_scale: u32,
    pub generation_method: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Identity {
    pub scenario_id: String,
    pub scenario_name: String,
    pub scenario_version: String,
    pub master_seed: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Retailer {
    pub retailer_id: String,
    pub name: String,
    pub reporting_currency: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TimeRange {
    pub start_date: NaiveDate,
    pub end_date: NaiveDate,
    pub generation_partition: PartitionGranularity,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum PartitionGranularity {
    Day,
    Month,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Market {
    pub market_id: String,
    pub name: String,
    pub country_code: String,
    pub currency_code: String,
    pub timezone: String,
    pub region_code: String,
    pub city: String,
    pub fx_rate_to_reporting: String,
    pub demand: Demand,
    pub customer_population: CustomerPopulation,
    pub assortment: Assortment,
    pub locale_pack: Value,
    pub catalog_pack: Value,
    #[serde(default)]
    pub signals: Value,
    #[serde(default)]
    pub price_dynamics: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Demand {
    pub starting_daily_orders: f64,
    pub average_lines_per_order: f64,
    pub annual_growth_rate: f64,
    pub demand_level_scalar: f64,
    pub day_of_week_factors: Vec<f64>,
    pub noise: f64,
    pub intermittency_rate: f64,
    pub new_product_ramp_days: u32,
    pub online_share_start: f64,
    pub online_share_end: f64,
    pub online_share_sku_variation: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CustomerPopulation {
    pub opening_registered_customers: u64,
    pub annual_new_customers: u64,
    pub annual_churn_rate: f64,
    pub annual_reactivation_rate: f64,
    pub guest_checkout_rate: f64,
    pub opening_customer_history_years: u32,
    pub max_orders_per_customer_per_day: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Assortment {
    pub skus_per_department: usize,
    pub variants_per_product: usize,
    #[serde(default)]
    pub category_assortment_weights: BTreeMap<String, f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LegalEntity {
    pub legal_entity_id: String,
    pub name: String,
    pub market_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Store {
    pub store_id: String,
    pub name: String,
    pub market_id: String,
    pub legal_entity_id: String,
    #[serde(default)]
    pub city: String,
    #[serde(default)]
    pub region_code: String,
    #[serde(default)]
    pub postcode: String,
    #[serde(default)]
    pub address_line1: String,
    pub business_central_location_code: String,
    pub demand_scale: f64,
    pub assortment_coverage: f64,
    pub channel_ids: Vec<String>,
    pub warehouse_priority: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Warehouse {
    pub warehouse_id: String,
    pub name: String,
    pub market_id: String,
    pub legal_entity_id: String,
    pub business_central_location_code: String,
    pub capacity_units: u64,
    pub opening_stock_per_sku: u64,
    pub opening_stock_days_of_cover: u32,
    pub replenishment_pack_size: u32,
    pub serves_locations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Channel {
    pub channel_id: String,
    pub market_id: String,
    pub name: String,
    #[serde(rename = "type")]
    pub channel_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CustomerSegment {
    pub segment_id: String,
    pub name: String,
    pub share: f64,
    pub demand_multiplier: f64,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceInstances {
    #[serde(default)]
    pub shopify: Vec<ShopifyInstance>,
    #[serde(default)]
    pub business_central: Vec<BusinessCentralInstance>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ShopifyInstance {
    pub shop_id: String,
    pub shop_domain: String,
    pub market_id: String,
    pub store_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct BusinessCentralInstance {
    pub company_id: String,
    pub company_name: String,
    pub legal_entity_id: String,
    pub warehouse_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Catalog {
    pub departments: Vec<Department>,
    pub generation: CatalogGeneration,
    #[serde(default)]
    pub product_templates: Vec<ProductTemplate>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Department {
    pub department_id: String,
    pub name: String,
    pub categories: Vec<Category>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Category {
    pub category_id: String,
    pub name: String,
    pub catalog_family: String,
    pub tax_category: String,
    pub costing_method: String,
    pub target_margin: f64,
    pub base_return_rate: f64,
    pub elasticity_min: f64,
    pub elasticity_max: f64,
    pub seasonality_peak_month: u32,
    pub seasonality_strength: f64,
    #[serde(default)]
    pub option_dimensions: Vec<String>,
    #[serde(default)]
    pub shelf_life_days: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CatalogGeneration {
    pub mode: String,
    pub catalog_pack_version: String,
    pub sku_prefix: String,
    pub launch_history_days: u32,
    pub incumbent_product_pct: f64,
    pub discontinue_rate: f64,
    pub launch_spread_pct: f64,
    pub variant_launch_spread_days: u32,
    pub replacement_link_rate: f64,
    pub min_product_life_days: u32,
    pub max_product_life_days: u32,
    pub lifecycle: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ProductTemplate {
    pub product_id: String,
    pub product_code: String,
    pub title: String,
    pub description: String,
    #[serde(default)]
    pub material: String,
    pub brand: String,
    pub brand_code: String,
    pub market_id: String,
    pub department_id: String,
    pub category_id: String,
    pub base_price: String,
    pub base_cost: String,
    pub launch_date: NaiveDate,
    #[serde(default, deserialize_with = "empty_string_as_none")]
    pub discontinue_date: Option<NaiveDate>,
    pub launch_profile: String,
    #[serde(default)]
    pub successor_of_product_code: String,
    #[serde(default)]
    pub option_dimensions: Vec<String>,
    pub variant_launch_spread_days: u32,
    pub variant_definitions: Vec<VariantDefinition>,
}

fn empty_string_as_none<'de, D>(deserializer: D) -> Result<Option<NaiveDate>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::Deserialize;
    let value = Option::<String>::deserialize(deserializer)?;
    match value.as_deref() {
        None | Some("") => Ok(None),
        Some(raw) => NaiveDate::parse_from_str(raw, "%Y-%m-%d")
            .map(Some)
            .map_err(serde::de::Error::custom),
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct VariantDefinition {
    #[serde(default)]
    pub option_values: BTreeMap<String, String>,
    #[serde(default)]
    pub sku: Option<String>,
    #[serde(default)]
    pub barcode: Option<String>,
    #[serde(default)]
    pub price: Option<String>,
    #[serde(default)]
    pub cost: Option<String>,
    #[serde(default)]
    pub launch_date: Option<NaiveDate>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Event {
    pub event_id: String,
    pub name: String,
    pub market_id: String,
    #[serde(rename = "type")]
    pub event_type: String,
    pub start_date: NaiveDate,
    pub end_date: NaiveDate,
    pub demand_multiplier: f64,
    pub traffic_multiplier: f64,
    pub lead_time_multiplier: f64,
    pub cost_multiplier: f64,
    pub inventory_loss_pct: f64,
    pub recovery_shape: String,
    #[serde(default)]
    pub store_id: String,
    #[serde(default)]
    pub department_ids: Vec<String>,
    #[serde(default)]
    pub category_ids: Vec<String>,
    #[serde(default)]
    pub channel_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Promotion {
    pub promotion_id: String,
    pub name: String,
    pub market_id: String,
    pub start_date: NaiveDate,
    pub end_date: NaiveDate,
    pub discount_pct: f64,
    pub demand_multiplier: f64,
    #[serde(default)]
    pub department_ids: Vec<String>,
    #[serde(default)]
    pub category_ids: Vec<String>,
    #[serde(default)]
    pub channel_ids: Vec<String>,
    #[serde(default)]
    pub customer_segment_ids: Vec<String>,
    #[serde(default)]
    pub store_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Operations {
    pub features: BTreeMap<String, bool>,
    pub fulfillment: Value,
    pub inventory: Value,
    pub returns: Value,
    pub supply_chain: Value,
    pub webhook: Value,
    #[serde(default)]
    pub store_inventory: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Output {
    pub root_directory: String,
    pub public_formats: Vec<String>,
    pub compression: Compression,
    pub write_hidden_truth: bool,
    pub overwrite: bool,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    None,
    Snappy,
    Zstd,
}

impl LoadedConfig {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let source_path = path.as_ref().to_path_buf();
        let mut stack = Vec::new();
        let mut raw = load_raw_config(&source_path, &mut stack)?;
        resolve_backward_compatible_defaults(&mut raw)?;
        let scenario: Scenario = serde_json::from_value(raw.clone())
            .with_context(|| format!("decode scenario config {}", source_path.display()))?;
        validate(&scenario)?;
        let canonical_json = serde_json::to_string(&raw).context("serialize canonical config")?;
        let config_hash = sha256_hex(canonical_json.as_bytes());
        Ok(Self {
            source_path,
            raw,
            scenario,
            canonical_json,
            config_hash,
        })
    }

    #[must_use]
    pub fn logical_days(&self) -> i64 {
        (self.scenario.time.end_date - self.scenario.time.start_date).num_days() + 1
    }

    #[must_use]
    pub fn pricing_evidence(&self) -> Option<&PricingEvidence> {
        self.scenario
            .pricing_evidence
            .as_ref()
            .filter(|evidence| evidence.enabled)
    }
}

fn load_raw_config(source_path: &Path, stack: &mut Vec<PathBuf>) -> Result<Value> {
    let canonical_path = source_path
        .canonicalize()
        .with_context(|| format!("resolve config {}", source_path.display()))?;
    if let Some(cycle_start) = stack.iter().position(|path| path == &canonical_path) {
        let mut cycle = stack[cycle_start..]
            .iter()
            .map(|path| path.display().to_string())
            .collect::<Vec<_>>();
        cycle.push(canonical_path.display().to_string());
        bail!("config extends cycle: {}", cycle.join(" -> "));
    }
    stack.push(canonical_path.clone());
    let bytes = fs::read(&canonical_path)
        .with_context(|| format!("read config {}", canonical_path.display()))?;
    let extension = canonical_path
        .extension()
        .and_then(|value| value.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();
    let mut raw: Value = match extension.as_str() {
        "json" => serde_json::from_slice(&bytes)
            .with_context(|| format!("parse JSON config {}", canonical_path.display()))?,
        "yaml" | "yml" => yaml_serde::from_slice(&bytes)
            .with_context(|| format!("parse YAML config {}", canonical_path.display()))?,
        _ => bail!("config must end in .json, .yaml, or .yml"),
    };
    let object = raw
        .as_object_mut()
        .context("scenario config root must be an object")?;
    if let Some(extends) = object.remove("extends") {
        let relative = extends
            .as_str()
            .filter(|value| !value.is_empty())
            .context("extends must be a non-empty relative path")?;
        let relative_path = Path::new(relative);
        ensure!(
            !relative_path.is_absolute(),
            "extends must be a relative path"
        );
        let directory = canonical_path.parent().context("config parent directory")?;
        let base_path = directory
            .join(relative_path)
            .canonicalize()
            .with_context(|| {
                format!(
                    "resolve extended config {} from {}",
                    relative,
                    canonical_path.display()
                )
            })?;
        ensure!(
            base_path.starts_with(directory),
            "extends must remain inside the preset directory"
        );
        let base = load_raw_config(&base_path, stack)?;
        raw = merge_config(base, raw);
    }
    stack.pop();
    Ok(raw)
}

fn merge_config(mut base: Value, overlay: Value) -> Value {
    match (&mut base, overlay) {
        (Value::Object(base_object), Value::Object(overlay_object)) => {
            for (key, value) in overlay_object {
                let merged = base_object
                    .remove(&key)
                    .map_or(value.clone(), |left| merge_config(left, value));
                base_object.insert(key, merged);
            }
            base
        }
        (_, value) => value,
    }
}

fn resolve_backward_compatible_defaults(raw: &mut Value) -> Result<()> {
    if let Some(pricing_evidence) = raw
        .get_mut("pricingEvidence")
        .map(|value| {
            value
                .as_object_mut()
                .context("pricingEvidence must be an object")
        })
        .transpose()?
    {
        pricing_evidence
            .entry("enabled")
            .or_insert_with(|| Value::from(false));
        pricing_evidence
            .entry("priceKnownAsOfLagDays")
            .or_insert_with(|| Value::from(0));
        pricing_evidence
            .entry("promotionPlanningLeadDays")
            .or_insert_with(|| Value::from(28));
        pricing_evidence
            .entry("responseStepScale")
            .or_insert_with(|| Value::from(1));
        pricing_evidence
            .entry("generationMethod")
            .or_insert_with(|| Value::from("deterministic-response-profile-v1"));
    }
    let response_step_scale = raw
        .get("pricingEvidence")
        .and_then(|value| value.get("responseStepScale"))
        .and_then(Value::as_u64);
    if let Some(response_step_scale) = response_step_scale {
        let markets = raw
            .get_mut("markets")
            .and_then(Value::as_array_mut)
            .context("markets must be an array")?;
        for market in markets {
            market
                .get_mut("priceDynamics")
                .and_then(Value::as_object_mut)
                .context("market.priceDynamics must be an object")?
                .insert(
                    "responseStepScale".to_owned(),
                    Value::from(response_step_scale),
                );
        }
    }
    let operations = raw
        .get_mut("operations")
        .and_then(Value::as_object_mut)
        .context("operations must be an object")?;
    let inventory = operations
        .get_mut("inventory")
        .and_then(Value::as_object_mut)
        .context("operations.inventory must be an object")?;
    inventory
        .entry("replenishmentDemandBufferPct")
        .or_insert_with(|| Value::from(0.05));
    inventory
        .entry("qualityControlHoldDays")
        .or_insert_with(|| Value::from(1));

    const STORE_INVENTORY_DEFAULTS: [(&str, u64); 9] = [
        ("snapshotCadenceDays", 7),
        ("reviewCycleDays", 7),
        ("targetDaysOfCover", 14),
        ("safetyStockUnits", 3),
        ("replenishmentPackSize", 6),
        ("openingDaysOfCover", 10),
        ("residualWorkoffWeeks", 26),
        ("primaryLaneTransitDays", 1),
        ("spillLaneTransitDays", 2),
    ];
    let store_inventory = operations
        .entry("storeInventory")
        .or_insert_with(|| Value::Object(serde_json::Map::new()))
        .as_object_mut()
        .context("operations.storeInventory must be an object")?;
    for (field, default) in STORE_INVENTORY_DEFAULTS {
        store_inventory
            .entry(field)
            .or_insert_with(|| Value::from(default));
    }
    Ok(())
}

fn unique<'a>(label: &str, values: impl IntoIterator<Item = &'a str>) -> Result<BTreeSet<String>> {
    let mut seen = BTreeSet::new();
    for value in values {
        ensure!(!value.trim().is_empty(), "{label} contains an empty id");
        ensure!(
            seen.insert(value.to_owned()),
            "duplicate {label} id: {value}"
        );
    }
    Ok(seen)
}

fn validate(config: &Scenario) -> Result<()> {
    ensure!(
        config.spec_version == SOURCE_SPEC_VERSION,
        "unsupported specVersion {}; expected {SOURCE_SPEC_VERSION}",
        config.spec_version
    );
    ensure!(
        config.time.start_date <= config.time.end_date,
        "time.startDate must not be after time.endDate"
    );
    ensure!(
        !config.identity.scenario_id.trim().is_empty(),
        "identity.scenarioId is required"
    );
    if let Some(evidence) = &config.pricing_evidence {
        ensure!(
            matches!(evidence.response_step_scale, 1 | 2),
            "pricingEvidence.responseStepScale must be 1 or 2"
        );
        ensure!(
            !evidence.generation_method.is_empty()
                && evidence.generation_method.chars().all(|character| {
                    character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-')
                }),
            "pricingEvidence.generationMethod must be a logical identifier"
        );
    }
    ensure!(
        !config.markets.is_empty(),
        "at least one market is required"
    );
    ensure!(!config.stores.is_empty(), "at least one store is required");
    ensure!(
        !config.warehouses.is_empty(),
        "at least one warehouse is required"
    );
    ensure!(
        config
            .output
            .public_formats
            .iter()
            .any(|value| value == "parquet"),
        "Rust datagen requires parquet in output.publicFormats"
    );

    let market_ids = unique(
        "market",
        config.markets.iter().map(|row| row.market_id.as_str()),
    )?;
    let legal_ids = unique(
        "legalEntity",
        config
            .legal_entities
            .iter()
            .map(|row| row.legal_entity_id.as_str()),
    )?;
    let store_ids = unique(
        "store",
        config.stores.iter().map(|row| row.store_id.as_str()),
    )?;
    let warehouse_ids = unique(
        "warehouse",
        config
            .warehouses
            .iter()
            .map(|row| row.warehouse_id.as_str()),
    )?;
    let channel_ids = unique(
        "channel",
        config.channels.iter().map(|row| row.channel_id.as_str()),
    )?;
    let segment_ids = unique(
        "customerSegment",
        config
            .customer_segments
            .iter()
            .map(|row| row.segment_id.as_str()),
    )?;

    for market in &config.markets {
        ensure!(
            Tz::from_str(&market.timezone).is_ok(),
            "invalid IANA timezone {}",
            market.timezone
        );
        ensure!(
            market.demand.starting_daily_orders >= 0.0,
            "negative startingDailyOrders"
        );
        ensure!(
            market.demand.average_lines_per_order >= 1.0,
            "averageLinesPerOrder must be >= 1"
        );
        ensure!(
            market.demand.day_of_week_factors.len() == 7,
            "dayOfWeekFactors must contain 7 values"
        );
        ensure!(
            (0.0..=1.0).contains(&market.demand.intermittency_rate),
            "invalid intermittencyRate"
        );
        ensure!(
            (0.0..=1.0).contains(&market.customer_population.guest_checkout_rate),
            "invalid guestCheckoutRate"
        );
    }
    for legal in &config.legal_entities {
        for market in &legal.market_ids {
            ensure!(
                market_ids.contains(market),
                "legal entity {} references unknown market {market}",
                legal.legal_entity_id
            );
        }
    }
    for store in &config.stores {
        ensure!(
            market_ids.contains(&store.market_id),
            "store {} references unknown market {}",
            store.store_id,
            store.market_id
        );
        ensure!(
            legal_ids.contains(&store.legal_entity_id),
            "store {} references unknown legal entity {}",
            store.store_id,
            store.legal_entity_id
        );
        ensure!(
            (0.0..=1.0).contains(&store.assortment_coverage),
            "invalid assortmentCoverage for {}",
            store.store_id
        );
        for channel in &store.channel_ids {
            ensure!(
                channel_ids.contains(channel),
                "store {} references unknown channel {channel}",
                store.store_id
            );
        }
        for warehouse in &store.warehouse_priority {
            ensure!(
                warehouse_ids.contains(warehouse),
                "store {} references unknown warehouse {warehouse}",
                store.store_id
            );
        }
    }
    for warehouse in &config.warehouses {
        ensure!(
            market_ids.contains(&warehouse.market_id),
            "warehouse {} references unknown market {}",
            warehouse.warehouse_id,
            warehouse.market_id
        );
        ensure!(
            legal_ids.contains(&warehouse.legal_entity_id),
            "warehouse {} references unknown legal entity {}",
            warehouse.warehouse_id,
            warehouse.legal_entity_id
        );
        for store in &warehouse.serves_locations {
            ensure!(
                store_ids.contains(store),
                "warehouse {} references unknown store {store}",
                warehouse.warehouse_id
            );
        }
    }
    for channel in &config.channels {
        ensure!(
            market_ids.contains(&channel.market_id),
            "channel {} references unknown market {}",
            channel.channel_id,
            channel.market_id
        );
        ensure!(
            matches!(
                channel.channel_type.as_str(),
                "store" | "online" | "marketplace"
            ),
            "unsupported channel type {}",
            channel.channel_type
        );
    }
    let share: f64 = config.customer_segments.iter().map(|row| row.share).sum();
    ensure!(
        (share - 1.0).abs() <= 1e-6,
        "customer segment shares must sum to 1.0; got {share}"
    );
    for shop in &config.source_instances.shopify {
        ensure!(
            market_ids.contains(&shop.market_id),
            "Shopify {} references unknown market {}",
            shop.shop_id,
            shop.market_id
        );
        for store in &shop.store_ids {
            ensure!(
                store_ids.contains(store),
                "Shopify {} references unknown store {store}",
                shop.shop_id
            );
        }
    }
    for company in &config.source_instances.business_central {
        ensure!(
            legal_ids.contains(&company.legal_entity_id),
            "Business Central {} references unknown legal entity {}",
            company.company_id,
            company.legal_entity_id
        );
        for warehouse in &company.warehouse_ids {
            ensure!(
                warehouse_ids.contains(warehouse),
                "Business Central {} references unknown warehouse {warehouse}",
                company.company_id
            );
        }
    }

    let department_ids = unique(
        "department",
        config
            .catalog
            .departments
            .iter()
            .map(|row| row.department_id.as_str()),
    )?;
    let mut category_ids = BTreeSet::new();
    for department in &config.catalog.departments {
        ensure!(
            !department.categories.is_empty(),
            "department {} has no categories",
            department.department_id
        );
        for category in &department.categories {
            ensure!(
                category_ids.insert(category.category_id.clone()),
                "duplicate category id {}",
                category.category_id
            );
            ensure!(
                (1..=12).contains(&category.seasonality_peak_month),
                "invalid seasonalityPeakMonth for {}",
                category.category_id
            );
        }
    }
    ensure!(
        matches!(
            config.catalog.generation.mode.as_str(),
            "generated" | "hybrid" | "explicit"
        ),
        "unsupported catalog generation mode {}",
        config.catalog.generation.mode
    );
    if config.catalog.generation.mode == "explicit" {
        ensure!(
            !config.catalog.product_templates.is_empty(),
            "explicit catalog requires productTemplates"
        );
    }
    let mut product_codes = BTreeSet::new();
    for product in &config.catalog.product_templates {
        ensure!(
            market_ids.contains(&product.market_id),
            "product {} references unknown market {}",
            product.product_code,
            product.market_id
        );
        ensure!(
            department_ids.contains(&product.department_id),
            "product {} references unknown department {}",
            product.product_code,
            product.department_id
        );
        ensure!(
            category_ids.contains(&product.category_id),
            "product {} references unknown category {}",
            product.product_code,
            product.category_id
        );
        ensure!(
            product_codes.insert(product.product_code.clone()),
            "duplicate productCode {}",
            product.product_code
        );
        ensure!(
            !product.variant_definitions.is_empty(),
            "product {} has no variants",
            product.product_code
        );
        ensure!(
            product.launch_date <= config.time.end_date,
            "product {} launchDate must not be after the scenario end",
            product.product_code
        );
        if let Some(discontinue_date) = product.discontinue_date {
            ensure!(
                discontinue_date >= product.launch_date,
                "product {} discontinueDate must not be before launchDate",
                product.product_code
            );
            ensure!(
                discontinue_date >= config.time.start_date,
                "product {} discontinueDate must not be before the scenario start",
                product.product_code
            );
        }
    }
    for event in &config.events {
        ensure!(
            market_ids.contains(&event.market_id),
            "event {} references unknown market {}",
            event.event_id,
            event.market_id
        );
        ensure!(
            event.start_date <= event.end_date,
            "event {} has inverted dates",
            event.event_id
        );
    }
    for promotion in &config.promotions {
        ensure!(
            market_ids.contains(&promotion.market_id),
            "promotion {} references unknown market {}",
            promotion.promotion_id,
            promotion.market_id
        );
        ensure!(
            promotion.start_date <= promotion.end_date,
            "promotion {} has inverted dates",
            promotion.promotion_id
        );
        for segment in &promotion.customer_segment_ids {
            ensure!(
                segment_ids.contains(segment),
                "promotion {} references unknown segment {segment}",
                promotion.promotion_id
            );
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use chrono::NaiveDate;

    use super::{LoadedConfig, validate};

    #[test]
    fn loads_gulf_json_and_reproduces_python_config_hash() {
        let config = LoadedConfig::load("../datagen/configs/gulf-oil-india-ten-year.yaml")
            .expect("load Gulf config");
        assert_eq!(
            config.config_hash,
            "5739b21117b4fbdcc1a0d196c0b4738db95a992f23c5398a519e51b15a0e37b5"
        );
        assert_eq!(config.logical_days(), 3_649);
        assert_eq!(config.scenario.catalog.product_templates.len(), 73);
    }

    #[test]
    fn resolves_mini_config_before_hashing_like_python() {
        let config = LoadedConfig::load("contracts/gulf-mini-parity-v13.json")
            .expect("load mini Gulf config");
        assert_eq!(
            config.config_hash,
            "e558de90db3c774aa2f110697f265e74a5c4ef63cf64153b455e796b7a6cc525"
        );
        assert_eq!(
            config.raw["operations"]["inventory"]["qualityControlHoldDays"],
            1
        );
    }

    #[test]
    fn rejects_catalog_launches_after_the_scenario_like_python() {
        let mut scenario = LoadedConfig::load("configs/gulf-oil-india-ten-year.yaml")
            .expect("load Gulf config")
            .scenario;
        scenario.time.end_date = NaiveDate::from_ymd_opt(2016, 10, 20).unwrap();
        let error = validate(&scenario).expect_err("future launch must be rejected");
        assert!(
            error
                .to_string()
                .contains("launchDate must not be after the scenario end")
        );
    }

    #[test]
    fn pricing_presets_resolve_to_python_compatible_hashes() {
        let rich = LoadedConfig::load("configs/pricing-response-rich.yaml")
            .expect("load response-rich pricing config");
        assert_eq!(
            rich.config_hash,
            "2173d4a90cb73655002ea4688b863a8531865641acd32b602678a78b7bb07116"
        );
        let evidence = rich.pricing_evidence().expect("enabled pricing evidence");
        assert_eq!(evidence.price_known_as_of_lag_days, 0);
        assert_eq!(evidence.promotion_planning_lead_days, 28);
        assert_eq!(evidence.response_step_scale, 2);

        let sparse = LoadedConfig::load("configs/pricing-evidence-sparse.yaml")
            .expect("load sparse pricing config");
        assert_eq!(
            sparse.config_hash,
            "71454229986128a1044d1b998712e64fbd6c59f07bad59e981e3ca1c6c8f586b"
        );
        assert!(sparse.pricing_evidence().is_none());
    }
}
