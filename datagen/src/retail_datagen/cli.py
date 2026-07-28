"""Dependency-light command-line interface for the isolated generator."""

from __future__ import annotations

import argparse
import calendar
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from . import GENERATOR_VERSION, SOURCE_SPEC_VERSION
from .catalog_packs import CATALOG_PACK_METADATA, build_catalog, catalog_controls
from .config import ConfigError, load_config
from .generator import generate
from .identity import config_hash, run_id
from .locale_packs import LOCALE_PACKS


def _plan(config: dict[str, Any]) -> dict[str, Any]:
    start = date.fromisoformat(config["time"]["startDate"])
    end = date.fromisoformat(config["time"]["endDate"])
    days = (end - start).days + 1
    store_count_by_market = {
        market["marketId"]: sum(
            store["marketId"] == market["marketId"] for store in config["stores"]
        )
        for market in config["markets"]
    }
    catalog = build_catalog(config)
    catalog_by_market = catalog_controls(catalog)
    products = sum(row["products"] for row in catalog_by_market.values())
    sellable_skus = sum(row["sellableSkus"] for row in catalog_by_market.values())
    estimated_orders = sum(
        market["demand"]["startingDailyOrders"]
        * market["demand"]["demandLevelScalar"]
        * days
        * sum(
            store["demandScale"]
            for store in config["stores"]
            if store["marketId"] == market["marketId"]
        )
        for market in config["markets"]
    )
    if config["time"]["generationPartition"] == "day":
        partitions_per_dated_dataset = days
    else:
        partitions_per_dated_dataset = (
            (end.year - start.year) * 12 + end.month - start.month + 1
        )
    estimated_demand_grains = sum(
        catalog_by_market[market["marketId"]]["sellableSkus"]
        * days
        * store_count_by_market[market["marketId"]]
        for market in config["markets"]
    )
    estimated_inventory_grains = sum(
        catalog_by_market[warehouse["marketId"]]["sellableSkus"]
        * (
            days // config["operations"]["inventory"]["snapshotCadenceDays"]
            + 1
        )
        for warehouse in config["warehouses"]
    )
    lifecycle = {
        market_id: {
            "productsIntroducedDuringRun": sum(
                start <= date.fromisoformat(row["launchDate"]) <= end
                for row in products
            ),
            "productsDiscontinuedDuringRun": sum(
                bool(row["discontinueDate"])
                and start <= date.fromisoformat(row["discontinueDate"]) <= end
                for row in products
            ),
            "replacementLinks": sum(
                bool(row["successorOfProductCode"]) for row in products
            ),
        }
        for market_id, products in catalog.items()
    }
    return {
        "scenarioId": config["identity"]["scenarioId"],
        "sourceSpecVersion": SOURCE_SPEC_VERSION,
        "generatorVersion": GENERATOR_VERSION,
        "configHash": config_hash(config),
        "runId": run_id(config, GENERATOR_VERSION),
        "days": days,
        "years": round(days / 365.2425, 2),
        "calendarDaysInStartYear": 366 if calendar.isleap(start.year) else 365,
        "partitionsPerDatedDataset": partitions_per_dated_dataset,
        "markets": len(config["markets"]),
        "stores": len(config["stores"]),
        "warehouses": len(config["warehouses"]),
        "products": products,
        "sellableSkus": sellable_skus,
        "catalogByMarket": catalog_by_market,
        "estimatedOrdersBeforeCausalFactors": estimated_orders,
        "estimatedMaximumDemandGrainsBeforeLifecycleGating": estimated_demand_grains,
        "estimatedInventoryObservationGrains": estimated_inventory_grains,
        "catalogLifecycleByMarket": lifecycle,
        "pandemics": {
            row["pandemicId"]: {
                "effectMode": row["effectMode"],
                "phases": len(row["phases"]),
            }
            for row in config["pandemics"]
        },
        "resourceNote": (
            "Long-horizon runs are partitioned on disk but the current Python "
            "simulation retains run state and projection rows in memory; size "
            "assortment/store/signal controls to the available RAM."
            if days >= 3650
            else "Short-horizon run."
        ),
        "publicFormat": config["output"]["publicFormats"],
    }


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retail-datagen",
        description="Generate independent Shopify/Business Central synthetic source data.",
    )
    parser.add_argument("--version", action="version", version=GENERATOR_VERSION)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-config", help="Validate builder YAML/JSON.")
    validate.add_argument("-c", "--config", required=True)

    plan = commands.add_parser("plan", help="Show a deterministic run estimate.")
    plan.add_argument("-c", "--config", required=True)

    run = commands.add_parser("generate", help="Generate and publish source-shaped data.")
    run.add_argument("-c", "--config", required=True)
    run.add_argument("-o", "--output-root")

    commands.add_parser("locales", help="Print supported resolved locale packs.")
    commands.add_parser("catalogs", help="Print supported rich catalog-pack metadata.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    try:
        if args.command == "locales":
            _print_json(LOCALE_PACKS)
            return
        if args.command == "catalogs":
            _print_json(CATALOG_PACK_METADATA)
            return
        config = load_config(Path(args.config))
        if args.command == "validate-config":
            _print_json(
                {
                    "valid": True,
                    "scenarioId": config["identity"]["scenarioId"],
                    "specVersion": config["specVersion"],
                    "configHash": config_hash(config),
                }
            )
            return
        if args.command == "plan":
            _print_json(_plan(config))
            return
        if args.command == "generate":
            result = generate(config, output_root=args.output_root)
            _print_json(
                {
                    "runId": result["runId"],
                    "outputBase": result["outputBase"],
                    "reused": result["reused"],
                    "objects": len(result["manifest"]["objects"]),
                    "controlsByCurrency": result["manifest"]["controlsByCurrency"],
                }
            )
            return
        raise AssertionError(f"unhandled command {args.command}")
    except ConfigError as exc:
        _print_json({"valid": False, "errors": exc.errors})
        raise SystemExit(2) from exc
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
