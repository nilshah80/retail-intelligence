package readmodel

import (
	"encoding/json"
	"math/big"
	"regexp"
	"sort"
	"time"

	"github.com/nilshah80/retail-intelligence/api/internal/fingerprint"
)

const scenarioReportingFXSchema = "retail-forecast-scenario-reporting-fx/v1"

var scenarioCurrencyPattern = regexp.MustCompile(`^[A-Z]{3}$`)

type selectedScenarioFXRate struct {
	BaseCurrency  string `json:"baseCurrency"`
	QuoteCurrency string `json:"quoteCurrency"`
	Rate          string `json:"rate"`
	RateDate      string `json:"rateDate"`
	Basis         string `json:"basis"`
}

// resolveScenarioReportingFX selects the greatest rate_date at or before the
// scenario decision cutoff from the immutable publication loaded at process
// start. The publication fingerprint is part of the rate-map identity, so a
// process using different accepted FX evidence cannot claim the same map.
func resolveScenarioReportingFX(
	reportingCurrency string,
	observations []ScenarioFXRateObservation,
	sourceFingerprint string,
	decisionAsOf time.Time,
) *ScenarioReportingFX {
	if !scenarioCurrencyPattern.MatchString(reportingCurrency) ||
		!scenarioFingerprintPattern.MatchString(sourceFingerprint) ||
		decisionAsOf.IsZero() {
		return nil
	}
	cutoffDate := decisionAsOf.UTC().Format(time.DateOnly)
	selected := make(map[string]selectedScenarioFXRate)
	for _, observation := range observations {
		if !scenarioCurrencyPattern.MatchString(observation.BaseCurrency) ||
			observation.QuoteCurrency != reportingCurrency ||
			!exactFXRatePattern.MatchString(observation.Rate) {
			return nil
		}
		parsedDate, err := time.Parse(time.DateOnly, observation.RateDate)
		if err != nil || parsedDate.Format(time.DateOnly) > cutoffDate {
			if err != nil {
				return nil
			}
			continue
		}
		candidate := selectedScenarioFXRate{
			BaseCurrency:  observation.BaseCurrency,
			QuoteCurrency: reportingCurrency,
			Rate:          observation.Rate,
			RateDate:      observation.RateDate,
			Basis:         "accepted_publication_rate",
		}
		current, exists := selected[observation.BaseCurrency]
		if exists && current.RateDate == candidate.RateDate {
			// Publication rate identity is base/quote/date. Two observations at
			// the same identity are ambiguous even if their values happen to match.
			return nil
		}
		if !exists || current.RateDate < candidate.RateDate {
			selected[observation.BaseCurrency] = candidate
		}
	}
	identity, hasIdentity := selected[reportingCurrency]
	if hasIdentity {
		identityRate, ok := new(big.Rat).SetString(identity.Rate)
		if !ok || identityRate.Cmp(big.NewRat(1, 1)) != 0 {
			return nil
		}
	}
	if !hasIdentity {
		selected[reportingCurrency] = selectedScenarioFXRate{
			BaseCurrency: reportingCurrency, QuoteCurrency: reportingCurrency,
			Rate: "1", RateDate: cutoffDate, Basis: "identity",
		}
	}
	bases := make([]string, 0, len(selected))
	for base := range selected {
		bases = append(bases, base)
	}
	sort.Strings(bases)
	rateRows := make([]selectedScenarioFXRate, 0, len(bases))
	rateMap := make(map[string]string, len(bases))
	for _, base := range bases {
		rateRows = append(rateRows, selected[base])
		rateMap[base] = selected[base].Rate
	}
	payload := struct {
		SchemaVersion                string                   `json:"schemaVersion"`
		DecisionAsOf                 string                   `json:"decisionAsOf"`
		ReportingCurrency            string                   `json:"reportingCurrency"`
		SourcePublicationFingerprint string                   `json:"sourcePublicationFingerprint"`
		Rates                        []selectedScenarioFXRate `json:"rates"`
	}{
		SchemaVersion:                scenarioReportingFXSchema,
		DecisionAsOf:                 decisionAsOf.UTC().Format(time.RFC3339Nano),
		ReportingCurrency:            reportingCurrency,
		SourcePublicationFingerprint: sourceFingerprint,
		Rates:                        rateRows,
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return nil
	}
	rateFingerprint, err := fingerprint.SemanticFingerprint(raw, nil)
	if err != nil {
		return nil
	}
	return &ScenarioReportingFX{
		CurrencyCode:              reportingCurrency,
		RateMapContentFingerprint: rateFingerprint,
		Rates:                     rateMap,
	}
}
