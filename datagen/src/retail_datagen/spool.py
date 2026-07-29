"""Bounded-memory, repeatable row streams for long-horizon generation."""

from __future__ import annotations

import pickle
import re
import shutil
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
        with self.path.open("ab") as handle:
            pickle.dump(self._buffer, handle, protocol=pickle.HIGHEST_PROTOCOL)
        self._buffer = []

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self.flush()
        if not self.path.exists():
            return
        with self.path.open("rb") as handle:
            while True:
                try:
                    chunk = pickle.load(handle)
                except EOFError:
                    break
                yield from chunk

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
                runs.append(run)
                buffer = []
            if buffer:
                buffer.sort(key=key)
                run = sort_directory / f"run-{len(runs):06d}.rows"
                self._write_sort_run(run, buffer)
                runs.append(run)
            pass_index = 0
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
                    merged_runs.append(merged_path)
                    for path in group:
                        path.unlink()
                runs = merged_runs
                pass_index += 1
            if runs:
                yield from heap_merge(
                    *(self._iter_sort_run(path) for path in runs),
                    key=key,
                )
        finally:
            shutil.rmtree(sort_directory, ignore_errors=True)

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
