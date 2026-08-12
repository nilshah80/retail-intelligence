import json
from pathlib import Path

import pytest

from retail_ml.pricing.selection import (
    PricingSelectionError,
    build_activation_set,
    build_selection_intent,
    build_selection_record,
    validate_activation_set,
    validate_selection_record,
)


ROOT = Path(__file__).resolve().parents[2]


def _evidence(**overrides):
    evidence = {
        "sourcePublicationFingerprint": "1" * 64,
        "readinessReportFingerprint": "2" * 64,
        "inputAuthorityId": "auth_0123456789abcdef",
        "responsePolicySha256": "3" * 64,
        "pricingPolicySha256": "4" * 64,
        "artifactContractSha256": "5" * 64,
        "responseAssessmentsFingerprint": "6" * 64,
        "recommendationsFingerprint": "7" * 64,
        "priceRevenueCapabilityFingerprint": "8" * 64,
    }
    evidence.update(overrides)
    return evidence


def _selection(
    state: str,
    predecessor: str | None = None,
    *,
    bundle_id: str = "pb_0123456789abcdef0123",
    actor: str = "local-reviewer",
):
    return build_selection_record(
        retailer_id="gulf-oil",
        tenant_id="india-demo",
        environment="local",
        audience="response_rich_local",
        evidence=_evidence(),
        state=state,
        bundle_id=bundle_id,
        bundle_semantic_fingerprint="a" * 64,
        predecessor_record_id=predecessor,
        actor=actor,
        reason="Reviewed local pricing evidence.",
        recorded_at="2026-08-11T12:00:00Z",
    )


def test_selection_lifecycle_shares_scope_identity_but_not_record_identity() -> None:
    candidate = _selection("candidate")
    approved = _selection("approved", candidate["recordId"])
    assert candidate["selectionId"] == approved["selectionId"]
    assert candidate["recordId"] != approved["recordId"]
    validate_selection_record(
        candidate, ROOT / "contracts/pricing/result-selection.schema.json"
    )


def test_selection_intent_prebinds_semantic_evidence() -> None:
    first = build_selection_intent(
        retailer_id="gulf-oil",
        tenant_id="india-demo",
        environment="local",
        audience="response_rich_local",
        evidence=_evidence(),
    )
    changed = build_selection_intent(
        retailer_id="gulf-oil",
        tenant_id="india-demo",
        environment="local",
        audience="response_rich_local",
        evidence=_evidence(recommendationsFingerprint="9" * 64),
    )

    assert first["selectionId"] != changed["selectionId"]


def test_bundle_and_approval_metadata_do_not_change_selection_identity() -> None:
    first = _selection("candidate")
    later_bundle = _selection(
        "approved",
        first["recordId"],
        bundle_id="pb_fedcba9876543210fedc",
        actor="second-reviewer",
    )

    assert first["selectionId"] == later_bundle["selectionId"]
    assert first["recordId"] != later_bundle["recordId"]


def test_result_selection_golden_vectors() -> None:
    document = json.loads(
        (ROOT / "contracts/pricing/result-selection-golden-vectors.json").read_text(
            encoding="utf-8"
        )
    )
    assert document["schemaVersion"] == (
        "retail-pricing-result-selection-golden-vectors/v1"
    )
    for vector in document["vectors"]:
        scope = vector["scope"]
        intent = build_selection_intent(
            retailer_id=scope["retailerId"],
            tenant_id=scope["tenantId"],
            environment=scope["environment"],
            audience=scope["audience"],
            evidence=vector["evidence"],
        )
        lifecycle = vector["lifecycle"]
        record = build_selection_record(
            retailer_id=scope["retailerId"],
            tenant_id=scope["tenantId"],
            environment=scope["environment"],
            audience=scope["audience"],
            evidence=vector["evidence"],
            state=lifecycle["state"],
            bundle_id=lifecycle["bundleId"],
            bundle_semantic_fingerprint=lifecycle["bundleSemanticFingerprint"],
            predecessor_record_id=lifecycle["predecessorRecordId"],
            actor=lifecycle["actor"],
            reason=lifecycle["reason"],
            recorded_at=lifecycle["recordedAt"],
        )
        assert intent["selectionId"] == vector["expectedSelectionId"]
        assert record["selectionId"] == vector["expectedSelectionId"]
        assert record["recordId"] == vector["expectedRecordId"]


def test_tampered_selection_identity_is_refused() -> None:
    record = _selection("candidate")
    record["tenantId"] = "different-tenant"
    with pytest.raises(PricingSelectionError, match="selectionId"):
        validate_selection_record(
            record, ROOT / "contracts/pricing/result-selection.schema.json"
        )


def test_activation_identity_is_stable_across_timestamp_only() -> None:
    first = build_activation_set(
        retailer_id="gulf-oil",
        tenant_id="india-demo",
        environment="local",
        bundle_id="pb_0123456789abcdef0123",
        bundle_semantic_fingerprint="a" * 64,
        active_selection_ids=["rsel_0123456789abcdef"],
        predecessor_activation_set_id=None,
        activated_at="2026-08-11T12:00:00Z",
    )
    second = json.loads(json.dumps(first))
    second["activatedAt"] = "2026-08-11T12:05:00Z"
    assert first["activationSetId"] == second["activationSetId"]
    validate_activation_set(
        second, ROOT / "contracts/pricing/activation-set.schema.json"
    )
