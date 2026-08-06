#!/usr/bin/env python3
"""Cross-platform developer entry point for the monorepo.

This file is authoritative; the root Makefile is a short POSIX convenience
wrapper. Every subprocess is invoked with an argument list, every path uses
``pathlib``, and virtual-environment executables resolve correctly on Windows.
"""

from __future__ import annotations

import argparse
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
from urllib.parse import quote
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


def _go_test_command(*flags: str) -> list[str]:
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


def _selection_module():
    """Import the selection builder as a module so repin can read its ledger."""

    sys.path.insert(0, str(REPO_ROOT / "tools"))
    sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))
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
    gate_a = json.loads((evidence / "gate-a.json").read_text(encoding="utf-8"))
    manifest = json.loads(
        (evidence / "publication-manifest.json").read_text(encoding="utf-8")
    )
    # Gate B is READ, not assumed. The docstring said this file was one of the
    # sources and it never was: the fingerprint and the capability mask both came
    # from the manifest's copy of them, so a missing, failing or inconsistent
    # `gate-b.json` still produced a confident proposal claiming Gate B passed.
    # Only `--approve` found out, one step later, via the rollback.
    gate_b_path = evidence / "gate-b.json"
    if not gate_b_path.is_file():
        # A clean refusal, matching what `build_pin` gives for the same four files.
        # A bare read_text here produced a FileNotFoundError traceback for missing
        # evidence, which reads like a crash rather than the governed stop it is.
        raise SystemExit(f"retained evidence is absent: {gate_b_path}")
    gate_b = json.loads(gate_b_path.read_text(encoding="utf-8"))
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
    missing = [
        name for name in required if not (mask.get(name) or {}).get("available")
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
    pin = json.loads(pin_path.read_text(encoding="utf-8"))
    return {
        "sourceSnapshotId": pin.get("sourceSnapshotId"),
        "publicationSemanticFingerprint": (pin.get("publication") or {}).get(
            "semanticFingerprint"
        ),
        "objectCount": (pin.get("publication") or {}).get("objectCount"),
        "duckdbSha256": ((pin.get("publication") or {}).get("duckdb") or {}).get(
            "sha256"
        ),
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


def command_repin(args: argparse.Namespace) -> int:
    """Propose or approve the adoption of a publication as source authority.

    Decision #89 makes moving the pin a governed act. This does not weaken that: it
    removes the five coordinated file edits that expressing one decision used to
    take, and keeps the decision itself an explicit, separately-invoked step whose
    record states honestly whether a human made it.
    """

    ingestion = _require_python(INGESTION_ENV, "ingestion")
    selection = _selection_module()
    run_id = args.run_id or _newest_published_run()
    if run_id is None:
        print(
            "no published run found under ingestion/data/evidence with a "
            "publication-manifest.json",
            file=sys.stderr,
        )
        return 2

    # Already adopted -> no-op, never a second chain. Without this, re-running
    # `repin --approve` appended a fresh generation for a run a committed record
    # already selects, producing duplicate candidate/approved/active records that
    # share one selectionId and break the one-active-per-scope invariant. The
    # pipeline stage checked this and the standalone command did not, which is
    # exactly the asymmetry that makes a governance tool unsafe to re-run.
    if _generation_names_run(run_id):
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
    except SystemExit as refusal:
        print(f"refusing: {refusal}", file=sys.stderr)
        return 1
    previous = _repin_previous()
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

    if args.actor and not args.reason:
        print("--actor requires --reason", file=sys.stderr)
        return 2
    reasons = _repin_reasons(facts, previous, automatic=not args.actor)

    # An adoption is one act, so a failed one must leave nothing behind. The ledger
    # is written first because everything downstream derives FROM it, which means a
    # missing evidence file, a --no-clobber conflict or a pin failure would otherwise
    # persist a half-adoption: a generation recorded, selections possibly advanced,
    # and the pin still naming the previous publication. Restoring the ledger and
    # removing the records it produced is the closest this gets to a transaction.
    # Bytes, not text: restoring must not itself depend on `write_text(newline=)`,
    # which is 3.10+. A rollback that raises on the interpreter it is most likely to
    # run under is worse than no rollback, because it fails while claiming to repair.
    ledger_before = (
        selection.GENERATIONS_PATH.read_bytes()
        if selection.GENERATIONS_PATH.is_file()
        else None
    )
    pin_path = REPO_ROOT / "contracts" / "ml" / "expected-pin.json"
    pin_before = pin_path.read_bytes() if pin_path.is_file() else None
    records_before = {
        path.name
        for path in (
            REPO_ROOT / "contracts" / "evidence" / "publication-selections"
        ).glob("*.json")
    }

    def _roll_back(stage: str) -> None:
        if ledger_before is not None:
            selection.GENERATIONS_PATH.write_bytes(ledger_before)
        # The pin too. Rollback restored the ledger and the records but left a pin
        # that a failed expected-pin stage had already rewritten or truncated --
        # while reporting that no half-adoption remained. A rollback that claims more
        # than it undid is the thing that makes the next failure hard to diagnose.
        if pin_before is not None:
            pin_path.write_bytes(pin_before)
        elif pin_path.is_file():
            pin_path.unlink()
        directory = REPO_ROOT / "contracts" / "evidence" / "publication-selections"
        for path in directory.glob("*.json"):
            if path.name not in records_before:
                path.unlink()
        print(
            f"repin failed at {stage}; rolled the ledger and any records it wrote "
            "back to their prior state so no half-adoption is left committed",
            file=sys.stderr,
        )

    entry = selection.append_generation(
        run=run_id,
        approved_at=args.approved_at or _utc_now(),
        reason_code=args.reason_code,
        candidate_reason=(args.reason or reasons["candidate"]),
        approved_reason=reasons["approved"],
        active_reason=reasons["active"],
        supersede_reason=reasons["supersede"],
        actor=args.actor,
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
            _roll_back(label)
            return result
    return 0


def command_serve(args: argparse.Namespace) -> int:
    """Start the API against the live activation, resolving its scope from the database.

    This automates the LOOKUP, not the authority. The API still requires an explicit
    `-forecast-activation-scope` and still fails closed without one: a scope names the
    exact activation a reader is entitled to, and making the read model self-resolve
    would be a governance change rather than a convenience. What was manual here was
    copying a fingerprint out of psql by hand, which is not a decision anyone makes.
    """

    run_id = args.run_id or _newest_published_run()
    if run_id is None:
        print("no published run under ingestion/data/evidence", file=sys.stderr)
        return 2
    evidence = REPO_ROOT / "ingestion" / "data" / "evidence" / run_id
    curated = REPO_ROOT / "ingestion" / "data" / "curated" / run_id
    manifest_path = curated / "publication-manifest.json"
    if not manifest_path.is_file():
        print(f"no publication manifest at {manifest_path}", file=sys.stderr)
        return 2
    publication = json.loads(manifest_path.read_text(encoding="utf-8"))[
        "semanticFingerprint"
    ]

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
    dsn = _local_postgres_dsn(sqlalchemy=False)
    # The DSN carries a password, so it goes through the child's environment rather
    # than argv, where it would be visible to any process listing on the host. That
    # matters more now than it did with the hard-coded local default, because this
    # path deliberately honours a real deployment's credentials.
    probe_env = dict(os.environ)
    probe_env["RETAIL_PROBE_DSN"] = dsn
    probe = subprocess.run(
        [
            str(_require_python(ML_ENV, "ml")),
            "-c",
            "import os, sys, psycopg\n"
            "with psycopg.connect(os.environ['RETAIL_PROBE_DSN']) as c:\n"
            "    row = c.execute(\n"
            "        'select activation_scope_fingerprint from '\n"
            "        'retail_serving.active_forecast_versions '\n"
            "        'where publication_semantic_fingerprint = %s',\n"
            "        (sys.argv[1],),\n"
            "    ).fetchone()\n"
            "print(row[0] if row else '')\n",
            publication,
        ],
        capture_output=True, encoding="utf-8", errors="replace", check=False,
        env=probe_env,
    )
    fingerprint = (probe.stdout or "").strip()
    if not fingerprint:
        detail = (probe.stderr or "").strip().splitlines()[-1:] or ["(no error)"]
        print(
            f"no active forecast activation for publication {publication[:12]}… "
            f"(the publication {run_id} names). Materialize and activate a forecast "
            f"built on THIS publication, or pass --run-id for the one that is "
            f"active. Probe said: {detail[0]}",
            file=sys.stderr,
        )
        return 1
    print(f"resolved activation scope {fingerprint[:16]}… for {run_id}")
    environment = dict(os.environ)
    # Assignment, not setdefault: an override already in the environment may be the
    # SQLAlchemy form, and pgx rejects `postgresql+psycopg://`. `dsn` is the value
    # `_local_postgres_dsn` normalised and the probe just used successfully, so the
    # API and the probe now agree by construction.
    environment["RETAIL_POSTGRES_DSN"] = dsn
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
    ui = subprocess.Popen(  # noqa: S603
        [_npm(), "run", "dev"], cwd=REPO_ROOT / "ui"
    )
    try:
        return _run(api, cwd=REPO_ROOT / "api", env=environment)
    finally:
        ui.terminate()
        try:
            ui.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ui.kill()


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

    existing = sorted(output.glob("*/run-*"))
    if existing and not args.regenerate:
        print(
            "a promoted source run already exists; generation refused:\n  "
            + "\n  ".join(str(path.relative_to(REPO_ROOT)) for path in existing)
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
    promoted = sorted(output.glob("*/run-*"))
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
        except (OSError, json.JSONDecodeError):
            continue
        if (record.get("publication") or {}).get("logicalPath") == target:
            return True
    return False


def _pipeline_step_inline(label: str, action) -> None:
    """Time and label an in-process stage the way `_pipeline_step` does a subprocess."""

    print(f"\n===== {label} =====", flush=True)
    started = time.monotonic()
    code = action()
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
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        # Explicit UTF-8 rather than `text=True`. `text=True` decodes with the
        # PARENT's locale encoding, which is cp1252 on Windows, and PYTHONUTF8 set
        # above cannot change that -- an interpreter fixes its own stdio encoding at
        # startup, so the variable only reaches children. The result was a decode
        # mirror of the encode bug: the child now correctly WROTE MLflow's emoji as
        # UTF-8, the reader thread could not DECODE those bytes, `completed.stdout`
        # came back None, and the stage died on `.index("{")` after 3h21m of work
        # that had in fact succeeded. errors="replace" so a stray undecodable byte
        # degrades one character instead of discarding a completed stage's output.
        encoding="utf-8",
        errors="replace",
    )
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
                    "--source-profile",
                    str(REPO_ROOT / "ingestion" / "src" / "retail_ingestion"
                        / "profiles" / "retail_datagen.yaml"),
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
        # Timings before the message: a failed run's per-stage costs are how you tell
        # "the backtest is slow on this host" from "the backtest died immediately".
        _report_stage_timings()
        print(
            f"\npipeline failed at stage {failure.stage!r} (exit {failure.code})\n"
            f"resume with: tools/dev.py pipeline --from {failure.stage.split()[0]} "
            f"--to {args.to_stage} --label {args.label}",
            file=sys.stderr,
        )
        if "expected pin" in str(failure.stage):
            pass
        return failure.code
    _report_stage_timings()
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


def command_api_test(_: argparse.Namespace) -> int:
    environment = dict(os.environ)
    environment.setdefault(
        "GOCACHE",
        str(Path(tempfile.gettempdir()) / "retail-intelligence-go-cache"),
    )
    return _run(
        _go_test_command(),
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
