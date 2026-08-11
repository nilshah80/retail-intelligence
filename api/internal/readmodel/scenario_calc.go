package readmodel

import (
	"errors"
	"math"
	"math/big"
	"regexp"
	"sort"
	"strconv"
)

const scenarioZ90 = 1.2815515655446004

type ScenarioSeriesKey struct {
	Market  string `json:"marketId"`
	SKU     string `json:"skuId"`
	Store   string `json:"storeId"`
	Channel string `json:"channelId"`
}

type ScenarioNodeKey struct {
	Market   string `json:"marketId"`
	SKU      string `json:"skuId"`
	Location string `json:"locationId"`
}

type ScenarioHorizonFact struct {
	Key               ScenarioSeriesKey
	Category          string
	ChannelType       string
	HorizonWeek       int
	ExpectedUnits     float64
	P50Units          float64
	P90Units          *float64
	IntervalAvailable bool
}

type ScenarioCommercialFact struct {
	Key                            ScenarioSeriesKey
	DeptID                         string
	CurrencyCode                   string
	PriceAvailable                 bool
	UnitPriceMinor                 *int64
	PriceBasis                     *string
	PriceUnavailableReason         *string
	SourceRowIdentity              *string
	SourceRowVersion               *string
	SourceObservationDate          *string
	SourceKnownAsOf                *string
	SourceRowContentFingerprint    *string
	FallbackPopulationCount        *int
	FallbackObservationStart       *string
	FallbackObservationEnd         *string
	FallbackMaxKnownAsOf           *string
	FallbackMemberSetFingerprint   *string
	SourceCutoff                   string
	FreshnessStatus                string
	FreshnessReasonCode            *string
	ObservedSupportLowMinor        *int64
	ObservedSupportHighMinor       *int64
	ObservedSupportStart           *string
	ObservedSupportEnd             *string
	ObservedSupportFingerprint     *string
	BaselinePriceTier              *string
	TierResolutionReason           *string
	AssumedBeta                    *float64
	CompetitorStockoutSensitivity  *float64
	CompetitorPromotionSensitivity *float64
	WeatherPositiveSensitivity     *float64
	WeatherNegativeSensitivity     *float64
	CoefficientContentFingerprint  *string
}

type ScenarioPriceRule struct {
	MarketID           string
	CurrencyCode       string
	MinimumPriceMinor  int64
	MaximumPriceMinor  int64
	CandidateStepMinor int64
	GridOriginMinor    int64
}

type ScenarioInventorySeriesFact struct {
	Key               ScenarioSeriesKey
	AllocatedATPUnits float64
}

type ScenarioInventoryNodeFact struct {
	Key                 ScenarioNodeKey
	CurrencyCode        string
	OrderUpToUnits      *float64
	UnitCostMinor       *int64
	ResidualATPUnits    float64
	ProtectionAvailable bool
	ProtectionDays      *float64
	ReviewPeriodDays    int
}

type ScenarioBusinessScope struct {
	MarketID     string
	StoreID      string
	ChannelID    string
	ChannelType  string
	Category     string
	HorizonWeeks int
}

type ScenarioResolvedFactors struct {
	DemandAdjustmentPct    float64
	PriceChangePct         float64
	PriceChangePctText     string
	PromotionUpliftPct     float64
	CompetitorAvailability string
	WeatherEvent           string
	ATPAdjustment          float64
}

type ScenarioCalculationInput struct {
	Scope           ScenarioBusinessScope
	Factors         ScenarioResolvedFactors
	Horizons        []ScenarioHorizonFact
	Commercial      []ScenarioCommercialFact
	PriceRules      []ScenarioPriceRule
	InventorySeries []ScenarioInventorySeriesFact
	InventoryNodes  []ScenarioInventoryNodeFact
	ReportingFX     *ScenarioReportingFX
}

type ScenarioReportingFX struct {
	CurrencyCode              string
	RateMapContentFingerprint string
	Rates                     map[string]string
}

type ScenarioCoverage struct {
	Numerator   int      `json:"numerator"`
	Denominator int      `json:"denominator"`
	Grain       string   `json:"grain"`
	Pct         *float64 `json:"pct"`
}

type ScenarioFloatComponent struct {
	Availability string   `json:"availability"`
	Value        *float64 `json:"value"`
	ReasonCodes  []string `json:"reasonCodes"`
}

type ScenarioFloatMetric struct {
	Current      ScenarioFloatComponent `json:"current"`
	Scenario     ScenarioFloatComponent `json:"scenario"`
	Impact       ScenarioFloatComponent `json:"impact"`
	ImpactPct    *float64               `json:"impactPct,omitempty"`
	ImpactPoints *float64               `json:"impactPoints,omitempty"`
	Coverage     ScenarioCoverage       `json:"coverage"`
}

type ScenarioMoneyComponent struct {
	Availability string   `json:"availability"`
	ValueMinor   *int64   `json:"valueMinor"`
	ReasonCodes  []string `json:"reasonCodes"`
}

type ScenarioMoneyMetric struct {
	MarketID     string                 `json:"marketId"`
	CurrencyCode string                 `json:"currencyCode"`
	Current      ScenarioMoneyComponent `json:"current"`
	Scenario     ScenarioMoneyComponent `json:"scenario"`
	Impact       ScenarioMoneyComponent `json:"impact"`
	Coverage     ScenarioCoverage       `json:"coverage"`
}

type ScenarioReportingMoneyMetric struct {
	CurrencyCode              *string                `json:"currencyCode"`
	RateMapContentFingerprint *string                `json:"rateMapContentFingerprint"`
	Current                   ScenarioMoneyComponent `json:"current"`
	Scenario                  ScenarioMoneyComponent `json:"scenario"`
	Impact                    ScenarioMoneyComponent `json:"impact"`
	Coverage                  ScenarioCoverage       `json:"coverage"`
}

type ScenarioAppliedPrice struct {
	Key                   ScenarioSeriesKey `json:"seriesKey"`
	RequestedChangePct    float64           `json:"requestedPriceChangePct"`
	AppliedPriceMinor     *int64            `json:"appliedPriceMinor"`
	AppliedPriceChangePct *float64          `json:"appliedPriceChangePct"`
	Availability          string            `json:"availability"`
	ReasonCodes           []string          `json:"reasonCodes"`
}

type ScenarioAppliedPriceSummary struct {
	MarketID           string           `json:"marketId"`
	CurrencyCode       string           `json:"currencyCode"`
	Availability       string           `json:"availability"`
	RequestedChangePct float64          `json:"requestedPriceChangePct"`
	AppliedChangePct   *float64         `json:"baselineValueWeightedAppliedPriceChangePct"`
	ReasonCodes        []string         `json:"reasonCodes"`
	Coverage           ScenarioCoverage `json:"coverage"`
}

type ScenarioCalculation struct {
	DemandUnits             ScenarioFloatMetric           `json:"demandUnits"`
	RevenuePotential        []ScenarioMoneyMetric         `json:"revenuePotential"`
	ReportingRevenue        ScenarioReportingMoneyMetric  `json:"reportingRevenuePotential"`
	RequiredInventoryUnits  ScenarioFloatMetric           `json:"requiredInventoryUnits"`
	RequiredInventoryValue  []ScenarioMoneyMetric         `json:"requiredInventoryValue"`
	ReportingInventoryValue ScenarioReportingMoneyMetric  `json:"reportingRequiredInventoryValue"`
	StockoutRiskPct         ScenarioFloatMetric           `json:"demandWeightedSeriesStockoutRiskPct"`
	AppliedPrices           []ScenarioAppliedPrice        `json:"appliedPrices"`
	AppliedPriceSummaries   []ScenarioAppliedPriceSummary `json:"appliedPriceSummaries"`
}

type scenarioFactor struct {
	value          float64
	appliedPrice   *int64
	appliedPct     *float64
	reasons        []string
	appliedReasons []string
}

func uniqueReasons(values ...[]string) []string {
	set := make(map[string]struct{})
	for _, group := range values {
		for _, value := range group {
			if value != "" {
				set[value] = struct{}{}
			}
		}
	}
	result := make([]string, 0, len(set))
	for value := range set {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func coverage(numerator, denominator int, grain string) ScenarioCoverage {
	var pct *float64
	if denominator > 0 {
		value := 100 * float64(numerator) / float64(denominator)
		pct = &value
	}
	return ScenarioCoverage{Numerator: numerator, Denominator: denominator, Grain: grain, Pct: pct}
}

func availability(numerator, denominator int) string {
	if numerator == 0 {
		return "unavailable"
	}
	if numerator < denominator {
		return "partial"
	}
	return "available"
}

func floatMetric(current, scenario float64, numerator, denominator int, grain string, reasons []string, risk bool) ScenarioFloatMetric {
	if denominator == 0 {
		reasons = uniqueReasons(reasons, []string{"EMPTY_SCOPE"})
	}
	state := availability(numerator, denominator)
	if numerator == 0 {
		component := ScenarioFloatComponent{Availability: state, ReasonCodes: uniqueReasons(reasons)}
		return ScenarioFloatMetric{
			Current: component, Scenario: component, Impact: component,
			Coverage: coverage(numerator, denominator, grain),
		}
	}
	impact := scenario - current
	currentValue, scenarioValue, impactValue := current, scenario, impact
	result := ScenarioFloatMetric{
		Current:  ScenarioFloatComponent{Availability: state, Value: &currentValue, ReasonCodes: uniqueReasons(reasons)},
		Scenario: ScenarioFloatComponent{Availability: state, Value: &scenarioValue, ReasonCodes: uniqueReasons(reasons)},
		Impact:   ScenarioFloatComponent{Availability: state, Value: &impactValue, ReasonCodes: uniqueReasons(reasons)},
		Coverage: coverage(numerator, denominator, grain),
	}
	if risk {
		result.ImpactPoints = &impactValue
	} else if current == 0 {
		if scenario == 0 {
			zero := 0.0
			result.ImpactPct = &zero
			result.Impact.ReasonCodes = uniqueReasons(
				result.Impact.ReasonCodes, []string{"BOTH_ZERO"},
			)
		} else {
			result.Impact.ReasonCodes = uniqueReasons(
				result.Impact.ReasonCodes, []string{"ZERO_CURRENT"},
			)
		}
	} else {
		pct := 100 * impact / current
		if math.IsNaN(pct) || math.IsInf(pct, 0) {
			result.Impact.ReasonCodes = uniqueReasons(
				result.Impact.ReasonCodes, []string{"arithmetic_out_of_range"},
			)
		} else {
			result.ImpactPct = &pct
		}
	}
	return result
}

func roundRatHalfEven(value *big.Rat) *big.Int {
	sign := value.Sign()
	abs := new(big.Rat).Abs(value)
	numerator := new(big.Int).Set(abs.Num())
	denominator := new(big.Int).Set(abs.Denom())
	quotient, remainder := new(big.Int), new(big.Int)
	quotient.QuoRem(numerator, denominator, remainder)
	doubleRemainder := new(big.Int).Lsh(remainder, 1)
	comparison := doubleRemainder.Cmp(denominator)
	if comparison > 0 || (comparison == 0 && quotient.Bit(0) == 1) {
		quotient.Add(quotient, big.NewInt(1))
	}
	if sign < 0 {
		quotient.Neg(quotient)
	}
	return quotient
}

func gridRoundPrice(price int64, changePctText string, rule ScenarioPriceRule) (int64, error) {
	change, ok := new(big.Rat).SetString(changePctText)
	if !ok {
		return 0, errors.New("invalid_price_change")
	}
	if rule.CandidateStepMinor <= 0 {
		return 0, errors.New("invalid_price_grid")
	}
	ratio := new(big.Rat).Add(big.NewRat(1, 1), new(big.Rat).Quo(change, big.NewRat(100, 1)))
	raw := new(big.Rat).Mul(big.NewRat(price, 1), ratio)
	offset := new(big.Rat).Sub(raw, big.NewRat(rule.GridOriginMinor, 1))
	gridUnits := new(big.Rat).Quo(offset, big.NewRat(rule.CandidateStepMinor, 1))
	roundedUnits := roundRatHalfEven(gridUnits)
	result := new(big.Int).Mul(roundedUnits, big.NewInt(rule.CandidateStepMinor))
	result.Add(result, big.NewInt(rule.GridOriginMinor))
	if !result.IsInt64() {
		return 0, errors.New("arithmetic_out_of_range")
	}
	return result.Int64(), nil
}

func finitePositive(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && value > 0
}

func finiteNonNegative(value float64) bool {
	return !math.IsNaN(value) && !math.IsInf(value, 0) && value >= 0
}

func addFiniteNonNegative(left, right float64) (float64, bool) {
	if !finiteNonNegative(left) || !finiteNonNegative(right) {
		return 0, false
	}
	result := left + right
	return result, finiteNonNegative(result)
}

func scenarioPriceEvidenceReason(commercial *ScenarioCommercialFact) string {
	if commercial == nil {
		return "PRICE_UNAVAILABLE"
	}
	if commercial.PriceUnavailableReason != nil && *commercial.PriceUnavailableReason != "" {
		return *commercial.PriceUnavailableReason
	}
	if commercial.FreshnessReasonCode != nil && *commercial.FreshnessReasonCode != "" {
		return *commercial.FreshnessReasonCode
	}
	if commercial.FreshnessStatus == "stale" {
		return "PRICE_STALE"
	}
	if commercial.FreshnessStatus != "fresh" {
		return "PRICE_SUPPORT_UNAVAILABLE"
	}
	return "PRICE_UNAVAILABLE"
}

func calculateFactor(
	commercial *ScenarioCommercialFact,
	rule *ScenarioPriceRule,
	factors ScenarioResolvedFactors,
) scenarioFactor {
	demand := 1 + factors.DemandAdjustmentPct/100
	promotion := 1 + factors.PromotionUpliftPct/100
	if !finitePositive(demand) || !finitePositive(promotion) {
		return scenarioFactor{reasons: []string{"NON_POSITIVE_DIRECT_FACTOR"}}
	}
	priceFactor := 1.0
	var applied *int64
	var appliedPct *float64
	var appliedReasons []string
	if factors.PriceChangePct == 0 {
		if commercial != nil && commercial.PriceAvailable && commercial.UnitPriceMinor != nil &&
			*commercial.UnitPriceMinor > 0 && commercial.FreshnessStatus == "fresh" {
			value := *commercial.UnitPriceMinor
			zero := 0.0
			applied, appliedPct = &value, &zero
		} else if commercial != nil && commercial.FreshnessStatus != "fresh" {
			// A stale price does not block a semantically neutral demand factor,
			// but it is not valid applied-price or revenue evidence.
			appliedReasons = []string{scenarioPriceEvidenceReason(commercial)}
		} else {
			appliedReasons = []string{scenarioPriceEvidenceReason(commercial)}
		}
	} else {
		if commercial == nil || !commercial.PriceAvailable || commercial.UnitPriceMinor == nil || *commercial.UnitPriceMinor <= 0 {
			reason := scenarioPriceEvidenceReason(commercial)
			return scenarioFactor{reasons: []string{reason}, appliedReasons: []string{reason}}
		}
		if commercial.FreshnessStatus != "fresh" {
			reason := scenarioPriceEvidenceReason(commercial)
			return scenarioFactor{reasons: []string{reason}, appliedReasons: []string{reason}}
		}
		if rule == nil {
			return scenarioFactor{reasons: []string{"PRICE_RULE_UNAVAILABLE"}, appliedReasons: []string{"PRICE_RULE_UNAVAILABLE"}}
		}
		candidate, err := gridRoundPrice(*commercial.UnitPriceMinor, factors.PriceChangePctText, *rule)
		if err != nil {
			return scenarioFactor{reasons: []string{err.Error()}, appliedReasons: []string{err.Error()}}
		}
		applied = &candidate
		change := 100 * (float64(candidate)/float64(*commercial.UnitPriceMinor) - 1)
		appliedPct = &change
		if candidate != *commercial.UnitPriceMinor {
			if candidate <= 0 || candidate < rule.MinimumPriceMinor || candidate > rule.MaximumPriceMinor {
				return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"PRICE_MARKET_GUARDRAIL"}, appliedReasons: []string{"PRICE_MARKET_GUARDRAIL"}}
			}
			if commercial.ObservedSupportLowMinor == nil || commercial.ObservedSupportHighMinor == nil ||
				candidate < *commercial.ObservedSupportLowMinor || candidate > *commercial.ObservedSupportHighMinor {
				return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"PRICE_OBSERVED_SUPPORT"}, appliedReasons: []string{"PRICE_OBSERVED_SUPPORT"}}
			}
			if commercial.AssumedBeta == nil {
				return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"PRICE_TIER_UNRESOLVED"}, appliedReasons: []string{"PRICE_TIER_UNRESOLVED"}}
			}
			priceFactor = math.Pow(float64(candidate)/float64(*commercial.UnitPriceMinor), *commercial.AssumedBeta)
		}
	}
	competitor := 1.0
	switch factors.CompetitorAvailability {
	case "normal":
	case "stockout":
		if commercial == nil || commercial.CompetitorStockoutSensitivity == nil {
			return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"COMPETITOR_COEFFICIENT_UNAVAILABLE"}, appliedReasons: appliedReasons}
		}
		competitor += *commercial.CompetitorStockoutSensitivity
	case "promotion":
		if commercial == nil || commercial.CompetitorPromotionSensitivity == nil {
			return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"COMPETITOR_COEFFICIENT_UNAVAILABLE"}, appliedReasons: appliedReasons}
		}
		competitor -= *commercial.CompetitorPromotionSensitivity
	default:
		return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"COMPETITOR_STATE_INVALID"}, appliedReasons: appliedReasons}
	}
	weather := 1.0
	switch factors.WeatherEvent {
	case "normal":
	case "positive":
		if commercial == nil || commercial.WeatherPositiveSensitivity == nil {
			return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"WEATHER_COEFFICIENT_UNAVAILABLE"}, appliedReasons: appliedReasons}
		}
		weather += *commercial.WeatherPositiveSensitivity
	case "negative":
		if commercial == nil || commercial.WeatherNegativeSensitivity == nil {
			return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"WEATHER_COEFFICIENT_UNAVAILABLE"}, appliedReasons: appliedReasons}
		}
		weather -= *commercial.WeatherNegativeSensitivity
	default:
		return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"WEATHER_STATE_INVALID"}, appliedReasons: appliedReasons}
	}
	result := demand * promotion * priceFactor * competitor * weather
	if !finitePositive(result) {
		return scenarioFactor{appliedPrice: applied, appliedPct: appliedPct, reasons: []string{"NON_POSITIVE_SCENARIO_FACTOR"}, appliedReasons: appliedReasons}
	}
	return scenarioFactor{value: result, appliedPrice: applied, appliedPct: appliedPct, appliedReasons: appliedReasons}
}

func matchesScope(
	key ScenarioSeriesKey,
	category string,
	channelType string,
	scope ScenarioBusinessScope,
) bool {
	return (scope.MarketID == "" || scope.MarketID == key.Market) &&
		(scope.StoreID == "" || scope.StoreID == key.Store) &&
		(scope.ChannelID == "" || scope.ChannelID == key.Channel) &&
		(scope.ChannelType == "" || scope.ChannelType == channelType) &&
		(scope.Category == "" || scope.Category == category)
}

func completeWindow(rows map[int]ScenarioHorizonFact, weeks int) ([]ScenarioHorizonFact, bool) {
	if weeks < 1 {
		return nil, false
	}
	result := make([]ScenarioHorizonFact, 0, weeks)
	for horizon := 1; horizon <= weeks; horizon++ {
		row, ok := rows[horizon]
		if !ok {
			return nil, false
		}
		result = append(result, row)
	}
	return result, true
}

func roundHalfEvenInt64(value float64) (int64, bool) {
	if math.IsNaN(value) || math.IsInf(value, 0) ||
		value >= float64(math.MaxInt64) || value < float64(math.MinInt64) {
		return 0, false
	}
	return int64(math.RoundToEven(value)), true
}

func addInt64(left, right int64) (int64, bool) {
	if (right > 0 && left > math.MaxInt64-right) || (right < 0 && left < math.MinInt64-right) {
		return 0, false
	}
	return left + right, true
}

type moneyAccumulator struct {
	market, currency       string
	current, scenario      int64
	numerator, denominator int
	reasons                []string
	valid                  bool
}

type scenarioMoneyFact struct {
	current, scenario int64
	currency          string
}

var exactFXRatePattern = regexp.MustCompile(`^(?:0|[1-9][0-9]{0,19})(?:\.[0-9]{1,18})?$`)

var scenarioMinorExponent = map[string]int{
	"EUR": 2,
	"GBP": 2,
	"INR": 2,
	"USD": 2,
}

func convertScenarioMinor(
	amount int64,
	rateText string,
	baseCurrency string,
	quoteCurrency string,
) (int64, bool) {
	if !exactFXRatePattern.MatchString(rateText) {
		return 0, false
	}
	rate, ok := new(big.Rat).SetString(rateText)
	if !ok || rate.Sign() <= 0 {
		return 0, false
	}
	baseExponent, baseKnown := scenarioMinorExponent[baseCurrency]
	quoteExponent, quoteKnown := scenarioMinorExponent[quoteCurrency]
	if !baseKnown || !quoteKnown {
		return 0, false
	}
	if baseCurrency == quoteCurrency && rate.Cmp(big.NewRat(1, 1)) != 0 {
		return 0, false
	}
	value := new(big.Rat).Mul(big.NewRat(amount, 1), rate)
	shift := quoteExponent - baseExponent
	if shift != 0 {
		power := new(big.Int).Exp(big.NewInt(10), big.NewInt(int64(absInt(shift))), nil)
		if shift > 0 {
			value.Mul(value, new(big.Rat).SetInt(power))
		} else {
			value.Quo(value, new(big.Rat).SetInt(power))
		}
	}
	rounded := roundRatHalfEven(value)
	if !rounded.IsInt64() {
		return 0, false
	}
	return rounded.Int64(), true
}

func absInt(value int) int {
	if value < 0 {
		return -value
	}
	return value
}

func reportingMoneyMetric(
	facts []scenarioMoneyFact,
	denominator int,
	grain string,
	fx *ScenarioReportingFX,
) ScenarioReportingMoneyMetric {
	result := ScenarioReportingMoneyMetric{
		Coverage: coverage(0, denominator, grain),
	}
	unavailable := func(reason string, assessed int) ScenarioReportingMoneyMetric {
		result.Coverage = coverage(assessed, denominator, grain)
		component := ScenarioMoneyComponent{
			Availability: "unavailable", ReasonCodes: []string{reason},
		}
		result.Current, result.Scenario, result.Impact = component, component, component
		return result
	}
	if fx == nil || !scenarioCurrencyPattern.MatchString(fx.CurrencyCode) ||
		!scenarioFingerprintPattern.MatchString(fx.RateMapContentFingerprint) {
		return unavailable("REPORTING_FX_UNAVAILABLE", 0)
	}
	result.CurrencyCode = &fx.CurrencyCode
	result.RateMapContentFingerprint = &fx.RateMapContentFingerprint
	current, scenario, assessed := int64(0), int64(0), 0
	for _, fact := range facts {
		rate, exists := fx.Rates[fact.currency]
		if !exists {
			return unavailable("REPORTING_FX_RATE_MISSING", assessed)
		}
		convertedCurrent, currentOK := convertScenarioMinor(
			fact.current, rate, fact.currency, fx.CurrencyCode,
		)
		convertedScenario, scenarioOK := convertScenarioMinor(
			fact.scenario, rate, fact.currency, fx.CurrencyCode,
		)
		if !currentOK || !scenarioOK {
			return unavailable("REPORTING_FX_ARITHMETIC_INVALID", assessed)
		}
		newCurrent, currentSumOK := addInt64(current, convertedCurrent)
		newScenario, scenarioSumOK := addInt64(scenario, convertedScenario)
		if !currentSumOK || !scenarioSumOK {
			return unavailable("arithmetic_out_of_range", assessed)
		}
		current, scenario = newCurrent, newScenario
		assessed++
	}
	if assessed == 0 {
		reason := "NO_PAIRED_MONEY_FACTS"
		if denominator == 0 {
			reason = "EMPTY_SCOPE"
		}
		return unavailable(reason, 0)
	}
	impact, ok := addInt64(scenario, -current)
	if !ok {
		return unavailable("arithmetic_out_of_range", assessed)
	}
	state := availability(assessed, denominator)
	result.Coverage = coverage(assessed, denominator, grain)
	result.Current = ScenarioMoneyComponent{Availability: state, ValueMinor: &current, ReasonCodes: []string{}}
	result.Scenario = ScenarioMoneyComponent{Availability: state, ValueMinor: &scenario, ReasonCodes: []string{}}
	result.Impact = ScenarioMoneyComponent{Availability: state, ValueMinor: &impact, ReasonCodes: []string{}}
	return result
}

func moneyMetrics(accumulators map[string]*moneyAccumulator, grain string) []ScenarioMoneyMetric {
	keys := make([]string, 0, len(accumulators))
	for key := range accumulators {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	result := make([]ScenarioMoneyMetric, 0, len(keys))
	for _, key := range keys {
		acc := accumulators[key]
		state := availability(acc.numerator, acc.denominator)
		reasons := uniqueReasons(acc.reasons)
		metric := ScenarioMoneyMetric{
			MarketID: acc.market, CurrencyCode: acc.currency,
			Coverage: coverage(acc.numerator, acc.denominator, grain),
		}
		if acc.numerator == 0 || !acc.valid {
			component := ScenarioMoneyComponent{Availability: "unavailable", ReasonCodes: reasons}
			metric.Current, metric.Scenario, metric.Impact = component, component, component
		} else {
			impact, ok := addInt64(acc.scenario, -acc.current)
			if !ok {
				component := ScenarioMoneyComponent{Availability: "unavailable", ReasonCodes: uniqueReasons(reasons, []string{"arithmetic_out_of_range"})}
				metric.Current, metric.Scenario, metric.Impact = component, component, component
			} else {
				current, scenario := acc.current, acc.scenario
				metric.Current = ScenarioMoneyComponent{Availability: state, ValueMinor: &current, ReasonCodes: reasons}
				metric.Scenario = ScenarioMoneyComponent{Availability: state, ValueMinor: &scenario, ReasonCodes: reasons}
				metric.Impact = ScenarioMoneyComponent{Availability: state, ValueMinor: &impact, ReasonCodes: reasons}
			}
		}
		result = append(result, metric)
	}
	return result
}

func fractionalSum(values []float64, days float64) (float64, bool) {
	if math.IsNaN(days) || math.IsInf(days, 0) || days < 0 {
		return 0, false
	}
	if days == 0 {
		return 0, true
	}
	required := int(math.Ceil(days / 7))
	if len(values) < required {
		return 0, false
	}
	remaining := days / 7
	total := 0.0
	for _, value := range values {
		if remaining <= 0 {
			break
		}
		if !finiteNonNegative(value) {
			return 0, false
		}
		weight := math.Min(1, remaining)
		total += value * weight
		remaining -= weight
	}
	return total, !math.IsNaN(total) && !math.IsInf(total, 0)
}

func fractionalRSS(values []float64, days float64) (float64, bool) {
	if math.IsNaN(days) || math.IsInf(days, 0) || days < 0 {
		return 0, false
	}
	if days == 0 {
		return 0, true
	}
	required := int(math.Ceil(days / 7))
	if len(values) < required {
		return 0, false
	}
	remaining, squared := days/7, 0.0
	for _, value := range values {
		if remaining <= 0 {
			break
		}
		if value < 0 || math.IsNaN(value) || math.IsInf(value, 0) {
			return 0, false
		}
		weight := math.Min(1, remaining)
		squared += (value * weight) * (value * weight)
		remaining -= weight
	}
	result := math.Sqrt(squared)
	return result, !math.IsNaN(result) && !math.IsInf(result, 0)
}

func stockoutRisk(mu, sigma, atp float64) (float64, bool) {
	if !finiteNonNegative(mu) || !finiteNonNegative(atp) {
		return 0, false
	}
	if mu == 0 {
		return 0, true
	}
	if sigma < 0 || math.IsNaN(sigma) || math.IsInf(sigma, 0) {
		return 0, false
	}
	if sigma == 0 {
		if mu > atp {
			return 1, true
		}
		return 0, true
	}
	z := (atp - mu) / sigma
	risk := 1 - 0.5*(1+math.Erf(z/math.Sqrt2))
	if risk < 0 && risk > -1e-15 {
		risk = 0
	}
	if risk > 1 && risk < 1+1e-15 {
		risk = 1
	}
	return risk, risk >= 0 && risk <= 1 && !math.IsNaN(risk)
}

type scenarioRiskPair struct {
	mu0, mu1, risk0, risk1 float64
}

func scenarioRiskMetric(
	pairs []scenarioRiskPair,
	denominator int,
	reasons []string,
) ScenarioFloatMetric {
	numerator := 0
	baseReasons := uniqueReasons(reasons)
	result := ScenarioFloatMetric{}
	if denominator == 0 {
		empty := ScenarioFloatComponent{
			Availability: "unavailable", ReasonCodes: []string{"EMPTY_SCOPE"},
		}
		result.Current, result.Scenario, result.Impact = empty, empty, empty
		result.Coverage = coverage(0, 0, "series_key")
		return result
	}
	currentNumerator, scenarioNumerator := 0.0, 0.0
	currentWeight, scenarioWeight := 0.0, 0.0
	for _, pair := range pairs {
		if !finiteNonNegative(pair.mu0) || !finiteNonNegative(pair.mu1) ||
			!finiteNonNegative(pair.risk0) || !finiteNonNegative(pair.risk1) {
			baseReasons = uniqueReasons(baseReasons, []string{"arithmetic_out_of_range"})
			continue
		}
		nextCurrentNumerator, nextScenarioNumerator := currentNumerator, scenarioNumerator
		nextCurrentWeight, nextScenarioWeight := currentWeight, scenarioWeight
		valid := true
		if pair.mu0 > 0 {
			contribution := pair.mu0 * pair.risk0
			nextCurrentNumerator, valid = addFiniteNonNegative(currentNumerator, contribution)
			if valid {
				nextCurrentWeight, valid = addFiniteNonNegative(currentWeight, pair.mu0)
			}
		}
		if valid && pair.mu1 > 0 {
			contribution := pair.mu1 * pair.risk1
			nextScenarioNumerator, valid = addFiniteNonNegative(scenarioNumerator, contribution)
			if valid {
				nextScenarioWeight, valid = addFiniteNonNegative(scenarioWeight, pair.mu1)
			}
		}
		if !valid {
			baseReasons = uniqueReasons(baseReasons, []string{"arithmetic_out_of_range"})
			continue
		}
		currentNumerator, scenarioNumerator = nextCurrentNumerator, nextScenarioNumerator
		currentWeight, scenarioWeight = nextCurrentWeight, nextScenarioWeight
		numerator++
	}
	pairedState := availability(numerator, denominator)
	result.Coverage = coverage(numerator, denominator, "series_key")
	if currentWeight > 0 {
		value := 100 * currentNumerator / currentWeight
		result.Current = ScenarioFloatComponent{
			Availability: pairedState, Value: &value, ReasonCodes: baseReasons,
		}
	} else {
		result.Current = ScenarioFloatComponent{
			Availability: "unavailable",
			ReasonCodes:  uniqueReasons(baseReasons, []string{"ZERO_DEMAND_CURRENT"}),
		}
	}
	if scenarioWeight > 0 {
		value := 100 * scenarioNumerator / scenarioWeight
		result.Scenario = ScenarioFloatComponent{
			Availability: pairedState, Value: &value, ReasonCodes: baseReasons,
		}
	} else {
		result.Scenario = ScenarioFloatComponent{
			Availability: "unavailable",
			ReasonCodes:  uniqueReasons(baseReasons, []string{"ZERO_DEMAND_SCENARIO"}),
		}
	}
	if result.Current.Value == nil || result.Scenario.Value == nil {
		result.Impact = ScenarioFloatComponent{
			Availability: "unavailable",
			ReasonCodes:  uniqueReasons(result.Current.ReasonCodes, result.Scenario.ReasonCodes),
		}
		return result
	}
	impact := *result.Scenario.Value - *result.Current.Value
	result.Impact = ScenarioFloatComponent{
		Availability: pairedState, Value: &impact, ReasonCodes: baseReasons,
	}
	result.ImpactPoints = &impact
	return result
}

func CalculateScenario(input ScenarioCalculationInput) ScenarioCalculation {
	horizons := make(map[ScenarioSeriesKey]map[int]ScenarioHorizonFact)
	seriesByNode := make(map[ScenarioNodeKey][]ScenarioSeriesKey)
	categories := make(map[ScenarioSeriesKey]string)
	channelTypes := make(map[ScenarioSeriesKey]string)
	for _, row := range input.Horizons {
		if _, ok := horizons[row.Key]; !ok {
			horizons[row.Key] = make(map[int]ScenarioHorizonFact)
			nodeKey := ScenarioNodeKey{
				Market: row.Key.Market, SKU: row.Key.SKU, Location: row.Key.Store,
			}
			seriesByNode[nodeKey] = append(seriesByNode[nodeKey], row.Key)
		}
		horizons[row.Key][row.HorizonWeek] = row
		categories[row.Key] = row.Category
		channelTypes[row.Key] = row.ChannelType
	}
	for nodeKey := range seriesByNode {
		keys := seriesByNode[nodeKey]
		sort.Slice(keys, func(i, j int) bool {
			return keys[i].Channel < keys[j].Channel
		})
		seriesByNode[nodeKey] = keys
	}
	commercial := make(map[ScenarioSeriesKey]*ScenarioCommercialFact)
	for index := range input.Commercial {
		row := &input.Commercial[index]
		commercial[row.Key] = row
	}
	rules := make(map[string]*ScenarioPriceRule)
	for index := range input.PriceRules {
		rule := &input.PriceRules[index]
		rules[rule.MarketID] = rule
	}
	factors := make(map[ScenarioSeriesKey]scenarioFactor)
	applied := make([]ScenarioAppliedPrice, 0)
	inScope := make([]ScenarioSeriesKey, 0)
	for key := range horizons {
		if !matchesScope(key, categories[key], channelTypes[key], input.Scope) {
			continue
		}
		inScope = append(inScope, key)
		factor := calculateFactor(commercial[key], rules[key.Market], input.Factors)
		factors[key] = factor
		state := "available"
		if len(factor.appliedReasons) > 0 || factor.appliedPrice == nil {
			state = "unavailable"
		}
		applied = append(applied, ScenarioAppliedPrice{
			Key: key, RequestedChangePct: input.Factors.PriceChangePct,
			AppliedPriceMinor: factor.appliedPrice, AppliedPriceChangePct: factor.appliedPct,
			Availability: state, ReasonCodes: uniqueReasons(factor.appliedReasons),
		})
	}
	sort.Slice(inScope, func(i, j int) bool {
		left, right := inScope[i], inScope[j]
		return left.Market+"\x00"+left.SKU+"\x00"+left.Store+"\x00"+left.Channel <
			right.Market+"\x00"+right.SKU+"\x00"+right.Store+"\x00"+right.Channel
	})
	sort.Slice(applied, func(i, j int) bool {
		left, right := applied[i].Key, applied[j].Key
		return left.Market+"\x00"+left.SKU+"\x00"+left.Store+"\x00"+left.Channel <
			right.Market+"\x00"+right.SKU+"\x00"+right.Store+"\x00"+right.Channel
	})

	demandCurrent, demandScenario, demandNumerator := 0.0, 0.0, 0
	demandReasons := make([]string, 0)
	revenue := make(map[string]*moneyAccumulator)
	revenueFacts := make([]scenarioMoneyFact, 0)
	type priceSummaryAccumulator struct {
		market, currency       string
		baselineValue          float64
		appliedValue           float64
		numerator, denominator int
		reasons                []string
	}
	priceSummaries := make(map[string]*priceSummaryAccumulator)
	for _, key := range inScope {
		rows, complete := completeWindow(horizons[key], input.Scope.HorizonWeeks)
		factor := factors[key]
		commercialRow := commercial[key]
		currency := "unavailable"
		if commercialRow != nil && commercialRow.CurrencyCode != "" {
			currency = commercialRow.CurrencyCode
		} else if rules[key.Market] != nil {
			currency = rules[key.Market].CurrencyCode
		}
		localMoneyKey := key.Market + "\x1f" + currency
		acc := revenue[localMoneyKey]
		if acc == nil {
			acc = &moneyAccumulator{market: key.Market, currency: currency, valid: true}
			revenue[localMoneyKey] = acc
		}
		// The canonical revenue denominator is the requested number of weekly
		// money facts for every in-scope SeriesKey, before evidence exclusions.
		acc.denominator += input.Scope.HorizonWeeks
		summaryKey := key.Market + "\x1f" + currency
		priceAcc := priceSummaries[summaryKey]
		if priceAcc == nil {
			priceAcc = &priceSummaryAccumulator{
				market: key.Market, currency: currency,
			}
			priceSummaries[summaryKey] = priceAcc
		}
		priceAcc.denominator++
		if !complete || len(factor.reasons) > 0 {
			if !complete {
				demandReasons = append(demandReasons, "INCOMPLETE_REQUESTED_HORIZON")
				acc.reasons = append(acc.reasons, "INCOMPLETE_REQUESTED_HORIZON")
			} else {
				demandReasons = append(demandReasons, factor.reasons...)
				acc.reasons = append(acc.reasons, factor.reasons...)
			}
		} else {
			seriesCurrent, seriesScenario := 0.0, 0.0
			seriesValid := true
			for _, row := range rows {
				var ok bool
				seriesCurrent, ok = addFiniteNonNegative(seriesCurrent, row.ExpectedUnits)
				if !ok {
					seriesValid = false
					break
				}
				seriesScenario, ok = addFiniteNonNegative(
					seriesScenario, row.ExpectedUnits*factor.value,
				)
				if !ok {
					seriesValid = false
					break
				}
			}
			if seriesValid {
				nextCurrent, currentOK := addFiniteNonNegative(demandCurrent, seriesCurrent)
				nextScenario, scenarioOK := addFiniteNonNegative(demandScenario, seriesScenario)
				if currentOK && scenarioOK {
					demandCurrent, demandScenario = nextCurrent, nextScenario
					demandNumerator++
				} else {
					seriesValid = false
				}
			}
			if !seriesValid {
				demandReasons = append(demandReasons, "arithmetic_out_of_range")
			}
		}
		priceAssessed := complete && commercialRow != nil &&
			commercialRow.UnitPriceMinor != nil && factor.appliedPrice != nil &&
			len(factor.appliedReasons) == 0 && commercialRow.FreshnessStatus == "fresh"
		if priceAssessed {
			q0 := 0.0
			priceValid := true
			for _, row := range rows {
				var ok bool
				q0, ok = addFiniteNonNegative(q0, row.ExpectedUnits)
				if !ok {
					priceValid = false
					break
				}
			}
			baselineValue := q0 * float64(*commercialRow.UnitPriceMinor)
			appliedValue := q0 * float64(*factor.appliedPrice)
			nextBaseline, baselineOK := addFiniteNonNegative(priceAcc.baselineValue, baselineValue)
			nextApplied, appliedOK := addFiniteNonNegative(priceAcc.appliedValue, appliedValue)
			if !priceValid || !baselineOK || !appliedOK {
				priceAcc.reasons = append(priceAcc.reasons, "arithmetic_out_of_range")
			} else {
				priceAcc.baselineValue = nextBaseline
				priceAcc.appliedValue = nextApplied
				priceAcc.numerator++
			}
		} else if !complete {
			priceAcc.reasons = append(priceAcc.reasons, "INCOMPLETE_REQUESTED_HORIZON")
		} else if commercialRow == nil || commercialRow.UnitPriceMinor == nil {
			priceAcc.reasons = append(priceAcc.reasons, "PRICE_UNAVAILABLE")
		} else {
			priceAcc.reasons = append(priceAcc.reasons, factor.appliedReasons...)
		}

		if !complete || len(factor.reasons) > 0 || commercialRow == nil ||
			commercialRow.UnitPriceMinor == nil || factor.appliedPrice == nil ||
			len(factor.appliedReasons) > 0 || commercialRow.FreshnessStatus != "fresh" {
			if commercialRow == nil || commercialRow.UnitPriceMinor == nil {
				acc.reasons = append(acc.reasons, "PRICE_UNAVAILABLE")
			} else if len(factor.appliedReasons) > 0 {
				acc.reasons = append(acc.reasons, factor.appliedReasons...)
			}
			continue
		}
		for _, row := range rows {
			currentFact, okCurrent := roundHalfEvenInt64(row.ExpectedUnits * float64(*commercialRow.UnitPriceMinor))
			scenarioFact, okScenario := roundHalfEvenInt64(row.ExpectedUnits * factor.value * float64(*factor.appliedPrice))
			if !okCurrent || !okScenario {
				acc.reasons = append(acc.reasons, "arithmetic_out_of_range")
				continue
			}
			revenueFacts = append(revenueFacts, scenarioMoneyFact{
				current: currentFact, scenario: scenarioFact, currency: currency,
			})
			currentTotal, currentOK := addInt64(acc.current, currentFact)
			scenarioTotal, scenarioOK := addInt64(acc.scenario, scenarioFact)
			if !currentOK || !scenarioOK {
				acc.valid = false
				acc.reasons = append(acc.reasons, "arithmetic_out_of_range")
				continue
			}
			acc.current = currentTotal
			acc.scenario = scenarioTotal
			acc.numerator++
		}
	}
	priceSummaryKeys := make([]string, 0, len(priceSummaries))
	for key := range priceSummaries {
		priceSummaryKeys = append(priceSummaryKeys, key)
	}
	sort.Strings(priceSummaryKeys)
	appliedPriceSummaries := make([]ScenarioAppliedPriceSummary, 0, len(priceSummaryKeys))
	for _, key := range priceSummaryKeys {
		acc := priceSummaries[key]
		state := availability(acc.numerator, acc.denominator)
		var value *float64
		reasons := uniqueReasons(acc.reasons)
		if acc.numerator > 0 && acc.baselineValue > 0 {
			change := 100 * (acc.appliedValue/acc.baselineValue - 1)
			if math.IsNaN(change) || math.IsInf(change, 0) {
				state = "unavailable"
				reasons = uniqueReasons(reasons, []string{"arithmetic_out_of_range"})
			} else {
				value = &change
			}
		} else {
			state = "unavailable"
			reasons = uniqueReasons(reasons, []string{"ZERO_BASELINE_PRICE_VALUE"})
		}
		appliedPriceSummaries = append(appliedPriceSummaries, ScenarioAppliedPriceSummary{
			MarketID: acc.market, CurrencyCode: acc.currency,
			Availability: state, RequestedChangePct: input.Factors.PriceChangePct,
			AppliedChangePct: value, ReasonCodes: reasons,
			Coverage: coverage(acc.numerator, acc.denominator, "series_key"),
		})
	}

	nodes := make(map[ScenarioNodeKey]ScenarioInventoryNodeFact)
	for _, node := range input.InventoryNodes {
		nodes[node.Key] = node
	}
	allocations := make(map[ScenarioSeriesKey]float64)
	for _, row := range input.InventorySeries {
		allocations[row.Key] = row.AllocatedATPUnits
	}
	inScopeNodes := make(map[ScenarioNodeKey]struct{})
	for _, key := range inScope {
		inScopeNodes[ScenarioNodeKey{Market: key.Market, SKU: key.SKU, Location: key.Store}] = struct{}{}
	}
	requiredCurrent, requiredScenario, requiredNumerator := 0.0, 0.0, 0
	requiredReasons := make([]string, 0)
	inventoryValue := make(map[string]*moneyAccumulator)
	inventoryValueFacts := make([]scenarioMoneyFact, 0)
	for nodeKey := range inScopeNodes {
		node, ok := nodes[nodeKey]
		currency := "unavailable"
		if ok && node.CurrencyCode != "" {
			currency = node.CurrencyCode
		} else if rules[nodeKey.Market] != nil {
			currency = rules[nodeKey.Market].CurrencyCode
		}
		localMoneyKey := nodeKey.Market + "\x1f" + currency
		valueAcc := inventoryValue[localMoneyKey]
		if valueAcc == nil {
			valueAcc = &moneyAccumulator{market: nodeKey.Market, currency: currency, valid: true}
			inventoryValue[localMoneyKey] = valueAcc
		}
		valueAcc.denominator++
		if !ok || node.OrderUpToUnits == nil || !node.ProtectionAvailable || node.ProtectionDays == nil {
			requiredReasons = append(requiredReasons, "ORDER_UP_TO_WINDOW_UNAVAILABLE")
			valueAcc.reasons = append(valueAcc.reasons, "ORDER_UP_TO_WINDOW_UNAVAILABLE")
			continue
		}
		// The materialized protection period already contains lead time plus the
		// governed review period. Adding review again would double-count it.
		windowDays := *node.ProtectionDays
		weeks := int(math.Ceil(windowDays / 7))
		baseline, scenarioDemand := 0.0, 0.0
		valid := true
		for _, seriesKey := range seriesByNode[nodeKey] {
			seriesRows := horizons[seriesKey]
			window, complete := completeWindow(seriesRows, weeks)
			if !complete {
				valid = false
				break
			}
			values := make([]float64, len(window))
			for i, row := range window {
				values[i] = row.ExpectedUnits
			}
			mu, ok := fractionalSum(values, windowDays)
			if !ok {
				valid = false
				break
			}
			seriesFactor := 1.0
			if matchesScope(
				seriesKey, categories[seriesKey], channelTypes[seriesKey], input.Scope,
			) {
				factor := factors[seriesKey]
				if len(factor.reasons) > 0 {
					valid = false
					break
				}
				seriesFactor = factor.value
			}
			baseline += mu
			scenarioDemand += mu * seriesFactor
		}
		if !valid || baseline <= 0 {
			reason := "INCOMPLETE_ORDER_UP_TO_WINDOW"
			if valid && baseline == 0 {
				reason = "ZERO_BASELINE_DEMAND"
			}
			requiredReasons = append(requiredReasons, reason)
			valueAcc.reasons = append(valueAcc.reasons, reason)
			continue
		}
		factorBar := scenarioDemand / baseline
		currentValue := *node.OrderUpToUnits
		scenarioValue := currentValue * factorBar
		if !finitePositive(factorBar) || math.IsNaN(scenarioValue) || math.IsInf(scenarioValue, 0) {
			requiredReasons = append(requiredReasons, "arithmetic_out_of_range")
			valueAcc.reasons = append(valueAcc.reasons, "arithmetic_out_of_range")
			continue
		}
		nextRequiredCurrent, currentUnitsOK := addFiniteNonNegative(requiredCurrent, currentValue)
		nextRequiredScenario, scenarioUnitsOK := addFiniteNonNegative(requiredScenario, scenarioValue)
		if currentUnitsOK && scenarioUnitsOK {
			requiredCurrent, requiredScenario = nextRequiredCurrent, nextRequiredScenario
			requiredNumerator++
		} else {
			requiredReasons = append(requiredReasons, "arithmetic_out_of_range")
		}
		if node.UnitCostMinor == nil {
			valueAcc.reasons = append(valueAcc.reasons, "UNIT_COST_UNAVAILABLE")
			continue
		}
		currentMoney, okCurrent := roundHalfEvenInt64(currentValue * float64(*node.UnitCostMinor))
		scenarioMoney, okScenario := roundHalfEvenInt64(scenarioValue * float64(*node.UnitCostMinor))
		if !okCurrent || !okScenario {
			valueAcc.reasons = append(valueAcc.reasons, "arithmetic_out_of_range")
			continue
		}
		inventoryValueFacts = append(inventoryValueFacts, scenarioMoneyFact{
			current: currentMoney, scenario: scenarioMoney, currency: currency,
		})
		currentTotal, currentOK := addInt64(valueAcc.current, currentMoney)
		scenarioTotal, scenarioOK := addInt64(valueAcc.scenario, scenarioMoney)
		if !currentOK || !scenarioOK {
			valueAcc.valid = false
			valueAcc.reasons = append(valueAcc.reasons, "arithmetic_out_of_range")
			continue
		}
		valueAcc.current = currentTotal
		valueAcc.scenario = scenarioTotal
		valueAcc.numerator++
	}

	// Risk is evaluated node-by-node so one residual balance is allocated once
	// across all sibling channels in each state.
	riskPairs := make([]scenarioRiskPair, 0)
	riskReasons := make([]string, 0)
	for nodeKey := range inScopeNodes {
		node, ok := nodes[nodeKey]
		if !ok || !node.ProtectionAvailable || node.ProtectionDays == nil {
			riskReasons = append(riskReasons, "ATP_OR_PROTECTION_UNAVAILABLE")
			continue
		}
		if !finiteNonNegative(node.ResidualATPUnits) ||
			!finitePositive(*node.ProtectionDays) {
			riskReasons = append(riskReasons, "ATP_OR_PROTECTION_INVALID")
			continue
		}
		weeks := int(math.Ceil(*node.ProtectionDays / 7))
		type seriesRiskInput struct {
			key                      ScenarioSeriesKey
			mu0, mu1, sigma0, sigma1 float64
			inScope                  bool
		}
		seriesInputs := make([]seriesRiskInput, 0)
		totalMu0, totalMu1 := 0.0, 0.0
		residualAllocationValid := true
		allocationEvidenceValid := true
		for _, seriesKey := range seriesByNode[nodeKey] {
			seriesRows := horizons[seriesKey]
			allocatedATP, allocationPresent := allocations[seriesKey]
			if !allocationPresent || !finiteNonNegative(allocatedATP) {
				riskReasons = append(riskReasons, "ATP_ALLOCATION_UNAVAILABLE")
				allocationEvidenceValid = false
				continue
			}
			window, complete := completeWindow(seriesRows, weeks)
			if !complete {
				riskReasons = append(riskReasons, "RISK_WINDOW_UNAVAILABLE")
				if node.ResidualATPUnits > 0 {
					residualAllocationValid = false
				}
				continue
			}
			expected, spreads := make([]float64, len(window)), make([]float64, len(window))
			intervalAvailable := true
			for i, row := range window {
				expected[i] = row.ExpectedUnits
				if !row.IntervalAvailable || row.P90Units == nil || *row.P90Units < row.P50Units {
					intervalAvailable = false
					continue
				}
				spreads[i] = *row.P90Units - row.P50Units
			}
			factorValue := 1.0
			isInScope := matchesScope(
				seriesKey, categories[seriesKey], channelTypes[seriesKey], input.Scope,
			)
			if isInScope {
				factor := factors[seriesKey]
				if len(factor.reasons) > 0 {
					riskReasons = append(riskReasons, factor.reasons...)
					if node.ResidualATPUnits > 0 {
						residualAllocationValid = false
					}
					continue
				}
				factorValue = factor.value
			}
			mu0, ok0 := fractionalSum(expected, *node.ProtectionDays)
			if !ok0 {
				riskReasons = append(riskReasons, "RISK_WINDOW_UNAVAILABLE")
				if node.ResidualATPUnits > 0 {
					residualAllocationValid = false
				}
				continue
			}
			mu1 := mu0 * factorValue
			totalMu0 += mu0
			totalMu1 += mu1
			if !intervalAvailable {
				if isInScope {
					riskReasons = append(riskReasons, "INTERVAL_UNAVAILABLE")
				}
				continue
			}
			spread0, okSpread := fractionalRSS(spreads, *node.ProtectionDays)
			if !okSpread {
				if isInScope {
					riskReasons = append(riskReasons, "INTERVAL_INVALID")
				}
				continue
			}
			sigma0 := spread0 / scenarioZ90
			sigma1 := sigma0 * factorValue
			seriesInputs = append(seriesInputs, seriesRiskInput{seriesKey, mu0, mu1, sigma0, sigma1, isInScope})
		}
		if !allocationEvidenceValid {
			continue
		}
		if node.ResidualATPUnits > 0 && !residualAllocationValid {
			riskReasons = append(riskReasons, "RESIDUAL_ALLOCATION_UNAVAILABLE")
			continue
		}
		for _, series := range seriesInputs {
			if !series.inScope {
				continue
			}
			atp0, atp1 := allocations[series.key], allocations[series.key]
			if node.ResidualATPUnits > 0 {
				if totalMu0 > 0 {
					atp0 += node.ResidualATPUnits * series.mu0 / totalMu0
				}
				if totalMu1 > 0 {
					atp1 += node.ResidualATPUnits * series.mu1 / totalMu1
				}
			}
			atp1 = math.Max(0, atp1*(1+input.Factors.ATPAdjustment))
			risk0, ok0 := stockoutRisk(series.mu0, series.sigma0, atp0)
			risk1, ok1 := stockoutRisk(series.mu1, series.sigma1, atp1)
			if !ok0 || !ok1 {
				riskReasons = append(riskReasons, "RISK_ARITHMETIC_INVALID")
				continue
			}
			riskPairs = append(riskPairs, scenarioRiskPair{series.mu0, series.mu1, risk0, risk1})
		}
	}
	riskMetric := scenarioRiskMetric(riskPairs, len(inScope), riskReasons)

	return ScenarioCalculation{
		DemandUnits:             floatMetric(demandCurrent, demandScenario, demandNumerator, len(inScope), "series_key", demandReasons, false),
		RevenuePotential:        moneyMetrics(revenue, "sku_store_channel_horizon_week"),
		ReportingRevenue:        reportingMoneyMetric(revenueFacts, len(inScope)*input.Scope.HorizonWeeks, "sku_store_channel_horizon_week", input.ReportingFX),
		RequiredInventoryUnits:  floatMetric(requiredCurrent, requiredScenario, requiredNumerator, len(inScopeNodes), "sku_location", requiredReasons, false),
		RequiredInventoryValue:  moneyMetrics(inventoryValue, "sku_location_money_fact"),
		ReportingInventoryValue: reportingMoneyMetric(inventoryValueFacts, len(inScopeNodes), "sku_location_money_fact", input.ReportingFX),
		StockoutRiskPct:         riskMetric,
		AppliedPrices:           applied,
		AppliedPriceSummaries:   appliedPriceSummaries,
	}
}

func ScenarioResolvedFactorsFromStrings(
	demand, price, promotion, competitor, weather, atp string,
) (ScenarioResolvedFactors, error) {
	parse := func(value string) (float64, error) {
		parsed, err := strconv.ParseFloat(value, 64)
		if err != nil || math.IsNaN(parsed) || math.IsInf(parsed, 0) {
			return 0, errors.New("non-finite scenario factor")
		}
		return parsed, nil
	}
	demandValue, err := parse(demand)
	if err != nil {
		return ScenarioResolvedFactors{}, err
	}
	priceValue, err := parse(price)
	if err != nil {
		return ScenarioResolvedFactors{}, err
	}
	promotionValue, err := parse(promotion)
	if err != nil {
		return ScenarioResolvedFactors{}, err
	}
	atpValue, err := parse(atp)
	if err != nil {
		return ScenarioResolvedFactors{}, err
	}
	return ScenarioResolvedFactors{
		DemandAdjustmentPct: demandValue, PriceChangePct: priceValue,
		PriceChangePctText: price, PromotionUpliftPct: promotionValue,
		CompetitorAvailability: competitor, WeatherEvent: weather,
		ATPAdjustment: atpValue,
	}, nil
}
