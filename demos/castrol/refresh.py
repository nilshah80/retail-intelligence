"""Refresh catalog-dependent totals in the disposable serving projection.

The caller owns the isolated connection and transaction. This module never
commits, starts services, alters original artifacts, or trains models. Original
predictions and canonical facts are opened read-only to recalculate aggregates
after excluded products have been removed from the clone.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Callable

import duckdb
import pandas as pd
from psycopg import sql
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = "run-73ba460b02d63c40"
SOURCE_CANONICAL = ROOT / "ingestion/data/curated" / SOURCE_RUN / "retail_v2.duckdb"
SOURCE_EVALUATION = (
    ROOT / "ml/data/artifacts/backtest_gulf-rust-perf1/forecast_eval_predictions.parquet"
)


def _value(value):
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _refresh_forecast(cur, excluded: set[str], transform: Callable[[str], str]):
    from retail_ml.publish import run_artifacts as publisher

    identities = cur.execute(
        "SELECT forecast_run_id, version_id FROM retail_serving.forecast_materializations"
    ).fetchall()
    if len(identities) != 1:
        raise ValueError("The disposable refresh requires exactly one source forecast run")
    run_id, version_id = identities[0]
    columns = list(dict.fromkeys([
        *publisher.EVALUATION_KEY_COLUMNS, "dept_id", "category", "actual_units",
        "expected_units", "yhat_p50", "yhat_p90", "zero_share_52w",
        *publisher.BASELINE_COLUMNS.values(),
    ]))
    evaluation = pd.read_parquet(
        SOURCE_EVALUATION, columns=columns,
        filters=[("sku_id", "not in", sorted(excluded))] if excluded else None,
    )
    served_rows = cur.execute(
        "SELECT count(*) FROM retail_serving.forecast_eval_predictions WHERE forecast_run_id=%s",
        (run_id,),
    ).fetchone()[0]
    if len(evaluation) != served_rows:
        raise ValueError("Filtered source predictions do not match the clone's forecast row count")

    # Individual retained series are unchanged. Preserve their published metrics
    # and avoid rebuilding millions of series/model/horizon metric rows.
    original = publisher._metric_rows_for_scope

    def aggregate_rows(*args, **kwargs):
        if kwargs.get("scope_type") == "series":
            return []
        return original(*args, **kwargs)

    publisher._metric_rows_for_scope = aggregate_rows
    try:
        metrics = publisher.derive_forecast_metrics(evaluation)
    finally:
        publisher._metric_rows_for_scope = original
    del evaluation
    metrics["slice_id"] = metrics["slice_id"].map(transform)
    cur.execute(
        "DELETE FROM retail_serving.forecast_metrics WHERE forecast_run_id=%s AND slice_type<>'series'",
        (run_id,),
    )
    # A series slice stores its SKU inside a JSON-array text key.
    transformed_exclusions = [transform(sku) for sku in sorted(excluded)]
    cur.execute(
        "DELETE FROM retail_serving.forecast_metrics WHERE forecast_run_id=%s "
        "AND (CASE WHEN slice_type='series' THEN slice_id::jsonb->>0 END)=ANY(%s)",
        (run_id, transformed_exclusions),
    )
    cur.execute(
        "DELETE FROM retail_serving.forecast_drivers WHERE forecast_run_id=%s "
        "AND (CASE WHEN scope LIKE 'series:%%' THEN substring(scope from 8)::jsonb->>0 END)=ANY(%s)",
        (run_id, transformed_exclusions),
    )
    metric_columns = list(metrics.columns)
    statement = sql.SQL("COPY retail_serving.forecast_metrics ({}) FROM STDIN").format(
        sql.SQL(",").join(sql.Identifier(c) for c in ["forecast_run_id", *metric_columns])
    )
    with cur.copy(statement) as copy:
        for row in metrics.itertuples(index=False, name=None):
            copy.write_row((run_id, *(_value(value) for value in row)))
    global_metric = metrics.loc[
        metrics.slice_type.eq("global") & metrics.slice_id.eq("portfolio")
        & metrics.horizon.eq(0) & metrics.model_id.eq("champion")
    ]
    if len(global_metric) != 1:
        raise ValueError("Expected exactly one refreshed global champion metric")
    global_metric = global_metric.iloc[0]
    demand = cur.execute(
        "SELECT coalesce(sum(expected_units),0) FROM retail_serving.forecast_series WHERE version_id=%s",
        (version_id,),
    ).fetchone()[0]
    cur.execute(
        "UPDATE retail_serving.forecast_versions SET accuracy=%s,bias=%s,demand_units=%s WHERE version_id=%s",
        (float(global_metric.accuracy), float(global_metric.bias), round(float(demand)), version_id),
    )
    tables = cur.execute(
        "SELECT table_name FROM information_schema.columns WHERE table_schema='retail_serving' "
        "AND column_name='forecast_run_id' AND table_name NOT LIKE 'active_%%' ORDER BY table_name"
    ).fetchall()
    counts = {}
    for (table,) in tables:
        if table in {"forecast_materializations", "forecast_activation_events", "inventory_materializations"}:
            continue
        counts[table] = cur.execute(
            sql.SQL("SELECT count(*) FROM retail_serving.{} WHERE forecast_run_id=%s").format(sql.Identifier(table)),
            (run_id,),
        ).fetchone()[0]
    cur.execute(
        "UPDATE retail_serving.forecast_materializations SET row_counts=%s WHERE forecast_run_id=%s",
        (Jsonb(counts), run_id),
    )
    return {"aggregateMetricsRebuilt": len(metrics), "retainedEvaluationRows": served_rows,
            "forecastDemandUnits": round(float(demand)), "rowCounts": counts}


def _canonical(excluded: set[str], as_of):
    """Filtered in-memory views over an attached, read-only source database."""
    connection = duckdb.connect()
    escaped = str(SOURCE_CANONICAL).replace("'", "''")
    connection.execute(f"ATTACH '{escaped}' AS original (READ_ONLY)")
    connection.register("excluded_skus", pd.DataFrame({"sku_id": sorted(excluded)}, dtype="string"))
    source = "original.canonical_data"
    for table in ["products", "store_shortfall_events", "stock_snapshots", "wms_inventory_comparisons", "inbound_shipments"]:
        connection.execute(
            f"CREATE TEMP VIEW {table} AS SELECT * FROM {source}.{table} "
            "WHERE sku_id NOT IN (SELECT sku_id FROM excluded_skus)"
        )
    for table in ["locations", "warehouse_capacity_snapshots", "suppliers", "suppliers_leadtimes", "supplier_performance"]:
        connection.execute(f"CREATE TEMP VIEW {table} AS SELECT * FROM {source}.{table}")
    # Shipment status is one row per lifecycle transition; quantity belongs to
    # its merchandise lines. Keep transitions for shipments with retained lines
    # and use retained-line quantities, including mixed-product shipments.
    end = (as_of + timedelta(days=1)).isoformat()
    connection.execute(
        f"CREATE TEMP VIEW inbound_shipment_status_events AS "
        "SELECT status.* REPLACE (lines.retained_qty AS qty) "
        f"FROM {source}.inbound_shipment_status_events AS status "
        "JOIN (SELECT shipment_id, sum(qty)::BIGINT AS retained_qty FROM inbound_shipments "
        f"WHERE known_as_of < TIMESTAMPTZ '{end}' GROUP BY shipment_id) AS lines USING(shipment_id)"
    )
    connection.execute(
        f"CREATE TEMP VIEW supply_terms AS SELECT * FROM {source}.supply_terms "
        "WHERE (merch_scope_type<>'sku' OR merch_scope_id NOT IN (SELECT sku_id FROM excluded_skus)) "
        "AND (merch_scope_type<>'category' OR merch_scope_id IN (SELECT DISTINCT category FROM products)) "
        "AND (merch_scope_type<>'dept' OR merch_scope_id IN (SELECT DISTINCT dept_id FROM products))"
    )
    return connection


def _refresh_inventory(cur, source, version, as_of, transform):
    from retail_ml.inventory_run.load import (
        load_inbound_summary, load_open_purchase_orders, load_suppliers,
        load_warehouse_capacity, load_wms_variance,
    )

    # Valuation is stored per category. Regroup the retained stock/cost rows,
    # including partial-category removals, and keep missing costs unavailable.
    cur.execute(
        "DELETE FROM retail_serving.inventory_valuation v WHERE inventory_version_id=%s "
        "AND NOT EXISTS (SELECT 1 FROM retail_serving.inventory_sku_dimension d "
        "WHERE d.inventory_version_id=v.inventory_version_id AND d.market_id=v.market_id "
        "AND d.location_id=v.location_id AND d.category=v.category)", (version,),
    )
    cur.execute("""
        WITH totals AS (
          SELECT p.inventory_version_id,p.market_id,p.location_id,d.category,
                 CASE WHEN count(*) FILTER (WHERE d.unit_cost_minor IS NULL)=0
                      THEN sum(p.on_hand_units*d.unit_cost_minor)::BIGINT END AS value
          FROM retail_serving.inventory_positions p JOIN retail_serving.inventory_sku_dimension d
          USING(inventory_version_id,market_id,location_id,sku_id)
          WHERE p.inventory_version_id=%s GROUP BY 1,2,3,4
        ) UPDATE retail_serving.inventory_valuation v
          SET gross_value_minor=totals.value,
              cost_reason_code=CASE WHEN totals.value IS NULL THEN 'COST_EVIDENCE_UNAVAILABLE' ELSE NULL END
          FROM totals WHERE v.inventory_version_id=totals.inventory_version_id
          AND v.market_id=totals.market_id AND v.location_id=totals.location_id AND v.category=totals.category
        """, (version,))
    dimensions = cur.execute(
        "SELECT market_id,location_id,sku_id,category,unit_cost_minor FROM retail_serving.inventory_sku_dimension "
        "WHERE inventory_version_id=%s", (version,),
    ).fetchall()
    dim = {(m, l, s): (cat, cost) for m, l, s, cat, cost in dimensions}
    variances = load_wms_variance(source, as_of=as_of)
    grouped_variance = {}
    for row in variances.itertuples(index=False):
        key = tuple(transform(str(value)) for value in (row.market_id, row.location_id, row.sku_id))
        if key not in dim:
            continue
        group = (key[0], key[1], dim[key][0])
        grouped_variance[group] = grouped_variance.get(group, 0) + int(row.variance_units)
    cur.execute("UPDATE retail_serving.inventory_valuation SET wms_variance_units=NULL WHERE inventory_version_id=%s", (version,))
    cur.executemany(
        "UPDATE retail_serving.inventory_valuation SET wms_variance_units=%s WHERE inventory_version_id=%s "
        "AND market_id=%s AND location_id=%s AND category=%s",
        [(value, version, *key) for key, value in grouped_variance.items()],
    )
    capacities = load_warehouse_capacity(source, as_of=as_of)
    for row in capacities.itertuples(index=False):
        cur.execute(
            "UPDATE retail_serving.inventory_warehouse_capacity SET fill_demand_units=%s,fill_served_units=%s,"
            "fill_window_start=%s,fill_window_end=%s WHERE inventory_version_id=%s AND market_id=%s AND location_id=%s",
            (int(row.fill_demand_units), int(row.fill_served_units), row.fill_window_start, row.fill_window_end,
             version, transform(str(row.market_id)), transform(str(row.location_id))),
        )
    inbound = load_inbound_summary(source, as_of=as_of)
    cur.execute("DELETE FROM retail_serving.inventory_inbound_summary WHERE inventory_version_id=%s", (version,))
    cur.executemany(
        "INSERT INTO retail_serving.inventory_inbound_summary "
        "(inventory_version_id,market_id,location_id,open_shipments,open_units,received_shipments,late_shipments) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        [(version, transform(str(r.market_id)), transform(str(r.location_id)), int(r.open_shipments),
          int(r.open_units), int(r.received_shipments), int(r.late_shipments)) for r in inbound.itertuples(index=False)],
    )
    suppliers = load_suppliers(source, as_of=as_of)
    for row in suppliers.itertuples(index=False):
        category = transform(str(row.category)) if pd.notna(row.category) else None
        labels = cur.execute(
            "SELECT max(category_label) FROM retail_serving.inventory_sku_dimension "
            "WHERE inventory_version_id=%s AND category=%s", (version, category),
        ).fetchone()[0]
        cur.execute(
            "UPDATE retail_serving.replenishment_suppliers SET category=%s,category_label=%s,scope_count=%s "
            "WHERE inventory_version_id=%s AND market_id=%s AND supplier_id=%s",
            (category if labels else None, labels, _value(row.scope_count), version,
             transform(str(row.market_id)), transform(str(row.supplier_id))),
        )
    open_orders = load_open_purchase_orders(source, as_of=as_of)
    open_by_supplier = {}
    for row in open_orders.itertuples(index=False):
        market, supplier, location, sku = map(transform, map(str, (row.market_id, row.supplier_id, row.location_id, row.sku_id)))
        if (market, location, sku) not in dim:
            continue
        cost = dim[(market, location, sku)][1]
        units, value, complete = open_by_supplier.get((market, supplier), (0, 0, True))
        units += int(row.open_units)
        value += int(row.open_units) * int(cost or 0)
        open_by_supplier[(market, supplier)] = (units, value, complete and cost is not None)
    cur.execute("UPDATE retail_serving.replenishment_suppliers SET open_po_units=0,open_po_value_minor=0 WHERE inventory_version_id=%s", (version,))
    cur.executemany(
        "UPDATE retail_serving.replenishment_suppliers SET open_po_units=%s,open_po_value_minor=%s "
        "WHERE inventory_version_id=%s AND market_id=%s AND supplier_id=%s",
        [(units, value if complete else None, version, *key) for key, (units, value, complete) in open_by_supplier.items()],
    )
    return {"warehouseServiceNodes": len(capacities), "inboundNodes": len(inbound),
            "valuationVarianceGroups": len(grouped_variance), "supplierScopesRefreshed": len(suppliers),
            "physicalCapacityAndBlockedUnits": "Retained source node-level capacity/blocked snapshot; no SKU decomposition exists for blocked units."}


def _refresh_promotions(cur, source, excluded, transform):
    targets = source.execute(
        "SELECT promo_id,merch_scope_id FROM original.canonical_data.promotion_merchandise_targets "
        "WHERE merch_scope_type='sku' GROUP BY 1,2"
    ).fetchall()
    affected = {transform(str(promo)) for promo, sku in targets if sku in excluded}
    removed = []
    for bundle, details in cur.execute(
        "SELECT bundle_id,details FROM retail_serving.pricing_promotion_dispositions"
    ).fetchall():
        keep = []
        for item in details.get("acceptedPromotions", []):
            if item.get("promoId") in affected:
                removed.append(item.get("promoId"))
            else:
                keep.append(item)
        details["acceptedPromotions"] = keep
        cur.execute(
            "UPDATE retail_serving.pricing_promotion_dispositions SET details=%s WHERE bundle_id=%s",
            (Jsonb(details), bundle),
        )
    return {"removedPromotionsWithExcludedProducts": removed,
            "retainedPromotionEstimates": "Only unchanged merchandise populations retain their original synthetic estimates."}


def refresh(conn, excluded_skus, transform: Callable[[str], str]):
    """Refresh the already-transformed clone inside the caller's transaction.

    ``excluded_skus`` contains original canonical identifiers, and ``transform``
    is the caller's consistent text/identifier mapping. The complete original
    backtest and curated DuckDB must exist; failures propagate and roll back the
    caller's transaction instead of silently leaving inconsistent aggregates.
    """
    excluded = set(excluded_skus)
    with conn.cursor(row_factory=tuple_row) as cur:
        inventory = cur.execute(
            "SELECT inventory_version_id,decision_as_of FROM retail_serving.inventory_versions"
        ).fetchall()
        if len(inventory) != 1:
            raise ValueError("The disposable refresh requires exactly one inventory version")
        version, decision = inventory[0]
        report = {"forecast": _refresh_forecast(cur, excluded, transform)}
        source = _canonical(excluded, decision.date())
        try:
            report["inventory"] = _refresh_inventory(cur, source, version, decision.date(), transform)
            report["promotions"] = _refresh_promotions(cur, source, excluded, transform)
        finally:
            source.close()
        return report
