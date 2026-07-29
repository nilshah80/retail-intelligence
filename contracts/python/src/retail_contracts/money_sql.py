"""DuckDB SQL fragments for the canonical integer-money contract.

The Python contract remains authoritative.  These helpers make SQL transforms
use the same closed currency/exponent map, fail closed for unknown currencies,
and avoid binary floating-point intermediates.
"""

from __future__ import annotations

from retail_contracts.money import (
    MAX_MONEY_MINOR,
    MIN_MONEY_MINOR,
    MINOR_UNIT_EXPONENT,
)


def minor_scale_sql(currency_sql: str) -> str:
    """Return a closed CASE expression for a currency's minor-unit scale."""

    branches = " ".join(
        f"WHEN '{currency}' THEN {10**exponent}"
        for currency, exponent in sorted(MINOR_UNIT_EXPONENT.items())
    )
    return f"(CASE upper({currency_sql}) {branches} ELSE NULL END)"


def exact_minor_sql(amount_sql: str, currency_sql: str) -> str:
    """Convert a previously validated exact decimal amount to signed int64."""

    scale = minor_scale_sql(currency_sql)
    return f"try_cast(trunc(({amount_sql}) * {scale}) AS BIGINT)"


def invalid_minor_sql(amount_sql: str, currency_sql: str) -> str:
    """Predicate for unknown, over-precise, or signed-int64-overflow money."""

    scale = minor_scale_sql(currency_sql)
    scaled = f"(({amount_sql}) * {scale})"
    return (
        f"({amount_sql}) IS NULL OR ({currency_sql}) IS NULL "
        f"OR {scale} IS NULL OR {scaled} <> trunc({scaled}) "
        f"OR {scaled} < {MIN_MONEY_MINOR} OR {scaled} > {MAX_MONEY_MINOR}"
    )


def allocated_minor_sql(
    total_minor_sql: str,
    fulfilled_units_sql: str,
    ordered_units_sql: str,
) -> str:
    """Allocate the first fulfilled units of a line without losing a minor unit.

    Source line totals are distributed across ordered units in stable unit
    order.  The first remainder units receive one extra minor unit.  Selecting
    the first ``fulfilled_units`` therefore yields an exact deterministic
    fulfilled share while leaving the unfulfilled share outside realized sales.
    """

    return (
        f"(({total_minor_sql}) // ({ordered_units_sql})) "
        f"* ({fulfilled_units_sql}) + least("
        f"({total_minor_sql}) % ({ordered_units_sql}), ({fulfilled_units_sql}))"
    )


__all__ = [
    "allocated_minor_sql",
    "exact_minor_sql",
    "invalid_minor_sql",
    "minor_scale_sql",
]
