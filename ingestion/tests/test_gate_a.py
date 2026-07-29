"""Executable A01–A13 contract tests with passing and failing evidence."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from retail_ingestion.landing import land_source_snapshot
from retail_ingestion.quality import run_gate_a


def _write_profile(
    path: Path,
    *,
    classify_orders: bool = True,
    order_format: str = "parquet",
) -> Path:
    datasets = [
        {
            "sourceSystem": "generator",
            "datasetId": "sourceSchema",
            "classification": "control_only",
            "permissionLane": "public",
            "format": "json",
            "sourceKeys": [],
            "grainFields": [],
            "columnPolicies": [],
        }
    ]
    if classify_orders:
        datasets.insert(
            0,
            {
                "sourceSystem": "shopify",
                "datasetId": "orders",
                "classification": "staged",
                "permissionLane": "public",
                "format": order_format,
                "sourceKeys": ["id"],
                "grainFields": ["id", "createdAt"],
                "columnPolicies": [],
            },
        )
    profile = {
        "schemaVersion": "retail-source-profile/v1",
        "profileId": "gate-a-fixture",
        "profileVersion": "1.0.0",
        "sourceSystem": "fixture",
        "sourceSchemaVersion": "fixture/v1",
        "businessTimezone": "source_location_timezone",
        "extractWindow": {"start": "2026-07-01", "end": "2026-07-28"},
        "channelPolicy": {"mode": "native"},
        "assortmentPolicy": {"mode": "unavailable"},
        "money": {
            "sourceUnit": "major_decimal",
            "taxBasis": "source_field",
            "currencyField": "currencyCode",
            "taxBasisField": "taxesIncluded",
        },
        "quantityPolicy": {
            "mode": "entity_semantics",
            "derivationRule": "order-line quantity is an item count",
        },
        "mappingReferences": ["orders.locationId"],
        "sourceInstances": [
            {
                "sourceSystem": "shopify",
                "sourceInstance": "fixture",
                "logicalPathPrefix": "shopify/fixture/",
                "marketId": "fixture-market",
                "currencyCode": "USD",
                "timezone": "UTC",
                "capabilities": ["commerce"],
            }
        ],
        "publicationRequirements": {
            "requiredCapabilities": ["commerce"]
        },
        "authenticity": {"mode": "not_required_for_snapshot"},
        "datasets": datasets,
    }
    path.write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_gate_source(
    root: Path, ids: list[str], *, order_format: str = "parquet"
) -> Path:
    order_path = (
        root / "shopify" / "fixture" / "orders" / f"part.{order_format}"
    )
    order_path.parent.mkdir(parents=True)
    table = pa.table(
        {
            "id": ids,
            "createdAt": ["2026-07-28T10:00:00Z"] * len(ids),
            "currencyCode": ["USD"] * len(ids),
            "taxesIncluded": ["false"] * len(ids),
            "locationId": ["loc-1"] * len(ids),
        }
    )
    if order_format == "parquet":
        pq.write_table(table, order_path, compression="zstd")
    elif order_format == "csv":
        order_path.write_text(
            "id,createdAt,currencyCode,taxesIncluded,locationId\n"
            + "".join(
                f"{identifier},2026-07-28T10:00:00Z,USD,false,loc-1\n"
                for identifier in ids
            ),
            encoding="utf-8",
            newline="\n",
        )
    elif order_format == "jsonl":
        order_path.write_text(
            "".join(
                json.dumps(
                    {
                        "id": identifier,
                        "createdAt": "2026-07-28T10:00:00Z",
                        "currencyCode": "USD",
                        "taxesIncluded": "false",
                        "locationId": "loc-1",
                    },
                    separators=(",", ":"),
                )
                + "\n"
                for identifier in ids
            ),
            encoding="utf-8",
            newline="\n",
        )
    else:
        raise ValueError(f"unsupported test format: {order_format}")

    source_schema = {
        "schemaVersion": "retail-source-schema/v1",
        "physicalTypePolicy": "fixture",
        "datasets": [
            {
                "sourceSystem": "shopify",
                "dataset": "orders",
                "logicalPath": f"shopify/fixture/orders.{order_format}",
                "restricted": False,
                "fields": [
                    {
                        "name": field.name,
                        "physicalType": str(field.type),
                        "nullable": field.nullable,
                    }
                    for field in table.schema
                ],
            }
        ],
    }
    schema_path = root / "source-schema.json"
    schema_path.write_text(
        json.dumps(source_schema, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )

    objects = []
    for path, logical_path, source_system, dataset, rows, artifact_format in (
        (
            order_path,
            f"shopify/fixture/orders.{order_format}",
            "shopify",
            "orders",
            len(ids),
            order_format,
        ),
        (
            schema_path,
            "source-schema.json",
            "generator",
            "sourceSchema",
            None,
            "json",
        ),
    ):
        raw = path.read_bytes()
        objects.append(
            {
                "path": path.relative_to(root).as_posix(),
                "logicalPath": logical_path,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "rows": rows,
                "format": artifact_format,
                "compression": "zstd" if artifact_format == "parquet" else "none",
                "sourceSystem": source_system,
                "dataset": dataset,
                "restricted": False,
            }
        )
    manifest = {
        "manifestVersion": "source-run-manifest/v3",
        "runId": "run-gate-a-fixture",
        "scenarioId": "gate-a-fixture",
        "logicalStartDate": "2026-07-01",
        "logicalEndDate": "2026-07-28",
        "retailer": {"retailerId": "retailer-fixture"},
        "objects": objects,
        "controlsByCurrency": {
            "USD": {
                "orders": len(ids),
                "units": len(ids),
                "grossAmount": f"{10 * len(ids)}.00",
                "netAmount": f"{9 * len(ids)}.00",
                "taxAmount": f"{len(ids)}.00",
            }
        },
    }
    (root / "source-run-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
        newline="\n",
    )
    return root


def _land_fixture(
    tmp_path: Path, ids: list[str], *, order_format: str = "parquet"
) -> Path:
    result = land_source_snapshot(
        _write_gate_source(
            tmp_path / "source", ids, order_format=order_format
        ),
        tmp_path / "landing",
        execution_profile={
            "schemaVersion": "retail-execution-profile/v1",
            "profile": "safe",
            "affectsRunIdentity": False,
        },
    )
    return result.snapshot_root


def test_gate_a_passes_all_thirteen_rules_on_valid_source(tmp_path: Path) -> None:
    snapshot = _land_fixture(tmp_path, ["order-1", "order-2"])
    profile = _write_profile(tmp_path / "profile.yaml")
    report = run_gate_a(
        snapshot,
        profile,
        duckdb_threads=3,
        memory_limit_gb=7,
        execution_profile={
            "schemaVersion": "retail-execution-profile/v1",
            "profile": "test-bounded",
            "affectsRunIdentity": False,
            "duckdbThreads": 3,
            "memoryLimitGb": 7,
        },
    )

    assert report.status == "pass"
    assert [(rule.rule_id, rule.outcome.value) for rule in report.rules] == [
        (f"A{number:02d}", "pass") for number in range(1, 14)
    ]
    payload = report.as_dict()
    assert payload["controlsByCurrency"]["USD"]["orders"] == 2
    assert payload["datasetInventory"][0]["scannedRows"] == 2
    assert payload["executionProfile"]["profile"] == "test-bounded"
    assert payload["semanticFingerprint"]


def test_gate_a_rejects_duplicate_declared_source_keys(tmp_path: Path) -> None:
    snapshot = _land_fixture(tmp_path, ["order-1", "order-1"])
    report = run_gate_a(snapshot, _write_profile(tmp_path / "profile.yaml"))

    assert report.status == "critical"
    a05 = next(rule for rule in report.rules if rule.rule_id == "A05")
    assert a05.outcome.value == "critical"
    assert "duplicate source keys" in str(a05.evidence)


def test_gate_a_accepts_declared_jsonl_source(tmp_path: Path) -> None:
    snapshot = _land_fixture(
        tmp_path, ["order-1", "order-2"], order_format="jsonl"
    )
    report = run_gate_a(
        snapshot,
        _write_profile(tmp_path / "profile.yaml", order_format="jsonl"),
    )

    assert report.status == "pass"
    assert report.dataset_inventory[0]["format"] == "jsonl"
    assert report.dataset_inventory[0]["scannedRows"] == 2


def test_gate_a_rejects_unclassified_published_dataset(tmp_path: Path) -> None:
    snapshot = _land_fixture(tmp_path, ["order-1"])
    report = run_gate_a(
        snapshot,
        _write_profile(tmp_path / "profile.yaml", classify_orders=False),
    )

    assert report.status == "critical"
    a13 = next(rule for rule in report.rules if rule.rule_id == "A13")
    assert a13.outcome.value == "critical"
    assert "shopify/orders" in str(a13.evidence)


def test_gate_a_detects_public_content_tampering(tmp_path: Path) -> None:
    snapshot = _land_fixture(tmp_path, ["order-1"])
    artifact = snapshot / "public" / "shopify" / "fixture" / "orders" / "part.parquet"
    artifact.chmod(stat.S_IRUSR | stat.S_IWUSR)
    with artifact.open("ab") as writer:
        writer.write(b"tampered")

    report = run_gate_a(
        snapshot,
        _write_profile(tmp_path / "profile.yaml"),
        scan_data=False,
    )
    a01 = next(rule for rule in report.rules if rule.rule_id == "A01")
    assert a01.outcome.value == "critical"
    assert "bytes" in str(a01.evidence)


def test_gate_a_metadata_replay_says_content_was_not_rehashed(
    tmp_path: Path,
) -> None:
    snapshot = _land_fixture(tmp_path, ["order-1"])
    report = run_gate_a(
        snapshot,
        _write_profile(tmp_path / "profile.yaml"),
        verify_content=False,
        scan_data=False,
    )

    assert report.status == "pass"
    a01 = next(rule for rule in report.rules if rule.rule_id == "A01")
    assert a01.evidence["verificationMode"] == "metadata_only"
    a10 = next(rule for rule in report.rules if rule.rule_id == "A10")
    assert a10.evidence["restrictedObjectsOpened"] == 0


def test_gate_a_supports_profile_declared_csv_sources(tmp_path: Path) -> None:
    snapshot = _land_fixture(
        tmp_path, ["order-1", "order-2"], order_format="csv"
    )
    report = run_gate_a(
        snapshot,
        _write_profile(tmp_path / "profile.yaml", order_format="csv"),
    )

    assert report.status == "pass"
    order_inventory = next(
        row for row in report.dataset_inventory if row["dataset"] == "orders"
    )
    assert order_inventory["format"] == "csv"
    assert order_inventory["scannedRows"] == 2


def test_manifestless_retailer_drop_builds_profile_derived_evidence(
    tmp_path: Path,
) -> None:
    source = _write_gate_source(tmp_path / "source", ["order-1", "order-2"])
    (source / "source-run-manifest.json").unlink()
    (source / "source-schema.json").unlink()
    profile_path = _write_profile(tmp_path / "profile.yaml")
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    profile["datasets"] = [
        row for row in profile["datasets"] if row["sourceSystem"] != "generator"
    ]
    profile["datasets"][0]["pathGlob"] = "shopify/fixture/orders/*.parquet"
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False),
        encoding="utf-8",
        newline="\n",
    )

    landed = land_source_snapshot(
        source,
        tmp_path / "landing",
        source_profile=profile_path,
        source_instance="fixture",
        extract_boundary="2026-07-28",
        execution_profile={
            "schemaVersion": "retail-execution-profile/v1",
            "profile": "safe",
            "affectsRunIdentity": False,
        },
    )
    landing = json.loads(landed.landing_manifest.read_text(encoding="utf-8"))
    assert landing["upstreamManifest"]["origin"] == "ingestion_derived"

    report = run_gate_a(landed.snapshot_root, profile_path)
    assert report.status == "pass"
    assert next(
        rule for rule in report.rules if rule.rule_id == "A08"
    ).outcome.value == "capability_downgrade"
    assert report.dataset_inventory[0]["scannedRows"] == 2
