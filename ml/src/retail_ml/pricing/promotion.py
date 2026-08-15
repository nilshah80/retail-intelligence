"""Origin-visible promotion protection and explicit Planner disposition.

The protection foundation (``build_promotion_foundation``) is the forward-looking
price-safety guard and stays on the negative safety branch. The observational
uplift estimator below (``build_promotion_uplift``) is the P5-D20/P5-D22 positive
Planner branch: it measures the demand lift of *completed* promotions from the
canonical sales panel, accepts only well-supported/holdout-stable scopes, and
flips the package disposition to ``positive`` when at least one promotion is
accepted. Per §0.0/P5-D23 this is owner-directed PoC engineering — positive
revenue/margin emerges from the estimator, never a hardcoded flag.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import duckdb
import numpy as np
import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint


class PromotionFoundationError(RuntimeError):
    """Promotion safety evidence is missing, ambiguous, or invalid."""


PROMOTION_COLUMNS = (
    "market_id", "sku_id", "store_id", "channel_id", "department_id",
    "category", "guard_status", "first_failure_reason",
    "applicable_promotion_ids", "selected_precedence",
)


def load_promotion_policy(path: str | Path) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("schemaVersion") != "retail-promotion-protection/v1":
        raise PromotionFoundationError("unsupported promotion protection policy")
    precedence = policy.get("merchandisePrecedence")
    if precedence != ["sku", "dept", "category"]:
        raise PromotionFoundationError("promotion merchandise precedence changed")
    if policy.get("scopeLogic") != {"withinRow": "and", "acrossRows": "or"}:
        raise PromotionFoundationError("promotion scope logic changed")
    horizon = policy.get("protectionHorizonDays")
    if type(horizon) is not int or horizon < 0:
        raise PromotionFoundationError("promotion protection horizon is invalid")
    return policy


def _geography_matches(scope: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    checks = (
        ("region", "region"),
        ("location_id", "store_id"),
        ("channel_id", "channel_id"),
    )
    for candidate_key, scope_key in checks:
        expected = candidate.get(candidate_key)
        if expected is not None and not pd.isna(expected) and str(expected) != "":
            if str(scope.get(scope_key) or "") != str(expected):
                return False
    return True


def assess_promotion_protection(
    pricing_scopes: pd.DataFrame,
    promotions: pd.DataFrame,
    targets: pd.DataFrame,
    geographic_scopes: pd.DataFrame,
    *,
    policy: Mapping[str, Any],
    feed_available: bool = True,
) -> pd.DataFrame:
    required = {
        "market_id", "sku_id", "store_id", "channel_id", "department_id",
        "category",
    }
    missing = sorted(required - set(pricing_scopes.columns))
    if missing:
        raise PromotionFoundationError(
            "pricing scopes lack: " + ", ".join(missing)
        )
    precedence = {name: len(policy["merchandisePrecedence"]) - index for index, name in enumerate(policy["merchandisePrecedence"])}
    rows: list[dict[str, Any]] = []
    for scope in pricing_scopes.to_dict("records"):
        identity = {key: scope[key] for key in sorted(required)}
        if not feed_available:
            rows.append(
                {
                    **identity,
                    "guard_status": "missing",
                    "first_failure_reason": policy["missingSafetyFeed"],
                    "applicable_promotion_ids": "[]",
                    "selected_precedence": None,
                }
            )
            continue
        market_promotions = promotions[promotions["market_id"] == scope["market_id"]]
        applicable: list[tuple[int, str]] = []
        for promotion in market_promotions.to_dict("records"):
            promotion_id = promotion["promo_id"]
            if str(promotion.get("known_as_of_evidence_grade", "")) in {
                "landing_backfill", "unknown", ""
            }:
                continue
            merchandise = targets[
                (targets["market_id"] == scope["market_id"])
                & (targets["promo_id"] == promotion_id)
            ]
            matched_levels: list[int] = []
            for target in merchandise.to_dict("records"):
                target_type = str(target["merch_scope_type"])
                expected = {
                    "sku": scope["sku_id"],
                    "category": scope["category"],
                    "dept": scope["department_id"],
                }.get(target_type)
                if expected is not None and str(target["merch_scope_id"]) == str(expected):
                    matched_levels.append(precedence[target_type])
            if not matched_levels:
                continue
            geography = geographic_scopes[
                (geographic_scopes["market_id"] == scope["market_id"])
                & (geographic_scopes["promo_id"] == promotion_id)
            ]
            if geography.empty or not any(
                _geography_matches(scope, candidate)
                for candidate in geography.to_dict("records")
            ):
                continue
            applicable.append((max(matched_levels), str(promotion_id)))
        if not applicable:
            rows.append(
                {
                    **identity,
                    "guard_status": "no_overlap",
                    "first_failure_reason": None,
                    "applicable_promotion_ids": "[]",
                    "selected_precedence": None,
                }
            )
            continue
        highest = max(level for level, _ in applicable)
        selected = sorted(identifier for level, identifier in applicable if level == highest)
        conflict = len(selected) > 1
        rows.append(
            {
                **identity,
                "guard_status": "conflict" if conflict else "applicable",
                "first_failure_reason": policy["equalPrecedenceConflict"] if conflict else None,
                "applicable_promotion_ids": json.dumps(selected, separators=(",", ":")),
                "selected_precedence": next(
                    name for name, value in precedence.items() if value == highest
                ),
            }
        )
    if not rows:
        return pd.DataFrame(columns=PROMOTION_COLUMNS)
    return pd.DataFrame(rows).sort_values(
        ["market_id", "sku_id", "store_id", "channel_id"]
    ).reset_index(drop=True)


def build_promotion_foundation(
    curated_database: str | Path,
    pricing_scopes: pd.DataFrame,
    *,
    decision_as_of: datetime | str,
    policy: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    database = Path(curated_database)
    if not database.is_file():
        raise PromotionFoundationError(f"curated database is absent: {database}")
    feed_available = True
    protection_through = (
        pd.Timestamp(decision_as_of) + pd.Timedelta(
            days=int(policy["protectionHorizonDays"])
        )
    ).date()
    with duckdb.connect(str(database), read_only=True) as connection:
        try:
            promotions = connection.execute(
                """
                SELECT * FROM canonical_data.promotions
                WHERE known_as_of <= ?::TIMESTAMPTZ
                  AND start_date <= ?::DATE
                  AND end_date >= ?::DATE
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id
                """,
                [decision_as_of, protection_through, decision_as_of],
            ).fetch_df()
            targets = connection.execute(
                """
                SELECT * FROM canonical_data.promotion_merchandise_targets
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id, merch_scope_type,
                                 merch_scope_id
                    ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id, merch_scope_type, merch_scope_id
                """,
                [decision_as_of],
            ).fetch_df()
            geography = connection.execute(
                """
                SELECT * FROM canonical_data.promotion_scopes
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id, scope_row_id
                    ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id, scope_row_id
                """,
                [decision_as_of],
            ).fetch_df()
        except duckdb.Error:
            feed_available = False
            promotions = pd.DataFrame(columns=["market_id", "promo_id", "known_as_of_evidence_grade"])
            targets = pd.DataFrame(columns=["market_id", "promo_id", "merch_scope_type", "merch_scope_id"])
            geography = pd.DataFrame(columns=["market_id", "promo_id", "region", "location_id", "channel_id"])
    guard = assess_promotion_protection(
        pricing_scopes,
        promotions,
        targets,
        geography,
        policy=policy,
        feed_available=feed_available,
    )
    disposition = {
        "schemaVersion": "retail-promotion-package-disposition/v1",
        "decisionId": int(policy["decisionId"]),
        "decisionDisposition": policy["decisionDisposition"],
        "packageDisposition": "negative",
        "plannerAvailable": False,
        "firstFailureReason": policy["plannerFirstFailureReason"],
        "safetyGuardInternal": True,
        "forbiddenClaims": [
            "numeric_uplift", "promotion_margin", "promotion_simulation",
            "customer_targeting", "cannibalisation", "bundle_response",
        ],
    }
    return guard, disposition


# ---------------------------------------------------------------------------
# P5-D20 / P5-D22 — observational promotion-uplift estimator (positive branch)
# ---------------------------------------------------------------------------

UPLIFT_RESULT_COLUMNS = (
    "market_id", "promo_id", "promo_name", "promo_type",
    "episode_weeks", "control_weeks",
    "expected_demand_uplift", "uplift_low", "uplift_high",
    "revenue_uplift_minor", "margin_impact_minor", "margin_reason_code",
    "baseline_revenue_minor", "required_stock_units",
    "cannibalisation_risk", "confidence",
    "valid_draws", "numeric_result_rate",
    "acceptance_status", "first_failure_reason",
)

# Per-promotion source-metadata columns merged onto the estimator result (built in
# ``build_promotion_uplift`` from the same curated canonical facts the estimator
# reads). They describe *what* each promotion is — window, offer, scope, catalogue
# coverage — so the served Planner portfolio shows real values rather than a bare
# governed placeholder. Every value is read from the source; none is invented.
_PROMO_METADATA_COLUMNS = (
    "period_start", "period_end", "offer_value", "objective", "status",
    "category_labels", "category_count", "product_count",
    "channel_count", "all_stores",
)

_UPLIFT_PANEL_COLUMNS = (
    "market_id", "promo_id", "promo_name", "promo_type", "role",
    "week_start", "units", "net_sales_minor", "wac_unit_cost_minor",
)


def load_promotion_uplift_policy(path: str | Path) -> dict[str, Any]:
    """Load and fingerprint-verify the frozen uplift estimator policy.

    The seed, resample contract and acceptance thresholds are frozen here so the
    serving (Go) layer can evaluate stored accepted parameters and never refit at
    request time (P5-D22).
    """

    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    if policy.get("schemaVersion") != "retail-promotion-uplift/v1":
        raise PromotionFoundationError("unsupported promotion uplift policy")
    expected = semantic_fingerprint(policy, volatile_pointers=("/policyFingerprint",))
    if policy.get("policyFingerprint") != expected:
        raise PromotionFoundationError("promotion uplift policy fingerprint mismatch")
    estimator = policy.get("estimator")
    if not isinstance(estimator, Mapping):
        raise PromotionFoundationError("promotion uplift estimator block is absent")
    for field in (
        "seed", "resampleDraws", "blockLengthWeeks", "controlLookbackDays",
        "holdoutEpisodeWeeks",
    ):
        if type(estimator.get(field)) is not int or estimator[field] < 0:
            raise PromotionFoundationError(
                f"promotion uplift estimator {field} is invalid"
            )
    if int(estimator["resampleDraws"]) <= 0:
        raise PromotionFoundationError("promotion uplift resampleDraws must be positive")
    for field in ("intervalLowerQuantile", "intervalUpperQuantile"):
        value = float(estimator[field])
        if not 0.0 <= value <= 1.0:
            raise PromotionFoundationError(
                f"promotion uplift {field} must be in [0, 1]"
            )
    if float(estimator["intervalLowerQuantile"]) > float(
        estimator["intervalUpperQuantile"]
    ):
        raise PromotionFoundationError("promotion uplift interval quantiles are inverted")
    acceptance = policy.get("acceptance")
    if not isinstance(acceptance, Mapping):
        raise PromotionFoundationError("promotion uplift acceptance block is absent")
    for field in ("minEpisodeWeeks", "minControlWeeks", "minimumValidDraws"):
        if type(acceptance.get(field)) is not int or acceptance[field] <= 0:
            raise PromotionFoundationError(
                f"promotion uplift acceptance {field} is invalid"
            )
    for field in ("numericResultRateMin", "minPointUplift", "holdoutMinUplift"):
        float(acceptance[field])
    if not 0.0 <= float(acceptance["numericResultRateMin"]) <= 1.0:
        raise PromotionFoundationError(
            "promotion uplift numericResultRateMin must be in [0, 1]"
        )
    if type(acceptance.get("requirePositiveMargin")) is not bool:
        raise PromotionFoundationError(
            "promotion uplift requirePositiveMargin must be boolean"
        )
    if type(policy.get("horizonWeeks")) is not int or policy["horizonWeeks"] <= 0:
        raise PromotionFoundationError("promotion uplift horizon is invalid")
    for field in ("reasonCodes", "allowedClaims", "restrictedClaims"):
        if not policy.get(field):
            raise PromotionFoundationError(f"promotion uplift {field} is absent")
    return policy


def _stable_promotion_seed(base_seed: int, promo_id: str) -> int:
    """Derive a frozen, reproducible per-promotion resample seed.

    Recipe (also declared in the policy so the Go layer can reproduce it):
    the first 8 bytes of ``sha256(promo_id)`` big-endian XOR the base seed,
    reduced modulo 2**64.
    """

    digest = hashlib.sha256(str(promo_id).encode("utf-8")).digest()[:8]
    return (int(base_seed) ^ int.from_bytes(digest, "big")) % (2**64)


def _moving_block_indices(
    rng: np.random.Generator, length: int, block: int
) -> np.ndarray:
    """Circular moving-block bootstrap index vector of size ``length``."""

    if length <= 0:
        return np.empty(0, dtype=int)
    block = max(1, min(int(block), length))
    picks: list[int] = []
    while len(picks) < length:
        start = int(rng.integers(0, length))
        picks.extend((start + offset) % length for offset in range(block))
    return np.asarray(picks[:length], dtype=int)


def _resample_uplifts(
    episode_units: np.ndarray,
    control_units: np.ndarray,
    *,
    seed: int,
    draws: int,
    block: int,
) -> np.ndarray:
    """Return the finite (numeric) resampled uplift ratios for one promotion.

    A draw is *valid* only when its resampled control mean is strictly positive;
    invalid draws are dropped, so ``result.size`` is the valid-draw count and
    ``result.size / draws`` is the numeric-result rate gated by P5-D22.
    """

    rng = np.random.default_rng(int(seed))
    episode = np.asarray(episode_units, dtype=float)
    control = np.asarray(control_units, dtype=float)
    uplifts: list[float] = []
    for _ in range(int(draws)):
        # Both series are resampled every draw so the seed stream stays aligned
        # regardless of which draws end up invalid.
        episode_draw = episode[_moving_block_indices(rng, episode.size, block)]
        control_draw = control[_moving_block_indices(rng, control.size, block)]
        control_mean = float(control_draw.mean()) if control_draw.size else 0.0
        episode_mean = float(episode_draw.mean()) if episode_draw.size else 0.0
        if control_mean > 0.0:
            uplifts.append(episode_mean / control_mean - 1.0)
    return np.asarray(uplifts, dtype=float)


def _first_scalar(group: pd.DataFrame, column: str, default: Any = None) -> Any:
    if column not in group.columns:
        return default
    series = group[column].dropna()
    if series.empty:
        return default
    return series.iloc[0]


def _evaluate_promotion(
    market_id: str, promo_id: str, group: pd.DataFrame, *, policy: Mapping[str, Any]
) -> dict[str, Any]:
    estimator = policy["estimator"]
    acceptance = policy["acceptance"]
    reasons = policy["reasonCodes"]
    horizon = int(policy["horizonWeeks"])

    episodes = group[group["role"] == "episode"].sort_values("week_start")
    controls = group[group["role"] == "control"].sort_values("week_start")
    episode_units = episodes["units"].to_numpy(dtype=float)
    control_units = controls["units"].to_numpy(dtype=float)
    episode_revenue = episodes["net_sales_minor"].to_numpy(dtype=float)
    control_revenue = controls["net_sales_minor"].to_numpy(dtype=float)
    n_episode = int(episode_units.size)
    n_control = int(control_units.size)

    control_mean_units = float(control_units.mean()) if n_control else 0.0
    control_mean_revenue = float(control_revenue.mean()) if n_control else 0.0
    episode_mean_units = float(episode_units.mean()) if n_episode else 0.0
    episode_mean_revenue = float(episode_revenue.mean()) if n_episode else 0.0

    point = (
        episode_mean_units / control_mean_units - 1.0
        if control_mean_units > 0.0 and n_episode
        else None
    )

    resampled = _resample_uplifts(
        episode_units,
        control_units,
        seed=_stable_promotion_seed(int(estimator["seed"]), promo_id),
        draws=int(estimator["resampleDraws"]),
        block=int(estimator["blockLengthWeeks"]),
    )
    valid_draws = int(resampled.size)
    numeric_result_rate = valid_draws / int(estimator["resampleDraws"])
    if valid_draws:
        uplift_low = float(np.quantile(resampled, float(estimator["intervalLowerQuantile"])))
        uplift_high = float(np.quantile(resampled, float(estimator["intervalUpperQuantile"])))
        confidence = float(np.mean(resampled > 0.0))
    else:
        uplift_low = uplift_high = None
        confidence = 0.0

    # Untouched holdout: reserve the last H episode weeks. The train fit never
    # sees them, and both the train and held-out estimate must stay positive, so
    # a lift concentrated in a couple of weeks cannot be accepted (P5-D20).
    holdout_weeks = int(estimator["holdoutEpisodeWeeks"])
    holdout_ok = False
    if control_mean_units > 0.0 and holdout_weeks >= 1 and n_episode > holdout_weeks:
        train = episode_units[:-holdout_weeks]
        held = episode_units[-holdout_weeks:]
        if train.size and held.size:
            uplift_train = float(train.mean()) / control_mean_units - 1.0
            uplift_held = float(held.mean()) / control_mean_units - 1.0
            holdout_ok = (
                uplift_held > float(acceptance["holdoutMinUplift"]) and uplift_train > 0.0
            )

    # Support, stability and untouched-holdout gates (precedence-ordered).
    first_failure: str | None = None
    if n_episode < int(acceptance["minEpisodeWeeks"]):
        first_failure = reasons["insufficientEpisodes"]
    elif n_control < int(acceptance["minControlWeeks"]):
        first_failure = reasons["insufficientControls"]
    elif point is None or point <= float(acceptance["minPointUplift"]):
        first_failure = reasons["nonPositiveUplift"]
    elif valid_draws < int(acceptance["minimumValidDraws"]):
        first_failure = reasons["insufficientValidDraws"]
    elif numeric_result_rate < float(acceptance["numericResultRateMin"]):
        first_failure = reasons["numericResultRateRejected"]
    elif not holdout_ok:
        first_failure = reasons["holdoutRejected"]

    # Revenue uplift is the point uplift applied to baseline (control) revenue over
    # the horizon; incremental margin values the extra units at the realized *promo*
    # price (net of the discount) against the accepted WAC cost basis (§0.0). Margin
    # is a first-class profit guard: a well-supported lift that dilutes gross margin
    # is withheld (MARGIN_DILUTION), mirroring the frozen recommendation guard — it
    # is never counted as a positive opportunity. When the cost basis is absent the
    # guard cannot run, but the margin-independent uplift/revenue claim still stands.
    revenue_uplift_minor: int | None = None
    margin_impact_minor: int | None = None
    margin_reason_code: str | None = None
    if first_failure is None:
        revenue_uplift_minor = int(round(point * control_mean_revenue * horizon))
        incremental_units = point * control_mean_units * horizon
        episode_unit_price = (
            episode_mean_revenue / episode_mean_units if episode_mean_units > 0.0 else None
        )
        wac_unit_cost = _first_scalar(group, "wac_unit_cost_minor")
        if wac_unit_cost is not None and episode_unit_price is not None:
            margin_impact_minor = int(
                round(incremental_units * (episode_unit_price - float(wac_unit_cost)))
            )
            if bool(acceptance.get("requirePositiveMargin", False)) and margin_impact_minor <= 0:
                first_failure = reasons["marginDilution"]
        else:
            margin_reason_code = reasons["missingCostBasis"]

    accepted = first_failure is None
    if not accepted:
        # A withheld promotion makes no numeric uplift/revenue/margin claim at all.
        revenue_uplift_minor = None
        margin_impact_minor = None
        margin_reason_code = None

    # Baseline (control) revenue over the horizon and the promoted-demand stock
    # requirement are reported only for an accepted promotion, alongside its uplift.
    # Both come straight from the observed control mean and the accepted point lift —
    # the baseline the Planner charts against, and the units needed to serve the lift.
    baseline_revenue_minor: int | None = None
    required_stock_units: int | None = None
    if accepted and point is not None:
        baseline_revenue_minor = int(round(control_mean_revenue * horizon))
        required_stock_units = int(round(control_mean_units * (1.0 + point) * horizon))

    return {
        "market_id": str(market_id),
        "promo_id": str(promo_id),
        "promo_name": str(_first_scalar(group, "promo_name", promo_id)),
        "promo_type": (
            str(_first_scalar(group, "promo_type"))
            if _first_scalar(group, "promo_type") is not None
            else None
        ),
        "episode_weeks": n_episode,
        "control_weeks": n_control,
        "expected_demand_uplift": (float(point) if accepted else None),
        "uplift_low": (uplift_low if accepted else None),
        "uplift_high": (uplift_high if accepted else None),
        "revenue_uplift_minor": revenue_uplift_minor,
        "margin_impact_minor": margin_impact_minor,
        "margin_reason_code": margin_reason_code,
        "baseline_revenue_minor": baseline_revenue_minor,
        "required_stock_units": required_stock_units,
        # Cannibalisation stays an explicit privacy-restricted state (Decision #19),
        # never a fabricated number and never a silent omission.
        "cannibalisation_risk": str(policy["privacyReason"]),
        "confidence": (confidence if accepted else None),
        "valid_draws": valid_draws,
        "numeric_result_rate": float(numeric_result_rate),
        "acceptance_status": "accepted" if accepted else "withheld",
        "first_failure_reason": first_failure,
    }


def estimate_promotion_uplift(
    weekly: pd.DataFrame, *, policy: Mapping[str, Any]
) -> pd.DataFrame:
    """Estimate per-promotion demand uplift from a tidy weekly episode/control panel.

    ``weekly`` carries one row per (market_id, promo_id, role, week_start) with
    ``role`` in {``episode``, ``control``}, ``units`` and ``net_sales_minor``, plus
    an optional constant ``wac_unit_cost_minor`` per promotion for the margin basis.
    """

    required = {"market_id", "promo_id", "role", "week_start", "units", "net_sales_minor"}
    missing = sorted(required - set(weekly.columns))
    if missing:
        raise PromotionFoundationError(
            "promotion weekly panel lacks: " + ", ".join(missing)
        )
    if weekly.empty:
        return pd.DataFrame(columns=list(UPLIFT_RESULT_COLUMNS))
    rows = [
        _evaluate_promotion(market_id, promo_id, group, policy=policy)
        for (market_id, promo_id), group in weekly.groupby(
            ["market_id", "promo_id"], sort=True, dropna=False
        )
    ]
    return (
        pd.DataFrame(rows, columns=list(UPLIFT_RESULT_COLUMNS))
        .sort_values(["market_id", "promo_id"])
        .reset_index(drop=True)
    )


def build_promotion_disposition(
    uplift: pd.DataFrame,
    *,
    protection_policy: Mapping[str, Any],
    uplift_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Flip the Planner package disposition from the estimator outcome.

    When at least one promotion is accepted the package is ``positive`` and the
    numeric uplift/margin/simulation claims are allowed for accepted promotions
    only; PII, customer targeting, cannibalisation and bundle response remain
    explicit ``privacy_restricted`` states rather than silent omissions.
    """

    accepted = (
        uplift[uplift["acceptance_status"] == "accepted"]
        if not uplift.empty
        else uplift
    )
    accepted_count = int(len(accepted))
    evaluated_count = int(len(uplift))
    positive = accepted_count >= 1
    if positive:
        first_failure = None
    elif evaluated_count:
        codes = [
            code
            for code in uplift["first_failure_reason"].tolist()
            if isinstance(code, str) and code
        ]
        first_failure = (
            Counter(codes).most_common(1)[0][0]
            if codes
            else uplift_policy["reasonCodes"]["plannerUnsupported"]
        )
    else:
        first_failure = uplift_policy["reasonCodes"]["plannerUnsupported"]
    estimator = uplift_policy["estimator"]
    acceptance = uplift_policy["acceptance"]
    return {
        "schemaVersion": str(uplift_policy["dispositionSchemaVersion"]),
        "decisionId": int(uplift_policy["decisionId"]),
        "decisionDisposition": str(uplift_policy["decisionDisposition"]),
        "packageDisposition": "positive" if positive else "negative",
        "plannerAvailable": positive,
        "firstFailureReason": first_failure,
        "acceptedPromotionCount": accepted_count,
        "evaluatedPromotionCount": evaluated_count,
        # Numeric claims are authorised only on the positive branch, and only for
        # the accepted promotions the result frame marks as accepted.
        "allowedClaims": list(uplift_policy["allowedClaims"]) if positive else [],
        "restrictedClaims": list(uplift_policy["restrictedClaims"]),
        "protectionDecisionId": int(protection_policy["decisionId"]),
        "protectionDecisionDisposition": str(protection_policy["decisionDisposition"]),
        # Frozen so the serving layer evaluates stored parameters, never refits.
        "estimatorParameters": {
            "policyFingerprint": str(uplift_policy["policyFingerprint"]),
            "seed": int(estimator["seed"]),
            "perPromotionSeedRecipe": str(estimator["perPromotionSeedRecipe"]),
            "resampleDraws": int(estimator["resampleDraws"]),
            "blockLengthWeeks": int(estimator["blockLengthWeeks"]),
            "controlLookbackDays": int(estimator["controlLookbackDays"]),
            "holdoutEpisodeWeeks": int(estimator["holdoutEpisodeWeeks"]),
            "horizonWeeks": int(uplift_policy["horizonWeeks"]),
            "intervalLowerQuantile": str(estimator["intervalLowerQuantile"]),
            "intervalUpperQuantile": str(estimator["intervalUpperQuantile"]),
            "acceptance": {
                "minEpisodeWeeks": int(acceptance["minEpisodeWeeks"]),
                "minControlWeeks": int(acceptance["minControlWeeks"]),
                "minimumValidDraws": int(acceptance["minimumValidDraws"]),
                "numericResultRateMin": str(acceptance["numericResultRateMin"]),
                "minPointUplift": str(acceptance["minPointUplift"]),
                "holdoutMinUplift": str(acceptance["holdoutMinUplift"]),
                "requirePositiveMargin": bool(acceptance["requirePositiveMargin"]),
            },
        },
    }


def _empty_uplift_panel() -> pd.DataFrame:
    return pd.DataFrame(columns=list(_UPLIFT_PANEL_COLUMNS))


def _resolve_scope_skus(
    promo_id: str, targets: pd.DataFrame, products: pd.DataFrame
) -> list[str]:
    scope = targets[targets["promo_id"] == promo_id]
    skus: set[str] = set()
    for target in scope.to_dict("records"):
        scope_type = str(target["merch_scope_type"])
        scope_id = str(target["merch_scope_id"])
        if scope_type == "sku":
            skus.add(scope_id)
        elif scope_type == "category":
            skus.update(products.loc[products["category"] == scope_id, "sku_id"].astype(str))
        elif scope_type == "dept":
            skus.update(products.loc[products["dept_id"] == scope_id, "sku_id"].astype(str))
    return sorted(skus)


def _local_id(value: Any, market_id: str) -> str:
    """Strip a leading ``<market_id>:`` prefix so market-scoped and local ids compare.

    Sales/stores carry market-prefixed ids (``gulf-india:gulf-marketplace``) while
    ``promotion_scopes`` carries local ids (``gulf-marketplace``); normalising both
    sides makes the geography match convention-agnostic.
    """

    text = str(value)
    prefix = f"{market_id}:"
    return text[len(prefix):] if text.startswith(prefix) else text


def _resolve_allowed_pairs(
    promo_id: str,
    market_id: str,
    scopes: pd.DataFrame,
    stores: pd.DataFrame,
    channels: list[str],
) -> list[tuple[str, str]]:
    scope_rows = scopes[scopes["promo_id"] == promo_id].to_dict("records")

    def _matches(store: Mapping[str, Any], channel: str, row: Mapping[str, Any]) -> bool:
        # Within-row AND across the nullable region/location/channel dimensions.
        checks = (
            (store.get("region"), row.get("region"), False),
            (store.get("store_id"), row.get("location_id"), True),
            (channel, row.get("channel_id"), True),
        )
        for actual, expected, localize in checks:
            if expected is None or pd.isna(expected) or str(expected) == "":
                continue
            left = _local_id(actual, market_id) if localize else str(actual)
            right = _local_id(expected, market_id) if localize else str(expected)
            if left != right:
                return False
        return True

    pairs: set[tuple[str, str]] = set()
    for store in stores.to_dict("records"):
        for channel in channels:
            if not scope_rows or any(_matches(store, channel, row) for row in scope_rows):
                # keep the raw (market-scoped) ids for the sales pair filter.
                pairs.add((str(store["store_id"]), str(channel)))
    return sorted(pairs)


def _promotion_weekly(
    connection: duckdb.DuckDBPyConnection,
    promo: Mapping[str, Any],
    *,
    targets: pd.DataFrame,
    scopes: pd.DataFrame,
    products: pd.DataFrame,
    stores: pd.DataFrame,
    sku_cost: Mapping[str, float],
    decision_as_of: datetime | str,
    lookback_days: int,
    buffer_weeks: int,
) -> pd.DataFrame | None:
    promo_id = str(promo["promo_id"])
    skus = _resolve_scope_skus(promo_id, targets, products)
    if not skus:
        return None
    start = pd.Timestamp(promo["start_date"])
    end = pd.Timestamp(promo["end_date"])
    lookback_start = start - pd.Timedelta(days=int(lookback_days))
    channels = [
        str(row[0])
        for row in connection.execute(
            f"""
            SELECT DISTINCT channel_id FROM canonical_data.sales
            WHERE sku_id IN ({",".join(["?"] * len(skus))})
              AND date BETWEEN ?::DATE AND ?::DATE
              AND known_as_of <= ?::TIMESTAMPTZ
            """,
            [*skus, lookback_start.date(), end.date(), decision_as_of],
        ).fetchall()
    ]
    pairs = _resolve_allowed_pairs(
        promo_id, str(promo["market_id"]), scopes, stores, channels
    )
    if not pairs:
        return None
    pair_values = ", ".join(["(?, ?)"] * len(pairs))
    pair_params = [value for pair in pairs for value in pair]
    sku_placeholders = ",".join(["?"] * len(skus))
    weekly = connection.execute(
        f"""
        WITH visible AS (
            SELECT sku_id, store_id, channel_id, date, units,
                   net_sales_amount, promo_flag
            FROM canonical_data.sales
            WHERE sku_id IN ({sku_placeholders})
              AND (store_id, channel_id) IN (VALUES {pair_values})
              AND date BETWEEN ?::DATE AND ?::DATE
              AND known_as_of <= ?::TIMESTAMPTZ
            QUALIFY row_number() OVER (
                PARTITION BY sku_id, store_id, channel_id, date
                ORDER BY sales_version DESC, known_as_of DESC
            ) = 1
        )
        SELECT date_trunc('week', date)::DATE AS week_start,
               sum(units)::BIGINT AS units,
               sum(net_sales_amount)::BIGINT AS net_sales_minor,
               bool_or(coalesce(promo_flag, FALSE)) AS promo_flag_any
        FROM visible
        GROUP BY 1
        ORDER BY 1
        """,
        [*skus, *pair_params, lookback_start.date(), end.date(), decision_as_of],
    ).fetch_df()
    if weekly.empty:
        return None
    weekly["week_start"] = pd.to_datetime(weekly["week_start"])
    episode_from = start.normalize() - pd.Timedelta(days=start.weekday())
    control_to = start.normalize() - pd.Timedelta(weeks=int(buffer_weeks))
    is_episode = (weekly["week_start"] >= episode_from) & (
        weekly["week_start"] <= end.normalize()
    )
    is_control = (
        (weekly["week_start"] >= lookback_start.normalize())
        & (weekly["week_start"] < control_to)
        & (~weekly["promo_flag_any"].astype(bool))
    )
    weekly = weekly[is_episode | is_control].copy()
    if weekly.empty:
        return None
    weekly["role"] = np.where(is_episode.loc[weekly.index], "episode", "control")
    weekly["market_id"] = str(promo["market_id"])
    weekly["promo_id"] = promo_id
    weekly["promo_name"] = str(promo.get("promo_name", promo_id))
    weekly["promo_type"] = promo.get("promo_type")
    # Scope WAC = mean of the latest per-SKU weighted-average cost of record — the
    # accepted authoritative cost basis for the incremental-margin claim (§0.0).
    scope_costs = [float(sku_cost[sku]) for sku in skus if sku in sku_cost]
    weekly["wac_unit_cost_minor"] = (
        float(np.mean(scope_costs)) if scope_costs else np.nan
    )
    return weekly[list(_UPLIFT_PANEL_COLUMNS)]


def _load_promotion_metadata(
    connection: Any, decision_as_of: datetime | str
) -> pd.DataFrame | None:
    """Resolve per-promotion source metadata for the served Planner portfolio.

    Returns one row per ``(market_id, promo_id)`` with the promotion window, offer,
    catalogue coverage and channel scope, read from the same canonical facts the
    estimator uses. SKU targets join to the product catalogue for human category
    labels; scope rows count distinct channels and note whether the plan is
    market-wide. A curated publication that predates any of these source columns
    degrades to ``None`` (null cells) rather than aborting the uplift estimation.
    """

    try:
        return connection.execute(
            """
            WITH tgt AS (
                SELECT market_id, promo_id, merch_scope_id AS sku_id
                FROM canonical_data.promotion_merchandise_targets
                WHERE merch_scope_type = 'sku' AND known_as_of <= ?::TIMESTAMPTZ
                GROUP BY market_id, promo_id, merch_scope_id
            ),
            prod AS (
                SELECT sku_id, category_label
                FROM canonical_data.products
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY sku_id ORDER BY known_as_of DESC
                ) = 1
            ),
            cat AS (
                SELECT t.market_id, t.promo_id,
                       count(DISTINCT t.sku_id) AS product_count,
                       count(DISTINCT p.category_label) AS category_count,
                       string_agg(DISTINCT p.category_label, ', ') AS category_labels
                FROM tgt t LEFT JOIN prod p USING (sku_id)
                GROUP BY t.market_id, t.promo_id
            ),
            sc AS (
                SELECT market_id, promo_id,
                       count(DISTINCT channel_id) AS channel_count,
                       bool_and(location_id IS NULL) AS all_stores
                FROM canonical_data.promotion_scopes
                WHERE known_as_of <= ?::TIMESTAMPTZ
                GROUP BY market_id, promo_id
            )
            SELECT pr.market_id, pr.promo_id,
                   pr.start_date AS period_start, pr.end_date AS period_end,
                   pr.offer_value, pr.objective, pr.status,
                   cat.category_labels, cat.category_count, cat.product_count,
                   sc.channel_count, sc.all_stores
            FROM (
                SELECT market_id, promo_id, start_date, end_date,
                       offer_value, objective, status
                FROM canonical_data.promotions
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id ORDER BY known_as_of DESC
                ) = 1
            ) pr
            LEFT JOIN cat USING (market_id, promo_id)
            LEFT JOIN sc USING (market_id, promo_id)
            """,
            [decision_as_of, decision_as_of, decision_as_of, decision_as_of],
        ).fetch_df()
    except duckdb.Error:
        return None


def build_promotion_uplift(
    curated_database: str | Path,
    *,
    decision_as_of: datetime | str,
    protection_policy: Mapping[str, Any],
    uplift_policy: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build the per-promotion uplift result frame and the Planner disposition.

    Mirrors ``build_competitor_foundation`` — reads the curated canonical facts,
    runs the frozen estimator, and returns a result frame plus a JSON disposition
    consumable by the pricing bundle. Only *completed* promotions (fully observed
    episodes as of the decision cutoff) are evaluated.
    """

    database = Path(curated_database)
    if not database.is_file():
        raise PromotionFoundationError(f"curated database is absent: {database}")
    lookback_days = int(uplift_policy["estimator"]["controlLookbackDays"])
    buffer_weeks = int(uplift_policy["estimator"].get("controlBufferWeeks", 0))
    as_of = pd.Timestamp(decision_as_of)
    frames: list[pd.DataFrame] = []
    metadata: pd.DataFrame | None = None
    with duckdb.connect(str(database), read_only=True) as connection:
        try:
            promotions = connection.execute(
                """
                SELECT market_id, promo_id, name AS promo_name,
                       type AS promo_type, start_date, end_date
                FROM canonical_data.promotions
                WHERE known_as_of <= ?::TIMESTAMPTZ
                  AND end_date < ?::DATE
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id ORDER BY known_as_of DESC
                ) = 1
                ORDER BY market_id, promo_id
                """,
                [decision_as_of, as_of.date()],
            ).fetch_df()
            targets = connection.execute(
                """
                SELECT market_id, promo_id, merch_scope_type, merch_scope_id
                FROM canonical_data.promotion_merchandise_targets
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id, merch_scope_type, merch_scope_id
                    ORDER BY known_as_of DESC
                ) = 1
                """,
                [decision_as_of],
            ).fetch_df()
            scopes = connection.execute(
                """
                SELECT market_id, promo_id, scope_row_id, region,
                       location_id, channel_id
                FROM canonical_data.promotion_scopes
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY market_id, promo_id, scope_row_id
                    ORDER BY known_as_of DESC
                ) = 1
                """,
                [decision_as_of],
            ).fetch_df()
            products = connection.execute(
                """
                SELECT sku_id, dept_id, category
                FROM canonical_data.products
                WHERE known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY sku_id ORDER BY known_as_of DESC
                ) = 1
                """,
                [decision_as_of],
            ).fetch_df()
            stores = connection.execute(
                "SELECT store_id, market_id, region FROM canonical_data.stores"
            ).fetch_df()
            costs = connection.execute(
                """
                SELECT sku_id, avg(wac_cost)::DOUBLE AS wac_cost
                FROM (
                    SELECT sku_id, location_id, wac_cost
                    FROM canonical_data.inventory_cost
                    WHERE known_as_of <= ?::TIMESTAMPTZ
                    QUALIFY row_number() OVER (
                        PARTITION BY sku_id, location_id
                        ORDER BY as_of_date DESC, known_as_of DESC
                    ) = 1
                )
                GROUP BY sku_id
                """,
                [decision_as_of],
            ).fetch_df()
            sku_cost = {
                str(row["sku_id"]): float(row["wac_cost"])
                for row in costs.to_dict("records")
                if pd.notna(row["wac_cost"])
            }
            metadata = _load_promotion_metadata(connection, decision_as_of)
            for promo in promotions.to_dict("records"):
                frame = _promotion_weekly(
                    connection,
                    promo,
                    targets=targets,
                    scopes=scopes,
                    products=products,
                    stores=stores,
                    sku_cost=sku_cost,
                    decision_as_of=decision_as_of,
                    lookback_days=lookback_days,
                    buffer_weeks=buffer_weeks,
                )
                if frame is not None and not frame.empty:
                    frames.append(frame)
        except duckdb.Error:
            # A curated publication that predates the promotion feed leaves the
            # Planner on its negative branch rather than failing the build.
            frames = []
    weekly = pd.concat(frames, ignore_index=True) if frames else _empty_uplift_panel()
    uplift = estimate_promotion_uplift(weekly, policy=uplift_policy)
    uplift = _attach_promotion_metadata(uplift, metadata)
    disposition = build_promotion_disposition(
        uplift, protection_policy=protection_policy, uplift_policy=uplift_policy
    )
    return uplift, disposition


def _attach_promotion_metadata(
    uplift: pd.DataFrame, metadata: pd.DataFrame | None
) -> pd.DataFrame:
    """Merge per-promotion source metadata onto the estimator result frame.

    The metadata is looked up from the curated canonical facts by
    ``(market_id, promo_id)``. A promotion with no metadata match keeps null cells
    rather than a fabricated value, and the metadata columns are always present so
    the served copy has a stable shape whether or not any promotion was evaluated.
    """

    result = uplift.copy()
    if metadata is not None and not metadata.empty:
        keep = ["market_id", "promo_id", *_PROMO_METADATA_COLUMNS]
        available = [column for column in keep if column in metadata.columns]
        result = result.merge(
            metadata[available], on=["market_id", "promo_id"], how="left"
        )
    for column in _PROMO_METADATA_COLUMNS:
        if column not in result.columns:
            result[column] = pd.Series([None] * len(result), dtype="object")
    return result


__all__ = [
    "PROMOTION_COLUMNS", "UPLIFT_RESULT_COLUMNS", "PromotionFoundationError",
    "assess_promotion_protection", "build_promotion_disposition",
    "build_promotion_foundation", "build_promotion_uplift",
    "estimate_promotion_uplift", "load_promotion_policy",
    "load_promotion_uplift_policy",
]
