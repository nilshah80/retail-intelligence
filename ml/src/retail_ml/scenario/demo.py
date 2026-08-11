"""Explicitly approve, materialize, and activate a local-only scenario demo."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import psycopg
from retail_contracts.scenario_assumptions import load_scenario_assumption_bundle

from retail_ml.scenario.context import AssumptionApproval, ScenarioAuthority
from retail_ml.scenario.materialize import (
    ScenarioMaterialization,
    materialize_scenario_base,
)
from retail_ml.scenario.postgres import (
    BaseContextActivation,
    InventoryExtensionActivation,
    RegisteredAssumptionBundle,
    ScenarioServingError,
    activate_base_context,
    activate_inventory_extension,
    append_assumption_approval_event,
    register_assumption_bundle,
)

LOCAL_DEMO_ENVIRONMENT = "local"
LOCAL_DEMO_ASSUMPTION_PREFIX = "fsa_local_demo_"


@dataclass(frozen=True)
class LocalDemoActivation:
    assumption: RegisteredAssumptionBundle
    approval: AssumptionApproval
    materialization: ScenarioMaterialization
    base_activation: BaseContextActivation
    inventory_activation: InventoryExtensionActivation | None


def _require_local_demo_bundle(bundle: dict) -> None:
    assumption_set_id = str(bundle.get("assumptionSetId", ""))
    disclosure = str(bundle.get("disclosure", "")).lower()
    if (
        not assumption_set_id.startswith(LOCAL_DEMO_ASSUMPTION_PREFIX)
        or bundle.get("artifactClass") != "serving_candidate"
        or bundle.get("servingEligible") is not True
        or "local demonstration" not in disclosure
        or "not fitted evidence" not in disclosure
    ):
        raise ScenarioServingError(
            "local demo activation requires an explicitly labelled local-demo "
            "serving candidate"
        )


def _approval_head(
    postgres_dsn: str,
    *,
    authority: ScenarioAuthority,
    assumption_semantic_fingerprint: str,
) -> tuple[int, str, str] | None:
    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT event_id, event_type, approval_semantic_fingerprint
                FROM retail_serving.forecast_scenario_assumption_approval_heads
                WHERE retailer_id = %s AND tenant_id = %s
                  AND capability = %s AND environment = %s
                  AND assumption_semantic_fingerprint = %s
                """,
                (
                    authority.retailer_id,
                    authority.tenant_id,
                    authority.capability,
                    authority.environment,
                    assumption_semantic_fingerprint,
                ),
            )
            rows = cursor.fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise ScenarioServingError("local demo assumption authority has competing heads")
    return int(rows[0][0]), str(rows[0][1]), str(rows[0][2])


def _ensure_local_demo_approval(
    postgres_dsn: str,
    *,
    authority: ScenarioAuthority,
    registered: RegisteredAssumptionBundle,
    actor: str,
    decision_reference: str,
    recorded_at: datetime,
) -> AssumptionApproval:
    head = _approval_head(
        postgres_dsn,
        authority=authority,
        assumption_semantic_fingerprint=registered.semantic_fingerprint,
    )
    if head is not None and head[1] == "approved":
        return AssumptionApproval(head[0], head[2])
    if head is not None and head[1] not in {"candidate"}:
        raise ScenarioServingError(
            "local demo assumption was rejected or superseded; publish a new version"
        )
    return append_assumption_approval_event(
        postgres_dsn,
        authority=authority,
        assumption_set_id=registered.assumption_set_id,
        assumption_version=registered.assumption_version,
        event_type="approved",
        actor=actor,
        decision_reference=decision_reference,
        prior_event_id=None if head is None else head[0],
        recorded_at=recorded_at,
    )


def activate_local_demo(
    *,
    postgres_dsn: str,
    curated_root: str | Path,
    authority: ScenarioAuthority,
    forecast_activation_scope_fingerprint: str,
    assumption_bundle_path: str | Path,
    actor: str,
    decision_reference: str,
    recorded_at: datetime | None = None,
) -> LocalDemoActivation:
    """Activate a reproducible demo context, but only for the local authority."""

    if authority.environment != LOCAL_DEMO_ENVIRONMENT:
        raise ScenarioServingError(
            "local demo activation is forbidden outside environment=local"
        )
    if not actor or not decision_reference:
        raise ScenarioServingError("local demo actor and decision reference are required")
    moment = recorded_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ScenarioServingError("local demo recorded_at must be timezone-aware")
    bundle = load_scenario_assumption_bundle(assumption_bundle_path)
    _require_local_demo_bundle(bundle)
    registered = register_assumption_bundle(postgres_dsn, bundle)
    approval = _ensure_local_demo_approval(
        postgres_dsn,
        authority=authority,
        registered=registered,
        actor=actor,
        decision_reference=decision_reference,
        recorded_at=moment,
    )
    materialization = materialize_scenario_base(
        postgres_dsn=postgres_dsn,
        curated_root=curated_root,
        authority=authority,
        forecast_activation_scope_fingerprint=forecast_activation_scope_fingerprint,
        assumption_bundle_path=assumption_bundle_path,
    )
    base_activation = activate_base_context(
        postgres_dsn,
        authority=authority,
        scenario_context_version=materialization.base.scenario_context_version,
        actor=actor,
        decision_reference=decision_reference,
        recorded_at=moment,
    )
    inventory_activation: InventoryExtensionActivation | None = None
    if materialization.inventory is not None:
        inventory_activation = activate_inventory_extension(
            postgres_dsn,
            scenario_context_version=materialization.base.scenario_context_version,
            inventory_extension_version=(
                materialization.inventory.inventory_extension_version
            ),
            actor=actor,
            decision_reference=decision_reference,
            recorded_at=moment,
        )
    return LocalDemoActivation(
        assumption=registered,
        approval=approval,
        materialization=materialization,
        base_activation=base_activation,
        inventory_activation=inventory_activation,
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Approve, materialize, and activate the explicitly labelled local "
            "Forecast Scenario Planning demo. Production environments are refused."
        )
    )
    parser.add_argument(
        "--postgres-dsn", default=os.environ.get("RETAIL_POSTGRES_DSN", "")
    )
    parser.add_argument("--curated-root", required=True)
    parser.add_argument("--forecast-activation-scope-fingerprint", required=True)
    parser.add_argument("--assumption-bundle", required=True)
    parser.add_argument("--retailer-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--capability", default="forecast_scenario_v1")
    parser.add_argument("--actor", required=True)
    parser.add_argument("--decision-reference", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _argument_parser()
    args = parser.parse_args(argv)
    if not args.postgres_dsn:
        parser.error("--postgres-dsn or RETAIL_POSTGRES_DSN is required")
    result = activate_local_demo(
        postgres_dsn=args.postgres_dsn,
        curated_root=args.curated_root,
        authority=ScenarioAuthority(
            retailer_id=args.retailer_id,
            tenant_id=args.tenant_id,
            capability=args.capability,
            environment=args.environment,
        ),
        forecast_activation_scope_fingerprint=(
            args.forecast_activation_scope_fingerprint
        ),
        assumption_bundle_path=args.assumption_bundle,
        actor=args.actor,
        decision_reference=args.decision_reference,
    )
    print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
