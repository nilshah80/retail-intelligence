"""MLflow telemetry with HTTP-server and local-file compatibility."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import mlflow


@contextmanager
def tracked_mlflow_run(
    tracking_uri: str | Path,
    *,
    experiment_name: str,
    run_name: str,
    parameters: dict[str, Any],
) -> Iterator[str]:
    raw_uri = str(tracking_uri)
    parsed = urlparse(raw_uri)
    is_remote = parsed.scheme in {"http", "https", "databricks"}
    previous_file_store = os.environ.get("MLFLOW_ALLOW_FILE_STORE")
    if is_remote:
        resolved_uri = raw_uri
    else:
        root = Path(parsed.path if parsed.scheme == "file" else raw_uri).resolve()
        root.mkdir(parents=True, exist_ok=True)
        resolved_uri = root.as_uri()
        os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    try:
        mlflow.set_tracking_uri(resolved_uri)
        mlflow.set_experiment(experiment_name)
        with mlflow.start_run(run_name=run_name) as active:
            mlflow.log_params(
                {
                    key: (
                        ",".join(str(item) for item in value)
                        if isinstance(value, (list, tuple))
                        else value
                    )
                    for key, value in parameters.items()
                }
            )
            yield active.info.run_id
    finally:
        if not is_remote:
            if previous_file_store is None:
                os.environ.pop("MLFLOW_ALLOW_FILE_STORE", None)
            else:
                os.environ["MLFLOW_ALLOW_FILE_STORE"] = previous_file_store


def log_metrics(metrics: dict[str, float], *, step: int | None = None) -> None:
    mlflow.log_metrics(metrics, step=step)


def log_artifact(path: str | Path) -> None:
    mlflow.log_artifact(str(Path(path).resolve()))


__all__ = ["log_artifact", "log_metrics", "tracked_mlflow_run"]
