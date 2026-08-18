package readmodel

import (
	"context"
	"fmt"
	"sort"
	"time"
)

const ExecutiveOverviewSchema = "retail-executive-overview/v1"

type executiveSalesMetric struct {
	ScopeKey      string
	PeriodKey     string
	Start         time.Time
	End           time.Time
	Revenue       float64
	CostedRevenue float64
	COGS          float64
	NetUnits      int64
	CostedRows    int64
	Rows          int64
}

type executiveInventoryMetric struct {
	ScopeKey       string
	ValueMinor     float64
	OverstockMinor float64
	OnHandUnits    float64
	DailyUnits     float64
	StockoutCells  int64
	Cells          int64
	CostedCells    int64
}

func executiveGrowth(current, prior float64) *float64 {
	if prior == 0 {
		return nil
	}
	value := 100 * (current - prior) / prior
	return &value
}

func executiveMargin(metric executiveSalesMetric) *float64 {
	if metric.CostedRevenue == 0 || metric.CostedRows == 0 {
		return nil
	}
	value := 100 * (metric.CostedRevenue - metric.COGS) / metric.CostedRevenue
	return &value
}

func appendExecutiveFilter(
	clauses *[]string,
	args *[]any,
	column string,
	value string,
) {
	if value == "" {
		return
	}
	*args = append(*args, value)
	*clauses = append(*clauses, fmt.Sprintf("%s = $%d", column, len(*args)))
}

func executiveDimensionExpression(dimension, alias string) (string, error) {
	switch dimension {
	case "portfolio":
		return "'portfolio'", nil
	case "store":
		return alias + ".store_id", nil
	case "region":
		return alias + ".region", nil
	case "category":
		return alias + ".category", nil
	default:
		return "", fmt.Errorf("unsupported executive dimension %q", dimension)
	}
}

func (s *InventoryStore) executiveSalesMetrics(
	ctx context.Context,
	query InventoryQuery,
	dimension string,
) (map[string]map[string]executiveSalesMetric, map[string]map[string]string, error) {
	expression, err := executiveDimensionExpression(dimension, "sales")
	if err != nil {
		return nil, nil, err
	}
	clauses := []string{"sales.forecast_run_id = $1"}
	args := []any{s.forecastRunID, s.inventoryVersionID}
	appendExecutiveFilter(&clauses, &args, "sales.market_id", query.MarketID)
	appendExecutiveFilter(&clauses, &args, "sales.region", query.Region)
	appendExecutiveFilter(&clauses, &args, "sales.store_id", query.StoreID)
	appendExecutiveFilter(&clauses, &args, "sales.channel_type", query.ChannelType)
	appendExecutiveFilter(&clauses, &args, "sales.category", query.Category)
	revenue := s.fxMoneySum("sales.net_sales_minor", "sales.currency_code", "")
	costedRevenue := s.fxMoneySum(
		"sales.net_sales_minor",
		"sales.currency_code",
		" FILTER (WHERE dim.unit_cost_minor IS NOT NULL)",
	)
	cogs := s.fxExpr("sales.net_units")
	rows, err := s.pool.Query(ctx, fmt.Sprintf(`
		SELECT
			%s AS scope_key,
			sales.period_key,
			MIN(sales.period_start),
			MAX(sales.period_end),
			(%s)::double precision AS revenue_minor,
			(%s)::double precision AS costed_revenue_minor,
			COALESCE((%s)::double precision, 0) AS cogs_minor,
			COALESCE(SUM(sales.net_units), 0)::bigint AS net_units,
			COUNT(dim.unit_cost_minor) AS costed_rows,
			COUNT(*) AS rows
		FROM retail_serving.executive_sales AS sales
		LEFT JOIN retail_serving.inventory_sku_dimension AS dim
		  ON dim.inventory_version_id = $2
		 AND dim.market_id = sales.market_id
		 AND dim.location_id = sales.store_id
		 AND dim.sku_id = sales.sku_id
		WHERE %s
		GROUP BY 1, 2
		ORDER BY 1, 2
	`, expression, revenue, costedRevenue, cogs, joinClauses(clauses)), args...)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()
	metrics := map[string]map[string]executiveSalesMetric{}
	periods := map[string]map[string]string{}
	for rows.Next() {
		var metric executiveSalesMetric
		if err := rows.Scan(
			&metric.ScopeKey,
			&metric.PeriodKey,
			&metric.Start,
			&metric.End,
			&metric.Revenue,
			&metric.CostedRevenue,
			&metric.COGS,
			&metric.NetUnits,
			&metric.CostedRows,
			&metric.Rows,
		); err != nil {
			return nil, nil, err
		}
		if metrics[metric.ScopeKey] == nil {
			metrics[metric.ScopeKey] = map[string]executiveSalesMetric{}
		}
		metrics[metric.ScopeKey][metric.PeriodKey] = metric
		periods[metric.PeriodKey] = map[string]string{
			"start": metric.Start.Format("2006-01-02"),
			"end":   metric.End.Format("2006-01-02"),
		}
	}
	return metrics, periods, rows.Err()
}

func joinClauses(clauses []string) string {
	result := ""
	for index, clause := range clauses {
		if index > 0 {
			result += " AND "
		}
		result += clause
	}
	return result
}

func (s *InventoryStore) executiveInventoryMetrics(
	ctx context.Context,
	query InventoryQuery,
	dimension string,
) (map[string]executiveInventoryMetric, error) {
	expression, err := executiveDimensionExpression(dimension, "scope")
	if err != nil {
		return nil, err
	}
	// Inventory has no channel grain. Channel scoping remains exact for sales and
	// forecast, while these physical-position measures retain their store/category
	// scope and the payload says so explicitly.
	clauses := []string{
		"positions.inventory_version_id = $1",
		"positions.location_kind = 'store'",
	}
	args := []any{s.inventoryVersionID, s.forecastRunID}
	appendExecutiveFilter(&clauses, &args, "positions.market_id", query.MarketID)
	appendExecutiveFilter(&clauses, &args, "positions.location_id", query.StoreID)
	appendExecutiveFilter(&clauses, &args, "stores.region", query.Region)
	appendExecutiveFilter(&clauses, &args, "dim.category", query.Category)
	value := s.fxExpr("positions.on_hand_units")
	overstock := s.fxExpr("positions.on_hand_units") +
		" FILTER (WHERE health.health_class = 'overstock')"
	rows, err := s.pool.Query(ctx, fmt.Sprintf(`
		SELECT
			%s AS scope_key,
			COALESCE((%s)::double precision, 0) AS value_minor,
			COALESCE((%s)::double precision, 0) AS overstock_minor,
			COALESCE(SUM(positions.on_hand_units), 0)::double precision,
			COALESCE(SUM(dim.trailing_daily_units), 0)::double precision,
			COUNT(*) FILTER (WHERE health.health_class = 'stockout'),
			COUNT(*),
			COUNT(dim.unit_cost_minor)
		FROM retail_serving.inventory_positions AS positions
		LEFT JOIN retail_serving.inventory_sku_dimension AS dim
		USING (inventory_version_id, market_id, location_id, sku_id)
		LEFT JOIN retail_serving.inventory_stock_health AS health
		USING (inventory_version_id, market_id, location_id, sku_id)
		JOIN retail_serving.forecast_stores AS stores
		  ON stores.forecast_run_id = $2
		 AND stores.store_id = positions.location_id
		CROSS JOIN LATERAL (
			SELECT positions.location_id AS store_id,
			       stores.region,
			       dim.category
		) AS scope
		WHERE %s
		GROUP BY 1
		ORDER BY 1
	`, expression, value, overstock, joinClauses(clauses)), args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	metrics := map[string]executiveInventoryMetric{}
	for rows.Next() {
		var metric executiveInventoryMetric
		if err := rows.Scan(
			&metric.ScopeKey,
			&metric.ValueMinor,
			&metric.OverstockMinor,
			&metric.OnHandUnits,
			&metric.DailyUnits,
			&metric.StockoutCells,
			&metric.Cells,
			&metric.CostedCells,
		); err != nil {
			return nil, err
		}
		metrics[metric.ScopeKey] = metric
	}
	return metrics, rows.Err()
}

func (s *InventoryStore) executiveForecastAccuracy(
	ctx context.Context,
	query InventoryQuery,
	dimension string,
) (map[string]*float64, error) {
	if dimension != "portfolio" && dimension != "region" {
		return nil, fmt.Errorf("unsupported executive forecast dimension %q", dimension)
	}
	joins := ""
	expression := "'portfolio'"
	if dimension == "region" || query.Region != "" {
		joins += `
			JOIN retail_serving.forecast_stores AS stores
			  ON stores.forecast_run_id = evaluation.forecast_run_id
			 AND stores.store_id = evaluation.store_id`
	}
	if dimension == "region" {
		expression = "stores.region"
	}
	args := []any{s.forecastRunID}
	if query.ChannelType != "" {
		args = append(args, s.forecastVersionID)
		joins += fmt.Sprintf(`
			JOIN retail_serving.forecast_series_dimensions AS dimensions
			  ON dimensions.version_id = $%d
			 AND dimensions.sku_id = evaluation.sku_id
			 AND dimensions.store_id = evaluation.store_id
			 AND dimensions.channel_id = evaluation.channel_id`, len(args))
	}
	clauses := []string{
		"evaluation.forecast_run_id = $1",
		"evaluation.horizon <= 4",
	}
	appendExecutiveFilter(&clauses, &args, "evaluation.market_id", query.MarketID)
	appendExecutiveFilter(&clauses, &args, "evaluation.store_id", query.StoreID)
	appendExecutiveFilter(&clauses, &args, "stores.region", query.Region)
	appendExecutiveFilter(&clauses, &args, "dimensions.channel_type", query.ChannelType)
	appendExecutiveFilter(&clauses, &args, "evaluation.category", query.Category)
	rows, err := s.pool.Query(ctx, fmt.Sprintf(`
		WITH cells AS (
			SELECT
				%s AS scope_key,
				evaluation.forecast_origin,
				evaluation.target_week_start,
				evaluation.horizon,
				SUM(evaluation.actual_units) AS actual,
				SUM(evaluation.expected_units) AS predicted
			FROM retail_serving.forecast_eval_predictions AS evaluation%s
			WHERE %s
			GROUP BY 1, 2, 3, 4
		), metrics AS (
			SELECT
				scope_key,
				SUM(ABS(predicted - actual)) AS abs_error_sum,
				SUM(actual) AS actual_sum
			FROM cells
			GROUP BY scope_key
		)
		SELECT
			scope_key,
			CASE WHEN actual_sum = 0 THEN NULL
			ELSE 100.0 * (1.0 - abs_error_sum / actual_sum) END
		FROM metrics
		ORDER BY scope_key
	`, expression, joins, joinClauses(clauses)), args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	metrics := map[string]*float64{}
	for rows.Next() {
		var key string
		var accuracy *float64
		if err := rows.Scan(&key, &accuracy); err != nil {
			return nil, err
		}
		metrics[key] = accuracy
	}
	return metrics, rows.Err()
}

func metricPeriod(
	metrics map[string]map[string]executiveSalesMetric,
	key string,
	period string,
) executiveSalesMetric {
	return metrics[key][period]
}

func executiveSalesPayload(
	current executiveSalesMetric,
	prior executiveSalesMetric,
	prefix string,
) map[string]any {
	return map[string]any{
		prefix + "RevenueMinor":        current.Revenue,
		prefix + "PriorRevenueMinor":   prior.Revenue,
		prefix + "GrowthPct":           executiveGrowth(current.Revenue, prior.Revenue),
		prefix + "GrossMarginPct":      executiveMargin(current),
		prefix + "PriorGrossMarginPct": executiveMargin(prior),
		prefix + "NetUnits":            current.NetUnits,
		prefix + "CostCoveragePct": func() float64 {
			if current.Rows == 0 {
				return 0
			}
			return 100 * float64(current.CostedRows) / float64(current.Rows)
		}(),
	}
}

func inventoryPayload(metric executiveInventoryMetric) map[string]any {
	days := (*float64)(nil)
	if metric.DailyUnits > 0 {
		value := metric.OnHandUnits / metric.DailyUnits
		days = &value
	}
	sellThrough := (*float64)(nil)
	moved := 91 * metric.DailyUnits
	if moved+metric.OnHandUnits > 0 {
		value := 100 * moved / (moved + metric.OnHandUnits)
		sellThrough = &value
	}
	stockoutRate := (*float64)(nil)
	if metric.Cells > 0 {
		value := 100 * float64(metric.StockoutCells) / float64(metric.Cells)
		stockoutRate = &value
	}
	return map[string]any{
		"inventoryValueMinor": metric.ValueMinor,
		"overstockValueMinor": metric.OverstockMinor,
		"inventoryDays":       days,
		"sellThroughPct":      sellThrough,
		"stockoutRatePct":     stockoutRate,
		"stockoutCells":       metric.StockoutCells,
		"inventoryCells":      metric.Cells,
	}
}

func mergePayload(left, right map[string]any) map[string]any {
	merged := make(map[string]any, len(left)+len(right))
	for key, value := range left {
		merged[key] = value
	}
	for key, value := range right {
		merged[key] = value
	}
	return merged
}

func (s *InventoryStore) executiveOverview(
	ctx context.Context,
	query InventoryQuery,
) (map[string]any, error) {
	portfolioSales, periods, err := s.executiveSalesMetrics(ctx, query, "portfolio")
	if err != nil {
		return nil, err
	}
	storeSales, _, err := s.executiveSalesMetrics(ctx, query, "store")
	if err != nil {
		return nil, err
	}
	regionSales, _, err := s.executiveSalesMetrics(ctx, query, "region")
	if err != nil {
		return nil, err
	}
	categorySales, _, err := s.executiveSalesMetrics(ctx, query, "category")
	if err != nil {
		return nil, err
	}
	portfolioInventory, err := s.executiveInventoryMetrics(ctx, query, "portfolio")
	if err != nil {
		return nil, err
	}
	storeInventory, err := s.executiveInventoryMetrics(ctx, query, "store")
	if err != nil {
		return nil, err
	}
	regionInventory, err := s.executiveInventoryMetrics(ctx, query, "region")
	if err != nil {
		return nil, err
	}
	categoryInventory, err := s.executiveInventoryMetrics(ctx, query, "category")
	if err != nil {
		return nil, err
	}
	portfolioAccuracy, err := s.executiveForecastAccuracy(ctx, query, "portfolio")
	if err != nil {
		return nil, err
	}
	regionAccuracy, err := s.executiveForecastAccuracy(ctx, query, "region")
	if err != nil {
		return nil, err
	}

	currentLTM := metricPeriod(portfolioSales, "portfolio", "ltm")
	priorLTM := metricPeriod(portfolioSales, "portfolio", "prior_ltm")
	currentMonth := metricPeriod(portfolioSales, "portfolio", "month_to_date")
	priorMonth := metricPeriod(
		portfolioSales, "portfolio", "prior_year_month_to_date",
	)
	summary := executiveSalesPayload(currentLTM, priorLTM, "ltm")
	month := executiveSalesPayload(currentMonth, priorMonth, "month")
	for key, value := range month {
		summary[key] = value
	}
	for key, value := range inventoryPayload(portfolioInventory["portfolio"]) {
		summary[key] = value
	}
	summary["forecastAccuracyPct"] = portfolioAccuracy["portfolio"]
	if current := executiveMargin(currentLTM); current != nil {
		if prior := executiveMargin(priorLTM); prior != nil {
			summary["grossMarginDeltaPts"] = *current - *prior
		}
	}

	stores := make([]map[string]any, 0, len(storeSales))
	for key, values := range storeSales {
		row := executiveSalesPayload(
			values["month_to_date"], values["prior_year_month_to_date"], "month",
		)
		row["storeId"] = key
		row = mergePayload(row, inventoryPayload(storeInventory[key]))
		stores = append(stores, row)
	}
	sort.Slice(stores, func(i, j int) bool {
		return stores[i]["storeId"].(string) < stores[j]["storeId"].(string)
	})
	regions := make([]map[string]any, 0, len(regionSales))
	for key, values := range regionSales {
		row := executiveSalesPayload(
			values["quarter_to_date"],
			values["prior_year_quarter_to_date"],
			"quarter",
		)
		row["region"] = key
		row["forecastAccuracyPct"] = regionAccuracy[key]
		row = mergePayload(row, inventoryPayload(regionInventory[key]))
		regions = append(regions, row)
	}
	sort.Slice(regions, func(i, j int) bool {
		return regions[i]["region"].(string) < regions[j]["region"].(string)
	})
	categories := make([]map[string]any, 0, len(categorySales))
	for key, values := range categorySales {
		row := executiveSalesPayload(
			values["quarter_to_date"],
			values["prior_year_quarter_to_date"],
			"quarter",
		)
		row["category"] = key
		row = mergePayload(row, inventoryPayload(categoryInventory[key]))
		categories = append(categories, row)
	}
	sort.Slice(categories, func(i, j int) bool {
		return categories[i]["category"].(string) < categories[j]["category"].(string)
	})

	payload := s.envelope(ExecutiveOverviewSchema)
	payload["decisionAsOf"] = s.decisionAsOf.UTC().Format(time.RFC3339Nano)
	payload["periods"] = periods
	payload["summary"] = summary
	payload["stores"] = stores
	payload["regions"] = regions
	payload["categories"] = categories
	payload["basis"] = map[string]any{
		"revenue":          "Canonical net sales after typed financial refunds.",
		"grossMargin":      "Cost-covered net sales less net fulfilled units valued at the current accepted store-receipt WAC; coverage is published with each measure.",
		"comparison":       "Current period compared with the same prior-year period; no plan target is inferred.",
		"inventory":        "Current accepted store positions and trailing 91-day demand velocity.",
		"forecastAccuracy": "Exact additive portfolio WAPE over comparable horizons 1-4.",
	}
	payload["scopeNotes"] = map[string]any{
		"inventoryChannelScope":       query.ChannelType == "",
		"inventoryChannelScopeReason": "Physical inventory has no channel grain; a channel filter scopes sales and forecast only.",
	}
	return payload, nil
}
