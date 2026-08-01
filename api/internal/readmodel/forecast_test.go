package readmodel

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/jackc/pgx/v5"
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

func TestForecastReadErrorsPreserveRuntimeLineageReason(t *testing.T) {
	lineage := forecastReadError(
		ForecastReasonLineage,
		"activation changed",
	)
	if reason := ForecastReadErrorReason(lineage); reason != ForecastReasonLineage {
		t.Fatalf("runtime lineage reason = %s", reason)
	}
	if reason := ForecastReadErrorReason(context.Canceled); reason != ForecastReasonUnmaterialized {
		t.Fatalf("untyped read error reason = %s", reason)
	}
}

// TestForecastServesGovernedUnavailableOnNoGo is the Go half of the governed
// NO-GO evidence. When Phase 3 closes NO-GO the active view is deliberately
// empty, so requiring an active version would make the branch unreachable.
// Asserting fail-closed serving instead turns the branch into positive evidence.
func TestForecastServesGovernedUnavailableOnNoGo(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PostgreSQL forecast integration environment is not configured")
	}
	if os.Getenv("RETAIL_TEST_FORECAST_LIFECYCLE") == "accepted" {
		t.Skip("gate is running the accepted branch")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	connection, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("connect to forecast integration database: %v", err)
	}
	defer connection.Close(ctx)
	active := 0
	if err := connection.QueryRow(
		ctx,
		"SELECT count(*) FROM retail_serving.active_forecast_versions",
	).Scan(&active); err != nil {
		t.Fatalf("count active forecast versions: %v", err)
	}
	if active != 0 {
		t.Fatalf("NO-GO branch must have no active forecast version, found %d", active)
	}

	store := LoadForecast(ctx, ForecastConfig{
		PostgresDSN:                    dsn,
		ExpectedPublicationFingerprint: strings.Repeat("a", 64),
		ActivationScopeFingerprint:     strings.Repeat("b", 64),
		DBReadPool:                     2,
	})
	defer store.Close()
	if store.Available() {
		t.Fatal("no accepted active version exists, yet forecast serving reports available")
	}
	payload := store.Unavailable()
	// Both governed 503 reasons are acceptable here; only a lineage mismatch
	// maps to 409, and that would wrongly imply an activated version exists.
	reason, _ := payload["reasonCode"].(string)
	if reason != ForecastReasonUnmaterialized && reason != ForecastReasonInvalid {
		t.Fatalf("governed unavailable reason must map to 503, got %v", reason)
	}
	if reason == ForecastReasonLineage {
		t.Fatal("NO-GO branch must not report a lineage mismatch")
	}
	if payload["forecastRunId"] != nil || payload["semanticFingerprint"] != nil {
		t.Fatalf("fail-closed payload must not expose an identity: %v", payload)
	}
}

// TestForecastAuthorityAmbiguityFailsClosed is the decision-#90/#93 global
// validation half. The old startup path selected by activation_scope_fingerprint
// only, so two authorities under different legacy scope hashes each returned one
// row and serving looked healthy. This asserts the projection-wide count decides,
// and that a duplicate authority is reported rather than resolved by configuration.
func TestForecastAuthorityAmbiguityFailsClosed(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PostgreSQL forecast integration environment is not configured")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	connection, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("connect to forecast integration database: %v", err)
	}
	defer connection.Close(ctx)

	active := 0
	if err := connection.QueryRow(
		ctx,
		"SELECT count(*) FROM retail_serving.active_forecast_versions",
	).Scan(&active); err != nil {
		t.Fatalf("count active forecast versions: %v", err)
	}
	distinctScopes := 0
	if err := connection.QueryRow(
		ctx,
		`SELECT count(DISTINCT activation_scope_fingerprint)
		 FROM retail_serving.active_forecast_versions`,
	).Scan(&distinctScopes); err != nil {
		t.Fatalf("count distinct activation scopes: %v", err)
	}
	if active > 1 {
		t.Fatalf(
			"decision #90 requires exactly one active authority, found %d rows across %d scopes",
			active, distinctScopes,
		)
	}

	// A configured fingerprint that matches nothing must still be refused on the
	// global count when zero rows are active, and must never be able to select a
	// winner when more than one is.
	store := LoadForecast(ctx, ForecastConfig{
		PostgresDSN:                    dsn,
		ExpectedPublicationFingerprint: strings.Repeat("a", 64),
		ActivationScopeFingerprint:     strings.Repeat("b", 64),
		DBReadPool:                     2,
	})
	defer store.Close()
	if store.Available() {
		t.Fatal("an unmatched configured scope must never resolve to an active authority")
	}
	reason, _ := store.Unavailable()["reasonCode"].(string)
	switch active {
	case 0:
		if reason != ForecastReasonUnmaterialized {
			t.Fatalf("zero active authorities reason = %s", reason)
		}
	default:
		// Exactly one row is active but it is not the configured scope: the
		// global count passes and lineage resolution refuses.
		if reason != ForecastReasonUnmaterialized && reason != ForecastReasonLineage {
			t.Fatalf("unmatched scope over one active authority reason = %s", reason)
		}
	}
}

// TestWorkbenchIntervalAggregatesAtEverySelection is the §1.3.1 regression.
//
// The defect it guards is not a null-handling bug, which is why no null check
// caught it: SUM skips nulls, so after decision #92's withholding the confidence
// numerator omitted the withheld weeks while its denominator still counted their
// retained P50 weight, and SUM(yhat_p90) covered h1-h4 beside a central total
// covering the whole selection. Measured on the live version over the 398
// affected series at 26 weeks: 0.0814 served against a covered-week 0.5817, and
// 372 of 398 series returned an interval total below their own central total.
//
// The screen offers 4/8/13/26 and withholding starts at h5, so exactly one
// selection is clean. All four are asserted, because the reason 8 weeks matters
// is that it is one click from the default.
func TestWorkbenchIntervalAggregatesAtEverySelection(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("PostgreSQL forecast integration environment is not configured")
	}
	if lifecycle := os.Getenv("RETAIL_TEST_FORECAST_LIFECYCLE"); lifecycle != "" &&
		lifecycle != "accepted" {
		t.Skip("gate is running the governed NO-GO branch")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	connection, err := pgx.Connect(ctx, dsn)
	if err != nil {
		t.Fatalf("connect to forecast integration database: %v", err)
	}
	defer connection.Close(ctx)
	var scope, publication string
	if err := connection.QueryRow(
		ctx,
		`SELECT activation_scope_fingerprint, publication_semantic_fingerprint
		 FROM retail_serving.active_forecast_versions`,
	).Scan(&scope, &publication); err != nil {
		t.Fatalf("discover active forecast identity: %v", err)
	}
	store := LoadForecast(ctx, ForecastConfig{
		PostgresDSN:                    dsn,
		ExpectedPublicationFingerprint: publication,
		ActivationScopeFingerprint:     scope,
		DBReadPool:                     2,
	})
	defer store.Close()
	if !store.Available() {
		t.Fatalf("active forecast is unavailable: %v", store.Unavailable())
	}

	for _, horizonWeeks := range []int{4, 8, 13, 26} {
		payload, err := store.Read(
			ctx,
			"/api/v1/forecast/series",
			ForecastQuery{View: "workbench", HorizonWeeks: horizonWeeks, Limit: 500},
		)
		if err != nil {
			t.Fatalf("%d weeks: %v", horizonWeeks, err)
		}
		items, ok := payload["items"].([]map[string]any)
		if !ok || len(items) == 0 {
			t.Fatalf("%d weeks returned no items", horizonWeeks)
		}

		mixedRows := 0
		for _, item := range items {
			withheld, ok := item["intervalWithheldWeeks"].(int64)
			if !ok {
				t.Fatalf("%d weeks: withheld count is %T", horizonWeeks, item["intervalWithheldWeeks"])
			}
			confidence, _ := item["confidence"].(*float64)
			intervalTotal, _ := item["aiForecastP90"].(*float64)
			central, _ := item["aiForecast"].(*float64)
			covered, _ := item["confidenceCoveredWindowMean"].(*float64)

			if withheld == 0 {
				// Nothing withheld: both cells stay numeric and the covered-window
				// mean IS the full-window mean.
				if item["confidenceState"] != "measured" {
					t.Fatalf(
						"%d weeks: clean window reports confidenceState %v",
						horizonWeeks, item["confidenceState"],
					)
				}
				if confidence == nil {
					t.Fatalf("%d weeks: clean window withheld a numeric confidence", horizonWeeks)
				}
				if item["aiForecastP90State"] != "available" {
					t.Fatalf(
						"%d weeks: clean window reports interval state %v",
						horizonWeeks, item["aiForecastP90State"],
					)
				}
				continue
			}

			mixedRows++
			// Q19's frozen behaviour: BOTH cells absent, with a reason, and no
			// numeric confidence served.
			if item["confidenceState"] != "unavailable_mixed_window" {
				t.Fatalf(
					"%d weeks: mixed window reports confidenceState %v",
					horizonWeeks, item["confidenceState"],
				)
			}
			if confidence != nil {
				t.Fatalf(
					"%d weeks: mixed window served a numeric confidence %v; Q19 "+
						"freezes it unavailable",
					horizonWeeks, *confidence,
				)
			}
			if intervalTotal != nil {
				t.Fatalf(
					"%d weeks: mixed window served an interval total %v beside a "+
						"differently scoped central total",
					horizonWeeks, *intervalTotal,
				)
			}
			if item["intervalUnavailableReason"] == nil {
				t.Fatalf("%d weeks: unavailable interval carries no reason", horizonWeeks)
			}
			// The covered window must be published so the absence is explicable.
			if item["intervalCoveredFromHorizon"] == nil ||
				item["intervalCoveredThroughHorizon"] == nil {
				t.Fatalf("%d weeks: covered window is not published", horizonWeeks)
			}
			if through, ok := item["intervalCoveredThroughHorizon"].(int); ok && through > 4 {
				t.Fatalf(
					"%d weeks: covered window reaches h%d beyond the calibrated h4",
					horizonWeeks, through,
				)
			}
			// The corrected reference is still computed, and it must not be the
			// diluted figure. 0.0814 was the measured dilution; anything that low
			// means the denominator is still counting weeks the numerator skipped.
			if covered == nil {
				t.Fatalf("%d weeks: covered-window confidence reference was not computed", horizonWeeks)
			}
			if *covered <= 0.10 {
				t.Fatalf(
					"%d weeks: covered-window confidence %v is still diluted; the "+
						"ratio must be restricted on both sides",
					horizonWeeks, *covered,
				)
			}
			// P50 is never withdrawn. A withheld interval retracts a distribution
			// claim, never a forecast.
			if central == nil {
				t.Fatalf("%d weeks: a withheld interval also removed the central forecast", horizonWeeks)
			}
		}

		if horizonWeeks == 4 && mixedRows != 0 {
			t.Fatalf("the 4-week default must contain no withheld week, found %d rows", mixedRows)
		}
		if horizonWeeks != 4 && mixedRows == 0 {
			t.Fatalf(
				"%d weeks returned no mixed-window row, so the regression proves "+
					"nothing; the fixture must include withheld weeks",
				horizonWeeks,
			)
		}
	}
}

func TestForecastPostgresProjectionIntegration(t *testing.T) {
	dsn := os.Getenv("RETAIL_TEST_POSTGRES_DSN")
	scope := os.Getenv("RETAIL_TEST_FORECAST_SCOPE")
	publication := os.Getenv("RETAIL_TEST_PUBLICATION_FINGERPRINT")
	if dsn == "" {
		t.Skip("PostgreSQL forecast integration environment is not configured")
	}
	if lifecycle := os.Getenv("RETAIL_TEST_FORECAST_LIFECYCLE"); lifecycle != "" &&
		lifecycle != "accepted" {
		t.Skip("gate is running the governed NO-GO branch")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	expectedRunID := ""
	expectedVersionID := ""
	if scope == "" || publication == "" {
		connection, err := pgx.Connect(ctx, dsn)
		if err != nil {
			t.Fatalf("connect to forecast integration database: %v", err)
		}
		defer connection.Close(ctx)
		err = connection.QueryRow(
			ctx,
			`
			SELECT
				activation_scope_fingerprint,
				publication_semantic_fingerprint,
				forecast_run_id,
				version_id
			FROM retail_serving.active_forecast_versions
			ORDER BY recorded_at DESC
			LIMIT 1
			`,
		).Scan(&scope, &publication, &expectedRunID, &expectedVersionID)
		if err != nil {
			t.Fatalf("discover active forecast integration identity: %v", err)
		}
	}
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
	if expectedRunID == "" {
		expectedRunID = store.forecastRunID
		expectedVersionID = store.versionID
	}
	if !forecastRunIDPattern.MatchString(expectedRunID) ||
		!forecastVersionID.MatchString(expectedVersionID) {
		t.Fatalf("active forecast identity is malformed: %s %s", expectedRunID, expectedVersionID)
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
			payload["forecastRunId"] != expectedRunID ||
			payload["versionId"] != expectedVersionID {
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
