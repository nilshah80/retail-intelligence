"""Add immutable Forecast Scenario v1 bundles and approval authority.

Decision #96 keeps labelled assumption projection separate from Phase 5 fitted
price response. Bundle values are immutable; approval is an append-only,
branch-visible event chain. A competing head therefore remains visible to the
materializer and fails its exactly-one check instead of being hidden by a
``latest event_id`` query.

Revision ID: 0025_scenario_assumptions
Revises: 0024_warehouse_service_metrics
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_scenario_assumptions"
down_revision: str | Sequence[str] | None = "0024_warehouse_service_metrics"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def _fingerprint(name: str) -> sa.Column:
    return sa.Column(name, sa.String(length=64), nullable=False)


def upgrade() -> None:
    op.create_table(
        "forecast_scenario_assumption_sets",
        sa.Column("assumption_set_id", sa.Text(), nullable=False),
        sa.Column("assumption_version", sa.Text(), nullable=False),
        _fingerprint("semantic_fingerprint"),
        sa.Column("schema_version", sa.Text(), nullable=False),
        sa.Column("artifact_class", sa.Text(), nullable=False),
        sa.Column("serving_eligible", sa.Boolean(), nullable=False),
        sa.Column(
            "children_sealed",
            sa.Boolean(),
            server_default=sa.text("FALSE"),
            nullable=False,
        ),
        sa.Column("projection_basis", sa.Text(), nullable=False),
        sa.Column("evidence_class", sa.Text(), nullable=False),
        sa.Column("statistical_gate_status", sa.Text(), nullable=False),
        sa.Column("disclosure", sa.Text(), nullable=False),
        sa.Column(
            "request_bounds",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "bundle_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("assumption_set_id", "assumption_version"),
        sa.UniqueConstraint(
            "semantic_fingerprint", name="uq_scenario_assumption_fingerprint"
        ),
        sa.UniqueConstraint(
            "assumption_set_id",
            "assumption_version",
            "semantic_fingerprint",
            name="uq_scenario_assumption_identity",
        ),
        sa.CheckConstraint(
            "semantic_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_scenario_assumption_fingerprint",
        ),
        sa.CheckConstraint(
            "schema_version = 'retail-forecast-scenario-assumptions/v1'",
            name="ck_scenario_assumption_schema",
        ),
        sa.CheckConstraint(
            "artifact_class IN ('serving_candidate', 'synthetic_test')",
            name="ck_scenario_assumption_artifact_class",
        ),
        sa.CheckConstraint(
            "(artifact_class = 'serving_candidate' AND serving_eligible) "
            "OR (artifact_class = 'synthetic_test' AND NOT serving_eligible)",
            name="ck_scenario_assumption_serving_eligible",
        ),
        sa.CheckConstraint(
            "projection_basis = 'assumption_set'",
            name="ck_scenario_assumption_projection_basis",
        ),
        sa.CheckConstraint(
            "evidence_class = 'synthetic_scenario'",
            name="ck_scenario_assumption_evidence_class",
        ),
        sa.CheckConstraint(
            "statistical_gate_status = 'not_applicable'",
            name="ck_scenario_assumption_gate_status",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_market_rules",
        _fingerprint("assumption_semantic_fingerprint"),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("minimum_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("maximum_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("candidate_step_minor", sa.BigInteger(), nullable=False),
        sa.Column("grid_origin_minor", sa.BigInteger(), nullable=False),
        sa.Column("rounding_mode", sa.Text(), nullable=False),
        sa.Column("price_freshness_days", sa.Integer(), nullable=False),
        sa.Column("observed_support_window_days", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["assumption_semantic_fingerprint"],
            [f"{SCHEMA}.forecast_scenario_assumption_sets.semantic_fingerprint"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "assumption_semantic_fingerprint", "market_id", "currency_code"
        ),
        sa.UniqueConstraint(
            "assumption_semantic_fingerprint",
            "market_id",
            name="uq_scenario_market_operating_currency",
        ),
        sa.CheckConstraint(
            "minimum_price_minor > 0 AND maximum_price_minor > minimum_price_minor",
            name="ck_scenario_market_price_domain",
        ),
        sa.CheckConstraint(
            "candidate_step_minor > 0 AND grid_origin_minor >= 0",
            name="ck_scenario_market_grid",
        ),
        sa.CheckConstraint(
            "rounding_mode = 'round_half_even'",
            name="ck_scenario_market_rounding",
        ),
        sa.CheckConstraint(
            "price_freshness_days > 0 AND observed_support_window_days > 0",
            name="ck_scenario_market_windows",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_tier_coefficients",
        _fingerprint("assumption_semantic_fingerprint"),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("dept_id", sa.Text(), nullable=False),
        sa.Column("baseline_price_tier", sa.Text(), nullable=False),
        sa.Column("lower_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("upper_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("assumed_beta", sa.Numeric(18, 9), nullable=False),
        sa.Column(
            "competitor_stockout_sensitivity", sa.Numeric(18, 9), nullable=False
        ),
        sa.Column(
            "competitor_promotion_sensitivity", sa.Numeric(18, 9), nullable=False
        ),
        sa.Column("weather_positive_sensitivity", sa.Numeric(18, 9), nullable=False),
        sa.Column("weather_negative_sensitivity", sa.Numeric(18, 9), nullable=False),
        sa.ForeignKeyConstraint(
            ["assumption_semantic_fingerprint"],
            [f"{SCHEMA}.forecast_scenario_assumption_sets.semantic_fingerprint"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "assumption_semantic_fingerprint",
            "market_id",
            "dept_id",
            "baseline_price_tier",
        ),
        sa.UniqueConstraint(
            "assumption_semantic_fingerprint",
            "market_id",
            "dept_id",
            "lower_price_minor",
            name="uq_scenario_tier_lower_bound",
        ),
        sa.CheckConstraint(
            "lower_price_minor > 0 "
            "AND (upper_price_minor IS NULL OR upper_price_minor > lower_price_minor)",
            name="ck_scenario_tier_price_band",
        ),
        sa.CheckConstraint("assumed_beta < 0", name="ck_scenario_tier_beta"),
        sa.CheckConstraint(
            "competitor_stockout_sensitivity >= 0 "
            "AND competitor_stockout_sensitivity < 1 "
            "AND competitor_promotion_sensitivity >= 0 "
            "AND competitor_promotion_sensitivity < 1 "
            "AND weather_positive_sensitivity >= 0 "
            "AND weather_positive_sensitivity < 1 "
            "AND weather_negative_sensitivity >= 0 "
            "AND weather_negative_sensitivity < 1",
            name="ck_scenario_tier_positive_factors",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_tier_resolution",
        "forecast_scenario_tier_coefficients",
        [
            "assumption_semantic_fingerprint",
            "market_id",
            "dept_id",
            "lower_price_minor",
            "upper_price_minor",
        ],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_presets",
        _fingerprint("assumption_semantic_fingerprint"),
        sa.Column("preset_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("demand_adjustment_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("price_change_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("promotion_uplift_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("competitor_availability", sa.Text(), nullable=False),
        sa.Column("weather_event", sa.Text(), nullable=False),
        sa.Column("atp_adjustment", sa.Numeric(9, 6), nullable=False),
        sa.ForeignKeyConstraint(
            ["assumption_semantic_fingerprint"],
            [f"{SCHEMA}.forecast_scenario_assumption_sets.semantic_fingerprint"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("assumption_semantic_fingerprint", "preset_id"),
        sa.CheckConstraint(
            "preset_id IN "
            "('expected_demand','high_demand','low_demand',"
            "'promotion_upside','supply_constrained')",
            name="ck_scenario_preset_id",
        ),
        sa.CheckConstraint(
            "price_change_pct BETWEEN -5 AND 5",
            name="ck_scenario_preset_price_change",
        ),
        sa.CheckConstraint(
            "competitor_availability IN ('normal','stockout','promotion')",
            name="ck_scenario_preset_competitor",
        ),
        sa.CheckConstraint(
            "weather_event IN ('normal','positive','negative')",
            name="ck_scenario_preset_weather",
        ),
        sa.CheckConstraint(
            "atp_adjustment BETWEEN -1 AND 0",
            name="ck_scenario_preset_atp",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_scenario_assumption_approval_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("assumption_set_id", sa.Text(), nullable=False),
        sa.Column("assumption_version", sa.Text(), nullable=False),
        _fingerprint("assumption_semantic_fingerprint"),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("decision_reference", sa.Text(), nullable=False),
        _fingerprint("approval_semantic_fingerprint"),
        sa.Column("prior_event_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
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
        sa.ForeignKeyConstraint(
            ["prior_event_id"],
            [f"{SCHEMA}.forecast_scenario_assumption_approval_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "approval_semantic_fingerprint",
            name="uq_scenario_approval_semantic_fingerprint",
        ),
        sa.CheckConstraint(
            "capability = 'forecast_scenario_v1'",
            name="ck_scenario_approval_capability",
        ),
        sa.CheckConstraint(
            "event_type IN ('candidate','approved','superseded','rejected')",
            name="ck_scenario_approval_event_type",
        ),
        sa.CheckConstraint(
            "assumption_semantic_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND approval_semantic_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_scenario_approval_fingerprints",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_approval_head",
        "forecast_scenario_assumption_approval_events",
        [
            "retailer_id",
            "tenant_id",
            "capability",
            "environment",
            "assumption_semantic_fingerprint",
            "event_id",
        ],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_scenario_approval_prior_event",
        "forecast_scenario_assumption_approval_events",
        ["prior_event_id"],
        schema=SCHEMA,
    )

    # Shared by this and the context migration. Immutable authority history is
    # not a convention: PostgreSQL refuses updates and deletes.
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.reject_append_only_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.validate_scenario_approval_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            prior_row {SCHEMA}.forecast_scenario_assumption_approval_events%ROWTYPE;
            bundle_serving_eligible BOOLEAN;
            bundle_artifact_class TEXT;
            bundle_children_sealed BOOLEAN;
        BEGIN
            SELECT serving_eligible, artifact_class, children_sealed
              INTO bundle_serving_eligible, bundle_artifact_class,
                   bundle_children_sealed
              FROM {SCHEMA}.forecast_scenario_assumption_sets
             WHERE assumption_set_id = NEW.assumption_set_id
               AND assumption_version = NEW.assumption_version
               AND semantic_fingerprint = NEW.assumption_semantic_fingerprint;

            IF NEW.event_type = 'approved'
               AND (NOT bundle_serving_eligible
                    OR bundle_artifact_class <> 'serving_candidate'
                    OR NOT bundle_children_sealed) THEN
                RAISE EXCEPTION 'bundle % cannot receive serving approval',
                    NEW.assumption_semantic_fingerprint;
            END IF;

            IF NEW.prior_event_id IS NOT NULL THEN
                SELECT * INTO STRICT prior_row
                  FROM {SCHEMA}.forecast_scenario_assumption_approval_events
                 WHERE event_id = NEW.prior_event_id;
                IF prior_row.retailer_id <> NEW.retailer_id
                   OR prior_row.tenant_id <> NEW.tenant_id
                   OR prior_row.capability <> NEW.capability
                   OR prior_row.environment <> NEW.environment
                   OR prior_row.assumption_semantic_fingerprint
                      <> NEW.assumption_semantic_fingerprint THEN
                    RAISE EXCEPTION 'prior approval event belongs to another authority chain';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_validate_scenario_approval_insert
        BEFORE INSERT ON {SCHEMA}.forecast_scenario_assumption_approval_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.validate_scenario_approval_event()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_scenario_approval_append_only
        BEFORE UPDATE OR DELETE
        ON {SCHEMA}.forecast_scenario_assumption_approval_events
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_append_only_mutation()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.validate_scenario_assumption_child_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            sealed BOOLEAN;
        BEGIN
            SELECT children_sealed INTO STRICT sealed
              FROM {SCHEMA}.forecast_scenario_assumption_sets
             WHERE semantic_fingerprint = NEW.assumption_semantic_fingerprint
             FOR UPDATE;
            IF sealed THEN
                RAISE EXCEPTION 'assumption bundle % is sealed',
                    NEW.assumption_semantic_fingerprint;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE FUNCTION {SCHEMA}.seal_scenario_assumption_set()
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
    op.execute(
        f"""
        CREATE TRIGGER trg_scenario_assumption_set_seal_only
        BEFORE UPDATE OR DELETE
        ON {SCHEMA}.forecast_scenario_assumption_sets
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.seal_scenario_assumption_set()
        """
    )
    for table in (
        "forecast_scenario_market_rules",
        "forecast_scenario_tier_coefficients",
        "forecast_scenario_presets",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_sealed_insert
            BEFORE INSERT ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.validate_scenario_assumption_child_insert()
            """
        )
    for table in (
        "forecast_scenario_market_rules",
        "forecast_scenario_tier_coefficients",
        "forecast_scenario_presets",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_append_only_mutation()
            """
        )

    # A chain head is an event with no child, not merely the greatest event id.
    # Forked histories therefore return multiple heads and fail the consumer's
    # exactly-one cardinality check.
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.forecast_scenario_assumption_approval_heads AS
        SELECT events.*
        FROM {SCHEMA}.forecast_scenario_assumption_approval_events AS events
        WHERE NOT EXISTS (
            SELECT 1
            FROM {SCHEMA}.forecast_scenario_assumption_approval_events AS successor
            WHERE successor.prior_event_id = events.event_id
        )
        """
    )
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.effective_forecast_scenario_assumption_approvals AS
        SELECT
            events.event_id,
            events.retailer_id,
            events.tenant_id,
            events.capability,
            events.environment,
            events.assumption_set_id,
            events.assumption_version,
            events.assumption_semantic_fingerprint,
            events.approval_semantic_fingerprint,
            events.actor,
            events.decision_reference,
            events.recorded_at
        FROM {SCHEMA}.forecast_scenario_assumption_approval_heads AS events
        JOIN {SCHEMA}.forecast_scenario_assumption_sets AS bundles
          ON bundles.assumption_set_id = events.assumption_set_id
         AND bundles.assumption_version = events.assumption_version
         AND bundles.semantic_fingerprint = events.assumption_semantic_fingerprint
        WHERE events.event_type = 'approved'
          AND bundles.artifact_class = 'serving_candidate'
          AND bundles.serving_eligible
          AND NOT EXISTS (
              SELECT 1
              FROM {SCHEMA}.forecast_scenario_assumption_approval_heads AS competing
              WHERE competing.retailer_id = events.retailer_id
                AND competing.tenant_id = events.tenant_id
                AND competing.capability = events.capability
                AND competing.environment = events.environment
                AND competing.assumption_semantic_fingerprint
                    = events.assumption_semantic_fingerprint
                AND competing.event_id <> events.event_id
          )
        """
    )


def downgrade() -> None:
    op.execute(
        f"DROP VIEW IF EXISTS {SCHEMA}.effective_forecast_scenario_assumption_approvals"
    )
    op.execute(
        f"DROP VIEW IF EXISTS {SCHEMA}.forecast_scenario_assumption_approval_heads"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_scenario_approval_append_only "
        f"ON {SCHEMA}.forecast_scenario_assumption_approval_events"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_validate_scenario_approval_insert "
        f"ON {SCHEMA}.forecast_scenario_assumption_approval_events"
    )
    op.execute(
        f"DROP TRIGGER IF EXISTS trg_scenario_assumption_set_seal_only "
        f"ON {SCHEMA}.forecast_scenario_assumption_sets"
    )
    for table in (
        "forecast_scenario_market_rules",
        "forecast_scenario_tier_coefficients",
        "forecast_scenario_presets",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_sealed_insert ON {SCHEMA}.{table}"
        )
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {SCHEMA}.{table}"
        )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.seal_scenario_assumption_set()")
    op.execute(
        f"DROP FUNCTION IF EXISTS {SCHEMA}.validate_scenario_assumption_child_insert()"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.validate_scenario_approval_event()")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.reject_append_only_mutation()")
    for table in (
        "forecast_scenario_assumption_approval_events",
        "forecast_scenario_presets",
        "forecast_scenario_tier_coefficients",
        "forecast_scenario_market_rules",
        "forecast_scenario_assumption_sets",
    ):
        op.drop_table(table, schema=SCHEMA)
