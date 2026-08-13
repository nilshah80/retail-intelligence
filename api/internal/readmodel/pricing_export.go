package readmodel

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"regexp"
	"sort"
	"strings"
	"time"
)

const MaxPricingExportRows = 10_000

var (
	pricingRecommendationIDPattern = regexp.MustCompile(`^pr_[0-9a-f]{20}$`)
	pricingExportFilenamePattern   = regexp.MustCompile(`^[A-Za-z0-9 _.-]{1,80}$`)
	pricingWhitespacePattern       = regexp.MustCompile(`\s+`)
	pricingReservedFilenamePattern = regexp.MustCompile(`(?i)^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)`)
)

type PricingExportRequest struct {
	Scope                   string
	Format                  string
	IncludeExplanation      bool
	Filename                string
	ExpectedCount           int
	ExpectedActivationSetID string
	SelectedIDs             []string
	Query                   PricingQuery
}

type PricingExport struct {
	Bytes         []byte
	Filename      string
	Count         int
	ExportID      string
	ScopeRevision string
}

func normalizePricingExportFilename(value string) (string, error) {
	value = strings.TrimSpace(value)
	if !pricingExportFilenamePattern.MatchString(value) || strings.Contains(value, "..") ||
		strings.HasPrefix(value, ".") || strings.ContainsAny(value, `/\`) ||
		pricingReservedFilenamePattern.MatchString(value) {
		return "", pricingError(
			"EXPORT_FILENAME_INVALID",
			"File name must use 1–80 letters, digits, spaces, _, - or . without path or reserved-name segments.",
			422,
		)
	}
	value = pricingWhitespacePattern.ReplaceAllString(value, "_")
	for strings.HasSuffix(strings.ToLower(value), ".csv") {
		value = value[:len(value)-4]
	}
	if value == "" || pricingReservedFilenamePattern.MatchString(value) {
		return "", pricingError("EXPORT_FILENAME_INVALID", "File name is invalid.", 422)
	}
	return value + ".csv", nil
}

func uniqueRecommendationIDs(values []string) ([]string, error) {
	seen := make(map[string]bool, len(values))
	result := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if !pricingRecommendationIDPattern.MatchString(value) || seen[value] {
			return nil, pricingError(
				"EXPORT_SELECTION_INVALID",
				"Selected recommendation IDs must be unique active recommendation identities.",
				422,
			)
		}
		seen[value] = true
		result = append(result, value)
	}
	return result, nil
}

func spreadsheetSafe(value string) string {
	if value == "" {
		return value
	}
	switch value[0] {
	case '=', '+', '-', '@', '\t', '\r':
		return "'" + value
	default:
		return value
	}
}

func quoteCSV(value string) string {
	return `"` + strings.ReplaceAll(spreadsheetSafe(value), `"`, `""`) + `"`
}

func serializeCSV(rows [][]string, excelCompatible bool) []byte {
	separator := "\n"
	if excelCompatible {
		separator = "\r\n"
	}
	lines := make([]string, 0, len(rows))
	for _, row := range rows {
		fields := make([]string, len(row))
		for index, value := range row {
			fields[index] = quoteCSV(value)
		}
		lines = append(lines, strings.Join(fields, ","))
	}
	result := []byte(strings.Join(lines, separator))
	if excelCompatible {
		result = append([]byte{0xef, 0xbb, 0xbf}, result...)
	}
	return result
}

func exportHeaders() []string {
	return []string{
		"Priority", "SKU / Product", "Category", "Store", "Action",
		"Current", "AI Price", "Change", "Competitor", "Stock Cover",
		"Forecast Demand", "Current Margin", "Expected Margin",
		"Revenue Impact", "Margin Impact", "AI Reason", "Confidence",
		"Status", "Owner", "export_scope", "record_id", "selection_id",
		"run_id", "retailer_id", "tenant_id", "environment", "authority_id",
		"effective_store_id", "channel_id", "currency", "source_as_of",
		"generated_at",
	}
}

func (s *PricingStore) ExportRecommendations(
	ctx context.Context, request PricingExportRequest,
) (PricingExport, error) {
	if !s.Available() {
		return PricingExport{}, s.unavailableError()
	}
	if request.ExpectedActivationSetID != s.activationSetID {
		return PricingExport{}, pricingError(
			PricingReasonStale,
			"The pricing authority changed; refresh before exporting.",
			409,
		)
	}
	if request.Scope != "selected" && request.Scope != "filtered" && request.Scope != "all" {
		return PricingExport{}, pricingError("EXPORT_SCOPE_INVALID", "Export scope is invalid.", 422)
	}
	if request.Format != "csv" && request.Format != "excel_csv" {
		return PricingExport{}, pricingError("EXPORT_FORMAT_INVALID", "Only CSV and Excel-compatible CSV are available.", 422)
	}
	if request.ExpectedCount < 0 {
		return PricingExport{}, pricingError("EXPORT_COUNT_INVALID", "Expected export count is required.", 422)
	}
	filename, err := normalizePricingExportFilename(request.Filename)
	if err != nil {
		return PricingExport{}, err
	}

	query := request.Query
	query.RecordKind = "recommendation"
	query.Offset = 0
	query.Limit = MaxPricingExportRows
	if request.Scope == "all" {
		query.Category = ""
		query.Action = ""
		query.Confidence = ""
		query.Search = ""
	}
	where, arguments := recommendationWhere(query)
	arguments = bindBundle(arguments, s.bundleID)
	if request.Scope == "selected" {
		identities, identityError := uniqueRecommendationIDs(request.SelectedIDs)
		if identityError != nil {
			return PricingExport{}, identityError
		}
		if len(identities) == 0 {
			return PricingExport{}, pricingError("EXPORT_EMPTY", "No selected recommendations are available to export.", 422)
		}
		arguments = append(arguments, identities)
		where += fmt.Sprintf(" AND recommendation_id = ANY($%d)", len(arguments))
	}

	var count int
	if err := s.pool.QueryRow(
		ctx,
		"SELECT count(*) FROM retail_serving.price_recommendations WHERE "+where,
		arguments...,
	).Scan(&count); err != nil {
		return PricingExport{}, pricingError(PricingReasonRead, "Export population could not be counted.", 503)
	}
	if count != request.ExpectedCount {
		return PricingExport{}, pricingError(
			PricingReasonStale,
			fmt.Sprintf("Export scope changed: expected %d rows, current scope has %d.", request.ExpectedCount, count),
			409,
		)
	}
	if count == 0 {
		return PricingExport{}, pricingError("EXPORT_EMPTY", "No recommendations are available to export.", 422)
	}
	if count > MaxPricingExportRows {
		return PricingExport{}, pricingError(
			"EXPORT_LIMIT_EXCEEDED",
			fmt.Sprintf("Export limit is %d rows; narrow filters or selection.", MaxPricingExportRows),
			422,
		)
	}

	rows, err := s.pool.Query(ctx, `
		SELECT
		 coalesce(priority,''),
		 sku_id || CASE WHEN coalesce(details->>'product_name','') <> ''
		               THEN ' / ' || details->>'product_name' ELSE '' END,
		 coalesce(details->>'category',''),
		 store_id || CASE WHEN channel_id <> '' THEN E'\n' || channel_id ELSE '' END,
		 coalesce(action,''),
		 CASE WHEN current_price_minor IS NULL THEN '' ELSE currency_code || ' ' ||
		  to_char(current_price_minor::numeric/100.0,'FM999999999999990.00') END,
		 CASE WHEN proposed_price_minor IS NULL THEN '' ELSE currency_code || ' ' ||
		  to_char(proposed_price_minor::numeric/100.0,'FM999999999999990.00') END,
		 CASE WHEN current_price_minor > 0 AND proposed_price_minor IS NOT NULL
		  THEN to_char(round(100.0*(proposed_price_minor-current_price_minor)/current_price_minor,2),'FM999999990.00') || '%' ELSE '' END,
		 CASE WHEN competitor_price_minor IS NULL THEN '' ELSE currency_code || ' ' ||
		  to_char(competitor_price_minor::numeric/100.0,'FM999999999999990.00') END,
		 CASE WHEN stock_cover_days IS NULL THEN '' ELSE
		  to_char(stock_cover_days,'FM999999990.0') || ' days' END,
		 coalesce(details->>'forecast_demand_label',''),
		 CASE WHEN current_margin_pct IS NULL THEN '' ELSE
		  to_char(current_margin_pct,'FM999999990.00') || '%' END,
		 CASE WHEN expected_margin_pct IS NULL THEN '' ELSE
		  to_char(expected_margin_pct,'FM999999990.00') || '%' END,
		 CASE WHEN revenue_impact_minor IS NULL THEN '' ELSE currency_code || ' ' ||
		  to_char(revenue_impact_minor::numeric/100.0,'FM999999999999990.00') END,
		 CASE WHEN margin_impact_minor IS NULL THEN '' ELSE currency_code || ' ' ||
		  to_char(margin_impact_minor::numeric/100.0,'FM999999999999990.00') END,
		 coalesce(details->>'drivers',''),
		 CASE WHEN confidence IS NULL THEN '' ELSE
		  to_char(confidence*100.0,'FM990.0') || '%' END,
		 '', '', recommendation_id, store_id, channel_id, currency_code
		FROM retail_serving.price_recommendations
		WHERE `+where+`
		ORDER BY `+recommendationOrder(query.Sort), arguments...)
	if err != nil {
		return PricingExport{}, pricingError(PricingReasonRead, "Export rows could not be read.", 503)
	}
	defer rows.Close()

	generatedAt := time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
	selectionIDs := append([]string(nil), s.selectionIDs...)
	sort.Strings(selectionIDs)
	selectionID := strings.Join(selectionIDs, ";")
	csvRows := make([][]string, 0, count+1)
	csvRows = append(csvRows, exportHeaders())
	for rows.Next() {
		values := make([]string, 19)
		var recordID, effectiveStoreID, channelID, currency string
		pointers := make([]any, 0, 23)
		for index := range values {
			pointers = append(pointers, &values[index])
		}
		pointers = append(pointers, &recordID, &effectiveStoreID, &channelID, &currency)
		if err := rows.Scan(pointers...); err != nil {
			return PricingExport{}, pricingError(PricingReasonRead, "Export row could not be decoded.", 503)
		}
		if !request.IncludeExplanation {
			values[15] = ""
		}
		values = append(values,
			request.Scope, recordID, selectionID, s.sourceRunID,
			s.retailerID, s.tenantID, s.environment, s.inputAuthorityID,
			effectiveStoreID, channelID, currency,
			s.decisionAsOf.UTC().Format(time.RFC3339), generatedAt,
		)
		csvRows = append(csvRows, values)
	}
	if err := rows.Err(); err != nil || len(csvRows)-1 != count {
		return PricingExport{}, pricingError(PricingReasonRead, "Export row count changed while streaming.", 503)
	}
	bytes := serializeCSV(csvRows, request.Format == "excel_csv")
	digest := sha256.Sum256(bytes)
	return PricingExport{
		Bytes: bytes, Filename: filename, Count: count,
		ExportID:      "pex_" + hex.EncodeToString(digest[:8]),
		ScopeRevision: s.activationSetID,
	}, nil
}
