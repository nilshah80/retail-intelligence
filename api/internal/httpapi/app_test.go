package httpapi

import (
	"os"
	"path/filepath"
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
	app := New(store, execution.Resolved{
		SchemaVersion: execution.SchemaVersion,
		Profile:       "safe",
		API: execution.APIProfile{
			BackgroundJobWorkers: 2,
			DBReadPool:           6,
			GoMaxProcs:           2,
			HTTPConcurrency:      64,
		},
	})
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
