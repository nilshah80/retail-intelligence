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


def test_forecast_routes_have_live_stale_and_fail_closed_contracts() -> None:
    contract = yaml.safe_load(OPENAPI.read_text(encoding="utf-8"))

    assert contract["info"]["version"] == "0.3.1"
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
