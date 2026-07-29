package execution

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func contractPath(name string) string {
	return filepath.Join(
		"..", "..", "..", "execution", "src", "retail_execution",
		"data", "v1", name,
	)
}

func TestNamedAPIProfilesMatchSharedContract(t *testing.T) {
	path := contractPath("profiles.json")
	tests := []struct {
		name        string
		concurrency int
		gomaxprocs  int
	}{
		{"safe", 64, 2},
		{"balanced", 128, 4},
		{"performance", 256, 8},
		{"ultra-performance", 512, 12},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			resolved, err := Load(path, test.name)
			if err != nil {
				t.Fatal(err)
			}
			if resolved.API.HTTPConcurrency != test.concurrency {
				t.Fatalf(
					"httpConcurrency = %d, want %d",
					resolved.API.HTTPConcurrency,
					test.concurrency,
				)
			}
			if resolved.API.GoMaxProcs != test.gomaxprocs {
				t.Fatalf(
					"gomaxprocs = %d, want %d",
					resolved.API.GoMaxProcs,
					test.gomaxprocs,
				)
			}
		})
	}
}

func TestAPIProfilesMatchSharedGoldenVectors(t *testing.T) {
	raw, err := os.ReadFile(contractPath("golden-vectors.json"))
	if err != nil {
		t.Fatal(err)
	}
	var vectors []struct {
		Name        string      `json:"name"`
		Profile     string      `json:"profile"`
		ExpectedAPI *APIProfile `json:"expectedApi"`
	}
	if err := json.Unmarshal(raw, &vectors); err != nil {
		t.Fatal(err)
	}
	tested := 0
	for _, vector := range vectors {
		if vector.ExpectedAPI == nil {
			continue
		}
		t.Run(vector.Name, func(t *testing.T) {
			resolved, err := Load(contractPath("profiles.json"), vector.Profile)
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(resolved.API, *vector.ExpectedAPI) {
				t.Fatalf("API profile = %#v, want %#v", resolved.API, *vector.ExpectedAPI)
			}
		})
		tested++
	}
	if tested < 2 {
		t.Fatalf("shared contract supplied only %d API golden vectors", tested)
	}
}

func TestEnvironmentOverrideIsValidated(t *testing.T) {
	path := contractPath("profiles.json")
	t.Setenv("RETAIL_API_HTTP_CONCURRENCY", "0")
	if _, err := Load(path, "safe"); err == nil {
		t.Fatal("expected invalid HTTP concurrency to fail")
	}
}

func TestEnvironmentSelectsProfileWhenCLISelectionIsAbsent(t *testing.T) {
	t.Setenv("RETAIL_EXECUTION_PROFILE", "ultra-performance")
	resolved, err := Load(contractPath("profiles.json"), "")
	if err != nil {
		t.Fatal(err)
	}
	if resolved.Profile != "ultra-performance" {
		t.Fatalf("profile = %q, want ultra-performance", resolved.Profile)
	}
}
