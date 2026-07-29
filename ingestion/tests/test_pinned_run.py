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
