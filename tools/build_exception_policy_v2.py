"""Derive forecast exception policy v2 from v1 by adding decision #92's class.

`P4-1` task 7. Decision #92 withholds the cold-start interval beyond h4, and a
withheld interval is a fact a planner and a Phase 4 engine both have to act on.
Emitting it as an exception is how it reaches them; emitting it under policy v1
would mean the artifact advertised a class its own policy never defined.

Two things this gets right on purpose:

* **One record per affected series, not one per horizon.** The exceptions table
  key is `(version_id, sku_id, store_id, channel_id, exception_class)` with no
  horizon column, so 22 horizon rows would collide on the primary key rather than
  produce 22 records. The affected horizon *range* travels inside the evidence.
* **The fingerprint is computed, never typed.** `_verify_section` recomputes it on
  load and refuses a mismatch, so a hand-written value would fail closed at best
  and silently describe the wrong policy at worst.

v1 stays immutable: it is bound into every bundle published before this, and
rewriting it would retroactively change what those bundles claim to have applied.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "contracts" / "python" / "src"))

from retail_contracts.fingerprint import semantic_fingerprint  # noqa: E402

V1_PATH = REPO_ROOT / "contracts" / "ml" / "forecast-classification-policy.json"
V2_PATH = REPO_ROOT / "contracts" / "ml" / "forecast-classification-policy-v2.json"

NEW_CLASS = "cold_start_interval_unavailable"

#: The class definition. `emitOnce` is not decoration: it records why the grain is
#: the series rather than the horizon, so a later reader does not "fix" it into 22
#: rows and discover the primary key the hard way.
CLASS_DEFINITION: dict[str, Any] = {
    "formula": (
        "interval_available=false for at least one selected horizon of the "
        "SeriesKey; affected range is "
        "[unavailableFromHorizon, unavailableThroughHorizon]"
    ),
    "trigger": (
        "cohort=cold_start AND any horizon > calibratedMaxHorizon carries "
        "interval_available=false"
    ),
    "severity": "medium",
    "grain": "series_key",
    "emitOnce": (
        "Exactly one record per affected SeriesKey. forecast_exceptions is keyed "
        "on (version_id, sku_id, store_id, channel_id, exception_class) and has "
        "no horizon column, so per-horizon records would collide rather than "
        "accumulate. The affected horizon range is carried in the evidence."
    ),
    "thresholds": {
        "calibratedMaxHorizon": 4,
        "reasonCode": "COLD_START_INTERVAL_UNCALIBRATED",
    },
    "consumerBehavior": {
        "retainCentralForecast": True,
        "coerceNullToZero": False,
        "note": (
            "P50 remains available and usable where the consuming feature's own "
            "contract authorizes it. An interval-dependent output is skipped, "
            "never computed from a zero spread: safety stock is quantile spread "
            "times service level, so a zero would return zero safety stock on the "
            "least predictable products."
        ),
    },
}

TEST_VECTOR: dict[str, Any] = {
    "id": "cold-start-interval-withheld-beyond-h4",
    "input": {
        "cohort": "cold_start",
        "calibrated_max_horizon": 4,
        "interval_withheld_horizon_count": 22,
        "interval_unavailable_from_horizon": 5,
        "interval_unavailable_through_horizon": 26,
        "interval_unavailable_reason": "COLD_START_INTERVAL_UNCALIBRATED",
    },
    "expected": {
        "exception_classes": [NEW_CLASS],
        "records": 1,
        "severity": "medium",
    },
}

NOT_TRIGGERED_VECTOR: dict[str, Any] = {
    "id": "established-history-keeps-its-full-range-interval",
    "input": {
        "cohort": "established_history",
        "calibrated_max_horizon": 4,
        "interval_withheld_horizon_count": 0,
        "interval_unavailable_from_horizon": None,
        "interval_unavailable_through_horizon": None,
        "interval_unavailable_reason": None,
    },
    "expected": {"exception_classes": [], "records": 0},
}


def build() -> dict[str, Any]:
    v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
    exceptions = json.loads(json.dumps(v1["exceptions"]))

    if NEW_CLASS in exceptions["classes"]:
        raise SystemExit(f"{NEW_CLASS} is already defined in v1")

    exceptions["policyId"] = "retail-forecast-exceptions/v2"
    exceptions["classes"][NEW_CLASS] = CLASS_DEFINITION
    exceptions["supersedes"] = {
        "policyId": v1["exceptions"]["policyId"],
        "semanticFingerprint": v1["exceptions"]["semanticFingerprint"],
        "reason": (
            "Adds decision #92's cold_start_interval_unavailable class. v1 stays "
            "immutable and remains the bound policy for every bundle published "
            "before this one."
        ),
    }
    exceptions["decisionIds"] = [60, 92]
    exceptions["testVectors"] = [
        *exceptions["testVectors"],
        TEST_VECTOR,
        NOT_TRIGGERED_VECTOR,
    ]
    exceptions.pop("semanticFingerprint", None)
    exceptions["semanticFingerprint"] = semantic_fingerprint(
        exceptions, volatile_pointers=()
    )

    return {
        "schemaVersion": "retail-forecast-classification-policy/v2",
        "decisionId": 60,
        "decisionIds": [60, 92],
        "exceptions": exceptions,
        # Unchanged and carried forward byte-for-byte, fingerprint included. The
        # quality battery is not what decision #92 touches, and reproducing it
        # here rather than referencing v1 keeps the document self-contained the
        # way the loader expects.
        "dataQuality": v1["dataQuality"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    policy = build()
    rendered = json.dumps(policy, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not V2_PATH.is_file():
            print("exception policy v2 is absent", file=sys.stderr)
            return 1
        if V2_PATH.read_text(encoding="utf-8") != rendered:
            print("exception policy v2 drifted from its derivation", file=sys.stderr)
            return 1
        print("exception policy v2 matches its derivation")
        return 0
    V2_PATH.write_text(rendered, encoding="utf-8")
    print(
        f"wrote {V2_PATH.relative_to(REPO_ROOT)}\n"
        f"  policyId: {policy['exceptions']['policyId']}\n"
        f"  fingerprint: {policy['exceptions']['semanticFingerprint']}\n"
        f"  classes: {len(policy['exceptions']['classes'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
