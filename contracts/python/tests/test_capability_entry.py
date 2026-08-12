from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from retail_contracts.capability_entry import (
    CapabilityEntryError,
    SimulatedInterruption,
    adopt_records,
    canonical_document_bytes,
    record_id,
    recover_pending,
    scope_key,
    uuid7,
    validate_exact_file,
    validate_record,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_ROOT = REPO_ROOT / "contracts" / "onboarding"
ENTRY_SCHEMA = SCHEMA_ROOT / "capability-entry-record.schema.json"
POINTER_SCHEMA = SCHEMA_ROOT / "capability-entry-pointer.schema.json"
RECEIPT_SCHEMA = SCHEMA_ROOT / "capability-entry-receipt.schema.json"
VECTORS = SCHEMA_ROOT / "capability-entry-golden-vectors.json"


def _vector_record() -> dict:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    return copy.deepcopy(document["vectors"][0]["record"])


def _record(capability: str, predecessor: str | None = None) -> dict:
    value = _vector_record()
    value["scope"]["capability"] = capability
    value["predecessorRecordId"] = predecessor
    value["recordId"] = record_id(value)
    return value


def test_golden_record_id_and_exact_jcs_bytes() -> None:
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    vector = document["vectors"][0]
    assert record_id(vector["record"]) == vector["recordId"]
    record = copy.deepcopy(vector["record"])
    record["recordId"] = vector["recordId"]
    raw = validate_record(record, ENTRY_SCHEMA)
    assert raw == canonical_document_bytes(record)
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not raw.endswith(b"\n")


def test_record_identity_excludes_only_its_embedded_id() -> None:
    record = _vector_record()
    original = record_id(record)
    record["recordId"] = "f" * 64
    assert record_id(record) == original
    record["sourceAuthority"]["objectCount"] += 1
    assert record_id(record) != original


def test_uuid7_is_lowercase_canonical_and_monotonic_by_timestamp() -> None:
    first = uuid7(1_700_000_000_000)
    second = uuid7(1_700_000_000_001)
    pattern = re.compile(
        r"^[a-f0-9]{8}-[a-f0-9]{4}-7[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
    )
    assert pattern.fullmatch(first)
    assert pattern.fullmatch(second)
    assert first < second


def test_complete_set_adopts_once_and_preserves_canonical_order(tmp_path: Path) -> None:
    records = [_record("price_revenue"), _record("demand_forecast_non_pit")]
    receipt, receipt_path = adopt_records(
        list(reversed(records)),
        repository_root=tmp_path,
        entry_schema=ENTRY_SCHEMA,
        pointer_schema=POINTER_SCHEMA,
        receipt_schema=RECEIPT_SCHEMA,
    )
    assert receipt["outcome"] == "adopted"
    pointer_path = tmp_path / "contracts/evidence/capability-entry-current.json"
    pointer = validate_exact_file(pointer_path, POINTER_SCHEMA)
    assert pointer["lastAdoptionReceiptId"] == receipt["receiptId"]
    assert [scope_key(row["scope"]) for row in pointer["entries"]] == sorted(
        scope_key(row["scope"]) for row in pointer["entries"]
    )
    assert all(
        row["adoptionReceiptId"] == receipt["receiptId"]
        for row in pointer["entries"]
    )
    assert receipt_path.name == (
        f"capability-entry-receipt-{receipt['receiptId']}.json"
    )
    validate_exact_file(receipt_path, RECEIPT_SCHEMA)


def test_one_bad_predecessor_refuses_the_entire_pointer_transaction(tmp_path: Path) -> None:
    initial = _record("price_revenue")
    adopt_records(
        [initial],
        repository_root=tmp_path,
        entry_schema=ENTRY_SCHEMA,
        pointer_schema=POINTER_SCHEMA,
        receipt_schema=RECEIPT_SCHEMA,
    )
    pointer_path = tmp_path / "contracts/evidence/capability-entry-current.json"
    before = pointer_path.read_bytes()
    bad = _record("price_revenue", predecessor="a" * 64)
    receipt, _ = adopt_records(
        [bad],
        repository_root=tmp_path,
        entry_schema=ENTRY_SCHEMA,
        pointer_schema=POINTER_SCHEMA,
        receipt_schema=RECEIPT_SCHEMA,
    )
    assert receipt["outcome"] == "refused"
    assert receipt["failure"]["reasonCode"] == "PREDECESSOR_MISMATCH"
    assert pointer_path.read_bytes() == before


def test_create_only_collision_refuses_and_emits_receipt(tmp_path: Path) -> None:
    record = _record("price_revenue")
    records_root = tmp_path / "contracts/evidence/capability-entry-records"
    records_root.mkdir(parents=True)
    destination = records_root / f"capability-entry-record-{record['recordId']}.json"
    destination.write_bytes(b"collision")

    receipt, receipt_path = adopt_records(
        [record],
        repository_root=tmp_path,
        entry_schema=ENTRY_SCHEMA,
        pointer_schema=POINTER_SCHEMA,
        receipt_schema=RECEIPT_SCHEMA,
    )

    assert receipt["outcome"] == "refused"
    assert receipt["failure"]["reasonCode"] == "CREATE_ONLY_COLLISION"
    assert receipt["failure"]["failingScope"] == record["scope"]
    assert not (tmp_path / "contracts/evidence/capability-entry-current.json").exists()
    validate_exact_file(receipt_path, RECEIPT_SCHEMA)


def test_recovery_after_pointer_replacement_emits_bound_receipt(tmp_path: Path) -> None:
    with pytest.raises(SimulatedInterruption):
        adopt_records(
            [_record("price_revenue")],
            repository_root=tmp_path,
            entry_schema=ENTRY_SCHEMA,
            pointer_schema=POINTER_SCHEMA,
            receipt_schema=RECEIPT_SCHEMA,
            fail_after="pointer_replaced",
        )
    evidence = tmp_path / "contracts/evidence"
    recovered = recover_pending(
        pointer_path=evidence / "capability-entry-current.json",
        receipts_root=evidence / "capability-entry-receipts",
        journal_root=evidence / ".capability-entry-adoption-staging",
        receipt_schema=RECEIPT_SCHEMA,
    )
    assert len(recovered) == 1
    receipt = validate_exact_file(recovered[0], RECEIPT_SCHEMA)
    assert receipt["outcome"] == "adopted"
    assert receipt["recovery"]["recovered"] is True
    assert not list((evidence / ".capability-entry-adoption-staging").glob("*.json"))


def test_recovery_before_pointer_replacement_records_refusal(tmp_path: Path) -> None:
    with pytest.raises(SimulatedInterruption):
        adopt_records(
            [_record("price_revenue")],
            repository_root=tmp_path,
            entry_schema=ENTRY_SCHEMA,
            pointer_schema=POINTER_SCHEMA,
            receipt_schema=RECEIPT_SCHEMA,
            fail_after="prepared",
        )
    evidence = tmp_path / "contracts/evidence"
    recovered = recover_pending(
        pointer_path=evidence / "capability-entry-current.json",
        receipts_root=evidence / "capability-entry-receipts",
        journal_root=evidence / ".capability-entry-adoption-staging",
        receipt_schema=RECEIPT_SCHEMA,
    )
    receipt = validate_exact_file(recovered[0], RECEIPT_SCHEMA)
    assert receipt["outcome"] == "refused"
    assert receipt["failure"]["reasonCode"] == "INTERRUPTED_BEFORE_ADOPTION"
    assert not (evidence / "capability-entry-current.json").exists()


def test_filename_or_noncanonical_bytes_never_validate(tmp_path: Path) -> None:
    record = _record("price_revenue")
    path = tmp_path / "wrong.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(CapabilityEntryError, match="canonical"):
        validate_exact_file(path, ENTRY_SCHEMA)
