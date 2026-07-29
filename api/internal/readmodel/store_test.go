package readmodel

import (
	"os"
	"path/filepath"
	"testing"
)

func writeFixture(t *testing.T, directory, name, body string) string {
	t.Helper()
	path := filepath.Join(directory, name)
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadRejectsMixedSnapshotEvidence(t *testing.T) {
	directory := t.TempDir()
	_, err := Load(Paths{
		GateAReport: writeFixture(
			t, directory, "gate-a.json",
			`{"sourceSnapshotId":"snapshot-a"}`,
		),
		GateBReport: writeFixture(
			t, directory, "gate-b.json",
			`{"sourceSnapshotId":"snapshot-b"}`,
		),
		PublicationManifest: writeFixture(
			t, directory, "publication.json",
			`{"sourceSnapshotId":"snapshot-a"}`,
		),
	})
	if err == nil {
		t.Fatal("expected mismatched source snapshots to fail")
	}
}

func TestSummaryAndFindingsPreserveLiveEvidence(t *testing.T) {
	directory := t.TempDir()
	store, err := Load(Paths{
		GateAReport: writeFixture(
			t, directory, "gate-a.json",
			`{"sourceSnapshotId":"snapshot-a","nativeSnapshotId":"run-a",`+
				`"status":"pass","datasetInventory":[{},{}]}`,
		),
		GateBReport: writeFixture(
			t, directory, "gate-b.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass",`+
				`"capabilityMask":{"forecast":{"available":false}},`+
				`"reconciliation":[],"rules":[`+
				`{"outcome":"pass"},{"outcome":"capability_downgrade"}]}`,
		),
		PublicationManifest: writeFixture(
			t, directory, "publication.json",
			`{"sourceSnapshotId":"snapshot-a","semanticFingerprint":"abc",`+
				`"publishedAt":"2026-07-30T00:00:00Z",`+
				`"entityCounts":{"sales":1,"quarantine_records":0},`+
				`"businessControls":{"totalSkus":720,"activeSkus":348,`+
				`"markets":[],"stores":[{},{},{},{}],`+
				`"channels":[{},{},{},{}],`+
				`"dateRange":{"start":"2016-07-28","end":"2026-07-28"},`+
				`"fx":{"reportingCurrency":"INR","coverage":{`+
				`"start":"2016-07-28","end":"2026-07-28","observations":7306},`+
				`"rates":[]},`+
				`"currencies":["INR","USD"],"forecastCoveragePct":null,`+
				`"modelAccuracyPct":null},"objects":[{}]}`,
		),
	})
	if err != nil {
		t.Fatal(err)
	}
	if store.Summary()["dataMode"] != "live" {
		t.Fatal("summary must identify live artifact evidence")
	}
	if len(store.QualityFindings()) != 1 {
		t.Fatal("only non-pass findings should be exposed")
	}
}

func TestDashboardUsesGovernedEvidenceWithoutSampleValues(t *testing.T) {
	directory := t.TempDir()
	store, err := Load(Paths{
		GateAReport: writeFixture(
			t, directory, "gate-a.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass","rules":[`+
				`{"ruleId":"A03","outcome":"pass","evidence":{`+
				`"expectedSourceSystems":["shopify","businessCentral"],`+
				`"representedSourceSystems":["shopify"]}},`+
				`{"ruleId":"A07","outcome":"pass","evidence":{`+
				`"inputRows":100,"rejectedRows":2}}],`+
				`"datasetInventory":[{"sourceSystem":"shopify",`+
				`"scannedRows":100,"nullSourceKeyRows":1,`+
				`"duplicateSourceKeyRows":0,"objectCount":3}]}`,
		),
		GateBReport: writeFixture(
			t, directory, "gate-b.json",
			`{"sourceSnapshotId":"snapshot-a","status":"pass","rules":[`+
				`{"ruleId":"B01","outcome":"pass"},`+
				`{"ruleId":"B15","outcome":"warning"}],`+
				`"capabilityMask":{},"reconciliation":[]}`,
		),
		PublicationManifest: writeFixture(
			t, directory, "publication.json",
			`{"sourceSnapshotId":"snapshot-a","semanticFingerprint":"abc",`+
				`"publishedAt":"2026-07-30T00:00:00Z",`+
				`"entityCounts":{"quarantine_records":3},`+
				`"businessControls":{"totalSkus":720,"activeSkus":348,`+
				`"markets":[{"marketId":"india-west","name":"India West"},`+
				`{"marketId":"us-new-york","name":"US New York"}],`+
				`"stores":[{"storeId":"india-west:pune-koregaon",`+
				`"marketId":"india-west","name":"Pune Koregaon Park"},`+
				`{},{},{}],"channels":[`+
				`{"marketId":"india-west","type":"online"},`+
				`{"marketId":"india-west","type":"store"},`+
				`{"marketId":"us-new-york","type":"online"},`+
				`{"marketId":"us-new-york","type":"store"}],`+
				`"dateRange":{"start":"2016-07-28","end":"2026-07-28"},`+
				`"fx":{"reportingCurrency":"INR","coverage":{`+
				`"start":"2016-07-28","end":"2026-07-28","observations":7306},`+
				`"rates":[{"baseCurrency":"USD","quoteCurrency":"INR",`+
				`"rate":"83.000000000000000000","rateDate":"2026-07-28"}]},`+
				`"currencies":["INR","USD"],"forecastCoveragePct":null,`+
				`"modelAccuracyPct":null},"objects":[{}]}`,
		),
	})
	if err != nil {
		t.Fatal(err)
	}

	dashboard := store.Dashboard()
	kpis := dashboard["kpis"].(map[string]any)
	if kpis["dataFreshnessPct"] != 50.0 {
		t.Fatalf("freshness must use represented/expected sources, got %v", kpis)
	}
	if kpis["qualityScorePct"] != 95.0 {
		t.Fatalf("quality score must be record-weighted, got %v", kpis)
	}
	if kpis["rejectedRecords"] != int64(5) {
		t.Fatalf("rejections must reconcile Gate A and quarantine, got %v", kpis)
	}
	sources := dashboard["sources"].([]map[string]any)
	if len(sources) != 1 || sources[0]["records"] != int64(100) ||
		sources[0]["qualityPct"] != 99.0 ||
		sources[0]["action"] != "View mapping" {
		t.Fatalf("source row is not evidence-derived: %v", sources)
	}
	footer := dashboard["footer"].(map[string]any)
	if footer["channels"] != 2 {
		t.Fatalf("channels must use business channel-type grain: %v", footer)
	}
	filters := dashboard["filters"].(map[string]any)
	channelTypes := filters["channelTypes"].([]map[string]any)
	if len(channelTypes) != 2 ||
		channelTypes[0]["name"] != "E-commerce" ||
		channelTypes[1]["name"] != "Store" {
		t.Fatalf("filter must expose channel types, not native instances: %v", filters)
	}
	if _, exposed := filters["channels"]; exposed {
		t.Fatalf("market-qualified channel instances must remain internal: %v", filters)
	}
	if footer["forecastCoveragePct"] != nil || footer["modelAccuracyPct"] != nil {
		t.Fatalf("unavailable ML metrics must remain null: %v", footer)
	}
	fx := store.FX()
	if fx["reportingCurrency"] != "INR" ||
		len(fx["rates"].([]any)) != 1 {
		t.Fatalf("FX controls are not preserved: %v", fx)
	}
}
