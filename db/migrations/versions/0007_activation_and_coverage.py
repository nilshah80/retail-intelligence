"""Retire decision-#90 v1 activation scopes and require the #85 hard coverage gate.

Two changes, both about which materialization may serve. Neither rewrites an accepted
artifact.

Decision #90. `_activation_scope` v1 hashed `modelPolicy` and `classificationPolicies`,
so refitting a policy over the same input bundle, feature fingerprint and markets minted
a parallel authority scope instead of superseding the previous one. Both rows stayed
`active` with `prior_event_id = NULL`, and the Go read model filters on a single
configured fingerprint and could not see the competing authority. This retires those v1
scopes by appending `superseded` events rather than deleting history, and leaves the
append-only log intact.

Decision #85. Its hard-gate deadline is Phase 4 entry, and its own text records that the
promised fail-closed version boundary was never created: recomputation and verifier were
already v4 from decision #82, so nothing distinguished a run evaluated against the
per-cohort coverage gate from one that predated it. This creates that boundary. Only
`retail-forecast-verifier/v5` materializations may serve, so every run accepted while
`A2_per_cohort` was report-only stops being eligible without being reinterpreted.

Revision ID: 0007_activation_and_coverage
Revises: 0006_cohorted_verifier_v4
Create Date: 2026-07-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007_activation_and_coverage"
down_revision: str | Sequence[str] | None = "0006_cohorted_verifier_v4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
VERIFIER_V4 = "retail-forecast-verifier/v4"
VERIFIER_V5 = "retail-forecast-verifier/v5"


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
    # Append a supersession for every currently-active scope. History is append-only, so
    # the v1 rows stay readable; they simply stop being the latest event for their scope.
    op.execute(
        f"""
        INSERT INTO {SCHEMA}.forecast_activation_events (
            activation_scope_fingerprint,
            forecast_run_id,
            version_id,
            event_type,
            actor,
            prior_event_id
        )
        SELECT
            latest.activation_scope_fingerprint,
            latest.forecast_run_id,
            latest.version_id,
            'superseded',
            'migration:0007_activation_and_coverage',
            latest.event_id
        FROM (
            SELECT DISTINCT ON (activation_scope_fingerprint)
                event_id,
                activation_scope_fingerprint,
                forecast_run_id,
                version_id,
                event_type
            FROM {SCHEMA}.forecast_activation_events
            ORDER BY activation_scope_fingerprint, event_id DESC
        ) AS latest
        WHERE latest.event_type = 'active'
        """
    )
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.execute(_active_view(VERIFIER_V5))


def downgrade() -> None:
    # The supersession events are deliberately NOT removed. Deleting them would rewrite
    # an append-only audit log to make a rollback look tidy, and a scope that was
    # retired for competing with another authority should stay retired.
    op.execute(f"DROP VIEW {SCHEMA}.active_forecast_versions")
    op.execute(_active_view(VERIFIER_V4))
