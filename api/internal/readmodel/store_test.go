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
				`"entityCounts":{"sales":1},"objects":[{}]}`,
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
