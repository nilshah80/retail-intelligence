"""Content-derived identities and stable, order-independent source IDs."""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from typing import Any

BC_NAMESPACE = uuid.UUID("00000000-0000-0000-0000-0000513c0001")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def config_hash(config: dict[str, Any]) -> str:
    return sha256_text(canonical_json(config))


def run_id(config: dict[str, Any], generator_version: str) -> str:
    payload = {
        "generatorVersion": generator_version,
        "sourceSpecVersion": config["specVersion"],
        "configHash": config_hash(config),
    }
    return "run-" + sha256_text(canonical_json(payload))[:16]


def stable_integer(*parts: object, modulo: int = 2**63 - 1) -> int:
    raw = "|".join(str(part) for part in parts)
    return int.from_bytes(hashlib.sha256(raw.encode("utf-8")).digest()[:8], "big") % modulo


def rng(master_seed: int, *parts: object) -> random.Random:
    return random.Random(stable_integer(master_seed, *parts))


def shopify_numeric(resource: str, business_key: str) -> int:
    # The earlier 40-bit range has a material birthday-collision probability
    # once a source run publishes around a million lines. Keep the value within
    # a signed 64-bit integer while using roughly 62 bits of hash space.
    return 1_000_000_000_000_000 + stable_integer(
        resource,
        business_key,
        modulo=4_000_000_000_000_000_000,
    )


def shopify_gid(resource: str, business_key: str) -> str:
    return f"gid://shopify/{resource}/{shopify_numeric(resource, business_key)}"


def shopify_order_name(source_sequence: int) -> str:
    """Return a source-wide Shopify-shaped monotonic display name."""

    if source_sequence < 1:
        raise ValueError("source_sequence must be positive")
    return f"#{1000 + source_sequence}"


def bc_uuid(resource: str, business_key: str) -> str:
    return str(uuid.uuid5(BC_NAMESPACE, f"{resource}:{business_key}"))
