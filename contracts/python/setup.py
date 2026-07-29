"""Setuptools build hook for the versioned machine-readable contracts.

The YAML/JSON files remain authored once under ``contracts/``.  Wheel builds copy
that authoritative tree into ``retail_contracts/data`` so installed consumers do
not depend on a monorepo checkout.  ``pathlib``/``shutil`` keep this identical on
Windows, macOS and Linux.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

CONTRACT_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_DIRECTORIES = (
    "coverage",
    "fingerprints",
    "guardrails",
    "profiles",
    "retail_v2",
    "staging",
)


class BuildPyWithContracts(build_py):
    """Copy the authoritative non-Python contracts into the built package."""

    def run(self) -> None:
        super().run()
        destination_root = Path(self.build_lib) / "retail_contracts" / "data"
        self._contract_outputs: list[str] = []
        for directory in CONTRACT_DIRECTORIES:
            source = CONTRACT_ROOT / directory
            if not source.is_dir():
                continue
            destination = destination_root / directory
            shutil.copytree(source, destination, dirs_exist_ok=True)
            self._contract_outputs.extend(
                str(path) for path in destination.rglob("*") if path.is_file()
            )

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = super().get_outputs(include_bytecode=include_bytecode)
        return [*outputs, *getattr(self, "_contract_outputs", [])]


setup(cmdclass={"build_py": BuildPyWithContracts})
