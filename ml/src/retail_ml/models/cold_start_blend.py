"""Candidate C5: the decision #84 cold-start shrinkage estimator.

Every constant here is fixed by decision #84, which was frozen before this module
was written. Nothing in it may be re-chosen after a result is visible -- that is
the point of having framed the decision first, and PP3-B4's C2 already
demonstrated the alternative: a criterion added after seeing a result cannot be
distinguished from tuning to admit the candidate.

Why a blend rather than a sixth rescaling. Measured on the decision #83 bundle,
the champion beats the cold-start comparator on 54.0% of us-new-york rows and
still loses on WAPE, because it is under-dispersed (prediction std 93.66 against
an actual 132.54, comparator 118.50) and more under-biased (-23.50% against
-15.00%). The deficit is entirely long-horizon: the champion wins h1-h4 by 15.0%
relative and loses h14-h26 by 9.0%, and that band carries 56.0% of the cohort's
error. C1 and C3 both failed because a single factor cannot preserve short-horizon
skill while deferring at long horizons. A horizon-varying blend weight can.
"""

from __future__ import annotations

from typing import Any, Final, Sequence

import numpy as np
import pandas as pd

from retail_ml.models.bias_correction import CandidateError, OriginRoles
from retail_ml.models.confidence import forecast_confidence
from retail_ml.models.reconciliation import (
    MIN_SEGMENT_ORIGINS,
    MIN_SEGMENT_ROWS,
    MIN_SEGMENT_SERIES,
)

C5_ID: Final[str] = "C5"
DECISION_IDS: Final[tuple[int, ...]] = (84,)

#: Decision #84 §3.2. Exact horizon, never a band: a band boundary is a choice
#: that could be placed after seeing where the champion crosses over.
C5_SEGMENT_COLUMNS: Final[tuple[str, ...]] = ("market_id", "horizon")

#: Decision #84 §3.3. A grid rather than an optimiser so the fit is exactly
#: reproducible and no seed or convergence tolerance can drift between runs.
BLEND_GRID: Final[tuple[float, ...]] = tuple(round(0.05 * step, 2) for step in range(21))

#: Decision #84 §3.1. The blend target, retained on review over `ma13`: for
#: thin-history series the two are numerically almost the same estimator, so
#: substituting it would buy the appearance of independence from the A1 yardstick
#: rather than the substance.
COMPARATOR_COLUMN: Final[str] = "cold_start_baseline"

COHORT_COLUMN: Final[str] = "cohort"
COLD_START_COHORT: Final[str] = "cold_start"


def _wape(actual: pd.Series, predicted: pd.Series) -> float | None:
    total = float(actual.sum())
    if total <= 0:
        return None
    return float((predicted - actual).abs().sum()) / total


def _blend(champion: pd.Series, comparator: pd.Series, weight: float) -> pd.Series:
    return champion * weight + comparator * (1.0 - weight)


def _best_weight(frame: pd.DataFrame) -> tuple[float | None, dict[str, Any]]:
    """Pick the grid weight minimising cell WAPE.

    WAPE is the acceptance metric, so it is also the fitting objective. PP3-B4
    established why that matters: C1 optimised bias instead, eliminated it
    (-6.72% to +0.62%), and *worsened* WAPE, because P50 is a median forecast and
    WAPE is a median-optimal loss.
    """

    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    champion = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    comparator = pd.to_numeric(frame[COMPARATOR_COLUMN], errors="coerce")
    if actual.sum() <= 0:
        return None, {}
    scores = {
        weight: _wape(actual, _blend(champion, comparator, weight))
        for weight in BLEND_GRID
    }
    usable = {w: s for w, s in scores.items() if s is not None}
    if not usable:
        return None, {}
    # Ties resolve to the larger weight, which keeps more of the fitted model
    # rather than silently drifting toward the comparator on an exact tie.
    best = min(usable, key=lambda w: (usable[w], -w))
    return best, {
        "gridWapeAtSelected": usable[best],
        "gridWapeAtChampion": usable.get(1.0),
        "gridWapeAtComparator": usable.get(0.0),
    }


def _sufficient(frame: pd.DataFrame) -> bool:
    series = frame[["sku_id", "store_id", "channel_id"]].drop_duplicates()
    return (
        len(frame) >= MIN_SEGMENT_ROWS
        and len(series) >= MIN_SEGMENT_SERIES
        and frame["forecast_origin"].nunique() >= MIN_SEGMENT_ORIGINS
    )


def fit_cold_start_blend(
    frame: pd.DataFrame,
    roles: OriginRoles,
    *,
    segment_columns: Sequence[str] = C5_SEGMENT_COLUMNS,
) -> dict[str, Any]:
    """Fit the blend weight on development origins only.

    Reading a confirmation origin here would invalidate the candidate under
    decision #84's first stop rule, so the overlap is asserted rather than
    assumed.
    """

    if COHORT_COLUMN not in frame.columns:
        raise CandidateError(
            f"C5 requires a {COHORT_COLUMN!r} column assigned by decisions #82/#83"
        )
    if COMPARATOR_COLUMN not in frame.columns:
        raise CandidateError(f"C5 requires the {COMPARATOR_COLUMN!r} column")

    cold_start = frame[frame[COHORT_COLUMN] == COLD_START_COHORT]
    fit_rows = cold_start[cold_start["forecast_origin"].isin(roles.development)]
    leaked = sorted(
        set(fit_rows["forecast_origin"].unique()) & set(roles.confirmation)
    )
    if leaked:
        raise CandidateError(
            f"C5 fit population includes confirmation origins: {leaked}"
        )
    if fit_rows.empty:
        raise CandidateError("no development cold-start rows available to fit C5")

    global_weight, global_scores = _best_weight(fit_rows)
    if global_weight is None:
        raise CandidateError("development cold-start rows carry no usable volume")

    market_weights: dict[str, float] = {}
    for market, group in fit_rows.groupby("market_id", sort=True, observed=True):
        weight, _ = _best_weight(group)
        market_weights[str(market)] = (
            weight if weight is not None and _sufficient(group) else global_weight
        )

    segments: dict[str, Any] = {}
    shrunk = 0
    for key, group in fit_rows.groupby(list(segment_columns), sort=True, observed=True):
        parts = key if isinstance(key, tuple) else (key,)
        name = "|".join(str(part) for part in parts)
        market = str(parts[0])
        own, scores = _best_weight(group)
        sufficient = own is not None and _sufficient(group)
        if sufficient and own is not None:
            weight = own
            shrink_level = None
        else:
            shrunk += 1
            weight = market_weights.get(market, global_weight)
            shrink_level = "market" if market in market_weights else "global"
        series = group[["sku_id", "store_id", "channel_id"]].drop_duplicates()
        segments[name] = {
            "weight": float(weight),
            "rows": int(len(group)),
            "seriesKeys": int(len(series)),
            "origins": int(group["forecast_origin"].nunique()),
            "sufficient": bool(sufficient),
            "shrunkTo": shrink_level,
            **scores,
        }

    return {
        "candidateId": C5_ID,
        "decisionIds": list(DECISION_IDS),
        "segmentColumns": list(segment_columns),
        "blendTarget": COMPARATOR_COLUMN,
        "grid": list(BLEND_GRID),
        "globalWeight": float(global_weight),
        "marketWeights": market_weights,
        "segments": segments,
        "segmentsShrunkToParent": shrunk,
        "globalScores": global_scores,
        "sufficiencyRule": {
            "minimumRows": MIN_SEGMENT_ROWS,
            "minimumSeriesKeys": MIN_SEGMENT_SERIES,
            "minimumOrigins": MIN_SEGMENT_ORIGINS,
            "frozenBeforeScoring": True,
            "source": "decision #84 §3.2 reuses C3's rule unchanged",
        },
        "fitOrigins": [str(value) for value in roles.development],
        # A property of the fit, so it belongs to the fit. The verifier now requires
        # it on every remediation bundle, and deriving it later in the pipeline meant
        # a model produced by fit_cold_start_blend alone could not satisfy that.
        "confirmationOriginsHeldOut": [str(value) for value in roles.confirmation],
        "appliesToCohort": COLD_START_COHORT,
        "objective": "minimise cell WAPE over the frozen grid",
    }


def apply_cold_start_blend(
    frame: pd.DataFrame,
    model: dict[str, Any],
    *,
    candidate_column: str = "c5_p50",
    candidate_upper_column: str = "c5_p90",
) -> pd.DataFrame:
    """Blend cold-start rows and leave established rows exactly as they were.

    P90 keeps the champion's **absolute** interval width per decision #84 §3.1,
    so A2 coverage moves only because the centre moved. Re-fitting the interval
    at the same time would make a coverage change impossible to attribute, and
    adjusting it to rescue coverage is a stop rule in either direction.
    """

    result = frame.copy()
    champion = pd.to_numeric(result["yhat_p50"], errors="coerce")
    upper = pd.to_numeric(result["yhat_p90"], errors="coerce")
    comparator = pd.to_numeric(result[COMPARATOR_COLUMN], errors="coerce")
    width = upper - champion

    columns = list(model["segmentColumns"])
    keys = result[columns].astype(str).agg("|".join, axis=1)
    weights = keys.map(
        {name: segment["weight"] for name, segment in model["segments"].items()}
    )
    weights = weights.fillna(
        result["market_id"].astype(str).map(model["marketWeights"])
    ).fillna(model["globalWeight"])

    is_cold_start = result[COHORT_COLUMN].eq(COLD_START_COHORT)
    # A cold-start row without a comparator would silently fall back to the
    # champion. Decision #83 guarantees one exists, so assert it instead.
    missing = int((is_cold_start & comparator.isna()).sum())
    if missing:
        raise CandidateError(
            f"{missing} cold-start rows lack {COMPARATOR_COLUMN!r}; decision #83 "
            "guarantees a comparator for every cold-start row"
        )

    blended = _blend(champion, comparator, weights).clip(lower=0.0)
    result[candidate_column] = np.where(is_cold_start, blended, champion)
    result[candidate_upper_column] = np.where(
        is_cold_start,
        np.maximum(result[candidate_column] + width.fillna(0.0), result[candidate_column]),
        upper,
    )
    return result


def established_rows_unchanged(
    frame: pd.DataFrame,
    *,
    candidate_column: str = "c5_p50",
    candidate_upper_column: str = "c5_p90",
) -> dict[str, Any]:
    """Decision #84 §4 criterion 3, as a structural check rather than a claim."""

    established = frame[frame[COHORT_COLUMN] != COLD_START_COHORT]
    p50_identical = bool(
        established[candidate_column]
        .astype(float)
        .equals(established["yhat_p50"].astype(float))
    )
    p90_identical = bool(
        established[candidate_upper_column]
        .astype(float)
        .equals(established["yhat_p90"].astype(float))
    )
    return {
        "rows": int(len(established)),
        "p50Identical": p50_identical,
        "p90Identical": p90_identical,
        "passed": p50_identical and p90_identical,
    }


def remediate_cold_start(
    frame: pd.DataFrame,
    *,
    development_origins: int = 8,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fit and apply C5 in one step, replacing the served P50/P90.

    The champion values are retained as `champion_p50`/`champion_p90` rather than
    discarded: decision #86 §2.3 requires proving the untargeted population is
    byte-identical, and that check needs the original to compare against.

    Cohorts are assigned here rather than taken on trust, because the blend is
    keyed on cohort membership and a mislabelled row would be silently blended or
    silently skipped.
    """

    from retail_ml.models.bias_correction import split_origins
    from retail_ml.models.cohorts import assign_cohorts

    cohorted = assign_cohorts(frame)
    roles = split_origins(cohorted, development=development_origins)
    model = fit_cold_start_blend(cohorted, roles)
    applied = apply_cold_start_blend(cohorted, model)
    applied["champion_p50"] = pd.to_numeric(applied["yhat_p50"], errors="coerce")
    applied["champion_p90"] = pd.to_numeric(applied["yhat_p90"], errors="coerce")
    applied["yhat_p50"] = applied["c5_p50"]
    applied["yhat_p90"] = applied["c5_p90"]
    applied = applied.drop(columns=["c5_p50", "c5_p90"])
    # Decision #12 derives confidence from the relative P50-P90 spread, so moving
    # the served quantiles without recomputing it leaves the two inconsistent. The
    # publisher validates this and refused the first C5 bundle for exactly that
    # reason -- a fail-closed check catching an incomplete integration rather than
    # a modelling error.
    if "confidence" in applied.columns:
        applied["confidence"] = forecast_confidence(
            applied["yhat_p50"], applied["yhat_p90"]
        )
    return applied, model


BLEND_MODEL_FILENAME: Final[str] = "cold_start_blend_model.json"


def apply_frozen_blend(
    frame: pd.DataFrame,
    model: dict[str, Any],
    history: pd.DataFrame,
    partial_history: pd.DataFrame,
) -> pd.DataFrame:
    """Apply already-fitted weights to a serving cycle. Never refits.

    The current cycle has a single origin, so refitting is both impossible and
    wrong: decision #84 fits on 8 development origins and the served estimator must
    be the same one the acceptance gate scored. A serving path that refit -- or that
    skipped the blend entirely -- would certify one estimator and serve another.
    """

    from retail_ml.models.cohorts import assign_cohorts, attach_cold_start_baseline

    prepared = attach_cold_start_baseline(frame, history, partial_history)
    prepared = assign_cohorts(prepared)
    applied = apply_cold_start_blend(prepared, model)
    applied["champion_p50"] = pd.to_numeric(applied["yhat_p50"], errors="coerce")
    applied["champion_p90"] = pd.to_numeric(applied["yhat_p90"], errors="coerce")
    applied["yhat_p50"] = applied["c5_p50"]
    applied["yhat_p90"] = applied["c5_p90"]
    applied = applied.drop(columns=["c5_p50", "c5_p90"])
    if "confidence" in applied.columns:
        applied["confidence"] = forecast_confidence(
            applied["yhat_p50"], applied["yhat_p90"]
        )
    return applied


__all__ = [
    "BLEND_GRID",
    "BLEND_MODEL_FILENAME",
    "apply_frozen_blend",
    "C5_ID",
    "C5_SEGMENT_COLUMNS",
    "COLD_START_COHORT",
    "COMPARATOR_COLUMN",
    "DECISION_IDS",
    "apply_cold_start_blend",
    "established_rows_unchanged",
    "fit_cold_start_blend",
    "remediate_cold_start",
]
