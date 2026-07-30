"""Decision #12 confidence formulas."""

from __future__ import annotations

import numpy as np
import pandas as pd


def forecast_confidence(
    p50: pd.Series | np.ndarray | float,
    p90: pd.Series | np.ndarray | float,
) -> np.ndarray:
    median = np.asarray(p50, dtype=float)
    upper = np.asarray(p90, dtype=float)
    spread = np.maximum(upper - median, 0.0)
    relative_spread = spread / np.maximum(median, 1.0)
    return np.round(np.clip(1.0 / (1.0 + relative_spread), 0.0, 1.0), 4)


def aggregate_confidence(
    confidence: pd.Series | np.ndarray,
    p50: pd.Series | np.ndarray,
) -> float | None:
    values = np.asarray(confidence, dtype=float)
    weights = np.maximum(np.asarray(p50, dtype=float), 1.0)
    valid = np.isfinite(values) & np.isfinite(weights)
    if not valid.any():
        return None
    return round(float(np.average(values[valid], weights=weights[valid])), 4)


__all__ = ["aggregate_confidence", "forecast_confidence"]
