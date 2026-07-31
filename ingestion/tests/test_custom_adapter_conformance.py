"""PP3-A5 deliverable A-D6: bounded custom-adapter protocol and conformance.

Proves the extension path exists for semantics mapped files cannot express,
without letting a custom adapter widen its own boundary: it must declare a
manifest, register deterministically, emit standardized roles only, avoid
importing downstream code, and require no Shopify or Business Central copy.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import duckdb
import pytest
import yaml
from jsonschema import Draft202012Validator

from retail_ingestion.adapters import registered_adapters
from retail_ingestion.adapters.registry import register_adapter

from .fixtures.custom_ledger_adapter import MANIFEST, LedgerErpAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCHEMA = REPO_ROOT / "contracts/adapters/adapter-manifest.schema.json"
MAPPED_FILES_SCHEMA = REPO_ROOT / "contracts/adapters/mapped-files.schema.json"
STAGING_V2 = REPO_ROOT / "contracts/staging/staging-v2.yaml"
ADAPTER_DIR = REPO_ROOT / "ingestion/src/retail_ingestion/adapters"


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    schema = json.loads(MANIFEST_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(scope="module")
def roles() -> dict:
    return yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))["roles"]


def test_the_custom_adapter_manifest_validates(
    validator: Draft202012Validator,
) -> None:
    validator.validate(MANIFEST)


def test_a_bounded_custom_adapter_must_justify_itself(
    validator: Draft202012Validator,
) -> None:
    """A custom adapter may not exist just because someone preferred code."""

    without = {k: v for k, v in MANIFEST.items() if k != "customSemantics"}
    assert not validator.is_valid(without)

    thin = dict(MANIFEST)
    thin["justification"] = "because"
    assert not validator.is_valid(thin)


def test_declared_roles_exist_and_declare_resolution(
    roles: dict,
    validator: Draft202012Validator,
) -> None:
    for supplied in MANIFEST["suppliedRoles"]:
        assert supplied["role"] in roles
        assert supplied["providerResolution"] in {
            "exclusive",
            "union",
            "cross_validate",
            "fallback",
        }

    missing_resolution = json.loads(json.dumps(MANIFEST))
    del missing_resolution["suppliedRoles"][0]["providerResolution"]
    assert not validator.is_valid(missing_resolution)


def test_external_loading_cannot_be_declared(
    validator: Draft202012Validator,
) -> None:
    """Decision #69 defers installable packages; no other value validates."""

    assert MANIFEST["loading"] == "static_in_repository_registry"
    for attempt in ("entry_point", "plugin_discovery", "pip_package", "url"):
        candidate = dict(MANIFEST, loading=attempt)
        assert not validator.is_valid(candidate), attempt


def test_duplicate_source_system_registration_fails_closed() -> None:
    class Duplicate(LedgerErpAdapter):
        source_system = "shopify"

    with pytest.raises(RuntimeError, match="already registered"):
        register_adapter(Duplicate)


def test_registering_the_fixture_twice_fails_closed() -> None:
    register_adapter(LedgerErpAdapter)
    try:
        assert "ledgerErp" in registered_adapters()
        with pytest.raises(RuntimeError, match="already registered"):
            register_adapter(LedgerErpAdapter)
    finally:
        from retail_ingestion.adapters import registry

        registry._ADAPTERS.pop("ledgerErp", None)


def test_no_adapter_imports_downstream_code() -> None:
    """An adapter may not import canonical transforms, ML, API or UI."""

    forbidden = ("retail_ingestion.transforms", "retail_ml", "api.", "ui.")
    sources = list(ADAPTER_DIR.glob("*.py")) + [
        Path(__file__).parent / "fixtures/custom_ledger_adapter.py"
    ]
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                for banned in forbidden:
                    assert not name.startswith(banned), f"{path.name} imports {name}"


def test_the_custom_adapter_needs_no_shopify_or_bc_copy() -> None:
    """The fixture must not be a copied dialect adapter."""

    fixture = (
        Path(__file__).parent / "fixtures/custom_ledger_adapter.py"
    ).read_text(encoding="utf-8")

    for platform in ("shopify", "business_central", "businessCentral", "companion"):
        assert platform not in fixture, platform
    # It does reuse shared helpers rather than reimplementing money maths.
    assert "exact_minor_sql" in fixture
    assert "SourceAdapter" in fixture
    assert MANIFEST["customSemantics"]["sharedHelpersUsed"]


def test_the_custom_semantics_are_genuinely_beyond_mapped_files() -> None:
    """The gap must be real: the allowlist has no join or ordering operation."""

    allowlist = set(
        json.loads(MAPPED_FILES_SCHEMA.read_text(encoding="utf-8"))["$defs"][
            "field"
        ]["properties"]["operation"]["enum"]
    )
    for expressive in ("join", "window", "order_by", "row_number", "aggregate"):
        assert expressive not in allowlist

    fixture = (
        Path(__file__).parent / "fixtures/custom_ledger_adapter.py"
    ).read_text(encoding="utf-8")
    assert "row_number() OVER" in fixture
    assert "JOIN" in fixture


def test_the_custom_adapter_reaches_the_same_role(roles: dict) -> None:
    """A genuinely different source reaches `merchandise` with no downstream branch."""

    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_ledger_erp")
    con.execute(
        """
        CREATE VIEW raw_ledger_erp.ledger_headers AS
        SELECT * FROM (VALUES
            ('S-1', '2026-01-06 09:00:00', 'EUR', 'inst-1'),
            ('S-2', '2026-01-06 09:05:00', 'EUR', 'inst-1')
        ) AS t(sale_id, posted_at, currency_code, _source_instance)
        """
    )
    con.execute(
        """
        CREATE VIEW raw_ledger_erp.ledger_lines AS
        SELECT * FROM (VALUES
            -- two revisions of the same line: only the latest posted one counts
            ('S-1','L-1',1,'SKU-1','store-1','2026-01-05',5,'40.00','DRAFT',
             'inst-1','eu-west','hash-1'),
            ('S-1','L-1',2,'SKU-1','store-1','2026-01-05',3,'24.00','POSTED',
             'inst-1','eu-west','hash-1'),
            -- a line whose terminal state is not posted must not become demand
            ('S-2','L-1',1,'SKU-2','store-1','2026-01-05',9,'90.00','CANCELLED',
             'inst-1','eu-west','hash-2')
        ) AS t(sale_id, line_id, revision, sku, shop, business_day, qty,
               net_major, status, _source_instance, _market_id, _raw_object_hash)
        """
    )

    class _Ctx:
        connection = con
        catalog = None
        profile = {
            "sourceSchemaVersion": "ledger-erp/2",
            "profileVersion": "ledger-erp-profile/1",
        }

        @property
        def landing(self):
            return {"sourceSnapshotId": "snap-1"}

    created = LedgerErpAdapter().materialize_staging(_Ctx())
    assert created == ("stage_data.merchandise",)

    rows = con.execute(
        """
        SELECT source_sale_id, source_line_id, units, net_amount_major,
               currency_code, role_id, provider_id, derivation_class
        FROM stage_data.merchandise
        ORDER BY source_sale_id
        """
    ).fetchall()

    # Revision 2 of S-1/L-1 wins; the cancelled S-2 line is absent.
    assert len(rows) == 1
    assert rows[0][0] == "S-1"
    assert int(rows[0][2]) == 3
    assert int(rows[0][3]) == 2400
    assert rows[0][4] == "EUR"
    assert rows[0][5] == "merchandise"
    assert rows[0][7] == "derived"


def test_a_custom_adapter_cannot_bypass_shared_role_validation(
    roles: dict,
) -> None:
    """Emitting a role means satisfying that role's required fields."""

    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_ledger_erp")
    con.execute(
        """
        CREATE VIEW raw_ledger_erp.ledger_headers AS
        SELECT * FROM (VALUES ('S-1','2026-01-06 09:00:00','EUR','inst-1'))
            AS t(sale_id, posted_at, currency_code, _source_instance)
        """
    )
    con.execute(
        """
        CREATE VIEW raw_ledger_erp.ledger_lines AS
        SELECT * FROM (VALUES
            ('S-1','L-1',1,'SKU-1','store-1','2026-01-05',3,'24.00','POSTED',
             'inst-1','eu-west','hash-1')
        ) AS t(sale_id, line_id, revision, sku, shop, business_day, qty,
               net_major, status, _source_instance, _market_id, _raw_object_hash)
        """
    )

    class _Ctx:
        connection = con
        catalog = None
        profile = {
            "sourceSchemaVersion": "ledger-erp/2",
            "profileVersion": "ledger-erp-profile/1",
        }

        @property
        def landing(self):
            return {"sourceSnapshotId": "snap-1"}

    LedgerErpAdapter().materialize_staging(_Ctx())
    emitted = {
        row[0]
        for row in con.execute("DESCRIBE stage_data.merchandise").fetchall()
    }

    required = set(roles["merchandise"]["requiredFields"])
    assert required <= emitted, sorted(required - emitted)

    # Common lineage and provenance fields are equally non-optional.
    contract = yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))
    for field in ("role_id", "provider_id", "known_as_of", "evidence_grade"):
        assert field in contract["commonFields"] or field in emitted
        assert field in emitted, field
    for field in ("evidence_class", "derivation_class"):
        assert field in emitted, field
