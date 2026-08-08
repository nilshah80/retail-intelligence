"""Replay-driver clock and channel-scope invariants."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb

from retail_ml.inventory_run.replay_driver import (
    load_market_history,
    oracle_period_diagnostics,
)


def _curated_fixture(root: Path) -> None:
    database = root / "retail_v2.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            """
            CREATE SCHEMA canonical_data;
            SET schema = 'canonical_data';

            CREATE TABLE locations (
                location_id VARCHAR, market_id VARCHAR, type VARCHAR
            );
            INSERT INTO locations VALUES ('store-1', 'market-1', 'store');

            CREATE TABLE channels (channel_id VARCHAR, type VARCHAR);
            INSERT INTO channels VALUES
                ('channel-store', 'store'),
                ('channel-marketplace', 'marketplace');

            CREATE TABLE sales (
                store_id VARCHAR, sku_id VARCHAR, channel_id VARCHAR,
                date DATE, units BIGINT, known_as_of TIMESTAMPTZ
            );
            INSERT INTO sales VALUES
                ('store-1', 'sku-1', 'channel-store', DATE '2026-01-04', 1,
                    TIMESTAMPTZ '2026-01-04T23:00:00Z'),
                ('store-1', 'sku-1', 'channel-store', DATE '2026-01-05', 1,
                    TIMESTAMPTZ '2026-01-05T23:00:00Z'),
                ('store-1', 'sku-1', 'channel-marketplace', DATE '2026-01-05', 20,
                    TIMESTAMPTZ '2026-01-05T23:00:00Z'),
                ('store-1', 'sku-1', 'channel-store', DATE '2026-01-07', 2,
                    TIMESTAMPTZ '2026-01-07T23:00:00Z'),
                ('store-1', 'sku-1', 'channel-store', DATE '2026-01-13', 3,
                    TIMESTAMPTZ '2026-01-13T23:00:00Z');

            CREATE TABLE inventory_transfer_events (
                to_location_id VARCHAR, sku_id VARCHAR,
                status_effective_at TIMESTAMPTZ, status VARCHAR, qty BIGINT,
                known_as_of TIMESTAMPTZ
            );
            INSERT INTO inventory_transfer_events VALUES
                ('store-1', 'sku-1', TIMESTAMPTZ '2026-01-08T23:00:00Z',
                    'received', 5, TIMESTAMPTZ '2026-01-08T23:00:00Z');

            CREATE TABLE waste_events (
                location_id VARCHAR, sku_id VARCHAR, event_date DATE,
                units BIGINT, known_as_of TIMESTAMPTZ
            );

            CREATE TABLE stock_snapshots (
                snapshot_date DATE, location_id VARCHAR, sku_id VARCHAR,
                on_hand_units BIGINT, known_as_of TIMESTAMPTZ
            );
            INSERT INTO stock_snapshots VALUES
                (DATE '2026-01-03', 'store-1', 'sku-1', 11,
                    TIMESTAMPTZ '2026-01-03T23:00:00Z'),
                (DATE '2026-01-06', 'store-1', 'sku-1', 9,
                    TIMESTAMPTZ '2026-01-06T23:00:00Z'),
                (DATE '2026-01-16', 'store-1', 'sku-1', 9,
                    TIMESTAMPTZ '2026-01-16T23:00:00Z');
            """
        )
    finally:
        connection.close()


def test_replay_derives_each_snapshot_bridge_and_excludes_marketplace(
    tmp_path: Path,
) -> None:
    _curated_fixture(tmp_path)

    history = load_market_history(
        tmp_path,
        market_id="market-1",
        timezone="UTC",
        as_of=date(2026, 1, 19),
        weeks=2,
    )

    # The Saturday opening snapshot advances through Sunday's store sale. A
    # fixed preceding-Thursday bridge would start from a different, invented day.
    assert history.opening_state == {("sku-1", "store-1"): 10}
    # The 20 marketplace units never touched the shelf and are not replay demand.
    first_period = next(iter(sorted(history.origins)))
    first_open = next(
        period for period in history.demand_by_period
        if period.date() == first_period
    )
    assert sum(history.demand_by_period[first_open].values()) == 3

    diagnostics = oracle_period_diagnostics(history)
    assert diagnostics == [
        {
            "periodOpen": "2026-01-05",
            "snapshotDates": ["2026-01-06"],
            "bridgeStart": "2026-01-07",
            "bridgeEnd": "2026-01-11",
            "bridgeDaysMin": 5,
            "bridgeDaysMax": 5,
            "snapshotCells": 1,
            "arrivalWeek": True,
            "arrivalUnits": 5,
            "bridgeArrivalUnits": 5,
            "reconstructedClosingUnits": 12,
            "observedClosingUnits": 12,
            "signedDeltaUnits": 0,
            "absDeltaPerCell": "0",
        },
        {
            "periodOpen": "2026-01-12",
            "snapshotDates": ["2026-01-16"],
            "bridgeStart": "2026-01-17",
            "bridgeEnd": "2026-01-18",
            "bridgeDaysMin": 2,
            "bridgeDaysMax": 2,
            "snapshotCells": 1,
            "arrivalWeek": False,
            "arrivalUnits": 0,
            "bridgeArrivalUnits": 0,
            "reconstructedClosingUnits": 9,
            "observedClosingUnits": 9,
            "signedDeltaUnits": 0,
            "absDeltaPerCell": "0",
        },
    ]
