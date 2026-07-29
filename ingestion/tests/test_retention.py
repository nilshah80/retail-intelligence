"""Accepted evidence survives after disposable work is pruned."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from retail_ingestion.retention import RetentionError, finalize_publication


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_finalize_retains_evidence_then_prunes_work(tmp_path: Path) -> None:
    work = tmp_path / "work"
    publication = tmp_path / "curated"
    evidence = tmp_path / "evidence"
    snapshot = "snapshot-1"
    _write_json(
        work / "gate-a.json",
        {"sourceSnapshotId": snapshot, "status": "pass"},
    )
    _write_json(
        work / "gate-b.json",
        {"sourceSnapshotId": snapshot, "status": "pass"},
    )
    _write_json(
        publication / "publication-manifest.json",
        {
            "sourceSnapshotId": snapshot,
            "semanticFingerprint": "published-fingerprint",
        },
    )
    (publication / "retail_v2.duckdb").write_bytes(b"fixture")
    (work / "staging.duckdb").write_bytes(b"disposable")

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
    retained = json.loads(
        (evidence / "retention-manifest.json").read_text(encoding="utf-8")
    )
    assert retained["sourceSnapshotId"] == snapshot
    assert publication.is_dir()


def test_finalize_rejects_overlapping_roots(tmp_path: Path) -> None:
    with pytest.raises(RetentionError, match="must be disjoint"):
        finalize_publication(
            tmp_path / "work",
            tmp_path / "work" / "curated",
            tmp_path / "evidence",
        )
