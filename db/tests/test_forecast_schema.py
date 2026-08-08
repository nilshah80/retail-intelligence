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
        "forecast_eval_recent",
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
        "inventory_sku_dimension",
        "inventory_valuation",
        "replenishment_recommendations",
        "replenishment_safety_stock",
        "replenishment_transfers",
        "replenishment_allocations",
        "replenishment_suppliers",
        "replenishment_exceptions",
        "inventory_replay_metrics",
        # Migration 0014: the storage ceiling Capacity Utilization divides by.
        "inventory_warehouse_capacity",
        # Migration 0017: inbound reliability per receiving node.
        "inventory_inbound_summary",
        # Migration 0018: the market ceilings a plan is measured against.
        "inventory_market_policy",
    }
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version_num
                FROM retail_intelligence_alembic_version
                """
            )
            assert cursor.fetchone() == ("0022_expected_volume_forecast",)
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
            # Migration 0022 advances the serving boundary to verifier-v7: a run
            # must carry Decision #95's separately named additive expectation. Older
            # accepted materializations are not reinterpreted; they become ineligible
            # until rebuilt under run/v5 and verifier/v7.
            assert "retail-forecast-verifier/v7" in view_definition
            assert "retail-forecast-verifier/v6" not in view_definition
            assert "retail-forecast-verifier/v5" not in view_definition
            assert "retail-forecast-verifier/v4" not in view_definition
            assert "retail-forecast-verifier/v3" not in view_definition
            cursor.execute(
                """
                SELECT table_name, column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'retail_serving'
                  AND column_name IN ('expected_units', 'expected_model')
                  AND table_name IN (
                    'forecast_series',
                    'forecast_eval_predictions',
                    'forecast_eval_recent'
                  )
                ORDER BY table_name, column_name
                """
            )
            assert cursor.fetchall() == [
                ("forecast_eval_predictions", "expected_model", "YES"),
                ("forecast_eval_predictions", "expected_units", "YES"),
                ("forecast_eval_recent", "expected_model", "YES"),
                ("forecast_eval_recent", "expected_units", "YES"),
                ("forecast_series", "expected_model", "YES"),
                ("forecast_series", "expected_units", "YES"),
            ]
            cursor.execute(
                """
                SELECT check_clause
                FROM information_schema.check_constraints
                WHERE constraint_schema = 'retail_serving'
                  AND constraint_name = 'ck_forecast_eval_recent_horizon'
                """
            )
            recent_horizon_check = cursor.fetchone()
            assert recent_horizon_check is not None
            assert "horizon >= 1" in recent_horizon_check[0]
            assert "horizon <= 4" in recent_horizon_check[0]
