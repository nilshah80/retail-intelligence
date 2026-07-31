"""Fixed rolling-origin schedule, additive slices, and five publication gates."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Final

import numpy as np
import pandas as pd

from retail_ml.models.baselines import AdditiveMetrics, metric_for_column
from retail_ml.models.cohorts import (
    COHORT_KEY_COLUMNS,
    COHORT_RECOMPUTATION_VERSION,
    COLD_START,
    COLD_START_BASELINE_COLUMN,
    ESTABLISHED,
    INELIGIBLE,
    MAX_INELIGIBLE_ROW_SHARE,
    assign_cohorts,
    cohort_population,
)

EVALUATION_WINDOW_WEEKS: Final[int] = 26
ORIGIN_STEP_WEEKS: Final[int] = 2
SCORING_ORIGINS: Final[int] = 13
TRAINING_ORIGINS: Final[int] = 104
SLOW_MOVER_THRESHOLD: Final[float] = 0.60
ACCEPTANCE_SCHEMA_VERSION: Final[str] = "retail-forecast-acceptance/v4"

#: Decision #85. Per-cohort P90 coverage is computed and published at every scope,
#: but does not fail acceptance for this version. The gate turns hard at Phase 4
#: entry -- a dependency, not a date: Phase 4 safety stock is quantile-spread x
#: service level, so a P90 covering 78% while claiming 90% feeds an under-stocked
#: reorder point. A phased introduction, not a repeal; no version was ever
#: evaluated against this gate, so nothing that passed is being excused.
COVERAGE_GATE_MODE: Final[str] = "report_only"
COVERAGE_GATE_HARD_AT: Final[str] = "phase_4_entry"

#: Decision #86. A remediation candidate repairs a named failing gate and is
#: forbidden from being presented as an accuracy improvement, so the class travels
#: with the acceptance document where a consumer cannot miss it.
CANDIDATE_CLASS_REMEDIATION: Final[str] = "gate_remediation"
CANDIDATE_CLASS_CHAMPION: Final[str] = "champion"

#: Gates that are computed and published but do not decide acceptance. Removing a
#: name from this tuple is the single edit that turns its gate hard.
REPORT_ONLY_GATES: Final[tuple[str, ...]] = ("A2_per_cohort",)
A1_IMPROVEMENT_THRESHOLD_PCT: Final[float] = 25.0
P90_COVERAGE_MIN: Final[float] = 0.85
P90_COVERAGE_MAX: Final[float] = 0.95


def rolling_origin_schedule(eligible_origins: list[date]) -> list[date]:
    ordered = sorted(set(eligible_origins))
    window = ordered[-EVALUATION_WINDOW_WEEKS:]
    if not window:
        return []
    selected = list(reversed(list(reversed(window))[::ORIGIN_STEP_WEEKS]))
    if len(window) == EVALUATION_WINDOW_WEEKS and len(selected) != SCORING_ORIGINS:
        raise RuntimeError("fixed rolling-origin schedule did not produce 13 origins")
    return selected


def _relative_improvement(
    champion: AdditiveMetrics,
    baseline: AdditiveMetrics,
) -> float | None:
    if champion.wape is None or baseline.wape in (None, 0):
        return None
    return (baseline.wape - champion.wape) / baseline.wape * 100.0


def _clustered_interval(
    frame: pd.DataFrame,
    *,
    comparator_column: str = "seasonal_naive_baseline",
    samples: int = 500,
    seed: int = 20260730,
) -> tuple[float | None, float | None]:
    key_columns = ["sku_id", "store_id", "channel_id"]
    keys = frame[key_columns].drop_duplicates().reset_index(drop=True)
    if keys.empty:
        return (None, None)
    grouped = {
        tuple(key): group
        for key, group in frame.groupby(key_columns, sort=False, observed=True)
    }
    generator = np.random.default_rng(seed)
    differences: list[float] = []
    for _ in range(samples):
        selected = generator.integers(0, len(keys), size=len(keys))
        sampled = pd.concat(
            [grouped[tuple(keys.iloc[index])].copy() for index in selected],
            ignore_index=True,
        )
        champion = metric_for_column(sampled, "yhat_p50")
        seasonal = metric_for_column(sampled, comparator_column)
        if champion.wape is not None and seasonal.wape is not None:
            differences.append(champion.wape - seasonal.wape)
    if not differences:
        return (None, None)
    lower, upper = np.quantile(differences, [0.025, 0.975])
    return (round(float(lower), 8), round(float(upper), 8))


def _paired_rows(
    frame: pd.DataFrame,
    comparator_column: str = "seasonal_naive_baseline",
) -> pd.DataFrame:
    """Return the one row population used by champion and its comparator."""

    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    champion = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    comparator = pd.to_numeric(
        frame.get(comparator_column),
        errors="coerce",
    )
    valid = (
        actual.notna()
        & champion.notna()
        & comparator.notna()
        & np.isfinite(actual)
        & np.isfinite(champion)
        & np.isfinite(comparator)
    )
    return frame.loc[valid].copy()


def _eligible_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Return rows whose actual and champion prediction are both finite."""

    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    champion = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    valid = (
        actual.notna()
        & champion.notna()
        & np.isfinite(actual)
        & np.isfinite(champion)
    )
    return frame.loc[valid].copy()


def _pairing_key_columns(frame: pd.DataFrame) -> list[str]:
    required = [
        "forecast_origin",
        "sku_id",
        "store_id",
        "channel_id",
    ]
    optional = ["target_week_start", "horizon"]
    return [column for column in (*required, *optional) if column in frame.columns]


def _key_fingerprint(frame: pd.DataFrame, key_columns: list[str]) -> str:
    rows = [
        [str(value) for value in row]
        for row in frame[key_columns]
        .sort_values(key_columns)
        .itertuples(index=False, name=None)
    ]
    return hashlib.sha256(
        json.dumps(rows, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _paired_key_diagnostics(
    frame: pd.DataFrame,
    comparator_column: str = "seasonal_naive_baseline",
    comparator_label: str = "seasonalNaive",
) -> dict[str, Any]:
    """Prove the three metric inputs use one duplicate-free canonical row set."""

    key_columns = _pairing_key_columns(frame)
    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    champion = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    comparator = pd.to_numeric(frame.get(comparator_column), errors="coerce")
    masks = {
        "actual": actual.notna() & np.isfinite(actual),
        "champion": champion.notna() & np.isfinite(champion),
        comparator_label: comparator.notna() & np.isfinite(comparator),
    }
    paired_mask = masks["actual"] & masks["champion"] & masks[comparator_label]
    fingerprints: dict[str, str] = {}
    duplicate_free = True
    counts: dict[str, int] = {}
    for label, mask in masks.items():
        rows = frame.loc[paired_mask & mask, key_columns]
        counts[label] = len(rows)
        duplicate_free = duplicate_free and not rows.duplicated(key_columns).any()
        fingerprints[label] = _key_fingerprint(rows, key_columns)
    identical = (
        duplicate_free
        and len(set(counts.values())) == 1
        and len(set(fingerprints.values())) == 1
    )
    return {
        "keyColumns": key_columns,
        "keySha256": fingerprints,
        "rowCounts": counts,
        "duplicateFree": bool(duplicate_free),
        "pairedRowsIdentical": bool(identical),
    }


def slow_mover_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    """Decision-#52 A3 over established-history slow movers only.

    Decision #82 keeps cold-start slow movers inside the cold-start A1 gate; they
    never receive a fabricated seasonal-naive comparator here.
    """

    scoped = frame
    if "cohort" in frame.columns:
        scoped = frame[frame["cohort"].astype(str).eq(ESTABLISHED)]
    eligible_slow = scoped[
        pd.to_numeric(scoped["zero_share_52w"], errors="coerce").fillna(0.0)
        > SLOW_MOVER_THRESHOLD
    ].copy()
    slow = _paired_rows(eligible_slow)
    key_columns = ["sku_id", "store_id", "channel_id"]
    origins = sorted(pd.to_datetime(slow["forecast_origin"]).dt.date.unique())
    per_origin = (
        slow.groupby("forecast_origin", observed=True)[key_columns]
        .apply(lambda value: len(value.drop_duplicates()))
        .astype(int)
        .to_dict()
        if not slow.empty
        else {}
    )
    n_series = len(slow[key_columns].drop_duplicates()) if not slow.empty else 0
    actual_sum = float(pd.to_numeric(slow.get("actual_units"), errors="coerce").sum())
    sufficient = (
        n_series >= 100
        and len(origins) == SCORING_ORIGINS
        and bool(per_origin)
        and min(per_origin.values()) >= 50
        and actual_sum > 0
    )
    champion = metric_for_column(slow, "yhat_p50") if not slow.empty else None
    seasonal = (
        metric_for_column(slow, "seasonal_naive_baseline") if not slow.empty else None
    )
    interval = _clustered_interval(slow) if sufficient else (None, None)
    pairing = _paired_key_diagnostics(slow)
    sufficient = sufficient and pairing["pairedRowsIdentical"]
    point_passed = bool(
        sufficient
        and champion is not None
        and seasonal is not None
        and champion.wape is not None
        and seasonal.wape is not None
        and champion.wape <= seasonal.wape
    )
    return {
        "cohort": ESTABLISHED,
        "sufficient": sufficient,
        "verdict": "pass" if point_passed else (
            "fail" if sufficient else "insufficient_evidence"
        ),
        "nSeries": n_series,
        "nRows": len(slow),
        "eligibleRows": len(eligible_slow),
        "droppedUnpairedRows": len(eligible_slow) - len(slow),
        "pairedRowsIdentical": pairing["pairedRowsIdentical"],
        "pairingKeys": pairing,
        "originCount": len(origins),
        "minimumPairedSeriesPerOrigin": min(per_origin.values()) if per_origin else 0,
        "actualSum": actual_sum,
        "championWape": champion.wape if champion else None,
        "seasonalNaiveWape": seasonal.wape if seasonal else None,
        "seriesClusteredDifferenceInterval95": list(interval),
        "passed": point_passed,
    }


def _established_gate(cohort: pd.DataFrame) -> dict[str, Any]:
    """Spec 4.3 established-history leg: complete pairing plus >= 25% lift."""

    paired = _paired_rows(cohort)
    paired_champion = metric_for_column(paired, "yhat_p50")
    seasonal = metric_for_column(paired, "seasonal_naive_baseline")
    improvement = _relative_improvement(paired_champion, seasonal)
    pairing = _paired_key_diagnostics(paired)
    complete = len(paired) == len(cohort) and pairing["pairedRowsIdentical"]
    if cohort.empty:
        complete = True
    return {
        "cohort": ESTABLISHED,
        "passed": bool(
            complete
            and (
                cohort.empty
                or (
                    improvement is not None
                    and improvement >= A1_IMPROVEMENT_THRESHOLD_PCT
                )
            )
        ),
        "verdict": (
            "not_applicable"
            if cohort.empty
            else (
                "pass"
                if complete
                and improvement is not None
                and improvement >= A1_IMPROVEMENT_THRESHOLD_PCT
                else "fail"
            )
        ),
        "comparator": "seasonal_naive",
        "eligibleRows": len(cohort),
        "pairedRows": len(paired),
        "droppedUnpairedRows": len(cohort) - len(paired),
        "relativeWapeImprovementPct": improvement,
        "minimumRelativeWapeImprovementPct": A1_IMPROVEMENT_THRESHOLD_PCT,
        "comparisonComplete": bool(complete),
        "championWape": paired_champion.wape,
        "comparatorWape": seasonal.wape,
        "pairingKeys": pairing,
    }


def _cold_start_gate(cohort: pd.DataFrame) -> dict[str, Any]:
    """Decision-#82 cold-start leg: complete pairing plus non-inferiority.

    A cold-start row with no prior complete origin-visible week has no
    defensible comparator. It stays in this cohort, is reason-coded, and makes
    the verdict ``insufficient_evidence`` rather than a pass.
    """

    paired = _paired_rows(cohort, COLD_START_BASELINE_COLUMN)
    paired_champion = metric_for_column(paired, "yhat_p50")
    comparator = metric_for_column(paired, COLD_START_BASELINE_COLUMN)
    pairing = _paired_key_diagnostics(
        paired,
        COLD_START_BASELINE_COLUMN,
        "coldStartComparator",
    )
    unbacked = len(cohort) - len(paired)
    complete = unbacked == 0 and pairing["pairedRowsIdentical"]
    interval = (
        _clustered_interval(paired, comparator_column=COLD_START_BASELINE_COLUMN)
        if complete and not paired.empty
        else (None, None)
    )
    margin = _relative_improvement(paired_champion, comparator)
    if cohort.empty:
        verdict = "not_applicable"
    elif not complete or paired_champion.wape is None or comparator.wape is None:
        verdict = "insufficient_evidence"
    elif paired_champion.wape <= comparator.wape:
        verdict = "pass"
    else:
        verdict = "fail"
    return {
        "cohort": COLD_START,
        "passed": verdict in ("pass", "not_applicable"),
        "verdict": verdict,
        "comparator": "cold_start_mean",
        "comparatorDefinition": (
            "mean of the last min(13, history_weeks) complete origin-visible "
            "weekly actuals available at the forecast origin"
        ),
        "eligibleRows": len(cohort),
        "pairedRows": len(paired),
        "rowsWithoutComparator": unbacked,
        "relativeWapeImprovementPct": margin,
        "nonInferiorityRequired": True,
        "comparisonComplete": bool(complete),
        "championWape": paired_champion.wape,
        "comparatorWape": comparator.wape,
        "seriesClusteredDifferenceInterval95": list(interval),
        "pairingKeys": pairing,
    }


def _scope_gates(frame: pd.DataFrame) -> dict[str, Any]:
    champion = metric_for_column(frame, "yhat_p50", upper_column="yhat_p90")
    eligible = _eligible_rows(frame)
    established = eligible[eligible["cohort"].astype(str).eq(ESTABLISHED)].copy()
    cold_start = eligible[eligible["cohort"].astype(str).eq(COLD_START)].copy()
    # Decision #83: rows with no prior observation of any kind are
    # evaluation-ineligible. They are counted and capped, never dropped silently.
    ineligible = eligible[eligible["cohort"].astype(str).eq(INELIGIBLE)].copy()
    if len(established) + len(cold_start) + len(ineligible) != len(eligible):
        raise ValueError("decision-#82 cohorts do not partition the eligible rows")
    total_actual = float(
        pd.to_numeric(eligible.get("actual_units"), errors="coerce").sum()
    )
    p90_coverage = champion.coverage
    monotonic = bool(
        (
            pd.to_numeric(frame["yhat_p90"], errors="coerce")
            >= pd.to_numeric(frame["yhat_p50"], errors="coerce")
        ).all()
    )
    established_gate = _established_gate(established)
    cold_start_gate = _cold_start_gate(cold_start)
    gates = {
        "A1_established": established_gate,
        "A1_cold_start": cold_start_gate,
        "A2": {
            "passed": (
                p90_coverage is not None
                and P90_COVERAGE_MIN <= p90_coverage <= P90_COVERAGE_MAX
            ),
            "p90Coverage": p90_coverage,
            "minimumP90Coverage": P90_COVERAGE_MIN,
            "maximumP90Coverage": P90_COVERAGE_MAX,
        },
        "A3": slow_mover_diagnostics(eligible),
        "A4": {"passed": monotonic},
    }
    # Decision #85: the same 0.85-0.95 band applied per cohort. Published with an
    # explicit verdict even while report-only, so a reader cannot mistake a
    # measured failure for a pass.
    cohort_coverage: dict[str, Any] = {}
    for label, subset in (("established_history", established), ("cold_start", cold_start)):
        actual_sum = float(pd.to_numeric(subset.get("actual_units"), errors="coerce").sum())
        metric = metric_for_column(subset, "yhat_p50", upper_column="yhat_p90")
        coverage = metric.coverage
        if coverage is None or actual_sum <= 0:
            verdict, passed = "insufficient_evidence", None
        elif P90_COVERAGE_MIN <= coverage <= P90_COVERAGE_MAX:
            verdict, passed = "pass", True
        else:
            verdict, passed = "fail", False
        cohort_coverage[label] = {
            "p90Coverage": coverage,
            "rows": int(len(subset)),
            "actualSum": actual_sum,
            "minimumP90Coverage": P90_COVERAGE_MIN,
            "maximumP90Coverage": P90_COVERAGE_MAX,
            "verdict": verdict,
            "passed": passed,
        }
    gates["A2_per_cohort"] = {
        "gateMode": COVERAGE_GATE_MODE,
        "hardGateAt": COVERAGE_GATE_HARD_AT,
        "cohorts": cohort_coverage,
        "wouldPassIfHard": all(
            entry["passed"] is True for entry in cohort_coverage.values()
        ),
        "note": (
            "Decision #85. Report-only for this version; does not fail acceptance. "
            "Becomes a hard gate at Phase 4 entry because safety stock is derived "
            "from the quantile spread."
        ),
    }
    established_paired = _paired_rows(established)
    cold_paired = _paired_rows(cold_start, COLD_START_BASELINE_COLUMN)
    return {
        "cohorts": {
            "establishedHistory": cohort_population(
                established,
                total_rows=len(eligible),
                total_actual=total_actual,
            ),
            "coldStart": cohort_population(
                cold_start,
                total_rows=len(eligible),
                total_actual=total_actual,
            ),
            "evaluationIneligible": cohort_population(
                ineligible,
                total_rows=len(eligible),
                total_actual=total_actual,
            ),
            "eligibleRows": len(eligible),
            "scoredRows": len(established) + len(cold_start),
            "ineligibleRowSharePct": round(
                100.0 * len(ineligible) / len(eligible), 6
            ) if len(eligible) else 0.0,
            "maximumIneligibleRowSharePct": MAX_INELIGIBLE_ROW_SHARE * 100.0,
            "unassignedRows": (
                len(eligible) - len(established) - len(cold_start) - len(ineligible)
            ),
            "keyColumns": [
                column
                for column in COHORT_KEY_COLUMNS
                if column in eligible.columns
            ],
        },
        "metrics": {
            "champion": champion.as_record(),
            "establishedChampion": metric_for_column(
                established_paired,
                "yhat_p50",
            ).as_record(),
            "seasonalNaive": metric_for_column(
                established_paired,
                "seasonal_naive_baseline",
            ).as_record(),
            "coldStartChampion": metric_for_column(
                cold_paired,
                "yhat_p50",
            ).as_record(),
            "coldStartComparator": metric_for_column(
                cold_paired,
                COLD_START_BASELINE_COLUMN,
            ).as_record(),
        },
        "gates": gates,
        # Decision #85 is report-only until Phase 4 entry, so A2_per_cohort is
        # excluded from the verdict by name rather than by giving it a cosmetic
        # `passed: True`. Naming it here is what makes the exclusion auditable and
        # what a future commit has to delete to make the gate hard.
        "reportOnlyGates": list(REPORT_ONLY_GATES),
        "passed": all(
            value["passed"]
            for name, value in gates.items()
            if name not in REPORT_ONLY_GATES
        ),
    }


def evaluate_acceptance(
    frame: pd.DataFrame,
    *,
    candidate_class: str = CANDIDATE_CLASS_CHAMPION,
) -> dict[str, Any]:
    required = {
        "market_id",
        "sku_id",
        "store_id",
        "channel_id",
        "forecast_origin",
        "actual_units",
        "yhat_p50",
        "yhat_p90",
        "seasonal_naive_baseline",
        COLD_START_BASELINE_COLUMN,
        "zero_share_52w",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"acceptance frame is missing: {', '.join(missing)}")
    cohorted = assign_cohorts(frame)
    global_result = _scope_gates(cohorted)
    markets = {
        str(market): _scope_gates(group)
        for market, group in cohorted.groupby("market_id", sort=True, observed=True)
    }
    market_gate = bool(markets) and all(result["passed"] for result in markets.values())
    return {
        "schemaVersion": ACCEPTANCE_SCHEMA_VERSION,
        "recomputationVersion": COHORT_RECOMPUTATION_VERSION,
        "candidateClass": candidate_class,
        "coverageGateMode": COVERAGE_GATE_MODE,
        "coverageHardGateAt": COVERAGE_GATE_HARD_AT,
        "global": global_result,
        "markets": markets,
        "A5": {
            "passed": market_gate,
            "supportedMarketCount": len(markets),
            "failedMarkets": [
                market for market, result in markets.items() if not result["passed"]
            ],
        },
        "passed": global_result["passed"] and market_gate,
    }


__all__ = [
    "A1_IMPROVEMENT_THRESHOLD_PCT",
    "ACCEPTANCE_SCHEMA_VERSION",
    "CANDIDATE_CLASS_CHAMPION",
    "CANDIDATE_CLASS_REMEDIATION",
    "COVERAGE_GATE_HARD_AT",
    "COVERAGE_GATE_MODE",
    "REPORT_ONLY_GATES",
    "COHORT_RECOMPUTATION_VERSION",
    "EVALUATION_WINDOW_WEEKS",
    "P90_COVERAGE_MAX",
    "P90_COVERAGE_MIN",
    "ORIGIN_STEP_WEEKS",
    "SCORING_ORIGINS",
    "SLOW_MOVER_THRESHOLD",
    "TRAINING_ORIGINS",
    "evaluate_acceptance",
    "rolling_origin_schedule",
    "slow_mover_diagnostics",
]
