pub mod catalog;
pub mod commerce;
pub mod context;
pub mod signals;
pub mod supply;

use std::collections::BTreeMap;

#[derive(Debug, Clone)]
pub struct LogicalDataset {
    pub prefix: String,
    pub source_system: String,
    pub dataset: String,
    pub restricted: bool,
    pub rows: Vec<BTreeMap<String, String>>,
}
