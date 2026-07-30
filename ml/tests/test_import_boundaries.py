"""ML's view of the repository ownership boundaries.

`ml/` consumes capability-complete curated data and nothing else. Reaching into
`ingestion/` is how source-specific branching gets into features and models, which
decision #2 exists to prevent.
"""

import subprocess
import sys
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


def test_ml_may_not_import_ingestion() -> None:
    sys.path.insert(0, str(CHECKER.parent))
    try:
        import check_import_boundaries as checker
    finally:
        sys.path.pop(0)

    ml = next(b for b in checker.BOUNDARIES if b.name == "ml")
    assert {
        "datagen",
        "ingestion",
        "pipeline",
        "reports",
        "retail_ai",
        "retail_datagen",
        "retail_ingestion",
    } <= ml.forbidden
