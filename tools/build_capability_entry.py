#!/usr/bin/env python3
"""Measure, validate, and atomically adopt capability entry records.

The records capture the exact source/upstream/UI authority at the start of the
pricing-intelligence work. They are semantic and content-addressed; execution
time belongs only to the separate immutable receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

import duckdb
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "contracts" / "python" / "src"))
sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from retail_contracts.capability_entry import (  # noqa: E402
    ENTRY_IDENTITY_EXCLUSIONS,
    adopt_records,
    canonical_document_bytes,
    record_id,
    scope_key,
    validate_exact_file,
)
from retail_ingestion.readiness.selection import (  # noqa: E402
    SELECTION_SCHEMA_VERSION,
    scope_key as selection_scope_key,
    validate_selection,
)

from build_publication_selection import current_records  # noqa: E402

ENTRY_SCHEMA = REPO_ROOT / "contracts/onboarding/capability-entry-record.schema.json"
POINTER_SCHEMA = REPO_ROOT / "contracts/onboarding/capability-entry-pointer.schema.json"
RECEIPT_SCHEMA = REPO_ROOT / "contracts/onboarding/capability-entry-receipt.schema.json"
TENANT_SCHEMA = REPO_ROOT / "contracts/onboarding/tenant-market-set.schema.json"
DEFAULT_TENANT_CONTRACT = (
    REPO_ROOT / "contracts/evidence/tenant-market-sets/gulf-oil-india-local.json"
)
SELECTION_ROOT = REPO_ROOT / "contracts/evidence/publication-selections"
EXPECTED_PIN = REPO_ROOT / "contracts/ml/expected-pin.json"
CAPABILITIES = (
    "demand_forecast_non_pit",
    "inventory_replenishment_current_snapshot",
    "inventory_replenishment_replay",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _migration_head() -> str:
    revisions = sorted(
        path.name[:4]
        for path in (REPO_ROOT / "db/migrations/versions").glob("[0-9][0-9][0-9][0-9]_*.py")
    )
    if not revisions:
        raise RuntimeError("no Alembic revision exists")
    return revisions[-1]


def _active_selections() -> list[tuple[dict[str, Any], Path]]:
    records_with_paths: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(SELECTION_ROOT.glob("*.json")):
        record = _json(path)
        if record.get("schemaVersion") != SELECTION_SCHEMA_VERSION:
            continue
        validate_selection(record)
        records_with_paths.append((record, path))
    current_ids = {
        row["lifecycle"]["recordId"]
        for row in current_records([record for record, _ in records_with_paths])
        if row["lifecycle"]["state"] == "active"
    }
    return [
        (record, path)
        for record, path in records_with_paths
        if record["lifecycle"]["recordId"] in current_ids
    ]


def _expected_pin_check() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools/build_expected_pin.py"), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "exitCode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _pinned_run() -> str:
    generations = _json(REPO_ROOT / "contracts/evidence/publication-selection-generations.json")
    rows = generations if isinstance(generations, list) else generations["generations"]

    def number(row: Mapping[str, Any]) -> int:
        tag = str(row.get("tag") or "")
        return int(tag[1:]) if tag.startswith("r") and tag[1:].isdigit() else -1

    run = str(max(rows, key=number)["run"])
    if not run.startswith("run-"):
        raise RuntimeError("selection-generation ledger has no usable run")
    return run


def _publication(run: str) -> tuple[dict[str, Any], Path, Path]:
    evidence = REPO_ROOT / "ingestion/data/evidence" / run
    publication_root = REPO_ROOT / "ingestion/data/curated" / run
    manifest_path = evidence / "publication-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"retained publication manifest is absent: {manifest_path}")
    return _json(manifest_path), manifest_path, publication_root


def _publication_markets(publication_root: Path) -> list[str]:
    database = publication_root / "retail_v2.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        return [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT market_id FROM canonical_data.stores ORDER BY market_id"
            ).fetchall()
        ]


def _source_findings(publication_root: Path) -> list[dict[str, Any]]:
    database = publication_root / "retail_v2.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        price = connection.execute(
            "SELECT known_as_of_evidence_grade, count(*) "
            "FROM canonical_data.sell_prices GROUP BY 1 ORDER BY 1"
        ).fetchall()
        promotions = connection.execute(
            "SELECT known_as_of_evidence_grade, count(*), "
            "list_sort(list_distinct(list(status))), list_sort(list_distinct(list(type))) "
            "FROM canonical_data.promotions GROUP BY 1 ORDER BY 1"
        ).fetchall()
        matches = connection.execute(
            "SELECT count(*), count(*) FILTER (WHERE matched_attributes IS NULL "
            "OR trim(matched_attributes) = '') FROM canonical_data.competitor_matches"
        ).fetchone()
        cost = connection.execute(
            "SELECT method, known_as_of_evidence_grade, count(*) "
            "FROM canonical_data.inventory_cost GROUP BY 1,2 ORDER BY 1,2"
        ).fetchall()
    return [
        {
            "id": "price-temporal-availability",
            "state": "unavailable" if any(row[0] == "landing_backfill" for row in price) else "available",
            "reasonCode": "PRICE_AVAILABILITY_BACKFILLED" if any(row[0] == "landing_backfill" for row in price) else None,
            "evidence": f"canonical_data.sell_prices evidence grades/counts: {price}",
        },
        {
            "id": "promotion-origin-visibility",
            "state": "unavailable" if any(row[0] == "landing_backfill" for row in promotions) else "available",
            "reasonCode": "NO_ORIGIN_VISIBLE_PROMOTION_PLAN" if any(row[0] == "landing_backfill" for row in promotions) else None,
            "evidence": f"canonical_data.promotions grades/counts/status/type: {promotions}",
        },
        {
            "id": "competitor-match-attributes",
            "state": "open" if matches and matches[1] else "available",
            "reasonCode": "MATCH_ATTRIBUTES_MISSING" if matches and matches[1] else None,
            "evidence": f"competitor matches total/attribute-empty: {matches}",
        },
        {
            "id": "cost-method-provenance",
            "state": "open",
            "reasonCode": "GENERATED_WAC_LABELLED_FIFO",
            "evidence": f"canonical_data.inventory_cost method/grade/counts: {cost}",
        },
        {
            "id": "client-margin-claim",
            "state": "unavailable",
            "reasonCode": "COST_NOT_CLIENT_ACTUAL",
            "evidence": "inventory_cost ownership is PoC-generated; synthetic scenario only",
        },
    ]


def _screen_amendments() -> list[str]:
    values: list[str] = []
    for path in sorted((REPO_ROOT / "contracts/screens").glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in ("amendments", "presentationAmendments"):
            for row in document.get(key, []) or []:
                if row.get("approval", {}).get("status") == "approved":
                    values.append(str(row["amendmentId"]))
    return sorted(set(values))


def _compose_observation() -> dict[str, Any]:
    sql = (
        "SELECT 'migration|'||version_num FROM retail_intelligence_alembic_version;"
        "SELECT 'forecast|'||forecast_run_id||'|'||version_id||'|'||"
        "run_semantic_fingerprint FROM retail_serving.active_forecast_versions;"
        "SELECT 'inventory|'||inventory_run_id||'|'||inventory_version_id||'|'||"
        "run_semantic_fingerprint FROM retail_serving.active_inventory_versions;"
    )
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(REPO_ROOT / "deploy/compose.yaml"),
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "retail",
            "-d",
            "retail_intelligence",
            "-Atc",
            sql,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {
            "state": "unavailable",
            "reason": result.stderr.strip() or "local PostgreSQL could not be queried",
            "forecast": None,
            "inventory": None,
            "migration": None,
        }
    parsed: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split("|")
        if parts and parts[0]:
            if parts[0] in parsed:
                raise RuntimeError(f"multiple live {parts[0]} authority rows")
            parsed[parts[0]] = parts[1:]
    for required in ("migration", "forecast", "inventory"):
        if required not in parsed:
            raise RuntimeError(f"database returned no {required} authority")
    return {
        "state": "verified",
        "reason": None,
        "migration": parsed["migration"][0],
        "forecast": {
            "runId": parsed["forecast"][0],
            "versionId": parsed["forecast"][1],
            "semanticFingerprint": parsed["forecast"][2],
        },
        "inventory": {
            "runId": parsed["inventory"][0],
            "versionId": parsed["inventory"][1],
            "semanticFingerprint": parsed["inventory"][2],
        },
    }


def _authority(
    capability: str, observation: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    forecast = observation.get("forecast")
    inventory = observation.get("inventory")
    forecast_value = {
        "state": "active" if forecast else "unresolved",
        "runId": forecast["runId"] if forecast else None,
        "versionId": forecast["versionId"] if forecast else None,
        "semanticFingerprint": forecast["semanticFingerprint"] if forecast else None,
        "reasonCodes": ["LANDING_BACKFILL_DEPENDENCY"] if capability == "demand_forecast_non_pit" else [],
    }
    if capability == "inventory_replenishment_current_snapshot":
        inventory_value = {
            "state": "active" if inventory else "unresolved",
            "runId": inventory["runId"] if inventory else None,
            "versionId": inventory["versionId"] if inventory else None,
            "semanticFingerprint": inventory["semanticFingerprint"] if inventory else None,
            "reasonCodes": [],
        }
    elif capability == "inventory_replenishment_replay":
        inventory_value = {
            "state": "rejected",
            "runId": inventory["runId"] if inventory else None,
            "versionId": inventory["versionId"] if inventory else None,
            "semanticFingerprint": inventory["semanticFingerprint"] if inventory else None,
            "reasonCodes": ["REPLAY_NO_CANDIDATE_IMPROVEMENT", "REPLAY_GATE_FAILED"],
        }
    else:
        inventory_value = {
            "state": "not_applicable",
            "runId": None,
            "versionId": None,
            "semanticFingerprint": None,
            "reasonCodes": [],
        }
    return forecast_value, inventory_value


def _previous_by_scope() -> dict[tuple[str, str, str, str], str]:
    pointer_path = REPO_ROOT / "contracts/evidence/capability-entry-current.json"
    if not pointer_path.is_file():
        return {}
    pointer = validate_exact_file(pointer_path, POINTER_SCHEMA)
    return {
        scope_key(row["scope"]): str(row["recordId"])
        for row in pointer["entries"]
    }


def build_records(
    *,
    tenant_contract_path: Path,
    starting_commit: str,
    starting_branch: str,
    starting_dirty_paths: Iterable[str],
    observe_compose: bool,
) -> list[dict[str, Any]]:
    tenant = _json(tenant_contract_path)
    from jsonschema import Draft202012Validator, FormatChecker

    tenant_schema = _json(TENANT_SCHEMA)
    Draft202012Validator(tenant_schema, format_checker=FormatChecker()).validate(tenant)
    run = _pinned_run()
    publication, publication_manifest_path, publication_root = _publication(run)
    declared_markets = sorted(row["marketId"] for row in tenant["governedMarkets"])
    publication_markets = _publication_markets(publication_root)
    missing = sorted(set(declared_markets) - set(publication_markets))
    outside = sorted(set(publication_markets) - set(declared_markets))
    if missing:
        raise RuntimeError(f"publication omits declared markets: {missing}")
    active = _active_selections()
    expected_check = _expected_pin_check()
    if expected_check["exitCode"] != 0:
        raise RuntimeError(f"expected pin direct check failed: {expected_check}")
    observation = _compose_observation() if observe_compose else {
        "state": "unavailable",
        "reason": "Compose observation not requested",
        "forecast": None,
        "inventory": None,
        "migration": None,
    }
    if observation["state"] == "verified" and not str(observation["migration"]).startswith(_migration_head()):
        raise RuntimeError(
            f"database migration {observation['migration']} disagrees with repository head {_migration_head()}"
        )
    selection_map: dict[tuple[str, str, str, str], tuple[dict[str, Any], Path]] = {
        selection_scope_key(record): (record, path) for record, path in active
    }
    previous = _previous_by_scope()
    common_findings = _source_findings(publication_root)
    contract_paths = [ENTRY_SCHEMA, POINTER_SCHEMA, RECEIPT_SCHEMA, TENANT_SCHEMA]
    contract_hashes = {
        path.relative_to(REPO_ROOT).as_posix(): _sha256(path)
        for path in contract_paths
    }
    records: list[dict[str, Any]] = []
    for capability in CAPABILITIES:
        key = (
            tenant["retailerId"],
            tenant["tenantId"],
            capability,
            tenant["environment"],
        )
        selected = selection_map.get(key)
        forecast, inventory = _authority(capability, observation)
        scope = {
            "retailerId": key[0],
            "tenantId": key[1],
            "capability": key[2],
            "environment": key[3],
        }
        record: dict[str, Any] = {
            "schemaVersion": "retail-capability-entry-record/v1",
            "identityExclusions": list(ENTRY_IDENTITY_EXCLUSIONS),
            "recordId": "0" * 64,
            "scope": scope,
            "predecessorRecordId": previous.get(key),
            "repository": {
                "branch": starting_branch,
                "commit": starting_commit,
                "dirtyPaths": sorted(set(starting_dirty_paths)),
                "migrationHead": _migration_head(),
                "contractHashes": contract_hashes,
            },
            "tenantMarketSet": {
                "contractPath": tenant_contract_path.relative_to(REPO_ROOT).as_posix(),
                "contractSha256": _sha256(tenant_contract_path),
                "declaredMarkets": declared_markets,
                "publicationMarkets": publication_markets,
                "missingDeclaredMarkets": missing,
                "outOfScopePublicationMarkets": outside,
            },
            "sourceAuthority": {
                "runId": run,
                "sourceSnapshotId": publication["sourceSnapshotId"],
                "publicationPath": publication_root.relative_to(REPO_ROOT).as_posix(),
                "publicationManifestSha256": _sha256(publication_manifest_path),
                "publicationSemanticFingerprint": publication["semanticFingerprint"],
                "objectCount": len(publication["objects"]),
                "gateAStatus": _json(publication_manifest_path.parent / "gate-a.json")["status"],
                "gateBStatus": _json(publication_manifest_path.parent / "gate-b.json")["status"],
                "expectedPinPath": EXPECTED_PIN.relative_to(REPO_ROOT).as_posix(),
                "expectedPinSha256": _sha256(EXPECTED_PIN),
                "expectedPinCheck": expected_check,
                "activeSelection": (
                    {
                        "selectionId": selected[0]["selectionId"],
                        "recordId": selected[0]["lifecycle"]["recordId"],
                        "recordPath": selected[1].relative_to(REPO_ROOT).as_posix(),
                        "recordSha256": _sha256(selected[1]),
                        "resolutionMode": "capability_only",
                        "fullScopeResolutionRequired": True,
                    }
                    if selected is not None
                    else {
                        "state": "unresolved",
                        "reasonCode": "NO_PRIOR_EXACT_SCOPE_SELECTION",
                        "resolutionMode": "full_scope",
                        "fullScopeResolutionRequired": True,
                    }
                ),
            },
            "upstreamAuthority": {
                "forecast": forecast,
                "inventory": inventory,
                "databaseObservation": {
                    "state": observation["state"],
                    "reason": observation["reason"],
                },
            },
            "carryovers": [
                *common_findings,
                {
                    "id": "selection-resolution",
                    "state": "open",
                    "reasonCode": "CAPABILITY_ONLY_SELECTION_LOOKUP",
                    "evidence": "tools/build_expected_pin.py _active_selections keys by capability",
                },
            ],
            "uiReview": {
                "implementedDestinations": 16,
                "openVisualDestinations": 16,
                "approvedAmendments": _screen_amendments(),
            },
            "resumeMatrix": [
                {"dependency": "source bytes or publication identity", "firstConsumer": "source selection and input pin", "successorRequired": "source, feature, forecast, inventory, pricing"},
                {"dependency": "readiness producer or policy", "firstConsumer": "readiness sidecar", "successorRequired": "readiness and downstream capability consumers"},
                {"dependency": "feature identity", "firstConsumer": "forecast build", "successorRequired": "forecast, inventory, pricing"},
                {"dependency": "forecast identity", "firstConsumer": "inventory and pricing context", "successorRequired": "inventory and pricing"},
                {"dependency": "inventory identity", "firstConsumer": "pricing context", "successorRequired": "pricing"},
                {"dependency": "pricing model or policy", "firstConsumer": "recommendation bundle", "successorRequired": "bundle, materialization, activation"},
                {"dependency": "bundle", "firstConsumer": "materialization", "successorRequired": "materialization and activation"},
                {"dependency": "activation set", "firstConsumer": "local serving", "successorRequired": "server startup and UI"},
            ],
        }
        record["recordId"] = record_id(record)
        records.append(record)
    return sorted(records, key=lambda row: scope_key(row["scope"]))


def check_current() -> None:
    pointer_path = REPO_ROOT / "contracts/evidence/capability-entry-current.json"
    pointer = validate_exact_file(pointer_path, POINTER_SCHEMA)
    receipt_id = pointer["lastAdoptionReceiptId"]
    receipt_path = (
        REPO_ROOT
        / "contracts/evidence/capability-entry-receipts"
        / f"capability-entry-receipt-{receipt_id}.json"
    )
    receipt = validate_exact_file(receipt_path, RECEIPT_SCHEMA)
    if receipt["outcome"] != "adopted":
        raise RuntimeError("current pointer names a non-adopted receipt")
    receipt_rows = {
        scope_key(row["scope"]): row for row in receipt["orderedRecords"]
    }
    for row in pointer["entries"]:
        path = REPO_ROOT / row["recordPath"]
        record = validate_exact_file(path, ENTRY_SCHEMA)
        if record["recordId"] != row["recordId"] or record_id(record) != row["recordId"]:
            raise RuntimeError(f"record identity mismatch: {path}")
        if _sha256(path) != row["recordByteSha256"]:
            raise RuntimeError(f"record byte hash mismatch: {path}")
        if row["adoptionReceiptId"] == receipt_id:
            receipt_row = receipt_rows.get(scope_key(row["scope"]))
            if receipt_row is None or receipt_row["recordId"] != row["recordId"]:
                raise RuntimeError(f"receipt does not bind current entry: {path}")
    journal_root = REPO_ROOT / "contracts/evidence/.capability-entry-adoption-staging"
    if journal_root.exists() and list(journal_root.glob("*.json")):
        raise RuntimeError("unfinished capability-entry recovery journal exists")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--observe-compose", action="store_true")
    parser.add_argument("--tenant-contract", type=Path, default=DEFAULT_TENANT_CONTRACT)
    parser.add_argument("--starting-commit", default=None)
    parser.add_argument("--starting-branch", default=None)
    parser.add_argument(
        "--starting-dirty-path",
        action="append",
        default=None,
        help="repeat for each path dirty at implementation start; omit for a clean start",
    )
    args = parser.parse_args(argv)
    if args.check:
        check_current()
        print("capability entry set, pointer, and receipt are valid")
        return 0
    records = build_records(
        tenant_contract_path=args.tenant_contract.resolve(),
        starting_commit=args.starting_commit or _git("rev-parse", "HEAD"),
        starting_branch=args.starting_branch or _git("branch", "--show-current"),
        starting_dirty_paths=args.starting_dirty_path or [],
        observe_compose=bool(args.observe_compose),
    )
    receipt, receipt_path = adopt_records(
        records,
        repository_root=REPO_ROOT,
        entry_schema=ENTRY_SCHEMA,
        pointer_schema=POINTER_SCHEMA,
        receipt_schema=RECEIPT_SCHEMA,
    )
    print(
        json.dumps(
            {
                "outcome": receipt["outcome"],
                "receiptId": receipt["receiptId"],
                "receiptPath": receipt_path.relative_to(REPO_ROOT).as_posix(),
                "recordIds": [row["recordId"] for row in receipt["orderedRecords"]],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if receipt["outcome"] == "adopted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
