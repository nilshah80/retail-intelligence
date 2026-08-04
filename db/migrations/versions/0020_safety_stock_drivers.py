"""What a safety buffer is made of, and when lead time cannot be one of them.

`P4-12g`. Policy v2 declares the buffer as

    z * sqrt(protection_weeks * demand_variance_weekly
             + mean_weekly_demand^2 * lead_time_variance_weeks)

and the engine implemented the first addend only. So `leadTime.variabilityMethod`,
`leadTime.minimumObservations`, `leadTime.zeroVarianceBehavior` and its
`LEAD_TIME_VARIABILITY_UNAVAILABLE` reason code had no consumer, a supplier whose
lead time swings by nine days got the same buffer as a metronomic one, and the
reference's Safety Stock driver decomposition could not be published at all --
one of its two drivers did not exist.

`lead_time_std_days` was canonical the whole time: non-zero on 16,198 of 17,829
published supplier-period rows, median 1.286 days, maximum 9.5, against lead
times of 5 to 31 days.

The two driver columns combine in QUADRATURE, not additively, so they do not sum
to `safety_stock_units`. A check constraint enforces that each is no greater than
the total, which is what quadrature implies and what an accidental additive
rewrite would violate.

`lead_time_variability_reason_code` is null when both drivers are real. It is set
when the lead-time term could not be computed and the total is the demand driver
alone -- an internal service lane has no supplier performance, and a supplier
observed over fewer than eight periods has no admissible estimate. Policy v2's
`zeroVarianceBehavior: reason_code_not_zero_buffer` is why that is reason-coded
rather than recorded as zero variance: a zero-variance buffer is a misleading
number rather than a missing one.

Revision ID: 0020_safety_stock_drivers
Revises: 0019_supplier_identity
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_safety_stock_drivers"
down_revision: str | Sequence[str] | None = "0019_supplier_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "replenishment_safety_stock"

COLUMNS = (
    # Nullable for the same reason `safety_stock_units` is: a withheld interval
    # produces no buffer, and therefore no drivers. Decision #92 forbids coercing
    # that to zero.
    ("safety_stock_demand_units", sa.Numeric(18, 4)),
    ("safety_stock_lead_time_units", sa.Numeric(18, 4)),
    ("lead_time_variability_reason_code", sa.Text()),
)


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column(TABLE, sa.Column(name, kind, nullable=True), schema=SCHEMA)
    # A driver larger than the buffer it contributes to is arithmetically
    # impossible under quadrature, and is exactly what rewriting the combination
    # as a sum would produce.
    for driver in ("safety_stock_demand_units", "safety_stock_lead_time_units"):
        op.create_check_constraint(
            f"ck_safety_stock_{driver}_within_total",
            TABLE,
            f"{driver} IS NULL OR safety_stock_units IS NULL "
            f"OR {driver} <= safety_stock_units",
            schema=SCHEMA,
        )
    # Both drivers travel with the buffer or none of them do. A total whose
    # composition is unpublished is a number nobody can account for.
    op.create_check_constraint(
        "ck_safety_stock_drivers_paired",
        TABLE,
        "(safety_stock_demand_units IS NULL) "
        "= (safety_stock_lead_time_units IS NULL)",
        schema=SCHEMA,
    )
    # A lead-time contribution and a reason it is absent are mutually exclusive
    # claims: the reason exists precisely because the contribution is zero.
    op.create_check_constraint(
        "ck_safety_stock_lead_time_reason_excludes_contribution",
        TABLE,
        "lead_time_variability_reason_code IS NULL "
        "OR coalesce(safety_stock_lead_time_units, 0) = 0",
        schema=SCHEMA,
    )


def downgrade() -> None:
    for name in (
        "ck_safety_stock_lead_time_reason_excludes_contribution",
        "ck_safety_stock_drivers_paired",
        "ck_safety_stock_safety_stock_lead_time_units_within_total",
        "ck_safety_stock_safety_stock_demand_units_within_total",
    ):
        op.drop_constraint(name, TABLE, type_="check", schema=SCHEMA)
    for name, _ in reversed(COLUMNS):
        op.drop_column(TABLE, name, schema=SCHEMA)
