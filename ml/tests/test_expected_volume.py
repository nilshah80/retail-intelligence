import numpy as np
import pandas as pd
import pytest

from retail_ml.models.expected_volume import (
    COLD_FALLBACK_MODEL,
    COLD_MODEL,
    ESTABLISHED_MODEL,
    attach_expected_volume,
)


def test_expected_volume_preserves_quantiles_and_segments_the_centre() -> None:
    frame = pd.DataFrame(
        {
            "cohort": ["established_history", "cold_start", "evaluation_ineligible"],
            "ma13_baseline": [11.0, 2.0, 0.0],
            "lightgbm_cold_expected": [np.nan, 8.0, 5.0],
            "yhat_p50": [10.0, 3.0, 1.0],
            "yhat_p90": [15.0, 12.0, 7.0],
        }
    )

    result = attach_expected_volume(frame)

    assert result["expected_units"].tolist() == [11.0, 8.0, 5.0]
    assert result["expected_model"].tolist() == [
        ESTABLISHED_MODEL,
        COLD_MODEL,
        COLD_MODEL,
    ]
    assert result["expected_cold_head_fallback"].tolist() == [False, False, False]
    assert result["yhat_p50"].equals(frame["yhat_p50"])
    assert result["yhat_p90"].equals(frame["yhat_p90"])


def test_expected_volume_records_cold_head_fallback() -> None:
    result = attach_expected_volume(
        pd.DataFrame(
            {
                "cohort": ["cold_start"],
                "ma13_baseline": [4.0],
                "lightgbm_cold_expected": [np.nan],
            }
        )
    )

    assert result.loc[0, "expected_units"] == 4.0
    assert result.loc[0, "expected_model"] == COLD_FALLBACK_MODEL
    assert bool(result.loc[0, "expected_cold_head_fallback"])


def test_expected_volume_rejects_unknown_cohort() -> None:
    with pytest.raises(ValueError, match="unknown cohorts"):
        attach_expected_volume(
            pd.DataFrame(
                {
                    "cohort": ["mystery"],
                    "ma13_baseline": [1.0],
                    "lightgbm_cold_expected": [1.0],
                }
            )
        )
