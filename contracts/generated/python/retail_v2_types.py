"""# Generated from contracts/retail_v2/schema.yaml; DO NOT EDIT."""

from typing import Literal, NotRequired, TypedDict

RuleOutcome = Literal["pass", "warning", "capability_downgrade", "critical"]
EvidenceGrade = Literal["native_observed", "native_processed", "native_posted_available", "native_extracted", "landing_backfill"]
EntityTier = Literal["t1_core", "t2_operational", "t3_control"]
DatasetClass = Literal["staged", "control_only", "fixture_only", "restricted_oracle", "ignored_by_profile", "unsupported"]
ColumnOutcome = Literal["gate_a_failure", "derive_with_provenance", "capability_downgrade", "quarantine", "declared_unsupported"]
GeoScopeType = Literal["market", "region", "location"]
MerchScopeType = Literal["sku", "dept", "category"]

class Sales(TypedDict):
    sku_id: str
    store_id: str
    channel_id: str
    date: str
    sales_version: int
    units: int
    gross_sales_amount: NotRequired[int]
    discount_amount: NotRequired[int]
    net_sales_amount: int
    tax_amount: NotRequired[int]
    currency_code: str
    net_price: NotRequired[int]
    promo_flag: NotRequired[bool]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class SalesAdjustments(TypedDict):
    adjustment_id: str
    adjustment_version: int
    source_sale_id: NotRequired[str]
    source_parent_event_id: NotRequired[str]
    sku_id: str
    store_id: str
    channel_id: str
    sale_date: str
    event_date: str
    event_type: Literal["physical_return", "post_fulfilment_cancellation", "financial_refund"]
    units: NotRequired[int]
    amount: NotRequired[int]
    currency_code: NotRequired[str]
    reason_code: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class SalesFulfillments(TypedDict):
    fulfillment_line_id: str
    fulfillment_version: int
    source_sale_id: str
    sku_id: str
    demand_location_id: str
    channel_id: str
    supply_location_id: str
    sale_date: str
    fulfilled_at: str
    units: int
    shipment_id: NotRequired[str]
    carrier_status: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class Products(TypedDict):
    sku_id: str
    dept_id: str
    category: str
    sub_cat: str
    pack_size: int
    product_name: NotRequired[str]
    brand: NotRequired[str]
    shelf_life_days: NotRequired[int]
    reference_cost: NotRequired[int]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class Locations(TypedDict):
    location_id: str
    name: NotRequired[str]
    type: Literal["store", "online", "dc", "3pl"]
    market_id: str
    currency_code: str
    timezone: str
    region: str
    city: NotRequired[str]
    parent_dc: NotRequired[str]
    format: NotRequired[str]
    active: bool
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class Stores(TypedDict):
    store_id: str
    market_id: str
    currency_code: str
    timezone: str
    region: str
    format: NotRequired[str]
    city: NotRequired[str]

class Channels(TypedDict):
    market_id: str
    channel_id: str
    name: str
    type: str
    description: NotRequired[str]
    active: bool
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class Calendar(TypedDict):
    market_id: str
    date: str
    weekday: NotRequired[str]
    month: NotRequired[int]
    year: NotRequired[int]
    working_day: NotRequired[bool]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class CalendarEvents(TypedDict):
    market_id: str
    geo_scope_type: Literal["market", "region", "location"]
    geo_scope_id: str
    date: str
    event_name: str
    event_type: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class SellPrices(TypedDict):
    sku_id: str
    store_id: str
    channel_id: str
    week_start: str
    net_price: int
    regular_price: NotRequired[int]
    promo_price: NotRequired[int]
    currency_code: str
    source_price_path_id: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class StockSnapshots(TypedDict):
    sku_id: str
    location_id: str
    snapshot_date: str
    on_hand_units: int
    on_order_units: int
    committed_units: NotRequired[int]
    reserved_units: NotRequired[int]
    damaged_units: NotRequired[int]
    in_transit_units: NotRequired[int]
    atp_units: NotRequired[int]
    atp_method: NotRequired[Literal["derived_buckets", "source_observed"]]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class SuppliersLeadtimes(TypedDict):
    supplier_id: str
    destination_location_id: str
    merch_scope_type: Literal["sku", "dept", "category"]
    merch_scope_id: str
    from_location_id: str | None
    effective_from: str
    lead_time_days: int
    moq: int
    pack_qty: int
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class AssortmentCalendar(TypedDict):
    sku_id: str
    store_id: str
    channel_id: str
    active_from: str
    active_to: NotRequired[str]
    derivation_method: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class PurchaseReceipts(TypedDict):
    receipt_id: str
    sku_id: str
    location_id: str
    supplier_id: str
    receipt_date: str
    qty: int
    unit_cost: int
    currency_code: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class InventoryCost(TypedDict):
    sku_id: str
    location_id: str
    as_of_date: str
    wac_cost: int
    currency_code: str
    on_hand_qty: int
    method: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class Competitors(TypedDict):
    market_id: str
    comp_id: str
    name: str
    type: str
    collection_method: str
    refresh: str
    currency_code: str
    compliance_ok: bool

class CompetitorProducts(TypedDict):
    market_id: str
    comp_id: str
    comp_product_id: str
    observed_at: str
    title: str
    brand: NotRequired[str]
    model: NotRequired[str]
    gtin: NotRequired[str]
    attributes: NotRequired[object]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class CompetitorPrices(TypedDict):
    market_id: str
    comp_id: str
    comp_product_id: str
    geo_scope_type: Literal["market", "region", "location"]
    geo_scope_id: str
    observed_at: str
    price: int
    currency_code: str
    in_stock_flag: bool
    promo_flag: bool
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class CompetitorMatches(TypedDict):
    match_id: str
    market_id: str
    sku_id: str
    comp_id: str
    comp_product_id: str
    match_confidence: str
    match_status: str
    matched_attributes: NotRequired[str]

class Promotions(TypedDict):
    market_id: str
    promo_id: str
    name: str
    type: str
    objective: NotRequired[str]
    offer_value: str
    currency_code: NotRequired[str]
    start_date: str
    end_date: str
    segment_id: NotRequired[str]
    status: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class PromotionScopes(TypedDict):
    market_id: str
    promo_id: str
    scope_row_id: str
    region: NotRequired[str]
    location_id: NotRequired[str]
    channel_id: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class PromotionMerchandiseTargets(TypedDict):
    market_id: str
    promo_id: str
    merch_scope_type: Literal["sku", "dept", "category"]
    merch_scope_id: str
    discount_pct: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class CustomerSegments(TypedDict):
    market_id: str
    segment_id: str
    name: str
    size: int
    share_pct: str
    description: NotRequired[str]
    as_of_date: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class WeatherActual(TypedDict):
    market_id: str
    geo_scope_type: Literal["market", "region", "location"]
    geo_scope_id: str
    date: str
    tavg_c: str
    precip_mm: str
    weather_code: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class WeatherForecast(TypedDict):
    market_id: str
    geo_scope_type: Literal["market", "region", "location"]
    geo_scope_id: str
    forecast_date: str
    target_date: str
    tavg_c: str
    precip_prob: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class LocalEvents(TypedDict):
    market_id: str
    geo_scope_type: Literal["market", "region", "location"]
    geo_scope_id: str
    date: str
    event_name: str
    event_type: str
    expected_impact: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class MacroIndex(TypedDict):
    market_id: str
    geo_scope_type: Literal["market", "region", "location"]
    geo_scope_id: str
    week_start: str
    index_name: str
    value: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class FXRates(TypedDict):
    base_ccy: str
    quote_ccy: str
    rate: str
    rate_date: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class MarketDisruptions(TypedDict):
    market_id: str
    disruption_id: str
    phase_id: str
    start_date: str
    end_date: str
    demand_factor: NotRequired[str]
    traffic_factor: NotRequired[str]
    supply_factor: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class InventoryBatches(TypedDict):
    batch_id: str
    sku_id: str
    location_id: str
    batch_qty: int
    mfg_date: NotRequired[str]
    expiry_date: NotRequired[str]
    receipt_date: str
    unit_cost: NotRequired[int]
    currency_code: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class InboundShipments(TypedDict):
    shipment_id: str
    sku_id: str
    from_location: NotRequired[str]
    to_location: str
    qty: int
    dispatch_date: NotRequired[str]
    expected_receipt_date: str
    status: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class TransferOrders(TypedDict):
    transfer_id: str
    sku_id: str
    from_location: str
    to_location: str
    qty: int
    reason: str
    expected_benefit_minor: NotRequired[int]
    currency_code: NotRequired[str]
    status: str

class Allocations(TypedDict):
    allocation_id: str
    sku_id: str
    pool_qty: int
    location_id: str
    requested_qty: int
    allocated_qty: int
    shortfall: int
    rule: str
    priority: str
    status: str

class WasteEvents(TypedDict):
    event_id: str
    sku_id: str
    location_id: str
    event_date: str
    units: int
    reason_code: str
    unit_cost: NotRequired[int]
    currency_code: NotRequired[str]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class WarehouseCapacitySnapshots(TypedDict):
    location_id: str
    snapshot_date: str
    capacity_units: int
    used_units: int
    blocked_units: NotRequired[int]
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class WmsInventoryComparisons(TypedDict):
    sku_id: str
    location_id: str
    snapshot_date: str
    erp_on_hand_units: int
    wms_on_hand_units: int
    difference_units: int
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class SupplierPerformance(TypedDict):
    supplier_id: str
    period: str
    otd_pct: str
    capacity_confirmed_pct: str
    lead_time_mean_days: str
    lead_time_std_days: str
    risk: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class ForecastVersions(TypedDict):
    version_id: str
    kind: str
    origin_date: str
    horizon_weeks: int
    created_by: str
    accuracy: NotRequired[str]
    bias: NotRequired[str]
    demand_units: int
    semantic_fingerprint: str
    status: str

class ForecastSeries(TypedDict):
    version_id: str
    sku_id: str
    store_id: str
    channel_id: str
    horizon_week: int
    yhat_p50: str
    yhat_p90: str
    confidence: str

class ForecastDrivers(TypedDict):
    version_id: str
    scope: str
    driver: str
    contribution_pct: str
    direction: str
    confidence: str

class PlannerAdjustments(TypedDict):
    adj_id: str
    sku_id: str
    store_id: str
    channel_id: str
    origin_date: str
    ai_forecast: str
    planner_forecast: str
    reason_code: str
    effective_period: str
    comment: NotRequired[str]
    actor: str
    status: str
    value_added_flag: NotRequired[bool]

class Users(TypedDict):
    user_id: str
    name: str
    role: str
    scope: str
    approval_limit_pct: str
    status: str

class Roles(TypedDict):
    role_id: str
    name: str
    approval_limit: str
    rbac_scope_type: str

class DataSources(TypedDict):
    source_id: str
    name: str
    type: str
    source_schema_version: str
    refresh: str
    profile_ref: str
    adapter_version: str
    transform_bundle_version: str
    enabled: bool

class SourceMappingConfigs(TypedDict):
    mapping_config_id: str
    source_id: str
    entity: str
    source_key: str
    canonical_key: str
    effective_from: str
    effective_to: NotRequired[str]
    version: int
    approved_by: str
    approved_at: str
    status: str

class IngestRuns(TypedDict):
    ingest_run_id: str
    source_id: str
    source_snapshot_id: str
    native_snapshot_id: NotRequired[str]
    raw_manifest_hash: str
    coverage_manifest_hash: str
    composite_manifest_hash: str
    profile_version: str
    adapter_version: str
    transform_version: str
    started_at: str
    completed_at: NotRequired[str]
    status: Literal["pass", "validated_partial", "fail"]
    raw_quality_pct: NotRequired[str]
    canonical_quality_pct: NotRequired[str]
    capability_mask: object
    curated_fingerprint: NotRequired[str]

class ReconciliationResults(TypedDict):
    reconciliation_id: str
    ingest_run_id: str
    entity: str
    metric: str
    raw_value: str
    filtered_value: str
    canonical_value: str
    difference: str
    tolerance: str
    status: str

class QualityViolations(TypedDict):
    violation_id: str
    ingest_run_id: str
    gate: str
    entity: str
    source_record_id: NotRequired[str]
    rule_id: str
    outcome: Literal["pass", "warning", "capability_downgrade", "critical"]
    affected_capability: NotRequired[str]
    reason_code: NotRequired[str]
    reason: str
    observed_at: str

class QuarantineRecords(TypedDict):
    quarantine_id: str
    ingest_run_id: str
    gate: str
    entity: str
    source_record_id: NotRequired[str]
    reason_code: str
    raw_record_ref: str
    payload_hash: str
    quarantined_at: str

class SourceCrosswalks(TypedDict):
    crosswalk_id: str
    ingest_run_id: str
    mapping_config_id: str
    source_id: str
    entity: str
    source_key: str
    canonical_key: str
    resolution_status: str
    known_as_of: str
    known_as_of_evidence_grade: EvidenceGrade

class ModelRegistry(TypedDict):
    model_id: str
    family: str
    version: str
    coverage: str
    accuracy: NotRequired[str]
    last_trained: str
    status: str
    fingerprint: str

class ModelDrift(TypedDict):
    model_id: str
    as_of: str
    drift_score: str
    threshold: str
    status: str

class AlertRules(TypedDict):
    rule_id: str
    category: str
    trigger: str
    threshold: str
    direction: str
    owner: str
    priority: str
    active: bool
