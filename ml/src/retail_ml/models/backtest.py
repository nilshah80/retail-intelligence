"""Fixed rolling-origin schedule, additive slices, and five publication gates."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any, Final

import numpy as np
import pandas as pd

from retail_ml.models.baselines import AdditiveMetrics, metric_for_column

EVALUATION_WINDOW_WEEKS: Final[int] = 26
ORIGIN_STEP_WEEKS: Final[int] = 2
SCORING_ORIGINS: Final[int] = 13
TRAINING_ORIGINS: Final[int] = 104
SLOW_MOVER_THRESHOLD: Final[float] = 0.60
ACCEPTANCE_SCHEMA_VERSION: Final[str] = "retail-forecast-acceptance/v2"
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
        seasonal = metric_for_column(sampled, "seasonal_naive_baseline")
        if champion.wape is not None and seasonal.wape is not None:
            differences.append(champion.wape - seasonal.wape)
    if not differences:
        return (None, None)
    lower, upper = np.quantile(differences, [0.025, 0.975])
    return (round(float(lower), 8), round(float(upper), 8))


def _seasonal_paired_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the one row population used by champion and seasonal naive."""

    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    champion = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    seasonal = pd.to_numeric(
        frame["seasonal_naive_baseline"],
        errors="coerce",
    )
    valid = (
        actual.notna()
        & champion.notna()
        & seasonal.notna()
        & np.isfinite(actual)
        & np.isfinite(champion)
        & np.isfinite(seasonal)
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


def _paired_key_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    """Prove the three metric inputs use one duplicate-free canonical row set."""

    key_columns = _pairing_key_columns(frame)
    actual = pd.to_numeric(frame["actual_units"], errors="coerce")
    champion = pd.to_numeric(frame["yhat_p50"], errors="coerce")
    seasonal = pd.to_numeric(frame["seasonal_naive_baseline"], errors="coerce")
    masks = {
        "actual": actual.notna() & np.isfinite(actual),
        "champion": champion.notna() & np.isfinite(champion),
        "seasonalNaive": seasonal.notna() & np.isfinite(seasonal),
    }
    paired_mask = masks["actual"] & masks["champion"] & masks["seasonalNaive"]
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
    eligible_slow = frame[
        pd.to_numeric(frame["zero_share_52w"], errors="coerce").fillna(0.0)
        > SLOW_MOVER_THRESHOLD
    ].copy()
    slow = _seasonal_paired_rows(eligible_slow)
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


def _scope_gates(frame: pd.DataFrame) -> dict[str, Any]:
    champion = metric_for_column(frame, "yhat_p50", upper_column="yhat_p90")
    paired = _seasonal_paired_rows(frame)
    paired_champion = metric_for_column(paired, "yhat_p50")
    seasonal = metric_for_column(paired, "seasonal_naive_baseline")
    dropped = frame.loc[~frame.index.isin(paired.index)].copy()
    dropped_champion = metric_for_column(dropped, "yhat_p50")
    improvement = _relative_improvement(paired_champion, seasonal)
    pairing = _paired_key_diagnostics(paired)
    pairing_complete = (
        len(paired) == champion.n and pairing["pairedRowsIdentical"]
    )
    paired_row_share = len(paired) / champion.n if champion.n else 0.0
    paired_actual_share = (
        paired_champion.actual_sum / champion.actual_sum
        if champion.actual_sum > 0
        else 0.0
    )
    p90_coverage = champion.coverage
    monotonic = bool(
        (
            pd.to_numeric(frame["yhat_p90"], errors="coerce")
            >= pd.to_numeric(frame["yhat_p50"], errors="coerce")
        ).all()
    )
    slow = slow_mover_diagnostics(frame)
    gates = {
        "A1": {
            "passed": bool(
                pairing_complete
                and improvement is not None
                and improvement >= A1_IMPROVEMENT_THRESHOLD_PCT
            ),
            "relativeWapeImprovementPct": improvement,
            "minimumRelativeWapeImprovementPct": A1_IMPROVEMENT_THRESHOLD_PCT,
            "comparisonComplete": pairing_complete,
        },
        "A2": {
            "passed": (
                p90_coverage is not None
                and P90_COVERAGE_MIN <= p90_coverage <= P90_COVERAGE_MAX
            ),
            "p90Coverage": p90_coverage,
            "minimumP90Coverage": P90_COVERAGE_MIN,
            "maximumP90Coverage": P90_COVERAGE_MAX,
        },
        "A3": slow,
        "A4": {"passed": monotonic},
    }
    return {
        "metrics": {
            "champion": champion.as_record(),
            "pairedChampion": paired_champion.as_record(),
            "droppedChampion": dropped_champion.as_record(),
            "seasonalNaive": seasonal.as_record(),
        },
        "seasonalComparison": {
            "eligibleChampionRows": champion.n,
            "pairedRows": len(paired),
            "droppedUnpairedRows": champion.n - len(paired),
            "pairedRowShare": paired_row_share,
            "pairedActualShare": paired_actual_share,
            "comparisonComplete": pairing_complete,
            "pairedRowsIdentical": pairing["pairedRowsIdentical"],
            "pairingKeys": pairing,
        },
        "gates": gates,
        "passed": all(value["passed"] for value in gates.values()),
    }


def evaluate_acceptance(frame: pd.DataFrame) -> dict[str, Any]:
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
        "zero_share_52w",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"acceptance frame is missing: {', '.join(missing)}")
    global_result = _scope_gates(frame)
    markets = {
        str(market): _scope_gates(group)
        for market, group in frame.groupby("market_id", sort=True, observed=True)
    }
    market_gate = bool(markets) and all(result["passed"] for result in markets.values())
    return {
        "schemaVersion": ACCEPTANCE_SCHEMA_VERSION,
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
