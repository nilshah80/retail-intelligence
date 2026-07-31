"""Profile-driven `mapped_files` adapter.

Onboards an ordinary client file drop through declarative configuration instead
of copied adapter code. The mapping language is deliberately
non-Turing-complete under decision #68: this module compiles a closed operation
set into SQL and refuses anything else. It cannot run caller-supplied SQL or
Python, reach the network, read an undeclared path, or drop a row without a
reason code.

A retailer whose semantics cannot be expressed here needs a bounded custom
adapter, not a wider mapping language.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Final, Mapping

from retail_contracts.money_sql import exact_minor_sql, invalid_minor_sql
from retail_ingestion.readers.catalog import sql_identifier, sql_string

from .base import AdapterContext, SourceAdapter
from .registry import register_adapter

MAPPING_SCHEMA_VERSION: Final[str] = "retail-mapped-files/v1"

#: Decision #68 allowlist. Compiling anything outside this set is a hard error.
ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "select",
        "constant",
        "value_map",
        "parse_decimal",
        "parse_integer",
        "parse_date",
        "parse_timestamp",
        "money_major_to_minor",
        # Normalises a major-unit money column's physical type without touching
        # its scale. Needed because staging-v2 money fields are declared in MAJOR
        # units and the canonical transforms convert them; an adapter that also
        # converted would multiply twice.
        "money_major_normalize",
        "quantity",
        "compose_key",
    }
)

KNOWN_AS_OF_MODES: Final[frozenset[str]] = frozenset({"column", "landing_time"})
EVIDENCE_GRADES: Final[frozenset[str]] = frozenset(
    {
        "native_observed",
        "native_processed",
        "native_posted_available",
        "native_extracted",
        "landing_backfill",
    }
)
QUARANTINE_TABLE: Final[str] = "stage_data.adapter_quarantine"


class MappedFilesError(RuntimeError):
    """A declared mapping is not expressible under decision #68."""


@dataclass(frozen=True)
class MappingFingerprint:
    """Identity of the approved mapping, carried into staging lineage."""

    mapping_version: str
    sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MappedFilesError(message)


def _safe_logical_path(value: str) -> str:
    """Reject anything that could escape the declared landing root."""

    _require(bool(value), "logicalPath must not be empty")
    _require(not value.startswith("/"), f"absolute logicalPath rejected: {value}")
    _require("\\" not in value, f"backslash in logicalPath rejected: {value}")
    parts = PurePosixPath(value).parts
    _require(
        all(part not in {"..", "."} for part in parts),
        f"relative traversal in logicalPath rejected: {value}",
    )
    return value


def _identifier(value: str, *, label: str) -> str:
    """Only plain source field names may reach compiled SQL."""

    _require(
        value.replace("_", "").isalnum() and not value[:1].isdigit(),
        f"{label} must be a plain field name, got {value!r}",
    )
    return value


def mapping_fingerprint(mapping: Mapping[str, Any]) -> MappingFingerprint:
    """Fingerprint the approved mapping, excluding prose."""

    payload = {
        key: value
        for key, value in mapping.items()
        if key not in {"description"}
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return MappingFingerprint(
        mapping_version=str(mapping["mappingVersion"]),
        sha256=digest,
    )


def _compile_field(field: Mapping[str, Any], dataset: Mapping[str, Any]) -> str:
    """Compile one allowlisted operation into a SQL expression."""

    operation = field.get("operation")
    _require(
        operation in ALLOWED_OPERATIONS,
        f"operation {operation!r} is outside the decision-#68 allowlist",
    )
    target = _identifier(str(field["target"]), label="target")

    if operation == "constant":
        _require("value" in field, f"{target}: constant requires a value")
        value = field["value"]
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "TRUE" if value else "FALSE"
        if isinstance(value, (int, float)):
            return repr(value)
        return sql_string(str(value))

    if operation == "compose_key":
        sources = field.get("sources") or []
        _require(len(sources) >= 2, f"{target}: compose_key needs two sources")
        separator = str(field.get("separator", ""))
        parts = ", ".join(
            f"{_identifier(str(source), label=target)}::VARCHAR"
            for source in sources
        )
        return f"concat_ws({sql_string(separator)}, {parts})"

    source = field.get("source")
    _require(bool(source), f"{target}: {operation} requires a source field")
    column = _identifier(str(source), label=target)

    if operation == "select":
        return f"{column}::VARCHAR"
    if operation == "parse_integer":
        return f"try_cast({column} AS BIGINT)"
    if operation == "parse_decimal":
        return f"try_cast({column} AS DECIMAL(38, 12))"
    if operation == "parse_date":
        pattern = field.get("format")
        _require(bool(pattern), f"{target}: parse_date requires an explicit format")
        # The declared format governs *text* input. A physical reader may already
        # have recognised the column as a DATE, in which case its VARCHAR form is
        # ISO and would not match the client's pattern; accept that rather than
        # emitting NULL for a value the reader parsed correctly.
        return (
            f"coalesce("
            f"try_strptime({column}::VARCHAR, {sql_string(str(pattern))})::DATE, "
            f"try_cast({column} AS DATE))"
        )
    if operation == "parse_timestamp":
        pattern = field.get("format")
        _require(
            bool(pattern), f"{target}: parse_timestamp requires an explicit format"
        )
        timezone = str(dataset["timezone"])
        return (
            f"timezone({sql_string(timezone)}, coalesce("
            f"try_strptime({column}::VARCHAR, {sql_string(str(pattern))}), "
            f"try_cast({column} AS TIMESTAMP)))"
        )
    if operation == "quantity":
        scale = int(field.get("scale", 0))
        _require(0 <= scale <= 6, f"{target}: quantity scale must be 0..6")
        return f"round(try_cast({column} AS DECIMAL(38, 12)), {scale})"
    if operation == "money_major_normalize":
        # Physical readers type money as text or numeric depending on the drop
        # format. Normalise the type and leave the scale alone.
        return f"try_cast({column} AS DECIMAL(38, 12))"
    if operation == "money_major_to_minor":
        currency = field.get("currencyColumn")
        if currency:
            currency_sql = _identifier(str(currency), label=target)
        else:
            code = field.get("currencyCode")
            _require(
                bool(code),
                f"{target}: money needs a currencyColumn or currencyCode",
            )
            currency_sql = sql_string(str(code))
        # Physical readers type a money column as text or numeric depending on
        # the drop format. Normalize first so the same mapping works across all
        # four formats.
        return exact_minor_sql(
            f"try_cast({column} AS DECIMAL(38, 12))",
            currency_sql,
        )
    if operation == "value_map":
        mapping = field.get("map")
        _require(isinstance(mapping, dict) and mapping, f"{target}: empty value_map")
        branches = " ".join(
            f"WHEN {column}::VARCHAR = {sql_string(str(key))} THEN "
            + ("NULL" if value is None else sql_string(str(value)))
            for key, value in sorted(mapping.items())
        )
        # No ELSE branch: an unmapped value becomes NULL and is quarantined as
        # UNKNOWN_ENUM_VALUE rather than silently defaulting.
        return f"CASE {branches} END"

    raise MappedFilesError(f"unreachable operation {operation!r}")


def _money_guard(dataset: Mapping[str, Any]) -> str | None:
    """Return a predicate matching rows whose money precision is invalid."""

    # Both money operations need this. Whether a value's scale is converted or
    # merely normalised, a sub-minor-unit amount cannot be represented exactly and
    # must be reason-coded rather than rounded. Gating this on the conversion
    # operation alone left every major-unit field unchecked once the conversion was
    # refused on them.
    money_operations = {"money_major_to_minor", "money_major_normalize"}
    checks = []
    for field in dataset["fields"]:
        if field.get("operation") not in money_operations:
            continue
        column = _identifier(str(field["source"]), label="money")
        currency = field.get("currencyColumn")
        currency_sql = (
            _identifier(str(currency), label="money")
            if currency
            else sql_string(str(field["currencyCode"]))
        )
        checks.append(
            invalid_minor_sql(
                f"try_cast({column} AS DECIMAL(38, 12))",
                currency_sql,
            )
        )
    if not checks:
        return None
    return " OR ".join(f"({check})" for check in checks)


def _row_filter_predicate(dataset: Mapping[str, Any]) -> str | None:
    row_filter = dataset.get("rowFilter")
    if not row_filter:
        return None
    column = _identifier(str(row_filter["column"]), label="rowFilter")
    values = ", ".join(sql_string(str(value)) for value in row_filter["values"])
    operator = row_filter["operator"]
    _require(operator in {"in", "not_in"}, f"unsupported rowFilter {operator!r}")
    return (
        f"{column}::VARCHAR NOT IN ({values})"
        if operator == "in"
        else f"{column}::VARCHAR IN ({values})"
    )


def validate_mapping(mapping: Mapping[str, Any], roles: Mapping[str, Any]) -> None:
    """Fail closed before any SQL is compiled."""

    _require(
        mapping.get("schemaVersion") == MAPPING_SCHEMA_VERSION,
        f"unsupported mapping schema {mapping.get('schemaVersion')!r}",
    )
    datasets = mapping.get("datasets") or []
    _require(bool(datasets), "a mapping must declare at least one dataset")
    seen: set[tuple[str, str]] = set()
    for dataset in datasets:
        dataset_id = str(dataset["datasetId"])
        role = str(dataset["role"])
        _require(role in roles, f"{dataset_id}: unknown role {role!r}")
        key = (role, dataset_id)
        _require(key not in seen, f"duplicate dataset {dataset_id} for role {role}")
        seen.add(key)
        _safe_logical_path(str(dataset["logicalPath"]))
        _require(
            dataset["format"] in {"csv", "parquet", "jsonl", "json"},
            f"{dataset_id}: unsupported format {dataset['format']!r}",
        )
        _require(
            dataset["nullPolicy"]["onMissingRequired"] == "quarantine",
            f"{dataset_id}: a missing required field must quarantine",
        )
        evidence = dataset["temporalEvidence"]
        _require(
            evidence["knownAsOf"]["mode"] in KNOWN_AS_OF_MODES,
            f"{dataset_id}: unsupported knownAsOf mode",
        )
        _require(
            evidence["grade"] in EVIDENCE_GRADES,
            f"{dataset_id}: unsupported evidence grade {evidence['grade']!r}",
        )
        if evidence["knownAsOf"]["mode"] == "column":
            _require(
                bool(evidence["knownAsOf"].get("column")),
                f"{dataset_id}: column mode needs a column",
            )
        else:
            _require(
                evidence["grade"] == "landing_backfill",
                f"{dataset_id}: landing_time evidence must declare "
                "landing_backfill and accept the capability downgrade",
            )
        declared = {str(field["target"]) for field in dataset["fields"]}
        required = set(roles[role].get("requiredFields") or [])
        missing = sorted(required - declared)
        _require(
            not missing,
            f"{dataset_id}: role {role} requires {missing}",
        )
        # staging-v2 declares its money fields in MAJOR units, and the canonical
        # transforms convert major to minor. An adapter that converted as well
        # would land minor units in a column the contract says holds major, and
        # the transform would multiply again -- a silent 100x on any two-decimal
        # currency. The scale conversion is therefore refused on those targets;
        # money_major_normalize is the type-only operation they may use.
        major_money = {str(name) for name in (roles[role].get("money") or [])}
        for field in dataset["fields"]:
            _require(
                field.get("operation") in ALLOWED_OPERATIONS,
                f"{dataset_id}: operation {field.get('operation')!r} is not allowed",
            )
            target = str(field.get("target", ""))
            _require(
                not (
                    field.get("operation") == "money_major_to_minor"
                    and target in major_money
                ),
                f"{dataset_id}: {target} is a major-unit money field; "
                "money_major_to_minor would be converted a second time by the "
                "canonical transforms. Use money_major_normalize.",
            )
        if dataset.get("rowFilter"):
            _require(
                bool(dataset["rowFilter"].get("reasonCode")),
                f"{dataset_id}: a rowFilter must carry a reason code",
            )
    _enforce_provider_resolution(datasets, roles)


def _enforce_provider_resolution(
    datasets: Sequence[Mapping[str, Any]],
    roles: Mapping[str, Any],
) -> None:
    """Apply each role's declared providerResolution instead of last-write-wins.

    The materialiser writes ``CREATE OR REPLACE TABLE stage_data.<role>`` once per
    dataset, so two datasets on one role silently discarded the first. staging-v2
    declares how a role with several providers must behave, and none of the four
    modes is "the last one wins".

    ``exclusive`` is enforced here. ``union``, ``cross_validate`` and ``fallback``
    need real merge semantics -- disjoint-partition checks, a reconciliation pass,
    a precedence order with reason codes -- and this adapter implements none of
    them, so a mapping that needs one fails closed rather than producing a table
    that looks merged and is not.
    """

    by_role: dict[str, list[str]] = {}
    for dataset in datasets:
        by_role.setdefault(str(dataset["role"]), []).append(str(dataset["datasetId"]))
    for role, dataset_ids in sorted(by_role.items()):
        if len(dataset_ids) < 2:
            continue
        resolution = str(roles.get(role, {}).get("providerResolution") or "exclusive")
        if resolution == "exclusive":
            _require(
                False,
                f"role {role} declares providerResolution exclusive but "
                f"{len(dataset_ids)} datasets supply it: {sorted(dataset_ids)}",
            )
        _require(
            False,
            f"role {role} declares providerResolution {resolution!r} for "
            f"{sorted(dataset_ids)}; this adapter does not implement multi-provider "
            "merge semantics and will not silently keep only the last provider",
        )


def dry_run_report(
    mapping: Mapping[str, Any],
    roles: Mapping[str, Any],
) -> dict[str, Any]:
    """Describe what a mapping would do before any ingestion runs."""

    validate_mapping(mapping, roles)
    fingerprint = mapping_fingerprint(mapping)
    datasets = []
    for dataset in mapping["datasets"]:
        operations = sorted({str(f["operation"]) for f in dataset["fields"]})
        datasets.append(
            {
                "datasetId": str(dataset["datasetId"]),
                "role": str(dataset["role"]),
                "format": str(dataset["format"]),
                "logicalPath": str(dataset["logicalPath"]),
                "fieldCount": len(dataset["fields"]),
                "operations": operations,
                "evidenceGrade": dataset["temporalEvidence"]["grade"],
                "knownAsOfMode": dataset["temporalEvidence"]["knownAsOf"]["mode"],
                "rowFilterReasonCode": (
                    dataset.get("rowFilter", {}).get("reasonCode")
                ),
                "capabilityDowngrade": (
                    dataset["temporalEvidence"]["grade"] == "landing_backfill"
                ),
            }
        )
    return {
        "schemaVersion": "retail-mapped-files-dry-run/v1",
        "sourceSystem": str(mapping["sourceSystem"]),
        "mappingVersion": fingerprint.mapping_version,
        "mappingSha256": fingerprint.sha256,
        "datasets": datasets,
    }


@register_adapter
class MappedFilesAdapter(SourceAdapter):
    """Compile a declared mapping into standardized role relations."""

    source_system = "mapped_files"
    adapter_version = "mapped-files-adapter/1.0.0"
    raw_schema = "raw_mapped_files"

    def materialize_staging(self, context: AdapterContext) -> tuple[str, ...]:
        profile = context.profile
        mapping = profile.get("mappedFiles")
        _require(
            isinstance(mapping, dict),
            "the mapped_files adapter requires a `mappedFiles` mapping in the "
            "source profile",
        )
        roles = profile.get("roleCatalog") or {}
        validate_mapping(mapping, roles)
        fingerprint = mapping_fingerprint(mapping)

        con = context.connection
        con.execute("CREATE SCHEMA IF NOT EXISTS stage_data")
        landing = context.landing
        snapshot_id = landing["sourceSnapshotId"]
        native_snapshot_id = landing.get("nativeSnapshotId")
        landing_time = landing.get("landingTime")
        source_schema_version = profile["sourceSchemaVersion"]
        profile_version = profile["profileVersion"]

        created: list[str] = []
        for dataset in mapping["datasets"]:
            role = str(dataset["role"])
            dataset_id = str(dataset["datasetId"])
            view = f"{self.raw_schema}.{dataset_id.replace('-', '_')}"
            evidence = dataset["temporalEvidence"]
            if evidence["knownAsOf"]["mode"] == "column":
                known_as_of = (
                    "timezone("
                    f"{sql_string(str(dataset['timezone']))}, "
                    "try_cast("
                    f"{_identifier(str(evidence['knownAsOf']['column']), label='knownAsOf')}"
                    " AS TIMESTAMP))"
                )
            else:
                known_as_of = f"try_cast({sql_string(str(landing_time))} AS TIMESTAMPTZ)"

            projections = [
                # The mapping's declared dialect, not the adapter's own name. The
                # role contract asks for the exact source identity, and writing
                # "mapped_files" for every client would erase which retailer a row
                # came from -- the one thing provenance exists to preserve.
                f"{sql_string(str(mapping['sourceSystem']))}::VARCHAR "
                "AS source_system",
                "_source_instance AS source_instance",
                f"{sql_string(str(source_schema_version))}::VARCHAR "
                "AS source_schema_version",
                f"{sql_string(str(snapshot_id))}::VARCHAR AS source_snapshot_id",
                f"{sql_string(str(native_snapshot_id or ''))}::VARCHAR "
                "AS native_snapshot_id",
                "_market_id AS market_id",
                f"{known_as_of} AS known_as_of",
                f"{sql_string(str(evidence['grade']))}::VARCHAR AS evidence_grade",
                "'client'::VARCHAR AS evidence_class",
                "'native'::VARCHAR AS derivation_class",
                "_raw_object_hash AS raw_object_hash",
                f"{sql_string(str(profile_version))}::VARCHAR AS profile_version",
                f"{sql_string(self.adapter_version)}::VARCHAR AS adapter_version",
                f"{sql_string(role)}::VARCHAR AS role_id",
                # Required by staging-v2 and previously omitted, so a consumer
                # could not tell which revision of a role shaped the row.
                f"{sql_string(str(roles[role].get('version', '')))}::VARCHAR "
                "AS role_version",
                f"{sql_string(dataset_id)}::VARCHAR AS provider_id",
                f"{sql_string(fingerprint.sha256)}::VARCHAR AS mapping_sha256",
            ]
            key_parts = ", ".join(
                f"{_identifier(str(column), label='sourceKeys')}::VARCHAR"
                for column in dataset["sourceKeys"]
            )
            projections.append(
                f"sha256(concat_ws('|', {key_parts}))::VARCHAR AS native_record_id"
            )
            for field in dataset["fields"]:
                expression = _compile_field(field, dataset)
                alias = _identifier(str(field["target"]), label="target")
                projections.append(f"{expression} AS {alias}")

            rejects: list[str] = []
            money_guard = _money_guard(dataset)
            if money_guard:
                rejects.append(f"CASE WHEN {money_guard} THEN "
                               "'MONEY_PRECISION_INVALID' END")
            for field in dataset["fields"]:
                if field.get("operation") != "value_map":
                    continue
                column = _identifier(str(field["source"]), label="value_map")
                allowed = ", ".join(
                    sql_string(str(key)) for key in sorted(field["map"])
                )
                rejects.append(
                    f"CASE WHEN {column} IS NOT NULL AND "
                    f"{column}::VARCHAR NOT IN ({allowed}) THEN "
                    "'UNKNOWN_ENUM_VALUE' END"
                )
            for column in dataset["sourceKeys"]:
                name = _identifier(str(column), label="sourceKeys")
                rejects.append(
                    f"CASE WHEN {name} IS NULL THEN 'NULL_IN_KEY' END"
                )
            # Validation confirms a required role field is DECLARED. It cannot know
            # whether the value will parse: an invalid date or a non-numeric quantity
            # becomes NULL through try_cast and previously entered the accepted role
            # table with no rejection reason at all. The declared-versus-parsed gap is
            # closed here, on the compiled expression, so the check sees exactly the
            # value the role table would receive.
            required_targets = set(roles[role].get("requiredFields") or [])
            for field in dataset["fields"]:
                target = str(field["target"])
                if target not in required_targets:
                    continue
                expression = _compile_field(field, dataset)
                rejects.append(
                    f"CASE WHEN ({expression}) IS NULL THEN "
                    f"{sql_string('REQUIRED_FIELD_UNPARSABLE:' + target)} END"
                )
            filter_predicate = _row_filter_predicate(dataset)
            if filter_predicate:
                reason = str(dataset["rowFilter"]["reasonCode"])
                rejects.append(
                    f"CASE WHEN {filter_predicate} THEN {sql_string(reason)} END"
                )
            reject_sql = (
                "coalesce(" + ", ".join(rejects) + ")" if rejects else "NULL::VARCHAR"
            )

            projected = ",\n                    ".join(projections)
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.{sql_identifier(role + "_candidate")} AS
                SELECT
                    {projected},
                    {reject_sql} AS _reject_reason
                FROM {view}
                """
            )
            con.execute(
                f"""
                CREATE OR REPLACE TABLE stage_data.{sql_identifier(role)} AS
                SELECT * EXCLUDE (_reject_reason)
                FROM stage_data.{sql_identifier(role + "_candidate")}
                WHERE _reject_reason IS NULL
                """
            )
            created.append(f"stage_data.{role}")
        return tuple(created)


__all__ = [
    "ALLOWED_OPERATIONS",
    "MAPPING_SCHEMA_VERSION",
    "MappedFilesAdapter",
    "MappedFilesError",
    "MappingFingerprint",
    "dry_run_report",
    "mapping_fingerprint",
    "validate_mapping",
]
