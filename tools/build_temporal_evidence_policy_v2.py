"""Derive temporal-evidence policy v2 from v1 by splitting the inventory capability.

`P4-2` task 15. v1 has one `inventory_replenishment` capability at
`native_extracted`, so the current pin -- whose supplier terms are
`landing_backfill` -- returns `unavailable` for the whole thing. That verdict is
correct and too coarse: DC current-position analytics ARE serviceable on this pin,
while origin-safe historical replay is not, and one flag cannot say both.

The split makes the two claims independently falsifiable:

* `inventory_replenishment_current_snapshot` may accept present-time landing
  evidence, because a current position only has to be true now.
* `inventory_replenishment_replay` requires `native_extracted` or stronger on
  every temporal role plus the new status-history roles, because reconstructing a
  position at an arbitrary past origin is the thing landing evidence cannot do.

The point of the split is NOT to make replay easier to claim. `validated_partial`
or `unavailable` current analytics never authorizes replay, and both must be
`ready + sufficient` before the inventory demo exits -- replay is an exit
criterion, so a split that let current-snapshot readiness stand in for it would
defeat its own purpose.

v1 stays immutable: it is the policy every readiness verdict published before this
was evaluated under.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
V1_PATH = REPO_ROOT / "contracts" / "onboarding" / "temporal-evidence-policy.json"
V2_PATH = (
    REPO_ROOT / "contracts" / "onboarding" / "temporal-evidence-policy-v2.json"
)

CURRENT_SNAPSHOT = "inventory_replenishment_current_snapshot"
REPLAY = "inventory_replenishment_replay"

SPLIT_DEFINITIONS: dict[str, dict[str, Any]] = {
    CURRENT_SNAPSHOT: {
        "requiredRoles": [
            "inventory",
            "inbound_shipment",
            "supply_term",
            "service_lane",
            "merchandise",
        ],
        "requiredEvidence": ["reconciled_current_position"],
        # Landing evidence is admissible here and only here, and only because the
        # claim is scoped to the present. It is explicitly NOT a weaker floor for
        # the same capability: it is a different, narrower capability.
        "minimumGrade": "landing_backfill",
        "landingEvidenceAdmissible": True,
        "landingEvidenceCondition": (
            "Admissible only for a claim explicitly scoped to the current cutoff. "
            "A current-snapshot verdict may never be presented as replay "
            "readiness."
        ),
        "supportsHistoricalOrigins": False,
    },
    REPLAY: {
        "requiredRoles": [
            "inventory",
            "inbound_shipment",
            "inbound_status_event",
            "inventory_transfer_event",
            "supply_term",
            "service_lane",
            "merchandise",
            "assortment",
        ],
        "requiredEvidence": [
            "reconciled_demand",
            "lead_time_evidence",
            "lead_time_variability",
            "origin_reconstructible_inbound_state",
            "store_grain_inventory_state",
        ],
        "minimumGrade": "native_extracted",
        "landingEvidenceAdmissible": False,
        "supportsHistoricalOrigins": True,
        "eventPlacementRules": [
            "known_as_of >= fulfilled_at for every fulfillment line",
            "known_as_of >= status_effective_at for every status observation",
        ],
    },
}


def build() -> dict[str, Any]:
    v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
    document = json.loads(json.dumps(v1))

    document["schemaVersion"] = "retail-temporal-evidence-policy/v2"
    document["policyId"] = "retail-temporal-evidence/v2"
    document["decisionIds"] = sorted({*v1["decisionIds"], 72, 92})
    document["supersedes"] = {
        "policyId": v1["policyId"],
        "reason": (
            "Splits inventory_replenishment into an explicitly current-scoped "
            "capability and an origin-safe replay capability. v1 remains the "
            "policy every readiness verdict published before this was evaluated "
            "under."
        ),
    }

    definitions = document["capabilities"]["definitions"]
    legacy = definitions.pop("inventory_replenishment", None)
    if legacy is None:
        raise SystemExit("v1 does not define inventory_replenishment")
    definitions.update(SPLIT_DEFINITIONS)
    document["capabilities"]["retiredDefinitions"] = {
        "inventory_replenishment": {
            **legacy,
            "retiredReason": (
                "One flag could not distinguish serviceable current-position "
                "analytics from unavailable origin-safe replay. Replaced by "
                f"{CURRENT_SNAPSHOT} and {REPLAY}."
            ),
        }
    }
    document["capabilities"]["splitRule"] = (
        "Each capability publishes independent readiness and sufficiency. A "
        f"{CURRENT_SNAPSHOT} verdict of ready never implies {REPLAY} readiness, "
        "and validated_partial or unavailable current analytics authorizes no "
        "replay. Both must be ready + sufficient before the inventory and "
        "replenishment destinations exit, because replay is an exit criterion "
        "rather than a bonus."
    )
    # The distinction the evaluator already makes and the UI must keep making.
    # Both set consumerMayProceed = false, and collapsing them would lose the
    # difference between "the evidence is too weak" and "a temporal rule was
    # violated".
    document["capabilities"]["labelSemantics"] = {
        "unavailable": (
            "Required evidence is absent or below the grade floor. Reason code "
            "EVIDENCE_GRADE_TOO_WEAK."
        ),
        "blocked": (
            "A temporal-policy violation is present, such as a business-effective "
            "date promoted into availability. Reason code "
            "BUSINESS_DATE_AS_AVAILABILITY."
        ),
        "note": (
            "Both set consumerMayProceed = false. The distinction must stay "
            "accurate in evidence and in the UI: one is missing evidence, the "
            "other is a rule violation."
        ),
    }
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = json.dumps(build(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if not V2_PATH.is_file():
            print("temporal evidence policy v2 is absent", file=sys.stderr)
            return 1
        if V2_PATH.read_text(encoding="utf-8") != rendered:
            print("temporal evidence policy v2 drifted", file=sys.stderr)
            return 1
        print("temporal evidence policy v2 matches its derivation")
        return 0
    V2_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {V2_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
