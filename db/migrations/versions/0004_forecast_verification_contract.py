"""Invalidate serving projections materialized before gate recomputation.

Revision ID: 0004_verifier_contract
Revises: 0003_forecast_series_dimensions
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_verifier_contract"
down_revision: str | Sequence[str] | None = "0003_forecast_series_dimensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
VERIFIER_V2 = "retail-forecast-verifier/v2"


def _active_view(*, require_verifier_v2: bool) -> str:
    verifier_predicate = (
        f"AND materializations.verification_contract = '{VERIFIER_V2}'"
        if require_verifier_v2
        else ""
    )
    return f"""
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
          {verifier_predicate}
    """


def upgrade() -> None:
    op.add_column(
        "forecast_materializations",
        sa.Column(
            "verification_contract",
            sa.Text(),
            nullable=False,
            server_default="legacy-unverified",
        ),
        schema=SCHEMA,
    )
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.execute(_active_view(require_verifier_v2=True))


def downgrade() -> None:
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.drop_column(
        "forecast_materializations",
        "verification_contract",
        schema=SCHEMA,
    )
    op.execute(_active_view(require_verifier_v2=False))
