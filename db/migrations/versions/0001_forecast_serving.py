"""Create the immutable Phase 3 forecast serving projection.

Revision ID: 0001_forecast_serving
Revises:
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_forecast_serving"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def _fingerprint(name: str) -> sa.Column:
    return sa.Column(name, sa.String(length=64), nullable=False)


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema(SCHEMA))

    op.create_table(
        "forecast_materializations",
        sa.Column("forecast_run_id", sa.Text(), primary_key=True),
        sa.Column("version_id", sa.Text(), nullable=False, unique=True),
        _fingerprint("run_semantic_fingerprint"),
        _fingerprint("publication_semantic_fingerprint"),
        _fingerprint("feature_semantic_fingerprint"),
        _fingerprint("activation_scope_fingerprint"),
        sa.Column("decision_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lifecycle_status", sa.Text(), nullable=False),
        sa.Column(
            "input_bundle",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "model_policy",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "classification_policies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "acceptance",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "artifact_descriptors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "row_counts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "markets",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "materialized_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "forecast_run_id ~ '^fr_[0-9a-f]{16}$'",
            name="ck_forecast_materialization_run_id",
        ),
        sa.CheckConstraint(
            "lifecycle_status = 'accepted'",
            name="ck_forecast_materialization_accepted",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_versions",
        sa.Column("version_id", sa.Text(), primary_key=True),
        sa.Column(
            "forecast_run_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.forecast_materializations.forecast_run_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("origin_date", sa.Date(), nullable=False),
        sa.Column("horizon_weeks", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("accuracy", sa.Double(), nullable=False),
        sa.Column("bias", sa.Double(), nullable=False),
        sa.Column("demand_units", sa.BigInteger(), nullable=False),
        _fingerprint("semantic_fingerprint"),
        sa.Column("artifact_status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "horizon_weeks = 26",
            name="ck_forecast_version_horizon",
        ),
        sa.CheckConstraint(
            "artifact_status = 'accepted'",
            name="ck_forecast_version_accepted",
        ),
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_series",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("dept_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("horizon_week", sa.Integer(), nullable=False),
        sa.Column("target_week_start", sa.Date(), nullable=False),
        sa.Column("yhat_p50", sa.Double(), nullable=False),
        sa.Column("yhat_p90", sa.Double(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("data_quality_class", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{SCHEMA}.forecast_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "sku_id",
            "store_id",
            "channel_id",
            "horizon_week",
        ),
        sa.CheckConstraint(
            "horizon_week BETWEEN 1 AND 26",
            name="ck_forecast_series_horizon",
        ),
        sa.CheckConstraint(
            "yhat_p90 >= yhat_p50",
            name="ck_forecast_series_quantiles",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_forecast_series_confidence",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_series_filters",
        "forecast_series",
        ["version_id", "market_id", "store_id", "channel_id", "category"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_eval_predictions",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("forecast_origin", sa.Date(), nullable=False),
        sa.Column("target_week_start", sa.Date(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("dept_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("actual_units", sa.Double(), nullable=False),
        sa.Column("yhat_p50", sa.Double(), nullable=False),
        sa.Column("yhat_p90", sa.Double(), nullable=False),
        sa.Column("confidence", sa.Double(), nullable=False),
        sa.Column("selected_model", sa.Text(), nullable=False),
        sa.Column("zero_share_52w", sa.Double(), nullable=False),
        sa.Column("abs_error_sum", sa.Double(), nullable=False),
        sa.Column("signed_error_sum", sa.Double(), nullable=False),
        sa.Column("actual_sum", sa.Double(), nullable=False),
        sa.Column("coverage_hits", sa.BigInteger(), nullable=False),
        sa.Column("n", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            [f"{SCHEMA}.forecast_materializations.forecast_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "forecast_run_id",
            "forecast_origin",
            "target_week_start",
            "market_id",
            "sku_id",
            "store_id",
            "channel_id",
            "horizon",
        ),
        sa.CheckConstraint(
            "horizon BETWEEN 1 AND 26",
            name="ck_forecast_eval_horizon",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_eval_filters",
        "forecast_eval_predictions",
        [
            "forecast_run_id",
            "market_id",
            "store_id",
            "channel_id",
            "category",
            "forecast_origin",
        ],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_metrics",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("slice_type", sa.Text(), nullable=False),
        sa.Column("slice_id", sa.Text(), nullable=False),
        sa.Column("horizon", sa.Integer(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("abs_error_sum", sa.Double(), nullable=False),
        sa.Column("signed_error_sum", sa.Double(), nullable=False),
        sa.Column("actual_sum", sa.Double(), nullable=False),
        sa.Column("coverage_hits", sa.BigInteger(), nullable=False),
        sa.Column("n", sa.BigInteger(), nullable=False),
        sa.Column("wape", sa.Double(), nullable=True),
        sa.Column("bias", sa.Double(), nullable=True),
        sa.Column("accuracy", sa.Double(), nullable=True),
        sa.Column("p90_coverage", sa.Double(), nullable=True),
        sa.Column("fva_vs_ma13_pct", sa.Double(), nullable=True),
        sa.Column(
            "improvement_vs_seasonal_naive_pct",
            sa.Double(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            [f"{SCHEMA}.forecast_materializations.forecast_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "forecast_run_id",
            "slice_type",
            "slice_id",
            "horizon",
            "model_id",
        ),
        sa.CheckConstraint(
            "horizon BETWEEN 0 AND 26",
            name="ck_forecast_metric_horizon",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_metrics_slice",
        "forecast_metrics",
        ["forecast_run_id", "slice_type", "slice_id", "horizon"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_drivers",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("driver", sa.Text(), nullable=False),
        sa.Column("contribution_pct", sa.Numeric(9, 4), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(9, 4), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{SCHEMA}.forecast_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("version_id", "scope", "driver"),
        sa.CheckConstraint(
            "contribution_pct BETWEEN 0 AND 100",
            name="ck_forecast_driver_contribution",
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 1",
            name="ck_forecast_driver_confidence",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_drivers_scope",
        "forecast_drivers",
        ["version_id", "scope"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_exceptions",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("exception_class", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("threshold", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("policy_id", sa.Text(), nullable=False),
        _fingerprint("policy_semantic_fingerprint"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{SCHEMA}.forecast_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "sku_id",
            "store_id",
            "channel_id",
            "exception_class",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_exceptions_filters",
        "forecast_exceptions",
        ["version_id", "market_id", "exception_class", "severity", "status"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_data_quality",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("data_quality_class", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("policy_id", sa.Text(), nullable=False),
        _fingerprint("policy_semantic_fingerprint"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{SCHEMA}.forecast_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "sku_id",
            "store_id",
            "channel_id",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_quality_filters",
        "forecast_data_quality",
        ["version_id", "market_id", "data_quality_class"],
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_stores",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("city", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            [f"{SCHEMA}.forecast_materializations.forecast_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("forecast_run_id", "store_id"),
        schema=SCHEMA,
    )

    op.create_table(
        "forecast_activation_events",
        sa.Column(
            "event_id",
            sa.BigInteger(),
            sa.Identity(),
            primary_key=True,
        ),
        _fingerprint("activation_scope_fingerprint"),
        sa.Column(
            "forecast_run_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.forecast_materializations.forecast_run_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "version_id",
            sa.Text(),
            sa.ForeignKey(
                f"{SCHEMA}.forecast_versions.version_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "prior_event_id",
            sa.BigInteger(),
            sa.ForeignKey(
                f"{SCHEMA}.forecast_activation_events.event_id",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "event_type IN ('active', 'superseded')",
            name="ck_forecast_activation_event_type",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_activation_scope_event",
        "forecast_activation_events",
        ["activation_scope_fingerprint", "event_id"],
        schema=SCHEMA,
    )

    op.execute(
        f"""
        CREATE VIEW {SCHEMA}.active_forecast_versions AS
        WITH latest AS (
            SELECT DISTINCT ON (activation_scope_fingerprint)
                event_id,
                activation_scope_fingerprint,
                forecast_run_id,
                version_id,
                event_type,
                actor,
                recorded_at,
                prior_event_id
            FROM {SCHEMA}.forecast_activation_events
            ORDER BY activation_scope_fingerprint, event_id DESC
        )
        SELECT
            latest.*,
            materializations.run_semantic_fingerprint,
            materializations.publication_semantic_fingerprint,
            materializations.feature_semantic_fingerprint,
            materializations.decision_as_of,
            materializations.markets
        FROM latest
        JOIN {SCHEMA}.forecast_materializations AS materializations
          USING (forecast_run_id)
        WHERE latest.event_type = 'active'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {SCHEMA}.active_forecast_versions")
    for table in (
        "forecast_activation_events",
        "forecast_stores",
        "forecast_data_quality",
        "forecast_exceptions",
        "forecast_drivers",
        "forecast_metrics",
        "forecast_eval_predictions",
        "forecast_series",
        "forecast_versions",
        "forecast_materializations",
    ):
        op.drop_table(table, schema=SCHEMA)
    op.execute(sa.schema.DropSchema(SCHEMA))
