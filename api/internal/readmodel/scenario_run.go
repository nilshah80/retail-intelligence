package readmodel

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

const ScenarioAssumptionResponseSchema = "retail-forecast-scenario-assumption/v1"

var scenarioFingerprintPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)
var scenarioInventoryVersionPattern = regexp.MustCompile(`^iv_[0-9a-f]{16}$`)

type ScenarioRunRequest struct {
	PresetID          string
	UserOverrides     map[string]string
	Scope             ScenarioBusinessScope
	ExpectedAuthority ScenarioAuthorityTuple
}

type ScenarioResolvedVector struct {
	DemandAdjustmentPct    float64 `json:"demandAdjustmentPct"`
	PriceChangePct         float64 `json:"priceChangePct"`
	PromotionUpliftPct     float64 `json:"promotionUpliftPct"`
	CompetitorAvailability string  `json:"competitorAvailability"`
	WeatherEvent           string  `json:"weatherEvent"`
	ATPAdjustment          float64 `json:"atpAdjustment"`
}

type ScenarioFactorBasis struct {
	ValueSource            string  `json:"valueSource"`
	CoefficientSource      string  `json:"coefficientSource"`
	CoefficientFingerprint *string `json:"coefficientFingerprint,omitempty"`
	ReasonCode             *string `json:"reasonCode,omitempty"`
}

type ScenarioRunResponse struct {
	SchemaVersion                 string                         `json:"schemaVersion"`
	DataMode                      string                         `json:"dataMode"`
	Authority                     ScenarioAuthorityTuple         `json:"authority"`
	ScenarioDecisionAsOf          time.Time                      `json:"scenarioDecisionAsOf"`
	AssumptionSetID               string                         `json:"assumptionSetId"`
	AssumptionVersion             string                         `json:"assumptionVersion"`
	AssumptionSemanticFingerprint string                         `json:"assumptionSemanticFingerprint"`
	AssumptionApprovalEventID     int64                          `json:"assumptionApprovalEventId"`
	AssumptionApprovalFingerprint string                         `json:"assumptionApprovalSemanticFingerprint"`
	PresetID                      string                         `json:"presetId"`
	ResolvedVector                ScenarioResolvedVector         `json:"resolvedVector"`
	FactorBasis                   map[string]ScenarioFactorBasis `json:"factorBasis"`
	ProjectionBasis               string                         `json:"projectionBasis"`
	EvidenceClass                 string                         `json:"evidenceClass"`
	StatisticalGateStatus         string                         `json:"statisticalGateStatus"`
	Disclosure                    string                         `json:"disclosure"`
	PriceSnapshotFingerprint      string                         `json:"priceSnapshotContentFingerprint"`
	PriceProvenance               []ScenarioPriceProvenance      `json:"priceProvenance"`
	Calculation                   ScenarioCalculation            `json:"calculation"`
}

type ScenarioPriceProvenance struct {
	SeriesKey                     ScenarioSeriesKey `json:"seriesKey"`
	DeptID                        string            `json:"deptId"`
	CurrencyCode                  string            `json:"currencyCode"`
	PriceAvailable                bool              `json:"priceAvailable"`
	UnitPriceMinor                *int64            `json:"unitPriceMinor"`
	PriceBasis                    *string           `json:"priceBasis"`
	PriceUnavailableReason        *string           `json:"priceUnavailableReason"`
	SourceRowIdentity             *string           `json:"sourceRowIdentity"`
	SourceRowVersion              *string           `json:"sourceRowVersion"`
	SourceObservationDate         *string           `json:"sourceObservationDate"`
	SourceKnownAsOf               *string           `json:"sourceKnownAsOf"`
	SourceRowContentFingerprint   *string           `json:"sourceRowContentFingerprint"`
	FallbackPopulationCount       *int              `json:"fallbackPopulationCount"`
	FallbackObservationStart      *string           `json:"fallbackObservationStart"`
	FallbackObservationEnd        *string           `json:"fallbackObservationEnd"`
	FallbackMaxKnownAsOf          *string           `json:"fallbackMaxKnownAsOf"`
	FallbackMemberSetFingerprint  *string           `json:"fallbackMemberSetContentFingerprint"`
	SourceCutoff                  string            `json:"sourceCutoff"`
	FreshnessStatus               string            `json:"freshnessStatus"`
	FreshnessReasonCode           *string           `json:"freshnessReasonCode"`
	ObservedSupportLowMinor       *int64            `json:"observedSupportLowMinor"`
	ObservedSupportHighMinor      *int64            `json:"observedSupportHighMinor"`
	ObservedSupportStart          *string           `json:"observedSupportStart"`
	ObservedSupportEnd            *string           `json:"observedSupportEnd"`
	ObservedSupportFingerprint    *string           `json:"observedSupportContentFingerprint"`
	BaselinePriceTier             *string           `json:"baselinePriceTier"`
	TierResolutionReason          *string           `json:"tierResolutionReason"`
	CoefficientContentFingerprint *string           `json:"coefficientContentFingerprint"`
}

type ScenarioValidationError struct {
	ReasonCode string
	Message    string
}

func (e *ScenarioValidationError) Error() string { return e.Message }

func scenarioValidation(reason, message string) error {
	return &ScenarioValidationError{ReasonCode: reason, Message: message}
}

func ScenarioValidationPayload(err error) map[string]any {
	var validation *ScenarioValidationError
	if errors.As(err, &validation) {
		return map[string]any{
			"schemaVersion": "retail-scenario-validation-error/v1",
			"reasonCode":    validation.ReasonCode,
			"message":       validation.Message,
		}
	}
	return map[string]any{
		"schemaVersion": "retail-scenario-validation-error/v1",
		"reasonCode":    "SCENARIO_REQUEST_INVALID",
		"message":       "The scenario request is invalid.",
	}
}

func ValidScenarioAuthorityTuple(tuple ScenarioAuthorityTuple) bool {
	if !ValidScenarioForecastVersion(tuple.ForecastVersion) ||
		!scenarioFingerprintPattern.MatchString(tuple.ScenarioContextVersion) {
		return false
	}
	if tuple.Inventory == nil {
		return true
	}
	return scenarioInventoryVersionPattern.MatchString(tuple.Inventory.InventoryVersion) &&
		scenarioFingerprintPattern.MatchString(tuple.Inventory.InventoryExtensionVersion)
}

func (s *ScenarioStore) CurrentAuthority(ctx context.Context) (ScenarioContextBootstrap, error) {
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
		IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly,
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
	if err := tx.Commit(ctx); err != nil {
		return ScenarioContextBootstrap{}, scenarioUnavailable(
			ScenarioReasonReadUnavailable,
			"Forecast Scenario Planning authority could not be confirmed.",
			nil,
		)
	}
	return current, nil
}

func validatePinnedAuthority(expected ScenarioAuthorityTuple, current ScenarioContextBootstrap) error {
	currentTuple := current.Authority()
	if ScenarioAuthorityEqual(expected, currentTuple) {
		return nil
	}
	return scenarioStale(
		ScenarioReasonContextStale,
		"The pinned scenario authority changed; bootstrap again before rerunning.",
		&expected,
		&currentTuple,
	)
}

type scenarioPreset struct {
	demand, price, promotion string
	competitor, weather, atp string
}

type scenarioContextMetadata struct {
	decisionAsOf             time.Time
	assumptionSetID          string
	assumptionVersion        string
	assumptionFingerprint    string
	approvalEventID          int64
	approvalFingerprint      string
	requestBounds            []byte
	disclosure               string
	priceSnapshotFingerprint string
}

type decimalBounds struct {
	Minimum string `json:"minimum"`
	Maximum string `json:"maximum"`
}

type scenarioRequestBounds struct {
	DemandAdjustmentPct    decimalBounds `json:"demandAdjustmentPct"`
	PriceChangePct         decimalBounds `json:"priceChangePct"`
	PromotionUpliftPct     decimalBounds `json:"promotionUpliftPct"`
	CompetitorAvailability []string      `json:"competitorAvailability"`
	WeatherEvent           []string      `json:"weatherEvent"`
}

func parseFinite(value string) (float64, error) {
	parsed, err := strconv.ParseFloat(value, 64)
	if err != nil || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
		return 0, scenarioValidation("SCENARIO_INPUT_NOT_FINITE", "Scenario numeric inputs must be finite.")
	}
	return parsed, nil
}

func allowedState(value string, allowed []string) bool {
	for _, candidate := range allowed {
		if value == candidate {
			return true
		}
	}
	return false
}

func resolveScenarioFactors(
	preset scenarioPreset,
	overrides map[string]string,
	boundsJSON []byte,
	assumptionFingerprint string,
) (ScenarioResolvedFactors, ScenarioResolvedVector, map[string]ScenarioFactorBasis, error) {
	var bounds scenarioRequestBounds
	if err := json.Unmarshal(boundsJSON, &bounds); err != nil {
		return ScenarioResolvedFactors{}, ScenarioResolvedVector{}, nil,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario request bounds are invalid.", nil)
	}
	values := map[string]string{
		"demandAdjustmentPct":    preset.demand,
		"priceChangePct":         preset.price,
		"promotionUpliftPct":     preset.promotion,
		"competitorAvailability": preset.competitor,
		"weatherEvent":           preset.weather,
	}
	for key, value := range overrides {
		values[key] = value
	}
	validateNumeric := func(field, value string, bounds decimalBounds) (float64, error) {
		parsed, err := parseFinite(value)
		if err != nil {
			return 0, err
		}
		minimum, err := strconv.ParseFloat(bounds.Minimum, 64)
		if err != nil {
			return 0, scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario request bounds are invalid.", nil)
		}
		maximum, err := strconv.ParseFloat(bounds.Maximum, 64)
		if err != nil {
			return 0, scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario request bounds are invalid.", nil)
		}
		if parsed < minimum || parsed > maximum {
			return 0, scenarioValidation(
				"SCENARIO_OVERRIDE_OUT_OF_BOUNDS",
				fmt.Sprintf("%s must be within [%s, %s] percentage points.", field, bounds.Minimum, bounds.Maximum),
			)
		}
		return parsed, nil
	}
	demand, err := validateNumeric("demandAdjustmentPct", values["demandAdjustmentPct"], bounds.DemandAdjustmentPct)
	if err != nil {
		return ScenarioResolvedFactors{}, ScenarioResolvedVector{}, nil, err
	}
	price, err := validateNumeric("priceChangePct", values["priceChangePct"], bounds.PriceChangePct)
	if err != nil {
		return ScenarioResolvedFactors{}, ScenarioResolvedVector{}, nil, err
	}
	promotion, err := validateNumeric("promotionUpliftPct", values["promotionUpliftPct"], bounds.PromotionUpliftPct)
	if err != nil {
		return ScenarioResolvedFactors{}, ScenarioResolvedVector{}, nil, err
	}
	atp, err := parseFinite(preset.atp)
	if err != nil || atp < -1 || atp > 0 {
		return ScenarioResolvedFactors{}, ScenarioResolvedVector{}, nil,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "The server-owned ATP assumption is invalid.", nil)
	}
	competitor := values["competitorAvailability"]
	weather := values["weatherEvent"]
	if !allowedState(competitor, bounds.CompetitorAvailability) || !allowedState(weather, bounds.WeatherEvent) {
		return ScenarioResolvedFactors{}, ScenarioResolvedVector{}, nil,
			scenarioValidation("SCENARIO_STATE_INVALID", "Competitor and weather values must use an approved state.")
	}
	resolved := ScenarioResolvedFactors{
		DemandAdjustmentPct:    demand,
		PriceChangePct:         price,
		PriceChangePctText:     values["priceChangePct"],
		PromotionUpliftPct:     promotion,
		CompetitorAvailability: competitor,
		WeatherEvent:           weather,
		ATPAdjustment:          atp,
	}
	vector := ScenarioResolvedVector{
		DemandAdjustmentPct: demand, PriceChangePct: price,
		PromotionUpliftPct: promotion, CompetitorAvailability: competitor,
		WeatherEvent: weather, ATPAdjustment: atp,
	}
	basis := make(map[string]ScenarioFactorBasis)
	valueSource := func(field string) string {
		if _, overridden := overrides[field]; overridden {
			return "user_override"
		}
		return "preset"
	}
	basis["demandAdjustment"] = ScenarioFactorBasis{ValueSource: valueSource("demandAdjustmentPct"), CoefficientSource: "not_applicable_direct_input"}
	basis["promotionUplift"] = ScenarioFactorBasis{ValueSource: valueSource("promotionUpliftPct"), CoefficientSource: "not_applicable_direct_input"}
	basis["atpAdjustment"] = ScenarioFactorBasis{ValueSource: "preset", CoefficientSource: "not_applicable_direct_input"}
	coefficientBasis := func(source string, used bool) ScenarioFactorBasis {
		if !used {
			return ScenarioFactorBasis{ValueSource: source, CoefficientSource: "not_used_neutral"}
		}
		fingerprint := assumptionFingerprint
		return ScenarioFactorBasis{ValueSource: source, CoefficientSource: "assumption_bundle", CoefficientFingerprint: &fingerprint}
	}
	basis["priceResponse"] = coefficientBasis(valueSource("priceChangePct"), price != 0)
	basis["competitorSensitivity"] = coefficientBasis(valueSource("competitorAvailability"), competitor != "normal")
	basis["weatherSensitivity"] = coefficientBasis(valueSource("weatherEvent"), weather != "normal")
	return resolved, vector, basis, nil
}

func targetNodeCTE() string {
	return `
		WITH context_authority AS (
			SELECT forecast_version_id
			FROM retail_serving.forecast_scenario_contexts
			WHERE scenario_context_version = $1
		),
		series_dimensions AS (
			SELECT dimensions.sku_id, dimensions.store_id,
			       dimensions.channel_id, dimensions.channel_type
			FROM retail_serving.forecast_series_dimensions AS dimensions
			JOIN context_authority
			  ON context_authority.forecast_version_id = dimensions.version_id
		),
		target_nodes AS (
			SELECT DISTINCT market_id, sku_id, store_id
			FROM retail_serving.forecast_scenario_horizon_rows AS rows
			JOIN series_dimensions AS dimensions
			  USING (sku_id, store_id, channel_id)
			WHERE rows.scenario_context_version = $1
			  AND ($2 = '' OR rows.market_id = $2)
			  AND ($3 = '' OR rows.store_id = $3)
			  AND ($4 = '' OR rows.channel_id = $4)
			  AND ($5 = '' OR rows.category = $5)
			  AND ($6 = '' OR dimensions.channel_type = $6)
		)
	`
}

func loadScenarioInputs(
	ctx context.Context,
	tx pgx.Tx,
	request ScenarioRunRequest,
) (ScenarioCalculationInput, ScenarioResolvedVector, map[string]ScenarioFactorBasis, scenarioContextMetadata, error) {
	var metadata scenarioContextMetadata
	err := tx.QueryRow(
		ctx,
		`
		SELECT contexts.scenario_decision_as_of, contexts.assumption_set_id,
		       contexts.assumption_version, contexts.assumption_semantic_fingerprint,
		       contexts.assumption_approval_event_id,
		       contexts.assumption_approval_semantic_fingerprint,
		       assumptions.request_bounds, assumptions.disclosure,
		       contexts.price_snapshot_content_fingerprint
		FROM retail_serving.forecast_scenario_contexts AS contexts
		JOIN retail_serving.forecast_scenario_assumption_sets AS assumptions
		  ON assumptions.assumption_set_id = contexts.assumption_set_id
		 AND assumptions.assumption_version = contexts.assumption_version
		 AND assumptions.semantic_fingerprint = contexts.assumption_semantic_fingerprint
		WHERE contexts.scenario_context_version = $1
		`,
		request.ExpectedAuthority.ScenarioContextVersion,
	).Scan(
		&metadata.decisionAsOf, &metadata.assumptionSetID, &metadata.assumptionVersion,
		&metadata.assumptionFingerprint, &metadata.approvalEventID,
		&metadata.approvalFingerprint, &metadata.requestBounds, &metadata.disclosure,
		&metadata.priceSnapshotFingerprint,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "The pinned scenario context could not be read.", nil)
	}
	var preset scenarioPreset
	err = tx.QueryRow(
		ctx,
		`
		SELECT demand_adjustment_pct::text, price_change_pct::text,
		       promotion_uplift_pct::text, competitor_availability,
		       weather_event, atp_adjustment::text
		FROM retail_serving.forecast_scenario_presets
		WHERE assumption_semantic_fingerprint = $1 AND preset_id = $2
		`,
		metadata.assumptionFingerprint,
		request.PresetID,
	).Scan(&preset.demand, &preset.price, &preset.promotion, &preset.competitor, &preset.weather, &preset.atp)
	if errors.Is(err, pgx.ErrNoRows) {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioValidation("SCENARIO_PRESET_UNKNOWN", "presetId does not name an approved server preset.")
	}
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "The approved scenario preset could not be read.", nil)
	}
	factors, vector, basis, err := resolveScenarioFactors(
		preset, request.UserOverrides, metadata.requestBounds, metadata.assumptionFingerprint,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata, err
	}
	parameters := []any{
		request.ExpectedAuthority.ScenarioContextVersion,
		request.Scope.MarketID, request.Scope.StoreID,
		request.Scope.ChannelID, request.Scope.Category, request.Scope.ChannelType,
	}
	horizonRows, err := tx.Query(
		ctx,
		targetNodeCTE()+`
		SELECT rows.market_id, rows.sku_id, rows.store_id, rows.channel_id,
		       rows.category, dimensions.channel_type,
		       rows.horizon_week, rows.expected_units,
		       rows.p50_units, rows.p90_units, rows.interval_available
		FROM retail_serving.forecast_scenario_horizon_rows AS rows
		JOIN target_nodes USING (market_id, sku_id, store_id)
		JOIN series_dimensions AS dimensions USING (sku_id, store_id, channel_id)
		WHERE rows.scenario_context_version = $1
		ORDER BY rows.market_id, rows.sku_id, rows.store_id,
		         rows.channel_id, rows.horizon_week
		`,
		parameters...,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario forecast facts could not be read.", nil)
	}
	horizons := make([]ScenarioHorizonFact, 0)
	for horizonRows.Next() {
		var row ScenarioHorizonFact
		if err := horizonRows.Scan(
			&row.Key.Market, &row.Key.SKU, &row.Key.Store, &row.Key.Channel,
			&row.Category, &row.ChannelType, &row.HorizonWeek, &row.ExpectedUnits,
			&row.P50Units, &row.P90Units, &row.IntervalAvailable,
		); err != nil {
			horizonRows.Close()
			return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
				scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario forecast facts are invalid.", nil)
		}
		horizons = append(horizons, row)
	}
	horizonErr := horizonRows.Err()
	horizonRows.Close()
	if horizonErr != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario forecast facts could not be read.", nil)
	}
	commercialRows, err := tx.Query(
		ctx,
		targetNodeCTE()+`
		SELECT rows.market_id, rows.sku_id, rows.store_id, rows.channel_id,
		       rows.dept_id, rows.currency_code, rows.price_available,
		       rows.unit_price_minor, rows.price_basis,
		       rows.price_unavailable_reason, rows.source_row_identity,
		       rows.source_row_version, rows.source_observation_date::text,
		       rows.source_known_as_of::text,
		       rows.source_row_content_fingerprint,
		       rows.fallback_population_count,
		       rows.fallback_observation_start::text,
		       rows.fallback_observation_end::text,
		       rows.fallback_max_known_as_of::text,
		       rows.fallback_member_set_content_fingerprint,
		       rows.source_cutoff::text, rows.freshness_status,
		       rows.freshness_reason_code, rows.observed_support_low_minor,
		       rows.observed_support_high_minor,
		       rows.observed_support_start::text,
		       rows.observed_support_end::text,
		       rows.observed_support_content_fingerprint,
		       rows.baseline_price_tier, rows.tier_resolution_reason,
		       rows.assumed_beta,
		       rows.competitor_stockout_sensitivity,
		       rows.competitor_promotion_sensitivity,
		       rows.weather_positive_sensitivity,
		       rows.weather_negative_sensitivity,
		       rows.coefficient_content_fingerprint
		FROM retail_serving.forecast_scenario_commercial_rows AS rows
		JOIN target_nodes USING (market_id, sku_id, store_id)
		WHERE rows.scenario_context_version = $1
		ORDER BY rows.market_id, rows.sku_id, rows.store_id, rows.channel_id
		`,
		parameters...,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario commercial facts could not be read.", nil)
	}
	commercial := make([]ScenarioCommercialFact, 0)
	for commercialRows.Next() {
		var row ScenarioCommercialFact
		if err := commercialRows.Scan(
			&row.Key.Market, &row.Key.SKU, &row.Key.Store, &row.Key.Channel,
			&row.DeptID, &row.CurrencyCode, &row.PriceAvailable,
			&row.UnitPriceMinor, &row.PriceBasis, &row.PriceUnavailableReason,
			&row.SourceRowIdentity, &row.SourceRowVersion,
			&row.SourceObservationDate, &row.SourceKnownAsOf,
			&row.SourceRowContentFingerprint, &row.FallbackPopulationCount,
			&row.FallbackObservationStart, &row.FallbackObservationEnd,
			&row.FallbackMaxKnownAsOf, &row.FallbackMemberSetFingerprint,
			&row.SourceCutoff, &row.FreshnessStatus, &row.FreshnessReasonCode,
			&row.ObservedSupportLowMinor, &row.ObservedSupportHighMinor,
			&row.ObservedSupportStart, &row.ObservedSupportEnd,
			&row.ObservedSupportFingerprint, &row.BaselinePriceTier,
			&row.TierResolutionReason, &row.AssumedBeta,
			&row.CompetitorStockoutSensitivity,
			&row.CompetitorPromotionSensitivity,
			&row.WeatherPositiveSensitivity, &row.WeatherNegativeSensitivity,
			&row.CoefficientContentFingerprint,
		); err != nil {
			commercialRows.Close()
			return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
				scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario commercial facts are invalid.", nil)
		}
		commercial = append(commercial, row)
	}
	commercialErr := commercialRows.Err()
	commercialRows.Close()
	if commercialErr != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario commercial facts could not be read.", nil)
	}
	ruleRows, err := tx.Query(
		ctx,
		`
		SELECT market_id, currency_code, minimum_price_minor,
		       maximum_price_minor, candidate_step_minor, grid_origin_minor
		FROM retail_serving.forecast_scenario_market_rules
		WHERE assumption_semantic_fingerprint = $1
		ORDER BY market_id
		`,
		metadata.assumptionFingerprint,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario price rules could not be read.", nil)
	}
	rules := make([]ScenarioPriceRule, 0)
	for ruleRows.Next() {
		var row ScenarioPriceRule
		if err := ruleRows.Scan(
			&row.MarketID, &row.CurrencyCode, &row.MinimumPriceMinor,
			&row.MaximumPriceMinor, &row.CandidateStepMinor, &row.GridOriginMinor,
		); err != nil {
			ruleRows.Close()
			return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
				scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario price rules are invalid.", nil)
		}
		rules = append(rules, row)
	}
	ruleErr := ruleRows.Err()
	ruleRows.Close()
	if ruleErr != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario price rules could not be read.", nil)
	}

	input := ScenarioCalculationInput{
		Scope: request.Scope, Factors: factors, Horizons: horizons,
		Commercial: commercial, PriceRules: rules,
	}
	if request.ExpectedAuthority.Inventory == nil {
		return input, vector, basis, metadata, nil
	}
	extension := request.ExpectedAuthority.Inventory.InventoryExtensionVersion
	inventorySeriesRows, err := tx.Query(
		ctx,
		targetNodeCTE()+`
		SELECT rows.market_id, rows.sku_id, rows.store_id, rows.channel_id,
		       rows.allocated_atp_units
		FROM retail_serving.forecast_scenario_inventory_series_rows AS rows
		JOIN target_nodes USING (market_id, sku_id, store_id)
		WHERE rows.inventory_extension_version = $7
		ORDER BY rows.market_id, rows.sku_id, rows.store_id, rows.channel_id
		`,
		append(parameters, extension)...,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario ATP facts could not be read.", nil)
	}
	for inventorySeriesRows.Next() {
		var row ScenarioInventorySeriesFact
		if err := inventorySeriesRows.Scan(
			&row.Key.Market, &row.Key.SKU, &row.Key.Store, &row.Key.Channel,
			&row.AllocatedATPUnits,
		); err != nil {
			inventorySeriesRows.Close()
			return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
				scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario ATP facts are invalid.", nil)
		}
		input.InventorySeries = append(input.InventorySeries, row)
	}
	inventorySeriesErr := inventorySeriesRows.Err()
	inventorySeriesRows.Close()
	if inventorySeriesErr != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario ATP facts could not be read.", nil)
	}
	nodeRows, err := tx.Query(
		ctx,
		targetNodeCTE()+`
		SELECT rows.market_id, rows.sku_id, rows.location_id,
		       rows.currency_code, rows.order_up_to_units,
		       rows.unit_cost_minor, rows.residual_atp_units,
		       rows.protection_available, rows.protection_days,
		       rows.review_period_days
		FROM retail_serving.forecast_scenario_inventory_node_rows AS rows
		JOIN target_nodes
		  ON target_nodes.market_id = rows.market_id
		 AND target_nodes.sku_id = rows.sku_id
		 AND target_nodes.store_id = rows.location_id
		WHERE rows.inventory_extension_version = $7
		ORDER BY rows.market_id, rows.sku_id, rows.location_id
		`,
		append(parameters, extension)...,
	)
	if err != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario inventory node facts could not be read.", nil)
	}
	for nodeRows.Next() {
		var row ScenarioInventoryNodeFact
		if err := nodeRows.Scan(
			&row.Key.Market, &row.Key.SKU, &row.Key.Location,
			&row.CurrencyCode, &row.OrderUpToUnits, &row.UnitCostMinor,
			&row.ResidualATPUnits, &row.ProtectionAvailable,
			&row.ProtectionDays, &row.ReviewPeriodDays,
		); err != nil {
			nodeRows.Close()
			return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
				scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario inventory node facts are invalid.", nil)
		}
		input.InventoryNodes = append(input.InventoryNodes, row)
	}
	nodeErr := nodeRows.Err()
	nodeRows.Close()
	if nodeErr != nil {
		return ScenarioCalculationInput{}, ScenarioResolvedVector{}, nil, metadata,
			scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario inventory node facts could not be read.", nil)
	}
	return input, vector, basis, metadata, nil
}

func scenarioPriceProvenance(input ScenarioCalculationInput) []ScenarioPriceProvenance {
	categories := make(map[ScenarioSeriesKey]string)
	channelTypes := make(map[ScenarioSeriesKey]string)
	for _, row := range input.Horizons {
		categories[row.Key] = row.Category
		channelTypes[row.Key] = row.ChannelType
	}
	result := make([]ScenarioPriceProvenance, 0, len(input.Commercial))
	for _, row := range input.Commercial {
		if !matchesScope(row.Key, categories[row.Key], channelTypes[row.Key], input.Scope) {
			continue
		}
		result = append(result, ScenarioPriceProvenance{
			SeriesKey:                     row.Key,
			DeptID:                        row.DeptID,
			CurrencyCode:                  row.CurrencyCode,
			PriceAvailable:                row.PriceAvailable,
			UnitPriceMinor:                row.UnitPriceMinor,
			PriceBasis:                    row.PriceBasis,
			PriceUnavailableReason:        row.PriceUnavailableReason,
			SourceRowIdentity:             row.SourceRowIdentity,
			SourceRowVersion:              row.SourceRowVersion,
			SourceObservationDate:         row.SourceObservationDate,
			SourceKnownAsOf:               row.SourceKnownAsOf,
			SourceRowContentFingerprint:   row.SourceRowContentFingerprint,
			FallbackPopulationCount:       row.FallbackPopulationCount,
			FallbackObservationStart:      row.FallbackObservationStart,
			FallbackObservationEnd:        row.FallbackObservationEnd,
			FallbackMaxKnownAsOf:          row.FallbackMaxKnownAsOf,
			FallbackMemberSetFingerprint:  row.FallbackMemberSetFingerprint,
			SourceCutoff:                  row.SourceCutoff,
			FreshnessStatus:               row.FreshnessStatus,
			FreshnessReasonCode:           row.FreshnessReasonCode,
			ObservedSupportLowMinor:       row.ObservedSupportLowMinor,
			ObservedSupportHighMinor:      row.ObservedSupportHighMinor,
			ObservedSupportStart:          row.ObservedSupportStart,
			ObservedSupportEnd:            row.ObservedSupportEnd,
			ObservedSupportFingerprint:    row.ObservedSupportFingerprint,
			BaselinePriceTier:             row.BaselinePriceTier,
			TierResolutionReason:          row.TierResolutionReason,
			CoefficientContentFingerprint: row.CoefficientContentFingerprint,
		})
	}
	sort.Slice(result, func(i, j int) bool {
		left, right := result[i].SeriesKey, result[j].SeriesKey
		return left.Market+"\x00"+left.SKU+"\x00"+left.Store+"\x00"+left.Channel <
			right.Market+"\x00"+right.SKU+"\x00"+right.Store+"\x00"+right.Channel
	})
	return result
}

func refineScenarioFactorBasis(
	input ScenarioCalculationInput,
	basis map[string]ScenarioFactorBasis,
) map[string]ScenarioFactorBasis {
	categories := make(map[ScenarioSeriesKey]string)
	channelTypes := make(map[ScenarioSeriesKey]string)
	for _, row := range input.Horizons {
		categories[row.Key] = row.Category
		channelTypes[row.Key] = row.ChannelType
	}
	rules := make(map[string]*ScenarioPriceRule)
	for index := range input.PriceRules {
		rule := &input.PriceRules[index]
		rules[rule.MarketID] = rule
	}
	setUnavailable := func(name, reason string) {
		entry := basis[name]
		entry.CoefficientSource = "unavailable"
		entry.CoefficientFingerprint = nil
		entry.ReasonCode = &reason
		basis[name] = entry
	}
	setPartial := func(name, reason string) {
		entry := basis[name]
		entry.ReasonCode = &reason
		basis[name] = entry
	}
	if input.Factors.PriceChangePct != 0 {
		used := false
		assessed := 0
		resolved := 0
		unavailableReason := ""
		priceOnly := input.Factors
		priceOnly.DemandAdjustmentPct = 0
		priceOnly.PromotionUpliftPct = 0
		priceOnly.CompetitorAvailability = "normal"
		priceOnly.WeatherEvent = "normal"
		for _, row := range input.Commercial {
			if !matchesScope(row.Key, categories[row.Key], channelTypes[row.Key], input.Scope) {
				continue
			}
			assessed++
			factor := calculateFactor(&row, rules[row.Key.Market], priceOnly)
			if len(factor.reasons) > 0 {
				unavailableReason = factor.reasons[0]
				continue
			}
			resolved++
			if factor.appliedPrice != nil && row.UnitPriceMinor != nil &&
				*factor.appliedPrice != *row.UnitPriceMinor {
				used = true
			}
		}
		if assessed == 0 || resolved == 0 {
			setUnavailable("priceResponse", "PRICE_UNAVAILABLE")
		} else if unavailableReason != "" {
			setPartial("priceResponse", "PRICE_RESPONSE_COEFFICIENT_PARTIAL")
		} else if !used {
			entry := basis["priceResponse"]
			entry.CoefficientSource = "not_used_neutral"
			entry.CoefficientFingerprint = nil
			basis["priceResponse"] = entry
		}
	}
	if input.Factors.CompetitorAvailability != "normal" {
		assessed := 0
		resolved := 0
		missing := false
		for _, row := range input.Commercial {
			if !matchesScope(row.Key, categories[row.Key], channelTypes[row.Key], input.Scope) {
				continue
			}
			assessed++
			coefficientMissing := input.Factors.CompetitorAvailability == "stockout" &&
				row.CompetitorStockoutSensitivity == nil
			coefficientMissing = coefficientMissing || input.Factors.CompetitorAvailability == "promotion" &&
				row.CompetitorPromotionSensitivity == nil
			if coefficientMissing {
				missing = true
				continue
			}
			resolved++
		}
		if assessed == 0 || resolved == 0 {
			setUnavailable("competitorSensitivity", "COMPETITOR_COEFFICIENT_UNAVAILABLE")
		} else if missing {
			setPartial("competitorSensitivity", "COMPETITOR_COEFFICIENT_PARTIAL")
		}
	}
	if input.Factors.WeatherEvent != "normal" {
		assessed := 0
		resolved := 0
		missing := false
		for _, row := range input.Commercial {
			if !matchesScope(row.Key, categories[row.Key], channelTypes[row.Key], input.Scope) {
				continue
			}
			assessed++
			coefficientMissing := input.Factors.WeatherEvent == "positive" &&
				row.WeatherPositiveSensitivity == nil
			coefficientMissing = coefficientMissing || input.Factors.WeatherEvent == "negative" &&
				row.WeatherNegativeSensitivity == nil
			if coefficientMissing {
				missing = true
				continue
			}
			resolved++
		}
		if assessed == 0 || resolved == 0 {
			setUnavailable("weatherSensitivity", "WEATHER_COEFFICIENT_UNAVAILABLE")
		} else if missing {
			setPartial("weatherSensitivity", "WEATHER_COEFFICIENT_PARTIAL")
		}
	}
	return basis
}

func (s *ScenarioStore) Run(
	ctx context.Context,
	request ScenarioRunRequest,
) (ScenarioRunResponse, error) {
	if !ValidScenarioAuthorityTuple(request.ExpectedAuthority) {
		return ScenarioRunResponse{}, scenarioValidation(
			"SCENARIO_AUTHORITY_TUPLE_INVALID",
			"expectedAuthority must contain a complete compatible tuple.",
		)
	}
	if request.PresetID == "" {
		return ScenarioRunResponse{}, scenarioValidation("SCENARIO_PRESET_REQUIRED", "presetId is required.")
	}
	if request.Scope.HorizonWeeks < 1 || request.Scope.HorizonWeeks > 26 {
		return ScenarioRunResponse{}, scenarioValidation("SCENARIO_HORIZON_INVALID", "horizonWeeks must be within 1..26.")
	}
	current, err := s.CurrentAuthority(ctx)
	if err != nil {
		return ScenarioRunResponse{}, err
	}
	if err := validatePinnedAuthority(request.ExpectedAuthority, current); err != nil {
		return ScenarioRunResponse{}, err
	}
	tx, err := s.pool.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.RepeatableRead, AccessMode: pgx.ReadOnly})
	if err != nil {
		return ScenarioRunResponse{}, scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario facts could not be opened.", nil)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	input, vector, basis, metadata, err := loadScenarioInputs(ctx, tx, request)
	if err != nil {
		return ScenarioRunResponse{}, err
	}
	input.ReportingFX = resolveScenarioReportingFX(
		s.reportingCurrency,
		s.reportingFXRates,
		s.reportingSourceFingerprint,
		metadata.decisionAsOf,
	)
	calculation := CalculateScenario(input)
	basis = refineScenarioFactorBasis(input, basis)
	if err := tx.Commit(ctx); err != nil {
		return ScenarioRunResponse{}, scenarioUnavailable(ScenarioReasonReadUnavailable, "Scenario facts could not be confirmed.", nil)
	}
	latest, err := s.CurrentAuthority(ctx)
	if err != nil {
		return ScenarioRunResponse{}, err
	}
	if err := validatePinnedAuthority(request.ExpectedAuthority, latest); err != nil {
		return ScenarioRunResponse{}, err
	}
	return ScenarioRunResponse{
		SchemaVersion:                 ScenarioAssumptionResponseSchema,
		DataMode:                      "assumption_projection",
		Authority:                     request.ExpectedAuthority,
		ScenarioDecisionAsOf:          metadata.decisionAsOf,
		AssumptionSetID:               metadata.assumptionSetID,
		AssumptionVersion:             metadata.assumptionVersion,
		AssumptionSemanticFingerprint: metadata.assumptionFingerprint,
		AssumptionApprovalEventID:     metadata.approvalEventID,
		AssumptionApprovalFingerprint: metadata.approvalFingerprint,
		PresetID:                      request.PresetID,
		ResolvedVector:                vector,
		FactorBasis:                   basis,
		ProjectionBasis:               "assumption_set",
		EvidenceClass:                 "synthetic_scenario",
		StatisticalGateStatus:         "not_applicable",
		Disclosure:                    metadata.disclosure,
		PriceSnapshotFingerprint:      metadata.priceSnapshotFingerprint,
		PriceProvenance:               scenarioPriceProvenance(input),
		Calculation:                   calculation,
	}, nil
}
