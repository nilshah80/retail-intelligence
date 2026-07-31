"""PP3-B6 step 1-5: admissibility screening for optional exogenous signals.

The plan lists five optional signals and six obligations per signal: coverage,
frozen origin/target semantics, missing/fallback indicators, an ablation on
identical paired rows, leakage rejection, and reason-coded unavailability.

An ablation is the most expensive obligation and the least informative when the
signal cannot be admitted at all, so the screens run in cost order and the first
failure is terminal:

1. ``temporal`` -- the source's own ``known_as_of_evidence_grade`` must support
   historical replay. Decision #70/#71 froze this; a grade of ``landing_backfill``
   is serving-eligible but replay-ineligible, and every origin in an acceptance
   backtest is historical.
2. ``grain`` -- the signal must join to a SeriesKey. A relation keyed on
   distribution centres cannot describe a store.
3. ``leakage`` -- a field that reproduces the target is not a signal. This screen
   exists because the one signal that cleared materiality (assortment exit, 14.31%
   of error mass) turned out to be the last observed sale date back-stamped with an
   earlier ``known_as_of``.
4. ``materiality`` -- decision #75 requires 5% relative WAPE. A signal present on
   rows carrying less than 5% of error mass cannot reach it even if perfect, so the
   ablation is skipped and the reason is recorded rather than left implied.

Only a signal that survives all four earns an ablation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, Sequence

import pandas as pd

SIGNAL_SCREEN_VERSION: Final[str] = "optional-signal-admissibility/v1"

#: Decision #75's floor. A signal whose rows carry less error mass than this
#: cannot satisfy the gate even with a perfect fit, so the ablation is not run.
MIN_ADDRESSABLE_ERROR_SHARE_PCT: Final[float] = 5.0

#: A field this close to the target is the target.
TARGET_REPRODUCTION_SHARE: Final[float] = 0.25

SCREENS: Final[tuple[str, ...]] = ("temporal", "grain", "leakage", "materiality")

VERDICT_ADMISSIBLE: Final[str] = "admissible_pending_ablation"
VERDICT_ALREADY_SHIPPED: Final[str] = "already_in_feature_set"
VERDICT_REJECTED: Final[str] = "rejected"

REASON_NO_HISTORICAL_REPLAY: Final[str] = "GRADE_DOES_NOT_SUPPORT_HISTORICAL_REPLAY"
REASON_GRAIN_ABOVE_SERIESKEY: Final[str] = "SOURCE_GRAIN_DOES_NOT_REACH_SERIESKEY"
REASON_TARGET_DERIVED: Final[str] = "FIELD_REPRODUCES_THE_TARGET"
REASON_IMMATERIAL: Final[str] = "ADDRESSABLE_ERROR_MASS_BELOW_ACCEPTANCE_FLOOR"
REASON_SOURCE_LEAD_EXHAUSTED: Final[str] = "SOURCE_LEAD_ALREADY_FULLY_CONSUMED"


class SignalScreenError(RuntimeError):
    """A screen could not be evaluated, which is not the same as a pass."""


def _policy(repository_root: Path) -> dict[str, Any]:
    path = repository_root / "contracts/onboarding/temporal-evidence-policy.json"
    if not path.exists():
        raise SignalScreenError(f"temporal evidence policy is absent at {path}")
    return json.loads(path.read_text())


def screen_temporal(
    grades: Sequence[str],
    *,
    repository_root: Path,
) -> dict[str, Any]:
    """Does the source's own evidence grade permit historical replay?

    Ingestion success is never sufficient on its own -- that is the policy's first
    sentence, and this screen is the reason it is machine-checked rather than
    asserted in a review comment.
    """

    policy = _policy(repository_root)["grades"]
    unknown = sorted({grade for grade in grades if grade not in policy})
    if unknown:
        raise SignalScreenError(f"grades absent from the frozen policy: {unknown}")
    observed = sorted(set(grades))
    blocking = [
        grade for grade in observed if not policy[grade]["supportsHistoricalReplay"]
    ]
    return {
        "screen": "temporal",
        "observedGrades": observed,
        "replayIneligibleGrades": blocking,
        "passed": not blocking,
        "reasonCode": REASON_NO_HISTORICAL_REPLAY if blocking else None,
    }


def screen_grain(
    signal_keys: Sequence[str],
    serieskey_values: Sequence[str],
    *,
    label: str,
) -> dict[str, Any]:
    """Can the signal's own key reach a SeriesKey at all?"""

    signal = set(signal_keys)
    series = set(serieskey_values)
    overlap = sorted(signal & series)
    return {
        "screen": "grain",
        "joinColumn": label,
        "signalKeyCount": len(signal),
        "seriesKeyCount": len(series),
        "overlappingKeys": len(overlap),
        "passed": bool(overlap),
        "reasonCode": None if overlap else REASON_GRAIN_ABOVE_SERIESKEY,
    }


def screen_leakage(
    observed: pd.Series,
    target: pd.Series,
    *,
    tolerance_days: int = 7,
) -> dict[str, Any]:
    """Does the candidate field reproduce the target?

    Two independent readings, because either alone is arguable: exact agreement,
    and agreement inside a tolerance. A field matching the target's own boundary
    on most keys is that boundary under a different name, whatever the source
    calls its derivation method.
    """

    frame = pd.DataFrame({"observed": observed, "target": target}).dropna()
    if frame.empty:
        raise SignalScreenError("leakage screen received no comparable rows")
    delta = (
        pd.to_datetime(frame["observed"]) - pd.to_datetime(frame["target"])
    ).dt.days
    exact = float((delta == 0).mean())
    within = float((delta.abs() <= tolerance_days).mean())
    reproduces = exact >= TARGET_REPRODUCTION_SHARE or within >= 0.5
    return {
        "screen": "leakage",
        "comparedRows": int(len(frame)),
        "exactAgreementShare": exact,
        "withinToleranceShare": within,
        "toleranceDays": tolerance_days,
        "medianDeltaDays": float(delta.median()),
        "passed": not reproduces,
        "reasonCode": REASON_TARGET_DERIVED if reproduces else None,
    }


def screen_materiality(
    frame: pd.DataFrame,
    *,
    active: pd.Series,
    prediction_column: str = "yhat_p50",
    actual_column: str = "actual_units",
) -> dict[str, Any]:
    """What share of absolute error mass sits on rows where the signal is live?

    This is the same arithmetic that let PP3-B3 reject intermittent routing at
    0.91%: an improvement confined to a small share of error mass is bounded by
    that share, so the acceptance floor decides admissibility before any model is
    fitted.
    """

    error = (
        pd.to_numeric(frame[prediction_column], errors="coerce")
        - pd.to_numeric(frame[actual_column], errors="coerce")
    ).abs()
    total = float(error.sum())
    if total <= 0:
        raise SignalScreenError("materiality screen found no error mass to apportion")
    live = float(error[active.fillna(False).astype(bool)].sum())
    share = 100.0 * live / total
    return {
        "screen": "materiality",
        "activeRows": int(active.fillna(False).astype(bool).sum()),
        "totalRows": int(len(frame)),
        "addressableErrorSharePct": share,
        "acceptanceFloorPct": MIN_ADDRESSABLE_ERROR_SHARE_PCT,
        "passed": share >= MIN_ADDRESSABLE_ERROR_SHARE_PCT,
        "reasonCode": (
            None if share >= MIN_ADDRESSABLE_ERROR_SHARE_PCT else REASON_IMMATERIAL
        ),
    }


def disposition(
    signal_id: str,
    *,
    screens: Sequence[dict[str, Any]],
    already_shipped: bool = False,
    notes: str = "",
) -> dict[str, Any]:
    """Reduce screens to one verdict, keeping the first failure as the reason.

    Unavailability stays reason-coded rather than silent: a signal that is absent
    because the source cannot support it reads differently from one that is absent
    because nobody built it, and only the first is a finished answer.
    """

    ordered = sorted(screens, key=lambda item: SCREENS.index(item["screen"]))
    failed = [item for item in ordered if not item["passed"]]
    if failed:
        verdict = VERDICT_REJECTED
        reason = failed[0]["reasonCode"]
    elif already_shipped:
        verdict = VERDICT_ALREADY_SHIPPED
        reason = None
    else:
        verdict = VERDICT_ADMISSIBLE
        reason = None
    return {
        "signalId": signal_id,
        "verdict": verdict,
        "reasonCode": reason,
        "ablationRequired": verdict == VERDICT_ADMISSIBLE,
        "screens": ordered,
        "firstFailedScreen": failed[0]["screen"] if failed else None,
        "notes": notes,
    }


def screen_report(dispositions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Assemble the reviewable record B6's exit criterion asks for."""

    return {
        "schemaVersion": SIGNAL_SCREEN_VERSION,
        "screenOrder": list(SCREENS),
        "acceptanceFloorPct": MIN_ADDRESSABLE_ERROR_SHARE_PCT,
        "signals": list(dispositions),
        "admissible": [
            item["signalId"]
            for item in dispositions
            if item["verdict"] == VERDICT_ADMISSIBLE
        ],
        "alreadyShipped": [
            item["signalId"]
            for item in dispositions
            if item["verdict"] == VERDICT_ALREADY_SHIPPED
        ],
        "rejected": {
            item["signalId"]: item["reasonCode"]
            for item in dispositions
            if item["verdict"] == VERDICT_REJECTED
        },
        "rule": (
            "Screens run in cost order and the first failure is terminal. An "
            "ablation is only run for a signal that survives all four, so a "
            "rejected signal always carries the screen that rejected it."
        ),
    }


__all__ = [
    "MIN_ADDRESSABLE_ERROR_SHARE_PCT",
    "REASON_GRAIN_ABOVE_SERIESKEY",
    "REASON_IMMATERIAL",
    "REASON_NO_HISTORICAL_REPLAY",
    "REASON_SOURCE_LEAD_EXHAUSTED",
    "REASON_TARGET_DERIVED",
    "SCREENS",
    "SIGNAL_SCREEN_VERSION",
    "TARGET_REPRODUCTION_SHARE",
    "VERDICT_ADMISSIBLE",
    "VERDICT_ALREADY_SHIPPED",
    "VERDICT_REJECTED",
    "SignalScreenError",
    "disposition",
    "screen_grain",
    "screen_leakage",
    "screen_materiality",
    "screen_report",
    "screen_temporal",
]
