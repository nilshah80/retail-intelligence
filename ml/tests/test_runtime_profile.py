from retail_ml.runtime.profile import model_worker_budget, resolve_ml_runtime_profile
from retail_ml.runtime.telemetry import MLStageTelemetry


def test_ml_profile_binds_all_shared_fields() -> None:
    profile = resolve_ml_runtime_profile("balanced", environment={})

    assert profile.feature_workers == 4
    assert profile.fold_workers == 2
    assert profile.model_workers == 2
    assert profile.threads_per_model == 2
    assert profile.memory_limit_gb == 12
    assert profile.as_manifest_dict()["affectsRunIdentity"] is False


def test_ml_environment_overrides_are_resolved_by_shared_package() -> None:
    profile = resolve_ml_runtime_profile(
        "safe",
        environment={
            "RETAIL_ML_FEATURE_WORKERS": "3",
            "RETAIL_ML_FOLD_WORKERS": "2",
            "RETAIL_ML_MODEL_WORKERS": "2",
            "RETAIL_ML_THREADS_PER_MODEL": "1",
            "RETAIL_ML_MEMORY_LIMIT_GB": "16",
        },
    )

    assert profile.feature_workers == 3
    assert profile.fold_workers == 2
    assert profile.model_workers == 2
    assert profile.threads_per_model == 1
    assert profile.memory_limit_gb == 16


def test_nested_model_workers_are_bounded_by_cpu_and_memory() -> None:
    profile = resolve_ml_runtime_profile("ultra-performance", environment={})
    assert model_worker_budget(profile, logical_cpu_count=8) == 2


def test_stage_telemetry_labels_sampled_rss_honestly() -> None:
    telemetry = MLStageTelemetry()
    with telemetry.measure("fixture"):
        values = [index for index in range(100)]
    snapshot = telemetry.snapshot()

    assert len(values) == 100
    assert snapshot["rssMeasurement"] in {
        "sampled_at_stage_boundaries_process_tree",
        "sampled_at_stage_boundaries_process_only",
    }
    assert snapshot["maxSampledRssBytes"] > 0
    assert snapshot["stages"]["fixture"]["calls"] == 1
