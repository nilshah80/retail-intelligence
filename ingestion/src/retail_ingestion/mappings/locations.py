"""Resolve source location identifiers before canonical transformation."""

from __future__ import annotations

import json
from typing import Any

import duckdb

from retail_ingestion.readers import PublicSourceCatalog


class LocationMappingError(RuntimeError):
    """Source location identities cannot be resolved unambiguously."""


def build_location_crosswalk(
    connection: duckdb.DuckDBPyConnection,
    catalog: PublicSourceCatalog,
) -> int:
    """Build a source-neutral location crosswalk from declared topology evidence.

    The datagen profile uses its retained source-run topology. A real-retailer
    profile can replace this resolver with a governed mapping dataset without
    changing transformations.
    """

    path = catalog.snapshot_root / "public" / "upstream" / "source-run-manifest.json"
    try:
        upstream = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LocationMappingError(f"cannot read topology evidence: {exc}") from exc
    topology = upstream.get("topology")
    if not isinstance(topology, dict):
        raise LocationMappingError("source profile requires upstream topology evidence")
    stores = topology.get("stores", [])
    warehouses = topology.get("warehouses", [])
    market_aliases: dict[str, str] = {}
    for instance in catalog.profile.get("sourceInstances", []):
        source_market = str(
            instance.get("sourceMarketId", instance["marketId"])
        )
        canonical_market = str(instance["marketId"])
        existing = market_aliases.setdefault(source_market, canonical_market)
        if existing != canonical_market:
            raise LocationMappingError(
                f"source market {source_market!r} maps to multiple canonical markets"
            )

    def canonical_market_id(source_market_id: Any) -> str:
        source_market = str(source_market_id)
        try:
            return market_aliases[source_market]
        except KeyError as exc:
            raise LocationMappingError(
                f"topology market has no profile mapping: {source_market!r}"
            ) from exc

    canonical_names = {
        (str(row["sourceInstance"]), str(row["sourceLocationKey"])): str(
            row["canonicalName"]
        )
        for row in catalog.profile.get("locationOverrides", [])
        if row.get("canonicalName")
    }
    shopify_locations = connection.execute(
        """
        SELECT source_instance, market_id, location_source_key,
               location_name, location_type
        FROM stage_data.shopify_locations
        """
    ).fetchall()
    by_name: dict[tuple[str, str], tuple[str, str, str]] = {}
    for (
        source_instance,
        market_id,
        source_key,
        name,
        location_type,
    ) in shopify_locations:
        key = (str(market_id), str(name).strip().casefold())
        if key in by_name:
            raise LocationMappingError(f"duplicate Shopify location name: {key!r}")
        by_name[key] = (
            str(source_instance),
            str(source_key),
            str(location_type),
        )

    rows: list[tuple[str, str, str, str, str, str, str]] = []
    for row in stores:
        market = canonical_market_id(row["marketId"])
        canonical = str(row["storeId"])
        name = str(row["name"])
        match = by_name.get((market, name.strip().casefold()))
        if match is None:
            raise LocationMappingError(f"Shopify store has no name match: {name!r}")
        canonical_name = canonical_names.get((match[0], match[1]), name)
        rows.extend(
            (
                (
                    "shopify",
                    market,
                    match[1],
                    canonical,
                    "store",
                    canonical_name,
                    "upstream_topology_name_match",
                ),
                (
                    "companion",
                    market,
                    canonical,
                    canonical,
                    "store",
                    canonical_name,
                    "upstream_topology_native_key",
                ),
            )
        )
    for row in warehouses:
        market = canonical_market_id(row["marketId"])
        canonical = str(row["warehouseId"])
        name = str(row["name"])
        match = by_name.get((market, name.strip().casefold()))
        if match is None:
            raise LocationMappingError(f"Shopify warehouse has no name match: {name!r}")
        canonical_name = canonical_names.get((match[0], match[1]), name)
        rows.extend(
            (
                (
                    "shopify",
                    market,
                    match[1],
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_name_match",
                ),
                (
                    "businessCentral",
                    market,
                    str(row["businessCentralLocationCode"]),
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_bc_code",
                ),
                (
                    "businessCentral",
                    market,
                    canonical,
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_native_warehouse_key",
                ),
                (
                    "companion",
                    market,
                    canonical,
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_native_key",
                ),
            )
        )
    connection.execute(
        """
        CREATE OR REPLACE TABLE stage_data.location_crosswalk (
            source_system VARCHAR NOT NULL,
            market_id VARCHAR NOT NULL,
            source_location_key VARCHAR NOT NULL,
            canonical_location_key VARCHAR NOT NULL,
            canonical_location_type VARCHAR NOT NULL,
            canonical_location_name VARCHAR NOT NULL,
            resolution_method VARCHAR NOT NULL,
            PRIMARY KEY (source_system, market_id, source_location_key)
        )
        """
    )
    connection.executemany(
        "INSERT INTO stage_data.location_crosswalk VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    unresolved = connection.execute(
        """
        SELECT count(*)
        FROM (
            SELECT DISTINCT source_system, market_id, location_source_key
            FROM stage_data.inventory
            UNION
            SELECT DISTINCT source_system, market_id, demand_location_source_key
            FROM stage_data.merchandise
            UNION
            SELECT DISTINCT source_system, market_id, demand_location_source_key
            FROM stage_data.store_assortment
            UNION
            SELECT DISTINCT source_system, market_id, location_source_key
            FROM stage_data.receipt
            UNION
            SELECT DISTINCT source_system, market_id, location_source_key
            FROM stage_data.inventory_cost
            UNION
            SELECT DISTINCT 'businessCentral', market_id, location_source_key
            FROM stage_data.inventory_batches
            UNION
            SELECT DISTINCT 'businessCentral', market_id, to_location_source_key
            FROM stage_data.inbound_shipments
            UNION
            SELECT DISTINCT 'businessCentral', market_id, from_location_source_key
            FROM stage_data.transfer_orders
            UNION
            SELECT DISTINCT 'businessCentral', market_id, to_location_source_key
            FROM stage_data.transfer_orders
            UNION
            SELECT DISTINCT 'businessCentral', market_id, location_source_key
            FROM stage_data.waste_events
            UNION
            SELECT DISTINCT 'businessCentral', market_id, location_source_key
            FROM stage_data.warehouse_capacity
            UNION
            SELECT DISTINCT 'businessCentral', market_id, location_source_key
            FROM stage_data.wms_comparisons
            UNION
            SELECT DISTINCT 'companion', market_id, location_source_key
            FROM stage_data.allocations
        ) AS used
        LEFT JOIN stage_data.location_crosswalk AS x
          ON x.source_system = used.source_system
         AND x.market_id = used.market_id
         AND x.source_location_key = used.location_source_key
        WHERE x.source_location_key IS NULL
        """
    ).fetchone()[0]
    if unresolved:
        raise LocationMappingError(f"{unresolved} used location keys are unresolved")
    return len(rows)


__all__ = ["LocationMappingError", "build_location_crosswalk"]
