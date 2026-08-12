"""Promote small acceptance evidence and prune disposable pipeline work."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .readiness.operational import validate_readiness_retention


class RetentionError(RuntimeError):
    """Accepted evidence cannot be retained or work cannot be pruned safely."""


@dataclass(frozen=True)
class RetentionResult:
    source_snapshot_id: str
    evidence_root: Path
    work_pruned: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "retail-ingestion-retention-result/v1",
            "sourceSnapshotId": self.source_snapshot_id,
            "evidenceRoot": str(self.evidence_root),
            "workPruned": self.work_pruned,
        }


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RetentionError(f"cannot read governed evidence {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RetentionError(f"governed evidence must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _cleanup_readonly(function, path, exc_info) -> None:
    del exc_info
    target = Path(path)
    target.chmod(
        stat.S_IRUSR
        | stat.S_IWUSR
        | (stat.S_IXUSR if target.is_dir() else 0)
    )
    function(path)


def _assert_disjoint(*roots: Path) -> None:
    for index, left in enumerate(roots):
        for right in roots[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise RetentionError(
                    f"retention roots must be disjoint: {left} and {right}"
                )


def finalize_publication(
    work_root: str | Path,
    publication_root: str | Path,
    evidence_root: str | Path,
    *,
    prune_work: bool = False,
) -> RetentionResult:
    """Retain governed evidence atomically, then optionally prune rebuildable work."""

    work = Path(work_root).expanduser().resolve()
    publication = Path(publication_root).expanduser().resolve()
    evidence = Path(evidence_root).expanduser().resolve()
    _assert_disjoint(work, publication, evidence)
    gate_a_path = work / "gate-a.json"
    gate_b_path = work / "gate-b.json"
    readiness_path = work / "operational-readiness.json"
    readiness_retention_path = work / "operational-readiness-retention.json"
    publication_path = publication / "publication-manifest.json"
    curated_database = publication / "retail_v2.duckdb"
    gate_a = _load(gate_a_path)
    gate_b = _load(gate_b_path)
    published = _load(publication_path)
    snapshot_ids = {
        str(gate_a.get("sourceSnapshotId")),
        str(gate_b.get("sourceSnapshotId")),
        str(published.get("sourceSnapshotId")),
    }
    if len(snapshot_ids) != 1 or "None" in snapshot_ids:
        raise RetentionError("Gate A, Gate B and publication snapshot IDs differ")
    if gate_a.get("status") != "pass" or gate_b.get("status") != "pass":
        raise RetentionError("only Gate-A/Gate-B-approved work may be finalized")
    if not curated_database.is_file():
        raise RetentionError("curated retail_v2.duckdb is missing")

    readiness_files = (readiness_path, readiness_retention_path)
    readiness_presence = tuple(path.is_file() for path in readiness_files)
    if any(readiness_presence) and not all(readiness_presence):
        raise RetentionError(
            "operational readiness and its retention record must be finalized together"
        )
    retain_readiness = all(readiness_presence)
    if retain_readiness:
        repository_root = Path(__file__).resolve().parents[3]
        try:
            validate_readiness_retention(
                _load(readiness_retention_path),
                schema_path=(
                    repository_root
                    / "contracts/onboarding/readiness-retention.schema.json"
                ),
                readiness_path=readiness_path,
                readiness_schema_path=(
                    repository_root
                    / "contracts/onboarding/readiness-report-v2.schema.json"
                ),
            )
        except Exception as exc:
            raise RetentionError(f"operational readiness retention is invalid: {exc}") from exc
        readiness = _load(readiness_path)
        if readiness.get("sourceSnapshotId") != published.get("sourceSnapshotId"):
            raise RetentionError(
                "operational readiness and publication snapshot IDs differ"
            )
        if (
            readiness.get("publicationSemanticFingerprint")
            != published.get("semanticFingerprint")
        ):
            raise RetentionError(
                "operational readiness and publication fingerprints differ"
            )

    snapshot_id = snapshot_ids.pop()
    payload = {
        "schemaVersion": "retail-ingestion-retained-evidence/v1",
        "sourceSnapshotId": snapshot_id,
        "publicationFingerprint": published.get("semanticFingerprint"),
        "files": {
            "gate-a.json": _sha256(gate_a_path),
            "gate-b.json": _sha256(gate_b_path),
            "publication-manifest.json": _sha256(publication_path),
        },
    }
    if evidence.exists():
        existing = _load(evidence / "retention-manifest.json")
        if existing != payload:
            raise RetentionError(
                "a different retained-evidence set already occupies the target"
            )
        retained_readiness = evidence / "operational-readiness.json"
        retained_readiness_retention = (
            evidence / "operational-readiness-retention.json"
        )
        retained_presence = (
            retained_readiness.is_file(),
            retained_readiness_retention.is_file(),
        )
        if any(retained_presence) and not all(retained_presence):
            raise RetentionError(
                "retained operational readiness evidence is incomplete"
            )
        if retain_readiness:
            if not all(retained_presence):
                raise RetentionError(
                    "the existing evidence target lacks the operational readiness pair"
                )
            if any(
                _sha256(source) != _sha256(retained)
                for source, retained in zip(
                    readiness_files,
                    (retained_readiness, retained_readiness_retention),
                    strict=True,
                )
            ):
                raise RetentionError(
                    "a different operational readiness pair occupies the target"
                )
    else:
        evidence.parent.mkdir(parents=True, exist_ok=True)
        temporary = evidence.with_name(
            f".{evidence.name}.retention-{uuid.uuid4().hex}"
        )
        temporary.mkdir()
        try:
            shutil.copy2(gate_a_path, temporary / "gate-a.json")
            shutil.copy2(gate_b_path, temporary / "gate-b.json")
            shutil.copy2(
                publication_path,
                temporary / "publication-manifest.json",
            )
            if retain_readiness:
                shutil.copy2(
                    readiness_path,
                    temporary / "operational-readiness.json",
                )
                shutil.copy2(
                    readiness_retention_path,
                    temporary / "operational-readiness-retention.json",
                )
            (temporary / "retention-manifest.json").write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            os.replace(temporary, evidence)
        except Exception:
            if temporary.exists():
                shutil.rmtree(temporary, onexc=_cleanup_readonly)
            raise

    if prune_work and work.exists():
        shutil.rmtree(work, onexc=_cleanup_readonly)
    return RetentionResult(
        source_snapshot_id=snapshot_id,
        evidence_root=evidence,
        work_pruned=prune_work,
    )


__all__ = [
    "RetentionError",
    "RetentionResult",
    "finalize_publication",
]
