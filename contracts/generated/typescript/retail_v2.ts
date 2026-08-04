// Generated from contracts/retail_v2/schema.yaml; DO NOT EDIT.

export type Int64String = string;

export type RuleOutcome = "pass" | "warning" | "capability_downgrade" | "critical";
export type EvidenceGrade = "native_observed" | "native_processed" | "native_posted_available" | "native_extracted" | "landing_backfill";
export type EntityTier = "t1_core" | "t2_operational" | "t3_control";
export type DatasetClass = "staged" | "control_only" | "fixture_only" | "restricted_oracle" | "ignored_by_profile" | "unsupported";
export type ColumnOutcome = "gate_a_failure" | "derive_with_provenance" | "capability_downgrade" | "quarantine" | "declared_unsupported";
export type GeoScopeType = "market" | "region" | "location";
export type MerchScopeType = "sku" | "dept" | "category";

export interface Sales {
  sku_id: string;
  store_id: string;
  channel_id: string;
  date: string;
  sales_version: Int64String;
  units: Int64String;
  gross_sales_amount?: Int64String;
  discount_amount?: Int64String;
  net_sales_amount: Int64String;
  tax_amount?: Int64String;
  currency_code: string;
  net_price?: Int64String;
  promo_flag?: boolean;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface SalesAdjustments {
  adjustment_id: string;
  adjustment_version: Int64String;
  source_sale_id?: string;
  source_parent_event_id?: string;
  sku_id: string;
  store_id: string;
  channel_id: string;
  sale_date: string;
  event_date: string;
  event_type: "physical_return" | "post_fulfilment_cancellation" | "financial_refund";
  units?: Int64String;
  amount?: Int64String;
  currency_code?: string;
  reason_code?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface SalesFulfillments {
  fulfillment_line_id: string;
  fulfillment_version: Int64String;
  source_sale_id: string;
  sku_id: string;
  demand_location_id: string;
  channel_id: string;
  supply_location_id: string;
  sale_date: string;
  fulfilled_at: string;
  units: Int64String;
  shipment_id?: string;
  carrier_status?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface Products {
  sku_id: string;
  dept_id: string;
  category: string;
  sub_cat: string;
  pack_size: Int64String;
  product_name?: string;
  brand?: string;
  shelf_life_days?: number;
  reference_cost?: Int64String;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface Locations {
  location_id: string;
  name?: string;
  type: "store" | "online" | "dc" | "3pl";
  market_id: string;
  currency_code: string;
  timezone: string;
  region: string;
  city?: string;
  parent_dc?: string;
  format?: string;
  active: boolean;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface Stores {
  store_id: string;
  market_id: string;
  currency_code: string;
  timezone: string;
  region: string;
  format?: string;
  city?: string;
}

export interface Channels {
  market_id: string;
  channel_id: string;
  name: string;
  type: string;
  description?: string;
  active: boolean;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface Calendar {
  market_id: string;
  date: string;
  weekday?: string;
  month?: number;
  year?: number;
  working_day?: boolean;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface CalendarEvents {
  market_id: string;
  geo_scope_type: "market" | "region" | "location";
  geo_scope_id: string;
  date: string;
  event_name: string;
  event_type: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface SellPrices {
  sku_id: string;
  store_id: string;
  channel_id: string;
  week_start: string;
  net_price: Int64String;
  regular_price?: Int64String;
  promo_price?: Int64String;
  currency_code: string;
  source_price_path_id?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface StockSnapshots {
  sku_id: string;
  location_id: string;
  snapshot_date: string;
  on_hand_units: Int64String;
  on_order_units: Int64String;
  committed_units?: Int64String;
  reserved_units?: Int64String;
  damaged_units?: Int64String;
  in_transit_units?: Int64String;
  atp_units?: Int64String;
  atp_method?: "derived_buckets" | "source_observed";
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface SuppliersLeadtimes {
  supplier_id: string;
  destination_location_id: string;
  merch_scope_type: "sku" | "dept" | "category";
  merch_scope_id: string;
  from_location_id: string | null;
  effective_from: string;
  lead_time_days: number;
  moq: Int64String;
  pack_qty: Int64String;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface AssortmentCalendar {
  sku_id: string;
  store_id: string;
  channel_id: string;
  active_from: string;
  active_to?: string;
  derivation_method: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface PurchaseReceipts {
  receipt_id: string;
  sku_id: string;
  location_id: string;
  supplier_id: string;
  receipt_date: string;
  qty: Int64String;
  unit_cost: Int64String;
  currency_code: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface InventoryCost {
  sku_id: string;
  location_id: string;
  as_of_date: string;
  wac_cost: Int64String;
  currency_code: string;
  on_hand_qty: Int64String;
  method: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface Competitors {
  market_id: string;
  comp_id: string;
  name: string;
  type: string;
  collection_method: string;
  refresh: string;
  currency_code: string;
  compliance_ok: boolean;
}

export interface CompetitorProducts {
  market_id: string;
  comp_id: string;
  comp_product_id: string;
  observed_at: string;
  title: string;
  brand?: string;
  model?: string;
  gtin?: string;
  attributes?: unknown;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface CompetitorPrices {
  market_id: string;
  comp_id: string;
  comp_product_id: string;
  geo_scope_type: "market" | "region" | "location";
  geo_scope_id: string;
  observed_at: string;
  price: Int64String;
  currency_code: string;
  in_stock_flag: boolean;
  promo_flag: boolean;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface CompetitorMatches {
  match_id: string;
  market_id: string;
  sku_id: string;
  comp_id: string;
  comp_product_id: string;
  match_confidence: string;
  match_status: string;
  matched_attributes?: string;
}

export interface Promotions {
  market_id: string;
  promo_id: string;
  name: string;
  type: string;
  objective?: string;
  offer_value: string;
  currency_code?: string;
  start_date: string;
  end_date: string;
  segment_id?: string;
  status: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface PromotionScopes {
  market_id: string;
  promo_id: string;
  scope_row_id: string;
  region?: string;
  location_id?: string;
  channel_id?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface PromotionMerchandiseTargets {
  market_id: string;
  promo_id: string;
  merch_scope_type: "sku" | "dept" | "category";
  merch_scope_id: string;
  discount_pct: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface CustomerSegments {
  market_id: string;
  segment_id: string;
  name: string;
  size: Int64String;
  share_pct: string;
  description?: string;
  as_of_date: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface WeatherActual {
  market_id: string;
  geo_scope_type: "market" | "region" | "location";
  geo_scope_id: string;
  date: string;
  tavg_c: string;
  precip_mm: string;
  weather_code?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface WeatherForecast {
  market_id: string;
  geo_scope_type: "market" | "region" | "location";
  geo_scope_id: string;
  forecast_date: string;
  target_date: string;
  tavg_c: string;
  precip_prob: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface LocalEvents {
  market_id: string;
  geo_scope_type: "market" | "region" | "location";
  geo_scope_id: string;
  date: string;
  event_name: string;
  event_type: string;
  expected_impact?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface MacroIndex {
  market_id: string;
  geo_scope_type: "market" | "region" | "location";
  geo_scope_id: string;
  week_start: string;
  index_name: string;
  value: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface FXRates {
  base_ccy: string;
  quote_ccy: string;
  rate: string;
  rate_date: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface MarketDisruptions {
  market_id: string;
  disruption_id: string;
  phase_id: string;
  start_date: string;
  end_date: string;
  demand_factor?: string;
  traffic_factor?: string;
  supply_factor?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface InventoryBatches {
  batch_id: string;
  sku_id: string;
  location_id: string;
  batch_qty: Int64String;
  mfg_date?: string;
  expiry_date?: string;
  receipt_date: string;
  unit_cost?: Int64String;
  currency_code?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface InboundShipments {
  shipment_id: string;
  sku_id: string;
  from_location?: string;
  to_location: string;
  qty: Int64String;
  dispatch_date?: string;
  expected_receipt_date: string;
  status: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface ServiceLanes {
  lane_id: string;
  market_id: string;
  lane_type: "replenishment" | "customer_fulfillment";
  demand_location_id: string;
  channel_id: string | null;
  supply_location_id: string;
  priority_rank: number;
  transit_days: number;
  effective_from: string;
  effective_to?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface InboundShipmentStatusEvents {
  shipment_id: string;
  sku_id: string;
  from_location?: string;
  to_location: string;
  qty: Int64String;
  status: "on_order" | "in_transit" | "received" | "cancelled" | "exception";
  status_effective_at: string;
  expected_receipt_date?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface InventoryTransferEvents {
  transfer_id: string;
  sku_id: string;
  from_location_id: string;
  to_location_id: string;
  qty: Int64String;
  status: "created" | "dispatched" | "in_transit" | "received" | "cancelled";
  status_effective_at: string;
  unit_cost_minor?: Int64String;
  currency_code?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface SupplyTerms {
  destination_location_id: string;
  origin_kind: "external_supplier" | "internal_location";
  origin_id: string;
  merch_scope_type: MerchScopeType;
  merch_scope_id: string;
  effective_from: string;
  effective_to?: string;
  lead_time_days: number;
  lead_time_std_days?: string;
  moq: Int64String;
  pack_qty: Int64String;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface TransferOrders {
  transfer_id: string;
  sku_id: string;
  from_location: string;
  to_location: string;
  qty: Int64String;
  reason: string;
  expected_benefit_minor?: Int64String;
  currency_code?: string;
  status: string;
}

export interface Allocations {
  allocation_id: string;
  sku_id: string;
  pool_qty: Int64String;
  location_id: string;
  requested_qty: Int64String;
  allocated_qty: Int64String;
  shortfall: Int64String;
  rule: string;
  priority: string;
  status: string;
}

export interface WasteEvents {
  event_id: string;
  sku_id: string;
  location_id: string;
  event_date: string;
  units: Int64String;
  reason_code: string;
  unit_cost?: Int64String;
  currency_code?: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface WarehouseCapacitySnapshots {
  location_id: string;
  snapshot_date: string;
  capacity_units: Int64String;
  used_units: Int64String;
  blocked_units?: Int64String;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface WmsInventoryComparisons {
  sku_id: string;
  location_id: string;
  snapshot_date: string;
  erp_on_hand_units: Int64String;
  wms_on_hand_units: Int64String;
  difference_units: Int64String;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface Suppliers {
  supplier_id: string;
  market_id: string;
  supplier_name: string;
  supplier_number: string;
  brand_name: string;
  currency_code: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface SupplierPerformance {
  supplier_id: string;
  period: string;
  otd_pct: string;
  capacity_confirmed_pct: string;
  lead_time_mean_days: string;
  lead_time_std_days: string;
  risk: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface ForecastVersions {
  version_id: string;
  kind: string;
  origin_date: string;
  horizon_weeks: number;
  created_by: string;
  accuracy?: string;
  bias?: string;
  demand_units: Int64String;
  semantic_fingerprint: string;
  status: string;
}

export interface ForecastSeries {
  version_id: string;
  sku_id: string;
  store_id: string;
  channel_id: string;
  horizon_week: number;
  yhat_p50: string;
  yhat_p90: string;
  confidence: string;
}

export interface ForecastDrivers {
  version_id: string;
  scope: string;
  driver: string;
  contribution_pct: string;
  direction: string;
  confidence: string;
}

export interface PlannerAdjustments {
  adj_id: string;
  sku_id: string;
  store_id: string;
  channel_id: string;
  origin_date: string;
  ai_forecast: string;
  planner_forecast: string;
  reason_code: string;
  effective_period: string;
  comment?: string;
  actor: string;
  status: string;
  value_added_flag?: boolean;
}

export interface Users {
  user_id: string;
  name: string;
  role: string;
  scope: string;
  approval_limit_pct: string;
  status: string;
}

export interface Roles {
  role_id: string;
  name: string;
  approval_limit: string;
  rbac_scope_type: string;
}

export interface DataSources {
  source_id: string;
  name: string;
  type: string;
  source_schema_version: string;
  refresh: string;
  profile_ref: string;
  adapter_version: string;
  transform_bundle_version: string;
  enabled: boolean;
}

export interface SourceMappingConfigs {
  mapping_config_id: string;
  source_id: string;
  entity: string;
  source_key: string;
  canonical_key: string;
  effective_from: string;
  effective_to?: string;
  version: Int64String;
  approved_by: string;
  approved_at: string;
  status: string;
}

export interface IngestRuns {
  ingest_run_id: string;
  source_id: string;
  source_snapshot_id: string;
  native_snapshot_id?: string;
  raw_manifest_hash: string;
  coverage_manifest_hash: string;
  composite_manifest_hash: string;
  profile_version: string;
  adapter_version: string;
  transform_version: string;
  started_at: string;
  completed_at?: string;
  status: "pass" | "validated_partial" | "fail";
  raw_quality_pct?: string;
  canonical_quality_pct?: string;
  capability_mask: unknown;
  curated_fingerprint?: string;
}

export interface ReconciliationResults {
  reconciliation_id: string;
  ingest_run_id: string;
  entity: string;
  metric: string;
  raw_value: string;
  filtered_value: string;
  canonical_value: string;
  difference: string;
  tolerance: string;
  status: string;
}

export interface QualityViolations {
  violation_id: string;
  ingest_run_id: string;
  gate: string;
  entity: string;
  source_record_id?: string;
  rule_id: string;
  outcome: "pass" | "warning" | "capability_downgrade" | "critical";
  affected_capability?: string;
  reason_code?: string;
  reason: string;
  observed_at: string;
}

export interface QuarantineRecords {
  quarantine_id: string;
  ingest_run_id: string;
  gate: string;
  entity: string;
  source_record_id?: string;
  reason_code: string;
  raw_record_ref: string;
  payload_hash: string;
  quarantined_at: string;
}

export interface SourceCrosswalks {
  crosswalk_id: string;
  ingest_run_id: string;
  mapping_config_id: string;
  source_id: string;
  entity: string;
  source_key: string;
  canonical_key: string;
  resolution_status: string;
  known_as_of: string;
  known_as_of_evidence_grade: EvidenceGrade;
}

export interface ModelRegistry {
  model_id: string;
  family: string;
  version: string;
  coverage: string;
  accuracy?: string;
  last_trained: string;
  status: string;
  fingerprint: string;
}

export interface ModelDrift {
  model_id: string;
  as_of: string;
  drift_score: string;
  threshold: string;
  status: string;
}

export interface AlertRules {
  rule_id: string;
  category: string;
  trigger: string;
  threshold: string;
  direction: string;
  owner: string;
  priority: string;
  active: boolean;
}
