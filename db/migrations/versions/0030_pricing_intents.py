"""Retain prebound pricing result-selection intents with materializations.

Revision ID: 0030_pricing_intents
Revises: 0029_pricing_events
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0030_pricing_intents"
down_revision: str | None = "0029_pricing_events"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    op.add_column(
        "pricing_materializations",
        sa.Column("prospective_result_selections", sa.JSON(), nullable=True),
        schema=SCHEMA,
    )
    # Existing materializations predate the intent contract and therefore have
    # no authority to activate through the new path. Preserve them truthfully
    # as an empty set rather than fabricating a prospective identity.
    op.execute(
        f"UPDATE {SCHEMA}.pricing_materializations "
        "SET prospective_result_selections = '[]'::json "
        "WHERE prospective_result_selections IS NULL"
    )
    op.alter_column(
        "pricing_materializations",
        "prospective_result_selections",
        nullable=False,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(
        "pricing_materializations",
        "prospective_result_selections",
        schema=SCHEMA,
    )
