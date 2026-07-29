package fingerprint

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

type vectorDocument struct {
	SpecVersion         string `json:"specVersion"`
	VolatilePathVersion string `json:"volatilePathVersion"`
	Vectors             []struct {
		Name      string          `json:"name"`
		Payload   json.RawMessage `json:"payload"`
		Canonical string          `json:"canonical"`
		SHA256    string          `json:"sha256"`
	} `json:"vectors"`
	InvalidVectors []struct {
		Name    string          `json:"name"`
		Payload json.RawMessage `json:"payload"`
	} `json:"invalidVectors"`
}

type pointerDocument struct {
	Version  string   `json:"version"`
	Pointers []string `json:"pointers"`
}

func contractPath(parts ...string) string {
	all := append([]string{"..", "..", "..", "contracts", "fingerprints"}, parts...)
	return filepath.Join(all...)
}

func TestSharedGoldenVectors(t *testing.T) {
	vectorBytes, err := os.ReadFile(contractPath("vectors", "v1.json"))
	if err != nil {
		t.Fatal(err)
	}
	pointerBytes, err := os.ReadFile(contractPath("volatile-pointers.v1.json"))
	if err != nil {
		t.Fatal(err)
	}
	var vectors vectorDocument
	if err := json.Unmarshal(vectorBytes, &vectors); err != nil {
		t.Fatal(err)
	}
	var pointers pointerDocument
	if err := json.Unmarshal(pointerBytes, &pointers); err != nil {
		t.Fatal(err)
	}
	if vectors.SpecVersion != SpecVersion {
		t.Fatalf("spec version = %q", vectors.SpecVersion)
	}
	if vectors.VolatilePathVersion != VolatilePathVersion ||
		pointers.Version != VolatilePathVersion {
		t.Fatal("volatile pointer versions differ")
	}

	for _, vector := range vectors.Vectors {
		t.Run(vector.Name, func(t *testing.T) {
			canonical, err := Canonicalize(vector.Payload, pointers.Pointers)
			if err != nil {
				t.Fatal(err)
			}
			if string(canonical) != vector.Canonical {
				t.Fatalf("canonical = %s", canonical)
			}
			digest, err := SemanticFingerprint(vector.Payload, pointers.Pointers)
			if err != nil {
				t.Fatal(err)
			}
			if digest != vector.SHA256 {
				t.Fatalf("sha256 = %s", digest)
			}
		})
	}

	for _, vector := range vectors.InvalidVectors {
		t.Run("invalid-"+vector.Name, func(t *testing.T) {
			if _, err := Canonicalize(vector.Payload, pointers.Pointers); err == nil {
				t.Fatal("invalid vector unexpectedly canonicalized")
			}
		})
	}
}

func TestVolatilePointersArePathQualified(t *testing.T) {
	raw := []byte(`{
		"executionTelemetry":"remove",
		"nested":{"executionTelemetry":"keep"},
		"a/b":{"~key":"remove"}
	}`)
	canonical, err := Canonicalize(
		raw,
		[]string{"/executionTelemetry", "/a~1b/~0key"},
	)
	if err != nil {
		t.Fatal(err)
	}
	if string(canonical) != `{"a/b":{},"nested":{"executionTelemetry":"keep"}}` {
		t.Fatalf("canonical = %s", canonical)
	}
}

func TestDuplicateObjectKeysAreRejected(t *testing.T) {
	if _, err := Canonicalize([]byte(`{"market":"in","market":"us"}`), nil); err == nil {
		t.Fatal("duplicate object key unexpectedly canonicalized")
	}
}
