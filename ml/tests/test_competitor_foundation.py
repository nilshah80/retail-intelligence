import json
from pathlib import Path

import pandas as pd

from retail_ml.pricing.competitor import (
    assess_competitor_rows,
    classify_freshness,
    classify_match,
    evaluate_competitor_matcher,
    load_competitor_policy,
)


ROOT = Path(__file__).resolve().parents[2]


def _policy():
    return load_competitor_policy(ROOT / "contracts/pricing/competitor-policy.json")


def test_market_position_tolerance_is_governed() -> None:
    assert _policy()["marketPositionTolerancePct"] == "0.50"


def test_policy_freezes_thresholds_without_predeclaring_an_outcome() -> None:
    policy = _policy()
    assert "status" not in policy["evaluationGate"]
    assert policy["evaluationGate"]["minimumPopulation"] == 200


def _evaluation(*, accepted: bool, reason: str | None = None):
    return {
        "status": "accepted" if accepted else "rejected",
        "firstFailureReason": reason,
    }


def test_match_states_cover_all_ui_values() -> None:
    policy = _policy()
    attributes = '{"brand":1,"model":1,"pack":1}'

    assert classify_match(0.91, attributes, attributes, policy)[0] == "Matched"
    assert classify_match(0.80, attributes, attributes, policy)[0] == "Needs Review"
    assert classify_match(0.70, attributes, attributes, policy)[0] == "Rejected"
    assert classify_match(0.50, attributes, attributes, policy)[0] == "No Match"
    assert classify_match(0.99, "{}", attributes, policy) == (
        "Needs Review", "MATCH_ATTRIBUTES_INSUFFICIENT"
    )


def test_freshness_boundaries_are_inclusive() -> None:
    policy = _policy()
    as_of = "2026-08-11T00:00:00Z"

    assert classify_freshness("2026-07-28T00:00:00Z", as_of, policy) == ("Fresh", 14)
    assert classify_freshness("2026-07-12T00:00:00Z", as_of, policy) == ("Near threshold", 30)
    assert classify_freshness("2026-07-11T00:00:00Z", as_of, policy) == ("Stale", 31)


def test_only_audited_fresh_matched_rows_enter_price_bound() -> None:
    base = {
        "match_id": "match-1", "market_id": "gulf-india", "sku_id": "sku-1",
        "comp_id": "comp-1", "comp_product_id": "product-1",
        "matched_attributes": '{"brand":1,"model":1}',
        "product_attributes": '{"brand":"Gulf","model":"X"}',
        "observed_at": "2026-08-10T00:00:00Z",
        "known_as_of": "2026-08-10T00:00:00Z", "price_minor": 19_999,
        "currency_code": "INR", "market_currency_code": "INR",
        "availability_state": "In Stock", "compliance_ok": True,
        "evidence_class": "synthetic", "use_purpose": "synthetic_demo",
    }
    assessed = assess_competitor_rows(
        pd.DataFrame([
            {**base, "match_confidence": 0.94},
            {**base, "match_id": "match-2", "match_confidence": 0.80},
            {**base, "match_id": "match-3", "match_confidence": 0.94,
             "observed_at": "2026-06-01T00:00:00Z"},
        ]),
        decision_as_of="2026-08-11T00:00:00Z",
        policy=_policy(),
        evaluation=_evaluation(accepted=True),
    )

    by_id = assessed.set_index("match_id")
    assert by_id["match_status"].to_dict() == {
        "match-1": "Matched", "match-2": "Needs Review", "match-3": "Matched"
    }
    assert by_id["bound_eligible"].to_dict() == {
        "match-1": True, "match-2": False, "match-3": False
    }
    assert by_id.loc["match-1", "synthetic_label"] == "Synthetic demo"


def test_unaccepted_match_evaluation_withholds_an_otherwise_eligible_bound() -> None:
    row = {
        "match_id": "match-1", "market_id": "gulf-india", "sku_id": "sku-1",
        "comp_id": "comp-1", "comp_product_id": "product-1",
        "matched_attributes": '{"brand":1,"model":1}',
        "product_attributes": '{"brand":"Gulf","model":"X"}',
        "observed_at": "2026-08-10T00:00:00Z",
        "known_as_of": "2026-08-10T00:00:00Z", "price_minor": 19_999,
        "currency_code": "INR", "market_currency_code": "INR",
        "availability_state": "In Stock", "compliance_ok": True,
        "evidence_class": "synthetic", "use_purpose": "synthetic_demo",
        "match_confidence": 0.94,
    }

    assessed = assess_competitor_rows(
        pd.DataFrame([row]),
        decision_as_of="2026-08-11T00:00:00Z",
        policy=_policy(),
        evaluation=_evaluation(
            accepted=False, reason="MATCH_EVALUATION_TRUTH_NOT_DISJOINT"
        ),
    ).iloc[0]

    assert not assessed["bound_eligible"]
    assert assessed["first_exclusion_reason"] == "MATCH_EVALUATION_TRUTH_NOT_DISJOINT"


def test_zero_competitor_rows_preserve_the_governed_artifact_shape() -> None:
    columns = [
        "match_id", "market_id", "sku_id", "comp_id", "comp_product_id",
        "match_confidence", "matched_attributes", "product_attributes",
        "observed_at", "known_as_of", "price_minor", "currency_code",
        "market_currency_code", "availability_state", "compliance_ok",
        "evidence_class", "use_purpose", "geo_scope_type", "geo_scope_id",
    ]
    assessed = assess_competitor_rows(
        pd.DataFrame(columns=columns),
        decision_as_of="2026-08-11T00:00:00Z",
        policy=_policy(),
        evaluation=_evaluation(
            accepted=False, reason="MATCH_EVALUATION_TRUTH_MISSING"
        ),
    )

    assert assessed.empty
    assert {
        "match_status", "freshness", "bound_eligible",
        "first_exclusion_reason", "all_exclusion_reasons",
    } <= set(assessed.columns)


def test_held_out_evaluation_accepts_and_skips_one_bad_record(tmp_path) -> None:
    rows = []
    for index in range(420):
        label = index % 2 == 0
        split = "development" if index < 200 else "evaluation"
        reference = {
            "categoryId": "engine-oil",
            "brand": "Gulf",
            "option:grade": "5W-30",
        }
        candidate = (
            reference
            if label
            else {key: f"different:{value}" for key, value in reference.items()}
        )
        rows.append(
            {
                "candidateKey": f"truth-{index}",
                "marketKey": "gulf-india",
                "ourSku": f"sku-{index}",
                "competitorSku": f"EVAL-CMP-{index}",
                "referenceAttributes": json.dumps(reference),
                "candidateAttributes": json.dumps(candidate),
                "truthLabel": str(label).lower(),
                "truthSplit": split,
                "missingAttributeCohort": str(
                    split == "evaluation" and index < 230
                ).lower(),
            }
        )
    rows.append({**rows[-1], "candidateKey": "bad-row", "truthLabel": "not-bool"})
    path = tmp_path / "truth.parquet"
    pd.DataFrame(rows).to_parquet(path, index=False)

    result = evaluate_competitor_matcher(
        path,
        served_matches=pd.DataFrame(
            columns=["market_id", "sku_id", "comp_product_id"]
        ),
        policy=_policy(),
    )

    assert result["status"] == "accepted"
    assert result["evaluationPopulation"] == 220
    assert result["recordExceptionCount"] == 1
    assert result["recordExceptionReasons"] == {
        "MATCH_EVALUATION_TRUTH_RECORD_INVALID": 1
    }
