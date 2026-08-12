package readmodel

import (
	"reflect"
	"strings"
	"testing"
)

func TestDirectExportRegistryIsClosedAndComplete(t *testing.T) {
	t.Parallel()
	want := []string{
		"ageingExportBtn", "allocationExportBtn", "exceptionExportBtn", "expiryExportBtn",
		"exportForecastBtn", "inventoryExportBtn", "replenishmentExportBtn",
		"safetyStockExportBtn", "storeInventoryExportBtn", "suggestedExportBtn",
		"supplierExportBtn", "transferExportBtn", "valuationExportBtn", "warehouseExportBtn",
	}
	got := make([]string, 0, len(directExportRegistry))
	for id, spec := range directExportRegistry {
		got = append(got, id)
		if spec.prefix == "" || spec.path == "" || len(spec.columns) == 0 {
			t.Fatalf("registry entry %q is incomplete: %#v", id, spec)
		}
		seen := map[string]bool{}
		for _, column := range spec.columns {
			if column.header == "" || seen[column.header] {
				t.Fatalf("registry entry %q has an empty or duplicate column %q", id, column.header)
			}
			seen[column.header] = true
			if column.field == "" && column.unavailableReason == "" {
				t.Fatalf("registry entry %q column %q has no binding or reason", id, column.header)
			}
		}
	}
	sortStrings(got)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("registered triggers = %v; want %v", got, want)
	}
}

func sortStrings(values []string) {
	for i := 1; i < len(values); i++ {
		for j := i; j > 0 && values[j] < values[j-1]; j-- {
			values[j], values[j-1] = values[j-1], values[j]
		}
	}
}

func TestDirectScopeRevisionBindsReviewedScope(t *testing.T) {
	t.Parallel()
	request := DirectExportRequest{
		ExportID: "exportForecastBtn", Scope: "selected_visible", ExpectedCount: 2,
		SelectedIDs: []string{"forecast_b", "forecast_a"}, Currency: "INR",
		ForecastQuery: ForecastQuery{MarketID: "india-west", HorizonWeeks: 4},
	}
	first := directScopeRevision("forecast", strings.Repeat("a", 64), "pact_1", request)
	request.SelectedIDs = []string{"forecast_a", "forecast_b"}
	if second := directScopeRevision("forecast", strings.Repeat("a", 64), "pact_1", request); second != first {
		t.Fatalf("selection order changed semantic scope revision: %q != %q", first, second)
	}
	request.ForecastQuery.HorizonWeeks = 8
	if changed := directScopeRevision("forecast", strings.Repeat("a", 64), "pact_1", request); changed == first {
		t.Fatal("horizon change did not change scope revision")
	}
	request.ForecastQuery.HorizonWeeks = 4
	request.ExpectedCount = 3
	if changed := directScopeRevision("forecast", strings.Repeat("a", 64), "pact_1", request); changed == first {
		t.Fatal("reviewed count change did not change scope revision")
	}
}

func TestDirectExportPrimitiveValidation(t *testing.T) {
	t.Parallel()
	if !directExportCurrencyPattern.MatchString("INR") ||
		!directExportCurrencyPattern.MatchString("MULTI") ||
		directExportCurrencyPattern.MatchString("inr") {
		t.Fatal("currency vocabulary is not closed as expected")
	}
	if _, err := uniqueDirectIDs([]string{"inventory_0123456789abcdef0123", "inventory_0123456789abcdef0123"}); err == nil {
		t.Fatal("duplicate selected row IDs unexpectedly passed")
	}
	if err := validateDirectExportRequest(DirectExportRequest{
		Scope: "selected_visible", ExpectedCount: 2,
		SelectedIDs: []string{"forecast_0123456789abcdef0123"}, Currency: "INR",
	}); err == nil {
		t.Fatal("selected count mismatch unexpectedly passed")
	}
	if got := directCell(map[string]any{}, directExportColumn{
		header: "Value", unavailableReason: "Not available — governed reason.",
	}); got != "Not available — governed reason." {
		t.Fatalf("unavailable export cell = %q", got)
	}
}
