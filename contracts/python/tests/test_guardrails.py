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
    document = json.loads(VECTORS.read_text(encoding="utf-8"))
    for vector in document["vectors"]:
        payload = resolve_guardrails(vector["marketId"], vector["currencyCode"])
        assert canonical_json_bytes(payload).decode("utf-8") == vector["canonical"]
        assert (
            resolved_guardrail_fingerprint(
                vector["marketId"], vector["currencyCode"]
            )
            == vector["sha256"]
        )


def test_missing_or_wrong_currency_rule_fails_closed() -> None:
    for market_id, currency_code in (
        ("india-mumbai", "USD"),
        ("us-new-york", "INR"),
        ("uk-london", "GBP"),
    ):
        with pytest.raises(GuardrailContractError, match="exactly one"):
            resolve_guardrails(market_id, currency_code)


def test_absolute_rules_are_market_local() -> None:
    india = resolve_guardrails("india-mumbai", "INR")
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
