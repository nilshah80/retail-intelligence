from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pandas as pd
import pytest
from retail_contracts.scenario_assumptions import load_scenario_assumption_bundle

from retail_ml.inventory_run.price_resolution import build_price_index
from retail_ml.scenario.context import (
    AssumptionApproval,
    ScenarioAuthority,
    ScenarioContextBuildError,
    build_base_context,
    build_inventory_extension,
)
from retail_ml.scenario.postgres import _inventory_identity_is_compatible


def _bundle() -> dict:
    bundle = deepcopy(load_scenario_assumption_bundle())
    bundle["assumptionSetId"] = "fsa_test_serving"
    bundle["version"] = "test-serving-1"
    bundle["artifactClass"] = "serving_candidate"
    bundle["servingEligible"] = True
    return bundle


def _forecast() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market_id": "synthetic-market",
                "sku_id": "sku1",
                "store_id": "store1",
                "channel_id": "store",
                "dept_id": "synthetic-dept",
                "category": "test",
                "horizon_week": horizon,
                "target_week_start": date(2026, 8, 10 + 7 * (horizon - 1)),
                "expected_units": 10.5 + horizon,
                "expected_model": "zero_inflated_expected_v1",
                "yhat_p50": 10 + horizon,
                "yhat_p90": 15 + horizon,
                "interval_available": True,
                "interval_unavailable_reason": None,
            }
            for horizon in (1, 2)
        ]
    )


def _prices(observed: date = date(2026, 8, 8)) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market_id": "synthetic-market",
                "location_id": "store1",
                "channel_id": "store",
                "sku_id": "sku1",
                "currency_code": "USD",
                "observation_date": observed,
                "known_as_of": datetime(2026, 8, 9, tzinfo=timezone.utc),
                "sales_version": 1,
                "unit_price_minor": 1000,
            }
        ]
    )


def _build(*, forecast: pd.DataFrame | None = None, observed: date = date(2026, 8, 8)):
    prices = _prices(observed)
    index = build_price_index(
        prices, source_cutoff=date(2026, 8, 10), require_provenance=True
    )
    return build_base_context(
        authority=ScenarioAuthority(
            retailer_id="retailer-test",
            tenant_id="tenant-test",
            capability="forecast_scenario_v1",
            environment="test",
        ),
        forecast_version_id="fv_test",
        forecast_activation_scope_fingerprint="a" * 64,
        scenario_decision_as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
        forecast_rows=_forecast() if forecast is None else forecast,
        price_index=index,
        price_history=prices,
        assumption_bundle=_bundle(),
        approval=AssumptionApproval(event_id=7, semantic_fingerprint="b" * 64),
    )


def test_base_context_is_complete_non_circular_and_order_stable() -> None:
    built = _build()
    reversed_rows = _forecast().iloc[::-1].reset_index(drop=True)
    reordered = _build(forecast=reversed_rows)
    assert built.scenario_context_version == reordered.scenario_context_version
    assert built.base_output_content_fingerprint == reordered.base_output_content_fingerprint
    assert len(built.horizon_rows) == 2
    assert len(built.commercial_rows) == 1
    assert built.manifest["scenarioContextVersion"] == built.scenario_context_version
    assert "scenarioContextVersion" not in {
        key
        for key in built.manifest
        if key in {
            "baseOutputContentFingerprint",
            "priceSnapshotContentFingerprint",
        }
    }


def test_commercial_row_carries_exact_price_support_and_tier_provenance() -> None:
    row = _build().commercial_rows[0]
    assert row["priceAvailable"] is True
    assert row["priceBasis"] == "latest_realized_exact"
    assert row["freshnessStatus"] == "fresh"
    assert row["observedSupportLowMinor"] == 1000
    assert row["baselinePriceTier"] == "entry"
    assert row["assumedBeta"] == "-1"
    assert row["sourceRowContentFingerprint"] is not None
    assert row["coefficientContentFingerprint"] is not None


def test_stale_price_keeps_lineage_but_does_not_resolve_a_tier() -> None:
    row = _build(observed=date(2026, 6, 1)).commercial_rows[0]
    assert row["priceAvailable"] is True
    assert row["sourceRowIdentity"] is not None
    assert row["freshnessStatus"] == "stale"
    assert row["baselinePriceTier"] is None
    assert row["tierResolutionReason"] == "PRICE_STALE"


def test_price_outside_support_window_is_unavailable_not_invalid_stale() -> None:
    row = _build(observed=date(2025, 1, 1)).commercial_rows[0]
    assert row["priceAvailable"] is True
    assert row["freshnessStatus"] == "unavailable"
    assert row["freshnessReasonCode"] == "PRICE_SUPPORT_UNAVAILABLE"
    assert row["observedSupportContentFingerprint"] is None
    assert row["tierResolutionReason"] == "PRICE_STALE"


def test_inventory_extension_identity_requires_forecast_and_cutoff() -> None:
    base = _build()
    matching = datetime(2026, 8, 10, tzinfo=timezone.utc)

    assert _inventory_identity_is_compatible(
        forecast_version_id="fv_test",
        inventory_decision_as_of=matching,
        base_context=base,
    )
    assert not _inventory_identity_is_compatible(
        forecast_version_id="fv_other",
        inventory_decision_as_of=matching,
        base_context=base,
    )
    assert not _inventory_identity_is_compatible(
        forecast_version_id="fv_test",
        inventory_decision_as_of=datetime(2026, 8, 9, tzinfo=timezone.utc),
        base_context=base,
    )


def test_synthetic_test_bundle_cannot_build_a_publishable_context() -> None:
    prices = _prices()
    with pytest.raises(ScenarioContextBuildError, match="serving_candidate"):
        build_base_context(
            authority=ScenarioAuthority(
                "retailer", "tenant", "forecast_scenario_v1", "test"
            ),
            forecast_version_id="fv_test",
            forecast_activation_scope_fingerprint="a" * 64,
            scenario_decision_as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
            forecast_rows=_forecast(),
            price_index=build_price_index(
                prices, source_cutoff=date(2026, 8, 10), require_provenance=True
            ),
            price_history=prices,
            assumption_bundle=load_scenario_assumption_bundle(),
            approval=AssumptionApproval(1, "b" * 64),
        )


def test_base_context_requires_an_unambiguous_decision_instant() -> None:
    prices = _prices()
    with pytest.raises(ScenarioContextBuildError, match="timezone-aware"):
        build_base_context(
            authority=ScenarioAuthority(
                "retailer", "tenant", "forecast_scenario_v1", "test"
            ),
            forecast_version_id="fv_test",
            forecast_activation_scope_fingerprint="a" * 64,
            scenario_decision_as_of=datetime(2026, 8, 10),
            forecast_rows=_forecast(),
            price_index=build_price_index(
                prices,
                source_cutoff=datetime(2026, 8, 10, tzinfo=timezone.utc),
                require_provenance=True,
            ),
            price_history=prices,
            assumption_bundle=_bundle(),
            approval=AssumptionApproval(1, "b" * 64),
        )


def test_base_context_refuses_cross_currency_support_history() -> None:
    prices = _prices()
    wrong_history = prices.copy()
    wrong_history.loc[0, "currency_code"] = "EUR"
    with pytest.raises(ScenarioContextBuildError, match="price support.*uses EUR"):
        build_base_context(
            authority=ScenarioAuthority(
                "retailer", "tenant", "forecast_scenario_v1", "test"
            ),
            forecast_version_id="fv_test",
            forecast_activation_scope_fingerprint="a" * 64,
            scenario_decision_as_of=datetime(2026, 8, 10, tzinfo=timezone.utc),
            forecast_rows=_forecast(),
            price_index=build_price_index(
                prices,
                source_cutoff=datetime(2026, 8, 10, tzinfo=timezone.utc),
                require_provenance=True,
            ),
            price_history=wrong_history,
            assumption_bundle=_bundle(),
            approval=AssumptionApproval(1, "b" * 64),
        )


def _inventory_frames():
    positions = pd.DataFrame(
        [{"market_id": "synthetic-market", "location_id": "store1", "sku_id": "sku1", "atp_units": 12}]
    )
    allocations = pd.DataFrame(
        [
            {"market_id": "synthetic-market", "location_id": "store1", "sku_id": "sku1", "channel_id": "store", "allocated_units": 7, "requested_units": 10},
            {"market_id": "synthetic-market", "location_id": "store1", "sku_id": "sku1", "channel_id": "online", "allocated_units": 2, "requested_units": 5},
        ]
    )
    recommendations = pd.DataFrame(
        [{"market_id": "synthetic-market", "destination_location_id": "store1", "sku_id": "sku1", "order_up_to_units": 20, "reorder_point_units": 15, "lead_time_days": 2, "interval_available": True, "reason_code": None}]
    )
    dimensions = pd.DataFrame(
        [{"market_id": "synthetic-market", "location_id": "store1", "sku_id": "sku1", "unit_cost_minor": 500, "cost_method": "store_wac", "currency_code": "USD"}]
    )
    return positions, allocations, recommendations, dimensions


def test_inventory_extension_stores_residual_once_and_is_order_stable() -> None:
    base = _build()
    positions, allocations, recommendations, dimensions = _inventory_frames()
    built = build_inventory_extension(
        base_context=base,
        inventory_version_id="iv_test",
        positions=positions,
        allocations=allocations,
        recommendations=recommendations,
        sku_dimensions=dimensions,
        review_period_days_by_market={"synthetic-market": 7},
        currency_by_market={"synthetic-market": "USD"},
    )
    reversed_built = build_inventory_extension(
        base_context=base,
        inventory_version_id="iv_test",
        positions=positions,
        allocations=allocations.iloc[::-1].reset_index(drop=True),
        recommendations=recommendations,
        sku_dimensions=dimensions,
        review_period_days_by_market={"synthetic-market": 7},
        currency_by_market={"synthetic-market": "USD"},
    )
    assert built.inventory_extension_version == reversed_built.inventory_extension_version
    assert len(built.series_rows) == 2
    node = built.node_rows[0]
    assert node["nodeAtpUnits"] == 12
    assert node["allocatedAtpUnits"] == 9
    assert node["residualAtpUnits"] == 3
    assert node["orderUpToUnits"] == "20"
    assert node["protectionDays"] == "9"
    assert node["unitCostContentFingerprint"] is not None


def test_inventory_extension_refuses_overallocated_atp() -> None:
    positions, allocations, recommendations, dimensions = _inventory_frames()
    allocations.loc[1, "allocated_units"] = 6
    with pytest.raises(ScenarioContextBuildError, match="ATP conservation"):
        build_inventory_extension(
            base_context=_build(),
            inventory_version_id="iv_test",
            positions=positions,
            allocations=allocations,
            recommendations=recommendations,
            sku_dimensions=dimensions,
            review_period_days_by_market={"synthetic-market": 7},
            currency_by_market={"synthetic-market": "USD"},
        )


def test_inventory_extension_materializes_governed_zero_channel_allocation() -> None:
    positions, allocations, recommendations, dimensions = _inventory_frames()
    allocations = allocations.loc[allocations["channel_id"] == "online"].copy()
    built = build_inventory_extension(
        base_context=_build(),
        inventory_version_id="iv_test",
        positions=positions,
        allocations=allocations,
        recommendations=recommendations,
        sku_dimensions=dimensions,
        review_period_days_by_market={"synthetic-market": 7},
        currency_by_market={"synthetic-market": "USD"},
    )
    store = next(row for row in built.series_rows if row["channelId"] == "store")
    assert store["allocatedAtpUnits"] == 0
    assert store["requestedUnits"] == 0
    assert built.node_rows[0]["allocatedAtpUnits"] == 2
    assert built.node_rows[0]["residualAtpUnits"] == 10
