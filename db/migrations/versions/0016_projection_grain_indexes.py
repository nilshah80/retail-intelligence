"""A unique index on every inventory projection's declared grain.

`P4-12`. Migration 0010 gave each projection table one index --
`(inventory_version_id, market_id)` -- and no key. Two consequences, one slow and
one dangerous.

SLOW: every read model join between projections matches on the full grain
(version, market, location, SKU), and with no index covering it Postgres hash
joins the whole table each time. That cost grew with every activation, because a
serving table holds all fifteen materialized versions: the positions aggregate
took 1.4 seconds on its own and 8.8 with the outbound-need roll-up joined,
which put the Inventory Overview and Stock Health routes past the server's write
timeout. They did not fail with a governed 503 -- they closed the connection, and
the page sat on "Loading live retail data..." for ever.

DANGEROUS: `ARTIFACT_GRAIN` declares each projection's grain and the publisher
checks it, but nothing at the database boundary enforced it. A duplicate row would
silently multiply every value it was joined into, which is precisely the failure
mode 0011 wrote a primary key to prevent for the dimension. The dimension had one;
none of the twelve fact tables did.

UNIQUE rather than a plain index, so the grain is a constraint and not a hope.
Verified clean across all fifteen versions before writing this: zero duplicate
groups on every table below.

The column lists are `ARTIFACT_GRAIN` with `inventory_version_id` prepended, in
that order, so the version leads and a single-version read is a range scan.

Revision ID: 0016_projection_grain_indexes
Revises: 0015_recommendation_lead_time
Create Date: 2026-08-04
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016_projection_grain_indexes"
down_revision: str | Sequence[str] | None = "0015_recommendation_lead_time"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"

#: table -> the grain it is published at, mirroring ARTIFACT_GRAIN.
GRAINS: dict[str, tuple[str, ...]] = {
    "inventory_positions": ("market_id", "location_id", "sku_id"),
    "inventory_stock_health": ("market_id", "location_id", "sku_id"),
    "inventory_demand_at_risk": (
        "market_id",
        "location_id",
        "sku_id",
        "channel_id",
    ),
    "inventory_ageing": ("market_id", "location_id", "sku_id", "age_bucket"),
    "inventory_expiry_waste": ("market_id", "location_id", "sku_id"),
    "inventory_valuation": ("market_id", "location_id", "category"),
    "replenishment_recommendations": (
        "market_id",
        "destination_location_id",
        "sku_id",
    ),
    "replenishment_safety_stock": ("market_id", "location_id", "sku_id"),
    "replenishment_transfers": ("market_id", "lane_id", "sku_id"),
    "replenishment_allocations": (
        "market_id",
        "location_id",
        "channel_id",
        "sku_id",
    ),
    "replenishment_suppliers": ("market_id", "supplier_id"),
    "replenishment_exceptions": (
        "market_id",
        "location_id",
        "sku_id",
        "channel_id",
        "exception_class",
    ),
    "inventory_replay_metrics": ("market_id", "metric", "cohort"),
}


def _index_name(table: str) -> str:
    return f"uq_{table}_grain"


def upgrade() -> None:
    for table, grain in GRAINS.items():
        op.create_index(
            _index_name(table),
            table,
            ["inventory_version_id", *grain],
            unique=True,
            schema=SCHEMA,
        )


def downgrade() -> None:
    for table in reversed(list(GRAINS)):
        op.drop_index(_index_name(table), table_name=table, schema=SCHEMA)
