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

from build_publication_selection import current_records  # noqa: E402

PIN_PATH = REPO_ROOT / "contracts" / "ml" / "expected-pin.json"
SELECTION_DIR = REPO_ROOT / "contracts" / "evidence" / "publication-selections"

#: The publication P4-3 pinned. Named rather than discovered: there is no
#: newest-wins here either, and a caller changing the pin should have to say so.
RUN = "run-5bf9580d18d67e36"

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


def build_pin() -> dict[str, Any]:
    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / RUN
    curated = REPO_ROOT / "ingestion" / "data" / "curated" / RUN
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
        mask = gate_b["capabilityMask"].get(capability) or {}
        if not mask.get("available"):
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed pin matches a fresh derivation",
    )
    args = parser.parse_args(argv)

    pin = build_pin()
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

    PIN_PATH.write_text(
        json.dumps(pin, indent=2) + "\n", encoding="utf-8", newline="\n"
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
