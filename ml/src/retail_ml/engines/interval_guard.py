"""Decision #92 interval-consumer guards (P4-D17).

Two consumer shapes, and they fail differently on purpose:

* An ALL-OR-NOTHING consumer declares the horizon it needs at startup and
  refuses before any row runs when the declaration exceeds the calibrated range.
  Refusing late would let a batch half-complete against an interval that was
  never offered.
* A PARTIAL consumer branches per row on `interval_available` -- never on P90
  nullability, which cannot distinguish a governed withholding from a lost
  value -- skips only the interval-dependent output, retains P50 where its own
  contract authorizes it, and records the skip in a ledger that reconciles
  against the forecast availability artifact.

Nothing here converts an absent interval into a number. Safety stock is quantile
spread x service level; any placeholder is consumed arithmetically, and a zero
returns zero safety stock on exactly the newest, least predictable products.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

CALIBRATED_MAX_HORIZON = 4
REASON_CODE = "COLD_START_INTERVAL_UNCALIBRATED"
EXCEPTION_CLASS = "cold_start_interval_unavailable"


class IntervalUnavailable(RuntimeError):
    """An all-or-nothing consumer requires horizons the interval does not offer."""


def require_interval_horizon(
    *,
    consumer: str,
    required_horizon_weeks: int,
    calibrated_max_horizon: int = CALIBRATED_MAX_HORIZON,
) -> None:
    """Startup refusal for contractually all-or-nothing consumers.

    The required horizon is DERIVED from the selected rows' origin-safe lead
    time plus review period -- it is never a configuration value, because a
    configured horizon is a promise nobody measured.
    """

    if required_horizon_weeks < 1:
        raise ValueError("required_horizon_weeks must be >= 1")
    if required_horizon_weeks > calibrated_max_horizon:
        raise IntervalUnavailable(
            f"{consumer} requires h{required_horizon_weeks} but the cold-start "
            f"interval is calibrated only through h{calibrated_max_horizon} "
            f"({REASON_CODE}); refusing before any row runs"
        )


@dataclass
class PartialConsumerLedger:
    """Per-consumer skip accounting for declared-partial consumers.

    The ledger is what makes a partial consumer honest: every skipped row is
    counted by series and demand, one governed exception is emitted per affected
    SeriesKey (the exceptions table has no horizon column, so per-horizon rows
    would collide), and the market-level floors from P4-D17 are evaluated from
    these counts rather than asserted.
    """

    consumer: str
    skipped_rows: int = 0
    skipped_series: set[tuple[str, str, str]] = field(default_factory=set)
    skipped_demand_units: float = 0.0
    total_rows: int = 0
    total_demand_units: float = 0.0
    _exceptions: dict[tuple[str, str, str], dict[str, Any]] = field(
        default_factory=dict
    )

    def observe(self, row: Mapping[str, Any]) -> bool:
        """Record one row; return True when its interval output may be computed.

        Branches on the EXPLICIT `interval_available` flag. `p90 is None` is not
        the same fact: migration 0009 stores availability precisely so a
        governed withholding and a writer that lost the value stop being
        indistinguishable.
        """

        available = row.get("interval_available")
        if available is None:
            raise ValueError(
                "row carries no interval_available flag; a partial consumer "
                "may not infer availability from P90 nullability"
            )
        p50 = row.get("yhat_p50")
        demand = float(p50) if p50 is not None else 0.0
        self.total_rows += 1
        self.total_demand_units += demand
        if available:
            return True
        self.skipped_rows += 1
        series = (
            str(row["sku_id"]),
            str(row["store_id"]),
            str(row["channel_id"]),
        )
        self.skipped_series.add(series)
        self.skipped_demand_units += demand
        entry = self._exceptions.setdefault(
            series,
            {
                "exception_class": EXCEPTION_CLASS,
                "consumer": self.consumer,
                "reason_code": REASON_CODE,
                "calibrated_max_horizon": CALIBRATED_MAX_HORIZON,
                "unavailable_from_horizon": int(row["horizon_week"]),
                "unavailable_through_horizon": int(row["horizon_week"]),
                "withheld_horizon_count": 0,
            },
        )
        horizon = int(row["horizon_week"])
        entry["unavailable_from_horizon"] = min(
            entry["unavailable_from_horizon"], horizon
        )
        entry["unavailable_through_horizon"] = max(
            entry["unavailable_through_horizon"], horizon
        )
        entry["withheld_horizon_count"] += 1
        return False

    def exceptions(self) -> list[dict[str, Any]]:
        """One record per affected SeriesKey, deterministic order."""

        return [self._exceptions[key] for key in sorted(self._exceptions)]

    def market_summary(self) -> dict[str, Any]:
        """The P4-D17 floors, computed rather than asserted.

        `marketSubCapabilityUnavailable` is true when 100% of the observed rows'
        series or demand was skipped; `wholeConsumerUnavailable` when no
        computable row remained at all. P4-4 may freeze stricter pre-result
        limits; these floors may never be weakened after results exist.
        """

        all_series_skipped = (
            self.total_rows > 0 and self.skipped_rows == self.total_rows
        )
        all_demand_skipped = (
            self.total_demand_units > 0
            and self.skipped_demand_units >= self.total_demand_units
        )
        return {
            "consumer": self.consumer,
            "skippedRows": self.skipped_rows,
            "skippedSeries": len(self.skipped_series),
            "skippedDemandUnits": self.skipped_demand_units,
            "totalRows": self.total_rows,
            "totalDemandUnits": self.total_demand_units,
            "marketSubCapabilityUnavailable": (
                all_series_skipped or all_demand_skipped
            ),
            "wholeConsumerUnavailable": (
                self.total_rows > 0 and self.skipped_rows == self.total_rows
            ),
        }


__all__ = [
    "CALIBRATED_MAX_HORIZON",
    "EXCEPTION_CLASS",
    "IntervalUnavailable",
    "PartialConsumerLedger",
    "REASON_CODE",
    "require_interval_horizon",
]
