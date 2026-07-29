"""SQL money fragments must preserve the Python integer-money contract."""

from __future__ import annotations

import duckdb

from retail_contracts.money_sql import (
    allocated_minor_sql,
    exact_minor_sql,
    invalid_minor_sql,
    minor_scale_sql,
)


def test_minor_sql_fails_closed_and_never_rounds_precision_loss() -> None:
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"""
            SELECT
                {minor_scale_sql("currency")} AS scale,
                {exact_minor_sql("amount", "currency")} AS minor,
                {invalid_minor_sql("amount", "currency")} AS invalid
            FROM (
                VALUES
                    ('USD', 1.23::DECIMAL(38, 6)),
                    ('USD', 1.005::DECIMAL(38, 6)),
                    ('JPY', 1.00::DECIMAL(38, 6))
            ) AS input(currency, amount)
            """
        ).fetchall()
    finally:
        connection.close()

    assert rows == [
        (100, 123, False),
        (100, 100, True),
        (None, None, True),
    ]


def test_fulfilled_money_allocation_is_integer_and_deterministic() -> None:
    connection = duckdb.connect(":memory:")
    try:
        values = connection.execute(
            f"""
            SELECT
                {
                    allocated_minor_sql(
                        "total_minor", "fulfilled_units", "ordered_units"
                    )
                } AS allocated
            FROM (
                VALUES
                    (101::HUGEINT, 1::BIGINT, 3::BIGINT),
                    (101::HUGEINT, 2::BIGINT, 3::BIGINT),
                    (101::HUGEINT, 3::BIGINT, 3::BIGINT)
            ) AS input(total_minor, fulfilled_units, ordered_units)
            """
        ).fetchall()
    finally:
        connection.close()

    assert values == [(34,), (68,), (101,)]
