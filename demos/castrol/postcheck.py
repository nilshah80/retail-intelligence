"""Finalize and audit the isolated demo without creating new model claims.

These helpers use the caller's connection and transaction and never commit.
``audit`` is read-only. ``finalize`` updates projection metadata and withholds
source replay benefit projections whose merchandise population has changed.
"""

from __future__ import annotations

from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb


def finalize(conn) -> dict:
    """Refresh context counts and suppress unrecomputed replay benefit claims."""
    with conn.cursor(row_factory=tuple_row) as cur:
        refreshed_bases = 0
        for version, manifest in cur.execute(
            "SELECT scenario_context_version,manifest FROM retail_serving.forecast_scenario_contexts"
        ).fetchall():
            horizon = cur.execute(
                "SELECT count(*) FROM retail_serving.forecast_scenario_horizon_rows WHERE scenario_context_version=%s",
                (version,),
            ).fetchone()[0]
            commercial = cur.execute(
                "SELECT count(*) FROM retail_serving.forecast_scenario_commercial_rows WHERE scenario_context_version=%s",
                (version,),
            ).fetchone()[0]
            manifest["rowCounts"] = {"forecastHorizon": horizon, "seriesCommercial": commercial}
            cur.execute(
                "UPDATE retail_serving.forecast_scenario_contexts SET manifest=%s WHERE scenario_context_version=%s",
                (Jsonb(manifest), version),
            )
            refreshed_bases += 1
        refreshed_extensions = 0
        for version, manifest in cur.execute(
            "SELECT inventory_extension_version,manifest FROM retail_serving.forecast_scenario_inventory_extensions"
        ).fetchall():
            nodes = cur.execute(
                "SELECT count(*) FROM retail_serving.forecast_scenario_inventory_node_rows WHERE inventory_extension_version=%s",
                (version,),
            ).fetchone()[0]
            series = cur.execute(
                "SELECT count(*) FROM retail_serving.forecast_scenario_inventory_series_rows WHERE inventory_extension_version=%s",
                (version,),
            ).fetchone()[0]
            manifest["rowCounts"] = {"inventoryNode": nodes, "inventorySeries": series}
            cur.execute(
                "UPDATE retail_serving.forecast_scenario_inventory_extensions SET manifest=%s WHERE inventory_extension_version=%s",
                (Jsonb(manifest), version),
            )
            refreshed_extensions += 1
        # These rows are aggregated at market/cohort grain. They contain no SKU
        # decomposition, so filtering the serving catalog cannot reproduce a
        # matching policy replay. Removing the derivative read projection uses
        # the application's existing unavailable state. Do not mark the source
        # policy as failed or fabricate filtered candidate/incumbent values.
        removed = cur.execute("DELETE FROM retail_serving.inventory_replay_metrics").rowcount
        return {
            "scenarioBaseManifestsRefreshed": refreshed_bases,
            "scenarioInventoryManifestsRefreshed": refreshed_extensions,
            "sourceReplayProjectionRowsRemoved": removed,
            "replayBenefitStatus": "withheld_for_changed_demo_catalog",
            "caveat": (
                "Inventory policy replay benefit tiles are unavailable because the source "
                "replay covered a different catalog. No filtered replay or model training was run. "
                "Original replay evidence remains preserved in the backup and original artifacts."
            ),
        }


def audit(conn) -> dict:
    """Check active authority and trigger invariants after clone-only mutation."""
    checks = []
    with conn.cursor(row_factory=tuple_row) as cur:
        def check(name: str, statement: str, expected: int = 0):
            observed = cur.execute(statement).fetchone()[0]
            checks.append({"check": name, "observed": observed,
                           "expected": expected, "passed": observed == expected})

        for view in (
            "active_forecast_versions", "active_inventory_versions", "active_pricing_bundles",
            "effective_forecast_scenario_assumption_approvals", "active_forecast_scenario_contexts",
            "active_forecast_scenario_inventory_extensions",
        ):
            # Fixed relation names, never caller-supplied SQL.
            check(f"single-{view}", f"SELECT count(*) FROM retail_serving.{view}", 1)
        for table in (
            "forecast_scenario_assumption_sets", "forecast_scenario_contexts",
            "forecast_scenario_inventory_extensions",
        ):
            check(f"sealed-{table}", f"SELECT count(*) FROM retail_serving.{table} WHERE NOT children_sealed")

        check("scenario-commercial-cutoff", """
            SELECT count(*) FROM retail_serving.forecast_scenario_commercial_rows commercial
            JOIN retail_serving.forecast_scenario_contexts context USING(scenario_context_version)
            WHERE commercial.source_cutoff <> context.scenario_decision_as_of
        """)
        check("scenario-channel-atp-conservation", """
            SELECT count(*) FROM retail_serving.forecast_scenario_inventory_node_rows node
            LEFT JOIN (
                SELECT inventory_extension_version,market_id,sku_id,store_id,
                       sum(allocated_atp_units)::BIGINT AS allocated_atp_units
                FROM retail_serving.forecast_scenario_inventory_series_rows
                GROUP BY inventory_extension_version,market_id,sku_id,store_id
            ) series ON series.inventory_extension_version=node.inventory_extension_version
                AND series.market_id=node.market_id AND series.sku_id=node.sku_id
                AND series.store_id=node.location_id
            WHERE coalesce(series.allocated_atp_units,0) <> node.allocated_atp_units
        """)
        check("scenario-series-have-node", """
            SELECT count(*) FROM retail_serving.forecast_scenario_inventory_series_rows series
            LEFT JOIN retail_serving.forecast_scenario_inventory_node_rows node
              ON node.inventory_extension_version=series.inventory_extension_version
             AND node.market_id=series.market_id AND node.sku_id=series.sku_id
             AND node.location_id=series.store_id
            WHERE node.inventory_extension_version IS NULL
        """)
        check("scenario-context-approval-identity", """
            SELECT count(*) FROM retail_serving.forecast_scenario_contexts context
            JOIN retail_serving.forecast_scenario_assumption_approval_events approval
              ON approval.event_id=context.assumption_approval_event_id
            WHERE (context.retailer_id,context.tenant_id,context.capability,context.environment,
                   context.assumption_set_id,context.assumption_version,context.assumption_semantic_fingerprint,
                   context.assumption_approval_semantic_fingerprint)
              IS DISTINCT FROM
                  (approval.retailer_id,approval.tenant_id,approval.capability,approval.environment,
                   approval.assumption_set_id,approval.assumption_version,approval.assumption_semantic_fingerprint,
                   approval.approval_semantic_fingerprint)
        """)
        check("scenario-activation-context-identity", """
            SELECT count(*) FROM retail_serving.forecast_scenario_context_activation_events event
            JOIN retail_serving.forecast_scenario_contexts context USING(scenario_context_version)
            WHERE (event.retailer_id,event.tenant_id,event.capability,event.environment,event.authority_scope_fingerprint)
              IS DISTINCT FROM
                  (context.retailer_id,context.tenant_id,context.capability,context.environment,context.authority_scope_fingerprint)
        """)
        check("scenario-extension-activation-base-identity", """
            SELECT count(*) FROM retail_serving.forecast_scenario_inventory_activation_events event
            JOIN retail_serving.forecast_scenario_inventory_extensions extension USING(inventory_extension_version)
            WHERE event.scenario_context_version <> extension.scenario_context_version
        """)
        check("scenario-base-manifest-counts", """
            SELECT count(*) FROM retail_serving.forecast_scenario_contexts context
            WHERE (context.manifest#>>'{rowCounts,forecastHorizon}')::BIGINT IS DISTINCT FROM
                    (SELECT count(*) FROM retail_serving.forecast_scenario_horizon_rows horizon
                     WHERE horizon.scenario_context_version=context.scenario_context_version)
               OR (context.manifest#>>'{rowCounts,seriesCommercial}')::BIGINT IS DISTINCT FROM
                    (SELECT count(*) FROM retail_serving.forecast_scenario_commercial_rows commercial
                     WHERE commercial.scenario_context_version=context.scenario_context_version)
        """)
        check("scenario-inventory-manifest-counts", """
            SELECT count(*) FROM retail_serving.forecast_scenario_inventory_extensions extension
            WHERE (extension.manifest#>>'{rowCounts,inventoryNode}')::BIGINT IS DISTINCT FROM
                    (SELECT count(*) FROM retail_serving.forecast_scenario_inventory_node_rows node
                     WHERE node.inventory_extension_version=extension.inventory_extension_version)
               OR (extension.manifest#>>'{rowCounts,inventorySeries}')::BIGINT IS DISTINCT FROM
                    (SELECT count(*) FROM retail_serving.forecast_scenario_inventory_series_rows series
                     WHERE series.inventory_extension_version=extension.inventory_extension_version)
        """)
        check("source-replay-benefits-withheld", "SELECT count(*) FROM retail_serving.inventory_replay_metrics")
        check("serving-triggers-enabled", """
            SELECT count(*) FROM pg_trigger trigger
            JOIN pg_class relation ON relation.oid=trigger.tgrelid
            JOIN pg_namespace schema ON schema.oid=relation.relnamespace
            WHERE schema.nspname='retail_serving' AND trigger.tgenabled='D'
        """)
        return {"checks": checks, "passed": all(c["passed"] for c in checks),
                "sessionReplicationRole": cur.execute("SHOW session_replication_role").fetchone()[0]}
