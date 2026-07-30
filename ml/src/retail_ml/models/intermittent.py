"""Channel-aware intermittent-demand routing using Croston SBA."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import date

import pandas as pd

from retail_ml.keys import SeriesKey
from retail_ml.models.confidence import forecast_confidence


def croston_sba(values: Iterable[float], alpha: float = 0.10) -> float:
    if not 0 < alpha <= 1:
        raise ValueError("alpha must be in (0, 1]")
    observations = [max(0.0, float(value)) for value in values]
    nonzero_indices = [index for index, value in enumerate(observations) if value > 0]
    if not nonzero_indices:
        return 0.0
    first = nonzero_indices[0]
    demand_level = observations[first]
    interval_level = float(first + 1)
    last_nonzero = first
    for index in nonzero_indices[1:]:
        interval = float(index - last_nonzero)
        demand_level += alpha * (observations[index] - demand_level)
        interval_level += alpha * (interval - interval_level)
        last_nonzero = index
    return max(
        0.0,
        (1.0 - alpha / 2.0) * demand_level / max(interval_level, 1.0),
    )


def croston_beats_seasonal_naive(
    values: Iterable[float],
    *,
    seasonal_lag: int = 52,
    alpha: float = 0.10,
) -> bool:
    observations = [max(0.0, float(value)) for value in values]
    if len(observations) <= seasonal_lag:
        return False
    actuals: list[float] = []
    croston_predictions: list[float] = []
    seasonal_predictions: list[float] = []
    demand_level: float | None = None
    interval_level = 1.0
    last_nonzero = -1
    for index, observation in enumerate(observations):
        if index >= seasonal_lag:
            actuals.append(observation)
            croston_predictions.append(
                0.0
                if demand_level is None
                else (1.0 - alpha / 2.0)
                * demand_level
                / max(interval_level, 1.0)
            )
            seasonal_predictions.append(observations[index - seasonal_lag])
        if observation <= 0:
            continue
        if demand_level is None:
            demand_level = observation
            interval_level = float(index + 1)
        else:
            interval = float(index - last_nonzero)
            demand_level += alpha * (observation - demand_level)
            interval_level += alpha * (interval - interval_level)
        last_nonzero = index
    denominator = sum(actuals)
    if denominator <= 0:
        return False
    croston_wape = sum(
        abs(actual - predicted)
        for actual, predicted in zip(actuals, croston_predictions, strict=True)
    ) / denominator
    seasonal_wape = sum(
        abs(actual - predicted)
        for actual, predicted in zip(actuals, seasonal_predictions, strict=True)
    ) / denominator
    return croston_wape <= seasonal_wape


def _keys(frame: pd.DataFrame) -> list[SeriesKey]:
    return [
        SeriesKey(str(sku), str(store), str(channel))
        for sku, store, channel in zip(
            frame["sku_id"],
            frame["store_id"],
            frame["channel_id"],
            strict=True,
        )
    ]


def route_intermittent_forecasts(
    scored: pd.DataFrame,
    history: pd.DataFrame,
    *,
    replay_preferred_keys: set[SeriesKey] | None = None,
    zero_share_threshold: float = 0.60,
    alpha: float = 0.10,
) -> pd.DataFrame:
    result = scored.copy()
    result["selected_model"] = "lightgbm_horizon_quantile"
    result["tail_candidate_model"] = ""
    result["tail_candidate_selected"] = False
    result["tail_candidate_p50"] = math.nan
    result["tail_candidate_p90"] = math.nan
    result["confidence"] = forecast_confidence(
        result["yhat_p50"],
        result["yhat_p90"],
    )
    if "zero_share_52w" not in result or history.empty:
        return result
    sparse = (
        pd.to_numeric(result["zero_share_52w"], errors="coerce").fillna(0.0)
        > zero_share_threshold
    )
    levels: dict[SeriesKey, float] = {}
    historically_selected: set[SeriesKey] = set()
    for values, group in history.groupby(
        ["sku_id", "store_id", "channel_id"],
        sort=False,
    ):
        key = SeriesKey(*(str(value) for value in values))
        history_values = group.sort_values("forecast_origin")["origin_units"].tolist()
        levels[key] = croston_sba(history_values, alpha=alpha)
        if croston_beats_seasonal_naive(history_values, alpha=alpha):
            historically_selected.add(key)
    keys = _keys(result)
    sba_values = pd.Series([levels.get(key, math.nan) for key in keys], index=result.index)
    eligible = (
        sparse
        & sba_values.notna()
        & pd.Series([key in historically_selected for key in keys], index=result.index)
    )
    candidate_p50 = sba_values.clip(lower=0.0)
    candidate_p90 = candidate_p50 + np_sqrt(candidate_p50.clip(lower=1.0)) * 1.28
    candidate_p90 = candidate_p90.clip(lower=candidate_p50 + 1.0)
    result.loc[sparse, "tail_candidate_model"] = "croston_sba"
    result.loc[eligible, "tail_candidate_p50"] = candidate_p50[eligible]
    result.loc[eligible, "tail_candidate_p90"] = candidate_p90[eligible]
    replay = replay_preferred_keys or set()
    held_out_replay = (
        result["tail_replay_preferred"].fillna(False).astype(bool)
        if "tail_replay_preferred" in result
        else pd.Series(False, index=result.index)
    )
    routed = eligible & (
        held_out_replay
        | pd.Series([key in replay for key in keys], index=result.index)
    )
    result.loc[routed, "yhat_p50"] = candidate_p50[routed]
    result.loc[routed, "yhat_p90"] = candidate_p90[routed]
    result.loc[routed, "selected_model"] = "croston_sba_replay_selected"
    result.loc[routed, "tail_candidate_selected"] = True
    result.loc[sparse & ~routed, "selected_model"] = "lightgbm_intermittent_fallback"
    result["confidence"] = forecast_confidence(
        result["yhat_p50"],
        result["yhat_p90"],
    )
    return result


def np_sqrt(values: pd.Series) -> pd.Series:
    return values.pow(0.5)


def replay_preferred_tail_keys(
    candidate_history: pd.DataFrame,
    *,
    known_before: str | date,
    min_resolved_rows: int = 8,
) -> set[SeriesKey]:
    if candidate_history.empty:
        return set()
    required = {
        "sku_id",
        "store_id",
        "channel_id",
        "target_week_start",
        "actual_units",
        "lightgbm_p50",
        "tail_candidate_p50",
    }
    missing = sorted(required - set(candidate_history.columns))
    if missing:
        raise ValueError(f"tail replay history is missing: {', '.join(missing)}")
    cutoff = pd.Timestamp(known_before)
    resolved = candidate_history[
        (pd.to_datetime(candidate_history["target_week_start"]) < cutoff)
        & candidate_history["tail_candidate_p50"].notna()
    ].copy()
    if resolved.empty:
        return set()
    resolved["candidate_error"] = (
        pd.to_numeric(resolved["tail_candidate_p50"], errors="coerce")
        - pd.to_numeric(resolved["actual_units"], errors="coerce")
    ).abs()
    resolved["lightgbm_error"] = (
        pd.to_numeric(resolved["lightgbm_p50"], errors="coerce")
        - pd.to_numeric(resolved["actual_units"], errors="coerce")
    ).abs()
    grouped = resolved.groupby(
        ["sku_id", "store_id", "channel_id"],
        sort=False,
    ).agg(
        rows=("actual_units", "size"),
        actual_units=("actual_units", "sum"),
        candidate_error=("candidate_error", "sum"),
        lightgbm_error=("lightgbm_error", "sum"),
    )
    winners = grouped[
        (grouped["rows"] >= int(min_resolved_rows))
        & (grouped["actual_units"] > 0)
        & (grouped["candidate_error"] <= grouped["lightgbm_error"])
    ]
    return {
        SeriesKey(str(sku), str(store), str(channel))
        for sku, store, channel in winners.index
    }


__all__ = [
    "croston_beats_seasonal_naive",
    "croston_sba",
    "replay_preferred_tail_keys",
    "route_intermittent_forecasts",
]
