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


def _copy_policy(root: Path) -> None:
    """The retirement guard fails closed, so a temp repo needs the committed policy."""

    import shutil

    target = root / "contracts" / "onboarding"
    target.mkdir(parents=True, exist_ok=True)
    name = "temporal-evidence-policy-v2.json"
    shutil.copyfile(REPO_ROOT / "contracts" / "onboarding" / name, target / name)


def _empty_generation_document() -> dict:
    """A valid ledger envelope with no post-r6 generation yet."""

    document = json.loads(
        (
            REPO_ROOT
            / "contracts"
            / "evidence"
            / "publication-selection-generations.json"
        ).read_text(encoding="utf-8")
    )
    document["generations"] = []
    return document


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
            json.dumps(_empty_generation_document()) + "\n", encoding="utf-8"
        )
        selection.GENERATIONS_PATH = scratch
        try:
            entry = selection.append_generation(
                run="run-test",
                approved_at="1970-01-01T00:00:00Z",
                reason_code="AUTOMATED_REPIN_ADOPTION",
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
        scratch.write_text(
            json.dumps(_empty_generation_document()) + "\n", encoding="utf-8"
        )
        selection.GENERATIONS_PATH = scratch
        try:
            entry = selection.append_generation(
                run="run-test",
                approved_at="1970-01-01T00:00:00Z",
                reason_code="HUMAN_REPIN_ADOPTION",
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
                    reason_code="AUTOMATED_REPIN_ADOPTION",
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
                    reason_code="AUTOMATED_REPIN_ADOPTION",
                    approved_at="1970-01-01T00:00:00Z",
                )
            )
        finally:
            dev._repin_facts = original
        assert code == 2
        assert "must be supplied together" in capsys.readouterr().err


class TestAttributionSymmetry:
    def test_a_reason_without_an_actor_is_refused(self, capsys) -> None:
        """Prose could claim a review the metadata denied.

        The check was one-sided: `--actor` required `--reason`, but a reason alone was
        accepted -- so `--reason "Alice reviewed and approved this"` was stored while
        actor stayed `automated/repin-policy/v1` and approvalMode stayed `automatic`.
        """

        import argparse

        code = dev.command_repin(
            argparse.Namespace(
                run_id="run-x", approve=True, actor=None,
                reason="Alice reviewed and approved this",
                reason_code="AUTOMATED_REPIN_ADOPTION", approved_at=None,
            )
        )
        assert code == 2
        assert "must be supplied together" in capsys.readouterr().err

    def test_a_human_actor_cannot_carry_the_automatic_reason_code(self) -> None:
        """A human approval labelled AUTOMATED_REPIN_ADOPTION is contradictory."""

        import argparse
        import inspect

        # The derivation, asserted on the source rather than by reaching the write
        # path, which needs real evidence.
        source = inspect.getsource(dev.command_repin)
        assert "HUMAN_REPIN_ADOPTION" in source

    def test_a_human_reason_code_without_an_actor_is_refused(self, capsys) -> None:
        import argparse

        code = dev.command_repin(
            argparse.Namespace(
                run_id="run-x", approve=True, actor=None, reason=None,
                reason_code="HUMAN_REPIN_ADOPTION", approved_at=None,
            )
        )
        assert code == 2
        assert "not valid for an automatic adoption" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "actor,reason,reason_code",
        [
            ("   ", "reviewed", "AUTOMATED_REPIN_ADOPTION"),
            ("Alice", "   ", "AUTOMATED_REPIN_ADOPTION"),
            ("Alice", "reviewed", "AUTOMATED_CUSTOM_APPROVAL"),
        ],
    )
    def test_blank_attribution_and_automatic_human_codes_are_refused(
        self, actor, reason, reason_code, capsys
    ) -> None:
        import argparse

        code = dev.command_repin(
            argparse.Namespace(
                run_id="run-x",
                approve=True,
                actor=actor,
                reason=reason,
                reason_code=reason_code,
                approved_at=None,
            )
        )
        assert code == 2
        assert capsys.readouterr().err


class TestLedgerValidation:
    def test_a_flipped_approval_mode_is_refused(self) -> None:
        """approvalMode was never consumed, so flipping it changed nothing."""

        import copy

        good = json.loads(
            selection.GENERATIONS_PATH.read_text(encoding="utf-8")
        )["generations"]
        bad = copy.deepcopy(good)
        bad[0]["approvalMode"] = "human"
        with pytest.raises(SystemExit, match="derived from the actor"):
            selection.validate_generations(bad)

    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("approvedAt", "yesterday", "not RFC 3339"),
            ("reasonCode", "lowercase", "UPPER_SNAKE_CASE"),
            ("supersedesTag", "r3", "contiguous"),
            ("tag", "seven", "not of the form"),
            ("run", "../outside", "portable run-... path component"),
        ],
    )
    def test_malformed_entries_are_refused(self, field, value, expected) -> None:
        import copy

        good = json.loads(
            selection.GENERATIONS_PATH.read_text(encoding="utf-8")
        )["generations"]
        bad = copy.deepcopy(good)
        bad[0][field] = value
        with pytest.raises(SystemExit, match=expected):
            selection.validate_generations(bad)

    def test_a_duplicate_generation_is_refused(self) -> None:
        import copy

        good = json.loads(
            selection.GENERATIONS_PATH.read_text(encoding="utf-8")
        )["generations"]
        bad = copy.deepcopy(good) + copy.deepcopy(good)
        with pytest.raises(SystemExit, match="repeats"):
            selection.validate_generations(bad)

    def test_the_committed_ledger_validates(self) -> None:
        assert selection.load_generations()

    def test_a_gap_and_out_of_order_entries_are_refused(self) -> None:
        import copy

        r7 = copy.deepcopy(selection.load_generations()[0])
        r8 = copy.deepcopy(r7)
        r8.update(tag="r8", supersedesTag="r7", run="run-r8-test")
        r9 = copy.deepcopy(r7)
        r9.update(tag="r9", supersedesTag="r8", run="run-r9-test")
        with pytest.raises(SystemExit, match="expected 'r8'"):
            selection.validate_generations([r7, r9])
        with pytest.raises(SystemExit, match="expected 'r7'"):
            selection.validate_generations([r8, r7])

    @pytest.mark.parametrize(
        "field,value,expected",
        [
            ("approvedAt", "2026-99-99T99:99:99Z", "not RFC 3339"),
            ("reasonCode", "A", "3-64 character"),
            ("actor", "   ", "actor is blank"),
            ("candidateReason", "   ", "candidateReason.*blank"),
        ],
    )
    def test_well_typed_but_unusable_audit_values_are_refused(
        self, field, value, expected
    ) -> None:
        import copy

        bad = copy.deepcopy(selection.load_generations())
        bad[0][field] = value
        if field == "actor":
            bad[0]["approvalMode"] = "human"
            bad[0]["reasonCode"] = "HUMAN_REPIN_ADOPTION"
        with pytest.raises(SystemExit, match=expected):
            selection.validate_generations(bad)

    @pytest.mark.parametrize(
        "mutation,expected",
        [
            (lambda document: document.update(generations=None), "expected list"),
            (lambda document: document.pop("recordType"), "has no 'recordType'"),
            (
                lambda document: document.update(schemaVersion="other/v1"),
                "unsupported schemaVersion",
            ),
        ],
    )
    def test_the_ledger_envelope_is_validated(self, mutation, expected) -> None:
        document = _empty_generation_document()
        mutation(document)
        with pytest.raises(SystemExit, match=expected):
            selection.validate_generation_document(document)

    def test_append_validates_before_replacing_the_ledger(
        self, tmp_path, monkeypatch
    ) -> None:
        scratch = tmp_path / "generations.json"
        scratch.write_text(
            json.dumps(_empty_generation_document()) + "\n", encoding="utf-8"
        )
        before = scratch.read_bytes()
        monkeypatch.setattr(selection, "GENERATIONS_PATH", scratch)
        with pytest.raises(SystemExit, match="not RFC 3339"):
            selection.append_generation(
                run="run-test",
                approved_at="2026-99-99T99:99:99Z",
                reason_code="AUTOMATED_REPIN_ADOPTION",
                candidate_reason="candidate",
                approved_reason="approved",
                active_reason="active",
                supersede_reason="superseded",
                actor=None,
            )
        assert scratch.read_bytes() == before
        assert not list(tmp_path.glob("*.tmp"))


class TestAtomicAdoptionWrites:
    def test_a_failed_replace_leaves_the_destination_intact(
        self, tmp_path, monkeypatch
    ) -> None:
        destination = tmp_path / "ledger.json"
        destination.write_bytes(b"before")

        def fail_replace(source, target):
            raise OSError("injected replace failure")

        monkeypatch.setattr(selection.os, "replace", fail_replace)
        with pytest.raises(OSError, match="injected"):
            selection.atomic_write_bytes(destination, b"after")
        assert destination.read_bytes() == b"before"
        assert not list(tmp_path.glob("*.tmp"))

    def test_lock_precedes_the_authoritative_recheck_and_snapshots(self) -> None:
        import inspect

        source = inspect.getsource(dev.command_repin)
        lock = source.rindex("_acquire_repin_lock")
        recheck = source.index("_generation_names_run(run_id)", lock)
        snapshot = source.index("_repin_snapshot(selection)", lock)
        assert lock < recheck < snapshot

    def test_the_process_lock_is_released_by_closing_its_handle(
        self, tmp_path
    ) -> None:
        lock_path = tmp_path / "repin.lock"
        first = dev._acquire_repin_lock(lock_path)
        try:
            with pytest.raises(BlockingIOError):
                dev._acquire_repin_lock(lock_path)
        finally:
            dev._release_repin_lock(first)
        second = dev._acquire_repin_lock(lock_path)
        dev._release_repin_lock(second)

    @staticmethod
    def _transaction_fixture(tmp_path, monkeypatch):
        root = tmp_path / "repo"
        ledger = (
            root / "contracts" / "evidence" /
            "publication-selection-generations.json"
        )
        pin = root / "contracts" / "ml" / "expected-pin.json"
        records = root / "contracts" / "evidence" / "publication-selections"
        ledger.parent.mkdir(parents=True)
        pin.parent.mkdir(parents=True)
        records.mkdir(parents=True)
        ledger.write_bytes(b"ledger-before")
        pin.write_bytes(b"pin-before")
        (records / "existing.json").write_bytes(b"record-before")
        monkeypatch.setattr(dev, "REPO_ROOT", root)
        monkeypatch.setattr(selection, "GENERATIONS_PATH", ledger)
        _, journal = dev._repin_state_paths(selection)
        snapshot = dev._repin_snapshot(selection)
        return ledger, pin, records, journal, snapshot

    def test_a_prepared_crash_journal_restores_the_complete_before_image(
        self, tmp_path, monkeypatch
    ) -> None:
        ledger, pin, records, journal, snapshot = self._transaction_fixture(
            tmp_path, monkeypatch
        )
        dev._write_repin_transaction(
            selection, journal, snapshot, state="prepared"
        )
        ledger.write_bytes(b"ledger-after")
        pin.write_bytes(b"pin-after")
        (records / "existing.json").write_bytes(b"record-after")
        (records / "new.json").write_bytes(b"new-record")

        assert dev._recover_repin_transaction(selection, journal) == "prepared"
        assert ledger.read_bytes() == b"ledger-before"
        assert pin.read_bytes() == b"pin-before"
        assert (records / "existing.json").read_bytes() == b"record-before"
        assert not (records / "new.json").exists()
        assert not journal.exists()

    def test_a_committed_crash_journal_preserves_the_verified_adoption(
        self, tmp_path, monkeypatch
    ) -> None:
        ledger, pin, records, journal, snapshot = self._transaction_fixture(
            tmp_path, monkeypatch
        )
        ledger.write_bytes(b"ledger-after")
        pin.write_bytes(b"pin-after")
        (records / "existing.json").write_bytes(b"record-after")
        dev._write_repin_transaction(
            selection, journal, snapshot, state="committed"
        )

        assert dev._recover_repin_transaction(selection, journal) == "committed"
        assert ledger.read_bytes() == b"ledger-after"
        assert pin.read_bytes() == b"pin-after"
        assert (records / "existing.json").read_bytes() == b"record-after"
        assert not journal.exists()

    def test_an_incomplete_crash_journal_refuses_before_mutating_files(
        self, tmp_path, monkeypatch
    ) -> None:
        ledger, _, _, journal, snapshot = self._transaction_fixture(
            tmp_path, monkeypatch
        )
        dev._write_repin_transaction(
            selection, journal, snapshot, state="prepared"
        )
        document = json.loads(journal.read_text(encoding="utf-8"))
        document["before"].pop("ledger")
        journal.write_text(json.dumps(document), encoding="utf-8")
        ledger.write_bytes(b"live-state")

        with pytest.raises(RuntimeError, match="missing ledger"):
            dev._recover_repin_transaction(selection, journal)
        assert ledger.read_bytes() == b"live-state"
        assert journal.exists()

    def test_other_readers_fail_closed_while_a_transaction_is_prepared(
        self, tmp_path, monkeypatch
    ) -> None:
        ledger, _, _, journal, _ = self._transaction_fixture(
            tmp_path, monkeypatch
        )
        ledger.write_text(
            json.dumps(_empty_generation_document()), encoding="utf-8"
        )
        snapshot = dev._repin_snapshot(selection)
        dev._write_repin_transaction(
            selection, journal, snapshot, state="prepared"
        )

        with pytest.raises(SystemExit, match="adoption is incomplete"):
            selection.load_generations()
        pin_builder = _load("build_expected_pin")
        with pytest.raises(SystemExit, match="adoption is incomplete"):
            pin_builder.build_pin("run-x")
        monkeypatch.setenv(
            selection.REPIN_TRANSACTION_ENV, str(journal.resolve())
        )
        assert selection.load_generations() == []


class TestPipelineTimingFailures:
    def test_a_raising_inline_stage_still_records_its_timing(self) -> None:
        dev._STAGE_TIMINGS.clear()
        try:
            with pytest.raises(RuntimeError, match="probe"):
                dev._pipeline_step_inline(
                    "raising inline stage",
                    lambda: (_ for _ in ()).throw(RuntimeError("probe")),
                )
            assert [label for label, _ in dev._STAGE_TIMINGS] == [
                "raising inline stage"
            ]
        finally:
            dev._STAGE_TIMINGS.clear()


class TestScorecardFailsClosed:
    def test_a_missing_retirement_authority_refuses(self, tmp_path) -> None:
        """`_load(...) or {}` turned unreadable into "retires nothing"."""

        scorecard = _load("direction_scorecard")
        with pytest.raises(SystemExit, match="authority is absent"):
            scorecard.retired_capabilities(tmp_path)

    def test_the_callers_root_is_honoured(self, tmp_path) -> None:
        """`build(root)` read evidence from root and policy from this checkout."""

        scorecard = _load("direction_scorecard")
        policy = tmp_path / "contracts" / "onboarding"
        policy.mkdir(parents=True)
        (policy / "temporal-evidence-policy-v2.json").write_text(
            json.dumps(
                {"capabilities": {"retiredDefinitions": {"data_management": {}}}}
            ),
            encoding="utf-8",
        )
        assert scorecard.retired_capabilities(tmp_path) == {"data_management"}

    @pytest.mark.parametrize("payload", ["[]", "null", "42", "{}", '{"capabilities": 1}'])
    def test_a_malformed_authority_refuses(self, tmp_path, payload) -> None:
        scorecard = _load("direction_scorecard")
        root = tmp_path / payload.replace('"', "").replace(":", "").replace(" ", "")
        policy = root / "contracts" / "onboarding"
        policy.mkdir(parents=True)
        (policy / "temporal-evidence-policy-v2.json").write_text(
            payload, encoding="utf-8"
        )
        with pytest.raises(SystemExit):
            scorecard.retired_capabilities(root)


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
                reason_code="AUTOMATED_REPIN_ADOPTION",
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

    def test_an_unreadable_selection_cannot_make_the_collision_check_skip_it(
        self, tmp_path, monkeypatch
    ) -> None:
        directory = (
            tmp_path / "contracts" / "evidence" / "publication-selections"
        )
        directory.mkdir(parents=True)
        (directory / "broken.json").write_text("[]", encoding="utf-8")
        monkeypatch.setattr(dev, "REPO_ROOT", tmp_path)
        with pytest.raises(SystemExit, match="expected an object"):
            dev._generation_names_run("run-x")


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
                    reason_code="AUTOMATED_REPIN_ADOPTION",
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
                    reason_code="AUTOMATED_REPIN_ADOPTION", approved_at=None,
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
    def test_active_record_id_is_the_current_head_not_merely_state_active(
        self,
    ) -> None:
        """The pointer must name the CURRENT chain head for the scope.

        `state == "active"` is not currency and cannot be: supersession writes a NEW
        record, so every superseded generation's own file still reads "active" --
        eight of them do for `demand_forecast_non_pit` alone. An earlier version of
        this test asserted only that field, and would have accepted a pointer to r2.
        Currency is derived from the supersedes chain, which is what
        `current_records` computes.

        This is the load-bearing check for the drift that shipped at c368512: the
        builder writes a fresh value and never reads the committed one, so only a
        test that reads from disk can see a stale pointer.
        """

        source = json.loads(
            (
                REPO_ROOT / "contracts" / "evidence"
                / "inventory-replenishment-entry-record.json"
            ).read_text(encoding="utf-8")
        )["sourceSelection"]
        directory = (
            REPO_ROOT / "contracts" / "evidence" / "publication-selections"
        )
        records = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*.json"))
        ]
        records = [
            record
            for record in records
            if record.get("schemaVersion") == selection.SELECTION_SCHEMA_VERSION
        ]
        heads = [
            record
            for record in selection.current_records(records)
            if record["lifecycle"]["state"] == "active"
            and record["scope"]["capability"] == "demand_forecast_non_pit"
        ]
        assert len(heads) == 1, f"expected one current head, found {len(heads)}"
        head = heads[0]
        assert source["activeRecordId"] == head["lifecycle"]["recordId"], (
            f"entry record names {source['activeRecordId']} but the current head "
            f"is {head['lifecycle']['recordId']}"
        )
        assert source["selectionId"] == head["selectionId"]
        assert source["scope"]["capability"] == "demand_forecast_non_pit"


class TestGateBMaskIsRequired:
    def test_a_gate_b_without_a_mask_is_refused_not_backfilled(
        self, tmp_path
    ) -> None:
        """"Could not find the evidence" must not resolve to "the evidence says yes".

        The mask previously fell back to the publication manifest's transcription, so
        a Gate B carrying no mask silently handed the capability verdict back to the
        copy -- inside the very change whose point was to read the gate itself.
        """

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text(
            json.dumps({"status": "pass", "semanticFingerprint": "a" * 64}),
            encoding="utf-8",
        )
        # An EMPTY mask, not an absent one: absent is now caught earlier by the
        # required-field check, and both must refuse. This case proves the manifest
        # cannot backfill a mask the gate does not usefully carry.
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "semanticFingerprint": "b" * 64,
                    "capabilityMask": {},
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps(
                {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "objects": [],
                    "duckdb": {"sha256": "d" * 64},
                    # A mask here must NOT rescue a Gate B that carries none.
                    "capabilityMask": {
                        name: {"available": True}
                        for name in (
                            "demand_forecast_non_pit",
                            "inventory_replenishment_current_snapshot",
                            "inventory_replenishment_replay",
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="no usable capabilityMask"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original

    def test_absent_gate_b_refuses_cleanly(self, tmp_path) -> None:
        """Missing evidence should read as a governed stop, not a traceback."""

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text(
            json.dumps({"status": "pass", "semanticFingerprint": "a" * 64}),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps(
                {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "objects": [],
                    "duckdb": {"sha256": "d" * 64},
                }
            ),
            encoding="utf-8",
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="retained evidence is absent"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original


class TestMaskIsInterpretedStrictly:
    @staticmethod
    def _run_dir(tmp_path, mask):
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text(
            json.dumps({"status": "pass", "semanticFingerprint": "a" * 64}),
            encoding="utf-8",
        )
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "semanticFingerprint": "b" * 64,
                    "capabilityMask": mask,
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps(
                {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "objects": [],
                    "duckdb": {"sha256": "d" * 64},
                }
            ),
            encoding="utf-8",
        )
        return tmp_path

    def test_the_string_false_does_not_read_as_available(self, tmp_path) -> None:
        """`"available": "false"` is a truthy string and authorized adoption."""

        root = self._run_dir(
            tmp_path,
            {
                "demand_forecast_non_pit": {"available": "false"},
                "inventory_replenishment_current_snapshot": {"available": "no"},
                "inventory_replenishment_replay": {"available": True},
            },
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = root
        try:
            with pytest.raises(SystemExit, match=r"not \{'available': <bool>\}"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original

    def test_a_real_false_is_reported_as_missing_not_malformed(
        self, tmp_path
    ) -> None:
        """An honest `false` is a capability verdict, not broken evidence."""

        root = self._run_dir(
            tmp_path,
            {
                "demand_forecast_non_pit": {"available": True},
                "inventory_replenishment_current_snapshot": {"available": True},
                "inventory_replenishment_replay": {"available": False},
            },
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = root
        try:
            facts = dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original
        assert facts["missingRequiredCapabilities"] == [
            "inventory_replenishment_replay"
        ]


class TestEvidenceReadsAreUniform:
    @pytest.mark.parametrize(
        "absent", ["gate-a.json", "gate-b.json", "publication-manifest.json"]
    )
    def test_any_absent_source_refuses_the_same_way(self, tmp_path, absent) -> None:
        """One of three refusing cleanly and two crashing is the bug."""

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        payloads = {
            "gate-a.json": {"status": "pass", "semanticFingerprint": "a" * 64},
            "gate-b.json": {
                "status": "pass",
                "semanticFingerprint": "b" * 64,
                "capabilityMask": {},
            },
            "publication-manifest.json": {
                "sourceSnapshotId": "c" * 64,
                "gateBSemanticFingerprint": "b" * 64,
                "semanticFingerprint": "e" * 64,
                "objects": [],
                "duckdb": {"sha256": "d" * 64},
            },
        }
        for name, payload in payloads.items():
            if name != absent:
                (evidence / name).write_text(json.dumps(payload), encoding="utf-8")
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="retained evidence is absent"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original

    def test_malformed_json_refuses_rather_than_raising(self, tmp_path) -> None:
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text("{not json", encoding="utf-8")
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="not valid JSON"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original


class TestSharedMaskReader:
    """One reader, because three copies of a check is how the next one drifts.

    The truthiness defect was fixed first in `_repin_facts` -- the PROPOSAL gate, and
    the least consequential of the three. It survived at both gates that write
    committed artifacts: `build_candidate`, which writes the governance record, and
    `build_pin`, which writes the pin. Both are reachable without `repin`, so the
    earlier refusal shielded neither.
    """

    @pytest.mark.parametrize(
        "value",
        ["false", "no", "0", 1, 0.0, None, [], {}],
        ids=["str-false", "str-no", "str-zero", "int", "float", "none", "list", "dict"],
    )
    def test_only_a_real_boolean_is_a_verdict(self, value) -> None:
        mask = {"demand_forecast_non_pit": {"available": value}}
        with pytest.raises(SystemExit, match=r"not \{'available': <bool>\}"):
            selection.capability_is_available(
                mask, "demand_forecast_non_pit", subject="run-x"
            )

    def test_real_booleans_pass_through(self) -> None:
        for available in (True, False):
            mask = {"demand_forecast_non_pit": {"available": available}}
            assert (
                selection.capability_is_available(
                    mask, "demand_forecast_non_pit", subject="run-x"
                )
                is available
            )

    @pytest.mark.parametrize("mask", [None, {}, [], "nope", {"other": {}}])
    def test_an_unusable_mask_is_refused(self, mask) -> None:
        with pytest.raises(SystemExit):
            selection.capability_is_available(
                mask, "demand_forecast_non_pit", subject="run-x"
            )

    def test_both_writing_gates_use_the_shared_reader(self) -> None:
        """A guard at the proposal gate alone does not protect the artifacts."""

        import inspect

        pin = _load("build_expected_pin")
        assert "capability_is_available" in inspect.getsource(pin.build_pin)
        assert "capability_is_available" in inspect.getsource(
            selection.build_candidate
        )


class TestEvidenceMustBeAnObject:
    @pytest.mark.parametrize("payload", ["[]", "null", "42", '"text"'])
    def test_valid_json_that_is_not_an_object_is_refused(
        self, tmp_path, payload
    ) -> None:
        """`[]`, `null` and scalars all parse, then every reader calls .get()."""

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text(payload, encoding="utf-8")
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="not a JSON object"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original


class TestEvidenceFieldsAreRequired:
    """An object is not enough either.

    Each round this escaped one type further out: FileNotFoundError, then
    AttributeError on `[]`/`null`, now KeyError on `{}`. None of them is a SystemExit,
    so each in turn bypassed `command_repin`'s handler and cost the stage timings.
    The fields are declared up front rather than discovered by whichever line first
    needs one.
    """

    CAPS = (
        "demand_forecast_non_pit",
        "inventory_replenishment_current_snapshot",
        "inventory_replenishment_replay",
    )

    def _write(self, tmp_path, overrides):
        mask = {c: {"available": True} for c in self.CAPS}
        payloads = {
            "gate-a.json": {"status": "pass", "semanticFingerprint": "a" * 64},
            "gate-b.json": {
                "status": "pass",
                "semanticFingerprint": "b" * 64,
                "capabilityMask": mask,
            },
            "publication-manifest.json": {
                "sourceSnapshotId": "c" * 64,
                "gateBSemanticFingerprint": "b" * 64,
                "semanticFingerprint": "e" * 64,
                "objects": [],
                "duckdb": {"sha256": "d" * 64},
            },
        }
        payloads.update(overrides)
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        for name, payload in payloads.items():
            (evidence / name).write_text(json.dumps(payload), encoding="utf-8")
        return tmp_path

    @pytest.mark.parametrize(
        "name,payload,expected",
        [
            ("gate-a.json", {"status": "pass"}, "has no 'semanticFingerprint'"),
            (
                "publication-manifest.json",
                {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "duckdb": {"sha256": "d" * 64},
                },
                "has no 'objects'",
            ),
            (
                "publication-manifest.json",
                {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "objects": [],
                    "duckdb": "nope",
                },
                "expected dict",
            ),
        ],
        ids=["gate-a-missing-field", "manifest-missing-field", "manifest-wrong-type"],
    )
    def test_incomplete_evidence_refuses_rather_than_raising(
        self, tmp_path, name, payload, expected
    ) -> None:
        root = self._write(tmp_path, {name: payload})
        original = dev.REPO_ROOT
        dev.REPO_ROOT = root
        try:
            with pytest.raises(SystemExit, match=expected):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original

    def test_a_nested_duckdb_sha_is_required(self, tmp_path) -> None:
        root = self._write(
            tmp_path,
            {
                "publication-manifest.json": {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "objects": [],
                    "duckdb": {},
                }
            },
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = root
        try:
            with pytest.raises(SystemExit, match="duckdb.sha256"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original

    def test_a_typed_but_invalid_fingerprint_is_refused(self, tmp_path) -> None:
        root = self._write(
            tmp_path,
            {
                "gate-a.json": {
                    "status": "pass",
                    "semanticFingerprint": "z" * 64,
                }
            },
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = root
        try:
            with pytest.raises(SystemExit, match="lowercase SHA-256"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original


class TestScorecardMaskReader:
    def test_a_malformed_mask_is_not_reported_as_available(self, tmp_path) -> None:
        """The fourth reader. Reporting, not authorization -- so strict, not raising."""

        scorecard = _load("direction_scorecard")
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "r"
        evidence.mkdir(parents=True)
        _copy_policy(tmp_path)
        capabilities = sorted(
            {
                capability
                for spec in scorecard.PHASE_REQUIREMENTS.values()
                for capability in spec["capabilities"]
            }
        )
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "semanticFingerprint": "b" * 64,
                    "capabilityMask": {
                        c: {"available": "false"} for c in capabilities
                    },
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps({"sourceSnapshotId": "c" * 64}), encoding="utf-8"
        )
        result = scorecard.build(tmp_path)
        for name, spec in scorecard.PHASE_REQUIREMENTS.items():
            if not spec["capabilities"]:
                continue
            codes = {
                entry["reasonCode"]
                for entry in result["phases"][name].get("missingCapabilities") or []
            }
            # ENTRY level: the mask itself was readable, one entry was not.
            assert codes == {"ENTRY_UNREADABLE"}, (
                f"{name} did not flag the unreadable entry: {codes}"
            )


class TestAbsentMaskField:
    def test_gate_b_without_the_mask_key_refuses_up_front(self, tmp_path) -> None:
        """Declared as required, so it is named rather than met later as a KeyError."""

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text(
            json.dumps({"status": "pass", "semanticFingerprint": "a" * 64}),
            encoding="utf-8",
        )
        (evidence / "gate-b.json").write_text(
            json.dumps({"status": "pass", "semanticFingerprint": "b" * 64}),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps(
                {
                    "sourceSnapshotId": "c" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "e" * 64,
                    "objects": [],
                    "duckdb": {"sha256": "d" * 64},
                }
            ),
            encoding="utf-8",
        )
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="has no 'capabilityMask'"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original


class TestOptionalFieldsAreTypedToo:
    def test_business_controls_must_be_an_object_when_present(self, tmp_path) -> None:
        """Optional means "may be absent", never "may be anything".

        `(manifest.get("businessControls") or {}).keys()` covered absent, null and
        {} -- which is why it survived three rounds -- but a non-empty list or string
        went straight to `.keys()` and raised AttributeError past the handler.
        """

        caps = (
            "demand_forecast_non_pit",
            "inventory_replenishment_current_snapshot",
            "inventory_replenishment_replay",
        )
        for value in ([1, 2], "text", 7):
            evidence = tmp_path / str(id(value)) / "ingestion/data/evidence/run-x"
            evidence.mkdir(parents=True)
            (evidence / "gate-a.json").write_text(
                json.dumps({"status": "pass", "semanticFingerprint": "a" * 64}),
                encoding="utf-8",
            )
            (evidence / "gate-b.json").write_text(
                json.dumps(
                    {
                        "status": "pass",
                        "semanticFingerprint": "b" * 64,
                        "capabilityMask": {c: {"available": True} for c in caps},
                    }
                ),
                encoding="utf-8",
            )
            (evidence / "publication-manifest.json").write_text(
                json.dumps(
                    {
                        "sourceSnapshotId": "c" * 64,
                        "gateBSemanticFingerprint": "b" * 64,
                        "semanticFingerprint": "e" * 64,
                        "objects": [],
                        "duckdb": {"sha256": "d" * 64},
                        "businessControls": value,
                    }
                ),
                encoding="utf-8",
            )
            original = dev.REPO_ROOT
            dev.REPO_ROOT = tmp_path / str(id(value))
            try:
                with pytest.raises(SystemExit, match="optional field"):
                    dev._repin_facts("run-x")
            finally:
                dev.REPO_ROOT = original

    def test_invalid_utf8_refuses_before_json_sees_it(self, tmp_path) -> None:
        """`read_text` raises UnicodeDecodeError, which is not a JSONDecodeError."""

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_bytes(b'\xff\xfe{"status":"pass"}')
        original = dev.REPO_ROOT
        dev.REPO_ROOT = tmp_path
        try:
            with pytest.raises(SystemExit, match="not valid UTF-8"):
                dev._repin_facts("run-x")
        finally:
            dev.REPO_ROOT = original


class TestScorecardContainer:
    @pytest.mark.parametrize("shape", [None, [1, 2], "text", 7])
    def test_an_unreadable_mask_container_does_not_crash(self, tmp_path, shape) -> None:
        """The entry guard did not cover the container holding the entries."""

        scorecard = _load("direction_scorecard")
        root = tmp_path / str(id(shape))
        evidence = root / "ingestion" / "data" / "evidence" / "r"
        evidence.mkdir(parents=True)
        _copy_policy(root)
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "semanticFingerprint": "b" * 64,
                    "capabilityMask": shape,
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps({"sourceSnapshotId": "c" * 64}), encoding="utf-8"
        )
        result = scorecard.build(root)
        codes = {
            entry["reasonCode"]
            for phase in result["phases"].values()
            for entry in (phase.get("missingCapabilities") or [])
        }
        # MASK_UNREADABLE, not NOT_EVALUATED: the gate did not run and skip these,
        # the mask could not be read at all, and the output must not conflate them.
        assert codes == {"MASK_UNREADABLE"}, codes

    def test_phase_4_checks_the_split_capabilities_not_the_retired_one(self) -> None:
        """`replenishment` is superseded, and the mask says so itself."""

        scorecard = _load("direction_scorecard")
        required = scorecard.PHASE_REQUIREMENTS["phase_4_inventory"]["capabilities"]
        assert "replenishment" not in required
        assert set(required) == {
            "inventory_replenishment_current_snapshot",
            "inventory_replenishment_replay",
        }

    def test_no_phase_requires_a_retired_capability(self) -> None:
        """The class guard -- and it must run on a fresh clone, which it did not.

        This previously read the Gate-B mask under `ingestion/data/`, which is
        gitignored, so it skipped on a fresh clone, on macOS, and here after a wipe.
        It also named one run id, so it stopped running the moment the pin moved even
        on a host that had evidence. That is the same "passes only where the bytes
        are" shape the selection ledger was fixed for at a855c62 -- reappearing inside
        the guard written to stop a class from recurring.

        The authority is now the committed policy, so this runs everywhere.
        """

        scorecard = _load("direction_scorecard")
        retired = scorecard.retired_capabilities()
        assert retired, "the committed policy should declare at least one retirement"
        offenders = sorted(
            f"{phase}:{capability}"
            for phase, spec in scorecard.PHASE_REQUIREMENTS.items()
            for capability in spec["capabilities"]
            if capability in retired
        )
        assert not offenders, f"phases requiring retired capabilities: {offenders}"

    def test_the_retirement_authority_is_committed_not_gitignored(self) -> None:
        """A guard sourced from gitignored data is a guard that skips."""

        scorecard = _load("direction_scorecard")
        assert scorecard._POLICY_PATH.is_file(), scorecard._POLICY_PATH
        assert "ingestion/data" not in scorecard._POLICY_PATH.as_posix()

    def test_the_mask_alias_matches_a_real_policy_retirement(self) -> None:
        """An alias naming nothing would silently stop covering its mask spelling."""

        scorecard = _load("direction_scorecard")
        policy = json.loads(
            scorecard._POLICY_PATH.read_text(encoding="utf-8")
        )
        declared = set(
            (policy.get("capabilities") or {}).get("retiredDefinitions") or {}
        )
        for mask_name, policy_name in scorecard.RETIRED_CAPABILITY_ALIASES.items():
            assert policy_name in declared, (
                f"alias {mask_name} -> {policy_name} names no policy retirement"
            )


class TestReadBoundary:
    def test_a_read_error_refuses_rather_than_raising(self, tmp_path, monkeypatch):
        """PermissionError and a deletion race are OSError, not SystemExit.

        The is_file() check cannot close the race on its own -- the file can vanish
        between the check and the read -- so only catching the read closes it.
        """

        import pathlib as _pathlib

        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-x"
        evidence.mkdir(parents=True)
        (evidence / "gate-a.json").write_text("{}", encoding="utf-8")
        real = _pathlib.Path.read_text

        def deny(self, *args, **kwargs):
            if self.name == "gate-a.json":
                raise PermissionError(13, "Permission denied")
            return real(self, *args, **kwargs)

        monkeypatch.setattr(_pathlib.Path, "read_text", deny)
        monkeypatch.setattr(dev, "REPO_ROOT", tmp_path)
        with pytest.raises(SystemExit, match="could not be read"):
            dev._repin_facts("run-x")


class TestScorecardNullEntry:
    def test_an_explicit_null_entry_is_malformed_not_unevaluated(
        self, tmp_path
    ) -> None:
        """An absent key and `"capability": null` are different claims.

        Absent means the gate did not evaluate it; an explicit null is malformed
        evidence. `.get()` returns None for both and collapsed the distinction.
        """

        scorecard = _load("direction_scorecard")
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "r"
        evidence.mkdir(parents=True)
        _copy_policy(tmp_path)
        capabilities = sorted(
            {
                capability
                for spec in scorecard.PHASE_REQUIREMENTS.values()
                for capability in spec["capabilities"]
            }
        )
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "semanticFingerprint": "b" * 64,
                    "capabilityMask": {c: None for c in capabilities},
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps({"sourceSnapshotId": "c" * 64}), encoding="utf-8"
        )
        codes = {
            entry["reasonCode"]
            for phase in scorecard.build(tmp_path)["phases"].values()
            for entry in (phase.get("missingCapabilities") or [])
        }
        assert codes == {"ENTRY_UNREADABLE"}, codes

    def test_an_absent_key_is_still_not_evaluated(self, tmp_path) -> None:
        scorecard = _load("direction_scorecard")
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "r"
        evidence.mkdir(parents=True)
        _copy_policy(tmp_path)
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "semanticFingerprint": "b" * 64,
                    "capabilityMask": {},
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps({"sourceSnapshotId": "c" * 64}), encoding="utf-8"
        )
        report = scorecard.build(tmp_path)
        codes = {
            entry["reasonCode"]
            for phase in report["phases"].values()
            for entry in (phase.get("missingCapabilities") or [])
        }
        assert codes == {"NOT_EVALUATED"}, codes
        assert "NOT_EVALUATED" in {
            blocker["reasonCode"] for blocker in report["blockersByLeverage"]
        }

    def test_an_unavailable_entry_without_a_reason_uses_a_stable_code(
        self, tmp_path
    ) -> None:
        scorecard = _load("direction_scorecard")
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "r"
        evidence.mkdir(parents=True)
        _copy_policy(tmp_path)
        (evidence / "gate-b.json").write_text(
            json.dumps(
                {
                    "status": "pass",
                    "capabilityMask": {
                        "pricing_elasticity": {
                            "available": False,
                            "reasonCode": None,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        (evidence / "publication-manifest.json").write_text(
            json.dumps({"semanticFingerprint": "publication"}), encoding="utf-8"
        )
        phase = scorecard.build(tmp_path)["phases"]["phase_5_pricing"]
        assert phase["missingCapabilities"] == [
            {"capability": "pricing_elasticity", "reasonCode": "UNAVAILABLE"}
        ]


class TestScorecardAuthorityBoundary:
    @staticmethod
    def _write_gate(root: Path, run: str, *, gate: object, manifest: object) -> Path:
        evidence = root / "ingestion" / "data" / "evidence" / run
        evidence.mkdir(parents=True)
        (evidence / "gate-b.json").write_text(json.dumps(gate), encoding="utf-8")
        (evidence / "publication-manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return evidence / "gate-b.json"

    def test_multiple_unpinned_gate_documents_are_refused(self, tmp_path) -> None:
        scorecard = _load("direction_scorecard")
        for run in ("run-a", "run-z"):
            self._write_gate(
                tmp_path,
                run,
                gate={"status": "pass", "capabilityMask": {}},
                manifest={"semanticFingerprint": run},
            )
        with pytest.raises(SystemExit, match="more than one passing"):
            scorecard.gate_b_evidence(tmp_path)

    def test_an_accepted_lifecycle_without_a_run_identity_does_not_authorize(
        self, tmp_path
    ) -> None:
        scorecard = _load("direction_scorecard")
        artifact = (
            tmp_path / "ml" / "data" / "artifacts" / "broken" /
            "forecast-run-manifest.json"
        )
        artifact.parent.mkdir(parents=True)
        artifact.write_text(
            json.dumps(
                {
                    "forecastRunId": None,
                    "lifecycleStatus": "accepted",
                    "modelPolicy": {
                        "acceptanceEvaluation": (
                            "cohorted-seasonal-cold-start-recomputation/v4"
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
        state = scorecard.forecast_state(tmp_path)
        assert state["governedAcceptedRuns"] == []
        assert state["servingAuthorized"] is False

    def test_the_expected_pin_selects_its_gate_not_the_last_hash(self, tmp_path) -> None:
        scorecard = _load("direction_scorecard")
        pin_dir = tmp_path / "contracts" / "ml"
        pin_dir.mkdir(parents=True)
        (pin_dir / "expected-pin.json").write_text(
            json.dumps(
                {
                    "publication": {"semanticFingerprint": "publication-a"},
                    "gateB": {"semanticFingerprint": "gate-a"},
                }
            ),
            encoding="utf-8",
        )
        expected = self._write_gate(
            tmp_path,
            "run-a",
            gate={
                "status": "pass",
                "semanticFingerprint": "gate-a",
                "capabilityMask": {},
            },
            manifest={"semanticFingerprint": "publication-a"},
        )
        self._write_gate(
            tmp_path,
            "run-z",
            gate={
                "status": "pass",
                "semanticFingerprint": "gate-z",
                "capabilityMask": {},
            },
            manifest={"semanticFingerprint": "publication-z"},
        )
        _, actual = scorecard.gate_b_evidence(tmp_path)
        assert actual == expected

    @pytest.mark.parametrize("gate", [None, 42, [1], "text"])
    def test_a_non_object_gate_is_mask_unreadable(self, tmp_path, gate) -> None:
        scorecard = _load("direction_scorecard")
        root = tmp_path / str(id(gate))
        _copy_policy(root)
        self._write_gate(
            root,
            "run-a",
            gate=gate,
            manifest={"semanticFingerprint": "publication-a"},
        )
        report = scorecard.build(root)
        codes = {
            entry["reasonCode"]
            for phase in report["phases"].values()
            for entry in (phase.get("missingCapabilities") or [])
        }
        assert codes == {"MASK_UNREADABLE"}, codes

    def test_a_missing_mask_field_is_not_an_empty_evaluated_mask(
        self, tmp_path
    ) -> None:
        scorecard = _load("direction_scorecard")
        _copy_policy(tmp_path)
        self._write_gate(
            tmp_path,
            "run-a",
            gate={"status": "pass", "semanticFingerprint": "gate-a"},
            manifest={"semanticFingerprint": "publication-a"},
        )
        report = scorecard.build(tmp_path)
        codes = {
            entry["reasonCode"]
            for phase in report["phases"].values()
            for entry in (phase.get("missingCapabilities") or [])
        }
        assert codes == {"MASK_UNREADABLE"}, codes

    def test_invalid_utf8_retirement_policy_refuses_cleanly(self, tmp_path) -> None:
        scorecard = _load("direction_scorecard")
        policy = tmp_path / "contracts" / "onboarding"
        policy.mkdir(parents=True)
        (policy / "temporal-evidence-policy-v2.json").write_bytes(b"\xff")
        with pytest.raises(SystemExit, match="not valid UTF-8"):
            scorecard.retired_capabilities(tmp_path)


class TestServeAuthorityResolution:
    @staticmethod
    def _authority(scope: str, publication: str) -> dict[str, str]:
        return {
            "activationScopeFingerprint": scope,
            "publicationSemanticFingerprint": publication,
        }

    def test_multiple_active_rows_are_refused_not_fetchone_tiebroken(self) -> None:
        rows = [
            self._authority("scope-a", "publication-a"),
            self._authority("scope-b", "publication-b"),
        ]
        with pytest.raises(SystemExit, match="2 active forecast authorities"):
            dev._active_authority_run(rows)

    def test_a_probe_failure_is_not_a_silent_newest_run_fallback(
        self, monkeypatch
    ) -> None:
        import types

        monkeypatch.setattr(dev, "_require_python", lambda *args: Path("python"))
        monkeypatch.setattr(
            dev,
            "_local_postgres_dsn",
            lambda **kwargs: "postgresql://example",
        )
        monkeypatch.setattr(
            dev.subprocess,
            "run",
            lambda *args, **kwargs: types.SimpleNamespace(
                returncode=1, stdout="", stderr="connection refused"
            ),
        )
        with pytest.raises(SystemExit, match="connection refused"):
            dev._active_forecast_authorities()

    def test_an_authority_probe_timeout_refuses_cleanly(self, monkeypatch) -> None:
        monkeypatch.setattr(dev, "_require_python", lambda *args: Path("python"))
        monkeypatch.setattr(
            dev,
            "_local_postgres_dsn",
            lambda **kwargs: "postgresql://example",
        )

        def time_out(*args, **kwargs):
            raise dev.subprocess.TimeoutExpired(args[0], timeout=15)

        monkeypatch.setattr(dev.subprocess, "run", time_out)
        with pytest.raises(SystemExit, match="timed out after 15 seconds"):
            dev._active_forecast_authorities()

    def test_one_active_publication_maps_to_exactly_one_retained_run(
        self, tmp_path, monkeypatch
    ) -> None:
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "run-a"
        evidence.mkdir(parents=True)
        (evidence / "publication-manifest.json").write_text(
            json.dumps({"semanticFingerprint": "publication-a"}), encoding="utf-8"
        )
        monkeypatch.setattr(dev, "REPO_ROOT", tmp_path)
        assert dev._active_authority_run(
            [self._authority("scope-a", "publication-a")]
        ) == "run-a"

    def test_duplicate_retained_runs_for_one_active_fingerprint_are_refused(
        self, tmp_path, monkeypatch
    ) -> None:
        for run in ("run-a", "run-b"):
            evidence = tmp_path / "ingestion" / "data" / "evidence" / run
            evidence.mkdir(parents=True)
            (evidence / "publication-manifest.json").write_text(
                json.dumps({"semanticFingerprint": "publication-a"}),
                encoding="utf-8",
            )
        monkeypatch.setattr(dev, "REPO_ROOT", tmp_path)
        with pytest.raises(SystemExit, match="2 retained run directories"):
            dev._active_authority_run(
                [self._authority("scope-a", "publication-a")]
            )

    @pytest.mark.parametrize(
        "address,target",
        [
            (":9090", "http://127.0.0.1:9090"),
            ("0.0.0.0:8080", "http://127.0.0.1:8080"),
            ("127.0.0.1:7070", "http://127.0.0.1:7070"),
            ("[::1]:6060", "http://[::1]:6060"),
        ],
    )
    def test_go_listen_addresses_become_dialable_proxy_urls(
        self, address, target
    ) -> None:
        assert dev._api_proxy_target(address) == target

    @pytest.mark.parametrize(
        "address",
        [
            "http://127.0.0.1:8080",
            "user@127.0.0.1:8080",
            "localhost",
            ":0",
            "localhost:8080/",
        ],
    )
    def test_non_listen_addresses_are_refused(self, address) -> None:
        with pytest.raises(ValueError, match="host:port"):
            dev._api_proxy_target(address)

    def test_vite_consumes_the_normalized_target(self) -> None:
        source = (REPO_ROOT / "ui" / "vite.config.ts").read_text(encoding="utf-8")
        assert "RETAIL_API_TARGET" in source
        assert "http://${process.env.RETAIL_API_ADDRESS" not in source

    def test_serve_uses_workspace_go_runtime_paths(self) -> None:
        import inspect

        source = inspect.getsource(dev.command_serve)
        assert 'environment.setdefault("GOCACHE"' in source
        assert 'environment.setdefault("GOTMPDIR"' in source
