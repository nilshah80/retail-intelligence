from decimal import Decimal
from pathlib import Path

import pytest

from retail_ml.pricing.panel import load_response_policy
from retail_ml.pricing.policy import (
    PricingPolicyError,
    enumerate_candidates,
    load_pricing_policy,
    resolve_market_rule,
    scaled_change_cap,
)


ROOT = Path(__file__).resolve().parents[2]


def test_response_policy_has_frozen_identity_and_origin_split() -> None:
    policy = load_response_policy(ROOT / "contracts/pricing/response-evaluation.json")

    assert policy["policyFingerprint"] == (
        "820f484ecdf1643e72f589fe3217d625acfe21217430dca45e6acf686b6da2e5"
    )
    assert [row["purpose"] for row in policy["origins"]] == (
        ["development"] * 8 + ["confirmation"] * 5
    )
    assert policy["model"]["baseline"] == "same_controls_without_log_price"
    assert policy["panel"]["exposureSemantics"] == {
        "unitMeaning": "fulfilled_customer_units_including_dc_substitution",
        "zeroUnitWeeks": "explicit_closed_source_week",
        "offset": "none",
        "storeAvailabilityControl": "store_shortfall_share",
        "shortfallUnitsMustNotBeAddedToResponse": True,
    }
    assert policy["originRules"]["priceTier"] == {
        "anchor": "median_regular_price_before_first_confirmation",
        "quantiles": ["0.25", "0.50", "0.75"],
    }
    assert [
        candidate["shrinkage"]
        for candidate in policy["originRules"]["candidateConfigurations"]
    ] == ["none", "department", "department_price_tier"]


@pytest.mark.parametrize(
    ("dominance", "expected"),
    [("0.70", "0.02"), ("0.85", "0.035"), ("1.00", "0.05")],
)
def test_scaled_change_cap_boundaries(dominance: str, expected: str) -> None:
    assert scaled_change_cap(dominance) == Decimal(expected)


def test_two_percent_is_a_cap_not_a_minimum_action() -> None:
    rule = resolve_market_rule(
        load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
        "gulf-india",
        "INR",
    )

    candidates = enumerate_candidates(
        current_price_minor=20_000,
        support_min_minor=19_700,
        support_max_minor=20_300,
        dominance="0.70",
        rule=rule,
    )

    assert 19_800 in candidates
    assert 20_100 in candidates
    assert all(abs(Decimal(value) / Decimal(20_000) - 1) <= Decimal("0.02") for value in candidates)


def test_competitor_upper_bound_only_blocks_price_increases() -> None:
    rule = resolve_market_rule(
        load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml"),
        "gulf-india",
        "INR",
    )
    candidates = enumerate_candidates(
        current_price_minor=20_000,
        support_min_minor=19_000,
        support_max_minor=21_000,
        dominance="1",
        rule=rule,
        competitor_upper_bound_minor=20_150,
    )

    assert min(candidates) < 20_000
    assert max(candidates) <= 20_150


def test_post_rounding_guardrail_rejects_only_escaped_candidates() -> None:
    rule = {
        "candidateStepMinor": 1,
        "gridOriginMinor": 0,
        "preferredEndingMinor": [0],
        "minimumPriceMinor": 1,
        "maximumPriceMinor": 1_000,
        "maxChangePctPerCycle": "5",
    }

    candidates = enumerate_candidates(
        current_price_minor=200,
        support_min_minor=190,
        support_max_minor=210,
        dominance="0.775",
        rule=rule,
    )

    assert candidates == tuple(range(195, 206))


def test_missing_market_currency_rule_fails_closed() -> None:
    policy = load_pricing_policy(ROOT / "contracts/guardrails/pricing_rules.yaml")
    with pytest.raises(PricingPolicyError, match="resolves to 0"):
        resolve_market_rule(policy, "gulf-india", "USD")
