"""Bind the shared execution resolver's ML namespace without a local parser."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Mapping

from retail_execution.profiles import resolve_profile


@dataclass(frozen=True)
class MLRuntimeProfile:
    schema_version: str
    profile: str
    feature_workers: int
    fold_workers: int
    model_workers: int
    threads_per_model: int
    memory_limit_gb: int

    def as_manifest_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "profile": self.profile,
            "affectsRunIdentity": False,
            "featureWorkers": self.feature_workers,
            "foldWorkers": self.fold_workers,
            "modelWorkers": self.model_workers,
            "threadsPerModel": self.threads_per_model,
            "memoryLimitGb": self.memory_limit_gb,
            "effectiveModelWorkers": model_worker_budget(self),
        }


def model_worker_budget(
    profile: MLRuntimeProfile,
    *,
    logical_cpu_count: int | None = None,
) -> int:
    cpus = logical_cpu_count or os.cpu_count() or 1
    cpu_bound = max(1, cpus // profile.threads_per_model)
    memory_bound = max(1, profile.memory_limit_gb // 2)
    return max(1, min(profile.model_workers, cpu_bound, memory_bound))


def resolve_ml_runtime_profile(
    name: str | None = None,
    *,
    document: Mapping[str, Any] | None = None,
    overrides: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> MLRuntimeProfile:
    resolved = resolve_profile(
        name,
        document=document,
        layer_overrides={"ml": overrides or {}},
        environment=environment,
    )
    values = resolved["ml"]
    return MLRuntimeProfile(
        schema_version=resolved["schemaVersion"],
        profile=resolved["profile"],
        feature_workers=values["featureWorkers"],
        fold_workers=values["foldWorkers"],
        model_workers=values["modelWorkers"],
        threads_per_model=values["threadsPerModel"],
        memory_limit_gb=values["memoryLimitGb"],
    )


__all__ = [
    "MLRuntimeProfile",
    "model_worker_budget",
    "resolve_ml_runtime_profile",
]
