"""Require complete-pairing acceptance and verifier v3 for active serving.

Revision ID: 0005_complete_pairing_verifier
Revises: 0004_verifier_contract
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005_complete_pairing_verifier"
down_revision: str | Sequence[str] | None = "0004_verifier_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
VERIFIER_V2 = "retail-forecast-verifier/v2"
VERIFIER_V3 = "retail-forecast-verifier/v3"


def _active_view(verifier_contract: str) -> str:
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
          AND materializations.verification_contract = '{verifier_contract}'
    """


def upgrade() -> None:
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.execute(_active_view(VERIFIER_V3))


def downgrade() -> None:
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.execute(_active_view(VERIFIER_V2))
