"""The API smoke harness must refuse before it is trusted (P4-8 task 14).

`tools/inventory_api_smoke.py` is the evidence generator, so a bug in it produces
a clean-looking record over a broken API -- which is worse than no record at all.
These tests drive it with stubbed responses and assert that each binding actually
refuses. Nothing here touches the network or PostgreSQL.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _module():
    spec = importlib.util.spec_from_file_location(
        "inventory_api_smoke", REPO_ROOT / "tools" / "inventory_api_smoke.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["inventory_api_smoke"] = module
    spec.loader.exec_module(module)
    return module


SMOKE = _module()

ACTIVE = {
    "inventoryVersionId": "iv_0123456789abcdef",
    "inventoryRunId": "ir_0123456789abcdef",
    "semanticFingerprint": "a" * 64,
    "sourceSelectionId": "sel_2d3c5e156bedabd4",
    "forecastAuthority": {
        "forecastRunId": "fr_0123456789abcdef",
        "forecastVersionId": "fv_0123456789abcdef",
    },
    "policyVersion": "inventory-policy/2.0.0",
    "markets": ["india-west", "us-new-york"],
}


def _served(**overrides: Any) -> dict[str, Any]:
    body = {
        "schemaVersion": "retail-inventory-positions/v1",
        "dataMode": "live",
        "inventoryRunId": ACTIVE["inventoryRunId"],
        "inventoryVersionId": ACTIVE["inventoryVersionId"],
        "semanticFingerprint": ACTIVE["semanticFingerprint"],
        "forecastAuthority": dict(ACTIVE["forecastAuthority"]),
        "policyVersion": ACTIVE["policyVersion"],
        "markets": list(ACTIVE["markets"]),
        "items": [{"marketId": "india-west"}],
    }
    body.update(overrides)
    return body


def _run(monkeypatch, *, identity, responses):
    """Drive smoke() with stubbed HTTP and a stubbed active identity."""

    monkeypatch.setattr(SMOKE, "active_identity", lambda _dsn: identity)

    def fetch(_base: str, path: str) -> tuple[int, dict[str, Any]]:
        return responses(path)

    monkeypatch.setattr(SMOKE, "_fetch", fetch)
    return SMOKE.smoke("http://api.test", "postgresql://stub")


# -- the unavailable branch ----------------------------------------------------

def test_all_fifteen_returning_the_governed_503_is_valid_evidence(
    monkeypatch,
) -> None:
    record = _run(
        monkeypatch,
        identity=None,
        responses=lambda _p: (503, {"reasonCode": "INVENTORY_READ_MODEL_UNAVAILABLE"}),
    )
    assert record["state"] == "unavailable_no_active_bundle"
    assert record["routeCount"] == 15
    assert {entry["status"] for entry in record["routes"]} == {503}


def test_a_200_with_no_active_bundle_is_refused(monkeypatch) -> None:
    """Serving rows nothing activated is the worst possible outcome here: the
    screen looks correct and no record says which bundle produced it."""

    with pytest.raises(SMOKE.SmokeError, match="governed status is 503"):
        _run(monkeypatch, identity=None, responses=lambda _p: (200, _served()))


def test_an_unavailable_body_that_leaks_identity_is_refused(monkeypatch) -> None:
    """'Withheld' and 'absent' are different facts and only one is true.

    A 503 carrying the run id it declined to serve tells a caller that a version
    exists and is being held back, which would send somebody looking for a
    permission problem that does not exist.
    """

    with pytest.raises(SMOKE.SmokeError, match="leaks"):
        _run(
            monkeypatch,
            identity=None,
            responses=lambda _p: (
                503,
                {"reasonCode": "X", "inventoryRunId": "ir_0123456789abcdef"},
            ),
        )


# -- the live branch -----------------------------------------------------------

def test_a_matching_envelope_on_every_route_is_valid_evidence(
    monkeypatch,
) -> None:
    record = _run(
        monkeypatch, identity=ACTIVE, responses=lambda _p: (200, _served())
    )
    assert record["state"] == "live"
    assert record["activeIdentity"] == ACTIVE
    assert all(entry["rows"] == 1 for entry in record["routes"])


def test_an_envelope_naming_a_different_version_is_refused(monkeypatch) -> None:
    """The check that catches a stale activation. Without it, old rows served
    under a new activation would pass as cleanly as correct ones."""

    with pytest.raises(SMOKE.SmokeError, match="inventoryVersionId is"):
        _run(
            monkeypatch,
            identity=ACTIVE,
            responses=lambda _p: (
                200,
                _served(inventoryVersionId="iv_beefbeefbeefbeef"),
            ),
        )


def test_an_envelope_naming_a_different_forecast_is_refused(monkeypatch) -> None:
    with pytest.raises(SMOKE.SmokeError, match="forecastAuthority"):
        _run(
            monkeypatch,
            identity=ACTIVE,
            responses=lambda _p: (
                200,
                _served(
                    forecastAuthority={
                        "forecastRunId": "fr_beefbeefbeefbeef",
                        "forecastVersionId": "fv_beefbeefbeefbeef",
                    }
                ),
            ),
        )


def test_a_response_not_marked_live_is_refused(monkeypatch) -> None:
    """A served row that is not marked live is a row nobody can place."""

    with pytest.raises(SMOKE.SmokeError, match="dataMode"):
        _run(
            monkeypatch,
            identity=ACTIVE,
            responses=lambda _p: (200, _served(dataMode="sample")),
        )


def test_a_mixed_result_is_refused_rather_than_partially_recorded(
    monkeypatch,
) -> None:
    """Fourteen serving and one 503 means the fifteen do not share one authority.

    A partial pass would leave nobody able to say which screens are trustworthy,
    which is the same reason bundle verification has no partial pass either.
    """

    def responses(path: str) -> tuple[int, dict[str, Any]]:
        if path == "/api/v1/replenishment/exceptions":
            return 503, {"reasonCode": "INVENTORY_READ_MODEL_UNAVAILABLE"}
        return 200, _served()

    with pytest.raises(SMOKE.SmokeError, match="mixed statuses"):
        _run(monkeypatch, identity=ACTIVE, responses=responses)


def test_two_active_rows_is_refused(monkeypatch) -> None:
    """P4-D15 allows one active bundle; the smoke tool must not average two."""

    class Cursor:
        def execute(self, *_args: Any) -> None:
            pass

        def fetchall(self) -> list[tuple[Any, ...]]:
            row = (
                "iv_a", "ir_a", "a" * 64, "sel_a", "fr_a", "fv_a",
                "inventory-policy/2.0.0", ["india-west"],
            )
            return [row, row]

        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

    class Connection:
        def cursor(self):
            return Cursor()

        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            pass

    fake = type("psycopg", (), {"connect": staticmethod(lambda _dsn: Connection())})
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    with pytest.raises(SMOKE.SmokeError, match="P4-D15 allows one"):
        SMOKE.active_identity("postgresql://stub")


# -- the route list itself -----------------------------------------------------

def test_the_route_list_matches_the_go_handler(monkeypatch) -> None:
    """One list of fifteen paths in Go and another in Python, with nothing
    comparing them, is how a route stops being smoke-tested silently."""

    source = (
        REPO_ROOT / "api" / "internal" / "httpapi" / "inventory.go"
    ).read_text(encoding="utf-8")
    declared = source.split("inventoryPaths = []string{", 1)[1].split("}", 1)[0]
    go_paths = [
        line.strip().strip(",").strip('"')
        for line in declared.splitlines()
        if line.strip().startswith('"')
    ]
    assert go_paths == list(SMOKE.ROUTES)
