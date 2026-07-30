#!/usr/bin/env python3
"""Cross-platform developer entry point for the monorepo.

This file is authoritative; the root Makefile is a short POSIX convenience
wrapper. Every subprocess is invoked with an argument list, every path uses
``pathlib``, and virtual-environment executables resolve correctly on Windows.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parent.parent
INGESTION_ENV = REPO_ROOT / "ingestion" / ".venv"
ML_ENV = REPO_ROOT / "ml" / ".venv"
DATAGEN_ENV = REPO_ROOT / "datagen" / ".venv"
DB_ENV = REPO_ROOT / "db" / ".venv"
COMPOSE_FILE = REPO_ROOT / "deploy" / "compose.yaml"
COMPOSE_ENV = REPO_ROOT / "deploy" / ".env"
COMPOSE_ENV_EXAMPLE = REPO_ROOT / "deploy" / ".env.example"
ACCEPTANCE_EVALUATION_VERSION = (
    "paired-seasonal-complete-recomputation/v3"
)


def venv_python(root: Path) -> Path:
    return (
        root / "Scripts" / "python.exe"
        if os.name == "nt"
        else root / "bin" / "python"
    )


def _run(
    args: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str] | None = None,
) -> int:
    return subprocess.run(args, cwd=cwd, env=env, check=False).returncode


def _require_python(root: Path, label: str) -> Path:
    python = venv_python(root)
    if not python.is_file():
        raise RuntimeError(
            f"{label} environment is missing at {root}. "
            f"Run {Path(sys.executable).name} tools/dev.py envs first."
        )
    return python


def _create_environment(
    root: Path,
    editable: list[str],
    *,
    interpreter: Path | None = None,
    clear: bool = True,
    install_shared: bool = True,
) -> None:
    if interpreter is None or interpreter.resolve() == Path(sys.executable).resolve():
        venv.EnvBuilder(with_pip=True, clear=clear).create(root)
    else:
        venv_command = [str(interpreter), "-m", "venv"]
        if clear:
            venv_command.append("--clear")
        venv_command.append(str(root))
        if _run(venv_command):
            raise RuntimeError(f"failed to create environment with {interpreter}")
    python = venv_python(root)
    commands = [
        [str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
    ]
    if install_shared:
        commands.append([
            str(python),
            "-m",
            "pip",
            "install",
            "--editable",
            str(REPO_ROOT / "execution"),
            "--editable",
            str(REPO_ROOT / "contracts" / "python"),
        ])
    commands.append([
            str(python),
            "-m",
            "pip",
            "install",
            *sum(
                (
                    ["--editable", str(REPO_ROOT / item)]
                    for item in editable
                ),
                [],
            ),
        ])
    for command in commands:
        if _run(command):
            raise RuntimeError(f"environment command failed: {command!r}")


def _ml_python() -> Path:
    """Select the supported Python 3.12/3.13 ML interpreter explicitly."""

    candidates: list[Path] = []
    override = os.environ.get("RETAIL_ML_PYTHON")
    if override:
        candidates.append(Path(override))
    for name in ("python3.13", "python3.12"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(Path(resolved))
    candidates.append(Path(sys.executable))

    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        probe = subprocess.run(
            [
                str(resolved),
                "-c",
                (
                    "import sys; "
                    "raise SystemExit(0 if (3, 12) <= sys.version_info[:2] < (3, 14) else 1)"
                ),
            ],
            check=False,
        )
        if probe.returncode == 0:
            return resolved
    raise RuntimeError(
        "Phase 3 ML requires Python 3.12 or 3.13 because the pinned MLflow/pandas "
        "stack does not support Python 3.14. Set RETAIL_ML_PYTHON to that interpreter."
    )


def command_envs(_: argparse.Namespace) -> int:
    _create_environment(
        DATAGEN_ENV,
        ["datagen[dev]"],
        clear=False,
        install_shared=False,
    )
    _create_environment(INGESTION_ENV, ["ingestion[dev]"])
    _create_environment(ML_ENV, ["ml[dev]"], interpreter=_ml_python())
    _create_environment(DB_ENV, ["db[dev]"], interpreter=_ml_python())
    return 0


def command_db_env(_: argparse.Namespace) -> int:
    _create_environment(DB_ENV, ["db[dev]"], interpreter=_ml_python())
    return 0


def _compose_values() -> dict[str, str]:
    env_file = COMPOSE_ENV if COMPOSE_ENV.is_file() else COMPOSE_ENV_EXAMPLE
    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _local_postgres_dsn(*, sqlalchemy: bool) -> str:
    override = os.environ.get("RETAIL_POSTGRES_DSN")
    if override:
        if sqlalchemy and override.startswith("postgresql://"):
            return override.replace("postgresql://", "postgresql+psycopg://", 1)
        if not sqlalchemy and override.startswith("postgresql+psycopg://"):
            return override.replace("postgresql+psycopg://", "postgresql://", 1)
        return override
    values = _compose_values()
    user = quote(values.get("RETAIL_POSTGRES_USER", "retail"), safe="")
    password = quote(
        values.get("RETAIL_POSTGRES_PASSWORD", "retail-local-only"),
        safe="",
    )
    database = quote(
        values.get("RETAIL_POSTGRES_DB", "retail_intelligence"),
        safe="",
    )
    port = values.get("RETAIL_POSTGRES_PORT", "5432")
    scheme = "postgresql+psycopg" if sqlalchemy else "postgresql"
    return f"{scheme}://{user}:{password}@127.0.0.1:{port}/{database}"


def command_db_upgrade(_: argparse.Namespace) -> int:
    python = _require_python(DB_ENV, "database")
    environment = dict(os.environ)
    environment["RETAIL_POSTGRES_DSN"] = _local_postgres_dsn(sqlalchemy=True)
    return _run(
        [
            str(python),
            "-m",
            "alembic",
            "--config",
            str(REPO_ROOT / "db" / "alembic.ini"),
            "upgrade",
            "head",
        ],
        env=environment,
    )


def command_db_current(_: argparse.Namespace) -> int:
    python = _require_python(DB_ENV, "database")
    environment = dict(os.environ)
    environment["RETAIL_POSTGRES_DSN"] = _local_postgres_dsn(sqlalchemy=True)
    return _run(
        [
            str(python),
            "-m",
            "alembic",
            "--config",
            str(REPO_ROOT / "db" / "alembic.ini"),
            "current",
        ],
        env=environment,
    )


def command_db_test(_: argparse.Namespace) -> int:
    python = _require_python(DB_ENV, "database")
    environment = dict(os.environ)
    environment.setdefault(
        "RETAIL_TEST_POSTGRES_DSN",
        _local_postgres_dsn(sqlalchemy=False),
    )
    return _run(
        [str(python), "-m", "pytest", "db/tests", "-q"],
        env=environment,
    )


def command_boundaries(_: argparse.Namespace) -> int:
    return _run([sys.executable, str(REPO_ROOT / "tools" / "check_import_boundaries.py")])


def command_test(args: argparse.Namespace) -> int:
    datagen = _require_python(DATAGEN_ENV, "datagen")
    ingestion = _require_python(INGESTION_ENV, "ingestion")
    ml = _require_python(ML_ENV, "ml")
    database = _require_python(DB_ENV, "database")
    commands = [
        [sys.executable, str(REPO_ROOT / "tools" / "check_import_boundaries.py")],
        [str(ingestion), "-m", "pytest", "execution/tests", "-q"],
        [str(ingestion), "-m", "pytest", "contracts/python/tests", "-q"],
        [str(datagen), "-m", "pytest", "datagen/tests", "-q"],
        [
            str(ingestion),
            "-m",
            "pytest",
            "ingestion/tests",
            "-q",
            "-m",
            "pinned_run" if args.pinned_only else "not pinned_run",
        ],
        [str(ml), "-m", "pytest", "ml/tests", "-q"],
        [str(database), "-m", "pytest", "db/tests", "-q"],
    ]
    if args.pinned_only:
        commands = [commands[4]]
    for command in commands:
        result = _run(command)
        if result:
            return result
    return 0


def _discover_accepted_forecast_run() -> Path:
    override = os.environ.get("RETAIL_TEST_FORECAST_RUN")
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.is_dir():
            raise RuntimeError(
                f"RETAIL_TEST_FORECAST_RUN is not a directory: {candidate}"
            )
        return candidate

    candidates: list[tuple[str, Path]] = []
    artifact_root = REPO_ROOT / "ml" / "data" / "artifacts"
    for manifest_path in artifact_root.glob(
        "forecast_run_accepted_*/forecast-run-manifest.json"
    ):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if (
            manifest.get("lifecycleStatus") == "accepted"
            and manifest.get("modelPolicy", {}).get("acceptanceEvaluation")
            == ACCEPTANCE_EVALUATION_VERSION
        ):
            candidates.append(
                (str(manifest.get("decisionAsOf", "")), manifest_path.parent)
            )
    if not candidates:
        raise RuntimeError(
            "No independently recomputed accepted forecast run is available. "
            "Set RETAIL_TEST_FORECAST_RUN or complete the Phase 3 publication first."
        )
    return max(candidates, key=lambda value: (value[0], str(value[1])))[1]


def command_verify(_: argparse.Namespace) -> int:
    """Run the authoritative local phase-exit gate without repository CI."""

    datagen = _require_python(DATAGEN_ENV, "datagen")
    ingestion = _require_python(INGESTION_ENV, "ingestion")
    ml = _require_python(ML_ENV, "ml")
    database = _require_python(DB_ENV, "database")
    result = command_contracts(argparse.Namespace())
    if result:
        return result
    result = command_db_upgrade(argparse.Namespace())
    if result:
        return result
    mlflow_port = _compose_values().get("MLFLOW_PORT", "5000")
    try:
        with urlopen(
            f"http://127.0.0.1:{mlflow_port}/health",
            timeout=5,
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"MLflow health returned HTTP {response.status}"
                )
    except OSError as exc:
        raise RuntimeError(
            "MLflow is unavailable; run tools/dev.py services up"
        ) from exc
    integration_environment = dict(os.environ)
    integration_environment["RETAIL_TEST_POSTGRES_DSN"] = _local_postgres_dsn(
        sqlalchemy=False
    )
    integration_environment["RETAIL_TEST_FORECAST_RUN"] = str(
        _discover_accepted_forecast_run()
    )
    integration_environment.setdefault(
        "GOCACHE",
        str(Path(tempfile.gettempdir()) / "retail-intelligence-go-cache"),
    )
    commands: list[tuple[list[str], Path, dict[str, str] | None]] = [
        (
            [sys.executable, str(REPO_ROOT / "tools/check_import_boundaries.py")],
            REPO_ROOT,
            None,
        ),
        (
            [str(ingestion), "-m", "pytest", "execution/tests", "-q"],
            REPO_ROOT,
            None,
        ),
        (
            [str(ingestion), "-m", "pytest", "contracts/python/tests", "-q"],
            REPO_ROOT,
            None,
        ),
        (
            [str(datagen), "-m", "pytest", "datagen/tests", "-q"],
            REPO_ROOT,
            None,
        ),
        (
            [str(ingestion), "-m", "pytest", "ingestion/tests", "-q"],
            REPO_ROOT,
            None,
        ),
        (
            [str(database), "-m", "pytest", "db/tests", "-q"],
            REPO_ROOT,
            integration_environment,
        ),
        (
            [str(ml), "-m", "pytest", "ml/tests", "-q"],
            REPO_ROOT,
            integration_environment,
        ),
        (
            ["go", "test", "-count=1", "-race", "./..."],
            REPO_ROOT / "api",
            integration_environment,
        ),
        (["npm", "test"], REPO_ROOT / "ui", None),
        (["npm", "run", "typecheck"], REPO_ROOT / "ui", None),
        (["npm", "run", "build"], REPO_ROOT / "ui", None),
    ]
    for command, cwd, environment in commands:
        result = _run(command, cwd=cwd, env=environment)
        if result:
            return result
    return 0


def command_wheels(args: argparse.Namespace) -> int:
    builder = _require_python(INGESTION_ENV, "ingestion")
    command = [
        sys.executable,
        str(REPO_ROOT / "tools" / "check_isolated_wheels.py"),
        "--builder-python",
        str(builder),
    ]
    if args.offline:
        command.append("--offline")
    return _run(command)


def command_contracts(_: argparse.Namespace) -> int:
    ingestion = _require_python(INGESTION_ENV, "ingestion")
    validator = REPO_ROOT / "tools" / "validate_contracts.py"
    generator = REPO_ROOT / "tools" / "generate_contract_types.py"
    if not validator.is_file() or not generator.is_file():
        print("contract validator/code generator has not landed yet", file=sys.stderr)
        return 3
    result = _run([str(ingestion), str(validator)])
    if result:
        return result
    return _run([str(ingestion), str(generator), "--check"])


def command_ingest_stage(args: argparse.Namespace) -> int:
    ingestion = _require_python(INGESTION_ENV, "ingestion")
    command = [
        str(ingestion),
        "-m",
        "retail_ingestion.cli",
        args.command,
    ]
    if args.command != "finalize":
        command.extend(["--execution-profile", args.execution_profile])
    if args.command == "land":
        command.extend(
            [
                "--source-root",
                str(args.source_root),
                "--landing-root",
                str(args.landing_root),
            ]
        )
        if args.source_instance is not None:
            command.extend(["--source-instance", args.source_instance])
        if args.extract_boundary is not None:
            command.extend(["--extract-boundary", args.extract_boundary])
        if args.source_profile is not None:
            command.extend(["--source-profile", str(args.source_profile)])
    elif args.command == "gate-a":
        command.extend(
            [
                "--snapshot-root",
                str(args.snapshot_root),
                "--source-profile",
                str(args.source_profile),
            ]
        )
        if args.metadata_only:
            command.append("--metadata-only")
        if args.skip_data_scan:
            command.append("--skip-data-scan")
        if args.report_path is not None:
            command.extend(["--report-path", str(args.report_path)])
    elif args.command == "stage":
        command.extend(
            [
                "--snapshot-root",
                str(args.snapshot_root),
                "--source-profile",
                str(args.source_profile),
                "--output-database",
                str(args.output_database),
            ]
        )
    elif args.command == "transform":
        command.extend(
            [
                "--staging-database",
                str(args.staging_database),
                "--candidate-database",
                str(args.candidate_database),
            ]
        )
    elif args.command == "gate-b":
        command.extend(
            [
                "--candidate-database",
                str(args.candidate_database),
                "--staging-database",
                str(args.staging_database),
            ]
        )
        if args.report_path is not None:
            command.extend(["--report-path", str(args.report_path)])
    elif args.command == "publish":
        command.extend(
            [
                "--candidate-database",
                str(args.candidate_database),
                "--gate-b-report",
                str(args.gate_b_report),
                "--publication-root",
                str(args.publication_root),
            ]
        )
    elif args.command == "run":
        command.extend(
            [
                "--snapshot-root",
                str(args.snapshot_root),
                "--source-profile",
                str(args.source_profile),
                "--work-root",
                str(args.work_root),
                "--publication-root",
                str(args.publication_root),
            ]
        )
        if args.rebuild:
            command.append("--rebuild")
    elif args.command == "bench":
        command.extend(
            [
                "--snapshot-root",
                str(args.snapshot_root),
                "--source-profile",
                str(args.source_profile),
                "--report-path",
                str(args.report_path),
            ]
        )
        if args.temp_root is not None:
            command.extend(["--temp-root", str(args.temp_root)])
        if args.work_root is not None:
            command.extend(["--work-root", str(args.work_root)])
        if args.publication_root is not None:
            command.extend(["--publication-root", str(args.publication_root)])
    elif args.command == "finalize":
        command.extend(
            [
                "--work-root",
                str(args.work_root),
                "--publication-root",
                str(args.publication_root),
                "--evidence-root",
                str(args.evidence_root),
            ]
        )
        if args.prune_work:
            command.append("--prune-work")
    return _run(command)


def command_config_hash(_: argparse.Namespace) -> int:
    datagen = _require_python(DATAGEN_ENV, "datagen")
    return _run(
        [
            str(datagen),
            "-m",
            "retail_datagen.cli",
            "validate-config",
            "-c",
            str(
                REPO_ROOT
                / "datagen"
                / "configs"
                / "multi-market-10-year-demo.yaml"
            ),
        ]
    )


def command_run_status(_: argparse.Namespace) -> int:
    output = REPO_ROOT / "datagen" / "output"
    promoted = sorted(output.glob("*/run-*"))
    staging = sorted(output.glob("*/.run-*.staging-*"))
    if not promoted:
        print("no promoted run")
    for path in promoted:
        print(path.relative_to(REPO_ROOT))
    for path in staging:
        print(f"{path.relative_to(REPO_ROOT)} (staging in progress)")
    return 0


def command_api_test(_: argparse.Namespace) -> int:
    environment = dict(os.environ)
    environment.setdefault(
        "GOCACHE",
        str(Path(tempfile.gettempdir()) / "retail-intelligence-go-cache"),
    )
    return _run(
        ["go", "test", "-race", "./..."],
        cwd=REPO_ROOT / "api",
        env=environment,
    )


def command_services(args: argparse.Namespace) -> int:
    if not COMPOSE_FILE.is_file() or not COMPOSE_ENV_EXAMPLE.is_file():
        raise RuntimeError("the Phase 3 Compose service definition is incomplete")
    env_file = COMPOSE_ENV if COMPOSE_ENV.is_file() else COMPOSE_ENV_EXAMPLE
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "--file",
        str(COMPOSE_FILE),
    ]
    action = args.service_action
    if action == "up":
        command.extend(["up", "--detach", "--build", "--wait"])
    elif action == "down":
        command.append("down")
    elif action == "status":
        command.append("ps")
    elif action == "logs":
        command.extend(["logs", "--tail", str(args.tail)])
    else:
        raise RuntimeError(f"unsupported service action: {action}")
    return _run(command)


def command_ui_test(_: argparse.Namespace) -> int:
    return _run(["npm", "test"], cwd=REPO_ROOT / "ui")


def command_ui_build(_: argparse.Namespace) -> int:
    result = _run(["npm", "run", "typecheck"], cwd=REPO_ROOT / "ui")
    if result:
        return result
    return _run(["npm", "run", "build"], cwd=REPO_ROOT / "ui")


def command_ml(args: argparse.Namespace) -> int:
    ml = _require_python(ML_ENV, "ml")
    if args.command == "ml-test":
        return _run([str(ml), "-m", "pytest", "ml/tests", "-q"])
    mapped = {
        "features": "features",
        "characterize": "characterize",
        "train": "train",
        "backtest": "backtest",
        "drivers": "drivers",
        "ml-publish": "publish",
        "ml-bench": "bench",
        "forecast-materialize": "materialize-serving",
        "forecast-activate": "activate-serving",
    }[args.command]
    command = [str(ml), "-m", "retail_ml.cli", mapped]
    if args.command in {
        "features",
        "ml-bench",
        "forecast-materialize",
        "forecast-activate",
    }:
        command.extend(["--repository-root", str(args.repository_root)])
    if args.command == "features":
        command.extend(
            [
                "--output-dir",
                str(args.output_dir),
                "--execution-profile",
                args.execution_profile,
            ]
        )
    elif args.command == "characterize":
        command.extend(
            [
                "--feature-dir",
                str(args.feature_dir),
                "--report",
                str(args.report),
            ]
        )
    elif args.command == "backtest":
        command.extend(
            [
                "--feature-dir",
                str(args.feature_dir),
                "--output-dir",
                str(args.output_dir),
                "--tracking-uri",
                args.tracking_uri,
                "--horizons",
                args.horizons,
                "--origin-count",
                str(args.origin_count),
                "--execution-profile",
                args.execution_profile,
            ]
        )
    elif args.command == "drivers":
        command.extend(
            [
                "--evaluation",
                str(args.evaluation),
                "--output",
                str(args.output),
            ]
        )
        if args.version_id is not None:
            command.extend(["--version-id", args.version_id])
        if args.portfolio_only:
            command.append("--portfolio-only")
    elif args.command == "ml-publish":
        command.extend(
            [
                "--feature-dir",
                str(args.feature_dir),
                "--backtest-dir",
                str(args.backtest_dir),
                "--exceptions",
                str(args.exceptions),
                "--data-quality",
                str(args.data_quality),
                "--classification-policies",
                str(args.classification_policies),
                "--output-dir",
                str(args.output_dir),
                "--decision-as-of",
                args.decision_as_of,
                "--execution-profile",
                args.execution_profile,
            ]
        )
    elif args.command == "ml-bench":
        command.extend(["--report", str(args.report)])
    elif args.command == "forecast-materialize":
        command.extend(
            [
                "--forecast-run",
                str(args.forecast_run),
                "--postgres-dsn",
                _local_postgres_dsn(sqlalchemy=False),
            ]
        )
    elif args.command == "forecast-activate":
        command.extend(
            [
                "--forecast-run-id",
                args.forecast_run_id,
                "--activation-scope-fingerprint",
                args.activation_scope_fingerprint,
                "--actor",
                args.actor,
                "--postgres-dsn",
                _local_postgres_dsn(sqlalchemy=False),
            ]
        )
    return _run(command)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "envs",
        help="create datagen, ingestion, ML, and database environments",
    )
    subparsers.add_parser("db-env", help="create the database tooling environment")
    subparsers.add_parser("db-upgrade", help="upgrade PostgreSQL to the latest migration")
    subparsers.add_parser("db-current", help="show the current PostgreSQL migration")
    subparsers.add_parser("db-test", help="run database schema tests")
    subparsers.add_parser("boundaries", help="run static package-boundary checks")

    test = subparsers.add_parser("test", help="run the fast repository suites")
    test.add_argument("--pinned-only", action="store_true")
    subparsers.add_parser(
        "verify",
        help="run the authoritative stateful local phase-exit gate",
    )

    wheels = subparsers.add_parser("wheels", help="build and isolate actual wheels")
    wheels.add_argument("--offline", action="store_true")

    subparsers.add_parser("contracts", help="validate machine-readable contracts")
    subparsers.add_parser("config-hash", help="validate the pinned datagen config")
    subparsers.add_parser("run-status", help="show promoted/staging source runs")
    subparsers.add_parser("api-test", help="run portable Go API race tests")
    subparsers.add_parser("ui-test", help="run the UI unit tests")
    subparsers.add_parser("ui-build", help="typecheck and build the UI")
    subparsers.add_parser("ml-test", help="run the isolated ML tests")
    services = subparsers.add_parser(
        "services",
        help="manage the local PostgreSQL and MLflow services",
    )
    services.add_argument(
        "service_action",
        choices=("up", "down", "status", "logs"),
    )
    services.add_argument("--tail", type=int, default=200)

    features = subparsers.add_parser("features", help="build verified weekly ML features")
    features.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    features.add_argument("--output-dir", type=Path, required=True)
    features.add_argument(
        "--execution-profile",
        default="safe",
        choices=("safe", "balanced", "performance", "ultra-performance"),
    )

    characterize = subparsers.add_parser(
        "characterize",
        help="characterize a weekly feature artifact",
    )
    characterize.add_argument("--feature-dir", type=Path, required=True)
    characterize.add_argument("--report", type=Path, required=True)

    subparsers.add_parser("train", help="run the Phase-3 forecast trainer")
    backtest = subparsers.add_parser(
        "backtest",
        help="run the Phase-3 rolling-origin backtest",
    )
    backtest.add_argument("--feature-dir", type=Path, required=True)
    backtest.add_argument("--output-dir", type=Path, required=True)
    backtest.add_argument(
        "--tracking-uri",
        "--tracking-root",
        dest="tracking_uri",
        default=os.environ.get(
            "MLFLOW_TRACKING_URI",
            str(REPO_ROOT / "ml" / "mlruns"),
        ),
        help="MLflow HTTP URI or local file-store path",
    )
    backtest.add_argument(
        "--horizons",
        default=",".join(str(value) for value in range(1, 27)),
    )
    backtest.add_argument("--origin-count", type=int, default=13)
    backtest.add_argument(
        "--execution-profile",
        default="safe",
        choices=("safe", "balanced", "performance", "ultra-performance"),
    )

    drivers = subparsers.add_parser(
        "drivers",
        help="aggregate governed forecast driver rows",
    )
    drivers.add_argument("--evaluation", type=Path, required=True)
    drivers.add_argument("--output", type=Path, required=True)
    drivers.add_argument("--version-id", default=None)
    drivers.add_argument("--portfolio-only", action="store_true")

    ml_publish = subparsers.add_parser(
        "ml-publish",
        help="publish a complete immutable forecast-run bundle",
    )
    ml_publish.add_argument("--feature-dir", type=Path, required=True)
    ml_publish.add_argument("--backtest-dir", type=Path, required=True)
    ml_publish.add_argument("--exceptions", type=Path, required=True)
    ml_publish.add_argument("--data-quality", type=Path, required=True)
    ml_publish.add_argument("--classification-policies", type=Path, required=True)
    ml_publish.add_argument("--output-dir", type=Path, required=True)
    ml_publish.add_argument("--decision-as-of", required=True)
    ml_publish.add_argument(
        "--execution-profile",
        default="safe",
        choices=("safe", "balanced", "performance", "ultra-performance"),
    )

    ml_bench = subparsers.add_parser("ml-bench", help="run the full-data ML memory spike")
    ml_bench.add_argument("--repository-root", type=Path, default=REPO_ROOT)
    ml_bench.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / "ml/reports/w0-memory-spike-safe-16gb.json",
    )
    forecast_materialize = subparsers.add_parser(
        "forecast-materialize",
        help="verify and transactionally load an accepted forecast into PostgreSQL",
    )
    forecast_materialize.add_argument(
        "--repository-root",
        type=Path,
        default=REPO_ROOT,
    )
    forecast_materialize.add_argument("--forecast-run", type=Path, required=True)
    forecast_activate = subparsers.add_parser(
        "forecast-activate",
        help="explicitly activate a materialized accepted forecast",
    )
    forecast_activate.add_argument(
        "--repository-root",
        type=Path,
        default=REPO_ROOT,
    )
    forecast_activate.add_argument("--forecast-run-id", required=True)
    forecast_activate.add_argument(
        "--activation-scope-fingerprint",
        required=True,
    )
    forecast_activate.add_argument("--actor", required=True)

    for name in (
        "land",
        "gate-a",
        "stage",
        "transform",
        "gate-b",
        "publish",
        "run",
        "bench",
        "finalize",
    ):
        stage = subparsers.add_parser(name)
        if name != "finalize":
            stage.add_argument(
                "--execution-profile",
                default="safe",
                choices=("safe", "balanced", "performance", "ultra-performance"),
            )
        if name == "land":
            stage.add_argument("--source-root", type=Path, required=True)
            stage.add_argument("--landing-root", type=Path, required=True)
            stage.add_argument("--source-instance", default=None)
            stage.add_argument("--extract-boundary", default=None)
            stage.add_argument("--source-profile", type=Path, default=None)
        elif name == "gate-a":
            stage.add_argument("--snapshot-root", type=Path, required=True)
            stage.add_argument(
                "--source-profile",
                type=Path,
                default=(
                    REPO_ROOT
                    / "ingestion"
                    / "src"
                    / "retail_ingestion"
                    / "profiles"
                    / "retail_datagen.yaml"
                ),
            )
            stage.add_argument("--metadata-only", action="store_true")
            stage.add_argument("--skip-data-scan", action="store_true")
            stage.add_argument("--report-path", type=Path, default=None)
        elif name == "stage":
            stage.add_argument("--snapshot-root", type=Path, required=True)
            stage.add_argument(
                "--source-profile",
                type=Path,
                default=(
                    REPO_ROOT
                    / "ingestion"
                    / "src"
                    / "retail_ingestion"
                    / "profiles"
                    / "retail_datagen.yaml"
                ),
            )
            stage.add_argument("--output-database", type=Path, required=True)
        elif name == "transform":
            stage.add_argument("--staging-database", type=Path, required=True)
            stage.add_argument("--candidate-database", type=Path, required=True)
        elif name == "gate-b":
            stage.add_argument("--candidate-database", type=Path, required=True)
            stage.add_argument("--staging-database", type=Path, required=True)
            stage.add_argument("--report-path", type=Path, default=None)
        elif name == "publish":
            stage.add_argument("--candidate-database", type=Path, required=True)
            stage.add_argument("--gate-b-report", type=Path, required=True)
            stage.add_argument("--publication-root", type=Path, required=True)
        elif name == "run":
            stage.add_argument("--snapshot-root", type=Path, required=True)
            stage.add_argument(
                "--source-profile",
                type=Path,
                default=(
                    REPO_ROOT
                    / "ingestion"
                    / "src"
                    / "retail_ingestion"
                    / "profiles"
                    / "retail_datagen.yaml"
                ),
            )
            stage.add_argument("--work-root", type=Path, required=True)
            stage.add_argument("--publication-root", type=Path, required=True)
            stage.add_argument("--rebuild", action="store_true")
        elif name == "bench":
            stage.add_argument("--snapshot-root", type=Path, required=True)
            stage.add_argument(
                "--source-profile",
                type=Path,
                default=(
                    REPO_ROOT
                    / "ingestion"
                    / "src"
                    / "retail_ingestion"
                    / "profiles"
                    / "retail_datagen.yaml"
                ),
            )
            stage.add_argument("--report-path", type=Path, required=True)
            stage.add_argument("--temp-root", type=Path, default=None)
            stage.add_argument("--work-root", type=Path, default=None)
            stage.add_argument("--publication-root", type=Path, default=None)
        elif name == "finalize":
            stage.add_argument("--work-root", type=Path, required=True)
            stage.add_argument("--publication-root", type=Path, required=True)
            stage.add_argument("--evidence-root", type=Path, required=True)
            stage.add_argument("--prune-work", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "envs": command_envs,
        "db-env": command_db_env,
        "db-upgrade": command_db_upgrade,
        "db-current": command_db_current,
        "db-test": command_db_test,
        "boundaries": command_boundaries,
        "test": command_test,
        "verify": command_verify,
        "wheels": command_wheels,
        "contracts": command_contracts,
        "config-hash": command_config_hash,
        "run-status": command_run_status,
        "api-test": command_api_test,
        "services": command_services,
        "ui-test": command_ui_test,
        "ui-build": command_ui_build,
        "ml-test": command_ml,
        "features": command_ml,
        "characterize": command_ml,
        "train": command_ml,
        "backtest": command_ml,
        "drivers": command_ml,
        "ml-publish": command_ml,
        "ml-bench": command_ml,
        "forecast-materialize": command_ml,
        "forecast-activate": command_ml,
        "land": command_ingest_stage,
        "gate-a": command_ingest_stage,
        "stage": command_ingest_stage,
        "transform": command_ingest_stage,
        "gate-b": command_ingest_stage,
        "publish": command_ingest_stage,
        "run": command_ingest_stage,
        "bench": command_ingest_stage,
        "finalize": command_ingest_stage,
    }
    try:
        return commands[args.command](args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
