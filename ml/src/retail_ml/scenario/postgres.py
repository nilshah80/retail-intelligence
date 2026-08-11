"""PostgreSQL authority and immutable publication for scenario contexts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final, Mapping

import pandas as pd
import psycopg
from psycopg.types.json import Jsonb
from retail_contracts.fingerprint import semantic_fingerprint
from retail_contracts.scenario_assumptions import (
    may_receive_serving_approval,
    scenario_assumption_fingerprint,
    validate_scenario_assumption_bundle,
)

from retail_ml.scenario.context import (
    AssumptionApproval,
    BuiltBaseContext,
    BuiltInventoryExtension,
    ScenarioAuthority,
)

SERVING_SCHEMA: Final[str] = "retail_serving"
MIGRATION_REVISION: Final[str] = "0027_scenario_hardening"


class ScenarioServingError(RuntimeError):
    """Scenario authority is absent, ambiguous, stale, or non-publishable."""


@dataclass(frozen=True)
class RegisteredAssumptionBundle:
    assumption_set_id: str
    assumption_version: str
    semantic_fingerprint: str
    already_registered: bool


@dataclass(frozen=True)
class ForecastAuthority:
    forecast_run_id: str
    forecast_version_id: str
    activation_scope_fingerprint: str
    decision_as_of: datetime
    rows: pd.DataFrame


@dataclass(frozen=True)
class BaseContextMaterialization:
    scenario_context_version: str
    horizon_rows: int
    commercial_rows: int
    already_materialized: bool


@dataclass(frozen=True)
class BaseContextActivation:
    event_id: int
    scenario_context_version: str
    already_active: bool


@dataclass(frozen=True)
class InventoryAuthority:
    inventory_version_id: str
    forecast_version_id: str
    decision_as_of: datetime
    positions: pd.DataFrame
    allocations: pd.DataFrame
    recommendations: pd.DataFrame
    sku_dimensions: pd.DataFrame
    currency_by_market: dict[str, str]


@dataclass(frozen=True)
class InventoryExtensionMaterialization:
    inventory_extension_version: str
    series_rows: int
    node_rows: int
    already_materialized: bool


@dataclass(frozen=True)
class InventoryExtensionActivation:
    event_id: int
    inventory_extension_version: str
    already_active: bool


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioServingError(message)


def _require_schema(cursor: psycopg.Cursor[Any]) -> None:
    try:
        cursor.execute("SELECT version_num FROM retail_intelligence_alembic_version")
        row = cursor.fetchone()
    except psycopg.Error as exc:
        raise ScenarioServingError(
            "PostgreSQL serving migrations are absent; run tools/dev.py db-upgrade"
        ) from exc
    _require(
        row is not None and row[0] == MIGRATION_REVISION,
        f"PostgreSQL serving schema must be at {MIGRATION_REVISION}",
    )


def register_assumption_bundle(
    postgres_dsn: str,
    bundle: Mapping[str, Any],
) -> RegisteredAssumptionBundle:
    """Insert an immutable bundle and all multi-grain children, idempotently."""

    validate_scenario_assumption_bundle(bundle)
    fingerprint = scenario_assumption_fingerprint(bundle)
    assumption_set_id = str(bundle["assumptionSetId"])
    assumption_version = str(bundle["version"])
    with psycopg.connect(postgres_dsn) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT semantic_fingerprint, bundle_payload, children_sealed
                    FROM {SERVING_SCHEMA}.forecast_scenario_assumption_sets
                    WHERE assumption_set_id = %s AND assumption_version = %s
                    """,
                    (assumption_set_id, assumption_version),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    _require(
                        existing[0] == fingerprint
                        and scenario_assumption_fingerprint(existing[1]) == fingerprint
                        and bool(existing[2]),
                        "an assumption id/version already exists with different values",
                    )
                    return RegisteredAssumptionBundle(
                        assumption_set_id,
                        assumption_version,
                        fingerprint,
                        True,
                    )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_assumption_sets (
                        assumption_set_id, assumption_version, semantic_fingerprint,
                        schema_version, artifact_class, serving_eligible,
                        projection_basis, evidence_class, statistical_gate_status,
                        disclosure, request_bounds, bundle_payload
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        assumption_set_id,
                        assumption_version,
                        fingerprint,
                        bundle["schemaVersion"],
                        bundle["artifactClass"],
                        bundle["servingEligible"],
                        bundle["projectionBasis"],
                        bundle["evidenceClass"],
                        bundle["statisticalGateStatus"],
                        bundle["disclosure"],
                        Jsonb(bundle["requestBounds"]),
                        Jsonb(dict(bundle)),
                    ),
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_market_rules (
                        assumption_semantic_fingerprint, market_id, currency_code,
                        minimum_price_minor, maximum_price_minor,
                        candidate_step_minor, grid_origin_minor, rounding_mode,
                        price_freshness_days, observed_support_window_days
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            fingerprint,
                            rule["marketId"],
                            rule["currencyCode"],
                            rule["minimumPriceMinor"],
                            rule["maximumPriceMinor"],
                            rule["candidateStepMinor"],
                            rule["gridOriginMinor"],
                            rule["roundingMode"],
                            rule["priceFreshnessDays"],
                            rule["observedSupportWindowDays"],
                        )
                        for rule in bundle["marketCurrencyRules"]
                    ],
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_tier_coefficients (
                        assumption_semantic_fingerprint, market_id, dept_id,
                        baseline_price_tier, lower_price_minor, upper_price_minor,
                        assumed_beta, competitor_stockout_sensitivity,
                        competitor_promotion_sensitivity,
                        weather_positive_sensitivity, weather_negative_sensitivity
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            fingerprint,
                            tier["marketId"],
                            tier["deptId"],
                            tier["baselinePriceTier"],
                            tier["lowerPriceMinor"],
                            tier["upperPriceMinor"],
                            tier["assumedBeta"],
                            tier["competitorStockoutSensitivity"],
                            tier["competitorPromotionSensitivity"],
                            tier["weatherPositiveSensitivity"],
                            tier["weatherNegativeSensitivity"],
                        )
                        for tier in bundle["tierCoefficients"]
                    ],
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_presets (
                        assumption_semantic_fingerprint, preset_id, label,
                        demand_adjustment_pct, price_change_pct,
                        promotion_uplift_pct, competitor_availability,
                        weather_event, atp_adjustment
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            fingerprint,
                            preset["presetId"],
                            preset["label"],
                            preset["demandAdjustmentPct"],
                            preset["priceChangePct"],
                            preset["promotionUpliftPct"],
                            preset["competitorAvailability"],
                            preset["weatherEvent"],
                            preset["atpAdjustment"],
                        )
                        for preset in bundle["presets"]
                    ],
                )
                cursor.execute(
                    f"""
                    UPDATE {SERVING_SCHEMA}.forecast_scenario_assumption_sets
                    SET children_sealed = TRUE
                    WHERE assumption_set_id = %s AND assumption_version = %s
                      AND semantic_fingerprint = %s AND NOT children_sealed
                    """,
                    (assumption_set_id, assumption_version, fingerprint),
                )
                _require(cursor.rowcount == 1, "assumption bundle could not be sealed")
    return RegisteredAssumptionBundle(
        assumption_set_id, assumption_version, fingerprint, False
    )


def _timestamp_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ScenarioServingError("governance event recorded_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _approval_fingerprint(
    *,
    authority: ScenarioAuthority,
    assumption_set_id: str,
    assumption_version: str,
    assumption_semantic_fingerprint: str,
    event_type: str,
    actor: str,
    decision_reference: str,
    prior_event_id: int | None,
    recorded_at: datetime,
) -> str:
    return semantic_fingerprint(
        {
            "schemaVersion": "retail-forecast-scenario-assumption-approval/v1",
            "authorityScope": authority.payload(),
            "assumptionSetId": assumption_set_id,
            "assumptionVersion": assumption_version,
            "assumptionSemanticFingerprint": assumption_semantic_fingerprint,
            "eventType": event_type,
            "actor": actor,
            "decisionReference": decision_reference,
            "priorEventId": prior_event_id,
            "recordedAt": _timestamp_text(recorded_at),
        },
        volatile_pointers=(),
    )


def append_assumption_approval_event(
    postgres_dsn: str,
    *,
    authority: ScenarioAuthority,
    assumption_set_id: str,
    assumption_version: str,
    event_type: str,
    actor: str,
    decision_reference: str,
    prior_event_id: int | None,
    recorded_at: datetime,
) -> AssumptionApproval:
    """Append one auditable lifecycle event; never mutate a prior decision."""

    _require(
        event_type in {"candidate", "approved", "superseded", "rejected"},
        "unknown assumption approval event type",
    )
    _require(bool(actor) and bool(decision_reference), "approval actor/decision are required")
    _require(recorded_at.tzinfo is not None, "approval recorded_at must be timezone-aware")
    with psycopg.connect(postgres_dsn) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT semantic_fingerprint, bundle_payload
                    FROM {SERVING_SCHEMA}.forecast_scenario_assumption_sets
                    WHERE assumption_set_id = %s AND assumption_version = %s
                    """,
                    (assumption_set_id, assumption_version),
                )
                row = cursor.fetchone()
                _require(row is not None, "assumption bundle is not registered")
                fingerprint = str(row[0])
                if event_type == "approved":
                    _require(
                        may_receive_serving_approval(row[1]),
                        "this bundle class cannot receive serving approval",
                    )
                approval_fingerprint = _approval_fingerprint(
                    authority=authority,
                    assumption_set_id=assumption_set_id,
                    assumption_version=assumption_version,
                    assumption_semantic_fingerprint=fingerprint,
                    event_type=event_type,
                    actor=actor,
                    decision_reference=decision_reference,
                    prior_event_id=prior_event_id,
                    recorded_at=recorded_at,
                )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_assumption_approval_events (
                        retailer_id, tenant_id, capability, environment,
                        assumption_set_id, assumption_version,
                        assumption_semantic_fingerprint, event_type, actor,
                        decision_reference, approval_semantic_fingerprint,
                        prior_event_id, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING event_id
                    """,
                    (
                        authority.retailer_id,
                        authority.tenant_id,
                        authority.capability,
                        authority.environment,
                        assumption_set_id,
                        assumption_version,
                        fingerprint,
                        event_type,
                        actor,
                        decision_reference,
                        approval_fingerprint,
                        prior_event_id,
                        recorded_at,
                    ),
                )
                inserted = cursor.fetchone()
                assert inserted is not None
                return AssumptionApproval(int(inserted[0]), approval_fingerprint)


def effective_assumption_approval(
    cursor: psycopg.Cursor[Any],
    *,
    authority: ScenarioAuthority,
    assumption_semantic_fingerprint: str,
) -> AssumptionApproval:
    cursor.execute(
        f"""
        SELECT event_id, approval_semantic_fingerprint
        FROM {SERVING_SCHEMA}.effective_forecast_scenario_assumption_approvals
        WHERE retailer_id = %s AND tenant_id = %s
          AND capability = %s AND environment = %s
          AND assumption_semantic_fingerprint = %s
        """,
        (
            authority.retailer_id,
            authority.tenant_id,
            authority.capability,
            authority.environment,
            assumption_semantic_fingerprint,
        ),
    )
    rows = cursor.fetchall()
    _require(
        len(rows) == 1,
        "assumption bundle must have exactly one effective approved head",
    )
    return AssumptionApproval(int(rows[0][0]), str(rows[0][1]))


def load_active_forecast(
    postgres_dsn: str,
    *,
    activation_scope_fingerprint: str,
) -> ForecastAuthority:
    """Read one complete active forecast authority for offline materialization."""

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _require_schema(cursor)
            cursor.execute(
                f"SELECT count(*) FROM {SERVING_SCHEMA}.active_forecast_versions"
            )
            count_row = cursor.fetchone()
            _require(
                count_row is not None and int(count_row[0]) == 1,
                "forecast authority must contain exactly one active version",
            )
            cursor.execute(
                f"""
                SELECT forecast_run_id, version_id, decision_as_of
                FROM {SERVING_SCHEMA}.active_forecast_versions
                WHERE activation_scope_fingerprint = %s
                """,
                (activation_scope_fingerprint,),
            )
            authority_row = cursor.fetchone()
            _require(authority_row is not None, "configured forecast authority is not active")
            run_id, version_id, decision_as_of = authority_row
            cursor.execute(
                f"""
                SELECT market_id, sku_id, store_id, channel_id, dept_id, category,
                       horizon_week, target_week_start, expected_units, expected_model,
                       yhat_p50, yhat_p90, interval_available,
                       interval_unavailable_reason
                FROM {SERVING_SCHEMA}.forecast_series
                WHERE version_id = %s
                ORDER BY market_id, sku_id, store_id, channel_id, horizon_week
                """,
                (version_id,),
            )
            columns = [description.name for description in cursor.description]
            rows = cursor.fetchall()
            _require(bool(rows), "active forecast has no series rows")
            return ForecastAuthority(
                forecast_run_id=str(run_id),
                forecast_version_id=str(version_id),
                activation_scope_fingerprint=activation_scope_fingerprint,
                decision_as_of=decision_as_of,
                rows=pd.DataFrame(rows, columns=columns),
            )


def _query_frame(
    cursor: psycopg.Cursor[Any], query: str, parameters: tuple[Any, ...]
) -> pd.DataFrame:
    cursor.execute(query, parameters)
    columns = [description.name for description in cursor.description]
    return pd.DataFrame(cursor.fetchall(), columns=columns)


def _inventory_identity_is_compatible(
    *,
    forecast_version_id: str,
    inventory_decision_as_of: datetime,
    base_context: BuiltBaseContext,
) -> bool:
    actual_decision = inventory_decision_as_of
    if actual_decision.tzinfo is None:
        actual_decision = actual_decision.replace(tzinfo=timezone.utc)
    expected_decision = datetime.fromisoformat(
        base_context.manifest["scenarioDecisionAsOf"].replace("Z", "+00:00")
    )
    return (
        forecast_version_id == base_context.manifest["forecastVersion"]
        and actual_decision.astimezone(timezone.utc) == expected_decision
    )


def load_active_inventory(
    postgres_dsn: str,
    *,
    base_context: BuiltBaseContext,
) -> InventoryAuthority | None:
    """Return zero/one compatible inventory authority; ambiguity fails closed."""

    with psycopg.connect(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            _require_schema(cursor)
            cursor.execute(
                f"SELECT count(*) FROM {SERVING_SCHEMA}.active_inventory_versions"
            )
            count_row = cursor.fetchone()
            count = 0 if count_row is None else int(count_row[0])
            if count == 0:
                return None
            _require(count == 1, "inventory authority contains multiple active versions")
            cursor.execute(
                f"""
                SELECT inventory_version_id, forecast_version_id, decision_as_of
                FROM {SERVING_SCHEMA}.active_inventory_versions
                """
            )
            identity = cursor.fetchone()
            assert identity is not None
            inventory_version, forecast_version, decision_as_of = identity
            actual_decision = decision_as_of
            if actual_decision.tzinfo is None:
                actual_decision = actual_decision.replace(tzinfo=timezone.utc)
            if not _inventory_identity_is_compatible(
                forecast_version_id=str(forecast_version),
                inventory_decision_as_of=actual_decision,
                base_context=base_context,
            ):
                # Inventory is an optional extension. An active inventory authority
                # for another forecast/cutoff is therefore zero compatible rows,
                # not a failure of the independently valid base context.
                return None
            version = str(inventory_version)
            positions = _query_frame(
                cursor,
                f"""
                SELECT market_id, location_id, sku_id, atp_units
                FROM {SERVING_SCHEMA}.inventory_positions
                WHERE inventory_version_id = %s
                ORDER BY market_id, location_id, sku_id
                """,
                (version,),
            )
            allocations = _query_frame(
                cursor,
                f"""
                SELECT market_id, location_id, channel_id, sku_id,
                       allocated_units, requested_units
                FROM {SERVING_SCHEMA}.replenishment_allocations
                WHERE inventory_version_id = %s
                ORDER BY market_id, location_id, sku_id, channel_id
                """,
                (version,),
            )
            recommendations = _query_frame(
                cursor,
                f"""
                SELECT market_id, destination_location_id, sku_id,
                       order_up_to_units, reorder_point_units, lead_time_days,
                       interval_available, reason_code
                FROM {SERVING_SCHEMA}.replenishment_recommendations
                WHERE inventory_version_id = %s
                ORDER BY market_id, destination_location_id, sku_id
                """,
                (version,),
            )
            dimensions = _query_frame(
                cursor,
                f"""
                SELECT market_id, location_id, sku_id, unit_cost_minor,
                       cost_method, currency_code
                FROM {SERVING_SCHEMA}.inventory_sku_dimension
                WHERE inventory_version_id = %s
                ORDER BY market_id, location_id, sku_id
                """,
                (version,),
            )
            cursor.execute(
                f"""
                SELECT market_id, currency_code
                FROM {SERVING_SCHEMA}.inventory_market_policy
                WHERE inventory_version_id = %s
                ORDER BY market_id
                """,
                (version,),
            )
            currencies: dict[str, str] = {}
            for market, currency in cursor.fetchall():
                market_id = str(market)
                _require(
                    market_id not in currencies,
                    f"inventory market {market_id} has multiple currencies",
                )
                currencies[market_id] = str(currency)
            _require(not positions.empty, "active inventory has no position rows")
            return InventoryAuthority(
                inventory_version_id=version,
                forecast_version_id=str(forecast_version),
                decision_as_of=actual_decision,
                positions=positions,
                allocations=allocations,
                recommendations=recommendations,
                sku_dimensions=dimensions,
                currency_by_market=currencies,
            )


def materialize_base_context(
    postgres_dsn: str,
    built: BuiltBaseContext,
) -> BaseContextMaterialization:
    """Publish one immutable base context transactionally, without activating it."""

    manifest = built.manifest
    authority = manifest["authorityScope"]
    with psycopg.connect(postgres_dsn) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT base_output_content_fingerprint, children_sealed
                    FROM {SERVING_SCHEMA}.forecast_scenario_contexts
                    WHERE scenario_context_version = %s
                    """,
                    (built.scenario_context_version,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    _require(
                        existing[0] == built.base_output_content_fingerprint
                        and bool(existing[1]),
                        "existing context id has different output content",
                    )
                    cursor.execute(
                        f"SELECT count(*) FROM {SERVING_SCHEMA}.forecast_scenario_horizon_rows "
                        "WHERE scenario_context_version = %s",
                        (built.scenario_context_version,),
                    )
                    horizon_count = int(cursor.fetchone()[0])
                    cursor.execute(
                        f"SELECT count(*) FROM {SERVING_SCHEMA}.forecast_scenario_commercial_rows "
                        "WHERE scenario_context_version = %s",
                        (built.scenario_context_version,),
                    )
                    commercial_count = int(cursor.fetchone()[0])
                    _require(
                        horizon_count == len(built.horizon_rows)
                        and commercial_count == len(built.commercial_rows),
                        "existing context row counts disagree with its manifest",
                    )
                    return BaseContextMaterialization(
                        built.scenario_context_version,
                        horizon_count,
                        commercial_count,
                        True,
                    )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_contexts (
                        scenario_context_version, retailer_id, tenant_id,
                        capability, environment, authority_scope_fingerprint,
                        forecast_activation_scope_fingerprint, forecast_version_id,
                        scenario_decision_as_of, assumption_set_id,
                        assumption_version, assumption_semantic_fingerprint,
                        assumption_approval_event_id,
                        assumption_approval_semantic_fingerprint,
                        price_snapshot_content_fingerprint, context_schema_version,
                        materializer_version, base_output_content_fingerprint, manifest
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        built.scenario_context_version,
                        authority["retailerId"],
                        authority["tenantId"],
                        authority["capability"],
                        authority["environment"],
                        built.authority_scope_fingerprint,
                        manifest["forecastActivationScopeFingerprint"],
                        manifest["forecastVersion"],
                        manifest["scenarioDecisionAsOf"],
                        manifest["assumptionSetId"],
                        manifest["assumptionVersion"],
                        manifest["approvedAssumptionBundleFingerprint"],
                        manifest["assumptionApprovalEventId"],
                        manifest["assumptionApprovalSemanticFingerprint"],
                        manifest["priceSnapshotContentFingerprint"],
                        manifest["schemaVersion"],
                        manifest["materializerVersion"],
                        built.base_output_content_fingerprint,
                        Jsonb(manifest),
                    ),
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_horizon_rows (
                        scenario_context_version, market_id, sku_id, store_id,
                        channel_id, dept_id, category, horizon_week,
                        target_week_start, expected_units, expected_model,
                        p50_units, p90_units, interval_available,
                        interval_reason_code
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            built.scenario_context_version,
                            row["marketId"], row["skuId"], row["storeId"],
                            row["channelId"], row["deptId"], row["category"],
                            row["horizonWeek"], row["targetWeekStart"],
                            row["expectedUnits"], row["expectedModel"],
                            row["p50Units"], row["p90Units"],
                            row["intervalAvailable"], row["intervalReasonCode"],
                        )
                        for row in built.horizon_rows
                    ],
                )
                commercial_columns = (
                    "marketId", "skuId", "storeId", "channelId", "deptId",
                    "currencyCode", "priceAvailable", "unitPriceMinor", "priceBasis",
                    "priceUnavailableReason", "sourceRowIdentity", "sourceRowVersion",
                    "sourceObservationDate", "sourceKnownAsOf",
                    "sourceRowContentFingerprint", "fallbackPopulationCount",
                    "fallbackObservationStart", "fallbackObservationEnd",
                    "fallbackMaxKnownAsOf", "fallbackMemberSetContentFingerprint",
                    "sourceCutoff", "freshnessStatus", "freshnessReasonCode",
                    "observedSupportLowMinor", "observedSupportHighMinor",
                    "observedSupportStart", "observedSupportEnd",
                    "observedSupportContentFingerprint", "baselinePriceTier",
                    "tierResolutionReason", "assumedBeta",
                    "competitorStockoutSensitivity",
                    "competitorPromotionSensitivity", "weatherPositiveSensitivity",
                    "weatherNegativeSensitivity", "coefficientContentFingerprint",
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_commercial_rows (
                        scenario_context_version, market_id, sku_id, store_id,
                        channel_id, dept_id, currency_code, price_available,
                        unit_price_minor, price_basis, price_unavailable_reason,
                        source_row_identity, source_row_version,
                        source_observation_date, source_known_as_of,
                        source_row_content_fingerprint, fallback_population_count,
                        fallback_observation_start, fallback_observation_end,
                        fallback_max_known_as_of,
                        fallback_member_set_content_fingerprint, source_cutoff,
                        freshness_status, freshness_reason_code,
                        observed_support_low_minor, observed_support_high_minor,
                        observed_support_start, observed_support_end,
                        observed_support_content_fingerprint, baseline_price_tier,
                        tier_resolution_reason, assumed_beta,
                        competitor_stockout_sensitivity,
                        competitor_promotion_sensitivity,
                        weather_positive_sensitivity, weather_negative_sensitivity,
                        coefficient_content_fingerprint
                    ) VALUES ({', '.join(['%s'] * 37)})
                    """,
                    [
                        (
                            built.scenario_context_version,
                            *(row[column] for column in commercial_columns),
                        )
                        for row in built.commercial_rows
                    ],
                )
                cursor.execute(
                    f"""
                    UPDATE {SERVING_SCHEMA}.forecast_scenario_contexts
                    SET children_sealed = TRUE
                    WHERE scenario_context_version = %s AND NOT children_sealed
                    """,
                    (built.scenario_context_version,),
                )
                _require(cursor.rowcount == 1, "scenario context could not be sealed")
    return BaseContextMaterialization(
        built.scenario_context_version,
        len(built.horizon_rows),
        len(built.commercial_rows),
        False,
    )


def activate_base_context(
    postgres_dsn: str,
    *,
    authority: ScenarioAuthority,
    scenario_context_version: str,
    actor: str,
    decision_reference: str,
    recorded_at: datetime,
) -> BaseContextActivation:
    """Atomically replace context authority and retire its prior bundle approval.

    Product/quant approval remains a separate prerequisite. This operation is not
    called by materialization and is deliberately explicit. When the replacement
    uses a different assumption fingerprint, the previous context's approval head
    is superseded in this same transaction; there is no externally visible window
    with a new context and two serving-effective assumption approvals.
    """

    _require(
        bool(actor) and bool(decision_reference),
        "activation actor and decision reference are required",
    )
    _require(recorded_at.tzinfo is not None, "activation recorded_at must be timezone-aware")
    with psycopg.connect(postgres_dsn) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _require_schema(cursor)
                lock_key = "\x1f".join(
                    (
                        authority.retailer_id,
                        authority.tenant_id,
                        authority.capability,
                        authority.environment,
                    )
                )
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_key,),
                )
                cursor.execute(
                    f"""
                    SELECT event_id, scenario_context_version, event_type,
                           authority_scope_fingerprint
                    FROM {SERVING_SCHEMA}.forecast_scenario_context_activation_heads
                    WHERE retailer_id = %s AND tenant_id = %s
                      AND capability = %s AND environment = %s
                    """,
                    (
                        authority.retailer_id,
                        authority.tenant_id,
                        authority.capability,
                        authority.environment,
                    ),
                )
                heads = cursor.fetchall()
                _require(len(heads) <= 1, "scenario context authority has competing heads")
                cursor.execute(
                    f"""
                    SELECT authority_scope_fingerprint,
                           assumption_set_id, assumption_version,
                           assumption_semantic_fingerprint,
                           assumption_approval_event_id, children_sealed
                    FROM {SERVING_SCHEMA}.forecast_scenario_contexts
                    WHERE scenario_context_version = %s
                      AND retailer_id = %s AND tenant_id = %s
                      AND capability = %s AND environment = %s
                    """,
                    (
                        scenario_context_version,
                        authority.retailer_id,
                        authority.tenant_id,
                        authority.capability,
                        authority.environment,
                    ),
                )
                context_row = cursor.fetchone()
                _require(context_row is not None, "scenario context is not materialized")
                _require(bool(context_row[5]), "scenario context children are not sealed")
                scope_fingerprint = str(context_row[0])
                if heads and heads[0][1] == scenario_context_version and heads[0][2] == "active":
                    return BaseContextActivation(
                        int(heads[0][0]), scenario_context_version, True
                    )
                prior_event_id: int | None = None
                prior_approval: tuple[Any, ...] | None = None
                if heads:
                    _require(
                        heads[0][3] == scope_fingerprint,
                        "authority scope fingerprint changed within one activation chain",
                    )
                    prior_event_id = int(heads[0][0])
                    if heads[0][2] == "active":
                        cursor.execute(
                            f"""
                            SELECT approval.event_id, approval.assumption_set_id,
                                   approval.assumption_version,
                                   approval.assumption_semantic_fingerprint
                            FROM {SERVING_SCHEMA}.forecast_scenario_contexts AS prior_context
                            JOIN {SERVING_SCHEMA}.forecast_scenario_assumption_approval_events AS approval
                              ON approval.event_id = prior_context.assumption_approval_event_id
                            WHERE prior_context.scenario_context_version = %s
                            """,
                            (heads[0][1],),
                        )
                        prior_approval = cursor.fetchone()
                        _require(
                            prior_approval is not None,
                            "active scenario context has no approval lineage",
                        )
                        cursor.execute(
                            f"""
                            INSERT INTO {SERVING_SCHEMA}.forecast_scenario_context_activation_events (
                                retailer_id, tenant_id, capability, environment,
                                authority_scope_fingerprint, scenario_context_version,
                                event_type, actor, decision_reference,
                                prior_event_id, recorded_at
                            ) VALUES (%s, %s, %s, %s, %s, %s, 'superseded', %s, %s, %s, %s)
                            RETURNING event_id
                            """,
                            (
                                authority.retailer_id, authority.tenant_id,
                                authority.capability, authority.environment,
                                scope_fingerprint, heads[0][1], actor,
                                decision_reference, prior_event_id, recorded_at,
                            ),
                        )
                        prior_event_id = int(cursor.fetchone()[0])
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_context_activation_events (
                        retailer_id, tenant_id, capability, environment,
                        authority_scope_fingerprint, scenario_context_version,
                        event_type, actor, decision_reference,
                        prior_event_id, recorded_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, %s)
                    RETURNING event_id
                    """,
                    (
                        authority.retailer_id, authority.tenant_id,
                        authority.capability, authority.environment,
                        scope_fingerprint, scenario_context_version, actor,
                        decision_reference, prior_event_id, recorded_at,
                    ),
                )
                event_id = int(cursor.fetchone()[0])
                if (
                    prior_approval is not None
                    and str(prior_approval[3]) != str(context_row[3])
                ):
                    old_event_id = int(prior_approval[0])
                    cursor.execute(
                        f"""
                        SELECT event_id, event_type
                        FROM {SERVING_SCHEMA}.forecast_scenario_assumption_approval_heads
                        WHERE retailer_id = %s AND tenant_id = %s
                          AND capability = %s AND environment = %s
                          AND assumption_semantic_fingerprint = %s
                        """,
                        (
                            authority.retailer_id,
                            authority.tenant_id,
                            authority.capability,
                            authority.environment,
                            str(prior_approval[3]),
                        ),
                    )
                    approval_heads = cursor.fetchall()
                    _require(
                        len(approval_heads) == 1
                        and int(approval_heads[0][0]) == old_event_id
                        and str(approval_heads[0][1]) == "approved",
                        "prior context approval is not its effective approved head",
                    )
                    approval_fingerprint = _approval_fingerprint(
                        authority=authority,
                        assumption_set_id=str(prior_approval[1]),
                        assumption_version=str(prior_approval[2]),
                        assumption_semantic_fingerprint=str(prior_approval[3]),
                        event_type="superseded",
                        actor=actor,
                        decision_reference=decision_reference,
                        prior_event_id=old_event_id,
                        recorded_at=recorded_at,
                    )
                    cursor.execute(
                        f"""
                        INSERT INTO {SERVING_SCHEMA}.forecast_scenario_assumption_approval_events (
                            retailer_id, tenant_id, capability, environment,
                            assumption_set_id, assumption_version,
                            assumption_semantic_fingerprint, event_type, actor,
                            decision_reference, approval_semantic_fingerprint,
                            prior_event_id, recorded_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, 'superseded',
                            %s, %s, %s, %s, %s
                        )
                        """,
                        (
                            authority.retailer_id,
                            authority.tenant_id,
                            authority.capability,
                            authority.environment,
                            str(prior_approval[1]),
                            str(prior_approval[2]),
                            str(prior_approval[3]),
                            actor,
                            decision_reference,
                            approval_fingerprint,
                            old_event_id,
                            recorded_at,
                        ),
                    )
                return BaseContextActivation(event_id, scenario_context_version, False)


def materialize_inventory_extension(
    postgres_dsn: str,
    built: BuiltInventoryExtension,
) -> InventoryExtensionMaterialization:
    """Publish an immutable optional extension without changing active authority."""

    manifest = built.manifest
    with psycopg.connect(postgres_dsn) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    f"""
                    SELECT inventory_output_content_fingerprint, children_sealed
                    FROM {SERVING_SCHEMA}.forecast_scenario_inventory_extensions
                    WHERE inventory_extension_version = %s
                    """,
                    (built.inventory_extension_version,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    _require(
                        existing[0] == built.inventory_output_content_fingerprint
                        and bool(existing[1]),
                        "existing inventory extension id has different output content",
                    )
                    cursor.execute(
                        f"SELECT count(*) FROM {SERVING_SCHEMA}.forecast_scenario_inventory_series_rows "
                        "WHERE inventory_extension_version = %s",
                        (built.inventory_extension_version,),
                    )
                    series_count = int(cursor.fetchone()[0])
                    cursor.execute(
                        f"SELECT count(*) FROM {SERVING_SCHEMA}.forecast_scenario_inventory_node_rows "
                        "WHERE inventory_extension_version = %s",
                        (built.inventory_extension_version,),
                    )
                    node_count = int(cursor.fetchone()[0])
                    _require(
                        series_count == len(built.series_rows)
                        and node_count == len(built.node_rows),
                        "existing inventory extension row counts disagree",
                    )
                    return InventoryExtensionMaterialization(
                        built.inventory_extension_version,
                        series_count,
                        node_count,
                        True,
                    )
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_inventory_extensions (
                        inventory_extension_version, scenario_context_version,
                        inventory_version_id, extension_schema_version,
                        materializer_version, inventory_output_content_fingerprint,
                        manifest
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        built.inventory_extension_version,
                        manifest["baseScenarioContextVersion"],
                        manifest["inventoryVersion"],
                        manifest["schemaVersion"],
                        manifest["materializerVersion"],
                        built.inventory_output_content_fingerprint,
                        Jsonb(manifest),
                    ),
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_inventory_series_rows (
                        inventory_extension_version, market_id, sku_id, store_id,
                        channel_id, allocated_atp_units, requested_units
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            built.inventory_extension_version,
                            row["marketId"], row["skuId"], row["storeId"],
                            row["channelId"], row["allocatedAtpUnits"],
                            row["requestedUnits"],
                        )
                        for row in built.series_rows
                    ],
                )
                node_columns = (
                    "marketId", "skuId", "locationId", "currencyCode",
                    "replenishmentAvailable", "orderUpToUnits", "reorderPointUnits",
                    "replenishmentReasonCode", "nodeAtpUnits", "allocatedAtpUnits",
                    "residualAtpUnits", "unitCostMinor", "unitCostBasis",
                    "unitCostReasonCode", "unitCostContentFingerprint",
                    "protectionAvailable", "leadTimeDays", "reviewPeriodDays",
                    "protectionDays", "protectionReasonCode",
                )
                cursor.executemany(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_inventory_node_rows (
                        inventory_extension_version, market_id, sku_id, location_id,
                        currency_code, replenishment_available, order_up_to_units,
                        reorder_point_units, replenishment_reason_code, node_atp_units,
                        allocated_atp_units, residual_atp_units, unit_cost_minor,
                        unit_cost_basis, unit_cost_reason_code,
                        unit_cost_content_fingerprint, protection_available,
                        lead_time_days, review_period_days, protection_days,
                        protection_reason_code
                    ) VALUES ({', '.join(['%s'] * 21)})
                    """,
                    [
                        (
                            built.inventory_extension_version,
                            *(row[column] for column in node_columns),
                        )
                        for row in built.node_rows
                    ],
                )
                cursor.execute(
                    f"""
                    UPDATE {SERVING_SCHEMA}.forecast_scenario_inventory_extensions
                    SET children_sealed = TRUE
                    WHERE inventory_extension_version = %s AND NOT children_sealed
                    """,
                    (built.inventory_extension_version,),
                )
                _require(
                    cursor.rowcount == 1,
                    "scenario inventory extension could not be sealed",
                )
    return InventoryExtensionMaterialization(
        built.inventory_extension_version,
        len(built.series_rows),
        len(built.node_rows),
        False,
    )


def activate_inventory_extension(
    postgres_dsn: str,
    *,
    scenario_context_version: str,
    inventory_extension_version: str,
    actor: str,
    decision_reference: str,
    recorded_at: datetime,
) -> InventoryExtensionActivation:
    """Explicitly append the optional-extension activation chain."""

    _require(
        bool(actor) and bool(decision_reference),
        "inventory extension activation actor and decision reference are required",
    )
    _require(
        recorded_at.tzinfo is not None,
        "inventory extension activation recorded_at must be timezone-aware",
    )
    with psycopg.connect(postgres_dsn) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                _require_schema(cursor)
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    ("scenario-inventory\x1f" + scenario_context_version,),
                )
                cursor.execute(
                    f"""
                    SELECT event_id, inventory_extension_version, event_type
                    FROM {SERVING_SCHEMA}.forecast_scenario_inventory_activation_heads
                    WHERE scenario_context_version = %s
                    """,
                    (scenario_context_version,),
                )
                heads = cursor.fetchall()
                _require(len(heads) <= 1, "inventory extension has competing heads")
                cursor.execute(
                    f"""
                    SELECT children_sealed
                    FROM {SERVING_SCHEMA}.forecast_scenario_inventory_extensions
                    WHERE scenario_context_version = %s
                      AND inventory_extension_version = %s
                    """,
                    (scenario_context_version, inventory_extension_version),
                )
                extension_row = cursor.fetchone()
                _require(
                    extension_row is not None and bool(extension_row[0]),
                    "inventory extension is not materialized and sealed",
                )
                if heads and heads[0][1] == inventory_extension_version and heads[0][2] == "active":
                    return InventoryExtensionActivation(
                        int(heads[0][0]), inventory_extension_version, True
                    )
                prior_event_id: int | None = None
                if heads:
                    prior_event_id = int(heads[0][0])
                    if heads[0][2] == "active":
                        cursor.execute(
                            f"""
                            INSERT INTO {SERVING_SCHEMA}.forecast_scenario_inventory_activation_events (
                                scenario_context_version, inventory_extension_version,
                                event_type, actor, decision_reference,
                                prior_event_id, recorded_at
                            ) VALUES (%s, %s, 'superseded', %s, %s, %s, %s)
                            RETURNING event_id
                            """,
                            (
                                scenario_context_version, heads[0][1], actor,
                                decision_reference, prior_event_id, recorded_at,
                            ),
                        )
                        prior_event_id = int(cursor.fetchone()[0])
                cursor.execute(
                    f"""
                    INSERT INTO {SERVING_SCHEMA}.forecast_scenario_inventory_activation_events (
                        scenario_context_version, inventory_extension_version,
                        event_type, actor, decision_reference,
                        prior_event_id, recorded_at
                    ) VALUES (%s, %s, 'active', %s, %s, %s, %s)
                    RETURNING event_id
                    """,
                    (
                        scenario_context_version, inventory_extension_version,
                        actor, decision_reference, prior_event_id, recorded_at,
                    ),
                )
                event_id = int(cursor.fetchone()[0])
                return InventoryExtensionActivation(
                    event_id, inventory_extension_version, False
                )
