"""Explicit batch input-authority verification shared by ML entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from retail_contracts.input_authority import verify_input_authority


def verify_job_authority(
    *,
    repository_root: str | Path,
    authority_path: str | Path,
    expected_pin_path: str | Path,
    expected_run_id: str,
    expected_job_purpose: str,
    retailer_id: str,
    tenant_id: str,
    environment: str,
    evidence_root: str | Path,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    pin = Path(expected_pin_path)
    if not pin.is_absolute():
        pin = root / pin
    return verify_input_authority(
        authority_path,
        schema_path=root / "contracts/onboarding/input-authority.schema.json",
        repository_root=root,
        expected_run_id=expected_run_id,
        expected_job_purpose=expected_job_purpose,
        retailer_id=retailer_id,
        tenant_id=tenant_id,
        environment=environment,
        expected_pin_path=pin,
        evidence_root=evidence_root,
    )


def selection_ids(authority: dict[str, Any]) -> dict[str, str]:
    return {
        str(scope["capability"]): str(scope["selectionId"])
        for scope in authority["scopes"]
    }


__all__ = ["selection_ids", "verify_job_authority"]
