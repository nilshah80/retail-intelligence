"""Thread-safe stage telemetry with explicitly sampled process RSS."""

from __future__ import annotations

import os
import platform
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from math import isfinite
from typing import Any, Iterator

import psutil


@dataclass
class _StageAggregate:
    calls: int = 0
    cumulative_seconds: float = 0.0
    max_sampled_rss_bytes: int = 0
    rss_samples: int = 0


@dataclass
class _ValueAggregate:
    calls: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    samples: list[float] = field(default_factory=list)


def _percentile(samples: list[float], quantile: float) -> float:
    """Return a linearly interpolated percentile without a NumPy dependency."""

    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - lower_index
    return ordered[lower_index] + (
        ordered[upper_index] - ordered[lower_index]
    ) * fraction


class MLStageTelemetry:
    """Collect stage timings without claiming an continuously sampled RSS peak."""

    def __init__(self) -> None:
        self._process = psutil.Process(os.getpid())
        self._lock = threading.Lock()
        self._stages: dict[str, _StageAggregate] = {}
        self._values: dict[str, _ValueAggregate] = {}
        self._rss_scope = "process_tree"
        self._max_sampled_rss_bytes = self._sample_rss()

    def _sample_rss(self) -> int:
        try:
            total = int(self._process.memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return 0
        try:
            for child in self._process.children(recursive=True):
                try:
                    total += int(child.memory_info().rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            self._rss_scope = "process_only"
        return total

    def observe(self) -> int:
        sampled = self._sample_rss()
        with self._lock:
            self._max_sampled_rss_bytes = max(
                self._max_sampled_rss_bytes,
                sampled,
            )
        return sampled

    def record_value(self, name: str, value: int | float) -> None:
        """Record a finite numeric observation from concurrent model workers."""

        if not name:
            raise ValueError("telemetry value name is required")
        numeric = float(value)
        if not isfinite(numeric):
            raise ValueError("telemetry values must be finite")
        with self._lock:
            aggregate = self._values.setdefault(name, _ValueAggregate())
            aggregate.calls += 1
            aggregate.total += numeric
            aggregate.samples.append(numeric)
            aggregate.minimum = (
                numeric
                if aggregate.minimum is None
                else min(aggregate.minimum, numeric)
            )
            aggregate.maximum = (
                numeric
                if aggregate.maximum is None
                else max(aggregate.maximum, numeric)
            )

    @contextmanager
    def measure(
        self,
        stage: str,
        *,
        sample_rss: bool = True,
    ) -> Iterator[None]:
        if not stage:
            raise ValueError("telemetry stage name is required")
        started = time.perf_counter()
        if sample_rss:
            self.observe()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            sampled = self.observe() if sample_rss else 0
            with self._lock:
                aggregate = self._stages.setdefault(stage, _StageAggregate())
                aggregate.calls += 1
                aggregate.cumulative_seconds += elapsed
                aggregate.rss_samples += 2 if sample_rss else 0
                aggregate.max_sampled_rss_bytes = max(
                    aggregate.max_sampled_rss_bytes,
                    sampled,
                )

    def snapshot(self) -> dict[str, Any]:
        self.observe()
        with self._lock:
            stages = {
                name: {
                    "calls": aggregate.calls,
                    "cumulativeSeconds": (
                        f"{aggregate.cumulative_seconds:.6f}"
                    ),
                    "maxSampledRssBytes": aggregate.max_sampled_rss_bytes,
                    "rssSamples": aggregate.rss_samples,
                }
                for name, aggregate in sorted(self._stages.items())
            }
            values = {
                name: {
                    "calls": aggregate.calls,
                    "minimum": aggregate.minimum,
                    "maximum": aggregate.maximum,
                    "mean": aggregate.total / aggregate.calls,
                    "p50": _percentile(aggregate.samples, 0.50),
                    "p90": _percentile(aggregate.samples, 0.90),
                    "p95": _percentile(aggregate.samples, 0.95),
                }
                for name, aggregate in sorted(self._values.items())
            }
            maximum = self._max_sampled_rss_bytes
        return {
            "schemaVersion": "retail-ml-stage-telemetry/v2",
            "rssMeasurement": (
                f"sampled_at_stage_boundaries_{self._rss_scope}"
            ),
            "maxSampledRssBytes": maximum,
            "logicalCpuCount": os.cpu_count() or 1,
            "pythonVersion": platform.python_version(),
            "platform": sys.platform,
            "stages": stages,
            "values": values,
        }


__all__ = ["MLStageTelemetry"]
