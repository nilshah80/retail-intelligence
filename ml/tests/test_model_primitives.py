from datetime import date, timedelta

import numpy as np
import pandas as pd

from retail_ml.models.backtest import rolling_origin_schedule
from retail_ml.models.baselines import additive_metrics
from retail_ml.models.confidence import aggregate_confidence, forecast_confidence
from retail_ml.models.intermittent import (
    croston_sba,
    route_intermittent_forecasts,
)
from retail_ml.models.train_lgbm import _tail_replay_preferred_keys


def test_fixed_schedule_has_13_step_two_origins_in_26_week_window() -> None:
    start = date(2026, 1, 5)
    origins = [start + timedelta(weeks=index) for index in range(40)]
    selected = rolling_origin_schedule(origins)

    assert len(selected) == 13
    assert selected[-1] == origins[-1]
    assert all((right - left).days == 14 for left, right in zip(selected, selected[1:]))


def test_additive_components_sum_before_division() -> None:
    left = additive_metrics(pd.Series([10]), pd.Series([8]), upper=pd.Series([12]))
    right = additive_metrics(pd.Series([90]), pd.Series([99]), upper=pd.Series([85]))
    combined = left.plus(right)

    assert combined.abs_error_sum == 11
    assert combined.actual_sum == 100
    assert combined.wape == 0.11
    assert combined.coverage == 0.5


def test_confidence_handles_zero_p50_and_aggregates_with_forecast_weights() -> None:
    confidence = forecast_confidence(np.array([0.0, 10.0]), np.array([1.0, 12.0]))

    assert confidence.tolist() == [0.5, 0.8333]
    assert aggregate_confidence(confidence, np.array([0.0, 10.0])) == 0.803


def test_croston_sba_is_nonnegative() -> None:
    assert croston_sba([0, 0, 4, 0, 0, 5, 0]) >= 0


def test_held_out_replay_can_route_at_the_first_formal_origin() -> None:
    origins = [date(2023, 1, 2) + timedelta(weeks=index) for index in range(120)]
    history = pd.DataFrame(
        {
            "sku_id": "sku",
            "store_id": "store",
            "channel_id": "channel",
            "forecast_origin": origins,
            "origin_units": [
                2.0 if index % 7 == 0 else 0.0
                for index in range(len(origins))
            ],
        }
    )
    scored = pd.DataFrame(
        [
            {
                "sku_id": "sku",
                "store_id": "store",
                "channel_id": "channel",
                "zero_share_52w": 0.8,
                "yhat_p50": 5.0,
                "yhat_p90": 7.0,
                "tail_replay_preferred": True,
            }
        ]
    )

    routed = route_intermittent_forecasts(scored, history)

    assert routed.iloc[0]["selected_model"] == "croston_sba_replay_selected"
    assert bool(routed.iloc[0]["tail_candidate_selected"]) is True


def test_tail_replay_learns_before_series_crosses_slow_mover_threshold() -> None:
    origins = pd.to_datetime(
        [date(2023, 1, 2) + timedelta(weeks=index) for index in range(10)]
    )
    frame = pd.DataFrame(
        {
            "sku_id": "sku",
            "store_id": "store",
            "channel_id": "channel",
            "forecast_origin": origins,
            "origin_units": 2.0,
        }
    )
    calibration = pd.DataFrame(
        {
            "sku_id": "sku",
            "store_id": "store",
            "channel_id": "channel",
            "forecast_origin": origins[-8:],
            "target_units": 2.0,
            "units_lag_52": 0.0,
            # The series was not slow during calibration; eligibility is
            # determined later from the scored origin's zero_share_52w.
            "zero_share_52w": 0.0,
        }
    )

    preferred = _tail_replay_preferred_keys(
        frame,
        calibration,
        np.repeat(10.0, len(calibration)),
    )

    assert len(preferred) == 1
