"""Immutable raw landing and snapshot identity."""

from .snapshot import (
    LandingError,
    LandingResult,
    land_source_snapshot,
)

__all__ = ["LandingError", "LandingResult", "land_source_snapshot"]
