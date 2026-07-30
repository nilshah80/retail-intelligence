"""Fail-closed verification for immutable forecast-run bundles."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ml.publish.run_artifacts import (
    ARTIFACT_SCHEMAS,
    RUN_SCHEMA_VERSION,
    RUN_VOLATILE_POINTERS,
    _frame_semantic_fingerprint,
    _json_semantic_fingerprint,
    _validate_calibration_schedule,
    _validate_complete_schedule,
)


class ForecastRunVerificationError(RuntimeError):
    """A forecast bundle is missing, corrupt, or semantically inconsistent."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ForecastRunVerificationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ForecastRunVerificationError(
            f"cannot read valid JSON from {path}: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ForecastRunVerificationError(f"{path} must contain a JSON object")
    return document


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ForecastRunVerificationError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ForecastRunVerificationError(message)


def _safe_artifact_path(root: Path, value: Any) -> Path:
    _require(isinstance(value, str) and bool(value), "artifact path is required")
    logical = Path(value)
    _require(
        not logical.is_absolute() and logical.name == value,
        f"artifact path must be one local filename: {value!r}",
    )
    resolved = (root / logical).resolve()
    _require(
        resolved.parent == root and resolved.is_file(),
        f"artifact path escapes or is absent: {value!r}",
    )
    return resolved


@dataclass(frozen=True)
class VerifiedForecastRun:
    """Identity and physical paths released only after every check passes."""

    root: Path
    manifest: dict[str, Any]
    artifact_paths: dict[str, Path]

    @property
    def forecast_run_id(self) -> str:
        return str(self.manifest["forecastRunId"])

    @property
    def semantic_fingerprint(self) -> str:
        return str(self.manifest["semanticFingerprint"])

    @property
    def lifecycle_status(self) -> str:
        return str(self.manifest["lifecycleStatus"])


def verify_forecast_run(path: str | Path) -> VerifiedForecastRun:
    """Verify manifest identity, every object, schedule, and lifecycle binding."""

    root = Path(path).resolve()
    _require(root.is_dir(), f"forecast-run root is absent: {root}")
    manifest = _load_json(root / "forecast-run-manifest.json")
    _require(
        manifest.get("schemaVersion") == RUN_SCHEMA_VERSION,
        "unsupported forecast-run schemaVersion",
    )
    expected_artifacts = set(ARTIFACT_SCHEMAS)
    artifacts = manifest.get("artifacts")
    _require(
        isinstance(artifacts, dict) and set(artifacts) == expected_artifacts,
        "forecast-run artifacts do not match the frozen contract",
    )
    fingerprint_contract = manifest.get("fingerprintContract")
    _require(
        isinstance(fingerprint_contract, dict)
        and fingerprint_contract.get("schemaVersion") == "semantic-fingerprint/v1"
        and fingerprint_contract.get("volatilePointers")
        == list(RUN_VOLATILE_POINTERS),
        "forecast-run fingerprint contract differs from the frozen contract",
    )
    recorded_fingerprint = manifest.get("semanticFingerprint")
    _require(_is_sha256(recorded_fingerprint), "invalid run semanticFingerprint")
    fingerprint_payload = dict(manifest)
    fingerprint_payload.pop("semanticFingerprint", None)
    try:
        recomputed_fingerprint = semantic_fingerprint(
            fingerprint_payload,
            volatile_pointers=RUN_VOLATILE_POINTERS,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ForecastRunVerificationError(
            f"forecast-run manifest cannot be fingerprinted: {exc}"
        ) from exc
    _require(
        recomputed_fingerprint == recorded_fingerprint,
        "forecast-run semantic fingerprint does not match its content",
    )
    try:
        parsed_decision_as_of = datetime.fromisoformat(
            str(manifest["decisionAsOf"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise ForecastRunVerificationError("invalid decisionAsOf") from exc
    _require(
        parsed_decision_as_of.tzinfo is not None,
        "decisionAsOf must be timezone-aware",
    )

    artifact_paths: dict[str, Path] = {}
    for name, schema_version in ARTIFACT_SCHEMAS.items():
        descriptor = artifacts[name]
        _require(isinstance(descriptor, dict), f"invalid descriptor for {name}")
        _require(
            descriptor.get("schemaVersion") == schema_version,
            f"invalid schemaVersion for {name}",
        )
        _require(
            _is_sha256(descriptor.get("sha256"))
            and _is_sha256(descriptor.get("semanticFingerprint")),
            f"invalid hashes for {name}",
        )
        artifact_path = _safe_artifact_path(root, descriptor.get("path"))
        _require(
            artifact_path.stat().st_size == descriptor.get("bytes"),
            f"byte size mismatch for {name}",
        )
        _require(
            _sha256_file(artifact_path) == descriptor.get("sha256"),
            f"physical hash mismatch for {name}",
        )
        artifact_paths[name] = artifact_path

    frames: dict[str, pd.DataFrame] = {}
    for name, artifact_path in artifact_paths.items():
        descriptor = artifacts[name]
        if name == "forecast_acceptance":
            acceptance = _load_json(artifact_path)
            semantic = _json_semantic_fingerprint(
                acceptance,
                schema_version=ARTIFACT_SCHEMAS[name],
            )
            row_count = 1
        else:
            try:
                frame = pd.read_parquet(artifact_path)
            except (OSError, ValueError, TypeError) as exc:
                raise ForecastRunVerificationError(
                    f"cannot read Parquet artifact {name}: {exc}"
                ) from exc
            frames[name] = frame
            semantic = _frame_semantic_fingerprint(
                frame,
                schema_version=ARTIFACT_SCHEMAS[name],
            )
            row_count = len(frame)
        _require(
            row_count == descriptor.get("rowCount"),
            f"row count mismatch for {name}",
        )
        _require(
            semantic == descriptor.get("semanticFingerprint"),
            f"semantic fingerprint mismatch for {name}",
        )

    evaluation = frames["forecast_eval_predictions"]
    calibration = frames["forecast_calibration"]
    try:
        _validate_complete_schedule(evaluation)
        _validate_calibration_schedule(calibration, evaluation)
    except RuntimeError as exc:
        raise ForecastRunVerificationError(str(exc)) from exc
    additive_columns = artifacts["forecast_eval_predictions"].get(
        "additiveMetricColumns"
    )
    _require(
        additive_columns
        == [
            "abs_error_sum",
            "signed_error_sum",
            "actual_sum",
            "coverage_hits",
            "n",
        ]
        and set(additive_columns) <= set(evaluation.columns),
        "evaluation additive metric columns differ from the frozen contract",
    )
    lifecycle_status = manifest.get("lifecycleStatus")
    _require(
        lifecycle_status in {"accepted", "rejected"},
        "invalid forecast lifecycleStatus",
    )
    _require(
        acceptance.get("schemaVersion")
        == ARTIFACT_SCHEMAS["forecast_acceptance"]
        and isinstance(acceptance.get("passed"), bool),
        "invalid forecast acceptance document",
    )
    _require(
        (lifecycle_status == "accepted") == acceptance["passed"],
        "lifecycleStatus disagrees with the acceptance verdict",
    )
    versions = frames["forecast_versions"]
    series = frames["forecast_series"]
    drivers = frames["forecast_drivers"]
    _require(
        len(versions) == 1
        and not versions["version_id"].duplicated().any(),
        "forecast_versions must contain exactly one immutable version",
    )
    version_id = str(versions.iloc[0]["version_id"])
    _require(
        str(versions.iloc[0]["status"]) == lifecycle_status,
        "canonical forecast version status disagrees with lifecycleStatus",
    )
    _require(
        set(series["version_id"].astype(str)) == {version_id}
        and set(drivers["version_id"].astype(str)) == {version_id},
        "canonical forecast artifacts disagree on version_id",
    )
    _require(
        not series.duplicated(
            [
                "version_id",
                "sku_id",
                "store_id",
                "channel_id",
                "horizon_week",
            ]
        ).any()
        and set(pd.to_numeric(series["horizon_week"]).astype(int).unique())
        == set(range(1, 27)),
        "forecast_series violates its canonical grain or horizon set",
    )
    _require(
        not drivers.duplicated(["version_id", "scope", "driver"]).any(),
        "forecast_drivers violates its canonical grain",
    )

    run_seed = {
        "inputBundle": manifest.get("inputBundle"),
        "featureSemanticFingerprint": manifest.get("featureSemanticFingerprint"),
        "decisionAsOf": parsed_decision_as_of.isoformat(),
        "artifactSemanticFingerprints": {
            name: artifacts[name]["semanticFingerprint"]
            for name in ARTIFACT_SCHEMAS
        },
        "classificationPolicies": manifest.get("classificationPolicies"),
    }
    expected_run_id = "fr_" + hashlib.sha256(
        json.dumps(
            run_seed,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    _require(
        manifest.get("forecastRunId") == expected_run_id,
        "forecastRunId does not match semantic run inputs",
    )
    return VerifiedForecastRun(
        root=root,
        manifest=manifest,
        artifact_paths=artifact_paths,
    )


__all__ = [
    "ForecastRunVerificationError",
    "VerifiedForecastRun",
    "verify_forecast_run",
]
