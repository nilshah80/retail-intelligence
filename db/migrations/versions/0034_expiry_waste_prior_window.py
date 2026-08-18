"""Add a prior-window waste comparison to serving (§6.0 Bucket A, Waste Reduction).

Revision ID: 0034_expiry_waste_prior_window
Revises: 0033_promotion_positive_branch

The Expiry & Waste screen's "Waste Reduction" tile was a governed absence
(PRIOR_PERIOD_NOT_COMPARED): inventory_expiry_waste published only the current
trailing 91-day window, so there was no second window to compare against. This
migration adds two nullable prior-window columns the inventory materializer
populates from the 91 days preceding the current window; the read model then
serves reduction = (prior - current) / prior. Nullable so existing rows and any
bundle materialized before the materializer change remain valid and simply leave
the tile a governed absence until a bundle carrying the prior window is served.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0034_expiry_waste_prior_window"
down_revision: str | None = "0033_promotion_positive_branch"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_expiry_waste"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("prior_waste_units", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE,
        sa.Column("prior_waste_minor", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(TABLE, "prior_waste_minor", schema=SCHEMA)
    op.drop_column(TABLE, "prior_waste_units", schema=SCHEMA)
