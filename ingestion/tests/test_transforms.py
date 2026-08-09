"""Source-neutral transform invariants that do not need the full pinned run."""

from __future__ import annotations

from datetime import date

import duckdb

from retail_ingestion.transforms.core import (
    _channel_type_sql,
    _create_stock_snapshots,
    _densify_sales,
)


def test_channel_type_preserves_marketplace_semantics() -> None:
    connection = duckdb.connect(":memory:")
    try:
        rows = connection.execute(
            f"""
            SELECT channel_key, {_channel_type_sql("channel_key")} AS channel_type
            FROM (VALUES
                ('bazaar-trade'),
                ('gulf-online'),
                ('gulf-marketplace'),
                ('PARTNER-MARKETPLACE')
            ) AS source(channel_key)
            ORDER BY channel_key
            """
        ).fetchall()
        assert rows == [
            ("PARTNER-MARKETPLACE", "marketplace"),
            ("bazaar-trade", "store"),
            ("gulf-marketplace", "marketplace"),
            ("gulf-online", "online"),
        ]
    finally:
        connection.close()


def test_stock_buckets_use_snapshot_visible_status_and_remain_disjoint() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            SET TimeZone = 'UTC';
            ATTACH ':memory:' AS stage;
            CREATE SCHEMA canonical_data;
            CREATE SCHEMA stage.stage_data;

            CREATE TABLE stage.stage_data.location_crosswalk (
                source_system VARCHAR,
                market_id VARCHAR,
                source_location_key VARCHAR,
                canonical_location_key VARCHAR
            );
            INSERT INTO stage.stage_data.location_crosswalk VALUES
                ('businessCentral', 'market-1', 'dc-1', 'dc-1');

            CREATE TABLE stage.stage_data.inventory (
                source_system VARCHAR,
                source_instance VARCHAR,
                market_id VARCHAR,
                sku_source_key VARCHAR,
                location_source_key VARCHAR,
                snapshot_date DATE,
                oldest_receipt_date DATE,
                on_hand_units BIGINT,
                incoming_units BIGINT,
                committed_units BIGINT,
                reserved_units BIGINT,
                damaged_units BIGINT,
                quality_control_units BIGINT,
                safety_stock_units BIGINT,
                known_as_of TIMESTAMPTZ,
                evidence_grade VARCHAR
            );
            INSERT INTO stage.stage_data.inventory VALUES
                (
                    'businessCentral', 'bc-1', 'market-1', 'sku-1', 'dc-1',
                    DATE '2026-01-10', DATE '2025-12-20', 100, 50, 10, 3, 2, 5, 7,
                    TIMESTAMPTZ '2026-01-10T23:00:00Z', 'native_observed'
                ),
                (
                    'businessCentral', 'bc-1', 'market-1', 'sku-1', 'dc-1',
                    DATE '2026-01-12', DATE '2025-12-20', 100, 0, 10, 3, 2, 5, 7,
                    TIMESTAMPTZ '2026-01-12T23:00:00Z', 'native_observed'
                );

            CREATE TABLE stage.stage_data.inbound_status_events (
                source_system VARCHAR,
                source_instance VARCHAR,
                market_id VARCHAR,
                sku_source_key VARCHAR,
                location_source_key VARCHAR,
                source_shipment_id VARCHAR,
                native_record_id VARCHAR,
                qty BIGINT,
                status VARCHAR,
                status_effective_at TIMESTAMPTZ,
                known_as_of TIMESTAMPTZ
            );
            INSERT INTO stage.stage_data.inbound_status_events VALUES
                (
                    'businessCentral', 'bc-1', 'market-1', 'sku-1', 'dc-1',
                    'shipment-1', 'shipment-1:on_order', 30, 'on_order',
                    TIMESTAMPTZ '2026-01-08T08:00:00Z',
                    TIMESTAMPTZ '2026-01-08T10:00:00Z'
                ),
                (
                    'businessCentral', 'bc-1', 'market-1', 'sku-1', 'dc-1',
                    'shipment-1', 'shipment-1:in_transit', 30, 'in_transit',
                    TIMESTAMPTZ '2026-01-09T08:00:00Z',
                    TIMESTAMPTZ '2026-01-09T10:00:00Z'
                ),
                (
                    'businessCentral', 'bc-1', 'market-1', 'sku-1', 'dc-1',
                    'shipment-1', 'shipment-1:received', 30, 'received',
                    TIMESTAMPTZ '2026-01-10T20:00:00Z',
                    TIMESTAMPTZ '2026-01-11T10:00:00Z'
                );
            """
        )

        _create_stock_snapshots(connection)

        assert connection.execute(
            """
            SELECT
                snapshot_date, oldest_receipt_date, on_order_units, in_transit_units,
                reserved_units, damaged_units, atp_units,
                on_order_units + in_transit_units AS incoming_units
            FROM canonical_data.stock_snapshots
            ORDER BY snapshot_date
            """
        ).fetchall() == [
            (date(2026, 1, 10), date(2025, 12, 20), 20, 30, 10, 7, 73, 50),
            (date(2026, 1, 12), date(2025, 12, 20), 0, 0, 10, 7, 73, 0),
        ]
    finally:
        connection.close()


def test_sales_densification_is_limited_to_active_assortment_dates() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            CREATE SCHEMA canonical_data;
            CREATE TABLE canonical_data.stores (
                store_id VARCHAR,
                market_id VARCHAR,
                currency_code VARCHAR,
                timezone VARCHAR
            );
            INSERT INTO canonical_data.stores VALUES
                ('store-1', 'market-1', 'USD', 'America/New_York');

            CREATE TABLE canonical_data.calendar (
                market_id VARCHAR,
                date DATE
            );
            INSERT INTO canonical_data.calendar VALUES
                ('market-1', DATE '2026-01-01'),
                ('market-1', DATE '2026-01-02'),
                ('market-1', DATE '2026-01-03'),
                ('market-1', DATE '2026-01-04');

            CREATE TABLE canonical_data.assortment_calendar (
                sku_id VARCHAR,
                store_id VARCHAR,
                channel_id VARCHAR,
                active_from DATE,
                active_to DATE,
                known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            );
            INSERT INTO canonical_data.assortment_calendar VALUES
                (
                    'sku-1', 'store-1', 'channel-1',
                    DATE '2026-01-01', DATE '2026-01-03',
                    TIMESTAMPTZ '2026-02-01T00:00:00Z', 'landing_backfill'
                ),
                (
                    'sku-1', 'store-1', 'channel-1',
                    DATE '2026-01-01', DATE '2026-01-03',
                    TIMESTAMPTZ '2026-01-31T00:00:00Z', 'landing_backfill'
                );

            CREATE TABLE canonical_data.sales (
                sku_id VARCHAR,
                store_id VARCHAR,
                channel_id VARCHAR,
                date DATE,
                sales_version INTEGER,
                units BIGINT,
                gross_sales_amount BIGINT,
                discount_amount BIGINT,
                net_sales_amount BIGINT,
                tax_amount BIGINT,
                currency_code VARCHAR,
                net_price BIGINT,
                promo_flag BOOLEAN,
                known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            );
            INSERT INTO canonical_data.sales VALUES
                (
                    'sku-1', 'store-1', 'channel-1', DATE '2026-01-02',
                    1, 2, 2000, 0, 1800, 200, 'USD', 900, false,
                    TIMESTAMPTZ '2026-01-02T12:00:00Z', 'native_processed'
                );
            """
        )

        _densify_sales(connection)

        assert connection.execute(
            """
            SELECT date, units, net_price, known_as_of_evidence_grade
            FROM canonical_data.sales
            ORDER BY date
            """
        ).fetchall() == [
            (
                date(2026, 1, 1),
                0,
                None,
                "landing_backfill",
            ),
            (
                date(2026, 1, 2),
                2,
                900,
                "native_processed",
            ),
            (
                date(2026, 1, 3),
                0,
                None,
                "landing_backfill",
            ),
        ]
        assert connection.execute(
            "SELECT count(*) FROM canonical_data.sales WHERE date = DATE '2026-01-04'"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_native_assortment_makes_zero_sale_visible_after_business_day() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute(
            """
            SET TimeZone = 'UTC';
            CREATE SCHEMA canonical_data;
            CREATE TABLE canonical_data.stores (
                store_id VARCHAR,
                market_id VARCHAR,
                currency_code VARCHAR,
                timezone VARCHAR
            );
            INSERT INTO canonical_data.stores VALUES
                ('store-1', 'market-1', 'USD', 'America/New_York');
            CREATE TABLE canonical_data.calendar (market_id VARCHAR, date DATE);
            INSERT INTO canonical_data.calendar VALUES
                ('market-1', DATE '2026-01-01');
            CREATE TABLE canonical_data.assortment_calendar (
                sku_id VARCHAR,
                store_id VARCHAR,
                channel_id VARCHAR,
                active_from DATE,
                active_to DATE,
                known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            );
            INSERT INTO canonical_data.assortment_calendar VALUES (
                'sku-1', 'store-1', 'channel-1',
                DATE '2026-01-01', NULL,
                TIMESTAMPTZ '2026-01-01T00:00:00-05:00',
                'native_observed'
            );
            CREATE TABLE canonical_data.sales (
                sku_id VARCHAR,
                store_id VARCHAR,
                channel_id VARCHAR,
                date DATE,
                sales_version INTEGER,
                units BIGINT,
                gross_sales_amount BIGINT,
                discount_amount BIGINT,
                net_sales_amount BIGINT,
                tax_amount BIGINT,
                currency_code VARCHAR,
                net_price BIGINT,
                promo_flag BOOLEAN,
                known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            );
            """
        )

        _densify_sales(connection)

        assert connection.execute(
            """
            SELECT
                units,
                cast(known_as_of AS VARCHAR),
                known_as_of_evidence_grade
            FROM canonical_data.sales
            """
        ).fetchone() == (0, "2026-01-02 05:00:00+00", "native_observed")
    finally:
        connection.close()
