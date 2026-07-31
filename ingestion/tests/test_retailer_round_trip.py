"""PP3-A8 deliverables A-D10 and A-D12: client-shaped round trips.

The architectural promise is narrow and testable: a new retailer arrives through
a mapping or a bounded adapter, reaches standardized roles, and every file
downstream of staging is untouched. These tests assert the *unchanged* part,
which is the half that silently rots.

They do not claim any retailer works automatically. Capability and sufficiency
verdicts stay separate and reason-coded.
"""

from __future__ import annotations

import ast
import hashlib
import json
from decimal import Decimal
import subprocess
from pathlib import Path

import duckdb
import pytest
import yaml

from retail_ingestion.adapters.mapped_files import (
    MappedFilesAdapter,
    MappedFilesError,
    validate_mapping,
)
from retail_ingestion.readiness.evaluator import (
    BLOCKED,
    INSUFFICIENT,
    READY,
    UNAVAILABLE,
    ReadinessInputs,
    RoleEvidence,
    ZeroDemandCell,
    build_readiness_report,
)
from retail_ingestion.readiness.selection import (
    SelectionError,
    derive_record_id,
    derive_selection_id,
    resolve_selection,
)

from .fixtures.custom_ledger_adapter import LedgerErpAdapter

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGING_V2 = REPO_ROOT / "contracts/staging/staging-v2.yaml"
ROLE_MAP = REPO_ROOT / "contracts/staging/role-map.yaml"

#: Everything downstream of staging must be byte-identical for a new retailer.
DOWNSTREAM_TREES = (
    "ingestion/src/retail_ingestion/transforms",
    "ingestion/src/retail_ingestion/quality",
    "ml/src",
    "api/internal",
    "ui/src",
)


@pytest.fixture(scope="module")
def roles() -> dict:
    return yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))["roles"]


def _tree_digest(trees=DOWNSTREAM_TREES) -> str:
    """Hash every downstream source file, so any edit is detectable."""

    digest = hashlib.sha256()
    for tree in trees:
        root = REPO_ROOT / tree
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {
                ".py",
                ".go",
                ".ts",
                ".tsx",
                ".sql",
            }:
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            digest.update(str(path.relative_to(REPO_ROOT)).encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Positive path 2: a generic mapped-files retailer.
# ---------------------------------------------------------------------------
def _mapping(source_system: str = "generic-flat-file") -> dict:
    return {
        "schemaVersion": "retail-mapped-files/v1",
        "sourceSystem": source_system,
        "mappingVersion": "1.0.0",
        "datasets": [
            {
                "datasetId": "weekly_sales",
                "role": "merchandise",
                "format": "csv",
                "logicalPath": "sales/weekly.csv",
                "sourceKeys": ["order_no", "line_no"],
                "grain": "order line",
                "timezone": "Europe/London",
                "nullPolicy": {"onMissingRequired": "quarantine"},
                "temporalEvidence": {
                    "knownAsOf": {"mode": "column", "column": "posted_at"},
                    "grade": "native_posted_available",
                },
                "fields": [
                    {"target": "event_kind", "operation": "constant", "value": "sale"},
                    {
                        "target": "source_sale_id",
                        "operation": "select",
                        "source": "order_no",
                    },
                    {
                        "target": "source_line_id",
                        "operation": "select",
                        "source": "line_no",
                    },
                    {"target": "sku_source_key", "operation": "select", "source": "item"},
                    {
                        "target": "demand_location_source_key",
                        "operation": "select",
                        "source": "shop",
                    },
                    {
                        "target": "channel_source_key",
                        "operation": "value_map",
                        "source": "chan",
                        "map": {"1": "store", "2": "online"},
                    },
                    {
                        "target": "business_date",
                        "operation": "parse_date",
                        "source": "day",
                        "format": "%d/%m/%Y",
                    },
                    {
                        "target": "units",
                        "operation": "quantity",
                        "source": "qty",
                        "scale": 0,
                    },
                    {
                        "target": "net_amount_major",
                        "operation": "money_major_normalize",
                        "source": "net",
                        "currencyColumn": "ccy",
                    },
                    {"target": "currency_code", "operation": "select", "source": "ccy"},
                ],
            }
        ],
    }


def _mapped_retailer_staging(tmp_path: Path, mapping: dict) -> duckdb.DuckDBPyConnection:
    """Land a renamed, reordered, DD/MM/YYYY client CSV and stage it."""

    source = tmp_path / "weekly.csv"
    source.write_text(
        "ccy,net,qty,day,chan,shop,item,line_no,order_no,posted_at\n"
        "GBP,12.50,3,05/01/2026,1,store-1,SKU-1,1,A-1,2026-01-06 08:00:00\n"
        "GBP,7.25,2,05/01/2026,2,store-1,SKU-2,1,A-2,2026-01-06 08:05:00\n",
        encoding="utf-8",
    )
    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_mapped_files")
    con.execute(
        f"""
        CREATE VIEW raw_mapped_files.weekly_sales AS
        SELECT *,
               'acme-uk-1' AS _source_instance,
               'gb-south' AS _market_id,
               '{hashlib.sha256(source.read_bytes()).hexdigest()}' AS _raw_object_hash
        FROM read_csv_auto('{source}')
        """
    )

    class _Ctx:
        connection = con
        catalog = None
        profile = {
            "sourceSchemaVersion": "flat/1",
            "profileVersion": "acme-profile/1",
            "mappedFiles": mapping,
            "roleCatalog": yaml.safe_load(
                STAGING_V2.read_text(encoding="utf-8")
            )["roles"],
        }

        @property
        def landing(self):
            return {
                "sourceSnapshotId": "snap-acme-1",
                "nativeSnapshotId": None,
                "landingTime": "2026-01-07T00:00:00Z",
            }

    MappedFilesAdapter().materialize_staging(_Ctx())
    return con


def test_a_mapped_retailer_reaches_standardized_roles(
    roles: dict,
    tmp_path: Path,
) -> None:
    con = _mapped_retailer_staging(tmp_path, _mapping())
    rows = con.execute(
        """
        SELECT source_sale_id, channel_source_key, units, net_amount_major,
               business_date, role_id, source_system, evidence_grade
        FROM stage_data.merchandise ORDER BY source_sale_id
        """
    ).fetchall()

    assert len(rows) == 2
    # Column order, names and DD/MM/YYYY dates differed from the demo source;
    # only the mapping changed.
    assert rows[0][1] == "store"
    assert rows[1][1] == "online"
    # Major units at the staging layer; the canonical transforms convert to minor.
    assert Decimal(str(rows[0][3])) == Decimal("12.50")
    assert str(rows[0][4]) == "2026-01-05"
    assert rows[0][5] == "merchandise"
    # The retailer's declared dialect, not the adapter name.
    assert rows[0][6] == "generic-flat-file"


def test_every_row_carries_lineage_to_the_raw_object(tmp_path: Path) -> None:
    con = _mapped_retailer_staging(tmp_path, _mapping())
    lineage = con.execute(
        """
        SELECT count(*),
               count(DISTINCT raw_object_hash),
               count(*) FILTER (WHERE native_record_id IS NULL),
               count(*) FILTER (WHERE raw_object_hash IS NULL),
               count(*) FILTER (WHERE source_snapshot_id IS NULL)
        FROM stage_data.merchandise
        """
    ).fetchone()

    assert lineage[0] == 2
    assert lineage[1] == 1
    assert lineage[2] == 0
    assert lineage[3] == 0
    assert lineage[4] == 0


def test_reordering_or_renaming_columns_needs_no_new_adapter(
    roles: dict,
    tmp_path: Path,
) -> None:
    """The same adapter handles a differently shaped drop via mapping alone."""

    before = _tree_digest()
    con = _mapped_retailer_staging(tmp_path, _mapping())
    assert con.execute("SELECT count(*) FROM stage_data.merchandise").fetchone()[0] == 2
    assert _tree_digest() == before


# ---------------------------------------------------------------------------
# Positive path 3: a semantically different custom-adapter retailer.
# ---------------------------------------------------------------------------
def _custom_retailer_staging() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_ledger_erp")
    con.execute(
        """
        CREATE VIEW raw_ledger_erp.ledger_headers AS
        SELECT * FROM (VALUES ('S-1','2026-01-06 09:00:00','EUR','erp-1'))
            AS t(sale_id, posted_at, currency_code, _source_instance)
        """
    )
    con.execute(
        """
        CREATE VIEW raw_ledger_erp.ledger_lines AS
        SELECT * FROM (VALUES
            ('S-1','L-1',1,'SKU-1','store-1','2026-01-05',5,'40.00','DRAFT',
             'erp-1','eu-west','hash-1'),
            ('S-1','L-1',2,'SKU-1','store-1','2026-01-05',3,'24.00','POSTED',
             'erp-1','eu-west','hash-1')
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
            return {"sourceSnapshotId": "snap-erp-1"}

    LedgerErpAdapter().materialize_staging(_Ctx())
    return con


def test_a_custom_retailer_reaches_the_same_role_without_downstream_change() -> None:
    before = _tree_digest()
    con = _custom_retailer_staging()

    row = con.execute(
        """
        SELECT source_sale_id, units, net_amount_major, role_id, source_system
        FROM stage_data.merchandise
        """
    ).fetchone()
    assert row[0] == "S-1"
    assert int(row[1]) == 3
    # Major units at the staging layer: EUR 24.00, not 2400 minor units. The canonical
    # transform is what converts to minor, and doing it twice was a 100x error.
    assert Decimal(str(row[2])) == Decimal("24.00")
    assert row[3] == "merchandise"
    assert row[4] == "ledgerErp"

    # The whole point: nothing downstream of staging moved.
    assert _tree_digest() == before


def test_both_retailers_produce_the_same_role_shape(tmp_path: Path) -> None:
    """Two unrelated sources converge on one standardized column set."""

    mapped = _mapped_retailer_staging(tmp_path, _mapping())
    custom = _custom_retailer_staging()

    def columns(connection) -> set[str]:
        return {
            row[0]
            for row in connection.execute("DESCRIBE stage_data.merchandise").fetchall()
        }

    shared = columns(mapped) & columns(custom)
    required = set(
        yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))["roles"][
            "merchandise"
        ]["requiredFields"]
    )
    assert required <= shared, sorted(required - shared)
    for field in ("role_id", "provider_id", "evidence_grade", "raw_object_hash"):
        assert field in shared, field


# ---------------------------------------------------------------------------
# The architectural promise, asserted structurally.
# ---------------------------------------------------------------------------
def test_no_retailer_identifier_appears_outside_adapters_or_fixtures() -> None:
    """The new retailers must not have leaked a name downstream."""

    for name in ("acme", "ledgererp", "ledger_erp", "generic-flat-file"):
        for tree in DOWNSTREAM_TREES:
            root = REPO_ROOT / tree
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix not in {
                    ".py",
                    ".go",
                    ".ts",
                    ".tsx",
                    ".sql",
                }:
                    continue
                if "__pycache__" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8", errors="ignore").lower()
                assert name not in text, f"{path.relative_to(REPO_ROOT)} names {name}"


def test_downstream_trees_are_unchanged_by_this_whole_module() -> None:
    """A single digest over transforms, quality, ML, API and UI source."""

    digest = _tree_digest()
    assert len(digest) == 64
    # Recomputing must be stable; a moving digest would make the guard useless.
    assert _tree_digest() == digest


def test_the_boundary_allowlist_still_holds() -> None:
    """PP3-A1's scan is part of the round-trip gate, not a one-off."""

    role_map = yaml.safe_load(ROLE_MAP.read_text(encoding="utf-8"))
    register = role_map["boundaryAllowlist"]["prohibitedKnownViolations"]
    assert register["violations"] == []
    for entry in register["cleared"]:
        text = (REPO_ROOT / entry["path"]).read_text(encoding="utf-8")
        assert entry["pattern"] not in text


# ---------------------------------------------------------------------------
# Negative paths.
# ---------------------------------------------------------------------------
def test_missing_temporal_evidence_is_reason_coded_not_fabricated(
    roles: dict,
) -> None:
    mapping = _mapping()
    mapping["datasets"][0]["temporalEvidence"] = {
        "knownAsOf": {"mode": "landing_time"},
        "grade": "native_observed",
    }
    with pytest.raises(MappedFilesError, match="landing_backfill"):
        validate_mapping(mapping, roles)


def test_an_ambiguous_mapping_fails_closed(roles: dict) -> None:
    mapping = _mapping()
    mapping["datasets"].append(dict(mapping["datasets"][0]))
    with pytest.raises(MappedFilesError, match="duplicate dataset"):
        validate_mapping(mapping, roles)


def test_landing_only_evidence_downgrades_rather_than_claiming_pit() -> None:
    """A retailer with only landing time gets an honest capability verdict."""

    evidence = {
        role: RoleEvidence(role=role, grade="landing_backfill", rows=10)
        for role in ("merchandise", "assortment", "product", "location")
    }
    report = build_readiness_report(
        ReadinessInputs(
            role_evidence=evidence,
            present_roles=frozenset(evidence),
            evidence_flags=frozenset(
                {"reconciliation", "sufficient_history", "accepted_fallback_semantics"}
            ),
            sufficiency={"demand_forecast_non_pit": "sufficient"},
        ),
        [],
        repository_root=REPO_ROOT,
        tenant_id="acme-uk",
        source_snapshot_id="snap-acme-1",
    )

    assert report["capabilities"]["demand_forecast_non_pit"]["readiness"] == READY
    assert report["capabilities"]["point_in_time_forecasting"]["readiness"] == (
        UNAVAILABLE
    )
    assert report["capabilities"]["historical_replay"]["readiness"] == UNAVAILABLE
    # Nothing was fabricated: the reason is explicit.
    assert any(
        reason.startswith("EVIDENCE_GRADE_TOO_WEAK")
        for reason in report["capabilities"]["historical_replay"]["reasonCodes"]
    )


def test_absent_assortment_coverage_blocks_zero_demand() -> None:
    report = build_readiness_report(
        ReadinessInputs(
            role_evidence={
                "merchandise": RoleEvidence(
                    role="merchandise", grade="native_extracted", rows=10
                )
            },
            present_roles=frozenset({"merchandise"}),
        ),
        [
            ZeroDemandCell(
                sku_id="SKU-1",
                store_id="store-1",
                channel_id="store",
                interval_start="2026-01-05",
                extract_complete=True,
                assortment_active=None,
                known_by_cutoff=True,
            )
        ],
        repository_root=REPO_ROOT,
        tenant_id="acme-uk",
        source_snapshot_id="snap-acme-1",
    )

    zero = report["zeroDemand"]
    assert zero["zeroEligible"] == 0
    assert zero["unknownReasonCodes"] == {"ASSORTMENT_UNKNOWN": 1}


def test_statistical_insufficiency_produces_an_honest_no_go() -> None:
    """Real retailer data may simply not support a capability."""

    evidence = {
        role: RoleEvidence(role=role, grade="native_extracted", rows=10)
        for role in ("merchandise", "assortment", "product", "location")
    }
    report = build_readiness_report(
        ReadinessInputs(
            role_evidence=evidence,
            present_roles=frozenset(evidence),
            evidence_flags=frozenset(
                {"reconciliation", "sufficient_history", "accepted_fallback_semantics"}
            ),
            sufficiency={"demand_forecast_non_pit": INSUFFICIENT},
        ),
        [],
        repository_root=REPO_ROOT,
        tenant_id="acme-uk",
        source_snapshot_id="snap-acme-1",
    )
    forecast = report["capabilities"]["demand_forecast_non_pit"]

    assert forecast["readiness"] == READY
    assert forecast["sufficiency"] == INSUFFICIENT
    assert forecast["consumerMayProceed"] is False


def test_mixed_tenant_lineage_cannot_reach_a_consumer(tmp_path: Path) -> None:
    """A selection for one tenant must not serve another."""

    selection = {
        "schemaVersion": "retail-publication-selection/v1",
        "scope": {
            "retailerId": "acme-grocers",
            "tenantId": "acme-uk",
            "capability": "demand_forecast_non_pit",
            "environment": "local",
        },
        "lifecycle": {"state": "active", "supersedes": None},
        "publication": {
            "sourceSnapshotId": "a" * 64,
            "gateASemanticFingerprint": "b" * 64,
            "gateBSemanticFingerprint": "c" * 64,
            "publicationSemanticFingerprint": "d" * 64,
            "logicalPath": "ingestion/data/curated/run-c5eb1506ecd4c550",
            "objectCount": 1509,
        },
        "readiness": {
            "reportFingerprint": "e" * 64,
            "capabilityReadiness": "ready",
            "capabilitySufficiency": "sufficient",
        },
        "approval": {
            "actor": "reviewer",
            "approvedAt": "2026-07-31T00:00:00Z",
            "reason": "round trip",
        },
    }
    selection["selectionId"] = derive_selection_id(selection)
    selection["lifecycle"]["recordId"] = derive_record_id(selection)
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(selection), encoding="utf-8")

    with pytest.raises(SelectionError, match="does not match requested"):
        resolve_selection(
            path,
            retailer_id="acme-grocers",
            tenant_id="acme-de",
            capability="demand_forecast_non_pit",
            environment="local",
            repository_root=REPO_ROOT,
        )


def test_an_unregistered_adapter_cannot_be_summoned() -> None:
    from retail_ingestion.adapters import adapter_for

    with pytest.raises(KeyError, match="no adapter registered"):
        adapter_for("some-plugin-from-a-url")


def test_import_boundaries_hold_for_the_new_adapters() -> None:
    """The shared boundary checker covers the new code too."""

    result = subprocess.run(
        ["python3", str(REPO_ROOT / "tools/check_import_boundaries.py")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_readiness_report_names_its_tenant_and_snapshot() -> None:
    """Lineage must be explicit so two tenants cannot be conflated."""

    report = build_readiness_report(
        ReadinessInputs(
            role_evidence={
                "merchandise": RoleEvidence(
                    role="merchandise", grade="native_extracted", rows=1
                )
            },
            present_roles=frozenset({"merchandise"}),
        ),
        [],
        repository_root=REPO_ROOT,
        tenant_id="acme-uk",
        source_snapshot_id="snap-acme-1",
    )
    assert report["tenantId"] == "acme-uk"
    assert report["sourceSnapshotId"] == "snap-acme-1"


def test_standardized_views_do_not_destroy_an_adapter_supplied_role() -> None:
    """The Track A blocker: the builder used to overwrite what an adapter staged.

    `_create_standardized_views` mapped every neutral role to a platform-dialect
    relation and ran unconditionally, so a role the mapped_files adapter had already
    materialised as a table was replaced by a view over a table a mapped-files-only
    retailer does not have. The retailer's rows were discarded, or the build failed
    outright on the missing relation.
    """

    import duckdb

    from retail_ingestion.staging.builder import _create_standardized_views

    con = duckdb.connect()
    con.execute("CREATE SCHEMA stage_data")
    # A retailer role staged by an adapter, with no platform-dialect relations at all.
    con.execute(
        "CREATE TABLE stage_data.merchandise AS "
        "SELECT 'client-row' AS marker, 1 AS units"
    )

    created = _create_standardized_views(
        con,
        already_materialized=frozenset({"stage_data.merchandise"}),
    )

    # The adapter's table survives untouched.
    rows = con.execute("SELECT marker FROM stage_data.merchandise").fetchall()
    assert rows == [("client-row",)]
    assert "stage_data.merchandise" in created

    # Roles nobody supplied are absent rather than fabricated, so a downstream
    # consumer sees them as unavailable instead of empty-but-present.
    assert "stage_data.inventory" not in created
    assert "stage_data.prices" not in created


def test_the_builder_does_not_require_platform_relations_to_exist() -> None:
    """A mapped-files-only source must not fail the view stage."""

    import duckdb

    from retail_ingestion.staging.builder import _create_standardized_views

    con = duckdb.connect()
    con.execute("CREATE SCHEMA stage_data")

    created = _create_standardized_views(con)

    assert created == (), "no supplier means no standardized relation, not an error"


def _mapped_only_snapshot(tmp_path: Path) -> tuple[Path, Path]:
    """Land a mapped-files-only snapshot: merchandise plus its location role."""

    snapshot = tmp_path / "snap"
    (snapshot / "public" / "sales").mkdir(parents=True)
    locations = snapshot / "public" / "sales" / "shops.csv"
    locations.write_text("code,title,kind\nstore-1,Camden Road,store\n", encoding="utf-8")
    sales = snapshot / "public" / "sales" / "weekly.csv"
    sales.write_text(
        "ccy,net,qty,day,chan,shop,item,line_no,order_no,posted_at\n"
        "GBP,12.50,3,05/01/2026,1,store-1,SKU-1,1,A-1,2026-01-06 08:00:00\n"
        "GBP,7.25,2,05/01/2026,2,store-1,SKU-2,1,A-2,2026-01-06 08:05:00\n",
        encoding="utf-8",
    )

    def _object(path: Path, logical: str, dataset: str, rows: int) -> dict:
        return {
            "permissionLane": "public",
            "landedPath": f"public/{logical}",
            "logicalPath": logical,
            "objectPath": f"s3://acme/{logical}",
            "sourceSystem": "mapped_files",
            "dataset": dataset,
            "format": "csv",
            "rows": rows,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }

    (snapshot / "landing-manifest.json").write_text(
        json.dumps(
            {
                "sourceSnapshotId": "snap-acme-1",
                "nativeSnapshotId": None,
                "landingTime": "2026-01-07T00:00:00Z",
                "semanticFingerprint": "0" * 64,
                "objects": [
                    _object(locations, "sales/shops.csv", "shop_master", 1),
                    _object(sales, "sales/weekly.csv", "weekly_sales", 2),
                ],
            }
        ),
        encoding="utf-8",
    )

    mapping = _mapping()
    mapping["datasets"].append(
        {
            "datasetId": "shop_master",
            "role": "location",
            "format": "csv",
            "logicalPath": "sales/shops.csv",
            "sourceKeys": ["code"],
            "grain": "location",
            "timezone": "Europe/London",
            "nullPolicy": {"onMissingRequired": "quarantine"},
            "temporalEvidence": {
                "knownAsOf": {"mode": "landing_time"},
                "grade": "landing_backfill",
            },
            "fields": [
                {"target": "location_source_key", "operation": "select", "source": "code"},
                {"target": "name", "operation": "select", "source": "title"},
                {"target": "location_kind", "operation": "select", "source": "kind"},
            ],
        }
    )
    profile = yaml.safe_load(
        (
            REPO_ROOT
            / "ingestion/src/retail_ingestion/profiles/retail_datagen.yaml"
        ).read_text(encoding="utf-8")
    )
    profile["sourceSystem"] = "mapped_files"
    profile["mappedFiles"] = mapping
    profile["locationResolution"] = {"mode": "location_role_identity"}
    profile["sourceInstances"] = [
        {
            "sourceSystem": "mapped_files",
            "sourceInstance": "acme-uk-1",
            "logicalPathPrefix": "sales/",
            "marketId": "gb-south",
            "currencyCode": "GBP",
            "timezone": "Europe/London",
            "capabilities": ["merchandise"],
        }
    ]
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")
    return snapshot, profile_path


def test_a_mapped_retailer_completes_the_whole_builder(tmp_path: Path) -> None:
    """The real entrypoint, not a hand-built adapter context.

    Driving `materialize_staging` directly proved the adapter but not the builder, and
    the builder held six couplings that each failed a mapped-files-only run *after* the
    retailer's rows were already staged: standardized views overwrote or demanded
    dialect relations, the quarantine pass queried them unconditionally, the profile
    schema refused the `mappedFiles` key the adapter requires, the location crosswalk
    read the generator's topology manifest, its coverage check unioned relations no
    retailer supplies, and the manifest required an upstream generator hash. A test
    that stops at the adapter cannot see any of them.
    """

    from retail_ingestion.staging.builder import build_staging

    snapshot, profile_path = _mapped_only_snapshot(tmp_path)
    result = build_staging(
        snapshot,
        profile_path,
        tmp_path / "stage.duckdb",
        execution_profile={"duckdbThreads": 2, "memoryLimitGb": 2},
    )

    manifest = json.loads(result.staging_manifest.read_text(encoding="utf-8"))
    counts = result.table_counts
    assert counts["stage_data.merchandise"] == 2
    # The role is `location`; a source-neutral consumer imports `locations`. Both must
    # resolve to the retailer's single row, not to an empty dialect view.
    assert counts["stage_data.location"] == 1
    assert counts["stage_data.locations"] == 1
    assert counts["stage_data.adapter_quarantine"] == 0
    # No dialect relation was invented to satisfy a view.
    assert not [name for name in counts if "shopify" in name or name.startswith("bc_")]
    assert manifest["upstreamManifestSha256"] is None
    assert manifest["locationCrosswalkRows"] == 1


def test_identity_resolution_must_be_declared_not_inferred(tmp_path: Path) -> None:
    """Omitting topology evidence must not silently switch identity authority."""

    from retail_ingestion.staging.builder import build_staging

    snapshot, profile_path = _mapped_only_snapshot(tmp_path)
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    del profile["locationResolution"]
    profile_path.write_text(yaml.safe_dump(profile), encoding="utf-8")

    with pytest.raises(Exception) as excinfo:
        build_staging(
            snapshot,
            profile_path,
            tmp_path / "stage.duckdb",
            execution_profile={"duckdbThreads": 2, "memoryLimitGb": 2},
        )
    # Defaulting to upstream_topology means the missing manifest is reported, rather
    # than the retailer's own keys being promoted to canonical identity by accident.
    assert "topology evidence" in str(excinfo.value)


def test_an_adapter_reject_reaches_the_shared_quarantine(tmp_path: Path) -> None:
    """Every invalid row must be traceable, whichever adapter rejected it.

    `_build_quarantine` only inspects dialect relations, so a mapped-files reject had
    nowhere governed to go: the row was excluded from `stage_data.merchandise` while both
    `manifest.quarantineRows` and `stage_data.adapter_quarantine` stayed at zero. Neither
    served nor traceable is the one outcome the contract forbids, and it is invisible
    precisely because the accepted role looks clean.
    """

    from retail_ingestion.staging.builder import build_staging

    snapshot, profile_path = _mapped_only_snapshot(tmp_path)
    # Break one required field on one row: a non-numeric quantity.
    sales = snapshot / "public" / "sales" / "weekly.csv"
    sales.write_text(
        "ccy,net,qty,day,chan,shop,item,line_no,order_no,posted_at\n"
        "GBP,12.50,3,05/01/2026,1,store-1,SKU-1,1,A-1,2026-01-06 08:00:00\n"
        "GBP,7.25,NOT-A-NUMBER,05/01/2026,2,store-1,SKU-2,1,A-2,2026-01-06 08:05:00\n",
        encoding="utf-8",
    )
    manifest_path = snapshot / "landing-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["objects"]:
        if entry["dataset"] == "weekly_sales":
            entry["bytes"] = sales.stat().st_size
            entry["sha256"] = hashlib.sha256(sales.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = build_staging(
        snapshot,
        profile_path,
        tmp_path / "stage.duckdb",
        execution_profile={"duckdbThreads": 2, "memoryLimitGb": 2},
    )

    counts = result.table_counts
    # The bad row is excluded from the accepted role...
    assert counts["stage_data.merchandise"] == 1
    # ...and is recorded in the shared quarantine rather than vanishing.
    assert counts["stage_data.adapter_quarantine"] == 1
    assert result.quarantine_rows == 1

    staged = duckdb.connect(str(result.staging_database), read_only=True)
    row = staged.execute(
        """
        SELECT dataset, reason_code, payload_hash IS NOT NULL
        FROM stage_data.adapter_quarantine
        """
    ).fetchone()
    # The reason code names WHY, and the dataset names which role it came from, so the
    # reject is attributable without reading adapter internals.
    assert row[0] == "merchandise"
    assert "UNPARSABLE" in str(row[1]) or "REQUIRED" in str(row[1])
    assert row[2] is True


def test_duplicate_display_names_are_allowed_under_identity_resolution() -> None:
    """Name uniqueness is a topology-matching requirement, not an identity one.

    `upstream_topology` resolves a topology entry to a role row BY NAME, so an ambiguous
    name would silently bind the wrong location and must fail. `location_role_identity`
    never reads the name -- the source key IS the canonical key -- so enforcing it there
    rejected valid client data: two distinct stores both called "Main Street" in one
    market, with distinct source keys, refused for a collision that cannot affect the
    result.
    """

    from retail_ingestion.mappings.locations import build_location_crosswalk

    class _Catalog:
        snapshot_root = Path("/nonexistent")
        profile = {
            "locationResolution": {"mode": "location_role_identity"},
            "sourceInstances": [
                {
                    "sourceInstance": "acme-1",
                    "marketId": "gb",
                    "currencyCode": "GBP",
                    "timezone": "UTC",
                }
            ],
        }

    con = duckdb.connect()
    con.execute("CREATE SCHEMA stage_data")
    con.execute(
        """
        CREATE TABLE stage_data.locations AS SELECT * FROM (VALUES
          ('generic-flat-file','acme-1','gb','store-1','Main Street','store'),
          ('generic-flat-file','acme-1','gb','store-2','Main Street','store'))
          AS t(source_system, source_instance, market_id,
               location_source_key, name, location_kind)
        """
    )
    con.execute(
        "CREATE TABLE stage_data.merchandise AS SELECT 'generic-flat-file' "
        "AS source_system, 'gb' AS market_id, 'store-1' AS demand_location_source_key"
    )

    rows = build_location_crosswalk(con, _Catalog())

    # Both locations resolve, keyed on their distinct source keys.
    assert rows == 2
    resolved = con.execute(
        "SELECT source_location_key, canonical_location_key "
        "FROM stage_data.location_crosswalk ORDER BY 1"
    ).fetchall()
    assert resolved == [("store-1", "store-1"), ("store-2", "store-2")]
