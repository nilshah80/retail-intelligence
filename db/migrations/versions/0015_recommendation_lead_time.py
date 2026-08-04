"""The resolved lead time on a replenishment recommendation.

`P4-12`. The reference's Priority Replenishment Recommendations grid carries a
Lead Time column -- "2 days", "6 days" -- and an Expected Receipt date derived
from it. Neither had a fact behind it, so both read "Not available" on every row
of the page a planner works from.

The engine already had the number. `CellSupply.lead_time_days` is resolved once
per cell from the declared supply term and consumed to size the protection
period; it was simply never published. Nothing new is computed here.

Nullable, because the resolution can fail: a cell with no active service lane or
no resolvable term has no lead time, which is the same population the
recommendation already withholds on with `SUPPLY_ROUTE_UNRESOLVED`. A missing
lead time stays missing rather than defaulting to zero -- a zero-day lead time
would read as "arrives today", which is the opposite of what an unresolved route
means.

Expected Receipt is deliberately NOT stored. It is this lead time added to the
version's `decision_as_of`, and both are published, so storing the sum would let
a date drift out of step with the origin it was derived from.

Revision ID: 0015_recommendation_lead_time
Revises: 0014_warehouse_capacity
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_recommendation_lead_time"
down_revision: str | Sequence[str] | None = "0014_warehouse_capacity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "replenishment_recommendations"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column("lead_time_days", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )
    # A negative lead time is not a lead time, and a zero would claim same-day
    # arrival on a route the resolver may not have resolved at all.
    op.create_check_constraint(
        "ck_recommendations_lead_time_positive",
        TABLE,
        "lead_time_days IS NULL OR lead_time_days > 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_recommendations_lead_time_positive",
        TABLE,
        type_="check",
        schema=SCHEMA,
    )
    op.drop_column(TABLE, "lead_time_days", schema=SCHEMA)
