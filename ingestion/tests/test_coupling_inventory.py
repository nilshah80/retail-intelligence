"""PP3-A1 deliverable A-D1: coupling inventory and boundary allowlist.

These tests make the reviewed role map executable. They fail when a current
staging relation gains no role, when a proposed role gains no provider or
disposition, or when a platform identifier appears outside the reviewed
allowlist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLE_MAP = REPO_ROOT / "contracts/staging/role-map.yaml"
BUILDER = REPO_ROOT / "ingestion/src/retail_ingestion/staging/builder.py"
COMPANION = REPO_ROOT / "ingestion/src/retail_ingestion/adapters/companion.py"

# `businessCentral` is camelCase with no underscore, so an earlier
# `\bbc_[a-z_]+` pattern missed it entirely and PP3-A1 under-reported two
# prohibited joins. Dialect names are listed explicitly.
PLATFORM_PATTERN = re.compile(
    r"shopify|companion|businesscentral|\bbc_[a-z_]+",
    re.IGNORECASE,
)
SCANNED_SUFFIXES = (".py", ".sql", ".yaml", ".yml")


@pytest.fixture(scope="module")
def role_map() -> dict:
    return yaml.safe_load(ROLE_MAP.read_text(encoding="utf-8"))


def _neutral_relations() -> set[str]:
    """Return the neutral relations `_create_standardized_views` exposes."""

    source = BUILDER.read_text(encoding="utf-8")
    start = source.index("    direct = {")
    end = source.index("    for target, source in direct.items():")
    direct = set(re.findall(r'"([a-z_]+)": "[a-z_]+"', source[start:end]))

    start = source.index("    statements = {")
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    derived = set(re.findall(r'^        "([a-z_]+)": ', source[start:end], re.M))
    return direct | derived


def _consumed_relations() -> set[str]:
    """Return every `stage_data.*` relation referenced outside the adapters."""

    consumed: set[str] = set()
    for path in (REPO_ROOT / "ingestion/src/retail_ingestion").rglob("*.py"):
        if "adapters" in path.parts:
            continue
        consumed.update(
            re.findall(r"stage_data\.([a-z0-9_]+)", path.read_text(encoding="utf-8"))
        )
    return consumed


def _declared_signal_kinds() -> set[str]:
    source = COMPANION.read_text(encoding="utf-8")
    start = source.index("_SIGNAL") if "_SIGNAL" in source else 0
    return set(re.findall(r'"([a-zA-Z]+)":\s*\(', source[start:]))


def test_every_neutral_relation_has_a_role_or_disposition(role_map: dict) -> None:
    mapped = role_map["relationRoleMap"]
    for relation in sorted(_neutral_relations()):
        assert relation in mapped, f"{relation} has no PP3-A1 mapping"
        entry = mapped[relation]
        assert entry.get("role") or entry.get("disposition"), relation


def test_every_consumed_relation_is_inventoried(role_map: dict) -> None:
    mapped = role_map["relationRoleMap"]
    platform = re.compile(r"^(shopify|bc|companion)_")
    for relation in sorted(_consumed_relations()):
        if platform.match(relation):
            # Platform relations are the coupling PP3-A3 removes; the builder
            # and crosswalk occurrences are tracked as migrationOnly.
            continue
        assert relation in mapped, (
            f"{relation} is consumed but absent from the PP3-A1 inventory"
        )


def test_every_proposed_role_names_a_provider_or_disposition(
    role_map: dict,
) -> None:
    for role, entry in sorted(role_map["roleProviderMap"].items()):
        providers = entry.get("providers")
        assert providers is not None, f"{role} declares no providers key"
        if not providers:
            assert entry.get("disposition"), (
                f"{role} has no provider and no explicit disposition"
            )


def test_channel_stays_a_canonical_transform_not_a_staging_role(
    role_map: dict,
) -> None:
    channel = role_map["roleProviderMap"]["channel"]

    assert channel["providers"] == []
    assert channel["disposition"] == "derived_in_transform"
    assert channel["derivedAt"].endswith("transforms/core.py")
    assert "channel" not in role_map["relationRoleMap"]


def test_allocation_supply_is_typed_rather_than_absent(role_map: dict) -> None:
    supply = role_map["roleProviderMap"]["allocation_supply"]

    assert supply["providers"] == ["companion_allocation_supply_pools"]
    assert supply["exposedAsNeutralRelation"] is False
    assert supply.get("disposition") is None


def test_retired_dimension_signal_has_no_runtime_consumer(role_map: dict) -> None:
    entry = role_map["relationRoleMap"]["dimension_signal"]
    assert entry["disposition"] == "retired_no_consumer"

    consumers = []
    for path in REPO_ROOT.rglob("*.py"):
        if ".venv" in path.parts or "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "stage_data.dimension_signal" in text:
            consumers.append(str(path.relative_to(REPO_ROOT)))
    assert consumers == [], f"dimension_signal gained a consumer: {consumers}"


def test_every_signal_kind_maps_to_a_role(role_map: dict) -> None:
    declared = _declared_signal_kinds()
    mapped = role_map["dimensionSignalKinds"]["kinds"]

    assert declared, "companion adapter declared no signal kinds"
    assert set(mapped) == declared
    roles = set(role_map["roleProviderMap"])
    for kind, entry in sorted(mapped.items()):
        assert entry["role"] in roles, f"{kind} maps to unknown role {entry['role']}"


def test_platform_identifiers_stay_inside_the_reviewed_allowlist(
    role_map: dict,
) -> None:
    allowlist = role_map["boundaryAllowlist"]
    allowed = {entry["path"] for entry in allowlist["allowed"]}
    migration_only = {entry["path"] for entry in allowlist["migrationOnly"]}
    false_positives = {
        entry["path"] for entry in allowlist["documentedFalsePositives"]
    }
    known = {
        entry["path"]
        for entry in allowlist["prohibitedKnownViolations"]["violations"]
    }
    permitted = allowed | migration_only | false_positives | known

    offenders: list[str] = []
    for prefix in allowlist["prohibited"]:
        root = REPO_ROOT / prefix
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SCANNED_SUFFIXES or not path.is_file():
                continue
            if ".venv" in path.parts or "node_modules" in path.parts:
                continue
            relative = str(path.relative_to(REPO_ROOT))
            if any(relative.startswith(entry) for entry in permitted):
                continue
            if PLATFORM_PATTERN.search(path.read_text(encoding="utf-8", errors="ignore")):
                offenders.append(relative)

    assert offenders == [], (
        "platform identifiers appear outside the PP3-A1 allowlist: "
        f"{sorted(offenders)}"
    )


def test_known_transform_violations_do_not_grow(role_map: dict) -> None:
    """Any surviving violation may not multiply before PP3-A3 clears it."""

    register = role_map["boundaryAllowlist"]["prohibitedKnownViolations"]
    for entry in register["violations"]:
        text = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
        actual = len(re.findall(re.escape(entry["pattern"]), text))
        assert actual == entry["occurrences"], (
            f"{entry['path']} now has {actual} occurrences of "
            f"{entry['pattern']!r}, expected {entry['occurrences']}"
        )


def test_cleared_violations_do_not_return(role_map: dict) -> None:
    """A violation PP3-A3 removed must stay removed."""

    cleared = role_map["boundaryAllowlist"]["prohibitedKnownViolations"]["cleared"]
    assert cleared, "the cleared register records what PP3-A3 fixed"
    for entry in cleared:
        text = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
        assert entry["pattern"] not in text, (
            f"{entry['path']} reintroduced {entry['pattern']!r}, cleared by "
            f"{entry['clearedBy']}"
        )
        assert entry.get("remediation"), entry["path"]


def test_crosswalk_resolves_by_key_space_not_source_name() -> None:
    """The neutral predicate PP3-A3 introduced must stay in place."""

    transforms = (
        REPO_ROOT / "ingestion/src/retail_ingestion/transforms/core.py"
    ).read_text(encoding="utf-8")
    crosswalk = (
        REPO_ROOT / "ingestion/src/retail_ingestion/mappings/locations.py"
    ).read_text(encoding="utf-8")

    # Every crosswalk join resolves column-to-column on the minting authority.
    # No consumer names a dialect, and no dialect literal survives anywhere in
    # the prohibited trees.
    for literal in ("'companion'", "'shopify'", "'businessCentral'"):
        assert f"source_system = {literal}" not in transforms, literal
    assert "x.source_system = p.source_system" in transforms
    assert "x.source_system = a.source_system" in transforms

    # The crosswalk is built from the standardized role, and `key_space` labels
    # what each row's key IS rather than who supplied it.
    assert "FROM stage_data.locations" in crosswalk
    assert "FROM stage_data.shopify_locations" not in crosswalk
    assert "key_space VARCHAR NOT NULL" in crosswalk
    assert '"canonical_identity"' in crosswalk
    assert '"source_native"' in crosswalk

    # key_space describes what a crosswalk row's key IS. It must never become a
    # join predicate: one relation can carry keys from both spaces, so filtering
    # on it silently drops resolvable rows.
    assert "x.key_space =" not in transforms
    assert "x.key_space =" not in crosswalk


def test_migration_only_coupling_does_not_grow(role_map: dict) -> None:
    """Freeze today's known coupling so PP3-A3 can only reduce it."""

    expected = {
        entry["path"]: entry["occurrences"]
        for entry in role_map["boundaryAllowlist"]["migrationOnly"]
    }
    for relative, budget in sorted(expected.items()):
        text = (REPO_ROOT / relative).read_text(encoding="utf-8")
        actual = len(re.findall(r"shopify_|bc_|companion_", text))
        assert actual <= budget, (
            f"{relative} platform coupling grew from {budget} to {actual}"
        )
