import pandas as pd

from retail_ml.models.drivers import (
    LIVE_DRIVER_GROUPS,
    aggregate_driver_rows,
)
from retail_ml.models.train_lgbm import DRIVER_FEATURE_GROUPS, MODEL_FEATURES


def test_every_model_feature_maps_to_a_live_driver_group() -> None:
    assigned = set().union(*DRIVER_FEATURE_GROUPS.values())
    assert set(MODEL_FEATURES) <= assigned


def test_driver_rounding_is_exact_and_mixed_direction_is_explicit() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["sku", "sku"],
            "store_id": ["store", "store"],
            "channel_id": ["channel", "channel"],
            "shap_demand_trend": [2.0, -1.0],
            "shap_seasonality": [1.0, 1.0],
            "shap_price": [0.5, 0.5],
            "shap_competitor_activity": [0.25, 0.25],
            "shap_weather_local_events": [0.25, 0.25],
        }
    )
    rows = aggregate_driver_rows(frame)
    portfolio = rows[rows["scope"] == "portfolio"]

    assert set(portfolio["driver"]) == set(LIVE_DRIVER_GROUPS)
    assert round(portfolio["contribution_pct"].astype(float).sum(), 4) == 100.0
    demand = portfolio[portfolio["driver"] == "demand_trend"].iloc[0]
    assert demand["direction"] == "Mixed"


def test_croston_rows_do_not_pretend_to_have_tree_shap() -> None:
    frame = pd.DataFrame(
        {
            "sku_id": ["sku", "sku"],
            "store_id": ["store", "store"],
            "channel_id": ["channel", "channel"],
            "selected_model": [
                "lightgbm_horizon_quantile",
                "croston_sba_replay_selected",
            ],
            "shap_demand_trend": [1.0, 0.0],
            "shap_seasonality": [0.0, 100.0],
            "shap_price": [0.0, 0.0],
            "shap_competitor_activity": [0.0, 0.0],
            "shap_weather_local_events": [0.0, 0.0],
        }
    )
    rows = aggregate_driver_rows(frame, include_series=False)

    live = rows[rows["driver"].isin(LIVE_DRIVER_GROUPS)]
    demand = live[live["driver"] == "demand_trend"].iloc[0]
    seasonality = live[live["driver"] == "seasonality"].iloc[0]
    assert demand["contribution_pct"] == "100.0000"
    assert seasonality["contribution_pct"] == "0.0000"
    assert "croston_routing_explanation" in set(rows["driver"])
