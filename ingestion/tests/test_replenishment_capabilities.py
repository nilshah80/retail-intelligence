"""The inventory capabilities must be evaluated, not asserted.

`P4-2` task 16. Gate B hard-coded `replenishment.available = False` with reason
HISTORICAL_INBOUND_STATUS_NOT_VERSIONED. The verdict was right for the pin it was
written against, and that is precisely the problem: a publication carrying the
missing evidence would still have reported the capability unavailable, and one
that lost evidence it previously had would report the same thing. A constant
detects neither.

These tests build two canonical fixtures -- one current-only, one fully
replay-capable -- and require the two capabilities to disagree on the first and
agree on the second. A test that only ever exercises the failing branch cannot
tell an evaluation from a constant, which is why the passing branch is here.
"""

from __future__ import annotations

from typing import Any

import duckdb
import pytest

from retail_ingestion.quality.gate_b import _replenishment_capabilities

CUTOFF = "2026-07-28 23:00:00+00"
ORIGIN_SAFE = "native_extracted"


def _base(connection: duckdb.DuckDBPyConnection, *, store_stock: bool) -> None:
    """A DC-only current position, optionally with store-grain rows."""

    connection.execute("CREATE SCHEMA canonical_data")
    connection.execute(
        """
        CREATE TABLE canonical_data.locations (
            location_id VARCHAR, type VARCHAR, known_as_of TIMESTAMPTZ,
            known_as_of_evidence_grade VARCHAR
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.locations VALUES
            ('india-west:mumbai-dc', 'dc', '{CUTOFF}', '{ORIGIN_SAFE}'),
            ('india-west:mumbai-bandra', 'store', '{CUTOFF}', '{ORIGIN_SAFE}')
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.stock_snapshots (
            sku_id VARCHAR, location_id VARCHAR, snapshot_date DATE,
            on_hand_units BIGINT, known_as_of TIMESTAMPTZ,
            known_as_of_evidence_grade VARCHAR
        )
        """
    )
    rows = [f"('sku-1', 'india-west:mumbai-dc', '2026-07-23', 100, '{CUTOFF}', '{ORIGIN_SAFE}')"]
    if store_stock:
        rows.append(
            f"('sku-1', 'india-west:mumbai-bandra', '2026-07-23', 12, "
            f"'{CUTOFF}', '{ORIGIN_SAFE}')"
        )
    connection.execute(
        f"INSERT INTO canonical_data.stock_snapshots VALUES {', '.join(rows)}"
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.inbound_shipments (
            shipment_id VARCHAR, sku_id VARCHAR, to_location VARCHAR,
            qty BIGINT, status VARCHAR, known_as_of TIMESTAMPTZ,
            known_as_of_evidence_grade VARCHAR
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.inbound_shipments VALUES
            ('ship-1', 'sku-1', 'india-west:mumbai-dc', 50, 'in_transit',
             '{CUTOFF}', '{ORIGIN_SAFE}')
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.service_lanes (
            lane_id VARCHAR, market_id VARCHAR, lane_type VARCHAR,
            demand_location_id VARCHAR, channel_id VARCHAR,
            supply_location_id VARCHAR, priority_rank INTEGER,
            transit_days INTEGER, effective_from DATE,
            known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.service_lanes VALUES
            ('lane-1', 'india-west', 'replenishment',
             'india-west:mumbai-bandra', NULL, 'india-west:mumbai-dc', 1, 2,
             '2020-01-01', '{CUTOFF}', '{ORIGIN_SAFE}')
        """
    )


def _legacy_terms(connection: duckdb.DuckDBPyConnection) -> None:
    """v1 terms: adequate for a current claim, replay-ineligible by design."""

    connection.execute(
        """
        CREATE TABLE canonical_data.suppliers_leadtimes (
            supplier_id VARCHAR, destination_location_id VARCHAR,
            lead_time_days INTEGER, known_as_of TIMESTAMPTZ,
            known_as_of_evidence_grade VARCHAR
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.suppliers_leadtimes VALUES
            ('india-west:sup-1', 'india-west:mumbai-dc', 5, '{CUTOFF}',
             'landing_backfill')
        """
    )


def _origin_safe_terms(
    connection: duckdb.DuckDBPyConnection, *, grade: str = ORIGIN_SAFE
) -> None:
    connection.execute(
        """
        CREATE TABLE canonical_data.supply_terms (
            destination_location_id VARCHAR, origin_kind VARCHAR,
            origin_id VARCHAR, merch_scope_type VARCHAR, merch_scope_id VARCHAR,
            effective_from DATE, lead_time_days INTEGER,
            known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.supply_terms VALUES
            ('india-west:mumbai-dc', 'external_supplier', 'india-west:sup-1',
             'sku', 'sku-1', '2020-01-01', 5, '{CUTOFF}', '{grade}')
        """
    )


def _status_history(
    connection: duckdb.DuckDBPyConnection, *, premature: bool = False
) -> None:
    connection.execute(
        """
        CREATE TABLE canonical_data.inbound_shipment_status_events (
            shipment_id VARCHAR, sku_id VARCHAR, to_location VARCHAR,
            qty BIGINT, status VARCHAR, status_effective_at TIMESTAMPTZ,
            known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
        )
        """
    )
    # A premature row is knowable before it happened, which is the placement
    # defect that lets future state into replay.
    known_as_of = "2026-07-01 00:00:00+00" if premature else CUTOFF
    connection.execute(
        f"""
        INSERT INTO canonical_data.inbound_shipment_status_events VALUES
            ('ship-1', 'sku-1', 'india-west:mumbai-dc', 50, 'in_transit',
             '2026-07-20 08:00:00+00', '{known_as_of}', '{ORIGIN_SAFE}')
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.inventory_transfer_events (
            transfer_id VARCHAR, sku_id VARCHAR, from_location_id VARCHAR,
            to_location_id VARCHAR, qty BIGINT, status VARCHAR,
            status_effective_at TIMESTAMPTZ, unit_cost_minor BIGINT,
            currency_code VARCHAR, known_as_of TIMESTAMPTZ,
            known_as_of_evidence_grade VARCHAR
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.inventory_transfer_events VALUES
            ('tr-1', 'sku-1', 'india-west:mumbai-dc',
             'india-west:mumbai-bandra', 12, 'received',
             '2026-07-21 09:00:00+00', 4500, 'INR', '{CUTOFF}', '{ORIGIN_SAFE}')
        """
    )


def _fulfillments(
    connection: duckdb.DuckDBPyConnection, *, premature: bool
) -> None:
    connection.execute(
        """
        CREATE TABLE canonical_data.sales_fulfillments (
            fulfillment_line_id VARCHAR, sku_id VARCHAR,
            fulfilled_at TIMESTAMPTZ, known_as_of TIMESTAMPTZ,
            known_as_of_evidence_grade VARCHAR
        )
        """
    )
    # The current pin's defect: known_as_of inherited from the parent sale, so a
    # DELIVERED line is knowable a median 32 hours before it was fulfilled.
    known_as_of = (
        "2026-07-20 00:00:00+00" if premature else "2026-07-22 12:00:00+00"
    )
    connection.execute(
        f"""
        INSERT INTO canonical_data.sales_fulfillments VALUES
            ('ful-1', 'sku-1', '2026-07-21 10:00:00+00', '{known_as_of}',
             '{ORIGIN_SAFE}')
        """
    )


def _evaluate(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    present = {
        row[0]
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'canonical_data'"
        ).fetchall()
    }
    return _replenishment_capabilities(
        connection,
        present,
        pit_backfill={},
        incoming_split_mismatch=0,
    )


@pytest.fixture
def connection() -> duckdb.DuckDBPyConnection:
    handle = duckdb.connect(":memory:")
    try:
        yield handle
    finally:
        handle.close()


def test_the_current_pin_shape_is_current_ready_and_replay_unavailable(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """The exact split the capability exists to express.

    DC position, current inbound status, category-only landing-backfill terms, no
    store stock, no status history. Current analytics are serviceable; replay is
    not. One flag could only have said one of those.
    """

    _base(connection, store_stock=False)
    _legacy_terms(connection)
    _fulfillments(connection, premature=True)
    mask = _evaluate(connection)

    assert mask["inventory_replenishment_current_snapshot"]["available"] is True
    assert mask["inventory_replenishment_current_snapshot"]["scope"] == (
        "current_cutoff_only"
    )
    replay = mask["inventory_replenishment_replay"]
    assert replay["available"] is False
    assert "HISTORICAL_INBOUND_STATUS_NOT_VERSIONED" in replay["reasonCodes"]
    assert "STORE_GRAIN_INVENTORY_ABSENT" in replay["reasonCodes"]
    assert "ORIGIN_SAFE_SUPPLY_TERMS_ABSENT" in replay["reasonCodes"]
    assert "FULFILLMENT_AVAILABLE_BEFORE_EVENT" in replay["reasonCodes"]
    assert replay["storeGrainInventoryRows"] == 0
    assert replay["prematureFulfillmentRows"] == 1


def test_a_fully_evidenced_publication_reaches_replay_available(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """The branch a hard-coded False could never reach.

    Without this test the evaluation is indistinguishable from the constant it
    replaced.
    """

    _base(connection, store_stock=True)
    _origin_safe_terms(connection)
    _status_history(connection)
    _fulfillments(connection, premature=False)
    mask = _evaluate(connection)

    assert mask["inventory_replenishment_current_snapshot"]["available"] is True
    replay = mask["inventory_replenishment_replay"]
    assert replay["available"] is True, replay["reasonCodes"]
    assert replay["reasonCodes"] == []
    assert replay["storeGrainInventoryRows"] == 1
    assert replay["prematureFulfillmentRows"] == 0


def test_the_retired_key_tracks_replay_not_the_easier_capability(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """`replenishment` meant origin-safe replenishment; it must keep meaning that.

    A consumer reading the old key must not silently gain a weaker guarantee
    because a narrower capability was introduced beside it.
    """

    _base(connection, store_stock=False)
    _legacy_terms(connection)
    mask = _evaluate(connection)
    assert mask["inventory_replenishment_current_snapshot"]["available"] is True
    assert mask["replenishment"]["available"] is False
    assert mask["replenishment"]["available"] == (
        mask["inventory_replenishment_replay"]["available"]
    )
    assert mask["replenishment"]["supersededBy"] == [
        "inventory_replenishment_current_snapshot",
        "inventory_replenishment_replay",
    ]


def test_missing_lanes_block_both_capabilities(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """A route is required even for a current suggestion: without a declared lane
    there is no governed answer to "where would this be replenished from"."""

    _base(connection, store_stock=True)
    connection.execute("DROP TABLE canonical_data.service_lanes")
    _origin_safe_terms(connection)
    _status_history(connection)
    mask = _evaluate(connection)

    assert mask["inventory_replenishment_current_snapshot"]["available"] is False
    assert mask["inventory_replenishment_current_snapshot"]["reasonCode"] == (
        "SERVICE_LANES_NOT_DECLARED"
    )
    assert "SERVICE_LANES_NOT_DECLARED" in (
        mask["inventory_replenishment_replay"]["reasonCodes"]
    )


def test_weakly_graded_supply_terms_block_replay_only(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Present but landing-backfilled terms describe now, not a past origin."""

    _base(connection, store_stock=True)
    _origin_safe_terms(connection, grade="landing_backfill")
    _status_history(connection)
    _fulfillments(connection, premature=False)
    mask = _evaluate(connection)

    assert mask["inventory_replenishment_current_snapshot"]["available"] is True
    replay = mask["inventory_replenishment_replay"]
    assert replay["available"] is False
    assert "EVIDENCE_GRADE_TOO_WEAK" in replay["reasonCodes"]


def test_a_premature_status_row_blocks_replay(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """known_as_of before status_effective_at admits future state into replay."""

    _base(connection, store_stock=True)
    _origin_safe_terms(connection)
    _status_history(connection, premature=True)
    _fulfillments(connection, premature=False)
    mask = _evaluate(connection)

    replay = mask["inventory_replenishment_replay"]
    assert replay["available"] is False
    assert "STATUS_AVAILABLE_BEFORE_EVENT" in replay["reasonCodes"]
    assert replay["prematureStatusRows"] == 1


def test_every_failing_reason_is_reported_not_just_the_first(
    connection: duckdb.DuckDBPyConnection,
) -> None:
    """Fixing one blocker should not reveal the next one at a time."""

    _base(connection, store_stock=False)
    _legacy_terms(connection)
    _fulfillments(connection, premature=True)
    replay = _evaluate(connection)["inventory_replenishment_replay"]
    assert len(replay["reasonCodes"]) >= 4
    # The single-valued field stays for existing consumers and must agree.
    assert replay["reasonCode"] == replay["reasonCodes"][0]
