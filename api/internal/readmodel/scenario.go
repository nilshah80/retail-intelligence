package readmodel

import (
	"context"
	"errors"
	"fmt"
	"regexp"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	ScenarioContextBootstrapSchema = "retail-forecast-scenario-context-bootstrap/v1"
	ScenarioUnavailableSchema      = "retail-forecast-scenario-unavailable/v1"
	ScenarioStaleSchema            = "retail-forecast-scenario-stale/v1"

	ScenarioReasonBaseMissing        = "SCENARIO_BASE_CONTEXT_MISSING"
	ScenarioReasonBaseAmbiguous      = "SCENARIO_BASE_CONTEXT_AMBIGUOUS"
	ScenarioReasonInventoryAmbiguous = "SCENARIO_INVENTORY_EXTENSION_AMBIGUOUS"
	ScenarioReasonForecastStale      = "SCENARIO_FORECAST_VERSION_STALE"
	ScenarioReasonContextStale       = "SCENARIO_CONTEXT_STALE"
	ScenarioReasonSchemaInvalid      = "SCENARIO_SERVING_SCHEMA_INVALID"
	ScenarioReasonReadUnavailable    = "SCENARIO_READ_MODEL_UNAVAILABLE"
)

var scenarioForecastVersionPattern = regexp.MustCompile(`^fv_[0-9a-f]{16}$`)

type ScenarioConfig struct {
	PostgresDSN                string
	RetailerID                 string
	TenantID                   string
	Environment                string
	DBReadPool                 int
	ReportingCurrency          string
	ReportingFXRates           []ScenarioFXRateObservation
	ReportingSourceFingerprint string
}

type ScenarioFXRateObservation struct {
	BaseCurrency  string
	QuoteCurrency string
	Rate          string
	RateDate      string
}

type ScenarioInventoryAuthority struct {
	InventoryVersion          string `json:"inventoryVersion"`
	InventoryExtensionVersion string `json:"inventoryExtensionVersion"`
}

type ScenarioAuthorityTuple struct {
	ForecastVersion        string                      `json:"forecastVersion"`
	ScenarioContextVersion string                      `json:"scenarioContextVersion"`
	Inventory              *ScenarioInventoryAuthority `json:"inventory"`
}

type ScenarioAuthorityReference struct {
	ForecastVersion        *string                     `json:"forecastVersion"`
	ScenarioContextVersion *string                     `json:"scenarioContextVersion"`
	Inventory              *ScenarioInventoryAuthority `json:"inventory"`
}

type ScenarioContextBootstrap struct {
	SchemaVersion          string                      `json:"schemaVersion"`
	ForecastVersion        string                      `json:"forecastVersion"`
	ScenarioContextVersion string                      `json:"scenarioContextVersion"`
	Inventory              *ScenarioInventoryAuthority `json:"inventory"`
	ScenarioDecisionAsOf   time.Time                   `json:"scenarioDecisionAsOf"`
}

func (b ScenarioContextBootstrap) Authority() ScenarioAuthorityTuple {
	return ScenarioAuthorityTuple{
		ForecastVersion:        b.ForecastVersion,
		ScenarioContextVersion: b.ScenarioContextVersion,
		Inventory:              b.Inventory,
	}
}

type ScenarioUnavailable struct {
	SchemaVersion          string  `json:"schemaVersion"`
	DataMode               string  `json:"dataMode"`
	ScenarioContextVersion *string `json:"scenarioContextVersion"`
	ReasonCode             string  `json:"reasonCode"`
	Message                string  `json:"message"`
}

type ScenarioStale struct {
	SchemaVersion string                     `json:"schemaVersion"`
	DataMode      string                     `json:"dataMode"`
	ReasonCode    string                     `json:"reasonCode"`
	Message       string                     `json:"message"`
	Expected      ScenarioAuthorityReference `json:"expected"`
	Current       ScenarioAuthorityReference `json:"current"`
}

type scenarioErrorKind uint8

const (
	scenarioUnavailableError scenarioErrorKind = iota + 1
	scenarioStaleError
)

type ScenarioReadError struct {
	kind        scenarioErrorKind
	reasonCode  string
	message     string
	unavailable ScenarioUnavailable
	stale       ScenarioStale
}

func (e *ScenarioReadError) Error() string { return e.message }

func ScenarioReadErrorStatus(err error) int {
	var scenarioErr *ScenarioReadError
	if errors.As(err, &scenarioErr) && scenarioErr.kind == scenarioStaleError {
		return 409
	}
	return 503
}

func ScenarioReadErrorPayload(err error) any {
	var scenarioErr *ScenarioReadError
	if !errors.As(err, &scenarioErr) {
		return ScenarioUnavailable{
			SchemaVersion: ScenarioUnavailableSchema,
			DataMode:      "unavailable",
			ReasonCode:    ScenarioReasonReadUnavailable,
			Message:       "Forecast Scenario Planning context is unavailable.",
		}
	}
	if scenarioErr.kind == scenarioStaleError {
		return scenarioErr.stale
	}
	return scenarioErr.unavailable
}

type ScenarioStore struct {
	pool                       *pgxpool.Pool
	retailerID                 string
	tenantID                   string
	environment                string
	reportingCurrency          string
	reportingFXRates           []ScenarioFXRateObservation
	reportingSourceFingerprint string
	loadError                  *ScenarioReadError
}

func unavailableScenarioStore(reasonCode, message string) *ScenarioStore {
	err := scenarioUnavailable(reasonCode, message, nil)
	var readErr *ScenarioReadError
	errors.As(err, &readErr)
	return &ScenarioStore{loadError: readErr}
}

func scenarioUnavailable(
	reasonCode string,
	message string,
	contextVersion *string,
) error {
	payload := ScenarioUnavailable{
		SchemaVersion:          ScenarioUnavailableSchema,
		DataMode:               "unavailable",
		ScenarioContextVersion: contextVersion,
		ReasonCode:             reasonCode,
		Message:                message,
	}
	return &ScenarioReadError{
		kind:        scenarioUnavailableError,
		reasonCode:  reasonCode,
		message:     message,
		unavailable: payload,
	}
}

func authorityReference(tuple *ScenarioAuthorityTuple) ScenarioAuthorityReference {
	if tuple == nil {
		return ScenarioAuthorityReference{}
	}
	forecast := tuple.ForecastVersion
	reference := ScenarioAuthorityReference{
		ForecastVersion: &forecast,
		Inventory:       tuple.Inventory,
	}
	if tuple.ScenarioContextVersion != "" {
		contextVersion := tuple.ScenarioContextVersion
		reference.ScenarioContextVersion = &contextVersion
	}
	return reference
}

func scenarioStale(
	reasonCode string,
	message string,
	expected *ScenarioAuthorityTuple,
	current *ScenarioAuthorityTuple,
) error {
	payload := ScenarioStale{
		SchemaVersion: ScenarioStaleSchema,
		DataMode:      "stale",
		ReasonCode:    reasonCode,
		Message:       message,
		Expected:      authorityReference(expected),
		Current:       authorityReference(current),
	}
	return &ScenarioReadError{
		kind:       scenarioStaleError,
		reasonCode: reasonCode,
		message:    message,
		stale:      payload,
	}
}

func LoadScenario(ctx context.Context, config ScenarioConfig) *ScenarioStore {
	if config.PostgresDSN == "" || config.RetailerID == "" ||
		config.TenantID == "" || config.Environment == "" {
		return unavailableScenarioStore(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning authority is not configured.",
		)
	}
	poolConfig, err := pgxpool.ParseConfig(config.PostgresDSN)
	if err != nil {
		return unavailableScenarioStore(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning database configuration is invalid.",
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
		return unavailableScenarioStore(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning database is unavailable.",
		)
	}
	var migration string
	err = pool.QueryRow(
		ctx,
		"SELECT version_num FROM retail_intelligence_alembic_version",
	).Scan(&migration)
	if err != nil || migration != ForecastMigrationRevision {
		pool.Close()
		return unavailableScenarioStore(
			ScenarioReasonSchemaInvalid,
			fmt.Sprintf(
				"Forecast Scenario Planning requires serving migration %s.",
				ForecastMigrationRevision,
			),
		)
	}
	return &ScenarioStore{
		pool:                       pool,
		retailerID:                 config.RetailerID,
		tenantID:                   config.TenantID,
		environment:                config.Environment,
		reportingCurrency:          config.ReportingCurrency,
		reportingFXRates:           append([]ScenarioFXRateObservation(nil), config.ReportingFXRates...),
		reportingSourceFingerprint: config.ReportingSourceFingerprint,
	}
}

func (s *ScenarioStore) Close() {
	if s != nil && s.pool != nil {
		s.pool.Close()
	}
}

func (s *ScenarioStore) currentAuthority(
	ctx context.Context,
	querier interface {
		Query(context.Context, string, ...any) (pgx.Rows, error)
	},
) (ScenarioContextBootstrap, error) {
	rows, err := querier.Query(
		ctx,
		`
		SELECT forecast_version_id, scenario_context_version,
		       scenario_decision_as_of
		FROM retail_serving.active_forecast_scenario_contexts
		WHERE retailer_id = $1 AND tenant_id = $2
		  AND capability = 'forecast_scenario_v1' AND environment = $3
		ORDER BY scenario_context_version
		LIMIT 2
		`,
		s.retailerID,
		s.tenantID,
		s.environment,
	)
	if err != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"The active scenario base context could not be read.",
			nil,
		)
	}
	defer rows.Close()
	type baseRow struct {
		forecast string
		context  string
		decision time.Time
	}
	bases := make([]baseRow, 0, 2)
	for rows.Next() {
		var row baseRow
		if scanErr := rows.Scan(&row.forecast, &row.context, &row.decision); scanErr != nil {
			return ScenarioContextBootstrap{}, scenarioUnavailable(
				ScenarioReasonReadUnavailable,
				"The active scenario base context is invalid.",
				nil,
			)
		}
		bases = append(bases, row)
	}
	if rows.Err() != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"The active scenario base context could not be read.",
			nil,
		)
	}
	if len(bases) == 0 {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonBaseMissing,
			"No approved Forecast Scenario Planning base context is active.",
			nil,
		)
	}
	if len(bases) > 1 {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonBaseAmbiguous,
			"More than one Forecast Scenario Planning base context is active.",
			nil,
		)
	}
	base := bases[0]
	extensionRows, err := querier.Query(
		ctx,
		`
		SELECT inventory_version_id, inventory_extension_version
		FROM retail_serving.active_forecast_scenario_inventory_extensions
		WHERE scenario_context_version = $1
		ORDER BY inventory_extension_version
		LIMIT 2
		`,
		base.context,
	)
	if err != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"The scenario inventory extension could not be read.",
			&base.context,
		)
	}
	defer extensionRows.Close()
	extensions := make([]ScenarioInventoryAuthority, 0, 2)
	for extensionRows.Next() {
		var extension ScenarioInventoryAuthority
		if scanErr := extensionRows.Scan(
			&extension.InventoryVersion,
			&extension.InventoryExtensionVersion,
		); scanErr != nil {
			return ScenarioContextBootstrap{}, scenarioUnavailable(
				ScenarioReasonReadUnavailable,
				"The scenario inventory extension is invalid.",
				&base.context,
			)
		}
		extensions = append(extensions, extension)
	}
	if extensionRows.Err() != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"The scenario inventory extension could not be read.",
			&base.context,
		)
	}
	if len(extensions) > 1 {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonInventoryAmbiguous,
			"More than one compatible scenario inventory extension is active.",
			&base.context,
		)
	}
	var inventory *ScenarioInventoryAuthority
	if len(extensions) == 1 {
		inventory = &extensions[0]
	}
	return ScenarioContextBootstrap{
		SchemaVersion:          ScenarioContextBootstrapSchema,
		ForecastVersion:        base.forecast,
		ScenarioContextVersion: base.context,
		Inventory:              inventory,
		ScenarioDecisionAsOf:   base.decision,
	}, nil
}

func (s *ScenarioStore) Bootstrap(
	ctx context.Context,
	expectedForecastVersion string,
) (ScenarioContextBootstrap, error) {
	if s == nil || s.loadError != nil || s.pool == nil {
		if s != nil && s.loadError != nil {
			return ScenarioContextBootstrap{}, s.loadError
		}
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning authority is not configured.",
			nil,
		)
	}
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{
		IsoLevel:   pgx.RepeatableRead,
		AccessMode: pgx.ReadOnly,
	})
	if err != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning authority could not be opened.",
			nil,
		)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	current, err := s.currentAuthority(ctx, tx)
	if err != nil {
		return ScenarioContextBootstrap{}, err
	}
	if current.ForecastVersion != expectedForecastVersion {
		expected := ScenarioAuthorityTuple{ForecastVersion: expectedForecastVersion}
		currentTuple := current.Authority()
		return ScenarioContextBootstrap{}, scenarioStale(
			ScenarioReasonForecastStale,
			"The expected forecast version is no longer the scenario authority.",
			&expected,
			&currentTuple,
		)
	}
	if commitErr := tx.Commit(ctx); commitErr != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning authority could not be confirmed.",
			nil,
		)
	}
	return current, nil
}

func ValidScenarioForecastVersion(value string) bool {
	return scenarioForecastVersionPattern.MatchString(value)
}

func scenarioInventoryEqual(
	left *ScenarioInventoryAuthority,
	right *ScenarioInventoryAuthority,
) bool {
	if left == nil || right == nil {
		return left == nil && right == nil
	}
	return *left == *right
}

func ScenarioAuthorityEqual(left, right ScenarioAuthorityTuple) bool {
	return left.ForecastVersion == right.ForecastVersion &&
		left.ScenarioContextVersion == right.ScenarioContextVersion &&
		scenarioInventoryEqual(left.Inventory, right.Inventory)
}
