#!/usr/bin/env python3
"""Build or verify one explicit, full-scope batch input authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "contracts/python/src"))
sys.path.insert(0, str(REPO_ROOT / "ingestion/src"))

from retail_contracts.input_authority import (  # noqa: E402
    IDENTITY_EXCLUDES,
    SCHEMA_VERSION,
    authority_id,
    validate_input_authority,
    verify_input_authority,
)
from retail_ingestion.readiness.selection import (  # noqa: E402
    resolve_selection_ledger,
)

DEFAULT_SCHEMA = REPO_ROOT / "contracts/onboarding/input-authority.schema.json"
DEFAULT_POINTER = REPO_ROOT / "contracts/evidence/capability-entry-current.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _inside(root: Path, path: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"path is outside repository: {path}") from exc
    return resolved


def _logical(root: Path, path: Path) -> str:
    return _inside(root, path).relative_to(root.resolve()).as_posix()


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return _inside(root, path if path.is_absolute() else root / path)


def _scope_key(scope: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(scope["retailerId"]),
        str(scope["tenantId"]),
        str(scope["capability"]),
        str(scope["environment"]),
    )


def build_authority(
    *,
    repository_root: Path,
    run_id: str,
    audience: str,
    job_purpose: str,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    capabilities: Iterable[str],
    evidence_root: Path,
    selection_ledger: Path,
    entry_pointer: Path,
    expected_pin: Path,
    reviewer: str,
    reviewed_at: str,
    reason: str,
    schema_path: Path = DEFAULT_SCHEMA,
) -> dict[str, Any]:
    root = repository_root.resolve()
    evidence = _resolve(root, evidence_root)
    ledger = _resolve(root, selection_ledger)
    pointer_path = _resolve(root, entry_pointer)
    pin_path = _resolve(root, expected_pin)
    required_files = {
        "gate A": evidence / "gate-a.json",
        "gate B": evidence / "gate-b.json",
        "publication manifest": evidence / "publication-manifest.json",
        "operational readiness": evidence / "operational-readiness.json",
        "capability-entry pointer": pointer_path,
        "expected pin": pin_path,
    }
    for label, path in required_files.items():
        if not path.is_file():
            raise RuntimeError(f"{label} is absent: {path}")

    pointer = _load(pointer_path)
    pointer_by_scope = {
        _scope_key(entry["scope"]): entry for entry in pointer["entries"]
    }
    capabilities = tuple(sorted(set(capabilities)))
    if not capabilities:
        raise RuntimeError("at least one capability is required")

    scopes: list[dict[str, Any]] = []
    entry_records: list[dict[str, Any]] = []
    for capability in capabilities:
        scope_key = (retailer_id, tenant_id, capability, environment)
        pointer_entry = pointer_by_scope.get(scope_key)
        if pointer_entry is None:
            raise RuntimeError(
                "capability-entry pointer has no adopted exact scope "
                + "/".join(scope_key)
            )
        record_path = _resolve(root, pointer_entry["recordPath"])
        if _sha256(record_path) != pointer_entry["recordByteSha256"]:
            raise RuntimeError(f"capability-entry pointer hash mismatch: {record_path}")
        entry_records.append(
            {
                "scope": pointer_entry["scope"],
                "recordPath": _logical(root, record_path),
                "recordByteSha256": _sha256(record_path),
                "recordId": pointer_entry["recordId"],
            }
        )

        selection = resolve_selection_ledger(
            ledger,
            retailer_id=retailer_id,
            tenant_id=tenant_id,
            capability=capability,
            environment=environment,
            repository_root=root,
        )
        selection_path = _resolve(root, selection.pop("_recordPath"))
        subject = selection.get("subject") or selection.get("publication") or {}
        if subject.get("logicalPath") and not str(subject["logicalPath"]).endswith(run_id):
            raise RuntimeError(
                f"active {capability} selection does not name requested run {run_id}"
            )
        scopes.append(
            {
                "retailerId": retailer_id,
                "tenantId": tenant_id,
                "capability": capability,
                "environment": environment,
                "selectionId": selection["selectionId"],
                "selectionRecordId": selection["lifecycle"]["recordId"],
                "selectionRecordPath": _logical(root, selection_path),
                "selectionRecordByteSha256": _sha256(selection_path),
            }
        )

    gate_a = _load(required_files["gate A"])
    gate_b = _load(required_files["gate B"])
    manifest = _load(required_files["publication manifest"])
    readiness = _load(required_files["operational readiness"])
    if manifest.get("sourceSnapshotId") != gate_a.get("sourceSnapshotId"):
        raise RuntimeError("Gate A and publication source snapshot differ")
    if manifest.get("sourceSnapshotId") != gate_b.get("sourceSnapshotId"):
        raise RuntimeError("Gate B and publication source snapshot differ")
    if readiness.get("publicationSemanticFingerprint") != manifest.get(
        "semanticFingerprint"
    ):
        raise RuntimeError("readiness and publication identities differ")

    authority: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "authorityId": "auth_0000000000000000",
        "semanticIdentityExcludes": list(IDENTITY_EXCLUDES),
        "audience": audience,
        "jobPurpose": job_purpose,
        "runId": run_id,
        "evidenceRoot": _logical(root, evidence),
        "expectedPin": {
            "path": _logical(root, pin_path),
            "byteSha256": _sha256(pin_path),
        },
        "entryEvidence": {
            "pointerPath": _logical(root, pointer_path),
            "pointerByteSha256": _sha256(pointer_path),
            "records": sorted(entry_records, key=lambda row: _scope_key(row["scope"])),
        },
        "scopes": sorted(scopes, key=_scope_key),
        "sourceEvidence": {
            "sourceSnapshotId": manifest["sourceSnapshotId"],
            "gateASemanticFingerprint": gate_a["semanticFingerprint"],
            "gateBSemanticFingerprint": gate_b["semanticFingerprint"],
            "publicationSemanticFingerprint": manifest["semanticFingerprint"],
            "publicationManifestSha256": _sha256(
                required_files["publication manifest"]
            ),
            "readinessReportFingerprint": readiness["reportFingerprint"],
            "readinessReportSha256": _sha256(
                required_files["operational readiness"]
            ),
        },
        "review": {
            "actor": reviewer,
            "reviewedAt": reviewed_at,
            "reason": reason,
        },
    }
    authority["authorityId"] = authority_id(authority)
    validate_input_authority(authority, schema_path=schema_path)
    return authority


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as writer:
            writer.write(payload)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    parser.add_argument("--audience", required=True)
    parser.add_argument("--job-purpose", required=True)
    parser.add_argument("--retailer", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--capability", action="append", required=True)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--selection-ledger", required=True, type=Path)
    parser.add_argument("--entry-pointer", required=True, type=Path)
    parser.add_argument("--expected-pin", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument(
        "--reviewed-at",
        default=datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument("--check", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    output = _resolve(REPO_ROOT, args.output)
    if args.check:
        verify_input_authority(
            output,
            schema_path=DEFAULT_SCHEMA,
            repository_root=REPO_ROOT,
            expected_run_id=args.run,
            expected_job_purpose=args.job_purpose,
            retailer_id=args.retailer,
            tenant_id=args.tenant,
            environment=args.environment,
            expected_pin_path=args.expected_pin,
            evidence_root=args.evidence_root,
        )
        print(f"{output.relative_to(REPO_ROOT)} is valid")
        return 0
    authority = build_authority(
        repository_root=REPO_ROOT,
        run_id=args.run,
        audience=args.audience,
        job_purpose=args.job_purpose,
        retailer_id=args.retailer,
        tenant_id=args.tenant,
        environment=args.environment,
        capabilities=args.capability,
        evidence_root=args.evidence_root,
        selection_ledger=args.selection_ledger,
        entry_pointer=args.entry_pointer,
        expected_pin=args.expected_pin,
        reviewer=args.reviewer,
        reviewed_at=args.reviewed_at,
        reason=args.reason,
    )
    payload = _canonical_bytes(authority)
    if output.exists() and output.read_bytes() != payload:
        raise SystemExit(f"refusing to replace different input authority: {output}")
    if not output.exists():
        _atomic_write(output, payload)
    print(f"{authority['authorityId']} {output.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
