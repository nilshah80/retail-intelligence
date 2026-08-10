use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub struct DatasetTotals {
    pub rows: u64,
    pub bytes: u64,
    pub objects: u64,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RunSummary {
    pub path: PathBuf,
    pub run_id: String,
    pub generator_version: String,
    pub config_hash: String,
    pub elapsed_seconds: Option<f64>,
    pub peak_rss_bytes: Option<u64>,
    pub total_rows: u64,
    pub total_bytes: u64,
    pub total_objects: u64,
    pub datasets: BTreeMap<String, DatasetTotals>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ComparisonReport {
    pub schema_version: String,
    pub python: RunSummary,
    pub rust: RunSummary,
    pub same_config_hash: bool,
    pub row_count_mismatches: BTreeMap<String, DatasetPair>,
    pub missing_from_rust: Vec<String>,
    pub additional_in_rust: Vec<String>,
    pub wall_speedup: Option<f64>,
    pub peak_rss_reduction_pct: Option<f64>,
    pub semantic: SemanticComparison,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SemanticComparison {
    pub evaluated: bool,
    pub exact_logical_match: bool,
    pub reason: Option<String>,
    pub compared_datasets: u64,
    pub missing_logical_datasets: Vec<String>,
    pub additional_logical_datasets: Vec<String>,
    pub schema_mismatches: Vec<String>,
    pub content_mismatches: Vec<String>,
    pub control_mismatches: Vec<String>,
    pub partition_layout_mismatches: Vec<String>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DatasetPair {
    pub python: DatasetTotals,
    pub rust: DatasetTotals,
}

pub fn compare_runs(python_run: &Path, rust_run: &Path) -> Result<ComparisonReport> {
    let python_manifest = read_manifest(python_run)?;
    let rust_manifest = read_manifest(rust_run)?;
    let python = summarize(python_run)?;
    let rust = summarize(rust_run)?;
    let mut mismatches = BTreeMap::new();
    let mut missing = Vec::new();
    let mut additional = Vec::new();
    for (key, expected) in &python.datasets {
        match rust.datasets.get(key) {
            None => missing.push(key.clone()),
            Some(actual) if expected.rows != actual.rows => {
                mismatches.insert(
                    key.clone(),
                    DatasetPair {
                        python: expected.clone(),
                        rust: actual.clone(),
                    },
                );
            }
            Some(_) => {}
        }
    }
    for key in rust.datasets.keys() {
        if !python.datasets.contains_key(key) {
            additional.push(key.clone());
        }
    }
    let wall_speedup = python
        .elapsed_seconds
        .zip(rust.elapsed_seconds)
        .and_then(|(left, right)| (right > 0.0).then_some(left / right));
    let peak_rss_reduction_pct =
        python
            .peak_rss_bytes
            .zip(rust.peak_rss_bytes)
            .and_then(|(left, right)| {
                (left > 0).then_some((left as f64 - right as f64) / left as f64 * 100.0)
            });
    let semantic = compare_semantics(python_run, rust_run, &python_manifest, &rust_manifest)?;
    Ok(ComparisonReport {
        schema_version: "retail-datagen-comparison/v2".to_owned(),
        same_config_hash: python.config_hash == rust.config_hash,
        python,
        rust,
        row_count_mismatches: mismatches,
        missing_from_rust: missing,
        additional_in_rust: additional,
        wall_speedup,
        peak_rss_reduction_pct,
        semantic,
    })
}

fn summarize(run: &Path) -> Result<RunSummary> {
    let manifest = read_manifest(run)?;
    let mut datasets: BTreeMap<String, DatasetTotals> = BTreeMap::new();
    for object in manifest["objects"]
        .as_array()
        .context("manifest.objects must be an array")?
    {
        let Some(rows) = object["rows"].as_u64() else {
            continue;
        };
        let source_system = object["sourceSystem"].as_str().unwrap_or("unknown");
        let dataset = object["dataset"].as_str().unwrap_or("unknown");
        let key = format!("{source_system}/{dataset}");
        let entry = datasets.entry(key).or_default();
        entry.rows += rows;
        entry.bytes += object["bytes"].as_u64().unwrap_or(0);
        entry.objects += 1;
    }
    let telemetry = &manifest["executionTelemetry"];
    let elapsed_seconds = telemetry["elapsedBeforeManifestSeconds"]
        .as_f64()
        .or_else(|| telemetry["wallSeconds"].as_f64());
    let peak_rss_bytes = telemetry["aggregateProcessTreePeakRssBytes"]
        .as_u64()
        .or_else(|| telemetry["peakProcessTreeRssBytes"].as_u64())
        .or_else(|| telemetry["peakProcessRssBytes"].as_u64());
    Ok(RunSummary {
        path: run.to_path_buf(),
        run_id: manifest["runId"].as_str().unwrap_or_default().to_owned(),
        generator_version: manifest["generatorVersion"]
            .as_str()
            .unwrap_or_default()
            .to_owned(),
        config_hash: manifest["configHash"]
            .as_str()
            .unwrap_or_default()
            .to_owned(),
        elapsed_seconds,
        peak_rss_bytes,
        total_rows: datasets.values().map(|value| value.rows).sum(),
        total_bytes: datasets.values().map(|value| value.bytes).sum(),
        total_objects: datasets.values().map(|value| value.objects).sum(),
        datasets,
    })
}

fn read_manifest(run: &Path) -> Result<Value> {
    let manifest_path = run.join("source-run-manifest.json");
    ensure!(
        manifest_path.is_file(),
        "missing manifest {}",
        manifest_path.display()
    );
    serde_json::from_slice(
        &fs::read(&manifest_path).with_context(|| format!("read {}", manifest_path.display()))?,
    )
    .with_context(|| format!("parse {}", manifest_path.display()))
}

fn manifest_controls(left: &Value, right: &Value) -> Vec<String> {
    [
        ("simulationControls", "simulationControls"),
        ("controlsByCurrency", "controlsByCurrency"),
        ("catalogControlsByMarket", "catalogControlsByMarket"),
    ]
    .into_iter()
    .filter_map(|(label, field)| (left[field] != right[field]).then(|| label.to_owned()))
    .collect()
}

fn partition_layout(manifest: &Value) -> Result<BTreeMap<String, Vec<String>>> {
    let mut result = BTreeMap::<String, Vec<String>>::new();
    for object in manifest["objects"]
        .as_array()
        .context("manifest.objects must be an array")?
    {
        if !matches!(object["format"].as_str(), Some("parquet" | "csv")) {
            continue;
        }
        let Some(logical_path) = object["logicalPath"].as_str() else {
            continue;
        };
        let Some(path) = object["path"].as_str() else {
            continue;
        };
        result
            .entry(logical_path.to_owned())
            .or_default()
            .push(path.to_owned());
    }
    for paths in result.values_mut() {
        paths.sort();
    }
    Ok(result)
}

fn base_semantic_comparison(
    python_manifest: &Value,
    rust_manifest: &Value,
) -> Result<SemanticComparison> {
    let python_partitions = partition_layout(python_manifest)?;
    let rust_partitions = partition_layout(rust_manifest)?;
    let mut partition_layout_mismatches = python_partitions
        .iter()
        .filter_map(|(logical, paths)| {
            (rust_partitions.get(logical) != Some(paths)).then(|| logical.clone())
        })
        .collect::<Vec<_>>();
    partition_layout_mismatches.extend(
        rust_partitions
            .keys()
            .filter(|logical| !python_partitions.contains_key(*logical))
            .cloned(),
    );
    partition_layout_mismatches.sort();
    partition_layout_mismatches.dedup();
    Ok(SemanticComparison {
        evaluated: false,
        exact_logical_match: false,
        reason: None,
        compared_datasets: 0,
        missing_logical_datasets: Vec::new(),
        additional_logical_datasets: Vec::new(),
        schema_mismatches: Vec::new(),
        content_mismatches: Vec::new(),
        control_mismatches: manifest_controls(python_manifest, rust_manifest),
        partition_layout_mismatches,
    })
}

#[cfg(not(feature = "duckdb-mirror"))]
fn compare_semantics(
    _python_run: &Path,
    _rust_run: &Path,
    python_manifest: &Value,
    rust_manifest: &Value,
) -> Result<SemanticComparison> {
    let mut result = base_semantic_comparison(python_manifest, rust_manifest)?;
    result.reason =
        Some("exact logical comparison requires the default duckdb-mirror feature".to_owned());
    Ok(result)
}

#[cfg(feature = "duckdb-mirror")]
fn compare_semantics(
    python_run: &Path,
    rust_run: &Path,
    python_manifest: &Value,
    rust_manifest: &Value,
) -> Result<SemanticComparison> {
    use duckdb::{Connection, params};

    let mut result = base_semantic_comparison(python_manifest, rust_manifest)?;
    let python_db = python_run.join("source-run.duckdb");
    let rust_db = rust_run.join("source-run.duckdb");
    if !python_db.is_file() || !rust_db.is_file() {
        result.reason = Some(format!(
            "exact logical comparison requires both DuckDB mirrors (Python: {}, Rust: {})",
            python_db.is_file(),
            rust_db.is_file()
        ));
        return Ok(result);
    }

    let connection = Connection::open_in_memory().context("open comparison DuckDB")?;
    connection.execute_batch(
        "SET memory_limit='4GB'; SET threads=4; SET preserve_insertion_order=false;",
    )?;
    connection.execute_batch(&format!(
        "ATTACH '{}' AS python_run (READ_ONLY); ATTACH '{}' AS rust_run (READ_ONLY);",
        sql_string(&python_db),
        sql_string(&rust_db),
    ))?;
    let python_tables = attached_dataset_tables(&connection, "python_run")?;
    let rust_tables = attached_dataset_tables(&connection, "rust_run")?;
    result.missing_logical_datasets = python_tables
        .keys()
        .filter(|logical| !rust_tables.contains_key(*logical))
        .cloned()
        .collect();
    result.additional_logical_datasets = rust_tables
        .keys()
        .filter(|logical| !python_tables.contains_key(*logical))
        .cloned()
        .collect();

    for (logical_path, python_table) in &python_tables {
        let Some(rust_table) = rust_tables.get(logical_path) else {
            continue;
        };
        let schema_differs: bool = connection.query_row(
            "SELECT EXISTS(
                SELECT * FROM (
                    (SELECT source_system, dataset, restricted, ordinal_position,
                            field_name, physical_type, nullable
                     FROM python_run.main.source_schema WHERE logical_path = ?
                     EXCEPT ALL
                     SELECT source_system, dataset, restricted, ordinal_position,
                            field_name, physical_type, nullable
                     FROM rust_run.main.source_schema WHERE logical_path = ?)
                    UNION ALL
                    (SELECT source_system, dataset, restricted, ordinal_position,
                            field_name, physical_type, nullable
                     FROM rust_run.main.source_schema WHERE logical_path = ?
                     EXCEPT ALL
                     SELECT source_system, dataset, restricted, ordinal_position,
                            field_name, physical_type, nullable
                     FROM python_run.main.source_schema WHERE logical_path = ?)
                ) differences
            )",
            params![logical_path, logical_path, logical_path, logical_path],
            |row| row.get(0),
        )?;
        if schema_differs {
            result.schema_mismatches.push(logical_path.clone());
            continue;
        }

        let python_relation = format!("python_run.main.{}", quote_identifier(python_table));
        let rust_relation = format!("rust_run.main.{}", quote_identifier(rust_table));
        let content_differs: bool = connection.query_row(
            &format!(
                "SELECT EXISTS(
                    SELECT * FROM (
                        (SELECT * FROM {python_relation} EXCEPT ALL SELECT * FROM {rust_relation})
                        UNION ALL
                        (SELECT * FROM {rust_relation} EXCEPT ALL SELECT * FROM {python_relation})
                    ) differences
                )"
            ),
            [],
            |row| row.get(0),
        )?;
        result.compared_datasets += 1;
        if content_differs {
            result.content_mismatches.push(logical_path.clone());
        }
    }
    result.evaluated = true;
    result.exact_logical_match = result.missing_logical_datasets.is_empty()
        && result.additional_logical_datasets.is_empty()
        && result.schema_mismatches.is_empty()
        && result.content_mismatches.is_empty()
        && result.control_mismatches.is_empty();
    Ok(result)
}

#[cfg(feature = "duckdb-mirror")]
fn attached_dataset_tables(
    connection: &duckdb::Connection,
    catalog: &str,
) -> Result<BTreeMap<String, String>> {
    let mut statement = connection.prepare(&format!(
        "SELECT logical_path, table_name FROM {catalog}.main.source_dataset_catalog ORDER BY logical_path"
    ))?;
    let rows = statement.query_map([], |row| {
        Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
    })?;
    let mut result = BTreeMap::new();
    for row in rows {
        let (logical_path, table_name) = row?;
        result.insert(logical_path, table_name);
    }
    Ok(result)
}

#[cfg(feature = "duckdb-mirror")]
fn quote_identifier(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}

#[cfg(feature = "duckdb-mirror")]
fn sql_string(path: &Path) -> String {
    path.to_string_lossy().replace(char::from(39_u8), "''")
}
