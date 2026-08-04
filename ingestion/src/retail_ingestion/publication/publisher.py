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

#: Entities the publication step materialises itself, so they cannot appear in the
#: candidate's declared control set. `_write_gate_controls` rebuilds
#: `reconciliation_results` from the Gate-B report. Listing them explicitly is what
#: separates "the publisher created this" from "an uncontrolled table appeared",
#: which the recomputed controls must be able to tell apart.
PUBLICATION_CREATED_ENTITIES: frozenset[str] = frozenset(
    {"reconciliation_results"}
)


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


def _market_name(market_id: str) -> str:
    acronyms = {"us": "US", "uk": "UK"}
    return " ".join(
        acronyms.get(part, part.capitalize())
        for part in market_id.split("-")
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


def _business_controls(
    connection: duckdb.DuckDBPyConnection,
) -> dict[str, Any]:
    start_date, end_date = connection.execute(
        "SELECT min(date), max(date) FROM canonical_data.calendar"
    ).fetchone()
    active_skus = connection.execute(
        """
        SELECT count(DISTINCT sku_id)
        FROM canonical_data.assortment_calendar
        WHERE active_from <= ?
          AND (active_to IS NULL OR active_to >= ?)
        """,
        [end_date, end_date],
    ).fetchone()[0]
    stores = [
        {
            "storeId": row[0],
            "marketId": row[1],
            "currencyCode": row[2],
            "timezone": row[3],
            "region": row[4],
            "format": row[5],
            "city": row[6],
            "name": row[7],
            "active": row[8],
        }
        for row in connection.execute(
            """
            SELECT
                stores.store_id,
                stores.market_id,
                stores.currency_code,
                stores.timezone,
                stores.region,
                stores.format,
                stores.city,
                locations.name,
                locations.active
            FROM canonical_data.stores AS stores
            JOIN canonical_data.locations AS locations
              ON locations.location_id = stores.store_id
             AND locations.type = 'store'
            ORDER BY stores.market_id, stores.store_id
            """
        ).fetchall()
    ]
    channels = [
        {
            "marketId": row[0],
            "channelId": row[1],
            "name": row[2],
            "type": row[3],
        }
        for row in connection.execute(
            """
            SELECT market_id, channel_id, name, type
            FROM canonical_data.channels
            WHERE active
            ORDER BY market_id, channel_id
            """
        ).fetchall()
    ]
    markets = [
        {"marketId": market_id, "name": _market_name(market_id)}
        for market_id in sorted({row["marketId"] for row in stores})
    ]
    observation_count, fx_start, fx_end = connection.execute(
        """
        SELECT count(*), min(rate_date), max(rate_date)
        FROM canonical_data.fx_rates
        """
    ).fetchone()
    latest_rates = [
        {
            "baseCurrency": row[0],
            "quoteCurrency": row[1],
            "rate": str(row[2]),
            "rateDate": str(row[3]),
        }
        for row in connection.execute(
            """
            SELECT base_ccy, quote_ccy, rate, rate_date
            FROM canonical_data.fx_rates
            QUALIFY row_number() OVER (
                PARTITION BY base_ccy, quote_ccy
                ORDER BY rate_date DESC, known_as_of DESC
            ) = 1
            ORDER BY base_ccy, quote_ccy
            """
        ).fetchall()
    ]
    reporting_currencies = {
        row["quoteCurrency"] for row in latest_rates
    }
    if len(reporting_currencies) != 1:
        raise PublicationError(
            "FX business controls require one reporting currency"
        )
    return {
        "asOfDate": str(end_date),
        "dateRange": {
            "start": str(start_date),
            "end": str(end_date),
        },
        "totalSkus": int(
            connection.execute(
                "SELECT count(*) FROM canonical_data.products"
            ).fetchone()[0]
        ),
        "activeSkus": int(active_skus),
        "markets": markets,
        "stores": stores,
        "channels": channels,
        "currencies": sorted({row["currencyCode"] for row in stores}),
        "fx": {
            "reportingCurrency": reporting_currencies.pop(),
            "coverage": {
                "start": str(fx_start),
                "end": str(fx_end),
                "observations": int(observation_count),
            },
            "rates": latest_rates,
        },
        "forecastCoveragePct": None,
        "modelAccuracyPct": None,
    }


def _recomputed_entity_controls(
    connection: duckdb.DuckDBPyConnection,
    candidate_controls: Mapping[str, Any],
) -> dict[str, Any]:
    """Recompute every entity control from the final publication database.

    Uses the transform's own `_entity_control`, deliberately, rather than a second
    implementation. Two independent control definitions would eventually disagree,
    and a disagreement between "the control the candidate computed" and "the
    control the publication computed" is exactly the bug this repairs -- it would
    just move rather than close.

    The entity set comes from the candidate controls so the publication attests the
    same inventory the candidate declared: an entity appearing or vanishing between
    the two is a real defect, and it is reported rather than absorbed.
    """

    from ..transforms.core import _entity_control

    present = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'canonical_data'
            """
        ).fetchall()
    }
    declared = set(candidate_controls)
    missing = sorted(declared - present)
    if missing:
        raise PublicationError(
            "candidate declared controls for entities absent from the "
            f"publication database: {missing}"
        )
    # An entity the publication itself materialises is expected; anything else
    # appearing between candidate and publication is an uncontrolled table, which
    # is the same class of defect as an uncontrolled row.
    appeared = sorted(present - declared - PUBLICATION_CREATED_ENTITIES)
    if appeared:
        raise PublicationError(
            "publication database contains entities the candidate never "
            f"declared: {appeared}"
        )
    controlled = sorted((declared | PUBLICATION_CREATED_ENTITIES) & present)
    return {entity: _entity_control(connection, entity) for entity in controlled}


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
            canonical_quality_pct = NULL,
            capability_mask = ?
        """,
        [capability_json],
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
        business_controls = _business_controls(connection)
        # `P4-2` task 20. Controls must be computed from the database that is about
        # to be exported, not copied from the candidate.
        #
        # The candidate manifest was written before `_write_gate_controls` inserted
        # the Gate-B outcomes above, so `entityControls.quality_violations`
        # attested `rows: 0` with no digests while the Parquet export carried the
        # B15 and B21 rows. A control that does not cover the rows it accompanies
        # makes every critical-row gate unfalsifiable: "zero critical violations"
        # and "the controls never looked" are indistinguishable.
        entity_controls = _recomputed_entity_controls(
            connection, candidate_manifest.get("entityControls", {})
        )
        entity_counts = {
            entity: int(
                connection.execute(
                    f'SELECT count(*) FROM canonical_data."{entity}"'
                ).fetchone()[0]
            )
            for entity in sorted(entity_controls)
        }
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
            "entityCounts": entity_counts,
            "entityControls": entity_controls,
            "candidateEntityCounts": candidate_manifest["entityCounts"],
            "businessControls": business_controls,
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
