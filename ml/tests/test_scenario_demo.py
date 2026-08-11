from pathlib import Path

import pytest
from retail_contracts.scenario_assumptions import (
    load_scenario_assumption_bundle,
    may_receive_serving_approval,
)

from retail_ml.scenario.context import ScenarioAuthority
from retail_ml.scenario.demo import _require_local_demo_bundle, activate_local_demo
from retail_ml.scenario.postgres import ScenarioServingError


REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_BUNDLE = (
    REPO_ROOT
    / "contracts"
    / "scenarios"
    / "forecast_scenario_local_demo_gulf_india.yaml"
)


def test_local_demo_bundle_is_complete_and_explicitly_labelled() -> None:
    bundle = load_scenario_assumption_bundle(DEMO_BUNDLE)

    _require_local_demo_bundle(bundle)

    assert may_receive_serving_approval(bundle) is True
    assert {row["deptId"] for row in bundle["tierCoefficients"]} == {
        "adjacent-new-energy",
        "automotive-engine-oils",
        "driveline-specialities",
        "industrial-lubricants",
    }
    assert {row["marketId"] for row in bundle["marketCurrencyRules"]} == {
        "gulf-india"
    }


def test_local_demo_activation_refuses_every_nonlocal_environment() -> None:
    with pytest.raises(
        ScenarioServingError,
        match="forbidden outside environment=local",
    ):
        activate_local_demo(
            postgres_dsn="unused",
            curated_root="unused",
            authority=ScenarioAuthority(
                retailer_id="retailer-demo",
                tenant_id="tenant-demo",
                capability="forecast_scenario_v1",
                environment="production",
            ),
            forecast_activation_scope_fingerprint="a" * 64,
            assumption_bundle_path=DEMO_BUNDLE,
            actor="local-demo-bootstrap",
            decision_reference="LOCAL_DEMO_ONLY",
        )


def test_local_demo_guard_refuses_an_unlabelled_serving_candidate() -> None:
    bundle = load_scenario_assumption_bundle(DEMO_BUNDLE)
    bundle["assumptionSetId"] = "fsa_production_v1"

    with pytest.raises(ScenarioServingError, match="explicitly labelled"):
        _require_local_demo_bundle(bundle)
