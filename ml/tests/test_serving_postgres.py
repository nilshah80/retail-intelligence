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


def test_rejected_candidate_keeps_serving_fail_closed() -> None:
    """Governed NO-GO evidence: a rejected candidate cannot reach serving.

    The plan requires the same stateful gate on both closure branches. On the
    NO-GO branch this replaces the accepted-lineage assertions below: the
    rejected bundle must still verify, materialization must refuse it, and the
    active view must stay empty.
    """

    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    configured_run = os.environ.get("RETAIL_TEST_FORECAST_RUN")
    lifecycle = os.environ.get("RETAIL_TEST_FORECAST_LIFECYCLE", "accepted")
    if not dsn or not configured_run:
        pytest.skip("PostgreSQL forecast integration environment is not configured")
    if lifecycle == "accepted":
        pytest.skip("gate is running the accepted branch")
    run_path = Path(configured_run)
    if not run_path.is_dir():
        pytest.skip("rejected local forecast run is not present")

    import psycopg

    root = Path(__file__).parents[2]
    input_bundle = discover_input_bundle(root).verify()
    run = verify_forecast_run(run_path)
    assert run.lifecycle_status != "accepted"

    with pytest.raises(Exception, match="only an accepted forecast run"):
        materialize_forecast_run(run, input_bundle, postgres_dsn=dsn)

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM retail_serving.active_forecast_versions"
            )
            assert cursor.fetchone()[0] == 0
            cursor.execute(
                """
                SELECT count(*) FROM retail_serving.forecast_materializations
                WHERE forecast_run_id = %s
                """,
                (run.forecast_run_id,),
            )
            assert cursor.fetchone()[0] == 0


def test_accepted_forecast_postgres_materialization_integration() -> None:
    dsn = os.environ.get("RETAIL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("PostgreSQL forecast integration environment is not configured")
    configured_run = os.environ.get("RETAIL_TEST_FORECAST_RUN")
    if not configured_run:
        pytest.skip("accepted forecast-run integration artifact is not configured")
    if os.environ.get("RETAIL_TEST_FORECAST_LIFECYCLE", "accepted") != "accepted":
        pytest.skip("gate is running the governed NO-GO branch")
    root = Path(__file__).parents[2]
    run_path = Path(configured_run)
    if not run_path.is_dir():
        pytest.skip("accepted local forecast run is not present")

    input_bundle = discover_input_bundle(root).verify()
    run = verify_forecast_run(run_path)
    materialization = materialize_forecast_run(
        run,
        input_bundle,
        postgres_dsn=dsn,
    )
    assert materialization.row_counts["forecast_series"] == 52_884
    assert materialization.row_counts["forecast_series_dimensions"] == 2_232
    assert materialization.row_counts["forecast_eval_predictions"] == 708_708
    repeated_materialization = materialize_forecast_run(
        run,
        input_bundle,
        postgres_dsn=dsn,
    )
    assert repeated_materialization.already_materialized is True
    assert repeated_materialization.forecast_run_id == materialization.forecast_run_id

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
    repeated_activation = activate_forecast_version(
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
    assert repeated_activation.already_active is True
    assert repeated_activation.forecast_run_id == activation.forecast_run_id
