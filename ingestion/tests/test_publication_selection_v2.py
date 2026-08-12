from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from retail_ingestion.readiness.selection import (
    IDENTITY_EXCLUDES_V2,
    SelectionError,
    derive_record_id_v2,
    derive_selection_id_v2,
    resolve_selection_ledger,
    transition_v2,
    validate_selection,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "contracts/onboarding/publication-selection-v2.schema.json"
VECTORS = REPO_ROOT / "contracts/onboarding/publication-selection-golden-vectors.json"


def _golden() -> dict:
    return copy.deepcopy(
        json.loads(VECTORS.read_text(encoding="utf-8"))["vectors"][0]["record"]
    )


def _write(root: Path, name: str, record: dict) -> None:
    (root / name).write_text(json.dumps(record), encoding="utf-8")


def test_v2_golden_vector_is_schema_valid_and_recomputes_both_ids() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    record = _golden()
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(record)
    assert tuple(record["semanticIdentityExcludes"]) == IDENTITY_EXCLUDES_V2
    assert derive_selection_id_v2(record) == record["selectionId"]
    assert derive_record_id_v2(record) == record["lifecycle"]["recordId"]
    validate_selection(record)


def test_v2_identity_ignores_only_the_declared_fields() -> None:
    first = _golden()
    second = copy.deepcopy(first)
    second["approval"]["actor"] = "second-reviewer"
    second["lifecycle"]["state"] = "approved"
    second["selectionId"] = derive_selection_id_v2(second)
    assert second["selectionId"] == first["selectionId"]

    second["scope"]["tenantId"] = "another-tenant"
    assert derive_selection_id_v2(second) != first["selectionId"]


def test_v2_rejects_reordered_or_extra_exclusion_pointers() -> None:
    record = _golden()
    record["semanticIdentityExcludes"] = list(reversed(IDENTITY_EXCLUDES_V2))
    with pytest.raises(SelectionError, match="ordered vector"):
        derive_selection_id_v2(record)


def test_legacy_omission_is_compatible_but_conflicting_explicit_vector_refuses() -> None:
    legacy_path = REPO_ROOT / "contracts/evidence/publication-selections"
    legacy = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(legacy_path.glob("*.json"))
        if json.loads(path.read_text(encoding="utf-8")).get("schemaVersion")
        == "retail-publication-selection/v1"
    )
    legacy.pop("semanticIdentityExcludes", None)
    validate_selection(legacy)
    legacy["semanticIdentityExcludes"] = [
        "approval",
        "selectionId",
        "semanticIdentityExcludes",
    ]
    with pytest.raises(SelectionError, match="conflicting explicit"):
        validate_selection(legacy)


def test_ledger_resolution_uses_exact_full_scope_and_proves_chain(tmp_path: Path) -> None:
    curated = tmp_path / "ingestion/data/curated/run-example"
    curated.mkdir(parents=True)
    ledger = tmp_path / "ledger"
    ledger.mkdir()

    candidate = _golden()
    candidate["lifecycle"] = {
        "state": "candidate",
        "supersedes": None,
        "recordId": "rec_0000000000000000",
        "reasonCode": "SOURCE_VERIFIED",
    }
    candidate["selectionId"] = derive_selection_id_v2(candidate)
    candidate["lifecycle"]["recordId"] = derive_record_id_v2(candidate)
    approved = transition_v2(
        candidate,
        "approved",
        actor="reviewer",
        recorded_at="2026-08-11T00:01:00Z",
        reason="approved",
        evidence_fingerprint="3" * 64,
        reason_code="SOURCE_APPROVED",
    )
    active = transition_v2(
        approved,
        "active",
        actor="reviewer",
        recorded_at="2026-08-11T00:02:00Z",
        reason="active",
        evidence_fingerprint="4" * 64,
        reason_code="SOURCE_ACTIVE",
    )
    _write(ledger, "candidate.json", candidate)
    _write(ledger, "approved.json", approved)
    _write(ledger, "active.json", active)

    resolved = resolve_selection_ledger(
        ledger,
        retailer_id="retailer-demo",
        tenant_id="tenant-demo",
        capability="price_revenue",
        environment="local",
        repository_root=tmp_path,
    )
    assert resolved["lifecycle"]["recordId"] == active["lifecycle"]["recordId"]

    with pytest.raises(SelectionError, match="no selection records for exact scope"):
        resolve_selection_ledger(
            ledger,
            retailer_id="retailer-demo",
            tenant_id="tenant-demo",
            capability="price_revenue",
            environment="dev",
            repository_root=tmp_path,
        )


def test_ledger_resolution_refuses_missing_predecessor(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    active = _golden()
    active["lifecycle"]["supersedes"] = "rec_aaaaaaaaaaaaaaaa"
    active["lifecycle"]["recordId"] = derive_record_id_v2(active)
    _write(ledger, "active.json", active)
    with pytest.raises(SelectionError, match="predecessor .* is absent"):
        resolve_selection_ledger(
            ledger,
            retailer_id="retailer-demo",
            tenant_id="tenant-demo",
            capability="price_revenue",
            environment="local",
            repository_root=tmp_path,
        )
