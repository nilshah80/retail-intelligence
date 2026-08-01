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
from retail_contracts.money_sql import (
    allocated_minor_sql,
    exact_minor_sql,
    invalid_minor_sql,
)

from retail_ingestion.adapters import AdapterContext, adapter_for, registered_adapters
from retail_ingestion.mappings import build_location_crosswalk
from retail_ingestion.profiles import (
    load_source_profile,
    neutral_relation_roles,
    staging_v2_roles,
)
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
    merchandise_money_invalid = " OR ".join(
        invalid_minor_sql(field, "currency_code")
        for field in (
            "gross_amount_major",
            "discount_amount_major",
            "net_amount_major",
            "tax_amount_major",
        )
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
        (
            "stage_data.shopify_merchandise",
            "shopify_merchandise",
            merchandise_money_invalid,
            "money_precision_loss",
        ),
        (
            "stage_data.shopify_prices",
            "shopify_prices",
            invalid_minor_sql("price_major", "currency_code"),
            "money_precision_loss",
        ),
        (
            "stage_data.bc_receipts",
            "bc_receipts",
            invalid_minor_sql("unit_cost_major", "currency_code"),
            "money_precision_loss",
        ),
        (
            "stage_data.bc_inventory_cost",
            "bc_inventory_cost",
            invalid_minor_sql("unit_cost_major", "currency_code"),
            "money_precision_loss",
        ),
        (
            "stage_data.shopify_adjustment",
            "shopify_adjustment",
            "event_type = 'REFUND' AND (NOT money_precision_valid "
            "OR amount_minor IS NULL OR amount_minor <= 0 "
            "OR currency_code IS NULL)",
            "money_precision_loss",
        ),
        (
            "stage_data.shopify_adjustment",
            "shopify_adjustment",
            "(event_type = 'RETURN' AND (units IS NULL OR units <= 0 "
            "OR amount_minor IS NOT NULL OR currency_code IS NOT NULL)) "
            "OR event_type NOT IN ('RETURN', 'REFUND')",
            "INVALID_ADJUSTMENT_ROW",
        ),
    )
    for table, dataset, predicate, reason in checks:
        # These checks are written against dialect relations. A retailer that
        # supplies none of them has nothing for this pass to inspect, and demanding
        # the relation exist failed the build after standardized views had already
        # been created. An adapter that stages a role directly is responsible for
        # its own row-level rejection, which the mapped_files adapter does through
        # its candidate table and reason codes.
        if not _relation_exists(connection, table.split(".", 1)[1]):
            continue
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


def _drain_adapter_rejects(connection: duckdb.DuckDBPyConnection) -> int:
    """Move every adapter's row-level rejects into the shared quarantine.

    `_build_quarantine` only inspects dialect relations, so an adapter that does its own
    row validation had nowhere governed to put a reject. The mapped_files adapter records
    them in `<role>_candidate._reject_reason` and then excludes them from the accepted
    role, which means an invalid row vanished from staging while both
    `manifest.quarantineRows` and `stage_data.adapter_quarantine` stayed at zero -- the
    row was neither served nor traceable, which is the one outcome the contract forbids.

    This is source-neutral by construction: it discovers candidate relations and their
    reject column rather than naming any adapter or dialect, so a new adapter is governed
    by adopting the convention instead of by editing this function.
    """

    candidates = [
        str(row[0])
        for row in connection.execute(
            """
            SELECT table_name FROM duckdb_tables()
            WHERE schema_name = 'stage_data' AND table_name LIKE '%\_candidate' ESCAPE '\\'
            """
        ).fetchall()
    ]
    drained = 0
    for relation in candidates:
        columns = {
            str(row[0])
            for row in connection.execute(
                "SELECT column_name FROM duckdb_columns() WHERE schema_name = "
                f"'stage_data' AND table_name = '{relation}'"
            ).fetchall()
        }
        if "_reject_reason" not in columns:
            continue
        dataset = relation[: -len("_candidate")]
        # Lineage columns are optional across adapters, so absent ones become NULL rather
        # than failing the drain: a reject with partial lineage is still better recorded
        # than dropped.
        def col(name: str) -> str:
            return name if name in columns else "NULL"

        connection.execute(
            f"""
            INSERT INTO stage_data.adapter_quarantine
            SELECT
                {col("source_system")},
                {col("source_instance")},
                '{dataset}',
                {col("native_record_id")},
                _reject_reason,
                {col("raw_object_path")},
                sha256(
                    coalesce({col("native_record_id")}, '') || ':' ||
                    coalesce({col("raw_object_path")}, '') || ':' || _reject_reason
                )
            FROM stage_data.{relation}
            WHERE _reject_reason IS NOT NULL
            """
        )
        drained += int(
            connection.execute(
                f"SELECT count(*) FROM stage_data.{relation} "
                "WHERE _reject_reason IS NOT NULL"
            ).fetchone()[0]
        )
    return drained


def _relation_exists(
    connection: duckdb.DuckDBPyConnection,
    name: str,
) -> bool:
    """Is `stage_data.<name>` present as a table or a view?"""

    return bool(
        connection.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'stage_data' AND table_name = ?
            """,
            [name],
        ).fetchone()[0]
    )


def _create_standardized_views(
    connection: duckdb.DuckDBPyConnection,
    *,
    already_materialized: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    """Expose the only relations source-neutral transformations may import.

    Two things this must not do, both of which it used to.

    It must not overwrite a role an adapter already materialised. The mapped_files
    adapter creates `stage_data.merchandise` as a table; replacing it with a view
    over the platform-dialect relation discarded the retailer's data outright.

    It must not require a dialect relation the retailer never supplied. A
    mapped-files-only source has none of the platform-named tables in the mapping
    below, so creating views over them failed the build rather than producing a
    smaller, honest staging set.

    A role that nobody supplies is simply absent, and the capability that needs it
    reports unavailable downstream -- which is what the readiness policy is for.
    """

    direct = {
        "merchandise": "shopify_merchandise",
        "adjustment": "shopify_adjustment",
        "fulfillment": "shopify_fulfillment",
        "inventory": "bc_inventory",
        "receipt": "bc_receipts",
        "dimension_signal": "companion_dimension_signal",
        "products": "shopify_products",
        "product_references": "bc_products",
        "locations": "shopify_locations",
        "prices": "shopify_prices",
        "supplier_terms": "bc_supplier_terms",
        "invoice_sales_control": "bc_sales_control",
        "customer_segment_counts": "shopify_customer_segment_counts",
        "inventory_cost": "bc_inventory_cost",
        "inventory_batches": "bc_inventory_batches",
        "inbound_shipments": "bc_inbound_shipments",
        "transfer_orders": "bc_transfer_orders",
        "waste_events": "bc_waste_events",
        "warehouse_capacity": "bc_warehouse_capacity",
        "wms_comparisons": "bc_wms_comparisons",
        "supplier_performance": "bc_supplier_performance",
        # Source contract v13. Neutral names, because the canonical transforms may
        # import ONLY these: the platform spelling stops here.
        "service_lanes": "companion_service_lanes",
        "inbound_status_events": "bc_inbound_status_events",
        "inventory_transfer_events": "bc_inventory_transfer_events",
        "supply_terms": "bc_supply_terms",
    }
    # An adapter names its relation after the staging-v2 role, and several neutral
    # relations are not spelled like their role (`locations` <- `location`). The
    # correspondence is declared in role-map.yaml, so it is read rather than guessed.
    relation_roles = neutral_relation_roles()
    created_direct: list[str] = []
    for target, source in direct.items():
        if f"stage_data.{target}" in already_materialized:
            # An adapter supplied this role directly; leave its table alone.
            created_direct.append(target)
            continue
        role = relation_roles.get(target)
        if role is not None and f"stage_data.{role}" in already_materialized:
            # Same role, different spelling. Expose it under the neutral name a
            # source-neutral consumer imports, without copying the retailer's rows.
            connection.execute(
                f"CREATE OR REPLACE VIEW stage_data.{target} AS "
                f"SELECT * FROM stage_data.{role}"
            )
            created_direct.append(target)
            continue
        if not _relation_exists(connection, source):
            continue
        connection.execute(
            f"CREATE OR REPLACE VIEW stage_data.{target} AS "
            f"SELECT * FROM stage_data.{source}"
        )
        created_direct.append(target)

    fulfilled_units = "least(m.units, f.fulfilled_units)"
    gross_minor = exact_minor_sql("m.gross_amount_major", "m.currency_code")
    discount_minor = exact_minor_sql(
        "m.discount_amount_major", "m.currency_code"
    )
    net_minor = exact_minor_sql("m.net_amount_major", "m.currency_code")
    tax_minor = exact_minor_sql("m.tax_amount_major", "m.currency_code")
    statements = {
        "sales_control": f"""
            WITH fulfillment_by_line AS (
                SELECT
                    source_instance,
                    source_sale_id,
                    source_line_id,
                    sum(units)::BIGINT AS fulfilled_units,
                    max(known_as_of) AS known_as_of
                FROM stage_data.fulfillment
                GROUP BY source_instance, source_sale_id, source_line_id
            ),
            line_facts AS (
                SELECT
                    m.source_instance,
                    m.source_sale_id,
                    m.source_line_id,
                    m.currency_code,
                    m.units::BIGINT AS ordered_units,
                    {fulfilled_units}::BIGINT AS fulfilled_units,
                    {gross_minor}::HUGEINT AS gross_minor,
                    {discount_minor}::HUGEINT AS discount_minor,
                    {net_minor}::HUGEINT AS net_minor,
                    {tax_minor}::HUGEINT AS tax_minor,
                    f.known_as_of
                FROM stage_data.merchandise AS m
                JOIN fulfillment_by_line AS f
                  ON f.source_instance = m.source_instance
                 AND f.source_sale_id = m.source_sale_id
                 AND f.source_line_id = m.source_line_id
                WHERE m.units > 0 AND f.fulfilled_units > 0
            )
            SELECT
                source_instance,
                source_sale_id,
                source_line_id,
                currency_code,
                fulfilled_units AS units,
                {
                    allocated_minor_sql(
                        "gross_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS gross_minor,
                {
                    allocated_minor_sql(
                        "discount_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS discount_minor,
                {
                    allocated_minor_sql(
                        "net_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS net_minor,
                {
                    allocated_minor_sql(
                        "tax_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS tax_minor,
                known_as_of
            FROM line_facts
        """,
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
                source_system,
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
                source_system,
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
    created_derived: list[str] = []
    for name, select_sql in statements.items():
        if f"stage_data.{name}" in already_materialized:
            created_derived.append(name)
            continue
        try:
            connection.execute(
                f"CREATE OR REPLACE VIEW stage_data.{name} AS {select_sql}"
            )
        except duckdb.CatalogException:
            # A derived view whose platform inputs are absent is skipped rather
            # than failing the build. Nothing silently degrades: the relation is
            # simply not in the returned set, so it never appears in the staging
            # manifest and no consumer can mistake it for present.
            continue
        created_derived.append(name)
    return tuple(
        f"stage_data.{name}" for name in (*created_direct, *created_derived)
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
        connection.execute("SET TimeZone = 'UTC'")
        catalog.register_metadata(connection)
        # The frozen role catalog is injected rather than read from the profile, so a
        # retailer cannot redefine a platform role in a file they own. Without this the
        # mapped_files adapter could not run through build_staging() at all: it requires
        # a role catalog, and the profile schema rightly refuses to carry one.
        context = AdapterContext(
            connection=connection,
            catalog=catalog,
            profile={**profile, "roleCatalog": staging_v2_roles()},
        )
        source_systems = {
            row.source_system
            for row in catalog.objects
            if row.source_system != "generator"
        }
        unsupported = sorted(source_systems - set(registered_adapters()))
        if unsupported:
            raise StagingError(
                "no semantic adapter is registered for source system(s): "
                + ", ".join(unsupported)
            )
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
        standardized_views = _create_standardized_views(
            connection,
            already_materialized=frozenset(staged_tables),
        )
        crosswalk_rows = build_location_crosswalk(connection, catalog)
        quarantine_rows = _build_quarantine(connection)
        # Every adapter's own rejects, not just the dialect relations'.
        quarantine_rows += _drain_adapter_rejects(connection)
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
            # Evidence about the upstream generator run, which only exists when the
            # snapshot came from one. A retailer landing its own files has no upstream
            # manifest, and requiring one failed the build on a key that describes a
            # producer the retailer does not have. The landing semantic fingerprint
            # below is a property of the landing itself and stays required.
            "upstreamManifestSha256": (
                catalog.landing_manifest.get("upstreamManifest") or {}
            ).get("sha256"),
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
