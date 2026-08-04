"""P4-8 publication and independent verification: every refusal, exercised.

The fixture below is a minimal bundle that passes. Each test mutates exactly one
thing and asserts the refusal, because a gate that has never been observed to
refuse is a gate nobody has tested -- only a comment.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import pytest

from retail_ml.inventory_publish.run_artifacts import (
    ARTIFACT_COLUMNS,
    ARTIFACT_SCHEMAS,
    InventoryPublicationError,
    publish_inventory_run,
)
from retail_ml.inventory_publish.verify import (
    InventoryVerificationError,
    verify_inventory_run,
)

MARKETS = ["india-west", "us-new-york"]
DECISION_AS_OF = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)
CREATED_AT = datetime(2026, 7, 27, 6, 30, tzinfo=timezone.utc)

PIN: dict[str, Any] = {
    "sourceSnapshotId": "snap-v13",
    "gateA": {"semanticFingerprint": "a" * 64},
    "gateB": {"semanticFingerprint": "b" * 64},
    "publication": {"semanticFingerprint": "c" * 64},
}
INPUT_BUNDLE = {
    "sourceSnapshotId": "snap-v13",
    "gateASemanticFingerprint": "a" * 64,
    "gateBSemanticFingerprint": "b" * 64,
    "publicationSemanticFingerprint": "c" * 64,
}
SELECTION_ID = "sel-2026-07-27-current"
FORECAST = {
    "forecastRunId": "fr_0123456789abcdef",
    "forecastVersionId": "fv_0123456789abcdef",
    "coverageGateMode": "hard",
}
POLICY_FINGERPRINTS = {"india-west": "d" * 64, "us-new-york": "e" * 64}
REPLAY: dict[str, Any] = {
    "incumbentPolicyId": "incumbent/reorder-point-v0",
    "oracle": {"passed": True, "weeksCompared": 52},
    "oracleTolerance": {
        "frozenBeforeScoring": True,
        "meanAbsUnitDelta": "0.5000",
    },
}


def _frames() -> dict[str, pd.DataFrame]:
    """A minimal bundle: per market, one fully assessed cell and one whose
    interval decision #92 withheld."""

    def stack(builder: Callable[[str], list[dict[str, Any]]]) -> pd.DataFrame:
        return pd.DataFrame([row for market in MARKETS for row in builder(market)])

    frames: dict[str, pd.DataFrame] = {
        "inventory_positions": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "location_kind": "store",
                    "sku_id": "sku-1",
                    "on_hand_units": 40,
                    "committed_units": 4,
                    "reserved_units": 0,
                    "damaged_units": 1,
                    "on_order_units": 12,
                    "in_transit_units": 6,
                    "atp_units": 35,
                    "assortment_active": True,
                    "residual_only": False,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-dc-1",
                    "location_kind": "dc",
                    "sku_id": "sku-2",
                    "on_hand_units": 9,
                    "committed_units": 0,
                    "reserved_units": 0,
                    "damaged_units": 0,
                    "on_order_units": 0,
                    "in_transit_units": 0,
                    "atp_units": 9,
                    "assortment_active": False,
                    "residual_only": True,
                },
            ]
        ),
        "inventory_stock_health": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "sku_id": "sku-1",
                    "health_class": "healthy",
                    "cover_days": 21.5,
                    "reason_code": None,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-store-2",
                    "sku_id": "sku-2",
                    "health_class": "stockout",
                    "cover_days": None,
                    "reason_code": "COLD_START_INTERVAL_UNCALIBRATED",
                },
            ]
        ),
        "inventory_demand_at_risk": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "sku_id": "sku-1",
                    "channel_id": "store",
                    "risk_units": 3.25,
                    "risk_value_minor": 48750,
                    "currency_code": "INR",
                    "interval_available": True,
                    "reason_code": None,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-store-2",
                    "sku_id": "sku-2",
                    "channel_id": "store",
                    "risk_units": None,
                    "risk_value_minor": None,
                    "currency_code": None,
                    "interval_available": False,
                    "reason_code": "COLD_START_INTERVAL_UNCALIBRATED",
                },
            ]
        ),
        "inventory_ageing": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "sku_id": "sku-1",
                    "age_bucket": "0-30",
                    "on_hand_units": 40,
                    "action": "monitor",
                    "markdown_pct": None,
                    "residual_only": False,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-dc-1",
                    "sku_id": "sku-2",
                    "age_bucket": "91-180",
                    "on_hand_units": 9,
                    "action": "markdown",
                    "markdown_pct": 0.25,
                    "residual_only": True,
                },
            ]
        ),
        "inventory_expiry_waste": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "sku_id": "sku-1",
                    "expiring_units": 3,
                    "expired_units": 0,
                    "waste_units": 0,
                    "exposure_minor": 4500,
                    "currency_code": "INR",
                }
            ]
        ),
        # The dimension every screen reads category and money through (P4-11).
        "inventory_sku_dimension": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "sku_id": f"{market}-sku-1",
                    "category": "grocery",
                    "category_label": "Grocery",
                    "product_name": "Test Product",
                    "location_name": "Test Store",
                    "location_kind": "store",
                    "unit_cost_minor": 1250,
                    "cost_method": "store_wac",
                    "currency_code": "INR",
                    "trailing_daily_units": 4.5,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-dc-1",
                    "sku_id": f"{market}-sku-1",
                    "category": "grocery",
                    "category_label": "Grocery",
                    "product_name": "Test Product",
                    "location_name": "Test Distribution Centre",
                    "location_kind": "dc",
                    "unit_cost_minor": 1180,
                    "cost_method": "WAC",
                    "currency_code": "INR",
                    "trailing_daily_units": 9.0,
                },
            ]
        ),
        "inventory_valuation": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "category": "grocery",
                    "gross_value_minor": 1250000,
                    "currency_code": "INR",
                    "cost_method": "store_wac",
                    "cost_reason_code": None,
                    "wms_variance_units": 2,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-dc-1",
                    "category": "grocery",
                    "gross_value_minor": None,
                    "currency_code": "INR",
                    "cost_method": None,
                    "cost_reason_code": "NRV_UNAVAILABLE",
                    "wms_variance_units": None,
                },
            ]
        ),
        "replenishment_recommendations": stack(
            lambda market: [
                {
                    "market_id": market,
                    "destination_location_id": f"{market}-store-1",
                    "supply_location_id": f"{market}-dc-1",
                    "sku_id": "sku-1",
                    "recommended_units": 24,
                    "reorder_point_units": 18.5,
                    "order_up_to_units": 64.0,
                    "lead_time_days": 6,
                    "interval_available": True,
                    "reason_code": None,
                    "erp_status": "shadow_not_sent",
                },
                {
                    "market_id": market,
                    "destination_location_id": f"{market}-store-2",
                    "supply_location_id": None,
                    "sku_id": "sku-2",
                    "recommended_units": None,
                    "reorder_point_units": None,
                    "order_up_to_units": None,
                    "lead_time_days": 6,
                    "interval_available": False,
                    "reason_code": "COLD_START_INTERVAL_UNCALIBRATED",
                    "erp_status": "shadow_not_sent",
                },
            ]
        ),
        "replenishment_safety_stock": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "sku_id": "sku-1",
                    "abc_class": "A",
                    "service_level": 0.98,
                    "safety_stock_units": 11.75,
                    "interval_available": True,
                    "reason_code": None,
                },
                {
                    "market_id": market,
                    "location_id": f"{market}-store-2",
                    "sku_id": "sku-2",
                    "abc_class": "C",
                    "service_level": None,
                    "safety_stock_units": None,
                    "interval_available": False,
                    "reason_code": "COLD_START_INTERVAL_UNCALIBRATED",
                },
            ]
        ),
        "replenishment_transfers": stack(
            lambda market: [
                {
                    "market_id": market,
                    "lane_id": f"{market}-lane-1",
                    "from_location_id": f"{market}-dc-1",
                    "to_location_id": f"{market}-store-1",
                    "sku_id": "sku-1",
                    "units": 18,
                    "expected_benefit_minor": 32000,
                    "currency_code": "INR",
                    "transit_days": 2,
                }
            ]
        ),
        "replenishment_allocations": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-1",
                    "channel_id": "store",
                    "sku_id": "sku-1",
                    "requested_units": 30,
                    "allocated_units": 24,
                    "shortfall_units": 6,
                }
            ]
        ),
        "replenishment_suppliers": stack(
            lambda market: [
                {
                    "market_id": market,
                    "supplier_id": f"{market}-sup-1",
                    "otd_rate": 0.92,
                    "lead_time_mean_days": 6.5,
                    "lead_time_std_days": 1.25,
                    "capacity_confirmed_pct": 0.85,
                    "risk_class": "medium",
                    "reason_codes": ["LEAD_TIME_VARIABILITY"],
                    "category": "grocery",
                    "category_label": "Grocery",
                    "scope_count": 2,
                }
            ]
        ),
        "replenishment_exceptions": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-store-2",
                    "sku_id": "sku-2",
                    "channel_id": "store",
                    "exception_class": "cold_start_interval_unavailable",
                    "severity": "info",
                    "reason_code": "COLD_START_INTERVAL_UNCALIBRATED",
                    "evidence": "horizon 5 exceeds the calibrated maximum of 4",
                }
            ]
        ),
        "inventory_replay_metrics": stack(
            lambda market: [
                {
                    "market_id": market,
                    "metric": metric,
                    "cohort": cohort,
                    "candidate_value": "1.0000",
                    "incumbent_value": "2.0000",
                    "passed": True,
                }
                for metric in (
                    "stockoutPeriods",
                    "lostUnits",
                    "fillRate",
                    "meanInventoryUnits",
                )
                for cohort in ("calibration", "holdout")
            ]
        ),
        # One row per warehouse, not per snapshot date: the run publishes the
        # latest ceiling its origin admits, and the grain check rejects a second
        # row for the same node.
        "inventory_market_policy": stack(
            lambda market: [
                {
                    "market_id": market,
                    "weekly_replenishment_budget_minor": 23000000000,
                    "currency_code": "INR" if market == "india-west" else "USD",
                }
            ]
        ),
        "inventory_inbound_summary": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-dc-1",
                    "open_shipments": 4,
                    "open_units": 260,
                    "received_shipments": 40,
                    "late_shipments": 9,
                }
            ]
        ),
        "inventory_warehouse_capacity": stack(
            lambda market: [
                {
                    "market_id": market,
                    "location_id": f"{market}-dc-1",
                    "capacity_units": 750_000,
                    "snapshot_date": date(2026, 7, 28),
                }
            ]
        ),
    }
    # Nullable integers must stay integers: a float NaN written into a BIGINT
    # column is not the same absence the truth-table constraints are written for.
    for name, columns in (
        ("inventory_demand_at_risk", ("risk_value_minor",)),
        ("inventory_valuation", ("gross_value_minor", "wms_variance_units")),
        ("replenishment_recommendations", ("recommended_units",)),
    ):
        for column in columns:
            frames[name][column] = frames[name][column].astype("Int64")
    for name, frame in frames.items():
        frames[name] = frame[list(ARTIFACT_COLUMNS[name])]
    return frames


def _publish(tmp_path: Path, **overrides: Any):
    kwargs: dict[str, Any] = {
        "frames": _frames(),
        "markets": list(MARKETS),
        "decision_as_of": DECISION_AS_OF,
        "input_bundle": dict(INPUT_BUNDLE),
        "source_selection_id": SELECTION_ID,
        "forecast_authority": dict(FORECAST),
        "policy_fingerprints": dict(POLICY_FINGERPRINTS),
        "replay": json.loads(json.dumps(REPLAY)),
        "lane_coverage_pct": 100.0,
        "acceptance_passed": True,
        "execution_profile": "performance",
        "created_at": CREATED_AT,
    }
    kwargs.update(overrides)
    return publish_inventory_run(tmp_path / "bundle", **kwargs)


def _verify(root: Path, **overrides: Any):
    kwargs: dict[str, Any] = {
        "expected_pin": PIN,
        "active_selection_id": SELECTION_ID,
        "active_forecast": FORECAST,
    }
    kwargs.update(overrides)
    return verify_inventory_run(root, **kwargs)


# -- the happy path is the baseline every refusal is measured against ----------

def test_a_valid_bundle_publishes_and_independently_verifies(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    assert published.lifecycle_status == "accepted"
    assert published.inventory_run_id.startswith("ir_")

    verified = _verify(published.root)
    assert verified.inventory_run_id == published.inventory_run_id
    assert verified.semantic_fingerprint == published.semantic_fingerprint
    assert verified.markets == MARKETS
    assert set(verified.artifact_paths) == set(ARTIFACT_SCHEMAS)


def test_the_run_id_is_derived_so_the_same_evidence_is_the_same_run(
    tmp_path: Path,
) -> None:
    """Republishing identical evidence at a different wall-clock time must not
    mint a second run; that is what makes materialization idempotent."""

    first = _publish(tmp_path / "a")
    second = _publish(
        tmp_path / "b",
        created_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
        execution_profile="ultra-performance",
    )
    assert first.inventory_run_id == second.inventory_run_id
    assert first.semantic_fingerprint == second.semantic_fingerprint


def test_changed_lineage_mints_a_different_run(tmp_path: Path) -> None:
    baseline = _publish(tmp_path / "a")
    other = _publish(
        tmp_path / "b",
        source_selection_id="sel-2026-07-20-superseded",
    )
    assert baseline.inventory_run_id != other.inventory_run_id


# -- publisher refusals: structure --------------------------------------------

def test_a_partial_bundle_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    del frames["inventory_valuation"]
    with pytest.raises(InventoryPublicationError, match="omits required artifacts"):
        _publish(tmp_path, frames=frames)


def test_an_unknown_artifact_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["inventory_guesses"] = frames["inventory_positions"].copy()
    with pytest.raises(InventoryPublicationError, match="unknown artifacts"):
        _publish(tmp_path, frames=frames)


def test_a_duplicated_grain_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["inventory_positions"] = pd.concat(
        [frames["inventory_positions"], frames["inventory_positions"].head(1)],
        ignore_index=True,
    )
    with pytest.raises(InventoryPublicationError, match="duplicate the grain"):
        _publish(tmp_path, frames=frames)


def test_a_row_in_an_undeclared_market_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["inventory_positions"].loc[0, "market_id"] = "eu-central"
    with pytest.raises(InventoryPublicationError, match="eu-central"):
        _publish(tmp_path, frames=frames)


def test_a_position_that_is_neither_active_nor_residual_is_refused(
    tmp_path: Path,
) -> None:
    """The Cartesian guard. Emitting a cell nothing observed turns the store grain
    into a store x SKU cross join, and every coverage number stops meaning
    anything."""

    frames = _frames()
    frames["inventory_positions"].loc[1, "residual_only"] = False
    with pytest.raises(InventoryPublicationError, match="cross join"):
        _publish(tmp_path, frames=frames)


# -- publisher refusals: decision #92 ------------------------------------------

def test_a_withheld_interval_that_still_carries_a_value_is_refused(
    tmp_path: Path,
) -> None:
    frames = _frames()
    frames["inventory_demand_at_risk"].loc[1, "risk_units"] = 4.0
    with pytest.raises(
        InventoryPublicationError, match="interval_available disagrees"
    ):
        _publish(tmp_path, frames=frames)


def test_a_derived_value_surviving_a_withheld_interval_is_refused(
    tmp_path: Path,
) -> None:
    """The subtle one: the gated number is correctly absent, but a value DERIVED
    from it is still published, so the row asserts a currency exposure that has
    no interval behind it."""

    frames = _frames()
    frames["inventory_demand_at_risk"]["risk_value_minor"] = (
        frames["inventory_demand_at_risk"]["risk_value_minor"].fillna(999)
    )
    with pytest.raises(InventoryPublicationError, match="fabricated"):
        _publish(tmp_path, frames=frames)


def test_a_withheld_interval_with_no_reason_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["replenishment_safety_stock"].loc[1, "reason_code"] = None
    with pytest.raises(InventoryPublicationError, match="must name its reason"):
        _publish(tmp_path, frames=frames)


def test_an_ungoverned_interval_reason_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["replenishment_safety_stock"].loc[1, "reason_code"] = "MODEL_WAS_UNSURE"
    with pytest.raises(InventoryPublicationError, match="ungoverned interval"):
        _publish(tmp_path, frames=frames)


def test_an_available_interval_carrying_a_reason_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["inventory_demand_at_risk"].loc[
        0, "reason_code"
    ] = "COLD_START_INTERVAL_UNCALIBRATED"
    with pytest.raises(
        InventoryPublicationError, match="available interval carries a withholding"
    ):
        _publish(tmp_path, frames=frames)


def test_the_replay_reason_names_which_stage_withheld_it() -> None:
    """r3..r8 all published REPLAY_ORACLE_DID_NOT_REPRODUCE while their oracle had
    in fact reproduced -- one constant stood in for two unrelated causes, so the
    served reason was false on every bundle that ever activated."""

    from retail_ml.inventory_publish.run_artifacts import _replay_reason_code

    assert _replay_reason_code(acceptance_passed=True, oracle={"passed": True}) is None
    # Oracle reproduced, candidate did not strictly beat the incumbent. A governed
    # P4-D13 outcome, not a broken mechanism.
    assert (
        _replay_reason_code(acceptance_passed=False, oracle={"passed": True})
        == "REPLAY_NO_CANDIDATE_IMPROVEMENT"
    )
    # Oracle failed, so the comparison never earned the right to run.
    assert (
        _replay_reason_code(acceptance_passed=False, oracle={"passed": False})
        == "REPLAY_ORACLE_DID_NOT_REPRODUCE"
    )
    # No oracle at all cannot claim to have reproduced.
    assert (
        _replay_reason_code(acceptance_passed=False, oracle=None)
        == "REPLAY_ORACLE_DID_NOT_REPRODUCE"
    )


def test_a_reasoned_solver_refusal_publishes(tmp_path: Path) -> None:
    """0010 gates recommendations one-directionally -- `interval_available OR
    recommended_units IS NULL` -- while at-risk and safety stock use `=`. A
    recommended quantity is the output of a constrained solve that can refuse on
    its own terms with the interval perfectly intact, and that third state is
    legitimate. Applying the bidirectional rule here rejected rows the schema
    accepts."""

    frames = _frames()
    recommendations = frames["replenishment_recommendations"]
    available = recommendations.index[recommendations["interval_available"]][0]
    recommendations.loc[available, "recommended_units"] = None
    recommendations.loc[available, "reason_code"] = "MOQ_EXCEEDS_MAX_COVER"
    manifest = _publish(tmp_path, frames=frames)
    assert manifest is not None


def test_a_solver_refusal_with_no_reason_is_refused(tmp_path: Path) -> None:
    """The refusal is allowed; an unexplained one is not. Without a reason the
    screen prints an empty cell with nothing to account for it."""

    frames = _frames()
    recommendations = frames["replenishment_recommendations"]
    available = recommendations.index[recommendations["interval_available"]][0]
    recommendations.loc[available, "recommended_units"] = None
    with pytest.raises(InventoryPublicationError, match="absent without a reason"):
        _publish(tmp_path, frames=frames)


def test_an_ungoverned_solver_reason_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    recommendations = frames["replenishment_recommendations"]
    available = recommendations.index[recommendations["interval_available"]][0]
    recommendations.loc[available, "recommended_units"] = None
    recommendations.loc[available, "reason_code"] = "SOLVER_GAVE_UP"
    with pytest.raises(InventoryPublicationError, match="ungoverned solver"):
        _publish(tmp_path, frames=frames)


def test_safety_stock_still_obliges_a_value_when_its_interval_is_available(
    tmp_path: Path,
) -> None:
    """The relaxation is scoped to recommendations. Safety stock keeps `=`, so a
    missing value on an available interval stays a publication error."""

    frames = _frames()
    safety = frames["replenishment_safety_stock"]
    available = safety.index[safety["interval_available"]][0]
    safety.loc[available, "safety_stock_units"] = None
    with pytest.raises(
        InventoryPublicationError, match="interval_available disagrees"
    ):
        _publish(tmp_path, frames=frames)


def test_an_absent_value_with_no_named_reason_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["inventory_stock_health"].loc[1, "reason_code"] = None
    with pytest.raises(InventoryPublicationError, match="disagree on"):
        _publish(tmp_path, frames=frames)


# -- publisher refusals: frozen policy -----------------------------------------

def test_an_unknown_health_class_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["inventory_stock_health"].loc[0, "health_class"] = "fine_probably"
    with pytest.raises(InventoryPublicationError, match="unknown health classes"):
        _publish(tmp_path, frames=frames)


def test_a_recommendation_marked_sent_to_erp_is_refused(tmp_path: Path) -> None:
    frames = _frames()
    frames["replenishment_recommendations"].loc[0, "erp_status"] = "submitted"
    with pytest.raises(InventoryPublicationError, match="shadow-only"):
        _publish(tmp_path, frames=frames)


def test_a_market_without_a_resolved_policy_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InventoryPublicationError, match="no resolved policy"):
        _publish(tmp_path, policy_fingerprints={"india-west": "d" * 64})


def test_incomplete_lane_coverage_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InventoryPublicationError, match="lane coverage"):
        _publish(tmp_path, lane_coverage_pct=99.98)


def test_a_forecast_not_scored_under_the_hard_gate_is_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(InventoryPublicationError, match="hard"):
        _publish(
            tmp_path,
            forecast_authority={**FORECAST, "coverageGateMode": "soft"},
        )


def test_a_naive_decision_instant_is_refused(tmp_path: Path) -> None:
    with pytest.raises(InventoryPublicationError, match="timezone-aware"):
        _publish(tmp_path, decision_as_of=datetime(2026, 7, 27))


# -- publisher refusals: the replay --------------------------------------------

def test_a_failing_oracle_cannot_be_published(tmp_path: Path) -> None:
    replay = json.loads(json.dumps(REPLAY))
    replay["oracle"]["passed"] = False
    with pytest.raises(InventoryPublicationError, match="no standing"):
        _publish(tmp_path, replay=replay)


def test_a_tolerance_not_frozen_before_scoring_is_refused(tmp_path: Path) -> None:
    replay = json.loads(json.dumps(REPLAY))
    replay["oracleTolerance"]["frozenBeforeScoring"] = False
    with pytest.raises(InventoryPublicationError, match="is not a tolerance"):
        _publish(tmp_path, replay=replay)


def test_a_missing_incumbent_is_refused(tmp_path: Path) -> None:
    replay = json.loads(json.dumps(REPLAY))
    replay["incumbentPolicyId"] = ""
    with pytest.raises(InventoryPublicationError, match="not a baseline"):
        _publish(tmp_path, replay=replay)


def test_publishing_only_the_calibration_cohort_is_refused(tmp_path: Path) -> None:
    """A holdout that is never published is a holdout nobody can check."""

    frames = _frames()
    metrics = frames["inventory_replay_metrics"]
    frames["inventory_replay_metrics"] = metrics[
        metrics["cohort"] == "calibration"
    ].reset_index(drop=True)
    with pytest.raises(InventoryPublicationError, match="holdout"):
        _publish(tmp_path, frames=frames)


# -- verifier refusals: it must not trust the manifest -------------------------

def _rewrite_manifest(root: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    path = root / "inventory-run-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    mutate(manifest)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def test_a_tampered_artifact_fails_its_hash(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    target = published.root / "inventory_positions.parquet"
    frame = pd.read_parquet(target)
    frame.loc[0, "on_hand_units"] = 4000
    frame.to_parquet(target, index=False)
    with pytest.raises(InventoryVerificationError, match="hash mismatch|size mismatch"):
        _verify(published.root)


def test_an_artifact_path_outside_the_bundle_is_refused(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    _rewrite_manifest(
        published.root,
        lambda manifest: manifest["artifacts"]["inventory_positions"].update(
            {"path": "../inventory_positions.parquet"}
        ),
    )
    with pytest.raises(InventoryVerificationError, match="one local filename"):
        _verify(published.root)


def test_an_edited_manifest_field_breaks_the_run_fingerprint(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    _rewrite_manifest(
        published.root,
        lambda manifest: manifest["policy"].__setitem__(
            "resolvedFingerprints", {"india-west": "0" * 64, "us-new-york": "0" * 64}
        ),
    )
    with pytest.raises(
        InventoryVerificationError, match="fingerprint does not match its content"
    ):
        _verify(published.root)


def test_a_bundle_from_a_different_pin_is_refused(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    other_pin = json.loads(json.dumps(PIN))
    other_pin["publication"]["semanticFingerprint"] = "f" * 64
    with pytest.raises(
        InventoryVerificationError, match="does not match the committed pin"
    ):
        _verify(published.root, expected_pin=other_pin)


def test_a_bundle_whose_selection_is_no_longer_active_is_refused(
    tmp_path: Path,
) -> None:
    published = _publish(tmp_path)
    with pytest.raises(InventoryVerificationError, match="not authority"):
        _verify(published.root, active_selection_id="sel-2026-08-03-current")


def test_a_bundle_computed_from_a_superseded_forecast_is_refused(
    tmp_path: Path,
) -> None:
    published = _publish(tmp_path)
    with pytest.raises(InventoryVerificationError, match="is stale"):
        _verify(
            published.root,
            active_forecast={**FORECAST, "forecastVersionId": "fv_beefbeefbeefbeef"},
        )


def test_a_failed_replay_still_serves_current_state(tmp_path: Path) -> None:
    """The correction that made this bundle demoable at all.

    Twelve of the thirteen artifacts are current state and consume no replay, so
    an unreproducible replay must not withhold observed positions, ageing or
    valuation. It scopes ONE capability. The earlier design made the oracle a
    precondition for the whole bundle, which meant a network whose weekly stock
    could not be reconstructed served nothing -- not even its own stock levels.
    """

    frames = _frames()
    frames["inventory_replay_metrics"]["passed"] = False
    replay = json.loads(json.dumps(REPLAY))
    replay["oracle"] = {
        "passed": False,
        "reasonCode": "TOLERANCE_BREACHED",
        "perMarket": {
            market: {
                "passed": False,
                "measuredMeanAbsUnitDeltaPerCell": "13.84",
                "tolerancePerCell": "0.5",
            }
            for market in MARKETS
        },
    }
    published = _publish(tmp_path, frames=frames, replay=replay,
                         acceptance_passed=False)
    # Still accepted, and still verifiable: the current-state artifacts stand.
    assert published.lifecycle_status == "accepted"
    verified = _verify(published.root)

    capabilities = verified.manifest["capabilities"]
    assert capabilities["inventory_replenishment_current_snapshot"][
        "available"
    ] is True
    replay_capability = capabilities["inventory_replenishment_replay"]
    assert replay_capability["available"] is False
    assert replay_capability["reasonCode"] == "REPLAY_ORACLE_DID_NOT_REPRODUCE"
    # The measured oracle travels with the unavailability, so the claim is
    # auditable rather than asserted.
    assert replay_capability["oracle"]["passed"] is False


def test_a_run_claiming_the_replay_must_have_reproduced(tmp_path: Path) -> None:
    """Claiming the capability still requires the oracle. Only the coupling to
    the bundle's lifecycle was wrong, not the gate itself."""

    replay = json.loads(json.dumps(REPLAY))
    replay["oracle"]["passed"] = False
    with pytest.raises(InventoryPublicationError, match="no standing"):
        _publish(tmp_path, replay=replay, acceptance_passed=True)


def test_a_run_claiming_the_replay_may_not_publish_a_failing_gate(
    tmp_path: Path,
) -> None:
    frames = _frames()
    frames["inventory_replay_metrics"].loc[0, "passed"] = False
    published = _publish(tmp_path, frames=frames)
    with pytest.raises(
        InventoryVerificationError, match="claiming the replay capability"
    ):
        _verify(published.root)


def test_an_unavailable_replay_must_publish_the_evidence_for_it(
    tmp_path: Path,
) -> None:
    """An unavailability with no measured rows behind it is an assertion."""

    frames = _frames()
    frames["inventory_replay_metrics"]["passed"] = False
    replay = json.loads(json.dumps(REPLAY))
    replay["oracle"] = {
        "passed": False,
        "reasonCode": "TOLERANCE_BREACHED",
        "perMarket": {
            market: {
                "passed": False,
                "measuredMeanAbsUnitDeltaPerCell": "13.84",
                "tolerancePerCell": "0.5",
            }
            for market in MARKETS
        },
    }
    published = _publish(tmp_path, frames=frames, replay=replay,
                         acceptance_passed=False)
    metrics = published.root / "inventory_replay_metrics.parquet"
    pd.DataFrame(columns=list(ARTIFACT_COLUMNS["inventory_replay_metrics"])).to_parquet(
        metrics, index=False
    )
    with pytest.raises(InventoryVerificationError):
        _verify(published.root)


def test_an_unavailable_capability_with_a_passing_oracle_is_a_contradiction(
    tmp_path: Path,
) -> None:
    with pytest.raises(InventoryPublicationError, match="contradiction"):
        _publish(tmp_path, acceptance_passed=False)


def test_a_moved_interval_boundary_is_refused(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    _rewrite_manifest(
        published.root,
        lambda manifest: manifest["intervalAvailability"].__setitem__(
            "calibratedMaxHorizon", 26
        ),
    )
    # The fingerprint catches it first, which is the stronger refusal; the
    # boundary check exists for a bundle rebuilt around the changed value.
    with pytest.raises(InventoryVerificationError):
        _verify(published.root)


def test_a_swapped_acceptance_document_is_refused(tmp_path: Path) -> None:
    published = _publish(tmp_path)
    (published.root / "inventory-acceptance.json").write_text(
        json.dumps(
            {
                "schemaVersion": "retail-inventory-acceptance/v1",
                "passed": True,
                "replay": {"oracle": {"passed": True}},
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        InventoryVerificationError, match="does not match the fingerprint"
    ):
        _verify(published.root)
