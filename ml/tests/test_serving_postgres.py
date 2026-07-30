from __future__ import annotations

import os
from pathlib import Path

import pytest

from retail_ml.io.bundle import discover_input_bundle
from retail_ml.publish.verify import verify_forecast_run
from retail_ml.serving.postgres import (
    activate_forecast_version,
    materialize_forecast_run,
)


def test_accepted_forecast_postgres_materialization_integration() -> None:
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL forecast integration environment is not configured")
    root = Path(__file__).parents[2]
    run_path = Path(
        os.environ.get(
            "RETAIL_TEST_FORECAST_RUN",
            root
            / "ml"
            / "data"
            / "artifacts"
            / "forecast_run_accepted_db3784fdcc4cb833_v12",
        )
    )
    if not run_path.is_dir():
        pytest.skip("accepted local forecast run is not present")

    input_bundle = discover_input_bundle(root).verify()
    run = verify_forecast_run(run_path)
    materialization = materialize_forecast_run(
        run,
        input_bundle,
        postgres_dsn=dsn,
    )
    assert materialization.already_materialized is True
    assert materialization.row_counts["forecast_series"] == 52_884
    assert materialization.row_counts["forecast_series_dimensions"] == 2_232
    assert materialization.row_counts["forecast_eval_predictions"] == 708_708

    activation = activate_forecast_version(
        postgres_dsn=dsn,
        forecast_run_id=materialization.forecast_run_id,
        activation_scope_fingerprint=(
            materialization.activation_scope_fingerprint
        ),
        expected_publication_fingerprint=(
            input_bundle.publication_semantic_fingerprint
        ),
        actor="phase3-integration-test",
    )
    assert activation.already_active is True
