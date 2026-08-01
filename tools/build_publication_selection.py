"""Create and maintain the decision-#73 selection lifecycle for every scope.

`P4-0` tasks 4 and 5 established the first chain: the Phase 3 source pin had been
adopted by replacing `contracts/ml/expected-pin.json` during an authorized
clean-slate rebuild, which is a file edit and not a selection. No `selectionId`
existed anywhere, so "who approved this publication for this scope" had no
recorded answer while a forecast was already serving from it.

`P4-3` adds two more chains and retires one. The ten-year v13 publication is a
different publication, so it is a different selection -- `IDENTITY_EXCLUDES` keeps
`lifecycle` out of semantic identity, which means the selection id follows the
scope and the publication and nothing else. Three things therefore happen here:

* the Phase 3 `demand_forecast_non_pit` selection transitions to `superseded`,
  because the forecast is refit on the new pin and two active selections for one
  scope is a hard failure rather than a race;
* a new `demand_forecast_non_pit` chain is derived for the ten-year publication;
* a new `inventory_replenishment_replay` chain is derived for it, which is the
  capability the Phase 4 inventory bundle consumes.

The lifecycle machinery has existed since PP3-A7 in
`retail_ingestion.readiness.selection`; this only generates records from it, so
the derived ids are the module's own, and verifies every field against the
retained publication manifest and gate evidence rather than against plan prose.

Three things this deliberately does NOT do:

* It does not fabricate a superseded selection for the pre-Phase-3
  `db3784fd…` / `681090ee…` pin. No selection ever existed for it, so it is
  recorded as a `legacy_unselected_predecessor`. Inventing a supersession chain
  would make an ungoverned pin look governed in retrospect, which is the exact
  confusion decision #93 was written to stop. That is different from the Phase 3
  pin below, which HAS a real chain and so gets a real supersession.
* It does not invent a separate readiness report fingerprint. The readiness
  verdict lives in the retained `gate-b.json` capability mask, so that evidence's
  own fingerprint is bound and named for what it is.
* It does not create a selection for `inventory_replenishment_current_snapshot`,
  even though Gate B reports it available. Nothing resolves it: P4-D15 makes the
  bundle the activation unit and the bundle names one source selection, and the
  replay capability is strictly the stronger claim -- it requires everything the
  current claim requires plus origin-safety. An active selection with no consumer
  is a claim nobody checks.
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

RETAILER_ID = "retailer-demo"
TENANT_ID = "tenant-demo"
ENVIRONMENT = "local"
ACTOR = "nilay.shah"

#: The Phase 3 publication, still the source of the currently serving forecast
#: until P4-1 republishes on the ten-year pin.
PHASE_3_RUN = "run-c5eb1506ecd4c550"
PHASE_3_APPROVED_AT = "2026-08-01T00:00:00Z"

#: The ten-year v13 publication produced by P4-3.
PHASE_4_RUN = "run-5bf9580d18d67e36"
PHASE_4_APPROVED_AT = "2026-08-01T20:15:00Z"


def _scope(capability: str) -> dict[str, str]:
    return {
        "retailerId": RETAILER_ID,
        "tenantId": TENANT_ID,
        "capability": capability,
        "environment": ENVIRONMENT,
    }


#: The pin the Phase 3 publication replaced. It never had a selection record, and
#: saying so is the point: `supersedes` stays null because there is no prior
#: recordId to chain to.
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
    "scope": _scope("demand_forecast_non_pit"),
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


def _evidence_dir(run: str) -> Path:
    return REPO_ROOT / "ingestion" / "data" / "evidence" / run


def current_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The head of every lifecycle chain: records nothing supersedes.

    Shared with the contract test so both answer "what is selected right now" the
    same way. Deriving it from `supersedes` rather than from filenames or file
    times means adding a record can only ever move the head forward.
    """

    superseded = {
        str((record.get("lifecycle") or {}).get("supersedes"))
        for record in records
        if (record.get("lifecycle") or {}).get("supersedes")
    }
    return [
        record
        for record in records
        if str((record.get("lifecycle") or {}).get("recordId")) not in superseded
    ]


_current = current_records


def build_candidate(
    *,
    run: str,
    capability: str,
    approved_at: str,
    reason_code: str,
    candidate_reason: str,
) -> dict[str, Any]:
    """Derive one candidate record from retained evidence, or refuse.

    Every field comes from the retained gate and manifest files. Nothing is
    transcribed from a plan or from this script's constants except the scope and
    the audit metadata, which is why a publication that did not pass both gates
    cannot produce a candidate at all.
    """

    evidence = _evidence_dir(run)
    manifest = _load(evidence / "publication-manifest.json")
    gate_a = _load(evidence / "gate-a.json")
    gate_b = _load(evidence / "gate-b.json")

    if gate_a.get("status") != "pass" or gate_b.get("status") != "pass":
        raise SystemExit(
            f"{run}: both gates must pass; gate A = {gate_a.get('status')}, "
            f"gate B = {gate_b.get('status')}"
        )
    mask = gate_b["capabilityMask"].get(capability) or {}
    if not mask.get("available"):
        reasons = mask.get("reasonCodes") or [mask.get("reasonCode")]
        raise SystemExit(
            f"{run}: {capability} is not available in the retained capability "
            f"mask ({reasons})"
        )

    selection: dict[str, Any] = {
        "schemaVersion": SELECTION_SCHEMA_VERSION,
        "scope": _scope(capability),
        "lifecycle": {
            "state": "candidate",
            "supersedes": None,
            "reasonCode": reason_code,
        },
        "publication": {
            "sourceSnapshotId": manifest["sourceSnapshotId"],
            "gateASemanticFingerprint": gate_a["semanticFingerprint"],
            "gateBSemanticFingerprint": manifest["gateBSemanticFingerprint"],
            "publicationSemanticFingerprint": manifest["semanticFingerprint"],
            "logicalPath": f"ingestion/data/curated/{run}",
            "objectCount": len(manifest["objects"]),
            "duckdbSha256": manifest["duckdb"]["sha256"],
        },
        "readiness": {
            # Named for what it is: these publications retain no standalone
            # readiness report, so the capability verdict is the Gate B evidence's
            # own capability mask and that evidence's fingerprint is what binds.
            "reportFingerprint": gate_b["semanticFingerprint"],
            "capabilityReadiness": "ready",
            "capabilitySufficiency": "sufficient",
        },
        "approval": {
            "actor": ACTOR,
            "approvedAt": approved_at,
            "reason": candidate_reason,
        },
    }
    selection["selectionId"] = derive_selection_id(selection)
    selection["lifecycle"]["recordId"] = derive_record_id(selection)
    verify_against_publication(selection, manifest)
    validate_selection(selection)
    return selection


def build_chain(
    *,
    run: str,
    capability: str,
    approved_at: str,
    reason_code: str,
    candidate_reason: str,
    approved_reason: str,
    active_reason: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """candidate -> approved -> active, chained and self-checked."""

    candidate = build_candidate(
        run=run,
        capability=capability,
        approved_at=approved_at,
        reason_code=reason_code,
        candidate_reason=candidate_reason,
    )
    approved = transition(
        candidate,
        "approved",
        actor=ACTOR,
        reason=approved_reason,
        reason_code=reason_code,
    )
    active = transition(
        approved,
        "active",
        actor=ACTOR,
        reason=active_reason,
        reason_code=reason_code,
    )
    chain = (candidate, approved, active)
    for record in chain:
        validate_selection(record)
    selection_ids = {record["selectionId"] for record in chain}
    if len(selection_ids) != 1:
        raise SystemExit(
            f"{capability}: the three records must share one selectionId, "
            f"found {selection_ids}"
        )
    record_ids = [record["lifecycle"]["recordId"] for record in chain]
    if len(set(record_ids)) != 3:
        raise SystemExit(
            f"{capability}: lifecycle record ids must be distinct, found {record_ids}"
        )
    if approved["lifecycle"]["supersedes"] != candidate["lifecycle"]["recordId"]:
        raise SystemExit(f"{capability}: approved does not chain to candidate")
    if active["lifecycle"]["supersedes"] != approved["lifecycle"]["recordId"]:
        raise SystemExit(f"{capability}: active does not chain to approved")
    return chain


def build_lifecycle() -> list[tuple[str, dict[str, Any]]]:
    # -- Phase 3: the chain P4-0 created, now retired -------------------------
    phase_3 = build_chain(
        run=PHASE_3_RUN,
        capability="demand_forecast_non_pit",
        approved_at=PHASE_3_APPROVED_AT,
        reason_code="DECISION_93_ADOPTION",
        candidate_reason=(
            "Decision #93 adoption of the clean-slate rebuild pin that a "
            "forecast already serves. Recorded at P4-0 so the serving "
            "publication has a governed selection rather than a file edit."
        ),
        approved_reason=(
            "Gate A, Gate B, readiness capability mask and publication object "
            "count independently reverified against retained evidence."
        ),
        active_reason=(
            "Adopted as the active source authority for the serving forecast "
            "fr_357575f586905b11 / fv_3d66e3bd9939430d."
        ),
    )
    phase_3_candidate, phase_3_approved, phase_3_active = phase_3

    # -- Phase 4: the ten-year publication ------------------------------------
    forecast_chain = build_chain(
        run=PHASE_4_RUN,
        capability="demand_forecast_non_pit",
        approved_at=PHASE_4_APPROVED_AT,
        reason_code="PHASE_4_TEN_YEAR_REPIN",
        candidate_reason=(
            "The ten-year v13 publication passed Gate A and Gate B with the "
            "store-grain inventory, versioned inbound status and origin-safe "
            "supply terms Phase 4 requires. Proposed as the source authority "
            "the refit forecast and the inventory bundle will share."
        ),
        approved_reason=(
            "Gate A, Gate B, the capability mask, the object count and the "
            "curated DuckDB hash independently reverified against retained "
            "evidence for run-5bf9580d18d67e36."
        ),
        active_reason=(
            "Adopted as the active demand-forecast source authority. The Phase 3 "
            "selection over run-c5eb1506ecd4c550 is superseded in the same "
            "change, so exactly one selection is active for this scope."
        ),
    )
    replay_chain = build_chain(
        run=PHASE_4_RUN,
        capability="inventory_replenishment_replay",
        approved_at=PHASE_4_APPROVED_AT,
        reason_code="PHASE_4_INVENTORY_REPLAY",
        candidate_reason=(
            "Temporal-evidence policy v2 splits the retired "
            "`inventory_replenishment` capability, and this publication is the "
            "first to satisfy the origin-safe replay half: inbound status is "
            "versioned, transfer status is versioned, service lanes are declared, "
            "store-grain inventory exists and supply terms carry admissible "
            "evidence grades."
        ),
        approved_reason=(
            "The replay capability's five reason codes are all absent in the "
            "retained Gate B mask, reverified here rather than read from the "
            "pipeline result."
        ),
        active_reason=(
            "Adopted as the active source authority for the Phase 4 inventory "
            "and replenishment bundle. P4-D15 makes the bundle the activation "
            "unit, so this is the single selection its manifest names."
        ),
    )

    # A real chain gets a real supersession. The Phase 3 selection was governed,
    # unlike the pre-Phase-3 pin disclosed above, so it transitions rather than
    # being disclosed away -- and `approval.reason` names its replacement, which
    # is audit metadata excluded from identity and therefore the only place a
    # forward pointer can live without changing what was selected.
    phase_3_superseded = transition(
        phase_3_active,
        "superseded",
        actor=ACTOR,
        reason=(
            "Superseded by selection "
            f"{forecast_chain[2]['selectionId']} over the ten-year v13 "
            "publication run-5bf9580d18d67e36. The Phase 3 pin lacked "
            "store-grain inventory, versioned inbound status and origin-safe "
            "supply terms, so it cannot back a Phase 4 inventory bundle."
        ),
        reason_code="PHASE_4_TEN_YEAR_REPIN",
    )
    validate_selection(phase_3_superseded)

    everything = [
        phase_3_candidate,
        phase_3_approved,
        phase_3_active,
        phase_3_superseded,
        *forecast_chain,
        *replay_chain,
    ]
    # The Phase 3 active record stays on disk as history, so the directory now
    # holds two records whose state reads `active` for one scope. Resolving that
    # by filename or by mtime would be the arbitrary tie-break decision #90 was
    # written against, so currency is DERIVED: a record is current when nothing
    # else supersedes its recordId. Exactly one current record per scope, and it
    # must be active.
    assert_one_active_per_scope(_current(everything))

    predecessor = dict(LEGACY_UNSELECTED_PREDECESSOR)
    predecessor["supersededBySelectionId"] = phase_3_active["selectionId"]
    predecessor["supersededByRecordId"] = phase_3_active["lifecycle"]["recordId"]

    legacy_prefix = f"{RETAILER_ID}-demand-forecast-{ENVIRONMENT}"
    forecast_prefix = f"{RETAILER_ID}-demand-forecast-ten-year-{ENVIRONMENT}"
    replay_prefix = f"{RETAILER_ID}-inventory-replay-ten-year-{ENVIRONMENT}"
    return [
        (f"{legacy_prefix}-candidate.json", phase_3_candidate),
        (f"{legacy_prefix}-approved.json", phase_3_approved),
        (f"{legacy_prefix}-active.json", phase_3_active),
        (f"{legacy_prefix}-superseded.json", phase_3_superseded),
        (f"{legacy_prefix}-legacy-predecessor.json", predecessor),
        (f"{forecast_prefix}-candidate.json", forecast_chain[0]),
        (f"{forecast_prefix}-approved.json", forecast_chain[1]),
        (f"{forecast_prefix}-active.json", forecast_chain[2]),
        (f"{replay_prefix}-candidate.json", replay_chain[0]),
        (f"{replay_prefix}-approved.json", replay_chain[1]),
        (f"{replay_prefix}-active.json", replay_chain[2]),
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
        expected_names = {name for name, _ in records}
        committed_names = {path.name for path in OUTPUT_DIR.glob("*.json")}
        extra = sorted(committed_names - expected_names)
        if extra:
            print(
                f"selection records exist that no derivation produces: {extra}",
                file=sys.stderr,
            )
            return 1
        for name, record in records:
            path = OUTPUT_DIR / name
            if not path.is_file():
                print(f"missing selection record: {name}", file=sys.stderr)
                return 1
            if _load(path) != record:
                print(f"selection record drifted: {name}", file=sys.stderr)
                return 1
        print(f"{len(records)} selection records match their derivation")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, record in records:
        (OUTPUT_DIR / name).write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(f"wrote {len(records)} records to {OUTPUT_DIR.relative_to(REPO_ROOT)}")
    # Only chain heads, so a superseded record cannot read as a second authority.
    for record in current_records([record for _, record in records]):
        lifecycle = record.get("lifecycle")
        if not lifecycle:
            continue
        print(
            f"  {lifecycle['state']:11s} {record['scope']['capability']:42s} "
            f"{record['selectionId']}  rec {lifecycle['recordId']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
