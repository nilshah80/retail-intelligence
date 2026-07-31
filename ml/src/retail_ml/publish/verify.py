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

from retail_ml.models.backtest import evaluate_acceptance
from retail_ml.models.cohorts import CohortError
from retail_ml.models.cohorts import acceptance_frame as _acceptance_frame
from retail_ml.models.confidence import forecast_confidence
from retail_ml.publish.run_artifacts import (
    ARTIFACT_SCHEMAS,
    EVALUATION_KEY_COLUMNS,
    RUN_SCHEMA_VERSION,
    RUN_VOLATILE_POINTERS,
    _frame_semantic_fingerprint,
    _json_semantic_fingerprint,
    _validate_calibration_schedule,
    _validate_complete_schedule,
    model_policy,
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


def _recompute_remediation_checks(
    evaluation: pd.DataFrame,
    remediation: dict[str, Any],
) -> None:
    """Replay decision #86's structural checks from the published artifacts.

    Reading back the booleans the publisher stored would make
    `independentlyVerified` mean only "the publisher said so". The remediation
    bundle publishes the champion values and the cohort label for exactly this
    reason, so the checks are recomputed here and compared against what was
    recorded. A tampered artifact or a tampered record both fail.
    """

    from retail_ml.diagnostics.comparison import detect_leakage
    from retail_ml.models.cold_start_blend import (
        COHORT_COLUMN,
        COLD_START_COHORT,
        established_rows_unchanged,
    )

    required = ("champion_p50", "champion_p90", COHORT_COLUMN)
    missing = [name for name in required if name not in evaluation.columns]
    _require(
        not missing,
        f"a remediation bundle must publish {missing} so decision #86 can be "
        "replayed rather than trusted",
    )

    frame = evaluation.rename(
        columns={"yhat_p50": "_served_p50", "yhat_p90": "_served_p90"}
    ).rename(columns={"champion_p50": "yhat_p50", "champion_p90": "yhat_p90"})
    unchanged = established_rows_unchanged(
        frame.assign(_c50=frame["_served_p50"], _c90=frame["_served_p90"]),
        candidate_column="_c50",
        candidate_upper_column="_c90",
    )
    _require(
        unchanged["passed"],
        "recomputed decision #86 check failed: untargeted rows are not "
        "byte-identical to the champion",
    )

    cold_start = evaluation[
        evaluation[COHORT_COLUMN].astype(str).eq(COLD_START_COHORT)
    ]
    leakage = detect_leakage(
        cold_start.assign(_candidate=cold_start["yhat_p50"]),
        "_candidate",
        "champion_p50",
    )
    _require(
        not leakage["suspected"],
        f"recomputed leakage battery is not clean: {leakage['signals']}",
    )

    # Decision #86 §2.4, replayed rather than read back. The publisher stored a
    # displayCellIntegrity record; without recomputing it, a bundle could carry an
    # altered record -- or a real store/category regression with a clean-looking record --
    # and `independentlyVerified` would mean only "the publisher said so", which is the
    # exact failure §2.3 and §2.5 are replayed to avoid.
    from retail_ml.publish.run_artifacts import _decision_86_display_evidence

    recorded = (remediation.get("structuralChecks") or {}).get("displayCellIntegrity")
    _require(
        isinstance(recorded, dict),
        "a remediation bundle must publish its decision #86 §2.4 display-cell record",
    )
    replayed = _decision_86_display_evidence(evaluation)
    _require(
        replayed["passed"],
        "recomputed decision #86 §2.4 check failed: "
        f"{[c['grain'] + '/h' + str(c['horizon']) for c in replayed['violations']]}",
    )
    _require(
        sorted(replayed["grainsEvaluated"]) == sorted(recorded.get("grainsEvaluated", [])),
        "published display-cell evidence covers different grains than a replay does: "
        f"recorded {recorded.get('grainsEvaluated')}, replayed "
        f"{replayed['grainsEvaluated']}",
    )
    _require(
        bool(recorded.get("passed")) == bool(replayed["passed"])
        and len(recorded.get("violations") or []) == len(replayed["violations"]),
        "published display-cell verdict disagrees with a replay of it",
    )

    recorded = remediation.get("structuralChecks") or {}
    _require(
        bool((recorded.get("untargetedRowsByteIdentical") or {}).get("passed"))
        == unchanged["passed"],
        "the recorded untargeted-row check disagrees with the recomputation",
    )
    _require(
        (recorded.get("leakage") or {}).get("suspected") == leakage["suspected"],
        "the recorded leakage verdict disagrees with the recomputation",
    )


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
    # Rebuild the policy from the bundle's own declared class so a decision #86
    # remediation bundle verifies against the remediation shape and a champion
    # against the champion shape -- while still refusing any extra or missing field.
    declared_policy = manifest.get("modelPolicy") or {}
    declared_remediation = declared_policy.get("remediation")
    _require(
        declared_policy == model_policy(declared_remediation),
        "forecast-run model/acceptance policy is unsupported",
    )
    # A class without its evidence, or evidence without its class, is refused: the
    # point of #86 is that the two travel together.
    _require(
        (declared_policy.get("candidateClass") == "gate_remediation")
        == (declared_remediation is not None),
        "candidateClass and the remediation record must agree",
    )
    if declared_remediation is not None:
        _require(
            len(declared_remediation.get("confirmationOriginsHeldOut") or []) > 0,
            "a remediation bundle must record which origins were held out",
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
    baselines = frames["forecast_baseline_predictions"]
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
    for label, frame, p50_column, p90_column in (
        ("evaluation", evaluation, "yhat_p50", "yhat_p90"),
        ("current series", frames["forecast_series"], "yhat_p50", "yhat_p90"),
    ):
        # Decision #92 withholds the cold-start interval beyond the calibrated horizon,
        # so those rows carry no P90 and therefore no confidence -- confidence is DERIVED
        # from the interval, so publishing one without the other would assert a certainty
        # nothing supports. Those rows are exempted from the decision #12 identity and
        # required to be null on BOTH fields, so "withheld" cannot become a hiding place
        # for a confidence value that disagrees with its interval.
        upper = pd.to_numeric(frame[p90_column], errors="coerce")
        actual_confidence = pd.to_numeric(frame["confidence"], errors="coerce")
        withheld = upper.isna()
        _require(
            bool(actual_confidence[withheld].isna().all()),
            f"{label} withholds an interval but still publishes a confidence",
        )
        present = ~withheld
        expected_confidence = forecast_confidence(
            frame.loc[present, p50_column],
            frame.loc[present, p90_column],
        )
        served_confidence = actual_confidence[present].to_numpy(dtype=float)
        _require(
            bool(
                pd.notna(served_confidence).all()
                and (abs(served_confidence - expected_confidence) <= 1e-12).all()
            ),
            f"{label} confidence violates decision #12",
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
    try:
        acceptance_frame = _acceptance_frame(
            evaluation,
            baselines,
            EVALUATION_KEY_COLUMNS,
        )
    except CohortError as exc:
        raise ForecastRunVerificationError(str(exc)) from exc
    try:
        derived_acceptance = evaluate_acceptance(
            acceptance_frame,
            candidate_class=(
                "gate_remediation" if declared_remediation is not None else "champion"
            ),
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise ForecastRunVerificationError(
            f"cannot recompute A1-A5 acceptance gates: {exc}"
        ) from exc
    _require(
        derived_acceptance == acceptance,
        "forecast acceptance document does not match recomputed A1-A5 gates",
    )
    if declared_remediation is not None:
        _recompute_remediation_checks(evaluation, declared_remediation)
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
        # Must mirror the publisher's run_seed exactly. modelPolicy is part of the
        # identity so a decision #86 remediation bundle cannot share a run id with a
        # champion bundle over the same forecasts.
        "modelPolicy": manifest.get("modelPolicy"),
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
