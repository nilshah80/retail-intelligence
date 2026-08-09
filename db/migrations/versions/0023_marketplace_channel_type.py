"""Admit the source-authoritative marketplace forecast channel type.

Datagen, Config Builder, and ingestion all define the channel domain as
``store | online | marketplace``. Migration 0003 predated marketplace support and
kept a narrower check, so an otherwise valid Gulf run failed only when its display
dimensions reached PostgreSQL.

Revision ID: 0023_marketplace_channel_type
Revises: 0022_expected_volume_forecast
Create Date: 2026-08-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0023_marketplace_channel_type"
down_revision: str | Sequence[str] | None = "0022_expected_volume_forecast"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "retail_serving"
TABLE = "forecast_series_dimensions"
CONSTRAINT = "ck_forecast_series_dimension_channel_type"


def _replace_channel_type_check(values: tuple[str, ...]) -> None:
    op.drop_constraint(
        CONSTRAINT,
        TABLE,
        schema=SCHEMA,
        type_="check",
    )
    allowed = ", ".join(f"'{value}'" for value in values)
    op.create_check_constraint(
        CONSTRAINT,
        TABLE,
        f"channel_type IN ({allowed})",
        schema=SCHEMA,
    )


def upgrade() -> None:
    _replace_channel_type_check(("online", "store", "marketplace"))


def downgrade() -> None:
    _replace_channel_type_check(("online", "store"))
