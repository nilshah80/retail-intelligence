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

    for name in ("land", "gate-a", "gate-b", "bench"):
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
        "land": command_ingest_stage,
        "gate-a": command_ingest_stage,
        "gate-b": command_ingest_stage,
        "bench": command_ingest_stage,
    }
    try:
        return commands[args.command](args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
