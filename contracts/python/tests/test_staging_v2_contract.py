"""PP3-A2 deliverables A-D2 and A-D3: executable `retail-staging/v2` validators.

These tests keep the frozen role catalog honest: every role declares a complete
descriptor, provenance stays source-neutral, provider resolution is explicit,
the retired envelope cannot come back, and `retail-staging/v1` stays valid until
PP3-A3 proves parity.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
V1 = REPO_ROOT / "contracts/staging/staging.yaml"
V2 = REPO_ROOT / "contracts/staging/staging-v2.yaml"
ROLE_MAP = REPO_ROOT / "contracts/staging/role-map.yaml"

MONEY_SUFFIXES = ("_major", "_minor", "price", "rate", "value")
DESCRIPTIVE_KEYS = {"description", "note", "purpose"}


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def v2() -> dict:
    return _load(V2)


@pytest.fixture(scope="module")
def role_map() -> dict:
    return _load(ROLE_MAP)


def test_v1_remains_valid_until_cutover() -> None:
    v1 = _load(V1)

    assert v1["schemaVersion"] == "retail-staging/v1"
    assert set(v1["envelopes"]) == {
        "merchandise",
        "adjustment",
        "fulfillment",
        "inventory",
        "receipt",
        "dimension_signal",
    }


def test_v2_declares_a_versioned_dual_run_migration(v2: dict) -> None:
    assert v2["schemaVersion"] == "retail-staging/v2"
    assert v2["status"] == "frozen_not_cut_over"
    migration = v2["migration"]

    assert migration["from"] == "retail-staging/v1"
    assert migration["mode"] == "versioned_dual_run"
    assert "dimension_signal" in migration["retiredEnvelopes"]
    assert migration["roleMap"] == "contracts/staging/role-map.yaml"


def test_every_role_carries_a_complete_descriptor(v2: dict) -> None:
    for name, role in sorted(v2["roles"].items()):
        assert role.get("version"), name
        assert role.get("group"), name
        assert role.get("purpose"), name
        assert role.get("grain"), name
        assert role.get("key"), name
        assert role.get("requiredFields"), name
        assert "optionalFields" in role, name
        assert role.get("providerResolution"), name

        modes = set(v2["providerResolution"]["modes"])
        assert role["providerResolution"] in modes, name

        # A declared key field must be a common field or a role field.
        common = set(v2["commonFields"])
        declared = set(role["requiredFields"]) | set(role["optionalFields"] or [])
        for column in role["key"]:
            assert column in common or column in declared or column == "market_id", (
                f"{name} key column {column} is not declared"
            )


def test_money_and_quantity_fields_are_declared_where_present(v2: dict) -> None:
    for name, role in sorted(v2["roles"].items()):
        fields = list(role["requiredFields"]) + list(role["optionalFields"] or [])
        money_like = [f for f in fields if f.endswith("_major")]
        declared_money = set(role.get("money", []) or [])
        assert set(money_like) <= declared_money, (
            f"{name} has undeclared money fields: "
            f"{sorted(set(money_like) - declared_money)}"
        )
        unit_like = [f for f in fields if f.endswith("_units") or f in {"qty", "units"}]
        declared_qty = set(role.get("quantity", []) or [])
        assert set(unit_like) <= declared_qty, (
            f"{name} has undeclared quantity fields: "
            f"{sorted(set(unit_like) - declared_qty)}"
        )


def test_provenance_is_source_neutral_and_closed(v2: dict) -> None:
    provenance = v2["provenance"]

    assert provenance["evidence_class"]["enum"] == ["client", "third_party", "synthetic"]
    assert provenance["derivation_class"]["enum"] == ["native", "derived"]
    assert provenance["supersedes"]["field"] == "row_provenance"

    # Every v1 row_provenance value maps onto the two neutral dimensions.
    v1_enum = set(_load(V1)["commonFields"]["row_provenance"]["enum"])
    assert set(provenance["supersedes"]["mapping"]) == v1_enum
    for value, mapped in provenance["supersedes"]["mapping"].items():
        assert mapped["evidence_class"] in provenance["evidence_class"]["enum"], value
        assert mapped["derivation_class"] in provenance["derivation_class"]["enum"], value

    # No enum value may name a platform or retailer.
    for value in provenance["evidence_class"]["enum"]:
        assert "shopify" not in value.lower()
        assert "bc" != value.lower()


def test_no_role_or_field_names_a_platform(v2: dict) -> None:
    payload = json.dumps(
        {name: role for name, role in v2["roles"].items()},
        sort_keys=True,
    ).lower()
    # Descriptions legitimately mention the migration source; field and role
    # names must not.
    for name, role in sorted(v2["roles"].items()):
        assert "shopify" not in name and "companion" not in name
        for field in list(role["requiredFields"]) + list(role["optionalFields"] or []):
            lowered = field.lower()
            assert "shopify" not in lowered, f"{name}.{field}"
            assert "companion" not in lowered, f"{name}.{field}"
            assert not lowered.startswith("bc_"), f"{name}.{field}"
    assert payload  # keeps the serialization exercised


def test_retired_envelope_cannot_return_as_a_role(v2: dict) -> None:
    assert "dimension_signal" not in v2["roles"]
    retired = v2["migration"]["retiredEnvelopes"]["dimension_signal"]
    assert "no canonical transform" in retired


def test_channel_is_absent_because_it_is_a_canonical_derivation(
    v2: dict,
    role_map: dict,
) -> None:
    assert "channel" not in v2["roles"]
    assert role_map["roleProviderMap"]["channel"]["disposition"] == (
        "derived_in_transform"
    )


def test_role_catalog_matches_the_reviewed_role_map(
    v2: dict,
    role_map: dict,
) -> None:
    mapped = {
        role
        for role, entry in role_map["roleProviderMap"].items()
        if entry.get("disposition") != "derived_in_transform"
    }
    assert set(v2["roles"]) == mapped


def test_temporal_evidence_forbids_business_dates_as_availability(v2: dict) -> None:
    temporal = v2["temporalEvidence"]

    assert "landing_backfill" not in temporal["knownAsOfEligible"]
    assert temporal["downgradesReplayCapability"] == ["landing_backfill"]
    for field in ("business_date", "effective_date", "transaction_date"):
        assert field in temporal["neverProvesAvailability"]

    grades = set(_load(V1)["commonFields"]["evidence_grade"]["enum"])
    assert set(temporal["knownAsOfEligible"]) | set(
        temporal["downgradesReplayCapability"]
    ) == grades


def test_provider_resolution_forbids_implicit_precedence(v2: dict) -> None:
    resolution = v2["providerResolution"]

    assert set(resolution["modes"]) == {
        "exclusive",
        "union",
        "cross_validate",
        "fallback",
    }
    assert resolution["fingerprinted"] is True
    forbidden = " ".join(resolution["forbidden"]).lower()
    assert "first-source-wins" in forbidden
    assert "coalescing" in forbidden


def test_multi_provider_roles_name_an_explicit_owner(v2: dict) -> None:
    disruption = v2["roles"]["market_disruption"]

    assert disruption["providerResolution"] == "exclusive"
    assert len(disruption["providers"]["declared"]) == 2
    assert disruption["providers"]["owner"] == "pandemic_timeline"

    for name, role in sorted(v2["roles"].items()):
        declared = (role.get("providers") or {}).get("declared") or []
        if len(declared) > 1 and role["providerResolution"] == "exclusive":
            assert (role.get("providers") or {}).get("owner"), name


def test_cross_validate_roles_name_their_counterpart(v2: dict) -> None:
    for name, role in sorted(v2["roles"].items()):
        if role["providerResolution"] == "cross_validate":
            target = role.get("crossValidates")
            assert target, name
            assert target in v2["roles"], f"{name} cross-validates unknown {target}"


def test_union_roles_declare_their_partition(v2: dict) -> None:
    for name, role in sorted(v2["roles"].items()):
        if role["providerResolution"] == "union":
            assert role.get("unionPartitionField"), name


def test_adapter_manifest_fails_closed_on_duplicate_ownership(v2: dict) -> None:
    manifest = v2["adapterManifest"]

    for field in (
        "source_system_id",
        "adapter_version",
        "supplied_roles",
        "provider_resolution_compatibility",
    ):
        assert field in manifest["requiredFields"]
    rules = " ".join(manifest["rules"]).lower()
    assert "duplicate source_system_id fails closed" in rules
    assert "may not import canonical transforms" in rules
    assert manifest["loading"] == "static_in_repository_registry"


def test_quarantine_rules_cover_the_common_failure_modes(v2: dict) -> None:
    ids = {rule["id"] for rule in v2["commonQuarantineRules"]}

    assert {
        "MISSING_REQUIRED_FIELD",
        "NULL_IN_KEY",
        "DUPLICATE_ROLE_KEY",
        "MONEY_PRECISION_INVALID",
        "PROVIDER_COLLISION",
    } <= ids


def test_money_contract_is_exact_minor_units(v2: dict) -> None:
    money = v2["moneyContract"]

    assert money["representation"] == "exact_minor_units"
    assert "half_even" in money["rounding"]
    assert "float" in money["rule"]


# ---------------------------------------------------------------------------
# Golden vectors: the fingerprint must be deterministic and must ignore prose.
# ---------------------------------------------------------------------------
def _role_fingerprint(role: dict, rules: dict) -> str:
    payload = {
        key: value
        for key, value in sorted(role.items())
        if key not in DESCRIPTIVE_KEYS
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_role_fingerprints_are_deterministic_and_ignore_prose(v2: dict) -> None:
    rules = v2["fingerprintRules"]["roleContract"]
    assert set(rules["excludes"]) == {"description", "note"}

    for name, role in sorted(v2["roles"].items()):
        first = _role_fingerprint(role, rules)
        second = _role_fingerprint(dict(reversed(list(role.items()))), rules)
        assert first == second, f"{name} fingerprint is order dependent"

        reworded = dict(role)
        reworded["note"] = "editorial change that must not alter identity"
        reworded["purpose"] = "reworded purpose"
        assert _role_fingerprint(reworded, rules) == first, name

        material = dict(role)
        material["key"] = list(role["key"]) + ["injected_column"]
        assert _role_fingerprint(material, rules) != first, name


def test_role_fingerprints_are_unique_across_the_catalog(v2: dict) -> None:
    rules = v2["fingerprintRules"]["roleContract"]
    seen: dict[str, str] = {}
    for name, role in sorted(v2["roles"].items()):
        digest = _role_fingerprint(role, rules)
        assert digest not in seen, f"{name} collides with {seen.get(digest)}"
        seen[digest] = name
