package httpapi

import (
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
				`"entityCounts":{"sales":1},"objects":[{}]}`,
		),
	})
	if err != nil {
		t.Fatal(err)
	}
	app, err := New(store, execution.Resolved{
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
				`"entityCounts":{"sales":1},"objects":[{}]}`,
		),
	})
	if err != nil {
		t.Fatal(err)
	}
	spec := []byte("openapi: 3.1.0\ninfo:\n  title: Test\n  version: 1.0.0\n")
	app, err := New(store, execution.Resolved{
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
