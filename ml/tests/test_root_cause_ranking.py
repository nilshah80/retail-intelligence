"""PP3-B3: causes are ranked by recoverable error mass, not by WAPE."""

from __future__ import annotations

import pandas as pd
import pytest

from retail_ml.diagnostics.causes import (
    MATERIAL_ERROR_SHARE_PCT,
    REGISTERED_HYPOTHESES,
    bias_sign_split,
    build_root_cause_report,
    error_mass,
    rank_causes,
)


def _frame() -> pd.DataFrame:
    """A high-WAPE, low-volume slice beside a low-WAPE, high-volume one."""

    # Shaped to match the measured v6 pattern: the intermittent routes hold
    # 9.32% of rows but only 0.91% of absolute error, because their volumes are
    # tiny. WAPE alone would rank them first; error mass ranks them last.
    rows = [
        {
            "selected_model": "main",
            "category": "core",
            "market_id": "m1",
            "horizon": 1,
            "actual_units": 100.0,
            "yhat_p50": 90.0,
        }
        for _ in range(1000)
    ]
    rows += [
        {
            "selected_model": "fallback",
            "category": "sparse",
            "market_id": "m1",
            "horizon": 1,
            "actual_units": 1.0,
            "yhat_p50": 3.0,
        }
        for _ in range(100)
    ]
    return pd.DataFrame(rows)


def test_a_high_wape_low_volume_slice_is_not_the_top_cause() -> None:
    frame = _frame()
    ranked = error_mass(frame, "selected_model")

    fallback = next(item for item in ranked if item["value"] == "fallback")
    main = next(item for item in ranked if item["value"] == "main")

    # The fallback slice has by far the worse WAPE...
    assert fallback["wape"] > main["wape"]
    # ...yet carries a small share of the error, so it ranks lower.
    assert ranked[0]["value"] == "main"
    assert main["errorSharePct"] > fallback["errorSharePct"]


def test_an_immaterial_cause_is_rejected_not_left_plausible() -> None:
    causes = rank_causes(_frame())
    routing = causes["H3"]

    assert routing["verdict"] == "rejected_immaterial_error_share"
    assert routing["addressableErrorSharePct"] < MATERIAL_ERROR_SHARE_PCT
    assert routing["errorConcentratedInOneSlice"] is True


def test_the_materiality_floor_ties_to_the_improvement_gate() -> None:
    """A cause below decision #75's floor cannot satisfy it alone."""

    assert MATERIAL_ERROR_SHARE_PCT == 5.0


def test_untestable_hypotheses_are_labelled_not_silently_dropped() -> None:
    causes = rank_causes(_frame())

    for hypothesis_id in ("H5", "H6", "H9", "H10"):
        assert causes[hypothesis_id]["verdict"] == (
            "not_testable_from_this_artifact"
        )
        assert "controlled ablation" in causes[hypothesis_id]["reason"]


def test_every_registered_hypothesis_names_a_candidate_family() -> None:
    families = {h.candidate_family for h in REGISTERED_HYPOTHESES}
    assert families <= {"C1", "C2", "C3", "C4", "C5", "C6"}
    for hypothesis in REGISTERED_HYPOTHESES:
        assert hypothesis.description
        assert hypothesis.candidate_family


def test_bias_sign_split_warns_against_a_global_correction() -> None:
    """Mixed-sign bias means a single global shift would hurt some slices."""

    split = bias_sign_split(_frame(), "category")

    assert split["underBiased"] >= 1
    assert split["overBiased"] >= 1
    assert split["overBiased"] + split["underBiased"] + split["nearNeutral"] == 2


def test_the_report_states_its_ranking_rule_and_authority() -> None:
    report = build_root_cause_report(
        _frame(), authority="D0", authority_fingerprint="a" * 64
    )

    assert report["comparisonAuthority"] == "D0"
    assert report["authorityFingerprint"] == "a" * 64
    assert "share of total absolute error" in report["rankingRule"]
    assert "cannot satisfy" in report["rankingRule"]
    assert report["semanticFingerprint"]


def test_a_zero_actual_slice_does_not_produce_a_wape() -> None:
    frame = _frame()
    frame.loc[frame["category"] == "sparse", "actual_units"] = 0.0
    ranked = error_mass(frame, "category")

    sparse = next(item for item in ranked if item["value"] == "sparse")
    assert sparse["wape"] is None
    assert sparse["bias"] is None
