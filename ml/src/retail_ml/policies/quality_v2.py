"""Decision #76 quality policy v2, offered as a candidate beside active v1.

v1 reduces seven checks to one worst-of ``data_quality_class``. Three of those
checks -- ``reconciliation_passed``, ``source_quality_critical_count`` and
``source_quality_warning_count`` -- are publication-level scalars broadcast to
every row by the current-cycle assembler, so one warning anywhere in a
publication classifies every SeriesKey in it as ``Watch``. The row-local signal
is then unreadable: a genuinely stale or sparse SeriesKey looks exactly like a
healthy one.

v1's own contract already forbids this. ``inputSemantics.sourceFindings`` reads
"Only findings bound to the same SeriesKey and accepted input publication are
counted", which the broadcast violates. v2 does not relax the check; it puts each
signal at the grain it is actually measured at:

* ``global_limitations`` -- publication-scoped findings, listed once, never
  collapsed into a row class;
* ``row_quality_class`` -- reduced from row-local checks only;
* ``publication_quality_class`` -- reduced from the global findings alone.

The two classes are published side by side rather than merged, so a consumer can
always say which grain caused a degraded state. Suppressing the global warning
would be the opposite failure and is equally refused: ``global_limitations`` is
required, and an empty list is only valid when there are genuinely no findings.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final, Mapping, Sequence

POLICY_ID: Final[str] = "retail-forecast-data-quality/v2"
SCHEMA_VERSION: Final[str] = "retail-forecast-quality-policy/v2"

#: Promoted to active 2026-07-31 after review, with the accepted run
#: fr_463f53be6353e481 satisfying decision #76's "newly accepted run" condition.
#: v1 stays immutable and readable for prior bundles.
STATUS: Final[str] = "active"

GOOD: Final[str] = "Good"
WATCH: Final[str] = "Watch"
ISSUE: Final[str] = "Issue"
PRECEDENCE: Final[tuple[str, ...]] = (ISSUE, WATCH, GOOD)

#: Row-local dimensions, classified separately so one cannot mask another.
DIMENSION_KEY: Final[str] = "key"
DIMENSION_RECONCILIATION: Final[str] = "reconciliation"
DIMENSION_MISSINGNESS: Final[str] = "missingness"
DIMENSION_FRESHNESS: Final[str] = "freshness"
DIMENSION_COVERAGE: Final[str] = "coverage"

ROW_DIMENSIONS: Final[tuple[str, ...]] = (
    DIMENSION_KEY,
    DIMENSION_RECONCILIATION,
    DIMENSION_MISSINGNESS,
    DIMENSION_FRESHNESS,
    DIMENSION_COVERAGE,
)

#: Thresholds are carried over from v1 unchanged. v2 changes the grain a signal
#: is applied at, not how strict any single check is -- otherwise a v1/v2
#: comparison would be measuring two changes at once.
MISSINGNESS_ISSUE: Final[Decimal] = Decimal("0.20")
MISSINGNESS_WATCH: Final[Decimal] = Decimal("0.05")
FRESHNESS_ISSUE_DAYS: Final[int] = 21
FRESHNESS_WATCH_DAYS: Final[int] = 14
COVERAGE_ISSUE: Final[Decimal] = Decimal("0.75")
COVERAGE_WATCH: Final[Decimal] = Decimal("0.90")

#: Which v1 checks are publication-scoped rather than row-local. Naming them is
#: what lets a test prove no global finding reaches a row class.
PUBLICATION_SCOPED_CHECKS: Final[tuple[str, ...]] = (
    "source_quality_critical_count",
    "source_quality_warning_count",
    "reconciliation_passed",
)


class QualityPolicyV2Error(ValueError):
    """A quality input was outside its declared domain."""


def _reduce(outcomes: Sequence[str]) -> str:
    for candidate in PRECEDENCE:
        if candidate in outcomes:
            return candidate
    return GOOD


def classify_row(
    *,
    canonical_key_complete: bool,
    row_reconciliation_passed: bool | None,
    core_feature_missing_share: Decimal,
    latest_actual_age_days: int,
    observation_coverage_13w: Decimal,
) -> dict[str, Any]:
    """Classify one SeriesKey from row-local evidence only.

    ``row_reconciliation_passed`` is ``None`` when the publication carries no
    row-scoped reconciliation result. That is recorded as ``not_evaluated`` rather
    than silently passing or silently failing, because a check that never ran is a
    third state and collapsing it into either of the other two is how an unproven
    row comes to look proven.
    """

    if core_feature_missing_share < 0:
        raise QualityPolicyV2Error("core_feature_missing_share is negative")
    if not Decimal(0) <= observation_coverage_13w <= Decimal(1):
        raise QualityPolicyV2Error("observation_coverage_13w is outside [0, 1]")
    if latest_actual_age_days < 0:
        raise QualityPolicyV2Error("latest_actual_age_days is negative")

    dimensions: dict[str, dict[str, Any]] = {
        DIMENSION_KEY: {
            "observed": bool(canonical_key_complete),
            "outcome": GOOD if canonical_key_complete else ISSUE,
        },
        DIMENSION_RECONCILIATION: (
            {"observed": None, "outcome": GOOD, "state": "not_evaluated"}
            if row_reconciliation_passed is None
            else {
                "observed": bool(row_reconciliation_passed),
                "outcome": GOOD if row_reconciliation_passed else ISSUE,
                "state": "evaluated",
            }
        ),
        DIMENSION_MISSINGNESS: {
            "observed": str(core_feature_missing_share),
            "outcome": (
                ISSUE
                if core_feature_missing_share > MISSINGNESS_ISSUE
                else WATCH
                if core_feature_missing_share > MISSINGNESS_WATCH
                else GOOD
            ),
        },
        DIMENSION_FRESHNESS: {
            "observed": int(latest_actual_age_days),
            "outcome": (
                ISSUE
                if latest_actual_age_days > FRESHNESS_ISSUE_DAYS
                else WATCH
                if latest_actual_age_days > FRESHNESS_WATCH_DAYS
                else GOOD
            ),
        },
        DIMENSION_COVERAGE: {
            "observed": str(observation_coverage_13w),
            "outcome": (
                ISSUE
                if observation_coverage_13w < COVERAGE_ISSUE
                else WATCH
                if observation_coverage_13w < COVERAGE_WATCH
                else GOOD
            ),
        },
    }
    return {
        "policyId": POLICY_ID,
        "row_quality_class": _reduce(
            [entry["outcome"] for entry in dimensions.values()]
        ),
        "dimensions": dimensions,
        "degradedDimensions": sorted(
            name for name, entry in dimensions.items() if entry["outcome"] != GOOD
        ),
    }


def classify_publication(
    *,
    critical_count: int,
    warning_count: int,
    reconciliation_passed: bool,
    findings: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Classify the publication, and keep its findings visible as a list.

    The returned ``global_limitations`` is the field that must survive into the
    serving contract. Dropping it to avoid degrading rows is the failure mode
    decision #76 names second, and it is the more dangerous of the two because it
    is invisible downstream.
    """

    if critical_count < 0 or warning_count < 0:
        raise QualityPolicyV2Error("source finding counts cannot be negative")

    limitations: list[dict[str, Any]] = []
    if critical_count > 0:
        limitations.append(
            {
                "code": "SOURCE_QUALITY_CRITICAL",
                "severity": ISSUE,
                "count": int(critical_count),
                "scope": "publication",
            }
        )
    if warning_count > 0:
        limitations.append(
            {
                "code": "SOURCE_QUALITY_WARNING",
                "severity": WATCH,
                "count": int(warning_count),
                "scope": "publication",
            }
        )
    if not reconciliation_passed:
        limitations.append(
            {
                "code": "PUBLICATION_RECONCILIATION_FAILED",
                "severity": ISSUE,
                "count": 1,
                "scope": "publication",
            }
        )
    limitations.extend(
        {
            "code": str(finding.get("code", "SOURCE_FINDING")),
            "severity": str(finding.get("severity", WATCH)),
            "count": int(finding.get("count", 1)),
            "scope": "publication",
        }
        for finding in findings
    )
    return {
        "policyId": POLICY_ID,
        "publication_quality_class": _reduce(
            [entry["severity"] for entry in limitations]
        ),
        "global_limitations": limitations,
        "limitationCount": len(limitations),
    }


def present(
    row: Mapping[str, Any],
    publication: Mapping[str, Any],
) -> dict[str, Any]:
    """Combine the two grains for display without merging them.

    ``effective_display_class`` is the worst of the two so a consumer that shows a
    single badge is not misled, but both inputs travel with it and
    ``degradedBy`` names which grain set it. That is the whole point of v2: the
    combined state is still available, it just can no longer be mistaken for a
    row-local measurement.
    """

    row_class = str(row["row_quality_class"])
    publication_class = str(publication["publication_quality_class"])
    effective = _reduce([row_class, publication_class])
    degraded_by = []
    if row_class != GOOD:
        degraded_by.append("row")
    if publication_class != GOOD:
        degraded_by.append("publication")
    return {
        "policyId": POLICY_ID,
        "row_quality_class": row_class,
        "publication_quality_class": publication_class,
        "effective_display_class": effective,
        "degradedBy": degraded_by,
        "global_limitations": list(publication["global_limitations"]),
        "degradedDimensions": list(row.get("degradedDimensions", [])),
    }


__all__ = [
    "COVERAGE_ISSUE",
    "COVERAGE_WATCH",
    "FRESHNESS_ISSUE_DAYS",
    "FRESHNESS_WATCH_DAYS",
    "GOOD",
    "ISSUE",
    "MISSINGNESS_ISSUE",
    "MISSINGNESS_WATCH",
    "POLICY_ID",
    "PRECEDENCE",
    "PUBLICATION_SCOPED_CHECKS",
    "ROW_DIMENSIONS",
    "SCHEMA_VERSION",
    "STATUS",
    "WATCH",
    "QualityPolicyV2Error",
    "classify_publication",
    "classify_row",
    "present",
]
