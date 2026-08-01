"""The projection contract must be one contract, not two that agree today.

`ARTIFACT_COLUMNS` is what the publisher writes and what the materializer COPYs.
Migration 0010 is what PostgreSQL will accept. Nothing in the code makes those
agree -- so this asserts it against the live schema, column for column and in
order. A column added to one side and not the other is exactly the drift that
turns into a COPY failure during a materialization nobody can roll back halfway.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from retail_ml.inventory_publish.postgres import (
    MIGRATION_REVISION,
    SERVING_SCHEMA,
    InventoryServingError,
    activate_inventory_version,
    materialize_inventory_run,
)
from retail_ml.inventory_publish.run_artifacts import ARTIFACT_COLUMNS


def _cursor():
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL integration environment is not configured")
    import psycopg

    return psycopg.connect(dsn)


def test_every_projection_table_matches_the_published_column_contract() -> None:
    with _cursor() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM retail_intelligence_alembic_version")
            row = cursor.fetchone()
            if row is None or row[0] != MIGRATION_REVISION:
                pytest.skip(
                    f"schema is at {None if row is None else row[0]}, not "
                    f"{MIGRATION_REVISION}"
                )
            for table, columns in ARTIFACT_COLUMNS.items():
                cursor.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (SERVING_SCHEMA, table),
                )
                actual = tuple(record[0] for record in cursor.fetchall())
                assert actual, f"{table} does not exist in {SERVING_SCHEMA}"
                assert actual == ("inventory_version_id", *columns), (
                    f"{table}: schema has {actual}, the publisher writes "
                    f"{('inventory_version_id', *columns)}"
                )


def test_the_active_view_is_empty_until_something_is_activated() -> None:
    """The fail-closed default. An empty view is what makes the API's 503 a
    governed state rather than a bug, so it is asserted rather than assumed."""

    with _cursor() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT count(*) FROM {SERVING_SCHEMA}.active_inventory_versions"
            )
            row = cursor.fetchone()
            assert row is not None
            active = int(row[0])
            cursor.execute(
                f"SELECT count(*) FROM {SERVING_SCHEMA}.active_inventory_state"
            )
            state_row = cursor.fetchone()
            assert state_row is not None
            # The view can only be non-empty when the singleton points at an
            # activation whose forecast is still the active authority. Either the
            # pointer is absent and the view is empty, or both hold.
            assert active <= int(state_row[0]) <= 1


def test_the_singleton_cannot_hold_two_rows() -> None:
    """P4-D15 in the database rather than in writer discipline."""

    with _cursor() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT count(*) FROM information_schema.table_constraints
                WHERE table_schema = %s
                  AND table_name = 'active_inventory_state'
                  AND constraint_type IN ('PRIMARY KEY', 'CHECK')
                """,
                (SERVING_SCHEMA,),
            )
            row = cursor.fetchone()
            assert row is not None and int(row[0]) >= 2


# -- the refusals, exercised against the live database -------------------------

def _bundle(tmp_path) -> Any:
    """A verified bundle naming a forecast that is deliberately NOT active."""

    from test_inventory_publish import PIN, SELECTION_ID, _publish, _verify

    published = _publish(tmp_path)
    return _verify(published.root), PIN, SELECTION_ID


def test_materialization_refuses_a_bundle_whose_forecast_is_not_active(
    tmp_path,
) -> None:
    """The check that stops a silent 503.

    A bundle can verify perfectly and still name a forecast that has since been
    superseded. Loading it would put rows in the projection that the fail-closed
    active view can never join -- so the API would answer 503 while the database
    quietly held a full, unreachable materialization. Refusing here makes the
    failure something an operator can read.
    """

    verified, _, _ = _bundle(tmp_path)
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL integration environment is not configured")

    with pytest.raises(
        InventoryServingError, match="not the active .*authority|schema must be at"
    ):
        materialize_inventory_run(verified, postgres_dsn=dsn)

    with _cursor() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT count(*) FROM {SERVING_SCHEMA}.inventory_materializations
                WHERE inventory_run_id = %s
                """,
                (verified.inventory_run_id,),
            )
            row = cursor.fetchone()
            # All-or-nothing: a refused materialization leaves no partial trace.
            assert row is not None and int(row[0]) == 0
            cursor.execute(
                f"SELECT count(*) FROM {SERVING_SCHEMA}.inventory_positions"
            )
            positions = cursor.fetchone()
            assert positions is not None and int(positions[0]) == 0


def test_activation_refuses_a_run_that_was_never_materialized() -> None:
    """Activation reads the database, not the caller's word for it."""

    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL integration environment is not configured")

    with pytest.raises(InventoryServingError, match="no accepted, independently"):
        activate_inventory_version(
            postgres_dsn=dsn,
            inventory_run_id="ir_deadbeefdeadbeef",
            expected_run_semantic_fingerprint="f" * 64,
            actor="integration-test",
        )


def test_activation_refuses_an_empty_actor() -> None:
    """An activation nobody is named for is an activation nobody owns."""

    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL integration environment is not configured")

    with pytest.raises(InventoryServingError, match="actor is required"):
        activate_inventory_version(
            postgres_dsn=dsn,
            inventory_run_id="ir_deadbeefdeadbeef",
            expected_run_semantic_fingerprint="f" * 64,
            actor="   ",
        )
