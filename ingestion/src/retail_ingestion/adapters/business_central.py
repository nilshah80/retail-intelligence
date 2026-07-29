"""Microsoft Dynamics 365 Business Central-shaped source adapter."""

from __future__ import annotations

from .base import AdapterContext, SourceAdapter
from .registry import register_adapter


@register_adapter
class BusinessCentralAdapter(SourceAdapter):
    source_system = "businessCentral"
    adapter_version = "business-central-adapter/1.1.0"
    raw_schema = "raw_business_central"

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
            CREATE OR REPLACE TABLE stage_data.bc_inventory AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
                _source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                concat(locationCode, ':', sku, ':', observedAt)::VARCHAR
                    AS native_record_id,
                _market_id AS market_id,
                try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade,
                'ERP_ACTUAL'::VARCHAR AS row_provenance,
                _raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                sku::VARCHAR AS sku_source_key,
                locationCode::VARCHAR AS location_source_key,
                cast(
                    timezone(
                        _business_timezone,
                        try_cast(observedAt AS TIMESTAMPTZ)
                    ) AS DATE
                ) AS snapshot_date,
                try_cast(inventory AS BIGINT) AS on_hand_units,
                try_cast(incomingInventory AS BIGINT) AS incoming_units,
                try_cast(committedInventory AS BIGINT) AS committed_units,
                try_cast(reservedInventory AS BIGINT) AS reserved_units,
                try_cast(damagedInventory AS BIGINT) AS damaged_units,
                try_cast(qualityControlInventory AS BIGINT)
                    AS quality_control_units,
                try_cast(safetyStockInventory AS BIGINT) AS safety_stock_units,
                try_cast(availableInventory AS BIGINT) AS source_observed_atp_units,
                _raw_object_path AS raw_object_path
            FROM raw_business_central.inventory_snapshots
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.bc_receipts AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
                rl._source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                rl.id::VARCHAR AS native_record_id,
                rl._market_id AS market_id,
                try_cast(r.postingDate AS TIMESTAMPTZ) AS known_as_of,
                'native_posted_available'::VARCHAR AS evidence_grade,
                'ERP_ACTUAL'::VARCHAR AS row_provenance,
                rl._raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                rl.id::VARCHAR AS source_receipt_id,
                rl.sku::VARCHAR AS sku_source_key,
                r.locationCode::VARCHAR AS location_source_key,
                po.vendorId::VARCHAR AS supplier_source_key,
                cast(
                    timezone(
                        r._business_timezone,
                        try_cast(r.postingDate AS TIMESTAMPTZ)
                    ) AS DATE
                ) AS receipt_date,
                try_cast(rl.quantity AS BIGINT) AS qty,
                try_cast(rl.unitCost AS DECIMAL(38, 6)) AS unit_cost_major,
                rl.currencyCode::VARCHAR AS currency_code,
                NULL::VARCHAR AS batch_id,
                NULL::DATE AS expiry_date,
                rl._raw_object_path AS raw_object_path
            FROM raw_business_central.warehouse_receipt_lines AS rl
            JOIN raw_business_central.warehouse_receipts AS r
              ON r.id = rl.documentId
             AND r._source_instance = rl._source_instance
            LEFT JOIN raw_business_central.purchase_orders AS po
              ON po.id = r.purchaseOrderId
             AND po._source_instance = r._source_instance
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.bc_products AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
                v._source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                v.id::VARCHAR AS native_record_id,
                v._market_id AS market_id,
                try_cast(v.introducedDate AS TIMESTAMPTZ) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade,
                'ERP_ACTUAL'::VARCHAR AS row_provenance,
                v._raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                v.sku::VARCHAR AS sku_source_key,
                i.id::VARCHAR AS product_source_key,
                coalesce(i.displayName, i.description)::VARCHAR AS product_name,
                i.brandName::VARCHAR AS brand,
                i.itemCategoryCode::VARCHAR AS category_source_key,
                try_cast(v.unitCost AS DECIMAL(38, 6)) AS reference_cost_major,
                v.currencyCode::VARCHAR AS currency_code,
                try_cast(v.introducedDate AS DATE) AS launch_date,
                try_cast(v.discontinuedDate AS DATE) AS discontinue_date,
                v.measurementUnit::VARCHAR AS measurement_unit,
                try_cast(v.measurementValue AS DECIMAL(38, 6))
                    AS measurement_value,
                v.unitOfMeasureCode::VARCHAR AS unit_of_measure_code,
                i.vendorId::VARCHAR AS supplier_source_key,
                v._raw_object_path AS raw_object_path
            FROM raw_business_central.item_variants AS v
            JOIN raw_business_central.items AS i
              ON i.id = v.itemId
             AND i._source_instance = v._source_instance
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.bc_supplier_terms AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
                _source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                concat(vendorId, ':', marketCode, ':', coalesce(categoryId, 'ALL'))
                    ::VARCHAR AS native_record_id,
                _market_id AS market_id,
                try_cast('{landing["landingTime"]}' AS TIMESTAMPTZ) AS known_as_of,
                'landing_backfill'::VARCHAR AS evidence_grade,
                'ERP_ACTUAL'::VARCHAR AS row_provenance,
                _raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                vendorId::VARCHAR AS supplier_source_key,
                NULL::VARCHAR AS destination_location_source_key,
                'category'::VARCHAR AS merch_scope_type,
                categoryId::VARCHAR AS merch_scope_id,
                NULL::VARCHAR AS from_location_source_key,
                cast('{landing["extractBoundary"]}' AS DATE) AS effective_from,
                try_cast(leadTimeDays AS INTEGER) AS lead_time_days,
                try_cast(minimumOrderQuantity AS BIGINT) AS moq,
                try_cast(orderMultiple AS BIGINT) AS pack_qty,
                _raw_object_path AS raw_object_path
            FROM raw_business_central.vendor_item_terms
            """
        )

        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.bc_sales_control AS
            SELECT
                i._source_instance AS source_instance,
                i._market_id AS market_id,
                i.id::VARCHAR AS source_sale_id,
                l.id::VARCHAR AS source_line_id,
                l.sku::VARCHAR AS sku_source_key,
                l.locationCode::VARCHAR AS demand_location_source_key,
                i.salesChannelCode::VARCHAR AS channel_source_key,
                try_cast(i.invoiceDate AS DATE) AS business_date,
                try_cast(i.postingDate AS TIMESTAMPTZ) AS known_as_of,
                try_cast(l.quantity AS BIGINT) AS units,
                try_cast(l.amountIncludingTax AS DECIMAL(38, 6))
                    AS gross_amount_major,
                try_cast(l.netAmount AS DECIMAL(38, 6)) AS net_amount_major,
                try_cast(l.taxAmount AS DECIMAL(38, 6)) AS tax_amount_major,
                l.currencyCode::VARCHAR AS currency_code,
                l._raw_object_hash AS raw_object_hash,
                l._raw_object_path AS raw_object_path
            FROM raw_business_central.sales_invoices AS i
            JOIN raw_business_central.sales_invoice_lines AS l
              ON l.documentId = i.id
             AND l._source_instance = i._source_instance
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TABLE stage_data.bc_inventory_cost AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
                _source_instance AS source_instance,
                '{source_schema_version}'::VARCHAR AS source_schema_version,
                '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                costLayerId::VARCHAR AS native_record_id,
                _market_id AS market_id,
                try_cast(effectiveDate AS TIMESTAMPTZ) AS known_as_of,
                'native_posted_available'::VARCHAR AS evidence_grade,
                'ERP_ACTUAL'::VARCHAR AS row_provenance,
                _raw_object_hash AS raw_object_hash,
                '{profile_version}'::VARCHAR AS profile_version,
                '{self.adapter_version}'::VARCHAR AS adapter_version,
                sku::VARCHAR AS sku_source_key,
                warehouseId::VARCHAR AS location_source_key,
                try_cast(effectiveDate AS DATE) AS as_of_date,
                try_cast(unitCost AS DECIMAL(38, 6)) AS unit_cost_major,
                currencyCode::VARCHAR AS currency_code,
                try_cast(quantity AS BIGINT) AS quantity,
                costingMethod::VARCHAR AS method,
                _raw_object_path AS raw_object_path
            FROM raw_business_central.item_cost_layers
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_inventory_batches AS
            SELECT
                _source_instance AS source_instance, _market_id AS market_id,
                batchId::VARCHAR AS batch_id, sku::VARCHAR AS sku_source_key,
                coalesce(warehouseId, locationCode)::VARCHAR
                    AS location_source_key,
                try_cast(quantityRemainingAtExtract AS BIGINT) AS batch_qty,
                try_cast(manufactureDate AS DATE) AS mfg_date,
                try_cast(expiryDate AS DATE) AS expiry_date,
                try_cast(receiptDate AS DATE) AS receipt_date,
                try_cast(receiptDate AS TIMESTAMPTZ) AS known_as_of,
                'native_posted_available'::VARCHAR AS evidence_grade,
                _raw_object_hash AS raw_object_hash,
                _raw_object_path AS raw_object_path
            FROM raw_business_central.item_batches
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_inbound_shipments AS
            SELECT
                s._source_instance AS source_instance,
                s._market_id AS market_id,
                s.shipmentId::VARCHAR AS shipment_id,
                l.sku::VARCHAR AS sku_source_key,
                NULL::VARCHAR AS from_location_source_key,
                s.warehouseId::VARCHAR AS to_location_source_key,
                CASE WHEN lower(s.status) = 'received'
                    THEN try_cast(l.receivedQuantity AS BIGINT)
                    ELSE try_cast(l.outstandingQuantity AS BIGINT)
                END AS qty,
                NULL::DATE AS dispatch_date,
                try_cast(s.expectedArrivalDate AS DATE) AS expected_receipt_date,
                s.status::VARCHAR AS status,
                coalesce(
                    try_cast(s.actualArrivalDate AS TIMESTAMPTZ),
                    try_cast(s.expectedArrivalDate AS TIMESTAMPTZ)
                ) AS known_as_of,
                CASE WHEN s.actualArrivalDate IS NULL
                    THEN 'landing_backfill' ELSE 'native_observed'
                END::VARCHAR AS evidence_grade,
                s._raw_object_hash AS raw_object_hash,
                s._raw_object_path AS raw_object_path
            FROM raw_business_central.inbound_shipments AS s
            JOIN raw_business_central.purchase_order_lines AS l
              ON l.documentId = s.purchaseOrderId
             AND l._source_instance = s._source_instance
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_transfer_orders AS
            SELECT
                h._source_instance AS source_instance,
                h._market_id AS market_id,
                concat(h.id, ':', l.id)::VARCHAR AS transfer_id,
                l.sku::VARCHAR AS sku_source_key,
                h.fromLocationCode::VARCHAR AS from_location_source_key,
                h.toLocationCode::VARCHAR AS to_location_source_key,
                try_cast(l.requestedQuantity AS BIGINT) AS qty,
                'network_rebalance'::VARCHAR AS reason,
                h.status::VARCHAR AS status
            FROM raw_business_central.transfer_orders AS h
            JOIN raw_business_central.transfer_order_lines AS l
              ON l.documentId = h.id
             AND l._source_instance = h._source_instance
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_waste_events AS
            SELECT
                _source_instance AS source_instance, _market_id AS market_id,
                wasteEventId::VARCHAR AS event_id, sku::VARCHAR AS sku_source_key,
                warehouseId::VARCHAR AS location_source_key,
                try_cast(eventDate AS DATE) AS event_date,
                try_cast(quantity AS BIGINT) AS units,
                reason::VARCHAR AS reason_code,
                try_cast(eventDate AS TIMESTAMPTZ) AS known_as_of,
                'native_posted_available'::VARCHAR AS evidence_grade
            FROM raw_business_central.waste_events
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_warehouse_capacity AS
            SELECT
                _source_instance AS source_instance, _market_id AS market_id,
                warehouseId::VARCHAR AS location_source_key,
                cast(
                    timezone(
                        _business_timezone,
                        try_cast(observedAt AS TIMESTAMPTZ)
                    ) AS DATE
                ) AS snapshot_date,
                try_cast(capacityUnits AS BIGINT) AS capacity_units,
                try_cast(onHandUnits AS BIGINT) AS used_units,
                try_cast(blockedUnits AS BIGINT) AS blocked_units,
                try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade
            FROM raw_business_central.warehouse_capacity
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_wms_comparisons AS
            SELECT
                _source_instance AS source_instance, _market_id AS market_id,
                sku::VARCHAR AS sku_source_key,
                warehouseId::VARCHAR AS location_source_key,
                cast(
                    timezone(
                        _business_timezone,
                        try_cast(observedAt AS TIMESTAMPTZ)
                    ) AS DATE
                ) AS snapshot_date,
                try_cast(erpOnHand AS BIGINT) AS erp_on_hand_units,
                try_cast(wmsOnHand AS BIGINT) AS wms_on_hand_units,
                try_cast(varianceQuantity AS BIGINT) AS difference_units,
                try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                'native_observed'::VARCHAR AS evidence_grade
            FROM raw_business_central.wms_inventory_comparisons
            """
        )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_supplier_performance AS
            SELECT
                _source_instance AS source_instance, _market_id AS market_id,
                vendorId::VARCHAR AS supplier_source_key,
                date_trunc('month', try_cast(actualDate AS DATE))::DATE AS period,
                avg(CASE WHEN lower(onTime) = 'true' THEN 1.0 ELSE 0.0 END)
                    AS otd_pct,
                avg(try_cast(fillRate AS DECIMAL(18, 8)))
                    AS capacity_confirmed_pct,
                avg(try_cast(leadTimeDays AS DECIMAL(18, 8)))
                    AS lead_time_mean_days,
                stddev_pop(try_cast(leadTimeDays AS DECIMAL(18, 8)))
                    AS lead_time_std_days,
                max(try_cast(actualDate AS TIMESTAMPTZ)) AS known_as_of,
                'native_posted_available'::VARCHAR AS evidence_grade
            FROM raw_business_central.supplier_performance
            GROUP BY _source_instance, _market_id, vendorId,
                     date_trunc('month', try_cast(actualDate AS DATE))
            """
        )
        return (
            "stage_data.bc_inventory",
            "stage_data.bc_receipts",
            "stage_data.bc_products",
            "stage_data.bc_supplier_terms",
            "stage_data.bc_sales_control",
            "stage_data.bc_inventory_cost",
            "stage_data.bc_inventory_batches",
            "stage_data.bc_inbound_shipments",
            "stage_data.bc_transfer_orders",
            "stage_data.bc_waste_events",
            "stage_data.bc_warehouse_capacity",
            "stage_data.bc_wms_comparisons",
            "stage_data.bc_supplier_performance",
        )


__all__ = ["BusinessCentralAdapter"]
