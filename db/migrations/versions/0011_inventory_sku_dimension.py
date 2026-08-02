"""Inventory SKU dimension: the category and unit cost every screen reads through.

`P4-11`. Two facts existed in the inventory run's loader and reached no
projection: a SKU's CATEGORY, and its accepted unit COST.

Their absence was not cosmetic. The reference's "Inventory Risk by Category" and
"Valuation by Category" group by category, and with none published the screens
shipped location ids under a Category header. Every column the reference
denominates in rupees -- Inventory Value, Order Value, Financial Exposure,
Transfer Value, Safety Stock Value -- could only render a unit count under a
money caption.

Published as ONE dimension rather than as columns added to eight fact tables.
The grain is identical to the facts (market x location x SKU), the read model
joins it where a card needs category or currency, and no fact table's frozen
column contract has to move.

`unit_cost_minor` is nullable. That is the same population the safety-stock
engine already withholds on with `ABC_UNIT_COST_UNAVAILABLE`, and P4-D6 forbids
borrowing a DC's cost for a store -- so a missing cost stays missing here rather
than being filled from a neighbour.

Revision ID: 0011_inventory_sku_dimension
Revises: 0010_inventory_serving
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_inventory_sku_dimension"
down_revision: str | Sequence[str] | None = "0010_inventory_serving"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_sku_dimension"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("inventory_version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False),
        sa.Column("sku_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("unit_cost_minor", sa.BigInteger(), nullable=True),
        sa.Column("cost_method", sa.Text(), nullable=True),
        sa.Column("currency_code", sa.Text(), nullable=True),
        # A cost without a method is a number nobody can defend, and a method
        # without a cost is a claim with nothing behind it.
        sa.CheckConstraint(
            "(unit_cost_minor IS NULL) = (cost_method IS NULL)",
            name="ck_sku_dimension_cost_method",
        ),
        sa.CheckConstraint(
            "unit_cost_minor IS NULL OR unit_cost_minor >= 0",
            name="ck_sku_dimension_cost_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_version_id"],
            [f"{SCHEMA}.inventory_versions.inventory_version_id"],
            ondelete="RESTRICT",
        ),
        # One row per cell per version: the read model joins on this key and a
        # duplicate would silently multiply every value it is joined into.
        sa.PrimaryKeyConstraint(
            "inventory_version_id", "market_id", "location_id", "sku_id"
        ),
        schema=SCHEMA,
    )
    # Category lookups scan by version and category; the primary key leads with
    # version but not with category, so the grouped cards need their own index.
    op.create_index(
        "ix_inventory_sku_dimension_category",
        TABLE,
        ["inventory_version_id", "market_id", "category"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_sku_dimension_category", table_name=TABLE, schema=SCHEMA
    )
    op.drop_table(TABLE, schema=SCHEMA)
