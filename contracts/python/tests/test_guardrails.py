"""Decision #39 market/currency guardrail resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from retail_contracts.fingerprint import canonical_json_bytes
from retail_contracts.guardrails import (
    GuardrailContractError,
    resolve_guardrails,
    resolved_guardrail_fingerprint,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VECTORS = REPO_ROOT / "contracts" / "guardrails" / "resolved-policy-v1.json"


def test_resolved_policy_vectors_match_exact_bytes_and_fingerprint() -> None:
    """v1 vectors must resolve against v1, forever.

    They were fingerprinted under `inventory-policy/1.0.0`. Resolving them under
    whatever generation happens to be newest would make an immutable artifact
    unreproducible the moment a v2 landed, so the generation is named.
    """

    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in document["vectors"]:
        payload = resolve_guardrails(
            vector["marketId"],
            vector["currencyCode"],
            inventory_policy_generation="v1",
        )
        assert canonical_json_bytes(payload).decode("utf-8") == vector["canonical"]
        assert (
            resolved_guardrail_fingerprint(
                vector["marketId"],
                vector["currencyCode"],
                inventory_policy_generation="v1",
            )
            == vector["sha256"]
        )


def test_both_live_markets_resolve_a_market_local_inventory_policy() -> None:
    """Two separate defects had to be fixed for this to be true.

    First, `pricing_rules.yaml` named only the retired `india-mumbai` id, so
    `resolve_guardrails("india-west", "INR")` raised outright -- an executable
    failure, not vector staleness: one of the two live supported markets could
    resolve no policy at all. Adding the live rule fixes that under BOTH
    generations, which is why this test no longer asserts a v1 raise.

    Second, and only fixed by v2: v1 returns inventory policy from
    `globalDefaults` with no override path, so a per-market budget, timezone or
    service level was unexpressible. v1 therefore resolves india-west today and
    still cannot say anything market-local about it.
    """

    v1 = resolve_guardrails(
        "india-west", "INR", inventory_policy_generation="v1"
    )["inventoryPolicy"]
    assert v1["policyVersion"] == "inventory-policy/1.0.0"
    for market_local in (
        "weeklyReplenishmentBudgetMinor",
        "timezone",
        "nodeCapacityUnits",
    ):
        assert market_local not in v1, (
            f"v1 unexpectedly carries {market_local}; the override path it "
            "lacks is the whole reason v2 exists"
        )

    for market, currency in (("india-west", "INR"), ("us-new-york", "USD")):
        resolved = resolve_guardrails(
            market, currency, inventory_policy_generation="v2"
        )["inventoryPolicy"]
        assert resolved["policyVersion"] == "inventory-policy/2.0.0"
        assert resolved["marketId"] == market
        assert resolved["currencyCode"] == currency
        assert resolved["weeklyReplenishmentBudgetMinor"] > 0


def test_inventory_overrides_are_market_local_and_do_not_cross_inherit() -> None:
    """v1 had no override path at all, so a per-market budget was unexpressible.

    Budgets are market-local minor units: one number cannot be both INR and USD,
    which is exactly why it may not live in globalDefaults.
    """

    india = resolve_guardrails(
        "india-west", "INR", inventory_policy_generation="v2"
    )["inventoryPolicy"]
    us = resolve_guardrails(
        "us-new-york", "USD", inventory_policy_generation="v2"
    )["inventoryPolicy"]

    assert india["weeklyReplenishmentBudgetMinor"] != us[
        "weeklyReplenishmentBudgetMinor"
    ]
    assert india["timezone"] == "Asia/Kolkata"
    assert us["timezone"] == "America/New_York"
    # An override replaces the shared default for that market and never leaks
    # into the other one.
    assert india["serviceLevelsByClass"]["A"] == "0.97"
    assert us["serviceLevelsByClass"]["A"] == "0.96"
    # Shared dimensionless controls still come from globalDefaults.
    assert india["reviewPeriodDays"] == us["reviewPeriodDays"] == 7


def test_v2_negative_market_currency_cases_still_fail_closed() -> None:
    for market_id, currency_code in (
        ("india-west", "USD"),
        ("us-new-york", "INR"),
        ("does-not-exist", "INR"),
        # GOI-9. A tenant sharing a country must not inherit another tenant's
        # money by resolving on currency alone.
        ("gulf-india", "USD"),
    ):
        with pytest.raises(GuardrailContractError, match="exactly one"):
            resolve_guardrails(
                market_id, currency_code, inventory_policy_generation="v2"
            )


def test_the_gulf_tenant_resolves_its_own_money_not_the_retail_tenant_s() -> None:
    """GOI-9. Two tenants, one country, one currency -- and no bleed.

    Before this rule `resolve_guardrails("gulf-india", "INR")` raised under
    `zeroMatchBehavior: fail_closed`, which would have stopped the inventory
    engine AFTER a full run rather than before it. The risk in fixing it is the
    opposite one: `crossMarketInheritance: forbidden` means the Gulf market must
    take none of india-west's absolute money or capacity, even though both are
    India and both are INR.
    """

    gulf = resolve_guardrails("gulf-india", "INR", inventory_policy_generation="v2")
    india = resolve_guardrails("india-west", "INR", inventory_policy_generation="v2")

    gulf_inventory = gulf["inventoryPolicy"]
    india_inventory = india["inventoryPolicy"]

    # Absolute money and capacity are the tenant's own.
    assert gulf_inventory["weeklyReplenishmentBudgetMinor"] == 38000000000
    assert (
        gulf_inventory["weeklyReplenishmentBudgetMinor"]
        != india_inventory["weeklyReplenishmentBudgetMinor"]
    )
    assert gulf_inventory["nodeCapacityUnits"] == 300000
    assert gulf_inventory["nodeCapacityUnits"] != india_inventory["nodeCapacityUnits"]

    # Dimensionless shared controls still come from globalDefaults.
    assert gulf_inventory["reviewPeriodDays"] == india_inventory["reviewPeriodDays"]

    # Pricing bounds are the tenant's own: the retail Rs 5 floor admits no
    # lubricant pack, whose cheapest SKU is a Rs 162 grease tub.
    assert gulf["pricingRules"]["minimumPriceMinor"] == 10000
    assert gulf["currencyCode"] == "INR"


def test_the_v2_vectors_match_their_recorded_bytes_and_fingerprints() -> None:
    path = (
        REPO_ROOT
        / "contracts"
        / "guardrails"
        / "resolved-inventory-policy-v2.json"
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["policyVersion"] == "inventory-policy/2.0.0"
    # india-west, us-new-york, and the Gulf tenant added at GOI-9.
    assert len(document["vectors"]) == 3
    for vector in document["vectors"]:
        payload = resolve_guardrails(
            vector["marketId"],
            vector["currencyCode"],
            inventory_policy_generation="v2",
        )
        assert canonical_json_bytes(payload).decode("utf-8") == vector["canonical"]
        assert (
            resolved_guardrail_fingerprint(
                vector["marketId"],
                vector["currencyCode"],
                inventory_policy_generation="v2",
            )
            == vector["semanticFingerprint"]
        )


def test_missing_or_wrong_currency_rule_fails_closed() -> None:
    for market_id, currency_code in (
        ("india-mumbai", "USD"),
        ("us-new-york", "INR"),
        ("uk-london", "GBP"),
    ):
        with pytest.raises(GuardrailContractError, match="exactly one"):
            resolve_guardrails(
                market_id, currency_code, inventory_policy_generation="v1"
            )


def test_absolute_rules_are_market_local() -> None:
    india = resolve_guardrails(
        "india-mumbai", "INR", inventory_policy_generation="v1"
    )
    us = resolve_guardrails("us-new-york", "USD")
    assert india["pricingRules"]["candidateStepMinor"] == 100
    assert us["pricingRules"]["candidateStepMinor"] == 1
    assert india["pricingRules"]["preferredEndingMinor"] == [0, 99]
    assert us["pricingRules"]["preferredEndingMinor"] == [99]


def test_guardrail_decimal_text_has_one_cross_language_form() -> None:
    from retail_contracts.guardrails import _decimal

    assert str(_decimal("0.9", context="test")) == "0.9"
    for value in ("0.90", "4.00", "1e-1", "-0"):
        with pytest.raises(GuardrailContractError, match="canonical"):
            _decimal(value, context="test")
