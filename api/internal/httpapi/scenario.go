package httpapi

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

const scenarioContextPath = "/api/v1/forecast/scenario/context"
const scenarioRunPath = "/api/v1/forecast/scenario"
const scenarioMaxBodyBytes int64 = 4 << 20

type scenarioAuthorityJSON struct {
	ForecastVersion        string          `json:"forecastVersion"`
	ScenarioContextVersion string          `json:"scenarioContextVersion"`
	Inventory              json.RawMessage `json:"inventory"`
}

type scenarioBusinessScopeJSON struct {
	MarketID     *string `json:"marketId"`
	StoreID      *string `json:"storeId"`
	ChannelID    *string `json:"channelId"`
	ChannelType  string  `json:"channelType,omitempty"`
	Category     *string `json:"category"`
	HorizonWeeks *int    `json:"horizonWeeks"`
}

type scenarioRequestJSON struct {
	PresetID          string                      `json:"presetId"`
	UserOverrides     *map[string]json.RawMessage `json:"userOverrides"`
	BusinessScope     *scenarioBusinessScopeJSON  `json:"businessScope"`
	ExpectedAuthority *scenarioAuthorityJSON      `json:"expectedAuthority"`
}

type scenarioBodyError struct {
	status     int
	reasonCode string
	message    string
}

func (e *scenarioBodyError) Error() string { return e.message }

func malformedScenarioBody(message string) error {
	return &scenarioBodyError{
		status: http.StatusBadRequest, reasonCode: "JSON_BODY_INVALID", message: message,
	}
}

func invalidScenarioStructure(message string) error {
	return &scenarioBodyError{
		status:     http.StatusUnprocessableEntity,
		reasonCode: "SCENARIO_REQUEST_STRUCTURE_INVALID",
		message:    message,
	}
}

func decodeStrictJSON(raw []byte, destination any) error {
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return err
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("request must contain exactly one JSON value")
	}
	return nil
}

func parseScenarioRunRequest(raw []byte) (readmodel.ScenarioRunRequest, error) {
	var body scenarioRequestJSON
	if err := decodeStrictJSON(raw, &body); err != nil {
		var syntax *json.SyntaxError
		if errors.As(err, &syntax) || errors.Is(err, io.EOF) ||
			errors.Is(err, io.ErrUnexpectedEOF) || err.Error() == "unexpected EOF" ||
			strings.Contains(err.Error(), "exactly one JSON value") {
			return readmodel.ScenarioRunRequest{}, malformedScenarioBody(
				"Request body must contain exactly one valid JSON object.",
			)
		}
		// Type mismatches and unknown fields are valid JSON but violate the
		// frozen request structure, so S18/S20 classify them as 422.
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure(
			"Request body does not match the ScenarioRunRequest contract.",
		)
	}
	if body.UserOverrides == nil {
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure(
			"userOverrides must be present as an object",
		)
	}
	if body.BusinessScope == nil {
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure(
			"businessScope must be present as an object",
		)
	}
	if body.ExpectedAuthority == nil {
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure(
			"expectedAuthority must be present as an object",
		)
	}
	if body.BusinessScope.MarketID == nil || body.BusinessScope.StoreID == nil ||
		body.BusinessScope.ChannelID == nil || body.BusinessScope.Category == nil ||
		body.BusinessScope.HorizonWeeks == nil {
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure(
			"businessScope must include marketId, storeId, channelId, category, and horizonWeeks",
		)
	}
	if body.BusinessScope.ChannelType != "" &&
		body.BusinessScope.ChannelType != "online" &&
		body.BusinessScope.ChannelType != "store" &&
		body.BusinessScope.ChannelType != "marketplace" {
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure(
			"businessScope.channelType is invalid",
		)
	}
	request := readmodel.ScenarioRunRequest{
		PresetID:      body.PresetID,
		UserOverrides: make(map[string]string),
		Scope: readmodel.ScenarioBusinessScope{
			MarketID:     *body.BusinessScope.MarketID,
			StoreID:      *body.BusinessScope.StoreID,
			ChannelID:    *body.BusinessScope.ChannelID,
			ChannelType:  body.BusinessScope.ChannelType,
			Category:     *body.BusinessScope.Category,
			HorizonWeeks: *body.BusinessScope.HorizonWeeks,
		},
	}
	allowed := map[string]bool{
		"demandAdjustmentPct":    true,
		"priceChangePct":         true,
		"promotionUpliftPct":     true,
		"competitorAvailability": true,
		"weatherEvent":           true,
	}
	for key, value := range *body.UserOverrides {
		if !allowed[key] || bytes.Equal(bytes.TrimSpace(value), []byte("null")) {
			return readmodel.ScenarioRunRequest{}, invalidScenarioStructure("userOverrides contains an unknown or null field")
		}
		if key == "competitorAvailability" || key == "weatherEvent" {
			var state string
			if err := decodeStrictJSON(value, &state); err != nil || state == "" {
				return readmodel.ScenarioRunRequest{}, invalidScenarioStructure("scenario state override must be text")
			}
			request.UserOverrides[key] = state
			continue
		}
		var number json.Number
		if err := decodeStrictJSON(value, &number); err != nil {
			return readmodel.ScenarioRunRequest{}, invalidScenarioStructure("scenario numeric override must be a JSON number")
		}
		request.UserOverrides[key] = number.String()
	}
	request.ExpectedAuthority.ForecastVersion = body.ExpectedAuthority.ForecastVersion
	request.ExpectedAuthority.ScenarioContextVersion = body.ExpectedAuthority.ScenarioContextVersion
	if len(body.ExpectedAuthority.Inventory) == 0 {
		return readmodel.ScenarioRunRequest{}, invalidScenarioStructure("expectedAuthority.inventory must be present, including explicit null")
	}
	if !bytes.Equal(bytes.TrimSpace(body.ExpectedAuthority.Inventory), []byte("null")) {
		var inventory readmodel.ScenarioInventoryAuthority
		if err := decodeStrictJSON(body.ExpectedAuthority.Inventory, &inventory); err != nil {
			return readmodel.ScenarioRunRequest{}, invalidScenarioStructure("expectedAuthority.inventory is incomplete")
		}
		request.ExpectedAuthority.Inventory = &inventory
	}
	return request, nil
}

func readScenarioBody(c *aarv.Context) ([]byte, error) {
	request := c.Request()
	if request.ContentLength > scenarioMaxBodyBytes {
		request.Close = true
		c.SetHeader("Connection", "close")
		if request.Body != nil {
			_ = request.Body.Close()
		}
		return nil, &http.MaxBytesError{Limit: scenarioMaxBodyBytes}
	}
	if request.Body == nil {
		return nil, nil
	}
	return io.ReadAll(http.MaxBytesReader(
		c.Response(), request.Body, scenarioMaxBodyBytes,
	))
}

func mountScenarioRoutes(app *aarv.App, store *readmodel.ScenarioStore) {
	app.Get(scenarioContextPath, func(c *aarv.Context) error {
		expected := c.Query("expectedForecastVersion")
		if !readmodel.ValidScenarioForecastVersion(expected) {
			c.SetHeader("Cache-Control", "no-store")
			return c.JSON(http.StatusBadRequest, map[string]any{
				"schemaVersion": "retail-request-error/v1",
				"reasonCode":    "EXPECTED_FORECAST_VERSION_INVALID",
				"message":       "expectedForecastVersion is required and must be a forecast version id.",
			})
		}
		payload, err := store.Bootstrap(c.Context(), expected)
		c.SetHeader("Cache-Control", "no-store")
		if err != nil {
			return c.JSON(
				readmodel.ScenarioReadErrorStatus(err),
				readmodel.ScenarioReadErrorPayload(err),
			)
		}
		return c.JSON(http.StatusOK, payload)
	})
	app.Post(scenarioRunPath, func(c *aarv.Context) error {
		c.SetHeader("Cache-Control", "no-store")
		mediaType := strings.ToLower(strings.TrimSpace(strings.Split(c.Header("Content-Type"), ";")[0]))
		if mediaType != "application/json" {
			return c.JSON(http.StatusUnsupportedMediaType, map[string]any{
				"schemaVersion": "retail-request-error/v1",
				"reasonCode":    "CONTENT_TYPE_UNSUPPORTED",
				"message":       "Content-Type must be application/json.",
			})
		}
		raw, err := readScenarioBody(c)
		if err != nil {
			var maxBytes *http.MaxBytesError
			if errors.As(err, &maxBytes) {
				return c.JSON(http.StatusRequestEntityTooLarge, map[string]any{
					"schemaVersion": "retail-request-error/v1",
					"reasonCode":    "REQUEST_BODY_TOO_LARGE",
					"message":       "Request body exceeds the 4 MB limit.",
				})
			}
			return c.JSON(http.StatusBadRequest, map[string]any{
				"schemaVersion": "retail-request-error/v1",
				"reasonCode":    "JSON_BODY_UNREADABLE",
				"message":       "The JSON body could not be read.",
			})
		}
		request, err := parseScenarioRunRequest(raw)
		if err != nil {
			bodyError := &scenarioBodyError{
				status: http.StatusBadRequest, reasonCode: "JSON_BODY_INVALID", message: err.Error(),
			}
			_ = errors.As(err, &bodyError)
			schemaVersion := "retail-request-error/v1"
			if bodyError.status == http.StatusUnprocessableEntity {
				schemaVersion = "retail-scenario-validation-error/v1"
			}
			return c.JSON(bodyError.status, map[string]any{
				"schemaVersion": schemaVersion,
				"reasonCode":    bodyError.reasonCode,
				"message":       bodyError.message,
			})
		}
		payload, err := store.Run(c.Context(), request)
		if err != nil {
			var validation *readmodel.ScenarioValidationError
			if errors.As(err, &validation) {
				return c.JSON(http.StatusUnprocessableEntity, readmodel.ScenarioValidationPayload(err))
			}
			return c.JSON(readmodel.ScenarioReadErrorStatus(err), readmodel.ScenarioReadErrorPayload(err))
		}
		return c.JSON(http.StatusOK, payload)
	}, aarv.WithRouteMaxBodySize(scenarioMaxBodyBytes))
}
