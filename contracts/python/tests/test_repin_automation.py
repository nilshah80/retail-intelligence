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
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
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
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
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
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
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
                "sourceSnapshotId": "s" * 64,
                "gateBSemanticFingerprint": "b" * 64,
                "semanticFingerprint": "p" * 64,
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
                "sourceSnapshotId": "s" * 64,
                "gateBSemanticFingerprint": "b" * 64,
                "semanticFingerprint": "p" * 64,
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
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
                    "duckdb": {"sha256": "d" * 64},
                },
                "has no 'objects'",
            ),
            (
                "publication-manifest.json",
                {
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
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
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
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


class TestScorecardMaskReader:
    def test_a_malformed_mask_is_not_reported_as_available(self, tmp_path) -> None:
        """The fourth reader. Reporting, not authorization -- so strict, not raising."""

        scorecard = _load("direction_scorecard")
        evidence = tmp_path / "ingestion" / "data" / "evidence" / "r"
        evidence.mkdir(parents=True)
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
            json.dumps({"sourceSnapshotId": "s" * 64}), encoding="utf-8"
        )
        result = scorecard.build(tmp_path)
        for name, spec in scorecard.PHASE_REQUIREMENTS.items():
            if not spec["capabilities"]:
                continue
            codes = {
                entry["reasonCode"]
                for entry in result["phases"][name].get("missingCapabilities") or []
            }
            assert codes == {"MASK_UNREADABLE"}, (
                f"{name} did not flag the unreadable mask: {codes}"
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
                    "sourceSnapshotId": "s" * 64,
                    "gateBSemanticFingerprint": "b" * 64,
                    "semanticFingerprint": "p" * 64,
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
                        "sourceSnapshotId": "s" * 64,
                        "gateBSemanticFingerprint": "b" * 64,
                        "semanticFingerprint": "p" * 64,
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
            json.dumps({"sourceSnapshotId": "s" * 64}), encoding="utf-8"
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

    def test_no_phase_requires_a_superseded_capability(self) -> None:
        """The class, not the instance: any phase naming a retired flag fails here."""

        scorecard = _load("direction_scorecard")
        gate_b_path = (
            REPO_ROOT / "ingestion" / "data" / "evidence"
            / "run-adac9e85dccb56e8-r2" / "gate-b.json"
        )
        if not gate_b_path.is_file():
            pytest.skip("no retained evidence on this host")
        mask = json.loads(gate_b_path.read_text(encoding="utf-8"))["capabilityMask"]
        offenders = [
            f"{phase}:{capability}"
            for phase, spec in scorecard.PHASE_REQUIREMENTS.items()
            for capability in spec["capabilities"]
            if (mask.get(capability) or {}).get("supersededBy")
        ]
        assert not offenders, f"phases requiring superseded capabilities: {offenders}"
