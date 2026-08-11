from __future__ import annotations

from copy import deepcopy

import pytest
from retail_contracts.scenario_assumptions import (
    REQUIRED_PRESET_IDS,
    ScenarioAssumptionContractError,
    load_scenario_assumption_bundle,
    may_receive_serving_approval,
    scenario_assumption_fingerprint,
    validate_scenario_assumption_bundle,
)


def test_checked_in_bundle_is_complete_deterministic_and_non_activatable() -> None:
    bundle = load_scenario_assumption_bundle()
    assert bundle["artifactClass"] == "synthetic_test"
    assert bundle["servingEligible"] is False
    assert may_receive_serving_approval(bundle) is False
    assert {preset["presetId"] for preset in bundle["presets"]} == REQUIRED_PRESET_IDS
    assert scenario_assumption_fingerprint(bundle) == scenario_assumption_fingerprint(
        deepcopy(bundle)
    )
    assert len(scenario_assumption_fingerprint(bundle)) == 64


def test_tier_bands_reject_a_gap() -> None:
    bundle = load_scenario_assumption_bundle()
    broken = deepcopy(bundle)
    broken["tierCoefficients"][1]["lowerPriceMinor"] = 5001
    with pytest.raises(ScenarioAssumptionContractError, match="gap/overlap"):
        validate_scenario_assumption_bundle(broken)


def test_every_preset_must_be_present_and_complete() -> None:
    bundle = load_scenario_assumption_bundle()
    broken = deepcopy(bundle)
    broken["presets"].pop()
    with pytest.raises(ScenarioAssumptionContractError, match="presets must define exactly"):
        validate_scenario_assumption_bundle(broken)


def test_synthetic_fixture_cannot_claim_serving_eligibility() -> None:
    bundle = load_scenario_assumption_bundle()
    broken = deepcopy(bundle)
    broken["servingEligible"] = True
    with pytest.raises(ScenarioAssumptionContractError, match="can never"):
        validate_scenario_assumption_bundle(broken)


def test_request_bounds_cannot_permit_a_non_positive_direct_factor() -> None:
    bundle = load_scenario_assumption_bundle()
    broken = deepcopy(bundle)
    broken["requestBounds"]["demandAdjustmentPct"]["minimum"] = "-100"
    with pytest.raises(ScenarioAssumptionContractError, match="factor positive"):
        validate_scenario_assumption_bundle(broken)


def test_preset_vectors_cannot_hide_an_extra_factor() -> None:
    bundle = load_scenario_assumption_bundle()
    broken = deepcopy(bundle)
    high = next(
        preset for preset in broken["presets"] if preset["presetId"] == "high_demand"
    )
    high["priceChangePct"] = "1"
    with pytest.raises(ScenarioAssumptionContractError, match="high_demand must"):
        validate_scenario_assumption_bundle(broken)


def test_market_currency_must_exist_in_the_money_contract() -> None:
    bundle = load_scenario_assumption_bundle()
    broken = deepcopy(bundle)
    broken["marketCurrencyRules"][0]["currencyCode"] = "JPY"
    with pytest.raises(ScenarioAssumptionContractError, match="money contract"):
        validate_scenario_assumption_bundle(broken)
