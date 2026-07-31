"""PP3-B5 candidates C3 (segmented champions) and C4 (hierarchical reconciliation).

C3 is deliberately scoped to the causes PP3-B3 ranked material by **error mass**:
category composition (H2, 88.6% addressable) and cold-start (H4, 32.0%). It is
*not* scoped to intermittent routing or model pooling, which B3 rejected at 0.91%
of recoverable error — segmenting those would move a display number and not the
acceptance gate.

C4 measures leaf and aggregate quality separately, because an aggregate that
reconciles neatly can hide worse SeriesKey forecasts, and decision #78 forbids
presenting the easier number as the harder one.
"""

from __future__ import annotations

from typing import Any, Final, Sequence

import numpy as np
import pandas as pd

from retail_ml.models.bias_correction import (
    MAX_FACTOR,
    MIN_FACTOR,
    CandidateError,
    OriginRoles,
)

C3_ID: Final[str] = "C3"
C4_ID: Final[str] = "C4"

#: Frozen before scoring: a segment needs all three to earn its own adjustment.
MIN_SEGMENT_ROWS: Final[int] = 500
MIN_SEGMENT_SERIES: Final[int] = 25
MIN_SEGMENT_ORIGINS: Final[int] = 8

#: PP3-B3 ranked these material by error mass; routing and pooling were rejected.
C3_SEGMENT_COLUMNS: Final[tuple[str, ...]] = ("market_id", "category")

#: Hierarchy levels, leaf first.
HIERARCHY: Final[tuple[tuple[str, ...], ...]] = (
    ("sku_id", "store_id", "channel_id"),
    ("market_id", "category"),
    ("market_id",),
)

RECONCILIATION_METHODS: Final[tuple[str, ...]] = (
    "bottom_up",
    "top_down",
    "proportional_reconciled",
)


def _wape(frame: pd.DataFrame, column: str) -> float | None:
    actual = float(pd.to_numeric(frame["actual_units"], errors="coerce").sum())
    if actual <= 0:
        return None
    error = float(
        (
            pd.to_numeric(frame[column], errors="coerce")
            - pd.to_numeric(frame["actual_units"], errors="coerce")
        )
        .abs()
        .sum()
    )
    return error / actual


def _segment_sufficient(group: pd.DataFrame) -> bool:
    series = group[["sku_id", "store_id", "channel_id"]].drop_duplicates()
    return (
        len(group) >= MIN_SEGMENT_ROWS
        and len(series) >= MIN_SEGMENT_SERIES
        and group["forecast_origin"].nunique() >= MIN_SEGMENT_ORIGINS
    )


def fit_segmented_champions(
    frame: pd.DataFrame,
    roles: OriginRoles,
    *,
    segment_columns: Sequence[str] = C3_SEGMENT_COLUMNS,
) -> dict[str, Any]:
    """Learn per-segment adjustments from development origins only.

    A segment that cannot meet the frozen sufficiency rule shrinks to its parent
    rather than receiving a bespoke factor. Freezing the rule before scoring is
    what stops a weak segment from being handed its own overfit model because its
    displayed accuracy looked bad.
    """

    fit_rows = frame[frame["forecast_origin"].isin(roles.development)]
    leaked = sorted(set(fit_rows["forecast_origin"].unique()) & set(roles.confirmation))
    if leaked:
        raise CandidateError(f"C3 fit population includes confirmation origins: {leaked}")
    if fit_rows.empty:
        raise CandidateError("no development rows available to fit C3")

    def _factor(group: pd.DataFrame) -> float | None:
        predicted = float(pd.to_numeric(group["yhat_p50"], errors="coerce").sum())
        actual = float(pd.to_numeric(group["actual_units"], errors="coerce").sum())
        if predicted <= 0 or actual <= 0:
            return None
        return actual / predicted

    parent = _factor(fit_rows)
    if parent is None:
        raise CandidateError("development rows carry no usable volume")

    segments: dict[str, Any] = {}
    shrunk = 0
    for key, group in fit_rows.groupby(list(segment_columns), sort=True, observed=True):
        own = _factor(group)
        sufficient = own is not None and _segment_sufficient(group)
        if not sufficient:
            shrunk += 1
        factor = own if sufficient else parent
        series = group[["sku_id", "store_id", "channel_id"]].drop_duplicates()
        segments["|".join(str(part) for part in key)] = {
            "factor": float(np.clip(factor, MIN_FACTOR, MAX_FACTOR)),
            "rows": len(group),
            "seriesKeys": len(series),
            "origins": int(group["forecast_origin"].nunique()),
            "sufficient": bool(sufficient),
            "shrunkToParent": not sufficient,
        }
    return {
        "candidateId": C3_ID,
        "segmentColumns": list(segment_columns),
        "parentFactor": float(np.clip(parent, MIN_FACTOR, MAX_FACTOR)),
        "segments": segments,
        "segmentsShrunkToParent": shrunk,
        "sufficiencyRule": {
            "minimumRows": MIN_SEGMENT_ROWS,
            "minimumSeriesKeys": MIN_SEGMENT_SERIES,
            "minimumOrigins": MIN_SEGMENT_ORIGINS,
            "frozenBeforeScoring": True,
        },
        "fitOrigins": [str(value) for value in roles.development],
        "scopedToCauses": ["H2_category_composition", "H4_cold_start"],
        "deliberatelyNotScopedTo": [
            "H3_intermittent_routing",
            "H8_model_pooling",
        ],
        "scopeRationale": (
            "PP3-B3 measured routing and pooling at 0.91% of recoverable error; "
            "segmenting them cannot satisfy decision #75's 5% floor."
        ),
    }


def apply_segmented_champions(
    frame: pd.DataFrame,
    model: dict[str, Any],
) -> pd.DataFrame:
    result = frame.copy()
    columns = list(model["segmentColumns"])
    keys = result[columns].astype(str).agg("|".join, axis=1)
    factors = keys.map(
        {name: segment["factor"] for name, segment in model["segments"].items()}
    ).fillna(model["parentFactor"])
    result["yhat_p50"] = (
        pd.to_numeric(result["yhat_p50"], errors="coerce") * factors
    ).clip(lower=0.0)
    result["yhat_p90"] = np.maximum(
        pd.to_numeric(result["yhat_p90"], errors="coerce"),
        result["yhat_p50"],
    )
    return result


# ---------------------------------------------------------------------------
# C4: hierarchical reconciliation.
# ---------------------------------------------------------------------------
def reconcile(
    frame: pd.DataFrame,
    *,
    method: str,
    column: str = "yhat_p50",
    share_column: str | None = None,
) -> pd.DataFrame:
    """Reconcile leaf forecasts against a parent level.

    `bottom_up` is the identity on leaves and is included as the honest control:
    it changes nothing, so any apparent gain from the other methods must beat it.
    """

    if method not in RECONCILIATION_METHODS:
        raise CandidateError(f"unknown reconciliation method {method!r}")
    result = frame.copy()
    values = pd.to_numeric(result[column], errors="coerce").clip(lower=0.0)
    result[column] = values

    if method == "bottom_up":
        return result

    parent = list(HIERARCHY[1])
    grouped = result.groupby(parent, sort=False, observed=True)[column].transform("sum")
    if method == "top_down":
        # A top-down split needs a disaggregation share that was knowable at the
        # forecast origin. Deriving it from `actual_units` -- the target -- is
        # textbook leakage: it scored +59.2% relative WAPE in a first draft here,
        # which is what leakage looks like, not what a real candidate looks like.
        if share_column is None:
            raise CandidateError(
                "top_down requires an origin-safe share_column; deriving the "
                "split from actual_units leaks the target"
            )
        if share_column not in result.columns:
            raise CandidateError(f"share column {share_column!r} is absent")
        share_values = pd.to_numeric(result[share_column], errors="coerce").clip(
            lower=0.0
        )
        share_total = result.assign(_s=share_values).groupby(
            parent, sort=False, observed=True
        )["_s"].transform("sum")
        share = np.where(share_total > 0, share_values / share_total, 0.0)
        result[column] = (grouped * share).clip(lower=0.0)
    else:
        # Proportional: scale leaves so they sum to the parent's own forecast,
        # which for a summed parent is the identity. Kept explicit so the test
        # can prove it, rather than implying a gain that is not there.
        scale = np.where(grouped > 0, grouped / grouped.replace(0, np.nan), 1.0)
        result[column] = (values * np.nan_to_num(scale, nan=1.0)).clip(lower=0.0)

    result["yhat_p90"] = np.maximum(
        pd.to_numeric(result["yhat_p90"], errors="coerce"),
        result[column],
    )
    return result


def leaf_and_aggregate_quality(
    frame: pd.DataFrame,
    *,
    column: str = "yhat_p50",
) -> dict[str, Any]:
    """Report leaf and aggregate WAPE separately, never interchangeably."""

    leaf = _wape(frame, column)
    levels: dict[str, Any] = {
        "leaf_serieskey": {"wape": leaf, "rows": int(len(frame))},
    }
    for label, columns in (("market_category", HIERARCHY[1]), ("market", HIERARCHY[2])):
        rolled = (
            frame.groupby([*columns, "forecast_origin", "horizon"], observed=True)
            .agg(actual_units=("actual_units", "sum"), rolled=(column, "sum"))
            .reset_index()
        )
        levels[label] = {
            "wape": _wape(rolled.rename(columns={"rolled": column}), column),
            "rows": int(len(rolled)),
        }
    return {
        "levels": levels,
        "rule": (
            "Aggregate WAPE is always easier than leaf WAPE because errors "
            "offset when summed. Decision #78 forbids presenting the aggregate "
            "as SeriesKey accuracy."
        ),
        "aggregateEasierThanLeaf": bool(
            levels["market"]["wape"] is not None
            and leaf is not None
            and levels["market"]["wape"] < leaf
        ),
    }


__all__ = [
    "C3_ID",
    "C4_ID",
    "C3_SEGMENT_COLUMNS",
    "HIERARCHY",
    "MIN_SEGMENT_ORIGINS",
    "MIN_SEGMENT_ROWS",
    "MIN_SEGMENT_SERIES",
    "RECONCILIATION_METHODS",
    "apply_segmented_champions",
    "fit_segmented_champions",
    "leaf_and_aggregate_quality",
    "reconcile",
]
