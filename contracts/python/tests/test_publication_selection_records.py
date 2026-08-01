"""The serving source pin must have a governed decision-#73 selection.

`P4-0` tasks 4 and 5 created the first chain. Before it, the pin a forecast was
already serving from had been adopted by editing `contracts/ml/expected-pin.json`.
The lifecycle module and the JSON schema both existed; no record did. "Who
approved this publication for this scope" had no answer, and nothing failed,
because nothing looked.

`P4-3` made the directory multi-chain: the ten-year v13 publication is a
different publication and therefore a different selection, the Phase 3 selection
is superseded, and a second capability scope now has its own chain. So the
assertions here are stated over *chains* rather than over file counts -- the
earlier "exactly three records exist" was a property of there being one chain,
not a property decision #73 requires.

The load-bearing assertions are the two a schema cannot make: that currency is
derivable rather than positional, and that the prior ungoverned pin is disclosed
as unselected instead of being back-dated into a supersession it never had.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SELECTION_ROOT = REPO_ROOT / "contracts" / "evidence" / "publication-selections"

PREDECESSOR_SCHEMA = "retail-publication-selection-predecessor/v1"
SELECTION_SCHEMA = "retail-publication-selection/v1"

#: Every capability the repository currently selects a publication for. Exact by
#: intent: an unexpected scope appearing here means someone activated a source
#: authority the contract tests have never reasoned about.
EXPECTED_CAPABILITIES = {
    "demand_forecast_non_pit",
    "inventory_replenishment_replay",
}

#: Mirrors `retail_ingestion.readiness.selection.TERMINAL_STATES` and
#: `ALLOWED_TRANSITIONS`. Restated rather than imported because a contracts test
#: must not depend on the ingestion package; the mirror is kept honest by
#: `test_every_observed_state_is_one_this_test_classifies` below, which fails if a
#: record ever carries a state neither set names.
TERMINAL_STATES = {"superseded", "rejected"}
KNOWN_STATES = {"candidate", "approved", "active"} | TERMINAL_STATES


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


def _chains() -> dict[str, list[dict]]:
    """Selection records grouped by selectionId -- one group per chain."""

    chains: dict[str, list[dict]] = defaultdict(list)
    for record in _selections():
        chains[record["selectionId"]].append(record)
    return dict(chains)


def _current() -> list[dict]:
    """The head of every chain: records nothing supersedes.

    This is the whole reason the directory can hold two records reading
    `state: active` for one scope without ambiguity. Resolving by filename or by
    mtime would be the arbitrary tie-break decision #90 was written against, so
    currency is derived from the supersedes edges and from nothing else.
    """

    selections = _selections()
    superseded = {
        record["lifecycle"]["supersedes"]
        for record in selections
        if record["lifecycle"].get("supersedes")
    }
    return [
        record
        for record in selections
        if record["lifecycle"]["recordId"] not in superseded
    ]


def _scope_tuple(record: dict) -> tuple[str, str, str, str]:
    scope = record["scope"]
    return (
        scope["retailerId"],
        scope["tenantId"],
        scope["capability"],
        scope["environment"],
    )


# -- chain structure -----------------------------------------------------------

def test_every_chain_starts_at_a_candidate_and_reaches_an_active_state() -> None:
    """A file replacement is not a selection; the approval events must exist."""

    for selection_id, chain in _chains().items():
        states = [record["lifecycle"]["state"] for record in chain]
        assert "candidate" in states, f"{selection_id} has no candidate record"
        assert "approved" in states, f"{selection_id} has no approved record"
        assert "active" in states, (
            f"{selection_id} was never activated; decision #93 requires the full "
            "candidate -> approved -> active lifecycle"
        )


def test_every_record_in_a_chain_shares_that_chains_selection_id() -> None:
    """The selection id answers *what* is selected and must not move per state."""

    for selection_id, chain in _chains().items():
        assert {record["selectionId"] for record in chain} == {selection_id}


def test_lifecycle_record_ids_are_distinct_and_chained_within_each_chain() -> None:
    for selection_id, chain in _chains().items():
        by_state = {record["lifecycle"]["state"]: record for record in chain}
        record_ids = {
            state: record["lifecycle"]["recordId"]
            for state, record in by_state.items()
        }
        assert len(set(record_ids.values())) == len(chain), (
            f"{selection_id}: each approval event needs its own recordId, "
            f"found {record_ids}"
        )
        assert by_state["candidate"]["lifecycle"]["supersedes"] is None
        assert (
            by_state["approved"]["lifecycle"]["supersedes"]
            == record_ids["candidate"]
        )
        assert by_state["active"]["lifecycle"]["supersedes"] == record_ids["approved"]
        if "superseded" in by_state:
            assert (
                by_state["superseded"]["lifecycle"]["supersedes"]
                == record_ids["active"]
            ), "a supersession must chain to the active record it retires"


def test_no_record_supersedes_a_record_id_that_does_not_exist() -> None:
    """Fabricating a predecessor would make an ungoverned pin look governed."""

    known = {record["lifecycle"]["recordId"] for record in _selections()}
    for record in _selections():
        supersedes = record["lifecycle"]["supersedes"]
        if supersedes is None:
            continue
        assert supersedes in known, (
            f"{supersedes} is not a recordId anywhere in this directory"
        )


# -- currency ------------------------------------------------------------------

def test_exactly_one_live_current_record_per_scope() -> None:
    """Decision #73's core invariant, asserted over derived currency.

    Two files reading `state: active` for one scope is expected once a re-pin has
    happened -- history is not deleted. And a re-pinned scope has two chain HEADS:
    the retired chain ends at `superseded`, the new one at `active`. Neither fact
    is a conflict, so the invariant is over LIVE heads: at most one non-terminal
    current record per scope, and every other head for that scope must be
    terminal. Anything else means "which publication does this scope use" has two
    answers and the resolver would be choosing arbitrarily.
    """

    by_scope: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for record in _current():
        by_scope[_scope_tuple(record)].append(record)
    for scope, records in by_scope.items():
        live = [
            record
            for record in records
            if record["lifecycle"]["state"] not in TERMINAL_STATES
        ]
        assert len(live) == 1, (
            f"scope {'/'.join(scope)} has {len(live)} live current records: "
            f"{[r['selectionId'] for r in live]}"
        )
        assert live[0]["lifecycle"]["state"] == "active", (
            f"scope {'/'.join(scope)} resolves to a "
            f"{live[0]['lifecycle']['state']} record, which serves nothing"
        )


def test_every_observed_state_is_one_this_test_classifies() -> None:
    """TERMINAL_STATES is a local mirror, so a new lifecycle state must not slip
    past the currency check by being neither terminal nor recognised."""

    observed = {record["lifecycle"]["state"] for record in _selections()}
    assert observed <= KNOWN_STATES, (
        f"unclassified lifecycle states {sorted(observed - KNOWN_STATES)}; "
        "decide whether they are terminal before trusting the currency check"
    )


def test_the_current_record_for_a_live_scope_is_active_not_superseded() -> None:
    live = {
        _scope_tuple(record)[2]: record
        for record in _current()
        if record["lifecycle"]["state"] == "active"
    }
    assert set(live) == EXPECTED_CAPABILITIES, (
        f"active capabilities are {sorted(live)}, expected "
        f"{sorted(EXPECTED_CAPABILITIES)}"
    )


def test_a_superseded_record_names_its_replacement_in_its_approval_reason() -> None:
    """`additionalProperties: false` leaves no field for a forward pointer, and
    anything outside IDENTITY_EXCLUDES would change what was selected. The audit
    reason is the one place it can live, so it must actually be used."""

    live_ids = {
        record["selectionId"]
        for record in _current()
        if record["lifecycle"]["state"] == "active"
    }
    superseded = [
        record
        for record in _selections()
        if record["lifecycle"]["state"] == "superseded"
    ]
    for record in superseded:
        reason = record["approval"]["reason"]
        assert any(selection_id in reason for selection_id in live_ids), (
            f"superseded selection {record['selectionId']} does not name the "
            f"active selection that replaced it: {reason!r}"
        )


# -- binding to what is actually served ---------------------------------------

def test_the_forecast_selection_binds_the_publication_the_ml_pin_names() -> None:
    """The selection is only authority if it names the same bytes as the ML pin."""

    active = {
        _scope_tuple(record)[2]: record
        for record in _current()
        if record["lifecycle"]["state"] == "active"
    }
    pin = json.loads(
        (REPO_ROOT / "contracts" / "ml" / "expected-pin.json").read_text(
            encoding="utf-8"
        )
    )
    publication = active["demand_forecast_non_pit"]["publication"]
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


def test_every_pinned_capability_has_an_active_selection_on_the_pinned_bytes() -> None:
    """The pin claims capabilities; each claim needs its own approved authority.

    A pin requiring `inventory_replenishment_replay` while only the forecast
    scope had a selection would let Phase 4 consume a publication nobody approved
    for it.
    """

    pin = json.loads(
        (REPO_ROOT / "contracts" / "ml" / "expected-pin.json").read_text(
            encoding="utf-8"
        )
    )
    active = {
        _scope_tuple(record)[2]: record
        for record in _current()
        if record["lifecycle"]["state"] == "active"
    }
    for capability in pin["requiredCapabilities"]:
        assert capability in active, (
            f"the pin requires {capability} but no selection is active for it"
        )
        publication = active[capability]["publication"]
        assert publication["sourceSnapshotId"] == pin["sourceSnapshotId"]
        assert (
            publication["publicationSemanticFingerprint"]
            == pin["publication"]["semanticFingerprint"]
        )


def test_the_selected_publications_are_present_and_match_retained_evidence() -> None:
    for record in _current():
        if record["lifecycle"]["state"] != "active":
            continue
        logical = REPO_ROOT / record["publication"]["logicalPath"]
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
        publication = record["publication"]
        assert (
            publication["publicationSemanticFingerprint"]
            == manifest["semanticFingerprint"]
        )
        assert publication["objectCount"] == len(manifest["objects"])


def test_every_active_selection_is_ready_and_sufficient() -> None:
    for record in _current():
        if record["lifecycle"]["state"] != "active":
            continue
        readiness = record["readiness"]
        assert readiness["capabilityReadiness"] == "ready", (
            f"{record['selectionId']} is active but not ready"
        )
        assert readiness["capabilitySufficiency"] == "sufficient", (
            f"{record['selectionId']} is active on insufficient evidence"
        )


def test_scopes_are_the_ones_this_repository_reasons_about() -> None:
    for record in _selections():
        retailer, tenant, capability, environment = _scope_tuple(record)
        assert (retailer, tenant, environment) == (
            "retailer-demo",
            "tenant-demo",
            "local",
        )
        assert capability in EXPECTED_CAPABILITIES, (
            f"{record['selectionId']} selects for {capability}, which no contract "
            "test reasons about"
        )


# -- the pre-Phase-3 pin, which never had a selection at all -------------------

def test_the_prior_ungoverned_pin_is_disclosed_as_unselected() -> None:
    predecessors = [
        record
        for record in _records()
        if record.get("schemaVersion") == PREDECESSOR_SCHEMA
    ]
    assert len(predecessors) == 1, (
        "the pin that had no selection record must be disclosed exactly once"
    )
    predecessor = predecessors[0]
    assert predecessor["classification"] == "legacy_unselected_predecessor"
    assert predecessor["selectionRecordExists"] is False
    assert predecessor["bytesRetained"] is False


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
