"""CPU and peak-RSS measurement that does not require a POSIX host.

`resource` is POSIX-only. An unguarded top-level `import resource` makes this
whole package unimportable on Windows, which is a harder failure than losing the
telemetry it provides: the generator would not run at all.

The POSIX path is deliberately byte-identical to the previous inline calls,
including the macOS-versus-Linux `ru_maxrss` unit difference -- macOS reports
bytes and Linux reports kibibytes. Manifest telemetry feeds run fingerprints, so
a portability fix that also changed a measured value on the accepted host would
not be a portability fix.

Windows uses `ctypes` against `GetProcessMemoryInfo` and `GetProcessTimes`, both
stdlib-reachable, so no dependency is added. `PeakWorkingSetSize` is the
equivalent of `ru_maxrss`: the high-water mark of resident memory, not the
current value.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Final

#: Recorded in telemetry so a reader can tell which measurement produced a
#: number, rather than having to infer it from the host.
BASIS_POSIX_RUSAGE: Final[str] = "posix_getrusage"
BASIS_WINDOWS_PROCESS_API: Final[str] = "windows_process_api"
BASIS_UNAVAILABLE: Final[str] = "unavailable"

REASON_NO_MEASUREMENT_API: Final[str] = "NO_SUPPORTED_PROCESS_MEASUREMENT_API"

_IS_WINDOWS: Final[bool] = sys.platform == "win32"
_IS_MACOS: Final[bool] = sys.platform == "darwin"

if not _IS_WINDOWS:  # pragma: no cover - exercised on POSIX hosts
    import resource
else:  # pragma: no cover - exercised on Windows hosts
    resource = None  # type: ignore[assignment]


@dataclass(frozen=True)
class ProcessUsage:
    """A point-in-time reading of this process's CPU and peak resident memory."""

    cpu_seconds: float
    #: Zero means "not measured" and is always paired with a non-null
    #: ``reason_code``; it never means the process used no memory. Kept a plain
    #: ``int`` rather than optional because this value reaches run manifests,
    #: and widening the manifest to carry a null would change the accepted
    #: fingerprints on hosts where the measurement has always worked.
    peak_rss_bytes: int
    basis: str
    reason_code: str | None = None


def _posix_usage() -> ProcessUsage:
    usage = resource.getrusage(resource.RUSAGE_SELF)  # type: ignore[union-attr]
    # macOS reports ru_maxrss in bytes; Linux and the other POSIX hosts report
    # kibibytes. Getting this wrong silently misreports memory by 1024x.
    peak = int(usage.ru_maxrss) if _IS_MACOS else int(usage.ru_maxrss) * 1024
    return ProcessUsage(
        cpu_seconds=usage.ru_utime + usage.ru_stime,
        peak_rss_bytes=peak,
        basis=BASIS_POSIX_RUSAGE,
    )


def _windows_usage() -> ProcessUsage:  # pragma: no cover - Windows only
    import ctypes
    from ctypes import wintypes

    class _MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # Resolved via getattr because WinDLL does not exist in the POSIX ctypes
    # stubs; this branch only runs on Windows.
    windll = getattr(ctypes, "WinDLL")
    kernel32 = windll("kernel32", use_last_error=True)
    psapi = windll("psapi", use_last_error=True)
    handle = kernel32.GetCurrentProcess()

    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(_MemoryCounters)
    peak = 0
    measured = False
    if psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), counters.cb
    ):
        peak = int(counters.PeakWorkingSetSize)
        measured = True

    creation = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel_time = wintypes.FILETIME()
    user_time = wintypes.FILETIME()
    cpu_seconds = 0.0
    if kernel32.GetProcessTimes(
        handle,
        ctypes.byref(creation),
        ctypes.byref(exited),
        ctypes.byref(kernel_time),
        ctypes.byref(user_time),
    ):
        def _seconds(value: wintypes.FILETIME) -> float:
            # FILETIME counts 100-nanosecond intervals across two 32-bit halves.
            ticks = (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
            return ticks / 10_000_000.0

        cpu_seconds = _seconds(user_time) + _seconds(kernel_time)

    if not measured:
        return ProcessUsage(
            cpu_seconds=cpu_seconds,
            peak_rss_bytes=0,
            basis=BASIS_UNAVAILABLE,
            reason_code=REASON_NO_MEASUREMENT_API,
        )
    return ProcessUsage(
        cpu_seconds=cpu_seconds,
        peak_rss_bytes=peak,
        basis=BASIS_WINDOWS_PROCESS_API,
    )


def process_usage() -> ProcessUsage:
    """Read this process's CPU total and peak resident memory."""

    if _IS_WINDOWS:  # pragma: no cover - Windows only
        return _windows_usage()
    return _posix_usage()


def cpu_seconds_between(start: ProcessUsage, end: ProcessUsage) -> float:
    """CPU seconds consumed between two readings, rounded as before."""

    return round(end.cpu_seconds - start.cpu_seconds, 6)


__all__ = [
    "BASIS_POSIX_RUSAGE",
    "BASIS_UNAVAILABLE",
    "BASIS_WINDOWS_PROCESS_API",
    "REASON_NO_MEASUREMENT_API",
    "ProcessUsage",
    "cpu_seconds_between",
    "process_usage",
]
