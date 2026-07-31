"""PP3-B3 root-cause ranking against a frozen comparison authority.

The discipline this module enforces is a single rule: **rank causes by the share
of absolute error they carry, not by how bad their WAPE looks.** A slice with
terrible WAPE and negligible volume is a presentation problem, not a source of
recoverable error, and remedying it cannot move the acceptance gate.

Every hypothesis is registered with the candidate family it would justify, and a
hypothesis whose error share is below the materiality floor is explicitly
rejected rather than left as a plausible story.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Final, Sequence

import pandas as pd

CAUSES_SCHEMA_VERSION: Final[str] = "retail-forecast-root-cause-report/v1"

#: A cause carrying less than this share of total absolute error cannot
#: plausibly satisfy decision #75's 5% relative-improvement floor on its own.
MATERIAL_ERROR_SHARE_PCT: Final[float] = 5.0


@dataclass(frozen=True)
class Hypothesis:
    """One registered explanation and the candidate family it would justify."""

    id: str
    description: str
    candidate_family: str
    slice_column: str | None = None


REGISTERED_HYPOTHESES: Final[tuple[Hypothesis, ...]] = (
    Hypothesis(
        "H1",
        "market x horizon systematic under-bias",
        "C1",
        "market_id",
    ),
    Hypothesis("H2", "category/store/channel composition", "C3", "category"),
    Hypothesis(
        "H3",
        "intermittent routing and fallback behaviour",
        "C3",
        "selected_model",
    ),
    Hypothesis("H4", "lifecycle and cold-start treatment", "C6", "cohort"),
    Hypothesis("H5", "censored sales and stock-out effects", "C5", None),
    Hypothesis("H6", "insufficient assortment/exposure evidence", "C5", None),
    Hypothesis("H7", "feature fallback at longer horizons", "C1", "horizon"),
    Hypothesis(
        "H8",
        "model pooling across heterogeneous segments",
        "C3",
        "selected_model",
    ),
    Hypothesis("H9", "quantile calibration fallback", "C2", None),
    Hypothesis("H10", "optional-signal absence", "C5", None),
)


def _wape(frame: pd.DataFrame) -> float | None:
    actual = float(pd.to_numeric(frame["actual_units"], errors="coerce").sum())
    if actual <= 0:
        return None
    error = float(
        (
            pd.to_numeric(frame["yhat_p50"], errors="coerce")
            - pd.to_numeric(frame["actual_units"], errors="coerce")
        )
        .abs()
        .sum()
    )
    return error / actual


def _bias(frame: pd.DataFrame) -> float | None:
    actual = float(pd.to_numeric(frame["actual_units"], errors="coerce").sum())
    if actual <= 0:
        return None
    signed = float(
        (
            pd.to_numeric(frame["yhat_p50"], errors="coerce")
            - pd.to_numeric(frame["actual_units"], errors="coerce")
        ).sum()
    )
    return signed / actual


def error_mass(frame: pd.DataFrame, column: str) -> list[dict[str, Any]]:
    """Rank one slice by share of absolute error, not by WAPE."""

    total = float(
        (
            pd.to_numeric(frame["yhat_p50"], errors="coerce")
            - pd.to_numeric(frame["actual_units"], errors="coerce")
        )
        .abs()
        .sum()
    )
    rows: list[dict[str, Any]] = []
    if column not in frame.columns or total <= 0:
        return rows
    for value, group in frame.groupby(column, sort=False, observed=True):
        error = float(
            (
                pd.to_numeric(group["yhat_p50"], errors="coerce")
                - pd.to_numeric(group["actual_units"], errors="coerce")
            )
            .abs()
            .sum()
        )
        rows.append(
            {
                "value": str(value),
                "rows": int(len(group)),
                "rowSharePct": round(100.0 * len(group) / len(frame), 4),
                "errorSharePct": round(100.0 * error / total, 4),
                "wape": _wape(group),
                "bias": _bias(group),
            }
        )
    return sorted(rows, key=lambda item: item["errorSharePct"], reverse=True)


def bias_sign_split(frame: pd.DataFrame, column: str) -> dict[str, int]:
    """Count slices biased each way, so a global correction is not assumed safe."""

    over = under = neutral = 0
    if column not in frame.columns:
        return {"overBiased": 0, "underBiased": 0, "nearNeutral": 0}
    for _, group in frame.groupby(column, sort=False, observed=True):
        bias = _bias(group)
        if bias is None:
            continue
        if bias > 0.02:
            over += 1
        elif bias < -0.02:
            under += 1
        else:
            neutral += 1
    return {"overBiased": over, "underBiased": under, "nearNeutral": neutral}


def rank_causes(
    frame: pd.DataFrame,
    *,
    hypotheses: Sequence[Hypothesis] = REGISTERED_HYPOTHESES,
) -> dict[str, Any]:
    """Rank registered hypotheses by recoverable error mass."""

    results: dict[str, Any] = {}
    for hypothesis in hypotheses:
        if hypothesis.slice_column is None or (
            hypothesis.slice_column not in frame.columns
        ):
            results[hypothesis.id] = {
                "description": hypothesis.description,
                "candidateFamily": hypothesis.candidate_family,
                "verdict": "not_testable_from_this_artifact",
                "reason": (
                    "requires evidence the run bundle does not carry; needs a "
                    "controlled ablation rather than a slice"
                ),
            }
            continue
        slices = error_mass(frame, hypothesis.slice_column)
        worst = slices[0] if slices else None
        # The recoverable mass is what the *non-dominant* slices carry: if one
        # slice holds nearly all the error, the cause is that slice's model, not
        # the split itself.
        concentrated = bool(worst and worst["errorSharePct"] >= 90.0)
        addressable = (
            round(100.0 - worst["errorSharePct"], 4) if worst else 0.0
        )
        verdict = (
            "supported"
            if addressable >= MATERIAL_ERROR_SHARE_PCT
            else "rejected_immaterial_error_share"
        )
        results[hypothesis.id] = {
            "description": hypothesis.description,
            "candidateFamily": hypothesis.candidate_family,
            "sliceColumn": hypothesis.slice_column,
            "topSlices": slices[:6],
            "errorConcentratedInOneSlice": concentrated,
            "addressableErrorSharePct": addressable,
            "materialityFloorPct": MATERIAL_ERROR_SHARE_PCT,
            "verdict": verdict,
            "biasSignSplit": bias_sign_split(frame, hypothesis.slice_column),
        }
    return results


def build_root_cause_report(
    frame: pd.DataFrame,
    *,
    authority: str,
    authority_fingerprint: str,
) -> dict[str, Any]:
    payload = {
        "schemaVersion": CAUSES_SCHEMA_VERSION,
        "comparisonAuthority": authority,
        "authorityFingerprint": authority_fingerprint,
        "rankingRule": (
            "Causes are ranked by share of total absolute error. A slice with "
            "high WAPE and negligible volume is rejected as immaterial: fixing "
            "it cannot satisfy decision #75's improvement floor."
        ),
        "global": {"wape": _wape(frame), "bias": _bias(frame), "rows": int(len(frame))},
        "hypotheses": rank_causes(frame),
    }
    payload["semanticFingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


__all__ = [
    "CAUSES_SCHEMA_VERSION",
    "MATERIAL_ERROR_SHARE_PCT",
    "REGISTERED_HYPOTHESES",
    "Hypothesis",
    "bias_sign_split",
    "build_root_cause_report",
    "error_mass",
    "rank_causes",
]
