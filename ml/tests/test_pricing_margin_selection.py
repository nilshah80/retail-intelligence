"""price_margin selection-lifecycle capability (additive, gated).

These lock the additive contract foundation that lets a genuine client-actual
build carry a price_margin selection alongside price_revenue. The generated
pipeline never produces a price_margin capability, so this is exercised here with
synthetic client-actual evidence only; nothing here activates a live selection.
"""

from pathlib import Path

import pytest

from retail_ml.pricing.selection import (
    PricingSelectionError,
    build_selection_intent,
    build_selection_record,
    validate_selection_intent,
    validate_selection_record,
)


ROOT = Path(__file__).resolve().parents[2]
INTENT_SCHEMA = ROOT / "contracts/pricing/result-selection-intent.schema.json"
RECORD_SCHEMA = ROOT / "contracts/pricing/result-selection.schema.json"

_COMMON_EVIDENCE = {
    "sourcePublicationFingerprint": "a" * 64,
    "readinessReportFingerprint": "b" * 64,
    "inputAuthorityId": "auth_" + "0" * 16,
    "responsePolicySha256": "c" * 64,
    "pricingPolicySha256": "d" * 64,
    "artifactContractSha256": "e" * 64,
    "responseAssessmentsFingerprint": "f" * 64,
    "recommendationsFingerprint": "0" * 64,
}
REVENUE_EVIDENCE = {**_COMMON_EVIDENCE, "priceRevenueCapabilityFingerprint": "1" * 64}
MARGIN_EVIDENCE = {**_COMMON_EVIDENCE, "priceMarginCapabilityFingerprint": "2" * 64}
SCOPE = dict(retailer_id="gulf-oil-india", tenant_id="gulf-india", environment="local",
             audience="response_rich_local")


def test_price_revenue_selection_still_validates_unchanged() -> None:
    intent = build_selection_intent(**SCOPE, evidence=REVENUE_EVIDENCE)
    assert intent["capability"] == "price_revenue"
    assert validate_selection_intent(intent, INTENT_SCHEMA)["selectionId"] == intent["selectionId"]


def test_price_margin_selection_intent_is_representable() -> None:
    intent = build_selection_intent(**SCOPE, evidence=MARGIN_EVIDENCE, capability="price_margin")
    assert intent["capability"] == "price_margin"
    # Distinct evidence ⇒ distinct identity from the revenue selection.
    revenue = build_selection_intent(**SCOPE, evidence=REVENUE_EVIDENCE)
    assert intent["selectionId"] != revenue["selectionId"]
    validate_selection_intent(intent, INTENT_SCHEMA)


def test_price_margin_selection_record_is_representable() -> None:
    record = build_selection_record(
        **SCOPE, evidence=MARGIN_EVIDENCE, capability="price_margin",
        state="candidate", bundle_id="pb_" + "0" * 20,
        bundle_semantic_fingerprint="a" * 64, predecessor_record_id=None,
        actor="reviewer", reason="client-actual cost approved",
        recorded_at="2026-08-13T00:00:00Z",
    )
    assert record["capability"] == "price_margin"
    validate_selection_record(record, RECORD_SCHEMA)


def test_margin_capability_requires_the_margin_fingerprint() -> None:
    # A price_margin selection carrying only the revenue fingerprint must fail the
    # capability-conditional evidence gate.
    bad = build_selection_intent(**SCOPE, evidence=REVENUE_EVIDENCE, capability="price_margin")
    with pytest.raises(PricingSelectionError):
        validate_selection_intent(bad, INTENT_SCHEMA)


def test_unknown_capability_is_refused() -> None:
    with pytest.raises(PricingSelectionError):
        build_selection_intent(**SCOPE, evidence=MARGIN_EVIDENCE, capability="price_clearance")
