"""PP3-B1/B2: the improvement policy is frozen and D0 cannot authorize serving."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from retail_ml.diagnostics.baseline import (
    BASELINE_SCHEMA_VERSION,
    REQUIRED_RECOMPUTATION,
    DiagnosticBaselineError,
    build_diagnostic_baseline,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY = REPO_ROOT / "contracts/ml/forecast-improvement-policy.json"


@pytest.fixture(scope="module")
def policy() -> dict:
    return json.loads(POLICY.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# PP3-B1: the policy is frozen before any candidate exists.
# ---------------------------------------------------------------------------
def test_the_policy_is_frozen_before_results_exist(policy: dict) -> None:
    assert policy["status"] == "frozen_before_any_candidate_exists"
    assert policy["decisionIds"] == [74, 75]
    forbidden = " ".join(policy["forbidden"]).lower()
    assert "after a candidate result is visible" in forbidden


def test_origin_roles_split_eight_and_five(policy: dict) -> None:
    roles = policy["originRoles"]
    assert roles["developmentOrigins"]["count"] == 8
    assert roles["confirmationOrigins"]["count"] == 5
    assert roles["acceptanceSchedule"]["origins"] == 13
    # Acceptance stays partly in-sample, so both populations must be reported.
    assert set(policy["materiality"]["reportedPopulations"]) == {
        "all_13_origins",
        "final_5_confirmation_origins",
    }


def test_materiality_thresholds_are_explicit(policy: dict) -> None:
    materiality = policy["materiality"]
    assert materiality["minimumGlobalImprovementPct"] == 5.0
    assert materiality["perMarketNonRegression"]["maximumRelativeWapeRegressionPct"] == 1.0
    bootstrap = materiality["bootstrap"]
    assert bootstrap["unit"] == "SeriesKey"
    assert bootstrap["clustered"] is True
    assert bootstrap["seed"] == 20260730
    assert bootstrap["requirement"] == "candidate_minus_authority_upper_bound_below_zero"


def test_pairing_requires_identical_cohort_keys(policy: dict) -> None:
    pairing = policy["pairing"]
    assert pairing["cohortKeysMustBeIdentical"] is True
    assert "hard failure" in pairing["rule"]


def test_all_three_superseded_runs_are_permanently_excluded(policy: dict) -> None:
    excluded = " ".join(policy["comparisonAuthority"]["rejectedForever"])
    for run in ("fr_b2f18d0e2999a36d", "fr_ab5be7296a2c416e", "fr_92135aa7b5215b69"):
        assert run in excluded


def test_stop_rules_cover_the_ways_a_gain_can_be_fake(policy: dict) -> None:
    ids = {rule["id"] for rule in policy["stopRules"]}
    assert {
        "LEAKAGE",
        "POPULATION_CHANGED",
        "COVERAGE_FAILURE",
        "MARKET_FAILURE",
        "CONFIRMATION_PEEKED",
        "SIMPSONS_PARADOX",
    } <= ids


def test_only_registered_candidate_families_may_be_scored(policy: dict) -> None:
    registry = policy["candidateRegistry"]
    assert registry["searchBudgetConfigurations"] == 20
    assert registry["candidatesAdvanced"] == 1
    assert registry["preRegistrationRequired"] is True
    assert "may not be scored" in registry["rule"]


# ---------------------------------------------------------------------------
# PP3-B2: D0 construction refuses anything that could authorize serving.
# ---------------------------------------------------------------------------
def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        origin = first + timedelta(weeks=2 * origin_index)
        for horizon in (1, 4, 8, 13, 26):
            rows.append(
                {
                    "forecast_origin": origin,
                    "target_week_start": origin + timedelta(weeks=horizon),
                    "market_id": "india-west",
                    "sku_id": "SKU-1",
                    "store_id": "store-1",
                    "channel_id": "store",
                    "horizon": horizon,
                    "category": "FOODS",
                    "selected_model": "lightgbm_horizon_quantile",
                    "actual_units": 10.0,
                    "yhat_p50": 9.0,
                    "yhat_p90": 12.0,
                    "zero_share_52w": 0.1,
                }
            )
    evaluation = pd.DataFrame(rows)
    keys = [
        "forecast_origin",
        "target_week_start",
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "horizon",
    ]
    baselines = pd.concat(
        [
            evaluation[keys].assign(baseline_id=name, prediction=value)
            for name, value in (
                ("seasonal_naive", 5.0),
                ("cold_start_mean", 6.0),
                ("naive", 8.0),
                ("ma8", 8.0),
                ("ma13", 8.0),
            )
        ],
        ignore_index=True,
    )
    return evaluation, baselines


def _manifest(**overrides) -> dict:
    manifest = {
        "forecastRunId": "fr_test",
        "lifecycleStatus": "rejected",
        "semanticFingerprint": "a" * 64,
        "featureSemanticFingerprint": "b" * 64,
        "modelPolicy": {"acceptanceEvaluation": REQUIRED_RECOMPUTATION},
    }
    manifest.update(overrides)
    return manifest


def test_a_rejected_run_becomes_d0_and_authorizes_nothing() -> None:
    evaluation, baselines = _frames()
    baseline = build_diagnostic_baseline(
        {"schemaVersion": "retail-forecast-acceptance/v4", "passed": False},
        _manifest(),
        evaluation,
        baselines,
        authority="D0",
    )

    assert baseline["schemaVersion"] == BASELINE_SCHEMA_VERSION
    assert baseline["authority"] == "D0"
    assert baseline["servingAuthorized"] is False
    assert baseline["publicationAuthorized"] is False
    assert "never authorizes" in baseline["note"]
    assert baseline["semanticFingerprint"]


def test_an_accepted_run_cannot_be_published_as_d0() -> None:
    evaluation, baselines = _frames()
    with pytest.raises(DiagnosticBaselineError, match="published as C0"):
        build_diagnostic_baseline(
            {"schemaVersion": "retail-forecast-acceptance/v4", "passed": True},
            _manifest(lifecycleStatus="accepted"),
            evaluation,
            baselines,
            authority="D0",
        )


def test_a_rejected_run_cannot_be_promoted_to_c0() -> None:
    evaluation, baselines = _frames()
    with pytest.raises(DiagnosticBaselineError, match="C0 requires an accepted run"):
        build_diagnostic_baseline(
            {"schemaVersion": "retail-forecast-acceptance/v4", "passed": False},
            _manifest(),
            evaluation,
            baselines,
            authority="C0",
        )


def test_a_run_outside_the_current_authority_is_refused() -> None:
    """The three superseded runs cannot become a comparison authority."""

    evaluation, baselines = _frames()
    stale = _manifest(
        modelPolicy={
            "acceptanceEvaluation": "paired-seasonal-independent-recomputation/v2"
        }
    )
    with pytest.raises(DiagnosticBaselineError, match="not governed by the current"):
        build_diagnostic_baseline(
            {"schemaVersion": "retail-forecast-acceptance/v2", "passed": True},
            stale,
            evaluation,
            baselines,
            authority="D0",
        )


def test_the_baseline_separates_development_and_confirmation_origins() -> None:
    evaluation, baselines = _frames()
    baseline = build_diagnostic_baseline(
        {"schemaVersion": "retail-forecast-acceptance/v4", "passed": False},
        _manifest(),
        evaluation,
        baselines,
        authority="D0",
    )
    roles = baseline["originRoles"]

    assert len(roles["developmentOrigins"]) == 8
    assert len(roles["confirmationOrigins"]) == 5
    assert set(roles["developmentOrigins"]) & set(roles["confirmationOrigins"]) == set()


def test_a_zero_actual_slice_is_insufficient_evidence_not_a_pass() -> None:
    evaluation, baselines = _frames()
    evaluation.loc[evaluation["horizon"] == 26, "actual_units"] = 0.0
    baseline = build_diagnostic_baseline(
        {"schemaVersion": "retail-forecast-acceptance/v4", "passed": False},
        _manifest(),
        evaluation,
        baselines,
        authority="D0",
    )

    assert baseline["slices"]["horizon"]["h26"]["verdict"] == "insufficient_evidence"
    assert baseline["slices"]["horizon"]["h1"]["verdict"] == "measured"


def test_cohort_key_hashes_are_published_for_pairing() -> None:
    evaluation, baselines = _frames()
    baseline = build_diagnostic_baseline(
        {"schemaVersion": "retail-forecast-acceptance/v4", "passed": False},
        _manifest(),
        evaluation,
        baselines,
        authority="D0",
    )
    cohorts = baseline["cohorts"]

    assert len(cohorts["establishedHistory"]["keySha256"]) == 64
    assert len(cohorts["coldStart"]["keySha256"]) == 64
    assert cohorts["establishedHistory"]["keySha256"] != cohorts["coldStart"][
        "keySha256"
    ]
