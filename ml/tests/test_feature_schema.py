from retail_ml.features.availability import (
    FUTURE_CALENDAR_COLUMNS,
    TARGET_AVAILABILITY_COLUMNS,
    TARGET_COLUMNS,
)
from retail_ml.features.build import weekly_features_sql


def test_weekly_feature_sql_has_full_horizon_and_channel_grain() -> None:
    sql = weekly_features_sql()

    assert len(TARGET_COLUMNS) == 26
    assert len(TARGET_AVAILABILITY_COLUMNS) == 26
    assert len(FUTURE_CALENDAR_COLUMNS) == 52
    assert "target_units_h26" in sql
    assert "target_known_as_of_h26" in sql
    assert "event_count_h26" in sql
    assert "working_days_h26" in sql
    assert "PARTITION BY sku_id, store_id, channel_id" in sql


def test_model_feature_output_contains_no_absolute_currency_level() -> None:
    final_select = weekly_features_sql().split("selected_features AS (", maxsplit=1)[1]

    assert "observed_net_price" not in final_select.split("FROM feature_windows", maxsplit=1)[0]
    assert "price_ratio_13w" in final_select
    assert "local_category_price_index" in final_select
