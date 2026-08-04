"""Open purchase orders: the two source relations sit at different grains.

`P4-12e`. The loader joined `inbound_shipment_status_events` to `inbound_shipments`
on `shipment_id` alone and then collapsed the result with `DISTINCT ON
(shipment_id)`. The lifecycle is per SHIPMENT and the quantity is per shipment
LINE, so that join pairs every transition with every line and the collapse keeps
one arbitrary line per shipment. On the real publication it counted 17,235 open
units where 39,526 are open, and dropped 201 of 387 cells.

Nothing caught it: the builder's fixture passes an EMPTY open-purchase-orders frame,
so the SQL had no test at all. These cases are written against the grains the
curated tables actually have -- one shipment, several SKU lines, three transitions.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from retail_ml.inventory_run.load import load_open_purchase_orders

AS_OF = date(2026, 7, 31)
SUPPLIER = "india-west:vendor-1"
WAREHOUSE = "india-west:mumbai-dc"


def _utc(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


@pytest.fixture()
def curated() -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA canonical_data")
    connection.execute("SET schema = 'canonical_data'")
    connection.execute(
        """
        CREATE TABLE locations (
            location_id VARCHAR, market_id VARCHAR, known_as_of TIMESTAMPTZ
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE inbound_shipments (
            shipment_id VARCHAR, sku_id VARCHAR, supplier_id VARCHAR,
            to_location VARCHAR, qty BIGINT, known_as_of TIMESTAMPTZ
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE inbound_shipment_status_events (
            shipment_id VARCHAR, status VARCHAR,
            status_effective_at TIMESTAMPTZ, known_as_of TIMESTAMPTZ
        )
        """
    )
    connection.execute(
        "INSERT INTO locations VALUES (?, 'india-west', ?)",
        [WAREHOUSE, _utc("2016-01-01")],
    )
    return connection


def _line(
    connection: duckdb.DuckDBPyConnection,
    shipment: str,
    sku: str,
    qty: int,
    *,
    known: str = "2026-07-01",
) -> None:
    connection.execute(
        "INSERT INTO inbound_shipments VALUES (?, ?, ?, ?, ?, ?)",
        [shipment, sku, SUPPLIER, WAREHOUSE, qty, _utc(known)],
    )


def _event(
    connection: duckdb.DuckDBPyConnection,
    shipment: str,
    status: str,
    effective: str,
    *,
    known: str | None = None,
) -> None:
    connection.execute(
        "INSERT INTO inbound_shipment_status_events VALUES (?, ?, ?, ?)",
        [shipment, status, _utc(effective), _utc(known or effective)],
    )


def test_every_line_of_a_multi_sku_shipment_is_counted(curated) -> None:
    """The defect. One shipment, three SKUs, one lifecycle."""

    _line(curated, "ship-1", "sku-a", 100)
    _line(curated, "ship-1", "sku-b", 40)
    _line(curated, "ship-1", "sku-c", 7)
    _event(curated, "ship-1", "on_order", "2026-07-10")
    _event(curated, "ship-1", "in_transit", "2026-07-20")

    frame = load_open_purchase_orders(curated, as_of=AS_OF)

    assert sorted(frame["sku_id"]) == ["sku-a", "sku-b", "sku-c"]
    assert int(frame["open_units"].sum()) == 147
    assert set(frame["supplier_id"]) == {SUPPLIER}
    assert set(frame["market_id"]) == {"india-west"}
    assert set(frame["location_id"]) == {WAREHOUSE}


def test_a_received_shipment_is_not_open(curated) -> None:
    _line(curated, "ship-1", "sku-a", 100)
    _line(curated, "ship-1", "sku-b", 40)
    _event(curated, "ship-1", "on_order", "2026-07-10")
    _event(curated, "ship-1", "in_transit", "2026-07-15")
    _event(curated, "ship-1", "received", "2026-07-20")

    assert load_open_purchase_orders(curated, as_of=AS_OF).empty


def test_the_latest_transition_wins_not_the_first(curated) -> None:
    """Two shipments whose histories differ only in where they stopped."""

    _line(curated, "open", "sku-a", 11)
    _event(curated, "open", "on_order", "2026-07-10")
    _event(curated, "open", "in_transit", "2026-07-20")
    _line(curated, "closed", "sku-a", 500)
    _event(curated, "closed", "on_order", "2026-07-10")
    _event(curated, "closed", "received", "2026-07-20")

    frame = load_open_purchase_orders(curated, as_of=AS_OF)

    assert int(frame["open_units"].sum()) == 11


def test_a_receipt_not_yet_known_leaves_the_order_open(curated) -> None:
    """Point-in-time. The receipt happened; nobody knew it yet at the origin."""

    _line(curated, "ship-1", "sku-a", 60)
    _event(curated, "ship-1", "in_transit", "2026-07-15")
    _event(curated, "ship-1", "received", "2026-07-20", known="2026-08-15")

    frame = load_open_purchase_orders(curated, as_of=AS_OF)

    assert int(frame["open_units"].sum()) == 60


def test_a_transition_effective_after_the_origin_is_not_applied(curated) -> None:
    """Known early, effective late: a future-dated receipt is still the future."""

    _line(curated, "ship-1", "sku-a", 60)
    _event(curated, "ship-1", "in_transit", "2026-07-15")
    _event(curated, "ship-1", "received", "2026-08-20", known="2026-07-20")

    assert int(
        load_open_purchase_orders(curated, as_of=AS_OF)["open_units"].sum()
    ) == 60


def test_a_line_not_yet_known_is_not_on_order(curated) -> None:
    """A line invisible at the origin is not on order at the origin."""

    _line(curated, "ship-1", "sku-a", 60)
    _line(curated, "ship-1", "sku-late", 999, known="2026-08-15")
    _event(curated, "ship-1", "in_transit", "2026-07-15")

    frame = load_open_purchase_orders(curated, as_of=AS_OF)

    assert sorted(frame["sku_id"]) == ["sku-a"]
    assert int(frame["open_units"].sum()) == 60


def test_a_line_with_no_vendor_is_excluded(curated) -> None:
    """An internal transfer is not a purchase order."""

    _line(curated, "ship-1", "sku-a", 60)
    curated.execute(
        "INSERT INTO inbound_shipments VALUES (?, ?, NULL, ?, ?, ?)",
        ["ship-1", "sku-internal", WAREHOUSE, 500, _utc("2026-07-01")],
    )
    _event(curated, "ship-1", "in_transit", "2026-07-15")

    frame = load_open_purchase_orders(curated, as_of=AS_OF)

    assert sorted(frame["sku_id"]) == ["sku-a"]
    assert int(frame["open_units"].sum()) == 60
