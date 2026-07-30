from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[3]
FORECAST_CONTRACT = (
    REPO_ROOT / "contracts/screens/demand-forecast.parity.yaml"
)


def _forecast() -> dict:
    return yaml.safe_load(FORECAST_CONTRACT.read_text(encoding="utf-8"))


def test_demand_forecast_contract_is_frozen_and_authorized() -> None:
    contract = _forecast()
    pending = contract["reviewGate"]["pendingDecisions"]

    assert contract["status"] == "frozen_approved_for_implementation"
    assert contract["reviewGate"]["reactImplementationAuthorized"] is True
    assert pending == {}
    assert set(contract["reviewGate"]["resolvedDecision"]) == {
        *(f"Q{number}" for number in range(1, 19)),
    }
    assert contract["activation"]["currentState"] == "no_accepted_forecast"
    assert contract["activation"]["forecastRunId"] is None
    assert contract["activation"]["versionId"] is None
    assert contract["activation"]["semanticFingerprint"] is None
    assert (
        contract["activation"]["rejectedHistoricalRunId"]
        == "fr_92135aa7b5215b69"
    )


def test_demand_forecast_reference_order_is_machine_readable() -> None:
    contract = _forecast()

    assert [action["label"] for action in contract["actions"]] == [
        "Accept Forecast",
        "Add Planner Adjustment",
        "Compare Versions",
        "Scenario Planning",
        "Forecast Action Center",
        "Export",
    ]
    assert [
        control["selector"] for control in contract["filters"]["controls"]
    ] == [
        "#forecastRegionFilter",
        "#forecastStoreFilter",
        "#forecastCategoryFilter",
        "#forecastHorizonFilter",
        "#forecastGranularityFilter",
        "#forecastSearch",
    ]
    assert [tile["label"] for tile in contract["kpis"]["tiles"]] == [
        "Forecast Accuracy",
        "Forecast Bias",
        "Demand at Risk",
        "Planner Overrides",
        "Forecast Value Add",
    ]
    assert [item["label"] for item in contract["tabs"]["items"]] == [
        "Overview",
        "Store View",
        "SKU View",
        "Demand Drivers",
        "Governance",
    ]


def test_workbench_and_driver_rows_match_the_html_contract() -> None:
    contract = _forecast()
    sku_panel = next(
        panel for panel in contract["panels"] if panel["label"] == "SKU View"
    )
    workbench = next(
        element
        for element in sku_panel["elements"]
        if element["selector"] == "#forecastWorkbenchTable"
    )
    assert [column["label"] for column in workbench["columns"]] == [
        "Select",
        "Priority",
        "SKU / Product",
        "Store",
        "Baseline",
        "AI Forecast",
        "Planner Forecast",
        "Last Actual",
        "Accuracy",
        "Bias",
        "Confidence",
        "Primary Driver",
        "Data Quality",
        "Status",
    ]

    driver_panel = next(
        panel
        for panel in contract["panels"]
        if panel["label"] == "Demand Drivers"
    )
    contribution = driver_panel["elements"][0]
    assert [row["label"] for row in contribution["rows"]] == [
        "Base demand trend",
        "Promotion plan",
        "Seasonality",
        "Price movement",
        "Competitor availability",
        "Weather and local events",
    ]
    assert contribution["rows"][1]["status"] == "unavailable_on_current_pin"
    assert contribution["liveContributionTotal"] == "100.0000"


def test_html_sample_values_are_not_part_of_the_live_contract() -> None:
    text = FORECAST_CONTRACT.read_text(encoding="utf-8")

    for sample in ("87.6%", "₹3.84 Cr", "Phoenix Market City", "5 records"):
        assert sample not in text
