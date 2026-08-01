"""Create the decision-#73 candidate -> approved -> active selection lifecycle.

`P4-0` tasks 4 and 5. The current source pin was established by replacing
`contracts/ml/expected-pin.json` during an authorized clean-slate rebuild. That is
a file edit, not a selection: no `selectionId` existed anywhere, so the question
"who approved this publication for this scope" had no recorded answer while a
forecast was already serving from it.

The lifecycle machinery has existed since PP3-A7 in
`retail_ingestion.readiness.selection`; only the records were missing. This
generates them from that module so the derived ids are the module's own, and
verifies every field against the retained publication manifest and gate evidence
rather than against the plan's prose.

Two things this deliberately does NOT do:

* It does not fabricate a superseded selection for the prior
  `db3784fd…` / `681090ee…` pin. No selection ever existed for it, so it is
  recorded as a `legacy_unselected_predecessor` on the candidate record. Inventing
  a supersession chain would make an ungoverned pin look governed in retrospect,
  which is the exact confusion decision #93 was written to stop.
* It does not invent a separate readiness report fingerprint. The readiness
  verdict for this pin lives in the retained `gate-b.json` capability mask, so
  that evidence's own fingerprint is bound and named for what it is.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))

from retail_ingestion.readiness.selection import (  # noqa: E402
    SELECTION_SCHEMA_VERSION,
    assert_one_active_per_scope,
    derive_record_id,
    derive_selection_id,
    transition,
    validate_selection,
    verify_against_publication,
)

OUTPUT_DIR = REPO_ROOT / "contracts" / "evidence" / "publication-selections"
PUBLICATION_LOGICAL_PATH = "ingestion/data/curated/run-c5eb1506ecd4c550"
EVIDENCE_DIR = REPO_ROOT / "ingestion" / "data" / "evidence" / "run-c5eb1506ecd4c550"

SCOPE = {
    "retailerId": "retailer-demo",
    "tenantId": "tenant-demo",
    "capability": "demand_forecast_non_pit",
    "environment": "local",
}

APPROVED_AT = "2026-08-01T00:00:00Z"
ACTOR = "nilay.shah"

#: The pin this publication replaced. It never had a selection record, and saying
#: so is the point: `supersedes` stays null because there is no prior recordId to
#: chain to.
#:
#: This lives in a sibling record rather than inside the selection for two
#: reasons, and both are structural rather than stylistic. `publication-selection.
#: schema.json` is `additionalProperties: false`, so an extra key makes the record
#: schema-invalid; and any key outside `IDENTITY_EXCLUDES` participates in the
#: semantic identity, so carrying it on the candidate alone gave that record a
#: different `selectionId` from the approved and active records that must share
#: one. The expected-pin repin record already set this precedent for the same
#: reason: the machine-checkable artifact stays frozen and the reasoning lives
#: beside it.
LEGACY_UNSELECTED_PREDECESSOR = {
    "schemaVersion": "retail-publication-selection-predecessor/v1",
    "recordType": "legacy_unselected_predecessor_disclosure",
    "scope": dict(SCOPE),
    "classification": "legacy_unselected_predecessor",
    "sourceSnapshotId": (
        "681090eed03ae17263b31879e88adefbce0871aed5b12c6b36b1db59a3e4da0b"
    ),
    "publicationSemanticFingerprint": (
        "db3784fdcc4cb8334c2e17d6ae7e0216d05597659df4e9565a99f2b21b8d6fff"
    ),
    "objectCount": 1509,
    "selectionRecordExists": False,
    "bytesRetained": False,
    "note": (
        "Adopted by editing contracts/ml/expected-pin.json during the authorized "
        "clean-slate rebuild. No candidate/approved/active record was ever created "
        "for it and its bytes are gone, so it is disclosed as an unselected "
        "predecessor rather than back-dated into a supersession chain. Logical "
        "equivalence to this pin rests on the retained expected-pin repin record's "
        "control totals and ordered row digests, not on retained artifacts."
    ),
    "equivalenceEvidence": "contracts/evidence/expected-pin-repin-2026-07-31.json",
}


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_candidate() -> dict[str, Any]:
    manifest = _load(EVIDENCE_DIR / "publication-manifest.json")
    gate_a = _load(EVIDENCE_DIR / "gate-a.json")
    gate_b = _load(EVIDENCE_DIR / "gate-b.json")

    if gate_a.get("status") != "pass" or gate_b.get("status") != "pass":
        raise SystemExit(
            f"both gates must pass; gate A = {gate_a.get('status')}, "
            f"gate B = {gate_b.get('status')}"
        )
    capability = gate_b["capabilityMask"].get(SCOPE["capability"]) or {}
    if not capability.get("available"):
        raise SystemExit(
            f"{SCOPE['capability']} is not available in the retained capability mask"
        )

    selection: dict[str, Any] = {
        "schemaVersion": SELECTION_SCHEMA_VERSION,
        "scope": dict(SCOPE),
        "lifecycle": {
            "state": "candidate",
            "supersedes": None,
            "reasonCode": "DECISION_93_ADOPTION",
        },
        "publication": {
            "sourceSnapshotId": manifest["sourceSnapshotId"],
            "gateASemanticFingerprint": gate_a["semanticFingerprint"],
            "gateBSemanticFingerprint": manifest["gateBSemanticFingerprint"],
            "publicationSemanticFingerprint": manifest["semanticFingerprint"],
            "logicalPath": PUBLICATION_LOGICAL_PATH,
            "objectCount": len(manifest["objects"]),
            "duckdbSha256": manifest["duckdb"]["sha256"],
        },
        "readiness": {
            # Named for what it is: this pin retained no standalone readiness
            # report, so the capability verdict is the Gate B evidence's own
            # capability mask and that evidence's fingerprint is what binds.
            "reportFingerprint": gate_b["semanticFingerprint"],
            "capabilityReadiness": "ready",
            "capabilitySufficiency": "sufficient",
        },
        "approval": {
            "actor": ACTOR,
            "approvedAt": APPROVED_AT,
            "reason": (
                "Decision #93 adoption of the clean-slate rebuild pin that a "
                "forecast already serves. Recorded at P4-0 so the serving "
                "publication has a governed selection rather than a file edit."
            ),
        },
    }
    selection["selectionId"] = derive_selection_id(selection)
    selection["lifecycle"]["recordId"] = derive_record_id(selection)
    verify_against_publication(selection, manifest)
    validate_selection(selection)
    return selection


def build_lifecycle() -> list[tuple[str, dict[str, Any]]]:
    candidate = build_candidate()
    approved = transition(
        candidate,
        "approved",
        actor=ACTOR,
        reason=(
            "Gate A, Gate B, readiness capability mask and publication object "
            "count independently reverified against retained evidence."
        ),
        reason_code="DECISION_93_ADOPTION",
    )
    active = transition(
        approved,
        "active",
        actor=ACTOR,
        reason=(
            "Adopted as the active source authority for the serving forecast "
            "fr_357575f586905b11 / fv_3d66e3bd9939430d."
        ),
        reason_code="DECISION_93_ADOPTION",
    )
    for record in (candidate, approved, active):
        validate_selection(record)
    assert_one_active_per_scope([candidate, approved, active])

    selection_ids = {record["selectionId"] for record in (candidate, approved, active)}
    if len(selection_ids) != 1:
        raise SystemExit(
            f"the three records must share one selectionId, found {selection_ids}"
        )
    record_ids = [record["lifecycle"]["recordId"] for record in (candidate, approved, active)]
    if len(set(record_ids)) != 3:
        raise SystemExit(f"lifecycle record ids must be distinct, found {record_ids}")
    if approved["lifecycle"]["supersedes"] != candidate["lifecycle"]["recordId"]:
        raise SystemExit("approved record does not chain to the candidate record")
    if active["lifecycle"]["supersedes"] != approved["lifecycle"]["recordId"]:
        raise SystemExit("active record does not chain to the approved record")

    prefix = f"{SCOPE['retailerId']}-demand-forecast-{SCOPE['environment']}"
    predecessor = dict(LEGACY_UNSELECTED_PREDECESSOR)
    predecessor["supersededBySelectionId"] = active["selectionId"]
    predecessor["supersededByRecordId"] = active["lifecycle"]["recordId"]
    return [
        (f"{prefix}-candidate.json", candidate),
        (f"{prefix}-approved.json", approved),
        (f"{prefix}-active.json", active),
        (f"{prefix}-legacy-predecessor.json", predecessor),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed records match a fresh derivation",
    )
    args = parser.parse_args(argv)

    records = build_lifecycle()
    if args.check:
        for name, record in records:
            path = OUTPUT_DIR / name
            if not path.is_file():
                print(f"missing selection record: {name}", file=sys.stderr)
                return 1
            committed = _load(path)
            if committed != record:
                print(f"selection record drifted: {name}", file=sys.stderr)
                return 1
        print(f"{len(records)} selection records match their derivation")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, record in records:
        (OUTPUT_DIR / name).write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    active = next(
        record
        for _, record in records
        if (record.get("lifecycle") or {}).get("state") == "active"
    )
    print(
        f"wrote {len(records)} records to "
        f"{OUTPUT_DIR.relative_to(REPO_ROOT)}\n"
        f"  selectionId: {active['selectionId']}\n"
        f"  active recordId: {active['lifecycle']['recordId']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
