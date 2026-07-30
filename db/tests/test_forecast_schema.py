from __future__ import annotations

import os

import psycopg
import pytest


def test_forecast_serving_schema_integration() -> None:
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL schema integration environment is not configured")
    expected_tables = {
        "forecast_activation_events",
        "forecast_data_quality",
        "forecast_drivers",
        "forecast_eval_predictions",
        "forecast_exceptions",
        "forecast_materializations",
        "forecast_metrics",
        "forecast_series",
        "forecast_series_dimensions",
        "forecast_stores",
        "forecast_versions",
    }
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version_num
                FROM retail_intelligence_alembic_version
                """
            )
            assert cursor.fetchone() == ("0003_forecast_series_dimensions",)
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'retail_serving'
                  AND table_type = 'BASE TABLE'
                """
            )
            assert {row[0] for row in cursor.fetchall()} == expected_tables
            cursor.execute(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'retail_serving'
                  AND table_name = 'forecast_eval_predictions'
                  AND column_name = 'zero_share_52w'
                """
            )
            assert cursor.fetchone() == ("YES",)
