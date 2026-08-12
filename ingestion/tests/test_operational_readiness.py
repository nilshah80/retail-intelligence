from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from retail_contracts.fingerprint import semantic_fingerprint

from retail_ingestion.readiness.operational import (
    OperationalReadinessError,
    build_operational_readiness,
    validate_readiness_retention,
    validate_operational_readiness,
    write_readiness_retention,
    write_operational_readiness_sidecar,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "contracts/onboarding/readiness-report-v2.schema.json"
REGISTRY = REPO_ROOT / "contracts/onboarding/readiness-producer-registry.json"
RETENTION_SCHEMA = REPO_ROOT / "contracts/onboarding/readiness-retention.schema.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _retained_run() -> Path:
    pin = json.loads(
        (REPO_ROOT / "contracts/ml/expected-pin.json").read_text(encoding="utf-8")
    )
    for path in sorted((REPO_ROOT / "ingestion/data/evidence").glob("run-*")):
        manifest_path = path / "publication-manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("semanticFingerprint") == pin["publication"][
            "semanticFingerprint"
        ]:
            return path
    raise AssertionError("expected-pin publication evidence is not retained")


def test_sidecar_is_post_publication_one_way_and_schema_valid(tmp_path: Path) -> None:
    evidence = _retained_run()
    upstream = [
        evidence / "gate-a.json",
        evidence / "gate-b.json",
        evidence / "publication-manifest.json",
    ]
    before = {path: _sha(path) for path in upstream}
    destination = tmp_path / "operational-readiness.json"
    report = write_operational_readiness_sidecar(
        gate_a_path=upstream[0],
        gate_b_path=upstream[1],
        publication_manifest_path=upstream[2],
        destination=destination,
        producer_registry_path=REGISTRY,
        schema_path=SCHEMA,
    )

    assert {path: _sha(path) for path in upstream} == before
    validate_operational_readiness(report, schema_path=SCHEMA)
    assert report["capabilities"]["competitor_intelligence"]["readiness"] == "ready"
    assert (
        report["capabilities"]["competitor_intelligence"]["sufficiency"]
        == "not_evaluated"
    )
    forecast = report["capabilities"]["demand_forecast_non_pit"]
    assert forecast["sufficiency"] == "sufficient"
    assert forecast["claimAuthorization"] == "descriptive_only"
    assert forecast["consumerMayProceed"] is False
    assert "source.demand-forecast-non-pit-input" in forecast["producerIds"]
    assert report["capabilities"]["price_revenue"]["consumerMayProceed"] is False

    retention_path = tmp_path / "operational-readiness-retention.json"
    retention = write_readiness_retention(
        readiness_path=destination,
        destination=retention_path,
        schema_path=RETENTION_SCHEMA,
        readiness_schema_path=SCHEMA,
    )
    validate_readiness_retention(
        retention,
        schema_path=RETENTION_SCHEMA,
        readiness_path=destination,
        readiness_schema_path=SCHEMA,
    )
    assert retention["files"]["operational-readiness.json"] == _sha(destination)


def test_readiness_retention_refuses_changed_sidecar_bytes(tmp_path: Path) -> None:
    evidence = _retained_run()
    destination = tmp_path / "operational-readiness.json"
    write_operational_readiness_sidecar(
        gate_a_path=evidence / "gate-a.json",
        gate_b_path=evidence / "gate-b.json",
        publication_manifest_path=evidence / "publication-manifest.json",
        destination=destination,
        producer_registry_path=REGISTRY,
        schema_path=SCHEMA,
    )
    retention_path = tmp_path / "operational-readiness-retention.json"
    write_readiness_retention(
        readiness_path=destination,
        destination=retention_path,
        schema_path=RETENTION_SCHEMA,
        readiness_schema_path=SCHEMA,
    )
    destination.write_bytes(destination.read_bytes() + b" ")
    with pytest.raises(OperationalReadinessError, match="differs"):
        validate_readiness_retention(
            json.loads(retention_path.read_text(encoding="utf-8")),
            schema_path=RETENTION_SCHEMA,
            readiness_path=destination,
            readiness_schema_path=SCHEMA,
        )


def test_execution_time_never_changes_readiness_identity() -> None:
    evidence = _retained_run()
    gate_a = json.loads((evidence / "gate-a.json").read_text(encoding="utf-8"))
    gate_b = json.loads((evidence / "gate-b.json").read_text(encoding="utf-8"))
    manifest_path = evidence / "publication-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    first = build_operational_readiness(
        gate_a=gate_a,
        gate_b=gate_b,
        publication_manifest=manifest,
        publication_manifest_sha256=_sha(manifest_path),
        producer_registry=registry,
        produced_at="2026-08-11T00:00:00Z",
    )
    second = build_operational_readiness(
        gate_a=gate_a,
        gate_b=gate_b,
        publication_manifest=manifest,
        publication_manifest_sha256=_sha(manifest_path),
        producer_registry=registry,
        produced_at="2026-08-11T01:00:00Z",
    )
    assert first["reportFingerprint"] == second["reportFingerprint"]


def test_retained_reports_keep_their_exact_producer_registry() -> None:
    registries = {}
    for path in sorted(
        (REPO_ROOT / "contracts/onboarding").glob(
            "readiness-producer-registry*.json"
        )
    ):
        registry = json.loads(path.read_text(encoding="utf-8"))
        fingerprint = registry["registryFingerprint"]
        assert fingerprint == semantic_fingerprint(
            registry, volatile_pointers=("/registryFingerprint",)
        )
        assert fingerprint not in registries
        registries[fingerprint] = path

    retained = sorted(
        (REPO_ROOT / "ingestion/data/evidence").glob(
            "run-*/operational-readiness.json"
        )
    )
    assert retained
    for path in retained:
        report = json.loads(path.read_text(encoding="utf-8"))
        assert report["producerRegistryFingerprint"] in registries


def test_malformed_or_missing_producers_never_become_ready() -> None:
    evidence = _retained_run()
    gate_a = json.loads((evidence / "gate-a.json").read_text(encoding="utf-8"))
    gate_b = json.loads((evidence / "gate-b.json").read_text(encoding="utf-8"))
    manifest_path = evidence / "publication-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    malformed = copy.deepcopy(gate_b)
    malformed["capabilityMask"]["competitor_intelligence"]["available"] = "true"
    with pytest.raises(OperationalReadinessError, match="strict boolean"):
        build_operational_readiness(
            gate_a=gate_a,
            gate_b=malformed,
            publication_manifest=manifest,
            publication_manifest_sha256=_sha(manifest_path),
            producer_registry=registry,
        )

    report = build_operational_readiness(
        gate_a=gate_a,
        gate_b=gate_b,
        publication_manifest=manifest,
        publication_manifest_sha256=_sha(manifest_path),
        producer_registry=registry,
    )
    assert report["capabilities"]["promotion_response"]["readiness"] == "unavailable"
    assert "MISSING_READINESS_PRODUCER" in report["capabilities"][
        "promotion_response"
    ]["reasonCodes"]


def test_source_input_sufficiency_is_derived_and_fails_closed() -> None:
    evidence = _retained_run()
    gate_a = json.loads((evidence / "gate-a.json").read_text(encoding="utf-8"))
    gate_b = json.loads((evidence / "gate-b.json").read_text(encoding="utf-8"))
    manifest_path = evidence / "publication-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    insufficient = copy.deepcopy(gate_b)
    insufficient["capabilityMask"]["inventory_replenishment_replay"][
        "prematureStatusRows"
    ] = 1
    report = build_operational_readiness(
        gate_a=gate_a,
        gate_b=insufficient,
        publication_manifest=manifest,
        publication_manifest_sha256=_sha(manifest_path),
        producer_registry=registry,
    )
    replay = report["capabilities"]["inventory_replenishment_replay"]
    assert replay["sufficiency"] == "insufficient_evidence"
    assert replay["consumerMayProceed"] is False
    assert replay["reasonCodes"] == [
        "CLIENT_CLAIM_NOT_AUTHORIZED",
        "INVENTORY_REPLAY_SOURCE_INPUT_INSUFFICIENT",
    ]
