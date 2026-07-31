"""PP3-A7 deliverable A-D9: tenant publication selection and lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from retail_ingestion.readiness.selection import (
    IDENTITY_EXCLUDES,
    SelectionError,
    assert_one_active_per_scope,
    derive_selection_id,
    resolve_selection,
    rollback,
    semantic_identity,
    transition,
    validate_selection,
    verify_against_publication,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = REPO_ROOT / "contracts/onboarding/publication-selection.schema.json"
HEX = "a" * 64


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _selection(**overrides) -> dict:
    selection = {
        "schemaVersion": "retail-publication-selection/v1",
        "scope": {
            "retailerId": "acme-grocers",
            "tenantId": "acme-uk",
            "capability": "demand_forecast_non_pit",
            "environment": "local",
        },
        "lifecycle": {"state": "active", "supersedes": None},
        "publication": {
            "sourceSnapshotId": HEX,
            "gateASemanticFingerprint": "b" * 64,
            "gateBSemanticFingerprint": "c" * 64,
            "publicationSemanticFingerprint": "d" * 64,
            "logicalPath": "ingestion/data/curated/run-c5eb1506ecd4c550",
            "objectCount": 1509,
        },
        "readiness": {
            "reportFingerprint": "e" * 64,
            "capabilityReadiness": "ready",
            "capabilitySufficiency": "sufficient",
        },
        "approval": {
            "actor": "reviewer",
            "approvedAt": "2026-07-31T00:00:00Z",
            "reason": "round-trip accepted",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(selection.get(key), dict):
            selection[key] = {**selection[key], **value}
        else:
            selection[key] = value
    selection["selectionId"] = derive_selection_id(selection)
    return selection


def test_a_selection_validates_against_the_schema(
    validator: Draft202012Validator,
) -> None:
    validator.validate(_selection())
    validate_selection(_selection())


def test_approval_metadata_is_outside_semantic_identity() -> None:
    """Re-approving the same publication must not mint a different selection."""

    first = _selection()
    second = _selection(
        approval={
            "actor": "someone-else",
            "approvedAt": "2026-08-01T00:00:00Z",
            "reason": "re-approved",
        }
    )
    assert semantic_identity(first) == semantic_identity(second)
    assert first["selectionId"] == second["selectionId"]
    assert "approval" in IDENTITY_EXCLUDES


def test_changing_the_publication_changes_identity() -> None:
    other = _selection(publication={"publicationSemanticFingerprint": "f" * 64})
    assert semantic_identity(other) != semantic_identity(_selection())


def test_a_tampered_selection_id_fails_closed() -> None:
    selection = _selection()
    selection["selectionId"] = "sel_0000000000000000"
    with pytest.raises(SelectionError, match="does not match its semantic identity"):
        validate_selection(selection)


def test_two_active_selections_for_one_scope_fail_closed() -> None:
    first = _selection()
    second = _selection(publication={"objectCount": 1510})
    with pytest.raises(SelectionError, match="two active selections"):
        assert_one_active_per_scope([first, second])

    # Different capability is a different scope, so both may be active.
    other_scope = _selection(scope={"capability": "current_descriptive_analytics"})
    assert_one_active_per_scope([first, other_scope])


@pytest.mark.parametrize(
    ("state", "target"),
    [
        ("candidate", "active"),
        ("active", "approved"),
        ("superseded", "active"),
        ("rejected", "approved"),
    ],
)
def test_illegal_lifecycle_transitions_fail_closed(state: str, target: str) -> None:
    selection = _selection(lifecycle={"state": state, "supersedes": None})
    with pytest.raises(SelectionError, match="illegal transition"):
        transition(selection, target, actor="reviewer", reason="nope")


def test_the_lifecycle_walks_candidate_to_active() -> None:
    candidate = _selection(lifecycle={"state": "candidate", "supersedes": None})
    approved = transition(candidate, "approved", actor="reviewer", reason="ok")
    active = transition(approved, "active", actor="reviewer", reason="activate")

    assert approved["lifecycle"]["state"] == "approved"
    assert active["lifecycle"]["state"] == "active"
    # The originals are untouched: each step is a new record.
    assert candidate["lifecycle"]["state"] == "candidate"

    # What is selected never changed, so the selection id is stable...
    assert candidate["selectionId"] == approved["selectionId"] == active[
        "selectionId"
    ]
    # ...while each approval event has its own record id and supersedes chain.
    record_ids = {
        approved["lifecycle"]["recordId"],
        active["lifecycle"]["recordId"],
    }
    assert len(record_ids) == 2
    assert active["lifecycle"]["supersedes"] == approved["lifecycle"]["recordId"]


def test_rollback_creates_records_and_never_edits_history() -> None:
    previous = _selection(publication={"objectCount": 1400})
    active = _selection()

    retired, reinstated = rollback(
        active, previous, actor="reviewer", reason="regression"
    )

    assert retired["lifecycle"]["state"] == "superseded"
    assert retired["lifecycle"]["reasonCode"] == "ROLLBACK"
    assert reinstated["lifecycle"]["state"] == "active"
    assert reinstated["lifecycle"]["supersedes"] == retired["lifecycle"]["recordId"]
    # The originals are untouched.
    assert active["lifecycle"]["state"] == "active"
    assert previous["lifecycle"]["state"] == "active"


def test_rollback_refuses_a_different_scope() -> None:
    active = _selection()
    other = _selection(scope={"tenantId": "acme-de"})
    with pytest.raises(SelectionError, match="share the active scope"):
        rollback(active, other, actor="reviewer", reason="wrong tenant")


# ---------------------------------------------------------------------------
# Resolution fails closed; there is no "latest".
# ---------------------------------------------------------------------------
def _write(tmp_path: Path, selection: dict) -> Path:
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    return path


def _resolve(path: Path, **overrides):
    kwargs = {
        "retailer_id": "acme-grocers",
        "tenant_id": "acme-uk",
        "capability": "demand_forecast_non_pit",
        "environment": "local",
        "repository_root": REPO_ROOT,
    }
    kwargs.update(overrides)
    return resolve_selection(path, **kwargs)


def test_an_active_ready_sufficient_selection_resolves(tmp_path: Path) -> None:
    resolved = _resolve(_write(tmp_path, _selection()))
    assert resolved["scope"]["tenantId"] == "acme-uk"


def test_a_missing_selection_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="is absent"):
        _resolve(tmp_path / "nope.json")


def test_a_scope_mismatch_fails_closed(tmp_path: Path) -> None:
    path = _write(tmp_path, _selection())
    with pytest.raises(SelectionError, match="does not match requested"):
        _resolve(path, tenant_id="acme-de")


def test_a_non_active_selection_fails_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _selection(lifecycle={"state": "approved", "supersedes": None})
    )
    with pytest.raises(SelectionError, match="not active"):
        _resolve(path)


def test_an_under_capable_selection_fails_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _selection(readiness={"capabilityReadiness": "validated_partial"})
    )
    with pytest.raises(SelectionError, match="not ready"):
        _resolve(path)


def test_insufficient_evidence_fails_closed_unless_waived(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _selection(readiness={"capabilitySufficiency": "insufficient_evidence"}),
    )
    with pytest.raises(SelectionError, match="sufficiency is"):
        _resolve(path)

    # A diagnostic caller may waive sufficiency explicitly, never implicitly.
    assert _resolve(path, require_sufficient=False)["readiness"][
        "capabilitySufficiency"
    ] == "insufficient_evidence"


def test_a_moved_publication_fails_closed(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _selection(publication={"logicalPath": "ingestion/data/curated/gone"})
    )
    with pytest.raises(SelectionError, match="moved or is absent"):
        _resolve(path)


def test_selection_verifies_against_the_real_publication_manifest() -> None:
    """The demo pin remains expressible as a selection."""

    manifest = json.loads(
        (
            REPO_ROOT
            / "ingestion/data/curated/run-c5eb1506ecd4c550/publication-manifest.json"
        ).read_text(encoding="utf-8")
    )
    selection = _selection(
        publication={
            "sourceSnapshotId": manifest["sourceSnapshotId"],
            "gateBSemanticFingerprint": manifest["gateBSemanticFingerprint"],
            "publicationSemanticFingerprint": manifest["semanticFingerprint"],
            "objectCount": len(manifest["objects"]),
        }
    )
    verify_against_publication(selection, manifest)

    drifted = _selection(
        publication={
            "sourceSnapshotId": manifest["sourceSnapshotId"],
            "gateBSemanticFingerprint": manifest["gateBSemanticFingerprint"],
            "publicationSemanticFingerprint": "0" * 64,
            "objectCount": len(manifest["objects"]),
        }
    )
    with pytest.raises(SelectionError, match="publicationSemanticFingerprint mismatch"):
        verify_against_publication(drifted, manifest)


def test_object_count_drift_fails_closed() -> None:
    manifest = json.loads(
        (
            REPO_ROOT
            / "ingestion/data/curated/run-c5eb1506ecd4c550/publication-manifest.json"
        ).read_text(encoding="utf-8")
    )
    selection = _selection(
        publication={
            "sourceSnapshotId": manifest["sourceSnapshotId"],
            "gateBSemanticFingerprint": manifest["gateBSemanticFingerprint"],
            "publicationSemanticFingerprint": manifest["semanticFingerprint"],
            "objectCount": len(manifest["objects"]) - 1,
        }
    )
    with pytest.raises(SelectionError, match="object count mismatch"):
        verify_against_publication(selection, manifest)


def test_there_is_no_latest_resolution() -> None:
    """Resolution takes an explicit path; no search or newest-wins exists."""

    import ast
    import inspect

    from retail_ingestion.readiness import selection as module

    tree = ast.parse(inspect.getsource(module))
    # Strip docstrings so prose describing the rule cannot satisfy or break it.
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                node.body = body[1:]
    code = ast.unparse(tree)

    for forbidden in ("glob(", "iterdir(", "rglob(", "listdir(", "latest"):
        assert forbidden not in code, forbidden
    # resolve_selection takes one explicit path and no scan.
    signature = inspect.signature(module.resolve_selection)
    assert "path" in signature.parameters
