from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI = REPO_ROOT / "contracts/api/openapi.yaml"
FORECAST_PATHS = (
    "/api/v1/forecast/versions",
    "/api/v1/forecast/summary",
    "/api/v1/forecast/series",
    "/api/v1/forecast/actuals",
    "/api/v1/forecast/horizons",
    "/api/v1/forecast/stores",
    "/api/v1/forecast/drivers",
    "/api/v1/forecast/signals",
    "/api/v1/forecast/exceptions",
)
PRICING_READ_PATHS = (
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
)
PRICING_DETAIL_PATHS = (
    "/api/v1/pricing/recommendations/{id}",
    "/api/v1/competitors/matches/{id}",
)


def test_forecast_routes_have_live_stale_and_fail_closed_contracts() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))

    assert contract["info"]["version"] == "0.6.0"
    for path in FORECAST_PATHS:
        responses = contract["paths"][path]["get"]["responses"]
        assert set(responses) == {"200", "409", "503"}
        assert responses["200"] == {
            "$ref": "#/components/responses/ForecastLive"
        }
        assert responses["409"] == {
            "$ref": "#/components/responses/ForecastStale"
        }
        assert responses["503"] == {
            "$ref": "#/components/responses/ForecastUnavailable"
        }


def test_unavailable_forecast_never_requires_a_fake_identity() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    schema = contract["components"]["schemas"]["ForecastUnavailable"]

    assert schema["properties"]["dataMode"]["const"] == "unavailable"
    for field in ("versionId", "forecastRunId", "semanticFingerprint"):
        assert schema["properties"][field]["type"] == ["string", "null"]
    assert {
        "FORECAST_ARTIFACT_INVALID",
        "FORECAST_LINEAGE_MISMATCH",
        "FORECAST_READ_MODEL_UNAVAILABLE",
    } == set(schema["properties"]["reasonCode"]["enum"])


def test_pricing_routes_freeze_live_stale_missing_and_refusal_states() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    expected = {
        "200": {"$ref": "#/components/responses/PricingLive"},
        "409": {"$ref": "#/components/responses/PricingStale"},
        "503": {"$ref": "#/components/responses/PricingUnavailable"},
    }
    for path in PRICING_READ_PATHS:
        assert contract["paths"][path]["get"]["responses"] == expected
    for path in PRICING_DETAIL_PATHS:
        assert contract["paths"][path]["get"]["responses"] == {
            **expected,
            "404": {"$ref": "#/components/responses/PricingUnavailable"},
        }
    assert set(
        contract["paths"]["/api/v1/pricing/simulations:run"]["post"][
            "responses"
        ]
    ) == {"200", "400", "409", "413", "415", "422", "503"}
    assert contract["paths"]["/api/v1/promotions/simulations:run"]["post"][
        "responses"
    ] == {"422": {"$ref": "#/components/responses/PricingValidationInvalid"}}


def test_scenario_bootstrap_pins_forecast_and_fails_closed() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    operation = contract["paths"]["/api/v1/forecast/scenario/context"]["get"]
    assert set(operation["responses"]) == {"200", "400", "409", "503"}
    expected = operation["parameters"][0]
    assert expected["name"] == "expectedForecastVersion"
    assert expected["required"] is True
    bootstrap = contract["components"]["schemas"]["ScenarioContextBootstrap"]
    assert bootstrap["additionalProperties"] is False
    assert set(bootstrap["required"]) == {
        "schemaVersion",
        "forecastVersion",
        "scenarioContextVersion",
        "inventory",
        "scenarioDecisionAsOf",
    }
    unavailable = contract["components"]["schemas"]["ScenarioUnavailable"]
    assert "SCENARIO_BASE_CONTEXT_AMBIGUOUS" in unavailable["properties"][
        "reasonCode"
    ]["enum"]


def test_scenario_post_is_tuple_pinned_stateless_and_explicit() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))
    operation = contract["paths"]["/api/v1/forecast/scenario"]["post"]
    assert set(operation["responses"]) == {
        "200",
        "400",
        "409",
        "413",
        "415",
        "422",
        "503",
    }
    body = operation["requestBody"]
    assert body["required"] is True
    assert set(body["content"]) == {"application/json"}
    request = contract["components"]["schemas"]["ScenarioRunRequest"]
    assert request["additionalProperties"] is False
    assert set(request["required"]) == {
        "presetId",
        "userOverrides",
        "businessScope",
        "expectedAuthority",
    }
    overrides = contract["components"]["schemas"]["ScenarioUserOverrides"]
    assert overrides["additionalProperties"] is False
    assert "atpAdjustment" not in overrides["properties"]
    response = contract["components"]["schemas"]["ScenarioRunResponse"]
    assert response["properties"]["dataMode"]["const"] == "assumption_projection"
    calculation = contract["components"]["schemas"]["ScenarioCalculation"]
    assert {
        "reportingRevenuePotential",
        "reportingRequiredInventoryValue",
        "appliedPriceSummaries",
        "demandWeightedSeriesStockoutRiskPct",
    } <= set(calculation["required"])
