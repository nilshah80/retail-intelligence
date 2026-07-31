"""Decision #92: cold-start intervals are published only where they are calibrated.

Three candidates failed to make the whole horizon range calibrated for the cold-start
cohort (C6, C7, C8 under decisions #87 and #91), and the failure is monotonic in horizon:
0.8603 over h1-h4, 0.8433 h5-h8, 0.8024 h9-h13, 0.7798 h14-h26. A series with almost no
history cannot be bounded 26 weeks out; that is a property of the data.

Rather than publish an interval measured as wrong, the platform withholds it beyond the
calibrated range and says so. P50 is unaffected at every horizon, so this withdraws a
distribution claim, not a forecast.
"""

from __future__ import annotations

from typing import Final

POLICY_ID: Final[str] = "retail-forecast-interval-availability/v1"

#: Calibrated range for the cold-start cohort, measured on the 13-origin schedule.
COLD_START_CALIBRATED_MAX_HORIZON: Final[int] = 4

#: Published when an interval is requested beyond the calibrated range.
UNCALIBRATED_REASON_CODE: Final[str] = "COLD_START_INTERVAL_UNCALIBRATED"

#: Measured coverage by band, retained so the limit carries its own evidence and a future
#: reader does not have to trust that 4 was chosen for a reason.
MEASURED_COVERAGE_BY_BAND: Final[dict[str, float]] = {
    "h1-h4": 0.8603,
    "h5-h8": 0.8433,
    "h9-h13": 0.8024,
    "h14-h26": 0.7798,
}
P90_COVERAGE_MIN: Final[float] = 0.85


class IntervalHorizonUnavailableError(RuntimeError):
    """A consumer asked for a cold-start interval beyond the calibrated range."""


def cold_start_interval_available(horizon: int) -> bool:
    return int(horizon) <= COLD_START_CALIBRATED_MAX_HORIZON


def require_cold_start_interval_horizon(horizon: int, *, consumer: str) -> None:
    """Fail closed when a consumer needs an interval further out than we calibrated.

    The h1-h4 boundary is load-bearing. Reorder currently reads about h1, because every
    `suppliers_leadtimes` row carries `lead_time_days = 5` -- 0.7 weeks -- but a new
    overseas supplier or a longer review cycle would push the required horizon out, and
    silently reading past the calibrated range is exactly how an under-covered interval
    becomes an under-stocked order.

    So the limit is asserted rather than assumed. A consumer declares the horizon it
    needs and is refused here, at startup, instead of discovering the problem at the point
    of use where the number looks like any other.
    """

    if not cold_start_interval_available(horizon):
        raise IntervalHorizonUnavailableError(
            f"{UNCALIBRATED_REASON_CODE}: {consumer} requires a cold-start interval at "
            f"horizon {horizon}, beyond the calibrated maximum of "
            f"{COLD_START_CALIBRATED_MAX_HORIZON}. Measured coverage by band: "
            f"{MEASURED_COVERAGE_BY_BAND}. Decision #92 withholds the interval rather "
            "than serving an uncalibrated one; extending the range needs a new mechanism "
            "with its own preregistered protocol, not a raised limit."
        )


def horizon_for_lead_time(lead_time_days: int, *, review_period_days: int = 7) -> int:
    """Whole weeks of demand a reorder decision must cover.

    Lead time plus review period, rounded up, because a reorder placed today must cover
    demand until the next order can arrive.
    """

    total_days = max(int(lead_time_days), 0) + max(int(review_period_days), 0)
    return max(1, -(-total_days // 7))


__all__ = [
    "COLD_START_CALIBRATED_MAX_HORIZON",
    "IntervalHorizonUnavailableError",
    "MEASURED_COVERAGE_BY_BAND",
    "POLICY_ID",
    "P90_COVERAGE_MIN",
    "UNCALIBRATED_REASON_CODE",
    "cold_start_interval_available",
    "horizon_for_lead_time",
    "require_cold_start_interval_horizon",
]
