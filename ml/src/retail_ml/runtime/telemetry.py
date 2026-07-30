"""Thread-safe stage telemetry with explicitly sampled process RSS."""

from __future__ import annotations

import os
import platform
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import psutil


@dataclass
class _StageAggregate:
    calls: int = 0
    cumulative_seconds: float = 0.0
    max_sampled_rss_bytes: int = 0


class MLStageTelemetry:
    """Collect stage timings without claiming an continuously sampled RSS peak."""

    def __init__(self) -> None:
        self._process = psutil.Process(os.getpid())
        self._lock = threading.Lock()
        self._stages: dict[str, _StageAggregate] = {}
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

    @contextmanager
    def measure(self, stage: str) -> Iterator[None]:
        if not stage:
            raise ValueError("telemetry stage name is required")
        started = time.perf_counter()
        self.observe()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - started
            sampled = self.observe()
            with self._lock:
                aggregate = self._stages.setdefault(stage, _StageAggregate())
                aggregate.calls += 1
                aggregate.cumulative_seconds += elapsed
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
                }
                for name, aggregate in sorted(self._stages.items())
            }
            maximum = self._max_sampled_rss_bytes
        return {
            "schemaVersion": "retail-ml-stage-telemetry/v1",
            "rssMeasurement": (
                f"sampled_at_stage_boundaries_{self._rss_scope}"
            ),
            "maxSampledRssBytes": maximum,
            "logicalCpuCount": os.cpu_count() or 1,
            "pythonVersion": platform.python_version(),
            "platform": sys.platform,
            "stages": stages,
        }


__all__ = ["MLStageTelemetry"]
