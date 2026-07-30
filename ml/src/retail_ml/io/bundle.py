"""Fail-closed verification for the immutable Phase-3 curated input bundle."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final, Iterable

from retail_contracts.fingerprint import semantic_fingerprint

EXPECTED_PIN_SCHEMA: Final[str] = "retail-ml-expected-pin/v1"
RETENTION_SCHEMA: Final[str] = "retail-ingestion-retained-evidence/v1"
SHA256_LENGTH: Final[int] = 64
GATE_VOLATILE_POINTERS: Final[tuple[str, ...]] = ("/executionProfile",)
PUBLICATION_VOLATILE_POINTERS: Final[tuple[str, ...]] = (
    "/duckdb",
    "/objects",
    "/publishedAt",
    "/executionProfile",
)
RETAINED_EVIDENCE_FILES: Final[tuple[str, ...]] = (
    "gate-a.json",
    "gate-b.json",
    "publication-manifest.json",
)


class BundleVerificationError(RuntimeError):
    """The selected curated input is missing, corrupt, moved, or unaccepted."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleVerificationError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BundleVerificationError(f"cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BundleVerificationError(f"{path} must contain a JSON object")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise BundleVerificationError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BundleVerificationError(message)


def _without_fingerprint(document: dict[str, Any]) -> dict[str, Any]:
    payload = dict(document)
    _require(
        isinstance(payload.pop("semanticFingerprint", None), str),
        "document is missing semanticFingerprint",
    )
    return payload


def _recompute_fingerprint(
    document: dict[str, Any],
    *,
    volatile_pointers: tuple[str, ...],
    label: str,
) -> str:
    try:
        return semantic_fingerprint(
            _without_fingerprint(document),
            volatile_pointers=volatile_pointers,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise BundleVerificationError(
            f"{label} cannot be fingerprinted under semantic-fingerprint/v1: {exc}"
        ) from exc


def _validate_expected_pin(pin: dict[str, Any], path: Path) -> None:
    _require(
        pin.get("schemaVersion") == EXPECTED_PIN_SCHEMA,
        f"{path}: unsupported expected pin schemaVersion",
    )
    _require(_is_sha256(pin.get("sourceSnapshotId")), f"{path}: invalid sourceSnapshotId")
    for gate_name in ("gateA", "gateB"):
        gate = pin.get(gate_name)
        _require(isinstance(gate, dict), f"{path}: {gate_name} is required")
        _require(gate.get("status") == "pass", f"{path}: {gate_name}.status must be pass")
        for field in ("semanticFingerprint", "evidenceSha256"):
            _require(_is_sha256(gate.get(field)), f"{path}: invalid {gate_name}.{field}")
    publication = pin.get("publication")
    _require(isinstance(publication, dict), f"{path}: publication is required")
    for field in (
        "semanticFingerprint",
        "gateBSemanticFingerprint",
        "evidenceSha256",
    ):
        _require(_is_sha256(publication.get(field)), f"{path}: invalid publication.{field}")
    _require(
        isinstance(publication.get("objectCount"), int)
        and not isinstance(publication.get("objectCount"), bool)
        and publication["objectCount"] > 0,
        f"{path}: publication.objectCount must be positive",
    )
    duckdb = publication.get("duckdb")
    _require(isinstance(duckdb, dict), f"{path}: publication.duckdb is required")
    _require(
        isinstance(duckdb.get("path"), str) and bool(duckdb["path"]),
        f"{path}: publication.duckdb.path is required",
    )
    _require(
        isinstance(duckdb.get("bytes"), int)
        and not isinstance(duckdb.get("bytes"), bool)
        and duckdb["bytes"] > 0,
        f"{path}: publication.duckdb.bytes must be positive",
    )
    _require(_is_sha256(duckdb.get("sha256")), f"{path}: invalid publication.duckdb.sha256")
    retention = pin.get("retention")
    _require(isinstance(retention, dict), f"{path}: retention is required")
    _require(
        retention.get("schemaVersion") == RETENTION_SCHEMA,
        f"{path}: unsupported retention schemaVersion",
    )
    _require(
        _is_sha256(retention.get("publicationFingerprint")),
        f"{path}: invalid retention.publicationFingerprint",
    )
    retained_files = retention.get("files")
    _require(isinstance(retained_files, dict), f"{path}: retention.files is required")
    _require(
        set(retained_files) == set(RETAINED_EVIDENCE_FILES),
        f"{path}: retention.files must name exactly {RETAINED_EVIDENCE_FILES}",
    )
    for name, value in retained_files.items():
        _require(_is_sha256(value), f"{path}: invalid retention hash for {name}")
    capabilities = pin.get("requiredCapabilities")
    _require(
        isinstance(capabilities, list)
        and capabilities
        and all(isinstance(value, str) and value for value in capabilities)
        and len(capabilities) == len(set(capabilities)),
        f"{path}: requiredCapabilities must be a non-empty unique string list",
    )
    _require(
        "demand_forecast_non_pit" in capabilities,
        f"{path}: demand_forecast_non_pit must be required",
    )


def _single_match(paths: Iterable[Path], *, label: str) -> Path:
    matches = tuple(paths)
    if not matches:
        raise BundleVerificationError(f"no {label} matches the committed expected pin")
    if len(matches) > 1:
        rendered = ", ".join(str(path) for path in matches)
        raise BundleVerificationError(f"ambiguous {label}; matching paths: {rendered}")
    return matches[0]


@dataclass(frozen=True)
class InputBundlePaths:
    """Physical bundle paths selected by content identity, not folder name."""

    gate_a_report: Path
    gate_b_report: Path
    evidence_publication_manifest: Path
    retention_manifest: Path
    curated_publication_manifest: Path
    curated_root: Path

    def resolved(self) -> "InputBundlePaths":
        return InputBundlePaths(
            gate_a_report=self.gate_a_report.resolve(),
            gate_b_report=self.gate_b_report.resolve(),
            evidence_publication_manifest=self.evidence_publication_manifest.resolve(),
            retention_manifest=self.retention_manifest.resolve(),
            curated_publication_manifest=self.curated_publication_manifest.resolve(),
            curated_root=self.curated_root.resolve(),
        )


@dataclass(frozen=True)
class VerifiedInputBundle:
    """Identity and paths released only after every verification check passes."""

    paths: InputBundlePaths
    source_snapshot_id: str
    gate_a_semantic_fingerprint: str
    gate_b_semantic_fingerprint: str
    publication_semantic_fingerprint: str
    capability_mask: dict[str, Any]
    publication_manifest: dict[str, Any]

    @property
    def identity(self) -> dict[str, str]:
        return {
            "sourceSnapshotId": self.source_snapshot_id,
            "gateASemanticFingerprint": self.gate_a_semantic_fingerprint,
            "gateBSemanticFingerprint": self.gate_b_semantic_fingerprint,
            "publicationSemanticFingerprint": self.publication_semantic_fingerprint,
        }


@dataclass(frozen=True)
class InputBundle:
    """An untrusted bundle selection that must be verified before data access."""

    paths: InputBundlePaths
    expected_pin_path: Path

    def verify(self) -> VerifiedInputBundle:
        paths = self.paths.resolved()
        pin_path = self.expected_pin_path.resolve()
        pin = _load_json(pin_path)
        _validate_expected_pin(pin, pin_path)

        gate_a = _load_json(paths.gate_a_report)
        gate_b = _load_json(paths.gate_b_report)
        publication = _load_json(paths.evidence_publication_manifest)
        curated_publication = _load_json(paths.curated_publication_manifest)
        retention = _load_json(paths.retention_manifest)

        # Check 1: all evidence belongs to one source snapshot.
        snapshot_ids = {
            gate_a.get("sourceSnapshotId"),
            gate_b.get("sourceSnapshotId"),
            publication.get("sourceSnapshotId"),
            retention.get("sourceSnapshotId"),
        }
        _require(
            len(snapshot_ids) == 1 and None not in snapshot_ids,
            "sourceSnapshotId differs across Gate A, Gate B, publication, and retention",
        )
        source_snapshot_id = next(iter(snapshot_ids))

        # Check 2: the two actual gate reports passed.
        _require(gate_a.get("status") == "pass", "Gate A status is not pass")
        _require(gate_b.get("status") == "pass", "Gate B status is not pass")

        # Check 3: semantic identities are recomputed from content.
        gate_a_fingerprint = _recompute_fingerprint(
            gate_a,
            volatile_pointers=GATE_VOLATILE_POINTERS,
            label="Gate A",
        )
        gate_b_fingerprint = _recompute_fingerprint(
            gate_b,
            volatile_pointers=GATE_VOLATILE_POINTERS,
            label="Gate B",
        )
        publication_fingerprint = _recompute_fingerprint(
            publication,
            volatile_pointers=PUBLICATION_VOLATILE_POINTERS,
            label="publication",
        )
        _require(
            gate_a_fingerprint == gate_a.get("semanticFingerprint"),
            "Gate A semantic fingerprint does not match its content",
        )
        _require(
            gate_b_fingerprint == gate_b.get("semanticFingerprint"),
            "Gate B semantic fingerprint does not match its content",
        )
        _require(
            publication_fingerprint == publication.get("semanticFingerprint"),
            "publication semantic fingerprint does not match its content",
        )

        # Checks 4 and 5: cross-document semantic bindings.
        _require(
            publication.get("gateBSemanticFingerprint") == gate_b_fingerprint,
            "publication is not bound to the verified Gate B report",
        )
        _require(
            retention.get("publicationFingerprint") == publication_fingerprint,
            "retention manifest is not bound to the verified publication",
        )

        # Check 6: physical hashes for the retained evidence JSON files.
        retained_hashes = retention.get("files")
        _require(
            isinstance(retained_hashes, dict)
            and set(retained_hashes) == set(RETAINED_EVIDENCE_FILES),
            "retention manifest does not cover exactly the three required evidence files",
        )
        evidence_paths = {
            "gate-a.json": paths.gate_a_report,
            "gate-b.json": paths.gate_b_report,
            "publication-manifest.json": paths.evidence_publication_manifest,
        }
        actual_evidence_hashes = {
            name: _sha256_file(evidence_paths[name]) for name in RETAINED_EVIDENCE_FILES
        }
        _require(
            actual_evidence_hashes == retained_hashes,
            "retained evidence file hash mismatch",
        )
        _require(
            _sha256_file(paths.curated_publication_manifest)
            == actual_evidence_hashes["publication-manifest.json"],
            "curated publication manifest differs from its retained evidence copy",
        )
        _require(
            curated_publication == publication,
            "curated publication manifest content differs from retained evidence",
        )

        # Check 7: every published object and DuckDB file exists with exact bytes/hash.
        objects = publication.get("objects")
        _require(isinstance(objects, list), "publication objects must be an array")
        for index, entry in enumerate(objects):
            self._verify_physical_object(
                paths.curated_root,
                entry,
                label=f"publication object {index}",
            )
        self._verify_physical_object(
            paths.curated_root,
            publication.get("duckdb"),
            label="publication DuckDB",
        )

        # Check 8: capability declarations stored on Gate B and publication agree.
        gate_b_mask = gate_b.get("capabilityMask")
        publication_mask = publication.get("capabilityMask")
        _require(
            isinstance(gate_b_mask, dict) and gate_b_mask == publication_mask,
            "Gate B and publication capability masks differ",
        )

        # Check 9: every capability required by the committed pin is available.
        for capability in pin["requiredCapabilities"]:
            declaration = gate_b_mask.get(capability)
            _require(
                isinstance(declaration, dict) and declaration.get("available") is True,
                f"required capability {capability!r} is unavailable",
            )

        # Check 10: the verified identity and physical evidence match the committed pin.
        _require(source_snapshot_id == pin["sourceSnapshotId"], "source snapshot moved from pin")
        _require(
            gate_a.get("status") == pin["gateA"]["status"]
            and gate_a_fingerprint == pin["gateA"]["semanticFingerprint"]
            and actual_evidence_hashes["gate-a.json"] == pin["gateA"]["evidenceSha256"],
            "Gate A moved from committed pin",
        )
        _require(
            gate_b.get("status") == pin["gateB"]["status"]
            and gate_b_fingerprint == pin["gateB"]["semanticFingerprint"]
            and actual_evidence_hashes["gate-b.json"] == pin["gateB"]["evidenceSha256"],
            "Gate B moved from committed pin",
        )
        expected_publication = pin["publication"]
        _require(
            publication_fingerprint == expected_publication["semanticFingerprint"]
            and publication.get("gateBSemanticFingerprint")
            == expected_publication["gateBSemanticFingerprint"]
            and actual_evidence_hashes["publication-manifest.json"]
            == expected_publication["evidenceSha256"]
            and len(objects) == expected_publication["objectCount"]
            and publication.get("duckdb") == expected_publication["duckdb"],
            "publication moved from committed pin",
        )
        _require(
            retention.get("schemaVersion") == pin["retention"]["schemaVersion"]
            and retention.get("publicationFingerprint")
            == pin["retention"]["publicationFingerprint"]
            and retained_hashes == pin["retention"]["files"],
            "retained evidence moved from committed pin",
        )

        return VerifiedInputBundle(
            paths=paths,
            source_snapshot_id=source_snapshot_id,
            gate_a_semantic_fingerprint=gate_a_fingerprint,
            gate_b_semantic_fingerprint=gate_b_fingerprint,
            publication_semantic_fingerprint=publication_fingerprint,
            capability_mask=gate_b_mask,
            publication_manifest=publication,
        )

    @staticmethod
    def _verify_physical_object(
        curated_root: Path,
        entry: Any,
        *,
        label: str,
    ) -> None:
        _require(isinstance(entry, dict), f"{label} manifest entry must be an object")
        logical_path = entry.get("path")
        expected_bytes = entry.get("bytes")
        expected_sha = entry.get("sha256")
        _require(
            isinstance(logical_path, str) and logical_path,
            f"{label} path is missing",
        )
        _require(
            isinstance(expected_bytes, int)
            and not isinstance(expected_bytes, bool)
            and expected_bytes >= 0,
            f"{label} bytes is invalid",
        )
        _require(_is_sha256(expected_sha), f"{label} sha256 is invalid")
        pure = PurePosixPath(logical_path)
        _require(
            not pure.is_absolute()
            and "\\" not in logical_path
            and ".." not in pure.parts
            and "." not in pure.parts,
            f"{label} path is not a safe normalized logical path: {logical_path!r}",
        )
        physical = curated_root.joinpath(*pure.parts).resolve()
        _require(
            physical.is_relative_to(curated_root),
            f"{label} escapes the curated root",
        )
        try:
            actual_bytes = physical.stat().st_size
        except OSError as exc:
            raise BundleVerificationError(f"{label} is missing: {physical}: {exc}") from exc
        _require(actual_bytes == expected_bytes, f"{label} byte count mismatch: {logical_path}")
        _require(
            _sha256_file(physical) == expected_sha,
            f"{label} SHA-256 mismatch: {logical_path}",
        )


def _default_expected_pin() -> Path:
    override = os.environ.get("RETAIL_ML_EXPECTED_PIN")
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "contracts" / "ml" / "expected-pin.json"
        if candidate.is_file():
            return candidate
    raise BundleVerificationError(
        "cannot locate contracts/ml/expected-pin.json; pass expected_pin_path explicitly"
    )


def discover_input_bundle(
    repository_root: str | Path,
    *,
    expected_pin_path: str | Path | None = None,
) -> InputBundle:
    """Discover the one evidence/publication pair matching the committed pin."""

    root = Path(repository_root).resolve()
    pin_path = Path(expected_pin_path) if expected_pin_path else _default_expected_pin()
    pin = _load_json(pin_path)
    _validate_expected_pin(pin, pin_path)

    evidence_root = root / "ingestion" / "data" / "evidence"
    retention_candidates: list[Path] = []
    for candidate in sorted(evidence_root.glob("*/retention-manifest.json")):
        document = _load_json(candidate)
        if (
            document.get("sourceSnapshotId") == pin["sourceSnapshotId"]
            and document.get("publicationFingerprint")
            == pin["publication"]["semanticFingerprint"]
        ):
            retention_candidates.append(candidate)
    retention_path = _single_match(retention_candidates, label="retained evidence bundle")
    evidence_dir = retention_path.parent

    curated_root_parent = root / "ingestion" / "data" / "curated"
    curated_candidates: list[Path] = []
    for candidate in sorted(curated_root_parent.glob("*/publication-manifest.json")):
        document = _load_json(candidate)
        if (
            document.get("sourceSnapshotId") == pin["sourceSnapshotId"]
            and document.get("semanticFingerprint")
            == pin["publication"]["semanticFingerprint"]
        ):
            curated_candidates.append(candidate)
    curated_manifest = _single_match(curated_candidates, label="curated publication")

    return InputBundle(
        paths=InputBundlePaths(
            gate_a_report=evidence_dir / "gate-a.json",
            gate_b_report=evidence_dir / "gate-b.json",
            evidence_publication_manifest=evidence_dir / "publication-manifest.json",
            retention_manifest=retention_path,
            curated_publication_manifest=curated_manifest,
            curated_root=curated_manifest.parent,
        ),
        expected_pin_path=pin_path,
    )


__all__ = [
    "BundleVerificationError",
    "GATE_VOLATILE_POINTERS",
    "InputBundle",
    "InputBundlePaths",
    "PUBLICATION_VOLATILE_POINTERS",
    "VerifiedInputBundle",
    "discover_input_bundle",
]
