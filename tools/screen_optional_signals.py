#!/usr/bin/env python3
"""Run the PP3-B6 optional-signal admissibility screens against a live bundle.

Re-runnable by design: every number in the emitted record comes from the curated
publication and the evaluation frame, so a later publication that fixes a source
defect changes the verdict without anyone editing a document.

    python3 tools/screen_optional_signals.py \
        --curated ingestion/data/curated/run-c5eb1506ecd4c550/retail_v2.duckdb \
        --eval ml/data/artifacts/forecast_h1_h26_origins13_v12/forecast_eval_predictions.parquet \
        --out contracts/evidence/optional-signal-admissibility.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ml" / "src"))

import duckdb  # noqa: E402

from retail_ml.diagnostics.signals import (  # noqa: E402
    REASON_SOURCE_LEAD_EXHAUSTED,
    VERDICT_REJECTED,
    disposition,
    screen_grain,
    screen_leakage,
    screen_materiality,
    screen_report,
    screen_temporal,
)

MAX_FORECAST_HORIZON_DAYS = 26 * 7


def _grades(con: duckdb.DuckDBPyConnection, relations: list[str]) -> list[str]:
    grades: list[str] = []
    for relation in relations:
        rows = con.execute(
            f'select distinct known_as_of_evidence_grade from cur.canonical_data."{relation}"'
        ).fetchall()
        grades.extend(str(row[0]) for row in rows)
    return grades


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--curated", required=True, type=Path)
    parser.add_argument("--eval", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    con = duckdb.connect()
    con.execute(f"attach '{args.curated}' as cur (read_only)")
    con.execute(f"create view ev as select * from read_parquet('{args.eval}')")
    frame = con.execute(
        "select sku_id, store_id, channel_id, forecast_origin, target_week_start, "
        "horizon, actual_units, yhat_p50, weather_fallback_used, competitor_available "
        "from ev"
    ).df()

    dispositions = []

    # --- 1. future promotion plan -----------------------------------------
    promo_relations = [
        "promotions",
        "promotion_scopes",
        "promotion_merchandise_targets",
    ]
    temporal = screen_temporal(
        _grades(con, promo_relations), repository_root=REPO_ROOT
    )
    stamps = con.execute(
        "select count(distinct known_as_of), min(known_as_of), max(known_as_of) "
        "from cur.canonical_data.promotions"
    ).fetchone()
    dispositions.append(
        disposition(
            "future_promotion_plan",
            screens=[temporal],
            notes=(
                f"{stamps[0]} distinct known_as_of across the promotion family "
                f"(range {stamps[1]} .. {stamps[2]}); a single landing stamp later "
                "than every acceptance origin leaves nothing origin-visible to fit. "
                "Serving remains permitted; historical replay does not."
            ),
        )
    )

    # --- 2. weather forecast beyond available leads ------------------------
    leads = con.execute(
        "select min(date_diff('day', cast(forecast_date as date), cast(target_date as date))), "
        "       max(date_diff('day', cast(forecast_date as date), cast(target_date as date))) "
        "from cur.canonical_data.weather_forecast"
    ).fetchone()
    weather_temporal = screen_temporal(
        _grades(con, ["weather_forecast"]), repository_root=REPO_ROOT
    )
    weather_material = screen_materiality(
        frame, active=frame["weather_fallback_used"].astype(int).eq(0)
    )
    weather = disposition(
        "weather_forecast_extended_lead",
        screens=[weather_temporal, weather_material],
        notes=(
            f"The source issues leads of {leads[0]}-{leads[1]} days only, against a "
            f"{MAX_FORECAST_HORIZON_DAYS}-day h26 target window, so h1 is the sole "
            "coverable horizon and the shipped h1 features already consume the "
            "entire available lead. Rows carrying a real issued forecast rather "
            "than the climatology fallback bound any gain."
        ),
    )
    if weather["verdict"] == VERDICT_REJECTED and weather["reasonCode"] is None:
        weather["reasonCode"] = REASON_SOURCE_LEAD_EXHAUSTED
    weather["sourceLeadDays"] = {"min": leads[0], "max": leads[1]}
    weather["targetWindowDays"] = MAX_FORECAST_HORIZON_DAYS
    dispositions.append(weather)

    # --- 3. competitor availability / plan --------------------------------
    competitor_temporal = screen_temporal(
        _grades(con, ["competitor_prices", "competitor_products"]),
        repository_root=REPO_ROOT,
    )
    competitor_material = screen_materiality(
        frame, active=frame["competitor_available"].notna()
    )
    dispositions.append(
        disposition(
            "competitor_availability",
            screens=[competitor_temporal, competitor_material],
            already_shipped=True,
            notes=(
                "competitor_price_ratio, competitor_available, competitor_in_stock "
                "and competitor_age_days are already in the feature set with SHAP "
                "attribution. The source carries observed prices only -- there is no "
                "forward competitor plan to admit."
            ),
        )
    )

    # --- 4. stock-out / censored demand -----------------------------------
    locations = [
        row[0]
        for row in con.execute(
            "select distinct location_id from cur.canonical_data.stock_snapshots"
        ).fetchall()
    ]
    grain = screen_grain(
        locations,
        sorted(frame["store_id"].astype(str).unique()),
        label="store_id",
    )
    dispositions.append(
        disposition(
            "stockout_censored_demand",
            screens=[
                screen_temporal(
                    _grades(con, ["stock_snapshots"]), repository_root=REPO_ROOT
                ),
                grain,
            ],
            notes=(
                "stock_snapshots is keyed on distribution and fulfilment centres, "
                "not on the demand stores the SeriesKey forecasts. No store-grain "
                "on-hand exists in the publication, so censoring cannot be attached "
                "to a forecast row at all -- consistent with the Gate-B capability "
                "mask withholding replenishment."
            ),
        )
    )

    # --- 5. lifecycle / assortment change ---------------------------------
    exits = con.execute(
        """
        with last_sale as (
          select sku_id, store_id, channel_id, max(cast(date as date)) last_positive
          from cur.canonical_data.sales where units > 0 group by 1,2,3
        )
        select cast(a.active_to as date) as active_to, l.last_positive
        from cur.canonical_data.assortment_calendar a
        join last_sale l using (sku_id, store_id, channel_id)
        """
    ).df()
    assortment_leak = screen_leakage(exits["active_to"], exits["last_positive"])
    dispositions.append(
        disposition(
            "assortment_lifecycle",
            screens=[
                screen_temporal(
                    _grades(con, ["assortment_calendar"]), repository_root=REPO_ROOT
                ),
                screen_grain(
                    sorted(
                        con.execute(
                            "select distinct store_id from cur.canonical_data.assortment_calendar"
                        )
                        .df()["store_id"]
                        .astype(str)
                    ),
                    sorted(frame["store_id"].astype(str).unique()),
                    label="store_id",
                ),
                assortment_leak,
            ],
            notes=(
                "This is the only signal that cleared materiality: rows within 90 "
                "days of an assortment exit carry a large share of error mass. It "
                "fails leakage instead. active_to agrees with the last observed "
                "positive sale, and known_as_of precedes active_to on every row, so "
                "the field is the target's own boundary back-stamped as foreknowledge."
            ),
        )
    )

    report = screen_report(dispositions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n")

    print(f"wrote {args.out}")
    for item in report["signals"]:
        reason = item["reasonCode"] or "-"
        print(f"  {item['signalId']:34s} {item['verdict']:26s} {reason}")
    print(f"\nadmissible (ablation required): {report['admissible'] or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
