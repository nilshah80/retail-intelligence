"""Load and validate the machine-readable ``retail_v2`` contract."""

from __future__ import annotations

import json
import os
from importlib import resources
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator

EXPECTED_ENTITY_COUNT = 53
VERSIONED_ENTITIES = {
    "sales": "sales_version",
    "sales_adjustments": "adjustment_version",
    "sales_fulfillments": "fulfillment_version",
}
CHANNEL_REQUIRED_ENTITIES = {
    "sales",
    "sales_adjustments",
    "sales_fulfillments",
    "sell_prices",
    "assortment_calendar",
    "forecast_series",
    "planner_adjustments",
}
CHANNEL_GRAIN_ENTITIES = {
    "sales",
    "sell_prices",
    "assortment_calendar",
    "forecast_series",
}


class ContractValidationError(ValueError):
    """A machine-readable contract is internally inconsistent."""


def locate_contract_root(explicit: str | Path | None = None) -> Path:
    """Locate ``contracts/`` without assuming POSIX paths or a source checkout."""

    if explicit is not None:
        root = Path(explicit).expanduser().resolve()
        if (root / "retail_v2" / "schema.yaml").is_file():
            return root
        candidate = root / "contracts"
        if (candidate / "retail_v2" / "schema.yaml").is_file():
            return candidate
        raise ContractValidationError(
            f"{root} is neither a contract tree nor a repository containing contracts/"
        )
    configured = os.environ.get("RETAIL_CONTRACTS_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    candidates = [Path.cwd(), *Path(__file__).resolve().parents]
    for candidate in candidates:
        root = candidate / "contracts"
        if (root / "retail_v2" / "schema.yaml").is_file():
            return root
    packaged = resources.files("retail_contracts").joinpath("data")
    packaged_path = Path(str(packaged))
    if (packaged_path / "retail_v2" / "schema.yaml").is_file():
        return packaged_path
    raise ContractValidationError(
        "cannot locate contracts/ or packaged contract data; "
        "set RETAIL_CONTRACTS_ROOT or pass an explicit path"
    )


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path} must contain a mapping")
    return value


def load_retail_v2(root: str | Path | None = None) -> dict[str, Any]:
    contract_root = locate_contract_root(root)
    return load_yaml(contract_root / "retail_v2" / "schema.yaml")


def _required_field(entity: Mapping[str, Any], field: str) -> bool:
    fields = entity.get("fields", {})
    value = fields.get(field)
    return isinstance(value, Mapping) and value.get("required") is True


def validate_retail_v2(document: Mapping[str, Any]) -> None:
    errors: list[str] = []
    if document.get("schemaVersion") != "retail_v2":
        errors.append("schemaVersion must be retail_v2")
    entities = document.get("entities")
    if not isinstance(entities, Mapping):
        raise ContractValidationError("entities must be a mapping")
    if len(entities) != EXPECTED_ENTITY_COUNT:
        errors.append(
            f"expected {EXPECTED_ENTITY_COUNT} entities, found {len(entities)}"
        )
    types = set(document.get("typeVocabulary", ()))
    tiers = set(document.get("closedEnums", {}).get("entityTier", ()))

    for name, entity in entities.items():
        if not isinstance(entity, Mapping):
            errors.append(f"{name}: definition must be a mapping")
            continue
        fields = entity.get("fields")
        grain = entity.get("grain")
        primary_key = entity.get("primaryKey")
        if not isinstance(fields, Mapping) or not fields:
            errors.append(f"{name}: fields must be a non-empty mapping")
            continue
        if not isinstance(grain, list) or not grain:
            errors.append(f"{name}: grain must be a non-empty list")
        if not isinstance(primary_key, list) or not primary_key:
            errors.append(f"{name}: primaryKey must be a non-empty list")
            primary_key = []
        for key in primary_key:
            if key not in fields:
                errors.append(f"{name}: primary-key field {key!r} is undefined")
            elif not _required_field(entity, key):
                errors.append(f"{name}: primary-key field {key!r} must be required")
        if entity.get("tier") not in tiers:
            errors.append(f"{name}: unknown tier {entity.get('tier')!r}")
        for field_name, definition in fields.items():
            if not isinstance(definition, Mapping):
                errors.append(f"{name}.{field_name}: definition must be a mapping")
                continue
            if definition.get("type") not in types:
                errors.append(
                    f"{name}.{field_name}: unknown type {definition.get('type')!r}"
                )
            if definition.get("required") not in {True, False}:
                errors.append(f"{name}.{field_name}: required must be boolean")
            if definition.get("nullable", False) not in {True, False}:
                errors.append(
                    f"{name}.{field_name}: nullable must be boolean when supplied"
                )
            if definition.get("semantic") == "money_minor" and definition.get(
                "type"
            ) != "int64":
                errors.append(f"{name}.{field_name}: money_minor must be int64")
            enum_reference = definition.get("enumRef")
            if enum_reference is not None:
                if enum_reference not in document.get("closedEnums", {}):
                    errors.append(
                        f"{name}.{field_name}: unknown enumRef {enum_reference!r}"
                    )
                if "enum" in definition:
                    errors.append(
                        f"{name}.{field_name}: enum and enumRef are mutually exclusive"
                    )

        temporal_class = entity.get("temporalClass")
        if temporal_class is not None:
            if temporal_class not in {"cumulative_versioned", "observational"}:
                errors.append(f"{name}: unknown temporalClass {temporal_class!r}")
            if not _required_field(entity, "known_as_of"):
                errors.append(f"{name}: temporal entity requires known_as_of")
            if not _required_field(entity, "known_as_of_evidence_grade"):
                errors.append(
                    f"{name}: temporal entity requires known_as_of_evidence_grade"
                )
            elif (
                fields["known_as_of_evidence_grade"].get("enumRef")
                != "evidenceGrade"
            ):
                errors.append(
                    f"{name}: known_as_of_evidence_grade must reference evidenceGrade"
                )

    actual_versioned = {
        name
        for name, entity in entities.items()
        if entity.get("temporalClass") == "cumulative_versioned"
    }
    if actual_versioned != set(VERSIONED_ENTITIES):
        errors.append(
            "cumulative_versioned entities must be exactly "
            f"{sorted(VERSIONED_ENTITIES)}, found {sorted(actual_versioned)}"
        )
    for name, version_field in VERSIONED_ENTITIES.items():
        entity = entities.get(name, {})
        if entity.get("versionField") != version_field:
            errors.append(f"{name}: versionField must be {version_field}")
        if version_field not in entity.get("primaryKey", ()):
            errors.append(f"{name}: version field must participate in primaryKey")

    for name in CHANNEL_REQUIRED_ENTITIES:
        entity = entities.get(name)
        if not isinstance(entity, Mapping):
            errors.append(f"missing channel-grain entity {name}")
            continue
        if not _required_field(entity, "channel_id"):
            errors.append(f"{name}: channel_id must be required")
        if name in CHANNEL_GRAIN_ENTITIES and "channel_id" not in entity.get("grain", ()):
            errors.append(f"{name}: channel_id must participate in grain")
    if "channel_id" in entities.get("stores", {}).get("fields", {}):
        errors.append("stores: channel is orthogonal and must not be a store field")

    rule_outcomes = document.get("closedEnums", {}).get("ruleOutcome")
    if rule_outcomes != ["pass", "warning", "capability_downgrade", "critical"]:
        errors.append("ruleOutcome enum is not the locked four-value contract")

    if errors:
        raise ContractValidationError("\n".join(errors))


def validate_tiers(
    schema: Mapping[str, Any],
    tiers_document: Mapping[str, Any],
) -> None:
    entities = set(schema["entities"])
    assignments: dict[str, str] = {}
    errors: list[str] = []
    for tier, definition in tiers_document.get("tiers", {}).items():
        for entity in definition.get("entities", ()):
            if entity in assignments:
                errors.append(
                    f"{entity} appears in both {assignments[entity]} and {tier}"
                )
            assignments[entity] = tier
    if set(assignments) != entities:
        errors.append(
            f"tier inventory differs: missing={sorted(entities-set(assignments))}, "
            f"extra={sorted(set(assignments)-entities)}"
        )
    for entity, tier in assignments.items():
        if schema["entities"][entity]["tier"] != tier:
            errors.append(
                f"{entity}: schema tier {schema['entities'][entity]['tier']} != {tier}"
            )
    supporting = tiers_document["tiers"]["t1_core"].get(
        "stagedSupportingDatasets", []
    )
    if supporting != ["store_assortment"]:
        errors.append("store_assortment must be the staged T1 supporting dataset")
    if errors:
        raise ContractValidationError("\n".join(errors))


def validate_json_schema(path: Path) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)


def validate_openapi(path: Path) -> None:
    """Validate the stable Phase-2 surface without introducing a second toolchain."""

    document = load_yaml(path)
    if not str(document.get("openapi", "")).startswith("3.1."):
        raise ContractValidationError("OpenAPI contract must use 3.1")
    expected_paths = {
        "/healthz",
        "/api/v1/data-management/summary",
        "/api/v1/data-management/gates",
        "/api/v1/data-management/capabilities",
        "/api/v1/data-management/reconciliation",
        "/api/v1/data-management/quality-findings",
    }
    paths = document.get("paths")
    if not isinstance(paths, Mapping) or set(paths) != expected_paths:
        raise ContractValidationError("Phase-2 OpenAPI path inventory drifted")
    operation_ids: list[str] = []
    for endpoint, methods in paths.items():
        if not isinstance(methods, Mapping) or "get" not in methods:
            raise ContractValidationError(f"{endpoint}: GET operation is absent")
        operation = methods["get"]
        if not isinstance(operation, Mapping) or not operation.get("operationId"):
            raise ContractValidationError(f"{endpoint}: operationId is absent")
        if "200" not in operation.get("responses", {}):
            raise ContractValidationError(f"{endpoint}: 200 response is absent")
        operation_ids.append(str(operation["operationId"]))
    if len(operation_ids) != len(set(operation_ids)):
        raise ContractValidationError("OpenAPI operationId values must be unique")


def validate_contract_tree(root: str | Path | None = None) -> dict[str, int]:
    contract_root = locate_contract_root(root)
    schema = load_yaml(contract_root / "retail_v2" / "schema.yaml")
    validate_retail_v2(schema)
    tiers = load_yaml(contract_root / "retail_v2" / "tiers.yaml")
    validate_tiers(schema, tiers)
    determinism = load_yaml(contract_root / "retail_v2" / "determinism.yaml")
    if determinism.get("schemaVersion") != "retail-determinism/v1":
        raise ContractValidationError("unknown determinism contract version")
    expected_semantic_outputs = {
        "accepted_row_set",
        "quarantined_row_set",
        "quarantine_reason_codes",
        "reconciliation_controls",
        "capability_mask",
        "semantic_fingerprints",
    }
    actual_semantic_outputs = set(
        determinism.get("profileInvariance", {}).get(
            "requiredSemanticEquality", ()
        )
    )
    if actual_semantic_outputs != expected_semantic_outputs:
        raise ContractValidationError(
            "determinism requiredSemanticEquality inventory drifted"
        )
    if (
        determinism.get("byteEquality", {}).get("acceptanceRole")
        != "secondary_unless_writer_fully_pinned"
    ):
        raise ContractValidationError("determinism byte-equality policy drifted")
    staging = load_yaml(contract_root / "staging" / "staging.yaml")
    if set(staging.get("envelopes", {})) != {
        "merchandise",
        "adjustment",
        "fulfillment",
        "inventory",
        "receipt",
        "dimension_signal",
    }:
        raise ContractValidationError("staging contract must define exactly six envelopes")
    validate_json_schema(contract_root / "profiles" / "profile.schema.json")
    validate_json_schema(contract_root / "coverage" / "coverage.schema.json")
    validate_openapi(contract_root / "api" / "openapi.yaml")
    from .fingerprint import canonical_json_bytes
    from .guardrails import resolve_guardrails, resolved_guardrail_fingerprint

    guardrail_vectors = json.loads(
        (contract_root / "guardrails" / "resolved-policy-v1.json").read_text(
            encoding="utf-8"
        )
    )
    for vector in guardrail_vectors["vectors"]:
        resolved = resolve_guardrails(
            vector["marketId"], vector["currencyCode"], root=contract_root
        )
        if canonical_json_bytes(resolved).decode("utf-8") != vector["canonical"]:
            raise ContractValidationError(
                f"resolved guardrail bytes drifted for {vector['marketId']}"
            )
        if (
            resolved_guardrail_fingerprint(
                vector["marketId"], vector["currencyCode"], root=contract_root
            )
            != vector["sha256"]
        ):
            raise ContractValidationError(
                f"resolved guardrail fingerprint drifted for {vector['marketId']}"
            )
    return {
        "entities": len(schema["entities"]),
        "tiers": len(tiers["tiers"]),
        "stagingEnvelopes": len(staging["envelopes"]),
        "jsonSchemas": 2,
        "openApiContracts": 1,
        "guardrailVectors": len(guardrail_vectors["vectors"]),
        "determinismContracts": 1,
    }


__all__ = [
    "CHANNEL_GRAIN_ENTITIES",
    "CHANNEL_REQUIRED_ENTITIES",
    "EXPECTED_ENTITY_COUNT",
    "VERSIONED_ENTITIES",
    "ContractValidationError",
    "load_retail_v2",
    "locate_contract_root",
    "validate_contract_tree",
    "validate_json_schema",
    "validate_openapi",
    "validate_retail_v2",
    "validate_tiers",
]
