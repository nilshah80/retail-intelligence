"""PP3-B4 candidates C1 (P50 bias) and C2 (P90 calibration).

Both learn only from **development origins**. A correction fitted on the rows it
is scored against is not evidence, so the fit population and the confirmation
population are disjoint by construction, and the fitter refuses to see a
confirmation origin at all.

PP3-B3 measured mixed-sign bias — 26 of 41 categories under-forecast, 10
over-forecast — so a single global shift would help some slices by harming
others. C1 is therefore segmented at market x horizon with explicit shrinkage to
a sufficient parent, never a global constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Sequence

import numpy as np
import pandas as pd

C1_ID: Final[str] = "C1"
C2_ID: Final[str] = "C2"

#: A cell needs this many rows and this much actual volume before its own factor
#: is trusted; otherwise it shrinks to the parent.
MIN_CELL_ROWS: Final[int] = 200
MIN_CELL_ACTUAL: Final[float] = 100.0

#: Decision #58 / A2 coverage band. Sharpening may not leave it.
COVERAGE_MIN: Final[float] = 0.85
COVERAGE_MAX: Final[float] = 0.95

#: A correction factor is clamped so one noisy cell cannot rescale a forecast.
MIN_FACTOR: Final[float] = 0.5
MAX_FACTOR: Final[float] = 2.0

SEGMENT_COLUMNS: Final[tuple[str, ...]] = ("market_id", "horizon")


class CandidateError(RuntimeError):
    """A candidate would leak, or would violate a domain rule."""


@dataclass(frozen=True)
class OriginRoles:
    """Which origins may be fitted on, and which are held back."""

    development: tuple[Any, ...]
    confirmation: tuple[Any, ...]

    def __post_init__(self) -> None:
        overlap = set(self.development) & set(self.confirmation)
        if overlap:
            raise CandidateError(
                f"development and confirmation origins overlap: {sorted(overlap)}"
            )


def split_origins(
    frame: pd.DataFrame,
    *,
    development: int = 8,
) -> OriginRoles:
    origins = tuple(sorted(frame["forecast_origin"].unique()))
    return OriginRoles(
        development=origins[:development],
        confirmation=origins[development:],
    )


def _guard_no_confirmation_leak(
    frame: pd.DataFrame,
    roles: OriginRoles,
) -> None:
    seen = set(frame["forecast_origin"].unique())
    leaked = sorted(seen & set(roles.confirmation))
    if leaked:
        raise CandidateError(
            f"fit population includes confirmation origins: {leaked}"
        )


# ---------------------------------------------------------------------------
# C1: segmented P50 bias correction.
# ---------------------------------------------------------------------------
def fit_bias_correction(
    frame: pd.DataFrame,
    roles: OriginRoles,
    *,
    segment_columns: Sequence[str] = SEGMENT_COLUMNS,
) -> dict[str, Any]:
    """Learn multiplicative factors from development origins only."""

    fit_rows = frame[frame["forecast_origin"].isin(roles.development)]
    _guard_no_confirmation_leak(fit_rows, roles)
    if fit_rows.empty:
        raise CandidateError("no development rows available to fit C1")

    def _factor(group: pd.DataFrame) -> float | None:
        predicted = float(pd.to_numeric(group["yhat_p50"], errors="coerce").sum())
        actual = float(pd.to_numeric(group["actual_units"], errors="coerce").sum())
        if predicted <= 0 or actual <= 0:
            return None
        return actual / predicted

    parent = _factor(fit_rows)
    if parent is None:
        raise CandidateError("development rows carry no usable volume")

    cells: dict[str, Any] = {}
    shrunk = 0
    for key, group in fit_rows.groupby(list(segment_columns), sort=True, observed=True):
        rows = len(group)
        actual = float(pd.to_numeric(group["actual_units"], errors="coerce").sum())
        own = _factor(group)
        sufficient = (
            own is not None and rows >= MIN_CELL_ROWS and actual >= MIN_CELL_ACTUAL
        )
        factor = own if sufficient else parent
        if not sufficient:
            shrunk += 1
        cells["|".join(str(part) for part in key)] = {
            "factor": float(np.clip(factor, MIN_FACTOR, MAX_FACTOR)),
            "rows": rows,
            "actualSum": actual,
            "sufficient": bool(sufficient),
            "shrunkToParent": not sufficient,
        }
    return {
        "candidateId": C1_ID,
        "segmentColumns": list(segment_columns),
        "parentFactor": float(np.clip(parent, MIN_FACTOR, MAX_FACTOR)),
        "cells": cells,
        "cellsShrunkToParent": shrunk,
        "fitOrigins": [str(value) for value in roles.development],
        "minimumCellRows": MIN_CELL_ROWS,
        "minimumCellActual": MIN_CELL_ACTUAL,
        "factorClamp": [MIN_FACTOR, MAX_FACTOR],
    }


def apply_bias_correction(
    frame: pd.DataFrame,
    model: dict[str, Any],
) -> pd.DataFrame:
    """Apply C1, preserving the non-negative domain and P90 >= P50."""

    result = frame.copy()
    segment_columns = list(model["segmentColumns"])
    keys = result[segment_columns].astype(str).agg("|".join, axis=1)
    factors = keys.map(
        {name: cell["factor"] for name, cell in model["cells"].items()}
    ).fillna(model["parentFactor"])

    corrected = pd.to_numeric(result["yhat_p50"], errors="coerce") * factors
    result["yhat_p50"] = corrected.clip(lower=0.0)
    # A correction must never invert the quantiles.
    result["yhat_p90"] = np.maximum(
        pd.to_numeric(result["yhat_p90"], errors="coerce"),
        result["yhat_p50"],
    )
    if (result["yhat_p50"] < 0).any():
        raise CandidateError("C1 produced a negative P50")
    if (result["yhat_p90"] < result["yhat_p50"]).any():
        raise CandidateError("C1 inverted P90 below P50")
    return result


# ---------------------------------------------------------------------------
# C2: P90 quantile calibration.
# ---------------------------------------------------------------------------
def fit_quantile_calibration(
    frame: pd.DataFrame,
    roles: OriginRoles,
    *,
    segment_columns: Sequence[str] = SEGMENT_COLUMNS,
    target_coverage: float = 0.90,
) -> dict[str, Any]:
    """Learn P90 spread multipliers from development origins only."""

    fit_rows = frame[frame["forecast_origin"].isin(roles.development)]
    _guard_no_confirmation_leak(fit_rows, roles)
    if fit_rows.empty:
        raise CandidateError("no development rows available to fit C2")

    def _multiplier(group: pd.DataFrame) -> float | None:
        p50 = pd.to_numeric(group["yhat_p50"], errors="coerce")
        p90 = pd.to_numeric(group["yhat_p90"], errors="coerce")
        actual = pd.to_numeric(group["actual_units"], errors="coerce")
        spread = (p90 - p50).clip(lower=0.0)
        if len(group) == 0 or float(spread.sum()) <= 0:
            return None
        residual = (actual - p50).clip(lower=0.0)
        # The spread that would have covered `target_coverage` of residuals.
        needed = float(np.quantile(residual, target_coverage))
        observed = float(spread.mean())
        if observed <= 0:
            return None
        return needed / observed

    parent = _multiplier(fit_rows) or 1.0
    cells: dict[str, Any] = {}
    fallbacks = 0
    for key, group in fit_rows.groupby(list(segment_columns), sort=True, observed=True):
        own = _multiplier(group)
        sufficient = own is not None and len(group) >= MIN_CELL_ROWS
        if not sufficient:
            fallbacks += 1
        multiplier = own if sufficient else parent
        cells["|".join(str(part) for part in key)] = {
            "multiplier": float(np.clip(multiplier, MIN_FACTOR, MAX_FACTOR)),
            "rows": len(group),
            "sufficient": bool(sufficient),
            "usedFallback": not sufficient,
        }
    return {
        "candidateId": C2_ID,
        "segmentColumns": list(segment_columns),
        "targetCoverage": target_coverage,
        "parentMultiplier": float(np.clip(parent, MIN_FACTOR, MAX_FACTOR)),
        "cells": cells,
        "cellsUsingFallback": fallbacks,
        "fitOrigins": [str(value) for value in roles.development],
        "coverageBand": [COVERAGE_MIN, COVERAGE_MAX],
    }


def apply_quantile_calibration(
    frame: pd.DataFrame,
    model: dict[str, Any],
) -> pd.DataFrame:
    """Apply C2. P90 may narrow, but never below P50."""

    result = frame.copy()
    segment_columns = list(model["segmentColumns"])
    keys = result[segment_columns].astype(str).agg("|".join, axis=1)
    multipliers = keys.map(
        {name: cell["multiplier"] for name, cell in model["cells"].items()}
    ).fillna(model["parentMultiplier"])

    p50 = pd.to_numeric(result["yhat_p50"], errors="coerce")
    spread = (pd.to_numeric(result["yhat_p90"], errors="coerce") - p50).clip(lower=0.0)
    result["yhat_p90"] = (p50 + spread * multipliers).clip(lower=0.0)
    result["yhat_p90"] = np.maximum(result["yhat_p90"], result["yhat_p50"])
    if (result["yhat_p90"] < result["yhat_p50"]).any():
        raise CandidateError("C2 inverted P90 below P50")
    return result



#: The frozen C2 model, written by the backtest and replayed at scoring time.
COVERAGE_MODEL_FILENAME: Final[str] = "coverage_calibration_model.json"


def remediate_coverage(
    frame: pd.DataFrame,
    *,
    development_origins: int = 8,
    only_cohort: str = "cold_start",
    cohort_column: str = "cohort",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit and apply C2 to one cohort, restoring the rest byte-for-byte.

    The defect this repairs is a stated contract being missed, not a demo blemish.
    Decision #58 puts P90 coverage in an 85-95 per cent band. Measured on the
    published eval, the network is inside it at 89.1 per cent -- but split by
    cohort, `established_history` sits at 90.5 and `cold_start` at 80.6, so nearly
    a quarter of volume is served an interval narrower than the band allows. A
    pooled figure hid it.

    Scoped to cold start, and P90-only, for governance reasons rather than taste:
    decision #86 section 2.4 compares display-cell ACCURACY, which is computed
    from P50, so a P90-only correction cannot regress it; and section 2.3's
    byte-identity rule covers rows outside C5's target, which this never touches.
    That is the arrangement C1 could not reach -- C1 had to move P50 on the same
    rows C5 owned, and one gate or the other refused every ordering.

    Deliberately NOT a bias correction. sum(P50) sits 5 per cent below sum(actual)
    because P50 is a MEDIAN and the demand is heavily right-skewed -- mean 27.68
    against median 6.00, skew 8.44 -- so a well-calibrated median must sum low.
    P(actual <= P50) is 52.8 per cent, which is a median doing its job. PP3-B4
    already tested inflating P50: it eliminated the bias and WORSENED WAPE,
    because WAPE is a median-optimal loss. Widening the interval is the honest
    repair; raising the point forecast is not.
    """

    from retail_ml.models.confidence import forecast_confidence

    if cohort_column not in frame.columns:
        raise CandidateError(
            f"C2 requires a {cohort_column!r} column to scope to {only_cohort!r}"
        )
    target = frame[cohort_column].astype(str) == only_cohort
    if not bool(target.any()):
        raise CandidateError(f"no {only_cohort!r} rows to calibrate")

    roles = split_origins(frame, development=development_origins)
    model = fit_quantile_calibration(frame[target], roles)
    before_p90 = pd.to_numeric(frame["yhat_p90"], errors="coerce")
    applied = apply_quantile_calibration(frame, model)
    # Restored from the original column so untouched rows are byte-identical, not
    # merely close.
    applied.loc[~target, "yhat_p90"] = before_p90[~target]
    # Decision #12: confidence is derived from the P50-P90 spread, so moving P90
    # without recomputing it leaves the two inconsistent. That is what the
    # publisher refused the first C5 bundle for.
    if "confidence" in applied.columns:
        applied["confidence"] = forecast_confidence(
            applied["yhat_p50"], applied["yhat_p90"]
        )
    model = {
        **model,
        "decisionIds": ["#58", "#12"],
        "correctionTarget": "yhat_p90",
        "scopedToCohort": only_cohort,
        "confirmationOriginsHeldOut": [str(v) for v in roles.confirmation],
        "notAnAccuracyImprovement": (
            "C2 widens an interval that was narrower than decision #58 allows. It "
            "does not move the point forecast and is not an accuracy claim."
        ),
    }
    return applied, model


__all__ = [
    "COVERAGE_MODEL_FILENAME",
    "C1_ID",
    "C2_ID",
    "COVERAGE_MAX",
    "COVERAGE_MIN",
    "MAX_FACTOR",
    "MIN_CELL_ACTUAL",
    "MIN_CELL_ROWS",
    "MIN_FACTOR",
    "SEGMENT_COLUMNS",
    "CandidateError",
    "OriginRoles",
    "apply_bias_correction",
    "apply_quantile_calibration",
    "fit_bias_correction",
    "fit_quantile_calibration",
    "remediate_coverage",
    "split_origins",
]
