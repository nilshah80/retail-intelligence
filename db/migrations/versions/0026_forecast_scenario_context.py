"""Add immutable Forecast Scenario v1 base and inventory-extension contexts.

The base context is independently servable. Inventory is a separately versioned,
optional extension, preventing a missing inventory authority from blocking demand
and market-local revenue. Activation heads are branch-visible: competing active
heads survive in the views so the API can return 503 rather than silently choose.

Revision ID: 0026_scenario_context
Revises: 0025_scenario_assumptions
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_scenario_context"
down_revision: str | Sequence[str] | None = "0025_scenario_assumptions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def _fingerprint(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.String(length=64), nullable=nullable)


def _append_only_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_append_only
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_append_only_mutation()
        """
    )


def upgrade() -> None:
    op.create_table(
        "forecast_scenario_contexts",
        _fingerprint("scenario_context_version"),
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        _fingerprint("authority_scope_fingerprint"),
        _fingerprint("forecast_activation_scope_fingerprint"),
        sa.Column("forecast_version_id", sa.Text(), nullable=False),
        sa.Column("scenario_decision_as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("assumption_set_id", sa.Text(), nullable=False),
        sa.Column("assumption_version", sa.Text(), nullable=False),
        _fingerprint("assumption_semantic_fingerprint"),
        sa.Column("assumption_approval_event_id", sa.BigInteger(), nullable=False),
        _fingerprint("assumption_approval_semantic_fingerprint"),
        _fingerprint("price_snapshot_content_fingerprint"),
        sa.Column("context_schema_version", sa.Text(), nullable=False),
        sa.Column("materializer_version", sa.Text(), nullable=False),
        _fingerprint("base_output_content_fingerprint"),
        sa.Column(
            "children_sealed",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "materialized_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("scenario_context_version"),
        sa.ForeignKeyConstraint(
            ["forecast_version_id"],
            [f"{SCHEMA}.forecast_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assumption_approval_event_id"],
            [f"{SCHEMA}.forecast_scenario_assumption_approval_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "assumption_set_id",
                "assumption_version",
                "assumption_semantic_fingerprint",
            ],
            [
                f"{SCHEMA}.forecast_scenario_assumption_sets.assumption_set_id",
                f"{SCHEMA}.forecast_scenario_assumption_sets.assumption_version",
                f"{SCHEMA}.forecast_scenario_assumption_sets.semantic_fingerprint",
            ],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "capability = 'forecast_scenario_v1'",
            name="ck_scenario_context_capability",
        ),
        sa.CheckConstraint(
            "scenario_context_version ~ '^[0-9a-f]{64}$' "
            "AND authority_scope_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND forecast_activation_scope_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND assumption_semantic_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND assumption_approval_semantic_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND price_snapshot_content_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND base_output_content_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_scenario_context_fingerprints",
        ),
        sa.CheckConstraint(
            "context_schema_version = 'retail-forecast-scenario-context/v1'",
            name="ck_scenario_context_schema",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_context_authority",
        "forecast_scenario_contexts",
        [
            "retailer_id",
            "tenant_id",
            "capability",
            "environment",
            "scenario_context_version",
        ],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_horizon_rows",
        _fingerprint("scenario_context_version"),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("dept_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("horizon_week", sa.Integer(), nullable=False),
        sa.Column("target_week_start", sa.Date(), nullable=False),
        sa.Column("expected_units", sa.Numeric(24, 8), nullable=False),
        sa.Column("expected_model", sa.Text(), nullable=False),
        sa.Column("p50_units", sa.Numeric(24, 8), nullable=False),
        sa.Column("p90_units", sa.Numeric(24, 8), nullable=True),
        sa.Column("interval_available", sa.Boolean(), nullable=False),
        sa.Column("interval_reason_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["scenario_context_version"],
            [f"{SCHEMA}.forecast_scenario_contexts.scenario_context_version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "scenario_context_version",
            "market_id",
            "sku_id",
            "store_id",
            "channel_id",
            "horizon_week",
        ),
        sa.CheckConstraint(
            "horizon_week BETWEEN 1 AND 26",
            name="ck_scenario_horizon_week",
        ),
        sa.CheckConstraint(
            "expected_units >= 0 AND p50_units >= 0 "
            "AND (p90_units IS NULL OR p90_units >= p50_units)",
            name="ck_scenario_horizon_values",
        ),
        sa.CheckConstraint(
            "(interval_available AND p90_units IS NOT NULL "
            "AND interval_reason_code IS NULL) "
            "OR (NOT interval_available AND p90_units IS NULL "
            "AND interval_reason_code IS NOT NULL)",
            name="ck_scenario_horizon_interval",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_horizon_scope",
        "forecast_scenario_horizon_rows",
        [
            "scenario_context_version",
            "market_id",
            "store_id",
            "channel_id",
            "dept_id",
            "horizon_week",
        ],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_commercial_rows",
        _fingerprint("scenario_context_version"),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("dept_id", sa.Text(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("price_available", sa.Boolean(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("price_basis", sa.Text(), nullable=True),
        sa.Column("price_unavailable_reason", sa.Text(), nullable=True),
        sa.Column("source_row_identity", sa.Text(), nullable=True),
        sa.Column("source_row_version", sa.Text(), nullable=True),
        sa.Column("source_observation_date", sa.Date(), nullable=True),
        sa.Column("source_known_as_of", sa.TIMESTAMP(timezone=True), nullable=True),
        _fingerprint("source_row_content_fingerprint", nullable=True),
        sa.Column("fallback_population_count", sa.Integer(), nullable=True),
        sa.Column("fallback_observation_start", sa.Date(), nullable=True),
        sa.Column("fallback_observation_end", sa.Date(), nullable=True),
        sa.Column("fallback_max_known_as_of", sa.TIMESTAMP(timezone=True), nullable=True),
        _fingerprint("fallback_member_set_content_fingerprint", nullable=True),
        sa.Column("source_cutoff", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("freshness_status", sa.Text(), nullable=False),
        sa.Column("freshness_reason_code", sa.Text(), nullable=True),
        sa.Column("observed_support_low_minor", sa.BigInteger(), nullable=True),
        sa.Column("observed_support_high_minor", sa.BigInteger(), nullable=True),
        sa.Column("observed_support_start", sa.Date(), nullable=True),
        sa.Column("observed_support_end", sa.Date(), nullable=True),
        _fingerprint("observed_support_content_fingerprint", nullable=True),
        sa.Column("baseline_price_tier", sa.Text(), nullable=True),
        sa.Column("tier_resolution_reason", sa.Text(), nullable=True),
        sa.Column("assumed_beta", sa.Numeric(18, 9), nullable=True),
        sa.Column("competitor_stockout_sensitivity", sa.Numeric(18, 9), nullable=True),
        sa.Column("competitor_promotion_sensitivity", sa.Numeric(18, 9), nullable=True),
        sa.Column("weather_positive_sensitivity", sa.Numeric(18, 9), nullable=True),
        sa.Column("weather_negative_sensitivity", sa.Numeric(18, 9), nullable=True),
        _fingerprint("coefficient_content_fingerprint", nullable=True),
        sa.ForeignKeyConstraint(
            ["scenario_context_version"],
            [f"{SCHEMA}.forecast_scenario_contexts.scenario_context_version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "scenario_context_version",
            "market_id",
            "sku_id",
            "store_id",
            "channel_id",
        ),
        sa.CheckConstraint(
            "(price_available AND unit_price_minor > 0 "
            "AND price_basis IN ('latest_realized_exact','market_sku_latest_median') "
            "AND price_unavailable_reason IS NULL) "
            "OR (NOT price_available AND unit_price_minor IS NULL "
            "AND price_basis IS NULL AND price_unavailable_reason IS NOT NULL)",
            name="ck_scenario_commercial_price",
        ),
        sa.CheckConstraint(
            "(price_basis = 'latest_realized_exact' "
            "AND source_row_identity IS NOT NULL "
            "AND source_row_version IS NOT NULL "
            "AND source_observation_date IS NOT NULL "
            "AND source_known_as_of IS NOT NULL "
            "AND source_row_content_fingerprint IS NOT NULL "
            "AND fallback_population_count IS NULL "
            "AND fallback_observation_start IS NULL "
            "AND fallback_observation_end IS NULL "
            "AND fallback_max_known_as_of IS NULL "
            "AND fallback_member_set_content_fingerprint IS NULL) "
            "OR (price_basis = 'market_sku_latest_median' "
            "AND source_row_identity IS NULL AND source_row_version IS NULL "
            "AND source_observation_date IS NULL AND source_known_as_of IS NULL "
            "AND source_row_content_fingerprint IS NULL "
            "AND fallback_population_count > 0 "
            "AND fallback_observation_start IS NOT NULL "
            "AND fallback_observation_end IS NOT NULL "
            "AND fallback_observation_start <= fallback_observation_end "
            "AND fallback_max_known_as_of IS NOT NULL "
            "AND fallback_member_set_content_fingerprint IS NOT NULL) "
            "OR (price_basis IS NULL "
            "AND source_row_identity IS NULL AND source_row_version IS NULL "
            "AND source_observation_date IS NULL AND source_known_as_of IS NULL "
            "AND source_row_content_fingerprint IS NULL "
            "AND fallback_population_count IS NULL "
            "AND fallback_observation_start IS NULL "
            "AND fallback_observation_end IS NULL "
            "AND fallback_max_known_as_of IS NULL "
            "AND fallback_member_set_content_fingerprint IS NULL)",
            name="ck_scenario_commercial_provenance",
        ),
        sa.CheckConstraint(
            "(source_observation_date IS NULL OR source_observation_date <= "
            "CAST(source_cutoff AT TIME ZONE 'UTC' AS DATE)) AND "
            "(source_known_as_of IS NULL OR source_known_as_of <= source_cutoff) AND "
            "(fallback_observation_end IS NULL OR fallback_observation_end <= "
            "CAST(source_cutoff AT TIME ZONE 'UTC' AS DATE)) AND "
            "(fallback_max_known_as_of IS NULL OR "
            "fallback_max_known_as_of <= source_cutoff) AND "
            "(observed_support_end IS NULL OR observed_support_end <= "
            "CAST(source_cutoff AT TIME ZONE 'UTC' AS DATE))",
            name="ck_scenario_commercial_origin_cutoff",
        ),
        sa.CheckConstraint(
            "(freshness_status = 'fresh' AND price_available "
            "AND freshness_reason_code IS NULL) "
            "OR (freshness_status IN ('stale','unavailable') "
            "AND freshness_reason_code IS NOT NULL)",
            name="ck_scenario_commercial_freshness",
        ),
        sa.CheckConstraint(
            "(price_available AND ((observed_support_low_minor > 0 "
            "AND observed_support_high_minor >= observed_support_low_minor "
            "AND observed_support_start IS NOT NULL "
            "AND observed_support_end IS NOT NULL "
            "AND observed_support_start <= observed_support_end "
            "AND observed_support_content_fingerprint IS NOT NULL) "
            "OR (observed_support_low_minor IS NULL "
            "AND observed_support_high_minor IS NULL "
            "AND observed_support_start IS NULL "
            "AND observed_support_end IS NULL "
            "AND observed_support_content_fingerprint IS NULL "
            "AND freshness_status = 'unavailable' "
            "AND freshness_reason_code IS NOT NULL))) "
            "OR (NOT price_available "
            "AND observed_support_low_minor IS NULL "
            "AND observed_support_high_minor IS NULL "
            "AND observed_support_start IS NULL "
            "AND observed_support_end IS NULL "
            "AND observed_support_content_fingerprint IS NULL)",
            name="ck_scenario_commercial_support",
        ),
        sa.CheckConstraint(
            "(baseline_price_tier IS NOT NULL "
            "AND tier_resolution_reason IS NULL "
            "AND assumed_beta < 0 "
            "AND competitor_stockout_sensitivity >= 0 "
            "AND competitor_stockout_sensitivity < 1 "
            "AND competitor_promotion_sensitivity >= 0 "
            "AND competitor_promotion_sensitivity < 1 "
            "AND weather_positive_sensitivity >= 0 "
            "AND weather_positive_sensitivity < 1 "
            "AND weather_negative_sensitivity >= 0 "
            "AND weather_negative_sensitivity < 1 "
            "AND coefficient_content_fingerprint IS NOT NULL) "
            "OR (baseline_price_tier IS NULL "
            "AND tier_resolution_reason IS NOT NULL "
            "AND assumed_beta IS NULL "
            "AND competitor_stockout_sensitivity IS NULL "
            "AND competitor_promotion_sensitivity IS NULL "
            "AND weather_positive_sensitivity IS NULL "
            "AND weather_negative_sensitivity IS NULL "
            "AND coefficient_content_fingerprint IS NULL)",
            name="ck_scenario_commercial_tier",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_commercial_scope",
        "forecast_scenario_commercial_rows",
        [
            "scenario_context_version",
            "market_id",
            "store_id",
            "channel_id",
            "dept_id",
        ],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_inventory_extensions",
        _fingerprint("inventory_extension_version"),
        _fingerprint("scenario_context_version"),
        sa.Column("inventory_version_id", sa.Text(), nullable=False),
        sa.Column("extension_schema_version", sa.Text(), nullable=False),
        sa.Column("materializer_version", sa.Text(), nullable=False),
        _fingerprint("inventory_output_content_fingerprint"),
        sa.Column(
            "children_sealed",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column(
            "manifest",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "materialized_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("inventory_extension_version"),
        sa.ForeignKeyConstraint(
            ["scenario_context_version"],
            [f"{SCHEMA}.forecast_scenario_contexts.scenario_context_version"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_version_id"],
            [f"{SCHEMA}.inventory_versions.inventory_version_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "inventory_extension_version ~ '^[0-9a-f]{64}$' "
            "AND scenario_context_version ~ '^[0-9a-f]{64}$' "
            "AND inventory_output_content_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_scenario_inventory_extension_fingerprints",
        ),
        sa.CheckConstraint(
            "extension_schema_version = 'retail-forecast-scenario-inventory/v1'",
            name="ck_scenario_inventory_extension_schema",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_inventory_extension_base",
        "forecast_scenario_inventory_extensions",
        ["scenario_context_version", "inventory_extension_version"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_inventory_series_rows",
        _fingerprint("inventory_extension_version"),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("allocated_atp_units", sa.BigInteger(), nullable=False),
        sa.Column("requested_units", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["inventory_extension_version"],
            [
                f"{SCHEMA}.forecast_scenario_inventory_extensions."
                "inventory_extension_version"
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "inventory_extension_version",
            "market_id",
            "sku_id",
            "store_id",
            "channel_id",
        ),
        sa.CheckConstraint(
            "allocated_atp_units >= 0 AND requested_units >= 0",
            name="ck_scenario_inventory_series_units",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_inventory_series_scope",
        "forecast_scenario_inventory_series_rows",
        ["inventory_extension_version", "market_id", "store_id", "channel_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_inventory_node_rows",
        _fingerprint("inventory_extension_version"),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("replenishment_available", sa.Boolean(), nullable=False),
        sa.Column("order_up_to_units", sa.Numeric(24, 8), nullable=True),
        sa.Column("reorder_point_units", sa.Numeric(24, 8), nullable=True),
        sa.Column("replenishment_reason_code", sa.Text(), nullable=True),
        sa.Column("node_atp_units", sa.BigInteger(), nullable=False),
        sa.Column("allocated_atp_units", sa.BigInteger(), nullable=False),
        sa.Column("residual_atp_units", sa.BigInteger(), nullable=False),
        sa.Column("unit_cost_minor", sa.BigInteger(), nullable=True),
        sa.Column("unit_cost_basis", sa.Text(), nullable=True),
        sa.Column("unit_cost_reason_code", sa.Text(), nullable=True),
        _fingerprint("unit_cost_content_fingerprint", nullable=True),
        sa.Column("protection_available", sa.Boolean(), nullable=False),
        sa.Column("lead_time_days", sa.Numeric(12, 4), nullable=True),
        sa.Column("review_period_days", sa.Integer(), nullable=False),
        sa.Column("protection_days", sa.Numeric(12, 4), nullable=True),
        sa.Column("protection_reason_code", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["inventory_extension_version"],
            [
                f"{SCHEMA}.forecast_scenario_inventory_extensions."
                "inventory_extension_version"
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "inventory_extension_version", "market_id", "sku_id", "location_id"
        ),
        sa.CheckConstraint(
            "node_atp_units >= 0 AND allocated_atp_units >= 0 "
            "AND residual_atp_units >= 0 "
            "AND allocated_atp_units + residual_atp_units = node_atp_units",
            name="ck_scenario_inventory_node_conservation",
        ),
        sa.CheckConstraint(
            "(replenishment_available AND order_up_to_units >= 0 "
            "AND reorder_point_units >= 0 "
            "AND replenishment_reason_code IS NULL) "
            "OR (NOT replenishment_available AND order_up_to_units IS NULL "
            "AND reorder_point_units IS NULL "
            "AND replenishment_reason_code IS NOT NULL)",
            name="ck_scenario_inventory_node_replenishment",
        ),
        sa.CheckConstraint(
            "(unit_cost_minor > 0 AND unit_cost_basis IS NOT NULL "
            "AND unit_cost_reason_code IS NULL "
            "AND unit_cost_content_fingerprint IS NOT NULL) "
            "OR (unit_cost_minor IS NULL AND unit_cost_basis IS NULL "
            "AND unit_cost_reason_code IS NOT NULL "
            "AND unit_cost_content_fingerprint IS NULL)",
            name="ck_scenario_inventory_node_cost",
        ),
        sa.CheckConstraint(
            "review_period_days > 0 AND ("
            "(protection_available AND lead_time_days > 0 "
            "AND protection_days = lead_time_days + review_period_days "
            "AND protection_reason_code IS NULL) OR "
            "(NOT protection_available AND lead_time_days IS NULL "
            "AND protection_days IS NULL "
            "AND protection_reason_code IS NOT NULL))",
            name="ck_scenario_inventory_node_windows",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_inventory_node_scope",
        "forecast_scenario_inventory_node_rows",
        ["inventory_extension_version", "market_id", "location_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_context_activation_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        _fingerprint("authority_scope_fingerprint"),
        _fingerprint("scenario_context_version"),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("decision_reference", sa.Text(), nullable=False),
        sa.Column("prior_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scenario_context_version"],
            [f"{SCHEMA}.forecast_scenario_contexts.scenario_context_version"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_event_id"],
            [f"{SCHEMA}.forecast_scenario_context_activation_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "capability = 'forecast_scenario_v1'",
            name="ck_scenario_context_activation_capability",
        ),
        sa.CheckConstraint(
            "event_type IN ('active','superseded')",
            name="ck_scenario_context_activation_type",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_context_activation_scope",
        "forecast_scenario_context_activation_events",
        [
            "retailer_id",
            "tenant_id",
            "capability",
            "environment",
            "event_id",
        ],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_context_activation_prior",
        "forecast_scenario_context_activation_events",
        ["prior_event_id"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_inventory_activation_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _fingerprint("scenario_context_version"),
        _fingerprint("inventory_extension_version"),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("decision_reference", sa.Text(), nullable=False),
        sa.Column("prior_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["scenario_context_version"],
            [f"{SCHEMA}.forecast_scenario_contexts.scenario_context_version"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_extension_version"],
            [
                f"{SCHEMA}.forecast_scenario_inventory_extensions."
                "inventory_extension_version"
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_event_id"],
            [f"{SCHEMA}.forecast_scenario_inventory_activation_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_type IN ('active','superseded')",
            name="ck_scenario_inventory_activation_type",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_inventory_activation_base",
        "forecast_scenario_inventory_activation_events",
        ["scenario_context_version", "event_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_inventory_activation_prior",
        "forecast_scenario_inventory_activation_events",
        ["prior_event_id"],
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.validate_scenario_context_manifest()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            approval {SCHEMA}.forecast_scenario_assumption_approval_events%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT approval
              FROM {SCHEMA}.forecast_scenario_assumption_approval_events
             WHERE event_id = NEW.assumption_approval_event_id;
            IF approval.retailer_id <> NEW.retailer_id
               OR approval.tenant_id <> NEW.tenant_id
               OR approval.capability <> NEW.capability
               OR approval.environment <> NEW.environment
               OR approval.assumption_set_id <> NEW.assumption_set_id
               OR approval.assumption_version <> NEW.assumption_version
               OR approval.assumption_semantic_fingerprint
                    <> NEW.assumption_semantic_fingerprint
               OR approval.approval_semantic_fingerprint
                    <> NEW.assumption_approval_semantic_fingerprint THEN
                RAISE EXCEPTION 'scenario context approval identity mismatch';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM {SCHEMA}.effective_forecast_scenario_assumption_approvals AS effective
                WHERE effective.event_id = NEW.assumption_approval_event_id
                  AND effective.approval_semantic_fingerprint
                      = NEW.assumption_approval_semantic_fingerprint
            ) THEN
                RAISE EXCEPTION 'scenario context requires one effective serving approval head';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_validate_scenario_context_manifest
        BEFORE INSERT ON {SCHEMA}.forecast_scenario_contexts
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.validate_scenario_context_manifest()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.validate_scenario_context_activation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            context_row {SCHEMA}.forecast_scenario_contexts%ROWTYPE;
            prior_row {SCHEMA}.forecast_scenario_context_activation_events%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT context_row
              FROM {SCHEMA}.forecast_scenario_contexts
             WHERE scenario_context_version = NEW.scenario_context_version;
            IF context_row.retailer_id <> NEW.retailer_id
               OR context_row.tenant_id <> NEW.tenant_id
               OR context_row.capability <> NEW.capability
               OR context_row.environment <> NEW.environment
               OR context_row.authority_scope_fingerprint
                    <> NEW.authority_scope_fingerprint THEN
                RAISE EXCEPTION 'scenario context activation scope mismatch';
            END IF;
            IF NEW.event_type = 'active' AND NOT context_row.children_sealed THEN
                RAISE EXCEPTION 'scenario context children are not sealed';
            END IF;
            IF NEW.event_type = 'active' AND EXISTS (
                SELECT 1
                FROM {SCHEMA}.forecast_scenario_commercial_rows AS commercial
                WHERE commercial.scenario_context_version = NEW.scenario_context_version
                  AND commercial.source_cutoff <> context_row.scenario_decision_as_of
            ) THEN
                RAISE EXCEPTION 'scenario commercial evidence uses another decision cutoff';
            END IF;
            IF NEW.prior_event_id IS NOT NULL THEN
                SELECT * INTO STRICT prior_row
                  FROM {SCHEMA}.forecast_scenario_context_activation_events
                 WHERE event_id = NEW.prior_event_id;
                IF prior_row.retailer_id <> NEW.retailer_id
                   OR prior_row.tenant_id <> NEW.tenant_id
                   OR prior_row.capability <> NEW.capability
                   OR prior_row.environment <> NEW.environment
                   OR prior_row.authority_scope_fingerprint
                        <> NEW.authority_scope_fingerprint THEN
                    RAISE EXCEPTION 'prior context event belongs to another authority chain';
                END IF;
            END IF;
            IF NEW.event_type = 'active' AND NOT EXISTS (
                SELECT 1
                FROM {SCHEMA}.effective_forecast_scenario_assumption_approvals AS approval
                WHERE approval.event_id = context_row.assumption_approval_event_id
                  AND approval.retailer_id = NEW.retailer_id
                  AND approval.tenant_id = NEW.tenant_id
                  AND approval.capability = NEW.capability
                  AND approval.environment = NEW.environment
            ) THEN
                RAISE EXCEPTION 'scenario context has no effective approved assumption head';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_validate_scenario_context_activation
        BEFORE INSERT ON {SCHEMA}.forecast_scenario_context_activation_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.validate_scenario_context_activation()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.validate_scenario_inventory_activation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            extension_row {SCHEMA}.forecast_scenario_inventory_extensions%ROWTYPE;
            prior_row {SCHEMA}.forecast_scenario_inventory_activation_events%ROWTYPE;
        BEGIN
            SELECT * INTO STRICT extension_row
              FROM {SCHEMA}.forecast_scenario_inventory_extensions
             WHERE inventory_extension_version = NEW.inventory_extension_version;
            IF extension_row.scenario_context_version <> NEW.scenario_context_version THEN
                RAISE EXCEPTION 'inventory extension belongs to another base context';
            END IF;
            IF NEW.event_type = 'active' AND NOT extension_row.children_sealed THEN
                RAISE EXCEPTION 'inventory extension children are not sealed';
            END IF;
            IF NEW.prior_event_id IS NOT NULL THEN
                SELECT * INTO STRICT prior_row
                  FROM {SCHEMA}.forecast_scenario_inventory_activation_events
                 WHERE event_id = NEW.prior_event_id;
                IF prior_row.scenario_context_version <> NEW.scenario_context_version THEN
                    RAISE EXCEPTION 'prior inventory event belongs to another base context';
                END IF;
            END IF;
            IF NEW.event_type = 'active' AND EXISTS (
                SELECT 1
                FROM {SCHEMA}.forecast_scenario_inventory_node_rows AS node
                LEFT JOIN (
                    SELECT
                        inventory_extension_version,
                        market_id,
                        sku_id,
                        store_id,
                        SUM(allocated_atp_units)::BIGINT AS allocated_atp_units
                    FROM {SCHEMA}.forecast_scenario_inventory_series_rows
                    WHERE inventory_extension_version = NEW.inventory_extension_version
                    GROUP BY inventory_extension_version, market_id, sku_id, store_id
                ) AS series
                  ON series.inventory_extension_version = node.inventory_extension_version
                 AND series.market_id = node.market_id
                 AND series.sku_id = node.sku_id
                 AND series.store_id = node.location_id
                WHERE node.inventory_extension_version = NEW.inventory_extension_version
                  AND COALESCE(series.allocated_atp_units, 0)
                      <> node.allocated_atp_units
            ) THEN
                RAISE EXCEPTION 'inventory extension violates channel ATP conservation';
            END IF;
            IF NEW.event_type = 'active' AND EXISTS (
                SELECT 1
                FROM {SCHEMA}.forecast_scenario_inventory_series_rows AS series
                LEFT JOIN {SCHEMA}.forecast_scenario_inventory_node_rows AS node
                  ON node.inventory_extension_version = series.inventory_extension_version
                 AND node.market_id = series.market_id
                 AND node.sku_id = series.sku_id
                 AND node.location_id = series.store_id
                WHERE series.inventory_extension_version = NEW.inventory_extension_version
                  AND node.inventory_extension_version IS NULL
            ) THEN
                RAISE EXCEPTION 'inventory series row has no node balance';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_validate_scenario_inventory_activation
        BEFORE INSERT ON {SCHEMA}.forecast_scenario_inventory_activation_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.validate_scenario_inventory_activation()
        """
    )

    # Parent manifests are published first and sealed exactly once after their
    # child rows are complete. Child inserts take the same parent-row lock as
    # the seal transition, so no concurrent insert can cross the immutable
    # publication boundary.
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.validate_scenario_publication_child_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            sealed BOOLEAN;
        BEGIN
            IF TG_TABLE_NAME IN (
                'forecast_scenario_horizon_rows',
                'forecast_scenario_commercial_rows'
            ) THEN
                SELECT children_sealed INTO STRICT sealed
                  FROM {SCHEMA}.forecast_scenario_contexts
                 WHERE scenario_context_version = NEW.scenario_context_version
                 FOR UPDATE;
            ELSE
                SELECT children_sealed INTO STRICT sealed
                  FROM {SCHEMA}.forecast_scenario_inventory_extensions
                 WHERE inventory_extension_version = NEW.inventory_extension_version
                 FOR UPDATE;
            END IF;
            IF sealed THEN
                RAISE EXCEPTION 'scenario publication parent is sealed';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.seal_scenario_publication_parent()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND NOT OLD.children_sealed
               AND NEW.children_sealed
               AND (to_jsonb(NEW) - 'children_sealed')
                   = (to_jsonb(OLD) - 'children_sealed') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION '% is append-only after its one seal transition',
                TG_TABLE_NAME;
        END;
        $$
        """
    )
    for parent in (
        "forecast_scenario_contexts",
        "forecast_scenario_inventory_extensions",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{parent}_seal_only
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{parent}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.seal_scenario_publication_parent()
            """
        )
    for child in (
        "forecast_scenario_horizon_rows",
        "forecast_scenario_commercial_rows",
        "forecast_scenario_inventory_series_rows",
        "forecast_scenario_inventory_node_rows",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{child}_sealed_insert
            BEFORE INSERT ON {SCHEMA}.{child}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.validate_scenario_publication_child_insert()
            """
        )

    immutable_tables = (
        "forecast_scenario_horizon_rows",
        "forecast_scenario_commercial_rows",
        "forecast_scenario_inventory_series_rows",
        "forecast_scenario_inventory_node_rows",
        "forecast_scenario_context_activation_events",
        "forecast_scenario_inventory_activation_events",
    )
    for table in immutable_tables:
        _append_only_trigger(table)

    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.forecast_scenario_context_activation_heads AS
        SELECT events.*
        FROM {SCHEMA}.forecast_scenario_context_activation_events AS events
        WHERE NOT EXISTS (
            SELECT 1
            FROM {SCHEMA}.forecast_scenario_context_activation_events AS successor
            WHERE successor.prior_event_id = events.event_id
        )
        """
    )
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.active_forecast_scenario_contexts AS
        SELECT
            contexts.*,
            heads.event_id AS active_event_id,
            heads.recorded_at AS activated_at
        FROM {SCHEMA}.forecast_scenario_context_activation_heads AS heads
        JOIN {SCHEMA}.forecast_scenario_contexts AS contexts
          ON contexts.scenario_context_version = heads.scenario_context_version
         AND contexts.retailer_id = heads.retailer_id
         AND contexts.tenant_id = heads.tenant_id
         AND contexts.capability = heads.capability
         AND contexts.environment = heads.environment
         AND contexts.authority_scope_fingerprint = heads.authority_scope_fingerprint
        JOIN {SCHEMA}.active_forecast_versions AS forecast
          ON forecast.version_id = contexts.forecast_version_id
         AND forecast.activation_scope_fingerprint
             = contexts.forecast_activation_scope_fingerprint
        JOIN {SCHEMA}.effective_forecast_scenario_assumption_approvals AS approval
          ON approval.event_id = contexts.assumption_approval_event_id
         AND approval.approval_semantic_fingerprint
             = contexts.assumption_approval_semantic_fingerprint
         AND approval.assumption_semantic_fingerprint
             = contexts.assumption_semantic_fingerprint
         AND approval.retailer_id = contexts.retailer_id
         AND approval.tenant_id = contexts.tenant_id
         AND approval.capability = contexts.capability
         AND approval.environment = contexts.environment
        WHERE heads.event_type = 'active'
        """
    )
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.forecast_scenario_inventory_activation_heads AS
        SELECT events.*
        FROM {SCHEMA}.forecast_scenario_inventory_activation_events AS events
        WHERE NOT EXISTS (
            SELECT 1
            FROM {SCHEMA}.forecast_scenario_inventory_activation_events AS successor
            WHERE successor.prior_event_id = events.event_id
        )
        """
    )
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.active_forecast_scenario_inventory_extensions AS
        SELECT
            extensions.*,
            heads.event_id AS active_event_id,
            heads.recorded_at AS activated_at
        FROM {SCHEMA}.forecast_scenario_inventory_activation_heads AS heads
        JOIN {SCHEMA}.forecast_scenario_inventory_extensions AS extensions
          ON extensions.inventory_extension_version = heads.inventory_extension_version
         AND extensions.scenario_context_version = heads.scenario_context_version
        JOIN {SCHEMA}.active_forecast_scenario_contexts AS base
          ON base.scenario_context_version = extensions.scenario_context_version
        JOIN {SCHEMA}.active_inventory_versions AS inventory
          ON inventory.inventory_version_id = extensions.inventory_version_id
         AND inventory.forecast_version_id = base.forecast_version_id
        WHERE heads.event_type = 'active'
        """
    )


def downgrade() -> None:
    for view in (
        "active_forecast_scenario_inventory_extensions",
        "forecast_scenario_inventory_activation_heads",
        "active_forecast_scenario_contexts",
        "forecast_scenario_context_activation_heads",
    ):
        op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.{view}")
    for function in (
        "seal_scenario_publication_parent",
        "validate_scenario_publication_child_insert",
        "validate_scenario_inventory_activation",
        "validate_scenario_context_activation",
        "validate_scenario_context_manifest",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{function}() CASCADE")
    for table in (
        "forecast_scenario_inventory_activation_events",
        "forecast_scenario_context_activation_events",
        "forecast_scenario_inventory_node_rows",
        "forecast_scenario_inventory_series_rows",
        "forecast_scenario_inventory_extensions",
        "forecast_scenario_commercial_rows",
        "forecast_scenario_horizon_rows",
        "forecast_scenario_contexts",
    ):
        op.drop_table(table, schema=SCHEMA)
