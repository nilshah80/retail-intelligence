"""Auditable competitor matching, freshness, and price-bound foundation."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

import duckdb
import pandas as pd


class CompetitorFoundationError(RuntimeError):
    """Competitor evidence cannot support a governed assessment."""


EVALUATION_SCHEMA = "retail-competitor-evaluation/v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _set_fingerprint(values: set[str]) -> str:
    return hashlib.sha256(
        ("\n".join(sorted(values)) + "\n").encode("utf-8")
    ).hexdigest()


def _empty_evaluation(reason: str) -> dict[str, Any]:
    return {
        "schemaVersion": EVALUATION_SCHEMA,
        "protocolVersion": "competitor-match-evaluation/1.0.0",
        "status": "insufficient_evidence",
        "firstFailureReason": reason,
        "truthSha256": None,
        "truthMayBeServed": False,
        "developmentPopulation": 0,
        "evaluationPopulation": 0,
        "missingAttributeCohort": 0,
        "truthPositiveCount": 0,
        "truthNegativeCount": 0,
        "truePositive": 0,
        "falsePositive": 0,
        "trueNegative": 0,
        "falseNegative": 0,
        "precision": None,
        "recall": None,
        "falseMatchRate": None,
        "expectedCalibrationError": None,
        "calibrationBins": [],
        "developmentPairSetSha256": _set_fingerprint(set()),
        "evaluationPairSetSha256": _set_fingerprint(set()),
        "developmentEvaluationOverlap": 0,
        "servedTruthPairOverlap": 0,
        "recordExceptionCount": 0,
        "recordExceptionReasons": {},
    }


def _strict_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise ValueError("boolean value is not true/false")


def _attribute_map(value: Any) -> dict[str, str]:
    parsed = value if isinstance(value, Mapping) else json.loads(str(value))
    if not isinstance(parsed, Mapping):
        raise ValueError("attribute value is not an object")
    return {
        str(key): str(item)
        for key, item in parsed.items()
        if item not in (None, "")
    }


def _held_out_score(
    reference: Mapping[str, str], candidate: Mapping[str, str]
) -> tuple[float, int]:
    """Score raw held-out attributes without reading their truth label."""

    option_keys = sorted(key for key in reference if key.startswith("option:"))
    weights: dict[str, float] = {}
    if reference.get("categoryId"):
        weights["categoryId"] = 0.35
    if reference.get("brand"):
        weights["brand"] = 0.15
    if option_keys:
        for key in option_keys:
            weights[key] = 0.50 / len(option_keys)
    elif reference.get("gtin"):
        weights["gtin"] = 0.50
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("truth candidate has no scorable attributes")
    matched = sum(
        weight
        for key, weight in weights.items()
        if candidate.get(key) == reference.get(key)
    )
    compared = sum(key in candidate for key in weights)
    return matched / total, compared


def evaluate_competitor_matcher(
    truth_path: str | Path | None,
    *,
    served_matches: pd.DataFrame,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate held-out labelled pairs and return a non-serving acceptance record.

    A malformed candidate is excluded with a reason-coded exception so the rest
    of the evaluation population can still be assessed. File/schema authority,
    duplicate identities, and truth/output overlap fail the competitor gate
    closed, but do not abort unrelated price-response work.
    """

    if truth_path is None:
        return _empty_evaluation("MATCH_EVALUATION_TRUTH_MISSING")
    path = Path(truth_path).resolve()
    if not path.is_file():
        return _empty_evaluation("MATCH_EVALUATION_TRUTH_MISSING")
    try:
        truth = (
            pd.read_parquet(path)
            if path.suffix.lower() in {".parquet", ".pq"}
            else pd.read_csv(path, keep_default_na=False)
        )
    except (OSError, RuntimeError, ValueError) as exc:
        result = _empty_evaluation("MATCH_EVALUATION_TRUTH_UNREADABLE")
        result["recordExceptionCount"] = 1
        result["recordExceptionReasons"] = {type(exc).__name__: 1}
        return result
    required = {
        "candidateKey", "marketKey", "ourSku", "competitorSku",
        "referenceAttributes", "candidateAttributes", "truthLabel",
        "truthSplit", "missingAttributeCohort",
    }
    missing = sorted(required - set(truth.columns))
    if missing:
        result = _empty_evaluation("MATCH_EVALUATION_TRUTH_SCHEMA_INVALID")
        result["truthSha256"] = _sha256_file(path)
        result["recordExceptionCount"] = len(truth)
        result["recordExceptionReasons"] = {
            "MATCH_EVALUATION_TRUTH_SCHEMA_INVALID": len(truth)
        }
        return result

    exceptions: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    candidate_keys: set[str] = set()
    duplicate_identity = False
    matched_threshold = float(policy["matchThresholds"]["matched"])
    for source in truth.to_dict("records"):
        try:
            candidate_key = str(source["candidateKey"]).strip()
            market = str(source["marketKey"]).strip()
            our_sku = str(source["ourSku"]).strip()
            competitor_sku = str(source["competitorSku"]).strip()
            split = str(source["truthSplit"]).strip()
            if not all((candidate_key, market, our_sku, competitor_sku)):
                raise ValueError("truth identity is blank")
            if split not in {"development", "evaluation"}:
                raise ValueError("truth split is invalid")
            if candidate_key in candidate_keys:
                duplicate_identity = True
                exceptions["MATCH_EVALUATION_TRUTH_DUPLICATE"] += 1
                continue
            candidate_keys.add(candidate_key)
            label = _strict_bool(source["truthLabel"])
            missing_cohort = _strict_bool(source["missingAttributeCohort"])
            reference = _attribute_map(source["referenceAttributes"])
            candidate = _attribute_map(source["candidateAttributes"])
            raw_score, compared = _held_out_score(reference, candidate)
            confidence = min(0.99, max(0.01, raw_score))
            candidates.append(
                {
                    "candidateKey": candidate_key,
                    "pairKey": "|".join((market, our_sku, competitor_sku)),
                    "split": split,
                    "label": label,
                    "missing": missing_cohort,
                    "confidence": confidence,
                    "predicted": confidence >= matched_threshold and compared >= 2,
                }
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            exceptions["MATCH_EVALUATION_TRUTH_RECORD_INVALID"] += 1
            continue

    development = [row for row in candidates if row["split"] == "development"]
    evaluation = [row for row in candidates if row["split"] == "evaluation"]
    development_keys = {str(row["candidateKey"]) for row in development}
    evaluation_keys = {str(row["candidateKey"]) for row in evaluation}
    evaluation_pairs = {str(row["pairKey"]) for row in evaluation}
    served_pairs = {
        "|".join(
            (
                str(row.get("market_id", "")),
                str(row.get("sku_id", "")),
                str(row.get("comp_product_id", "")),
            )
        )
        for row in served_matches.to_dict("records")
    }
    overlap = len(development_keys & evaluation_keys)
    served_overlap = len(evaluation_pairs & served_pairs)
    tp = sum(row["predicted"] and row["label"] for row in evaluation)
    fp = sum(row["predicted"] and not row["label"] for row in evaluation)
    tn = sum(not row["predicted"] and not row["label"] for row in evaluation)
    fn = sum(not row["predicted"] and row["label"] for row in evaluation)
    positive = tp + fn
    negative = tn + fp
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / positive if positive else 0.0
    false_match_rate = fp / negative if negative else 0.0
    bins: list[dict[str, Any]] = []
    for index in range(10):
        rows = [
            row for row in evaluation
            if min(9, int(float(row["confidence"]) * 10)) == index
        ]
        if not rows:
            continue
        bins.append(
            {
                "index": index,
                "count": len(rows),
                "meanConfidence": sum(float(row["confidence"]) for row in rows)
                / len(rows),
                "positiveRate": sum(bool(row["label"]) for row in rows) / len(rows),
            }
        )
    ece = (
        sum(
            row["count"]
            * abs(float(row["meanConfidence"]) - float(row["positiveRate"]))
            for row in bins
        )
        / len(evaluation)
        if evaluation
        else 1.0
    )
    gate = policy["evaluationGate"]
    first_failure = None
    if duplicate_identity or overlap or served_overlap:
        first_failure = "MATCH_EVALUATION_TRUTH_NOT_DISJOINT"
    elif len(evaluation) < int(gate["minimumPopulation"]):
        first_failure = "MATCH_EVALUATION_POPULATION_INSUFFICIENT"
    elif sum(bool(row["missing"]) for row in evaluation) < int(
        gate["minimumMissingAttributeCohort"]
    ):
        first_failure = "MATCH_EVALUATION_MISSING_ATTRIBUTE_COHORT_INSUFFICIENT"
    elif precision < float(gate["precisionMin"]):
        first_failure = "MATCH_EVALUATION_PRECISION_REJECTED"
    elif recall < float(gate["recallMin"]):
        first_failure = "MATCH_EVALUATION_RECALL_REJECTED"
    elif false_match_rate > float(gate["falseMatchRateMax"]):
        first_failure = "MATCH_EVALUATION_FALSE_MATCH_RATE_REJECTED"
    elif ece > float(gate["expectedCalibrationErrorMax"]):
        first_failure = "MATCH_EVALUATION_CALIBRATION_REJECTED"
    return {
        "schemaVersion": EVALUATION_SCHEMA,
        "protocolVersion": "competitor-match-evaluation/1.0.0",
        "status": "accepted" if first_failure is None else "rejected",
        "firstFailureReason": first_failure,
        "truthSha256": _sha256_file(path),
        "truthMayBeServed": False,
        "developmentPopulation": len(development),
        "evaluationPopulation": len(evaluation),
        "missingAttributeCohort": sum(bool(row["missing"]) for row in evaluation),
        "truthPositiveCount": positive,
        "truthNegativeCount": negative,
        "truePositive": tp,
        "falsePositive": fp,
        "trueNegative": tn,
        "falseNegative": fn,
        "precision": precision,
        "recall": recall,
        "falseMatchRate": false_match_rate,
        "expectedCalibrationError": ece,
        "calibrationBins": bins,
        "developmentPairSetSha256": _set_fingerprint(development_keys),
        "evaluationPairSetSha256": _set_fingerprint(evaluation_keys),
        "developmentEvaluationOverlap": overlap,
        "servedTruthPairOverlap": served_overlap,
        "recordExceptionCount": sum(exceptions.values()),
        "recordExceptionReasons": dict(sorted(exceptions.items())),
    }


def load_competitor_policy(path: str | Path) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("schemaVersion") != "retail-competitor-assessment/v1":
        raise CompetitorFoundationError("unsupported competitor policy")
    thresholds = policy["matchThresholds"]
    values = [
        float(thresholds["matched"]),
        float(thresholds["needsReview"]),
        float(thresholds["rejected"]),
    ]
    if values != sorted(values, reverse=True):
        raise CompetitorFoundationError("competitor thresholds are not descending")
    try:
        market_position_tolerance = float(policy["marketPositionTolerancePct"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CompetitorFoundationError(
            "competitor market-position tolerance is absent or invalid"
        ) from exc
    if not 0 <= market_position_tolerance < 100:
        raise CompetitorFoundationError(
            "competitor market-position tolerance must be in [0, 100)"
        )
    evaluation = policy.get("evaluationGate")
    if not isinstance(evaluation, Mapping):
        raise CompetitorFoundationError("competitor evaluation gate is absent")
    if evaluation.get("truthMayBeServed") is not False:
        raise CompetitorFoundationError("competitor truth must never be served")
    for field in ("minimumPopulation", "minimumMissingAttributeCohort"):
        if type(evaluation.get(field)) is not int or evaluation[field] <= 0:
            raise CompetitorFoundationError(
                f"competitor evaluation {field} is invalid"
            )
    for field in (
        "precisionMin", "recallMin", "falseMatchRateMax",
        "expectedCalibrationErrorMax",
    ):
        try:
            value = float(evaluation[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise CompetitorFoundationError(
                f"competitor evaluation {field} is invalid"
            ) from exc
        if not 0 <= value <= 1:
            raise CompetitorFoundationError(
                f"competitor evaluation {field} must be in [0, 1]"
            )
    return policy


def _attribute_count(value: Any) -> int:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    if isinstance(value, Mapping):
        return sum(item not in (None, "", False) for item in value.values())
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = [item for item in str(value).split("|") if item]
    if isinstance(parsed, Mapping):
        return sum(item not in (None, "", False) for item in parsed.values())
    if isinstance(parsed, list):
        return len(parsed)
    return int(bool(parsed))


def classify_match(
    confidence: float,
    matched_attributes: Any,
    product_attributes: Any,
    policy: Mapping[str, Any],
) -> tuple[str, str | None]:
    """Return the display state and deterministic exclusion reason.

    A numeric score cannot auto-accept without auditable attributes. Two pieces
    of product evidence are required so a title-only match remains reviewable.
    """

    matched_count = _attribute_count(matched_attributes)
    product_count = _attribute_count(product_attributes)
    if matched_count < 2 or product_count < 2:
        return "Needs Review", "MATCH_ATTRIBUTES_INSUFFICIENT"
    thresholds = policy["matchThresholds"]
    if confidence >= float(thresholds["matched"]):
        return "Matched", None
    if confidence >= float(thresholds["needsReview"]):
        return "Needs Review", "MATCH_REVIEW_REQUIRED"
    if confidence >= float(thresholds["rejected"]):
        return "Rejected", "MATCH_CONFIDENCE_REJECTED"
    return "No Match", "NO_MATCH"


def classify_freshness(
    observed_at: datetime | str | pd.Timestamp,
    decision_as_of: datetime | str | pd.Timestamp,
    policy: Mapping[str, Any],
) -> tuple[str, int]:
    observed = pd.Timestamp(observed_at)
    decision = pd.Timestamp(decision_as_of)
    if observed.tzinfo is None:
        observed = observed.tz_localize(UTC)
    else:
        observed = observed.tz_convert(UTC)
    if decision.tzinfo is None:
        decision = decision.tz_localize(UTC)
    else:
        decision = decision.tz_convert(UTC)
    age_days = max(0, int((decision - observed).total_seconds() // 86_400))
    freshness = policy["freshness"]
    if age_days <= int(freshness["freshThroughDays"]):
        return "Fresh", age_days
    if age_days <= int(freshness["nearThresholdThroughDays"]):
        return "Near threshold", age_days
    return "Stale", age_days


def assess_competitor_rows(
    frame: pd.DataFrame,
    *,
    decision_as_of: datetime | str,
    policy: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    required = {
        "match_id", "market_id", "sku_id", "comp_id", "comp_product_id",
        "match_confidence", "matched_attributes", "product_attributes",
        "observed_at", "known_as_of", "price_minor", "currency_code",
        "market_currency_code", "availability_state", "compliance_ok",
        "evidence_class", "use_purpose",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise CompetitorFoundationError(
            "competitor assessment lacks: " + ", ".join(missing)
        )
    allowed_evidence = set(policy["allowedEvidenceClasses"])
    evaluation_record = evaluation or _empty_evaluation(
        "MATCH_EVALUATION_TRUTH_MISSING"
    )
    evaluation_accepted = evaluation_record.get("status") == "accepted"
    evaluation_reason = str(
        evaluation_record.get("firstFailureReason")
        or "MATCH_EVALUATION_NOT_ACCEPTED"
    )
    rows: list[dict[str, Any]] = []
    for source in frame.to_dict("records"):
        reasons: list[str] = []
        try:
            match_status, match_reason = classify_match(
                float(source["match_confidence"]),
                source["matched_attributes"],
                source["product_attributes"],
                policy,
            )
        except (TypeError, ValueError):
            match_status, match_reason = (
                "Needs Review", "MATCH_CONFIDENCE_INVALID"
            )
        try:
            freshness, age_days = classify_freshness(
                source["observed_at"], decision_as_of, policy
            )
        except (TypeError, ValueError, OverflowError):
            freshness, age_days = "Unknown", None
            reasons.append("COMPETITOR_OBSERVATION_INVALID")
        if match_reason:
            reasons.append(match_reason)
        if source["evidence_class"] not in allowed_evidence:
            reasons.append("COMPETITOR_EVIDENCE_UNAPPROVED")
        if freshness == "Stale":
            reasons.append("COMPETITOR_OBSERVATION_STALE")
        if source["currency_code"] != source["market_currency_code"]:
            reasons.append("CURRENCY_MISMATCH")
        if not bool(source["compliance_ok"]):
            reasons.append("COMPETITOR_SOURCE_NONCOMPLIANT")
        try:
            price_invalid = bool(pd.isna(source["price_minor"])) or int(
                source["price_minor"]
            ) <= 0
        except (TypeError, ValueError):
            price_invalid = True
        if price_invalid:
            reasons.append("COMPETITOR_PRICE_INVALID")
        synthetic = source["evidence_class"] == "synthetic"
        if synthetic and source.get("use_purpose") != policy["syntheticDisclosure"]["usePurpose"]:
            reasons.append("SYNTHETIC_DISCLOSURE_MISSING")
        if not evaluation_accepted:
            reasons.append(evaluation_reason)
        reasons = list(dict.fromkeys(reasons))
        eligible = match_status == policy["boundEligibility"]["requiredMatchStatus"] and not reasons
        rows.append(
            {
                **source,
                "match_status": match_status,
                "freshness": freshness,
                "age_days": age_days,
                "synthetic_label": policy["syntheticDisclosure"]["label"] if synthetic else None,
                "bound_eligible": eligible,
                "first_exclusion_reason": reasons[0] if reasons else None,
                "all_exclusion_reasons": json.dumps(reasons, separators=(",", ":")),
            }
        )
    result = pd.DataFrame(
        rows,
        columns=[
            *frame.columns,
            "match_status",
            "freshness",
            "age_days",
            "synthetic_label",
            "bound_eligible",
            "first_exclusion_reason",
            "all_exclusion_reasons",
        ],
    )
    return result.sort_values(
        ["market_id", "sku_id", "comp_id", "comp_product_id", "observed_at"]
    ).reset_index(drop=True)


def build_competitor_foundation(
    curated_database: str | Path,
    *,
    decision_as_of: datetime | str,
    policy: Mapping[str, Any],
    truth_path: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    database = Path(curated_database)
    if not database.is_file():
        raise CompetitorFoundationError(f"curated database is absent: {database}")
    with duckdb.connect(str(database), read_only=True) as connection:
        frame = connection.execute(
            """
            WITH latest_price AS (
                SELECT *
                FROM canonical_data.competitor_prices
                WHERE known_as_of <= ?::TIMESTAMPTZ
                  AND observed_at <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, comp_id, comp_product_id,
                                 geo_scope_type, geo_scope_id
                    ORDER BY observed_at DESC, known_as_of DESC
                ) = 1
            ), market_currency AS (
                SELECT market_id, any_value(currency_code)::VARCHAR AS currency_code
                FROM canonical_data.stores GROUP BY market_id
            )
            SELECT
                m.match_id, m.market_id, m.sku_id, m.comp_id,
                m.comp_product_id, m.match_confidence,
                m.matched_attributes,
                p.attributes AS product_attributes,
                p.title AS competitor_product_title,
                p.brand AS competitor_brand,
                p.model AS competitor_model,
                p.gtin AS competitor_gtin,
                c.name AS competitor_name,
                c.collection_method, c.compliance_ok,
                q.geo_scope_type, q.geo_scope_id,
                q.observed_at, q.known_as_of,
                q.price::BIGINT AS price_minor,
                q.currency_code,
                mc.currency_code AS market_currency_code,
                q.availability_state, q.in_stock_flag, q.promo_flag,
                coalesce(q.evidence_class, p.evidence_class, m.evidence_class)
                    AS evidence_class,
                coalesce(q.derivation_class, p.derivation_class, m.derivation_class)
                    AS derivation_class,
                coalesce(q.use_purpose, p.use_purpose, m.use_purpose)
                    AS use_purpose,
                coalesce(q.generation_method, p.generation_method,
                         m.generation_method) AS generation_method
            FROM canonical_data.competitor_matches AS m
            JOIN canonical_data.competitor_products AS p
              USING (market_id, comp_id, comp_product_id)
            JOIN canonical_data.competitors AS c USING (market_id, comp_id)
            JOIN latest_price AS q USING (market_id, comp_id, comp_product_id)
            JOIN market_currency AS mc USING (market_id)
            ORDER BY m.market_id, m.sku_id, m.comp_id, m.comp_product_id,
                     q.geo_scope_type, q.geo_scope_id
            """,
            [decision_as_of, decision_as_of],
        ).fetch_df()
    evaluation = evaluate_competitor_matcher(
        truth_path, served_matches=frame, policy=policy
    )
    assessed = assess_competitor_rows(
        frame,
        decision_as_of=decision_as_of,
        policy=policy,
        evaluation=evaluation,
    )
    eligible = assessed[assessed["bound_eligible"]].copy()
    if eligible.empty:
        bounds = pd.DataFrame(
            columns=[
                "market_id", "sku_id", "geo_scope_type", "geo_scope_id",
                "competitor_upper_bound_minor", "currency_code", "match_id",
                "comp_id", "comp_product_id", "observed_at", "known_as_of",
                "evidence_class", "synthetic_label",
            ]
        )
    else:
        chosen = eligible.sort_values(
            ["market_id", "sku_id", "geo_scope_type", "geo_scope_id",
             "price_minor", "match_id"]
        ).groupby(
            ["market_id", "sku_id", "geo_scope_type", "geo_scope_id"],
            sort=True,
            dropna=False,
            as_index=False,
        ).first()
        bounds = chosen[
            [
                "market_id", "sku_id", "geo_scope_type", "geo_scope_id",
                "price_minor", "currency_code", "match_id", "comp_id",
                "comp_product_id", "observed_at", "known_as_of",
                "evidence_class", "synthetic_label",
            ]
        ].rename(columns={"price_minor": "competitor_upper_bound_minor"})
    return assessed, bounds, evaluation


__all__ = [
    "CompetitorFoundationError", "assess_competitor_rows",
    "build_competitor_foundation", "classify_freshness", "classify_match",
    "evaluate_competitor_matcher", "load_competitor_policy",
]
