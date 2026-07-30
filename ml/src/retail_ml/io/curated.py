"""Read-only curated access released only for a verified input bundle."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import duckdb

from retail_ml.io.bundle import BundleVerificationError, VerifiedInputBundle


class CuratedReader:
    """Resolve only objects declared by a verified publication manifest."""

    def __init__(self, bundle: VerifiedInputBundle) -> None:
        if not isinstance(bundle, VerifiedInputBundle):
            raise BundleVerificationError(
                "curated data cannot be opened before InputBundle.verify() succeeds"
            )
        self._bundle = bundle
        objects = bundle.publication_manifest.get("objects", [])
        self._objects = {
            entry["path"]: entry
            for entry in objects
            if isinstance(entry, dict) and isinstance(entry.get("path"), str)
        }

    @property
    def bundle(self) -> VerifiedInputBundle:
        return self._bundle

    def object_path(self, logical_path: str) -> Path:
        if logical_path not in self._objects:
            raise BundleVerificationError(
                f"{logical_path!r} is not declared by the verified publication"
            )
        pure = PurePosixPath(logical_path)
        return self._bundle.paths.curated_root.joinpath(*pure.parts)

    def entity_parquet_path(self, entity: str) -> Path:
        if not entity or "/" in entity or "\\" in entity or entity in {".", ".."}:
            raise ValueError(f"invalid canonical entity name {entity!r}")
        return self.object_path(f"parquet/{entity}/data.parquet")

    def connect_duckdb(self) -> Any:
        logical_path = self._bundle.publication_manifest["duckdb"]["path"]
        pure = PurePosixPath(logical_path)
        physical = self._bundle.paths.curated_root.joinpath(*pure.parts)
        connection = duckdb.connect(str(physical), read_only=True)
        connection.execute("SET schema = 'canonical_data'")
        return connection


__all__ = ["CuratedReader"]
