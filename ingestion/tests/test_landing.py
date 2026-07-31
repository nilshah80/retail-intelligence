"""Immutable three-lane landing on small contract fixtures."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest
from retail_ingestion.landing import LandingError, land_source_snapshot
from retail_ingestion.landing.snapshot import _make_writable_and_retry
from retail_ingestion.landing.snapshot_id import (
    SnapshotIdentityError,
    source_snapshot_id,
)


def _write_source(
    root: Path,
    *,
    run_id: str = "run-fixture",
    public_content: bytes = b"public",
    logical_path: str = "shopify/orders.parquet",
) -> Path:
    root.mkdir(parents=True)
    rows = [
        {
            "logicalPath": logical_path,
            "path": logical_path,
            "bytes": len(public_content),
            "sha256": hashlib.sha256(public_content).hexdigest(),
            "rows": 1,
            "format": "parquet",
            "compression": "zstd",
            "sourceSystem": "shopify",
            "dataset": "orders",
            "restricted": False,
        },
        {
            "logicalPath": "_truth/control.parquet",
            "path": "_truth/control.parquet",
            "bytes": 5,
            "sha256": hashlib.sha256(b"truth").hexdigest(),
            "rows": 1,
            "format": "parquet",
            "compression": "zstd",
            "sourceSystem": "hiddenTruth",
            "dataset": "controlTruth",
            "restricted": True,
        },
        {
            "logicalPath": "source-run.duckdb",
            "path": "source-run.duckdb",
            "bytes": 6,
            "sha256": hashlib.sha256(b"mirror").hexdigest(),
            "rows": 2,
            "format": "duckdb",
            "compression": "none",
            "sourceSystem": "generator",
            "dataset": "allSourceMirror",
            "restricted": True,
        },
    ]
    physical_objects = [
        ("_truth/control.parquet", b"truth"),
        ("source-run.duckdb", b"mirror"),
    ]
    if logical_path == "shopify/orders.parquet":
        physical_objects.insert(0, (logical_path, public_content))
    for relative, content in physical_objects:
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    manifest = {
        "manifestVersion": "source-run-manifest/v3",
        "runId": run_id,
        "scenarioId": "landing-fixture",
        "logicalEndDate": "2026-07-28",
        "retailer": {"retailerId": "retailer-fixture"},
        "objects": rows,
    }
    (root / "source-run-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return root


def test_snapshot_identity_is_independent_of_manifest_object_order() -> None:
    objects = [
        {"path": "b/part-2", "logicalPath": "b", "bytes": 1, "sha256": "b" * 64},
        {"path": "a/part-1", "logicalPath": "a", "bytes": 2, "sha256": "a" * 64},
    ]
    forward = source_snapshot_id(
        source_instance="retailer:source",
        extract_boundary="2026-07-28",
        objects=objects,
    )
    reverse = source_snapshot_id(
        source_instance="retailer:source",
        extract_boundary="2026-07-28",
        objects=reversed(objects),
    )
    assert forward == reverse


def test_snapshot_identity_rejects_duplicate_paths() -> None:
    objects = [
        {"path": "a", "logicalPath": "dataset-a", "bytes": 1, "sha256": "a" * 64},
        {"path": "a", "logicalPath": "dataset-b", "bytes": 1, "sha256": "a" * 64},
    ]
    with pytest.raises(SnapshotIdentityError, match="duplicate"):
        source_snapshot_id(
            source_instance="source",
            extract_boundary="2026-07-28",
            objects=objects,
        )


def test_landing_separates_lanes_verifies_and_replays_idempotently(
    tmp_path: Path,
) -> None:
    source = _write_source(tmp_path / "source")
    landing = tmp_path / "landing"
    first = land_source_snapshot(
        source,
        landing,
        execution_profile={"profile": "safe", "affectsRunIdentity": False},
    )
    assert first.idempotent_replay is False
    assert first.object_count == 3
    assert first.public_object_count == 1
    assert first.restricted_truth_object_count == 1
    assert first.restricted_mirror_object_count == 1

    expected = (
        first.snapshot_root / "public" / "shopify" / "orders.parquet",
        first.snapshot_root
        / "restricted_truth"
        / "_truth"
        / "control.parquet",
        first.snapshot_root
        / "restricted_mirror"
        / "source-run.duckdb",
    )
    assert [path.read_bytes() for path in expected] == [
        b"public",
        b"truth",
        b"mirror",
    ]
    assert all(path.stat().st_mode & stat.S_IWUSR == 0 for path in expected)
    manifest = json.loads(first.landing_manifest.read_text(encoding="utf-8"))
    assert manifest["sourceSnapshotId"] == first.source_snapshot_id
    assert manifest["nativeSnapshotId"] == "run-fixture"
    assert manifest["permissionLaneCounts"] == {
        "public": 1,
        "restricted_truth": 1,
        "restricted_mirror": 1,
    }
    assert manifest["semanticFingerprint"]

    replay = land_source_snapshot(source, landing)
    assert replay.idempotent_replay is True
    assert replay.source_snapshot_id == first.source_snapshot_id


def test_reused_native_id_with_different_content_is_rejected(tmp_path: Path) -> None:
    landing = tmp_path / "landing"
    land_source_snapshot(
        _write_source(tmp_path / "first", run_id="run-reused"),
        landing,
    )
    second = _write_source(
        tmp_path / "second",
        run_id="run-reused",
        public_content=b"different",
    )
    with pytest.raises(LandingError, match="reused"):
        land_source_snapshot(second, landing)


@pytest.mark.parametrize(
    "logical_path",
    (
        "../outside.parquet",
        r"..\outside.parquet",
        "/absolute.parquet",
        "shopify/./orders.parquet",
        "shopify//orders.parquet",
        "shopify/CON.parquet",
        "shopify/bad:name.parquet",
    ),
)
def test_unsafe_logical_paths_are_rejected(
    tmp_path: Path, logical_path: str
) -> None:
    source = _write_source(tmp_path / "source", logical_path=logical_path)
    with pytest.raises(LandingError, match="unsafe|portable"):
        land_source_snapshot(source, tmp_path / "landing")


def test_hash_mismatch_does_not_publish_partial_snapshot(tmp_path: Path) -> None:
    source = _write_source(tmp_path / "source")
    (source / "shopify" / "orders.parquet").write_bytes(b"tampered")
    landing = tmp_path / "landing"
    with pytest.raises(LandingError, match="mismatch"):
        land_source_snapshot(source, landing)
    assert not list((landing / "snapshots").glob("*"))
    assert not list(landing.glob(".*.staging-*"))


def test_readonly_cleanup_retry_restores_directory_traversal(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "readonly"
    directory.mkdir()
    directory.chmod(stat.S_IRUSR)
    probe = directory / "probe.txt"

    def write_probe(value: str) -> None:
        Path(value, probe.name).write_text("ok", encoding="utf-8")

    try:
        _make_writable_and_retry(
            write_probe,
            str(directory),
            PermissionError("read-only directory"),
        )
        assert probe.read_text(encoding="utf-8") == "ok"
        mode = stat.S_IMODE(directory.stat().st_mode)
        assert mode & stat.S_IRUSR
        assert mode & stat.S_IWUSR
        assert mode & stat.S_IXUSR
    finally:
        directory.chmod(stat.S_IRWXU)


def test_land_cli_uses_the_shared_execution_profile(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from retail_ingestion.cli import main

    source = _write_source(tmp_path / "source")
    result = main(
        [
            "land",
            "--source-root",
            str(source),
            "--landing-root",
            str(tmp_path / "landing"),
            "--execution-profile",
            "safe",
        ]
    )
    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["objectCount"] == 3
    assert output["idempotentReplay"] is False


def test_snapshot_identity_ignores_a_non_byte_deterministic_mirror() -> None:
    """Decision #89: an identity over byte hashes must exclude unstable bytes.

    `source-run.duckdb` is a restricted browsing mirror that `capabilities.duckdbRole`
    calls "non-authoritative" and ordinary ingestion never reads, and the generator
    declares its `contentDeterminism` as `logical`. Including it meant a rebuilt mirror
    changed the identity of unchanged authoritative data: two independent generations of
    the same pinned scenario produced 508 byte-identical Parquet objects and one DuckDB
    file differing in size and hash. Every fingerprint downstream inherited that, and
    `expected-pin.json` fail-closed the ML stages on data that had not changed.
    """

    from retail_ingestion.landing.snapshot_id import source_snapshot_id

    authoritative = [
        {
            "path": "public/sales/week=1/part-0.parquet",
            "logicalPath": "sales/week=1",
            "bytes": 2048,
            "sha256": "a" * 64,
            "contentDeterminism": "byte",
        },
        # Restricted but byte-stable: real generated content in the hidden-truth lane.
        # It must stay IN the identity; permission is not the discriminator.
        {
            "path": "_truth/demand_factors.parquet",
            "logicalPath": "_truth/demand_factors",
            "bytes": 512,
            "sha256": "b" * 64,
            "contentDeterminism": "byte",
            "restricted": True,
        },
    ]
    mirror_first = {
        "path": "source-run.duckdb",
        "logicalPath": "source-run.duckdb",
        "dataset": "sourceRunDuckdb",
        "format": "duckdb",
        "bytes": 116_142_080,
        "sha256": "c" * 64,
        "contentDeterminism": "logical",
        "restricted": True,
    }
    # Same logical content, mirror rebuilt: different size, different hash.
    mirror_second = dict(mirror_first, bytes=117_977_088, sha256="d" * 64)

    identity = dict(source_instance="acme", extract_boundary="2026-07-28")
    first = source_snapshot_id(**identity, objects=[*authoritative, mirror_first])
    second = source_snapshot_id(**identity, objects=[*authoritative, mirror_second])

    assert first == second
    # And the mirror contributes nothing at all, rather than merely being stable.
    assert first == source_snapshot_id(**identity, objects=authoritative)


def test_a_byte_stable_object_still_changes_the_snapshot_identity() -> None:
    """The exclusion must not become a hole that hides a real data change."""

    from retail_ingestion.landing.snapshot_id import source_snapshot_id

    identity = dict(source_instance="acme", extract_boundary="2026-07-28")
    base = {
        "path": "public/sales/week=1/part-0.parquet",
        "logicalPath": "sales/week=1",
        "bytes": 2048,
        "sha256": "a" * 64,
        "contentDeterminism": "byte",
    }
    changed = dict(base, sha256="e" * 64)

    assert source_snapshot_id(**identity, objects=[base]) != source_snapshot_id(
        **identity, objects=[changed]
    )


def test_an_inventory_of_only_unstable_objects_fails_closed() -> None:
    """Excluding everything must refuse, not mint an identity over nothing."""

    from retail_ingestion.landing.snapshot_id import (
        SnapshotIdentityError,
        source_snapshot_id,
    )

    with pytest.raises(SnapshotIdentityError) as excinfo:
        source_snapshot_id(
            source_instance="acme",
            extract_boundary="2026-07-28",
            objects=[
                {
                    "path": "source-run.duckdb",
                    "logicalPath": "source-run.duckdb",
                    "bytes": 1,
                    "sha256": "c" * 64,
                    "contentDeterminism": "logical",
                }
            ],
        )
    # The reason names what was dropped, so "empty inventory" is not mistaken for
    # "no objects were supplied".
    assert "source-run.duckdb" in str(excinfo.value)


def test_only_the_governed_mirror_may_claim_logical_determinism() -> None:
    """A source must not be able to redefine what the identity covers.

    `contentDeterminism` is producer-supplied and the landing manifest is only checked to
    be an object with an objects array. Without this gate a source could label an
    authoritative sales object `logical`, change its bytes and keep the same
    sourceSnapshotId. Current datagen only uses the field for source-run.duckdb; this
    makes that restriction enforced rather than merely true today.
    """

    from retail_ingestion.landing.snapshot_id import (
        SnapshotIdentityError,
        source_snapshot_id,
    )

    forged = {
        "path": "public/sales/week=1/part-0.parquet",
        "logicalPath": "sales/week=1",
        "dataset": "shopifyMerchandise",
        "format": "parquet",
        "bytes": 2048,
        "sha256": "a" * 64,
        # An authoritative sales object claiming the mirror's exemption.
        "contentDeterminism": "logical",
    }

    with pytest.raises(SnapshotIdentityError) as excinfo:
        source_snapshot_id(
            source_instance="acme",
            extract_boundary="2026-07-28",
            objects=[forged],
        )
    assert "governed non-authoritative mirror" in str(excinfo.value)
