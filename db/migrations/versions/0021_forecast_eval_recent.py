"""The ragged recent schedule, in its own table so nothing can pool it.

`forecast_eval_predictions` is contractually a complete 13 x 26 rectangle --
`_validate_complete_schedule` raises on anything else -- because acceptance is
scored over it and a missing origin/horizon pair would silently narrow a gate.
That is also why a recent week cannot appear in it: an origin joins the complete
schedule only once all 26 horizons have a realised actual, so the newest scoreable
origin always sits exactly 26 weeks behind the newest actual.

The consequence reached the screen. Forecast vs Actual selects the most recent
weeks that have actuals, and those are reachable only at h19-h26, where pooled
bias runs -5.8% to -6.6% against -0.29% at h1. The chart showed the P50 under the
actual in 8 of 8 weeks and read as a forecast that is permanently short, when the
estimator at the horizon a planner acts on is very nearly unbiased.

This table holds the same origins the complete grid cannot reach, scored at the
horizons they CAN evaluate. A separate table rather than a marker column on the
existing one, deliberately: five Go read models and several Python consumers query
the eval projection, and an origin contributing four horizons must never move a
metric computed over twenty-six. A WHERE clause asks every future query politely;
a different table makes the mistake unrepresentable.

No `confidence`, `selected_model`, `zero_share_52w` or additive metric columns:
those feed the acceptance diagnostics the complete grid owns, and this projection
is forbidden from reaching them. It carries what a comparison needs and nothing
that could be mistaken for a gate input.

Paired with `retail-forecast-run/v4` and `retail-forecast-verifier/v6`. A v5 bundle
has no such artifact, so it stops being eligible to serve until it is rebuilt --
the same fail-closed shape decisions #82 and #85 used, and for the same reason: no
accepted artifact is rewritten and no verdict is reinterpreted.

Revision ID: 0021_forecast_eval_recent
Revises: 0020_safety_stock_drivers
Create Date: 2026-08-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_forecast_eval_recent"
down_revision: str | Sequence[str] | None = "0020_safety_stock_drivers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "forecast_eval_recent"

VERIFIER_V5 = "retail-forecast-verifier/v5"
VERIFIER_V6 = "retail-forecast-verifier/v6"


def _active_view(verifier_contract: str) -> str:
    """`active_forecast_versions`, re-pointed at a verifier contract.

    The view is where the contract version becomes a serving gate: a
    materialization recorded under any other contract simply is not in it, so
    decision #90's "exactly one active version" assertion sees zero and refuses.
    Bumping the Python constant without moving this view is therefore not a
    partial change -- it is a change that cannot activate anything at all.
    """

    return f"""
        CREATE OR REPLACE VIEW {SCHEMA}.active_forecast_versions AS
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
          AND materializations.verification_contract = '{verifier_contract}'
    """


def upgrade() -> None:
    op.create_table(
        TABLE,
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
        # The schedule's defining constraint, enforced by the database rather than
        # left to the writer: this projection exists for the horizons a recent
        # origin can evaluate, and a long-horizon row landing here would recreate
        # the very comparison the table was added to avoid.
        sa.CheckConstraint(
            "horizon BETWEEN 1 AND 4",
            name="ck_forecast_eval_recent_horizon",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_eval_recent_filters",
        TABLE,
        [
            "forecast_run_id",
            "market_id",
            "store_id",
            "channel_id",
            "category",
        ],
        schema=SCHEMA,
    )
    # v5 -> v6. A v5 materialization is not reinterpreted and no accepted
    # artifact is rewritten; it simply stops being eligible to serve until it is
    # rebuilt on run/v4, which is the same fail-closed shape 0006 and 0007 used.
    op.execute(_active_view(VERIFIER_V6))


def downgrade() -> None:
    op.execute(_active_view(VERIFIER_V5))
    op.drop_index(
        "ix_forecast_eval_recent_filters",
        table_name=TABLE,
        schema=SCHEMA,
    )
    op.drop_table(TABLE, schema=SCHEMA)
