"""PP3-B5: segmented champions, hierarchical reconciliation, and leakage.

The leakage tests here exist because a first-draft top-down reconciliation in
this module disaggregated by each leaf's share of `actual_units` and the gate
reported +59.2% relative WAPE as `accepted`. Decision #75 listed LEAKAGE as a
stop rule, but nothing implemented it.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from retail_ml.diagnostics.comparison import (
    MAX_PLAUSIBLE_IMPROVEMENT_PCT,
    MAX_TARGET_CORRELATION_UPLIFT,
    MAX_TARGET_REPRODUCTION_WAPE,
    compare_candidate,
    detect_leakage,
)
from retail_ml.models.bias_correction import CandidateError, split_origins
from retail_ml.models.reconciliation import (
    C3_SEGMENT_COLUMNS,
    MIN_SEGMENT_ORIGINS,
    MIN_SEGMENT_ROWS,
    MIN_SEGMENT_SERIES,
    apply_segmented_champions,
    fit_segmented_champions,
    leaf_and_aggregate_quality,
    reconcile,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _frame(series_per_segment: int = 30) -> pd.DataFrame:
    rows = []
    first = date(2025, 8, 4)
    for origin_index in range(13):
        origin = first + timedelta(weeks=2 * origin_index)
        for market in ("m1", "m2"):
            for category in ("FOODS", "HOME"):
                for index in range(series_per_segment):
                    # Volumes must vary widely and errors must be mixed-sign,
                    # or aggregation cannot offset and the fixture would not
                    # exercise either the hierarchy or the leakage guard.
                    actual = float(5 + (index * 37) % 400)
                    signed = 1.0 if index % 2 == 0 else -1.0
                    predicted = max(actual * (1.0 + signed * 0.25), 0.0)
                    rows.append(
                        {
                            "forecast_origin": origin,
                            "market_id": market,
                            "category": category,
                            "sku_id": f"SKU-{index}",
                            "store_id": f"{market}-store",
                            "channel_id": "store",
                            "horizon": 1,
                            "actual_units": actual,
                            "yhat_p50": predicted,
                            "yhat_p90": (
                                predicted * 0.95
                                if index % 10 == 0
                                else max(predicted, actual) * 1.3
                            ),
                        }
                    )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# C3 scope and sufficiency.
# ---------------------------------------------------------------------------
def test_c3_is_scoped_to_the_causes_b3_ranked_material() -> None:
    """Segmenting an immaterial cause cannot satisfy the improvement floor."""

    model = fit_segmented_champions(_frame(), split_origins(_frame(), development=8))

    assert model["segmentColumns"] == list(C3_SEGMENT_COLUMNS)
    assert set(model["scopedToCauses"]) == {
        "H2_category_composition",
        "H4_cold_start",
    }
    assert "H3_intermittent_routing" in model["deliberatelyNotScopedTo"]
    assert "H8_model_pooling" in model["deliberatelyNotScopedTo"]
    assert "0.91%" in model["scopeRationale"]


def test_c3_sufficiency_rule_is_frozen_before_scoring() -> None:
    model = fit_segmented_champions(_frame(), split_origins(_frame(), development=8))
    rule = model["sufficiencyRule"]

    assert rule["frozenBeforeScoring"] is True
    assert rule["minimumRows"] == MIN_SEGMENT_ROWS
    assert rule["minimumSeriesKeys"] == MIN_SEGMENT_SERIES
    assert rule["minimumOrigins"] == MIN_SEGMENT_ORIGINS


def test_c3_shrinks_an_insufficient_segment_rather_than_overfitting_it() -> None:
    """A weak segment must not be handed a bespoke factor."""

    frame = _frame(series_per_segment=3)
    model = fit_segmented_champions(frame, split_origins(frame, development=8))

    assert model["segmentsShrunkToParent"] > 0
    for segment in model["segments"].values():
        if segment["shrunkToParent"]:
            assert segment["sufficient"] is False
            assert segment["factor"] == pytest.approx(model["parentFactor"])


def test_c3_never_fits_on_a_confirmation_origin() -> None:
    frame = _frame(series_per_segment=3)
    roles = split_origins(frame, development=8)
    model = fit_segmented_champions(frame, roles)

    assert len(model["fitOrigins"]) == 8
    for origin in roles.confirmation:
        assert str(origin) not in model["fitOrigins"]


def test_c3_preserves_the_domain_and_quantile_order() -> None:
    frame = _frame()
    model = fit_segmented_champions(frame, split_origins(frame, development=8))
    applied = apply_segmented_champions(frame, model)

    assert (applied["yhat_p50"] >= 0).all()
    assert (applied["yhat_p90"] >= applied["yhat_p50"]).all()


# ---------------------------------------------------------------------------
# C4 reconciliation.
# ---------------------------------------------------------------------------
def test_bottom_up_is_the_honest_control() -> None:
    """It changes nothing, so other methods must beat an identity."""

    frame = _frame(series_per_segment=3)
    reconciled = reconcile(frame, method="bottom_up")

    pd.testing.assert_series_equal(
        reconciled["yhat_p50"].astype(float),
        frame["yhat_p50"].astype(float),
        check_names=False,
    )


def test_top_down_refuses_to_disaggregate_by_the_target() -> None:
    """The exact defect this module shipped in its first draft."""

    frame = _frame(series_per_segment=3)
    with pytest.raises(CandidateError, match="leaks the target"):
        reconcile(frame, method="top_down")


def test_top_down_requires_the_share_column_to_exist() -> None:
    frame = _frame(series_per_segment=3)
    with pytest.raises(CandidateError, match="is absent"):
        reconcile(frame, method="top_down", share_column="not_a_column")


def test_top_down_works_from_an_origin_safe_share() -> None:
    frame = _frame(series_per_segment=3)
    # A share knowable at the origin: the model's own prior-level forecast.
    frame["origin_safe_share"] = frame["yhat_p50"]
    reconciled = reconcile(
        frame, method="top_down", share_column="origin_safe_share"
    )

    assert (reconciled["yhat_p50"] >= 0).all()
    assert (reconciled["yhat_p90"] >= reconciled["yhat_p50"]).all()


def test_unknown_reconciliation_method_is_refused() -> None:
    with pytest.raises(CandidateError, match="unknown reconciliation method"):
        reconcile(_frame(series_per_segment=2), method="magic")


def test_aggregate_is_easier_than_leaf_and_says_so() -> None:
    """Decision #78 forbids presenting the aggregate as SeriesKey accuracy."""

    quality = leaf_and_aggregate_quality(_frame(series_per_segment=5))
    levels = quality["levels"]

    assert levels["leaf_serieskey"]["wape"] is not None
    assert levels["market"]["wape"] <= levels["leaf_serieskey"]["wape"]
    assert quality["aggregateEasierThanLeaf"] is True
    assert "forbids presenting the aggregate" in quality["rule"]


# ---------------------------------------------------------------------------
# The leakage detector the gate was missing.
# ---------------------------------------------------------------------------
def test_the_detector_catches_a_target_derived_candidate() -> None:
    frame = _frame(series_per_segment=5)
    leaking = frame.copy()
    # Disaggregate the parent total by each leaf's share of the ACTUAL.
    parent = ["market_id", "category"]
    grouped = frame.groupby(parent, observed=True)["yhat_p50"].transform("sum")
    actual_total = frame.groupby(parent, observed=True)["actual_units"].transform("sum")
    share = np.where(actual_total > 0, frame["actual_units"] / actual_total, 0.0)
    leaking["cand_p50"] = (grouped * share).clip(lower=0.0)

    result = detect_leakage(leaking, "cand_p50", "yhat_p50")

    assert result["suspected"] is True
    assert result["relativeImprovementPct"] > MAX_PLAUSIBLE_IMPROVEMENT_PCT
    assert any("IMPLAUSIBLE_IMPROVEMENT" in signal for signal in result["signals"])


def test_a_candidate_that_is_the_target_is_caught() -> None:
    frame = _frame(series_per_segment=5)
    frame["cand_p50"] = frame["actual_units"]

    result = detect_leakage(frame, "cand_p50", "yhat_p50")

    assert result["suspected"] is True
    assert result["candidateWape"] < MAX_TARGET_REPRODUCTION_WAPE
    assert result["candidateTargetCorrelationUplift"] > MAX_TARGET_CORRELATION_UPLIFT
    assert any("REPRODUCES_TARGET" in signal for signal in result["signals"])


def test_an_honest_rescale_is_not_flagged_however_correlated_the_authority_is() -> None:
    """The reason the correlation signal is uplift and not an absolute ceiling.

    A competent forecast already tracks its target closely. Scaling it cannot
    reveal anything new -- Pearson correlation is scale-invariant -- so the uplift
    is exactly zero and an absolute ceiling would have rejected it anyway.
    """

    frame = _frame(series_per_segment=5)
    frame["cand_p50"] = frame["yhat_p50"] * 1.08

    result = detect_leakage(frame, "cand_p50", "yhat_p50")

    assert result["candidateTargetCorrelationUplift"] == pytest.approx(0.0, abs=1e-9)
    assert result["suspected"] is False


def test_the_detector_stays_silent_on_a_plausible_candidate() -> None:
    """A guard that blocks honest gains would be worse than none."""

    frame = _frame(series_per_segment=5)
    # Perturb the model's own forecast only. A candidate built from
    # `actual_units` -- even a modest one -- is leakage by construction, which is
    # a trap my own first fixture fell into.
    frame["cand_p50"] = frame["yhat_p50"] * 0.97

    result = detect_leakage(frame, "cand_p50", "yhat_p50")

    assert result["suspected"] is False
    assert result["signals"] == []


def test_leakage_becomes_a_stop_rule_in_the_gate() -> None:
    frame = _frame(series_per_segment=5)
    roles = split_origins(frame, development=8)
    scored = frame.copy()
    scored["cand_p50"] = frame["actual_units"]
    scored["yhat_p90"] = np.maximum(frame["yhat_p90"], scored["cand_p50"])

    result = compare_candidate(
        scored,
        candidate_column="cand_p50",
        candidate_id="C4",
        development_origins=roles.development,
        confirmation_origins=roles.confirmation,
        repository_root=REPO_ROOT,
    )

    assert "LEAKAGE" in result["stopRulesTriggered"]
    assert result["accepted"] is False
    assert result["leakage"]["suspected"] is True
