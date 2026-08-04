"""Display names on the SKU dimension.

`P4-11`. Every inventory table showed an identifier where the reference shows a
name: "india-west:mumbai-dc" against "West DC, Ahmedabad", "apparel-footwear"
against "Footwear", a bare SKU code against "Nike Air Max 270". The names exist
in canonical -- `locations.name`, `products.product_name` -- and the category
slug is already the source's own vocabulary, needing only its separator and
casing changed.

`location_kind` rides along so a table can print the reference's own word for an
echelon: the reference's Type column reads "Warehouse", not "dc".

Denormalised onto the SKU dimension rather than given its own location table.
The dimension is already one row per market x location x SKU and is already the
join every card makes for category and cost; a second dimension would mean a
second join on every one of them to carry eight distinct location names.

Revision ID: 0013_sku_dimension_names
Revises: 0012_sku_dimension_trailing
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_sku_dimension_names"
down_revision: str | Sequence[str] | None = "0012_sku_dimension_trailing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "inventory_sku_dimension"

COLUMNS = (
    ("category_label", sa.Text()),
    ("product_name", sa.Text()),
    ("location_name", sa.Text()),
    ("location_kind", sa.Text()),
)


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column(
            TABLE,
            sa.Column(name, kind, nullable=False, server_default=""),
            schema=SCHEMA,
        )


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column(TABLE, name, schema=SCHEMA)
