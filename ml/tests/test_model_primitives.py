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


def test_decision_82_splits_cohorts_and_gates_them_separately() -> None:
    frame = pd.DataFrame(
        [
            {
                "market_id": "market",
                "sku_id": "sku-1",
                "store_id": "store",
                "channel_id": "channel",
                "forecast_origin": date(2026, 1, 5),
                "horizon": 1,
                "actual_units": 10.0,
                "yhat_p50": 8.0,
                "yhat_p90": 12.0,
                "seasonal_naive_baseline": 5.0,
                "cold_start_baseline": 5.0,
                "zero_share_52w": 0.1,
            },
            {
                "market_id": "market",
                "sku_id": "sku-2",
                "store_id": "store",
                "channel_id": "channel",
                "forecast_origin": date(2026, 1, 5),
                "horizon": 1,
                "actual_units": 10.0,
                "yhat_p50": 100.0,
                "yhat_p90": 101.0,
                "seasonal_naive_baseline": np.nan,
                "cold_start_baseline": 12.0,
                "zero_share_52w": 0.1,
            },
        ]
    )

    result = evaluate_acceptance(frame)["global"]
    cohorts = result["cohorts"]
    established = result["gates"]["A1_established"]
    cold_start = result["gates"]["A1_cold_start"]

    assert cohorts["eligibleRows"] == 2
    assert cohorts["unassignedRows"] == 0
    assert cohorts["establishedHistory"]["rows"] == 1
    assert cohorts["coldStart"]["rows"] == 1
    assert cohorts["establishedHistory"]["reasonCodes"] == {
        "ORIGIN_VISIBLE_LAG52_AVAILABLE": 1
    }
    assert cohorts["coldStart"]["reasonCodes"] == {
        "LAG52_UNAVAILABLE_SHORT_HISTORY": 1
    }

    # The established cohort now pairs completely, so decision #81's
    # completeness rule is satisfied inside the cohort and A1 passes there.
    assert established["comparisonComplete"] is True
    assert established["relativeWapeImprovementPct"] == 60.0
    assert established["passed"] is True

    # The cold-start row is compared with its own mean-history comparator and
    # loses, so the run is still unacceptable.
    assert cold_start["comparisonComplete"] is True
    assert cold_start["championWape"] == 9.0
    assert cold_start["comparatorWape"] == 0.2
    assert cold_start["verdict"] == "fail"
    assert cold_start["passed"] is False


def test_a_row_with_no_prior_observation_is_evaluation_ineligible() -> None:
    """Decision #83: no observation means no comparator and no skill claim.

    Such a row is reason-coded and counted rather than blocking acceptance
    forever, which is what decision #82 alone did.
    """

    rows = []
    for index in range(200):
        rows.append(
            {
                "market_id": "market",
                "sku_id": f"sku-{index}",
                "store_id": "store",
                "channel_id": "channel",
                "forecast_origin": date(2026, 1, 5),
                "horizon": 1,
                "actual_units": 10.0,
                "yhat_p50": 9.0,
                "yhat_p90": 12.0,
                "seasonal_naive_baseline": 5.0,
                "cold_start_baseline": 5.0,
                "zero_share_52w": 0.1,
            }
        )
    # One launch row with no observation of any kind.
    rows.append(
        {
            "market_id": "market",
            "sku_id": "sku-launch",
            "store_id": "store",
            "channel_id": "channel",
            "forecast_origin": date(2026, 1, 5),
            "horizon": 1,
            "actual_units": 10.0,
            "yhat_p50": 9.0,
            "yhat_p90": 12.0,
            "seasonal_naive_baseline": np.nan,
            "cold_start_baseline": np.nan,
            "zero_share_52w": 0.1,
        }
    )
    result = evaluate_acceptance(pd.DataFrame(rows))
    cohorts = result["global"]["cohorts"]

    assert cohorts["evaluationIneligible"]["rows"] == 1
    assert cohorts["evaluationIneligible"]["reasonCodes"] == {
        "NO_PRIOR_OBSERVATION_AT_FIRST_ORIGIN": 1
    }
    assert cohorts["unassignedRows"] == 0
    assert cohorts["scoredRows"] == 200
    # It no longer makes the cold-start gate insufficient.
    assert result["global"]["gates"]["A1_cold_start"]["verdict"] == "not_applicable"
    assert cohorts["ineligibleRowSharePct"] < cohorts["maximumIneligibleRowSharePct"]


def test_a_systemic_lack_of_observation_fails_closed() -> None:
    """The ineligible class is capped, so it cannot become an escape hatch."""

    frame = pd.DataFrame(
        [
            {
                "market_id": "market",
                "sku_id": f"sku-{index}",
                "store_id": "store",
                "channel_id": "channel",
                "forecast_origin": date(2026, 1, 5),
                "horizon": 1,
                "actual_units": 10.0,
                "yhat_p50": 9.0,
                "yhat_p90": 12.0,
                "seasonal_naive_baseline": np.nan,
                "cold_start_baseline": np.nan,
                "zero_share_52w": 0.1,
            }
            for index in range(50)
        ]
    )
    with pytest.raises(Exception, match="systemic evidence problem"):
        evaluate_acceptance(frame)


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
                        "cold_start_baseline": 5.0,
                        "zero_share_52w": 0.7,
                    }
                )
    return pd.DataFrame(rows)


def _disable_bootstrap(monkeypatch: object) -> None:
    monkeypatch.setattr(
        backtest,
        "_clustered_interval",
        lambda frame, **kwargs: (-0.5, -0.1),
    )


def test_all_acceptance_gates_accept_a_legitimate_run(monkeypatch) -> None:
    _disable_bootstrap(monkeypatch)
    result = evaluate_acceptance(_passing_acceptance_frame())

    assert result["passed"] is True
    assert result["global"]["gates"]["A1_established"]["passed"] is True
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
    established = result["global"]["gates"]["A1_established"]
    assert established["relativeWapeImprovementPct"] == pytest.approx(20.0)
    assert established["passed"] is False

    # Losing lag-52 moves a row into the cold-start cohort rather than dropping
    # it, so the established cohort stays complete and the cold-start gate owns
    # the row.
    moved = _passing_acceptance_frame()
    moved.loc[moved.index[0], "seasonal_naive_baseline"] = np.nan
    result = evaluate_acceptance(moved)
    assert result["global"]["gates"]["A1_established"]["comparisonComplete"] is True
    assert result["global"]["cohorts"]["coldStart"]["rows"] == 1
    assert result["global"]["cohorts"]["unassignedRows"] == 0


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


def test_per_cohort_coverage_is_now_binding(monkeypatch) -> None:
    """Decision #85 became a hard gate; prove it can fail a run.

    While report-only it was excluded from the verdict by name. Making it binding is the
    Phase 4 entry dependency #85 set, because reorder point and safety stock derive from
    the quantile spread, so an under-covered P90 becomes an under-stocked order.
    """

    _disable_bootstrap(monkeypatch)
    frame = _passing_acceptance_frame()
    # Narrow P90 below the actual on most rows: whole-population A2 and the per-cohort
    # gate should both see the under-coverage.
    frame["yhat_p90"] = 9.2

    result = evaluate_acceptance(frame)

    assert result["passed"] is False
    gate = result["global"]["gates"]["A2_per_cohort"]
    assert gate["gateMode"] == "hard"
    assert gate["passed"] is False
    # Excluded-by-name is gone; nothing may sit outside the verdict silently.
    assert result["global"]["reportOnlyGates"] == []


def test_an_absent_cohort_does_not_block_but_an_unmeasurable_one_does(
    monkeypatch,
) -> None:
    """Two different things that both look like "no number".

    Decision #85 names the zero-actual and decision-#52 cases as
    `insufficient_evidence` and never a pass. It does not address a cohort with no rows,
    and treating that the same way would make the gate unsatisfiable for any population
    that legitimately has one cohort -- a retailer whose whole assortment is established
    would be permanently blocked by the absence of cold-start rows.
    """

    _disable_bootstrap(monkeypatch)
    result = evaluate_acceptance(_passing_acceptance_frame())
    cohorts = result["global"]["gates"]["A2_per_cohort"]["cohorts"]

    verdicts = {name: entry["verdict"] for name, entry in cohorts.items()}
    # The fixture carries no lag-52 history, so every row is cold_start and the
    # established cohort is absent rather than unmeasurable.
    assert "not_applicable" in verdicts.values()
    assert result["global"]["gates"]["A2_per_cohort"]["passed"] is True

    # An absent cohort must not be the ONLY thing the gate sees, or it would pass on no
    # evidence at all.
    empty = _passing_acceptance_frame().iloc[0:0]
    assert evaluate_acceptance(empty)["global"]["gates"]["A2_per_cohort"][
        "passed"
    ] is False
