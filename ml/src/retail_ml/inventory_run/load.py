"""Load canonical inputs for one decision origin (P4-7/P4-8).

Every read is scoped and aggregated in SQL. The alternative -- pull the entity and
filter in pandas -- means materializing 2.5 million stock rows and 15.8 million
fulfillment rows to keep a few thousand, which is both slow and the thing the plan
forbids for the Go handlers for the same reason.

Origin safety is the other rule. Nothing here reads a row whose `known_as_of` is
later than the decision origin, because a replay that can see facts recorded after
its own origin is not a replay. `stock_snapshots` therefore takes the latest
snapshot at or before the origin, not the latest one that exists.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

import duckdb
import pandas as pd

from retail_ml.engines.analytics import store_wac_minor
from retail_ml.inventory_run.build import InventoryInputs

#: Trailing window for the demand rate every cover, ageing action and transfer
#: headroom is measured against. Thirteen weeks: long enough that one promotion
#: does not dominate, short enough to still be the current selling rate.
TRAILING_DAYS: Final[int] = 91


class InventoryLoadError(RuntimeError):
    """Canonical inputs cannot be loaded for this origin."""


def connect(curated_root: str | Path) -> duckdb.DuckDBPyConnection:
    """Open the curated database read-only, positioned on the canonical schema."""

    path = Path(curated_root) / "retail_v2.duckdb"
    if not path.is_file():
        raise InventoryLoadError(f"curated database is absent: {path}")
    connection = duckdb.connect(str(path), read_only=True)
    connection.execute("SET schema = 'canonical_data'")
    return connection


def _frame(
    connection: duckdb.DuckDBPyConnection, sql: str, parameters: list[Any]
) -> pd.DataFrame:
    return connection.execute(sql, parameters).fetch_df()


def _rows(
    connection: duckdb.DuckDBPyConnection, sql: str, parameters: list[Any]
) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, parameters)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


#: Why the evidence gate reads `known_as_of < as_of + INTERVAL 1 DAY` rather than
#: `<= as_of`.
#:
#: `as_of` is a DATE and `known_as_of` is a tz-aware instant, so `<=` coerces the
#: date to midnight and silently drops everything knowable during the as-of day
#: itself. The boundary stock snapshot is stamped 23:00 market-local, so the most
#: recent state evidence in the publication was invisible at its own date and only
#: appeared a day later -- which is why Inventory in Transit read zero while the
#: snapshot held 35,987 units.
#:
#: Moving the as-of forward instead was not an option: assortment_calendar records
#: end `active_to = 2026-07-28`, so an as-of past that leaves zero assorted cells
#: and classes every cell residual. The two requirements were one day apart and
#: mutually exclusive; treating the as-of as through-end-of-day satisfies both.
#:
#: This widens only what is READABLE at a given decision date. It does not touch
#: the stored instants, so Gate B B05's `known_as_of >= statusEffectiveAt` is
#: unaffected -- no row can be admitted before the event it describes.


def load_positions(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """The latest position per cell at or before the origin, plus assortment.

    `assortment_active` and the DISTINCT-ON pick are both done here so the builder
    never has to reason about which of several snapshot dates it is looking at.
    The canonical `atp_units` is loaded rather than recomputed, and checked below.
    """

    frame = _frame(
        connection,
        """
        WITH latest AS (
            SELECT DISTINCT ON (stock.sku_id, stock.location_id)
                stock.sku_id,
                stock.location_id,
                stock.snapshot_date,
                stock.on_hand_units,
                stock.committed_units,
                stock.reserved_units,
                stock.damaged_units,
                stock.on_order_units,
                stock.in_transit_units,
                stock.atp_units
            FROM stock_snapshots AS stock
            WHERE stock.snapshot_date <= ?
              AND stock.known_as_of < ? + INTERVAL 1 DAY
            ORDER BY stock.sku_id, stock.location_id, stock.snapshot_date DESC
        )
        SELECT
            locations.market_id,
            latest.location_id,
            locations.type AS location_kind,
            -- Display attributes. The screens name a node "Mumbai Distribution
            -- Centre", not "india-west:mumbai-dc", and a category "Apparel ·
            -- Footwear", not "apparel-footwear". Both exist in canonical and
            -- neither reached a projection, so every table showed an id.
            locations.name AS location_name,
            locations.city AS location_city,
            latest.sku_id,
            products.dept_id,
            products.category,
            products.product_name,
            latest.on_hand_units,
            latest.committed_units,
            latest.reserved_units,
            latest.damaged_units,
            latest.on_order_units,
            latest.in_transit_units,
            latest.atp_units AS canonical_atp_units,
            locations.currency_code,
            COALESCE(assortment.active, FALSE) AS assortment_active
        FROM latest
        JOIN locations ON locations.location_id = latest.location_id
        JOIN products ON products.sku_id = latest.sku_id
        LEFT JOIN (
            SELECT DISTINCT sku_id, store_id, TRUE AS active
            FROM assortment_calendar
            WHERE active_from <= ?
              AND (active_to IS NULL OR active_to >= ?)
              AND known_as_of < ? + INTERVAL 1 DAY
        ) AS assortment
          ON assortment.sku_id = latest.sku_id
         AND assortment.store_id = latest.location_id
        WHERE locations.active
        """,
        [as_of, as_of, as_of, as_of, as_of],
    )
    if frame.empty:
        raise InventoryLoadError(
            f"no canonical stock positions at or before {as_of}; an inventory "
            "bundle over zero positions would publish empty artifacts as facts"
        )
    # The canonical layer computes ATP with atp_method='derived_buckets', which is
    # the same subtraction Phase 4 needs. Assert it instead of choosing: if the two
    # definitions ever diverge, a silent pick would make every availability number
    # on every screen ambiguous.
    expected = (
        frame["on_hand_units"]
        - frame["committed_units"]
        - frame["reserved_units"]
        - frame["damaged_units"]
    ).clip(lower=0)
    mismatched = int((expected != frame["canonical_atp_units"]).sum())
    if mismatched:
        raise InventoryLoadError(
            f"{mismatched} rows where canonical atp_units disagrees with "
            "on_hand - committed - reserved - damaged. The two definitions have "
            "diverged and Phase 4 must not choose one silently."
        )
    return frame.drop(columns=["canonical_atp_units"])


def load_trailing_demand(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """Average daily units sold per cell over the trailing window.

    Divided by the window length rather than by the number of days that had a
    sale: a SKU selling on 3 of 91 days has a low rate, and dividing by 3 would
    report it as a fast mover and then buy safety stock for a rate it never has.
    """

    start = as_of - timedelta(days=TRAILING_DAYS - 1)
    # `sales` keys on store_id and dates its rows with `date`. Joining
    # locations.location_id to it is what makes a store's sales a node's demand;
    # a DC has no sales of its own and correctly gets no trailing rate.
    return _frame(
        connection,
        """
        SELECT
            locations.market_id,
            sales.store_id AS location_id,
            sales.sku_id,
            CAST(SUM(sales.units) AS DOUBLE) / ? AS trailing_avg_daily_units
        FROM sales
        JOIN locations ON locations.location_id = sales.store_id
        WHERE sales.date BETWEEN ? AND ?
          AND sales.known_as_of < ? + INTERVAL 1 DAY
        GROUP BY 1, 2, 3
        """,
        [float(TRAILING_DAYS), start, as_of, as_of],
    )


def load_batches(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    return _frame(
        connection,
        """
        SELECT
            locations.market_id,
            batches.location_id,
            batches.sku_id,
            batches.batch_id,
            batches.receipt_date AS received_on,
            batches.expiry_date AS expires_on,
            batches.batch_qty AS on_hand_units,
            batches.unit_cost AS unit_cost_minor
        FROM inventory_batches AS batches
        JOIN locations ON locations.location_id = batches.location_id
        WHERE batches.receipt_date <= ?
          AND batches.known_as_of < ? + INTERVAL 1 DAY
          AND batches.batch_qty > 0
        """,
        [as_of, as_of],
    )


def load_waste(connection: duckdb.DuckDBPyConnection, *, as_of: date) -> pd.DataFrame:
    """Waste and expiry in the trailing window, split by cause.

    `expired_units` is the subset whose reason code names expiry; the rest is
    damage, shrink and the other reasons. Reporting one number would make an
    expiry-management screen unable to say whether its own lever moved.
    """

    start = as_of - timedelta(days=TRAILING_DAYS - 1)
    return _frame(
        connection,
        """
        SELECT
            locations.market_id,
            waste.location_id,
            waste.sku_id,
            SUM(waste.units) AS waste_units,
            SUM(CASE WHEN lower(waste.reason_code) LIKE '%expir%'
                THEN waste.units ELSE 0 END) AS expired_units
        FROM waste_events AS waste
        JOIN locations ON locations.location_id = waste.location_id
        WHERE waste.event_date BETWEEN ? AND ?
          AND waste.known_as_of < ? + INTERVAL 1 DAY
        GROUP BY 1, 2, 3
        """,
        [start, as_of, as_of],
    )


def load_unit_costs(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """Accepted unit cost per cell as of the origin, per P4-D6's preference order.

    P4-D6 ranks the sources, and the first one is
    `receipt_or_transfer_line_accepted_unit_cost`. That matters here because
    `inventory_cost` in this publication holds DC rows only -- 2,736 cells, not one
    of them a store -- so reading it alone leaves every store cell uncosted, which
    means no cost-weighted ABC, no service level and no reorder point for the
    entire store echelon. The first version of this loader did exactly that and
    withheld all 4,741 rows.

    The store's own receipts are right there: `inventory_transfer_events` records
    320,717 received DC->store movements and every one carries
    `unit_cost_minor`. That is the store's OWN cost evidence, so
    `engines.analytics.store_wac_minor` computes a real store WAC from it -- no
    lane-imputed DC fallback, which P4-D6 makes a separately approved and visibly
    labelled thing this code must never do silently.

    SQL groups the events by DISTINCT unit cost per cell rather than returning
    them raw. The engine accumulates `total_units += qty` and
    `total_cost += qty * cost`, so pre-summing quantity within one cost is exactly
    distributive and the arithmetic is bit-identical -- while 320,717 rows become a
    few thousand.
    """

    dc_costs = _frame(
        connection,
        """
        SELECT DISTINCT ON (cost.sku_id, cost.location_id)
            locations.market_id,
            cost.location_id,
            cost.sku_id,
            cost.wac_cost AS unit_cost_minor,
            cost.method AS cost_method
        FROM inventory_cost AS cost
        JOIN locations ON locations.location_id = cost.location_id
        WHERE cost.as_of_date <= ?
          AND cost.known_as_of < ? + INTERVAL 1 DAY
        ORDER BY cost.sku_id, cost.location_id, cost.as_of_date DESC
        """,
        [as_of, as_of],
    )
    receipt_groups = _rows(
        connection,
        """
        SELECT
            locations.market_id,
            transfers.to_location_id AS location_id,
            transfers.sku_id,
            transfers.unit_cost_minor,
            transfers.currency_code,
            SUM(transfers.qty) AS qty
        FROM inventory_transfer_events AS transfers
        JOIN locations ON locations.location_id = transfers.to_location_id
        WHERE transfers.status = 'received'
          AND CAST(transfers.status_effective_at AS DATE) <= ?
          AND transfers.known_as_of < ? + INTERVAL 1 DAY
          AND transfers.unit_cost_minor IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5
        """,
        [as_of, as_of],
    )
    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in receipt_groups:
        key = (str(row["market_id"]), str(row["location_id"]), str(row["sku_id"]))
        by_cell[key].append(
            {
                "qty": int(row["qty"]),
                "unit_cost_minor": int(row["unit_cost_minor"]),
                "currency_code": str(row["currency_code"]),
            }
        )
    receipt_rows: list[dict[str, Any]] = []
    for (market, location, sku), receipts in sorted(by_cell.items()):
        verdict = store_wac_minor(receipts)
        if verdict["wac_minor"] is None:
            # The engine's own reason code, carried rather than replaced. A cell
            # with no cost-carrying receipt is simply absent from this frame and
            # the builder withholds it with ABC_UNIT_COST_UNAVAILABLE.
            continue
        receipt_rows.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "unit_cost_minor": int(verdict["wac_minor"]),
                "cost_method": str(verdict["method"]),
            }
        )
    receipts_frame = pd.DataFrame(
        receipt_rows,
        columns=["market_id", "location_id", "sku_id", "unit_cost_minor", "cost_method"],
    )
    # Receipt evidence wins where both exist: it is the store's own cost, and
    # P4-D6 ranks it above a canonical WAC computed from receipt-shaped facts.
    combined = pd.concat([receipts_frame, dc_costs], ignore_index=True)
    return combined.drop_duplicates(
        ["market_id", "location_id", "sku_id"], keep="first"
    ).reset_index(drop=True)


def load_wms_variance(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """Absolute ERP-versus-WMS discrepancy at the latest comparison per cell.

    Absolute, not signed: a location 50 units over on one SKU and 50 under on
    another has 100 units of discrepancy, and a signed sum would report zero and
    call a reconciliation problem clean.
    """

    return _frame(
        connection,
        """
        WITH latest AS (
            SELECT DISTINCT ON (sku_id, location_id)
                sku_id, location_id, difference_units
            FROM wms_inventory_comparisons
            WHERE snapshot_date <= ? AND known_as_of < ? + INTERVAL 1 DAY
            ORDER BY sku_id, location_id, snapshot_date DESC
        )
        SELECT
            locations.market_id,
            latest.location_id,
            latest.sku_id,
            abs(latest.difference_units) AS variance_units
        FROM latest
        JOIN locations ON locations.location_id = latest.location_id
        """,
        [as_of, as_of],
    )


def load_channel_demand(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """Per-channel requested units over the trailing window.

    Requested rather than fulfilled: allocation is about contention, and using
    what was actually shipped would hand the optimizer the answer it is meant to
    compute.
    """

    start = as_of - timedelta(days=TRAILING_DAYS - 1)
    return _frame(
        connection,
        """
        SELECT
            locations.market_id,
            sales.store_id AS location_id,
            sales.channel_id,
            sales.sku_id,
            SUM(sales.units) AS requested_units
        FROM sales
        JOIN locations ON locations.location_id = sales.store_id
        WHERE sales.date BETWEEN ? AND ?
          AND sales.known_as_of < ? + INTERVAL 1 DAY
        GROUP BY 1, 2, 3, 4
        HAVING SUM(sales.units) > 0
        """,
        [start, as_of, as_of],
    )


def load_lanes(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> list[dict[str, Any]]:
    return _rows(
        connection,
        """
        SELECT lane_id, market_id, lane_type, demand_location_id, channel_id,
               supply_location_id, priority_rank, transit_days,
               effective_from, effective_to
        FROM service_lanes
        WHERE known_as_of < ? + INTERVAL 1 DAY
        """,
        [as_of],
    )


def load_supply_terms(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> list[dict[str, Any]]:
    """Origin-safe terms only.

    `origin_id IS NOT NULL` is the filter that matters: the v1 `suppliers_leadtimes`
    generation carried a null origin, which the resolver treats as the wildcard it
    refuses. Loading those rows would make every term lookup ambiguous.
    """

    return _rows(
        connection,
        """
        SELECT destination_location_id, origin_kind, origin_id, merch_scope_type,
               merch_scope_id, effective_from, effective_to, lead_time_days,
               lead_time_std_days, moq, pack_qty
        FROM supply_terms
        WHERE known_as_of < ? + INTERVAL 1 DAY
          AND origin_id IS NOT NULL
          AND effective_from <= ?
        """,
        [as_of, as_of],
    )


def load_suppliers(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """On-time delivery, lead-time moments and confirmed capacity per supplier.

    Two source shapes have to be reconciled here.

    `supplier_performance.period` is a month string ('2026-07-01'), not a date
    column, so the latest period at or before the origin is picked by casting it
    -- ordering the text would happen to work for ISO dates and break silently
    the moment a period is written any other way.

    `otd_pct` and `capacity_confirmed_pct` are percentages on 0..100 in the
    source, while `engines.analytics.supplier_risk` compares against 0.90 and a
    policy floor expressed as "0.70". Dividing by 100 here rather than in the
    engine keeps the unit conversion at the IO boundary, which is the only place
    that knows what the source meant.
    """

    return _frame(
        connection,
        """
        WITH performance AS (
            SELECT DISTINCT ON (supplier_id)
                supplier_id,
                CAST(otd_pct AS DOUBLE) / 100.0 AS otd_rate,
                lead_time_mean_days,
                CAST(lead_time_std_days AS DOUBLE) AS lead_time_std_days,
                CAST(capacity_confirmed_pct AS DOUBLE) / 100.0
                    AS capacity_confirmed_pct
            FROM supplier_performance
            WHERE CAST(period AS DATE) <= ? AND known_as_of < ? + INTERVAL 1 DAY
            ORDER BY supplier_id, CAST(period AS DATE) DESC
        ),
        scoped AS (
            -- The merchandise scope a supplier serves, and how many it serves.
            -- Category terms rank first because that is the grain the screen's
            -- column is captioned at; a supplier with only dept or SKU terms
            -- falls back to those rather than showing nothing.
            SELECT DISTINCT ON (origin_id)
                origin_id,
                merch_scope_type,
                merch_scope_id,
                (SELECT COUNT(DISTINCT inner_terms.merch_scope_id)
                   FROM supply_terms AS inner_terms
                  WHERE inner_terms.origin_id = supply_terms.origin_id
                    AND inner_terms.known_as_of < ? + INTERVAL 1 DAY)
                    AS scope_count
            FROM supply_terms
            WHERE origin_id IS NOT NULL
              AND known_as_of < ? + INTERVAL 1 DAY
            GROUP BY origin_id, merch_scope_type, merch_scope_id
            ORDER BY origin_id,
                CASE merch_scope_type WHEN 'category' THEN 0
                     WHEN 'dept' THEN 1 ELSE 2 END,
                COUNT(*) DESC, merch_scope_id
        )
        SELECT DISTINCT ON (performance.supplier_id)
            locations.market_id,
            performance.supplier_id,
            performance.otd_rate,
            performance.lead_time_mean_days,
            performance.lead_time_std_days,
            performance.capacity_confirmed_pct,
            scoped.merch_scope_id AS category,
            scoped.scope_count
        FROM performance
        JOIN suppliers_leadtimes AS terms
          ON terms.supplier_id = performance.supplier_id
        JOIN locations
          ON locations.location_id = terms.destination_location_id
        LEFT JOIN scoped ON scoped.origin_id = performance.supplier_id
        ORDER BY performance.supplier_id, locations.market_id
        """,
        [as_of, as_of, as_of, as_of],
    )


def load_inbound_summary(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """Inbound reliability per node: what is open, and what arrived late.

    The position projection carries an on-order and an in-transit bucket and no
    DATES, so nothing downstream could tell a late receipt from a merely open one
    -- and policy v2 declares those buckets disjoint, which makes "on order with
    nothing in transit" true of every unshipped order. The dates are in the
    source: `inbound_shipment_status_events` carries an expected_receipt_date and
    the full on_order -> in_transit -> received lifecycle per shipment.

    Lateness is measured on ARRIVALS over the trailing window, not on the open
    book. Nothing is currently past due at this origin -- every open shipment is
    expected on or after it -- so an open-book measure reads zero at every node
    and says nothing about reliability. What did arrive, arrived late three times
    in four.

    The latest status per shipment wins: a shipment appears once per lifecycle
    transition, and counting the rows would count one delivery three times.
    """

    start = as_of - timedelta(days=TRAILING_DAYS - 1)
    return _frame(
        connection,
        """
        WITH visible AS (
            SELECT shipment_id, to_location, qty, status, status_effective_at,
                   expected_receipt_date
            FROM inbound_shipment_status_events
            WHERE known_as_of < ? + INTERVAL 1 DAY
              AND CAST(status_effective_at AS DATE) <= ?
        ),
        latest AS (
            SELECT DISTINCT ON (shipment_id)
                shipment_id, to_location, qty, status, expected_receipt_date
            FROM visible
            ORDER BY shipment_id, status_effective_at DESC
        ),
        arrived AS (
            SELECT shipment_id, to_location, expected_receipt_date,
                   MIN(CAST(status_effective_at AS DATE)) AS received_on
            FROM visible
            WHERE status = 'received'
              AND CAST(status_effective_at AS DATE) BETWEEN ? AND ?
            GROUP BY 1, 2, 3
        )
        SELECT
            locations.market_id,
            latest.to_location AS location_id,
            COUNT(*) FILTER (WHERE latest.status <> 'received')
                AS open_shipments,
            COALESCE(SUM(latest.qty)
                FILTER (WHERE latest.status <> 'received'), 0) AS open_units,
            (SELECT COUNT(*) FROM arrived
              WHERE arrived.to_location = latest.to_location) AS received_shipments,
            (SELECT COUNT(*) FROM arrived
              WHERE arrived.to_location = latest.to_location
                AND arrived.received_on > arrived.expected_receipt_date)
                AS late_shipments
        FROM latest
        JOIN locations ON locations.location_id = latest.to_location
        GROUP BY 1, 2
        """,
        [as_of, as_of, start, as_of],
    )


def load_warehouse_capacity(
    connection: duckdb.DuckDBPyConnection, *, as_of: date
) -> pd.DataFrame:
    """The storage ceiling per warehouse, at the latest snapshot the origin admits.

    The source writes one snapshot per warehouse per week over a decade, so
    "capacity now" is the most recent row at or before the origin. Loading the
    whole history would make the grain per-week and any sum over it meaningless.

    `used_units` is not loaded. The source's used figure is the same on-hand the
    position artifact already publishes -- identical to the unit at both India
    DCs -- so utilisation divides the holding this screen already values by the
    ceiling here, and the numerator cannot disagree with the column beside it.
    """

    return _frame(
        connection,
        """
        SELECT DISTINCT ON (capacity.location_id)
            locations.market_id,
            capacity.location_id,
            capacity.capacity_units,
            capacity.snapshot_date
        FROM warehouse_capacity_snapshots AS capacity
        JOIN locations ON locations.location_id = capacity.location_id
        WHERE capacity.snapshot_date <= ?
          AND capacity.known_as_of < ? + INTERVAL 1 DAY
        ORDER BY capacity.location_id, capacity.snapshot_date DESC
        """,
        [as_of, as_of],
    )


def load_forecast(
    forecast_series: pd.DataFrame,
    *,
    positions: pd.DataFrame,
    lanes: Sequence[Mapping[str, Any]],
    as_of: date,
) -> pd.DataFrame:
    """Reshape the served forecast onto the location grain the builder needs.

    The forecast is store-grain and inventory is location-grain, so a DC has no
    series of its own. Leaving DCs unforecast entirely -- which the first version
    did -- means every DC recommendation withholds for want of any demand estimate,
    and the warehouse screen has nothing to show at all.

    Policy v2 says how to fix that: `channelPolicy.nodeDemandAggregation:
    additive_central_p50_scenario_only`. A DC's demand is the additive P50 of the
    stores it supplies over declared lanes. Note what that permits and what it
    does not:

    * P50 sums. It is a central scenario, and the policy labels it as exactly that
      rather than as a statistical median of the aggregate.
    * P90 does NOT. `sumOfChannelP90: forbidden`, because the sum of upper
      quantiles is not the upper quantile of the sum -- it assumes every store
      peaks in the same week. So an aggregated DC row carries a P50 and no
      interval, and the builder withholds its safety stock with a governed reason.
      `nodeSafetyStockBasis: accepted_aggregate_residual_variability` is the real
      basis and the forecast artifact does not carry it.

    Only rank-1 lanes contribute. A store's demand belongs to its primary supply
    node; adding it to every alternate DC as well would double-count the same
    units across the network.
    """

    required = {
        "market_id",
        "store_id",
        "sku_id",
        "horizon_week",
        "yhat_p50",
        "yhat_p90",
    }
    missing = sorted(required - set(forecast_series.columns))
    if missing:
        raise InventoryLoadError(f"forecast series lacks columns {missing}")
    frame = forecast_series.rename(columns={"store_id": "location_id"}).copy()
    frame["interval_available"] = frame["yhat_p90"].notna()
    frame["demand_basis"] = "store_series"

    known = set(
        zip(
            positions["market_id"].astype(str),
            positions["location_id"].astype(str),
            positions["sku_id"].astype(str),
        )
    )
    columns = [
        "market_id",
        "location_id",
        "sku_id",
        "horizon_week",
        "yhat_p50",
        "yhat_p90",
        "interval_available",
        "demand_basis",
    ]
    store_rows = frame.loc[
        [
            key in known
            for key in zip(
                frame["market_id"].astype(str),
                frame["location_id"].astype(str),
                frame["sku_id"].astype(str),
            )
        ]
    ][columns]

    # market -> primary DC per store, from the rank-1 active lane only.
    primary_dc: dict[tuple[str, str], str] = {}
    for lane in lanes:
        if str(lane["lane_type"]) != "replenishment":
            continue
        if int(lane["priority_rank"]) != 1:
            continue
        effective_to = lane.get("effective_to")
        if as_of < lane["effective_from"]:
            continue
        if effective_to is not None and as_of > effective_to:
            continue
        primary_dc[(str(lane["market_id"]), str(lane["demand_location_id"]))] = str(
            lane["supply_location_id"]
        )
    if not primary_dc:
        return store_rows.reset_index(drop=True)

    supplied = frame.assign(
        dc_location_id=[
            primary_dc.get((str(market), str(location)))
            for market, location in zip(frame["market_id"], frame["location_id"])
        ]
    ).dropna(subset=["dc_location_id"])
    if supplied.empty:
        return store_rows.reset_index(drop=True)

    aggregated = (
        supplied.groupby(
            ["market_id", "dc_location_id", "sku_id", "horizon_week"], as_index=False
        )["yhat_p50"]
        .sum()
        .rename(columns={"dc_location_id": "location_id"})
    )
    aggregated["yhat_p90"] = pd.NA
    aggregated["interval_available"] = False
    aggregated["demand_basis"] = "aggregated_supplied_stores_p50"
    aggregated = aggregated.loc[
        [
            key in known
            for key in zip(
                aggregated["market_id"].astype(str),
                aggregated["location_id"].astype(str),
                aggregated["sku_id"].astype(str),
            )
        ]
    ][columns]

    return pd.concat([store_rows, aggregated], ignore_index=True).reset_index(
        drop=True
    )


def load_inventory_inputs(
    curated_root: str | Path,
    *,
    as_of: date,
    forecast_series: pd.DataFrame,
    policy: Mapping[str, Mapping[str, Any]],
) -> InventoryInputs:
    """Assemble every input for one origin from the curated publication."""

    connection = connect(curated_root)
    try:
        positions = load_positions(connection, as_of=as_of)
        currency_by_market = {
            str(market): str(code)
            for market, code in positions.groupby("market_id")["currency_code"]
            .agg(lambda values: sorted(set(values))[0])
            .items()
        }
        conflicting = {
            str(market): sorted(set(group))
            for market, group in positions.groupby("market_id")["currency_code"]
            if len(set(group)) > 1
        }
        if conflicting:
            raise InventoryLoadError(
                f"markets report more than one currency {conflicting}; a money "
                "column would then mean different things in the same column"
            )
        markets = sorted(currency_by_market)
        unresolved = [market for market in markets if market not in policy]
        if unresolved:
            raise InventoryLoadError(
                f"no resolved policy for markets {unresolved}"
            )
        lanes = load_lanes(connection, as_of=as_of)
        return InventoryInputs(
            as_of=as_of,
            positions=positions.drop(columns=["currency_code"]),
            trailing_demand=load_trailing_demand(connection, as_of=as_of),
            forecast=load_forecast(
                forecast_series, positions=positions, lanes=lanes, as_of=as_of
            ),
            batches=load_batches(connection, as_of=as_of),
            waste=load_waste(connection, as_of=as_of),
            unit_costs=load_unit_costs(connection, as_of=as_of),
            wms_variance=load_wms_variance(connection, as_of=as_of),
            lanes=lanes,
            supply_terms=load_supply_terms(connection, as_of=as_of),
            suppliers=load_suppliers(connection, as_of=as_of),
            warehouse_capacity=load_warehouse_capacity(connection, as_of=as_of),
            inbound_summary=load_inbound_summary(connection, as_of=as_of),
            channel_demand=load_channel_demand(connection, as_of=as_of),
            policy={market: policy[market] for market in markets},
            currency_by_market=currency_by_market,
        )
    finally:
        connection.close()


def lane_coverage_pct(
    curated_root: str | Path, *, as_of: date
) -> tuple[Decimal, int, int]:
    """Share of trailing fulfillments whose route resolves to a declared lane.

    The publisher refuses below 100%: a fulfillment the declared network cannot
    explain is a route that exists in reality and not in the contract, and a
    replay over it would be reconstructing a network nobody declared.
    """

    connection = connect(curated_root)
    try:
        start = as_of - timedelta(days=TRAILING_DAYS - 1)
        row = connection.execute(
            """
            WITH shipped AS (
                SELECT transfers.from_location_id, transfers.to_location_id
                FROM inventory_transfer_events AS transfers
                WHERE CAST(transfers.status_effective_at AS DATE) BETWEEN ? AND ?
                  AND transfers.known_as_of < ? + INTERVAL 1 DAY
            )
            SELECT
                count(*) AS total,
                count(*) FILTER (WHERE lanes.lane_id IS NOT NULL) AS covered
            FROM shipped
            LEFT JOIN service_lanes AS lanes
              ON lanes.demand_location_id = shipped.to_location_id
             AND lanes.supply_location_id = shipped.from_location_id
             AND lanes.effective_from <= ?
             AND (lanes.effective_to IS NULL OR lanes.effective_to >= ?)
            """,
            [start, as_of, as_of, as_of, as_of],
        ).fetchone()
    finally:
        connection.close()
    if row is None or int(row[0]) == 0:
        # No movement in the window is not full coverage. Returning 100% here
        # would let a window with no evidence satisfy a gate about evidence.
        return Decimal(0), 0, 0
    total, covered = int(row[0]), int(row[1])
    return (
        (Decimal(covered) * 100 / Decimal(total)).quantize(Decimal("0.0001")),
        covered,
        total,
    )


__all__ = [
    "TRAILING_DAYS",
    "InventoryLoadError",
    "connect",
    "lane_coverage_pct",
    "load_batches",
    "load_channel_demand",
    "load_forecast",
    "load_inventory_inputs",
    "load_lanes",
    "load_positions",
    "load_suppliers",
    "load_supply_terms",
    "load_trailing_demand",
    "load_unit_costs",
    "load_waste",
    "load_wms_variance",
]
