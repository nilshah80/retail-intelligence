"""Project a verified inventory bundle into PostgreSQL (P4-8 tasks 7 and 8).

Parquet stays the immutable authority. This module is the only boundary that
opens those artifacts for serving; the Go API reads the resulting projection and
nothing else.

Materialization and activation are separate transactions on purpose. A bundle can
be materialized and still not served -- that is the accepted-but-inactive state
the API answers with a governed 503 -- and activation is a second, append-only
decision with its own actor. Collapsing them would make "loaded" and "authorized"
one act, and there would be no state in which evidence exists but nobody has
taken responsibility for serving it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Any, Final

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql

from retail_ml.inventory_publish.run_artifacts import (
    ARTIFACT_COLUMNS,
    POLICY_VERSION,
)
from retail_ml.inventory_publish.verify import (
    VERIFIER_POLICY_ID,
    VerifiedInventoryRun,
)

SERVING_SCHEMA: Final[str] = "retail_serving"

#: 0010 adds the inventory serving surface. Materializing against 0009 would load
#: evidence into tables that do not exist; against a later head, into tables whose
#: constraints this writer has not been checked against.
MIGRATION_REVISION: Final[str] = "0010_inventory_serving"


class InventoryServingError(RuntimeError):
    """A verified bundle cannot be projected or activated."""


@dataclass(frozen=True)
class InventoryMaterialization:
    inventory_run_id: str
    inventory_version_id: str
    run_semantic_fingerprint: str
    forecast_run_id: str
    forecast_version_id: str
    row_counts: dict[str, int]
    already_materialized: bool


@dataclass(frozen=True)
class InventoryActivation:
    event_id: int
    inventory_version_id: str
    inventory_run_id: str
    already_active: bool


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryServingError(message)


def _database_value(value: Any) -> Any:
    """Coerce a pandas scalar to something psycopg can write.

    NaN becomes NULL rather than a float: 0010's truth-table constraints are
    written against NULL, and a NaN stored in a numeric column would satisfy
    `IS NOT NULL` while meaning "no value" -- which is how a withheld interval
    becomes an asserted one.
    """

    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, np.ndarray):
        return [_database_value(item) for item in value]
    if isinstance(value, (datetime, date, str, list)):
        return value
    return value.item() if hasattr(value, "item") else value


def _copy_frame(
    cursor: psycopg.Cursor[Any],
    *,
    table: str,
    version_id: str,
    frame: pd.DataFrame,
) -> None:
    columns = ("inventory_version_id", *ARTIFACT_COLUMNS[table])
    statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(SERVING_SCHEMA),
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    with cursor.copy(statement) as copy:
        for row in frame.itertuples(index=False, name=None):
            copy.write_row(
                (version_id, *(_database_value(value) for value in row))
            )


def _require_schema(cursor: psycopg.Cursor[Any]) -> None:
    try:
        cursor.execute("SELECT version_num FROM retail_intelligence_alembic_version")
        row = cursor.fetchone()
    except psycopg.Error as exc:
        raise InventoryServingError(
            "PostgreSQL serving migrations are absent; run tools/dev.py db-upgrade"
        ) from exc
    _require(
        row is not None and row[0] == MIGRATION_REVISION,
        f"PostgreSQL serving schema must be at {MIGRATION_REVISION}",
    )


def _version_id(run: VerifiedInventoryRun) -> str:
    """One version per run. P4-D15 makes the bundle the activation unit, so a run
    that produced one bundle cannot produce two independently servable versions."""

    return "iv_" + run.inventory_run_id.removeprefix("ir_")


def _existing_materialization(
    cursor: psycopg.Cursor[Any],
    *,
    run: VerifiedInventoryRun,
    row_counts: dict[str, int],
) -> InventoryMaterialization | None:
    """Return the prior materialization only if it is byte-for-byte the same run.

    An exact duplicate is idempotent; a run id that already exists with different
    lineage is a collision, and overwriting it would silently replace evidence
    somebody may already have activated.
    """

    cursor.execute(
        f"""
        SELECT
            run_semantic_fingerprint,
            source_selection_id,
            publication_semantic_fingerprint,
            forecast_run_id,
            forecast_version_id,
            policy_version,
            verifier_policy_id
        FROM {SERVING_SCHEMA}.inventory_materializations
        WHERE inventory_run_id = %s
        """,
        (run.inventory_run_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    manifest = run.manifest
    forecast = manifest["forecastAuthority"]
    _require(
        row[0] == run.semantic_fingerprint
        and row[1] == manifest["sourceSelectionId"]
        and row[2] == manifest["inputBundle"]["publicationSemanticFingerprint"]
        and row[3] == forecast["forecastRunId"]
        and row[4] == forecast["forecastVersionId"]
        and row[5] == POLICY_VERSION
        and row[6] == VERIFIER_POLICY_ID,
        "an existing materialization shares this inventory run id but disagrees "
        "with the verified bundle's lineage",
    )
    version_id = _version_id(run)
    cursor.execute(
        f"""
        SELECT inventory_version_id
        FROM {SERVING_SCHEMA}.inventory_versions
        WHERE inventory_run_id = %s
        """,
        (run.inventory_run_id,),
    )
    version_row = cursor.fetchone()
    _require(
        version_row is not None and version_row[0] == version_id,
        "the existing materialization has no matching version row",
    )
    for table, expected in row_counts.items():
        cursor.execute(
            sql.SQL("SELECT count(*) FROM {}.{} WHERE inventory_version_id = %s")
            .format(sql.Identifier(SERVING_SCHEMA), sql.Identifier(table)),
            (version_id,),
        )
        counted = cursor.fetchone()
        _require(
            counted is not None and int(counted[0]) == expected,
            f"{table} holds {None if counted is None else counted[0]} rows for "
            f"this version against {expected} in the verified bundle",
        )
    return InventoryMaterialization(
        inventory_run_id=run.inventory_run_id,
        inventory_version_id=version_id,
        run_semantic_fingerprint=run.semantic_fingerprint,
        forecast_run_id=str(forecast["forecastRunId"]),
        forecast_version_id=str(forecast["forecastVersionId"]),
        row_counts=row_counts,
        already_materialized=True,
    )


def materialize_inventory_run(
    run: VerifiedInventoryRun,
    *,
    postgres_dsn: str,
) -> InventoryMaterialization:
    """All-or-nothing projection of an independently verified bundle."""

    manifest = run.manifest
    forecast = manifest["forecastAuthority"]
    version_id = _version_id(run)
    frames = {
        name: pd.read_parquet(path) for name, path in run.artifact_paths.items()
    }
    row_counts = {name: len(frame) for name, frame in frames.items()}
    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (run.inventory_run_id,),
                )
                existing = _existing_materialization(
                    cursor, run=run, row_counts=row_counts
                )
                if existing is not None:
                    return existing
                # The forecast this bundle consumed must still be the active
                # authority AT MATERIALIZATION, not merely when the run was
                # scored. Materializing against a superseded forecast would load
                # rows the active view can never join, which serves as a silent
                # 503 rather than a refusal anyone can read.
                cursor.execute(
                    f"""
                    SELECT count(*)
                    FROM {SERVING_SCHEMA}.active_forecast_versions
                    WHERE forecast_run_id = %s AND version_id = %s
                    """,
                    (forecast["forecastRunId"], forecast["forecastVersionId"]),
                )
                matched = cursor.fetchone()
                _require(
                    matched is not None and int(matched[0]) == 1,
                    "the forecast this bundle consumed is not the active "
                    f"authority ({forecast['forecastRunId']}/"
                    f"{forecast['forecastVersionId']}); refit or re-activate "
                    "the forecast before materializing inventory against it",
                )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.inventory_materializations (
                        inventory_run_id,
                        run_semantic_fingerprint,
                        source_selection_id,
                        publication_semantic_fingerprint,
                        forecast_run_id,
                        forecast_version_id,
                        policy_version,
                        verifier_policy_id,
                        verifier_verdict
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'verified')
                    """,
                    (
                        run.inventory_run_id,
                        run.semantic_fingerprint,
                        manifest["sourceSelectionId"],
                        manifest["inputBundle"]["publicationSemanticFingerprint"],
                        forecast["forecastRunId"],
                        forecast["forecastVersionId"],
                        POLICY_VERSION,
                        VERIFIER_POLICY_ID,
                    ),
                )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.inventory_versions (
                        inventory_version_id,
                        inventory_run_id,
                        decision_as_of,
                        markets,
                        lifecycle_status
                    ) VALUES (%s, %s, %s, %s, 'accepted')
                    """,
                    (
                        version_id,
                        run.inventory_run_id,
                        manifest["decisionAsOf"],
                        run.markets,
                    ),
                )
                for table, frame in frames.items():
                    _copy_frame(
                        cursor,
                        table=table,
                        version_id=version_id,
                        frame=frame,
                    )
    except InventoryServingError:
        raise
    except psycopg.Error as exc:
        raise InventoryServingError(
            f"inventory PostgreSQL materialization failed: {exc}"
        ) from exc
    return InventoryMaterialization(
        inventory_run_id=run.inventory_run_id,
        inventory_version_id=version_id,
        run_semantic_fingerprint=run.semantic_fingerprint,
        forecast_run_id=str(forecast["forecastRunId"]),
        forecast_version_id=str(forecast["forecastVersionId"]),
        row_counts=row_counts,
        already_materialized=False,
    )


def activate_inventory_version(
    *,
    postgres_dsn: str,
    inventory_run_id: str,
    expected_run_semantic_fingerprint: str,
    actor: str,
) -> InventoryActivation:
    """Append an activation transition; never mutate the accepted artifacts.

    The predecessor is superseded in the same transaction and its event id is
    chained onto the new row, so the history reads as a sequence of decisions
    rather than a set of rows that happen to be marked active. The singleton
    pointer is what makes "one active bundle" a property of the database.
    """

    _require(bool(actor.strip()), "activation actor is required")
    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                _require_schema(cursor)
                # One lock for the whole surface: P4-D15 makes the bundle the
                # activation unit, so there is no narrower scope to serialize on.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended('retail_serving.active_inventory_state', 0))"
                )
                cursor.execute(
                    f"""
                    SELECT versions.inventory_version_id
                    FROM {SERVING_SCHEMA}.inventory_versions AS versions
                    JOIN {SERVING_SCHEMA}.inventory_materializations AS m
                      ON m.inventory_run_id = versions.inventory_run_id
                    WHERE versions.inventory_run_id = %s
                      AND m.run_semantic_fingerprint = %s
                      AND m.verifier_verdict = 'verified'
                      AND versions.lifecycle_status = 'accepted'
                    """,
                    (inventory_run_id, expected_run_semantic_fingerprint),
                )
                materialization = cursor.fetchone()
                _require(
                    materialization is not None,
                    "no accepted, independently verified materialization matches "
                    f"{inventory_run_id} at the expected fingerprint",
                )
                version_id = str(materialization[0])

                cursor.execute(
                    f"""
                    SELECT state.active_event_id, events.inventory_version_id
                    FROM {SERVING_SCHEMA}.active_inventory_state AS state
                    JOIN {SERVING_SCHEMA}.inventory_activation_events AS events
                      ON events.event_id = state.active_event_id
                    """
                )
                current = cursor.fetchone()
                if current is not None and current[1] == version_id:
                    return InventoryActivation(
                        event_id=int(current[0]),
                        inventory_version_id=version_id,
                        inventory_run_id=inventory_run_id,
                        already_active=True,
                    )

                prior_event_id: int | None = None
                if current is not None:
                    cursor.execute(
                        f"""
                        INSERT INTO {SERVING_SCHEMA}.inventory_activation_events (
                            inventory_version_id, event_type, actor, prior_event_id
                        ) VALUES (%s, 'superseded', %s, %s)
                        RETURNING event_id
                        """,
                        (current[1], actor, int(current[0])),
                    )
                    superseded = cursor.fetchone()
                    _require(
                        superseded is not None,
                        "failed to record the superseded activation",
                    )
                    prior_event_id = int(superseded[0])

                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.inventory_activation_events (
                        inventory_version_id, event_type, actor, prior_event_id
                    ) VALUES (%s, 'active', %s, %s)
                    RETURNING event_id
                    """,
                    (version_id, actor, prior_event_id),
                )
                activated = cursor.fetchone()
                _require(activated is not None, "failed to record the activation")
                event_id = int(activated[0])
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.active_inventory_state (
                        singleton, active_event_id
                    ) VALUES (TRUE, %s)
                    ON CONFLICT (singleton)
                    DO UPDATE SET active_event_id = EXCLUDED.active_event_id
                    """,
                    (event_id,),
                )
                # Assert the invariant rather than trusting the writes that are
                # supposed to guarantee it. If the fail-closed view is empty here,
                # the forecast authority moved between materialization and now and
                # this activation would serve nothing.
                cursor.execute(
                    f"SELECT count(*) FROM {SERVING_SCHEMA}.active_inventory_versions"
                )
                active_rows = cursor.fetchone()
                _require(
                    active_rows is not None and int(active_rows[0]) == 1,
                    "activation left "
                    f"{None if active_rows is None else active_rows[0]} rows in "
                    "active_inventory_versions; exactly one is required. The "
                    "consumed forecast is probably no longer the active authority.",
                )
    except InventoryServingError:
        raise
    except psycopg.Error as exc:
        raise InventoryServingError(f"inventory activation failed: {exc}") from exc
    return InventoryActivation(
        event_id=event_id,
        inventory_version_id=version_id,
        inventory_run_id=inventory_run_id,
        already_active=False,
    )


__all__ = [
    "MIGRATION_REVISION",
    "InventoryActivation",
    "InventoryMaterialization",
    "InventoryServingError",
    "activate_inventory_version",
    "materialize_inventory_run",
]
