"""Load and validate stable-named YAML/JSON source profiles."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

PROFILE_SCHEMA_RESOURCE = ("data", "profiles", "profile.schema.json")
STAGING_V2_RESOURCE = ("data", "staging", "staging-v2.yaml")
ROLE_MAP_RESOURCE = ("data", "staging", "role-map.yaml")


def _profile_schema_text() -> str:
    """Read the packaged contract, with an editable-monorepo fallback."""

    resource = files("retail_contracts")
    for part in PROFILE_SCHEMA_RESOURCE:
        resource = resource.joinpath(part)
    if resource.is_file():
        return resource.read_text(encoding="utf-8")
    editable_source = (
        Path(__file__).resolve().parents[4]
        / "contracts"
        / "profiles"
        / "profile.schema.json"
    )
    return editable_source.read_text(encoding="utf-8")


def _contract_text(resource_parts: tuple[str, ...], *fallback: str) -> str:
    resource = files("retail_contracts")
    for part in resource_parts:
        resource = resource.joinpath(part)
    if resource.is_file():
        return resource.read_text(encoding="utf-8")
    return (
        Path(__file__).resolve().parents[4].joinpath("contracts", *fallback)
    ).read_text(encoding="utf-8")


def neutral_relation_roles() -> dict[str, str]:
    """Map each neutral staging relation to the staging-v2 role that supplies it.

    The builder used to infer this by name, which silently broke wherever the neutral
    relation and its role are not spelled the same -- ``locations`` is supplied by the
    ``location`` role, and ``products`` by ``product``. An adapter names its table
    after the role, so an adapter-supplied ``location`` table was invisible to a
    consumer reading ``locations``. The correspondence is declared in role-map.yaml,
    so it is read from there rather than guessed.
    """

    document = yaml.safe_load(_contract_text(ROLE_MAP_RESOURCE, "staging", "role-map.yaml")) or {}
    mapping = document.get("relationRoleMap") or {}
    resolved = {
        str(relation): str(entry["role"])
        for relation, entry in mapping.items()
        if isinstance(entry, dict) and entry.get("role")
    }
    if not resolved:
        raise SourceProfileError("role map declares no relation-to-role mapping")
    return resolved


def staging_v2_roles() -> dict[str, Any]:
    """Return the frozen staging-v2 role catalog.

    The catalog is a platform contract, not retailer configuration, so the builder
    reads it here and injects it into the adapter context. Letting a retailer declare
    ``roleCatalog`` in their own profile would have let them redefine a platform role
    -- including which fields are required -- by editing a file they own.
    """

    document = yaml.safe_load(
        _contract_text(STAGING_V2_RESOURCE, "staging", "staging-v2.yaml")
    ) or {}
    roles = document.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise SourceProfileError("staging-v2 contract declares no roles")
    return roles


class SourceProfileError(ValueError):
    """A source-profile document violates its machine-readable contract."""


def load_source_profile(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        raw = source.read_text(encoding="utf-8")
        value = (
            json.loads(raw)
            if source.suffix.lower() == ".json"
            else yaml.safe_load(raw)
        )
    except (OSError, json.JSONDecodeError, yaml.YAMLError) as exc:
        raise SourceProfileError(f"cannot read source profile {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceProfileError(f"source profile must be an object: {source}")
    try:
        schema = json.loads(_profile_schema_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceProfileError(f"cannot read source-profile schema: {exc}") from exc
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors[:10]
        )
        raise SourceProfileError(f"invalid source profile {source}: {rendered}")
    return value


__all__ = [
    "PROFILE_SCHEMA_RESOURCE",
    "ROLE_MAP_RESOURCE",
    "STAGING_V2_RESOURCE",
    "SourceProfileError",
    "load_source_profile",
    "neutral_relation_roles",
    "staging_v2_roles",
]
