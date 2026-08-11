"""Build the immutable base half of a Forecast Scenario v1 context.

This module is pure: PostgreSQL and DuckDB reads happen outside it, and it emits
normalized records plus non-circular content identities. Request-time Go code
will consume these rows; it never reopens canonical files or reruns a pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Final, Mapping

import pandas as pd
from retail_contracts.fingerprint import (
    canonical_decimal_string,
    semantic_fingerprint,
)
from retail_contracts.scenario_assumptions import (
    scenario_assumption_fingerprint,
    validate_scenario_assumption_bundle,
)

from retail_ml.inventory_run.price_resolution import PriceEvidence, PriceIndex

CONTEXT_SCHEMA: Final[str] = "retail-forecast-scenario-context/v1"
MATERIALIZER_VERSION: Final[str] = "retail-forecast-scenario-materializer/v1"
OUTPUT_SCHEMA: Final[str] = "retail-forecast-scenario-base-output/v1"
INVENTORY_SCHEMA: Final[str] = "retail-forecast-scenario-inventory/v1"
INVENTORY_OUTPUT_SCHEMA: Final[str] = (
    "retail-forecast-scenario-inventory-output/v1"
)
SUPPORT_SCHEMA: Final[str] = "retail-forecast-scenario-price-support/v1"
AUTHORITY_SCOPE_SCHEMA: Final[str] = "retail-scenario-authority-scope/v1"
FINGERPRINT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class ScenarioContextBuildError(ValueError):
    """Inputs cannot produce a complete, immutable base context."""


@dataclass(frozen=True)
class ScenarioAuthority:
    retailer_id: str
    tenant_id: str
    capability: str
    environment: str

    def __post_init__(self) -> None:
        if self.capability != "forecast_scenario_v1":
            raise ScenarioContextBuildError(
                "scenario authority capability must be forecast_scenario_v1"
            )
        if not all(
            isinstance(value, str) and value
            for value in (
                self.retailer_id,
                self.tenant_id,
                self.environment,
            )
        ):
            raise ScenarioContextBuildError("scenario authority scope is incomplete")

    def payload(self) -> dict[str, str]:
        return {
            "schemaVersion": AUTHORITY_SCOPE_SCHEMA,
            "retailerId": self.retailer_id,
            "tenantId": self.tenant_id,
            "capability": self.capability,
            "environment": self.environment,
        }


@dataclass(frozen=True)
class AssumptionApproval:
    event_id: int
    semantic_fingerprint: str

    def __post_init__(self) -> None:
        if self.event_id < 1 or not FINGERPRINT_PATTERN.fullmatch(
            self.semantic_fingerprint
        ):
            raise ScenarioContextBuildError("assumption approval identity is invalid")


@dataclass(frozen=True)
class BuiltBaseContext:
    scenario_context_version: str
    authority_scope_fingerprint: str
    base_output_content_fingerprint: str
    manifest: dict[str, Any]
    horizon_rows: tuple[dict[str, Any], ...]
    commercial_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class BuiltInventoryExtension:
    inventory_extension_version: str
    inventory_output_content_fingerprint: str
    manifest: dict[str, Any]
    series_rows: tuple[dict[str, Any], ...]
    node_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _PriceSupportObservation:
    location_id: str
    channel_id: str
    currency_code: str
    observation_date: date
    known_as_of: datetime
    known_as_of_text: str
    sales_version: int
    unit_price_minor: int


@dataclass(frozen=True)
class _PriceSupportIndex:
    exact: dict[tuple[str, str, str, str], list[_PriceSupportObservation]]
    fallback: dict[tuple[str, str], list[_PriceSupportObservation]]

    @classmethod
    def build(cls, history: pd.DataFrame) -> _PriceSupportIndex:
        required = (
            "market_id",
            "location_id",
            "channel_id",
            "sku_id",
            "currency_code",
            "observation_date",
            "known_as_of",
            "sales_version",
            "unit_price_minor",
        )
        missing = set(required) - set(history.columns)
        if missing:
            raise ScenarioContextBuildError(
                f"price history lacks columns {sorted(missing)}"
            )
        exact: dict[
            tuple[str, str, str, str], list[_PriceSupportObservation]
        ] = {}
        fallback: dict[tuple[str, str], list[_PriceSupportObservation]] = {}
        for raw in history.loc[:, required].itertuples(index=False, name=None):
            (
                market_id,
                location_id,
                channel_id,
                sku_id,
                currency_code,
                observation_value,
                known_value,
                sales_version,
                unit_price_minor,
            ) = raw
            known = pd.Timestamp(known_value)
            if known.tzinfo is None:
                known = known.tz_localize(timezone.utc)
            else:
                known = known.tz_convert(timezone.utc)
            known_datetime = known.to_pydatetime()
            observation = _PriceSupportObservation(
                location_id=str(location_id),
                channel_id=str(channel_id),
                currency_code=str(currency_code),
                observation_date=pd.Timestamp(observation_value).date(),
                known_as_of=known_datetime,
                known_as_of_text=known.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                ),
                sales_version=int(sales_version),
                unit_price_minor=int(unit_price_minor),
            )
            market = str(market_id)
            sku = str(sku_id)
            exact.setdefault(
                (market, observation.location_id, sku, observation.channel_id), []
            ).append(observation)
            fallback.setdefault((market, sku), []).append(observation)
        return cls(exact=exact, fallback=fallback)


def _decimal_text(value: Any, *, context: str, minimum: str = "0") -> str:
    if value is None or value is pd.NA or pd.isna(value):
        raise ScenarioContextBuildError(f"{context} is missing")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ScenarioContextBuildError(f"{context} is not numeric") from exc
    if not decimal_value.is_finite() or decimal_value < Decimal(minimum):
        raise ScenarioContextBuildError(
            f"{context} must be finite and >= {minimum}"
        )
    return canonical_decimal_string(decimal_value)


def _timestamp_text(value: datetime, *, context: str) -> str:
    if not isinstance(value, datetime):
        raise ScenarioContextBuildError(f"{context} must be a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _date_text(value: Any, *, context: str) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    try:
        return pd.Timestamp(value).date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ScenarioContextBuildError(f"{context} is not a date") from exc


def _required_forecast_columns(frame: pd.DataFrame) -> None:
    required = {
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "dept_id",
        "category",
        "horizon_week",
        "target_week_start",
        "expected_units",
        "expected_model",
        "yhat_p50",
        "yhat_p90",
        "interval_available",
        "interval_unavailable_reason",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ScenarioContextBuildError(
            f"forecast rows lack columns {sorted(missing)}"
        )
    if frame.empty:
        raise ScenarioContextBuildError("forecast context population is empty")


def _normalized_horizon_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    _required_forecast_columns(frame)
    rows: list[dict[str, Any]] = []
    keys: set[tuple[str, str, str, str, int]] = set()
    for source in frame.to_dict(orient="records"):
        horizon = int(source["horizon_week"])
        if not 1 <= horizon <= 26:
            raise ScenarioContextBuildError(f"horizon {horizon} is outside 1..26")
        key = (
            str(source["market_id"]),
            str(source["sku_id"]),
            str(source["store_id"]),
            str(source["channel_id"]),
            horizon,
        )
        if key in keys:
            raise ScenarioContextBuildError(f"duplicate forecast horizon row {key}")
        keys.add(key)
        expected = _decimal_text(source["expected_units"], context=f"{key}.expected")
        p50 = _decimal_text(source["yhat_p50"], context=f"{key}.p50")
        available = bool(source["interval_available"])
        p90_value = source["yhat_p90"]
        reason_value = source["interval_unavailable_reason"]
        if available:
            p90 = _decimal_text(p90_value, context=f"{key}.p90")
            if Decimal(p90) < Decimal(p50) or (
                reason_value is not None and not pd.isna(reason_value)
            ):
                raise ScenarioContextBuildError(f"interval truth table fails for {key}")
            reason = None
        else:
            if p90_value is not None and not pd.isna(p90_value):
                raise ScenarioContextBuildError(f"withheld interval has P90 for {key}")
            if reason_value is None or pd.isna(reason_value) or not str(reason_value):
                raise ScenarioContextBuildError(f"withheld interval lacks reason for {key}")
            p90 = None
            reason = str(reason_value)
        rows.append(
            {
                "marketId": key[0],
                "skuId": key[1],
                "storeId": key[2],
                "channelId": key[3],
                "deptId": str(source["dept_id"]),
                "category": str(source["category"]),
                "horizonWeek": horizon,
                "targetWeekStart": _date_text(
                    source["target_week_start"], context=f"{key}.targetWeekStart"
                ),
                "expectedUnits": expected,
                "expectedModel": str(source["expected_model"]),
                "p50Units": p50,
                "p90Units": p90,
                "intervalAvailable": available,
                "intervalReasonCode": reason,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            row["marketId"],
            row["skuId"],
            row["storeId"],
            row["channelId"],
            row["horizonWeek"],
        ),
    )


def _support_members(
    history: _PriceSupportIndex,
    *,
    market_id: str,
    location_id: str,
    sku_id: str,
    channel_id: str,
    exact: bool,
    start: date,
    end: date,
    known_cutoff: datetime,
    currency_code: str,
) -> list[dict[str, Any]]:
    observations = (
        history.exact.get((market_id, location_id, sku_id, channel_id), ())
        if exact
        else history.fallback.get((market_id, sku_id), ())
    )
    members: list[dict[str, Any]] = []
    for observation in observations:
        if observation.currency_code != currency_code:
            raise ScenarioContextBuildError(
                f"price support for {(market_id, location_id, sku_id, channel_id)} "
                f"uses {observation.currency_code}, not {currency_code}"
            )
        if not start <= observation.observation_date <= end:
            continue
        if observation.unit_price_minor <= 0:
            continue
        if observation.known_as_of > known_cutoff:
            raise ScenarioContextBuildError(
                f"price support for {(market_id, location_id, sku_id, channel_id)} "
                "contains future-known evidence"
            )
        members.append(
            {
                "marketId": market_id,
                "locationId": observation.location_id,
                "channelId": observation.channel_id,
                "skuId": sku_id,
                "currencyCode": observation.currency_code,
                "observationDate": observation.observation_date.isoformat(),
                "knownAsOf": observation.known_as_of_text,
                "salesVersion": observation.sales_version,
                "unitPriceMinor": observation.unit_price_minor,
            }
        )
    return sorted(
        members,
        key=lambda member: (
            member["locationId"],
            member["channelId"],
            member["observationDate"],
            member["salesVersion"],
            member["knownAsOf"],
        ),
    )


def _market_rules(bundle: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {str(rule["marketId"]): rule for rule in bundle["marketCurrencyRules"]}


def _tier_for(
    bundle: Mapping[str, Any],
    *,
    market_id: str,
    dept_id: str,
    price_minor: int,
) -> Mapping[str, Any] | None:
    matches = [
        tier
        for tier in bundle["tierCoefficients"]
        if tier["marketId"] == market_id
        and tier["deptId"] == dept_id
        and price_minor >= int(tier["lowerPriceMinor"])
        and (
            tier["upperPriceMinor"] is None
            or price_minor < int(tier["upperPriceMinor"])
        )
    ]
    if len(matches) > 1:
        raise ScenarioContextBuildError(
            f"ambiguous baseline price tier for {(market_id, dept_id, price_minor)}"
        )
    return matches[0] if matches else None


def _commercial_row(
    *,
    series: tuple[str, str, str, str, str],
    decision_date: date,
    decision_cutoff: datetime,
    source_cutoff: str,
    evidence: PriceEvidence | None,
    price_history: _PriceSupportIndex,
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    market_id, sku_id, store_id, channel_id, dept_id = series
    rule = _market_rules(bundle).get(market_id)
    if rule is None:
        raise ScenarioContextBuildError(f"no assumption market rule for {market_id}")
    currency = str(rule["currencyCode"])
    common: dict[str, Any] = {
        "marketId": market_id,
        "skuId": sku_id,
        "storeId": store_id,
        "channelId": channel_id,
        "deptId": dept_id,
        "currencyCode": currency,
        "sourceCutoff": source_cutoff,
    }
    if evidence is None:
        return {
            **common,
            "priceAvailable": False,
            "unitPriceMinor": None,
            "priceBasis": None,
            "priceUnavailableReason": "PRICE_UNAVAILABLE",
            "sourceRowIdentity": None,
            "sourceRowVersion": None,
            "sourceObservationDate": None,
            "sourceKnownAsOf": None,
            "sourceRowContentFingerprint": None,
            "fallbackPopulationCount": None,
            "fallbackObservationStart": None,
            "fallbackObservationEnd": None,
            "fallbackMaxKnownAsOf": None,
            "fallbackMemberSetContentFingerprint": None,
            "freshnessStatus": "unavailable",
            "freshnessReasonCode": "PRICE_UNAVAILABLE",
            "observedSupportLowMinor": None,
            "observedSupportHighMinor": None,
            "observedSupportStart": None,
            "observedSupportEnd": None,
            "observedSupportContentFingerprint": None,
            "baselinePriceTier": None,
            "tierResolutionReason": "PRICE_UNAVAILABLE",
            "assumedBeta": None,
            "competitorStockoutSensitivity": None,
            "competitorPromotionSensitivity": None,
            "weatherPositiveSensitivity": None,
            "weatherNegativeSensitivity": None,
            "coefficientContentFingerprint": None,
        }
    if not evidence.provenance_complete:
        raise ScenarioContextBuildError(
            f"price evidence for {series[:4]} lacks required provenance"
        )
    if evidence.currency_code != currency:
        raise ScenarioContextBuildError(
            f"price evidence for {series[:4]} uses {evidence.currency_code}, not {currency}"
        )
    observation_end_text = (
        evidence.observation_date
        if evidence.price_basis == "latest_realized_exact"
        else evidence.fallback_observation_end
    )
    assert observation_end_text is not None
    observation_end = date.fromisoformat(observation_end_text)
    if observation_end > decision_date:
        raise ScenarioContextBuildError(f"price evidence for {series[:4]} is future-known")
    known_text = (
        evidence.known_as_of
        if evidence.price_basis == "latest_realized_exact"
        else evidence.fallback_max_known_as_of
    )
    assert known_text is not None
    known_as_of = pd.Timestamp(known_text)
    if known_as_of.tzinfo is None:
        known_as_of = known_as_of.tz_localize(timezone.utc)
    else:
        known_as_of = known_as_of.tz_convert(timezone.utc)
    if known_as_of.to_pydatetime() > decision_cutoff:
        raise ScenarioContextBuildError(
            f"price evidence for {series[:4]} is known after the decision cutoff"
        )
    freshness_days = int(rule["priceFreshnessDays"])
    fresh = decision_date - observation_end <= timedelta(days=freshness_days)
    support_days = int(rule["observedSupportWindowDays"])
    support_start = decision_date - timedelta(days=support_days - 1)
    members = _support_members(
        price_history,
        market_id=market_id,
        location_id=store_id,
        sku_id=sku_id,
        channel_id=channel_id,
        exact=evidence.price_basis == "latest_realized_exact",
        start=support_start,
        end=decision_date,
        known_cutoff=decision_cutoff,
        currency_code=currency,
    )
    if members:
        support_fingerprint = semantic_fingerprint(
            {
                "schemaVersion": SUPPORT_SCHEMA,
                "marketId": market_id,
                "skuId": sku_id,
                "basis": evidence.price_basis,
                "windowStart": support_start.isoformat(),
                "windowEnd": decision_date.isoformat(),
                "members": members,
            },
            volatile_pointers=(),
        )
        support_low = min(int(member["unitPriceMinor"]) for member in members)
        support_high = max(int(member["unitPriceMinor"]) for member in members)
        support_observed_start = min(member["observationDate"] for member in members)
        support_observed_end = max(member["observationDate"] for member in members)
    else:
        support_fingerprint = None
        support_low = None
        support_high = None
        support_observed_start = None
        support_observed_end = None

    tier: Mapping[str, Any] | None = None
    tier_reason: str | None
    if not fresh:
        tier_reason = "PRICE_STALE"
    elif not members:
        tier_reason = "PRICE_SUPPORT_UNAVAILABLE"
    else:
        tier = _tier_for(
            bundle,
            market_id=market_id,
            dept_id=dept_id,
            price_minor=evidence.unit_price_minor,
        )
        tier_reason = None if tier is not None else "PRICE_TIER_UNRESOLVED"
    coefficient_fingerprint = (
        None
        if tier is None
        else semantic_fingerprint(dict(tier), volatile_pointers=())
    )
    freshness_status = (
        "unavailable" if not members else "fresh" if fresh else "stale"
    )
    freshness_reason = (
        None
        if freshness_status == "fresh"
        else "PRICE_STALE"
        if freshness_status == "stale"
        else "PRICE_SUPPORT_UNAVAILABLE"
    )
    return {
        **common,
        "priceAvailable": True,
        "unitPriceMinor": evidence.unit_price_minor,
        "priceBasis": evidence.price_basis,
        "priceUnavailableReason": None,
        "sourceRowIdentity": evidence.source_row_identity,
        "sourceRowVersion": evidence.source_row_version,
        "sourceObservationDate": evidence.observation_date,
        "sourceKnownAsOf": evidence.known_as_of,
        "sourceRowContentFingerprint": evidence.source_row_content_fingerprint,
        "fallbackPopulationCount": evidence.fallback_population_count,
        "fallbackObservationStart": evidence.fallback_observation_start,
        "fallbackObservationEnd": evidence.fallback_observation_end,
        "fallbackMaxKnownAsOf": evidence.fallback_max_known_as_of,
        "fallbackMemberSetContentFingerprint": (
            evidence.fallback_member_set_content_fingerprint
        ),
        "freshnessStatus": freshness_status,
        "freshnessReasonCode": freshness_reason,
        "observedSupportLowMinor": support_low,
        "observedSupportHighMinor": support_high,
        "observedSupportStart": support_observed_start,
        "observedSupportEnd": support_observed_end,
        "observedSupportContentFingerprint": support_fingerprint,
        "baselinePriceTier": None if tier is None else str(tier["baselinePriceTier"]),
        "tierResolutionReason": tier_reason,
        "assumedBeta": None if tier is None else str(tier["assumedBeta"]),
        "competitorStockoutSensitivity": (
            None if tier is None else str(tier["competitorStockoutSensitivity"])
        ),
        "competitorPromotionSensitivity": (
            None if tier is None else str(tier["competitorPromotionSensitivity"])
        ),
        "weatherPositiveSensitivity": (
            None if tier is None else str(tier["weatherPositiveSensitivity"])
        ),
        "weatherNegativeSensitivity": (
            None if tier is None else str(tier["weatherNegativeSensitivity"])
        ),
        "coefficientContentFingerprint": coefficient_fingerprint,
    }


def build_base_context(
    *,
    authority: ScenarioAuthority,
    forecast_version_id: str,
    forecast_activation_scope_fingerprint: str,
    scenario_decision_as_of: datetime,
    forecast_rows: pd.DataFrame,
    price_index: PriceIndex,
    price_history: pd.DataFrame,
    assumption_bundle: Mapping[str, Any],
    approval: AssumptionApproval,
) -> BuiltBaseContext:
    """Build normalized rows and dependency-bound base-context identity."""

    validate_scenario_assumption_bundle(assumption_bundle)
    if assumption_bundle["artifactClass"] != "serving_candidate" or not assumption_bundle[
        "servingEligible"
    ]:
        raise ScenarioContextBuildError(
            "only a separately approved serving_candidate bundle may be published"
        )
    assumption_fingerprint = scenario_assumption_fingerprint(assumption_bundle)
    if price_index.snapshot_content_fingerprint is None:
        raise ScenarioContextBuildError("price snapshot lacks complete provenance")
    if not FINGERPRINT_PATTERN.fullmatch(forecast_activation_scope_fingerprint):
        raise ScenarioContextBuildError("forecast activation scope fingerprint is invalid")
    horizon_rows = _normalized_horizon_rows(forecast_rows)
    price_support_index = _PriceSupportIndex.build(price_history)
    series = sorted(
        {
            (
                row["marketId"],
                row["skuId"],
                row["storeId"],
                row["channelId"],
                row["deptId"],
            )
            for row in horizon_rows
        }
    )
    if scenario_decision_as_of.tzinfo is None:
        raise ScenarioContextBuildError(
            "scenario_decision_as_of must be timezone-aware"
        )
    normalized_decision = scenario_decision_as_of.astimezone(timezone.utc)
    decision_date = normalized_decision.date()
    decision_text = _timestamp_text(
        normalized_decision, context="scenario_decision_as_of"
    )
    commercial_rows = [
        _commercial_row(
            series=key,
            decision_date=decision_date,
            decision_cutoff=normalized_decision,
            source_cutoff=decision_text,
            evidence=price_index.resolve((key[0], key[2], key[1], key[3])),
            price_history=price_support_index,
            bundle=assumption_bundle,
        )
        for key in series
    ]
    output_fingerprint = semantic_fingerprint(
        {
            "schemaVersion": OUTPUT_SCHEMA,
            "horizonRows": horizon_rows,
            "commercialRows": commercial_rows,
        },
        volatile_pointers=(),
    )
    authority_payload = authority.payload()
    authority_fingerprint = semantic_fingerprint(
        authority_payload, volatile_pointers=()
    )
    identity_payload = {
        "schemaVersion": CONTEXT_SCHEMA,
        "authorityScope": authority_payload,
        "forecastVersion": forecast_version_id,
        "forecastActivationScopeFingerprint": forecast_activation_scope_fingerprint,
        "scenarioDecisionAsOf": decision_text,
        "approvedAssumptionBundleFingerprint": assumption_fingerprint,
        "assumptionApprovalSemanticFingerprint": approval.semantic_fingerprint,
        "priceSnapshotContentFingerprint": price_index.snapshot_content_fingerprint,
        "materializerVersion": MATERIALIZER_VERSION,
        "baseOutputContentFingerprint": output_fingerprint,
    }
    context_version = semantic_fingerprint(identity_payload, volatile_pointers=())
    manifest = {
        **identity_payload,
        "scenarioContextVersion": context_version,
        "authorityScopeFingerprint": authority_fingerprint,
        "assumptionSetId": str(assumption_bundle["assumptionSetId"]),
        "assumptionVersion": str(assumption_bundle["version"]),
        "assumptionApprovalEventId": approval.event_id,
        "rowCounts": {
            "forecastHorizon": len(horizon_rows),
            "seriesCommercial": len(commercial_rows),
        },
    }
    return BuiltBaseContext(
        scenario_context_version=context_version,
        authority_scope_fingerprint=authority_fingerprint,
        base_output_content_fingerprint=output_fingerprint,
        manifest=manifest,
        horizon_rows=tuple(horizon_rows),
        commercial_rows=tuple(commercial_rows),
    )


def _unique_records(
    frame: pd.DataFrame,
    *,
    required: set[str],
    key_fields: tuple[str, ...],
    context: str,
) -> dict[tuple[str, ...], dict[str, Any]]:
    missing = required - set(frame.columns)
    if missing:
        raise ScenarioContextBuildError(f"{context} lacks columns {sorted(missing)}")
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in frame.to_dict(orient="records"):
        key = tuple(str(row[field]) for field in key_fields)
        if key in result:
            raise ScenarioContextBuildError(f"duplicate {context} row {key}")
        result[key] = row
    return result


def build_inventory_extension(
    *,
    base_context: BuiltBaseContext,
    inventory_version_id: str,
    positions: pd.DataFrame,
    allocations: pd.DataFrame,
    recommendations: pd.DataFrame,
    sku_dimensions: pd.DataFrame,
    review_period_days_by_market: Mapping[str, int],
    currency_by_market: Mapping[str, str],
) -> BuiltInventoryExtension:
    """Build the optional ATP/order-up-to context with exact node conservation."""

    position_index = _unique_records(
        positions,
        required={"market_id", "location_id", "sku_id", "atp_units"},
        key_fields=("market_id", "location_id", "sku_id"),
        context="inventory position",
    )
    recommendation_index = _unique_records(
        recommendations,
        required={
            "market_id",
            "destination_location_id",
            "sku_id",
            "order_up_to_units",
            "reorder_point_units",
            "lead_time_days",
            "interval_available",
            "reason_code",
        },
        key_fields=("market_id", "destination_location_id", "sku_id"),
        context="replenishment recommendation",
    )
    dimension_index = _unique_records(
        sku_dimensions,
        required={
            "market_id",
            "location_id",
            "sku_id",
            "unit_cost_minor",
            "cost_method",
            "currency_code",
        },
        key_fields=("market_id", "location_id", "sku_id"),
        context="inventory SKU dimension",
    )
    allocation_index = _unique_records(
        allocations,
        required={
            "market_id",
            "location_id",
            "channel_id",
            "sku_id",
            "allocated_units",
            "requested_units",
        },
        key_fields=("market_id", "location_id", "sku_id", "channel_id"),
        context="replenishment allocation",
    )
    allocated_by_node: dict[tuple[str, str, str], int] = {}
    series_rows: list[dict[str, Any]] = []
    for key, row in allocation_index.items():
        market_id, location_id, sku_id, channel_id = key
        allocated = int(row["allocated_units"])
        requested = int(row["requested_units"])
        if allocated < 0 or requested < 0:
            raise ScenarioContextBuildError(f"negative allocation units for {key}")
        node_key = (market_id, location_id, sku_id)
        if node_key not in position_index:
            raise ScenarioContextBuildError(f"allocation {key} has no ATP position")
        allocated_by_node[node_key] = allocated_by_node.get(node_key, 0) + allocated
        series_rows.append(
            {
                "marketId": market_id,
                "skuId": sku_id,
                "storeId": location_id,
                "channelId": channel_id,
                "allocatedAtpUnits": allocated,
                "requestedUnits": requested,
            }
        )

    # ``replenishment_allocations`` contains only channels with positive
    # trailing requested demand. Absence there is therefore a governed zero,
    # not missing evidence. Materialize that zero explicitly for every base
    # forecast series at a known ATP node so request-time code never has to
    # infer a value from a missing row.
    base_series = {
        (
            str(row["marketId"]),
            str(row["storeId"]),
            str(row["skuId"]),
            str(row["channelId"]),
        )
        for row in base_context.horizon_rows
    }
    for market_id, location_id, sku_id, channel_id in sorted(base_series):
        series_key = (market_id, location_id, sku_id, channel_id)
        if series_key in allocation_index:
            continue
        if (market_id, location_id, sku_id) not in position_index:
            continue
        series_rows.append(
            {
                "marketId": market_id,
                "skuId": sku_id,
                "storeId": location_id,
                "channelId": channel_id,
                "allocatedAtpUnits": 0,
                "requestedUnits": 0,
            }
        )

    node_rows: list[dict[str, Any]] = []
    for key, position in position_index.items():
        market_id, location_id, sku_id = key
        if market_id not in review_period_days_by_market:
            raise ScenarioContextBuildError(f"no review period for market {market_id}")
        if market_id not in currency_by_market:
            raise ScenarioContextBuildError(f"no operating currency for market {market_id}")
        review_days = int(review_period_days_by_market[market_id])
        if review_days < 1:
            raise ScenarioContextBuildError(f"invalid review period for {market_id}")
        node_atp = int(position["atp_units"])
        allocated = allocated_by_node.get(key, 0)
        residual = node_atp - allocated
        if node_atp < 0 or residual < 0:
            raise ScenarioContextBuildError(
                f"ATP conservation fails for {key}: node={node_atp}, allocated={allocated}"
            )
        recommendation = recommendation_index.get(key)
        order_up_to: str | None = None
        reorder_point_value: str | None = None
        replenishment_available = False
        replenishment_reason = "REPLENISHMENT_RECOMMENDATION_UNAVAILABLE"
        lead_time: str | None = None
        protection_days: str | None = None
        protection_available = False
        protection_reason = "SUPPLY_ROUTE_UNRESOLVED"
        if recommendation is not None:
            order_value = recommendation["order_up_to_units"]
            reorder_value = recommendation["reorder_point_units"]
            if (
                bool(recommendation["interval_available"])
                and order_value is not None
                and not pd.isna(order_value)
                and reorder_value is not None
                and not pd.isna(reorder_value)
            ):
                order_up_to = _decimal_text(
                    order_value, context=f"{key}.order_up_to_units"
                )
                reorder_point_value = _decimal_text(
                    reorder_value, context=f"{key}.reorder_point_units"
                )
                replenishment_available = True
                replenishment_reason = None
            elif recommendation["reason_code"] is not None and not pd.isna(
                recommendation["reason_code"]
            ):
                replenishment_reason = str(recommendation["reason_code"])
            lead_value = recommendation["lead_time_days"]
            if lead_value is not None and not pd.isna(lead_value):
                lead_time = _decimal_text(
                    lead_value, context=f"{key}.lead_time_days", minimum="0.000000001"
                )
                protection_days = canonical_decimal_string(
                    Decimal(lead_time) + Decimal(review_days)
                )
                protection_available = True
                protection_reason = None
            elif replenishment_reason:
                protection_reason = replenishment_reason

        dimension = dimension_index.get(key)
        cost_value = None if dimension is None else dimension["unit_cost_minor"]
        if cost_value is not None and not pd.isna(cost_value) and int(cost_value) > 0:
            unit_cost_minor = int(cost_value)
            method_value = dimension["cost_method"]
            currency_value = dimension["currency_code"]
            if (
                method_value is None
                or pd.isna(method_value)
                or not str(method_value)
                or currency_value is None
                or pd.isna(currency_value)
            ):
                raise ScenarioContextBuildError(
                    f"positive unit cost for {key} lacks method/currency provenance"
                )
            unit_cost_basis = str(method_value)
            dimension_currency = str(currency_value)
            if dimension_currency != currency_by_market[market_id]:
                raise ScenarioContextBuildError(
                    f"cost currency mismatch for {key}: {dimension_currency}"
                )
            unit_cost_reason = None
            unit_cost_fingerprint = semantic_fingerprint(
                {
                    "schemaVersion": "retail-scenario-unit-cost-evidence/v1",
                    "inventoryVersion": inventory_version_id,
                    "marketId": market_id,
                    "locationId": location_id,
                    "skuId": sku_id,
                    "currencyCode": dimension_currency,
                    "unitCostMinor": unit_cost_minor,
                    "costMethod": unit_cost_basis,
                },
                volatile_pointers=(),
            )
        else:
            unit_cost_minor = None
            unit_cost_basis = None
            unit_cost_reason = "UNIT_COST_UNAVAILABLE"
            unit_cost_fingerprint = None
        node_rows.append(
            {
                "marketId": market_id,
                "skuId": sku_id,
                "locationId": location_id,
                "currencyCode": currency_by_market[market_id],
                "replenishmentAvailable": replenishment_available,
                "orderUpToUnits": order_up_to,
                "reorderPointUnits": reorder_point_value,
                "replenishmentReasonCode": replenishment_reason,
                "nodeAtpUnits": node_atp,
                "allocatedAtpUnits": allocated,
                "residualAtpUnits": residual,
                "unitCostMinor": unit_cost_minor,
                "unitCostBasis": unit_cost_basis,
                "unitCostReasonCode": unit_cost_reason,
                "unitCostContentFingerprint": unit_cost_fingerprint,
                "protectionAvailable": protection_available,
                "leadTimeDays": lead_time,
                "reviewPeriodDays": review_days,
                "protectionDays": protection_days,
                "protectionReasonCode": protection_reason,
            }
        )
    series_rows.sort(
        key=lambda row: (
            row["marketId"], row["skuId"], row["storeId"], row["channelId"]
        )
    )
    node_rows.sort(
        key=lambda row: (row["marketId"], row["skuId"], row["locationId"])
    )
    output_fingerprint = semantic_fingerprint(
        {
            "schemaVersion": INVENTORY_OUTPUT_SCHEMA,
            "seriesRows": series_rows,
            "nodeRows": node_rows,
        },
        volatile_pointers=(),
    )
    identity = {
        "schemaVersion": INVENTORY_SCHEMA,
        "baseScenarioContextVersion": base_context.scenario_context_version,
        "inventoryVersion": inventory_version_id,
        "materializerVersion": MATERIALIZER_VERSION,
        "inventoryOutputContentFingerprint": output_fingerprint,
    }
    extension_version = semantic_fingerprint(identity, volatile_pointers=())
    manifest = {
        **identity,
        "inventoryExtensionVersion": extension_version,
        "rowCounts": {
            "inventorySeries": len(series_rows),
            "inventoryNode": len(node_rows),
        },
    }
    return BuiltInventoryExtension(
        inventory_extension_version=extension_version,
        inventory_output_content_fingerprint=output_fingerprint,
        manifest=manifest,
        series_rows=tuple(series_rows),
        node_rows=tuple(node_rows),
    )
