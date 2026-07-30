"""Decision #57 deterministic TreeSHAP presentation aggregation."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any, Final

import numpy as np
import pandas as pd

from retail_ml.keys import SeriesKey

LIVE_DRIVER_GROUPS: Final[tuple[str, ...]] = (
    "demand_trend",
    "seasonality",
    "price",
    "competitor_activity",
    "weather_local_events",
)
PERCENT_UNITS: Final[int] = 1_000_000  # 100.0000 percent / 0.0001


def _rounded_percent_units(
    magnitudes: dict[str, float],
) -> dict[str, int]:
    total = sum(magnitudes.values())
    if total <= 0:
        return {group: 0 for group in LIVE_DRIVER_GROUPS}
    exact = {
        group: magnitudes[group] / total * PERCENT_UNITS
        for group in LIVE_DRIVER_GROUPS
    }
    allocated = {group: math.floor(value) for group, value in exact.items()}
    remaining = PERCENT_UNITS - sum(allocated.values())
    order = sorted(
        LIVE_DRIVER_GROUPS,
        key=lambda group: (-(exact[group] - allocated[group]), group),
    )
    for group in order[:remaining]:
        allocated[group] += 1
    return allocated


def _scope_rows(frame: pd.DataFrame, *, scope: str) -> list[dict[str, Any]]:
    if "selected_model" in frame:
        croston_mask = (
            frame["selected_model"]
            .fillna("")
            .astype(str)
            .str.startswith("croston_sba")
        )
    else:
        croston_mask = pd.Series(False, index=frame.index)
    explained = frame.loc[~croston_mask]
    croston_rows = int(croston_mask.sum())
    signed = {
        group: pd.to_numeric(
            (
                explained[f"shap_{group}"]
                if f"shap_{group}" in explained
                else pd.Series(0.0, index=explained.index)
            ),
            errors="coerce",
        ).fillna(0.0)
        for group in LIVE_DRIVER_GROUPS
    }
    magnitudes = {
        group: float(values.abs().sum()) for group, values in signed.items()
    }
    percentage_units = _rounded_percent_units(magnitudes)
    rows: list[dict[str, Any]] = []
    for group in LIVE_DRIVER_GROUPS:
        values = signed[group].to_numpy(dtype=float)
        magnitude = magnitudes[group]
        positive = float(np.clip(values, 0.0, None).sum())
        negative = float(np.clip(-values, 0.0, None).sum())
        if magnitude <= 0:
            direction = "Neutral"
            confidence = 0.0
        else:
            positive_share = positive / magnitude
            negative_share = negative / magnitude
            if positive_share >= 0.20 and negative_share >= 0.20:
                direction = "Mixed"
            elif positive > negative:
                direction = "Up"
            elif negative > positive:
                direction = "Down"
            else:
                direction = "Neutral"
            confidence = round(max(positive_share, negative_share), 4)
        rows.append(
            {
                "scope": scope,
                "driver": group,
                "contribution_pct": f"{percentage_units[group] / 10000:.4f}",
                "direction": direction,
                "confidence": f"{confidence:.4f}",
                "method": (
                    "lightgbm_tree_shap_p50"
                    if croston_rows == 0
                    else "lightgbm_tree_shap_p50_excludes_croston_rows"
                ),
                "magnitude": f"{magnitude:.8f}",
                "explained_rows": len(explained),
                "croston_rows": croston_rows,
            }
        )
    if croston_rows:
        rows.append(
            {
                "scope": scope,
                "driver": "croston_routing_explanation",
                "contribution_pct": "0.0000",
                "direction": "Neutral",
                "confidence": "1.0000",
                "method": "croston_sba_replay_routing",
                "magnitude": "0.00000000",
                "explained_rows": len(explained),
                "croston_rows": croston_rows,
            }
        )
    return rows


def series_scope(key: SeriesKey) -> str:
    return "series:" + json.dumps(key.as_tuple(), separators=(",", ":"))


def aggregate_driver_rows(
    scored: pd.DataFrame,
    *,
    include_series: bool = True,
) -> pd.DataFrame:
    rows = _scope_rows(scored, scope="portfolio")
    if include_series:
        for values, group in scored.groupby(
            ["sku_id", "store_id", "channel_id"],
            sort=True,
            observed=True,
        ):
            key = SeriesKey(*(str(value) for value in values))
            rows.extend(_scope_rows(group, scope=series_scope(key)))
    return pd.DataFrame(rows)


def live_contribution_total(rows: Iterable[dict[str, Any]]) -> float:
    return sum(
        float(row["contribution_pct"])
        for row in rows
        if row["driver"] in LIVE_DRIVER_GROUPS
    )


__all__ = [
    "LIVE_DRIVER_GROUPS",
    "aggregate_driver_rows",
    "live_contribution_total",
    "series_scope",
]
