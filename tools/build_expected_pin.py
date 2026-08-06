"""Derive `contracts/ml/expected-pin.json` from retained evidence (P4-3 task 5).

The pin was previously maintained by hand. Every value in it already exists in
the retained gate, publication and retention artifacts, so transcribing them is
pure risk: a typo in a 64-character hex string reads as a tampered bundle four
steps later, and the pin is precisely the file whose whole purpose is to be
trustworthy.

This derives the pin instead, and only from a publication whose evidence has been
retained. It refuses to write a pin whose selection is not active: the pin says
"this is the publication ML may consume", and decision #73 says which publication
that is. Two files claiming different answers is the state this repository has
already been burned by.

Run with `--check` to assert the committed pin matches a fresh derivation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))

from retail_ingestion.readiness.selection import (  # noqa: E402
    SELECTION_SCHEMA_VERSION,
    scope_key,
    validate_selection,
)

sys.path.insert(0, str(REPO_ROOT / "tools"))

from build_publication_selection import (  # noqa: E402
    atomic_write_bytes,
    assert_repin_transaction_readable,
    capability_is_available,
    current_records,
    load_generations,
)

PIN_PATH = REPO_ROOT / "contracts" / "ml" / "expected-pin.json"
SELECTION_DIR = REPO_ROOT / "contracts" / "evidence" / "publication-selections"

#: `contracts/ml/expected-pin.json` is the ONLY thing the ML chain consults to find
#: its curated root -- `features` takes no source argument at all -- so a pin naming
#: the wrong publication makes every ML stage read the previous one while
#: `--source-root` is silently ignored. That cost a full features-and-backtest run
#: once: the feature manifest recorded sourceSnapshotId d43fd302 when the intent was
#: 0634b079. Hence the derivation below, and hence `build_pin` cross-checking the
#: active decision-#73 selection before it writes anything.


def _fallback_run() -> str | None:
    """The run the committed ledger last adopted, for a checkout with no data.

    Derived, because a hardcoded fallback goes stale exactly as fast as the constant
    it replaced: it said r6 while the committed pin named r2, one commit later, so a
    fresh clone's `--list` reported a run nothing pinned. The newest ledger
    generation is the same authority `--check` verifies against, so the two cannot
    disagree.
    """

    try:
        generations = load_generations()
    except (OSError, ValueError):
        return None
    if not generations:
        return None

    # Highest tag, not last-in-file. `next_generation_tag()` next door already picks
    # the maximum, and two different rules for "newest" in adjacent functions is how
    # they eventually disagree about the same ledger.
    def _tag_number(entry: dict[str, Any]) -> int:
        tag = str(entry.get("tag") or "")
        return int(tag[1:]) if tag.startswith("r") and tag[1:].isdigit() else -1

    newest = max(generations, key=_tag_number)
    return str(newest.get("run") or "") or None


def _pinned_run() -> str:
    """The run this pin names, derived rather than transcribed.

    Retained evidence is the authority: a publication may only be pinned while its
    gate and manifest files are present, which is what `build_pin` reads. Exactly one
    run has them after a completed pipeline -- the rest are evidence-released -- so
    the derivation is unambiguous. Ambiguity is refused rather than tie-broken,
    because a newest-wins glob over content hashes is exactly the arbitrary choice
    decision #89 exists to prevent.
    """

    # The LEDGER decides what is pinned; retained evidence only decides whether the
    # pin can be derived. Those are different questions and conflating them gave a
    # wrong answer in an ordinary case: publish a new run without adopting it and the
    # single retained evidence directory made `--list` report that unadopted run as
    # "currently pinned", when the pin and every active selection still named the
    # previous one. Authority is a governed choice, not a side effect of which bytes
    # happen to be on this disk.
    adopted = _fallback_run()
    if adopted is not None:
        return adopted
    promoted = _promoted_runs()
    if len(promoted) == 1:
        return promoted[0]
    if not promoted:
        raise SystemExit(
            "no run has retained evidence and the ledger names none; "
            "pass --run to state which publication is pinned"
        )
    raise SystemExit(
        f"{len(promoted)} runs have retained evidence ({', '.join(promoted)}) and "
        "the ledger names none; pass --run to state which one is pinned rather "
        "than letting this guess"
    )

#: What ML must be able to do with this bundle. `inventory_replenishment_replay`
#: joins the list at P4-3 because the Phase 4 bundle consumes it, and a pin that
#: does not require it would let a publication without origin-safe evidence
#: satisfy the pin check while making the inventory run impossible.
REQUIRED_CAPABILITIES = [
    "demand_forecast_non_pit",
    "inventory_replenishment_current_snapshot",
    "inventory_replenishment_replay",
]


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _active_selections() -> dict[str, dict[str, Any]]:
    """Current, active selections keyed by capability.

    Currency is derived from the supersedes chain, not from filenames -- the same
    rule the selection builder uses, imported rather than restated.
    """

    records = [
        _load(path)
        for path in sorted(SELECTION_DIR.glob("*.json"))
        if _load(path).get("schemaVersion") == SELECTION_SCHEMA_VERSION
    ]
    active: dict[str, dict[str, Any]] = {}
    for record in current_records(records):
        if record["lifecycle"]["state"] != "active":
            continue
        validate_selection(record)
        active[scope_key(record)[2]] = record
    return active


def build_pin(run: str | None = None) -> dict[str, Any]:
    assert_repin_transaction_readable()
    # Resolved here rather than as a default argument value, so the derivation runs
    # at call time against the evidence on disk instead of at import time.
    run = run or _pinned_run()
    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run
    curated = REPO_ROOT / "ingestion" / "data" / "curated" / run
    for path in (
        evidence / "gate-a.json",
        evidence / "gate-b.json",
        evidence / "publication-manifest.json",
        evidence / "retention-manifest.json",
    ):
        if not path.is_file():
            raise SystemExit(f"retained evidence is absent: {path}")

    gate_a = _load(evidence / "gate-a.json")
    gate_b = _load(evidence / "gate-b.json")
    manifest = _load(evidence / "publication-manifest.json")
    retention = _load(evidence / "retention-manifest.json")

    for label, gate in (("A", gate_a), ("B", gate_b)):
        if gate.get("status") != "pass":
            raise SystemExit(f"Gate {label} is {gate.get('status')!r}, not pass")

    # The pin must name the publication decision #73 selected, for every
    # capability the pin claims. Deriving the pin from evidence alone would still
    # let it point at a publication nobody approved.
    active = _active_selections()
    for capability in REQUIRED_CAPABILITIES:
        selection = active.get(capability)
        if selection is None:
            raise SystemExit(
                f"no active decision-#73 selection for {capability}; create one "
                "before pinning a publication that claims it"
            )
        declared = selection["publication"]
        if declared["sourceSnapshotId"] != manifest["sourceSnapshotId"]:
            raise SystemExit(
                f"the active {capability} selection names snapshot "
                f"{declared['sourceSnapshotId'][:12]}… but this pin would name "
                f"{manifest['sourceSnapshotId'][:12]}…"
            )
        if (
            declared["publicationSemanticFingerprint"]
            != manifest["semanticFingerprint"]
        ):
            raise SystemExit(
                f"the active {capability} selection names a different publication "
                "fingerprint than the retained manifest"
            )
        if not capability_is_available(
            gate_b.get("capabilityMask"), capability, subject=run
        ):
            mask = (gate_b.get("capabilityMask") or {}).get(capability) or {}
            raise SystemExit(
                f"{capability} is required by the pin but unavailable in the "
                f"retained capability mask: {mask.get('reasonCodes') or mask}"
            )

    duckdb = manifest["duckdb"]
    duckdb_path = curated / duckdb["path"]
    if duckdb_path.is_file():
        # Recompute when the bytes are here. A pin whose hash came only from the
        # manifest that also declared it proves the manifest is self-consistent.
        actual = _sha256(duckdb_path)
        if actual != duckdb["sha256"]:
            raise SystemExit(
                f"curated DuckDB hash mismatch: manifest {duckdb['sha256'][:12]}…, "
                f"file {actual[:12]}…"
            )
        actual_bytes = duckdb_path.stat().st_size
        if actual_bytes != duckdb["bytes"]:
            raise SystemExit(
                f"curated DuckDB size mismatch: manifest {duckdb['bytes']}, "
                f"file {actual_bytes}"
            )

    return {
        "$schema": "./input-bundle.schema.json",
        "schemaVersion": "retail-ml-expected-pin/v1",
        "sourceSnapshotId": manifest["sourceSnapshotId"],
        "gateA": {
            "status": gate_a["status"],
            "semanticFingerprint": gate_a["semanticFingerprint"],
            "evidenceSha256": retention["files"]["gate-a.json"],
        },
        "gateB": {
            "status": gate_b["status"],
            "semanticFingerprint": gate_b["semanticFingerprint"],
            "evidenceSha256": retention["files"]["gate-b.json"],
        },
        "publication": {
            "semanticFingerprint": manifest["semanticFingerprint"],
            "gateBSemanticFingerprint": manifest["gateBSemanticFingerprint"],
            "evidenceSha256": retention["files"]["publication-manifest.json"],
            "objectCount": len(manifest["objects"]),
            "duckdb": {
                "bytes": duckdb["bytes"],
                "path": duckdb["path"],
                "sha256": duckdb["sha256"],
            },
        },
        "retention": {
            "schemaVersion": retention["schemaVersion"],
            "publicationFingerprint": retention["publicationFingerprint"],
            "files": dict(retention["files"]),
        },
        "requiredCapabilities": list(REQUIRED_CAPABILITIES),
    }


def _promoted_runs() -> list[str]:
    """Run ids that have retained publication evidence, oldest path order."""

    evidence = REPO_ROOT / "ingestion" / "data" / "evidence"
    return sorted(
        path.name
        for path in evidence.glob("run-*")
        if (path / "publication-manifest.json").is_file()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed pin matches a fresh derivation",
    )
    parser.add_argument(
        "--run",
        default=None,
        help=(
            "publication run id to pin, e.g. run-0123456789abcdef. Defaults to "
            "the committed pin's own run so --check needs no argument. Decision "
            "#89 makes moving the pin a governed act: state the run explicitly "
            "rather than letting a newest-wins glob choose it."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list run ids that have retained publication evidence, and exit",
    )
    args = parser.parse_args(argv)

    if args.list:
        available = _promoted_runs()
        # Guarded for the same reason the --check comparison is: `_pinned_run()`
        # refuses to guess between several retained runs, and a LISTING is exactly
        # when a caller needs to see those runs rather than be told to disambiguate
        # them. Raising here made the command that answers "which runs are there?"
        # fail because there was more than one.
        try:
            print(f"currently pinned: {_pinned_run()}")
        except SystemExit as ambiguity:
            print(f"currently pinned: undetermined -- {ambiguity}")
        if available:
            for run in available:
                print(f"  retained evidence: {run}")
        else:
            print("  no run has retained publication evidence")
        return 0

    run = args.run or _pinned_run()
    # The guard exists to stop `--check --run X` quietly verifying a derivation other
    # than the committed pin's. It must not itself fail when the caller has already
    # supplied the answer: `_pinned_run()` refuses to guess between several retained
    # runs, so calling it unconditionally made `--check --run X` die telling the
    # caller to "pass --run" with --run right there on the command line. When the run
    # cannot be derived there is nothing to contradict, and `--check` compares the
    # derived pin against the committed file regardless -- so skipping the guard
    # loses no safety.
    if args.check and args.run:
        try:
            committed = _pinned_run()
        except SystemExit:
            committed = None
        if committed is not None and args.run != committed:
            print(
                f"--check verifies the committed pin, which names {committed}; "
                f"--run {args.run} would verify a different derivation",
                file=sys.stderr,
            )
            return 2
    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run
    if not (evidence / "publication-manifest.json").is_file():
        available = _promoted_runs()
        print(
            f"{run}: no retained publication evidence at "
            f"{evidence.relative_to(REPO_ROOT)}. "
            + (
                "Runs with retained evidence: " + ", ".join(available)
                if available
                else "No run has retained evidence; publish one first."
            ),
            file=sys.stderr,
        )
        return 2

    pin = build_pin(run=run)
    if args.check:
        if not PIN_PATH.is_file():
            print("contracts/ml/expected-pin.json is absent", file=sys.stderr)
            return 1
        if _load(PIN_PATH) != pin:
            print(
                "contracts/ml/expected-pin.json does not match a fresh derivation "
                "from retained evidence",
                file=sys.stderr,
            )
            return 1
        print("expected-pin.json matches its derivation")
        return 0

    # Written through an explicit binary write rather than `write_text(newline=...)`:
    # that keyword is 3.10+, and this tool is reachable from an orchestrator running
    # whichever `python3` is on PATH -- which on macOS is still 3.9. The point of the
    # keyword was to keep the file LF on every platform, and encoding the bytes here
    # does that unconditionally.
    atomic_write_bytes(
        PIN_PATH, (json.dumps(pin, indent=2) + "\n").encode("utf-8")
    )
    print(
        f"wrote {PIN_PATH.relative_to(REPO_ROOT)}\n"
        f"  snapshot:    {pin['sourceSnapshotId']}\n"
        f"  publication: {pin['publication']['semanticFingerprint']}\n"
        f"  objects:     {pin['publication']['objectCount']}\n"
        f"  capabilities:{' ' + ', '.join(pin['requiredCapabilities'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
