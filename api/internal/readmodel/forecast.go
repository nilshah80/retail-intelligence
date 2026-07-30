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
	ForecastMigrationRevision = "0005_complete_pairing_verifier"

	ForecastReasonInvalid        = "FORECAST_ARTIFACT_INVALID"
	ForecastReasonLineage        = "FORECAST_LINEAGE_MISMATCH"
	ForecastReasonUnmaterialized = "FORECAST_READ_MODEL_UNAVAILABLE"
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
	var stillActive bool
	err := s.pool.QueryRow(
		ctx,
		`
		SELECT EXISTS (
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
	).Scan(&stillActive)
	if err != nil {
		return nil, forecastReadError(
			ForecastReasonUnmaterialized,
			"forecast activation could not be revalidated",
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
	payload := s.envelope("retail-forecast-summary/v1")
	payload["items"] = []map[string]any{{
		"accuracy":            accuracy,
		"bias":                bias,
		"p90Coverage":         p90Coverage,
		"baselineAccuracy":    baselineAccuracy,
		"fvaVsMa13Pct":        fvaVsMA13,
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
				SUM(series.yhat_p90) AS ai_forecast_p90,
				SUM(
					series.confidence * GREATEST(series.yhat_p50, 1.0)
				) / NULLIF(
					SUM(GREATEST(series.yhat_p50, 1.0)),
					0
				) AS confidence,
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
		series_metrics AS (
			SELECT
				slice_id::jsonb ->> 0 AS sku_id,
				slice_id::jsonb ->> 1 AS store_id,
				slice_id::jsonb ->> 2 AS channel_id,
				accuracy,
				bias
			FROM retail_serving.forecast_metrics
			WHERE forecast_run_id = $3
			  AND slice_type = 'series'
			  AND horizon = 0
			  AND model_id = 'champion'
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
			series_metrics.bias,
			current_forecast.confidence,
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
			accuracy, bias                                              *float64
			confidence                                                  float64
			primaryDriver                                               *string
			dataQuality, priority, status                               string
			exceptionClass                                              *string
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
			&bias,
			&confidence,
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
		items = append(items, map[string]any{
			"marketId": marketID, "skuId": skuID, "storeId": storeID,
			"channelId": channelID, "departmentId": departmentID,
			"category": category, "productName": productName,
			"channelType": channelType, "storeName": storeName,
			"storeCity": storeCity, "horizonWeeks": query.HorizonWeeks,
			"baseline": baseline, "aiForecast": aiForecast,
			"aiForecastP90": aiForecastP90, "plannerForecast": nil,
			"lastActual": lastActual, "lastActualWeek": lastActualDate,
			"accuracy": accuracy, "bias": bias, "confidence": confidence,
			"primaryDriver": primaryDriver, "dataQuality": dataQuality,
			"priority": priority, "exceptionClass": exceptionClass,
			"status": status,
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
			confidence, data_quality_class
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
			p50, p90, confidence                                  float64
			rowTotal                                              int64
		)
		if err := rows.Scan(
			&rowTotal,
			&marketID, &skuID, &storeID, &channelID, &deptID, &category,
			&horizon, &targetWeek, &p50, &p90, &confidence, &qualityClass,
		); err != nil {
			return nil, err
		}
		total = rowTotal
		items = append(items, map[string]any{
			"marketId": marketID, "skuId": skuID, "storeId": storeID,
			"channelId": channelID, "departmentId": deptID, "category": category,
			"horizonWeek": horizon, "targetWeekStart": targetWeek.Format("2006-01-02"),
			"p50": p50, "p90": p90, "confidence": confidence,
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
	clauses := []string{
		"evaluation.forecast_run_id = $1",
		"evaluation.horizon = 1",
		"dimensions.version_id = $2",
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
	rows, err := s.pool.Query(
		ctx,
		fmt.Sprintf(
			`
			SELECT
				evaluation.target_week_start,
				SUM(evaluation.yhat_p50),
				SUM(evaluation.actual_units)
			FROM retail_serving.forecast_eval_predictions AS evaluation
			JOIN retail_serving.forecast_series_dimensions AS dimensions
			  ON dimensions.version_id = $2
			 AND dimensions.sku_id = evaluation.sku_id
			 AND dimensions.store_id = evaluation.store_id
			 AND dimensions.channel_id = evaluation.channel_id
			JOIN retail_serving.forecast_stores AS stores
			  ON stores.forecast_run_id = dimensions.forecast_run_id
			 AND stores.store_id = dimensions.store_id
			WHERE %s
			GROUP BY evaluation.target_week_start
			ORDER BY evaluation.target_week_start DESC
			LIMIT $%d
			`,
			strings.Join(clauses, " AND "),
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
	statement := fmt.Sprintf(
		`
		SELECT
			evaluation.horizon,
			SUM(evaluation.abs_error_sum),
			SUM(evaluation.signed_error_sum),
			SUM(evaluation.actual_sum),
			SUM(evaluation.coverage_hits),
			SUM(evaluation.n)
		FROM retail_serving.forecast_eval_predictions AS evaluation
		JOIN retail_serving.forecast_series_dimensions AS dimensions
		  ON dimensions.version_id = $2
		 AND dimensions.sku_id = evaluation.sku_id
		 AND dimensions.store_id = evaluation.store_id
		 AND dimensions.channel_id = evaluation.channel_id
		JOIN retail_serving.forecast_stores AS stores
		  ON stores.forecast_run_id = dimensions.forecast_run_id
		 AND stores.store_id = dimensions.store_id
		WHERE %s
		GROUP BY evaluation.horizon
		ORDER BY evaluation.horizon
		`,
		strings.Join(clauses, " AND "),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := make([]map[string]any, 0, 26)
	for rows.Next() {
		var metric additiveMetric
		if err := rows.Scan(
			&metric.Horizon, &metric.AbsErrorSum, &metric.SignedErrorSum,
			&metric.ActualSum, &metric.CoverageHits, &metric.N,
		); err != nil {
			return nil, err
		}
		items = append(items, metricItem(metric))
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-forecast-horizons/v1")
	payload["items"] = items
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
	rows, err := s.pool.Query(
		ctx,
		fmt.Sprintf(
			`
			WITH filtered_metrics AS (
				SELECT
					evaluation.store_id,
					SUM(evaluation.abs_error_sum) AS abs_error_sum,
					SUM(evaluation.signed_error_sum) AS signed_error_sum,
					SUM(evaluation.actual_sum) AS actual_sum,
					SUM(evaluation.coverage_hits) AS coverage_hits,
					SUM(evaluation.n) AS n
				FROM retail_serving.forecast_eval_predictions AS evaluation
				JOIN retail_serving.forecast_series_dimensions AS dimensions
				  ON dimensions.version_id = $2
				 AND dimensions.sku_id = evaluation.sku_id
				 AND dimensions.store_id = evaluation.store_id
				 AND dimensions.channel_id = evaluation.channel_id
				JOIN retail_serving.forecast_stores AS stores
				  ON stores.forecast_run_id = evaluation.forecast_run_id
				 AND stores.store_id = evaluation.store_id
				WHERE %s
				GROUP BY evaluation.store_id
			)
			SELECT
				stores.store_id, stores.market_id, stores.name, stores.city,
				stores.region, stores.timezone, stores.currency_code,
				stores.format, stores.active,
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
			FROM retail_serving.forecast_stores AS stores
			JOIN filtered_metrics AS metrics
			  ON metrics.store_id = stores.store_id
			WHERE stores.forecast_run_id = $1
			ORDER BY stores.market_id, stores.name, stores.store_id
			`,
			strings.Join(clauses, " AND "),
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
