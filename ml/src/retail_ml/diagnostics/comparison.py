"""Decision #75 candidate-versus-authority comparison.

Implements the frozen materiality gate: >=5% relative WAPE improvement, a seeded
SeriesKey-clustered 95% interval whose candidate-minus-authority upper bound is
below zero, no supported-market regression beyond 1%, identical cohort keys, and
**both** the all-13 and final-5 populations passing independently.

The last requirement exists because D0 measured the confirmation origins to be
3.03 accuracy points easier than the development origins. A confirmation-only
gain is therefore not evidence of anything.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final, Sequence

import numpy as np
import pandas as pd

from retail_ml.models.cohorts import key_fingerprint

POLICY_PATH: Final[str] = "contracts/ml/forecast-improvement-policy.json"
COMPARISON_SCHEMA_VERSION: Final[str] = "retail-forecast-candidate-comparison/v1"
SERIES_KEY: Final[tuple[str, ...]] = ("sku_id", "store_id", "channel_id")
COHORT_KEY: Final[tuple[str, ...]] = (
    "forecast_origin",
    "horizon",
    "sku_id",
    "store_id",
    "channel_id",
)

#: Decision #75 lists LEAKAGE as a stop rule, but a materiality gate alone cannot
#: see it: a candidate built from the target scores brilliantly. A first-draft
#: top-down reconciliation here disaggregated by each leaf's share of
#: `actual_units` and reported +59.2% relative WAPE as `accepted`. These bounds
#: exist so that cannot happen silently again.
#:
#: No honest candidate reduces WAPE by more than this against an already-fitted
#: authority; beyond it, suspect construction rather than skill.
MAX_PLAUSIBLE_IMPROVEMENT_PCT: Final[float] = 25.0

#: How much closer to the target a candidate may track than the authority it is
#: replacing. Measured as uplift, not as an absolute correlation: a competent
#: forecast already correlates 0.9272 with actuals on the evaluation bundle, so an
#: absolute ceiling would reject every candidate built on one. Honest candidates
#: measured on that bundle move the correlation by 0.0000 (global rescale) to
#: 0.0011 (per-market factor); the leaking top-down reconciliation moved it by
#: 0.0590 and using the target outright by 0.0728. This sits between them, an
#: order of magnitude above the honest ceiling.
MAX_TARGET_CORRELATION_UPLIFT: Final[float] = 0.02

#: A candidate this accurate is not a forecast. Tested row-wise rather than by
#: correlation, because a perfectly correlated but biased forecast is legitimate
#: while one that equals the target is the target.
MAX_TARGET_REPRODUCTION_WAPE: Final[float] = 0.01


class ComparisonError(RuntimeError):
    """The comparison is not admissible under the frozen policy."""


def load_policy(repository_root: str | Path = ".") -> dict[str, Any]:
    policy = json.loads(
        (Path(repository_root) / POLICY_PATH).read_text(encoding="utf-8")
    )
    if policy.get("policyId") != "retail-forecast-improvement/v1":
        raise ComparisonError("unknown improvement policy")
    return policy


def _wape(frame: pd.DataFrame, column: str) -> float | None:
    actual = float(pd.to_numeric(frame["actual_units"], errors="coerce").sum())
    if actual <= 0:
        return None
    error = float(
        (
            pd.to_numeric(frame[column], errors="coerce")
            - pd.to_numeric(frame["actual_units"], errors="coerce")
        )
        .abs()
        .sum()
    )
    return error / actual


def _coverage(frame: pd.DataFrame, upper: str) -> float | None:
    if not len(frame):
        return None
    hits = (
        pd.to_numeric(frame["actual_units"], errors="coerce")
        <= pd.to_numeric(frame[upper], errors="coerce")
    ).sum()
    return float(hits) / float(len(frame))


def _clustered_interval(
    frame: pd.DataFrame,
    candidate_column: str,
    authority_column: str,
    *,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    """Seeded SeriesKey-clustered bootstrap of candidate minus authority WAPE."""

    keys = frame[list(SERIES_KEY)].drop_duplicates().reset_index(drop=True)
    if keys.empty:
        return (None, None)
    grouped = {
        tuple(str(part) for part in key): group
        for key, group in frame.groupby(list(SERIES_KEY), sort=False, observed=True)
    }
    index = [tuple(str(part) for part in row) for row in keys.itertuples(index=False)]
    generator = np.random.default_rng(seed)
    deltas: list[float] = []
    for _ in range(samples):
        picks = generator.integers(0, len(index), size=len(index))
        sampled = pd.concat(
            [grouped[index[position]] for position in picks], ignore_index=True
        )
        candidate = _wape(sampled, candidate_column)
        authority = _wape(sampled, authority_column)
        if candidate is not None and authority is not None:
            deltas.append(candidate - authority)
    if not deltas:
        return (None, None)
    lower, upper = np.quantile(deltas, [0.025, 0.975])
    return (round(float(lower), 8), round(float(upper), 8))


def detect_leakage(
    frame: pd.DataFrame,
    candidate_column: str,
    authority_column: str,
) -> dict[str, Any]:
    """Structural leakage checks, independent of the materiality gate.

    Three signals, each cheap and each decisive on a different failure:

    1. an implausibly large improvement -- real modelling gains against an
       already-fitted authority are incremental;
    2. a candidate that tracks the target *better than the authority already
       does*, which is what building a prediction from `actual_units` looks like;
    3. a candidate that reproduces the target row-wise, the degenerate case.

    Signal 2 is measured as uplift over the authority rather than as an absolute
    correlation, because a competent forecast is already highly correlated with
    its target and an absolute threshold would flag every candidate built on one.
    On the 708,708-row evaluation bundle the authority correlates 0.9272 with
    actuals; an honest global rescale moves that by 0.0000 and an honest
    per-market factor by 0.0011, while the leaking top-down reconciliation moves
    it by 0.0590 and using the target outright by 0.0728. Honest and leaking
    candidates separate by roughly fifty-fold, so the threshold sits an order of
    magnitude above the honest ceiling.
    """

    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    candidate = pd.to_numeric(frame[candidate_column], errors="coerce")
    authority = pd.to_numeric(frame[authority_column], errors="coerce")

    candidate_wape = _wape(frame, candidate_column)
    authority_wape = _wape(frame, authority_column)
    improvement = (
        100.0 * (authority_wape - candidate_wape) / authority_wape
        if candidate_wape is not None and authority_wape not in (None, 0)
        else None
    )

    def _correlation(series: pd.Series) -> float | None:
        valid = actual.notna() & series.notna()
        if int(valid.sum()) <= 2:
            return None
        if not float(actual[valid].std() or 0) > 0:
            return None
        if not float(series[valid].std() or 0) > 0:
            return None
        return float(np.corrcoef(actual[valid], series[valid])[0, 1])

    correlation = _correlation(candidate)
    authority_correlation = _correlation(authority)
    uplift = (
        correlation - authority_correlation
        if correlation is not None and authority_correlation is not None
        else None
    )

    signals: list[str] = []
    if improvement is not None and improvement > MAX_PLAUSIBLE_IMPROVEMENT_PCT:
        signals.append(
            f"IMPLAUSIBLE_IMPROVEMENT:{improvement:.2f}pct_exceeds_"
            f"{MAX_PLAUSIBLE_IMPROVEMENT_PCT:.0f}pct"
        )
    if uplift is not None and uplift > MAX_TARGET_CORRELATION_UPLIFT:
        signals.append(
            f"CANDIDATE_TRACKS_TARGET:corr_uplift_{uplift:+.4f}_exceeds_"
            f"{MAX_TARGET_CORRELATION_UPLIFT}"
        )
    # The degenerate case, tested on row-wise agreement rather than correlation:
    # a forecast that is perfectly correlated with its target but biased is a
    # legitimate forecast, while one that equals the target is not a forecast.
    if candidate_wape is not None and candidate_wape < MAX_TARGET_REPRODUCTION_WAPE:
        signals.append(
            f"CANDIDATE_REPRODUCES_TARGET:wape_{candidate_wape:.6f}_below_"
            f"{MAX_TARGET_REPRODUCTION_WAPE}"
        )
    # A candidate that is worse nowhere and better everywhere by a wide margin
    # has usually seen the answer.
    if improvement is not None and improvement > MAX_PLAUSIBLE_IMPROVEMENT_PCT:
        rowwise = (candidate - actual).abs() <= (authority - actual).abs()
        if float(rowwise.mean()) > 0.99:
            signals.append("IMPROVES_ALMOST_EVERY_ROW")

    return {
        "relativeImprovementPct": improvement,
        "candidateTargetCorrelation": correlation,
        "authorityTargetCorrelation": authority_correlation,
        "candidateTargetCorrelationUplift": uplift,
        "candidateWape": candidate_wape,
        "maxPlausibleImprovementPct": MAX_PLAUSIBLE_IMPROVEMENT_PCT,
        "maxTargetCorrelationUplift": MAX_TARGET_CORRELATION_UPLIFT,
        "maxTargetReproductionWape": MAX_TARGET_REPRODUCTION_WAPE,
        "signals": signals,
        "suspected": bool(signals),
    }


def _population(
    frame: pd.DataFrame,
    candidate_column: str,
    authority_column: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    candidate = _wape(frame, candidate_column)
    authority = _wape(frame, authority_column)
    if candidate is None or authority is None:
        return {"verdict": "insufficient_evidence", "rows": int(len(frame))}
    relative = 100.0 * (authority - candidate) / authority
    materiality = policy["materiality"]
    bootstrap = materiality["bootstrap"]
    lower, upper = _clustered_interval(
        frame,
        candidate_column,
        authority_column,
        samples=int(bootstrap["samples"]),
        seed=int(bootstrap["seed"]),
    )
    markets: dict[str, Any] = {}
    worst_regression = 0.0
    for market, group in sorted(
        frame.groupby("market_id", sort=True, observed=True),
        key=lambda item: str(item[0]),
    ):
        market_candidate = _wape(group, candidate_column)
        market_authority = _wape(group, authority_column)
        if market_candidate is None or market_authority is None:
            markets[str(market)] = {"verdict": "insufficient_evidence"}
            continue
        market_relative = (
            100.0 * (market_authority - market_candidate) / market_authority
        )
        worst_regression = min(worst_regression, market_relative)
        markets[str(market)] = {
            "candidateWape": market_candidate,
            "authorityWape": market_authority,
            "relativeImprovementPct": round(market_relative, 6),
        }
    tolerance = -float(
        materiality["perMarketNonRegression"]["maximumRelativeWapeRegressionPct"]
    )
    passed = bool(
        relative >= float(materiality["minimumGlobalImprovementPct"])
        and upper is not None
        and upper < 0
        and worst_regression >= tolerance
    )
    return {
        "rows": int(len(frame)),
        "candidateWape": candidate,
        "authorityWape": authority,
        "relativeImprovementPct": round(relative, 6),
        "minimumRequiredPct": materiality["minimumGlobalImprovementPct"],
        "clusteredInterval95": [lower, upper],
        "intervalUpperBoundBelowZero": bool(upper is not None and upper < 0),
        "markets": markets,
        "worstMarketRelativePct": round(worst_regression, 6),
        "marketTolerancePct": tolerance,
        "verdict": "pass" if passed else "fail",
        "passed": passed,
    }


def compare_candidate(
    frame: pd.DataFrame,
    *,
    candidate_column: str,
    authority_column: str = "yhat_p50",
    candidate_id: str,
    development_origins: Sequence[Any],
    confirmation_origins: Sequence[Any],
    repository_root: str | Path = ".",
) -> dict[str, Any]:
    """Score one candidate against the authority on both populations."""

    policy = load_policy(repository_root)
    if candidate_column not in frame.columns:
        raise ComparisonError(f"candidate column {candidate_column!r} is absent")

    registered = {family["id"] for family in policy["candidateRegistry"]["families"]}
    if candidate_id not in registered:
        raise ComparisonError(
            f"{candidate_id} is not a registered candidate family; scoring it "
            "would be a post-hoc addition"
        )

    all_13 = _population(frame, candidate_column, authority_column, policy)
    confirmation = _population(
        frame[frame["forecast_origin"].isin(list(confirmation_origins))],
        candidate_column,
        authority_column,
        policy,
    )
    development = _population(
        frame[frame["forecast_origin"].isin(list(development_origins))],
        candidate_column,
        authority_column,
        policy,
    )

    leakage = detect_leakage(frame, candidate_column, authority_column)
    coverage = _coverage(frame, "yhat_p90")
    monotonic = bool(
        (
            pd.to_numeric(frame["yhat_p90"], errors="coerce")
            >= pd.to_numeric(frame[candidate_column], errors="coerce")
        ).all()
    )
    band = policy["materiality"]
    stops: list[str] = []
    if leakage["suspected"]:
        stops.append("LEAKAGE")
    if coverage is None or not (0.85 <= coverage <= 0.95):
        stops.append("COVERAGE_FAILURE")
    if not monotonic:
        stops.append("QUANTILE_INVERSION")
    if not all_13["passed"]:
        stops.append("MATERIALITY_ALL_13")
    if not confirmation["passed"]:
        stops.append("MATERIALITY_CONFIRMATION")

    return {
        "schemaVersion": COMPARISON_SCHEMA_VERSION,
        "candidateId": candidate_id,
        "policyId": policy["policyId"],
        "cohortKeySha256": key_fingerprint(frame, list(COHORT_KEY)),
        "p90Coverage": coverage,
        "quantilesMonotonic": monotonic,
        "leakage": leakage,
        "populations": {
            "all_13_origins": all_13,
            "final_5_confirmation_origins": confirmation,
            "development_origins_diagnostic_only": development,
        },
        "stopRulesTriggered": stops,
        "accepted": not stops,
        "note": (
            "Both all-13 and final-5 must pass independently. D0 measured the "
            "confirmation origins as 3.03 accuracy points easier, so a "
            "confirmation-only gain is not evidence."
        ),
        "unusedPolicyKeys": sorted(set(band) - {
            "metric",
            "minimumGlobalImprovementPct",
            "bootstrap",
            "perMarketNonRegression",
            "reportedPopulations",
            "rule",
        }),
    }


__all__ = [
    "COHORT_KEY",
    "MAX_PLAUSIBLE_IMPROVEMENT_PCT",
    "MAX_TARGET_CORRELATION_UPLIFT",
    "MAX_TARGET_REPRODUCTION_WAPE",
    "COMPARISON_SCHEMA_VERSION",
    "SERIES_KEY",
    "ComparisonError",
    "compare_candidate",
    "detect_leakage",
    "load_policy",
]
