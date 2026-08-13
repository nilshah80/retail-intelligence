package readmodel

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	PricingUnavailableSchema = "retail-pricing-unavailable/v1"
	PricingPageSchema        = "retail-pricing-page/v1"
	PricingMigrationRevision = "0031_pricing_margin_pct"

	PricingReasonUnavailable = "PRICING_READ_MODEL_UNAVAILABLE"
	PricingReasonInvalid     = "PRICING_AUTHORITY_INVALID"
	PricingReasonStale       = "PRICING_AUTHORITY_STALE"
	PricingReasonRead        = "PRICING_READ_FAILED"
	PricingReasonPromotion   = "NO_ORIGIN_VISIBLE_PROMOTION_PLAN"

	DefaultPricingPageSize           = 50
	MaxPricingPageSize               = 200
	PricingForecastScenarioSemantics = "additive_expected_and_sum_of_weekly_planning_bounds_not_four_week_quantiles"
	// competitorMarketPositionTolerance is frozen by
	// contracts/pricing/competitor-policy.json (competitor-assessment/1.0.0).
	competitorMarketPositionTolerance = 0.005
)

var (
	pricingBundleIDPattern     = regexp.MustCompile(`^pb_[0-9a-f]{20}$`)
	pricingActivationIDPattern = regexp.MustCompile(`^pact_[0-9a-f]{16}$`)
)

type PricingConfig struct {
	PostgresDSN       string
	RetailerID        string
	TenantID          string
	Environment       string
	ActivationSetID   string
	BundleID          string
	BundleFingerprint string
	LogicalDatabase   string
	DBReadPool        int
	Presentation      *Store
}

type PricingStore struct {
	pool              *pgxpool.Pool
	reasonCode        string
	message           string
	status            int
	retailerID        string
	tenantID          string
	environment       string
	activationSetID   string
	bundleID          string
	bundleFingerprint string
	sourceFingerprint string
	sourceRunID       string
	inputAuthorityID  string
	decisionAsOf      time.Time
	capabilities      map[string]any
	selectionIDs      []string
	priceMarginActive bool
	presentation      *Store
}

type PricingQuery struct {
	StoreID      string
	ChannelID    string
	ChannelType  string
	Category     string
	Action       string
	Confidence   string
	Search       string
	MatchStatus  string
	CompetitorID string
	Freshness    string
	MatchID      string
	RecordKind   string
	Sort         string
	Offset       int
	Limit        int
}

type PriceSimulationRequest struct {
	RecommendationID        string
	ProposedPriceMinor      int64
	SimulationPeriod        string
	DemandAssumption        string
	InventoryObjective      string
	ExpectedActivationSetID string
}

type PricingReadError struct {
	reasonCode string
	message    string
	status     int
}

// LocalDemoAuthority reports whether the selected authority is the explicitly
// local audience. It exists only so the HTTP boundary can keep diagnostic
// failure injection unavailable for every non-local scope.
func (s *PricingStore) LocalDemoAuthority() bool {
	return s != nil && s.environment == "local"
}

func (e *PricingReadError) Error() string { return e.message }

func pricingError(reason, message string, status int) error {
	return &PricingReadError{reasonCode: reason, message: message, status: status}
}

func PricingReadErrorStatus(err error) int {
	var readError *PricingReadError
	if errors.As(err, &readError) {
		return readError.status
	}
	return 503
}

func PricingReadErrorPayload(err error) map[string]any {
	var readError *PricingReadError
	if !errors.As(err, &readError) {
		readError = &PricingReadError{
			reasonCode: PricingReasonRead,
			message:    "Live pricing intelligence is unavailable.",
			status:     503,
		}
	}
	return map[string]any{
		"schemaVersion": PricingUnavailableSchema,
		"dataMode":      "unavailable",
		"reasonCode":    readError.reasonCode,
		"message":       readError.message,
	}
}

func unavailablePricing(reason, message string, environment ...string) *PricingStore {
	status := 503
	if reason == PricingReasonStale {
		status = 409
	}
	configuredEnvironment := ""
	if len(environment) > 0 {
		configuredEnvironment = environment[0]
	}
	return &PricingStore{
		reasonCode: reason, message: message, status: status,
		environment: configuredEnvironment,
	}
}

func LoadPricing(ctx context.Context, config PricingConfig) *PricingStore {
	if config.PostgresDSN == "" || config.RetailerID == "" ||
		config.TenantID == "" || config.Environment == "" ||
		config.ActivationSetID == "" || config.BundleID == "" ||
		config.BundleFingerprint == "" {
		return unavailablePricing(
			PricingReasonUnavailable,
			"No active PostgreSQL pricing projection is configured.",
			config.Environment,
		)
	}
	if !pricingActivationIDPattern.MatchString(config.ActivationSetID) ||
		!pricingBundleIDPattern.MatchString(config.BundleID) ||
		!sha256Pattern.MatchString(config.BundleFingerprint) {
		return unavailablePricing(
			PricingReasonInvalid, "The configured pricing identity is invalid.", config.Environment,
		)
	}
	poolConfig, err := pgxpool.ParseConfig(config.PostgresDSN)
	if err != nil {
		return unavailablePricing(PricingReasonInvalid, "The PostgreSQL pricing configuration is invalid.", config.Environment)
	}
	if config.LogicalDatabase != "" && poolConfig.ConnConfig.Database != config.LogicalDatabase {
		return unavailablePricing(PricingReasonInvalid, "The PostgreSQL pricing database target differs from reviewed configuration.", config.Environment)
	}
	maxConns := config.DBReadPool
	if maxConns < 1 {
		maxConns = 4
	}
	poolConfig.MaxConns = int32(maxConns)
	poolConfig.MinConns = 0
	poolConfig.MaxConnIdleTime = 5 * time.Minute
	pool, err := pgxpool.NewWithConfig(ctx, poolConfig)
	if err != nil {
		return unavailablePricing(PricingReasonUnavailable, "The PostgreSQL pricing projection is unavailable.", config.Environment)
	}
	var migration string
	if err := pool.QueryRow(ctx, "SELECT version_num FROM retail_intelligence_alembic_version").Scan(&migration); err != nil || migration != PricingMigrationRevision {
		pool.Close()
		return unavailablePricing(PricingReasonInvalid, "The PostgreSQL pricing schema is not at the required migration.", config.Environment)
	}
	store := &PricingStore{pool: pool, presentation: config.Presentation}
	var capabilitiesRaw []byte
	err = pool.QueryRow(ctx, `
		SELECT retailer_id, tenant_id, environment, activation_set_id,
		       bundle_id, semantic_fingerprint, source_publication_fingerprint,
		       source_run_id, input_authority_id, decision_as_of,
		       capabilities, selection_ids
		FROM retail_serving.active_pricing_bundles
		WHERE retailer_id = $1 AND tenant_id = $2 AND environment = $3
	`, config.RetailerID, config.TenantID, config.Environment).Scan(
		&store.retailerID, &store.tenantID, &store.environment,
		&store.activationSetID, &store.bundleID, &store.bundleFingerprint,
		&store.sourceFingerprint, &store.sourceRunID, &store.inputAuthorityID,
		&store.decisionAsOf,
		&capabilitiesRaw, &store.selectionIDs,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		pool.Close()
		return unavailablePricing(PricingReasonUnavailable, "The verified pricing bundle has not been activated for this audience.", config.Environment)
	}
	if err != nil {
		pool.Close()
		return unavailablePricing(PricingReasonUnavailable, "The active pricing authority could not be read.", config.Environment)
	}
	if store.activationSetID != config.ActivationSetID || store.bundleID != config.BundleID ||
		store.bundleFingerprint != config.BundleFingerprint {
		pool.Close()
		return unavailablePricing(PricingReasonStale, "The active pricing authority differs from reviewed startup configuration.", config.Environment)
	}
	if err := json.Unmarshal(capabilitiesRaw, &store.capabilities); err != nil {
		pool.Close()
		return unavailablePricing(PricingReasonInvalid, "The active pricing capability document is invalid.", config.Environment)
	}
	// PoC cost-model: margin authority follows the accepted cost basis. This PoC has
	// no retailer integration, so the generated weighted-average cost IS the cost of
	// record; margin is served as authoritative whenever the bundle's priceMargin
	// capability reports an accepted cost (available=true). There is NO "client-actual"
	// data in this PoC — generated data is the actual data (see the PoC cost-model
	// note in the implementation plan). The production path (an active price_margin
	// selection on a client cost) is still honoured for a future real-data deployment.
	if pm, ok := store.capabilities["priceMargin"].(map[string]any); ok {
		if avail, ok := pm["available"].(bool); ok {
			store.priceMarginActive = avail
		}
	}
	if !store.priceMarginActive {
		if err := pool.QueryRow(ctx, `
			SELECT EXISTS (
				SELECT 1 FROM retail_serving.pricing_result_selection_events
				WHERE retailer_id = $1 AND tenant_id = $2 AND environment = $3
				  AND capability = 'price_margin' AND lifecycle_status = 'active'
				  AND selection_id = ANY($4)
			)
		`, config.RetailerID, config.TenantID, config.Environment, store.selectionIDs).Scan(&store.priceMarginActive); err != nil {
			store.priceMarginActive = false
		}
	}
	return store
}

func (s *PricingStore) Close() {
	if s != nil && s.pool != nil {
		s.pool.Close()
	}
}

func (s *PricingStore) Available() bool { return s != nil && s.pool != nil && s.reasonCode == "" }

func (s *PricingStore) unavailableError() error {
	if s == nil {
		return pricingError(
			PricingReasonUnavailable,
			"No active PostgreSQL pricing projection is configured.",
			503,
		)
	}
	status := s.status
	if status == 0 {
		status = 503
	}
	return pricingError(s.reasonCode, s.message, status)
}

func (s *PricingStore) Unavailable() map[string]any {
	return PricingReadErrorPayload(s.unavailableError())
}

func (s *PricingStore) authority() map[string]any {
	return map[string]any{
		"retailerId": s.retailerID, "tenantId": s.tenantID,
		"environment": s.environment, "activationSetId": s.activationSetID,
		"bundleId": s.bundleID, "bundleSemanticFingerprint": s.bundleFingerprint,
		"sourcePublicationFingerprint": s.sourceFingerprint,
		"sourceRunId":                  s.sourceRunID,
		"inputAuthorityId":             s.inputAuthorityID,
		"sourceAsOf":                   s.decisionAsOf.UTC().Format(time.RFC3339),
		"selectionIds":                 s.selectionIDs,
		// The minimum-margin floor is a known policy fact carried on the margin
		// capability. In this PoC the generated weighted-average cost is the
		// authoritative cost, so priceMarginActive is derived from the accepted cost
		// basis (priceMargin.available): primary margin and Margin Protection are
		// enabled on it. (A future real-data deployment would instead require an
		// active price_margin selection — see the PoC Data Principle, plan §0.0.)
		"priceMargin":       s.capabilities["priceMargin"],
		"priceMarginActive": s.priceMarginActive,
	}
}

// presentationLabels keeps display names tied to the governed publication
// that started the API. Native IDs remain in the payload for filtering and
// lineage; names are exposed in separate presentation fields.
func (s *PricingStore) presentationLabels() (map[string]string, map[string]string, map[string]string) {
	stores := map[string]string{}
	channels := map[string]string{}
	categories := map[string]string{}
	if s == nil || s.presentation == nil {
		return stores, channels, categories
	}
	business := mapValue(s.presentation.publication, "businessControls")
	for _, item := range sliceValue(business, "stores") {
		row, _ := item.(map[string]any)
		if id, name := stringValue(row, "storeId"), stringValue(row, "name"); id != "" && name != "" {
			stores[id] = name
		}
	}
	for _, item := range sliceValue(business, "channels") {
		row, _ := item.(map[string]any)
		if id, name := stringValue(row, "channelId"), stringValue(row, "name"); id != "" && name != "" {
			channels[id] = name
		}
	}
	for _, item := range sliceValue(business, "categories") {
		row, _ := item.(map[string]any)
		if id, name := stringValue(row, "categoryId"), stringValue(row, "name"); id != "" && name != "" {
			categories[id] = name
		}
	}
	return stores, channels, categories
}

func (s *PricingStore) addPresentationLabels(items []map[string]any) {
	stores, channels, categories := s.presentationLabels()
	for _, item := range items {
		if id, ok := item["storeId"].(string); ok {
			item["storeName"] = stores[id]
		}
		if id, ok := item["channelId"].(string); ok {
			item["channelName"] = channels[id]
		}
		if label, ok := item["categoryLabel"].(string); !ok || label == "" {
			if id, categoryOK := item["category"].(string); categoryOK {
				item["categoryLabel"] = categories[id]
			}
		}
	}
}

func normalizePricingQuery(query PricingQuery) PricingQuery {
	if query.Offset < 0 {
		query.Offset = 0
	}
	if query.Limit <= 0 {
		query.Limit = DefaultPricingPageSize
	}
	if query.Limit > MaxPricingPageSize {
		query.Limit = MaxPricingPageSize
	}
	query.Search = strings.TrimSpace(query.Search)
	return query
}

func recommendationWhere(query PricingQuery) (string, []any) {
	clauses := []string{"bundle_id = $1"}
	arguments := []any{queryBundleMarker{}}
	add := func(clause string, value any) {
		arguments = append(arguments, value)
		clauses = append(clauses, fmt.Sprintf(clause, len(arguments)))
	}
	if query.StoreID != "" {
		add("store_id = $%d", query.StoreID)
	}
	if query.ChannelID != "" {
		add("channel_id = $%d", query.ChannelID)
	}
	if query.ChannelType != "" {
		add("details->>'channel_type' = $%d", query.ChannelType)
	}
	if query.Category != "" {
		add("details->>'category' = $%d", query.Category)
	}
	if query.Action != "" {
		add("action = $%d", query.Action)
	}
	if query.RecordKind != "" {
		add("record_kind = $%d", query.RecordKind)
	}
	switch query.Confidence {
	case "90":
		clauses = append(clauses, "confidence >= 0.90")
	case "80":
		clauses = append(clauses, "confidence >= 0.80")
	case "low":
		clauses = append(clauses, "confidence < 0.80")
	}
	if query.Search != "" {
		add("(sku_id ILIKE '%%' || $%[1]d || '%%' OR details->>'product_name' ILIKE '%%' || $%[1]d || '%%' OR details->>'drivers' ILIKE '%%' || $%[1]d || '%%')", query.Search)
	}
	return strings.Join(clauses, " AND "), arguments
}

// A private marker lets the query builder reserve $1 without smuggling the
// current authority into generic filter code.
type queryBundleMarker struct{}

func bindBundle(arguments []any, bundleID string) []any {
	result := append([]any(nil), arguments...)
	if len(result) > 0 {
		result[0] = bundleID
	}
	return result
}

func collectMaps(rows pgx.Rows) ([]map[string]any, error) {
	defer rows.Close()
	fields := rows.FieldDescriptions()
	result := make([]map[string]any, 0)
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, err
		}
		row := make(map[string]any, len(fields))
		for index, field := range fields {
			value := values[index]
			if raw, ok := value.([]byte); ok && len(raw) > 0 && raw[0] == '{' {
				var decoded map[string]any
				if json.Unmarshal(raw, &decoded) == nil {
					value = decoded
				}
			}
			row[string(field.Name)] = value
		}
		result = append(result, row)
	}
	return result, rows.Err()
}

func recommendationOrder(sortKey string) string {
	switch sortKey {
	case "confidence_asc":
		return "confidence ASC NULLS LAST, recommendation_id"
	case "revenue_desc":
		return "revenue_impact_minor DESC NULLS LAST, recommendation_id"
	case "price_change_desc":
		return "abs(proposed_price_minor - current_price_minor) DESC NULLS LAST, recommendation_id"
	default:
		return "CASE priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 3 END, revenue_impact_minor DESC NULLS LAST, recommendation_id"
	}
}

func (s *PricingStore) recommendations(ctx context.Context, query PricingQuery) (map[string]any, error) {
	query = normalizePricingQuery(query)
	where, arguments := recommendationWhere(query)
	arguments = bindBundle(arguments, s.bundleID)
	var total int
	if err := s.pool.QueryRow(ctx, "SELECT count(*) FROM retail_serving.price_recommendations WHERE "+where, arguments...).Scan(&total); err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing recommendations could not be counted.", 503)
	}
	listArguments := append(arguments, query.Limit, query.Offset)
	rows, err := s.pool.Query(ctx, `
		SELECT recommendation_id AS "recommendationId",
		       record_kind AS "recordKind", selectable,
		       market_id AS "marketId", sku_id AS "skuId",
		       details->>'product_name' AS "productName",
		       details->>'category' AS category,
		       details->>'category_label' AS "categoryLabel",
		       store_id AS "storeId", channel_id AS "channelId", action,
		       current_price_minor AS "currentPriceMinor",
		       proposed_price_minor AS "proposedPriceMinor", currency_code AS "currencyCode",
		       CASE WHEN current_price_minor > 0 AND proposed_price_minor IS NOT NULL
		            THEN round(100.0 * (proposed_price_minor-current_price_minor)/current_price_minor, 2)
		       END AS "changePct",
		       competitor_price_minor AS "competitorPriceMinor",
		       stock_cover_days AS "stockCoverDays",
		       details->>'forecast_demand_label' AS "forecastDemand",
		       details->>'forecast_expected_units' AS "forecastUnits",
		       current_margin_pct AS "currentMarginPct",
		       expected_margin_pct AS "expectedMarginPct",
		       revenue_impact_minor AS "revenueImpactMinor",
		       margin_impact_minor AS "marginImpactMinor",
		       margin_reason_code AS "marginReasonCode",
		       details->>'drivers' AS "aiReason", confidence, priority, risk,
		       first_failure_reason AS "firstFailureReason",
		       NULL::text AS status, NULL::text AS owner
		FROM retail_serving.price_recommendations
		WHERE `+where+`
		ORDER BY `+recommendationOrder(query.Sort)+`
		LIMIT $`+fmt.Sprint(len(arguments)+1)+` OFFSET $`+fmt.Sprint(len(arguments)+2), listArguments...)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing recommendations could not be read.", 503)
	}
	items, err := collectMaps(rows)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing recommendations could not be decoded.", 503)
	}
	s.addPresentationLabels(items)
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live",
		"authority": s.authority(), "items": items,
		"pagination": map[string]any{
			"offset": query.Offset, "limit": query.Limit, "total": total,
			"ranking": query.Sort,
		},
	}, nil
}

func (s *PricingStore) recommendationSummary(ctx context.Context, query PricingQuery) (map[string]any, error) {
	query = normalizePricingQuery(query)
	where, arguments := recommendationWhere(query)
	arguments = bindBundle(arguments, s.bundleID)
	var open, increase, decrease, hold, withheld, marginRows int64
	var revenue, margin int64
	err := s.pool.QueryRow(ctx, `
		SELECT
		 count(*) FILTER (WHERE record_kind='recommendation'),
		 count(*) FILTER (WHERE record_kind='recommendation' AND action='Increase'),
		 count(*) FILTER (WHERE record_kind='recommendation' AND action='Decrease'),
		 count(*) FILTER (WHERE record_kind='recommendation' AND action='Hold'),
		 count(*) FILTER (WHERE record_kind='withheld_assessment'),
		 coalesce(sum(revenue_impact_minor) FILTER (WHERE record_kind='recommendation'),0),
		 coalesce(sum(margin_impact_minor) FILTER (WHERE record_kind='recommendation' AND margin_impact_minor IS NOT NULL),0),
		 count(*) FILTER (WHERE record_kind='recommendation' AND margin_impact_minor IS NOT NULL)
		FROM retail_serving.price_recommendations WHERE `+where,
		arguments...,
	).Scan(&open, &increase, &decrease, &hold, &withheld, &revenue, &margin, &marginRows)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing summary could not be read.", 503)
	}
	filters, err := s.recommendationFilters(ctx)
	if err != nil {
		return nil, err
	}
	marginValue := any(margin)
	marginReason := any(nil)
	if marginRows == 0 {
		marginValue = nil
		marginReason = "COST_MISSING"
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live",
		"authority": s.authority(), "capabilities": s.capabilities,
		"filters": filters,
		"kpis": map[string]any{
			"openRecommendations":     open,
			"revenueOpportunityMinor": revenue,
			"marginOpportunityMinor":  marginValue,
			"marginReasonCode":        marginReason,
			"recommendationsAtRisk":   0,
			"riskReason":              "No approved non-blocking recommendation warning is present.",
			"recommendationAdoption":  nil,
			"adoptionReason":          "Approval workflow evidence is not available.",
		},
		"recommendationMix": []map[string]any{
			{"label": "Increase price", "count": increase},
			{"label": "Reduce price", "count": decrease},
			{"label": "Hold price", "count": hold},
			{"label": "Manual review", "count": withheld},
		},
		"approvalPipeline": map[string]any{
			"available": false,
			"reason":    "Approval workflow evidence is not available.",
			"labels": []string{
				"Pending analyst review", "Pending category manager",
				"Pending finance approval", "Approved, not scheduled",
				"Scheduled for publishing",
			},
		},
	}, nil
}

func (s *PricingStore) recommendationFilters(ctx context.Context) (map[string]any, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT DISTINCT store_id, channel_id, coalesce(details->>'category','')
		FROM retail_serving.price_recommendations
		WHERE bundle_id=$1 ORDER BY 1,2,3
	`, s.bundleID)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing filters could not be read.", 503)
	}
	defer rows.Close()
	stores, channels, categories := map[string]bool{}, map[string]bool{}, map[string]bool{}
	for rows.Next() {
		var store, channel, category string
		if err := rows.Scan(&store, &channel, &category); err != nil {
			return nil, pricingError(PricingReasonRead, "Pricing filters could not be decoded.", 503)
		}
		stores[store], channels[channel] = true, true
		if category != "" {
			categories[category] = true
		}
	}
	toSorted := func(values map[string]bool) []string {
		result := make([]string, 0, len(values))
		for value := range values {
			result = append(result, value)
		}
		sort.Strings(result)
		return result
	}
	return map[string]any{
		"stores": toSorted(stores), "channels": toSorted(channels),
		"categories": toSorted(categories),
	}, nil
}

func (s *PricingStore) recommendationDetail(ctx context.Context, id string) (map[string]any, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT r.recommendation_id AS "recommendationId", r.record_kind AS "recordKind",
		       selectable, market_id AS "marketId", sku_id AS "skuId",
		       details->>'product_name' AS "productName",
		       details->>'category' AS category,
		       details->>'category_label' AS "categoryLabel",
		       store_id AS "storeId", channel_id AS "channelId", action,
		       current_price_minor AS "currentPriceMinor",
		       proposed_price_minor AS "proposedPriceMinor", currency_code AS "currencyCode",
		       CASE WHEN current_price_minor > 0 AND proposed_price_minor IS NOT NULL
		            THEN round(100.0 * (proposed_price_minor-current_price_minor)/current_price_minor, 2)
		       END AS "changePct",
		       competitor_price_minor AS "competitorPriceMinor",
		       stock_cover_days AS "stockCoverDays",
		       details->>'forecast_demand_label' AS "forecastDemand",
		       details->>'forecast_expected_units' AS "forecastUnits",
		       revenue_impact_minor AS "revenueImpactMinor",
		       margin_impact_minor AS "marginImpactMinor", margin_reason_code AS "marginReasonCode",
		       current_margin_pct AS "currentMarginPct", expected_margin_pct AS "expectedMarginPct",
		       details->>'drivers' AS "aiReason", confidence, priority, risk,
		       first_failure_reason AS "firstFailureReason",
		       NULL::text AS status, NULL::text AS owner, details,
		       ARRAY(
		           SELECT c.candidate_price_minor
		           FROM retail_serving.pricing_price_candidates AS c
		           WHERE c.bundle_id=r.bundle_id AND c.market_id=r.market_id
		             AND c.sku_id=r.sku_id AND c.store_id=r.store_id
		             AND c.channel_id=r.channel_id AND c.eligible
		           ORDER BY c.candidate_price_minor
		       ) AS "legalCandidatePricesMinor"
		FROM retail_serving.price_recommendations AS r
		WHERE r.bundle_id=$1 AND r.recommendation_id=$2
	`, s.bundleID, id)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing recommendation detail could not be read.", 503)
	}
	items, err := collectMaps(rows)
	if err != nil || len(items) != 1 {
		return nil, pricingError("RECOMMENDATION_NOT_FOUND", "The selected recommendation is not in the active authority.", 404)
	}
	s.addPresentationLabels(items)
	if details, ok := items[0]["details"].(map[string]any); ok {
		if available, present := booleanFromDetails(details, "clearance_context_available"); present {
			details["clearance_context_available"] = available
		}
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live",
		"authority": s.authority(), "item": items[0],
	}, nil
}

func (s *PricingStore) groupedRecommendations(ctx context.Context, dimension string, query PricingQuery) (map[string]any, error) {
	query = normalizePricingQuery(query)
	where, arguments := recommendationWhere(query)
	arguments = bindBundle(arguments, s.bundleID)
	expression := "store_id"
	label := "store"
	secondaryLabel := "NULL::text"
	if dimension == "category" {
		expression, label = "coalesce(details->>'category','Unclassified')", "category"
		secondaryLabel = "max(nullif(details->>'category_label',''))"
	}
	rows, err := s.pool.Query(ctx, `
		SELECT `+expression+` AS "`+label+`",
		 `+secondaryLabel+` AS "categoryLabel",
		 count(*) FILTER (WHERE record_kind='recommendation') AS recommendations,
		 coalesce(sum(revenue_impact_minor) FILTER (WHERE record_kind='recommendation'),0) AS "revenueOpportunityMinor",
		 sum(margin_impact_minor) FILTER (WHERE record_kind='recommendation') AS "marginOpportunityMinor",
		 count(*) FILTER (WHERE record_kind='withheld_assessment') AS risk,
		 CASE WHEN count(*) FILTER (WHERE action='Increase') >= count(*) FILTER (WHERE action='Decrease')
		      THEN 'Protect high-demand prices' ELSE 'Review targeted reductions' END AS "priorityAction"
		FROM retail_serving.price_recommendations
		WHERE `+where+` GROUP BY 1 ORDER BY 1`, arguments...)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing grouped view could not be read.", 503)
	}
	items, err := collectMaps(rows)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing grouped view could not be decoded.", 503)
	}
	stores, _, categories := s.presentationLabels()
	for _, item := range items {
		if dimension == "store" {
			if id, ok := item["store"].(string); ok {
				item["storeName"] = stores[id]
			}
		} else if categoryLabel, ok := item["categoryLabel"].(string); !ok || categoryLabel == "" {
			if id, categoryOK := item["category"].(string); categoryOK {
				item["categoryLabel"] = categories[id]
			}
		}
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live",
		"authority": s.authority(), "dimension": dimension, "items": items,
	}, nil
}

func (s *PricingStore) governance(ctx context.Context, query PricingQuery) (map[string]any, error) {
	query.RecordKind = "recommendation"
	where, arguments := recommendationWhere(query)
	arguments = bindBundle(arguments, s.bundleID)
	var total, explained, traced int64
	err := s.pool.QueryRow(ctx, `
		SELECT count(*), count(*) FILTER (WHERE coalesce(details->>'drivers','') <> ''),
		       count(*) FILTER (WHERE coalesce(details->>'lineage','') <> '')
		FROM retail_serving.price_recommendations WHERE `+where, arguments...).Scan(&total, &explained, &traced)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Pricing governance could not be read.", 503)
	}
	percentage := func(value int64) any {
		if total == 0 {
			return nil
		}
		return math.Round(1000*float64(value)/float64(total)) / 10
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live", "authority": s.authority(),
		"approvalSLA": map[string]any{"available": false, "reason": "Approval workflow evidence is not available."},
		"controls": []map[string]any{
			{"label": "Recommendations with AI explanation", "valuePct": percentage(explained), "available": total > 0},
			{"label": "Price changes with approval trail", "valuePct": nil, "available": false},
			{"label": "Published prices with rollback record", "valuePct": nil, "available": false},
			{"label": "Guardrail exceptions documented", "valuePct": percentage(total), "available": total > 0},
			{"label": "Model/version traceability", "valuePct": percentage(traced), "available": total > 0},
		},
	}, nil
}

func (s *PricingStore) competitorSummary(ctx context.Context, query PricingQuery) (map[string]any, error) {
	clauses := []string{"competitor.bundle_id=$1"}
	arguments := []any{s.bundleID}
	ownClauses := []string{
		"recommendation.bundle_id=competitor.bundle_id",
		"recommendation.market_id=competitor.market_id",
		"recommendation.sku_id=competitor.sku_id",
	}
	add := func(text string, value any) {
		arguments = append(arguments, value)
		clauses = append(clauses, fmt.Sprintf(text, len(arguments)))
	}
	addOwn := func(text string, value any) {
		arguments = append(arguments, value)
		ownClauses = append(ownClauses, fmt.Sprintf(text, len(arguments)))
	}
	if query.StoreID != "" {
		addOwn("recommendation.store_id=$%d", query.StoreID)
	}
	if query.ChannelID != "" {
		addOwn("recommendation.channel_id=$%d", query.ChannelID)
	}
	if query.ChannelType != "" {
		addOwn("recommendation.details->>'channel_type'=$%d", query.ChannelType)
	}
	if query.MatchStatus != "" {
		add("competitor.match_status=$%d", query.MatchStatus)
	}
	if query.CompetitorID != "" {
		add("competitor.competitor_id=$%d", query.CompetitorID)
	}
	if query.Freshness != "" {
		add("competitor.freshness=$%d", query.Freshness)
	}
	if query.Search != "" {
		add("(competitor.sku_id ILIKE '%%'||$%[1]d||'%%' OR competitor.details->>'competitor_name' ILIKE '%%'||$%[1]d||'%%' OR competitor.details->>'competitor_product_title' ILIKE '%%'||$%[1]d||'%%' OR own.details->>'product_name' ILIKE '%%'||$%[1]d||'%%')", query.Search)
	}
	where := strings.Join(clauses, " AND ")
	aboveMarketFactor := fmt.Sprintf("%.6f", 1+competitorMarketPositionTolerance)
	belowMarketFactor := fmt.Sprintf("%.6f", 1-competitorMarketPositionTolerance)
	var products, above, below, outOfStock, review int64
	var autoAccepted, manualReview, rejected int64
	var averageConfidence *float64
	err := s.pool.QueryRow(ctx, `
		WITH scoped AS (
		 SELECT competitor.*, own.current_price_minor
		 FROM retail_serving.pricing_competitor_assessments AS competitor
		 JOIN LATERAL (
		  SELECT recommendation.current_price_minor, recommendation.details
		  FROM retail_serving.price_recommendations AS recommendation
		  WHERE `+strings.Join(ownClauses, " AND ")+`
		  ORDER BY recommendation.store_id, recommendation.channel_id,
		           recommendation.recommendation_id LIMIT 1
		 ) AS own ON true
		 WHERE `+where+`
		)
		SELECT count(DISTINCT sku_id),
		 count(*) FILTER (
		  WHERE bound_eligible AND price_minor IS NOT NULL
		    AND current_price_minor::numeric > price_minor::numeric * `+aboveMarketFactor+`
		 ),
		 count(*) FILTER (
		  WHERE bound_eligible AND price_minor IS NOT NULL
		    AND current_price_minor::numeric < price_minor::numeric * `+belowMarketFactor+`
		 ),
		 count(*) FILTER (
		  WHERE bound_eligible AND freshness='Fresh'
		    AND availability_state='Out of Stock'
		 ),
		 count(*) FILTER (WHERE match_status='Needs Review'),
		 count(*) FILTER (WHERE match_status='Matched'),
		 count(*) FILTER (WHERE match_status='Needs Review'),
		 count(*) FILTER (WHERE match_status='Rejected'),
		 avg(match_confidence) * 100.0
		FROM scoped`, arguments...).Scan(
		&products, &above, &below, &outOfStock, &review,
		&autoAccepted, &manualReview, &rejected, &averageConfidence,
	)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Competitor summary could not be read.", 503)
	}
	average := any(nil)
	if averageConfidence != nil {
		average = math.Round(*averageConfidence*10) / 10
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live", "authority": s.authority(),
		"kpis": map[string]any{
			"productsMonitored": products, "aboveMarket": above,
			"belowMarket": below, "competitorOutOfStock": outOfStock,
			"matchesNeedingReview": review,
		},
		"quality": map[string]any{
			"autoAccepted": autoAccepted, "manualReview": manualReview,
			"rejected": rejected, "averageConfidencePct": average,
		},
	}, nil
}

func (s *PricingStore) competitorMatches(ctx context.Context, query PricingQuery) (map[string]any, error) {
	query = normalizePricingQuery(query)
	clauses := []string{"competitor.bundle_id=$1"}
	arguments := []any{s.bundleID}
	ownClauses := []string{
		"recommendation.bundle_id=competitor.bundle_id",
		"recommendation.market_id=competitor.market_id",
		"recommendation.sku_id=competitor.sku_id",
	}
	add := func(text string, value any) {
		arguments = append(arguments, value)
		clauses = append(clauses, fmt.Sprintf(text, len(arguments)))
	}
	addOwn := func(text string, value any) {
		arguments = append(arguments, value)
		ownClauses = append(ownClauses, fmt.Sprintf(text, len(arguments)))
	}
	if query.StoreID != "" {
		addOwn("recommendation.store_id=$%d", query.StoreID)
	}
	if query.ChannelID != "" {
		addOwn("recommendation.channel_id=$%d", query.ChannelID)
	}
	if query.ChannelType != "" {
		addOwn("recommendation.details->>'channel_type'=$%d", query.ChannelType)
	}
	if query.MatchID != "" {
		add("competitor.match_id=$%d", query.MatchID)
	}
	if query.MatchStatus != "" {
		add("competitor.match_status=$%d", query.MatchStatus)
	}
	if query.CompetitorID != "" {
		add("competitor.competitor_id=$%d", query.CompetitorID)
	}
	if query.Freshness != "" {
		add("competitor.freshness=$%d", query.Freshness)
	}
	if query.Search != "" {
		add("(competitor.sku_id ILIKE '%%'||$%[1]d||'%%' OR competitor.details->>'competitor_product_title' ILIKE '%%'||$%[1]d||'%%')", query.Search)
	}
	where := strings.Join(clauses, " AND ")
	aboveMarketFactor := fmt.Sprintf("%.6f", 1+competitorMarketPositionTolerance)
	belowMarketFactor := fmt.Sprintf("%.6f", 1-competitorMarketPositionTolerance)
	var total int
	if err := s.pool.QueryRow(ctx, `
		SELECT count(*)
		FROM retail_serving.pricing_competitor_assessments AS competitor
		JOIN LATERAL (
		 SELECT recommendation.details
		 FROM retail_serving.price_recommendations AS recommendation
		 WHERE `+strings.Join(ownClauses, " AND ")+`
		 ORDER BY recommendation.store_id, recommendation.channel_id,
		          recommendation.recommendation_id LIMIT 1
		) AS own ON true
		WHERE `+where, arguments...).Scan(&total); err != nil {
		return nil, pricingError(PricingReasonRead, "Competitor matches could not be counted.", 503)
	}
	listArgs := append(arguments, query.Limit, query.Offset)
	rows, err := s.pool.Query(ctx, `
		SELECT competitor.match_id AS "matchId", competitor.sku_id AS "skuId",
		       competitor.details->>'competitor_name' AS "competitorName",
		       competitor.details->>'competitor_product_title' AS "matchedProduct",
		       own.current_price_minor AS "ourPriceMinor", competitor.price_minor AS "competitorPriceMinor",
		       CASE WHEN own.current_price_minor > 0 AND competitor.price_minor IS NOT NULL
		            THEN round(100.0*(competitor.price_minor-own.current_price_minor)/own.current_price_minor,2) END AS "priceGapPct",
		       competitor.currency_code AS "currencyCode", competitor.availability_state AS availability,
		       competitor.observed_at AS "lastUpdated", competitor.match_confidence AS confidence,
		       competitor.match_status AS status, competitor.freshness,
		       competitor.first_exclusion_reason AS "firstExclusionReason",
		       CASE
		        WHEN NOT competitor.bound_eligible THEN 'Unavailable'
		        WHEN own.current_price_minor::numeric > competitor.price_minor::numeric * `+aboveMarketFactor+`
		          THEN 'Validate targeted reduction'
		        WHEN own.current_price_minor::numeric < competitor.price_minor::numeric * `+belowMarketFactor+`
		          THEN 'Hold / monitor'
		        ELSE 'No action'
		       END AS "recommendedResponse",
		       own.details->>'product_name' AS "ourProduct",
		       competitor.details
		FROM retail_serving.pricing_competitor_assessments AS competitor
		JOIN LATERAL (
		 SELECT recommendation.current_price_minor, recommendation.details
		 FROM retail_serving.price_recommendations AS recommendation
		 WHERE `+strings.Join(ownClauses, " AND ")+`
		 ORDER BY recommendation.store_id, recommendation.channel_id,
		          recommendation.recommendation_id LIMIT 1
		) AS own ON true
		WHERE `+where+`
		ORDER BY CASE competitor.match_status WHEN 'Needs Review' THEN 0 WHEN 'Matched' THEN 1 WHEN 'Rejected' THEN 2 ELSE 3 END,
		         competitor.match_confidence DESC, competitor.match_id
		LIMIT $`+fmt.Sprint(len(arguments)+1)+` OFFSET $`+fmt.Sprint(len(arguments)+2), listArgs...)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Competitor matches could not be read.", 503)
	}
	items, err := collectMaps(rows)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Competitor matches could not be decoded.", 503)
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live", "authority": s.authority(),
		"items": items, "pagination": map[string]any{"offset": query.Offset, "limit": query.Limit, "total": total},
	}, nil
}

func (s *PricingStore) competitorDetail(ctx context.Context, id string, query PricingQuery) (map[string]any, error) {
	query.MatchID = id
	query.Limit = 1
	query.Offset = 0
	query = normalizePricingQuery(query)
	payload, err := s.competitorMatches(ctx, query)
	if err != nil {
		return nil, err
	}
	items := payload["items"].([]map[string]any)
	if len(items) == 1 {
		return map[string]any{"schemaVersion": PricingPageSchema, "dataMode": "live", "authority": s.authority(), "item": items[0]}, nil
	}
	return nil, pricingError("COMPETITOR_MATCH_NOT_FOUND", "The competitor match is not in the active authority.", 404)
}

func (s *PricingStore) promotionPayload(ctx context.Context, surface string) (map[string]any, error) {
	var detailsRaw []byte
	err := s.pool.QueryRow(ctx, `
		SELECT details FROM retail_serving.pricing_promotion_dispositions WHERE bundle_id=$1
	`, s.bundleID).Scan(&detailsRaw)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Promotion disposition could not be read.", 503)
	}
	var disposition map[string]any
	if err := json.Unmarshal(detailsRaw, &disposition); err != nil {
		return nil, pricingError(PricingReasonRead, "Promotion disposition is invalid.", 503)
	}
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live", "authority": s.authority(),
		"surface": surface, "plannerAvailable": false, "reasonCode": PricingReasonPromotion,
		"message":     "Origin-visible promotion planning evidence is not available.",
		"disposition": disposition, "items": []any{},
	}, nil
}

func (s *PricingStore) alertRules() map[string]any {
	return map[string]any{
		"schemaVersion": PricingPageSchema, "dataMode": "live", "authority": s.authority(),
		"available": false, "reasonCode": "ALERT_WORKFLOW_UNAVAILABLE",
		"message": "Persisted competitor alert rules are not available.", "items": []any{},
	}
}

func numberFromDetails(details map[string]any, key string) (float64, bool) {
	value, ok := details[key]
	if !ok || value == nil {
		return 0, false
	}
	switch typed := value.(type) {
	case float64:
		return typed, true
	case json.Number:
		number, err := typed.Float64()
		return number, err == nil
	case string:
		var number float64
		_, err := fmt.Sscan(typed, &number)
		return number, err == nil
	default:
		return 0, false
	}
}

func booleanFromDetails(details map[string]any, key string) (bool, bool) {
	value, ok := details[key]
	if !ok || value == nil {
		return false, false
	}
	switch typed := value.(type) {
	case bool:
		return typed, true
	case float64:
		if typed == 0 || typed == 1 {
			return typed == 1, true
		}
	case json.Number:
		if typed == "0" || typed == "1" {
			return typed == "1", true
		}
	case string:
		if typed == "false" || typed == "true" || typed == "0" || typed == "1" {
			return typed == "true" || typed == "1", true
		}
	}
	return false, false
}

func roundedMinor(value float64) int64 {
	return int64(math.RoundToEven(value))
}

// minMarginFloorPct returns the configured minimum-margin floor (percent) from the
// active bundle's priceMargin capability, or 0 when it is absent/unparseable.
func (s *PricingStore) minMarginFloorPct() float64 {
	pm, ok := s.capabilities["priceMargin"].(map[string]any)
	if !ok {
		return 0
	}
	raw, ok := pm["minMarginPct"].(string)
	if !ok {
		return 0
	}
	value, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return 0
	}
	return value
}

// marginProtectionRefusal returns the pricing error that Margin Protection must raise
// for a proposed price on the given cost basis, or nil when the price satisfies the
// minimum-margin floor. Evaluated on the weighted-average cost basis (plan §0.0), this
// is the single source of the public COST_MISSING / MARGIN_BELOW_FLOOR refusal contract
// and is callable (and unit-testable) without a database.
func marginProtectionRefusal(proposedPriceMinor int64, marginCost, floorPct float64, costAvailable bool) error {
	if !costAvailable {
		return pricingError("COST_MISSING", "Margin Protection needs a cost basis to evaluate the floor.", 422)
	}
	if floorPct <= 0 || proposedPriceMinor <= 0 {
		return nil
	}
	marginPct := 100.0 * (float64(proposedPriceMinor) - marginCost) / float64(proposedPriceMinor)
	if marginPct < floorPct {
		return pricingError("MARGIN_BELOW_FLOOR", fmt.Sprintf("Proposed price margin %.2f%% is below the %.2f%% minimum-margin floor.", marginPct, floorPct), 422)
	}
	return nil
}

func (s *PricingStore) RunSimulation(ctx context.Context, request PriceSimulationRequest) (map[string]any, error) {
	if !s.Available() {
		return nil, s.unavailableError()
	}
	if request.ExpectedActivationSetID != s.activationSetID {
		return nil, pricingError(PricingReasonStale, "The pricing authority changed; refresh before simulating.", 409)
	}
	if request.SimulationPeriod != "Next 4 Weeks" ||
		(request.DemandAssumption != "Expected" && request.DemandAssumption != "Best Case" && request.DemandAssumption != "Worst Case") ||
		(request.InventoryObjective != "Margin Protection" && request.InventoryObjective != "Clearance") {
		return nil, pricingError("SIMULATION_REQUEST_INVALID", "The scenario options do not match the supported contract.", 422)
	}
	var market, sku, store, channel, currency, recordKind string
	var current, optimal int64
	var confidence float64
	var detailsRaw []byte
	err := s.pool.QueryRow(ctx, `
		SELECT market_id,sku_id,store_id,channel_id,currency_code,record_kind,
		       current_price_minor,proposed_price_minor,confidence,details
		FROM retail_serving.price_recommendations
		WHERE bundle_id=$1 AND recommendation_id=$2
	`, s.bundleID, request.RecommendationID).Scan(&market, &sku, &store, &channel, &currency, &recordKind, &current, &optimal, &confidence, &detailsRaw)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, pricingError("RECOMMENDATION_NOT_FOUND", "The selected recommendation is not active.", 404)
	}
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Simulation evidence could not be read.", 503)
	}
	if recordKind != "recommendation" {
		return nil, pricingError("MISSING_ACCEPTED_RESPONSE", "A withheld assessment cannot be simulated.", 422)
	}
	var eligible bool
	var proposedUnits, proposedRevenue float64
	err = s.pool.QueryRow(ctx, `
		SELECT eligible,expected_units,expected_revenue_minor
		FROM retail_serving.pricing_price_candidates
		WHERE bundle_id=$1 AND market_id=$2 AND sku_id=$3 AND store_id=$4
		  AND channel_id=$5 AND candidate_price_minor=$6
	`, s.bundleID, market, sku, store, channel, request.ProposedPriceMinor).Scan(&eligible, &proposedUnits, &proposedRevenue)
	if errors.Is(err, pgx.ErrNoRows) || !eligible {
		return nil, pricingError("PROPOSED_PRICE_OUTSIDE_GUARDRAIL", "Proposed price is off-grid, unsupported, or outside its change cap.", 422)
	}
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Simulation candidates could not be read.", 503)
	}
	var responseRaw []byte
	err = s.pool.QueryRow(ctx, `
		SELECT assessment FROM retail_serving.pricing_response_assessments
		WHERE bundle_id=$1 AND market_id=$2 AND sku_id=$3 AND store_id=$4 AND channel_id=$5
	`, s.bundleID, market, sku, store, channel).Scan(&responseRaw)
	if err != nil {
		return nil, pricingError(PricingReasonRead, "Accepted response evidence could not be read.", 503)
	}
	var details, response map[string]any
	if json.Unmarshal(detailsRaw, &details) != nil || json.Unmarshal(responseRaw, &response) != nil {
		return nil, pricingError(PricingReasonRead, "Simulation evidence is invalid.", 503)
	}
	if details["forecast_scenario_semantics"] != PricingForecastScenarioSemantics {
		return nil, pricingError(
			"FORECAST_SCENARIO_SEMANTICS_INVALID",
			"Four-week demand assumptions lack the approved planning-bound semantics.",
			422,
		)
	}
	if request.InventoryObjective == "Margin Protection" && !s.priceMarginActive {
		return nil, pricingError("PRICE_MARGIN_NOT_ACTIVE", "Margin Protection requires an active margin capability (an accepted cost basis).", 422)
	}
	if available, _ := booleanFromDetails(details, "clearance_context_available"); !available {
		return nil, pricingError("INVENTORY_CONTEXT_UNAVAILABLE", "Clearance requires accepted ageing and inventory evidence.", 422)
	}
	demandKey := map[string]string{"Expected": "forecast_expected_units", "Best Case": "forecast_best_case_units", "Worst Case": "forecast_worst_case_units"}[request.DemandAssumption]
	baseUnits, ok := numberFromDetails(details, demandKey)
	if !ok {
		return nil, pricingError("FORECAST_SCENARIO_UNAVAILABLE", request.DemandAssumption+" forecast evidence is unavailable.", 422)
	}
	beta, ok := numberFromDetails(response, "shrunk_beta")
	if !ok {
		return nil, pricingError("MISSING_ACCEPTED_RESPONSE", "The accepted response coefficient is unavailable.", 422)
	}
	atp, atpAvailable := numberFromDetails(details, "atp_units")
	// PoC cost-of-record: the generated weighted-average cost IS the authoritative
	// unit cost (no separate client cost exists in this PoC), so the primary Gross
	// Margin is computed from it. A client-actual cost is preferred only if one is
	// ever supplied. See the PoC cost-model note in the implementation plan.
	marginCost, costAvailable := numberFromDetails(details, "client_actual_cost_minor")
	if !costAvailable {
		marginCost, costAvailable = numberFromDetails(details, "synthetic_cost_minor")
	}
	// Margin Protection enforces the minimum-margin floor on the proposed price,
	// evaluated on the weighted-average cost basis (plan §0.0): a proposed price whose
	// margin falls below the configured floor is refused — that refusal is the protection.
	if request.InventoryObjective == "Margin Protection" {
		if refusal := marginProtectionRefusal(request.ProposedPriceMinor, marginCost, s.minMarginFloorPct(), costAvailable); refusal != nil {
			return nil, refusal
		}
	}
	scenario := func(price int64) map[string]any {
		units := baseUnits * math.Pow(float64(price)/float64(current), beta)
		revenue := roundedMinor(units * float64(price))
		var ending any
		if atpAvailable {
			ending = atp - units
		}
		var grossMargin any
		var grossMarginReason any = "COST_MISSING"
		if costAvailable {
			grossMargin = roundedMinor(units * (float64(price) - marginCost))
			grossMarginReason = nil
		}
		return map[string]any{"priceMinor": price, "units": units, "revenueMinor": revenue, "grossMarginMinor": grossMargin, "grossMarginReasonCode": grossMarginReason, "endingStockUnits": ending}
	}
	currentResult := scenario(current)
	proposedResult := scenario(request.ProposedPriceMinor)
	optimalResult := scenario(optimal)
	if request.DemandAssumption == "Expected" {
		computedUnits := proposedResult["units"].(float64)
		computedRevenue := proposedResult["revenueMinor"].(int64)
		unitTolerance := math.Max(1e-8, math.Abs(proposedUnits)*1e-10)
		if math.Abs(computedUnits-proposedUnits) > unitTolerance ||
			computedRevenue != roundedMinor(proposedRevenue) {
			return nil, pricingError(
				"SIMULATION_CANDIDATE_DRIFT",
				"The stored candidate no longer reconciles with the simulation formula.",
				503,
			)
		}
	}
	var marginImpact any
	var marginImpactReason any = "COST_MISSING"
	if costAvailable {
		marginImpact = proposedResult["grossMarginMinor"].(int64) - currentResult["grossMarginMinor"].(int64)
		marginImpactReason = nil
	}
	competitorIncluded := details["competitor_price_minor"] != nil
	stockRisk := "Unavailable"
	if ending, ok := proposedResult["endingStockUnits"].(float64); ok {
		if ending < 0 {
			stockRisk = "High"
		} else {
			stockRisk = "Low"
		}
	}
	return map[string]any{
		"schemaVersion": "retail-price-simulation/v1",
		"scope":         map[string]any{"market_id": market, "sku_id": sku, "store_id": store, "channel_id": channel},
		"currencyCode":  currency, "simulationPeriod": "Next 4 Weeks", "demandAssumption": request.DemandAssumption, "inventoryObjective": request.InventoryObjective,
		"demandScenarioSemantics": PricingForecastScenarioSemantics,
		"columns":                 map[string]any{"current": currentResult, "proposed": proposedResult, "aiOptimal": optimalResult},
		"metricOrder":             []string{"Units", "Revenue", "Gross Margin", "Ending Stock"},
		"recommendation":          map[string]any{"priceMinor": optimal, "revenueImpactMinor": proposedResult["revenueMinor"].(int64) - currentResult["revenueMinor"].(int64), "marginImpactMinor": marginImpact, "marginReasonCode": marginImpactReason, "stockOutRisk": stockRisk, "confidence": confidence},
		"competitorEvidence": map[string]any{"included": competitorIncluded, "reasonCode": func() any {
			if competitorIncluded {
				return nil
			}
			return "COMPETITOR_BOUND_UNAVAILABLE"
		}()},
		"mutated": false,
	}, nil
}

func (s *PricingStore) Read(ctx context.Context, path string, query PricingQuery) (map[string]any, error) {
	if !s.Available() {
		return nil, s.unavailableError()
	}
	switch path {
	case "/api/v1/pricing/recommendations/summary":
		return s.recommendationSummary(ctx, query)
	case "/api/v1/pricing/recommendations":
		return s.recommendations(ctx, query)
	case "/api/v1/pricing/recommendations/store-view":
		return s.groupedRecommendations(ctx, "store", query)
	case "/api/v1/pricing/recommendations/category-view":
		return s.groupedRecommendations(ctx, "category", query)
	case "/api/v1/pricing/recommendations/governance":
		return s.governance(ctx, query)
	case "/api/v1/competitors/summary":
		return s.competitorSummary(ctx, query)
	case "/api/v1/competitors/matches":
		return s.competitorMatches(ctx, query)
	case "/api/v1/competitors/alert-rules":
		return s.alertRules(), nil
	case "/api/v1/promotions/summary":
		return s.promotionPayload(ctx, "summary")
	case "/api/v1/promotions/opportunities":
		return s.promotionPayload(ctx, "opportunities")
	case "/api/v1/promotions/portfolio":
		return s.promotionPayload(ctx, "portfolio")
	case "/api/v1/promotions/calendar":
		return s.promotionPayload(ctx, "calendar")
	default:
		return nil, pricingError("PRICING_ROUTE_UNKNOWN", "The pricing route is not registered.", 404)
	}
}

func (s *PricingStore) Detail(ctx context.Context, kind, id string, query PricingQuery) (map[string]any, error) {
	if !s.Available() {
		return nil, s.unavailableError()
	}
	if kind == "recommendation" {
		return s.recommendationDetail(ctx, id)
	}
	if kind == "competitor" {
		return s.competitorDetail(ctx, id, query)
	}
	return nil, pricingError("PRICING_DETAIL_UNKNOWN", "The pricing detail route is not registered.", 404)
}
