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
from datetime import date
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

#: The two governed reasons Phase 4 may cite for an absent interval-derived
#: value. They are different findings: one says "wait for calibration", the other
#: says "declare a route", and an operator shown the wrong one waits forever.
COLD_START_REASON: Final[str] = "COLD_START_INTERVAL_UNCALIBRATED"
UNRESOLVED_ROUTE_REASON: Final[str] = "SUPPLY_ROUTE_UNRESOLVED"
assert {COLD_START_REASON, UNRESOLVED_ROUTE_REASON} <= GOVERNED_REASONS

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
    #: market_id, location_id, location_kind, sku_id, dept_id, category,
    #: on_hand_units, committed_units, reserved_units, damaged_units,
    #: on_order_units, in_transit_units, assortment_active
    positions: pd.DataFrame
    #: market_id, location_id, sku_id, trailing_avg_daily_units
    trailing_demand: pd.DataFrame
    #: market_id, location_id, sku_id, horizon_week, yhat_p50, yhat_p90,
    #: interval_available
    forecast: pd.DataFrame
    #: market_id, location_id, sku_id, batch_id, received_on, expires_on,
    #: on_hand_units, unit_cost_minor
    batches: pd.DataFrame
    #: market_id, location_id, sku_id, waste_units, expired_units
    waste: pd.DataFrame
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
    #: market_id, location_id, channel_id, sku_id, requested_units
    channel_demand: pd.DataFrame
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
    if value is None or value is pd.NA:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
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
            "yhat_p50": float(row.yhat_p50),
            "yhat_p90": None if pd.isna(row.yhat_p90) else float(row.yhat_p90),
            "interval_available": bool(row.interval_available),
        }
    return dict(nested)


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
    unit_costs: Mapping[tuple[str, str, str], tuple[int | None, str | None]],
    supply: Mapping[tuple[str, str, str], "CellSupply"],
    currency_by_market: Mapping[str, str],
    ledgers: dict[str, PartialConsumerLedger],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Risk over each cell's protection window, and the exceptions it produced.

    The window comes from the SAME resolved supply as the replenishment plan. It
    used to come from the market default, which meant a node with a 40-day
    supplier had its risk assessed over 14 days -- understating the exposure, and
    worse, publishing an assessed risk row beside a withheld safety-stock row for
    one cell. Two artifacts disagreeing about a cell's horizon is not a rounding
    difference; one of them is wrong and a reader cannot tell which.

    `demand_at_risk` is a per-horizon partial consumer that owns its own ledger,
    so the horizons in the window are handed to it whole and it decides which are
    assessable. Summing only what it returned -- rather than iterating horizons
    here and coercing the withheld ones -- keeps an unassessed horizon out of the
    total instead of in it as a zero.
    """

    per_market_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cells: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    unresolved: list[dict[str, Any]] = []
    for record in emitted.itertuples(index=False):
        row = record._asdict()
        market = str(row["market_id"])
        location = str(row["location_id"])
        sku = str(row["sku_id"])
        key = (market, location, sku)
        cell_supply = supply[key]
        if not cell_supply.resolved:
            # No declared route means no protection period, so there is no window
            # over which to assess risk at all. Withheld with the route's own
            # reason rather than assessed over a window nobody derived.
            unresolved.append(
                {
                    "market_id": market,
                    "location_id": location,
                    "sku_id": sku,
                    "reason": str(cell_supply.resolution_reason),
                }
            )
            continue
        weeks = cell_supply.horizon_weeks
        assert weeks is not None
        horizons = forecasts.get(key, {})
        cost, _ = unit_costs.get(key, (None, None))
        cells[market].append((market, location, sku, weeks))
        for horizon in range(1, weeks + 1):
            cell = horizons.get(horizon)
            per_market_rows[market].append(
                {
                    "sku_id": sku,
                    "store_id": location,
                    "channel_id": NODE_CHANNEL,
                    "horizon_week": horizon,
                    # A node with no forecast at all is withheld for the same
                    # governed reason: nothing measured its interval either.
                    "interval_available": bool(
                        cell and cell["interval_available"] and horizon <= weeks
                    ),
                    "yhat_p50": None if cell is None else cell["yhat_p50"],
                    "yhat_p90": None if cell is None else cell["yhat_p90"],
                    "atp_units": int(row["atp_units"]),
                    "unit_price_minor": cost,
                    "currency_code": (
                        None if cost is None else currency_by_market[market]
                    ),
                }
            )

    rows: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    for market in sorted(per_market_rows):
        assessment = demand_at_risk(
            per_market_rows[market], consumer=f"demand_at_risk:{market}"
        )
        assessed: dict[tuple[str, str], float] = defaultdict(float)
        assessed_value: dict[tuple[str, str], int | None] = {}
        for assessed_row in assessment["rows"]:
            pair = (str(assessed_row["store_id"]), str(assessed_row["sku_id"]))
            assessed[pair] += float(assessed_row["risk_units"])
            value = assessed_row["risk_value_minor"]
            if value is not None:
                assessed_value[pair] = (assessed_value.get(pair) or 0) + int(value)
        # Per-market ledger, retained so the run can publish what it withheld.
        ledgers[f"demand_at_risk:{market}"] = PartialConsumerLedger(
            consumer=f"demand_at_risk:{market}",
            skipped_rows=assessment["unassessed"]["rows"],
            skipped_demand_units=assessment["unassessed"]["demandUnits"],
        )
        for _, location, sku, weeks in cells[market]:
            pair = (location, sku)
            horizons = forecasts.get((market, location, sku), {})
            complete = _weekly(horizons, weeks=weeks, field_name="yhat_p90")
            if complete is None:
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
                        "reason_code": COLD_START_REASON,
                    }
                )
                exceptions.append(
                    {
                        "market_id": market,
                        "location_id": location,
                        "sku_id": sku,
                        "channel_id": NODE_CHANNEL,
                        "exception_class": "cold_start_interval_unavailable",
                        "severity": "info",
                        "reason_code": COLD_START_REASON,
                        "evidence": (
                            f"demand-at-risk needs horizons 1..{weeks}; the "
                            "cold-start interval is calibrated through 4"
                        ),
                    }
                )
                continue
            value = assessed_value.get(pair)
            rows.append(
                {
                    "market_id": market,
                    "location_id": location,
                    "sku_id": sku,
                    "channel_id": NODE_CHANNEL,
                    "risk_units": float(assessed.get(pair, 0.0)),
                    "risk_value_minor": value,
                    "currency_code": (
                        None if value is None else currency_by_market[market]
                    ),
                    "interval_available": True,
                    "reason_code": None,
                }
            )
    for cell in unresolved:
        rows.append(
            {
                "market_id": cell["market_id"],
                "location_id": cell["location_id"],
                "sku_id": cell["sku_id"],
                "channel_id": NODE_CHANNEL,
                "risk_units": None,
                "risk_value_minor": None,
                "currency_code": None,
                "interval_available": False,
                "reason_code": UNRESOLVED_ROUTE_REASON,
            }
        )
        exceptions.append(
            {
                "market_id": cell["market_id"],
                "location_id": cell["location_id"],
                "sku_id": cell["sku_id"],
                "channel_id": NODE_CHANNEL,
                "exception_class": "supply_route_unresolved",
                "severity": "warning",
                "reason_code": UNRESOLVED_ROUTE_REASON,
                "evidence": (
                    f"{cell['reason']}; with no declared route there is no "
                    "protection period to assess risk over"
                ),
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
        oldest[key] = max(oldest.get(key, age_days), age_days)
    rows: list[dict[str, Any]] = []
    for key, units in sorted(aggregated.items()):
        market, location, sku, bucket = key
        market_policy = policy[market]
        cover = cover_by_key.get((market, location, sku))
        action = ageing_action(
            on_hand_age_days=oldest[key],
            cover_days=_optional_decimal(cover),
            hold_cover_days=int(market_policy["holdCoverDays"]),
            markdown_cover_days=int(market_policy["markdownCoverDays"]),
            markdown_pct=_decimal(market_policy["markdownPct"]),
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
    for key in sorted((keys & set(grouped)) | (keys & set(waste_by_key))):
        market, location, sku = key
        exposure = expiry_exposure(
            grouped.get(key, []),
            as_of=as_of,
            window_days=int(policy[market]["expiryWindowDays"]),
        )
        waste_units, expired_units = waste_by_key.get(key, (0, 0))
        currency = exposure["currency_code"]
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
                    int(exposure["exposure_minor"]) if currency else None
                ),
                "currency_code": currency,
            }
        )
    frame = pd.DataFrame(rows, columns=list(ARTIFACT_COLUMNS["inventory_expiry_waste"]))
    if not frame.empty:
        frame["exposure_minor"] = frame["exposure_minor"].astype("Int64")
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
        centre: tuple[float, ...] | None = None
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
            if gate_reason is None:
                upper = _weekly(horizons, weeks=weeks, field_name="yhat_p90")
                centre = _weekly(horizons, weeks=weeks, field_name="yhat_p50")
                if upper is None or centre is None:
                    gate_reason = COLD_START_REASON
                else:
                    spreads = tuple(
                        max(0.0, high - mid) for high, mid in zip(upper, centre)
                    )
            if gate_reason is None and service_level is None:
                # No ABC class means no service level, and inventing one would set
                # a target nobody chose.
                gate_reason = COLD_START_REASON
                evidence = (
                    f"{abc.get('reason_code') or 'ABC_CLASS_UNAVAILABLE'}; no "
                    "service level applies without a class"
                )
            if gate_reason == COLD_START_REASON and not evidence:
                evidence = (
                    f"protection period {protection}d needs horizon {weeks}; the "
                    "cold-start interval is calibrated to 4"
                )

        if gate_reason is not None or spreads is None or centre is None:
            governed = gate_reason or COLD_START_REASON
            safety_rows.append(
                {
                    "market_id": market,
                    "location_id": location,
                    "sku_id": sku,
                    "abc_class": abc_class,
                    "service_level": None,
                    "safety_stock_units": None,
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
        stock = safety_stock_units(
            weekly_spreads=spreads,
            protection_days=protection,
            service_level=service_level,
        )
        point = reorder_point(
            weekly_p50=centre, protection_days=protection, safety_stock=stock
        )
        level = order_up_to_level(
            reorder_point_units=point,
            weekly_p50=centre,
            review_period_days=int(market_policy["reviewPeriodDays"]),
        )
        position_units = int(row["position_units"])
        daily = float(trailing.get(key, Decimal(0)))
        recommended: int | None
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
                exceptions.append(
                    {
                        "market_id": market,
                        "location_id": location,
                        "sku_id": sku,
                        "channel_id": None,
                        "exception_class": "order_constraint_conflict",
                        "severity": "warning",
                        "reason_code": None,
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
                "safety_stock_units": float(stock),
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
                # The interval WAS available; a null recommendation here means the
                # constraint solver refused, and the exception above says why.
                "interval_available": True,
                "reason_code": None,
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
    accepted = recommend_transfers(
        candidates,
        source_atp=atp_by_key,
        source_residual_cover_units=residual_cover,
        target_headroom_units=headroom,
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


def _build_suppliers(inputs: InventoryInputs) -> pd.DataFrame:
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
            }
        )
    return pd.DataFrame(
        rows, columns=list(ARTIFACT_COLUMNS["replenishment_suppliers"])
    )


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
    trailing = _index_trailing(inputs)
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
    risk, risk_exceptions = _build_demand_at_risk(
        emitted,
        forecasts=forecasts,
        unit_costs=unit_costs,
        supply=supply,
        currency_by_market=inputs.currency_by_market,
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
    allocations = _build_allocations(emitted, inputs=inputs)
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
