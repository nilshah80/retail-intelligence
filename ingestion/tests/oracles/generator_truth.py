"""Profile-versioned translation from restricted generator truth to retail_v2 controls.

This module intentionally lives under tests. It is an evaluation-admin consumer of
the restricted ``_truth`` lane and is never available to production transforms.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

ORACLE_PROFILE_VERSION = "retail-datagen-hidden-control-oracle/1.0.0"


def expected_units_by_market(source_run: Path) -> dict[str, int]:
    """Read generator-realized order demand from the restricted truth lane.

    This is an order/demand control. It is intentionally not the expected
    canonical sales measure because a later fulfillment failure can make
    fulfilled/realized retail sales lower than generated order-line units.
    """

    truth = source_run.resolve() / "_truth" / "demand_factors" / "**" / "*.parquet"
    if "_truth" not in truth.parts:
        raise ValueError("the evaluation oracle may only read the restricted truth lane")
    with duckdb.connect() as connection:
        rows = connection.execute(
            """
            SELECT marketKey, SUM(CAST(realizedSalesUnits AS BIGINT)) AS units
            FROM read_parquet(?, hive_partitioning = true)
            GROUP BY marketKey
            ORDER BY marketKey
            """,
            [str(truth)],
        ).fetchall()
    return {str(market): int(units) for market, units in rows}


def actual_units_by_market(curated_database: Path) -> dict[str, int]:
    """Read fulfilled/realized units from a curated publication."""

    with duckdb.connect(str(curated_database.resolve()), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT stores.market_id, SUM(sales.units) AS units
            FROM canonical_data.sales AS sales
            JOIN canonical_data.stores AS stores
              ON stores.store_id = sales.store_id
            GROUP BY stores.market_id
            ORDER BY stores.market_id
            """
        ).fetchall()
    return {str(market): int(units) for market, units in rows}
