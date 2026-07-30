package readmodel

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

func TestForecastLoadFailsClosedWithoutSQLProjection(t *testing.T) {
	store := LoadForecast(context.Background(), ForecastConfig{})
	defer store.Close()
	payload := store.Unavailable()

	if payload["reasonCode"] != ForecastReasonUnmaterialized {
		t.Fatalf("missing SQL projection reason = %v", payload["reasonCode"])
	}
	if payload["forecastRunId"] != nil || payload["semanticFingerprint"] != nil {
		t.Fatalf("missing projection must not expose an active identity: %v", payload)
	}
}

func TestForecastLoadRejectsInvalidConfiguredIdentity(t *testing.T) {
	store := LoadForecast(context.Background(), ForecastConfig{
		PostgresDSN:                    "postgresql://unused",
		ExpectedPublicationFingerprint: "not-a-fingerprint",
		ActivationScopeFingerprint:     "not-a-fingerprint",
	})
	defer store.Close()

	if reason := store.Unavailable()["reasonCode"]; reason != ForecastReasonInvalid {
		t.Fatalf("invalid identity reason = %v", reason)
	}
}

func TestForecastLoadFailsClosedWhenPostgresCannotBeReached(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	store := LoadForecast(ctx, ForecastConfig{
		PostgresDSN:                    "postgresql://127.0.0.1:1/missing",
		ExpectedPublicationFingerprint: strings.Repeat("a", 64),
		ActivationScopeFingerprint:     strings.Repeat("b", 64),
	})
	defer store.Close()

	if reason := store.Unavailable()["reasonCode"]; reason != ForecastReasonUnmaterialized {
		t.Fatalf("unreachable PostgreSQL reason = %v", reason)
	}
}

func TestForecastPostgresProjectionIntegration(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	scope := os.Getenv("RETAIL_TEST_FORECAST_SCOPE")
	publication := os.Getenv("RETAIL_TEST_PUBLICATION_FINGERPRINT")
	if dsn == "" || scope == "" || publication == "" {
		t.Skip("PostgreSQL forecast integration environment is not configured")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	store := LoadForecast(ctx, ForecastConfig{
		PostgresDSN:                    dsn,
		ExpectedPublicationFingerprint: publication,
		ActivationScopeFingerprint:     scope,
		DBReadPool:                     2,
	})
	defer store.Close()
	if !store.Available() {
		t.Fatalf("configured active forecast is unavailable: %v", store.Unavailable())
	}

	paths := []string{
		"/api/v1/forecast/versions",
		"/api/v1/forecast/summary",
		"/api/v1/forecast/series",
		"/api/v1/forecast/actuals",
		"/api/v1/forecast/horizons",
		"/api/v1/forecast/stores",
		"/api/v1/forecast/drivers",
		"/api/v1/forecast/signals",
		"/api/v1/forecast/exceptions",
	}
	for _, path := range paths {
		payload, err := store.Read(ctx, path, ForecastQuery{Limit: 2})
		if err != nil {
			t.Fatalf("%s: %v", path, err)
		}
		if payload["dataMode"] != "live" ||
			payload["forecastRunId"] != "fr_b2f18d0e2999a36d" ||
			payload["versionId"] != "fv_a00fe79a86768419" {
			t.Fatalf("%s returned invalid identity: %v", path, payload)
		}
	}

	summary, err := store.Read(
		ctx,
		"/api/v1/forecast/summary",
		ForecastQuery{},
	)
	if err != nil {
		t.Fatalf("summary: %v", err)
	}
	summaryItems, ok := summary["items"].([]map[string]any)
	if !ok || len(summaryItems) != 1 {
		t.Fatalf("summary returned invalid items: %T %v", summary["items"], summary["items"])
	}
	backtestCoverage, ok := summaryItems[0]["backtestCoveragePct"].(*float64)
	if !ok || backtestCoverage == nil || *backtestCoverage < 0 || *backtestCoverage > 100 {
		t.Fatalf("backtest coverage must be a governed percentage: %v", summaryItems[0])
	}

	workbench, err := store.Read(
		ctx,
		"/api/v1/forecast/series",
		ForecastQuery{View: "workbench", HorizonWeeks: 4, Limit: 2},
	)
	if err != nil {
		t.Fatalf("workbench: %v", err)
	}
	workbenchItems, ok := workbench["items"].([]map[string]any)
	if !ok || len(workbenchItems) != 2 {
		t.Fatalf("workbench returned invalid items: %T %v", workbench["items"], workbench["items"])
	}
	for _, field := range []string{
		"productName",
		"storeName",
		"baseline",
		"aiForecast",
		"lastActual",
		"accuracy",
		"bias",
		"primaryDriver",
		"dataQuality",
		"status",
	} {
		if workbenchItems[0][field] == nil {
			t.Fatalf("workbench field %s is unavailable: %v", field, workbenchItems[0])
		}
	}

	weekly, err := store.Read(
		ctx,
		"/api/v1/forecast/actuals",
		ForecastQuery{View: "weekly", Limit: 8},
	)
	if err != nil {
		t.Fatalf("weekly actuals: %v", err)
	}
	weeklyItems, ok := weekly["items"].([]map[string]any)
	if !ok || len(weeklyItems) != 8 {
		t.Fatalf("weekly actuals returned invalid items: %T %v", weekly["items"], weekly["items"])
	}

	storeSlice, err := store.Read(
		ctx,
		"/api/v1/forecast/stores",
		ForecastQuery{
			StoreID:      "india-west:pune-koregaon",
			ChannelType:  "online",
			HorizonWeeks: 4,
		},
	)
	if err != nil {
		t.Fatalf("filter-scoped stores: %v", err)
	}
	storeItems, ok := storeSlice["items"].([]map[string]any)
	if !ok || len(storeItems) != 1 || storeItems[0]["accuracy"] == nil {
		t.Fatalf("filter-scoped stores returned invalid items: %T %v", storeSlice["items"], storeSlice["items"])
	}
}
