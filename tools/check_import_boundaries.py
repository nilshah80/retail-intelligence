#!/usr/bin/env python3
"""Statically enforce the repository's package ownership boundaries.

Why static and not `ModuleNotFoundError`: an import-time assertion only fires when
the forbidden package is genuinely absent. Once `ingestion` and `ml` share a
developer validation environment, a runtime probe passes while the boundary is
being violated. Parsing the AST does not care what is
installed.

Two kinds of rule:

* **Package boundaries** — `datagen/` imports nothing downstream; `ml/` never reaches
  into `ingestion/`; ingestion never reaches into `ml/` or `api/`.
* **Transform allowlist** — modules under `transforms/` may import only staging
  contracts, shared semantic utilities and other transforms. This is what actually
  keeps source-specific logic out of the shared transforms; grepping for the word
  "shopify" would miss an indirect import and flag an innocent comment.

Run directly (`python3 tools/check_import_boundaries.py`) or via `make boundaries`.
Exit status is 0 when clean, 1 with a report otherwise.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Boundary:
    """One ownership rule over a source tree."""

    name: str
    root: Path
    forbidden: frozenset[str]
    rationale: str


@dataclass(frozen=True)
class Allowlist:
    """A tree that may import only from explicit module prefixes."""

    name: str
    root: Path
    permitted_prefixes: frozenset[str]
    rationale: str


@dataclass(frozen=True, order=True)
class ImportRef:
    """One statically resolved import."""

    module: str
    lineno: int


#: Distribution and import names that mean "a downstream package".
_DOWNSTREAM = frozenset(
    {
        "contracts",
        "retail_contracts",
        "ingestion",
        "retail_ingestion",
        "ml",
        "retail_ml",
        "api",
    }
)

BOUNDARIES: tuple[Boundary, ...] = (
    Boundary(
        name="datagen",
        root=REPO_ROOT / "datagen" / "src",
        # datagen vendors retail_execution from source, so operational profiles are
        # allowed; every semantic downstream package is not.
        forbidden=_DOWNSTREAM,
        rationale=(
            "decision #36: datagen owns its own source spec and stays extract-ready, so "
            "it must never import retail_v2 or any downstream module"
        ),
    ),
    Boundary(
        name="ml",
        root=REPO_ROOT / "ml" / "src",
        forbidden=frozenset(
            {
                "api",
                "datagen",
                "ingestion",
                "pipeline",
                "reports",
                "retail_ai",
                "retail_datagen",
                "retail_ingestion",
            }
        ),
        rationale=(
            "decision #2: ml consumes curated data only; reaching into ingestion would "
            "let source logic or a superseded publication path leak into features and models"
        ),
    ),
    Boundary(
        name="ingestion",
        root=REPO_ROOT / "ingestion" / "src",
        forbidden=frozenset({"ml", "retail_ml", "api"}),
        rationale=(
            "ingestion publishes curated data and knows nothing about its consumers"
        ),
    ),
)

ALLOWLISTS: tuple[Allowlist, ...] = (
    Allowlist(
        name="ingestion.transforms",
        root=REPO_ROOT / "ingestion" / "src" / "retail_ingestion" / "transforms",
        permitted_prefixes=frozenset(
            {
                # shared semantic contract
                "retail_contracts",
                # Only staging envelopes and sibling transforms. Deliberately do
                # not allow the retail_ingestion root: that would also admit
                # adapters, profiles, landing and source-specific code.
                "retail_ingestion.staging",
                "retail_ingestion.transforms",
                # stdlib / numeric primitives the transforms legitimately need
                "collections",
                "dataclasses",
                "datetime",
                "decimal",
                "enum",
                "functools",
                "hashlib",
                "itertools",
                "json",
                "math",
                "os",
                "pathlib",
                "typing",
                "uuid",
                "zoneinfo",
                "duckdb",
                "pyarrow",
                "pandas",
                "__future__",
            }
        ),
        rationale=(
            "source-neutral transforms read staging only and may not branch on "
            "retailer or platform identity"
        ),
    ),
)


def _module_name(path: Path, source_root: Path) -> tuple[list[str], list[str]]:
    """Return ``(module_parts, current_package_parts)`` for a source file."""

    relative = path.relative_to(source_root).with_suffix("")
    module_parts = list(relative.parts)
    if module_parts[-1] == "__init__":
        module_parts.pop()
        current_package = list(module_parts)
    else:
        current_package = module_parts[:-1]
    return module_parts, current_package


def _module_imports(tree: ast.AST, *, path: Path, source_root: Path) -> set[ImportRef]:
    """Resolve absolute and relative imports to complete module prefixes.

    A transform can violate its boundary with ``from ..adapters import ...`` just
    as easily as with an absolute import. Relative imports are therefore resolved
    against the file's package instead of being skipped.
    """

    _, current_package = _module_name(path, source_root)
    found: set[ImportRef] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(ImportRef(alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                parents_to_remove = node.level - 1
                if parents_to_remove > len(current_package):
                    found.add(ImportRef("<invalid-relative-import>", node.lineno))
                    continue
                base = current_package[: len(current_package) - parents_to_remove]
            else:
                base = []

            module_parts = node.module.split(".") if node.module else []
            resolved = base + module_parts
            # ``from package import child`` may import a child module. Include the
            # alias when the statement names only a package root or has no module
            # component, so ``from retail_ingestion import adapters`` cannot hide.
            if not node.module or (
                not node.level and node.module in {"retail_ingestion", "retail_ml"}
            ):
                for alias in node.names:
                    found.add(ImportRef(".".join(resolved + [alias.name]), node.lineno))
            elif resolved:
                found.add(ImportRef(".".join(resolved), node.lineno))
    return found


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _python_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [
        path
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts and ".venv" not in path.parts
    ]


def _parse(path: Path) -> ast.AST | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:  # a broken file is a separate problem; report it
        print(f"  ! {path.relative_to(REPO_ROOT)}: cannot parse ({exc})")
        return None


def check() -> list[str]:
    """Return a list of violation strings; empty means clean."""
    violations: list[str] = []

    for boundary in BOUNDARIES:
        files = _python_files(boundary.root)
        for path in files:
            tree = _parse(path)
            if tree is None:
                continue
            for imported in sorted(
                _module_imports(tree, path=path, source_root=boundary.root)
            ):
                if any(
                    _matches_prefix(imported.module, forbidden)
                    for forbidden in boundary.forbidden
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{imported.lineno} — "
                        f"{boundary.name} may not import {imported.module!r} "
                        f"({boundary.rationale})"
                    )

    for allowlist in ALLOWLISTS:
        files = _python_files(allowlist.root)
        for path in files:
            tree = _parse(path)
            if tree is None:
                continue
            for imported in sorted(
                _module_imports(tree, path=path, source_root=allowlist.root.parent.parent)
            ):
                if not any(
                    _matches_prefix(imported.module, permitted)
                    for permitted in allowlist.permitted_prefixes
                ):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)}:{imported.lineno} — "
                        f"{allowlist.name} may not import {imported.module!r}; "
                        f"permitted prefixes are "
                        f"{', '.join(sorted(allowlist.permitted_prefixes))} "
                        f"({allowlist.rationale})"
                    )

    return violations


def main() -> int:
    scanned = sum(len(_python_files(b.root)) for b in BOUNDARIES)
    violations = check()
    if violations:
        print(f"import-boundary violations ({len(violations)}):")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print(f"import boundaries clean ({scanned} files across {len(BOUNDARIES)} trees)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
