"""Adapter/reader boundary tests independent of canonical transformations."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

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


def test_companion_adapter_emits_generic_dimension_signal_envelope() -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute("CREATE SCHEMA raw_companion")
        connection.execute(
            """
            CREATE TABLE raw_companion.holidays (
                date VARCHAR,
                kind VARCHAR,
                marketKey VARCHAR,
                name VARCHAR,
                retailBehavior VARCHAR,
                targetId VARCHAR,
                targetType VARCHAR,
                _source_instance VARCHAR,
                _market_id VARCHAR,
                _market_currency_code VARCHAR,
                _business_timezone VARCHAR,
                _raw_object_hash VARCHAR,
                _raw_object_path VARCHAR
            )
            """
        )
        connection.execute(
            """
            INSERT INTO raw_companion.holidays VALUES (
                '2026-01-26', 'PUBLIC_HOLIDAY', 'india',
                'Republic Day', 'CLOSED', 'india', 'market',
                'calendar-in', 'india', 'INR', 'Asia/Kolkata',
                'object-hash', 'companion/india/holidays.parquet'
            )
            """
        )
        reference = SimpleNamespace(
            artifact_format="parquet",
            dataset="holidays",
        )
        catalog = SimpleNamespace(
            landing_manifest={
                "sourceSnapshotId": "snapshot-1",
                "nativeSnapshotId": "source-run-1",
                "landingTime": "2026-02-01T00:00:00Z",
            },
            for_source=lambda source_system: (
                (reference,) if source_system == "companion" else ()
            ),
        )
        context = AdapterContext(
            connection=connection,
            catalog=catalog,
            profile={
                "sourceSchemaVersion": "source/v1",
                "profileVersion": "profile/v1",
            },
        )

        created = adapter_for("companion").materialize_staging(context)

        assert "stage_data.companion_dimension_signal" in created
        row = connection.execute(
            """
            SELECT
                entity_kind,
                natural_key,
                cast(effective_at AS DATE),
                payload->>'name',
                geo_scope_type,
                geo_scope_id,
                length(native_record_id)
            FROM stage_data.companion_dimension_signal
            """
        ).fetchone()
        assert row == (
            "holidays",
            "calendar-in|holidays|2026-01-26|Republic Day|market|india",
            date(2026, 1, 26),
            "Republic Day",
            "market",
            "india",
            64,
        )
    finally:
        connection.close()


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
