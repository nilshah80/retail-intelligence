import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from retail_ml.pricing.build import (
    PricingBuildError,
    load_forecast_context,
    load_inventory_context,
)
from retail_ml.pricing.panel import build_weekly_panel


def test_weekly_panel_carries_visible_price_across_closed_assortment_weeks(
    tmp_path,
) -> None:
    database = tmp_path / "curated.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA canonical_data")
        connection.execute(
            """
            CREATE TABLE canonical_data.sell_prices (
                sku_id VARCHAR, store_id VARCHAR, channel_id VARCHAR,
                week_start DATE, net_price BIGINT, regular_price BIGINT,
                promo_price BIGINT, currency_code VARCHAR,
                source_price_path_id VARCHAR, known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.sales (
                sku_id VARCHAR, store_id VARCHAR, channel_id VARCHAR,
                date DATE, units BIGINT, net_sales_amount BIGINT,
                promo_flag BOOLEAN, known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.store_shortfall_events (
                event_id VARCHAR, sku_id VARCHAR, location_id VARCHAR,
                supply_location_id VARCHAR, channel_id VARCHAR,
                event_date DATE, demand_units BIGINT, served_units BIGINT,
                shortfall_units BIGINT, known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.stores (
                store_id VARCHAR, market_id VARCHAR, region VARCHAR,
                currency_code VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.products (
                sku_id VARCHAR, dept_id VARCHAR, category VARCHAR,
                product_name VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.channels (
                market_id VARCHAR, channel_id VARCHAR, type VARCHAR
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE canonical_data.assortment_calendar (
                sku_id VARCHAR, store_id VARCHAR, channel_id VARCHAR,
                active_from DATE, active_to DATE, derivation_method VARCHAR,
                known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO canonical_data.sell_prices VALUES
              ('sku-1', 'store-1', 'store', DATE '2026-07-13',
               20500, 21000, NULL, 'INR', 'price-1',
               TIMESTAMPTZ '2026-07-13T12:00:00Z', 'source_timestamp')
            """
        )
        connection.execute(
            """
            INSERT INTO canonical_data.sales VALUES
              ('sku-1', 'store-1', 'store', DATE '2026-07-23',
               3, 61500, FALSE,
               TIMESTAMPTZ '2026-07-23T13:00:00Z', 'source_timestamp')
            """
        )
        connection.execute(
            "INSERT INTO canonical_data.stores VALUES "
            "('store-1', 'gulf-india', 'West', 'INR')"
        )
        connection.execute(
            "INSERT INTO canonical_data.products VALUES "
            "('sku-1', 'lubricants', 'Engine Oil', 'Product')"
        )
        connection.execute(
            "INSERT INTO canonical_data.channels VALUES "
            "('gulf-india', 'store', 'Retail')"
        )
        connection.execute(
            """
            INSERT INTO canonical_data.assortment_calendar VALUES
              ('sku-1', 'store-1', 'store', DATE '2026-07-13',
               DATE '2026-07-31', 'source',
               TIMESTAMPTZ '2026-07-13T00:00:00Z', 'source_timestamp')
            """
        )

    panel = build_weekly_panel(
        database,
        decision_as_of="2026-07-31T18:30:00Z",
    )

    assert list(panel["week_start"].dt.strftime("%Y-%m-%d")) == [
        "2026-07-13",
        "2026-07-20",
    ]
    assert panel.iloc[-1]["channel_id"] == "store"
    assert panel.iloc[-1]["regular_price_minor"] == 21000
    assert panel.iloc[-1]["units"] == 3
    assert panel.iloc[-1]["store_shortfall_units"] == 0
    assert panel.iloc[-1]["store_shortfall_share"] == 0
    assert panel.iloc[-1]["channel_type"] == "Retail"


def _forecast_frame(*, horizons=(1, 2, 3, 4), versions=("fv_0123456789abcdef",)):
    rows = []
    for horizon in horizons:
        rows.append(
            {
                "sku_id": "india-west:sku-1",
                "store_id": "india-west:store-1",
                "channel_id": "store",
                "horizon_week": horizon,
                "version_id": versions[(horizon - 1) % len(versions)],
                "expected_units": 10.0 + horizon,
                "yhat_p50": 9.0 + horizon,
                "yhat_p90": 12.0 + horizon,
                "confidence": 0.9 - horizon / 100,
            }
        )
    return pd.DataFrame(rows)


def _verified():
    return SimpleNamespace(
        lifecycle_status="accepted",
        artifact_paths={"forecast_series": "forecast-series.parquet"},
        forecast_run_id="fr_0123456789abcdef",
        semantic_fingerprint="a" * 64,
    )


def test_four_week_context_sums_additive_volume_and_labels_planning_bounds(
    monkeypatch,
) -> None:
    monkeypatch.setattr("retail_ml.pricing.build.verify_forecast_run", lambda _: _verified())
    monkeypatch.setattr("retail_ml.pricing.build.pd.read_parquet", lambda _: _forecast_frame())

    context, lineage = load_forecast_context("accepted-run")

    assert len(context) == 1
    row = context.iloc[0]
    assert row["expected_units"] == pytest.approx(sum(10 + h for h in (1, 2, 3, 4)))
    assert row["best_case_units"] == pytest.approx(sum(12 + h for h in (1, 2, 3, 4)))
    assert row["worst_case_units"] == pytest.approx(sum(6 + h for h in (1, 2, 3, 4)))
    assert pd.isna(row["yhat_p50"]) and pd.isna(row["yhat_p90"])
    assert row["forecast_horizon_weeks"] == 4
    assert row["forecast_scenario_semantics"] == (
        "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
    )
    assert lineage == {
        "forecastRunId": "fr_0123456789abcdef",
        "forecastSemanticFingerprint": "a" * 64,
    }


def test_four_week_context_withholds_incomplete_series(monkeypatch) -> None:
    monkeypatch.setattr("retail_ml.pricing.build.verify_forecast_run", lambda _: _verified())
    monkeypatch.setattr(
        "retail_ml.pricing.build.pd.read_parquet",
        lambda _: _forecast_frame(horizons=(1, 2, 3)),
    )
    context, _ = load_forecast_context("accepted-run")
    assert context.empty


def test_four_week_context_refuses_mixed_forecast_versions(monkeypatch) -> None:
    monkeypatch.setattr("retail_ml.pricing.build.verify_forecast_run", lambda _: _verified())
    monkeypatch.setattr(
        "retail_ml.pricing.build.pd.read_parquet",
        lambda _: _forecast_frame(versions=("fv_0123456789abcdef", "fv_fedcba9876543210")),
    )
    with pytest.raises(PricingBuildError, match="multiple versions"):
        load_forecast_context("accepted-run")


def _inventory_frames():
    return {
        "inventory_positions.parquet": pd.DataFrame([{
            "market_id": "india-west", "location_id": "store-1",
            "location_kind": "store", "sku_id": "sku-1", "atp_units": 12,
        }]),
        "inventory_sku_dimension.parquet": pd.DataFrame([{
            "market_id": "india-west", "location_id": "store-1",
            "location_kind": "store", "sku_id": "sku-1",
            "unit_cost_minor": 1234, "cost_method": "computed_wac",
            "currency_code": "INR", "product_name": "Product",
            "category": "Engine Oil",
        }]),
        "inventory_stock_health.parquet": pd.DataFrame([{
            "market_id": "india-west", "location_id": "store-1",
            "sku_id": "sku-1", "health_class": "healthy", "cover_days": 20.0,
        }]),
        "inventory_ageing.parquet": pd.DataFrame([{
            "market_id": "india-west", "location_id": "store-1", "sku_id": "sku-1",
        }]),
    }


def test_inventory_context_uses_manifest_cutoff_as_synthetic_cost_as_of(
    tmp_path, monkeypatch,
) -> None:
    artifacts = {
        name.removesuffix(".parquet"): {"path": name, "sha256": "a" * 64}
        for name in _inventory_frames()
    }
    manifest = {
        "decisionAsOf": "2026-07-31T00:00:00+00:00",
        "inventoryRunId": "ir_0123456789abcdef",
        "semanticFingerprint": "b" * 64,
        "capabilities": {
            "inventory_replenishment_current_snapshot": {"available": True}
        },
        "artifacts": artifacts,
    }
    (tmp_path / "inventory-run-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    monkeypatch.setattr(
        "retail_ml.pricing.build._safe_artifact",
        lambda _root, record: Path(record["path"]),
    )
    frames = _inventory_frames()
    monkeypatch.setattr(
        "retail_ml.pricing.build.pd.read_parquet",
        lambda path: frames[path.name].copy(),
    )

    context, lineage = load_inventory_context(tmp_path)

    assert context.iloc[0]["cost_as_of"] == "2026-07-31T00:00:00+00:00"
    assert context.iloc[0]["synthetic_cost_method"] == "computed_wac"
    assert context.iloc[0]["synthetic_cost_minor"] == 1234
    assert lineage == {
        "inventoryRunId": "ir_0123456789abcdef",
        "inventorySemanticFingerprint": "b" * 64,
    }
