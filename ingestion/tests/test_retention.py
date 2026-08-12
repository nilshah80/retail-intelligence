"""Accepted evidence survives after disposable work is pruned."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from retail_ingestion.readiness.operational import (
    write_operational_readiness_sidecar,
    write_readiness_retention,
)
from retail_ingestion.retention import RetentionError, finalize_publication


REPO_ROOT = Path(__file__).resolve().parents[2]
READINESS_SCHEMA = REPO_ROOT / "contracts/onboarding/readiness-report-v2.schema.json"
READINESS_RETENTION_SCHEMA = (
    REPO_ROOT / "contracts/onboarding/readiness-retention.schema.json"
)
PRODUCER_REGISTRY = (
    REPO_ROOT / "contracts/onboarding/readiness-producer-registry.json"
)


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _publication_fixture(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    work = tmp_path / "work"
    publication = tmp_path / "curated"
    evidence = tmp_path / "evidence"
    snapshot = "1" * 64
    _write_json(
        work / "gate-a.json",
        {
            "sourceSnapshotId": snapshot,
            "status": "pass",
            "semanticFingerprint": "a" * 64,
        },
    )
    _write_json(
        work / "gate-b.json",
        {
            "sourceSnapshotId": snapshot,
            "status": "pass",
            "semanticFingerprint": "b" * 64,
            "capabilityMask": {
                "competitor_intelligence": {
                    "available": True,
                    "reasonCodes": [],
                }
            },
        },
    )
    _write_json(
        publication / "publication-manifest.json",
        {
            "sourceSnapshotId": snapshot,
            "semanticFingerprint": "c" * 64,
        },
    )
    (publication / "retail_v2.duckdb").write_bytes(b"fixture")
    (work / "staging.duckdb").write_bytes(b"disposable")
    write_operational_readiness_sidecar(
        gate_a_path=work / "gate-a.json",
        gate_b_path=work / "gate-b.json",
        publication_manifest_path=publication / "publication-manifest.json",
        destination=work / "operational-readiness.json",
        producer_registry_path=PRODUCER_REGISTRY,
        schema_path=READINESS_SCHEMA,
    )
    write_readiness_retention(
        readiness_path=work / "operational-readiness.json",
        destination=work / "operational-readiness-retention.json",
        schema_path=READINESS_RETENTION_SCHEMA,
        readiness_schema_path=READINESS_SCHEMA,
    )
    return work, publication, evidence, snapshot


def test_finalize_retains_evidence_then_prunes_work(tmp_path: Path) -> None:
    work, publication, evidence, snapshot = _publication_fixture(tmp_path)

    result = finalize_publication(
        work,
        publication,
        evidence,
        prune_work=True,
    )

    assert result.work_pruned is True
    assert not work.exists()
    assert (evidence / "gate-a.json").is_file()
    assert (evidence / "gate-b.json").is_file()
    assert (evidence / "publication-manifest.json").is_file()
    assert (evidence / "operational-readiness.json").is_file()
    assert (evidence / "operational-readiness-retention.json").is_file()
    retained = json.loads(
        (evidence / "retention-manifest.json").read_text(encoding="utf-8")
    )
    assert retained["sourceSnapshotId"] == snapshot
    assert publication.is_dir()


def test_finalize_refuses_tampered_readiness_before_pruning(tmp_path: Path) -> None:
    work, publication, evidence, _ = _publication_fixture(tmp_path)
    readiness = work / "operational-readiness.json"
    readiness.write_bytes(readiness.read_bytes() + b" ")

    with pytest.raises(RetentionError, match="retention is invalid"):
        finalize_publication(
            work,
            publication,
            evidence,
            prune_work=True,
        )

    assert work.is_dir()
    assert not evidence.exists()


def test_finalize_rejects_overlapping_roots(tmp_path: Path) -> None:
    with pytest.raises(RetentionError, match="must be disjoint"):
        finalize_publication(
            tmp_path / "work",
            tmp_path / "work" / "curated",
            tmp_path / "evidence",
        )
