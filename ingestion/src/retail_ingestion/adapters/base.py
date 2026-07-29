"""Adapter protocol and shared raw-view registration."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping

import duckdb

from retail_ingestion.readers import PublicSourceCatalog
from retail_ingestion.readers.catalog import sql_identifier, sql_string


def snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()


@dataclass(frozen=True)
class AdapterContext:
    connection: duckdb.DuckDBPyConnection
    catalog: PublicSourceCatalog
    profile: Mapping[str, Any]

    @property
    def landing(self) -> Mapping[str, Any]:
        return self.catalog.landing_manifest


class SourceAdapter(ABC):
    source_system: str
    adapter_version: str
    raw_schema: str

    def register_raw_views(self, context: AdapterContext) -> tuple[str, ...]:
        """Expose only this adapter's public tabular datasets as raw views."""

        connection = context.connection
        connection.execute(
            f"CREATE SCHEMA IF NOT EXISTS {sql_identifier(self.raw_schema)}"
        )
        created: list[str] = []
        datasets = {
            ref.dataset
            for ref in context.catalog.for_source(self.source_system)
            if ref.artifact_format in {"parquet", "csv", "jsonl", "json"}
        }
        for dataset in sorted(datasets):
            refs = context.catalog.find(self.source_system, dataset)
            relation = context.catalog.relation_sql(refs)
            view_name = snake_case(dataset)
            connection.execute(
                f"""
                CREATE OR REPLACE VIEW {sql_identifier(self.raw_schema)}.
                    {sql_identifier(view_name)} AS
                SELECT
                    raw.* EXCLUDE (filename),
                    meta.source_instance AS _source_instance,
                    meta.market_id AS _market_id,
                    meta.currency_code AS _market_currency_code,
                    meta.timezone AS _business_timezone,
                    meta.raw_object_hash AS _raw_object_hash,
                    meta.object_path AS _raw_object_path
                FROM {relation} AS raw
                JOIN ingest_meta.source_files AS meta
                  ON raw.filename = meta.file_path
                 AND meta.source_system = {sql_string(self.source_system)}
                 AND meta.dataset = {sql_string(dataset)}
                """
            )
            created.append(f"{self.raw_schema}.{view_name}")
        return tuple(created)

    @abstractmethod
    def materialize_staging(self, context: AdapterContext) -> tuple[str, ...]:
        """Emit this source's standardized staging relations."""


__all__ = ["AdapterContext", "SourceAdapter", "snake_case"]
