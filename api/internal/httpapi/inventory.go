package httpapi

import (
	"net/http"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

var inventoryPaths = []string{
	"/api/v1/inventory/versions",
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

// A lineage mismatch and a superseded consumed forecast both mean "an activated
// version exists and it is stale" — the OpenAPI 409. Everything else is the
// governed 503.
func inventoryUnavailableStatus(reasonCode string) int {
	switch reasonCode {
	case readmodel.InventoryReasonLineage,
		readmodel.InventoryReasonForecastSuperseded:
		return http.StatusConflict
	}
	return http.StatusServiceUnavailable
}

func mountInventoryRoutes(app *aarv.App, store *readmodel.InventoryStore) {
	for _, path := range inventoryPaths {
		app.Get(path, func(c *aarv.Context) error {
			if !store.Available() {
				return c.JSON(
					inventoryUnavailableStatus(store.UnavailableReason()),
					store.Unavailable(),
				)
			}
			payload, err := store.Read(c.Context(), path, readmodel.InventoryQuery{
				MarketID: c.Query("marketId"),
				StoreID:  c.Query("storeId"),
				Category: c.Query("category"),
				Search:   c.Query("search"),
				Offset:   c.QueryInt("offset", 0),
				// One default, in the read model. Repeating a literal here meant
				// the transport quietly overrode the page size the projections
				// declare, so raising it there changed nothing.
				Limit: c.QueryInt("limit", readmodel.DefaultInventoryPageSize),
			})
			if err != nil {
				reason := readmodel.InventoryReadErrorReason(err)
				return c.JSON(inventoryUnavailableStatus(reason), map[string]any{
					"schemaVersion": readmodel.InventoryUnavailableSchema,
					"dataMode":      "unavailable",
					"reasonCode":    reason,
					"message":       "Live inventory data is unavailable.",
				})
			}
			return c.JSON(http.StatusOK, payload)
		})
	}
}
