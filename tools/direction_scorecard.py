#!/usr/bin/env python3
"""Measure progress toward the plan section 1 program goal.

Answers one question with evidence rather than assertion: which phases of the
PoC can actually light up right now, and what is blocking the rest.

Every phase is tied to the Gate-B capability mask and the forecast serving
state, so re-running this after any change shows whether the change moved the
program goal or only moved local detail. Run it before and after work.

    python3 tools/direction_scorecard.py
    python3 tools/direction_scorecard.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The PoC is phase-sequential. A phase may be capability-ready and still not
#: startable because its predecessor has not closed, so capability readiness alone
#: overstates progress. `closesWhen` records what actually ends the phase.
PHASE_ORDER: list[str] = [
    "phase_1_datagen",
    "phase_2_ingestion",
    "phase_3_forecast",
    # The two deferred Post-Phase 3 workstreams sit BETWEEN Phase 3 and Phase 4
    # in tasks.md and in the implementation plan's sequencing. Omitting them
    # understates what stands between Phase 3 closure and Phase 4.
    "post_phase_3_track_a",
    "post_phase_3_track_b",
    "phase_4_inventory",
    "phase_5_pricing",
    "phase_6_api_workflow",
    "phase_7_ui",
    "phase_8_analytics",
]

#: Each phase's headline deliverable and the capabilities it cannot fake.
PHASE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "phase_1_datagen": {
        "goal": "deterministic multi-market synthetic source publications",
        "capabilities": [],
        "evidence": "accepted source snapshot and run manifest",
        "closesWhen": "accepted pinned source run",
        "closed": True,
    },
    "phase_2_ingestion": {
        "goal": "raw -> Gate A -> staging -> canonical retail_v2 -> Gate B -> curated",
        "capabilities": ["data_management"],
        "evidence": "Gate B pass with zero reconciliation difference",
        "closesWhen": "Gate B pass and curated publication",
        "closed": True,
    },
    "phase_3_forecast": {
        "goal": "accepted demand forecast serving the Demand Forecast screen live",
        "capabilities": ["demand_forecast_non_pit"],
        "evidence": "an accepted, independently verified forecast run",
        "alsoRequiresForecastServing": True,
        # Phase 3 closes on EITHER an accepted forecast OR an explicit governed
        # NO-GO closure. Acceptance is not the only exit.
        "closesWhen": "accepted forecast OR explicit governed NO-GO closure",
        "closureBranches": ["accepted", "explicit_no_go"],
    },
    "post_phase_3_track_a": {
        "goal": "retailer-source onboarding hardening: neutral roles, adapters, readiness, pins",
        "capabilities": [],
        "evidence": "A-D1..A-D13 delivered plus a recorded Track A acceptance review",
        "closesWhen": "Track A acceptance review recorded",
        "deliverables": [
            "A-D1", "A-D2", "A-D3", "A-D4", "A-D5", "A-D6", "A-D7",
            "A-D8", "A-D9", "A-D10", "A-D11", "A-D12", "A-D13",
        ],
        "delivered": [
            "A-D1", "A-D2", "A-D3", "A-D4", "A-D5", "A-D6", "A-D7",
            "A-D8", "A-D9", "A-D10", "A-D11", "A-D12", "A-D13",
        ],
        "humanGates": [
            "Track A contract/design review",
            "staging v2 cutover decision (currently frozen_not_cut_over)",
            "Track A client-shaped round-trip acceptance",
        ],
    },
    "post_phase_3_track_b": {
        "goal": "forecast quality and presentation hardening",
        "capabilities": [],
        "evidence": "B-D1..B-D12 plus an accepted publication or a published no-go",
        "closesWhen": "accepted candidate publication OR a recorded Track B no-go",
        "deliverables": [
            "B-D1", "B-D2", "B-D3", "B-D4", "B-D5", "B-D6",
            "B-D7", "B-D8", "B-D9", "B-D10", "B-D11", "B-D12",
        ],
        "delivered": ["B-D1", "B-D2", "B-D3", "B-D4", "B-D9", "B-D10"],
        "humanGates": [
            "Track B diagnostic and candidate protocol review",
            "Track B UI target/parity review",
        ],
    },
    "phase_4_inventory": {
        "goal": "reorder, safety stock, transfers, allocation, inventory replay",
        # The two split capabilities, not the retired umbrella. `replenishment` is
        # marked `supersededBy: [inventory_replenishment_current_snapshot,
        # inventory_replenishment_replay]` in the mask itself, and policy v2's
        # retiredReason says why: one flag could not distinguish serviceable
        # current-position analytics from unavailable origin-safe replay. Checking it
        # meant Phase 4 read as unblocked with current-snapshot false, because the
        # legacy flag was still true.
        "capabilities": [
            "inventory_replenishment_current_snapshot",
            "inventory_replenishment_replay",
        ],
        "evidence": "replay and policy holdout pass",
        "alsoRequiresForecastServing": True,
    },
    "phase_5_pricing": {
        "goal": "elasticity, price recommendations, promotion planning",
        "capabilities": ["pricing_elasticity"],
        "evidence": "gated elasticity series per department per market",
    },
    "phase_6_api_workflow": {
        "goal": "Go API, workflow/HITL, approvals, audit",
        "capabilities": ["data_management"],
        "evidence": "planner round-trip into audit_log",
    },
    "phase_7_ui": {
        "goal": "every core screen on live API data",
        "capabilities": ["data_management"],
        "evidence": "screenshot/DOM/live-data parity per screen",
    },
    "phase_8_analytics": {
        "goal": "registry, drift, adoption, end-to-end acceptance",
        "capabilities": ["data_management"],
        "evidence": "full ingest-to-serve acceptance run",
    },
}

#: Capability names this scorecard must never require, derived from the committed
#: policy rather than from evidence.
#:
#: The obvious source -- the Gate-B mask's own `supersededBy` -- lives under
#: `ingestion/data/`, which is gitignored, so a test reading it verifies only on a
#: host that still holds the bytes. That is the same "passes where the data is" shape
#: the selection ledger was fixed for, and it must not come back in the guard written
#: to stop a class of bug from recurring.
#:
#: `temporal-evidence-policy-v2.json` IS committed and carries the retirement, but
#: under a different spelling: the policy retires `inventory_replenishment` while the
#: mask emits `replenishment`. The alias is declared here, once, so the tool and its
#: test share one definition instead of the test inventing a second.
_POLICY_PATH = (
    REPO_ROOT / "contracts" / "onboarding" / "temporal-evidence-policy-v2.json"
)

#: Mask spelling -> policy spelling, for names that differ between the two.
RETIRED_CAPABILITY_ALIASES: dict[str, str] = {
    "replenishment": "inventory_replenishment",
}


def retired_capabilities(root: Path = REPO_ROOT) -> set[str]:
    """Names no phase may require, under either spelling.

    Fails CLOSED. `_load(...) or {}` turned "I could not read the authority" into "the
    authority retires nothing", which silently disabled the guard and let Phase 4
    measure the retired flag again -- reported as unblocked. That is the same
    unreadable-versus-empty collapse this file fixes for masks, one level up on the
    policy document, and the argument for moving the guard out of a test applies to
    its own input: a runtime that can go quiet is not guarded.

    Resolved beneath `root`, not the module's own REPO_ROOT, so `build(other_root)`
    reads that repository's policy rather than this checkout's.
    """

    path = root / "contracts" / "onboarding" / "temporal-evidence-policy-v2.json"
    if not path.is_file():
        raise SystemExit(f"the retirement authority is absent: {path}")
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
    except OSError as broken:
        raise SystemExit(f"the retirement authority could not be read: {path}: {broken}")
    except UnicodeDecodeError as broken:
        raise SystemExit(
            f"the retirement authority is not valid UTF-8: {path}: {broken}"
        )
    except json.JSONDecodeError as broken:
        raise SystemExit(f"the retirement authority is not valid JSON: {path}: {broken}")
    if not isinstance(policy, dict):
        raise SystemExit(
            f"the retirement authority is {type(policy).__name__}, expected an object: "
            f"{path}"
        )
    capabilities = policy.get("capabilities")
    if not isinstance(capabilities, dict):
        raise SystemExit(f"{path}: 'capabilities' is missing or not an object")
    # Absent key versus empty value, kept apart as everywhere else here: no
    # `retiredDefinitions` is a malformed policy, while `{}` is a policy that
    # legitimately retires nothing.
    if "retiredDefinitions" not in capabilities:
        raise SystemExit(f"{path}: 'capabilities.retiredDefinitions' is missing")
    declared = capabilities["retiredDefinitions"]
    if not isinstance(declared, dict):
        raise SystemExit(
            f"{path}: 'capabilities.retiredDefinitions' is "
            f"{type(declared).__name__}, expected an object"
        )
    retired = set(declared)
    aliases = {
        mask_name
        for mask_name, policy_name in RETIRED_CAPABILITY_ALIASES.items()
        if policy_name in retired
    }
    return retired | aliases


#: Capabilities that unlock more than one phase, so blocking them is expensive.
LEVERAGE_NOTE = (
    "A capability blocking more than one phase is higher leverage than any "
    "single-phase improvement."
)


def _load(path: Path) -> dict[str, Any] | None:
    """Read a JSON object for the scorecard, returning None for unusable evidence."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def gate_b_evidence(root: Path) -> tuple[dict[str, Any] | None, Path | None]:
    """Return Gate B for the governed publication, never a hash-order winner."""

    candidates = sorted((root / "ingestion/data/evidence").glob("*/gate-b.json"))
    passing: list[tuple[dict[str, Any], Path]] = []
    for path in candidates:
        payload = _load(path)
        if payload and payload.get("status") == "pass":
            passing.append((payload, path))

    # Production has a committed pin, so bind the evidence to its publication and
    # Gate-B fingerprints. Test/scratch repositories without a pin may use their only
    # passing candidate, but several candidates are ambiguity, never "last hash wins".
    pin_path = root / "contracts" / "ml" / "expected-pin.json"
    if pin_path.is_file():
        pin = _load(pin_path)
        if pin is None:
            raise SystemExit(f"the governed expected pin is unreadable: {pin_path}")
        publication = pin.get("publication")
        gate_b = pin.get("gateB")
        if not isinstance(publication, dict) or not isinstance(gate_b, dict):
            raise SystemExit(f"the governed expected pin is malformed: {pin_path}")
        publication_fingerprint = publication.get("semanticFingerprint")
        gate_b_fingerprint = gate_b.get("semanticFingerprint")
        if not isinstance(publication_fingerprint, str) or not isinstance(
            gate_b_fingerprint, str
        ):
            raise SystemExit(
                f"the governed expected pin has no publication/Gate-B fingerprint: "
                f"{pin_path}"
            )
        governed: list[tuple[dict[str, Any], Path]] = []
        for payload, path in passing:
            manifest = _load(path.with_name("publication-manifest.json"))
            if (
                manifest is not None
                and manifest.get("semanticFingerprint") == publication_fingerprint
                and payload.get("semanticFingerprint") == gate_b_fingerprint
            ):
                governed.append((payload, path))
        if len(governed) > 1:
            raise SystemExit(
                "more than one retained Gate-B document matches the governed pin: "
                + ", ".join(str(path) for _, path in governed)
            )
        return governed[0] if governed else (None, None)

    if len(passing) > 1:
        raise SystemExit(
            "more than one passing Gate-B document exists and no expected pin names "
            "the governed publication: " + ", ".join(str(path) for _, path in passing)
        )
    return passing[0] if passing else (None, None)


def forecast_state(root: Path) -> dict[str, Any]:
    """Determine whether an accepted forecast exists under the current authority."""

    from_policy = "cohorted-seasonal-cold-start-recomputation/v4"
    accepted: list[str] = []
    rejected: list[str] = []
    for manifest_path in (root / "ml/data/artifacts").glob(
        "*/forecast-run-manifest.json"
    ):
        manifest = _load(manifest_path)
        if not manifest:
            continue
        model_policy = manifest.get("modelPolicy")
        governed = isinstance(model_policy, dict) and (
            model_policy.get("acceptanceEvaluation") == from_policy
        )
        if not governed:
            continue
        run_id = manifest.get("forecastRunId")
        if not isinstance(run_id, str) or not run_id.strip():
            # A lifecycle word without the identity it applies to is malformed
            # evidence, not an accepted forecast. Converting None to the string
            # "None" made that shape truthy and opened every serving-dependent phase.
            continue
        target = accepted if manifest.get("lifecycleStatus") == "accepted" else rejected
        target.append(run_id)
    return {
        "requiredAcceptanceEvaluation": from_policy,
        "governedAcceptedRuns": sorted(accepted),
        "governedRejectedRuns": sorted(rejected),
        "servingAuthorized": bool(accepted),
        "state": "accepted" if accepted else "fail_closed_no_go",
    }


def phase_3_closure(root: Path) -> dict[str, Any]:
    """Phase 3 closes on an accepted forecast OR an explicit governed NO-GO.

    Acceptance is not the only exit. The NO-GO branch is a legitimate closure,
    but only when its evidence is complete, so this reports the outstanding items
    rather than treating a rejected run as closure by itself.
    """

    record = _load(root / "contracts/evidence/forecast-closure-record.json") or {}
    verdict_block = record.get("verdict")
    gate_block = record.get("statefulLocalGate")
    open_evidence = record.get("openEvidence")
    verdict = verdict_block.get("status") if isinstance(verdict_block, dict) else None
    outstanding = list(open_evidence) if isinstance(open_evidence, list) else []
    gate = gate_block.get("result") if isinstance(gate_block, dict) else None
    return {
        "recordPresent": bool(record),
        "verdict": verdict,
        "statefulLocalGate": gate,
        "outstandingEvidence": outstanding,
        "closed": bool(
            verdict in {"accepted", "explicit_no_go"}
            and gate == "pass"
            and not outstanding
        ),
        "branch": verdict,
    }


def build(root: Path = REPO_ROOT) -> dict[str, Any]:
    gate_b, gate_b_path = gate_b_evidence(root)
    raw_mask = gate_b.get("capabilityMask") if gate_b is not None else None
    # A mask that is null, a list or a string reached `.get()` below and crashed. The
    # entry-level guard added last round did not cover the container holding them --
    # the same one-level-up miss.
    #
    # Normalising to `{}` alone would report NOT_EVALUATED, which says the gate ran
    # and skipped the capability. It did not: the mask could not be read at all, and
    # those are different facts about the evidence. The flag keeps them apart.
    # Refuse to MEASURE a retired capability, not merely to have one configured.
    # Phase 4 required `replenishment` -- retired and superseded -- so it reported no
    # missing capability while current-snapshot was false. A scorecard that quietly
    # measures the wrong flag is worse than one that stops.
    retired = retired_capabilities(root)
    offenders = sorted(
        f"{phase}:{capability}"
        for phase, spec in PHASE_REQUIREMENTS.items()
        for capability in spec["capabilities"]
        if capability in retired
    )
    if offenders:
        raise SystemExit(
            "these phases require capabilities the committed policy retires: "
            f"{', '.join(offenders)}"
        )

    mask_unreadable = gate_b is None or not isinstance(raw_mask, dict)
    mask = raw_mask if isinstance(raw_mask, dict) else {}
    forecast = forecast_state(root)

    blockers: dict[str, dict[str, Any]] = {}
    phases: dict[str, Any] = {}

    def record_blocker(reason: str, capability: str, phase: str) -> None:
        blockers.setdefault(
            reason,
            {"reasonCode": reason, "capabilities": [], "phasesBlocked": []},
        )
        if capability not in blockers[reason]["capabilities"]:
            blockers[reason]["capabilities"].append(capability)
        if phase not in blockers[reason]["phasesBlocked"]:
            blockers[reason]["phasesBlocked"].append(phase)

    for name, spec in PHASE_REQUIREMENTS.items():
        missing: list[dict[str, str]] = []
        for capability in spec["capabilities"]:
            # Key membership, not `.get()`: an ABSENT key means the gate did not
            # evaluate this capability, while a key present with an explicit null is
            # malformed evidence. `.get()` returns None for both and collapsed the
            # same distinction this file draws everywhere else.
            evaluated = capability in mask
            entry = mask.get(capability)
            # The fourth reader of this field, and it had the same truthiness defect
            # as the three in the repin path: `{"available": "false"}` is a non-empty
            # string, so it read as AVAILABLE. The consequence here is different in
            # kind -- this tool prints a scorecard and writes no committed artifact,
            # so the failure is a phase shown as unblocked, not an authorization --
            # which is why it does not import the raising helper the other three
            # share: turning a report into a crash would be the wrong trade.
            #
            # Strict without raising: anything that is not a real boolean `True` is
            # not available, and says which of the two reasons applies. A non-dict
            # entry also used to reach `.get()` and raise AttributeError.
            if entry is None and not evaluated and not mask_unreadable:
                reason = "NOT_EVALUATED"
                missing.append({"capability": capability, "reasonCode": reason})
                record_blocker(reason, capability, name)
            elif mask_unreadable or not isinstance(entry, dict) or not isinstance(
                entry.get("available"), bool
            ):
                # MASK_UNREADABLE names a container-level fact; an unusable single
                # entry in an otherwise readable mask is a different one, and this
                # file's own standard is different facts, different codes.
                code = (
                    "MASK_UNREADABLE" if mask_unreadable else "ENTRY_UNREADABLE"
                )
                missing.append({"capability": capability, "reasonCode": code})
                record_blocker(code, capability, name)
            elif not entry["available"]:
                raw_reason = entry.get("reasonCode")
                reason = (
                    raw_reason.strip()
                    if isinstance(raw_reason, str) and raw_reason.strip()
                    else "UNAVAILABLE"
                )
                missing.append({"capability": capability, "reasonCode": reason})
                record_blocker(reason, capability, name)
        forecast_blocked = bool(
            spec.get("alsoRequiresForecastServing") and not forecast["servingAuthorized"]
        )
        if forecast_blocked:
            reason = "FORECAST_NOT_ACCEPTED"
            blockers.setdefault(
                reason,
                {"reasonCode": reason, "capabilities": [], "phasesBlocked": []},
            )
            if name not in blockers[reason]["phasesBlocked"]:
                blockers[reason]["phasesBlocked"].append(name)
        phases[name] = {
            "goal": spec["goal"],
            "deliverables": spec.get("deliverables") or [],
            "delivered": spec.get("delivered") or [],
            "outstandingDeliverables": sorted(
                set(spec.get("deliverables") or []) - set(spec.get("delivered") or [])
            ),
            "humanGates": spec.get("humanGates") or [],
            "requiredCapabilities": spec["capabilities"],
            "missingCapabilities": missing,
            "forecastServingRequired": bool(spec.get("alsoRequiresForecastServing")),
            "forecastServingBlocked": forecast_blocked,
            "status": "blocked" if (missing or forecast_blocked) else "unblocked",
            "evidence": spec["evidence"],
        }

    # Sequencing: a phase cannot start until every predecessor has CLOSED.
    closure = phase_3_closure(root)
    closed: dict[str, bool] = {}
    for name in PHASE_ORDER:
        spec = PHASE_REQUIREMENTS[name]
        if name == "phase_3_forecast":
            closed[name] = closure["closed"]
        elif spec.get("deliverables"):
            outstanding = set(spec["deliverables"]) - set(spec.get("delivered") or [])
            # A workstream closes only when every deliverable exists AND its
            # human review gates are recorded; the latter are never inferred.
            closed[name] = not outstanding and not spec.get("humanGates")
        else:
            closed[name] = bool(spec.get("closed"))
    for index, name in enumerate(PHASE_ORDER):
        predecessors = PHASE_ORDER[:index]
        open_predecessors = [item for item in predecessors if not closed[item]]
        phases[name]["predecessorsOpen"] = open_predecessors
        phases[name]["closed"] = closed[name]
        if open_predecessors:
            phases[name]["startable"] = False
            phases[name]["status"] = "not_startable_predecessor_open"
        else:
            phases[name]["startable"] = True
            if phases[name]["status"] != "blocked":
                phases[name]["status"] = "closed" if closed[name] else "startable"
    if not closure["closed"]:
        reason = "PHASE_3_NOT_CLOSED"
        blocked_by_sequence = [
            name
            for name in PHASE_ORDER
            if phases[name].get("predecessorsOpen")
        ]
        blockers[reason] = {
            "reasonCode": reason,
            "capabilities": [],
            "phasesBlocked": blocked_by_sequence,
        }

    ranked = sorted(
        blockers.values(),
        key=lambda item: (-len(item["phasesBlocked"]), item["reasonCode"]),
    )
    unblocked = [name for name, data in phases.items() if data.get("startable")]
    return {
        "schemaVersion": "retail-direction-scorecard/v1",
        "gateBEvidence": str(gate_b_path.relative_to(root)) if gate_b_path else None,
        "capabilityMask": mask,
        "forecast": forecast,
        "phaseOrder": PHASE_ORDER,
        "phase3Closure": closure,
        "phases": phases,
        "blockersByLeverage": ranked,
        "leverageNote": LEVERAGE_NOTE,
        "summary": {
            "phasesStartable": sorted(unblocked),
            "phasesNotStartable": sorted(
                name for name, data in phases.items() if not data.get("startable")
            ),
            "phasesClosed": sorted(
                name for name, data in phases.items() if data.get("closed")
            ),
            "unblockedCount": len(unblocked),
            "totalPhases": len(phases),
            "highestLeverageBlocker": ranked[0]["reasonCode"] if ranked else None,
            "phasesBehindHighestLeverageBlocker": (
                len(ranked[0]["phasesBlocked"]) if ranked else 0
            ),
        },
    }


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    summary = report["summary"]
    closure = report["phase3Closure"]
    lines.append(
        f"program goal: {summary['unblockedCount']}/{summary['totalPhases']} "
        f"phases startable, {len(summary['phasesClosed'])} closed"
    )
    lines.append(f"forecast serving: {report['forecast']['state']}")
    lines.append(
        f"phase 3 closure: branch={closure['branch']} gate={closure['statefulLocalGate']} "
        f"closed={closure['closed']}"
    )
    lines.append("")
    lines.append("phases (sequential; a phase needs every predecessor CLOSED):")
    for name in report["phaseOrder"]:
        data = report["phases"][name]
        if data.get("closed"):
            mark = "DONE "
        elif data.get("startable"):
            mark = "OPEN "
        else:
            mark = "WAIT "
        notes = ", ".join(
            item["reasonCode"] for item in data["missingCapabilities"]
        )
        if data["forecastServingBlocked"]:
            notes = ", ".join(filter(None, [notes, "FORECAST_NOT_ACCEPTED"]))
        if data.get("deliverables"):
            done = len(data["delivered"])
            total = len(data["deliverables"])
            gates = len(data.get("humanGates") or [])
            notes = f"{done}/{total} deliverables"
            if data["outstandingDeliverables"]:
                notes += f" (open: {', '.join(data['outstandingDeliverables'])})"
            if gates:
                notes += f", {gates} review gate(s)"
        if data.get("predecessorsOpen"):
            notes = f"waiting on {', '.join(data['predecessorsOpen'])}"
        lines.append(f"  {mark} {name:22s} {notes}")
    if closure["outstandingEvidence"]:
        lines.append("")
        lines.append("phase 3 closure - outstanding evidence:")
        for item in closure["outstandingEvidence"]:
            lines.append(f"  - {item}")
    lines.append("")
    lines.append("blockers by leverage (phases blocked, descending):")
    for blocker in report["blockersByLeverage"]:
        phases = ", ".join(blocker["phasesBlocked"])
        capabilities = ", ".join(blocker["capabilities"]) or "-"
        lines.append(
            f"  {len(blocker['phasesBlocked'])}x {blocker['reasonCode']:40s} "
            f"caps=[{capabilities}] phases=[{phases}]"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the raw report")
    parser.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    report = build(args.repository_root)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
