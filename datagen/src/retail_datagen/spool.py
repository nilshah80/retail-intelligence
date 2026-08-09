"""Bounded-memory, repeatable row streams for long-horizon generation."""

from __future__ import annotations

import pickle
import re
import shutil
import time
from heapq import merge as heap_merge
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Callable


class RowSpool:
    """Append-only disk-backed sequence with a bounded memory buffer.

    Pickle is used only for the writer's private working state. The files are
    removed before promotion and are never a published source format.
    """

    def __init__(
        self,
        work_directory: Path,
        name: str,
        *,
        chunk_rows: int = 10_000,
    ) -> None:
        if chunk_rows < 1:
            raise ValueError("chunk_rows must be positive")
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name).strip("-") or "rows"
        work_directory.mkdir(parents=True, exist_ok=True)
        self.path = work_directory / f"{safe_name}.rows"
        suffix = 1
        while True:
            try:
                # Reserve the name immediately. Checking exists() without
                # creating the file allowed two live, not-yet-flushed spools
                # to select the same backing path.
                self.path.touch(exist_ok=False)
                break
            except FileExistsError:
                self.path = work_directory / f"{safe_name}-{suffix}.rows"
                suffix += 1
        self._chunk_rows = chunk_rows
        self._buffer: list[dict[str, Any]] = []
        self._count = 0
        self._last: dict[str, Any] | None = None
        self._closed = False
        self._telemetry: dict[str, float | int] = {
            "flushes": 0,
            "flushSeconds": 0.0,
            "spillBytesWritten": 0,
            "iterationPasses": 0,
            "iterationRowsDecoded": 0,
            "iterationBytesRead": 0,
            "iterationSeconds": 0.0,
            "sortCalls": 0,
            "sortSeconds": 0.0,
            "sortInputBytes": 0,
            "sortSpillBytesWritten": 0,
            "sortPeakTemporaryBytes": 0,
            "sortMergePasses": 0,
        }

    def append(self, row: dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError("cannot append to a closed RowSpool")
        self._buffer.append(row)
        self._last = row
        self._count += 1
        if len(self._buffer) >= self._chunk_rows:
            self.flush()

    def extend(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.append(row)

    def flush(self) -> None:
        if not self._buffer:
            return
        before = self.path.stat().st_size
        started = time.perf_counter()
        with self.path.open("ab") as handle:
            pickle.dump(self._buffer, handle, protocol=pickle.HIGHEST_PROTOCOL)
        self._telemetry["flushes"] = int(self._telemetry["flushes"]) + 1
        self._telemetry["flushSeconds"] = float(
            self._telemetry["flushSeconds"]
        ) + time.perf_counter() - started
        self._telemetry["spillBytesWritten"] = int(
            self._telemetry["spillBytesWritten"]
        ) + self.path.stat().st_size - before
        self._buffer = []

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self.flush()
        if not self.path.exists():
            return
        started = time.perf_counter()
        rows = 0
        size = self.path.stat().st_size
        try:
            with self.path.open("rb") as handle:
                while True:
                    try:
                        chunk = pickle.load(handle)
                    except EOFError:
                        break
                    rows += len(chunk)
                    yield from chunk
        finally:
            self._telemetry["iterationPasses"] = int(
                self._telemetry["iterationPasses"]
            ) + 1
            self._telemetry["iterationRowsDecoded"] = int(
                self._telemetry["iterationRowsDecoded"]
            ) + rows
            self._telemetry["iterationBytesRead"] = int(
                self._telemetry["iterationBytesRead"]
            ) + size
            self._telemetry["iterationSeconds"] = float(
                self._telemetry["iterationSeconds"]
            ) + time.perf_counter() - started

    @staticmethod
    def _iter_sort_run(path: Path) -> Iterator[dict[str, Any]]:
        with path.open("rb") as handle:
            while True:
                try:
                    chunk = pickle.load(handle)
                except EOFError:
                    break
                yield from chunk

    @staticmethod
    def _write_sort_run(
        path: Path,
        rows: Iterable[dict[str, Any]],
        *,
        output_chunk_rows: int = 1_024,
    ) -> None:
        buffer: list[dict[str, Any]] = []
        with path.open("wb") as handle:
            for row in rows:
                buffer.append(row)
                if len(buffer) >= output_chunk_rows:
                    pickle.dump(
                        buffer,
                        handle,
                        protocol=pickle.HIGHEST_PROTOCOL,
                    )
                    buffer = []
            if buffer:
                pickle.dump(
                    buffer,
                    handle,
                    protocol=pickle.HIGHEST_PROTOCOL,
                )

    def iter_sorted(
        self,
        *,
        key: Callable[[dict[str, Any]], Any],
        max_open_runs: int = 16,
    ) -> Iterator[dict[str, Any]]:
        """Externally sort a spool with bounded memory and file descriptors."""

        if max_open_runs < 2:
            raise ValueError("max_open_runs must be at least 2")
        self.flush()
        sort_started = time.perf_counter()
        sort_input_bytes = self.path.stat().st_size
        sort_spill_bytes = 0
        live_sort_bytes = 0
        sort_peak_bytes = 0
        pass_index = 0
        sort_directory = self.path.parent / f".{self.path.name}.sort"
        sort_directory.mkdir(exist_ok=False)
        try:
            runs: list[Path] = []
            buffer: list[dict[str, Any]] = []
            for row in self:
                buffer.append(row)
                if len(buffer) < self._chunk_rows:
                    continue
                buffer.sort(key=key)
                run = sort_directory / f"run-{len(runs):06d}.rows"
                self._write_sort_run(run, buffer)
                run_size = run.stat().st_size
                sort_spill_bytes += run_size
                live_sort_bytes += run_size
                sort_peak_bytes = max(sort_peak_bytes, live_sort_bytes)
                runs.append(run)
                buffer = []
            if buffer:
                buffer.sort(key=key)
                run = sort_directory / f"run-{len(runs):06d}.rows"
                self._write_sort_run(run, buffer)
                run_size = run.stat().st_size
                sort_spill_bytes += run_size
                live_sort_bytes += run_size
                sort_peak_bytes = max(sort_peak_bytes, live_sort_bytes)
                runs.append(run)
            while len(runs) > max_open_runs:
                merged_runs: list[Path] = []
                for offset in range(0, len(runs), max_open_runs):
                    group = runs[offset : offset + max_open_runs]
                    merged_path = (
                        sort_directory
                        / f"merge-{pass_index:03d}-{len(merged_runs):06d}.rows"
                    )
                    self._write_sort_run(
                        merged_path,
                        heap_merge(
                            *(self._iter_sort_run(path) for path in group),
                            key=key,
                        ),
                    )
                    merged_size = merged_path.stat().st_size
                    sort_spill_bytes += merged_size
                    live_sort_bytes += merged_size
                    sort_peak_bytes = max(sort_peak_bytes, live_sort_bytes)
                    merged_runs.append(merged_path)
                    for path in group:
                        live_sort_bytes -= path.stat().st_size
                        path.unlink()
                runs = merged_runs
                pass_index += 1
            if runs:
                yield from heap_merge(
                    *(self._iter_sort_run(path) for path in runs),
                    key=key,
                )
        finally:
            self._telemetry["sortCalls"] = int(self._telemetry["sortCalls"]) + 1
            self._telemetry["sortSeconds"] = float(
                self._telemetry["sortSeconds"]
            ) + time.perf_counter() - sort_started
            self._telemetry["sortInputBytes"] = int(
                self._telemetry["sortInputBytes"]
            ) + sort_input_bytes
            self._telemetry["sortSpillBytesWritten"] = int(
                self._telemetry["sortSpillBytesWritten"]
            ) + sort_spill_bytes
            self._telemetry["sortPeakTemporaryBytes"] = max(
                int(self._telemetry["sortPeakTemporaryBytes"]),
                sort_peak_bytes,
            )
            self._telemetry["sortMergePasses"] = int(
                self._telemetry["sortMergePasses"]
            ) + pass_index
            shutil.rmtree(sort_directory, ignore_errors=True)

    def telemetry_snapshot(self) -> dict[str, Any]:
        """Stable shape, unstable measurements; excluded from run identity."""

        return {
            "spool": self.path.name,
            "logicalRows": self._count,
            "bufferRows": len(self._buffer),
            "backingBytes": self.path.stat().st_size if self.path.exists() else 0,
            **{
                key: round(value, 6) if isinstance(value, float) else value
                for key, value in self._telemetry.items()
            },
        }

    def __len__(self) -> int:
        return self._count

    def __bool__(self) -> bool:
        return self._count > 0

    def __getitem__(self, index: int) -> dict[str, Any]:
        if index != -1:
            raise TypeError("RowSpool supports only [-1] random access")
        if self._last is None:
            raise IndexError("RowSpool index out of range")
        return self._last

    def close(self) -> None:
        self._buffer = []
        self.path.unlink(missing_ok=True)
        self._count = 0
        self._last = None
        self._closed = True
