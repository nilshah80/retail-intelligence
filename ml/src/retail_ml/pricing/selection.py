"""Canonical pricing result-selection and activation-set identities."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


class PricingSelectionError(RuntimeError):
    """A selection or activation document is invalid or non-canonical."""


SELECTION_IDENTITY_EXCLUDES = (
    "/bundleId",
    "/bundleSemanticFingerprint",
    "/predecessorRecordId",
    "/recordId",
    "/recordedAt",
    "/review",
    "/selectionId",
    "/state",
)


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _short_identity(prefix: str, value: Mapping[str, Any]) -> str:
    return prefix + hashlib.sha256(_canonical(value)).hexdigest()[:16]


def selection_id(document: Mapping[str, Any]) -> str:
    """Identify the full capability scope and evidence, independent of lifecycle.

    Bundle and verifier identities belong to individual immutable event records,
    not to the stable result identity that candidate/approved/active events share.
    The non-circular evidence projection is deliberately part of this identity so
    two semantically different result sets cannot share a selection ID.
    """

    if document.get("semanticIdentityExcludes") != list(
        SELECTION_IDENTITY_EXCLUDES
    ):
        raise PricingSelectionError("selection identity exclusions changed")
    excluded = {pointer.removeprefix("/") for pointer in SELECTION_IDENTITY_EXCLUDES}
    projection = {
        key: value for key, value in document.items() if key not in excluded
    }
    return _short_identity("rsel_", projection)


SELECTION_CAPABILITIES = ("price_revenue", "price_margin")


def build_selection_intent(
    *,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    audience: str,
    evidence: Mapping[str, Any],
    capability: str = "price_revenue",
) -> dict[str, Any]:
    """Build the exact non-lifecycle projection bound before bundle closure.

    ``capability`` defaults to ``price_revenue`` so existing callers are
    unchanged byte-for-byte. ``price_margin`` is additive and only ever admitted
    with genuine client-actual cost evidence (``P5-D6``/``P5-D24``); generated
    cost never yields a ``price_margin`` selection.
    """

    if capability not in SELECTION_CAPABILITIES:
        raise PricingSelectionError(f"unknown selection capability {capability!r}")
    document: dict[str, Any] = {
        "schemaVersion": "retail-pricing-result-selection/v2",
        "selectionId": "pending",
        "semanticIdentityExcludes": list(SELECTION_IDENTITY_EXCLUDES),
        "retailerId": retailer_id,
        "tenantId": tenant_id,
        "environment": environment,
        "capability": capability,
        "audience": audience,
        "evidence": dict(evidence),
    }
    document["selectionId"] = selection_id(document)
    return document


def selection_intent_from_record(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": document["schemaVersion"],
        "selectionId": document["selectionId"],
        "semanticIdentityExcludes": document["semanticIdentityExcludes"],
        "retailerId": document["retailerId"],
        "tenantId": document["tenantId"],
        "environment": document["environment"],
        "capability": document["capability"],
        "audience": document["audience"],
        "evidence": document["evidence"],
    }


def selection_record_id(document: Mapping[str, Any]) -> str:
    projection = {key: value for key, value in document.items() if key != "recordId"}
    return _short_identity("rselrec_", projection)


def activation_set_id(document: Mapping[str, Any]) -> str:
    projection = {
        key: value
        for key, value in document.items()
        if key not in {"activationSetId", "activatedAt"}
    }
    return _short_identity("pact_", projection)


def build_selection_record(
    *,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    audience: str,
    evidence: Mapping[str, Any],
    state: str,
    bundle_id: str,
    bundle_semantic_fingerprint: str,
    predecessor_record_id: str | None,
    actor: str,
    reason: str,
    recorded_at: str | None = None,
    capability: str = "price_revenue",
) -> dict[str, Any]:
    if capability not in SELECTION_CAPABILITIES:
        raise PricingSelectionError(f"unknown selection capability {capability!r}")
    document: dict[str, Any] = {
        "schemaVersion": "retail-pricing-result-selection/v2",
        "recordId": "pending",
        "selectionId": "pending",
        "semanticIdentityExcludes": list(SELECTION_IDENTITY_EXCLUDES),
        "retailerId": retailer_id,
        "tenantId": tenant_id,
        "environment": environment,
        "capability": capability,
        "audience": audience,
        "evidence": dict(evidence),
        "state": state,
        "bundleId": bundle_id,
        "bundleSemanticFingerprint": bundle_semantic_fingerprint,
        "predecessorRecordId": predecessor_record_id,
        "recordedAt": recorded_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "review": {"actor": actor, "reason": reason},
    }
    document["selectionId"] = selection_id(document)
    document["recordId"] = selection_record_id(document)
    return document


def build_activation_set(
    *,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    bundle_id: str,
    bundle_semantic_fingerprint: str,
    active_selection_ids: list[str],
    predecessor_activation_set_id: str | None,
    activated_at: str | None = None,
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "schemaVersion": "retail-pricing-activation-set/v1",
        "activationSetId": "pending",
        "retailerId": retailer_id,
        "tenantId": tenant_id,
        "environment": environment,
        "audience": "response_rich_local",
        "bundleId": bundle_id,
        "bundleSemanticFingerprint": bundle_semantic_fingerprint,
        "activeSelectionIds": sorted(active_selection_ids),
        "predecessorActivationSetId": predecessor_activation_set_id,
        "activatedAt": activated_at
        or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    document["activationSetId"] = activation_set_id(document)
    return document


def validate_selection_record(
    document: Mapping[str, Any], schema_path: str | Path
) -> dict[str, Any]:
    resolved = dict(document)
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(resolved),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PricingSelectionError(errors[0].message)
    if resolved["selectionId"] != selection_id(resolved):
        raise PricingSelectionError("selectionId does not match the canonical full scope")
    if resolved["recordId"] != selection_record_id(resolved):
        raise PricingSelectionError("recordId does not match the immutable event bytes")
    return resolved


def validate_selection_intent(
    document: Mapping[str, Any], schema_path: str | Path
) -> dict[str, Any]:
    resolved = dict(document)
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(resolved),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PricingSelectionError(errors[0].message)
    if resolved["selectionId"] != selection_id(resolved):
        raise PricingSelectionError(
            "selectionId does not match the canonical full scope and evidence"
        )
    return resolved


def validate_activation_set(
    document: Mapping[str, Any], schema_path: str | Path
) -> dict[str, Any]:
    resolved = dict(document)
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(resolved),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PricingSelectionError(errors[0].message)
    if resolved["activationSetId"] != activation_set_id(resolved):
        raise PricingSelectionError(
            "activationSetId does not match the canonical activation content"
        )
    if resolved["activeSelectionIds"] != sorted(resolved["activeSelectionIds"]):
        raise PricingSelectionError("activeSelectionIds must use canonical sorted order")
    return resolved


__all__ = [
    "PricingSelectionError", "SELECTION_IDENTITY_EXCLUDES", "activation_set_id", "build_activation_set",
    "build_selection_intent", "build_selection_record", "selection_id",
    "selection_intent_from_record", "selection_record_id",
    "validate_activation_set", "validate_selection_intent",
    "validate_selection_record",
]
