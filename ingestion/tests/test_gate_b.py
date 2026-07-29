"""Focused Gate B contract tests independent of the full 10-year pin."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from retail_ingestion.publication import PublicationError, publish_candidate
from retail_ingestion.quality.gate_b import (
    GateBError,
    _apply_upstream_capability_downgrades,
    _b01_schema,
)


def test_required_nullable_is_presence_not_non_null() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE SCHEMA canonical_data;
            CREATE TABLE canonical_data.suppliers_leadtimes (
                supplier_id VARCHAR,
                from_location_id VARCHAR
            );
            INSERT INTO canonical_data.suppliers_leadtimes VALUES
                ('supplier-1', NULL)
            """
        )
        schema = {
            "closedEnums": {"evidenceGrade": []},
            "entities": {
                "suppliers_leadtimes": {
                    "fields": {
                        "supplier_id": {"type": "string", "required": True},
                        "from_location_id": {
                            "type": "string",
                            "required": True,
                            "nullable": True,
                        },
                    }
                }
            },
        }
        assert _b01_schema(
            connection,
            schema,
            {"suppliers_leadtimes"},
            {"suppliers_leadtimes"},
        ) == []

        connection.execute(
            """
            CREATE OR REPLACE TABLE canonical_data.suppliers_leadtimes (
                supplier_id VARCHAR
            )
            """
        )
        errors = _b01_schema(
            connection,
            schema,
            {"suppliers_leadtimes"},
            {"suppliers_leadtimes"},
        )
        assert errors == [
            "suppliers_leadtimes.from_location_id: required column is absent"
        ]
    finally:
        connection.close()


def test_publication_refuses_a_critical_gate_report(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.duckdb"
    candidate.write_bytes(b"not-opened")
    candidate.with_suffix(".duckdb.manifest.json").write_text(
        json.dumps({"sourceSnapshotId": "snapshot-a"}),
        encoding="utf-8",
    )
    report = tmp_path / "gate-b.json"
    report.write_text(
        json.dumps(
            {
                "status": "critical",
                "sourceSnapshotId": "snapshot-a",
                "rules": [{"outcome": "critical"}],
            }
        ),
        encoding="utf-8",
    )

    try:
        publish_candidate(
            candidate,
            report,
            tmp_path / "curated",
            execution_profile={"duckdbThreads": 1, "memoryLimitGb": 1},
        )
    except PublicationError as exc:
        assert "not passing" in str(exc)
    else:
        raise AssertionError("critical Gate B report must block publication")


def test_gate_a_capability_downgrade_reaches_publication_mask() -> None:
    merged = _apply_upstream_capability_downgrades(
        {"data_management": {"available": True}},
        {
            "sourceSnapshotId": "snapshot-a",
            "rules": [
                {
                    "ruleId": "A08",
                    "outcome": "capability_downgrade",
                    "affectedCapability": "exact_source_reconciliation",
                    "reasonCode": "SOURCE_CONTROLS_UNAVAILABLE",
                }
            ],
        },
        source_snapshot_id="snapshot-a",
    )

    assert merged["exact_source_reconciliation"] == {
        "available": False,
        "reasonCode": "SOURCE_CONTROLS_UNAVAILABLE",
        "evidence": "A08",
        "sourceGate": "A",
    }

    try:
        _apply_upstream_capability_downgrades(
            {},
            {"sourceSnapshotId": "snapshot-b", "rules": []},
            source_snapshot_id="snapshot-a",
        )
    except GateBError as exc:
        assert "snapshot identities differ" in str(exc)
    else:
        raise AssertionError("Gate A evidence from another snapshot must be rejected")
