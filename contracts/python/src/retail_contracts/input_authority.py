"""Content-addressed, explicit authority for source-consuming batch jobs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .fingerprint import semantic_fingerprint

SCHEMA_VERSION = "retail-input-authority/v1"
IDENTITY_EXCLUDES = ("/authorityId", "/review")


class InputAuthorityError(RuntimeError):
    """The requested job does not match its retained input authority."""


def authority_id(authority: Mapping[str, Any]) -> str:
    return "auth_" + semantic_fingerprint(
        dict(authority), volatile_pointers=IDENTITY_EXCLUDES
    )[:16]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repo_path(repository_root: Path, logical_path: str) -> Path:
    root = repository_root.resolve()
    candidate = (root / logical_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise InputAuthorityError(
            f"authority path escapes the repository: {logical_path}"
        ) from exc
    return candidate


def validate_input_authority(
    authority: Mapping[str, Any], *, schema_path: Path
) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(authority)
    if tuple(authority["semanticIdentityExcludes"]) != IDENTITY_EXCLUDES:
        raise InputAuthorityError("input-authority identity vector mismatch")
    expected = authority_id(authority)
    if authority.get("authorityId") != expected:
        raise InputAuthorityError(
            f"authorityId {authority.get('authorityId')!r} does not match {expected!r}"
        )
    scope_keys = [
        (
            row["retailerId"],
            row["tenantId"],
            row["capability"],
            row["environment"],
        )
        for row in authority["scopes"]
    ]
    if scope_keys != sorted(scope_keys) or len(scope_keys) != len(set(scope_keys)):
        raise InputAuthorityError(
            "input-authority scopes must be unique and canonically ordered"
        )
    entry_keys = [
        (
            row["scope"]["retailerId"],
            row["scope"]["tenantId"],
            row["scope"]["capability"],
            row["scope"]["environment"],
        )
        for row in authority["entryEvidence"]["records"]
    ]
    if entry_keys != sorted(entry_keys) or len(entry_keys) != len(set(entry_keys)):
        raise InputAuthorityError(
            "entry-evidence records must be unique and canonically ordered"
        )
    if entry_keys != scope_keys:
        raise InputAuthorityError(
            "entry-evidence records must cover exactly the authority scope set"
        )


def verify_input_authority(
    authority_path: str | Path,
    *,
    schema_path: Path,
    repository_root: str | Path,
    expected_run_id: str,
    expected_job_purpose: str,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    expected_pin_path: str | Path,
    evidence_root: str | Path,
) -> dict[str, Any]:
    """Validate authority, exact caller scope, and every retained byte binding."""

    root = Path(repository_root).resolve()
    path = Path(authority_path)
    if not path.is_absolute():
        path = _repo_path(root, str(path))
    if not path.is_file():
        raise InputAuthorityError(f"input authority is absent: {path}")
    authority = json.loads(path.read_text(encoding="utf-8"))
    validate_input_authority(authority, schema_path=schema_path)
    expected = {
        "runId": expected_run_id,
        "jobPurpose": expected_job_purpose,
    }
    for field, value in expected.items():
        if authority.get(field) != value:
            raise InputAuthorityError(
                f"{field} {authority.get(field)!r} does not match requested {value!r}"
            )
    declared_evidence = _repo_path(root, authority["evidenceRoot"])
    requested_evidence = Path(evidence_root)
    if not requested_evidence.is_absolute():
        requested_evidence = _repo_path(root, str(requested_evidence))
    else:
        requested_evidence = requested_evidence.resolve()
        try:
            requested_evidence.relative_to(root)
        except ValueError as exc:
            raise InputAuthorityError(
                "requested evidence root escapes the repository"
            ) from exc
    if declared_evidence != requested_evidence:
        raise InputAuthorityError(
            "authority evidence root differs from the requested repository path"
        )
    scopes = authority["scopes"]
    if not scopes:
        raise InputAuthorityError("input authority has no scopes")
    for scope in scopes:
        actual = (scope["retailerId"], scope["tenantId"], scope["environment"])
        requested = (retailer_id, tenant_id, environment)
        if actual != requested:
            raise InputAuthorityError(
                f"authority scope {actual!r} does not match caller {requested!r}"
            )

    pin = Path(expected_pin_path)
    if not pin.is_absolute():
        pin = _repo_path(root, str(pin))
    declared_pin = _repo_path(root, authority["expectedPin"]["path"])
    if declared_pin != pin.resolve():
        raise InputAuthorityError("caller expected-pin path differs from authority")
    if _sha256(pin) != authority["expectedPin"]["byteSha256"]:
        raise InputAuthorityError("expected-pin byte hash mismatch")
    pin_document = json.loads(pin.read_text(encoding="utf-8"))
    if pin_document.get("sourceSnapshotId") != authority["sourceEvidence"][
        "sourceSnapshotId"
    ]:
        raise InputAuthorityError("expected pin names a different source snapshot")
    if (pin_document.get("publication") or {}).get(
        "semanticFingerprint"
    ) != authority["sourceEvidence"]["publicationSemanticFingerprint"]:
        raise InputAuthorityError("expected pin names a different publication")

    pointer = _repo_path(root, authority["entryEvidence"]["pointerPath"])
    if _sha256(pointer) != authority["entryEvidence"]["pointerByteSha256"]:
        raise InputAuthorityError("capability-entry pointer byte hash mismatch")
    pointer_document = json.loads(pointer.read_text(encoding="utf-8"))
    adopted = {
        (
            row["scope"]["retailerId"],
            row["scope"]["tenantId"],
            row["scope"]["capability"],
            row["scope"]["environment"],
        ): row
        for row in pointer_document["entries"]
    }
    for entry in authority["entryEvidence"]["records"]:
        record_path = _repo_path(root, entry["recordPath"])
        if _sha256(record_path) != entry["recordByteSha256"]:
            raise InputAuthorityError(
                f"capability-entry record byte hash mismatch: {entry['recordPath']}"
            )
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("recordId") != entry["recordId"]:
            raise InputAuthorityError("capability-entry recordId mismatch")
        if record.get("scope") != entry["scope"]:
            raise InputAuthorityError("capability-entry scope mismatch")
        key = (
            entry["scope"]["retailerId"],
            entry["scope"]["tenantId"],
            entry["scope"]["capability"],
            entry["scope"]["environment"],
        )
        pointer_entry = adopted.get(key)
        if pointer_entry is None or pointer_entry.get("recordId") != entry["recordId"]:
            raise InputAuthorityError("input authority cites an unadopted entry record")

    for scope in scopes:
        selection_path = _repo_path(root, scope["selectionRecordPath"])
        if _sha256(selection_path) != scope["selectionRecordByteSha256"]:
            raise InputAuthorityError(
                f"selection record byte hash mismatch: {scope['selectionRecordPath']}"
            )
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        if selection.get("selectionId") != scope["selectionId"]:
            raise InputAuthorityError("selectionId mismatch")
        if (selection.get("lifecycle") or {}).get("recordId") != scope[
            "selectionRecordId"
        ]:
            raise InputAuthorityError("selection lifecycle recordId mismatch")
        if selection.get("scope") != {
            key: scope[key]
            for key in ("retailerId", "tenantId", "capability", "environment")
        }:
            raise InputAuthorityError("selection scope mismatch")
        if (selection.get("lifecycle") or {}).get("state") != "active":
            raise InputAuthorityError("selection is not active")
        subject = selection.get("subject") or selection.get("publication") or {}
        logical_path = str(subject.get("logicalPath") or "")
        if not logical_path or Path(logical_path).name != expected_run_id:
            raise InputAuthorityError("selection names a different source run")
        readiness = selection.get("readiness") or {}
        if readiness.get("capabilityReadiness") != "ready":
            raise InputAuthorityError("selection capability is not ready")
        if readiness.get("capabilitySufficiency") != "sufficient":
            raise InputAuthorityError("selection capability is not sufficient")

    evidence = requested_evidence
    manifest = evidence / "publication-manifest.json"
    readiness = evidence / "operational-readiness.json"
    gate_a = evidence / "gate-a.json"
    gate_b = evidence / "gate-b.json"
    if _sha256(manifest) != authority["sourceEvidence"][
        "publicationManifestSha256"
    ]:
        raise InputAuthorityError("publication manifest byte hash mismatch")
    if _sha256(readiness) != authority["sourceEvidence"]["readinessReportSha256"]:
        raise InputAuthorityError("readiness report byte hash mismatch")
    readiness_document = json.loads(readiness.read_text(encoding="utf-8"))
    if readiness_document.get("reportFingerprint") != authority["sourceEvidence"][
        "readinessReportFingerprint"
    ]:
        raise InputAuthorityError("readiness report fingerprint mismatch")
    manifest_document = json.loads(manifest.read_text(encoding="utf-8"))
    gate_a_document = json.loads(gate_a.read_text(encoding="utf-8"))
    gate_b_document = json.loads(gate_b.read_text(encoding="utf-8"))
    source_evidence = authority["sourceEvidence"]
    comparisons = {
        "sourceSnapshotId": manifest_document.get("sourceSnapshotId"),
        "publicationSemanticFingerprint": manifest_document.get(
            "semanticFingerprint"
        ),
        "gateASemanticFingerprint": gate_a_document.get("semanticFingerprint"),
        "gateBSemanticFingerprint": gate_b_document.get("semanticFingerprint"),
    }
    for field, actual in comparisons.items():
        if source_evidence.get(field) != actual:
            raise InputAuthorityError(f"source-evidence {field} mismatch")
    if readiness_document.get("publicationSemanticFingerprint") != (
        manifest_document.get("semanticFingerprint")
    ):
        raise InputAuthorityError("readiness sidecar names a different publication")
    for scope in scopes:
        selection = json.loads(
            _repo_path(root, scope["selectionRecordPath"]).read_text(encoding="utf-8")
        )
        subject = selection.get("subject") or selection.get("publication") or {}
        if subject.get("sourceSnapshotId") != manifest_document.get("sourceSnapshotId"):
            raise InputAuthorityError("selection names a different source snapshot")
        if subject.get("publicationSemanticFingerprint") != manifest_document.get(
            "semanticFingerprint"
        ):
            raise InputAuthorityError("selection names a different publication")
    return authority


__all__ = [
    "IDENTITY_EXCLUDES",
    "SCHEMA_VERSION",
    "InputAuthorityError",
    "authority_id",
    "validate_input_authority",
    "verify_input_authority",
]
