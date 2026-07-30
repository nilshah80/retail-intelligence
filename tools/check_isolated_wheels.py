#!/usr/bin/env python3
"""Build and import every Python distribution from its actual wheel.

This is the cross-platform half of the package-boundary check. It intentionally
uses ``subprocess`` argument lists and :mod:`pathlib`; Windows runs the same command
with ``py -3 tools/check_isolated_wheels.py`` while POSIX can use ``python3``.

By default dependencies are resolved normally (with the local wheelhouse preferred).
``--offline`` installs only the wheels built from this repository and validates
declared dependency metadata; it is useful in network-restricted sandboxes but is
not a replacement for the authoritative developer-run component suites.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Package:
    name: str
    distribution: str
    source: Path
    internal_dependencies: tuple[str, ...]
    required_metadata: tuple[str, ...]
    probe: str
    full_probe: str = ""


PACKAGES = (
    Package(
        name="retail-execution",
        distribution="retail-intelligence-execution",
        source=REPO_ROOT / "execution",
        internal_dependencies=(),
        required_metadata=(),
        probe=(
            "from retail_execution.profiles import resolve_profile; "
            "assert resolve_profile('safe', environment={})['ingestion']['memoryLimitGb'] == 4"
        ),
    ),
    Package(
        name="retail-contracts",
        distribution="retail-contracts",
        source=REPO_ROOT / "contracts" / "python",
        internal_dependencies=(),
        required_metadata=("rfc8785",),
        probe=(
            "import retail_contracts; "
            "from retail_contracts import enums, fingerprint, fx, money; "
            "assert retail_contracts.CONTRACT_VERSION == 'retail_v2'; "
            "assert enums.RuleOutcome.CAPABILITY_DOWNGRADE == 'capability_downgrade'; "
            "assert money.minor_exponent('INR') == 2"
        ),
        full_probe=(
            "from retail_contracts.entities import validate_contract_tree; "
            "assert validate_contract_tree()['entities'] == 53"
        ),
    ),
    Package(
        name="retail-ingestion",
        distribution="retail-ingestion",
        source=REPO_ROOT / "ingestion",
        internal_dependencies=(
            "retail-intelligence-execution",
            "retail-contracts",
        ),
        required_metadata=(
            "retail-intelligence-execution",
            "retail-contracts",
        ),
        probe=(
            "import retail_ingestion; "
            "from retail_ingestion.runtime.profile import resolve_ingestion_runtime; "
            "assert resolve_ingestion_runtime('safe', environment={}).memory_limit_gb == 4"
        ),
        full_probe=(
            "from retail_ingestion.cli import build_parser; "
            "p=build_parser().parse_args(['gate-a','--snapshot-root','.']).source_profile; "
            "assert p.name == 'retail_datagen.yaml' and p.is_file()"
        ),
    ),
    Package(
        name="retail-ml",
        distribution="retail-ml",
        source=REPO_ROOT / "ml",
        internal_dependencies=(
            "retail-intelligence-execution",
            "retail-contracts",
        ),
        required_metadata=(
            "retail-intelligence-execution",
            "retail-contracts",
        ),
        probe=(
            "import retail_ml, sys; "
            "assert not [m for m in sys.modules if m.startswith('retail_ingestion')]"
        ),
    ),
    Package(
        name="retail-datagen",
        distribution="retail-intelligence-datagen",
        source=REPO_ROOT / "datagen",
        internal_dependencies=(),
        required_metadata=(),
        probe=(
            "import retail_datagen, retail_execution, sys; "
            "assert retail_datagen.GENERATOR_VERSION; "
            "assert not [m for m in sys.modules if m.startswith('retail_contracts')]"
        ),
    ),
)


def _venv_python(root: Path) -> Path:
    return (
        root / "Scripts" / "python.exe"
        if os.name == "nt"
        else root / "bin" / "python"
    )


def _run(args: list[str], *, cwd: Path, capture: bool = False) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    environment.pop("PYTHONPATH", None)
    return subprocess.run(
        args,
        cwd=cwd,
        env=environment,
        check=False,
        text=True,
        capture_output=capture,
    )


def _wheel_for(wheelhouse: Path, distribution: str) -> Path:
    normalized = distribution.replace("-", "_")
    matches = sorted(wheelhouse.glob(f"{normalized}-*.whl"))
    if len(matches) != 1:
        names = ", ".join(path.name for path in matches) or "none"
        raise RuntimeError(
            f"expected one wheel for {distribution!r}, found {names}"
        )
    return matches[0]


def _build_wheels(builder: Path, wheelhouse: Path) -> dict[str, Path]:
    wheels: dict[str, Path] = {}
    for package in PACKAGES:
        print(f"build {package.name}")
        result = _run(
            [
                str(builder),
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--wheel-dir",
                str(wheelhouse),
                str(package.source),
            ],
            cwd=REPO_ROOT,
            capture=True,
        )
        if result.returncode:
            raise RuntimeError(
                f"wheel build failed for {package.name}:\n"
                f"{result.stdout}\n{result.stderr}"
            )
        wheels[package.distribution] = _wheel_for(
            wheelhouse, package.distribution
        )
    return wheels


def _metadata_probe(package: Package, *, offline: bool) -> str:
    expected = repr(tuple(value.lower() for value in package.required_metadata))
    return (
        "from importlib.metadata import requires; "
        f"rows=[r.lower() for r in (requires({package.distribution!r}) or [])]; "
        f"expected={expected}; "
        "assert all(any(item in row for row in rows) for item in expected), "
        "f'missing dependency metadata: expected={expected!r}, actual={rows!r}'; "
        + package.probe
        + ("; " + package.full_probe if package.full_probe and not offline else "")
    )


def _check_package(
    package: Package,
    *,
    wheels: dict[str, Path],
    wheelhouse: Path,
    work: Path,
    offline: bool,
) -> None:
    print(f"check {package.name}")
    environment_root = work / f"venv-{package.name}"
    venv.EnvBuilder(with_pip=True, clear=True).create(environment_root)
    python = _venv_python(environment_root)

    if offline:
        for dependency in package.internal_dependencies:
            result = _run(
                [
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--quiet",
                    "--no-index",
                    "--no-deps",
                    str(wheels[dependency]),
                ],
                cwd=work,
                capture=True,
            )
            if result.returncode:
                raise RuntimeError(result.stderr)
        install_args = [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-index",
            "--no-deps",
            str(wheels[package.distribution]),
        ]
    else:
        install_args = [
            str(python),
            "-m",
            "pip",
            "install",
            "--quiet",
            "--find-links",
            str(wheelhouse),
            str(wheels[package.distribution]),
        ]

    result = _run(install_args, cwd=work, capture=True)
    if result.returncode:
        raise RuntimeError(
            f"isolated install failed for {package.name}:\n{result.stderr}"
        )
    result = _run(
        [str(python), "-c", _metadata_probe(package, offline=offline)],
        cwd=work,
        capture=True,
    )
    if result.returncode:
        raise RuntimeError(
            f"isolated import failed for {package.name}:\n{result.stderr}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--offline",
        action="store_true",
        help="do not resolve external dependencies; still build and install actual wheels",
    )
    parser.add_argument(
        "--builder-python",
        type=Path,
        default=Path(sys.executable),
        help="interpreter whose pip/setuptools build the wheels",
    )
    args = parser.parse_args(argv)

    try:
        with tempfile.TemporaryDirectory(prefix="retail-wheels-") as temporary:
            work = Path(temporary)
            wheelhouse = work / "wheelhouse"
            wheelhouse.mkdir()
            wheels = _build_wheels(args.builder_python, wheelhouse)
            for package in PACKAGES:
                _check_package(
                    package,
                    wheels=wheels,
                    wheelhouse=wheelhouse,
                    work=work,
                    offline=args.offline,
                )
    except (OSError, RuntimeError) as exc:
        print(f"isolated-wheel checks FAILED: {exc}", file=sys.stderr)
        return 1

    print("isolated-wheel checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
