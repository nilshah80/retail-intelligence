package execution

import (
	"encoding/json"
	"fmt"
	"os"
	"runtime"
	"strconv"
)

const SchemaVersion = "retail-execution-profile/v1"

type APIProfile struct {
	BackgroundJobWorkers int `json:"backgroundJobWorkers"`
	DBReadPool           int `json:"dbReadPool"`
	GoMaxProcs           int `json:"gomaxprocs"`
	HTTPConcurrency      int `json:"httpConcurrency"`
}

type namedProfile struct {
	SchemaVersion string     `json:"schemaVersion"`
	Profile       string     `json:"profile"`
	API           APIProfile `json:"api"`
}

type Resolved struct {
	SchemaVersion string     `json:"schemaVersion"`
	Profile       string     `json:"profile"`
	API           APIProfile `json:"api"`
}

func Load(path, selected string) (Resolved, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return Resolved{}, fmt.Errorf("read execution profiles: %w", err)
	}
	var profiles map[string]namedProfile
	if err := json.Unmarshal(raw, &profiles); err != nil {
		return Resolved{}, fmt.Errorf("decode execution profiles: %w", err)
	}
	if selected == "" {
		selected = envOr("RETAIL_EXECUTION_PROFILE", "safe")
	}
	profile, ok := profiles[selected]
	if !ok {
		return Resolved{}, fmt.Errorf("unknown execution profile %q", selected)
	}
	resolved := Resolved{
		SchemaVersion: profile.SchemaVersion,
		Profile:       profile.Profile,
		API:           profile.API,
	}
	if err := applyEnvironment(&resolved.API); err != nil {
		return Resolved{}, err
	}
	if err := validate(resolved); err != nil {
		return Resolved{}, err
	}
	runtime.GOMAXPROCS(resolved.API.GoMaxProcs)
	return resolved, nil
}

func applyEnvironment(profile *APIProfile) error {
	values := []struct {
		name   string
		target *int
	}{
		{"RETAIL_API_BACKGROUND_JOB_WORKERS", &profile.BackgroundJobWorkers},
		{"RETAIL_API_DB_READ_POOL", &profile.DBReadPool},
		{"RETAIL_API_GOMAXPROCS", &profile.GoMaxProcs},
		{"RETAIL_API_HTTP_CONCURRENCY", &profile.HTTPConcurrency},
	}
	for _, value := range values {
		raw := os.Getenv(value.name)
		if raw == "" {
			continue
		}
		parsed, err := strconv.Atoi(raw)
		if err != nil {
			return fmt.Errorf("%s must be an integer: %w", value.name, err)
		}
		*value.target = parsed
	}
	return nil
}

func validate(profile Resolved) error {
	if profile.SchemaVersion != SchemaVersion {
		return fmt.Errorf("unsupported execution schema %q", profile.SchemaVersion)
	}
	if profile.API.BackgroundJobWorkers < 1 || profile.API.BackgroundJobWorkers > 64 {
		return fmt.Errorf("backgroundJobWorkers must be within 1..64")
	}
	if profile.API.DBReadPool < 1 || profile.API.DBReadPool > 512 {
		return fmt.Errorf("dbReadPool must be within 1..512")
	}
	if profile.API.GoMaxProcs < 1 || profile.API.GoMaxProcs > 64 {
		return fmt.Errorf("gomaxprocs must be within 1..64")
	}
	if profile.API.HTTPConcurrency < 1 || profile.API.HTTPConcurrency > 100000 {
		return fmt.Errorf("httpConcurrency must be within 1..100000")
	}
	return nil
}

func envOr(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
