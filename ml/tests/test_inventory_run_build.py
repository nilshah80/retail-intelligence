"""P4-7/P4-8 artifact assembly: the two echelons, the gate, and the grain.

The fixture is small on purpose. Two markets is enough to prove ABC stays
market-local; a store with a rank-1 and a rank-2 lane is enough to prove a
transfer uses the alternate; and one cell whose protection period reaches past
horizon 4 is enough to prove decision #92 withholds rather than zeroes.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import pytest

from retail_contracts.guardrails import resolve_guardrails

from retail_ml.engines.analytics import AGE_BUCKETS, age_bucket

from retail_ml.inventory_publish.run_artifacts import ARTIFACT_COLUMNS
from retail_ml.inventory_run.build import (
    COLD_START_REASON,
    UNRESOLVED_ROUTE_REASON,
    InventoryBuildError,
    InventoryInputs,
    build_artifacts,
    coverage_summary,
)

AS_OF = date(2026, 7, 27)
MARKET = "india-west"
OTHER = "us-new-york"
DC = f"{MARKET}:mumbai-dc"
ALT_DC = f"{MARKET}:pune-overflow"
STORE = f"{MARKET}:mumbai-bandra"
OTHER_STORE = f"{OTHER}:ny-manhattan"

CURRENCIES = {MARKET: "INR", OTHER: "USD"}

#: Resolved from the committed contract, not restated. A hand-written fixture
#: policy passes happily while production reads a key the contract renamed -- which
#: is exactly what happened here: the first version of this file declared
#: `ageingHoldCoverDays` and `serviceLevelByClass`, neither of which
#: inventory-policy-v2.yaml has ever contained. Resolving the real document means
#: a rename breaks these tests at the same moment it breaks the run.
POLICIES = {
    market: resolve_guardrails(
        market, currency, inventory_policy_generation="v2"
    )["inventoryPolicy"]
    for market, currency in CURRENCIES.items()
}

LANES = [
    {
        "lane_id": f"{STORE}:{DC}:replenishment",
        "market_id": MARKET,
        "lane_type": "replenishment",
        "demand_location_id": STORE,
        "channel_id": None,
        "supply_location_id": DC,
        "priority_rank": 1,
        "transit_days": 1,
        "effective_from": date(2016, 7, 28),
        "effective_to": None,
    },
    {
        "lane_id": f"{STORE}:{ALT_DC}:replenishment",
        "market_id": MARKET,
        "lane_type": "replenishment",
        "demand_location_id": STORE,
        "channel_id": None,
        "supply_location_id": ALT_DC,
        "priority_rank": 2,
        "transit_days": 2,
        "effective_from": date(2016, 7, 28),
        "effective_to": None,
    },
    {
        "lane_id": f"{OTHER_STORE}:{OTHER}:newark-dc:replenishment",
        "market_id": OTHER,
        "lane_type": "replenishment",
        "demand_location_id": OTHER_STORE,
        "channel_id": None,
        "supply_location_id": f"{OTHER}:newark-dc",
        "priority_rank": 1,
        "transit_days": 1,
        "effective_from": date(2016, 7, 28),
        "effective_to": None,
    },
]

SUPPLY_TERMS = [
    {
        "destination_location_id": DC,
        "origin_kind": "external_supplier",
        "origin_id": "sup-1",
        "merch_scope_type": "category",
        "merch_scope_id": "grocery",
        "effective_from": date(2016, 7, 28),
        "effective_to": None,
        "lead_time_days": 6,
        "lead_time_std_days": 1.5,
        "moq": 12,
        "pack_qty": 6,
    },
    {
        # 40-day lead time: the protection period reaches horizon 7, past the
        # calibrated 4, so decision #92 must withhold this cell.
        "destination_location_id": ALT_DC,
        "origin_kind": "external_supplier",
        "origin_id": "sup-2",
        "merch_scope_type": "category",
        "merch_scope_id": "grocery",
        "effective_from": date(2016, 7, 28),
        "effective_to": None,
        "lead_time_days": 40,
        "lead_time_std_days": 4.0,
        "moq": 1,
        "pack_qty": 1,
    },
]


def _position(
    market: str,
    location: str,
    kind: str,
    sku: str,
    *,
    on_hand: int,
    assortment_active: bool = True,
    committed: int = 0,
    in_transit: int = 0,
    on_order: int = 0,
) -> dict[str, Any]:
    return {
        "market_id": market,
        "location_id": location,
        "location_kind": kind,
        "sku_id": sku,
        "dept_id": "food",
        "category": "grocery",
        "on_hand_units": on_hand,
        "committed_units": committed,
        "reserved_units": 0,
        "damaged_units": 0,
        "on_order_units": on_order,
        "in_transit_units": in_transit,
        "assortment_active": assortment_active,
    }


def _inputs(**overrides: Any) -> InventoryInputs:
    positions = pd.DataFrame(
        [
            _position(MARKET, STORE, "store", "sku-1", on_hand=2, committed=1),
            _position(MARKET, STORE, "store", "sku-2", on_hand=0),
            # Residual: de-assorted but still holding stock, so it must appear.
            _position(
                MARKET, STORE, "store", "sku-3", on_hand=5, assortment_active=False
            ),
            # De-assorted AND empty: nothing observed it, so it must NOT appear.
            _position(
                MARKET, STORE, "store", "sku-4", on_hand=0, assortment_active=False
            ),
            _position(MARKET, DC, "dc", "sku-1", on_hand=6),
            _position(MARKET, ALT_DC, "dc", "sku-1", on_hand=400),
            _position(MARKET, ALT_DC, "dc", "sku-2", on_hand=50),
            _position(OTHER, OTHER_STORE, "store", "sku-1", on_hand=80),
        ]
    )
    trailing = pd.DataFrame(
        [
            {"market_id": MARKET, "location_id": STORE, "sku_id": "sku-1",
             "trailing_avg_daily_units": 4.0},
            {"market_id": MARKET, "location_id": STORE, "sku_id": "sku-2",
             "trailing_avg_daily_units": 2.0},
            {"market_id": MARKET, "location_id": STORE, "sku_id": "sku-3",
             "trailing_avg_daily_units": 0.0},
            {"market_id": MARKET, "location_id": DC, "sku_id": "sku-1",
             "trailing_avg_daily_units": 1.0},
            {"market_id": MARKET, "location_id": ALT_DC, "sku_id": "sku-1",
             "trailing_avg_daily_units": 1.0},
            {"market_id": MARKET, "location_id": ALT_DC, "sku_id": "sku-2",
             "trailing_avg_daily_units": 1.0},
            {"market_id": OTHER, "location_id": OTHER_STORE, "sku_id": "sku-1",
             "trailing_avg_daily_units": 1.0},
        ]
    )
    forecast = pd.DataFrame(
        [
            {
                "market_id": market,
                "location_id": location,
                "sku_id": sku,
                "horizon_week": horizon,
                "yhat_p50": 10.0,
                "yhat_p90": 16.0 if horizon <= 4 else None,
                "interval_available": horizon <= 4,
            }
            for market, location, sku in (
                (MARKET, STORE, "sku-1"),
                (MARKET, STORE, "sku-2"),
                (MARKET, STORE, "sku-3"),
                (MARKET, DC, "sku-1"),
                (MARKET, ALT_DC, "sku-1"),
                (MARKET, ALT_DC, "sku-2"),
                (OTHER, OTHER_STORE, "sku-1"),
            )
            for horizon in range(1, 9)
        ]
    )
    batches = pd.DataFrame(
        [
            {
                "market_id": MARKET, "location_id": STORE, "sku_id": "sku-1",
                "batch_id": "b1", "received_on": date(2026, 7, 20),
                "expires_on": date(2026, 8, 5), "on_hand_units": 2,
                "unit_cost_minor": 1500,
            },
            {
                "market_id": MARKET, "location_id": STORE, "sku_id": "sku-3",
                "batch_id": "b2", "received_on": date(2026, 1, 5),
                "expires_on": None, "on_hand_units": 5, "unit_cost_minor": 900,
            },
        ]
    )
    waste = pd.DataFrame(
        [
            {"market_id": MARKET, "location_id": STORE, "sku_id": "sku-1",
             "waste_units": 3, "expired_units": 2},
        ]
    )
    unit_costs = pd.DataFrame(
        [
            {"market_id": m, "location_id": loc, "sku_id": s,
             "unit_cost_minor": cost, "cost_method": "store_wac"}
            for m, loc, s, cost in (
                (MARKET, STORE, "sku-1", 1500),
                (MARKET, STORE, "sku-2", 800),
                (MARKET, STORE, "sku-3", 900),
                (MARKET, DC, "sku-1", 1400),
                (MARKET, ALT_DC, "sku-1", 1400),
                (MARKET, ALT_DC, "sku-2", 700),
                (OTHER, OTHER_STORE, "sku-1", 2000),
            )
        ]
    )
    wms = pd.DataFrame(
        [
            {"market_id": MARKET, "location_id": STORE, "sku_id": "sku-1",
             "variance_units": 2},
        ]
    )
    suppliers = pd.DataFrame(
        [
            {"market_id": MARKET, "supplier_id": "sup-1", "otd_rate": 0.95,
             "lead_time_mean_days": 6.0, "lead_time_std_days": 1.5,
             "capacity_confirmed_pct": 0.95},
            {"market_id": MARKET, "supplier_id": "sup-2", "otd_rate": 0.60,
             "lead_time_mean_days": 40.0, "lead_time_std_days": 9.0,
             "capacity_confirmed_pct": 0.50},
        ]
    )
    channel_demand = pd.DataFrame(
        [
            {"market_id": MARKET, "location_id": STORE, "channel_id": "store",
             "sku_id": "sku-1", "requested_units": 20},
            {"market_id": MARKET, "location_id": STORE, "channel_id": "online",
             "sku_id": "sku-1", "requested_units": 10},
        ]
    )
    warehouse_capacity = pd.DataFrame(
        [
            {"market_id": MARKET, "location_id": DC, "capacity_units": 750_000,
             "snapshot_date": AS_OF},
        ]
    )
    inbound_summary = pd.DataFrame(
        [
            {"market_id": MARKET, "location_id": DC, "open_shipments": 3,
             "open_units": 180, "received_shipments": 40, "late_shipments": 9},
        ]
    )
    fields: dict[str, Any] = {
        "as_of": AS_OF,
        "positions": positions,
        "trailing_demand": trailing,
        "forecast": forecast,
        "batches": batches,
        "waste": waste,
        "unit_costs": unit_costs,
        "wms_variance": wms,
        "lanes": [dict(lane) for lane in LANES],
        "supply_terms": [dict(term) for term in SUPPLY_TERMS],
        "suppliers": suppliers,
        "warehouse_capacity": warehouse_capacity,
        "inbound_summary": inbound_summary,
        "open_purchase_orders": pd.DataFrame(
            columns=[
                "market_id", "supplier_id", "location_id", "sku_id", "open_units",
            ]
        ),
        "channel_demand": channel_demand,
        "policy": POLICIES,
        "currency_by_market": CURRENCIES,
    }
    fields.update(overrides)
    return InventoryInputs(**fields)


def _metrics() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"market_id": market, "metric": metric, "cohort": cohort,
             "candidate_value": "1.0000", "incumbent_value": "2.0000",
             "passed": True}
            for market in (MARKET, OTHER)
            for metric in ("stockoutPeriods", "lostUnits", "fillRate",
                           "meanInventoryUnits")
            for cohort in ("calibration", "holdout")
        ]
    )


@pytest.fixture(name="artifacts")
def _artifacts() -> dict[str, pd.DataFrame]:
    return build_artifacts(_inputs(), replay_metrics=_metrics())


# -- the contract --------------------------------------------------------------

def test_every_artifact_is_built_in_the_frozen_column_order(artifacts) -> None:
    assert set(artifacts) == set(ARTIFACT_COLUMNS)
    for name, frame in artifacts.items():
        assert tuple(frame.columns) == ARTIFACT_COLUMNS[name], name


def test_zero_positions_is_refused_rather_than_published_as_facts() -> None:
    empty = _inputs(positions=pd.DataFrame(columns=_inputs().positions.columns))
    with pytest.raises(InventoryBuildError, match="zero"):
        build_artifacts(empty, replay_metrics=_metrics())


# -- grain ---------------------------------------------------------------------

def test_a_deassorted_empty_cell_is_not_emitted(artifacts) -> None:
    """The Cartesian guard. sku-4 is de-assorted and holds nothing, so nothing
    observed it and no screen should count it."""

    positions = artifacts["inventory_positions"]
    assert "sku-4" not in set(positions["sku_id"])


def test_a_deassorted_cell_still_holding_stock_is_emitted_as_residual(
    artifacts,
) -> None:
    positions = artifacts["inventory_positions"]
    residual = positions[positions["sku_id"] == "sku-3"]
    assert len(residual) == 1
    assert bool(residual.iloc[0]["residual_only"]) is True
    assert bool(residual.iloc[0]["assortment_active"]) is False


def test_dc_rows_are_active_via_the_lanes_they_supply_not_marked_residual(
    artifacts,
) -> None:
    """`assortment_calendar` is store-scoped, so without lane-derived activity
    every DC position would publish as residual-only and the overview would read
    as though the network were winding down."""

    positions = artifacts["inventory_positions"]
    dc_rows = positions[positions["location_id"].isin({DC, ALT_DC})]
    assert not dc_rows.empty
    active = dc_rows[dc_rows["sku_id"] == "sku-1"]
    assert bool(active["assortment_active"].all())
    assert not bool(active["residual_only"].any())


def test_atp_excludes_committed_stock_but_not_in_transit(artifacts) -> None:
    positions = artifacts["inventory_positions"]
    row = positions[
        (positions["location_id"] == STORE) & (positions["sku_id"] == "sku-1")
    ].iloc[0]
    assert int(row["on_hand_units"]) == 2
    assert int(row["committed_units"]) == 1
    assert int(row["atp_units"]) == 1


# -- decision #92 --------------------------------------------------------------

def test_a_protection_period_past_horizon_four_withholds_rather_than_zeroes(
    artifacts,
) -> None:
    """ALT_DC's supplier has a 40-day lead time, so its protection period needs
    horizon 7. A zero safety stock here would be indistinguishable from a real
    zero on exactly the least predictable node."""

    safety = artifacts["replenishment_safety_stock"]
    row = safety[
        (safety["location_id"] == ALT_DC) & (safety["sku_id"] == "sku-1")
    ].iloc[0]
    assert bool(row["interval_available"]) is False
    assert pd.isna(row["safety_stock_units"])
    assert pd.isna(row["service_level"])
    assert row["reason_code"] == COLD_START_REASON

    recommendations = artifacts["replenishment_recommendations"]
    recommendation = recommendations[
        (recommendations["destination_location_id"] == ALT_DC)
        & (recommendations["sku_id"] == "sku-1")
    ].iloc[0]
    assert bool(recommendation["interval_available"]) is False
    assert pd.isna(recommendation["recommended_units"])
    assert pd.isna(recommendation["reorder_point_units"])
    assert pd.isna(recommendation["order_up_to_units"])


def test_a_withheld_cell_emits_its_governed_exception(artifacts) -> None:
    exceptions = artifacts["replenishment_exceptions"]
    withheld = exceptions[
        exceptions["exception_class"] == "cold_start_interval_unavailable"
    ]
    assert not withheld.empty
    assert set(withheld["reason_code"]) == {COLD_START_REASON}
    assert ALT_DC in set(withheld["location_id"])


def test_a_cell_inside_the_calibrated_horizon_is_fully_assessed(
    artifacts,
) -> None:
    """The store's lane gives a 1-day transit, so its protection period needs
    horizon 2 and everything is available. If this row were withheld too, the
    withholding above would prove nothing."""

    safety = artifacts["replenishment_safety_stock"]
    row = safety[
        (safety["location_id"] == STORE) & (safety["sku_id"] == "sku-1")
    ].iloc[0]
    assert bool(row["interval_available"]) is True
    assert float(row["safety_stock_units"]) > 0
    assert row["reason_code"] is None
    assert row["abc_class"] in {"A", "B", "C"}


def test_the_interval_truth_table_holds_on_every_gated_artifact(artifacts) -> None:
    for name, gate in (
        ("inventory_demand_at_risk", "risk_units"),
        ("replenishment_safety_stock", "safety_stock_units"),
    ):
        frame = artifacts[name]
        available = frame["interval_available"].astype(bool)
        assert bool((available == frame[gate].notna()).all()), name
        assert bool(frame.loc[~available, "reason_code"].notna().all()), name
        assert bool(frame.loc[available, "reason_code"].isna().all()), name


def test_a_withheld_risk_row_carries_no_currency_or_value(artifacts) -> None:
    risk = artifacts["inventory_demand_at_risk"]
    withheld = risk[~risk["interval_available"].astype(bool)]
    assert not withheld.empty
    assert bool(withheld["risk_value_minor"].isna().all())
    assert bool(withheld["currency_code"].isna().all())


# -- the two echelons ----------------------------------------------------------

def test_a_store_is_supplied_by_its_rank_one_dc_over_the_declared_lane(
    artifacts,
) -> None:
    recommendations = artifacts["replenishment_recommendations"]
    row = recommendations[
        (recommendations["destination_location_id"] == STORE)
        & (recommendations["sku_id"] == "sku-1")
    ].iloc[0]
    assert row["supply_location_id"] == DC


def test_a_dc_is_supplied_by_its_external_supplier_term(artifacts) -> None:
    recommendations = artifacts["replenishment_recommendations"]
    row = recommendations[
        (recommendations["destination_location_id"] == DC)
        & (recommendations["sku_id"] == "sku-1")
    ].iloc[0]
    assert row["supply_location_id"] == "sup-1"


def test_every_recommendation_is_shadow_only(artifacts) -> None:
    statuses = set(artifacts["replenishment_recommendations"]["erp_status"])
    assert statuses == {"shadow_not_sent"}


def test_an_undeclared_route_fails_closed_instead_of_using_a_default() -> None:
    """Policy v2 says `laneResolution.unresolvedBehavior: fail_closed`.

    An earlier version applied a market default lead time here, which published a
    confident reorder point for a node whose route nobody declared -- and it
    looked identical on screen to a resolved one. The row must withhold, and it
    must withhold for the ROUTE's reason, not the cold-start one: an operator told
    to wait for calibration will wait forever for a missing lane.
    """

    orphaned = [
        lane for lane in LANES if lane["demand_location_id"] != STORE
    ]
    artifacts = build_artifacts(
        _inputs(lanes=orphaned), replay_metrics=_metrics()
    )

    recommendations = artifacts["replenishment_recommendations"]
    row = recommendations[
        (recommendations["destination_location_id"] == STORE)
        & (recommendations["sku_id"] == "sku-1")
    ].iloc[0]
    assert bool(row["interval_available"]) is False
    assert row["reason_code"] == UNRESOLVED_ROUTE_REASON
    assert pd.isna(row["recommended_units"])
    assert pd.isna(row["reorder_point_units"])
    assert row["supply_location_id"] is None

    risk = artifacts["inventory_demand_at_risk"]
    risk_row = risk[
        (risk["location_id"] == STORE) & (risk["sku_id"] == "sku-1")
    ].iloc[0]
    assert bool(risk_row["interval_available"]) is False
    assert risk_row["reason_code"] == UNRESOLVED_ROUTE_REASON

    exceptions = artifacts["replenishment_exceptions"]
    unresolved = exceptions[
        exceptions["exception_class"] == "supply_route_unresolved"
    ]
    assert not unresolved.empty
    assert set(unresolved["severity"]) == {"warning"}
    assert "NO_ACTIVE_SERVICE_LANE" in " ".join(unresolved["evidence"])


def test_the_two_governed_reasons_stay_distinguishable(artifacts) -> None:
    """A cold-start withholding and an unresolved route are different findings.

    If they collapsed to one code the exceptions screen could not tell an operator
    which lever to pull.
    """

    safety = artifacts["replenishment_safety_stock"]
    withheld = set(safety.loc[~safety["interval_available"].astype(bool), "reason_code"])
    assert withheld <= {COLD_START_REASON, UNRESOLVED_ROUTE_REASON}
    assert COLD_START_REASON in withheld


# -- transfers over the declared alternate lane --------------------------------

def test_a_transfer_uses_the_rank_two_alternate_when_the_primary_cannot_cover(
    artifacts,
) -> None:
    """The store is short, its rank-1 DC holds only 6 units, and the rank-2 DC
    holds 400. That is the case this network's transfer screen exists for."""

    transfers = artifacts["replenishment_transfers"]
    assert not transfers.empty
    row = transfers.iloc[0]
    assert row["from_location_id"] == ALT_DC
    assert row["to_location_id"] == STORE
    assert row["lane_id"] == f"{STORE}:{ALT_DC}:replenishment"
    assert int(row["transit_days"]) == 2
    assert int(row["units"]) > 0
    assert row["currency_code"] == "INR"


def test_a_transfer_never_leaves_a_donor_below_its_retained_cover(
    artifacts,
) -> None:
    transfers = artifacts["replenishment_transfers"]
    positions = artifacts["inventory_positions"]
    for row in transfers.itertuples(index=False):
        donor = positions[
            (positions["location_id"] == row.from_location_id)
            & (positions["sku_id"] == row.sku_id)
        ].iloc[0]
        assert int(row.units) <= int(donor["atp_units"])


# -- money and markets ---------------------------------------------------------

def test_abc_is_ranked_within_each_market(artifacts) -> None:
    """Cross-market ranking would order SKUs by exchange rate. The engine refuses
    it, so this asserts the builder actually splits before calling."""

    safety = artifacts["replenishment_safety_stock"]
    for market in (MARKET, OTHER):
        classes = safety[safety["market_id"] == market]["abc_class"].dropna()
        assert not classes.empty, market
        assert "A" in set(classes), f"{market} has no A class of its own"


def test_every_money_column_carries_its_market_currency(artifacts) -> None:
    for name, column in (
        ("inventory_valuation", "gross_value_minor"),
        ("inventory_expiry_waste", "exposure_minor"),
        ("inventory_demand_at_risk", "risk_value_minor"),
    ):
        frame = artifacts[name]
        present = frame[frame[column].notna()]
        for row in present.itertuples(index=False):
            assert row.currency_code == CURRENCIES[row.market_id], name


def test_a_category_with_an_uncosted_on_hand_sku_is_unvalued_with_a_reason() -> (
    None
):
    inputs = _inputs()
    costs = inputs.unit_costs
    inputs = _inputs(
        unit_costs=costs[
            ~(
                (costs["location_id"] == STORE) & (costs["sku_id"] == "sku-1")
            )
        ].reset_index(drop=True)
    )
    artifacts = build_artifacts(inputs, replay_metrics=_metrics())
    valuation = artifacts["inventory_valuation"]
    row = valuation[valuation["location_id"] == STORE].iloc[0]
    assert pd.isna(row["gross_value_minor"])
    assert row["cost_reason_code"] == "UNIT_COST_UNAVAILABLE"
    # Currency survives: the reader still needs to know which currency the
    # missing number would have been in.
    assert row["currency_code"] == "INR"


def test_the_valuation_truth_table_holds(artifacts) -> None:
    valuation = artifacts["inventory_valuation"]
    absent = valuation["gross_value_minor"].isna()
    named = valuation["cost_reason_code"].notna()
    assert bool((absent == named).all())


# -- health, ageing, expiry ----------------------------------------------------

def test_health_reasons_come_from_the_engine_not_from_the_builder(
    artifacts,
) -> None:
    """sku-3 is de-assorted with stock, so the engine calls it dead for a
    different reason than a zero-demand assorted SKU would be."""

    health = artifacts["inventory_stock_health"]
    row = health[health["sku_id"] == "sku-3"].iloc[0]
    assert row["health_class"] == "dead"
    assert row["reason_code"] == "DEAD_STOCK_DEASSORTED"
    assert pd.isna(row["cover_days"])


def test_the_health_cover_reason_truth_table_holds(artifacts) -> None:
    health = artifacts["inventory_stock_health"]
    assert bool(
        (health["cover_days"].isna() == health["reason_code"].notna()).all()
    )


def test_forward_expiry_exposure_and_realized_waste_stay_separate(
    artifacts,
) -> None:
    expiry = artifacts["inventory_expiry_waste"]
    row = expiry[expiry["sku_id"] == "sku-1"].iloc[0]
    # b1 expires 2026-08-05, nine days out, inside the 30-day window.
    assert int(row["expiring_units"]) == 2
    assert int(row["exposure_minor"]) == 2 * 1500
    # Realized loss comes from waste events, not from the same batch rows.
    assert int(row["waste_units"]) == 3
    assert int(row["expired_units"]) == 2


def test_a_batch_with_no_expiry_contributes_no_exposure(artifacts) -> None:
    """Inventing an expiry for a non-perishable would fabricate waste evidence."""

    expiry = artifacts["inventory_expiry_waste"]
    row = expiry[expiry["sku_id"] == "sku-3"]
    if not row.empty:
        assert int(row.iloc[0]["expiring_units"]) == 0


def test_ageing_handles_pandas_timestamps_not_only_date_literals() -> None:
    """Parquet gives Timestamps, and this fixture used to give only date literals.

    `pd.Timestamp` subclasses `datetime` which subclasses `date`, so an
    `isinstance(value, date)` check returns it unconverted and the subtraction
    that follows raises TypeError. Every fixture test passed while the real run
    died on the first batch row, which is the exact shape of gap a fixture that
    is tidier than production leaves behind.
    """

    inputs = _inputs()
    batches = inputs.batches.copy()
    for column in ("received_on", "expires_on"):
        batches[column] = pd.to_datetime(batches[column])
    artifacts = build_artifacts(
        _inputs(batches=batches), replay_metrics=_metrics()
    )
    ageing = artifacts["inventory_ageing"]
    assert not ageing.empty
    # The engine owns the bucket vocabulary. Ask it for the labels rather than
    # restating them: AGE_BUCKETS holds the numeric ranges, and `age_bucket` is
    # what turns a range into the published string.
    labels = {
        age_bucket(on_hand_age_days=days)
        for lower, upper in AGE_BUCKETS
        for days in (lower, (upper - 1) if upper else lower + 1)
    }
    assert set(ageing["age_bucket"]) <= labels
    expiry = artifacts["inventory_expiry_waste"]
    assert int(expiry[expiry["sku_id"] == "sku-1"].iloc[0]["expiring_units"]) == 2


def test_ageing_buckets_are_keyed_by_receipt_age(artifacts) -> None:
    ageing = artifacts["inventory_ageing"]
    old = ageing[ageing["sku_id"] == "sku-3"].iloc[0]
    assert old["age_bucket"] not in {"0-30"}
    assert int(old["on_hand_units"]) == 5
    assert bool(old["residual_only"]) is True


# -- allocation and suppliers --------------------------------------------------

def test_allocation_conserves_the_pool_and_loses_no_channel(artifacts) -> None:
    allocations = artifacts["replenishment_allocations"]
    assert set(allocations["channel_id"]) == {"store", "online"}
    positions = artifacts["inventory_positions"]
    atp = int(
        positions[
            (positions["location_id"] == STORE) & (positions["sku_id"] == "sku-1")
        ].iloc[0]["atp_units"]
    )
    assert int(allocations["allocated_units"].sum()) <= atp
    for row in allocations.itertuples(index=False):
        assert int(row.allocated_units) + int(row.shortfall_units) == int(
            row.requested_units
        )


def test_supplier_risk_reflects_otd_variability_and_capacity(artifacts) -> None:
    suppliers = artifacts["replenishment_suppliers"]
    healthy = suppliers[suppliers["supplier_id"] == "sup-1"].iloc[0]
    assert healthy["risk_class"] == "low"
    assert healthy["reason_codes"] is None

    troubled = suppliers[suppliers["supplier_id"] == "sup-2"].iloc[0]
    assert troubled["risk_class"] == "high"
    assert set(troubled["reason_codes"]) >= {
        "OTD_BELOW_FLOOR",
        "CAPACITY_UNCONFIRMED",
        "LEAD_TIME_VOLATILE",
    }


# -- disclosure ----------------------------------------------------------------

def test_the_coverage_summary_reports_both_assessed_and_withheld(
    artifacts,
) -> None:
    summary = coverage_summary(artifacts)
    risk = summary["inventory_demand_at_risk"]
    assert risk["rows"] == risk["intervalAvailableRows"] + risk[
        "intervalWithheldRows"
    ]
    assert risk["intervalWithheldRows"] > 0, (
        "the fixture must actually withhold something or this proves nothing"
    )
    assert summary["inventory_positions"]["residualOnlyRows"] == 1
    assert summary["inventory_stock_health"]["byClass"]


def test_no_exception_row_duplicates_a_cell_and_class(artifacts) -> None:
    exceptions = artifacts["replenishment_exceptions"]
    grain = ["market_id", "location_id", "sku_id", "channel_id", "exception_class"]
    assert not bool(exceptions.duplicated(grain).any())
