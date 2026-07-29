// Generated from contracts/retail_v2/schema.yaml; DO NOT EDIT.

package retailv2

type RuleOutcome string

const (
	RuleOutcomePass RuleOutcome = "pass"
	RuleOutcomeWarning RuleOutcome = "warning"
	RuleOutcomeCapabilityDowngrade RuleOutcome = "capability_downgrade"
	RuleOutcomeCritical RuleOutcome = "critical"
)

type EvidenceGrade string

const (
	EvidenceGradeNativeObserved EvidenceGrade = "native_observed"
	EvidenceGradeNativeProcessed EvidenceGrade = "native_processed"
	EvidenceGradeNativePostedAvailable EvidenceGrade = "native_posted_available"
	EvidenceGradeNativeExtracted EvidenceGrade = "native_extracted"
	EvidenceGradeLandingBackfill EvidenceGrade = "landing_backfill"
)

type EntityTier string

const (
	EntityTierT1Core EntityTier = "t1_core"
	EntityTierT2Operational EntityTier = "t2_operational"
	EntityTierT3Control EntityTier = "t3_control"
)

type DatasetClass string

const (
	DatasetClassStaged DatasetClass = "staged"
	DatasetClassControlOnly DatasetClass = "control_only"
	DatasetClassFixtureOnly DatasetClass = "fixture_only"
	DatasetClassRestrictedOracle DatasetClass = "restricted_oracle"
	DatasetClassIgnoredByProfile DatasetClass = "ignored_by_profile"
	DatasetClassUnsupported DatasetClass = "unsupported"
)

type ColumnOutcome string

const (
	ColumnOutcomeGateAFailure ColumnOutcome = "gate_a_failure"
	ColumnOutcomeDeriveWithProvenance ColumnOutcome = "derive_with_provenance"
	ColumnOutcomeCapabilityDowngrade ColumnOutcome = "capability_downgrade"
	ColumnOutcomeQuarantine ColumnOutcome = "quarantine"
	ColumnOutcomeDeclaredUnsupported ColumnOutcome = "declared_unsupported"
)

type GeoScopeType string

const (
	GeoScopeTypeMarket GeoScopeType = "market"
	GeoScopeTypeRegion GeoScopeType = "region"
	GeoScopeTypeLocation GeoScopeType = "location"
)

type MerchScopeType string

const (
	MerchScopeTypeSKU MerchScopeType = "sku"
	MerchScopeTypeDept MerchScopeType = "dept"
	MerchScopeTypeCategory MerchScopeType = "category"
)

type Sales struct {
	SKUID string `json:"sku_id"`
	StoreID string `json:"store_id"`
	ChannelID string `json:"channel_id"`
	Date string `json:"date"`
	SalesVersion int64 `json:"sales_version"`
	Units int64 `json:"units"`
	GrossSalesAmount *int64 `json:"gross_sales_amount,omitempty"`
	DiscountAmount *int64 `json:"discount_amount,omitempty"`
	NetSalesAmount int64 `json:"net_sales_amount"`
	TaxAmount *int64 `json:"tax_amount,omitempty"`
	CurrencyCode string `json:"currency_code"`
	NetPrice *int64 `json:"net_price,omitempty"`
	PromoFlag *bool `json:"promo_flag,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type SalesAdjustments struct {
	AdjustmentID string `json:"adjustment_id"`
	AdjustmentVersion int64 `json:"adjustment_version"`
	SourceSaleID *string `json:"source_sale_id,omitempty"`
	SourceParentEventID *string `json:"source_parent_event_id,omitempty"`
	SKUID string `json:"sku_id"`
	StoreID string `json:"store_id"`
	ChannelID string `json:"channel_id"`
	SaleDate string `json:"sale_date"`
	EventDate string `json:"event_date"`
	EventType string `json:"event_type"`
	Units *int64 `json:"units,omitempty"`
	Amount *int64 `json:"amount,omitempty"`
	CurrencyCode *string `json:"currency_code,omitempty"`
	ReasonCode *string `json:"reason_code,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type SalesFulfillments struct {
	FulfillmentLineID string `json:"fulfillment_line_id"`
	FulfillmentVersion int64 `json:"fulfillment_version"`
	SourceSaleID string `json:"source_sale_id"`
	SKUID string `json:"sku_id"`
	DemandLocationID string `json:"demand_location_id"`
	ChannelID string `json:"channel_id"`
	SupplyLocationID string `json:"supply_location_id"`
	SaleDate string `json:"sale_date"`
	FulfilledAt string `json:"fulfilled_at"`
	Units int64 `json:"units"`
	ShipmentID *string `json:"shipment_id,omitempty"`
	CarrierStatus *string `json:"carrier_status,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type Products struct {
	SKUID string `json:"sku_id"`
	DeptID string `json:"dept_id"`
	Category string `json:"category"`
	SubCat string `json:"sub_cat"`
	PackSize int64 `json:"pack_size"`
	ProductName *string `json:"product_name,omitempty"`
	Brand *string `json:"brand,omitempty"`
	ShelfLifeDays *int32 `json:"shelf_life_days,omitempty"`
	ReferenceCost *int64 `json:"reference_cost,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type Locations struct {
	LocationID string `json:"location_id"`
	Name *string `json:"name,omitempty"`
	Type string `json:"type"`
	MarketID string `json:"market_id"`
	CurrencyCode string `json:"currency_code"`
	Timezone string `json:"timezone"`
	Region string `json:"region"`
	City *string `json:"city,omitempty"`
	ParentDc *string `json:"parent_dc,omitempty"`
	Format *string `json:"format,omitempty"`
	Active bool `json:"active"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type Stores struct {
	StoreID string `json:"store_id"`
	MarketID string `json:"market_id"`
	CurrencyCode string `json:"currency_code"`
	Timezone string `json:"timezone"`
	Region string `json:"region"`
	Format *string `json:"format,omitempty"`
	City *string `json:"city,omitempty"`
}

type Channels struct {
	MarketID string `json:"market_id"`
	ChannelID string `json:"channel_id"`
	Name string `json:"name"`
	Type string `json:"type"`
	Description *string `json:"description,omitempty"`
	Active bool `json:"active"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type Calendar struct {
	MarketID string `json:"market_id"`
	Date string `json:"date"`
	Weekday *string `json:"weekday,omitempty"`
	Month *int32 `json:"month,omitempty"`
	Year *int32 `json:"year,omitempty"`
	WorkingDay *bool `json:"working_day,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type CalendarEvents struct {
	MarketID string `json:"market_id"`
	GeoScopeType string `json:"geo_scope_type"`
	GeoScopeID string `json:"geo_scope_id"`
	Date string `json:"date"`
	EventName string `json:"event_name"`
	EventType string `json:"event_type"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type SellPrices struct {
	SKUID string `json:"sku_id"`
	StoreID string `json:"store_id"`
	ChannelID string `json:"channel_id"`
	WeekStart string `json:"week_start"`
	NetPrice int64 `json:"net_price"`
	RegularPrice *int64 `json:"regular_price,omitempty"`
	PromoPrice *int64 `json:"promo_price,omitempty"`
	CurrencyCode string `json:"currency_code"`
	SourcePricePathID *string `json:"source_price_path_id,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type StockSnapshots struct {
	SKUID string `json:"sku_id"`
	LocationID string `json:"location_id"`
	SnapshotDate string `json:"snapshot_date"`
	OnHandUnits int64 `json:"on_hand_units"`
	OnOrderUnits int64 `json:"on_order_units"`
	CommittedUnits *int64 `json:"committed_units,omitempty"`
	ReservedUnits *int64 `json:"reserved_units,omitempty"`
	DamagedUnits *int64 `json:"damaged_units,omitempty"`
	InTransitUnits *int64 `json:"in_transit_units,omitempty"`
	AtpUnits *int64 `json:"atp_units,omitempty"`
	AtpMethod *string `json:"atp_method,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type SuppliersLeadtimes struct {
	SupplierID string `json:"supplier_id"`
	DestinationLocationID string `json:"destination_location_id"`
	MerchScopeType string `json:"merch_scope_type"`
	MerchScopeID string `json:"merch_scope_id"`
	FromLocationID *string `json:"from_location_id"`
	EffectiveFrom string `json:"effective_from"`
	LeadTimeDays int32 `json:"lead_time_days"`
	Moq int64 `json:"moq"`
	PackQty int64 `json:"pack_qty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type AssortmentCalendar struct {
	SKUID string `json:"sku_id"`
	StoreID string `json:"store_id"`
	ChannelID string `json:"channel_id"`
	ActiveFrom string `json:"active_from"`
	ActiveTo *string `json:"active_to,omitempty"`
	DerivationMethod string `json:"derivation_method"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type PurchaseReceipts struct {
	ReceiptID string `json:"receipt_id"`
	SKUID string `json:"sku_id"`
	LocationID string `json:"location_id"`
	SupplierID string `json:"supplier_id"`
	ReceiptDate string `json:"receipt_date"`
	Qty int64 `json:"qty"`
	UnitCost int64 `json:"unit_cost"`
	CurrencyCode string `json:"currency_code"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type InventoryCost struct {
	SKUID string `json:"sku_id"`
	LocationID string `json:"location_id"`
	AsOfDate string `json:"as_of_date"`
	WacCost int64 `json:"wac_cost"`
	CurrencyCode string `json:"currency_code"`
	OnHandQty int64 `json:"on_hand_qty"`
	Method string `json:"method"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type Competitors struct {
	MarketID string `json:"market_id"`
	CompID string `json:"comp_id"`
	Name string `json:"name"`
	Type string `json:"type"`
	CollectionMethod string `json:"collection_method"`
	Refresh string `json:"refresh"`
	CurrencyCode string `json:"currency_code"`
	ComplianceOk bool `json:"compliance_ok"`
}

type CompetitorProducts struct {
	MarketID string `json:"market_id"`
	CompID string `json:"comp_id"`
	CompProductID string `json:"comp_product_id"`
	ObservedAt string `json:"observed_at"`
	Title string `json:"title"`
	Brand *string `json:"brand,omitempty"`
	Model *string `json:"model,omitempty"`
	Gtin *string `json:"gtin,omitempty"`
	Attributes map[string]any `json:"attributes,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type CompetitorPrices struct {
	MarketID string `json:"market_id"`
	CompID string `json:"comp_id"`
	CompProductID string `json:"comp_product_id"`
	GeoScopeType string `json:"geo_scope_type"`
	GeoScopeID string `json:"geo_scope_id"`
	ObservedAt string `json:"observed_at"`
	Price int64 `json:"price"`
	CurrencyCode string `json:"currency_code"`
	InStockFlag bool `json:"in_stock_flag"`
	PromoFlag bool `json:"promo_flag"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type CompetitorMatches struct {
	MatchID string `json:"match_id"`
	MarketID string `json:"market_id"`
	SKUID string `json:"sku_id"`
	CompID string `json:"comp_id"`
	CompProductID string `json:"comp_product_id"`
	MatchConfidence string `json:"match_confidence"`
	MatchStatus string `json:"match_status"`
	MatchedAttributes *string `json:"matched_attributes,omitempty"`
}

type Promotions struct {
	MarketID string `json:"market_id"`
	PromoID string `json:"promo_id"`
	Name string `json:"name"`
	Type string `json:"type"`
	Objective *string `json:"objective,omitempty"`
	OfferValue string `json:"offer_value"`
	CurrencyCode *string `json:"currency_code,omitempty"`
	StartDate string `json:"start_date"`
	EndDate string `json:"end_date"`
	SegmentID *string `json:"segment_id,omitempty"`
	Status string `json:"status"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type PromotionScopes struct {
	MarketID string `json:"market_id"`
	PromoID string `json:"promo_id"`
	ScopeRowID string `json:"scope_row_id"`
	Region *string `json:"region,omitempty"`
	LocationID *string `json:"location_id,omitempty"`
	ChannelID *string `json:"channel_id,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type PromotionMerchandiseTargets struct {
	MarketID string `json:"market_id"`
	PromoID string `json:"promo_id"`
	MerchScopeType string `json:"merch_scope_type"`
	MerchScopeID string `json:"merch_scope_id"`
	DiscountPct string `json:"discount_pct"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type CustomerSegments struct {
	MarketID string `json:"market_id"`
	SegmentID string `json:"segment_id"`
	Name string `json:"name"`
	Size int64 `json:"size"`
	SharePct string `json:"share_pct"`
	Description *string `json:"description,omitempty"`
	AsOfDate string `json:"as_of_date"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type WeatherActual struct {
	MarketID string `json:"market_id"`
	GeoScopeType string `json:"geo_scope_type"`
	GeoScopeID string `json:"geo_scope_id"`
	Date string `json:"date"`
	TavgC string `json:"tavg_c"`
	PrecipMm string `json:"precip_mm"`
	WeatherCode *string `json:"weather_code,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type WeatherForecast struct {
	MarketID string `json:"market_id"`
	GeoScopeType string `json:"geo_scope_type"`
	GeoScopeID string `json:"geo_scope_id"`
	ForecastDate string `json:"forecast_date"`
	TargetDate string `json:"target_date"`
	TavgC string `json:"tavg_c"`
	PrecipProb string `json:"precip_prob"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type LocalEvents struct {
	MarketID string `json:"market_id"`
	GeoScopeType string `json:"geo_scope_type"`
	GeoScopeID string `json:"geo_scope_id"`
	Date string `json:"date"`
	EventName string `json:"event_name"`
	EventType string `json:"event_type"`
	ExpectedImpact *string `json:"expected_impact,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type MacroIndex struct {
	MarketID string `json:"market_id"`
	GeoScopeType string `json:"geo_scope_type"`
	GeoScopeID string `json:"geo_scope_id"`
	WeekStart string `json:"week_start"`
	IndexName string `json:"index_name"`
	Value string `json:"value"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type FXRates struct {
	BaseCcy string `json:"base_ccy"`
	QuoteCcy string `json:"quote_ccy"`
	Rate string `json:"rate"`
	RateDate string `json:"rate_date"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type MarketDisruptions struct {
	MarketID string `json:"market_id"`
	DisruptionID string `json:"disruption_id"`
	PhaseID string `json:"phase_id"`
	StartDate string `json:"start_date"`
	EndDate string `json:"end_date"`
	DemandFactor *string `json:"demand_factor,omitempty"`
	TrafficFactor *string `json:"traffic_factor,omitempty"`
	SupplyFactor *string `json:"supply_factor,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type InventoryBatches struct {
	BatchID string `json:"batch_id"`
	SKUID string `json:"sku_id"`
	LocationID string `json:"location_id"`
	BatchQty int64 `json:"batch_qty"`
	MfgDate *string `json:"mfg_date,omitempty"`
	ExpiryDate *string `json:"expiry_date,omitempty"`
	ReceiptDate string `json:"receipt_date"`
	UnitCost *int64 `json:"unit_cost,omitempty"`
	CurrencyCode *string `json:"currency_code,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type InboundShipments struct {
	ShipmentID string `json:"shipment_id"`
	SKUID string `json:"sku_id"`
	FromLocation *string `json:"from_location,omitempty"`
	ToLocation string `json:"to_location"`
	Qty int64 `json:"qty"`
	DispatchDate *string `json:"dispatch_date,omitempty"`
	ExpectedReceiptDate string `json:"expected_receipt_date"`
	Status string `json:"status"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type TransferOrders struct {
	TransferID string `json:"transfer_id"`
	SKUID string `json:"sku_id"`
	FromLocation string `json:"from_location"`
	ToLocation string `json:"to_location"`
	Qty int64 `json:"qty"`
	Reason string `json:"reason"`
	ExpectedBenefitMinor *int64 `json:"expected_benefit_minor,omitempty"`
	CurrencyCode *string `json:"currency_code,omitempty"`
	Status string `json:"status"`
}

type Allocations struct {
	AllocationID string `json:"allocation_id"`
	SKUID string `json:"sku_id"`
	PoolQty int64 `json:"pool_qty"`
	LocationID string `json:"location_id"`
	RequestedQty int64 `json:"requested_qty"`
	AllocatedQty int64 `json:"allocated_qty"`
	Shortfall int64 `json:"shortfall"`
	Rule string `json:"rule"`
	Priority string `json:"priority"`
	Status string `json:"status"`
}

type WasteEvents struct {
	EventID string `json:"event_id"`
	SKUID string `json:"sku_id"`
	LocationID string `json:"location_id"`
	EventDate string `json:"event_date"`
	Units int64 `json:"units"`
	ReasonCode string `json:"reason_code"`
	UnitCost *int64 `json:"unit_cost,omitempty"`
	CurrencyCode *string `json:"currency_code,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type WarehouseCapacitySnapshots struct {
	LocationID string `json:"location_id"`
	SnapshotDate string `json:"snapshot_date"`
	CapacityUnits int64 `json:"capacity_units"`
	UsedUnits int64 `json:"used_units"`
	BlockedUnits *int64 `json:"blocked_units,omitempty"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type WmsInventoryComparisons struct {
	SKUID string `json:"sku_id"`
	LocationID string `json:"location_id"`
	SnapshotDate string `json:"snapshot_date"`
	ErpOnHandUnits int64 `json:"erp_on_hand_units"`
	WmsOnHandUnits int64 `json:"wms_on_hand_units"`
	DifferenceUnits int64 `json:"difference_units"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type SupplierPerformance struct {
	SupplierID string `json:"supplier_id"`
	Period string `json:"period"`
	OtdPct string `json:"otd_pct"`
	CapacityConfirmedPct string `json:"capacity_confirmed_pct"`
	LeadTimeMeanDays string `json:"lead_time_mean_days"`
	LeadTimeStdDays string `json:"lead_time_std_days"`
	Risk string `json:"risk"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type ForecastVersions struct {
	VersionID string `json:"version_id"`
	Kind string `json:"kind"`
	OriginDate string `json:"origin_date"`
	HorizonWeeks int32 `json:"horizon_weeks"`
	CreatedBy string `json:"created_by"`
	Accuracy *string `json:"accuracy,omitempty"`
	Bias *string `json:"bias,omitempty"`
	DemandUnits int64 `json:"demand_units"`
	SemanticFingerprint string `json:"semantic_fingerprint"`
	Status string `json:"status"`
}

type ForecastSeries struct {
	VersionID string `json:"version_id"`
	SKUID string `json:"sku_id"`
	StoreID string `json:"store_id"`
	ChannelID string `json:"channel_id"`
	HorizonWeek int32 `json:"horizon_week"`
	YhatP50 string `json:"yhat_p50"`
	YhatP90 string `json:"yhat_p90"`
	Confidence string `json:"confidence"`
}

type ForecastDrivers struct {
	VersionID string `json:"version_id"`
	Scope string `json:"scope"`
	Driver string `json:"driver"`
	ContributionPct string `json:"contribution_pct"`
	Direction string `json:"direction"`
	Confidence string `json:"confidence"`
}

type PlannerAdjustments struct {
	AdjID string `json:"adj_id"`
	SKUID string `json:"sku_id"`
	StoreID string `json:"store_id"`
	ChannelID string `json:"channel_id"`
	OriginDate string `json:"origin_date"`
	AiForecast string `json:"ai_forecast"`
	PlannerForecast string `json:"planner_forecast"`
	ReasonCode string `json:"reason_code"`
	EffectivePeriod string `json:"effective_period"`
	Comment *string `json:"comment,omitempty"`
	Actor string `json:"actor"`
	Status string `json:"status"`
	ValueAddedFlag *bool `json:"value_added_flag,omitempty"`
}

type Users struct {
	UserID string `json:"user_id"`
	Name string `json:"name"`
	Role string `json:"role"`
	Scope string `json:"scope"`
	ApprovalLimitPct string `json:"approval_limit_pct"`
	Status string `json:"status"`
}

type Roles struct {
	RoleID string `json:"role_id"`
	Name string `json:"name"`
	ApprovalLimit string `json:"approval_limit"`
	RbacScopeType string `json:"rbac_scope_type"`
}

type DataSources struct {
	SourceID string `json:"source_id"`
	Name string `json:"name"`
	Type string `json:"type"`
	SourceSchemaVersion string `json:"source_schema_version"`
	Refresh string `json:"refresh"`
	ProfileRef string `json:"profile_ref"`
	AdapterVersion string `json:"adapter_version"`
	TransformBundleVersion string `json:"transform_bundle_version"`
	Enabled bool `json:"enabled"`
}

type SourceMappingConfigs struct {
	MappingConfigID string `json:"mapping_config_id"`
	SourceID string `json:"source_id"`
	Entity string `json:"entity"`
	SourceKey string `json:"source_key"`
	CanonicalKey string `json:"canonical_key"`
	EffectiveFrom string `json:"effective_from"`
	EffectiveTo *string `json:"effective_to,omitempty"`
	Version int64 `json:"version"`
	ApprovedBy string `json:"approved_by"`
	ApprovedAt string `json:"approved_at"`
	Status string `json:"status"`
}

type IngestRuns struct {
	IngestRunID string `json:"ingest_run_id"`
	SourceID string `json:"source_id"`
	SourceSnapshotID string `json:"source_snapshot_id"`
	NativeSnapshotID *string `json:"native_snapshot_id,omitempty"`
	RawManifestHash string `json:"raw_manifest_hash"`
	CoverageManifestHash string `json:"coverage_manifest_hash"`
	CompositeManifestHash string `json:"composite_manifest_hash"`
	ProfileVersion string `json:"profile_version"`
	AdapterVersion string `json:"adapter_version"`
	TransformVersion string `json:"transform_version"`
	StartedAt string `json:"started_at"`
	CompletedAt *string `json:"completed_at,omitempty"`
	Status string `json:"status"`
	RawQualityPct *string `json:"raw_quality_pct,omitempty"`
	CanonicalQualityPct *string `json:"canonical_quality_pct,omitempty"`
	CapabilityMask map[string]any `json:"capability_mask"`
	CuratedFingerprint *string `json:"curated_fingerprint,omitempty"`
}

type ReconciliationResults struct {
	ReconciliationID string `json:"reconciliation_id"`
	IngestRunID string `json:"ingest_run_id"`
	Entity string `json:"entity"`
	Metric string `json:"metric"`
	RawValue string `json:"raw_value"`
	FilteredValue string `json:"filtered_value"`
	CanonicalValue string `json:"canonical_value"`
	Difference string `json:"difference"`
	Tolerance string `json:"tolerance"`
	Status string `json:"status"`
}

type QualityViolations struct {
	ViolationID string `json:"violation_id"`
	IngestRunID string `json:"ingest_run_id"`
	Gate string `json:"gate"`
	Entity string `json:"entity"`
	SourceRecordID *string `json:"source_record_id,omitempty"`
	RuleID string `json:"rule_id"`
	Outcome string `json:"outcome"`
	AffectedCapability *string `json:"affected_capability,omitempty"`
	ReasonCode *string `json:"reason_code,omitempty"`
	Reason string `json:"reason"`
	ObservedAt string `json:"observed_at"`
}

type QuarantineRecords struct {
	QuarantineID string `json:"quarantine_id"`
	IngestRunID string `json:"ingest_run_id"`
	Gate string `json:"gate"`
	Entity string `json:"entity"`
	SourceRecordID *string `json:"source_record_id,omitempty"`
	ReasonCode string `json:"reason_code"`
	RawRecordRef string `json:"raw_record_ref"`
	PayloadHash string `json:"payload_hash"`
	QuarantinedAt string `json:"quarantined_at"`
}

type SourceCrosswalks struct {
	CrosswalkID string `json:"crosswalk_id"`
	IngestRunID string `json:"ingest_run_id"`
	MappingConfigID string `json:"mapping_config_id"`
	SourceID string `json:"source_id"`
	Entity string `json:"entity"`
	SourceKey string `json:"source_key"`
	CanonicalKey string `json:"canonical_key"`
	ResolutionStatus string `json:"resolution_status"`
	KnownAsOf string `json:"known_as_of"`
	KnownAsOfEvidenceGrade EvidenceGrade `json:"known_as_of_evidence_grade"`
}

type ModelRegistry struct {
	ModelID string `json:"model_id"`
	Family string `json:"family"`
	Version string `json:"version"`
	Coverage string `json:"coverage"`
	Accuracy *string `json:"accuracy,omitempty"`
	LastTrained string `json:"last_trained"`
	Status string `json:"status"`
	Fingerprint string `json:"fingerprint"`
}

type ModelDrift struct {
	ModelID string `json:"model_id"`
	AsOf string `json:"as_of"`
	DriftScore string `json:"drift_score"`
	Threshold string `json:"threshold"`
	Status string `json:"status"`
}

type AlertRules struct {
	RuleID string `json:"rule_id"`
	Category string `json:"category"`
	Trigger string `json:"trigger"`
	Threshold string `json:"threshold"`
	Direction string `json:"direction"`
	Owner string `json:"owner"`
	Priority string `json:"priority"`
	Active bool `json:"active"`
}
