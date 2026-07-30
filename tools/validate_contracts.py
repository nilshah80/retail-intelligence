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
    if driver_semantics.get("schemaVersion") != "retail-ml-driver-semantics/v1":
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
    screen_contracts = [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(screen_root.glob("*.yaml"))
    ]
    screen_ids = [contract.get("screenId") for contract in screen_contracts]
    if (
        any(
            contract.get("schemaVersion") != "retail-screen-contract/v1"
            for contract in screen_contracts
        )
        or len(screen_ids) != len(set(screen_ids))
    ):
        raise ValueError("invalid or duplicate screen contract")
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
            "503": {"$ref": "#/components/responses/ForecastUnavailable"},
        }:
            raise ValueError(
                f"{path} must declare both the live projection and fail-closed states"
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
                "apiContract": {
                    "version": openapi["info"]["version"],
                    "forecastRoutes": len(FORECAST_API_PATHS),
                    "forecastState": "live_or_fail_closed",
                },
                "validationPolicy": {
                    "mode": validation_policy["validation"]["mode"],
                    "repositoryCI": "prohibited",
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
