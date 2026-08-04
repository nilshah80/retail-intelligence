"""A supplier's name, and what it still owes the network.

`P4-12`. Supplier Planning showed a UUID under "Supplier" and nothing under "Open
PO Value", and neither was a missing fact -- both were a fact that stopped short of
canonical.

The vendor master has always existed. Datagen emits `vendors.csv` with a
`displayName`, a number and a brand, and the ingestion profile declares the dataset
as `staged` -- but no adapter staged it and no transform made it canonical, so the
only supplier identity that ever reached a screen was the hash. It is now staged as
`bc_vendors`, canonicalised as `canonical_data.suppliers`, and published here.

Open PO value had the same shape. `canonical_data.inbound_shipments` hard-coded
`NULL::VARCHAR AS from_location`, and the staging query that builds it already
joined `purchase_order_lines` on `purchaseOrderId` -- while
`raw_business_central.purchase_orders` carried the `vendorId` one join away. The
shipment now names its vendor in its own column: `from_location` stays NULL because
an external supplier is not a node in the location crosswalk, and forcing one
through it would invent a warehouse.

`open_po_value_minor` is struck at the accepted unit cost for the RECEIVING cell,
the same cost every other money figure in the bundle uses. A cell with no accepted
cost contributes its units and no value, so the quantity stays complete and the
money understates rather than inventing a price -- which is why the two columns are
published separately instead of only the value.

Revision ID: 0019_supplier_identity
Revises: 0018_market_policy_scope
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_supplier_identity"
down_revision: str | Sequence[str] | None = "0018_market_policy_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "replenishment_suppliers"

COLUMNS = (
    # Nullable: a supplier with performance evidence but no vendor-master row has
    # no name, and an absent name stays absent rather than falling back to the id
    # the whole change exists to stop showing.
    ("supplier_name", sa.Text(), True),
    ("open_po_units", sa.BigInteger(), False),
    ("open_po_value_minor", sa.BigInteger(), False),
    # The currency the open-PO value is denominated in. A money column without one
    # is how a multi-market total ends up adding dollars to rupees.
    ("currency_code", sa.Text(), True),
)


def upgrade() -> None:
    for name, kind, nullable in COLUMNS:
        op.add_column(
            TABLE,
            sa.Column(
                name,
                kind,
                nullable=nullable,
                server_default=None if nullable else "0",
            ),
            schema=SCHEMA,
        )
    op.create_check_constraint(
        "ck_suppliers_open_po_nonnegative",
        TABLE,
        "open_po_units >= 0 AND open_po_value_minor >= 0",
        schema=SCHEMA,
    )
    # Value without units is a number with nothing behind it. Units without value
    # is the honest state of an uncosted cell, so only the reverse is refused.
    op.create_check_constraint(
        "ck_suppliers_open_po_value_needs_units",
        TABLE,
        "open_po_value_minor = 0 OR open_po_units > 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_suppliers_open_po_value_needs_units",
        TABLE,
        type_="check",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "ck_suppliers_open_po_nonnegative", TABLE, type_="check", schema=SCHEMA
    )
    for name, _, _ in reversed(COLUMNS):
        op.drop_column(TABLE, name, schema=SCHEMA)
