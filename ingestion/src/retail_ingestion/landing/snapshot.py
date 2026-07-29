"""Hash-verified immutable landing with physically separate permission lanes."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import duckdb
from retail_contracts.fingerprint import semantic_fingerprint
from retail_ingestion.profiles import load_source_profile

from .snapshot_id import SnapshotIdentityError, source_snapshot_id

LANDING_MANIFEST_VERSION = "retail-ingestion-landing/v1"
CHUNK_BYTES = 1024 * 1024
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"|?*')


class LandingError(RuntimeError):
    """The source snapshot cannot be landed without violating the contract."""


@dataclass(frozen=True)
class LandingResult:
    source_snapshot_id: str
    native_snapshot_id: str | None
    snapshot_root: Path
    landing_manifest: Path
    object_count: int
    public_object_count: int
    restricted_truth_object_count: int
    restricted_mirror_object_count: int
    idempotent_replay: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": LANDING_MANIFEST_VERSION,
            "sourceSnapshotId": self.source_snapshot_id,
            "nativeSnapshotId": self.native_snapshot_id,
            "snapshotRoot": str(self.snapshot_root),
            "landingManifest": str(self.landing_manifest),
            "objectCount": self.object_count,
            "publicObjectCount": self.public_object_count,
            "restrictedTruthObjectCount": self.restricted_truth_object_count,
            "restrictedMirrorObjectCount": self.restricted_mirror_object_count,
            "idempotentReplay": self.idempotent_replay,
        }


def _tabular_rows(path: Path, artifact_format: str) -> int | None:
    if artifact_format not in {"parquet", "csv", "jsonl", "json"}:
        return None
    escaped = str(path).replace("'", "''")
    relation = {
        "parquet": f"read_parquet('{escaped}')",
        "csv": f"read_csv_auto('{escaped}', header=true, all_varchar=true)",
        "jsonl": (
            f"read_json_auto('{escaped}', format='newline_delimited')"
        ),
        "json": f"read_json_auto('{escaped}', format='auto')",
    }[artifact_format]
    connection = duckdb.connect(":memory:")
    try:
        return int(
            connection.execute(f"SELECT count(*) FROM {relation}").fetchone()[0]
        )
    except duckdb.Error as exc:
        raise LandingError(f"cannot count {path}: {exc}") from exc
    finally:
        connection.close()


def _derive_upstream_manifest(
    source_root: Path,
    source_profile: str | Path,
    *,
    source_instance: str | None,
    extract_boundary: str | None,
) -> tuple[bytes, dict[str, Any]]:
    profile = load_source_profile(source_profile)
    declarations = [
        row
        for row in profile["datasets"]
        if row.get("classification") not in {
            "ignored_by_profile",
            "unsupported",
            "restricted_oracle",
        }
    ]
    without_glob = [
        str(row["datasetId"]) for row in declarations if not row.get("pathGlob")
    ]
    if without_glob:
        raise LandingError(
            "manifest-less landing requires pathGlob for every included dataset; "
            f"missing on {without_glob[:20]}"
        )
    objects: list[dict[str, Any]] = []
    matched_paths: set[Path] = set()
    for declaration in declarations:
        matches = sorted(
            path
            for path in source_root.glob(str(declaration["pathGlob"]))
            if path.is_file()
        )
        if declaration.get("expected", True) and not matches:
            raise LandingError(
                f"{declaration['datasetId']}: pathGlob matched no source files"
            )
        for path in matches:
            resolved = path.resolve()
            if resolved in matched_paths:
                raise LandingError(
                    f"{path}: matched by more than one dataset pathGlob"
                )
            matched_paths.add(resolved)
            relative = path.relative_to(source_root).as_posix()
            raw_hash = hashlib.sha256()
            byte_count = 0
            with path.open("rb") as reader:
                while chunk := reader.read(CHUNK_BYTES):
                    raw_hash.update(chunk)
                    byte_count += len(chunk)
            lane = declaration["permissionLane"]
            objects.append(
                {
                    "path": relative,
                    "logicalPath": relative,
                    "bytes": byte_count,
                    "sha256": raw_hash.hexdigest(),
                    "rows": _tabular_rows(path, declaration["format"]),
                    "format": declaration["format"],
                    "compression": declaration.get("compression", "unknown"),
                    "sourceSystem": declaration.get(
                        "sourceSystem", profile["sourceSystem"]
                    ),
                    "dataset": declaration["datasetId"],
                    "restricted": lane != "public",
                }
            )
    unclassified = sorted(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file() and path.resolve() not in matched_paths
    )
    if unclassified:
        raise LandingError(
            "manifest-less source contains files not classified by pathGlob: "
            f"{unclassified[:20]}"
        )
    window = profile.get("extractWindow", {})
    manifest = {
        "manifestVersion": "retail-ingestion-derived-source-manifest/v1",
        "runId": None,
        "scenarioId": profile["profileId"],
        "logicalStartDate": window.get("start"),
        "logicalEndDate": extract_boundary or window.get("end"),
        "sourceSpecVersion": profile["sourceSchemaVersion"],
        "sourceInstance": source_instance or profile["profileId"],
        "objects": objects,
        "controlsByCurrency": {},
        "manifestDerivation": {
            "method": "profile_path_glob_and_content_scan",
            "profileId": profile["profileId"],
            "profileVersion": profile["profileVersion"],
        },
    }
    raw = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return raw, manifest


def _read_upstream_manifest(
    source_root: Path,
    source_profile: str | Path | None,
    *,
    source_instance: str | None,
    extract_boundary: str | None,
) -> tuple[bytes, dict[str, Any], str]:
    path = source_root / "source-run-manifest.json"
    if not path.is_file():
        if source_profile is None:
            raise LandingError(
                "source-run-manifest.json is absent; --source-profile is required "
                "to derive immutable landing evidence"
            )
        raw, value = _derive_upstream_manifest(
            source_root,
            source_profile,
            source_instance=source_instance,
            extract_boundary=extract_boundary,
        )
        return raw, value, "ingestion_derived"
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise LandingError(f"cannot read upstream manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("objects"), list):
        raise LandingError("upstream manifest must be an object with an objects array")
    return raw, value, "source_provided"


def _safe_logical_path(value: Any) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
    ):
        raise LandingError(f"unsafe logical path {value!r}")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise LandingError(f"unsafe logical path {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute():
        raise LandingError(f"unsafe logical path {value!r}")
    for part in path.parts:
        stem = part.split(".", 1)[0].upper()
        if (
            any(character in WINDOWS_FORBIDDEN_CHARACTERS for character in part)
            or part.endswith((" ", "."))
            or stem in WINDOWS_RESERVED_NAMES
            or any(ord(character) < 32 for character in part)
        ):
            raise LandingError(
                f"logical path is not portable to Windows: {value!r}"
            )
    return path


def _permission_lane(row: Mapping[str, Any], logical_path: PurePosixPath) -> str:
    restricted = row.get("restricted")
    if restricted is False:
        if logical_path.parts[0] == "_truth" or row.get("sourceSystem") == "hiddenTruth":
            raise LandingError(
                f"{logical_path}: truth-like object cannot enter the public lane"
            )
        return "public"
    if restricted is not True:
        raise LandingError(f"{logical_path}: restricted must be an explicit boolean")
    if row.get("format") == "duckdb":
        if logical_path.parts[-1] != "source-run.duckdb":
            raise LandingError(
                f"{logical_path}: restricted DuckDB is not the declared all-source mirror"
            )
        return "restricted_mirror"
    if logical_path.parts[0] == "_truth":
        return "restricted_truth"
    raise LandingError(
        f"{logical_path}: restricted object is neither _truth nor the all-source mirror"
    )


def _source_path(source_root: Path, logical_path: PurePosixPath) -> Path:
    candidate = source_root.joinpath(*logical_path.parts).resolve()
    try:
        candidate.relative_to(source_root)
    except ValueError as exc:
        raise LandingError(f"{logical_path}: object escapes source root") from exc
    if not candidate.is_file():
        raise LandingError(f"{logical_path}: source object is missing")
    return candidate


def _copy_verified(
    source: Path,
    destination: Path,
    *,
    expected_bytes: int,
    expected_sha256: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    byte_count = 0
    with source.open("rb") as reader, destination.open("xb") as writer:
        while chunk := reader.read(CHUNK_BYTES):
            writer.write(chunk)
            digest.update(chunk)
            byte_count += len(chunk)
    if byte_count != expected_bytes or digest.hexdigest() != expected_sha256:
        destination.unlink(missing_ok=True)
        raise LandingError(
            f"{source}: byte/hash mismatch; expected "
            f"{expected_bytes}/{expected_sha256}, got {byte_count}/{digest.hexdigest()}"
        )
    destination.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)


def _make_writable_and_retry(function, value: str, _error: BaseException) -> None:
    """Restore usable owner permissions before retrying a failed removal."""

    current_mode = os.stat(value, follow_symlinks=False).st_mode
    owner_mode = stat.S_IRUSR | stat.S_IWUSR
    if stat.S_ISDIR(current_mode):
        owner_mode |= stat.S_IXUSR
    os.chmod(value, owner_mode)
    function(value)


def _remove_staging_tree(path: Path) -> None:
    """Remove failed partial work, including Windows read-only files."""

    shutil.rmtree(path, onexc=_make_writable_and_retry)


def _existing_native_snapshot(
    snapshots_root: Path, native_snapshot_id: str | None
) -> tuple[str, Path] | None:
    if native_snapshot_id is None or not snapshots_root.is_dir():
        return None
    for manifest_path in snapshots_root.glob("*/landing-manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LandingError(
                f"existing landing manifest is unreadable: {manifest_path}"
            ) from exc
        if manifest.get("nativeSnapshotId") == native_snapshot_id:
            return str(manifest.get("sourceSnapshotId")), manifest_path
    return None


def _result_from_manifest(
    snapshot_root: Path,
    manifest: Mapping[str, Any],
    *,
    idempotent: bool,
) -> LandingResult:
    counts = manifest["permissionLaneCounts"]
    return LandingResult(
        source_snapshot_id=manifest["sourceSnapshotId"],
        native_snapshot_id=manifest.get("nativeSnapshotId"),
        snapshot_root=snapshot_root,
        landing_manifest=snapshot_root / "landing-manifest.json",
        object_count=len(manifest["objects"]),
        public_object_count=counts["public"],
        restricted_truth_object_count=counts["restricted_truth"],
        restricted_mirror_object_count=counts["restricted_mirror"],
        idempotent_replay=idempotent,
    )


def land_source_snapshot(
    source_root: str | Path,
    landing_root: str | Path,
    *,
    source_instance: str | None = None,
    extract_boundary: str | None = None,
    source_profile: str | Path | None = None,
    execution_profile: Mapping[str, Any] | None = None,
) -> LandingResult:
    """Copy one complete source run into an immutable three-lane snapshot."""

    source = Path(source_root).expanduser().resolve()
    destination = Path(landing_root).expanduser().resolve()
    if not source.is_dir():
        raise LandingError(f"source root does not exist: {source}")
    raw_manifest, upstream, manifest_origin = _read_upstream_manifest(
        source,
        source_profile,
        source_instance=source_instance,
        extract_boundary=extract_boundary,
    )
    retailer = upstream.get("retailer")
    retailer_id = retailer.get("retailerId") if isinstance(retailer, dict) else None
    resolved_source_instance = source_instance or ":".join(
        value
        for value in (retailer_id, upstream.get("scenarioId"))
        if isinstance(value, str) and value
    )
    resolved_extract_boundary = extract_boundary or upstream.get("logicalEndDate")
    try:
        snapshot_id = source_snapshot_id(
            source_instance=resolved_source_instance,
            extract_boundary=resolved_extract_boundary,
            objects=upstream["objects"],
        )
    except (SnapshotIdentityError, TypeError) as exc:
        raise LandingError(f"cannot derive source snapshot identity: {exc}") from exc

    native_snapshot_id = upstream.get("runId")
    if native_snapshot_id is not None and not isinstance(native_snapshot_id, str):
        raise LandingError("upstream runId/native snapshot ID must be a string")
    snapshots_root = destination / "snapshots"
    final_root = snapshots_root / snapshot_id
    manifest_path = final_root / "landing-manifest.json"
    upstream_sha256 = hashlib.sha256(raw_manifest).hexdigest()

    if final_root.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise LandingError(
                f"snapshot exists without a readable landing manifest: {final_root}"
            ) from exc
        if (
            existing.get("sourceSnapshotId") != snapshot_id
            or existing.get("upstreamManifest", {}).get("sha256")
            != upstream_sha256
        ):
            raise LandingError(
                "source_snapshot_id collision: existing snapshot has different evidence"
            )
        return _result_from_manifest(final_root, existing, idempotent=True)

    native_existing = _existing_native_snapshot(snapshots_root, native_snapshot_id)
    if native_existing is not None and native_existing[0] != snapshot_id:
        raise LandingError(
            f"native snapshot ID {native_snapshot_id!r} was reused for a different "
            f"ingestion-owned source_snapshot_id; prior evidence: {native_existing[1]}"
        )

    stage_root = destination / f".{snapshot_id}.staging-{uuid.uuid4().hex}"
    lane_counts = {
        "public": 0,
        "restricted_truth": 0,
        "restricted_mirror": 0,
    }
    landed_objects: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    try:
        stage_root.mkdir(parents=True)
        for row in sorted(
            upstream["objects"],
            key=lambda value: value.get("path", value.get("logicalPath", "")),
        ):
            object_path = _safe_logical_path(
                row.get("path", row.get("logicalPath"))
            )
            logical_path = _safe_logical_path(
                row.get("logicalPath", row.get("path"))
            )
            object_path_text = object_path.as_posix()
            if object_path_text in seen_paths:
                raise LandingError(f"duplicate object path: {object_path_text}")
            seen_paths.add(object_path_text)
            lane = _permission_lane(row, object_path)
            lane_counts[lane] += 1
            byte_count = row.get("bytes")
            sha256 = row.get("sha256")
            if (
                isinstance(byte_count, bool)
                or not isinstance(byte_count, int)
                or byte_count < 0
                or not isinstance(sha256, str)
            ):
                raise LandingError(
                    f"{object_path_text}: invalid bytes/sha256 evidence"
                )
            source_path = _source_path(source, object_path)
            landed_relative = Path(lane).joinpath(*object_path.parts)
            _copy_verified(
                source_path,
                stage_root / landed_relative,
                expected_bytes=byte_count,
                expected_sha256=sha256,
            )
            landed_objects.append(
                {
                    "objectPath": object_path_text,
                    "logicalPath": logical_path.as_posix(),
                    "landedPath": landed_relative.as_posix(),
                    "bytes": byte_count,
                    "sha256": sha256,
                    "rows": row.get("rows"),
                    "format": row.get("format"),
                    "compression": row.get("compression"),
                    "sourceSystem": row.get("sourceSystem"),
                    "dataset": row.get("dataset"),
                    "permissionLane": lane,
                }
            )

        upstream_copy = (
            stage_root / "public" / "upstream" / "source-run-manifest.json"
        )
        upstream_copy.parent.mkdir(parents=True, exist_ok=True)
        upstream_copy.write_bytes(raw_manifest)
        upstream_copy.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        landing_time = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        landing_manifest = {
            "schemaVersion": LANDING_MANIFEST_VERSION,
            "ingestRunId": f"ingest-{snapshot_id[:16]}",
            "sourceSnapshotId": snapshot_id,
            "nativeSnapshotId": native_snapshot_id,
            "sourceInstance": resolved_source_instance,
            "extractBoundary": resolved_extract_boundary,
            "landingTime": landing_time,
            "upstreamManifest": {
                "path": "public/upstream/source-run-manifest.json",
                "bytes": len(raw_manifest),
                "sha256": upstream_sha256,
                "origin": manifest_origin,
            },
            "permissionLaneCounts": lane_counts,
            "objects": landed_objects,
            "executionProfile": dict(execution_profile or {}),
        }
        landing_manifest["semanticFingerprint"] = semantic_fingerprint(
            landing_manifest,
            volatile_pointers=(
                "/landingTime",
                "/executionProfile",
            ),
        )
        stage_manifest = stage_root / "landing-manifest.json"
        stage_manifest.write_text(
            json.dumps(landing_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        stage_manifest.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
        snapshots_root.mkdir(parents=True, exist_ok=True)
        os.replace(stage_root, final_root)
        return _result_from_manifest(
            final_root, landing_manifest, idempotent=False
        )
    except Exception:
        if stage_root.exists():
            _remove_staging_tree(stage_root)
        raise


__all__ = [
    "LANDING_MANIFEST_VERSION",
    "LandingError",
    "LandingResult",
    "land_source_snapshot",
]
