from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.io.bundle import (
    GATE_VOLATILE_POINTERS,
    PUBLICATION_VOLATILE_POINTERS,
    BundleVerificationError,
    discover_input_bundle,
)
from retail_ml.io.curated import CuratedReader


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _fingerprint(document: dict[str, Any], volatile: tuple[str, ...]) -> str:
    payload = dict(document)
    payload.pop("semanticFingerprint", None)
    return semantic_fingerprint(payload, volatile_pointers=volatile)


def _fixture_bundle(root: Path) -> dict[str, Any]:
    evidence = root / "ingestion/data/evidence/arbitrary-evidence-name"
    curated = root / "ingestion/data/curated/arbitrary-publication-name"
    object_path = curated / "parquet/sales/data.parquet"
    duckdb_path = curated / "retail_v2.duckdb"
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"parquet-fixture")
    duckdb_path.write_bytes(b"duckdb-fixture")

    snapshot = "a" * 64
    capability = {"demand_forecast_non_pit": {"available": True}}
    gate_a: dict[str, Any] = {
        "schemaVersion": "retail-ingestion-gate-a/v1",
        "sourceSnapshotId": snapshot,
        "status": "pass",
        "executionProfile": {"profile": "safe"},
    }
    gate_b: dict[str, Any] = {
        "schemaVersion": "retail-ingestion-gate-b/v1",
        "sourceSnapshotId": snapshot,
        "status": "pass",
        "capabilityMask": capability,
        "executionProfile": {"profile": "safe"},
    }
    publication: dict[str, Any] = {
        "schemaVersion": "retail-curated-publication/v1",
        "sourceSnapshotId": snapshot,
        "candidateSemanticFingerprint": "b" * 64,
        "capabilityMask": capability,
        "publishedAt": "2026-07-30T00:00:00Z",
        "executionProfile": {"profile": "safe"},
        "objects": [
            {
                "path": "parquet/sales/data.parquet",
                "bytes": object_path.stat().st_size,
                "sha256": _sha256(object_path),
            }
        ],
        "duckdb": {
            "path": "retail_v2.duckdb",
            "bytes": duckdb_path.stat().st_size,
            "sha256": _sha256(duckdb_path),
        },
    }

    state = {
        "root": root,
        "evidence": evidence,
        "curated": curated,
        "object_path": object_path,
        "duckdb_path": duckdb_path,
        "gate_a": gate_a,
        "gate_b": gate_b,
        "publication": publication,
        "pin_path": root / "contracts/ml/expected-pin.json",
    }
    _refresh_bundle(state, update_pin=True)
    return state


def _refresh_bundle(state: dict[str, Any], *, update_pin: bool) -> None:
    gate_a = state["gate_a"]
    gate_b = state["gate_b"]
    publication = state["publication"]
    evidence: Path = state["evidence"]
    curated: Path = state["curated"]

    gate_a["semanticFingerprint"] = _fingerprint(gate_a, GATE_VOLATILE_POINTERS)
    gate_b["semanticFingerprint"] = _fingerprint(gate_b, GATE_VOLATILE_POINTERS)
    publication["gateBSemanticFingerprint"] = gate_b["semanticFingerprint"]
    publication["semanticFingerprint"] = _fingerprint(
        publication,
        PUBLICATION_VOLATILE_POINTERS,
    )
    _write_json(evidence / "gate-a.json", gate_a)
    _write_json(evidence / "gate-b.json", gate_b)
    _write_json(evidence / "publication-manifest.json", publication)
    _write_json(curated / "publication-manifest.json", publication)

    hashes = {
        name: _sha256(evidence / name)
        for name in ("gate-a.json", "gate-b.json", "publication-manifest.json")
    }
    retention = {
        "schemaVersion": "retail-ingestion-retained-evidence/v1",
        "sourceSnapshotId": publication["sourceSnapshotId"],
        "publicationFingerprint": publication["semanticFingerprint"],
        "files": hashes,
    }
    _write_json(evidence / "retention-manifest.json", retention)
    if not update_pin:
        return
    pin = {
        "$schema": "./input-bundle.schema.json",
        "schemaVersion": "retail-ml-expected-pin/v1",
        "sourceSnapshotId": publication["sourceSnapshotId"],
        "gateA": {
            "status": "pass",
            "semanticFingerprint": gate_a["semanticFingerprint"],
            "evidenceSha256": hashes["gate-a.json"],
        },
        "gateB": {
            "status": "pass",
            "semanticFingerprint": gate_b["semanticFingerprint"],
            "evidenceSha256": hashes["gate-b.json"],
        },
        "publication": {
            "semanticFingerprint": publication["semanticFingerprint"],
            "gateBSemanticFingerprint": publication["gateBSemanticFingerprint"],
            "evidenceSha256": hashes["publication-manifest.json"],
            "objectCount": len(publication["objects"]),
            "duckdb": publication["duckdb"],
        },
        "retention": {
            "schemaVersion": retention["schemaVersion"],
            "publicationFingerprint": retention["publicationFingerprint"],
            "files": hashes,
        },
        "requiredCapabilities": ["demand_forecast_non_pit"],
    }
    _write_json(state["pin_path"], pin)


def test_verified_bundle_releases_curated_reader(tmp_path: Path) -> None:
    state = _fixture_bundle(tmp_path)
    selected = discover_input_bundle(tmp_path, expected_pin_path=state["pin_path"])
    verified = selected.verify()
    reader = CuratedReader(verified)

    assert verified.identity["sourceSnapshotId"] == "a" * 64
    assert reader.entity_parquet_path("sales") == state["object_path"]


def test_curated_reader_rejects_unverified_bundle(tmp_path: Path) -> None:
    state = _fixture_bundle(tmp_path)
    selected = discover_input_bundle(tmp_path, expected_pin_path=state["pin_path"])

    with pytest.raises(BundleVerificationError, match="before InputBundle.verify"):
        CuratedReader(selected)  # type: ignore[arg-type]


def test_tampered_evidence_file_is_rejected(tmp_path: Path) -> None:
    state = _fixture_bundle(tmp_path)
    with (state["evidence"] / "gate-a.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")

    with pytest.raises(BundleVerificationError, match="evidence file hash"):
        discover_input_bundle(
            tmp_path,
            expected_pin_path=state["pin_path"],
        ).verify()


def test_mutated_publication_object_is_rejected(tmp_path: Path) -> None:
    state = _fixture_bundle(tmp_path)
    state["object_path"].write_bytes(b"parquet-Fixture")

    with pytest.raises(BundleVerificationError, match="SHA-256 mismatch"):
        discover_input_bundle(
            tmp_path,
            expected_pin_path=state["pin_path"],
        ).verify()


def test_mismatched_capability_masks_are_rejected_even_when_repinned(
    tmp_path: Path,
) -> None:
    state = _fixture_bundle(tmp_path)
    state["gate_b"]["capabilityMask"] = {
        "demand_forecast_non_pit": {"available": True},
        "extra": {"available": True},
    }
    _refresh_bundle(state, update_pin=True)

    with pytest.raises(BundleVerificationError, match="capability masks differ"):
        discover_input_bundle(
            tmp_path,
            expected_pin_path=state["pin_path"],
        ).verify()


def test_publication_moved_from_committed_pin_is_rejected(tmp_path: Path) -> None:
    state = _fixture_bundle(tmp_path)
    state["publication"]["candidateSemanticFingerprint"] = "c" * 64
    _refresh_bundle(state, update_pin=False)

    with pytest.raises(
        BundleVerificationError,
        match="matches the committed expected pin|publication moved",
    ):
        discover_input_bundle(
            tmp_path,
            expected_pin_path=state["pin_path"],
        ).verify()
