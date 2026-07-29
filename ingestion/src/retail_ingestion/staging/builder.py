"""Build a versioned standardized-staging DuckDB atomically."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import duckdb
from retail_contracts.fingerprint import semantic_fingerprint

from retail_ingestion.adapters import AdapterContext, adapter_for, registered_adapters
from retail_ingestion.mappings import build_location_crosswalk
from retail_ingestion.profiles import load_source_profile
from retail_ingestion.readers import PublicSourceCatalog

STAGING_MANIFEST_VERSION = "retail-ingestion-staging/v1"


class StagingError(RuntimeError):
    """Standardized staging could not be built safely."""


@dataclass(frozen=True)
class StagingResult:
    staging_database: Path
    staging_manifest: Path
    source_snapshot_id: str
    table_counts: Mapping[str, int]
    quarantine_rows: int
    semantic_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": STAGING_MANIFEST_VERSION,
            "stagingDatabase": str(self.staging_database),
            "stagingManifest": str(self.staging_manifest),
            "sourceSnapshotId": self.source_snapshot_id,
            "tableCounts": dict(self.table_counts),
            "quarantineRows": self.quarantine_rows,
            "semanticFingerprint": self.semantic_fingerprint,
        }


def _table_count(
    connection: duckdb.DuckDBPyConnection, qualified_name: str
) -> int:
    return int(connection.execute(f"SELECT count(*) FROM {qualified_name}").fetchone()[0])


def _build_quarantine(connection: duckdb.DuckDBPyConnection) -> int:
    connection.execute(
        """
        CREATE OR REPLACE TABLE stage_data.adapter_quarantine (
            source_system VARCHAR NOT NULL,
            source_instance VARCHAR NOT NULL,
            dataset VARCHAR NOT NULL,
            native_record_id VARCHAR,
            reason_code VARCHAR NOT NULL,
            raw_object_path VARCHAR,
            payload_hash VARCHAR
        )
        """
    )
    checks = (
        (
            "stage_data.shopify_merchandise",
            "shopify_merchandise",
            "native_record_id IS NULL OR sku_source_key IS NULL "
            "OR demand_location_source_key IS NULL OR channel_source_key IS NULL "
            "OR business_date IS NULL OR units IS NULL OR units < 0 "
            "OR net_amount_major IS NULL OR currency_code IS NULL "
            "OR known_as_of IS NULL",
            "INVALID_MERCHANDISE_ROW",
        ),
        (
            "stage_data.shopify_products",
            "shopify_products",
            "native_record_id IS NULL OR sku_source_key IS NULL "
            "OR product_name IS NULL OR known_as_of IS NULL",
            "INVALID_PRODUCT_ROW",
        ),
        (
            "stage_data.shopify_locations",
            "shopify_locations",
            "native_record_id IS NULL OR location_source_key IS NULL "
            "OR market_id IS NULL OR currency_code IS NULL OR timezone IS NULL",
            "INVALID_LOCATION_ROW",
        ),
        (
            "stage_data.shopify_prices",
            "shopify_prices",
            "native_record_id IS NULL OR sku_source_key IS NULL "
            "OR effective_date IS NULL OR price_major IS NULL "
            "OR price_major <= 0 OR currency_code IS NULL",
            "INVALID_PRICE_ROW",
        ),
        (
            "stage_data.shopify_fulfillment",
            "shopify_fulfillment",
            "native_record_id IS NULL OR source_sale_id IS NULL "
            "OR sku_source_key IS NULL OR units IS NULL OR units < 0 "
            "OR fulfilled_at IS NULL",
            "INVALID_FULFILLMENT_ROW",
        ),
        (
            "stage_data.bc_inventory",
            "bc_inventory",
            "native_record_id IS NULL OR sku_source_key IS NULL "
            "OR location_source_key IS NULL OR snapshot_date IS NULL "
            "OR on_hand_units IS NULL OR known_as_of IS NULL",
            "INVALID_INVENTORY_ROW",
        ),
        (
            "stage_data.bc_receipts",
            "bc_receipts",
            "native_record_id IS NULL OR sku_source_key IS NULL "
            "OR location_source_key IS NULL OR receipt_date IS NULL "
            "OR qty IS NULL OR unit_cost_major IS NULL OR currency_code IS NULL",
            "INVALID_RECEIPT_ROW",
        ),
    )
    for table, dataset, predicate, reason in checks:
        connection.execute(
            f"""
            INSERT INTO stage_data.adapter_quarantine
            SELECT
                source_system,
                source_instance,
                '{dataset}',
                native_record_id,
                '{reason}',
                raw_object_path,
                sha256(
                    coalesce(native_record_id, '') || ':' ||
                    coalesce(raw_object_path, '')
                )
            FROM {table}
            WHERE {predicate}
            """
        )
        connection.execute(f"DELETE FROM {table} WHERE {predicate}")
    return _table_count(connection, "stage_data.adapter_quarantine")


def _create_standardized_views(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[str, ...]:
    """Expose the only relations source-neutral transformations may import."""

    direct = {
        "merchandise": "shopify_merchandise",
        "adjustment": "shopify_adjustment",
        "fulfillment": "shopify_fulfillment",
        "inventory": "bc_inventory",
        "receipt": "bc_receipts",
        "products": "shopify_products",
        "product_references": "bc_products",
        "locations": "shopify_locations",
        "prices": "shopify_prices",
        "supplier_terms": "bc_supplier_terms",
        "sales_control": "bc_sales_control",
        "customer_segment_counts": "shopify_customer_segment_counts",
        "inventory_cost": "bc_inventory_cost",
        "inventory_batches": "bc_inventory_batches",
        "inbound_shipments": "bc_inbound_shipments",
        "transfer_orders": "bc_transfer_orders",
        "waste_events": "bc_waste_events",
        "warehouse_capacity": "bc_warehouse_capacity",
        "wms_comparisons": "bc_wms_comparisons",
        "supplier_performance": "bc_supplier_performance",
    }
    for target, source in direct.items():
        connection.execute(
            f"CREATE OR REPLACE VIEW stage_data.{target} AS "
            f"SELECT * FROM stage_data.{source}"
        )

    statements = {
        "store_assortment": """
            SELECT
                source_system, source_instance, source_schema_version,
                source_snapshot_id, native_snapshot_id, market_id, known_as_of,
                evidence_grade, row_provenance, raw_object_hash, profile_version,
                adapter_version, sku::VARCHAR AS sku_source_key,
                storeKey::VARCHAR AS demand_location_source_key,
                validFrom::VARCHAR AS active_from_raw,
                validTo::VARCHAR AS active_to_raw,
                active::VARCHAR AS active_raw,
                assortmentReason::VARCHAR AS derivation_method,
                raw_object_path
            FROM stage_data.companion_store_assortment
        """,
        "holidays": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                date::VARCHAR AS date_raw, name::VARCHAR AS event_name,
                kind::VARCHAR AS event_type, targetType::VARCHAR AS geo_scope_type,
                targetId::VARCHAR AS geo_scope_id, retailBehavior::VARCHAR
                    AS retail_behavior, raw_object_hash, raw_object_path
            FROM stage_data.companion_holidays
        """,
        "fx_rates": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                baseCurrency::VARCHAR AS base_ccy,
                quoteCurrency::VARCHAR AS quote_ccy,
                quotePerBase::VARCHAR AS rate_raw,
                rateDate::VARCHAR AS rate_date_raw,
                rateType::VARCHAR AS rate_type,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_fx_rates
        """,
        "market_disruptions": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                pandemicId::VARCHAR AS disruption_id,
                phaseId::VARCHAR AS phase_id,
                startDate::VARCHAR AS start_date_raw,
                endDate::VARCHAR AS end_date_raw,
                demandMultiplier::VARCHAR AS demand_factor_raw,
                trafficMultiplier::VARCHAR AS traffic_factor_raw,
                leadTimeMultiplier::VARCHAR AS supply_factor_raw,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_pandemic_timeline
        """,
        "customer_segments": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                segmentId::VARCHAR AS segment_id, name::VARCHAR AS name,
                scenarioShare::VARCHAR AS share_raw,
                demandMultiplier::VARCHAR AS demand_multiplier_raw,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_customer_segments
        """,
        "weather_actual": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                targetType::VARCHAR AS geo_scope_type,
                targetId::VARCHAR AS geo_scope_id,
                validDate::VARCHAR AS date_raw,
                temperatureC::VARCHAR AS temperature_raw,
                precipitationMm::VARCHAR AS precipitation_raw,
                condition::VARCHAR AS weather_code,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_weather_actuals
        """,
        "weather_forecast": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                targetType::VARCHAR AS geo_scope_type,
                targetId::VARCHAR AS geo_scope_id,
                issuedAt::VARCHAR AS forecast_date_raw,
                validDate::VARCHAR AS target_date_raw,
                temperatureC::VARCHAR AS temperature_raw,
                precipitationMm::VARCHAR AS precipitation_raw,
                provider::VARCHAR AS provider,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_weather_forecasts
        """,
        "local_events": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                targetType::VARCHAR AS geo_scope_type,
                targetId::VARCHAR AS geo_scope_id,
                startDate::VARCHAR AS start_date_raw,
                endDate::VARCHAR AS end_date_raw,
                name::VARCHAR AS event_name, type::VARCHAR AS event_type,
                demandMultiplier::VARCHAR AS expected_impact_raw,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_local_events
        """,
        "macro_index": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                targetType::VARCHAR AS geo_scope_type,
                targetId::VARCHAR AS geo_scope_id,
                validDate::VARCHAR AS valid_date_raw,
                indexName::VARCHAR AS index_name,
                indexValue::VARCHAR AS value_raw,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_macro_index
        """,
        "competitor_prices": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                competitorId::VARCHAR AS competitor_id,
                competitorSku::VARCHAR AS competitor_product_id,
                competitorProductTitle::VARCHAR AS competitor_product_title,
                targetType::VARCHAR AS geo_scope_type,
                targetId::VARCHAR AS geo_scope_id,
                observedAt::VARCHAR AS observed_at_raw,
                price::VARCHAR AS price_raw,
                currencyCode::VARCHAR AS currency_code,
                available::VARCHAR AS available_raw,
                promotionText::VARCHAR AS promotion_text,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_competitor_prices
        """,
        "competitor_matches": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                matchKey::VARCHAR AS match_id,
                ourSku::VARCHAR AS sku_source_key,
                competitorId::VARCHAR AS competitor_id,
                competitorSku::VARCHAR AS competitor_product_id,
                matchConfidence::VARCHAR AS confidence_raw,
                matchMethod::VARCHAR AS match_method,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_competitor_matches
        """,
        "promotions": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                promotionId::VARCHAR AS promotion_id, name::VARCHAR AS name,
                promotionType::VARCHAR AS promotion_type,
                startDate::VARCHAR AS start_date_raw,
                endDate::VARCHAR AS end_date_raw,
                discountPct::VARCHAR AS discount_pct_raw,
                discountBasis::VARCHAR AS discount_basis,
                customerSegmentIds::VARCHAR AS segment_ids,
                storeIds::VARCHAR AS store_ids,
                channelIds::VARCHAR AS channel_ids,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_promotions
        """,
        "promotion_targets": """
            SELECT
                market_id, known_as_of, evidence_grade, row_provenance,
                promotionId::VARCHAR AS promotion_id,
                CASE
                    WHEN nullif(sku, '') IS NOT NULL THEN 'sku'
                    WHEN nullif(departmentId, '') IS NOT NULL THEN 'dept'
                    ELSE 'category'
                END::VARCHAR AS merch_scope_type,
                coalesce(nullif(sku, ''), nullif(departmentId, ''), categoryId)
                    ::VARCHAR AS merch_scope_id,
                discountPct::VARCHAR AS discount_pct_raw,
                raw_object_hash, raw_object_path
            FROM stage_data.companion_promotion_skus
        """,
        "allocations": """
            SELECT
                source_instance, market_id,
                requestKey::VARCHAR AS allocation_id,
                sku::VARCHAR AS sku_source_key,
                storeKey::VARCHAR AS location_source_key,
                try_cast(requestedQuantity AS BIGINT) AS requested_qty,
                try_cast(allocatedQuantity AS BIGINT) AS allocated_qty,
                try_cast(unallocatedQuantity AS BIGINT) AS shortfall,
                warehousePriority::VARCHAR AS priority,
                status::VARCHAR AS status,
                known_as_of, evidence_grade
            FROM stage_data.companion_allocation_demand_requests
        """,
    }
    for name, select_sql in statements.items():
        connection.execute(
            f"CREATE OR REPLACE VIEW stage_data.{name} AS {select_sql}"
        )
    return tuple(
        f"stage_data.{name}" for name in (*direct, *statements)
    )


def build_staging(
    snapshot_root: str | Path,
    profile_path: str | Path,
    output_database: str | Path,
    *,
    execution_profile: Mapping[str, Any],
) -> StagingResult:
    """Materialize all registered source adapters into one atomic staging DB."""

    destination = Path(output_database).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.staging-{uuid.uuid4().hex}"
    )
    temporary_manifest = temporary.with_suffix(temporary.suffix + ".manifest.json")
    final_manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    profile = load_source_profile(profile_path)
    catalog = PublicSourceCatalog.from_snapshot(snapshot_root, profile)
    connection: duckdb.DuckDBPyConnection | None = None
    try:
        connection = duckdb.connect(str(temporary))
        threads = max(1, int(execution_profile["duckdbThreads"]))
        memory = max(1, int(execution_profile["memoryLimitGb"]))
        connection.execute(f"SET threads = {threads}")
        connection.execute(f"SET memory_limit = '{memory}GB'")
        catalog.register_metadata(connection)
        context = AdapterContext(connection=connection, catalog=catalog, profile=profile)
        raw_views: list[str] = []
        staged_tables: list[str] = []
        adapter_versions: dict[str, str] = {}
        for source_system in registered_adapters():
            if not catalog.for_source(source_system):
                continue
            adapter = adapter_for(source_system)
            raw_views.extend(adapter.register_raw_views(context))
            staged_tables.extend(adapter.materialize_staging(context))
            adapter_versions[source_system] = adapter.adapter_version
        standardized_views = _create_standardized_views(connection)
        crosswalk_rows = build_location_crosswalk(connection, catalog)
        quarantine_rows = _build_quarantine(connection)
        table_counts = {
            name: _table_count(connection, name)
            for name in sorted(
                (
                    *staged_tables,
                    *standardized_views,
                    "stage_data.adapter_quarantine",
                )
            )
        }
        connection.execute("CHECKPOINT")
        connection.close()
        connection = None

        db_hash = hashlib.sha256()
        with temporary.open("rb") as reader:
            while chunk := reader.read(1024 * 1024):
                db_hash.update(chunk)
        manifest: dict[str, Any] = {
            "schemaVersion": STAGING_MANIFEST_VERSION,
            "sourceSnapshotId": catalog.landing_manifest["sourceSnapshotId"],
            "nativeSnapshotId": catalog.landing_manifest.get("nativeSnapshotId"),
            "upstreamManifestSha256": catalog.landing_manifest[
                "upstreamManifest"
            ]["sha256"],
            "landingSemanticFingerprint": catalog.landing_manifest[
                "semanticFingerprint"
            ],
            "extractBoundary": catalog.landing_manifest.get("extractBoundary"),
            "landingTime": catalog.landing_manifest.get("landingTime"),
            "profileId": profile["profileId"],
            "profileVersion": profile["profileVersion"],
            "sourceSchemaVersion": profile["sourceSchemaVersion"],
            "adapterVersions": adapter_versions,
            "rawViews": sorted(raw_views),
            "stagingTables": sorted(staged_tables),
            "standardizedViews": sorted(standardized_views),
            "tableCounts": table_counts,
            "quarantineRows": quarantine_rows,
            "locationCrosswalkRows": crosswalk_rows,
            "databaseSha256": db_hash.hexdigest(),
            "completedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "executionProfile": dict(execution_profile),
        }
        manifest["semanticFingerprint"] = semantic_fingerprint(
            manifest,
            volatile_pointers=(
                "/completedAt",
                "/executionProfile",
                "/databaseSha256",
            ),
        )
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, destination)
        os.replace(temporary_manifest, final_manifest)
        return StagingResult(
            staging_database=destination,
            staging_manifest=final_manifest,
            source_snapshot_id=manifest["sourceSnapshotId"],
            table_counts=table_counts,
            quarantine_rows=quarantine_rows,
            semantic_fingerprint=manifest["semanticFingerprint"],
        )
    except Exception:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        raise


__all__ = [
    "STAGING_MANIFEST_VERSION",
    "StagingError",
    "StagingResult",
    "build_staging",
]
