"""Materialize verified pricing bundles and adopt one local serving set."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Final, Iterable, Mapping
import uuid

import numpy as np
import pandas as pd
import psycopg
from jsonschema import Draft202012Validator, FormatChecker
from psycopg import sql
from psycopg.types.json import Jsonb

from retail_ml.pricing.bundle import (
    ARTIFACT_SCHEMAS,
    JSON_ARTIFACTS,
    verify_pricing_bundle,
)
from retail_ml.pricing.selection import (
    selection_intent_from_record,
    validate_activation_set,
    validate_selection_record,
)


SERVING_SCHEMA: Final[str] = "retail_serving"
MIGRATION_REVISION: Final[str] = "0031_pricing_margin_pct"
VERIFIER_CONTRACT: Final[str] = "retail-pricing-bundle-verification/v1"


class PricingServingError(RuntimeError):
    """Verified pricing evidence cannot be materialized or activated."""


@dataclass(frozen=True)
class PricingMaterialization:
    bundle_id: str
    semantic_fingerprint: str
    bundle_kind: str
    row_counts: dict[str, int]
    already_materialized: bool


@dataclass(frozen=True)
class PricingActivation:
    activation_event_id: int
    activation_set_id: str
    bundle_id: str
    transaction_id: str
    selection_record_ids: tuple[str, ...]
    already_active: bool


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PricingServingError(message)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if value is pd.NaT:
        return None
    # bool is a subclass of int in Python, so preserve it before numeric
    # normalization or JSON feature flags become 0/1.
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, np.ndarray):
        return [_value(item) for item in value]
    if isinstance(value, (datetime, date, str, list, dict)):
        return value
    return value.item() if hasattr(value, "item") else value


def _json_value(value: Any) -> Any:
    converted = _value(value)
    if isinstance(converted, (datetime, date)):
        return converted.isoformat()
    if isinstance(converted, Mapping):
        return {str(key): _json_value(item) for key, item in converted.items()}
    if isinstance(converted, (list, tuple)):
        return [_json_value(item) for item in converted]
    return converted


def _details(row: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _json_value(value) for key, value in row.items()}


def _matches_prebound_intent(
    records: list[dict[str, Any]], prospective: Any
) -> bool:
    return (
        isinstance(prospective, list)
        and len(prospective) == 1
        and selection_intent_from_record(records[0]) == prospective[0]
        and all(
            selection_intent_from_record(record) == prospective[0]
            for record in records
        )
    )


def _field(row: Mapping[str, Any], name: str, default: Any = None) -> Any:
    return _value(row.get(name, default))


def _integer_field(row: Mapping[str, Any], name: str) -> int | None:
    """Preserve nullable Parquet integer columns through pandas row conversion."""

    value = _field(row, name)
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except Exception as exc:  # pragma: no cover - defensive type boundary
        raise PricingServingError(f"{name} is not an integer") from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise PricingServingError(f"{name} is not an integer")
    return int(number)


def _require_schema(cursor: psycopg.Cursor[Any]) -> None:
    try:
        cursor.execute("SELECT version_num FROM retail_intelligence_alembic_version")
        row = cursor.fetchone()
    except psycopg.Error as exc:
        raise PricingServingError(
            "PostgreSQL serving migrations are absent; run tools/dev.py db-upgrade"
        ) from exc
    _require(
        row is not None and row[0] == MIGRATION_REVISION,
        f"PostgreSQL serving schema must be at {MIGRATION_REVISION}",
    )


def _copy(
    cursor: psycopg.Cursor[Any],
    table: str,
    columns: tuple[str, ...],
    rows: Iterable[tuple[Any, ...]],
) -> None:
    statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(SERVING_SCHEMA),
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    with cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _load_verified(
    bundle_path: str | Path, verification_record_path: str | Path
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, pd.DataFrame]]:
    root = Path(bundle_path).resolve()
    independent = verify_pricing_bundle(root)
    record_path = Path(verification_record_path).resolve()
    _require(record_path.is_file(), "independent pricing verification record is absent")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    _require(record == independent, "verification record differs from recomputed verification")
    manifest_path = root / "pricing-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require(
        independent["manifestSha256"] == _sha256_file(manifest_path),
        "manifest changed after verification",
    )
    frames = {
        name: pd.read_parquet(root / manifest["artifacts"][name]["path"])
        for name in ARTIFACT_SCHEMAS
        if name not in JSON_ARTIFACTS
    }
    return root, manifest, record, frames


def _existing(
    cursor: psycopg.Cursor[Any],
    manifest: Mapping[str, Any],
    row_counts: dict[str, int],
    *,
    manifest_sha256: str,
    verifier_record_sha256: str,
) -> PricingMaterialization | None:
    cursor.execute(
        f"""
        SELECT bundle_kind, manifest_sha256, semantic_fingerprint,
               source_publication_fingerprint, source_run_id, input_authority_id,
               verifier_contract, verifier_record_sha256,
               prospective_result_selections
        FROM {SERVING_SCHEMA}.pricing_materializations
        WHERE bundle_id = %s
        """,
        (manifest["bundleId"],),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    lineage = manifest["lineage"]
    _require(
        row[0] == manifest["bundleKind"]
        and row[1] == manifest_sha256
        and row[2] == manifest["semanticFingerprint"]
        and row[3] == lineage["publicationSemanticFingerprint"]
        and row[4] == lineage["sourceRunId"]
        and row[5] == lineage["inputAuthorityId"]
        and row[6] == VERIFIER_CONTRACT
        and row[7] == verifier_record_sha256
        and row[8] == manifest["prospectiveResultSelections"],
        "existing pricing materialization disagrees with the verified bundle",
    )
    table_by_artifact = {
        "response_assessments": "pricing_response_assessments",
        "price_candidates": "pricing_price_candidates",
        "price_recommendations": "price_recommendations",
        "competitor_assessments": "pricing_competitor_assessments",
        "promotion_protection": "pricing_promotion_protection",
    }
    for artifact, table in table_by_artifact.items():
        cursor.execute(
            sql.SQL("SELECT count(*) FROM {}.{} WHERE bundle_id = %s").format(
                sql.Identifier(SERVING_SCHEMA), sql.Identifier(table)
            ),
            (manifest["bundleId"],),
        )
        counted = cursor.fetchone()
        _require(
            counted is not None and int(counted[0]) == row_counts[artifact],
            f"existing {table} row count differs from the verified artifact",
        )
    return PricingMaterialization(
        bundle_id=str(manifest["bundleId"]),
        semantic_fingerprint=str(manifest["semanticFingerprint"]),
        bundle_kind=str(manifest["bundleKind"]),
        row_counts=row_counts,
        already_materialized=True,
    )


def materialize_pricing_bundle(
    bundle_path: str | Path,
    verification_record_path: str | Path,
    *,
    postgres_dsn: str,
) -> PricingMaterialization:
    """Load one independently verified bundle without activating it."""

    root, manifest, verification, frames = _load_verified(
        bundle_path, verification_record_path
    )
    row_counts = {
        name: int(manifest["artifacts"][name]["rowCount"])
        for name in ARTIFACT_SCHEMAS
    }
    lineage = manifest.get("lineage") or {}
    verifier_record_sha256 = _sha256_file(Path(verification_record_path).resolve())
    for field in (
        "publicationSemanticFingerprint", "sourceRunId", "inputAuthorityId"
    ):
        _require(bool(lineage.get(field)), f"pricing lineage lacks {field}")
    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (str(manifest["bundleId"]),),
                )
                existing = _existing(
                    cursor,
                    manifest,
                    row_counts,
                    manifest_sha256=str(verification["manifestSha256"]),
                    verifier_record_sha256=verifier_record_sha256,
                )
                if existing is not None:
                    return existing
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.pricing_materializations (
                        bundle_id, bundle_kind, manifest_sha256,
                        semantic_fingerprint, decision_as_of,
                        source_publication_fingerprint, source_run_id,
                        input_authority_id, verifier_contract,
                        verifier_record_sha256, capabilities, artifact_inventory,
                        prospective_result_selections
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        manifest["bundleId"], manifest["bundleKind"],
                        verification["manifestSha256"],
                        manifest["semanticFingerprint"], manifest["decisionAsOf"],
                        lineage["publicationSemanticFingerprint"],
                        lineage["sourceRunId"], lineage["inputAuthorityId"],
                        VERIFIER_CONTRACT,
                        verifier_record_sha256,
                        Jsonb(manifest["capabilities"]),
                        Jsonb(manifest["artifacts"]),
                        Jsonb(manifest["prospectiveResultSelections"]),
                    ),
                )
                bundle_id = str(manifest["bundleId"])

                response_rows = frames["response_assessments"].to_dict("records")
                _copy(
                    cursor, "pricing_response_assessments",
                    (
                        "bundle_id", "market_id", "sku_id", "store_id",
                        "channel_id", "disposition", "first_failure_reason",
                        "current_price_minor", "currency_code", "shrunk_beta",
                        "confidence", "support_min_minor", "support_max_minor",
                        "assessment",
                    ),
                    (
                        (
                            bundle_id, _field(row, "market_id"), _field(row, "sku_id"),
                            _field(row, "store_id"), _field(row, "channel_id"),
                            _field(row, "disposition"), _field(row, "first_failure_reason"),
                            _integer_field(row, "current_price_minor"), _field(row, "currency_code"),
                            _field(row, "shrunk_beta"), _field(row, "confidence"),
                            _integer_field(row, "support_min_minor"),
                            _integer_field(row, "support_max_minor"),
                            Jsonb(_details(row)),
                        )
                        for row in response_rows
                    ),
                )

                candidate_rows = frames["price_candidates"].to_dict("records")
                _copy(
                    cursor, "pricing_price_candidates",
                    (
                        "bundle_id", "market_id", "sku_id", "store_id",
                        "channel_id", "candidate_price_minor", "expected_units",
                        "expected_revenue_minor", "eligible", "rejection_reason",
                        "details",
                    ),
                    (
                        (
                            bundle_id, _field(row, "market_id"), _field(row, "sku_id"),
                            _field(row, "store_id"), _field(row, "channel_id"),
                            _integer_field(row, "candidate_price_minor"),
                            _field(row, "expected_units"),
                            _integer_field(row, "expected_revenue_minor"),
                            _field(row, "eligible"),
                            _field(row, "rejection_reason"), Jsonb(_details(row)),
                        )
                        for row in candidate_rows
                    ),
                )

                recommendation_rows = frames["price_recommendations"].to_dict("records")
                _copy(
                    cursor, "price_recommendations",
                    (
                        "bundle_id", "recommendation_id", "market_id", "sku_id",
                        "store_id", "channel_id", "record_kind", "selectable",
                        "action", "disposition", "first_failure_reason",
                        "current_price_minor", "proposed_price_minor", "currency_code",
                        "expected_units_current", "expected_units_proposed",
                        "revenue_impact_minor", "margin_impact_minor", "margin_reason_code",
                        "current_margin_pct", "expected_margin_pct",
                        "confidence", "priority", "risk", "stock_cover_days",
                        "competitor_price_minor", "details",
                    ),
                    (
                        (
                            bundle_id, _field(row, "recommendation_id"),
                            _field(row, "market_id"), _field(row, "sku_id"),
                            _field(row, "store_id"), _field(row, "channel_id"),
                            _field(row, "record_kind"), _field(row, "selectable"),
                            _field(row, "action"), _field(row, "disposition"),
                            _field(row, "first_failure_reason"),
                            _integer_field(row, "current_price_minor"),
                            _integer_field(row, "proposed_price_minor"),
                            _field(row, "currency_code"),
                            _field(row, "expected_units_current"),
                            _field(row, "expected_units_proposed"),
                            _integer_field(row, "revenue_impact_minor"),
                            _integer_field(row, "margin_impact_minor"),
                            _field(row, "margin_reason_code"),
                            _field(row, "current_margin_pct"),
                            _field(row, "expected_margin_pct"),
                            _field(row, "confidence"), _field(row, "priority", "Unassigned"),
                            _field(row, "risk", "Unavailable"),
                            _field(row, "stock_cover_days"),
                            _integer_field(row, "competitor_price_minor"),
                            Jsonb(_details(row)),
                        )
                        for row in recommendation_rows
                    ),
                )

                competitor_rows = frames["competitor_assessments"].to_dict("records")
                _copy(
                    cursor, "pricing_competitor_assessments",
                    (
                        "bundle_id", "match_id", "market_id", "sku_id",
                        "competitor_id", "competitor_product_id", "geo_scope_type",
                        "geo_scope_id", "observed_at", "known_as_of", "price_minor",
                        "currency_code", "availability_state", "match_confidence",
                        "match_status", "freshness", "bound_eligible",
                        "first_exclusion_reason", "details",
                    ),
                    (
                        (
                            bundle_id, _field(row, "match_id"), _field(row, "market_id"),
                            _field(row, "sku_id"), _field(row, "comp_id"),
                            _field(row, "comp_product_id"), _field(row, "geo_scope_type"),
                            _field(row, "geo_scope_id") or "__market__",
                            _field(row, "observed_at"), _field(row, "known_as_of"),
                            _integer_field(row, "price_minor"),
                            _field(row, "currency_code"),
                            _field(row, "availability_state"),
                            _field(row, "match_confidence"), _field(row, "match_status"),
                            _field(row, "freshness"), _field(row, "bound_eligible"),
                            _field(row, "first_exclusion_reason"), Jsonb(_details(row)),
                        )
                        for row in competitor_rows
                    ),
                )

                promotion_rows = frames["promotion_protection"].to_dict("records")
                _copy(
                    cursor, "pricing_promotion_protection",
                    (
                        "bundle_id", "market_id", "sku_id", "store_id",
                        "channel_id", "guard_status", "first_failure_reason",
                        "selected_precedence", "applicable_promotion_ids", "details",
                    ),
                    (
                        (
                            bundle_id, _field(row, "market_id"), _field(row, "sku_id"),
                            _field(row, "store_id"), _field(row, "channel_id"),
                            _field(row, "guard_status"), _field(row, "first_failure_reason"),
                            _field(row, "selected_precedence"),
                            Jsonb(json.loads(_field(row, "applicable_promotion_ids", "[]"))),
                            Jsonb(_details(row)),
                        )
                        for row in promotion_rows
                    ),
                )

                disposition = json.loads(
                    (root / manifest["artifacts"]["promotion_disposition"]["path"])
                    .read_text(encoding="utf-8")
                )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.pricing_promotion_dispositions (
                        bundle_id, decision_id, decision_disposition,
                        package_disposition, planner_available,
                        first_failure_reason, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        bundle_id, disposition["decisionId"],
                        disposition["decisionDisposition"],
                        disposition["packageDisposition"],
                        disposition["plannerAvailable"],
                        disposition["firstFailureReason"], Jsonb(disposition),
                    ),
                )
                for table in (
                    "pricing_response_assessments", "pricing_price_candidates",
                    "price_recommendations", "pricing_competitor_assessments",
                    "pricing_promotion_protection",
                ):
                    cursor.execute(
                        sql.SQL("ANALYZE {}.{}").format(
                            sql.Identifier(SERVING_SCHEMA), sql.Identifier(table)
                        )
                    )
    except PricingServingError:
        raise
    except (psycopg.Error, KeyError, TypeError, ValueError) as exc:
        raise PricingServingError(f"pricing materialization failed: {exc}") from exc
    return PricingMaterialization(
        bundle_id=str(manifest["bundleId"]),
        semantic_fingerprint=str(manifest["semanticFingerprint"]),
        bundle_kind=str(manifest["bundleKind"]),
        row_counts=row_counts,
        already_materialized=False,
    )


def activate_pricing_bundle(
    *,
    postgres_dsn: str,
    selection_record_paths: list[str | Path],
    activation_set_path: str | Path,
    selection_schema_path: str | Path,
    activation_schema_path: str | Path,
    actor: str,
) -> PricingActivation:
    """Adopt approved selection bytes and one rich activation atomically."""

    _require(bool(actor.strip()), "pricing activation actor is required")
    selection_records = [
        validate_selection_record(
            json.loads(Path(path).read_text(encoding="utf-8")), selection_schema_path
        )
        for path in selection_record_paths
    ]
    lifecycle_order = {"candidate": 0, "approved": 1, "active": 2}
    _require(
        len(selection_records) == 3
        and {record["state"] for record in selection_records} == set(lifecycle_order),
        "activation requires exactly candidate, approved, and active selection records",
    )
    selection_records.sort(key=lambda record: lifecycle_order[record["state"]])
    _require(
        len({record["selectionId"] for record in selection_records}) == 1,
        "selection lifecycle records must share one stable scope identity",
    )
    _require(
        selection_records[1]["predecessorRecordId"]
        == selection_records[0]["recordId"]
        and selection_records[2]["predecessorRecordId"]
        == selection_records[1]["recordId"],
        "selection lifecycle predecessor record IDs are not candidate → approved → active",
    )
    activation = validate_activation_set(
        json.loads(Path(activation_set_path).read_text(encoding="utf-8")),
        activation_schema_path,
    )
    record_hashes = {
        str(record["recordId"]): _canonical_sha256(record)
        for record in selection_records
    }
    activation_sha256 = _canonical_sha256(activation)
    transaction_id = str(uuid.uuid4())
    active_records = [record for record in selection_records if record["state"] == "active"]
    _require(active_records, "activation requires at least one active selection record")
    _require(
        sorted(record["selectionId"] for record in active_records)
        == activation["activeSelectionIds"],
        "activation selection membership differs from the approved records",
    )
    _require(
        all(record["bundleId"] == activation["bundleId"] for record in selection_records),
        "selection records do not share the activation bundle",
    )
    _require(
        all(
            record["bundleSemanticFingerprint"]
            == activation["bundleSemanticFingerprint"]
            and record["retailerId"] == activation["retailerId"]
            and record["tenantId"] == activation["tenantId"]
            and record["environment"] == activation["environment"]
            and record["audience"] == activation["audience"]
            for record in selection_records
        ),
        "selection lifecycle scope or bundle fingerprint differs from activation",
    )
    scope = (
        activation["retailerId"], activation["tenantId"], activation["environment"]
    )
    try:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("|".join(scope),),
                )
                cursor.execute(
                    f"""
                    SELECT activation.activation_event_id,
                           activation.activation_set_id, activation.bundle_id,
                           activation.transaction_id, activation.selection_ids,
                           activation.evidence, activation.activation_set_sha256
                    FROM {SERVING_SCHEMA}.pricing_active_state AS state
                    JOIN {SERVING_SCHEMA}.pricing_activation_sets AS activation
                      USING (activation_event_id)
                    WHERE state.retailer_id = %s AND state.tenant_id = %s
                      AND state.environment = %s
                    FOR UPDATE OF state
                    """,
                    scope,
                )
                predecessor = cursor.fetchone()
                if predecessor is not None and predecessor[1] == activation["activationSetId"]:
                    _require(
                        predecessor[2] == activation["bundleId"]
                        and predecessor[4] == activation["activeSelectionIds"]
                        and predecessor[5] == activation
                        and predecessor[6] == activation_sha256,
                        "existing activation set identity points at a different bundle",
                    )
                    cursor.execute(
                        f"""
                        SELECT record_id, record_sha256, review_evidence,
                               lifecycle_status, predecessor_event_id, event_id
                        FROM {SERVING_SCHEMA}.pricing_result_selection_events
                        WHERE transaction_id = %s
                        ORDER BY event_id
                        """,
                        (predecessor[3],),
                    )
                    existing_records = cursor.fetchall()
                    _require(
                        len(existing_records) == 3
                        and [row[0] for row in existing_records]
                        == [record["recordId"] for record in selection_records]
                        and [row[1] for row in existing_records]
                        == [record_hashes[record["recordId"]] for record in selection_records]
                        and [row[2] for row in existing_records] == selection_records
                        and [row[3] for row in existing_records]
                        == ["candidate", "approved", "active"]
                        and existing_records[1][4] == existing_records[0][5]
                        and existing_records[2][4] == existing_records[1][5],
                        "existing activation lifecycle differs from approved immutable bytes",
                    )
                    cursor.execute(
                        f"""
                        SELECT prospective_result_selections
                        FROM {SERVING_SCHEMA}.pricing_materializations
                        WHERE bundle_id = %s
                        """,
                        (activation["bundleId"],),
                    )
                    existing_materialization = cursor.fetchone()
                    _require(
                        existing_materialization is not None
                        and _matches_prebound_intent(
                            selection_records, existing_materialization[0]
                        ),
                        "existing activation differs from its prebound intent",
                    )
                    return PricingActivation(
                        activation_event_id=int(predecessor[0]),
                        activation_set_id=str(predecessor[1]),
                        bundle_id=str(predecessor[2]),
                        transaction_id=str(predecessor[3]),
                        selection_record_ids=tuple(
                            str(record["recordId"]) for record in selection_records
                        ),
                        already_active=True,
                    )
                expected_predecessor = activation["predecessorActivationSetId"]
                actual_predecessor = None if predecessor is None else predecessor[1]
                _require(
                    expected_predecessor == actual_predecessor,
                    "activation predecessor changed after review",
                )
                previous_selection_event: int | None = None
                previous_selection_record_id: str | None = None
                if predecessor is not None:
                    cursor.execute(
                        f"""
                        SELECT event_id, record_id
                        FROM {SERVING_SCHEMA}.pricing_result_selection_events
                        WHERE retailer_id = %s AND tenant_id = %s
                          AND environment = %s AND capability = 'price_revenue'
                          AND lifecycle_status = 'active'
                          AND selection_id = ANY(%s) AND bundle_id = %s
                        ORDER BY event_id DESC
                        FOR UPDATE
                        """,
                        (*scope, predecessor[4], predecessor[2]),
                    )
                    previous_selections = cursor.fetchall()
                    _require(
                        len(previous_selections) == 1,
                        "active pricing set does not have exactly one price_revenue predecessor",
                    )
                    previous_selection = previous_selections[0]
                    previous_selection_event = int(previous_selection[0])
                    previous_selection_record_id = str(previous_selection[1])
                _require(
                    selection_records[0]["predecessorRecordId"]
                    == previous_selection_record_id,
                    "selection predecessor changed after review",
                )
                cursor.execute(
                    f"""
                    SELECT bundle_kind, semantic_fingerprint,
                           prospective_result_selections
                    FROM {SERVING_SCHEMA}.pricing_materializations
                    WHERE bundle_id = %s
                    """,
                    (activation["bundleId"],),
                )
                materialization = cursor.fetchone()
                _require(
                    materialization is not None
                    and materialization[0] == "response_rich"
                    and materialization[1] == activation["bundleSemanticFingerprint"],
                    "only the verified response-rich materialization can activate",
                )
                _require(
                    _matches_prebound_intent(selection_records, materialization[2]),
                    "selection lifecycle differs from the prebound materialized intent",
                )
                prior_selection_event: int | None = previous_selection_event
                for record in selection_records:
                    cursor.execute(
                        f"""
                        SELECT event_id, bundle_id, predecessor_event_id,
                               review_evidence, record_sha256, transaction_id
                        FROM {SERVING_SCHEMA}.pricing_result_selection_events
                        WHERE record_id = %s
                        """,
                        (record["recordId"],),
                    )
                    existing = cursor.fetchone()
                    if existing is not None:
                        _require(
                            existing[1] == record["bundleId"]
                            and existing[2] == prior_selection_event
                            and existing[3] == record
                            and existing[4] == record_hashes[record["recordId"]],
                            "existing selection event differs from approved immutable bytes",
                        )
                        prior_selection_event = int(existing[0])
                        transaction_id = str(existing[5])
                        continue
                    cursor.execute(
                        f"""
                        INSERT INTO {SERVING_SCHEMA}.pricing_result_selection_events (
                            selection_id, lifecycle_status, retailer_id, tenant_id,
                            capability, environment, bundle_id, predecessor_event_id,
                            review_actor, review_evidence, recorded_at, record_id,
                            record_sha256, transaction_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  %s, %s, %s)
                        RETURNING event_id
                        """,
                        (
                            record["selectionId"], record["state"], record["retailerId"],
                            record["tenantId"], record["capability"], record["environment"],
                            record["bundleId"], prior_selection_event,
                            record["review"]["actor"], Jsonb(record),
                            record["recordedAt"],
                            record["recordId"], record_hashes[record["recordId"]],
                            transaction_id,
                        ),
                    )
                    inserted = cursor.fetchone()
                    _require(inserted is not None, "selection event insert returned no identity")
                    prior_selection_event = int(inserted[0])
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.pricing_activation_sets (
                        activation_set_id, bundle_id, retailer_id, tenant_id,
                        environment, selection_ids, predecessor_activation_event_id,
                        actor, evidence, activation_set_sha256, transaction_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING activation_event_id
                    """,
                    (
                        activation["activationSetId"], activation["bundleId"],
                        *scope, activation["activeSelectionIds"],
                        None if predecessor is None else predecessor[0], actor,
                        Jsonb(activation), activation_sha256, transaction_id,
                    ),
                )
                inserted = cursor.fetchone()
                _require(inserted is not None, "activation insert returned no identity")
                event_id = int(inserted[0])
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.pricing_active_state (
                        retailer_id, tenant_id, environment, activation_event_id
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (retailer_id, tenant_id, environment)
                    DO UPDATE SET activation_event_id = EXCLUDED.activation_event_id
                    """,
                    (*scope, event_id),
                )
    except PricingServingError:
        raise
    except (psycopg.Error, KeyError, TypeError, ValueError) as exc:
        raise PricingServingError(f"pricing activation failed: {exc}") from exc
    return PricingActivation(
        activation_event_id=event_id,
        activation_set_id=str(activation["activationSetId"]),
        bundle_id=str(activation["bundleId"]),
        transaction_id=transaction_id,
        selection_record_ids=tuple(
            str(record["recordId"]) for record in selection_records
        ),
        already_active=False,
    )


def write_pricing_activation_receipt(
    *,
    postgres_dsn: str,
    activation_set_id: str,
    destination: str | Path,
    schema_path: str | Path,
) -> Path:
    """Export deterministic post-commit evidence; never select serving from it."""

    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT activation.activation_event_id,
                           activation.activation_set_id,
                           activation.activation_set_sha256,
                           activation.transaction_id,
                           activation.bundle_id,
                           activation.retailer_id,
                           activation.tenant_id,
                           activation.environment
                    FROM {SERVING_SCHEMA}.pricing_activation_sets AS activation
                    JOIN {SERVING_SCHEMA}.pricing_active_state AS active
                      ON active.activation_event_id = activation.activation_event_id
                     AND active.retailer_id = activation.retailer_id
                     AND active.tenant_id = activation.tenant_id
                     AND active.environment = activation.environment
                    WHERE activation.activation_set_id = %s
                    """,
                    (activation_set_id,),
                )
                activation = cursor.fetchone()
                _require(activation is not None, "active pricing activation is absent")
                cursor.execute(
                    f"""
                    SELECT event_id, record_id, record_sha256, selection_id,
                           lifecycle_status, predecessor_event_id
                    FROM {SERVING_SCHEMA}.pricing_result_selection_events
                    WHERE transaction_id = %s
                    ORDER BY event_id
                    """,
                    (activation[3],),
                )
                selections = cursor.fetchall()
    except PricingServingError:
        raise
    except psycopg.Error as exc:
        raise PricingServingError(
            f"pricing activation receipt query failed: {exc}"
        ) from exc
    _require(len(selections) == 3, "activation receipt requires three selection events")
    _require(
        [str(row[4]) for row in selections] == ["candidate", "approved", "active"]
        and selections[1][5] == selections[0][0]
        and selections[2][5] == selections[1][0],
        "activation receipt selection lifecycle is not contiguous",
    )
    receipt = {
        "schemaVersion": "retail-pricing-activation-receipt/v1",
        "transactionId": str(activation[3]),
        "activationEventId": int(activation[0]),
        "activationSetId": str(activation[1]),
        "activationSetSha256": str(activation[2]),
        "bundleId": str(activation[4]),
        "retailerId": str(activation[5]),
        "tenantId": str(activation[6]),
        "environment": str(activation[7]),
        "selectionEvents": [
            {
                "eventId": int(row[0]),
                "recordId": str(row[1]),
                "recordSha256": str(row[2]),
                "selectionId": str(row[3]),
                "state": str(row[4]),
                "predecessorEventId": int(row[5]) if row[5] is not None else None,
            }
            for row in selections
        ],
    }
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema, format_checker=FormatChecker()
        ).iter_errors(receipt),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise PricingServingError(
            f"pricing activation receipt schema violation: {errors[0].message}"
        )
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    if target.exists():
        _require(
            target.read_text(encoding="utf-8") == payload,
            "existing activation receipt differs from immutable database evidence",
        )
        return target
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(target)
    return target


__all__ = [
    "PricingActivation", "PricingMaterialization", "PricingServingError",
    "activate_pricing_bundle", "materialize_pricing_bundle",
    "write_pricing_activation_receipt",
]
