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
`P4-7` then added a fourth chain, and the reason it was missing is worth keeping.
An earlier version of this file argued that
`inventory_replenishment_current_snapshot` needed no selection because the replay
capability was "strictly the stronger claim". That was wrong in a way only running
the pipeline revealed: twelve of the bundle's thirteen artifacts are current state
and consume no replay at all, so when the replay oracle failed to reproduce this
network's weekly stock they were withheld along with it -- observed positions,
ageing, valuation, all of it -- for want of a capability none of them depends on.
The two capabilities rest on different evidence and fail independently, which is
exactly why temporal-evidence policy v2 split them, and each therefore needs its
own governed selection.
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

#: The same source snapshot, re-ingested at P4-10 after the adapter began landing
#: the store echelon's write-offs. Same raw evidence, different canonical content,
#: therefore a different publication and a different selection -- the identity of
#: a selection follows the publication fingerprint, not the snapshot behind it.
PHASE_4R2_RUN = "run-5bf9580d18d67e36-r2"
PHASE_4R2_APPROVED_AT = "2026-08-02T00:00:00Z"

#: A regenerated source run, not a re-ingest of the same one. The store
#: replenishment policy was tightened at P4-12 -- seven days of cover against a
#: seven-day review cycle, one unit of safety stock, two days of lane transit --
#: because the previous policy replenished faster than any store could sell and
#: no store ever ran out. Every availability measure saturated, so the screens
#: had nothing to report and the product had nothing to demonstrate.
PHASE_4R3_RUN = "run-ae5fcbcb9b8abb34"
PHASE_4R3_APPROVED_AT = "2026-08-02T12:00:00Z"

#: P4-12c. The run that finally publishes `store_stockout_events`, plus the store
#: unit-cost correction. Both are source-side, so they need a new publication and
#: a new pin rather than a rebuild on the old one.
PHASE_4R4_RUN = "run-b847177c11ac724d"
PHASE_4R4_APPROVED_AT = "2026-08-03T00:00:00Z"

#: P4-12e. The from-scratch rebuild on datagen 0.16.0. Lane transit was one of two
#: run-wide constants, so every rank-1 lane resolved the same lead time and the
#: planner's Lead Time and Expected Receipt columns were one value repeated down
#: the page. It is source-side, so it needs a new publication and a new pin rather
#: than a rebuild on the old one.
PHASE_4R5_RUN = "run-adac9e85dccb56e8"
PHASE_4R5_APPROVED_AT = "2026-08-04T00:00:00Z"

#: The Windows-host regeneration, run to measure cross-platform stage timings
#: against the macOS baseline in `docs/pipeline-stage-timings.md`. It carries the
#: `-r6` suffix for the same reason `-r2` did: the source run id is deterministic
#: and reproduced exactly, so a re-publication of it cannot share the curated and
#: evidence roots of the generation it replaces without overwriting the artifacts
#: those committed records attest to. That is what happened here before the rename,
#: and it is what put r5 in EVIDENCE_RELEASED_RUNS below.
PHASE_4R6_RUN = "run-adac9e85dccb56e8-r6"
PHASE_4R6_APPROVED_AT = "2026-08-05T00:00:00Z"


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


#: Runs whose retained evidence was destroyed on 2026-08-04 during an authorized
#: full-rebuild wipe: `ingestion/data/evidence/` was cleared along with the bulk
#: run data, and it was never tracked in git.
#:
#: Their selection records remain committed and unchanged. Each record already
#: embeds every value the derivation produces -- both gate fingerprints, the
#: publication fingerprint, the object count and the DuckDB digest -- so the
#: ledger and its supersession chain survive intact. What does NOT survive is the
#: ability to re-derive those values from source evidence, and that distinction is
#: disclosed here rather than papered over.
#:
#: A run listed here is reproduced from its own committed record. A run that is
#: neither listed here nor has retained evidence still refuses, so this can never
#: become a way to mint a selection nobody verified.
EVIDENCE_RELEASED_RUNS: dict[str, str] = {
    "run-c5eb1506ecd4c550": "Phase 3 serving publication",
    "run-5bf9580d18d67e36": "P4-3 ten-year v13 publication",
    "run-5bf9580d18d67e36-r2": "P4-10 re-ingest of the same snapshot",
    "run-ae5fcbcb9b8abb34": "P4-12 tightened store replenishment policy",
    "run-b847177c11ac724d": "P4-12c store_stockout_events and unit-cost fix",
    # The r6 Windows regeneration republished the same deterministic run id, and
    # before the `-r6` rename it wrote over this generation's curated and evidence
    # roots. The bytes these records were derived FROM are therefore gone, so they
    # are reproduced from their own committed blocks rather than re-derived. Listing
    # it here is the disclosure, not a workaround: a run that is neither listed nor
    # has retained evidence still refuses.
    "run-adac9e85dccb56e8": "P4-12e per-lane transit publication",
    # The Windows regeneration's own publication. Released when the derived data was
    # wiped for a clean ingestion-onward rebuild, which is the ordinary end of a
    # publication's life rather than an incident: `ingestion/data/evidence/<run>` is
    # run data and gets deleted, while the record that selected it is a committed
    # contract and does not. This is the same disclosure r5 carries, arrived at the
    # same way, and it is why the two things called "evidence" must not be confused.
    "run-adac9e85dccb56e8-r6": "Windows-host regeneration publication",
}

#: Counted so `--check` can report how much of the ledger still rests on retained
#: bytes rather than reporting a bare pass.
_reproduced_runs: set[str] = set()
_derived_runs: set[str] = set()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _evidence_dir(run: str) -> Path:
    return REPO_ROOT / "ingestion" / "data" / "evidence" / run


def _recorded_blocks(run: str, capability: str) -> tuple[dict[str, Any], str] | None:
    """The publication block and readiness fingerprint a committed record carries.

    Matched on the logical path and capability rather than on a filename, so the
    lookup cannot drift when a record is renamed.
    """

    target = f"ingestion/data/curated/{run}"
    for path in sorted(OUTPUT_DIR.glob("*.json")):
        record = _load(path)
        publication = record.get("publication") or {}
        scope = record.get("scope") or {}
        if (
            publication.get("logicalPath") == target
            and scope.get("capability") == capability
        ):
            readiness = record.get("readiness") or {}
            return publication, str(readiness.get("reportFingerprint"))
    return None


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
    actor: str = ACTOR,
) -> dict[str, Any]:
    """Derive one candidate record from retained evidence, or refuse.

    Every field comes from the retained gate and manifest files. Nothing is
    transcribed from a plan or from this script's constants except the scope and
    the audit metadata, which is why a publication that did not pass both gates
    cannot produce a candidate at all.
    """

    evidence = _evidence_dir(run)
    if not (evidence / "publication-manifest.json").is_file():
        # No retained evidence. Reproduce the record that was derived when the
        # evidence existed, or refuse -- never invent one.
        if run not in EVIDENCE_RELEASED_RUNS:
            raise SystemExit(
                f"{run}: no retained evidence at {evidence} and the run is not a "
                "declared evidence-released run. A selection cannot be derived "
                "without the gate and manifest files it is derived FROM."
            )
        blocks = _recorded_blocks(run, capability)
        if blocks is None:
            raise SystemExit(
                f"{run}: declared evidence-released but no committed selection "
                f"record carries its {capability} publication block, so there is "
                "nothing to reproduce it from."
            )
        publication, readiness_fingerprint = blocks
        _reproduced_runs.add(run)
        selection = {
            "schemaVersion": SELECTION_SCHEMA_VERSION,
            "scope": _scope(capability),
            "lifecycle": {
                "state": "candidate",
                "supersedes": None,
                "reasonCode": reason_code,
            },
            "publication": dict(publication),
            "readiness": {
                "reportFingerprint": readiness_fingerprint,
                "capabilityReadiness": "ready",
                "capabilitySufficiency": "sufficient",
            },
            "approval": {
                "actor": actor,
                "approvedAt": approved_at,
                "reason": candidate_reason,
            },
        }
        selection["selectionId"] = derive_selection_id(selection)
        selection["lifecycle"]["recordId"] = derive_record_id(selection)
        # verify_against_publication is deliberately NOT called: there is no
        # manifest to verify against, which is the whole disclosure.
        validate_selection(selection)
        return selection

    _derived_runs.add(run)
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
            "actor": actor,
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
    actor: str = ACTOR,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """candidate -> approved -> active, chained and self-checked."""

    candidate = build_candidate(
        run=run,
        capability=capability,
        approved_at=approved_at,
        reason_code=reason_code,
        candidate_reason=candidate_reason,
        actor=actor,
    )
    approved = transition(
        candidate,
        "approved",
        actor=actor,
        reason=approved_reason,
        reason_code=reason_code,
    )
    active = transition(
        approved,
        "active",
        actor=actor,
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


#: Generations added after r6, as data rather than source. Appended by
#: `tools/dev.py repin --approve`; derived into records by `_derived_generations`.
GENERATIONS_PATH = (
    REPO_ROOT / "contracts" / "evidence" / "publication-selection-generations.json"
)

#: The actor recorded when no human supplied one. Deliberately not a person's name:
#: an auto-adopted publication is a real, defensible event, but a record claiming a
#: human approved something nobody read is worse than no record at all, because every
#: reader downstream treats the ledger as evidence that someone looked.
AUTOMATED_ACTOR = "automated/repin-policy/v1"

#: Suffix on the ledger tag, so `-r7-active.json` follows `-r6-active.json` and the
#: committed filenames stay sortable and obviously sequential.
_GENERATION_CAPABILITIES = (
    "demand_forecast_non_pit",
    "inventory_replenishment_current_snapshot",
    "inventory_replenishment_replay",
)


def load_generations() -> list[dict[str, Any]]:
    if not GENERATIONS_PATH.is_file():
        return []
    return list(_load(GENERATIONS_PATH).get("generations") or [])


def next_generation_tag() -> str:
    """`r7`, `r8`, ... -- the tag the next adopted publication will carry.

    Derived from the ledger rather than passed in, because a caller guessing the tag
    is a caller who can collide with a committed record.
    """

    highest = 6  # r6 is the last hand-written generation.
    for entry in load_generations():
        tag = str(entry.get("tag") or "")
        if tag.startswith("r") and tag[1:].isdigit():
            highest = max(highest, int(tag[1:]))
    return f"r{highest + 1}"


def _derived_generations(
    *,
    previous_actives: dict[str, dict[str, Any]],
    prefixes: dict[str, str],
) -> list[tuple[str, dict[str, Any]]]:
    """Build candidate/approved/active plus the predecessor's supersession.

    One entry in the ledger becomes ten records: three states per capability plus one
    supersession per capability. That ten-for-one ratio is the whole reason this is
    data now -- it is exactly the boilerplate that made a hand-edited generation a
    five-file change, and none of it carries information a human chose.
    """

    out: list[tuple[str, dict[str, Any]]] = []
    active = dict(previous_actives)
    for entry in load_generations():
        run = entry["run"]
        tag = entry["tag"]
        actor = entry.get("actor") or AUTOMATED_ACTOR
        reason_code = entry["reasonCode"]
        for capability in _GENERATION_CAPABILITIES:
            chain = build_chain(
                run=run,
                capability=capability,
                approved_at=entry["approvedAt"],
                reason_code=reason_code,
                candidate_reason=entry["candidateReason"],
                approved_reason=entry["approvedReason"],
                active_reason=entry["activeReason"],
                actor=actor,
            )
            superseded = transition(
                active[capability],
                "superseded",
                actor=actor,
                reason=(
                    f"Superseded by selection {chain[2]['selectionId']} over "
                    f"publication {run}. {entry['supersedeReason']} "
                    f"Scope: {capability}."
                ),
                reason_code=reason_code,
            )
            validate_selection(superseded)
            prefix = prefixes[capability]
            out.append((f"{prefix}-{entry['supersedesTag']}-superseded.json", superseded))
            for state, record in zip(("candidate", "approved", "active"), chain):
                out.append((f"{prefix}-{tag}-{state}.json", record))
            active[capability] = chain[2]
    return out


def append_generation(
    *,
    run: str,
    approved_at: str,
    reason_code: str,
    candidate_reason: str,
    approved_reason: str,
    active_reason: str,
    supersede_reason: str,
    actor: str | None,
) -> dict[str, Any]:
    """Append one generation to the ledger and return it.

    `actor=None` records the automated actor. There is no path here that writes a
    human name the caller did not supply.
    """

    document = _load(GENERATIONS_PATH)
    generations = list(document.get("generations") or [])
    tag = next_generation_tag()
    supersedes_tag = f"r{int(tag[1:]) - 1}"
    entry = {
        "tag": tag,
        "run": run,
        "supersedesTag": supersedes_tag,
        "approvedAt": approved_at,
        "reasonCode": reason_code,
        "actor": actor or AUTOMATED_ACTOR,
        "approvalMode": "human" if actor else "automatic",
        "candidateReason": candidate_reason,
        "approvedReason": approved_reason,
        "activeReason": active_reason,
        "supersedeReason": supersede_reason,
    }
    generations.append(entry)
    document["generations"] = generations
    GENERATIONS_PATH.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return entry


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
    current_chain = build_chain(
        run=PHASE_4_RUN,
        capability="inventory_replenishment_current_snapshot",
        approved_at=PHASE_4_APPROVED_AT,
        reason_code="PHASE_4_CURRENT_SNAPSHOT",
        candidate_reason=(
            "Store-grain and DC positions, batches, costs, lanes and terms are all "
            "present at the cutoff, which is what a current-state claim needs. This "
            "capability backs the twelve artifacts computed from observed state and "
            "the served forecast; none of them consumes a replay."
        ),
        approved_reason=(
            "Gate B reports the capability available with no missing entities, "
            "reverified here against the retained mask rather than the pipeline "
            "result."
        ),
        active_reason=(
            "Adopted as the active source authority for the current-state half of "
            "the Phase 4 bundle. It is selected separately from the replay "
            "capability because the two rest on different evidence and fail "
            "independently -- which is why policy v2 split them."
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

    # -- P4-10: the same snapshot re-ingested with store waste ----------------
    #
    # `raw_business_central.store_waste_events` reached staging from the first
    # landing and never reached canonical, so `waste_events` held DC write-offs
    # only. The weekly replay reconstructs store stock from opening, arrivals and
    # demand, and with a whole flow missing its closing balance ran ~589 units per
    # week above every observed snapshot -- 0.56 units per cell against a
    # tolerance frozen at 0.5, failing in every period and in one direction.
    #
    # These three chains select the corrected publication for the same three
    # capabilities. Nothing about the tolerance moved; the evidence did.
    r2_reason = (
        "Re-ingested from source snapshot a92f0254 after the Business Central "
        "adapter began landing store_waste_events into the waste_event role. "
        "The store echelon's expiry write-offs are 317,056 units in india-west "
        "against 140,787 at its DCs, so their absence was the larger half of the "
        "write-off evidence, not a rounding difference."
    )
    r2_forecast_chain = build_chain(
        run=PHASE_4R2_RUN,
        capability="demand_forecast_non_pit",
        approved_at=PHASE_4R2_APPROVED_AT,
        reason_code="PHASE_4_STORE_WASTE_REINGEST",
        candidate_reason=r2_reason,
        approved_reason=(
            "Gate A, Gate B, the capability mask, the object count and the "
            "curated DuckDB hash independently reverified against retained "
            "evidence for run-5bf9580d18d67e36-r2."
        ),
        active_reason=(
            "Adopted as the active demand-forecast source authority. The forecast "
            "is refit on this publication, so the selection over "
            "run-5bf9580d18d67e36 is superseded in the same change."
        ),
    )
    r2_current_chain = build_chain(
        run=PHASE_4R2_RUN,
        capability="inventory_replenishment_current_snapshot",
        approved_at=PHASE_4R2_APPROVED_AT,
        reason_code="PHASE_4_STORE_WASTE_REINGEST",
        candidate_reason=r2_reason,
        approved_reason=(
            "Gate B reports the capability available with no missing entities, "
            "reverified here against the retained mask rather than the pipeline "
            "result."
        ),
        active_reason=(
            "Adopted as the active source authority for the current-state half of "
            "the bundle. The current-state artifacts do not consume the replay, "
            "so this selection would have stood either way; it moves because the "
            "bundle is one activation unit and must name one publication."
        ),
    )
    r2_replay_chain = build_chain(
        run=PHASE_4R2_RUN,
        capability="inventory_replenishment_replay",
        approved_at=PHASE_4R2_APPROVED_AT,
        reason_code="PHASE_4_STORE_WASTE_REINGEST",
        candidate_reason=r2_reason,
        approved_reason=(
            "The replay capability's five reason codes are all absent in the "
            "retained Gate B mask, reverified here rather than read from the "
            "pipeline result."
        ),
        active_reason=(
            "Adopted as the active source authority for the replay half. This is "
            "the capability the missing write-offs were suppressing: the same "
            "mechanism against the same frozen tolerance reconstructs observed "
            "closing stock once the third flow is present."
        ),
    )

    def _supersede(active, replacement, capability, run=None, because=None):
        record = transition(
            active,
            "superseded",
            actor=ACTOR,
            reason=(
                f"Superseded by selection {replacement['selectionId']} over "
                f"publication {run or 'run-5bf9580d18d67e36-r2'}. "
                + (
                    because
                    or "The publication this record selects carries DC write-offs "
                    "only, which leaves the evidence incomplete at the store "
                    "echelon."
                )
                + f" Scope: {capability}."
            ),
            reason_code=(
                "PHASE_4_TIGHTENED_REPLENISHMENT"
                if run
                else "PHASE_4_STORE_WASTE_REINGEST"
            ),
        )
        validate_selection(record)
        return record

    forecast_superseded = _supersede(
        forecast_chain[2], r2_forecast_chain[2], "demand_forecast_non_pit"
    )
    current_superseded = _supersede(
        current_chain[2], r2_current_chain[2],
        "inventory_replenishment_current_snapshot",
    )
    replay_superseded = _supersede(
        replay_chain[2], r2_replay_chain[2], "inventory_replenishment_replay"
    )

    # -- P4-12: the regenerated run with a tightened replenishment policy -------
    r3_reason = (
        "Regenerated source run. The store replenishment policy replenished to 14 "
        "days of cover plus 3 units of safety stock, reviewed weekly, with one day "
        "of transit -- faster than any store could sell, so no store ever ran out. "
        "Zero-stock cells were 0.48 per cent and the in-stock rate 99.08, which "
        "left every availability and fill-rate measure saturated. At seven days of "
        "cover, one unit of safety stock and two days of transit the same "
        "simulation produces 9.39 per cent zero-stock cells and an 82.67 per cent "
        "in-stock rate, inside the range the approved reference shows."
    )
    r3_chains = {
        capability: build_chain(
            run=PHASE_4R3_RUN,
            capability=capability,
            approved_at=PHASE_4R3_APPROVED_AT,
            reason_code="PHASE_4_TIGHTENED_REPLENISHMENT",
            candidate_reason=r3_reason,
            approved_reason=approved,
            active_reason=active,
        )
        for capability, approved, active in (
            (
                "demand_forecast_non_pit",
                "Gate A, Gate B, the capability mask, the object count and the "
                "curated DuckDB hash independently reverified against retained "
                "evidence for run-ae5fcbcb9b8abb34.",
                "Adopted as the active demand-forecast source authority. The "
                "forecast is refit on this publication, so the selection over "
                "run-5bf9580d18d67e36-r2 is superseded in the same change.",
            ),
            (
                "inventory_replenishment_current_snapshot",
                "Gate B reports the capability available with no missing "
                "entities, reverified against the retained mask.",
                "Adopted as the active source authority for the current-state "
                "half of the bundle.",
            ),
            (
                "inventory_replenishment_replay",
                "The replay capability's five reason codes are all absent in the "
                "retained Gate B mask, reverified rather than read from the "
                "pipeline result.",
                "Adopted as the active source authority for the replay half. The "
                "tightened policy changes what the replay reconstructs: less "
                "stock sitting means less expiry, so the write-off term shrinks "
                "from 317,056 units to 26,672 and the oracle is re-measured "
                "against the same frozen tolerance rather than a relaxed one.",
            ),
        )
    }

    # -- P4-12c: the run that publishes the store shortfall ---------------------
    r4_reason = (
        "Regenerated source run. `store_stockout_events` has been computed every "
        "run since source contract v13 and written by none of them: the store "
        "echelon serves what it can and the DC covers the rest, so `sales` records "
        "the whole sale while the shelf drops only by servedFromStoreUnits, and "
        "nothing published the difference. Any shelf-level reconstruction "
        "therefore charged the DC's share to the store. On the tightened network "
        "that is 123,894 units of india-west drift over 52 weeks and the replay "
        "oracle measured 11.05 units per cell against a frozen 0.5. This run also "
        "corrects store transfer receipts, which carried the major-unit base cost "
        "in a field named unitCostMinor, so every store cost was a hundredth of "
        "the truth."
    )
    r4_chains = {
        capability: build_chain(
            run=PHASE_4R4_RUN,
            capability=capability,
            approved_at=PHASE_4R4_APPROVED_AT,
            reason_code="PHASE_4_STORE_SHORTFALL_PUBLISHED",
            candidate_reason=r4_reason,
            approved_reason=approved,
            active_reason=active,
        )
        for capability, approved, active in (
            (
                "demand_forecast_non_pit",
                "Gate A, Gate B, the capability mask, the object count and the "
                "curated DuckDB hash independently reverified against retained "
                "evidence for run-b847177c11ac724d. Gate A rule A13 refused the "
                "first attempt until the new relation carried an explicit "
                "classification, which is the check working rather than an "
                "obstacle.",
                "Adopted as the active demand-forecast source authority. Sales are "
                "unchanged by both corrections -- publishing an already-computed "
                "relation and rescaling a cost column move no sale -- so the "
                "forecast is refit on this publication and lands numerically where "
                "it did, with its lineage now naming the run it was actually fit "
                "on.",
            ),
            (
                "inventory_replenishment_current_snapshot",
                "Gate B reports the capability available with no missing "
                "entities, reverified against the retained mask.",
                "Adopted as the active source authority for the current-state "
                "half. Store unit costs are correct here for the first time, so "
                "store inventory value, cost-weighted ABC and every store service "
                "level stop being understated a hundredfold.",
            ),
            (
                "inventory_replenishment_replay",
                "The replay capability's five reason codes are all absent in the "
                "retained Gate B mask, reverified rather than read from the "
                "pipeline result.",
                "Adopted as the active source authority for the replay half. With "
                "the shortfall published the mass balance closes -- the replay's "
                "own clamp stops firing entirely, 102,533 lost units to zero in "
                "india-west -- and the oracle reproduces at 0.132 and 0.338 units "
                "per cell against the same frozen 0.5 tolerance, never a relaxed "
                "one.",
            ),
        )
    }

    # -- P4-12e: per-lane transit, and a supplier with a name -------------------
    r5_reason = (
        "Regenerated source run. Replenishment lane transit was one of two "
        "run-wide constants and every rank-1 lane took the primary one, so every "
        "recommendation in the network resolved an identical lead time and the "
        "planner's Lead Time and Expected Receipt columns were one value repeated "
        "down the page. Transit now varies per LANE, deterministically in the "
        "lane's own identity and additive on the policy floor. The vendor master "
        "travels with it: `vendors` landed every run and was staged by none of "
        "them, so every supplier a screen named was a UUID. It is now staged, "
        "canonicalised as `suppliers` and declared in the retail_v2 contract -- "
        "the declaration being what makes it validated rather than merely present. "
        "The fingerprints below are also the first ones that MEAN anything across "
        "runs: `landingTime`, the wall clock at which the snapshot was landed, "
        "participated in the staging semantic fingerprint and propagated through the "
        "candidate into the publication, so re-landing byte-identical source moved "
        "the publication fingerprint and no selection record could ever be "
        "re-derived. It is now excluded from identity while still recorded as "
        "provenance, exactly as `completedAt` already was."
    )
    r5_chains = {
        capability: build_chain(
            run=PHASE_4R5_RUN,
            capability=capability,
            approved_at=PHASE_4R5_APPROVED_AT,
            reason_code="PHASE_4_PER_LANE_TRANSIT",
            candidate_reason=r5_reason,
            approved_reason=approved,
            active_reason=active,
        )
        for capability, approved, active in (
            (
                "demand_forecast_non_pit",
                "Gate A, Gate B, the capability mask, the publication "
                "fingerprint and the curated DuckDB hash derived from this run's "
                "own retained evidence rather than reproduced from a committed "
                "record. Sales are unchanged at 7,471,784 rows and the business "
                "controls still read 573 active SKUs at 2026-07-28: a transit "
                "time moves no sale, and that is the equivalence this repin "
                "rests on.",
                "Adopted as the active demand-forecast source authority. The r4 "
                "selection over run-b847177c11ac724d is superseded in the same "
                "change, so exactly one selection is active for this scope. The "
                "forecast is refit here and lands where it did, with its lineage "
                "naming the run it was actually fit on.",
            ),
            (
                "inventory_replenishment_current_snapshot",
                "Gate B reports the capability available with no missing "
                "entities and no reason code, derived from this run's retained "
                "mask. `suppliers` publishes 280 rows and all 197,368 inbound "
                "shipments name their vendor, so supplier identity and open-PO "
                "value have a source for the first time.",
                "Adopted as the active source authority for the current-state "
                "half. Lead times vary per lane here, so the planner's Lead Time "
                "and Expected Receipt columns carry the spread the policy always "
                "implied, and Supplier Planning can name a supplier instead of "
                "printing its hash.",
            ),
            (
                "inventory_replenishment_replay",
                "The replay capability's reason codes are all absent from this "
                "run's Gate B mask, with prematureFulfillmentRows and "
                "prematureStatusRows both zero, derived rather than read from "
                "the pipeline result.",
                "Adopted as the active source authority for the replay half. "
                "Lane transit sizes the protection period, so the reconstruction "
                "moves with it and the oracle is re-measured against the same "
                "frozen 0.5 tolerance rather than a relaxed one.",
            ),
        )
    }

    # -- r6: the Windows-host regeneration ------------------------------------
    #
    # Approved by nilay.shah on 2026-08-05. This is NOT an equivalence re-pin in
    # the sense of nothing having moved: the DATA reproduced and is provably the
    # same, but the ARTIFACT is new, and decision #89 draws that line deliberately.
    # Gate A and Gate B fingerprints are the evidence that the data reproduced;
    # a selection record is the evidence of which artifact was chosen.
    r6_reason = (
        "Ten-year v13 regenerated on a Windows 11 host to measure cross-platform "
        "stage timings against the macOS baseline in "
        "`docs/pipeline-stage-timings.md`. The scenario is deterministic and it "
        "showed: run id run-adac9e85dccb56e8 and the 9,938-object source snapshot "
        "reproduced exactly, and both quality gates pass with all three required "
        "capabilities available. What moved is the artifact, not the data -- "
        "sourceSnapshotId hashes Parquet bytes, so it went from cd20ca5a to "
        "4c205cd1, and the curated DuckDB's internal layout and partition split "
        "moved with it (1,306 curated objects against 1,589). Under decision #89 "
        "that is a new bundle needing a new governed selection rather than an edit "
        "to the record of the old one."
    )
    r6_chains = {
        capability: build_chain(
            run=PHASE_4R6_RUN,
            capability=capability,
            approved_at=PHASE_4R6_APPROVED_AT,
            reason_code="WINDOWS_HOST_REGENERATION",
            candidate_reason=r6_reason,
            approved_reason=approved,
            active_reason=active,
        )
        for capability, approved, active in (
            (
                "demand_forecast_non_pit",
                "Gate A, Gate B, the capability mask, the publication fingerprint "
                "and the curated DuckDB hash all derived from this run's own "
                "retained evidence rather than transcribed from a plan. Gate A "
                "4999fa1a, Gate B 0817812c, publication e5d34f94, DuckDB "
                "f5cec9fa.",
                "Adopted as the active demand-forecast source authority. The r5 "
                "selection over the same run id is superseded in the same change, "
                "so exactly one selection is active for this scope.",
            ),
            (
                "inventory_replenishment_current_snapshot",
                "Gate B reports the capability available with no missing entities "
                "and no reason code, read from this run's own retained mask.",
                "Adopted as the active source authority for the current-state "
                "half of the Phase 4 bundle, selected separately from the replay "
                "capability because the two rest on different evidence.",
            ),
            (
                "inventory_replenishment_replay",
                "The replay capability's reason codes are all absent from this "
                "run's Gate B mask, derived rather than read from the pipeline "
                "result.",
                "Adopted as the active source authority for the replay half. The "
                "oracle is re-measured on this publication against the same "
                "frozen 0.5 tolerance rather than a relaxed one.",
            ),
        )
    }

    r6_superseded = {
        capability: _supersede(
            r5_chains[capability][2], r6_chains[capability][2], capability,
            PHASE_4R6_RUN,
            "The curated and evidence roots this record selects were overwritten "
            "by the r6 regeneration of the same deterministic run id, so the "
            "artifact it names no longer exists on disk. It is retained as "
            "evidence of what was selected, and reproduced from its own committed "
            "block -- see EVIDENCE_RELEASED_RUNS.",
        )
        for capability in (
            "demand_forecast_non_pit",
            "inventory_replenishment_current_snapshot",
            "inventory_replenishment_replay",
        )
    }

    r5_superseded = {
        capability: _supersede(
            r4_chains[capability][2], r5_chains[capability][2], capability,
            PHASE_4R5_RUN,
            "The publication this record selects resolves one lane transit for "
            "every rank-1 lane in the network, so every recommendation shares a "
            "lead time and no screen can show a spread the policy already "
            "declares.",
        )
        for capability in (
            "demand_forecast_non_pit",
            "inventory_replenishment_current_snapshot",
            "inventory_replenishment_replay",
        )
    }

    r4_superseded = {
        capability: _supersede(
            r3_chains[capability][2], r4_chains[capability][2], capability,
            "run-ae5fcbcb9b8abb34",
            "The publication this record selects does not carry "
            "store_stockout_events, so the part of a store sale the shelf could "
            "not cover is unknowable from it and no shelf-level reconstruction "
            "can balance.",
        )
        for capability in (
            "demand_forecast_non_pit",
            "inventory_replenishment_current_snapshot",
            "inventory_replenishment_replay",
        )
    }

    r3_superseded = {
        capability: _supersede(
            chain[2], r3_chains[capability][2], capability,
            "run-ae5fcbcb9b8abb34",
            "The publication this record selects was generated with a "
            "replenishment policy that never ran out of stock.",
        )
        for capability, chain in (
            ("demand_forecast_non_pit", r2_forecast_chain),
            ("inventory_replenishment_current_snapshot", r2_current_chain),
            ("inventory_replenishment_replay", r2_replay_chain),
        )
    }

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
        *current_chain,
        *replay_chain,
        forecast_superseded,
        current_superseded,
        replay_superseded,
        *r2_forecast_chain,
        *r2_current_chain,
        *r2_replay_chain,
        *r3_superseded.values(),
        *(record for chain in r3_chains.values() for record in chain),
        # r4 was written to disk but left out of this list, so the invariant below
        # was being asserted against a ledger that stopped at r3 -- it passed
        # because the r3 actives were the newest thing it could see, not because
        # the directory held one active per scope. Every generation belongs here or
        # the check verifies a subset and reports on the whole.
        *r4_superseded.values(),
        *(record for chain in r4_chains.values() for record in chain),
        *r5_superseded.values(),
        *(record for chain in r5_chains.values() for record in chain),
        *r6_superseded.values(),
        *(record for chain in r6_chains.values() for record in chain),
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
    current_prefix = f"{RETAILER_ID}-inventory-current-ten-year-{ENVIRONMENT}"
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
        (f"{current_prefix}-candidate.json", current_chain[0]),
        (f"{current_prefix}-approved.json", current_chain[1]),
        (f"{current_prefix}-active.json", current_chain[2]),
        (f"{replay_prefix}-candidate.json", replay_chain[0]),
        (f"{replay_prefix}-approved.json", replay_chain[1]),
        (f"{replay_prefix}-active.json", replay_chain[2]),
        (f"{forecast_prefix}-superseded.json", forecast_superseded),
        (f"{current_prefix}-superseded.json", current_superseded),
        (f"{replay_prefix}-superseded.json", replay_superseded),
        (f"{forecast_prefix}-r2-candidate.json", r2_forecast_chain[0]),
        (f"{forecast_prefix}-r2-approved.json", r2_forecast_chain[1]),
        (f"{forecast_prefix}-r2-active.json", r2_forecast_chain[2]),
        (f"{current_prefix}-r2-candidate.json", r2_current_chain[0]),
        (f"{current_prefix}-r2-approved.json", r2_current_chain[1]),
        (f"{current_prefix}-r2-active.json", r2_current_chain[2]),
        (f"{replay_prefix}-r2-candidate.json", r2_replay_chain[0]),
        (f"{replay_prefix}-r2-approved.json", r2_replay_chain[1]),
        (f"{replay_prefix}-r2-active.json", r2_replay_chain[2]),
        (f"{forecast_prefix}-r2-superseded.json",
         r3_superseded["demand_forecast_non_pit"]),
        (f"{current_prefix}-r2-superseded.json",
         r3_superseded["inventory_replenishment_current_snapshot"]),
        (f"{replay_prefix}-r2-superseded.json",
         r3_superseded["inventory_replenishment_replay"]),
        *(
            (f"{prefix}-r3-{state}.json", record)
            for prefix, capability in (
                (forecast_prefix, "demand_forecast_non_pit"),
                (current_prefix, "inventory_replenishment_current_snapshot"),
                (replay_prefix, "inventory_replenishment_replay"),
            )
            for state, record in zip(
                ("candidate", "approved", "active"), r3_chains[capability]
            )
        ),
        (f"{forecast_prefix}-r3-superseded.json",
         r4_superseded["demand_forecast_non_pit"]),
        (f"{current_prefix}-r3-superseded.json",
         r4_superseded["inventory_replenishment_current_snapshot"]),
        (f"{replay_prefix}-r3-superseded.json",
         r4_superseded["inventory_replenishment_replay"]),
        *(
            (f"{prefix}-r4-{state}.json", record)
            for prefix, capability in (
                (forecast_prefix, "demand_forecast_non_pit"),
                (current_prefix, "inventory_replenishment_current_snapshot"),
                (replay_prefix, "inventory_replenishment_replay"),
            )
            for state, record in zip(
                ("candidate", "approved", "active"), r4_chains[capability]
            )
        ),
        (f"{forecast_prefix}-r4-superseded.json",
         r5_superseded["demand_forecast_non_pit"]),
        (f"{current_prefix}-r4-superseded.json",
         r5_superseded["inventory_replenishment_current_snapshot"]),
        (f"{replay_prefix}-r4-superseded.json",
         r5_superseded["inventory_replenishment_replay"]),
        *(
            (f"{prefix}-r5-{state}.json", record)
            for prefix, capability in (
                (forecast_prefix, "demand_forecast_non_pit"),
                (current_prefix, "inventory_replenishment_current_snapshot"),
                (replay_prefix, "inventory_replenishment_replay"),
            )
            for state, record in zip(
                ("candidate", "approved", "active"), r5_chains[capability]
            )
        ),
        (f"{forecast_prefix}-r5-superseded.json",
         r6_superseded["demand_forecast_non_pit"]),
        (f"{current_prefix}-r5-superseded.json",
         r6_superseded["inventory_replenishment_current_snapshot"]),
        (f"{replay_prefix}-r5-superseded.json",
         r6_superseded["inventory_replenishment_replay"]),
        *(
            (f"{prefix}-r6-{state}.json", record)
            for prefix, capability in (
                (forecast_prefix, "demand_forecast_non_pit"),
                (current_prefix, "inventory_replenishment_current_snapshot"),
                (replay_prefix, "inventory_replenishment_replay"),
            )
            for state, record in zip(
                ("candidate", "approved", "active"), r6_chains[capability]
            )
        ),
        # Everything after r6 is DATA, not source. See the note in the generations
        # ledger: the six hand-written chains above are why adopting one publication
        # took five coordinated edits, and they stay hand-written because they are
        # already committed and verified.
        *_derived_generations(
            previous_actives={
                "demand_forecast_non_pit": r6_chains["demand_forecast_non_pit"][2],
                "inventory_replenishment_current_snapshot": r6_chains[
                    "inventory_replenishment_current_snapshot"
                ][2],
                "inventory_replenishment_replay": r6_chains[
                    "inventory_replenishment_replay"
                ][2],
            },
            prefixes={
                "demand_forecast_non_pit": forecast_prefix,
                "inventory_replenishment_current_snapshot": current_prefix,
                "inventory_replenishment_replay": replay_prefix,
            },
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the committed records match a fresh derivation",
    )
    parser.add_argument(
        "--no-clobber",
        action="store_true",
        help=(
            "write only records that are absent; refuse if an existing record's "
            "derivation has moved. What an automated rebuild should use -- a build "
            "step may create a governance record, never silently restate one."
        ),
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
        # A publication with no selection is the failure this check could not see.
        #
        # The run ids are constants on purpose -- each committed record must be
        # reproducible from this file alone, which is why `--check` compares them
        # byte for byte and why the run cannot come from the command line. The gap
        # was the other direction: a newly published run that nobody added a chain
        # for produced no error at all, it simply had no governed selection, and the
        # ML stages would happily consume a publication no record ever selected.
        selected_runs = {
            str((record.get("publication") or {}).get("logicalPath", "")).rsplit(
                "/", 1
            )[-1]
            for _, record in records
        }
        evidence_root = REPO_ROOT / "ingestion" / "data" / "evidence"
        published = {
            path.name
            for path in evidence_root.glob("run-*")
            if (path / "publication-manifest.json").is_file()
        }
        unselected = sorted(published - selected_runs)
        if unselected:
            print(
                "published runs with retained evidence and no selection record: "
                f"{', '.join(unselected)}.\n"
                "Add a chain in build_lifecycle() naming the run, its capability, "
                "an approver and a reason -- a selection is a governed act, so the "
                "actor and reason are deliberately human inputs and cannot be "
                "derived.",
                file=sys.stderr,
            )
            return 1

        # Report the basis, not just the verdict. A bare pass would read as
        # "everything re-derived from retained evidence", which is no longer true
        # for the runs whose evidence was released.
        if _reproduced_runs:
            print(
                f"{len(records)} selection records match their derivation "
                f"({len(_reproduced_runs)} of "
                f"{len(_reproduced_runs) + len(_derived_runs)} runs reproduced "
                "from their committed records; retained evidence for them is gone "
                "-- see EVIDENCE_RELEASED_RUNS)"
            )
            for run in sorted(_reproduced_runs):
                print(f"  reproduced: {run} ({EVIDENCE_RELEASED_RUNS[run]})")
            for run in sorted(_derived_runs):
                print(f"  derived from retained evidence: {run}")
        else:
            print(f"{len(records)} selection records match their derivation")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    unchanged = 0
    for name, record in records:
        path = OUTPUT_DIR / name
        rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
        if args.no_clobber and path.is_file():
            existing = path.read_text(encoding="utf-8")
            if existing == rendered:
                unchanged += 1
                continue
            # A committed record whose derivation has MOVED. Rewriting it is how a
            # ledger stops being evidence: the record would then attest whatever was
            # published most recently rather than what was actually selected, and
            # `--check` would pass against the rewrite. This is reachable in normal
            # use, because a publication fingerprint is not byte-reproducible -- the
            # curated DuckDB's internal layout and the Parquet partition split both
            # move between publishes of identical data, so re-publishing a governed
            # run lands here even though every row is the same. Gate A and Gate B
            # fingerprints are the evidence that the DATA reproduced; this file is
            # the record of which ARTIFACT was chosen, and a new artifact needs a new
            # generation rather than an edit to the old one.
            print(
                f"refusing to overwrite {name}: its derivation has changed.\n"
                "A published artifact this record already selected has been "
                "re-published, so the fingerprints it names no longer exist. Add a "
                "new generation in build_lifecycle() selecting the new publication "
                "and superseding this one -- with an approver and a reason, because "
                "choosing a different artifact is a governed act -- or restore the "
                "publication this record names.",
                file=sys.stderr,
            )
            return 1
        path.write_text(rendered, encoding="utf-8")
        written += 1
    if args.no_clobber:
        print(
            f"wrote {written} record(s), {unchanged} already matched, in "
            f"{OUTPUT_DIR.relative_to(REPO_ROOT)}"
        )
    else:
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
