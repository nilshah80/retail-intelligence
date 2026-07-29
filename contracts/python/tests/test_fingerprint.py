"""Shared semantic-fingerprint contract (decision #16)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from retail_contracts.fingerprint import (
    DECISION_16_RECORDED,
    DEFAULT_VOLATILE_POINTERS,
    FINGERPRINT_SPEC_VERSION,
    MAX_SAFE_INTEGER,
    VOLATILE_KEYS_VERSION,
    FingerprintContractError,
    NonCanonicalPayloadError,
    assert_fingerprintable,
    canonical_decimal_string,
    canonical_json_bytes,
    semantic_fingerprint,
    strip_volatile_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
VECTOR_PATH = REPO_ROOT / "contracts" / "fingerprints" / "vectors" / "v1.json"
VOLATILE_PATH = (
    REPO_ROOT / "contracts" / "fingerprints" / "volatile-pointers.v1.json"
)


def test_decision_16_is_recorded_and_language_neutral_artifacts_match_code() -> None:
    assert DECISION_16_RECORDED is True
    vectors = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    volatile = json.loads(VOLATILE_PATH.read_text(encoding="utf-8"))
    assert vectors["specVersion"] == FINGERPRINT_SPEC_VERSION
    assert vectors["volatilePathVersion"] == VOLATILE_KEYS_VERSION
    assert volatile["version"] == VOLATILE_KEYS_VERSION
    assert tuple(volatile["pointers"]) == DEFAULT_VOLATILE_POINTERS


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("83.000000000000000000", "83"),
        ("0.1250", "0.125"),
        ("-0.00", "0"),
        (Decimal("1200.5000"), "1200.5"),
        (MAX_SAFE_INTEGER + 1, "9007199254740992"),
    ],
)
def test_decimal_text_has_one_canonical_form(source, expected: str) -> None:
    assert canonical_decimal_string(source) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "not-a-number"])
def test_invalid_decimal_text_fails(value) -> None:
    with pytest.raises(NonCanonicalPayloadError):
        canonical_decimal_string(value)


class TestPayloadDomain:
    def test_accepts_only_real_json_container_types(self) -> None:
        assert_fingerprintable(
            {"objects": [{"rows": 1}, {"rows": 2}], "ok": True, "note": None}
        )
        for value in ((1, 2), b"abc", bytearray(b"abc"), {1, 2}):
            with pytest.raises(NonCanonicalPayloadError):
                assert_fingerprintable(value)

    def test_rejects_binary_float_decimal_and_unsafe_integer(self) -> None:
        for value in (0.1, Decimal("0.1"), MAX_SAFE_INTEGER + 1):
            with pytest.raises(NonCanonicalPayloadError):
                assert_fingerprintable({"value": value})

    def test_rejects_non_string_keys_and_unpaired_surrogate(self) -> None:
        with pytest.raises(NonCanonicalPayloadError, match="non-string key"):
            assert_fingerprintable({1: "one"})
        with pytest.raises(NonCanonicalPayloadError, match="surrogate"):
            assert_fingerprintable({"bad": "\ud800"})


class TestVolatilePointers:
    def test_path_matching_is_exact_not_recursive_by_name(self) -> None:
        source = {
            "executionTelemetry": {"elapsed": "1"},
            "nested": {"executionTelemetry": "business-value"},
        }
        assert strip_volatile_paths(source) == {
            "nested": {"executionTelemetry": "business-value"}
        }
        assert "executionTelemetry" in source  # input is not mutated

    def test_missing_pointer_is_an_idempotent_noop(self) -> None:
        payload = {"a": {"b": 1}}
        assert strip_volatile_paths(payload, ("/missing",)) == payload

    def test_array_pointer_fails_closed(self) -> None:
        with pytest.raises(FingerprintContractError, match="array"):
            strip_volatile_paths({"rows": [{"volatile": 1}]}, ("/rows/0/volatile",))

    @pytest.mark.parametrize("pointer", ("", "/", "/bad~2escape"))
    def test_invalid_pointer_fails_closed(self, pointer: str) -> None:
        with pytest.raises(FingerprintContractError):
            strip_volatile_paths({"a": 1}, (pointer,))


def test_every_shared_vector_matches_canonical_bytes_and_sha256() -> None:
    document = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    for vector in document["vectors"]:
        semantic = strip_volatile_paths(vector["payload"])
        assert canonical_json_bytes(semantic).decode("utf-8") == vector["canonical"]
        assert semantic_fingerprint(vector["payload"]) == vector["sha256"]


def test_invalid_shared_vectors_are_rejected() -> None:
    document = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    for vector in document["invalidVectors"]:
        with pytest.raises(NonCanonicalPayloadError):
            semantic_fingerprint(vector["payload"])
