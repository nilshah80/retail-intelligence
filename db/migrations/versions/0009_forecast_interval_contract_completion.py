"""Make interval availability explicit and admit exactly two row states.

`P4-1` task 5. Migration 0008 made the withheld interval *storable*; it did not
make availability *stated*. Four gaps survived it, and each one lets a row be
written that the decision-#92 contract forbids:

* Availability was inferred from `yhat_p90 IS NULL` in Go and in the read model.
  An inferred flag cannot distinguish "withheld under a governed policy" from
  "the writer lost the value", so the projection had no way to refuse the second.
* `forecast_series_withheld_reason` requires a reason when the interval is
  absent, but permits one when it is present. A row carrying a real P90 *and*
  `COLD_START_INTERVAL_UNCALIBRATED` was accepted, which is a self-contradicting
  row that any consumer branching on the reason would mishandle.
* The reason column is free text, so a typo produced a reason code no policy
  defines and nothing objected.
* Nothing enforced `yhat_p90 >= yhat_p50` on an available interval, so an
  inverted quantile pair was storable at row level.

After this migration exactly two row states exist, and the database is what
enforces it rather than the publisher's good intentions:

    available = true   ->  p90 NOT NULL, confidence NOT NULL, reason NULL,
                           p90 >= p50
    available = false  ->  p90 NULL,     confidence NULL,     reason governed

`yhat_p50` remains NOT NULL throughout: decision #92 withdraws a distribution
claim, never a forecast.

The backfill derives availability from the existing nullability, which is correct
for exactly this transition because 0008's pairing constraint already guaranteed
p90 and confidence move together. It is the last time availability is inferred.

Revision ID: 0009_forecast_interval_contract
Revises: 0008_nullable_withheld_interval
Create Date: 2026-08-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_forecast_interval_contract"
down_revision: str | Sequence[str] | None = "0008_nullable_withheld_interval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"

#: The only reason a withheld interval may carry. Extending this list is a
#: decision, not a configuration change: decision #92 states that widening the
#: calibrated range needs a new preregistered mechanism, and a second reason code
#: would be a second mechanism arriving without one.
GOVERNED_REASONS = ("COLD_START_INTERVAL_UNCALIBRATED",)


def upgrade() -> None:
    op.add_column(
        "forecast_series",
        sa.Column(
            "interval_available",
            sa.Boolean(),
            nullable=True,
            comment=(
                "Explicit decision-#92 availability. Never inferred from "
                "yhat_p90 nullability by any consumer."
            ),
        ),
        schema=SCHEMA,
    )
    # Last inferred derivation. 0008's pairing constraint guarantees p90 and
    # confidence are null together, so nullability is a sound source here and
    # nowhere afterwards.
    op.execute(
        f"""
        UPDATE {SCHEMA}.forecast_series
        SET interval_available = (yhat_p90 IS NOT NULL)
        """
    )
    op.alter_column(
        "forecast_series", "interval_available", nullable=False, schema=SCHEMA
    )

    reasons = ", ".join(f"'{reason}'" for reason in GOVERNED_REASONS)
    # One constraint per rule rather than one compound rule, so a violation names
    # which invariant broke instead of reporting that "the row is invalid".
    op.create_check_constraint(
        "forecast_series_availability_matches_interval",
        "forecast_series",
        "interval_available = (yhat_p90 IS NOT NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "forecast_series_available_interval_has_no_reason",
        "forecast_series",
        "NOT interval_available OR interval_unavailable_reason IS NULL",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "forecast_series_withheld_reason_is_governed",
        "forecast_series",
        f"interval_available OR interval_unavailable_reason IN ({reasons})",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        "forecast_series_available_interval_is_ordered",
        "forecast_series",
        "NOT interval_available OR yhat_p90 >= yhat_p50",
        schema=SCHEMA,
    )
    op.create_index(
        "ix_forecast_series_interval_available",
        "forecast_series",
        ["version_id", "interval_available"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_forecast_series_interval_available",
        table_name="forecast_series",
        schema=SCHEMA,
    )
    for name in (
        "forecast_series_available_interval_is_ordered",
        "forecast_series_withheld_reason_is_governed",
        "forecast_series_available_interval_has_no_reason",
        "forecast_series_availability_matches_interval",
    ):
        op.drop_constraint(
            name, "forecast_series", schema=SCHEMA, type_="check"
        )
    # Dropping the column returns availability to being inferred. That is a real
    # loss of contract rather than a clean rollback, which is why the note exists:
    # 0008's weaker guarantees are what remain.
    op.drop_column("forecast_series", "interval_available", schema=SCHEMA)
