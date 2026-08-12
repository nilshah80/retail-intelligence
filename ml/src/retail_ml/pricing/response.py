"""Deterministic Poisson response fitting, origin scoring, and shrinkage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

FEATURE_NAMES = (
    "intercept",
    "log_regular_price",
    "promotion_flag",
    "store_shortfall_share",
    "linear_trend",
    "annual_sine",
    "annual_cosine",
)
SERIES_COLUMNS = ("market_id", "sku_id", "store_id", "channel_id")
PANEL_REQUIRED_COLUMNS = {
    *SERIES_COLUMNS,
    "week_start",
    "units",
    "regular_price_minor",
    "store_shortfall_units",
    "store_shortfall_share",
    "store_availability_constrained",
    "availability_known_as_of",
    "promotion_flag",
    "price_known_as_of",
    "sales_known_as_of",
    "price_evidence_grade",
    "department_id",
    "category",
    "product_name",
    "channel_type",
    "currency_code",
    "decision_as_of",
}
RESPONSE_COLUMNS = (
    *SERIES_COLUMNS,
    "department_id",
    "category",
    "category_label",
    "product_name",
    "channel_type",
    "currency_code",
    "observation_count",
    "price_level_count",
    "price_transition_count",
    "store_shortfall_week_count",
    "store_shortfall_units",
    "support_min_minor",
    "support_max_minor",
    "current_price_minor",
    "development_tier_price_minor",
    "first_failure_reason",
    "disposition",
    "converged",
    "raw_beta",
    "shrunk_beta",
    "standard_error",
    "deviance",
    "confidence",
    "resample_iqr_ratio",
    "valid_resample_draws",
    "development_improvement",
    "confirmation_improvement",
    "origin_diagnostics",
    "price_tier",
    "selected_configuration_id",
    "selected_shrinkage",
    "candidate_selection_diagnostics",
    "department_accepted_coverage",
    "department_distinct_sku_store_pairs",
    "department_enabled",
)


@dataclass(frozen=True)
class PoissonFit:
    coefficients: np.ndarray
    covariance: np.ndarray
    fitted_mean: np.ndarray
    converged: bool
    iterations: int
    deviance: float
    feature_names: tuple[str, ...] = FEATURE_NAMES


class ResponseModelError(RuntimeError):
    """A response fit or its immutable protocol is invalid."""


def poisson_deviance(actual: np.ndarray, predicted: np.ndarray) -> float:
    y = np.asarray(actual, dtype=np.float64)
    mu = np.clip(np.asarray(predicted, dtype=np.float64), 1e-9, 1e15)
    terms = mu.copy()
    positive = y > 0
    terms[positive] = (
        y[positive] * np.log(y[positive] / mu[positive])
        - (y[positive] - mu[positive])
    )
    return float(2.0 * np.sum(terms))


def fit_poisson(
    response: Sequence[float] | np.ndarray,
    design: np.ndarray,
    *,
    maximum_iterations: int = 50,
    tolerance: float = 1e-8,
    ridge: float = 1e-6,
) -> PoissonFit:
    y = np.asarray(response, dtype=np.float64)
    x = np.asarray(design, dtype=np.float64)
    if x.ndim != 2 or y.ndim != 1 or len(y) != len(x):
        raise ResponseModelError("Poisson response/design shapes disagree")
    if len(y) <= x.shape[1] or np.any(y < 0) or not np.isfinite(x).all():
        raise ResponseModelError("Poisson inputs are invalid or underdetermined")
    penalty = np.eye(x.shape[1], dtype=np.float64) * ridge
    penalty[0, 0] = ridge * 0.01
    beta = np.linalg.lstsq(x, np.log(y + 0.25), rcond=None)[0]
    converged = False
    covariance = np.full((x.shape[1], x.shape[1]), np.nan)
    for iteration in range(1, maximum_iterations + 1):
        eta = np.clip(x @ beta, -25.0, 25.0)
        mu = np.exp(eta)
        working = eta + (y - mu) / np.clip(mu, 1e-9, None)
        weighted = x * mu[:, None]
        information = x.T @ weighted + penalty
        score = x.T @ (mu * working)
        try:
            updated = np.linalg.solve(information, score)
        except np.linalg.LinAlgError:
            updated = np.linalg.pinv(information) @ score
        if not np.isfinite(updated).all():
            break
        if float(np.max(np.abs(updated - beta))) <= tolerance:
            beta = updated
            converged = True
            break
        beta = updated
    eta = np.clip(x @ beta, -25.0, 25.0)
    mu = np.exp(eta)
    information = x.T @ (x * mu[:, None]) + penalty
    try:
        covariance = np.linalg.inv(information)
    except np.linalg.LinAlgError:
        covariance = np.linalg.pinv(information)
    return PoissonFit(
        coefficients=beta,
        covariance=covariance,
        fitted_mean=mu,
        converged=converged,
        iterations=iteration,
        deviance=poisson_deviance(y, mu),
    )


def _design(
    frame: pd.DataFrame, transform: Mapping[str, float] | None = None
) -> tuple[np.ndarray, dict[str, float]]:
    price = frame["regular_price_minor"].to_numpy(dtype=np.float64)
    if np.any(price <= 0):
        raise ResponseModelError("price response contains a non-positive price")
    weeks = pd.to_datetime(frame["week_start"], utc=True)
    absolute_weeks = weeks.map(lambda value: value.toordinal() / 7.0).to_numpy()
    if transform is None:
        transform = {
            "logPriceCentre": float(np.mean(np.log(price))),
            "trendCentre": float(np.mean(absolute_weeks)),
            "trendScale": float(max(np.std(absolute_weeks), 1.0)),
        }
    log_price = np.log(price) - float(transform["logPriceCentre"])
    trend = (absolute_weeks - float(transform["trendCentre"])) / float(
        transform["trendScale"]
    )
    iso_week = weeks.dt.isocalendar().week.to_numpy(dtype=np.float64)
    angle = 2.0 * np.pi * iso_week / 52.1775
    design = np.column_stack(
        [
            np.ones(len(frame), dtype=np.float64),
            log_price,
            frame["promotion_flag"].astype(float).to_numpy(),
            frame["store_shortfall_share"].astype(float).to_numpy(),
            trend,
            np.sin(angle),
            np.cos(angle),
        ]
    )
    return design, dict(transform)


def _first_failure(series: pd.DataFrame, policy: Mapping[str, Any]) -> str | None:
    panel = policy["panel"]
    prohibited = set(panel["prohibitedEvidenceGrades"])
    grades = set(series["price_evidence_grade"].dropna().astype(str))
    if grades & prohibited:
        return "LANDING_BACKFILL_DEPENDENCY"
    if series["regular_price_minor"].isna().any():
        return "INSUFFICIENT_LEVEL_SUPPORT"
    shortfall_share = pd.to_numeric(
        series["store_shortfall_share"], errors="coerce"
    )
    if shortfall_share.isna().any() or not shortfall_share.between(0, 1).all():
        return "STOCK_AVAILABILITY_EVIDENCE_INVALID"
    if "decision_as_of" in series and not series["decision_as_of"].isna().all():
        decision_as_of = pd.to_datetime(series["decision_as_of"], utc=True).max()
        latest_week = pd.to_datetime(series["week_start"], utc=True).max()
        if (decision_as_of - latest_week).days > int(panel["freshnessDays"]):
            return "SOURCE_STALE"
    if len(series) < int(panel["minimumObservations"]):
        return "INSUFFICIENT_OBSERVATIONS"
    prices = series["regular_price_minor"].astype(int)
    if int(prices.nunique()) < int(panel["minimumPriceLevels"]):
        return "INSUFFICIENT_PRICE_LEVELS"
    transitions = int((prices.to_numpy()[1:] != prices.to_numpy()[:-1]).sum())
    if transitions < int(panel["minimumTransitions"]):
        return "INSUFFICIENT_PRICE_TRANSITIONS"
    if int(prices.value_counts().min()) < int(panel["minimumWeeksPerLevel"]):
        return "INSUFFICIENT_LEVEL_SUPPORT"
    missing = float(series["regular_price_minor"].isna().mean())
    if missing > float(panel["maximumMissingPriceRatio"]):
        return "INSUFFICIENT_LEVEL_SUPPORT"
    return None


def _origin_diagnostics(
    series: pd.DataFrame,
    policy: Mapping[str, Any],
    *,
    include_internal: bool = False,
) -> tuple[list[dict[str, Any]], str | None]:
    rules = policy["originRules"]
    model = policy["model"]
    diagnostics: list[dict[str, Any]] = []
    for origin in policy["origins"]:
        origin_date = pd.Timestamp(origin["originDate"], tz="UTC")
        train_start = origin_date - timedelta(weeks=int(rules["trainingWeeks"]))
        train = series[
            (series["week_start"] >= train_start)
            & (series["week_start"] < origin_date)
            & (series["price_known_as_of"] <= origin_date)
            & (series["sales_known_as_of"] <= origin_date)
            & (series["availability_known_as_of"] <= origin_date)
        ]
        test_end = origin_date + timedelta(weeks=int(rules["scoringWeeks"]))
        test = series[
            (series["week_start"] >= origin_date)
            & (series["week_start"] < test_end)
        ]
        row: dict[str, Any] = {
            "index": int(origin["index"]),
            "originDate": str(origin["originDate"]),
            "purpose": str(origin["purpose"]),
            "trainingRows": int(len(train)),
            "scoringRows": int(len(test)),
            "status": "insufficient",
            "devianceImprovement": None,
        }
        if len(train) < int(rules["minimumTrainingWeeks"]) or len(test) < 8:
            diagnostics.append(row)
            continue
        try:
            train_design, transform = _design(train)
            fit = fit_poisson(
                train["units"].to_numpy(dtype=float),
                train_design,
                maximum_iterations=int(model["maximumIterations"]),
                tolerance=float(model["convergenceTolerance"]),
                ridge=float(model["ridge"]),
            )
            test_design, _ = _design(test, transform)
            model_mean = np.exp(
                np.clip(test_design @ fit.coefficients, -25.0, 25.0)
            )
            # The frozen baseline keeps the identical intercept, promotion,
            # trend and seasonality terms and removes only log price. A flat
            # historical mean would make the candidate look better by also
            # withholding every approved control from its comparator.
            baseline_columns = [0, 2, 3, 4, 5, 6]
            baseline_fit = fit_poisson(
                train["units"].to_numpy(dtype=float),
                train_design[:, baseline_columns],
                maximum_iterations=int(model["maximumIterations"]),
                tolerance=float(model["convergenceTolerance"]),
                ridge=float(model["ridge"]),
            )
            baseline_mean = np.exp(
                np.clip(
                    test_design[:, baseline_columns] @ baseline_fit.coefficients,
                    -25.0,
                    25.0,
                )
            )
            model_deviance = poisson_deviance(
                test["units"].to_numpy(dtype=float), model_mean
            )
            baseline_deviance = poisson_deviance(
                test["units"].to_numpy(dtype=float), baseline_mean
            )
            improvement = (
                (baseline_deviance - model_deviance) / baseline_deviance
                if baseline_deviance > 0
                else 0.0
            )
            row.update(
                {
                    "status": "scored" if fit.converged else "not_converged",
                    "modelDeviance": model_deviance,
                    "baselineDeviance": baseline_deviance,
                    "devianceImprovement": improvement,
                    "beta": float(fit.coefficients[1]),
                    "betaStandardError": float(
                        np.sqrt(max(fit.covariance[1, 1], 0.0))
                    ),
                    "baselineSpecification": "same_controls_without_log_price",
                }
            )
            if not baseline_fit.converged:
                row["status"] = "not_converged"
            if include_internal:
                row.update(
                    {
                        "_actual": test["units"].to_numpy(dtype=float),
                        "_rawMean": model_mean,
                        "_priceTerm": test_design[:, 1],
                    }
                )
        except (ResponseModelError, ValueError, FloatingPointError):
            pass
        diagnostics.append(row)
    if len(diagnostics) != 13 or any(
        row["status"] != "scored" for row in diagnostics
    ):
        return diagnostics, "INSUFFICIENT_ORIGINS"
    return diagnostics, None


def _resample_draws(
    series: pd.DataFrame,
    fit: PoissonFit,
    design: np.ndarray,
    policy: Mapping[str, Any],
    key: tuple[str, str, str, str],
) -> np.ndarray:
    contract = policy["resampling"]
    block_weeks = int(contract["blockWeeks"])
    residual_scores = design * (
        series["units"].to_numpy(dtype=float) - fit.fitted_mean
    )[:, None]
    block_scores = np.vstack(
        [
            residual_scores[start : start + block_weeks].sum(axis=0)
            for start in range(0, len(series), block_weeks)
        ]
    )
    seed_payload = "|".join((policy["policyFingerprint"], *key)).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(seed_payload).digest()[:8], "big")
    generator = np.random.default_rng(seed)
    draws = int(contract["draws"])
    sampled = generator.integers(
        0, len(block_scores), size=(draws, len(block_scores)), endpoint=False
    )
    counts = np.zeros((draws, len(block_scores)), dtype=np.float64)
    for index in range(draws):
        counts[index] = np.bincount(
            sampled[index], minlength=len(block_scores)
        )
    score_draws = (counts - 1.0) @ block_scores
    deltas = score_draws @ fit.covariance.T
    return fit.coefficients[1] + deltas[:, 1]


def _gate_reason(
    *,
    beta: float,
    confidence: float,
    iqr_ratio: float,
    confirmation_improvement: float,
    valid_draws: int,
    policy: Mapping[str, Any],
) -> str | None:
    gates = policy["strictGates"]
    if bool(gates["requireNegativeBeta"]) and beta >= 0:
        return "BETA_SIGN_REJECTED"
    magnitude = abs(beta)
    if not float(gates["betaMinAbs"]) < magnitude < float(gates["betaMaxAbs"]):
        return "BETA_MAGNITUDE_REJECTED"
    if valid_draws < int(policy["resampling"]["minimumValidDraws"]):
        return "RESAMPLE_STABILITY_REJECTED"
    if confidence < float(gates["signConsistencyMin"]):
        return "SIGN_CONSISTENCY_REJECTED"
    if iqr_ratio >= float(gates["resampleIqrRatioMax"]):
        return "RESAMPLE_STABILITY_REJECTED"
    if confirmation_improvement <= float(gates["holdoutImprovementMin"]):
        return "HOLDOUT_IMPROVEMENT_REJECTED"
    return None


def assess_response_series(
    series: pd.DataFrame,
    policy: Mapping[str, Any],
    *,
    include_internal: bool = False,
) -> dict[str, Any]:
    ordered = series.sort_values("week_start").reset_index(drop=True)
    key = tuple(str(ordered.iloc[0][column]) for column in SERIES_COLUMNS)
    prices = ordered["regular_price_minor"].dropna().astype(int)
    confirmation_start = pd.Timestamp(policy["origins"][8]["originDate"], tz="UTC")
    development_prices = ordered.loc[
        ordered["week_start"] < confirmation_start, "regular_price_minor"
    ].dropna().astype(int)
    first_failure = _first_failure(ordered, policy)
    result: dict[str, Any] = {
        **dict(zip(SERIES_COLUMNS, key, strict=True)),
        "department_id": str(ordered.iloc[0]["department_id"]),
        "category": str(ordered.iloc[0]["category"]),
        "category_label": (
            None
            if "category_label" not in ordered.columns
            or pd.isna(ordered.iloc[0]["category_label"])
            else str(ordered.iloc[0]["category_label"])
        ),
        "product_name": str(ordered.iloc[0]["product_name"]),
        "channel_type": str(ordered.iloc[0]["channel_type"]),
        "currency_code": str(ordered.iloc[0]["currency_code"]),
        "observation_count": int(len(ordered)),
        "price_level_count": int(prices.nunique()),
        "price_transition_count": int(
            (prices.to_numpy()[1:] != prices.to_numpy()[:-1]).sum()
        )
        if len(prices) > 1
        else 0,
        "store_shortfall_week_count": int(
            ordered["store_availability_constrained"].astype(bool).sum()
        ),
        "store_shortfall_units": int(ordered["store_shortfall_units"].sum()),
        "support_min_minor": int(prices.min()) if not prices.empty else None,
        "support_max_minor": int(prices.max()) if not prices.empty else None,
        "current_price_minor": int(prices.iloc[-1]) if not prices.empty else None,
        "development_tier_price_minor": (
            int(round(float(development_prices.median())))
            if not development_prices.empty
            else None
        ),
        "first_failure_reason": first_failure,
        "disposition": "insufficient_evidence" if first_failure else "assessed",
        "converged": False,
        "raw_beta": None,
        "shrunk_beta": None,
        "standard_error": None,
        "deviance": None,
        "confidence": None,
        "resample_iqr_ratio": None,
        "valid_resample_draws": 0,
        "development_improvement": None,
        "confirmation_improvement": None,
        "origin_diagnostics": [],
    }
    if first_failure:
        return result
    origins, origin_failure = _origin_diagnostics(
        ordered, policy, include_internal=include_internal
    )
    result["origin_diagnostics"] = origins
    if origin_failure:
        result["first_failure_reason"] = origin_failure
        result["disposition"] = "insufficient_evidence"
        return result
    design, _ = _design(ordered)
    model = policy["model"]
    fit = fit_poisson(
        ordered["units"].to_numpy(dtype=float),
        design,
        maximum_iterations=int(model["maximumIterations"]),
        tolerance=float(model["convergenceTolerance"]),
        ridge=float(model["ridge"]),
    )
    result["converged"] = bool(fit.converged)
    if not fit.converged:
        result["first_failure_reason"] = "MODEL_DID_NOT_CONVERGE"
        result["disposition"] = "rejected"
        return result
    draws = _resample_draws(ordered, fit, design, policy, key)
    valid = draws[np.isfinite(draws)]
    raw_beta = float(fit.coefficients[1])
    confidence = float(np.mean(valid < 0)) if len(valid) else 0.0
    iqr = float(np.quantile(valid, 0.75) - np.quantile(valid, 0.25)) if len(valid) else np.inf
    iqr_ratio = iqr / max(abs(raw_beta), 1e-12)
    development = [
        float(row["devianceImprovement"])
        for row in origins[:8]
        if row["devianceImprovement"] is not None
    ]
    confirmation = [
        float(row["devianceImprovement"])
        for row in origins[8:]
        if row["devianceImprovement"] is not None
    ]
    development_improvement = float(np.mean(development))
    confirmation_improvement = float(np.mean(confirmation))
    failure = _gate_reason(
        beta=raw_beta,
        confidence=confidence,
        iqr_ratio=iqr_ratio,
        confirmation_improvement=confirmation_improvement,
        valid_draws=len(valid),
        policy=policy,
    )
    result.update(
        {
            "raw_beta": raw_beta,
            "shrunk_beta": raw_beta,
            "standard_error": float(np.sqrt(max(fit.covariance[1, 1], 0.0))),
            "deviance": float(fit.deviance),
            "confidence": confidence,
            "resample_iqr_ratio": iqr_ratio,
            "valid_resample_draws": int(len(valid)),
            "development_improvement": development_improvement,
            "confirmation_improvement": confirmation_improvement,
            "first_failure_reason": failure,
            "disposition": "accepted" if failure is None else "rejected",
        }
    )
    if include_internal:
        result["_draws"] = valid
    return result


def _exception_response_series(
    series: pd.DataFrame, reason: str
) -> dict[str, Any]:
    """Retain one bad series as a reason-coded assessment.

    This is deliberately a record boundary, not a blanket pipeline catch. The
    caller has already proved the panel schema, identity columns and policy.
    Expected value/conversion/model failures in one series therefore withhold
    that series while unrelated series continue. Contract, identity and
    artifact-integrity failures still escape and abort the bundle.
    """

    ordered = series.sort_values("week_start").reset_index(drop=True)
    first = ordered.iloc[0]
    prices = pd.to_numeric(ordered["regular_price_minor"], errors="coerce").dropna()
    shortfall = pd.to_numeric(
        ordered["store_shortfall_units"], errors="coerce"
    ).fillna(0)
    constrained = ordered["store_availability_constrained"].fillna(False)
    return {
        **{column: str(first[column]) for column in SERIES_COLUMNS},
        "department_id": str(first["department_id"]),
        "category": str(first["category"]),
        "category_label": (
            None
            if "category_label" not in first.index or pd.isna(first["category_label"])
            else str(first["category_label"])
        ),
        "product_name": str(first["product_name"]),
        "channel_type": str(first["channel_type"]),
        "currency_code": str(first["currency_code"]),
        "observation_count": int(len(ordered)),
        "price_level_count": int(prices.nunique()),
        "price_transition_count": 0,
        "store_shortfall_week_count": int(constrained.astype(bool).sum()),
        "store_shortfall_units": int(shortfall.sum()),
        "support_min_minor": int(prices.min()) if not prices.empty else None,
        "support_max_minor": int(prices.max()) if not prices.empty else None,
        "current_price_minor": int(prices.iloc[-1]) if not prices.empty else None,
        "development_tier_price_minor": None,
        "first_failure_reason": reason,
        "disposition": "rejected",
        "converged": False,
        "raw_beta": None,
        "shrunk_beta": None,
        "standard_error": None,
        "deviance": None,
        "confidence": None,
        "resample_iqr_ratio": None,
        "valid_resample_draws": 0,
        "development_improvement": None,
        "confirmation_improvement": None,
        "origin_diagnostics": [
            {"status": "exception", "reasonCode": reason}
        ],
    }


def _price_tiers(rows: list[dict[str, Any]]) -> None:
    by_market_department: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        by_market_department.setdefault(
            (str(row["market_id"]), str(row["department_id"])), []
        ).append(row)
    for group in by_market_department.values():
        values = sorted(
            int(row["development_tier_price_minor"])
            for row in group
            if row["development_tier_price_minor"] is not None
        )
        if not values:
            continue
        boundaries = np.quantile(values, [0.25, 0.5, 0.75])
        for row in group:
            price = int(row["development_tier_price_minor"] or 0)
            row["price_tier"] = int(np.searchsorted(boundaries, price, side="right") + 1)


def _pool_key(
    row: Mapping[str, Any], shrinkage: str
) -> tuple[str, ...]:
    if shrinkage == "none":
        return tuple(str(row[column]) for column in SERIES_COLUMNS)
    if shrinkage == "department":
        return (str(row["market_id"]), str(row["department_id"]))
    if shrinkage == "department_price_tier":
        return (
            str(row["market_id"]),
            str(row["department_id"]),
            str(int(row.get("price_tier", 0))),
        )
    raise ResponseModelError(f"unsupported shrinkage configuration: {shrinkage}")


def _shrink_group(
    beta: np.ndarray, variance: np.ndarray
) -> tuple[np.ndarray, float, float]:
    if len(beta) == 1:
        return beta.copy(), float(beta[0]), 0.0
    fixed_weights = 1.0 / variance
    fixed_mean = float(np.sum(fixed_weights * beta) / np.sum(fixed_weights))
    q = float(np.sum(fixed_weights * np.square(beta - fixed_mean)))
    c = float(
        np.sum(fixed_weights)
        - np.sum(np.square(fixed_weights)) / np.sum(fixed_weights)
    )
    tau_squared = max(0.0, (q - (len(beta) - 1)) / c) if c > 0 else 0.0
    random_weights = 1.0 / (variance + tau_squared)
    pool_mean = float(np.sum(random_weights * beta) / np.sum(random_weights))
    prior_variance = max(tau_squared, 1e-6)
    shrunk = (beta / variance + pool_mean / prior_variance) / (
        1.0 / variance + 1.0 / prior_variance
    )
    return shrunk, pool_mean, tau_squared


def _origin_candidate_score(
    rows: list[dict[str, Any]], shrinkage: str, origin_index: int
) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if len(row.get("origin_diagnostics", [])) > origin_index
        and row["origin_diagnostics"][origin_index].get("status") == "scored"
        and "_actual" in row["origin_diagnostics"][origin_index]
    ]
    pools: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in eligible:
        pools.setdefault(_pool_key(row, shrinkage), []).append(row)
    scored: list[dict[str, Any]] = []
    for key, group in sorted(pools.items()):
        diagnostics = [row["origin_diagnostics"][origin_index] for row in group]
        beta = np.asarray([row["beta"] for row in diagnostics], dtype=float)
        variance = np.square(
            np.maximum(
                np.asarray([row["betaStandardError"] for row in diagnostics], dtype=float),
                1e-6,
            )
        )
        selected, pool_mean, tau_squared = _shrink_group(beta, variance)
        for row, diagnostic, raw, adjusted in zip(
            group, diagnostics, beta, selected, strict=True
        ):
            mean = np.asarray(diagnostic["_rawMean"], dtype=float) * np.exp(
                (adjusted - raw) * np.asarray(diagnostic["_priceTerm"], dtype=float)
            )
            deviance = poisson_deviance(diagnostic["_actual"], mean)
            baseline = float(diagnostic["baselineDeviance"])
            scored.append(
                {
                    "row": row,
                    "diagnostic": diagnostic,
                    "beta": float(adjusted),
                    "deviance": deviance,
                    "improvement": (
                        (baseline - deviance) / baseline if baseline > 0 else 0.0
                    ),
                    "pool": "|".join(key),
                    "poolMeanBeta": pool_mean,
                    "poolTauSquared": tau_squared,
                }
            )
    return scored


def _select_configuration(
    rows: list[dict[str, Any]], policy: Mapping[str, Any]
) -> dict[str, Any]:
    rules = policy["originRules"]
    candidates = list(rules["candidateConfigurations"])
    if not candidates or len(candidates) > int(rules["maximumCandidateConfigurations"]):
        raise ResponseModelError("response candidate registry exceeds its frozen budget")
    ids = [str(candidate["id"]) for candidate in candidates]
    if len(ids) != len(set(ids)):
        raise ResponseModelError("response candidate registry contains duplicate ids")
    scores: list[dict[str, Any]] = []
    for candidate in candidates:
        shrinkage = str(candidate["shrinkage"])
        evaluations = [
            item
            for origin_index in range(8)
            for item in _origin_candidate_score(rows, shrinkage, origin_index)
        ]
        if not evaluations:
            scores.append(
                {
                    "configurationId": str(candidate["id"]),
                    "shrinkage": shrinkage,
                    "developmentEvaluationCount": 0,
                    "meanDevianceImprovement": None,
                    "meanDeviance": None,
                    "safeSignRate": None,
                }
            )
            continue
        scores.append(
            {
                "configurationId": str(candidate["id"]),
                "shrinkage": shrinkage,
                "developmentEvaluationCount": len(evaluations),
                "meanDevianceImprovement": float(
                    np.mean([item["improvement"] for item in evaluations])
                ),
                "meanDeviance": float(
                    np.mean([item["deviance"] for item in evaluations])
                ),
                "safeSignRate": float(
                    np.mean([item["beta"] < 0 for item in evaluations])
                ),
            }
        )
    evaluable = [score for score in scores if score["meanDeviance"] is not None]
    selected = min(
        evaluable,
        key=lambda score: (
            -float(score["meanDevianceImprovement"]),
            -float(score["safeSignRate"]),
            float(score["meanDeviance"]),
            str(score["configurationId"]),
        ),
    ) if evaluable else None
    return {
        "selectionMetric": str(rules["selectionMetric"]),
        "developmentOrigins": list(range(1, 9)),
        "confirmationOriginsRead": [],
        "candidateCount": len(candidates),
        "candidateScores": scores,
        "selectedConfigurationId": (
            str(selected["configurationId"]) if selected else None
        ),
        "selectedShrinkage": str(selected["shrinkage"]) if selected else None,
        "status": "selected" if selected else "not_evaluable",
    }


def _apply_origin_configuration(
    rows: list[dict[str, Any]], selection: Mapping[str, Any]
) -> None:
    shrinkage = selection.get("selectedShrinkage")
    if shrinkage is None:
        return
    for origin_index in range(13):
        for item in _origin_candidate_score(rows, str(shrinkage), origin_index):
            diagnostic = item["diagnostic"]
            diagnostic.update(
                {
                    "selectedBeta": item["beta"],
                    "modelDeviance": item["deviance"],
                    "devianceImprovement": item["improvement"],
                    "shrinkagePool": item["pool"],
                    "poolMeanBeta": item["poolMeanBeta"],
                    "poolTauSquared": item["poolTauSquared"],
                }
            )
    for row in rows:
        origins = row.get("origin_diagnostics", [])
        development = [
            float(item["devianceImprovement"])
            for item in origins[:8]
            if item.get("devianceImprovement") is not None
        ]
        confirmation = [
            float(item["devianceImprovement"])
            for item in origins[8:]
            if item.get("devianceImprovement") is not None
        ]
        if development:
            row["development_improvement"] = float(np.mean(development))
        if confirmation:
            row["confirmation_improvement"] = float(np.mean(confirmation))


def _apply_shrinkage(
    rows: list[dict[str, Any]], policy: Mapping[str, Any], shrinkage: str | None
) -> None:
    if shrinkage is None:
        return
    pools: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        if row["raw_beta"] is not None and row["standard_error"] is not None:
            pools.setdefault(_pool_key(row, shrinkage), []).append(row)
    for key, group in pools.items():
        beta = np.asarray([row["raw_beta"] for row in group], dtype=float)
        variance = np.square(
            np.maximum(
                np.asarray([row["standard_error"] for row in group], dtype=float),
                1e-6,
            )
        )
        shrunk_values, pool_mean, tau_squared = _shrink_group(beta, variance)
        for row, raw, shrunk in zip(group, beta, shrunk_values, strict=True):
            shrunk = float(shrunk)
            draws = np.asarray(row.pop("_draws"), dtype=float) + (shrunk - raw)
            valid = draws[np.isfinite(draws)]
            confidence = float(np.mean(valid < 0)) if len(valid) else 0.0
            iqr = (
                float(np.quantile(valid, 0.75) - np.quantile(valid, 0.25))
                if len(valid)
                else np.inf
            )
            iqr_ratio = iqr / max(abs(shrunk), 1e-12)
            failure = _gate_reason(
                beta=shrunk,
                confidence=confidence,
                iqr_ratio=iqr_ratio,
                confirmation_improvement=float(row["confirmation_improvement"]),
                valid_draws=len(valid),
                policy=policy,
            )
            row.update(
                {
                    "shrinkage_pool": "|".join(map(str, key)),
                    "pool_mean_beta": pool_mean,
                    "pool_tau_squared": tau_squared,
                    "shrunk_beta": shrunk,
                    "confidence": confidence,
                    "resample_iqr_ratio": iqr_ratio,
                    "valid_resample_draws": int(len(valid)),
                    "first_failure_reason": failure,
                    "disposition": "accepted" if failure is None else "rejected",
                }
            )


def _apply_department_coverage(rows: list[dict[str, Any]], policy: Mapping[str, Any]) -> None:
    gates = policy["coverageGates"]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(
            (str(row["market_id"]), str(row["department_id"])), []
        ).append(row)
    for group in groups.values():
        accepted = [row for row in group if row["disposition"] == "accepted"]
        gated_pairs = {
            (str(row["sku_id"]), str(row["store_id"])) for row in accepted
        }
        coverage = len(accepted) / max(len(group), 1)
        enabled = (
            coverage >= float(gates["departmentCoverageMin"])
            and len(gated_pairs) >= int(gates["departmentMinDistinctSkuStorePairs"])
        )
        for row in group:
            row["department_accepted_coverage"] = coverage
            row["department_distinct_sku_store_pairs"] = len(gated_pairs)
            row["department_enabled"] = enabled
            if row["disposition"] == "accepted" and not enabled:
                row["disposition"] = "rejected"
                row["first_failure_reason"] = "DEPARTMENT_COVERAGE_REJECTED"


def run_response_assessment(
    panel: pd.DataFrame, policy: Mapping[str, Any]
) -> pd.DataFrame:
    missing = sorted(PANEL_REQUIRED_COLUMNS - set(panel.columns))
    if missing:
        raise ResponseModelError("pricing panel lacks: " + ", ".join(missing))
    if panel.empty:
        return pd.DataFrame(columns=RESPONSE_COLUMNS)
    identity = panel.loc[:, list(SERIES_COLUMNS)]
    if identity.isna().any(axis=None) or identity.apply(
        lambda column: column.astype(str).str.strip().eq("").any()
    ).any():
        raise ResponseModelError(
            "pricing panel contains a null or blank series identity"
        )
    rows: list[dict[str, Any]] = []
    for _, group in panel.groupby(
        list(SERIES_COLUMNS), sort=True, observed=True, dropna=False
    ):
        try:
            rows.append(
                assess_response_series(group, policy, include_internal=True)
            )
        except (
            ResponseModelError,
            FloatingPointError,
            OverflowError,
            TypeError,
            ValueError,
        ):
            rows.append(
                _exception_response_series(
                    group, "RESPONSE_SERIES_EVALUATION_EXCEPTION"
                )
            )
    _price_tiers(rows)
    selection = _select_configuration(rows, policy)
    _apply_origin_configuration(rows, selection)
    _apply_shrinkage(rows, policy, selection["selectedShrinkage"])
    selection_json = __import__("json").dumps(
        selection, sort_keys=True, separators=(",", ":")
    )
    for row in rows:
        row["selected_configuration_id"] = selection["selectedConfigurationId"]
        row["selected_shrinkage"] = selection["selectedShrinkage"]
        row["candidate_selection_diagnostics"] = selection_json
        row.pop("_draws", None)
        for diagnostic in row.get("origin_diagnostics", []):
            for field in ("_actual", "_rawMean", "_priceTerm"):
                diagnostic.pop(field, None)
    _apply_department_coverage(rows, policy)
    result = pd.DataFrame(rows)
    result["origin_diagnostics"] = result["origin_diagnostics"].map(
        lambda value: __import__("json").dumps(
            value, sort_keys=True, separators=(",", ":")
        )
    )
    return result.sort_values(list(SERIES_COLUMNS)).reset_index(drop=True)


__all__ = [
    "FEATURE_NAMES", "RESPONSE_COLUMNS",
    "PoissonFit",
    "ResponseModelError",
    "assess_response_series",
    "fit_poisson",
    "poisson_deviance",
    "run_response_assessment",
]
