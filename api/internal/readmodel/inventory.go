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
	InventoryMigrationRevision = "0014_warehouse_capacity"

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
	// Approved reporting FX from the publication's business controls, quote per
	// unit of base. Policy v2 forbids a nominal sum across currencies, and this
	// is the approval that lifts it -- without it the store refuses to add INR to
	// USD and reports money per market instead of one enterprise figure.
	ReportingCurrency string
	FXToReporting     map[string]string
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
	reportingCurrency   string
	fxToReporting       map[string]string
}

// fxExpr converts a money expression to the reporting currency inside SQL.
//
// In SQL rather than in the browser because the SUM has to be legal before it
// leaves the database: adding INR minor units to USD minor units and converting
// the total afterwards is not the same number, and it is the one policy v2
// names outright.
//
// A currency with no approved rate contributes NULL, so an unconvertible market
// drops out of the total rather than being added at par.
func (s *InventoryStore) fxExpr(units string) string {
	if len(s.fxToReporting) == 0 {
		return fmt.Sprintf("SUM(%s::numeric * dim.unit_cost_minor)", units)
	}
	branches := make([]string, 0, len(s.fxToReporting))
	for _, currency := range sortedKeys(s.fxToReporting) {
		branches = append(branches, fmt.Sprintf(
			"WHEN dim.currency_code = '%s' THEN %s::numeric * dim.unit_cost_minor * %s",
			currency, units, s.fxToReporting[currency],
		))
	}
	return fmt.Sprintf("SUM(CASE %s END)", strings.Join(branches, " "))
}

// fxMoneySum totals a column that is ALREADY money in the row's own currency,
// converting each row before adding it. `currency` names the column holding that
// currency, because the valuation projections carry their own rather than
// borrowing the dimension's.
//
// Every money aggregate over a published amount used a bare SUM, which adds
// rupees to dollars nominally -- the thing policy v2 forbids and the reason
// "Store Inventory Value" read Rs 7.02L on the stores page while the overview's
// own store row read Rs 17.60L. Enterprise gross valuation was out by the same
// mechanism: Rs 26.92 Cr summed nominally against Rs 106.83 Cr converted.
// `filter` is a complete " FILTER (WHERE ...)" clause or empty. Taken as an
// argument rather than concatenated by the caller because it has to sit INSIDE
// the COALESCE, attached to the aggregate -- appended outside it is a syntax
// error, and the route would fail closed on a governed 503.
func (s *InventoryStore) fxMoneySum(amount, currency, filter string) string {
	if len(s.fxToReporting) == 0 {
		return fmt.Sprintf("COALESCE(SUM(%s)%s, 0)", amount, filter)
	}
	branches := make([]string, 0, len(s.fxToReporting))
	for _, code := range sortedKeys(s.fxToReporting) {
		branches = append(branches, fmt.Sprintf(
			"WHEN %s = '%s' THEN %s::numeric * %s",
			currency, code, amount, s.fxToReporting[code],
		))
	}
	return fmt.Sprintf(
		"COALESCE(SUM(CASE %s END)%s, 0)", strings.Join(branches, " "), filter,
	)
}

// rowFXVariance values a unit count at the category-rollup cost. Distinct from
// rowFXExpr because the cost column is the rollup's, not the per-cell dimension's
// -- valuation is held per category and has no single SKU to price against.
func (s *InventoryStore) rowFXVariance(units string) string {
	if len(s.fxToReporting) == 0 {
		return fmt.Sprintf("%s::numeric * catcost.category_unit_cost", units)
	}
	branches := make([]string, 0, len(s.fxToReporting))
	for _, currency := range sortedKeys(s.fxToReporting) {
		branches = append(branches, fmt.Sprintf(
			"WHEN catcost.vc_currency = '%s' THEN %s::numeric"+
				" * catcost.category_unit_cost * %s",
			currency, units, s.fxToReporting[currency],
		))
	}
	return fmt.Sprintf("CASE %s END", strings.Join(branches, " "))
}

// rowFXMoney converts an amount that is already denominated in minor units of
// the row's own currency. rowFXExpr cannot serve here: it multiplies by
// dim.unit_cost_minor, which for a published money column would square the cost.
func (s *InventoryStore) rowFXMoney(amount string) string {
	if len(s.fxToReporting) == 0 {
		return amount + "::numeric"
	}
	branches := make([]string, 0, len(s.fxToReporting))
	for _, currency := range sortedKeys(s.fxToReporting) {
		branches = append(branches, fmt.Sprintf(
			"WHEN dim.currency_code = '%s' THEN %s::numeric * %s",
			currency, amount, s.fxToReporting[currency],
		))
	}
	return fmt.Sprintf("CASE %s END", strings.Join(branches, " "))
}

// rowFXExpr is fxExpr without the SUM: a single row's money, converted.
//
// Split rather than parameterised because the two shapes are used in different
// clauses -- one inside an aggregate, one in a row projection -- and a function
// returning "SUM(...)" for a per-row column produced a grouping error rather
// than a wrong number, which at least failed loudly.
func (s *InventoryStore) rowFXExpr(units string) string {
	if len(s.fxToReporting) == 0 {
		return fmt.Sprintf("%s::numeric * dim.unit_cost_minor", units)
	}
	branches := make([]string, 0, len(s.fxToReporting))
	for _, currency := range sortedKeys(s.fxToReporting) {
		branches = append(branches, fmt.Sprintf(
			"WHEN dim.currency_code = '%s' THEN %s::numeric * dim.unit_cost_minor * %s",
			currency, units, s.fxToReporting[currency],
		))
	}
	return fmt.Sprintf("CASE %s END", strings.Join(branches, " "))
}

// namesFXExpr is the row-grain money expression against the NAMES lookup alias.
//
// A third variant only because the cost sits behind a different alias here --
// `names` rather than `dim` -- and a shared helper would have to be told which,
// which is the same parameter spelled less clearly.
func (s *InventoryStore) namesFXExpr(units string) string {
	if len(s.fxToReporting) == 0 {
		return fmt.Sprintf("%s::numeric * names.unit_cost_minor", units)
	}
	branches := make([]string, 0, len(s.fxToReporting))
	for _, currency := range sortedKeys(s.fxToReporting) {
		branches = append(branches, fmt.Sprintf(
			"WHEN names.names_currency = '%s' THEN %s::numeric * names.unit_cost_minor * %s",
			currency, units, s.fxToReporting[currency],
		))
	}
	return fmt.Sprintf("CASE %s END", strings.Join(branches, " "))
}

func sortedKeys(values map[string]string) []string {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
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
	reportingCurrency := config.ReportingCurrency
	fxToReporting := config.FXToReporting
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
	store.reportingCurrency = reportingCurrency
	store.fxToReporting = fxToReporting
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
			"market_id, location_id, inventory_positions.location_kind, sku_id, on_hand_units, "+
				"committed_units, reserved_units, damaged_units, on_order_units, "+
				"in_transit_units, atp_units, assortment_active, residual_only",
			rankByPosition)
	case "/api/v1/inventory/stores":
		return s.tableSlice(ctx, query, "inventory_positions",
			"market_id, location_id, inventory_positions.location_kind, sku_id, on_hand_units, "+
				"atp_units, in_transit_units, assortment_active, residual_only",
			rankByPosition,
			"inventory_positions.location_kind = 'store'")
	case "/api/v1/inventory/warehouses":
		return s.tableSlice(ctx, query, "inventory_positions",
			// residual_only drives the reference's Action column. It was absent
			// from this route's projection alone, so every warehouse row showed
			// a blank action while the same column filled on every other screen.
			"market_id, location_id, inventory_positions.location_kind, sku_id, on_hand_units, "+
				"committed_units, damaged_units, atp_units, on_order_units, "+
				"residual_only",
			rankByPosition,
			"inventory_positions.location_kind IN ('dc', '3pl')")
	case "/api/v1/inventory/ageing":
		return s.tableSlice(ctx, query, "inventory_ageing",
			"market_id, location_id, sku_id, age_bucket, on_hand_units, "+
				"action, markdown_pct, residual_only, "+
				// The reference prints "Markdown 12% + transfer", not the engine's
				// own `markdown_candidate`. The depth is the policy's, read from
				// the row rather than written in here, so a market that markes
				// down at a different rate says so.
				`CASE action
					WHEN 'markdown_candidate' THEN
						'Markdown ' || round(markdown_pct * 100)::text ||
						'% + transfer'
					WHEN 'watch' THEN 'Watch cover'
					WHEN 'hold' THEN 'Hold'
				END AS action_label`,
			rankByAge)
	case "/api/v1/inventory/transfers":
		return s.tableSlice(ctx, query, "replenishment_transfers",
			"replenishment_transfers.market_id, lane_id, from_location_id, "+
				"to_location_id, replenishment_transfers.sku_id, units, "+
				"expected_benefit_minor, currency_code, transit_days",
			rankByBenefit)
	case "/api/v1/inventory/valuation":
		return s.tableSlice(ctx, query, "inventory_valuation",
			"inventory_valuation.market_id, location_id, "+
				"inventory_valuation.category, gross_value_minor, "+
				"currency_code, cost_method, cost_reason_code, wms_variance_units",
			rankByValue)
	case "/api/v1/inventory/expiry-waste":
		return s.tableSlice(ctx, query, "inventory_expiry_waste",
			"market_id, location_id, sku_id, expiring_units, expired_units, "+
				"waste_units, exposure_minor, "+
				"inventory_expiry_waste.currency_code",
			rankByExposure,
			// Only cells with something at risk. The artifact carries a row per
			// cell the expiry engine assessed -- 2,268 of them -- and 2,081 have
			// nothing expiring, nothing expired and no waste. Unscoped, the grid
			// filled with rows whose Expiry Window was blank, whose Units and
			// Value were zero and whose disposition advised acting on nothing,
			// and "Products at Risk" counted every assessed cell as at risk:
			// 2,268 against the 148 that actually hold expiring or expired stock.
			//
			// The route's clauses scope the summary as well as the rows, so the
			// tile and the grid under it now count the same population.
			"(inventory_expiry_waste.expiring_units > 0"+
				" OR inventory_expiry_waste.expired_units > 0"+
				" OR inventory_expiry_waste.waste_units > 0)")
	case "/api/v1/inventory/stock-health":
		return s.tableSlice(ctx, query, "inventory_stock_health",
			// reason_code must be qualified: the row projection joins
			// inventory_demand_at_risk for the lost-sales side of exposure, and it
			// carries a reason_code too. Unqualified, pgx rejects the statement and
			// the page fails closed -- correct, but invisible until it is opened.
			"market_id, location_id, sku_id, health_class, cover_days, "+
				"inventory_stock_health.reason_code",
			rankByHealth)
	case "/api/v1/replenishment/planner", "/api/v1/replenishment/orders":
		return s.tableSlice(ctx, query, "replenishment_recommendations",
			"replenishment_recommendations.market_id, destination_location_id, "+
				"supply_location_id, replenishment_recommendations.sku_id, "+
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
			"replenishment_exceptions.market_id, location_id, "+
				"replenishment_exceptions.sku_id, channel_id, exception_class, "+
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
		// The currency every money figure in this payload is expressed in, after
		// conversion. Published so the UI renders the symbol the number actually
		// carries instead of inferring one from the market list.
		"reportingCurrency": s.reportingCurrency,
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
	source := "retail_serving." + table
	selected := columns
	if rowDisplayTables[table] {
		source += `
			LEFT JOIN retail_serving.inventory_sku_dimension AS dim
			USING (inventory_version_id, market_id, location_id, sku_id)`
		selected += rowDisplayColumns
	}
	{
		// Outside the display-dimension gate on purpose. Transfers key on a lane
		// and valuation on a category, so neither joins the dimension at
		// market x location x SKU -- but both still need extra columns, and while
		// this was nested inside that gate their entries were declared and silently
		// never applied. Five named fields resolved against nothing.
		if extra, present := rowExtraJoins[table]; present {
			source += extra.join
			// %[1]s is the row's money expression, converted with this store's
			// approved reporting FX rather than a rate written into the literal.
			// %[2]s converts an amount that is ALREADY money -- the demand-at-risk
			// value is published in minor units, so it must not be multiplied by
			// unit cost a second time.
			//
			// The unit column is per route, not universal: Stock Health reads it
			// from the positions table it joins, while ageing and waste value their
			// OWN quantity. Hard-coding position.on_hand_units here meant any new
			// route referencing %[1]s emitted SQL naming an alias it never joined.
			units := rowMoneyUnits[table]
			if units == "" {
				units = "position.on_hand_units"
			}
			projected := strings.ReplaceAll(
				extra.columns, "%[1]s", s.rowFXExpr(units),
			)
			projected = strings.ReplaceAll(
				projected, "%[2]s", s.rowFXMoney("risk.risk_value_minor"),
			)
			// %[3]s values a UNIT variance at a rolled-up category cost: it
			// multiplies like a quantity, but reads its cost from the rollup rather
			// than the per-cell dimension, because valuation has no single SKU.
			selected += strings.ReplaceAll(
				projected, "%[3]s", s.rowFXVariance("wms_variance_units"),
			)
		}
	}
	if lookup, present := rowNameLookup[table]; present {
		key := "sku_id"
		if table == "inventory_valuation" {
			key = "category"
		}
		// Every column the subquery exposes is aliased away from the projection's
		// own names. Exposing `inventory_version_id` or `market_id` unaliased
		// made the outer WHERE clause ambiguous, which is a 503 on the route
		// rather than a wrong number.
		source += fmt.Sprintf(`
			LEFT JOIN (
				SELECT inventory_version_id AS names_version,
				       market_id AS names_market, %[1]s AS names_key,
				       MAX(product_name) AS product_name,
				       MAX(category_label) AS category_label,
				       MAX(unit_cost_minor) AS unit_cost_minor,
				       MAX(currency_code) AS names_currency
				FROM retail_serving.inventory_sku_dimension
				GROUP BY inventory_version_id, market_id, %[1]s
			) AS names
			ON names.names_version = %[2]s.inventory_version_id
			AND names.names_market = %[2]s.market_id
			AND names.names_key = %[3]s`, key, table, lookup.on)
		// %[1]s is the row's money expression under this store's approved FX.
		selected += strings.ReplaceAll(
			lookup.columns, "%[1]s", s.namesFXExpr("units"),
		)
	}
	statement := fmt.Sprintf(
		`SELECT COUNT(*) OVER(), %s FROM %s
		 WHERE %s ORDER BY %s LIMIT $%d OFFSET $%d`,
		selected, source, strings.Join(clauses, " AND "), ranking.orderBy,
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
	// The grouped cards, at the grains the reference draws them. One request per
	// screen still: a second browser call could apply a different scope and the
	// page would disagree with itself.
	if cards := groupedCards[table]; len(cards) > 0 {
		rendered := make(map[string]any, len(cards))
		for _, card := range cards {
			grouped, err := s.groupedCard(ctx, card, filters, extraClauses)
			if err != nil {
				return nil, err
			}
			rendered[card.name] = grouped
		}
		payload["cards"] = rendered
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
	// Health class FIRST made page one a single class: 174 stock-outs outrank
	// everything, so every row read "stockout / High / Replenish immediately" and
	// the column might as well have been a caption. The reference leads its own
	// Stock Health table with the largest exposure -- and its top row is an
	// Overstock, not a stock-out -- so capital at risk leads here too, with class
	// and cover as the tiebreaks. Money first also mixes the classes, which is
	// what makes the column worth reading.
	rankByHealth = inventoryRanking{
		orderBy: `exposure_minor DESC NULLS LAST,
			CASE health_class WHEN 'stockout' THEN 0 WHEN 'understock' THEN 1
			WHEN 'dead' THEN 2 WHEN 'overstock' THEN 3 ELSE 4 END,
			cover_days ASC NULLS FIRST, market_id, location_id, sku_id`,
		criterion: "the largest capital at risk, then the least healthy cells",
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

// A card the reference draws at a grain that is NOT the projection's row grain.
//
// This is the defect the whole file was shaped around and did not admit: the
// read model knew one shape -- a page of rows plus a scalar summary -- and six
// reference cards are GROUP BY tables. "Inventory Risk by Category" has four
// rows, one per category. "Location-Level Inventory Performance" has one row per
// LOCATION, as its title says. "Ageing Inventory" has one row per age bucket
// with a SKU COUNT in it. Served at row grain they showed a location id under a
// Category header and a SKU id under a Location header, which is not a rounding
// error in the layout -- it is a different table.
type groupedCard struct {
	// Key the UI reads the card by, and the key it appears under in `cards`.
	name string
	// FROM, including any join the card's columns need.
	source string
	// The GROUP BY, and the leading columns of the projection.
	groupBy string
	// Everything after the grouping columns, already aggregated.
	columns string
	orderBy string
	limit   int
}

// The money join. Every card that reports currency needs a unit cost, and the
// cost lives one join away in the dimension published by migration 0011.
//
// A row whose SKU has no accepted cost contributes NULL, not zero, and SUM skips
// it -- so an uncosted cell understates a total rather than silently valuing
// itself at nothing. `costedUnits` is published beside every money figure so a
// reader can see the coverage the number rests on.
const costJoin = `LEFT JOIN retail_serving.inventory_sku_dimension AS dim
	USING (inventory_version_id, market_id, location_id, sku_id)`

// outboundNeedJoin attaches, to each warehouse cell, the units the stores that
// warehouse supplies need from it for that SKU. The recommendations are rolled
// up to the supplying node first, so the join lands on the position's own grain
// -- one row per version x market x location x SKU -- and cannot multiply rows.
//
// It is the input to the reference's "Warehouse Fill Rate". Deliberately NOT
// allocated over requested from replenishment_allocations: every one of those
// rows sits at a DEMANDING store and names no supply node, so grouping them by
// supply_location_id attributes four stores' horizon channel demand to a
// warehouse and reads 2.6 per cent -- an authoritative-looking number answering
// a different question.
const outboundNeedJoin = `
	LEFT JOIN (
		SELECT rec.inventory_version_id AS need_version,
		       rec.market_id AS need_market,
		       rec.supply_location_id AS need_location,
		       rec.sku_id AS need_sku,
		       SUM(rec.recommended_units) AS need_units
		FROM retail_serving.replenishment_recommendations AS rec
		WHERE rec.supply_location_id IS NOT NULL
		  AND rec.recommended_units > 0
		GROUP BY rec.inventory_version_id, rec.market_id,
		         rec.supply_location_id, rec.sku_id
	) AS need
	  ON need.need_version = inventory_positions.inventory_version_id
	 AND need.need_market = inventory_positions.market_id
	 AND need.need_location = inventory_positions.location_id
	 AND need.need_sku = inventory_positions.sku_id`

// capacityJoin attaches a node's storage ceiling. One row per version x market x
// location, so it cannot multiply the positions it is joined to.
//
// The key columns are aliased rather than joined bare. Joined with ON, a second
// market_id and location_id enter scope, and every clause on this route that
// names them unqualified -- the group-by, the dc/3pl restriction, the market
// filter -- becomes ambiguous and the route serves a governed 503.
const capacityJoin = `
	LEFT JOIN (
		SELECT inventory_version_id AS cap_version,
		       market_id AS cap_market,
		       location_id AS cap_location,
		       capacity_units
		FROM retail_serving.inventory_warehouse_capacity
	) AS capacity
	  ON capacity.cap_version = inventory_positions.inventory_version_id
	 AND capacity.cap_market = inventory_positions.market_id
	 AND capacity.cap_location = inventory_positions.location_id`

// Utilisation divides the holding this card already values by the published
// ceiling. The numerator is the card's own SUM, not the source's `used_units`,
// so the percentage and the Inventory Value beside it rest on one number.
const capacityUtilizationExpr = `CASE WHEN MAX(capacity.capacity_units) > 0
	THEN SUM(on_hand_units)::numeric / MAX(capacity.capacity_units)
END`

// valuationCostJoin prices a valuation row's unit variance. Valuation is held
// per CATEGORY, so there is no single SKU to price against: the cost is the
// category's own trailing-demand-weighted mean, falling back to a plain mean
// where nothing moved.
//
// Shared by the row page and the "Valuation by Category" card rather than
// written twice -- the card's Variance column and the row's are the same figure
// at two grains, and two copies of it could drift apart.
const valuationCostJoin = `
	LEFT JOIN (
		SELECT inventory_version_id AS vc_version, market_id AS vc_market,
		       location_id AS vc_location, category AS vc_category,
		       CASE WHEN SUM(trailing_daily_units) > 0
		            THEN SUM(unit_cost_minor * trailing_daily_units)
		                 / SUM(trailing_daily_units)
		            ELSE AVG(unit_cost_minor) END AS category_unit_cost,
		       MAX(currency_code) AS vc_currency
		FROM retail_serving.inventory_sku_dimension
		GROUP BY inventory_version_id, market_id, location_id, category
	) AS catcost
	  ON catcost.vc_version = inventory_valuation.inventory_version_id
	 AND catcost.vc_market = inventory_valuation.market_id
	 AND catcost.vc_location = inventory_valuation.location_id
	 AND catcost.vc_category = inventory_valuation.category`

// A line fill rate: of the units the stores a warehouse supplies need from it,
// the share it can ship from its own stock. The cap is per SKU line, because
// surplus of one SKU cannot fill a shortfall of another -- summing both sides
// first and capping once would report a warehouse as able to fill orders it
// holds nothing for. Cells with no outbound need contribute nothing to either
// side rather than counting as filled.
// The FILTER is load-bearing, not defensive. LEAST ignores its NULL arguments
// rather than returning NULL, so on a cell with no outbound need
// LEAST(NULL, on_hand_units) is the whole on-hand: every warehouse cell nobody
// ordered from added its full holding to the numerator and nothing to the
// denominator, and the rate read 308% overall and 770% at Newark.
const fillRateExpr = `CASE WHEN SUM(need.need_units) > 0
	THEN (SUM(LEAST(need.need_units, COALESCE(on_hand_units, 0)))
	      FILTER (WHERE need.need_units IS NOT NULL))::numeric
	     / SUM(need.need_units)
END`

// The reference draws Ageing Inventory on the Inventory Overview AND on the
// Inventory Ageing page. A card names its own source, so one declaration serves
// both rather than two that can drift.
var ageingBucketCard = groupedCard{
	// "Ageing Inventory". Four rows, one per bucket, with a SKU COUNT --
	// not one row per SKU with the bucket name repeated down a column.
	name:    "buckets",
	source:  "retail_serving.inventory_ageing " + costJoin,
	groupBy: "age_bucket",
	columns: `COUNT(DISTINCT sku_id) AS skus,
SUM(on_hand_units) AS on_hand_units,
%[1]s AS value_minor,
COUNT(*) FILTER (WHERE action = 'markdown_candidate') AS markdown_cells,
-- Sell-through over the trailing quarter: units moved against units moved
-- plus units still held. The window is named in the column note rather than
-- left implicit, because a sell-through with no window is not a number.
CASE WHEN SUM(dim.trailing_daily_units) * 91 + SUM(on_hand_units) > 0
	THEN (SUM(dim.trailing_daily_units) * 91)
		/ (SUM(dim.trailing_daily_units) * 91 + SUM(on_hand_units))
END AS sell_through_pct,
-- The action escalates with AGE, which is what the reference's ladder
-- shows: monitor, optimise, transfer, clear. Testing the markdown
-- candidate count first made every bucket read "Markdown / clearance",
-- because every bucket contains at least one candidate.
CASE age_bucket
	WHEN '0-30' THEN 'Monitor'
	WHEN '30-60' THEN 'Optimize replenishment'
	WHEN '60-90' THEN 'Transfer / promote'
	ELSE 'Markdown / clearance'
END AS recommended_action,
MAX(dim.currency_code) AS currency_code`,
	// Oldest first, and by bucket ORDER not alphabetically: '180-plus'
	// sorts before '30-60' as text.
	orderBy: `CASE age_bucket WHEN '0-30' THEN 0 WHEN '30-60' THEN 1
WHEN '60-90' THEN 2 WHEN '90-180' THEN 3 ELSE 4 END`,
	limit: 20,
}

var groupedCards = map[string][]groupedCard{
	"inventory_positions": {
		ageingBucketCard,
		{
			// The reference's Warehouse Inventory table is one row per WAREHOUSE --
			// three of them, "West DC, Ahmedabad" and friends -- with a money
			// Inventory Value and a money Blocked Stock. This route was serving the
			// positions projection at its own market x location x SKU grain, so a
			// SKU sat under a Warehouse header and every money column showed a unit
			// count.
			//
			// Delayed Receipts is a COUNT in the reference (18, 26), not a quantity:
			// how many inbound lines are late, which is what a warehouse manager
			// chases. on_order_units answered "how many units are coming".
			name: "warehouses",
			source: "retail_serving.inventory_positions " + costJoin +
				outboundNeedJoin + capacityJoin,
			groupBy: "market_id, location_id, dim.location_name",
			columns: `%[1]s AS value_minor,
				-- The damaged holding at cost. This valued the whole ON-HAND of any
				-- cell carrying damage instead: one damaged unit in a cell of 93
				-- reported 93 units' worth, Rs 52,173 against the true Rs 561, and
				-- the tile beside it -- correctly damaged units at cost -- disagreed.
				%[4]s AS blocked_value_minor,
				SUM(on_hand_units) AS on_hand_units,
				SUM(damaged_units) AS damaged_units,
				-- Late inbound LINES, not units. A line with nothing yet received
				-- against it is the thing the reference counts.
				COUNT(*) FILTER (WHERE on_order_units > 0
					AND in_transit_units = 0) AS delayed_receipts,
				` + fillRateExpr + ` AS fill_rate,
				` + capacityUtilizationExpr + ` AS capacity_utilization,
				-- The reference's Action column names what to do about the state
				-- this row is in, in its own words.
				CASE
					WHEN SUM(damaged_units) > 0 THEN 'Release blocked stock'
					WHEN COUNT(*) FILTER (WHERE on_order_units > 0
						AND in_transit_units = 0) > 0 THEN 'Expedite receipts'
					WHEN COUNT(*) FILTER (WHERE residual_only) > 0
						THEN 'Review residual stock'
					ELSE 'Maintain'
				END AS warehouse_action,
				COUNT(*) AS cells,
				COUNT(dim.unit_cost_minor) AS costed_cells,
				MAX(dim.currency_code) AS currency_code`,
			orderBy: "%[1]s DESC NULLS LAST, market_id, location_id",
			limit:   20,
			// No scope field is needed: the card builder applies the route's own
			// static clauses, and this route already restricts to dc/3pl.
		},
		{
			// "Location-Level Inventory Performance". One row per location, as
			// the title says. Type, value, availability, cover, risk, overstock.
			name: "locations",
			source: "retail_serving.inventory_positions " + costJoin + `
				LEFT JOIN retail_serving.inventory_stock_health AS health
				USING (inventory_version_id, market_id, location_id, sku_id)`,
			groupBy: "market_id, location_id, inventory_positions.location_kind, dim.location_name",
			columns: `-- The reference's Type column reads "Store" and "Warehouse";
				-- "dc" is the source's word for the echelon, not the screen's.
				CASE inventory_positions.location_kind
					WHEN 'store' THEN 'Store'
					WHEN 'dc' THEN 'Warehouse'
					WHEN '3pl' THEN 'Warehouse (3PL)'
					ELSE initcap(inventory_positions.location_kind)
				END AS location_type,
				SUM(on_hand_units) AS on_hand_units,
				%[1]s AS value_minor,
				SUM(atp_units) AS atp_units,
				-- On-shelf availability is an IN-STOCK RATE: of the SKUs this
				-- node is meant to carry, how many are actually available to
				-- sell. It is not ATP over on-hand -- that ratio is
				-- definitionally 1 at a store, because the source records no
				-- committed or reserved units there, which is why every store
				-- reported exactly 100%.
				CASE WHEN COUNT(*) FILTER (WHERE assortment_active) > 0
					THEN COUNT(*) FILTER (
						WHERE assortment_active AND atp_units > 0
					)::numeric / COUNT(*) FILTER (WHERE assortment_active)
				END AS availability_pct,
				CASE WHEN SUM(dim.trailing_daily_units) > 0
					THEN SUM(on_hand_units) / SUM(dim.trailing_daily_units)
				END AS days_of_supply,
				AVG(health.cover_days) AS cover_days,
				CASE WHEN COUNT(*) > 0 THEN
					COUNT(*) FILTER (WHERE health.health_class = 'overstock')::numeric
					/ COUNT(*) END AS overstock_pct,
				CASE WHEN COUNT(*) > 0 THEN
					COUNT(*) FILTER (WHERE health.health_class IN
						('understock', 'stockout'))::numeric
					/ COUNT(*) END AS understock_pct,
				-- The reference badges a location Low/Medium/High, from the health
				-- engine's own classes and from which condition DOMINATES the group
				-- rather than merely appears in it.
				--
				-- Presence was the wrong test. These groups hold hundreds of cells, so
				-- "any stock-out is High" put High on every row and printed one value
				-- down the whole column, hiding the spread the column exists to show.
				-- 'dead' is deliberately NOT in the excess bucket. 2,514 of 4,737 cells
				-- are dead, which is structural rather than a signal, and folding it in
				-- made excess swamp shortage in every single group -- collapsing the
				-- column again, just onto a different constant. Dead stock is what the
				-- Ageing card reports; this column is about over versus under.
				CASE
					WHEN COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock')) = 0 THEN 'Low'
					WHEN COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock'))
						>= COUNT(*) FILTER (WHERE health.health_class = 'overstock') THEN 'High'
					ELSE 'Medium'
				END AS stockout_risk,
				-- The reference's own action vocabulary for this card: Maintain,
				-- Rebalance, Replenish, Transfer + markdown. A group clearly dominated
				-- by one side gets that side's action; only a genuinely balanced group
				-- gets both. Testing presence of both made every row read
				-- "Transfer + markdown".
				CASE
					WHEN COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock')) = 0
						AND COUNT(*) FILTER (WHERE health.health_class = 'overstock') = 0 THEN 'Maintain'
					WHEN COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock'))
						> 2 * COUNT(*) FILTER (WHERE health.health_class = 'overstock') THEN 'Replenish'
					WHEN COUNT(*) FILTER (WHERE health.health_class = 'overstock')
						> 2 * COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock')) THEN 'Rebalance'
					ELSE 'Transfer + markdown'
				END AS priority_action,
				COUNT(*) AS cells,
				COUNT(dim.unit_cost_minor) AS costed_cells,
				MAX(dim.currency_code) AS currency_code`,
			orderBy: "%[1]s DESC NULLS LAST, market_id, location_id",
			limit:   20,
		},
		{
			// "Inventory Risk by Category". Four rows in the reference, one per
			// product category -- the thing that had no source at all until the
			// dimension existed.
			name: "categories",
			source: "retail_serving.inventory_positions " + costJoin + `
				LEFT JOIN retail_serving.inventory_stock_health AS health
				USING (inventory_version_id, market_id, location_id, sku_id)
				LEFT JOIN retail_serving.inventory_expiry_waste AS waste
				USING (inventory_version_id, market_id, location_id, sku_id)`,
			groupBy: "dim.category, dim.category_label",
			columns: `SUM(on_hand_units) AS on_hand_units,
				%[1]s AS value_minor,
				SUM(atp_units) AS atp_units,
				CASE WHEN SUM(dim.trailing_daily_units) > 0
					THEN SUM(on_hand_units) / SUM(dim.trailing_daily_units)
				END AS days_of_supply,
				AVG(health.cover_days) AS cover_days,
				-- Risk and action, paired exactly as the reference pairs them: Healthy
				-- with Protect availability, Watch with Target transfers, Mixed with
				-- Replenish top sellers, Expiry Risk with Promote near expiry.
				--
				-- Two things were wrong. Expiry Risk was keyed off health_class
				-- 'stockout', which is its opposite -- a cell with nothing on the shelf
				-- cannot have stock about to expire -- and it was keyed off PRESENCE, so
				-- one stock-out cell in a hundred-cell category tripped the first
				-- branch. Between them, every category read "Expiry Risk / Promote near
				-- expiry" no matter what it held.
				--
				-- Expiry now comes from the expiry artifact, which is what measures it,
				-- and each branch tests which condition DOMINATES the category rather
				-- than whether it occurs at all.
				CASE
					WHEN COUNT(*) FILTER (WHERE waste.expiring_units > 0
						OR waste.expired_units > 0) >= COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock'))
						AND COUNT(*) FILTER (WHERE waste.expiring_units > 0
						OR waste.expired_units > 0)
							>= COUNT(*) FILTER (WHERE health.health_class = 'overstock')
						AND COUNT(*) FILTER (WHERE waste.expiring_units > 0
						OR waste.expired_units > 0) > 0
						THEN 'Expiry Risk'
					WHEN COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock'))
						>= COUNT(*) FILTER (WHERE health.health_class = 'overstock')
						AND COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock')) > 0
						THEN 'Watch'
					WHEN COUNT(*) FILTER (WHERE health.health_class = 'overstock') > 0 THEN 'Mixed'
					ELSE 'Healthy'
				END AS risk_class,
				CASE
					WHEN COUNT(*) FILTER (WHERE waste.expiring_units > 0
						OR waste.expired_units > 0) >= COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock'))
						AND COUNT(*) FILTER (WHERE waste.expiring_units > 0
						OR waste.expired_units > 0)
							>= COUNT(*) FILTER (WHERE health.health_class = 'overstock')
						AND COUNT(*) FILTER (WHERE waste.expiring_units > 0
						OR waste.expired_units > 0) > 0
						THEN 'Promote near expiry'
					WHEN COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock'))
						>= COUNT(*) FILTER (WHERE health.health_class = 'overstock')
						AND COUNT(*) FILTER (WHERE health.health_class IN
						('stockout', 'understock')) > 0
						THEN 'Target transfers'
					WHEN COUNT(*) FILTER (WHERE health.health_class = 'overstock') > 0 THEN 'Replenish top sellers'
					ELSE 'Protect availability'
				END AS risk_action,
				COUNT(*) AS cells,
				COUNT(dim.unit_cost_minor) AS costed_cells,
				MAX(dim.currency_code) AS currency_code`,
			orderBy: "%[1]s DESC NULLS LAST, dim.category",
			limit:   20,
		},
	},
	"inventory_ageing": {ageingBucketCard},
	"inventory_valuation": {
		{
			// "Valuation by Category" -- already at category grain in the
			// projection, so this only needs the rollup across locations.
			name: "categories",
			// The label lives on the SKU dimension, so the card grouped by the
			// slug and printed "electronics-laptops" under a Category header.
			// Reduced to one row per category first: joining the dimension at its
			// own market x location x SKU grain would multiply the value.
			source: `retail_serving.inventory_valuation
				LEFT JOIN (
					SELECT inventory_version_id AS label_version,
					       category AS label_category,
					       MAX(category_label) AS category_label
					FROM retail_serving.inventory_sku_dimension
					GROUP BY inventory_version_id, category
				) AS labels
				ON labels.label_version = inventory_valuation.inventory_version_id
				AND labels.label_category = inventory_valuation.category` +
				valuationCostJoin,
			groupBy: "inventory_valuation.category, labels.category_label",
			columns: `%[3]s AS value_minor,
				SUM(wms_variance_units) AS wms_variance_units,
				-- The reference's Variance column is MONEY -- Rs 0.1 Cr -- and this
				-- card published only the unit count, so it printed a quantity under
				-- a rupee header while the Inventory Variance tile above it, reading
				-- the same variance, showed rupees.
				COALESCE(SUM(%[5]s), 0) AS variance_value_minor,
				COUNT(*) AS rows_in_group,
				COUNT(*) FILTER (WHERE gross_value_minor IS NULL) AS unvalued_rows,
				MAX(currency_code) AS currency_code`,
			orderBy: "%[3]s DESC NULLS LAST, inventory_valuation.category",
			limit:   20,
		},
	},
	"inventory_stock_health": {
		{
			// Per-location health, which the store heatmap and the overview's
			// location card both read for cover days and risk mix.
			name:    "locations",
			source:  "retail_serving.inventory_stock_health",
			groupBy: "market_id, location_id",
			columns: `AVG(cover_days) AS cover_days,
				COUNT(*) AS cells,
				COUNT(*) FILTER (WHERE health_class = 'overstock') AS overstock_cells,
				COUNT(*) FILTER (WHERE health_class = 'understock') AS understock_cells,
				COUNT(*) FILTER (WHERE health_class = 'stockout') AS stockout_cells,
				COUNT(*) FILTER (WHERE health_class = 'dead') AS dead_cells`,
			orderBy: "market_id, location_id",
			limit:   50,
		},
	},
	"replenishment_safety_stock": {
		{
			// "Policy Segment" is the ABC class -- "A / High Velocity" -- with a
			// SKU count and a buffer VALUE. Two rows in the reference, not 4,741.
			name: "segments",
			source: `retail_serving.replenishment_safety_stock
				LEFT JOIN retail_serving.inventory_sku_dimension AS dim
				USING (inventory_version_id, market_id, location_id, sku_id)`,
			groupBy: "abc_class",
			columns: `COUNT(DISTINCT sku_id) AS skus,
				AVG(service_level) AS service_level,
				SUM(safety_stock_units) AS safety_stock_units,
				%[2]s AS value_minor,
				COUNT(*) FILTER (WHERE interval_available) AS assessed_cells,
				COUNT(*) AS cells,
				MAX(dim.currency_code) AS currency_code`,
			orderBy: `CASE abc_class WHEN 'A' THEN 0 WHEN 'B' THEN 1 WHEN 'C' THEN 2
				ELSE 3 END`,
			limit: 20,
		},
	},
	"replenishment_recommendations": {
		{
			// "Lead-Time Risk" -- per supply source, not per recommendation.
			name:    "leadTime",
			source:  `retail_serving.replenishment_recommendations`,
			groupBy: "market_id, supply_location_id",
			columns: `COUNT(*) AS cells,
				COUNT(*) FILTER (WHERE recommended_units > 0) AS orders,
				SUM(recommended_units) AS recommended_units,
				COUNT(*) FILTER (WHERE NOT interval_available) AS withheld_cells`,
			orderBy: "COUNT(*) FILTER (WHERE recommended_units > 0) DESC, market_id, supply_location_id",
			limit:   20,
		},
	},
}

// Row pages that print a NAME rather than an identifier.
//
// Listed rather than inferred: every one of these is keyed
// (market_id, location_id, sku_id), which is exactly the dimension's grain, so
// the join is a USING and the shared columns merge instead of colliding. The
// replenishment projections key on destination_location_id and are not in this
// set -- they need an aliased ON, which is a different change.
var rowDisplayTables = map[string]bool{
	"inventory_positions":        true,
	"inventory_stock_health":     true,
	"inventory_ageing":           true,
	"inventory_expiry_waste":     true,
	"inventory_demand_at_risk":   true,
	"replenishment_safety_stock": true,
	"replenishment_allocations":  true,
}

// The unit column each row page values. Absent means the route joins positions
// and reads on_hand_units from there, which is what Stock Health does.
var rowMoneyUnits = map[string]string{
	"inventory_ageing": "inventory_ageing.on_hand_units",
	// The reference's waste Value column sits beside "Units", and its Units column
	// is the EXPIRED quantity -- so the money figure is what is at risk now, the
	// expiring holding, not what has already been written off.
	"inventory_expiry_waste": "inventory_expiry_waste.expiring_units",
}

// Extra joins a row page needs beyond the display dimension, with the columns
// they contribute.
//
// Stock Health is the case that forced this: the reference's row carries Days of
// Supply, AGEING, Health, FINANCIAL EXPOSURE, an action and a priority. Health
// and cover come from the health projection, but ageing lives in the ageing
// projection and exposure is on-hand times cost -- on-hand being in positions.
// Three projections, one row, and no way to express that before.
var rowExtraJoins = map[string]struct {
	join    string
	columns string
}{
	// The reference's ageing row carries a money Value; the projection has units
	// and the dimension has the cost, so it only ever needed composing. `%[1]s` is
	// the row money expression under the store's approved FX.
	"inventory_ageing": {
		join: "",
		// The reference's ageing Priority is a WORD -- "High", "Medium" -- ranking
		// how urgently the row needs working, not a Yes/No on residual status.
		columns: `, %[1]s AS value_minor,
			-- Sell-through at row grain: the same trailing-quarter ratio the
			-- Ageing Inventory card carries one bucket at a time -- units moved
			-- over units moved plus units still held -- read from this row's own
			-- trailing demand instead of a SUM over the bucket. A row that moved
			-- nothing reads 0%, which on an ageing screen is the point.
			CASE WHEN dim.trailing_daily_units * 91
			          + inventory_ageing.on_hand_units > 0
				THEN (dim.trailing_daily_units * 91)
					/ (dim.trailing_daily_units * 91
					   + inventory_ageing.on_hand_units)
			END AS sell_through_pct,
			CASE
				WHEN residual_only THEN 'High'
				WHEN age_bucket = '180-plus' THEN 'High'
				WHEN age_bucket = '90-180' THEN 'Medium'
				ELSE 'Low'
			END AS ageing_priority`,
	},
	// Expiry Window in the reference is a DURATION -- "1 day", "21 days" -- not a
	// unit count, and Priority is a word, not a quantity. Both were bound to unit
	// columns, so the screen printed 420 under "Expiry Window" and a waste
	// quantity under "Priority".
	"inventory_expiry_waste": {
		// Positions, for the holding sell-through measures against. The waste
		// artifact carries only the expiring and expired slices of a cell, and a
		// sell-through against a slice is not the cell's sell-through.
		join: `
			LEFT JOIN retail_serving.inventory_positions AS wastepos
			USING (inventory_version_id, market_id, location_id, sku_id)`,
		columns: `, %[1]s AS value_minor,
			-- The same trailing-quarter sell-through the ageing row carries, so the
			-- two pages cannot disagree about one cell. Withheld, not zeroed, where
			-- the cell has no position to measure against.
			CASE WHEN dim.trailing_daily_units * 91
			          + wastepos.on_hand_units > 0
				THEN (dim.trailing_daily_units * 91)
					/ (dim.trailing_daily_units * 91 + wastepos.on_hand_units)
			END AS sell_through_pct,
			-- The reference names a disposition per row -- and the artifact
			-- publishes none, so this column was blank on every row.
			--
			-- Keyed on what the row actually publishes: what has already expired can
			-- only be written off, and what has not is redistributable from a DC in
			-- the reference's own words for its DC row ("Transfer to high-demand
			-- stores") but not from the shelf it is already on.
			--
			-- Deliberately NOT a graded ladder on quantity. Splitting the
			-- unexpired rows by at-risk units against trailing demand, or by their
			-- share of the cell's on-hand, moves 4 to 10 rows of 2,268 at every
			-- threshold from 10% to 50% and 3 to 30 days -- the near-expiry slice is
			-- a small part of the holding almost everywhere. Four labels where three
			-- are near-empty reads as discrimination the evidence cannot support.
			-- Ordered by what is still actionable. A cell whose stock is already
			-- written off has nothing to move: reaching the DC branch, it advised
			-- transferring stock that no longer exists.
			CASE
				WHEN inventory_expiry_waste.expired_units > 0
					THEN 'Write off and record waste'
				WHEN inventory_expiry_waste.expiring_units = 0
					THEN 'Review waste cause'
				WHEN dim.location_kind IN ('dc', '3pl')
					THEN 'Transfer to high-demand stores'
				ELSE 'Promote before expiry'
			END AS waste_action,
			-- Expiring stock is inside its shelf-life window by definition; the
			-- window itself is not published per row, so this names which side of
			-- the boundary the row sits on rather than inventing a day count.
			--
			-- The third state is load-bearing: a cell can reach this page on WASTE
			-- alone, with nothing expiring and nothing expired. Those rows had no
			-- branch and printed an empty window.
			CASE
				WHEN expired_units > 0 THEN 'Expired'
				WHEN expiring_units > 0 THEN 'Within shelf life'
				WHEN waste_units > 0 THEN 'Written off'
			END AS expiry_window,
			CASE
				WHEN expired_units > 0 THEN 'High'
				WHEN expiring_units > 0 THEN 'Medium'
				ELSE 'Low'
			END AS waste_priority`,
	},
	// The reference's Variance column is MONEY -- Rs 0.1 Cr -- and the projection
	// publishes a unit variance. Valuing it needs a cost, and valuation is held per
	// market x location x CATEGORY, so the cost comes from the dimension rolled up
	// to the same grain: demand-weighted where there is demand, a plain mean
	// otherwise, so a category with no movement still prices.
	"inventory_valuation": {
		join:    valuationCostJoin,
		columns: `, %[3]s AS variance_value_minor`,
	},
	// The reference's transfer row names both ends in words and shows the qty
	// AVAILABLE at the source beside the qty suggested. Raw location ids and a
	// single quantity reused for both columns is what shipped.
	"replenishment_transfers": {
		join: `
			LEFT JOIN (
				SELECT DISTINCT inventory_version_id AS fl_version,
				       market_id AS fl_market, location_id AS fl_location,
				       location_name AS from_location_name
				FROM retail_serving.inventory_sku_dimension
			) AS fromloc
			  ON fromloc.fl_version = replenishment_transfers.inventory_version_id
			 AND fromloc.fl_market = replenishment_transfers.market_id
			 AND fromloc.fl_location = replenishment_transfers.from_location_id
			LEFT JOIN (
				SELECT DISTINCT inventory_version_id AS tl_version,
				       market_id AS tl_market, location_id AS tl_location,
				       location_name AS to_location_name
				FROM retail_serving.inventory_sku_dimension
			) AS toloc
			  ON toloc.tl_version = replenishment_transfers.inventory_version_id
			 AND toloc.tl_market = replenishment_transfers.market_id
			 AND toloc.tl_location = replenishment_transfers.to_location_id
			LEFT JOIN (
				SELECT inventory_version_id AS sp_version,
				       market_id AS sp_market, location_id AS sp_location,
				       sku_id AS sp_sku, on_hand_units AS available_units
				FROM retail_serving.inventory_positions
			) AS sourcepos
			  ON sourcepos.sp_version
			     = replenishment_transfers.inventory_version_id
			 AND sourcepos.sp_market = replenishment_transfers.market_id
			 AND sourcepos.sp_location = replenishment_transfers.from_location_id
			 AND sourcepos.sp_sku = replenishment_transfers.sku_id`,
		columns: `, fromloc.from_location_name, toloc.to_location_name,
			sourcepos.available_units,
			-- P4-D11 makes every recommendation shadow-only, so there is no
			-- workflow state to report. The reference's Review/Draft is a stage in
			-- an approval flow this release does not run; saying so is the honest
			-- answer, and it is a governed reason rather than a blank.
			'Shadow (not sent)' AS transfer_status`,
	},
	"inventory_stock_health": {
		join: `
			LEFT JOIN retail_serving.inventory_positions AS position
			USING (inventory_version_id, market_id, location_id, sku_id)
			LEFT JOIN (
				SELECT inventory_version_id, market_id, location_id, sku_id,
				       MIN(age_bucket) AS age_bucket
				FROM retail_serving.inventory_ageing
				GROUP BY inventory_version_id, market_id, location_id, sku_id
			) AS ageing
			USING (inventory_version_id, market_id, location_id, sku_id)
			LEFT JOIN retail_serving.inventory_demand_at_risk AS risk
			USING (inventory_version_id, market_id, location_id, sku_id)`,
		columns: `, position.on_hand_units,
			-- What it costs to leave this row alone, which is not the same measure
			-- on both sides of the problem. The reference makes the distinction
			-- explicit: its overstock row shows the value held (Rs 18.2L) and its
			-- understock row shows "Rs 3.2L lost sales".
			--
			-- On-hand value alone put every shortage row at zero, so ranking by
			-- money swept all 174 stock-outs off page one -- monotony in the other
			-- direction. A shortage is exposed by the demand it cannot serve, which
			-- is what inventory_demand_at_risk publishes. Where that interval was
			-- withheld there is no substitute, so the row falls back to what is held
			-- and reads zero rather than estimating.
			CASE
				WHEN health_class IN ('stockout', 'understock')
					AND risk.risk_value_minor IS NOT NULL THEN %[2]s
				ELSE %[1]s
			END AS exposure_minor,
			CASE ageing.age_bucket
				WHEN '0-30' THEN '0-30 days'
				WHEN '30-60' THEN '31-60 days'
				WHEN '60-90' THEN '61-90 days'
				WHEN '90-180' THEN '91-180 days'
				WHEN '180-plus' THEN '180+ days'
			END AS ageing_band,
			CASE health_class
				WHEN 'stockout' THEN 'High'
				WHEN 'understock' THEN 'High'
				WHEN 'overstock' THEN 'Medium'
				WHEN 'dead' THEN 'Medium'
				ELSE 'Low'
			END AS priority,
			CASE health_class
				WHEN 'stockout' THEN 'Replenish immediately'
				WHEN 'understock' THEN 'Replenish immediately'
				WHEN 'overstock' THEN 'Markdown + transfer'
				WHEN 'dead' THEN 'Review for clearance'
				ELSE 'Maintain'
			END AS recommended_action`,
	},
}

// Routes keyed on something other than (market, location, sku) that still print
// a name. A product's name does not depend on where it sits, so a SKU-only
// lookup is enough -- and DISTINCT because the dimension has one row per cell.
var rowNameLookup = map[string]struct {
	on      string
	columns string
}{
	"replenishment_transfers": {
		on: "replenishment_transfers.sku_id",
		// The row's own value: units at cost, converted. Distinct from
		// expected_benefit_minor, which the reference shows in its own column.
		columns: ", names.product_name, names.category_label, %[1]s AS transfer_value_minor",
	},
	"replenishment_recommendations": {
		on:      "replenishment_recommendations.sku_id",
		columns: ", names.product_name, names.category_label",
	},
	"replenishment_exceptions": {
		on:      "replenishment_exceptions.sku_id",
		columns: ", names.product_name, names.category_label",
	},
	"inventory_valuation": {
		// Valuation has no SKU at all -- it is per category -- so the label is
		// looked up on the category instead.
		on:      "inventory_valuation.category",
		columns: ", names.category_label",
	},
}

// : What a row page selects from the dimension. Same expression everywhere so a
// : product is named the same way on every screen that lists it.
const rowDisplayColumns = `, dim.product_name, dim.location_name,
	dim.category_label,
	CASE dim.location_kind
		WHEN 'store' THEN 'Store'
		WHEN 'dc' THEN 'Warehouse'
		WHEN '3pl' THEN 'Warehouse (3PL)'
		ELSE initcap(dim.location_kind)
	END AS location_type`

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
		// "Open PO Value" is inbound already on order, which lives in the
		// position projection's on_order bucket -- the suppliers projection
		// carries performance and risk, and no quantity at all.
		{table: "inventory_positions", prefix: "position"},
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
	"inventory_sku_dimension":       {"market_id": true, "location_id": true, "sku_id": true, "category": true},
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
		"storeOnHandUnits": "COALESCE(SUM(on_hand_units) FILTER (WHERE inventory_positions.location_kind = 'store'), 0)",
		"dcOnHandUnits":    "COALESCE(SUM(on_hand_units) FILTER (WHERE inventory_positions.location_kind = 'dc'), 0)",
		"inTransitUnits":   "COALESCE(SUM(in_transit_units), 0)",
		"onOrderUnits":     "COALESCE(SUM(on_order_units), 0)",
		"committedUnits":   "COALESCE(SUM(committed_units), 0)",
		"damagedUnits":     "COALESCE(SUM(damaged_units), 0)",
		// A real count, not a stand-in. It reads 0 today, and 0 is the answer --
		// rendering "Not available" over a measure the projection can compute
		// tells a retailer the platform cannot see negative inventory when in
		// fact it can see there is none.
		"negativeCells": "COUNT(*) FILTER (WHERE on_hand_units < 0)",
		// On-shelf availability, the same in-stock rate the heatmap shows per
		// store: of the cells this node is meant to carry, how many can be sold.
		// The KPI tile was ATP over on-hand, which is 1 by construction at a
		// store, so it read exactly 100% however the stores were actually doing.
		"assortedCells": "COUNT(*) FILTER (WHERE assortment_active)",
		"inStockAssortedCells": "COUNT(*) FILTER " +
			"(WHERE assortment_active AND atp_units > 0)",
		"zeroCells":         "COUNT(*) FILTER (WHERE on_hand_units = 0)",
		"cells":             "COUNT(*)",
		"residualOnlyCells": "COUNT(*) FILTER (WHERE residual_only)",
		"activeCells":       "COUNT(*) FILTER (WHERE assortment_active)",
		"storeCells":        "COUNT(*) FILTER (WHERE inventory_positions.location_kind = 'store')",
		"dcCells":           "COUNT(*) FILTER (WHERE inventory_positions.location_kind = 'dc')",
		// The reference's "Warehouse Fill Rate" tile, the same line fill the
		// warehouse rows carry. It reads over whatever the route scopes to, so
		// the warehouse page's dc/3pl restriction and any market filter both
		// apply -- the tile and the rows under it cannot disagree.
		"warehouseFillRate": fillRateExpr,
		"outboundNeedUnits": "COALESCE(SUM(need.need_units), 0)",
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
		"locations": "COUNT(DISTINCT location_id)",
		// Store-scoped counts, for the pages that show stores. A page titled
		// Store Inventory must not report a warehouse among its stores at risk.
		"atRiskStores": "COUNT(DISTINCT location_id) FILTER (WHERE " +
			"dim.location_kind = 'store' AND " +
			"health_class IN ('understock', 'stockout', 'overstock'))",
		"stores": "COUNT(DISTINCT location_id) FILTER " +
			"(WHERE dim.location_kind = 'store')",
		"warehouses": "COUNT(DISTINCT location_id) FILTER " +
			"(WHERE dim.location_kind IN ('dc', '3pl'))",
		"coverUnavailableCells": "COUNT(*) FILTER (WHERE cover_days IS NULL)",
		"meanCoverDays":         "AVG(cover_days)",
	},
	"inventory_demand_at_risk": {
		"cells":         "COUNT(*)",
		"assessedCells": "COUNT(*) FILTER (WHERE interval_available)",
		"withheldCells": "COUNT(*) FILTER (WHERE NOT interval_available)",
		"riskUnits":     "COALESCE(SUM(risk_units), 0)",
		"currencyCount": "COUNT(DISTINCT currency_code)",
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
		// Qualified: this aggregate joins the SKU dimension for a unit cost, and
		// the dimension carries a currency_code of its own. Unqualified, pgx
		// rejects the statement and the route fails closed.
		"currencyCount": "COUNT(DISTINCT inventory_expiry_waste.currency_code)",
	},
	"inventory_valuation_by_kind": {
		// `echelon` is this view's own alias for the kind, not the positions
		// projection: valuation has no location_kind of its own.
		"wmsVarianceUnits": "COALESCE(SUM(wms_variance_units), 0)",
		"currencyCount":    "COUNT(DISTINCT currency_code)",
		"unvaluedRows":     "COUNT(*) FILTER (WHERE gross_value_minor IS NULL)",
	},
	"inventory_valuation": {
		// varianceValueMinor is built per request from varianceMoneyAggregates.
		// Written here as a static string, it valued the units at cost and applied
		// no FX -- so a US row's variance entered the rupee total in dollars, and
		// the tile read Rs 2.15 Cr under a by-category table summing to Rs 3.20 Cr.
		"negativeValueRows": "COUNT(*) FILTER (WHERE gross_value_minor < 0)",
		"rows":              "COUNT(*)",
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
		// MOQ and pack-size compliance, which the reference scores as a share.
		// The engine's rounding order is apply_moq, apply_pack_multiple, then
		// apply_caps, and a line whose MOQ cannot be met inside the cover cap is
		// refused with MOQ_EXCEEDS_MAX_COVER rather than emitted rounded-down. So
		// a line that ordered at all cleared both rules, and the refusals are the
		// published complement -- no separate scoring pass is needed.
		"moqCompliantCells": "COUNT(*) FILTER (WHERE recommended_units > 0 " +
			"AND reason_code IS DISTINCT FROM 'MOQ_EXCEEDS_MAX_COVER')",
		"moqRefusedCells": "COUNT(*) FILTER " +
			"(WHERE reason_code = 'MOQ_EXCEEDS_MAX_COVER')",
		// The denominator is lines the solver TRIED to place, not lines it placed.
		// Against cellsToOrder the share is 720 of 720 and can never be anything
		// else -- a line that ordered cleared MOQ by construction -- so the tile
		// would read a permanent 100% and measure nothing. Adding the refusals
		// back makes it 720 of 722: of the orders the solver wanted, the share
		// whose minimum and pack size fitted inside the cover cap.
		"moqAttemptedCells": "COUNT(*) FILTER (WHERE recommended_units > 0 " +
			"OR reason_code = 'MOQ_EXCEEDS_MAX_COVER')",
		// The reference's "High Priority" is a subset of the SUGGESTED ORDERS --
		// 742 of 4,286 -- and this tile was bound to withheldCells, so it read
		// 3,722 cells the engine declined to recommend at all under a caption a
		// buyer reads as "urgent orders".
		//
		// Stockout at the destination, not stockout-or-understock: an order
		// exists mostly BECAUSE the cell is understocked, so that wider test
		// marks 578 of 720 urgent and separates almost nothing. A destination
		// with nothing available to sell is already losing sales, which is what
		// makes its order jump the queue.
		"highPriorityCells": "COUNT(*) FILTER (WHERE recommended_units > 0 " +
			"AND desthealth.health_class = 'stockout')",
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
		"rows":          "COUNT(*)",
		"costedRows":    "COUNT(dim.unit_cost_minor)",
		"units":         "COALESCE(SUM(units), 0)",
		"lanes":         "COUNT(DISTINCT lane_id)",
		"currencyCount": "COUNT(DISTINCT currency_code)",
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
		// No fillRate here, deliberately. Allocated over requested looks like the
		// reference's "Warehouse Fill Rate" and is not: every one of the 2,065
		// allocation rows sits at a STORE, and the projection carries no supply
		// node, so the ratio measures how much STORE demand was allocated, not how
		// well a warehouse served the orders placed on it. Wired to the tile it
		// read 2.2 per cent -- an authoritative-looking number answering a
		// different question.
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

// moneyAggregates names, per projection, the unit column behind each money
// figure. The expression itself is built per request by `fxExpr`, because the
// conversion depends on the approved reporting FX the store was given.
//
// Every one of these renders as rupees in the reference and rendered a unit
// count here until migration 0011 published a cost to multiply by.
var moneyAggregates = map[string]map[string]string{
	// The reference shows "Transfer Value" and "Expected Benefit" as DIFFERENT
	// columns and different KPIs. Value is units at cost; benefit is the
	// lost-sales recovery the optimizer projects. Mapping the caption "Transfer
	// Value" onto expected_benefit_minor answered the wrong question.
	"replenishment_transfers": {
		"transferValueMinor": "units",
	},
	"inventory_ageing": {
		// Each bucket's holding at cost. The reference's four ageing tiles are
		// these, plus a transfer figure from the transfers companion.
		"ageingValueMinor":    "on_hand_units",
		"value60PlusMinor":    "on_hand_units",
		"value90PlusMinor":    "on_hand_units",
		"deadStockValueMinor": "on_hand_units",
		"markdownValueMinor":  "on_hand_units",
	},
	"inventory_expiry_waste": {
		"nearExpiryValueMinor": "expiring_units",
		"wasteValueMinor":      "waste_units",
	},
	// The reference's "Order Value" on Suggested Orders, and the same figure under
	// the `order` prefix on Supplier Planning. It read "Not available" on the
	// grounds that the lines were not costed -- every one of the 720 lines that
	// actually orders carries a cost, and `costedCells` is published beside it so
	// a reader can see that coverage rather than trust it.
	"replenishment_recommendations": {
		"orderValueMinor": "recommended_units",
	},
	"inventory_positions": {
		"onHandValueMinor": "on_hand_units",
		// The reference reads "Inventory at Risk / Rs 8.7 Cr / 17.9% exposure"
		// and notes its own scope: overstock, ageing, expiry. So it is the VALUE
		// of the cells the health engine did not class healthy -- a cell count
		// under a money caption was answering a different question.
		"atRiskValueMinor":    "on_hand_units",
		"atpValueMinor":       "atp_units",
		"inTransitValueMinor": "in_transit_units",
		"reservedValueMinor":  "reserved_units",
		"damagedValueMinor":   "damaged_units",
		"onOrderValueMinor":   "on_order_units",
	},
}

// varianceMoneyAggregates names, per projection, the unit column behind a money
// figure priced at the CATEGORY rollup cost rather than the per-cell dimension
// cost. Separate from moneyAggregates because the cost column differs: valuation
// is held per category and has no single SKU to price against.
var varianceMoneyAggregates = map[string]map[string]string{
	"inventory_valuation": {
		"varianceValueMinor": "wms_variance_units",
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
	// The enterprise money tiles. On-Hand Inventory, Available to Promise and
	// Inventory in Transit are all rupees in the reference and were all unit
	// counts here, because the positions projection carries no cost.
	"inventory_positions": `retail_serving.inventory_positions
		LEFT JOIN retail_serving.inventory_sku_dimension AS dim
		USING (inventory_version_id, market_id, location_id, sku_id)
		LEFT JOIN retail_serving.inventory_stock_health AS health
		USING (inventory_version_id, market_id, location_id, sku_id)` +
		outboundNeedJoin,

	// The reference's ageing tiles are ALL money -- "60+ Day Inventory Rs 14.1
	// Cr", not a unit count -- and the ageing projection carries no cost, so it
	// could only ever report units under a rupee caption. Same grain on both
	// sides, so the join cannot multiply rows.
	"inventory_ageing": `retail_serving.inventory_ageing
		LEFT JOIN retail_serving.inventory_sku_dimension AS dim
		USING (inventory_version_id, market_id, location_id, sku_id)`,

	// Waste likewise: "Near-Expiry Inventory Rs 0.9 Cr" and "Waste This Month
	// Rs 0.22 Cr" are money. exposure_minor is published but covers only the
	// expiring slice, so the waste figure needs units at cost.
	"inventory_expiry_waste": `retail_serving.inventory_expiry_waste
		LEFT JOIN retail_serving.inventory_sku_dimension AS dim
		USING (inventory_version_id, market_id, location_id, sku_id)`,

	// A transfer's value is its units at cost. The dimension is per node and a
	// transfer spans two, so the cost is taken per market x SKU -- the same
	// figure whichever end of the lane it is read from.
	"replenishment_transfers": `retail_serving.replenishment_transfers
		LEFT JOIN (
			SELECT DISTINCT inventory_version_id AS cost_version,
			       market_id AS cost_market, sku_id AS cost_sku,
			       MAX(unit_cost_minor) AS unit_cost_minor,
			       MAX(currency_code) AS currency_code
			FROM retail_serving.inventory_sku_dimension
			GROUP BY inventory_version_id, market_id, sku_id
		) AS dim
		ON dim.cost_version = replenishment_transfers.inventory_version_id
		AND dim.cost_market = replenishment_transfers.market_id
		AND dim.cost_sku = replenishment_transfers.sku_id`,

	// The category cost rollup, so the Variance tile can be money. Same subquery
	// the row projection uses, so tile and table price the variance identically.
	"inventory_valuation": "retail_serving.inventory_valuation" + valuationCostJoin,

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
		     = replenishment_recommendations.supply_location_id
		-- The cost, so an order can be valued. Keyed on the DESTINATION: the
		-- units are being bought INTO that node, and P4-D6 forbids pricing a
		-- store's holding from a DC's cost. Aliased as dim because that is the
		-- name fxExpr and the costedCells companion both reference.
		LEFT JOIN (
			SELECT inventory_version_id AS rc_version, market_id AS rc_market,
			       location_id AS rc_location, sku_id AS rc_sku,
			       unit_cost_minor, currency_code
			FROM retail_serving.inventory_sku_dimension
		) AS dim
		ON dim.rc_version = replenishment_recommendations.inventory_version_id
		AND dim.rc_market = replenishment_recommendations.market_id
		AND dim.rc_location
		     = replenishment_recommendations.destination_location_id
		AND dim.rc_sku = replenishment_recommendations.sku_id
		-- The DESTINATION's health, for how urgent each order is. Every column
		-- but health_class is aliased away on purpose: the health projection
		-- carries a reason_code too, and joined bare it makes the reason_code
		-- this route already reads for MOQ refusals ambiguous, which fails the
		-- whole page closed.
		LEFT JOIN (
			SELECT inventory_version_id AS hc_version, market_id AS hc_market,
			       location_id AS hc_location, sku_id AS hc_sku, health_class
			FROM retail_serving.inventory_stock_health
		) AS desthealth
		ON desthealth.hc_version
		     = replenishment_recommendations.inventory_version_id
		AND desthealth.hc_market = replenishment_recommendations.market_id
		AND desthealth.hc_location
		     = replenishment_recommendations.destination_location_id
		AND desthealth.hc_sku = replenishment_recommendations.sku_id`,

	// Stock health carries no echelon, so a store-scoped page could not ask for
	// "Stores at Risk" and got every node instead -- eight on a page showing
	// four. The dimension carries the kind.
	"inventory_stock_health": `retail_serving.inventory_stock_health
		LEFT JOIN retail_serving.inventory_sku_dimension AS dim
		USING (inventory_version_id, market_id, location_id, sku_id)`,

	"inventory_valuation_by_kind": `retail_serving.inventory_valuation
		JOIN (SELECT DISTINCT inventory_version_id, market_id, location_id,
		             location_kind
		      FROM retail_serving.inventory_positions) AS echelon
		USING (inventory_version_id, market_id, location_id)`,
}

// moneyColumnAggregates names aggregates over a column that is ALREADY money,
// as opposed to moneyAggregates whose entries are unit counts to be multiplied by
// a cost. Both need the approved FX; only the second needs the cost. Every one of
// these was a bare SUM adding rupees to dollars.
var moneyColumnAggregates = map[string]map[string]struct {
	amount   string
	currency string
	filter   string
}{
	"inventory_valuation_by_kind": {
		"grossValueMinor": {"gross_value_minor", "currency_code", ""},
		"storeValueMinor": {
			"gross_value_minor", "currency_code",
			" FILTER (WHERE echelon.location_kind = 'store')",
		},
		"dcValueMinor": {
			"gross_value_minor", "currency_code",
			" FILTER (WHERE echelon.location_kind IN ('dc', '3pl'))",
		},
	},
	"inventory_valuation": {
		"grossValueMinor": {"gross_value_minor", "currency_code", ""},
	},
	"inventory_expiry_waste": {
		// No exposureMinor entry. exposure_minor is NULL on all 2,268 rows in this
		// publication, and the COALESCE every money aggregate needs turned that
		// into a confident "Rs 0.00" on screen -- the bare-unavailable defect
		// wearing a currency symbol. Omitted so the tile withholds with a reason
		// instead of asserting a measured zero.
	},
	"inventory_demand_at_risk": {
		"riskValueMinor": {"risk_value_minor", "currency_code", ""},
	},
	"replenishment_transfers": {
		"expectedBenefitMinor": {
			"expected_benefit_minor", "replenishment_transfers.currency_code", "",
		},
	},
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
	// Published money first, so a table with no unit-based money still gets its
	// amounts converted rather than summed across currencies.
	if columns, wanted := moneyColumnAggregates[table]; wanted {
		converted := make(map[string]string, len(expressions)+len(columns))
		for name, expression := range expressions {
			converted[name] = expression
		}
		for name, column := range columns {
			converted[name] = s.fxMoneySum(
				column.amount, column.currency, column.filter,
			)
		}
		expressions = converted
	}
	if variance, wanted := varianceMoneyAggregates[table]; wanted {
		converted := make(map[string]string, len(expressions)+len(variance))
		for name, expression := range expressions {
			converted[name] = expression
		}
		for name, units := range variance {
			converted[name] = fmt.Sprintf(
				"COALESCE(SUM(%s), 0)", s.rowFXVariance(units),
			)
		}
		expressions = converted
	}
	// Money is built here, not in the static map, because the conversion depends
	// on the approved FX this store was constructed with.
	if money, wanted := moneyAggregates[table]; wanted {
		merged := make(map[string]string, len(expressions)+len(money))
		for name, expression := range expressions {
			merged[name] = expression
		}
		for name, units := range money {
			merged[name] = s.fxExpr(units)
		}
		merged["costedCells"] = "COUNT(dim.unit_cost_minor)"
		merged["currencyCount"] = "COUNT(DISTINCT dim.currency_code)"
		// Position-only. A transfers or safety-stock join carries the cost but
		// neither on_hand_units nor a category, so adding these unconditionally
		// asked the database for columns that are not in scope.
		if table == "inventory_positions" {
			merged["categories"] = "COUNT(DISTINCT dim.category)"
			// Days of supply and stock turn are the same fact twice: cover is
			// on-hand over daily demand, turn is a year divided by cover.
			merged["daysOfSupply"] = "CASE WHEN SUM(dim.trailing_daily_units) > 0 " +
				"THEN SUM(on_hand_units) / SUM(dim.trailing_daily_units) END"
			merged["stockTurn"] = "CASE WHEN SUM(on_hand_units) > 0 " +
				"THEN (SUM(dim.trailing_daily_units) * 365.0) / SUM(on_hand_units) END"
		}
		if table == "inventory_positions" {
			// The reference's own note scopes this tile: "Overstock, ageing,
			// expiry". Named classes rather than "not healthy", which would also
			// sweep in understock and stock-out -- those are lost-sales risk, a
			// different exposure from capital tied up in stock that will not move.
			merged["atRiskValueMinor"] = s.fxExpr("on_hand_units") +
				" FILTER (WHERE health.health_class IN ('overstock', 'dead'))"
			merged["storeValueMinor"] = s.fxExpr("on_hand_units") +
				" FILTER (WHERE inventory_positions.location_kind = 'store')"
			merged["dcValueMinor"] = s.fxExpr("on_hand_units") +
				" FILTER (WHERE inventory_positions.location_kind IN ('dc', '3pl'))"
		}
		if table == "inventory_ageing" {
			// The reference's ageing tiles are cumulative bands, not the engine's
			// disjoint buckets: "60+" includes 90+ and 180+, which is how a
			// merchandiser reads it. Reporting only the 60-90 slice under a "60+"
			// caption would understate the exposure it exists to flag.
			merged["value60PlusMinor"] = s.fxExpr("on_hand_units") +
				" FILTER (WHERE age_bucket IN ('60-90', '90-180', '180-plus'))"
			merged["value90PlusMinor"] = s.fxExpr("on_hand_units") +
				" FILTER (WHERE age_bucket IN ('90-180', '180-plus'))"
			// Dead stock is the de-assorted holding, which is what residual_only
			// marks -- not simply the oldest bucket.
			merged["deadStockValueMinor"] = s.fxExpr("on_hand_units") +
				" FILTER (WHERE residual_only)"
			// The markdown OPPORTUNITY is the provision the markdown would cost --
			// holding times the proposed depth -- not the whole holding that
			// qualifies. The reference puts it at Rs 1.8 Cr against Rs 14.1 Cr of
			// 60-plus stock, a ratio that only makes sense as a percentage of value
			// rather than the value itself, and the artifact carries the depth
			// (markdown_pct, 0.10 here) to multiply by.
			merged["markdownValueMinor"] = s.fxExpr(
				"(on_hand_units * markdown_pct)",
			) + " FILTER (WHERE action = 'markdown_candidate')"
		}
		if table == "inventory_expiry_waste" {
			// "Near-Expiry Inventory" is stock still sellable but inside its expiry
			// window; "Waste This Month" is what was already written off. Two
			// different columns, and the reference gives each its own tile.
			merged["nearExpiryValueMinor"] = s.fxExpr("expiring_units")
			merged["wasteValueMinor"] = s.fxExpr("waste_units")
		}
		expressions = merged
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

// groupedCard runs one card's GROUP BY under the request's own scope.
//
// Scoped through the same typed filters as the page, so a market filter narrows
// the cards and the table together. A filter the card's source cannot express is
// dropped with its argument rather than failing the request.
func (s *InventoryStore) groupedCard(
	ctx context.Context, card groupedCard, filters []inventoryFilter,
	static []string,
) ([]map[string]any, error) {
	base := card.source
	if index := strings.IndexAny(base, " \n\t"); index > 0 {
		base = base[:index]
	}
	base = strings.TrimPrefix(base, "retail_serving.")
	columns := filterableColumns[base]
	// A card joined to the dimension can be scoped by category even when its own
	// projection has no such column.
	joinsDimension := strings.Contains(card.source, "inventory_sku_dimension")
	clauses := []string{"inventory_version_id = $1"}
	args := []any{s.inventoryVersionID}
	// The route's own restriction, so Store Inventory's heatmap is stores and
	// Warehouse Inventory's table is warehouses. A card that ignored this showed
	// every node under a heading that named one echelon.
	for _, clause := range static {
		if strings.Contains(clause, "location_kind") &&
			!strings.Contains(card.source, "inventory_positions") {
			continue
		}
		clauses = append(clauses, clause)
	}
	for _, filter := range filters {
		column := filter.column
		switch {
		case columns[column]:
		case joinsDimension && column == "category":
			column = "dim.category"
		default:
			continue
		}
		args = append(args, filter.value)
		clauses = append(clauses, fmt.Sprintf(
			"%s %s $%d", column, filter.operator, len(args),
		))
	}
	args = append(args, card.limit)
	// A card's money columns carry %[1]s / %[2]s placeholders so the FX
	// conversion is applied with this store's approved rates rather than baked
	// into a literal at package scope.
	onHandValue := s.fxExpr("on_hand_units")
	bufferValue := s.fxExpr("safety_stock_units")
	// %[3]s totals a column that is already money, converting per row first.
	// "Valuation by Category" summed gross_value_minor with a bare SUM, adding
	// dollars to rupees: Rs 26.92 Cr nominal against Rs 106.83 Cr converted.
	valuedAmount := s.fxMoneySum("gross_value_minor", "currency_code", "")
	// Replacement, not Sprintf: a card whose columns carry no placeholder would
	// otherwise pick up "%!(EXTRA string=...)" and ship it into the SQL.
	// %[4]s values the DAMAGED holding. Distinct from %[1]s because a blocked
	// figure filtered on damage but valued on-hand overstates by the whole cell.
	damagedValue := s.fxExpr("damaged_units")
	// %[5]s is a PER-ROW variance at the category rollup cost, so a card using it
	// must wrap it in its own SUM. %[3]s already aggregates; the two are not
	// interchangeable.
	varianceValue := s.rowFXVariance("wms_variance_units")
	replace := strings.NewReplacer(
		"%[1]s", onHandValue, "%[2]s", bufferValue, "%[3]s", valuedAmount,
		"%[4]s", damagedValue, "%[5]s", varianceValue,
	)
	cardColumns := replace.Replace(card.columns)
	cardOrderBy := replace.Replace(card.orderBy)
	statement := fmt.Sprintf(
		"SELECT %s, %s FROM %s WHERE %s GROUP BY %s ORDER BY %s LIMIT $%d",
		card.groupBy, cardColumns, card.source,
		strings.Join(clauses, " AND "), card.groupBy, cardOrderBy, len(args),
	)
	rows, err := s.pool.Query(ctx, statement, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	fields := rows.FieldDescriptions()
	out := make([]map[string]any, 0, card.limit)
	for rows.Next() {
		values, err := rows.Values()
		if err != nil {
			return nil, err
		}
		row := make(map[string]any, len(fields))
		for index := range fields {
			row[snakeToCamel(string(fields[index].Name))] = values[index]
		}
		out = append(out, row)
	}
	return out, rows.Err()
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
