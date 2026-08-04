"""Demand-at-risk from the governed available interval (P4-6, net-new).

The one net-new engine that consumes P90, so it is built ON the interval guard:
rows flow through a PartialConsumerLedger, a withheld interval skips the row and
emits the governed exception, and the headline number discloses how much demand
it could not assess. Zero risk from a null interval is the exact coercion
decision #92 forbids -- an unassessed row is unassessed, not safe.

Interpretation label required by P4-6: this measures potential unserved demand
value where demand exceeds available supply AT THE UPPER QUANTILE. It is not a
stock-out probability and not a forecast of lost sales.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from retail_ml.engines.interval_guard import PartialConsumerLedger

INTERPRETATION = (
    "potential unserved demand value where upper-quantile demand exceeds "
    "available supply; not a stock-out probability"
)


def demand_at_risk(
    rows: Sequence[Mapping[str, Any]],
    *,
    consumer: str = "demand_at_risk",
) -> dict[str, Any]:
    """Risk units/value per row and the disclosed unassessed remainder.

    Each row carries the SeriesKey, `horizon_week`, `interval_available`,
    `yhat_p50`, `yhat_p90`, `atp_units`, `unit_price_minor` and
    `currency_code`. Money stays market-local; a caller wanting a global figure
    converts under approved reporting FX after this returns.
    """

    ledger = PartialConsumerLedger(consumer=consumer)
    currencies: set[str] = set()
    assessed: list[dict[str, Any]] = []
    risk_units_total = 0.0
    risk_value_minor_total = 0

    for row in rows:
        if not ledger.observe(row):
            continue
        p90 = row.get("yhat_p90")
        if p90 is None:
            # The guard said available; a missing P90 here is corruption, not a
            # withholding, and computing around it would hide that.
            raise ValueError(
                "row is marked interval_available yet carries no yhat_p90"
            )
        atp = int(row["atp_units"])
        risk_units = max(0.0, float(p90) - atp)
        unit_price = row.get("unit_price_minor")
        risk_value = (
            int(risk_units * int(unit_price)) if unit_price is not None else None
        )
        if risk_value is not None:
            currencies.add(str(row["currency_code"]))
            risk_value_minor_total += risk_value
        risk_units_total += risk_units
        assessed.append(
            {
                "sku_id": str(row["sku_id"]),
                "store_id": str(row["store_id"]),
                "channel_id": str(row["channel_id"]),
                "horizon_week": int(row["horizon_week"]),
                "risk_units": risk_units,
                "risk_value_minor": risk_value,
            }
        )
    if len(currencies) > 1:
        raise ValueError(
            f"demand-at-risk crosses currencies {sorted(currencies)}"
        )
    summary = ledger.market_summary()
    return {
        "interpretation": INTERPRETATION,
        "rows": assessed,
        "riskUnits": risk_units_total,
        "riskValueMinor": risk_value_minor_total,
        "currencyCode": next(iter(currencies), None),
        # The honest remainder: what this number could NOT assess, disclosed
        # beside it rather than folded into it as zero.
        "unassessed": {
            "rows": summary["skippedRows"],
            "series": summary["skippedSeries"],
            "demandUnits": summary["skippedDemandUnits"],
            "reasonCode": "COLD_START_INTERVAL_UNCALIBRATED",
        },
        "exceptions": ledger.exceptions(),
        "marketSubCapabilityUnavailable": summary["marketSubCapabilityUnavailable"],
    }


__all__ = ["INTERPRETATION", "demand_at_risk"]
