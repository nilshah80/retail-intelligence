"""Permission-safe catalog and DuckDB relations for landed public objects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

import duckdb

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SourceCatalogError(RuntimeError):
    """Public source objects cannot be resolved safely."""


def sql_string(value: str) -> str:
    """Return a DuckDB string literal without relying on shell escaping."""

    return "'" + value.replace("'", "''") + "'"


def sql_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SourceCatalogError(f"unsafe SQL identifier: {value!r}")
    return '"' + value + '"'


@dataclass(frozen=True)
class SourceObject:
    source_system: str
    dataset: str
    logical_path: str
    object_path: str
    file_path: Path
    artifact_format: str
    rows: int | None
    bytes: int
    sha256: str
    source_instance: str
    market_id: str
    currency_code: str
    timezone: str


@dataclass(frozen=True)
class DatasetRef:
    source_system: str
    dataset: str
    logical_path: str
    artifact_format: str
    objects: tuple[SourceObject, ...]

    @property
    def source_instances(self) -> tuple[str, ...]:
        return tuple(sorted({row.source_instance for row in self.objects}))


class PublicSourceCatalog:
    """Resolved public objects only; restricted paths are never represented."""

    def __init__(
        self,
        *,
        snapshot_root: Path,
        landing_manifest: Mapping[str, Any],
        profile: Mapping[str, Any],
        objects: Iterable[SourceObject],
    ) -> None:
        self.snapshot_root = snapshot_root
        self.landing_manifest = dict(landing_manifest)
        self.profile = dict(profile)
        self.objects = tuple(objects)
        grouped: dict[tuple[str, str, str], list[SourceObject]] = {}
        for row in self.objects:
            grouped.setdefault(
                (row.source_system, row.dataset, row.logical_path), []
            ).append(row)
        self.datasets = tuple(
            DatasetRef(
                source_system=key[0],
                dataset=key[1],
                logical_path=key[2],
                artifact_format=next(iter({row.artifact_format for row in rows})),
                objects=tuple(sorted(rows, key=lambda row: row.object_path)),
            )
            for key, rows in sorted(grouped.items())
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot_root: str | Path,
        profile: Mapping[str, Any],
    ) -> "PublicSourceCatalog":
        root = Path(snapshot_root).expanduser().resolve()
        try:
            landing = json.loads(
                (root / "landing-manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise SourceCatalogError(f"cannot read landing manifest: {exc}") from exc
        instances = list(profile.get("sourceInstances", []))
        objects: list[SourceObject] = []
        for row in landing.get("objects", []):
            if row.get("permissionLane") != "public":
                continue
            landed_path = row.get("landedPath")
            if not isinstance(landed_path, str):
                raise SourceCatalogError("public object has no landedPath")
            pure = PurePosixPath(landed_path)
            if (
                pure.is_absolute()
                or "\\" in landed_path
                or any(part in {"", ".", ".."} for part in landed_path.split("/"))
                or pure.parts[0] != "public"
            ):
                raise SourceCatalogError(f"unsafe public landedPath: {landed_path!r}")
            file_path = root.joinpath(*pure.parts).resolve()
            try:
                file_path.relative_to(root / "public")
            except ValueError as exc:
                raise SourceCatalogError(
                    f"public object escapes physical permission lane: {landed_path}"
                ) from exc
            if not file_path.is_file():
                raise SourceCatalogError(f"public object is missing: {file_path}")

            logical_path = str(row.get("logicalPath", ""))
            source_system = str(row.get("sourceSystem", ""))
            matching = [
                value
                for value in instances
                if value.get("sourceSystem") == source_system
                and logical_path.startswith(str(value.get("logicalPathPrefix", "")))
            ]
            if source_system == "generator":
                instance = {
                    "sourceInstance": "generator-metadata",
                    "marketId": "not_applicable",
                    "currencyCode": "XXX",
                    "timezone": "UTC",
                }
            elif len(matching) == 1:
                instance = matching[0]
            else:
                raise SourceCatalogError(
                    f"{logical_path}: expected one source-instance mapping, got "
                    f"{len(matching)}"
                )
            formats = str(row.get("format", ""))
            if formats not in {"parquet", "csv", "json", "yaml", "jsonl"}:
                raise SourceCatalogError(
                    f"{logical_path}: ordinary ingestion does not support format "
                    f"{formats!r}"
                )
            objects.append(
                SourceObject(
                    source_system=source_system,
                    dataset=str(row.get("dataset", "")),
                    logical_path=logical_path,
                    object_path=str(row.get("objectPath", "")),
                    file_path=file_path,
                    artifact_format=formats,
                    rows=int(row["rows"]) if row.get("rows") is not None else None,
                    bytes=int(row["bytes"]),
                    sha256=str(row["sha256"]),
                    source_instance=str(instance["sourceInstance"]),
                    market_id=str(instance["marketId"]),
                    currency_code=str(instance["currencyCode"]),
                    timezone=str(instance["timezone"]),
                )
            )
        return cls(
            snapshot_root=root,
            landing_manifest=landing,
            profile=profile,
            objects=objects,
        )

    def for_source(self, source_system: str) -> tuple[DatasetRef, ...]:
        return tuple(
            row for row in self.datasets if row.source_system == source_system
        )

    def find(self, source_system: str, dataset: str) -> tuple[DatasetRef, ...]:
        return tuple(
            row
            for row in self.datasets
            if row.source_system == source_system and row.dataset == dataset
        )

    def register_metadata(self, connection: duckdb.DuckDBPyConnection) -> None:
        connection.execute("CREATE SCHEMA IF NOT EXISTS ingest_meta")
        connection.execute(
            """
            CREATE OR REPLACE TABLE ingest_meta.source_files (
                file_path VARCHAR PRIMARY KEY,
                object_path VARCHAR NOT NULL,
                logical_path VARCHAR NOT NULL,
                source_system VARCHAR NOT NULL,
                dataset VARCHAR NOT NULL,
                source_instance VARCHAR NOT NULL,
                market_id VARCHAR NOT NULL,
                currency_code VARCHAR NOT NULL,
                timezone VARCHAR NOT NULL,
                raw_object_hash VARCHAR NOT NULL,
                manifest_rows BIGINT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO ingest_meta.source_files VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row.file_path),
                    row.object_path,
                    row.logical_path,
                    row.source_system,
                    row.dataset,
                    row.source_instance,
                    row.market_id,
                    row.currency_code,
                    row.timezone,
                    row.sha256,
                    row.rows,
                )
                for row in self.objects
            ],
        )

    def relation_sql(self, refs: Iterable[DatasetRef]) -> str:
        selected = tuple(refs)
        if not selected:
            raise SourceCatalogError("cannot build a relation for an empty dataset")
        formats = {row.artifact_format for row in selected}
        if len(formats) != 1:
            raise SourceCatalogError(f"mixed dataset formats: {sorted(formats)}")
        artifact_format = next(iter(formats))
        paths = [
            str(item.file_path)
            for ref in selected
            for item in ref.objects
        ]
        rendered_paths = "[" + ", ".join(sql_string(path) for path in paths) + "]"
        if artifact_format == "parquet":
            return (
                f"read_parquet({rendered_paths}, filename=true, union_by_name=true)"
            )
        if artifact_format == "csv":
            return (
                f"read_csv_auto({rendered_paths}, filename=true, "
                "header=true, all_varchar=true, union_by_name=true)"
            )
        if artifact_format == "jsonl":
            return (
                f"read_json_auto({rendered_paths}, filename=true, "
                "format='newline_delimited', union_by_name=true)"
            )
        if artifact_format == "json":
            return (
                f"read_json_auto({rendered_paths}, filename=true, "
                "format='auto', union_by_name=true)"
            )
        raise SourceCatalogError(
            f"{artifact_format!r} is metadata, not a tabular adapter input"
        )


__all__ = [
    "DatasetRef",
    "PublicSourceCatalog",
    "SourceCatalogError",
    "SourceObject",
    "sql_identifier",
    "sql_string",
]
