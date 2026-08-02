"""Microsoft Dynamics 365 Business Central-shaped source adapter."""

from __future__ import annotations

from .base import AdapterContext, SourceAdapter
from .registry import register_adapter


@register_adapter
class BusinessCentralAdapter(SourceAdapter):
    source_system = "businessCentral"
    adapter_version = "business-central-adapter/1.2.0"
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
        if "store_inventory_snapshots" in {
            row[0]
            for row in con.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'raw_business_central'
                """
            ).fetchall()
        }:
            # Source contract v13. Store rows flow into the SAME staging role as
            # the DC rows -- one inventory relation, one canonical transform --
            # so the two echelons cannot drift on ATP semantics. The store file
            # carries assortment/residual context the DC file does not; those
            # columns ride into canonical via the shared transform's passthrough
            # of source-observed ATP and are re-derived downstream where needed.
            con.execute(
                f"""
                INSERT INTO stage_data.bc_inventory
                SELECT
                    'businessCentral'::VARCHAR,
                    _source_instance,
                    '{source_schema_version}'::VARCHAR,
                    '{snapshot_id}'::VARCHAR,
                    {repr(native_snapshot_id)}::VARCHAR,
                    concat(locationCode, ':', sku, ':', observedAt)::VARCHAR,
                    _market_id,
                    try_cast(observedAt AS TIMESTAMPTZ),
                    'native_observed'::VARCHAR,
                    'ERP_ACTUAL'::VARCHAR,
                    _raw_object_hash,
                    '{profile_version}'::VARCHAR,
                    '{self.adapter_version}'::VARCHAR,
                    sku::VARCHAR,
                    locationCode::VARCHAR,
                    cast(
                        timezone(
                            _business_timezone,
                            try_cast(observedAt AS TIMESTAMPTZ)
                        ) AS DATE
                    ),
                    try_cast(inventory AS BIGINT),
                    try_cast(incomingInventory AS BIGINT),
                    try_cast(committedInventory AS BIGINT),
                    try_cast(reservedInventory AS BIGINT),
                    try_cast(damagedInventory AS BIGINT),
                    try_cast(qualityControlInventory AS BIGINT),
                    try_cast(safetyStockInventory AS BIGINT),
                    try_cast(availableInventory AS BIGINT),
                    _raw_object_path
                FROM raw_business_central.store_inventory_snapshots
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
                'businessCentral'::VARCHAR AS source_system,
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
                'businessCentral'::VARCHAR AS source_system,
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
                'businessCentral'::VARCHAR AS source_system,
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
        # Source contract v13. These three relations exist only when the source
        # run was generated with the storeInventory feature; DuckDB CREATE OR
        # REPLACE over a missing raw relation would fail, so presence is probed
        # first and an empty typed table is created otherwise -- a v12 landing
        # stays processable and simply carries no v13 evidence.
        v13_relations = {
            row[0]
            for row in con.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'raw_business_central'
                """
            ).fetchall()
        }
        if "inbound_status_events" in v13_relations:
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.bc_inbound_status_events AS
                SELECT
                    'businessCentral'::VARCHAR AS source_system,
                    _source_instance AS source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    concat(shipmentId, ':', sku, ':', status)::VARCHAR
                        AS native_record_id,
                    _market_id AS market_id,
                    -- observedAt is when the status became knowable, and it is
                    -- strictly after statusEffectiveAt by construction. Deriving
                    -- known_as_of from the effective time instead would repeat
                    -- the fulfillment defect this contract exists to close.
                    try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                    'native_observed'::VARCHAR AS evidence_grade,
                    'ERP_ACTUAL'::VARCHAR AS row_provenance,
                    _raw_object_hash AS raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    shipmentId::VARCHAR AS source_shipment_id,
                    sku::VARCHAR AS sku_source_key,
                    locationCode::VARCHAR AS location_source_key,
                    NULL::VARCHAR AS from_location_source_key,
                    try_cast(quantity AS BIGINT) AS qty,
                    lower(status)::VARCHAR AS status,
                    try_cast(statusEffectiveAt AS TIMESTAMPTZ)
                        AS status_effective_at,
                    try_cast(expectedReceiptDate AS DATE) AS expected_date,
                    _raw_object_path AS raw_object_path
                FROM raw_business_central.inbound_status_events
                """
            )
        else:
            con.execute(
                """
                CREATE OR REPLACE TABLE stage_data.bc_inbound_status_events (
                    source_system VARCHAR, source_instance VARCHAR,
                    source_schema_version VARCHAR, source_snapshot_id VARCHAR,
                    native_snapshot_id VARCHAR, native_record_id VARCHAR,
                    market_id VARCHAR, known_as_of TIMESTAMPTZ,
                    evidence_grade VARCHAR, row_provenance VARCHAR,
                    raw_object_hash VARCHAR, profile_version VARCHAR,
                    adapter_version VARCHAR, source_shipment_id VARCHAR,
                    sku_source_key VARCHAR, location_source_key VARCHAR,
                    from_location_source_key VARCHAR, qty BIGINT,
                    status VARCHAR, status_effective_at TIMESTAMPTZ,
                    expected_date DATE, raw_object_path VARCHAR
                )
                """
            )
        if "store_transfer_events" in v13_relations:
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.bc_inventory_transfer_events AS
                SELECT
                    'businessCentral'::VARCHAR AS source_system,
                    _source_instance AS source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    concat(transferId, ':', status)::VARCHAR AS native_record_id,
                    _market_id AS market_id,
                    try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                    'native_observed'::VARCHAR AS evidence_grade,
                    'ERP_ACTUAL'::VARCHAR AS row_provenance,
                    _raw_object_hash AS raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    transferId::VARCHAR AS source_transfer_id,
                    sku::VARCHAR AS sku_source_key,
                    fromLocationCode::VARCHAR AS from_location_source_key,
                    toLocationCode::VARCHAR AS to_location_source_key,
                    try_cast(quantity AS BIGINT) AS qty,
                    lower(status)::VARCHAR AS status,
                    try_cast(statusEffectiveAt AS TIMESTAMPTZ)
                        AS status_effective_at,
                    try_cast(unitCostAmountMinor AS BIGINT) AS unit_cost_minor,
                    currencyCode::VARCHAR AS currency_code,
                    _raw_object_path AS raw_object_path
                FROM raw_business_central.store_transfer_events
                """
            )
        else:
            con.execute(
                """
                CREATE OR REPLACE TABLE stage_data.bc_inventory_transfer_events (
                    source_system VARCHAR, source_instance VARCHAR,
                    source_schema_version VARCHAR, source_snapshot_id VARCHAR,
                    native_snapshot_id VARCHAR, native_record_id VARCHAR,
                    market_id VARCHAR, known_as_of TIMESTAMPTZ,
                    evidence_grade VARCHAR, row_provenance VARCHAR,
                    raw_object_hash VARCHAR, profile_version VARCHAR,
                    adapter_version VARCHAR, source_transfer_id VARCHAR,
                    sku_source_key VARCHAR, from_location_source_key VARCHAR,
                    to_location_source_key VARCHAR, qty BIGINT, status VARCHAR,
                    status_effective_at TIMESTAMPTZ, unit_cost_minor BIGINT,
                    currency_code VARCHAR, raw_object_path VARCHAR
                )
                """
            )
        if "supply_terms" in v13_relations:
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.bc_supply_terms AS
                SELECT
                    'businessCentral'::VARCHAR AS source_system,
                    _source_instance AS source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    concat(
                        vendorId, ':', destinationLocationCode, ':',
                        merchScopeType, ':', merchScopeId
                    )::VARCHAR AS native_record_id,
                    _market_id AS market_id,
                    try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                    'native_extracted'::VARCHAR AS evidence_grade,
                    'ERP_ACTUAL'::VARCHAR AS row_provenance,
                    _raw_object_hash AS raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    destinationLocationCode::VARCHAR
                        AS destination_location_source_key,
                    originKind::VARCHAR AS origin_kind,
                    vendorId::VARCHAR AS origin_source_key,
                    merchScopeType::VARCHAR AS merch_scope_type,
                    merchScopeId::VARCHAR AS merch_scope_id,
                    try_cast(effectiveFrom AS DATE) AS effective_from,
                    try_cast(leadTimeDays AS INTEGER) AS lead_time_days,
                    try_cast(leadTimeStdDevDays AS DECIMAL(8, 2))
                        AS lead_time_std_days,
                    try_cast(minimumOrderQuantity AS BIGINT) AS moq_units,
                    try_cast(orderMultiple AS BIGINT) AS pack_size_units,
                    _raw_object_path AS raw_object_path
                FROM raw_business_central.supply_terms
                """
            )
        else:
            con.execute(
                """
                CREATE OR REPLACE TABLE stage_data.bc_supply_terms (
                    source_system VARCHAR, source_instance VARCHAR,
                    source_schema_version VARCHAR, source_snapshot_id VARCHAR,
                    native_snapshot_id VARCHAR, native_record_id VARCHAR,
                    market_id VARCHAR, known_as_of TIMESTAMPTZ,
                    evidence_grade VARCHAR, row_provenance VARCHAR,
                    raw_object_hash VARCHAR, profile_version VARCHAR,
                    adapter_version VARCHAR,
                    destination_location_source_key VARCHAR,
                    origin_kind VARCHAR, origin_source_key VARCHAR,
                    merch_scope_type VARCHAR, merch_scope_id VARCHAR,
                    effective_from DATE, lead_time_days INTEGER,
                    lead_time_std_days DECIMAL(8, 2), moq_units BIGINT,
                    pack_size_units BIGINT, raw_object_path VARCHAR
                )
                """
            )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_transfer_orders AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
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
                'businessCentral'::VARCHAR AS source_system,
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
        if "store_waste_events" in v13_relations:
            # Source contract v13, same posture as store_inventory_snapshots
            # above: store rows join the SAME staging role as the warehouse rows.
            # Two waste relations would mean two canonical vocabularies for one
            # physical event, and the store echelon's write-offs are the larger
            # stream -- 317,056 units against india-west's 140,787 at the DCs.
            #
            # Leaving them out is what made the weekly replay irreconcilable: the
            # generator expires store stock and emits the event, but nothing
            # landed it, so reconstructed on-hand rose ~589 units/week above
            # every observed snapshot. That is the whole of the residual.
            #
            # `expiry` is normalised to the warehouse relation's `expired`: one
            # controlled enum per role, and the two source spellings name the
            # same cause. `observedAt` is a real 23:00 market-local instant, so
            # it is better availability evidence than the warehouse rows' date
            # cast and is used directly.
            con.execute(
                """
                INSERT INTO stage_data.bc_waste_events
                SELECT
                    'businessCentral'::VARCHAR,
                    _source_instance, _market_id,
                    eventId::VARCHAR, sku::VARCHAR,
                    locationCode::VARCHAR,
                    try_cast(eventDate AS DATE),
                    try_cast(quantity AS BIGINT),
                    CASE reasonCode WHEN 'expiry' THEN 'expired'
                                    ELSE reasonCode END::VARCHAR,
                    try_cast(observedAt AS TIMESTAMPTZ),
                    'native_posted_available'::VARCHAR
                FROM raw_business_central.store_waste_events
                """
            )
        # Source contract v13. A store sale the shelf could not cover, which the
        # DC fulfilled instead -- so `sales` records the whole sale while the
        # store's own stock drops only by servedFromStoreUnits. Nothing published
        # the difference, and without it a shelf-level reconstruction charges the
        # DC's share to the store: 123,894 units of india-west drift over 52
        # weeks on the tightened network, which is the whole of the replay
        # oracle's residual.
        #
        # Its own role rather than a join onto an existing one: this is not a
        # movement of stock, it is the record of a movement that did NOT happen at
        # this echelon, and no existing canonical vocabulary carries that.
        if "store_stockout_events" in v13_relations:
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.bc_store_shortfall_events AS
                SELECT
                    'businessCentral'::VARCHAR AS source_system,
                    _source_instance AS source_instance,
                    '{source_schema_version}'::VARCHAR AS source_schema_version,
                    '{snapshot_id}'::VARCHAR AS source_snapshot_id,
                    {repr(native_snapshot_id)}::VARCHAR AS native_snapshot_id,
                    eventId::VARCHAR AS native_record_id,
                    _market_id AS market_id,
                    -- observedAt is a real 23:00 market-local instant, strictly
                    -- after the eventDate it describes, so it is the availability
                    -- evidence rather than a cast of the date.
                    try_cast(observedAt AS TIMESTAMPTZ) AS known_as_of,
                    'native_observed'::VARCHAR AS evidence_grade,
                    'ERP_ACTUAL'::VARCHAR AS row_provenance,
                    _raw_object_hash AS raw_object_hash,
                    '{profile_version}'::VARCHAR AS profile_version,
                    '{self.adapter_version}'::VARCHAR AS adapter_version,
                    sku::VARCHAR AS sku_source_key,
                    locationCode::VARCHAR AS location_source_key,
                    servedFromLocationCode::VARCHAR
                        AS supply_location_source_key,
                    channelId::VARCHAR AS channel_source_key,
                    try_cast(eventDate AS DATE) AS event_date,
                    try_cast(demandUnits AS BIGINT) AS demand_units,
                    try_cast(servedFromStoreUnits AS BIGINT) AS served_units,
                    try_cast(shortfallUnits AS BIGINT) AS shortfall_units,
                    _raw_object_path AS raw_object_path
                FROM raw_business_central.store_stockout_events
                """
            )
        else:
            con.execute(
                """
                CREATE OR REPLACE TABLE stage_data.bc_store_shortfall_events (
                    source_system VARCHAR, source_instance VARCHAR,
                    source_schema_version VARCHAR, source_snapshot_id VARCHAR,
                    native_snapshot_id VARCHAR, native_record_id VARCHAR,
                    market_id VARCHAR, known_as_of TIMESTAMPTZ,
                    evidence_grade VARCHAR, row_provenance VARCHAR,
                    raw_object_hash VARCHAR, profile_version VARCHAR,
                    adapter_version VARCHAR, sku_source_key VARCHAR,
                    location_source_key VARCHAR,
                    supply_location_source_key VARCHAR,
                    channel_source_key VARCHAR, event_date DATE,
                    demand_units BIGINT, served_units BIGINT,
                    shortfall_units BIGINT, raw_object_path VARCHAR
                )
                """
            )
        con.execute(
            """
            CREATE OR REPLACE TABLE stage_data.bc_warehouse_capacity AS
            SELECT
                'businessCentral'::VARCHAR AS source_system,
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
                'businessCentral'::VARCHAR AS source_system,
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
                'businessCentral'::VARCHAR AS source_system,
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
            "stage_data.bc_supply_terms",
            "stage_data.bc_inbound_status_events",
            "stage_data.bc_inventory_transfer_events",
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
