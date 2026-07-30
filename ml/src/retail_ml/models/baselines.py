"""Forecast baselines and exact additive metric components."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AdditiveMetrics:
    abs_error_sum: float
    signed_error_sum: float
    actual_sum: float
    coverage_hits: int
    n: int

    @property
    def wape(self) -> float | None:
        return self.abs_error_sum / self.actual_sum if self.actual_sum > 0 else None

    @property
    def bias(self) -> float | None:
        return self.signed_error_sum / self.actual_sum if self.actual_sum > 0 else None

    @property
    def accuracy(self) -> float | None:
        return 100.0 * (1.0 - self.wape) if self.wape is not None else None

    @property
    def coverage(self) -> float | None:
        return self.coverage_hits / self.n if self.n else None

    def plus(self, other: "AdditiveMetrics") -> "AdditiveMetrics":
        return AdditiveMetrics(
            abs_error_sum=self.abs_error_sum + other.abs_error_sum,
            signed_error_sum=self.signed_error_sum + other.signed_error_sum,
            actual_sum=self.actual_sum + other.actual_sum,
            coverage_hits=self.coverage_hits + other.coverage_hits,
            n=self.n + other.n,
        )

    def as_record(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "wape": self.wape,
            "bias": self.bias,
            "accuracy": self.accuracy,
            "coverage": self.coverage,
        }


def attach_baselines(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["naive_baseline"] = pd.to_numeric(
        result.get("units_lag_1", 0.0),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)
    result["seasonal_naive_baseline"] = pd.to_numeric(
        result.get(
            "units_lag_52",
            pd.Series(np.nan, index=result.index, dtype=float),
        ),
        errors="coerce",
    ).clip(lower=0.0)
    result["ma8_baseline"] = pd.to_numeric(
        result.get("units_roll_mean_8", 0.0),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)
    result["ma13_baseline"] = pd.to_numeric(
        result.get("units_roll_mean_13", 0.0),
        errors="coerce",
    ).fillna(0.0).clip(lower=0.0)
    return result


def additive_metrics(
    actual: pd.Series | np.ndarray,
    predicted: pd.Series | np.ndarray,
    *,
    upper: pd.Series | np.ndarray | None = None,
) -> AdditiveMetrics:
    actual_values = pd.to_numeric(pd.Series(actual), errors="coerce")
    predicted_values = pd.to_numeric(pd.Series(predicted), errors="coerce")
    valid = actual_values.notna() & predicted_values.notna()
    actual_array = actual_values[valid].to_numpy(dtype=float)
    predicted_array = predicted_values[valid].to_numpy(dtype=float)
    error = predicted_array - actual_array
    if upper is None:
        hits = 0
    else:
        upper_values = pd.to_numeric(pd.Series(upper), errors="coerce")[valid]
        hits = int((actual_array <= upper_values.to_numpy(dtype=float)).sum())
    return AdditiveMetrics(
        abs_error_sum=float(np.abs(error).sum()),
        signed_error_sum=float(error.sum()),
        actual_sum=float(actual_array.sum()),
        coverage_hits=hits,
        n=len(actual_array),
    )


def metric_for_column(
    frame: pd.DataFrame,
    prediction_column: str,
    *,
    upper_column: str | None = None,
) -> AdditiveMetrics:
    return additive_metrics(
        frame["actual_units"],
        frame[prediction_column],
        upper=frame[upper_column] if upper_column else None,
    )


__all__ = [
    "AdditiveMetrics",
    "additive_metrics",
    "attach_baselines",
    "metric_for_column",
]
