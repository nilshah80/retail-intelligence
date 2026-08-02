"""Trailing weekly demand on the SKU dimension.

`P4-11`. Four screen measures are arithmetic on trailing demand and none of them
could do the arithmetic, because the build computed it for the replenishment
engine and never published it:

* days of supply -- on-hand over daily demand -- which the reference shows on
  Inventory Risk by Category, Location-Level Performance, the Store heatmap and
  Stock Health, and which read "Not available" on every row;
* sell-through, on Ageing Inventory and Expiry & Waste;
* stock turn, the enterprise KPI, which is simply 365 over days of supply.

Nullable is wrong here and zero is right: a cell with no trailing demand HAS no
trailing demand, which is a fact about the cell, not a gap in the evidence. Days
of supply over zero demand is then correctly undefined rather than unknown.

Revision ID: 0012_sku_dimension_trailing
Revises: 0011_inventory_sku_dimension
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_sku_dimension_trailing"
down_revision: str | Sequence[str] | None = "0011_inventory_sku_dimension"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_sku_dimension"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "trailing_daily_units",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "ck_sku_dimension_trailing_nonnegative",
        TABLE,
        "trailing_daily_units >= 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sku_dimension_trailing_nonnegative", TABLE, schema=SCHEMA
    )
    op.drop_column(TABLE, "trailing_daily_units", schema=SCHEMA)
