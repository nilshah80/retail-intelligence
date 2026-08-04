"""Resolve the shared market/currency guardrail contract (decision #39)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .entities import load_yaml, locate_contract_root
from .fingerprint import canonical_decimal_string, semantic_fingerprint
from .money import minor_exponent

RESOLVED_POLICY_SCHEMA = "retail-resolved-policy/v1"


class GuardrailContractError(ValueError):
    """A guardrail document or requested market context is unsafe."""


def _exact_keys(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    context: str,
) -> None:
    missing = required - set(value)
    unknown = set(value) - required - optional
    if missing or unknown:
        raise GuardrailContractError(
            f"{context} keys invalid: missing={sorted(missing)}, "
            f"unknown={sorted(unknown)}"
        )


def _decimal(
    value: Any,
    *,
    context: str,
    minimum: str | None = None,
    maximum: str | None = None,
) -> Decimal:
    if not isinstance(value, str):
        raise GuardrailContractError(
            f"{context} must be an exact canonical decimal string"
        )
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise GuardrailContractError(f"{context} is not decimal text") from exc
    if (
        not result.is_finite()
        or format(result, "f") != value
        or canonical_decimal_string(value) != value
    ):
        raise GuardrailContractError(
            f"{context} must be canonical finite plain decimal text"
        )
    if minimum is not None and result < Decimal(minimum):
        raise GuardrailContractError(f"{context} must be >= {minimum}")
    if maximum is not None and result > Decimal(maximum):
        raise GuardrailContractError(f"{context} must be <= {maximum}")
    return result


def _positive_int(value: Any, *, context: str, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardrailContractError(f"{context} must be an integer")
    floor = 0 if allow_zero else 1
    if value < floor:
        raise GuardrailContractError(f"{context} must be >= {floor}")
    return value


#: Inventory policy generations, newest first. v1 stays on disk and stays
#: resolvable because it is bound to every artifact published under it; removing
#: it would make those artifacts unreproducible rather than merely superseded.
INVENTORY_POLICY_FILES: dict[str, str] = {
    "v2": "inventory-policy-v2.yaml",
    "v1": "policy.yaml",
}


def load_guardrail_documents(
    root: str | Path | None = None,
    *,
    inventory_policy_generation: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load the guardrail contracts, newest inventory policy by default.

    `inventory_policy_generation` names a generation explicitly. A caller
    verifying a vector fingerprinted under `inventory-policy/1.0.0` must be able
    to say so: resolving that vector under v2 would silently change bytes an
    immutable artifact was fingerprinted against.
    """

    contract_root = locate_contract_root(root)
    directory = contract_root / "guardrails"
    if inventory_policy_generation is None:
        inventory_path = next(
            (
                directory / name
                for name in INVENTORY_POLICY_FILES.values()
                if (directory / name).is_file()
            ),
            directory / INVENTORY_POLICY_FILES["v1"],
        )
    else:
        if inventory_policy_generation not in INVENTORY_POLICY_FILES:
            raise GuardrailContractError(
                f"unknown inventory policy generation "
                f"{inventory_policy_generation!r}"
            )
        inventory_path = directory / INVENTORY_POLICY_FILES[
            inventory_policy_generation
        ]
        if not inventory_path.is_file():
            raise GuardrailContractError(
                f"inventory policy {inventory_policy_generation} is absent"
            )
    documents = {
        "pricingRules": load_yaml(directory / "pricing_rules.yaml"),
        "inventoryPolicy": load_yaml(inventory_path),
        "priceResponse": load_yaml(directory / "price_response.yaml"),
    }
    _validate_documents(documents)
    return documents


def _validate_documents(documents: Mapping[str, Mapping[str, Any]]) -> None:
    pricing = documents["pricingRules"]
    _exact_keys(
        pricing,
        required={
            "schemaVersion",
            "policyVersion",
            "mode",
            "objective",
            "globalDefaults",
            "marketCurrencyRules",
        },
        context="pricing_rules",
    )
    if pricing["schemaVersion"] != "retail-pricing-rules/v1":
        raise GuardrailContractError("unknown pricing_rules schemaVersion")
    if pricing["mode"] != "shadow" or pricing["objective"] != "revenue":
        raise GuardrailContractError(
            "Phase-2 pricing rules must remain shadow/revenue"
        )
    defaults = pricing["globalDefaults"]
    _exact_keys(
        defaults,
        required={
            "maxChangePctPerCycle",
            "minActionCapPct",
            "minMarginPct",
            "confidenceDominanceMin",
            "endingFallback",
        },
        context="pricing_rules.globalDefaults",
    )
    _decimal(
        defaults["maxChangePctPerCycle"],
        context="maxChangePctPerCycle",
        minimum="0",
        maximum="100",
    )
    _decimal(
        defaults["minActionCapPct"],
        context="minActionCapPct",
        minimum="0",
        maximum=defaults["maxChangePctPerCycle"],
    )
    _decimal(
        defaults["minMarginPct"],
        context="minMarginPct",
        minimum="0",
        maximum="100",
    )
    _decimal(
        defaults["confidenceDominanceMin"],
        context="confidenceDominanceMin",
        minimum="0",
        maximum="1",
    )
    if defaults["endingFallback"] != "nearest_step":
        raise GuardrailContractError("endingFallback must be nearest_step")

    seen: set[tuple[str, str]] = set()
    for index, rule in enumerate(pricing["marketCurrencyRules"]):
        context = f"pricing_rules.marketCurrencyRules[{index}]"
        _exact_keys(
            rule,
            required={
                "marketId",
                "currencyCode",
                "minorUnitExponent",
                "minimumPriceMinor",
                "maximumPriceMinor",
                "candidateStepMinor",
                "gridOriginMinor",
                "preferredEndingMinor",
            },
            context=context,
        )
        pair = (rule["marketId"], rule["currencyCode"])
        if pair in seen:
            raise GuardrailContractError(f"duplicate market/currency rule {pair}")
        seen.add(pair)
        if rule["minorUnitExponent"] != minor_exponent(rule["currencyCode"]):
            raise GuardrailContractError(f"{context} minor-unit exponent mismatch")
        minimum = _positive_int(
            rule["minimumPriceMinor"], context=f"{context}.minimumPriceMinor"
        )
        maximum = _positive_int(
            rule["maximumPriceMinor"], context=f"{context}.maximumPriceMinor"
        )
        if minimum >= maximum:
            raise GuardrailContractError(f"{context} price band is empty")
        _positive_int(
            rule["candidateStepMinor"], context=f"{context}.candidateStepMinor"
        )
        _positive_int(
            rule["gridOriginMinor"],
            context=f"{context}.gridOriginMinor",
            allow_zero=True,
        )
        modulus = 10 ** rule["minorUnitExponent"]
        endings = rule["preferredEndingMinor"]
        if (
            not isinstance(endings, list)
            or not endings
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value >= modulus
                for value in endings
            )
            or len(set(endings)) != len(endings)
        ):
            raise GuardrailContractError(
                f"{context}.preferredEndingMinor must be unique values in "
                f"[0, {modulus})"
            )

    inventory = documents["inventoryPolicy"]
    inventory_schema = inventory.get("schemaVersion")
    if inventory_schema == "retail-inventory-policy/v1":
        inventory_required = {"schemaVersion", "policyVersion", "globalDefaults"}
        inventory_optional: set[str] = set()
    elif inventory_schema == "retail-inventory-policy/v2":
        inventory_required = {
            "schemaVersion",
            "policyVersion",
            "globalDefaults",
            "marketCurrencyRules",
            "resolution",
        }
        # v2 carries the frozen P4-D decision blocks. Enumerated rather than
        # allowed wholesale: an unrecognised top-level key in a policy contract is
        # a rule nothing reads, which is worse than a rule that fails validation.
        inventory_optional = {"decisionIds", "supersedes", "erpTransmission"}
    else:
        raise GuardrailContractError("unknown policy schemaVersion")
    unknown = sorted(set(inventory) - inventory_required - inventory_optional)
    if unknown or not inventory_required <= set(inventory):
        _exact_keys(
            inventory,
            required=inventory_required | (set(inventory) & inventory_optional),
            context="policy",
        )
    inventory_defaults = inventory["globalDefaults"]
    # v1 froze exactly nine shared controls. v2 adds the engine-facing decision
    # blocks beside them, so the nine remain REQUIRED while the additions are
    # permitted -- a v2 document missing a v1 control is still invalid.
    inventory_default_required = {
        "serviceLevelsByClass",
        "reviewPeriodDays",
        "maxCoverDays",
        "holdDeclineThreshold",
        "holdCoverDays",
        "markdownCoverDays",
        "markdownPct",
        "calibrationCohortPct",
        "validationHoldoutPct",
    }
    missing_defaults = sorted(inventory_default_required - set(inventory_defaults))
    if missing_defaults:
        raise GuardrailContractError(
            f"policy.globalDefaults keys invalid: missing={missing_defaults}"
        )
    if inventory_schema == "retail-inventory-policy/v1":
        _exact_keys(
            inventory_defaults,
            required=inventory_default_required,
            context="policy.globalDefaults",
        )
    service_levels = inventory_defaults["serviceLevelsByClass"]
    _exact_keys(
        service_levels, required={"A", "B", "C"}, context="serviceLevelsByClass"
    )
    for key, value in service_levels.items():
        _decimal(value, context=f"serviceLevelsByClass.{key}", minimum="0.5", maximum="0.999")
    for key in (
        "reviewPeriodDays",
        "maxCoverDays",
        "holdCoverDays",
        "markdownCoverDays",
    ):
        _positive_int(inventory_defaults[key], context=key)
    for key in (
        "holdDeclineThreshold",
        "markdownPct",
        "calibrationCohortPct",
        "validationHoldoutPct",
    ):
        _decimal(inventory_defaults[key], context=key, minimum="0", maximum="100")
    if (
        Decimal(inventory_defaults["calibrationCohortPct"])
        + Decimal(inventory_defaults["validationHoldoutPct"])
        != 100
    ):
        raise GuardrailContractError(
            "calibrationCohortPct + validationHoldoutPct must equal 100"
        )

    response = documents["priceResponse"]
    _exact_keys(
        response,
        required={"schemaVersion", "policyVersion", "globalDefaults"},
        context="price_response",
    )
    if response["schemaVersion"] != "retail-price-response/v1":
        raise GuardrailContractError("unknown price_response schemaVersion")
    response_defaults = response["globalDefaults"]
    _exact_keys(
        response_defaults,
        required={
            "requireNegativeBeta",
            "betaMinAbs",
            "betaMaxAbs",
            "signConsistencyMin",
            "resampleIqrRatioMax",
            "minResampleDraws",
            "holdoutImprovementMin",
            "departmentCoverageMin",
            "departmentMinGatedSeries",
        },
        context="price_response.globalDefaults",
    )
    if response_defaults["requireNegativeBeta"] is not True:
        raise GuardrailContractError("requireNegativeBeta must be true")
    for key in (
        "betaMinAbs",
        "betaMaxAbs",
        "signConsistencyMin",
        "resampleIqrRatioMax",
        "holdoutImprovementMin",
        "departmentCoverageMin",
    ):
        _decimal(response_defaults[key], context=key, minimum="0")
    for key in ("minResampleDraws", "departmentMinGatedSeries"):
        _positive_int(response_defaults[key], context=key)
    if Decimal(response_defaults["betaMinAbs"]) > Decimal(
        response_defaults["betaMaxAbs"]
    ):
        raise GuardrailContractError("beta range is reversed")


def _resolve_inventory_policy(
    document: Mapping[str, Any],
    market_id: str,
    currency_code: str,
) -> dict[str, Any]:
    """Merge inventory policy for one market, version-aware.

    v1 had no override path at all: the resolver returned `globalDefaults`
    verbatim, so a per-market service level, budget ceiling or node capacity was
    unexpressible. Multi-echelon replenishment needs all three, and a budget in
    particular cannot be global -- it is market-local minor units, and one number
    cannot be both INR and USD.

    v1 documents keep resolving exactly as before. They declare no
    `marketCurrencyRules`, so there is nothing to merge and the returned shape is
    unchanged; every artifact resolved under v1 stays reproducible.
    """

    resolved: dict[str, Any] = {
        "policyVersion": document["policyVersion"],
        **document["globalDefaults"],
    }
    rules = document.get("marketCurrencyRules")
    if rules is None:
        return resolved

    matches = [
        rule
        for rule in rules
        if rule["marketId"] == market_id and rule["currencyCode"] == currency_code
    ]
    if len(matches) != 1:
        raise GuardrailContractError(
            "exactly one inventory market rule is required for "
            f"{market_id!r} + {currency_code!r}; found {len(matches)}"
        )
    override = {
        key: value
        for key, value in matches[0].items()
        if key not in {"marketId", "currencyCode"}
    }
    # A shallow merge, deliberately. A deep merge would let one market inherit
    # half of another market's absolute rule -- a service-level table with two
    # classes from here and one from a default is a policy nobody approved.
    resolved.update(override)
    resolved["marketId"] = market_id
    resolved["currencyCode"] = currency_code
    return resolved


def resolve_guardrails(
    market_id: str,
    currency_code: str,
    *,
    root: str | Path | None = None,
    inventory_policy_generation: str | None = None,
) -> dict[str, Any]:
    """Resolve one complete policy; missing/mismatched absolute rules fail closed."""

    documents = load_guardrail_documents(
        root, inventory_policy_generation=inventory_policy_generation
    )
    pricing = documents["pricingRules"]
    matches = [
        rule
        for rule in pricing["marketCurrencyRules"]
        if rule["marketId"] == market_id and rule["currencyCode"] == currency_code
    ]
    if len(matches) != 1:
        raise GuardrailContractError(
            f"exactly one guardrail rule is required for "
            f"{market_id!r} + {currency_code!r}; found {len(matches)}"
        )
    rule = matches[0]
    return {
        "schemaVersion": RESOLVED_POLICY_SCHEMA,
        "marketId": market_id,
        "currencyCode": currency_code,
        "pricingRules": {
            "policyVersion": pricing["policyVersion"],
            "mode": pricing["mode"],
            "objective": pricing["objective"],
            **pricing["globalDefaults"],
            **{
                key: value
                for key, value in rule.items()
                if key not in {"marketId", "currencyCode"}
            },
        },
        "inventoryPolicy": _resolve_inventory_policy(
            documents["inventoryPolicy"], market_id, currency_code
        ),
        "priceResponse": {
            "policyVersion": documents["priceResponse"]["policyVersion"],
            **documents["priceResponse"]["globalDefaults"],
        },
    }


def resolved_guardrail_fingerprint(
    market_id: str,
    currency_code: str,
    *,
    root: str | Path | None = None,
    inventory_policy_generation: str | None = None,
) -> str:
    return semantic_fingerprint(
        resolve_guardrails(
            market_id,
            currency_code,
            root=root,
            inventory_policy_generation=inventory_policy_generation,
        ),
        volatile_pointers=(),
    )


__all__ = [
    "INVENTORY_POLICY_FILES",
    "RESOLVED_POLICY_SCHEMA",
    "GuardrailContractError",
    "load_guardrail_documents",
    "resolve_guardrails",
    "resolved_guardrail_fingerprint",
]
