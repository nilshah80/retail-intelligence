"""Add immutable pricing-intelligence serving projections.

Pricing bundles are verified and materialized independently of activation.  A
separate append-only activation event plus the scoped active pointer makes the
current read authority explicit without turning materialization into serving.

Revision ID: 0028_pricing_serving
Revises: 0027_scenario_hardening
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_pricing_serving"
down_revision: str | Sequence[str] | None = "0027_scenario_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def _scope_columns() -> list[sa.Column]:
    return [
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
    ]


def _bundle_foreign_key() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["bundle_id"],
        [f"{SCHEMA}.pricing_materializations.bundle_id"],
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    op.create_table(
        "pricing_materializations",
        sa.Column("bundle_id", sa.Text(), primary_key=True),
        sa.Column("bundle_kind", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.Text(), nullable=False, unique=True),
        sa.Column("semantic_fingerprint", sa.Text(), nullable=False, unique=True),
        sa.Column("decision_as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("source_publication_fingerprint", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.Text(), nullable=False),
        sa.Column("input_authority_id", sa.Text(), nullable=False),
        sa.Column("verifier_contract", sa.Text(), nullable=False),
        sa.Column("verifier_record_sha256", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("artifact_inventory", sa.JSON(), nullable=False),
        sa.Column(
            "materialized_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "bundle_kind IN ('response_rich', 'evidence_sparse')",
            name="ck_pricing_materialization_kind",
        ),
        sa.CheckConstraint(
            "verifier_contract = 'retail-pricing-bundle-verification/v1'",
            name="ck_pricing_materialization_verifier",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_response_assessments",
        sa.Column("bundle_id", sa.Text(), nullable=False),
        *_scope_columns(),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("first_failure_reason", sa.Text(), nullable=True),
        sa.Column("current_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency_code", sa.Text(), nullable=True),
        sa.Column("shrunk_beta", sa.Numeric(20, 10), nullable=True),
        sa.Column("confidence", sa.Numeric(12, 10), nullable=True),
        sa.Column("support_min_minor", sa.BigInteger(), nullable=True),
        sa.Column("support_max_minor", sa.BigInteger(), nullable=True),
        sa.Column("assessment", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bundle_id", "market_id", "sku_id", "store_id", "channel_id",
            name="pk_pricing_response_assessments",
        ),
        _bundle_foreign_key(),
        sa.CheckConstraint(
            "disposition <> 'accepted' OR "
            "(shrunk_beta IS NOT NULL AND confidence IS NOT NULL)",
            name="ck_pricing_response_acceptance_values",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "price_recommendations",
        sa.Column("bundle_id", sa.Text(), nullable=False),
        sa.Column("recommendation_id", sa.Text(), nullable=False),
        *_scope_columns(),
        sa.Column("record_kind", sa.Text(), nullable=False),
        sa.Column("selectable", sa.Boolean(), nullable=False),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("disposition", sa.Text(), nullable=False),
        sa.Column("first_failure_reason", sa.Text(), nullable=True),
        sa.Column("current_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("proposed_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency_code", sa.Text(), nullable=True),
        sa.Column("expected_units_current", sa.Numeric(24, 8), nullable=True),
        sa.Column("expected_units_proposed", sa.Numeric(24, 8), nullable=True),
        sa.Column("revenue_impact_minor", sa.BigInteger(), nullable=True),
        sa.Column("margin_impact_minor", sa.BigInteger(), nullable=True),
        sa.Column("margin_reason_code", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(12, 10), nullable=True),
        sa.Column("priority", sa.Text(), nullable=False),
        sa.Column("risk", sa.Text(), nullable=False),
        sa.Column("stock_cover_days", sa.Numeric(18, 4), nullable=True),
        sa.Column("competitor_price_minor", sa.BigInteger(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bundle_id", "recommendation_id",
            name="pk_price_recommendations",
        ),
        sa.UniqueConstraint(
            "bundle_id", "market_id", "sku_id", "store_id", "channel_id",
            name="uq_price_recommendation_scope",
        ),
        _bundle_foreign_key(),
        sa.CheckConstraint(
            "record_kind IN ('recommendation', 'withheld_assessment')",
            name="ck_price_recommendation_record_kind",
        ),
        sa.CheckConstraint(
            "(record_kind = 'recommendation') = selectable",
            name="ck_price_recommendation_selectability",
        ),
        sa.CheckConstraint(
            "(record_kind = 'recommendation') OR "
            "(action IS NULL AND proposed_price_minor IS NULL "
            "AND revenue_impact_minor IS NULL AND margin_impact_minor IS NULL)",
            name="ck_withheld_recommendation_values",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_price_candidates",
        sa.Column("bundle_id", sa.Text(), nullable=False),
        *_scope_columns(),
        sa.Column("candidate_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("expected_units", sa.Numeric(24, 8), nullable=False),
        sa.Column("expected_revenue_minor", sa.BigInteger(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bundle_id", "market_id", "sku_id", "store_id", "channel_id",
            "candidate_price_minor", name="pk_pricing_price_candidates",
        ),
        _bundle_foreign_key(),
        sa.CheckConstraint(
            "eligible = (rejection_reason IS NULL)",
            name="ck_pricing_candidate_eligibility_reason",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_competitor_assessments",
        sa.Column("bundle_id", sa.Text(), nullable=False),
        sa.Column("match_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("competitor_id", sa.Text(), nullable=False),
        sa.Column("competitor_product_id", sa.Text(), nullable=False),
        sa.Column("geo_scope_type", sa.Text(), nullable=False),
        sa.Column("geo_scope_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("known_as_of", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency_code", sa.Text(), nullable=True),
        sa.Column("availability_state", sa.Text(), nullable=True),
        sa.Column("match_confidence", sa.Numeric(12, 10), nullable=False),
        sa.Column("match_status", sa.Text(), nullable=False),
        sa.Column("freshness", sa.Text(), nullable=False),
        sa.Column("bound_eligible", sa.Boolean(), nullable=False),
        sa.Column("first_exclusion_reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bundle_id", "match_id", "geo_scope_type", "geo_scope_id",
            "observed_at", name="pk_pricing_competitor_assessments",
        ),
        _bundle_foreign_key(),
        sa.CheckConstraint(
            "match_status IN ('Matched', 'Needs Review', 'Rejected', 'No Match')",
            name="ck_competitor_match_status",
        ),
        sa.CheckConstraint(
            "freshness IN ('Fresh', 'Near threshold', 'Stale')",
            name="ck_competitor_freshness",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_promotion_protection",
        sa.Column("bundle_id", sa.Text(), nullable=False),
        *_scope_columns(),
        sa.Column("guard_status", sa.Text(), nullable=False),
        sa.Column("first_failure_reason", sa.Text(), nullable=True),
        sa.Column("selected_precedence", sa.Text(), nullable=True),
        sa.Column("applicable_promotion_ids", sa.JSON(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint(
            "bundle_id", "market_id", "sku_id", "store_id", "channel_id",
            name="pk_pricing_promotion_protection",
        ),
        _bundle_foreign_key(),
        sa.CheckConstraint(
            "guard_status IN ('missing', 'no_overlap', 'applicable', 'conflict')",
            name="ck_promotion_guard_status",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_promotion_dispositions",
        sa.Column("bundle_id", sa.Text(), primary_key=True),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("decision_disposition", sa.Text(), nullable=False),
        sa.Column("package_disposition", sa.Text(), nullable=False),
        sa.Column("planner_available", sa.Boolean(), nullable=False),
        sa.Column("first_failure_reason", sa.Text(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        _bundle_foreign_key(),
        sa.CheckConstraint(
            "decision_id = 53 AND decision_disposition = 'not_amended' "
            "AND package_disposition = 'negative' AND NOT planner_available",
            name="ck_promotion_planner_negative_disposition",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_result_selection_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("selection_id", sa.Text(), nullable=False),
        sa.Column("lifecycle_status", sa.Text(), nullable=False),
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("bundle_id", sa.Text(), nullable=False),
        sa.Column("predecessor_event_id", sa.BigInteger(), nullable=True),
        sa.Column("review_actor", sa.Text(), nullable=False),
        sa.Column("review_evidence", sa.JSON(), nullable=False),
        sa.Column(
            "recorded_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        _bundle_foreign_key(),
        sa.ForeignKeyConstraint(
            ["predecessor_event_id"],
            [f"{SCHEMA}.pricing_result_selection_events.event_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "selection_id", "lifecycle_status",
            name="uq_pricing_selection_lifecycle",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('candidate', 'approved', 'active', 'refused', 'superseded')",
            name="ck_pricing_selection_lifecycle",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_activation_sets",
        sa.Column("activation_event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("activation_set_id", sa.Text(), nullable=False, unique=True),
        sa.Column("bundle_id", sa.Text(), nullable=False),
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("selection_ids", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("predecessor_activation_event_id", sa.BigInteger(), nullable=True),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "recorded_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        _bundle_foreign_key(),
        sa.ForeignKeyConstraint(
            ["predecessor_activation_event_id"],
            [f"{SCHEMA}.pricing_activation_sets.activation_event_id"],
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "pricing_active_state",
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("environment", sa.Text(), nullable=False),
        sa.Column("activation_event_id", sa.BigInteger(), nullable=False, unique=True),
        sa.PrimaryKeyConstraint(
            "retailer_id", "tenant_id", "environment",
            name="pk_pricing_active_state",
        ),
        sa.ForeignKeyConstraint(
            ["activation_event_id"],
            [f"{SCHEMA}.pricing_activation_sets.activation_event_id"],
            ondelete="RESTRICT",
        ),
        schema=SCHEMA,
    )

    for table in (
        "pricing_response_assessments",
        "price_recommendations",
        "pricing_price_candidates",
        "pricing_competitor_assessments",
        "pricing_promotion_protection",
    ):
        op.create_index(
            f"ix_{table}_scope",
            table,
            ["bundle_id", "market_id", "sku_id"],
            schema=SCHEMA,
        )
    op.create_index(
        "ix_price_recommendations_filters",
        "price_recommendations",
        ["bundle_id", "store_id", "record_kind", "action", "priority"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_competitor_assessments_queue",
        "pricing_competitor_assessments",
        ["bundle_id", "match_status", "freshness", "competitor_id"],
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.active_pricing_bundles AS
        SELECT
            state.retailer_id,
            state.tenant_id,
            state.environment,
            activation.activation_event_id,
            activation.activation_set_id,
            activation.selection_ids,
            materialization.*
        FROM {SCHEMA}.pricing_active_state AS state
        JOIN {SCHEMA}.pricing_activation_sets AS activation
          ON activation.activation_event_id = state.activation_event_id
         AND activation.retailer_id = state.retailer_id
         AND activation.tenant_id = state.tenant_id
         AND activation.environment = state.environment
        JOIN {SCHEMA}.pricing_materializations AS materialization
          ON materialization.bundle_id = activation.bundle_id
        WHERE materialization.bundle_kind = 'response_rich'
        """
    )
    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.current_price_recommendations AS
        SELECT recommendation.*, active.retailer_id, active.tenant_id,
               active.environment, active.activation_set_id,
               active.decision_as_of, active.source_publication_fingerprint
        FROM {SCHEMA}.price_recommendations AS recommendation
        JOIN {SCHEMA}.active_pricing_bundles AS active
          ON active.bundle_id = recommendation.bundle_id
        """
    )

    immutable_tables = (
        "pricing_materializations",
        "pricing_response_assessments",
        "price_recommendations",
        "pricing_price_candidates",
        "pricing_competitor_assessments",
        "pricing_promotion_protection",
        "pricing_promotion_dispositions",
        "pricing_result_selection_events",
        "pricing_activation_sets",
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {SCHEMA}.reject_pricing_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END;
        $$
        """
    )
    for table in immutable_tables:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
            FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.reject_pricing_mutation()
            """
        )


def downgrade() -> None:
    for view in ("current_price_recommendations", "active_pricing_bundles"):
        op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.{view}")
    for table in (
        "pricing_active_state",
        "pricing_activation_sets",
        "pricing_result_selection_events",
        "pricing_promotion_dispositions",
        "pricing_promotion_protection",
        "pricing_competitor_assessments",
        "pricing_price_candidates",
        "price_recommendations",
        "pricing_response_assessments",
        "pricing_materializations",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.reject_pricing_mutation()")
