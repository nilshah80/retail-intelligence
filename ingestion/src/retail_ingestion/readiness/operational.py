"""Identity-safe operational readiness produced after curated publication.

The sidecar points one way: it binds immutable Gate A, Gate B and publication
identities, while none of those upstream artifacts includes or changes because
of this report. Sufficiency is derived only by versioned producers; client-
claim authorization remains separate and fail-closed at source-publication
time.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from retail_contracts.fingerprint import semantic_fingerprint

REPORT_SCHEMA_VERSION = "retail-operational-readiness/v2"
RETENTION_SCHEMA_VERSION = "retail-operational-readiness-retention/v1"
IDENTITY_EXCLUDES = ("/producedAt", "/reportFingerprint")
EXPECTED_CAPABILITIES = (
    "competitor_intelligence",
    "demand_forecast_non_pit",
    "inventory_replenishment_current_snapshot",
    "inventory_replenishment_replay",
    "price_margin",
    "price_revenue",
    "price_simulation",
    "promotion_planning",
    "promotion_response",
)


class OperationalReadinessError(RuntimeError):
    """The sidecar cannot be derived or validated without inventing evidence."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        for chunk in iter(lambda: reader.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reason_codes(entry: Mapping[str, Any]) -> list[str]:
    values = list(entry.get("reasonCodes") or [])
    if entry.get("reasonCode"):
        values.append(str(entry["reasonCode"]))
    return sorted(set(values))


_MISSING = object()


def _json_pointer(document: Mapping[str, Any], pointer: str) -> Any:
    if not pointer.startswith("/"):
        raise OperationalReadinessError(
            f"producer predicate is not an RFC 6901 pointer: {pointer!r}"
        )
    value: Any = document
    for encoded in pointer[1:].split("/"):
        token = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(value, Mapping) and token in value:
            value = value[token]
        else:
            return _MISSING
    return value


def _predicate_matches(value: Any, predicate: Mapping[str, Any]) -> bool:
    operators = [name for name in ("equals", "minimum") if name in predicate]
    if len(operators) != 1:
        raise OperationalReadinessError(
            "producer predicate must declare exactly one of equals or minimum"
        )
    if operators[0] == "equals":
        return value == predicate["equals"]
    minimum = predicate["minimum"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)):
        raise OperationalReadinessError("producer minimum must be numeric")
    return value >= minimum


def _registry_sufficiency(
    *, capability: str, gate_b: Mapping[str, Any], producer_registry: Mapping[str, Any]
) -> tuple[str, str | None, list[str]]:
    """Evaluate the declared source-input sufficiency producer, if one exists."""

    applicable = [
        producer
        for producer in producer_registry.get("producers", [])
        if isinstance(producer, Mapping)
        and "sufficiency" in (producer.get("fields") or [])
        and capability in (producer.get("appliesToCapabilities") or [])
    ]
    if len(applicable) > 1:
        raise OperationalReadinessError(
            f"multiple sufficiency producers apply to {capability}"
        )
    if not applicable:
        return "not_evaluated", None, ["STATISTICAL_SUFFICIENCY_NOT_EVALUATED"]

    producer = applicable[0]
    producer_id = str(producer.get("producerId") or "")
    predicates = producer.get("predicates")
    if not producer_id or not isinstance(predicates, list) or not predicates:
        raise OperationalReadinessError(
            f"sufficiency producer for {capability} is incomplete"
        )
    values: list[tuple[Any, Mapping[str, Any]]] = []
    for predicate in predicates:
        if not isinstance(predicate, Mapping) or not isinstance(
            predicate.get("pointer"), str
        ):
            raise OperationalReadinessError(
                f"sufficiency producer {producer_id} has an invalid predicate"
            )
        values.append((_json_pointer(gate_b, predicate["pointer"]), predicate))

    if any(value is _MISSING for value, _ in values):
        disposition = str(producer.get("missingDisposition") or "")
        reason = str(producer.get("missingReasonCode") or "")
    elif all(_predicate_matches(value, predicate) for value, predicate in values):
        disposition = str(producer.get("satisfiedDisposition") or "")
        reason = ""
    else:
        disposition = str(producer.get("failedDisposition") or "")
        reason = str(producer.get("failureReasonCode") or "")
    if disposition not in {
        "sufficient",
        "insufficient_evidence",
        "not_evaluated",
    }:
        raise OperationalReadinessError(
            f"sufficiency producer {producer_id} emitted invalid disposition"
        )
    if disposition != "sufficient" and not reason:
        raise OperationalReadinessError(
            f"sufficiency producer {producer_id} omitted its failure reason"
        )
    return disposition, producer_id, [reason] if reason else []


def build_operational_readiness(
    *,
    gate_a: Mapping[str, Any],
    gate_b: Mapping[str, Any],
    publication_manifest: Mapping[str, Any],
    publication_manifest_sha256: str,
    producer_registry: Mapping[str, Any],
    produced_at: str | None = None,
) -> dict[str, Any]:
    """Build a report without treating an absent producer as a positive fact."""

    if gate_a.get("status") != "pass" or gate_b.get("status") != "pass":
        raise OperationalReadinessError("both source gates must pass")
    if gate_a.get("sourceSnapshotId") != publication_manifest.get("sourceSnapshotId"):
        raise OperationalReadinessError("Gate A and publication snapshot disagree")
    if gate_b.get("sourceSnapshotId") != publication_manifest.get("sourceSnapshotId"):
        raise OperationalReadinessError("Gate B and publication snapshot disagree")
    recorded_registry = producer_registry.get("registryFingerprint")
    computed_registry = semantic_fingerprint(
        dict(producer_registry), volatile_pointers=("/registryFingerprint",)
    )
    if recorded_registry != computed_registry:
        raise OperationalReadinessError("producer registry fingerprint mismatch")

    mask = gate_b.get("capabilityMask")
    if not isinstance(mask, Mapping):
        raise OperationalReadinessError("Gate B capabilityMask is absent")
    names = sorted(set(mask) | set(EXPECTED_CAPABILITIES))
    capabilities: dict[str, Any] = {}
    for name in names:
        raw = mask.get(name)
        producer_ids: list[str]
        if not isinstance(raw, Mapping):
            readiness = "unavailable"
            reasons = ["MISSING_READINESS_PRODUCER"]
            producer_ids = ["registry.missing-producer"]
        else:
            available = raw.get("available")
            if not isinstance(available, bool):
                raise OperationalReadinessError(
                    f"Gate B capability {name} has no strict boolean availability"
                )
            readiness = "ready" if available else "unavailable"
            reasons = _reason_codes(raw)
            if not available and not reasons:
                reasons = ["SOURCE_CAPABILITY_UNAVAILABLE"]
            producer_ids = ["gate-b.capability-mask"]

        measured_sufficiency, sufficiency_producer, sufficiency_reasons = (
            _registry_sufficiency(
                capability=name,
                gate_b=gate_b,
                producer_registry=producer_registry,
            )
        )
        reasons.extend(sufficiency_reasons)
        if sufficiency_producer:
            producer_ids.append(sufficiency_producer)

        authorization = (
            "descriptive_only" if readiness == "ready" else "not_authorized"
        )
        if authorization == "descriptive_only":
            reasons.append("CLIENT_CLAIM_NOT_AUTHORIZED")

        capabilities[name] = {
            "readiness": readiness,
            "sufficiency": measured_sufficiency,
            "claimAuthorization": authorization,
            "consumerMayProceed": (
                readiness == "ready"
                and measured_sufficiency == "sufficient"
                and authorization == "authorized"
            ),
            "producerIds": sorted(set(producer_ids)),
            "reasonCodes": sorted(set(reasons)),
        }

    report: dict[str, Any] = {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "semanticIdentityExcludes": list(IDENTITY_EXCLUDES),
        "reportFingerprint": "0" * 64,
        "sourceSnapshotId": str(publication_manifest["sourceSnapshotId"]),
        "gateASemanticFingerprint": str(gate_a["semanticFingerprint"]),
        "gateBSemanticFingerprint": str(gate_b["semanticFingerprint"]),
        "publicationSemanticFingerprint": str(
            publication_manifest["semanticFingerprint"]
        ),
        "publicationManifestSha256": publication_manifest_sha256,
        "producerRegistryFingerprint": str(recorded_registry),
        "capabilities": capabilities,
        "summary": {
            "ready": sorted(
                name for name, value in capabilities.items() if value["readiness"] == "ready"
            ),
            "validatedPartial": sorted(
                name
                for name, value in capabilities.items()
                if value["readiness"] == "validated_partial"
            ),
            "unavailable": sorted(
                name
                for name, value in capabilities.items()
                if value["readiness"] == "unavailable"
            ),
            "blocked": sorted(
                name
                for name, value in capabilities.items()
                if value["readiness"] == "blocked"
            ),
        },
        "producedAt": produced_at
        or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    report["reportFingerprint"] = semantic_fingerprint(
        report, volatile_pointers=IDENTITY_EXCLUDES
    )
    return report


def validate_operational_readiness(
    report: Mapping[str, Any], *, schema_path: Path
) -> None:
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(report)
    expected = semantic_fingerprint(
        dict(report), volatile_pointers=IDENTITY_EXCLUDES
    )
    if report.get("reportFingerprint") != expected:
        raise OperationalReadinessError("readiness report fingerprint mismatch")


def build_readiness_retention(
    *, readiness_path: Path, report: Mapping[str, Any]
) -> dict[str, Any]:
    """Bind the exact retained sidecar bytes without changing source identity."""

    if readiness_path.name != "operational-readiness.json":
        raise OperationalReadinessError(
            "readiness retention requires the canonical sidecar filename"
        )
    return {
        "schemaVersion": RETENTION_SCHEMA_VERSION,
        "sourceSnapshotId": str(report["sourceSnapshotId"]),
        "publicationSemanticFingerprint": str(
            report["publicationSemanticFingerprint"]
        ),
        "readinessReportFingerprint": str(report["reportFingerprint"]),
        "producerRegistryFingerprint": str(report["producerRegistryFingerprint"]),
        "files": {"operational-readiness.json": _sha256(readiness_path)},
    }


def validate_readiness_retention(
    retention: Mapping[str, Any],
    *,
    schema_path: Path,
    readiness_path: Path,
    readiness_schema_path: Path,
) -> None:
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(retention)
    report = _load(readiness_path)
    validate_operational_readiness(report, schema_path=readiness_schema_path)
    expected = build_readiness_retention(
        readiness_path=readiness_path,
        report=report,
    )
    if dict(retention) != expected:
        raise OperationalReadinessError(
            "readiness retention record differs from the exact retained sidecar"
        )


def write_readiness_retention(
    *,
    readiness_path: Path,
    destination: Path,
    schema_path: Path,
    readiness_schema_path: Path,
) -> dict[str, Any]:
    """Create or verify the separate immutable readiness retention record."""

    report = _load(readiness_path)
    validate_operational_readiness(report, schema_path=readiness_schema_path)
    retention = build_readiness_retention(
        readiness_path=readiness_path,
        report=report,
    )
    schema = _load(schema_path)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema, format_checker=FormatChecker()
    ).validate(retention)
    if destination.exists():
        existing = _load(destination)
        validate_readiness_retention(
            existing,
            schema_path=schema_path,
            readiness_path=readiness_path,
            readiness_schema_path=readiness_schema_path,
        )
        return existing
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(retention, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)
    return retention


def write_operational_readiness_sidecar(
    *,
    gate_a_path: Path,
    gate_b_path: Path,
    publication_manifest_path: Path,
    destination: Path,
    producer_registry_path: Path,
    schema_path: Path,
) -> dict[str, Any]:
    """Create or verify the retained sidecar without changing publication bytes."""

    report = build_operational_readiness(
        gate_a=_load(gate_a_path),
        gate_b=_load(gate_b_path),
        publication_manifest=_load(publication_manifest_path),
        publication_manifest_sha256=_sha256(publication_manifest_path),
        producer_registry=_load(producer_registry_path),
    )
    validate_operational_readiness(report, schema_path=schema_path)
    if destination.exists():
        existing = _load(destination)
        validate_operational_readiness(existing, schema_path=schema_path)
        if existing["reportFingerprint"] != report["reportFingerprint"]:
            raise OperationalReadinessError(
                "existing readiness sidecar describes different upstream evidence"
            )
        return existing
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(destination)
    return report


__all__ = [
    "EXPECTED_CAPABILITIES",
    "IDENTITY_EXCLUDES",
    "OperationalReadinessError",
    "REPORT_SCHEMA_VERSION",
    "RETENTION_SCHEMA_VERSION",
    "build_readiness_retention",
    "build_operational_readiness",
    "validate_readiness_retention",
    "validate_operational_readiness",
    "write_readiness_retention",
    "write_operational_readiness_sidecar",
]
