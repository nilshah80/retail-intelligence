"""Admit only decision-#82 verifier v4 evidence for active serving.

Decision #82 replaces the single seasonal-naive A1 population with an
established-history cohort plus a separately gated cold-start cohort, published
as acceptance-v3/verifier-v4. Older verifier-v2/v3 materializations are not
reinterpreted under the new policy: they simply stop being eligible to serve, so
no accepted artifact is rewritten and migration 0005 remains immutable.

Revision ID: 0006_cohorted_verifier_v4
Revises: 0005_complete_pairing_verifier
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_cohorted_verifier_v4"
down_revision: str | Sequence[str] | None = "0005_complete_pairing_verifier"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
VERIFIER_V3 = "retail-forecast-verifier/v3"
VERIFIER_V4 = "retail-forecast-verifier/v4"


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
    op.execute(_active_view(VERIFIER_V4))


def downgrade() -> None:
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.execute(_active_view(VERIFIER_V3))
