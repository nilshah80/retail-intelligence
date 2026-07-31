"""Allow a withheld cold-start interval to be stored.

Decision #92 publishes no P90 for a cold-start row beyond the calibrated horizon, because
three candidates failed to calibrate the full range and the measured coverage falls to
0.7798 by h14-h26. `forecast_series` declared `yhat_p90` and `confidence` NOT NULL, so a
correctly withheld bundle could not be materialised at all: the publisher withheld and
PostgreSQL refused, which left serving carrying the uncalibrated value while the
acceptance gate was scoped to the calibrated range.

Nullable is the honest representation. A sentinel number would be worse than a null,
because safety stock is quantile spread x service level and any placeholder would be
arithmetically consumed -- a zero would return zero safety stock on precisely the newest,
least predictable products. A null forces a consumer to branch.

`interval_unavailable_reason` is added so the absence is attributable rather than merely
present, and P50 stays NOT NULL: this withdraws a distribution claim, never a forecast.

Revision ID: 0008_nullable_withheld_interval
Revises: 0007_activation_and_coverage
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_nullable_withheld_interval"
down_revision: str | Sequence[str] | None = "0007_activation_and_coverage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    for column in ("yhat_p90", "confidence"):
        op.alter_column(
            "forecast_series", column, nullable=True, schema=SCHEMA
        )
    op.add_column(
        "forecast_series",
        sa.Column("interval_unavailable_reason", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    # Both fields move together: a confidence without its interval would assert a
    # certainty nothing supports, and an interval without confidence hides a derived
    # value the contract requires. Enforced in the database so no writer can split them.
    op.create_check_constraint(
        "forecast_series_interval_pairing",
        "forecast_series",
        "(yhat_p90 IS NULL) = (confidence IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "forecast_series_withheld_reason",
        "forecast_series",
        "(yhat_p90 IS NOT NULL) OR (interval_unavailable_reason IS NOT NULL)",
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_constraint(
        "forecast_series_withheld_reason",
        "forecast_series",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_constraint(
        "forecast_series_interval_pairing",
        "forecast_series",
        schema=SCHEMA,
        type_="check",
    )
    op.drop_column("forecast_series", "interval_unavailable_reason", schema=SCHEMA)
    # Rows with a withheld interval cannot be represented under the old contract, so a
    # rollback must delete them rather than invent a value for them.
    op.execute(f"DELETE FROM {SCHEMA}.forecast_series WHERE yhat_p90 IS NULL")
    for column in ("yhat_p90", "confidence"):
        op.alter_column(
            "forecast_series", column, nullable=False, schema=SCHEMA
        )
