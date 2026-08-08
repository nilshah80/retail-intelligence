from datetime import date

import pandas as pd
import pytest

from retail_ml.inventory_run.load import InventoryLoadError, load_forecast


def _series() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market_id": "gulf-india",
                "store_id": store,
                "sku_id": "sku-1",
                "horizon_week": 1,
                "expected_units": expected,
                "yhat_p50": p50,
                "yhat_p90": p90,
                "interval_available": True,
            }
            for store, expected, p50, p90 in (
                ("store-1", 10.0, 8.0, 14.0),
                ("store-2", 20.0, 12.0, 25.0),
            )
        ]
    )


def test_node_demand_sums_expected_units_without_claiming_an_interval() -> None:
    positions = pd.DataFrame(
        [
            {"market_id": "gulf-india", "location_id": location, "sku_id": "sku-1"}
            for location in ("store-1", "store-2", "dc-1")
        ]
    )
    lanes = [
        {
            "market_id": "gulf-india",
            "lane_type": "replenishment",
            "priority_rank": 1,
            "demand_location_id": store,
            "supply_location_id": "dc-1",
            "effective_from": date(2020, 1, 1),
            "effective_to": None,
        }
        for store in ("store-1", "store-2")
    ]

    loaded = load_forecast(
        _series(), positions=positions, lanes=lanes, as_of=date(2026, 8, 9)
    )

    node = loaded[loaded["location_id"].eq("dc-1")].iloc[0]
    assert node["expected_units"] == pytest.approx(30.0)
    assert node["yhat_p50"] == pytest.approx(20.0)
    assert pd.isna(node["yhat_p90"])
    assert bool(node["interval_available"]) is False
    assert node["demand_basis"] == "aggregated_supplied_stores_expected_units"


def test_inventory_refuses_to_infer_interval_availability_from_p90() -> None:
    series = _series()
    series.loc[0, "interval_available"] = False

    with pytest.raises(InventoryLoadError, match="disagrees"):
        load_forecast(
            series,
            positions=pd.DataFrame(
                [
                    {
                        "market_id": "gulf-india",
                        "location_id": "store-1",
                        "sku_id": "sku-1",
                    }
                ]
            ),
            lanes=[],
            as_of=date(2026, 8, 9),
        )
