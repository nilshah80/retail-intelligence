package readmodel

import (
	"context"
	"testing"
)

func TestScenarioAuthorityTupleDistinguishesExplicitInventoryAbsence(t *testing.T) {
	base := ScenarioAuthorityTuple{
		ForecastVersion:        "fv_0000000000000000",
		ScenarioContextVersion: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
	}
	if !ScenarioAuthorityEqual(base, base) {
		t.Fatal("an authority tuple must equal itself")
	}
	withInventory := base
	withInventory.Inventory = &ScenarioInventoryAuthority{
		InventoryVersion:          "iv_test",
		InventoryExtensionVersion: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
	}
	if ScenarioAuthorityEqual(base, withInventory) {
		t.Fatal("explicit inventory absence must differ from a present extension")
	}
}

func TestScenarioForecastVersionValidation(t *testing.T) {
	if !ValidScenarioForecastVersion("fv_0123456789abcdef") {
		t.Fatal("valid forecast version was rejected")
	}
	for _, invalid := range []string{"", "fv_123", "iv_0123456789abcdef", "fv_0123456789abcdeg"} {
		if ValidScenarioForecastVersion(invalid) {
			t.Fatalf("invalid forecast version %q was accepted", invalid)
		}
	}
}

func TestUnconfiguredScenarioStoreFailsClosed(t *testing.T) {
	store := LoadScenario(context.Background(), ScenarioConfig{})
	defer store.Close()
	_, err := store.Bootstrap(context.Background(), "fv_0123456789abcdef")
	if err == nil {
		t.Fatal("unconfigured scenario authority returned success")
	}
	if status := ScenarioReadErrorStatus(err); status != 503 {
		t.Fatalf("status = %d", status)
	}
	payload, ok := ScenarioReadErrorPayload(err).(ScenarioUnavailable)
	if !ok || payload.ReasonCode != ScenarioReasonReadUnavailable {
		t.Fatalf("unexpected unavailable payload: %#v", payload)
	}
}
