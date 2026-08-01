"""Migration 0009's interval truth table must refuse every invalid row state.

`P4-1` task 5. Migration 0008 made a withheld interval *storable*. It did not make
availability *stated*, so four contradictions remained writable: a row whose
availability disagreed with its own interval, an available interval carrying an
unavailability reason, a reason code no policy defines, and an inverted quantile
pair.

A constraint that is never exercised against a violating row is a comment. Each
test below writes the row the contract forbids and requires the database to
reject it, so the guarantee is demonstrated rather than asserted.

Exactly two row states are legal:

    available = true   ->  p90 NOT NULL, confidence NOT NULL, reason NULL,
                           p90 >= p50
    available = false  ->  p90 NULL,     confidence NULL,     reason governed
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest

SCHEMA = "retail_serving"


def _dsn() -> str:
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL schema integration environment is not configured")
    return dsn


@contextmanager
def _probe_row() -> Iterator[Any]:
    """Yield a cursor inside a transaction that is always rolled back.

    The live projection is real serving data. Every probe below writes a
    deliberately invalid row, so nothing may survive the test -- the rollback is
    the isolation, not a cleanup step that could be skipped on failure.
    """

    with psycopg.connect(_dsn()) as connection:
        connection.autocommit = False
        with connection.cursor() as cursor:
            try:
                yield cursor
            finally:
                connection.rollback()


def _template(cursor: Any) -> dict[str, Any] | None:
    """Copy a real served row so a probe differs only in what it is testing."""

    cursor.execute(
        f"""
        SELECT version_id, forecast_run_id, market_id, sku_id, store_id,
               channel_id, dept_id, category, horizon_week, target_week_start,
               yhat_p50, yhat_p90, confidence, data_quality_class
        FROM {SCHEMA}.forecast_series
        WHERE interval_available
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [description[0] for description in cursor.description]
    return dict(zip(columns, row, strict=True))


def _insert(cursor: Any, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join(f"%({name})s" for name in row)
    cursor.execute(
        f"INSERT INTO {SCHEMA}.forecast_series ({columns}) VALUES ({placeholders})",
        row,
    )


def _probe(**overrides: Any) -> None:
    with _probe_row() as cursor:
        template = _template(cursor)
        if template is None:
            pytest.skip("no materialized forecast series row to base a probe on")
        # A distinct horizon keeps the probe from colliding with the row it copied.
        template["horizon_week"] = 99
        template["interval_available"] = True
        template["interval_unavailable_reason"] = None
        template.update(overrides)
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert(cursor, template)


def test_availability_true_with_a_null_interval_is_refused() -> None:
    """Claiming an interval exists while storing none is the core contradiction."""

    _probe(interval_available=True, yhat_p90=None, confidence=None)


def test_availability_false_with_a_present_interval_is_refused() -> None:
    """The inverse hides a published interval behind an unavailable flag."""

    _probe(
        interval_available=False,
        interval_unavailable_reason="COLD_START_INTERVAL_UNCALIBRATED",
    )


def test_an_available_interval_may_not_carry_an_unavailability_reason() -> None:
    """0008 permitted this. A row asserting both is unhandleable by any consumer."""

    _probe(
        interval_available=True,
        interval_unavailable_reason="COLD_START_INTERVAL_UNCALIBRATED",
    )


def test_a_withheld_interval_must_carry_a_governed_reason_code() -> None:
    """Free text let a typo produce a reason no policy defines."""

    _probe(
        interval_available=False,
        yhat_p90=None,
        confidence=None,
        interval_unavailable_reason="SOMETHING_PLAUSIBLE_BUT_UNGOVERNED",
    )


def test_a_withheld_interval_must_carry_some_reason() -> None:
    _probe(
        interval_available=False,
        yhat_p90=None,
        confidence=None,
        interval_unavailable_reason=None,
    )


def test_an_inverted_quantile_pair_is_refused() -> None:
    """P90 below P50 is not a weak interval, it is not an interval."""

    with _probe_row() as cursor:
        template = _template(cursor)
        if template is None:
            pytest.skip("no materialized forecast series row to base a probe on")
        template["horizon_week"] = 99
        template["interval_available"] = True
        template["interval_unavailable_reason"] = None
        template["yhat_p50"] = 100.0
        template["yhat_p90"] = 50.0
        with pytest.raises(psycopg.errors.CheckViolation):
            _insert(cursor, template)


def test_the_interval_and_its_confidence_move_together() -> None:
    """Inherited from 0008 and still binding: a confidence without its interval
    asserts a certainty nothing supports."""

    _probe(interval_available=False, yhat_p90=None, confidence=0.5)


def test_p50_is_never_nullable() -> None:
    """Decision #92 withdraws a distribution claim, never a forecast."""

    with _probe_row() as cursor:
        cursor.execute(
            f"""
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_schema = '{SCHEMA}'
              AND table_name = 'forecast_series'
              AND column_name = 'yhat_p50'
            """
        )
        row = cursor.fetchone()
        assert row is not None, "forecast_series.yhat_p50 does not exist"
        assert row[0] == "NO"


def test_the_live_projection_satisfies_the_truth_table() -> None:
    """The constraints guarantee this going forward; this proves it holds now."""

    with psycopg.connect(_dsn()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT
                    count(*) FILTER (
                        WHERE interval_available <> (yhat_p90 IS NOT NULL)
                    ),
                    count(*) FILTER (
                        WHERE interval_available
                          AND interval_unavailable_reason IS NOT NULL
                    ),
                    count(*) FILTER (
                        WHERE NOT interval_available
                          AND interval_unavailable_reason IS DISTINCT FROM
                              'COLD_START_INTERVAL_UNCALIBRATED'
                    ),
                    count(*) FILTER (
                        WHERE interval_available AND yhat_p90 < yhat_p50
                    ),
                    count(*) FILTER (WHERE (yhat_p90 IS NULL) <> (confidence IS NULL))
                FROM {SCHEMA}.forecast_series
                """
            )
            row = cursor.fetchone()
            assert row is not None
            assert row == (0, 0, 0, 0, 0), (
                "the live projection violates the interval truth table: "
                f"availability mismatch={row[0]}, reason on available={row[1]}, "
                f"ungoverned reason={row[2]}, inverted pair={row[3]}, "
                f"unpaired confidence={row[4]}"
            )
