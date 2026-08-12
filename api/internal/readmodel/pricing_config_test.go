package readmodel

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func servingConfigFixture(t *testing.T, mutate func(map[string]any)) string {
	t.Helper()
	document := map[string]any{
		"schemaVersion":             "retail-pricing-local-serving-config/v1",
		"retailerId":                "retailer-demo",
		"tenantId":                  "tenant-demo",
		"environment":               "local",
		"audience":                  "response_rich_local",
		"activationSetId":           "pact_0123456789abcdef",
		"bundleId":                  "pb_0123456789abcdef0123",
		"bundleSemanticFingerprint": strings.Repeat("a", 64),
		"logicalDatabaseTarget":     "retail_intelligence",
		"dsnEnvironmentVariable":    "RETAIL_POSTGRES_DSN",
	}
	if mutate != nil {
		mutate(document)
	}
	identity, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	digest := sha256.Sum256(identity)
	document["configFingerprint"] = hex.EncodeToString(digest[:])
	payload, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "pricing-serving.json")
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadPricingServingConfigAcceptsReviewedSecretFreeIdentity(t *testing.T) {
	config, err := LoadPricingServingConfig(servingConfigFixture(t, nil))
	if err != nil {
		t.Fatal(err)
	}
	if config.RetailerID != "retailer-demo" || config.TenantID != "tenant-demo" ||
		config.Environment != "local" || config.ActivationSetID != "pact_0123456789abcdef" ||
		config.BundleID != "pb_0123456789abcdef0123" ||
		config.LogicalDatabase != "retail_intelligence" {
		t.Fatalf("serving identity did not survive parsing: %#v", config)
	}
	if config.PostgresDSN != "" {
		t.Fatal("retained serving configuration unexpectedly carried a DSN")
	}
}

func TestBooleanFromDetailsPreservesFlagsAndReadsLegacyNumericProjection(t *testing.T) {
	for _, test := range []struct {
		value    any
		expected bool
	}{
		{value: true, expected: true},
		{value: false, expected: false},
		{value: float64(1), expected: true},
		{value: float64(0), expected: false},
	} {
		actual, ok := booleanFromDetails(map[string]any{"available": test.value}, "available")
		if !ok || actual != test.expected {
			t.Fatalf("booleanFromDetails(%v) = %v, %v", test.value, actual, ok)
		}
	}
	if _, ok := booleanFromDetails(map[string]any{"available": float64(2)}, "available"); ok {
		t.Fatal("non-boolean numeric detail was accepted")
	}
}

func TestLoadPricingServingConfigRejectsSecretOrUnknownFields(t *testing.T) {
	for _, field := range []string{"dsn", "password", "credentials", "unknown"} {
		path := servingConfigFixture(t, func(document map[string]any) {
			document[field] = "must-not-be-retained"
		})
		if _, err := LoadPricingServingConfig(path); err == nil {
			t.Fatalf("serving configuration accepted %s", field)
		}
	}
}

func TestLoadPricingServingConfigRejectsIdentityDrift(t *testing.T) {
	path := servingConfigFixture(t, nil)
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var document map[string]any
	if err := json.Unmarshal(payload, &document); err != nil {
		t.Fatal(err)
	}
	document["bundleId"] = "pb_abcdef0123456789abcd"
	modified, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, modified, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := LoadPricingServingConfig(path); err == nil ||
		!strings.Contains(err.Error(), "fingerprint mismatch") {
		t.Fatalf("identity drift was not rejected by fingerprint: %v", err)
	}
}

func TestPricingMoneyRoundingMatchesProducerHalfEvenContract(t *testing.T) {
	cases := map[float64]int64{
		2.5: 2,
		3.5: 4,
		4.5: 4,
		5.5: 6,
	}
	for input, expected := range cases {
		if actual := roundedMinor(input); actual != expected {
			t.Fatalf("roundedMinor(%v)=%d, want %d", input, actual, expected)
		}
	}
}

func TestLoadPricingServingConfigRejectsNonLocalOrSparseAuthority(t *testing.T) {
	for _, mutation := range []func(map[string]any){
		func(document map[string]any) { document["environment"] = "dev" },
		func(document map[string]any) { document["audience"] = "pricing_evidence_sparse_dev" },
		func(document map[string]any) { document["dsnEnvironmentVariable"] = "OTHER_DSN" },
	} {
		if _, err := LoadPricingServingConfig(servingConfigFixture(t, mutation)); err == nil {
			t.Fatal("serving configuration accepted an out-of-scope authority")
		}
	}
}
