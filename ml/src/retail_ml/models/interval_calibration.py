"""Decision #87 cold-start P90 interval calibration.

Decision #85 evaluates A2 P90 coverage per cohort against an unchanged 0.85-0.95 band.
The established cohort passes everywhere; the cold-start cohort fails everywhere -- 0.7847
globally, 0.8051 india-west, 0.7673 us-new-york -- while the pooled 0.8887 hides it
because 605,904 established rows outvote 102,388 cold-start ones.

Under-coverage means the interval is too narrow. Decision #84's C5 deliberately preserved
the champion's absolute interval width while raising the centre, and its stop rules forbade
adjusting intervals to rescue either direction; that prohibition was scoped to C5, whose
declared target was the estimator. This module is the separately framed interval remedy
decision #85 anticipated by setting a Phase 4 entry deadline.

Mechanism, deliberately the narrowest thing that can work:

    p90' = p50 + k * (p90 - p50),  k >= 1

`p50` is untouched, so A1 non-inferiority, WAPE, bias and every decision #77 display cell
are unchanged BY CONSTRUCTION rather than by measurement. That is the point: a candidate
that cannot move accuracy cannot be mistaken for an accuracy improvement, which decision
#86 forbids for a gate-remediation class.
"""

from __future__ import annotations

from typing import Any, Final, Sequence

import numpy as np
import pandas as pd

from retail_ml.models.bias_correction import CandidateError, split_origins
# Reused from C5 rather than redeclared: two candidates disagreeing about which column
# names the cohort would be a silent correctness bug, not a style difference.
from retail_ml.models.cold_start_blend import COHORT_COLUMN, COLD_START_COHORT
from retail_ml.models.confidence import forecast_confidence
from retail_ml.models.reconciliation import (
    MIN_SEGMENT_ORIGINS,
    MIN_SEGMENT_ROWS,
    MIN_SEGMENT_SERIES,
)

CANDIDATE_ID: Final[str] = "C6"
#: C7 replaces C6's rescaling with a measured width. See the decision #87 addendum.
C7_CANDIDATE_ID: Final[str] = "C7"

#: Split-conformal target. 0.90 is the centre of decision #85's 0.85-0.95 band, not its
#: edge, and it is not moved to buy margin -- that is the boundary-hugging C6's 0.88
#: development target was declared to avoid.
RESIDUAL_QUANTILE: Final[float] = 0.90

#: Reject if mean cold-start confidence falls by this much, relative. The C4 precedent
#: rather than a fresh threshold: C4 was rejected for a widening that would have cost
#: about a third of displayed confidence. Buying coverage by making every cold-start row
#: look worthless moves the problem instead of solving it.
CONFIDENCE_DROP_REJECT_AT: Final[float] = 0.33

#: Same segmentation as C5. Reused rather than re-chosen: a different segmentation would
#: make the two candidates' sufficiency behaviour incomparable for no stated reason.
C6_SEGMENT_COLUMNS: Final[tuple[str, ...]] = ("market_id", "horizon")

#: Frozen 31-point grid. The 2.50 ceiling is a stop rule, not a range: C4 was rejected
#: earlier for a 2.39x widening that would have cost about a third of displayed
#: confidence, so a segment selecting at or near the ceiling rejects the candidate rather
#: than raising the ceiling.
WIDTH_GRID: Final[tuple[float, ...]] = tuple(
    round(1.00 + 0.05 * step, 2) for step in range(31)
)
CEILING_REJECT_AT: Final[float] = 2.40

#: Coverage targeted on the development origins. Deliberately above the 0.85 floor: a
#: factor tuned to sit exactly on the boundary fails confirmation on ordinary sampling
#: noise, and declaring the margin in advance is the honest way to avoid retuning after a
#: near miss.
DEVELOPMENT_TARGET_COVERAGE: Final[float] = 0.88
P90_COVERAGE_MIN: Final[float] = 0.85
P90_COVERAGE_MAX: Final[float] = 0.95


def _coverage(frame: pd.DataFrame, factor: float) -> float | None:
    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    p50 = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    p90 = pd.to_numeric(frame["yhat_p90"], errors="coerce")
    widened = p50 + factor * (p90 - p50)
    usable = actual.notna() & widened.notna()
    if not usable.any():
        return None
    return float((actual[usable] <= widened[usable]).mean())


def _sufficient(frame: pd.DataFrame) -> bool:
    series = frame[["sku_id", "store_id", "channel_id"]].drop_duplicates()
    return bool(
        len(frame) >= MIN_SEGMENT_ROWS
        and len(series) >= MIN_SEGMENT_SERIES
        and frame["forecast_origin"].nunique() >= MIN_SEGMENT_ORIGINS
    )


def _select_factor(frame: pd.DataFrame) -> tuple[float, float | None]:
    """Smallest grid factor reaching the development target.

    Smallest-such-k rather than best-coverage-k: needless width destroys the confidence
    signal decision #12 derives from ``(p90 - p50) / max(p50, 1)``, so the interval is
    kept as tight as the requirement allows. If no factor reaches the target the largest
    is returned and the caller's acceptance criteria reject it -- the grid is not extended
    to chase a number.
    """

    best = WIDTH_GRID[-1]
    achieved = None
    for factor in WIDTH_GRID:
        coverage = _coverage(frame, factor)
        if coverage is None:
            continue
        achieved = coverage
        if coverage >= DEVELOPMENT_TARGET_COVERAGE:
            return factor, coverage
    return best, achieved


def fit_interval_calibration(
    frame: pd.DataFrame,
    *,
    development_origins: int = 8,
    segment_columns: Sequence[str] = C6_SEGMENT_COLUMNS,
) -> dict[str, Any]:
    """Fit `k` per segment on the development origins only.

    Decision #74: the first 8 chronological origins are development data and the final 5
    are untouched confirmation data read once after the model is frozen. This function
    never sees the confirmation rows.
    """

    cold = frame[frame[COHORT_COLUMN].astype(str).eq(COLD_START_COHORT)]
    if cold.empty:
        raise CandidateError(
            "decision #87 targets the cold_start cohort and the frame carries none"
        )
    roles = split_origins(cold, development=development_origins)
    development = cold[cold["forecast_origin"].isin(roles.development)]
    if development.empty:
        raise CandidateError("no development-origin cold-start rows to fit on")

    parent_factor, parent_coverage = _select_factor(development)
    segments: dict[str, Any] = {}
    for key, subset in development.groupby(list(segment_columns), dropna=False):
        label = "|".join(str(part) for part in (key if isinstance(key, tuple) else (key,)))
        if _sufficient(subset):
            factor, coverage = _select_factor(subset)
            basis = "segment"
        else:
            # C3's frozen shrink-to-parent rule. A thin cell borrows the parent factor
            # rather than fitting its own, because a factor fitted on too few series is
            # noise dressed as calibration.
            factor, coverage = parent_factor, _coverage(subset, parent_factor)
            basis = "shrunk_to_parent"
        segments[label] = {
            "factor": factor,
            "developmentCoverage": coverage,
            "basis": basis,
            "rows": int(len(subset)),
        }

    return {
        "candidateId": CANDIDATE_ID,
        "decisionIds": [85, 87],
        "appliesToCohort": COLD_START_COHORT,
        "mechanism": "p90' = p50 + k * (p90 - p50); p50 untouched",
        "segmentColumns": list(segment_columns),
        "grid": list(WIDTH_GRID),
        "gridCeiling": WIDTH_GRID[-1],
        "ceilingRejectAt": CEILING_REJECT_AT,
        "developmentTargetCoverage": DEVELOPMENT_TARGET_COVERAGE,
        "developmentOrigins": [str(origin) for origin in roles.development],
        "confirmationOriginsHeldOut": [str(origin) for origin in roles.confirmation],
        "parent": {"factor": parent_factor, "developmentCoverage": parent_coverage},
        "segments": segments,
        "sufficiency": {
            "minimumRows": MIN_SEGMENT_ROWS,
            "minimumSeries": MIN_SEGMENT_SERIES,
            "minimumOrigins": MIN_SEGMENT_ORIGINS,
        },
        "maximumSelectedFactor": max(
            (entry["factor"] for entry in segments.values()), default=parent_factor
        ),
    }


def _residual_quantile(frame: pd.DataFrame) -> float | None:
    """Empirical 90th percentile of (actual - p50) within a segment."""

    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    p50 = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    residual = (actual - p50).dropna()
    if residual.empty:
        return None
    return float(np.quantile(residual, RESIDUAL_QUANTILE))


def fit_residual_intervals(
    frame: pd.DataFrame,
    *,
    development_origins: int = 8,
    segment_columns: Sequence[str] = C6_SEGMENT_COLUMNS,
) -> dict[str, Any]:
    """C7: fit an interval WIDTH from observed dispersion, on development origins only.

    C6 scaled the champion's existing spread and could not reach the target where that
    spread was mis-scaled to begin with -- 14 of 52 segments pinned at its grid ceiling.
    This sets the width from the residual distribution instead, so there is no arbitrary
    multiple to cap and the quantile level itself is the whole model.
    """

    cold = frame[frame[COHORT_COLUMN].astype(str).eq(COLD_START_COHORT)]
    if cold.empty:
        raise CandidateError(
            "decision #87 targets the cold_start cohort and the frame carries none"
        )
    roles = split_origins(cold, development=development_origins)
    development = cold[cold["forecast_origin"].isin(roles.development)]
    if development.empty:
        raise CandidateError("no development-origin cold-start rows to fit on")

    parent_offset = _residual_quantile(development)
    if parent_offset is None:
        raise CandidateError("cold-start residuals are entirely unusable")
    segments: dict[str, Any] = {}
    for key, subset in development.groupby(list(segment_columns), dropna=False):
        label = "|".join(str(part) for part in (key if isinstance(key, tuple) else (key,)))
        offset = _residual_quantile(subset) if _sufficient(subset) else None
        basis = "segment" if offset is not None else "shrunk_to_parent"
        if offset is None:
            offset = parent_offset
        segments[label] = {
            # max(q, 0) keeps p90 >= p50 where p50 over-forecasts and the raw residual
            # quantile is negative, so quantile ordering stays valid.
            "offset": max(float(offset), 0.0),
            "rawQuantile": float(offset),
            "basis": basis,
            "rows": int(len(subset)),
        }

    return {
        "candidateId": C7_CANDIDATE_ID,
        "decisionIds": [85, 87],
        "appliesToCohort": COLD_START_COHORT,
        "mechanism": (
            "p90' = p50 + max(quantile_0.90(actual - p50), 0); p50 untouched; "
            "split-conformal, width measured not rescaled"
        ),
        "residualQuantile": RESIDUAL_QUANTILE,
        "segmentColumns": list(segment_columns),
        "developmentOrigins": [str(origin) for origin in roles.development],
        "confirmationOriginsHeldOut": [str(origin) for origin in roles.confirmation],
        "parent": {"offset": max(float(parent_offset), 0.0)},
        "segments": segments,
        "sufficiency": {
            "minimumRows": MIN_SEGMENT_ROWS,
            "minimumSeries": MIN_SEGMENT_SERIES,
            "minimumOrigins": MIN_SEGMENT_ORIGINS,
        },
        "confidenceDropRejectAt": CONFIDENCE_DROP_REJECT_AT,
    }


def apply_residual_intervals(
    frame: pd.DataFrame,
    model: dict[str, Any],
) -> pd.DataFrame:
    """Set cold-start P90 from the fitted offsets; recompute confidence per #12."""

    result = frame.copy()
    segment_columns = list(model["segmentColumns"])
    is_cold = result[COHORT_COLUMN].astype(str).eq(COLD_START_COHORT)

    offsets = pd.Series(np.nan, index=result.index, dtype="float64")
    labels = result[segment_columns].astype(str).agg("|".join, axis=1)
    for label, entry in model["segments"].items():
        offsets[is_cold & labels.eq(label)] = float(entry["offset"])
    offsets[is_cold & offsets.isna()] = float(model["parent"]["offset"])

    p50 = pd.to_numeric(result["yhat_p50"], errors="coerce")
    result.loc[is_cold, "yhat_p90"] = (p50 + offsets)[is_cold]
    result.loc[is_cold, "confidence"] = forecast_confidence(
        result.loc[is_cold, "yhat_p50"], result.loc[is_cold, "yhat_p90"]
    )
    return result


def remediate_intervals_c7(
    frame: pd.DataFrame,
    *,
    development_origins: int = 8,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit and apply C7, retaining the champion interval for decision #86 §2.3."""

    model = fit_residual_intervals(frame, development_origins=development_origins)
    prepared = frame.copy()
    if "champion_p90" not in prepared.columns:
        prepared["champion_p90"] = prepared["yhat_p90"]
    if "champion_p50" not in prepared.columns:
        prepared["champion_p50"] = prepared["yhat_p50"]
    applied = apply_residual_intervals(prepared, model)

    cold = applied[COHORT_COLUMN].astype(str).eq(COLD_START_COHORT)
    before = float(pd.to_numeric(frame.loc[cold, "confidence"], errors="coerce").mean())
    after = float(pd.to_numeric(applied.loc[cold, "confidence"], errors="coerce").mean())
    model["confidence"] = {
        "coldStartBefore": before,
        "coldStartAfter": after,
        "relativeChange": (after - before) / before if before else None,
    }
    model["appliedCohortCoverage"] = cohort_coverage(applied)
    return applied, model


def apply_interval_calibration(
    frame: pd.DataFrame,
    model: dict[str, Any],
) -> pd.DataFrame:
    """Widen cold-start P90 only, and recompute confidence per decision #12.

    Established rows are returned untouched on both P50 and P90 so decision #86 §2.3's
    byte-identical check passes structurally rather than by assertion.
    """

    result = frame.copy()
    segment_columns = list(model["segmentColumns"])
    is_cold = result[COHORT_COLUMN].astype(str).eq(COLD_START_COHORT)

    factors = pd.Series(np.nan, index=result.index, dtype="float64")
    labels = result[segment_columns].astype(str).agg("|".join, axis=1)
    for label, entry in model["segments"].items():
        factors[is_cold & labels.eq(label)] = float(entry["factor"])
    # A cold-start segment absent from the model was never fitted; the parent factor is
    # the declared fallback rather than 1.0, which would silently leave it uncalibrated.
    factors[is_cold & factors.isna()] = float(model["parent"]["factor"])

    p50 = pd.to_numeric(result["yhat_p50"], errors="coerce")
    p90 = pd.to_numeric(result["yhat_p90"], errors="coerce")
    widened = p50 + factors * (p90 - p50)
    result.loc[is_cold, "yhat_p90"] = widened[is_cold]

    # Confidence is derived from the interval, so a widened interval MUST lower it.
    # Publishing the old confidence beside a wider interval would misreport certainty.
    result.loc[is_cold, "confidence"] = forecast_confidence(
        result.loc[is_cold, "yhat_p50"], result.loc[is_cold, "yhat_p90"]
    )
    return result


def cohort_coverage(frame: pd.DataFrame) -> dict[str, float | None]:
    """Coverage per cohort, for reporting a candidate's effect on the #85 gate."""

    out: dict[str, float | None] = {}
    for label, subset in frame.groupby(frame[COHORT_COLUMN].astype(str)):
        out[str(label)] = _coverage(subset, 1.0)
    return out


def remediate_intervals(
    frame: pd.DataFrame,
    *,
    development_origins: int = 8,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit and apply C6 in one step, preserving the champion interval for comparison."""

    model = fit_interval_calibration(
        frame, development_origins=development_origins
    )
    prepared = frame.copy()
    if "champion_p90" not in prepared.columns:
        prepared["champion_p90"] = prepared["yhat_p90"]
    if "champion_p50" not in prepared.columns:
        prepared["champion_p50"] = prepared["yhat_p50"]
    applied = apply_interval_calibration(prepared, model)
    model["appliedCohortCoverage"] = cohort_coverage(applied)
    return applied, model


__all__ = [
    "C6_SEGMENT_COLUMNS",
    "C7_CANDIDATE_ID",
    "CONFIDENCE_DROP_REJECT_AT",
    "RESIDUAL_QUANTILE",
    "apply_residual_intervals",
    "fit_residual_intervals",
    "remediate_intervals_c7",
    "CANDIDATE_ID",
    "CEILING_REJECT_AT",
    "DEVELOPMENT_TARGET_COVERAGE",
    "WIDTH_GRID",
    "apply_interval_calibration",
    "cohort_coverage",
    "fit_interval_calibration",
    "remediate_intervals",
]
