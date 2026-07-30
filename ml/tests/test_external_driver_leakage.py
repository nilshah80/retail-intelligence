from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from retail_ml.features.external import (
    DRIVER_NAMES,
    DriverAvailabilityError,
    assert_no_promotion_features,
    load_driver_semantics,
    origin_published_target_rows,
    origin_visible_rows,
)


@pytest.mark.parametrize("driver", DRIVER_NAMES)
def test_planted_post_origin_value_is_rejected_for_every_driver(driver: str) -> None:
    rows = pd.DataFrame(
        {
            "driver": [driver, driver],
            "known_as_of": [
                "2026-07-01T00:00:00Z",
                "2026-07-03T00:00:00Z",
            ],
            "value": [1, 999],
        }
    )

    visible = origin_visible_rows(
        rows,
        fit_known_as_of=datetime(2026, 7, 2, tzinfo=timezone.utc),
    )

    assert visible["value"].tolist() == [1]


def test_weather_target_value_requires_exact_origin_published_date() -> None:
    rows = pd.DataFrame(
        {
            "target_date": ["2026-07-08", "2026-07-09", "2026-07-08"],
            "known_as_of": [
                "2026-07-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
                "2026-07-03T00:00:00Z",
            ],
            "value": [10, 20, 999],
        }
    )
    selected = origin_published_target_rows(
        rows,
        target_date=date(2026, 7, 8),
        fit_known_as_of=datetime(2026, 7, 2, tzinfo=timezone.utc),
        target_date_column="target_date",
    )
    assert selected["value"].tolist() == [10]


def test_promotion_feature_cannot_reappear() -> None:
    with pytest.raises(DriverAvailabilityError, match="unavailable"):
        assert_no_promotion_features(["units_lag_1", "promotion_discount"])


def test_versioned_driver_contract_lists_every_driver() -> None:
    root = Path(__file__).resolve().parents[2]
    semantics = load_driver_semantics(root / "contracts/ml/driver-semantics.yaml")
    assert set(semantics["drivers"]) == set(DRIVER_NAMES)
