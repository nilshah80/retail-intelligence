#!/usr/bin/env python3
"""Append full-scope v2 source-publication selection lifecycles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "contracts/python/src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "ingestion/src"))

from retail_contracts.fingerprint import canonical_json_bytes  # noqa: E402
from retail_ingestion.readiness.selection import (  # noqa: E402
    IDENTITY_EXCLUDES_V2,
    SELECTION_SCHEMA_VERSION,
    SELECTION_SCHEMA_VERSION_V2,
    derive_record_id_v2,
    derive_selection_id_v2,
    scope_key,
    transition_v2,
    validate_selection,
)


DEFAULT_LEDGER = REPOSITORY_ROOT / "contracts/evidence/publication-selections"
DEFAULT_SCHEMA = (
    REPOSITORY_ROOT / "contracts/onboarding/publication-selection-v2.schema.json"
)


class PublicationAuthorityError(RuntimeError):
    """The requested immutable source authority cannot be proven."""


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PublicationAuthorityError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PublicationAuthorityError(f"JSON document must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _repository_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else REPOSITORY_ROOT / path
    candidate = candidate.resolve()
    try:
        candidate.relative_to(REPOSITORY_ROOT)
    except ValueError as exc:
        raise PublicationAuthorityError(
            f"authority path is outside the repository: {path}"
        ) from exc
    return candidate


def _logical_path(path: Path) -> str:
    return _repository_path(path).relative_to(REPOSITORY_ROOT).as_posix()


def _selection_records(ledger: Path) -> list[tuple[dict[str, Any], Path]]:
    records: list[tuple[dict[str, Any], Path]] = []
    seen_ids: dict[str, Path] = {}
    if not ledger.is_dir():
        raise PublicationAuthorityError(f"selection ledger is absent: {ledger}")
    for path in sorted(ledger.glob("*.json")):
        document = _load(path)
        if document.get("schemaVersion") not in {
            SELECTION_SCHEMA_VERSION,
            SELECTION_SCHEMA_VERSION_V2,
        }:
            continue
        validate_selection(document)
        record_id = str((document.get("lifecycle") or {}).get("recordId") or "")
        if record_id in seen_ids:
            raise PublicationAuthorityError(
                f"duplicate selection record {record_id}: {seen_ids[record_id]} and {path}"
            )
        seen_ids[record_id] = path
        records.append((document, path))
    return records


def _heads(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = list(records)
    superseded = {
        str(row["lifecycle"]["supersedes"])
        for row in rows
        if row["lifecycle"].get("supersedes")
    }
    return [
        row
        for row in rows
        if str(row["lifecycle"]["recordId"]) not in superseded
    ]


def _parse_predecessors(values: Iterable[str]) -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for value in values:
        capability, separator, predecessor = value.partition("=")
        if not separator or not capability or not predecessor or capability in result:
            raise PublicationAuthorityError(
                "--predecessor must be unique capability=genesis or capability=rec_<id>"
            )
        if predecessor == "genesis":
            result[capability] = None
        elif predecessor.startswith("rec_") and len(predecessor) == 20:
            result[capability] = predecessor
        else:
            raise PublicationAuthorityError(
                f"invalid predecessor for {capability}: {predecessor}"
            )
    return result


def _validate_source_evidence(
    *, evidence_root: Path, publication_root: Path, run_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    if evidence_root.name != run_id or publication_root.name != run_id:
        raise PublicationAuthorityError(
            "evidence and publication directories must end in the explicit run ID"
        )
    gate_a = _load(evidence_root / "gate-a.json")
    gate_b = _load(evidence_root / "gate-b.json")
    manifest = _load(evidence_root / "publication-manifest.json")
    readiness = _load(evidence_root / "operational-readiness.json")
    if gate_a.get("status") != "pass" or gate_b.get("status") != "pass":
        raise PublicationAuthorityError("both source gates must pass")
    snapshot = manifest.get("sourceSnapshotId")
    if snapshot != gate_a.get("sourceSnapshotId") or snapshot != gate_b.get(
        "sourceSnapshotId"
    ):
        raise PublicationAuthorityError("source snapshot identity differs across evidence")
    if readiness.get("sourceSnapshotId") != snapshot:
        raise PublicationAuthorityError("readiness sidecar names a different snapshot")
    if readiness.get("gateASemanticFingerprint") != gate_a.get(
        "semanticFingerprint"
    ):
        raise PublicationAuthorityError("readiness sidecar names a different Gate A")
    if readiness.get("gateBSemanticFingerprint") != gate_b.get(
        "semanticFingerprint"
    ):
        raise PublicationAuthorityError("readiness sidecar names a different Gate B")
    if readiness.get("publicationSemanticFingerprint") != manifest.get(
        "semanticFingerprint"
    ):
        raise PublicationAuthorityError("readiness sidecar names a different publication")
    if readiness.get("publicationManifestSha256") != _sha256(
        evidence_root / "publication-manifest.json"
    ):
        raise PublicationAuthorityError("readiness sidecar manifest hash mismatch")
    database = publication_root / str((manifest.get("duckdb") or {}).get("path") or "")
    if not database.is_file() or _sha256(database) != (manifest.get("duckdb") or {}).get(
        "sha256"
    ):
        raise PublicationAuthorityError("curated DuckDB is absent or hash-mismatched")
    return gate_a, gate_b, manifest, readiness


def _validate_v2_schema(document: dict[str, Any], schema: dict[str, Any]) -> None:
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        path = "/" + "/".join(str(part) for part in errors[0].absolute_path)
        raise PublicationAuthorityError(
            f"selection schema violation at {path}: {errors[0].message}"
        )
    validate_selection(document)


def build_source_chains(
    *,
    run_id: str,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    capabilities: Iterable[str],
    predecessors: dict[str, str | None],
    evidence_root: Path,
    publication_root: Path,
    ledger: Path,
    actor: str,
    recorded_at: str,
    reason: str,
    schema_path: Path = DEFAULT_SCHEMA,
) -> list[dict[str, Any]]:
    capabilities = tuple(sorted(set(capabilities)))
    if not capabilities or set(predecessors) != set(capabilities):
        raise PublicationAuthorityError(
            "every requested capability needs exactly one explicit predecessor disposition"
        )
    gate_a, gate_b, manifest, readiness = _validate_source_evidence(
        evidence_root=evidence_root,
        publication_root=publication_root,
        run_id=run_id,
    )
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    existing = _selection_records(ledger)
    existing_rows = [row for row, _ in existing]
    by_id = {str(row["lifecycle"]["recordId"]): row for row in existing_rows}
    heads = _heads(existing_rows)
    head_ids = {str(row["lifecycle"]["recordId"]) for row in heads}
    manifest_path = evidence_root / "publication-manifest.json"
    subject = {
        "kind": "source_publication",
        "sourceSnapshotId": str(manifest["sourceSnapshotId"]),
        "gateASemanticFingerprint": str(gate_a["semanticFingerprint"]),
        "gateBSemanticFingerprint": str(gate_b["semanticFingerprint"]),
        "publicationSemanticFingerprint": str(manifest["semanticFingerprint"]),
        "manifestSha256": _sha256(manifest_path),
        "logicalPath": _logical_path(publication_root),
        "objectCount": len(manifest["objects"]),
        "duckdbSha256": str(manifest["duckdb"]["sha256"]),
    }
    output: list[dict[str, Any]] = []
    for capability in capabilities:
        scope = {
            "retailerId": retailer_id,
            "tenantId": tenant_id,
            "capability": capability,
            "environment": environment,
        }
        requested_scope = (retailer_id, tenant_id, capability, environment)
        scoped = [row for row in existing_rows if scope_key(row) == requested_scope]
        predecessor = predecessors[capability]
        if predecessor is None:
            if scoped:
                raise PublicationAuthorityError(
                    f"{capability} declares genesis but exact-scope history already exists"
                )
        else:
            prior = by_id.get(predecessor)
            if prior is None or scope_key(prior) != requested_scope:
                raise PublicationAuthorityError(
                    f"{capability} predecessor is absent from the exact scope"
                )
            if predecessor not in head_ids or prior["lifecycle"]["state"] != "active":
                raise PublicationAuthorityError(
                    f"{capability} predecessor is not the current active exact-scope head"
                )
        readiness_row = (readiness.get("capabilities") or {}).get(capability)
        if not isinstance(readiness_row, dict):
            raise PublicationAuthorityError(
                f"operational readiness has no {capability} verdict"
            )
        # A source-publication selection authorizes immutable input for a
        # downstream evaluation. It is not a client-facing result claim. The
        # source therefore needs producer-backed readiness and source-input
        # sufficiency, while claimAuthorization remains fail-closed until a
        # separately verified result lifecycle exists.
        if (
            readiness_row.get("readiness") != "ready"
            or readiness_row.get("sufficiency") != "sufficient"
        ):
            raise PublicationAuthorityError(
                f"{capability} cannot be selected: {readiness_row.get('reasonCodes') or readiness_row}"
            )
        candidate: dict[str, Any] = {
            "schemaVersion": SELECTION_SCHEMA_VERSION_V2,
            "selectionId": "sel_0000000000000000",
            "semanticIdentityExcludes": list(IDENTITY_EXCLUDES_V2),
            "scope": scope,
            "subject": dict(subject),
            "readiness": {
                "reportFingerprint": str(readiness["reportFingerprint"]),
                "capabilityReadiness": str(readiness_row["readiness"]),
                "capabilitySufficiency": str(readiness_row["sufficiency"]),
                "claimAuthorization": str(readiness_row["claimAuthorization"]),
                "reasonCodes": sorted(set(readiness_row.get("reasonCodes") or [])),
            },
            "lifecycle": {
                "state": "candidate",
                "supersedes": predecessor,
                "recordId": "rec_0000000000000000",
                "reasonCode": "SOURCE_VERIFIED",
            },
            "approval": {
                "actor": actor,
                "recordedAt": recorded_at,
                "reason": reason,
                "evidenceFingerprint": str(readiness["reportFingerprint"]),
            },
        }
        candidate["selectionId"] = derive_selection_id_v2(candidate)
        candidate["lifecycle"]["recordId"] = derive_record_id_v2(candidate)
        approved = transition_v2(
            candidate,
            "approved",
            actor=actor,
            recorded_at=recorded_at,
            reason=reason,
            evidence_fingerprint=str(readiness["reportFingerprint"]),
            reason_code="SOURCE_APPROVED",
        )
        active = transition_v2(
            approved,
            "active",
            actor=actor,
            recorded_at=recorded_at,
            reason=reason,
            evidence_fingerprint=str(readiness["reportFingerprint"]),
            reason_code="SOURCE_ACTIVE",
        )
        for document in (candidate, approved, active):
            _validate_v2_schema(document, schema)
            output.append(document)
    return output


def write_chains(records: Iterable[dict[str, Any]], *, ledger: Path) -> list[Path]:
    ledger.mkdir(parents=True, exist_ok=True)
    records = list(records)
    staged = Path(tempfile.mkdtemp(prefix=".publication-authority-", dir=ledger))
    destinations: list[Path] = []
    try:
        for record in records:
            record_id = str(record["lifecycle"]["recordId"])
            name = f"publication-selection-{record_id}.json"
            payload = canonical_json_bytes(record)
            destination = ledger / name
            if destination.exists():
                if destination.read_bytes() != payload:
                    raise PublicationAuthorityError(
                        f"immutable selection collision at {destination}"
                    )
            else:
                (staged / name).write_bytes(payload)
            destinations.append(destination)
        for destination in destinations:
            source = staged / destination.name
            if not source.exists():
                continue
            try:
                os.link(source, destination)
            except FileExistsError:
                if destination.read_bytes() != source.read_bytes():
                    raise PublicationAuthorityError(
                        f"immutable selection collision at {destination}"
                    )
        return destinations
    finally:
        for path in staged.iterdir() if staged.exists() else ():
            path.unlink(missing_ok=True)
        staged.rmdir()


def verify_ledger(*, ledger: Path, schema_path: Path = DEFAULT_SCHEMA) -> None:
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    records = _selection_records(ledger)
    rows = [row for row, _ in records]
    by_id = {str(row["lifecycle"]["recordId"]): row for row in rows}
    for row, path in records:
        if row["schemaVersion"] == SELECTION_SCHEMA_VERSION_V2:
            _validate_v2_schema(row, schema)
            expected_name = f"publication-selection-{row['lifecycle']['recordId']}.json"
            if path.name.startswith("publication-selection-rec_") and path.name != expected_name:
                raise PublicationAuthorityError(
                    f"v2 selection filename does not match record ID: {path}"
                )
        predecessor = row["lifecycle"].get("supersedes")
        if predecessor is not None:
            prior = by_id.get(str(predecessor))
            if prior is None or scope_key(prior) != scope_key(row):
                raise PublicationAuthorityError(
                    f"selection predecessor is absent from exact scope: {path}"
                )
    active_heads: dict[tuple[str, str, str, str], str] = {}
    for row in _heads(rows):
        if row["lifecycle"]["state"] != "active":
            continue
        key = scope_key(row)
        if key in active_heads:
            raise PublicationAuthorityError(
                f"multiple current active selections for {'/'.join(key)}"
            )
        active_heads[key] = str(row["lifecycle"]["recordId"])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--run")
    parser.add_argument("--retailer")
    parser.add_argument("--tenant")
    parser.add_argument("--environment", choices=("local", "dev", "staging", "prod"))
    parser.add_argument("--capability", action="append", default=[])
    parser.add_argument("--predecessor", action="append", default=[])
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--publication-root", type=Path)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    parser.add_argument("--actor")
    parser.add_argument("--recorded-at")
    parser.add_argument("--reason")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    ledger = _repository_path(args.ledger)
    schema = _repository_path(args.schema)
    if args.check:
        verify_ledger(ledger=ledger, schema_path=schema)
        print("publication authority ledger is valid")
        return 0
    required = {
        "--run": args.run,
        "--retailer": args.retailer,
        "--tenant": args.tenant,
        "--environment": args.environment,
        "--evidence-root": args.evidence_root,
        "--publication-root": args.publication_root,
        "--actor": args.actor,
        "--recorded-at": args.recorded_at,
        "--reason": args.reason,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing or not args.capability or not args.predecessor:
        raise PublicationAuthorityError(
            "creation requires "
            + ", ".join(missing or [])
            + (", --capability" if not args.capability else "")
            + (", --predecessor" if not args.predecessor else "")
        )
    records = build_source_chains(
        run_id=str(args.run),
        retailer_id=str(args.retailer),
        tenant_id=str(args.tenant),
        environment=str(args.environment),
        capabilities=args.capability,
        predecessors=_parse_predecessors(args.predecessor),
        evidence_root=_repository_path(args.evidence_root),
        publication_root=_repository_path(args.publication_root),
        ledger=ledger,
        actor=str(args.actor),
        recorded_at=str(args.recorded_at),
        reason=str(args.reason),
        schema_path=schema,
    )
    paths = write_chains(records, ledger=ledger)
    verify_ledger(ledger=ledger, schema_path=schema)
    print(
        json.dumps(
            {
                "records": [_logical_path(path) for path in paths],
                "selectionIds": sorted({row["selectionId"] for row in records}),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
