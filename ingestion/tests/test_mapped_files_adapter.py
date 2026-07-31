"""PP3-A4 deliverable A-D5: mapped-files adapter conformance.

A non-Shopify, non-Business-Central retailer must reach standardized roles
through configuration alone, across all four physical formats, and every
negative fixture must fail closed with a reason code rather than losing rows.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest
import yaml

from retail_ingestion.adapters.mapped_files import (
    ALLOWED_OPERATIONS,
    MappedFilesAdapter,
    MappedFilesError,
    dry_run_report,
    mapping_fingerprint,
    validate_mapping,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGING_V2 = REPO_ROOT / "contracts/staging/staging-v2.yaml"


@pytest.fixture(scope="module")
def roles() -> dict:
    return yaml.safe_load(STAGING_V2.read_text(encoding="utf-8"))["roles"]


def _mapping(**dataset_overrides) -> dict:
    dataset = {
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
            {"target": "source_sale_id", "operation": "select", "source": "order_no"},
            {"target": "source_line_id", "operation": "select", "source": "line_no"},
            {"target": "sku_source_key", "operation": "select", "source": "item"},
            {
                "target": "demand_location_source_key",
                "operation": "select",
                "source": "shop",
            },
            {"target": "channel_source_key", "operation": "constant", "value": "store"},
            {
                "target": "business_date",
                "operation": "parse_date",
                "source": "day",
                "format": "%Y-%m-%d",
            },
            {"target": "units", "operation": "quantity", "source": "qty", "scale": 0},
            {
                "target": "net_amount_major",
                "operation": "money_major_normalize",
                "source": "net",
                "currencyColumn": "ccy",
            },
            {"target": "currency_code", "operation": "select", "source": "ccy"},
        ],
    }
    dataset.update(dataset_overrides)
    return {
        "schemaVersion": "retail-mapped-files/v1",
        "sourceSystem": "generic-flat-file",
        "mappingVersion": "1.0.0",
        "datasets": [dataset],
    }


# ---------------------------------------------------------------------------
# Positive: the mapping validates, fingerprints deterministically and compiles.
# ---------------------------------------------------------------------------
def test_a_generic_retailer_mapping_validates(roles: dict) -> None:
    validate_mapping(_mapping(), roles)


def test_mapping_fingerprint_is_deterministic_and_ignores_prose() -> None:
    first = mapping_fingerprint(_mapping())
    second = mapping_fingerprint(_mapping())
    assert first == second

    reworded = _mapping()
    reworded["description"] = "editorial change"
    assert mapping_fingerprint(reworded).sha256 == first.sha256

    material = _mapping()
    material["datasets"][0]["sourceKeys"] = ["order_no"]
    assert mapping_fingerprint(material).sha256 != first.sha256


def test_dry_run_reports_before_any_ingestion(roles: dict) -> None:
    report = dry_run_report(_mapping(), roles)

    assert report["schemaVersion"] == "retail-mapped-files-dry-run/v1"
    assert report["mappingSha256"]
    dataset = report["datasets"][0]
    assert dataset["role"] == "merchandise"
    assert dataset["evidenceGrade"] == "native_posted_available"
    assert dataset["capabilityDowngrade"] is False
    assert set(dataset["operations"]) <= ALLOWED_OPERATIONS


@pytest.mark.parametrize("physical_format", ["csv", "parquet", "jsonl", "json"])
def test_all_four_physical_formats_reach_the_same_role(
    roles: dict,
    physical_format: str,
    tmp_path: Path,
) -> None:
    """Renaming or re-encoding a client drop is a mapping change, not code."""

    rows = [
        {
            "order_no": "A-1",
            "line_no": "1",
            "item": "SKU-1",
            "shop": "store-1",
            "day": "2026-01-05",
            "qty": 3,
            "net": "12.50",
            "ccy": "GBP",
            "posted_at": "2026-01-06 08:00:00",
        }
    ]
    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_mapped_files")
    source = tmp_path / f"weekly.{physical_format}"
    if physical_format == "csv":
        source.write_text(
            "order_no,line_no,item,shop,day,qty,net,ccy,posted_at\n"
            "A-1,1,SKU-1,store-1,2026-01-05,3,12.50,GBP,2026-01-06 08:00:00\n",
            encoding="utf-8",
        )
        reader = f"read_csv_auto('{source}')"
    elif physical_format == "parquet":
        con.execute(
            f"COPY (SELECT * FROM (VALUES ('A-1','1','SKU-1','store-1','2026-01-05',"
            f"3,'12.50','GBP','2026-01-06 08:00:00')) AS t(order_no,line_no,item,shop,"
            f"day,qty,net,ccy,posted_at)) TO '{source}' (FORMAT PARQUET)"
        )
        reader = f"read_parquet('{source}')"
    else:
        payload = (
            json.dumps(rows[0])
            if physical_format == "jsonl"
            else json.dumps(rows)
        )
        source.write_text(payload, encoding="utf-8")
        reader = f"read_json_auto('{source}')"

    con.execute(
        f"""
        CREATE VIEW raw_mapped_files.weekly_sales AS
        SELECT *,
               'inst-1' AS _source_instance,
               'gb-south' AS _market_id,
               'deadbeef' AS _raw_object_hash
        FROM {reader}
        """
    )

    class _Ctx:
        connection = con
        catalog = None
        profile = {
            "sourceSchemaVersion": "flat/1",
            "profileVersion": "profile/1",
            "mappedFiles": _mapping(format=physical_format),
            "roleCatalog": roles,
        }

        @property
        def landing(self):
            return {
                "sourceSnapshotId": "snap-1",
                "nativeSnapshotId": None,
                "landingTime": "2026-01-07T00:00:00Z",
            }

    created = MappedFilesAdapter().materialize_staging(_Ctx())
    assert created == ("stage_data.merchandise",)

    row = con.execute(
        """
        SELECT role_id, provider_id, source_system, evidence_grade,
               evidence_class, derivation_class, units, currency_code,
               net_amount_major, business_date
        FROM stage_data.merchandise
        """
    ).fetchone()
    assert row is not None, f"{physical_format} produced no standardized row"
    assert row[0] == "merchandise"
    # The mapping's declared dialect, not the adapter's own name. Writing
    # "mapped_files" for every client would erase which retailer a row came from.
    assert row[2] == "generic-flat-file"
    assert row[3] == "native_posted_available"
    assert row[4] == "client"
    assert row[5] == "native"
    assert int(row[6]) == 3
    assert row[7] == "GBP"
    # net_amount_major holds MAJOR units, which is what its name and staging-v2's
    # `money:` list declare. The canonical transforms convert major to minor, so
    # 12.50 here becomes 1250 minor units downstream. This assertion used to expect
    # 1250 at the staging layer, meaning the transform converted a second time --
    # 125000 minor units, a hundred times the real amount for a two-decimal
    # currency.
    assert Decimal(str(row[8])) == Decimal("12.50")


# ---------------------------------------------------------------------------
# Negative fixtures: every one must fail closed.
# ---------------------------------------------------------------------------
def test_an_unlisted_operation_is_refused(roles: dict) -> None:
    mapping = _mapping()
    mapping["datasets"][0]["fields"].append(
        {"target": "units", "operation": "run_sql", "source": "SELECT 1"}
    )
    with pytest.raises(MappedFilesError, match="not allowed|allowlist"):
        validate_mapping(mapping, roles)


def test_a_missing_required_role_field_is_refused(roles: dict) -> None:
    mapping = _mapping()
    mapping["datasets"][0]["fields"] = [
        field
        for field in mapping["datasets"][0]["fields"]
        if field["target"] != "units"
    ]
    with pytest.raises(MappedFilesError, match="requires"):
        validate_mapping(mapping, roles)


def test_an_unknown_role_is_refused(roles: dict) -> None:
    with pytest.raises(MappedFilesError, match="unknown role"):
        validate_mapping(_mapping(role="not_a_role"), roles)


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../../secrets.csv", "sales/../../out.csv", "sales\\weekly.csv"],
)
def test_path_escape_is_refused(roles: dict, path: str) -> None:
    with pytest.raises(MappedFilesError):
        validate_mapping(_mapping(logicalPath=path), roles)


def test_an_unsupported_format_is_refused(roles: dict) -> None:
    with pytest.raises(MappedFilesError, match="unsupported format"):
        validate_mapping(_mapping(format="xlsx"), roles)


def test_landing_time_evidence_must_accept_the_downgrade(roles: dict) -> None:
    """Landing time may only be claimed as landing_backfill."""

    mapping = _mapping(
        temporalEvidence={
            "knownAsOf": {"mode": "landing_time"},
            "grade": "native_observed",
        }
    )
    with pytest.raises(MappedFilesError, match="landing_backfill"):
        validate_mapping(mapping, roles)

    allowed = _mapping(
        temporalEvidence={
            "knownAsOf": {"mode": "landing_time"},
            "grade": "landing_backfill",
        }
    )
    validate_mapping(allowed, roles)
    assert dry_run_report(allowed, roles)["datasets"][0]["capabilityDowngrade"] is True


def test_a_row_filter_without_a_reason_code_is_refused(roles: dict) -> None:
    mapping = _mapping(
        rowFilter={"column": "status", "operator": "in", "values": ["ok"]}
    )
    with pytest.raises(MappedFilesError, match="reason code"):
        validate_mapping(mapping, roles)


def test_a_field_name_cannot_smuggle_sql(roles: dict) -> None:
    """Only plain field names may reach compiled SQL."""

    from retail_ingestion.adapters.mapped_files import _compile_field

    with pytest.raises(MappedFilesError, match="plain field name"):
        _compile_field(
            {
                "target": "units",
                "operation": "select",
                "source": "qty FROM x; DROP TABLE stage_data.merchandise; --",
            },
            _mapping()["datasets"][0],
        )


def test_value_map_has_no_default_branch(roles: dict) -> None:
    from retail_ingestion.adapters.mapped_files import _compile_field

    expression = _compile_field(
        {
            "target": "channel_source_key",
            "operation": "value_map",
            "source": "chan",
            "map": {"1": "store", "2": "online"},
        },
        _mapping()["datasets"][0],
    )
    assert "ELSE" not in expression.upper()


def test_duplicate_dataset_for_one_role_is_refused(roles: dict) -> None:
    mapping = _mapping()
    mapping["datasets"].append(dict(mapping["datasets"][0]))
    with pytest.raises(MappedFilesError, match="duplicate dataset"):
        validate_mapping(mapping, roles)


def test_invalid_money_precision_quarantines_rather_than_rounding(
    roles: dict,
    tmp_path: Path,
) -> None:
    """A sub-minor-unit amount must be reason-coded, not silently rounded."""

    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_mapped_files")
    source = tmp_path / "weekly.csv"
    source.write_text(
        "order_no,line_no,item,shop,day,qty,net,ccy,posted_at\n"
        "A-1,1,SKU-1,store-1,2026-01-05,3,12.505,GBP,2026-01-06 08:00:00\n"
        "A-2,1,SKU-2,store-1,2026-01-05,1,10.00,GBP,2026-01-06 08:00:00\n",
        encoding="utf-8",
    )
    con.execute(
        f"""
        CREATE VIEW raw_mapped_files.weekly_sales AS
        SELECT *, 'inst-1' AS _source_instance, 'gb-south' AS _market_id,
               'deadbeef' AS _raw_object_hash
        FROM read_csv_auto('{source}')
        """
    )

    class _Ctx:
        connection = con
        catalog = None
        profile = {
            "sourceSchemaVersion": "flat/1",
            "profileVersion": "profile/1",
            "mappedFiles": _mapping(),
            "roleCatalog": roles,
        }

        @property
        def landing(self):
            return {
                "sourceSnapshotId": "snap-1",
                "nativeSnapshotId": None,
                "landingTime": "2026-01-07T00:00:00Z",
            }

    MappedFilesAdapter().materialize_staging(_Ctx())

    accepted = con.execute("SELECT count(*) FROM stage_data.merchandise").fetchone()[0]
    rejected = con.execute(
        """
        SELECT _reject_reason, count(*)
        FROM stage_data.merchandise_candidate
        WHERE _reject_reason IS NOT NULL
        GROUP BY 1
        """
    ).fetchall()

    # The valid row is accepted; the sub-minor-unit row is reason-coded, and no
    # row disappears without an accounting.
    assert accepted == 1
    assert rejected == [("MONEY_PRECISION_INVALID", 1)]
    total = con.execute(
        "SELECT count(*) FROM stage_data.merchandise_candidate"
    ).fetchone()[0]
    assert total == accepted + 1


def test_money_scale_conversion_is_refused_on_a_major_unit_target(roles: dict) -> None:
    """The 100x bug this fixture set used to encode.

    staging-v2 declares merchandise money in MAJOR units and the canonical
    transforms convert major to minor. An adapter that also converted would land
    minor units in a major-unit column and the transform would multiply again, so
    a two-decimal currency would report a hundred times its real revenue. Every
    fixture in this file used to do exactly that.
    """

    mapping = _mapping()
    for field in mapping["datasets"][0]["fields"]:
        if field["target"] == "net_amount_major":
            field["operation"] = "money_major_to_minor"

    with pytest.raises(MappedFilesError, match="converted a second time"):
        validate_mapping(mapping, roles)


def test_two_datasets_on_an_exclusive_role_fail_closed(roles: dict) -> None:
    """Last-write-wins silently discarded the first provider."""

    mapping = _mapping()
    duplicate = json.loads(json.dumps(mapping["datasets"][0]))
    duplicate["datasetId"] = "weekly_sales_second_feed"
    mapping["datasets"].append(duplicate)

    with pytest.raises(MappedFilesError, match="providerResolution"):
        validate_mapping(mapping, roles)


def test_a_required_field_that_fails_to_parse_is_rejected(
    roles: dict,
    tmp_path: Path,
) -> None:
    """The declared-versus-parsed gap.

    Mapping validation confirms a required role field is DECLARED. It cannot know
    whether the value parses. An invalid date and a non-numeric quantity both become
    NULL through try_cast, and both used to enter the accepted role table with no
    rejection reason -- a required field silently absent, which is worse than a
    rejected row because nothing downstream can tell.
    """

    con = duckdb.connect()
    con.execute("CREATE SCHEMA raw_mapped_files")
    source = tmp_path / "weekly.csv"
    source.write_text(
        "order_no,line_no,item,shop,day,qty,net,ccy,posted_at\n"
        # valid
        "A-1,1,SKU-1,store-1,2026-01-05,3,10.00,GBP,2026-01-06 08:00:00\n"
        # unparsable required date
        "A-2,1,SKU-2,store-1,not-a-date,3,10.00,GBP,2026-01-06 08:00:00\n"
        # unparsable required quantity
        "A-3,1,SKU-3,store-1,2026-01-05,three,10.00,GBP,2026-01-06 08:00:00\n",
        encoding="utf-8",
    )
    con.execute(
        f"""
        CREATE VIEW raw_mapped_files.weekly_sales AS
        SELECT *, 'inst-1' AS _source_instance, 'gb-south' AS _market_id,
               'deadbeef' AS _raw_object_hash
        FROM read_csv_auto('{source}', all_varchar=true)
        """
    )

    class _Ctx:
        connection = con
        catalog = None
        profile = {
            "sourceSchemaVersion": "flat/1",
            "profileVersion": "profile/1",
            "mappedFiles": _mapping(),
            "roleCatalog": roles,
        }

        @property
        def landing(self):
            return {
                "sourceSnapshotId": "snap-1",
                "nativeSnapshotId": None,
                "landingTime": "2026-01-07T00:00:00Z",
            }

    MappedFilesAdapter().materialize_staging(_Ctx())

    accepted = con.execute(
        "SELECT count(*) FROM stage_data.merchandise"
    ).fetchone()[0]
    reasons = [
        row[0]
        for row in con.execute(
            """
            SELECT DISTINCT _reject_reason
            FROM stage_data.merchandise_candidate
            WHERE _reject_reason IS NOT NULL
            """
        ).fetchall()
    ]

    assert accepted == 1, "only the fully parsable row may be accepted"
    assert any("REQUIRED_FIELD_UNPARSABLE" in reason for reason in reasons)
    # No accepted row may carry a NULL required field.
    nulls = con.execute(
        """
        SELECT count(*) FROM stage_data.merchandise
        WHERE business_date IS NULL OR units IS NULL
        """
    ).fetchone()[0]
    assert nulls == 0
