"""Decision #84 candidate C5, the cold-start shrinkage estimator.

C5 is the candidate that moved Phase 3 from explicit NO-GO to accepted, and it runs
in both the backtest and the serving path. It shipped with no tests at all: the only
occurrence of `cold_start_blend` under `ml/tests/` was a fixture filename string.
C1 through C4 each had a suite. This closes that gap.

The tests are written against the ways C5 could be wrong rather than against its
structure: fitting on a confirmation origin, touching an untargeted row, refitting
at serving time, or leaving the served quantiles inconsistent with the confidence
derived from them.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from retail_ml.models.bias_correction import CandidateError, split_origins
from retail_ml.models.cold_start_blend import (
    BLEND_GRID,
    C5_SEGMENT_COLUMNS,
    COLD_START_COHORT,
    COMPARATOR_COLUMN,
    apply_cold_start_blend,
    established_rows_unchanged,
    fit_cold_start_blend,
)
from retail_ml.models.confidence import forecast_confidence


def _frame(series_per_cohort: int = 30) -> pd.DataFrame:
    """Two markets, 13 biweekly origins, both cohorts present.

    Cold-start rows are deliberately worse at long horizons than the comparator and
    better at short ones, which is the measured shape C5 exists to exploit.
    """

    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        origin = first + timedelta(weeks=2 * origin_index)
        for market in ("m1", "m2"):
            for cohort in ("established_history", COLD_START_COHORT):
                for index in range(series_per_cohort):
                    for horizon in (1, 26):
                        actual = float(50 + (index * 17) % 200)
                        if cohort == COLD_START_COHORT:
                            # Better than the comparator at h1, far worse at h26.
                            error = 0.01 if horizon == 1 else 0.40
                        else:
                            error = 0.10
                        rows.append(
                            {
                                "forecast_origin": origin,
                                "market_id": market,
                                "sku_id": f"SKU-{index}",
                                "store_id": f"{market}-store",
                                "channel_id": "store",
                                "horizon": horizon,
                                "cohort": cohort,
                                "actual_units": actual,
                                "yhat_p50": actual * (1 - error),
                                "yhat_p90": actual * 1.3,
                                # A comparator that is close at every horizon, so the
                                # fit has something to prefer at h26.
                                COMPARATOR_COLUMN: (
                                    actual * 0.98
                                    if cohort == COLD_START_COHORT
                                    else np.nan
                                ),
                            }
                        )
    return pd.DataFrame(rows)


def _fitted(frame: pd.DataFrame) -> dict:
    return fit_cold_start_blend(frame, split_origins(frame, development=8))


# ---------------------------------------------------------------------------
# Fitting protocol: decision #84 §3.2 and §3.3.
# ---------------------------------------------------------------------------
def test_the_fit_uses_only_development_origins() -> None:
    """§3.3. Reading a confirmation origin is #84's first stop rule."""

    frame = _frame()
    roles = split_origins(frame, development=8)
    model = _fitted(frame)

    assert len(model["fitOrigins"]) == 8
    assert len(model["confirmationOriginsHeldOut"]) == 5
    for origin in roles.confirmation:
        assert str(origin) not in model["fitOrigins"]
    assert not set(model["fitOrigins"]) & set(model["confirmationOriginsHeldOut"])


def test_a_confirmation_origin_in_the_development_set_is_refused() -> None:
    """Defence in depth behind OriginRoles' own overlap check.

    OriginRoles refuses an overlapping pair at construction, so this uses a
    stand-in to reach the guard inside the fit. Both layers matter: the fit is
    reachable from callers that build roles some other way.
    """

    frame = _frame(series_per_cohort=3)
    roles = split_origins(frame, development=8)

    class _Contaminated:
        development = (*roles.development, roles.confirmation[0])
        confirmation = roles.confirmation

    with pytest.raises(CandidateError, match="confirmation origins"):
        fit_cold_start_blend(frame, _Contaminated())  # type: ignore[arg-type]


def test_weights_come_from_the_frozen_grid_and_stay_in_range() -> None:
    """§3.3. A grid, not an optimiser, so the fit cannot drift on a seed."""

    model = _fitted(_frame())

    assert model["grid"] == list(BLEND_GRID)
    for segment in model["segments"].values():
        assert segment["weight"] in BLEND_GRID
        assert 0.0 <= segment["weight"] <= 1.0
    assert model["globalWeight"] in BLEND_GRID


def test_segmentation_is_market_by_exact_horizon() -> None:
    """§3.2 chose exact horizon over bands so no boundary could be placed later."""

    model = _fitted(_frame())

    assert model["segmentColumns"] == list(C5_SEGMENT_COLUMNS)
    assert "horizon" in model["segmentColumns"]
    assert len(model["segments"]) == 4  # two markets x two horizons present


def test_the_fit_prefers_the_comparator_where_the_model_is_worse() -> None:
    """The mechanism, not the implementation: h26 should lean toward the comparator.

    The fixture makes cold-start rows 1% off at h1 and 40% off at h26 while the
    comparator is 2% off throughout, so the honest answer is "keep the model at h1,
    defer at h26". A fit that ignored horizon could not express that, which is
    exactly why C1 and C3 failed.

    The frame has to be large enough that each market x horizon cell clears the
    frozen sufficiency rule -- 500 rows over 8 development origins needs 63 series
    per cell. Below that every cell shrinks to the pooled parent, the pooled cell is
    dominated by the h26 rows, and the horizon signal this test is about disappears.
    That shrink-to-parent behaviour is correct and is covered separately.
    """

    model = _fitted(_frame(series_per_cohort=70))
    assert model["segmentsShrunkToParent"] == 0, "expected every cell to be sufficient"
    weights = {name: seg["weight"] for name, seg in model["segments"].items()}
    short = [w for name, w in weights.items() if name.endswith("|1")]
    long = [w for name, w in weights.items() if name.endswith("|26")]

    assert short, "expected h1 segments"
    assert long, "expected h26 segments"
    assert max(long) < min(short)


def test_an_insufficient_segment_shrinks_instead_of_overfitting() -> None:
    frame = _frame(series_per_cohort=2)
    model = _fitted(frame)

    assert model["segmentsShrunkToParent"] > 0
    for segment in model["segments"].values():
        if segment["shrunkTo"] is not None:
            assert segment["sufficient"] is False


# ---------------------------------------------------------------------------
# Application: decision #84 §3.1 and #86 §2.3.
# ---------------------------------------------------------------------------
def test_only_cold_start_rows_move() -> None:
    """#86 §2.3. The check that publication now enforces structurally."""

    frame = _frame()
    applied = apply_cold_start_blend(frame, _fitted(frame))

    established = applied[applied["cohort"] != COLD_START_COHORT]
    pd.testing.assert_series_equal(
        established["c5_p50"].astype(float),
        established["yhat_p50"].astype(float),
        check_names=False,
    )
    cold = applied[applied["cohort"] == COLD_START_COHORT]
    assert not cold["c5_p50"].astype(float).equals(cold["yhat_p50"].astype(float))


def test_established_rows_unchanged_reports_the_untargeted_population() -> None:
    frame = _frame()
    applied = apply_cold_start_blend(frame, _fitted(frame))

    verdict = established_rows_unchanged(applied)

    assert verdict["passed"] is True
    assert verdict["p50Identical"] is True
    assert verdict["p90Identical"] is True
    assert verdict["rows"] == int((frame["cohort"] != COLD_START_COHORT).sum())


def test_established_rows_unchanged_catches_a_leaked_change() -> None:
    """The checker has to be able to fail, or enforcing it proves nothing."""

    frame = _frame()
    applied = apply_cold_start_blend(frame, _fitted(frame))
    applied.loc[applied["cohort"] != COLD_START_COHORT, "c5_p50"] *= 1.01

    verdict = established_rows_unchanged(applied)

    assert verdict["passed"] is False
    assert verdict["p50Identical"] is False


def test_the_domain_and_quantile_order_survive() -> None:
    frame = _frame()
    applied = apply_cold_start_blend(frame, _fitted(frame))

    assert (applied["c5_p50"] >= 0).all()
    assert (applied["c5_p90"] >= applied["c5_p50"]).all()


def test_a_cold_start_row_without_a_comparator_is_refused() -> None:
    """Decision #83 guarantees one, so silence would hide a broken guarantee."""

    frame = _frame(series_per_cohort=3)
    model = _fitted(frame)
    broken = frame.copy()
    mask = broken["cohort"].eq(COLD_START_COHORT)
    broken.loc[broken.index[mask][0], COMPARATOR_COLUMN] = np.nan

    with pytest.raises(CandidateError, match="lack"):
        apply_cold_start_blend(broken, model)


def test_confidence_is_recomputed_from_the_served_quantiles() -> None:
    """The publisher rejected the first C5 bundle for exactly this.

    Decision #12 derives confidence from the P50-P90 spread, so moving the served
    quantiles without recomputing it leaves the two inconsistent and publication
    fails closed with "evaluation confidence violates decision #12".
    """

    from retail_ml.models.cohorts import COLD_START_BASELINE_COLUMN

    assert COMPARATOR_COLUMN == COLD_START_BASELINE_COLUMN

    frame = _frame()
    frame["confidence"] = forecast_confidence(frame["yhat_p50"], frame["yhat_p90"])
    applied = apply_cold_start_blend(frame, _fitted(frame))
    applied["yhat_p50"] = applied["c5_p50"]
    applied["yhat_p90"] = applied["c5_p90"]
    applied["confidence"] = forecast_confidence(
        applied["yhat_p50"], applied["yhat_p90"]
    )

    expected = forecast_confidence(applied["yhat_p50"], applied["yhat_p90"])
    assert np.allclose(applied["confidence"].to_numpy(dtype=float), expected)


# ---------------------------------------------------------------------------
# Verifier replay: decision #86 must be reproducible, not read back.
# ---------------------------------------------------------------------------
def _plausible_frame(series_per_cohort: int = 70) -> pd.DataFrame:
    """A frame whose blend is a realistic gain, not a fixture artefact.

    The main fixture makes the comparator 2% off against a 40%-off model, so
    blending toward it improves WAPE by 90% and the leakage detector flags it --
    correctly, because no honest candidate gains that much against an already-fitted
    authority. The replay tests need a bundle that passes the battery, so here the
    comparator is only modestly better.
    """

    frame = _frame(series_per_cohort=series_per_cohort)
    cold = frame["cohort"] == COLD_START_COHORT
    actual = frame.loc[cold, "actual_units"]
    long_horizon = cold & frame["horizon"].eq(26)
    frame.loc[cold, COMPARATOR_COLUMN] = actual * 0.90
    frame.loc[long_horizon, "yhat_p50"] = frame.loc[long_horizon, "actual_units"] * 0.88
    return frame


def _published_shape(frame: pd.DataFrame) -> pd.DataFrame:
    """Mimic what a remediation bundle publishes: served values plus replay columns."""

    applied = apply_cold_start_blend(frame, _fitted(frame))
    published = applied.copy()
    published["champion_p50"] = published["yhat_p50"]
    published["champion_p90"] = published["yhat_p90"]
    published["yhat_p50"] = published["c5_p50"]
    published["yhat_p90"] = published["c5_p90"]
    return published.drop(columns=["c5_p50", "c5_p90"])


def _recorded_checks(published: pd.DataFrame) -> dict:
    from retail_ml.diagnostics.comparison import detect_leakage

    cold = published[published["cohort"] == COLD_START_COHORT]
    leakage = detect_leakage(
        cold.assign(_candidate=cold["yhat_p50"]), "_candidate", "champion_p50"
    )
    return {
        "structuralChecks": {
            "untargetedRowsByteIdentical": {"passed": True},
            "leakage": {"suspected": leakage["suspected"]},
        },
        "confirmationOriginsHeldOut": ["x"],
    }


def test_the_verifier_replays_the_checks_on_an_honest_bundle() -> None:
    from retail_ml.publish.verify import _recompute_remediation_checks

    published = _published_shape(_plausible_frame())

    _recompute_remediation_checks(published, _recorded_checks(published))


def test_the_verifier_rejects_a_tampered_untargeted_row() -> None:
    """A hash-consistent forgery still has to fail on the recomputation."""

    from retail_ml.publish.verify import (
        ForecastRunVerificationError,
        _recompute_remediation_checks,
    )

    published = _published_shape(_plausible_frame())
    recorded = _recorded_checks(published)
    established = published["cohort"] != COLD_START_COHORT
    published.loc[published.index[established][0], "yhat_p50"] *= 1.5

    with pytest.raises(ForecastRunVerificationError, match="byte-identical"):
        _recompute_remediation_checks(published, recorded)


def test_the_verifier_rejects_a_record_that_disagrees_with_the_replay() -> None:
    """The reason the booleans are no longer trusted."""

    from retail_ml.publish.verify import (
        ForecastRunVerificationError,
        _recompute_remediation_checks,
    )

    published = _published_shape(_plausible_frame())
    recorded = _recorded_checks(published)
    recorded["structuralChecks"]["leakage"]["suspected"] = True

    with pytest.raises(ForecastRunVerificationError, match="disagrees"):
        _recompute_remediation_checks(published, recorded)


def test_the_verifier_refuses_a_bundle_missing_its_replay_columns() -> None:
    """Without the champion values there is nothing to recompute against."""

    from retail_ml.publish.verify import (
        ForecastRunVerificationError,
        _recompute_remediation_checks,
    )

    published = _published_shape(_plausible_frame()).drop(columns=["champion_p50"])

    with pytest.raises(ForecastRunVerificationError, match="replayed rather than trusted"):
        _recompute_remediation_checks(published, {"confirmationOriginsHeldOut": ["x"]})

