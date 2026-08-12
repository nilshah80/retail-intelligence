use std::fs::{self, File};
use std::io::{BufReader, Read};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context, Result, ensure};
use arrow_array::builder::StringBuilder;
use arrow_array::{ArrayRef, RecordBatch};
use arrow_schema::{DataType, Field, Schema};
use parquet::arrow::ArrowWriter;
use parquet::basic::{Compression as ParquetCompression, ZstdLevel};
use parquet::file::properties::WriterProperties;

use crate::config::Compression;
use crate::manifest::{DatasetSchema, SchemaField, SourceObject};
use sha2::{Digest, Sha256};

pub type Row = Vec<Option<String>>;

#[derive(Debug, Clone)]
pub struct DatasetSpec {
    pub relative_path: String,
    pub logical_path: String,
    pub source_system: String,
    pub dataset: String,
    pub restricted: bool,
    pub fields: Vec<String>,
}

impl DatasetSpec {
    #[must_use]
    pub fn schema_record(&self) -> DatasetSchema {
        DatasetSchema {
            logical_path: self.logical_path.clone(),
            source_system: self.source_system.clone(),
            dataset: self.dataset.clone(),
            restricted: self.restricted,
            fields: self
                .fields
                .iter()
                .map(|name| SchemaField {
                    name: name.clone(),
                    physical_type: "VARCHAR".to_owned(),
                    nullable: true,
                })
                .collect(),
        }
    }
}

#[derive(Debug)]
pub struct AtomicRun {
    target: PathBuf,
    stage: PathBuf,
    promoted: bool,
}

impl AtomicRun {
    pub fn create(output_root: &Path, scenario_id: &str, run_id: &str) -> Result<Self> {
        let parent = output_root.join(scenario_id);
        fs::create_dir_all(&parent)
            .with_context(|| format!("create output parent {}", parent.display()))?;
        let target = parent.join(run_id);
        ensure!(
            !target.exists(),
            "Rust output target already exists: {}",
            target.display()
        );
        let stage = parent.join(format!(".{run_id}.rust-staging-{}", std::process::id()));
        ensure!(
            !stage.exists(),
            "Rust staging path already exists: {}",
            stage.display()
        );
        fs::create_dir(&stage)
            .with_context(|| format!("create staging directory {}", stage.display()))?;
        Ok(Self {
            target,
            stage,
            promoted: false,
        })
    }

    #[must_use]
    pub fn base(&self) -> &Path {
        &self.stage
    }

    #[must_use]
    pub fn target(&self) -> &Path {
        &self.target
    }

    pub fn promote(mut self) -> Result<PathBuf> {
        fs::rename(&self.stage, &self.target).with_context(|| {
            format!(
                "promote {} to {}",
                self.stage.display(),
                self.target.display()
            )
        })?;
        self.promoted = true;
        Ok(self.target.clone())
    }
}

impl Drop for AtomicRun {
    fn drop(&mut self) {
        if !self.promoted && self.stage.is_dir() {
            let _ = fs::remove_dir_all(&self.stage);
        }
    }
}

pub struct ParquetDatasetWriter {
    spec: DatasetSpec,
    path: PathBuf,
    compression: Compression,
    batch_rows: usize,
    rows: u64,
    schema: Arc<Schema>,
    writer: ArrowWriter<File>,
    pending: Vec<Row>,
}

impl ParquetDatasetWriter {
    pub fn create(
        run_base: &Path,
        spec: DatasetSpec,
        compression: Compression,
        batch_rows: usize,
    ) -> Result<Self> {
        ensure!(
            !spec.fields.is_empty(),
            "dataset {} has no fields",
            spec.dataset
        );
        let path = run_base.join(&spec.relative_path);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .with_context(|| format!("create dataset directory {}", parent.display()))?;
        }
        let schema = Arc::new(Schema::new(
            spec.fields
                .iter()
                .map(|name| Field::new(name, DataType::Utf8, true))
                .collect::<Vec<_>>(),
        ));
        let properties = WriterProperties::builder()
            .set_compression(match compression {
                Compression::None => ParquetCompression::UNCOMPRESSED,
                Compression::Snappy => ParquetCompression::SNAPPY,
                Compression::Zstd => ParquetCompression::ZSTD(ZstdLevel::default()),
            })
            .set_max_row_group_row_count(Some(batch_rows))
            .set_created_by("retail-datagen-rust".to_owned())
            .build();
        let file = File::create(&path).with_context(|| format!("create {}", path.display()))?;
        let writer = ArrowWriter::try_new(file, Arc::clone(&schema), Some(properties))
            .with_context(|| format!("open Parquet writer {}", path.display()))?;
        Ok(Self {
            spec,
            path,
            compression,
            batch_rows,
            rows: 0,
            schema,
            writer,
            pending: Vec::with_capacity(batch_rows),
        })
    }

    pub fn push(&mut self, row: Row) -> Result<()> {
        ensure!(
            row.len() == self.spec.fields.len(),
            "dataset {} expected {} columns, received {}",
            self.spec.dataset,
            self.spec.fields.len(),
            row.len()
        );
        self.pending.push(row);
        if self.pending.len() >= self.batch_rows {
            self.flush()?;
        }
        Ok(())
    }

    pub fn extend(&mut self, rows: impl IntoIterator<Item = Row>) -> Result<()> {
        for row in rows {
            self.push(row)?;
        }
        Ok(())
    }

    fn flush(&mut self) -> Result<()> {
        if self.pending.is_empty() {
            return Ok(());
        }
        let row_count = self.pending.len();
        let mut columns: Vec<ArrayRef> = Vec::with_capacity(self.spec.fields.len());
        for column_index in 0..self.spec.fields.len() {
            let estimated_bytes = self
                .pending
                .iter()
                .filter_map(|row| row[column_index].as_ref())
                .map(String::len)
                .sum();
            let mut builder = StringBuilder::with_capacity(row_count, estimated_bytes);
            for row in &self.pending {
                builder.append_option(row[column_index].as_deref());
            }
            columns.push(Arc::new(builder.finish()));
        }
        let batch = RecordBatch::try_new(Arc::clone(&self.schema), columns)
            .with_context(|| format!("build record batch for {}", self.spec.dataset))?;
        self.writer
            .write(&batch)
            .with_context(|| format!("write Parquet batch for {}", self.spec.dataset))?;
        self.rows += row_count as u64;
        self.pending.clear();
        Ok(())
    }

    pub fn finish(mut self) -> Result<(SourceObject, DatasetSchema)> {
        self.flush()?;
        self.writer
            .close()
            .with_context(|| format!("close Parquet writer {}", self.path.display()))?;
        let (bytes, digest) = file_sha256(&self.path)?;
        let object = SourceObject {
            path: self.spec.relative_path.clone(),
            logical_path: self.spec.logical_path.clone(),
            source_system: self.spec.source_system.clone(),
            dataset: self.spec.dataset.clone(),
            format: "parquet".to_owned(),
            compression: match self.compression {
                Compression::None => "none",
                Compression::Snappy => "snappy",
                Compression::Zstd => "zstd",
            }
            .to_owned(),
            rows: Some(self.rows),
            bytes,
            sha256: digest,
            // Parquet objects are authoritative source bytes. This must match
            // Python's writer contract: only source-run.duckdb is a logical,
            // non-authoritative mirror that landing may exclude from identity.
            content_determinism: "byte".to_owned(),
            restricted: self.spec.restricted,
        };
        Ok((object, self.spec.schema_record()))
    }
}

/// Hash a file with constant memory. Full Gulf objects can be several gigabytes each.
pub fn file_sha256(path: &Path) -> Result<(u64, String)> {
    let file = File::open(path).with_context(|| format!("open {} for hashing", path.display()))?;
    let bytes = file
        .metadata()
        .with_context(|| format!("stat {}", path.display()))?
        .len();
    let mut reader = BufReader::with_capacity(1024 * 1024, file);
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let read = reader
            .read(&mut buffer)
            .with_context(|| format!("read {} for hashing", path.display()))?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok((bytes, hex::encode(hasher.finalize())))
}

pub fn write_json(path: &Path, value: &impl serde::Serialize) -> Result<()> {
    let bytes = serde_json::to_vec_pretty(value).context("serialize JSON artifact")?;
    let mut with_newline = bytes;
    with_newline.push(b'\n');
    fs::write(path, with_newline).with_context(|| format!("write {}", path.display()))
}

#[cfg(test)]
mod tests {
    use tempfile::tempdir;

    use super::{DatasetSpec, ParquetDatasetWriter};
    use crate::config::Compression;

    #[test]
    fn parquet_is_byte_deterministic_source_content() {
        let directory = tempdir().expect("temporary output");
        let spec = DatasetSpec {
            relative_path: "companion/test/rows.parquet".to_owned(),
            logical_path: "companion/test/rows.parquet".to_owned(),
            source_system: "companion".to_owned(),
            dataset: "rows".to_owned(),
            restricted: true,
            fields: vec!["id".to_owned()],
        };
        let mut writer = ParquetDatasetWriter::create(
            directory.path(),
            spec,
            Compression::Zstd,
            16,
        )
        .expect("create parquet writer");
        writer
            .push(vec![Some("row-1".to_owned())])
            .expect("write source row");

        let (object, _) = writer.finish().expect("finish parquet object");
        assert_eq!(object.content_determinism, "byte");
        assert!(object.restricted, "restricted truth bytes still bind identity");
    }
}
