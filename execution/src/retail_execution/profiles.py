"""Resolve bounded execution profiles without retail/business dependencies."""

from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping

PROFILE_SCHEMA_VERSION = "retail-execution-profile/v1"
_PROFILE_NAMES = (
    "safe",
    "balanced",
    "performance",
    "ultra-performance",
    "custom",
)
_DATAGEN_INTEGER_FIELDS = (
    "marketWorkers",
    "partitionWorkers",
    "duckdbThreads",
    "spoolChunkRows",
)
_DATAGEN_FIELDS = _DATAGEN_INTEGER_FIELDS + ("memoryLimitGb",)
_LAYER_FIELDS: dict[str, tuple[str, ...]] = {
    "datagen": _DATAGEN_FIELDS,
    "ingestion": (
        "scanWorkers",
        "transformWorkers",
        "writeWorkers",
        "duckdbThreads",
        "memoryLimitGb",
    ),
    "ml": (
        "featureWorkers",
        "foldWorkers",
        "modelWorkers",
        "threadsPerModel",
        "memoryLimitGb",
    ),
    "api": (
        "backgroundJobWorkers",
        "dbReadPool",
        "gomaxprocs",
        "httpConcurrency",
    ),
}
_PROFILE_FIELDS = {
    "schemaVersion",
    "profile",
    "datagen",
    "ingestion",
    "ml",
    "api",
}
_ENVIRONMENT_OVERRIDES: dict[str, dict[str, str]] = {
    "datagen": {
        "marketWorkers": "RETAIL_DATAGEN_MARKET_WORKERS",
        "partitionWorkers": "RETAIL_DATAGEN_PARTITION_WORKERS",
        "duckdbThreads": "RETAIL_DATAGEN_DUCKDB_THREADS",
        "memoryLimitGb": "RETAIL_DATAGEN_MEMORY_LIMIT_GB",
        "spoolChunkRows": "RETAIL_DATAGEN_SPOOL_CHUNK_ROWS",
    },
    "ingestion": {
        "scanWorkers": "RETAIL_INGESTION_SCAN_WORKERS",
        "transformWorkers": "RETAIL_INGESTION_TRANSFORM_WORKERS",
        "writeWorkers": "RETAIL_INGESTION_WRITE_WORKERS",
        "duckdbThreads": "RETAIL_INGESTION_DUCKDB_THREADS",
        "memoryLimitGb": "RETAIL_INGESTION_MEMORY_LIMIT_GB",
    },
    "ml": {
        "featureWorkers": "RETAIL_ML_FEATURE_WORKERS",
        "foldWorkers": "RETAIL_ML_FOLD_WORKERS",
        "modelWorkers": "RETAIL_ML_MODEL_WORKERS",
        "threadsPerModel": "RETAIL_ML_THREADS_PER_MODEL",
        "memoryLimitGb": "RETAIL_ML_MEMORY_LIMIT_GB",
    },
    "api": {
        "backgroundJobWorkers": "RETAIL_API_BACKGROUND_JOB_WORKERS",
        "dbReadPool": "RETAIL_API_DB_READ_POOL",
        "gomaxprocs": "RETAIL_API_GOMAXPROCS",
        "httpConcurrency": "RETAIL_API_HTTP_CONCURRENCY",
    },
}


class ProfileValidationError(ValueError):
    """Raised when an operational execution profile is unsafe or malformed."""


def _data(name: str) -> Any:
    resource = files("retail_execution").joinpath("data", "v1", name)
    return json.loads(resource.read_text(encoding="utf-8"))


def named_profiles() -> dict[str, dict[str, Any]]:
    """Return a defensive copy of every built-in named profile."""

    return deepcopy(_data("profiles.json"))


@lru_cache(maxsize=1)
def _profile_schema() -> dict[str, Any]:
    return _data("schema.json")


def available_profiles() -> tuple[str, ...]:
    return _PROFILE_NAMES


def load_profile_document(path: str | Path) -> dict[str, Any]:
    """Load a YAML or JSON execution profile.

    PyYAML remains an optional caller dependency so the shared resolver itself
    stays standard-library-only.
    """

    source = Path(path).expanduser().resolve()
    text = source.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise ProfileValidationError(
                "YAML execution profiles require PyYAML in the calling environment"
            ) from exc
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ProfileValidationError(
                f"{source}: invalid YAML: {exc}"
            ) from exc
    if not isinstance(value, dict):
        raise ProfileValidationError("execution profile root must be an object")
    return value


def _merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _validate_schema_node(
    value: Any,
    schema: Mapping[str, Any],
    path: str,
    errors: list[str],
) -> None:
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            errors.append(f"{path} must be an object")
            return
        properties = schema.get("properties", {})
        missing = set(schema.get("required", ())).difference(value)
        for field in sorted(missing):
            errors.append(f"{path}.{field} is required")
        if schema.get("additionalProperties") is False:
            unknown = set(value).difference(properties)
            for field in sorted(unknown):
                errors.append(f"{path}.{field} is not allowed")
        for field, child in value.items():
            child_schema = properties.get(field)
            if child_schema is not None:
                _validate_schema_node(
                    child,
                    child_schema,
                    f"{path}.{field}",
                    errors,
                )
        return
    if expected_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(f"{path} must be an integer")
            return
    elif expected_type == "number":
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
        ):
            errors.append(f"{path} must be a finite number")
            return
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']!r}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path} must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path} must be <= {schema['maximum']}")


def _validate_against_profile_schema(profile: Mapping[str, Any]) -> None:
    errors: list[str] = []
    _validate_schema_node(profile, _profile_schema(), "executionProfile", errors)
    if errors:
        raise ProfileValidationError("; ".join(errors))


def _environment_overrides(
    layer: str,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field, variable in _ENVIRONMENT_OVERRIDES[layer].items():
        raw = environment.get(variable)
        if raw in (None, ""):
            continue
        try:
            values[field] = (
                float(raw)
                if layer == "datagen" and field == "memoryLimitGb"
                else int(raw)
            )
        except ValueError as exc:
            raise ProfileValidationError(
                f"{variable} has invalid numeric value {raw!r}"
            ) from exc
    return values


def resolve_profile(
    name: str | None = None,
    *,
    document: Mapping[str, Any] | None = None,
    datagen_overrides: Mapping[str, Any] | None = None,
    layer_overrides: Mapping[str, Mapping[str, Any]] | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve one profile using deterministic, explicit precedence.

    Precedence is explicit layer overrides, then environment overrides, then a
    supplied profile document, then the named profile, then ``safe``. The legacy
    ``datagen_overrides`` argument remains as a compatibility alias and wins over
    ``layer_overrides["datagen"]`` when both are supplied.
    """

    env = environment if environment is not None else os.environ
    selected = (
        name
        or (str(document.get("profile")) if document and document.get("profile") else None)
        or env.get("RETAIL_EXECUTION_PROFILE")
        or "safe"
    )
    if selected not in _PROFILE_NAMES:
        raise ProfileValidationError(
            f"unknown execution profile {selected!r}; expected one of {_PROFILE_NAMES}"
        )
    presets = named_profiles()
    if selected == "custom" and (
        not document or not isinstance(document.get("datagen"), Mapping)
    ):
        raise ProfileValidationError(
            "custom execution profile requires a profile document with datagen settings"
        )
    base_name = "safe" if selected == "custom" else selected
    resolved = deepcopy(presets[base_name])
    resolved["profile"] = selected
    if document is not None:
        unknown = set(document).difference(_PROFILE_FIELDS)
        if unknown:
            raise ProfileValidationError(
                f"unknown execution profile settings: {sorted(unknown)}"
            )
        missing = {"schemaVersion", "profile", "datagen"}.difference(document)
        if missing:
            raise ProfileValidationError(
                "execution profile document is missing required settings: "
                f"{sorted(missing)}"
            )
        if not isinstance(
            document["datagen"],
            Mapping,
        ):
            raise ProfileValidationError(
                "execution profile document datagen must be an object"
            )
        version = document["schemaVersion"]
        if version != PROFILE_SCHEMA_VERSION:
            raise ProfileValidationError(
                f"unsupported execution profile schemaVersion {version!r}"
            )
        # Validate the supplied document before merging it with a named base.
        # Otherwise an empty custom datagen block silently becomes the safe
        # profile and malformed future-layer settings are hidden by defaults.
        _validate_against_profile_schema(document)
        resolved = _merge(resolved, document)
        resolved["profile"] = selected
    resolved.setdefault("schemaVersion", PROFILE_SCHEMA_VERSION)
    for layer in _LAYER_FIELDS:
        resolved[layer] = _merge(
            resolved.get(layer, {}),
            _environment_overrides(layer, env),
        )
    explicit_layers = layer_overrides or {}
    unknown_layers = set(explicit_layers).difference(_LAYER_FIELDS)
    if unknown_layers:
        raise ProfileValidationError(
            f"unknown execution override layers: {sorted(unknown_layers)}"
        )
    for layer, supplied in explicit_layers.items():
        if not isinstance(supplied, Mapping):
            raise ProfileValidationError(f"{layer} execution overrides must be an object")
        explicit = {key: value for key, value in supplied.items() if value is not None}
        unknown = set(explicit).difference(_LAYER_FIELDS[layer])
        if unknown:
            raise ProfileValidationError(
                f"unknown {layer} execution overrides: {sorted(unknown)}"
            )
        resolved[layer] = _merge(resolved[layer], explicit)
    if datagen_overrides:
        explicit = {
            key: value
            for key, value in datagen_overrides.items()
            if value is not None
        }
        unknown = set(explicit).difference(_DATAGEN_FIELDS)
        if unknown:
            raise ProfileValidationError(
                f"unknown datagen execution overrides: {sorted(unknown)}"
            )
        resolved["datagen"] = _merge(resolved["datagen"], explicit)
    validate_profile(resolved)
    return resolved


def validate_profile(profile: Mapping[str, Any]) -> None:
    """Validate bounded controls shared by every Python caller."""

    _validate_against_profile_schema(profile)
    if profile.get("schemaVersion") != PROFILE_SCHEMA_VERSION:
        raise ProfileValidationError(
            f"schemaVersion must be {PROFILE_SCHEMA_VERSION!r}"
        )
    if profile.get("profile") not in _PROFILE_NAMES:
        raise ProfileValidationError(
            f"profile must be one of {_PROFILE_NAMES}"
        )
    unknown_profile = set(profile).difference(_PROFILE_FIELDS)
    if unknown_profile:
        raise ProfileValidationError(
            f"unknown execution profile settings: {sorted(unknown_profile)}"
        )
    datagen = profile.get("datagen")
    if not isinstance(datagen, Mapping):
        raise ProfileValidationError("datagen execution settings are required")
    unknown = set(datagen).difference(_DATAGEN_FIELDS)
    if unknown:
        raise ProfileValidationError(
            f"unknown datagen execution settings: {sorted(unknown)}"
        )
    for field in _DATAGEN_INTEGER_FIELDS:
        value = datagen.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ProfileValidationError(f"datagen.{field} must be a positive integer")
    memory = datagen.get("memoryLimitGb")
    if (
        not isinstance(memory, (int, float))
        or isinstance(memory, bool)
        or not math.isfinite(float(memory))
        or memory < 0.5
    ):
        raise ProfileValidationError("datagen.memoryLimitGb must be at least 0.5")
    if datagen["marketWorkers"] > 4:
        raise ProfileValidationError("datagen.marketWorkers must be <= 4")
    if datagen["partitionWorkers"] > 32:
        raise ProfileValidationError("datagen.partitionWorkers must be <= 32")
    if datagen["duckdbThreads"] > 32:
        raise ProfileValidationError("datagen.duckdbThreads must be <= 32")
    if datagen["spoolChunkRows"] > 1_000_000:
        raise ProfileValidationError("datagen.spoolChunkRows must be <= 1000000")
    if datagen["partitionWorkers"] * 0.25 > float(memory):
        raise ProfileValidationError(
            "datagen.memoryLimitGb must provide at least 0.25 GiB per partition worker"
        )

    # The JSON schema owns type/range validation for every other layer. Keep this
    # explicit presence check here so callers get a stable contract error even if a
    # future schema revision makes a layer optional for backward compatibility.
    for layer in ("ingestion", "ml", "api"):
        if not isinstance(profile.get(layer), Mapping):
            raise ProfileValidationError(f"{layer} execution settings are required")
