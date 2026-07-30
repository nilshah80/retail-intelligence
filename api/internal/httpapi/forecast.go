package httpapi

import (
	"net/http"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

var forecastPaths = []string{
	"/api/v1/forecast/versions",
	"/api/v1/forecast/summary",
	"/api/v1/forecast/series",
	"/api/v1/forecast/actuals",
	"/api/v1/forecast/horizons",
	"/api/v1/forecast/stores",
	"/api/v1/forecast/drivers",
	"/api/v1/forecast/signals",
	"/api/v1/forecast/exceptions",
}

func forecastUnavailableStatus(reasonCode string) int {
	if reasonCode == readmodel.ForecastReasonLineage {
		return http.StatusConflict
	}
	return http.StatusServiceUnavailable
}

func mountForecastRoutes(app *aarv.App, store *readmodel.ForecastStore) {
	for _, path := range forecastPaths {
		app.Get(path, func(c *aarv.Context) error {
			if !store.Available() {
				return c.JSON(
					forecastUnavailableStatus(store.UnavailableReason()),
					store.Unavailable(),
				)
			}
			payload, err := store.Read(c.Context(), path, readmodel.ForecastQuery{
				MarketID:       c.Query("marketId"),
				Region:         c.Query("region"),
				StoreID:        c.Query("storeId"),
				ChannelID:      c.Query("channelId"),
				Category:       c.Query("category"),
				ChannelType:    c.Query("channelType"),
				Search:         c.Query("search"),
				Scope:          c.Query("scope"),
				View:           c.Query("view"),
				ExceptionClass: c.Query("exceptionClass"),
				Horizon:        c.QueryInt("horizon", 0),
				HorizonWeeks:   c.QueryInt("horizonWeeks", 4),
				Offset:         c.QueryInt("offset", 0),
				Limit:          c.QueryInt("limit", 100),
			})
			if err != nil {
				reasonCode := readmodel.ForecastReadErrorReason(err)
				return c.JSON(
					forecastUnavailableStatus(reasonCode),
					map[string]any{
						"schemaVersion":       readmodel.ForecastUnavailableSchema,
						"dataMode":            "unavailable",
						"versionId":           nil,
						"forecastRunId":       nil,
						"semanticFingerprint": nil,
						"reasonCode":          reasonCode,
						"message":             "The PostgreSQL forecast projection could not be read.",
						"capabilities": map[string]any{
							"demandForecastNonPit": map[string]any{
								"available":  false,
								"reasonCode": reasonCode,
							},
							"pointInTimeForecasting": map[string]any{
								"available":  false,
								"reasonCode": "LANDING_BACKFILL_DEPENDENCY",
							},
						},
					},
				)
			}
			return c.JSON(http.StatusOK, payload)
		})
	}
}
