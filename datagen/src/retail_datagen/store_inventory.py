"""Store-grain stock state, replenished from a DC over declared service lanes.

Source contract v13. The accepted pin has `stock_snapshots` rows at four DC/MFC
nodes and **zero rows at all four stores**, so store position, days of supply,
ageing, store waste and store-level transfer opportunity have no source at all.
Multi-echelon replenishment is not a partial capability without this; it is
absent.

What this module adds, and what it deliberately does not touch:

* Stores hold real state -- on hand, committed, damaged, in transit -- driven by
  arrivals, store-channel sales and expiry. A store can run short, and a shortage
  is recorded rather than smoothed away.
* The DC flow is unchanged. Store-channel demand already depletes DC stock through
  `_allocate_inventory`, and that continues to be the DC withdrawal the canonical
  `sales_fulfillments` records. When a store cannot cover demand from its own
  shelf, the sale is still served from the DC -- which is what a retailer actually
  does, and which the fulfillment row already states truthfully through its
  `supply_location_id`. The store's inability to cover is published as a stockout
  event instead of being hidden by it.

The alternative -- letting store stock gate the sale -- would rewrite every
existing order, fulfillment and DC control total for a model whose store layer has
no independent evidence to validate against yet. That is a rebaseline with no
oracle, so the store echelon is additive and its shortfalls are disclosed.

**Emission is active-or-residual, never Cartesian.** A snapshot row exists for a
SKU x store cell when the cell is actively assorted at that date, or when it still
carries non-zero residual state. A de-assorted cell keeps its stock until the
stock is worked off, which is what makes dead stock possible: the current pin shows
524 SKUs holding DC stock while outside active assortment, and a store model that
emitted only active cells would make that shape structurally impossible. Inactive
zero-state cells are omitted -- a fixed 1,440 x 4 product is forbidden.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Iterator
from zoneinfo import ZoneInfo

from .identity import stable_integer


@dataclass
class _Cell:
    """One SKU x store stock cell."""

    on_hand: int = 0
    committed: int = 0
    damaged: int = 0
    in_transit: int = 0
    #: Receipt day of the oldest unsold unit, for ageing and expiry.
    oldest_receipt_day: date | None = None
    #: Set when the cell leaves active assortment while still holding stock.
    residual_since: date | None = None

    def residual_state(self) -> int:
        return self.on_hand + self.committed + self.damaged + self.in_transit


@dataclass
class StoreEchelon:
    """Weekly store stock state and its replenishment over declared lanes."""

    config: dict[str, Any]
    markets: dict[str, dict[str, Any]]
    stores: dict[str, dict[str, Any]]
    warehouses: dict[str, dict[str, Any]]
    store_variants: dict[str, list[dict[str, Any]]]
    start: date
    end: date
    master_seed: str

    cells: dict[tuple[str, str], _Cell] = field(default_factory=dict)
    arrivals: dict[date, list[dict[str, Any]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    #: Trailing store-channel demand, used to size a review-cycle order. Sized from
    #: what the store OBSERVED, never from latent truth: a policy fitted on hidden
    #: demand is not a policy a retailer could run.
    observed_demand: dict[tuple[str, str], dict[date, int]] = field(
        default_factory=lambda: defaultdict(dict)
    )

    def __post_init__(self) -> None:
        policy = self.config["operations"].get("storeInventory") or {}
        self.enabled = bool(
            self.config["operations"]["features"].get("storeInventory")
        )
        self.snapshot_cadence = int(policy.get("snapshotCadenceDays", 7))
        self.review_cycle = int(policy.get("reviewCycleDays", 7))
        self.target_cover_days = int(policy.get("targetDaysOfCover", 14))
        self.safety_stock = int(policy.get("safetyStockUnits", 3))
        self.pack_size = max(1, int(policy.get("replenishmentPackSize", 6)))
        self.opening_cover_days = int(policy.get("openingDaysOfCover", 10))
        self.residual_workoff_weeks = int(policy.get("residualWorkoffWeeks", 26))
        self.primary_transit = int(policy.get("primaryLaneTransitDays", 1))
        self.spill_transit = int(policy.get("spillLaneTransitDays", 2))
        self._assortment_window: dict[tuple[str, str], tuple[date, date | None]] = {}
        for store_id, variants in self.store_variants.items():
            for variant in variants:
                launch = date.fromisoformat(variant["_launchDate"])
                discontinue = (
                    date.fromisoformat(variant["_discontinueDate"])
                    if variant["_discontinueDate"]
                    else None
                )
                self._assortment_window[(store_id, variant["sku"])] = (
                    launch,
                    discontinue,
                )
        self._shelf_life: dict[str, int] = {}
        for variants in self.store_variants.values():
            for variant in variants:
                shelf_life = variant.get("_shelfLifeDays")
                if shelf_life:
                    self._shelf_life[variant["sku"]] = int(shelf_life)

    # -- lanes ---------------------------------------------------------------

    def lane_rows(self) -> list[dict[str, Any]]:
        """Publish the declared supply relationship as typed, effective-dated rows.

        This does NOT invent a lane model. `stores[].warehousePriority` already
        declares the relationship and already matches the observed fulfillment
        volume shares in the accepted pin -- 91.3/8.7 in Mumbai, 90.8/9.2 in
        Brooklyn, 100% in Manhattan. v13 publishes it as a governed fact instead of
        leaving it implicit in generator config, so a downstream resolver reads a
        declared lane rather than parsing an allocation priority string.
        """

        rows: list[dict[str, Any]] = []
        for store in self.stores.values():
            for rank, warehouse_id in enumerate(store["warehousePriority"], start=1):
                transit = (
                    self.primary_transit if rank == 1 else self.spill_transit
                )
                rows.append(
                    {
                        "laneKey": f"{store['storeId']}:{warehouse_id}:replenishment",
                        "marketKey": store["marketId"],
                        "laneType": "replenishment",
                        "demandLocationKey": store["storeId"],
                        # Null channel is the market-wide default for this store.
                        # An exact channel row would win over it; none is declared
                        # here because replenishment is not channel-specific.
                        "channelKey": "",
                        "supplyLocationKey": warehouse_id,
                        "priorityRank": rank,
                        "transitDays": transit,
                        "effectiveFrom": self.start.isoformat(),
                        "effectiveTo": "",
                        "observedAt": _iso_at(
                            self.start, self.markets[store["marketId"]]["timezone"]
                        ),
                    }
                )
        rows.sort(key=lambda row: (row["laneKey"],))
        return rows

    def _lane_for(self, store_id: str) -> tuple[str, int]:
        """Rank-1 supplying node and its transit days."""

        priority = self.stores[store_id]["warehousePriority"]
        return priority[0], self.primary_transit

    # -- state ---------------------------------------------------------------

    def _cell(self, store_id: str, sku: str) -> _Cell:
        key = (store_id, sku)
        cell = self.cells.get(key)
        if cell is None:
            cell = _Cell()
            self.cells[key] = cell
        return cell

    def is_active(self, store_id: str, sku: str, day: date) -> bool:
        window = self._assortment_window.get((store_id, sku))
        if window is None:
            return False
        launch, discontinue = window
        if day < launch:
            return False
        return discontinue is None or day <= discontinue

    def seed_opening(self, opening_daily_rate: dict[tuple[str, str], Decimal]) -> None:
        """Seed opening stock for cells already active at the window boundary.

        A source extract normally opens with stock bought against demand observed
        BEFORE the requested window, so the opening balance is a merchandising
        bootstrap rather than a simulated receipt. After day one every movement is
        generated.
        """

        if not self.enabled:
            return
        for store in self.stores.values():
            store_id = store["storeId"]
            warehouse_id, _ = self._lane_for(store_id)
            for variant in self.store_variants[store_id]:
                sku = variant["sku"]
                if not self.is_active(store_id, sku, self.start):
                    continue
                daily = opening_daily_rate.get((warehouse_id, sku), Decimal("0"))
                planned = int(Decimal(self.opening_cover_days) * daily)
                jitter = stable_integer(
                    self.master_seed,
                    "store-opening-stock",
                    store_id,
                    sku,
                    modulo=self.pack_size,
                )
                opening = max(0, planned + jitter)
                if opening == 0:
                    continue
                cell = self._cell(store_id, sku)
                cell.on_hand = opening
                cell.oldest_receipt_day = self.start

    # -- daily flow ----------------------------------------------------------

    def receive(self, day: date) -> Iterator[dict[str, Any]]:
        """Apply arrivals effective today and yield the received status events."""

        if not self.enabled:
            return
        for arrival in self.arrivals.pop(day, []):
            cell = self._cell(arrival["storeKey"], arrival["sku"])
            cell.in_transit = max(0, cell.in_transit - arrival["quantity"])
            cell.on_hand += arrival["quantity"]
            if cell.oldest_receipt_day is None:
                cell.oldest_receipt_day = day
            yield {**arrival, "status": "received", "statusEffectiveAt": _iso_at(
                day, self.markets[arrival["marketKey"]]["timezone"]
            )}

    def sell(
        self,
        day: date,
        store_id: str,
        sku: str,
        units: int,
    ) -> tuple[int, int]:
        """Consume store stock for store-channel demand.

        Returns `(served_from_store, shortfall)`. The shortfall is NOT a lost sale:
        the DC allocation already served it, so this is the store's inability to
        cover from its own shelf, which is exactly the stockout signal a
        replenishment policy has to be scored against.
        """

        if not self.enabled or units <= 0:
            return 0, 0
        self.observed_demand[(store_id, sku)][day] = (
            self.observed_demand[(store_id, sku)].get(day, 0) + units
        )
        cell = self._cell(store_id, sku)
        available = max(0, cell.on_hand - cell.damaged)
        served = min(available, units)
        cell.on_hand -= served
        if cell.on_hand == 0:
            cell.oldest_receipt_day = None
        return served, units - served

    def expire(self, day: date) -> Iterator[dict[str, Any]]:
        """Waste perishable store stock whose shelf life has elapsed.

        Only for SKUs whose product rules declare a shelf life. A non-perishable
        cell has no expiry, and inventing one would fabricate waste evidence.
        """

        if not self.enabled:
            return
        for (store_id, sku), cell in sorted(self.cells.items()):
            shelf_life = self._shelf_life.get(sku)
            if (
                shelf_life is None
                or cell.on_hand <= 0
                or cell.oldest_receipt_day is None
            ):
                continue
            if (day - cell.oldest_receipt_day).days < shelf_life:
                continue
            # Only the aged portion is wasted, not the whole cell: a store that
            # discarded its entire shelf on one day would be an artifact of the
            # model rather than of shelf life.
            wasted = max(1, cell.on_hand // 4)
            wasted = min(wasted, cell.on_hand)
            cell.on_hand -= wasted
            cell.oldest_receipt_day = None if cell.on_hand == 0 else day
            yield {
                "eventKey": f"store-waste:{store_id}:{sku}:{day.isoformat()}",
                "marketKey": self.stores[store_id]["marketId"],
                "storeKey": store_id,
                "sku": sku,
                "eventDate": day.isoformat(),
                "units": wasted,
                "reasonCode": "expiry",
                "observedAt": _iso_at(
                    day, self.markets[self.stores[store_id]["marketId"]]["timezone"]
                ),
            }

    def review(self, day: date) -> Iterator[dict[str, Any]]:
        """Place replenishment requests on the review cycle over the rank-1 lane.

        Demand is sized from the trailing observed window, so the order a store
        places is one a planner could have placed with the same information.
        """

        if not self.enabled:
            return
        if (day - self.start).days % self.review_cycle != 0:
            return
        window_start = day - timedelta(days=self.review_cycle * 2)
        for store in sorted(self.stores.values(), key=lambda row: row["storeId"]):
            store_id = store["storeId"]
            warehouse_id, transit = self._lane_for(store_id)
            market_id = store["marketId"]
            for variant in self.store_variants[store_id]:
                sku = variant["sku"]
                if not self.is_active(store_id, sku, day):
                    continue
                observed = self.observed_demand.get((store_id, sku), {})
                trailing = sum(
                    units
                    for observed_day, units in observed.items()
                    if window_start <= observed_day <= day
                )
                if trailing <= 0:
                    # No observed demand in the trailing window, so no order.
                    #
                    # Safety stock protects against variability in demand that
                    # exists; adding it to a cell with no demand at all would order
                    # a pack into a SKU nobody buys, which manufactures the dead
                    # stock the ageing screens are supposed to be reporting on.
                    # `inventory-policy-v2.yaml` freezes this as
                    # `reorder.zeroDemandBehavior: no_order`.
                    continue
                span_days = max(1, min(self.review_cycle * 2, (day - self.start).days + 1))
                daily_rate = Decimal(trailing) / Decimal(span_days)
                target = int(
                    daily_rate * Decimal(self.target_cover_days)
                ) + self.safety_stock
                cell = self._cell(store_id, sku)
                position = cell.on_hand + cell.in_transit - cell.damaged
                if position >= target:
                    continue
                shortfall = target - position
                # Round UP to a pack multiple. Rounding down would silently order
                # less than the policy asked for.
                quantity = -(-shortfall // self.pack_size) * self.pack_size
                if quantity <= 0:
                    continue
                cell.in_transit += quantity
                receipt_day = day + timedelta(days=transit)
                event = {
                    "transferKey": (
                        f"{warehouse_id}:{store_id}:{sku}:{day.isoformat()}"
                    ),
                    "marketKey": market_id,
                    "sku": sku,
                    "fromLocationKey": warehouse_id,
                    "toLocationKey": store_id,
                    "storeKey": store_id,
                    "quantity": quantity,
                    "orderDate": day.isoformat(),
                    "expectedReceiptDate": receipt_day.isoformat(),
                    "unitCostMinor": int(variant.get("_baseCost", 0) or 0),
                    "currencyCode": self.markets[market_id]["currencyCode"],
                    "observedAt": _iso_at(day, self.markets[market_id]["timezone"]),
                }
                if receipt_day <= self.end:
                    self.arrivals[receipt_day].append(event)
                yield {
                    **event,
                    "status": "dispatched",
                    "statusEffectiveAt": _iso_at(
                        day, self.markets[market_id]["timezone"]
                    ),
                }

    # -- emission ------------------------------------------------------------

    def snapshot(self, day: date) -> Iterator[dict[str, Any]]:
        """Emit store snapshot rows under the active-or-residual rule.

        A cell qualifies when it is actively assorted at `day`, or when it still
        carries non-zero residual state after leaving assortment. Inactive
        zero-state cells are omitted: a fixed SKU x store product would assert that
        every store stocks every SKU, and would make dead stock impossible by
        construction.
        """

        if not self.enabled:
            return
        if (day - self.start).days % self.snapshot_cadence != 0 and day != self.end:
            return
        workoff_cutoff = timedelta(weeks=self.residual_workoff_weeks)
        for (store_id, sku), cell in sorted(self.cells.items()):
            active = self.is_active(store_id, sku, day)
            residual = cell.residual_state()
            if not active and residual == 0:
                # Nothing here and nothing listed: the cell does not exist.
                continue
            if not active:
                if cell.residual_since is None:
                    cell.residual_since = day
                elif day - cell.residual_since > workoff_cutoff:
                    # Held far past its work-off window. Kept visible rather than
                    # dropped, because vanishing stock is not a disposal: the
                    # ageing screen exists to show exactly this.
                    pass
            else:
                cell.residual_since = None
            market_id = self.stores[store_id]["marketId"]
            available = max(0, cell.on_hand - cell.committed - cell.damaged)
            yield {
                "marketKey": market_id,
                "storeKey": store_id,
                "locationCode": self.stores[store_id][
                    "businessCentralLocationCode"
                ],
                "sku": sku,
                "snapshotDate": day.isoformat(),
                "observedAt": _iso_at(day, self.markets[market_id]["timezone"]),
                "onHand": cell.on_hand,
                "available": available,
                "committed": cell.committed,
                "damaged": cell.damaged,
                "inTransit": cell.in_transit,
                "assortmentActive": "true" if active else "false",
                # The reason a de-assorted cell is still here. Without it a reader
                # cannot tell retained residual stock from a stale row.
                "residualOnly": "false" if active else "true",
                "oldestReceiptDate": (
                    cell.oldest_receipt_day.isoformat()
                    if cell.oldest_receipt_day
                    else ""
                ),
            }

    def coverage_summary(self) -> dict[str, int]:
        """Control totals for the store echelon, for Gate-B style reconciliation."""

        active_cells = sum(
            1
            for store_id, sku in self.cells
            if self.is_active(store_id, sku, self.end)
        )
        residual_cells = sum(
            1
            for (store_id, sku), cell in self.cells.items()
            if not self.is_active(store_id, sku, self.end)
            and cell.residual_state() > 0
        )
        return {
            "cells": len(self.cells),
            "activeCellsAtEnd": active_cells,
            "residualCellsAtEnd": residual_cells,
            "storesWithStock": len(
                {store_id for (store_id, _), cell in self.cells.items() if cell.on_hand}
            ),
        }


def _iso_at(day: date, timezone: str) -> str:
    """Store observations are timed at local end of day, like the DC snapshots.

    23:00 market-local, matching `simulation._iso_at`, because the replay clock's
    opening state is derived from the preceding Thursday 23:00 local snapshot. A
    store row timed differently from a DC row would not bridge to the same Monday.
    """

    return datetime.combine(
        day, time(hour=23), tzinfo=ZoneInfo(timezone)
    ).isoformat()


__all__ = ["StoreEchelon"]
