"""Approval-gated offline orchestration for a Scenario Planning base context."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from dataclasses import asdict, dataclass
from typing import Sequence

import psycopg
from retail_contracts.guardrails import resolve_guardrails
from retail_contracts.scenario_assumptions import (
    load_scenario_assumption_bundle,
    scenario_assumption_fingerprint,
)

from retail_ml.inventory_run.load import (
    connect,
    load_unit_price_history,
    load_unit_prices,
)
from retail_ml.inventory_run.price_resolution import build_price_index
from retail_ml.scenario.context import (
    ScenarioAuthority,
    build_base_context,
    build_inventory_extension,
)
from retail_ml.scenario.postgres import (
    BaseContextMaterialization,
    InventoryExtensionMaterialization,
    effective_assumption_approval,
    load_active_forecast,
    load_active_inventory,
    materialize_base_context,
    materialize_inventory_extension,
    register_assumption_bundle,
)


@dataclass(frozen=True)
class ScenarioMaterialization:
    base: BaseContextMaterialization
    inventory: InventoryExtensionMaterialization | None


def materialize_scenario_base(
    *,
    postgres_dsn: str,
    curated_root: str | Path,
    authority: ScenarioAuthority,
    forecast_activation_scope_fingerprint: str,
    assumption_bundle_path: str | Path,
) -> ScenarioMaterialization:
    """Build and publish an inactive context; never activate as a side effect."""

    bundle = load_scenario_assumption_bundle(assumption_bundle_path)
    registered = register_assumption_bundle(postgres_dsn, bundle)
    forecast = load_active_forecast(
        postgres_dsn,
        activation_scope_fingerprint=forecast_activation_scope_fingerprint,
    )
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            approval = effective_assumption_approval(
                cursor,
                authority=authority,
                assumption_semantic_fingerprint=registered.semantic_fingerprint,
            )
    max_support_window = max(
        int(rule["observedSupportWindowDays"])
        for rule in bundle["marketCurrencyRules"]
    )
    curated = connect(curated_root)
    try:
        prices = load_unit_prices(curated, as_of=forecast.decision_as_of)
        history = load_unit_price_history(
            curated,
            as_of=forecast.decision_as_of,
            window_days=max_support_window,
        )
    finally:
        curated.close()
    price_index = build_price_index(
        prices,
        source_cutoff=forecast.decision_as_of,
        require_provenance=True,
    )
    built = build_base_context(
        authority=authority,
        forecast_version_id=forecast.forecast_version_id,
        forecast_activation_scope_fingerprint=forecast.activation_scope_fingerprint,
        scenario_decision_as_of=forecast.decision_as_of,
        forecast_rows=forecast.rows,
        price_index=price_index,
        price_history=history,
        assumption_bundle=bundle,
        approval=approval,
    )
    assert (
        registered.semantic_fingerprint
        == scenario_assumption_fingerprint(bundle)
        == built.manifest["approvedAssumptionBundleFingerprint"]
    )
    base_materialization = materialize_base_context(postgres_dsn, built)
    inventory = load_active_inventory(postgres_dsn, base_context=built)
    if inventory is None:
        return ScenarioMaterialization(base=base_materialization, inventory=None)
    review_periods = {
        market: int(
            resolve_guardrails(
                market,
                currency,
                inventory_policy_generation="v2",
            )["inventoryPolicy"]["reviewPeriodDays"]
        )
        for market, currency in inventory.currency_by_market.items()
    }
    extension = build_inventory_extension(
        base_context=built,
        inventory_version_id=inventory.inventory_version_id,
        positions=inventory.positions,
        allocations=inventory.allocations,
        recommendations=inventory.recommendations,
        sku_dimensions=inventory.sku_dimensions,
        review_period_days_by_market=review_periods,
        currency_by_market=inventory.currency_by_market,
    )
    return ScenarioMaterialization(
        base=base_materialization,
        inventory=materialize_inventory_extension(postgres_dsn, extension),
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Materialize an inactive, approval-gated Forecast Scenario Planning "
            "context. This command never activates it."
        )
    )
    parser.add_argument(
        "--postgres-dsn",
        default=os.environ.get("RETAIL_POSTGRES_DSN", ""),
    )
    parser.add_argument("--curated-root", required=True)
    parser.add_argument("--forecast-activation-scope-fingerprint", required=True)
    parser.add_argument("--assumption-bundle", required=True)
    parser.add_argument("--retailer-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--capability", default="forecast_scenario_v1")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or RETAIL_POSTGRES_DSN is required")
    authority = ScenarioAuthority(
        retailer_id=args.retailer_id,
        tenant_id=args.tenant_id,
        capability=args.capability,
        environment=args.environment,
    )
    result = materialize_scenario_base(
        postgres_dsn=args.postgres_dsn,
        curated_root=args.curated_root,
        authority=authority,
        forecast_activation_scope_fingerprint=(
            args.forecast_activation_scope_fingerprint
        ),
        assumption_bundle_path=args.assumption_bundle,
    )
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
