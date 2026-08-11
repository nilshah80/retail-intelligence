"""Forecast Scenario Planning v1 assumption-bundle contract.

The checked-in bundle is deliberately a non-activatable ``synthetic_test``
fixture. Serving approval is a separate append-only database authority; loading
or fingerprinting a YAML document never turns its values into approved evidence.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .entities import load_yaml, locate_contract_root
from .fingerprint import canonical_decimal_string, semantic_fingerprint
from .money import UnknownCurrencyError, minor_exponent

SCHEMA_VERSION = "retail-forecast-scenario-assumptions/v1"
REQUIRED_PRESET_IDS = frozenset(
    {
        "expected_demand",
        "high_demand",
        "low_demand",
        "promotion_upside",
        "supply_constrained",
    }
)


class ScenarioAssumptionContractError(ValueError):
    """An assumption bundle is incomplete, ambiguous, or unsafe."""


def _exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    context: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - required
    if missing or unknown:
        raise ScenarioAssumptionContractError(
            f"{context} keys invalid: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _decimal(
    value: Any,
    *,
    context: str,
    minimum: str | None = None,
    maximum: str | None = None,
    maximum_exclusive: str | None = None,
) -> Decimal:
    if not isinstance(value, str):
        raise ScenarioAssumptionContractError(
            f"{context} must be an exact canonical decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ScenarioAssumptionContractError(
            f"{context} is not decimal text"
        ) from exc
    if (
        not result.is_finite()
        or canonical_decimal_string(value) != value
        or format(result, "f") != value
    ):
        raise ScenarioAssumptionContractError(
            f"{context} must be canonical finite plain decimal text"
        )
    if minimum is not None and result < Decimal(minimum):
        raise ScenarioAssumptionContractError(f"{context} must be >= {minimum}")
    if maximum is not None and result > Decimal(maximum):
        raise ScenarioAssumptionContractError(f"{context} must be <= {maximum}")
    if maximum_exclusive is not None and result >= Decimal(maximum_exclusive):
        raise ScenarioAssumptionContractError(
            f"{context} must be < {maximum_exclusive}"
        )
    return result


def _integer(
    value: Any,
    *,
    context: str,
    minimum: int = 0,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ScenarioAssumptionContractError(
            f"{context} must be an integer >= {minimum}"
        )
    return value


def _validate_bounds(document: Mapping[str, Any]) -> dict[str, tuple[Decimal, Decimal]]:
    bounds = document["requestBounds"]
    _exact_keys(
        bounds,
        required={
            "demandAdjustmentPct",
            "priceChangePct",
            "promotionUpliftPct",
            "competitorAvailability",
            "weatherEvent",
        },
        context="requestBounds",
    )
    result: dict[str, tuple[Decimal, Decimal]] = {}
    for field in (
        "demandAdjustmentPct",
        "priceChangePct",
        "promotionUpliftPct",
    ):
        value = bounds[field]
        if not isinstance(value, Mapping):
            raise ScenarioAssumptionContractError(f"requestBounds.{field} must map")
        _exact_keys(
            value,
            required={"minimum", "maximum"},
            context=f"requestBounds.{field}",
        )
        minimum = _decimal(value["minimum"], context=f"{field}.minimum")
        maximum = _decimal(value["maximum"], context=f"{field}.maximum")
        if minimum > maximum:
            raise ScenarioAssumptionContractError(f"{field} bounds are reversed")
        result[field] = (minimum, maximum)
    if result["priceChangePct"] != (Decimal("-5"), Decimal("5")):
        raise ScenarioAssumptionContractError(
            "Scenario v1 priceChangePct is frozen to [-5, 5] percentage points"
        )
    for field in ("demandAdjustmentPct", "promotionUpliftPct"):
        if result[field][0] <= Decimal("-100"):
            raise ScenarioAssumptionContractError(
                f"{field} bounds must keep its multiplicative factor positive"
            )
    if bounds["competitorAvailability"] != ["normal", "stockout", "promotion"]:
        raise ScenarioAssumptionContractError(
            "competitorAvailability states/order must be normal, stockout, promotion"
        )
    if bounds["weatherEvent"] != ["normal", "positive", "negative"]:
        raise ScenarioAssumptionContractError(
            "weatherEvent states/order must be normal, positive, negative"
        )
    return result


def _validate_market_rules(document: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    rules = document["marketCurrencyRules"]
    if not isinstance(rules, list) or not rules:
        raise ScenarioAssumptionContractError("marketCurrencyRules must be non-empty")
    domains: dict[str, tuple[int, int]] = {}
    seen: set[tuple[str, str]] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, Mapping):
            raise ScenarioAssumptionContractError(f"marketCurrencyRules[{index}] must map")
        context = f"marketCurrencyRules[{index}]"
        _exact_keys(
            rule,
            required={
                "marketId",
                "currencyCode",
                "minimumPriceMinor",
                "maximumPriceMinor",
                "candidateStepMinor",
                "gridOriginMinor",
                "roundingMode",
                "priceFreshnessDays",
                "observedSupportWindowDays",
            },
            context=context,
        )
        market_id = rule["marketId"]
        currency_code = rule["currencyCode"]
        if not isinstance(market_id, str) or not market_id:
            raise ScenarioAssumptionContractError(f"{context}.marketId is empty")
        if not isinstance(currency_code, str):
            raise ScenarioAssumptionContractError(
                f"{context}.currencyCode must be text"
            )
        try:
            minor_exponent(currency_code)
        except UnknownCurrencyError as exc:
            raise ScenarioAssumptionContractError(
                f"{context}.currencyCode is not in the money contract"
            ) from exc
        pair = (market_id, currency_code)
        if pair in seen:
            raise ScenarioAssumptionContractError(
                f"duplicate market/currency rule {pair}"
            )
        seen.add(pair)
        if market_id in domains:
            raise ScenarioAssumptionContractError(
                f"market {market_id!r} has multiple operating currencies"
            )
        minimum = _integer(
            rule["minimumPriceMinor"], context=f"{context}.minimumPriceMinor", minimum=1
        )
        maximum = _integer(
            rule["maximumPriceMinor"], context=f"{context}.maximumPriceMinor", minimum=1
        )
        if minimum >= maximum:
            raise ScenarioAssumptionContractError(f"{context} price domain is empty")
        step = _integer(
            rule["candidateStepMinor"], context=f"{context}.candidateStepMinor", minimum=1
        )
        origin = _integer(rule["gridOriginMinor"], context=f"{context}.gridOriginMinor")
        if origin >= maximum or step > maximum - minimum:
            raise ScenarioAssumptionContractError(f"{context} grid cannot cover its domain")
        if rule["roundingMode"] != "round_half_even":
            raise ScenarioAssumptionContractError(
                f"{context}.roundingMode must be round_half_even"
            )
        _integer(
            rule["priceFreshnessDays"],
            context=f"{context}.priceFreshnessDays",
            minimum=1,
        )
        _integer(
            rule["observedSupportWindowDays"],
            context=f"{context}.observedSupportWindowDays",
            minimum=1,
        )
        domains[market_id] = (minimum, maximum)
    return domains


def _validate_tiers(document: Mapping[str, Any], domains: Mapping[str, tuple[int, int]]) -> None:
    tiers = document["tierCoefficients"]
    if not isinstance(tiers, list) or not tiers:
        raise ScenarioAssumptionContractError("tierCoefficients must be non-empty")
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, str]] = set()
    for index, tier in enumerate(tiers):
        if not isinstance(tier, Mapping):
            raise ScenarioAssumptionContractError(f"tierCoefficients[{index}] must map")
        context = f"tierCoefficients[{index}]"
        _exact_keys(
            tier,
            required={
                "marketId",
                "deptId",
                "baselinePriceTier",
                "lowerPriceMinor",
                "upperPriceMinor",
                "assumedBeta",
                "competitorStockoutSensitivity",
                "competitorPromotionSensitivity",
                "weatherPositiveSensitivity",
                "weatherNegativeSensitivity",
            },
            context=context,
        )
        identity = (tier["marketId"], tier["deptId"], tier["baselinePriceTier"])
        if any(not isinstance(part, str) or not part for part in identity):
            raise ScenarioAssumptionContractError(f"{context} identity is empty")
        if identity in seen:
            raise ScenarioAssumptionContractError(f"duplicate tier grain {identity}")
        seen.add(identity)
        if tier["marketId"] not in domains:
            raise ScenarioAssumptionContractError(
                f"{context} has no market/currency rule"
            )
        _integer(tier["lowerPriceMinor"], context=f"{context}.lowerPriceMinor", minimum=1)
        if tier["upperPriceMinor"] is not None:
            upper = _integer(
                tier["upperPriceMinor"], context=f"{context}.upperPriceMinor", minimum=1
            )
            if upper <= tier["lowerPriceMinor"]:
                raise ScenarioAssumptionContractError(f"{context} band is empty")
        if _decimal(tier["assumedBeta"], context=f"{context}.assumedBeta") >= 0:
            raise ScenarioAssumptionContractError(f"{context}.assumedBeta must be < 0")
        for field in (
            "competitorStockoutSensitivity",
            "competitorPromotionSensitivity",
            "weatherPositiveSensitivity",
            "weatherNegativeSensitivity",
        ):
            _decimal(
                tier[field],
                context=f"{context}.{field}",
                minimum="0",
                maximum_exclusive="1",
            )
        grouped[(tier["marketId"], tier["deptId"])].append(tier)

    for (market_id, dept_id), group in grouped.items():
        ordered = sorted(group, key=lambda row: row["lowerPriceMinor"])
        domain_min, _domain_max = domains[market_id]
        expected_lower = domain_min
        for index, tier in enumerate(ordered):
            if tier["lowerPriceMinor"] != expected_lower:
                raise ScenarioAssumptionContractError(
                    f"tier bands for {(market_id, dept_id)} have a gap/overlap at "
                    f"{expected_lower}"
                )
            upper = tier["upperPriceMinor"]
            if upper is None:
                if index != len(ordered) - 1:
                    raise ScenarioAssumptionContractError(
                        f"only the final tier for {(market_id, dept_id)} may be unbounded"
                    )
                expected_lower = -1
            else:
                expected_lower = upper
        if ordered[-1]["upperPriceMinor"] is not None:
            raise ScenarioAssumptionContractError(
                f"final tier for {(market_id, dept_id)} must have upperPriceMinor=null"
            )


def _validate_presets(
    document: Mapping[str, Any], bounds: Mapping[str, tuple[Decimal, Decimal]]
) -> None:
    presets = document["presets"]
    if not isinstance(presets, list):
        raise ScenarioAssumptionContractError("presets must be a list")
    identities = [preset.get("presetId") for preset in presets if isinstance(preset, Mapping)]
    if len(identities) != len(presets) or set(identities) != REQUIRED_PRESET_IDS:
        raise ScenarioAssumptionContractError(
            f"presets must define exactly {sorted(REQUIRED_PRESET_IDS)}"
        )
    if len(identities) != len(set(identities)):
        raise ScenarioAssumptionContractError("preset ids must be unique")
    resolved: dict[str, Mapping[str, Any]] = {}
    for index, preset in enumerate(presets):
        assert isinstance(preset, Mapping)
        context = f"presets[{index}]"
        _exact_keys(
            preset,
            required={
                "presetId",
                "label",
                "demandAdjustmentPct",
                "priceChangePct",
                "promotionUpliftPct",
                "competitorAvailability",
                "weatherEvent",
                "atpAdjustment",
            },
            context=context,
        )
        if not isinstance(preset["label"], str) or not preset["label"]:
            raise ScenarioAssumptionContractError(f"{context}.label is empty")
        for field in (
            "demandAdjustmentPct",
            "priceChangePct",
            "promotionUpliftPct",
        ):
            value = _decimal(preset[field], context=f"{context}.{field}")
            minimum, maximum = bounds[field]
            if not minimum <= value <= maximum:
                raise ScenarioAssumptionContractError(
                    f"{context}.{field} is outside request bounds"
                )
        if preset["competitorAvailability"] not in {"normal", "stockout", "promotion"}:
            raise ScenarioAssumptionContractError(
                f"{context}.competitorAvailability is unknown"
            )
        if preset["weatherEvent"] not in {"normal", "positive", "negative"}:
            raise ScenarioAssumptionContractError(f"{context}.weatherEvent is unknown")
        _decimal(
            preset["atpAdjustment"],
            context=f"{context}.atpAdjustment",
            minimum="-1",
            maximum="0",
        )
        resolved[preset["presetId"]] = preset

    neutral = resolved["expected_demand"]
    for field in (
        "demandAdjustmentPct",
        "priceChangePct",
        "promotionUpliftPct",
        "atpAdjustment",
    ):
        if neutral[field] != "0":
            raise ScenarioAssumptionContractError("expected_demand must be neutral")
    if neutral["competitorAvailability"] != "normal" or neutral["weatherEvent"] != "normal":
        raise ScenarioAssumptionContractError("expected_demand must be neutral")

    if _decimal(resolved["high_demand"]["demandAdjustmentPct"], context="high") <= 0:
        raise ScenarioAssumptionContractError("high_demand demand adjustment must be positive")
    high = resolved["high_demand"]
    if (
        high["priceChangePct"] != "0"
        or high["promotionUpliftPct"] != "0"
        or high["competitorAvailability"] != "normal"
        or high["weatherEvent"] != "positive"
        or high["atpAdjustment"] != "0"
    ):
        raise ScenarioAssumptionContractError(
            "high_demand must change only demand and positive weather"
        )
    if _decimal(resolved["low_demand"]["demandAdjustmentPct"], context="low") >= 0:
        raise ScenarioAssumptionContractError("low_demand demand adjustment must be negative")
    low = resolved["low_demand"]
    if (
        low["priceChangePct"] != "0"
        or low["promotionUpliftPct"] != "0"
        or low["competitorAvailability"] != "normal"
        or low["weatherEvent"] != "negative"
        or low["atpAdjustment"] != "0"
    ):
        raise ScenarioAssumptionContractError(
            "low_demand must change only demand and negative weather"
        )
    promotion = resolved["promotion_upside"]
    if (
        promotion["demandAdjustmentPct"] != "0"
        or _decimal(promotion["priceChangePct"], context="promotion.price") >= 0
        or _decimal(promotion["promotionUpliftPct"], context="promotion.uplift") <= 0
        or promotion["competitorAvailability"] != "normal"
        or promotion["weatherEvent"] != "normal"
        or promotion["atpAdjustment"] != "0"
    ):
        raise ScenarioAssumptionContractError(
            "promotion_upside must contain only a discount and positive non-price uplift"
        )
    supply = resolved["supply_constrained"]
    if (
        supply["demandAdjustmentPct"] != "0"
        or supply["priceChangePct"] != "0"
        or supply["promotionUpliftPct"] != "0"
        or supply["competitorAvailability"] != "normal"
        or supply["weatherEvent"] != "normal"
        or _decimal(supply["atpAdjustment"], context="supply.atp") >= 0
    ):
        raise ScenarioAssumptionContractError(
            "supply_constrained must contain only a negative atpAdjustment"
        )


def validate_scenario_assumption_bundle(document: Mapping[str, Any]) -> None:
    """Validate one immutable bundle before it can become an approval candidate."""

    _exact_keys(
        document,
        required={
            "schemaVersion",
            "assumptionSetId",
            "version",
            "artifactClass",
            "servingEligible",
            "projectionBasis",
            "evidenceClass",
            "statisticalGateStatus",
            "disclosure",
            "requestBounds",
            "marketCurrencyRules",
            "tierCoefficients",
            "presets",
        },
        context="assumption bundle",
    )
    if document["schemaVersion"] != SCHEMA_VERSION:
        raise ScenarioAssumptionContractError("unknown scenario assumption schemaVersion")
    for field in ("assumptionSetId", "version", "disclosure"):
        if not isinstance(document[field], str) or not document[field]:
            raise ScenarioAssumptionContractError(f"{field} must be non-empty text")
    if document["artifactClass"] not in {"serving_candidate", "synthetic_test"}:
        raise ScenarioAssumptionContractError("artifactClass is unknown")
    if not isinstance(document["servingEligible"], bool):
        raise ScenarioAssumptionContractError("servingEligible must be boolean")
    if document["artifactClass"] == "synthetic_test" and document["servingEligible"]:
        raise ScenarioAssumptionContractError(
            "synthetic_test bundles can never be servingEligible"
        )
    if document["artifactClass"] == "serving_candidate" and not document["servingEligible"]:
        raise ScenarioAssumptionContractError(
            "serving_candidate bundles must be eligible for separate approval"
        )
    if document["projectionBasis"] != "assumption_set":
        raise ScenarioAssumptionContractError("projectionBasis must be assumption_set")
    if document["evidenceClass"] != "synthetic_scenario":
        raise ScenarioAssumptionContractError("evidenceClass must be synthetic_scenario")
    if document["statisticalGateStatus"] != "not_applicable":
        raise ScenarioAssumptionContractError(
            "statisticalGateStatus must be not_applicable"
        )
    bounds = _validate_bounds(document)
    domains = _validate_market_rules(document)
    _validate_tiers(document, domains)
    _validate_presets(document, bounds)


def scenario_assumption_fingerprint(document: Mapping[str, Any]) -> str:
    """Return the non-circular semantic identity of a validated bundle."""

    validate_scenario_assumption_bundle(document)
    return semantic_fingerprint(dict(document), volatile_pointers=())


def load_scenario_assumption_bundle(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and validate a bundle, defaulting to the synthetic contract fixture."""

    if path is None:
        path = (
            locate_contract_root()
            / "scenarios"
            / "forecast_scenario_assumptions.yaml"
        )
    document = load_yaml(Path(path))
    validate_scenario_assumption_bundle(document)
    return document


def may_receive_serving_approval(document: Mapping[str, Any]) -> bool:
    """Whether the artifact class may enter the *separate* approval lifecycle."""

    validate_scenario_assumption_bundle(document)
    return bool(
        document["artifactClass"] == "serving_candidate"
        and document["servingEligible"]
    )
