package readmodel

import (
	"context"
	"errors"
	"fmt"
	"math"
	"regexp"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	ForecastUnavailableSchema = "retail-forecast-unavailable/v1"
	// Decision #82 made 0006 v4-only: the cohorted verifier and v4 acceptance
	// generation are the only shapes serving accepts. 0005 stays immutable but is
	// no longer eligible to back an activation, so this pin must move with it or
	// the API fails closed against a correctly migrated database.
	ForecastMigrationRevision = "0009_forecast_interval_contract"

	ForecastReasonInvalid        = "FORECAST_ARTIFACT_INVALID"
	ForecastReasonLineage        = "FORECAST_LINEAGE_MISMATCH"
	ForecastReasonUnmaterialized = "FORECAST_READ_MODEL_UNAVAILABLE"
	// Decision #90 authority uniqueness is a property of the whole projection,
	// not of one configured scope. Selecting by activation_scope_fingerprint
	// alone returns one row per scope hash, so a second authority activated
	// under a different legacy scope reads as healthy. This reason exists so
	// that state is reported as an ambiguous authority rather than silently
	// served, and it maps to 503 like the other governed unavailable reasons.
	ForecastReasonAuthorityAmbiguous = "FORECAST_AUTHORITY_AMBIGUOUS"
)

type ForecastReadError struct {
	reasonCode string
	message    string
}

func (e *ForecastReadError) Error() string {
	return e.message
}

func forecastReadError(reasonCode, message string) error {
	return &ForecastReadError{reasonCode: reasonCode, message: message}
}

func ForecastReadErrorReason(err error) string {
	var forecastError *ForecastReadError
	if errors.As(err, &forecastError) {
		return forecastError.reasonCode
	}
	return ForecastReasonUnmaterialized
}

var (
	forecastRunIDPattern = regexp.MustCompile(`^fr_[0-9a-f]{16}$`)
	forecastVersionID    = regexp.MustCompile(`^fv_[0-9a-f]{16}$`)
	sha256Pattern        = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

type ForecastConfig struct {
	PostgresDSN                    string
	ExpectedPublicationFingerprint string
	ActivationScopeFingerprint     string
	DBReadPool                     int
}

type ForecastStore struct {
	pool                       *pgxpool.Pool
	reasonCode                 string
	message                    string
	forecastRunID              string
	versionID                  string
	semanticFingerprint        string
	publicationFingerprint     string
	activationScopeFingerprint string
	decisionAsOf               time.Time
	markets                    []string
}

type ForecastQuery struct {
	MarketID       string
	Region         string
	StoreID        string
	ChannelID      string
	Category       string
	ChannelType    string
	Search         string
	Scope          string
	View           string
	ExceptionClass string
	Horizon        int
	HorizonWeeks   int
	Offset         int
	Limit          int
}

func unavailableForecast(reasonCode, message string) *ForecastStore {
	return &ForecastStore{reasonCode: reasonCode, message: message}
}

// LoadForecast opens only the PostgreSQL projection produced by the offline
// ten-artifact verifier/materializer. The API never scans forecast Parquet.
func LoadForecast(ctx context.Context, config ForecastConfig) *ForecastStore {
	if config.PostgresDSN == "" || config.ActivationScopeFingerprint == "" {
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"No active PostgreSQL forecast projection is configured.",
		)
	}
	if !sha256Pattern.MatchString(config.ExpectedPublicationFingerprint) ||
		!sha256Pattern.MatchString(config.ActivationScopeFingerprint) {
		return unavailableForecast(
			ForecastReasonInvalid,
			"The configured forecast identity is invalid.",
		)
	}
	poolConfig, err := pgxpool.ParseConfig(config.PostgresDSN)
	if err != nil {
		return unavailableForecast(
			ForecastReasonInvalid,
			"The PostgreSQL forecast configuration is invalid.",
		)
	}
	maxConns := config.DBReadPool
	if maxConns < 1 {
		maxConns = 4
	}
	poolConfig.MaxConns = int32(maxConns)
	poolConfig.MinConns = 0
	poolConfig.MaxConnIdleTime = 5 * time.Minute
	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"The PostgreSQL forecast projection is unavailable.",
		)
	}
	var migrationRevision string
	err = pool.QueryRow(
		ctx,
		"SELECT version_num FROM retail_intelligence_alembic_version",
	).Scan(&migrationRevision)
	if err != nil {
		pool.Close()
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"The PostgreSQL forecast schema could not be verified.",
		)
	}
	if migrationRevision != ForecastMigrationRevision {
		pool.Close()
		return unavailableForecast(
			ForecastReasonInvalid,
			"The PostgreSQL forecast schema is not at the required migration.",
		)
	}

	// Decision #90 / #93: prove the global authority count BEFORE resolving the
	// configured fingerprint. Configuration may select the one proven row; it may
	// never hide a competing one.
	var activeAuthorities int
	err = pool.QueryRow(
		ctx,
		"SELECT count(*) FROM retail_serving.active_forecast_versions",
	).Scan(&activeAuthorities)
	if err != nil {
		pool.Close()
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"The active forecast authority count could not be verified.",
		)
	}
	if activeAuthorities == 0 {
		pool.Close()
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"The accepted forecast projection has not been activated.",
		)
	}
	if activeAuthorities > 1 {
		pool.Close()
		return unavailableForecast(
			ForecastReasonAuthorityAmbiguous,
			"More than one forecast version is active; serving fails closed "+
				"until exactly one authority remains.",
		)
	}

	var store ForecastStore
	store.pool = pool
	store.activationScopeFingerprint = config.ActivationScopeFingerprint
	err = pool.QueryRow(
		ctx,
		`
		SELECT
			forecast_run_id,
			version_id,
			run_semantic_fingerprint,
			publication_semantic_fingerprint,
			decision_as_of,
			markets
		FROM retail_serving.active_forecast_versions
		WHERE activation_scope_fingerprint = $1
		`,
		config.ActivationScopeFingerprint,
	).Scan(
		&store.forecastRunID,
		&store.versionID,
		&store.semanticFingerprint,
		&store.publicationFingerprint,
		&store.decisionAsOf,
		&store.markets,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		pool.Close()
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"The accepted forecast projection has not been activated.",
		)
	}
	if err != nil {
		pool.Close()
		return unavailableForecast(
			ForecastReasonUnmaterialized,
			"The PostgreSQL forecast projection failed verification.",
		)
	}
	if store.publicationFingerprint != config.ExpectedPublicationFingerprint {
		pool.Close()
		return unavailableForecast(
			ForecastReasonLineage,
			"The active forecast projection does not match the curated publication.",
		)
	}
	if !forecastRunIDPattern.MatchString(store.forecastRunID) ||
		!forecastVersionID.MatchString(store.versionID) ||
		!sha256Pattern.MatchString(store.semanticFingerprint) ||
		len(store.markets) == 0 {
		pool.Close()
		return unavailableForecast(
			ForecastReasonInvalid,
			"The active PostgreSQL forecast identity is invalid.",
		)
	}
	return &store
}

func (s *ForecastStore) Close() {
	if s != nil && s.pool != nil {
		s.pool.Close()
	}
}

func (s *ForecastStore) Available() bool {
	return s != nil && s.pool != nil
}

func (s *ForecastStore) UnavailableReason() string {
	if s == nil || s.reasonCode == "" {
		return ForecastReasonUnmaterialized
	}
	return s.reasonCode
}

func (s *ForecastStore) Unavailable() map[string]any {
	reasonCode := s.UnavailableReason()
	message := ""
	if s != nil {
		message = s.message
	}
	if message == "" {
		message = "The PostgreSQL forecast projection is unavailable."
	}
	return map[string]any{
		"schemaVersion":       ForecastUnavailableSchema,
		"dataMode":            "unavailable",
		"versionId":           nil,
		"forecastRunId":       nil,
		"semanticFingerprint": nil,
		"reasonCode":          reasonCode,
		"message":             message,
		"capabilities": map[string]any{
			"demandForecastNonPit": map[string]any{
				"available":  false,
				"reasonCode": reasonCode,
			},
			"pointInTimeForecasting": map[string]any{
				"available":  false,
				"reasonCode": "LANDING_BACKFILL_DEPENDENCY",
			},
		},
	}
}

func (s *ForecastStore) envelope(schemaVersion string) map[string]any {
	return map[string]any{
		"schemaVersion":              schemaVersion,
		"dataMode":                   "live",
		"versionId":                  s.versionID,
		"forecastRunId":              s.forecastRunID,
		"semanticFingerprint":        s.semanticFingerprint,
		"publicationFingerprint":     s.publicationFingerprint,
		"activationScopeFingerprint": s.activationScopeFingerprint,
		"decisionAsOf":               s.decisionAsOf.UTC().Format(time.RFC3339Nano),
		"markets":                    append([]string(nil), s.markets...),
		"capabilities": map[string]any{
			"demandForecastNonPit": map[string]any{"available": true},
			"pointInTimeForecasting": map[string]any{
				"available":  false,
				"reasonCode": "LANDING_BACKFILL_DEPENDENCY",
			},
		},
	}
}

func (s *ForecastStore) Read(
	ctx context.Context,
	path string,
	query ForecastQuery,
) (map[string]any, error) {
	if !s.Available() {
		return nil, errors.New("forecast store is unavailable")
	}
	// Two facts are revalidated per request, and they are not the same fact.
	// `activeAuthorities` is the decision-#90 global invariant across every
	// activation scope hash; `stillActive` is this store's own lineage. A second
	// authority activated mid-process is invisible to the second check alone,
	// which is exactly the hole the configured-scope-only query left open.
	var activeAuthorities int
	var stillActive bool
	err := s.pool.QueryRow(
		ctx,
		`
		SELECT
			(SELECT count(*) FROM retail_serving.active_forecast_versions),
			EXISTS (
				SELECT 1
				FROM retail_serving.active_forecast_versions
				WHERE activation_scope_fingerprint = $1
				  AND forecast_run_id = $2
				  AND version_id = $3
				  AND run_semantic_fingerprint = $4
				  AND publication_semantic_fingerprint = $5
			)
		`,
		s.activationScopeFingerprint,
		s.forecastRunID,
		s.versionID,
		s.semanticFingerprint,
		s.publicationFingerprint,
	).Scan(&activeAuthorities, &stillActive)
	if err != nil {
		return nil, forecastReadError(
			ForecastReasonUnmaterialized,
			"forecast activation could not be revalidated",
		)
	}
	if activeAuthorities != 1 {
		return nil, forecastReadError(
			ForecastReasonAuthorityAmbiguous,
			"forecast authority is not unique across activation scopes",
		)
	}
	if !stillActive {
		return nil, forecastReadError(
			ForecastReasonLineage,
			"forecast activation is no longer current or independently verified",
		)
	}
	query = normalizedForecastQuery(query)
	switch path {
	case "/api/v1/forecast/versions":
		return s.versions(ctx)
	case "/api/v1/forecast/summary":
		return s.summary(ctx)
	case "/api/v1/forecast/series":
		if query.View == "workbench" {
			return s.workbench(ctx, query)
		}
		return s.series(ctx, query)
	case "/api/v1/forecast/actuals":
		if query.View == "weekly" {
			return s.weeklyActuals(ctx, query)
		}
		return s.actuals(ctx, query)
	case "/api/v1/forecast/horizons":
		return s.horizons(ctx, query)
	case "/api/v1/forecast/stores":
		return s.stores(ctx, query)
	case "/api/v1/forecast/drivers":
		return s.drivers(ctx, query)
	case "/api/v1/forecast/signals":
		return s.signals(), nil
	case "/api/v1/forecast/exceptions":
		return s.exceptions(ctx, query)
	default:
		return nil, fmt.Errorf("unsupported forecast path %q", path)
	}
}

func normalizedForecastQuery(query ForecastQuery) ForecastQuery {
	if query.Offset < 0 {
		query.Offset = 0
	}
	if query.Limit < 1 {
		query.Limit = 100
	}
	if query.Limit > 1000 {
		query.Limit = 1000
	}
	if query.Horizon < 0 || query.Horizon > 26 {
		query.Horizon = 0
	}
	if query.HorizonWeeks < 1 {
		query.HorizonWeeks = 4
	}
	if query.HorizonWeeks > 26 {
		query.HorizonWeeks = 26
	}
	if query.ChannelType != "online" && query.ChannelType != "store" {
		query.ChannelType = ""
	}
	return query
}

func (s *ForecastStore) versions(ctx context.Context) (map[string]any, error) {
	var (
		versionID, kind, createdBy, semantic, artifactStatus string
		originDate                                           time.Time
		horizonWeeks                                         int
		accuracy, bias                                       float64
		demandUnits                                          int64
	)
	err := s.pool.QueryRow(
		ctx,
		`
		SELECT
			version_id, kind, origin_date, horizon_weeks, created_by,
			accuracy, bias, demand_units, semantic_fingerprint, artifact_status
		FROM retail_serving.forecast_versions
		WHERE version_id = $1 AND forecast_run_id = $2
		`,
		s.versionID,
		s.forecastRunID,
	).Scan(
		&versionID, &kind, &originDate, &horizonWeeks, &createdBy,
		&accuracy, &bias, &demandUnits, &semantic, &artifactStatus,
	)
	if err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-versions/v1")
	payload["items"] = []map[string]any{{
		"versionId":           versionID,
		"kind":                kind,
		"originDate":          originDate.Format("2006-01-02"),
		"horizonWeeks":        horizonWeeks,
		"createdBy":           createdBy,
		"accuracy":            accuracy,
		"bias":                bias,
		"demandUnits":         demandUnits,
		"semanticFingerprint": semantic,
		"artifactStatus":      artifactStatus,
		"lifecycleStatus":     "active",
	}}
	return payload, nil
}

func (s *ForecastStore) summary(ctx context.Context) (map[string]any, error) {
	var (
		accuracy, bias, p90Coverage, baselineAccuracy *float64
		fvaVsMA13, forecastCoverage, backtestCoverage *float64
		demandUnits                                   int64
		seriesCount, exceptionCount                   int64
	)
	err := s.pool.QueryRow(
		ctx,
		`
		SELECT
			versions.accuracy,
			versions.bias,
			versions.demand_units,
			(
				SELECT COUNT(*)
				FROM retail_serving.forecast_series
				WHERE version_id = versions.version_id AND horizon_week = 1
			),
			(
				SELECT COUNT(*)
				FROM retail_serving.forecast_exceptions
				WHERE version_id = versions.version_id
			),
			(
				SELECT p90_coverage
				FROM retail_serving.forecast_metrics
				WHERE forecast_run_id = versions.forecast_run_id
				  AND slice_type = 'global'
				  AND slice_id = 'portfolio'
				  AND horizon = 0
				  AND model_id = 'champion'
			),
			(
				SELECT accuracy
				FROM retail_serving.forecast_metrics
				WHERE forecast_run_id = versions.forecast_run_id
				  AND slice_type = 'global'
				  AND slice_id = 'portfolio'
				  AND horizon = 0
				  AND model_id = 'ma13'
			),
			(
				SELECT fva_vs_ma13_pct
				FROM retail_serving.forecast_metrics
				WHERE forecast_run_id = versions.forecast_run_id
				  AND slice_type = 'global'
				  AND slice_id = 'portfolio'
				  AND horizon = 0
				  AND model_id = 'champion'
			),
			(
				SELECT
					100.0 * COUNT(DISTINCT (sku_id, store_id, channel_id))
					/ NULLIF((
						SELECT COUNT(*)
						FROM retail_serving.forecast_data_quality
						WHERE version_id = versions.version_id
					), 0)
				FROM retail_serving.forecast_series
				WHERE version_id = versions.version_id
			),
			(
				SELECT
					100.0 * COUNT(DISTINCT (sku_id, store_id, channel_id))
					/ NULLIF((
						SELECT COUNT(*)
						FROM retail_serving.forecast_data_quality
						WHERE version_id = versions.version_id
					), 0)
				FROM retail_serving.forecast_eval_predictions AS evaluation
				WHERE evaluation.forecast_run_id = versions.forecast_run_id
				  AND EXISTS (
					SELECT 1
					FROM retail_serving.forecast_series AS current_series
					WHERE current_series.version_id = versions.version_id
					  AND current_series.horizon_week = 1
					  AND current_series.sku_id = evaluation.sku_id
					  AND current_series.store_id = evaluation.store_id
					  AND current_series.channel_id = evaluation.channel_id
				  )
			)
		FROM retail_serving.forecast_versions AS versions
		WHERE versions.version_id = $1
		`,
		s.versionID,
	).Scan(
		&accuracy,
		&bias,
		&demandUnits,
		&seriesCount,
		&exceptionCount,
		&p90Coverage,
		&baselineAccuracy,
		&fvaVsMA13,
		&forecastCoverage,
		&backtestCoverage,
	)
	if err != nil {
		return nil, err
	}
	qualityRows, err := s.pool.Query(
		ctx,
		`
		SELECT data_quality_class, COUNT(*)
		FROM retail_serving.forecast_data_quality
		WHERE version_id = $1
		GROUP BY data_quality_class
		ORDER BY data_quality_class
		`,
		s.versionID,
	)
	if err != nil {
		return nil, err
	}
	defer qualityRows.Close()
	qualityCounts := map[string]int64{}
	for qualityRows.Next() {
		var class string
		var count int64
		if err := qualityRows.Scan(&class, &count); err != nil {
			return nil, err
		}
		qualityCounts[class] = count
	}
	if err := qualityRows.Err(); err != nil {
		return nil, err
	}
	exceptionRows, err := s.pool.Query(
		ctx,
		`
		SELECT exception_class, COUNT(*)
		FROM retail_serving.forecast_exceptions
		WHERE version_id = $1
		GROUP BY exception_class
		ORDER BY exception_class
		`,
		s.versionID,
	)
	if err != nil {
		return nil, err
	}
	defer exceptionRows.Close()
	exceptionCounts := map[string]int64{}
	for exceptionRows.Next() {
		var class string
		var count int64
		if err := exceptionRows.Scan(&class, &count); err != nil {
			return nil, err
		}
		exceptionCounts[class] = count
	}
	if err := exceptionRows.Err(); err != nil {
		return nil, err
	}
	categoryRows, err := s.pool.Query(
		ctx,
		`
		SELECT DISTINCT category
		FROM retail_serving.forecast_series
		WHERE version_id = $1
		ORDER BY category
		`,
		s.versionID,
	)
	if err != nil {
		return nil, err
	}
	defer categoryRows.Close()
	categories := []string{}
	for categoryRows.Next() {
		var category string
		if err := categoryRows.Scan(&category); err != nil {
			return nil, err
		}
		categories = append(categories, category)
	}
	if err := categoryRows.Err(); err != nil {
		return nil, err
	}
	// The stored version accuracy is SeriesKey grain and stays exactly as the
	// accepted record wrote it. The portfolio figures are computed here, under
	// decision #77's additive semantics, because a headline that says "Model
	// Accuracy" for the whole portfolio must be measured at portfolio grain: 72.31%
	// is the SeriesKey number and 92.82% is the portfolio one. Both are published
	// and both are labelled, which is what decision #78 requires -- the aggregate
	// must never be readable as SeriesKey accuracy, and vice versa.
	portfolio, err := s.portfolioGrainSummary(ctx)
	if err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-summary/v1")
	payload["items"] = []map[string]any{{
		"accuracy":            accuracy,
		"bias":                bias,
		"p90Coverage":         p90Coverage,
		"baselineAccuracy":    baselineAccuracy,
		"fvaVsMa13Pct":        fvaVsMA13,
		"accuracyGrain":                  "series_key",
		"baselineAccuracyGrain":          "series_key",
		"fvaGrain":                       "series_key",
		"portfolioAccuracy":              portfolio["accuracy"],
		"portfolioBias":                  portfolio["bias"],
		"portfolioBaselineAccuracy":      portfolio["baselineAccuracy"],
		"portfolioFvaVsMa13Pct":          portfolio["fvaVsMa13Pct"],
		"portfolioAccuracyGrain":         "market_portfolio",
		"demandUnits":         demandUnits,
		"seriesCount":         seriesCount,
		"exceptionCount":      exceptionCount,
		"exceptionCounts":     exceptionCounts,
		"qualityCounts":       qualityCounts,
		"forecastCoveragePct": forecastCoverage,
		"backtestCoveragePct": backtestCoverage,
		"categories":          categories,
	}}
	return payload, nil
}

// portfolioGrainSummary reads the decision #77 market_portfolio figures the
// publisher now emits with exact_horizon_additive semantics.
//
// The champion, the MA13 baseline and the FVA between them all come from the same
// grain, because comparing a portfolio-grain champion against a leaf-grain baseline
// would not be a comparison. That consistency has a cost worth stating: FVA is
// LOWER at portfolio grain, +25.26 percent against +31.84 at leaf, because
// aggregation helps MA13 too. The card previously showed the leaf triplet, which
// was internally consistent but disagreed with every other accuracy figure on the
// screen; showing the portfolio triplet trades a flattering FVA for a coherent one.
func (s *ForecastStore) portfolioGrainSummary(
	ctx context.Context,
) (map[string]any, error) {
	var accuracy, bias, baseline, fva *float64
	err := s.pool.QueryRow(
		ctx,
		`
		SELECT
			MAX(CASE WHEN model_id = 'champion' THEN accuracy END),
			MAX(CASE WHEN model_id = 'champion' THEN bias END),
			MAX(CASE WHEN model_id = 'ma13' THEN accuracy END),
			MAX(CASE WHEN model_id = 'champion' THEN fva_vs_ma13_pct END)
		FROM retail_serving.forecast_metrics
		WHERE forecast_run_id = $1
		  AND slice_type = 'market_portfolio'
		  AND slice_id = 'portfolio'
		  AND horizon = 0
		  AND model_id IN ('champion', 'ma13')
		`,
		s.forecastRunID,
	).Scan(&accuracy, &bias, &baseline, &fva)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"accuracy":         accuracy,
		"bias":             bias,
		"baselineAccuracy": baseline,
		"fvaVsMa13Pct":     fva,
	}, nil
}

func appendSeriesFilters(
	clauses []string,
	args []any,
	query ForecastQuery,
	aliases map[string]string,
) ([]string, []any) {
	values := []struct {
		value  string
		column string
	}{
		{query.MarketID, aliases["market"]},
		{query.StoreID, aliases["store"]},
		{query.ChannelID, aliases["channel"]},
		{query.Category, aliases["category"]},
	}
	for _, item := range values {
		if item.value == "" || item.column == "" {
			continue
		}
		args = append(args, item.value)
		clauses = append(clauses, fmt.Sprintf("%s = $%d", item.column, len(args)))
	}
	if query.Horizon > 0 && aliases["horizon"] != "" {
		args = append(args, query.Horizon)
		clauses = append(
			clauses,
			fmt.Sprintf("%s = $%d", aliases["horizon"], len(args)),
		)
	}
	if query.Search != "" && aliases["search"] != "" {
		args = append(args, "%"+query.Search+"%")
		clauses = append(
			clauses,
			fmt.Sprintf("%s ILIKE $%d", aliases["search"], len(args)),
		)
	}
	return clauses, args
}

func appendWorkbenchFilters(
	clauses []string,
	args []any,
	query ForecastQuery,
) ([]string, []any) {
	values := []struct {
		value  string
		column string
	}{
		{query.MarketID, "dimensions.market_id"},
		{query.Region, "stores.region"},
		{query.StoreID, "series.store_id"},
		{query.ChannelID, "series.channel_id"},
		{query.ChannelType, "dimensions.channel_type"},
		{query.Category, "series.category"},
	}
	for _, item := range values {
		if item.value == "" {
			continue
		}
		args = append(args, item.value)
		clauses = append(
			clauses,
			fmt.Sprintf("%s = $%d", item.column, len(args)),
		)
	}
	if query.Search != "" {
		args = append(args, "%"+query.Search+"%")
		index := len(args)
		clauses = append(
			clauses,
			fmt.Sprintf(
				"(series.sku_id ILIKE $%d OR dimensions.product_name ILIKE $%d OR stores.name ILIKE $%d OR stores.city ILIKE $%d)",
				index,
				index,
				index,
				index,
			),
		)
	}
	return clauses, args
}

func (s *ForecastStore) workbench(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	clauses := []string{
		"series.version_id = $1",
		"series.horizon_week <= $2",
	}
	args := []any{s.versionID, query.HorizonWeeks, s.forecastRunID}
	clauses, args = appendWorkbenchFilters(clauses, args, query)
	args = append(args, query.Limit, query.Offset)
	statement := fmt.Sprintf(
		`
		WITH current_forecast AS (
			SELECT
				dimensions.market_id,
				series.sku_id,
				series.store_id,
				series.channel_id,
				series.dept_id,
				series.category,
				dimensions.product_name,
				dimensions.channel_type,
				stores.name AS store_name,
				stores.city AS store_city,
				SUM(series.yhat_p50) AS ai_forecast,
				-- Decision #92 withholds the cold-start interval beyond h4 while
				-- retaining P50 at every horizon, so a selected window of 8, 13 or
				-- 26 weeks mixes horizons that carry an interval with horizons that
				-- do not. Both aggregates below were written when every row had an
				-- interval, and SUM skips nulls, so both silently changed meaning.
				--
				-- Frozen by decision #64 Q19 / parity amendment P4-0P-A1.
				COUNT(*) FILTER (WHERE NOT series.interval_available)
					AS interval_withheld_weeks,
				MIN(series.horizon_week) FILTER (WHERE series.interval_available)
					AS interval_covered_from,
				MAX(series.horizon_week) FILTER (WHERE series.interval_available)
					AS interval_covered_through,
				MAX(series.interval_unavailable_reason)
					AS interval_unavailable_reason,
				-- The interval total is absent whenever the window contains a
				-- withheld week. Confining the sum to h1-h4 would remove the
				-- population mismatch and still label a sum of weekly upper bounds
				-- as an interval for a multi-week total: a sum of P90 bounds is not
				-- the P90 of the sum, which predates #92 and is not made true by
				-- scoping.
				CASE
					WHEN COUNT(*) FILTER (WHERE NOT series.interval_available) = 0
					THEN SUM(series.yhat_p90)
				END AS ai_forecast_p90,
				-- Confidence is repaired in two steps, because correcting the
				-- arithmetic and choosing the presentation are different problems.
				--
				-- Step one, the arithmetic: decision #12 defines slice confidence as
				-- the max(P50,1)-weighted mean of per-row confidence, and the old
				-- expression let a retained P50 weight sit in a denominator whose
				-- numerator had skipped it. Restricting BOTH sides to the weeks that
				-- carry an interval is that same formula applied to the population
				-- where confidence exists. Over the 398 affected series at 26 weeks
				-- this moves the figure from 0.0814 to 0.5817.
				SUM(series.confidence * GREATEST(series.yhat_p50, 1.0))
					FILTER (WHERE series.interval_available)
				/ NULLIF(
					SUM(GREATEST(series.yhat_p50, 1.0))
						FILTER (WHERE series.interval_available),
					0
				) AS confidence_covered_window_mean,
				-- Step two, the presentation: a correct h1-h4 number under a heading
				-- reading "Confidence", beside forecast values covering the whole
				-- selection, still states a scope the screen does not. Q19 freezes it
				-- unavailable when the window is mixed. At a 4-week selection nothing
				-- is withheld, so this is the unchanged full-window mean.
				CASE
					WHEN COUNT(*) FILTER (WHERE NOT series.interval_available) = 0
					THEN SUM(series.confidence * GREATEST(series.yhat_p50, 1.0))
					   / NULLIF(SUM(GREATEST(series.yhat_p50, 1.0)), 0)
				END AS confidence,
				CASE MAX(
					CASE series.data_quality_class
						WHEN 'Issue' THEN 3
						WHEN 'Watch' THEN 2
						ELSE 1
					END
				)
					WHEN 3 THEN 'Issue'
					WHEN 2 THEN 'Watch'
					ELSE 'Good'
				END AS data_quality_class
			FROM retail_serving.forecast_series AS series
			JOIN retail_serving.forecast_series_dimensions AS dimensions
			  ON dimensions.version_id = series.version_id
			 AND dimensions.sku_id = series.sku_id
			 AND dimensions.store_id = series.store_id
			 AND dimensions.channel_id = series.channel_id
			JOIN retail_serving.forecast_stores AS stores
			  ON stores.forecast_run_id = dimensions.forecast_run_id
			 AND stores.store_id = dimensions.store_id
			WHERE %s
			GROUP BY
				dimensions.market_id,
				series.sku_id,
				series.store_id,
				series.channel_id,
				series.dept_id,
				series.category,
				dimensions.product_name,
				dimensions.channel_type,
				stores.name,
				stores.city
		),
		actual_by_week AS (
			SELECT
				sku_id,
				store_id,
				channel_id,
				target_week_start,
				MAX(actual_units) AS actual_units
			FROM retail_serving.forecast_eval_predictions
			WHERE forecast_run_id = $3
			GROUP BY sku_id, store_id, channel_id, target_week_start
		),
		ranked_actual AS (
			SELECT
				*,
				ROW_NUMBER() OVER (
					PARTITION BY sku_id, store_id, channel_id
					ORDER BY target_week_start DESC
				) AS recency
			FROM actual_by_week
		),
		actual_context AS (
			SELECT
				sku_id,
				store_id,
				channel_id,
				MAX(actual_units) FILTER (WHERE recency = 1) AS last_actual,
				MAX(target_week_start) FILTER (WHERE recency = 1) AS last_actual_week,
				AVG(actual_units) FILTER (WHERE recency <= 13) AS baseline_ma13_weekly
			FROM ranked_actual
			GROUP BY sku_id, store_id, channel_id
		),
		-- Row accuracy and bias are scoped to the SAME horizon window the row's
		-- forecast column shows. The horizon = 0 slice pools all 26 horizons, so a
		-- SeriesKey reading 74.5 percent at h1 displayed as 21.3 percent next to a
		-- four-week forecast. Summing leaf errors is correct here because the row's
		-- subject IS the SeriesKey.
		--
		-- Accuracy leaves its domain when absolute error exceeds demand -- 321 of
		-- 2,212 SeriesKeys read negative, the worst at -1049 percent -- so the
		-- percentage is withheld and the row carries a state instead.
		--
		-- Bias is NOT withheld with it. A signed ratio is bounded below at -100
		-- percent, a zero forecast, and legitimately unbounded above: +150 percent
		-- means the forecast was two and a half times demand, which is a bad number
		-- and a perfectly defined one. Suppressing it because a different metric
		-- left its own domain hides a fact the truth-visible policy requires, so
		-- accuracy and bias are now judged on their own terms.
		series_metrics AS (
			SELECT
				slice_id::jsonb ->> 0 AS sku_id,
				slice_id::jsonb ->> 1 AS store_id,
				slice_id::jsonb ->> 2 AS channel_id,
				CASE
					WHEN SUM(actual_sum) = 0 THEN NULL
					WHEN SUM(abs_error_sum) / SUM(actual_sum) > 1 THEN NULL
					ELSE 100.0 * (1.0 - SUM(abs_error_sum) / SUM(actual_sum))
				END AS accuracy,
				CASE
					WHEN SUM(actual_sum) = 0 THEN NULL
					ELSE SUM(signed_error_sum) / SUM(actual_sum)
				END AS bias,
				CASE
					WHEN SUM(actual_sum) = 0 THEN NULL
					ELSE SUM(abs_error_sum) / SUM(actual_sum)
				END AS wape,
				CASE
					WHEN SUM(actual_sum) = 0 THEN 'insufficient_evidence'
					WHEN SUM(abs_error_sum) / SUM(actual_sum) > 1 THEN 'error_exceeds_demand'
					ELSE 'measured'
				END AS accuracy_state
			FROM retail_serving.forecast_metrics
			WHERE forecast_run_id = $3
			  AND slice_type = 'series'
			  AND horizon BETWEEN 1 AND $2
			  AND model_id = 'champion'
			GROUP BY 1, 2, 3
		),
		primary_drivers AS (
			SELECT DISTINCT ON (scope)
				SUBSTRING(scope FROM 8)::jsonb ->> 0 AS sku_id,
				SUBSTRING(scope FROM 8)::jsonb ->> 1 AS store_id,
				SUBSTRING(scope FROM 8)::jsonb ->> 2 AS channel_id,
				driver
			FROM retail_serving.forecast_drivers
			WHERE version_id = $1
			  AND scope LIKE 'series:%%'
			  AND driver <> 'croston_routing_explanation'
			ORDER BY scope, contribution_pct DESC, driver
		),
		primary_exceptions AS (
			SELECT DISTINCT ON (sku_id, store_id, channel_id)
				sku_id,
				store_id,
				channel_id,
				severity,
				exception_class
			FROM retail_serving.forecast_exceptions
			WHERE version_id = $1
			ORDER BY
				sku_id,
				store_id,
				channel_id,
				CASE severity
					WHEN 'High' THEN 3
					WHEN 'Medium' THEN 2
					ELSE 1
				END DESC,
				exception_class
		)
		SELECT
			COUNT(*) OVER(),
			current_forecast.market_id,
			current_forecast.sku_id,
			current_forecast.store_id,
			current_forecast.channel_id,
			current_forecast.dept_id,
			current_forecast.category,
			current_forecast.product_name,
			current_forecast.channel_type,
			current_forecast.store_name,
			current_forecast.store_city,
			actual_context.baseline_ma13_weekly * $2,
			current_forecast.ai_forecast,
			current_forecast.ai_forecast_p90,
			actual_context.last_actual,
			actual_context.last_actual_week,
			series_metrics.accuracy,
			series_metrics.wape,
			series_metrics.accuracy_state,
			series_metrics.bias,
			-- Share of the filtered set's forecast demand. A SeriesKey reading 0.4
			-- percent accuracy on 1.2 forecast units is arithmetically true and
			-- commercially irrelevant; without this column a reader cannot tell the
			-- two apart. Measured across the whole result before LIMIT.
			100.0 * current_forecast.ai_forecast / NULLIF(
				SUM(current_forecast.ai_forecast) OVER (),
				0
			),
			current_forecast.confidence,
			current_forecast.confidence_covered_window_mean,
			current_forecast.interval_covered_from,
			current_forecast.interval_covered_through,
			current_forecast.interval_withheld_weeks,
			current_forecast.interval_unavailable_reason,
			primary_drivers.driver,
			current_forecast.data_quality_class,
			COALESCE(primary_exceptions.severity, 'Low'),
			primary_exceptions.exception_class,
			CASE
				WHEN primary_exceptions.exception_class IS NULL THEN 'Active'
				ELSE 'Review'
			END
		FROM current_forecast
		LEFT JOIN actual_context
		  USING (sku_id, store_id, channel_id)
		LEFT JOIN series_metrics
		  USING (sku_id, store_id, channel_id)
		LEFT JOIN primary_drivers
		  USING (sku_id, store_id, channel_id)
		LEFT JOIN primary_exceptions
		  USING (sku_id, store_id, channel_id)
		ORDER BY
			CASE COALESCE(primary_exceptions.severity, 'Low')
				WHEN 'High' THEN 3
				WHEN 'Medium' THEN 2
				ELSE 1
			END DESC,
			-- Within a severity band, lead with the SeriesKeys that carry demand.
			-- Alphabetical order put "3M Car Care Glass Cleaner" at 1.2 forecast
			-- units on the first screen, and the weakest accuracy in this dataset
			-- sits almost entirely in rows carrying no volume: the 276 withheld rows
			-- are 0.19 percent of units and everything under 40 percent accuracy is
			-- 1.15 percent. Sorting by materiality is what a planner wants anyway,
			-- and the weak tail stays fully reachable by sorting or filtering, which
			-- is what decision #78 requires -- preserve weak slices, do not lead
			-- with them.
			current_forecast.ai_forecast DESC NULLS LAST,
			current_forecast.market_id,
			current_forecast.store_name,
			current_forecast.product_name,
			current_forecast.sku_id,
			current_forecast.channel_id
		LIMIT $%d OFFSET $%d
		`,
		strings.Join(clauses, " AND "),
		len(args)-1,
		len(args),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]map[string]any, 0, query.Limit)
	var total int64
	for rows.Next() {
		var (
			rowTotal                                                    int64
			marketID, skuID, storeID, channelID, departmentID, category string
			productName, channelType, storeName, storeCity              string
			baseline, aiForecast, aiForecastP90, lastActual             *float64
			lastActualWeek                                              *time.Time
			accuracy, wape, bias, demandSharePct                        *float64
			accuracyState                                               string
			// Every aggregated interval value is scanned as nullable. The old
			// non-pointer `confidence` survived only because the window is
			// cumulative from h1 and therefore always contained a calibrated week;
			// any horizon-range filter -- which the P4-1 truth table and Phase 4
			// safety-stock work both invite -- turned it into a request-time scan
			// error rather than a governed unavailable state.
			confidence, confidenceCoveredWindowMean *float64
			intervalCoveredFrom, intervalCoveredThrough *int32
			intervalWithheldWeeks                       int64
			intervalUnavailableReason                   *string
			primaryDriver                               *string
			dataQuality, priority, status               string
			exceptionClass                             *string
		)
		if err := rows.Scan(
			&rowTotal,
			&marketID,
			&skuID,
			&storeID,
			&channelID,
			&departmentID,
			&category,
			&productName,
			&channelType,
			&storeName,
			&storeCity,
			&baseline,
			&aiForecast,
			&aiForecastP90,
			&lastActual,
			&lastActualWeek,
			&accuracy,
			&wape,
			&accuracyState,
			&bias,
			&demandSharePct,
			&confidence,
			&confidenceCoveredWindowMean,
			&intervalCoveredFrom,
			&intervalCoveredThrough,
			&intervalWithheldWeeks,
			&intervalUnavailableReason,
			&primaryDriver,
			&dataQuality,
			&priority,
			&exceptionClass,
			&status,
		); err != nil {
			return nil, err
		}
		total = rowTotal
		var lastActualDate any
		if lastActualWeek != nil {
			lastActualDate = lastActualWeek.Format("2006-01-02")
		}
		// A mixed window is a governed unavailable state, not a missing value, so
		// the reason travels with it. Without a state the consumer cannot tell an
		// unavailable interval from an absent row, and "null means zero spread" is
		// the coercion decision #92 exists to prevent.
		intervalState := "available"
		confidenceState := "measured"
		if intervalWithheldWeeks > 0 {
			intervalState = "unavailable_mixed_window"
			confidenceState = "unavailable_mixed_window"
		}
		var coveredFrom, coveredThrough any
		if intervalCoveredFrom != nil {
			coveredFrom = int(*intervalCoveredFrom)
		}
		if intervalCoveredThrough != nil {
			coveredThrough = int(*intervalCoveredThrough)
		}
		items = append(items, map[string]any{
			"marketId": marketID, "skuId": skuID, "storeId": storeID,
			"channelId": channelID, "departmentId": departmentID,
			"category": category, "productName": productName,
			"channelType": channelType, "storeName": storeName,
			"storeCity": storeCity, "horizonWeeks": query.HorizonWeeks,
			"baseline": baseline, "aiForecast": aiForecast,
			"aiForecastP90": aiForecastP90, "plannerForecast": nil,
			"lastActual": lastActual, "lastActualWeek": lastActualDate,
			"accuracy": accuracy, "wape": wape,
			"accuracyState": accuracyState, "accuracyGrain": "series_key",
			"demandSharePct": demandSharePct,
			"bias": bias, "confidence": confidence,
			"confidenceState": confidenceState,
			// Diagnostic, not the display value. The parity contract renders
			// Confidence unavailable when the window is mixed; this is the
			// arithmetically corrected covered-window mean that the regression
			// asserts, exposed so an API consumer sees the honest figure rather
			// than only its absence. It is rendered nowhere.
			"confidenceCoveredWindowMean":   confidenceCoveredWindowMean,
			"aiForecastP90State":            intervalState,
			"intervalCoveredFromHorizon":    coveredFrom,
			"intervalCoveredThroughHorizon": coveredThrough,
			"intervalWithheldWeeks":         intervalWithheldWeeks,
			"intervalUnavailableReason":     intervalUnavailableReason,
			"primaryDriver":                 primaryDriver,
			"dataQuality":                   dataQuality,
			"priority":                      priority,
			"exceptionClass":                exceptionClass,
			"status":                        status,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-series/v1")
	payload["items"] = items
	payload["pagination"] = map[string]any{
		"offset": query.Offset, "limit": query.Limit, "total": total,
	}
	return payload, nil
}

func (s *ForecastStore) series(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	clauses := []string{"version_id = $1"}
	args := []any{s.versionID}
	clauses, args = appendSeriesFilters(clauses, args, query, map[string]string{
		"market": "market_id", "store": "store_id", "channel": "channel_id",
		"category": "category", "horizon": "horizon_week", "search": "sku_id",
	})
	args = append(args, query.Limit, query.Offset)
	statement := fmt.Sprintf(
		`
		SELECT
			COUNT(*) OVER(),
			market_id, sku_id, store_id, channel_id, dept_id, category,
			horizon_week, target_week_start, yhat_p50, yhat_p90,
			confidence, interval_available, interval_unavailable_reason,
			data_quality_class
		FROM retail_serving.forecast_series
		WHERE %s
		ORDER BY market_id, store_id, sku_id, channel_id, horizon_week
		LIMIT $%d OFFSET $%d
		`,
		strings.Join(clauses, " AND "),
		len(args)-1,
		len(args),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]map[string]any, 0, query.Limit)
	var total int64
	for rows.Next() {
		var (
			marketID, skuID, storeID, channelID, deptID, category string
			qualityClass                                          string
			horizon                                               int
			targetWeek                                            time.Time
			p50                                                   float64
			// Decision #92 withholds the cold-start interval beyond the calibrated
			// horizon, so these arrive NULL. Non-pointer float64 made the scan fail
			// outright with "converting NULL to float64 is unsupported", which is why
			// migration 0008 could not be adopted without this. A null must reach the
			// client as null rather than as a zero: zero spread would be consumed
			// arithmetically as certainty on the least predictable rows.
			p90, confidence *float64
			// Read, never inferred. Migration 0009 stores availability explicitly
			// and constrains it to agree with nullability, so deriving it here from
			// `p90 != nil` would silently re-implement a rule the database already
			// owns -- and would be unable to distinguish a governed withholding from
			// a writer that lost the value.
			intervalAvailable bool
			intervalReason    *string
			rowTotal          int64
		)
		if err := rows.Scan(
			&rowTotal,
			&marketID, &skuID, &storeID, &channelID, &deptID, &category,
			&horizon, &targetWeek, &p50, &p90, &confidence,
			&intervalAvailable, &intervalReason,
			&qualityClass,
		); err != nil {
			return nil, err
		}
		// Defence in depth against a projection written before 0009's constraints.
		// The database refuses this combination now; a request-time refusal is
		// still cheaper than serving a row whose availability disagrees with its
		// own interval.
		if intervalAvailable != (p90 != nil) {
			return nil, forecastReadError(
				ForecastReasonInvalid,
				"interval availability disagrees with the stored interval",
			)
		}
		total = rowTotal
		items = append(items, map[string]any{
			"marketId": marketID, "skuId": skuID, "storeId": storeID,
			"channelId": channelID, "departmentId": deptID, "category": category,
			"horizonWeek": horizon, "targetWeekStart": targetWeek.Format("2006-01-02"),
			"p50": p50, "p90": p90, "confidence": confidence,
			// Present so a client can distinguish "no interval was published, here is
			// why" from "the field is missing", per decision #92.
			"intervalAvailable":         intervalAvailable,
			"intervalUnavailableReason": intervalReason,
			"dataQuality": qualityClass,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-series/v1")
	payload["items"] = items
	payload["pagination"] = map[string]any{
		"offset": query.Offset, "limit": query.Limit, "total": total,
	}
	return payload, nil
}

func (s *ForecastStore) weeklyActuals(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	// "Last 8 weeks" used to mean "the last 8 horizon-1 target weeks". Origins are
	// biweekly, so those 8 points spanned 15 calendar weeks and stopped at
	// 2026-01-26 while actuals run to 2026-07-20 -- the chart showed the oldest
	// slice of the comparison window and labelled it the newest.
	//
	// Now: take the most recent 8 target weeks that have actuals, and for each one
	// use the forecast from the most recent origin that predicted it, i.e. the
	// smallest available horizon. That is the freshest honest forecast for each
	// week, and it makes the label true.
	clauses := []string{
		"evaluation.forecast_run_id = $1",
	}
	args := []any{s.forecastRunID, s.versionID}
	values := []struct {
		value  string
		column string
	}{
		{query.MarketID, "evaluation.market_id"},
		{query.Region, "stores.region"},
		{query.StoreID, "evaluation.store_id"},
		{query.ChannelID, "evaluation.channel_id"},
		{query.ChannelType, "dimensions.channel_type"},
		{query.Category, "evaluation.category"},
	}
	for _, item := range values {
		if item.value == "" {
			continue
		}
		args = append(args, item.value)
		clauses = append(
			clauses,
			fmt.Sprintf("%s = $%d", item.column, len(args)),
		)
	}
	if query.Search != "" {
		args = append(args, "%"+query.Search+"%")
		index := len(args)
		clauses = append(
			clauses,
			fmt.Sprintf(
				"(evaluation.sku_id ILIKE $%d OR dimensions.product_name ILIKE $%d OR stores.name ILIKE $%d OR stores.city ILIKE $%d)",
				index,
				index,
				index,
				index,
			),
		)
	}
	weekCount := query.Limit
	if weekCount > 52 {
		weekCount = 52
	}
	args = append(args, weekCount)
	// Same lesson as the stores aggregate: each join is paid on a full scan of the
	// run, so only add the ones a filter actually needs.
	weeklyJoins := ""
	if query.ChannelType != "" || query.Search != "" {
		weeklyJoins += `
				JOIN retail_serving.forecast_series_dimensions AS dimensions
				  ON dimensions.version_id = $2
				 AND dimensions.sku_id = evaluation.sku_id
				 AND dimensions.store_id = evaluation.store_id
				 AND dimensions.channel_id = evaluation.channel_id`
	}
	if query.Region != "" || query.Search != "" {
		weeklyJoins += `
				JOIN retail_serving.forecast_stores AS stores
				  ON stores.forecast_run_id = evaluation.forecast_run_id
				 AND stores.store_id = evaluation.store_id`
	}
	// See the note in stores: $2 is asserted rather than merely referenced.
	weeklyScoped := "evaluation.forecast_run_id = $1 AND length($2) = 19"
	for _, clause := range clauses[1:] {
		if strings.HasPrefix(clause, "dimensions.version_id") {
			continue
		}
		weeklyScoped += " AND " + clause
	}
	rows, err := s.pool.Query(
		ctx,
		fmt.Sprintf(
			`
			WITH scoped AS (
				SELECT
					evaluation.target_week_start,
					evaluation.horizon,
					evaluation.yhat_p50,
					evaluation.actual_units
				FROM retail_serving.forecast_eval_predictions AS evaluation%s
				WHERE %s
			),
			freshest AS (
				SELECT target_week_start, MIN(horizon) AS horizon
				FROM scoped
				GROUP BY target_week_start
			)
			SELECT
				scoped.target_week_start,
				SUM(scoped.yhat_p50),
				SUM(scoped.actual_units)
			FROM scoped
			JOIN freshest
			  ON freshest.target_week_start = scoped.target_week_start
			 AND freshest.horizon = scoped.horizon
			GROUP BY scoped.target_week_start
			ORDER BY scoped.target_week_start DESC
			LIMIT $%d
			`,
			weeklyJoins,
			weeklyScoped,
			len(args),
		),
		args...,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var targetWeek time.Time
		var forecast, actual float64
		if err := rows.Scan(&targetWeek, &forecast, &actual); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"targetWeekStart": targetWeek.Format("2006-01-02"),
			"forecast":        forecast,
			"actual":          actual,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for left, right := 0, len(items)-1; left < right; left, right = left+1, right-1 {
		items[left], items[right] = items[right], items[left]
	}
	payload := s.envelope("retail-forecast-actuals/v1")
	payload["items"] = items
	return payload, nil
}

func (s *ForecastStore) actuals(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	clauses := []string{"forecast_run_id = $1"}
	args := []any{s.forecastRunID}
	clauses, args = appendSeriesFilters(clauses, args, query, map[string]string{
		"market": "market_id", "store": "store_id", "channel": "channel_id",
		"category": "category", "horizon": "horizon", "search": "sku_id",
	})
	args = append(args, query.Limit, query.Offset)
	statement := fmt.Sprintf(
		`
		SELECT
			COUNT(*) OVER(),
			forecast_origin, target_week_start, market_id, sku_id, store_id,
			channel_id, horizon, dept_id, category, actual_units,
			yhat_p50, yhat_p90, confidence, selected_model
		FROM retail_serving.forecast_eval_predictions
		WHERE %s
		ORDER BY forecast_origin DESC, target_week_start, market_id, store_id,
		         sku_id, channel_id, horizon
		LIMIT $%d OFFSET $%d
		`,
		strings.Join(clauses, " AND "),
		len(args)-1,
		len(args),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]map[string]any, 0, query.Limit)
	var total int64
	for rows.Next() {
		var (
			rowTotal                                              int64
			origin, target                                        time.Time
			marketID, skuID, storeID, channelID, deptID, category string
			model                                                 string
			horizon                                               int
			actual, p50, p90, confidence                          float64
		)
		if err := rows.Scan(
			&rowTotal, &origin, &target, &marketID, &skuID, &storeID,
			&channelID, &horizon, &deptID, &category, &actual,
			&p50, &p90, &confidence, &model,
		); err != nil {
			return nil, err
		}
		total = rowTotal
		items = append(items, map[string]any{
			"forecastOrigin":  origin.Format("2006-01-02"),
			"targetWeekStart": target.Format("2006-01-02"),
			"marketId":        marketID, "skuId": skuID, "storeId": storeID,
			"channelId": channelID, "horizon": horizon,
			"departmentId": deptID, "category": category,
			"actualUnits": actual, "p50": p50, "p90": p90,
			"confidence": confidence, "selectedModel": model,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-actuals/v1")
	payload["items"] = items
	payload["pagination"] = map[string]any{
		"offset": query.Offset, "limit": query.Limit, "total": total,
	}
	return payload, nil
}

type additiveMetric struct {
	Horizon        int
	AbsErrorSum    float64
	SignedErrorSum float64
	ActualSum      float64
	CoverageHits   int64
	N              int64
}

func ratio(numerator, denominator float64) *float64 {
	if denominator == 0 {
		return nil
	}
	value := numerator / denominator
	if math.IsNaN(value) || math.IsInf(value, 0) {
		return nil
	}
	return &value
}

func metricItem(metric additiveMetric) map[string]any {
	wape := ratio(metric.AbsErrorSum, metric.ActualSum)
	bias := ratio(metric.SignedErrorSum, metric.ActualSum)
	coverage := ratio(float64(metric.CoverageHits), float64(metric.N))
	var accuracy *float64
	if wape != nil {
		value := 100 * (1 - *wape)
		accuracy = &value
	}
	return map[string]any{
		"horizon":     metric.Horizon,
		"absErrorSum": metric.AbsErrorSum, "signedErrorSum": metric.SignedErrorSum,
		"actualSum": metric.ActualSum, "coverageHits": metric.CoverageHits, "n": metric.N,
		"wape": wape, "bias": bias, "accuracy": accuracy, "p90Coverage": coverage,
	}
}

// Decision #77 grain resolution, applied server-side so the metric matches the
// target the client will compare it against. The same first-matching-rule order
// the UI uses: a SeriesKey selection wins, then a single store or category, then
// portfolio. A channel filter never changes the grain.
func resolveHealthGrain(query ForecastQuery) (string, []string) {
	// series_key is deliberately unreachable here. Decision #77 grants it only when
	// "exactly one complete sku_id x store_id x channel_id SeriesKey is explicitly
	// selected", and this screen has no SeriesKey selector -- the UI says so at the
	// point it resolves the grain. Free-text search is not a selector: it can match
	// many SKUs, and because series_key carries no grouping columns those matches
	// would be summed into one cell and then scored against the SeriesKey target as
	// though they were a single series.
	//
	// A store or category selection narrows the population without changing what a
	// row is, so it resolves to store_category, and everything else is portfolio.
	if query.StoreID != "" || query.Category != "" {
		// Bare column names: these are grouped inside the `cells` CTE, which
		// selects from `scoped`, not from `evaluation`.
		return "store_category", []string{"store_id", "category"}
	}
	return "market_portfolio", []string{"market_id"}
}

func (s *ForecastStore) horizons(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	clauses := []string{
		"evaluation.forecast_run_id = $1",
		"dimensions.version_id = $2",
	}
	args := []any{s.forecastRunID, s.versionID}
	clauses, args = appendSeriesFilters(clauses, args, query, map[string]string{
		"market": "evaluation.market_id", "store": "evaluation.store_id",
		"channel": "evaluation.channel_id", "category": "evaluation.category",
		"horizon": "evaluation.horizon",
		"search":  "CONCAT(evaluation.sku_id, ' ', dimensions.product_name, ' ', stores.name, ' ', stores.city)",
	})
	if query.Region != "" {
		args = append(args, query.Region)
		clauses = append(clauses, fmt.Sprintf("stores.region = $%d", len(args)))
	}
	if query.ChannelType != "" {
		args = append(args, query.ChannelType)
		clauses = append(
			clauses,
			fmt.Sprintf("dimensions.channel_type = $%d", len(args)),
		)
	}
	grain, grainColumns := resolveHealthGrain(query)
	// Same treatment as stores and weekly actuals: this aggregate scans every
	// evaluation row for the run, so a join it does not need is paid on the whole
	// scan. With several materialisations accumulated the table holds millions of
	// rows and the unconditional joins pushed the response past the write deadline,
	// surfacing only "i/o timeout".
	horizonJoins := ""
	if query.ChannelType != "" || query.Search != "" {
		horizonJoins += `
				JOIN retail_serving.forecast_series_dimensions AS dimensions
				  ON dimensions.version_id = $2
				 AND dimensions.sku_id = evaluation.sku_id
				 AND dimensions.store_id = evaluation.store_id
				 AND dimensions.channel_id = evaluation.channel_id`
	}
	if query.Region != "" || query.Search != "" {
		horizonJoins += `
				JOIN retail_serving.forecast_stores AS stores
				  ON stores.forecast_run_id = evaluation.forecast_run_id
				 AND stores.store_id = evaluation.store_id`
	}
	horizonScoped := "evaluation.forecast_run_id = $1 AND length($2) = 19"
	for _, clause := range clauses {
		if strings.HasPrefix(clause, "evaluation.forecast_run_id") ||
			strings.HasPrefix(clause, "dimensions.version_id") {
			continue
		}
		horizonScoped += " AND " + clause
	}

	// Decision #77 declares exact_horizon_additive semantics: at a grain above
	// SeriesKey, actual and predicted are summed into the grain cell BEFORE any
	// error is taken. Summing per-row abs_error_sum instead -- which is what this
	// handler used to do -- yields leaf accuracy under whatever label the client
	// resolved, so the Forecast Health table read 78.27% against a 90% portfolio
	// target and showed Action on four rows that all pass at 95.18%.
	//
	// P90 coverage is measured at leaf grain in the same statement and reported
	// separately, because a sum of P90s is not the P90 of a sum. Quantiles do not
	// aggregate, so coverage has exactly one honest grain and it is labelled.
	cellGrouping := append([]string{}, grainColumns...)
	cellGrouping = append(
		cellGrouping,
		"horizon",
		"forecast_origin",
		"target_week_start",
	)
	statement := fmt.Sprintf(
		`
		WITH scoped AS (
			SELECT
				evaluation.horizon,
				evaluation.forecast_origin,
				evaluation.target_week_start,
				evaluation.market_id,
				evaluation.store_id,
				evaluation.category,
				evaluation.actual_units,
				evaluation.yhat_p50,
				evaluation.coverage_hits,
				evaluation.n
			FROM retail_serving.forecast_eval_predictions AS evaluation%s
				WHERE %s
		),
		cells AS (
			SELECT
				horizon,
				SUM(actual_units) AS actual,
				SUM(yhat_p50) AS predicted
			FROM scoped
			GROUP BY %s
		),
		leaf AS (
			SELECT horizon, SUM(coverage_hits) AS hits, SUM(n) AS rows_counted
			FROM scoped
			GROUP BY horizon
		)
		SELECT
			cells.horizon,
			SUM(ABS(cells.predicted - cells.actual)),
			SUM(cells.predicted - cells.actual),
			SUM(cells.actual),
			COALESCE(MAX(leaf.hits), 0),
			COALESCE(MAX(leaf.rows_counted), 0),
			COUNT(*)
		FROM cells
		LEFT JOIN leaf ON leaf.horizon = cells.horizon
		GROUP BY cells.horizon
		ORDER BY cells.horizon
		`,
		horizonJoins,
		horizonScoped,
		strings.Join(cellGrouping, ", "),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]map[string]any, 0, 26)
	for rows.Next() {
		var metric additiveMetric
		var cellCount int64
		if err := rows.Scan(
			&metric.Horizon, &metric.AbsErrorSum, &metric.SignedErrorSum,
			&metric.ActualSum, &metric.CoverageHits, &metric.N, &cellCount,
		); err != nil {
			return nil, err
		}
		item := metricItem(metric)
		item["metricGrain"] = grain
		item["coverageGrain"] = "series_key"
		item["grainCells"] = cellCount
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-horizons/v1")
	payload["items"] = items
	payload["metricGrain"] = grain
	payload["metricSemantics"] = "exact_horizon_additive"
	payload["coverageGrain"] = "series_key"
	payload["coverageNote"] = "P90 coverage is measured at SeriesKey grain because quantiles do not aggregate; a sum of P90 bounds is not the P90 of the sum."
	return payload, nil
}

func (s *ForecastStore) stores(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	clauses := []string{
		"evaluation.forecast_run_id = $1",
		"dimensions.version_id = $2",
		"evaluation.horizon <= $3",
	}
	args := []any{s.forecastRunID, s.versionID, query.HorizonWeeks}
	values := []struct {
		value  string
		column string
	}{
		{query.MarketID, "evaluation.market_id"},
		{query.Region, "stores.region"},
		{query.StoreID, "evaluation.store_id"},
		{query.ChannelID, "evaluation.channel_id"},
		{query.ChannelType, "dimensions.channel_type"},
		{query.Category, "evaluation.category"},
	}
	for _, item := range values {
		if item.value == "" {
			continue
		}
		args = append(args, item.value)
		clauses = append(
			clauses,
			fmt.Sprintf("%s = $%d", item.column, len(args)),
		)
	}
	if query.Search != "" {
		args = append(args, "%"+query.Search+"%")
		index := len(args)
		clauses = append(
			clauses,
			fmt.Sprintf(
				"(evaluation.sku_id ILIKE $%d OR dimensions.product_name ILIKE $%d OR stores.name ILIKE $%d OR stores.city ILIKE $%d)",
				index,
				index,
				index,
				index,
			),
		)
	}
	// The aggregate touches every evaluation row for the run, so each join is paid
	// on the full scan. Under a generic prepared-statement plan the two joins took
	// this query from well under a second to roughly 37, past the request deadline,
	// and the handler surfaced only "context canceled". They are needed for the
	// region, channel-type and search filters and for nothing else, so they are
	// added only when one of those is actually in play.
	joins := ""
	if query.ChannelType != "" || query.Search != "" {
		joins += `
				JOIN retail_serving.forecast_series_dimensions AS dimensions
				  ON dimensions.version_id = $2
				 AND dimensions.sku_id = evaluation.sku_id
				 AND dimensions.store_id = evaluation.store_id
				 AND dimensions.channel_id = evaluation.channel_id`
	}
	if query.Region != "" || query.Search != "" {
		joins += `
				JOIN retail_serving.forecast_stores AS stores
				  ON stores.forecast_run_id = evaluation.forecast_run_id
				 AND stores.store_id = evaluation.store_id`
	}
	// $2 is the version id. With no join there is no dimensions table to constrain
	// it against, and forecast_eval_predictions carries no version column, so the
	// run id is what pins the rows -- forecast_run_id is unique per version. The
	// assertion is kept as an explicit non-empty check rather than a placeholder
	// comparison so a caller that lost the version cannot read a bundle by run id
	// alone.
	scoped := "evaluation.forecast_run_id = $1 AND length($2) = 19"
	for _, clause := range clauses[1:] {
		if strings.HasPrefix(clause, "dimensions.version_id") {
			continue
		}
		scoped += " AND " + clause
	}
	rows, err := s.pool.Query(
		ctx,
		fmt.Sprintf(
			`
			-- A store row's subject is the store, so decision #77's additive
			-- semantics apply: sum actual and predicted into the store's weekly
			-- cell first, then take the error. Summing per-row errors reported
			-- 73.35 accuracy points for Mumbai Bandra where the store's own
			-- accuracy is 92.90. No literal percent sign belongs in this string --
			-- it is a fmt.Sprintf format and a stray percent is read as a verb.
			-- P90 coverage stays leaf-grain and is labelled, because quantiles do
			-- not aggregate.
			WITH cells AS (
				SELECT
					evaluation.store_id,
					evaluation.forecast_origin,
					evaluation.target_week_start,
					evaluation.horizon,
					SUM(evaluation.actual_units) AS actual,
					SUM(evaluation.yhat_p50) AS predicted,
					SUM(evaluation.coverage_hits) AS coverage_hits,
					SUM(evaluation.n) AS n
				FROM retail_serving.forecast_eval_predictions AS evaluation%s
				WHERE %s
				GROUP BY
					evaluation.store_id,
					evaluation.forecast_origin,
					evaluation.target_week_start,
					evaluation.horizon
			),
			filtered_metrics AS (
				SELECT
					store_id,
					SUM(ABS(predicted - actual)) AS abs_error_sum,
					SUM(predicted - actual) AS signed_error_sum,
					SUM(actual) AS actual_sum,
					SUM(coverage_hits) AS coverage_hits,
					SUM(n) AS n
				FROM cells
				GROUP BY store_id
			)
			SELECT
				store_rows.store_id, store_rows.market_id, store_rows.name,
				store_rows.city, store_rows.region, store_rows.timezone,
				store_rows.currency_code, store_rows.format, store_rows.active,
				CASE
					WHEN metrics.actual_sum = 0 THEN NULL
					ELSE 100.0 * (1.0 - metrics.abs_error_sum / metrics.actual_sum)
				END,
				CASE
					WHEN metrics.actual_sum = 0 THEN NULL
					ELSE metrics.signed_error_sum / metrics.actual_sum
				END,
				CASE
					WHEN metrics.n = 0 THEN NULL
					ELSE metrics.coverage_hits::double precision / metrics.n
				END
			-- Aliased store_rows rather than stores: the cells CTE already binds the
			-- name stores for the region filter, and reusing it in the outer scope
			-- leaves each reference ambiguous. No backticks in this string -- it is a
			-- Go raw literal and a backtick ends it.
			FROM retail_serving.forecast_stores AS store_rows
			JOIN filtered_metrics AS metrics
			  ON metrics.store_id = store_rows.store_id
			WHERE store_rows.forecast_run_id = $1
			ORDER BY store_rows.market_id, store_rows.name, store_rows.store_id
			`,
			joins,
			scoped,
		),
		args...,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var (
			storeID, marketID, name, city, region, timezone string
			currency, format                                string
			active                                          bool
			accuracy, bias, coverage                        *float64
		)
		if err := rows.Scan(
			&storeID, &marketID, &name, &city, &region, &timezone,
			&currency, &format, &active, &accuracy, &bias, &coverage,
		); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"storeId": storeID, "marketId": marketID, "name": name,
			"city": city, "region": region, "timezone": timezone,
			"currencyCode": currency, "format": format, "active": active,
			"accuracy": accuracy, "bias": bias, "p90Coverage": coverage,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-stores/v1")
	payload["items"] = items
	return payload, nil
}

func (s *ForecastStore) drivers(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	scope := query.Scope
	if scope == "" {
		scope = "portfolio"
	}
	rows, err := s.pool.Query(
		ctx,
		`
		SELECT scope, driver, contribution_pct::text, direction, confidence::text
		FROM retail_serving.forecast_drivers
		WHERE version_id = $1 AND scope = $2
		ORDER BY driver
		`,
		s.versionID,
		scope,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []map[string]any{}
	for rows.Next() {
		var rowScope, driver, contribution, direction, confidence string
		if err := rows.Scan(
			&rowScope, &driver, &contribution, &direction, &confidence,
		); err != nil {
			return nil, err
		}
		items = append(items, map[string]any{
			"scope": rowScope, "driver": driver,
			"contributionPct": contribution, "direction": direction,
			"confidence": confidence,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-drivers/v1")
	payload["items"] = items
	payload["unavailableItems"] = []map[string]any{{
		"driver":     "promo",
		"label":      "Promotion plan",
		"reasonCode": "NO_ORIGIN_VISIBLE_PROMOTION_PLAN",
	}}
	return payload, nil
}

func (s *ForecastStore) signals() map[string]any {
	payload := s.envelope("retail-forecast-signals/v1")
	payload["items"] = []map[string]any{
		{
			"signal": "promotion_calendar", "label": "Promotion calendar",
			"status":     "unavailable",
			"reasonCode": "NO_ORIGIN_VISIBLE_PROMOTION_PLAN",
			"knownAsOf":  nil,
		},
		{
			"signal": "competitor_pricing", "label": "Competitor pricing",
			"status":     "unavailable",
			"reasonCode": "SIGNAL_FRESHNESS_NOT_MATERIALIZED",
			"knownAsOf":  nil,
		},
		{
			"signal": "weather", "label": "Weather feed",
			"status":     "unavailable",
			"reasonCode": "SIGNAL_FRESHNESS_NOT_MATERIALIZED",
			"knownAsOf":  nil,
		},
		{
			"signal": "local_events", "label": "Local event feed",
			"status":     "unavailable",
			"reasonCode": "NO_ORIGIN_VISIBLE_LOCAL_EVENT_PLAN",
			"knownAsOf":  nil,
		},
		{
			"signal": "macro", "label": "Macroeconomic index",
			"status":     "unavailable",
			"reasonCode": "SIGNAL_FRESHNESS_NOT_MATERIALIZED",
			"knownAsOf":  nil,
		},
	}
	payload["freshnessBaseline"] = s.decisionAsOf.UTC().Format(time.RFC3339Nano)
	return payload
}

func (s *ForecastStore) exceptions(
	ctx context.Context,
	query ForecastQuery,
) (map[string]any, error) {
	clauses := []string{"version_id = $1"}
	args := []any{s.versionID}
	if query.MarketID != "" {
		args = append(args, query.MarketID)
		clauses = append(clauses, fmt.Sprintf("market_id = $%d", len(args)))
	}
	if query.StoreID != "" {
		args = append(args, query.StoreID)
		clauses = append(clauses, fmt.Sprintf("store_id = $%d", len(args)))
	}
	if query.ChannelID != "" {
		args = append(args, query.ChannelID)
		clauses = append(clauses, fmt.Sprintf("channel_id = $%d", len(args)))
	}
	if query.ExceptionClass != "" {
		args = append(args, query.ExceptionClass)
		clauses = append(
			clauses,
			fmt.Sprintf("exception_class = $%d", len(args)),
		)
	}
	if query.Search != "" {
		args = append(args, "%"+query.Search+"%")
		clauses = append(clauses, fmt.Sprintf("sku_id ILIKE $%d", len(args)))
	}
	args = append(args, query.Limit, query.Offset)
	rows, err := s.pool.Query(
		ctx,
		fmt.Sprintf(
			`
			SELECT
				COUNT(*) OVER(), market_id, sku_id, store_id, channel_id,
				exception_class, severity, status, threshold, evidence,
				policy_id, policy_semantic_fingerprint
			FROM retail_serving.forecast_exceptions
			WHERE %s
			ORDER BY severity DESC, exception_class, market_id, store_id, sku_id
			LIMIT $%d OFFSET $%d
			`,
			strings.Join(clauses, " AND "),
			len(args)-1,
			len(args),
		),
		args...,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]map[string]any, 0, query.Limit)
	var total int64
	for rows.Next() {
		var (
			rowTotal                                                     int64
			marketID, skuID, storeID, channelID, class, severity, status string
			threshold, evidence, policyID, policyFingerprint             string
		)
		if err := rows.Scan(
			&rowTotal, &marketID, &skuID, &storeID, &channelID,
			&class, &severity, &status, &threshold, &evidence,
			&policyID, &policyFingerprint,
		); err != nil {
			return nil, err
		}
		total = rowTotal
		items = append(items, map[string]any{
			"marketId": marketID, "skuId": skuID, "storeId": storeID,
			"channelId": channelID, "exceptionClass": class,
			"severity": severity, "status": status, "threshold": threshold,
			"evidence": evidence, "policyId": policyID,
			"policySemanticFingerprint": policyFingerprint,
		})
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-exceptions/v1")
	payload["items"] = items
	payload["pagination"] = map[string]any{
		"offset": query.Offset, "limit": query.Limit, "total": total,
	}
	return payload, nil
}
