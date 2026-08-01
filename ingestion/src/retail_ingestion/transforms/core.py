"""Source-neutral transformations from standardized staging to retail_v2.

This module is intentionally forbidden from importing source adapters or
referencing raw/source-specific schemas. Its sole input contract is
``stage_data``.
"""

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
)

TRANSFORM_VERSION = "retail-transform/1.2.0"
TRANSFORM_MANIFEST_VERSION = "retail-ingestion-candidate/v1"


class TransformError(RuntimeError):
    """A canonical candidate cannot be constructed."""


@dataclass(frozen=True)
class TransformResult:
    candidate_database: Path
    candidate_manifest: Path
    entity_counts: Mapping[str, int]
    semantic_fingerprint: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": TRANSFORM_MANIFEST_VERSION,
            "candidateDatabase": str(self.candidate_database),
            "candidateManifest": str(self.candidate_manifest),
            "entityCounts": dict(self.entity_counts),
            "semanticFingerprint": self.semantic_fingerprint,
        }


def _sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _entity_control(
    connection: duckdb.DuckDBPyConnection, entity: str
) -> dict[str, int | str]:
    volatile_columns = {
        "ingest_runs": {
            "started_at",
            "completed_at",
            "canonical_quality_pct",
            "capability_mask",
            "curated_fingerprint",
        },
        "quality_violations": {"observed_at"},
        "quarantine_records": {"quarantined_at"},
    }
    columns = [
        str(row[1])
        for row in connection.execute(
            f"PRAGMA table_info('canonical_data.{entity}')"
        ).fetchall()
        if str(row[1]) not in volatile_columns.get(entity, set())
    ]
    rendered = ", ".join(
        '"' + column.replace('"', '""') + '"' for column in columns
    )
    row_count, hash_xor, hash_sum = connection.execute(
        f"""
        SELECT
            count(*)::BIGINT,
            coalesce(bit_xor(hash({rendered})), 0)::UBIGINT,
            coalesce(sum(hash({rendered})), 0)::HUGEINT
        FROM canonical_data."{entity}"
        """
    ).fetchone()
    return {
        "rows": int(row_count),
        # Hash controls exceed the RFC 8785 / JavaScript safe-integer domain.
        # The fingerprint contract requires canonical decimal strings here.
        "rowHashXor": str(int(hash_xor)),
        "rowHashSum": str(int(hash_sum)),
    }


def _densify_sales(connection: duckdb.DuckDBPyConnection) -> None:
    """Insert explicit zero rows only for missing active assortment dates."""

    connection.execute(
        """
        INSERT INTO canonical_data.sales
        WITH active_dates AS (
            SELECT
                a.sku_id,
                a.store_id,
                a.channel_id,
                calendar.date,
                stores.currency_code,
                greatest(
                    a.known_as_of,
                    timezone(
                        stores.timezone,
                        cast(calendar.date + INTERVAL 1 DAY AS TIMESTAMP)
                    )
                ) AS known_as_of,
                a.known_as_of_evidence_grade,
                row_number() OVER (
                    PARTITION BY
                        a.sku_id, a.store_id, a.channel_id, calendar.date
                    ORDER BY a.known_as_of DESC, a.active_from DESC
                ) AS active_window_rank
            FROM canonical_data.assortment_calendar AS a
            JOIN canonical_data.stores AS stores
              ON stores.store_id = a.store_id
            JOIN canonical_data.calendar AS calendar
              ON calendar.market_id = stores.market_id
             AND calendar.date >= a.active_from
             AND (
                    a.active_to IS NULL
                    OR calendar.date <= a.active_to
                 )
        )
        SELECT
            active.sku_id,
            active.store_id,
            active.channel_id,
            active.date,
            1::INTEGER AS sales_version,
            0::BIGINT AS units,
            0::BIGINT AS gross_sales_amount,
            0::BIGINT AS discount_amount,
            0::BIGINT AS net_sales_amount,
            0::BIGINT AS tax_amount,
            active.currency_code,
            NULL::BIGINT AS net_price,
            false::BOOLEAN AS promo_flag,
            active.known_as_of,
            active.known_as_of_evidence_grade
        FROM active_dates AS active
        ANTI JOIN canonical_data.sales AS observed
          ON observed.sku_id = active.sku_id
         AND observed.store_id = active.store_id
         AND observed.channel_id = active.channel_id
         AND observed.date = active.date
         AND observed.sales_version = 1
        WHERE active.active_window_rank = 1
        """
    )


def _create_core(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    connection.execute("CREATE SCHEMA canonical_data")

    connection.execute(
        f"""
        CREATE TABLE canonical_data.products AS
        SELECT
            concat(market_id, ':', sku_source_key)::VARCHAR AS sku_id,
            split_part(tags, '|', 1)::VARCHAR AS dept_id,
            split_part(tags, '|', 2)::VARCHAR AS category,
            nullif(split_part(tags, '|', 3), '')::VARCHAR AS sub_cat,
            greatest(
                1,
                coalesce(
                    try_cast(measurement_value AS BIGINT),
                    1
                )
            )::BIGINT AS pack_size,
            product_name::VARCHAR AS product_name,
            brand::VARCHAR AS brand,
            NULL::INTEGER AS shelf_life_days,
            {
                exact_minor_sql(
                    "reference_price_major", "currency_code"
                )
            } AS reference_cost,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.products
        QUALIFY row_number() OVER (
            PARTITION BY market_id, sku_source_key
            ORDER BY known_as_of DESC, native_record_id DESC
        ) = 1
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.locations AS
        SELECT
            concat(l.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            x.canonical_location_name::VARCHAR AS name,
            x.canonical_location_type::VARCHAR AS type,
            l.market_id::VARCHAR AS market_id,
            l.currency_code::VARCHAR AS currency_code,
            l.timezone::VARCHAR AS timezone,
            l.region::VARCHAR AS region,
            l.city::VARCHAR AS city,
            NULL::VARCHAR AS parent_dc,
            lower(l.location_kind)::VARCHAR AS format,
            coalesce(try_cast(l.active_raw AS BOOLEAN), true)::BOOLEAN AS active,
            l.known_as_of,
            l.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.locations AS l
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = l.source_system
         AND x.market_id = l.market_id
         AND x.source_location_key = l.location_source_key
        QUALIFY row_number() OVER (
            PARTITION BY l.market_id, x.canonical_location_key
            ORDER BY l.known_as_of DESC, l.native_record_id DESC
        ) = 1
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.stores AS
        SELECT
            location_id::VARCHAR AS store_id,
            market_id,
            currency_code,
            timezone,
            region,
            format,
            city
        FROM canonical_data.locations
        WHERE type = 'store' AND active
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.channels AS
        SELECT
            market_id::VARCHAR AS market_id,
            concat(market_id, ':', channel_source_key)::VARCHAR AS channel_id,
            channel_source_key::VARCHAR AS name,
            CASE
                WHEN lower(channel_source_key) LIKE '%online%' THEN 'online'
                ELSE 'store'
            END::VARCHAR AS type,
            'Derived from the native sales channel'::VARCHAR AS description,
            true::BOOLEAN AS active,
            min(known_as_of) AS known_as_of,
            'native_processed'::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.merchandise
        GROUP BY market_id, channel_source_key
        """
    )
    gross_minor = exact_minor_sql("m.gross_amount_major", "m.currency_code")
    discount_minor = exact_minor_sql(
        "m.discount_amount_major", "m.currency_code"
    )
    net_minor = exact_minor_sql("m.net_amount_major", "m.currency_code")
    tax_minor = exact_minor_sql("m.tax_amount_major", "m.currency_code")
    fulfilled_units = "least(m.units, f.fulfilled_units)"
    connection.execute(
        f"""
        CREATE TABLE canonical_data.sales AS
        WITH fulfillment_by_line AS (
            SELECT
                source_instance,
                source_sale_id,
                source_line_id,
                sum(units)::BIGINT AS fulfilled_units,
                max(known_as_of) AS known_as_of,
                arg_max(evidence_grade, known_as_of)::VARCHAR
                    AS evidence_grade
            FROM stage.stage_data.fulfillment
            GROUP BY source_instance, source_sale_id, source_line_id
        ),
        fulfilled_line_facts AS (
            SELECT
                m.*,
                m.units::BIGINT AS ordered_units,
                {fulfilled_units}::BIGINT AS fulfilled_units,
                {gross_minor}::HUGEINT AS gross_minor,
                {discount_minor}::HUGEINT AS discount_minor,
                {net_minor}::HUGEINT AS net_minor,
                {tax_minor}::HUGEINT AS tax_minor,
                f.known_as_of AS fulfilled_known_as_of,
                f.evidence_grade AS fulfilled_evidence_grade
            FROM stage.stage_data.merchandise AS m
            JOIN fulfillment_by_line AS f
              ON f.source_instance = m.source_instance
             AND f.source_sale_id = m.source_sale_id
             AND f.source_line_id = m.source_line_id
            WHERE m.units > 0 AND f.fulfilled_units > 0
        ),
        allocated AS (
            SELECT
                *,
                {
                    allocated_minor_sql(
                        "gross_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS fulfilled_gross_minor,
                {
                    allocated_minor_sql(
                        "discount_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS fulfilled_discount_minor,
                {
                    allocated_minor_sql(
                        "net_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS fulfilled_net_minor,
                {
                    allocated_minor_sql(
                        "tax_minor", "fulfilled_units", "ordered_units"
                    )
                }::BIGINT AS fulfilled_tax_minor
            FROM fulfilled_line_facts
        )
        SELECT
            concat(m.market_id, ':', m.sku_source_key)::VARCHAR AS sku_id,
            concat(m.market_id, ':', x.canonical_location_key)::VARCHAR AS store_id,
            concat(m.market_id, ':', m.channel_source_key)::VARCHAR AS channel_id,
            m.business_date::DATE AS date,
            1::INTEGER AS sales_version,
            sum(fulfilled_units)::BIGINT AS units,
            sum(fulfilled_gross_minor)::BIGINT AS gross_sales_amount,
            sum(fulfilled_discount_minor)::BIGINT AS discount_amount,
            sum(fulfilled_net_minor)::BIGINT AS net_sales_amount,
            sum(fulfilled_tax_minor)::BIGINT AS tax_amount,
            m.currency_code::VARCHAR AS currency_code,
            CASE WHEN sum(fulfilled_units) = 0 THEN 0
                ELSE (
                    sum(fulfilled_net_minor)
                    + sum(fulfilled_units) // 2
                ) // sum(fulfilled_units)
            END::BIGINT AS net_price,
            bool_or(
                promo_source_key IS NOT NULL
                AND promo_source_key NOT IN ('', '[]')
            )::BOOLEAN AS promo_flag,
            max(fulfilled_known_as_of) AS known_as_of,
            arg_max(
                fulfilled_evidence_grade, fulfilled_known_as_of
            )::VARCHAR AS known_as_of_evidence_grade
        FROM allocated AS m
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = m.source_system
         AND x.market_id = m.market_id
         AND x.source_location_key = m.demand_location_source_key
        GROUP BY
            m.market_id, m.sku_source_key, x.canonical_location_key,
            m.channel_source_key, m.business_date, m.currency_code
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.sales_adjustments AS
        SELECT
            concat(a.market_id, ':', a.source_event_id)::VARCHAR AS adjustment_id,
            1::INTEGER AS adjustment_version,
            source_sale_id::VARCHAR AS source_sale_id,
            source_parent_event_id::VARCHAR AS source_parent_event_id,
            concat(a.market_id, ':', a.sku_source_key)::VARCHAR AS sku_id,
            concat(a.market_id, ':', x.canonical_location_key)::VARCHAR AS store_id,
            concat(a.market_id, ':', a.channel_source_key)::VARCHAR AS channel_id,
            sale_date::DATE AS sale_date,
            event_date::DATE AS event_date,
            CASE upper(event_type)
                WHEN 'RETURN' THEN 'physical_return'
                WHEN 'CANCELLATION' THEN 'post_fulfilment_cancellation'
                ELSE 'financial_refund'
            END::VARCHAR AS event_type,
            abs(units)::BIGINT AS units,
            amount_minor::BIGINT AS amount,
            currency_code::VARCHAR AS currency_code,
            reason_code::VARCHAR AS reason_code,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.adjustment AS a
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = a.source_system
         AND x.market_id = a.market_id
         AND x.source_location_key = a.demand_location_source_key
        WHERE coalesce(abs(a.units), 0) > 0
           OR coalesce(a.amount_minor, 0) > 0
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.sales_fulfillments AS
        SELECT
            concat(f.market_id, ':', f.source_fulfillment_line_id)::VARCHAR
                AS fulfillment_line_id,
            1::INTEGER AS fulfillment_version,
            source_sale_id::VARCHAR AS source_sale_id,
            concat(f.market_id, ':', f.sku_source_key)::VARCHAR AS sku_id,
            concat(f.market_id, ':', demand.canonical_location_key)::VARCHAR
                AS demand_location_id,
            concat(f.market_id, ':', f.channel_source_key)::VARCHAR AS channel_id,
            concat(f.market_id, ':', supply.canonical_location_key)::VARCHAR
                AS supply_location_id,
            sale_date::DATE AS sale_date,
            fulfilled_at,
            units::BIGINT AS units,
            shipment_id::VARCHAR AS shipment_id,
            carrier_status::VARCHAR AS carrier_status,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.fulfillment AS f
        JOIN stage.stage_data.location_crosswalk AS demand
          ON demand.source_system = f.source_system
         AND demand.market_id = f.market_id
         AND demand.source_location_key = f.demand_location_source_key
        JOIN stage.stage_data.location_crosswalk AS supply
          ON supply.source_system = f.source_system
         AND supply.market_id = f.market_id
         AND supply.source_location_key = f.supply_location_source_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.calendar AS
        WITH bounds AS (
            SELECT st.market_id, min(s.date) AS start_date, max(s.date) AS end_date
            FROM canonical_data.sales AS s
            JOIN canonical_data.stores AS st USING (store_id)
            GROUP BY st.market_id
        )
        SELECT
            b.market_id,
            d.date::DATE AS date,
            dayname(d.date)::VARCHAR AS weekday,
            month(d.date)::INTEGER AS month,
            year(d.date)::INTEGER AS year,
            (dayofweek(d.date) NOT IN (0, 6))::BOOLEAN AS working_day,
            try_cast('1970-01-01T00:00:00Z' AS TIMESTAMPTZ) AS known_as_of,
            'native_extracted'::VARCHAR AS known_as_of_evidence_grade
        FROM bounds AS b,
        LATERAL generate_series(b.start_date, b.end_date, INTERVAL 1 DAY) AS d(date)
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.calendar_events AS
        SELECT
            market_id,
            CASE WHEN geo_scope_type = 'MARKET' THEN 'market'
                ELSE lower(geo_scope_type)
            END::VARCHAR AS geo_scope_type,
            CASE WHEN lower(geo_scope_type) = 'market' THEN market_id
                ELSE coalesce(nullif(geo_scope_id, ''), market_id)
            END::VARCHAR AS geo_scope_id,
            try_cast(date_raw AS DATE) AS date,
            event_name::VARCHAR AS event_name,
            event_type::VARCHAR AS event_type,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.holidays
        """
    )
    connection.execute(
        f"""
        CREATE TABLE canonical_data.sell_prices AS
        SELECT
            concat(p.market_id, ':', p.sku_source_key)::VARCHAR AS sku_id,
            s.store_id,
            c.channel_id,
            date_trunc('week', p.effective_date)::DATE AS week_start,
            {exact_minor_sql("p.price_major", "p.currency_code")}
                AS net_price,
            {exact_minor_sql("p.price_major", "p.currency_code")}
                AS regular_price,
            CASE WHEN lower(coalesce(p.price_reason, '')) LIKE '%promo%'
                      OR lower(coalesce(p.price_reason, '')) LIKE '%clear%'
                      OR lower(coalesce(p.price_reason, '')) LIKE '%sale%'
                THEN {exact_minor_sql("p.price_major", "p.currency_code")}
                ELSE NULL
            END AS promo_price,
            p.currency_code,
            sha256(p.raw_object_path || ':' || p.sku_source_key)::VARCHAR
                AS source_price_path_id,
            p.known_as_of,
            p.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.prices AS p
        JOIN canonical_data.stores AS s USING (market_id)
        JOIN canonical_data.channels AS c
          ON c.market_id = p.market_id
        QUALIFY row_number() OVER (
            PARTITION BY
                p.market_id, p.sku_source_key, s.store_id, c.channel_id,
                date_trunc('week', p.effective_date), p.known_as_of
            ORDER BY p.effective_date DESC, p.native_record_id DESC
        ) = 1
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.stock_snapshots AS
        WITH inventory_boundary AS (
            SELECT market_id, max(snapshot_date) AS snapshot_date
            FROM stage.stage_data.inventory
            GROUP BY market_id
        ),
        current_in_transit AS (
            SELECT
                s.market_id,
                s.sku_source_key,
                x.canonical_location_key,
                sum(s.qty)::BIGINT AS units
            FROM stage.stage_data.inbound_shipments AS s
            JOIN stage.stage_data.location_crosswalk AS x
              ON x.source_system = s.source_system
             AND x.market_id = s.market_id
             AND x.source_location_key = s.to_location_source_key
            WHERE replace(lower(s.status), ' ', '_') IN (
                'in_transit', 'dispatched', 'shipped'
            )
            GROUP BY s.market_id, s.sku_source_key, x.canonical_location_key
        )
        SELECT
            concat(i.market_id, ':', i.sku_source_key)::VARCHAR AS sku_id,
            concat(i.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            i.snapshot_date::DATE AS snapshot_date,
            on_hand_units::BIGINT AS on_hand_units,
            CASE
                WHEN i.snapshot_date = boundary.snapshot_date
                THEN greatest(
                    i.incoming_units
                    - least(
                        i.incoming_units,
                        coalesce(transit.units, 0)
                    ),
                    0
                )
                ELSE i.incoming_units
            END::BIGINT AS on_order_units,
            committed_units::BIGINT AS committed_units,
            (
                reserved_units
                + quality_control_units
                + safety_stock_units
            )::BIGINT AS reserved_units,
            damaged_units::BIGINT AS damaged_units,
            CASE
                WHEN i.snapshot_date = boundary.snapshot_date
                THEN least(
                    i.incoming_units,
                    coalesce(transit.units, 0)
                )
                ELSE 0
            END::BIGINT AS in_transit_units,
            greatest(
                0,
                on_hand_units - committed_units - reserved_units
                    - quality_control_units - safety_stock_units
                    - damaged_units
            )::BIGINT AS atp_units,
            'derived_buckets'::VARCHAR AS atp_method,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.inventory AS i
        JOIN inventory_boundary AS boundary
          ON boundary.market_id = i.market_id
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = i.source_system
         AND x.market_id = i.market_id
         AND x.source_location_key = i.location_source_key
        LEFT JOIN current_in_transit AS transit
          ON transit.market_id = i.market_id
         AND transit.sku_source_key = i.sku_source_key
         AND transit.canonical_location_key = x.canonical_location_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.suppliers_leadtimes AS
        SELECT
            concat(t.market_id, ':', t.supplier_source_key)::VARCHAR AS supplier_id,
            l.location_id::VARCHAR AS destination_location_id,
            t.merch_scope_type::VARCHAR AS merch_scope_type,
            CASE
                WHEN t.merch_scope_type = 'sku'
                THEN concat(t.market_id, ':', t.merch_scope_id)
                ELSE t.merch_scope_id
            END::VARCHAR AS merch_scope_id,
            CASE WHEN t.from_location_source_key IS NULL THEN NULL
                ELSE concat(t.market_id, ':', t.from_location_source_key)
            END::VARCHAR AS from_location_id,
            t.effective_from::DATE AS effective_from,
            t.lead_time_days::INTEGER AS lead_time_days,
            t.moq::BIGINT AS moq,
            t.pack_qty::BIGINT AS pack_qty,
            t.known_as_of,
            t.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.supplier_terms AS t
        JOIN canonical_data.locations AS l
          ON l.market_id = t.market_id
         AND l.type <> 'store'
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.assortment_calendar AS
        SELECT
            concat(a.market_id, ':', a.sku_source_key)::VARCHAR AS sku_id,
            concat(a.market_id, ':', x.canonical_location_key)::VARCHAR
                AS store_id,
            c.channel_id,
            try_cast(a.active_from_raw AS DATE) AS active_from,
            try_cast(a.active_to_raw AS DATE) AS active_to,
            a.derivation_method::VARCHAR AS derivation_method,
            a.known_as_of,
            a.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.store_assortment AS a
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = a.source_system
         AND x.market_id = a.market_id
         AND x.source_location_key = a.demand_location_source_key
        JOIN canonical_data.channels AS c
          ON c.market_id = a.market_id
        WHERE coalesce(try_cast(a.active_raw AS BOOLEAN), true)
        """
    )
    _densify_sales(connection)
    connection.execute(
        """
        CREATE TABLE canonical_data.customer_segments AS
        SELECT
            segments.market_id,
            segments.segment_id,
            segments.name,
            counts.customer_count::BIGINT AS size,
            round(try_cast(segments.share_raw AS DECIMAL(18, 8)) * 100, 4)
                ::DECIMAL(18, 4) AS share_pct,
            concat('demand_multiplier=', segments.demand_multiplier_raw)::VARCHAR
                AS description,
            cast(segments.known_as_of AS DATE) AS as_of_date,
            segments.known_as_of,
            segments.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.customer_segments AS segments
        JOIN stage.stage_data.customer_segment_counts AS counts
          ON counts.market_id = segments.market_id
         AND counts.segment_id = segments.segment_id
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.fx_rates AS
        SELECT
            base_ccy,
            quote_ccy,
            try_cast(rate_raw AS DECIMAL(38, 18)) AS rate,
            try_cast(rate_date_raw AS DATE) AS rate_date,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.fx_rates
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.market_disruptions AS
        SELECT
            market_id,
            disruption_id,
            phase_id,
            try_cast(start_date_raw AS DATE) AS start_date,
            try_cast(end_date_raw AS DATE) AS end_date,
            try_cast(demand_factor_raw AS DECIMAL(18, 8)) AS demand_factor,
            try_cast(traffic_factor_raw AS DECIMAL(18, 8)) AS traffic_factor,
            try_cast(supply_factor_raw AS DECIMAL(18, 8)) AS supply_factor,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.market_disruptions
        """
    )
    return (
        "products", "locations", "stores", "channels", "sales",
        "sales_adjustments", "sales_fulfillments", "calendar",
        "calendar_events", "sell_prices", "stock_snapshots",
        "suppliers_leadtimes", "assortment_calendar", "customer_segments",
        "fx_rates", "market_disruptions",
    )


def _create_operational(connection: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    connection.execute(
        f"""
        CREATE TABLE canonical_data.purchase_receipts AS
        SELECT
            concat(r.market_id, ':', r.source_receipt_id)::VARCHAR AS receipt_id,
            concat(r.market_id, ':', r.sku_source_key)::VARCHAR AS sku_id,
            concat(r.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            concat(r.market_id, ':', r.supplier_source_key)::VARCHAR AS supplier_id,
            r.receipt_date::DATE AS receipt_date,
            r.qty::BIGINT AS qty,
            {exact_minor_sql("unit_cost_major", "currency_code")} AS unit_cost,
            currency_code,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.receipt AS r
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = r.source_system
         AND x.market_id = r.market_id
         AND x.source_location_key = r.location_source_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.weather_actual AS
        SELECT
            market_id, lower(geo_scope_type)::VARCHAR AS geo_scope_type,
            CASE WHEN lower(geo_scope_type) = 'market' THEN market_id
                ELSE geo_scope_id
            END::VARCHAR AS geo_scope_id,
            try_cast(date_raw AS DATE) AS date,
            try_cast(temperature_raw AS DECIMAL(18, 4)) AS tavg_c,
            try_cast(precipitation_raw AS DECIMAL(18, 4)) AS precip_mm,
            weather_code, known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.weather_actual
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.weather_forecast AS
        SELECT
            market_id, lower(geo_scope_type)::VARCHAR AS geo_scope_type,
            CASE WHEN lower(geo_scope_type) = 'market' THEN market_id
                ELSE geo_scope_id
            END::VARCHAR AS geo_scope_id,
            cast(try_cast(forecast_date_raw AS TIMESTAMPTZ) AS DATE)
                AS forecast_date,
            try_cast(target_date_raw AS DATE) AS target_date,
            try_cast(temperature_raw AS DECIMAL(18, 4)) AS tavg_c,
            try_cast(precipitation_raw AS DECIMAL(18, 4)) AS precip_prob,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.weather_forecast
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.local_events AS
        SELECT
            market_id,
            -- 'store' is the source's spelling of a location-scoped event. The
            -- canonical enum is market/region/location, and a store IS a
            -- location; passing the dialect word through was invisible until a
            -- fixture actually carried store-targeted events.
            CASE WHEN lower(geo_scope_type) = 'store' THEN 'location'
                ELSE lower(geo_scope_type)
            END::VARCHAR AS geo_scope_type,
            CASE WHEN lower(geo_scope_type) = 'market' THEN market_id
                ELSE geo_scope_id
            END::VARCHAR AS geo_scope_id,
            d.date::DATE AS date, event_name, event_type,
            try_cast(expected_impact_raw AS DECIMAL(18, 8)) AS expected_impact,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.local_events,
        LATERAL generate_series(
            try_cast(start_date_raw AS DATE),
            try_cast(end_date_raw AS DATE),
            INTERVAL 1 DAY
        ) AS d(date)
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.macro_index AS
        SELECT
            market_id, lower(geo_scope_type)::VARCHAR AS geo_scope_type,
            CASE WHEN lower(geo_scope_type) = 'market' THEN market_id
                ELSE geo_scope_id
            END::VARCHAR AS geo_scope_id,
            date_trunc('week', try_cast(valid_date_raw AS DATE))::DATE
                AS week_start,
            index_name,
            try_cast(value_raw AS DECIMAL(38, 8)) AS value,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.macro_index
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.competitors AS
        SELECT DISTINCT
            market_id,
            competitor_id::VARCHAR AS comp_id,
            competitor_id::VARCHAR AS name,
            'retailer'::VARCHAR AS type,
            'source_feed'::VARCHAR AS collection_method,
            'daily'::VARCHAR AS refresh,
            currency_code,
            true::BOOLEAN AS compliance_ok
        FROM stage.stage_data.competitor_prices
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.competitor_products AS
        SELECT
            market_id, competitor_id::VARCHAR AS comp_id,
            competitor_product_id::VARCHAR AS comp_product_id,
            min(try_cast(observed_at_raw AS TIMESTAMPTZ)) AS observed_at,
            any_value(competitor_product_title)::VARCHAR AS title,
            NULL::VARCHAR AS brand, NULL::VARCHAR AS model,
            NULL::VARCHAR AS gtin, '{}'::VARCHAR AS attributes,
            min(known_as_of) AS known_as_of,
            'native_observed'::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.competitor_prices
        GROUP BY market_id, competitor_id, competitor_product_id
        """
    )
    connection.execute(
        f"""
        CREATE TABLE canonical_data.competitor_prices AS
        SELECT
            p.market_id, p.competitor_id::VARCHAR AS comp_id,
            p.competitor_product_id::VARCHAR AS comp_product_id,
            CASE
                WHEN lower(p.geo_scope_type) IN ('store', 'location')
                THEN 'location'
                ELSE lower(p.geo_scope_type)
            END::VARCHAR AS geo_scope_type,
            CASE
                WHEN lower(p.geo_scope_type) IN ('store', 'location')
                THEN concat(p.market_id, ':', x.canonical_location_key)
                WHEN lower(p.geo_scope_type) = 'market'
                THEN p.market_id
                ELSE p.geo_scope_id
            END::VARCHAR AS geo_scope_id,
            try_cast(p.observed_at_raw AS TIMESTAMPTZ) AS observed_at,
            {
                exact_minor_sql(
                    "try_cast(p.price_raw AS DECIMAL(38, 6))",
                    "p.currency_code",
                )
            } AS price,
            p.currency_code,
            coalesce(try_cast(p.available_raw AS BOOLEAN), false) AS in_stock_flag,
            (p.promotion_text IS NOT NULL AND p.promotion_text <> '')::BOOLEAN
                AS promo_flag,
            p.known_as_of,
            p.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.competitor_prices AS p
        LEFT JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = p.source_system
         AND x.market_id = p.market_id
         AND x.source_location_key = p.geo_scope_id
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.competitor_matches AS
        SELECT
            match_id, market_id,
            concat(market_id, ':', sku_source_key)::VARCHAR AS sku_id,
            competitor_id::VARCHAR AS comp_id,
            competitor_product_id::VARCHAR AS comp_product_id,
            try_cast(confidence_raw AS DECIMAL(18, 8)) AS match_confidence,
            'active'::VARCHAR AS match_status,
            match_method::VARCHAR AS matched_attributes
        FROM stage.stage_data.competitor_matches
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.promotions AS
        SELECT
            market_id, promotion_id::VARCHAR AS promo_id, name,
            promotion_type::VARCHAR AS type,
            'demand_generation'::VARCHAR AS objective,
            try_cast(discount_pct_raw AS DECIMAL(18, 8)) AS offer_value,
            NULL::VARCHAR AS currency_code,
            try_cast(start_date_raw AS DATE) AS start_date,
            try_cast(end_date_raw AS DATE) AS end_date,
            segment_ids::VARCHAR AS segment_id,
            CASE WHEN (
                    SELECT max(date) FROM canonical_data.calendar
                 ) BETWEEN try_cast(start_date_raw AS DATE)
                AND try_cast(end_date_raw AS DATE)
                THEN 'active' ELSE 'historical' END::VARCHAR AS status,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.promotions
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.promotion_scopes AS
        SELECT
            market_id, promotion_id::VARCHAR AS promo_id,
            sha256(
                market_id || ':' || promotion_id || ':' ||
                coalesce(store_ids, '') || ':' || coalesce(channel_ids, '')
            )::VARCHAR AS scope_row_id,
            NULL::VARCHAR AS region,
            NULL::VARCHAR AS location_id,
            NULL::VARCHAR AS channel_id,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.promotions
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.promotion_merchandise_targets AS
        SELECT
            market_id, promotion_id::VARCHAR AS promo_id,
            merch_scope_type,
            CASE
                WHEN merch_scope_type = 'sku'
                THEN concat(market_id, ':', merch_scope_id)
                ELSE merch_scope_id
            END::VARCHAR AS merch_scope_id,
            try_cast(discount_pct_raw AS DECIMAL(18, 8)) AS discount_pct,
            known_as_of,
            evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.promotion_targets
        """
    )
    connection.execute(
        f"""
        CREATE TABLE canonical_data.inventory_cost AS
        WITH cost_layers AS (
            SELECT
                c.*,
                {
                    exact_minor_sql(
                        "c.unit_cost_major", "c.currency_code"
                    )
                }::HUGEINT AS unit_cost_minor
            FROM stage.stage_data.inventory_cost AS c
        ),
        weighted AS (
            SELECT
                c.market_id,
                c.sku_source_key,
                x.canonical_location_key,
                c.as_of_date,
                c.currency_code,
                sum(
                    c.unit_cost_minor * greatest(c.quantity, 0)
                )::HUGEINT AS weighted_minor,
                sum(greatest(c.quantity, 0))::HUGEINT AS positive_quantity,
                sum(c.quantity)::BIGINT AS on_hand_qty,
                any_value(c.method)::VARCHAR AS method,
                max(c.known_as_of) AS known_as_of
            FROM cost_layers AS c
            JOIN stage.stage_data.location_crosswalk AS x
              ON x.source_system = c.source_system
             AND x.market_id = c.market_id
             AND x.source_location_key = c.location_source_key
            GROUP BY
                c.market_id,
                c.sku_source_key,
                x.canonical_location_key,
                c.as_of_date,
                c.currency_code
        )
        SELECT
            concat(c.market_id, ':', c.sku_source_key)::VARCHAR AS sku_id,
            concat(c.market_id, ':', c.canonical_location_key)::VARCHAR
                AS location_id,
            c.as_of_date,
            CASE
                WHEN c.positive_quantity = 0 THEN NULL
                ELSE (
                    c.weighted_minor + c.positive_quantity // 2
                ) // c.positive_quantity
            END::BIGINT AS wac_cost,
            c.currency_code,
            c.on_hand_qty,
            c.method,
            c.known_as_of,
            'native_posted_available'::VARCHAR AS known_as_of_evidence_grade
        FROM weighted AS c
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.inventory_batches AS
        SELECT
            b.batch_id,
            concat(b.market_id, ':', b.sku_source_key)::VARCHAR AS sku_id,
            concat(b.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            b.batch_qty, b.mfg_date, b.expiry_date, b.receipt_date,
            NULL::BIGINT AS unit_cost,
            l.currency_code,
            b.known_as_of,
            b.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.inventory_batches AS b
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = b.source_system
         AND x.market_id = b.market_id
         AND x.source_location_key = b.location_source_key
        JOIN canonical_data.locations AS l
          ON l.location_id = concat(b.market_id, ':', x.canonical_location_key)
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.inbound_shipments AS
        SELECT
            s.shipment_id,
            concat(s.market_id, ':', s.sku_source_key)::VARCHAR AS sku_id,
            NULL::VARCHAR AS from_location,
            concat(s.market_id, ':', x.canonical_location_key)::VARCHAR
                AS to_location,
            s.qty::BIGINT AS qty,
            s.dispatch_date,
            s.expected_receipt_date,
            lower(s.status)::VARCHAR AS status,
            s.known_as_of,
            s.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.inbound_shipments AS s
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = s.source_system
         AND x.market_id = s.market_id
         AND x.source_location_key = s.to_location_source_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.transfer_orders AS
        SELECT
            t.transfer_id,
            concat(t.market_id, ':', t.sku_source_key)::VARCHAR AS sku_id,
            concat(t.market_id, ':', origin.canonical_location_key)::VARCHAR
                AS from_location,
            concat(t.market_id, ':', destination.canonical_location_key)::VARCHAR
                AS to_location,
            t.qty::BIGINT AS qty,
            t.reason,
            NULL::BIGINT AS expected_benefit_minor,
            l.currency_code,
            lower(t.status)::VARCHAR AS status
        FROM stage.stage_data.transfer_orders AS t
        JOIN stage.stage_data.location_crosswalk AS origin
          ON origin.source_system = t.source_system
         AND origin.market_id = t.market_id
         AND origin.source_location_key = t.from_location_source_key
        JOIN stage.stage_data.location_crosswalk AS destination
          ON destination.source_system = t.source_system
         AND destination.market_id = t.market_id
         AND destination.source_location_key = t.to_location_source_key
        JOIN canonical_data.locations AS l
          ON l.location_id = concat(t.market_id, ':', origin.canonical_location_key)
        """
    )
    # ------------------------------------------------------------------
    # Source contract v13 entities. Each staging relation is probed first: a v12
    # staging database has none of them, and the canonical tables are then
    # created empty so the entity inventory stays contract-complete on every
    # generation of input.
    # ------------------------------------------------------------------
    # duckdb_tables()/duckdb_views() rather than information_schema: the staging
    # database is ATTACHED under the name `stage`, and an attached catalog's
    # information_schema is not addressable as `stage.information_schema`. Views
    # are probed too, because the neutral role names are views over the adapter
    # tables.
    staged_relations = {
        row[0]
        for row in connection.execute(
            """
            SELECT table_name FROM duckdb_tables()
            WHERE database_name = 'stage' AND schema_name = 'stage_data'
            UNION ALL
            SELECT view_name FROM duckdb_views()
            WHERE database_name = 'stage' AND schema_name = 'stage_data'
            """
        ).fetchall()
    }

    if "service_lanes" in staged_relations:
        connection.execute(
            """
            CREATE TABLE canonical_data.service_lanes AS
            SELECT
                concat(s.market_id, ':', s.laneKey)::VARCHAR AS lane_id,
                s.market_id::VARCHAR AS market_id,
                s.laneType::VARCHAR AS lane_type,
                concat(s.market_id, ':', demand.canonical_location_key)::VARCHAR
                    AS demand_location_id,
                -- Empty string is the source's spelling of "market-wide default".
                -- Canonical stores NULL: an exact channel row wins over it, and
                -- an empty string that joined like a value would defeat the
                -- default semantics the contract declares.
                CASE WHEN s.channelKey IS NULL OR s.channelKey = ''
                    THEN NULL ELSE s.channelKey
                END::VARCHAR AS channel_id,
                concat(s.market_id, ':', supply.canonical_location_key)::VARCHAR
                    AS supply_location_id,
                try_cast(s.priorityRank AS INTEGER) AS priority_rank,
                try_cast(s.transitDays AS INTEGER) AS transit_days,
                try_cast(s.effectiveFrom AS DATE) AS effective_from,
                CASE WHEN s.effectiveTo IS NULL OR s.effectiveTo = ''
                    THEN NULL ELSE try_cast(s.effectiveTo AS DATE)
                END AS effective_to,
                s.known_as_of,
                s.evidence_grade::VARCHAR AS known_as_of_evidence_grade
            FROM stage.stage_data.service_lanes AS s
            JOIN stage.stage_data.location_crosswalk AS demand
              ON demand.source_system = s.source_system
             AND demand.market_id = s.market_id
             AND demand.source_location_key = s.demandLocationKey
            JOIN stage.stage_data.location_crosswalk AS supply
              ON supply.source_system = s.source_system
             AND supply.market_id = s.market_id
             AND supply.source_location_key = s.supplyLocationKey
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE canonical_data.service_lanes (
                lane_id VARCHAR, market_id VARCHAR, lane_type VARCHAR,
                demand_location_id VARCHAR, channel_id VARCHAR,
                supply_location_id VARCHAR, priority_rank INTEGER,
                transit_days INTEGER, effective_from DATE, effective_to DATE,
                known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
            )
            """
        )

    if "inbound_status_events" in staged_relations:
        connection.execute(
            """
            CREATE TABLE canonical_data.inbound_shipment_status_events AS
            SELECT
                s.source_shipment_id::VARCHAR AS shipment_id,
                concat(s.market_id, ':', s.sku_source_key)::VARCHAR AS sku_id,
                CASE WHEN s.from_location_source_key IS NULL THEN NULL
                    ELSE concat(s.market_id, ':', origin.canonical_location_key)
                END::VARCHAR AS from_location,
                concat(s.market_id, ':', dest.canonical_location_key)::VARCHAR
                    AS to_location,
                s.qty::BIGINT AS qty,
                s.status::VARCHAR AS status,
                s.status_effective_at,
                s.expected_date AS expected_receipt_date,
                s.known_as_of,
                s.evidence_grade::VARCHAR AS known_as_of_evidence_grade
            FROM stage.stage_data.inbound_status_events AS s
            JOIN stage.stage_data.location_crosswalk AS dest
              ON dest.source_system = s.source_system
             AND dest.market_id = s.market_id
             AND dest.source_location_key = s.location_source_key
            LEFT JOIN stage.stage_data.location_crosswalk AS origin
              ON origin.source_system = s.source_system
             AND origin.market_id = s.market_id
             AND origin.source_location_key = s.from_location_source_key
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE canonical_data.inbound_shipment_status_events (
                shipment_id VARCHAR, sku_id VARCHAR, from_location VARCHAR,
                to_location VARCHAR, qty BIGINT, status VARCHAR,
                status_effective_at TIMESTAMPTZ, expected_receipt_date DATE,
                known_as_of TIMESTAMPTZ, known_as_of_evidence_grade VARCHAR
            )
            """
        )

    if "inventory_transfer_events" in staged_relations:
        connection.execute(
            """
            CREATE TABLE canonical_data.inventory_transfer_events AS
            SELECT
                t.source_transfer_id::VARCHAR AS transfer_id,
                concat(t.market_id, ':', t.sku_source_key)::VARCHAR AS sku_id,
                concat(t.market_id, ':', origin.canonical_location_key)::VARCHAR
                    AS from_location_id,
                concat(t.market_id, ':', dest.canonical_location_key)::VARCHAR
                    AS to_location_id,
                t.qty::BIGINT AS qty,
                t.status::VARCHAR AS status,
                t.status_effective_at,
                t.unit_cost_minor::BIGINT AS unit_cost_minor,
                t.currency_code::VARCHAR AS currency_code,
                t.known_as_of,
                t.evidence_grade::VARCHAR AS known_as_of_evidence_grade
            FROM stage.stage_data.inventory_transfer_events AS t
            JOIN stage.stage_data.location_crosswalk AS origin
              ON origin.source_system = t.source_system
             AND origin.market_id = t.market_id
             AND origin.source_location_key = t.from_location_source_key
            JOIN stage.stage_data.location_crosswalk AS dest
              ON dest.source_system = t.source_system
             AND dest.market_id = t.market_id
             AND dest.source_location_key = t.to_location_source_key
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE canonical_data.inventory_transfer_events (
                transfer_id VARCHAR, sku_id VARCHAR, from_location_id VARCHAR,
                to_location_id VARCHAR, qty BIGINT, status VARCHAR,
                status_effective_at TIMESTAMPTZ, unit_cost_minor BIGINT,
                currency_code VARCHAR, known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )

    if "supply_terms" in staged_relations:
        connection.execute(
            """
            CREATE TABLE canonical_data.supply_terms AS
            SELECT
                concat(t.market_id, ':', dest.canonical_location_key)::VARCHAR
                    AS destination_location_id,
                t.origin_kind::VARCHAR AS origin_kind,
                concat(t.market_id, ':', t.origin_source_key)::VARCHAR
                    AS origin_id,
                t.merch_scope_type::VARCHAR AS merch_scope_type,
                CASE WHEN t.merch_scope_type = 'sku'
                    THEN concat(t.market_id, ':', t.merch_scope_id)
                    ELSE t.merch_scope_id
                END::VARCHAR AS merch_scope_id,
                t.effective_from,
                NULL::DATE AS effective_to,
                t.lead_time_days::INTEGER AS lead_time_days,
                t.lead_time_std_days,
                t.moq_units::BIGINT AS moq,
                t.pack_size_units::BIGINT AS pack_qty,
                t.known_as_of,
                t.evidence_grade::VARCHAR AS known_as_of_evidence_grade
            FROM stage.stage_data.supply_terms AS t
            JOIN stage.stage_data.location_crosswalk AS dest
              ON dest.source_system = t.source_system
             AND dest.market_id = t.market_id
             AND dest.source_location_key = t.destination_location_source_key
            """
        )
    else:
        connection.execute(
            """
            CREATE TABLE canonical_data.supply_terms (
                destination_location_id VARCHAR, origin_kind VARCHAR,
                origin_id VARCHAR, merch_scope_type VARCHAR,
                merch_scope_id VARCHAR, effective_from DATE, effective_to DATE,
                lead_time_days INTEGER, lead_time_std_days DECIMAL(8, 2),
                moq BIGINT, pack_qty BIGINT, known_as_of TIMESTAMPTZ,
                known_as_of_evidence_grade VARCHAR
            )
            """
        )

    connection.execute(
        """
        CREATE TABLE canonical_data.allocations AS
        SELECT
            a.allocation_id,
            concat(a.market_id, ':', a.sku_source_key)::VARCHAR AS sku_id,
            a.requested_qty::BIGINT AS pool_qty,
            concat(a.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            a.requested_qty::BIGINT AS requested_qty,
            a.allocated_qty::BIGINT AS allocated_qty,
            a.shortfall::BIGINT AS shortfall,
            'warehouse_priority'::VARCHAR AS rule,
            a.priority::VARCHAR AS priority,
            lower(a.status)::VARCHAR AS status
        FROM stage.stage_data.allocations AS a
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = a.source_system
         AND x.market_id = a.market_id
         AND x.source_location_key = a.location_source_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.waste_events AS
        SELECT
            w.event_id,
            concat(w.market_id, ':', w.sku_source_key)::VARCHAR AS sku_id,
            concat(w.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            w.event_date, w.units, w.reason_code,
            NULL::BIGINT AS unit_cost,
            l.currency_code,
            w.known_as_of,
            w.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.waste_events AS w
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = w.source_system
         AND x.market_id = w.market_id
         AND x.source_location_key = w.location_source_key
        JOIN canonical_data.locations AS l
          ON l.location_id = concat(w.market_id, ':', x.canonical_location_key)
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.warehouse_capacity_snapshots AS
        SELECT
            concat(w.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            w.snapshot_date, w.capacity_units, w.used_units, w.blocked_units,
            w.known_as_of,
            w.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.warehouse_capacity AS w
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = w.source_system
         AND x.market_id = w.market_id
         AND x.source_location_key = w.location_source_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.wms_inventory_comparisons AS
        SELECT
            concat(w.market_id, ':', w.sku_source_key)::VARCHAR AS sku_id,
            concat(w.market_id, ':', x.canonical_location_key)::VARCHAR
                AS location_id,
            w.snapshot_date, w.erp_on_hand_units, w.wms_on_hand_units,
            w.difference_units, w.known_as_of,
            w.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.wms_comparisons AS w
        JOIN stage.stage_data.location_crosswalk AS x
          ON x.source_system = w.source_system
         AND x.market_id = w.market_id
         AND x.source_location_key = w.location_source_key
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.supplier_performance AS
        SELECT
            concat(s.market_id, ':', s.supplier_source_key)::VARCHAR
                AS supplier_id,
            s.period::VARCHAR AS period,
            round(s.otd_pct * 100, 4)::DECIMAL(18, 4) AS otd_pct,
            round(s.capacity_confirmed_pct * 100, 4)::DECIMAL(18, 4)
                AS capacity_confirmed_pct,
            s.lead_time_mean_days,
            coalesce(s.lead_time_std_days, 0)::DECIMAL(18, 8)
                AS lead_time_std_days,
            CASE WHEN s.otd_pct < 0.8 THEN 'high'
                 WHEN s.otd_pct < 0.95 THEN 'medium'
                 ELSE 'low' END::VARCHAR AS risk,
            s.known_as_of,
            s.evidence_grade::VARCHAR AS known_as_of_evidence_grade
        FROM stage.stage_data.supplier_performance AS s
        """
    )
    return (
        "purchase_receipts", "weather_actual", "weather_forecast",
        "local_events", "macro_index", "competitors", "competitor_products",
        "competitor_prices", "competitor_matches", "promotions",
        "promotion_scopes", "promotion_merchandise_targets", "inventory_cost",
        "inventory_batches", "inbound_shipments", "transfer_orders",
        "allocations", "waste_events", "warehouse_capacity_snapshots",
        "wms_inventory_comparisons", "supplier_performance",
        "service_lanes", "inbound_shipment_status_events",
        "inventory_transfer_events", "supply_terms",
    )


def _create_controls(
    connection: duckdb.DuckDBPyConnection,
    *,
    staging_manifest: Mapping[str, Any],
    completed_at: str,
) -> tuple[str, ...]:
    source_snapshot_id = staging_manifest["sourceSnapshotId"]
    native_snapshot_id = staging_manifest.get("nativeSnapshotId")
    raw_manifest_hash = str(staging_manifest["upstreamManifestSha256"])
    coverage_manifest_hash = str(staging_manifest["semanticFingerprint"])
    composite_manifest_hash = hashlib.sha256(
        f"{raw_manifest_hash}:{coverage_manifest_hash}".encode("utf-8")
    ).hexdigest()
    connection.execute(
        f"""
        CREATE TABLE canonical_data.ingest_runs AS
        SELECT
            'ingest-{source_snapshot_id[:16]}'::VARCHAR AS ingest_run_id,
            'retail-datagen-multi-source'::VARCHAR AS source_id,
            {_sql_string(source_snapshot_id)}::VARCHAR AS source_snapshot_id,
            {_sql_string(str(native_snapshot_id))}::VARCHAR AS native_snapshot_id,
            {_sql_string(raw_manifest_hash)}::VARCHAR
                AS raw_manifest_hash,
            {_sql_string(coverage_manifest_hash)}::VARCHAR
                AS coverage_manifest_hash,
            {_sql_string(composite_manifest_hash)}::VARCHAR
                AS composite_manifest_hash,
            {_sql_string(staging_manifest['profileVersion'])}::VARCHAR
                AS profile_version,
            {_sql_string(json.dumps(staging_manifest['adapterVersions'], sort_keys=True))}
                ::VARCHAR AS adapter_version,
            '{TRANSFORM_VERSION}'::VARCHAR AS transform_version,
            try_cast({_sql_string(staging_manifest['completedAt'])} AS TIMESTAMPTZ)
                AS started_at,
            try_cast({_sql_string(completed_at)} AS TIMESTAMPTZ) AS completed_at,
            'pass'::VARCHAR AS status,
            100.0::DECIMAL(5, 2) AS raw_quality_pct,
            NULL::DECIMAL(5, 2) AS canonical_quality_pct,
            '{{}}'::VARCHAR AS capability_mask,
            NULL::VARCHAR AS curated_fingerprint
        """
    )
    connection.execute(
        """
        CREATE TABLE canonical_data.quality_violations (
            violation_id VARCHAR,
            ingest_run_id VARCHAR,
            gate VARCHAR,
            entity VARCHAR,
            source_record_id VARCHAR,
            rule_id VARCHAR,
            outcome VARCHAR,
            affected_capability VARCHAR,
            reason_code VARCHAR,
            reason VARCHAR,
            observed_at TIMESTAMPTZ
        )
        """
    )
    connection.execute(
        f"""
        CREATE TABLE canonical_data.quarantine_records AS
        SELECT
            sha256(
                source_system || ':' || source_instance || ':' ||
                coalesce(native_record_id, '') || ':' || reason_code
            )::VARCHAR AS quarantine_id,
            (SELECT ingest_run_id FROM canonical_data.ingest_runs LIMIT 1)
                AS ingest_run_id,
            'A'::VARCHAR AS gate,
            dataset::VARCHAR AS entity,
            native_record_id::VARCHAR AS source_record_id,
            reason_code,
            raw_object_path::VARCHAR AS raw_record_ref,
            payload_hash,
            try_cast({_sql_string(completed_at)} AS TIMESTAMPTZ)
                AS quarantined_at
        FROM stage.stage_data.adapter_quarantine
        """
    )
    return ("ingest_runs", "quality_violations", "quarantine_records")


def build_canonical_candidate(
    staging_database: str | Path,
    candidate_database: str | Path,
    *,
    execution_profile: Mapping[str, Any],
) -> TransformResult:
    source = Path(staging_database).expanduser().resolve()
    destination = Path(candidate_database).expanduser().resolve()
    staging_manifest_path = source.with_suffix(source.suffix + ".manifest.json")
    if not source.is_file() or not staging_manifest_path.is_file():
        raise TransformError("staging database/manifest is missing")
    staging_manifest = json.loads(staging_manifest_path.read_text(encoding="utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.candidate-{uuid.uuid4().hex}"
    )
    temporary_manifest = temporary.with_suffix(temporary.suffix + ".manifest.json")
    final_manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    connection: duckdb.DuckDBPyConnection | None = None
    completed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        connection = duckdb.connect(str(temporary))
        connection.execute(
            f"SET threads = {max(1, int(execution_profile['duckdbThreads']))}"
        )
        connection.execute(
            f"SET memory_limit = '{max(1, int(execution_profile['memoryLimitGb']))}GB'"
        )
        connection.execute("SET TimeZone = 'UTC'")
        connection.execute(
            f"ATTACH {_sql_string(str(source))} AS stage (READ_ONLY)"
        )
        entities = [
            *_create_core(connection),
            *_create_operational(connection),
            *_create_controls(
                connection,
                staging_manifest=staging_manifest,
                completed_at=completed_at,
            ),
        ]
        counts = {
            entity: int(
                connection.execute(
                    f"SELECT count(*) FROM canonical_data.{entity}"
                ).fetchone()[0]
            )
            for entity in sorted(entities)
        }
        entity_controls = {
            entity: _entity_control(connection, entity)
            for entity in sorted(entities)
        }
        connection.execute("DETACH stage")
        connection.execute("CHECKPOINT")
        connection.close()
        connection = None

        digest = hashlib.sha256()
        with temporary.open("rb") as reader:
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
        manifest: dict[str, Any] = {
            "schemaVersion": TRANSFORM_MANIFEST_VERSION,
            "transformVersion": TRANSFORM_VERSION,
            "sourceSnapshotId": staging_manifest["sourceSnapshotId"],
            "stagingSemanticFingerprint": staging_manifest["semanticFingerprint"],
            "entityCounts": counts,
            "entityControls": entity_controls,
            "databaseSha256": digest.hexdigest(),
            "completedAt": completed_at,
            "executionProfile": dict(execution_profile),
        }
        manifest["semanticFingerprint"] = semantic_fingerprint(
            manifest,
            volatile_pointers=(
                "/databaseSha256",
                "/completedAt",
                "/executionProfile",
            ),
        )
        temporary_manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, destination)
        os.replace(temporary_manifest, final_manifest)
        return TransformResult(
            candidate_database=destination,
            candidate_manifest=final_manifest,
            entity_counts=counts,
            semantic_fingerprint=manifest["semanticFingerprint"],
        )
    except Exception:
        if connection is not None:
            connection.close()
        temporary.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        raise


__all__ = [
    "TRANSFORM_MANIFEST_VERSION",
    "TRANSFORM_VERSION",
    "TransformError",
    "TransformResult",
    "build_canonical_candidate",
]
