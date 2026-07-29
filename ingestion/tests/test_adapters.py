"""Adapter/reader boundary tests independent of canonical transformations."""

from __future__ import annotations

from pathlib import Path

import duckdb

from retail_ingestion.adapters import AdapterContext, adapter_for, registered_adapters
from retail_ingestion.profiles import load_source_profile
from retail_ingestion.readers import PublicSourceCatalog

from .test_gate_a import _land_fixture, _write_profile


def test_registry_has_source_semantic_not_format_adapters() -> None:
    assert registered_adapters() == ("businessCentral", "companion", "shopify")
    assert adapter_for("shopify").adapter_version.startswith("shopify-adapter/")


def test_shopify_adapter_reads_declared_csv_through_shared_reader(
    tmp_path: Path,
) -> None:
    snapshot = _land_fixture(
        tmp_path, ["order-1", "order-2"], order_format="csv"
    )
    profile = load_source_profile(
        _write_profile(tmp_path / "profile.yaml", order_format="csv")
    )
    catalog = PublicSourceCatalog.from_snapshot(snapshot, profile)
    connection = duckdb.connect(":memory:")
    try:
        catalog.register_metadata(connection)
        context = AdapterContext(connection, catalog, profile)
        created = adapter_for("shopify").register_raw_views(context)
        assert created == ("raw_shopify.orders",)
        assert connection.execute(
            "SELECT count(*) FROM raw_shopify.orders"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT DISTINCT _market_id FROM raw_shopify.orders"
        ).fetchone()[0] == "fixture-market"
    finally:
        connection.close()


def test_catalog_never_exposes_restricted_lanes(tmp_path: Path) -> None:
    snapshot = _land_fixture(tmp_path, ["order-1"])
    profile = load_source_profile(_write_profile(tmp_path / "profile.yaml"))
    catalog = PublicSourceCatalog.from_snapshot(snapshot, profile)

    assert catalog.objects
    assert all(
        row.file_path.is_relative_to(snapshot / "public")
        for row in catalog.objects
    )


def test_shopify_adapter_reads_declared_jsonl_through_shared_reader(
    tmp_path: Path,
) -> None:
    snapshot = _land_fixture(
        tmp_path, ["order-1", "order-2"], order_format="jsonl"
    )
    profile = load_source_profile(
        _write_profile(tmp_path / "profile.yaml", order_format="jsonl")
    )
    catalog = PublicSourceCatalog.from_snapshot(snapshot, profile)
    connection = duckdb.connect(":memory:")
    try:
        catalog.register_metadata(connection)
        context = AdapterContext(connection, catalog, profile)
        adapter_for("shopify").register_raw_views(context)
        assert connection.execute(
            "SELECT count(*) FROM raw_shopify.orders"
        ).fetchone()[0] == 2
    finally:
        connection.close()
