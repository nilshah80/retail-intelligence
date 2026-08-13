"""Add Current/Expected Margin percentages to price recommendations.

Revision ID: 0031_pricing_margin_pct
Revises: 0030_pricing_intents
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0031_pricing_margin_pct"
down_revision: str | None = "0030_pricing_intents"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    # Current and Expected Margin percent are populated only when a client-actual
    # cost resolves; every withheld or cost-unavailable row stays NULL alongside
    # margin_impact_minor. Nullable numeric mirrors the existing margin columns and
    # never coerces an unavailable margin to zero.
    op.add_column(
        "price_recommendations",
        sa.Column("current_margin_pct", sa.Numeric(12, 4), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "price_recommendations",
        sa.Column("expected_margin_pct", sa.Numeric(12, 4), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("price_recommendations", "expected_margin_pct", schema=SCHEMA)
    op.drop_column("price_recommendations", "current_margin_pct", schema=SCHEMA)
