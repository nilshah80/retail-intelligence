"""Every client that names the required serving migration must name the same one.

`P4-0` task 6. Six files independently hard-code the migration head that serving
requires: the ML materializer, the ML publisher's manifest evidence, the Go read
model, the database schema test, the closure-record generator and the generated
closure record. Five of them said `0008_nullable_withheld_interval` while the
closure generator and its record still said `0007_activation_and_coverage`, so
`tools/dev.py verify` passed against a record that named a migration the live
stack had already moved past.

A string constant cannot detect its own staleness, so this does not compare the
pins to another string. It derives the head from the Alembic graph -- the revision
no other revision revises -- and requires every client to equal that. When 0009
and 0010 land the test fails until each pin advances, which is the behaviour the
plan asks for: the pins move together or the gate stops.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = REPO_ROOT / "db" / "migrations" / "versions"

#: Regression floor. Each of these was the required head once and is now
#: inherited history: 0006 was v4-only, 0007 established the verifier-v5
#: boundary, and 0008 made the withheld interval storable without making
#: availability explicit. Naming any of them as the *current required head* is
#: the specific regression this test exists to catch, so it is asserted
#: explicitly rather than left to the graph comparison.
RETIRED_HEADS = frozenset(
    {
        "0006_cohorted_verifier_v4",
        "0007_activation_and_coverage",
        "0008_nullable_withheld_interval",
        "0009_forecast_interval_contract",
    }
)


def _alembic_revisions() -> dict[str, str | None]:
    revisions: dict[str, str | None] = {}
    revision_pattern = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)
    down_pattern = re.compile(
        r'^down_revision:[^=]*=\s*(?:"([^"]+)"|None)', re.MULTILINE
    )
    for path in sorted(MIGRATIONS.glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8")
        revision = revision_pattern.search(text)
        down = down_pattern.search(text)
        assert revision, f"{path.name} declares no revision id"
        assert down, f"{path.name} declares no down_revision"
        revisions[revision.group(1)] = down.group(1)
    return revisions


def alembic_head() -> str:
    """The one revision nothing else revises. A branch or a cycle is a failure."""

    revisions = _alembic_revisions()
    assert revisions, "no Alembic revisions were discovered"
    revised = {down for down in revisions.values() if down is not None}
    heads = sorted(set(revisions) - revised)
    assert len(heads) == 1, f"Alembic history is not linear; heads = {heads}"
    for down in revised:
        assert down in revisions, f"down_revision {down} has no migration file"
    return heads[0]


def _extract(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"))
    assert match, f"{path.relative_to(REPO_ROOT)} does not declare a migration pin"
    return match.group(1)


def _client_pins() -> dict[str, str]:
    """Each entry is a file that fails closed against the wrong migration."""

    return {
        "ml/serving/postgres.py": _extract(
            REPO_ROOT / "ml" / "src" / "retail_ml" / "serving" / "postgres.py",
            r'MIGRATION_REVISION:\s*Final\[str\]\s*=\s*"([^"]+)"',
        ),
        "ml/publish/run_artifacts.py": _extract(
            REPO_ROOT / "ml" / "src" / "retail_ml" / "publish" / "run_artifacts.py",
            r'"servingMigration":\s*"([^"]+)"',
        ),
        "api/readmodel/forecast.go": _extract(
            REPO_ROOT / "api" / "internal" / "readmodel" / "forecast.go",
            r'ForecastMigrationRevision\s*=\s*"([^"]+)"',
        ),
        "db/tests/test_forecast_schema.py": _extract(
            REPO_ROOT / "db" / "tests" / "test_forecast_schema.py",
            r'assert cursor\.fetchone\(\) == \("([^"]+)",\)',
        ),
    }


def test_alembic_history_is_linear_with_one_head() -> None:
    assert alembic_head() == "0010_inventory_serving"


def test_the_required_head_is_not_a_retired_boundary() -> None:
    head = alembic_head()
    assert head not in RETIRED_HEADS, (
        f"{head} is inherited history, not the current required head; "
        "serving must pin the newest applied migration"
    )


def test_every_client_pin_matches_the_alembic_head() -> None:
    head = alembic_head()
    disagreeing = {
        name: pin for name, pin in _client_pins().items() if pin != head
    }
    assert not disagreeing, (
        f"migration pins disagree with the Alembic head {head}: {disagreeing}"
    )


def test_no_client_pin_regresses_to_a_retired_head() -> None:
    regressed = {
        name: pin for name, pin in _client_pins().items() if pin in RETIRED_HEADS
    }
    assert not regressed, f"client pins regressed to a retired head: {regressed}"


def test_the_closure_generator_derives_the_head_instead_of_declaring_one() -> None:
    """The generator is the one client that must NOT carry a string pin.

    It hard-coded `0007_activation_and_coverage` while every other client had
    moved to 0008, and because it generates the record, that one stale string
    republished itself on every regeneration. A generated artifact that
    hard-codes one of its own derived facts is the drift it exists to prevent.
    """

    source = (REPO_ROOT / "tools" / "build_closure_record.py").read_text(
        encoding="utf-8"
    )
    assert "_alembic_head()" in source, (
        "the closure generator must derive the required head from the migration graph"
    )
    literal_pins = re.findall(r'"servingMigration":\s*"([^"]+)"', source)
    assert not literal_pins, (
        f"the closure generator declares literal migration pins {literal_pins}; "
        "it must derive the head instead"
    )
    assert "_live_migration()" in source, (
        "the derived head must be confirmed against the applied database head"
    )


def test_the_generated_closure_record_names_the_required_head() -> None:
    record_path = REPO_ROOT / "contracts" / "evidence" / "forecast-closure-record.json"
    if not record_path.is_file():
        pytest.skip("closure record is not present")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["servingMigration"] == alembic_head(), (
        "the closure record names a migration the live stack has moved past; "
        "regenerate it with tools/dev.py closure-record"
    )
