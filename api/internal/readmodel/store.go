package readmodel

import (
	"encoding/json"
	"fmt"
	"os"
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
