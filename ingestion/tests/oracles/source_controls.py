"""Public source controls that independently validate canonical sales grain."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

SOURCE_CONTROL_PROFILE_VERSION = "retail-datagen-public-controls/1.0.0"


def _shop_markets(source_run: Path) -> tuple[tuple[str, str], ...]:
    manifest = json.loads(
        (source_run / "source-run-manifest.json").read_text(encoding="utf-8")
    )
    return tuple(
        (str(row["shopId"]), str(row["marketId"]))
        for row in manifest["topology"]["sourceInstances"]["shopify"]
    )


def _units_by_market(source_run: Path, dataset: str) -> dict[str, int]:
    result: dict[str, int] = {}
    with duckdb.connect() as connection:
        for shop_id, market_id in _shop_markets(source_run):
            path = source_run / "shopify" / shop_id / f"{dataset}.parquet"
            result[market_id] = int(
                connection.execute(
                    "SELECT coalesce(sum(try_cast(quantity AS BIGINT)), 0) "
                    "FROM read_parquet(?)",
                    [str(path)],
                ).fetchone()[0]
            )
    return result


def ordered_units_by_market(source_run: Path) -> dict[str, int]:
    """Order-line units: a demand/source control, not canonical realized sales."""

    return _units_by_market(source_run.resolve(), "order_lines")


def fulfilled_units_by_market(source_run: Path) -> dict[str, int]:
    """Successful Shopify fulfillment-line units expected in canonical sales."""

    # The fixture's fulfillment-lines dataset contains only lines belonging to
    # SUCCESS fulfillments; the adapter additionally enforces that status join.
    return _units_by_market(source_run.resolve(), "fulfillment_lines")


__all__ = [
    "SOURCE_CONTROL_PROFILE_VERSION",
    "fulfilled_units_by_market",
    "ordered_units_by_market",
]
