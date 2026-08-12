from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pandas as pd

from retail_ml.pricing.panel import load_response_policy
from retail_ml.pricing.response import (
    assess_response_series,
    fit_poisson,
    poisson_deviance,
    run_response_assessment,
)


ROOT = Path(__file__).resolve().parents[2]


def _series(*, grade: str = "source_native", beta: float = -1.25) -> pd.DataFrame:
    weeks = pd.date_range("2020-01-06", "2026-06-22", freq="W-MON", tz="UTC")
    index = np.arange(len(weeks), dtype=float)
    episode = (index // 13).astype(int)
    prices = np.asarray([18_000, 20_000, 22_000, 19_000, 21_000], dtype=float)[episode % 5]
    promotions = ((episode + 1) % 7 == 0).astype(float)
    angle = 2 * np.pi * weeks.isocalendar().week.to_numpy(dtype=float) / 52.1775
    linear_predictor = (
        4.8
        + beta * (np.log(prices) - np.log(20_000))
        + 0.12 * promotions
        + 0.08 * np.sin(angle)
        - 0.04 * np.cos(angle)
        + index * 0.0004
    )
    rng = np.random.default_rng(9876)
    units = rng.poisson(np.exp(linear_predictor))
    return pd.DataFrame(
        {
            "market_id": "gulf-india",
            "sku_id": "sku-1",
            "store_id": "store-1",
            "channel_id": "store",
            "channel_type": "store",
            "department_id": "dept-1",
            "category": "Engine Oil",
            "product_name": "Synthetic response fixture",
            "currency_code": "INR",
            "week_start": weeks,
            "units": units,
            "store_shortfall_units": np.zeros(len(weeks), dtype=int),
            "store_shortfall_share": np.zeros(len(weeks), dtype=float),
            "store_availability_constrained": np.zeros(len(weeks), dtype=bool),
            "regular_price_minor": prices.astype(int),
            "promotion_flag": promotions.astype(bool),
            "price_evidence_grade": grade,
            "price_known_as_of": weeks,
            "sales_known_as_of": weeks + pd.Timedelta(days=7),
            "availability_known_as_of": weeks + pd.Timedelta(days=7),
            "decision_as_of": pd.Timestamp("2026-06-26", tz="UTC"),
        }
    )


def test_poisson_fit_recovers_negative_log_price_response() -> None:
    frame = _series()
    x = np.column_stack(
        [np.ones(len(frame)), np.log(frame["regular_price_minor"] / 20_000)]
    )
    fit = fit_poisson(frame["units"].to_numpy(), x)

    assert fit.converged
    assert -1.6 < fit.coefficients[1] < -0.9
    assert poisson_deviance(frame["units"].to_numpy(), fit.fitted_mean) >= 0


def test_assessment_scores_all_frozen_origins_and_recovers_beta() -> None:
    policy = load_response_policy(ROOT / "contracts/pricing/response-evaluation.json")
    result = assess_response_series(_series(), policy)

    assert result["first_failure_reason"] is None
    assert result["disposition"] == "accepted"
    assert -1.6 < result["raw_beta"] < -0.9
    assert len(result["origin_diagnostics"]) == 13
    assert [row["index"] for row in result["origin_diagnostics"]] == list(range(1, 14))
    assert result["valid_resample_draws"] == 200


def test_backfilled_price_evidence_is_refused_before_fit() -> None:
    policy = load_response_policy(ROOT / "contracts/pricing/response-evaluation.json")
    result = assess_response_series(_series(grade="landing_backfill"), policy)

    assert result["disposition"] == "insufficient_evidence"
    assert result["first_failure_reason"] == "LANDING_BACKFILL_DEPENDENCY"
    assert result["raw_beta"] is None


def test_non_negative_beta_is_rejected_by_strict_gate() -> None:
    policy = deepcopy(
        load_response_policy(ROOT / "contracts/pricing/response-evaluation.json")
    )
    result = assess_response_series(_series(beta=0.8), policy)

    assert result["disposition"] == "rejected"
    assert result["first_failure_reason"] in {
        "BETA_SIGN_REJECTED",
        "HOLDOUT_IMPROVEMENT_REJECTED",
    }


def test_candidate_selection_uses_development_only_and_keeps_the_control_baseline() -> None:
    policy = load_response_policy(ROOT / "contracts/pricing/response-evaluation.json")
    original = _series()
    changed_confirmation = original.copy()
    confirmation = changed_confirmation["week_start"] >= pd.Timestamp(
        "2025-03-31", tz="UTC"
    )
    changed_confirmation.loc[confirmation, "units"] = (
        changed_confirmation.loc[confirmation, "units"] * 3 + 17
    )

    first = run_response_assessment(original, policy).iloc[0]
    second = run_response_assessment(changed_confirmation, policy).iloc[0]
    first_selection = json.loads(first["candidate_selection_diagnostics"])
    second_selection = json.loads(second["candidate_selection_diagnostics"])

    assert first_selection == second_selection
    assert first_selection["candidateCount"] == 3
    assert first_selection["developmentOrigins"] == list(range(1, 9))
    assert first_selection["confirmationOriginsRead"] == []
    assert first_selection["status"] == "selected"
    assert first["selected_configuration_id"] == first_selection[
        "selectedConfigurationId"
    ]
    origins = json.loads(first["origin_diagnostics"])
    assert {origin["baselineSpecification"] for origin in origins} == {
        "same_controls_without_log_price"
    }


def test_one_invalid_series_is_reason_coded_without_stopping_other_series() -> None:
    policy = load_response_policy(ROOT / "contracts/pricing/response-evaluation.json")
    valid = _series()
    invalid = _series().assign(sku_id="sku-2", week_start="not-a-date")
    baseline = run_response_assessment(valid, policy).set_index("sku_id")

    result = run_response_assessment(
        pd.concat([valid, invalid], ignore_index=True), policy
    ).set_index("sku_id")

    assert result.loc["sku-1", "disposition"] == baseline.loc[
        "sku-1", "disposition"
    ]
    assert result.loc["sku-1", "first_failure_reason"] == baseline.loc[
        "sku-1", "first_failure_reason"
    ]
    assert result.loc["sku-2", "disposition"] == "rejected"
    assert (
        result.loc["sku-2", "first_failure_reason"]
        == "RESPONSE_SERIES_EVALUATION_EXCEPTION"
    )
    assert json.loads(result.loc["sku-2", "origin_diagnostics"]) == [
        {
            "reasonCode": "RESPONSE_SERIES_EVALUATION_EXCEPTION",
            "status": "exception",
        }
    ]
