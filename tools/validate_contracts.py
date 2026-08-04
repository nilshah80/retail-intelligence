#!/usr/bin/env python3
"""Validate every machine-readable repository contract."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from retail_contracts.entities import validate_contract_tree
from retail_contracts.fingerprint import semantic_fingerprint

REPO_ROOT = Path(__file__).resolve().parent.parent
INVENTORY_API_PATHS = {
    "/api/v1/inventory/versions",
    "/api/v1/inventory/overview",
    "/api/v1/inventory/stores",
    "/api/v1/inventory/warehouses",
    "/api/v1/inventory/ageing",
    "/api/v1/inventory/transfers",
    "/api/v1/inventory/valuation",
    "/api/v1/inventory/expiry-waste",
    "/api/v1/inventory/stock-health",
    "/api/v1/replenishment/planner",
    "/api/v1/replenishment/orders",
    "/api/v1/replenishment/suppliers",
    "/api/v1/replenishment/safety-stock",
    "/api/v1/replenishment/allocations",
    "/api/v1/replenishment/exceptions",
}
FORECAST_API_PATHS = {
    "/api/v1/forecast/versions",
    "/api/v1/forecast/summary",
    "/api/v1/forecast/series",
    "/api/v1/forecast/actuals",
    "/api/v1/forecast/horizons",
    "/api/v1/forecast/stores",
    "/api/v1/forecast/drivers",
    "/api/v1/forecast/signals",
    "/api/v1/forecast/exceptions",
}


def _validate_publication_selections() -> dict[str, object]:
    """Validate every committed decision-#73 selection against its own schema.

    Also enforces the two invariants the schema alone cannot express: the three
    lifecycle records share one `selectionId` while chaining distinct `recordId`s,
    and exactly one record per scope is active.
    """

    selection_root = REPO_ROOT / "contracts" / "evidence" / "publication-selections"
    if not selection_root.is_dir():
        raise ValueError(
            "no decision-#73 publication selection exists; a source pin cannot "
            "be forecast authority without a governed selection"
        )
    schema = json.loads(
        (
            REPO_ROOT / "contracts" / "onboarding" / "publication-selection.schema.json"
        ).read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    selections: list[dict] = []
    predecessors: list[dict] = []
    for path in sorted(selection_root.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schemaVersion") == "retail-publication-selection-predecessor/v1":
            predecessors.append(record)
            continue
        validator.validate(record)
        selections.append(record)

    if not selections:
        raise ValueError("publication-selections contains no selection record")

    by_scope: dict[tuple, list[dict]] = {}
    for record in selections:
        scope = record["scope"]
        key = (
            scope["retailerId"],
            scope["tenantId"],
            scope["capability"],
            scope["environment"],
        )
        by_scope.setdefault(key, []).append(record)

    # Currency is derived from the supersedes edges, never from filenames or
    # order. A re-pinned scope legitimately holds two chains -- the retired one
    # ending at `superseded`, the new one at `active` -- and both keep a record
    # whose state reads `active`, because history is appended rather than edited.
    # Resolving that by position would be the arbitrary tie-break decision #90 was
    # written against, so the invariant is stated over LIVE chain heads.
    terminal_states = {"superseded", "rejected"}
    superseded_ids = {
        record["lifecycle"]["supersedes"]
        for record in selections
        if record["lifecycle"].get("supersedes")
    }
    live_scopes: dict[tuple, str] = {}
    for key, group in by_scope.items():
        record_ids = [record["lifecycle"]["recordId"] for record in group]
        if len(set(record_ids)) != len(record_ids):
            raise ValueError(f"scope {'/'.join(key)} reuses a lifecycle recordId")
        heads = [
            record
            for record in group
            if record["lifecycle"]["recordId"] not in superseded_ids
        ]
        live = [
            record
            for record in heads
            if record["lifecycle"]["state"] not in terminal_states
        ]
        if len(live) != 1:
            raise ValueError(
                f"scope {'/'.join(key)} has {len(live)} live selections: "
                f"{sorted(record['selectionId'] for record in live)}; exactly one "
                "is required"
            )
        state = live[0]["lifecycle"]["state"]
        if state != "active":
            raise ValueError(
                f"scope {'/'.join(key)} resolves to a {state} selection, which "
                "serves nothing"
            )
        live_scopes[key] = str(live[0]["selectionId"])
        # Every chain in this scope must be complete: an approval event that never
        # reached `active` is a selection nobody finished making.
        for selection_id in {record["selectionId"] for record in group}:
            chain_states = {
                record["lifecycle"]["state"]
                for record in group
                if record["selectionId"] == selection_id
            }
            missing = {"candidate", "approved", "active"} - chain_states
            if missing:
                raise ValueError(
                    f"selection {selection_id} is missing lifecycle records "
                    f"{sorted(missing)}"
                )

    unknown = {
        record["lifecycle"]["state"] for record in selections
    } - ({"candidate", "approved", "active"} | terminal_states)
    if unknown:
        raise ValueError(
            f"unclassified lifecycle states {sorted(unknown)}; the currency rule "
            "above cannot decide whether they are live"
        )

    # A legacy predecessor must be disclosed as unselected, never as a
    # supersession chain that never happened.
    for predecessor in predecessors:
        if predecessor.get("selectionRecordExists") is not False:
            raise ValueError(
                "a legacy predecessor disclosure must record "
                "selectionRecordExists: false"
            )

    return {
        "scopes": ["/".join(key) for key in sorted(by_scope)],
        "liveSelections": {
            "/".join(key): selection_id
            for key, selection_id in sorted(live_scopes.items())
        },
        "records": len(selections),
        "legacyPredecessors": len(predecessors),
    }


def main() -> int:
    summary = validate_contract_tree()
    ml_contract_root = REPO_ROOT / "contracts" / "ml"
    input_schema = json.loads(
        (ml_contract_root / "input-bundle.schema.json").read_text(encoding="utf-8")
    )
    expected_pin = json.loads(
        (ml_contract_root / "expected-pin.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator(input_schema).validate(expected_pin)
    forecast_schema = yaml.safe_load(
        (ml_contract_root / "forecast-run.schema.yaml").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(forecast_schema)
    driver_semantics = yaml.safe_load(
        (ml_contract_root / "driver-semantics.yaml").read_text(encoding="utf-8")
    )
    if driver_semantics.get("schemaVersion") != "retail-ml-driver-semantics/v3":
        raise ValueError("unsupported ML driver-semantics schemaVersion")
    classification_policy = json.loads(
        (
            ml_contract_root / "forecast-classification-policy.json"
        ).read_text(encoding="utf-8")
    )
    if (
        classification_policy.get("schemaVersion")
        != "retail-forecast-classification-policy/v1"
        or classification_policy.get("decisionId") != 60
    ):
        raise ValueError("unsupported forecast classification policy")
    for name in ("exceptions", "dataQuality"):
        section = dict(classification_policy[name])
        recorded = section.pop("semanticFingerprint", None)
        if semantic_fingerprint(section, volatile_pointers=()) != recorded:
            raise ValueError(
                f"forecast classification policy {name} fingerprint mismatch"
            )
    validation_policy = yaml.safe_load(
        (REPO_ROOT / "contracts" / "validation-policy.yaml").read_text(
            encoding="utf-8"
        )
    )
    if (
        validation_policy.get("schemaVersion")
        != "retail-validation-policy/v1"
        or validation_policy.get("repositoryCI", {}).get("allowed") is not False
        or validation_policy.get("validation", {}).get("mode")
        != "developer_run"
        or validation_policy.get("validation", {}).get("phaseExitCommand")
        != "tools/dev.py verify"
    ):
        raise ValueError("invalid repository validation policy")
    workflow_root = REPO_ROOT / ".github" / "workflows"
    workflow_files = (
        [*workflow_root.glob("*.yml"), *workflow_root.glob("*.yaml")]
        if workflow_root.exists()
        else []
    )
    if workflow_files:
        raise ValueError("repository CI is prohibited by validation policy")
    screen_root = REPO_ROOT / "contracts" / "screens"
    screen_ids: list[str] = []
    for path in sorted(screen_root.glob("*.yaml")):
        contract = yaml.safe_load(path.read_text(encoding="utf-8"))
        schema_version = contract.get("schemaVersion")
        if schema_version == "retail-screen-contract/v1":
            screen_ids.append(contract.get("screenId"))
        elif schema_version == "retail-screen-contract-set/v1":
            # One document, many destinations. Introduced for the 14
            # inventory/replenishment screens so the directory does not carry
            # fourteen copies of identical shell/behavior boilerplate; each
            # section still freezes its own endpoint, artifacts and elements.
            sections = contract.get("screens")
            if not isinstance(sections, list) or not sections:
                raise ValueError(f"{path.name}: contract set declares no screens")
            screen_ids.extend(section.get("screenId") for section in sections)
        else:
            raise ValueError(f"{path.name}: unknown screen contract schema")
    if len(screen_ids) != len(set(screen_ids)) or None in screen_ids:
        raise ValueError("invalid or duplicate screen contract")
    # `P4-0` tasks 4/5. Decision #73 selections were an unvalidated directory:
    # the lifecycle module existed, the schema existed, and nothing checked that
    # a committed record satisfied either. An unchecked governance record reads
    # as authority while being whatever someone last typed.
    selection_summary = _validate_publication_selections()
    openapi = yaml.safe_load(
        (REPO_ROOT / "contracts" / "api" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    if openapi.get("openapi") != "3.1.0":
        raise ValueError("unsupported OpenAPI contract version")
    if not FORECAST_API_PATHS <= set(openapi.get("paths", {})):
        raise ValueError("OpenAPI contract is missing a Phase 3 forecast route")
    for path in FORECAST_API_PATHS:
        responses = openapi["paths"][path]["get"]["responses"]
        if responses != {
            "200": {"$ref": "#/components/responses/ForecastLive"},
            "409": {"$ref": "#/components/responses/ForecastStale"},
            "503": {"$ref": "#/components/responses/ForecastUnavailable"},
        }:
            raise ValueError(
                f"{path} must declare live, stale, and unavailable states"
            )
    # P4-4: the version endpoint plus one route per screen, every one of them
    # carrying the same governed live/stale/unavailable triple as forecast.
    if not INVENTORY_API_PATHS <= set(openapi.get("paths", {})):
        missing = sorted(INVENTORY_API_PATHS - set(openapi.get("paths", {})))
        raise ValueError(f"OpenAPI contract is missing inventory routes: {missing}")
    for path in INVENTORY_API_PATHS:
        responses = openapi["paths"][path]["get"]["responses"]
        if responses != {
            "200": {"$ref": "#/components/responses/InventoryLive"},
            "409": {"$ref": "#/components/responses/InventoryStale"},
            "503": {"$ref": "#/components/responses/InventoryUnavailable"},
        }:
            raise ValueError(
                f"{path} must declare live, stale, and unavailable states"
            )
    print(
        json.dumps(
            {
                "status": "valid",
                **summary,
                "mlContracts": {
                    "expectedPin": expected_pin["schemaVersion"],
                    "forecastRun": forecast_schema["properties"]["schemaVersion"]["const"],
                    "driverSemantics": driver_semantics["schemaVersion"],
                    "classificationPolicy": classification_policy["schemaVersion"],
                },
                "screenContracts": screen_ids,
                "publicationSelections": selection_summary,
                "apiContract": {
                    "version": openapi["info"]["version"],
                    "forecastRoutes": len(FORECAST_API_PATHS),
                    "inventoryRoutes": len(INVENTORY_API_PATHS),
                    "forecastState": "live_stale_or_fail_closed",
                },
                "validationPolicy": {
                    "mode": validation_policy["validation"]["mode"],
                    "phaseExitCommand": validation_policy["validation"][
                        "phaseExitCommand"
                    ],
                    "repositoryCI": "prohibited",
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
