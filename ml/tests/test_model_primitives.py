from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from retail_ml.models import backtest
from retail_ml.models.backtest import (
    evaluate_acceptance,
    rolling_origin_schedule,
    slow_mover_diagnostics,
)
from retail_ml.models.baselines import additive_metrics, attach_baselines
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


def test_seasonal_naive_preserves_missing_lag_52() -> None:
    baselines = attach_baselines(
        pd.DataFrame(
            {
                "units_lag_1": [2.0, 3.0],
                "units_lag_52": [5.0, np.nan],
                "units_roll_mean_8": [2.0, 3.0],
                "units_roll_mean_13": [2.0, 3.0],
            }
        )
    )

    assert baselines["seasonal_naive_baseline"].iloc[0] == 5.0
    assert pd.isna(baselines["seasonal_naive_baseline"].iloc[1])


def test_acceptance_uses_identical_paired_rows_for_seasonal_comparison() -> None:
    frame = pd.DataFrame(
        [
            {
                "market_id": "market",
                "sku_id": "sku-1",
                "store_id": "store",
                "channel_id": "channel",
                "forecast_origin": date(2026, 1, 5),
                "actual_units": 10.0,
                "yhat_p50": 8.0,
                "yhat_p90": 12.0,
                "seasonal_naive_baseline": 5.0,
                "zero_share_52w": 0.1,
            },
            {
                "market_id": "market",
                "sku_id": "sku-2",
                "store_id": "store",
                "channel_id": "channel",
                "forecast_origin": date(2026, 1, 5),
                "actual_units": 10.0,
                "yhat_p50": 100.0,
                "yhat_p90": 101.0,
                "seasonal_naive_baseline": np.nan,
                "zero_share_52w": 0.1,
            },
        ]
    )

    result = evaluate_acceptance(frame)["global"]

    assert result["seasonalComparison"]["pairedRows"] == 1
    assert result["seasonalComparison"]["droppedUnpairedRows"] == 1
    assert result["seasonalComparison"]["pairedRowsIdentical"] is True
    assert result["seasonalComparison"]["comparisonComplete"] is False
    assert result["metrics"]["champion"]["wape"] == 4.6
    assert result["metrics"]["droppedChampion"]["wape"] == 9.0
    assert result["metrics"]["pairedChampion"]["n"] == 1
    assert result["metrics"]["seasonalNaive"]["n"] == 1
    assert result["gates"]["A1"]["relativeWapeImprovementPct"] == 60.0
    assert result["gates"]["A1"]["passed"] is False


def _passing_acceptance_frame() -> pd.DataFrame:
    rows = []
    first = date(2025, 8, 4)
    for market in ("india-west", "us-new-york"):
        for origin_index in range(13):
            origin = first + timedelta(weeks=2 * origin_index)
            for series in range(100):
                rows.append(
                    {
                        "market_id": market,
                        "sku_id": f"sku-{series}",
                        "store_id": f"{market}:store",
                        "channel_id": f"{market}:channel",
                        "forecast_origin": origin,
                        "actual_units": 10.0,
                        "yhat_p50": 9.0,
                        "yhat_p90": 10.0 if series < 90 else 9.5,
                        "seasonal_naive_baseline": 5.0,
                        "zero_share_52w": 0.7,
                    }
                )
    return pd.DataFrame(rows)


def _disable_bootstrap(monkeypatch: object) -> None:
    monkeypatch.setattr(backtest, "_clustered_interval", lambda frame: (-0.5, -0.1))


def test_all_acceptance_gates_accept_a_legitimate_run(monkeypatch) -> None:
    _disable_bootstrap(monkeypatch)
    result = evaluate_acceptance(_passing_acceptance_frame())

    assert result["passed"] is True
    assert result["global"]["gates"]["A1"]["passed"] is True
    assert result["global"]["gates"]["A2"]["passed"] is True
    assert result["global"]["gates"]["A3"]["passed"] is True
    assert result["global"]["gates"]["A4"]["passed"] is True
    assert result["A5"]["passed"] is True


def test_a1_enforces_threshold_and_complete_pairing(monkeypatch) -> None:
    _disable_bootstrap(monkeypatch)
    below_threshold = _passing_acceptance_frame()
    below_threshold["yhat_p50"] = 6.0
    below_threshold["yhat_p90"] = 10.0
    result = evaluate_acceptance(below_threshold)
    assert result["global"]["gates"]["A1"]["relativeWapeImprovementPct"] == pytest.approx(
        20.0
    )
    assert result["global"]["gates"]["A1"]["passed"] is False

    incomplete = _passing_acceptance_frame()
    incomplete.loc[incomplete.index[0], "seasonal_naive_baseline"] = np.nan
    result = evaluate_acceptance(incomplete)
    assert result["global"]["seasonalComparison"]["droppedUnpairedRows"] == 1
    assert result["global"]["gates"]["A1"]["comparisonComplete"] is False
    assert result["global"]["gates"]["A1"]["passed"] is False


def test_a2_enforces_both_coverage_bounds(monkeypatch) -> None:
    _disable_bootstrap(monkeypatch)
    below = _passing_acceptance_frame()
    below["yhat_p90"] = 9.5
    assert evaluate_acceptance(below)["global"]["gates"]["A2"]["passed"] is False

    above = _passing_acceptance_frame()
    above["yhat_p90"] = 10.5
    assert evaluate_acceptance(above)["global"]["gates"]["A2"]["passed"] is False


def test_a3_enforces_series_origin_pairing_and_point_gate(monkeypatch) -> None:
    _disable_bootstrap(monkeypatch)
    passing_market = _passing_acceptance_frame().query(
        "market_id == 'india-west'"
    )
    assert slow_mover_diagnostics(passing_market)["passed"] is True

    too_few_series = passing_market.query("sku_id != 'sku-99'")
    assert slow_mover_diagnostics(too_few_series)["verdict"] == "insufficient_evidence"

    too_few_origins = passing_market[
        passing_market["forecast_origin"]
        != passing_market["forecast_origin"].max()
    ]
    assert slow_mover_diagnostics(too_few_origins)["verdict"] == "insufficient_evidence"

    too_few_at_one_origin = passing_market[
        ~(
            passing_market["forecast_origin"].eq(
                passing_market["forecast_origin"].max()
            )
            & pd.to_numeric(
                passing_market["sku_id"].str.removeprefix("sku-")
            ).ge(49)
        )
    ]
    assert (
        slow_mover_diagnostics(too_few_at_one_origin)["verdict"]
        == "insufficient_evidence"
    )

    worse = passing_market.copy()
    worse["yhat_p50"] = 4.0
    worse["yhat_p90"] = 10.0
    assert slow_mover_diagnostics(worse)["verdict"] == "fail"


def test_a4_and_a5_fail_on_monotonicity_and_supported_market(
    monkeypatch,
) -> None:
    _disable_bootstrap(monkeypatch)
    non_monotonic = _passing_acceptance_frame()
    non_monotonic.loc[non_monotonic.index[0], "yhat_p90"] = 8.0
    result = evaluate_acceptance(non_monotonic)
    assert result["global"]["gates"]["A4"]["passed"] is False
    assert result["passed"] is False

    market_failure = _passing_acceptance_frame()
    market_failure.loc[
        market_failure["market_id"].eq("us-new-york"),
        "yhat_p50",
    ] = 4.0
    market_failure.loc[
        market_failure["market_id"].eq("us-new-york"),
        "yhat_p90",
    ] = 10.0
    result = evaluate_acceptance(market_failure)
    assert result["A5"]["passed"] is False
    assert "us-new-york" in result["A5"]["failedMarkets"]


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
    assert routed.iloc[0]["confidence"] == forecast_confidence(
        routed["yhat_p50"],
        routed["yhat_p90"],
    )[0]


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
