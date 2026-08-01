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
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORD = REPO_ROOT / "contracts" / "evidence" / "forecast-closure-record.json"
MIGRATIONS = REPO_ROOT / "db" / "migrations" / "versions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alembic_head() -> str:
    """Derive the required serving migration from the migration graph.

    This was a hard-coded `0007_activation_and_coverage` while every other client
    -- ML materializer, ML publisher, Go read model, database schema test -- had
    moved to 0008. A generated record that hard-codes one of its own facts is
    exactly the drift the generator exists to prevent, so the head is read from
    the revisions themselves: the one revision nothing else revises.
    """

    revision_pattern = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)
    down_pattern = re.compile(
        r'^down_revision:[^=]*=\s*(?:"([^"]+)"|None)', re.MULTILINE
    )
    revisions: dict[str, str | None] = {}
    for path in sorted(MIGRATIONS.glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8")
        revision = revision_pattern.search(text)
        down = down_pattern.search(text)
        if not revision or not down:
            raise SystemExit(f"{path.name} does not declare a revision pair")
        revisions[revision.group(1)] = down.group(1)
    revised = {down for down in revisions.values() if down is not None}
    heads = sorted(set(revisions) - revised)
    if len(heads) != 1:
        raise SystemExit(f"Alembic history is not linear; heads = {heads}")
    return heads[0]


#: `P4-0` task 9. The v2 simplification derived everything from the bundle and the
#: live activation, which is why it stopped drifting -- and in doing so it silently
#: dropped the pre-v2 ledger of C5-generation supersessions and attestations. That
#: history is not derivable from either source, because four of the sibling bundles
#: were deleted without retaining their manifest or acceptance hashes. Dropping it
#: is a governed disposition or it is data loss; this makes it the former. A
#: deterministic rerun must never be used to fill these hashes: that would be a
#: reconstruction presented as an original record.
HISTORICAL_ATTESTATION_LEDGER = {
    "disposition": "retained_by_reference_with_declared_missing_hashes",
    "note": (
        "The pre-v2 closure ledger held manifest and acceptance hashes for older "
        "generations that never reached the current serving schema. Those that were "
        "hashed remain verifiable by reference; those whose bytes are gone are "
        "recorded as missing and are never reconstructed."
    ),
    "hashedGenerations": [
        {"generation": "pitfix_v12", "hashesRetained": True},
        {"generation": "pitfix_v14", "hashesRetained": True},
        {"generation": "pitfix_v15", "hashesRetained": True},
        {
            "generation": "v6_cohort82",
            "hashesRetained": True,
            "note": "Separately rejected; retained as rejected evidence.",
        },
        {
            "generation": "forecast_run_v6_c5_final",
            "hashesRetained": True,
            "note": "The only one of the five C5 siblings with retained hashes.",
        },
    ],
    "unhashedSupersededSiblings": [
        {
            "forecastRunId": "fr_463f53be6353e481",
            "generation": "_c5",
            "hashesRetained": False,
        },
        {
            "forecastRunId": "fr_f62041e95fe7c305",
            "generation": "_v2",
            "hashesRetained": False,
        },
        {
            "forecastRunId": "fr_b55046df351c1a65",
            "generation": "_grain",
            "hashesRetained": False,
        },
        {
            "forecastRunId": "fr_8e73fb0f8d3c502c",
            "generation": "_gov",
            "hashesRetained": False,
        },
    ],
    "unhashedSiblingReason": (
        "Bundle bytes were deleted before their manifest/acceptance hashes were "
        "retained. Superseded by retained run id, original directory, generation "
        "label and reason only."
    ),
    "reconstructionForbidden": True,
    "attestationClassification": {
        "windowsLinuxPortability": "user_attested",
        "trackA": "user_attested",
        "note": (
            "Attested evidence is labelled attested, never locally_verified. No "
            "retained execution artifact exists for these on this host."
        ),
    },
}

#: `P4-0` task 13. The served-field withholding is live; the rest of decision #92 is
#: not. Recording the gap here rather than in prose is what makes the handoff
#: enforceable: `P4-1` cannot claim completion while any of these stays true.
DECISION_92_RESIDUE = {
    "servedFieldWithholdingImplemented": True,
    "handedTo": "P4-1",
    "openItems": [
        "versioned cold_start_interval_unavailable series exception "
        "(one per affected series, not one per horizon)",
        "exact availability/reason/nullability truth table enforced in the "
        "Parquet row, not derived from P90 nullability in Go",
        "migration 0009 explicit interval_available column forbidding a reason "
        "on an available interval",
        "served interval aggregate repair (plan §1.3.1): the P50-weighted "
        "confidence mean counts withheld weeks in its denominator only",
        "final-pin republication after the P4-3 source pin changes",
        "interval-consumer integration under P4-D17",
    ],
    "twoOperationsAreDistinct": {
        "withheldFromPublication": {
            "rows": 8756,
            "series": 398,
            "horizonRange": "H5-H26",
            "cohort": "cold_start",
            "effect": (
                "null P90/confidence in the artifact, the projection and the API. "
                "This is what a planner and a Phase 4 engine consume."
            ),
        },
        "excludedFromOneGateCell": {
            "rows": 86636,
            "cell": "A2_per_cohort.cold_start",
            "effect": (
                "removed from that cohort's coverage denominator only. "
                "Whole-population A2 still scores all 708,708 evaluation rows, and "
                "forecast_eval_predictions retains non-null P90/confidence on every "
                "one of them."
            ),
        },
    },
    "servedAggregateDefectMeasured": {
        "planReference": "plans/local/phase4-implementation-plan.md §1.3.1",
        "affectedSeries": 398,
        "seriesWithIntervalTotalBelowCentralTotal": 372,
        "servedMeanWeightedConfidence": 0.0814,
        "coveredWeekMeanWeightedConfidence": 0.5817,
        "affectedSelections": [8, 13, 26],
        "cleanSelections": [4],
        "gatedBy": "P4-0P",
    },
}


def _psql(sql: str) -> list[list[str]]:
    result = subprocess.run(
        [
            "docker", "compose", "-f", str(REPO_ROOT / "deploy" / "compose.yaml"),
            "exec", "-T", "postgres", "psql", "-U", "retail",
            "-d", "retail_intelligence", "-Atc", sql,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"psql failed: {result.stderr.strip()}")
    return [
        line.split("|") for line in result.stdout.strip().splitlines() if line
    ]


def _live_migration() -> str:
    rows = _psql("SELECT version_num FROM retail_intelligence_alembic_version")
    if len(rows) != 1:
        raise SystemExit(f"expected one Alembic version row, found {len(rows)}")
    return rows[0][0]


def _live_activation() -> dict[str, str]:
    rows = _psql(
        "SELECT forecast_run_id||'|'||version_id||'|'"
        "||activation_scope_fingerprint FROM "
        "retail_serving.active_forecast_versions"
    )
    if len(rows) != 1:
        raise SystemExit(
            f"decision #90 requires exactly one active forecast version, found {len(rows)}"
        )
    run_id, version_id, scope = rows[0]
    return {
        "forecastRunId": run_id,
        "forecastVersionId": version_id,
        "activationScopeFingerprint": scope,
    }


def _bundle_index() -> dict[str, str]:
    """Map every locally retained run id to its bundle directory.

    Retention is a fact about the filesystem, so it is measured rather than
    declared. A version whose bytes are gone cannot be re-verified or rolled back
    to, and the record has to say so instead of listing an id that looks intact.
    """

    index: dict[str, str] = {}
    for manifest_path in sorted(
        (REPO_ROOT / "ml" / "data" / "artifacts").glob("*/forecast-run-manifest.json")
    ):
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        run_id = manifest.get("forecastRunId")
        if run_id:
            index[run_id] = str(manifest_path.parent.relative_to(REPO_ROOT))
    return index


def _authority_ledger(active_run: str) -> dict:
    """The append-only activation chain, read from PostgreSQL.

    Decision #93's invariant is a property of this chain, not of a prose summary:
    event 7 activated with a null predecessor, event 8 superseded it, and event 9
    continues from 8. Reading the chain rather than restating it means the record
    cannot claim a successor link the database does not have.
    """

    events = [
        {
            "eventId": int(row[0]),
            "priorEventId": int(row[1]) if row[1] else None,
            "eventType": row[2],
            "forecastRunId": row[3],
            "versionId": row[4],
            "activationScopeFingerprint": row[5],
            "actor": row[6],
            "recordedAt": row[7],
        }
        for row in _psql(
            "SELECT event_id, coalesce(prior_event_id::text,''), event_type, "
            "forecast_run_id, version_id, activation_scope_fingerprint, actor, "
            "recorded_at FROM retail_serving.forecast_activation_events "
            "ORDER BY event_id"
        )
    ]
    active_events = [event for event in events if event["eventType"] == "active"]
    superseded_ids = {
        event["priorEventId"] for event in events if event["eventType"] == "superseded"
    }
    current = [
        event for event in active_events if event["eventId"] not in superseded_ids
    ]
    if len(current) != 1:
        raise SystemExit(
            f"exactly one activation event must be current, found {len(current)}"
        )
    if current[0]["forecastRunId"] != active_run:
        raise SystemExit(
            f"current activation event names {current[0]['forecastRunId']}, "
            f"but the active view serves {active_run}"
        )
    # Event ids 3 and 4 were consumed by rolled-back transactions. The identity
    # sequence does not reuse them, so the gap is recorded as observed instead of
    # being renumbered into a tidier-looking chain.
    observed = [event["eventId"] for event in events]
    gaps = [
        candidate
        for candidate in range(min(observed), max(observed) + 1)
        if candidate not in observed
    ]
    return {
        "events": events,
        "currentEventId": current[0]["eventId"],
        "currentPriorEventId": current[0]["priorEventId"],
        "nullPredecessorEventIds": [
            event["eventId"] for event in events if event["priorEventId"] is None
        ],
        "unusedEventIds": gaps,
        "unusedEventIdNote": (
            "Identity-sequence values consumed by rolled-back transactions. "
            "Recorded as observed; never renumbered."
        ),
    }


def _superseded_identities(active_run: str, active_version: str) -> list[dict]:
    """Every materialized identity that is not the current authority.

    `P4-0` task 11. The v2 record dropped this ledger entirely rather than
    recording a disposition for it, so a superseded generation became invisible
    instead of visibly retired.
    """

    bundles = _bundle_index()
    rows = _psql(
        "SELECT version_id, forecast_run_id FROM retail_serving.forecast_versions "
        "ORDER BY version_id"
    )
    ledger: list[dict] = []
    for version_id, run_id in rows:
        if run_id == active_run and version_id == active_version:
            continue
        bundle = bundles.get(run_id)
        ledger.append(
            {
                "forecastRunId": run_id,
                "forecastVersionId": version_id,
                "bundleBytesRetained": bundle is not None,
                "bundlePath": bundle,
                "activationEligible": False,
                "rollbackEligible": bundle is not None,
                "reason": (
                    "Superseded under decision #90 authority-generation-2; retained "
                    "as historical evidence."
                    if bundle
                    else "Superseded and bundle bytes are gone; it cannot be "
                    "re-verified, activated, or used as a rollback target. Never "
                    "reconstructed."
                ),
            }
        )
    return ledger


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

    required_migration = _alembic_head()
    applied_migration = _live_migration()
    if applied_migration != required_migration:
        raise SystemExit(
            f"the database is at {applied_migration} but the required head is "
            f"{required_migration}; run tools/dev.py db-upgrade before generating "
            "the closure record"
        )
    ledger = _authority_ledger(live["forecastRunId"])
    superseded = _superseded_identities(
        live["forecastRunId"], live["forecastVersionId"]
    )
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
        "authorityLedger": ledger,
        "supersededIdentities": superseded,
        "historicalAttestationLedger": HISTORICAL_ATTESTATION_LEDGER,
        "decision92Residue": DECISION_92_RESIDUE,
        "servingMigration": required_migration,
        "servingMigrationSource": (
            "derived from the Alembic revision graph and confirmed against the "
            "applied database head; never hard-coded"
        ),
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
