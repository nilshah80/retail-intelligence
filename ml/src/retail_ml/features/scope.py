"""Fail-closed guards for market-qualified contextual joins."""

from __future__ import annotations

from collections.abc import Iterable


class ScopeJoinError(ValueError):
    """A contextual join could cross markets or scopes."""


def assert_market_qualified_join(
    join_columns: Iterable[str],
    *,
    require_geo_scope: bool,
) -> tuple[str, ...]:
    columns = tuple(join_columns)
    column_set = set(columns)
    if "market_id" not in column_set:
        raise ScopeJoinError("contextual joins must include market_id")
    if require_geo_scope and not {
        "geo_scope_type",
        "geo_scope_id",
    } <= column_set:
        raise ScopeJoinError(
            "scoped contextual joins must include geo_scope_type and geo_scope_id"
        )
    if {"region", "city"} & column_set and "market_id" not in column_set:
        raise ScopeJoinError("free-form geography is never a global join key")
    return columns


__all__ = ["ScopeJoinError", "assert_market_qualified_join"]
