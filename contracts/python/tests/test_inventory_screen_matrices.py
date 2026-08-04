"""The 14 inventory/replenishment screen matrices, and what they may not claim.

`P4-4` tasks 12-16. A matrix is the per-screen authority: every rendered value
must trace to an artifact and endpoint recorded here, every unavailable element
must name its owning decision, and every action control must be disabled without
a mutation path. The tests below assert the claims that would be dangerous if
silently wrong -- not the YAML shapes, which the generator guarantees.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCREEN_ROOT = REPO_ROOT / "contracts" / "screens"

MATRIX_SET = SCREEN_ROOT / "inventory-replenishment.parity.yaml"

RUN_ARTIFACTS = {
    "inventory_positions",
    "stock_health",
    "demand_at_risk",
    "inventory_ageing",
    "inventory_expiry_waste",
    "inventory_valuation",
    "replenishment_recommendations",
    "safety_stock_segments",
    "transfer_recommendations",
    "allocation_recommendations",
    "supplier_planning",
    "replenishment_exceptions",
    "replay_metrics",
}


def _document() -> dict:
    return yaml.safe_load(MATRIX_SET.read_text(encoding="utf-8"))


def _matrices() -> list[dict]:
    return _document()["screens"]


def test_exactly_fourteen_destinations_exist() -> None:
    """Thirteen was the ledger's count; Stock Health is the fourteenth."""

    screens = _matrices()
    assert len(screens) == 14
    assert len({screen["screenId"] for screen in screens}) == 14


def test_every_screen_has_a_live_endpoint_and_known_artifacts() -> None:
    """The artifact -> screen -> endpoint mapping, enforced not narrated."""

    seen_endpoints: set[str] = set()
    for matrix in _matrices():
        read_model = matrix["readModel"]
        endpoint = read_model["endpoint"]
        assert endpoint.startswith("/api/v1/"), endpoint
        assert endpoint not in seen_endpoints, f"{endpoint} serves two screens"
        seen_endpoints.add(endpoint)
        unknown = set(read_model["artifacts"]) - RUN_ARTIFACTS
        assert not unknown, (
            f"{matrix['screenId']} cites artifacts outside the run schema: "
            f"{sorted(unknown)}"
        )


def test_the_endpoints_match_the_openapi_contract() -> None:
    """A matrix pointing at a route OpenAPI does not declare is a dead screen."""

    openapi = yaml.safe_load(
        (REPO_ROOT / "contracts" / "api" / "openapi.yaml").read_text(
            encoding="utf-8"
        )
    )
    declared = set(openapi["paths"])
    for matrix in _matrices():
        assert matrix["readModel"]["endpoint"] in declared, (
            f"{matrix['screenId']} endpoint is not in OpenAPI"
        )


def test_every_unavailable_element_names_its_owning_decision() -> None:
    """Unavailable is a governed state, not a shrug. P4-D10 owns NRV, P4-D9 owns
    workflow, P4-D8 owns the Phase 8 exclusions -- and each element says so."""

    for matrix in _matrices():
        for element in matrix["elements"]:
            if element["status"] in {"unavailable", "out_of_scope", "disabled_action"}:
                assert element.get("decision"), (
                    f"{matrix['screenId']}: {element['label']} is "
                    f"{element['status']} without an owning decision"
                )


def test_no_element_is_removed_for_being_unavailable() -> None:
    """The forbidden repair is removal: NRV stays on the valuation screen as
    Not available, AI-vs-Control stays recorded as out of scope."""

    by_id = {matrix["screenId"]: matrix for matrix in _matrices()}
    valuation_labels = {e["label"] for e in by_id["inventoryValuation"]["elements"]}
    assert "NRV" in valuation_labels
    assert "Provisions" in valuation_labels
    health_labels = {e["label"] for e in by_id["stockHealth"]["elements"]}
    assert "AI vs Control" in health_labels
    assert "Model Performance" in health_labels


def test_actions_are_disabled_with_no_mutation_path() -> None:
    behavior = _document()["actionBehavior"]
    assert "natively disabled" in behavior
    assert "no mutation endpoint or handler" in behavior


def test_interval_consuming_screens_freeze_the_p4_d17_rule() -> None:
    """Safety stock and the planner consume the interval; both must state that a
    withheld interval is skipped with an exception, never zeroed."""

    by_id = {matrix["screenId"]: matrix for matrix in _matrices()}
    for screen_id in ("safetyStock", "replenishmentPlanner", "inventoryOverview"):
        rules = [
            element.get("intervalRule")
            for element in by_id[screen_id]["elements"]
            if element.get("intervalRule")
        ]
        assert rules, f"{screen_id} consumes the interval but freezes no rule"
        combined = " ".join(rules) + _document()["behavior"]["intervalRule"]
        assert "zero" in combined, (
            f"{screen_id} must state the no-null-to-zero rule explicitly"
        )


def test_one_bundle_owns_all_fourteen_read_models() -> None:
    """P4-D15: partial page activation is forbidden."""

    activation = _document()["activation"]
    assert activation["oneBundleForAllScreens"] is True
    assert activation["requiredLifecycleStatus"] == "accepted"
    assert activation["verifier"] == "retail-inventory-verifier/v1"


def test_the_approval_does_not_overclaim_human_review() -> None:
    """Same posture as the P4-0P amendment: an autonomous authorization must
    never be readable as a completed per-screen human sign-off."""

    approval = _document()["reviewGate"]["approval"]
    assert approval["classification"] == (
        "autonomous_authorization_not_independent_human_review"
    )
    assert approval["reviewOutstanding"]


def test_matrices_match_their_generator() -> None:
    """A hand-edited matrix silently diverging from the definition is drift."""

    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "tools" / "build_inventory_screen_matrices.py"),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_page_selectors_exist_in_the_reference_html() -> None:
    """A matrix for a page the HTML does not contain freezes nothing."""

    html = (
        REPO_ROOT / "docs" / "ai_retail_intelligence_dashboard_multicurrency_v6.html"
    ).read_text(encoding="utf-8")
    for matrix in _matrices():
        selector = matrix["pageSelector"].lstrip("#")
        assert f'id="{selector}"' in html, (
            f"{matrix['screenId']} page selector missing from reference HTML"
        )
