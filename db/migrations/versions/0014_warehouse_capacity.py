"""Warehouse storage capacity: the denominator utilisation had none of.

`P4-12`. The reference's Warehouse Inventory table carries a Capacity Utilization
column -- 82%, 76%, 69% -- and the platform published every warehouse's holding
and none of their ceilings, so the column could only ever read "Not available".

The ceiling exists in canonical. `warehouse_capacity_snapshots` carries a weekly
`capacity_units` per warehouse across a decade, at `native_observed` grade, and
nothing downstream read it.

Given its own table rather than columns on the SKU dimension. Capacity is a
property of a NODE, and the dimension is one row per market x location x SKU:
carrying it there would repeat one warehouse's ceiling across every SKU it
stocks, and any sum over the column would report a capacity hundreds of times
the real one.

`used_units` from the source is deliberately not published. It is the same
on-hand the position artifact already carries -- identical to the unit at both
India DCs -- so utilisation divides the holding the screen already values by the
ceiling here, and the numerator cannot disagree with the money column beside it.

Revision ID: 0014_warehouse_capacity
Revises: 0013_sku_dimension_names
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_warehouse_capacity"
down_revision: str | Sequence[str] | None = "0013_sku_dimension_names"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_warehouse_capacity"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("inventory_version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False),
        sa.Column("capacity_units", sa.BigInteger(), nullable=False),
        # Which snapshot the ceiling was read from. A capacity with no date is a
        # number a reader cannot age, and the source revises capacity over time.
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        # A zero ceiling is not a ceiling: it would make utilisation a division
        # by zero, and the read model would have to guess whether to withhold or
        # report infinity.
        sa.CheckConstraint(
            "capacity_units > 0",
            name="ck_warehouse_capacity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_version_id"],
            [f"{SCHEMA}.inventory_versions.inventory_version_id"],
            ondelete="RESTRICT",
        ),
        # One row per NODE per version, not per node per snapshot date: the run
        # publishes the latest ceiling its origin admits, and a second row for
        # the same node would multiply every position it is joined into.
        sa.PrimaryKeyConstraint("inventory_version_id", "market_id", "location_id"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table(TABLE, schema=SCHEMA)
