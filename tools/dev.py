#!/usr/bin/env python3
"""Cross-platform developer entry point for the monorepo.

This file is authoritative; the root Makefile is a short POSIX convenience
wrapper. Every subprocess is invoked with an argument list, every path uses
``pathlib``, and virtual-environment executables resolve correctly on Windows.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

#: Force UTF-8 stdio in every child process.
#:
#: Windows defaults `sys.stdout.encoding` to the ANSI code page -- cp1252 on this
#: host, for a piped stream as well as a console -- and cp1252 cannot encode an
#: emoji. MLflow's `set_terminated` writes "\U0001f3c3 View run ... at: ..." from
#: inside the run context manager's `__exit__`, so a stage that had finished all of
#: its real work still died, with the traceback pointing at contextlib rather than
#: at anything the pipeline does. It cost a complete 3h20m backtest: all thirteen
#: rolling origins were scored and logged, then the process raised on the print and
#: the bundle -- written after the context exits -- was never created.
#:
#: `PYTHONUTF8=1` is read by any CPython at startup, so every venv subprocess picks
#: it up by inheritance, and it changes nothing on macOS or Linux where stdio is
#: already UTF-8. `setdefault` so an explicit host setting still wins.
os.environ.setdefault("PYTHONUTF8", "1")

#: ...and fix THIS process's own streams, which the variable above cannot reach.
#:
#: The same defect appeared three times because each fix addressed one leg of a
#: round trip instead of the stream underneath it:
#:
#:   1. the child WROTE the emoji to cp1252            -> PYTHONUTF8 above
#:   2. the parent DECODED the child's UTF-8 as cp1252 -> encoding="utf-8" on capture
#:   3. the parent RE-PRINTED it to its own cp1252 stdout  <- here
#:
#: An interpreter fixes its stdio encoding at startup, so setting PYTHONUTF8 in
#: os.environ only ever helped children; this process kept the ANSI code page it was
#: born with. Reconfiguring the streams closes the whole class at the source rather
#: than at each print site, which is why the first two fixes did not hold.
#: errors="replace" because a stage's output is worth more than a glyph -- the third
#: failure discarded a 3-hour backtest's result block over one character.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        # Not a reconfigurable text stream (redirected to a pipe wrapper, or already
        # detached). Nothing to do: the capture-side fix still applies.
        pass

REPO_ROOT = Path(__file__).resolve().parent.parent
INGESTION_ENV = REPO_ROOT / "ingestion" / ".venv"
ML_ENV = REPO_ROOT / "ml" / ".venv"
DATAGEN_ENV = REPO_ROOT / "datagen" / ".venv"
DB_ENV = REPO_ROOT / "db" / ".venv"
COMPOSE_FILE = REPO_ROOT / "deploy" / "compose.yaml"
COMPOSE_ENV = REPO_ROOT / "deploy" / ".env"
COMPOSE_ENV_EXAMPLE = REPO_ROOT / "deploy" / ".env.example"
ACCEPTANCE_EVALUATION_VERSION = (
    "cohorted-seasonal-cold-start-recomputation/v4"
)

#: Kept beside the evaluation version because the two move together: the hard per-cohort
#: coverage gate is what acceptance-v5 means, and a v4 document was scored before it bound.
ACCEPTANCE_SCHEMA_GENERATION = "retail-forecast-acceptance/v5"


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


def _npm() -> str:
    """Resolve ``npm`` to something ``CreateProcess`` can actually execute.

    On Windows npm is ``npm.CMD``, a batch script rather than an executable, and
    ``subprocess.run(["npm", ...])`` without a shell fails with
    ``FileNotFoundError: [WinError 2]`` before running anything -- so every npm
    step here was Windows-broken while working on macOS and Linux, where npm is an
    ordinary file on PATH. ``shutil.which`` applies ``PATHEXT`` on Windows and
    returns the plain path elsewhere, so one call serves all three targets without
    a platform branch and without ``shell=True``.
    """

    resolved = shutil.which("npm")
    if resolved is None:
        raise RuntimeError(
            "npm is not on PATH; install Node.js 22.12+ or 24 LTS and reopen the shell"
        )
    return resolved


def _go_test_command(*flags: str, require_race: bool = True) -> list[str]:
    """``go test`` with the race detector when the host can actually run it.

    ``-race`` requires cgo, and cgo requires a C compiler. macOS and Linux have
    one through the Xcode command line tools or the distro toolchain, so the
    detector stays on there and nothing about those runs changes. A stock Windows
    host has none, and ``go test -race`` then fails with "-race requires cgo"
    without executing a single test -- which is a false red rather than a finding.

    The fallback is deliberately loud. A gate that quietly stops checking for data
    races still reports success, and that is worse than a gate that says out loud
    which check it dropped and how to restore it.
    """

    command = ["go", "test", *flags]
    probe = subprocess.run(
        ["go", "env", "CGO_ENABLED", "CC"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = probe.stdout.splitlines() if probe.returncode == 0 else []
    enabled = lines[0].strip() if lines else "0"
    compiler = lines[1].strip() if len(lines) > 1 else ""
    if enabled == "1" and compiler and shutil.which(compiler):
        return [*command, "-race", "./..."]
    if require_race:
        # tasks.md states plainly that `verify` cannot pass until the race detector
        # runs, and that race evidence is not optional for a concurrent API. A loud
        # notice followed by exit 0 contradicted both: the gate reported success while
        # skipping the check. Degrading is now opt-in per command, never silent.
        raise SystemExit(
            "go test -race cannot run here: the race detector needs cgo and a C "
            f"compiler; CGO_ENABLED={enabled or 'unset'} and CC={compiler or 'unset'} "
            "is not resolvable on PATH. Install a C toolchain (mingw-w64 on Windows, "
            "Xcode command line tools on macOS) and set CGO_ENABLED=1. To run the Go "
            "tests without the detector -- which is NOT race evidence -- use "
            "`tools/dev.py api-test --allow-missing-race`."
        )
    print(
        "NOTICE: running go test WITHOUT -race. The race detector needs cgo and a C "
        f"compiler; CGO_ENABLED={enabled or 'unset'} and CC={compiler or 'unset'} is "
        "not resolvable on PATH. Install a C toolchain (mingw-w64 on Windows, Xcode "
        "command line tools on macOS) and set CGO_ENABLED=1 to restore it.",
        file=sys.stderr,
        flush=True,
    )
    return [*command, "./..."]


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


def _committed_pin_publication() -> str | None:
    """The publication fingerprint `contracts/ml/expected-pin.json` names.

    Read rather than cached: the pin moves when a publication is re-derived, and
    a stale copy here would reintroduce the arbitrary tiebreak it exists to
    remove.
    """

    try:
        pin = json.loads(
            (REPO_ROOT / "contracts" / "ml" / "expected-pin.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return None
    return (pin.get("publication") or {}).get("semanticFingerprint")


def _discover_forecast_run() -> tuple[Path, str]:
    """Return the newest decision-#82 governed run and its lifecycle status.

    Discovery keys on the manifest, never on the directory name: three
    superseded bundles are still named `forecast_run_accepted_*` while carrying a
    rejected verdict under the current authority, so a name-based glob would
    resurrect them.

    An accepted candidate is preferred. When none exists the gate runs in
    governed NO-GO mode against a rejected candidate, because the plan requires
    the same stateful gate on both closure branches: the rejected publication
    path and fail-closed serving are themselves the evidence.
    """

    override = os.environ.get("RETAIL_TEST_FORECAST_RUN")
    if override:
        candidate = Path(override).expanduser().resolve()
        if not candidate.is_dir():
            raise RuntimeError(
                f"RETAIL_TEST_FORECAST_RUN is not a directory: {candidate}"
            )
        return candidate, os.environ.get(
            "RETAIL_TEST_FORECAST_LIFECYCLE",
            "accepted",
        )

    accepted: list[tuple[str, Path]] = []
    rejected: list[tuple[str, Path]] = []
    artifact_root = REPO_ROOT / "ml" / "data" / "artifacts"
    for manifest_path in artifact_root.glob("*/forecast-run-manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        model_policy = manifest.get("modelPolicy") or {}
        if model_policy.get("acceptanceEvaluation") != ACCEPTANCE_EVALUATION_VERSION:
            continue
        # Decision #86 requires every bundle to declare its candidate class. A
        # manifest published before that field existed cannot verify, so selecting
        # it would fail the gate on a superseded bundle rather than on the current
        # one. Same intent as the acceptance-generation filter above: discovery
        # only offers candidates the current verifier can accept.
        if "candidateClass" not in model_policy:
            continue
        # Decision #86 §3 puts the candidate class in the acceptance document too.
        # A bundle whose acceptance disagrees with its manifest predates that fix and
        # cannot verify, so offering it would fail the gate on a superseded bundle
        # instead of on the current one.
        acceptance_path = manifest_path.parent / "forecast_acceptance.json"
        try:
            acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Decision #85's hard coverage gate ships as acceptance-v5, paired with
        # verifier-v5 and migration 0007. A v4 bundle was scored while the gate was
        # report-only, so the current verifier refuses it and materialisation refuses it:
        # offering it here would fail the gate on a superseded bundle instead of on the
        # one that would actually serve. Same intent as the filters above.
        if acceptance.get("schemaVersion") != ACCEPTANCE_SCHEMA_GENERATION:
            continue
        if acceptance.get("candidateClass") != model_policy["candidateClass"]:
            continue
        # And it must be pinned to the publication the repository currently pins.
        # Two bundles refit on different publications share a decisionAsOf, so the
        # newest-wins tiebreak fell through to the directory name -- which picked
        # `forecast_run_tenyear` over `forecast_run_r2` on nothing but the letter
        # "t", and failed the gate on a bundle that cannot serve. Same intent as
        # every filter above: only offer candidates the current verifier accepts.
        input_bundle = manifest.get("inputBundle") or {}
        published = input_bundle.get("publicationSemanticFingerprint") or (
            input_bundle.get("publication") or {}
        ).get("semanticFingerprint")
        if published != _committed_pin_publication():
            continue
        entry = (str(manifest.get("decisionAsOf", "")), manifest_path.parent)
        if manifest.get("lifecycleStatus") == "accepted":
            accepted.append(entry)
        else:
            rejected.append(entry)
    for bucket, status in ((accepted, "accepted"), (rejected, "rejected")):
        if bucket:
            newest = max(bucket, key=lambda value: (value[0], str(value[1])))
            return newest[1], status
    raise RuntimeError(
        "No decision-#82 governed forecast run is available. Set "
        "RETAIL_TEST_FORECAST_RUN or complete the Phase 3 publication first."
    )


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
    forecast_run, forecast_lifecycle = _discover_forecast_run()
    integration_environment["RETAIL_TEST_FORECAST_RUN"] = str(forecast_run)
    integration_environment["RETAIL_TEST_FORECAST_LIFECYCLE"] = forecast_lifecycle
    if forecast_lifecycle != "accepted":
        print(
            f"gate mode: governed NO-GO against rejected candidate {forecast_run.name}; "
            "serving must stay fail-closed",
            flush=True,
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
            _go_test_command("-count=1"),
            REPO_ROOT / "api",
            integration_environment,
        ),
        ([_npm(), "test"], REPO_ROOT / "ui", None),
        ([_npm(), "run", "typecheck"], REPO_ROOT / "ui", None),
        ([_npm(), "run", "build"], REPO_ROOT / "ui", None),
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
    result = _run([str(ingestion), str(generator), "--check"])
    if result:
        return result
    # `P4-0`: a committed selection record must still match a fresh derivation
    # from the retained publication evidence. A hand-edited governance record is
    # indistinguishable from a real one until something recomputes it.
    selections = REPO_ROOT / "tools" / "build_publication_selection.py"
    if selections.is_file():
        return _run([str(ingestion), str(selections), "--check"])
    return 0


def _utc_now() -> str:
    """The event time for an approval, as RFC 3339 UTC.

    `approvedAt` is audit evidence and is excluded from semantic identity, so a real
    clock here cannot move a selectionId -- the value is stored in the ledger once
    and read back verbatim, which keeps `--check` reproducible. The previous default
    was the epoch, and it put "approved 1970-01-01" into committed audit records: a
    field whose only job is to say when something happened, saying something false.
    """

    return (
        datetime.datetime.now(datetime.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_run_id(value: object) -> bool:
    """A single portable path component in the repository's run-id namespace."""

    if not isinstance(value, str) or not value.startswith("run-"):
        return False
    suffix = value[4:]
    return (
        1 <= len(suffix) <= 128
        and suffix[0].isascii()
        and suffix[0].isalnum()
        and all(
            character.isascii()
            and (character.isalnum() or character in "._-")
            for character in suffix
        )
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _selection_module():
    """Import the selection builder as a module so repin can read its ledger."""

    for entry in (REPO_ROOT / "ingestion" / "src", REPO_ROOT / "tools"):
        # Guarded: unconditional inserts grew sys.path by two on every call, so a
        # measurement taken after a single call read as stable when it was not.
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    import build_publication_selection as selection  # noqa: PLC0415

    return selection


def _repin_facts(run_id: str) -> dict[str, object]:
    """The facts an adoption rests on, read from retained evidence only.

    Everything here comes from the run's own `gate-a.json`, `gate-b.json` and
    `publication-manifest.json`. Nothing is transcribed from a plan, a constant or a
    prior record, because the point of an adoption record is to name what THIS
    publication is -- and a value copied from the thing being replaced would make the
    two indistinguishable.
    """

    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run_id

    # All three sources, one way. Only `gate-b.json` had an existence pre-check, so a
    # run missing Gate A or the manifest raised FileNotFoundError -- which is not a
    # SystemExit, so `command_repin`'s handler did not catch it and the pipeline lost
    # its stage timings to a traceback. `build_pin` already loops over its four files
    # like this; a function whose docstring names three sources should not refuse
    # cleanly for one of them and crash for the other two.
    def _evidence(name: str, required: dict, optional: dict | None = None) -> dict:
        path = evidence / name
        if not path.is_file():
            raise SystemExit(f"retained evidence is absent: {path}")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except OSError as broken:
            # PermissionError, a deletion between the is_file() check and this read,
            # a disk error -- all OSError, none a SystemExit, so each escaped the
            # handler like the four shapes before it. The is_file() check above cannot
            # close the race on its own; only catching the read can.
            raise SystemExit(f"retained evidence could not be read: {path}: {broken}")
        except UnicodeDecodeError as broken:
            # `read_text` raises this BEFORE json ever sees the bytes, so catching
            # JSONDecodeError alone missed it -- the fourth shape of the same escape.
            raise SystemExit(f"retained evidence is not valid UTF-8: {path}: {broken}")
        except json.JSONDecodeError as broken:
            raise SystemExit(f"retained evidence is not valid JSON: {path}: {broken}")
        # Valid JSON is not enough: `[]`, `null` and a bare scalar all parse, and
        # every reader below calls `.get()` on the result. That AttributeError is not
        # a SystemExit, so it escaped the handler and cost the stage timings again --
        # the same failure this loader was written to stop, one type further out.
        if not isinstance(document, dict):
            raise SystemExit(
                f"retained evidence is not a JSON object: {path} parsed as "
                f"{type(document).__name__}"
            )
        # ...and an object is still not enough. `{}` parses, is a dict, and then meets
        # `gate_a["semanticFingerprint"]` -- a KeyError, which is no more a SystemExit
        # than the AttributeError before it or the FileNotFoundError before that. Each
        # round this escaped one type further out, so the fields are declared here
        # rather than discovered by the first line that happens to need one.
        for field, kinds in required.items():
            if field not in document:
                raise SystemExit(
                    f"retained evidence is incomplete: {path} has no {field!r}"
                )
            if not isinstance(document[field], kinds):
                raise SystemExit(
                    f"retained evidence is malformed: {path} field {field!r} is "
                    f"{type(document[field]).__name__}, expected "
                    f"{' or '.join(k.__name__ for k in (kinds if isinstance(kinds, tuple) else (kinds,)))}"
                )
        # Optional means "may be absent", never "may be anything". `businessControls`
        # was read as `(manifest.get("businessControls") or {}).keys()`, so absent,
        # null and {} were all covered -- and a non-empty list or string went straight
        # to `.keys()` and raised AttributeError past the handler. The declaration
        # should cover every field this function READS, not only those it requires.
        for field, kinds in (optional or {}).items():
            if field in document and not isinstance(document[field], kinds):
                raise SystemExit(
                    f"retained evidence is malformed: {path} optional field "
                    f"{field!r} is {type(document[field]).__name__}, expected "
                    f"{' or '.join(k.__name__ for k in (kinds if isinstance(kinds, tuple) else (kinds,)))}"
                )
        return document

    gate_a = _evidence(
        "gate-a.json", {"status": str, "semanticFingerprint": str}
    )
    manifest = _evidence(
        "publication-manifest.json",
        {
            "sourceSnapshotId": str,
            "gateBSemanticFingerprint": str,
            "semanticFingerprint": str,
            "objects": list,
            "duckdb": dict,
        },
        optional={"businessControls": dict, "capabilityMask": dict},
    )
    if not isinstance(manifest["duckdb"].get("sha256"), str):
        raise SystemExit(
            f"retained evidence is malformed: {evidence / 'publication-manifest.json'}"
            " field 'duckdb.sha256' is missing or not a string"
        )
    # Gate B is READ, not assumed. The docstring said this file was one of the
    # sources and it never was: the fingerprint and the capability mask both came
    # from the manifest's copy of them, so a missing, failing or inconsistent
    # `gate-b.json` still produced a confident proposal claiming Gate B passed.
    # Only `--approve` found out, one step later, via the rollback.
    gate_b = _evidence(
        "gate-b.json",
        {"status": str, "semanticFingerprint": str, "capabilityMask": dict},
    )
    for label, value in (
        ("gate-a.json semanticFingerprint", gate_a["semanticFingerprint"]),
        ("gate-b.json semanticFingerprint", gate_b["semanticFingerprint"]),
        ("publication sourceSnapshotId", manifest["sourceSnapshotId"]),
        (
            "publication gateBSemanticFingerprint",
            manifest["gateBSemanticFingerprint"],
        ),
        ("publication semanticFingerprint", manifest["semanticFingerprint"]),
        ("publication duckdb.sha256", manifest["duckdb"]["sha256"]),
    ):
        if not _is_sha256(value):
            raise SystemExit(
                f"retained evidence is malformed: {run_id} {label} is not a "
                "lowercase SHA-256 fingerprint"
            )
    if gate_b.get("semanticFingerprint") != manifest.get(
        "gateBSemanticFingerprint"
    ):
        raise SystemExit(
            f"{run_id}: gate-b.json fingerprint "
            f"{str(gate_b.get('semanticFingerprint'))[:12]}… disagrees with the "
            f"publication manifest's "
            f"{str(manifest.get('gateBSemanticFingerprint'))[:12]}…; the evidence "
            "for this run is inconsistent with itself"
        )
    # The mask from Gate B itself, with NO fallback to the manifest. The fallback was
    # a residue of the very thing this was fixing: a Gate B carrying no mask silently
    # handed the capability verdict back to the transcription, so the proposal passed
    # while nothing had actually read a mask from the gate. Absent or malformed is
    # refused, because "I could not find the evidence" and "the evidence says yes"
    # must never produce the same outcome.
    mask = gate_b.get("capabilityMask")
    if not isinstance(mask, dict) or not mask:
        raise SystemExit(
            f"{run_id}: gate-b.json carries no usable capabilityMask, so no "
            "capability verdict can be derived from the gate that produced it"
        )
    required = (
        "demand_forecast_non_pit",
        "inventory_replenishment_current_snapshot",
        "inventory_replenishment_replay",
    )
    # The shared strict reader, not a third private copy of the same check. It
    # raises on a malformed entry, which keeps "cannot interpret" distinct from "the
    # gate says no" -- so `missing` below only ever holds genuine gate verdicts, and
    # the reason string that interpolates it cannot misreport one as the other.
    capability_is_available = _selection_module().capability_is_available
    missing = [
        name
        for name in required
        if not capability_is_available(
            mask, name, subject=f"{run_id} gate-b.json"
        )
    ]
    return {
        "run": run_id,
        "sourceSnapshotId": manifest["sourceSnapshotId"],
        "gateAStatus": gate_a.get("status"),
        "gateBStatus": gate_b.get("status"),
        "gateASemanticFingerprint": gate_a["semanticFingerprint"],
        "gateBSemanticFingerprint": gate_b["semanticFingerprint"],
        "publicationSemanticFingerprint": manifest["semanticFingerprint"],
        "objectCount": len(manifest["objects"]),
        "duckdbSha256": manifest["duckdb"]["sha256"],
        "missingRequiredCapabilities": missing,
        # Summarised, not embedded. The raw block carries the full store topology and
        # made a proposal unreadable, which defeats the purpose of showing a human the
        # facts before they approve them.
        "businessControlKeys": sorted(
            (manifest.get("businessControls") or {}).keys()
        ),
    }


def _repin_previous() -> dict[str, object]:
    """What the pin currently names, so a proposal can show the delta."""

    pin_path = REPO_ROOT / "contracts" / "ml" / "expected-pin.json"
    if not pin_path.is_file():
        return {}
    try:
        pin = json.loads(pin_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as broken:
        raise SystemExit(f"the current pin is unreadable: {pin_path}: {broken}")
    if not isinstance(pin, dict):
        raise SystemExit(
            f"the current pin is {type(pin).__name__}, expected an object: {pin_path}"
        )
    publication = pin.get("publication")
    if not isinstance(publication, dict):
        raise SystemExit(f"the current pin has no publication object: {pin_path}")
    duckdb = publication.get("duckdb")
    if not isinstance(duckdb, dict):
        raise SystemExit(f"the current pin has no publication.duckdb object: {pin_path}")
    expected = {
        "sourceSnapshotId": pin.get("sourceSnapshotId"),
        "publication.semanticFingerprint": publication.get("semanticFingerprint"),
        "publication.duckdb.sha256": duckdb.get("sha256"),
    }
    invalid = [name for name, value in expected.items() if not _is_sha256(value)]
    object_count = publication.get("objectCount")
    object_count_valid = type(object_count) is int and object_count >= 0
    if invalid or not object_count_valid:
        fields = invalid + (
            []
            if object_count_valid
            else ["publication.objectCount"]
        )
        raise SystemExit(
            f"the current pin has missing or malformed fields: {', '.join(fields)}"
        )
    return {
        "sourceSnapshotId": pin.get("sourceSnapshotId"),
        "publicationSemanticFingerprint": publication["semanticFingerprint"],
        "objectCount": publication["objectCount"],
        "duckdbSha256": duckdb["sha256"],
    }


def _repin_reasons(facts: dict, previous: dict, automatic: bool) -> dict[str, str]:
    """Compose the four reason strings from measured deltas.

    A derived reason is worth more than a typed one precisely because it cannot be
    vague: it names which fingerprints moved and which controls did not. What it
    cannot supply is judgement, which is why the automatic variant says so in its
    own text rather than reading like a person wrote it.
    """

    moved = [
        name
        for name, new_key in (
            ("sourceSnapshotId", "sourceSnapshotId"),
            ("publication fingerprint", "publicationSemanticFingerprint"),
            ("curated DuckDB hash", "duckdbSha256"),
        )
        if previous.get(new_key) and previous.get(new_key) != facts.get(new_key)
    ]
    controls = facts.get("businessControlKeys") or []
    control_note = (
        f"Business controls present for {len(controls)} group(s) in this run's own "
        f"manifest: {', '.join(controls)}."
        if controls
        else "No business-control block was present in this manifest."
    )
    origin = (
        "Adopted automatically by the repin policy: no actor was supplied, so this "
        "record asserts a POLICY decision on derived evidence and not a human "
        "review. Anyone relying on it should read the facts below, not the fact that "
        "it was approved."
        if automatic
        else "Adopted on explicit human approval."
    )
    delta = (
        ", ".join(moved)
        if moved
        else (
            "nothing the pin names moved, so this publication is byte-equivalent to "
            "the one it replaces at every pinned field"
        )
    )
    return {
        "candidate": (
            f"{origin} Publication for {facts['run']} passed Gate A "
            f"({facts['gateAStatus']}) and Gate B ({facts.get('gateBStatus')}), "
            f"both read from this run's own gate files, with all three required "
            f"capabilities available in Gate B's mask. Relative to the previous "
            f"pin: {delta}. "
            f"{control_note}"
        ),
        "approved": (
            "Gate A, Gate B, the capability mask, the publication fingerprint and "
            "the curated DuckDB hash were all derived from this run's own retained "
            f"evidence rather than transcribed: Gate A "
            f"{facts['gateASemanticFingerprint'][:8]}, Gate B "
            f"{facts['gateBSemanticFingerprint'][:8]}, publication "
            f"{facts['publicationSemanticFingerprint'][:8]}, DuckDB "
            f"{facts['duckdbSha256'][:8]}, {facts['objectCount']} curated objects."
        ),
        "active": (
            "Adopted as the active source authority for this scope. The preceding "
            "generation is superseded in the same change, so exactly one selection "
            "is active per scope (decision #90)."
        ),
        "supersede": (
            f"Replaced as source authority by the publication for {facts['run']}. "
            f"Compared with the pin this record's publication carried: {delta}."
        ),
    }


_REPIN_TRANSACTION_SCHEMA = "retail-repin-transaction/v1"


def _repin_state_paths(selection) -> tuple[Path, Path]:
    """Stable lock anchor and crash journal beside the governed ledger."""

    ledger = selection.GENERATIONS_PATH
    return ledger.with_suffix(".lock"), ledger.with_suffix(".transaction.json")


def _acquire_repin_lock(path: Path):
    """Acquire a kernel-owned, non-blocking lock that cannot become stale.

    An ``O_EXCL`` marker survives a killed process and strands every later adoption.
    A byte-range/file lock is released by the operating system when the process dies;
    the small ignored file is only a stable inode on which to take that lock.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as busy:
                raise BlockingIOError(str(busy)) from busy
        else:
            import fcntl  # noqa: PLC0415

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as busy:
                raise BlockingIOError(str(busy)) from busy
        return handle
    except BaseException:
        handle.close()
        raise


def _release_repin_lock(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl  # noqa: PLC0415

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Closing the descriptor is the authoritative release on both platforms.
        # Do not turn a completed adoption into a reported failure because an
        # explicit unlock raced with process teardown.
        pass
    finally:
        # Closing also releases the kernel lock if the explicit unlock failed.
        handle.close()


def _repin_snapshot(selection) -> dict[str, object]:
    """Capture every file an adoption is allowed to change."""

    ledger = selection.GENERATIONS_PATH
    pin = REPO_ROOT / "contracts" / "ml" / "expected-pin.json"
    records = REPO_ROOT / "contracts" / "evidence" / "publication-selections"
    return {
        "ledger": ledger.read_bytes() if ledger.is_file() else None,
        "pin": pin.read_bytes() if pin.is_file() else None,
        "records": {
            path.name: path.read_bytes()
            for path in sorted(records.glob("*.json"))
        },
    }


def _encoded_repin_snapshot(snapshot: dict[str, object]) -> dict[str, object]:
    def encode(value: bytes | None) -> str | None:
        return base64.b64encode(value).decode("ascii") if value is not None else None

    records = snapshot["records"]
    if not isinstance(records, dict):
        raise TypeError("repin snapshot records must be an object")
    return {
        "ledger": encode(snapshot["ledger"]),
        "pin": encode(snapshot["pin"]),
        "records": {name: encode(payload) for name, payload in records.items()},
    }


def _write_repin_transaction(
    selection, journal: Path, snapshot: dict[str, object], *, state: str
) -> None:
    if state not in ("prepared", "committed"):
        raise ValueError(f"unsupported repin transaction state {state!r}")
    document = {
        "schemaVersion": _REPIN_TRANSACTION_SCHEMA,
        "repoRoot": str(REPO_ROOT.resolve()),
        "state": state,
        "before": _encoded_repin_snapshot(snapshot),
    }
    selection.atomic_write_bytes(
        journal,
        (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _load_repin_transaction(journal: Path) -> tuple[str, dict[str, object]]:
    """Read and fully validate a crash journal before restoring any path."""

    try:
        document = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as broken:
        raise RuntimeError(f"cannot read crash journal {journal}: {broken}") from broken
    if not isinstance(document, dict):
        raise RuntimeError(f"crash journal {journal} is not a JSON object")
    if document.get("schemaVersion") != _REPIN_TRANSACTION_SCHEMA:
        raise RuntimeError(f"crash journal {journal} has an unsupported schema")
    recorded_root = document.get("repoRoot")
    if not isinstance(recorded_root, str) or os.path.normcase(recorded_root) != os.path.normcase(
        str(REPO_ROOT.resolve())
    ):
        raise RuntimeError(
            f"crash journal {journal} belongs to {recorded_root!r}, not this checkout"
        )
    state = document.get("state")
    if state not in ("prepared", "committed"):
        raise RuntimeError(f"crash journal {journal} has invalid state {state!r}")
    before = document.get("before")
    if not isinstance(before, dict):
        raise RuntimeError(f"crash journal {journal} has no valid before snapshot")
    missing_before = [
        field for field in ("ledger", "pin", "records") if field not in before
    ]
    if missing_before:
        raise RuntimeError(
            f"crash journal {journal} before snapshot is missing "
            f"{', '.join(missing_before)}"
        )

    def decode(value, label: str) -> bytes | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise RuntimeError(f"crash journal field {label} is not base64 text")
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as broken:
            raise RuntimeError(
                f"crash journal field {label} is not valid base64"
            ) from broken

    records = before.get("records")
    if not isinstance(records, dict):
        raise RuntimeError("crash journal before.records is not an object")
    decoded_records: dict[str, bytes] = {}
    for name, payload in records.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or "/" in name
            or "\\" in name
            or not name.endswith(".json")
        ):
            raise RuntimeError(f"crash journal contains unsafe record name {name!r}")
        decoded = decode(payload, f"before.records.{name}")
        if decoded is None:
            raise RuntimeError(f"crash journal record {name!r} has no payload")
        decoded_records[name] = decoded
    return state, {
        "ledger": decode(before["ledger"], "before.ledger"),
        "pin": decode(before["pin"], "before.pin"),
        "records": decoded_records,
    }


def _restore_repin_snapshot(selection, snapshot: dict[str, object]) -> None:
    """Idempotently restore a prepared transaction's complete before-image."""

    ledger = selection.GENERATIONS_PATH
    pin = REPO_ROOT / "contracts" / "ml" / "expected-pin.json"
    directory = REPO_ROOT / "contracts" / "evidence" / "publication-selections"
    directory.mkdir(parents=True, exist_ok=True)
    records = snapshot["records"]
    if not isinstance(records, dict):
        raise RuntimeError("repin recovery snapshot has invalid records")

    for path, payload in ((ledger, snapshot["ledger"]), (pin, snapshot["pin"])):
        if payload is None:
            path.unlink(missing_ok=True)
        elif isinstance(payload, bytes):
            selection.atomic_write_bytes(path, payload)
        else:
            raise RuntimeError(f"repin recovery snapshot for {path} is invalid")

    for path in directory.glob("*.json"):
        if path.name not in records:
            path.unlink()
    for name, payload in records.items():
        if not isinstance(payload, bytes):
            raise RuntimeError(f"repin recovery snapshot for {name} is invalid")
        selection.atomic_write_bytes(directory / name, payload)


def _recover_repin_transaction(selection, journal: Path) -> str | None:
    """Recover a killed adoption while holding the process-lifetime lock."""

    if not journal.exists():
        return None
    state, snapshot = _load_repin_transaction(journal)
    if state == "prepared":
        _restore_repin_snapshot(selection, snapshot)
    # A committed marker is written only after all builders have succeeded. In that
    # state the correct recovery is finalization, never undoing a completed adoption.
    journal.unlink()
    return state


def command_repin(args: argparse.Namespace) -> int:
    """Propose or approve the adoption of a publication as source authority.

    Decision #89 makes moving the pin a governed act. This does not weaken that: it
    removes the five coordinated file edits that expressing one decision used to
    take, and keeps the decision itself an explicit, separately-invoked step whose
    record states honestly whether a human made it.
    """

    # Argument validation first: cheaper than reading evidence, and previously
    # unreachable for a run whose evidence was absent.
    actor = args.actor.strip() if isinstance(args.actor, str) else None
    reason = args.reason.strip() if isinstance(args.reason, str) else None
    if args.actor is not None and not actor:
        print("--actor must contain a non-whitespace identity", file=sys.stderr)
        return 2
    if args.reason is not None and not reason:
        print("--reason must contain a non-whitespace explanation", file=sys.stderr)
        return 2
    if bool(actor) != bool(reason):
        print(
            "--actor and --reason must be supplied together: an actor without a "
            "reason is a rubber stamp, and a reason without an actor is prose that "
            "can claim a review the metadata denies",
            file=sys.stderr,
        )
        return 2
    reason_code = str(args.reason_code or "").strip()
    if actor and reason_code == "AUTOMATED_REPIN_ADOPTION":
        reason_code = "HUMAN_REPIN_ADOPTION"
    if not actor and reason_code != "AUTOMATED_REPIN_ADOPTION":
        print(
            f"--reason-code {reason_code!r} is not valid for an automatic adoption; "
            "omit it or use AUTOMATED_REPIN_ADOPTION",
            file=sys.stderr,
        )
        return 2

    selection = _selection_module()
    lock_path, journal_path = _repin_state_paths(selection)
    try:
        selection._approval_mode(
            actor or selection.AUTOMATED_ACTOR,
            reason_code,
            where="repin arguments",
        )
    except SystemExit as refusal:
        print(f"refusing: {refusal}", file=sys.stderr)
        return 2
    ingestion = _require_python(INGESTION_ENV, "ingestion")
    run_id = args.run_id or _newest_published_run()
    if run_id is None:
        print(
            "no published run found under ingestion/data/evidence with a "
            "publication-manifest.json",
            file=sys.stderr,
        )
        return 2
    if not _is_run_id(run_id):
        print(
            f"invalid run id {run_id!r}: expected one portable run-... path component",
            file=sys.stderr,
        )
        return 2

    # A killed process may have written the new ledger before it reached the pin.
    # Recover before the optimistic "already selected" check, otherwise that
    # half-written ledger would turn the repair command into a no-op forever. This
    # preflight is also used by proposal-only invocations; restoring an interrupted
    # transaction is part of making the repository readable again, not a new
    # adoption decision.
    if journal_path.exists():
        try:
            recovery_lock = _acquire_repin_lock(lock_path)
        except BlockingIOError:
            print(
                f"another adoption holds {lock_path.name}; retry after it completes",
                file=sys.stderr,
            )
            return 1
        except OSError as broken:
            print(f"cannot acquire the adoption lock: {broken}", file=sys.stderr)
            return 1
        try:
            try:
                recovered = _recover_repin_transaction(selection, journal_path)
            except (OSError, RuntimeError) as broken:
                print(
                    f"refusing: a prior adoption has an unrecoverable transaction "
                    f"journal: {broken}",
                    file=sys.stderr,
                )
                return 1
            if recovered == "prepared":
                print(
                    "recovered and rolled back a previously interrupted adoption",
                    file=sys.stderr,
                )
            elif recovered == "committed":
                print(
                    "finalized the journal of a previously completed adoption",
                    file=sys.stderr,
                )
        finally:
            _release_repin_lock(recovery_lock)

    # Already adopted -> no-op, never a second chain. Without this, re-running
    # `repin --approve` appended a fresh generation for a run a committed record
    # already selects, producing duplicate candidate/approved/active records that
    # share one selectionId and break the one-active-per-scope invariant. The
    # pipeline stage checked this and the standalone command did not, which is
    # exactly the asymmetry that makes a governance tool unsafe to re-run.
    try:
        already_selected = _generation_names_run(run_id)
    except SystemExit as refusal:
        print(f"refusing: {refusal}", file=sys.stderr)
        return 1
    if already_selected:
        print(
            f"{run_id} is already selected by a committed record; nothing to adopt. "
            "Re-running an adoption is a no-op, not a second generation."
        )
        return 0

    # `_repin_facts` refuses inconsistent or absent evidence by raising SystemExit,
    # which would propagate straight past `command_pipeline`'s `_PipelineFailure`
    # handler and skip `_report_stage_timings()`. Nothing is written either way --
    # this runs before the ledger snapshot -- but the cost is the timing table on a
    # stage that can be hours into a run, which is precisely the case the
    # instrumentation exists for. Converted to a return code so it stays in reach.
    try:
        facts = _repin_facts(run_id)
        previous = _repin_previous()
    except SystemExit as refusal:
        print(f"refusing: {refusal}", file=sys.stderr)
        return 1
    # Gate A is interpolated into the candidate reason as "passed Gate A (...)",
    # so a non-pass run would produce a governance record asserting it passed while
    # naming the failure in the same sentence. The builder catches it a step later
    # and the rollback unwinds it, but a record should not be able to say that at
    # all -- refusing here is cheaper than relying on a downstream catch.
    for gate, key in (("A", "gateAStatus"), ("B", "gateBStatus")):
        if facts.get(key) != "pass":
            print(
                f"refusing: Gate {gate} is {facts.get(key)!r}, not 'pass'",
                file=sys.stderr,
            )
            return 1
    if facts["missingRequiredCapabilities"]:
        print(
            "refusing: this publication does not offer every required capability: "
            f"{', '.join(facts['missingRequiredCapabilities'])}",
            file=sys.stderr,
        )
        return 1

    print(json.dumps({"proposal": facts, "currentPin": previous}, indent=2,
                     sort_keys=True))
    if not args.approve:
        print(
            f"\nProposal only. Nothing was written.\n"
            f"Approve with:\n"
            f"  tools/dev.py repin --approve --run-id {run_id} "
            f"[--actor <name> --reason <why>]\n"
            f"Omitting --actor records the automated policy actor "
            f"({selection.AUTOMATED_ACTOR}) rather than a person.",
            file=sys.stderr,
        )
        return 0

    # Only the writing path needs serialization. The proposal above is read-only, but
    # everything below -- the second no-op check, the authority/evidence comparison,
    # and every rollback snapshot -- is protected by the same lock. Capturing those
    # values before the lock allowed a failed process to restore r7 over another
    # process's completed r8 adoption.
    try:
        lock = _acquire_repin_lock(lock_path)
    except BlockingIOError:
        print(
            f"another adoption holds {lock_path.name}; retry after it completes",
            file=sys.stderr,
        )
        return 1
    except OSError as broken:
        print(f"cannot acquire the adoption lock: {broken}", file=sys.stderr)
        return 1

    try:
        try:
            recovered = _recover_repin_transaction(selection, journal_path)
        except (OSError, RuntimeError) as broken:
            print(
                f"refusing: a prior adoption has an unrecoverable transaction "
                f"journal: {broken}",
                file=sys.stderr,
            )
            return 1
        if recovered == "prepared":
            print(
                "recovered and rolled back a previously interrupted adoption "
                "before preparing this one",
                file=sys.stderr,
            )
        elif recovered == "committed":
            print(
                "finalized the journal of a previously completed adoption",
                file=sys.stderr,
            )

        # The pre-lock check is an optimization; this one is the concurrency guard.
        try:
            already_selected = _generation_names_run(run_id)
        except SystemExit as refusal:
            print(f"refusing: {refusal}", file=sys.stderr)
            return 1
        if already_selected:
            print(
                f"{run_id} was selected while this proposal was being prepared; "
                "nothing to adopt."
            )
            return 0

        try:
            locked_facts = _repin_facts(run_id)
            locked_previous = _repin_previous()
        except SystemExit as refusal:
            print(f"refusing: {refusal}", file=sys.stderr)
            return 1
        if locked_facts != facts or locked_previous != previous:
            print(
                "refusing: the publication evidence or current pin changed after "
                "the proposal was displayed; rerun repin so the approved proposal "
                "matches the state that will be written",
                file=sys.stderr,
            )
            return 1
        reasons = _repin_reasons(facts, previous, automatic=not actor)

        # Snapshot only after the lock. Persist its complete before-image before the
        # first live write: an exception rolls back immediately, while an uncatchable
        # process termination is repaired by the next lock holder.
        snapshot = _repin_snapshot(selection)
        try:
            _write_repin_transaction(
                selection, journal_path, snapshot, state="prepared"
            )
        except (OSError, TypeError, ValueError) as broken:
            print(
                f"refusing: could not prepare the adoption transaction: {broken}",
                file=sys.stderr,
            )
            return 1

        def _roll_back(stage: str) -> None:
            _restore_repin_snapshot(selection, snapshot)
            journal_path.unlink(missing_ok=True)
            print(
                f"repin failed at {stage}; restored the ledger, pin, and complete "
                "selection-record directory to their prior state",
                file=sys.stderr,
            )

        # try/except around everything that writes. Rollback previously ran only when
        # a child returned nonzero, so an OSError from `_run`, or any exception between
        # the ledger write and the last builder, left a half-adoption committed.
        try:
            transaction_env = selection.REPIN_TRANSACTION_ENV
            previous_transaction = os.environ.get(transaction_env)
            os.environ[transaction_env] = str(journal_path.resolve())
            try:
                result, failed_stage = _repin_apply(
                    selection=selection,
                    ingestion=ingestion,
                    run_id=run_id,
                    facts=facts,
                    reasons=reasons,
                    reason_code=reason_code,
                    actor=actor,
                    reason=reason,
                    approved_at=args.approved_at or _utc_now(),
                )
            finally:
                if previous_transaction is None:
                    os.environ.pop(transaction_env, None)
                else:
                    os.environ[transaction_env] = previous_transaction
        except BaseException as failure:
            try:
                _roll_back(f"an unhandled {type(failure).__name__}")
            except BaseException as recovery_failure:
                raise RuntimeError(
                    f"repin failed and automatic rollback also failed; "
                    f"{journal_path} was retained for the next invocation"
                ) from recovery_failure
            raise
        if result:
            _roll_back(failed_stage or "an unnamed builder")
            return result

        # This marker distinguishes a kill after the final verified write from a kill
        # during publication. Recovery preserves the former and rolls back the latter.
        try:
            _write_repin_transaction(
                selection, journal_path, snapshot, state="committed"
            )
        except BaseException:
            try:
                _roll_back("transaction commit")
            except BaseException as recovery_failure:
                raise RuntimeError(
                    f"repin commit and rollback both failed; {journal_path} was "
                    "retained for the next invocation"
                ) from recovery_failure
            raise
        try:
            journal_path.unlink()
        except OSError as cleanup_failure:
            # The committed marker makes this safe: the next invocation finalizes it
            # without undoing the already verified adoption.
            print(
                f"NOTICE: adoption succeeded but {journal_path.name} could not be "
                f"removed ({cleanup_failure}); the next repin will finalize it",
                file=sys.stderr,
            )
        return 0
    finally:
        _release_repin_lock(lock)


def _repin_apply(
    *, selection, ingestion, run_id, facts, reasons, reason_code, actor, reason,
    approved_at,
) -> tuple[int, str | None]:
    """Write the generation, derive its records, then move the pin."""

    entry = selection.append_generation(
        run=run_id,
        approved_at=approved_at,
        reason_code=reason_code,
        candidate_reason=(reason or reasons["candidate"]),
        approved_reason=reasons["approved"],
        active_reason=reasons["active"],
        supersede_reason=reasons["supersede"],
        actor=actor,
    )
    print(
        f"appended generation {entry['tag']} for {run_id} "
        f"(actor={entry['actor']}, mode={entry['approvalMode']}, "
        f"approvedAt={entry['approvedAt']})"
    )
    builder = REPO_ROOT / "tools" / "build_publication_selection.py"
    for label, command in (
        ("selection ledger", [str(ingestion), str(builder), "--no-clobber"]),
        ("selection ledger verified", [str(ingestion), str(builder), "--check"]),
        (
            "expected pin",
            [
                str(ingestion),
                str(REPO_ROOT / "tools" / "build_expected_pin.py"),
                "--run",
                run_id,
            ],
        ),
    ):
        result = _run(command)
        if result:
            return result, label
    return 0, None


def command_serve(args: argparse.Namespace) -> int:
    """Start the API against the live activation, resolving its scope from the database.

    This automates the LOOKUP, not the authority. The API still requires an explicit
    `-forecast-activation-scope` and still fails closed without one: a scope names the
    exact activation a reader is entitled to, and making the read model self-resolve
    would be a governance change rather than a convenience. What was manual here was
    copying a fingerprint out of psql by hand, which is not a decision anyone makes.
    """

    # Resolve the complete active set once. A failed database lookup must not silently
    # become the newest manifest by mtime, and `.fetchone()` must not turn several
    # active scopes into an arbitrary first row.
    try:
        authorities = _active_forecast_authorities()
        run_id = args.run_id or _active_authority_run(authorities)
    except SystemExit as refusal:
        print(f"refusing: {refusal}", file=sys.stderr)
        return 1
    if not _is_run_id(run_id):
        print(
            f"invalid run id {run_id!r}: expected one portable run-... path component",
            file=sys.stderr,
        )
        return 2
    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run_id
    curated = REPO_ROOT / "ingestion" / "data" / "curated" / run_id
    manifest_path = curated / "publication-manifest.json"
    if not manifest_path.is_file():
        print(f"no publication manifest at {manifest_path}", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as broken:
        print(f"unusable publication manifest {manifest_path}: {broken}", file=sys.stderr)
        return 2
    if not isinstance(manifest, dict) or not isinstance(
        manifest.get("semanticFingerprint"), str
    ):
        print(
            f"publication manifest {manifest_path} has no semanticFingerprint",
            file=sys.stderr,
        )
        return 2
    publication = manifest["semanticFingerprint"]

    # Two independent choices used to be made here and nothing tied them together:
    # the evidence came from `run_id` while the scope came from the newest activation
    # globally. With an older forecast still active the API would start on mismatched
    # lineage and fail closed -- correct, but for a reason nothing on screen explains.
    # Selecting the activation BY this publication's fingerprint makes the pairing
    # explicit, so a genuine mismatch is reported here by name instead.
    #
    # Queried over the configured DSN rather than `docker exec` with a hard-coded
    # container, user and database: `_local_postgres_dsn` already honours
    # RETAIL_POSTGRES_DSN and deploy/.env, and the previous form reported a
    # customised deployment as having no active forecast at all.
    # `_local_postgres_dsn` unconditionally, never the raw environment variable: it
    # is the function that NORMALISES the override, and a supported
    # `postgresql+psycopg://…` value read directly reaches psycopg unparsed and
    # raises. Reading the variable myself skipped the one thing the helper is for.
    matching = [
        row for row in authorities
        if row["publicationSemanticFingerprint"] == publication
    ]
    # The API enforces one global active authority before applying its configured
    # scope. Mirror that invariant here so `serve` never starts a process guaranteed
    # to fail, and so --run-id cannot hide a competing activation.
    if len(authorities) != 1 or len(matching) != 1:
        print(
            f"no active forecast activation for publication {publication[:12]}… "
            f"(the publication {run_id} names). Materialize and activate a forecast "
            "built on THIS publication and retire every competing active scope. "
            f"The database currently exposes {len(authorities)} active row(s), "
            f"{len(matching)} for this publication.",
            file=sys.stderr,
        )
        return 1
    fingerprint = matching[0]["activationScopeFingerprint"]
    print(f"resolved activation scope {fingerprint[:16]}… for {run_id}")
    dsn = _local_postgres_dsn(sqlalchemy=False)
    environment = dict(os.environ)
    # Assignment, not setdefault: an override already in the environment may be the
    # SQLAlchemy form, and pgx rejects `postgresql+psycopg://`. `dsn` is the value
    # `_local_postgres_dsn` normalised and the probe just used successfully, so the
    # API and the probe now agree by construction.
    environment["RETAIL_POSTGRES_DSN"] = dsn
    serve_runtime = REPO_ROOT / ".serve-runtime"
    go_cache = serve_runtime / "go-cache"
    go_tmp = serve_runtime / "go-tmp"
    go_cache.mkdir(parents=True, exist_ok=True)
    go_tmp.mkdir(parents=True, exist_ok=True)
    # A sandboxed Windows host may deny the default cache beneath LocalAppData even
    # though the checkout itself is writable. `go run` needs both locations before
    # the API can bind its port, so keep its disposable state in the ignored runtime
    # directory used by this launcher.
    environment.setdefault("GOCACHE", str(go_cache))
    environment.setdefault("GOTMPDIR", str(go_tmp))
    profile = args.execution_profile or _host_execution_profile()
    api = [
        "go", "run", "./cmd/server",
        "-address", args.address,
        "-gate-a-report", str(evidence / "gate-a.json"),
        "-gate-b-report", str(evidence / "gate-b.json"),
        "-publication-manifest", str(curated / "publication-manifest.json"),
        "-execution-profiles",
        str(REPO_ROOT / "execution" / "src" / "retail_execution" / "data" / "v1"
            / "profiles.json"),
        "-execution-profile", profile,
        "-openapi-spec", str(REPO_ROOT / "contracts" / "api" / "openapi.yaml"),
        "-forecast-activation-scope", fingerprint,
    ]
    if not args.with_ui:
        return _run(api, cwd=REPO_ROOT / "api", env=environment)
    # Both in the foreground would each block, so the UI is a child and the API owns
    # the terminal; Ctrl-C stops the API and the finally clause stops the UI with it.
    # The address goes to Vite too. Its proxy targeted 127.0.0.1:8080 literally, so
    # `--with-ui --address 127.0.0.1:9090` started both processes and every UI request
    # still went to 8080 -- two healthy servers and a dead screen.
    try:
        proxy_target = _api_proxy_target(args.address)
    except ValueError as broken:
        print(f"invalid --address {args.address!r}: {broken}", file=sys.stderr)
        return 2
    ui_environment = dict(os.environ)
    ui_environment["RETAIL_API_TARGET"] = proxy_target
    ui = subprocess.Popen(  # noqa: S603
        [_npm(), "run", "dev"], cwd=REPO_ROOT / "ui", env=ui_environment
    )
    try:
        return _run(api, cwd=REPO_ROOT / "api", env=environment)
    finally:
        ui.terminate()
        try:
            ui.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ui.kill()


def _active_forecast_authorities() -> list[dict[str, str]]:
    """Read and validate every active forecast row from the configured database."""

    try:
        ml_python = _require_python(ML_ENV, "ml")
    except RuntimeError as broken:
        raise SystemExit(f"the active authority cannot be read: {broken}")
    probe_env = dict(os.environ)
    probe_env["RETAIL_PROBE_DSN"] = _local_postgres_dsn(sqlalchemy=False)
    try:
        probe = subprocess.run(
            [
                str(ml_python),
                "-c",
                "import json, os, psycopg\n"
                "with psycopg.connect(os.environ['RETAIL_PROBE_DSN']) as c:\n"
                "    rows = c.execute(\n"
                "        'select activation_scope_fingerprint, '\n"
                "        'publication_semantic_fingerprint from '\n"
                "        'retail_serving.active_forecast_versions order by 1, 2'\n"
                "    ).fetchall()\n"
                "print(json.dumps([{'activationScopeFingerprint': r[0], "
                "'publicationSemanticFingerprint': r[1]} for r in rows]))\n",
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=probe_env,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(
            "the active authority probe timed out after 15 seconds; pass --run-id "
            "only after the configured database is reachable"
        )
    except OSError as broken:
        raise SystemExit(f"the active authority probe could not start: {broken}")
    if probe.returncode:
        detail = (probe.stderr or "").strip().splitlines()[-1:] or ["(no error)"]
        raise SystemExit(f"the active authority probe failed: {detail[0]}")
    try:
        rows = json.loads(probe.stdout or "")
    except json.JSONDecodeError as broken:
        raise SystemExit(f"the active authority probe returned invalid JSON: {broken}")
    if not isinstance(rows, list):
        raise SystemExit(
            f"the active authority probe returned {type(rows).__name__}, expected a list"
        )
    required = ("activationScopeFingerprint", "publicationSemanticFingerprint")
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or any(
            not _is_sha256(row.get(field))
            for field in required
        ):
            raise SystemExit(
                f"the active authority probe returned an unusable fingerprint row "
                f"at index {index}"
            )
    return rows


def _active_authority_run(
    authorities: list[dict[str, str]] | None = None,
) -> str:
    """The unique retained run whose publication the live activation names.

    Asks PostgreSQL which publication is actually serving, then finds the retained
    evidence directory whose manifest carries that fingerprint. Governed authority
    rather than filesystem recency.
    """

    rows = authorities if authorities is not None else _active_forecast_authorities()
    if not rows:
        raise SystemExit(
            "the database has no active forecast authority; pass --run-id only after "
            "materializing and activating that publication"
        )
    if len(rows) != 1:
        identities = sorted(
            {
                f"{row['activationScopeFingerprint'][:12]}…/"
                f"{row['publicationSemanticFingerprint'][:12]}…"
                for row in rows
            }
        )
        raise SystemExit(
            f"the database has {len(rows)} active forecast authorities "
            f"({', '.join(identities)}); retire the competing scopes rather than "
            "letting serve choose an unordered row"
        )
    fingerprint = rows[0]["publicationSemanticFingerprint"]
    evidence_root = REPO_ROOT / "ingestion" / "data" / "evidence"
    matches: list[str] = []
    for path in sorted(evidence_root.glob("run-*")):
        manifest = path / "publication-manifest.json"
        if not manifest.is_file():
            continue
        try:
            document = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict) and document.get("semanticFingerprint") == fingerprint:
            matches.append(path.name)
    if len(matches) != 1:
        raise SystemExit(
            f"active publication {fingerprint[:12]}… resolves to {len(matches)} "
            "retained run directories; pass --run-id to identify the intended "
            "publication explicitly"
        )
    return matches[0]


def _api_proxy_target(address: str) -> str:
    """Turn a Go listen address into a URL the local Vite proxy can dial."""

    listen = str(address or "").strip()
    if not listen or "://" in listen:
        raise ValueError("expected a host:port or :port listen address")
    parsed = urlsplit(f"//{listen}")
    try:
        port = parsed.port
    except ValueError as broken:
        raise ValueError(str(broken))
    if (
        port is None
        or port < 1
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("expected a host:port or :port listen address")
    host = parsed.hostname
    if host in (None, "", "0.0.0.0", "::"):
        host = "127.0.0.1"
    elif ":" in host:
        host = f"[{host}]"
    return f"http://{host}:{port}"


def _newest_published_run() -> str | None:
    """The published run with the newest manifest, never a sorted glob over hashes."""

    candidates = [
        path
        for path in (REPO_ROOT / "ingestion" / "data" / "evidence").glob("run-*")
        if (path / "publication-manifest.json").is_file()
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda path: (path / "publication-manifest.json").stat().st_mtime,
    ).name


def command_closure_record(args: argparse.Namespace) -> int:
    """Regenerate the forecast closure record from the bundle and live activation.

    The record's own note told developers to run `tools/dev.py closure-record`,
    but the subcommand was never wired up, so the only way to regenerate the
    thing that must never drift was to remember the script path. `P4-0` needs it
    regenerated against migration 0008, so the advertised command now exists.
    """

    builder = REPO_ROOT / "tools" / "build_closure_record.py"
    if not builder.is_file():
        print("closure-record generator has not landed yet", file=sys.stderr)
        return 3
    return _run([sys.executable, str(builder), str(args.forecast_run)])


def command_inventory_entry_record(args: argparse.Namespace) -> int:
    """Regenerate or verify the inventory & replenishment entry record."""

    ingestion = _require_python(INGESTION_ENV, "ingestion")
    builder = REPO_ROOT / "tools" / "build_inventory_entry_record.py"
    if not builder.is_file():
        print("inventory entry-record generator has not landed yet", file=sys.stderr)
        return 3
    command = [str(ingestion), str(builder)]
    if getattr(args, "check", False):
        command.append("--check")
    return _run(command)


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


def _host_execution_profile() -> str:
    """Pick an execution profile from the host, not from a README assumption.

    The README prescribes ``safe`` for "the 16-GiB-available demo machine". Following
    that on a 128 GB / 16-core host throttled the forecast trainer to two threads and
    one rolling origin took twenty-two minutes; the same schedule on ``performance``
    finished thirteen origins in thirty-seven. The profile does not change results --
    ``ml/reports/w7-profile-invariance-local.json`` records identical forecast run ids
    and semantic fingerprints across ``safe`` and ``ultra-performance``, and agreement
    to 1e-12 across thread counts -- so this is purely about not wasting hours.

    Deliberately conservative: it never returns ``ultra-performance``, whose ML tier
    asks for 6 model workers x 4 threads against however many cores exist, so on a
    16-core host it oversubscribes and contends rather than going faster.
    """

    try:
        import multiprocessing

        cores = multiprocessing.cpu_count()
    except (ImportError, NotImplementedError):
        cores = 1
    memory_gb = 0
    if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:
        try:
            memory_gb = (
                os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            ) // (1024**3)
        except (OSError, ValueError):
            memory_gb = 0
    if memory_gb == 0:
        try:
            memory_gb = int(
                subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
                or 0
            ) // (1024**3)
        except (OSError, ValueError):
            memory_gb = 0
    if memory_gb == 0 and os.name == "nt":
        # Neither probe above exists on Windows: os.sysconf is POSIX-only and
        # sysctl is macOS. So memory_gb stayed 0 there and every Windows host fell
        # through to `safe` no matter its size -- a 32 GB / 8-core box was throttled
        # to the profile the docstring above reserves for a 16 GB machine, which is
        # hours on the backtest rather than a preference. GlobalMemoryStatusEx is
        # the stdlib answer via ctypes; guarded by os.name so ctypes.windll -- which
        # does not exist off Windows -- is never touched on macOS or Linux.
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                # ROUNDED, not floored. GlobalMemoryStatusEx reports OS-visible
                # physical memory -- installed minus the firmware reservation -- so a
                # nominal 32 GB box reports 31.7 GiB and flooring gives 31, one below
                # the `>= 32` threshold. macOS's `sysctl hw.memsize` returns the
                # nominal 34359738368 and gives 32, so identical hardware resolved
                # `performance` there and `balanced` here: precisely the
                # cross-platform divergence this probe was added to remove.
                memory_gb = round(int(status.ullTotalPhys) / (1024**3))
        except (ImportError, AttributeError, OSError, ValueError):
            memory_gb = 0
    if memory_gb >= 32 and cores >= 8:
        return "performance"
    if memory_gb >= 16 and cores >= 4:
        return "balanced"
    return "safe"


def _scenario_id(config_path: Path) -> str:
    """Read `identity.scenarioId` without importing the datagen package.

    `tools/` runs on the repo interpreter and datagen lives in its own isolated
    environment, so this parses the one field it needs rather than taking a
    dependency across that boundary.
    """

    try:
        for line in Path(config_path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("scenarioId:"):
                return stripped.split(":", 1)[1].strip().strip("'\"")
    except OSError:
        return ""
    return ""


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def command_datagen(args: argparse.Namespace) -> int:
    """Generate a source run. Deliberately NOT part of `pipeline`.

    Generation is ~90 minutes and 15 GB for the ten-year demo, and the pinned scenario
    is deterministic in its business data -- a regeneration reproduces every control
    total to the cent -- so repeating it is almost always wasted time. Keeping it out of
    the pipeline command means the fast loop cannot accidentally spend an hour and a half
    reproducing data it already has.
    """

    datagen = _require_python(DATAGEN_ENV, "datagen")
    profile = args.execution_profile or _host_execution_profile()
    if args.execution_profile is None:
        print(f"selected execution profile {profile!r} from host resources")
    output = args.output.resolve()

    # Scoped to the scenario being generated, not the whole output root. The
    # guard exists to stop a pointless ~90-minute rebuild of a run we already
    # have; it is not a claim that the stack may hold only one scenario. Glob
    # everything and a second tenant can never be generated at all while the
    # first one's run is on disk, which pushes the work somewhere it does not
    # belong.
    scenario_id = _scenario_id(args.config)
    existing = sorted((output / scenario_id).glob("run-*")) if scenario_id else []
    if existing and not args.regenerate:
        print(
            f"a promoted source run for {scenario_id!r} already exists; generation "
            "refused:\n  "
            + "\n  ".join(_display_path(path) for path in existing)
            + "\n\nThe pinned scenario reproduces its business data exactly, so "
            "regenerating usually costs ~90 minutes for no change. Pass --regenerate "
            "to do it anyway.\n\nNote decision #89: a regeneration DOES move "
            "sourceSnapshotId and every fingerprint derived from it, because "
            "source_snapshot_id hashes Parquet bytes. The ML stages will fail closed "
            "against contracts/ml/expected-pin.json until the pin is re-established "
            "with equivalence evidence."
        )
        return 1

    started = time.monotonic()
    code = _run(
        [
            str(datagen),
            "-m",
            "retail_datagen.cli",
            "generate",
            "-c",
            str(args.config),
            "-o",
            str(output),
            "--execution-profile",
            profile,
        ]
    )
    # Timed like a pipeline stage even though it deliberately is not one: generation
    # is the single largest cost in a from-scratch rebuild -- 79 min of the ~2h20m
    # macOS baseline -- so a rebuild comparison without it is missing most of its mass.
    _STAGE_TIMINGS.append((f"datagen ({profile})", time.monotonic() - started))
    _report_stage_timings()
    if code:
        return code
    promoted = sorted((output / scenario_id).glob("run-*")) if scenario_id else []
    if promoted:
        print("\npromoted source run:")
        for path in promoted:
            print(f"  {path}")
        print(
            "\nNext: tools/dev.py pipeline --source-root <run dir> "
            "--to activate"
        )
    return 0


#: Ordered pipeline stages. `datagen` is absent on purpose -- see command_datagen.
PIPELINE_STAGES: tuple[str, ...] = (
    "land",
    "ingest",
    "finalize",
    # The governed step between publish and features, and the reason a rebuild used
    # to need two commands with a manual gap. Every ML stage validates the curated
    # publication against contracts/ml/expected-pin.json and fails closed when it
    # does not match, so a regeneration -- which moves sourceSnapshotId and every
    # fingerprint under it -- stops the chain here whether or not the stage exists.
    # Making it a stage does not weaken decision #89: the pin still refuses unless
    # the selection ledger already names this run as the active source authority,
    # and that record carries an approver and a reason no derivation can invent. So
    # a run a human has governed rebuilds in ONE command, and a brand-new run stops
    # with the sentence that says which chain to add.
    "repin",
    "features",
    "characterize",
    "backtest",
    "score-current",
    "classify",
    "publish",
    "materialize",
    "activate",
    # The inventory half. Previously the chain stopped at the forecast activation
    # and the four inventory commands were run by hand, which is where the identity
    # threading went wrong most often: build mints the run id, verify re-derives the
    # fingerprint, and activate needs both.
    "inventory-build",
    "inventory-verify",
    "inventory-materialize",
    "inventory-activate",
    # The two evidence records. Previously outside the chain as "a governed step",
    # which in practice meant forgotten: a complete run left both naming the PREVIOUS
    # authority, and `tools/dev.py verify` compares them against the Alembic graph, so
    # a rebuild that skipped them failed a gate for a reason nothing pointed at. They
    # derive entirely from the bundle and the live activation -- there is no decision
    # in either -- so being outside the chain bought nothing.
    "closure-record",
    "inventory-entry-record",
)


def _stage_slice(start: str, end: str) -> tuple[str, ...]:
    order = list(PIPELINE_STAGES)
    return tuple(order[order.index(start) : order.index(end) + 1])


#: Wall clock per stage, in execution order, appended by `_pipeline_step` and
#: reported as a table when the chain ends. Exists so a run on one host can be
#: compared line by line against `docs/pipeline-stage-timings.md`, which records a
#: macOS baseline: a total alone cannot tell you whether a slower host is slower
#: everywhere or just on the backtest. Populated even when a stage raises, because
#: knowing how far a failed run got is most of diagnosing it.
_STAGE_TIMINGS: list[tuple[str, float]] = []


def _format_duration(seconds: float) -> str:
    """Format to match `docs/pipeline-stage-timings.md` so the tables can be diffed."""

    if seconds < 1:
        return "<1s"
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    if hours:
        return f"{hours}h {minutes:02d}m {remainder:04.1f}s"
    if minutes:
        return f"{minutes} min {remainder:04.1f} s"
    return f"{remainder:.1f} s"


def _report_stage_timings() -> None:
    """Print the per-stage table. Called on success and on failure alike."""

    if not _STAGE_TIMINGS:
        return
    width = max(len(label) for label, _ in _STAGE_TIMINGS)
    total = sum(elapsed for _, elapsed in _STAGE_TIMINGS)
    print("\n===== stage timings =====", flush=True)
    print(f"host: {platform.system()} {platform.release()} ({platform.machine()})")
    for index, (label, elapsed) in enumerate(_STAGE_TIMINGS, start=1):
        print(f"{index:>3}. {label:<{width}}  {_format_duration(elapsed)}")
    print(f"{'':>3}  {'TOTAL':<{width}}  {_format_duration(total)}", flush=True)


def _generation_names_run(run_id: str) -> bool:
    """Is this publication already adopted by some committed selection record?

    Read from the committed records rather than only the generations ledger, because
    the six hand-written generations predate that ledger and a run named by one of
    them is already adopted.
    """

    target = f"ingestion/data/curated/{run_id}"
    directory = REPO_ROOT / "contracts" / "evidence" / "publication-selections"
    for path in directory.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as broken:
            raise SystemExit(
                f"cannot verify whether {run_id} is already selected because "
                f"{path} is unreadable: {broken}"
            )
        if not isinstance(record, dict):
            raise SystemExit(
                f"cannot verify whether {run_id} is already selected because "
                f"{path} is {type(record).__name__}, expected an object"
            )
        publication = record.get("publication")
        # The directory also carries the disclosed legacy-predecessor companion,
        # which deliberately has no publication block and is not a selection.
        if publication is None:
            continue
        if not isinstance(publication, dict) or not isinstance(
            publication.get("logicalPath"), str
        ):
            raise SystemExit(
                f"cannot verify whether {run_id} is already selected because "
                f"{path} has no valid publication.logicalPath"
            )
        if publication["logicalPath"] == target:
            return True
    return False


def _pipeline_step_inline(label: str, action) -> None:
    """Time and label an in-process stage the way `_pipeline_step` does a subprocess."""

    print(f"\n===== {label} =====", flush=True)
    started = time.monotonic()
    try:
        code = action()
    finally:
        # The action can raise SystemExit, OSError, or an unexpected exception. The
        # pipeline-level finally prints the table, but it can only print this failing
        # stage if the helper records it before propagating the exception.
        elapsed = time.monotonic() - started
        _STAGE_TIMINGS.append((label, elapsed))
        print(f"----- {label}: {_format_duration(elapsed)} -----", flush=True)
    if code:
        raise _PipelineFailure(label, code)


def _pipeline_step(label: str, command: list[str], *, cwd: Path = REPO_ROOT) -> dict:
    """Run one stage, capturing stdout so later stages can read its identities."""

    print(f"\n===== {label} =====", flush=True)
    # monotonic, not time(): a clock adjustment mid-run must not be able to make a
    # stage look negative or free. This measures elapsed wall clock for the stage,
    # which is what the baseline table records and what a user actually waits.
    started = time.monotonic()
    # Explicit UTF-8 rather than `text=True`. `text=True` decodes with the PARENT's
    # locale encoding, which is cp1252 on Windows, and PYTHONUTF8 cannot change that
    # -- an interpreter fixes its own stdio encoding at startup, so the variable only
    # reaches children. The result was a decode mirror of the encode bug: the child
    # correctly WROTE MLflow's emoji as UTF-8, the reader thread could not DECODE
    # those bytes, `completed.stdout` came back None, and the stage died on
    # `.index("{")` after 3h21m of work that had in fact succeeded. errors="replace"
    # so a stray undecodable byte degrades one character instead of discarding a
    # completed stage's output.
    #
    # finally, so a stage that RAISES still contributes its elapsed time.
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        elapsed = time.monotonic() - started
        _STAGE_TIMINGS.append((label, elapsed))
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    print(f"----- {label}: {_format_duration(elapsed)} -----", flush=True)
    if completed.returncode:
        raise _PipelineFailure(label, completed.returncode)
    try:
        start = completed.stdout.index("{")
        return json.loads(completed.stdout[start:])
    except (ValueError, json.JSONDecodeError):
        return {}


class _PipelineFailure(RuntimeError):
    def __init__(self, stage: str, code: int) -> None:
        super().__init__(stage)
        self.stage = stage
        self.code = code


def command_pipeline(args: argparse.Namespace) -> int:
    """Report stage timings on EVERY exit, then return the inner result.

    The report used to sit on the success path and in the _PipelineFailure handler, so
    a direct `return 2` after completed stages -- a missing activation identity, for
    instance -- and any unexpected exception skipped it. One finally covers all three,
    which matters most for the failure modes that happen hours in.
    """

    try:
        return _command_pipeline(args)
    finally:
        _report_stage_timings()


def _command_pipeline(args: argparse.Namespace) -> int:
    """Chain land through activate. Everything after datagen, in one command.

    Before this, `tools/dev.py run` covered only gate-a..publish and the ML half had no
    orchestrator at all -- `retail_ml.cli run` and `train` are declared subcommands wired
    to a "workstream has not landed yet" stub. Rebuilding the stack therefore meant
    hand-written scripts, and every wiring detail below is a failure that actually
    happened during one such rebuild rather than a hypothetical.
    """

    ingestion = _require_python(INGESTION_ENV, "ingestion")
    ml = _require_python(ML_ENV, "ml")
    profile = args.execution_profile or _host_execution_profile()
    if args.execution_profile is None:
        print(f"selected execution profile {profile!r} from host resources")

    stages = _stage_slice(args.from_stage, args.to_stage)
    print(f"stages: {' -> '.join(stages)}")

    source_root = args.source_root
    if source_root is None and "land" in stages:
        promoted = sorted((REPO_ROOT / "datagen" / "output").glob("*/run-*"))
        if not promoted:
            print(
                "no promoted source run; run tools/dev.py datagen first",
                file=sys.stderr,
            )
            return 2
        source_root = promoted[-1]
        print(f"source run: {source_root.relative_to(REPO_ROOT)}")
    # The profile is scenario-bound, not generic: it names its source instances,
    # their market mapping and its own extract window. A second tenant therefore
    # needs its own profile, and hard-coding the retail one here made the whole
    # pipeline single-tenant no matter which source run was passed in.
    source_profile = args.source_profile or (
        REPO_ROOT / "ingestion" / "src" / "retail_ingestion" / "profiles"
        / "retail_datagen.yaml"
    )
    if "ingest" in stages and not Path(source_profile).is_file():
        print(f"source profile not found: {source_profile}", file=sys.stderr)
        return 2

    run_id = (source_root or Path(args.run_id or "run-unknown")).name
    if run_id == "run-unknown":
        # Resuming mid-chain with no --source-root: `curated` and `work` are built
        # from run_id, so every stage below `land` was silently pointed at
        # .../curated/run-unknown. `--from inventory-build` therefore failed on a
        # missing curated root rather than on anything real. Recovered from the
        # publication that exists -- newest by its own manifest, never a sorted glob
        # over content hashes, which is the tie-break that once cost a full
        # regeneration by ingesting an unrelated snapshot.
        published_runs = [
            path
            for path in (REPO_ROOT / "ingestion" / "data" / "evidence").glob("run-*")
            if (path / "publication-manifest.json").is_file()
        ]
        if published_runs:
            run_id = max(
                published_runs,
                key=lambda path: (path / "publication-manifest.json").stat().st_mtime,
            ).name
            print(f"resolved run: {run_id}")

    # A re-publication of a run some committed record already selects must NOT reuse
    # that record's curated and evidence roots. The source run id is deterministic, so
    # a regenerated run reproduces it exactly and lands on the same paths -- which
    # overwrites the artifacts those records attest to and is only discovered later,
    # when repin refuses because a fingerprint it names has stopped existing. That
    # cost a rename of two multi-gigabyte trees mid-run.
    #
    # The existing preflight cannot catch this: it checks whether the curated root
    # EXISTS, and on a fresh clone it does not. Six of seven runs are
    # evidence-released, so "the ledger names a path whose bytes are absent" is the
    # normal state, not an edge case. Suffix instead of refuse, matching the `-r2`
    # convention already in the ledger.
    if (
        args.publication_root is None
        and "ingest" in stages
        and _generation_names_run(run_id)
    ):
        base = run_id
        suffix = 2
        while _generation_names_run(f"{base}-r{suffix}"):
            suffix += 1
        superseded_run, run_id = run_id, f"{base}-r{suffix}"
        print(
            f"a committed selection record already names "
            f"ingestion/data/curated/{superseded_run}; publishing this run as "
            f"{run_id} so that record's artifact is not overwritten"
        )

    work = args.work_root or REPO_ROOT / "ingestion" / "data" / "work" / run_id
    curated = (
        args.publication_root or REPO_ROOT / "ingestion" / "data" / "curated" / run_id
    )
    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run_id
    artifacts = REPO_ROOT / "ml" / "data" / "artifacts"
    # --label names the ARTIFACT directories for this cycle. The feature directory is
    # separate and defaults to matching, because features are expensive and routinely
    # reused across several artifact labels -- resuming `--from backtest` with a new label
    # otherwise looks for features that were never built under that name, which is exactly
    # how this command failed the first time it was used for real.
    features = (
        args.feature_dir
        if args.feature_dir is not None
        else REPO_ROOT / "ml" / "data" / "features" / args.label
    )
    # Only the stages that actually READ the feature directory need one to exist.
    #
    # The guard used to fire whenever `features` was absent from the slice, which
    # made every ingestion-only slice refuse: `--to finalize` needs no features at
    # all, and neither do the inventory stages, yet both were rejected before a
    # single command ran. The check is for resuming mid-chain -- `--from backtest`
    # against a feature set that was never built under that label -- so it belongs
    # to the consumers, not to the absence.
    FEATURE_CONSUMERS = frozenset(
        {"characterize", "backtest", "score-current", "publish"}
    )
    consumers_in_slice = FEATURE_CONSUMERS.intersection(stages)
    if (
        consumers_in_slice
        and "features" not in stages
        and not (features / "manifest.json").is_file()
    ):
        print(
            f"no feature manifest at {features}, and this slice runs "
            f"{', '.join(sorted(consumers_in_slice))} without building features. "
            "Build features first, or pass --feature-dir pointing at an existing "
            "feature set.",
            file=sys.stderr,
        )
        return 2
    backtest = artifacts / f"backtest_{args.label}"
    current = artifacts / f"current_{args.label}"
    classifications = artifacts / f"classifications_{args.label}"
    bundle = artifacts / f"forecast_run_{args.label}"

    horizons = ",".join(str(h) for h in range(1, args.horizons + 1))
    decision_as_of = args.decision_as_of
    # The forecast stages take an INSTANT; the inventory build takes a DATE. Its
    # cutoff is a day -- every visibility predicate under it reads
    # `known_as_of < as_of + INTERVAL 1 DAY` -- and its CLI parses with
    # `date.fromisoformat`, which refuses '2026-07-31T00:00:00Z'. One flag was
    # feeding both, so a complete chain died at inventory-build 49 minutes in, after
    # the forecast had already published, materialized and activated. Truncating
    # here rather than widening the ML parser: a date is the type that stage means,
    # and accepting a timestamp would let a non-midnight instant pass and be
    # silently floored.
    inventory_as_of = decision_as_of.split("T", 1)[0]

    # Preflight: every immutable output this slice would write, checked before the
    # first stage runs.
    #
    # Publication is immutable by design -- `publish`, `characterize` and the
    # inventory publisher each refuse to overwrite -- and re-running deterministic
    # inputs reproduces the same fingerprints, so a repeat run collides on purpose.
    # What was wrong was the TIMING: a full run died at `characterize` four minutes
    # in, on a stale report from a previous run, having already re-landed 15 GB and
    # re-ingested. And it would have reported only that one collision, so clearing it
    # and rerunning would have died again at `publish`. Every blocker is named at
    # once, before anything is written.
    # Every stage below has its own guard, verified against the raising call sites
    # rather than assumed -- a preflight that clears a slice it has not fully checked
    # is worse than none, because it converts "you will fail later" into "you are
    # ready". Grep for FileExistsError under ml/src if a stage is added.
    immutable_outputs = [
        ("ingest", curated, "curated publication"),
        ("features", features, "feature set"),
        (
            "characterize",
            REPO_ROOT / "ml" / "reports" / f"{args.label}-characterization.json",
            "characterization report",
        ),
        ("backtest", backtest, "backtest output"),
        ("score-current", current, "current-cycle output"),
        ("classify", classifications, "classification output"),
        ("publish", bundle, "forecast run bundle"),
        (
            "inventory-build",
            artifacts / f"inventory_run_{args.label}",
            "inventory run bundle",
        ),
    ]
    collisions = [
        (stage, path, what)
        for stage, path, what in immutable_outputs
        if stage in stages and path.exists()
    ]
    if collisions:
        print(
            f"{len(collisions)} immutable output(s) already exist, so this slice "
            "cannot run to completion:",
            file=sys.stderr,
        )
        for stage, path, what in collisions:
            try:
                shown = path.relative_to(REPO_ROOT)
            except ValueError:
                shown = path
            print(f"  {stage}: {what} at {shown}", file=sys.stderr)
        print(
            "Remove them to rebuild, or pass --label <name> to build alongside them. "
            "Note that materialize and activate also refuse a version id that is "
            "already in PostgreSQL, and identical inputs mint an identical id, so a "
            "true from-scratch run additionally needs the retail_serving schema and "
            "its ledger dropped -- which is a deliberate act, not something this "
            "command will do for you.",
            file=sys.stderr,
        )
        return 2

    try:
        landing = None
        if "land" in stages:
            landing = _pipeline_step(
                "land",
                [
                    str(ingestion), "-m", "retail_ingestion.cli", "land",
                    "--source-root", str(source_root),
                    "--landing-root", str(REPO_ROOT / "ingestion" / "data" / "raw"),
                    "--execution-profile", profile,
                ],
            )

        # The snapshot LAND just wrote, taken from its own output -- not the last
        # entry of a sorted glob over content-hash directory names.
        #
        # That glob is an alphabetical tie-break over hashes, which is to say it
        # is arbitrary. It cost a full 50-minute regeneration: `land` wrote
        # d43fd302..., the glob's last entry was f75e1490..., and the pipeline
        # ingested an unrelated quarter-long scenario whose extract window Gate A
        # then correctly refused. The gate did its job; the selection was wrong.
        snapshot = args.snapshot_root
        if snapshot is None and landing:
            root = landing.get("snapshotRoot")
            if root:
                snapshot = Path(root)
        if snapshot is None:
            snapshots = sorted(
                (REPO_ROOT / "ingestion" / "data" / "raw" / "snapshots").glob("*"),
                key=lambda path: path.stat().st_mtime,
            )
            snapshot = snapshots[-1] if snapshots else None
        if snapshot is None and any(
            stage in stages for stage in ("ingest", "finalize")
        ):
            print("no landed snapshot found", file=sys.stderr)
            return 2

        if "ingest" in stages:
            # gate-a, stage, transform, gate-b and publish in order.
            _pipeline_step(
                "ingest (gate-a, stage, transform, gate-b, publish)",
                [
                    str(ingestion), "-m", "retail_ingestion.cli", "run",
                    "--snapshot-root", str(snapshot),
                    "--source-profile", str(source_profile),
                    "--work-root", str(work),
                    "--publication-root", str(curated),
                    "--execution-profile", profile,
                ],
            )

        if "finalize" in stages:
            # Retains the small evidence bundle. Skipping it left
            # ingestion/data/evidence/<run>/gate-a.json absent, which the pinned-run
            # tests read directly, so two of them failed on a complete pipeline.
            _pipeline_step(
                "finalize",
                [
                    str(ingestion), "-m", "retail_ingestion.cli", "finalize",
                    "--work-root", str(work),
                    "--publication-root", str(curated),
                    "--evidence-root", str(evidence),
                ],
            )

        if "repin" in stages:
            # Write, then verify, then pin -- in that order for the error message.
            # Pinning first fails with a fingerprint mismatch, which reads like a
            # corrupt publication; verifying first names the actual problem, which
            # is a run nobody selected.
            if run_id == "run-unknown":
                print(
                    "repin needs a published run; none has a "
                    "publication-manifest.json under ingestion/data/evidence",
                    file=sys.stderr,
                )
                return 2
            selection = REPO_ROOT / "tools" / "build_publication_selection.py"
            # --no-clobber, emphatically. Without it this step rewrote committed
            # selection records to match the publication that had just been written,
            # and the verify step below then passed against that rewrite -- a check
            # that can never fail, because the thing it checks was just re-aligned to
            # it. A build command may CREATE a governance record whose derivation is
            # deterministic; it must not restate one whose subject has changed.
            #
            # If no generation names this run yet, adopt it first. Previously the
            # chain stopped here and expressing one decision took five coordinated
            # edits across two files; now it is one appended ledger entry. The
            # decision is not weakened -- `repin --approve` still refuses a
            # publication missing a required capability, and it records the automated
            # actor rather than a person's name when no human supplied one, so a
            # reader can always tell which kind of approval they are looking at.
            if not _generation_names_run(run_id):
                repin_args = argparse.Namespace(
                    run_id=run_id,
                    approve=True,
                    actor=args.repin_actor,
                    reason=args.repin_reason,
                    reason_code=args.repin_reason_code,
                    approved_at=args.repin_approved_at,
                )
                _pipeline_step_inline("repin (adopt publication)",
                                      lambda: command_repin(repin_args))
            _pipeline_step(
                "repin (selection ledger)",
                [str(ingestion), str(selection), "--no-clobber"],
            )
            _pipeline_step(
                "repin (selection ledger verified)",
                [str(ingestion), str(selection), "--check"],
            )
            _pipeline_step(
                "repin (expected pin)",
                [
                    str(ingestion),
                    str(REPO_ROOT / "tools" / "build_expected_pin.py"),
                    "--run", run_id,
                ],
            )

        if "features" in stages:
            _pipeline_step(
                "features",
                [
                    str(ml), "-m", "retail_ml.cli", "features",
                    "--output-dir", str(features),
                    "--execution-profile", profile,
                ],
            )

        if "characterize" in stages:
            _pipeline_step(
                "characterize",
                [
                    str(ml), "-m", "retail_ml.cli", "characterize",
                    "--feature-dir", str(features),
                    "--report",
                    str(REPO_ROOT / "ml" / "reports"
                        / f"{args.label}-characterization.json"),
                ],
            )

        if "backtest" in stages:
            # --horizons takes a comma list. Passing the range "1-26" raises
            # "invalid literal for int() with base 10: '1-26'", so it is derived here
            # from a horizon COUNT and the caller never formats it.
            _pipeline_step(
                "backtest",
                [
                    str(ml), "-m", "retail_ml.cli", "backtest",
                    "--feature-dir", str(features),
                    "--output-dir", str(backtest),
                    "--tracking-uri", args.tracking_uri,
                    "--horizons", horizons,
                    "--origin-count", str(args.origin_count),
                    "--execution-profile", profile,
                ],
            )

        if "score-current" in stages:
            # The frozen decision #84 blend must come from the accepted backtest, or the
            # cycle certifies one estimator and serves another.
            command = [
                str(ml), "-m", "retail_ml.cli", "score-current",
                "--feature-dir", str(features),
                "--output-dir", str(current),
                "--decision-as-of", decision_as_of,
                "--execution-profile", profile,
            ]
            blend = backtest / "cold_start_blend_model.json"
            if blend.is_file():
                command.extend(["--blend-model", str(blend)])
            coverage = backtest / "coverage_calibration_model.json"
            if coverage.is_file():
                command.extend(["--coverage-model", str(coverage)])
            _pipeline_step("score-current", command)

        if "classify" in stages:
            # score-current writes current_cycle_classification_input.parquet for this
            # stage and current_forecast_predictions.parquet for publish. There is no
            # current_cycle_forecasts.parquet; guessing that name failed a rebuild after
            # the expensive stages had already succeeded.
            _pipeline_step(
                "classify",
                [
                    str(ml), "-m", "retail_ml.cli", "classify",
                    "--current-cycle",
                    str(current / "current_cycle_classification_input.parquet"),
                    "--output-dir", str(classifications),
                    "--decision-as-of", decision_as_of,
                ],
            )

        published: dict = {}
        if "publish" in stages:
            # --classification-policies wants the file classify EMITS, carrying policy
            # ids and fingerprints. Passing contracts/ml/forecast-classification-policy
            # .json instead fails with "must contain exceptions and dataQuality".
            published = _pipeline_step(
                "publish",
                [
                    str(ml), "-m", "retail_ml.cli", "publish",
                    "--feature-dir", str(features),
                    "--backtest-dir", str(backtest),
                    "--exceptions",
                    str(classifications / "forecast_exceptions.parquet"),
                    "--data-quality",
                    str(classifications / "forecast_data_quality.parquet"),
                    "--classification-policies",
                    str(classifications / "classification-policies.json"),
                    "--current-forecasts",
                    str(current / "current_forecast_predictions.parquet"),
                    "--output-dir", str(bundle),
                    "--decision-as-of", decision_as_of,
                    "--execution-profile", profile,
                ],
            )

        materialized: dict = {}
        # Bound here rather than in the `activate` block, because the closing summary
        # reads it and an inventory-only slice never enters that block: `--from
        # inventory-build` raised NameError on the last line of a run that had
        # otherwise fully succeeded.
        run: str | None = None
        # Bound out here for the same reason as `run`: the closing summary prints the
        # API command, and the API cannot serve the forecast screens without this.
        scope: str | None = None
        if "materialize" in stages:
            materialized = _pipeline_step(
                "materialize",
                [
                    str(ml), "-m", "retail_ml.cli", "materialize-serving",
                    "--forecast-run", str(bundle),
                    # Supplied here for the same reason forecast-materialize supplies
                    # it: the ML CLI requires a DSN and will not invent one, and a
                    # developer should not have to export RETAIL_POSTGRES_DSN to run
                    # the pipeline on the local compose stack.
                    "--postgres-dsn", _local_postgres_dsn(sqlalchemy=False),
                ],
            )

        if "activate" in stages:
            # Identity threading: publish mints the run id, materialize mints the
            # activation scope, activate needs both. All three were copied by hand.
            run = materialized.get("forecast_run_id") or published.get(
                "forecast_run_id"
            )
            scope = materialized.get("activation_scope_fingerprint")
            if not run or not scope:
                print(
                    "activate needs a run id and activation scope from materialize; "
                    "rerun with --from materialize",
                    file=sys.stderr,
                )
                return 2
            activate_command = [
                str(ml), "-m", "retail_ml.cli", "activate-serving",
                "--forecast-run-id", run,
                "--activation-scope-fingerprint", scope,
                "--actor", args.actor,
                "--postgres-dsn", _local_postgres_dsn(sqlalchemy=False),
            ]
            if args.retire_other_scopes:
                activate_command.append("--retire-other-scopes")
            _pipeline_step("activate", activate_command)

        # -- inventory half ---------------------------------------------------
        #
        # The bundle name follows the artifact label, like the forecast bundle, so a
        # second cycle under a new label does not collide with the first -- the
        # inventory publisher refuses to overwrite a bundle directory, and a
        # colliding name reads as an immutability failure rather than a naming one.
        inventory_bundle = artifacts / f"inventory_run_{args.label}"
        dsn = _local_postgres_dsn(sqlalchemy=False)
        inventory_built: dict = {}
        if "inventory-build" in stages:
            inventory_built = _pipeline_step(
                "inventory-build",
                [
                    str(ml), "-m", "retail_ml.cli", "inventory-build",
                    "--curated-root", str(curated),
                    "--bundle", str(inventory_bundle),
                    "--as-of", inventory_as_of,
                    "--postgres-dsn", dsn,
                    "--execution-profile", profile,
                ],
            )

        inventory_verified: dict = {}
        if "inventory-verify" in stages:
            inventory_verified = _pipeline_step(
                "inventory-verify",
                [
                    str(ml), "-m", "retail_ml.cli", "inventory-verify",
                    "--bundle", str(inventory_bundle),
                    "--postgres-dsn", dsn,
                ],
            )

        if "inventory-materialize" in stages:
            _pipeline_step(
                "inventory-materialize",
                [
                    str(ml), "-m", "retail_ml.cli", "inventory-materialize",
                    "--bundle", str(inventory_bundle),
                    "--postgres-dsn", dsn,
                ],
            )

        if "inventory-activate" in stages:
            # Verify is the authority on both identities: it re-derives them from
            # the bundle rather than trusting what build reported.
            inventory_run = (
                inventory_verified.get("inventoryRunId")
                or inventory_built.get("inventory_run_id")
            )
            fingerprint = (
                inventory_verified.get("semanticFingerprint")
                or inventory_built.get("semantic_fingerprint")
            )
            if not inventory_run or not fingerprint:
                print(
                    "inventory-activate needs the run id and semantic fingerprint "
                    "from inventory-verify; rerun with --from inventory-verify",
                    file=sys.stderr,
                )
                return 2
            # --retire-other-scopes belongs to the FORECAST activation and only to
            # it: `retail_ml.cli inventory-activate` takes no such flag, so
            # appending it here made `pipeline --retire-other-scopes` fail at the
            # sixteenth stage on an argparse error, after the bundle had already
            # been built, verified and materialized. Inventory activation retires
            # its own predecessor for the scope it activates.
            _pipeline_step(
                "inventory-activate",
                [
                    str(ml), "-m", "retail_ml.cli", "inventory-activate",
                    "--inventory-run-id", inventory_run,
                    "--run-semantic-fingerprint", fingerprint,
                    "--actor", args.actor,
                    "--postgres-dsn", dsn,
                ],
            )
            forecast_identity = (
                f"forecast {run} / {materialized.get('version_id')}\n"
                if run
                else ""
            )
            print(f"\nserving inventory {inventory_run}\n{forecast_identity}")
            # The API command, ready to run, because leaving it to be reconstructed
            # is how the forecast screens end up dark. `-forecast-activation-scope`
            # is not optional: without it every /api/v1/forecast/* route answers 503
            # FORECAST_READ_MODEL_UNAVAILABLE while the inventory screens serve live
            # data, which reads as missing forecast data rather than a missing flag.
            # The scope is known here and nowhere more conveniently, so it is printed
            # here rather than looked up from PostgreSQL afterwards.
            evidence_dir = evidence.relative_to(REPO_ROOT)
            curated_dir = curated.relative_to(REPO_ROOT)
            print("Start the API with (it reads activation from PostgreSQL at boot):")
            print(
                f"  cd api && go run ./cmd/server \\\n"
                f"    -address 127.0.0.1:8080 \\\n"
                f"    -gate-a-report ../{evidence_dir}/gate-a.json \\\n"
                f"    -gate-b-report ../{evidence_dir}/gate-b.json \\\n"
                f"    -publication-manifest ../{curated_dir}/publication-manifest.json \\\n"
                f"    -execution-profiles "
                f"../execution/src/retail_execution/data/v1/profiles.json \\\n"
                f"    -execution-profile safe \\\n"
                f"    -openapi-spec ../contracts/api/openapi.yaml \\\n"
                + (
                    f"    -forecast-activation-scope {scope}"
                    if scope
                    else "    -forecast-activation-scope <run the activate stage to "
                    "learn this; the forecast screens stay dark without it>"
                )
            )
            print(
                "\nOr let the scope be resolved for you:\n"
                "  tools/dev.py serve --with-ui"
            )

        if "closure-record" in stages:
            # Positional bundle path, and the system interpreter -- matching
            # command_closure_record rather than inventing a second calling
            # convention for the same script.
            _pipeline_step(
                "closure-record",
                [
                    sys.executable,
                    str(REPO_ROOT / "tools" / "build_closure_record.py"),
                    str(bundle),
                ],
            )

        if "inventory-entry-record" in stages:
            # The ingestion interpreter, not sys.executable: this one imports
            # retail_contracts and psycopg, which the system Python does not have.
            _pipeline_step(
                "inventory-entry-record",
                [
                    str(ingestion),
                    str(REPO_ROOT / "tools" / "build_inventory_entry_record.py"),
                ],
            )
    except _PipelineFailure as failure:
        # Timings come from the finally below now, so every exit path reports them:
        # a _PipelineFailure, a direct `return 2` after completed stages (a missing
        # activation identity, say), and an unexpected exception all used to skip it.
        print(
            f"\npipeline failed at stage {failure.stage!r} (exit {failure.code})\n"
            f"resume with: tools/dev.py pipeline --from {failure.stage.split()[0]} "
            f"--to {args.to_stage} --label {args.label}",
            file=sys.stderr,
        )
        return failure.code
    return 0


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


def command_api_test(args: argparse.Namespace) -> int:
    environment = dict(os.environ)
    environment.setdefault(
        "GOCACHE",
        str(Path(tempfile.gettempdir()) / "retail-intelligence-go-cache"),
    )
    return _run(
        _go_test_command(require_race=not args.allow_missing_race),
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
    return _run([_npm(), "test"], cwd=REPO_ROOT / "ui")


def command_ui_build(_: argparse.Namespace) -> int:
    result = _run([_npm(), "run", "typecheck"], cwd=REPO_ROOT / "ui")
    if result:
        return result
    return _run([_npm(), "run", "build"], cwd=REPO_ROOT / "ui")


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
    repin = subparsers.add_parser(
        "repin",
        help="propose or approve adopting a publication as the source authority",
    )
    repin.add_argument("--run-id", default=None,
                       help="published run to adopt; defaults to the newest")
    repin.add_argument(
        "--approve", action="store_true",
        help=(
            "write the adoption. Without this the command only PROPOSES: it prints "
            "the facts and the current pin and writes nothing."
        ),
    )
    repin.add_argument(
        "--actor", default=None,
        help=(
            "the person approving. Omit to record the automated policy actor "
            "instead -- never a person's name the caller did not supply."
        ),
    )
    repin.add_argument("--reason", default=None,
                       help="required with --actor; replaces the derived reason")
    repin.add_argument("--reason-code", default="AUTOMATED_REPIN_ADOPTION")
    repin.add_argument(
        "--approved-at", default=None,
        help="approval timestamp for the ledger entry; defaults to now, in UTC",
    )
    serve = subparsers.add_parser(
        "serve",
        help="start the API (and optionally the UI) against the active activation",
    )
    serve.add_argument("--run-id", default=None,
                       help="published run whose evidence the API reads")
    serve.add_argument("--address", default="127.0.0.1:8080")
    serve.add_argument("--execution-profile", default=None)
    serve.add_argument("--with-ui", action="store_true",
                       help="also start the Vite dev server")
    datagen = subparsers.add_parser(
        "datagen",
        help="generate a source run (separate from pipeline: ~90 min, ~15 GB)",
    )
    datagen.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "datagen" / "configs" / "multi-market-10-year-demo.yaml",
    )
    datagen.add_argument(
        "--output", type=Path, default=REPO_ROOT / "datagen" / "output"
    )
    datagen.add_argument(
        "--execution-profile", choices=("safe", "balanced", "performance", "ultra-performance"),
        default=None
    )
    datagen.add_argument(
        "--regenerate",
        action="store_true",
        help="regenerate even when a promoted run already exists",
    )

    pipeline = subparsers.add_parser(
        "pipeline",
        help="land -> ingest -> ML -> materialize -> activate in one command",
    )
    pipeline.add_argument("--from", dest="from_stage", choices=PIPELINE_STAGES,
                          default="land")
    # Default to the LAST stage rather than the forecast activation: the chain now
    # reaches the inventory half, and a default that stopped short would leave the
    # four inventory commands to be remembered by hand -- which is the wiring this
    # command exists to remove.
    pipeline.add_argument("--to", dest="to_stage", choices=PIPELINE_STAGES,
                          default=PIPELINE_STAGES[-1])
    pipeline.add_argument("--source-root", type=Path, default=None)
    pipeline.add_argument(
        "--source-profile",
        type=Path,
        default=None,
        help="tenant source profile; defaults to the retail datagen profile",
    )
    pipeline.add_argument("--snapshot-root", type=Path, default=None)
    pipeline.add_argument("--work-root", type=Path, default=None)
    pipeline.add_argument("--publication-root", type=Path, default=None)
    pipeline.add_argument("--run-id", default=None)
    pipeline.add_argument(
        "--feature-dir",
        type=Path,
        default=None,
        help="reuse an existing feature set; defaults to ml/data/features/<label>",
    )
    pipeline.add_argument(
        "--label",
        default="current",
        help="names the ML ARTIFACT directories for this cycle, not the feature set",
    )
    # Adoption inputs for the `repin` stage. All optional: with none of them the stage
    # adopts an unadopted publication under the automated policy actor, which is what
    # makes an unattended rebuild possible. Supplying --repin-actor with
    # --repin-reason records a human approval instead.
    pipeline.add_argument("--repin-actor", default=None,
                          help="record a human approver for the repin stage")
    pipeline.add_argument("--repin-reason", default=None,
                          help="required with --repin-actor")
    pipeline.add_argument("--repin-reason-code", default="AUTOMATED_REPIN_ADOPTION")
    pipeline.add_argument(
        "--repin-approved-at", default=None,
        help="approval timestamp for an adoption made by the repin stage; "
             "defaults to now, in UTC",
    )
    pipeline.add_argument("--horizons", type=int, default=26,
                          help="horizon COUNT; the comma list is derived")
    pipeline.add_argument("--origin-count", type=int, default=13)
    pipeline.add_argument("--decision-as-of", default="2026-07-31T00:00:00Z")
    pipeline.add_argument("--tracking-uri", default="http://127.0.0.1:5000")
    pipeline.add_argument("--actor", default=os.environ.get("USER", "developer"))
    pipeline.add_argument(
        "--retire-other-scopes",
        action="store_true",
        help=(
            "at activate, supersede every other active activation scope in the "
            "same transaction. Needed when re-pinning onto a new publication: the "
            "activation scope covers the input bundle, so a new publication mints "
            "a new scope which supersedes nothing and decision #90 then refuses "
            "two active forecasts. Off by default -- retiring a competing lineage "
            "is a decision, not a step."
        ),
    )
    pipeline.add_argument(
        "--execution-profile", choices=("safe", "balanced", "performance", "ultra-performance"),
        default=None
    )

    subparsers.add_parser("config-hash", help="validate the pinned datagen config")
    subparsers.add_parser("run-status", help="show promoted/staging source runs")
    api_test = subparsers.add_parser(
        "api-test", help="run portable Go API race tests"
    )
    api_test.add_argument(
        "--allow-missing-race", action="store_true",
        help=(
            "run go test WITHOUT the race detector when cgo is unavailable. This is "
            "not race evidence; `verify` never accepts it."
        ),
    )
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
        default=REPO_ROOT / "ml/data/artifacts/evidence/w0-memory-spike-safe-16gb.json",
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
    closure_record = subparsers.add_parser(
        "closure-record",
        help="regenerate the forecast closure record from a bundle and live activation",
    )
    closure_record.add_argument("--forecast-run", type=Path, required=True)
    entry_record = subparsers.add_parser(
        "inventory-entry-record",
        help="regenerate the inventory & replenishment entry record",
    )
    entry_record.add_argument("--check", action="store_true")

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
        "datagen": command_datagen,
        "pipeline": command_pipeline,
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
        "repin": command_repin,
        "serve": command_serve,
        "closure-record": command_closure_record,
        "inventory-entry-record": command_inventory_entry_record,
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
