package readmodel

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
)

type Paths struct {
	GateAReport         string
	GateBReport         string
	PublicationManifest string
}

type Store struct {
	gateA       map[string]any
	gateB       map[string]any
	publication map[string]any
}

func Load(paths Paths) (*Store, error) {
	gateA, err := readObject(paths.GateAReport)
	if err != nil {
		return nil, fmt.Errorf("Gate A report: %w", err)
	}
	gateB, err := readObject(paths.GateBReport)
	if err != nil {
		return nil, fmt.Errorf("Gate B report: %w", err)
	}
	publication, err := readObject(paths.PublicationManifest)
	if err != nil {
		return nil, fmt.Errorf("publication manifest: %w", err)
	}
	snapshot := stringValue(gateA, "sourceSnapshotId")
	if snapshot == "" ||
		stringValue(gateB, "sourceSnapshotId") != snapshot ||
		stringValue(publication, "sourceSnapshotId") != snapshot {
		return nil, fmt.Errorf("evidence files do not identify the same source snapshot")
	}
	business, ok := publication["businessControls"].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("publication manifest has no governed business controls")
	}
	if _, ok := business["fx"].(map[string]any); !ok {
		return nil, fmt.Errorf("publication manifest has no governed FX controls")
	}
	return &Store{gateA: gateA, gateB: gateB, publication: publication}, nil
}

func readObject(path string) (map[string]any, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var value map[string]any
	if err := json.Unmarshal(raw, &value); err != nil {
		return nil, err
	}
	return value, nil
}

func stringValue(value map[string]any, key string) string {
	result, _ := value[key].(string)
	return result
}

func mapValue(value map[string]any, key string) map[string]any {
	result, _ := value[key].(map[string]any)
	return result
}

func sliceValue(value map[string]any, key string) []any {
	result, _ := value[key].([]any)
	return result
}

func intValue(value map[string]any, key string) int64 {
	number, _ := value[key].(float64)
	return int64(number)
}

func ruleByID(report map[string]any, ruleID string) map[string]any {
	for _, item := range sliceValue(report, "rules") {
		rule, _ := item.(map[string]any)
		if stringValue(rule, "ruleId") == ruleID {
			return rule
		}
	}
	return nil
}

func sourceLabel(sourceSystem string) (string, string) {
	switch sourceSystem {
	case "shopify":
		return "Shopify Commerce", "Commerce / Parquet"
	case "businessCentral":
		return "Business Central ERP", "ERP / Parquet"
	case "companion":
		return "External & Companion", "External / Parquet"
	default:
		return sourceSystem, "Governed source"
	}
}

func channelTypeLabel(channelType string) string {
	switch channelType {
	case "online":
		return "E-commerce"
	case "store":
		return "Store"
	default:
		return channelType
	}
}

func (s *Store) Summary() map[string]any {
	inventory, _ := s.gateA["datasetInventory"].([]any)
	entities, _ := s.publication["entityCounts"].(map[string]any)
	objects, _ := s.publication["objects"].([]any)
	return map[string]any{
		"schemaVersion":          "retail-data-management/v1",
		"dataMode":               "live",
		"sourceSnapshotId":       stringValue(s.gateA, "sourceSnapshotId"),
		"nativeSnapshotId":       s.gateA["nativeSnapshotId"],
		"gateAStatus":            s.gateA["status"],
		"gateBStatus":            s.gateB["status"],
		"sourceDatasetCount":     len(inventory),
		"canonicalEntityCount":   len(entities),
		"curatedObjectCount":     len(objects),
		"publicationFingerprint": s.publication["semanticFingerprint"],
		"capabilityMask":         s.gateB["capabilityMask"],
	}
}

func (s *Store) PublicationFingerprint() string {
	return stringValue(s.publication, "semanticFingerprint")
}

func (s *Store) Dashboard() map[string]any {
	type sourceAggregate struct {
		sourceSystem string
		records      int64
		nullKeys     int64
		duplicates   int64
		datasets     int64
		objects      int64
	}
	aggregates := map[string]*sourceAggregate{}
	for _, item := range sliceValue(s.gateA, "datasetInventory") {
		row, _ := item.(map[string]any)
		sourceSystem := stringValue(row, "sourceSystem")
		if sourceSystem == "" || sourceSystem == "generator" {
			continue
		}
		aggregate := aggregates[sourceSystem]
		if aggregate == nil {
			aggregate = &sourceAggregate{sourceSystem: sourceSystem}
			aggregates[sourceSystem] = aggregate
		}
		records := intValue(row, "scannedRows")
		if records == 0 {
			records = intValue(row, "manifestRows")
		}
		aggregate.records += records
		aggregate.nullKeys += intValue(row, "nullSourceKeyRows")
		aggregate.duplicates += intValue(row, "duplicateSourceKeyRows")
		aggregate.datasets++
		aggregate.objects += intValue(row, "objectCount")
	}
	sourceSystems := make([]string, 0, len(aggregates))
	for sourceSystem := range aggregates {
		sourceSystems = append(sourceSystems, sourceSystem)
	}
	sort.Strings(sourceSystems)

	publishedAt := stringValue(s.publication, "publishedAt")
	gateAPassed := stringValue(s.gateA, "status") == "pass"
	sources := make([]map[string]any, 0, len(sourceSystems))
	for _, sourceSystem := range sourceSystems {
		aggregate := aggregates[sourceSystem]
		invalid := aggregate.nullKeys + aggregate.duplicates
		if invalid > aggregate.records {
			invalid = aggregate.records
		}
		quality := 100.0
		if aggregate.records > 0 {
			quality = math.Round(
				1000*float64(aggregate.records-invalid)/
					float64(aggregate.records),
			) / 10
		}
		name, sourceType := sourceLabel(sourceSystem)
		status := "Healthy"
		if !gateAPassed || quality < 95 {
			status = "Needs attention"
		}
		sources = append(sources, map[string]any{
			"sourceSystem":  sourceSystem,
			"name":          name,
			"type":          sourceType,
			"lastRefreshAt": publishedAt,
			"records":       aggregate.records,
			"qualityPct":    quality,
			"status":        status,
			"action":        "View mapping",
			"datasetCount":  aggregate.datasets,
			"objectCount":   aggregate.objects,
		})
	}

	a03 := ruleByID(s.gateA, "A03")
	dataFreshness := 0.0
	a03Evidence := mapValue(a03, "evidence")
	expectedSources := len(sliceValue(a03Evidence, "expectedSourceSystems"))
	representedSources := len(
		sliceValue(a03Evidence, "representedSourceSystems"),
	)
	if a03 != nil && stringValue(a03, "outcome") == "pass" &&
		expectedSources > 0 {
		dataFreshness = math.Round(
			1000*float64(representedSources)/float64(expectedSources),
		) / 10
	}
	a07 := ruleByID(s.gateA, "A07")
	a07Evidence := mapValue(a07, "evidence")
	rejected := intValue(a07Evidence, "rejectedRows")
	entityCounts := mapValue(s.publication, "entityCounts")
	quarantined := intValue(entityCounts, "quarantine_records")
	rejected += quarantined
	inputRows := intValue(a07Evidence, "inputRows")
	invalidRows := rejected
	if invalidRows > inputRows {
		invalidRows = inputRows
	}
	qualityScore := 0.0
	if inputRows > 0 {
		qualityScore = math.Round(
			1000*float64(inputRows-invalidRows)/float64(inputRows),
		) / 10
	}
	business := mapValue(s.publication, "businessControls")
	channelMarkets := map[string]map[string]struct{}{}
	for _, item := range sliceValue(business, "channels") {
		channel, _ := item.(map[string]any)
		channelType := stringValue(channel, "type")
		marketID := stringValue(channel, "marketId")
		if channelType == "" || marketID == "" {
			continue
		}
		if channelMarkets[channelType] == nil {
			channelMarkets[channelType] = map[string]struct{}{}
		}
		channelMarkets[channelType][marketID] = struct{}{}
	}
	channelTypeKeys := make([]string, 0, len(channelMarkets))
	for channelType := range channelMarkets {
		channelTypeKeys = append(channelTypeKeys, channelType)
	}
	sort.Strings(channelTypeKeys)
	channelTypes := make([]map[string]any, 0, len(channelTypeKeys))
	for _, channelType := range channelTypeKeys {
		marketIDs := make([]string, 0, len(channelMarkets[channelType]))
		for marketID := range channelMarkets[channelType] {
			marketIDs = append(marketIDs, marketID)
		}
		sort.Strings(marketIDs)
		channelTypes = append(channelTypes, map[string]any{
			"type":      channelType,
			"name":      channelTypeLabel(channelType),
			"marketIds": marketIDs,
		})
	}

	return map[string]any{
		"schemaVersion": "retail-data-management-dashboard/v1",
		"dataMode":      "live",
		"kpis": map[string]any{
			"dataFreshnessPct": dataFreshness,
			"qualityScorePct":  qualityScore,
			"connectedSources": len(sources),
			"rejectedRecords":  rejected,
			"lastRefreshAt":    publishedAt,
		},
		"sources": sources,
		"footer": map[string]any{
			"totalSkus":           intValue(business, "totalSkus"),
			"activeSkus":          intValue(business, "activeSkus"),
			"stores":              len(sliceValue(business, "stores")),
			"channels":            len(channelTypeKeys),
			"forecastCoveragePct": business["forecastCoveragePct"],
			"modelAccuracyPct":    business["modelAccuracyPct"],
		},
		"filters": map[string]any{
			"dateRange":    business["dateRange"],
			"markets":      business["markets"],
			"stores":       business["stores"],
			"channelTypes": channelTypes,
			"currencies":   business["currencies"],
		},
	}
}

func (s *Store) FX() map[string]any {
	fx := mapValue(mapValue(s.publication, "businessControls"), "fx")
	return map[string]any{
		"schemaVersion":     "retail-fx-rates/v1",
		"dataMode":          "live",
		"reportingCurrency": fx["reportingCurrency"],
		"coverage":          fx["coverage"],
		"rates":             fx["rates"],
	}
}

// ReportingFX is the approved conversion the inventory read model needs to make
// a cross-currency total legal: reporting currency, and quote-per-base for every
// currency the publication declares a rate for. Read from the same business
// controls `/api/v1/fx/rates` serves, so the screens and the aggregates convert
// with one set of rates rather than two.
//
// The newest rate per base wins. A publication carries ten years of daily
// observations and an inventory position is valued as of now, not as of 2016.
func (s *Store) ReportingFX() (string, map[string]string) {
	fx := mapValue(mapValue(s.publication, "businessControls"), "fx")
	reporting, _ := fx["reportingCurrency"].(string)
	rates := map[string]string{}
	newest := map[string]string{}
	observations, _ := fx["rates"].([]any)
	for _, entry := range observations {
		rate, _ := entry.(map[string]any)
		base, _ := rate["baseCurrency"].(string)
		quote, _ := rate["quoteCurrency"].(string)
		value, _ := rate["rate"].(string)
		asOf, _ := rate["rateDate"].(string)
		if base == "" || quote != reporting || value == "" {
			continue
		}
		if previous, seen := newest[base]; seen && previous >= asOf {
			continue
		}
		newest[base] = asOf
		rates[base] = value
	}
	return reporting, rates
}

func (s *Store) Gates() map[string]any {
	return map[string]any{
		"schemaVersion": "retail-quality-gates/v1",
		"gateA":         s.gateA,
		"gateB":         s.gateB,
	}
}

func (s *Store) Capabilities() any {
	return s.gateB["capabilityMask"]
}

func (s *Store) Reconciliation() any {
	return s.gateB["reconciliation"]
}

func (s *Store) QualityFindings() []any {
	rules, _ := s.gateB["rules"].([]any)
	result := make([]any, 0)
	for _, item := range rules {
		rule, ok := item.(map[string]any)
		if !ok {
			continue
		}
		outcome, _ := rule["outcome"].(string)
		if outcome == "warning" || outcome == "capability_downgrade" ||
			outcome == "critical" {
			result = append(result, rule)
		}
	}
	return result
}
