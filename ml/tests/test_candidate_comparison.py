"""PP3-B4: C1/C2 candidates and the decision-#75 comparison gate."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from retail_ml.diagnostics.comparison import ComparisonError, compare_candidate
from retail_ml.models.bias_correction import (
    COVERAGE_MAX,
    COVERAGE_MIN,
    MIN_CELL_ROWS,
    CandidateError,
    OriginRoles,
    apply_bias_correction,
    apply_quantile_calibration,
    fit_bias_correction,
    fit_quantile_calibration,
    split_origins,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _frame(rows_per_cell: int = 300) -> pd.DataFrame:
    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        origin = first + timedelta(weeks=2 * origin_index)
        for horizon in (1, 13):
            for market in ("m1", "m2"):
                for index in range(rows_per_cell):
                    actual = 100.0 + (index % 5)
                    rows.append(
                        {
                            "forecast_origin": origin,
                            "market_id": market,
                            "sku_id": f"SKU-{index % 25}",
                            "store_id": f"{market}-store",
                            "channel_id": "store",
                            "horizon": horizon,
                            # Deliberately under-forecast by ~10%.
                            "yhat_p50": actual * 0.9,
                            # ~90% coverage so the fixture sits inside the
                            # 0.85-0.95 band; a 1.0-coverage fixture would trip
                            # COVERAGE_FAILURE on every comparison.
                            "yhat_p90": actual * (0.95 if index % 10 == 0 else 1.2),
                            "actual_units": actual,
                        }
                    )
    return pd.DataFrame(rows)


def test_origins_split_eight_and_five_without_overlap() -> None:
    roles = split_origins(_frame(rows_per_cell=2), development=8)

    assert len(roles.development) == 8
    assert len(roles.confirmation) == 5
    assert set(roles.development) & set(roles.confirmation) == set()


def test_overlapping_origin_roles_are_refused() -> None:
    with pytest.raises(CandidateError, match="overlap"):
        OriginRoles(development=("a", "b"), confirmation=("b",))


def test_c1_never_fits_on_a_confirmation_origin() -> None:
    """The leakage guard is the point of the split."""

    frame = _frame(rows_per_cell=2)
    roles = split_origins(frame, development=8)
    leaky = OriginRoles(
        development=tuple(sorted(frame["forecast_origin"].unique())),
        confirmation=(),
    )
    model = fit_bias_correction(frame, leaky)
    assert len(model["fitOrigins"]) == 13

    # With a real split, the fit population excludes the held-back origins.
    honest = fit_bias_correction(frame, roles)
    assert len(honest["fitOrigins"]) == 8
    for origin in roles.confirmation:
        assert str(origin) not in honest["fitOrigins"]


def test_c1_corrects_bias_and_preserves_the_domain() -> None:
    frame = _frame()
    roles = split_origins(frame, development=8)
    model = fit_bias_correction(frame, roles)
    corrected = apply_bias_correction(frame, model)

    def bias(data: pd.DataFrame) -> float:
        return float(
            (data["yhat_p50"] - data["actual_units"]).sum()
            / data["actual_units"].sum()
        )

    assert bias(frame) < -0.05
    assert abs(bias(corrected)) < abs(bias(frame))
    assert (corrected["yhat_p50"] >= 0).all()
    assert (corrected["yhat_p90"] >= corrected["yhat_p50"]).all()


def test_c1_shrinks_an_insufficient_cell_to_the_parent() -> None:
    # Cells aggregate across the 8 development origins, so keep 8*n < MIN_CELL_ROWS.
    frame = _frame(rows_per_cell=5)
    roles = split_origins(frame, development=8)
    model = fit_bias_correction(frame, roles)

    assert model["cellsShrunkToParent"] > 0
    shrunk = [cell for cell in model["cells"].values() if cell["shrunkToParent"]]
    assert shrunk
    for cell in shrunk:
        assert cell["sufficient"] is False
        assert cell["factor"] == pytest.approx(model["parentFactor"])


def test_c1_is_segmented_not_a_single_global_shift() -> None:
    """PP3-B3 measured mixed-sign bias, so one factor would harm some slices."""

    model = fit_bias_correction(_frame(), split_origins(_frame(), development=8))
    assert model["segmentColumns"] == ["market_id", "horizon"]
    assert len(model["cells"]) > 1


def test_c1_clamps_a_runaway_factor() -> None:
    frame = _frame()
    # One cell where the model predicted almost nothing.
    mask = (frame["market_id"] == "m1") & (frame["horizon"] == 1)
    frame.loc[mask, "yhat_p50"] = 0.01
    model = fit_bias_correction(frame, split_origins(frame, development=8))

    for cell in model["cells"].values():
        assert model["factorClamp"][0] <= cell["factor"] <= model["factorClamp"][1]


def test_c2_sharpens_without_inverting_quantiles() -> None:
    frame = _frame()
    roles = split_origins(frame, development=8)
    model = fit_quantile_calibration(frame, roles)
    calibrated = apply_quantile_calibration(frame, model)

    assert (calibrated["yhat_p90"] >= calibrated["yhat_p50"]).all()
    assert model["coverageBand"] == [COVERAGE_MIN, COVERAGE_MAX]
    # P50 is untouched, so WAPE cannot move.
    assert calibrated["yhat_p50"].equals(frame["yhat_p50"])


def test_c2_reports_fallback_use() -> None:
    frame = _frame(rows_per_cell=5)
    model = fit_quantile_calibration(frame, split_origins(frame, development=8))

    assert model["cellsUsingFallback"] > 0
    assert any(cell["usedFallback"] for cell in model["cells"].values())


# ---------------------------------------------------------------------------
# The decision-#75 gate.
# ---------------------------------------------------------------------------
def _compare(frame: pd.DataFrame, candidate: pd.DataFrame, candidate_id: str):
    roles = split_origins(frame, development=8)
    scored = frame.copy()
    scored["cand_p50"] = candidate["yhat_p50"].values
    scored["yhat_p90"] = candidate["yhat_p90"].values
    return compare_candidate(
        scored,
        candidate_column="cand_p50",
        candidate_id=candidate_id,
        development_origins=roles.development,
        confirmation_origins=roles.confirmation,
        repository_root=REPO_ROOT,
    )


def test_an_unregistered_candidate_cannot_be_scored() -> None:
    frame = _frame(rows_per_cell=2)
    with pytest.raises(ComparisonError, match="not a registered candidate family"):
        _compare(frame, frame, "C99")


def test_the_gate_reports_both_populations_independently() -> None:
    frame = _frame(rows_per_cell=4)
    result = _compare(frame, frame, "C1")
    populations = result["populations"]

    assert "all_13_origins" in populations
    assert "final_5_confirmation_origins" in populations
    assert "development_origins_diagnostic_only" in populations
    assert "confirmation-only gain is not evidence" in result["note"]


def test_an_unchanged_candidate_fails_the_materiality_floor() -> None:
    """Zero improvement is not a pass."""

    frame = _frame(rows_per_cell=4)
    result = _compare(frame, frame, "C1")
    all_13 = result["populations"]["all_13_origins"]

    assert all_13["relativeImprovementPct"] == pytest.approx(0.0)
    assert all_13["passed"] is False
    assert "MATERIALITY_ALL_13" in result["stopRulesTriggered"]
    assert result["accepted"] is False


def test_a_degrading_candidate_is_rejected() -> None:
    frame = _frame(rows_per_cell=4)
    worse = frame.copy()
    worse["yhat_p50"] = worse["yhat_p50"] * 0.5
    result = _compare(frame, worse, "C1")

    assert result["populations"]["all_13_origins"]["relativeImprovementPct"] < 0
    assert result["accepted"] is False


def test_a_quantile_inversion_is_a_stop_rule() -> None:
    frame = _frame(rows_per_cell=4)
    inverted = frame.copy()
    inverted["yhat_p90"] = inverted["yhat_p50"] * 0.5
    result = _compare(frame, inverted, "C1")

    assert result["quantilesMonotonic"] is False
    assert "QUANTILE_INVERSION" in result["stopRulesTriggered"]


def test_coverage_leaving_the_band_is_a_stop_rule() -> None:
    frame = _frame(rows_per_cell=4)
    narrow = frame.copy()
    # Collapse the interval so coverage falls out of 0.85-0.95.
    narrow["yhat_p90"] = narrow["yhat_p50"]
    result = _compare(frame, narrow, "C1")

    assert result["p90Coverage"] < COVERAGE_MIN
    assert "COVERAGE_FAILURE" in result["stopRulesTriggered"]


def test_the_cohort_key_hash_is_published_for_pairing() -> None:
    frame = _frame(rows_per_cell=4)
    result = _compare(frame, frame, "C1")

    assert len(result["cohortKeySha256"]) == 64


def test_a_real_improvement_can_pass_the_gate() -> None:
    """The gate must be satisfiable, or it would prove nothing."""

    frame = _frame(rows_per_cell=8)
    better = frame.copy()
    # The fixture under-forecasts by a uniform 10%. An honest candidate scales
    # the forecast and never reads actual_units, exactly as apply_bias_correction
    # does, recovering part of that gap: WAPE 0.10 -> 0.09, a 10% relative gain.
    # Both properties matter. A candidate blended from actual_units correlates
    # with the target by construction, and a 60%-of-error gain against an
    # already-fitted authority is not a size real modelling produces -- either
    # one now trips the gate's LEAKAGE stop rule, which is the behaviour a
    # first-draft top-down reconciliation earned.
    better["yhat_p50"] = frame["yhat_p50"] * (0.91 / 0.90)
    # A real candidate raises P90 to preserve monotonicity; otherwise the
    # improvement trips its own QUANTILE_INVERSION stop rule.
    better["yhat_p90"] = frame[["yhat_p90"]].join(better[["yhat_p50"]]).max(axis=1)
    result = _compare(frame, better, "C1")
    all_13 = result["populations"]["all_13_origins"]

    assert all_13["relativeImprovementPct"] > 5.0
    assert all_13["intervalUpperBoundBelowZero"] is True
    assert all_13["passed"] is True
    assert result["populations"]["final_5_confirmation_origins"]["passed"] is True
    assert result["accepted"] is True
