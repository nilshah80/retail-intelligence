"""Store-grain stock, and the active-or-residual emission rule.

Source contract v13. The accepted pin has zero `stock_snapshots` rows at all four
stores, so every store-grain screen has no source. These tests pin the two things
that make the store echelon trustworthy rather than merely present:

* Emission is **active-or-residual**. A fixed SKU x store product would assert that
  every store stocks every SKU and would make dead stock impossible by
  construction -- yet the current pin already shows 524 SKUs holding DC stock while
  outside active assortment, so a store model that cannot reproduce that shape is
  wrong about the thing it exists to describe.
* Replenishment is sized from **observed** demand. A policy fitted on latent truth
  is not a policy a planner could have run, and scoring it would flatter the
  engine rather than test it.
"""

from __future__ import annotations

import sys
import unittest
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from retail_datagen.store_inventory import StoreEchelon  # noqa: E402

START = date(2026, 1, 5)  # a Monday
END = date(2026, 6, 29)

MARKETS = {
    "india-west": {"timezone": "Asia/Kolkata", "currencyCode": "INR"},
}
STORES = {
    "bandra": {
        "storeId": "bandra",
        "marketId": "india-west",
        "businessCentralLocationCode": "MUM-BAN",
        "warehousePriority": ["mumbai-dc", "pune-overflow"],
    },
}
WAREHOUSES = {
    "mumbai-dc": {"warehouseId": "mumbai-dc", "marketId": "india-west"},
    "pune-overflow": {"warehouseId": "pune-overflow", "marketId": "india-west"},
}


def _variant(
    sku: str,
    *,
    launch: date = START,
    discontinue: date | None = None,
    shelf_life: int | None = None,
) -> dict:
    return {
        "sku": sku,
        "_launchDate": launch.isoformat(),
        "_discontinueDate": discontinue.isoformat() if discontinue else "",
        "_shelfLifeDays": shelf_life,
        "_baseCost": 4500,
    }


def _echelon(variants: list[dict], *, enabled: bool = True) -> StoreEchelon:
    config = {
        "operations": {
            "features": {"storeInventory": enabled},
            "storeInventory": {
                "snapshotCadenceDays": 7,
                "reviewCycleDays": 7,
                "targetDaysOfCover": 14,
                "safetyStockUnits": 3,
                "replenishmentPackSize": 6,
                "openingDaysOfCover": 10,
                "residualWorkoffWeeks": 26,
                "primaryLaneTransitDays": 1,
                "spillLaneTransitDays": 2,
            },
        }
    }
    return StoreEchelon(
        config=config,
        markets=MARKETS,
        stores=STORES,
        warehouses=WAREHOUSES,
        store_variants={"bandra": variants},
        start=START,
        end=END,
        master_seed="seed-1",
    )


class LaneTests(unittest.TestCase):
    def test_lanes_publish_the_declared_priority_rather_than_inventing_one(self) -> None:
        """`warehousePriority` already declares the relationship; v13 publishes it."""

        rows = _echelon([_variant("sku-1")]).lane_rows()
        self.assertEqual(len(rows), 2)
        by_rank = {row["priorityRank"]: row for row in rows}
        self.assertEqual(by_rank[1]["supplyLocationKey"], "mumbai-dc")
        self.assertEqual(by_rank[2]["supplyLocationKey"], "pune-overflow")
        self.assertTrue(all(row["laneType"] == "replenishment" for row in rows))
        # A null channel is the store-wide default, not a wildcard match.
        self.assertTrue(all(row["channelKey"] == "" for row in rows))

    def test_the_spill_lane_never_arrives_sooner_than_the_primary(self) -> None:
        """A faster spill lane would invert the priority the contract declares."""

        rows = {row["priorityRank"]: row for row in _echelon([_variant("s")]).lane_rows()}
        self.assertLessEqual(rows[1]["transitDays"], rows[2]["transitDays"])

    def test_ranks_are_unique_and_contiguous_from_one(self) -> None:
        ranks = sorted(row["priorityRank"] for row in _echelon([_variant("s")]).lane_rows())
        self.assertEqual(ranks, list(range(1, len(ranks) + 1)))


class EmissionTests(unittest.TestCase):
    def test_an_inactive_zero_state_cell_is_never_emitted(self) -> None:
        """The forbidden Cartesian row: no stock, not listed, so no cell exists."""

        echelon = _echelon([_variant("sku-future", launch=date(2026, 6, 1))])
        rows = list(echelon.snapshot(START))
        self.assertEqual(rows, [])

    def test_a_de_assorted_cell_with_residual_stock_stays_visible(self) -> None:
        """Dead stock must be possible. This is the shape the DC pin already has.

        524 SKUs hold DC stock while outside the active assortment set, so a store
        model that dropped a de-assorted cell would make the ageing and dead-stock
        screens structurally unable to show anything.
        """

        discontinue = START + timedelta(days=14)
        echelon = _echelon([_variant("sku-1", discontinue=discontinue)])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        self.assertGreater(echelon.cells[("bandra", "sku-1")].on_hand, 0)

        after = discontinue + timedelta(days=21)
        rows = list(echelon.snapshot(after))
        self.assertEqual(len(rows), 1, "residual stock must remain visible")
        self.assertEqual(rows[0]["assortmentActive"], "false")
        self.assertEqual(rows[0]["residualOnly"], "true")
        self.assertGreater(rows[0]["onHand"], 0)

    def test_a_de_assorted_cell_that_sold_through_stops_being_emitted(self) -> None:
        """Residual visibility is about residual STOCK, not about history."""

        discontinue = START + timedelta(days=14)
        echelon = _echelon([_variant("sku-1", discontinue=discontinue)])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        cell = echelon.cells[("bandra", "sku-1")]
        echelon.sell(discontinue, "bandra", "sku-1", cell.on_hand)
        self.assertEqual(cell.residual_state(), 0)

        rows = list(echelon.snapshot(discontinue + timedelta(days=21)))
        self.assertEqual(rows, [])

    def test_an_active_cell_is_emitted_even_at_zero_stock(self) -> None:
        """An active cell at zero is a stockout, which is exactly what must show."""

        echelon = _echelon([_variant("sku-1")])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        cell = echelon.cells[("bandra", "sku-1")]
        echelon.sell(START, "bandra", "sku-1", cell.on_hand)
        self.assertEqual(cell.on_hand, 0)

        rows = list(echelon.snapshot(START + timedelta(days=7)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["onHand"], 0)
        self.assertEqual(rows[0]["assortmentActive"], "true")

    def test_snapshots_land_on_the_declared_cadence(self) -> None:
        echelon = _echelon([_variant("sku-1")])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        self.assertEqual(len(list(echelon.snapshot(START))), 1)
        self.assertEqual(list(echelon.snapshot(START + timedelta(days=3))), [])
        self.assertEqual(len(list(echelon.snapshot(START + timedelta(days=7)))), 1)

    def test_the_store_row_is_addressable_as_a_business_central_location(self) -> None:
        """Store stock reaches canonical through the BC-shaped inventory relation."""

        echelon = _echelon([_variant("sku-1")])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        row = next(iter(echelon.snapshot(START)))
        self.assertEqual(row["locationCode"], "MUM-BAN")
        self.assertEqual(row["storeKey"], "bandra")

    def test_observations_are_timed_at_local_end_of_day(self) -> None:
        """The replay clock bridges from a Thursday 23:00 local snapshot.

        A store row timed differently from a DC row would not bridge to the same
        Monday opening, so the two echelons would disagree about the same week.
        """

        echelon = _echelon([_variant("sku-1")])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        row = next(iter(echelon.snapshot(START)))
        self.assertTrue(row["observedAt"].startswith("2026-01-05T23:00:00"))
        self.assertIn("+05:30", row["observedAt"])


class ReplenishmentTests(unittest.TestCase):
    def test_a_review_orders_a_pack_multiple_and_never_rounds_down(self) -> None:
        echelon = _echelon([_variant("sku-1")])
        # Seven days of observed demand, no stock on hand.
        for day_offset in range(7):
            echelon.sell(
                START + timedelta(days=day_offset), "bandra", "sku-1", 5
            )
        orders = list(echelon.review(START + timedelta(days=7)))
        self.assertEqual(len(orders), 1)
        order = orders[0]
        self.assertEqual(order["quantity"] % echelon.pack_size, 0)
        self.assertGreater(order["quantity"], 0)
        self.assertEqual(order["fromLocationKey"], "mumbai-dc")
        self.assertEqual(order["toLocationKey"], "bandra")
        self.assertEqual(order["status"], "dispatched")

    def test_an_order_arrives_after_the_declared_lane_transit(self) -> None:
        echelon = _echelon([_variant("sku-1")])
        for day_offset in range(7):
            echelon.sell(START + timedelta(days=day_offset), "bandra", "sku-1", 5)
        review_day = START + timedelta(days=7)
        order = next(iter(echelon.review(review_day)))
        arrival_day = review_day + timedelta(days=echelon.primary_transit)
        self.assertEqual(order["expectedReceiptDate"], arrival_day.isoformat())

        cell = echelon.cells[("bandra", "sku-1")]
        self.assertEqual(cell.in_transit, order["quantity"])
        # Nothing arrives before its transit elapses.
        self.assertEqual(list(echelon.receive(review_day)), [])
        received = list(echelon.receive(arrival_day))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["status"], "received")
        self.assertEqual(cell.in_transit, 0)
        self.assertEqual(cell.on_hand, order["quantity"])

    def test_replenishment_is_sized_from_observed_demand_only(self) -> None:
        """A store with no observed demand orders nothing, whatever latent truth says."""

        echelon = _echelon([_variant("sku-1")])
        orders = list(echelon.review(START + timedelta(days=7)))
        self.assertEqual(orders, [])

    def test_a_de_assorted_cell_is_not_replenished(self) -> None:
        """Residual stock is worked off, never topped up."""

        discontinue = START + timedelta(days=7)
        echelon = _echelon([_variant("sku-1", discontinue=discontinue)])
        for day_offset in range(7):
            echelon.sell(START + timedelta(days=day_offset), "bandra", "sku-1", 5)
        orders = list(echelon.review(discontinue + timedelta(days=7)))
        self.assertEqual(orders, [])

    def test_a_review_only_happens_on_the_declared_cycle(self) -> None:
        echelon = _echelon([_variant("sku-1")])
        for day_offset in range(7):
            echelon.sell(START + timedelta(days=day_offset), "bandra", "sku-1", 5)
        self.assertEqual(list(echelon.review(START + timedelta(days=3))), [])
        self.assertNotEqual(list(echelon.review(START + timedelta(days=7))), [])


class ShortfallTests(unittest.TestCase):
    def test_a_shortfall_is_reported_rather_than_allowing_negative_stock(self) -> None:
        echelon = _echelon([_variant("sku-1")])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("1")})
        cell = echelon.cells[("bandra", "sku-1")]
        on_hand = cell.on_hand
        served, shortfall = echelon.sell(START, "bandra", "sku-1", on_hand + 25)
        self.assertEqual(served, on_hand)
        self.assertEqual(shortfall, 25)
        self.assertEqual(cell.on_hand, 0, "store stock must never go negative")

    def test_damaged_units_are_not_sellable(self) -> None:
        echelon = _echelon([_variant("sku-1")])
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        cell = echelon.cells[("bandra", "sku-1")]
        cell.damaged = cell.on_hand
        served, shortfall = echelon.sell(START, "bandra", "sku-1", 5)
        self.assertEqual(served, 0)
        self.assertEqual(shortfall, 5)


class ExpiryTests(unittest.TestCase):
    def test_only_perishable_skus_ever_expire(self) -> None:
        """Inventing expiry for a non-perishable SKU would fabricate waste."""

        echelon = _echelon([_variant("sku-durable", shelf_life=None)])
        echelon.seed_opening({("mumbai-dc", "sku-durable"): Decimal("4")})
        self.assertEqual(list(echelon.expire(START + timedelta(days=400))), [])

    def test_a_perishable_cell_wastes_after_its_shelf_life(self) -> None:
        echelon = _echelon([_variant("sku-fresh", shelf_life=7)])
        echelon.seed_opening({("mumbai-dc", "sku-fresh"): Decimal("10")})
        cell = echelon.cells[("bandra", "sku-fresh")]
        before = cell.on_hand
        self.assertEqual(list(echelon.expire(START + timedelta(days=3))), [])
        events = list(echelon.expire(START + timedelta(days=8)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["reasonCode"], "expiry")
        self.assertGreater(events[0]["units"], 0)
        self.assertLess(cell.on_hand, before)

    def test_expiry_does_not_discard_the_whole_shelf_at_once(self) -> None:
        """A store clearing its entire shelf in one day is a model artifact."""

        echelon = _echelon([_variant("sku-fresh", shelf_life=7)])
        echelon.seed_opening({("mumbai-dc", "sku-fresh"): Decimal("20")})
        cell = echelon.cells[("bandra", "sku-fresh")]
        before = cell.on_hand
        list(echelon.expire(START + timedelta(days=8)))
        self.assertGreater(cell.on_hand, 0)
        self.assertLess(cell.on_hand, before)


class FeatureSwitchTests(unittest.TestCase):
    def test_the_domain_removes_cleanly_when_switched_off(self) -> None:
        """Off must mean "no store stock reported", not "every store is empty"."""

        echelon = _echelon([_variant("sku-1")], enabled=False)
        echelon.seed_opening({("mumbai-dc", "sku-1"): Decimal("4")})
        self.assertEqual(echelon.cells, {})
        self.assertEqual(list(echelon.snapshot(START)), [])
        self.assertEqual(list(echelon.review(START + timedelta(days=7))), [])
        self.assertEqual(echelon.sell(START, "bandra", "sku-1", 5), (0, 0))


class ControlTotalTests(unittest.TestCase):
    def test_the_summary_separates_active_from_residual_cells(self) -> None:
        """Gate B needs both counts: one proves coverage, the other proves dead
        stock is representable."""

        discontinue = START + timedelta(days=14)
        echelon = _echelon(
            [_variant("sku-active"), _variant("sku-dead", discontinue=discontinue)]
        )
        echelon.seed_opening(
            {
                ("mumbai-dc", "sku-active"): Decimal("4"),
                ("mumbai-dc", "sku-dead"): Decimal("4"),
            }
        )
        summary = echelon.coverage_summary()
        self.assertEqual(summary["cells"], 2)
        self.assertEqual(summary["activeCellsAtEnd"], 1)
        self.assertEqual(summary["residualCellsAtEnd"], 1)
        self.assertEqual(summary["storesWithStock"], 1)


if __name__ == "__main__":
    unittest.main()
