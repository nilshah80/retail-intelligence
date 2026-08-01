"""The closure record must match the artifact it claims to describe.

No validator covered this record, so `tools/dev.py verify` passed while the record
carried stale artifact hashes, a stale semantic fingerprint, a materialization action
naming a superseded version, an A5 line reporting a failure that had been fixed, the old
input publication, and the current run listed as superseded by itself. Unchecked evidence
is worse than absent evidence: it reads as authoritative.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORD = REPO_ROOT / "contracts" / "evidence" / "forecast-closure-record.json"


def _record() -> dict:
    if not RECORD.is_file():
        pytest.skip("closure record is not present")
    return json.loads(RECORD.read_text(encoding="utf-8"))


def test_closure_record_is_generated_not_hand_maintained() -> None:
    record = _record()
    assert record["schemaVersion"] == "retail-forecast-closure-record/v2"
    assert record["generatedBy"] == "tools/build_closure_record.py"


def test_closure_record_hashes_match_the_bundle_on_disk() -> None:
    record = _record()
    bundle = REPO_ROOT / record["bundlePath"]
    if not bundle.is_dir():
        pytest.skip("the described bundle is not present locally")
    for name, expected in record["artifactHashes"].items():
        actual = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} drifted from the record"


def test_closure_record_identity_matches_the_bundle_manifest() -> None:
    record = _record()
    bundle = REPO_ROOT / record["bundlePath"]
    if not bundle.is_dir():
        pytest.skip("the described bundle is not present locally")
    manifest = json.loads(
        (bundle / "forecast-run-manifest.json").read_text(encoding="utf-8")
    )
    assert record["acceptedRun"]["forecastRunId"] == manifest["forecastRunId"]
    assert (
        record["acceptedRun"]["runSemanticFingerprint"]
        == manifest["semanticFingerprint"]
    )
    assert record["inputBundle"] == manifest["inputBundle"]


def test_the_accepted_run_is_not_listed_as_superseded_by_itself() -> None:
    """The v1 record did exactly this, which is how the contradiction stayed invisible."""

    record = _record()
    current = {
        record["acceptedRun"]["forecastRunId"],
        record["acceptedRun"]["forecastVersionId"],
    }
    superseded = json.dumps(record.get("supersededIdentities", []))
    for identity in current:
        assert identity not in superseded, f"{identity} is both current and superseded"


def test_the_record_describes_a_passing_run_under_the_hard_gate() -> None:
    record = _record()
    acceptance = record["acceptance"]
    assert acceptance["passed"] is True
    assert acceptance["schemaVersion"] == "retail-forecast-acceptance/v5"
    assert acceptance["coverageGateMode"] == "hard"
    # No gate may be recorded as anything other than passing on an accepted run.
    assert all(value is True for value in acceptance["gates"].values())


# --------------------------------------------------------------------------
# `P4-0` / Decision #93. The reconciliation below is what the v2 record was
# missing: it derived its facts from the bundle and the live activation, which
# stopped the drift, and in doing so dropped every fact that lives only in the
# activation ledger. An invariant nobody records is an invariant nobody keeps.
# --------------------------------------------------------------------------


def test_the_current_activation_event_has_a_non_null_predecessor() -> None:
    """Event 7 activated with `prior_event_id = NULL`. Event 9 must not repeat it.

    This is the whole append-only invariant in one assertion: a replacement
    continues from the event it supersedes, so history is a chain rather than a
    set of parallel roots that a most-recent-row tiebreak silently arbitrates.
    """

    ledger = _record()["authorityLedger"]
    assert ledger["currentPriorEventId"] is not None, (
        "the current authority minted a new null-predecessor chain; a replacement "
        "must continue from the event it supersedes"
    )
    events = {event["eventId"]: event for event in ledger["events"]}
    predecessor = events[ledger["currentPriorEventId"]]
    assert predecessor["eventType"] == "superseded", (
        "the current active event must chain to a supersession, not to another "
        "active event"
    )


def test_event_seven_remains_an_immutable_null_predecessor_incident() -> None:
    """The incident is evidence. Editing it to look clean is the forbidden repair."""

    ledger = _record()["authorityLedger"]
    assert 7 in ledger["nullPredecessorEventIds"], (
        "event 7's null-predecessor incident has been edited out of history"
    )
    events = {event["eventId"]: event for event in ledger["events"]}
    assert events[7]["eventType"] == "active"
    assert events[8]["priorEventId"] == 7
    assert events[8]["eventType"] == "superseded"


def test_authority_generation_one_activations_stay_retired() -> None:
    ledger = _record()["authorityLedger"]
    events = {event["eventId"]: event for event in ledger["events"]}
    for active_event, supersession in ((1, 5), (2, 6)):
        assert events[active_event]["eventType"] == "active"
        assert events[supersession]["eventType"] == "superseded"
        assert events[supersession]["priorEventId"] == active_event
        assert events[supersession]["actor"].startswith("migration:")


def test_exactly_one_activation_event_is_current() -> None:
    ledger = _record()["authorityLedger"]
    superseded = {
        event["priorEventId"]
        for event in ledger["events"]
        if event["eventType"] == "superseded"
    }
    current = [
        event["eventId"]
        for event in ledger["events"]
        if event["eventType"] == "active" and event["eventId"] not in superseded
    ]
    assert current == [ledger["currentEventId"]]


def test_the_served_identity_is_never_listed_as_superseded() -> None:
    record = _record()
    served = {
        record["acceptedRun"]["forecastRunId"],
        record["acceptedRun"]["forecastVersionId"],
    }
    for entry in record["supersededIdentities"]:
        assert entry["forecastRunId"] not in served
        assert entry["forecastVersionId"] not in served


def test_a_version_without_bundle_bytes_cannot_be_activated_or_rolled_back_to() -> None:
    """Retained descriptors are historical evidence, not a bundle.

    `fr_9aaa1d4431381570`'s bytes are gone, so it cannot be independently
    re-verified. Listing it as a rollback target would offer a recovery path that
    does not exist.
    """

    for entry in _record()["supersededIdentities"]:
        assert entry["activationEligible"] is False
        if not entry["bundleBytesRetained"]:
            assert entry["rollbackEligible"] is False
            assert entry["bundlePath"] is None


def test_the_historical_attestation_ledger_has_a_governed_disposition() -> None:
    ledger = _record()["historicalAttestationLedger"]
    assert ledger["disposition"] == "retained_by_reference_with_declared_missing_hashes"
    assert ledger["reconstructionForbidden"] is True
    unhashed = ledger["unhashedSupersededSiblings"]
    assert len(unhashed) == 4, "all four deleted C5 siblings must be named exactly once"
    assert len({entry["forecastRunId"] for entry in unhashed}) == 4
    assert all(entry["hashesRetained"] is False for entry in unhashed)
    # Attested evidence must never be relabelled as locally verified.
    classification = ledger["attestationClassification"]
    assert classification["windowsLinuxPortability"] == "user_attested"
    assert classification["trackA"] == "user_attested"


def test_the_decision_92_residue_is_handed_to_p4_1_and_keeps_the_two_operations_apart() -> None:
    """Conflating withholding with gate exclusion is how 86,636 becomes 8,756."""

    residue = _record()["decision92Residue"]
    assert residue["handedTo"] == "P4-1"
    assert residue["openItems"], "the remaining #92 work must be enumerated"
    operations = residue["twoOperationsAreDistinct"]
    assert operations["withheldFromPublication"]["rows"] == 8756
    assert operations["withheldFromPublication"]["series"] == 398
    assert operations["excludedFromOneGateCell"]["rows"] == 86636
    assert (
        operations["excludedFromOneGateCell"]["cell"] == "A2_per_cohort.cold_start"
    )


def test_the_served_aggregate_defect_is_recorded_and_gated() -> None:
    defect = _record()["decision92Residue"]["servedAggregateDefectMeasured"]
    assert defect["gatedBy"] == "P4-0P"
    assert defect["affectedSelections"] == [8, 13, 26]
    assert defect["cleanSelections"] == [4]
    assert defect["servedMeanWeightedConfidence"] < defect[
        "coveredWeekMeanWeightedConfidence"
    ], "the recorded defect must show the served value understating the truth"
