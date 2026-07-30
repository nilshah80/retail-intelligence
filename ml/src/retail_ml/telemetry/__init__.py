"""MLflow telemetry that is never an artifact of record."""

from retail_ml.telemetry.mlflow import tracked_mlflow_run

__all__ = ["tracked_mlflow_run"]
