"""Warehouse service metrics are origin-safe, node-grain facts."""

from __future__ import annotations

from datetime import date

import duckdb

from retail_ml.inventory_run.load import load_warehouse_capacity


def test_warehouse_service_uses_the_frozen_visible_window() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            SET TimeZone = 'UTC';
            CREATE TABLE locations (location_id VARCHAR, market_id VARCHAR);
            INSERT INTO locations VALUES ('dc-1', 'market-1'), ('dc-2', 'market-1');

            CREATE TABLE warehouse_capacity_snapshots (
                location_id VARCHAR,
                snapshot_date DATE,
                capacity_units BIGINT,
                used_units BIGINT,
                blocked_units BIGINT,
                known_as_of TIMESTAMPTZ
            );
            INSERT INTO warehouse_capacity_snapshots VALUES
                ('dc-1', DATE '2026-07-23', 900, 500, 7,
                 TIMESTAMPTZ '2026-07-23T23:00:00Z'),
                ('dc-1', DATE '2026-07-30', 1000, 600, 12,
                 TIMESTAMPTZ '2026-07-30T23:00:00Z'),
                ('dc-2', DATE '2026-07-30', 2000, 800, 0,
                 TIMESTAMPTZ '2026-07-30T23:00:00Z');

            CREATE TABLE store_shortfall_events (
                supply_location_id VARCHAR,
                event_date DATE,
                demand_units BIGINT,
                served_units BIGINT,
                known_as_of TIMESTAMPTZ
            );
            INSERT INTO store_shortfall_events VALUES
                ('dc-1', DATE '2026-05-01', 60, 45,
                 TIMESTAMPTZ '2026-05-01T23:00:00Z'),
                ('dc-1', DATE '2026-07-30', 40, 35,
                 TIMESTAMPTZ '2026-07-30T23:00:00Z'),
                -- Outside the exact 91-day window.
                ('dc-1', DATE '2026-04-30', 1000, 1000,
                 TIMESTAMPTZ '2026-04-30T23:00:00Z'),
                -- Business-effective in the window but not knowable at origin.
                ('dc-1', DATE '2026-07-29', 1000, 1000,
                 TIMESTAMPTZ '2026-08-01T00:00:00Z');
            """
        )

        frame = load_warehouse_capacity(connection, as_of=date(2026, 7, 30))
        rows = {
            row.location_id: row
            for row in frame.itertuples(index=False)
        }
        assert set(rows) == {"dc-1", "dc-2"}
        assert rows["dc-1"].capacity_units == 1000
        assert rows["dc-1"].blocked_units == 12
        assert rows["dc-1"].fill_demand_units == 100
        assert rows["dc-1"].fill_served_units == 80
        assert rows["dc-1"].fill_window_start.date() == date(2026, 5, 1)
        assert rows["dc-1"].fill_window_end.date() == date(2026, 7, 30)
        assert rows["dc-2"].fill_demand_units == 0
        assert rows["dc-2"].fill_served_units == 0
    finally:
        connection.close()
