package readmodel

import (
	"bytes"
	"strings"
	"testing"
)

func TestNormalizePricingExportFilename(t *testing.T) {
	t.Parallel()
	valid := map[string]string{
		" price recommendations ": "price_recommendations.csv",
		"prices.csv":              "prices.csv",
		"prices.csv.csv":          "prices.csv",
		"report.v1":               "report.v1.csv",
	}
	for input, expected := range valid {
		input, expected := input, expected
		t.Run(input, func(t *testing.T) {
			t.Parallel()
			actual, err := normalizePricingExportFilename(input)
			if err != nil || actual != expected {
				t.Fatalf("normalize(%q) = %q, %v; want %q", input, actual, err, expected)
			}
		})
	}
	for _, input := range []string{"", "../prices", "CON", ".hidden", "a/b", "a\\b"} {
		if _, err := normalizePricingExportFilename(input); err == nil {
			t.Fatalf("normalize(%q) unexpectedly succeeded", input)
		}
	}
}

func TestSerializePricingCSVExactEncodings(t *testing.T) {
	t.Parallel()
	rows := [][]string{
		{"Product", "Formula", "Unicode"},
		{"Oil, \"Premium\"\n5L", "=1+1", "₹"},
	}
	plain := serializeCSV(rows, false)
	if bytes.HasPrefix(plain, []byte{0xef, 0xbb, 0xbf}) {
		t.Fatal("plain CSV unexpectedly has a BOM")
	}
	if bytes.HasSuffix(plain, []byte("\n")) || bytes.Contains(plain, []byte("\r\n")) {
		t.Fatalf("plain CSV has incorrect record separators: %q", plain)
	}
	if !strings.Contains(string(plain), `"Oil, ""Premium""`+"\n"+`5L"`) {
		t.Fatalf("quoted multiline cell was not RFC-4180 escaped: %q", plain)
	}
	if !strings.Contains(string(plain), `"'=1+1"`) {
		t.Fatalf("formula cell was not neutralized: %q", plain)
	}

	excel := serializeCSV(rows, true)
	if !bytes.HasPrefix(excel, []byte{0xef, 0xbb, 0xbf}) {
		t.Fatal("Excel-compatible CSV lacks UTF-8 BOM")
	}
	if bytes.HasSuffix(excel, []byte("\r\n")) || !bytes.Contains(excel, []byte("\r\n")) {
		t.Fatalf("Excel-compatible CSV separators are incorrect: %q", excel)
	}
}

func TestUniqueRecommendationIDs(t *testing.T) {
	t.Parallel()
	id := "pr_0123456789abcdef0123"
	values, err := uniqueRecommendationIDs([]string{id})
	if err != nil || len(values) != 1 || values[0] != id {
		t.Fatalf("valid ID rejected: %v, %v", values, err)
	}
	if _, err := uniqueRecommendationIDs([]string{id, id}); err == nil {
		t.Fatal("duplicate selection unexpectedly accepted")
	}
	if _, err := uniqueRecommendationIDs([]string{"not-an-id"}); err == nil {
		t.Fatal("invalid selection unexpectedly accepted")
	}
}

func TestRecommendationWherePreservesChannelIdentityAndFiltersChannelType(t *testing.T) {
	t.Parallel()
	where, arguments := recommendationWhere(PricingQuery{
		ChannelID:   "gulf-india:gulf-online",
		ChannelType: "online",
	})
	if !strings.Contains(where, "channel_id = $2") ||
		!strings.Contains(where, "details->>'channel_type' = $3") {
		t.Fatalf("channel filters missing from query: %s", where)
	}
	if len(arguments) != 3 || arguments[1] != "gulf-india:gulf-online" ||
		arguments[2] != "online" {
		t.Fatalf("channel filter arguments are not stable: %#v", arguments)
	}
}

func TestPricingUnavailableStatusPreservesStaleAuthority(t *testing.T) {
	store := unavailablePricing(PricingReasonStale, "authority changed")
	if status := PricingReadErrorStatus(store.unavailableError()); status != 409 {
		t.Fatalf("stale pricing authority status = %d", status)
	}
	if status := PricingReadErrorStatus(
		unavailablePricing(PricingReasonUnavailable, "missing").unavailableError(),
	); status != 503 {
		t.Fatalf("missing pricing authority status = %d", status)
	}
}
