"""Bounded execution-profile resolution for ingestion.

A thin binding onto the shared `retail_execution` resolver — deliberately not a
second parser. `tasks.md` §2.5 requires the common resolver so that a profile change
cannot mean one thing to datagen and another to ingestion.

The resolved profile is recorded in the ingest manifest and **excluded from
landing/canonical fingerprints**: it changes throughput only. `safe` and
`ultra-performance` must accept and quarantine identical rows.
"""

from dataclasses import dataclass
from typing import Any, Mapping

from retail_execution.profiles import ProfileValidationError, resolve_profile

#: The ingestion namespace of `retail-execution-profile/v1`.
INGESTION_FIELDS = (
    "scanWorkers",
    "transformWorkers",
    "writeWorkers",
    "duckdbThreads",
    "memoryLimitGb",
)


@dataclass(frozen=True)
class IngestionRuntime:
    """Bounded runtime controls for one ingest run."""

    profile: str
    scan_workers: int
    transform_workers: int
    write_workers: int
    duckdb_threads: int
    memory_limit_gb: int

    def duckdb_pragmas(self) -> tuple[str, ...]:
        """PRAGMAs to apply to every ingestion DuckDB connection.

        Centralised so no call site invents its own memory ceiling.
        """
        return (
            f"PRAGMA threads={self.duckdb_threads}",
            f"PRAGMA memory_limit='{self.memory_limit_gb}GB'",
        )

    def manifest_record(self) -> dict[str, Any]:
        """The manifest block for this run.

        `affectsRunIdentity: false` mirrors datagen's precedent and documents, in the
        artifact itself, that this block is fingerprint-excluded.
        """
        return {
            "schemaVersion": "retail-execution-profile/v1",
            "profile": self.profile,
            "affectsRunIdentity": False,
            "scanWorkers": self.scan_workers,
            "transformWorkers": self.transform_workers,
            "writeWorkers": self.write_workers,
            "duckdbThreads": self.duckdb_threads,
            "memoryLimitGb": self.memory_limit_gb,
        }


def resolve_ingestion_runtime(
    profile_name: str | None = None,
    *,
    document: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> IngestionRuntime:
    """Resolve the ingestion runtime through the shared resolver.

    Precedence is owned by `retail_execution`: explicit override > supplied document
    > named profile > safe. We do not re-implement it, and we never auto-expand to
    detected host capacity.
    """
    resolved = resolve_profile(
        profile_name,
        document=document,
        layer_overrides={"ingestion": overrides or {}},
        environment=environment,
    )
    block = resolved.get("ingestion")
    if not isinstance(block, Mapping):
        raise ProfileValidationError(
            f"resolved profile {resolved.get('profile')!r} has no ingestion namespace"
        )

    missing = [field for field in INGESTION_FIELDS if field not in block]
    if missing:
        raise ProfileValidationError(
            f"ingestion namespace is missing {', '.join(missing)}"
        )
    if (
        not isinstance(block["memoryLimitGb"], int)
        or isinstance(block["memoryLimitGb"], bool)
    ):
        raise ProfileValidationError(
            "ingestion.memoryLimitGb must be a whole number of GiB"
        )

    return IngestionRuntime(
        profile=str(resolved["profile"]),
        scan_workers=int(block["scanWorkers"]),
        transform_workers=int(block["transformWorkers"]),
        write_workers=int(block["writeWorkers"]),
        duckdb_threads=int(block["duckdbThreads"]),
        memory_limit_gb=int(block["memoryLimitGb"]),
    )


__all__ = [
    "INGESTION_FIELDS",
    "IngestionRuntime",
    "resolve_ingestion_runtime",
]
