"""Independent verification of an inventory/replenishment bundle (P4-8 task 1).

This RECOMPUTES; it does not read the run's opinion of itself. Every check exists
because its absence would let a bundle assert something nobody measured -- the
posture the forecast verifier reached only after a closure record was found
stating facts nothing had checked.

Lineage is compared against externally supplied authority: the committed pin, the
ACTIVE decision-#73 selection and the live decision-#90 forecast authority. A
manifest verified only against itself proves internal consistency and nothing
else.

Refusal is total. There is no partial pass, because a partly-verified bundle
serving fourteen screens has no honest way to say which screen is trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Final, Mapping

import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ml.inventory_publish.run_artifacts import (
    ARTIFACT_SCHEMAS,
    CALIBRATED_MAX_HORIZON,
    POLICY_VERSION,
    RUN_SCHEMA_VERSION,
    RUN_VOLATILE_POINTERS,
    _validate_artifact,
    _validate_replay,
)
from retail_ml.publish.run_artifacts import (
    _frame_semantic_fingerprint,
    _json_semantic_fingerprint,
)

VERIFIER_POLICY_ID: Final[str] = "retail-inventory-verifier/v1"


class InventoryVerificationError(RuntimeError):
    """A bundle cannot be independently verified."""


@dataclass(frozen=True)
class VerifiedInventoryRun:
    """Identity and physical paths released only after every check passes."""

    root: Path
    manifest: dict[str, Any]
    artifact_paths: dict[str, Path]

    @property
    def inventory_run_id(self) -> str:
        return str(self.manifest["inventoryRunId"])

    @property
    def semantic_fingerprint(self) -> str:
        return str(self.manifest["semanticFingerprint"])

    @property
    def lifecycle_status(self) -> str:
        return str(self.manifest["lifecycleStatus"])

    @property
    def markets(self) -> list[str]:
        return [str(market) for market in self.manifest["markets"]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InventoryVerificationError(message)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InventoryVerificationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InventoryVerificationError(
            f"cannot read valid JSON from {path}: {exc}"
        ) from exc
    _require(isinstance(document, dict), f"{path} must contain a JSON object")
    return document


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise InventoryVerificationError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _safe_artifact_path(root: Path, value: Any) -> Path:
    """Resolve a declared filename inside the bundle, or refuse.

    A manifest is untrusted input. Without this, a declared path of
    `../../etc/passwd` would be hashed and reported as a verified artifact.
    """

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


def _pin_lineage(expected_pin: Mapping[str, Any]) -> dict[str, str]:
    """The four lineage values the pin is authoritative for."""

    return {
        "sourceSnapshotId": str(expected_pin.get("sourceSnapshotId")),
        "gateASemanticFingerprint": str(
            (expected_pin.get("gateA") or {}).get("semanticFingerprint")
        ),
        "gateBSemanticFingerprint": str(
            (expected_pin.get("gateB") or {}).get("semanticFingerprint")
        ),
        "publicationSemanticFingerprint": str(
            (expected_pin.get("publication") or {}).get("semanticFingerprint")
        ),
    }


def verify_inventory_run(
    path: str | Path,
    *,
    expected_pin: Mapping[str, Any],
    active_selection_id: str,
    active_forecast: Mapping[str, str],
) -> VerifiedInventoryRun:
    """Recompute identity, bytes, structure, lineage and acceptance, or refuse."""

    root = Path(path).resolve()
    _require(root.is_dir(), f"inventory-run root is absent: {root}")
    manifest = _load_json(root / "inventory-run-manifest.json")
    _require(
        manifest.get("schemaVersion") == RUN_SCHEMA_VERSION,
        f"unsupported inventory-run schemaVersion {manifest.get('schemaVersion')!r}",
    )
    _require(
        manifest.get("lifecycleStatus") == "accepted",
        f"lifecycleStatus is {manifest.get('lifecycleStatus')!r}; only an accepted "
        "run may be verified for materialization",
    )
    artifacts = manifest.get("artifacts")
    _require(
        isinstance(artifacts, dict) and set(artifacts) == set(ARTIFACT_SCHEMAS),
        "inventory-run artifacts do not match the frozen contract",
    )
    fingerprint_contract = manifest.get("fingerprintContract")
    _require(
        isinstance(fingerprint_contract, dict)
        and fingerprint_contract.get("schemaVersion") == "semantic-fingerprint/v1"
        and fingerprint_contract.get("volatilePointers")
        == list(RUN_VOLATILE_POINTERS),
        "inventory-run fingerprint contract differs from the frozen contract",
    )

    recorded_fingerprint = manifest.get("semanticFingerprint")
    _require(_is_sha256(recorded_fingerprint), "invalid run semanticFingerprint")
    fingerprint_payload = dict(manifest)
    fingerprint_payload.pop("semanticFingerprint", None)
    try:
        recomputed_fingerprint = semantic_fingerprint(
            fingerprint_payload, volatile_pointers=RUN_VOLATILE_POINTERS
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise InventoryVerificationError(
            f"inventory-run manifest cannot be fingerprinted: {exc}"
        ) from exc
    _require(
        recomputed_fingerprint == recorded_fingerprint,
        "inventory-run semantic fingerprint does not match its content",
    )

    # -- bytes: every declared hash, size and row count recomputed -------------
    artifact_paths: dict[str, Path] = {}
    frames: dict[str, pd.DataFrame] = {}
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
        try:
            frame = pd.read_parquet(artifact_path)
        except (OSError, ValueError, TypeError) as exc:
            raise InventoryVerificationError(
                f"cannot read Parquet artifact {name}: {exc}"
            ) from exc
        _require(
            len(frame) == descriptor.get("rowCount"),
            f"row count mismatch for {name}",
        )
        _require(
            _frame_semantic_fingerprint(frame, schema_version=schema_version)
            == descriptor.get("semanticFingerprint"),
            f"semantic fingerprint mismatch for {name}",
        )
        artifact_paths[name] = artifact_path
        frames[name] = frame

    # -- structure: the publisher's own rules, replayed on the read-back rows --
    # Calling the publisher's validators rather than restating them is the point:
    # a rule that only the publisher enforces is a rule a hand-built bundle can
    # walk past, and a second copy here would drift from the first.
    markets = manifest.get("markets")
    _require(
        isinstance(markets, list) and bool(markets) and markets == sorted(markets),
        "manifest markets must be a non-empty sorted list",
    )
    declared_markets = [str(market) for market in markets]
    try:
        for name in ARTIFACT_SCHEMAS:
            _validate_artifact(name, frames[name], markets=declared_markets)
        _validate_replay(
            manifest.get("replay") or {},
            metrics=frames["inventory_replay_metrics"],
        )
    except RuntimeError as exc:
        raise InventoryVerificationError(
            f"published artifacts violate the run contract: {exc}"
        ) from exc

    # -- acceptance: recomputed from the artifact, not read from the manifest --
    acceptance = _load_json(root / "inventory-acceptance.json")
    recorded_acceptance = manifest.get("acceptance") or {}
    _require(
        _json_semantic_fingerprint(
            acceptance, schema_version=str(acceptance.get("schemaVersion"))
        )
        == recorded_acceptance.get("semanticFingerprint"),
        "the acceptance document does not match the fingerprint the manifest "
        "recorded for it",
    )
    _require(
        isinstance(acceptance.get("passed"), bool)
        and acceptance["passed"] is True
        and recorded_acceptance.get("passed") is True,
        "an accepted lifecycle requires a passing acceptance document",
    )
    _require(
        acceptance.get("replay") == manifest.get("replay"),
        "the acceptance document and the manifest disagree about the replay",
    )
    # Every published gate must actually have passed. A verdict of "accepted" over
    # a failing gate row is exactly the state the per-market gates exist to stop.
    gates = frames["inventory_replay_metrics"]
    failed = gates[~gates["passed"].astype(bool)]
    _require(
        failed.empty,
        "accepted run publishes failing replay gates: "
        + ", ".join(
            f"{row.market_id}/{row.metric}/{row.cohort}"
            for row in failed.itertuples()
        ),
    )

    # -- lineage: against external authority, never against self --------------
    input_bundle = manifest.get("inputBundle") or {}
    expected_lineage = _pin_lineage(expected_pin)
    for field, expected in expected_lineage.items():
        _require(
            input_bundle.get(field) == expected,
            f"inputBundle.{field} does not match the committed pin",
        )
    _require(
        manifest.get("sourceSelectionId") == active_selection_id,
        "sourceSelectionId does not name the ACTIVE decision-#73 selection; a "
        "source pin without an active selection is not authority",
    )
    forecast = manifest.get("forecastAuthority") or {}
    for field in ("forecastRunId", "forecastVersionId"):
        _require(
            forecast.get(field) == active_forecast.get(field),
            f"forecastAuthority.{field} is not the live active forecast; an "
            "inventory number computed from a superseded forecast is stale",
        )
    _require(
        forecast.get("coverageGateMode") == "hard",
        "the consumed forecast was not scored under decision #85's hard "
        "per-cohort coverage gate",
    )

    # -- decision #92 and the frozen policy -----------------------------------
    interval = manifest.get("intervalAvailability") or {}
    _require(
        interval.get("calibratedMaxHorizon") == CALIBRATED_MAX_HORIZON,
        f"calibratedMaxHorizon is {interval.get('calibratedMaxHorizon')!r}, not "
        f"{CALIBRATED_MAX_HORIZON}; moving the boundary needs a preregistered "
        "mechanism, not a manifest field",
    )
    _require(
        interval.get("consumersEnabled") is True,
        "intervalAvailability.consumersEnabled is false, so this bundle should "
        "not carry interval-derived artifacts at all",
    )
    policy = manifest.get("policy") or {}
    _require(
        policy.get("policyVersion") == POLICY_VERSION,
        f"policyVersion is {policy.get('policyVersion')!r}, not {POLICY_VERSION}",
    )
    resolved = policy.get("resolvedFingerprints") or {}
    unresolved = [market for market in declared_markets if market not in resolved]
    _require(
        not unresolved,
        f"no resolved policy fingerprint for markets {unresolved}; an unresolved "
        "market is served by no policy at all",
    )
    lanes = manifest.get("laneContract") or {}
    coverage = lanes.get("fulfillmentCoveragePct")
    _require(
        coverage is not None and float(coverage) >= 100.0,
        f"lane coverage is {coverage}%; a fulfillment row the network cannot "
        "explain cannot be replayed",
    )

    # -- identity: the run id must be what its own inputs imply ---------------
    run_seed = {
        "inputBundle": input_bundle,
        "sourceSelectionId": manifest.get("sourceSelectionId"),
        "forecastAuthority": forecast,
        "policy": policy,
        "decisionAsOf": manifest.get("decisionAsOf"),
        "markets": markets,
        "artifactSemanticFingerprints": {
            name: artifacts[name]["semanticFingerprint"] for name in ARTIFACT_SCHEMAS
        },
        "acceptanceSemanticFingerprint": recorded_acceptance.get(
            "semanticFingerprint"
        ),
    }
    expected_run_id = "ir_" + hashlib.sha256(
        json.dumps(run_seed, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    _require(
        manifest.get("inventoryRunId") == expected_run_id,
        "inventoryRunId does not match semantic run inputs",
    )
    return VerifiedInventoryRun(
        root=root,
        manifest=manifest,
        artifact_paths=artifact_paths,
    )


__all__ = [
    "VERIFIER_POLICY_ID",
    "InventoryVerificationError",
    "VerifiedInventoryRun",
    "verify_inventory_run",
]
