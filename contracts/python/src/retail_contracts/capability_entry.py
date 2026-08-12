"""Immutable, crash-safe capability entry-record adoption.

The entry record is semantic, content-addressed evidence. Execution metadata is
kept in a separate UUIDv7 receipt, and the only mutable file is a small current
pointer. A durable journal makes an interrupted pointer replacement recover to
exactly one receipt before another adoption can begin.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from .fingerprint import canonical_json_bytes, semantic_fingerprint

ENTRY_SCHEMA_VERSION = "retail-capability-entry-record/v1"
POINTER_SCHEMA_VERSION = "retail-capability-entry-pointer/v1"
RECEIPT_SCHEMA_VERSION = "retail-capability-entry-receipt/v1"
ENTRY_IDENTITY_EXCLUSIONS = ("/recordId",)


class CapabilityEntryError(RuntimeError):
    """The entry set cannot be validated, adopted, or recovered safely."""


class SimulatedInterruption(CapabilityEntryError):
    """Test-only interruption at a durable adoption boundary."""


def scope_key(scope: Mapping[str, Any]) -> tuple[str, str, str, str]:
    """Return the one canonical ordering key used at every handoff."""

    return (
        str(scope["retailerId"]),
        str(scope["tenantId"]),
        str(scope["capability"]),
        str(scope["environment"]),
    )


def scope_token(scope: Mapping[str, Any]) -> str:
    """Return a stable display/storage key without making it an authority."""

    return "|".join(scope_key(scope))


def record_id(record: Mapping[str, Any]) -> str:
    """Derive the lowercase semantic SHA-256 with only ``/recordId`` removed."""

    return semantic_fingerprint(
        dict(record), volatile_pointers=ENTRY_IDENTITY_EXCLUSIONS
    )


def canonical_document_bytes(document: Mapping[str, Any]) -> bytes:
    """Return the exact complete JCS document bytes (no BOM or trailing LF)."""

    return canonical_json_bytes(dict(document))


def byte_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pointer_identity(data: bytes | None) -> dict[str, str]:
    if data is None:
        return {"state": "absent"}
    return {"state": "present", "byteSha256": byte_sha256(data)}


def uuid7(now_ms: int | None = None) -> str:
    """Create a lowercase canonical RFC 9562 UUIDv7 without runtime drift."""

    timestamp = int(time.time_ns() // 1_000_000 if now_ms is None else now_ms)
    if not 0 <= timestamp < (1 << 48):
        raise CapabilityEntryError("UUIDv7 timestamp exceeds its 48-bit field")
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        (timestamp << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return str(uuid.UUID(int=value))


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_document(document: Mapping[str, Any], schema_path: Path) -> None:
    schema = _load_schema(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(document)


def validate_record(record: Mapping[str, Any], schema_path: Path) -> bytes:
    validate_document(record, schema_path)
    actual = record_id(record)
    if record.get("recordId") != actual:
        raise CapabilityEntryError(
            f"recordId {record.get('recordId')!r} does not match {actual!r}"
        )
    return canonical_document_bytes(record)


def validate_exact_file(path: Path, schema_path: Path) -> dict[str, Any]:
    """Validate schema and prove the file is the canonical serialization."""

    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise CapabilityEntryError(f"{path}: UTF-8 BOM is forbidden")
    document = json.loads(raw.decode("utf-8"))
    validate_document(document, schema_path)
    if canonical_document_bytes(document) != raw:
        raise CapabilityEntryError(
            f"{path}: bytes are not the exact RFC 8785 canonical document"
        )
    return document


def _flush_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_create(path: Path, data: bytes) -> None:
    """Create once; an identical immutable object is an idempotent retry."""

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        if path.read_bytes() == data:
            return
        raise CapabilityEntryError(f"CREATE_ONLY_COLLISION: {path}") from None
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    _flush_directory(path.parent)


def _durable_replace(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid7()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _flush_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise CapabilityEntryError("LOCK_UNAVAILABLE") from exc
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise CapabilityEntryError("LOCK_UNAVAILABLE") from exc
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _receipt_path(receipts_root: Path, receipt_id: str) -> Path:
    return receipts_root / f"capability-entry-receipt-{receipt_id}.json"


def _write_receipt(
    receipt: Mapping[str, Any],
    *,
    receipts_root: Path,
    receipt_schema: Path,
) -> Path:
    validate_document(receipt, receipt_schema)
    destination = _receipt_path(receipts_root, str(receipt["receiptId"]))
    _durable_create(destination, canonical_document_bytes(receipt))
    return destination


def _remove_journal(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    _flush_directory(path.parent)


def recover_pending(
    *,
    pointer_path: Path,
    receipts_root: Path,
    journal_root: Path,
    receipt_schema: Path,
) -> list[Path]:
    """Resolve every durable journal before a new adoption is permitted."""

    recovered: list[Path] = []
    if not journal_root.exists():
        return recovered
    for journal_path in sorted(journal_root.glob("*.json")):
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        current = _read_bytes(pointer_path)
        current_identity = pointer_identity(current)
        before = journal["receipt"]["pointerBefore"]
        after = journal["receipt"]["pointerAfter"]
        receipt = dict(journal["receipt"])
        receipt["recovery"] = {
            "recovered": True,
            "journalId": journal["journalId"],
        }
        if current_identity == after:
            receipt["outcome"] = "adopted"
            receipt["failure"] = None
        elif current_identity == before:
            receipt["outcome"] = "refused"
            receipt["pointerAfter"] = before
            receipt["failure"] = {
                "reasonCode": "INTERRUPTED_BEFORE_ADOPTION",
                "failingScope": None,
                "detail": "Recovery found the predecessor pointer unchanged.",
            }
        else:
            receipt["outcome"] = "refused"
            receipt["pointerAfter"] = current_identity
            receipt["failure"] = {
                "reasonCode": "RECOVERY_CONFLICT",
                "failingScope": None,
                "detail": "Current pointer matches neither journal boundary.",
            }
            destination = _write_receipt(
                receipt,
                receipts_root=receipts_root,
                receipt_schema=receipt_schema,
            )
            recovered.append(destination)
            raise CapabilityEntryError("RECOVERY_CONFLICT")
        destination = _write_receipt(
            receipt,
            receipts_root=receipts_root,
            receipt_schema=receipt_schema,
        )
        recovered.append(destination)
        _remove_journal(journal_path)
    return recovered


def _entry_index(pointer: Mapping[str, Any] | None) -> dict[tuple[str, ...], dict[str, Any]]:
    if pointer is None:
        return {}
    return {scope_key(row["scope"]): dict(row) for row in pointer["entries"]}


def _refusal_receipt(
    ordered: Sequence[Mapping[str, Any]],
    *,
    receipt_id: str,
    executed_at: str,
    before_bytes: bytes | None,
    reason_code: str,
    detail: str,
    failing_scope: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Build the one refusal shape used by validation and create-only failures."""

    return {
        "schemaVersion": RECEIPT_SCHEMA_VERSION,
        "receiptId": receipt_id,
        "executedAt": executed_at,
        "orderedRecords": [
            {
                "scope": dict(item["scope"]),
                "recordId": str(item.get("recordId") or "0" * 64),
                "recordByteSha256": byte_sha256(canonical_document_bytes(item)),
            }
            for item in ordered
        ],
        "pointerBefore": pointer_identity(before_bytes),
        "pointerAfter": pointer_identity(before_bytes),
        "outcome": "refused",
        "failure": {
            "reasonCode": reason_code,
            "failingScope": dict(failing_scope) if failing_scope is not None else None,
            "detail": detail,
        },
        "recovery": {"recovered": False, "journalId": None},
    }


def adopt_records(
    records: Sequence[Mapping[str, Any]],
    *,
    repository_root: Path,
    entry_schema: Path,
    pointer_schema: Path,
    receipt_schema: Path,
    fail_after: str | None = None,
) -> tuple[dict[str, Any], Path]:
    """Adopt a complete record set atomically and emit its immutable receipt."""

    if not records:
        raise CapabilityEntryError("an adoption set cannot be empty")
    ordered = sorted(
        (dict(record) for record in records), key=lambda row: scope_key(row["scope"])
    )
    keys = [scope_key(record["scope"]) for record in ordered]
    if len(keys) != len(set(keys)):
        raise CapabilityEntryError("an adoption set contains duplicate scopes")

    evidence_root = repository_root / "contracts" / "evidence"
    records_root = evidence_root / "capability-entry-records"
    receipts_root = evidence_root / "capability-entry-receipts"
    pointer_path = evidence_root / "capability-entry-current.json"
    journal_root = evidence_root / ".capability-entry-adoption-staging"
    lock_path = evidence_root / ".capability-entry-adoption.lock"
    receipt_id = uuid7()
    executed_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    with _exclusive_lock(lock_path):
        recover_pending(
            pointer_path=pointer_path,
            receipts_root=receipts_root,
            journal_root=journal_root,
            receipt_schema=receipt_schema,
        )
        before_bytes = _read_bytes(pointer_path)
        before_document = (
            json.loads(before_bytes.decode("utf-8")) if before_bytes is not None else None
        )
        if before_document is not None:
            validate_document(before_document, pointer_schema)
            if canonical_document_bytes(before_document) != before_bytes:
                raise CapabilityEntryError("current pointer is not exact canonical JSON")
        existing = _entry_index(before_document)

        prepared: list[tuple[dict[str, Any], bytes]] = []
        try:
            for record in ordered:
                raw = validate_record(record, entry_schema)
                key = scope_key(record["scope"])
                current = existing.get(key)
                expected_predecessor = current["recordId"] if current else None
                if record["predecessorRecordId"] != expected_predecessor:
                    raise CapabilityEntryError(
                        "PREDECESSOR_MISMATCH: " + scope_token(record["scope"])
                    )
                prepared.append((record, raw))
        except Exception as exc:
            failure_scope = dict(record["scope"]) if "record" in locals() else None
            reason = str(exc).split(":", 1)[0]
            if reason not in {"PREDECESSOR_MISMATCH", "CREATE_ONLY_COLLISION"}:
                reason = "INVALID_ENTRY"
            receipt = _refusal_receipt(
                ordered,
                receipt_id=receipt_id,
                executed_at=executed_at,
                before_bytes=before_bytes,
                reason_code=reason,
                detail=str(exc),
                failing_scope=failure_scope,
            )
            receipt_path = _write_receipt(
                receipt,
                receipts_root=receipts_root,
                receipt_schema=receipt_schema,
            )
            return receipt, receipt_path

        try:
            for record, raw in prepared:
                destination = records_root / f"capability-entry-record-{record['recordId']}.json"
                _durable_create(destination, raw)
        except CapabilityEntryError as exc:
            receipt = _refusal_receipt(
                ordered,
                receipt_id=receipt_id,
                executed_at=executed_at,
                before_bytes=before_bytes,
                reason_code="CREATE_ONLY_COLLISION",
                detail=str(exc),
                failing_scope=record["scope"],
            )
            receipt_path = _write_receipt(
                receipt,
                receipts_root=receipts_root,
                receipt_schema=receipt_schema,
            )
            return receipt, receipt_path

        updated = dict(existing)
        for record, raw in prepared:
            updated[scope_key(record["scope"])] = {
                "scope": dict(record["scope"]),
                "recordId": record["recordId"],
                "recordPath": (
                    "contracts/evidence/capability-entry-records/"
                    f"capability-entry-record-{record['recordId']}.json"
                ),
                "recordByteSha256": byte_sha256(raw),
                "adoptionReceiptId": receipt_id,
            }
        pointer = {
            "schemaVersion": POINTER_SCHEMA_VERSION,
            "lastAdoptionReceiptId": receipt_id,
            "entries": [updated[key] for key in sorted(updated)],
        }
        validate_document(pointer, pointer_schema)
        after_bytes = canonical_document_bytes(pointer)
        receipt = {
            "schemaVersion": RECEIPT_SCHEMA_VERSION,
            "receiptId": receipt_id,
            "executedAt": executed_at,
            "orderedRecords": [
                {
                    "scope": dict(record["scope"]),
                    "recordId": record["recordId"],
                    "recordByteSha256": byte_sha256(raw),
                }
                for record, raw in prepared
            ],
            "pointerBefore": pointer_identity(before_bytes),
            "pointerAfter": pointer_identity(after_bytes),
            "outcome": "adopted",
            "failure": None,
            "recovery": {"recovered": False, "journalId": None},
        }
        journal_root.mkdir(parents=True, exist_ok=True)
        journal_id = f"journal-{receipt_id}"
        journal = {
            "schemaVersion": "retail-capability-entry-adoption-journal/v1",
            "journalId": journal_id,
            "receipt": receipt,
        }
        journal_path = journal_root / f"{journal_id}.json"
        _durable_create(journal_path, canonical_document_bytes(journal))
        if fail_after == "prepared":
            raise SimulatedInterruption("simulated interruption after journal prepare")
        _durable_replace(pointer_path, after_bytes)
        if fail_after == "pointer_replaced":
            raise SimulatedInterruption("simulated interruption after pointer replacement")
        receipt_path = _write_receipt(
            receipt,
            receipts_root=receipts_root,
            receipt_schema=receipt_schema,
        )
        _remove_journal(journal_path)
        return receipt, receipt_path


__all__ = [
    "ENTRY_IDENTITY_EXCLUSIONS",
    "ENTRY_SCHEMA_VERSION",
    "POINTER_SCHEMA_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "CapabilityEntryError",
    "SimulatedInterruption",
    "adopt_records",
    "byte_sha256",
    "canonical_document_bytes",
    "pointer_identity",
    "record_id",
    "recover_pending",
    "scope_key",
    "scope_token",
    "uuid7",
    "validate_document",
    "validate_exact_file",
    "validate_record",
]
