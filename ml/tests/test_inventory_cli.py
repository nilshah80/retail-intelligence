from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from retail_ml.inventory_run import cli


class _VerifiedBundle:
    def __init__(self, curated_root: Path) -> None:
        self.paths = SimpleNamespace(curated_root=curated_root)


class _Bundle:
    def __init__(self, curated_root: Path) -> None:
        self.curated_root = curated_root

    def verify(self) -> _VerifiedBundle:
        return _VerifiedBundle(self.curated_root)


def _args(tmp_path: Path, curated_root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        repository_root=tmp_path,
        expected_pin=tmp_path / "contracts/ml/expected-pin.json",
        curated_root=curated_root,
    )


def test_curated_root_comes_from_verified_input_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "ingestion/data/curated/run-current"
    expected.mkdir(parents=True)
    seen: dict[str, object] = {}

    def discover(repository_root: Path, *, expected_pin_path: Path) -> _Bundle:
        seen["repository_root"] = repository_root
        seen["expected_pin_path"] = expected_pin_path
        return _Bundle(expected)

    monkeypatch.setattr(cli, "discover_input_bundle", discover)

    assert cli._verified_curated_root(_args(tmp_path, expected)) == expected.resolve()
    assert seen == {
        "repository_root": tmp_path,
        "expected_pin_path": tmp_path / "contracts/ml/expected-pin.json",
    }


def test_curated_root_refuses_a_directory_outside_verified_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "ingestion/data/curated/run-current"
    requested = tmp_path / "ingestion/data/curated/run-other"
    expected.mkdir(parents=True)
    requested.mkdir(parents=True)
    monkeypatch.setattr(
        cli,
        "discover_input_bundle",
        lambda *_args, **_kwargs: _Bundle(expected),
    )

    with pytest.raises(SystemExit, match="does not match verified publication"):
        cli._verified_curated_root(_args(tmp_path, requested))


def _input_bundle() -> dict[str, str]:
    return {
        "sourceSnapshotId": "snapshot",
        "gateASemanticFingerprint": "gate-a",
        "gateBSemanticFingerprint": "gate-b",
        "publicationSemanticFingerprint": "publication",
    }


def _accepted_forecast_bundle(tmp_path: Path) -> SimpleNamespace:
    series_path = tmp_path / "forecast-series.parquet"
    acceptance_path = tmp_path / "forecast-acceptance.json"
    pd.DataFrame(
        [
            {
                "version_id": "fv_sparse",
                "sku_id": "gulf-india:sku-1",
                "store_id": "gulf-india:store-1",
                "channel_id": "gulf-india:online",
                "horizon_week": 1,
                "expected_units": 4.0,
                "yhat_p50": 4.0,
                "yhat_p90": 6.0,
                "confidence": 0.9,
            }
        ]
    ).to_parquet(series_path, index=False)
    acceptance_path.write_text(
        "{\n"
        '  "schemaVersion": "retail-forecast-acceptance/v6",\n'
        '  "coverageGateMode": "hard",\n'
        '  "passed": true\n'
        "}\n",
        encoding="utf-8",
    )
    return SimpleNamespace(
        lifecycle_status="accepted",
        manifest={
            "inputBundle": _input_bundle(),
            "decisionAsOf": "2026-07-31T18:30:00Z",
        },
        artifact_paths={
            "forecast_series": series_path,
            "forecast_acceptance": acceptance_path,
        },
        forecast_run_id="fr_sparse",
        semantic_fingerprint="forecast-fingerprint",
    )


def test_explicit_forecast_bundle_supplies_its_own_verified_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified = _accepted_forecast_bundle(tmp_path)
    monkeypatch.setattr(cli, "verify_forecast_run", lambda _path: verified)

    authority, series = cli._forecast_from_bundle(
        tmp_path, expected_input=_input_bundle()
    )

    assert authority == {
        "forecastRunId": "fr_sparse",
        "forecastVersionId": "fv_sparse",
        "runSemanticFingerprint": "forecast-fingerprint",
        "coverageGateMode": "hard",
        "acceptanceSchemaVersion": "retail-forecast-acceptance/v6",
        "decisionAsOf": "2026-07-31T18:30:00+00:00",
    }
    assert series.loc[0, "market_id"] == "gulf-india"
    assert bool(series.loc[0, "interval_available"]) is True


def test_inventory_decision_instant_defaults_to_exact_forecast_cutoff() -> None:
    resolved = cli._inventory_decision_instant(
        None,
        forecast={"decisionAsOf": "2026-07-31T18:30:00Z"},
    )

    assert resolved == datetime(2026, 7, 31, 18, 30, tzinfo=timezone.utc)


def test_explicit_inventory_decision_instant_can_be_independently_governed() -> None:
    resolved = cli._inventory_decision_instant(
        "2026-07-30T23:00:00+05:30",
        forecast={"decisionAsOf": "2026-07-31T18:30:00Z"},
    )

    assert resolved == datetime(2026, 7, 30, 17, 30, tzinfo=timezone.utc)


def test_inventory_decision_instant_refuses_a_naive_timestamp() -> None:
    with pytest.raises(SystemExit, match="timezone-aware"):
        cli._inventory_decision_instant(
            "2026-07-31T18:30:00",
            forecast={"decisionAsOf": "2026-07-31T18:30:00Z"},
        )


def test_explicit_forecast_bundle_refuses_a_different_input_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verified = _accepted_forecast_bundle(tmp_path)
    verified.manifest["inputBundle"]["publicationSemanticFingerprint"] = "other"
    monkeypatch.setattr(cli, "verify_forecast_run", lambda _path: verified)

    with pytest.raises(SystemExit, match="different pinned input lineage"):
        cli._forecast_from_bundle(tmp_path, expected_input=_input_bundle())
