//! Bounded binary spooling for dynamic projection rows.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Write};
use std::path::{Path, PathBuf};

use anyhow::{Context, Result, ensure};
use rayon::prelude::*;

use crate::config::{Compression, LoadedConfig, PartitionGranularity};
use crate::contracts;
use crate::manifest::{DatasetSchema, SourceObject};
use crate::simulation::model::FieldValues;
use crate::writer::{DatasetSpec, ParquetDatasetWriter};

const PARTITION_FIELDS: &[&str] = &[
    "__partitionDate",
    "date",
    "businessDate",
    "postingDate",
    "effectiveDate",
    "effectiveFrom",
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

const UNPARTITIONED_DATASETS: &[&str] = &[
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

const LEDGER_SPOOL_FIELDS: &[&str] = &[
    "id",
    "postingDate",
    "entryType",
    "itemNumber",
    "variantCode",
    "sku",
    "locationCode",
    "quantity",
    "documentNumber",
];

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
struct SpoolDatasetKey {
    prefix: String,
    source_system: String,
    dataset: String,
    restricted: bool,
}

#[derive(Debug)]
struct SpoolPartition {
    dataset_key: SpoolDatasetKey,
    spec: DatasetSpec,
    spool_path: Option<PathBuf>,
    rows: u64,
}

#[derive(Debug)]
pub struct ProjectionSpoolOutput {
    root: PathBuf,
    partitions: Vec<SpoolPartition>,
}

/// Compact intermediate storage split by final physical output partition.
///
/// Records use contract-field order and little-endian length-prefixed UTF-8. `u32::MAX`
/// represents null, so publication performs one sequential read without JSON or CSV parsing.
pub struct ProjectionSpool {
    root: PathBuf,
    generation_partition: PartitionGranularity,
    declared: BTreeSet<SpoolDatasetKey>,
    partitions: BTreeMap<String, SpoolPartition>,
    open_writers: BTreeMap<PathBuf, (BufWriter<File>, u64)>,
    access_clock: u64,
    max_open_writers: usize,
}

#[derive(Debug)]
struct LedgerPartition {
    path: PathBuf,
    rows: u64,
}

/// Date-bucketed item-ledger staging. Only one business day is materialized for sorting at a
/// time, while the final global entry number remains stable across the complete extract.
pub struct LedgerSpool {
    root: PathBuf,
    partitions: BTreeMap<(String, String), LedgerPartition>,
    open_writers: BTreeMap<PathBuf, (BufWriter<File>, u64)>,
    access_clock: u64,
    max_open_writers: usize,
}

impl LedgerSpool {
    pub fn create(run_base: &Path, max_open_writers: usize) -> Result<Self> {
        let root = run_base.join(".ledger-spool");
        ensure!(
            !root.exists(),
            "ledger spool already exists: {}",
            root.display()
        );
        fs::create_dir(&root).with_context(|| format!("create ledger spool {}", root.display()))?;
        Ok(Self {
            root,
            partitions: BTreeMap::new(),
            open_writers: BTreeMap::new(),
            access_clock: 0,
            max_open_writers: max_open_writers.max(8),
        })
    }

    pub fn append(&mut self, company_id: &str, row: &FieldValues) -> Result<()> {
        let posting_date = row
            .get("postingDate")
            .context("ledger spool row lacks postingDate")?
            .clone();
        let key = (company_id.to_owned(), posting_date);
        let next_index = self.partitions.len();
        let partition = self
            .partitions
            .entry(key)
            .or_insert_with(|| LedgerPartition {
                path: self.root.join(format!("part-{next_index:06}.rows")),
                rows: 0,
            });
        partition.rows += 1;
        let path = partition.path.clone();
        self.write_record(&path, row)
    }

    fn write_record(&mut self, path: &Path, values: &FieldValues) -> Result<()> {
        self.access_clock += 1;
        if !self.open_writers.contains_key(path) {
            if self.open_writers.len() >= self.max_open_writers {
                let oldest = self
                    .open_writers
                    .iter()
                    .min_by_key(|(_, (_, access))| *access)
                    .map(|(path, _)| path.clone())
                    .context("open ledger writer cache is unexpectedly empty")?;
                if let Some((mut writer, _)) = self.open_writers.remove(&oldest) {
                    writer
                        .flush()
                        .with_context(|| format!("flush ledger spool {}", oldest.display()))?;
                }
            }
            let file = OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
                .with_context(|| format!("open ledger spool {}", path.display()))?;
            self.open_writers.insert(
                path.to_path_buf(),
                (BufWriter::new(file), self.access_clock),
            );
        }
        let (writer, access) = self
            .open_writers
            .get_mut(path)
            .context("ledger spool writer disappeared")?;
        *access = self.access_clock;
        for field in LEDGER_SPOOL_FIELDS {
            let value = values
                .get(*field)
                .with_context(|| format!("ledger spool row lacks {field}"))?;
            let bytes = value.as_bytes();
            let length = u32::try_from(bytes.len())
                .with_context(|| format!("ledger field {field} exceeds spool record limit"))?;
            writer.write_all(&length.to_le_bytes())?;
            writer.write_all(bytes)?;
        }
        Ok(())
    }

    pub fn finish(mut self, mut emit: impl FnMut(&str, FieldValues) -> Result<()>) -> Result<()> {
        for (path, (mut writer, _)) in std::mem::take(&mut self.open_writers) {
            writer
                .flush()
                .with_context(|| format!("flush ledger spool {}", path.display()))?;
        }
        let mut sequences = BTreeMap::<String, u64>::new();
        for ((company_id, posting_date), partition) in self.partitions {
            let mut reader = BufReader::with_capacity(
                1024 * 1024,
                File::open(&partition.path)
                    .with_context(|| format!("open ledger spool {}", partition.path.display()))?,
            );
            let mut rows = Vec::with_capacity(usize::try_from(partition.rows)?);
            for _ in 0..partition.rows {
                let mut row = FieldValues::default();
                for field in LEDGER_SPOOL_FIELDS {
                    let mut encoded_length = [0_u8; 4];
                    reader.read_exact(&mut encoded_length)?;
                    let mut bytes =
                        vec![0_u8; usize::try_from(u32::from_le_bytes(encoded_length,))?];
                    reader.read_exact(&mut bytes)?;
                    row.insert(
                        *field,
                        String::from_utf8(bytes).context("decode ledger spool value")?,
                    );
                }
                ensure!(
                    row["postingDate"] == posting_date,
                    "ledger spool date bucket mismatch"
                );
                rows.push(row);
            }
            let mut trailing = [0_u8; 1];
            ensure!(
                reader.read(&mut trailing)? == 0,
                "ledger spool {} has trailing bytes",
                partition.path.display()
            );
            rows.sort_by(|left, right| {
                (
                    &left["postingDate"],
                    &left["locationCode"],
                    &left["sku"],
                    &left["entryType"],
                    &left["id"],
                )
                    .cmp(&(
                        &right["postingDate"],
                        &right["locationCode"],
                        &right["sku"],
                        &right["entryType"],
                        &right["id"],
                    ))
            });
            let sequence = sequences.entry(company_id.clone()).or_default();
            for mut row in rows {
                *sequence += 1;
                row.insert("entryNumber", sequence.to_string());
                emit(&company_id, row)?;
            }
        }
        fs::remove_dir_all(&self.root)
            .with_context(|| format!("remove completed ledger spool {}", self.root.display()))?;
        Ok(())
    }
}

impl ProjectionSpool {
    pub fn create(run_base: &Path, config: &LoadedConfig, max_open_writers: usize) -> Result<Self> {
        let root = run_base.join(".projection-spool");
        ensure!(
            !root.exists(),
            "projection spool already exists: {}",
            root.display()
        );
        fs::create_dir(&root)
            .with_context(|| format!("create projection spool {}", root.display()))?;
        Ok(Self {
            root,
            generation_partition: config.scenario.time.generation_partition,
            declared: BTreeSet::new(),
            partitions: BTreeMap::new(),
            open_writers: BTreeMap::new(),
            access_clock: 0,
            max_open_writers: max_open_writers.max(8),
        })
    }

    pub fn declare(&mut self, prefix: &str, source_system: &str, dataset: &str, restricted: bool) {
        self.declared.insert(SpoolDatasetKey {
            prefix: prefix.to_owned(),
            source_system: source_system.to_owned(),
            dataset: dataset.to_owned(),
            restricted,
        });
    }

    pub fn append_rows(
        &mut self,
        prefix: &str,
        source_system: &str,
        dataset: &str,
        restricted: bool,
        rows: impl IntoIterator<Item = FieldValues>,
    ) -> Result<()> {
        let key = SpoolDatasetKey {
            prefix: prefix.to_owned(),
            source_system: source_system.to_owned(),
            dataset: dataset.to_owned(),
            restricted,
        };
        self.declared.insert(key.clone());
        let fields = contracts::fields(source_system, dataset)?;
        let file_stem = contracts::snake_case(dataset);
        let logical_path = format!("{prefix}/{file_stem}.parquet");
        let mut partition_field = UNPARTITIONED_DATASETS
            .contains(&dataset)
            .then_some(None::<&'static str>);
        let mut last_bucket = String::new();
        let mut relative_path = logical_path.clone();
        let mut spool_path = self.root.join(format!("{relative_path}.rows"));
        for values in rows {
            let field = match partition_field {
                Some(field) => field,
                None => {
                    let field = PARTITION_FIELDS
                        .iter()
                        .find(|field| values.contains_key(**field))
                        .copied();
                    partition_field = Some(field);
                    field
                }
            };
            if let Some(field) = field {
                let raw = values
                    .get(field)
                    .with_context(|| format!("{dataset} row lacks partition field {field}"))?;
                ensure!(
                    raw.len() >= 10,
                    "{dataset} has invalid partition date {raw:?}"
                );
                let bucket_length = match self.generation_partition {
                    PartitionGranularity::Month => 7,
                    PartitionGranularity::Day => 10,
                };
                let bucket = raw
                    .get(..bucket_length)
                    .with_context(|| format!("{dataset} has invalid partition date {raw:?}"))?;
                if last_bucket != bucket {
                    let date_text = raw
                        .get(..10)
                        .with_context(|| format!("{dataset} has invalid partition date {raw:?}"))?;
                    let date = chrono::NaiveDate::parse_from_str(date_text, "%Y-%m-%d")
                        .with_context(|| format!("{dataset} has invalid partition date {raw:?}"))?;
                    relative_path = match self.generation_partition {
                        PartitionGranularity::Month => format!(
                            "{prefix}/{file_stem}/year={:04}/month={:02}/part.parquet",
                            chrono::Datelike::year(&date),
                            chrono::Datelike::month(&date),
                        ),
                        PartitionGranularity::Day => format!(
                            "{prefix}/{file_stem}/year={:04}/month={:02}/day={:02}/part.parquet",
                            chrono::Datelike::year(&date),
                            chrono::Datelike::month(&date),
                            chrono::Datelike::day(&date),
                        ),
                    };
                    spool_path = self.root.join(format!("{relative_path}.rows"));
                    last_bucket.clear();
                    last_bucket.push_str(bucket);
                }
            }

            if let Some(partition) = self.partitions.get_mut(relative_path.as_str()) {
                ensure!(
                    partition.dataset_key == key,
                    "projection spool path collision for {}",
                    partition.spec.relative_path
                );
                partition.rows += 1;
            } else {
                if let Some(parent) = spool_path.parent() {
                    fs::create_dir_all(parent)
                        .with_context(|| format!("create spool directory {}", parent.display()))?;
                }
                self.partitions.insert(
                    relative_path.clone(),
                    SpoolPartition {
                        dataset_key: key.clone(),
                        spec: DatasetSpec {
                            relative_path: relative_path.clone(),
                            logical_path: logical_path.clone(),
                            source_system: source_system.to_owned(),
                            dataset: dataset.to_owned(),
                            restricted,
                            fields: fields.clone(),
                        },
                        spool_path: Some(spool_path.clone()),
                        rows: 1,
                    },
                );
            }
            self.write_record(&spool_path, &fields, &values)?;
        }
        Ok(())
    }

    fn write_record(&mut self, path: &Path, fields: &[String], values: &FieldValues) -> Result<()> {
        self.access_clock += 1;
        if !self.open_writers.contains_key(path) {
            if self.open_writers.len() >= self.max_open_writers {
                let oldest = self
                    .open_writers
                    .iter()
                    .min_by_key(|(_, (_, access))| *access)
                    .map(|(path, _)| path.clone())
                    .context("open spool writer cache is unexpectedly empty")?;
                if let Some((mut writer, _)) = self.open_writers.remove(&oldest) {
                    writer
                        .flush()
                        .with_context(|| format!("flush spool {}", oldest.display()))?;
                }
            }
            let file = OpenOptions::new()
                .create(true)
                .append(true)
                .open(path)
                .with_context(|| format!("open projection spool {}", path.display()))?;
            self.open_writers.insert(
                path.to_path_buf(),
                (BufWriter::new(file), self.access_clock),
            );
        }
        let (writer, access) = self
            .open_writers
            .get_mut(path)
            .context("projection spool writer disappeared")?;
        *access = self.access_clock;
        for field in fields {
            match values.get(field.as_str()).filter(|value| !value.is_empty()) {
                None => writer.write_all(&u32::MAX.to_le_bytes())?,
                Some(value) => {
                    let bytes = value.as_bytes();
                    let length = u32::try_from(bytes.len()).with_context(|| {
                        format!("field {field} exceeds the projection spool record limit")
                    })?;
                    writer.write_all(&length.to_le_bytes())?;
                    writer.write_all(bytes)?;
                }
            }
        }
        Ok(())
    }

    pub fn finish(mut self) -> Result<ProjectionSpoolOutput> {
        for (path, (mut writer, _)) in std::mem::take(&mut self.open_writers) {
            writer
                .flush()
                .with_context(|| format!("flush projection spool {}", path.display()))?;
        }
        for key in std::mem::take(&mut self.declared) {
            if self
                .partitions
                .values()
                .any(|partition| partition.dataset_key == key)
            {
                continue;
            }
            let file_stem = contracts::snake_case(&key.dataset);
            let relative_path = format!("{}/{file_stem}.parquet", key.prefix);
            self.partitions.insert(
                relative_path.clone(),
                SpoolPartition {
                    dataset_key: key.clone(),
                    spec: DatasetSpec {
                        relative_path: relative_path.clone(),
                        logical_path: relative_path,
                        source_system: key.source_system.clone(),
                        dataset: key.dataset.clone(),
                        restricted: key.restricted,
                        fields: contracts::fields(&key.source_system, &key.dataset)?,
                    },
                    spool_path: None,
                    rows: 0,
                },
            );
        }
        Ok(ProjectionSpoolOutput {
            root: self.root,
            partitions: self.partitions.into_values().collect(),
        })
    }
}

pub fn publish_projection_spool(
    run_base: &Path,
    output: ProjectionSpoolOutput,
    compression: Compression,
    total_batch_rows: usize,
    workers: usize,
) -> Result<(Vec<SourceObject>, Vec<DatasetSchema>)> {
    let worker_count = workers.max(1);
    let batch_rows = (total_batch_rows / worker_count).max(1_000);
    let pool = rayon::ThreadPoolBuilder::new()
        .num_threads(worker_count)
        .thread_name(|index| format!("datagen-partition-{index}"))
        .build()
        .context("create partition publication worker pool")?;
    let mut published = pool.install(|| {
        output
            .partitions
            .into_par_iter()
            .map(|partition| publish_spool_partition(run_base, partition, compression, batch_rows))
            .collect::<Result<Vec<_>>>()
    })?;
    published.sort_by(|left, right| left.0.path.cmp(&right.0.path));
    fs::remove_dir_all(&output.root).with_context(|| {
        format!(
            "remove completed projection spool {}",
            output.root.display()
        )
    })?;
    let (objects, schemas): (Vec<_>, Vec<_>) = published.into_iter().unzip();
    Ok((objects, schemas))
}

fn publish_spool_partition(
    run_base: &Path,
    partition: SpoolPartition,
    compression: Compression,
    batch_rows: usize,
) -> Result<(SourceObject, DatasetSchema)> {
    let field_count = partition.spec.fields.len();
    let mut writer =
        ParquetDatasetWriter::create(run_base, partition.spec, compression, batch_rows)?;
    if let Some(spool_path) = partition.spool_path {
        let mut reader = BufReader::with_capacity(
            1024 * 1024,
            File::open(&spool_path)
                .with_context(|| format!("open projection spool {}", spool_path.display()))?,
        );
        for _ in 0..partition.rows {
            let mut row = Vec::with_capacity(field_count);
            for _ in 0..field_count {
                let mut encoded_length = [0_u8; 4];
                reader.read_exact(&mut encoded_length).with_context(|| {
                    format!("read projection spool length from {}", spool_path.display())
                })?;
                let length = u32::from_le_bytes(encoded_length);
                if length == u32::MAX {
                    row.push(None);
                    continue;
                }
                let mut bytes = vec![0_u8; usize::try_from(length)?];
                reader.read_exact(&mut bytes).with_context(|| {
                    format!("read projection spool value from {}", spool_path.display())
                })?;
                row.push(Some(String::from_utf8(bytes).with_context(|| {
                    format!(
                        "decode projection spool value from {}",
                        spool_path.display()
                    )
                })?));
            }
            writer.push(row)?;
        }
        let mut trailing = [0_u8; 1];
        ensure!(
            reader.read(&mut trailing)? == 0,
            "projection spool {} has trailing bytes",
            spool_path.display()
        );
    }
    writer.finish()
}
