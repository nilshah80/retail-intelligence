"""Cross-language semantic fingerprints (decision #16).

The contract is RFC 8785 JSON Canonicalization Scheme followed by SHA-256, with a
smaller admissible JSON domain:

* binary floats and :class:`~decimal.Decimal` objects are forbidden;
* JSON integer numbers are restricted to the interoperable I-JSON/JCS safe range;
* larger integers and every non-integral numeric value are canonical decimal text;
* volatile metadata is removed by versioned **JSON Pointer**, never by recursive
  field-name matching.

The same vectors under ``contracts/fingerprints/vectors`` are consumed by Python
now and by the Go API implementation in W7.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Any, Final

DECISION_16_RECORDED = True
FINGERPRINT_SPEC_VERSION = "semantic-fingerprint/v1"
VOLATILE_KEYS_VERSION = "volatile-pointers/v1"
MAX_SAFE_INTEGER: Final[int] = 9_007_199_254_740_991
MIN_SAFE_INTEGER: Final[int] = -MAX_SAFE_INTEGER

# Mirrored in contracts/fingerprints/volatile-pointers.v1.json. The contract test
# compares them so code and the language-neutral artifact cannot drift.
DEFAULT_VOLATILE_POINTERS: Final[tuple[str, ...]] = (
    "/artifacts",
    "/duckdb_mtime_ns",
    "/duckdb_size",
    "/duration_seconds",
    "/executionProfile",
    "/executionTelemetry",
    "/generated_at_utc",
    "/mtime_ns",
    "/output_dir",
    "/size_bytes",
    "/warehouse_metadata_mtime_ns",
    "/warehouse_metadata_size",
)


class FingerprintContractError(RuntimeError):
    """The canonicalization contract cannot be applied."""


class NonCanonicalPayloadError(TypeError):
    """The payload contains a value outside the cross-language JSON domain."""


def canonical_decimal_string(value: str | int | Decimal) -> str:
    """Return the one permitted plain-text representation of a decimal number.

    No exponent, leading plus, redundant leading/trailing zero, or negative zero
    survives. Callers use this for non-integral numerics and integers outside the
    JCS safe domain before inserting them into a fingerprint payload.
    """

    if isinstance(value, bool) or isinstance(value, float):
        raise NonCanonicalPayloadError(
            "canonical decimal text requires an exact string, int or Decimal"
        )
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise NonCanonicalPayloadError(
            f"{value!r} is not exact decimal text"
        ) from exc
    if not decimal_value.is_finite():
        raise NonCanonicalPayloadError(
            f"canonical decimal text must be finite, got {decimal_value}"
        )
    if decimal_value == 0:
        return "0"
    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered.startswith("-0") and Decimal(rendered) == 0:
        return "0"
    return rendered


def assert_fingerprintable(payload: Any, *, path: str = "$") -> None:
    """Reject values that cannot canonicalize identically in Python and Go."""

    if payload is None or isinstance(payload, bool):
        return
    if isinstance(payload, int):
        if not MIN_SAFE_INTEGER <= payload <= MAX_SAFE_INTEGER:
            raise NonCanonicalPayloadError(
                f"{path} integer {payload} exceeds the RFC 8785 safe domain; "
                "serialize it with canonical_decimal_string"
            )
        return
    if isinstance(payload, str):
        try:
            payload.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise NonCanonicalPayloadError(
                f"{path} contains an unpaired Unicode surrogate"
            ) from exc
        return
    if isinstance(payload, float):
        raise NonCanonicalPayloadError(
            f"{path} is a binary float ({payload!r}); fingerprinted payloads carry "
            "non-integral values as canonical decimal strings"
        )
    if isinstance(payload, Decimal):
        raise NonCanonicalPayloadError(
            f"{path} is a Decimal ({payload!r}); serialize it with "
            "canonical_decimal_string before fingerprinting"
        )
    if isinstance(payload, dict):
        for key, child in payload.items():
            if not isinstance(key, str):
                raise NonCanonicalPayloadError(
                    f"{path} has a non-string key {key!r}; JSON object keys are strings"
                )
            assert_fingerprintable(child, path=f"{path}.{key}")
        return
    if isinstance(payload, list):
        for index, child in enumerate(payload):
            assert_fingerprintable(child, path=f"{path}[{index}]")
        return
    raise NonCanonicalPayloadError(
        f"{path} is {type(payload).__name__}, which has no canonical JSON form"
    )


def _pointer_parts(pointer: str) -> tuple[str, ...]:
    if not pointer.startswith("/") or pointer == "/":
        raise FingerprintContractError(
            f"volatile path {pointer!r} must be a non-root RFC 6901 JSON Pointer"
        )
    parts: list[str] = []
    for raw in pointer[1:].split("/"):
        index = 0
        decoded = ""
        while index < len(raw):
            if raw[index] != "~":
                decoded += raw[index]
                index += 1
                continue
            if index + 1 >= len(raw) or raw[index + 1] not in {"0", "1"}:
                raise FingerprintContractError(
                    f"volatile path {pointer!r} contains invalid JSON Pointer escape"
                )
            decoded += "~" if raw[index + 1] == "0" else "/"
            index += 2
        parts.append(decoded)
    return tuple(parts)


def strip_volatile_paths(
    payload: dict[str, Any],
    pointers: tuple[str, ...] = DEFAULT_VOLATILE_POINTERS,
) -> dict[str, Any]:
    """Copy ``payload`` and remove exact mapping paths.

    Array-index paths are deliberately unsupported: deleting one element changes
    every later index and is too fragile for a versioned identity contract.
    Missing paths are idempotent no-ops.
    """

    def clone(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clone(child) for key, child in value.items()}
        if isinstance(value, list):
            return [clone(child) for child in value]
        return value

    result = clone(payload)
    for pointer in pointers:
        parts = _pointer_parts(pointer)
        parent: Any = result
        for part in parts[:-1]:
            if isinstance(parent, list):
                raise FingerprintContractError(
                    f"volatile path {pointer!r} traverses an array"
                )
            if not isinstance(parent, dict) or part not in parent:
                parent = None
                break
            parent = parent[part]
        if parent is None:
            continue
        if isinstance(parent, list):
            raise FingerprintContractError(
                f"volatile path {pointer!r} targets an array element"
            )
        if isinstance(parent, dict):
            parent.pop(parts[-1], None)
    return result


def canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    """Return RFC 8785 bytes for an already-semantic payload."""

    assert_fingerprintable(payload)
    try:
        import rfc8785
    except ModuleNotFoundError as exc:  # pragma: no cover - packaging check owns it
        raise FingerprintContractError(
            "rfc8785 is required by semantic-fingerprint/v1"
        ) from exc
    try:
        return rfc8785.dumps(payload)
    except (TypeError, ValueError) as exc:
        raise NonCanonicalPayloadError(
            f"payload cannot be canonicalized under RFC 8785: {exc}"
        ) from exc


def semantic_fingerprint(
    payload: dict[str, Any],
    *,
    volatile_pointers: tuple[str, ...] = DEFAULT_VOLATILE_POINTERS,
) -> str:
    """Strip versioned volatile paths, canonicalize, and return lowercase SHA-256."""

    semantic = strip_volatile_paths(payload, volatile_pointers)
    return hashlib.sha256(canonical_json_bytes(semantic)).hexdigest()


__all__ = [
    "DECISION_16_RECORDED",
    "DEFAULT_VOLATILE_POINTERS",
    "FINGERPRINT_SPEC_VERSION",
    "MAX_SAFE_INTEGER",
    "MIN_SAFE_INTEGER",
    "VOLATILE_KEYS_VERSION",
    "FingerprintContractError",
    "NonCanonicalPayloadError",
    "assert_fingerprintable",
    "canonical_decimal_string",
    "canonical_json_bytes",
    "semantic_fingerprint",
    "strip_volatile_paths",
]
