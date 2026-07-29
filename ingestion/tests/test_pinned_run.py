"""Slow/local acceptance for the immutable Phase-2 source pin.

The test intentionally verifies the manifest and every object's path/byte count
without hashing 16 GiB on every invocation. Full SHA-256 verification belongs to
the one-time oracle-admin acceptance procedure already recorded in the plan.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = (
    REPO_ROOT
    / "datagen"
    / "output"
    / "multi-market-10-year-demo"
    / "run-34b0ff729c8abe09"
)
MANIFEST = RUN_ROOT / "source-run-manifest.json"
EVIDENCE_ROOT = (
    REPO_ROOT / "ingestion" / "data" / "evidence" / "run-34b0ff729c8abe09"
)
CURATED_ROOT = (
    REPO_ROOT / "ingestion" / "data" / "curated" / "run-34b0ff729c8abe09"
)


@pytest.mark.pinned_run
def test_phase2_pin_identity_inventory_and_permission_lanes() -> None:
    assert MANIFEST.is_file(), (
        "the accepted Phase-2 pin is not present locally; restore the exact immutable "
        "run rather than selecting latest or regenerating with another seed"
    )
    raw = MANIFEST.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == (
        "9edb5a7b5d931cd43a0333ce156404c93b0caa2c6b448e33d398e8425003598b"
    )
    manifest = json.loads(raw)
    assert manifest["runId"] == "run-34b0ff729c8abe09"
    assert manifest["configHash"] == (
        "3abbb96147c99c55e36e989a6eb6ba79305aab2caf0e1aa0cc200c1521853728"
    )
    assert manifest["generatorVersion"] == "0.12.0"
    assert manifest["sourceSpecVersion"] == "retail-source-config/v11"

    objects = manifest["objects"]
    assert len(objects) == 8_644
    paths = [row["path"] for row in objects]
    assert len(paths) == len(set(paths))
    source_truth_rows = sum(
        int(row["rows"] or 0)
        for row in objects
        if row["sourceSystem"] != "generator"
    )
    assert source_truth_rows == 253_192_804

    public = [row for row in objects if not row["restricted"]]
    truth = [
        row
        for row in objects
        if row["restricted"] and row["path"].startswith("_truth/")
    ]
    restricted_mirrors = [
        row
        for row in objects
        if row["restricted"] and row["format"] == "duckdb"
    ]
    assert len(public) == 8_398  # 8,395 source objects + 3 public metadata
    assert len(truth) == 245
    assert len(restricted_mirrors) == 1
    assert not [
        row
        for row in public
        if row["path"].startswith("_truth/")
        or row["dataset"].lower().endswith("truth")
    ]

    for row in objects:
        relative = Path(row["path"])
        assert not relative.is_absolute()
        artifact = RUN_ROOT / relative
        assert artifact.is_file(), row["path"]
        assert artifact.stat().st_size == int(row["bytes"]), row["path"]


@pytest.mark.pinned_run
def test_phase2_pin_controls_are_exact() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["controlsByCurrency"] == {
        "INR": {
            "grossAmount": "113592452338.96",
            "netAmount": "98156265872.00",
            "orders": 4_827_543,
            "taxAmount": "15436186466.96",
            "units": 12_395_915,
        },
        "USD": {
            "grossAmount": "1185135402.04",
            "netAmount": "1099192986.27",
            "orders": 4_720_243,
            "taxAmount": "85942415.77",
            "units": 12_764_658,
        },
    }
    assert manifest["simulationControls"]["fillRate"] == "0.972567"
    assert manifest["simulationControls"]["orders"] == 9_547_786
    assert manifest["simulationControls"]["orderLines"] == 17_130_980


@pytest.mark.pinned_run
def test_phase2_pipeline_gate_and_publication_evidence() -> None:
    gate_a = json.loads(
        (EVIDENCE_ROOT / "gate-a.json").read_text(encoding="utf-8")
    )
    gate_b = json.loads(
        (EVIDENCE_ROOT / "gate-b.json").read_text(encoding="utf-8")
    )
    publication = json.loads(
        (CURATED_ROOT / "publication-manifest.json").read_text(encoding="utf-8")
    )
    assert gate_a["status"] == "pass"
    assert gate_b["status"] == "pass"
    assert publication["sourceSnapshotId"] == gate_a["sourceSnapshotId"]
    assert publication["sourceSnapshotId"] == gate_b["sourceSnapshotId"]
    assert len(gate_a["datasetInventory"]) == 132
    assert gate_a["rules"][9]["evidence"]["restrictedObjectsOpened"] == 0
    assert next(
        rule for rule in gate_b["rules"] if rule["ruleId"] == "B18"
    )["outcome"] == "pass"
    b03 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B03")
    assert b03["outcome"] == "pass"
    assert b03["evidence"] == {
        "activeAssortmentDates": 4_565_498,
        "dateGapPolicy": "distinct_daily_row_inside_active_assortment_v1",
        "missingActiveDates": 0,
        "positiveSalesOutsideAssortment": 0,
        "zeroSalesRows": 2_228_133,
    }
    b15 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B15")
    assert b15["evidence"]["staleIntervals"] == 844
    b21 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B21")
    assert b21["evidence"]["affectedEntities"]["sales"] == 2_228_133
    b16 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B16")
    assert b16["evidence"]["fulfillmentAggregateMismatches"] == 0
    assert b16["evidence"]["overfulfilledLines"] == 0
    b17 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B17")
    assert b17["evidence"]["controls"] == [
        {
            "amountMinor": 458_825_950_637,
            "eventType": "financial_refund",
            "rows": 452_327,
            "units": 0,
        },
        {
            "amountMinor": 0,
            "eventType": "physical_return",
            "rows": 476_062,
            "units": 476_062,
        },
    ]
    assert all(
        row["difference"] == [0, 0, 0, 0]
        for row in gate_b["reconciliation"]
    )
    assert len(publication["entityCounts"]) == 40
    assert publication["entityCounts"]["sales"] == 4_565_498
    assert publication["businessControls"] == {
        "activeSkus": 348,
        "asOfDate": "2026-07-28",
        "channels": [
            {
                "channelId": "india-west:mumbai-online",
                "marketId": "india-west",
                "name": "mumbai-online",
                "type": "online",
            },
            {
                "channelId": "india-west:mumbai-store",
                "marketId": "india-west",
                "name": "mumbai-store",
                "type": "store",
            },
            {
                "channelId": "us-new-york:ny-online",
                "marketId": "us-new-york",
                "name": "ny-online",
                "type": "online",
            },
            {
                "channelId": "us-new-york:ny-store",
                "marketId": "us-new-york",
                "name": "ny-store",
                "type": "store",
            },
        ],
        "currencies": ["INR", "USD"],
        "dateRange": {"end": "2026-07-28", "start": "2016-07-28"},
        "fx": {
            "coverage": {
                "end": "2026-07-28",
                "observations": 7306,
                "start": "2016-07-28",
            },
            "rates": [
                {
                    "baseCurrency": "INR",
                    "quoteCurrency": "INR",
                    "rate": "1.000000000000000000",
                    "rateDate": "2026-07-28",
                },
                {
                    "baseCurrency": "USD",
                    "quoteCurrency": "INR",
                    "rate": "83.000000000000000000",
                    "rateDate": "2026-07-28",
                },
            ],
            "reportingCurrency": "INR",
        },
        "forecastCoveragePct": None,
        "markets": [
            {"marketId": "india-west", "name": "India West"},
            {"marketId": "us-new-york", "name": "US New York"},
        ],
        "modelAccuracyPct": None,
        "stores": [
            {
                "active": True,
                "city": "Mumbai",
                "currencyCode": "INR",
                "format": "store",
                "marketId": "india-west",
                "name": "Mumbai Bandra",
                "region": "MH",
                "storeId": "india-west:mumbai-bandra",
                "timezone": "Asia/Kolkata",
            },
            {
                "active": True,
                "city": "Pune",
                "currencyCode": "INR",
                "format": "store",
                "marketId": "india-west",
                "name": "Pune Koregaon Park",
                "region": "MH",
                "storeId": "india-west:pune-koregaon",
                "timezone": "Asia/Kolkata",
            },
            {
                "active": True,
                "city": "New York",
                "currencyCode": "USD",
                "format": "store",
                "marketId": "us-new-york",
                "name": "Brooklyn",
                "region": "NY",
                "storeId": "us-new-york:ny-brooklyn",
                "timezone": "America/New_York",
            },
            {
                "active": True,
                "city": "New York",
                "currencyCode": "USD",
                "format": "store",
                "marketId": "us-new-york",
                "name": "Manhattan",
                "region": "NY",
                "storeId": "us-new-york:ny-manhattan",
                "timezone": "America/New_York",
            },
        ],
        "totalSkus": 720,
    }
    object_paths = [row["path"] for row in publication["objects"]]
    assert len(object_paths) >= len(publication["entityCounts"])
    assert len(object_paths) == len(set(object_paths))
    assert (CURATED_ROOT / "retail_v2.duckdb").is_file()
