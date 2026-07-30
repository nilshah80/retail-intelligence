"""Source-neutral transform invariants that do not need the full pinned run."""

from __future__ import annotations

from datetime import date

import duckdb

from retail_ingestion.transforms.core import _densify_sales


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
