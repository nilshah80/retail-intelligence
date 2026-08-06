"""Generate the inventory & replenishment capability entry record.

`P4-0` tasks 2, 12, 13 and the `P4-0P` recording obligation. This is the record a
later package reads to answer "was Phase 4 authorized to start, and on what". It
is generated rather than written for the same reason the closure record is: the
last hand-maintained governance record in this repository accumulated four
generations of evidence at once while the developer gate passed.

Every count below is measured against the live PostgreSQL projection and the
immutable bundle, not transcribed from the plan. Where a fact cannot be measured
on this host it is recorded as attested and named as such.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORD = REPO_ROOT / "contracts" / "evidence" /\
    "inventory-replenishment-entry-record.json"
PARITY_CONTRACT = REPO_ROOT / "contracts" / "screens" / "demand-forecast.parity.yaml"
SELECTION_ROOT = REPO_ROOT / "contracts" / "evidence" / "publication-selections"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    return [line.split("|") for line in result.stdout.strip().splitlines() if line]


def _one(sql: str) -> list[str]:
    rows = _psql(sql)
    if len(rows) != 1:
        raise SystemExit(f"expected exactly one row from: {sql}")
    return rows[0]


def _measure_serving(version_id: str, run_id: str) -> dict[str, Any]:
    """Measure the served and evaluated populations separately.

    They are different populations and conflating them is the specific error the
    plan warns about twice: 8,756 rows lose an interval in *serving*, while 86,636
    rows are dropped from *one gate cell* and keep their interval everywhere.
    """

    served = _one(
        "SELECT count(*)||'|'||count(DISTINCT (sku_id,store_id,channel_id))||'|'"
        "||count(*) FILTER (WHERE yhat_p90 IS NULL)||'|'"
        "||count(*) FILTER (WHERE confidence IS NULL)||'|'"
        "||count(*) FILTER (WHERE yhat_p50 IS NULL)||'|'"
        "||count(DISTINCT horizon_week)||'|'||min(horizon_week)||'|'"
        "||max(horizon_week)||'|'"
        "||count(DISTINCT interval_unavailable_reason) "
        f"FROM retail_serving.forecast_series WHERE version_id='{version_id}'"
    )
    withheld = _one(
        "SELECT count(DISTINCT (sku_id,store_id,channel_id))||'|'"
        "||min(horizon_week)||'|'||max(horizon_week)||'|'"
        "||coalesce(max(interval_unavailable_reason),'') "
        f"FROM retail_serving.forecast_series WHERE version_id='{version_id}' "
        "AND yhat_p90 IS NULL"
    )
    evaluated = _one(
        "SELECT count(*)||'|'||count(*) FILTER (WHERE yhat_p90 IS NULL)||'|'"
        "||count(*) FILTER (WHERE confidence IS NULL)||'|'"
        "||count(DISTINCT horizon) "
        "FROM retail_serving.forecast_eval_predictions "
        f"WHERE forecast_run_id='{run_id}'"
    )
    return {
        "currentCycle": {
            "rows": int(served[0]),
            "servedSeriesKeys": int(served[1]),
            "p90NullRows": int(served[2]),
            "confidenceNullRows": int(served[3]),
            "p50NullRows": int(served[4]),
            "distinctHorizons": int(served[5]),
            "horizonRange": [int(served[6]), int(served[7])],
            "distinctUnavailableReasons": int(served[8]),
        },
        "withheldFromPublication": {
            "rows": int(served[2]),
            "series": int(withheld[0]),
            "horizonRange": [int(withheld[1]), int(withheld[2])],
            "reasonCode": withheld[3],
        },
        "evaluationPopulation": {
            "rows": int(evaluated[0]),
            "p90NullRows": int(evaluated[1]),
            "confidenceNullRows": int(evaluated[2]),
            "distinctHorizons": int(evaluated[3]),
            "note": (
                "Withholding is per-field on the served cycle only. Evaluation "
                "retains a non-null interval on every row, which is what makes the "
                "A2 gate scoping falsifiable rather than self-fulfilling."
            ),
        },
    }


def _selection() -> dict[str, Any]:
    """The CURRENT active selection for the capability this record is about.

    Currency is derived from the supersedes chain, not read from the `state`
    field, and the capability is named rather than taken first. Taking the first
    record whose state reads "active" in filename order is the arbitrary
    tie-break decision #90 exists to remove: the directory holds every lifecycle
    record ever written, three capabilities are active at once, and a superseded
    record still says "active" in its own lifecycle -- it is superseded by
    something else pointing at it, which only the chain knows.

    That is not hypothetical. With three chains live it picked a stale record and
    refused to build, reporting that the selection named a different publication
    than the forecast serves, when in fact it had read the wrong selection.
    """

    sys.path.insert(0, str(REPO_ROOT / "ingestion" / "src"))
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from build_publication_selection import current_records  # noqa: PLC0415
    from retail_ingestion.readiness.selection import scope_key  # noqa: PLC0415

    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(SELECTION_ROOT.glob("*.json"))
    ]
    active = None
    for record in current_records(records):
        if (record.get("lifecycle") or {}).get("state") != "active":
            continue
        if scope_key(record)[2] == "demand_forecast_non_pit":
            active = record
            break
    if active is None:
        raise SystemExit(
            "no active decision-#73 selection exists; P4-0 cannot exit without one"
        )
    # Resolve the ids back against the committed directory before writing them.
    #
    # This record shipped once naming `rec_3955dd35e0b6d9e3`, a lifecycle record that
    # exists in no committed file -- the selection records had moved and this had not.
    # The only assertion on the field is `startswith("rec_")`, which cannot see that,
    # so a governance record pointed at nothing for a whole commit. A pointer into a
    # committed set should be checked against that set.
    resolved = [
        record
        for record in records
        if (record.get("lifecycle") or {}).get("recordId")
        == active["lifecycle"]["recordId"]
    ]
    if len(resolved) != 1:
        raise SystemExit(
            f"activeRecordId {active['lifecycle']['recordId']} matches "
            f"{len(resolved)} committed records; it must match exactly one"
        )
    resolved_record = resolved[0]
    if resolved_record["selectionId"] != active["selectionId"]:
        raise SystemExit(
            "the record named by activeRecordId carries selectionId "
            f"{resolved_record['selectionId']} but this record would claim "
            f"{active['selectionId']}"
        )
    if scope_key(resolved_record)[2] != "demand_forecast_non_pit":
        raise SystemExit(
            "activeRecordId names a record for scope "
            f"{scope_key(resolved_record)[2]}, not demand_forecast_non_pit"
        )
    if (resolved_record.get("lifecycle") or {}).get("state") != "active":
        raise SystemExit(
            "activeRecordId names a record whose state is "
            f"{(resolved_record.get('lifecycle') or {}).get('state')!r}, not 'active'"
        )
    return {
        "selectionId": active["selectionId"],
        "activeRecordId": active["lifecycle"]["recordId"],
        "scope": active["scope"],
        "publicationSemanticFingerprint": active["publication"][
            "publicationSemanticFingerprint"
        ],
        "sourceSnapshotId": active["publication"]["sourceSnapshotId"],
        "objectCount": active["publication"]["objectCount"],
        "capabilityReadiness": active["readiness"]["capabilityReadiness"],
        "capabilitySufficiency": active["readiness"]["capabilitySufficiency"],
        "lifecycleRecords": sorted(
            path.name for path in SELECTION_ROOT.glob("*.json")
        ),
    }


def _parity_amendment() -> dict[str, Any]:
    import yaml

    contract = yaml.safe_load(PARITY_CONTRACT.read_text(encoding="utf-8"))
    amendment = next(
        entry
        for entry in contract["amendments"]
        if entry["amendmentId"] == "P4-0P-A1"
    )
    return {
        "amendmentId": amendment["amendmentId"],
        "decisionAmendment": amendment["decisionAmendment"],
        "frozenBehavior": amendment["frozenBehavior"],
        "approval": amendment["approval"],
        # as_posix for the same reason as bundlePath: a committed logical path
        # must not carry the separator of whichever host wrote it.
        "amendedContractPath": PARITY_CONTRACT.relative_to(REPO_ROOT).as_posix(),
        "amendedContractSha256": _sha256(PARITY_CONTRACT),
        "resolvedDecisionQuestions": sorted(
            contract["reviewGate"]["resolvedDecision"],
            key=lambda key: int(key[1:]),
        ),
    }


#: The decision states `P4-0` is required to assert, each with what remains. A
#: decision recorded as simply "decided" hides whether its implementation is
#: complete, which is how #92 came to be described as done while the served
#: aggregates were still wrong.
DECISION_STATES = {
    "85": {
        "state": "decided_hard_and_active",
        "gateMode": "hard",
        "boundary": "acceptance-v5 / verifier-v5",
        "remaining": None,
    },
    "86": {
        "state": "decided_and_enforced_in_publication",
        "remaining": None,
    },
    "87": {
        "state": "closed_both_candidates_rejected",
        "candidates": {"C6": "rejected", "C7": "rejected"},
        "remaining": None,
        "note": (
            "Historical evidence only. C6's grid may not be extended, C7 may not "
            "be refit on confirmation origins, and neither may return under a new "
            "label."
        ),
    },
    "88": {"state": "decided_option_a_implemented", "remaining": "P4-2 verification"},
    "89": {
        "state": "decided_and_implemented",
        "remaining": "P4-2 implementation/adoption verification",
    },
    "90": {
        "state": "decided_option_a_implemented",
        "remaining": None,
        "closedAtP40": (
            "Go now counts the entire active_forecast_versions projection at "
            "startup and per request before applying the configured fingerprint. "
            "A competing authority under a different legacy scope hash can no "
            "longer read as healthy."
        ),
    },
    "91": {
        "state": "decided_c8_rejected_as_full_range_remedy",
        "coldStartCoverage": 0.8063,
        "floor": 0.85,
        "remaining": "P4-1 must retain executable C8 rejection evidence",
        "note": "C8 is not the H1-H4 serving producer. The accepted C5 interval is.",
    },
    "92": {
        "state": "decided_served_field_withholding_live_contract_incomplete",
        "remaining": "P4-1",
    },
    "93": {
        "state": "decided_reconciled_at_p4_0",
        "remaining": None,
    },
}

#: `P4-0` task 10. Attested evidence stays labelled attested. Calling it
#: locally_verified without a retained execution artifact is the overclaim the
#: plan explicitly forbids.
OPEN_EVIDENCE_CLASSIFICATION = {
    "windowsPortability": {
        "classification": "user_attested",
        "artifactRetained": False,
        "host": "macOS only on this host",
    },
    "linuxPortability": {
        "classification": "user_attested",
        "artifactRetained": False,
        "host": "macOS only on this host",
    },
    "trackA": {"classification": "user_attested", "artifactRetained": False},
    "safePerformanceBenchmark": {
        "classification": "locally_verified",
        "artifactRetained": True,
        "artifact": "contracts/evidence/profile-invariance-record.json",
    },
    "visualApproval": {
        "classification": "user_attested",
        "artifactRetained": False,
        "note": (
            "The P4-0P confidence-cell amendment adds a NEW outstanding visual "
            "review that no prior attestation covers."
        ),
    },
}

#: The as-built ordering disposition `P4-0` must record explicitly. `P4-D0` asked
#: the reviewer to choose an ordering; the implementation already chose it by
#: publishing the bounded run on the current pin.
P4_D0_DISPOSITION = {
    "state": "resolved_by_as_built_ordering",
    "resolution": (
        "The bounded decision-#92 publication and migration 0008 already ran on "
        "the current pin, so no pre-start ordering decision remains. Source-only "
        "P4-2/P4-3 work may follow P4-0; exactly one final-pin P4-1 publication "
        "remains after the P4-0P approval."
    ),
    "sourceOnlyForbids": [
        "reading P50/P90 artifacts in Phase 4 code",
        "calculating safety stock, reorder, replay or policy results",
        "publishing a Phase 4 run",
        "materializing or serving a Phase 4 number",
        "presenting sample or static values as live",
    ],
}


def build() -> dict[str, Any]:
    live = _one(
        "SELECT forecast_run_id||'|'||version_id||'|'"
        "||run_semantic_fingerprint||'|'||publication_semantic_fingerprint||'|'"
        "||activation_scope_fingerprint "
        "FROM retail_serving.active_forecast_versions"
    )
    run_id, version_id, run_fingerprint, publication, scope = live
    authority_count = int(
        _one("SELECT count(*) FROM retail_serving.active_forecast_versions")[0]
    )
    if authority_count != 1:
        raise SystemExit(
            f"decision #90 requires exactly one active authority, found "
            f"{authority_count}"
        )
    migration = _one(
        "SELECT version_num FROM retail_intelligence_alembic_version"
    )[0]

    closure = json.loads(
        (REPO_ROOT / "contracts" / "evidence" / "forecast-closure-record.json").read_text(
            encoding="utf-8"
        )
    )
    if closure["servingMigration"] != migration:
        raise SystemExit(
            "the closure record and the applied migration disagree; regenerate "
            "the closure record before the entry record"
        )
    if closure["acceptedRun"]["forecastRunId"] != run_id:
        raise SystemExit("the closure record does not describe the active run")

    manifest = json.loads(
        (REPO_ROOT / closure["bundlePath"] / "forecast-run-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    selection = _selection()
    if selection["publicationSemanticFingerprint"] != publication:
        raise SystemExit(
            "the active selection names a different publication than the active "
            "forecast serves"
        )

    return {
        "schemaVersion": "retail-inventory-replenishment-entry-record/v1",
        "recordType": "generated_capability_entry_record",
        "generatedBy": "tools/build_inventory_entry_record.py",
        "note": (
            "Generated, never hand-edited. Regenerate with: "
            "tools/dev.py inventory-entry-record"
        ),
        "package": "P4-0",
        "entryAuthorized": True,
        "forecastAuthority": {
            "forecastRunId": run_id,
            "versionId": version_id,
            "runSemanticFingerprint": run_fingerprint,
            "publicationSemanticFingerprint": publication,
            "activationScopeFingerprint": scope,
            "activeAuthorityCount": authority_count,
            "featureSemanticFingerprint": manifest["inputBundle"].get(
                "featureSemanticFingerprint"
            )
            or manifest.get("featureSemanticFingerprint"),
            "lifecycleStatus": manifest.get("lifecycleStatus"),
            "bundlePath": closure["bundlePath"],
        },
        "servingMigration": migration,
        "measured": _measure_serving(version_id, run_id),
        "authorityLedger": {
            "currentEventId": closure["authorityLedger"]["currentEventId"],
            "currentPriorEventId": closure["authorityLedger"]["currentPriorEventId"],
            "nullPredecessorEventIds": closure["authorityLedger"][
                "nullPredecessorEventIds"
            ],
            "supersededIdentityCount": len(closure["supersededIdentities"]),
            "identitiesWithoutRetainedBytes": [
                entry["forecastRunId"]
                for entry in closure["supersededIdentities"]
                if not entry["bundleBytesRetained"]
            ],
        },
        "sourceSelection": selection,
        "parityAmendment": _parity_amendment(),
        "decisionStates": DECISION_STATES,
        "openEvidenceClassification": OPEN_EVIDENCE_CLASSIFICATION,
        "p4d0Disposition": P4_D0_DISPOSITION,
        "decision92Residue": closure["decision92Residue"],
        "intervalConsumersEnabled": False,
        "intervalConsumerGate": (
            "No Phase 4 engine, replay, policy score, API value or UI value may "
            "consume yhat_p90 until the final-pin P4-1 pass completes."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    record = build()
    if args.check:
        if not RECORD.is_file():
            print("inventory entry record is absent", file=sys.stderr)
            return 1
        if json.loads(RECORD.read_text(encoding="utf-8")) != record:
            print("inventory entry record drifted from live evidence", file=sys.stderr)
            return 1
        print("inventory entry record matches live evidence")
        return 0
    RECORD.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(
        f"wrote {RECORD.relative_to(REPO_ROOT)}\n"
        f"  authority: {record['forecastAuthority']['forecastRunId']} / "
        f"{record['forecastAuthority']['versionId']}\n"
        f"  selection: {record['sourceSelection']['selectionId']}\n"
        f"  migration: {record['servingMigration']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
