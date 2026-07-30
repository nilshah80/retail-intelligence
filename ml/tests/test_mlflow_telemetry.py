from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace

from retail_ml.telemetry import mlflow as telemetry


def _patch_mlflow(monkeypatch, observed: dict[str, object]) -> None:
    monkeypatch.setattr(
        telemetry.mlflow,
        "set_tracking_uri",
        lambda value: observed.__setitem__("uri", value),
    )
    monkeypatch.setattr(telemetry.mlflow, "set_experiment", lambda value: None)
    monkeypatch.setattr(telemetry.mlflow, "log_params", lambda value: None)

    @contextmanager
    def fake_start_run(*, run_name: str):
        observed["run_name"] = run_name
        yield SimpleNamespace(info=SimpleNamespace(run_id="run-id"))

    monkeypatch.setattr(telemetry.mlflow, "start_run", fake_start_run)


def test_remote_mlflow_uri_is_not_treated_as_a_file(
    monkeypatch,
) -> None:
    observed: dict[str, object] = {}
    _patch_mlflow(monkeypatch, observed)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)

    with telemetry.tracked_mlflow_run(
        "http://127.0.0.1:5000",
        experiment_name="experiment",
        run_name="remote-run",
        parameters={},
    ) as run_id:
        assert run_id == "run-id"

    assert observed["uri"] == "http://127.0.0.1:5000"
    assert "MLFLOW_ALLOW_FILE_STORE" not in os.environ


def test_local_mlflow_path_remains_supported(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}
    _patch_mlflow(monkeypatch, observed)
    monkeypatch.delenv("MLFLOW_ALLOW_FILE_STORE", raising=False)
    tracking_root = tmp_path / "mlruns"

    with telemetry.tracked_mlflow_run(
        tracking_root,
        experiment_name="experiment",
        run_name="local-run",
        parameters={},
    ):
        assert os.environ["MLFLOW_ALLOW_FILE_STORE"] == "true"

    assert observed["uri"] == tracking_root.resolve().as_uri()
    assert tracking_root.is_dir()
    assert "MLFLOW_ALLOW_FILE_STORE" not in os.environ
