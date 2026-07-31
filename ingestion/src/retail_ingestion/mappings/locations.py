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

    Two modes, chosen by the profile's declared ``locationResolution.mode`` rather
    than by which files happen to exist:

    ``upstream_topology`` (the default, and what the datagen profile uses) takes
    canonical store and warehouse identity from the retained source-run topology and
    matches it to the location role by name.

    ``location_role_identity`` treats the retailer's own location role as the
    authority, so its source keys are the canonical keys. A retailer arriving through
    a mapping has no upstream topology manifest, and before this mode existed the
    resolver read that manifest unconditionally -- so a mapped-files-only build failed
    here even though its locations were fully staged. The mode is declared rather than
    inferred from a missing file: falling back on absence would mean any profile that
    lost its topology evidence silently switched identity authority.
    """

    mode = str(
        (catalog.profile.get("locationResolution") or {}).get(
            "mode", "upstream_topology"
        )
    )
    if mode == "upstream_topology":
        path = (
            catalog.snapshot_root / "public" / "upstream" / "source-run-manifest.json"
        )
        try:
            upstream = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LocationMappingError(f"cannot read topology evidence: {exc}") from exc
        topology = upstream.get("topology")
        if not isinstance(topology, dict):
            raise LocationMappingError(
                "source profile requires upstream topology evidence"
            )
        stores = topology.get("stores", [])
        warehouses = topology.get("warehouses", [])
    elif mode == "location_role_identity":
        stores = []
        warehouses = []
    else:
        raise LocationMappingError(f"unsupported location resolution mode: {mode!r}")
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
    # PP3-A3: read the standardized `location` role, not a platform relation.
    # A retailer that stages no location role gets a reason-coded refusal rather than
    # a raw catalog error, because "which role is missing" is the actionable fact and
    # a DuckDB exception buries it.
    staged_locations = connection.execute(
        """
        SELECT count(*) FROM duckdb_tables()
        WHERE schema_name = 'stage_data' AND table_name = 'locations'
        UNION ALL
        SELECT count(*) FROM duckdb_views()
        WHERE schema_name = 'stage_data' AND view_name = 'locations'
        """
    ).fetchall()
    if not any(int(row[0]) for row in staged_locations):
        raise LocationMappingError(
            "MISSING_ROLE:locations -- no source staged the location role, so no "
            "location key can be resolved to a canonical identity"
        )
    # staging-v2's `location` role declares `name` and `location_kind`, but the
    # shopify adapter has always emitted `location_name` and `location_type`, so the
    # neutral relation carries the dialect spelling in the generator path and the
    # contract spelling for a mapped-files retailer. Both are accepted here so neither
    # source is locked out; the divergence itself is a contract-versus-implementation
    # defect that needs a decision, not a silent rename underneath a frozen contract.
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT column_name FROM duckdb_columns() "
            "WHERE schema_name = 'stage_data' AND table_name = 'locations'"
        ).fetchall()
    }
    name_column = "location_name" if "location_name" in present else "name"
    kind_column = "location_type" if "location_type" in present else "location_kind"
    missing = sorted({name_column, kind_column} - present)
    if missing:
        raise LocationMappingError(
            "MISSING_FIELD:locations -- the location role must present a name and a "
            f"kind column; absent: {', '.join(missing)}"
        )
    market_column = "market_id" if "market_id" in present else "_market_id"
    role_locations = connection.execute(
        f"""
        SELECT source_system, source_instance, {market_column}, location_source_key,
               {name_column}, {kind_column}
        FROM stage_data.locations
        """
    ).fetchall()
    by_name: dict[tuple[str, str], tuple[str, str, str, str]] = {}
    for (
        source_system,
        source_instance,
        market_id,
        source_key,
        name,
        location_type,
    ) in role_locations:
        key = (str(market_id), str(name).strip().casefold())
        if key in by_name:
            raise LocationMappingError(
                f"duplicate location name in the location role: {key!r}"
            )
        by_name[key] = (
            str(source_instance),
            str(source_key),
            str(location_type),
            str(source_system),
        )

    rows: list[tuple[str, str, str, str, str, str, str, str]] = []
    for row in stores:
        market = canonical_market_id(row["marketId"])
        canonical = str(row["storeId"])
        name = str(row["name"])
        match = by_name.get((market, name.strip().casefold()))
        if match is None:
            raise LocationMappingError(
                f"store has no location-role name match: {name!r}"
            )
        canonical_name = canonical_names.get((match[0], match[1]), name)
        match_source_system = match[3]
        rows.extend(
            (
                (
                    "source_native",
                    match_source_system,
                    market,
                    match[1],
                    canonical,
                    "store",
                    canonical_name,
                    "upstream_topology_name_match",
                ),
                (
                    "canonical_identity",
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
            raise LocationMappingError(
                f"warehouse has no location-role name match: {name!r}"
            )
        canonical_name = canonical_names.get((match[0], match[1]), name)
        match_source_system = match[3]
        rows.extend(
            (
                (
                    "source_native",
                    match_source_system,
                    market,
                    match[1],
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_name_match",
                ),
                (
                    "source_native",
                    "businessCentral",
                    market,
                    str(row["businessCentralLocationCode"]),
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_bc_code",
                ),
                (
                    "canonical_identity",
                    "businessCentral",
                    market,
                    canonical,
                    canonical,
                    "dc",
                    canonical_name,
                    "upstream_topology_native_warehouse_key",
                ),
                (
                    "canonical_identity",
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
    if mode == "location_role_identity":
        # The location role is the authority, so each source key resolves to itself.
        # This is an identity crosswalk, not a fabricated one: no canonical key is
        # invented, and locationOverrides can still rename for display.
        for (market_id, source_key), (
            source_instance,
            _key,
            location_type,
            source_system,
        ) in (
            ((market, key), value)
            for (market, _name), value in by_name.items()
            for key in (value[1],)
        ):
            rows.append(
                (
                    "source_native",
                    source_system,
                    market_id,
                    source_key,
                    source_key,
                    location_type,
                    canonical_names.get((source_instance, source_key), source_key),
                    "location_role_declared_identity",
                )
            )

    connection.execute(
        """
        CREATE OR REPLACE TABLE stage_data.location_crosswalk (
            key_space VARCHAR NOT NULL,
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
        "INSERT INTO stage_data.location_crosswalk VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    # PP3-A3: every location key used by a role must resolve through the
    # crosswalk under the authority that minted it. The authority is a join
    # *column*, never a literal, so onboarding a dialect needs no change here.
    #
    # `key_space` is deliberately NOT part of this predicate. A single relation
    # can legitimately carry keys from both spaces — Business Central rows
    # reference warehouses by their own location code and by the canonical id —
    # so key space describes what a crosswalk row's key is, not which rows a
    # consumer may match.
    # Every relation that carries a location key, with the column that carries it.
    # A retailer supplies a subset of these; a role nobody staged is absent, not a
    # failure, so the union is built from what exists. Enumerating them as data also
    # means a consumer relation cannot be added without appearing in this check.
    location_key_columns = (
        ("inventory", "location_source_key"),
        ("merchandise", "demand_location_source_key"),
        ("store_assortment", "demand_location_source_key"),
        ("receipt", "location_source_key"),
        ("inventory_cost", "location_source_key"),
        ("inventory_batches", "location_source_key"),
        ("inbound_shipments", "to_location_source_key"),
        ("transfer_orders", "from_location_source_key"),
        ("transfer_orders", "to_location_source_key"),
        ("waste_events", "location_source_key"),
        ("warehouse_capacity", "location_source_key"),
        ("wms_comparisons", "location_source_key"),
        ("allocations", "location_source_key"),
    )
    existing_relations = {
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM duckdb_tables() WHERE schema_name = 'stage_data' "
            "UNION ALL "
            "SELECT view_name FROM duckdb_views() WHERE schema_name = 'stage_data'"
        ).fetchall()
    }
    used_selects = [
        f"SELECT DISTINCT source_system, market_id, {column} AS location_source_key "
        f"FROM stage_data.{relation}"
        for relation, column in location_key_columns
        if relation in existing_relations
    ]
    if not used_selects:
        raise LocationMappingError(
            "no staged relation carries a location key, so crosswalk coverage cannot "
            "be proven"
        )
    used_sql = "\n            UNION\n            ".join(used_selects)
    unresolved = connection.execute(
        f"""
        WITH used AS (
            {used_sql}
        )
        SELECT used.source_system, used.market_id, used.location_source_key
        FROM used
        LEFT JOIN stage_data.location_crosswalk AS x
          ON x.source_system = used.source_system
         AND x.market_id = used.market_id
         AND x.source_location_key = used.location_source_key
        WHERE x.source_location_key IS NULL
        ORDER BY 1, 2, 3
        """
    ).fetchall()
    if unresolved:
        sample = "; ".join(
            f"{source_system}/{market}/{key}"
            for source_system, market, key in unresolved[:10]
        )
        raise LocationMappingError(
            f"{len(unresolved)} used location keys are unresolved: {sample}"
        )
    return len(rows)


__all__ = ["LocationMappingError", "build_location_crosswalk"]
