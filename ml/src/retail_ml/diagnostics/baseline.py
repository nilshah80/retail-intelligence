"""PP3-B2 immutable diagnostic baseline (D0).

Publishes sliced additive evidence for a rejected candidate so Track B has a
frozen comparison authority. D0 is diagnostic only: it can never authorize
publication, materialization, activation or serving, and this module refuses to
build one from a run that is not governed by the current authority.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Final, Sequence

import pandas as pd

from retail_ml.models.baselines import metric_for_column
from retail_ml.models.cohorts import (
    COLD_START,
    COLD_START_BASELINE_COLUMN,
    ESTABLISHED,
    assign_cohorts,
    key_fingerprint,
)

BASELINE_SCHEMA_VERSION: Final[str] = "retail-forecast-diagnostic-baseline/v1"
REQUIRED_RECOMPUTATION: Final[str] = (
    "cohorted-seasonal-cold-start-recomputation/v4"
)
HORIZON_CHECKPOINTS: Final[tuple[int, ...]] = (1, 4, 8, 13, 26)
DEVELOPMENT_ORIGINS: Final[int] = 8
CONFIRMATION_ORIGINS: Final[int] = 5


class DiagnosticBaselineError(RuntimeError):
    """The run cannot serve as a governed comparison authority."""


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    champion = metric_for_column(frame, "yhat_p50", upper_column="yhat_p90")
    record = champion.as_record()
    return {
        "absErrorSum": record["abs_error_sum"],
        "signedErrorSum": record["signed_error_sum"],
        "actualSum": record["actual_sum"],
        "coverageHits": record["coverage_hits"],
        "n": record["n"],
        "wape": record["wape"],
        "accuracy": record["accuracy"],
        "bias": record["bias"],
        "p90Coverage": record["coverage"],
        "verdict": "insufficient_evidence" if record["actual_sum"] <= 0 else "measured",
    }


def _slice(frame: pd.DataFrame, column: str) -> dict[str, Any]:
    if column not in frame.columns:
        return {}
    return {
        str(value): _metrics(group)
        for value, group in sorted(
            frame.groupby(column, sort=True, observed=True),
            key=lambda item: str(item[0]),
        )
    }


def _horizon_slices(frame: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for checkpoint in HORIZON_CHECKPOINTS:
        exact = frame[frame["horizon"] == checkpoint]
        result[f"h{checkpoint}"] = _metrics(exact)
    return result


def _origin_roles(frame: pd.DataFrame) -> dict[str, Any]:
    origins = sorted(frame["forecast_origin"].unique())
    development = origins[:DEVELOPMENT_ORIGINS]
    confirmation = origins[DEVELOPMENT_ORIGINS:]
    if len(confirmation) != CONFIRMATION_ORIGINS:
        raise DiagnosticBaselineError(
            f"expected {CONFIRMATION_ORIGINS} confirmation origins, "
            f"found {len(confirmation)}"
        )
    return {
        "developmentOrigins": [str(value) for value in development],
        "confirmationOrigins": [str(value) for value in confirmation],
        "development": _metrics(frame[frame["forecast_origin"].isin(development)]),
        "confirmation": _metrics(frame[frame["forecast_origin"].isin(confirmation)]),
    }


def build_diagnostic_baseline(
    acceptance: dict[str, Any],
    run_manifest: dict[str, Any],
    evaluation: pd.DataFrame,
    baselines: pd.DataFrame,
    *,
    authority: str = "D0",
) -> dict[str, Any]:
    """Freeze sliced evidence for one governed run."""

    if authority not in {"C0", "D0"}:
        raise DiagnosticBaselineError(f"unknown authority {authority!r}")
    recomputation = run_manifest.get("modelPolicy", {}).get("acceptanceEvaluation")
    if recomputation != REQUIRED_RECOMPUTATION:
        raise DiagnosticBaselineError(
            "run is not governed by the current comparison authority: "
            f"{recomputation!r}"
        )
    lifecycle = run_manifest.get("lifecycleStatus")
    if authority == "C0" and lifecycle != "accepted":
        raise DiagnosticBaselineError("C0 requires an accepted run")
    if authority == "D0" and lifecycle == "accepted":
        raise DiagnosticBaselineError(
            "an accepted run must be published as C0, not D0"
        )

    from retail_ml.models.cohorts import acceptance_frame
    from retail_ml.publish.run_artifacts import EVALUATION_KEY_COLUMNS

    frame = assign_cohorts(
        acceptance_frame(evaluation, baselines, EVALUATION_KEY_COLUMNS)
    )
    established = frame[frame["cohort"].astype(str).eq(ESTABLISHED)]
    cold_start = frame[frame["cohort"].astype(str).eq(COLD_START)]

    payload = {
        "schemaVersion": BASELINE_SCHEMA_VERSION,
        "authority": authority,
        "servingAuthorized": False,
        "publicationAuthorized": False,
        "note": (
            "Diagnostic comparison authority only. It never authorizes "
            "publication, materialization, activation or serving."
        )
        if authority == "D0"
        else "Accepted comparison authority.",
        "forecastRunId": run_manifest["forecastRunId"],
        "lifecycleStatus": lifecycle,
        "runSemanticFingerprint": run_manifest["semanticFingerprint"],
        "featureSemanticFingerprint": run_manifest["featureSemanticFingerprint"],
        "acceptanceSchemaVersion": acceptance["schemaVersion"],
        "recomputationVersion": recomputation,
        "acceptancePassed": acceptance["passed"],
        "global": _metrics(frame),
        "cohorts": {
            "establishedHistory": {
                **_metrics(established),
                "keySha256": key_fingerprint(
                    established,
                    [
                        "forecast_origin",
                        "horizon",
                        "sku_id",
                        "store_id",
                        "channel_id",
                    ],
                ),
            },
            "coldStart": {
                **_metrics(cold_start),
                "keySha256": key_fingerprint(
                    cold_start,
                    [
                        "forecast_origin",
                        "horizon",
                        "sku_id",
                        "store_id",
                        "channel_id",
                    ],
                ),
                "rowsWithoutComparator": int(
                    pd.to_numeric(
                        cold_start.get(COLD_START_BASELINE_COLUMN),
                        errors="coerce",
                    )
                    .isna()
                    .sum()
                ),
            },
        },
        "slices": {
            "market": _slice(frame, "market_id"),
            "store": _slice(frame, "store_id"),
            "category": _slice(frame, "category"),
            "channel": _slice(frame, "channel_id"),
            "modelRoute": _slice(frame, "selected_model"),
            "cohort": _slice(frame, "cohort"),
            "horizon": _horizon_slices(frame),
        },
        "originRoles": _origin_roles(frame),
    }
    payload["semanticFingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def load_and_build(
    run_root: str | Path,
    *,
    authority: str = "D0",
) -> dict[str, Any]:
    """Build a baseline from an immutable run bundle on disk."""

    root = Path(run_root)
    manifest = json.loads(
        (root / "forecast-run-manifest.json").read_text(encoding="utf-8")
    )
    acceptance = json.loads(
        (root / "forecast_acceptance.json").read_text(encoding="utf-8")
    )
    evaluation = pd.read_parquet(root / "forecast_eval_predictions.parquet")
    baselines = pd.read_parquet(root / "forecast_baseline_predictions.parquet")
    return build_diagnostic_baseline(
        acceptance,
        manifest,
        evaluation,
        baselines,
        authority=authority,
    )


__all__ = [
    "BASELINE_SCHEMA_VERSION",
    "CONFIRMATION_ORIGINS",
    "DEVELOPMENT_ORIGINS",
    "DiagnosticBaselineError",
    "HORIZON_CHECKPOINTS",
    "REQUIRED_RECOMPUTATION",
    "build_diagnostic_baseline",
    "load_and_build",
]
