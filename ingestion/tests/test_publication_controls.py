"""Published controls must cover the rows that were actually exported.

`P4-2` task 20. The publisher copied `entityControls` from the candidate manifest,
which was written *before* `_write_gate_controls` inserted the Gate-B outcomes into
`canonical_data.quality_violations`. So the current pin exports two rows -- B15 and
B21 -- under a control attesting `rows: 0` with no digests.

This is worse than a wrong number. Every critical-row gate reads these controls, so
"zero critical violations" and "the controls never looked" produce identical
evidence. The gate becomes unfalsifiable rather than merely inaccurate.

The regression below builds the exact shape: a candidate whose controls say zero,
a Gate-B report that inserts rows during publication, and an assertion that the
published control counts what the Parquet contains.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from retail_ingestion.publication import publish_candidate

PROFILE = {"duckdbThreads": 1, "memoryLimitGb": 1}

#: DuckDB types for the canonical type vocabulary. Derived DDL keeps this fixture
#: aligned with `contracts/retail_v2/schema.yaml` instead of with a transcription
#: of it -- the fx_rates grain alone drifted three times when written by hand.
_DUCKDB_TYPES = {
    "string": "VARCHAR",
    "date": "DATE",
    "timestamp": "TIMESTAMPTZ",
    "int32": "INTEGER",
    "int64": "BIGINT",
    "boolean": "BOOLEAN",
    "decimal": "DECIMAL(18,8)",
    "json": "VARCHAR",
}


def _canonical_schema() -> dict:
    import yaml

    path = (
        Path(__file__).resolve().parents[2]
        / "contracts"
        / "retail_v2"
        / "schema.yaml"
    )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _create_table_sql(entity: str) -> str:
    fields = _canonical_schema()["entities"][entity]["fields"]
    columns = ", ".join(
        f'"{name}" {_DUCKDB_TYPES[spec["type"]]}' for name, spec in fields.items()
    )
    return f"CREATE TABLE canonical_data.{entity} ({columns})"


#: Only the columns each publisher query actually reads. Unlisted columns are
#: created by the derived DDL and left null, which is what a minimal fixture should
#: assert: the control repair, not the completeness of the demo data.
_PUBLISHER_FIXTURE_ROWS: dict[str, list[dict]] = {
    "calendar": [{"market_id": "india-west", "date": "2026-07-27"}],
    "assortment_calendar": [
        {
            "sku_id": "sku-1",
            "store_id": "india-west:bandra",
            "channel_id": "store",
            "active_from": "2020-01-01",
        }
    ],
    "locations": [
        {
            "location_id": "india-west:bandra",
            "name": "Bandra",
            "type": "store",
            "market_id": "india-west",
            "currency_code": "INR",
            "timezone": "Asia/Kolkata",
            "region": "west",
            "city": "Mumbai",
            "format": "flagship",
            "active": True,
        }
    ],
    "stores": [
        {
            "store_id": "india-west:bandra",
            "market_id": "india-west",
            "currency_code": "INR",
            "timezone": "Asia/Kolkata",
            "region": "west",
            "format": "flagship",
            "city": "Mumbai",
        }
    ],
    "channels": [
        {
            "market_id": "india-west",
            "channel_id": "store",
            "name": "Store",
            "type": "store",
            "active": True,
        }
    ],
    "fx_rates": [
        {
            "base_ccy": "INR",
            "quote_ccy": "USD",
            "rate_date": "2026-07-27",
            "rate": 0.012,
            "known_as_of": "2026-07-27 00:00:00+00",
        }
    ],
    "products": [
        {
            "sku_id": "sku-1",
            "dept_id": "FOODS",
            "category": "FOODS",
            "sub_cat": "BREAD",
            "pack_size": 1,
        }
    ],
    "ingest_runs": [{"ingest_run_id": "run-1", "status": "candidate"}],
    "quality_violations": [],
    "quarantine_records": [],
}



def _entity_control_of(connection: duckdb.DuckDBPyConnection, entity: str) -> dict:
    from retail_ingestion.transforms.core import _entity_control

    return _entity_control(connection, entity)


def _candidate(tmp_path: Path) -> tuple[Path, Path]:
    """A minimal passing candidate whose quality_violations table starts empty."""

    candidate = tmp_path / "candidate.duckdb"
    connection = duckdb.connect(str(candidate))
    connection.execute("CREATE SCHEMA canonical_data")
    for entity, rows in _PUBLISHER_FIXTURE_ROWS.items():
        connection.execute(_create_table_sql(entity))
        for row in rows:
            placeholders = ", ".join("?" for _ in row)
            connection.execute(
                f"INSERT INTO canonical_data.{entity} "
                f"({', '.join(row)}) VALUES ({placeholders})",
                list(row.values()),
            )
    controls = {
        entity: _entity_control_of(connection, entity)
        for entity in sorted(_PUBLISHER_FIXTURE_ROWS)
    }
    counts = {
        entity: int(
            connection.execute(
                f"SELECT count(*) FROM canonical_data.{entity}"
            ).fetchone()[0]
        )
        for entity in controls
    }
    connection.execute("CHECKPOINT")
    connection.close()

    # The candidate genuinely believes quality_violations is empty. It is, at this
    # moment -- which is why copying this control forward was so easy to miss.
    assert controls["quality_violations"]["rows"] == 0

    candidate.with_suffix(".duckdb.manifest.json").write_text(
        json.dumps(
            {
                "sourceSnapshotId": "snapshot-a",
                "semanticFingerprint": "a" * 64,
                "entityCounts": counts,
                "entityControls": controls,
            }
        ),
        encoding="utf-8",
    )

    report = tmp_path / "gate-b.json"
    report.write_text(
        json.dumps(
            {
                "status": "pass",
                "sourceSnapshotId": "snapshot-a",
                "semanticFingerprint": "b" * 64,
                "capabilityMask": {"data_management": {"available": True}},
                # Two outcomes, inserted during publication. Exactly the B15/B21
                # shape the current pin carries.
                "rules": [
                    {
                        "ruleId": "B15",
                        "outcome": "warning",
                        "summary": "stale intervals",
                        "affectedCapability": None,
                        "reasonCode": None,
                    },
                    {
                        "ruleId": "B21",
                        "outcome": "capability_downgrade",
                        "summary": "landing backfill dependency",
                        "affectedCapability": "point_in_time_forecasting",
                        "reasonCode": "LANDING_BACKFILL_DEPENDENCY",
                    },
                ],
                "reconciliation": [],
            }
        ),
        encoding="utf-8",
    )
    return candidate, report


def test_published_controls_count_the_rows_inserted_during_publication(
    tmp_path: Path,
) -> None:
    """The 2-row artifact / 0-row control defect, as a failing-then-passing fixture."""

    candidate, report = _candidate(tmp_path)
    result = publish_candidate(
        candidate, report, tmp_path / "curated", execution_profile=PROFILE
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    control = manifest["entityControls"]["quality_violations"]

    assert control["rows"] == 2, (
        "the published control must count the Gate-B outcomes inserted during "
        "publication, not the zero the candidate saw before them"
    )
    assert manifest["entityCounts"]["quality_violations"] == 2
    # A digest over zero rows is coalesced to "0"; over two real rows at least
    # one of the two controls must be non-zero, which is what proves the digest
    # was computed over the exported rows rather than over an empty table.
    assert control["rowHashXor"] != "0" or control["rowHashSum"] != "0"


def test_the_published_control_reconciles_with_the_exported_parquet(
    tmp_path: Path,
) -> None:
    """Parquet, DuckDB and the manifest control must agree exactly."""

    candidate, report = _candidate(tmp_path)
    result = publish_candidate(
        candidate, report, tmp_path / "curated", execution_profile=PROFILE
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))

    reader = duckdb.connect(":memory:")
    try:
        parquet = result.parquet_root / "quality_violations"
        exported = int(
            reader.execute(
                "SELECT count(*) FROM read_parquet(?)",
                [str(parquet / "**" / "*.parquet")],
            ).fetchone()[0]
        )
    finally:
        reader.close()

    served = duckdb.connect(str(result.duckdb_path), read_only=True)
    try:
        stored = int(
            served.execute(
                "SELECT count(*) FROM canonical_data.quality_violations"
            ).fetchone()[0]
        )
    finally:
        served.close()

    control_rows = manifest["entityControls"]["quality_violations"]["rows"]
    assert exported == stored == control_rows == 2, (
        f"parquet={exported}, duckdb={stored}, control={control_rows}"
    )


def test_the_candidate_counts_are_retained_for_comparison(tmp_path: Path) -> None:
    """Keeping both makes the insertion visible rather than erasing the difference.

    The candidate's zero was not wrong when it was computed. Retaining it lets a
    reader see that rows arrived during publication instead of wondering which
    number to trust.
    """

    candidate, report = _candidate(tmp_path)
    result = publish_candidate(
        candidate, report, tmp_path / "curated", execution_profile=PROFILE
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["candidateEntityCounts"]["quality_violations"] == 0
    assert manifest["entityCounts"]["quality_violations"] == 2


def test_an_entity_that_appears_after_the_candidate_is_refused(
    tmp_path: Path,
) -> None:
    """Silently absorbing a new entity would hide an uncontrolled table.

    The candidate declares the inventory the publication must attest. A table that
    materialises in between is a defect, and the publication refuses rather than
    quietly extending its own control set.
    """

    candidate, report = _candidate(tmp_path)
    connection = duckdb.connect(str(candidate))
    try:
        connection.execute(
            "CREATE TABLE canonical_data.surprise (id VARCHAR)"
        )
        connection.execute("CHECKPOINT")
    finally:
        connection.close()

    with pytest.raises(Exception, match="never declared"):
        publish_candidate(
            candidate, report, tmp_path / "curated", execution_profile=PROFILE
        )
