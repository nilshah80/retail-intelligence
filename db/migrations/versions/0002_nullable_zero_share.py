"""Preserve unavailable historical zero-share evidence.

Revision ID: 0002_nullable_zero_share
Revises: 0001_forecast_serving
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_nullable_zero_share"
down_revision: str | Sequence[str] | None = "0001_forecast_serving"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "forecast_eval_predictions",
        "zero_share_52w",
        existing_type=sa.Double(),
        nullable=True,
        schema="retail_serving",
    )


def downgrade() -> None:
    op.alter_column(
        "forecast_eval_predictions",
        "zero_share_52w",
        existing_type=sa.Double(),
        nullable=False,
        schema="retail_serving",
    )
