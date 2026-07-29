#!/usr/bin/env python3
"""Benchmark logical-equivalent datagen execution profiles on one scenario."""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from retail_execution import available_profiles, resolve_profile
from retail_datagen.config import load_config
from retail_datagen.generator import generate


DATAGEN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = DATAGEN_ROOT / "configs" / "multi-market-showcase.yaml"


def _byte_objects(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        source_object["path"]: source_object["sha256"]
        for source_object in manifest["objects"]
        if source_object["contentDeterminism"] == "byte"
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one disposable run per profile, compare authoritative "
            "hashes, and print measured execution telemetry."
        )
    )
    parser.add_argument("-c", "--config", default=str(DEFAULT_CONFIG))
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=["safe", "performance", "ultra-performance"],
        choices=available_profiles(),
    )
    args = parser.parse_args()
    config = load_config(args.config)
    results: list[dict[str, Any]] = []
    authoritative: dict[str, dict[str, str]] = {}
    controls: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(
        prefix="retail-datagen-profile-benchmark-"
    ) as temporary_root:
        for profile_name in args.profiles:
            started = time.perf_counter()
            result = generate(
                config,
                str(Path(temporary_root) / profile_name),
                execution_profile=resolve_profile(
                    profile_name,
                    environment={},
                ),
            )
            elapsed = time.perf_counter() - started
            manifest = result["manifest"]
            authoritative[profile_name] = _byte_objects(manifest)
            controls[profile_name] = manifest["controlsByCurrency"]
            results.append(
                {
                    "profile": profile_name,
                    "runId": result["runId"],
                    "elapsedSeconds": round(elapsed, 3),
                    "executionProfile": manifest["executionProfile"],
                    "executionTelemetry": manifest["executionTelemetry"],
                    "authoritativeObjects": len(authoritative[profile_name]),
                }
            )
    baseline = args.profiles[0]
    parity = all(
        authoritative[name] == authoritative[baseline]
        and controls[name] == controls[baseline]
        for name in args.profiles[1:]
    )
    print(
        json.dumps(
            {
                "config": str(Path(args.config).resolve()),
                "profiles": results,
                "logicalParity": parity,
                "temporaryOutputsRemoved": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if not parity:
        raise SystemExit("execution profiles changed authoritative output")


if __name__ == "__main__":
    main()
