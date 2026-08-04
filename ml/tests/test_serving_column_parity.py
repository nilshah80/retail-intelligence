"""Every serving writer's column list must match the schema it writes into.

This test exists because its absence cost a full pipeline run. Migration 0009
added an explicit NOT NULL `interval_available` to `retail_serving.forecast_series`
and `serving/postgres.py`'s `TABLE_COLUMNS` was never updated, so the COPY omitted
the column and PostgreSQL rejected every row -- after the ten-year refit had
already spent forty minutes fitting models.

Nothing in the code makes a hand-maintained Python tuple agree with an Alembic
migration. The inventory side got this check when its projection tables were
built; the forecast side, which is older, never had one. Both are covered here so
the next added column fails in under a second instead of at the end of a
materialization.

The check compares SETS, exactly, in both directions. A superset would let a
stale writer pass while silently omitting a nullable column, and a subset means
the writer names a column the schema does not have.

It deliberately does NOT compare order against the schema, and the first version
of this test got that wrong too. `ALTER TABLE ADD COLUMN` appends, so 0009's two
new columns sit at the end of `forecast_series` physically while the writer's
tuple groups them with the other interval fields -- and that is fine, because
`_copy_frame` emits `COPY table (col, col, ...)` naming every column, so
PostgreSQL maps by name. What order DOES matter for is the tuple against the
DATAFRAME, since `itertuples` yields positionally; `prepare_serving_projection`
reindexes every frame with `frame[list(TABLE_COLUMNS[name])]` and asserts the
match at runtime, which is the right place for it. Asserting physical order here
would fail on the next ADD COLUMN while proving nothing.
"""

from __future__ import annotations

import os

import pytest

from retail_ml.inventory_publish.postgres import (
    MIGRATION_REVISION as INVENTORY_REVISION,
)
from retail_ml.inventory_publish.run_artifacts import ARTIFACT_COLUMNS
from retail_ml.serving.postgres import (
    MIGRATION_REVISION as FORECAST_REVISION,
    SERVING_SCHEMA,
    TABLE_COLUMNS,
)


#: Columns the database fills in. A writer that named one would be overriding an
#: audit timestamp with a value it chose.
SERVER_MANAGED = {"created_at", "updated_at", "materialized_at"}


def _connection():
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL integration environment is not configured")
    import psycopg

    return psycopg.connect(dsn)


def _actual_columns(cursor, table: str) -> tuple[str, ...]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (SERVING_SCHEMA, table),
    )
    return tuple(row[0] for row in cursor.fetchall())


def test_the_two_writers_agree_on_the_migration_head() -> None:
    """A forecast writer pinned to 0009 and an inventory writer pinned to 0010
    would each refuse the other's schema, so exactly one head is servable."""

    assert FORECAST_REVISION == INVENTORY_REVISION


def test_every_forecast_table_column_list_matches_the_live_schema() -> None:
    with _connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version_num FROM retail_intelligence_alembic_version")
            row = cursor.fetchone()
            if row is None or row[0] != FORECAST_REVISION:
                pytest.skip(
                    f"schema is at {None if row is None else row[0]}, not "
                    f"{FORECAST_REVISION}"
                )
            for table, declared in TABLE_COLUMNS.items():
                actual = _actual_columns(cursor, table)
                assert actual, f"{table} does not exist in {SERVING_SCHEMA}"
                # Server-managed columns are never written by the COPY.
                writable = set(actual) - SERVER_MANAGED
                missing = sorted(writable - set(declared))
                unknown = sorted(set(declared) - writable)
                assert not missing, (
                    f"{table}: the schema has {missing} and the writer omits them; "
                    "a NOT NULL column omitted from the COPY rejects every row"
                )
                assert not unknown, (
                    f"{table}: the writer names {unknown}, which the schema does "
                    "not have"
                )


def test_the_forecast_series_availability_column_is_written() -> None:
    """The specific regression, named so it cannot be quietly reintroduced."""

    assert "interval_available" in TABLE_COLUMNS["forecast_series"]
    assert "interval_unavailable_reason" in TABLE_COLUMNS["forecast_series"]
    # Both halves of decision #92's pairing, or neither. A writer that populates
    # the flag without the reason trips 0009's CHECK on the first withheld row.


def test_no_table_is_declared_by_both_writers() -> None:
    """One table with two writers has two column lists to keep in step, and the
    second one to be updated wins by accident."""

    overlap = set(TABLE_COLUMNS) & set(ARTIFACT_COLUMNS)
    assert not overlap, f"{sorted(overlap)} is written by both writers"
