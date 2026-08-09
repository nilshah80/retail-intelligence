"""Publish blocked stock and realised warehouse service denominators.

The warehouse screen previously inferred fill from current reorder suggestions,
which left five Gulf warehouses unavailable and reported the only warehouse with
a four-unit suggestion as 100%.  These columns carry the origin-visible 91-day
demand and served totals at the table's existing one-row-per-node grain.  They
also retain the source capacity snapshot's blocked units for reconciliation.

Older immutable inventory versions legitimately have no service window, so the
four service columns are nullable as one all-or-none group.  Newly published v2
artifacts always populate them, including an explicit zero denominator.

Revision ID: 0024_warehouse_service_metrics
Revises: 0023_marketplace_channel_type
Create Date: 2026-08-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_warehouse_service_metrics"
down_revision: str | Sequence[str] | None = "0023_marketplace_channel_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_warehouse_capacity"
SERVICE_CHECK = "ck_warehouse_service_metrics_consistent"
BLOCKED_CHECK = "ck_warehouse_blocked_nonnegative"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "blocked_units",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        TABLE, sa.Column("fill_demand_units", sa.BigInteger()), schema=SCHEMA
    )
    op.add_column(
        TABLE, sa.Column("fill_served_units", sa.BigInteger()), schema=SCHEMA
    )
    op.add_column(
        TABLE, sa.Column("fill_window_start", sa.Date()), schema=SCHEMA
    )
    op.add_column(
        TABLE, sa.Column("fill_window_end", sa.Date()), schema=SCHEMA
    )
    op.create_check_constraint(
        BLOCKED_CHECK,
        TABLE,
        "blocked_units >= 0",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        SERVICE_CHECK,
        TABLE,
        """
        (
            fill_demand_units IS NULL
            AND fill_served_units IS NULL
            AND fill_window_start IS NULL
            AND fill_window_end IS NULL
        ) OR (
            fill_demand_units >= 0
            AND fill_served_units >= 0
            AND fill_served_units <= fill_demand_units
            AND fill_window_start IS NOT NULL
            AND fill_window_end IS NOT NULL
            AND fill_window_start <= fill_window_end
        )
        """,
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(SERVICE_CHECK, TABLE, schema=SCHEMA, type_="check")
    op.drop_constraint(BLOCKED_CHECK, TABLE, schema=SCHEMA, type_="check")
    for column in (
        "fill_window_end",
        "fill_window_start",
        "fill_served_units",
        "fill_demand_units",
        "blocked_units",
    ):
        op.drop_column(TABLE, column, schema=SCHEMA)
