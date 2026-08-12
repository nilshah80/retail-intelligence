from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

from retail_contracts.fingerprint import semantic_fingerprint


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    run = "run-source"
    evidence = tmp_path / "ingestion/data/evidence" / run
    publication = tmp_path / "ingestion/data/curated" / run
    publication.mkdir(parents=True)
    database = publication / "retail_v2.duckdb"
    database.write_bytes(b"duckdb")
    snapshot = "1" * 64
    gate_a = {
        "status": "pass",
        "sourceSnapshotId": snapshot,
        "semanticFingerprint": "2" * 64,
    }
    gate_b = {
        "status": "pass",
        "sourceSnapshotId": snapshot,
        "semanticFingerprint": "3" * 64,
    }
    manifest = {
        "sourceSnapshotId": snapshot,
        "semanticFingerprint": "4" * 64,
        "gateBSemanticFingerprint": "3" * 64,
        "objects": [{"logicalPath": "one.parquet"}],
        "duckdb": {
            "path": "retail_v2.duckdb",
            "sha256": hashlib.sha256(b"duckdb").hexdigest(),
        },
    }
    _write(evidence / "gate-a.json", gate_a)
    _write(evidence / "gate-b.json", gate_b)
    _write(evidence / "publication-manifest.json", manifest)
    manifest_hash = hashlib.sha256(
        (evidence / "publication-manifest.json").read_bytes()
    ).hexdigest()
    readiness = {
        "schemaVersion": "retail-operational-readiness/v2",
        "semanticIdentityExcludes": ["/producedAt", "/reportFingerprint"],
        "reportFingerprint": "5" * 64,
        "sourceSnapshotId": snapshot,
        "gateASemanticFingerprint": "2" * 64,
        "gateBSemanticFingerprint": "3" * 64,
        "publicationSemanticFingerprint": "4" * 64,
        "publicationManifestSha256": manifest_hash,
        "producerRegistryFingerprint": "6" * 64,
        "capabilities": {
            "demand_forecast_non_pit": {
                "readiness": "ready",
                "sufficiency": "sufficient",
                "claimAuthorization": "descriptive_only",
                "consumerMayProceed": False,
                "producerIds": [
                    "gate-b.capability-mask",
                    "source.demand-forecast-non-pit-input",
                ],
                "reasonCodes": ["CLIENT_CLAIM_NOT_AUTHORIZED"],
            }
        },
        "summary": {
            "ready": ["demand_forecast_non_pit"],
            "validatedPartial": [],
            "unavailable": [],
            "blocked": [],
        },
        "producedAt": "2026-08-12T00:00:00Z",
    }
    readiness["reportFingerprint"] = semantic_fingerprint(
        readiness, volatile_pointers=("/producedAt", "/reportFingerprint")
    )
    _write(evidence / "operational-readiness.json", readiness)
    return evidence, publication


def test_builds_schema_valid_genesis_chain_with_stable_selection_id(
    tmp_path: Path, monkeypatch
) -> None:
    import build_publication_authority as builder

    evidence, publication = _fixture(tmp_path)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    monkeypatch.setattr(builder, "REPOSITORY_ROOT", tmp_path)
    records = builder.build_source_chains(
        run_id="run-source",
        retailer_id="retailer-demo",
        tenant_id="tenant-demo",
        environment="dev",
        capabilities=["demand_forecast_non_pit"],
        predecessors={"demand_forecast_non_pit": None},
        evidence_root=evidence,
        publication_root=publication,
        ledger=ledger,
        actor="reviewer",
        recorded_at="2026-08-12T00:00:00Z",
        reason="verified diagnostic publication",
        schema_path=REPO_ROOT / "contracts/onboarding/publication-selection-v2.schema.json",
    )

    assert [record["lifecycle"]["state"] for record in records] == [
        "candidate",
        "approved",
        "active",
    ]
    assert len({record["selectionId"] for record in records}) == 1
    assert records[0]["lifecycle"]["supersedes"] is None
    assert records[1]["lifecycle"]["supersedes"] == records[0]["lifecycle"][
        "recordId"
    ]
    assert records[-1]["readiness"]["claimAuthorization"] == "descriptive_only"


def test_refuses_source_without_producer_backed_input_sufficiency(
    tmp_path: Path, monkeypatch
) -> None:
    import build_publication_authority as builder

    evidence, publication = _fixture(tmp_path)
    readiness_path = evidence / "operational-readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    row = readiness["capabilities"]["demand_forecast_non_pit"]
    row["sufficiency"] = "not_evaluated"
    row["reasonCodes"].append("DEMAND_FORECAST_SOURCE_INPUT_NOT_EVALUATED")
    readiness["reportFingerprint"] = semantic_fingerprint(
        readiness, volatile_pointers=("/producedAt", "/reportFingerprint")
    )
    _write(readiness_path, readiness)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    monkeypatch.setattr(builder, "REPOSITORY_ROOT", tmp_path)

    try:
        builder.build_source_chains(
            run_id="run-source",
            retailer_id="retailer-demo",
            tenant_id="tenant-demo",
            environment="dev",
            capabilities=["demand_forecast_non_pit"],
            predecessors={"demand_forecast_non_pit": None},
            evidence_root=evidence,
            publication_root=publication,
            ledger=ledger,
            actor="reviewer",
            recorded_at="2026-08-12T00:00:00Z",
            reason="must refuse insufficient source input",
            schema_path=REPO_ROOT
            / "contracts/onboarding/publication-selection-v2.schema.json",
        )
    except builder.PublicationAuthorityError as exc:
        assert "cannot be selected" in str(exc)
    else:
        raise AssertionError("source without producer-backed sufficiency was accepted")


def test_refuses_genesis_when_exact_scope_history_exists(
    tmp_path: Path, monkeypatch
) -> None:
    import build_publication_authority as builder

    evidence, publication = _fixture(tmp_path)
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    monkeypatch.setattr(builder, "REPOSITORY_ROOT", tmp_path)
    records = builder.build_source_chains(
        run_id="run-source",
        retailer_id="retailer-demo",
        tenant_id="tenant-demo",
        environment="dev",
        capabilities=["demand_forecast_non_pit"],
        predecessors={"demand_forecast_non_pit": None},
        evidence_root=evidence,
        publication_root=publication,
        ledger=ledger,
        actor="reviewer",
        recorded_at="2026-08-12T00:00:00Z",
        reason="verified diagnostic publication",
        schema_path=REPO_ROOT / "contracts/onboarding/publication-selection-v2.schema.json",
    )
    builder.write_chains(records, ledger=ledger)

    try:
        builder.build_source_chains(
            run_id="run-source",
            retailer_id="retailer-demo",
            tenant_id="tenant-demo",
            environment="dev",
            capabilities=["demand_forecast_non_pit"],
            predecessors={"demand_forecast_non_pit": None},
            evidence_root=evidence,
            publication_root=publication,
            ledger=ledger,
            actor="reviewer",
            recorded_at="2026-08-12T00:00:00Z",
            reason="invalid second genesis",
            schema_path=REPO_ROOT / "contracts/onboarding/publication-selection-v2.schema.json",
        )
    except builder.PublicationAuthorityError as exc:
        assert "declares genesis" in str(exc)
    else:
        raise AssertionError("second genesis was accepted")
