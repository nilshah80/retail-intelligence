"""Inventory & replenishment serving: versions, materializations, activation and
read projections.

`P4-8` task 2. The lifecycle mirrors the forecast chain deliberately -- the
version/materialization/activation split is the part of that design that was
hard-won, and diverging from it would mean relearning its lessons:

* a VERSION row exists only for an accepted run (CHECK, like forecast);
* MATERIALIZATION is transactional and idempotent by run id;
* ACTIVATION is append-only with `prior_event_id` supersession chaining, and
  exactly one version may be active for the P4-D15 product-bundle scope --
  enforced by a partial unique index rather than by writer discipline;
* the ACTIVE VIEW refuses stale lineage: it returns the active inventory version
  only while the forecast authority it consumed is still THE active forecast
  under decision #90. An inventory number computed from a superseded forecast is
  stale by definition, and this is where that staleness becomes 409 rather than
  a quietly wrong screen.

Read projections are one table per run artifact, keyed to the version so
materialization can be verified row-for-row against the bundle.

Revision ID: 0010_inventory_serving
Revises: 0009_forecast_interval_contract
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_inventory_serving"
down_revision: str | Sequence[str] | None = "0009_forecast_interval_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    op.create_table(
        "inventory_materializations",
        sa.Column("inventory_run_id", sa.Text(), primary_key=True),
        sa.Column("run_semantic_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_selection_id", sa.Text(), nullable=False),
        sa.Column(
            "publication_semantic_fingerprint", sa.String(64), nullable=False
        ),
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("forecast_version_id", sa.Text(), nullable=False),
        sa.Column("policy_version", sa.Text(), nullable=False),
        sa.Column("verifier_policy_id", sa.Text(), nullable=False),
        sa.Column("verifier_verdict", sa.Text(), nullable=False),
        sa.Column(
            "materialized_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        # Materialization requires an independent verification, not the run's
        # opinion of itself.
        sa.CheckConstraint(
            "verifier_verdict = 'verified'",
            name="ck_inventory_materialization_verified",
        ),
        sa.CheckConstraint(
            "verifier_policy_id = 'retail-inventory-verifier/v1'",
            name="ck_inventory_materialization_verifier_policy",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "inventory_versions",
        sa.Column("inventory_version_id", sa.Text(), primary_key=True),
        sa.Column("inventory_run_id", sa.Text(), nullable=False, unique=True),
        sa.Column("decision_as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("markets", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("lifecycle_status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status = 'accepted'",
            name="ck_inventory_version_accepted",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_run_id"],
            [f"{SCHEMA}.inventory_materializations.inventory_run_id"],
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )
    op.create_table(
        "inventory_activation_events",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        sa.Column("inventory_version_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("prior_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ('active', 'superseded')",
            name="ck_inventory_activation_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_version_id"],
            [f"{SCHEMA}.inventory_versions.inventory_version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["prior_event_id"],
            [f"{SCHEMA}.inventory_activation_events.event_id"],
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    # One active inventory version, total -- the P4-D15 bundle scope is the whole
    # product surface, so the uniqueness needs no scope column at all. A partial
    # unique index makes the invariant a property of the database rather than of
    # writer discipline; the forecast chain learned this after three republishes
    # activated without superseding their predecessors.
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.active_inventory_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE,
            active_event_id BIGINT NOT NULL
                REFERENCES {SCHEMA}.inventory_activation_events(event_id),
            CONSTRAINT ck_active_inventory_singleton CHECK (singleton)
        )
        """
    )

    # Read projections: one table per artifact, keyed to the version.
    projection_columns: dict[str, list[sa.Column]] = {
        "inventory_positions": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("location_kind", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("on_hand_units", sa.BigInteger(), nullable=False),
            sa.Column("committed_units", sa.BigInteger(), nullable=False),
            sa.Column("reserved_units", sa.BigInteger(), nullable=False),
            sa.Column("damaged_units", sa.BigInteger(), nullable=False),
            sa.Column("on_order_units", sa.BigInteger(), nullable=False),
            sa.Column("in_transit_units", sa.BigInteger(), nullable=False),
            sa.Column("atp_units", sa.BigInteger(), nullable=False),
            sa.Column("assortment_active", sa.Boolean(), nullable=False),
            sa.Column("residual_only", sa.Boolean(), nullable=False),
        ],
        "inventory_stock_health": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("health_class", sa.Text(), nullable=False),
            sa.Column("cover_days", sa.Numeric(12, 2), nullable=True),
            sa.Column("reason_code", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "health_class IN "
                "('stockout','understock','healthy','overstock','dead')",
                name="ck_stock_health_class",
            ),
            # Frozen truth table: a numeric cover has no reason, an absent cover
            # names one. The same shape 0009 gave the interval.
            sa.CheckConstraint(
                "(cover_days IS NULL) = (reason_code IS NOT NULL)",
                name="ck_stock_health_cover_reason",
            ),
        ],
        "inventory_demand_at_risk": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("channel_id", sa.Text(), nullable=False),
            sa.Column("risk_units", sa.Numeric(18, 4), nullable=True),
            sa.Column("risk_value_minor", sa.BigInteger(), nullable=True),
            sa.Column("currency_code", sa.Text(), nullable=True),
            sa.Column("interval_available", sa.Boolean(), nullable=False),
            sa.Column("reason_code", sa.Text(), nullable=True),
            # Decision #92 end to end: an unassessed row carries NO risk number
            # and a governed reason; an assessed row carries the number and no
            # reason. Zero-from-null cannot be stored.
            sa.CheckConstraint(
                "interval_available = (risk_units IS NOT NULL)",
                name="ck_demand_risk_availability",
            ),
            sa.CheckConstraint(
                "interval_available OR reason_code IS NOT NULL",
                name="ck_demand_risk_reason",
            ),
        ],
        "inventory_ageing": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("age_bucket", sa.Text(), nullable=False),
            sa.Column("on_hand_units", sa.BigInteger(), nullable=False),
            sa.Column("action", sa.Text(), nullable=False),
            sa.Column("markdown_pct", sa.Numeric(6, 4), nullable=True),
            sa.Column("residual_only", sa.Boolean(), nullable=False),
        ],
        "inventory_expiry_waste": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("expiring_units", sa.BigInteger(), nullable=False),
            sa.Column("expired_units", sa.BigInteger(), nullable=False),
            sa.Column("waste_units", sa.BigInteger(), nullable=False),
            sa.Column("exposure_minor", sa.BigInteger(), nullable=True),
            sa.Column("currency_code", sa.Text(), nullable=True),
        ],
        "inventory_valuation": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("category", sa.Text(), nullable=False),
            sa.Column("gross_value_minor", sa.BigInteger(), nullable=True),
            sa.Column("currency_code", sa.Text(), nullable=False),
            sa.Column("cost_method", sa.Text(), nullable=True),
            sa.Column("cost_reason_code", sa.Text(), nullable=True),
            sa.Column("wms_variance_units", sa.BigInteger(), nullable=True),
            sa.CheckConstraint(
                "(gross_value_minor IS NULL) = (cost_reason_code IS NOT NULL)",
                name="ck_valuation_cost_reason",
            ),
        ],
        "replenishment_recommendations": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("destination_location_id", sa.Text(), nullable=False),
            sa.Column("supply_location_id", sa.Text(), nullable=True),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("recommended_units", sa.BigInteger(), nullable=True),
            sa.Column("reorder_point_units", sa.Numeric(18, 4), nullable=True),
            sa.Column("order_up_to_units", sa.Numeric(18, 4), nullable=True),
            sa.Column("interval_available", sa.Boolean(), nullable=False),
            sa.Column("reason_code", sa.Text(), nullable=True),
            sa.Column("erp_status", sa.Text(), nullable=False),
            sa.CheckConstraint(
                "erp_status = 'shadow_not_sent'",
                name="ck_replenishment_erp_shadow",
            ),
            sa.CheckConstraint(
                "interval_available OR recommended_units IS NULL",
                name="ck_replenishment_interval_gate",
            ),
        ],
        "replenishment_safety_stock": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("abc_class", sa.Text(), nullable=True),
            sa.Column("service_level", sa.Numeric(6, 4), nullable=True),
            sa.Column("safety_stock_units", sa.Numeric(18, 4), nullable=True),
            sa.Column("interval_available", sa.Boolean(), nullable=False),
            sa.Column("reason_code", sa.Text(), nullable=True),
            sa.CheckConstraint(
                "interval_available = (safety_stock_units IS NOT NULL)",
                name="ck_safety_stock_availability",
            ),
        ],
        "replenishment_transfers": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("lane_id", sa.Text(), nullable=False),
            sa.Column("from_location_id", sa.Text(), nullable=False),
            sa.Column("to_location_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("units", sa.BigInteger(), nullable=False),
            sa.Column("expected_benefit_minor", sa.BigInteger(), nullable=False),
            sa.Column("currency_code", sa.Text(), nullable=False),
            sa.Column("transit_days", sa.Integer(), nullable=False),
        ],
        "replenishment_allocations": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=False),
            sa.Column("channel_id", sa.Text(), nullable=False),
            sa.Column("sku_id", sa.Text(), nullable=False),
            sa.Column("requested_units", sa.BigInteger(), nullable=False),
            sa.Column("allocated_units", sa.BigInteger(), nullable=False),
            sa.Column("shortfall_units", sa.BigInteger(), nullable=False),
        ],
        "replenishment_suppliers": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("supplier_id", sa.Text(), nullable=False),
            sa.Column("otd_rate", sa.Numeric(6, 4), nullable=True),
            sa.Column("lead_time_mean_days", sa.Numeric(8, 2), nullable=True),
            sa.Column("lead_time_std_days", sa.Numeric(8, 2), nullable=True),
            sa.Column("capacity_confirmed_pct", sa.Numeric(6, 4), nullable=True),
            sa.Column("risk_class", sa.Text(), nullable=True),
            sa.Column("reason_codes", sa.ARRAY(sa.Text()), nullable=True),
        ],
        "replenishment_exceptions": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("location_id", sa.Text(), nullable=True),
            sa.Column("sku_id", sa.Text(), nullable=True),
            sa.Column("channel_id", sa.Text(), nullable=True),
            sa.Column("exception_class", sa.Text(), nullable=False),
            sa.Column("severity", sa.Text(), nullable=False),
            sa.Column("reason_code", sa.Text(), nullable=True),
            sa.Column("evidence", sa.Text(), nullable=False),
        ],
        "inventory_replay_metrics": [
            sa.Column("market_id", sa.Text(), nullable=False),
            sa.Column("metric", sa.Text(), nullable=False),
            sa.Column("cohort", sa.Text(), nullable=False),
            sa.Column("candidate_value", sa.Text(), nullable=False),
            sa.Column("incumbent_value", sa.Text(), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False),
        ],
    }
    for table_name, columns in projection_columns.items():
        op.create_table(
            table_name,
            sa.Column("inventory_version_id", sa.Text(), nullable=False),
            *columns,
            sa.ForeignKeyConstraint(
                ["inventory_version_id"],
                [f"{SCHEMA}.inventory_versions.inventory_version_id"],
                ondelete="RESTRICT",
            ),
            schema=SCHEMA,
        )
        op.create_index(
            f"ix_{table_name}_version",
            table_name,
            ["inventory_version_id", "market_id"],
            schema=SCHEMA,
        )

    # The fail-closed active view. Its second join is the point: the inventory
    # version is servable only while the forecast it consumed is STILL the one
    # active forecast. Nothing here selects "latest"; either the joins hold or
    # the view is empty and the API returns the governed state.
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.active_inventory_versions AS
        SELECT
            versions.inventory_version_id,
            versions.inventory_run_id,
            versions.decision_as_of,
            versions.markets,
            materializations.run_semantic_fingerprint,
            materializations.source_selection_id,
            materializations.publication_semantic_fingerprint,
            materializations.forecast_run_id,
            materializations.forecast_version_id,
            materializations.policy_version,
            events.event_id AS active_event_id,
            events.recorded_at AS activated_at
        FROM {SCHEMA}.active_inventory_state AS state
        JOIN {SCHEMA}.inventory_activation_events AS events
          ON events.event_id = state.active_event_id
         AND events.event_type = 'active'
        JOIN {SCHEMA}.inventory_versions AS versions
          ON versions.inventory_version_id = events.inventory_version_id
        JOIN {SCHEMA}.inventory_materializations AS materializations
          ON materializations.inventory_run_id = versions.inventory_run_id
        JOIN {SCHEMA}.active_forecast_versions AS forecast
          ON forecast.forecast_run_id = materializations.forecast_run_id
         AND forecast.version_id = materializations.forecast_version_id
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.active_inventory_versions")
    for table_name in (
        "inventory_replay_metrics",
        "replenishment_exceptions",
        "replenishment_suppliers",
        "replenishment_allocations",
        "replenishment_transfers",
        "replenishment_safety_stock",
        "replenishment_recommendations",
        "inventory_valuation",
        "inventory_expiry_waste",
        "inventory_ageing",
        "inventory_demand_at_risk",
        "inventory_stock_health",
        "inventory_positions",
    ):
        op.drop_table(table_name, schema=SCHEMA)
    op.execute(f"DROP TABLE {SCHEMA}.active_inventory_state")
    op.drop_table("inventory_activation_events", schema=SCHEMA)
    op.drop_table("inventory_versions", schema=SCHEMA)
    op.drop_table("inventory_materializations", schema=SCHEMA)
