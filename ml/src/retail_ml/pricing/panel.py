"""Point-in-time weekly SKU × store × channel pricing panel."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from retail_contracts.fingerprint import semantic_fingerprint

POLICY_IDENTITY_EXCLUDES = ("/policyFingerprint",)


class PricingPanelError(RuntimeError):
    """The canonical publication cannot support a truthful pricing panel."""


def load_response_policy(path: str | Path) -> dict[str, Any]:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = semantic_fingerprint(
        policy, volatile_pointers=POLICY_IDENTITY_EXCLUDES
    )
    if policy.get("policyFingerprint") != expected:
        raise PricingPanelError("response-evaluation policy fingerprint mismatch")
    origins = policy.get("origins") or []
    if len(origins) != 13:
        raise PricingPanelError("response policy must declare exactly 13 origins")
    indices = [int(row["index"]) for row in origins]
    dates = [str(row["originDate"]) for row in origins]
    if indices != list(range(1, 14)) or dates != sorted(dates):
        raise PricingPanelError("response origins are not contiguous and chronological")
    if [row["purpose"] for row in origins[:8]] != ["development"] * 8:
        raise PricingPanelError("origins 1-8 must be development origins")
    if [row["purpose"] for row in origins[8:]] != ["confirmation"] * 5:
        raise PricingPanelError("origins 9-13 must be confirmation origins")
    model = policy.get("model") or {}
    if model.get("baseline") != "same_controls_without_log_price":
        raise PricingPanelError("response baseline must remove only the log-price term")
    exposure = (policy.get("panel") or {}).get("exposureSemantics")
    if exposure != {
        "unitMeaning": "fulfilled_customer_units_including_dc_substitution",
        "zeroUnitWeeks": "explicit_closed_source_week",
        "offset": "none",
        "storeAvailabilityControl": "store_shortfall_share",
        "shortfallUnitsMustNotBeAddedToResponse": True,
    }:
        raise PricingPanelError("response exposure semantics changed")
    from retail_ml.pricing.response import FEATURE_NAMES

    if model.get("features") != list(FEATURE_NAMES):
        raise PricingPanelError("response feature registry differs from implementation")
    rules = policy.get("originRules") or {}
    if rules.get("priceTier") != {
        "anchor": "median_regular_price_before_first_confirmation",
        "quantiles": ["0.25", "0.50", "0.75"],
    }:
        raise PricingPanelError("response price-tier protocol changed")
    candidates = rules.get("candidateConfigurations") or []
    if not candidates or len(candidates) > int(
        rules.get("maximumCandidateConfigurations", 0)
    ):
        raise PricingPanelError("response candidate registry exceeds its frozen budget")
    if len({candidate.get("id") for candidate in candidates}) != len(candidates):
        raise PricingPanelError("response candidate ids must be unique")
    if any(
        candidate.get("shrinkage")
        not in {"none", "department", "department_price_tier"}
        for candidate in candidates
    ):
        raise PricingPanelError("response candidate has an unsupported shrinkage mode")
    if any("confirmation" in str(item) for item in rules.get("tieBreak", [])):
        raise PricingPanelError("response candidate selection cannot read confirmation origins")
    return policy


def _columns(connection: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {str(row[0]) for row in connection.execute(f"DESCRIBE {table}").fetchall()}


def _as_utc(value: datetime | str) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def build_weekly_panel(
    curated_database: str | Path,
    *,
    decision_as_of: datetime | str,
    allow_empty: bool = False,
) -> pd.DataFrame:
    """Build a complete weekly panel from point-in-time eligible canonical facts.

    `assortment_calendar` defines eligible weeks. `sell_prices` is an effective
    price-change stream, so the latest point-in-time-visible price is carried
    forward until the next change. Weeks with no source sales rows are explicit
    zero observations only after the source week closes; this conservative
    closed-period timestamp is retained in `sales_known_as_of`.
    """

    database = Path(curated_database)
    if not database.is_file():
        raise PricingPanelError(f"curated database is absent: {database}")
    as_of = _as_utc(decision_as_of)
    with duckdb.connect(str(database), read_only=True) as connection:
        price_columns = _columns(connection, "canonical_data.sell_prices")
        provenance = (
            "coalesce(p.provenance_class, 'unclassified')"
            if "provenance_class" in price_columns
            else "'unclassified'"
        )
        generation_method = (
            "p.generation_method"
            if "generation_method" in price_columns
            else "NULL::VARCHAR"
        )
        query = f"""
            WITH weekly_sales AS (
                SELECT
                    sku_id, store_id, channel_id,
                    date_trunc('week', date)::DATE AS week_start,
                    sum(units)::BIGINT AS units,
                    sum(net_sales_amount)::BIGINT AS net_sales_minor,
                    bool_or(promo_flag)::BOOLEAN AS promotion_flag,
                    max(known_as_of) AS sales_known_as_of,
                    string_agg(
                        DISTINCT known_as_of_evidence_grade,
                        ',' ORDER BY known_as_of_evidence_grade
                    ) AS sales_evidence_grades
                FROM canonical_data.sales
                WHERE date <= ?::DATE
                  AND known_as_of <= ?::TIMESTAMPTZ
                GROUP BY 1, 2, 3, 4
            ), weekly_shortfalls AS (
                SELECT
                    sku_id, location_id AS store_id, channel_id,
                    date_trunc('week', event_date)::DATE AS week_start,
                    sum(shortfall_units)::BIGINT AS store_shortfall_units,
                    max(known_as_of) AS availability_known_as_of,
                    string_agg(
                        DISTINCT known_as_of_evidence_grade,
                        ',' ORDER BY known_as_of_evidence_grade
                    ) AS availability_evidence_grades
                FROM canonical_data.store_shortfall_events
                WHERE event_date <= ?::DATE
                  AND known_as_of <= ?::TIMESTAMPTZ
                GROUP BY 1, 2, 3, 4
            ), visible_assortment AS (
                SELECT
                    a.sku_id, a.store_id, a.channel_id,
                    a.active_from, a.active_to
                FROM canonical_data.assortment_calendar AS a
                WHERE a.active_from <= ?::DATE
                  AND a.known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY a.sku_id, a.store_id, a.channel_id
                    ORDER BY a.known_as_of DESC, a.active_from DESC
                ) = 1
            ), eligible_weeks AS (
                SELECT
                    a.sku_id, a.store_id, a.channel_id,
                    generated.week_start::DATE AS week_start
                FROM visible_assortment AS a
                CROSS JOIN LATERAL generate_series(
                    date_trunc('week', a.active_from)::DATE,
                    date_trunc(
                        'week', least(coalesce(a.active_to, ?::DATE), ?::DATE)
                    )::DATE,
                    INTERVAL 1 WEEK
                ) AS generated(week_start)
                WHERE generated.week_start::DATE + INTERVAL 7 DAY <= ?::DATE
            ), prices AS (
                SELECT
                    g.sku_id, g.store_id, g.channel_id, g.week_start,
                    p.net_price, p.regular_price, p.promo_price,
                    p.currency_code, p.source_price_path_id,
                    p.known_as_of AS price_known_as_of,
                    p.known_as_of_evidence_grade AS price_evidence_grade,
                    {provenance}::VARCHAR AS provenance_class,
                    {generation_method}::VARCHAR AS generation_method
                FROM eligible_weeks AS g
                JOIN canonical_data.sell_prices AS p
                  ON p.sku_id = g.sku_id
                 AND p.store_id = g.store_id
                 AND p.channel_id = g.channel_id
                 AND p.week_start <= g.week_start
                WHERE p.known_as_of <= ?::TIMESTAMPTZ
                QUALIFY row_number() OVER (
                    PARTITION BY g.sku_id, g.store_id, g.channel_id, g.week_start
                    ORDER BY p.week_start DESC, p.known_as_of DESC,
                             p.source_price_path_id DESC
                ) = 1
            )
            SELECT
                s.market_id, p.sku_id, p.store_id, p.channel_id,
                p.week_start,
                coalesce(w.units, 0)::BIGINT AS units,
                coalesce(sf.store_shortfall_units, 0)::BIGINT
                    AS store_shortfall_units,
                CASE
                    WHEN coalesce(w.units, 0) <= 0 THEN 0::DOUBLE
                    ELSE least(
                        1::DOUBLE,
                        coalesce(sf.store_shortfall_units, 0)::DOUBLE
                        / w.units::DOUBLE
                    )
                END AS store_shortfall_share,
                (coalesce(sf.store_shortfall_units, 0) > 0)::BOOLEAN
                    AS store_availability_constrained,
                coalesce(w.net_sales_minor, 0)::BIGINT AS net_sales_minor,
                p.net_price::BIGINT AS net_price_minor,
                p.regular_price::BIGINT AS regular_price_minor,
                p.promo_price::BIGINT AS promo_price_minor,
                coalesce(w.promotion_flag, p.promo_price IS NOT NULL)::BOOLEAN
                    AS promotion_flag,
                p.currency_code,
                p.source_price_path_id,
                p.price_known_as_of,
                coalesce(
                    w.sales_known_as_of,
                    (p.week_start + INTERVAL 7 DAY)::TIMESTAMPTZ
                ) AS sales_known_as_of,
                coalesce(
                    sf.availability_known_as_of,
                    (p.week_start + INTERVAL 7 DAY)::TIMESTAMPTZ
                ) AS availability_known_as_of,
                p.price_evidence_grade,
                coalesce(w.sales_evidence_grades, 'derived_closed_period')::VARCHAR
                    AS sales_evidence_grades,
                coalesce(
                    sf.availability_evidence_grades,
                    'derived_closed_period'
                )::VARCHAR AS availability_evidence_grades,
                (w.units IS NULL)::BOOLEAN AS zero_observation,
                CASE WHEN w.units IS NULL THEN 'closed_source_week'
                     ELSE 'source_transactions' END::VARCHAR
                    AS zero_observation_method,
                p.provenance_class,
                p.generation_method,
                pr.dept_id AS department_id,
                pr.category,
                pr.product_name,
                c.type AS channel_type,
                s.region,
                s.currency_code AS market_currency_code
            FROM prices AS p
            JOIN canonical_data.stores AS s USING (store_id)
            JOIN canonical_data.products AS pr USING (sku_id)
            LEFT JOIN canonical_data.channels AS c
              ON c.market_id = s.market_id AND c.channel_id = p.channel_id
            LEFT JOIN weekly_sales AS w
              ON w.sku_id = p.sku_id
             AND w.store_id = p.store_id
             AND w.channel_id = p.channel_id
             AND w.week_start = p.week_start
            LEFT JOIN weekly_shortfalls AS sf
              ON sf.sku_id = p.sku_id
             AND sf.store_id = p.store_id
             AND sf.channel_id = p.channel_id
             AND sf.week_start = p.week_start
            ORDER BY s.market_id, p.sku_id, p.store_id, p.channel_id, p.week_start
        """
        frame = connection.execute(
            query,
            [
                as_of.date(),
                as_of,
                as_of.date(),
                as_of,
                as_of.date(),
                as_of,
                as_of.date(),
                as_of.date(),
                as_of.date(),
                as_of,
            ],
        ).fetch_df()
    if frame.empty and not allow_empty:
        raise PricingPanelError("weekly pricing panel is empty")
    if frame["regular_price_minor"].isna().any():
        raise PricingPanelError("weekly pricing panel contains null regular prices")
    if (frame["currency_code"] != frame["market_currency_code"]).any():
        raise PricingPanelError("operating price currency differs from market currency")
    frame["week_start"] = pd.to_datetime(frame["week_start"], utc=True)
    frame["price_known_as_of"] = pd.to_datetime(
        frame["price_known_as_of"], utc=True
    )
    frame["sales_known_as_of"] = pd.to_datetime(
        frame["sales_known_as_of"], utc=True
    )
    frame["availability_known_as_of"] = pd.to_datetime(
        frame["availability_known_as_of"], utc=True
    )
    frame["decision_as_of"] = pd.Timestamp(as_of)
    return frame


__all__ = ["PricingPanelError", "build_weekly_panel", "load_response_policy"]
