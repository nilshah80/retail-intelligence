"""Make pricing selection and activation evidence fully append-only.

Revision ID: 0029_pricing_events
Revises: 0028_pricing_serving
"""

from __future__ import annotations

import hashlib
import json
import uuid

from alembic import op
import sqlalchemy as sa


revision: str = "0029_pricing_events"
down_revision: str | None = "0028_pricing_serving"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA = "retail_serving"


def _canonical_sha(document: object) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def upgrade() -> None:
    op.drop_constraint(
        "uq_pricing_selection_lifecycle",
        "pricing_result_selection_events",
        schema=SCHEMA,
        type_="unique",
    )
    op.add_column(
        "pricing_result_selection_events",
        sa.Column("record_id", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "pricing_result_selection_events",
        sa.Column("record_sha256", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "pricing_result_selection_events",
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "pricing_activation_sets",
        sa.Column("activation_set_sha256", sa.Text(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "pricing_activation_sets",
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        schema=SCHEMA,
    )

    connection = op.get_bind()
    selections = connection.execute(
        sa.text(
            f"SELECT event_id, review_evidence FROM {SCHEMA}.pricing_result_selection_events"
        )
    ).mappings()
    for row in selections:
        evidence = row["review_evidence"]
        record_id = str(evidence["recordId"])
        transaction_id = uuid.uuid5(uuid.NAMESPACE_URL, f"pricing-selection:{record_id}")
        connection.execute(
            sa.text(
                f"UPDATE {SCHEMA}.pricing_result_selection_events "
                "SET record_id=:record_id, record_sha256=:record_sha256, "
                "transaction_id=:transaction_id WHERE event_id=:event_id"
            ),
            {
                "record_id": record_id,
                "record_sha256": _canonical_sha(evidence),
                "transaction_id": transaction_id,
                "event_id": row["event_id"],
            },
        )
    activations = connection.execute(
        sa.text(
            f"SELECT activation_event_id, evidence FROM {SCHEMA}.pricing_activation_sets"
        )
    ).mappings()
    for row in activations:
        evidence = row["evidence"]
        activation_id = str(evidence["activationSetId"])
        transaction_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"pricing-activation:{activation_id}"
        )
        connection.execute(
            sa.text(
                f"UPDATE {SCHEMA}.pricing_activation_sets "
                "SET activation_set_sha256=:activation_set_sha256, "
                "transaction_id=:transaction_id "
                "WHERE activation_event_id=:activation_event_id"
            ),
            {
                "activation_set_sha256": _canonical_sha(evidence),
                "transaction_id": transaction_id,
                "activation_event_id": row["activation_event_id"],
            },
        )

    for table, columns in (
        (
            "pricing_result_selection_events",
            ("record_id", "record_sha256", "transaction_id"),
        ),
        ("pricing_activation_sets", ("activation_set_sha256", "transaction_id")),
    ):
        for column in columns:
            op.alter_column(table, column, nullable=False, schema=SCHEMA)
    op.create_unique_constraint(
        "uq_pricing_selection_record_id",
        "pricing_result_selection_events",
        ["record_id"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_pricing_selection_record_sha256",
        "pricing_result_selection_events",
        ["record_sha256"],
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_pricing_activation_set_sha256",
        "pricing_activation_sets",
        ["activation_set_sha256"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_pricing_selection_scope_lifecycle",
        "pricing_result_selection_events",
        ["retailer_id", "tenant_id", "environment", "selection_id", "lifecycle_status"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pricing_selection_scope_lifecycle",
        table_name="pricing_result_selection_events",
        schema=SCHEMA,
    )
    op.drop_constraint(
        "uq_pricing_activation_set_sha256",
        "pricing_activation_sets",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "uq_pricing_selection_record_sha256",
        "pricing_result_selection_events",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_constraint(
        "uq_pricing_selection_record_id",
        "pricing_result_selection_events",
        schema=SCHEMA,
        type_="unique",
    )
    op.drop_column("pricing_activation_sets", "transaction_id", schema=SCHEMA)
    op.drop_column(
        "pricing_activation_sets", "activation_set_sha256", schema=SCHEMA
    )
    op.drop_column(
        "pricing_result_selection_events", "transaction_id", schema=SCHEMA
    )
    op.drop_column(
        "pricing_result_selection_events", "record_sha256", schema=SCHEMA
    )
    op.drop_column("pricing_result_selection_events", "record_id", schema=SCHEMA)
    op.create_unique_constraint(
        "uq_pricing_selection_lifecycle",
        "pricing_result_selection_events",
        ["selection_id", "lifecycle_status"],
        schema=SCHEMA,
    )
