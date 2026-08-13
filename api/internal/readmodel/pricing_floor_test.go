package readmodel

import "testing"

// TestMarginProtectionRefusal covers the public Margin Protection refusal contract
// directly (plan §0.0): a proposed price whose margin on the weighted-average cost
// basis is under the configured floor is refused with MARGIN_BELOW_FLOOR, and a
// missing cost basis is refused with COST_MISSING. This is always-on coverage of the
// error RunSimulation returns; the DB-backed simulation path is an integration concern
// that skips without a Postgres DSN.
func TestMarginProtectionRefusal(t *testing.T) {
	cases := []struct {
		name          string
		proposedMinor int64
		marginCost    float64
		floorPct      float64
		costAvailable bool
		wantReason    string // "" means no refusal (nil error)
	}{
		{"sub-floor margin is refused", 19_000, 18_000, 12, true, "MARGIN_BELOW_FLOOR"}, // 5.26% < 12%
		{"exactly at floor passes", 20_000, 17_600, 12, true, ""},                       // 12.00%
		{"comfortable WAC margin passes", 20_000, 12_000, 12, true, ""},                 // 40%
		{"missing cost basis is refused", 19_000, 0, 12, false, "COST_MISSING"},
		{"zero floor never refuses", 19_000, 18_000, 0, true, ""},
		{"non-positive price never refuses", 0, 18_000, 12, true, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := marginProtectionRefusal(tc.proposedMinor, tc.marginCost, tc.floorPct, tc.costAvailable)
			if tc.wantReason == "" {
				if err != nil {
					t.Fatalf("expected no refusal, got %v", err)
				}
				return
			}
			readErr, ok := err.(*PricingReadError)
			if !ok {
				t.Fatalf("expected *PricingReadError, got %T (%v)", err, err)
			}
			if readErr.reasonCode != tc.wantReason {
				t.Fatalf("reasonCode = %q, want %q", readErr.reasonCode, tc.wantReason)
			}
			if readErr.status != 422 {
				t.Fatalf("status = %d, want 422", readErr.status)
			}
		})
	}
}

// TestMinMarginFloorPctReadsTheCapability confirms the floor percent is sourced from
// the active bundle's priceMargin capability, and is a no-op floor when absent.
func TestMinMarginFloorPctReadsTheCapability(t *testing.T) {
	store := &PricingStore{capabilities: map[string]any{
		"priceMargin": map[string]any{"minMarginPct": "12"},
	}}
	if got := store.minMarginFloorPct(); got != 12 {
		t.Fatalf("minMarginFloorPct() = %v, want 12", got)
	}
	empty := &PricingStore{capabilities: map[string]any{}}
	if got := empty.minMarginFloorPct(); got != 0 {
		t.Fatalf("minMarginFloorPct() with no capability = %v, want 0", got)
	}
}
