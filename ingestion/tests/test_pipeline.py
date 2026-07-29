"""Governed terminal states for complete and partial source composites."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ingestion import pipeline


def test_shopify_only_stops_as_validated_partial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    snapshot_id = "snapshot-shopify-only"
    (snapshot / "landing-manifest.json").write_text(
        json.dumps({"sourceSnapshotId": snapshot_id}),
        encoding="utf-8",
    )
    gate_payload = {
        "schemaVersion": "retail-ingestion-gate-a/v1",
        "status": "pass",
        "sourceSnapshotId": snapshot_id,
        "datasetInventory": [
            {
                "sourceSystem": "shopify",
                "dataset": "orders",
                "logicalPath": "shopify/store/orders",
            }
        ],
    }
    gate_payload["semanticFingerprint"] = semantic_fingerprint(gate_payload)
    monkeypatch.setattr(
        pipeline,
        "run_gate_a",
        lambda *args, **kwargs: SimpleNamespace(
            status="pass",
            as_dict=lambda: gate_payload,
        ),
    )

    def must_not_run(*args, **kwargs):
        raise AssertionError("partial source coverage must not enter staging")

    monkeypatch.setattr(pipeline, "build_staging", must_not_run)
    work = tmp_path / "work"
    publication = tmp_path / "curated"
    result = pipeline.run_pipeline(
        snapshot,
        tmp_path / "shopify-profile.yaml",
        work,
        publication,
        execution_profile={"duckdbThreads": 1, "memoryLimitGb": 1},
    )

    assert result.pipeline_status == "validated_partial"
    assert result.gate_b_status == "not_run"
    assert not publication.exists()
    evidence = json.loads(
        (work / "validated-partial.json").read_text(encoding="utf-8")
    )
    assert evidence["availableSourceSystems"] == ["shopify"]
    assert evidence["missingSourceSystems"] == ["businessCentral", "companion"]
    assert evidence["publicationBlocked"] is True
