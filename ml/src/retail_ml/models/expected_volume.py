"""Decision #95 additive expected-volume forecast.

P50/P90 are quantiles and stay quantiles. This module attaches the separately named
planning expectation after cohorts and baselines are available, so an additive
consumer never has to reinterpret a median.
"""

from __future__ import annotations

from typing import Final

import numpy as np
import pandas as pd

from retail_ml.models.cohorts import COLD_START, ESTABLISHED, INELIGIBLE

EXPECTED_COLUMN: Final[str] = "expected_units"
EXPECTED_MODEL_COLUMN: Final[str] = "expected_model"
FALLBACK_COLUMN: Final[str] = "expected_cold_head_fallback"
POLICY_ID: Final[str] = "retail-forecast-expected-volume/v1"
DECISION_IDS: Final[tuple[int, ...]] = (95,)

ESTABLISHED_MODEL: Final[str] = "ma13_established_expectation"
COLD_MODEL: Final[str] = "lightgbm_cold_conditional_mean"
COLD_FALLBACK_MODEL: Final[str] = "ma13_cold_head_unavailable"


def attach_expected_volume(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the additive planning forecast without mutating P50 or P90."""

    required = {
        "cohort",
        "ma13_baseline",
        "lightgbm_cold_expected",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(
            "expected-volume input is missing: " + ", ".join(missing)
        )

    result = frame.copy()
    cohort = result["cohort"].astype(str)
    unknown = sorted(set(cohort.unique()) - {ESTABLISHED, COLD_START, INELIGIBLE})
    if unknown:
        raise ValueError(f"expected-volume input has unknown cohorts: {unknown}")

    ma13 = pd.to_numeric(result["ma13_baseline"], errors="coerce")
    cold_mean = pd.to_numeric(result["lightgbm_cold_expected"], errors="coerce")
    if ma13.isna().any() or not np.isfinite(ma13).all():
        raise ValueError("expected-volume MA13 basis must be finite")

    cold_like = cohort.isin({COLD_START, INELIGIBLE})
    cold_available = cold_mean.notna() & np.isfinite(cold_mean)
    expected = ma13.copy()
    expected.loc[cold_like & cold_available] = cold_mean.loc[
        cold_like & cold_available
    ]
    expected = expected.clip(lower=0.0)

    result[EXPECTED_COLUMN] = expected
    result[EXPECTED_MODEL_COLUMN] = ESTABLISHED_MODEL
    result.loc[cold_like & cold_available, EXPECTED_MODEL_COLUMN] = COLD_MODEL
    result.loc[cold_like & ~cold_available, EXPECTED_MODEL_COLUMN] = (
        COLD_FALLBACK_MODEL
    )
    # Recompute rather than trust a training-stage marker: the row-level audit must
    # agree with the value that was actually selected.
    result[FALLBACK_COLUMN] = cold_like & ~cold_available

    if result[EXPECTED_COLUMN].isna().any() or not np.isfinite(
        result[EXPECTED_COLUMN]
    ).all():
        raise ValueError("expected-volume forecast must be finite")
    if (result[EXPECTED_COLUMN] < 0).any():
        raise ValueError("expected-volume forecast must be non-negative")
    return result


def policy_identity() -> dict[str, object]:
    return {
        "policyId": POLICY_ID,
        "decisionIds": list(DECISION_IDS),
        "expectedColumn": EXPECTED_COLUMN,
        "establishedModel": ESTABLISHED_MODEL,
        "coldStartModel": COLD_MODEL,
        "coldStartMinimumTrainingRows": 2_000,
        "fallbackModel": COLD_FALLBACK_MODEL,
        "p50SemanticsUnchanged": True,
    }


__all__ = [
    "COLD_FALLBACK_MODEL",
    "COLD_MODEL",
    "DECISION_IDS",
    "ESTABLISHED_MODEL",
    "EXPECTED_COLUMN",
    "EXPECTED_MODEL_COLUMN",
    "FALLBACK_COLUMN",
    "POLICY_ID",
    "attach_expected_volume",
    "policy_identity",
]
