"""PP3-A4: the mapped-files mapping language stays non-Turing-complete.

Decision #68 admits a closed operation set. These tests fail if the allowlist
grows, if a mapping can omit the declarations that make its semantics explicit,
or if a mapping could drop a row without a reason code.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA = REPO_ROOT / "contracts/adapters/mapped-files.schema.json"
STAGING_V2 = REPO_ROOT / "contracts/staging/staging-v2.yaml"

ALLOWED_OPERATIONS = {
    "select",
    "constant",
    "value_map",
    "parse_decimal",
    "parse_integer",
    "parse_date",
    "parse_timestamp",
    "money_major_to_minor",
    "money_major_normalize",
    "quantity",
    "compose_key",
}


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _mapping(**overrides) -> dict:
    dataset = {
        "datasetId": "weekly-sales",
        "role": "merchandise",
        "format": "csv",
        "logicalPath": "sales/weekly.csv",
        "sourceKeys": ["order_no", "line_no"],
        "grain": "order line",
        "timezone": "Europe/London",
        "nullPolicy": {"onMissingRequired": "quarantine"},
        "temporalEvidence": {
            "knownAsOf": {"mode": "column", "column": "posted_at"},
            "grade": "native_posted_available",
        },
        "fields": [
            {"target": "source_sale_id", "operation": "select", "source": "order_no"},
            {
                "target": "net_amount_major",
                "operation": "money_major_normalize",
                "source": "net_value",
                "currencyColumn": "ccy",
            },
        ],
    }
    dataset.update(overrides.pop("dataset", {}))
    mapping = {
        "schemaVersion": "retail-mapped-files/v1",
        "sourceSystem": "generic-flat-file",
        "mappingVersion": "1.0.0",
        "datasets": [dataset],
    }
    mapping.update(overrides)
    return mapping


def test_a_minimal_declarative_mapping_validates(
    validator: Draft202012Validator,
) -> None:
    validator.validate(_mapping())


def test_operation_allowlist_is_closed(schema: dict) -> None:
    operations = set(
        schema["$defs"]["field"]["properties"]["operation"]["enum"]
    )
    assert operations == ALLOWED_OPERATIONS

    for forbidden in ("sql", "python", "eval", "exec", "lambda", "http", "shell"):
        assert forbidden not in operations


def test_an_unlisted_operation_is_rejected(
    validator: Draft202012Validator,
) -> None:
    mapping = _mapping()
    mapping["datasets"][0]["fields"].append(
        {"target": "units", "operation": "run_sql", "source": "SELECT 1"}
    )
    assert not validator.is_valid(mapping)


def test_every_dataset_must_declare_its_semantics(
    validator: Draft202012Validator,
) -> None:
    required = (
        "role",
        "format",
        "logicalPath",
        "sourceKeys",
        "grain",
        "timezone",
        "nullPolicy",
        "temporalEvidence",
        "fields",
    )
    for field in required:
        mapping = _mapping()
        mapping["datasets"][0].pop(field)
        assert not validator.is_valid(mapping), (
            f"a mapping without {field} must be rejected"
        )


def test_temporal_evidence_grade_is_closed_and_explicit(schema: dict) -> None:
    evidence = schema["$defs"]["dataset"]["properties"]["temporalEvidence"]
    grades = set(evidence["properties"]["grade"]["enum"])
    contract = yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))

    assert grades == set(contract["commonFields"]["evidence_grade"]["enum"])
    assert evidence["required"] == ["knownAsOf", "grade"]
    modes = set(evidence["properties"]["knownAsOf"]["properties"]["mode"]["enum"])
    assert modes == {"column", "landing_time"}


def test_a_missing_required_field_can_only_quarantine(schema: dict) -> None:
    policy = schema["$defs"]["dataset"]["properties"]["nullPolicy"]

    assert policy["properties"]["onMissingRequired"]["const"] == "quarantine"
    assert policy["required"] == ["onMissingRequired"]


def test_row_filters_must_carry_a_reason_code(
    schema: dict,
    validator: Draft202012Validator,
) -> None:
    row_filter = schema["$defs"]["dataset"]["properties"]["rowFilter"]
    assert set(row_filter["required"]) == {
        "column",
        "operator",
        "values",
        "reasonCode",
    }
    assert set(row_filter["properties"]["operator"]["enum"]) == {"in", "not_in"}

    mapping = _mapping(
        dataset={
            "rowFilter": {
                "column": "status",
                "operator": "in",
                "values": ["confirmed"],
            }
        }
    )
    assert not validator.is_valid(mapping), (
        "a row filter without a reason code would drop rows silently"
    )


def test_value_map_has_no_default_branch(schema: dict) -> None:
    field = schema["$defs"]["field"]
    description = field["properties"]["map"]["description"]

    assert "UNKNOWN_ENUM_VALUE" in description
    assert "no default branch" in description
    assert "default" not in field["properties"]


def test_parsed_dates_require_an_explicit_format(
    validator: Draft202012Validator,
) -> None:
    mapping = _mapping()
    mapping["datasets"][0]["fields"].append(
        {"target": "business_date", "operation": "parse_date", "source": "day"}
    )
    assert not validator.is_valid(mapping), (
        "an implicit date format is ambiguous across locales"
    )

    mapping["datasets"][0]["fields"][-1]["format"] = "%Y-%m-%d"
    validator.validate(mapping)


def test_logical_paths_cannot_escape_the_landing_root(
    validator: Draft202012Validator,
) -> None:
    for path in ("/etc/passwd", "../../secrets.csv", "sales/../../out.csv"):
        mapping = _mapping(dataset={"logicalPath": path})
        assert not validator.is_valid(mapping), path


def test_only_the_four_supported_physical_formats_are_accepted(
    validator: Draft202012Validator,
) -> None:
    for good in ("csv", "parquet", "jsonl", "json"):
        validator.validate(_mapping(dataset={"format": good}))
    for bad in ("xlsx", "xml", "avro", "sql"):
        assert not validator.is_valid(_mapping(dataset={"format": bad}))


def test_target_roles_exist_in_the_frozen_role_catalog() -> None:
    """A mapping may only target a role that staging v2 actually defines."""

    contract = yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))
    roles = set(contract["roles"])

    # The example mapping used across these tests must stay valid as the
    # catalog evolves.
    assert _mapping()["datasets"][0]["role"] in roles


def test_source_system_id_is_a_dialect_not_a_brand(
    schema: dict,
    validator: Draft202012Validator,
) -> None:
    pattern = schema["properties"]["sourceSystem"]["pattern"]
    assert pattern == "^[a-z][a-z0-9-]{2,63}$"

    # Upper case, spaces and underscores are rejected so ids stay stable,
    # lowercase dialect slugs rather than free-text retailer names.
    for bad in ("Acme Retail", "acme_retail", "AC", "a" * 70):
        assert not validator.is_valid(_mapping(sourceSystem=bad)), bad
