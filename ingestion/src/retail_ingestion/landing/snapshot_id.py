"""Ingestion-owned source snapshot identity (plan §2.10)."""

from __future__ import annotations

from typing import Any, Final, Iterable, Mapping

from retail_contracts.fingerprint import semantic_fingerprint


class SnapshotIdentityError(ValueError):
    """The source object inventory cannot establish a safe identity."""


#: An object declaring this cannot contribute to a byte-level identity.
#:
#: The generator marks each object's ``contentDeterminism`` as ``byte`` or ``logical``.
#: Exactly one object declares ``logical``: ``source-run.duckdb``, the restricted
#: browsing mirror that ``capabilities.duckdbRole`` describes as "non-authoritative
#: mirror of generated source objects" and that ordinary ingestion never reads.
#:
#: Including it made the snapshot identity irreproducible. Two independent generations
#: of the same pinned scenario, same seed, same execution profile, produced 508
#: byte-identical Parquet objects and one DuckDB file differing in both size and hash
#: (116,142,080 vs 117,977,088 bytes) -- so the identity of the authoritative data
#: moved because a convenience mirror was rebuilt. Excluding it, the derived id
#: reproduced exactly across both runs.
#:
#: Restricted objects are NOT excluded. 245 of them in the ten-year demo declare
#: ``byte`` determinism and are real generated content that happens to sit in the
#: hidden-truth lane; dropping them would weaken the identity rather than stabilise it.
#: The discriminator is byte-stability, which the producer declares, not permission.
NON_BYTE_DETERMINISTIC: Final[str] = "logical"


def source_snapshot_id(
    *,
    source_instance: str,
    extract_boundary: str,
    objects: Iterable[Mapping[str, Any]],
) -> str:
    """Hash source identity, extract boundary and ordered content inventory.

    Native snapshot/run IDs are deliberately absent. They are retained separately
    and checked for corrupt reuse, but never replace the ingestion-owned identity.

    Objects that declare themselves non-byte-deterministic are excluded, so an
    identity over byte hashes is not defeated by an artifact whose producer has already
    said its bytes may vary. See decision #89.
    """

    if (
        not isinstance(source_instance, str)
        or not source_instance
        or not isinstance(extract_boundary, str)
        or not extract_boundary
    ):
        raise SnapshotIdentityError(
            "source_instance and extract_boundary must be non-empty"
        )
    inventory: list[dict[str, Any]] = []
    seen_object_paths: set[str] = set()
    excluded: list[str] = []
    for row in objects:
        if str(row.get("contentDeterminism", "byte")) == NON_BYTE_DETERMINISTIC:
            excluded.append(str(row.get("path", row.get("logicalPath", "<unnamed>"))))
            continue
        object_path = row.get("path", row.get("logicalPath"))
        logical_path = row.get("logicalPath", object_path)
        byte_count = row.get("bytes")
        sha256 = row.get("sha256")
        if not isinstance(object_path, str) or not object_path:
            raise SnapshotIdentityError("every object requires path or logicalPath")
        if not isinstance(logical_path, str) or not logical_path:
            raise SnapshotIdentityError("every object requires logicalPath")
        if object_path in seen_object_paths:
            raise SnapshotIdentityError(
                f"duplicate object path in source inventory: {object_path}"
            )
        seen_object_paths.add(object_path)
        if isinstance(byte_count, bool) or not isinstance(byte_count, int) or byte_count < 0:
            raise SnapshotIdentityError(
                f"{object_path}: bytes must be a non-negative integer"
            )
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise SnapshotIdentityError(
                f"{object_path}: sha256 must be 64 lowercase hexadecimal characters"
            )
        inventory.append(
            {
                "object_path": object_path,
                "logical_path": logical_path,
                "bytes": byte_count,
                "sha256": sha256,
            }
        )
    if not inventory:
        raise SnapshotIdentityError(
            "source inventory cannot be empty"
            + (
                f" (every object declared {NON_BYTE_DETERMINISTIC} determinism: "
                f"{', '.join(sorted(excluded))})"
                if excluded
                else ""
            )
        )
    inventory.sort(key=lambda row: row["object_path"])
    payload = {
        "source_instance": source_instance,
        "extract_boundary": extract_boundary,
        "objects": inventory,
    }
    return semantic_fingerprint(payload, volatile_pointers=())


__all__ = [
    "NON_BYTE_DETERMINISTIC",
    "SnapshotIdentityError",
    "source_snapshot_id",
]
