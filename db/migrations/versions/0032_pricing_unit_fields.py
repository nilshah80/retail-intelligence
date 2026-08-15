"""Add per-unit pricing fields to price recommendations (§6.0 P4).

Revision ID: 0032_pricing_unit_fields
Revises: 0031_pricing_margin_pct

Price Simulation shows Current/Proposed price on a per base selling unit basis
(for example `₹278.30 / L`) with the commercial pack shown secondarily (for
example `210 L drum`). These persisted fields carry the governed base unit and
the sellable-pack content so the read model can convert a per-unit price to the
canonical sellable-SKU minor amount exactly — never by dividing an aggregate.

All three columns are nullable: a row without a resolved unit basis (or a bundle
materialized before this migration) stays NULL and the simulation falls back to
the aggregate price without fabricating a unit value.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "0032_pricing_unit_fields"
down_revision: str | None = "0031_pricing_margin_pct"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "retail_serving"


def upgrade() -> None:
    # The base selling unit label (e.g. "L", "kg", "unit"). Per-unit prices and
    # the pack conversion are expressed against this unit.
    op.add_column(
        "price_recommendations",
        sa.Column("pricing_unit_label", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    # The sellable pack's content measured in base units (e.g. 210 for a 210 L
    # drum). per_unit_price = price_minor / base_unit_quantity; the read model
    # multiplies a proposed per-unit price back by this quantity to recover the
    # canonical sellable-SKU minor amount exactly.
    op.add_column(
        "price_recommendations",
        sa.Column("base_unit_quantity", sa.Numeric(18, 4), nullable=True),
        schema=SCHEMA,
    )
    # The commercial pack descriptor shown secondarily (e.g. "210 L drum").
    op.add_column(
        "price_recommendations",
        sa.Column("pricing_pack_label", sa.Text(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column("price_recommendations", "pricing_pack_label", schema=SCHEMA)
    op.drop_column("price_recommendations", "base_unit_quantity", schema=SCHEMA)
    op.drop_column("price_recommendations", "pricing_unit_label", schema=SCHEMA)
