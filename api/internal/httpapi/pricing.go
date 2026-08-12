package httpapi

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

const pricingMaxBodyBytes int64 = 64 << 10

const pricingDemoAdapterEnvironment = "RETAIL_PRICING_DEMO_ADAPTER"

var pricingReadPaths = []string{
	"/api/v1/pricing/recommendations/summary",
	"/api/v1/pricing/recommendations",
	"/api/v1/pricing/recommendations/store-view",
	"/api/v1/pricing/recommendations/category-view",
	"/api/v1/pricing/recommendations/governance",
	"/api/v1/competitors/summary",
	"/api/v1/competitors/matches",
	"/api/v1/competitors/alert-rules",
	"/api/v1/promotions/summary",
	"/api/v1/promotions/opportunities",
	"/api/v1/promotions/portfolio",
	"/api/v1/promotions/calendar",
}

type priceSimulationJSON struct {
	RecommendationID        *string `json:"recommendationId"`
	ProposedPriceMinor      *int64  `json:"proposedPriceMinor"`
	SimulationPeriod        *string `json:"simulationPeriod"`
	DemandAssumption        *string `json:"demandAssumption"`
	InventoryObjective      *string `json:"inventoryObjective"`
	ExpectedActivationSetID *string `json:"expectedActivationSetId"`
}

func pricingQuery(c *aarv.Context) readmodel.PricingQuery {
	return readmodel.PricingQuery{
		StoreID: c.Query("storeId"), ChannelID: c.Query("channelId"),
		ChannelType: c.Query("channelType"),
		Category:    c.Query("category"), Action: c.Query("action"),
		Confidence: c.Query("confidence"), Search: c.Query("search"),
		MatchStatus: c.Query("matchStatus"), CompetitorID: c.Query("competitorId"),
		Freshness: c.Query("freshness"), RecordKind: c.Query("recordKind"),
		Sort: c.Query("sort"), Offset: c.QueryInt("offset", 0),
		Limit: c.QueryInt("limit", readmodel.DefaultPricingPageSize),
	}
}

func pricingFailure(c *aarv.Context, err error) error {
	c.SetHeader("Cache-Control", "no-store")
	return c.JSON(
		readmodel.PricingReadErrorStatus(err),
		readmodel.PricingReadErrorPayload(err),
	)
}

func pricingRequestFailure(c *aarv.Context, status int, reasonCode, message string) error {
	c.SetHeader("Cache-Control", "no-store")
	return c.JSON(status, map[string]any{
		"schemaVersion": "retail-request-error/v1",
		"reasonCode":    reasonCode,
		"message":       message,
	})
}

// pricingDemoFailure is a local-only, non-mutating negative-evidence adapter.
// It never changes the store or database and is inert unless the developer
// process explicitly enables it. This keeps stale/missing/corrupt/panel states
// reproducible without making a client-controlled query parameter authoritative.
func pricingDemoFailure(
	c *aarv.Context,
	store *readmodel.PricingStore,
	path string,
) (bool, error) {
	if os.Getenv(pricingDemoAdapterEnvironment) != "enabled" ||
		!store.LocalDemoAuthority() {
		return false, nil
	}
	state := c.Query("demoState")
	status := http.StatusServiceUnavailable
	reasonCode := ""
	message := ""
	switch state {
	case "":
		return false, nil
	case "stale":
		status = http.StatusConflict
		reasonCode = "STALE_AUTHORITY"
		message = "The selected pricing authority is stale."
	case "missing":
		reasonCode = "MISSING_AUTHORITY"
		message = "The selected pricing authority is missing."
	case "corrupt":
		reasonCode = "CORRUPT_AUTHORITY"
		message = "The selected pricing authority failed integrity verification."
	case "panel":
		if c.Query("demoPanel") != path {
			return false, nil
		}
		reasonCode = "PANEL_UNAVAILABLE"
		message = "This pricing panel is unavailable; unaffected panels remain live."
	default:
		return false, nil
	}
	c.SetHeader("Cache-Control", "no-store")
	return true, c.JSON(status, map[string]any{
		"schemaVersion": readmodel.PricingUnavailableSchema,
		"dataMode":      "unavailable",
		"reasonCode":    reasonCode,
		"message":       message,
	})
}

func readPricingBody(c *aarv.Context) ([]byte, error) {
	request := c.Request()
	if request.ContentLength > pricingMaxBodyBytes {
		request.Close = true
		c.SetHeader("Connection", "close")
		if request.Body != nil {
			_ = request.Body.Close()
		}
		return nil, &http.MaxBytesError{Limit: pricingMaxBodyBytes}
	}
	if request.Body == nil {
		return nil, nil
	}
	return io.ReadAll(http.MaxBytesReader(c.Response(), request.Body, pricingMaxBodyBytes))
}

func mountPricingRoutes(app *aarv.App, store *readmodel.PricingStore) {
	for _, path := range pricingReadPaths {
		path := path
		app.Get(path, func(c *aarv.Context) error {
			if handled, err := pricingDemoFailure(c, store, path); handled {
				return err
			}
			payload, err := store.Read(c.Context(), path, pricingQuery(c))
			if err != nil {
				return pricingFailure(c, err)
			}
			return c.JSON(http.StatusOK, payload)
		})
	}
	app.Get("/api/v1/pricing/recommendations/{id}", func(c *aarv.Context) error {
		if handled, err := pricingDemoFailure(c, store, "/api/v1/pricing/recommendations/{id}"); handled {
			return err
		}
		payload, err := store.Detail(c.Context(), "recommendation", c.Param("id"), pricingQuery(c))
		if err != nil {
			return pricingFailure(c, err)
		}
		return c.JSON(http.StatusOK, payload)
	})
	app.Get("/api/v1/competitors/matches/{id}", func(c *aarv.Context) error {
		if handled, err := pricingDemoFailure(c, store, "/api/v1/competitors/matches/{id}"); handled {
			return err
		}
		payload, err := store.Detail(c.Context(), "competitor", c.Param("id"), pricingQuery(c))
		if err != nil {
			return pricingFailure(c, err)
		}
		return c.JSON(http.StatusOK, payload)
	})
	app.Get("/api/v1/pricing/export", func(c *aarv.Context) error {
		expectedCount, err := strconv.Atoi(c.Query("expectedCount"))
		if err != nil || expectedCount < 0 {
			return pricingRequestFailure(
				c, http.StatusUnprocessableEntity, "EXPORT_COUNT_INVALID",
				"Expected export count is invalid.",
			)
		}
		includeExplanation := c.Query("includeExplanation")
		if includeExplanation != "yes" && includeExplanation != "no" {
			return pricingRequestFailure(
				c, http.StatusUnprocessableEntity, "EXPORT_EXPLANATION_INVALID",
				"Include explanation must be yes or no.",
			)
		}
		selectedIDs := []string{}
		if raw := strings.TrimSpace(c.Query("ids")); raw != "" {
			selectedIDs = strings.Split(raw, ",")
		}
		export, err := store.ExportRecommendations(c.Context(), readmodel.PricingExportRequest{
			Scope: c.Query("scope"), Format: c.Query("format"),
			IncludeExplanation:      includeExplanation == "yes",
			Filename:                c.Query("filename"),
			ExpectedCount:           expectedCount,
			ExpectedActivationSetID: c.Query("expectedActivationSetId"),
			SelectedIDs:             selectedIDs,
			Query:                   pricingQuery(c),
		})
		if err != nil {
			return pricingFailure(c, err)
		}
		c.SetHeader("Cache-Control", "no-store")
		c.SetHeader("Content-Disposition", `attachment; filename="`+export.Filename+`"`)
		c.SetHeader("X-Export-Count", strconv.Itoa(export.Count))
		c.SetHeader("X-Export-ID", export.ExportID)
		c.SetHeader("X-Scope-Revision", export.ScopeRevision)
		return c.Blob(http.StatusOK, "text/csv; charset=utf-8", export.Bytes)
	})
	app.Post("/api/v1/pricing/simulations:run", func(c *aarv.Context) error {
		c.SetHeader("Cache-Control", "no-store")
		mediaType := strings.ToLower(strings.TrimSpace(strings.Split(c.Header("Content-Type"), ";")[0]))
		if mediaType != "application/json" {
			return c.JSON(http.StatusUnsupportedMediaType, map[string]any{
				"schemaVersion": "retail-request-error/v1",
				"reasonCode":    "CONTENT_TYPE_UNSUPPORTED",
				"message":       "Content-Type must be application/json.",
			})
		}
		raw, err := readPricingBody(c)
		if err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				return c.JSON(http.StatusRequestEntityTooLarge, map[string]any{
					"schemaVersion": "retail-request-error/v1",
					"reasonCode":    "REQUEST_BODY_TOO_LARGE",
					"message":       "Request body exceeds the 64 KB limit.",
				})
			}
			return c.JSON(http.StatusBadRequest, map[string]any{
				"schemaVersion": "retail-request-error/v1",
				"reasonCode":    "JSON_BODY_UNREADABLE",
				"message":       "The JSON body could not be read.",
			})
		}
		var body priceSimulationJSON
		if err := decodeStrictJSON(raw, &body); err != nil {
			var syntax *json.SyntaxError
			if errors.As(err, &syntax) || errors.Is(err, io.EOF) ||
				errors.Is(err, io.ErrUnexpectedEOF) || err.Error() == "unexpected EOF" ||
				strings.Contains(err.Error(), "exactly one JSON value") {
				return c.JSON(http.StatusBadRequest, map[string]any{
					"schemaVersion": "retail-request-error/v1",
					"reasonCode":    "JSON_BODY_INVALID",
					"message":       "Request body must contain exactly one valid JSON object.",
				})
			}
			return c.JSON(http.StatusUnprocessableEntity, map[string]any{
				"schemaVersion": "retail-price-simulation-validation/v1",
				"reasonCode":    "SIMULATION_REQUEST_INVALID",
				"message":       "Request body does not match the price simulation contract.",
			})
		}
		if body.RecommendationID == nil || body.ProposedPriceMinor == nil ||
			body.SimulationPeriod == nil || body.DemandAssumption == nil ||
			body.InventoryObjective == nil || body.ExpectedActivationSetID == nil {
			return c.JSON(http.StatusUnprocessableEntity, map[string]any{
				"schemaVersion": "retail-price-simulation-validation/v1",
				"reasonCode":    "SIMULATION_REQUEST_INCOMPLETE",
				"message":       "Every price simulation field is required.",
			})
		}
		payload, err := store.RunSimulation(c.Context(), readmodel.PriceSimulationRequest{
			RecommendationID:        *body.RecommendationID,
			ProposedPriceMinor:      *body.ProposedPriceMinor,
			SimulationPeriod:        *body.SimulationPeriod,
			DemandAssumption:        *body.DemandAssumption,
			InventoryObjective:      *body.InventoryObjective,
			ExpectedActivationSetID: *body.ExpectedActivationSetID,
		})
		if err != nil {
			return pricingFailure(c, err)
		}
		return c.JSON(http.StatusOK, payload)
	}, aarv.WithRouteMaxBodySize(pricingMaxBodyBytes))
	app.Post("/api/v1/promotions/simulations:run", func(c *aarv.Context) error {
		c.SetHeader("Cache-Control", "no-store")
		return c.JSON(http.StatusUnprocessableEntity, map[string]any{
			"schemaVersion": readmodel.PricingUnavailableSchema,
			"dataMode":      "unavailable",
			"reasonCode":    readmodel.PricingReasonPromotion,
			"message":       "Origin-visible promotion planning evidence is not available; no simulation was run.",
		})
	}, aarv.WithRouteMaxBodySize(pricingMaxBodyBytes))
}
