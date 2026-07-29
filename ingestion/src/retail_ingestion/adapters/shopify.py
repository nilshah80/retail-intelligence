"""Shopify-shaped source adapter."""

from __future__ import annotations

from retail_contracts.money_sql import (
    exact_minor_sql,
    invalid_minor_sql,
)

from .base import AdapterContext, SourceAdapter
from .registry import register_adapter


@register_adapter
class ShopifyAdapter(SourceAdapter):
    source_system = "shopify"
    adapter_version = "shopify-adapter/1.1.0"
    raw_schema = "raw_shopify"

    def materialize_staging(self, context: AdapterContext) -> tuple[str, ...]:
        con = context.connection
        landing = context.landing
        source_schema_version = context.profile["sourceSchemaVersion"]
        profile_version = context.profile["profileVersion"]
        snapshot_id = landing["sourceSnapshotId"]
        native_snapshot_id = landing.get("nativeSnapshotId")
        con.execute("CREATE SCHEMA IF NOT EXISTS stage_data")

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_merchandise AS
            SELECT
                'shopify'::VARCHAR AS source_system,
                o._source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                l.id::VARCHAR AS native_record_id,
                o._market_id AS market_id,
                try_cast(o.processedAt AS TIMESTAMPTZ) AS known_as_of,
                'native_processed'::VARCHAR AS evidence_grade,
                'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                l._raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                'sale'::VARCHAR AS event_kind,
                o.id::VARCHAR AS source_sale_id,
                l.id::VARCHAR AS source_line_id,
                l.sku::VARCHAR AS sku_source_key,
                o.locationId::VARCHAR AS demand_location_source_key,
                o.channelId::VARCHAR AS channel_source_key,
                cast(
                    timezone(
                        o._business_timezone,
                        try_cast(o.createdAt AS TIMESTAMPTZ)
                    ) AS DATE
                ) AS business_date,
                try_cast(l.quantity AS BIGINT) AS units,
                CASE
                    WHEN try_cast(o.taxesIncluded AS BOOLEAN)
                    THEN (
                        try_cast(l.discountedUnitPrice AS DECIMAL(38, 6))
                        * try_cast(l.quantity AS BIGINT)
                    ) - coalesce(t.tax_amount_major, 0)
                    ELSE try_cast(l.discountedUnitPrice AS DECIMAL(38, 6))
                        * try_cast(l.quantity AS BIGINT)
                END AS net_amount_major,
                CASE
                    WHEN try_cast(o.taxesIncluded AS BOOLEAN)
                    THEN try_cast(l.discountedUnitPrice AS DECIMAL(38, 6))
                        * try_cast(l.quantity AS BIGINT)
                    ELSE (
                        try_cast(l.discountedUnitPrice AS DECIMAL(38, 6))
                        * try_cast(l.quantity AS BIGINT)
                    ) + coalesce(t.tax_amount_major, 0)
                END AS gross_amount_major,
                (
                    try_cast(l.originalUnitPrice AS DECIMAL(38, 6))
                    - try_cast(l.discountedUnitPrice AS DECIMAL(38, 6))
                ) * try_cast(l.quantity AS BIGINT) AS discount_amount_major,
                coalesce(t.tax_amount_major, 0)::DECIMAL(38, 6)
                    AS tax_amount_major,
                coalesce(l.currencyCode, o.currencyCode)::VARCHAR AS currency_code,
                l.promotionIds::VARCHAR AS promo_source_key,
                try_cast(o.taxesIncluded AS BOOLEAN) AS taxes_included,
                o._business_timezone AS business_timezone,
                l._raw_object_path AS raw_object_path
            FROM raw_shopify.orders AS o
            JOIN raw_shopify.order_lines AS l
              ON l.orderId = o.id
             AND l._source_instance = o._source_instance
            LEFT JOIN (
                SELECT
                    _source_instance,
                    orderLineId,
                    sum(try_cast(price AS DECIMAL(38, 6))) AS tax_amount_major
                FROM raw_shopify.tax_lines
                GROUP BY _source_instance, orderLineId
            ) AS t
              ON t.orderLineId = l.id
             AND t._source_instance = l._source_instance
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_products AS
            SELECT
                'shopify'::VARCHAR AS source_system,
                v._source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                v.id::VARCHAR AS native_record_id,
                v._market_id AS market_id,
                try_cast(v.createdAt AS TIMESTAMPTZ) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade,
                'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                v._raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                v.sku::VARCHAR AS sku_source_key,
                p.id::VARCHAR AS product_source_key,
                p.title::VARCHAR AS product_name,
                p.vendor::VARCHAR AS brand,
                p.productType::VARCHAR AS category_source_key,
                p.tags::VARCHAR AS tags,
                try_cast(v.price AS DECIMAL(38, 6)) AS reference_price_major,
                v.currencyCode::VARCHAR AS currency_code,
                try_cast(v.launchDate AS DATE) AS launch_date,
                try_cast(v.discontinueDate AS DATE) AS discontinue_date,
                v.measurementUnit::VARCHAR AS measurement_unit,
                try_cast(v.measurementValue AS DECIMAL(38, 6))
                    AS measurement_value,
                v._raw_object_path AS raw_object_path
            FROM raw_shopify.product_variants AS v
            JOIN raw_shopify.products AS p
              ON p.id = v.productId
             AND p._source_instance = v._source_instance
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_locations AS
            SELECT
                'shopify'::VARCHAR AS source_system,
                _source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                id::VARCHAR AS native_record_id,
                _market_id AS market_id,
                try_cast('{landing["landingTime"]}' AS TIMESTAMPTZ) AS known_as_of,
                'landing_backfill'::VARCHAR AS evidence_grade,
                'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                _raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                id::VARCHAR AS location_source_key,
                name::VARCHAR AS location_name,
                upper(locationType)::VARCHAR AS location_type,
                _market_currency_code AS currency_code,
                coalesce(nullif(timezone, ''), _business_timezone)::VARCHAR
                    AS timezone,
                provinceCode::VARCHAR AS region,
                city::VARCHAR AS city,
                active::VARCHAR AS active_raw,
                _raw_object_path AS raw_object_path
            FROM raw_shopify.locations
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_prices AS
            SELECT
                'shopify'::VARCHAR AS source_system,
                p._source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                concat(p.variantId, ':', p.effectiveDate)::VARCHAR
                    AS native_record_id,
                p._market_id AS market_id,
                try_cast('{landing["landingTime"]}' AS TIMESTAMPTZ) AS known_as_of,
                'landing_backfill'::VARCHAR AS evidence_grade,
                'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                p._raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                p.sku::VARCHAR AS sku_source_key,
                p.variantId::VARCHAR AS variant_source_key,
                try_cast(p.effectiveDate AS DATE) AS effective_date,
                try_cast(p.price AS DECIMAL(38, 6)) AS price_major,
                p.currencyCode::VARCHAR AS currency_code,
                p.priceReason::VARCHAR AS price_reason,
                p._raw_object_path AS raw_object_path
            FROM raw_shopify.price_history AS p
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_fulfillment AS
            SELECT
                'shopify'::VARCHAR AS source_system,
                fl._source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                fl.id::VARCHAR AS native_record_id,
                fl._market_id AS market_id,
                try_cast(f.createdAt AS TIMESTAMPTZ) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade,
                'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                fl._raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                fl.id::VARCHAR AS source_fulfillment_line_id,
                f.orderId::VARCHAR AS source_sale_id,
                fl.orderLineId::VARCHAR AS source_line_id,
                fl.sku::VARCHAR AS sku_source_key,
                o.locationId::VARCHAR AS demand_location_source_key,
                o.channelId::VARCHAR AS channel_source_key,
                coalesce(f.locationId, fl.warehouseKey)::VARCHAR
                    AS supply_location_source_key,
                cast(
                    timezone(
                        o._business_timezone,
                        try_cast(o.createdAt AS TIMESTAMPTZ)
                    ) AS DATE
                ) AS sale_date,
                coalesce(
                    try_cast(f.deliveredAt AS TIMESTAMPTZ),
                    try_cast(f.createdAt AS TIMESTAMPTZ)
                ) AS fulfilled_at,
                try_cast(fl.quantity AS BIGINT) AS units,
                f.id::VARCHAR AS shipment_id,
                f.shipmentStatus::VARCHAR AS carrier_status,
                fl._raw_object_path AS raw_object_path
            FROM raw_shopify.fulfillment_lines AS fl
            JOIN raw_shopify.fulfillments AS f
              ON f.id = fl.fulfillmentId
             AND f._source_instance = fl._source_instance
            JOIN raw_shopify.orders AS o
              ON o.id = f.orderId
             AND o._source_instance = f._source_instance
            WHERE upper(f.status) = 'SUCCESS'
            """
        )

        refund_amount = "try_cast(tx.amount AS DECIMAL(38, 6))"
        refund_minor = exact_minor_sql(refund_amount, "tx.currencyCode")
        refund_money_invalid = invalid_minor_sql(
            refund_amount, "tx.currencyCode"
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_adjustment AS
            WITH physical_returns AS (
                SELECT
                    'shopify'::VARCHAR AS source_system,
                    rl._source_instance AS source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    concat(rl.id, ':physical')::VARCHAR AS native_record_id,
                    rl._market_id AS market_id,
                    coalesce(
                        try_cast(r.processedAt AS TIMESTAMPTZ),
                        try_cast(r.requestedAt AS TIMESTAMPTZ)
                    ) AS known_as_of,
                    'native_processed'::VARCHAR AS evidence_grade,
                    'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                    rl._raw_object_hash AS raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    concat(rl.id, ':physical')::VARCHAR AS source_event_id,
                    r.id::VARCHAR AS source_parent_event_id,
                    r.orderId::VARCHAR AS source_sale_id,
                    rl.sku::VARCHAR AS sku_source_key,
                    o.locationId::VARCHAR AS demand_location_source_key,
                    o.channelId::VARCHAR AS channel_source_key,
                    cast(
                        timezone(
                            o._business_timezone,
                            try_cast(o.createdAt AS TIMESTAMPTZ)
                        ) AS DATE
                    ) AS sale_date,
                    cast(
                        timezone(
                            o._business_timezone,
                            coalesce(
                                try_cast(r.processedAt AS TIMESTAMPTZ),
                                try_cast(r.requestedAt AS TIMESTAMPTZ)
                            )
                        ) AS DATE
                    ) AS event_date,
                    'RETURN'::VARCHAR AS event_type,
                    try_cast(rl.processedQuantity AS BIGINT) AS units,
                    NULL::BIGINT AS amount_minor,
                    NULL::DECIMAL(38, 6) AS amount_major,
                    NULL::VARCHAR AS currency_code,
                    true::BOOLEAN AS money_precision_valid,
                    r.reason::VARCHAR AS reason_code,
                    rl._raw_object_path AS raw_object_path
                FROM raw_shopify.return_lines AS rl
                JOIN raw_shopify.returns AS r
                  ON r.id = rl.returnId
                 AND r._source_instance = rl._source_instance
                JOIN raw_shopify.orders AS o
                  ON o.id = r.orderId
                 AND o._source_instance = r._source_instance
                WHERE try_cast(rl.processedQuantity AS BIGINT) > 0
            ),
            refund_line_source AS (
                SELECT
                    tx._source_instance AS source_instance,
                    tx._market_id AS market_id,
                    tx.id::VARCHAR AS transaction_id,
                    tx.refundId::VARCHAR AS refund_id,
                    tx.orderId::VARCHAR AS source_sale_id,
                    tx.processedAt,
                    tx.currencyCode::VARCHAR AS currency_code,
                    tx.gateway::VARCHAR AS gateway,
                    tx._raw_object_hash AS raw_object_hash,
                    tx._raw_object_path AS raw_object_path,
                    rf.returnId::VARCHAR AS return_id,
                    r.reason::VARCHAR AS return_reason,
                    rl.id::VARCHAR AS return_line_id,
                    rl.sku::VARCHAR AS sku_source_key,
                    greatest(
                        try_cast(rl.processedQuantity AS BIGINT), 0
                    )::BIGINT AS line_weight,
                    o.locationId::VARCHAR AS demand_location_source_key,
                    o.channelId::VARCHAR AS channel_source_key,
                    o.createdAt,
                    o._business_timezone,
                    {refund_minor}::HUGEINT AS total_amount_minor,
                    NOT ({refund_money_invalid}) AS money_precision_valid
                FROM raw_shopify.refund_transactions AS tx
                JOIN raw_shopify.refunds AS rf
                  ON rf.id = tx.refundId
                 AND rf._source_instance = tx._source_instance
                JOIN raw_shopify.returns AS r
                  ON r.id = rf.returnId
                 AND r._source_instance = rf._source_instance
                JOIN raw_shopify.return_lines AS rl
                  ON rl.returnId = r.id
                 AND rl._source_instance = r._source_instance
                JOIN raw_shopify.orders AS o
                  ON o.id = tx.orderId
                 AND o._source_instance = tx._source_instance
                WHERE upper(tx.status) = 'SUCCESS'
                  AND upper(tx.kind) = 'REFUND'
                  AND upper(rf.status) = 'SUCCESS'
                  AND greatest(
                        try_cast(rl.processedQuantity AS BIGINT), 0
                      ) > 0
            ),
            refund_weighted AS (
                SELECT
                    *,
                    sum(line_weight) OVER (
                        PARTITION BY source_instance, transaction_id
                    )::HUGEINT AS total_weight
                FROM refund_line_source
            ),
            refund_base AS (
                SELECT
                    *,
                    (
                        total_amount_minor * line_weight
                    ) // total_weight AS base_minor,
                    (
                        total_amount_minor * line_weight
                    ) % total_weight AS remainder_minor
                FROM refund_weighted
            ),
            refund_ranked AS (
                SELECT
                    *,
                    total_amount_minor - sum(base_minor) OVER (
                        PARTITION BY source_instance, transaction_id
                    ) AS minor_units_left,
                    row_number() OVER (
                        PARTITION BY source_instance, transaction_id
                        ORDER BY remainder_minor DESC, return_line_id
                    ) AS remainder_rank
                FROM refund_base
            ),
            financial_refunds AS (
                SELECT
                    'shopify'::VARCHAR AS source_system,
                    source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    concat(transaction_id, ':', return_line_id)::VARCHAR
                        AS native_record_id,
                    market_id,
                    try_cast(processedAt AS TIMESTAMPTZ) AS known_as_of,
                    'native_processed'::VARCHAR AS evidence_grade,
                    'SHOPIFY_ACTUAL'::VARCHAR AS row_provenance,
                    raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    concat(transaction_id, ':', return_line_id)::VARCHAR
                        AS source_event_id,
                    refund_id::VARCHAR AS source_parent_event_id,
                    source_sale_id,
                    sku_source_key,
                    demand_location_source_key,
                    channel_source_key,
                    cast(
                        timezone(
                            _business_timezone,
                            try_cast(createdAt AS TIMESTAMPTZ)
                        ) AS DATE
                    ) AS sale_date,
                    cast(
                        timezone(
                            _business_timezone,
                            try_cast(processedAt AS TIMESTAMPTZ)
                        ) AS DATE
                    ) AS event_date,
                    'REFUND'::VARCHAR AS event_type,
                    NULL::BIGINT AS units,
                    (
                        base_minor
                        + CASE
                            WHEN remainder_rank <= minor_units_left THEN 1
                            ELSE 0
                          END
                    )::BIGINT AS amount_minor,
                    NULL::DECIMAL(38, 6) AS amount_major,
                    currency_code,
                    money_precision_valid,
                    coalesce(return_reason, gateway)::VARCHAR AS reason_code,
                    raw_object_path
                FROM refund_ranked
            )
            SELECT
                * FROM physical_returns
            UNION ALL BY NAME
            SELECT
                * FROM financial_refunds
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.shopify_customer_segment_counts AS
            SELECT
                'shopify'::VARCHAR AS source_system,
                _source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                _market_id AS market_id,
                segmentId::VARCHAR AS segment_id,
                count(*)::BIGINT AS customer_count,
                max(try_cast(createdAt AS TIMESTAMPTZ)) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version
            FROM raw_shopify.customers
            GROUP BY _source_instance, _market_id, segmentId
            """
        )
        return (
            "stage_data.shopify_merchandise",
            "stage_data.shopify_products",
            "stage_data.shopify_locations",
            "stage_data.shopify_prices",
            "stage_data.shopify_fulfillment",
            "stage_data.shopify_adjustment",
            "stage_data.shopify_customer_segment_counts",
        )


__all__ = ["ShopifyAdapter"]
