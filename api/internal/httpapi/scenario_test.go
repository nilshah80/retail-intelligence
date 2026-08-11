package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func TestScenarioRequestRequiresExplicitInventoryAbsence(t *testing.T) {
	base := `{
		"presetId":"expected_demand",
		"userOverrides":{},
		"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},
		"expectedAuthority":{
			"forecastVersion":"fv_0123456789abcdef",
			"scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
		}
	}`
	if _, err := parseScenarioRunRequest([]byte(base)); err == nil {
		t.Fatal("missing inventory member was accepted")
	} else {
		var bodyError *scenarioBodyError
		if !errors.As(err, &bodyError) || bodyError.status != http.StatusUnprocessableEntity {
			t.Fatalf("incomplete authority must be 422, got %v", err)
		}
	}
	withNull := `{
		"presetId":"expected_demand",
		"userOverrides":{"priceChangePct":0},
		"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},
		"expectedAuthority":{
			"forecastVersion":"fv_0123456789abcdef",
			"scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
			"inventory":null
		}
	}`
	request, err := parseScenarioRunRequest([]byte(withNull))
	if err != nil {
		t.Fatal(err)
	}
	if request.ExpectedAuthority.Inventory != nil || request.UserOverrides["priceChangePct"] != "0" {
		t.Fatalf("explicit absence/override did not survive: %#v", request)
	}
}

func TestScenarioRequestDistinguishesMalformedJSONFromInvalidStructure(t *testing.T) {
	for _, test := range []struct {
		body   string
		status int
	}{
		{`{"presetId":`, http.StatusBadRequest},
		{`{"unknown":true}`, http.StatusUnprocessableEntity},
		{`{"presetId":4}`, http.StatusUnprocessableEntity},
	} {
		_, err := parseScenarioRunRequest([]byte(test.body))
		var bodyError *scenarioBodyError
		if !errors.As(err, &bodyError) || bodyError.status != test.status {
			t.Fatalf("%s status = %#v, error = %v", test.body, bodyError, err)
		}
	}
	_, err := parseScenarioRunRequest([]byte(`{"privateField":true}`))
	var bodyError *scenarioBodyError
	if !errors.As(err, &bodyError) {
		t.Fatal("invalid structure did not return a scenario body error")
	}
	if strings.Contains(bodyError.message, "privateField") || strings.Contains(bodyError.message, "json:") {
		t.Fatalf("raw decoder detail leaked to the client: %q", bodyError.message)
	}
}

func TestScenarioRequestRejectsUnknownNullAndATPOverrides(t *testing.T) {
	for _, overrides := range []string{
		`{"priceChangePct":null}`,
		`{"atpAdjustment":-0.2}`,
		`{"unknown":1}`,
	} {
		body := `{
			"presetId":"expected_demand",
			"userOverrides":` + overrides + `,
			"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},
			"expectedAuthority":{
				"forecastVersion":"fv_0123456789abcdef",
				"scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
				"inventory":null
			}
		}`
		if _, err := parseScenarioRunRequest([]byte(body)); err == nil {
			t.Fatalf("override %s was accepted", overrides)
		}
	}
}

func TestScenarioRequestRequiresEveryBusinessScopeMember(t *testing.T) {
	for _, missing := range []string{"marketId", "storeId", "channelId", "category", "horizonWeeks"} {
		body := map[string]any{
			"presetId":      "expected_demand",
			"userOverrides": map[string]any{},
			"businessScope": map[string]any{
				"marketId": "", "storeId": "", "channelId": "",
				"category": "", "horizonWeeks": 4,
			},
			"expectedAuthority": map[string]any{
				"forecastVersion":        "fv_0123456789abcdef",
				"scenarioContextVersion": strings.Repeat("a", 64),
				"inventory":              nil,
			},
		}
		delete(body["businessScope"].(map[string]any), missing)
		raw, err := json.Marshal(body)
		if err != nil {
			t.Fatal(err)
		}
		_, err = parseScenarioRunRequest(raw)
		var bodyError *scenarioBodyError
		if !errors.As(err, &bodyError) || bodyError.status != http.StatusUnprocessableEntity {
			t.Fatalf("missing %s was not 422: %v", missing, err)
		}
	}
}

func TestScenarioRequestRequiresContractedTopLevelObjects(t *testing.T) {
	for _, body := range []string{
		`{"presetId":"expected_demand","businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},"expectedAuthority":{"forecastVersion":"fv_0123456789abcdef","scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","inventory":null}}`,
		`{"presetId":"expected_demand","userOverrides":{},"expectedAuthority":{"forecastVersion":"fv_0123456789abcdef","scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","inventory":null}}`,
		`{"presetId":"expected_demand","userOverrides":{},"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4}}`,
		`{"presetId":"expected_demand","userOverrides":null,"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},"expectedAuthority":{"forecastVersion":"fv_0123456789abcdef","scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","inventory":null}}`,
	} {
		_, err := parseScenarioRunRequest([]byte(body))
		var bodyError *scenarioBodyError
		if !errors.As(err, &bodyError) || bodyError.status != http.StatusUnprocessableEntity {
			t.Fatalf("missing required object was not 422: %s: %v", body, err)
		}
	}
}

func TestScenarioPostHTTPOutcomePrecedence(t *testing.T) {
	app := aarv.New(aarv.WithBanner(false))
	mountScenarioRoutes(app, readmodel.LoadScenario(context.Background(), readmodel.ScenarioConfig{}))
	request := func(contentType, body string) *httptest.ResponseRecorder {
		recorder := httptest.NewRecorder()
		httpRequest := httptest.NewRequest(http.MethodPost, scenarioRunPath, strings.NewReader(body))
		if contentType != "" {
			httpRequest.Header.Set("Content-Type", contentType)
		}
		app.ServeHTTP(recorder, httpRequest)
		return recorder
	}
	unsupported := request("text/plain", `{}`)
	if unsupported.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("unsupported content type status = %d", unsupported.Code)
	}
	malformed := request("application/json", `{"presetId":`)
	if malformed.Code != http.StatusBadRequest {
		t.Fatalf("malformed JSON status = %d", malformed.Code)
	}
	incomplete := request("application/json", `{
		"presetId":"expected_demand",
		"userOverrides":{},
		"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},
		"expectedAuthority":{"forecastVersion":"fv_0123456789abcdef","scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
	}`)
	if incomplete.Code != http.StatusUnprocessableEntity {
		t.Fatalf("incomplete authority status = %d", incomplete.Code)
	}
	valid := request("application/json", `{
		"presetId":"expected_demand",
		"userOverrides":{},
		"businessScope":{"marketId":"","storeId":"","channelId":"","category":"","horizonWeeks":4},
		"expectedAuthority":{"forecastVersion":"fv_0123456789abcdef","scenarioContextVersion":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","inventory":null}
	}`)
	if valid.Code != http.StatusServiceUnavailable {
		t.Fatalf("valid request did not reach authority check: %d", valid.Code)
	}
	if valid.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("scenario POST response is cacheable")
	}
}

func TestScenarioPostRejectsOversizedDeclaredBodyBeforeReading(t *testing.T) {
	app := aarv.New(aarv.WithBanner(false))
	mountScenarioRoutes(app, readmodel.LoadScenario(context.Background(), readmodel.ScenarioConfig{}))
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, scenarioRunPath, strings.NewReader(`{}`))
	request.Header.Set("Content-Type", "application/json")
	request.ContentLength = 2_000_000_000

	app.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("oversized declared body status = %d", recorder.Code)
	}
	if recorder.Header().Get("Connection") != "close" {
		t.Fatal("oversized declared body did not force the connection closed")
	}
	if !strings.Contains(recorder.Body.String(), `"reasonCode":"REQUEST_BODY_TOO_LARGE"`) {
		t.Fatalf("oversized body response is not stable: %s", recorder.Body.String())
	}
}
