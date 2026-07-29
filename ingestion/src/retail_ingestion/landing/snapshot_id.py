"""Ingestion-owned source snapshot identity (plan §2.10)."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from retail_contracts.fingerprint import semantic_fingerprint


class SnapshotIdentityError(ValueError):
    """The source object inventory cannot establish a safe identity."""


def source_snapshot_id(
    *,
    source_instance: str,
    extract_boundary: str,
    objects: Iterable[Mapping[str, Any]],
) -> str:
    """Hash source identity, extract boundary and ordered content inventory.

    Native snapshot/run IDs are deliberately absent. They are retained separately
    and checked for corrupt reuse, but never replace the ingestion-owned identity.
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
    for row in objects:
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
        raise SnapshotIdentityError("source inventory cannot be empty")
    inventory.sort(key=lambda row: row["object_path"])
    payload = {
        "source_instance": source_instance,
        "extract_boundary": extract_boundary,
        "objects": inventory,
    }
    return semantic_fingerprint(payload, volatile_pointers=())


__all__ = ["SnapshotIdentityError", "source_snapshot_id"]
