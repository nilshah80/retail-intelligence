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
        # Migration 0010: the inventory/replenishment serving surface. Same
        # exhaustive posture as the forecast set -- a table appearing without a
        # deliberate migration is drift.
        "inventory_materializations",
        "inventory_versions",
        "inventory_activation_events",
        "active_inventory_state",
        "inventory_positions",
        "inventory_stock_health",
        "inventory_demand_at_risk",
        "inventory_ageing",
        "inventory_expiry_waste",
        "inventory_valuation",
        "replenishment_recommendations",
        "replenishment_safety_stock",
        "replenishment_transfers",
        "replenishment_allocations",
        "replenishment_suppliers",
        "replenishment_exceptions",
        "inventory_replay_metrics",
    }
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version_num
                FROM retail_intelligence_alembic_version
                """
            )
            assert cursor.fetchone() == ("0010_inventory_serving",)
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
            cursor.execute(
                """
                SELECT is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'retail_serving'
                  AND table_name = 'forecast_materializations'
                  AND column_name = 'verification_contract'
                """
            )
            nullable, default = cursor.fetchone()
            assert nullable == "NO"
            assert "legacy-unverified" in default
            cursor.execute(
                """
                SELECT view_definition
                FROM information_schema.views
                WHERE table_schema = 'retail_serving'
                  AND table_name = 'active_forecast_versions'
                """
            )
            view_definition = cursor.fetchone()[0]
            assert "verification_contract" in view_definition
            # Migration 0007 admits decision-#85 verifier-v5 evidence only: a run scored
            # against the HARD per-cohort coverage gate. Every earlier contract stops
            # being eligible to serve without being reinterpreted, which is the
            # fail-closed version boundary #85 promised and originally never created.
            assert "retail-forecast-verifier/v5" in view_definition
            assert "retail-forecast-verifier/v4" not in view_definition
            assert "retail-forecast-verifier/v3" not in view_definition
