"""The repin automation must not be able to forge a human approval.

Adoption is now one appended ledger entry instead of five coordinated source edits,
which is a convenience change. These tests pin the part that is NOT a convenience: an
automatic adoption records the policy actor and says so, a human adoption records the
person who supplied it, and neither path can produce a record claiming a review that
did not happen.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "tools" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


selection = _load("build_publication_selection")
dev = _load("dev")


class TestApprovalAttribution:
    def test_automated_actor_is_not_a_person(self) -> None:
        """The sentinel must be obviously non-human at a glance."""

        actor = selection.AUTOMATED_ACTOR
        assert actor.startswith("automated/")
        assert actor != selection.ACTOR

    def test_omitting_actor_records_the_policy_not_a_name(self, tmp_path) -> None:
        original = selection.GENERATIONS_PATH
        scratch = tmp_path / "generations.json"
        scratch.write_text(
            json.dumps({"generations": []}) + "\n", encoding="utf-8"
        )
        selection.GENERATIONS_PATH = scratch
        try:
            entry = selection.append_generation(
                run="run-test",
                approved_at="1970-01-01T00:00:00Z",
                reason_code="TEST",
                candidate_reason="c",
                approved_reason="a",
                active_reason="v",
                supersede_reason="s",
                actor=None,
            )
        finally:
            selection.GENERATIONS_PATH = original
        assert entry["actor"] == selection.AUTOMATED_ACTOR
        assert entry["approvalMode"] == "automatic"
        # The human constant must not leak in through any default.
        assert selection.ACTOR not in json.dumps(entry)

    def test_supplied_actor_is_recorded_verbatim(self, tmp_path) -> None:
        original = selection.GENERATIONS_PATH
        scratch = tmp_path / "generations.json"
        scratch.write_text(json.dumps({"generations": []}) + "\n", encoding="utf-8")
        selection.GENERATIONS_PATH = scratch
        try:
            entry = selection.append_generation(
                run="run-test",
                approved_at="1970-01-01T00:00:00Z",
                reason_code="TEST",
                candidate_reason="c",
                approved_reason="a",
                active_reason="v",
                supersede_reason="s",
                actor="a.person",
            )
        finally:
            selection.GENERATIONS_PATH = original
        assert entry["actor"] == "a.person"
        assert entry["approvalMode"] == "human"

    def test_automatic_reason_discloses_that_nobody_reviewed_it(self) -> None:
        """An auto-adoption must not read as though a person vouched for it."""

        facts = {
            "run": "run-test",
            "gateAStatus": "pass",
            "gateASemanticFingerprint": "a" * 64,
            "gateBSemanticFingerprint": "b" * 64,
            "publicationSemanticFingerprint": "c" * 64,
            "duckdbSha256": "d" * 64,
            "objectCount": 1,
            "businessControlKeys": [],
        }
        automatic = dev._repin_reasons(facts, {}, automatic=True)["candidate"]
        assert "not a human review" in automatic
        human = dev._repin_reasons(facts, {}, automatic=False)["candidate"]
        assert "human approval" in human
        assert "not a human review" not in human


class TestAdoptionRefusals:
    def test_generation_tag_is_derived_never_guessed(self) -> None:
        """A caller inventing the tag is a caller who can collide with history.

        Asserts the PROPERTY -- one past the highest committed tag -- rather than a
        literal. An earlier version of this test asserted `== "r7"` and broke the
        moment an adoption actually happened, which is a test encoding the very
        hand-maintained constant this change exists to remove.
        """

        committed = [
            int(entry["tag"][1:])
            for entry in selection.load_generations()
            if str(entry.get("tag", "")).startswith("r")
        ]
        highest = max([6, *committed])  # r6 is the last hand-written generation
        assert selection.next_generation_tag() == f"r{highest + 1}"

    def test_capability_shortfall_is_refused(self, tmp_path, capsys) -> None:
        """A publication missing a required capability cannot be adopted at all."""

        import argparse

        original = dev._repin_facts
        dev._repin_facts = lambda run_id: {
            "run": run_id,
            "gateAStatus": "pass",  # both gates pass, so the capability check
            "gateBStatus": "pass",  # is what refuses
            "missingRequiredCapabilities": ["inventory_replenishment_replay"],
        }
        try:
            code = dev.command_repin(
                argparse.Namespace(
                    run_id="run-test",
                    approve=True,
                    actor=None,
                    reason=None,
                    reason_code="TEST",
                    approved_at="1970-01-01T00:00:00Z",
                )
            )
        finally:
            dev._repin_facts = original
        assert code == 1
        assert "does not offer every required capability" in capsys.readouterr().err

    def test_human_actor_without_reason_is_refused(self, capsys) -> None:
        """Naming a person without saying why is the shape of a rubber stamp."""

        import argparse

        original = dev._repin_facts
        dev._repin_facts = lambda run_id: {
            "run": run_id,
            "gateAStatus": "pass",
            "gateBStatus": "pass",
            "missingRequiredCapabilities": [],
        }
        try:
            code = dev.command_repin(
                argparse.Namespace(
                    run_id="run-test",
                    approve=True,
                    actor="a.person",
                    reason=None,
                    reason_code="TEST",
                    approved_at="1970-01-01T00:00:00Z",
                )
            )
        finally:
            dev._repin_facts = original
        assert code == 2
        assert "--actor requires --reason" in capsys.readouterr().err


class TestReRunSafety:
    def test_adopting_an_already_selected_run_is_a_no_op(self, capsys) -> None:
        """Re-running an approval must not mint a second generation.

        It did: the pipeline stage checked whether a record already named the run and
        the standalone command did not, so `repin --approve` twice produced duplicate
        candidate/approved/active records sharing one selectionId and broke the
        one-active-per-scope invariant.
        """

        import argparse

        before = len(selection.load_generations())
        code = dev.command_repin(
            argparse.Namespace(
                run_id="run-adac9e85dccb56e8-r6",  # already selected by a record
                approve=True,
                actor=None,
                reason=None,
                reason_code="TEST",
                approved_at=None,
            )
        )
        assert code == 0
        assert "already selected" in capsys.readouterr().out
        assert len(selection.load_generations()) == before

    def test_no_committed_approval_claims_the_epoch(self) -> None:
        """An approval timestamp whose only job is to say when must not say 1970."""

        directory = (
            REPO_ROOT / "contracts" / "evidence" / "publication-selections"
        )
        offenders = [
            path.name
            for path in directory.glob("*.json")
            if (json.loads(path.read_text(encoding="utf-8")).get("approval") or {})
            .get("approvedAt", "")
            .startswith("1970")
        ]
        assert not offenders, f"epoch approval timestamps in {offenders}"

    def test_utc_now_is_rfc3339_zulu(self) -> None:
        stamp = dev._utc_now()
        assert stamp.endswith("Z") and "T" in stamp
        assert not stamp.startswith("1970")


class TestPortability:
    def test_every_selected_run_is_derivable_without_local_bytes(self) -> None:
        """The ledger must verify on a fresh clone, not only where the data is.

        `ingestion/data/` is gitignored, so a run adopted here has no bytes anywhere
        else. r7 named a run that was in neither EVIDENCE_RELEASED_RUNS nor any
        released set, and `--check` consequently failed on macOS, on a fresh clone,
        and on this host the moment it wiped derived data -- while passing here.
        """

        released = set(selection.EVIDENCE_RELEASED_RUNS)
        released |= {str(e.get("run")) for e in selection.load_generations()}
        directory = (
            REPO_ROOT / "contracts" / "evidence" / "publication-selections"
        )
        unreachable = set()
        for path in directory.glob("*.json"):
            record = json.loads(path.read_text(encoding="utf-8"))
            logical = (record.get("publication") or {}).get("logicalPath")
            if not logical:
                continue
            run = logical.rsplit("/", 1)[-1]
            if run not in released:
                unreachable.add(run)
        assert not unreachable, (
            "these runs are named by committed records but are neither declared "
            f"evidence-released nor named by a ledger generation: {sorted(unreachable)}"
        )

    def test_committed_logical_paths_use_forward_slashes(self) -> None:
        """A committed logical path must not carry the writing host's separator."""

        offenders = []
        for path in (REPO_ROOT / "contracts" / "evidence").rglob("*.json"):
            document = json.loads(path.read_text(encoding="utf-8"))

            def walk(node, where=path.name):
                if isinstance(node, dict):
                    for key, value in node.items():
                        if (
                            key.lower().endswith("path")
                            and isinstance(value, str)
                            and "\\" in value
                        ):
                            offenders.append(f"{where}:{key}={value}")
                        walk(value, where)
                elif isinstance(node, list):
                    for item in node:
                        walk(item, where)

            walk(document)
        assert not offenders, f"backslashes in committed logical paths: {offenders}"


class TestCollisionAvoidance:
    def test_an_adopted_run_is_recognised(self) -> None:
        """The check that stops a re-publication overwriting an attested artifact."""

        assert dev._generation_names_run("run-adac9e85dccb56e8-r6")
        assert not dev._generation_names_run("run-does-not-exist")


class TestGateRefusal:
    def test_a_failing_gate_a_is_refused_before_any_record_is_written(
        self, capsys
    ) -> None:
        """A reason string must not be able to say "passed Gate A (fail)"."""

        import argparse

        original = dev._repin_facts
        dev._repin_facts = lambda run_id: {
            "run": run_id,
            "gateAStatus": "fail",
            "gateBStatus": "pass",
            "missingRequiredCapabilities": [],
        }
        try:
            code = dev.command_repin(
                argparse.Namespace(
                    run_id="run-test",
                    approve=True,
                    actor=None,
                    reason=None,
                    reason_code="TEST",
                    approved_at=None,
                )
            )
        finally:
            dev._repin_facts = original
        assert code == 1
        assert "Gate A is 'fail'" in capsys.readouterr().err


class TestEvidenceIsRead:
    def test_gate_b_status_is_read_from_gate_b(self) -> None:
        """Gate B must come from gate-b.json, not the manifest's copy of it.

        `_repin_facts` documented gate-b.json as a source and never opened it: the
        fingerprint and mask came from the manifest, so a missing or failing Gate B
        still produced a confident proposal claiming it passed.
        """

        run = "run-adac9e85dccb56e8-r2"
        evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run
        if not (evidence / "gate-b.json").is_file():
            pytest.skip("no retained evidence on this host")
        facts = dev._repin_facts(run)
        gate_b = json.loads((evidence / "gate-b.json").read_text(encoding="utf-8"))
        assert facts["gateBStatus"] == gate_b["status"]
        assert facts["gateBSemanticFingerprint"] == gate_b["semanticFingerprint"]

    def test_a_failing_gate_b_is_refused(self, capsys) -> None:
        import argparse

        original = dev._repin_facts
        dev._repin_facts = lambda run_id: {
            "run": run_id,
            "gateAStatus": "pass",
            "gateBStatus": "validated_partial",
            "missingRequiredCapabilities": [],
        }
        try:
            code = dev.command_repin(
                argparse.Namespace(
                    run_id="run-test", approve=True, actor=None, reason=None,
                    reason_code="TEST", approved_at=None,
                )
            )
        finally:
            dev._repin_facts = original
        assert code == 1
        assert "Gate B is 'validated_partial'" in capsys.readouterr().err


class TestPinAuthority:
    def test_the_ledger_outranks_retained_evidence(self) -> None:
        """What is pinned is a governed choice, not whichever bytes are on disk.

        A newly published but unadopted run left one retained evidence directory, and
        `--list` then reported that run as "currently pinned" while the pin and every
        active selection still named the previous one.
        """

        pin = _load("build_expected_pin")
        original = pin._promoted_runs
        pin._promoted_runs = lambda: ["run-freshly-published-not-adopted"]
        try:
            assert pin._pinned_run() == pin._fallback_run()
            assert pin._pinned_run() != "run-freshly-published-not-adopted"
        finally:
            pin._promoted_runs = original

    def test_newest_generation_is_the_highest_tag_not_file_order(self) -> None:
        """Two rules for "newest" in adjacent functions eventually disagree."""

        pin = _load("build_expected_pin")
        # Patched on `pin`, not on `selection`: the module does
        # `from build_publication_selection import load_generations`, so the name is
        # bound at import and rebinding the source module would not be seen.
        original = pin.load_generations
        pin.load_generations = lambda: [
            {"tag": "r9", "run": "run-nine"},
            {"tag": "r8", "run": "run-eight"},  # later in file, lower tag
        ]
        try:
            assert pin._fallback_run() == "run-nine"
        finally:
            pin.load_generations = original


class TestEntryRecordPointer:
    def test_active_record_id_resolves_to_a_committed_active_record(self) -> None:
        """The field shipped once naming a record that existed nowhere."""

        record = json.loads(
            (
                REPO_ROOT / "contracts" / "evidence"
                / "inventory-replenishment-entry-record.json"
            ).read_text(encoding="utf-8")
        )
        source = record["sourceSelection"]
        directory = (
            REPO_ROOT / "contracts" / "evidence" / "publication-selections"
        )
        matches = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in directory.glob("*.json")
            if (
                json.loads(path.read_text(encoding="utf-8")).get("lifecycle") or {}
            ).get("recordId") == source["activeRecordId"]
        ]
        assert len(matches) == 1, (
            f"activeRecordId {source['activeRecordId']} matches {len(matches)} "
            "committed records"
        )
        assert matches[0]["selectionId"] == source["selectionId"]
        assert matches[0]["lifecycle"]["state"] == "active"
        assert matches[0]["scope"]["capability"] == "demand_forecast_non_pit"
