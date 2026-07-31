"""Cross-platform Phase-3 ML entry point."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from retail_ml.bench.memory_spike import run_memory_spike
from retail_ml.features.build import build_features
from retail_ml.features.characterize import characterize_features
from retail_ml.io.bundle import discover_input_bundle
from retail_ml.models.drivers import aggregate_driver_rows
from retail_ml.models.current_cycle import run_current_cycle
from retail_ml.models.forecasting import (
    _verified_feature_path,
    run_backtest,
    verified_backtest_artifacts,
)
from retail_ml.policies.classification import (
    classify_current_cycle,
    load_classification_policy,
)
from retail_ml.publish.run_artifacts import publish_forecast_run
from retail_ml.publish.verify import verify_forecast_run
from retail_ml.runtime.profile import resolve_ml_runtime_profile
from retail_ml.serving.postgres import (
    activate_forecast_version,
    materialize_forecast_run,
)


def _command_verify(args: argparse.Namespace) -> int:
    verified = discover_input_bundle(
        args.repository_root,
        expected_pin_path=args.expected_pin,
    ).verify()
    print(json.dumps(verified.identity, indent=2, sort_keys=True))
    return 0


def _command_features(args: argparse.Namespace) -> int:
    bundle = discover_input_bundle(
        args.repository_root,
        expected_pin_path=args.expected_pin,
    ).verify()
    stats, output = build_features(
        bundle,
        args.output_dir,
        runtime_profile=resolve_ml_runtime_profile(args.execution_profile),
    )
    print(
        json.dumps(
            {"output": str(output), "stats": asdict(stats)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _command_characterize(args: argparse.Namespace) -> int:
    result = characterize_features(
        args.feature_dir,
        args.report,
        replace=args.replace,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _command_bench(args: argparse.Namespace) -> int:
    result = run_memory_spike(args.repository_root, args.report)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "pass" else 1


def _command_backtest(args: argparse.Namespace) -> int:
    horizons = tuple(
        int(value)
        for token in args.horizons.split(",")
        for value in [token.strip()]
        if value
    )
    stats = run_backtest(
        args.feature_dir,
        args.output_dir,
        runtime_profile=resolve_ml_runtime_profile(args.execution_profile),
        tracking_uri=args.tracking_uri,
        horizons=horizons,
        origin_count=args.origin_count,
    )
    print(json.dumps(asdict(stats), indent=2, sort_keys=True))
    return 0


def _command_score_current(args: argparse.Namespace) -> int:
    bundle = discover_input_bundle(
        args.repository_root,
        expected_pin_path=args.expected_pin,
    ).verify()
    stats = run_current_cycle(
        args.feature_dir,
        args.output_dir,
        verified_bundle=bundle,
        decision_as_of=datetime.fromisoformat(
            args.decision_as_of.replace("Z", "+00:00")
        ),
        runtime_profile=resolve_ml_runtime_profile(args.execution_profile),
        blend_model_path=args.blend_model,
    )
    print(json.dumps(asdict(stats), indent=2, sort_keys=True))
    return 0


def _command_drivers(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"driver output already exists: {output}")
    evaluation = pd.read_parquet(args.evaluation)
    drivers = aggregate_driver_rows(
        evaluation,
        include_series=not args.portfolio_only,
    )
    if args.version_id:
        drivers.insert(0, "version_id", args.version_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    drivers.to_parquet(output, index=False)
    print(
        json.dumps(
            {"output": str(output), "rows": len(drivers)},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _command_classify(args: argparse.Namespace) -> int:
    output = args.output_dir.resolve()
    if output.exists():
        raise FileExistsError(f"classification output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.",
            dir=output.parent,
        )
    )
    try:
        policy = load_classification_policy(args.policy)
        exceptions, data_quality, bindings = classify_current_cycle(
            pd.read_parquet(args.current_cycle),
            decision_as_of=datetime.fromisoformat(
                args.decision_as_of.replace("Z", "+00:00")
            ),
            policy=policy,
        )
        exceptions.to_parquet(
            staging / "forecast_exceptions.parquet",
            index=False,
        )
        data_quality.to_parquet(
            staging / "forecast_data_quality.parquet",
            index=False,
        )
        (staging / "classification-policies.json").write_text(
            json.dumps(bindings, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(staging, output)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    print(
        json.dumps(
            {
                "dataQualityRows": len(data_quality),
                "exceptionRows": len(exceptions),
                "output": str(output),
                "policies": bindings,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _command_publish(args: argparse.Namespace) -> int:
    backtest_dir = args.backtest_dir.resolve()
    _, feature_manifest = _verified_feature_path(args.feature_dir.resolve())
    backtest_manifest, backtest_paths = verified_backtest_artifacts(
        backtest_dir,
        feature_manifest=feature_manifest,
    )
    acceptance = json.loads(
        backtest_paths["acceptance.json"].read_text(encoding="utf-8")
    )
    classification_policies = json.loads(
        args.classification_policies.read_text(encoding="utf-8")
    )
    decision_as_of = datetime.fromisoformat(
        args.decision_as_of.replace("Z", "+00:00")
    )
    # Decision #84/#86 provenance. Read from the accepted backtest so the published
    # manifest carries the exact estimator that was scored, and so a bundle cannot
    # claim a remediation class without the weights that justify it.
    blend_path = Path(args.backtest_dir) / "cold_start_blend_model.json"
    remediation = (
        json.loads(blend_path.read_text(encoding="utf-8"))
        if blend_path.is_file()
        else None
    )
    publication = publish_forecast_run(
        pd.read_parquet(backtest_paths["forecast_eval_predictions.parquet"]),
        pd.read_parquet(backtest_paths["forecast_calibration.parquet"]),
        acceptance,
        pd.read_parquet(args.exceptions),
        pd.read_parquet(args.data_quality),
        args.output_dir,
        current_forecasts=pd.read_parquet(args.current_forecasts),
        classification_policies=classification_policies,
        input_bundle=feature_manifest["sourceInput"],
        feature_semantic_fingerprint=feature_manifest["semanticFingerprint"],
        decision_as_of=decision_as_of,
        runtime_profile=resolve_ml_runtime_profile(args.execution_profile),
        stage_telemetry=backtest_manifest.get(
            "stageTelemetry",
            backtest_manifest["stats"],
        ),
        mlflow_run_id=backtest_manifest.get("mlflowRunId"),
        remediation=remediation,
    )
    print(json.dumps(asdict(publication), indent=2, sort_keys=True))
    return 0


def _postgres_dsn(args: argparse.Namespace) -> str:
    value = args.postgres_dsn or os.environ.get("RETAIL_POSTGRES_DSN")
    if not value:
        raise RuntimeError(
            "PostgreSQL DSN is required through --postgres-dsn or RETAIL_POSTGRES_DSN"
        )
    return str(value)


def _command_materialize_serving(args: argparse.Namespace) -> int:
    input_bundle = discover_input_bundle(
        args.repository_root,
        expected_pin_path=args.expected_pin,
    ).verify()
    run = verify_forecast_run(args.forecast_run)
    result = materialize_forecast_run(
        run,
        input_bundle,
        postgres_dsn=_postgres_dsn(args),
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def _command_activate_serving(args: argparse.Namespace) -> int:
    input_bundle = discover_input_bundle(
        args.repository_root,
        expected_pin_path=args.expected_pin,
    ).verify()
    result = activate_forecast_version(
        postgres_dsn=_postgres_dsn(args),
        forecast_run_id=args.forecast_run_id,
        activation_scope_fingerprint=args.activation_scope_fingerprint,
        expected_publication_fingerprint=(
            input_bundle.publication_semantic_fingerprint
        ),
        actor=args.actor,
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0


def _command_not_landed(args: argparse.Namespace) -> int:
    raise SystemExit(
        f"{args.command} is a declared Phase-3 command but its workstream has not landed yet"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--repository-root", type=Path, default=Path.cwd())
    verify.add_argument("--expected-pin", type=Path, default=None)
    verify.set_defaults(handler=_command_verify)

    features = subparsers.add_parser("features")
    features.add_argument("--repository-root", type=Path, default=Path.cwd())
    features.add_argument("--expected-pin", type=Path, default=None)
    features.add_argument("--output-dir", type=Path, required=True)
    features.add_argument(
        "--execution-profile",
        choices=("safe", "balanced", "performance", "ultra-performance"),
        default="safe",
    )
    features.set_defaults(handler=_command_features)

    characterize = subparsers.add_parser("characterize")
    characterize.add_argument("--feature-dir", type=Path, required=True)
    characterize.add_argument("--report", type=Path, required=True)
    characterize.add_argument("--replace", action="store_true")
    characterize.set_defaults(handler=_command_characterize)

    bench = subparsers.add_parser("bench")
    bench.add_argument("--repository-root", type=Path, default=Path.cwd())
    bench.add_argument("--report", type=Path, required=True)
    bench.set_defaults(handler=_command_bench)

    backtest = subparsers.add_parser("backtest")
    backtest.add_argument("--feature-dir", type=Path, required=True)
    backtest.add_argument("--output-dir", type=Path, required=True)
    backtest.add_argument(
        "--tracking-uri",
        "--tracking-root",
        dest="tracking_uri",
        default=os.environ.get("MLFLOW_TRACKING_URI"),
        required=os.environ.get("MLFLOW_TRACKING_URI") is None,
        help="MLflow HTTP URI or local file-store path",
    )
    backtest.add_argument("--horizons", default=",".join(str(value) for value in range(1, 27)))
    backtest.add_argument("--origin-count", type=int, default=13)
    backtest.add_argument(
        "--execution-profile",
        choices=("safe", "balanced", "performance", "ultra-performance"),
        default="safe",
    )
    backtest.set_defaults(handler=_command_backtest)

    score_current = subparsers.add_parser("score-current")
    score_current.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    score_current.add_argument("--expected-pin", type=Path, default=None)
    score_current.add_argument("--feature-dir", type=Path, required=True)
    score_current.add_argument("--output-dir", type=Path, required=True)
    score_current.add_argument("--decision-as-of", required=True)
    score_current.add_argument(
        "--blend-model",
        type=Path,
        default=None,
        help=(
            "decision #84 cold_start_blend_model.json from the accepted backtest. "
            "Required to serve the estimator the acceptance gate scored."
        ),
    )
    score_current.add_argument(
        "--execution-profile",
        choices=("safe", "balanced", "performance", "ultra-performance"),
        default="safe",
    )
    score_current.set_defaults(handler=_command_score_current)

    drivers = subparsers.add_parser("drivers")
    drivers.add_argument("--evaluation", type=Path, required=True)
    drivers.add_argument("--output", type=Path, required=True)
    drivers.add_argument("--version-id", default=None)
    drivers.add_argument("--portfolio-only", action="store_true")
    drivers.set_defaults(handler=_command_drivers)

    classify = subparsers.add_parser("classify")
    classify.add_argument("--current-cycle", type=Path, required=True)
    classify.add_argument("--output-dir", type=Path, required=True)
    classify.add_argument("--decision-as-of", required=True)
    classify.add_argument("--policy", type=Path, default=None)
    classify.set_defaults(handler=_command_classify)

    publish = subparsers.add_parser("publish")
    publish.add_argument("--feature-dir", type=Path, required=True)
    publish.add_argument("--backtest-dir", type=Path, required=True)
    publish.add_argument("--exceptions", type=Path, required=True)
    publish.add_argument("--data-quality", type=Path, required=True)
    publish.add_argument("--classification-policies", type=Path, required=True)
    publish.add_argument("--current-forecasts", type=Path, required=True)
    publish.add_argument("--output-dir", type=Path, required=True)
    publish.add_argument("--decision-as-of", required=True)
    publish.add_argument(
        "--execution-profile",
        choices=("safe", "balanced", "performance", "ultra-performance"),
        default="safe",
    )
    publish.set_defaults(handler=_command_publish)

    materialize = subparsers.add_parser("materialize-serving")
    materialize.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    materialize.add_argument("--expected-pin", type=Path, default=None)
    materialize.add_argument("--forecast-run", type=Path, required=True)
    materialize.add_argument("--postgres-dsn", default=None)
    materialize.set_defaults(handler=_command_materialize_serving)

    activate = subparsers.add_parser("activate-serving")
    activate.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd(),
    )
    activate.add_argument("--expected-pin", type=Path, default=None)
    activate.add_argument("--forecast-run-id", required=True)
    activate.add_argument("--activation-scope-fingerprint", required=True)
    activate.add_argument("--actor", required=True)
    activate.add_argument("--postgres-dsn", default=None)
    activate.set_defaults(handler=_command_activate_serving)

    for name in ("train", "run"):
        future = subparsers.add_parser(name)
        future.set_defaults(handler=_command_not_landed)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
