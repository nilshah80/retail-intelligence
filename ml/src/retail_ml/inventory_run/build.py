"""Assemble the thirteen published artifacts from canonical inputs (P4-7/P4-8).

This is the only place engine outputs become served rows. It is deliberately free
of IO: `InventoryInputs` is handed in already loaded, so every artifact can be
built and asserted on a handful of rows rather than on a ten-year snapshot.

Three rules run through all of it.

**The interval gate is asked before a number is computed, never after.** Decision
#92 withholds the cold-start interval past horizon 4. A consumer whose protection
period reaches further has no interval to work from, so the row is emitted with
`interval_available = False`, a governed reason, and NULL where the number would
have been. Not zero: a zero safety stock and an unassessed safety stock look
identical on a screen and mean opposite things.

**Grain is active-or-residual, never Cartesian.** A cell appears only if the SKU
is in that node's assortment or the node is still holding stock of it. Emitting
the cross product would make every coverage and stockout percentage a function of
catalogue size.

**The network is the one that was declared.** This dataset has two echelons with
two different contracts -- `supply_terms` govern external_supplier -> DC and every
row is DC-destined, while `service_lanes` govern DC -> store and every row is
store-destined. Replenishment therefore branches on node kind rather than asking
one resolver to answer for both, and transfers use the declared rank-2 alternate
lane because no store-to-store lane and no `transfer` lane type exist at all.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final, Mapping

import pandas as pd

from retail_ml.engines.abc import classify_abc
from retail_ml.engines.analytics import (
    age_bucket,
    ageing_action,
    classify_health,
    expiry_exposure,
    supplier_risk,
)
from retail_ml.engines.demand_risk import demand_at_risk
from retail_ml.engines.interval_guard import (
    IntervalUnavailable,
    PartialConsumerLedger,
    require_interval_horizon,
)
from retail_ml.engines.optimizers import (
    TransferCandidate,
    allocate_channels,
    recommend_transfers,
)
from retail_ml.engines.primitives import (
    InventoryPosition,
    OrderConstraintError,
    apply_order_constraints,
    fractional_horizon_sum,
    inventory_position,
    order_up_to_level,
    protection_period_days,
    reorder_point,
    required_horizon_weeks,
    safety_stock_units,
)
from retail_ml.engines.resolution import (
    ResolutionError,
    active_lanes,
    resolve_supply_term,
)
from retail_ml.inventory_publish.run_artifacts import (
    ARTIFACT_COLUMNS,
    ERP_STATUS,
    GOVERNED_REASONS,
)
from retail_ml.inventory_run.price_resolution import (
    PriceResolutionError,
    build_price_index,
)

#: The two governed reasons Phase 4 may cite for an absent interval-derived
#: value. They are different findings: one says "wait for calibration", the other
#: says "declare a route", and an operator shown the wrong one waits forever.
COLD_START_REASON: Final[str] = "COLD_START_INTERVAL_UNCALIBRATED"
UNRESOLVED_ROUTE_REASON: Final[str] = "SUPPLY_ROUTE_UNRESOLVED"
NO_NODE_FORECAST_REASON: Final[str] = "FORECAST_ABSENT_FOR_NODE"
NO_ABC_COST_REASON: Final[str] = "ABC_UNIT_COST_UNAVAILABLE"
NO_NODE_INTERVAL_REASON: Final[str] = "NODE_INTERVAL_BASIS_UNAVAILABLE"
#: Policy v2 `leadTime.zeroVarianceReasonCode`. Until `P4-12g` nothing could emit
#: it, because the engine had no lead-time term to be missing.
NO_LEAD_TIME_VARIANCE_REASON: Final[str] = "LEAD_TIME_VARIABILITY_UNAVAILABLE"


def _lead_time_variance_weeks(
    inputs: InventoryInputs,
) -> dict[tuple[str, str], tuple[float | None, str | None]]:
    """Lead-time variance in WEEKS squared per supplier, or why there is none.

    Policy v2 declares `leadTime.variabilityMethod:
    supplier_performance_mean_and_std` and `minimumObservations: 8`, and both had
    no consumer. A standard deviation over fewer than eight periods is not an
    admissible estimate, and `zeroVarianceBehavior: reason_code_not_zero_buffer`
    says a zero-variance buffer is a misleading number rather than a missing one --
    so both cases return a reason instead of a zero.

    Squared because the formula's second addend takes a VARIANCE, and the source
    publishes a standard deviation in DAYS: (std_days / 7) ** 2.
    """

    minimum = 8
    index: dict[tuple[str, str], tuple[float | None, str | None]] = {}
    for record in inputs.suppliers.itertuples(index=False):
        row = record._asdict()
        key = (str(row["market_id"]), str(row["supplier_id"]))
        periods = row.get("observation_periods")
        std_days = row.get("lead_time_std_days")
        if periods is None or pd.isna(periods) or int(periods) < minimum:
            index[key] = (None, NO_LEAD_TIME_VARIANCE_REASON)
            continue
        if std_days is None or pd.isna(std_days) or float(std_days) <= 0:
            index[key] = (None, NO_LEAD_TIME_VARIANCE_REASON)
            continue
        index[key] = ((float(std_days) / 7.0) ** 2, None)
    return index
assert {
    COLD_START_REASON,
    UNRESOLVED_ROUTE_REASON,
    NO_NODE_FORECAST_REASON,
    NO_ABC_COST_REASON,
    NO_NODE_INTERVAL_REASON,
} <= GOVERNED_REASONS

#: Set by the loader when a node's demand is the additive expectation of the
#: stores it supplies. Such a node has expected volume and, by policy, no interval.
AGGREGATED_BASIS: Final[str] = "aggregated_supplied_stores_expected_units"

#: Reasons a non-interval value can be absent. Each names a real gap so a screen
#: can say which one instead of showing a plausible zero.
COST_UNAVAILABLE: Final[str] = "UNIT_COST_UNAVAILABLE"

#: Channel used for node-level rows in artifacts that carry a channel column but
#: describe a position rather than a channel's demand.
NODE_CHANNEL: Final[str] = "store"

#: Weeks per year used to annualize the trailing rate for ABC. The engine
#: multiplies weekly units by 52 itself, so this converts daily to weekly only.
DAYS_PER_WEEK: Final[Decimal] = Decimal(7)


class InventoryBuildError(RuntimeError):
    """Canonical inputs cannot support the artifact contract."""


@dataclass(frozen=True)
class InventoryInputs:
    """Everything the builder reads, already scoped to one decision origin.

    Frames rather than a connection: the builder must be runnable on a fixture,
    and a builder that can open storage is a builder whose determinism can only
    be checked by running the whole pipeline.
    """

    as_of: date
    #: market_id, location_id, location_kind, sku_id, oldest_receipt_date,
    #: dept_id, category,
    #: on_hand_units, committed_units, reserved_units, damaged_units,
    #: on_order_units, in_transit_units, assortment_active
    positions: pd.DataFrame
    #: market_id, location_id, sku_id, trailing_avg_daily_units
    trailing_demand: pd.DataFrame
    #: market_id, location_id, sku_id, horizon_week, expected_units, yhat_p50,
    #: yhat_p90, interval_available
    forecast: pd.DataFrame
    #: market_id, location_id, sku_id, batch_id, received_on, expires_on,
    #: on_hand_units, unit_cost_minor
    batches: pd.DataFrame
    #: market_id, location_id, sku_id, waste_units, expired_units
    waste: pd.DataFrame
    #: market_id, location_id, sku_id, prior_waste_units -- the 91-day window
    #: immediately preceding `waste`'s, for the Waste Reduction comparison
    prior_waste: pd.DataFrame
    #: market_id, location_id, sku_id, unit_cost_minor, cost_method
    unit_costs: pd.DataFrame
    #: market_id, location_id, sku_id, variance_units
    wms_variance: pd.DataFrame
    #: rows accepted by engines.resolution.active_lanes
    lanes: list[dict[str, Any]]
    #: rows accepted by engines.resolution.resolve_supply_term
    supply_terms: list[dict[str, Any]]
    #: market_id, supplier_id, otd_rate, lead_time_mean_days,
    #: lead_time_std_days, capacity_confirmed_pct -- all on a 0..1 scale
    suppliers: pd.DataFrame
    #: market_id, location_id, capacity_units, snapshot_date -- one row per
    #: warehouse, at the latest snapshot the origin admits
    warehouse_capacity: pd.DataFrame
    #: market_id, location_id, open_shipments, open_units, received_shipments,
    #: late_shipments -- inbound reliability per receiving node
    inbound_summary: pd.DataFrame
    #: market_id, supplier_id, location_id, sku_id, open_units -- inbound still on
    #: order, at the cell grain the accepted cost is keyed by
    open_purchase_orders: pd.DataFrame
    #: market_id, location_id, channel_id, sku_id, requested_units
    channel_demand: pd.DataFrame
    #: Raw served SeriesKey forecasts: market_id, store_id, channel_id, sku_id,
    #: horizon_week, expected_units, yhat_p50, yhat_p90, interval_available.
    #: Kept separately from ``forecast`` because inventory positions are node
    #: grain while demand-at-risk must preserve the channel allocation.
    channel_forecast: pd.DataFrame
    #: Latest origin-visible selling price per market/location/channel/SKU.
    #: Demand-at-risk is potential unserved SALES value, not inventory cost.
    unit_prices: pd.DataFrame
    #: per-market resolved policy, keyed by market_id
    policy: Mapping[str, Mapping[str, Any]]
    #: market_id -> ISO 4217 code used for every money column in that market
    currency_by_market: Mapping[str, str]
    ledgers: dict[str, PartialConsumerLedger] = field(default_factory=dict)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryBuildError(message)


def _decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value is pd.NA:
        return Decimal(default)
    if isinstance(value, float) and pd.isna(value):
        return Decimal(default)
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return Decimal(str(value))


def _optional_int(value: Any) -> int | None:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return int(value)


def _position(row: Mapping[str, Any]) -> InventoryPosition:
    return InventoryPosition(
        on_hand_units=int(row["on_hand_units"]),
        committed_units=int(row["committed_units"]),
        reserved_units=int(row["reserved_units"]),
        damaged_units=int(row["damaged_units"]),
        on_order_units=int(row["on_order_units"]),
        in_transit_units=int(row["in_transit_units"]),
    )


def _atp(row: Mapping[str, Any]) -> int:
    """Available to promise: on hand less every claim already made against it.

    On-order and in-transit are excluded on purpose -- they are inventory
    position, not availability. A screen that promises stock still on a truck is
    the reason this is a named function rather than an inline subtraction.
    """

    return max(
        0,
        int(row["on_hand_units"])
        - int(row["committed_units"])
        - int(row["reserved_units"])
        - int(row["damaged_units"]),
    )


def _as_date(value: Any) -> date | None:
    """Coerce a Parquet date-ish value to a plain `date`, or None.

    The datetime check comes BEFORE the date check, and that order is the whole
    point: `pd.Timestamp` subclasses `datetime`, which subclasses `date`, so an
    `isinstance(value, date)` test first returns the Timestamp unconverted.
    Subtracting one from a `date` then raises TypeError -- which is exactly how
    the ageing builder failed on real Parquet rows after passing every fixture
    test, because the fixtures used `datetime.date` literals.
    """

    # One null test, first, over every null pandas has: None, NaN, NaT and pd.NA.
    # Type-specific null checks miss NaT, which is itself a `datetime` instance --
    # so it passed the isinstance dispatch below, `.date()` returned NaT again, and
    # the comparison downstream raised "Cannot compare NaT with datetime.date".
    if value is None or pd.isna(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    timestamp = pd.Timestamp(value)
    return None if pd.isna(timestamp) else timestamp.date()


# -- indexing ------------------------------------------------------------------

def _index_trailing(inputs: InventoryInputs) -> dict[tuple[str, str, str], Decimal]:
    return {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): _decimal(
            row.trailing_avg_daily_units
        )
        for row in inputs.trailing_demand.itertuples(index=False)
    }


def _index_unit_costs(
    inputs: InventoryInputs,
) -> dict[tuple[str, str, str], tuple[int | None, str | None]]:
    return {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): (
            _optional_int(row.unit_cost_minor),
            None if pd.isna(row.cost_method) else str(row.cost_method),
        )
        for row in inputs.unit_costs.itertuples(index=False)
    }


def _index_forecast(
    inputs: InventoryInputs,
) -> dict[tuple[str, str, str], dict[int, dict[str, Any]]]:
    nested: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = defaultdict(dict)
    for row in inputs.forecast.itertuples(index=False):
        key = (str(row.market_id), str(row.location_id), str(row.sku_id))
        nested[key][int(row.horizon_week)] = {
            "expected_units": float(row.expected_units),
            "yhat_p50": float(row.yhat_p50),
            "yhat_p90": None if pd.isna(row.yhat_p90) else float(row.yhat_p90),
            "interval_available": bool(row.interval_available),
            # Absent on a store series; the loader stamps it on an aggregated
            # node so the builder can name the right reason for a missing
            # interval instead of reporting every one as cold-start.
            "demand_basis": getattr(row, "demand_basis", "store_expected_volume"),
        }
    return dict(nested)


def _index_channel_forecast(
    inputs: InventoryInputs,
) -> dict[tuple[str, str, str, str], dict[int, dict[str, Any]]]:
    """Served forecast at its native SeriesKey grain.

    The node-level ``forecast`` index deliberately has no channel key because it
    feeds replenishment. Demand-at-risk is different: ATP is a shared node pool,
    and silently overwriting three channel rows with the last one both discards
    demand and makes the result depend on PostgreSQL row order.
    """

    nested: dict[
        tuple[str, str, str, str], dict[int, dict[str, Any]]
    ] = defaultdict(dict)
    for row in inputs.channel_forecast.itertuples(index=False):
        key = (
            str(row.market_id),
            str(row.store_id),
            str(row.sku_id),
            str(row.channel_id),
        )
        horizon = int(row.horizon_week)
        _require(
            horizon not in nested[key],
            f"duplicate served forecast row for {key} at h{horizon}",
        )
        nested[key][horizon] = {
            "expected_units": float(row.expected_units),
            "yhat_p50": float(row.yhat_p50),
            "yhat_p90": None if pd.isna(row.yhat_p90) else float(row.yhat_p90),
            "interval_available": bool(row.interval_available),
        }
    return dict(nested)


def _index_unit_prices(
    inputs: InventoryInputs,
) -> tuple[
    dict[tuple[str, str, str, str], int],
    dict[tuple[str, str], int],
]:
    """Exact SeriesKey prices and a deterministic market/SKU fallback.

    A location/channel with no realised sale yet may still have an active
    forecast. The fallback is the median latest realised selling price for the
    SAME market and SKU. It never crosses markets and never substitutes unit
    cost, which would turn a lost-sales label into an inventory-value measure.
    """

    # Inventory consumes only the historical integer maps. Provenance columns are
    # deliberately excluded here: Scenario Planning validates currency-coherent
    # provenance, while inventory's pre-scenario behavior took the same-market/SKU
    # median numerically even when dirty source currencies disagreed. Letting the
    # presence of new columns switch algorithms made an unrelated inventory run
    # start failing during scenario implementation.
    numeric_columns = [
        "market_id",
        "location_id",
        "channel_id",
        "sku_id",
        "unit_price_minor",
    ]
    try:
        return build_price_index(
            inputs.unit_prices.loc[:, numeric_columns]
        ).numeric_views()
    except PriceResolutionError as exc:
        raise InventoryBuildError(str(exc)) from exc


def _is_aggregated(horizons: Mapping[int, Mapping[str, Any]]) -> bool:
    """True when every horizon came from the additive-supplied-stores basis."""

    return bool(horizons) and all(
        cell.get("demand_basis") == AGGREGATED_BASIS for cell in horizons.values()
    )


def _weekly(
    horizons: Mapping[int, Mapping[str, Any]], *, weeks: int, field_name: str
) -> tuple[float, ...] | None:
    """The first `weeks` horizons of one field, or None if any is missing.

    None rather than a shorter tuple: a protection period silently computed over
    three weeks when it needs five understates every safety stock it feeds.
    """

    values: list[float] = []
    for horizon in range(1, weeks + 1):
        cell = horizons.get(horizon)
        if cell is None or cell[field_name] is None:
            return None
        values.append(float(cell[field_name]))
    return tuple(values)


def _dc_assortment(inputs: InventoryInputs) -> set[tuple[str, str]]:
    """(dc_location_id, sku_id) pairs a DC is a declared supply node for.

    `assortment_calendar` is store-scoped, so a DC row would otherwise read as
    de-assorted and every DC position would be published as residual-only. A DC
    is "active" for a SKU when some store it supplies over a declared lane has
    that SKU assorted -- which is what a distribution centre's assortment means.
    """

    stores_by_dc: dict[str, set[str]] = defaultdict(set)
    for lane in inputs.lanes:
        stores_by_dc[str(lane["supply_location_id"])].add(
            str(lane["demand_location_id"])
        )
    store_skus: dict[str, set[str]] = defaultdict(set)
    for row in inputs.positions.itertuples(index=False):
        if str(row.location_kind) == "store" and bool(row.assortment_active):
            store_skus[str(row.location_id)].add(str(row.sku_id))
    return {
        (dc, sku)
        for dc, stores in stores_by_dc.items()
        for store in stores
        for sku in store_skus.get(store, set())
    }


def _emitted_positions(inputs: InventoryInputs) -> pd.DataFrame:
    """Active-or-residual rows only, with derived availability attached."""

    frame = inputs.positions.copy()
    _require(
        not frame.empty,
        "no canonical positions at this origin; an inventory bundle over zero "
        "positions would publish thirteen empty artifacts as if they were facts",
    )
    dc_active = _dc_assortment(inputs)
    active = [
        (
            bool(row.assortment_active)
            if str(row.location_kind) == "store"
            else (str(row.location_id), str(row.sku_id)) in dc_active
        )
        for row in frame.itertuples(index=False)
    ]
    frame["assortment_active"] = active
    residual = frame["on_hand_units"].astype(int).gt(0) & ~frame["assortment_active"]
    frame = frame.loc[frame["assortment_active"] | residual].copy()
    frame["residual_only"] = ~frame["assortment_active"]
    frame["atp_units"] = [
        _atp(row._asdict()) for row in frame.itertuples(index=False)
    ]
    frame["position_units"] = [
        inventory_position(_position(row._asdict()))
        for row in frame.itertuples(index=False)
    ]
    return frame.reset_index(drop=True)


# -- artifact builders ---------------------------------------------------------

def _build_positions(emitted: pd.DataFrame) -> pd.DataFrame:
    return emitted[list(ARTIFACT_COLUMNS["inventory_positions"])].copy()


def _build_stock_health(
    emitted: pd.DataFrame,
    *,
    trailing: Mapping[tuple[str, str, str], Decimal],
    policy: Mapping[str, Mapping[str, Any]],
) -> pd.DataFrame:
    """The engine already returns the artifact's three columns, reason included.

    Deliberately not post-processed: `classify_health` decides both the class and
    why a cover is absent (DEAD_STOCK_NO_DEMAND vs DEAD_STOCK_DEASSORTED), and
    substituting a reason here would let the published row disagree with the
    engine's own classification.
    """

    rows: list[dict[str, Any]] = []
    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        key = (market, str(row["location_id"]), str(row["sku_id"]))
        market_policy = policy[market]
        verdict = classify_health(
            position=_position(row),
            trailing_avg_daily_units=trailing.get(key, Decimal(0)),
            assortment_active=bool(row["assortment_active"]),
            understock_cover_days=_decimal(
                market_policy["understockCoverDays"], "7"
            ),
            overstock_cover_days=_decimal(market_policy["overstockCoverDays"], "45"),
        )
        cover = verdict["cover_days"]
        rows.append(
            {
                "market_id": market,
                "location_id": row["location_id"],
                "sku_id": row["sku_id"],
                "health_class": verdict["health_class"],
                "cover_days": None if cover is None else float(cover),
                "reason_code": verdict["reason_code"],
            }
        )
    frame = pd.DataFrame(rows, columns=list(ARTIFACT_COLUMNS["inventory_stock_health"]))
    if not frame.empty:
        # 0010's truth table, asserted here rather than discovered at COPY time.
        inconsistent = frame["cover_days"].isna() != frame["reason_code"].notna()
        _require(
            not bool(inconsistent.any()),
            f"classify_health returned {int(inconsistent.sum())} rows where an "
            "absent cover carries no reason or a present one carries a reason",
        )
    return frame


def _build_demand_at_risk(
    emitted: pd.DataFrame,
    *,
    forecasts: Mapping[tuple[str, str, str], Mapping[int, Mapping[str, Any]]],
    allocations: pd.DataFrame,
    supply: Mapping[tuple[str, str, str], "CellSupply"],
    inputs: InventoryInputs,
    ledgers: dict[str, PartialConsumerLedger],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Risk over the exact protection window, with ATP consumed exactly once.

    The previous implementation emitted one row per horizon and copied the
    node's full ATP onto every row. Summing ``max(P90[h] - ATP, 0)`` therefore
    replenished the same stock balance at the start of every future week. It also
    indexed a three-channel forecast without ``channel_id``, so two channels were
    overwritten and one arbitrary channel became the node demand.

    This implementation keeps the served SeriesKey grain, allocates the one node
    ATP pool through the governed channel allocator, sums each channel's P90 over
    the fractional lead+review window, and subtracts that channel allocation
    once. Channel exposures are then added back to the node row the existing
    inventory read models consume. The sum is an exposure measure over leaf
    scenarios; it is never labelled the statistical P90 of aggregate demand.
    """

    channel_forecasts = _index_channel_forecast(inputs)
    prices, fallback_prices = _index_unit_prices(inputs)
    channels_by_node: dict[
        tuple[str, str, str],
        dict[str, Mapping[int, Mapping[str, Any]]],
    ] = defaultdict(dict)
    for (market, location, sku, channel), horizons in channel_forecasts.items():
        channels_by_node[(market, location, sku)][channel] = horizons

    allocated = {
        (
            str(row.market_id),
            str(row.location_id),
            str(row.sku_id),
            str(row.channel_id),
        ): int(row.allocated_units)
        for row in allocations.itertuples(index=False)
    }

    per_market_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # One final row per emitted node. ``reason`` is None only when every channel
    # contributing to that node is assessable over the whole protection window.
    cells: dict[tuple[str, str, str], dict[str, Any]] = {}

    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        sku = str(row["sku_id"])
        key = (market, location, sku)
        cell_supply = supply[key]
        if not cell_supply.resolved:
            cells[key] = {
                "reason": UNRESOLVED_ROUTE_REASON,
                "resolution_reason": str(cell_supply.resolution_reason),
                "weeks": None,
            }
            continue

        weeks = cell_supply.horizon_weeks
        protection_days = cell_supply.protection_days
        assert weeks is not None and protection_days is not None
        native_channels = channels_by_node.get(key)

        # Store demand is published at SeriesKey grain. DC demand has no native
        # series; retain the existing node branch so it is withheld under the
        # explicit aggregate-interval reason rather than disappearing.
        if native_channels:
            reason: str | None = None
            for channel, horizons in sorted(native_channels.items()):
                expected = _weekly(
                    horizons, weeks=weeks, field_name="expected_units"
                )
                p50 = _weekly(horizons, weeks=weeks, field_name="yhat_p50")
                _require(
                    expected is not None and p50 is not None,
                    f"served forecast is incomplete for {(market, location, sku, channel)} "
                    f"over h1..h{weeks}",
                )
                p90 = _weekly(horizons, weeks=weeks, field_name="yhat_p90")
                first_missing = next(
                    (
                        horizon
                        for horizon in range(1, weeks + 1)
                        if horizon not in horizons
                        or not bool(horizons[horizon]["interval_available"])
                        or horizons[horizon]["yhat_p90"] is None
                    ),
                    None,
                )
                available = p90 is not None and first_missing is None
                if not available:
                    reason = COLD_START_REASON

                price = prices.get((market, location, sku, channel))
                if price is None:
                    price = fallback_prices.get((market, sku))
                _require(
                    not available or price is not None,
                    "no origin-visible realised selling price for "
                    f"{(market, location, sku, channel)} or market/SKU fallback",
                )
                per_market_rows[market].append(
                    {
                        "sku_id": sku,
                        "store_id": location,
                        "channel_id": channel,
                        "horizon_week": first_missing or weeks,
                        "interval_available": available,
                        "expected_units": fractional_horizon_sum(
                            expected, protection_days
                        ),
                        "yhat_p50": fractional_horizon_sum(p50, protection_days),
                        "yhat_p90": (
                            None
                            if p90 is None
                            else fractional_horizon_sum(p90, protection_days)
                        ),
                        # The governed allocation conserves the ONE node ATP pool.
                        # A channel absent from trailing contention receives zero,
                        # never a fresh copy of the whole node balance.
                        "atp_units": allocated.get(
                            (market, location, sku, channel), 0
                        ),
                        "unit_price_minor": price,
                        "currency_code": (
                            None if price is None else inputs.currency_by_market[market]
                        ),
                    }
                )
            cells[key] = {"reason": reason, "weeks": weeks}
            continue

        horizons = forecasts.get(key, {})
        expected = _weekly(horizons, weeks=weeks, field_name="expected_units")
        p50 = _weekly(horizons, weeks=weeks, field_name="yhat_p50")
        p90 = _weekly(horizons, weeks=weeks, field_name="yhat_p90")
        absent = not horizons
        aggregated = _is_aggregated(horizons)
        reason = (
            NO_NODE_FORECAST_REASON
            if absent
            else NO_NODE_INTERVAL_REASON
            if aggregated
            else COLD_START_REASON
            if p90 is None
            else None
        )
        node_price = prices.get((market, location, sku, NODE_CHANNEL))
        if node_price is None:
            node_price = fallback_prices.get((market, sku))
        _require(
            reason is not None or node_price is not None,
            "no origin-visible realised selling price for assessed node "
            f"{(market, location, sku)} or market/SKU fallback",
        )
        cells[key] = {"reason": reason, "weeks": weeks}
        # Even a withheld node reaches the partial-consumer ledger so coverage is
        # disclosed. It cannot be valued because the interval branch stops first.
        per_market_rows[market].append(
            {
                "sku_id": sku,
                "store_id": location,
                "channel_id": NODE_CHANNEL,
                "horizon_week": weeks,
                "interval_available": reason is None,
                "expected_units": (
                    0.0
                    if expected is None
                    else fractional_horizon_sum(expected, protection_days)
                ),
                "yhat_p50": (
                    None if p50 is None else fractional_horizon_sum(p50, protection_days)
                ),
                "yhat_p90": (
                    None if p90 is None else fractional_horizon_sum(p90, protection_days)
                ),
                "atp_units": int(row["atp_units"]),
                "unit_price_minor": node_price,
                "currency_code": (
                    None
                    if node_price is None
                    else inputs.currency_by_market[market]
                ),
            }
        )

    assessed: dict[tuple[str, str, str], float] = defaultdict(float)
    assessed_value: dict[tuple[str, str, str], int] = defaultdict(int)
    for market in sorted(per_market_rows):
        assessment = demand_at_risk(
            per_market_rows[market], consumer=f"demand_at_risk:{market}"
        )
        for assessed_row in assessment["rows"]:
            key = (
                market,
                str(assessed_row["store_id"]),
                str(assessed_row["sku_id"]),
            )
            assessed[key] += float(assessed_row["risk_units"])
            value = assessed_row["risk_value_minor"]
            _require(value is not None, f"assessed demand-at-risk row {key} has no value")
            assessed_value[key] += int(value)
        ledgers[f"demand_at_risk:{market}"] = PartialConsumerLedger(
            consumer=f"demand_at_risk:{market}",
            skipped_rows=assessment["unassessed"]["rows"],
            skipped_demand_units=assessment["unassessed"]["demandUnits"],
        )

    rows: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for (market, location, sku), cell in sorted(cells.items()):
        reason = cell["reason"]
        if reason is None:
            rows.append(
                {
                    "market_id": market,
                    "location_id": location,
                    "sku_id": sku,
                    "channel_id": NODE_CHANNEL,
                    "risk_units": float(assessed[(market, location, sku)]),
                    "risk_value_minor": int(
                        assessed_value[(market, location, sku)]
                    ),
                    "currency_code": inputs.currency_by_market[market],
                    "interval_available": True,
                    "reason_code": None,
                }
            )
            continue

        rows.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "channel_id": NODE_CHANNEL,
                "risk_units": None,
                "risk_value_minor": None,
                "currency_code": None,
                "interval_available": False,
                "reason_code": reason,
            }
        )
        if reason == UNRESOLVED_ROUTE_REASON:
            exception_class = "supply_route_unresolved"
            severity = "warning"
            evidence = (
                f"{cell['resolution_reason']}; with no declared route there is no "
                "protection period to assess risk over"
            )
        elif reason == NO_NODE_FORECAST_REASON:
            exception_class = "node_forecast_absent"
            severity = "info"
            evidence = (
                "no forecast series exists for this node, so it has no interval "
                "to assess risk from"
            )
        elif reason == NO_NODE_INTERVAL_REASON:
            exception_class = "node_interval_basis_unavailable"
            severity = "info"
            evidence = (
                "node demand is the additive expectation of supplied stores; "
                "summing their P90s is forbidden"
            )
        else:
            exception_class = "cold_start_interval_unavailable"
            severity = "info"
            evidence = (
                f"demand-at-risk needs horizons 1..{cell['weeks']}; the "
                "cold-start interval is calibrated through 4"
            )
        exceptions.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "channel_id": NODE_CHANNEL,
                "exception_class": exception_class,
                "severity": severity,
                "reason_code": reason,
                "evidence": evidence,
            }
        )

    frame = pd.DataFrame(
        rows, columns=list(ARTIFACT_COLUMNS["inventory_demand_at_risk"])
    )
    if not frame.empty:
        frame["risk_value_minor"] = frame["risk_value_minor"].astype("Int64")
    return frame, exceptions


def _build_ageing(
    emitted: pd.DataFrame,
    *,
    batches: pd.DataFrame,
    health: pd.DataFrame,
    policy: Mapping[str, Mapping[str, Any]],
    as_of: date,
) -> pd.DataFrame:
    cover_by_key = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): row.cover_days
        for row in health.itertuples(index=False)
    }
    residual_by_key = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): bool(
            row.residual_only
        )
        for row in emitted.itertuples(index=False)
    }
    aggregated: dict[tuple[str, str, str, str], int] = defaultdict(int)
    oldest: dict[tuple[str, str, str, str], int] = {}
    batch_units_by_cell: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in batches.itertuples(index=False):
        key3 = (str(row.market_id), str(row.location_id), str(row.sku_id))
        if key3 not in residual_by_key:
            continue
        received = _as_date(row.received_on)
        if received is None:
            continue
        age_days = (as_of - received).days
        bucket = age_bucket(on_hand_age_days=age_days)
        key = (*key3, bucket)
        aggregated[key] += int(row.on_hand_units)
        batch_units_by_cell[key3] += int(row.on_hand_units)
        oldest[key] = max(oldest.get(key, age_days), age_days)

    # Store positions have no lot/batch ledger in Gulf, but their native snapshot
    # does carry the oldest receipt still represented in on-hand. Age only the
    # uncovered holding from that source field; a cell with full batch lineage is
    # unchanged, and absent receipt evidence is never replaced with today's date.
    for row in emitted.itertuples(index=False):
        values = row._asdict()
        key3 = (str(row.market_id), str(row.location_id), str(row.sku_id))
        uncovered = int(row.on_hand_units) - batch_units_by_cell.get(key3, 0)
        if uncovered <= 0:
            continue
        received = _as_date(values.get("oldest_receipt_date"))
        if received is None:
            continue
        age_days = (as_of - received).days
        bucket = age_bucket(on_hand_age_days=age_days)
        key = (*key3, bucket)
        aggregated[key] += uncovered
        oldest[key] = max(oldest.get(key, age_days), age_days)

    # Preserve the remainder explicitly. Dropping it makes an enterprise card
    # silently warehouse-only/store-incomplete; assigning today's date makes it
    # look fresh; assigning the oldest known batch overstates its age. An
    # unavailable bucket is the only truthful member of the additive partition.
    accounted_by_cell: dict[tuple[str, str, str], int] = defaultdict(int)
    for key, units in aggregated.items():
        accounted_by_cell[key[:3]] += units
    for row in emitted.itertuples(index=False):
        key3 = (str(row.market_id), str(row.location_id), str(row.sku_id))
        accounted = accounted_by_cell.get(key3, 0)
        missing = int(row.on_hand_units) - accounted
        if missing < 0:
            raise InventoryBuildError(
                "age lineage exceeds on-hand for "
                f"{key3}: aged={accounted}, on_hand={int(row.on_hand_units)}"
            )
        if missing > 0:
            aggregated[(*key3, "unavailable")] += missing
    rows: list[dict[str, Any]] = []
    for key, units in sorted(aggregated.items()):
        market, location, sku, bucket = key
        market_policy = policy[market]
        cover = cover_by_key.get((market, location, sku))
        action = (
            {"action": "age_evidence_unavailable", "markdown_pct": None}
            if bucket == "unavailable"
            else ageing_action(
                on_hand_age_days=oldest[key],
                cover_days=_optional_decimal(cover),
                hold_cover_days=int(market_policy["holdCoverDays"]),
                markdown_cover_days=int(market_policy["markdownCoverDays"]),
                markdown_pct=_decimal(market_policy["markdownPct"]),
            )
        )
        markdown = action["markdown_pct"]
        rows.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "age_bucket": bucket,
                "on_hand_units": int(units),
                "action": action["action"],
                "markdown_pct": None if markdown is None else float(markdown),
                "residual_only": residual_by_key[(market, location, sku)],
            }
        )
    return pd.DataFrame(rows, columns=list(ARTIFACT_COLUMNS["inventory_ageing"]))


def _build_expiry_waste(
    emitted: pd.DataFrame,
    *,
    batches: pd.DataFrame,
    waste: pd.DataFrame,
    prior_waste: pd.DataFrame,
    unit_costs: Mapping[tuple[str, str, str], tuple[int | None, str | None]],
    policy: Mapping[str, Mapping[str, Any]],
    currency_by_market: Mapping[str, str],
    as_of: date,
) -> pd.DataFrame:
    """Forward exposure from batches, realized loss from waste events.

    Two different facts kept in two different columns. `expiring_units` and
    `exposure_minor` are stock that WILL expire inside the policy window;
    `expired_units` and `waste_units` are stock that already did and was written
    off. Collapsing them would make a screen unable to tell whether its own
    intervention worked.

    `prior_waste_units`/`prior_waste_minor` carry the same realized loss for the
    91-day window immediately before, so the read model can serve Waste Reduction
    = (prior - current) / prior. The prior value is the prior units valued at the
    cell's accepted unit cost -- the same WAC every other money column uses -- so
    it is left NULL when that cost is unknown rather than valuing waste at zero.
    """

    keys = {
        (str(row.market_id), str(row.location_id), str(row.sku_id))
        for row in emitted.itertuples(index=False)
    }
    waste_by_key = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): (
            int(row.waste_units),
            int(row.expired_units),
        )
        for row in waste.itertuples(index=False)
    }
    prior_by_key = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): int(
            row.prior_waste_units
        )
        for row in prior_waste.itertuples(index=False)
    }
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in batches.itertuples(index=False):
        key = (str(row.market_id), str(row.location_id), str(row.sku_id))
        if key not in keys:
            continue
        grouped[key].append(
            {
                "batch_id": row.batch_id,
                "expiry_date": _as_date(row.expires_on),
                "on_hand_units": int(row.on_hand_units),
                "unit_cost_minor": _optional_int(row.unit_cost_minor),
                "currency_code": currency_by_market[key[0]],
            }
        )
    rows: list[dict[str, Any]] = []
    # A cell wasting in the prior window but not now is a genuine reduction, so it
    # is emitted (when still an active position) even with no current exposure or
    # waste -- otherwise the eliminated baseline would silently drop out of the
    # aggregate and understate the reduction.
    for key in sorted(
        (keys & set(grouped)) | (keys & set(waste_by_key)) | (keys & set(prior_by_key))
    ):
        market, location, sku = key
        exposure = expiry_exposure(
            grouped.get(key, []),
            as_of=as_of,
            window_days=int(policy[market]["expiryWindowDays"]),
        )
        waste_units, expired_units = waste_by_key.get(key, (0, 0))
        prior_units = prior_by_key.get(key, 0)
        cost, _ = unit_costs.get(key, (None, None))
        # Exposure carries a currency only when every expiring batch was costed;
        # a prior-only row has no batch, so fall back to the market's currency.
        currency = exposure["currency_code"] or currency_by_market.get(market)
        rows.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "expiring_units": int(exposure["expiring_units"]),
                "expired_units": int(expired_units),
                "waste_units": int(waste_units),
                # Exposure has no meaning without a currency, and the engine
                # returns one only when every expiring batch carried a cost.
                "exposure_minor": (
                    int(exposure["exposure_minor"])
                    if exposure["currency_code"]
                    else None
                ),
                "currency_code": currency,
                "prior_waste_units": int(prior_units),
                # Valued at the accepted unit cost, same as every money column;
                # NULL when that cost is unknown rather than valuing at zero.
                "prior_waste_minor": (
                    int(prior_units * cost) if cost is not None else None
                ),
            }
        )
    frame = pd.DataFrame(rows, columns=list(ARTIFACT_COLUMNS["inventory_expiry_waste"]))
    if not frame.empty:
        frame["exposure_minor"] = frame["exposure_minor"].astype("Int64")
        frame["prior_waste_minor"] = frame["prior_waste_minor"].astype("Int64")
    return frame


def _build_valuation(
    emitted: pd.DataFrame,
    *,
    unit_costs: Mapping[tuple[str, str, str], tuple[int | None, str | None]],
    wms_variance: pd.DataFrame,
    currency_by_market: Mapping[str, str],
) -> pd.DataFrame:
    """Gross value per market/location/category, at store WAC (P4-D6).

    A category is valued only when EVERY on-hand SKU in it has a cost. Summing
    the SKUs that happen to have one and presenting the total as the category's
    value understates it silently, which is worse than saying it is unavailable.
    """

    variance_by_location: dict[tuple[str, str], int] = defaultdict(int)
    variance_seen: set[tuple[str, str]] = set()
    for row in wms_variance.itertuples(index=False):
        pair = (str(row.market_id), str(row.location_id))
        variance_by_location[pair] += int(row.variance_units)
        variance_seen.add(pair)

    totals: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        group = (market, location, str(row["category"]))
        bucket = totals.setdefault(
            group, {"minor": 0, "methods": set(), "priced": True}
        )
        cost, method = unit_costs.get(
            (market, location, str(row["sku_id"])), (None, None)
        )
        units = int(row["on_hand_units"])
        if cost is None:
            if units > 0:
                bucket["priced"] = False
            continue
        bucket["minor"] += units * cost
        if method:
            bucket["methods"].add(method)

    rows: list[dict[str, Any]] = []
    for group, bucket in sorted(totals.items()):
        market, location, category = group
        priced = bool(bucket["priced"])
        methods = sorted(bucket["methods"])
        rows.append(
            {
                "market_id": market,
                "location_id": location,
                "category": category,
                "gross_value_minor": int(bucket["minor"]) if priced else None,
                # Currency is a property of the market, not of the valuation, so
                # it stays populated on an unpriced row: the reader still needs to
                # know which currency the missing number would have been in.
                "currency_code": currency_by_market[market],
                "cost_method": (
                    None
                    if not priced
                    else ("mixed" if len(methods) > 1 else (methods[0] or "store_wac"))
                ),
                "cost_reason_code": None if priced else COST_UNAVAILABLE,
                "wms_variance_units": (
                    int(variance_by_location[(market, location)])
                    if (market, location) in variance_seen
                    else None
                ),
            }
        )
    frame = pd.DataFrame(rows, columns=list(ARTIFACT_COLUMNS["inventory_valuation"]))
    if not frame.empty:
        for column in ("gross_value_minor", "wms_variance_units"):
            frame[column] = frame[column].astype("Int64")
    return frame


@dataclass(frozen=True)
class CellSupply:
    """One cell's resolved supply, and the protection window it implies.

    Resolved once per cell and shared by every artifact that needs it, because
    two artifacts computing the same window independently is how they end up
    disagreeing about whether a cell was assessable.
    """

    supply_location_id: str | None
    lead_time_days: int | None
    moq: int | None
    pack_qty: int | None
    resolution_reason: str | None
    protection_days: int | None
    horizon_weeks: int | None

    @property
    def resolved(self) -> bool:
        return self.resolution_reason is None


def _supply_for(row: Mapping[str, Any], *, inputs: InventoryInputs) -> CellSupply:
    """Resolve one cell's supply, or fail closed with the resolver's reason.

    Branches on echelon because the declared contracts do. A store's supply is a
    DC over a `service_lanes` row whose `transit_days` IS the lead time -- no
    supply term exists for a store destination in this dataset, and asking for one
    would return SUPPLY_TERM_ABSENT on every store. A DC's supply is an external
    supplier under a `supply_terms` row, which carries its own lead time, MOQ and
    pack, and needs no lane because the origin is outside the network.

    There is deliberately NO default lead time, MOQ or pack. Policy v2 says
    `laneResolution.unresolvedBehavior: fail_closed` and
    `supplyTermResolution.ambiguityBehavior: fail_closed`, and an earlier version
    of this function fell back to market defaults instead -- which would have
    published a confident reorder point for a node whose route nobody declared.
    Falling back is exactly what fail-closed forbids: the recommendation looks
    identical to a resolved one and there is no way to tell them apart on screen.
    """

    location = str(row["location_id"])
    if str(row["location_kind"]) == "store":
        try:
            lane = active_lanes(
                inputs.lanes,
                demand_location_id=location,
                channel_id=None,
                on_date=inputs.as_of,
            )[0]
        except ResolutionError as error:
            return _unresolved(error.reason_code)
        return _resolved(
            row,
            inputs=inputs,
            supply_location_id=str(lane["supply_location_id"]),
            lead_time_days=int(lane["transit_days"]),
            # An internal DC -> store move has no purchase-order minimum: the
            # units already belong to the network. Pack rounding is a supplier
            # constraint and there is no supplier on this leg.
            moq=1,
            pack_qty=1,
        )
    matching = [
        term
        for term in inputs.supply_terms
        if str(term["destination_location_id"]) == location
    ]
    last_reason = "SUPPLY_TERM_ABSENT"
    for origin in sorted({str(term["origin_id"]) for term in matching}):
        try:
            term = resolve_supply_term(
                matching,
                destination_location_id=location,
                origin_kind="external_supplier",
                origin_id=origin,
                sku_id=str(row["sku_id"]),
                dept_id=str(row.get("dept_id") or ""),
                category=str(row["category"]),
                on_date=inputs.as_of,
            )
        except ResolutionError as error:
            last_reason = error.reason_code
            continue
        return _resolved(
            row,
            inputs=inputs,
            supply_location_id=origin,
            lead_time_days=int(term["lead_time_days"]),
            moq=int(term["moq"]),
            pack_qty=int(term["pack_qty"]),
        )
    return _unresolved(last_reason)


def _unresolved(reason: str) -> CellSupply:
    return CellSupply(
        supply_location_id=None,
        lead_time_days=None,
        moq=None,
        pack_qty=None,
        resolution_reason=reason,
        protection_days=None,
        horizon_weeks=None,
    )


def _resolved(
    row: Mapping[str, Any],
    *,
    inputs: InventoryInputs,
    supply_location_id: str,
    lead_time_days: int,
    moq: int,
    pack_qty: int,
) -> CellSupply:
    protection = protection_period_days(
        lead_time_days,
        int(inputs.policy[str(row["market_id"])]["reviewPeriodDays"]),
    )
    return CellSupply(
        supply_location_id=supply_location_id,
        lead_time_days=lead_time_days,
        moq=moq,
        pack_qty=pack_qty,
        resolution_reason=None,
        protection_days=protection,
        horizon_weeks=required_horizon_weeks(protection),
    )


def _resolve_supply(
    emitted: pd.DataFrame, *, inputs: InventoryInputs
) -> dict[tuple[str, str, str], CellSupply]:
    """Resolve every cell's supply and protection window exactly once."""

    return {
        (
            str(row["market_id"]),
            str(row["location_id"]),
            str(row["sku_id"]),
        ): _supply_for(row, inputs=inputs)
        for row in (record._asdict() for record in emitted.itertuples(index=False))
    }


def _replenishment_plan(
    emitted: pd.DataFrame,
    *,
    forecasts: Mapping[tuple[str, str, str], Mapping[int, Mapping[str, Any]]],
    trailing: Mapping[tuple[str, str, str], Decimal],
    inputs: InventoryInputs,
    abc_classes: Mapping[tuple[str, str], Mapping[str, Any]],
    supply: Mapping[tuple[str, str, str], CellSupply],
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    """Recommendations, safety stock and the exceptions both produced.

    They are built together because they share one gate decision per cell.
    Computing them separately would mean asking the interval question twice and
    risking two different answers for one row.
    """

    recommendations: list[dict[str, Any]] = []
    safety_rows: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    lead_time_variance = _lead_time_variance_weeks(inputs)

    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        sku = str(row["sku_id"])
        key = (market, location, sku)
        market_policy = inputs.policy[market]
        abc = abc_classes.get((sku, location), {})
        abc_class = abc.get("abc_class")
        service_level = market_policy["serviceLevelsByClass"].get(str(abc_class))

        cell = supply[key]
        supply_location = cell.supply_location_id
        protection = cell.protection_days
        weeks = cell.horizon_weeks
        horizons = forecasts.get(key, {})

        # An unresolved route is checked FIRST and separately. Policy v2 fails
        # closed here, and there is no protection period to ask the interval
        # question about, so this is not a cold-start row wearing a different
        # label -- it withholds for its own reason and the exception says which.
        gate_reason: str | None = None
        exception_class = "cold_start_interval_unavailable"
        severity = "info"
        evidence = ""
        spreads: tuple[float, ...] | None = None
        expected: tuple[float, ...] | None = None
        p50: tuple[float, ...] | None = None
        if not cell.resolved:
            gate_reason = UNRESOLVED_ROUTE_REASON
            exception_class = "supply_route_unresolved"
            severity = "warning"
            evidence = (
                f"{cell.resolution_reason}; policy v2 fails closed rather than "
                "applying a default lead time to a route nobody declared"
            )
        else:
            assert weeks is not None and protection is not None
            try:
                require_interval_horizon(
                    consumer="replenishment", required_horizon_weeks=weeks
                )
            except IntervalUnavailable:
                gate_reason = COLD_START_REASON
                evidence = (
                    f"protection period {protection}d needs horizon {weeks}; the "
                    "cold-start interval is calibrated to 4"
                )
            if gate_reason is None:
                upper = _weekly(horizons, weeks=weeks, field_name="yhat_p90")
                p50 = _weekly(horizons, weeks=weeks, field_name="yhat_p50")
                expected = _weekly(
                    horizons, weeks=weeks, field_name="expected_units"
                )
                if not horizons:
                    # Nothing forecast this node at all. A DC's demand is derived
                    # from the stores it supplies rather than forecast directly, so
                    # this is a modelling boundary and NOT a calibration gap --
                    # calling it cold-start would send someone to wait for
                    # calibration that was never the obstacle.
                    gate_reason = NO_NODE_FORECAST_REASON
                    exception_class = "node_forecast_absent"
                    evidence = (
                        "no forecast series exists for this node, so it has no "
                        "interval of its own at any horizon"
                    )
                elif _is_aggregated(horizons):
                    # A node whose demand is the additive expectation of its stores
                    # has volume and no interval, because policy v2 forbids
                    # summing channel P90s. Expected volume is still published, so
                    # the warehouse screen shows real demand; only the safety stock
                    # that needs a spread is withheld.
                    gate_reason = NO_NODE_INTERVAL_REASON
                    exception_class = "node_interval_basis_unavailable"
                    evidence = (
                        "node demand is the additive expectation of supplied stores; "
                        "summing their P90s is forbidden because the sum of upper "
                        "quantiles assumes every store peaks in the same week"
                    )
                elif upper is None or p50 is None or expected is None:
                    gate_reason = COLD_START_REASON
                    evidence = (
                        f"the forecast covers this node but not every horizon in "
                        f"1..{weeks} that a {protection}d protection period needs"
                    )
                else:
                    spreads = tuple(
                        max(0.0, high - mid) for high, mid in zip(upper, p50)
                    )
            if gate_reason is None and service_level is None:
                # No ABC class means no service level, and inventing one would set
                # a target nobody chose. P4-D6 forbids borrowing another node's
                # cost, so an uncosted cell is genuinely unclassifiable.
                gate_reason = str(abc.get("reason_code") or NO_ABC_COST_REASON)
                if gate_reason not in GOVERNED_REASONS:
                    gate_reason = NO_ABC_COST_REASON
                exception_class = "abc_class_unavailable"
                severity = "warning"
                evidence = (
                    f"{gate_reason}: no accepted unit cost, so cost-weighted ABC "
                    "cannot rank this cell and no service level applies"
                )

        if gate_reason is not None or spreads is None or expected is None:
            governed = gate_reason or COLD_START_REASON
            safety_rows.append(
                {
                    "market_id": market,
                    "location_id": location,
                    "sku_id": sku,
                    "abc_class": abc_class,
                    "service_level": None,
                    "safety_stock_units": None,
                    # No buffer means no drivers. Zeros here would read as "demand
                    # and lead time both contribute nothing", which is a
                    # measurement this row does not have.
                    "safety_stock_demand_units": None,
                    "safety_stock_lead_time_units": None,
                    "lead_time_variability_reason_code": None,
                    "interval_available": False,
                    "reason_code": governed,
                }
            )
            recommendations.append(
                {
                    "market_id": market,
                    "destination_location_id": location,
                    "supply_location_id": supply_location,
                    "sku_id": sku,
                    "recommended_units": None,
                    "reorder_point_units": None,
                    "order_up_to_units": None,
                    # The resolved lead time, even on a withheld row: the supply
                    # term resolved even where the interval did not, and it is
                    # what a planner needs to judge when a manual order lands.
                    "lead_time_days": cell.lead_time_days,
                    "interval_available": False,
                    "reason_code": governed,
                    "erp_status": ERP_STATUS,
                }
            )
            exceptions.append(
                {
                    "market_id": market,
                    "location_id": location,
                    "sku_id": sku,
                    "channel_id": None,
                    "exception_class": exception_class,
                    "severity": severity,
                    "reason_code": governed,
                    "evidence": evidence,
                }
            )
            continue

        assert protection is not None and cell.moq is not None
        assert cell.pack_qty is not None
        # Lead-time variability is a SUPPLIER property, and only a DC's supply has
        # one. A store is replenished over an internal service lane whose origin is
        # our own DC, and no supplier-performance row exists for it -- the same
        # reason Supplier Planning withholds a risk class for an internal warehouse.
        # That is reason-coded rather than treated as zero variance, which would
        # publish a confident buffer for a route whose variability nobody measured.
        variance, variance_reason = (
            lead_time_variance.get(
                (market, str(cell.supply_location_id)),
                (None, NO_LEAD_TIME_VARIANCE_REASON),
            )
            if str(row["location_kind"]) != "store"
            else (None, NO_LEAD_TIME_VARIANCE_REASON)
        )
        stock = safety_stock_units(
            weekly_spreads=spreads,
            protection_days=protection,
            service_level=service_level,
            weekly_expected=expected,
            lead_time_variance_weeks=variance,
            lead_time_reason_code=variance_reason,
        )
        point = reorder_point(
            weekly_expected=expected,
            protection_days=protection,
            safety_stock=stock.total_units,
        )
        level = order_up_to_level(
            reorder_point_units=point,
            weekly_expected=expected,
            review_period_days=int(market_policy["reviewPeriodDays"]),
        )
        position_units = int(row["position_units"])
        daily = float(trailing.get(key, Decimal(0)))
        recommended: int | None
        # A solver refusal is not a withheld interval, so it cannot borrow the
        # interval's reason column semantics -- but it still owes the screen a
        # reason, or the cell renders bare.
        refusal: str | None = None
        if position_units > point:
            # Above the reorder point there is nothing to order. Recommending the
            # gap to the order-up-to level anyway is what turns a periodic review
            # policy into a continuous one and doubles working capital.
            recommended = 0
        else:
            try:
                recommended = apply_order_constraints(
                    level - position_units,
                    moq=cell.moq,
                    pack_qty=cell.pack_qty,
                    inventory_position_units=position_units,
                    avg_daily_demand=daily,
                    max_cover_days=int(market_policy["maxCoverDays"]),
                )
            except OrderConstraintError as error:
                recommended = None
                refusal = error.reason_code
                exceptions.append(
                    {
                        "market_id": market,
                        "location_id": location,
                        "sku_id": sku,
                        "channel_id": None,
                        "exception_class": "order_constraint_conflict",
                        "severity": "warning",
                        "reason_code": error.reason_code,
                        "evidence": f"{error.reason_code}: {error}",
                    }
                )
        safety_rows.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "abc_class": abc_class,
                "service_level": float(Decimal(str(service_level))),
                "safety_stock_units": float(stock.total_units),
                # The two drivers policy v2's formula names. They combine in
                # quadrature, so they do not sum to the total -- the screen shows
                # them as contributions, not as an additive split.
                "safety_stock_demand_units": float(stock.demand_units),
                "safety_stock_lead_time_units": float(stock.lead_time_units),
                "lead_time_variability_reason_code": stock.lead_time_reason_code,
                "interval_available": True,
                "reason_code": None,
            }
        )
        recommendations.append(
            {
                "market_id": market,
                "destination_location_id": location,
                "supply_location_id": supply_location,
                "sku_id": sku,
                "recommended_units": recommended,
                "reorder_point_units": float(point),
                "order_up_to_units": float(level),
                # Already resolved to compute the protection period above, and
                # discarded until now: the screen's Lead Time and Expected Receipt
                # columns were blank on every row for want of this one integer.
                "lead_time_days": cell.lead_time_days,
                # The interval WAS available; a null recommendation here means the
                # constraint solver refused, and `refusal` says why. 0010's gate on
                # this table is one-directional precisely to admit that state.
                "interval_available": True,
                "reason_code": refusal,
                "erp_status": ERP_STATUS,
            }
        )

    recommendation_frame = pd.DataFrame(
        recommendations,
        columns=list(ARTIFACT_COLUMNS["replenishment_recommendations"]),
    )
    if not recommendation_frame.empty:
        recommendation_frame["recommended_units"] = recommendation_frame[
            "recommended_units"
        ].astype("Int64")
    safety_frame = pd.DataFrame(
        safety_rows, columns=list(ARTIFACT_COLUMNS["replenishment_safety_stock"])
    )
    return recommendation_frame, safety_frame, exceptions


def _build_transfers(
    emitted: pd.DataFrame,
    *,
    inputs: InventoryInputs,
    health: pd.DataFrame,
    trailing: Mapping[tuple[str, str, str], Decimal],
    unit_costs: Mapping[tuple[str, str, str], tuple[int | None, str | None]],
) -> pd.DataFrame:
    """Cover a shortfall over a declared ALTERNATE lane.

    Modelled on the network that exists rather than the one a generic transfer
    engine assumes. Every declared lane here is DC -> store `replenishment`, and
    each store declares a rank-1 primary DC plus a rank-2 alternate; there is no
    store-to-store lane and no `transfer` lane type at all. Proposing store-to-
    store moves would be inventing routes the network never declared.

    So the transfer decision this network supports is: the rank-1 DC cannot cover
    a store the health classifier calls short, and a rank-2 DC holds surplus above
    its own retained cover. That is the case worth surfacing -- following the
    primary lane is already the replenishment recommendation, and publishing it
    twice would double-count the same units.

    Donor and receiver both come from the health classification the screens
    display, so a transfer can never contradict the health row beside it.
    """

    health_by_key = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): str(
            row.health_class
        )
        for row in health.itertuples(index=False)
    }
    atp_by_key: dict[tuple[str, str], int] = {}
    residual_cover: dict[tuple[str, str], int] = {}
    headroom: dict[tuple[str, str], int] = {}
    rows_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        sku = str(row["sku_id"])
        market_policy = inputs.policy[market]
        daily = trailing.get((market, location, sku), Decimal(0))
        atp_by_key[(location, sku)] = int(row["atp_units"])
        residual_cover[(location, sku)] = int(
            daily * int(market_policy["transferDonorRetainedCoverDays"])
        )
        headroom[(location, sku)] = max(
            0,
            int(daily * int(market_policy["maxCoverDays"]))
            - int(row["position_units"]),
        )
        rows_by_key[(market, location, sku)] = row

    candidates: list[TransferCandidate] = []
    for (market, destination, sku), _row in sorted(rows_by_key.items()):
        if health_by_key.get((market, destination, sku)) not in {
            "understock",
            "stockout",
        }:
            continue
        try:
            lanes = active_lanes(
                inputs.lanes,
                demand_location_id=destination,
                channel_id=None,
                on_date=inputs.as_of,
            )
        except ResolutionError:
            continue
        primary, *alternates = lanes
        primary_origin = str(primary["supply_location_id"])
        primary_available = max(
            0,
            atp_by_key.get((primary_origin, sku), 0)
            - residual_cover.get((primary_origin, sku), 0),
        )
        shortfall = headroom[(destination, sku)] - primary_available
        if shortfall <= 0:
            continue
        for lane in alternates:
            origin = str(lane["supply_location_id"])
            if origin == destination:
                continue
            surplus = max(
                0,
                atp_by_key.get((origin, sku), 0)
                - residual_cover.get((origin, sku), 0),
            )
            units = min(surplus, shortfall)
            if units <= 0:
                continue
            cost, _ = unit_costs.get((market, destination, sku), (None, None))
            candidates.append(
                TransferCandidate(
                    lane_id=str(lane["lane_id"]),
                    from_location_id=origin,
                    to_location_id=destination,
                    sku_id=sku,
                    market_id=market,
                    currency_code=inputs.currency_by_market[market],
                    # Benefit is the cost value of demand that would otherwise go
                    # unserved; with no cost on file it is zero rather than a
                    # guess, and the optimizer then ranks it last.
                    units=int(units),
                    expected_benefit_minor=int(units * (cost or 0)),
                    transit_days=int(lane["transit_days"]),
                )
            )
    # Per market, because the optimizer refuses a mixed set and is right to: a
    # transfer lane is declared within a market, and ranking an INR benefit
    # against a USD one would order candidates by exchange rate. The engine has
    # always guarded this; the caller only ever passed one market's worth by
    # accident, because the previous replenishment policy left so little
    # imbalance that only two candidates existed in the whole network. Tightening
    # stock produced candidates in both markets and the guard fired.
    by_market: dict[str, list[TransferCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_market[candidate.market_id].append(candidate)
    accepted: list[Any] = []
    for market in sorted(by_market):
        accepted.extend(
            recommend_transfers(
                by_market[market],
                source_atp=atp_by_key,
                source_residual_cover_units=residual_cover,
                target_headroom_units=headroom,
            )
        )
    return pd.DataFrame(
        accepted, columns=list(ARTIFACT_COLUMNS["replenishment_transfers"])
    )


def _build_allocations(
    emitted: pd.DataFrame, *, inputs: InventoryInputs
) -> pd.DataFrame:
    atp_by_key = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): int(row.atp_units)
        for row in emitted.itertuples(index=False)
    }
    cost_index = _index_unit_costs(inputs)
    channel_rank = {
        str(channel): index + 1
        for index, channel in enumerate(
            sorted({str(row.channel_id) for row in inputs.channel_demand.itertuples(index=False)})
        )
    }
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in inputs.channel_demand.itertuples(index=False):
        key = (str(row.market_id), str(row.location_id), str(row.sku_id))
        if key not in atp_by_key:
            continue
        cost, _ = cost_index.get(key, (None, None))
        grouped[key].append(
            {
                "market_id": key[0],
                "location_id": key[1],
                "channel_id": str(row.channel_id),
                "sku_id": key[2],
                "requested_units": int(row.requested_units),
                # Rank from the channel id's frozen sort order, so the priority is
                # stable across runs rather than a function of row arrival.
                "service_class_rank": channel_rank[str(row.channel_id)],
                "value_weight_minor": int(row.requested_units) * int(cost or 0),
            }
        )
    rows: list[dict[str, Any]] = []
    for key, demands in sorted(grouped.items()):
        market = key[0]
        result = allocate_channels(
            node_atp_units=atp_by_key[key],
            demands=demands,
            minimum_share=_decimal(
                inputs.policy[market]["allocationMinimumShare"], "0"
            ),
        )
        for allocation in result["allocations"]:
            rows.append(
                {
                    "market_id": allocation["market_id"],
                    "location_id": allocation["location_id"],
                    "channel_id": allocation["channel_id"],
                    "sku_id": allocation["sku_id"],
                    "requested_units": int(allocation["requested_units"]),
                    "allocated_units": int(allocation["allocated_units"]),
                    "shortfall_units": int(allocation["shortfall_units"]),
                }
            )
    return pd.DataFrame(
        rows, columns=list(ARTIFACT_COLUMNS["replenishment_allocations"])
    )


def _open_po_by_supplier(
    inputs: InventoryInputs,
) -> dict[tuple[str, str], tuple[int, int]]:
    """Open inbound units and their value, per market and supplier.

    Valued at the accepted unit cost for the RECEIVING cell, which is the same
    cost every other money figure in this bundle is struck at. A cell with no
    accepted cost contributes its units and no value, so the quantity stays
    complete and the money understates rather than inventing a price.
    """

    costs = {
        (str(row.market_id), str(row.location_id), str(row.sku_id)): int(
            row.unit_cost_minor
        )
        for row in inputs.unit_costs.itertuples(index=False)
        if row.unit_cost_minor is not None and not pd.isna(row.unit_cost_minor)
    }
    totals: dict[tuple[str, str], tuple[int, int]] = {}
    for row in inputs.open_purchase_orders.itertuples(index=False):
        key = (str(row.market_id), str(row.supplier_id))
        units = int(row.open_units)
        cost = costs.get(
            (str(row.market_id), str(row.location_id), str(row.sku_id))
        )
        held_units, held_value = totals.get(key, (0, 0))
        totals[key] = (
            held_units + units,
            held_value + (units * cost if cost is not None else 0),
        )
    return totals


def _build_suppliers(inputs: InventoryInputs) -> pd.DataFrame:
    open_po = _open_po_by_supplier(inputs)
    rows: list[dict[str, Any]] = []
    for record in inputs.suppliers.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        std_days = _optional_decimal(row["lead_time_std_days"])
        verdict = supplier_risk(
            otd_rate=_decimal(row["otd_rate"]),
            lead_time_std_days=std_days,
            capacity_confirmed_pct=_decimal(row["capacity_confirmed_pct"]),
            capacity_floor_pct=_decimal(
                inputs.policy[market]["supplierCapacityConfirmedPctFloor"]
            ),
        )
        mean_days = _optional_decimal(row["lead_time_mean_days"])
        rows.append(
            {
                "market_id": market,
                "supplier_id": str(row["supplier_id"]),
                "otd_rate": float(_decimal(row["otd_rate"])),
                "lead_time_mean_days": (
                    None if mean_days is None else float(mean_days)
                ),
                "lead_time_std_days": None if std_days is None else float(std_days),
                "capacity_confirmed_pct": float(
                    _decimal(row["capacity_confirmed_pct"])
                ),
                "risk_class": verdict["risk_class"],
                "reason_codes": list(verdict["reason_codes"]) or None,
                # The scope this supplier serves. `_label` turns the source's own
                # slug into the words the screen shows: "grocery-dairy" reads
                # "Grocery - Dairy", exactly as the SKU dimension does elsewhere.
                "category": (
                    None if row.get("category") is None else str(row["category"])
                ),
                "category_label": (
                    None
                    if row.get("category") is None
                    else _label(str(row["category"]))
                ),
                "scope_count": (
                    None
                    if row.get("scope_count") is None
                    else int(row["scope_count"])
                ),
                "supplier_name": (
                    None
                    if row.get("supplier_name") is None
                    else str(row["supplier_name"])
                ),
                "open_po_units": open_po.get(
                    (market, str(row["supplier_id"])), (0, 0)
                )[0],
                "open_po_value_minor": open_po.get(
                    (market, str(row["supplier_id"])), (0, 0)
                )[1],
                # The currency the open-PO value is denominated in. Without it a
                # multi-market slice would add dollars to rupees, which is the one
                # defect this phase spent the most time removing.
                "currency_code": (
                    None
                    if row.get("currency_code") is None
                    else str(row["currency_code"])
                ),
            }
        )
    return pd.DataFrame(
        rows, columns=list(ARTIFACT_COLUMNS["replenishment_suppliers"])
    )


def market_policy_frame(
    policy: Mapping[str, Mapping[str, Any]],
    currency_by_market: Mapping[str, str],
) -> pd.DataFrame:
    """The market-scoped ceilings, resolved from the policy contract.

    Published because the read model cannot open a policy document: the weekly
    replenishment budget is declared per market and every governance figure
    measured against it had no denominator to divide by.
    """

    return pd.DataFrame(
        [
            {
                "market_id": market,
                "weekly_replenishment_budget_minor": int(
                    resolved["weeklyReplenishmentBudgetMinor"]
                ),
                "currency_code": currency_by_market[market],
            }
            for market, resolved in sorted(policy.items())
        ]
    )


def _build_inbound_summary(inputs: InventoryInputs) -> pd.DataFrame:
    """Pass the loaded inbound facts through at the node grain.

    Counts only, no rate. A late SHARE is a ratio the read model scopes per market
    and per echelon; freezing it here would publish one denominator and make every
    filtered view of it wrong.
    """

    rows = [
        {
            "market_id": str(record.market_id),
            "location_id": str(record.location_id),
            "open_shipments": int(record.open_shipments),
            "open_units": int(record.open_units),
            "received_shipments": int(record.received_shipments),
            "late_shipments": int(record.late_shipments),
        }
        for record in inputs.inbound_summary.itertuples(index=False)
    ]
    return pd.DataFrame(
        rows, columns=list(ARTIFACT_COLUMNS["inventory_inbound_summary"])
    )


def _build_warehouse_capacity(inputs: InventoryInputs) -> pd.DataFrame:
    """Pass the loaded ceiling through at the grain the screen reads it.

    Nothing is derived here on purpose. Utilisation is a ratio of the position
    holding to this ceiling, and computing it in the artifact would freeze a
    numerator that the read model scopes per market and location -- the rate
    belongs where the holding is aggregated, not beside the denominator.
    """

    rows = [
        {
            "market_id": str(record.market_id),
            "location_id": str(record.location_id),
            "capacity_units": int(record.capacity_units),
            "blocked_units": int(record.blocked_units),
            "fill_demand_units": int(record.fill_demand_units),
            "fill_served_units": int(record.fill_served_units),
            "fill_window_start": record.fill_window_start,
            "fill_window_end": record.fill_window_end,
            "snapshot_date": record.snapshot_date,
        }
        for record in inputs.warehouse_capacity.itertuples(index=False)
    ]
    return pd.DataFrame(
        rows, columns=list(ARTIFACT_COLUMNS["inventory_warehouse_capacity"])
    )


def _label(slug: str) -> str:
    """A hyphenated source slug as a readable label.

    "apparel-footwear" -> "Apparel - Footwear". The words are the source's own;
    only the separator and the casing change, so nothing is renamed and no
    mapping table has to be maintained alongside the taxonomy.
    """

    return " - ".join(part.capitalize() for part in slug.split("-") if part)


def _node_demand(
    emitted: pd.DataFrame,
    trailing: Mapping[tuple[str, str, str], Decimal],
) -> dict[tuple[str, str, str], Decimal]:
    """Trailing daily demand for EVERY node, not just the ones that sell.

    `trailing` is built from `sales`, which keys on store, so a DC has no row --
    correctly, because a DC has no sales of its own. But "no sales" is not "no
    demand": a DC's demand is the demand of the stores it supplies, and treating
    the absence as zero told the health engine that 2,190 DC cells were dead
    stock with no movement. That put 99.8 per cent of inventory VALUE into
    "Inventory at Risk", which is not a finding, it is a missing join.

    Derived per market x SKU across store nodes and attributed to every non-store
    node in the market. Coarser than the lane-resolved derivation `load_forecast`
    uses for DC forecasting, and deliberately so: this drives health
    classification and a days-of-supply display, not an order quantity, so it
    must not silently inherit a replenishment decision.
    """

    store_nodes = {
        (str(row["market_id"]), str(row["location_id"]))
        for row in (record._asdict() for record in emitted.itertuples(index=False))
        if str(row.get("location_kind")) == "store"
    }
    by_market_sku: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for (market, location, sku), rate in trailing.items():
        if (market, location) in store_nodes:
            by_market_sku[(market, sku)] += rate

    effective = dict(trailing)
    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        sku = str(row["sku_id"])
        key = (market, location, sku)
        if key in effective or str(row.get("location_kind")) == "store":
            continue
        effective[key] = by_market_sku.get((market, sku), Decimal(0))
    return effective


def _build_sku_dimension(
    emitted: pd.DataFrame,
    *,
    unit_costs: Mapping[tuple[str, str, str], tuple[int | None, str | None]],
    trailing: Mapping[tuple[str, str, str], Decimal],
    currency_by_market: Mapping[str, str],
) -> pd.DataFrame:
    """The dimension every screen needed and none of them had.

    Two facts live only in the loader and never reached a projection: a SKU's
    CATEGORY, and its accepted unit COST. Without the first, "Inventory Risk by
    Category" had nothing to group by and shipped location ids under a Category
    header. Without the second, every column the reference denominates in rupees
    -- Inventory Value, Order Value, Financial Exposure, Transfer Value -- could
    only render a unit count.

    Published as one dimension rather than as columns on eight fact tables: the
    grain is the same (market x location x SKU), the read model joins it where it
    needs it, and a fact table's frozen column contract stays frozen.

    `unit_cost_minor` is null where no accepted cost exists. That is the same
    ABC_UNIT_COST_UNAVAILABLE population the safety-stock engine already
    withholds on, and a borrowed cost from another node is never substituted.
    """

    # A DC has no sales of its own, so `trailing` carries no row for one -- and
    # days of supply at a warehouse would be permanently undefined, which is what
    # the Location-Level card showed on every DC row. A DC's demand is the demand
    # of the stores it supplies, which is the same derivation `load_forecast`
    # already uses for DC forecasting: rank-1 supplied stores, additively.
    #
    # Summed per market x SKU across store nodes and attributed to every non-store
    # node in that market. Coarser than the lane-resolved version the forecast
    # uses, and deliberately so: this figure drives a days-of-supply DISPLAY, not
    # a replenishment quantity, and a display must not silently inherit an
    # ordering decision.
    rows: list[dict[str, Any]] = []
    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        sku = str(row["sku_id"])
        cost, method = unit_costs.get((market, location, sku), (None, None))
        rows.append(
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "category": str(row["category"]),
                # "apparel-footwear" is a slug, not a label. The reference names
                # its categories "Footwear" and "Apparel"; this is the same
                # vocabulary the source uses, made readable rather than renamed.
                "category_label": _label(str(row["category"])),
                "product_name": str(row.get("product_name") or row["sku_id"]),
                "location_name": str(row.get("location_name") or row["location_id"]),
                "location_kind": str(row.get("location_kind") or ""),
                "unit_cost_minor": cost,
                "cost_method": method,
                "currency_code": currency_by_market.get(market),
                # Trailing average DAILY demand for the cell -- the grain the loader
                # produces. Published because
                # four different screens are arithmetic on it and none could do
                # the arithmetic: days of supply is on-hand over daily demand,
                # sell-through is demand over demand-plus-stock, and stock turn
                # is 365 over days of supply. The build has computed this for the
                # replenishment engine all along and dropped it.
                "trailing_daily_units": trailing.get(
                    (market, location, sku), Decimal(0)
                ),
            }
        )
    frame = pd.DataFrame(rows, columns=list(ARTIFACT_COLUMNS["inventory_sku_dimension"]))
    # Nullable integer, not float. A column of Python ints with one None becomes
    # float64, and 58410 then serialises as "58410.0", which PostgreSQL rejects
    # for a bigint at COPY time rather than at publish time.
    frame["unit_cost_minor"] = frame["unit_cost_minor"].astype("Int64")
    frame["trailing_daily_units"] = frame["trailing_daily_units"].astype(float)
    return frame.drop_duplicates(subset=["market_id", "location_id", "sku_id"])


def build_artifacts(
    inputs: InventoryInputs,
    *,
    replay_metrics: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build all thirteen artifacts, in the frozen column order.

    `replay_metrics` arrives already scored: acceptance is decided by the replay
    against an incumbent, and rebuilding it here from the same rows the candidate
    produced would make the candidate its own baseline.
    """

    emitted = _emitted_positions(inputs)
    trailing = _node_demand(emitted, _index_trailing(inputs))
    forecasts = _index_forecast(inputs)
    unit_costs = _index_unit_costs(inputs)

    # Cost-weighted ABC (P4-D7), ranked PER MARKET because the engine refuses
    # cross-market ranking: nominal money across INR and USD would order SKUs by
    # exchange rate rather than by value.
    abc_classes: dict[tuple[str, str], Mapping[str, Any]] = {}
    for market in sorted(inputs.policy):
        market_rows = [
            {
                "market_id": market,
                "sku_id": str(row["sku_id"]),
                "location_id": str(row["location_id"]),
                "trailing_avg_weekly_units": trailing.get(
                    (market, str(row["location_id"]), str(row["sku_id"])), Decimal(0)
                )
                * DAYS_PER_WEEK,
                "accepted_unit_cost_minor": unit_costs.get(
                    (market, str(row["location_id"]), str(row["sku_id"])),
                    (None, None),
                )[0],
            }
            for row in (record._asdict() for record in emitted.itertuples(index=False))
            if str(row["market_id"]) == market
        ]
        if market_rows:
            abc_classes.update(classify_abc(market_rows))

    # One resolution per cell, shared by every artifact that needs the window.
    supply = _resolve_supply(emitted, inputs=inputs)

    positions = _build_positions(emitted)
    health = _build_stock_health(emitted, trailing=trailing, policy=inputs.policy)
    # Demand-at-risk consumes the same governed channel allocation published in
    # the bundle, so build it once and pass the exact frame into both outputs.
    allocations = _build_allocations(emitted, inputs=inputs)
    risk, risk_exceptions = _build_demand_at_risk(
        emitted,
        forecasts=forecasts,
        allocations=allocations,
        supply=supply,
        inputs=inputs,
        ledgers=inputs.ledgers,
    )
    ageing = _build_ageing(
        emitted,
        batches=inputs.batches,
        health=health,
        policy=inputs.policy,
        as_of=inputs.as_of,
    )
    expiry = _build_expiry_waste(
        emitted,
        batches=inputs.batches,
        waste=inputs.waste,
        prior_waste=inputs.prior_waste,
        unit_costs=unit_costs,
        policy=inputs.policy,
        currency_by_market=inputs.currency_by_market,
        as_of=inputs.as_of,
    )
    valuation = _build_valuation(
        emitted,
        unit_costs=unit_costs,
        wms_variance=inputs.wms_variance,
        currency_by_market=inputs.currency_by_market,
    )
    recommendations, safety_stock, plan_exceptions = _replenishment_plan(
        emitted,
        forecasts=forecasts,
        trailing=trailing,
        inputs=inputs,
        abc_classes=abc_classes,
        supply=supply,
    )
    transfers = _build_transfers(
        emitted,
        inputs=inputs,
        health=health,
        trailing=trailing,
        unit_costs=unit_costs,
    )
    suppliers = _build_suppliers(inputs)

    exception_frame = pd.DataFrame(
        plan_exceptions + risk_exceptions,
        columns=list(ARTIFACT_COLUMNS["replenishment_exceptions"]),
    )
    # One row per cell and class. The same cell can be gated by the interval AND
    # unresolved by the network, and both belong; two rows of one class over one
    # cell is a double count on the exceptions screen.
    if not exception_frame.empty:
        exception_frame = exception_frame.drop_duplicates(
            ["market_id", "location_id", "sku_id", "channel_id", "exception_class"]
        ).reset_index(drop=True)

    artifacts = {
        "inventory_sku_dimension": _build_sku_dimension(
            emitted,
            unit_costs=unit_costs,
            trailing=trailing,
            currency_by_market=inputs.currency_by_market,
        ),
        "inventory_positions": positions,
        "inventory_stock_health": health,
        "inventory_demand_at_risk": risk,
        "inventory_ageing": ageing,
        "inventory_expiry_waste": expiry,
        "inventory_valuation": valuation,
        "replenishment_recommendations": recommendations,
        "replenishment_safety_stock": safety_stock,
        "replenishment_transfers": transfers,
        "replenishment_allocations": allocations,
        "replenishment_suppliers": suppliers,
        "replenishment_exceptions": exception_frame,
        "inventory_replay_metrics": replay_metrics,
        "inventory_warehouse_capacity": _build_warehouse_capacity(inputs),
        "inventory_inbound_summary": _build_inbound_summary(inputs),
        "inventory_market_policy": market_policy_frame(
            inputs.policy, inputs.currency_by_market
        ),
    }
    for name, frame in artifacts.items():
        artifacts[name] = frame[list(ARTIFACT_COLUMNS[name])].reset_index(drop=True)
    return artifacts


def coverage_summary(artifacts: Mapping[str, pd.DataFrame]) -> dict[str, Any]:
    """What the run assessed and what it withheld, as publishable counts.

    Every gated artifact reports both, so "how much of this bundle is actually
    assessed" is answerable from the bundle instead of by re-deriving it.
    """

    summary: dict[str, Any] = {}
    for name in (
        "inventory_demand_at_risk",
        "replenishment_safety_stock",
        "replenishment_recommendations",
    ):
        frame = artifacts[name]
        available = int(frame["interval_available"].astype(bool).sum())
        summary[name] = {
            "rows": int(len(frame)),
            "intervalAvailableRows": available,
            "intervalWithheldRows": int(len(frame)) - available,
        }
    health = artifacts["inventory_stock_health"]
    summary["inventory_stock_health"] = {
        "rows": int(len(health)),
        "byClass": {
            str(key): int(value)
            for key, value in health["health_class"].value_counts().items()
        },
        "coverUnavailableRows": int(health["cover_days"].isna().sum()),
    }
    positions = artifacts["inventory_positions"]
    summary["inventory_positions"] = {
        "rows": int(len(positions)),
        "residualOnlyRows": int(positions["residual_only"].astype(bool).sum()),
    }
    for name in ("replenishment_transfers", "replenishment_exceptions"):
        summary[name] = {"rows": int(len(artifacts[name]))}
    return summary


__all__ = [
    "COLD_START_REASON",
    "COST_UNAVAILABLE",
    "UNRESOLVED_ROUTE_REASON",
    "CellSupply",
    "InventoryBuildError",
    "InventoryInputs",
    "build_artifacts",
    "coverage_summary",
]
