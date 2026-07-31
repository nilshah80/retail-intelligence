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
