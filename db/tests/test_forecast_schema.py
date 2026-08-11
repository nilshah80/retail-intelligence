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
        # Decision #96: immutable assumption bundles, separately approved, plus
        # independently activatable base and inventory-extension contexts.
        "forecast_scenario_assumption_sets",
        "forecast_scenario_market_rules",
        "forecast_scenario_tier_coefficients",
        "forecast_scenario_presets",
        "forecast_scenario_assumption_approval_events",
        "forecast_scenario_contexts",
        "forecast_scenario_horizon_rows",
        "forecast_scenario_commercial_rows",
        "forecast_scenario_inventory_extensions",
        "forecast_scenario_inventory_series_rows",
        "forecast_scenario_inventory_node_rows",
        "forecast_scenario_context_activation_events",
        "forecast_scenario_inventory_activation_events",
    }
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT version_num
                FROM retail_intelligence_alembic_version
                """
            )
            assert cursor.fetchone() == ("0027_scenario_hardening",)
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
                SELECT table_name
                FROM information_schema.views
                WHERE table_schema = 'retail_serving'
                  AND table_name IN (
                    'forecast_scenario_assumption_approval_heads',
                    'effective_forecast_scenario_assumption_approvals',
                    'forecast_scenario_context_activation_heads',
                    'active_forecast_scenario_contexts',
                    'forecast_scenario_inventory_activation_heads',
                    'active_forecast_scenario_inventory_extensions'
                  )
                """
            )
            assert {row[0] for row in cursor.fetchall()} == {
                "forecast_scenario_assumption_approval_heads",
                "effective_forecast_scenario_assumption_approvals",
                "forecast_scenario_context_activation_heads",
                "active_forecast_scenario_contexts",
                "forecast_scenario_inventory_activation_heads",
                "active_forecast_scenario_inventory_extensions",
            }
            cursor.execute(
                """
                SELECT table_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'retail_serving'
                  AND column_name = 'children_sealed'
                  AND table_name IN (
                    'forecast_scenario_assumption_sets',
                    'forecast_scenario_contexts',
                    'forecast_scenario_inventory_extensions'
                  )
                ORDER BY table_name
                """
            )
            sealed_columns = cursor.fetchall()
            assert [row[0] for row in sealed_columns] == [
                "forecast_scenario_assumption_sets",
                "forecast_scenario_contexts",
                "forecast_scenario_inventory_extensions",
            ]
            assert all(row[1] == "NO" and "false" in row[2] for row in sealed_columns)
            cursor.execute(
                """
                SELECT pg_get_functiondef(
                    'retail_serving.seal_scenario_assumption_set()'::regprocedure
                )
                """
            )
            tier_seal_guard = cursor.fetchone()[0]
            assert "previous_upper" in tier_seal_guard
            assert "minimum_price_minor" in tier_seal_guard
            assert "incomplete or ambiguous tier coverage" in tier_seal_guard
            cursor.execute(
                """
                SELECT trigger_name
                FROM information_schema.triggers
                WHERE trigger_schema = 'retail_serving'
                  AND trigger_name IN (
                    'trg_scenario_assumption_set_seal_only',
                    'trg_forecast_scenario_contexts_seal_only',
                    'trg_forecast_scenario_inventory_extensions_seal_only',
                    'trg_forecast_scenario_horizon_rows_sealed_insert',
                    'trg_forecast_scenario_commercial_rows_sealed_insert',
                    'trg_forecast_scenario_inventory_series_rows_sealed_insert',
                    'trg_forecast_scenario_inventory_node_rows_sealed_insert'
                  )
                """
            )
            assert {row[0] for row in cursor.fetchall()} == {
                "trg_scenario_assumption_set_seal_only",
                "trg_forecast_scenario_contexts_seal_only",
                "trg_forecast_scenario_inventory_extensions_seal_only",
                "trg_forecast_scenario_horizon_rows_sealed_insert",
                "trg_forecast_scenario_commercial_rows_sealed_insert",
                "trg_forecast_scenario_inventory_series_rows_sealed_insert",
                "trg_forecast_scenario_inventory_node_rows_sealed_insert",
            }
            cursor.execute(
                """
                SELECT check_clause
                FROM information_schema.check_constraints
                WHERE constraint_schema = 'retail_serving'
                  AND constraint_name = 'ck_forecast_series_dimension_channel_type'
                """
            )
            channel_type_check = cursor.fetchone()
            assert channel_type_check is not None
            assert "'online'" in channel_type_check[0]
            assert "'store'" in channel_type_check[0]
            assert "'marketplace'" in channel_type_check[0]
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


def test_database_refuses_to_seal_ambiguous_scenario_tiers() -> None:
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL schema integration environment is not configured")
    fingerprint = "f" * 64
    connection = psycopg.connect(dsn)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO retail_serving.forecast_scenario_assumption_sets (
                    assumption_set_id, assumption_version, semantic_fingerprint,
                    schema_version, artifact_class, serving_eligible,
                    projection_basis, evidence_class, statistical_gate_status,
                    disclosure, request_bounds, bundle_payload
                ) VALUES (
                    'db-tier-guard-test', '1', %s,
                    'retail-forecast-scenario-assumptions/v1',
                    'serving_candidate', TRUE, 'assumption_set',
                    'synthetic_scenario', 'not_applicable', 'test', '{}'::jsonb,
                    '{}'::jsonb
                )
                """,
                (fingerprint,),
            )
            cursor.execute(
                """
                INSERT INTO retail_serving.forecast_scenario_market_rules (
                    assumption_semantic_fingerprint, market_id, currency_code,
                    minimum_price_minor, maximum_price_minor,
                    candidate_step_minor, grid_origin_minor, rounding_mode,
                    price_freshness_days, observed_support_window_days
                ) VALUES (%s, 'm', 'USD', 1, 10000, 1, 0,
                          'round_half_even', 30, 90)
                """,
                (fingerprint,),
            )
            cursor.execute(
                """
                INSERT INTO retail_serving.forecast_scenario_tier_coefficients (
                    assumption_semantic_fingerprint, market_id, dept_id,
                    baseline_price_tier, lower_price_minor, upper_price_minor,
                    assumed_beta, competitor_stockout_sensitivity,
                    competitor_promotion_sensitivity,
                    weather_positive_sensitivity, weather_negative_sensitivity
                ) VALUES
                    (%s, 'm', 'd', 'first', 1, NULL, -1, .1, .1, .1, .1),
                    (%s, 'm', 'd', 'second', 5000, NULL, -1, .1, .1, .1, .1)
                """,
                (fingerprint, fingerprint),
            )
            with pytest.raises(
                psycopg.errors.RaiseException,
                match="incomplete or ambiguous tier coverage",
            ):
                cursor.execute(
                    """
                    UPDATE retail_serving.forecast_scenario_assumption_sets
                    SET children_sealed = TRUE
                    WHERE semantic_fingerprint = %s
                    """,
                    (fingerprint,),
                )
    finally:
        connection.rollback()
        connection.close()
