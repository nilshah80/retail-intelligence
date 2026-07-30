from datetime import date, timedelta
from dataclasses import asdict

import numpy as np
import pandas as pd

from retail_ml.models.train_lgbm import fit_horizon_model, score_horizon_model
from retail_ml.models.drivers import LIVE_DRIVER_GROUPS


def _training_frame() -> pd.DataFrame:
    rows = []
    start = date(2025, 1, 6)
    for origin_index in range(12):
        origin = start + timedelta(weeks=origin_index)
        for series in range(100):
            market = "india-west" if series < 50 else "us-new-york"
            units = 8 + (series % 7) + (origin_index % 3)
            rows.append(
                {
                    "sku_id": f"sku-{series}",
                    "store_id": f"{market}:store",
                    "channel_id": f"{market}:store",
                    "market_id": market,
                    "dept_id": "dept",
                    "category": "category",
                    "sub_cat": "sub",
                    "forecast_origin": origin,
                    "horizon": 1,
                    "target_units": units,
                    "origin_units": units - 1,
                    "weekly_units_equivalent": units - 1,
                    "week_index": origin_index + 60,
                    "units_lag_1": units - 1,
                    "units_lag_4": units - 2,
                    "units_lag_13": units - 1,
                    "units_lag_52": units - 1,
                    "units_roll_mean_4": units - 1,
                    "units_roll_std_4": 1,
                    "units_roll_mean_8": units - 1,
                    "units_roll_std_8": 1,
                    "units_roll_mean_13": units - 1,
                    "units_roll_std_13": 1,
                    "units_roll_mean_52": units - 1,
                    "units_roll_std_52": 1,
                    "zero_share_52w": 0.1,
                    "demand_trend_4v13": 0,
                    "price_ratio_13w": 1,
                    "local_category_price_index": 1,
                    "iso_week": origin.isocalendar().week,
                    "week_sin": np.sin(origin_index),
                    "week_cos": np.cos(origin_index),
                    "event_count_origin": 0,
                    "working_days_origin": 5,
                    "event_count_horizon": 0,
                    "working_days_horizon": 5,
                    "weather_tavg_origin": 24,
                    "weather_precip_origin": 2,
                    "weather_tavg_horizon": 25,
                    "weather_precip_horizon": 2,
                    "weather_fallback_used": 0,
                    "macro_index_value": 100,
                    "competitor_price_ratio": 1,
                    "competitor_available": 1,
                    "competitor_in_stock": 1,
                    "competitor_age_days": 1,
                    "local_event_count_horizon": 0,
                    "local_event_impact_horizon": 0,
                    "disruption_demand_factor_horizon": 1,
                    "origin_year": origin.year,
                }
            )
    return pd.DataFrame(rows)


def test_horizon_model_is_deterministic_monotonic_and_channel_aware() -> None:
    frame = _training_frame()
    model = fit_horizon_model(frame, horizon=1, threads_per_model=1)
    scored = score_horizon_model(frame.tail(200), model)

    assert (scored["yhat_p90"] >= scored["yhat_p50"]).all()
    assert scored["confidence"].between(0, 1).all()
    assert model.global_calibration.sufficient
    assert "shap_demand_trend" in scored
    assert set(model.categories["channel_id"]) == {
        "india-west:store",
        "us-new-york:store",
    }


def test_model_outputs_are_invariant_to_threads_per_model() -> None:
    frame = _training_frame()
    evaluation = frame.tail(200)
    safe_model = fit_horizon_model(
        frame,
        horizon=1,
        threads_per_model=1,
    )
    performance_model = fit_horizon_model(
        frame,
        horizon=1,
        threads_per_model=4,
    )
    safe = score_horizon_model(evaluation, safe_model)
    performance = score_horizon_model(evaluation, performance_model)

    columns = [
        "lightgbm_p50_raw",
        "lightgbm_p90_raw",
        "yhat_p50",
        "yhat_p90",
        "confidence",
        *(f"shap_{group}" for group in LIVE_DRIVER_GROUPS),
    ]
    np.testing.assert_allclose(
        safe[columns].to_numpy(dtype=float),
        performance[columns].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    )
    assert asdict(safe_model.global_calibration) == asdict(
        performance_model.global_calibration
    )
    assert safe_model.market_calibrations == performance_model.market_calibrations
