"""Immutable pricing-intelligence bundle publication and independent verification."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Mapping

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker

from retail_contracts.fingerprint import semantic_fingerprint
from retail_ml.publish.run_artifacts import (
    _frame_semantic_fingerprint,
    _json_semantic_fingerprint,
)
from retail_ml.pricing.selection import (
    PricingSelectionError,
    build_selection_intent,
    validate_selection_intent,
)


BUNDLE_SCHEMA: Final[str] = "retail-pricing-intelligence-bundle/v1"
ARTIFACT_SCHEMAS: Final[dict[str, str]] = {
    "pricing_panel": "retail-pricing-panel/v1",
    "response_assessments": "retail-price-response-assessments/v1",
    "price_candidates": "retail-price-candidates/v1",
    "price_recommendations": "retail-price-recommendations/v1",
    "competitor_assessments": "retail-competitor-assessments/v1",
    "competitor_bounds": "retail-competitor-bounds/v1",
    "competitor_evaluation": "retail-competitor-evaluation/v1",
    "promotion_protection": "retail-promotion-protection-rows/v1",
    "promotion_disposition": "retail-promotion-package-disposition/v1",
}
JSON_ARTIFACTS: Final[frozenset[str]] = frozenset(
    {"competitor_evaluation", "promotion_disposition"}
)
MANIFEST_VOLATILE_POINTERS: Final[tuple[str, ...]] = (
    "/bundleId",
    "/createdAt",
    *tuple(
        f"/artifacts/{name}/{field}"
        for name in ARTIFACT_SCHEMAS
        for field in ("path", "bytes", "sha256")
    ),
)
BUNDLE_SCHEMA_PATH: Final[Path] = (
    Path(__file__).resolve().parents[4] / "contracts/pricing/bundle.schema.json"
)
ARTIFACT_CONTRACT_PATH: Final[Path] = (
    Path(__file__).resolve().parents[4] / "contracts/pricing/artifacts.schema.json"
)
SELECTION_INTENT_SCHEMA_PATH: Final[Path] = (
    Path(__file__).resolve().parents[4]
    / "contracts/pricing/result-selection-intent.schema.json"
)
POLICY_PATHS: Final[dict[str, Path]] = {
    "response": Path(__file__).resolve().parents[4]
    / "contracts/pricing/response-evaluation.json",
    "pricing": Path(__file__).resolve().parents[4]
    / "contracts/guardrails/pricing_rules.yaml",
    "competitor": Path(__file__).resolve().parents[4]
    / "contracts/pricing/competitor-policy.json",
    "promotion": Path(__file__).resolve().parents[4]
    / "contracts/pricing/promotion-protection-policy.json",
    "artifacts": ARTIFACT_CONTRACT_PATH,
}


class PricingBundleError(RuntimeError):
    """A pricing bundle is incomplete, mutable, or semantically invalid."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(path: Path, document: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _canonical_fingerprint(document: Mapping[str, Any]) -> str:
    payload = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _selection_evidence(
    *,
    lineage: Mapping[str, Any],
    policies: Mapping[str, str],
    capabilities: Mapping[str, Any],
    artifacts: Mapping[str, Any],
) -> dict[str, str]:
    capability = capabilities.get("priceRevenue")
    if not isinstance(capability, Mapping):
        raise PricingBundleError("priceRevenue capability evidence is absent")
    required_lineage = (
        "publicationSemanticFingerprint",
        "readinessReportFingerprint",
        "inputAuthorityId",
    )
    missing_lineage = [name for name in required_lineage if not lineage.get(name)]
    if missing_lineage:
        raise PricingBundleError(
            "pricing lineage lacks selection evidence: "
            + ", ".join(missing_lineage)
        )
    for name in ("response_assessments", "price_recommendations"):
        record = artifacts.get(name)
        if not isinstance(record, Mapping) or not record.get("semanticFingerprint"):
            raise PricingBundleError(f"{name} semantic evidence is absent")
    return {
        "sourcePublicationFingerprint": str(
            lineage["publicationSemanticFingerprint"]
        ),
        "readinessReportFingerprint": str(lineage["readinessReportFingerprint"]),
        "inputAuthorityId": str(lineage["inputAuthorityId"]),
        "responsePolicySha256": str(policies["response"]),
        "pricingPolicySha256": str(policies["pricing"]),
        "artifactContractSha256": str(policies["artifacts"]),
        "responseAssessmentsFingerprint": str(
            artifacts["response_assessments"]["semanticFingerprint"]
        ),
        "recommendationsFingerprint": str(
            artifacts["price_recommendations"]["semanticFingerprint"]
        ),
        "priceRevenueCapabilityFingerprint": _canonical_fingerprint(capability),
    }


def _prospective_selection(
    *,
    bundle_kind: str,
    selection_scope: Mapping[str, str],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    required = {"retailerId", "tenantId", "environment", "audience"}
    if set(selection_scope) != required:
        raise PricingBundleError(
            "result-selection scope must contain exactly "
            + ", ".join(sorted(required))
        )
    expected = {
        "response_rich": ("local", "response_rich_local"),
        "evidence_sparse": ("dev", "pricing_evidence_sparse_dev"),
    }[bundle_kind]
    actual = (selection_scope["environment"], selection_scope["audience"])
    if actual != expected:
        raise PricingBundleError(
            f"{bundle_kind} result-selection scope must be {expected[0]}/{expected[1]}"
        )
    intent = build_selection_intent(
        retailer_id=selection_scope["retailerId"],
        tenant_id=selection_scope["tenantId"],
        environment=selection_scope["environment"],
        audience=selection_scope["audience"],
        evidence=evidence,
    )
    try:
        return validate_selection_intent(intent, SELECTION_INTENT_SCHEMA_PATH)
    except PricingSelectionError as exc:
        raise PricingBundleError(
            f"prospective result-selection intent is invalid: {exc}"
        ) from exc


def _validate_manifest(document: Mapping[str, Any]) -> None:
    schema = json.loads(BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            document
        ),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].absolute_path)
        raise PricingBundleError(
            f"pricing manifest schema violation at {location}: {errors[0].message}"
        )


def _artifact_contract() -> dict[str, Any]:
    contract = json.loads(ARTIFACT_CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract.get("schemaVersion") != "retail-pricing-artifact-contract/v1":
        raise PricingBundleError("unsupported pricing artifact contract")
    exclusions = contract.get("semanticIdentityExcludes")
    if exclusions != ["/contractFingerprint"]:
        raise PricingBundleError("pricing artifact identity exclusions changed")
    fingerprint = semantic_fingerprint(
        contract, volatile_pointers=tuple(exclusions)
    )
    if contract.get("contractFingerprint") != fingerprint:
        raise PricingBundleError("pricing artifact contract fingerprint mismatch")
    definitions = contract.get("artifacts")
    if not isinstance(definitions, dict) or set(definitions) != set(ARTIFACT_SCHEMAS):
        raise PricingBundleError("pricing artifact contract inventory changed")
    for name, schema in ARTIFACT_SCHEMAS.items():
        if definitions[name].get("schemaVersion") != schema:
            raise PricingBundleError(f"{name} contract schemaVersion differs")
    return contract


def _validate_artifacts(
    artifacts: Mapping[str, pd.DataFrame | Mapping[str, Any]]
) -> None:
    contract = _artifact_contract()
    definitions = contract["artifacts"]
    for name, definition in definitions.items():
        value = artifacts[name]
        if name in JSON_ARTIFACTS:
            if not isinstance(value, Mapping):
                raise PricingBundleError(f"{name} must be a JSON object")
            missing = sorted(
                set(definition["requiredProperties"]) - set(value)
            )
            if missing:
                raise PricingBundleError(
                    f"{name} lacks required properties: {', '.join(missing)}"
                )
            continue
        if not isinstance(value, pd.DataFrame):
            raise PricingBundleError(f"{name} must be a dataframe")
        missing = sorted(set(definition["requiredColumns"]) - set(value.columns))
        if missing:
            raise PricingBundleError(
                f"{name} lacks required columns: {', '.join(missing)}"
            )
        key = list(definition["primaryKey"])
        if not value.empty:
            if value[key].isna().any(axis=None):
                raise PricingBundleError(f"{name} primary key contains nulls")
            if value.duplicated(key).any():
                raise PricingBundleError(f"{name} primary key is not unique")


def _validate_policy_hashes(policies: Mapping[str, str]) -> None:
    if set(policies) != set(POLICY_PATHS):
        raise PricingBundleError("pricing policy inventory changed")
    mismatches = [
        name
        for name, path in POLICY_PATHS.items()
        if policies.get(name) != _sha256_file(path)
    ]
    if mismatches:
        raise PricingBundleError(
            "pricing policy hashes differ: " + ", ".join(sorted(mismatches))
        )


def _verify_response_acceptance(responses: pd.DataFrame) -> None:
    policy = json.loads(POLICY_PATHS["response"].read_text(encoding="utf-8"))
    gates = policy["strictGates"]
    coverage_gates = policy["coverageGates"]
    candidates = {
        str(item["id"]): str(item["shrinkage"])
        for item in policy["originRules"]["candidateConfigurations"]
    }
    selection_documents: list[dict[str, Any]] = []
    for value in responses["candidate_selection_diagnostics"].dropna().unique():
        try:
            selection = json.loads(str(value))
        except json.JSONDecodeError as exc:
            raise PricingBundleError(
                "response candidate-selection evidence is not JSON"
            ) from exc
        _require(
            selection.get("developmentOrigins") == list(range(1, 9))
            and selection.get("confirmationOriginsRead") == [],
            "response candidate selection read outside development origins",
        )
        scores = selection.get("candidateScores") or []
        _require(
            {str(item.get("configurationId")) for item in scores} == set(candidates),
            "response candidate-selection registry differs from policy",
        )
        selected = selection.get("selectedConfigurationId")
        _require(
            selected is None
            or (
                selected in candidates
                and selection.get("selectedShrinkage") == candidates[selected]
            ),
            "response selected configuration differs from policy",
        )
        evaluable = [
            item
            for item in scores
            if item.get("meanDeviance") is not None
            and item.get("meanDevianceImprovement") is not None
            and item.get("safeSignRate") is not None
        ]
        recomputed = min(
            evaluable,
            key=lambda item: (
                -float(item["meanDevianceImprovement"]),
                -float(item["safeSignRate"]),
                float(item["meanDeviance"]),
                str(item["configurationId"]),
            ),
        ) if evaluable else None
        _require(
            selected
            == (str(recomputed["configurationId"]) if recomputed else None),
            "response selected configuration differs from recomputed development ranking",
        )
        selection_documents.append(selection)
    _require(
        len(selection_documents) <= 1,
        "response rows disagree on the frozen candidate selection",
    )
    if selection_documents:
        selected = selection_documents[0].get("selectedConfigurationId")
        shrinkage = selection_documents[0].get("selectedShrinkage")
        _require(
            set(responses["selected_configuration_id"].dropna().astype(str))
            <= ({str(selected)} if selected is not None else set()),
            "response row configuration differs from selection evidence",
        )
        _require(
            set(responses["selected_shrinkage"].dropna().astype(str))
            <= ({str(shrinkage)} if shrinkage is not None else set()),
            "response row shrinkage differs from selection evidence",
        )
    for encoded in responses["origin_diagnostics"]:
        try:
            origins = json.loads(str(encoded))
        except json.JSONDecodeError as exc:
            raise PricingBundleError("response origin evidence is not JSON") from exc
        for origin in origins:
            if origin.get("status") == "scored":
                _require(
                    origin.get("baselineSpecification")
                    == "same_controls_without_log_price",
                    "response origin used the wrong baseline",
                )
        if len(origins) > 0:
            _require(
                len(origins) == 13
                and [int(origin.get("index", 0)) for origin in origins]
                == list(range(1, 14)),
                "response origin registry is not exactly 1-13",
            )

    beta = pd.to_numeric(responses["shrunk_beta"], errors="coerce")
    confidence = pd.to_numeric(responses["confidence"], errors="coerce")
    iqr_ratio = pd.to_numeric(responses["resample_iqr_ratio"], errors="coerce")
    draws = pd.to_numeric(responses["valid_resample_draws"], errors="coerce")
    confirmation = pd.to_numeric(
        responses["confirmation_improvement"], errors="coerce"
    )
    strict = (
        beta.notna()
        & (beta < 0)
        & (beta.abs() > float(gates["betaMinAbs"]))
        & (beta.abs() < float(gates["betaMaxAbs"]))
        & (confidence >= float(gates["signConsistencyMin"]))
        & (iqr_ratio < float(gates["resampleIqrRatioMax"]))
        & (draws >= int(policy["resampling"]["minimumValidDraws"]))
        & (confirmation > float(gates["holdoutImprovementMin"]))
    )
    for _, indices in responses.groupby(
        ["market_id", "department_id"], sort=True, dropna=False
    ).groups.items():
        group = responses.loc[indices]
        passing = group.loc[strict.loc[indices]]
        coverage = len(passing) / max(len(group), 1)
        pairs = len(
            set(zip(passing["sku_id"].astype(str), passing["store_id"].astype(str)))
        )
        enabled = (
            coverage >= float(coverage_gates["departmentCoverageMin"])
            and pairs >= int(coverage_gates["departmentMinDistinctSkuStorePairs"])
        )
        _require(
            np.isclose(
                pd.to_numeric(group["department_accepted_coverage"]).to_numpy(),
                coverage,
            ).all(),
            "department accepted coverage was not independently reproduced",
        )
        _require(
            (pd.to_numeric(group["department_distinct_sku_store_pairs"]) == pairs).all(),
            "department distinct SKU/store count was not independently reproduced",
        )
        _require(
            (group["department_enabled"].astype(bool) == enabled).all(),
            "department enablement was not independently reproduced",
        )
        expected_accepted = strict.loc[indices] & enabled
        recorded_accepted = group["disposition"].astype(str) == "accepted"
        _require(
            np.array_equal(recorded_accepted.to_numpy(), expected_accepted.to_numpy()),
            "response acceptance differs from independently recomputed gates",
        )


def _verify_competitor_evaluation(
    evaluation: Mapping[str, Any], assessments: pd.DataFrame
) -> None:
    policy = __import__("json").loads(
        POLICY_PATHS["competitor"].read_text(encoding="utf-8")
    )
    gate = policy["evaluationGate"]
    _require(
        evaluation.get("truthMayBeServed") is False,
        "competitor evaluation permits truth serving",
    )
    _require(
        int(evaluation.get("developmentEvaluationOverlap", -1)) == 0
        and int(evaluation.get("servedTruthPairOverlap", -1)) == 0,
        "competitor evaluation truth is not disjoint",
    )
    tp = int(evaluation.get("truePositive", 0))
    fp = int(evaluation.get("falsePositive", 0))
    tn = int(evaluation.get("trueNegative", 0))
    fn = int(evaluation.get("falseNegative", 0))
    population = int(evaluation.get("evaluationPopulation", 0))
    _require(tp + fp + tn + fn == population, "competitor confusion counts disagree")
    positive = tp + fn
    negative = tn + fp
    _require(
        int(evaluation.get("truthPositiveCount", -1)) == positive
        and int(evaluation.get("truthNegativeCount", -1)) == negative,
        "competitor truth-label counts disagree",
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / positive if positive else 0.0
    false_match_rate = fp / negative if negative else 0.0
    for field, value in (
        ("precision", precision),
        ("recall", recall),
        ("falseMatchRate", false_match_rate),
    ):
        recorded = evaluation.get(field)
        if population:
            _require(
                recorded is not None and np.isclose(float(recorded), value),
                f"competitor {field} differs from confusion counts",
            )
    bins = evaluation.get("calibrationBins") or []
    _require(isinstance(bins, list), "competitor calibration bins are invalid")
    if population:
        _require(
            sum(int(row.get("count", 0)) for row in bins) == population,
            "competitor calibration population disagrees",
        )
        ece = sum(
            int(row["count"])
            * abs(float(row["meanConfidence"]) - float(row["positiveRate"]))
            for row in bins
        ) / population
        _require(
            evaluation.get("expectedCalibrationError") is not None
            and np.isclose(float(evaluation["expectedCalibrationError"]), ece),
            "competitor calibration error differs from bins",
        )
    else:
        ece = 1.0
    exception_reasons = evaluation.get("recordExceptionReasons") or {}
    _require(
        isinstance(exception_reasons, Mapping)
        and sum(int(value) for value in exception_reasons.values())
        == int(evaluation.get("recordExceptionCount", -1)),
        "competitor record-exception totals disagree",
    )
    accepted = (
        population >= int(gate["minimumPopulation"])
        and int(evaluation.get("missingAttributeCohort", 0))
        >= int(gate["minimumMissingAttributeCohort"])
        and precision >= float(gate["precisionMin"])
        and recall >= float(gate["recallMin"])
        and false_match_rate <= float(gate["falseMatchRateMax"])
        and ece <= float(gate["expectedCalibrationErrorMax"])
    )
    _require(
        (evaluation.get("status") == "accepted") is accepted,
        "competitor evaluation disposition differs from frozen gates",
    )
    if accepted:
        _require(
            isinstance(evaluation.get("truthSha256"), str)
            and len(str(evaluation["truthSha256"])) == 64
            and evaluation.get("firstFailureReason") is None,
            "accepted competitor evaluation lacks immutable truth identity",
        )
    else:
        _require(
            isinstance(evaluation.get("firstFailureReason"), str)
            and bool(evaluation["firstFailureReason"]),
            "unaccepted competitor evaluation lacks a reason",
        )
        if not assessments.empty:
            _require(
                not assessments["bound_eligible"].astype(bool).any(),
                "unaccepted competitor evaluation produced an eligible bound",
            )


def publish_pricing_bundle(
    destination: str | Path,
    *,
    bundle_kind: str,
    decision_as_of: str,
    artifacts: Mapping[str, pd.DataFrame | Mapping[str, Any]],
    lineage: Mapping[str, Any],
    policies: Mapping[str, str],
    capabilities: Mapping[str, Any],
    selection_scope: Mapping[str, str],
) -> Path:
    if bundle_kind not in {"response_rich", "evidence_sparse"}:
        raise PricingBundleError("bundle kind must be response_rich or evidence_sparse")
    if set(artifacts) != set(ARTIFACT_SCHEMAS):
        raise PricingBundleError("pricing artifacts do not match the frozen inventory")
    _validate_policy_hashes(policies)
    _validate_artifacts(artifacts)
    target = Path(destination).resolve()
    if target.exists():
        raise PricingBundleError(f"pricing bundle already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        object_records: dict[str, Any] = {}
        for name in ARTIFACT_SCHEMAS:
            schema = ARTIFACT_SCHEMAS[name]
            value = artifacts[name]
            if name in JSON_ARTIFACTS:
                if not isinstance(value, Mapping):
                    raise PricingBundleError(f"{name} must be a JSON object")
                document = dict(value)
                if document.get("schemaVersion") != schema:
                    raise PricingBundleError(f"{name} schemaVersion differs")
                path = staging / f"{name}.json"
                _canonical_json(path, document)
                row_count = 1
                artifact_fingerprint = _json_semantic_fingerprint(
                    document, schema_version=schema
                )
            else:
                if not isinstance(value, pd.DataFrame):
                    raise PricingBundleError(f"{name} must be a dataframe")
                frame = value.reset_index(drop=True)
                path = staging / f"{name}.parquet"
                frame.to_parquet(path, index=False, compression="zstd")
                row_count = len(frame)
                artifact_fingerprint = _frame_semantic_fingerprint(
                    frame, schema_version=schema
                )
            object_records[name] = {
                "path": path.name,
                "schemaVersion": schema,
                "rowCount": row_count,
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
                "semanticFingerprint": artifact_fingerprint,
            }
        prospective_selection = _prospective_selection(
            bundle_kind=bundle_kind,
            selection_scope=selection_scope,
            evidence=_selection_evidence(
                lineage=lineage,
                policies=policies,
                capabilities=capabilities,
                artifacts=object_records,
            ),
        )
        manifest: dict[str, Any] = {
            "schemaVersion": BUNDLE_SCHEMA,
            "bundleKind": bundle_kind,
            "bundleId": "pending",
            "createdAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "decisionAsOf": decision_as_of,
            "lineage": dict(lineage),
            "policies": dict(policies),
            "capabilities": dict(capabilities),
            "artifacts": object_records,
            "prospectiveResultSelections": [prospective_selection],
            "fingerprintContract": {
                "schemaVersion": "semantic-fingerprint/v1",
                "volatilePointers": list(MANIFEST_VOLATILE_POINTERS),
            },
        }
        identity = semantic_fingerprint(
            manifest, volatile_pointers=MANIFEST_VOLATILE_POINTERS
        )
        manifest["bundleId"] = "pb_" + identity[:20]
        manifest["semanticFingerprint"] = identity
        _validate_manifest(manifest)
        _canonical_json(staging / "pricing-manifest.json", manifest)
        os.replace(staging, target)
    except BaseException:
        # Staging contains only newly produced bytes and is never an adopted bundle.
        for child in staging.iterdir() if staging.exists() else ():
            child.unlink(missing_ok=True)
        staging.rmdir()
        raise
    return target


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PricingBundleError(message)


def verify_pricing_bundle(path: str | Path) -> dict[str, Any]:
    """Recompute closure and safety invariants without producer gate functions."""

    root = Path(path).resolve()
    _require(root.is_dir(), f"pricing bundle is absent: {root}")
    manifest_path = root / "pricing-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(manifest)
    _require(manifest.get("schemaVersion") == BUNDLE_SCHEMA, "unsupported bundle schema")
    _require(
        (manifest.get("fingerprintContract") or {}).get("volatilePointers")
        == list(MANIFEST_VOLATILE_POINTERS),
        "bundle fingerprint contract changed",
    )
    artifacts = manifest.get("artifacts")
    _require(isinstance(artifacts, dict) and set(artifacts) == set(ARTIFACT_SCHEMAS), "bundle object inventory changed")
    payload = dict(manifest)
    recorded = payload.pop("semanticFingerprint", None)
    recomputed = semantic_fingerprint(payload, volatile_pointers=MANIFEST_VOLATILE_POINTERS)
    _require(recorded == recomputed, "bundle semantic fingerprint mismatch")
    _require(manifest.get("bundleId") == "pb_" + recomputed[:20], "bundleId mismatch")
    loaded: dict[str, Any] = {}
    for name, schema in ARTIFACT_SCHEMAS.items():
        record = artifacts[name]
        filename = record.get("path")
        _require(isinstance(filename, str) and Path(filename).name == filename, f"unsafe {name} path")
        object_path = root / filename
        _require(object_path.is_file(), f"missing {name}")
        _require(object_path.stat().st_size == record.get("bytes"), f"{name} byte count mismatch")
        _require(_sha256_file(object_path) == record.get("sha256"), f"{name} checksum mismatch")
        _require(record.get("schemaVersion") == schema, f"{name} schema mismatch")
        if name in JSON_ARTIFACTS:
            value = json.loads(object_path.read_text(encoding="utf-8"))
            semantic = _json_semantic_fingerprint(value, schema_version=schema)
            count = 1
        else:
            value = pd.read_parquet(object_path)
            semantic = _frame_semantic_fingerprint(value, schema_version=schema)
            count = len(value)
        _require(count == record.get("rowCount"), f"{name} row count mismatch")
        _require(semantic == record.get("semanticFingerprint"), f"{name} semantic fingerprint mismatch")
        loaded[name] = value
    _validate_policy_hashes(manifest.get("policies") or {})
    _validate_artifacts(loaded)
    prospective = manifest.get("prospectiveResultSelections") or []
    _require(
        isinstance(prospective, list) and len(prospective) == 1,
        "bundle must bind exactly one prospective price_revenue selection",
    )
    try:
        intent = validate_selection_intent(
            prospective[0], SELECTION_INTENT_SCHEMA_PATH
        )
    except PricingSelectionError as exc:
        raise PricingBundleError(
            f"prospective result-selection intent is invalid: {exc}"
        ) from exc
    expected_intent = _prospective_selection(
        bundle_kind=str(manifest["bundleKind"]),
        selection_scope={
            key: str(intent[key])
            for key in ("retailerId", "tenantId", "environment", "audience")
        },
        evidence=_selection_evidence(
            lineage=manifest.get("lineage") or {},
            policies=manifest.get("policies") or {},
            capabilities=manifest.get("capabilities") or {},
            artifacts=artifacts,
        ),
    )
    _require(
        intent == expected_intent,
        "prospective result-selection identity differs from recomputed evidence",
    )
    responses: pd.DataFrame = loaded["response_assessments"]
    _verify_response_acceptance(responses)
    _verify_competitor_evaluation(
        loaded["competitor_evaluation"], loaded["competitor_assessments"]
    )
    accepted = responses[responses.get("disposition", pd.Series(dtype=str)) == "accepted"]
    if not accepted.empty:
        _require((accepted["shrunk_beta"] < 0).all(), "accepted response has non-negative beta")
        _require(((accepted["shrunk_beta"].abs() > 0.3) & (accepted["shrunk_beta"].abs() < 4)).all(), "accepted beta escaped strict magnitude gates")
        _require((accepted["confidence"] >= 0.9).all(), "accepted response escaped sign-consistency gate")
        _require((accepted["valid_resample_draws"] >= 50).all(), "accepted response lacks valid resamples")
        _require((accepted["confirmation_improvement"] > 0).all(), "accepted response failed confirmation holdout")
    recommendations: pd.DataFrame = loaded["price_recommendations"]
    actionable = recommendations[
        (recommendations.get("record_kind") == "recommendation")
        & (recommendations.get("action").isin(["Increase", "Decrease"]))
    ]
    price_revenue = (manifest.get("capabilities") or {}).get("priceRevenue") or {}
    _require(
        price_revenue.get("available") is (not actionable.empty)
        and price_revenue.get("actionableRows") == len(actionable),
        "priceRevenue capability evidence differs from recommendation artifacts",
    )
    if not actionable.empty:
        change = (
            actionable["proposed_price_minor"] / actionable["current_price_minor"] - 1
        ).abs()
        _require((change <= 0.05 + 1e-12).all(), "action exceeds absolute five-percent cap")
        _require(actionable["margin_impact_minor"].isna().equals(actionable["margin_reason_code"].notna()), "margin null/reason pairing differs")
    kind = manifest["bundleKind"]
    if kind == "evidence_sparse":
        _require(accepted.empty, "sparse bundle contains accepted response")
        _require(actionable.empty, "sparse bundle contains actionable recommendation")
    disposition = loaded["promotion_disposition"]
    _require(disposition.get("decisionDisposition") == "not_amended", "promotion decision branch drift")
    _require(disposition.get("packageDisposition") == "negative", "promotion package branch drift")
    return {
        "schemaVersion": "retail-pricing-bundle-verification/v1",
        "bundleId": manifest["bundleId"],
        "manifestSha256": _sha256_file(manifest_path),
        "semanticFingerprint": recorded,
        "passed": True,
        "artifactCount": len(ARTIFACT_SCHEMAS),
        "acceptedResponseRows": len(accepted),
        "actionableRecommendationRows": len(actionable),
        "prospectiveSelectionIds": [str(intent["selectionId"])],
    }


def write_verification_record(bundle: str | Path, destination: str | Path) -> Path:
    record = verify_pricing_bundle(bundle)
    target = Path(destination).resolve()
    if target.exists():
        raise PricingBundleError(f"verification record already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    _canonical_json(temporary, record)
    os.replace(temporary, target)
    return target


__all__ = [
    "ARTIFACT_SCHEMAS", "BUNDLE_SCHEMA", "PricingBundleError",
    "SELECTION_INTENT_SCHEMA_PATH",
    "publish_pricing_bundle", "verify_pricing_bundle", "write_verification_record",
]
