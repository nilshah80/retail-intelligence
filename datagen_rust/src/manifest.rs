use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceObject {
    pub path: String,
    pub logical_path: String,
    pub source_system: String,
    pub dataset: String,
    pub format: String,
    pub compression: String,
    pub rows: Option<u64>,
    pub bytes: u64,
    pub sha256: String,
    pub content_determinism: String,
    pub restricted: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SchemaField {
    pub name: String,
    pub physical_type: String,
    pub nullable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DatasetSchema {
    pub logical_path: String,
    pub source_system: String,
    pub dataset: String,
    pub restricted: bool,
    pub fields: Vec<SchemaField>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SourceSchema {
    pub schema_version: String,
    pub physical_type_policy: String,
    pub datasets: Vec<DatasetSchema>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RunManifest {
    pub manifest_version: String,
    pub generator_version: String,
    pub engine: String,
    pub engine_version: String,
    pub source_spec_version: String,
    pub scenario_id: String,
    pub scenario_version: String,
    pub retailer: Value,
    pub master_seed: u64,
    pub config_hash: String,
    pub run_id: String,
    pub run_identity_method: String,
    pub logical_start_date: String,
    pub logical_end_date: String,
    pub topology: Value,
    pub capabilities: BTreeMap<String, bool>,
    pub execution_profile: Value,
    pub execution_telemetry: Value,
    pub simulation_controls: Value,
    pub controls_by_currency: Value,
    pub catalog_controls_by_market: Value,
    pub objects: Vec<SourceObject>,
}
