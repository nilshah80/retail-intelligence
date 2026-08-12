import hashlib
import json

import pandas as pd
import pytest

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.pricing.bundle import (
    ARTIFACT_CONTRACT_PATH,
    ARTIFACT_SCHEMAS,
    MANIFEST_VOLATILE_POINTERS,
    POLICY_PATHS,
    PricingBundleError,
    publish_pricing_bundle,
    verify_pricing_bundle,
    write_verification_record,
)


CONTRACT = json.loads(ARTIFACT_CONTRACT_PATH.read_text(encoding="utf-8"))


def _empty(name: str) -> pd.DataFrame:
    return pd.DataFrame(
        columns=CONTRACT["artifacts"][name]["requiredColumns"]
    )


def _policies() -> dict[str, str]:
    return {
        name: hashlib.sha256(path.read_bytes()).hexdigest()
        for name, path in POLICY_PATHS.items()
    }


def _lineage() -> dict[str, str]:
    return {
        "publicationSemanticFingerprint": "1" * 64,
        "readinessReportFingerprint": "2" * 64,
        "inputAuthorityId": "auth_0123456789abcdef",
        "sourceRunId": "run-0123456789abcdef",
    }


def _scope(*, sparse: bool = False) -> dict[str, str]:
    return {
        "retailerId": "retailer-demo",
        "tenantId": "tenant-demo",
        "environment": "dev" if sparse else "local",
        "audience": (
            "pricing_evidence_sparse_dev" if sparse else "response_rich_local"
        ),
    }


def _capabilities(*, sparse: bool = False) -> dict[str, object]:
    return {
        "priceRevenue": {
            "available": not sparse,
            "actionableRows": 0 if sparse else 25,
        }
    }


def _artifacts(*, sparse: bool = False):
    selection = json.dumps(
        {
            "selectionMetric": "poisson_deviance_improvement",
            "developmentOrigins": list(range(1, 9)),
            "confirmationOriginsRead": [],
            "candidateCount": 3,
            "candidateScores": [
                {
                    "configurationId": "glm-local",
                    "meanDevianceImprovement": None if sparse else 0.10,
                    "safeSignRate": None if sparse else 0.95,
                    "meanDeviance": None if sparse else 100.0,
                },
                {
                    "configurationId": "glm-department",
                    "meanDevianceImprovement": None if sparse else 0.11,
                    "safeSignRate": None if sparse else 0.95,
                    "meanDeviance": None if sparse else 90.0,
                },
                {
                    "configurationId": "glm-department-tier",
                    "meanDevianceImprovement": None if sparse else 0.12,
                    "safeSignRate": None if sparse else 0.96,
                    "meanDeviance": None if sparse else 80.0,
                },
            ],
            "selectedConfigurationId": None if sparse else "glm-department-tier",
            "selectedShrinkage": None if sparse else "department_price_tier",
            "status": "not_evaluable" if sparse else "selected",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    origins = json.dumps(
        [
            {
                "index": index,
                "status": "scored",
                "baselineSpecification": "same_controls_without_log_price",
            }
            for index in range(1, 14)
        ],
        separators=(",", ":"),
    )
    response_template = {
            "market_id": "gulf-india",
            "channel_id": "store",
            "channel_type": "store",
            "department_id": "dept-1",
            "currency_code": "INR",
            "observation_count": 156,
            "price_level_count": 4,
            "price_transition_count": 12,
            "store_shortfall_week_count": 0,
            "store_shortfall_units": 0,
            "current_price_minor": 20_000,
            "development_tier_price_minor": 20_000,
            "disposition": "insufficient_evidence" if sparse else "accepted",
            "first_failure_reason": "INSUFFICIENT_PRICE_LEVELS" if sparse else None,
            "raw_beta": None if sparse else -1.2,
            "shrunk_beta": None if sparse else -1.2,
            "confidence": None if sparse else 0.96,
            "resample_iqr_ratio": None if sparse else 0.2,
            "valid_resample_draws": 0 if sparse else 200,
            "development_improvement": None if sparse else 0.12,
            "confirmation_improvement": None if sparse else 0.1,
            "origin_diagnostics": "[]" if sparse else origins,
            "price_tier": 2,
            "selected_configuration_id": None if sparse else "glm-department-tier",
            "selected_shrinkage": None if sparse else "department_price_tier",
            "candidate_selection_diagnostics": selection,
            "department_accepted_coverage": 1.0 if not sparse else 0.0,
            "department_distinct_sku_store_pairs": 25 if not sparse else 0,
            "department_enabled": not sparse,
    }
    row_count = 1 if sparse else 25
    response = pd.DataFrame(
        [
            {
                **response_template,
                "sku_id": f"sku-{index:02d}",
                "store_id": f"store-{index:02d}",
            }
            for index in range(row_count)
        ]
    )
    recommendation_template = {
            "market_id": "gulf-india",
            "channel_id": "store",
            "channel_type": "store",
            "record_kind": "withheld_assessment" if sparse else "recommendation",
            "selectable": not sparse,
            "action": None if sparse else "Increase",
            "disposition": "withheld" if sparse else "recommended",
            "first_failure_reason": (
                "INSUFFICIENT_PRICE_LEVELS" if sparse
                else "NO_BETTER_LEGAL_CANDIDATE"
            ),
            "current_price_minor": 20_000,
            "proposed_price_minor": None if sparse else 21_000,
            "currency_code": "INR",
            "expected_units_current": None if sparse else 100.0,
            "expected_units_proposed": None if sparse else 95.0,
            "expected_revenue_current_minor": None if sparse else 2_000_000,
            "expected_revenue_proposed_minor": None if sparse else 1_995_000,
            "revenue_impact_minor": None if sparse else -5_000,
            "margin_impact_minor": None,
            "margin_reason_code": "COST_NOT_CLIENT_ACTUAL",
            "confidence": None if sparse else 0.96,
            "priority": "Manual review" if sparse else "Low",
            "risk": "Unavailable" if sparse else "Low",
            "drivers": "[]",
            "lineage": "{}",
    }
    recommendation = pd.DataFrame(
        [
            {
                **recommendation_template,
                "sku_id": f"sku-{index:02d}",
                "store_id": f"store-{index:02d}",
                "recommendation_id": f"pr_{index:020x}",
            }
            for index in range(row_count)
        ]
    )
    result = {
        "pricing_panel": _empty("pricing_panel"),
        "response_assessments": response,
        "price_candidates": _empty("price_candidates"),
        "price_recommendations": recommendation,
        "competitor_assessments": _empty("competitor_assessments"),
        "competitor_bounds": _empty("competitor_bounds"),
        "competitor_evaluation": {
            "schemaVersion": ARTIFACT_SCHEMAS["competitor_evaluation"],
            "protocolVersion": "competitor-match-evaluation/1.0.0",
            "status": "accepted",
            "firstFailureReason": None,
            "truthSha256": "a" * 64,
            "truthMayBeServed": False,
            "developmentPopulation": 200,
            "evaluationPopulation": 200,
            "missingAttributeCohort": 25,
            "truthPositiveCount": 100,
            "truthNegativeCount": 100,
            "truePositive": 100,
            "falsePositive": 0,
            "trueNegative": 100,
            "falseNegative": 0,
            "precision": 1.0,
            "recall": 1.0,
            "falseMatchRate": 0.0,
            "expectedCalibrationError": 0.01,
            "calibrationBins": [
                {"index": 0, "count": 100, "meanConfidence": 0.01, "positiveRate": 0.0},
                {"index": 9, "count": 100, "meanConfidence": 0.99, "positiveRate": 1.0},
            ],
            "developmentPairSetSha256": "b" * 64,
            "evaluationPairSetSha256": "c" * 64,
            "developmentEvaluationOverlap": 0,
            "servedTruthPairOverlap": 0,
            "recordExceptionCount": 0,
            "recordExceptionReasons": {},
        },
        "promotion_protection": _empty("promotion_protection"),
        "promotion_disposition": {
            "schemaVersion": ARTIFACT_SCHEMAS["promotion_disposition"],
            "decisionId": 53,
            "decisionDisposition": "not_amended",
            "packageDisposition": "negative",
            "plannerAvailable": False,
            "firstFailureReason": "PROMOTION_FEATURE_POLICY_NOT_AMENDED",
            "safetyGuardInternal": True,
            "forbiddenClaims": ["numeric_uplift"],
        },
    }
    return result


@pytest.mark.parametrize("sparse", [False, True])
def test_bundle_closes_and_verifies_outside_its_artifact_set(tmp_path, sparse) -> None:
    bundle = publish_pricing_bundle(
        tmp_path / "bundle",
        bundle_kind="evidence_sparse" if sparse else "response_rich",
        decision_as_of="2026-07-31T00:00:00Z",
        artifacts=_artifacts(sparse=sparse),
        lineage=_lineage(),
        policies=_policies(),
        capabilities=_capabilities(sparse=sparse),
        selection_scope=_scope(sparse=sparse),
    )
    verification = verify_pricing_bundle(bundle)
    record = write_verification_record(bundle, tmp_path / "pricing-verification.json")

    assert verification["passed"] is True
    assert record.parent != bundle
    assert json.loads(record.read_text())["bundleId"] == verification["bundleId"]


def test_tampered_artifact_is_refused(tmp_path) -> None:
    bundle = publish_pricing_bundle(
        tmp_path / "bundle", bundle_kind="response_rich",
        decision_as_of="2026-07-31T00:00:00Z", artifacts=_artifacts(),
        lineage=_lineage(),
        policies=_policies(), capabilities=_capabilities(),
        selection_scope=_scope(),
    )
    target = bundle / "promotion_disposition.json"
    target.write_text(target.read_text().replace("negative", "positive_numeric"))

    with pytest.raises(PricingBundleError, match="byte count mismatch|checksum mismatch"):
        verify_pricing_bundle(bundle)


def test_independent_verifier_rejects_a_producer_accepted_gate_failure(tmp_path) -> None:
    artifacts = _artifacts()
    artifacts["response_assessments"].loc[0, "confidence"] = 0.50
    bundle = publish_pricing_bundle(
        tmp_path / "bundle",
        bundle_kind="response_rich",
        decision_as_of="2026-07-31T00:00:00Z",
        artifacts=artifacts,
        lineage=_lineage(),
        policies=_policies(),
        capabilities=_capabilities(),
        selection_scope=_scope(),
    )

    with pytest.raises(PricingBundleError, match="independently"):
        verify_pricing_bundle(bundle)


def test_artifact_contract_rejects_a_missing_governance_column(tmp_path) -> None:
    artifacts = _artifacts()
    artifacts["response_assessments"] = artifacts[
        "response_assessments"
    ].drop(columns=["candidate_selection_diagnostics"])

    with pytest.raises(PricingBundleError, match="lacks required columns"):
        publish_pricing_bundle(
            tmp_path / "bundle",
            bundle_kind="response_rich",
            decision_as_of="2026-07-31T00:00:00Z",
            artifacts=artifacts,
            lineage=_lineage(),
            policies=_policies(),
            capabilities=_capabilities(),
            selection_scope=_scope(),
        )


def test_verifier_recomputes_prebound_selection_identity(tmp_path) -> None:
    bundle = publish_pricing_bundle(
        tmp_path / "bundle",
        bundle_kind="response_rich",
        decision_as_of="2026-07-31T00:00:00Z",
        artifacts=_artifacts(),
        lineage=_lineage(),
        policies=_policies(),
        capabilities=_capabilities(),
        selection_scope=_scope(),
    )
    manifest_path = bundle / "pricing-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prospectiveResultSelections"][0]["evidence"][
        "recommendationsFingerprint"
    ] = "f" * 64
    payload = dict(manifest)
    payload.pop("semanticFingerprint")
    fingerprint = semantic_fingerprint(
        payload, volatile_pointers=MANIFEST_VOLATILE_POINTERS
    )
    manifest["bundleId"] = "pb_" + fingerprint[:20]
    manifest["semanticFingerprint"] = fingerprint
    manifest_path.write_text(
        json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(PricingBundleError, match="prospective result-selection"):
        verify_pricing_bundle(bundle)
