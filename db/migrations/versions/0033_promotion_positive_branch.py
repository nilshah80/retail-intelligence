"""Support the positive promotion-planner branch in serving (§6.0 P5).

Revision ID: 0033_promotion_positive_branch
Revises: 0032_pricing_unit_fields

The pricing_promotion_dispositions table (migration 0028) pinned the
promotion-planner disposition to the NEGATIVE branch only, via
ck_promotion_planner_negative_disposition
(decision_id = 53, decision_disposition = 'not_amended',
package_disposition = 'negative', NOT planner_available) and a NOT NULL
first_failure_reason. The §6.0 positive Promotion branch serves an
accepted-uplift disposition (package_disposition = 'positive',
planner_available = true, no failure reason), which both constraints reject —
so a positive disposition could not be materialized at all.

This migration relaxes the schema to accept BOTH branches while preserving the
per-branch consistency invariant: a negative disposition still requires
planner_available = false and a non-null first_failure_reason; a positive
disposition requires planner_available = true and a null first_failure_reason.
The disposition detail (accepted-promotion summary) continues to travel in the
existing JSON `details` column.
"""

from __future__ import annotations

from alembic import op


revision: str = "0033_promotion_positive_branch"
down_revision: str | None = "0032_pricing_unit_fields"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "retail_serving"
TABLE = "pricing_promotion_dispositions"

_POSITIVE_BRANCH_CHECK = (
    "(package_disposition = 'negative' AND NOT planner_available "
    "AND first_failure_reason IS NOT NULL) "
    "OR (package_disposition = 'positive' AND planner_available "
    "AND first_failure_reason IS NULL)"
)

_NEGATIVE_ONLY_CHECK = (
    "decision_id = 53 AND decision_disposition = 'not_amended' "
    "AND package_disposition = 'negative' AND NOT planner_available"
)


def upgrade() -> None:
    # The 0028 constraint hard-pinned the table to the negative branch.
    op.drop_constraint(
        "ck_promotion_planner_negative_disposition",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    # A positive disposition legitimately has no failure reason.
    op.alter_column(TABLE, "first_failure_reason", nullable=True, schema=SCHEMA)
    # Branch-agnostic invariant covering both dispositions.
    op.create_check_constraint(
        "ck_promotion_planner_disposition",
        TABLE,
        _POSITIVE_BRANCH_CHECK,
        schema=SCHEMA,
    )


def downgrade() -> None:
    # Downgrade requires no positive rows to remain.
    op.drop_constraint(
        "ck_promotion_planner_disposition",
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    op.alter_column(TABLE, "first_failure_reason", nullable=False, schema=SCHEMA)
    op.create_check_constraint(
        "ck_promotion_planner_negative_disposition",
        TABLE,
        _NEGATIVE_ONLY_CHECK,
        schema=SCHEMA,
    )
