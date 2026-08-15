#!/usr/bin/env python3
"""Calibration measurement for a price_recommendations parquet (or serving export).

Reports the §2.2.1 / §6.0 acceptance metrics so each calibration iteration can be
scored against the frozen targets without activating the artifact:

  - total recommendations vs withheld assessments
  - action distribution (Increase / Decrease / Hold)
  - aggregate Margin Opportunity and Revenue Opportunity (must be > 0)
  - competitor-price coverage on recommendation rows (must be complete)
  - priority-first default first-page (20-row) action mix

Usage: python measure_pricing.py <price_recommendations.parquet>
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

TARGET = {
    "recs_total": (80, 120),
    "increase": (3, 4),
    "decrease": (3, 4),          # "Reduce" in UI vocabulary
    "page_hold": (12, 14),
    "page_increase": (3, 4),
    "page_decrease": (3, 4),
}


def _band(label: str, value, lo, hi) -> str:
    ok = "PASS" if lo <= value <= hi else "FAIL"
    return f"  [{ok}] {label}: {value}  (target {lo}-{hi})"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: measure_pricing.py <price_recommendations.parquet>", file=sys.stderr)
        return 2
    df = pd.read_parquet(Path(argv[1]))
    recs = df[df["record_kind"] == "recommendation"].copy()
    withheld = df[df["record_kind"] == "withheld_assessment"]

    print(f"rows total: {len(df)}   recommendations: {len(recs)}   withheld: {len(withheld)}")
    print("\naction distribution (recommendations):")
    counts = recs["action"].value_counts(dropna=False).to_dict()
    for action in ("Hold", "Increase", "Decrease"):
        print(f"  {action}: {counts.get(action, 0)}")

    inc = int((recs["action"] == "Increase").sum())
    dec = int((recs["action"] == "Decrease").sum())

    margin_opp = int(recs["margin_impact_minor"].fillna(0).sum())
    revenue_opp = int(recs["revenue_impact_minor"].fillna(0).sum())
    print(f"\nMargin Opportunity (minor):  {margin_opp:>16,}   {'PASS' if margin_opp > 0 else 'FAIL'} (>0)")
    print(f"Revenue Opportunity (minor): {revenue_opp:>16,}   {'PASS' if revenue_opp > 0 else 'FAIL'} (>0)")

    # Competitor coverage on recommendation rows.
    if "competitor_price_minor" in recs.columns and len(recs):
        covered = int(recs["competitor_price_minor"].notna().sum())
        pct = 100.0 * covered / len(recs)
        print(f"\ncompetitor price coverage: {covered}/{len(recs)} ({pct:.1f}%)   "
              f"{'PASS' if covered == len(recs) else 'FAIL'} (100%)")

    # Priority-first default first page (High > Medium > Low), then take 20.
    order = {"High": 0, "Medium": 1, "Low": 2}
    if len(recs):
        recs["_p"] = recs["priority"].map(order).fillna(3)
        page = recs.sort_values(["_p"]).head(20)
        pc = page["action"].value_counts().to_dict()
        print("\ndefault first-page (priority-first, 20 rows):")
        print(f"  Hold: {pc.get('Hold', 0)}  Increase: {pc.get('Increase', 0)}  Decrease: {pc.get('Decrease', 0)}  (total {len(page)})")

    print("\n=== frozen-target gates (§2.2.1) ===")
    print(_band("recs total", len(recs), *TARGET["recs_total"]))
    print(_band("Increase", inc, *TARGET["increase"]))
    print(_band("Decrease/Reduce", dec, *TARGET["decrease"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
