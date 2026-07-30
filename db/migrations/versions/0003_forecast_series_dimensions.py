"""Add source-neutral display dimensions for the forecast workbench.

Revision ID: 0003_forecast_series_dimensions
Revises: 0002_nullable_zero_share
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_forecast_series_dimensions"
down_revision: str | Sequence[str] | None = "0002_nullable_zero_share"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    op.create_table(
        "forecast_series_dimensions",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("channel_type", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["version_id"],
            [f"{SCHEMA}.forecast_versions.version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "version_id",
            "sku_id",
            "store_id",
            "channel_id",
        ),
        sa.CheckConstraint(
            "channel_type IN ('online', 'store')",
            name="ck_forecast_series_dimension_channel_type",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_series_dimension_filters",
        "forecast_series_dimensions",
        [
            "version_id",
            "market_id",
            "store_id",
            "channel_type",
            "product_name",
        ],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("forecast_series_dimensions", schema=SCHEMA)
