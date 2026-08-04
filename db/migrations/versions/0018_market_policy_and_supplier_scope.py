"""The market ceilings a plan is measured against, and what a supplier supplies.

`P4-12`. Two governance figures had no fact behind them.

"Orders within budget" on the Replenishment Planner and "Budget Exceptions" on
Replenishment Exceptions both measure a plan against `weeklyReplenishmentBudgetMinor`,
which the policy contract declares per market. The read model cannot open a policy
document, so the ceiling had no denominator and three cells read "Not available".
The declared value was also a placeholder two orders of magnitude below the network
it governs -- one review period's recommendations are Rs 26.08 Cr against a Rs 25
lakh ceiling -- so it is now Rs 23 Cr and USD 1.2M, and the compliance figure means
something.

"Category" on Supplier Planning printed nothing because the supplier projection
carried performance and risk and no merchandise scope. The scope is in
`supply_terms`, and all 280 suppliers resolve a category from it -- but 239 of them
serve more than one, so `scope_count` travels with the label. A screen that showed
one category and implied exclusivity would misrepresent 85 per cent of the rows.

Revision ID: 0018_market_policy_scope
Revises: 0017_inbound_summary
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_market_policy_scope"
down_revision: str | Sequence[str] | None = "0017_inbound_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
POLICY_TABLE = "inventory_market_policy"
SUPPLIERS = "replenishment_suppliers"

SUPPLIER_COLUMNS = (
    ("category", sa.Text()),
    ("category_label", sa.Text()),
    ("scope_count", sa.BigInteger()),
)


def upgrade() -> None:
    op.create_table(
        POLICY_TABLE,
        sa.Column("inventory_version_id", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column(
            "weekly_replenishment_budget_minor", sa.BigInteger(), nullable=False
        ),
        sa.Column("currency_code", sa.Text(), nullable=False),
        # A zero or negative ceiling is not a ceiling: it would make every
        # compliance figure either zero or a division by zero.
        sa.CheckConstraint(
            "weekly_replenishment_budget_minor > 0",
            name="ck_market_policy_budget_positive",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_version_id"],
            [f"{SCHEMA}.inventory_versions.inventory_version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("inventory_version_id", "market_id"),
        schema=SCHEMA,
    )
    # Nullable: a supplier with performance evidence but no resolvable term has no
    # scope, and an absent scope stays absent rather than defaulting to a category
    # nobody declared.
    for name, kind in SUPPLIER_COLUMNS:
        op.add_column(SUPPLIERS, sa.Column(name, kind, nullable=True), schema=SCHEMA)
    op.create_check_constraint(
        "ck_suppliers_scope_count_positive",
        SUPPLIERS,
        "scope_count IS NULL OR scope_count > 0",
        schema=SCHEMA,
    )
    # A label without its slug is a display string nobody can group by, and a slug
    # without its label is the identifier this whole phase set out to stop showing.
    op.create_check_constraint(
        "ck_suppliers_category_label_paired",
        SUPPLIERS,
        "(category IS NULL) = (category_label IS NULL)",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_suppliers_category_label_paired", SUPPLIERS, type_="check", schema=SCHEMA
    )
    op.drop_constraint(
        "ck_suppliers_scope_count_positive", SUPPLIERS, type_="check", schema=SCHEMA
    )
    for name, _ in reversed(SUPPLIER_COLUMNS):
        op.drop_column(SUPPLIERS, name, schema=SCHEMA)
    op.drop_table(POLICY_TABLE, schema=SCHEMA)
