import json
from decimal import Decimal
from pathlib import Path

import yaml

from retail_contracts.fingerprint import semantic_fingerprint


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / "contracts/ml/forecast-health-policy.json"
FORECAST_CONTRACT = (
    REPO_ROOT / "contracts/screens/demand-forecast.parity.yaml"
)


def _policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def _health_element() -> dict:
    contract = yaml.safe_load(
        FORECAST_CONTRACT.read_text(encoding="utf-8")
    )
    overview = next(
        panel for panel in contract["panels"] if panel["label"] == "Overview"
    )
    return next(
        element
        for element in overview["elements"]
        if element["label"] == "Forecast Health by Horizon"
    )


def _decimal(value: str) -> Decimal:
    return Decimal(str(value))


def _resolve_grain(policy: dict, inputs: dict) -> str:
    resolution = policy["grainResolution"]
    assert resolution["mode"] == "first_matching_rule"
    for grain in resolution["evaluationOrder"]:
        if grain == "series_key":
            if inputs["completeSeriesKeyCount"] == 1:
                return grain
        elif grain == "store_category":
            if inputs["completeSeriesKeyCount"] == 0 and (
                inputs["selectedStoreCount"] == 1
                or inputs["selectedCategoryCount"] == 1
            ):
                return grain
        else:
            return grain
    raise AssertionError("grain resolution must be total")


def _resolve_status(policy: dict, inputs: dict) -> str:
    evaluation = policy["statusEvaluation"]
    assert evaluation["mode"] == "first_matching_tier"
    assert evaluation["conditionsWithinTier"] == "all"

    accuracy = inputs["accuracyPct"]
    bias = inputs["biasPct"]
    coverage = inputs["p90CoverageRatio"]
    if accuracy is None or bias is None or coverage is None:
        return evaluation["missingOrInsufficientMetric"]

    target = _decimal(
        policy["accuracyTargetsPct"][inputs["grain"]][str(inputs["horizon"])]
    )
    margin = _decimal(accuracy) - target
    absolute_bias = abs(_decimal(bias))
    coverage_ratio = _decimal(coverage)

    for name in evaluation["evaluationOrder"]:
        tier = evaluation["tiers"][name]
        if tier.get("otherwise"):
            return name
        if margin < _decimal(tier["accuracyVsTargetMinPoints"]):
            continue
        if absolute_bias > _decimal(tier["absoluteBiasMaxPct"]):
            continue
        if not (
            _decimal(tier["coverageMinRatio"])
            <= coverage_ratio
            <= _decimal(tier["coverageMaxRatio"])
        ):
            continue
        return name
    raise AssertionError("status evaluation must be total")


def test_decision_77_80_policy_is_immutably_fingerprinted() -> None:
    policy = _policy()

    assert policy["schemaVersion"] == "retail-forecast-health-policy/v1"
    assert policy["policyId"] == "retail-forecast-health/v1"
    assert policy["decisionIds"] == [77, 80]
    assert policy["status"] == "implemented"

    # Rollout state must not be part of governed identity: implementing a policy
    # does not change what the policy says. `status` is therefore excluded, the
    # same way the role contract excludes prose.
    excludes = set(policy["fingerprintExcludes"])
    assert {"semanticFingerprint", "status"} <= excludes
    payload = {key: value for key, value in policy.items() if key not in excludes}
    assert semantic_fingerprint(payload, volatile_pointers=()) == (
        policy["semanticFingerprint"]
    )

    # Flipping the rollout state must leave identity untouched.
    reworded = dict(policy)
    reworded["status"] = "superseded"
    replayed = {
        key: value for key, value in reworded.items() if key not in excludes
    }
    assert semantic_fingerprint(replayed, volatile_pointers=()) == (
        policy["semanticFingerprint"]
    )


def test_parity_contract_binds_the_same_health_policy_identity() -> None:
    policy = _policy()
    health = _health_element()
    binding = health["healthPolicy"]

    assert binding["ref"] == "contracts/ml/forecast-health-policy.json"
    assert binding["policyId"] == policy["policyId"]
    assert binding["semanticFingerprint"] == policy["semanticFingerprint"]

    assert health["metricSemantics"] == policy["metricSemantics"]
    assert health["checkpoints"] == policy["defaultDisplayHorizons"]
    assert (
        health["diagnosticOnlyCheckpoints"]
        == policy["diagnosticOnlyHorizons"]
    )
    assert health["independentOfOperationalHorizonCap"] is True


def test_decision_80_freezes_exact_horizon_rows_and_units() -> None:
    policy = _policy()

    assert policy["metricSemantics"] == "exact_horizon_additive"
    assert policy["defaultDisplayHorizons"] == [1, 4, 8, 13]
    assert policy["diagnosticOnlyHorizons"] == [26]
    assert policy["units"] == {
        "accuracy": "percentage_points_0_to_100",
        "accuracyVsTarget": "percentage_points",
        "absoluteBias": "percentage_points",
        "p90Coverage": "ratio_0_to_1",
    }
    assert list(policy["statusEvaluation"]["evaluationOrder"]) == [
        "Strong",
        "Healthy",
        "Watch",
        "Action",
    ]
    assert (
        policy["statusEvaluation"]["missingOrInsufficientMetric"]
        == "unavailable"
    )


def test_decision_77_targets_cover_every_governed_grain_and_horizon() -> None:
    policy = _policy()
    targets = policy["accuracyTargetsPct"]

    assert set(targets) == {
        "market_portfolio",
        "store_category",
        "series_key",
    }
    for grain, horizons in targets.items():
        assert set(horizons) == {
            str(horizon) for horizon in policy["horizons"]
        }, grain
        values = [_decimal(horizons[str(h)]) for h in policy["horizons"]]
        assert values == sorted(values, reverse=True), grain

    for horizon in policy["horizons"]:
        key = str(horizon)
        assert (
            _decimal(targets["market_portfolio"][key])
            > _decimal(targets["store_category"][key])
            > _decimal(targets["series_key"][key])
        )


def test_grain_resolution_vectors_are_reproducible() -> None:
    policy = _policy()
    vectors = policy["grainResolutionTestVectors"]

    assert vectors
    for vector in vectors:
        assert _resolve_grain(policy, vector["input"]) == (
            vector["expectedGrain"]
        ), vector["id"]

    assert policy["grainResolution"][
        "channelFilterDoesNotChangeTargetGrain"
    ] is True


def test_status_vectors_are_reproducible() -> None:
    policy = _policy()
    vectors = policy["statusTestVectors"]

    assert vectors
    for vector in vectors:
        assert _resolve_status(policy, vector["input"]) == (
            vector["expectedStatus"]
        ), vector["id"]

    expected = {vector["expectedStatus"] for vector in vectors}
    assert {"Strong", "Healthy", "Watch", "Action", "unavailable"} <= expected


def test_reference_html_sample_values_are_not_status_authority() -> None:
    policy = _policy()
    reference = policy["referenceHtmlPolicy"]

    assert reference["layoutAuthority"] is True
    assert reference["sampleCoverageAndStatusValuesAuthoritative"] is False

    # The reference mockup's h1 row (93.4% accuracy, -0.8% bias, 99.6%
    # coverage) is badged Strong in the HTML but is Action under decision #80
    # because its coverage exceeds the accepted 0.85-0.95 interval. Parity
    # review must compare layout, not the sample badge column.
    assert (
        _resolve_status(
            policy,
            {
                "grain": "market_portfolio",
                "horizon": 1,
                "accuracyPct": "93.4",
                "biasPct": "-0.8",
                "p90CoverageRatio": "0.996",
            },
        )
        == "Action"
    )


def test_react_implementation_deviation_is_resolved() -> None:
    """The React correction landed, so the deviation must record its closure.

    Live-value and screenshot parity stay unexercised while forecast serving is
    fail-closed, so the record must still carry that remaining obligation rather
    than claim full HTML parity.
    """

    health = _health_element()
    deviation = health["knownDeviation"]

    assert deviation["code"] == "PP3_B7_REACT_IMPLEMENTATION_PENDING"
    assert deviation["status"] == "resolved"
    assert deviation["resolvedOn"]
    assert deviation["previousBehavior"]
    assert "exact-horizon" in deviation["implementedBehavior"]
    assert "forecastHealthPolicy" in deviation["implementedBehavior"]
    assert deviation["remainingObligation"]
    assert health["referenceSamplePolicy"][
        "coverageAndBadgeValuesAuthoritative"
    ] is False
