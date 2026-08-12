package readmodel

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
)

type pricingServingDocument struct {
	SchemaVersion             string `json:"schemaVersion"`
	ConfigFingerprint         string `json:"configFingerprint"`
	RetailerID                string `json:"retailerId"`
	TenantID                  string `json:"tenantId"`
	Environment               string `json:"environment"`
	Audience                  string `json:"audience"`
	ActivationSetID           string `json:"activationSetId"`
	BundleID                  string `json:"bundleId"`
	BundleSemanticFingerprint string `json:"bundleSemanticFingerprint"`
	LogicalDatabaseTarget     string `json:"logicalDatabaseTarget"`
	DSNEnvironmentVariable    string `json:"dsnEnvironmentVariable"`
}

func LoadPricingServingConfig(path string) (PricingConfig, error) {
	if path == "" {
		return PricingConfig{}, nil
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return PricingConfig{}, fmt.Errorf("pricing serving config: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	var document pricingServingDocument
	if err := decoder.Decode(&document); err != nil {
		return PricingConfig{}, fmt.Errorf("pricing serving config is invalid: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return PricingConfig{}, fmt.Errorf("pricing serving config has trailing JSON")
		}
		return PricingConfig{}, fmt.Errorf("pricing serving config has invalid trailing content: %w", err)
	}
	if document.SchemaVersion != "retail-pricing-local-serving-config/v1" ||
		document.Environment != "local" || document.Audience != "response_rich_local" ||
		document.DSNEnvironmentVariable != "RETAIL_POSTGRES_DSN" ||
		document.RetailerID == "" || document.TenantID == "" ||
		document.LogicalDatabaseTarget == "" ||
		!pricingActivationIDPattern.MatchString(document.ActivationSetID) ||
		!pricingBundleIDPattern.MatchString(document.BundleID) ||
		!sha256Pattern.MatchString(document.BundleSemanticFingerprint) {
		return PricingConfig{}, fmt.Errorf("pricing serving config violates the closed startup contract")
	}
	var identity map[string]any
	if err := json.Unmarshal(raw, &identity); err != nil {
		return PricingConfig{}, fmt.Errorf("pricing serving config identity: %w", err)
	}
	delete(identity, "configFingerprint")
	canonical, err := json.Marshal(identity)
	if err != nil {
		return PricingConfig{}, fmt.Errorf("pricing serving config canonicalization: %w", err)
	}
	digest := sha256.Sum256(canonical)
	if document.ConfigFingerprint != hex.EncodeToString(digest[:]) {
		return PricingConfig{}, fmt.Errorf("pricing serving config fingerprint mismatch")
	}
	return PricingConfig{
		RetailerID: document.RetailerID, TenantID: document.TenantID,
		Environment:     document.Environment,
		ActivationSetID: document.ActivationSetID, BundleID: document.BundleID,
		BundleFingerprint: document.BundleSemanticFingerprint,
		LogicalDatabase:   document.LogicalDatabaseTarget,
	}, nil
}
