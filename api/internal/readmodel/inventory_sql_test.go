package readmodel

import (
	"context"
	"os"
	"testing"
)

// Every declared aggregate must actually execute.
//
// The read model fails closed: one bad expression in inventoryAggregates or one
// ambiguous column in aggregateSource does not degrade a tile, it takes the
// whole screen to a governed 503. That is the right posture and it is exactly
// why the SQL needs a test — a join added with ON rather than USING left
// `inventory_version_id` ambiguous and put the Replenishment Planner behind
// "Live inventory data is unavailable" with nothing in the log to say why.
//
// Skips without a DSN, like the other integration tests here, so the fast suite
// stays hermetic.
func TestEveryDeclaredAggregateExecutesAgainstTheLiveSchema(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PostgreSQL integration environment is not configured")
	}
	ctx := context.Background()
	store := LoadInventory(ctx, InventoryConfig{PostgresDSN: dsn})
	if !store.Available() {
		t.Skipf("no active inventory projection: %s", store.UnavailableReason())
	}
	defer store.Close()

	for table := range inventoryAggregates {
		t.Run(table, func(t *testing.T) {
			// The scope every request applies, plus each filter this table can
			// express — a clause is only proven by being rendered and run.
			filters := []inventoryFilter{
				{"market_id", "=", "india-west"},
				{"location_id", "=", "india-west:mumbai-dc"},
				{"category", "=", "grocery"},
				{"sku_id", "ILIKE", "%NST%"},
			}
			clauses, args := store.scope(table, filters, nil)
			if _, err := store.aggregate(ctx, table, clauses, args); err != nil {
				t.Fatalf("%s aggregate failed: %v", table, err)
			}
		})
	}
}

// A companion is rendered against a different table than the page it decorates,
// which is where a filter mismatch hides. Exercised the same way.
func TestEveryDashboardCompanionExecutesAgainstTheLiveSchema(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PostgreSQL integration environment is not configured")
	}
	ctx := context.Background()
	store := LoadInventory(ctx, InventoryConfig{PostgresDSN: dsn})
	if !store.Available() {
		t.Skipf("no active inventory projection: %s", store.UnavailableReason())
	}
	defer store.Close()

	for host, companions := range dashboardCompanions {
		for _, companion := range companions {
			t.Run(host+"->"+companion.table, func(t *testing.T) {
				if _, present := inventoryAggregates[companion.table]; !present {
					t.Fatalf("%s declares no aggregates, so merging it under "+
						"%q adds nothing", companion.table, companion.prefix)
				}
				filters := []inventoryFilter{{"market_id", "=", "india-west"}}
				clauses, args := store.scope(companion.table, filters, nil)
				if _, err := store.aggregate(
					ctx, companion.table, clauses, args,
				); err != nil {
					t.Fatalf("companion %s of %s failed: %v",
						companion.table, host, err)
				}
			})
		}
	}
}

// Ordering is SQL too. A ranking naming a column its projection lacks is a 503
// on that route and nothing anywhere else.
func TestEveryRouteOrderingExecutesAgainstTheLiveSchema(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PostgreSQL integration environment is not configured")
	}
	ctx := context.Background()
	store := LoadInventory(ctx, InventoryConfig{PostgresDSN: dsn})
	if !store.Available() {
		t.Skipf("no active inventory projection: %s", store.UnavailableReason())
	}
	defer store.Close()

	routes := []string{
		"/api/v1/inventory/overview",
		"/api/v1/inventory/stores",
		"/api/v1/inventory/warehouses",
		"/api/v1/inventory/ageing",
		"/api/v1/inventory/transfers",
		"/api/v1/inventory/valuation",
		"/api/v1/inventory/expiry-waste",
		"/api/v1/inventory/stock-health",
		"/api/v1/replenishment/planner",
		"/api/v1/replenishment/orders",
		"/api/v1/replenishment/suppliers",
		"/api/v1/replenishment/safety-stock",
		"/api/v1/replenishment/allocations",
		"/api/v1/replenishment/exceptions",
	}
	for _, route := range routes {
		t.Run(route, func(t *testing.T) {
			payload, err := store.Read(ctx, route, InventoryQuery{})
			if err != nil {
				t.Fatalf("%s failed: %v", route, err)
			}
			pagination, _ := payload["pagination"].(map[string]any)
			if pagination == nil {
				t.Fatalf("%s returned no pagination", route)
			}
			if limit, _ := pagination["limit"].(int); limit != DefaultInventoryPageSize {
				t.Errorf("%s served %v rows per page, want %d",
					route, pagination["limit"], DefaultInventoryPageSize)
			}
			if criterion, _ := payload["ranking"].(string); criterion == "" {
				t.Errorf("%s serves a capped page with no stated ranking", route)
			}
		})
	}
}
