from datetime import datetime, timedelta, timezone

import duckdb

from retail_ml.inventory_run.load import load_unit_price_history, load_unit_prices


def _connection() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE locations(location_id VARCHAR, market_id VARCHAR)"
    )
    connection.execute(
        """
        CREATE TABLE sales(
            store_id VARCHAR,
            channel_id VARCHAR,
            sku_id VARCHAR,
            currency_code VARCHAR,
            date DATE,
            known_as_of TIMESTAMPTZ,
            sales_version BIGINT,
            net_price BIGINT,
            units BIGINT
        )
        """
    )
    connection.execute("INSERT INTO locations VALUES ('store-1', 'market-1')")
    connection.execute(
        """
        INSERT INTO sales VALUES
          ('store-1', 'store', 'sku-1', 'USD', DATE '2026-08-10',
           TIMESTAMPTZ '2026-08-10 11:00:00+00', 1, 100, 1),
          ('store-1', 'store', 'sku-1', 'USD', DATE '2026-08-10',
           TIMESTAMPTZ '2026-08-10 13:00:00+00', 2, 200, 1)
        """
    )
    return connection


def test_scenario_price_load_uses_the_exact_decision_instant() -> None:
    connection = _connection()
    try:
        cutoff = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
        latest = load_unit_prices(connection, as_of=cutoff)
        history = load_unit_price_history(
            connection, as_of=cutoff, window_days=30
        )
    finally:
        connection.close()
    assert latest["unit_price_minor"].tolist() == [100]
    assert history["unit_price_minor"].tolist() == [100]


def test_scenario_price_observation_date_uses_the_utc_decision_date() -> None:
    connection = _connection()
    try:
        # Local 10 August is still 9 August in UTC. An observation dated
        # 10 August must therefore remain invisible at this instant.
        cutoff = datetime(
            2026, 8, 10, 0, 30,
            tzinfo=timezone(timedelta(hours=5, minutes=30)),
        )
        latest = load_unit_prices(connection, as_of=cutoff)
        history = load_unit_price_history(connection, as_of=cutoff, window_days=30)
    finally:
        connection.close()
    assert latest.empty
    assert history.empty
