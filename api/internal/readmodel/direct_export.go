package readmodel

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

const MaxDirectExportRows = 1_000

var directExportCurrencyPattern = regexp.MustCompile(`^(?:[A-Z]{3}|MULTI)$`)
var directExportRowIDPattern = regexp.MustCompile(`^(?:forecast|inventory)_[0-9a-f]{20}$`)

type DirectExportRequest struct {
	ExportID       string
	Scope          string
	ExpectedCount  int
	ScopeRevision  string
	SelectedIDs    []string
	Currency       string
	StoreID        string
	ChannelScope   string
	ForecastQuery  ForecastQuery
	InventoryQuery InventoryQuery
}

type DirectExport struct {
	Bytes         []byte
	Filename      string
	Count         int
	ExportID      string
	ScopeRevision string
}

type directExportColumn struct {
	header            string
	field             string
	unavailableReason string
}

type directExportSpec struct {
	prefix  string
	kind    string
	path    string
	card    string
	columns []directExportColumn
}

func directColumns(values ...string) []directExportColumn {
	columns := make([]directExportColumn, 0, len(values)/2)
	for index := 0; index < len(values); index += 2 {
		columns = append(columns, directExportColumn{header: values[index], field: values[index+1]})
	}
	return columns
}

var directExportRegistry = map[string]directExportSpec{
	"exportForecastBtn": {
		prefix: "demand-forecast", kind: "forecast", path: "/api/v1/forecast/series",
		columns: directColumns(
			"sku_id", "skuId", "product_name", "productName", "store", "storeName",
			"channel", "channelId", "category", "category", "horizon_weeks", "horizonWeeks",
			"baseline", "baseline", "ai_forecast", "aiForecast", "last_actual", "lastActual",
			"accuracy", "accuracy", "bias", "bias", "confidence", "confidence",
			"confidence_state", "confidenceState", "interval_covered_through_horizon", "intervalCoveredThroughHorizon",
			"interval_withheld_weeks", "intervalWithheldWeeks", "primary_driver", "primaryDriver",
			"data_quality", "dataQuality", "status", "status",
		),
	},
	"inventoryExportBtn": {
		prefix: "inventory-overview", kind: "inventory", path: "/api/v1/inventory/overview", card: "locations",
		columns: directColumns(
			"Location", "locationName", "Type", "locationType", "Inventory Value", "valueMinor",
			"Availability", "availabilityPct", "Days of Supply", "daysOfSupply", "Stock-out Risk", "stockoutRisk",
			"Overstock", "overstockPct", "Priority Action", "priorityAction",
		),
	},
	"storeInventoryExportBtn": {
		prefix: "store-inventory", kind: "inventory", path: "/api/v1/inventory/stores", card: "locations",
		columns: directColumns(
			"Store", "locationName", "Availability", "availabilityPct", "DoS", "daysOfSupply",
			"Overstock", "overstockPct", "Understock", "understockPct", "Action", "priorityAction",
		),
	},
	"warehouseExportBtn": {
		prefix: "warehouse-inventory", kind: "inventory", path: "/api/v1/inventory/warehouses", card: "warehouses",
		columns: directColumns(
			"Warehouse", "locationName", "Inventory Value", "valueMinor", "Capacity Utilization", "capacityUtilization",
			"Fill Rate", "fillRate", "Blocked Stock", "blockedValueMinor", "Delayed Receipts", "delayedReceipts", "Action", "warehouseAction",
		),
	},
	"ageingExportBtn": {
		prefix: "inventory-ageing", kind: "inventory", path: "/api/v1/inventory/ageing",
		columns: directColumns(
			"SKU / Product", "productName", "Category", "categoryLabel", "Age", "ageBucket", "Units", "onHandUnits",
			"Value", "valueMinor", "Sell-through", "sellThroughPct", "Recommended Action", "actionLabel", "Priority", "ageingPriority",
		),
	},
	"transferExportBtn": {
		prefix: "inventory-transfers", kind: "inventory", path: "/api/v1/inventory/transfers",
		columns: directColumns(
			"SKU", "productName", "From Location", "fromLocationName", "To Location", "toLocationName", "Available Qty", "availableUnits",
			"Suggested Qty", "units", "Value", "transferValueMinor", "Expected Benefit", "expectedBenefitMinor", "Status", "transferStatus",
		),
	},
	"valuationExportBtn": {
		prefix: "inventory-valuation", kind: "inventory", path: "/api/v1/inventory/valuation", card: "categories",
		columns: []directExportColumn{
			{header: "Category", field: "categoryLabel"}, {header: "Gross Value", field: "valueMinor"},
			{header: "NRV", unavailableReason: "Not available — an approved markdown and NRV policy is required."},
			{header: "Provision", unavailableReason: "Not available — an approved provisioning rate is required."},
			{header: "Variance", field: "varianceValueMinor"},
		},
	},
	"expiryExportBtn": {
		prefix: "expiry-waste", kind: "inventory", path: "/api/v1/inventory/expiry-waste",
		columns: directColumns(
			"Product", "productName", "Location", "locationName", "Expiry Window", "expiryWindow", "Units", "expiringUnits",
			"Value", "nearExpiryValueMinor", "Sell-through", "sellThroughPct", "Recommended Action", "wasteAction", "Priority", "wastePriority",
		),
	},
	"replenishmentExportBtn": {
		prefix: "replenishment-planner", kind: "inventory", path: "/api/v1/replenishment/planner",
		columns: []directExportColumn{
			{header: "Priority", field: "replenishmentPriority"}, {header: "SKU / Product", field: "productName"},
			{header: "Destination", field: "destinationName"}, {header: "Current Stock", field: "currentStockUnits"},
			{header: "Forecast Demand", field: "forecastDemandUnits"}, {header: "Safety Stock", field: "safetyStockUnits"},
			{header: "Suggested Qty", field: "recommendedUnits"}, {header: "Source", field: "sourceName"},
			{header: "Lead Time", field: "leadTimeDays"}, {header: "Expected Receipt", field: "expectedReceiptDate"},
			{header: "Order Value", field: "orderValueMinor"},
			{header: "Service Impact", unavailableReason: "Not available — an accepted policy replay is required."},
			{header: "Confidence", field: "forecastConfidence"}, {header: "Status", field: "erpStatusLabel"},
		},
	},
	"suggestedExportBtn": {
		prefix: "suggested-orders", kind: "inventory", path: "/api/v1/replenishment/orders",
		columns: directColumns(
			"Order", "productName", "Type", "orderType", "Destination", "destinationName", "Source", "sourceName",
			"Items", "recommendedUnits", "Value", "orderValueMinor", "Need Date", "expectedReceiptDate", "Confidence", "forecastConfidence", "Status", "erpStatusLabel",
		),
	},
	"supplierExportBtn": {
		prefix: "supplier-planning", kind: "inventory", path: "/api/v1/replenishment/suppliers",
		columns: directColumns(
			"Supplier", "supplierName", "Category", "categoryLabel", "Open PO Value", "openPoValueMinor", "Capacity", "capacityConfirmedPct",
			"Lead Time", "leadTimeMeanDays", "OTD", "otdRate", "Risk", "riskClass", "Action", "supplierAction",
		),
	},
	"safetyStockExportBtn": {
		prefix: "safety-stock", kind: "inventory", path: "/api/v1/replenishment/safety-stock",
		columns: []directExportColumn{
			{header: "Policy Segment", field: "segmentLabel"}, {header: "SKUs", field: "productName"},
			{header: "Service Target", field: "serviceLevel"},
			{header: "Current Value", unavailableReason: "Not available — the incumbent buffer is not published."},
			{header: "Recommended Value", field: "safetyStockValueMinor"},
			{header: "Impact", unavailableReason: "Not available — the incumbent buffer is not published."},
		},
	},
	"allocationExportBtn": {
		prefix: "allocation-fulfillment", kind: "inventory", path: "/api/v1/replenishment/allocations",
		columns: directColumns(
			"Product", "productName", "Available Pool", "availablePoolUnits", "Store Demand", "requestedUnits", "Allocated", "allocatedUnits",
			"Shortfall", "shortfallUnits", "Allocation Rule", "allocationRule", "Priority", "allocationPriority", "Status", "allocationStatus",
		),
	},
	"exceptionExportBtn": {
		prefix: "replenishment-exceptions", kind: "inventory", path: "/api/v1/replenishment/exceptions",
		columns: []directExportColumn{
			{header: "Exception", field: "exceptionLabel"}, {header: "Order / SKU", field: "productName"},
			{header: "Business Impact", field: "evidence"},
			{header: "Owner", unavailableReason: "Not available — assignment is not published."},
			{header: "Age", unavailableReason: "Not available — a raised timestamp is not published."},
			{header: "Priority", field: "severity"}, {header: "Recommended Resolution", field: "exceptionResolution"},
			{header: "Status", field: "exceptionStatus"},
		},
	},
}

func stableRowID(prefix string, value any) string {
	encoded, _ := json.Marshal(value)
	digest := sha256.Sum256(append([]byte(prefix+"\x00"), encoded...))
	return prefix + "_" + hex.EncodeToString(digest[:10])
}

func directScopeRevision(kind, authority, pricingActivation string, request DirectExportRequest) string {
	selected := append([]string(nil), request.SelectedIDs...)
	sort.Strings(selected)
	return stableRowID("scope", map[string]any{
		"kind": kind, "authority": authority, "pricingActivation": pricingActivation,
		"exportId": request.ExportID, "scope": request.Scope,
		"expectedCount": request.ExpectedCount, "selectedIds": selected,
		"currency": request.Currency, "storeId": request.StoreID,
		"channelScope": request.ChannelScope,
		"forecast": map[string]any{
			"marketId": request.ForecastQuery.MarketID, "region": request.ForecastQuery.Region,
			"storeId": request.ForecastQuery.StoreID, "channelId": request.ForecastQuery.ChannelID,
			"category": request.ForecastQuery.Category, "channelType": request.ForecastQuery.ChannelType,
			"search": request.ForecastQuery.Search, "horizonWeeks": request.ForecastQuery.HorizonWeeks,
		},
		"inventory": map[string]any{
			"marketId": request.InventoryQuery.MarketID, "storeId": request.InventoryQuery.StoreID,
			"category": request.InventoryQuery.Category, "search": request.InventoryQuery.Search,
		},
	})
}

func directRows(payload map[string]any, card string) ([]map[string]any, error) {
	if card == "" {
		rows, ok := payload["items"].([]map[string]any)
		if !ok {
			return nil, fmt.Errorf("direct export source has no row population")
		}
		return rows, nil
	}
	cards, ok := payload["cards"].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("direct export source has no grouped population")
	}
	rows, ok := cards[card].([]map[string]any)
	if !ok {
		return nil, fmt.Errorf("direct export card %q is unavailable", card)
	}
	return rows, nil
}

func uniqueDirectIDs(values []string) (map[string]bool, error) {
	result := make(map[string]bool, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if !directExportRowIDPattern.MatchString(value) || result[value] {
			return nil, pricingError("DIRECT_EXPORT_SELECTION_INVALID", "Selected row IDs must be unique current-page identities.", 422)
		}
		result[value] = true
	}
	return result, nil
}

func validateDirectExportRequest(request DirectExportRequest) error {
	if request.Scope != "selected_visible" && request.Scope != "current_filtered" {
		return pricingError("DIRECT_EXPORT_SCOPE_INVALID", "Direct export scope is invalid.", 422)
	}
	if request.ExpectedCount < 0 {
		return pricingError("DIRECT_EXPORT_COUNT_INVALID", "Expected export count is invalid.", 422)
	}
	if request.ExpectedCount > MaxDirectExportRows {
		return pricingError("DIRECT_EXPORT_LIMIT_EXCEEDED", fmt.Sprintf("Export limit is %d rows; narrow filters or selection.", MaxDirectExportRows), 422)
	}
	if !directExportCurrencyPattern.MatchString(request.Currency) {
		return pricingError("DIRECT_EXPORT_CURRENCY_INVALID", "Export currency must be a three-letter code or MULTI.", 422)
	}
	if request.Scope == "current_filtered" && len(request.SelectedIDs) != 0 {
		return pricingError("DIRECT_EXPORT_SELECTION_INVALID", "Current-filtered export cannot carry selected row IDs.", 422)
	}
	if request.Scope == "selected_visible" {
		selected, err := uniqueDirectIDs(request.SelectedIDs)
		if err != nil {
			return err
		}
		if len(selected) != request.ExpectedCount {
			return pricingError("DIRECT_EXPORT_COUNT_INVALID", "Selected row count differs from the reviewed count.", 422)
		}
	}
	return nil
}

func directCell(row map[string]any, column directExportColumn) string {
	if column.field == "" {
		return column.unavailableReason
	}
	value, present := row[column.field]
	if !present || value == nil {
		if column.unavailableReason != "" {
			return column.unavailableReason
		}
		return "Not available — the active authority does not publish this value."
	}
	switch typed := value.(type) {
	case time.Time:
		return typed.UTC().Format(time.RFC3339)
	case []byte:
		return string(typed)
	default:
		return fmt.Sprint(typed)
	}
}

func ExportDirect(
	ctx context.Context,
	forecast *ForecastStore,
	inventory *InventoryStore,
	pricing *PricingStore,
	request DirectExportRequest,
) (DirectExport, error) {
	spec, registered := directExportRegistry[request.ExportID]
	if !registered {
		return DirectExport{}, pricingError("DIRECT_EXPORT_UNKNOWN", "The export trigger is not registered.", 404)
	}
	if err := validateDirectExportRequest(request); err != nil {
		return DirectExport{}, err
	}
	if pricing == nil || !pricing.Available() {
		return DirectExport{}, pricingError(PricingReasonUnavailable, "The shared rich authority required for export lineage is unavailable.", 503)
	}

	var payload map[string]any
	var authority string
	var err error
	if spec.kind == "forecast" {
		if forecast == nil || !forecast.Available() {
			return DirectExport{}, pricingError("DIRECT_EXPORT_SOURCE_UNAVAILABLE", "The active forecast export source is unavailable.", 503)
		}
		request.ForecastQuery.View = "workbench"
		request.ForecastQuery.Offset = 0
		request.ForecastQuery.Limit = MaxDirectExportRows
		payload, err = forecast.Read(ctx, spec.path, request.ForecastQuery)
		authority = forecast.semanticFingerprint
	} else {
		if inventory == nil || !inventory.Available() {
			return DirectExport{}, pricingError("DIRECT_EXPORT_SOURCE_UNAVAILABLE", "The active inventory export source is unavailable.", 503)
		}
		request.InventoryQuery.Offset = 0
		request.InventoryQuery.Limit = MaxDirectExportRows
		payload, err = inventory.Read(ctx, spec.path, request.InventoryQuery)
		authority = inventory.semanticFingerprint
	}
	if err != nil {
		return DirectExport{}, pricingError("DIRECT_EXPORT_SOURCE_UNAVAILABLE", "The registered export source could not be read.", 503)
	}
	revision := directScopeRevision(spec.kind, authority, pricing.activationSetID, request)
	if request.ScopeRevision != revision {
		return DirectExport{}, pricingError(PricingReasonStale, "The export scope changed; refresh before exporting.", 409)
	}
	rows, err := directRows(payload, spec.card)
	if err != nil {
		return DirectExport{}, pricingError("DIRECT_EXPORT_SOURCE_INVALID", err.Error(), 503)
	}
	actualCount := len(rows)
	if request.Scope == "selected_visible" {
		selected, selectionErr := uniqueDirectIDs(request.SelectedIDs)
		if selectionErr != nil {
			return DirectExport{}, selectionErr
		}
		filtered := make([]map[string]any, 0, len(selected))
		for _, row := range rows {
			if rowID, ok := row["rowId"].(string); ok && selected[rowID] {
				filtered = append(filtered, row)
				delete(selected, rowID)
			}
		}
		if len(selected) != 0 {
			return DirectExport{}, pricingError("DIRECT_EXPORT_SELECTION_STALE", "A selected row is no longer visible in the current scope.", 409)
		}
		rows = filtered
		actualCount = len(rows)
	} else if spec.card == "" {
		if pagination, ok := payload["pagination"].(map[string]any); ok {
			switch total := pagination["total"].(type) {
			case int:
				actualCount = total
			case int64:
				actualCount = int(total)
			case float64:
				actualCount = int(total)
			}
		}
	}
	if actualCount > MaxDirectExportRows {
		return DirectExport{}, pricingError("DIRECT_EXPORT_LIMIT_EXCEEDED", fmt.Sprintf("Export limit is %d rows; narrow filters or selection.", MaxDirectExportRows), 422)
	}
	if actualCount != request.ExpectedCount || len(rows) != actualCount {
		return DirectExport{}, pricingError(PricingReasonStale, "The server-counted export population differs from the reviewed count.", 409)
	}
	if len(rows) == 0 {
		return DirectExport{}, pricingError("DIRECT_EXPORT_EMPTY", "No rows are available to export.", 422)
	}

	generatedAt := time.Now().UTC().Truncate(time.Second)
	sourceAsOf := pricing.decisionAsOf.UTC().Truncate(time.Second)
	authorityShort := pricing.bundleFingerprint[:12]
	headers := make([]string, 0, len(spec.columns)+10)
	for _, column := range spec.columns {
		headers = append(headers, column.header)
	}
	headers = append(headers,
		"export_scope", "retailer_id", "tenant_id", "environment", "authority_id",
		"effective_store_id", "channel_scope", "currency", "source_as_of", "generated_at",
	)
	csvRows := [][]string{headers}
	for _, row := range rows {
		values := make([]string, 0, len(headers))
		for _, column := range spec.columns {
			values = append(values, directCell(row, column))
		}
		values = append(values,
			request.Scope, pricing.retailerID, pricing.tenantID, pricing.environment,
			pricing.activationSetID, request.StoreID, request.ChannelScope, request.Currency,
			sourceAsOf.Format(time.RFC3339), generatedAt.Format(time.RFC3339),
		)
		csvRows = append(csvRows, values)
	}
	filename := fmt.Sprintf(
		"%s-%s-%s.csv", spec.prefix, authorityShort,
		sourceAsOf.Format("20060102T150405Z"),
	)
	bytes := serializeCSV(csvRows, false)
	digest := sha256.Sum256(bytes)
	return DirectExport{
		Bytes: bytes, Filename: filename, Count: len(rows),
		ExportID: "dx_" + hex.EncodeToString(digest[:10]), ScopeRevision: revision,
	}, nil
}

func DirectExportMetadata(
	forecast *ForecastStore,
	inventory *InventoryStore,
	pricing *PricingStore,
	request DirectExportRequest,
) (map[string]any, error) {
	spec, registered := directExportRegistry[request.ExportID]
	if !registered {
		return nil, pricingError("DIRECT_EXPORT_UNKNOWN", "The export trigger is not registered.", 404)
	}
	if err := validateDirectExportRequest(request); err != nil {
		return nil, err
	}
	if pricing == nil || !pricing.Available() {
		return nil, pricingError(PricingReasonUnavailable, "The shared rich authority required for export lineage is unavailable.", 503)
	}
	var authority string
	if spec.kind == "forecast" {
		if forecast == nil || !forecast.Available() {
			return nil, pricingError("DIRECT_EXPORT_SOURCE_UNAVAILABLE", "The active forecast export source is unavailable.", 503)
		}
		authority = forecast.semanticFingerprint
	} else {
		if inventory == nil || !inventory.Available() {
			return nil, pricingError("DIRECT_EXPORT_SOURCE_UNAVAILABLE", "The active inventory export source is unavailable.", 503)
		}
		authority = inventory.semanticFingerprint
	}
	registeredIDs := make([]string, 0, len(directExportRegistry))
	for id := range directExportRegistry {
		registeredIDs = append(registeredIDs, id)
	}
	sort.Strings(registeredIDs)
	return map[string]any{
		"schemaVersion": "retail-direct-export-metadata/v1",
		"exportId":      request.ExportID, "limit": MaxDirectExportRows,
		"scopeRevision": directScopeRevision(spec.kind, authority, pricing.activationSetID, request),
		"registered":    registeredIDs,
	}, nil
}
