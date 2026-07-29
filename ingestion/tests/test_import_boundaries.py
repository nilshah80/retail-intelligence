"""Ingestion's view of the repository ownership boundaries.

The rules themselves live in `tools/check_import_boundaries.py` so all three
packages assert the same matrix instead of drifting apart. This test exists so a
plain `pytest` inside `ingestion/` still catches a violation.
"""

import subprocess
import sys
import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "tools" / "check_import_boundaries.py"


def test_import_boundaries_hold() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        "import-boundary violations detected:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_ingestion_does_not_import_ml_or_api() -> None:
    """Spot-check the specific rule this package is responsible for."""
    sys.path.insert(0, str(CHECKER.parent))
    try:
        import check_import_boundaries as checker
    finally:
        sys.path.pop(0)

    ingestion = next(b for b in checker.BOUNDARIES if b.name == "ingestion")
    assert {"ml", "retail_ml", "api"} <= ingestion.forbidden


def _checker_module():
    sys.path.insert(0, str(CHECKER.parent))
    try:
        import check_import_boundaries as checker
    finally:
        sys.path.pop(0)
    return checker


def test_transform_relative_adapter_import_is_resolved_and_rejected() -> None:
    checker = _checker_module()
    path = (
        REPO_ROOT
        / "ingestion"
        / "src"
        / "retail_ingestion"
        / "transforms"
        / "sales.py"
    )
    imports = checker._module_imports(
        ast.parse("from ..adapters import shopify"),
        path=path,
        source_root=REPO_ROOT / "ingestion" / "src",
    )
    assert checker.ImportRef("retail_ingestion.adapters", 1) in imports
    allowlist = next(a for a in checker.ALLOWLISTS if a.name == "ingestion.transforms")
    assert not any(
        checker._matches_prefix("retail_ingestion.adapters", prefix)
        for prefix in allowlist.permitted_prefixes
    )


def test_transform_absolute_adapter_import_is_rejected_but_staging_is_allowed() -> None:
    checker = _checker_module()
    allowlist = next(a for a in checker.ALLOWLISTS if a.name == "ingestion.transforms")

    def permitted(module: str) -> bool:
        return any(
            checker._matches_prefix(module, prefix)
            for prefix in allowlist.permitted_prefixes
        )

    assert not permitted("retail_ingestion.adapters.shopify")
    assert not permitted("retail_ingestion.profiles.datagen_shopify_v1")
    assert permitted("retail_ingestion.staging.envelopes")
    assert permitted("retail_ingestion.transforms.money")
