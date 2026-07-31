"""Generate the forecast closure record from the accepted artifact and live activation.

Written because the hand-maintained record accumulated several generations of evidence at
once: stale artifact hashes, a stale semantic fingerprint, a materialization action naming
a superseded version, an A5 line still reporting a failure that had been fixed, the old
input publication, and the current run listed as superseded by itself. No contract
validator checked it, so the full developer gate passed while the record contradicted the
run it claimed to describe.

A record that can drift is a record nobody can rely on. This derives every field from the
bundle on disk and the live activation, so drift becomes impossible rather than merely
discouraged, and tools/dev.py contracts checks it.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORD = REPO_ROOT / "contracts" / "evidence" / "forecast-closure-record.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _live_activation() -> dict[str, str]:
    result = subprocess.run(
        [
            "docker", "compose", "-f", str(REPO_ROOT / "deploy" / "compose.yaml"),
            "exec", "-T", "postgres", "psql", "-U", "retail",
            "-d", "retail_intelligence", "-Atc",
            "SELECT forecast_run_id||'|'||version_id||'|'"
            "||activation_scope_fingerprint FROM "
            "retail_serving.active_forecast_versions",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    rows = [line for line in result.stdout.strip().splitlines() if line]
    if len(rows) != 1:
        raise SystemExit(
            f"decision #90 requires exactly one active forecast version, found {len(rows)}"
        )
    run_id, version_id, scope = rows[0].split("|")
    return {
        "forecastRunId": run_id,
        "forecastVersionId": version_id,
        "activationScopeFingerprint": scope,
    }


def build(bundle: Path) -> dict:
    manifest = json.loads((bundle / "forecast-run-manifest.json").read_text())
    acceptance = json.loads((bundle / "forecast_acceptance.json").read_text())
    live = _live_activation()
    if live["forecastRunId"] != manifest["forecastRunId"]:
        raise SystemExit(
            f"bundle {manifest['forecastRunId']} is not the active run "
            f"{live['forecastRunId']}; the record must describe what serves"
        )
    policy = manifest.get("modelPolicy") or {}
    remediation = policy.get("remediation") or {}
    checks = remediation.get("structuralChecks") or {}
    per_cohort = acceptance["global"]["gates"]["A2_per_cohort"]
    return {
        "schemaVersion": "retail-forecast-closure-record/v2",
        "recordType": "generated_closure_record",
        "generatedBy": "tools/build_closure_record.py",
        "note": (
            "Generated, never hand-edited. The v1 record was maintained by hand and "
            "accumulated several generations of evidence at once while no validator "
            "checked it, so the developer gate passed on a record that contradicted the "
            "run it described. Regenerate with: "
            "tools/dev.py closure-record --forecast-run <bundle>"
        ),
        "bundlePath": str(bundle.relative_to(REPO_ROOT)),
        "acceptedRun": {
            "forecastRunId": manifest["forecastRunId"],
            "forecastVersionId": live["forecastVersionId"],
            "lifecycleStatus": manifest.get("lifecycleStatus"),
            "runSemanticFingerprint": manifest["semanticFingerprint"],
            "decisionAsOf": manifest.get("decisionAsOf"),
        },
        "artifactHashes": {
            name: _sha256(bundle / name)
            for name in sorted(p.name for p in bundle.glob("*.json"))
        },
        "inputBundle": manifest["inputBundle"],
        "liveActivation": live,
        "acceptance": {
            "schemaVersion": acceptance["schemaVersion"],
            "passed": acceptance["passed"],
            "candidateClass": acceptance.get("candidateClass"),
            "coverageGateMode": acceptance.get("coverageGateMode"),
            "gates": {
                name: gate.get("passed")
                for name, gate in acceptance["global"]["gates"].items()
                if isinstance(gate, dict)
            },
            "perCohortCoverage": {
                cohort: entry["p90Coverage"]
                for cohort, entry in per_cohort["cohorts"].items()
            },
        },
        "intervalAvailability": manifest.get("intervalAvailability"),
        "decision86StructuralChecks": {
            "refusingCriteria": checks.get("refusingCriteria"),
            "reportOnlyCriteria": checks.get("reportOnlyCriteria"),
            "displayGrainsEvaluated": (
                (checks.get("displayCellIntegrity") or {}).get("grainsEvaluated")
            ),
            "displayPassed": (
                (checks.get("displayCellIntegrity") or {}).get("passed")
            ),
        },
        "servingMigration": "0007_activation_and_coverage",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: build_closure_record.py <forecast-run-bundle>", file=sys.stderr)
        return 2
    record = build(Path(argv[1]).resolve())
    RECORD.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(f"wrote {RECORD.relative_to(REPO_ROOT)} for {record['acceptedRun']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
