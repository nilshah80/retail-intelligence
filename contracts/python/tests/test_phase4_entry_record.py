"""The Phase 4 entry record must agree with the evidence it cites.

`P4-0`. This record is what a later package reads to decide whether it is
authorized to start, so the failure mode is specific: a record that says "entry
authorized" while one of its own preconditions is unmet authorizes work that
should have been blocked.

The interesting assertions here are the ones that check the record against a
*different* artifact -- the closure record, the selection, the parity contract --
because a self-consistent record proves nothing.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
RECORD = REPO_ROOT / "contracts" / "evidence" / "phase4-entry-record.json"
CLOSURE = REPO_ROOT / "contracts" / "evidence" / "forecast-closure-record.json"


def _record() -> dict:
    if not RECORD.is_file():
        pytest.fail("the Phase 4 entry record is absent; P4-0 cannot have exited")
    return json.loads(RECORD.read_text(encoding="utf-8"))


def _closure() -> dict:
    return json.loads(CLOSURE.read_text(encoding="utf-8"))


def test_the_record_is_generated_not_hand_maintained() -> None:
    record = _record()
    assert record["schemaVersion"] == "retail-phase4-entry-record/v1"
    assert record["generatedBy"] == "tools/build_phase4_entry_record.py"


def test_exactly_one_forecast_authority_is_active() -> None:
    authority = _record()["forecastAuthority"]
    assert authority["activeAuthorityCount"] == 1
    assert authority["lifecycleStatus"] == "accepted"


def test_the_entry_record_and_closure_record_name_the_same_authority() -> None:
    record = _record()
    closure = _closure()
    assert (
        record["forecastAuthority"]["forecastRunId"]
        == closure["acceptedRun"]["forecastRunId"]
    )
    assert (
        record["forecastAuthority"]["versionId"]
        == closure["acceptedRun"]["forecastVersionId"]
    )
    assert record["servingMigration"] == closure["servingMigration"]


def test_the_source_selection_names_the_publication_the_forecast_serves() -> None:
    """A selection for a different publication is not authority for this one."""

    record = _record()
    assert (
        record["sourceSelection"]["publicationSemanticFingerprint"]
        == record["forecastAuthority"]["publicationSemanticFingerprint"]
    )
    assert record["sourceSelection"]["capabilityReadiness"] == "ready"
    assert record["sourceSelection"]["capabilitySufficiency"] == "sufficient"
    assert record["sourceSelection"]["selectionId"].startswith("sel_")
    assert record["sourceSelection"]["activeRecordId"].startswith("rec_")


def test_the_withheld_and_evaluated_populations_are_recorded_separately() -> None:
    """These are different populations. Conflating them turns 86,636 into 8,756."""

    measured = _record()["measured"]
    served = measured["currentCycle"]
    withheld = measured["withheldFromPublication"]
    evaluated = measured["evaluationPopulation"]

    # Serving: the interval and its confidence are withheld as a pair, and P50
    # survives everywhere. A withheld P50 would withdraw a forecast, not a
    # distribution claim.
    assert served["p90NullRows"] == served["confidenceNullRows"], (
        "the interval and its derived confidence must be withheld as a pair"
    )
    assert served["p50NullRows"] == 0
    assert served["distinctUnavailableReasons"] == 1
    assert served["horizonRange"] == [1, 26]
    assert served["distinctHorizons"] == 26

    # Withholding starts strictly after the calibrated range.
    assert withheld["horizonRange"][0] == 5
    assert withheld["rows"] == served["p90NullRows"]
    assert withheld["reasonCode"] == "COLD_START_INTERVAL_UNCALIBRATED"

    # Evaluation retains everything, which is what makes the A2 scoping
    # falsifiable rather than self-fulfilling.
    assert evaluated["p90NullRows"] == 0
    assert evaluated["confidenceNullRows"] == 0


def test_the_authority_ledger_chain_is_recorded_without_a_null_predecessor() -> None:
    ledger = _record()["authorityLedger"]
    assert ledger["currentPriorEventId"] is not None
    # Event 7's incident stays disclosed rather than being edited out.
    assert 7 in ledger["nullPredecessorEventIds"]


def test_an_identity_without_retained_bytes_is_named() -> None:
    """Silence here would let a missing bundle look like a rollback target."""

    ledger = _record()["authorityLedger"]
    closure = _closure()
    expected = [
        entry["forecastRunId"]
        for entry in closure["supersededIdentities"]
        if not entry["bundleBytesRetained"]
    ]
    assert ledger["identitiesWithoutRetainedBytes"] == expected


def test_the_parity_amendment_is_bound_by_fingerprint() -> None:
    """A recorded approval must name the exact bytes it approved."""

    amendment = _record()["parityAmendment"]
    contract = REPO_ROOT / amendment["amendedContractPath"]
    actual = hashlib.sha256(contract.read_bytes()).hexdigest()
    assert actual == amendment["amendedContractSha256"], (
        "the parity contract changed after the amendment was recorded; "
        "regenerate the entry record"
    )
    assert amendment["decisionAmendment"] == "Decision #64 Q19"
    assert "Q19" in amendment["resolvedDecisionQuestions"]
    assert amendment["frozenBehavior"] == {
        "confidence": "unavailable_when_mixed",
        "intervalTotal": "absent_with_governed_reason_when_mixed",
    }


def test_the_amendment_approval_is_classified_honestly() -> None:
    approval = _record()["parityAmendment"]["approval"]
    assert (
        approval["classification"]
        == "autonomous_authorization_not_independent_human_review"
    )
    assert approval["reviewOutstanding"]


def test_rejected_remedies_stay_rejected() -> None:
    """#87's two candidates and #91's C8 may never be described as passing."""

    states = _record()["decisionStates"]
    assert states["87"]["state"] == "closed_both_candidates_rejected"
    assert states["87"]["candidates"] == {"C6": "rejected", "C7": "rejected"}
    assert states["91"]["state"] == "decided_c8_rejected_as_full_range_remedy"
    assert states["91"]["coldStartCoverage"] < states["91"]["floor"], (
        "C8's recorded coverage must remain below the floor it failed"
    )


def test_decision_92_is_not_recorded_as_complete() -> None:
    """The served-field path is live; the contract is not. Both must be visible."""

    record = _record()
    assert (
        record["decisionStates"]["92"]["state"]
        == "decided_served_field_withholding_live_contract_incomplete"
    )
    assert record["decisionStates"]["92"]["remaining"] == "P4-1"
    assert record["decision92Residue"]["handedTo"] == "P4-1"
    assert record["decision92Residue"]["openItems"]


def test_interval_consumers_are_gated_off_at_entry() -> None:
    record = _record()
    assert record["intervalConsumersEnabled"] is False
    assert "P4-1" in record["intervalConsumerGate"]


def test_attested_evidence_is_never_relabelled_as_locally_verified() -> None:
    """Task 10's rule, asserted rather than trusted.

    An attestation without a retained execution artifact is honest evidence. The
    same attestation labelled `locally_verified` is an overclaim that makes the
    missing artifact undiscoverable.
    """

    for name, entry in _record()["openEvidenceClassification"].items():
        if entry["classification"] == "locally_verified":
            assert entry["artifactRetained"] is True, (
                f"{name} claims local verification without a retained artifact"
            )


def test_the_as_built_ordering_disposition_is_recorded() -> None:
    disposition = _record()["p4d0Disposition"]
    assert disposition["state"] == "resolved_by_as_built_ordering"
    assert disposition["sourceOnlyForbids"]
