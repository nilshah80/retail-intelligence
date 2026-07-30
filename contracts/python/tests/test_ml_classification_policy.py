import json
from pathlib import Path

from retail_contracts.fingerprint import semantic_fingerprint


REPO_ROOT = Path(__file__).resolve().parents[3]
POLICY = REPO_ROOT / "contracts/ml/forecast-classification-policy.json"


def _policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


def test_decision_60_policy_sections_are_immutably_fingerprinted() -> None:
    policy = _policy()

    assert policy["schemaVersion"] == (
        "retail-forecast-classification-policy/v1"
    )
    assert policy["decisionId"] == 60
    for name in ("exceptions", "dataQuality"):
        section = dict(policy[name])
        recorded = section.pop("semanticFingerprint")
        assert semantic_fingerprint(section, volatile_pointers=()) == recorded


def test_decision_60_freezes_all_visible_classifications() -> None:
    policy = _policy()

    assert set(policy["exceptions"]["classes"]) == {
        "high_under_forecast_risk",
        "high_over_forecast_risk",
        "new_product_sparse_history",
        "promotion_uplift_conflict",
        "data_quality_exception",
    }
    promotion = policy["exceptions"]["classes"][
        "promotion_uplift_conflict"
    ]["unavailableBehavior"]
    assert promotion == {
        "emitException": False,
        "reasonCode": "NO_ORIGIN_VISIBLE_PROMOTION_PLAN",
        "renderingState": "unavailable",
    }
    assert policy["dataQuality"]["reduction"]["precedence"] == [
        "Issue",
        "Watch",
        "Good",
    ]
