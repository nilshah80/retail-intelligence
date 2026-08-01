"""PP3-A6 deliverables A-D7 and A-D8, with the negative fixtures that matter.

Business dates must never become availability, a missing sale must not become a
zero without evidence, and readiness must stay separate from statistical
sufficiency.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from retail_ingestion.readiness.evaluator import (
    BLOCKED,
    INSUFFICIENT,
    NOT_EVALUATED,
    READY,
    SUFFICIENT,
    UNAVAILABLE,
    VALIDATED_PARTIAL,
    ReadinessError,
    ReadinessInputs,
    RoleEvidence,
    ZeroDemandCell,
    build_readiness_report,
    evaluate_capabilities,
    evaluate_temporal_evidence,
    evaluate_zero_demand,
    load_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def policy() -> dict:
    return load_policy(REPO_ROOT)


def _inputs(**overrides) -> ReadinessInputs:
    evidence = {
        role: RoleEvidence(role=role, grade="native_extracted", rows=100)
        for role in (
            "merchandise",
            "assortment",
            "product",
            "location",
            "sell_price",
            "weather_forecast",
            "inventory",
            "inbound_shipment",
            "supplier_term",
            "inventory_cost",
            "promotion",
            "promotion_target",
            "competitor_match",
            "competitor_price",
        )
    }
    base = {
        "role_evidence": evidence,
        "present_roles": frozenset(evidence),
        "evidence_flags": frozenset(
            {
                "reconciliation",
                "sufficient_history",
                "accepted_fallback_semantics",
                "origin_visible_targets",
                "origin_visible_features",
                "all_temporal_entities_origin_safe",
                "reconciled_demand",
                "lead_time_evidence",
                "origin_safe_prices",
                "demand_response_evidence",
                "temporal_cost_ledger_matching_currency_scope",
                "origin_visible_historical_and_future_plans",
                "origin_visible_match_price_availability",
            }
        ),
        "sufficiency": {},
    }
    base.update(overrides)
    return ReadinessInputs(**base)


# ---------------------------------------------------------------------------
# Temporal evidence
# ---------------------------------------------------------------------------
def test_the_five_grades_are_closed_and_ranked(policy: dict) -> None:
    grades = policy["grades"]
    assert set(grades) == {
        "native_observed",
        "native_processed",
        "native_posted_available",
        "native_extracted",
        "landing_backfill",
    }
    ranks = [grades[g]["rank"] for g in grades]
    assert sorted(ranks) == [1, 2, 3, 4, 5]
    assert grades["landing_backfill"]["supportsHistoricalReplay"] is False
    assert set(grades["landing_backfill"]["downgrades"]) == {
        "historical_replay",
        "point_in_time_forecasting",
    }


def test_a_business_date_is_never_availability_evidence(policy: dict) -> None:
    for column in ("business_date", "effective_date", "transaction_date"):
        assert column in policy["neverProvesAvailability"]

    inputs = _inputs(
        role_evidence={
            "merchandise": RoleEvidence(
                role="merchandise",
                grade="native_extracted",
                rows=10,
                availability_fields=("business_date",),
            )
        }
    )
    result = evaluate_temporal_evidence(inputs, policy)
    assert result["violations"] == [
        {
            "role": "merchandise",
            "field": "business_date",
            "reasonCode": "BUSINESS_DATE_AS_AVAILABILITY",
        }
    ]


def test_a_business_date_violation_blocks_replay_capabilities(policy: dict) -> None:
    """A silently origin-unsafe capability is worse than an unavailable one."""

    inputs = _inputs(
        role_evidence={
            **{
                role: RoleEvidence(role=role, grade="native_extracted", rows=10)
                for role in _inputs().present_roles
            },
            "merchandise": RoleEvidence(
                role="merchandise",
                grade="native_extracted",
                rows=10,
                availability_fields=("effective_date",),
            ),
        }
    )
    report = build_readiness_report(
        inputs,
        [],
        repository_root=REPO_ROOT,
        tenant_id="tenant-a",
        source_snapshot_id="snap-1",
    )
    replay = report["capabilities"]["historical_replay"]
    assert replay["readiness"] == BLOCKED
    assert "BUSINESS_DATE_AS_AVAILABILITY" in replay["reasonCodes"]
    assert replay["consumerMayProceed"] is False

    # Descriptive analytics tolerates weak evidence, so it is not blocked.
    assert report["capabilities"]["current_descriptive_analytics"]["readiness"] != (
        BLOCKED
    )


def test_landing_only_evidence_downgrades_replay(policy: dict) -> None:
    inputs = _inputs(
        role_evidence={
            role: RoleEvidence(role=role, grade="landing_backfill", rows=10)
            for role in _inputs().present_roles
        }
    )
    capabilities = evaluate_capabilities(inputs, policy)

    assert capabilities["historical_replay"]["readiness"] == UNAVAILABLE
    assert any(
        reason.startswith("EVIDENCE_GRADE_TOO_WEAK")
        for reason in capabilities["historical_replay"]["reasonCodes"]
    )
    assert capabilities["point_in_time_forecasting"]["readiness"] == UNAVAILABLE
    # Non-PIT forecasting explicitly tolerates landing_backfill.
    assert capabilities["demand_forecast_non_pit"]["readiness"] == READY


def test_an_unknown_grade_is_refused(policy: dict) -> None:
    inputs = _inputs(
        role_evidence={
            "merchandise": RoleEvidence(
                role="merchandise", grade="probably_fine", rows=1
            )
        }
    )
    with pytest.raises(ReadinessError, match="unknown evidence grade"):
        evaluate_temporal_evidence(inputs, policy)


# ---------------------------------------------------------------------------
# Zero demand
# ---------------------------------------------------------------------------
def _cell(**overrides) -> ZeroDemandCell:
    base = {
        "sku_id": "SKU-1",
        "store_id": "store-1",
        "channel_id": "store",
        "interval_start": "2026-01-05",
        "extract_complete": True,
        "assortment_active": True,
        "known_by_cutoff": True,
    }
    base.update(overrides)
    return ZeroDemandCell(**base)


def test_a_fully_evidenced_cell_may_become_zero(policy: dict) -> None:
    result = evaluate_zero_demand([_cell()], policy)
    assert result["zeroEligible"] == 1
    assert result["unknown"] == 0


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"extract_complete": False}, "EXTRACT_INCOMPLETE"),
        ({"assortment_active": None}, "ASSORTMENT_UNKNOWN"),
        ({"assortment_active": False}, "ASSORTMENT_INACTIVE"),
        ({"known_by_cutoff": False}, "NOT_KNOWN_BY_CUTOFF"),
        ({"boundary_exposure_handled": False}, "BOUNDARY_EXPOSURE_PARTIAL"),
        ({"unresolved_gap": True}, "CHANNEL_COVERAGE_INCOMPLETE"),
    ],
)
def test_every_missing_condition_yields_unknown_not_zero(
    policy: dict,
    override: dict,
    reason: str,
) -> None:
    result = evaluate_zero_demand([_cell(**override)], policy)

    assert result["zeroEligible"] == 0
    assert result["unknown"] == 1
    assert result["unknownReasonCodes"] == {reason: 1}


def test_a_current_catalog_backfill_cannot_manufacture_history(
    policy: dict,
) -> None:
    """Assortment unknown for a historical interval stays unknown."""

    historical = [
        _cell(interval_start="2018-01-01", assortment_active=None),
        _cell(interval_start="2018-01-08", assortment_active=None),
    ]
    result = evaluate_zero_demand(historical, policy)

    assert result["zeroEligible"] == 0
    assert result["unknownReasonCodes"] == {"ASSORTMENT_UNKNOWN": 2}
    forbidden = " ".join(policy["zeroDemand"]["forbidden"]).lower()
    assert "current catalog" in forbidden


def test_zero_demand_never_infers_assortment_from_sales(policy: dict) -> None:
    forbidden = " ".join(policy["zeroDemand"]["forbidden"]).lower()
    assert "inferring assortment from the presence of sales" in forbidden


# ---------------------------------------------------------------------------
# Capability readiness vs statistical sufficiency
# ---------------------------------------------------------------------------
def test_readiness_and_sufficiency_are_separate_fields(policy: dict) -> None:
    inputs = _inputs(sufficiency={"demand_forecast_non_pit": INSUFFICIENT})
    capabilities = evaluate_capabilities(inputs, policy)
    forecast = capabilities["demand_forecast_non_pit"]

    # Ready but statistically insufficient is a legitimate, reportable state.
    assert forecast["readiness"] == READY
    assert forecast["sufficiency"] == INSUFFICIENT
    assert forecast["consumerMayProceed"] is False


def test_unevaluated_sufficiency_is_not_a_pass(policy: dict) -> None:
    capabilities = evaluate_capabilities(_inputs(), policy)
    forecast = capabilities["demand_forecast_non_pit"]

    assert forecast["sufficiency"] == NOT_EVALUATED
    assert forecast["consumerMayProceed"] is False


def test_a_ready_and_sufficient_capability_may_proceed(policy: dict) -> None:
    inputs = _inputs(sufficiency={"demand_forecast_non_pit": SUFFICIENT})
    forecast = evaluate_capabilities(inputs, policy)["demand_forecast_non_pit"]

    assert forecast["readiness"] == READY
    assert forecast["consumerMayProceed"] is True


def test_validated_partial_stops_before_a_consumer(policy: dict) -> None:
    inputs = _inputs(
        evidence_flags=frozenset({"reconciliation", "sufficient_history"}),
        sufficiency={"demand_forecast_non_pit": SUFFICIENT},
    )
    forecast = evaluate_capabilities(inputs, policy)["demand_forecast_non_pit"]

    assert forecast["readiness"] == VALIDATED_PARTIAL
    assert "MISSING_EVIDENCE:accepted_fallback_semantics" in forecast["reasonCodes"]
    assert forecast["consumerMayProceed"] is False


def test_an_incomplete_channel_or_missing_role_is_reason_coded(
    policy: dict,
) -> None:
    inputs = _inputs(present_roles=frozenset({"merchandise", "product", "location"}))
    capabilities = evaluate_capabilities(inputs, policy)

    forecast = capabilities["demand_forecast_non_pit"]
    assert forecast["readiness"] == UNAVAILABLE
    assert "MISSING_ROLE:assortment" in forecast["reasonCodes"]
    # Nothing is fabricated: descriptive analytics still works.
    assert capabilities["current_descriptive_analytics"]["readiness"] == READY


def test_the_report_summarises_every_capability(policy: dict) -> None:
    report = build_readiness_report(
        _inputs(sufficiency={"demand_forecast_non_pit": SUFFICIENT}),
        [_cell()],
        repository_root=REPO_ROOT,
        tenant_id="tenant-a",
        source_snapshot_id="snap-1",
    )

    assert report["schemaVersion"] == "retail-readiness-report/v1"
    # Pinned to the loaded policy rather than to a literal, because the report's
    # job is to name the policy that actually produced its verdicts. Hard-coding
    # v1 here would keep passing after v2 was loaded, which is the same class of
    # stale assertion as a test that asserted `no_accepted_forecast`.
    assert report["policyId"] == policy["policyId"]
    assert report["tenantId"] == "tenant-a"
    declared = set(policy["capabilities"]["definitions"])
    assert set(report["capabilities"]) == declared
    buckets = report["summary"]
    counted = (
        len(buckets["ready"])
        + len(buckets["validatedPartial"])
        + len(buckets["unavailable"])
        + len(buckets["blocked"])
    )
    assert counted == len(declared)
