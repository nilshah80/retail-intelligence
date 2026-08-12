use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

use crate::catalog::{Product, build_catalog};
use crate::config::{Compression, LoadedConfig};
use crate::deterministic::{bc_uuid, sha256_hex, shopify_gid, stable_integer};
use crate::manifest::{RunManifest, SourceObject, SourceSchema};
use crate::telemetry::Telemetry;
use crate::writer::{AtomicRun, DatasetSpec, ParquetDatasetWriter, Row, file_sha256, write_json};
use crate::{ENGINE_VERSION, GENERATOR_VERSION};

#[derive(Debug, Clone, Copy, Serialize, Deserialize, clap::ValueEnum)]
#[serde(rename_all = "kebab-case")]
pub enum ProfileName {
    Safe,
    Balanced,
    Performance,
    UltraPerformance,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ExecutionProfile {
    pub schema_version: String,
    pub profile: String,
    pub market_workers: usize,
    pub partition_workers: usize,
    pub duckdb_threads: usize,
    pub memory_limit_gb: usize,
    #[serde(rename = "spoolChunkRows")]
    pub batch_rows: usize,
    pub row_storage: String,
    pub affects_run_identity: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ExecutionProfileDocument {
    schema_version: String,
    profile: String,
    datagen: DatagenExecutionSettings,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct DatagenExecutionSettings {
    market_workers: usize,
    partition_workers: usize,
    duckdb_threads: usize,
    memory_limit_gb: usize,
    spool_chunk_rows: usize,
}

impl ProfileName {
    #[must_use]
    pub fn resolve(self) -> ExecutionProfile {
        let (name, market_workers, partition_workers, duckdb_threads, memory_limit_gb, batch_rows) =
            match self {
                Self::Safe => ("safe", 1, 2, 1, 4, 10_000),
                Self::Balanced => ("balanced", 1, 4, 2, 8, 25_000),
                Self::Performance => ("performance", 2, 8, 6, 32, 50_000),
                Self::UltraPerformance => ("ultra-performance", 2, 16, 8, 64, 100_000),
            };
        ExecutionProfile {
            schema_version: "retail-execution-profile/v1".to_owned(),
            profile: name.to_owned(),
            market_workers,
            partition_workers,
            duckdb_threads,
            memory_limit_gb,
            batch_rows,
            row_storage: "bounded-disk-spool".to_owned(),
            affects_run_identity: false,
        }
        .validated()
        .expect("built-in execution profile")
    }
}

impl ExecutionProfile {
    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        let bytes =
            fs::read(path).with_context(|| format!("read execution profile {}", path.display()))?;
        let extension = path
            .extension()
            .and_then(|value| value.to_str())
            .unwrap_or_default()
            .to_ascii_lowercase();
        let raw: Value = match extension.as_str() {
            "json" => serde_json::from_slice(&bytes)
                .with_context(|| format!("parse JSON execution profile {}", path.display()))?,
            "yaml" | "yml" => yaml_serde::from_slice(&bytes)
                .with_context(|| format!("parse YAML execution profile {}", path.display()))?,
            _ => anyhow::bail!("execution profile must end in .json, .yaml, or .yml"),
        };
        let document: ExecutionProfileDocument = serde_json::from_value(raw)
            .with_context(|| format!("decode execution profile {}", path.display()))?;
        ensure!(
            document.schema_version == "retail-execution-profile/v1",
            "unsupported execution profile schema {:?}",
            document.schema_version
        );
        Self {
            schema_version: document.schema_version,
            profile: document.profile,
            market_workers: document.datagen.market_workers,
            partition_workers: document.datagen.partition_workers,
            duckdb_threads: document.datagen.duckdb_threads,
            memory_limit_gb: document.datagen.memory_limit_gb,
            batch_rows: document.datagen.spool_chunk_rows,
            row_storage: "bounded-disk-spool".to_owned(),
            affects_run_identity: false,
        }
        .validated()
    }

    fn validated(self) -> Result<Self> {
        ensure!(
            matches!(
                self.profile.as_str(),
                "safe" | "balanced" | "performance" | "ultra-performance" | "custom"
            ),
            "execution profile name must be safe, balanced, performance, ultra-performance, or custom"
        );
        ensure!(
            (1..=4).contains(&self.market_workers),
            "execution marketWorkers must be between 1 and 4"
        );
        ensure!(
            (1..=32).contains(&self.partition_workers),
            "execution partitionWorkers must be between 1 and 32"
        );
        ensure!(
            (1..=32).contains(&self.duckdb_threads),
            "execution duckdbThreads must be between 1 and 32"
        );
        ensure!(
            self.memory_limit_gb >= 1,
            "execution memoryLimitGb must be at least 1"
        );
        ensure!(
            (1..=1_000_000).contains(&self.batch_rows),
            "execution spoolChunkRows must be between 1 and 1000000"
        );
        ensure!(
            self.partition_workers <= self.memory_limit_gb.saturating_mul(4),
            "execution memoryLimitGb must provide at least 0.25 GiB per partition worker"
        );
        Ok(self)
    }
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GenerationPlan {
    pub scenario_id: String,
    pub source_spec_version: String,
    pub config_hash: String,
    pub rust_run_id: String,
    pub logical_days: i64,
    pub markets: usize,
    pub stores: usize,
    pub warehouses: usize,
    pub products: usize,
    pub variants: usize,
    pub estimated_opening_daily_orders: u64,
    pub estimated_end_daily_orders: u64,
    pub estimated_order_headers: u64,
    pub estimated_order_lines: u64,
    pub execution_profile: ExecutionProfile,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct GenerationResult {
    pub run_id: String,
    pub output_path: PathBuf,
    pub objects: usize,
    pub logical_rows: u64,
    pub elapsed_seconds: f64,
    pub peak_process_tree_rss_bytes: u64,
    pub execution_profile: ExecutionProfile,
}

#[must_use]
pub fn named_execution_profiles() -> BTreeMap<String, Value> {
    [
        ProfileName::Safe,
        ProfileName::Balanced,
        ProfileName::Performance,
        ProfileName::UltraPerformance,
    ]
    .into_iter()
    .map(|name| {
        let resolved = name.resolve();
        let profile_name = resolved.profile.clone();
        let document = json!({
            "schemaVersion": resolved.schema_version,
            "profile": resolved.profile,
            "datagen": {
                "marketWorkers": resolved.market_workers,
                "partitionWorkers": resolved.partition_workers,
                "duckdbThreads": resolved.duckdb_threads,
                "memoryLimitGb": resolved.memory_limit_gb,
                "spoolChunkRows": resolved.batch_rows,
            },
        });
        (profile_name, document)
    })
    .collect()
}

#[must_use]
pub fn rust_run_id(config: &LoadedConfig) -> String {
    let payload = json!({
        "configHash": config.config_hash,
        "generatorVersion": GENERATOR_VERSION,
        "sourceSpecVersion": config.scenario.spec_version,
    });
    let canonical = serde_json::to_string(&payload).expect("serialize run identity");
    format!("run-{}", &sha256_hex(canonical.as_bytes())[..16])
}

pub fn plan(config: &LoadedConfig, profile: &ExecutionProfile) -> Result<GenerationPlan> {
    let catalog = build_catalog(config)?;
    let variants = catalog.iter().map(|row| row.variants.len()).sum::<usize>();
    let opening = config
        .scenario
        .markets
        .iter()
        .map(|market| {
            let store_scale = config
                .scenario
                .stores
                .iter()
                .filter(|store| store.market_id == market.market_id)
                .map(|store| store.demand_scale)
                .sum::<f64>();
            market.demand.starting_daily_orders * market.demand.demand_level_scalar * store_scale
        })
        .sum::<f64>();
    let years = config.logical_days() as f64 / 365.2425;
    let end = config
        .scenario
        .markets
        .iter()
        .map(|market| {
            let store_scale = config
                .scenario
                .stores
                .iter()
                .filter(|store| store.market_id == market.market_id)
                .map(|store| store.demand_scale)
                .sum::<f64>();
            market.demand.starting_daily_orders
                * market.demand.demand_level_scalar
                * store_scale
                * (1.0 + market.demand.annual_growth_rate).powf(years)
        })
        .sum::<f64>();
    let average = (opening + end) / 2.0;
    let estimated_orders = (average * config.logical_days() as f64).round() as u64;
    let weighted_lines = config
        .scenario
        .markets
        .iter()
        .map(|market| market.demand.average_lines_per_order)
        .sum::<f64>()
        / config.scenario.markets.len() as f64;
    Ok(GenerationPlan {
        scenario_id: config.scenario.identity.scenario_id.clone(),
        source_spec_version: config.scenario.spec_version.clone(),
        config_hash: config.config_hash.clone(),
        rust_run_id: rust_run_id(config),
        logical_days: config.logical_days(),
        markets: config.scenario.markets.len(),
        stores: config.scenario.stores.len(),
        warehouses: config.scenario.warehouses.len(),
        products: catalog.len(),
        variants,
        estimated_opening_daily_orders: opening.round() as u64,
        estimated_end_daily_orders: end.round() as u64,
        estimated_order_headers: estimated_orders,
        estimated_order_lines: (estimated_orders as f64 * weighted_lines).round() as u64,
        execution_profile: profile.clone(),
    })
}

pub async fn generate(
    config: LoadedConfig,
    output_root: &Path,
    profile: ExecutionProfile,
) -> Result<GenerationResult> {
    let run_id = rust_run_id(&config);
    let telemetry = Telemetry::new();
    let sampler = telemetry.spawn_sampler();
    let atomic = AtomicRun::create(output_root, &config.scenario.identity.scenario_id, &run_id)?;
    let mut objects = Vec::new();
    let mut schemas = Vec::new();

    let catalog = {
        let _measurement = telemetry.measure("catalog");
        build_catalog(&config)?
    };
    {
        let _measurement = telemetry.measure("static-projections");
        write_exact_static_projections(
            &config,
            &catalog,
            atomic.base(),
            &profile,
            &mut objects,
            &mut schemas,
        )?;
    }

    // Transactional and operational projections are added by the streaming simulation
    // stage. Keeping the stage boundary explicit prevents a static-only artifact from being
    // mistaken for a complete comparison run while the migration is under construction.
    let simulation_pool = rayon::ThreadPoolBuilder::new()
        .num_threads(profile.partition_workers)
        .thread_name(|index| format!("datagen-simulation-{index}"))
        .build()
        .context("create profile-bounded simulation worker pool")?;
    let dynamic_result = {
        let _measurement = telemetry.measure("causal-simulation");
        simulation_pool.install(|| {
            crate::engine::streaming::generate_all(
                &config,
                &catalog,
                atomic.base(),
                &profile,
                &telemetry,
                &mut objects,
                &mut schemas,
            )
        })?
    };

    let source_schema = SourceSchema {
        schema_version: "retail-source-schema/v1".to_owned(),
        physical_type_policy: "all source fields are nullable UTF-8 strings".to_owned(),
        datasets: {
            schemas.sort_by(|left, right| left.logical_path.cmp(&right.logical_path));
            schemas.dedup_by(|left, right| left.logical_path == right.logical_path);
            schemas
        },
    };
    let source_schema_path = atomic.base().join("source-schema.json");
    write_json(&source_schema_path, &source_schema)?;
    register_metadata(
        &source_schema_path,
        atomic.base(),
        "sourceSchema",
        &mut objects,
    )?;

    let resolved_json_path = atomic.base().join("resolved-config.json");
    write_json(&resolved_json_path, &config.raw)?;
    register_metadata(
        &resolved_json_path,
        atomic.base(),
        "resolvedConfigJson",
        &mut objects,
    )?;
    let resolved_yaml_path = atomic.base().join("resolved-config.yaml");
    fs::write(
        &resolved_yaml_path,
        yaml_serde::to_string(&config.raw).context("serialize resolved YAML")?,
    )
    .context("write resolved-config.yaml")?;
    register_metadata(
        &resolved_yaml_path,
        atomic.base(),
        "resolvedConfigYaml",
        &mut objects,
    )?;

    #[cfg(feature = "duckdb-mirror")]
    {
        let _measurement = telemetry.measure("duckdb-mirror");
        let mirror_rows = crate::engine::streaming::build_duckdb_mirror(
            atomic.base(),
            &objects,
            &source_schema.datasets,
            profile.duckdb_threads,
            profile.memory_limit_gb,
        )?;
        let mirror = atomic.base().join("source-run.duckdb");
        register_source_mirror(&mirror, atomic.base(), mirror_rows, &mut objects)?;
    }

    objects.sort_by(|left, right| left.path.cmp(&right.path));
    let topology = json!({
        "markets": config.scenario.markets,
        "legalEntities": config.scenario.legal_entities,
        "stores": config.scenario.stores,
        "warehouses": config.scenario.warehouses,
        "channels": config.scenario.channels,
        "sourceInstances": config.scenario.source_instances,
    });
    let snapshot = telemetry.snapshot();
    let manifest = RunManifest {
        manifest_version: "source-run-manifest/v3".to_owned(),
        generator_version: GENERATOR_VERSION.to_owned(),
        engine: "rust".to_owned(),
        engine_version: ENGINE_VERSION.to_owned(),
        source_spec_version: config.scenario.spec_version.clone(),
        scenario_id: config.scenario.identity.scenario_id.clone(),
        scenario_version: config.scenario.identity.scenario_version.clone(),
        retailer: serde_json::to_value(&config.scenario.retailer)?,
        master_seed: config.scenario.identity.master_seed,
        config_hash: config.config_hash.clone(),
        run_id: run_id.clone(),
        run_identity_method: "sha256(rustGeneratorVersion+sourceSpecVersion+configHash)".to_owned(),
        logical_start_date: config.scenario.time.start_date.to_string(),
        logical_end_date: config.scenario.time.end_date.to_string(),
        topology,
        capabilities: config.scenario.operations.features.clone(),
        execution_profile: serde_json::to_value(&profile)?,
        execution_telemetry: serde_json::to_value(&snapshot)?,
        simulation_controls: dynamic_result.simulation_controls,
        controls_by_currency: dynamic_result.controls_by_currency,
        catalog_controls_by_market: catalog_controls(&catalog),
        objects,
    };
    write_json(&atomic.base().join("source-run-manifest.json"), &manifest)?;
    sampler.stop().await;
    let final_snapshot = telemetry.snapshot();
    let logical_rows = manifest.objects.iter().filter_map(|row| row.rows).sum();
    let object_count = manifest.objects.len();
    let output_path = atomic.promote()?;
    Ok(GenerationResult {
        run_id,
        output_path,
        objects: object_count,
        logical_rows,
        elapsed_seconds: final_snapshot.wall_seconds,
        peak_process_tree_rss_bytes: final_snapshot.peak_process_tree_rss_bytes,
        execution_profile: profile,
    })
}

fn write_exact_static_projections(
    config: &LoadedConfig,
    catalog: &[Product],
    base: &Path,
    profile: &ExecutionProfile,
    objects: &mut Vec<SourceObject>,
    schemas: &mut Vec<crate::manifest::DatasetSchema>,
) -> Result<()> {
    for dataset in crate::projection::catalog::build_catalog_datasets(config, catalog)? {
        write_projected_dataset(config, base, profile, objects, schemas, dataset)?;
    }
    for dataset in crate::projection::context::build_context_datasets(config, catalog)? {
        write_projected_dataset(config, base, profile, objects, schemas, dataset)?;
    }
    for dataset in crate::projection::signals::build_signal_datasets(config, catalog)? {
        write_projected_dataset(config, base, profile, objects, schemas, dataset)?;
    }
    Ok(())
}

fn write_projected_dataset(
    config: &LoadedConfig,
    base: &Path,
    profile: &ExecutionProfile,
    objects: &mut Vec<SourceObject>,
    schemas: &mut Vec<crate::manifest::DatasetSchema>,
    dataset: crate::projection::LogicalDataset,
) -> Result<()> {
    const PARTITION_FIELDS: &[&str] = &[
        "__partitionDate",
        "date",
        "businessDate",
        "postingDate",
        "effectiveDate",
        "effectiveFrom",
        "knownAsOf",
        "startDate",
        "observedAt",
        "validDate",
        "createdAt",
        "requestedAt",
        "processedAt",
        "issuedAt",
        "orderDate",
        "receiptDate",
        "requestDate",
        "expectedDate",
        "actualDate",
        "confirmedAt",
        "shipmentDate",
        "invoiceDate",
        "introducedDate",
        "discontinuedDate",
        "snapshotDate",
        "eventDate",
        "occurredAt",
        "rateDate",
    ];
    const UNPARTITIONED: &[&str] = &[
        "products",
        "productVariants",
        "inventoryItems",
        "locations",
        "items",
        "itemVariants",
        "companyMarketConfig",
        "vendors",
        "vendorItemTerms",
        "customerSegments",
        "storeAssortment",
        "competitorMatches",
        "catalogTruth",
        "competitorMatchTruth",
    ];
    let file_stem = crate::contracts::snake_case(&dataset.dataset);
    let logical_path = format!("{}/{file_stem}.parquet", dataset.prefix);
    let fields = crate::contracts::fields_with_pricing_evidence(
        &dataset.source_system,
        &dataset.dataset,
        config.pricing_evidence().is_some(),
    )?;
    let partition_field = if UNPARTITIONED.contains(&dataset.dataset.as_str()) {
        None
    } else {
        dataset.rows.first().and_then(|row| {
            PARTITION_FIELDS
                .iter()
                .find(|field| row.contains_key(**field))
                .copied()
        })
    };
    let mut partitions = BTreeMap::<String, Vec<BTreeMap<String, String>>>::new();
    for values in dataset.rows {
        let relative_path = if let Some(field) = partition_field {
            let raw = values.get(field).with_context(|| {
                format!("{} row lacks partition field {field}", dataset.dataset)
            })?;
            ensure!(
                raw.len() >= 10,
                "{} has invalid partition date {raw:?}",
                dataset.dataset
            );
            let date =
                chrono::NaiveDate::parse_from_str(&raw[..10], "%Y-%m-%d").with_context(|| {
                    format!("{} has invalid partition date {raw:?}", dataset.dataset)
                })?;
            match config.scenario.time.generation_partition {
                crate::config::PartitionGranularity::Month => format!(
                    "{}/{file_stem}/year={:04}/month={:02}/part.parquet",
                    dataset.prefix,
                    chrono::Datelike::year(&date),
                    chrono::Datelike::month(&date),
                ),
                crate::config::PartitionGranularity::Day => format!(
                    "{}/{file_stem}/year={:04}/month={:02}/day={:02}/part.parquet",
                    dataset.prefix,
                    chrono::Datelike::year(&date),
                    chrono::Datelike::month(&date),
                    chrono::Datelike::day(&date),
                ),
            }
        } else {
            logical_path.clone()
        };
        partitions.entry(relative_path).or_default().push(values);
    }
    if partitions.is_empty() {
        partitions.insert(logical_path.clone(), Vec::new());
    }
    for (relative_path, rows) in partitions {
        let spec = DatasetSpec {
            relative_path,
            logical_path: logical_path.clone(),
            source_system: dataset.source_system.clone(),
            dataset: dataset.dataset.clone(),
            restricted: dataset.restricted,
            fields: fields.clone(),
        };
        let mut writer = ParquetDatasetWriter::create(
            base,
            spec,
            config.scenario.output.compression,
            profile.batch_rows,
        )?;
        for values in rows {
            writer.push(
                fields
                    .iter()
                    .map(|field| values.get(field).filter(|value| !value.is_empty()).cloned())
                    .collect(),
            )?;
        }
        let (object, schema) = writer.finish()?;
        objects.push(object);
        schemas.push(schema);
    }
    Ok(())
}

#[allow(dead_code)]
fn write_static_projections(
    config: &LoadedConfig,
    catalog: &[Product],
    base: &Path,
    profile: &ExecutionProfile,
    objects: &mut Vec<SourceObject>,
    schemas: &mut Vec<crate::manifest::DatasetSchema>,
) -> Result<()> {
    for shop in &config.scenario.source_instances.shopify {
        let market = config
            .scenario
            .markets
            .iter()
            .find(|row| row.market_id == shop.market_id)
            .context("Shopify market disappeared after validation")?;
        let products = catalog
            .iter()
            .filter(|row| row.market_id == shop.market_id)
            .collect::<Vec<_>>();
        let prefix = format!("shopify/{}", shop.shop_id);
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "products",
                "shopify",
                &[
                    "createdAt",
                    "descriptionHtml",
                    "discontinueDate",
                    "handle",
                    "id",
                    "launchDate",
                    "launchProfile",
                    "predecessorProductCode",
                    "productType",
                    "publishedAt",
                    "status",
                    "successorProductCode",
                    "tags",
                    "title",
                    "vendor",
                ],
            ),
            products.iter().map(|product| {
                let id = shopify_gid("Product", &product.product_key);
                row(&[
                    ("createdAt", product.launch_date.to_string()),
                    ("descriptionHtml", product.description.clone()),
                    ("discontinueDate", option_date(product.discontinue_date)),
                    ("handle", slug(&product.title)),
                    ("id", id),
                    ("launchDate", product.launch_date.to_string()),
                    ("launchProfile", product.launch_profile.clone()),
                    (
                        "predecessorProductCode",
                        product.successor_of_product_code.clone(),
                    ),
                    ("productType", product.category_id.clone()),
                    ("publishedAt", product.launch_date.to_string()),
                    (
                        "status",
                        if product.discontinue_date.is_some() {
                            "ARCHIVED"
                        } else {
                            "ACTIVE"
                        }
                        .to_owned(),
                    ),
                    (
                        "successorProductCode",
                        product.successor_product_code.clone(),
                    ),
                    (
                        "tags",
                        format!(
                            "{},{},{}",
                            product.department_id, product.category_id, product.catalog_family
                        ),
                    ),
                    ("title", product.title.clone()),
                    ("vendor", product.brand.clone()),
                ])
            }),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "product_variants",
                "shopify",
                &[
                    "barcode",
                    "createdAt",
                    "currencyCode",
                    "discontinueDate",
                    "id",
                    "inventoryItemId",
                    "inventoryManagement",
                    "inventoryPolicy",
                    "launchDate",
                    "measurementUnit",
                    "measurementValue",
                    "option1Name",
                    "option1Value",
                    "option2Name",
                    "option2Value",
                    "option3Name",
                    "option3Value",
                    "position",
                    "predecessorProductCode",
                    "price",
                    "productId",
                    "publishedAt",
                    "sku",
                    "status",
                    "taxable",
                    "title",
                    "weight",
                    "weightUnit",
                ],
            ),
            products.iter().flat_map(|product| {
                product
                    .variants
                    .iter()
                    .enumerate()
                    .map(move |(index, variant)| {
                        let options = &variant.options;
                        row(&[
                            ("barcode", variant.barcode.clone()),
                            ("createdAt", variant.launch_date.to_string()),
                            ("currencyCode", market.currency_code.clone()),
                            ("discontinueDate", option_date(variant.discontinue_date)),
                            ("id", shopify_gid("ProductVariant", &variant.variant_key)),
                            (
                                "inventoryItemId",
                                shopify_gid("InventoryItem", &variant.variant_key),
                            ),
                            ("inventoryManagement", "SHOPIFY".to_owned()),
                            ("inventoryPolicy", "DENY".to_owned()),
                            ("launchDate", variant.launch_date.to_string()),
                            ("measurementUnit", variant.measurement_unit.clone()),
                            ("measurementValue", variant.measurement_value.to_string()),
                            (
                                "option1Name",
                                options
                                    .first()
                                    .map_or("", |row| row.name.as_str())
                                    .to_owned(),
                            ),
                            (
                                "option1Value",
                                options
                                    .first()
                                    .map_or("", |row| row.value.as_str())
                                    .to_owned(),
                            ),
                            (
                                "option2Name",
                                options
                                    .get(1)
                                    .map_or("", |row| row.name.as_str())
                                    .to_owned(),
                            ),
                            (
                                "option2Value",
                                options
                                    .get(1)
                                    .map_or("", |row| row.value.as_str())
                                    .to_owned(),
                            ),
                            (
                                "option3Name",
                                options
                                    .get(2)
                                    .map_or("", |row| row.name.as_str())
                                    .to_owned(),
                            ),
                            (
                                "option3Value",
                                options
                                    .get(2)
                                    .map_or("", |row| row.value.as_str())
                                    .to_owned(),
                            ),
                            ("position", (index + 1).to_string()),
                            (
                                "predecessorProductCode",
                                product.successor_of_product_code.clone(),
                            ),
                            ("price", variant.base_price.to_string()),
                            ("productId", shopify_gid("Product", &product.product_key)),
                            ("publishedAt", variant.launch_date.to_string()),
                            ("sku", variant.sku.clone()),
                            (
                                "status",
                                if variant.discontinue_date.is_some() {
                                    "ARCHIVED"
                                } else {
                                    "ACTIVE"
                                }
                                .to_owned(),
                            ),
                            ("taxable", "true".to_owned()),
                            ("title", variant.title.clone()),
                            ("weight", variant.weight.to_string()),
                            ("weightUnit", variant.measurement_unit.clone()),
                        ])
                    })
            }),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "inventory_items",
                "shopify",
                &[
                    "countryCodeOfOrigin",
                    "id",
                    "requiresShipping",
                    "sku",
                    "tracked",
                    "unitCostAmount",
                    "unitCostCurrencyCode",
                ],
            ),
            products.iter().flat_map(|product| {
                product.variants.iter().map(|variant| {
                    row(&[
                        ("countryCodeOfOrigin", market.country_code.clone()),
                        ("id", shopify_gid("InventoryItem", &variant.variant_key)),
                        ("requiresShipping", "true".to_owned()),
                        ("sku", variant.sku.clone()),
                        ("tracked", "true".to_owned()),
                        ("unitCostAmount", variant.base_cost.to_string()),
                        ("unitCostCurrencyCode", market.currency_code.clone()),
                    ])
                })
            }),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "locations",
                "shopify",
                &[
                    "active",
                    "address1",
                    "city",
                    "countryCode",
                    "id",
                    "locationType",
                    "name",
                    "provinceCode",
                    "timezone",
                    "zip",
                ],
            ),
            shopify_locations(config, &shop.market_id),
        )?;
    }

    for company in &config.scenario.source_instances.business_central {
        let legal = config
            .scenario
            .legal_entities
            .iter()
            .find(|row| row.legal_entity_id == company.legal_entity_id)
            .context("BC legal entity disappeared")?;
        let market_ids = legal.market_ids.iter().cloned().collect::<BTreeSet<_>>();
        let products = catalog
            .iter()
            .filter(|row| market_ids.contains(&row.market_id))
            .collect::<Vec<_>>();
        let prefix = format!("business-central/{}", company.company_id);
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "items",
                "businessCentral",
                &[
                    "baseUnitOfMeasureCode",
                    "blocked",
                    "brandName",
                    "costingMethod",
                    "countryRegionOfOriginCode",
                    "description",
                    "discontinuedDate",
                    "displayName",
                    "id",
                    "introducedDate",
                    "itemCategoryCode",
                    "number",
                    "predecessorItemNumber",
                    "type",
                    "vendorId",
                    "vendorName",
                    "vendorNumber",
                ],
            ),
            products.iter().map(|product| {
                let market = market_for(config, &product.market_id);
                row(&[
                    ("baseUnitOfMeasureCode", "PCS".to_owned()),
                    ("blocked", product.discontinue_date.is_some().to_string()),
                    ("brandName", product.brand.clone()),
                    ("costingMethod", product.costing_method.clone()),
                    ("countryRegionOfOriginCode", market.country_code.clone()),
                    ("description", product.description.clone()),
                    ("discontinuedDate", option_date(product.discontinue_date)),
                    ("displayName", product.title.clone()),
                    ("id", bc_uuid("item", &product.product_key)),
                    ("introducedDate", product.launch_date.to_string()),
                    ("itemCategoryCode", product.category_id.clone()),
                    ("number", product.product_code.clone()),
                    (
                        "predecessorItemNumber",
                        product.successor_of_product_code.clone(),
                    ),
                    ("type", "Inventory".to_owned()),
                    (
                        "vendorId",
                        bc_uuid(
                            "vendor",
                            &format!("{}:{}", product.market_id, product.brand_code),
                        ),
                    ),
                    ("vendorName", product.brand.clone()),
                    ("vendorNumber", product.brand_code.clone()),
                ])
            }),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "item_variants",
                "businessCentral",
                &[
                    "barcode",
                    "blocked",
                    "code",
                    "currencyCode",
                    "description",
                    "discontinuedDate",
                    "id",
                    "introducedDate",
                    "itemId",
                    "itemNumber",
                    "measurementUnit",
                    "measurementValue",
                    "predecessorItemNumber",
                    "sku",
                    "unitCost",
                    "unitOfMeasureCode",
                    "unitPrice",
                ],
            ),
            products.iter().flat_map(|product| {
                product.variants.iter().map(|variant| {
                    row(&[
                        ("barcode", variant.barcode.clone()),
                        ("blocked", variant.discontinue_date.is_some().to_string()),
                        ("code", variant.variant_code.clone()),
                        (
                            "currencyCode",
                            market_for(config, &variant.market_id).currency_code.clone(),
                        ),
                        ("description", variant.title.clone()),
                        ("discontinuedDate", option_date(variant.discontinue_date)),
                        ("id", bc_uuid("itemVariant", &variant.variant_key)),
                        ("introducedDate", variant.launch_date.to_string()),
                        ("itemId", bc_uuid("item", &product.product_key)),
                        ("itemNumber", product.product_code.clone()),
                        ("measurementUnit", variant.measurement_unit.clone()),
                        ("measurementValue", variant.measurement_value.to_string()),
                        (
                            "predecessorItemNumber",
                            product.successor_of_product_code.clone(),
                        ),
                        ("sku", variant.sku.clone()),
                        ("unitCost", variant.base_cost.to_string()),
                        ("unitOfMeasureCode", "PCS".to_owned()),
                        ("unitPrice", variant.base_price.to_string()),
                    ])
                })
            }),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "locations",
                "businessCentral",
                &[
                    "code",
                    "countryRegionCode",
                    "displayName",
                    "id",
                    "marketCode",
                    "taxAreaCode",
                ],
            ),
            bc_locations(config, &market_ids),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "company_market_configuration",
                "businessCentral",
                &[
                    "companyId",
                    "companyName",
                    "countryRegionCode",
                    "fiscalYearStartMonth",
                    "legalEntityId",
                    "localCurrencyCode",
                    "marketCode",
                    "taxBasis",
                    "taxJurisdiction",
                ],
            ),
            legal.market_ids.iter().map(|market_id| {
                let market = market_for(config, market_id);
                row(&[
                    ("companyId", company.company_id.clone()),
                    ("companyName", company.company_name.clone()),
                    ("countryRegionCode", market.country_code.clone()),
                    (
                        "fiscalYearStartMonth",
                        value_string(&market.locale_pack, "fiscalYearStartMonth", "1"),
                    ),
                    ("legalEntityId", company.legal_entity_id.clone()),
                    ("localCurrencyCode", market.currency_code.clone()),
                    ("marketCode", market.market_id.clone()),
                    (
                        "taxBasis",
                        value_string(&market.locale_pack, "taxBasis", "exclusive"),
                    ),
                    (
                        "taxJurisdiction",
                        value_string(&market.locale_pack, "taxJurisdiction", &market.region_code),
                    ),
                ])
            }),
        )?;
    }

    for market in &config.scenario.markets {
        let prefix = format!("companion/{}", market.market_id);
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "customer_segments",
                "companion",
                &["demandMultiplier", "name", "scenarioShare", "segmentId"],
            ),
            config.scenario.customer_segments.iter().map(|segment| {
                row(&[
                    ("demandMultiplier", decimal_text(segment.demand_multiplier)),
                    ("name", segment.name.clone()),
                    ("scenarioShare", decimal_text(segment.share)),
                    ("segmentId", segment.segment_id.clone()),
                ])
            }),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                &prefix,
                "store_assortment",
                "companion",
                &[
                    "active",
                    "assortmentReason",
                    "categoryId",
                    "departmentId",
                    "marketKey",
                    "observedAt",
                    "productCode",
                    "sku",
                    "storeKey",
                    "validFrom",
                    "validTo",
                ],
            ),
            store_assortment(config, catalog, &market.market_id),
        )?;
        write_rows(
            base,
            profile,
            objects,
            schemas,
            static_spec(
                "_truth",
                "catalog_truth",
                "hiddenTruth",
                &[
                    "baseCost",
                    "basePrice",
                    "brand",
                    "currencyCode",
                    "demandWeight",
                    "discontinueDate",
                    "elasticity",
                    "launchDate",
                    "launchProfile",
                    "marketKey",
                    "predecessorProductCode",
                    "productCode",
                    "productKey",
                    "productTitle",
                    "returnProbability",
                    "seasonalityPeakMonth",
                    "seasonalityStrength",
                    "shelfLifeDays",
                    "sku",
                    "successorLaunchDate",
                    "successorProductCode",
                    "variantCode",
                    "variantKey",
                ],
            ),
            catalog_truth(catalog, &market.market_id),
        )?;
    }
    Ok(())
}

fn static_spec(prefix: &str, file_stem: &str, source_system: &str, fields: &[&str]) -> DatasetSpec {
    let dataset = lower_camel(file_stem);
    let logical_path = format!("{prefix}/{file_stem}.parquet");
    DatasetSpec {
        relative_path: logical_path.clone(),
        logical_path,
        source_system: source_system.to_owned(),
        dataset,
        restricted: source_system == "hiddenTruth",
        fields: fields.iter().map(|value| (*value).to_owned()).collect(),
    }
}

fn write_rows(
    base: &Path,
    profile: &ExecutionProfile,
    objects: &mut Vec<SourceObject>,
    schemas: &mut Vec<crate::manifest::DatasetSchema>,
    spec: DatasetSpec,
    rows: impl IntoIterator<Item = BTreeMap<String, String>>,
) -> Result<()> {
    let fields = spec.fields.clone();
    let mut writer =
        ParquetDatasetWriter::create(base, spec, Compression::Zstd, profile.batch_rows)?;
    for values in rows {
        writer.push(
            fields
                .iter()
                .map(|field| values.get(field).cloned())
                .collect::<Row>(),
        )?;
    }
    let (object, schema) = writer.finish()?;
    objects.push(object);
    schemas.push(schema);
    Ok(())
}

fn row<const N: usize>(values: &[(&str, String); N]) -> BTreeMap<String, String> {
    values
        .iter()
        .map(|(key, value)| ((*key).to_owned(), value.clone()))
        .collect()
}

fn shopify_locations(config: &LoadedConfig, market_id: &str) -> Vec<BTreeMap<String, String>> {
    let market = market_for(config, market_id);
    config
        .scenario
        .stores
        .iter()
        .filter(|store| store.market_id == market_id)
        .map(|store| {
            row(&[
                ("active", "true".to_owned()),
                ("address1", store.address_line1.clone()),
                ("city", store.city.clone()),
                ("countryCode", market.country_code.clone()),
                (
                    "id",
                    shopify_gid("Location", &format!("store:{}", store.store_id)),
                ),
                ("locationType", "store".to_owned()),
                ("name", store.name.clone()),
                ("provinceCode", store.region_code.clone()),
                ("timezone", market.timezone.clone()),
                ("zip", store.postcode.clone()),
            ])
        })
        .chain(
            config
                .scenario
                .warehouses
                .iter()
                .filter(|warehouse| warehouse.market_id == market_id)
                .map(|warehouse| {
                    row(&[
                        ("active", "true".to_owned()),
                        ("address1", String::new()),
                        ("city", market.city.clone()),
                        ("countryCode", market.country_code.clone()),
                        (
                            "id",
                            shopify_gid(
                                "Location",
                                &format!("warehouse:{}", warehouse.warehouse_id),
                            ),
                        ),
                        ("locationType", "warehouse".to_owned()),
                        ("name", warehouse.name.clone()),
                        ("provinceCode", market.region_code.clone()),
                        ("timezone", market.timezone.clone()),
                        ("zip", String::new()),
                    ])
                }),
        )
        .collect()
}

fn bc_locations(
    config: &LoadedConfig,
    market_ids: &BTreeSet<String>,
) -> Vec<BTreeMap<String, String>> {
    config
        .scenario
        .stores
        .iter()
        .filter(|store| market_ids.contains(&store.market_id))
        .map(|store| {
            let market = market_for(config, &store.market_id);
            row(&[
                ("code", store.business_central_location_code.clone()),
                ("countryRegionCode", market.country_code.clone()),
                ("displayName", store.name.clone()),
                ("id", bc_uuid("location", &store.store_id)),
                ("marketCode", store.market_id.clone()),
                (
                    "taxAreaCode",
                    value_string(&market.locale_pack, "taxJurisdiction", &store.region_code),
                ),
            ])
        })
        .chain(
            config
                .scenario
                .warehouses
                .iter()
                .filter(|warehouse| market_ids.contains(&warehouse.market_id))
                .map(|warehouse| {
                    let market = market_for(config, &warehouse.market_id);
                    row(&[
                        ("code", warehouse.business_central_location_code.clone()),
                        ("countryRegionCode", market.country_code.clone()),
                        ("displayName", warehouse.name.clone()),
                        ("id", bc_uuid("location", &warehouse.warehouse_id)),
                        ("marketCode", warehouse.market_id.clone()),
                        (
                            "taxAreaCode",
                            value_string(
                                &market.locale_pack,
                                "taxJurisdiction",
                                &market.region_code,
                            ),
                        ),
                    ])
                }),
        )
        .collect()
}

fn store_assortment(
    config: &LoadedConfig,
    catalog: &[Product],
    market_id: &str,
) -> Vec<BTreeMap<String, String>> {
    let observed = config.scenario.time.start_date.to_string();
    let mut rows = Vec::new();
    for store in config
        .scenario
        .stores
        .iter()
        .filter(|row| row.market_id == market_id)
    {
        for product in catalog.iter().filter(|row| row.market_id == market_id) {
            for variant in &product.variants {
                let active =
                    stable_integer(&["assortment", &store.store_id, &variant.sku], 1_000_000)
                        as f64
                        / 1_000_000.0
                        < store.assortment_coverage;
                if active {
                    rows.push(row(&[
                        ("active", "true".to_owned()),
                        ("assortmentReason", "native_observed".to_owned()),
                        ("categoryId", product.category_id.clone()),
                        ("departmentId", product.department_id.clone()),
                        ("marketKey", market_id.to_owned()),
                        ("observedAt", observed.clone()),
                        ("productCode", product.product_code.clone()),
                        ("sku", variant.sku.clone()),
                        ("storeKey", store.store_id.clone()),
                        ("validFrom", variant.launch_date.to_string()),
                        ("validTo", option_date(variant.discontinue_date)),
                    ]));
                }
            }
        }
    }
    rows
}

fn catalog_truth(catalog: &[Product], market_id: &str) -> Vec<BTreeMap<String, String>> {
    catalog
        .iter()
        .filter(|row| row.market_id == market_id)
        .flat_map(|product| {
            product.variants.iter().map(|variant| {
                row(&[
                    ("baseCost", variant.base_cost.to_string()),
                    ("basePrice", variant.base_price.to_string()),
                    ("brand", product.brand.clone()),
                    ("currencyCode", variant.currency_code.clone()),
                    ("demandWeight", variant.demand_weight.to_string()),
                    ("discontinueDate", option_date(variant.discontinue_date)),
                    ("elasticity", variant.elasticity.to_string()),
                    ("launchDate", variant.launch_date.to_string()),
                    ("launchProfile", product.launch_profile.clone()),
                    ("marketKey", market_id.to_owned()),
                    (
                        "predecessorProductCode",
                        product.successor_of_product_code.clone(),
                    ),
                    ("productCode", product.product_code.clone()),
                    ("productKey", product.product_key.clone()),
                    ("productTitle", product.title.clone()),
                    ("returnProbability", variant.return_probability.to_string()),
                    (
                        "seasonalityPeakMonth",
                        product.seasonality_peak_month.to_string(),
                    ),
                    (
                        "seasonalityStrength",
                        product.seasonality_strength.to_string(),
                    ),
                    (
                        "shelfLifeDays",
                        product
                            .shelf_life_days
                            .map_or_else(String::new, |value| value.to_string()),
                    ),
                    ("sku", variant.sku.clone()),
                    (
                        "successorLaunchDate",
                        option_date(product.successor_launch_date),
                    ),
                    (
                        "successorProductCode",
                        product.successor_product_code.clone(),
                    ),
                    ("variantCode", variant.variant_code.clone()),
                    ("variantKey", variant.variant_key.clone()),
                ])
            })
        })
        .collect()
}

fn register_metadata(
    path: &Path,
    base: &Path,
    dataset: &str,
    objects: &mut Vec<SourceObject>,
) -> Result<()> {
    let (bytes, digest) = file_sha256(path)?;
    objects.push(SourceObject {
        path: path
            .strip_prefix(base)?
            .to_string_lossy()
            .replace('\\', "/"),
        logical_path: path
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned(),
        source_system: "generator".to_owned(),
        dataset: dataset.to_owned(),
        format: path
            .extension()
            .unwrap_or_default()
            .to_string_lossy()
            .into_owned(),
        compression: "none".to_owned(),
        rows: None,
        bytes,
        sha256: digest,
        content_determinism: "byte".to_owned(),
        restricted: false,
    });
    Ok(())
}

#[cfg(feature = "duckdb-mirror")]
fn register_source_mirror(
    path: &Path,
    base: &Path,
    rows: u64,
    objects: &mut Vec<SourceObject>,
) -> Result<()> {
    let (bytes, digest) = file_sha256(path)?;
    objects.push(SourceObject {
        path: path
            .strip_prefix(base)?
            .to_string_lossy()
            .replace('\\', "/"),
        logical_path: "source-run.duckdb".to_owned(),
        source_system: "generator".to_owned(),
        dataset: "sourceRunDuckdb".to_owned(),
        format: "duckdb".to_owned(),
        compression: "none".to_owned(),
        rows: Some(rows),
        bytes,
        sha256: digest,
        content_determinism: "logical".to_owned(),
        restricted: true,
    });
    Ok(())
}

fn catalog_controls(catalog: &[Product]) -> Value {
    let mut controls = BTreeMap::<String, Value>::new();
    for market in catalog
        .iter()
        .map(|row| row.market_id.clone())
        .collect::<BTreeSet<_>>()
    {
        let products = catalog
            .iter()
            .filter(|row| row.market_id == market)
            .collect::<Vec<_>>();
        controls.insert(market, json!({"products": products.len(), "sellableSkus": products.iter().map(|row| row.variants.len()).sum::<usize>()}));
    }
    serde_json::to_value(controls).expect("serialize catalog controls")
}

fn market_for<'a>(config: &'a LoadedConfig, market_id: &str) -> &'a crate::config::Market {
    config
        .scenario
        .markets
        .iter()
        .find(|row| row.market_id == market_id)
        .expect("validated market")
}

fn option_date(value: Option<chrono::NaiveDate>) -> String {
    value.map_or_else(String::new, |date| date.to_string())
}
fn slug(value: &str) -> String {
    value
        .to_ascii_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join("-")
}
fn decimal_text(value: f64) -> String {
    format!("{value:.8}")
        .trim_end_matches('0')
        .trim_end_matches('.')
        .to_owned()
}
fn value_string(value: &Value, key: &str, fallback: &str) -> String {
    value.get(key).map_or_else(
        || fallback.to_owned(),
        |item| {
            item.as_str()
                .map_or_else(|| item.to_string(), str::to_owned)
        },
    )
}
fn lower_camel(value: &str) -> String {
    let mut result = String::new();
    let mut upper = false;
    for c in value.chars() {
        if c == '_' {
            upper = true;
        } else if upper {
            result.extend(c.to_uppercase());
            upper = false;
        } else {
            result.push(c);
        }
    }
    result
}

pub mod streaming {
    use super::*;

    pub struct StreamingResult {
        pub simulation_controls: Value,
        pub controls_by_currency: Value,
    }

    pub fn generate_all(
        config: &LoadedConfig,
        catalog: &[Product],
        base: &Path,
        profile: &ExecutionProfile,
        telemetry: &Telemetry,
        objects: &mut Vec<SourceObject>,
        schemas: &mut Vec<crate::manifest::DatasetSchema>,
    ) -> Result<StreamingResult> {
        let mut projection = crate::projection::commerce::CommerceProjection::new_spooling(
            config,
            catalog,
            base,
            profile.batch_rows.min(10_000),
            profile.partition_workers.saturating_mul(16).clamp(16, 128),
        )?;
        {
            let _measurement = telemetry.measure("causal-core");
            crate::simulation::causal::simulate(config, catalog, &mut projection)?;
        }
        let mut result = {
            let _measurement = telemetry.measure("projection-finalize");
            projection.finish()?
        };
        if let Some(spool) = result.projection_spool.take() {
            let _measurement = telemetry.measure("partition-publication");
            let (published_objects, published_schemas) = crate::spool::publish_projection_spool(
                base,
                spool,
                config.scenario.output.compression,
                profile.batch_rows,
                profile.partition_workers,
            )?;
            objects.extend(published_objects);
            schemas.extend(published_schemas);
        }
        for dataset in result.datasets {
            super::write_projected_dataset(config, base, profile, objects, schemas, dataset)?;
        }
        Ok(StreamingResult {
            simulation_controls: result.simulation_controls,
            controls_by_currency: result.controls_by_currency,
        })
    }

    #[cfg(feature = "duckdb-mirror")]
    pub fn build_duckdb_mirror(
        base: &Path,
        objects: &[SourceObject],
        schemas: &[crate::manifest::DatasetSchema],
        threads: usize,
        memory_limit_gb: usize,
    ) -> Result<u64> {
        use duckdb::{Connection, params};

        let mut source_objects = objects
            .iter()
            .filter(|object| matches!(object.format.as_str(), "parquet" | "csv"))
            .collect::<Vec<_>>();
        source_objects.sort_by(|left, right| left.path.cmp(&right.path));
        if source_objects.is_empty() {
            return Ok(0);
        }

        let path = base.join("source-run.duckdb");
        let temp = base.join("source-run.duckdb.tmp");
        ensure!(
            !path.exists(),
            "DuckDB mirror already exists: {}",
            path.display()
        );
        ensure!(
            !temp.exists(),
            "DuckDB mirror temporary file already exists: {}",
            temp.display()
        );
        let connection = Connection::open(&temp)
            .with_context(|| format!("create DuckDB mirror {}", temp.display()))?;
        connection.execute_batch(&format!(
            "SET memory_limit='{}GB'; SET threads={};",
            memory_limit_gb.max(1),
            threads.max(1)
        ))?;
        connection.execute_batch(
            "CREATE TABLE source_object_catalog (
                table_name VARCHAR NOT NULL,
                source_path VARCHAR NOT NULL,
                logical_path VARCHAR NOT NULL,
                source_system VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                source_rows BIGINT,
                source_sha256 VARCHAR NOT NULL,
                source_format VARCHAR NOT NULL,
                source_compression VARCHAR NOT NULL,
                restricted BOOLEAN NOT NULL
            );",
        )?;

        let mut logical_by_table = BTreeMap::<String, String>::new();
        let mut created_tables = BTreeSet::<String>::new();
        for object in &source_objects {
            let table_name = duckdb_table_name(&object.logical_path);
            match logical_by_table.get(&table_name) {
                Some(prior) => ensure!(
                    prior == &object.logical_path,
                    "DuckDB table-name collision between {prior:?} and {:?}",
                    object.logical_path
                ),
                None => {
                    logical_by_table.insert(table_name.clone(), object.logical_path.clone());
                }
            }
            let quoted_table = quote_identifier(&table_name);
            let reader = match object.format.as_str() {
                "parquet" => "read_parquet(?, hive_partitioning=false)",
                "csv" => {
                    "read_csv_auto(?, header=true, all_varchar=true, sample_size=-1, hive_partitioning=false)"
                }
                other => anyhow::bail!("cannot mirror source format {other:?}"),
            };
            let source_path = base.join(&object.path).to_string_lossy().into_owned();
            let statement = if created_tables.insert(table_name.clone()) {
                format!("CREATE TABLE {quoted_table} AS SELECT * FROM {reader}")
            } else {
                format!("INSERT INTO {quoted_table} BY NAME SELECT * FROM {reader}")
            };
            connection
                .execute(&statement, params![source_path])
                .with_context(|| format!("mirror source object {}", object.path))?;
            let source_rows = object.rows.map(i64::try_from).transpose()?;
            connection.execute(
                "INSERT INTO source_object_catalog VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params![
                    table_name,
                    object.path,
                    object.logical_path,
                    object.source_system,
                    object.dataset,
                    source_rows,
                    object.sha256,
                    object.format,
                    object.compression,
                    object.restricted,
                ],
            )?;
        }
        connection.execute_batch(
            "CREATE TABLE source_dataset_catalog AS
             SELECT table_name, logical_path,
                    min(source_system) AS source_system,
                    min(dataset) AS dataset,
                    sum(source_rows) AS source_rows,
                    count(*) AS partition_count,
                    bool_or(restricted) AS restricted
             FROM source_object_catalog
             GROUP BY table_name, logical_path
             ORDER BY logical_path;
             CREATE TABLE source_schema (
                logical_path VARCHAR NOT NULL,
                source_system VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                restricted BOOLEAN NOT NULL,
                ordinal_position INTEGER NOT NULL,
                field_name VARCHAR NOT NULL,
                physical_type VARCHAR NOT NULL,
                nullable BOOLEAN NOT NULL
             );",
        )?;
        let mut ordered_schemas = schemas.iter().collect::<Vec<_>>();
        ordered_schemas.sort_by(|left, right| left.logical_path.cmp(&right.logical_path));
        for schema in ordered_schemas {
            for (index, field) in schema.fields.iter().enumerate() {
                connection.execute(
                    "INSERT INTO source_schema VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    params![
                        schema.logical_path,
                        schema.source_system,
                        schema.dataset,
                        schema.restricted,
                        i32::try_from(index + 1)?,
                        field.name,
                        field.physical_type,
                        field.nullable,
                    ],
                )?;
            }
        }
        connection.execute_batch("CHECKPOINT;")?;
        drop(connection);
        fs::rename(&temp, &path)
            .with_context(|| format!("publish DuckDB mirror {}", path.display()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&path, fs::Permissions::from_mode(0o600))?;
        }
        Ok(u64::try_from(source_objects.len())?)
    }

    #[cfg(feature = "duckdb-mirror")]
    fn duckdb_table_name(relative_path: &str) -> String {
        let stem = relative_path
            .strip_suffix(".parquet")
            .or_else(|| relative_path.strip_suffix(".csv"))
            .unwrap_or(relative_path);
        stem.chars()
            .map(|character| {
                if character.is_alphanumeric() {
                    character
                } else {
                    '_'
                }
            })
            .collect::<String>()
            .trim_matches('_')
            .to_lowercase()
    }

    #[cfg(feature = "duckdb-mirror")]
    fn quote_identifier(value: &str) -> String {
        format!("\"{}\"", value.replace('"', "\"\""))
    }
}

#[cfg(test)]
mod execution_profile_tests {
    use std::fs;

    use super::{ExecutionProfile, ProfileName, named_execution_profiles};

    #[test]
    fn checked_in_profile_documents_match_named_profiles() {
        for (name, named) in [
            ("safe", ProfileName::Safe),
            ("balanced", ProfileName::Balanced),
            ("performance", ProfileName::Performance),
            ("ultra-performance", ProfileName::UltraPerformance),
        ] {
            let from_file = ExecutionProfile::load(format!("configs/{name}.execution.yaml"))
                .expect("checked-in execution profile");
            assert_eq!(
                serde_json::to_value(from_file).expect("file profile JSON"),
                serde_json::to_value(named.resolve()).expect("named profile JSON"),
                "{name} profile file diverged from the named profile"
            );
        }
    }

    #[test]
    fn listed_profiles_use_the_python_document_shape() {
        let profiles = named_execution_profiles();
        assert_eq!(
            profiles["safe"]["datagen"],
            serde_json::json!({
                "marketWorkers": 1,
                "partitionWorkers": 2,
                "duckdbThreads": 1,
                "memoryLimitGb": 4,
                "spoolChunkRows": 10_000,
            })
        );
        assert_eq!(profiles["safe"]["profile"], "safe");
        assert_eq!(
            profiles["safe"]["schemaVersion"],
            "retail-execution-profile/v1"
        );
    }

    #[test]
    fn standalone_scenarios_match_the_python_files_byte_for_byte() {
        for name in [
            "gulf-oil-india-showcase.json",
            "gulf-oil-india-showcase.yaml",
            "gulf-oil-india-ten-year.json",
            "gulf-oil-india-ten-year.yaml",
            "multi-market-10-year-demo.yaml",
            "multi-market-20-year-history.yaml",
            "multi-market-2021-current-volume.yaml",
            "multi-market-showcase.yaml",
            "pricing-evidence-sparse.yaml",
            "pricing-response-rich.yaml",
        ] {
            assert_eq!(
                fs::read(format!("configs/{name}")).expect("standalone Rust scenario"),
                fs::read(format!("../datagen/configs/{name}")).expect("Python scenario"),
                "configs/{name} diverged from datagen/configs/{name}"
            );
        }
    }
}
