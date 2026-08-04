"""Inbound reliability per receiving node.

`P4-12`. Two screens ask whether inbound supply is late and neither could answer.
The Warehouse Inventory table has a Delayed Receipts column and the Replenishment
Planner's Lead-Time Risk card has Late Orders, and the position projection carries
an on-order bucket, an in-transit bucket and NO DATES.

Worse than absent: it was answered wrongly. Policy v2 declares those two buckets
disjoint (`inventoryPosition.bucketOverlap: forbidden`), so "on order with nothing
in transit" is true of every order not yet shipped -- it matched 100% of open lines
at all four warehouses and rendered them as delayed.

The dates are in the source. `inbound_shipment_status_events` carries an
`expected_receipt_date` and the full `on_order -> in_transit -> received`
lifecycle per shipment, and nothing downstream read it.

Lateness is measured on ARRIVALS over the trailing window, not on the open book.
Nothing is currently past due at this origin -- every open shipment is expected on
or after it -- so an open-book measure reads zero at every node and says nothing
about reliability. Of what did arrive, roughly three in four arrived late, which
is consistent with the 19.8% supplier on-time rate the supplier projection already
publishes.

Counts only. The late SHARE is a ratio the read model scopes per market and per
echelon; storing it would freeze one denominator and make every filtered view of
it wrong.

Revision ID: 0017_inbound_summary
Revises: 0016_projection_grain_indexes
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_inbound_summary"
down_revision: str | Sequence[str] | None = "0016_projection_grain_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_inbound_summary"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("inventory_version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("location_id", sa.Text(), nullable=False),
        # Open at the origin: a shipment whose latest status is not received.
        sa.Column("open_shipments", sa.BigInteger(), nullable=False),
        sa.Column("open_units", sa.BigInteger(), nullable=False),
        # Arrivals in the trailing window, and how many of them missed their
        # expected date. `late` is a subset of `received`, which the check below
        # enforces rather than trusting.
        sa.Column("received_shipments", sa.BigInteger(), nullable=False),
        sa.Column("late_shipments", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "open_shipments >= 0 AND open_units >= 0 "
            "AND received_shipments >= 0 AND late_shipments >= 0",
            name="ck_inbound_summary_nonnegative",
        ),
        sa.CheckConstraint(
            "late_shipments <= received_shipments",
            name="ck_inbound_summary_late_within_received",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_version_id"],
            [f"{SCHEMA}.inventory_versions.inventory_version_id"],
            ondelete="RESTRICT",
        ),
        # One row per receiving NODE per version, matching ARTIFACT_GRAIN, so a
        # duplicate cannot multiply a count it is joined into.
        sa.PrimaryKeyConstraint("inventory_version_id", "market_id", "location_id"),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table(TABLE, schema=SCHEMA)
