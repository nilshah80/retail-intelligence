"""Decision-#82 established-history and cold-start evaluation cohorts.

A forecast row belongs to exactly one cohort at
``forecast_origin x horizon x SeriesKey`` grain:

``established_history``
    its origin-visible lag-52 seasonal-naive input exists, so spec section 4.3's
    unchanged >= 25% seasonal-naive gate applies;
``cold_start``
    no lag-52 input exists, so the comparator is the arithmetic mean of the last
    ``min(13, history_weeks)`` complete origin-visible weekly actuals available
    at the forecast origin.

A row may never disappear from both cohorts, and a cold-start row with no prior
complete week is ``insufficient_evidence`` rather than a pass.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

import numpy as np
import pandas as pd

COHORT_RECOMPUTATION_VERSION: Final[str] = (
    "cohorted-seasonal-cold-start-recomputation/v4"
)
COLD_START_BASELINE_COLUMN: Final[str] = "cold_start_baseline"
COLD_START_HISTORY_COLUMN: Final[str] = "cold_start_history_weeks"
PARTIAL_WEEK_COLUMN: Final[str] = "cold_start_partial_week"
COLD_START_MAX_WEEKS: Final[int] = 13
SERIES_KEY_COLUMNS: Final[tuple[str, ...]] = ("sku_id", "store_id", "channel_id")
COHORT_KEY_COLUMNS: Final[tuple[str, ...]] = (
    "forecast_origin",
    "horizon",
    "sku_id",
    "store_id",
    "channel_id",
)

ESTABLISHED = "established_history"
COLD_START = "cold_start"

REASON_ESTABLISHED: Final[str] = "ORIGIN_VISIBLE_LAG52_AVAILABLE"
REASON_COLD_START: Final[str] = "LAG52_UNAVAILABLE_SHORT_HISTORY"
REASON_COLD_START_NO_HISTORY: Final[str] = "COLD_START_NO_PRIOR_OBSERVED_WEEK"
REASON_COLD_START_PARTIAL: Final[str] = "COLD_START_PARTIAL_LAUNCH_WEEK"

#: Decision #83 residue: a SeriesKey with no prior observation of any kind at its
#: first origin has no defensible comparator, so no skill claim is possible about
#: it either. Such rows are evaluation-ineligible with a published count, rather
#: than blocking acceptance forever. The cap is set from principle, not from the
#: observed residue: above 1% of rows this stops being a launch-week edge case
#: and indicates a systemic evidence problem that must fail closed.
MAX_INELIGIBLE_ROW_SHARE: Final[float] = 0.01
INELIGIBLE = "evaluation_ineligible"
REASON_NO_PRIOR_OBSERVATION: Final[str] = "NO_PRIOR_OBSERVATION_AT_FIRST_ORIGIN"


class CohortError(RuntimeError):
    """The cohort partition is not total or not reproducible."""


def _finite(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame.get(column), errors="coerce")
    if values is None:
        return pd.Series(False, index=frame.index)
    return values.notna() & np.isfinite(values)


def cold_start_comparator(
    history: pd.DataFrame,
    partial_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return one comparator row per SeriesKey from prior origin-visible weeks.

    ``history`` carries the complete (``training_eligible``) origin-visible
    weekly actuals strictly before one forecast origin, as produced for the
    intermittent-routing history. Weeks are ordered by ``forecast_origin`` and
    only the most recent ``min(13, history_weeks)`` contribute.

    Decision #83: when a SeriesKey has **no** complete prior week, its most
    recent *partial* origin-visible week is admitted at exposure-normalised
    ``weekly_units_equivalent``. Without this, a series' launch week leaves the
    cold-start gate permanently ``insufficient_evidence``, which made acceptance
    structurally unreachable for any rolling-origin panel. The value is real
    observed demand, never a fabricated one, and complete weeks always win.
    """

    keys = list(SERIES_KEY_COLUMNS)
    columns = [*keys, COLD_START_BASELINE_COLUMN, COLD_START_HISTORY_COLUMN]
    if history is None or history.empty:
        return pd.DataFrame(columns=columns)
    missing = sorted({*keys, "forecast_origin", "origin_units"} - set(history.columns))
    if missing:
        raise CohortError(f"cold-start history is missing: {', '.join(missing)}")
    usable = history.loc[_finite(history, "origin_units")].copy()
    if usable.empty:
        return pd.DataFrame(columns=columns)
    ordered = usable.sort_values([*keys, "forecast_origin"], kind="mergesort")
    recent = ordered.groupby(keys, sort=False, observed=True).tail(COLD_START_MAX_WEEKS)
    grouped = recent.groupby(keys, sort=True, observed=True)["origin_units"]
    result = grouped.agg(["mean", "size"]).reset_index()
    result.columns = [*keys, COLD_START_BASELINE_COLUMN, COLD_START_HISTORY_COLUMN]

    if partial_history is not None and not partial_history.empty:
        result = _admit_partial_launch_weeks(result, partial_history, keys)
    result[COLD_START_BASELINE_COLUMN] = pd.to_numeric(
        result[COLD_START_BASELINE_COLUMN],
        errors="coerce",
    ).clip(lower=0.0)
    result[COLD_START_HISTORY_COLUMN] = result[COLD_START_HISTORY_COLUMN].astype(int)
    return result[columns]



def _admit_partial_launch_weeks(
    complete: pd.DataFrame,
    partial_history: pd.DataFrame,
    keys: list[str],
) -> pd.DataFrame:
    """Decision #83 fallback for SeriesKeys with no complete prior week."""

    missing = sorted({"origin_units", "forecast_origin"} - set(partial_history.columns))
    if missing:
        raise CohortError(f"partial history is missing: {', '.join(missing)}")
    usable = partial_history.loc[_finite(partial_history, "origin_units")]
    if usable.empty:
        return complete
    ordered = usable.sort_values([*keys, "forecast_origin"], kind="mergesort")
    latest = ordered.groupby(keys, sort=True, observed=True).tail(1)
    fallback = latest[[*keys, "origin_units"]].rename(
        columns={"origin_units": COLD_START_BASELINE_COLUMN}
    )
    fallback[COLD_START_HISTORY_COLUMN] = 1
    fallback[PARTIAL_WEEK_COLUMN] = True

    covered = set(
        complete[keys].astype(str).agg("|".join, axis=1)
    ) if not complete.empty else set()
    fallback_keys = fallback[keys].astype(str).agg("|".join, axis=1)
    admitted = fallback.loc[~fallback_keys.isin(covered)].copy()
    if admitted.empty:
        return complete
    if not complete.empty:
        complete = complete.copy()
        complete[PARTIAL_WEEK_COLUMN] = False
        return pd.concat([complete, admitted], ignore_index=True)
    return admitted


def attach_cold_start_baseline(
    frame: pd.DataFrame,
    history: pd.DataFrame,
    partial_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Attach the decision-#82/#83 cold-start comparator to one origin's rows."""

    comparator = cold_start_comparator(history, partial_history)
    result = frame.copy()
    if comparator.empty:
        result[COLD_START_BASELINE_COLUMN] = np.nan
        result[COLD_START_HISTORY_COLUMN] = 0
        return result
    merged = result.merge(comparator, on=list(SERIES_KEY_COLUMNS), how="left")
    merged[COLD_START_HISTORY_COLUMN] = (
        pd.to_numeric(merged[COLD_START_HISTORY_COLUMN], errors="coerce")
        .fillna(0)
        .astype(int)
    )
    return merged


def assign_cohorts(frame: pd.DataFrame) -> pd.DataFrame:
    """Return ``frame`` with a total decision-#82 cohort and reason code."""

    if COLD_START_BASELINE_COLUMN not in frame.columns:
        raise CohortError(
            "acceptance frame is missing the decision-#82 cold-start comparator"
        )
    result = frame.copy()
    established = _finite(result, "seasonal_naive_baseline")
    comparator_present = _finite(result, COLD_START_BASELINE_COLUMN)
    ineligible = ~established & ~comparator_present
    result["cohort"] = np.where(
        established,
        ESTABLISHED,
        np.where(ineligible, INELIGIBLE, COLD_START),
    )
    result["cohort_reason_code"] = np.where(
        established,
        REASON_ESTABLISHED,
        np.where(ineligible, REASON_NO_PRIOR_OBSERVATION, REASON_COLD_START),
    )
    unassigned = int(
        (~result["cohort"].isin([ESTABLISHED, COLD_START, INELIGIBLE])).sum()
    )
    if unassigned:
        raise CohortError(f"{unassigned} rows belong to no decision-#82 cohort")

    # The ineligible class is explicit, counted and capped -- never silent.
    share = float(ineligible.sum()) / float(len(result)) if len(result) else 0.0
    if share > MAX_INELIGIBLE_ROW_SHARE:
        raise CohortError(
            f"{share:.4%} of rows have no prior observation, above the "
            f"{MAX_INELIGIBLE_ROW_SHARE:.0%} cap; this is a systemic evidence "
            "problem rather than a launch-week edge and must fail closed"
        )
    return result


ACCEPTANCE_BASELINES: Final[dict[str, str]] = {
    "seasonal_naive": "seasonal_naive_baseline",
    "cold_start_mean": COLD_START_BASELINE_COLUMN,
}


def acceptance_frame(
    evaluation: pd.DataFrame,
    baselines: pd.DataFrame,
    key_columns: tuple[str, ...],
) -> pd.DataFrame:
    """Rebuild the decision-#82 acceptance frame from published artifacts.

    Publication and verification both call this so the recomputed gates cannot
    depend on anything outside the immutable bundle.
    """

    keys = list(key_columns)
    result = evaluation
    for baseline_id, column in sorted(ACCEPTANCE_BASELINES.items()):
        rows = baselines[baselines["baseline_id"].astype(str).eq(baseline_id)][
            [*keys, "prediction"]
        ].rename(columns={"prediction": column})
        if len(rows) != len(evaluation) or rows.duplicated(keys).any():
            raise CohortError(
                f"{baseline_id} artifact does not pair one-to-one with "
                "evaluation rows"
            )
        result = result.merge(rows, on=keys, how="left", validate="one_to_one")
    return result


def key_fingerprint(frame: pd.DataFrame, key_columns: list[str]) -> str:
    """Return the canonical sorted row-key SHA-256 for a cohort population."""

    present = [column for column in key_columns if column in frame.columns]
    rows = [
        [str(value) for value in row]
        for row in frame[present]
        .sort_values(present, kind="mergesort")
        .itertuples(index=False, name=None)
    ]
    return hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def cohort_population(
    frame: pd.DataFrame,
    *,
    total_rows: int,
    total_actual: float,
) -> dict[str, Any]:
    """Return reason-coded population evidence for one cohort."""

    key_columns = [
        column for column in COHORT_KEY_COLUMNS if column in frame.columns
    ]
    series = (
        frame[list(SERIES_KEY_COLUMNS)].drop_duplicates()
        if not frame.empty
        else frame[list(SERIES_KEY_COLUMNS)]
    )
    actual = float(pd.to_numeric(frame.get("actual_units"), errors="coerce").sum())
    reasons = (
        frame["cohort_reason_code"].value_counts().sort_index().to_dict()
        if "cohort_reason_code" in frame.columns and not frame.empty
        else {}
    )
    return {
        "rows": len(frame),
        "seriesKeys": len(series),
        "actualSum": actual,
        "rowShare": len(frame) / total_rows if total_rows else 0.0,
        "actualShare": actual / total_actual if total_actual > 0 else 0.0,
        "reasonCodes": {str(key): int(value) for key, value in reasons.items()},
        "keyColumns": key_columns,
        "keySha256": key_fingerprint(frame, key_columns),
    }


__all__ = [
    "ACCEPTANCE_BASELINES",
    "COHORT_KEY_COLUMNS",
    "COHORT_RECOMPUTATION_VERSION",
    "COLD_START",
    "COLD_START_BASELINE_COLUMN",
    "COLD_START_HISTORY_COLUMN",
    "COLD_START_MAX_WEEKS",
    "PARTIAL_WEEK_COLUMN",
    "ESTABLISHED",
    "INELIGIBLE",
    "MAX_INELIGIBLE_ROW_SHARE",
    "REASON_COLD_START",
    "REASON_COLD_START_NO_HISTORY",
    "REASON_COLD_START_PARTIAL",
    "REASON_ESTABLISHED",
    "REASON_NO_PRIOR_OBSERVATION",
    "SERIES_KEY_COLUMNS",
    "CohortError",
    "acceptance_frame",
    "assign_cohorts",
    "attach_cold_start_baseline",
    "cohort_population",
    "cold_start_comparator",
    "key_fingerprint",
]
