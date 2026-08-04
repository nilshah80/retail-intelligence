"""Transactionally project a verified forecast run into PostgreSQL.

Parquet/JSON remains the immutable authority. This module is the only Phase-3
boundary that opens those forecast artifacts for API serving. The Go API reads
only the resulting PostgreSQL projection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from typing import Any, Final

import duckdb
import numpy as np
import pandas as pd
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ml.io.bundle import VerifiedInputBundle
from retail_ml.publish.verify import VerifiedForecastRun

SERVING_SCHEMA: Final[str] = "retail_serving"
#: Decision #82 made migration 0006 v4-only: the cohorted verifier and the v4
#: acceptance generation are the only shapes serving will accept, so 0005 is
#: immutable but no longer eligible to back a new activation.
#: Paired with acceptance-v5 / verifier-v5. 0007 retires decision #90's v1 activation
#: scopes and admits only runs scored against decision #85's HARD per-cohort coverage
#: gate, so materialising against 0006 would load evidence the schema no longer accepts.
#: 0008 makes forecast_series.yhat_p90/confidence nullable so decision #92's withheld
#: interval can be stored, and pairs them with an attributable reason.
MIGRATION_REVISION: Final[str] = "0019_supplier_identity"
#: v2 removes modelPolicy and classificationPolicies from the authority scope.
#:
#: Decision #90. v1 hashed them, so refitting a model policy over the SAME input bundle,
#: feature fingerprint and markets minted a parallel scope. The supersession lookup is
#: keyed on the scope, found nothing under the new one, and left both rows `active` with
#: `prior_event_id = NULL`. Two forecasts were then simultaneously authoritative over one
#: bundle, and Go -- which filters on a single configured fingerprint -- could not see the
#: competing authority. Serving happened to work only because the API took the most
#: recent row, an arbitrary tiebreak rather than a supersession rule.
#:
#: The policy fingerprints stay in RUN and VERSION identity, which is where they belong
#: and where they were deliberately added so a corrected remediation bundle cannot collide
#: with a mislabelled champion over byte-identical forecasts. The defect was reusing
#: policy-bearing lineage as the authority scope, not carrying policy in lineage.
ACTIVATION_SCOPE_SCHEMA: Final[str] = "retail-forecast-activation-scope/v2"
#: v5 pairs with acceptance-v5 and migration 0007: only a run scored against decision
#: #85's HARD per-cohort coverage gate may serve. v4 materialisations are not
#: reinterpreted, they simply stop being eligible, so no accepted artifact is rewritten.
FORECAST_VERIFICATION_CONTRACT: Final[str] = "retail-forecast-verifier/v5"

TABLE_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "forecast_versions": (
        "version_id",
        "forecast_run_id",
        "kind",
        "origin_date",
        "horizon_weeks",
        "created_by",
        "accuracy",
        "bias",
        "demand_units",
        "semantic_fingerprint",
        "artifact_status",
    ),
    "forecast_series": (
        "forecast_run_id",
        "version_id",
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "dept_id",
        "category",
        "horizon_week",
        "target_week_start",
        "yhat_p50",
        "yhat_p90",
        "confidence",
        # Explicit since 0009. Absent from this tuple the COPY omitted it and the
        # NOT NULL constraint rejected every row -- the one failure mode a column
        # list that drifts from its schema produces, and it produced it.
        "interval_available",
        "interval_unavailable_reason",
        "data_quality_class",
    ),
    "forecast_eval_predictions": (
        "forecast_run_id",
        "forecast_origin",
        "target_week_start",
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "horizon",
        "dept_id",
        "category",
        "actual_units",
        "yhat_p50",
        "yhat_p90",
        "confidence",
        "selected_model",
        "zero_share_52w",
        "abs_error_sum",
        "signed_error_sum",
        "actual_sum",
        "coverage_hits",
        "n",
    ),
    "forecast_metrics": (
        "forecast_run_id",
        "slice_type",
        "slice_id",
        "horizon",
        "model_id",
        "abs_error_sum",
        "signed_error_sum",
        "actual_sum",
        "coverage_hits",
        "n",
        "wape",
        "bias",
        "accuracy",
        "p90_coverage",
        "fva_vs_ma13_pct",
        "improvement_vs_seasonal_naive_pct",
    ),
    "forecast_drivers": (
        "forecast_run_id",
        "version_id",
        "scope",
        "driver",
        "contribution_pct",
        "direction",
        "confidence",
    ),
    "forecast_exceptions": (
        "forecast_run_id",
        "version_id",
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "exception_class",
        "severity",
        "status",
        "threshold",
        "evidence",
        "policy_id",
        "policy_semantic_fingerprint",
    ),
    "forecast_data_quality": (
        "forecast_run_id",
        "version_id",
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "data_quality_class",
        "evidence",
        "policy_id",
        "policy_semantic_fingerprint",
    ),
    "forecast_stores": (
        "forecast_run_id",
        "store_id",
        "market_id",
        "name",
        "city",
        "region",
        "timezone",
        "currency_code",
        "format",
        "active",
    ),
    "forecast_series_dimensions": (
        "forecast_run_id",
        "version_id",
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "product_name",
        "channel_type",
    ),
}


class ForecastServingError(RuntimeError):
    """A verified run cannot be safely materialized or activated."""


@dataclass(frozen=True)
class ForecastMaterialization:
    forecast_run_id: str
    version_id: str
    run_semantic_fingerprint: str
    publication_semantic_fingerprint: str
    activation_scope_fingerprint: str
    row_counts: dict[str, int]
    already_materialized: bool


@dataclass(frozen=True)
class ForecastActivation:
    event_id: int
    forecast_run_id: str
    version_id: str
    activation_scope_fingerprint: str
    already_active: bool
    #: Scopes superseded in the same transaction. Reported rather than logged: an
    #: operator activating a re-pin needs to see WHICH competing lineage was
    #: retired, and a silent retirement is the one outcome this must never be.
    retired_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PreparedServingProjection:
    version_id: str
    activation_scope_fingerprint: str
    markets: tuple[str, ...]
    acceptance: dict[str, Any]
    frames: dict[str, pd.DataFrame]

    @property
    def row_counts(self) -> dict[str, int]:
        return {name: len(frame) for name, frame in self.frames.items()}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ForecastServingError(message)


def _read_frame(run: VerifiedForecastRun, name: str) -> pd.DataFrame:
    try:
        return pd.read_parquet(run.artifact_paths[name])
    except (OSError, TypeError, ValueError) as exc:
        raise ForecastServingError(f"cannot read verified artifact {name}: {exc}") from exc


def _historical_series_dimensions(evaluation: pd.DataFrame) -> pd.DataFrame:
    keys = ["sku_id", "store_id", "channel_id"]
    columns = [*keys, "market_id", "dept_id", "category"]
    dimensions = evaluation[columns].drop_duplicates()
    conflicts = dimensions.duplicated(keys, keep=False)
    _require(
        not conflicts.any(),
        "a SeriesKey maps to multiple market/department/category dimensions",
    )
    return dimensions


def _canonical_series_dimensions(
    input_bundle: VerifiedInputBundle,
    series_keys: pd.DataFrame,
) -> pd.DataFrame:
    logical_path = input_bundle.publication_manifest.get("duckdb", {}).get("path")
    _require(
        isinstance(logical_path, str)
        and bool(logical_path)
        and Path(logical_path).name == logical_path,
        "publication DuckDB path is invalid",
    )
    database_path = (input_bundle.paths.curated_root / logical_path).resolve()
    _require(
        database_path.parent == input_bundle.paths.curated_root.resolve()
        and database_path.is_file(),
        "verified publication DuckDB is unavailable",
    )
    try:
        connection = duckdb.connect(str(database_path), read_only=True)
        try:
            products = connection.execute(
                """
                SELECT sku_id, dept_id, category, product_name
                FROM canonical_data.products
                """
            ).fetchdf()
            channels = connection.execute(
                """
                SELECT
                    channel_id,
                    market_id AS channel_market_id,
                    type AS channel_type
                FROM canonical_data.channels
                """
            ).fetchdf()
        finally:
            connection.close()
    except duckdb.Error as exc:
        raise ForecastServingError(
            f"cannot read canonical serving dimensions: {exc}"
        ) from exc
    _require(
        not products.duplicated(["sku_id"]).any(),
        "canonical products contain duplicate sku_id values",
    )
    _require(
        not channels.duplicated(["channel_id"]).any(),
        "canonical channels contain duplicate channel_id values",
    )
    raw_stores = input_bundle.publication_manifest["businessControls"]["stores"]
    all_markets = tuple(
        sorted(
            {
                str(store["marketId"])
                for store in raw_stores
                if isinstance(store, dict) and store.get("marketId") is not None
            }
        )
    )
    stores = _store_frame(
        input_bundle,
        run_id="dimension-lookup",
        markets=all_markets,
    )[["store_id", "market_id"]]
    dimensions = (
        series_keys.drop_duplicates()
        .merge(products, on="sku_id", how="left", validate="many_to_one")
        .merge(stores, on="store_id", how="left", validate="many_to_one")
        .merge(channels, on="channel_id", how="left", validate="many_to_one")
    )
    _require(
        not dimensions[
            [
                "market_id",
                "channel_market_id",
                "dept_id",
                "category",
                "product_name",
                "channel_type",
            ]
        ]
        .isna()
        .any(axis=None),
        "canonical products/stores/channels do not cover every forecast SeriesKey",
    )
    _require(
        bool((dimensions["market_id"] == dimensions["channel_market_id"]).all()),
        "forecast SeriesKey crosses store and channel markets",
    )
    return dimensions[
        [
            "sku_id",
            "store_id",
            "channel_id",
            "market_id",
            "dept_id",
            "category",
            "product_name",
            "channel_type",
        ]
    ]


def _store_frame(
    input_bundle: VerifiedInputBundle,
    *,
    run_id: str,
    markets: tuple[str, ...],
) -> pd.DataFrame:
    business_controls = input_bundle.publication_manifest.get("businessControls")
    _require(
        isinstance(business_controls, dict),
        "publication businessControls is required for serving dimensions",
    )
    raw_stores = business_controls.get("stores")
    _require(
        isinstance(raw_stores, list),
        "publication businessControls.stores is required",
    )
    rows: list[dict[str, Any]] = []
    for value in raw_stores:
        _require(isinstance(value, dict), "publication store must be an object")
        if value.get("marketId") not in markets:
            continue
        rows.append(
            {
                "forecast_run_id": run_id,
                "store_id": value.get("storeId"),
                "market_id": value.get("marketId"),
                "name": value.get("name"),
                "city": value.get("city"),
                "region": value.get("region"),
                "timezone": value.get("timezone"),
                "currency_code": value.get("currencyCode"),
                "format": value.get("format"),
                "active": value.get("active"),
            }
        )
    stores = pd.DataFrame(rows, columns=TABLE_COLUMNS["forecast_stores"])
    _require(
        not stores.empty and not stores.isna().any(axis=None),
        "publication stores do not cover the forecast markets",
    )
    _require(
        not stores["store_id"].duplicated().any(),
        "publication stores contain duplicate store_id values",
    )
    return stores


def _activation_scope(
    manifest: dict[str, Any],
    *,
    markets: tuple[str, ...],
) -> str:
    # What makes two forecasts rivals for the same audience: the same curated input, the
    # same features, the same markets. A different model policy over that input is a
    # SUCCESSOR to be superseded, not a separate authority to be served beside it.
    descriptor = {
        "schemaVersion": ACTIVATION_SCOPE_SCHEMA,
        "inputBundle": manifest["inputBundle"],
        "featureSemanticFingerprint": manifest["featureSemanticFingerprint"],
        "markets": list(markets),
    }
    return semantic_fingerprint(descriptor)


def prepare_serving_projection(
    run: VerifiedForecastRun,
    input_bundle: VerifiedInputBundle,
) -> PreparedServingProjection:
    """Create bounded SQL frames after both immutable bundles were verified."""

    _require(
        run.lifecycle_status == "accepted",
        "only an accepted forecast run can be materialized",
    )
    _require(
        run.manifest.get("inputBundle") == input_bundle.identity,
        "forecast run does not match the verified curated input bundle",
    )
    run_id = run.forecast_run_id
    versions = _read_frame(run, "forecast_versions")
    series = _read_frame(run, "forecast_series")
    evaluation = _read_frame(run, "forecast_eval_predictions")
    metrics = _read_frame(run, "forecast_metrics")
    drivers = _read_frame(run, "forecast_drivers")
    exceptions = _read_frame(run, "forecast_exceptions")
    quality = _read_frame(run, "forecast_data_quality")
    try:
        acceptance = json.loads(
            run.artifact_paths["forecast_acceptance"].read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ForecastServingError(f"cannot read acceptance evidence: {exc}") from exc

    _require(len(versions) == 1, "serving requires exactly one forecast version")
    version_id = str(versions.iloc[0]["version_id"])
    _require(
        str(versions.iloc[0]["status"]) == "accepted",
        "forecast version is not accepted",
    )
    historical_dimensions = _historical_series_dimensions(evaluation)
    series_keys = ["sku_id", "store_id", "channel_id"]
    dimensions = _canonical_series_dimensions(
        input_bundle,
        pd.concat(
            [
                series[series_keys],
                evaluation[series_keys],
                exceptions[series_keys],
                quality[series_keys],
            ],
            ignore_index=True,
        ),
    )
    historical_check = historical_dimensions.merge(
        dimensions,
        on=series_keys,
        how="left",
        suffixes=("_evaluation", "_canonical"),
        validate="one_to_one",
    )
    for column in ("market_id", "dept_id", "category"):
        _require(
            bool(
                (
                    historical_check[f"{column}_evaluation"]
                    == historical_check[f"{column}_canonical"]
                ).all()
            ),
            f"evaluation {column} disagrees with canonical dimensions",
        )
    markets = tuple(sorted(str(value) for value in dimensions["market_id"].unique()))
    _require(bool(markets), "forecast serving projection has no markets")

    quality_join = quality[[*series_keys, "data_quality_class"]]
    _require(
        not quality_join.duplicated(series_keys).any(),
        "forecast data quality violates SeriesKey grain",
    )
    # Decision #92. A withheld interval must carry WHY, and the reason comes from the
    # bundle's own `intervalAvailability.reasonCode` rather than being invented here: the
    # publisher decided what was withheld, so the serving layer must not author its own
    # explanation for it. Migration 0009 enforces the pairing in the database.
    availability = run.manifest.get("intervalAvailability") or {}
    interval_reason = str(availability.get("reasonCode") or "INTERVAL_UNAVAILABLE")
    series = series.copy()
    # Migration 0009 made availability an EXPLICIT NOT NULL column precisely so a
    # consumer can stop inferring it from P90 nullability -- the two facts are
    # different and only the flag is authoritative downstream. This writer is the
    # boundary where the flag is established, and the artifact's nullability is the
    # only per-row source it has, so the derivation is reconciled against the
    # publisher's own count below rather than simply trusted. Omitting the column
    # entirely, which is what this code did before, produced a NOT NULL violation
    # at COPY time on the first republish after 0009.
    interval_available = pd.to_numeric(
        series["yhat_p90"], errors="coerce"
    ).notna()
    series["interval_available"] = interval_available.to_numpy()
    declared_withheld = availability.get("withheldRows")
    derived_withheld = int((~interval_available).sum())
    _require(
        declared_withheld is None or int(declared_withheld) == derived_withheld,
        f"the bundle declares {declared_withheld} withheld interval rows but the "
        f"projection derives {derived_withheld}. The publisher decided what was "
        "withheld; a writer that disagrees with it must not choose a winner.",
    )
    _require(
        declared_withheld is not None,
        "the bundle records no withheldRows count, so the derived availability "
        "flag cannot be reconciled against the publisher's decision",
    )
    # Derived from the SAME flag, never independently from nullability: two
    # derivations of one fact are two chances to disagree, and 0009's CHECK
    # constraint would then reject the row with no indication which was wrong.
    series["interval_unavailable_reason"] = np.where(
        series["interval_available"], None, interval_reason
    )
    serving_series = series.merge(
        dimensions,
        on=series_keys,
        how="left",
        validate="many_to_one",
    ).merge(
        quality_join,
        on=series_keys,
        how="left",
        validate="many_to_one",
    )
    _require(
        not serving_series[
            ["market_id", "dept_id", "category", "data_quality_class"]
        ]
        .isna()
        .any(axis=None),
        "current forecast SeriesKeys are absent from evaluation dimensions or quality",
    )
    origin_date = pd.Timestamp(versions.iloc[0]["origin_date"]).date()
    serving_series["target_week_start"] = serving_series["horizon_week"].map(
        lambda horizon: origin_date + timedelta(weeks=int(horizon))
    )
    serving_series.insert(0, "forecast_run_id", run_id)

    serving_versions = versions.rename(columns={"status": "artifact_status"}).copy()
    serving_versions.insert(1, "forecast_run_id", run_id)

    serving_evaluation = evaluation.copy()
    serving_evaluation.insert(0, "forecast_run_id", run_id)
    serving_metrics = metrics.copy()
    serving_metrics.insert(0, "forecast_run_id", run_id)
    serving_drivers = drivers.copy()
    serving_drivers.insert(0, "forecast_run_id", run_id)

    exception_dimensions = dimensions[series_keys + ["market_id"]]
    serving_exceptions = exceptions.merge(
        exception_dimensions,
        on=series_keys,
        how="left",
        validate="many_to_one",
    )
    serving_exceptions.insert(0, "version_id", version_id)
    serving_exceptions.insert(0, "forecast_run_id", run_id)
    _require(
        not serving_exceptions["market_id"].isna().any(),
        "forecast exception SeriesKeys are absent from evaluation dimensions",
    )

    serving_quality = quality.merge(
        exception_dimensions,
        on=series_keys,
        how="left",
        validate="one_to_one",
    )
    serving_quality.insert(0, "version_id", version_id)
    serving_quality.insert(0, "forecast_run_id", run_id)
    _require(
        not serving_quality["market_id"].isna().any(),
        "forecast quality SeriesKeys are absent from evaluation dimensions",
    )

    serving_dimensions = dimensions[
        [
            "market_id",
            "sku_id",
            "store_id",
            "channel_id",
            "product_name",
            "channel_type",
        ]
    ].copy()
    serving_dimensions.insert(0, "version_id", version_id)
    serving_dimensions.insert(0, "forecast_run_id", run_id)

    frames = {
        "forecast_versions": serving_versions[
            list(TABLE_COLUMNS["forecast_versions"])
        ],
        "forecast_series": serving_series[list(TABLE_COLUMNS["forecast_series"])],
        "forecast_eval_predictions": serving_evaluation[
            list(TABLE_COLUMNS["forecast_eval_predictions"])
        ],
        "forecast_metrics": serving_metrics[list(TABLE_COLUMNS["forecast_metrics"])],
        "forecast_drivers": serving_drivers[list(TABLE_COLUMNS["forecast_drivers"])],
        "forecast_exceptions": serving_exceptions[
            list(TABLE_COLUMNS["forecast_exceptions"])
        ],
        "forecast_data_quality": serving_quality[
            list(TABLE_COLUMNS["forecast_data_quality"])
        ],
        "forecast_stores": _store_frame(
            input_bundle,
            run_id=run_id,
            markets=markets,
        ),
        "forecast_series_dimensions": serving_dimensions[
            list(TABLE_COLUMNS["forecast_series_dimensions"])
        ],
    }
    for name, frame in frames.items():
        _require(
            list(frame.columns) == list(TABLE_COLUMNS[name]),
            f"{name} differs from the frozen SQL projection",
        )
    return PreparedServingProjection(
        version_id=version_id,
        activation_scope_fingerprint=_activation_scope(
            run.manifest,
            markets=markets,
        ),
        markets=markets,
        acceptance=acceptance,
        frames=frames,
    )


def _database_value(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (np.floating, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, (datetime, date, str)):
        return value
    return value.item() if hasattr(value, "item") else value


def _copy_frame(
    cursor: psycopg.Cursor[Any],
    *,
    table: str,
    frame: pd.DataFrame,
) -> None:
    statement = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(SERVING_SCHEMA),
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in TABLE_COLUMNS[table]),
    )
    with cursor.copy(statement) as copy:
        for row in frame.itertuples(index=False, name=None):
            copy.write_row(tuple(_database_value(value) for value in row))


def _require_schema(cursor: psycopg.Cursor[Any]) -> None:
    try:
        cursor.execute(
            "SELECT version_num FROM retail_intelligence_alembic_version"
        )
        row = cursor.fetchone()
    except psycopg.Error as exc:
        raise ForecastServingError(
            "PostgreSQL serving migrations are absent; run tools/dev.py db-upgrade"
        ) from exc
    _require(
        row is not None and row[0] == MIGRATION_REVISION,
        f"PostgreSQL serving schema must be at {MIGRATION_REVISION}",
    )


def _existing_materialization(
    cursor: psycopg.Cursor[Any],
    *,
    run: VerifiedForecastRun,
    projection: PreparedServingProjection,
) -> ForecastMaterialization | None:
    cursor.execute(
        f"""
        SELECT
            version_id,
            run_semantic_fingerprint,
            publication_semantic_fingerprint,
            activation_scope_fingerprint,
            verification_contract,
            row_counts
        FROM {SERVING_SCHEMA}.forecast_materializations
        WHERE forecast_run_id = %s
        """,
        (run.forecast_run_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    expected_publication = str(
        run.manifest["inputBundle"]["publicationSemanticFingerprint"]
    )
    expected_counts = projection.row_counts
    recorded_counts = dict(row[5])
    recorded_counts_match = all(
        name in expected_counts and expected_counts[name] == count
        for name, count in recorded_counts.items()
    )
    _require(
        row[0] == projection.version_id
        and row[1] == run.semantic_fingerprint
        and row[2] == expected_publication
        and row[3] == projection.activation_scope_fingerprint
        and row[4] == FORECAST_VERIFICATION_CONTRACT
        and recorded_counts_match,
        "existing materialization disagrees with the verified immutable run",
    )
    return ForecastMaterialization(
        forecast_run_id=run.forecast_run_id,
        version_id=projection.version_id,
        run_semantic_fingerprint=run.semantic_fingerprint,
        publication_semantic_fingerprint=expected_publication,
        activation_scope_fingerprint=projection.activation_scope_fingerprint,
        row_counts=expected_counts,
        already_materialized=True,
    )


def _ensure_series_dimensions(
    cursor: psycopg.Cursor[Any],
    *,
    run: VerifiedForecastRun,
    projection: PreparedServingProjection,
) -> None:
    frame = projection.frames["forecast_series_dimensions"]
    cursor.execute(
        f"""
        SELECT COUNT(*)
        FROM {SERVING_SCHEMA}.forecast_series_dimensions
        WHERE forecast_run_id = %s
        """,
        (run.forecast_run_id,),
    )
    row = cursor.fetchone()
    existing_count = int(row[0]) if row is not None else 0
    if existing_count == 0:
        _copy_frame(
            cursor,
            table="forecast_series_dimensions",
            frame=frame,
        )
    else:
        _require(
            existing_count == len(frame),
            "existing forecast series dimensions are incomplete",
        )
    cursor.execute(
        f"""
        UPDATE {SERVING_SCHEMA}.forecast_materializations
        SET row_counts = %s
        WHERE forecast_run_id = %s
        """,
        (Jsonb(projection.row_counts), run.forecast_run_id),
    )


def materialize_forecast_run(
    run: VerifiedForecastRun,
    input_bundle: VerifiedInputBundle,
    *,
    postgres_dsn: str,
) -> ForecastMaterialization:
    """Verify-derived, idempotent, all-or-nothing PostgreSQL materialization."""

    projection = prepare_serving_projection(run, input_bundle)
    manifest = run.manifest
    publication_fingerprint = input_bundle.publication_semantic_fingerprint
    row_counts = projection.row_counts
    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (run.forecast_run_id,),
                )
                existing = _existing_materialization(
                    cursor,
                    run=run,
                    projection=projection,
                )
                if existing is not None:
                    _ensure_series_dimensions(
                        cursor,
                        run=run,
                        projection=projection,
                    )
                    return ForecastMaterialization(
                        forecast_run_id=existing.forecast_run_id,
                        version_id=existing.version_id,
                        run_semantic_fingerprint=existing.run_semantic_fingerprint,
                        publication_semantic_fingerprint=(
                            existing.publication_semantic_fingerprint
                        ),
                        activation_scope_fingerprint=(
                            existing.activation_scope_fingerprint
                        ),
                        row_counts=projection.row_counts,
                        already_materialized=True,
                    )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_materializations (
                        forecast_run_id,
                        version_id,
                        run_semantic_fingerprint,
                        publication_semantic_fingerprint,
                        feature_semantic_fingerprint,
                        verification_contract,
                        activation_scope_fingerprint,
                        decision_as_of,
                        lifecycle_status,
                        input_bundle,
                        model_policy,
                        classification_policies,
                        acceptance,
                        artifact_descriptors,
                        row_counts,
                        markets
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, 'accepted',
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        run.forecast_run_id,
                        projection.version_id,
                        run.semantic_fingerprint,
                        publication_fingerprint,
                        manifest["featureSemanticFingerprint"],
                        FORECAST_VERIFICATION_CONTRACT,
                        projection.activation_scope_fingerprint,
                        manifest["decisionAsOf"],
                        Jsonb(manifest["inputBundle"]),
                        Jsonb(manifest["modelPolicy"]),
                        Jsonb(manifest["classificationPolicies"]),
                        Jsonb(projection.acceptance),
                        Jsonb(manifest["artifacts"]),
                        Jsonb(row_counts),
                        list(projection.markets),
                    ),
                )
                for table, frame in projection.frames.items():
                    _copy_frame(cursor, table=table, frame=frame)
    except ForecastServingError:
        raise
    except psycopg.Error as exc:
        raise ForecastServingError(
            f"forecast PostgreSQL materialization failed: {exc}"
        ) from exc
    return ForecastMaterialization(
        forecast_run_id=run.forecast_run_id,
        version_id=projection.version_id,
        run_semantic_fingerprint=run.semantic_fingerprint,
        publication_semantic_fingerprint=publication_fingerprint,
        activation_scope_fingerprint=projection.activation_scope_fingerprint,
        row_counts=row_counts,
        already_materialized=False,
    )


def activate_forecast_version(
    *,
    postgres_dsn: str,
    forecast_run_id: str,
    activation_scope_fingerprint: str,
    expected_publication_fingerprint: str,
    actor: str,
    retire_other_scopes: bool = False,
) -> ForecastActivation:
    """Append an activation transition without mutating the accepted artifacts.

    `retire_other_scopes` supersedes every OTHER currently-active scope inside the
    same transaction. It exists because a re-pin onto a new source publication was
    otherwise unreachable: the scope fingerprint covers the input bundle, so a new
    publication legitimately mints a new scope, the same-scope supersession below
    finds nothing to retire, and the decision-#90 assertion at the end then refuses
    with "retire it before activating" -- advice nothing in this module could
    follow. That is a real dead end, not a safety feature.

    Three properties make it safe to have:

    * it is opt-in, so a competing lineage can never be retired as a side effect
      of a routine activation;
    * it happens in the SAME transaction as the new activation, so serving never
      passes through a window with zero active versions. A separate retire command
      would be a self-inflicted outage;
    * it is append-only. Each retirement inserts a `superseded` event chained to
      the event it retires, so the history says who retired what and when, and
      nothing is deleted or rewritten.
    """

    _require(bool(actor.strip()), "activation actor is required")
    try:
        with psycopg.connect(postgres_dsn) as connection:
            with connection.cursor() as cursor:
                _require_schema(cursor)
                # Lock the whole table, not just this scope: retiring OTHER scopes
                # means two concurrent activations in different scopes could each
                # retire the other's fresh activation. Scope-local locking is
                # enough only while activation is scope-local, which it no longer
                # is whenever retire_other_scopes is set.
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (
                        "retail_serving.forecast_activation_events"
                        if retire_other_scopes
                        else activation_scope_fingerprint,
                    ),
                )
                cursor.execute(
                    f"""
                    SELECT version_id
                    FROM {SERVING_SCHEMA}.forecast_materializations
                    WHERE forecast_run_id = %s
                      AND activation_scope_fingerprint = %s
                      AND publication_semantic_fingerprint = %s
                      AND lifecycle_status = 'accepted'
                    """,
                    (
                        forecast_run_id,
                        activation_scope_fingerprint,
                        expected_publication_fingerprint,
                    ),
                )
                materialization = cursor.fetchone()
                _require(
                    materialization is not None,
                    "no accepted lineage-matching materialization can be activated",
                )
                version_id = str(materialization[0])
                cursor.execute(
                    f"""
                    SELECT event_id, forecast_run_id, version_id, event_type
                    FROM {SERVING_SCHEMA}.forecast_activation_events
                    WHERE activation_scope_fingerprint = %s
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (activation_scope_fingerprint,),
                )
                current = cursor.fetchone()
                if (
                    current is not None
                    and current[1] == forecast_run_id
                    and current[2] == version_id
                    and current[3] == "active"
                ):
                    return ForecastActivation(
                        event_id=int(current[0]),
                        forecast_run_id=forecast_run_id,
                        version_id=version_id,
                        activation_scope_fingerprint=activation_scope_fingerprint,
                        already_active=True,
                    )
                prior_event_id = int(current[0]) if current is not None else None
                if current is not None and current[3] == "active":
                    cursor.execute(
                        f"""
                        INSERT INTO {SERVING_SCHEMA}.forecast_activation_events (
                            activation_scope_fingerprint,
                            forecast_run_id,
                            version_id,
                            event_type,
                            actor,
                            prior_event_id
                        ) VALUES (%s, %s, %s, 'superseded', %s, %s)
                        RETURNING event_id
                        """,
                        (
                            activation_scope_fingerprint,
                            current[1],
                            current[2],
                            actor,
                            prior_event_id,
                        ),
                    )
                    superseded = cursor.fetchone()
                    _require(
                        superseded is not None,
                        "failed to record superseded activation",
                    )
                    prior_event_id = int(superseded[0])

                retired: list[dict[str, str]] = []
                if retire_other_scopes:
                    # Every other scope whose latest event is still `active`. The
                    # DISTINCT ON picks each scope's newest event and keeps it only
                    # if that event is an activation, so a scope already retired is
                    # skipped rather than retired twice.
                    cursor.execute(
                        f"""
                        WITH latest AS (
                            SELECT DISTINCT ON (activation_scope_fingerprint)
                                activation_scope_fingerprint, event_id,
                                forecast_run_id, version_id, event_type
                            FROM {SERVING_SCHEMA}.forecast_activation_events
                            WHERE activation_scope_fingerprint <> %s
                            ORDER BY activation_scope_fingerprint, event_id DESC
                        )
                        SELECT activation_scope_fingerprint, event_id,
                               forecast_run_id, version_id
                        FROM latest
                        WHERE event_type = 'active'
                        ORDER BY activation_scope_fingerprint
                        """,
                        (activation_scope_fingerprint,),
                    )
                    for scope, retired_event, retired_run, retired_version in (
                        cursor.fetchall()
                    ):
                        cursor.execute(
                            f"""
                            INSERT INTO {SERVING_SCHEMA}.forecast_activation_events (
                                activation_scope_fingerprint,
                                forecast_run_id,
                                version_id,
                                event_type,
                                actor,
                                prior_event_id
                            ) VALUES (%s, %s, %s, 'superseded', %s, %s)
                            """,
                            (
                                str(scope),
                                str(retired_run),
                                str(retired_version),
                                actor,
                                int(retired_event),
                            ),
                        )
                        retired.append(
                            {
                                "activationScopeFingerprint": str(scope),
                                "forecastRunId": str(retired_run),
                                "versionId": str(retired_version),
                            }
                        )

                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_activation_events (
                        activation_scope_fingerprint,
                        forecast_run_id,
                        version_id,
                        event_type,
                        actor,
                        prior_event_id
                    ) VALUES (%s, %s, %s, 'active', %s, %s)
                    RETURNING event_id
                    """,
                    (
                        activation_scope_fingerprint,
                        forecast_run_id,
                        version_id,
                        actor,
                        prior_event_id,
                    ),
                )
                activated = cursor.fetchone()
                _require(activated is not None, "failed to record forecast activation")
                event_id = int(activated[0])
                # Decision #90 fails closed on competing authority. The scope change
                # above prevents a NEW parallel scope, but a scope minted under v1 can
                # still be sitting active, and a future scope-definition change could
                # reintroduce the same class of defect. Assert the invariant rather than
                # trusting the derivation that is supposed to guarantee it.
                cursor.execute(
                    f"""
                    SELECT count(*) FROM {SERVING_SCHEMA}.active_forecast_versions
                    """
                )
                active_rows = cursor.fetchone()
                _require(
                    active_rows is not None and int(active_rows[0]) == 1,
                    "decision #90 requires exactly one active forecast version; found "
                    f"{None if active_rows is None else active_rows[0]}. Another "
                    "activation scope is still active -- most often because this "
                    "publication is a re-pin and the scope fingerprint covers the "
                    "input bundle. Pass retire_other_scopes to supersede it in the "
                    "same transaction (--retire-other-scopes on the CLI).",
                )
    except ForecastServingError:
        raise
    except psycopg.Error as exc:
        raise ForecastServingError(f"forecast activation failed: {exc}") from exc
    return ForecastActivation(
        event_id=event_id,
        forecast_run_id=forecast_run_id,
        version_id=version_id,
        activation_scope_fingerprint=activation_scope_fingerprint,
        already_active=False,
        retired_scopes=tuple(
            entry["activationScopeFingerprint"] for entry in retired
        ),
    )


__all__ = [
    "ACTIVATION_SCOPE_SCHEMA",
    "FORECAST_VERIFICATION_CONTRACT",
    "ForecastActivation",
    "ForecastMaterialization",
    "ForecastServingError",
    "PreparedServingProjection",
    "activate_forecast_version",
    "materialize_forecast_run",
    "prepare_serving_projection",
]
