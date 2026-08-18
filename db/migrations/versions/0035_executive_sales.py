"""Publish bounded historical sales facts for Executive Overview.

Revision ID: 0035_executive_sales
Revises: 0034_expiry_waste_prior_window
Create Date: 2026-08-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0035_executive_sales"
down_revision: str | Sequence[str] | None = "0034_expiry_waste_prior_window"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    op.create_table(
        "executive_sales",
        sa.Column("forecast_run_id", sa.Text(), nullable=False),
        sa.Column("period_key", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("store_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("channel_type", sa.Text(), nullable=False),
        sa.Column("region", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("currency_code", sa.String(length=3), nullable=False),
        sa.Column("net_units", sa.BigInteger(), nullable=False),
        sa.Column("net_sales_minor", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["forecast_run_id"],
            [f"{SCHEMA}.forecast_materializations.forecast_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "forecast_run_id",
            "period_key",
            "sku_id",
            "store_id",
            "channel_id",
        ),
        sa.CheckConstraint(
            "period_key IN ('ltm', 'prior_ltm', 'month_to_date', "
            "'prior_year_month_to_date', 'quarter_to_date', "
            "'prior_year_quarter_to_date')",
            name="ck_executive_sales_period",
        ),
        sa.CheckConstraint(
            "period_end >= period_start",
            name="ck_executive_sales_period_bounds",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_executive_sales_filters",
        "executive_sales",
        [
            "forecast_run_id",
            "period_key",
            "market_id",
            "store_id",
            "region",
            "channel_type",
            "category",
        ],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_executive_sales_filters",
        table_name="executive_sales",
        schema=SCHEMA,
    )
    op.drop_table("executive_sales", schema=SCHEMA)
