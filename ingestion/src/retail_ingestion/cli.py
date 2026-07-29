"""Ingestion command-line entry point.

Stage commands are added as their workstreams land (`land`, `gate-a`, `stage`,
`transform`, `gate-b`, `publish`, `run`, `bench`). What exists today is the runtime
surface: every stage resolves its bounded execution profile through the shared
resolver, so there is exactly one place that decides how much machine a run may use.

Unimplemented stages exit non-zero with an explicit message rather than printing a
misleading success.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from retail_execution.profiles import (
    ProfileValidationError,
    available_profiles,
    load_profile_document,
)

from . import INGESTION_VERSION, PROFILE_CONTRACT_VERSION
from .runtime.profile import resolve_ingestion_runtime

_PENDING_STAGES = {
    "gate-a": "W2 — generic manifest-derived raw validation",
    "stage": "W3 — profile/adapter normalization to staging envelopes",
    "transform": "W4 — source-neutral transforms to canonical retail_v2",
    "gate-b": "W4 — canonical validation, capability mask and quarantine",
    "publish": "W4 — atomic curated Parquet/DuckDB publication",
    "run": "W2-W4 — full pipeline",
    "bench": "W5 — per-stage benchmarks and SLAs",
}


def _add_profile_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--execution-profile",
        dest="execution_profile",
        choices=sorted(available_profiles()),
        default=None,
        help=(
            "bounded runtime profile; omit to use the shared resolver's default. "
            "Precedence: explicit field override > environment > profile document > "
            "named profile > safe"
        ),
    )
    parser.add_argument(
        "--execution-profile-file",
        type=Path,
        default=None,
        help="cross-platform YAML or JSON execution-profile document",
    )
    parser.add_argument("--scan-workers", type=int, default=None)
    parser.add_argument("--transform-workers", type=int, default=None)
    parser.add_argument("--write-workers", type=int, default=None)
    parser.add_argument("--duckdb-threads", type=int, default=None)
    parser.add_argument("--memory-limit-gb", type=int, default=None)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retail-ingest",
        description="Retail Intelligence source ingestion",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"retail-ingestion {INGESTION_VERSION} ({PROFILE_CONTRACT_VERSION})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    profile_parser = subparsers.add_parser(
        "profile",
        help="Show the resolved execution profile for a run",
    )
    _add_profile_arguments(profile_parser)

    land_parser = subparsers.add_parser(
        "land",
        help="Land and hash-verify an immutable source snapshot",
    )
    _add_profile_arguments(land_parser)
    land_parser.add_argument("--source-root", type=Path, required=True)
    land_parser.add_argument("--landing-root", type=Path, required=True)
    land_parser.add_argument("--source-instance", default=None)
    land_parser.add_argument("--extract-boundary", default=None)

    for name, owner in _PENDING_STAGES.items():
        stage_parser = subparsers.add_parser(name, help=f"[not implemented] {owner}")
        _add_profile_arguments(stage_parser)

    return parser


def _resolved_runtime(args: argparse.Namespace):
    document = (
        load_profile_document(args.execution_profile_file)
        if args.execution_profile_file is not None
        else None
    )
    overrides = {
        "scanWorkers": args.scan_workers,
        "transformWorkers": args.transform_workers,
        "writeWorkers": args.write_workers,
        "duckdbThreads": args.duckdb_threads,
        "memoryLimitGb": args.memory_limit_gb,
    }
    return resolve_ingestion_runtime(
        args.execution_profile,
        document=document,
        overrides=overrides,
    )


def _cmd_profile(args: argparse.Namespace) -> int:
    runtime = _resolved_runtime(args)
    payload = {
        **runtime.manifest_record(),
        "duckdbPragmas": list(runtime.duckdb_pragmas()),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_land(args: argparse.Namespace) -> int:
    from .landing import land_source_snapshot

    runtime = _resolved_runtime(args)
    result = land_source_snapshot(
        args.source_root,
        args.landing_root,
        source_instance=args.source_instance,
        extract_boundary=args.extract_boundary,
        execution_profile=runtime.manifest_record(),
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in {"profile", "land"}:
        try:
            return _cmd_profile(args) if args.command == "profile" else _cmd_land(args)
        except (ProfileValidationError, OSError, ValueError, RuntimeError) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 2

    owner = _PENDING_STAGES[args.command]
    print(
        f"`{args.command}` is not implemented yet ({owner}). "
        "See plans/local/phase2-implementation-plan.md.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    sys.exit(main())
