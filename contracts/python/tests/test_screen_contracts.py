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
    # Q19 was added at the `P4-0P` gate. The range is inclusive of it rather than
    # open-ended: a new question must amend this test deliberately, which is the
    # point of freezing an enumeration.
    assert set(contract["reviewGate"]["resolvedDecision"]) == {
        *(f"Q{number}" for number in range(1, 20)),
    }


def test_the_activation_block_matches_the_forecast_that_actually_serves() -> None:
    """This block asserted `no_accepted_forecast` while one was live and serving.

    It was written during the Phase 3 NO-GO and never moved when the run was
    accepted, so the screen contract denied the version it renders. Same class of
    stale evidence as the closure record's 0007 migration pin: nothing failed,
    because the test asserted the staleness.
    """

    activation = _forecast()["activation"]
    assert activation["currentState"] == "accepted_forecast_active"
    assert activation["forecastRunId"] == "fr_357575f586905b11"
    assert activation["versionId"] == "fv_3d66e3bd9939430d"
    assert activation["semanticFingerprint"] is not None
    assert activation["acceptanceSchemaVersion"] == "retail-forecast-acceptance/v5"
    assert activation["coverageGateMode"] == "hard"
    assert activation["servingMigration"] == "0008_nullable_withheld_interval"
    # The rejected historical candidate stays disclosed; acceptance of a later run
    # does not erase the rejection that preceded it.
    assert activation["rejectedHistoricalRunId"] == "fr_92135aa7b5215b69"


def test_the_interval_availability_block_matches_decision_92() -> None:
    interval = _forecast()["activation"]["intervalAvailability"]
    assert interval["policyId"] == "retail-forecast-interval-availability/v1"
    assert interval["calibratedMaxHorizon"] == 4
    assert interval["withheldRows"] == 8756
    assert interval["withheldSeries"] == 398
    assert interval["reasonCode"] == "COLD_START_INTERVAL_UNCALIBRATED"


def test_the_p4_0p_amendment_is_recorded_with_both_frozen_behaviors() -> None:
    """`P4-1` may not implement the repair before both behaviors are frozen here."""

    amendments = _forecast()["amendments"]
    amendment = next(
        entry for entry in amendments if entry["amendmentId"] == "P4-0P-A1"
    )
    assert amendment["package"] == "P4-0P"
    assert 64 in amendment["decisionIds"], (
        "the amendment must name the decision that froze the semantics it changes"
    )
    assert amendment["decisionAmendment"] == "Decision #64 Q19"
    frozen = amendment["frozenBehavior"]
    assert frozen["confidence"] == "unavailable_when_mixed"
    assert frozen["intervalTotal"] == "absent_with_governed_reason_when_mixed"
    assert amendment["approval"]["status"] == "approved"


def test_the_amendment_approval_does_not_overclaim_human_review() -> None:
    """An autonomous approval must not be recorded as independent human review.

    The distinction is the whole value of the record. Labelling a self-issued
    approval as a human sign-off would make the outstanding review invisible,
    which is the failure mode every other evidence record here guards against.
    """

    amendment = next(
        entry
        for entry in _forecast()["amendments"]
        if entry["amendmentId"] == "P4-0P-A1"
    )
    approval = amendment["approval"]
    assert (
        approval["classification"]
        == "autonomous_authorization_not_independent_human_review"
    )
    assert approval["reviewOutstanding"], (
        "the outstanding per-screen visual review must stay recorded"
    )


def test_the_confidence_cell_freezes_its_interval_scope() -> None:
    contract = _forecast()
    sku_panel = next(
        panel for panel in contract["panels"] if panel["label"] == "SKU View"
    )
    workbench = next(
        element
        for element in sku_panel["elements"]
        if element["selector"] == "#forecastWorkbenchTable"
    )
    confidence = next(
        column for column in workbench["columns"] if column["label"] == "Confidence"
    )
    scope = confidence["intervalScope"]
    assert scope["rule"] == (
        "unavailable_when_window_mixes_published_and_withheld_intervals"
    )
    assert scope["mixedWindowPresentation"] == "Not available"
    assert scope["mixedWindowReasonCode"] == "COLD_START_INTERVAL_UNCALIBRATED"
    # The horizon selections the screen offers are 4/8/13/26 and withholding
    # starts at h5, so exactly one selection is clean.
    assert scope["cleanSelections"] == [4]
    assert scope["mixedSelections"] == [8, 13, 26]


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
