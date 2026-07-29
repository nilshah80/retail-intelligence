"""Cross-platform entry point for the complete governed ingestion pipeline.

Every stage (`land`, `gate-a`, `stage`, `transform`, `gate-b`, `publish`, `run`,
and `bench`) resolves its bounded execution settings through the shared resolver.
Execution tuning therefore changes resource use only, never source interpretation,
canonical meaning, capability decisions, or semantic fingerprints.
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

_PENDING_STAGES: dict[str, str] = {}


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
    land_parser.add_argument(
        "--source-profile",
        type=Path,
        default=None,
        help=(
            "required only when the retailer drop has no source-run-manifest.json; "
            "dataset pathGlob declarations then build immutable evidence"
        ),
    )

    gate_a_parser = subparsers.add_parser(
        "gate-a",
        help="Run manifest-derived raw/source-profile validation",
    )
    _add_profile_arguments(gate_a_parser)
    gate_a_parser.add_argument("--snapshot-root", type=Path, required=True)
    gate_a_parser.add_argument(
        "--source-profile",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "profiles"
            / "retail_datagen.yaml"
        ),
    )
    gate_a_parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="skip public content rehashing; A01 records metadata-only replay",
    )
    gate_a_parser.add_argument(
        "--skip-data-scan",
        action="store_true",
        help="skip Parquet row/key scans for fast diagnostics",
    )
    gate_a_parser.add_argument(
        "--report-path",
        type=Path,
        default=None,
        help="atomically write the JSON report in addition to stdout",
    )

    stage_parser = subparsers.add_parser(
        "stage",
        help="Run registered source adapters into standardized staging",
    )
    _add_profile_arguments(stage_parser)
    stage_parser.add_argument("--snapshot-root", type=Path, required=True)
    stage_parser.add_argument(
        "--source-profile",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "profiles"
            / "retail_datagen.yaml"
        ),
    )
    stage_parser.add_argument("--output-database", type=Path, required=True)

    transform_parser = subparsers.add_parser(
        "transform",
        help="Build a canonical retail_v2 candidate from standardized staging",
    )
    _add_profile_arguments(transform_parser)
    transform_parser.add_argument("--staging-database", type=Path, required=True)
    transform_parser.add_argument("--candidate-database", type=Path, required=True)

    gate_b_parser = subparsers.add_parser(
        "gate-b",
        help="Validate a canonical candidate and derive its capability mask",
    )
    _add_profile_arguments(gate_b_parser)
    gate_b_parser.add_argument("--candidate-database", type=Path, required=True)
    gate_b_parser.add_argument("--staging-database", type=Path, required=True)
    gate_b_parser.add_argument("--report-path", type=Path, default=None)

    publish_parser = subparsers.add_parser(
        "publish",
        help="Atomically publish a Gate-B-approved candidate",
    )
    _add_profile_arguments(publish_parser)
    publish_parser.add_argument("--candidate-database", type=Path, required=True)
    publish_parser.add_argument("--gate-b-report", type=Path, required=True)
    publish_parser.add_argument("--publication-root", type=Path, required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run or safely resume Gate A through curated publication",
    )
    _add_profile_arguments(run_parser)
    run_parser.add_argument("--snapshot-root", type=Path, required=True)
    run_parser.add_argument(
        "--source-profile",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "profiles"
            / "retail_datagen.yaml"
        ),
    )
    run_parser.add_argument("--work-root", type=Path, required=True)
    run_parser.add_argument("--publication-root", type=Path, required=True)
    run_parser.add_argument(
        "--rebuild",
        action="store_true",
        help="recompute governed work stages; immutable publication is never overwritten",
    )

    bench_parser = subparsers.add_parser(
        "bench",
        help="Run a disposable full-history per-stage benchmark",
    )
    _add_profile_arguments(bench_parser)
    bench_parser.add_argument("--snapshot-root", type=Path, required=True)
    bench_parser.add_argument(
        "--source-profile",
        type=Path,
        default=(
            Path(__file__).resolve().parent
            / "profiles"
            / "retail_datagen.yaml"
        ),
    )
    bench_parser.add_argument("--report-path", type=Path, required=True)
    bench_parser.add_argument("--temp-root", type=Path, default=None)
    bench_parser.add_argument("--work-root", type=Path, default=None)
    bench_parser.add_argument("--publication-root", type=Path, default=None)

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
        source_profile=args.source_profile,
        execution_profile=runtime.manifest_record(),
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_bench(args: argparse.Namespace) -> int:
    from .benchmark import run_full_benchmark

    runtime = _resolved_runtime(args)
    payload = run_full_benchmark(
        args.snapshot_root,
        args.source_profile,
        args.report_path,
        execution_profile=runtime.manifest_record(),
        temp_root=args.temp_root,
        work_root=args.work_root,
        publication_root=args.publication_root,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _cmd_gate_a(args: argparse.Namespace) -> int:
    from .quality import run_gate_a

    runtime = _resolved_runtime(args)
    report = run_gate_a(
        args.snapshot_root,
        args.source_profile,
        verify_content=not args.metadata_only,
        scan_data=not args.skip_data_scan,
        duckdb_threads=runtime.duckdb_threads,
        memory_limit_gb=runtime.memory_limit_gb,
        execution_profile=runtime.manifest_record(),
    )
    payload = report.as_dict()
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.report_path is not None:
        destination = args.report_path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(destination)
    print(rendered, end="")
    return 0 if report.status == "pass" else 4


def _cmd_stage(args: argparse.Namespace) -> int:
    from .staging import build_staging

    runtime = _resolved_runtime(args)
    result = build_staging(
        args.snapshot_root,
        args.source_profile,
        args.output_database,
        execution_profile=runtime.manifest_record(),
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_transform(args: argparse.Namespace) -> int:
    from .transforms import build_canonical_candidate

    runtime = _resolved_runtime(args)
    result = build_canonical_candidate(
        args.staging_database,
        args.candidate_database,
        execution_profile=runtime.manifest_record(),
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_gate_b(args: argparse.Namespace) -> int:
    from .quality import run_gate_b

    runtime = _resolved_runtime(args)
    report = run_gate_b(
        args.candidate_database,
        args.staging_database,
        execution_profile=runtime.manifest_record(),
    )
    rendered = json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"
    if args.report_path is not None:
        destination = args.report_path.expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(rendered, encoding="utf-8", newline="\n")
        temporary.replace(destination)
    print(rendered, end="")
    return 0 if report.status == "pass" else 5


def _cmd_publish(args: argparse.Namespace) -> int:
    from .publication import publish_candidate

    runtime = _resolved_runtime(args)
    result = publish_candidate(
        args.candidate_database,
        args.gate_b_report,
        args.publication_root,
        execution_profile=runtime.manifest_record(),
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from .pipeline import run_pipeline

    runtime = _resolved_runtime(args)
    result = run_pipeline(
        args.snapshot_root,
        args.source_profile,
        args.work_root,
        args.publication_root,
        execution_profile=runtime.manifest_record(),
        rebuild=args.rebuild,
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command in {
        "profile",
        "land",
        "gate-a",
        "stage",
        "transform",
        "gate-b",
        "publish",
        "run",
        "bench",
    }:
        try:
            commands = {
                "profile": _cmd_profile,
                "land": _cmd_land,
                "bench": _cmd_bench,
                "gate-a": _cmd_gate_a,
                "stage": _cmd_stage,
                "transform": _cmd_transform,
                "gate-b": _cmd_gate_b,
                "publish": _cmd_publish,
                "run": _cmd_run,
            }
            return commands[args.command](args)
        except (ProfileValidationError, OSError, ValueError, RuntimeError) as exc:
            print(f"{args.command} failed: {exc}", file=sys.stderr)
            return 2

    owner = _PENDING_STAGES[args.command]
    print(
        f"`{args.command}` is not implemented yet ({owner}). See plans/local/tasks.md.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    sys.exit(main())
