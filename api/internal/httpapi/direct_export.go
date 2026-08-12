package httpapi

import (
	"net/http"
	"strconv"
	"strings"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func splitDirectExportIDs(value string) []string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return strings.Split(value, ",")
}

func mountDirectExportRoute(
	app *aarv.App,
	forecast *readmodel.ForecastStore,
	inventory *readmodel.InventoryStore,
	pricing *readmodel.PricingStore,
) {
	app.Get("/api/v1/direct-exports/{exportId}", func(c *aarv.Context) error {
		c.SetHeader("Cache-Control", "no-store")
		exportID := c.Param("exportId")
		expectedCount, err := strconv.Atoi(c.Query("expectedCount"))
		if err != nil {
			return pricingRequestFailure(c, http.StatusUnprocessableEntity,
				"DIRECT_EXPORT_COUNT_INVALID", "Expected export count is invalid.")
		}
		request := readmodel.DirectExportRequest{
			ExportID: exportID, Scope: c.Query("scope"), ExpectedCount: expectedCount,
			ScopeRevision: c.Query("scopeRevision"), SelectedIDs: splitDirectExportIDs(c.Query("ids")),
			Currency: c.Query("currency"), StoreID: c.Query("storeId"), ChannelScope: c.Query("channelType"),
			ForecastQuery: readmodel.ForecastQuery{
				MarketID: c.Query("marketId"), Region: c.Query("region"), StoreID: c.Query("storeId"),
				ChannelID: c.Query("channelId"), Category: c.Query("category"), ChannelType: c.Query("channelType"),
				Search: c.Query("search"), HorizonWeeks: c.QueryInt("horizonWeeks", 4),
			},
			InventoryQuery: readmodel.InventoryQuery{
				MarketID: c.Query("marketId"), StoreID: c.Query("storeId"),
				Category: c.Query("category"), Search: c.Query("search"),
			},
		}
		if c.Query("metadata") == "true" {
			payload, metadataErr := readmodel.DirectExportMetadata(forecast, inventory, pricing, request)
			if metadataErr != nil {
				return pricingFailure(c, metadataErr)
			}
			return c.JSON(http.StatusOK, payload)
		}
		result, err := readmodel.ExportDirect(c.Context(), forecast, inventory, pricing, request)
		if err != nil {
			return pricingFailure(c, err)
		}
		c.SetHeader("Content-Disposition", `attachment; filename="`+result.Filename+`"`)
		c.SetHeader("X-Export-Count", strconv.Itoa(result.Count))
		c.SetHeader("X-Export-ID", result.ExportID)
		c.SetHeader("X-Scope-Revision", result.ScopeRevision)
		return c.Blob(http.StatusOK, "text/csv; charset=utf-8", result.Bytes)
	})
}
