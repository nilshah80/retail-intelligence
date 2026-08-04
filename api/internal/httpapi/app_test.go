package httpapi

import (
	"context"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/nilshah80/aarv"
	"github.com/nilshah80/retail-intelligence/api/internal/execution"
	"github.com/nilshah80/retail-intelligence/api/internal/readmodel"
)

func fixtureFile(t *testing.T, directory, name, body string) string {
	t.Helper()
	path := filepath.Join(directory, name)
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestDataManagementSummaryRoute(t *testing.T) {
	directory := t.TempDir()
	store, err := readmodel.Load(readmodel.Paths{
		GateAReport: fixtureFile(
			t, directory, "gate-a.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass",`+
				`"datasetInventory":[{}]}`,
		),
		GateBReport: fixtureFile(
			t, directory, "gate-b.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass",`+
				`"capabilityMask":{},"reconciliation":[],"rules":[]}`,
		),
		PublicationManifest: fixtureFile(
			t, directory, "publication.json",
			`{"sourceSnapshotId":"snapshot-a","semanticFingerprint":"abc",`+
				`"publishedAt":"2026-07-30T00:00:00Z",`+
				`"entityCounts":{"sales":1,"quarantine_records":0},`+
				`"businessControls":{"totalSkus":1,"activeSkus":1,`+
				`"stores":[],"channels":[],"currencies":[],`+
				`"dateRange":{"start":"2026-01-01","end":"2026-07-30"},`+
				`"fx":{"reportingCurrency":"INR","coverage":{`+
				`"start":"2026-01-01","end":"2026-07-30","observations":1},`+
				`"rates":[]},`+
				`"forecastCoveragePct":null,"modelAccuracyPct":null},`+
				`"objects":[{}]}`,
		),
	})
	if err != nil {
		t.Fatal(err)
	}
	app, err := New(store, readmodel.LoadForecast(context.Background(), readmodel.ForecastConfig{}), readmodel.LoadInventory(context.Background(), readmodel.InventoryConfig{}), execution.Resolved{
		SchemaVersion: execution.SchemaVersion,
		Profile:       "safe",
		API: execution.APIProfile{
			BackgroundJobWorkers: 2,
			DBReadPool:           6,
			GoMaxProcs:           2,
			HTTPConcurrency:      64,
		},
	}, []byte("openapi: 3.1.0\ninfo:\n  title: Test\n  version: 1.0.0\n"))
	if err != nil {
		t.Fatal(err)
	}
	response := aarv.NewTestClient(app).Get("/api/v1/data-management/summary")
	response.AssertStatus(t, 200)
	var payload map[string]any
	if err := response.JSON(&payload); err != nil {
		t.Fatal(err)
	}
	if payload["dataMode"] != "live" {
		t.Fatalf("dataMode = %v", payload["dataMode"])
	}

	dashboard := aarv.NewTestClient(app).Get(
		"/api/v1/data-management/dashboard",
	)
	dashboard.AssertStatus(t, http.StatusOK)
	var dashboardPayload map[string]any
	if err := dashboard.JSON(&dashboardPayload); err != nil {
		t.Fatal(err)
	}
	if dashboardPayload["schemaVersion"] !=
		"retail-data-management-dashboard/v1" {
		t.Fatalf("unexpected dashboard contract: %v", dashboardPayload)
	}

	fx := aarv.NewTestClient(app).Get("/api/v1/fx/rates")
	fx.AssertStatus(t, http.StatusOK)
	var fxPayload map[string]any
	if err := fx.JSON(&fxPayload); err != nil {
		t.Fatal(err)
	}
	if fxPayload["schemaVersion"] != "retail-fx-rates/v1" {
		t.Fatalf("unexpected FX contract: %v", fxPayload)
	}

	client := aarv.NewTestClient(app)
	for _, path := range forecastPaths {
		forecast := client.Get(path)
		forecast.AssertStatus(t, http.StatusServiceUnavailable)
		var unavailable map[string]any
		if err := forecast.JSON(&unavailable); err != nil {
			t.Fatal(err)
		}
		if unavailable["schemaVersion"] != readmodel.ForecastUnavailableSchema ||
			unavailable["dataMode"] != "unavailable" ||
			unavailable["reasonCode"] != readmodel.ForecastReasonUnmaterialized {
			t.Fatalf("%s returned an invalid fail-closed envelope: %v", path, unavailable)
		}
		if unavailable["forecastRunId"] != nil ||
			unavailable["semanticFingerprint"] != nil {
			t.Fatalf("%s exposed a forecast identity without an accepted run", path)
		}
	}
}

// TestInventoryRoutesFailClosedWithoutActivation is the P4-8 governed NO-GO
// half: no accepted inventory bundle exists yet, so every one of the fifteen
// routes must return the governed 503 envelope -- never an empty 200, and never
// an identity it cannot back with an activation.
func TestInventoryRoutesFailClosedWithoutActivation(t *testing.T) {
	if status := inventoryUnavailableStatus(readmodel.InventoryReasonForecastSuperseded); status != http.StatusConflict {
		t.Fatalf("superseded consumed forecast must map to 409, got %d", status)
	}
	if status := inventoryUnavailableStatus(readmodel.InventoryReasonUnmaterialized); status != http.StatusServiceUnavailable {
		t.Fatalf("unmaterialized must map to 503, got %d", status)
	}
	store := readmodel.LoadInventory(context.Background(), readmodel.InventoryConfig{})
	if store.Available() {
		t.Fatal("an unconfigured inventory store must be unavailable")
	}
	payload := store.Unavailable()
	if payload["dataMode"] != "unavailable" ||
		payload["inventoryRunId"] != nil ||
		payload["inventoryVersionId"] != nil {
		t.Fatalf("fail-closed payload must not expose an identity: %v", payload)
	}
	if len(inventoryPaths) != 15 {
		t.Fatalf("the route inventory drifted: %d paths", len(inventoryPaths))
	}
}

func TestForecastUnavailableStatus(t *testing.T) {
	if status := forecastUnavailableStatus(readmodel.ForecastReasonLineage); status != http.StatusConflict {
		t.Fatalf("lineage mismatch status = %d", status)
	}
	for _, reason := range []string{
		readmodel.ForecastReasonInvalid,
		readmodel.ForecastReasonUnmaterialized,
		// An ambiguous authority is a governed unavailable state, not a
		// staleness conflict: 409 would imply one activated version we could
		// name, and the whole point is that we cannot.
		readmodel.ForecastReasonAuthorityAmbiguous,
	} {
		if status := forecastUnavailableStatus(reason); status != http.StatusServiceUnavailable {
			t.Fatalf("%s status = %d", reason, status)
		}
	}
}

func TestOpenAPIDocumentationRoutes(t *testing.T) {
	directory := t.TempDir()
	store, err := readmodel.Load(readmodel.Paths{
		GateAReport: fixtureFile(
			t, directory, "gate-a.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass",`+
				`"datasetInventory":[{}]}`,
		),
		GateBReport: fixtureFile(
			t, directory, "gate-b.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass",`+
				`"capabilityMask":{},"reconciliation":[],"rules":[]}`,
		),
		PublicationManifest: fixtureFile(
			t, directory, "publication.json",
			`{"sourceSnapshotId":"snapshot-a","semanticFingerprint":"abc",`+
				`"publishedAt":"2026-07-30T00:00:00Z",`+
				`"entityCounts":{"sales":1,"quarantine_records":0},`+
				`"businessControls":{"totalSkus":1,"activeSkus":1,`+
				`"stores":[],"channels":[],"currencies":[],`+
				`"dateRange":{"start":"2026-01-01","end":"2026-07-30"},`+
				`"fx":{"reportingCurrency":"INR","coverage":{`+
				`"start":"2026-01-01","end":"2026-07-30","observations":1},`+
				`"rates":[]},`+
				`"forecastCoveragePct":null,"modelAccuracyPct":null},`+
				`"objects":[{}]}`,
		),
	})
	if err != nil {
		t.Fatal(err)
	}
	spec := []byte("openapi: 3.1.0\ninfo:\n  title: Test\n  version: 1.0.0\n")
	app, err := New(store, readmodel.LoadForecast(context.Background(), readmodel.ForecastConfig{}), readmodel.LoadInventory(context.Background(), readmodel.InventoryConfig{}), execution.Resolved{
		SchemaVersion: execution.SchemaVersion,
		Profile:       "safe",
		API: execution.APIProfile{
			BackgroundJobWorkers: 2,
			DBReadPool:           6,
			GoMaxProcs:           2,
			HTTPConcurrency:      64,
		},
	}, spec)
	if err != nil {
		t.Fatal(err)
	}
	client := aarv.NewTestClient(app)

	specResponse := client.Get("/openapi.yaml")
	specResponse.AssertStatus(t, http.StatusOK)
	if !strings.Contains(string(specResponse.Body), "openapi: 3.1.0") {
		t.Fatal("OpenAPI route did not return the supplied contract")
	}

	docsResponse := client.Get("/docs")
	docsResponse.AssertStatus(t, http.StatusOK)
	if !strings.Contains(string(docsResponse.Body), "Retail Intelligence API") {
		t.Fatal("Swagger UI did not render its configured title")
	}

	assetResponse := client.Get("/docs/static/swagger-ui.css")
	assetResponse.AssertStatus(t, http.StatusOK)

	redocResponse := client.Get("/redoc")
	redocResponse.AssertStatus(t, http.StatusOK)
}
