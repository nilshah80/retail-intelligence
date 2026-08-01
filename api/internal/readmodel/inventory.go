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
	pool               *pgxpool.Pool
	reasonCode         string
	message            string
	inventoryVersionID string
	inventoryRunID     string
	semanticFingerprint string
	forecastRunID      string
	forecastVersionID  string
	policyVersion      string
	markets            []string
	decisionAsOf       time.Time
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
		query.Limit = 100
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
			"market_id, location_id, sku_id")
	case "/api/v1/inventory/stores":
		return s.tableSlice(ctx, query, "inventory_positions",
			"market_id, location_id, location_kind, sku_id, on_hand_units, "+
				"atp_units, in_transit_units, assortment_active, residual_only",
			"market_id, location_id, sku_id",
			"location_kind = 'store'")
	case "/api/v1/inventory/warehouses":
		return s.tableSlice(ctx, query, "inventory_positions",
			"market_id, location_id, location_kind, sku_id, on_hand_units, "+
				"committed_units, damaged_units, atp_units",
			"market_id, location_id, sku_id",
			"location_kind IN ('dc', '3pl')")
	case "/api/v1/inventory/ageing":
		return s.tableSlice(ctx, query, "inventory_ageing",
			"market_id, location_id, sku_id, age_bucket, on_hand_units, "+
				"action, markdown_pct, residual_only",
			"market_id, location_id, sku_id, age_bucket")
	case "/api/v1/inventory/transfers":
		return s.tableSlice(ctx, query, "replenishment_transfers",
			"market_id, lane_id, from_location_id, to_location_id, sku_id, "+
				"units, expected_benefit_minor, currency_code, transit_days",
			"market_id, lane_id, sku_id")
	case "/api/v1/inventory/valuation":
		return s.tableSlice(ctx, query, "inventory_valuation",
			"market_id, location_id, category, gross_value_minor, "+
				"currency_code, cost_method, cost_reason_code, wms_variance_units",
			"market_id, location_id, category")
	case "/api/v1/inventory/expiry-waste":
		return s.tableSlice(ctx, query, "inventory_expiry_waste",
			"market_id, location_id, sku_id, expiring_units, expired_units, "+
				"waste_units, exposure_minor, currency_code",
			"market_id, location_id, sku_id")
	case "/api/v1/inventory/stock-health":
		return s.tableSlice(ctx, query, "inventory_stock_health",
			"market_id, location_id, sku_id, health_class, cover_days, reason_code",
			"market_id, location_id, sku_id")
	case "/api/v1/replenishment/planner", "/api/v1/replenishment/orders":
		return s.tableSlice(ctx, query, "replenishment_recommendations",
			"market_id, destination_location_id, supply_location_id, sku_id, "+
				"recommended_units, reorder_point_units, order_up_to_units, "+
				"interval_available, reason_code, erp_status",
			"market_id, destination_location_id, sku_id")
	case "/api/v1/replenishment/suppliers":
		return s.tableSlice(ctx, query, "replenishment_suppliers",
			"market_id, supplier_id, otd_rate, lead_time_mean_days, "+
				"lead_time_std_days, capacity_confirmed_pct, risk_class, reason_codes",
			"market_id, supplier_id")
	case "/api/v1/replenishment/safety-stock":
		return s.tableSlice(ctx, query, "replenishment_safety_stock",
			"market_id, location_id, sku_id, abc_class, service_level, "+
				"safety_stock_units, interval_available, reason_code",
			"market_id, location_id, sku_id")
	case "/api/v1/replenishment/allocations":
		return s.tableSlice(ctx, query, "replenishment_allocations",
			"market_id, location_id, channel_id, sku_id, requested_units, "+
				"allocated_units, shortfall_units",
			"market_id, location_id, channel_id, sku_id")
	case "/api/v1/replenishment/exceptions":
		return s.tableSlice(ctx, query, "replenishment_exceptions",
			"market_id, location_id, sku_id, channel_id, exception_class, "+
				"severity, reason_code, evidence",
			"market_id, exception_class, severity")
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
	orderBy string,
	extraClauses ...string,
) (map[string]any, error) {
	clauses := []string{"inventory_version_id = $1"}
	args := []any{s.inventoryVersionID}
	clauses = append(clauses, extraClauses...)
	if query.MarketID != "" {
		args = append(args, query.MarketID)
		clauses = append(clauses, fmt.Sprintf("market_id = $%d", len(args)))
	}
	if query.StoreID != "" && strings.Contains(columns, "location_id") {
		args = append(args, query.StoreID)
		clauses = append(clauses, fmt.Sprintf("location_id = $%d", len(args)))
	}
	if query.Category != "" && strings.Contains(columns, "category") {
		args = append(args, query.Category)
		clauses = append(clauses, fmt.Sprintf("category = $%d", len(args)))
	}
	if query.Search != "" && strings.Contains(columns, "sku_id") {
		args = append(args, "%"+query.Search+"%")
		clauses = append(clauses, fmt.Sprintf("sku_id ILIKE $%d", len(args)))
	}
	args = append(args, query.Limit, query.Offset)
	statement := fmt.Sprintf(
		`SELECT COUNT(*) OVER(), %s FROM retail_serving.%s
		 WHERE %s ORDER BY %s LIMIT $%d OFFSET $%d`,
		columns, table, strings.Join(clauses, " AND "), orderBy,
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
	return payload, nil
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
