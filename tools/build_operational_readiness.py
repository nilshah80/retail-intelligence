#!/usr/bin/env python3
"""Create or check the identity-bound operational-readiness sidecar."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "ingestion/src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "contracts/python/src"))

from retail_ingestion.readiness.operational import (  # noqa: E402
    validate_readiness_retention,
    validate_operational_readiness,
    write_readiness_retention,
    write_operational_readiness_sidecar,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-a", type=Path, required=True)
    parser.add_argument("--gate-b", type=Path, required=True)
    parser.add_argument("--publication-manifest", type=Path, required=True)
    parser.add_argument("--producer-registry", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=REPOSITORY_ROOT / "contracts/onboarding/readiness-report-v2.schema.json")
    parser.add_argument(
        "--retention-schema",
        type=Path,
        default=REPOSITORY_ROOT / "contracts/onboarding/readiness-retention.schema.json",
    )
    parser.add_argument("--retention-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    retention_output = args.retention_output or args.output.with_name(
        "operational-readiness-retention.json"
    )
    if args.check:
        if not args.output.is_file():
            print(f"readiness sidecar is absent: {args.output}", file=sys.stderr)
            return 1
        existing = json.loads(args.output.read_text(encoding="utf-8"))
        validate_operational_readiness(existing, schema_path=args.schema)
        # The writer performs the independent upstream-identity comparison and
        # refuses if the retained sidecar describes different bytes.
        report = write_operational_readiness_sidecar(
            gate_a_path=args.gate_a, gate_b_path=args.gate_b,
            publication_manifest_path=args.publication_manifest,
            destination=args.output, producer_registry_path=args.producer_registry,
            schema_path=args.schema,
        )
        if report["reportFingerprint"] != existing["reportFingerprint"]:
            return 1
        if not retention_output.is_file():
            print(
                f"readiness retention record is absent: {retention_output}",
                file=sys.stderr,
            )
            return 1
        validate_readiness_retention(
            json.loads(retention_output.read_text(encoding="utf-8")),
            schema_path=args.retention_schema,
            readiness_path=args.output,
            readiness_schema_path=args.schema,
        )
        print("operational readiness matches retained upstream evidence")
        return 0
    report = write_operational_readiness_sidecar(
        gate_a_path=args.gate_a, gate_b_path=args.gate_b,
        publication_manifest_path=args.publication_manifest,
        destination=args.output, producer_registry_path=args.producer_registry,
        schema_path=args.schema,
    )
    retention = write_readiness_retention(
        readiness_path=args.output,
        destination=retention_output,
        schema_path=args.retention_schema,
        readiness_schema_path=args.schema,
    )
    print(json.dumps({
        "output": str(args.output),
        "reportFingerprint": report["reportFingerprint"],
        "retentionOutput": str(retention_output),
        "retainedByteSha256": retention["files"]["operational-readiness.json"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
