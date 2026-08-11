package readmodel

import (
	"encoding/json"
	"math"
	"strings"
	"testing"
	"time"
)

func floatPointer(value float64) *float64 { return &value }
func intPointer(value int64) *int64       { return &value }

func scenarioCalcFixture() ScenarioCalculationInput {
	key := ScenarioSeriesKey{Market: "m1", SKU: "sku1", Store: "s1", Channel: "store"}
	node := ScenarioNodeKey{Market: "m1", SKU: "sku1", Location: "s1"}
	beta := -1.0
	sensitivity := 0.1
	return ScenarioCalculationInput{
		Scope: ScenarioBusinessScope{MarketID: "m1", HorizonWeeks: 2},
		Factors: ScenarioResolvedFactors{
			PriceChangePctText: "0", CompetitorAvailability: "normal",
			WeatherEvent: "normal",
		},
		Horizons: []ScenarioHorizonFact{
			{Key: key, Category: "cat", ChannelType: "store", HorizonWeek: 1, ExpectedUnits: 10, P50Units: 8, P90Units: floatPointer(12), IntervalAvailable: true},
			{Key: key, Category: "cat", ChannelType: "store", HorizonWeek: 2, ExpectedUnits: 20, P50Units: 16, P90Units: floatPointer(24), IntervalAvailable: true},
			{Key: key, Category: "cat", ChannelType: "store", HorizonWeek: 3, ExpectedUnits: 30, P50Units: 24, P90Units: floatPointer(36), IntervalAvailable: true},
		},
		Commercial: []ScenarioCommercialFact{{
			Key: key, CurrencyCode: "USD", PriceAvailable: true,
			UnitPriceMinor: intPointer(100), FreshnessStatus: "fresh",
			ObservedSupportLowMinor: intPointer(90), ObservedSupportHighMinor: intPointer(110),
			AssumedBeta: &beta, CompetitorStockoutSensitivity: &sensitivity,
			CompetitorPromotionSensitivity: &sensitivity,
			WeatherPositiveSensitivity:     &sensitivity, WeatherNegativeSensitivity: &sensitivity,
		}},
		PriceRules: []ScenarioPriceRule{{
			MarketID: "m1", CurrencyCode: "USD", MinimumPriceMinor: 1,
			MaximumPriceMinor: 1000, CandidateStepMinor: 1,
		}},
		InventorySeries: []ScenarioInventorySeriesFact{{Key: key, AllocatedATPUnits: 5}},
		InventoryNodes: []ScenarioInventoryNodeFact{{
			Key: node, CurrencyCode: "USD", OrderUpToUnits: floatPointer(40),
			UnitCostMinor: intPointer(50), ResidualATPUnits: 5,
			ProtectionAvailable: true, ProtectionDays: floatPointer(14), ReviewPeriodDays: 7,
		}},
	}
}

func TestScenarioScopeMatchesChannelTypeSeparatelyFromChannelID(t *testing.T) {
	key := ScenarioSeriesKey{Market: "m1", SKU: "sku1", Store: "s1", Channel: "native-marketplace"}
	scope := ScenarioBusinessScope{ChannelType: "marketplace"}
	if !matchesScope(key, "cat", "marketplace", scope) {
		t.Fatal("matching channel type was rejected")
	}
	if matchesScope(key, "cat", "store", scope) {
		t.Fatal("channel type filter was compared to the native channel id or ignored")
	}
}

func TestPartialCoefficientLineageRetainsTheBundleFingerprint(t *testing.T) {
	fingerprint := strings.Repeat("a", 64)
	second := ScenarioSeriesKey{Market: "m1", SKU: "sku2", Store: "s1", Channel: "store"}
	base := scenarioCalcFixture()
	base.Horizons = append(base.Horizons,
		ScenarioHorizonFact{Key: second, Category: "cat", ChannelType: "store", HorizonWeek: 1, ExpectedUnits: 5, P50Units: 4, P90Units: floatPointer(6), IntervalAvailable: true},
		ScenarioHorizonFact{Key: second, Category: "cat", ChannelType: "store", HorizonWeek: 2, ExpectedUnits: 5, P50Units: 4, P90Units: floatPointer(6), IntervalAvailable: true},
	)
	secondCommercial := base.Commercial[0]
	secondCommercial.Key = second
	base.Commercial = append(base.Commercial, secondCommercial)

	for _, test := range []struct {
		name      string
		basisKey  string
		partial   string
		configure func(*ScenarioCalculationInput)
	}{
		{
			name: "price response", basisKey: "priceResponse",
			partial: "PRICE_RESPONSE_COEFFICIENT_PARTIAL",
			configure: func(input *ScenarioCalculationInput) {
				input.Factors.PriceChangePct = 5
				input.Factors.PriceChangePctText = "5"
				input.Commercial[1].AssumedBeta = nil
			},
		},
		{
			name: "competitor", basisKey: "competitorSensitivity",
			partial: "COMPETITOR_COEFFICIENT_PARTIAL",
			configure: func(input *ScenarioCalculationInput) {
				input.Factors.CompetitorAvailability = "stockout"
				input.Commercial[1].CompetitorStockoutSensitivity = nil
			},
		},
		{
			name: "weather", basisKey: "weatherSensitivity",
			partial: "WEATHER_COEFFICIENT_PARTIAL",
			configure: func(input *ScenarioCalculationInput) {
				input.Factors.WeatherEvent = "positive"
				input.Commercial[1].WeatherPositiveSensitivity = nil
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			input := base
			input.Horizons = append([]ScenarioHorizonFact(nil), base.Horizons...)
			input.Commercial = append([]ScenarioCommercialFact(nil), base.Commercial...)
			test.configure(&input)
			basis := map[string]ScenarioFactorBasis{
				test.basisKey: {
					ValueSource: "preset", CoefficientSource: "assumption_bundle",
					CoefficientFingerprint: &fingerprint,
				},
			}
			refined := refineScenarioFactorBasis(input, basis)[test.basisKey]
			if refined.CoefficientSource != "assumption_bundle" ||
				refined.CoefficientFingerprint == nil ||
				*refined.CoefficientFingerprint != fingerprint {
				t.Fatalf("served coefficient lineage was erased: %#v", refined)
			}
			if refined.ReasonCode == nil || *refined.ReasonCode != test.partial {
				t.Fatalf("partial coefficient coverage was not disclosed: %#v", refined)
			}
		})
	}
}

func TestScenarioNeutralVectorIsAnExactNoOp(t *testing.T) {
	result := CalculateScenario(scenarioCalcFixture())
	for name, metric := range map[string]ScenarioFloatMetric{
		"demand":            result.DemandUnits,
		"requiredInventory": result.RequiredInventoryUnits,
		"risk":              result.StockoutRiskPct,
	} {
		if metric.Current.Value == nil || metric.Scenario.Value == nil || *metric.Current.Value != *metric.Scenario.Value {
			t.Fatalf("%s neutral current/scenario differ: %#v", name, metric)
		}
		if metric.Impact.Value == nil || *metric.Impact.Value != 0 {
			t.Fatalf("%s neutral impact is not zero: %#v", name, metric)
		}
	}
	if result.AppliedPrices[0].AppliedPriceMinor == nil || *result.AppliedPrices[0].AppliedPriceMinor != 100 {
		t.Fatalf("neutral price moved: %#v", result.AppliedPrices[0])
	}
	if len(result.RevenuePotential) != 1 || *result.RevenuePotential[0].Impact.ValueMinor != 0 {
		t.Fatalf("neutral revenue changed: %#v", result.RevenuePotential)
	}
}

func TestGridRoundUsesHalfEvenAndNeutralBypassesGrid(t *testing.T) {
	rule := ScenarioPriceRule{CandidateStepMinor: 10}
	price, err := gridRoundPrice(105, "0", rule)
	if err != nil || price != 100 { // 10.5 grid units ties to even 10.
		t.Fatalf("half-even grid result = %d, %v", price, err)
	}
	fixture := scenarioCalcFixture()
	fixture.Commercial[0].UnitPriceMinor = intPointer(105)
	result := CalculateScenario(fixture)
	if got := *result.AppliedPrices[0].AppliedPriceMinor; got != 105 {
		t.Fatalf("neutral request must bypass gridRound, got %d", got)
	}
}

func TestDemandUsesExpectedUnitsAndPriceResponseUsesAppliedPrice(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.Factors.PriceChangePct = 5
	fixture.Factors.PriceChangePctText = "5"
	fixture.Commercial[0].ObservedSupportHighMinor = intPointer(110)
	result := CalculateScenario(fixture)
	if result.DemandUnits.Current.Value == nil || *result.DemandUnits.Current.Value != 30 {
		t.Fatalf("demand current did not sum expected_units: %#v", result.DemandUnits)
	}
	if result.DemandUnits.Scenario.Value == nil || math.Abs(*result.DemandUnits.Scenario.Value-30.0/1.05) > 1e-9 {
		t.Fatalf("price factor did not use applied price: %#v", result.DemandUnits)
	}
}

func TestPerSeriesPriceGuardrailProducesPartialNotClamp(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.Factors.PriceChangePct = 5
	fixture.Factors.PriceChangePctText = "5"
	fixture.Commercial[0].ObservedSupportHighMinor = intPointer(102)
	result := CalculateScenario(fixture)
	if result.DemandUnits.Scenario.Value != nil || result.DemandUnits.Coverage.Numerator != 0 {
		t.Fatalf("guardrail failure was not unavailable: %#v", result.DemandUnits)
	}
	price := result.AppliedPrices[0]
	if price.AppliedPriceMinor == nil || *price.AppliedPriceMinor != 105 {
		t.Fatalf("rejected candidate was clamped or hidden: %#v", price)
	}
}

func TestNeutralMissingPriceKeepsDemandButWithholdsPriceAndRevenue(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.Commercial[0].PriceAvailable = false
	fixture.Commercial[0].UnitPriceMinor = nil
	fixture.Commercial[0].FreshnessStatus = "unavailable"
	fixture.Factors.DemandAdjustmentPct = 10
	result := CalculateScenario(fixture)
	if result.DemandUnits.Scenario.Value == nil || math.Abs(*result.DemandUnits.Scenario.Value-33) > 1e-9 {
		t.Fatalf("neutral missing price blocked direct demand: %#v", result.DemandUnits)
	}
	if result.AppliedPrices[0].Availability != "unavailable" ||
		len(result.AppliedPrices[0].ReasonCodes) == 0 {
		t.Fatalf("missing price was presented as assessed: %#v", result.AppliedPrices[0])
	}
	if len(result.RevenuePotential) != 1 || result.RevenuePotential[0].Scenario.ValueMinor != nil {
		t.Fatalf("revenue used missing price evidence: %#v", result.RevenuePotential)
	}
}

func TestPriceSupportReasonIsNotMisreportedAsStaleness(t *testing.T) {
	fixture := scenarioCalcFixture()
	reason := "PRICE_SUPPORT_UNAVAILABLE"
	fixture.Commercial[0].FreshnessStatus = "unavailable"
	fixture.Commercial[0].FreshnessReasonCode = &reason
	result := CalculateScenario(fixture)
	price := result.AppliedPrices[0]
	if len(price.ReasonCodes) != 1 || price.ReasonCodes[0] != reason {
		t.Fatalf("price support failure was mislabelled: %#v", price)
	}
	if result.DemandUnits.Scenario.Value == nil {
		t.Fatalf("a neutral price-evidence failure blocked demand: %#v", result.DemandUnits)
	}
}

func TestNonPriceCoefficientFailureDoesNotHideAppliedPrice(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.Factors.CompetitorAvailability = "stockout"
	fixture.Commercial[0].CompetitorStockoutSensitivity = nil
	result := CalculateScenario(fixture)
	if result.DemandUnits.Scenario.Value != nil {
		t.Fatalf("missing coefficient did not block demand: %#v", result.DemandUnits)
	}
	if result.AppliedPrices[0].Availability != "available" ||
		result.AppliedPrices[0].AppliedPriceMinor == nil {
		t.Fatalf("independent applied-price evidence was hidden: %#v", result.AppliedPrices[0])
	}
}

func TestRequiredInventoryUsesMaterializedProtectionWindowOnce(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.Scope.ChannelID = "store"
	fixture.Factors.DemandAdjustmentPct = 100
	sibling := ScenarioSeriesKey{Market: "m1", SKU: "sku1", Store: "s1", Channel: "web"}
	fixture.Horizons = append(fixture.Horizons,
		ScenarioHorizonFact{Key: sibling, Category: "cat", HorizonWeek: 1, ExpectedUnits: 0, P50Units: 0, P90Units: floatPointer(0), IntervalAvailable: true},
		ScenarioHorizonFact{Key: sibling, Category: "cat", HorizonWeek: 2, ExpectedUnits: 0, P50Units: 0, P90Units: floatPointer(0), IntervalAvailable: true},
		ScenarioHorizonFact{Key: sibling, Category: "cat", HorizonWeek: 3, ExpectedUnits: 100, P50Units: 100, P90Units: floatPointer(100), IntervalAvailable: true},
	)
	result := CalculateScenario(fixture)
	if result.RequiredInventoryUnits.Scenario.Value == nil ||
		*result.RequiredInventoryUnits.Scenario.Value != 80 {
		t.Fatalf("review period was double-counted: %#v", result.RequiredInventoryUnits)
	}
	if result.RequiredInventoryUnits.Coverage.Numerator != 1 ||
		result.RequiredInventoryUnits.Coverage.Denominator != 1 {
		t.Fatalf("node-grain coverage is invalid: %#v", result.RequiredInventoryUnits.Coverage)
	}
}

func TestAppliedPriceSummaryRefusesNonFinitePortfolioArithmetic(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.Horizons[0].ExpectedUnits = math.MaxFloat64
	result := CalculateScenario(fixture)
	if len(result.AppliedPriceSummaries) != 1 ||
		result.AppliedPriceSummaries[0].Availability != "unavailable" ||
		result.AppliedPriceSummaries[0].AppliedChangePct != nil {
		t.Fatalf("non-finite price summary was emitted: %#v", result.AppliedPriceSummaries)
	}
	if payload, err := json.Marshal(result); err != nil || len(payload) == 0 {
		t.Fatalf("result contains a non-JSON numeric value: %v", err)
	}
}

func TestRiskStatesRemainIndependentAtZeroDemand(t *testing.T) {
	metric := scenarioRiskMetric([]scenarioRiskPair{{mu0: 0, mu1: 5, risk0: 0, risk1: .25}}, 1, nil)
	if metric.Current.Value != nil || metric.Scenario.Value == nil || *metric.Scenario.Value != 25 {
		t.Fatalf("state-specific zero demand was not preserved: %#v", metric)
	}
	if metric.Impact.Value != nil || metric.ImpactPoints != nil {
		t.Fatalf("impact was fabricated with one unavailable state: %#v", metric)
	}
}

func TestRiskDoesNotInferZeroFromAMissingAllocationFact(t *testing.T) {
	fixture := scenarioCalcFixture()
	fixture.InventorySeries = nil
	result := CalculateScenario(fixture)
	if result.StockoutRiskPct.Coverage.Numerator != 0 ||
		result.StockoutRiskPct.Current.Value != nil {
		t.Fatalf("missing ATP allocation was treated as zero: %#v", result.StockoutRiskPct)
	}
	if !strings.Contains(
		strings.Join(result.StockoutRiskPct.Current.ReasonCodes, ","),
		"ATP_ALLOCATION_UNAVAILABLE",
	) {
		t.Fatalf("missing allocation reason was lost: %#v", result.StockoutRiskPct)
	}
}

func TestDecision44FXVectors(t *testing.T) {
	for _, vector := range []struct {
		amount int64
		rate   string
		want   int64
	}{
		{10_000, "83", 830_000},
		{5, "0.5", 2},
		{3, "0.5", 2},
		{1_000_000, "83.123456789012345678", 83_123_457},
	} {
		got, ok := convertScenarioMinor(vector.amount, vector.rate, "USD", "INR")
		if !ok || got != vector.want {
			t.Fatalf("convert(%d, %s) = %d, %v; want %d", vector.amount, vector.rate, got, ok, vector.want)
		}
	}
	facts := []scenarioMoneyFact{
		{current: 5, scenario: 5, currency: "USD"},
		{current: 5, scenario: 5, currency: "USD"},
		{current: 5, scenario: 5, currency: "USD"},
	}
	metric := reportingMoneyMetric(facts, 3, "fact", &ScenarioReportingFX{
		CurrencyCode: "INR", RateMapContentFingerprint: strings.Repeat("f", 64), Rates: map[string]string{"USD": "0.5"},
	})
	if metric.Current.ValueMinor == nil || *metric.Current.ValueMinor != 6 {
		t.Fatalf("FX was aggregated before per-fact rounding: %#v", metric)
	}
}

func TestMoneyRoundingRefusesTheFloat64Int64Boundary(t *testing.T) {
	if _, ok := roundHalfEvenInt64(float64(math.MaxInt64)); ok {
		t.Fatal("2^63 float was converted to a wrapped int64")
	}
	if got, ok := roundHalfEvenInt64(-math.Ldexp(1, 63)); !ok || got != math.MinInt64 {
		t.Fatalf("exact int64 minimum was refused: %d, %v", got, ok)
	}
}

func TestScenarioReportingFXUsesDecisionCutoffAndFingerprintsSelection(t *testing.T) {
	fx := resolveScenarioReportingFX(
		"INR",
		[]ScenarioFXRateObservation{
			{BaseCurrency: "USD", QuoteCurrency: "INR", Rate: "82.5", RateDate: "2026-08-09"},
			{BaseCurrency: "USD", QuoteCurrency: "INR", Rate: "83", RateDate: "2026-08-10"},
			{BaseCurrency: "USD", QuoteCurrency: "INR", Rate: "84", RateDate: "2026-08-11"},
		},
		strings.Repeat("a", 64),
		time.Date(2026, 8, 10, 12, 0, 0, 0, time.UTC),
	)
	if fx == nil {
		t.Fatal("admissible reporting FX was unavailable")
		return
	}
	if fx.Rates["USD"] != "83" || fx.Rates["INR"] != "1" {
		t.Fatalf("wrong cutoff-selected rates: %#v", fx.Rates)
	}
	if !scenarioFingerprintPattern.MatchString(fx.RateMapContentFingerprint) {
		t.Fatalf("rate-map fingerprint is invalid: %q", fx.RateMapContentFingerprint)
	}
}

func TestScenarioSeriesKeyUsesPublicContractNames(t *testing.T) {
	payload, err := json.Marshal(ScenarioSeriesKey{Market: "m", SKU: "k", Store: "s", Channel: "c"})
	if err != nil {
		t.Fatal(err)
	}
	if string(payload) != `{"marketId":"m","skuId":"k","storeId":"s","channelId":"c"}` {
		t.Fatalf("unexpected public SeriesKey: %s", payload)
	}
}
