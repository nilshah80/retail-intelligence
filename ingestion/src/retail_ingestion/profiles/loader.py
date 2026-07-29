"""Load and validate stable-named YAML/JSON source profiles."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

PROFILE_SCHEMA_RESOURCE = ("data", "profiles", "profile.schema.json")


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
    "SourceProfileError",
    "load_source_profile",
]
