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


class TestCollisionAvoidance:
    def test_an_adopted_run_is_recognised(self) -> None:
        """The check that stops a re-publication overwriting an attested artifact."""

        assert dev._generation_names_run("run-adac9e85dccb56e8-r6")
        assert not dev._generation_names_run("run-does-not-exist")
