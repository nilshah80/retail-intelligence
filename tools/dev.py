#!/usr/bin/env python3
"""Cross-platform developer entry point for the monorepo.

This file is authoritative; the root Makefile is a short POSIX convenience
wrapper. Every subprocess is invoked with an argument list, every path uses
``pathlib``, and virtual-environment executables resolve correctly on Windows.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INGESTION_ENV = REPO_ROOT / "ingestion" / ".venv"
ML_ENV = REPO_ROOT / "ml" / ".venv"
DATAGEN_ENV = REPO_ROOT / "datagen" / ".venv"


def venv_python(root: Path) -> Path:
    return (
        root / "Scripts" / "python.exe"
        if os.name == "nt"
        else root / "bin" / "python"
    )


def _run(args: list[str], *, cwd: Path = REPO_ROOT) -> int:
    return subprocess.run(args, cwd=cwd, check=False).returncode


def _require_python(root: Path, label: str) -> Path:
    python = venv_python(root)
    if not python.is_file():
        raise RuntimeError(
            f"{label} environment is missing at {root}. "
            f"Run {Path(sys.executable).name} tools/dev.py envs first."
        )
    return python


def _create_environment(root: Path, editable: list[str]) -> None:
    venv.EnvBuilder(with_pip=True, clear=True).create(root)
    python = venv_python(root)
    commands = (
        [str(python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--editable",
            str(REPO_ROOT / "execution"),
            "--editable",
            str(REPO_ROOT / "contracts" / "python"),
        ],
        [
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
        ],
    )
    for command in commands:
        if _run(command):
            raise RuntimeError(f"environment command failed: {command!r}")


def command_envs(_: argparse.Namespace) -> int:
    _create_environment(INGESTION_ENV, ["ingestion[dev]"])
    _create_environment(ML_ENV, ["ml[dev]"])
    return 0


def command_boundaries(_: argparse.Namespace) -> int:
    return _run([sys.executable, str(REPO_ROOT / "tools" / "check_import_boundaries.py")])


def command_test(args: argparse.Namespace) -> int:
    ingestion = _require_python(INGESTION_ENV, "ingestion")
    ml = _require_python(ML_ENV, "ml")
    commands = [
        [sys.executable, str(REPO_ROOT / "tools" / "check_import_boundaries.py")],
        [str(ingestion), "-m", "pytest", "execution/tests", "-q"],
        [str(ingestion), "-m", "pytest", "contracts/python/tests", "-q"],
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
    ]
    if args.pinned_only:
        commands = [commands[3]]
    for command in commands:
        result = _run(command)
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
        "--execution-profile",
        args.execution_profile,
    ]
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
    return _run(["go", "test", "-race", "./..."], cwd=REPO_ROOT / "api")


def command_ui_test(_: argparse.Namespace) -> int:
    return _run(["npm", "test"], cwd=REPO_ROOT / "ui")


def command_ui_build(_: argparse.Namespace) -> int:
    result = _run(["npm", "run", "typecheck"], cwd=REPO_ROOT / "ui")
    if result:
        return result
    return _run(["npm", "run", "build"], cwd=REPO_ROOT / "ui")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("envs", help="create ingestion and ML environments")
    subparsers.add_parser("boundaries", help="run static package-boundary checks")

    test = subparsers.add_parser("test", help="run the fast repository suites")
    test.add_argument("--pinned-only", action="store_true")

    wheels = subparsers.add_parser("wheels", help="build and isolate actual wheels")
    wheels.add_argument("--offline", action="store_true")

    subparsers.add_parser("contracts", help="validate machine-readable contracts")
    subparsers.add_parser("config-hash", help="validate the pinned datagen config")
    subparsers.add_parser("run-status", help="show promoted/staging source runs")
    subparsers.add_parser("api-test", help="run portable Go API race tests")
    subparsers.add_parser("ui-test", help="run the UI unit tests")
    subparsers.add_parser("ui-build", help="typecheck and build the UI")

    for name in (
        "land",
        "gate-a",
        "stage",
        "transform",
        "gate-b",
        "publish",
        "run",
        "bench",
    ):
        stage = subparsers.add_parser(name)
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "envs": command_envs,
        "boundaries": command_boundaries,
        "test": command_test,
        "wheels": command_wheels,
        "contracts": command_contracts,
        "config-hash": command_config_hash,
        "run-status": command_run_status,
        "api-test": command_api_test,
        "ui-test": command_ui_test,
        "ui-build": command_ui_build,
        "land": command_ingest_stage,
        "gate-a": command_ingest_stage,
        "stage": command_ingest_stage,
        "transform": command_ingest_stage,
        "gate-b": command_ingest_stage,
        "publish": command_ingest_stage,
        "run": command_ingest_stage,
        "bench": command_ingest_stage,
    }
    try:
        return commands[args.command](args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
