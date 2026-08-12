#!/usr/bin/env python3
"""Validate every machine-readable repository contract."""

from __future__ import annotations

import hashlib
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
PRICING_STANDARD_READ_PATHS = {
    "/api/v1/pricing/recommendations/summary",
    "/api/v1/pricing/recommendations",
    "/api/v1/pricing/recommendations/store-view",
    "/api/v1/pricing/recommendations/category-view",
    "/api/v1/pricing/recommendations/governance",
    "/api/v1/competitors/summary",
    "/api/v1/competitors/matches",
    "/api/v1/competitors/alert-rules",
    "/api/v1/promotions/summary",
    "/api/v1/promotions/opportunities",
    "/api/v1/promotions/portfolio",
    "/api/v1/promotions/calendar",
}
PRICING_DETAIL_PATHS = {
    "/api/v1/pricing/recommendations/{id}",
    "/api/v1/competitors/matches/{id}",
}
PRICING_SPECIAL_PATH_METHODS = {
    "/api/v1/pricing/simulations:run": "post",
    "/api/v1/pricing/export": "get",
    "/api/v1/direct-exports/{exportId}": "get",
    "/api/v1/promotions/simulations:run": "post",
}
PRICING_API_PATHS = (
    PRICING_STANDARD_READ_PATHS
    | PRICING_DETAIL_PATHS
    | set(PRICING_SPECIAL_PATH_METHODS)
)

REQUIRED_CLIENT_DEMO_SURFACES = {
    "modal.data.add-source",
    "modal.data.validation-results",
    "modal.forecast.accept",
    "modal.forecast.adjustment",
    "modal.forecast.compare-versions",
    "modal.forecast.scenario",
    "modal.forecast.scenario-results",
    "modal.forecast.action-center",
    "modal.forecast.store-drilldown",
    "modal.pricing.recommendation-detail",
    "modal.pricing.approve",
    "modal.pricing.send-review",
    "modal.pricing.export",
    "modal.pricing.schedule",
    "modal.pricing.compare-selected",
    "modal.pricing.action-center",
    "modal.pricing.store-drilldown",
    "modal.pricing.simulation-result",
    "modal.competitor.add",
    "modal.competitor.alert-rule",
    "modal.competitor.review-match.default",
    "modal.competitor.review-match.link-different-product-state",
    "structural.competitor.add-duplicate",
    "structural.competitor.alert-duplicate",
    "modal.promotion.create",
    "modal.promotion.simulate",
    "modal.promotion.simulation-results.unavailable-preview",
    "modal.promotion.calendar",
    "modal.stock-health.assign-owner.preview",
    "modal.stock-health.create-action.preview",
    "state.pricing.rich-active",
    "state.pricing.sparse-diagnostic",
    "state.pricing.exact-zero",
    "state.pricing.filtered-empty",
    "state.pricing.loading",
    "state.pricing.partial",
    "state.pricing.stale",
    "state.pricing.missing",
    "state.pricing.corrupt",
    "state.pricing.panel-failure",
}


def _validate_client_demo_capture_manifest(
    screen_ids: list[str],
) -> dict[str, object]:
    schema_path = (
        REPO_ROOT
        / "contracts/screens/client-demo-surface-state-capture-manifest.schema.json"
    )
    manifest_path = (
        REPO_ROOT
        / "contracts/evidence/client-demo-surface-state-capture-manifest.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(manifest)

    surfaces = manifest["surfaces"]
    surface_ids = [surface["surfaceId"] for surface in surfaces]
    test_ids = [surface["testId"] for surface in surfaces]
    capture_ids = [
        surface["captureId"]
        for surface in surfaces
        if surface["captureId"] is not None
    ]
    for label, values in (
        ("surfaceId", surface_ids),
        ("testId", test_ids),
        ("captureId", capture_ids),
    ):
        if len(values) != len(set(values)):
            raise ValueError(f"client-demo capture manifest reuses a {label}")

    page_surfaces = [surface for surface in surfaces if surface["kind"] == "page"]
    page_ids = [surface["pageId"] for surface in page_surfaces]
    if set(page_ids) != set(screen_ids) or len(page_ids) != len(screen_ids):
        raise ValueError(
            "client-demo capture manifest must contain exactly one page surface "
            "for every screen contract"
        )
    missing_surfaces = sorted(REQUIRED_CLIENT_DEMO_SURFACES - set(surface_ids))
    if missing_surfaces:
        raise ValueError(
            "client-demo capture manifest lacks mandatory surfaces: "
            + ", ".join(missing_surfaces)
        )

    original = manifest["originalHtml"]
    original_path = (REPO_ROOT / original["path"]).resolve()
    if REPO_ROOT not in original_path.parents or not original_path.is_file():
        raise ValueError("client-demo original HTML path is outside the repository or absent")
    if hashlib.sha256(original_path.read_bytes()).hexdigest() != original["sha256"]:
        raise ValueError("client-demo original HTML hash drifted")

    pending = 0
    failed = 0
    captured = 0
    keyboard_pending = 0
    keyboard_failed = 0
    for surface in surfaces:
        for viewport in ("desktop", "mobile"):
            evidence = surface[viewport]
            status = evidence["status"]
            path = evidence["path"]
            digest = evidence["sha256"]
            if status == "captured":
                if not path or not digest:
                    raise ValueError(
                        f"{surface['surfaceId']} {viewport} capture lacks path/hash"
                    )
                evidence_path = (REPO_ROOT / path).resolve()
                if REPO_ROOT not in evidence_path.parents or not evidence_path.is_file():
                    raise ValueError(
                        f"{surface['surfaceId']} {viewport} capture is absent"
                    )
                if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != digest:
                    raise ValueError(
                        f"{surface['surfaceId']} {viewport} capture hash drifted"
                    )
                captured += 1
            elif status in {"pending", "not_applicable"}:
                if path is not None or digest is not None:
                    raise ValueError(
                        f"{surface['surfaceId']} {viewport} {status} evidence must be null"
                    )
                pending += int(status == "pending")
            else:
                failed += 1

        keyboard_status = surface["keyboardStatus"]
        keyboard_pending += int(keyboard_status == "pending")
        keyboard_failed += int(keyboard_status == "failed")

    review = manifest["review"]
    if review["automatedStatus"] == "passed" and (
        pending or failed or keyboard_pending or keyboard_failed
    ):
        raise ValueError(
            "client-demo automated review cannot pass with pending/failed "
            "captures or keyboard checks"
        )
    human_status = review["humanStatus"]
    reviewed_by = review.get("reviewedBy")
    reviewed_at = review.get("reviewedAt")
    if human_status == "pending_user_review" and (
        reviewed_by is not None or reviewed_at is not None
    ):
        raise ValueError(
            "pending client-demo human review cannot name a reviewer or review time"
        )
    if human_status in {"approved", "changes_requested"} and (
        not reviewed_by or not reviewed_at
    ):
        raise ValueError(
            "completed client-demo human review requires reviewer and review time"
        )
    return {
        "surfaces": len(surfaces),
        "pageSurfaces": len(page_surfaces),
        "capturedViewports": captured,
        "pendingViewports": pending,
        "pendingKeyboardChecks": keyboard_pending,
        "automatedStatus": review["automatedStatus"],
        "humanStatus": review["humanStatus"],
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
    schema_paths = {
        "retail-publication-selection/v1": (
            REPO_ROOT
            / "contracts/onboarding/publication-selection.schema.json"
        ),
        "retail-publication-selection/v2": (
            REPO_ROOT
            / "contracts/onboarding/publication-selection-v2.schema.json"
        ),
    }
    validators: dict[str, Draft202012Validator] = {}
    for version, schema_path in schema_paths.items():
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validators[version] = Draft202012Validator(schema)

    selections: list[dict] = []
    predecessors: list[dict] = []
    for path in sorted(selection_root.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("schemaVersion") == "retail-publication-selection-predecessor/v1":
            predecessors.append(record)
            continue
        version = str(record.get("schemaVersion") or "")
        validator = validators.get(version)
        if validator is None:
            raise ValueError(
                f"unsupported publication-selection schemaVersion in {path}: {version}"
            )
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
    json_schema_paths = sorted((REPO_ROOT / "contracts").rglob("*.schema.json"))
    for schema_path in json_schema_paths:
        Draft202012Validator.check_schema(
            json.loads(schema_path.read_text(encoding="utf-8"))
        )
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
    capture_summary = _validate_client_demo_capture_manifest(screen_ids)
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
    if not PRICING_API_PATHS <= set(openapi.get("paths", {})):
        missing = sorted(PRICING_API_PATHS - set(openapi.get("paths", {})))
        raise ValueError(f"OpenAPI contract is missing pricing routes: {missing}")
    pricing_read_responses = {
        "200": {"$ref": "#/components/responses/PricingLive"},
        "409": {"$ref": "#/components/responses/PricingStale"},
        "503": {"$ref": "#/components/responses/PricingUnavailable"},
    }
    for path in PRICING_STANDARD_READ_PATHS:
        if openapi["paths"][path]["get"]["responses"] != pricing_read_responses:
            raise ValueError(
                f"{path} must declare pricing live, stale, and unavailable states"
            )
    pricing_detail_responses = {
        **pricing_read_responses,
        "404": {"$ref": "#/components/responses/PricingUnavailable"},
    }
    for path in PRICING_DETAIL_PATHS:
        if openapi["paths"][path]["get"]["responses"] != pricing_detail_responses:
            raise ValueError(
                f"{path} must also declare a typed missing-detail state"
            )
    special_response_codes = {
        "/api/v1/pricing/simulations:run": {
            "200", "400", "409", "413", "415", "422", "503"
        },
        "/api/v1/pricing/export": {"200", "409", "422", "503"},
        "/api/v1/direct-exports/{exportId}": {
            "200", "404", "409", "422", "503"
        },
        "/api/v1/promotions/simulations:run": {"422"},
    }
    for path, method in PRICING_SPECIAL_PATH_METHODS.items():
        responses = openapi["paths"][path][method]["responses"]
        if set(responses) != special_response_codes[path]:
            raise ValueError(
                f"{path} response states drifted: {sorted(responses)}"
            )
    expected_special_refs = {
        ("/api/v1/pricing/simulations:run", "400"): "RequestInvalid",
        ("/api/v1/pricing/simulations:run", "409"): "PricingStale",
        ("/api/v1/pricing/simulations:run", "413"): "RequestTooLarge",
        ("/api/v1/pricing/simulations:run", "415"): "UnsupportedMediaType",
        ("/api/v1/pricing/simulations:run", "422"): "PricingValidationInvalid",
        ("/api/v1/pricing/simulations:run", "503"): "PricingUnavailable",
        ("/api/v1/pricing/export", "409"): "PricingStale",
        ("/api/v1/pricing/export", "422"): "PricingValidationInvalid",
        ("/api/v1/pricing/export", "503"): "PricingUnavailable",
        ("/api/v1/direct-exports/{exportId}", "404"): "PricingUnavailable",
        ("/api/v1/direct-exports/{exportId}", "409"): "PricingStale",
        ("/api/v1/direct-exports/{exportId}", "422"): "PricingValidationInvalid",
        ("/api/v1/direct-exports/{exportId}", "503"): "PricingUnavailable",
        ("/api/v1/promotions/simulations:run", "422"): "PricingValidationInvalid",
    }
    for (path, status), response_name in expected_special_refs.items():
        method = PRICING_SPECIAL_PATH_METHODS[path]
        expected_ref = {"$ref": f"#/components/responses/{response_name}"}
        if openapi["paths"][path][method]["responses"][status] != expected_ref:
            raise ValueError(
                f"{path} {status} must reference {response_name}"
            )
    print(
        json.dumps(
            {
                "status": "valid",
                **summary,
                "contractJsonSchemas": len(json_schema_paths),
                "mlContracts": {
                    "expectedPin": expected_pin["schemaVersion"],
                    "forecastRun": forecast_schema["properties"]["schemaVersion"]["const"],
                    "driverSemantics": driver_semantics["schemaVersion"],
                    "classificationPolicy": classification_policy["schemaVersion"],
                },
                "screenContracts": screen_ids,
                "clientDemoCaptures": capture_summary,
                "publicationSelections": selection_summary,
                "apiContract": {
                    "version": openapi["info"]["version"],
                    "forecastRoutes": len(FORECAST_API_PATHS),
                    "inventoryRoutes": len(INVENTORY_API_PATHS),
                    "pricingRoutes": len(PRICING_API_PATHS),
                    "forecastState": "live_stale_or_fail_closed",
                    "pricingState": "live_stale_missing_or_fail_closed",
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
