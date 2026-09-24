"""Pure, idempotent presentation-label cleanup for the disposable environment.

This module has no database, filesystem or service side effects. The caller must
apply the same transformation to linked identities and runtime configuration.
Synthetic-data disclosures are preserved while temporary presentation labels
are removed. JSON scalar types and container types remain unchanged.
"""

from __future__ import annotations

import re
from typing import Any


_REPLACEMENTS = (
    ("Castrol India (Synthetic Demo)", "Castrol India"),
    ("Castrol Demo Online", "Castrol Online"),
    ("Castrol Demo Distributor", "Castrol Distributor"),
    ("Castrol demonstration projection", "Castrol presentation projection"),
    ("Castrol disposable demo", "Castrol disposable environment"),
    ("CST-DEMO-", "CST-"),
    ("retailer-demo", "retailer-castrol"),
    ("tenant-demo", "tenant-castrol"),
    ("_local_demo_", "_local_"),
    ("Synthetic demo", "Synthetic"),
    ("synthetic_demo", "synthetic"),
    (" (Demo)", ""),
    ("demoAdaptation", "pocAdaptation"),
)
_OPAQUE_HASH = re.compile(
    r"(?:[0-9a-f]{32,128}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})",
    re.IGNORECASE,
)
_PRESENTATION = re.compile(r"demonstration", re.IGNORECASE)
_TOKEN = re.compile(r"(?<![A-Za-z0-9])demo(?![A-Za-z0-9])", re.IGNORECASE)
_CAMEL = re.compile(r"(?<![A-Za-z0-9])demo(?=[A-Z])|Demo(?=[A-Z]|$)")


def _case_like(source: str, replacement: str) -> str:
    if source.isupper():
        return replacement.upper()
    if source[0].isupper():
        return replacement.capitalize()
    return replacement


def _text(value: str) -> str:
    if _OPAQUE_HASH.fullmatch(value):
        return value
    for original, replacement in _REPLACEMENTS:
        value = value.replace(original, replacement)
    value = _PRESENTATION.sub(lambda match: _case_like(match[0], "presentation"), value)
    value = _CAMEL.sub(lambda match: _case_like(match[0], "poc"), value)
    return _TOKEN.sub(lambda match: _case_like(match[0], "poc"), value)


def cleanup(value: Any) -> Any:
    """Return cleaned JSON-compatible data without mutating the input.

    String keys are cleaned as well as values, including identifiers embedded in
    stringified JSON. A key collision fails explicitly instead of discarding a
    field. Non-container/scalar objects, including numeric values, pass through.
    """
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            cleaned_key = _text(key) if isinstance(key, str) else key
            if cleaned_key in result:
                raise ValueError(f"Presentation cleanup collides on key {cleaned_key!r}")
            result[cleaned_key] = cleanup(item)
        return result
    if isinstance(value, list):
        return [cleanup(item) for item in value]
    if isinstance(value, tuple):
        return tuple(cleanup(item) for item in value)
    return _text(value) if isinstance(value, str) else value


__all__ = ["cleanup"]
