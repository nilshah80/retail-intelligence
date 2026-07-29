"""Gate A: manifest-derived validation before source-specific adaptation.

The gate deliberately operates on immutable landing evidence and source-profile
declarations.  It has no knowledge of ``retail_v2`` and never opens either
restricted permission lane.  Oracle/evaluation tooling may validate those lanes
separately, but ordinary ingestion is confined to ``public/`` by construction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

import duckdb
from retail_contracts.enums import BLOCKING_OUTCOMES, RuleOutcome
from retail_contracts.fingerprint import semantic_fingerprint

from retail_ingestion.landing.snapshot import LANDING_MANIFEST_VERSION
from retail_ingestion.landing.snapshot_id import source_snapshot_id
from retail_ingestion.profiles import load_source_profile

GATE_A_REPORT_VERSION = "retail-ingestion-gate-a/v1"
SHA256_CHUNK_BYTES = 1024 * 1024


class GateAError(RuntimeError):
    """Gate A cannot safely evaluate the supplied snapshot/profile."""


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    outcome: RuleOutcome
    summary: str
    evidence: Mapping[str, Any]
    affected_capability: str | None = None
    reason_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "ruleId": self.rule_id,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "evidence": dict(self.evidence),
        }
        if self.affected_capability is not None:
            value["affectedCapability"] = self.affected_capability
        if self.reason_code is not None:
            value["reasonCode"] = self.reason_code
        return value


@dataclass(frozen=True)
class GateAReport:
    source_snapshot_id: str
    native_snapshot_id: str | None
    profile_id: str
    profile_version: str
    rules: tuple[RuleResult, ...]
    controls_by_currency: Mapping[str, Any]
    dataset_inventory: tuple[Mapping[str, Any], ...]
    execution_profile: Mapping[str, Any]

    @property
    def status(self) -> str:
        return (
            "critical"
            if any(rule.outcome in BLOCKING_OUTCOMES for rule in self.rules)
            else "pass"
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "schemaVersion": GATE_A_REPORT_VERSION,
            "gate": "A",
            "status": self.status,
            "sourceSnapshotId": self.source_snapshot_id,
            "nativeSnapshotId": self.native_snapshot_id,
            "profileId": self.profile_id,
            "profileVersion": self.profile_version,
            "rules": [rule.as_dict() for rule in self.rules],
            "controlsByCurrency": dict(self.controls_by_currency),
            "datasetInventory": [dict(row) for row in self.dataset_inventory],
            "executionProfile": dict(self.execution_profile),
        }
        payload["semanticFingerprint"] = semantic_fingerprint(
            payload, volatile_pointers=("/executionProfile",)
        )
        return payload


def _critical(rule_id: str, summary: str, **evidence: Any) -> RuleResult:
    return RuleResult(rule_id, RuleOutcome.CRITICAL, summary, evidence)


def _pass(rule_id: str, summary: str, **evidence: Any) -> RuleResult:
    return RuleResult(rule_id, RuleOutcome.PASS, summary, evidence)


def _downgrade(
    rule_id: str,
    summary: str,
    *,
    capability: str,
    reason_code: str,
    **evidence: Any,
) -> RuleResult:
    return RuleResult(
        rule_id,
        RuleOutcome.CAPABILITY_DOWNGRADE,
        summary,
        evidence,
        affected_capability=capability,
        reason_code=reason_code,
    )


def _load_json_object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise GateAError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateAError(f"{label} must be a JSON object: {path}")
    return raw, value


def _safe_landed_path(snapshot_root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise GateAError("landing object is missing landedPath")
    logical = PurePosixPath(value)
    if (
        logical.is_absolute()
        or "\\" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise GateAError(f"unsafe landedPath in manifest: {value!r}")
    candidate = snapshot_root.joinpath(*logical.parts).resolve()
    try:
        candidate.relative_to(snapshot_root)
    except ValueError as exc:
        raise GateAError(f"landed object escapes snapshot root: {value!r}") from exc
    return candidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(SHA256_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _profile_rules(profile: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    source_system = str(profile["sourceSystem"])
    rules: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in profile["datasets"]:
        key = (str(row.get("sourceSystem", source_system)), str(row["datasetId"]))
        if key in rules:
            raise GateAError(f"duplicate dataset declaration in profile: {key!r}")
        rules[key] = row
    return rules


def _source_schema_index(
    source_schema: Mapping[str, Any],
) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    rows = source_schema.get("datasets")
    if not isinstance(rows, list):
        raise GateAError("source-schema.json requires a datasets array")
    index: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise GateAError("source-schema.json dataset entries must be objects")
        key = (
            str(row.get("sourceSystem", "")),
            str(row.get("dataset", "")),
            str(row.get("logicalPath", "")),
        )
        if not all(key):
            raise GateAError(f"incomplete source-schema dataset identity: {row!r}")
        if key in index:
            raise GateAError(f"duplicate source-schema dataset identity: {key!r}")
        index[key] = row
    return index


def _public_objects(
    snapshot_root: Path, landing: Mapping[str, Any]
) -> list[tuple[Mapping[str, Any], Path]]:
    selected: list[tuple[Mapping[str, Any], Path]] = []
    for row in landing.get("objects", []):
        if not isinstance(row, dict):
            raise GateAError("landing manifest object entries must be objects")
        path = _safe_landed_path(snapshot_root, row.get("landedPath"))
        if row.get("permissionLane") != "public":
            continue
        try:
            path.relative_to(snapshot_root / "public")
        except ValueError as exc:
            raise GateAError(
                f"public object resolves outside the public lane: {path}"
            ) from exc
        selected.append((row, path))
    return selected


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _source_relation(artifact_format: str) -> str:
    if artifact_format == "parquet":
        return "read_parquet(?)"
    if artifact_format == "csv":
        return "read_csv_auto(?, header=true, all_varchar=true)"
    if artifact_format == "jsonl":
        return "read_json_auto(?, format='newline_delimited')"
    if artifact_format == "json":
        return "read_json_auto(?, format='auto')"
    raise GateAError(f"unsupported tabular Gate A format: {artifact_format!r}")


def _scan_declared_keys(
    *,
    public_objects: Sequence[tuple[Mapping[str, Any], Path]],
    schema_index: Mapping[tuple[str, str, str], Mapping[str, Any]],
    profile_rules: Mapping[tuple[str, str], Mapping[str, Any]],
    scan_data: bool,
    infer_missing_schema: bool,
    connection: duckdb.DuckDBPyConnection,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    grouped: dict[tuple[str, str, str], list[tuple[Mapping[str, Any], Path]]] = {}
    for row, path in public_objects:
        if row.get("format") not in {"parquet", "csv", "jsonl", "json"}:
            continue
        key = (
            str(row.get("sourceSystem", "")),
            str(row.get("dataset", "")),
            str(row.get("logicalPath", "")),
        )
        grouped.setdefault(key, []).append((row, path))

    inventory: list[dict[str, Any]] = []
    schema_errors: list[str] = []
    key_errors: list[str] = []
    for identity, objects in sorted(grouped.items()):
        source_system, dataset, logical_path = identity
        profile_row = profile_rules.get((source_system, dataset))
        if profile_row is None:
            continue
        if profile_row.get("classification") in {"control_only", "excluded"}:
            continue
        artifact_format = str(objects[0][0].get("format"))
        formats = {str(row.get("format")) for row, _ in objects}
        if formats != {artifact_format}:
            schema_errors.append(
                f"{logical_path}: mixed physical formats {sorted(formats)}"
            )
            continue
        if artifact_format != profile_row.get("format"):
            schema_errors.append(
                f"{logical_path}: format {artifact_format!r} != profile "
                f"{profile_row.get('format')!r}"
            )
        schema_row = schema_index.get(identity)
        if schema_row is None and infer_missing_schema:
            paths = [str(path) for _, path in objects]
            relation = _source_relation(artifact_format)
            try:
                described = connection.execute(
                    f"DESCRIBE SELECT * FROM {relation}", [paths]
                ).fetchall()
            except duckdb.Error as exc:
                schema_errors.append(
                    f"{logical_path}: cannot infer source schema: {exc}"
                )
                continue
            schema_row = {
                "fields": [
                    {
                        "name": str(row[0]),
                        "physicalType": str(row[1]),
                        "nullable": True,
                    }
                    for row in described
                ]
            }
        if schema_row is None:
            schema_errors.append(f"{logical_path}: absent from source schema")
            continue
        fields = {
            field.get("name")
            for field in schema_row.get("fields", [])
            if isinstance(field, dict)
        }
        declared = [
            *profile_row.get("sourceKeys", []),
            *profile_row.get("grainFields", []),
        ]
        missing = sorted(set(declared) - fields)
        if missing:
            schema_errors.append(
                f"{logical_path}: missing declared key/grain fields {missing}"
            )
        expected_rows = sum(int(row.get("rows") or 0) for row, _ in objects)
        record: dict[str, Any] = {
            "sourceSystem": source_system,
            "dataset": dataset,
            "logicalPath": logical_path,
            "classification": profile_row["classification"],
            "format": artifact_format,
            "objectCount": len(objects),
            "manifestRows": expected_rows,
            "sourceKeys": list(profile_row.get("sourceKeys", [])),
            "grainFields": list(profile_row.get("grainFields", [])),
        }
        if scan_data and not missing:
            paths = [str(path) for _, path in objects]
            source_keys = list(profile_row.get("sourceKeys", []))
            relation = _source_relation(artifact_format)
            try:
                total = int(
                    connection.execute(
                        f"SELECT count(*) FROM {relation}", [paths]
                    ).fetchone()[0]
                )
                record["scannedRows"] = total
                if total != expected_rows:
                    key_errors.append(
                        f"{logical_path}: manifest rows {expected_rows} != scanned {total}"
                    )
                if source_keys:
                    keys = ", ".join(_quote_identifier(key) for key in source_keys)
                    nullable_keys = set(profile_row.get("nullableSourceKeys", []))
                    required_keys = [
                        key for key in source_keys if key not in nullable_keys
                    ]
                    if required_keys:
                        null_predicate = " OR ".join(
                            f"{_quote_identifier(key)} IS NULL"
                            for key in required_keys
                        )
                        null_count, unique_count = connection.execute(
                            "SELECT "
                            f"count(*) FILTER (WHERE {null_predicate}), "
                            f"count(DISTINCT ({keys})) "
                            f"FROM {relation}",
                            [paths],
                        ).fetchone()
                    else:
                        null_count = 0
                        unique_count = connection.execute(
                            f"SELECT count(DISTINCT ({keys})) FROM {relation}",
                            [paths],
                        ).fetchone()[0]
                    duplicate_count = total - int(unique_count)
                    record["nullSourceKeyRows"] = int(null_count)
                    record["duplicateSourceKeyRows"] = duplicate_count
                    if null_count:
                        key_errors.append(
                            f"{logical_path}: {null_count} rows have NULL source keys"
                        )
                    if duplicate_count:
                        key_errors.append(
                            f"{logical_path}: {duplicate_count} duplicate source keys"
                        )
            except duckdb.Error as exc:
                key_errors.append(
                    f"{logical_path}: cannot scan {artifact_format}: {exc}"
                )
        inventory.append(record)
    return inventory, schema_errors, key_errors


def run_gate_a(
    snapshot_root: str | Path,
    profile_path: str | Path,
    *,
    verify_content: bool = True,
    scan_data: bool = True,
    duckdb_threads: int = 1,
    memory_limit_gb: int = 4,
    execution_profile: Mapping[str, Any] | None = None,
) -> GateAReport:
    """Evaluate A01–A13 against one immutable landing snapshot.

    ``verify_content=False`` is intended only for fast, already-accepted replay.
    The resulting A01 outcome says exactly which verification mode was used.
    """

    root = Path(snapshot_root).expanduser().resolve()
    profile = load_source_profile(profile_path)
    profile_rules = _profile_rules(profile)
    _, landing = _load_json_object(
        root / "landing-manifest.json", "landing manifest"
    )
    if landing.get("schemaVersion") != LANDING_MANIFEST_VERSION:
        raise GateAError(
            f"unsupported landing manifest version: {landing.get('schemaVersion')!r}"
        )
    public_objects = _public_objects(root, landing)
    rules: list[RuleResult] = []

    object_errors: list[str] = []
    for row in landing.get("objects", []):
        path = _safe_landed_path(root, row.get("landedPath"))
        if not path.is_file():
            object_errors.append(f"{row.get('landedPath')}: missing")
            continue
        actual_bytes = path.stat().st_size
        if actual_bytes != row.get("bytes"):
            object_errors.append(
                f"{row.get('landedPath')}: bytes {actual_bytes} != {row.get('bytes')}"
            )
            continue
        if verify_content and row.get("permissionLane") == "public":
            actual_hash = _sha256(path)
            if actual_hash != row.get("sha256"):
                object_errors.append(f"{row.get('landedPath')}: SHA-256 mismatch")
    declared_counts = landing.get("permissionLaneCounts", {})
    actual_counts: dict[str, int] = {
        "public": 0,
        "restricted_truth": 0,
        "restricted_mirror": 0,
    }
    for row in landing.get("objects", []):
        lane = str(row.get("permissionLane"))
        actual_counts[lane] = actual_counts.get(lane, 0) + 1
    if actual_counts != declared_counts:
        object_errors.append(
            f"permission lane counts {actual_counts!r} != {declared_counts!r}"
        )
    a01_evidence = {
        "objectCount": len(landing.get("objects", [])),
        "publicObjectsContentHashed": len(public_objects) if verify_content else 0,
        "restrictedObjectsMetadataChecked": len(landing.get("objects", []))
        - len(public_objects),
        "verificationMode": "public_content_and_all_metadata"
        if verify_content
        else "metadata_only",
    }
    rules.append(
        _critical("A01", "landing object verification failed", errors=object_errors[:50])
        if object_errors
        else _pass("A01", "landing objects match immutable evidence", **a01_evidence)
    )

    upstream_descriptor = landing.get("upstreamManifest", {})
    upstream_path = _safe_landed_path(root, upstream_descriptor.get("path"))
    upstream_errors: list[str] = []
    try:
        upstream_raw, upstream = _load_json_object(
            upstream_path, "retained upstream manifest"
        )
    except GateAError as exc:
        upstream_raw, upstream = b"", {}
        upstream_errors.append(str(exc))
    if upstream_raw:
        if len(upstream_raw) != upstream_descriptor.get("bytes"):
            upstream_errors.append("retained upstream manifest byte count differs")
        if hashlib.sha256(upstream_raw).hexdigest() != upstream_descriptor.get("sha256"):
            upstream_errors.append("retained upstream manifest SHA-256 differs")
        upstream_by_path = {
            row.get("path", row.get("logicalPath")): row
            for row in upstream.get("objects", [])
            if isinstance(row, dict)
        }
        landing_by_path = {
            row.get("objectPath"): row
            for row in landing.get("objects", [])
            if isinstance(row, dict)
        }
        if set(upstream_by_path) != set(landing_by_path):
            upstream_errors.append("upstream and landing object-path sets differ")
        else:
            for path, source in upstream_by_path.items():
                landed = landing_by_path[path]
                if (
                    source.get("bytes"),
                    source.get("sha256"),
                    source.get("rows"),
                ) != (
                    landed.get("bytes"),
                    landed.get("sha256"),
                    landed.get("rows"),
                ):
                    upstream_errors.append(f"{path}: upstream evidence differs")
                    if len(upstream_errors) >= 50:
                        break
    rules.append(
        _critical("A02", "upstream manifest reconciliation failed", errors=upstream_errors)
        if upstream_errors
        else _pass(
            "A02",
            "retained upstream manifest reconciles to landing",
            upstreamManifestSha256=upstream_descriptor.get("sha256"),
            nativeSnapshotId=upstream.get("runId"),
        )
    )

    derived_manifest = str(upstream.get("manifestVersion", "")).startswith(
        "retail-ingestion-derived-source-manifest/"
    )
    source_schema_path = root / "public" / "source-schema.json"
    schema_errors: list[str] = []
    if source_schema_path.is_file():
        try:
            _, source_schema = _load_json_object(source_schema_path, "source schema")
            schema_index = _source_schema_index(source_schema)
        except GateAError as exc:
            source_schema, schema_index = {}, {}
            schema_errors.append(str(exc))
    elif derived_manifest:
        source_schema = {"schemaVersion": "ingestion-inferred-source-schema/v1"}
        schema_index = {}
    else:
        source_schema, schema_index = {}, {}
        schema_errors.append(f"source schema is missing: {source_schema_path}")

    published_keys = {
        (str(row.get("sourceSystem")), str(row.get("dataset")))
        for row, _ in public_objects
    }
    missing_expected = sorted(
        f"{source_system}/{dataset}"
        for (source_system, dataset), declaration in profile_rules.items()
        if declaration.get("expected", True)
        and (source_system, dataset) not in published_keys
    )
    extract_errors: list[str] = []
    extract_window = profile.get("extractWindow", {})
    start = upstream.get("logicalStartDate")
    end = upstream.get("logicalEndDate")
    if extract_window:
        if extract_window.get("start") and start != extract_window["start"]:
            extract_errors.append(
                f"logicalStartDate {start!r} != {extract_window['start']!r}"
            )
        if extract_window.get("end") and end != extract_window["end"]:
            extract_errors.append(
                f"logicalEndDate {end!r} != {extract_window['end']!r}"
            )
    expected_source_version = profile.get("sourceSchemaVersion")
    actual_source_version = upstream.get("sourceSpecVersion")
    if actual_source_version is not None and actual_source_version != expected_source_version:
        extract_errors.append(
            f"sourceSpecVersion {actual_source_version!r} != profile "
            f"{expected_source_version!r}"
        )
    a03_errors = [*missing_expected, *extract_errors]
    rules.append(
        _critical("A03", "expected dataset/extract-window validation failed", errors=a03_errors)
        if a03_errors
        else _pass(
            "A03",
            "expected datasets and extract window are present",
            expectedDatasetCount=sum(
                declaration.get("expected", True)
                for declaration in profile_rules.values()
            ),
            logicalStartDate=start,
            logicalEndDate=end,
        )
    )

    connection = duckdb.connect(":memory:")
    connection.execute(f"SET threads = {max(1, int(duckdb_threads))}")
    connection.execute(f"SET memory_limit = '{max(1, int(memory_limit_gb))}GB'")
    try:
        inventory, discovered_schema_errors, key_errors = _scan_declared_keys(
            public_objects=public_objects,
            schema_index=schema_index,
            profile_rules=profile_rules,
            scan_data=scan_data,
            infer_missing_schema=derived_manifest,
            connection=connection,
        )
    finally:
        connection.close()
    schema_errors.extend(discovered_schema_errors)
    rules.append(
        _critical("A04", "source schema/key/grain validation failed", errors=schema_errors)
        if schema_errors
        else _pass(
            "A04",
            "source schema is parseable and declared key/grain fields exist",
            sourceSchemaVersion=source_schema.get("schemaVersion"),
            schemaDatasetCount=len(schema_index),
        )
    )
    rules.append(
        _critical("A05", "declared source-key validation failed", errors=key_errors[:50])
        if key_errors
        else _pass(
            "A05",
            "declared source keys and snapshot identity are valid",
            dataScanPerformed=scan_data,
            scannedDatasetCount=len(inventory) if scan_data else 0,
        )
    )

    semantics_errors: list[str] = []
    if not profile.get("businessTimezone"):
        semantics_errors.append("businessTimezone is not resolved")
    if not profile.get("quantityPolicy"):
        semantics_errors.append("quantityPolicy is not resolved")
    if not profile.get("money"):
        semantics_errors.append("money/tax policy is not resolved")
    if not profile.get("mappingReferences"):
        semantics_errors.append("mappingReferences are not resolved")
    rules.append(
        _critical("A06", "source operational semantics are unresolved", errors=semantics_errors)
        if semantics_errors
        else _pass(
            "A06",
            "timezone, currency/tax, quantity, grain and mappings are profile-resolved",
            businessTimezone=profile["businessTimezone"],
            quantityPolicy=profile["quantityPolicy"],
            money=profile["money"],
            mappingReferences=profile["mappingReferences"],
        )
    )

    count_errors = [
        f"{row['logicalPath']}: row count mismatch"
        for row in inventory
        if scan_data and row.get("manifestRows") != row.get("scannedRows")
    ]
    rules.append(
        _critical("A07", "input/accepted row reconciliation failed", errors=count_errors)
        if count_errors
        else _pass(
            "A07",
            "input, accepted, rejected and filtered counts reconcile",
            inputRows=sum(row.get("manifestRows", 0) for row in inventory),
            acceptedRows=sum(row.get("scannedRows", row.get("manifestRows", 0)) for row in inventory),
            rejectedRows=0,
            filteredRows=0,
            dataScanPerformed=scan_data,
        )
    )

    controls = upstream.get("controlsByCurrency", {})
    control_errors: list[str] = []
    if not isinstance(controls, dict) or not controls:
        control_errors.append("controlsByCurrency is absent or empty")
        controls = {}
    else:
        for currency, value in controls.items():
            if not isinstance(currency, str) or not isinstance(value, dict):
                control_errors.append(f"invalid currency control: {currency!r}")
                continue
            for field in ("orders", "units", "grossAmount", "netAmount", "taxAmount"):
                if field not in value:
                    control_errors.append(f"{currency}: missing {field}")
    rules.append(
        _downgrade(
            "A08",
            "source controls are unavailable; row inventory remains usable",
            capability="exact_source_reconciliation",
            reason_code="SOURCE_CONTROLS_UNAVAILABLE",
            errors=control_errors,
        )
        if control_errors
        else _pass(
            "A08",
            "per-currency source controls are recorded before transformation",
            currencies=sorted(controls),
        )
    )

    authenticity = profile.get("authenticity", {})
    authenticity_errors: list[str] = []
    mode = authenticity.get("mode")
    if mode not in {"not_required_for_snapshot", "native_evidence"}:
        authenticity_errors.append("authenticity mode is not declared")
    if mode == "native_evidence":
        evidence_dataset = authenticity.get("evidenceDataset")
        if not evidence_dataset or not any(
            dataset == evidence_dataset for _, dataset in published_keys
        ):
            authenticity_errors.append(
                f"authenticity evidence dataset {evidence_dataset!r} is absent"
            )
    rules.append(
        _critical("A09", "required authenticity evidence is absent", errors=authenticity_errors)
        if authenticity_errors
        else _pass(
            "A09",
            "profile-gated authenticity requirement is satisfied",
            mode=mode,
            evidenceDataset=authenticity.get("evidenceDataset"),
        )
    )

    restricted_rows = [
        row
        for row in landing.get("objects", [])
        if row.get("permissionLane") != "public"
    ]
    public_leaks = [
        row.get("landedPath")
        for row, _ in public_objects
        if str(row.get("logicalPath", "")).startswith("_truth/")
        or row.get("format") == "duckdb"
    ]
    rules.append(
        _critical("A10", "restricted object leaked into ordinary ingestion", errors=public_leaks)
        if public_leaks
        else _pass(
            "A10",
            "ordinary Gate A opened only the physical public lane",
            publicObjectsOpened=len(public_objects)
            if verify_content or scan_data
            else 0,
            restrictedObjectsOpened=0,
            restrictedObjectsMetadataOnly=len(restricted_rows),
        )
    )

    non_authoritative = [
        row.get("logicalPath")
        for row, _ in public_objects
        if row.get("sourceSystem") != "generator"
        and row.get("format") not in {"parquet", "csv", "jsonl", "json"}
    ]
    rules.append(
        _critical("A11", "authoritative source lineage is unresolved", errors=non_authoritative)
        if non_authoritative
        else _pass(
            "A11",
            "authoritative public tabular lineage is recorded",
            authoritativeObjects=sum(
                row.get("sourceSystem") != "generator"
                for row, _ in public_objects
            ),
            cacheUsed=False,
        )
    )

    fingerprint_payload = dict(landing)
    recorded_fingerprint = fingerprint_payload.pop("semanticFingerprint", None)
    computed_fingerprint = semantic_fingerprint(
        fingerprint_payload,
        volatile_pointers=("/landingTime", "/executionProfile"),
    )
    landing_execution_profile = landing.get("executionProfile")
    a12_errors: list[str] = []
    if (
        not isinstance(landing_execution_profile, dict)
        or not landing_execution_profile
    ):
        a12_errors.append("resolved execution profile is absent")
    if recorded_fingerprint != computed_fingerprint:
        a12_errors.append("landing semantic fingerprint does not reconcile")
    rules.append(
        _critical("A12", "execution-profile/fingerprint validation failed", errors=a12_errors)
        if a12_errors
        else _pass(
            "A12",
            "execution profile is recorded and excluded from landing identity",
            executionProfile=landing_execution_profile,
            semanticFingerprint=recorded_fingerprint,
        )
    )

    unclassified = sorted(
        f"{source_system}/{dataset}"
        for source_system, dataset in published_keys
        if (source_system, dataset) not in profile_rules
    )
    rules.append(
        _critical("A13", "published datasets are unclassified", errors=unclassified)
        if unclassified
        else _pass(
            "A13",
            "every published dataset has an explicit profile classification",
            classifiedDatasetCount=len(published_keys),
            classifications=sorted(
                {
                    declaration["classification"]
                    for declaration in profile_rules.values()
                }
            ),
        )
    )

    # Re-derive the identity as a second practical collision/corruption safeguard.
    try:
        derived_snapshot_id = source_snapshot_id(
            source_instance=str(landing.get("sourceInstance", "")),
            extract_boundary=str(landing.get("extractBoundary", "")),
            objects=upstream.get("objects", []),
        )
    except Exception as exc:  # reported through A05, not as an unstructured crash
        derived_snapshot_id = ""
        key_errors.append(f"cannot rederive source snapshot ID: {exc}")
    if derived_snapshot_id != landing.get("sourceSnapshotId"):
        replacement = _critical(
            "A05",
            "source snapshot identity does not reconcile",
            expected=landing.get("sourceSnapshotId"),
            actual=derived_snapshot_id,
        )
        rules[rules.index(next(rule for rule in rules if rule.rule_id == "A05"))] = replacement

    return GateAReport(
        source_snapshot_id=str(landing["sourceSnapshotId"]),
        native_snapshot_id=landing.get("nativeSnapshotId"),
        profile_id=str(profile["profileId"]),
        profile_version=str(profile["profileVersion"]),
        rules=tuple(rules),
        controls_by_currency=controls,
        dataset_inventory=tuple(inventory),
        execution_profile=dict(
            execution_profile
            or {
                "affectsRunIdentity": False,
                "duckdbThreads": duckdb_threads,
                "memoryLimitGb": memory_limit_gb,
            }
        ),
    )


__all__ = [
    "GATE_A_REPORT_VERSION",
    "GateAError",
    "GateAReport",
    "RuleResult",
    "run_gate_a",
]
