"""Decision-60 forecast exception and per-series quality classifications."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pandas as pd

from retail_contracts.fingerprint import (
    canonical_decimal_string,
    semantic_fingerprint,
)

POLICY_SCHEMA_VERSION: Final[str] = (
    "retail-forecast-classification-policy/v1"
)
SERIES_COLUMNS: Final[tuple[str, ...]] = (
    "sku_id",
    "store_id",
    "channel_id",
)
QUALITY_INPUT_COLUMNS: Final[tuple[str, ...]] = (
    "canonical_key_complete",
    "core_feature_missing_share",
    "latest_actual_age_days",
    "observation_coverage_13w",
    "reconciliation_passed",
    "source_quality_critical_count",
    "source_quality_warning_count",
)
EXCEPTION_INPUT_COLUMNS: Final[tuple[str, ...]] = (
    "yhat_p50",
    "yhat_p90",
    "ma13_baseline",
    "history_weeks",
    "zero_share_52w",
    "promotion_plan_available",
    "planned_promotion_uplift_pct",
    "forecast_uplift_vs_ma13_pct",
)
EXCEPTION_CLASSES: Final[tuple[str, ...]] = (
    "high_under_forecast_risk",
    "high_over_forecast_risk",
    "new_product_sparse_history",
    "promotion_uplift_conflict",
    "data_quality_exception",
)


class ClassificationPolicyError(RuntimeError):
    """Decision #60 is missing, malformed, or applied to invalid inputs."""


def _default_policy_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "contracts"
        / "ml"
        / "forecast-classification-policy.json"
    )


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decimal(value: Any, *, label: str) -> Decimal:
    if value is None or pd.isna(value):
        raise ClassificationPolicyError(f"{label} cannot be null")
    try:
        result = Decimal(str(value))
    except (ValueError, ArithmeticError) as exc:
        raise ClassificationPolicyError(f"{label} must be numeric") from exc
    if not result.is_finite():
        raise ClassificationPolicyError(f"{label} must be finite")
    return result


def _integer(value: Any, *, label: str) -> int:
    decimal = _decimal(value, label=label)
    integral = decimal.to_integral_value()
    if decimal != integral:
        raise ClassificationPolicyError(f"{label} must be an integer")
    return int(integral)


def _boolean(value: Any, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if type(value).__name__ == "bool_":
        return bool(value)
    raise ClassificationPolicyError(f"{label} must be boolean")


def _recorded_decimal(value: Decimal) -> str:
    return canonical_decimal_string(value)


def _verify_section(section: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise ClassificationPolicyError(f"{label} policy must be an object")
    recorded = section.get("semanticFingerprint")
    payload = dict(section)
    payload.pop("semanticFingerprint", None)
    recomputed = semantic_fingerprint(payload, volatile_pointers=())
    if recorded != recomputed:
        raise ClassificationPolicyError(
            f"{label} policy fingerprint mismatch"
        )
    if not isinstance(section.get("policyId"), str) or not section["policyId"]:
        raise ClassificationPolicyError(f"{label} policyId is required")
    return section


@dataclass(frozen=True)
class ClassificationPolicy:
    document: dict[str, Any]
    exceptions: dict[str, Any]
    data_quality: dict[str, Any]

    def bindings(self) -> dict[str, dict[str, str]]:
        return {
            "exceptions": {
                "policyId": self.exceptions["policyId"],
                "semanticFingerprint": self.exceptions[
                    "semanticFingerprint"
                ],
            },
            "dataQuality": {
                "policyId": self.data_quality["policyId"],
                "semanticFingerprint": self.data_quality[
                    "semanticFingerprint"
                ],
            },
        }


def load_classification_policy(
    path: str | Path | None = None,
) -> ClassificationPolicy:
    policy_path = Path(path) if path is not None else _default_policy_path()
    try:
        document = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ClassificationPolicyError(
            f"cannot load classification policy {policy_path}: {exc}"
        ) from exc
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != POLICY_SCHEMA_VERSION
        or document.get("decisionId") != 60
        or set(document) != {
            "schemaVersion",
            "decisionId",
            "exceptions",
            "dataQuality",
        }
    ):
        raise ClassificationPolicyError(
            "classification policy envelope is invalid"
        )
    exceptions = _verify_section(document["exceptions"], label="exceptions")
    quality = _verify_section(document["dataQuality"], label="dataQuality")
    if set(exceptions.get("classes", {})) != set(EXCEPTION_CLASSES):
        raise ClassificationPolicyError(
            "exception class inventory differs from decision #60"
        )
    if quality.get("reduction", {}).get("precedence") != [
        "Issue",
        "Watch",
        "Good",
    ]:
        raise ClassificationPolicyError(
            "quality reduction precedence differs from decision #60"
        )
    return ClassificationPolicy(document, exceptions, quality)


def _quality_result(
    row: pd.Series | dict[str, Any],
    policy: ClassificationPolicy,
    *,
    decision_as_of: str,
) -> tuple[str, str]:
    missing_share = _decimal(
        row["core_feature_missing_share"],
        label="core_feature_missing_share",
    )
    actual_age = _integer(
        row["latest_actual_age_days"],
        label="latest_actual_age_days",
    )
    coverage = _decimal(
        row["observation_coverage_13w"],
        label="observation_coverage_13w",
    )
    critical = _integer(
        row["source_quality_critical_count"],
        label="source_quality_critical_count",
    )
    warnings = _integer(
        row["source_quality_warning_count"],
        label="source_quality_warning_count",
    )
    key_complete = _boolean(
        row["canonical_key_complete"],
        label="canonical_key_complete",
    )
    reconciliation = _boolean(
        row["reconciliation_passed"],
        label="reconciliation_passed",
    )
    if (
        missing_share < 0
        or coverage < 0
        or coverage > 1
        or actual_age < 0
        or critical < 0
        or warnings < 0
    ):
        raise ClassificationPolicyError(
            "quality battery inputs are outside their valid domain"
        )

    checks: dict[str, dict[str, Any]] = {}

    def record(name: str, observed: Any, outcome: str) -> None:
        checks[name] = {"observed": observed, "outcome": outcome}

    record(
        "canonical_key_complete",
        key_complete,
        "Issue" if not key_complete else "Good",
    )
    record(
        "reconciliation_passed",
        reconciliation,
        "Issue" if not reconciliation else "Good",
    )
    record(
        "source_quality_critical_count",
        critical,
        "Issue" if critical > 0 else "Good",
    )
    record(
        "source_quality_warning_count",
        warnings,
        "Watch" if warnings > 0 else "Good",
    )
    record(
        "core_feature_missing_share",
        _recorded_decimal(missing_share),
        (
            "Issue"
            if missing_share > Decimal("0.20")
            else "Watch"
            if missing_share > Decimal("0.05")
            else "Good"
        ),
    )
    record(
        "latest_actual_age_days",
        actual_age,
        "Issue" if actual_age > 21 else "Watch" if actual_age > 14 else "Good",
    )
    record(
        "observation_coverage_13w",
        _recorded_decimal(coverage),
        (
            "Issue"
            if coverage < Decimal("0.75")
            else "Watch"
            if coverage < Decimal("0.90")
            else "Good"
        ),
    )
    outcomes = {check["outcome"] for check in checks.values()}
    quality_class = (
        "Issue" if "Issue" in outcomes else "Watch" if "Watch" in outcomes else "Good"
    )
    evidence = _canonical_json(
        {
            "checks": checks,
            "decision_as_of": decision_as_of,
            "policy_id": policy.data_quality["policyId"],
        }
    )
    return quality_class, evidence


def _exception_results(
    row: pd.Series,
    policy: ClassificationPolicy,
    *,
    decision_as_of: str,
    quality_class: str,
) -> list[dict[str, Any]]:
    p50 = _decimal(row["yhat_p50"], label="yhat_p50")
    p90 = _decimal(row["yhat_p90"], label="yhat_p90")
    ma13 = _decimal(row["ma13_baseline"], label="ma13_baseline")
    history_weeks = _integer(row["history_weeks"], label="history_weeks")
    zero_share = _decimal(row["zero_share_52w"], label="zero_share_52w")
    promotion_available = _boolean(
        row["promotion_plan_available"],
        label="promotion_plan_available",
    )
    planned_uplift = _decimal(
        row["planned_promotion_uplift_pct"],
        label="planned_promotion_uplift_pct",
    )
    forecast_uplift = _decimal(
        row["forecast_uplift_vs_ma13_pct"],
        label="forecast_uplift_vs_ma13_pct",
    )
    if (
        p50 < 0
        or p90 < p50
        or ma13 < 0
        or history_weeks < 0
        or zero_share < 0
        or zero_share > 1
    ):
        raise ClassificationPolicyError(
            "exception inputs are outside their valid domain"
        )

    rows: list[dict[str, Any]] = []

    def emit(
        exception_class: str,
        severity: str,
        observed: dict[str, Any],
    ) -> None:
        rule = policy.exceptions["classes"][exception_class]
        rows.append(
            {
                "exception_class": exception_class,
                "severity": severity,
                "status": "open",
                "threshold": _canonical_json(rule["thresholds"]),
                "evidence": _canonical_json(
                    {
                        "decision_as_of": decision_as_of,
                        "observed": observed,
                        "policy_id": policy.exceptions["policyId"],
                        "rule_id": exception_class,
                        "thresholds": rule["thresholds"],
                    }
                ),
                "policy_id": policy.exceptions["policyId"],
                "policy_semantic_fingerprint": policy.exceptions[
                    "semanticFingerprint"
                ],
            }
        )

    upper_gap = p90 - p50
    upper_ratio = upper_gap / max(p50, Decimal(1))
    if upper_gap >= 5 and upper_ratio >= Decimal("0.50"):
        emit(
            "high_under_forecast_risk",
            "high",
            {
                "upper_gap_ratio": _recorded_decimal(upper_ratio),
                "upper_gap_units": _recorded_decimal(upper_gap),
                "yhat_p50": _recorded_decimal(p50),
                "yhat_p90": _recorded_decimal(p90),
            },
        )

    over_gap = p50 - ma13
    over_ratio = over_gap / max(ma13, Decimal(1))
    if over_gap >= 5 and over_ratio >= Decimal("0.50"):
        emit(
            "high_over_forecast_risk",
            "high",
            {
                "ma13_baseline": _recorded_decimal(ma13),
                "over_gap_ratio": _recorded_decimal(over_ratio),
                "over_gap_units": _recorded_decimal(over_gap),
                "yhat_p50": _recorded_decimal(p50),
            },
        )

    if history_weeks < 26 or zero_share > Decimal("0.60"):
        sparse_severity = (
            "high"
            if history_weeks < 13 or zero_share > Decimal("0.80")
            else "medium"
        )
        emit(
            "new_product_sparse_history",
            sparse_severity,
            {
                "history_weeks": history_weeks,
                "zero_share_52w": _recorded_decimal(zero_share),
            },
        )

    uplift_shortfall = planned_uplift - forecast_uplift
    if (
        promotion_available
        and planned_uplift >= Decimal("0.10")
        and uplift_shortfall >= Decimal("0.10")
    ):
        emit(
            "promotion_uplift_conflict",
            "medium",
            {
                "forecast_uplift_vs_ma13_pct": _recorded_decimal(
                    forecast_uplift
                ),
                "planned_promotion_uplift_pct": _recorded_decimal(
                    planned_uplift
                ),
                "promotion_plan_available": True,
                "uplift_shortfall_pct": _recorded_decimal(uplift_shortfall),
            },
        )

    if quality_class == "Issue":
        emit(
            "data_quality_exception",
            "high",
            {"data_quality_class": quality_class},
        )
    return rows


def classify_current_cycle(
    frame: pd.DataFrame,
    *,
    decision_as_of: datetime,
    policy: ClassificationPolicy | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, dict[str, str]]]:
    """Classify one row per current-cycle SeriesKey under decision #60."""

    if decision_as_of.tzinfo is None:
        raise ClassificationPolicyError(
            "decision_as_of must be timezone-aware"
        )
    active_policy = policy or load_classification_policy()
    required = {
        *SERIES_COLUMNS,
        *QUALITY_INPUT_COLUMNS,
        *EXCEPTION_INPUT_COLUMNS,
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ClassificationPolicyError(
            "current-cycle classification inputs are missing: "
            + ", ".join(missing)
        )
    duplicate = frame.duplicated(list(SERIES_COLUMNS), keep=False)
    if duplicate.any():
        raise ClassificationPolicyError(
            "current-cycle classification requires one row per SeriesKey"
        )
    cutoff = decision_as_of.isoformat().replace("+00:00", "Z")
    quality_rows: list[dict[str, Any]] = []
    exception_rows: list[dict[str, Any]] = []
    for _, row in frame.sort_values(list(SERIES_COLUMNS)).iterrows():
        series = {column: str(row[column]) for column in SERIES_COLUMNS}
        if any(not value for value in series.values()):
            raise ClassificationPolicyError("SeriesKey fields cannot be empty")
        quality_class, quality_evidence = _quality_result(
            row,
            active_policy,
            decision_as_of=cutoff,
        )
        quality_rows.append(
            {
                **series,
                "data_quality_class": quality_class,
                "evidence": quality_evidence,
                "policy_id": active_policy.data_quality["policyId"],
                "policy_semantic_fingerprint": active_policy.data_quality[
                    "semanticFingerprint"
                ],
            }
        )
        for exception in _exception_results(
            row,
            active_policy,
            decision_as_of=cutoff,
            quality_class=quality_class,
        ):
            exception_rows.append({**series, **exception})
    exception_columns = [
        *SERIES_COLUMNS,
        "exception_class",
        "severity",
        "status",
        "threshold",
        "evidence",
        "policy_id",
        "policy_semantic_fingerprint",
    ]
    quality_columns = [
        *SERIES_COLUMNS,
        "data_quality_class",
        "evidence",
        "policy_id",
        "policy_semantic_fingerprint",
    ]
    return (
        pd.DataFrame(exception_rows, columns=exception_columns),
        pd.DataFrame(quality_rows, columns=quality_columns),
        active_policy.bindings(),
    )


__all__ = [
    "ClassificationPolicy",
    "ClassificationPolicyError",
    "classify_current_cycle",
    "load_classification_policy",
]
