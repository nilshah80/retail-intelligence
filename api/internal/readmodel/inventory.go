// Package readmodel: the inventory/replenishment PostgreSQL read model (P4-8).
//
// Same posture as the forecast store, because the posture is the product: Go
// reads PostgreSQL only, startup proves the GLOBAL active count before applying
// any configuration, every request revalidates the activation AND the forecast
// authority it consumed, and every unavailable state is a governed reason code
// rather than an empty 200.
package readmodel

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	InventoryUnavailableSchema = "retail-inventory-unavailable/v1"
	// The serving schema this read model was written against. Pinned like the
	// forecast pin and covered by the same cross-file regression: the pins move
	// together or the gate stops.
	InventoryMigrationRevision = "0010_inventory_serving"

	InventoryReasonUnmaterialized = "INVENTORY_READ_MODEL_UNAVAILABLE"
	InventoryReasonInvalid        = "INVENTORY_ARTIFACT_INVALID"
	InventoryReasonLineage        = "INVENTORY_LINEAGE_MISMATCH"
	// The inventory bundle consumed a forecast that is no longer the active
	// authority. Maps to 409: an activated version exists, and it is stale.
	InventoryReasonForecastSuperseded = "INVENTORY_FORECAST_SUPERSEDED"

	// A page is a shortlist to act on, not a data dump. Every one of these
	// projections holds thousands of cells, and a hundred rows of alphabetically
	// ordered SKUs is a scroll, not an answer -- the buyer wants the twenty that
	// cost the most to ignore. Each route therefore declares a materiality order
	// (see inventoryRanking) and the page is cut to the top of it.
	//
	// The scoped total still rides in `pagination.total` and every KPI is
	// aggregated over the whole active version in SQL, so a capped page can never
	// be mistaken for the whole set.
	DefaultInventoryPageSize = 20
)

type InventoryReadError struct {
	reasonCode string
	message    string
}

func (e *InventoryReadError) Error() string { return e.message }

func inventoryReadError(reasonCode, message string) error {
	return &InventoryReadError{reasonCode: reasonCode, message: message}
}

func InventoryReadErrorReason(err error) string {
	var typed *InventoryReadError
	if errors.As(err, &typed) {
		return typed.reasonCode
	}
	return InventoryReasonUnmaterialized
}

type InventoryConfig struct {
	PostgresDSN string
	DBReadPool  int
}

type InventoryStore struct {
	pool                *pgxpool.Pool
	reasonCode          string
	message             string
	inventoryVersionID  string
	inventoryRunID      string
	semanticFingerprint string
	forecastRunID       string
	forecastVersionID   string
	policyVersion       string
	markets             []string
	decisionAsOf        time.Time
}

func unavailableInventory(reasonCode, message string) *InventoryStore {
	return &InventoryStore{reasonCode: reasonCode, message: message}
}

// LoadInventory opens only the PostgreSQL projection produced by the offline
// verifier/materializer. There is deliberately no configured version id: the
// P4-D15 scope is the whole product surface with one active version total, so
// the projection itself is the authority and configuration has nothing to
// select — and therefore nothing to hide.
func LoadInventory(ctx context.Context, config InventoryConfig) *InventoryStore {
	if config.PostgresDSN == "" {
		return unavailableInventory(
			InventoryReasonUnmaterialized,
			"No PostgreSQL inventory projection is configured.",
		)
	}
	poolConfig, err := pgxpool.ParseConfig(config.PostgresDSN)
	if err != nil {
		return unavailableInventory(
			InventoryReasonInvalid,
			"The PostgreSQL inventory configuration is invalid.",
		)
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
		return unavailableInventory(
			InventoryReasonUnmaterialized,
			"The PostgreSQL inventory projection is unavailable.",
		)
	}
	var migration string
	if err := pool.QueryRow(
		ctx, "SELECT version_num FROM retail_intelligence_alembic_version",
	).Scan(&migration); err != nil {
		pool.Close()
		return unavailableInventory(
			InventoryReasonUnmaterialized,
			"The PostgreSQL inventory schema could not be verified.",
		)
	}
	if migration != InventoryMigrationRevision {
		pool.Close()
		return unavailableInventory(
			InventoryReasonInvalid,
			"The PostgreSQL inventory schema is not at the required migration.",
		)
	}
	var active int
	if err := pool.QueryRow(
		ctx, "SELECT count(*) FROM retail_serving.active_inventory_versions",
	).Scan(&active); err != nil {
		pool.Close()
		return unavailableInventory(
			InventoryReasonUnmaterialized,
			"The active inventory version count could not be verified.",
		)
	}
	if active == 0 {
		pool.Close()
		return unavailableInventory(
			InventoryReasonUnmaterialized,
			"No accepted inventory/replenishment version is active.",
		)
	}
	if active > 1 {
		pool.Close()
		return unavailableInventory(
			InventoryReasonInvalid,
			"More than one inventory version is active; serving fails closed.",
		)
	}
	var store InventoryStore
	store.pool = pool
	if err := pool.QueryRow(
		ctx,
		`SELECT inventory_version_id, inventory_run_id,
		        run_semantic_fingerprint, forecast_run_id, forecast_version_id,
		        policy_version, markets, decision_as_of
		 FROM retail_serving.active_inventory_versions`,
	).Scan(
		&store.inventoryVersionID,
		&store.inventoryRunID,
		&store.semanticFingerprint,
		&store.forecastRunID,
		&store.forecastVersionID,
		&store.policyVersion,
		&store.markets,
		&store.decisionAsOf,
	); err != nil {
		pool.Close()
		return unavailableInventory(
			InventoryReasonUnmaterialized,
			"The active inventory projection failed verification.",
		)
	}
	return &store
}

func (s *InventoryStore) Close() {
	if s != nil && s.pool != nil {
		s.pool.Close()
	}
}

func (s *InventoryStore) Available() bool {
	return s != nil && s.pool != nil
}

func (s *InventoryStore) UnavailableReason() string {
	if s == nil || s.reasonCode == "" {
		return InventoryReasonUnmaterialized
	}
	return s.reasonCode
}

func (s *InventoryStore) Unavailable() map[string]any {
	message := ""
	if s != nil {
		message = s.message
	}
	if message == "" {
		message = "The PostgreSQL inventory projection is unavailable."
	}
	return map[string]any{
		"schemaVersion":       InventoryUnavailableSchema,
		"dataMode":            "unavailable",
		"inventoryRunId":      nil,
		"inventoryVersionId":  nil,
		"semanticFingerprint": nil,
		"reasonCode":          s.UnavailableReason(),
		"message":             message,
		"capabilities": map[string]any{
			"inventoryReplenishmentCurrentSnapshot": map[string]any{
				"available": false, "reasonCode": s.UnavailableReason(),
			},
			"inventoryReplenishmentReplay": map[string]any{
				"available": false, "reasonCode": s.UnavailableReason(),
			},
		},
	}
}

type InventoryQuery struct {
	MarketID string
	StoreID  string
	Category string
	Search   string
	Offset   int
	Limit    int
}

//nolint:gocyclo // one switch over fifteen routes reads better than a registry.
func (s *InventoryStore) Read(
	ctx context.Context, path string, query InventoryQuery,
) (map[string]any, error) {
	if !s.Available() {
		return nil, errors.New("inventory store is unavailable")
	}
	// Two facts per request, like the forecast store: the global activation is
	// still unique AND this version's consumed forecast is still THE active
	// forecast. The second is what turns a superseded forecast into a governed
	// 409 rather than a quietly stale screen.
	var activeCount int
	var stillCurrent bool
	if err := s.pool.QueryRow(
		ctx,
		`SELECT
			(SELECT count(*) FROM retail_serving.active_inventory_versions),
			EXISTS (
				SELECT 1 FROM retail_serving.active_inventory_versions
				WHERE inventory_version_id = $1
				  AND forecast_run_id = $2
				  AND forecast_version_id = $3
			)`,
		s.inventoryVersionID, s.forecastRunID, s.forecastVersionID,
	).Scan(&activeCount, &stillCurrent); err != nil {
		return nil, inventoryReadError(
			InventoryReasonUnmaterialized,
			"inventory activation could not be revalidated",
		)
	}
	if activeCount != 1 {
		return nil, inventoryReadError(
			InventoryReasonInvalid,
			"inventory authority is not unique",
		)
	}
	if !stillCurrent {
		return nil, inventoryReadError(
			InventoryReasonForecastSuperseded,
			"the active inventory version consumed a forecast that is no "+
				"longer the active authority",
		)
	}
	if query.Limit < 1 || query.Limit > 1000 {
		query.Limit = DefaultInventoryPageSize
	}
	if query.Offset < 0 {
		query.Offset = 0
	}
	switch path {
	case "/api/v1/inventory/versions":
		return s.versions(), nil
	case "/api/v1/inventory/overview":
		return s.tableSlice(ctx, query, "inventory_positions",
			"market_id, location_id, location_kind, sku_id, on_hand_units, "+
				"committed_units, reserved_units, damaged_units, on_order_units, "+
				"in_transit_units, atp_units, assortment_active, residual_only",
			rankByPosition)
	case "/api/v1/inventory/stores":
		return s.tableSlice(ctx, query, "inventory_positions",
			"market_id, location_id, location_kind, sku_id, on_hand_units, "+
				"atp_units, in_transit_units, assortment_active, residual_only",
			rankByPosition,
			"location_kind = 'store'")
	case "/api/v1/inventory/warehouses":
		return s.tableSlice(ctx, query, "inventory_positions",
			// residual_only drives the reference's Action column. It was absent
			// from this route's projection alone, so every warehouse row showed
			// a blank action while the same column filled on every other screen.
			"market_id, location_id, location_kind, sku_id, on_hand_units, "+
				"committed_units, damaged_units, atp_units, on_order_units, "+
				"residual_only",
			rankByPosition,
			"location_kind IN ('dc', '3pl')")
	case "/api/v1/inventory/ageing":
		return s.tableSlice(ctx, query, "inventory_ageing",
			"market_id, location_id, sku_id, age_bucket, on_hand_units, "+
				"action, markdown_pct, residual_only",
			rankByAge)
	case "/api/v1/inventory/transfers":
		return s.tableSlice(ctx, query, "replenishment_transfers",
			"market_id, lane_id, from_location_id, to_location_id, sku_id, "+
				"units, expected_benefit_minor, currency_code, transit_days",
			rankByBenefit)
	case "/api/v1/inventory/valuation":
		return s.tableSlice(ctx, query, "inventory_valuation",
			"market_id, location_id, category, gross_value_minor, "+
				"currency_code, cost_method, cost_reason_code, wms_variance_units",
			rankByValue)
	case "/api/v1/inventory/expiry-waste":
		return s.tableSlice(ctx, query, "inventory_expiry_waste",
			"market_id, location_id, sku_id, expiring_units, expired_units, "+
				"waste_units, exposure_minor, currency_code",
			rankByExposure)
	case "/api/v1/inventory/stock-health":
		return s.tableSlice(ctx, query, "inventory_stock_health",
			"market_id, location_id, sku_id, health_class, cover_days, reason_code",
			rankByHealth)
	case "/api/v1/replenishment/planner", "/api/v1/replenishment/orders":
		return s.tableSlice(ctx, query, "replenishment_recommendations",
			"market_id, destination_location_id, supply_location_id, sku_id, "+
				"recommended_units, reorder_point_units, order_up_to_units, "+
				"interval_available, reason_code, erp_status",
			rankByRecommendation)
	case "/api/v1/replenishment/suppliers":
		return s.tableSlice(ctx, query, "replenishment_suppliers",
			"market_id, supplier_id, otd_rate, lead_time_mean_days, "+
				"lead_time_std_days, capacity_confirmed_pct, risk_class, reason_codes",
			rankBySupplierRisk)
	case "/api/v1/replenishment/safety-stock":
		return s.tableSlice(ctx, query, "replenishment_safety_stock",
			"market_id, location_id, sku_id, abc_class, service_level, "+
				"safety_stock_units, interval_available, reason_code",
			rankByBuffer)
	case "/api/v1/replenishment/allocations":
		return s.tableSlice(ctx, query, "replenishment_allocations",
			"market_id, location_id, channel_id, sku_id, requested_units, "+
				"allocated_units, shortfall_units",
			rankByShortfall)
	case "/api/v1/replenishment/exceptions":
		return s.tableSlice(ctx, query, "replenishment_exceptions",
			"market_id, location_id, sku_id, channel_id, exception_class, "+
				"severity, reason_code, evidence",
			rankBySeverity)
	}
	return nil, inventoryReadError(
		InventoryReasonInvalid, fmt.Sprintf("unknown inventory path %s", path),
	)
}

func (s *InventoryStore) envelope(schemaVersion string) map[string]any {
	return map[string]any{
		"schemaVersion":       schemaVersion,
		"dataMode":            "live",
		"inventoryRunId":      s.inventoryRunID,
		"inventoryVersionId":  s.inventoryVersionID,
		"semanticFingerprint": s.semanticFingerprint,
		"forecastAuthority": map[string]any{
			"forecastRunId":     s.forecastRunID,
			"forecastVersionId": s.forecastVersionID,
		},
		"policyVersion": s.policyVersion,
		"markets":       append([]string(nil), s.markets...),
	}
}

func (s *InventoryStore) versions() map[string]any {
	payload := s.envelope("retail-inventory-versions/v1")
	payload["items"] = []map[string]any{{
		"inventoryVersionId": s.inventoryVersionID,
		"inventoryRunId":     s.inventoryRunID,
		"decisionAsOf":       s.decisionAsOf.UTC().Format(time.RFC3339Nano),
	}}
	return payload
}

// tableSlice serves one projection with market/search scope applied in SQL —
// never after an unbounded read (P4-8 task 11).
func (s *InventoryStore) tableSlice(
	ctx context.Context,
	query InventoryQuery,
	table string,
	columns string,
	ranking inventoryRanking,
	extraClauses ...string,
) (map[string]any, error) {
	filters := []inventoryFilter{}
	if query.MarketID != "" {
		filters = append(filters, inventoryFilter{"market_id", "=", query.MarketID})
	}
	if query.StoreID != "" {
		filters = append(filters, inventoryFilter{"location_id", "=", query.StoreID})
	}
	if query.Category != "" {
		filters = append(filters, inventoryFilter{"category", "=", query.Category})
	}
	if query.Search != "" {
		filters = append(filters,
			inventoryFilter{"sku_id", "ILIKE", "%" + query.Search + "%"})
	}
	clauses, args := s.scope(table, filters, extraClauses)
	args = append(args, query.Limit, query.Offset)
	statement := fmt.Sprintf(
		`SELECT COUNT(*) OVER(), %s FROM retail_serving.%s
		 WHERE %s ORDER BY %s LIMIT $%d OFFSET $%d`,
		columns, table, strings.Join(clauses, " AND "), ranking.orderBy,
		len(args)-1, len(args),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	fields := rows.FieldDescriptions()
	items := make([]map[string]any, 0, query.Limit)
	var total int64
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, err
		}
		total, _ = values[0].(int64)
		item := make(map[string]any, len(fields)-1)
		for index := 1; index < len(fields); index++ {
			item[snakeToCamel(string(fields[index].Name))] = values[index]
		}
		items = append(items, item)
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	payload := s.envelope("retail-inventory-" + strings.ReplaceAll(table, "_", "-") + "/v1")
	payload["items"] = items
	payload["pagination"] = map[string]any{
		"offset": query.Offset, "limit": query.Limit, "total": total,
	}
	// What the page was cut to, in the words the screen shows. Without it a
	// twenty-row table is indistinguishable from the whole population, and a
	// buyer cannot tell whether the rows are the worst offenders or the first
	// twenty SKU codes in the alphabet.
	payload["ranking"] = ranking.criterion
	// KPI tiles are aggregated HERE, in SQL, over every scoped row of the active
	// version -- not client-side over the returned page. Summing 100 of 4,741 rows
	// in the browser and rendering the result as "On-Hand Inventory" would be a
	// fabricated total, which is the one thing these screens must never show. The
	// aggregate reuses the same clauses and args as the page query above, so a
	// filter can never apply to the table and not to the tiles above it.
	summary, err := s.aggregate(ctx, table, clauses, args[:len(args)-2])
	if err != nil {
		return nil, err
	}
	if summary != nil {
		// A dashboard screen shows figures from more than one projection -- the
		// reference's Inventory Overview carries a health mix beside its position
		// breakdown. Those are merged under a prefix rather than fetched by a second
		// browser request, so one scope is applied once and the tiles cannot
		// disagree with the table beneath them.
		for _, related := range dashboardCompanions[table] {
			// Re-rendered against the companion's OWN columns rather than reusing
			// the page's clause list: a filter the companion cannot express must
			// drop its placeholder AND its argument together, and dropping only
			// the clause leaves the argument behind for pgx to reject.
			companionClauses, companionArgs := s.scope(related.table, filters, nil)
			companion, err := s.aggregate(
				ctx, related.table, companionClauses, companionArgs,
			)
			if err != nil {
				return nil, err
			}
			for name, value := range companion {
				summary[related.prefix+strings.ToUpper(name[:1])+name[1:]] = value
			}
		}
		payload["summary"] = summary
	}
	return payload, nil
}

// inventoryRanking is how one route decides which rows make the page, and the
// sentence the screen shows so a reader knows what "top 20" means here.
//
// Every order ends in the projection's key columns. Without that tiebreak two
// rows with equal materiality can swap between requests and the same row appears
// on page one and page two, or on neither.
type inventoryRanking struct {
	orderBy   string
	criterion string
}

// Ordered by what it costs to ignore the row -- oldest stock, deepest shortfall,
// worst health, largest benefit -- never by identifier. Alphabetical order by SKU
// is what every one of these routes did before, which put "NST-IN-AAA-001" at the
// top of a stockout list for no reason other than its name.
var (
	rankByPosition = inventoryRanking{
		orderBy:   "on_hand_units DESC, market_id, location_id, sku_id",
		criterion: "the largest positions by units on hand",
	}
	rankByAge = inventoryRanking{
		orderBy: `CASE age_bucket WHEN '180-plus' THEN 0 WHEN '90-180' THEN 1
			WHEN '60-90' THEN 2 WHEN '30-60' THEN 3 ELSE 4 END,
			on_hand_units DESC, market_id, location_id, sku_id`,
		criterion: "the oldest stock first, then the largest quantity held",
	}
	rankByBenefit = inventoryRanking{
		orderBy: "expected_benefit_minor DESC NULLS LAST, units DESC, " +
			"market_id, lane_id, sku_id",
		criterion: "the highest expected benefit per transfer",
	}
	rankByValue = inventoryRanking{
		orderBy:   "gross_value_minor DESC NULLS LAST, market_id, location_id, category",
		criterion: "the highest gross inventory value",
	}
	rankByExposure = inventoryRanking{
		orderBy: "exposure_minor DESC NULLS LAST, expiring_units DESC, " +
			"market_id, location_id, sku_id",
		criterion: "the largest financial exposure to expiry and waste",
	}
	rankByHealth = inventoryRanking{
		orderBy: `CASE health_class WHEN 'stockout' THEN 0 WHEN 'understock' THEN 1
			WHEN 'dead' THEN 2 WHEN 'overstock' THEN 3 ELSE 4 END,
			cover_days ASC NULLS FIRST, market_id, location_id, sku_id`,
		criterion: "the least healthy cells first, then the thinnest cover",
	}
	rankByRecommendation = inventoryRanking{
		orderBy:   "recommended_units DESC, market_id, destination_location_id, sku_id",
		criterion: "the largest recommended order quantity",
	}
	rankBySupplierRisk = inventoryRanking{
		orderBy: `CASE risk_class WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
			otd_rate ASC NULLS FIRST, market_id, supplier_id`,
		criterion: "the highest supplier risk, then the worst on-time delivery",
	}
	rankByBuffer = inventoryRanking{
		orderBy: `CASE abc_class WHEN 'A' THEN 0 WHEN 'B' THEN 1 ELSE 2 END,
			safety_stock_units DESC, market_id, location_id, sku_id`,
		criterion: "class A first, then the largest safety buffer",
	}
	rankByShortfall = inventoryRanking{
		orderBy: "shortfall_units DESC, requested_units DESC, " +
			"market_id, location_id, channel_id, sku_id",
		criterion: "the largest unmet allocation shortfall",
	}
	rankBySeverity = inventoryRanking{
		orderBy: `CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1
			WHEN 'info' THEN 2 ELSE 3 END, exception_class, market_id, location_id, sku_id`,
		criterion: "the most severe exceptions first",
	}
)

// A companion projection whose aggregates a dashboard screen also needs.
type dashboardCompanion struct {
	table  string
	prefix string
}

// A screen shows what its own projection measures plus whatever its reference
// card asks for from elsewhere -- the overview's health mix, the money behind a
// caption that says "Value", the transfer opportunity a store screen quotes. Each
// companion is one extra aggregate on the same scope, merged under a prefix, so
// the alternative is a second browser request that could disagree with the first.
//
// Every entry here removed an unavailable tile. `valuation` is why "Store
// Inventory Value" reports money rather than a unit count under a money caption.
var dashboardCompanions = map[string][]dashboardCompanion{
	"inventory_positions": {
		{table: "inventory_stock_health", prefix: "health"},
		{table: "inventory_valuation_by_kind", prefix: "valuation"},
		{table: "replenishment_transfers", prefix: "transfer"},
	},
	"inventory_ageing": {
		{table: "replenishment_transfers", prefix: "transfer"},
		{table: "inventory_valuation", prefix: "valuation"},
	},
	"replenishment_recommendations": {
		{table: "inventory_valuation", prefix: "valuation"},
		{table: "replenishment_suppliers", prefix: "supplier"},
	},
	"replenishment_safety_stock": {
		{table: "inventory_valuation", prefix: "valuation"},
	},
	"replenishment_suppliers": {
		{table: "replenishment_recommendations", prefix: "order"},
	},
	"replenishment_exceptions": {
		{table: "replenishment_recommendations", prefix: "order"},
	},
}

// One request-scope predicate, before it knows which table it will be rendered
// against. Kept as data rather than as SQL text so a table that cannot express it
// drops the clause and its argument as one thing.
type inventoryFilter struct {
	column   string
	operator string
	value    any
}

// filterableColumns is what each projection can actually be scoped by. Declared
// rather than probed: the projections are written by one frozen column contract
// (`ARTIFACT_COLUMNS`), and a table quietly losing a column should fail a schema
// test, not silently widen a companion aggregate to the whole market.
var filterableColumns = map[string]map[string]bool{
	"inventory_positions":           {"market_id": true, "location_id": true, "sku_id": true},
	"inventory_stock_health":        {"market_id": true, "location_id": true, "sku_id": true},
	"inventory_demand_at_risk":      {"market_id": true, "location_id": true, "sku_id": true},
	"inventory_ageing":              {"market_id": true, "location_id": true, "sku_id": true},
	"inventory_expiry_waste":        {"market_id": true, "location_id": true, "sku_id": true},
	"inventory_valuation":           {"market_id": true, "location_id": true, "category": true},
	"inventory_valuation_by_kind":   {"market_id": true, "location_id": true, "category": true},
	"replenishment_recommendations": {"market_id": true, "sku_id": true},
	"replenishment_safety_stock":    {"market_id": true, "location_id": true, "sku_id": true},
	"replenishment_transfers":       {"market_id": true, "sku_id": true},
	"replenishment_allocations":     {"market_id": true, "location_id": true, "sku_id": true},
	"replenishment_suppliers":       {"market_id": true},
	"replenishment_exceptions":      {"market_id": true, "location_id": true, "sku_id": true},
}

// scope renders the version clause, whichever filters this table can express, and
// any caller-supplied static clauses into matching SQL and arguments. The version
// clause is never optional: it is what binds a row to the one active authority.
func (s *InventoryStore) scope(
	table string, filters []inventoryFilter, static []string,
) ([]string, []any) {
	clauses := []string{"inventory_version_id = $1"}
	args := []any{s.inventoryVersionID}
	clauses = append(clauses, static...)
	columns := filterableColumns[table]
	for _, filter := range filters {
		if !columns[filter.column] {
			continue
		}
		args = append(args, filter.value)
		clauses = append(clauses, fmt.Sprintf(
			"%s %s $%d", filter.column, filter.operator, len(args),
		))
	}
	return clauses, args
}

// inventoryAggregates names, per projection table, the KPI expressions its screen
// needs. Keyed by the camelCase field the UI reads. Written as SQL rather than Go
// so the whole active version is reduced in the database.
//
// Money stays in market-local minor units: policy v2 forbids a nominal sum across
// INR and USD, so a caller wanting one figure converts under approved reporting FX
// after this returns. `currencyCount` is published so a consumer can see when a
// money aggregate spans more than one currency and refuse to add it.
var inventoryAggregates = map[string]map[string]string{
	"inventory_positions": {
		"onHandUnits":      "COALESCE(SUM(on_hand_units), 0)",
		"atpUnits":         "COALESCE(SUM(atp_units), 0)",
		"reservedUnits":    "COALESCE(SUM(reserved_units), 0)",
		"storeOnHandUnits": "COALESCE(SUM(on_hand_units) FILTER (WHERE location_kind = 'store'), 0)",
		"dcOnHandUnits":    "COALESCE(SUM(on_hand_units) FILTER (WHERE location_kind = 'dc'), 0)",
		"inTransitUnits":   "COALESCE(SUM(in_transit_units), 0)",
		"onOrderUnits":     "COALESCE(SUM(on_order_units), 0)",
		"committedUnits":   "COALESCE(SUM(committed_units), 0)",
		"damagedUnits":     "COALESCE(SUM(damaged_units), 0)",
		// A real count, not a stand-in. It reads 0 today, and 0 is the answer --
		// rendering "Not available" over a measure the projection can compute
		// tells a retailer the platform cannot see negative inventory when in
		// fact it can see there is none.
		"negativeCells":     "COUNT(*) FILTER (WHERE on_hand_units < 0)",
		"zeroCells":         "COUNT(*) FILTER (WHERE on_hand_units = 0)",
		"cells":             "COUNT(*)",
		"residualOnlyCells": "COUNT(*) FILTER (WHERE residual_only)",
		"activeCells":       "COUNT(*) FILTER (WHERE assortment_active)",
		"storeCells":        "COUNT(*) FILTER (WHERE location_kind = 'store')",
		"dcCells":           "COUNT(*) FILTER (WHERE location_kind = 'dc')",
	},
	"inventory_stock_health": {
		"cells":           "COUNT(*)",
		"healthyCells":    "COUNT(*) FILTER (WHERE health_class = 'healthy')",
		"understockCells": "COUNT(*) FILTER (WHERE health_class = 'understock')",
		"overstockCells":  "COUNT(*) FILTER (WHERE health_class = 'overstock')",
		"stockoutCells":   "COUNT(*) FILTER (WHERE health_class = 'stockout')",
		"deadCells":       "COUNT(*) FILTER (WHERE health_class = 'dead')",
		// The reference's health donut has four slices, and four slices must
		// partition the population or the percentages are a lie. The engine
		// classifies five ways, so "At Risk" carries both kinds of risk: a buffer
		// too thin to serve demand, and stock that has stopped moving. Healthy +
		// at risk + overstock + stockout then sums to the cell count exactly.
		"atRiskCells": "COUNT(*) FILTER (WHERE health_class IN ('understock', 'dead'))",
		// Locations, not cells. "Stores at Risk" is a count of stores, and summing
		// per-SKU risk rows would report 3,698 stores in a two-store market.
		"atRiskLocations": "COUNT(DISTINCT location_id) FILTER " +
			"(WHERE health_class IN ('understock', 'stockout'))",
		"locations":             "COUNT(DISTINCT location_id)",
		"coverUnavailableCells": "COUNT(*) FILTER (WHERE cover_days IS NULL)",
		"meanCoverDays":         "AVG(cover_days)",
	},
	"inventory_demand_at_risk": {
		"cells":          "COUNT(*)",
		"assessedCells":  "COUNT(*) FILTER (WHERE interval_available)",
		"withheldCells":  "COUNT(*) FILTER (WHERE NOT interval_available)",
		"riskUnits":      "COALESCE(SUM(risk_units), 0)",
		"riskValueMinor": "COALESCE(SUM(risk_value_minor), 0)",
		"currencyCount":  "COUNT(DISTINCT currency_code)",
	},
	"inventory_ageing": {
		"cells":         "COUNT(*)",
		"onHandUnits":   "COALESCE(SUM(on_hand_units), 0)",
		"residualUnits": "COALESCE(SUM(on_hand_units) FILTER (WHERE residual_only), 0)",
		"markdownCells": "COUNT(*) FILTER (WHERE action = 'markdown_candidate')",
		// The buckets the engine emits are 0-30, 30-60, 60-90, 90-180, 180-plus.
		// "60+ days" is the union of the last three and "90+ days" of the last
		// two, which is a cumulative sum the projection has always been able to
		// answer -- the screen simply never asked it, and reported the whole
		// ageing tile as unmeasured because a single bucket is not a total.
		"units60Plus": "COALESCE(SUM(on_hand_units) FILTER " +
			"(WHERE age_bucket IN ('60-90', '90-180', '180-plus')), 0)",
		"units90Plus": "COALESCE(SUM(on_hand_units) FILTER " +
			"(WHERE age_bucket IN ('90-180', '180-plus')), 0)",
		"cells60Plus": "COUNT(*) FILTER " +
			"(WHERE age_bucket IN ('60-90', '90-180', '180-plus'))",
	},
	"inventory_expiry_waste": {
		"cells":         "COUNT(*)",
		"expiringUnits": "COALESCE(SUM(expiring_units), 0)",
		"expiredUnits":  "COALESCE(SUM(expired_units), 0)",
		"wasteUnits":    "COALESCE(SUM(waste_units), 0)",
		"exposureMinor": "COALESCE(SUM(exposure_minor), 0)",
		"currencyCount": "COUNT(DISTINCT currency_code)",
	},
	"inventory_valuation_by_kind": {
		"storeValueMinor": "COALESCE(SUM(gross_value_minor) FILTER " +
			"(WHERE location_kind = 'store'), 0)",
		"dcValueMinor": "COALESCE(SUM(gross_value_minor) FILTER " +
			"(WHERE location_kind IN ('dc', '3pl')), 0)",
		"grossValueMinor":  "COALESCE(SUM(gross_value_minor), 0)",
		"wmsVarianceUnits": "COALESCE(SUM(wms_variance_units), 0)",
		"currencyCount":    "COUNT(DISTINCT currency_code)",
		"unvaluedRows":     "COUNT(*) FILTER (WHERE gross_value_minor IS NULL)",
	},
	"inventory_valuation": {
		"negativeValueRows": "COUNT(*) FILTER (WHERE gross_value_minor < 0)",
		"rows":              "COUNT(*)",
		"grossValueMinor":   "COALESCE(SUM(gross_value_minor), 0)",
		"unvaluedRows":      "COUNT(*) FILTER (WHERE gross_value_minor IS NULL)",
		"wmsVarianceUnits":  "COALESCE(SUM(wms_variance_units), 0)",
		"currencyCount":     "COUNT(DISTINCT currency_code)",
	},
	"replenishment_recommendations": {
		"cells":            "COUNT(*)",
		"assessedCells":    "COUNT(*) FILTER (WHERE interval_available)",
		"withheldCells":    "COUNT(*) FILTER (WHERE NOT interval_available)",
		"recommendedUnits": "COALESCE(SUM(recommended_units), 0)",
		"cellsToOrder":     "COUNT(*) FILTER (WHERE recommended_units > 0)",
		// P4-D11 keeps ERP transmission shadow-only, so there is no send path and
		// therefore no send failure. The count is real and it is zero; saying so
		// is more useful than withholding the tile.
		"erpFailures": "COUNT(*) FILTER (WHERE erp_status = 'failed')",
		"erpShadowed": "COUNT(*) FILTER (WHERE erp_status IS NOT NULL)",
		// Where a recommended order would be sourced from. The recommendation
		// carries a supply location; the echelon comes from the positions
		// projection, so the reference's order-mix card can name the three
		// routes instead of withholding all of them.
		"fromSupplier": "COUNT(*) FILTER (WHERE recommended_units > 0 " +
			"AND supply.location_kind IS NULL)",
		"fromWarehouse": "COUNT(*) FILTER (WHERE recommended_units > 0 " +
			"AND supply.location_kind IN ('dc', '3pl'))",
		"fromStore": "COUNT(*) FILTER (WHERE recommended_units > 0 " +
			"AND supply.location_kind = 'store')",
	},
	"replenishment_safety_stock": {
		"cells":            "COUNT(*)",
		"assessedCells":    "COUNT(*) FILTER (WHERE interval_available)",
		"withheldCells":    "COUNT(*) FILTER (WHERE NOT interval_available)",
		"safetyStockUnits": "COALESCE(SUM(safety_stock_units), 0)",
		// The buffer against the position holding it, per cell, over the whole
		// active version. Reported as unmeasurable before only because the two
		// sides live in different projections; see aggregateSource.
		"belowSafetyCells": "COUNT(*) FILTER (WHERE COALESCE(position.on_hand_units, 0) " +
			"< replenishment_safety_stock.safety_stock_units)",
		"excessSafetyCells": "COUNT(*) FILTER (WHERE COALESCE(position.on_hand_units, 0) " +
			"> replenishment_safety_stock.safety_stock_units * 2)",
		"comparedCells":    "COUNT(*) FILTER (WHERE position.on_hand_units IS NOT NULL)",
		"meanServiceLevel": "AVG(service_level)",
		"classACells":      "COUNT(*) FILTER (WHERE abc_class = 'A')",
		"classBCells":      "COUNT(*) FILTER (WHERE abc_class = 'B')",
		"classCCells":      "COUNT(*) FILTER (WHERE abc_class = 'C')",
	},
	"replenishment_transfers": {
		"rows":                 "COUNT(*)",
		"units":                "COALESCE(SUM(units), 0)",
		"expectedBenefitMinor": "COALESCE(SUM(expected_benefit_minor), 0)",
		"lanes":                "COUNT(DISTINCT lane_id)",
		"currencyCount":        "COUNT(DISTINCT currency_code)",
		// Transit time is a property of each declared lane, so the screen showed
		// nothing. A mean over the lanes actually being recommended is the figure
		// the reference's "Average Transfer Time" asks for.
		"meanTransitDays": "AVG(transit_days)",
		"maxTransitDays":  "MAX(transit_days)",
	},
	"replenishment_allocations": {
		"rows":           "COUNT(*)",
		"requestedUnits": "COALESCE(SUM(requested_units), 0)",
		"allocatedUnits": "COALESCE(SUM(allocated_units), 0)",
		"shortfallUnits": "COALESCE(SUM(shortfall_units), 0)",
		"channels":       "COUNT(DISTINCT channel_id)",
	},
	"replenishment_suppliers": {
		"suppliers":                "COUNT(*)",
		"highRisk":                 "COUNT(*) FILTER (WHERE risk_class = 'high')",
		"mediumRisk":               "COUNT(*) FILTER (WHERE risk_class = 'medium')",
		"lowRisk":                  "COUNT(*) FILTER (WHERE risk_class = 'low')",
		"meanOtdRate":              "AVG(otd_rate)",
		"meanLeadTimeDays":         "AVG(lead_time_mean_days)",
		"meanCapacityConfirmedPct": "AVG(capacity_confirmed_pct)",
		"capacityUnconfirmed":      "COUNT(*) FILTER (WHERE capacity_confirmed_pct IS NULL)",
	},
	"replenishment_exceptions": {
		"rows":     "COUNT(*)",
		"warnings": "COUNT(*) FILTER (WHERE severity = 'warning')",
		"infos":    "COUNT(*) FILTER (WHERE severity = 'info')",
		"classes":  "COUNT(DISTINCT exception_class)",
	},
}

// aggregateSource overrides the FROM for one projection's aggregate. Only
// declared where a KPI compares two projections cell for cell: "Below Safety
// Stock" is a comparison of the buffer against the position holding it, and
// neither table can answer it alone.
//
// USING, not ON, so the shared key columns stay single and the scope clauses
// above continue to name them unqualified. The grain is identical on both sides
// -- one row per market x location x SKU per version -- so the join cannot
// multiply rows, and a LEFT join keeps a buffer whose position is missing
// visible as below-buffer rather than dropping it from the count.
//
// Written as a join rather than a correlated subquery for a measured reason: the
// subquery form took 778ms per request against this projection, the join 8ms.
var aggregateSource = map[string]string{
	"replenishment_safety_stock": `retail_serving.replenishment_safety_stock
		LEFT JOIN retail_serving.inventory_positions AS position
		USING (inventory_version_id, market_id, location_id, sku_id)`,

	// Not a projection -- a companion-only view. Valuation is held per market x
	// location x category and carries no echelon, so a store screen asking for
	// "Store Inventory Value" would otherwise be handed the enterprise total.
	// The echelon comes from the positions projection, reduced to one row per
	// location first so the join cannot multiply a category's value by its SKUs.
	// The supply side of a recommendation, so the order mix can be split by
	// echelon. LEFT, because a supply location absent from the positions
	// projection is an external supplier rather than a node we hold stock at --
	// which is exactly the distinction the mix card draws.
	"replenishment_recommendations": `retail_serving.replenishment_recommendations
		LEFT JOIN (SELECT DISTINCT inventory_version_id AS supply_version,
		                  location_id AS supply_node, location_kind
		           FROM retail_serving.inventory_positions) AS supply
		ON supply.supply_version
		     = replenishment_recommendations.inventory_version_id
		AND supply.supply_node
		     = replenishment_recommendations.supply_location_id`,

	"inventory_valuation_by_kind": `retail_serving.inventory_valuation
		JOIN (SELECT DISTINCT inventory_version_id, market_id, location_id,
		             location_kind
		      FROM retail_serving.inventory_positions) AS echelon
		USING (inventory_version_id, market_id, location_id)`,
}

// aggregate reduces the whole scoped set for the KPI tiles. It returns nil when a
// table declares no aggregates, so a screen without tiles costs no query.
func (s *InventoryStore) aggregate(
	ctx context.Context,
	table string,
	clauses []string,
	args []any,
) (map[string]any, error) {
	expressions, present := inventoryAggregates[table]
	if !present {
		return nil, nil
	}
	source, joined := aggregateSource[table]
	if !joined {
		source = "retail_serving." + table
	}
	// Sorted so the generated SQL is stable across runs and diffable in logs.
	names := make([]string, 0, len(expressions))
	for name := range expressions {
		names = append(names, name)
	}
	sort.Strings(names)
	projections := make([]string, 0, len(names))
	for _, name := range names {
		projections = append(projections, expressions[name])
	}
	statement := fmt.Sprintf(
		"SELECT %s FROM %s WHERE %s",
		strings.Join(projections, ", "), source, strings.Join(clauses, " AND "),
	)
	row := s.pool.QueryRow(ctx, statement, args...)
	values := make([]any, len(names))
	pointers := make([]any, len(names))
	for index := range values {
		pointers[index] = &values[index]
	}
	if err := row.Scan(pointers...); err != nil {
		return nil, err
	}
	summary := make(map[string]any, len(names))
	for index, name := range names {
		summary[name] = values[index]
	}
	return summary, nil
}

func snakeToCamel(name string) string {
	parts := strings.Split(name, "_")
	for index := 1; index < len(parts); index++ {
		if parts[index] != "" {
			parts[index] = strings.ToUpper(parts[index][:1]) + parts[index][1:]
		}
	}
	return strings.Join(parts, "")
}

var _ = pgx.ErrNoRows
