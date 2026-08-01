"""The serving source pin must have a governed decision-#73 selection.

`P4-0` tasks 4 and 5. Before this, the pin a forecast was already serving from had
been adopted by editing `contracts/ml/expected-pin.json`. The lifecycle module and
the JSON schema both existed; no record did. "Who approved this publication for
this scope" had no answer, and nothing failed, because nothing looked.

These tests assert the two things a schema cannot: that the lifecycle is a real
chain rather than three unrelated files, and that the prior ungoverned pin is
disclosed as unselected instead of being back-dated into a supersession it never
had.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTION_ROOT = REPO_ROOT / "contracts" / "evidence" / "publication-selections"

PREDECESSOR_SCHEMA = "retail-publication-selection-predecessor/v1"
SELECTION_SCHEMA = "retail-publication-selection/v1"


def _records() -> list[dict]:
    if not SELECTION_ROOT.is_dir():
        pytest.fail("no decision-#73 publication selection directory exists")
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SELECTION_ROOT.glob("*.json"))
    ]


def _selections() -> list[dict]:
    return [
        record
        for record in _records()
        if record.get("schemaVersion") == SELECTION_SCHEMA
    ]


def _by_state() -> dict[str, dict]:
    return {
        record["lifecycle"]["state"]: record for record in _selections()
    }


def test_the_full_candidate_approved_active_lifecycle_exists() -> None:
    states = _by_state()
    assert set(states) == {"candidate", "approved", "active"}, (
        "decision #93 requires all three lifecycle records; a file replacement "
        "is not a selection"
    )


def test_the_three_records_share_one_selection_id() -> None:
    """The selection id answers *what* is selected and must not move per state."""

    selection_ids = {record["selectionId"] for record in _selections()}
    assert len(selection_ids) == 1, (
        f"lifecycle records must share one selectionId, found {selection_ids}"
    )


def test_the_lifecycle_record_ids_are_distinct_and_chained() -> None:
    states = _by_state()
    record_ids = {
        state: record["lifecycle"]["recordId"] for state, record in states.items()
    }
    assert len(set(record_ids.values())) == 3, (
        f"each approval event needs its own recordId, found {record_ids}"
    )
    assert states["candidate"]["lifecycle"]["supersedes"] is None
    assert (
        states["approved"]["lifecycle"]["supersedes"] == record_ids["candidate"]
    )
    assert states["active"]["lifecycle"]["supersedes"] == record_ids["approved"]


def test_the_selection_binds_the_publication_the_forecast_actually_serves() -> None:
    """The selection is only authority if it names the same bytes as the ML pin."""

    active = _by_state()["active"]
    pin = json.loads(
        (REPO_ROOT / "contracts" / "ml" / "expected-pin.json").read_text(
            encoding="utf-8"
        )
    )
    publication = active["publication"]
    assert publication["sourceSnapshotId"] == pin["sourceSnapshotId"]
    assert (
        publication["gateASemanticFingerprint"]
        == pin["gateA"]["semanticFingerprint"]
    )
    assert (
        publication["gateBSemanticFingerprint"]
        == pin["gateB"]["semanticFingerprint"]
    )
    assert (
        publication["publicationSemanticFingerprint"]
        == pin["publication"]["semanticFingerprint"]
    )
    assert publication["objectCount"] == pin["publication"]["objectCount"]
    assert publication["duckdbSha256"] == pin["publication"]["duckdb"]["sha256"]


def test_the_selected_publication_is_present_on_disk() -> None:
    active = _by_state()["active"]
    logical = REPO_ROOT / active["publication"]["logicalPath"]
    if not logical.exists():
        pytest.skip("the selected publication is not present on this host")
    manifest_path = (
        REPO_ROOT
        / "ingestion"
        / "data"
        / "evidence"
        / logical.name
        / "publication-manifest.json"
    )
    if not manifest_path.is_file():
        pytest.skip("retained publication manifest is not present on this host")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    publication = active["publication"]
    assert publication["publicationSemanticFingerprint"] == manifest[
        "semanticFingerprint"
    ]
    assert publication["objectCount"] == len(manifest["objects"])


def test_the_capability_scope_matches_what_phase_3_serves() -> None:
    active = _by_state()["active"]
    assert active["scope"] == {
        "retailerId": "retailer-demo",
        "tenantId": "tenant-demo",
        "capability": "demand_forecast_non_pit",
        "environment": "local",
    }
    readiness = active["readiness"]
    assert readiness["capabilityReadiness"] == "ready"
    assert readiness["capabilitySufficiency"] == "sufficient"


def test_the_prior_pin_is_disclosed_as_unselected_not_superseded() -> None:
    """Fabricating a supersession would make an ungoverned pin look governed."""

    predecessors = [
        record
        for record in _records()
        if record.get("schemaVersion") == PREDECESSOR_SCHEMA
    ]
    assert len(predecessors) == 1, (
        "the pin this publication replaced must be disclosed exactly once"
    )
    predecessor = predecessors[0]
    assert predecessor["classification"] == "legacy_unselected_predecessor"
    assert predecessor["selectionRecordExists"] is False
    assert predecessor["bytesRetained"] is False
    # No lifecycle record may claim to supersede a recordId that never existed.
    for record in _selections():
        supersedes = record["lifecycle"]["supersedes"]
        if supersedes is None:
            continue
        assert supersedes in {
            other["lifecycle"]["recordId"] for other in _selections()
        }, f"{supersedes} is not a recordId in this lifecycle"


def test_the_predecessor_disclosure_points_at_its_equivalence_evidence() -> None:
    """Equivalence rests on retained control totals, not on retained artifacts."""

    predecessor = next(
        record
        for record in _records()
        if record.get("schemaVersion") == PREDECESSOR_SCHEMA
    )
    evidence = REPO_ROOT / predecessor["equivalenceEvidence"]
    assert evidence.is_file(), (
        f"{predecessor['equivalenceEvidence']} is referenced but absent; a "
        "predecessor whose bytes are gone needs its equivalence evidence retained"
    )
