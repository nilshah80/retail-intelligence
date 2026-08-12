"""Command-line boundary for pricing build and independent verification."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Sequence

from jsonschema import Draft202012Validator, FormatChecker

from retail_ml.io.authority import verify_job_authority
from retail_ml.pricing.build import build_pricing_artifacts
from retail_ml.pricing.bundle import (
    publish_pricing_bundle,
    verify_pricing_bundle,
    write_verification_record,
)
from retail_ml.pricing.postgres import (
    activate_pricing_bundle,
    materialize_pricing_bundle,
    write_pricing_activation_receipt,
)
from retail_ml.pricing.selection import (
    build_activation_set,
    build_selection_record,
    validate_activation_set,
    validate_selection_record,
)


def _authority_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--input-authority", required=True)
    parser.add_argument("--job-purpose", required=True)
    parser.add_argument("--expected-pin", required=True)
    parser.add_argument("--retailer-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--evidence-root", required=True)


def _verified_authority(args: argparse.Namespace) -> dict:
    return verify_job_authority(
        repository_root=args.repository_root,
        authority_path=args.input_authority,
        expected_pin_path=args.expected_pin,
        expected_run_id=args.run_id,
        expected_job_purpose=args.job_purpose,
        retailer_id=args.retailer_id,
        tenant_id=args.tenant_id,
        environment=args.environment,
        evidence_root=args.evidence_root,
    )


def _build(args: argparse.Namespace) -> int:
    authority = _verified_authority(args)
    root = Path(args.repository_root).resolve()
    artifacts, lineage, policies, capabilities = build_pricing_artifacts(
        args.curated_database,
        decision_as_of=args.decision_as_of,
        response_policy_path=root / "contracts/pricing/response-evaluation.json",
        pricing_policy_path=root / "contracts/guardrails/pricing_rules.yaml",
        competitor_policy_path=root / "contracts/pricing/competitor-policy.json",
        competitor_truth_path=args.competitor_truth,
        promotion_policy_path=root / "contracts/pricing/promotion-protection-policy.json",
        forecast_run=args.forecast_run,
        inventory_run=args.inventory_run,
        bundle_kind=args.bundle_kind,
        lineage={
            "inputAuthorityId": authority["authorityId"],
            "sourceRunId": authority["runId"],
            **authority["sourceEvidence"],
        },
    )
    destination = publish_pricing_bundle(
        args.output,
        bundle_kind=args.bundle_kind,
        decision_as_of=args.decision_as_of,
        artifacts=artifacts,
        lineage=lineage,
        policies=policies,
        capabilities=capabilities,
        selection_scope={
            "retailerId": args.retailer_id,
            "tenantId": args.tenant_id,
            "environment": args.environment,
            "audience": (
                "response_rich_local"
                if args.bundle_kind == "response_rich"
                else "pricing_evidence_sparse_dev"
            ),
        },
    )
    print(json.dumps({"bundle": str(destination), "status": "published"}, sort_keys=True))
    return 0


def _verify(args: argparse.Namespace) -> int:
    authority = _verified_authority(args)
    manifest = json.loads(
        (Path(args.bundle).resolve() / "pricing-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    lineage = manifest.get("lineage") or {}
    expected_lineage = {
        "inputAuthorityId": authority["authorityId"],
        "sourceRunId": authority["runId"],
        **authority["sourceEvidence"],
    }
    mismatches = [
        key for key, value in expected_lineage.items() if lineage.get(key) != value
    ]
    if mismatches:
        raise RuntimeError(
            "bundle lineage differs from verification authority: "
            + ", ".join(sorted(mismatches))
        )
    _verify_result_scope(manifest, args)
    record = verify_pricing_bundle(args.bundle)
    if record["bundleId"] == authority.get("authorityId"):
        raise RuntimeError("bundle identity must not reuse its input-authority identity")
    output = write_verification_record(args.bundle, args.output)
    print(json.dumps({"verification": str(output), **record}, sort_keys=True))
    return 0


def _postgres_dsn() -> str:
    dsn = os.environ.get("RETAIL_POSTGRES_DSN", "").strip()
    if not dsn:
        raise RuntimeError("RETAIL_POSTGRES_DSN is required")
    return dsn


def _materialize(args: argparse.Namespace) -> int:
    authority = _verified_authority(args)
    manifest = json.loads(
        (Path(args.bundle).resolve() / "pricing-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    lineage = manifest.get("lineage") or {}
    if lineage.get("inputAuthorityId") != authority["authorityId"]:
        raise RuntimeError("materialization authority differs from bundle lineage")
    _verify_result_scope(manifest, args)
    result = materialize_pricing_bundle(
        args.bundle, args.verification_record, postgres_dsn=_postgres_dsn()
    )
    print(
        json.dumps(
            {
                "bundleId": result.bundle_id,
                "semanticFingerprint": result.semantic_fingerprint,
                "bundleKind": result.bundle_kind,
                "rowCounts": result.row_counts,
                "alreadyMaterialized": result.already_materialized,
            },
            sort_keys=True,
        )
    )
    return 0


def _activate(args: argparse.Namespace) -> int:
    root = Path(args.repository_root).resolve()
    result = activate_pricing_bundle(
        postgres_dsn=_postgres_dsn(),
        selection_record_paths=args.selection_record,
        activation_set_path=args.activation_set,
        selection_schema_path=root / "contracts/pricing/result-selection.schema.json",
        activation_schema_path=root / "contracts/pricing/activation-set.schema.json",
        actor=args.actor,
    )
    receipt = None
    if args.receipt:
        receipt = write_pricing_activation_receipt(
            postgres_dsn=_postgres_dsn(),
            activation_set_id=result.activation_set_id,
            destination=args.receipt,
            schema_path=root / "contracts/pricing/activation-receipt.schema.json",
        )
    print(
        json.dumps(
            {
                "activationEventId": result.activation_event_id,
                "activationSetId": result.activation_set_id,
                "bundleId": result.bundle_id,
                "transactionId": result.transaction_id,
                "selectionRecordIds": list(result.selection_record_ids),
                "receipt": str(receipt) if receipt else None,
                "alreadyActive": result.already_active,
            },
            sort_keys=True,
        )
    )
    return 0


def _canonical_bytes(document: dict) -> bytes:
    return (
        json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def _verify_result_scope(
    manifest: dict, args: argparse.Namespace
) -> dict:
    intents = manifest.get("prospectiveResultSelections") or []
    if len(intents) != 1:
        raise RuntimeError("bundle must bind exactly one result-selection intent")
    intent = intents[0]
    expected_audience = (
        "response_rich_local"
        if manifest.get("bundleKind") == "response_rich"
        else "pricing_evidence_sparse_dev"
    )
    expected = {
        "retailerId": args.retailer_id,
        "tenantId": args.tenant_id,
        "environment": args.environment,
        "audience": expected_audience,
        "capability": "price_revenue",
    }
    mismatches = [key for key, value in expected.items() if intent.get(key) != value]
    if mismatches:
        raise RuntimeError(
            "result-selection intent differs from explicit authority scope: "
            + ", ".join(sorted(mismatches))
        )
    return intent


def _prepare_activation(args: argparse.Namespace) -> int:
    root = Path(args.repository_root).resolve()
    bundle_root = Path(args.bundle).resolve()
    verification = verify_pricing_bundle(bundle_root)
    manifest = json.loads(
        (bundle_root / "pricing-manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("bundleKind") != "response_rich":
        raise RuntimeError("only a response-rich bundle can prepare local activation")
    price_revenue = (manifest.get("capabilities") or {}).get("priceRevenue") or {}
    if price_revenue.get("available") is not True:
        raise RuntimeError("price_revenue is unavailable in the verified bundle")
    intents = manifest.get("prospectiveResultSelections") or []
    if len(intents) != 1:
        raise RuntimeError("verified bundle lacks one prebound selection intent")
    intent = intents[0]
    if any(
        intent.get(key) != value
        for key, value in {
            "retailerId": args.retailer_id,
            "tenantId": args.tenant_id,
            "environment": "local",
            "audience": "response_rich_local",
            "capability": "price_revenue",
        }.items()
    ):
        raise RuntimeError("prebound result-selection intent differs from local scope")
    if bool(args.predecessor_activation_set_id) != bool(
        args.predecessor_selection_record_id
    ):
        raise RuntimeError(
            "successor preparation requires both activation and selection predecessors"
        )
    recorded_at = args.recorded_at or datetime.now(UTC).isoformat().replace(
        "+00:00", "Z"
    )
    records: list[dict] = []
    predecessor: str | None = args.predecessor_selection_record_id
    for state in ("candidate", "approved", "active"):
        record = build_selection_record(
            retailer_id=args.retailer_id,
            tenant_id=args.tenant_id,
            environment="local",
            audience="response_rich_local",
            evidence=intent["evidence"],
            state=state,
            bundle_id=str(manifest["bundleId"]),
            bundle_semantic_fingerprint=str(manifest["semanticFingerprint"]),
            predecessor_record_id=predecessor,
            actor=args.actor,
            reason=args.reason,
            recorded_at=recorded_at,
        )
        validate_selection_record(
            record, root / "contracts/pricing/result-selection.schema.json"
        )
        records.append(record)
        if record["selectionId"] != intent["selectionId"]:
            raise RuntimeError(
                "prepared selection identity differs from the prebound bundle intent"
            )
        predecessor = str(record["recordId"])
    activation = build_activation_set(
        retailer_id=args.retailer_id,
        tenant_id=args.tenant_id,
        environment="local",
        bundle_id=str(manifest["bundleId"]),
        bundle_semantic_fingerprint=str(manifest["semanticFingerprint"]),
        active_selection_ids=[str(records[-1]["selectionId"])],
        predecessor_activation_set_id=args.predecessor_activation_set_id,
        activated_at=recorded_at,
    )
    validate_activation_set(
        activation, root / "contracts/pricing/activation-set.schema.json"
    )
    serving_config = {
        "schemaVersion": "retail-pricing-local-serving-config/v1",
        "configFingerprint": "pending",
        "retailerId": args.retailer_id,
        "tenantId": args.tenant_id,
        "environment": "local",
        "audience": "response_rich_local",
        "activationSetId": activation["activationSetId"],
        "bundleId": manifest["bundleId"],
        "bundleSemanticFingerprint": manifest["semanticFingerprint"],
        "logicalDatabaseTarget": args.logical_database_target,
        "dsnEnvironmentVariable": "RETAIL_POSTGRES_DSN",
    }
    config_projection = dict(serving_config)
    config_projection.pop("configFingerprint")
    serving_config["configFingerprint"] = hashlib.sha256(
        json.dumps(
            config_projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    serving_schema = json.loads(
        (root / "contracts/pricing/local-serving-config.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = sorted(
        Draft202012Validator(
            serving_schema, format_checker=FormatChecker()
        ).iter_errors(serving_config),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise RuntimeError(f"serving configuration is invalid: {errors[0].message}")

    target = Path(args.output).resolve()
    if target.exists():
        raise RuntimeError(f"pricing authority directory already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        documents = {
            "price-revenue-candidate.json": records[0],
            "price-revenue-approved.json": records[1],
            "price-revenue-active.json": records[2],
            "pricing-activation-set.json": activation,
            "pricing-serving.json": serving_config,
        }
        for filename, document in documents.items():
            (staging / filename).write_bytes(_canonical_bytes(document))
        os.replace(staging, target)
    except BaseException:
        for child in staging.iterdir() if staging.exists() else ():
            child.unlink(missing_ok=True)
        staging.rmdir()
        raise
    print(
        json.dumps(
            {
                "authorityDirectory": str(target),
                "bundleId": manifest["bundleId"],
                "verificationPassed": verification["passed"],
                "selectionId": records[-1]["selectionId"],
                "activationSetId": activation["activationSetId"],
                "servingConfig": str(target / "pricing-serving.json"),
            },
            sort_keys=True,
        )
    )
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="retail-pricing")
    commands = root.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    _authority_arguments(build)
    build.add_argument("--curated-database", required=True)
    build.add_argument("--decision-as-of", required=True)
    build.add_argument("--forecast-run")
    build.add_argument("--inventory-run")
    build.add_argument(
        "--competitor-truth",
        help=(
            "restricted held-out competitor truth file; its rows are evaluated "
            "but never copied into the serving bundle"
        ),
    )
    build.add_argument(
        "--bundle-kind", required=True,
        choices=("response_rich", "evidence_sparse"),
    )
    build.add_argument("--output", required=True)
    build.set_defaults(function=_build)
    verify = commands.add_parser("verify")
    _authority_arguments(verify)
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--output", required=True)
    verify.set_defaults(function=_verify)
    materialize = commands.add_parser("materialize")
    _authority_arguments(materialize)
    materialize.add_argument("--bundle", required=True)
    materialize.add_argument("--verification-record", required=True)
    materialize.set_defaults(function=_materialize)
    activate = commands.add_parser("activate")
    activate.add_argument("--repository-root", required=True)
    activate.add_argument("--selection-record", action="append", required=True)
    activate.add_argument("--activation-set", required=True)
    activate.add_argument("--actor", required=True)
    activate.add_argument("--receipt")
    activate.set_defaults(function=_activate)
    prepare = commands.add_parser("prepare-activation")
    prepare.add_argument("--repository-root", required=True)
    prepare.add_argument("--bundle", required=True)
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--retailer-id", required=True)
    prepare.add_argument("--tenant-id", required=True)
    prepare.add_argument("--actor", required=True)
    prepare.add_argument("--reason", required=True)
    prepare.add_argument("--recorded-at")
    prepare.add_argument("--predecessor-activation-set-id")
    prepare.add_argument("--predecessor-selection-record-id")
    prepare.add_argument("--logical-database-target", default="retail_intelligence")
    prepare.set_defaults(function=_prepare_activation)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return int(args.function(args))


if __name__ == "__main__":
    raise SystemExit(main())
