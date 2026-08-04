"""PP3-A6 capability readiness, temporal evidence and zero-demand eligibility.

Answers three questions that ingestion success alone cannot:

1. what temporal evidence does each role actually carry, and does it permit
   origin-safe historical replay;
2. may a missing sale become a zero-demand label for a given cell;
3. for each downstream capability, is the data *ready*, and separately, is it
   *statistically sufficient*.

Readiness and sufficiency are deliberately different fields. A retailer can be
perfectly ready and still statistically insufficient, and reporting one as the
other is the "pipeline passed means ML ready" failure the plan exists to prevent.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

POLICY_PATH: Final[str] = "contracts/onboarding/temporal-evidence-policy.json"
POLICY_PATH_V2: Final[str] = (
    "contracts/onboarding/temporal-evidence-policy-v2.json"
)
READINESS_SCHEMA_VERSION: Final[str] = "retail-readiness-report/v1"

READY: Final[str] = "ready"
VALIDATED_PARTIAL: Final[str] = "validated_partial"
UNAVAILABLE: Final[str] = "unavailable"
BLOCKED: Final[str] = "blocked"

SUFFICIENT: Final[str] = "sufficient"
INSUFFICIENT: Final[str] = "insufficient_evidence"
NOT_EVALUATED: Final[str] = "not_evaluated"


class ReadinessError(RuntimeError):
    """The readiness inputs are inconsistent with the frozen policy."""


def load_policy(repository_root: str | Path = ".") -> dict[str, Any]:
    """Load the newest temporal-evidence policy present.

    v2 splits `inventory_replenishment` into an explicitly current-scoped
    capability and an origin-safe replay capability, because one flag could not
    say that DC current-position analytics are serviceable on this pin while
    historical replay is not. v1 stays loadable and remains the policy every
    readiness verdict published before v2 was evaluated under; a repository
    without v2 keeps behaving exactly as before.
    """

    root = Path(repository_root)
    for path, expected in (
        (root / POLICY_PATH_V2, "retail-temporal-evidence-policy/v2"),
        (root / POLICY_PATH, "retail-temporal-evidence-policy/v1"),
    ):
        if not path.is_file():
            continue
        policy = json.loads(path.read_text(encoding="utf-8"))
        if policy.get("schemaVersion") != expected:
            raise ReadinessError(
                f"{path.name} declares {policy.get('schemaVersion')!r}, "
                f"expected {expected!r}"
            )
        return policy
    raise ReadinessError("no temporal-evidence policy is present")


@dataclass(frozen=True)
class RoleEvidence:
    """What one role's temporal fields actually carry."""

    role: str
    grade: str
    rows: int
    #: Source fields the adapter tried to use as availability evidence.
    availability_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ZeroDemandCell:
    """One SKU x store x channel x interval candidate for a zero label."""

    sku_id: str
    store_id: str
    channel_id: str
    interval_start: str
    extract_complete: bool
    assortment_active: bool | None
    known_by_cutoff: bool
    boundary_exposure_handled: bool = True
    unresolved_gap: bool = False


@dataclass
class ReadinessInputs:
    """Everything the evaluator needs, with no implicit defaults."""

    role_evidence: Mapping[str, RoleEvidence]
    present_roles: frozenset[str] = dataclass_field(default_factory=frozenset)
    evidence_flags: frozenset[str] = dataclass_field(default_factory=frozenset)
    #: Capability -> measured sufficiency verdict, or absent for not_evaluated.
    sufficiency: Mapping[str, str] = dataclass_field(default_factory=dict)


def evaluate_temporal_evidence(
    inputs: ReadinessInputs,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Report each role's grade and reject business dates as availability."""

    grades = policy["grades"]
    forbidden = set(policy["neverProvesAvailability"])
    per_role: dict[str, Any] = {}
    violations: list[dict[str, str]] = []
    for name, evidence in sorted(inputs.role_evidence.items()):
        if evidence.grade not in grades:
            raise ReadinessError(f"{name}: unknown evidence grade {evidence.grade!r}")
        offending = sorted(set(evidence.availability_fields) & forbidden)
        for column in offending:
            violations.append(
                {
                    "role": name,
                    "field": column,
                    "reasonCode": "BUSINESS_DATE_AS_AVAILABILITY",
                }
            )
        per_role[name] = {
            "grade": evidence.grade,
            "rows": evidence.rows,
            "supportsHistoricalReplay": bool(
                grades[evidence.grade]["supportsHistoricalReplay"]
            ),
            "downgrades": list(grades[evidence.grade].get("downgrades", [])),
        }
    return {
        "roles": per_role,
        "violations": violations,
        "coverageByGrade": {
            grade: sum(
                1 for e in inputs.role_evidence.values() if e.grade == grade
            )
            for grade in sorted(grades)
        },
    }


def evaluate_zero_demand(
    cells: Sequence[ZeroDemandCell],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Decide, per cell, whether a missing sale may be labelled zero."""

    zero_policy = policy["zeroDemand"]
    allowed_reasons = set(zero_policy["unknownReasonCodes"])
    eligible = 0
    unknown: dict[str, int] = {}
    for cell in cells:
        reasons: list[str] = []
        if not cell.extract_complete:
            reasons.append("EXTRACT_INCOMPLETE")
        if cell.assortment_active is None:
            reasons.append("ASSORTMENT_UNKNOWN")
        elif not cell.assortment_active:
            reasons.append("ASSORTMENT_INACTIVE")
        if not cell.known_by_cutoff:
            reasons.append("NOT_KNOWN_BY_CUTOFF")
        if not cell.boundary_exposure_handled:
            reasons.append("BOUNDARY_EXPOSURE_PARTIAL")
        if cell.unresolved_gap:
            reasons.append("CHANNEL_COVERAGE_INCOMPLETE")
        if reasons:
            for reason in reasons:
                if reason not in allowed_reasons:
                    raise ReadinessError(f"unknown zero-demand reason {reason!r}")
                unknown[reason] = unknown.get(reason, 0) + 1
        else:
            eligible += 1
    return {
        "cells": len(cells),
        "zeroEligible": eligible,
        "unknown": len(cells) - eligible,
        "unknownReasonCodes": dict(sorted(unknown.items())),
        "conditions": [item["id"] for item in zero_policy["conditions"]],
    }


def _grade_rank(policy: Mapping[str, Any], grade: str) -> int:
    return int(policy["grades"][grade]["rank"])


def evaluate_capabilities(
    inputs: ReadinessInputs,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish a readiness verdict and a separate sufficiency verdict."""

    definitions = policy["capabilities"]["definitions"]
    results: dict[str, Any] = {}
    for capability, definition in sorted(definitions.items()):
        required_roles = set(definition["requiredRoles"])
        missing_roles = sorted(required_roles - set(inputs.present_roles))
        required_evidence = set(definition["requiredEvidence"])
        missing_evidence = sorted(required_evidence - set(inputs.evidence_flags))

        reasons: list[str] = []
        for role in missing_roles:
            reasons.append(f"MISSING_ROLE:{role}")
        for flag in missing_evidence:
            reasons.append(f"MISSING_EVIDENCE:{flag}")

        # The weakest grade among required roles caps the capability.
        graded = [
            inputs.role_evidence[role].grade
            for role in sorted(required_roles & set(inputs.role_evidence))
        ]
        weakest = (
            max(graded, key=lambda grade: _grade_rank(policy, grade))
            if graded
            else None
        )
        minimum = definition["minimumGrade"]
        grade_ok = weakest is not None and _grade_rank(
            policy, weakest
        ) <= _grade_rank(policy, minimum)
        if weakest is not None and not grade_ok:
            reasons.append(f"EVIDENCE_GRADE_TOO_WEAK:{weakest}")

        if missing_roles:
            readiness = UNAVAILABLE
        elif not grade_ok:
            readiness = UNAVAILABLE
        elif missing_evidence:
            readiness = VALIDATED_PARTIAL
        else:
            readiness = READY

        results[capability] = {
            "readiness": readiness,
            "sufficiency": inputs.sufficiency.get(capability, NOT_EVALUATED),
            "requiredRoles": sorted(required_roles),
            "missingRoles": missing_roles,
            "requiredEvidence": sorted(required_evidence),
            "missingEvidence": missing_evidence,
            "minimumGrade": minimum,
            "weakestGrade": weakest,
            "reasonCodes": reasons,
            "consumerMayProceed": readiness == READY
            and inputs.sufficiency.get(capability, NOT_EVALUATED) == SUFFICIENT,
        }
    return results


def build_readiness_report(
    inputs: ReadinessInputs,
    cells: Sequence[ZeroDemandCell],
    *,
    repository_root: str | Path = ".",
    tenant_id: str,
    source_snapshot_id: str,
) -> dict[str, Any]:
    """Assemble the full capability-specific readiness report."""

    policy = load_policy(repository_root)
    temporal = evaluate_temporal_evidence(inputs, policy)
    capabilities = evaluate_capabilities(inputs, policy)
    if temporal["violations"]:
        # A business date used as availability is a hard stop, not a downgrade:
        # every replay-dependent capability would silently look origin-safe.
        for name, result in capabilities.items():
            if policy["capabilities"]["definitions"][name]["minimumGrade"] != (
                "landing_backfill"
            ):
                result["readiness"] = BLOCKED
                result["reasonCodes"] = [
                    *result["reasonCodes"],
                    "BUSINESS_DATE_AS_AVAILABILITY",
                ]
                result["consumerMayProceed"] = False
    return {
        "schemaVersion": READINESS_SCHEMA_VERSION,
        "policyId": policy["policyId"],
        "tenantId": tenant_id,
        "sourceSnapshotId": source_snapshot_id,
        "temporalEvidence": temporal,
        "zeroDemand": evaluate_zero_demand(cells, policy),
        "capabilities": capabilities,
        "summary": {
            "ready": sorted(
                name
                for name, r in capabilities.items()
                if r["readiness"] == READY
            ),
            "validatedPartial": sorted(
                name
                for name, r in capabilities.items()
                if r["readiness"] == VALIDATED_PARTIAL
            ),
            "unavailable": sorted(
                name
                for name, r in capabilities.items()
                if r["readiness"] == UNAVAILABLE
            ),
            "blocked": sorted(
                name
                for name, r in capabilities.items()
                if r["readiness"] == BLOCKED
            ),
        },
    }


__all__ = [
    "BLOCKED",
    "INSUFFICIENT",
    "NOT_EVALUATED",
    "READINESS_SCHEMA_VERSION",
    "READY",
    "SUFFICIENT",
    "UNAVAILABLE",
    "VALIDATED_PARTIAL",
    "ReadinessError",
    "ReadinessInputs",
    "RoleEvidence",
    "ZeroDemandCell",
    "build_readiness_report",
    "evaluate_capabilities",
    "evaluate_temporal_evidence",
    "evaluate_zero_demand",
    "load_policy",
]
