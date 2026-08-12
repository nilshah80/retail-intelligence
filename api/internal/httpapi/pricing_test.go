package httpapi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func pricingTestApp() *aarv.App {
	app := aarv.New(aarv.WithBanner(false))
	mountPricingRoutes(
		app,
		readmodel.LoadPricing(context.Background(), readmodel.PricingConfig{}),
	)
	return app
}

func TestPricingReadsFailClosedWithoutActivation(t *testing.T) {
	client := aarv.NewTestClient(pricingTestApp())
	paths := append([]string{}, pricingReadPaths...)
	paths = append(
		paths,
		"/api/v1/pricing/recommendations/pr_0123456789abcdef0123",
		"/api/v1/competitors/matches/match-1",
	)
	for _, path := range paths {
		response := client.Get(path)
		response.AssertStatus(t, http.StatusServiceUnavailable)
		if response.Headers.Get("Cache-Control") != "no-store" {
			t.Fatalf("%s returned a cacheable authority failure", path)
		}
		var payload map[string]any
		if err := response.JSON(&payload); err != nil {
			t.Fatal(err)
		}
		if payload["schemaVersion"] != readmodel.PricingUnavailableSchema ||
			payload["dataMode"] != "unavailable" ||
			payload["reasonCode"] != readmodel.PricingReasonUnavailable {
			t.Fatalf("%s returned an invalid fail-closed envelope: %v", path, payload)
		}
	}
}

func TestPricingNegativeEvidenceAdapterIsExplicitLocalAndNonMutating(t *testing.T) {
	t.Setenv(pricingDemoAdapterEnvironment, "enabled")
	app := aarv.New(aarv.WithBanner(false))
	mountPricingRoutes(
		app,
		readmodel.LoadPricing(
			context.Background(),
			readmodel.PricingConfig{Environment: "local"},
		),
	)
	client := aarv.NewTestClient(app)

	for state, expected := range map[string]struct {
		status int
		reason string
	}{
		"stale":   {http.StatusConflict, "STALE_AUTHORITY"},
		"missing": {http.StatusServiceUnavailable, "MISSING_AUTHORITY"},
		"corrupt": {http.StatusServiceUnavailable, "CORRUPT_AUTHORITY"},
	} {
		response := client.Get(
			"/api/v1/pricing/recommendations/summary?demoState=" + state,
		)
		response.AssertStatus(t, expected.status)
		var payload map[string]any
		if err := response.JSON(&payload); err != nil {
			t.Fatal(err)
		}
		if payload["reasonCode"] != expected.reason {
			t.Fatalf("%s adapter reason = %v", state, payload["reasonCode"])
		}
	}

	target := "/api/v1/competitors/summary"
	panel := client.Get(
		target + "?demoState=panel&demoPanel=" + url.QueryEscape(target),
	)
	panel.AssertStatus(t, http.StatusServiceUnavailable)
	var payload map[string]any
	if err := panel.JSON(&payload); err != nil {
		t.Fatal(err)
	}
	if payload["reasonCode"] != "PANEL_UNAVAILABLE" {
		t.Fatalf("panel adapter reason = %v", payload["reasonCode"])
	}

	unaffected := client.Get(
		"/api/v1/pricing/recommendations/summary?demoState=panel&demoPanel=" +
			url.QueryEscape(target),
	)
	unaffected.AssertStatus(t, http.StatusServiceUnavailable)
	if err := unaffected.JSON(&payload); err != nil {
		t.Fatal(err)
	}
	if payload["reasonCode"] != readmodel.PricingReasonUnavailable {
		t.Fatalf("unaffected panel was intercepted: %v", payload)
	}
}

func TestPricingNegativeEvidenceAdapterIsInertWithoutLocalOptIn(t *testing.T) {
	for name, environment := range map[string]string{
		"adapter disabled": "local",
		"non-local scope":  "dev",
	} {
		t.Run(name, func(t *testing.T) {
			if name == "non-local scope" {
				t.Setenv(pricingDemoAdapterEnvironment, "enabled")
			} else {
				t.Setenv(pricingDemoAdapterEnvironment, "")
			}
			app := aarv.New(aarv.WithBanner(false))
			mountPricingRoutes(
				app,
				readmodel.LoadPricing(
					context.Background(),
					readmodel.PricingConfig{Environment: environment},
				),
			)
			response := aarv.NewTestClient(app).Get(
				"/api/v1/pricing/recommendations/summary?demoState=stale",
			)
			response.AssertStatus(t, http.StatusServiceUnavailable)
			var payload map[string]any
			if err := response.JSON(&payload); err != nil {
				t.Fatal(err)
			}
			if payload["reasonCode"] != readmodel.PricingReasonUnavailable {
				t.Fatalf("adapter activated outside local opt-in: %v", payload)
			}
		})
	}
}

func TestPriceSimulationHTTPOutcomePrecedence(t *testing.T) {
	app := pricingTestApp()
	request := func(contentType, body string) *httptest.ResponseRecorder {
		recorder := httptest.NewRecorder()
		httpRequest := httptest.NewRequest(
			http.MethodPost,
			"/api/v1/pricing/simulations:run",
			strings.NewReader(body),
		)
		if contentType != "" {
			httpRequest.Header.Set("Content-Type", contentType)
		}
		app.ServeHTTP(recorder, httpRequest)
		return recorder
	}

	if actual := request("text/plain", `{}`).Code; actual != http.StatusUnsupportedMediaType {
		t.Fatalf("unsupported content type status = %d", actual)
	}
	malformed := request("application/json", `{"recommendationId":`)
	if malformed.Code != http.StatusBadRequest ||
		!strings.Contains(malformed.Body.String(), `"reasonCode":"JSON_BODY_INVALID"`) {
		t.Fatalf("malformed JSON response = %d %s", malformed.Code, malformed.Body.String())
	}
	invalid := request("application/json", `{"unknown":true}`)
	if invalid.Code != http.StatusUnprocessableEntity {
		t.Fatalf("invalid structure status = %d", invalid.Code)
	}
	validBody, err := json.Marshal(map[string]any{
		"recommendationId":        "pr_0123456789abcdef0123",
		"proposedPriceMinor":      20500,
		"simulationPeriod":        "Next 4 Weeks",
		"demandAssumption":        "Expected",
		"inventoryObjective":      "Margin Protection",
		"expectedActivationSetId": "pact_0123456789abcdef",
	})
	if err != nil {
		t.Fatal(err)
	}
	valid := request("application/json", string(validBody))
	if valid.Code != http.StatusServiceUnavailable {
		t.Fatalf("valid request did not reach authority check: %d %s", valid.Code, valid.Body.String())
	}
	if valid.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("price simulation response is cacheable")
	}
}

func TestPriceSimulationRejectsOversizedDeclaredBodyBeforeReading(t *testing.T) {
	app := pricingTestApp()
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/pricing/simulations:run",
		strings.NewReader(`{}`),
	)
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

func TestPromotionSimulationIsExplicitlyUnavailableAndNonCacheable(t *testing.T) {
	app := pricingTestApp()
	recorder := httptest.NewRecorder()
	request := httptest.NewRequest(
		http.MethodPost,
		"/api/v1/promotions/simulations:run",
		nil,
	)
	app.ServeHTTP(recorder, request)

	if recorder.Code != http.StatusUnprocessableEntity {
		t.Fatalf("promotion simulation status = %d", recorder.Code)
	}
	if recorder.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("promotion refusal is cacheable")
	}
	if !strings.Contains(recorder.Body.String(), `"reasonCode":"NO_ORIGIN_VISIBLE_PROMOTION_PLAN"`) {
		t.Fatalf("promotion refusal is not explicit: %s", recorder.Body.String())
	}
}
