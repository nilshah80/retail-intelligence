package readmodel

import "testing"

// TestPromotionPlannerViewPositiveBranch covers the positive disposition: the view
// must honour plannerAvailable, carry the accepted promotions through as shaped
// portfolio rows, and skip any array entry that is not a JSON object. This is the
// contract the read model exposes without a database.
func TestPromotionPlannerViewPositiveBranch(t *testing.T) {
	disposition := map[string]any{
		"plannerAvailable":       true,
		"acceptedPromotionCount": float64(2),
		"acceptedPromotions": []any{
			map[string]any{
				"promoId":            "gulf-diwali-trade-2016",
				"promoName":          "Diwali distributor trade scheme 2016",
				"revenueUpliftMinor": float64(5735451880),
				"currencyCode":       "INR",
			},
			"not-an-object", // must be skipped, not shaped into a row
			map[string]any{"promoId": "gulf-summer-2019"},
		},
	}
	available, items, reasonCode, message := promotionPlannerView(disposition)
	if !available {
		t.Fatalf("expected planner available on the positive branch")
	}
	if len(items) != 2 {
		t.Fatalf("expected 2 shaped items (non-object skipped), got %d", len(items))
	}
	if items[0]["promoId"] != "gulf-diwali-trade-2016" {
		t.Fatalf("promoId = %v, want gulf-diwali-trade-2016", items[0]["promoId"])
	}
	if reasonCode != PricingReasonPromotion {
		t.Fatalf("reasonCode = %q, want %q", reasonCode, PricingReasonPromotion)
	}
	if message == "" {
		t.Fatalf("expected a non-empty governed message on the positive branch")
	}
}

// TestPromotionPlannerViewNegativeBranch covers the honest dark state: an explicit
// false, an absent flag, and a false flag that still carries promotions all yield
// unavailable with empty (non-nil) items — the accepted list is never leaked when
// the planner is dark.
func TestPromotionPlannerViewNegativeBranch(t *testing.T) {
	for name, disposition := range map[string]map[string]any{
		"explicit false": {"plannerAvailable": false},
		"absent flag":    {},
		"false with promotions": {
			"plannerAvailable":   false,
			"acceptedPromotions": []any{map[string]any{"promoId": "x"}},
		},
	} {
		t.Run(name, func(t *testing.T) {
			available, items, reasonCode, message := promotionPlannerView(disposition)
			if available {
				t.Fatalf("expected planner unavailable")
			}
			if items == nil || len(items) != 0 {
				t.Fatalf("expected empty non-nil items, got %#v", items)
			}
			if reasonCode != PricingReasonPromotion {
				t.Fatalf("reasonCode = %q, want %q", reasonCode, PricingReasonPromotion)
			}
			if message == "" {
				t.Fatalf("expected a governed message")
			}
		})
	}
}

// TestPromotionItems checks the array coercion in isolation: a non-array yields an
// empty non-nil slice, and non-object entries are dropped.
func TestPromotionItems(t *testing.T) {
	if got := promotionItems(nil); got == nil || len(got) != 0 {
		t.Fatalf("nil raw should yield an empty non-nil slice, got %#v", got)
	}
	if got := promotionItems("not-a-list"); got == nil || len(got) != 0 {
		t.Fatalf("non-array raw should yield an empty non-nil slice, got %#v", got)
	}
	got := promotionItems([]any{
		map[string]any{"promoId": "a"},
		42,
		map[string]any{"promoId": "b"},
	})
	if len(got) != 2 {
		t.Fatalf("expected 2 objects (non-object dropped), got %d", len(got))
	}
}
