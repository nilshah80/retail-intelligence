#!/usr/bin/env python3
"""Generate deterministic Python, Go and TypeScript retail_v2 row types."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "retail_v2" / "schema.yaml"
OUTPUT_ROOT = REPO_ROOT / "contracts" / "generated"
HEADER = "Generated from contracts/retail_v2/schema.yaml; DO NOT EDIT."
ACRONYMS = {
    "api": "API",
    "fx": "FX",
    "hmac": "HMAC",
    "id": "ID",
    "sku": "SKU",
    "url": "URL",
}


def _pascal(value: str) -> str:
    return "".join(
        ACRONYMS.get(part, part[:1].upper() + part[1:])
        for part in value.split("_")
    )


def _literal(values: list[Any]) -> str:
    return ", ".join(json.dumps(value, ensure_ascii=False) for value in values)


def _python_type(
    definition: Mapping[str, Any], closed_enums: Mapping[str, list[str]]
) -> str:
    if "enumRef" in definition:
        return _pascal(definition["enumRef"])
    if "enum" in definition:
        return f"Literal[{_literal(definition['enum'])}]"
    return {
        "string": "str",
        "date": "str",
        "timestamp": "str",
        "int32": "int",
        "int64": "int",
        "boolean": "bool",
        "decimal": "str",
        "json": "object",
    }[definition["type"]]


def _go_type(definition: Mapping[str, Any]) -> str:
    if "enumRef" in definition:
        return _pascal(definition["enumRef"])
    return {
        "string": "string",
        "date": "string",
        "timestamp": "string",
        "int32": "int32",
        "int64": "int64",
        "boolean": "bool",
        "decimal": "string",
        "json": "map[string]any",
    }[definition["type"]]


def _typescript_type(definition: Mapping[str, Any]) -> str:
    if "enumRef" in definition:
        return _pascal(definition["enumRef"])
    if "enum" in definition:
        return " | ".join(json.dumps(value) for value in definition["enum"])
    return {
        "string": "string",
        "date": "string",
        "timestamp": "string",
        "int32": "number",
        # JSON transports int64 as decimal text so browsers cannot lose precision.
        "int64": "Int64String",
        "boolean": "boolean",
        "decimal": "string",
        "json": "unknown",
    }[definition["type"]]


def render_python(schema: Mapping[str, Any]) -> str:
    lines = [
        f'"""# {HEADER}"""',
        "",
        "from typing import Literal, NotRequired, TypedDict",
        "",
    ]
    for name, values in schema["closedEnums"].items():
        lines.append(f"{_pascal(name)} = Literal[{_literal(values)}]")
    lines.append("")
    for entity_name, entity in schema["entities"].items():
        lines.append(f"class {_pascal(entity_name)}(TypedDict):")
        for field_name, definition in entity["fields"].items():
            field_type = _python_type(definition, schema["closedEnums"])
            if definition.get("nullable") is True:
                field_type = f"{field_type} | None"
            if not definition["required"]:
                field_type = f"NotRequired[{field_type}]"
            lines.append(f"    {field_name}: {field_type}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_go(schema: Mapping[str, Any]) -> str:
    lines = [
        f"// {HEADER}",
        "",
        "package retailv2",
        "",
    ]
    for name, values in schema["closedEnums"].items():
        type_name = _pascal(name)
        lines.extend((f"type {type_name} string", "", "const ("))
        for value in values:
            constant = _pascal(name) + _pascal(str(value))
            lines.append(f'\t{constant} {type_name} = "{value}"')
        lines.extend((")", ""))
    for entity_name, entity in schema["entities"].items():
        lines.append(f"type {_pascal(entity_name)} struct {{")
        for field_name, definition in entity["fields"].items():
            field_type = _go_type(definition)
            suffix = ""
            if definition.get("nullable") is True:
                field_type = "*" + field_type
            elif not definition["required"] and not field_type.startswith("map["):
                field_type = "*" + field_type
            if not definition["required"]:
                suffix = ",omitempty"
            lines.append(
                f'\t{_pascal(field_name)} {field_type} '
                f'`json:"{field_name}{suffix}"`'
            )
        lines.extend(("}", ""))
    return "\n".join(lines).rstrip() + "\n"


def render_typescript(schema: Mapping[str, Any]) -> str:
    lines = [
        f"// {HEADER}",
        "",
        "export type Int64String = string;",
        "",
    ]
    for name, values in schema["closedEnums"].items():
        union = " | ".join(json.dumps(value) for value in values)
        lines.append(f"export type {_pascal(name)} = {union};")
    lines.append("")
    for entity_name, entity in schema["entities"].items():
        lines.append(f"export interface {_pascal(entity_name)} {{")
        for field_name, definition in entity["fields"].items():
            optional = "" if definition["required"] else "?"
            field_type = _typescript_type(definition)
            if definition.get("nullable") is True:
                field_type = f"{field_type} | null"
            lines.append(
                f"  {field_name}{optional}: {field_type};"
            )
        lines.extend(("}", ""))
    return "\n".join(lines).rstrip() + "\n"


def expected_outputs() -> dict[Path, str]:
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))
    return {
        OUTPUT_ROOT / "python" / "retail_v2_types.py": render_python(schema),
        OUTPUT_ROOT / "go" / "retail_v2_types.go": render_go(schema),
        OUTPUT_ROOT / "typescript" / "retail_v2.ts": render_typescript(schema),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if generated outputs differ; do not write",
    )
    args = parser.parse_args(argv)
    outputs = expected_outputs()
    if args.check:
        stale = [
            str(path.relative_to(REPO_ROOT))
            for path, expected in outputs.items()
            if not path.is_file()
            or path.read_text(encoding="utf-8") != expected
        ]
        if stale:
            print("generated contract types are stale:", file=sys.stderr)
            for path in stale:
                print(f"  {path}", file=sys.stderr)
            return 1
        print("generated contract types are current")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        print(path.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
