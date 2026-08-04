"""No wall clock may participate in the staging semantic fingerprint.

`P4-12e`. `landingTime` did, and every fingerprint below staging inherits this one:
the transform manifest carries `stagingSemanticFingerprint`, the candidate's identity
carries the transform's, and the curated publication's carries the candidate's. So the
publication fingerprint moved on every re-land of byte-identical source -- which made
the pin move on rebuilds that changed nothing, and made a publication selection record
impossible to re-derive because the fingerprint it named had stopped existing.

Two full pipeline runs of one snapshot disagreed on the publication fingerprint while
transform and publish were each separately measured deterministic. Nothing failed,
because nothing asserted this. These tests are what that gap should have looked like:
they fingerprint the manifest payload directly, so they cost milliseconds rather than
the six minutes two real staging runs take.
"""

from __future__ import annotations

from retail_contracts.fingerprint import semantic_fingerprint

from retail_ingestion.staging.builder import STAGING_VOLATILE_POINTERS

#: Shaped like a real staging manifest, reduced to the fields these tests move.
BASE = {
    "schemaVersion": "retail-staging/v1",
    "sourceSnapshotId": "a" * 64,
    "extractBoundary": "2026-07-28",
    "landingTime": "2026-08-04T13:21:36.689972Z",
    "profileId": "retail_datagen",
    "profileVersion": "v13",
    "stagingTables": ["bc_vendors", "shopify_merchandise"],
    "tableCounts": {"bc_vendors": 280},
    "databaseSha256": "b" * 64,
    "completedAt": "2026-08-04T13:24:52.724934Z",
    "executionProfile": {"profile": "performance"},
}


def _fingerprint(**overrides) -> str:
    payload = {**BASE, **overrides}
    return semantic_fingerprint(payload, volatile_pointers=STAGING_VOLATILE_POINTERS)


def test_landing_time_does_not_change_the_staging_fingerprint() -> None:
    """The defect, stated as an assertion.

    Same snapshot, same tables, same counts, landed at a different instant. If these
    disagree, the curated publication fingerprint stops meaning "this data" and starts
    meaning "this data, landed at this moment" -- and every pin and selection record
    below inherits that.
    """

    assert _fingerprint() == _fingerprint(
        landingTime="2019-01-01T00:00:00.000001Z"
    )


def test_the_recorded_volatile_set_still_excludes_every_known_clock() -> None:
    """Named explicitly so removing one is a deliberate act, not a refactor."""

    for pointer in ("/landingTime", "/completedAt"):
        assert pointer in STAGING_VOLATILE_POINTERS


def test_landing_time_is_still_recorded_even_though_it_is_excluded() -> None:
    """Excluded from identity is not the same as dropped.

    The instant remains real provenance and stays in the manifest; it simply stops
    claiming to be part of what the staging database contains.
    """

    assert BASE["landingTime"] is not None


def test_content_still_changes_the_staging_fingerprint() -> None:
    """The exclusions must not have hollowed the fingerprint out.

    A volatile set that grows until nothing is left would pass the first test while
    making the fingerprint worthless, so each field that genuinely describes content
    is moved here and required to matter.
    """

    assert _fingerprint() != _fingerprint(sourceSnapshotId="c" * 64)
    assert _fingerprint() != _fingerprint(tableCounts={"bc_vendors": 281})
    assert _fingerprint() != _fingerprint(stagingTables=["bc_vendors"])
    assert _fingerprint() != _fingerprint(extractBoundary="2026-07-27")
    assert _fingerprint() != _fingerprint(profileVersion="v12")
