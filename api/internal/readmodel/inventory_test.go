package readmodel

import (
	"strings"
	"testing"
)

// A capped page is only honest if it is capped to the rows that matter. These
// assert the properties that make "Top 20" a claim rather than a truncation.

func TestEveryRankingBreaksTiesOnTheProjectionKey(t *testing.T) {
	// Without a deterministic tiebreak two rows of equal materiality can swap
	// between requests, so the same row shows on page one and page two -- or on
	// neither. Every ranking must therefore end in identifying columns.
	rankings := map[string]inventoryRanking{
		"position":       rankByPosition,
		"age":            rankByAge,
		"benefit":        rankByBenefit,
		"value":          rankByValue,
		"exposure":       rankByExposure,
		"health":         rankByHealth,
		"recommendation": rankByRecommendation,
		"supplierRisk":   rankBySupplierRisk,
		"buffer":         rankByBuffer,
		"shortfall":      rankByShortfall,
		"severity":       rankBySeverity,
	}
	for name, ranking := range rankings {
		if !strings.Contains(ranking.orderBy, "market_id") {
			t.Errorf("%s: ranking does not break ties on market_id: %q",
				name, ranking.orderBy)
		}
		if strings.TrimSpace(ranking.criterion) == "" {
			t.Errorf("%s: ranking has no criterion, so the screen cannot say "+
				"what its top 20 is the top of", name)
		}
	}
}

func TestNoRankingOrdersByIdentifierAlone(t *testing.T) {
	// The defect this replaced: every route ordered by market/location/SKU, which
	// put whichever SKU sorts first at the top of a stockout list.
	for name, ranking := range map[string]inventoryRanking{
		"position":       rankByPosition,
		"recommendation": rankByRecommendation,
		"shortfall":      rankByShortfall,
	} {
		first, _, _ := strings.Cut(ranking.orderBy, ",")
		if strings.TrimSpace(first) == "market_id" {
			t.Errorf("%s: ranks by identifier first, not materiality: %q",
				name, ranking.orderBy)
		}
	}
}

func TestCompanionAggregatesDropAFilterAndItsArgumentTogether(t *testing.T) {
	// Dropping the clause but keeping the argument is the bug the typed filter
	// list exists to prevent: pgx rejects the whole request, so one unsupported
	// filter would take a working screen down.
	store := &InventoryStore{inventoryVersionID: "iv_test"}
	filters := []inventoryFilter{
		{"market_id", "=", "india-west"},
		{"category", "=", "grocery"},
		{"sku_id", "ILIKE", "%NST%"},
	}
	// inventory_stock_health has no category column and no sku filter is
	// meaningless there -- it does have sku_id, so two of three survive.
	clauses, args := store.scope("inventory_stock_health", filters, nil)
	if len(clauses) != len(args) {
		t.Fatalf("clause/argument mismatch: %d clauses %v, %d args %v",
			len(clauses), clauses, len(args), args)
	}
	for _, clause := range clauses {
		if strings.Contains(clause, "category") {
			t.Errorf("stock health has no category column, got clause %q", clause)
		}
	}
	// The version clause is never optional: it is what binds a row to the one
	// active authority, so a companion that lost it would aggregate every
	// version ever materialized.
	if !strings.Contains(clauses[0], "inventory_version_id") {
		t.Errorf("companion scope dropped the version clause: %v", clauses)
	}
}

func TestEveryScopedTableDeclaresItsFilterableColumns(t *testing.T) {
	// A table missing from filterableColumns silently accepts no filters at all,
	// which turns a market-scoped tile into an enterprise total without failing.
	for table := range inventoryAggregates {
		if _, present := filterableColumns[table]; !present {
			t.Errorf("%s declares aggregates but no filterable columns, so a "+
				"market filter would be silently ignored", table)
		}
	}
}

func TestJoinedAggregateSourcesNameTheirBaseTable(t *testing.T) {
	// aggregateSource replaces the FROM. If it named a different table the
	// scope clauses -- written unqualified -- would apply to the wrong side.
	for table, source := range aggregateSource {
		base := table
		if table == "inventory_valuation_by_kind" {
			base = "inventory_valuation"
		}
		if !strings.Contains(source, "retail_serving."+base) {
			t.Errorf("%s: aggregate source does not read from %s: %q",
				table, base, source)
		}
	}
}

func TestDefaultPageIsAShortlist(t *testing.T) {
	if DefaultInventoryPageSize != 20 {
		t.Errorf("default page size is %d; the screens promise a top 20",
			DefaultInventoryPageSize)
	}
}
