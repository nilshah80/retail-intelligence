"""Publish a Gate-B-approved candidate as curated DuckDB and Parquet."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import duckdb
from retail_contracts.fingerprint import semantic_fingerprint

PUBLICATION_MANIFEST_VERSION = "retail-curated-publication/v1"


class PublicationError(RuntimeError):
    """A candidate cannot be promoted atomically."""


@dataclass(frozen=True)
class PublicationResult:
    publication_root: Path
    duckdb_path: Path
    parquet_root: Path
    manifest_path: Path
    semantic_fingerprint: str
    object_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": PUBLICATION_MANIFEST_VERSION,
            "publicationRoot": str(self.publication_root),
            "duckdbPath": str(self.duckdb_path),
            "parquetRoot": str(self.parquet_root),
            "manifestPath": str(self.manifest_path),
            "semanticFingerprint": self.semantic_fingerprint,
            "objectCount": self.object_count,
        }


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _table_names(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    return tuple(
        row[0]
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'canonical_data'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ).fetchall()
    )


def _partition_date(entity: str) -> str | None:
    return {
        "sales": "date",
        "sales_adjustments": "event_date",
        "sales_fulfillments": "sale_date",
        "sell_prices": "week_start",
        "stock_snapshots": "snapshot_date",
        "purchase_receipts": "receipt_date",
        "weather_actual": "date",
        "weather_forecast": "target_date",
        "local_events": "date",
        "macro_index": "week_start",
    }.get(entity)


def _write_gate_controls(
    connection: duckdb.DuckDBPyConnection,
    report: Mapping[str, Any],
    *,
    published_at: str,
) -> None:
    capability_json = json.dumps(report["capabilityMask"], sort_keys=True)
    connection.execute(
        """
        UPDATE canonical_data.ingest_runs
        SET status = 'pass',
            canonical_quality_pct = ?,
            capability_mask = ?
        """,
        [
            round(
                100
                * sum(rule["outcome"] != "critical" for rule in report["rules"])
                / len(report["rules"]),
                2,
            ),
            capability_json,
        ],
    )
    for rule in report["rules"]:
        if rule["outcome"] not in {"warning", "capability_downgrade"}:
            continue
        connection.execute(
            """
            INSERT INTO canonical_data.quality_violations VALUES
            (?, (SELECT ingest_run_id FROM canonical_data.ingest_runs LIMIT 1),
             'B', 'publication', NULL, ?, ?, ?, ?, ?, try_cast(? AS TIMESTAMPTZ))
            """,
            [
                hashlib.sha256(
                    f"{rule['ruleId']}:{rule['outcome']}".encode()
                ).hexdigest(),
                rule["ruleId"],
                rule["outcome"],
                rule.get("affectedCapability"),
                rule.get("reasonCode"),
                rule["summary"],
                published_at,
            ],
        )
    connection.execute(
        """
        CREATE OR REPLACE TABLE canonical_data.reconciliation_results (
            reconciliation_id VARCHAR,
            ingest_run_id VARCHAR,
            entity VARCHAR,
            metric VARCHAR,
            raw_value VARCHAR,
            filtered_value VARCHAR,
            canonical_value VARCHAR,
            difference VARCHAR,
            tolerance VARCHAR,
            status VARCHAR
        )
        """
    )
    for row in report["reconciliation"]:
        for index, metric in enumerate(
            ("gross_minor", "net_minor", "tax_minor", "units")
        ):
            difference = int(row["difference"][index])
            raw = int(row["raw"][{
                "gross_minor": "grossMinor",
                "net_minor": "netMinor",
                "tax_minor": "taxMinor",
                "units": "units",
            }[metric]])
            canonical = int(row["canonical"][{
                "gross_minor": "grossMinor",
                "net_minor": "netMinor",
                "tax_minor": "taxMinor",
                "units": "units",
            }[metric]])
            identity = f"{row['currencyCode']}:{metric}"
            connection.execute(
                """
                INSERT INTO canonical_data.reconciliation_results VALUES
                (?, (SELECT ingest_run_id FROM canonical_data.ingest_runs LIMIT 1),
                 'sales', ?, ?, ?, ?, ?, '0', ?)
                """,
                [
                    hashlib.sha256(identity.encode()).hexdigest(),
                    f"{row['currencyCode']}:{metric}",
                    str(raw),
                    str(raw),
                    str(canonical),
                    str(difference),
                    "pass" if difference == 0 else "fail",
                ],
            )


def publish_candidate(
    candidate_database: str | Path,
    gate_b_report: str | Path,
    publication_root: str | Path,
    *,
    execution_profile: Mapping[str, Any],
) -> PublicationResult:
    candidate = Path(candidate_database).expanduser().resolve()
    candidate_manifest_path = candidate.with_suffix(
        candidate.suffix + ".manifest.json"
    )
    report_path = Path(gate_b_report).expanduser().resolve()
    destination = Path(publication_root).expanduser().resolve()
    if destination.exists():
        raise PublicationError(
            f"publication already exists and is immutable: {destination}"
        )
    try:
        candidate_manifest = json.loads(
            candidate_manifest_path.read_text(encoding="utf-8")
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicationError(f"cannot read candidate/Gate-B evidence: {exc}") from exc
    if report.get("status") != "pass":
        raise PublicationError("Gate B is not passing; publication is blocked")
    if any(rule.get("outcome") == "critical" for rule in report.get("rules", [])):
        raise PublicationError("Gate B contains a critical rule outcome")
    if report.get("sourceSnapshotId") != candidate_manifest.get("sourceSnapshotId"):
        raise PublicationError("Gate B and candidate snapshot identities differ")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.publishing-{uuid.uuid4().hex}"
    )
    duckdb_path = temporary / "retail_v2.duckdb"
    parquet_root = temporary / "parquet"
    manifest_path = temporary / "publication-manifest.json"
    published_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        temporary.mkdir()
        parquet_root.mkdir()
        shutil.copy2(candidate, duckdb_path)
        connection = duckdb.connect(str(duckdb_path))
        connection.execute(
            f"SET threads = {max(1, int(execution_profile['duckdbThreads']))}"
        )
        connection.execute(
            f"SET memory_limit = '{max(1, int(execution_profile['memoryLimitGb']))}GB'"
        )
        _write_gate_controls(connection, report, published_at=published_at)
        tables = _table_names(connection)
        for entity in tables:
            entity_root = parquet_root / entity
            partition = _partition_date(entity)
            if partition is None:
                entity_root.mkdir()
                connection.execute(
                    f"""
                    COPY canonical_data."{entity}"
                    TO {_sql_string(str(entity_root / 'data.parquet'))}
                    (FORMAT PARQUET, COMPRESSION ZSTD)
                    """
                )
            else:
                entity_root.mkdir()
                connection.execute(
                    f"""
                    COPY (
                        SELECT *,
                               year("{partition}") AS publication_year,
                               month("{partition}") AS publication_month
                        FROM canonical_data."{entity}"
                    )
                    TO {_sql_string(str(entity_root))}
                    (
                        FORMAT PARQUET,
                        COMPRESSION ZSTD,
                        PARTITION_BY (publication_year, publication_month)
                    )
                    """
                )
        connection.execute("CHECKPOINT")
        connection.close()
        connection = None

        objects: list[dict[str, Any]] = []
        for path in sorted(parquet_root.rglob("*.parquet")):
            objects.append(
                {
                    "path": path.relative_to(temporary).as_posix(),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
        duckdb_hash = _sha256(duckdb_path)
        manifest: dict[str, Any] = {
            "schemaVersion": PUBLICATION_MANIFEST_VERSION,
            "sourceSnapshotId": candidate_manifest["sourceSnapshotId"],
            "candidateSemanticFingerprint": candidate_manifest[
                "semanticFingerprint"
            ],
            "gateBSemanticFingerprint": report["semanticFingerprint"],
            "capabilityMask": report["capabilityMask"],
            "entityCounts": candidate_manifest["entityCounts"],
            "entityControls": candidate_manifest.get("entityControls", {}),
            "duckdb": {
                "path": "retail_v2.duckdb",
                "bytes": duckdb_path.stat().st_size,
                "sha256": duckdb_hash,
            },
            "objects": objects,
            "publishedAt": published_at,
            "executionProfile": dict(execution_profile),
        }
        manifest["semanticFingerprint"] = semantic_fingerprint(
            manifest,
            volatile_pointers=(
                "/duckdb",
                "/objects",
                "/publishedAt",
                "/executionProfile",
            ),
        )
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, destination)
        return PublicationResult(
            publication_root=destination,
            duckdb_path=destination / "retail_v2.duckdb",
            parquet_root=destination / "parquet",
            manifest_path=destination / "publication-manifest.json",
            semantic_fingerprint=manifest["semanticFingerprint"],
            object_count=len(objects),
        )
    except Exception:
        if connection is not None:
            connection.close()
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


__all__ = [
    "PUBLICATION_MANIFEST_VERSION",
    "PublicationError",
    "PublicationResult",
    "publish_candidate",
]
