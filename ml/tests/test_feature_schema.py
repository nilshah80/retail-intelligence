import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.features.availability import (
    FUTURE_CALENDAR_COLUMNS,
    TARGET_AVAILABILITY_COLUMNS,
    TARGET_COLUMNS,
)
from retail_ml.features.build import (
    FEATURE_SCHEMA_VERSION,
    FEATURE_MANIFEST_VOLATILE_POINTERS,
    weekly_features_sql,
)
from retail_ml.models.forecasting import (
    _verified_feature_path,
    verified_backtest_artifacts,
)
from retail_ml.models.train_lgbm import (
    CATEGORICAL_FEATURES,
    MODEL_FEATURES,
    prepare_model_frame,
)


def test_weekly_feature_sql_has_full_horizon_and_channel_grain() -> None:
    sql = weekly_features_sql()

    assert len(TARGET_COLUMNS) == 26
    assert len(TARGET_AVAILABILITY_COLUMNS) == 26
    assert len(FUTURE_CALENDAR_COLUMNS) == 26
    assert "target_units_h26" in sql
    assert "target_known_as_of_h26" in sql
    assert "event_count_h26" not in sql
    assert "working_days_h26" in sql
    assert "PARTITION BY sku_id, store_id, channel_id" in sql


def test_model_feature_output_contains_no_absolute_currency_level() -> None:
    final_select = weekly_features_sql().split("selected_features AS (", maxsplit=1)[1]

    assert "observed_net_price" not in final_select.split("FROM feature_windows", maxsplit=1)[0]
    assert "price_ratio_13w" in final_select
    assert "local_category_price_index" in final_select


def test_calendar_event_snapshot_is_declared_unavailable_to_the_model() -> None:
    sql = weekly_features_sql()

    assert "greatest(max(calendar.known_as_of), max(events.known_as_of))" not in sql
    assert "calendar.event_count AS event_count_origin" in sql
    assert "working_days_known_as_of" in sql
    assert "calendar.working_days_known_as_of_h" in sql
    assert "<= features.week_end" in sql
    assert "round(local_category_price_index, 8)" in sql
    assert "round(weather_tavg_forecast_h1, 12)" in sql
    assert "round(weather_precip_forecast_h1, 12)" in sql
    assert "event_count_origin" in MODEL_FEATURES
    assert "event_count_horizon" not in MODEL_FEATURES
    assert "local_event_count_h1" not in sql
    assert "local_event_impact_h1" not in sql
    assert "disruption_demand_factor_h1" not in sql
    assert not {
        "local_event_count_horizon",
        "local_event_impact_horizon",
        "local_event_available_horizon",
        "disruption_demand_factor_horizon",
    } & set(MODEL_FEATURES)


def test_unavailable_future_calendar_events_cannot_change_the_model_matrix() -> None:
    base = {
        column: ["fixture"]
        for column in CATEGORICAL_FEATURES
    }
    without_events = pd.DataFrame(
        [{**{column: values[0] for column, values in base.items()}}]
    )
    without_events["event_count_origin"] = 2
    with_events = without_events.assign(
        event_count_horizon=999,
        local_event_count_horizon=3,
        local_event_impact_horizon=1.5,
        local_event_available_horizon=1,
        disruption_demand_factor_horizon=1.2,
    )
    categories = {
        column: ("fixture",)
        for column in CATEGORICAL_FEATURES
    }

    pd.testing.assert_frame_equal(
        prepare_model_frame(without_events, categories=categories),
        prepare_model_frame(with_events, categories=categories),
    )

    changed_origin = without_events.assign(event_count_origin=3)
    assert not prepare_model_frame(
        without_events,
        categories=categories,
    ).equals(
        prepare_model_frame(changed_origin, categories=categories)
    )


def _feature_fixture(tmp_path: Path) -> dict[str, object]:
    feature_path = tmp_path / "weekly_features.parquet"
    pd.DataFrame({"fixture": [1]}).to_parquet(feature_path, index=False)
    contents = feature_path.read_bytes()
    manifest: dict[str, object] = {
        "schemaVersion": FEATURE_SCHEMA_VERSION,
        "sourceInput": {},
        "featurePolicy": {
            "featureSqlSha256": hashlib.sha256(
                weekly_features_sql().encode("utf-8")
            ).hexdigest(),
            "allNullFeatureColumns": [],
        },
        "stats": {"feature_rows": 1},
        "objects": {
            "weeklyFeatures": {
                "path": feature_path.name,
                "bytes": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        },
        "executionProfile": {"profile": "safe"},
        "outputPath": str(tmp_path),
        "createdAt": "2026-07-30T00:00:00Z",
    }
    manifest["semanticFingerprint"] = semantic_fingerprint(
        manifest,
        volatile_pointers=FEATURE_MANIFEST_VOLATILE_POINTERS,
    )
    return manifest


def test_feature_consumer_rejects_manifest_changed_after_signing(
    tmp_path: Path,
) -> None:
    manifest = _feature_fixture(tmp_path)
    manifest["stats"] = {"feature_rows": 2}
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="semantic identity does not match",
    ):
        _verified_feature_path(tmp_path)


def test_feature_consumer_rejects_resigned_unknown_sql_policy(
    tmp_path: Path,
) -> None:
    manifest = _feature_fixture(tmp_path)
    manifest["featurePolicy"] = {"featureSqlSha256": "0" * 64}
    manifest.pop("semanticFingerprint")
    manifest["semanticFingerprint"] = semantic_fingerprint(
        manifest,
        volatile_pointers=FEATURE_MANIFEST_VOLATILE_POINTERS,
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="semantic identity does not match",
    ):
        _verified_feature_path(tmp_path)


def test_feature_fingerprint_binds_the_parquet_descriptor(
    tmp_path: Path,
) -> None:
    manifest = _feature_fixture(tmp_path)
    manifest["objects"]["weeklyFeatures"]["sha256"] = "f" * 64
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="semantic identity does not match",
    ):
        _verified_feature_path(tmp_path)


def test_feature_consumer_rejects_resigned_all_null_column(
    tmp_path: Path,
) -> None:
    manifest = _feature_fixture(tmp_path)
    feature_path = tmp_path / "weekly_features.parquet"
    pd.DataFrame({"fixture": [None]}).to_parquet(feature_path, index=False)
    contents = feature_path.read_bytes()
    descriptor = manifest["objects"]["weeklyFeatures"]
    descriptor["bytes"] = len(contents)
    descriptor["sha256"] = hashlib.sha256(contents).hexdigest()
    manifest.pop("semanticFingerprint")
    manifest["semanticFingerprint"] = semantic_fingerprint(
        manifest,
        volatile_pointers=FEATURE_MANIFEST_VOLATILE_POINTERS,
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="structurally all-null columns: fixture"):
        _verified_feature_path(tmp_path)


def test_backtest_consumer_rejects_mutated_publisher_input(
    tmp_path: Path,
) -> None:
    feature_manifest = {"semanticFingerprint": "a" * 64}
    objects: dict[str, dict[str, object]] = {}
    for name, contents in {
        "forecast_eval_predictions.parquet": b"evaluation",
        # The ragged recent schedule joined the frozen contract with the
        # forecast-versus-actual horizon fix; a bundle without it is rejected on
        # the object SET, which would mask the per-object tamper this asserts.
        "forecast_eval_recent.parquet": b"recent",
        "forecast_calibration.parquet": b"calibration",
        "acceptance.json": b"{}\n",
        # Decision #84 added the fitted blend weights to the frozen contract.
        "cold_start_blend_model.json": b"{}\n",
    }.items():
        path = tmp_path / name
        path.write_bytes(contents)
        objects[name] = {
            "bytes": len(contents),
            "sha256": hashlib.sha256(contents).hexdigest(),
        }
    (tmp_path / "backtest-manifest.json").write_text(
        json.dumps(
            {
                "schemaVersion": "retail-forecast-backtest/v1",
                "featureSemanticFingerprint": "a" * 64,
                "objects": objects,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "acceptance.json").write_text('{"forged":true}\n', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match="backtest object does not match its manifest",
    ):
        verified_backtest_artifacts(
            tmp_path,
            feature_manifest=feature_manifest,
        )
