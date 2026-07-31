"""Declarative source profiles.

Profile filenames are stable. Compatibility is controlled by the
``profileVersion`` and ``sourceSchemaVersion`` fields inside each document.
"""

from .loader import (
    SourceProfileError,
    load_source_profile,
    neutral_relation_roles,
    staging_v2_roles,
)

__all__ = [
    "SourceProfileError",
    "load_source_profile",
    "neutral_relation_roles",
    "staging_v2_roles",
]
