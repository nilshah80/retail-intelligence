"""Serve Decision #95's additive expectation and require verifier v7.

P50 remains a median. These nullable columns preserve historical v6
materializations without inventing an expectation for them; the active view admits only
verifier-v7 runs, whose publisher and projection require every new expected value.

Revision ID: 0022_expected_volume_forecast
Revises: 0021_forecast_eval_recent
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_expected_volume_forecast"
down_revision: str | Sequence[str] | None = "0021_forecast_eval_recent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
VERIFIER_V6 = "retail-forecast-verifier/v6"
VERIFIER_V7 = "retail-forecast-verifier/v7"


def _active_view(verifier_contract: str) -> str:
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


def _add_expected_columns(table: str, *, fallback: bool = False) -> None:
    op.add_column(
        table,
        sa.Column("expected_units", sa.Double(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        table,
        sa.Column("expected_model", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    if fallback:
        op.add_column(
            table,
            sa.Column(
                "expected_cold_head_fallback",
                sa.Boolean(),
                nullable=True,
            ),
            schema=SCHEMA,
        )
    op.create_check_constraint(
        f"ck_{table}_expected_pair",
        table,
        "(expected_units IS NULL) = (expected_model IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        f"ck_{table}_expected_nonnegative",
        table,
        "expected_units IS NULL OR expected_units >= 0",
        schema=SCHEMA,
    )


def upgrade() -> None:
    _add_expected_columns("forecast_series")
    _add_expected_columns("forecast_eval_predictions", fallback=True)
    _add_expected_columns("forecast_eval_recent")
    op.execute(_active_view(VERIFIER_V7))


def _drop_expected_columns(table: str, *, fallback: bool = False) -> None:
    op.drop_constraint(
        f"ck_{table}_expected_nonnegative",
        table,
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        f"ck_{table}_expected_pair",
        table,
        schema=SCHEMA,
        type_="check",
    )
    if fallback:
        op.drop_column(table, "expected_cold_head_fallback", schema=SCHEMA)
    op.drop_column(table, "expected_model", schema=SCHEMA)
    op.drop_column(table, "expected_units", schema=SCHEMA)


def downgrade() -> None:
    op.execute(_active_view(VERIFIER_V6))
    _drop_expected_columns("forecast_eval_recent")
    _drop_expected_columns("forecast_eval_predictions", fallback=True)
    _drop_expected_columns("forecast_series")
