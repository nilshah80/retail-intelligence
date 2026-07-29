"""Disposable full-history benchmark for the governed Phase 2 pipeline."""

from __future__ import annotations

import json
import tempfile
import time
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

from retail_contracts.fingerprint import semantic_fingerprint

from .publication import publish_candidate
from .quality import run_gate_a, run_gate_b
from .staging import build_staging
from .transforms import build_canonical_candidate


def _measure(function: Callable[[], Any]) -> tuple[Any, str]:
    started = time.perf_counter()
    result = function()
    return result, format(time.perf_counter() - started, ".6f")


def run_full_benchmark(
    snapshot_root: str | Path,
    source_profile: str | Path,
    report_path: str | Path,
    *,
    execution_profile: Mapping[str, Any],
    temp_root: str | Path | None = None,
    work_root: str | Path | None = None,
    publication_root: str | Path | None = None,
) -> dict[str, Any]:
    """Run every governed stage in disposable same-volume working storage."""

    parent = (
        Path(temp_root).expanduser().resolve()
        if temp_root is not None
        else Path(report_path).expanduser().resolve().parent
    )
    parent.mkdir(parents=True, exist_ok=True)
    if (work_root is None) != (publication_root is None):
        raise ValueError("work_root and publication_root must be supplied together")
    if work_root is None:
        workspace = tempfile.TemporaryDirectory(
            prefix="retail-ingestion-benchmark-", dir=parent
        )
    else:
        retained = Path(work_root).expanduser().resolve()
        retained.mkdir(parents=True, exist_ok=False)
        workspace = nullcontext(str(retained))
    with workspace as temporary_name:
        temporary = Path(temporary_name)
        staging = temporary / "staging.duckdb"
        candidate = temporary / "retail_v2-candidate.duckdb"
        gate_a_path = temporary / "gate-a.json"
        gate_b_path = temporary / "gate-b.json"
        curated = (
            Path(publication_root).expanduser().resolve()
            if publication_root is not None
            else temporary / "curated"
        )

        gate_a, gate_a_seconds = _measure(
            lambda: run_gate_a(
                snapshot_root,
                source_profile,
                duckdb_threads=int(execution_profile["duckdbThreads"]),
                memory_limit_gb=int(execution_profile["memoryLimitGb"]),
                execution_profile=execution_profile,
            )
        )
        if gate_a.status != "pass":
            raise RuntimeError("benchmark Gate A is critical")
        gate_a_path.write_text(
            json.dumps(gate_a.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        stage, stage_seconds = _measure(
            lambda: build_staging(
                snapshot_root,
                source_profile,
                staging,
                execution_profile=execution_profile,
            )
        )
        transform, transform_seconds = _measure(
            lambda: build_canonical_candidate(
                staging,
                candidate,
                execution_profile=execution_profile,
            )
        )
        gate_b, gate_b_seconds = _measure(
            lambda: run_gate_b(
                candidate,
                staging,
                execution_profile=execution_profile,
            )
        )
        if gate_b.status != "pass":
            raise RuntimeError("benchmark Gate B is critical")
        gate_b_path.write_text(
            json.dumps(gate_b.as_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        publication, publish_seconds = _measure(
            lambda: publish_candidate(
                candidate,
                gate_b_path,
                curated,
                execution_profile=execution_profile,
            )
        )
        payload: dict[str, Any] = {
            "schemaVersion": "retail-ingestion-benchmark/v1",
            "mode": "full_history",
            "artifactsRetained": work_root is not None,
            "sourceSnapshotId": gate_a.source_snapshot_id,
            "executionProfile": dict(execution_profile),
            "stages": {
                "gateA": {
                    "wallSeconds": gate_a_seconds,
                    "inputRows": sum(
                        int(row.get("scannedRows", 0))
                        for row in gate_a.dataset_inventory
                    ),
                    "semanticFingerprint": gate_a.as_dict()[
                        "semanticFingerprint"
                    ],
                },
                "staging": {
                    "wallSeconds": stage_seconds,
                    "outputBytes": staging.stat().st_size,
                    "semanticFingerprint": stage.semantic_fingerprint,
                },
                "transform": {
                    "wallSeconds": transform_seconds,
                    "outputBytes": candidate.stat().st_size,
                    "semanticFingerprint": transform.semantic_fingerprint,
                },
                "gateB": {
                    "wallSeconds": gate_b_seconds,
                    "semanticFingerprint": gate_b.as_dict()[
                        "semanticFingerprint"
                    ],
                },
                "publication": {
                    "wallSeconds": publish_seconds,
                    "objectCount": publication.object_count,
                    "outputBytes": sum(
                        path.stat().st_size
                        for path in curated.rglob("*")
                        if path.is_file()
                    ),
                    "semanticFingerprint": publication.semantic_fingerprint,
                },
            },
        }
        payload["totalWallSeconds"] = format(
            sum(
                Decimal(stage["wallSeconds"])
                for stage in payload["stages"].values()
            ),
            ".6f",
        )
        payload["semanticFingerprint"] = semantic_fingerprint(
            payload, volatile_pointers=("/executionProfile",)
        )
    destination = Path(report_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = destination.with_name(f".{destination.name}.tmp")
    temporary_report.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary_report.replace(destination)
    return payload


__all__ = ["run_full_benchmark"]
