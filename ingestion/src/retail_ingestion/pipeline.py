"""End-to-end Phase 2 ingestion orchestration with resumable stage evidence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from retail_contracts.fingerprint import semantic_fingerprint

from .publication import publish_candidate
from .quality import run_gate_a, run_gate_b
from .staging import build_staging
from .transforms import build_canonical_candidate


class PipelineError(RuntimeError):
    """The Phase 2 pipeline cannot proceed to the next governed boundary."""


@dataclass(frozen=True)
class PipelineResult:
    source_snapshot_id: str
    work_root: Path
    publication_root: Path
    pipeline_status: str
    gate_a_status: str
    gate_b_status: str
    semantic_fingerprint: str
    resumed_stages: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": "retail-ingestion-pipeline/v1",
            "sourceSnapshotId": self.source_snapshot_id,
            "workRoot": str(self.work_root),
            "publicationRoot": str(self.publication_root),
            "pipelineStatus": self.pipeline_status,
            "gateAStatus": self.gate_a_status,
            "gateBStatus": self.gate_b_status,
            "semanticFingerprint": self.semantic_fingerprint,
            "resumedStages": list(self.resumed_stages),
        }


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _matching(path: Path, source_snapshot_id: str) -> bool:
    if not path.is_file():
        return False
    try:
        return _json(path).get("sourceSnapshotId") == source_snapshot_id
    except (OSError, json.JSONDecodeError):
        return False


_FULL_PUBLICATION_SOURCES = frozenset(
    {"shopify", "businessCentral", "companion"}
)


def _write_validated_partial(
    work: Path,
    gate_a_payload: Mapping[str, Any],
) -> str:
    available = sorted(
        {
            str(row["sourceSystem"])
            for row in gate_a_payload.get("datasetInventory", [])
            if row.get("sourceSystem") != "generator"
        }
    )
    missing = sorted(_FULL_PUBLICATION_SOURCES - set(available))
    payload: dict[str, Any] = {
        "schemaVersion": "retail-ingestion-validated-partial/v1",
        "status": "validated_partial",
        "sourceSnapshotId": gate_a_payload["sourceSnapshotId"],
        "gateASemanticFingerprint": gate_a_payload["semanticFingerprint"],
        "availableSourceSystems": available,
        "missingSourceSystems": missing,
        "publicationBlocked": True,
        "reasonCode": "COMPOSITE_SOURCE_COVERAGE_INCOMPLETE",
    }
    payload["semanticFingerprint"] = semantic_fingerprint(payload)
    destination = work / "validated-partial.json"
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)
    return str(payload["semanticFingerprint"])


def run_pipeline(
    snapshot_root: str | Path,
    source_profile: str | Path,
    work_root: str | Path,
    publication_root: str | Path,
    *,
    execution_profile: Mapping[str, Any],
    rebuild: bool = False,
) -> PipelineResult:
    snapshot = Path(snapshot_root).expanduser().resolve()
    work = Path(work_root).expanduser().resolve()
    publication = Path(publication_root).expanduser().resolve()
    landing = _json(snapshot / "landing-manifest.json")
    source_snapshot_id = str(landing["sourceSnapshotId"])
    work.mkdir(parents=True, exist_ok=True)
    gate_a_path = work / "gate-a.json"
    staging_path = work / "staging.duckdb"
    staging_manifest = staging_path.with_suffix(staging_path.suffix + ".manifest.json")
    candidate_path = work / "retail_v2-candidate.duckdb"
    candidate_manifest = candidate_path.with_suffix(
        candidate_path.suffix + ".manifest.json"
    )
    gate_b_path = work / "gate-b.json"
    resumed: list[str] = []

    if not rebuild and _matching(gate_a_path, source_snapshot_id):
        gate_a_payload = _json(gate_a_path)
        resumed.append("gate-a")
    else:
        gate_a = run_gate_a(
            snapshot,
            source_profile,
            verify_content=True,
            scan_data=True,
            duckdb_threads=int(execution_profile["duckdbThreads"]),
            memory_limit_gb=int(execution_profile["memoryLimitGb"]),
            execution_profile=execution_profile,
        )
        gate_a_payload = gate_a.as_dict()
        gate_a_path.write_text(
            json.dumps(gate_a_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if gate_a_payload["status"] != "pass":
        raise PipelineError("Gate A is critical; staging is blocked")

    available_sources = {
        str(row["sourceSystem"])
        for row in gate_a_payload.get("datasetInventory", [])
        if row.get("sourceSystem") != "generator"
    }
    if not _FULL_PUBLICATION_SOURCES.issubset(available_sources):
        partial_fingerprint = _write_validated_partial(work, gate_a_payload)
        return PipelineResult(
            source_snapshot_id=source_snapshot_id,
            work_root=work,
            publication_root=publication,
            pipeline_status="validated_partial",
            gate_a_status=gate_a_payload["status"],
            gate_b_status="not_run",
            semantic_fingerprint=partial_fingerprint,
            resumed_stages=tuple(resumed),
        )

    if (
        not rebuild
        and staging_path.is_file()
        and _matching(staging_manifest, source_snapshot_id)
    ):
        resumed.append("stage")
    else:
        build_staging(
            snapshot,
            source_profile,
            staging_path,
            execution_profile=execution_profile,
        )

    if (
        not rebuild
        and candidate_path.is_file()
        and _matching(candidate_manifest, source_snapshot_id)
    ):
        resumed.append("transform")
    else:
        build_canonical_candidate(
            staging_path,
            candidate_path,
            execution_profile=execution_profile,
        )

    if not rebuild and _matching(gate_b_path, source_snapshot_id):
        gate_b_payload = _json(gate_b_path)
        resumed.append("gate-b")
    else:
        gate_b = run_gate_b(
            candidate_path,
            staging_path,
            execution_profile=execution_profile,
        )
        gate_b_payload = gate_b.as_dict()
        gate_b_path.write_text(
            json.dumps(gate_b_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    if gate_b_payload["status"] != "pass":
        raise PipelineError("Gate B is critical; curated publication is blocked")

    publication_manifest = publication / "publication-manifest.json"
    if not rebuild and _matching(publication_manifest, source_snapshot_id):
        publication_payload = _json(publication_manifest)
        resumed.append("publish")
        publication_fingerprint = publication_payload["semanticFingerprint"]
    else:
        if publication.exists():
            raise PipelineError(
                "a different immutable publication already occupies the target"
            )
        result = publish_candidate(
            candidate_path,
            gate_b_path,
            publication,
            execution_profile=execution_profile,
        )
        publication_fingerprint = result.semantic_fingerprint

    return PipelineResult(
        source_snapshot_id=source_snapshot_id,
        work_root=work,
        publication_root=publication,
        pipeline_status="published",
        gate_a_status=gate_a_payload["status"],
        gate_b_status=gate_b_payload["status"],
        semantic_fingerprint=publication_fingerprint,
        resumed_stages=tuple(resumed),
    )


__all__ = ["PipelineError", "PipelineResult", "run_pipeline"]
