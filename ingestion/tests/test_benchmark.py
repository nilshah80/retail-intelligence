"""Benchmark telemetry must not affect its semantic identity."""

from __future__ import annotations

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ingestion.benchmark import _benchmark_semantic_payload


def _payload(profile: str, seconds: str, objects: int) -> dict[str, object]:
    return {
        "schemaVersion": "retail-ingestion-benchmark/v1",
        "mode": "full_history",
        "sourceSnapshotId": "snapshot-1",
        "executionProfile": {"profile": profile},
        "totalWallSeconds": seconds,
        "stages": {
            "gateA": {
                "wallSeconds": seconds,
                "semanticFingerprint": "gate-a",
            },
            "publication": {
                "wallSeconds": seconds,
                "objectCount": objects,
                "outputBytes": objects * 100,
                "semanticFingerprint": "publication",
            },
        },
    }


def test_benchmark_semantic_identity_excludes_runtime_and_layout() -> None:
    safe = _payload("safe", "333.000000", 1952)
    ultra = _payload("ultra-performance", "164.000000", 1444)

    assert semantic_fingerprint(_benchmark_semantic_payload(safe)) == (
        semantic_fingerprint(_benchmark_semantic_payload(ultra))
    )
