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
    / "run-adac9e85dccb56e8"
)
MANIFEST = RUN_ROOT / "source-run-manifest.json"
EVIDENCE_ROOT = (
    REPO_ROOT / "ingestion" / "data" / "evidence" / "run-adac9e85dccb56e8"
)
CURATED_ROOT = (
    REPO_ROOT / "ingestion" / "data" / "curated" / "run-adac9e85dccb56e8"
)


@pytest.mark.pinned_run
def test_phase2_pin_identity_inventory_and_permission_lanes() -> None:
    assert MANIFEST.is_file(), (
        "the accepted Phase-2 pin is not present locally; restore the exact immutable "
        "run rather than selecting latest or regenerating with another seed"
    )
    raw = MANIFEST.read_bytes()
    # Re-pinned 2026-08-04 onto the from-scratch rebuild, generator 0.16.0 / source
    # spec v13. The guard is kept deliberately byte-exact -- it exists to catch an
    # unnoticed regeneration or a changed seed, and that is exactly what it did.
    #
    # It cannot, however, be satisfied BY a regeneration: the manifest embeds
    # executionTelemetry (cpuProcessSeconds, cpuUtilizationPct, elapsed and per-worker
    # wallSeconds/peakRssBytes), so its bytes move on every run regardless of the data.
    # `runIdentityMethod` already excludes telemetry from runId; this hash does not.
    # So a rebuild must re-pin, and the exact-value assertions below are what actually
    # prove the data reproduced. Decision #89 covers whether that split is acceptable.
    #
    # This re-pin skipped three accepted runs -- the test still named the Phase 3
    # v12 run while r2, r3 and r4 came and went -- so the values below moved for
    # reasons this change did not cause, and each one that MOVED is annotated with
    # which run moved it. The ones that did NOT move across four regenerations and a
    # source-spec bump are the equivalence evidence: sales at 7,471,784 rows, 573
    # active SKUs at 2026-07-28, and a closed money reconciliation.
    assert hashlib.sha256(raw).hexdigest() == (
        "f9fc6c4a6f3628c4ee43e3b498915200a15edb8392f5e23abe2a363b6936fd73"
    )
    manifest = json.loads(raw)
    assert manifest["runId"] == "run-adac9e85dccb56e8"
    assert manifest["configHash"] == (
        "6dd93041e093e7d6294dd5925a031146c447ce0159169ad321a05a231e77b094"
    )
    assert manifest["generatorVersion"] == "0.16.0"
    assert manifest["sourceSpecVersion"] == "retail-source-config/v13"

    objects = manifest["objects"]
    # 8,726 under source spec v12. The datasets v13 added -- service lanes, inbound
    # and transfer status events, supply terms, store shortfall events -- account for
    # the difference; it is not a change in what any v12 dataset contains.
    assert len(objects) == 9_938
    paths = [row["path"] for row in objects]
    assert len(paths) == len(set(paths))
    source_truth_rows = sum(
        int(row["rows"] or 0)
        for row in objects
        if row["sourceSystem"] != "generator"
    )
    # 252,864,055 under v12, and the delta is entirely the new datasets: every v12
    # control below -- the currency totals, the fill rate, the order and line counts --
    # is unchanged, which is what says no existing row moved.
    assert source_truth_rows == 255_061_144

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
    assert len(public) == 9_692  # 9,689 source objects + 3 public metadata
    # Both unchanged from v12. The restricted lane is the one the permission model
    # rests on, so it growing by nothing while the public lane grew by 1,212 is worth
    # asserting rather than deriving: 9,692 + 245 + 1 is the whole inventory.
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
            "grossAmount": "97238216662.69",
            "netAmount": "84426913125.00",
            "orders": 4_590_902,
            "taxAmount": "12811303537.69",
            "units": 11_354_448,
        },
        "USD": {
            "grossAmount": "1261917926.25",
            "netAmount": "1170730807.46",
            "orders": 4_209_420,
            "taxAmount": "91187118.79",
            "units": 8_917_814,
        },
    }
    assert manifest["simulationControls"]["fillRate"] == "0.976855"
    assert manifest["simulationControls"]["orders"] == 8_800_322
    assert manifest["simulationControls"]["orderLines"] == 15_785_727


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
    assert len(gate_a["datasetInventory"]) == 146  # 132 under source spec v12
    assert gate_a["rules"][9]["evidence"]["restrictedObjectsOpened"] == 0
    assert next(
        rule for rule in gate_b["rules"] if rule["ruleId"] == "B18"
    )["outcome"] == "pass"
    b03 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B03")
    assert b03["outcome"] == "pass"
    assert b03["evidence"] == {
        "activeAssortmentDates": 7_471_784,
        "dateGapPolicy": "distinct_daily_row_inside_active_assortment_v1",
        "missingActiveDates": 0,
        "positiveSalesOutsideAssortment": 0,
        "zeroSalesRows": 4_275_653,
    }
    b15 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B15")
    assert b15["evidence"]["staleIntervals"] == 1_906
    b21 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B21")
    assert b21["evidence"]["affectedEntities"] == {
        "locations": 8,
        "sell_prices": 289_884,
        "suppliers_leadtimes": 654,
    }
    b16 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B16")
    assert b16["evidence"]["fulfillmentAggregateMismatches"] == 0
    assert b16["evidence"]["overfulfilledLines"] == 0
    b17 = next(rule for rule in gate_b["rules"] if rule["ruleId"] == "B17")
    assert b17["evidence"]["controls"] == [
        {
            "amountMinor": 437_291_129_332,
            "eventType": "financial_refund",
            "rows": 441_089,
            "units": 0,
        },
        {
            "amountMinor": 0,
            "eventType": "physical_return",
            "rows": 464_230,
            "units": 464_230,
        },
    ]
    assert all(
        row["difference"] == [0, 0, 0, 0]
        for row in gate_b["reconciliation"]
    )
    # 40 when this test was last re-pinned. The six v13 entities account for most of
    # it; the forty-seventh is `suppliers`, the vendor master, which landed every run
    # since v13 and was staged by none of them until P4-12e.
    assert len(publication["entityCounts"]) == 47
    assert publication["entityCounts"]["suppliers"] == 280
    assert publication["entityCounts"]["sales"] == 7_471_784
    assert publication["businessControls"] == {
        "activeSkus": 573,
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
        "totalSkus": 1_440,
    }
    object_paths = [row["path"] for row in publication["objects"]]
    assert len(object_paths) >= len(publication["entityCounts"])
    assert len(object_paths) == len(set(object_paths))
    assert (CURATED_ROOT / "retail_v2.duckdb").is_file()
