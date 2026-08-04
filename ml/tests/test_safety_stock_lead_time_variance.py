"""The lead-time addend policy v2 declared and the engine did not implement.

`P4-12g`. `safetyStock.formula` is

    z * sqrt(protection_weeks * demand_variance_weekly
             + mean_weekly_demand^2 * lead_time_variance_weeks)

and only the first addend existed. Four policy keys therefore had no consumer --
`leadTime.variabilityMethod`, `leadTime.minimumObservations`,
`leadTime.zeroVarianceBehavior` and its `LEAD_TIME_VARIABILITY_UNAVAILABLE` reason
code -- and a supplier whose lead time swung by nine days got the same buffer as a
metronomic one, while `lead_time_std_days` sat published on 16,198 of 17,829 rows.

The first addend is derived from the accepted interval rather than a variance
estimate, which `safetyStock.intervalSource` declares, so these tests pin the
substitution as well: adding the second addend must not disturb the first.
"""

from __future__ import annotations

import math

import pytest

from retail_ml.engines import safety_stock_units

SPREADS = (10.0, 10.0, 10.0, 10.0)
P50 = (100.0, 100.0, 100.0, 100.0)
LEVEL = "0.95"


def _demand_only():
    return safety_stock_units(
        weekly_spreads=SPREADS, protection_days=14, service_level=LEVEL
    )


def test_lead_time_variance_raises_the_buffer() -> None:
    """The defect, stated as an assertion."""

    with_variance = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=(2.0 / 7.0) ** 2,
    )
    assert with_variance.total_units > _demand_only().total_units


def test_adding_the_lead_time_term_does_not_disturb_the_demand_term() -> None:
    """The interval substitution stays exactly what it was.

    If this drifts, the second addend has been implemented by rewriting the first
    rather than by adding to it, and every previously published buffer changes for
    a reason nobody chose.
    """

    with_variance = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=(2.0 / 7.0) ** 2,
    )
    assert with_variance.demand_units == pytest.approx(
        _demand_only().demand_units
    )


def test_the_drivers_combine_in_quadrature_not_additively() -> None:
    """The formula puts both terms under one root.

    Asserted because an additive split is the intuitive wrong implementation, and
    it would overstate every buffer that has both drivers.
    """

    stock = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=(3.0 / 7.0) ** 2,
    )
    assert stock.total_units == pytest.approx(
        math.hypot(stock.demand_units, stock.lead_time_units)
    )
    assert stock.total_units < stock.demand_units + stock.lead_time_units
    # Each driver is bounded by the total, which is what migration 0020's check
    # constraint enforces in the serving table.
    assert stock.demand_units <= stock.total_units
    assert stock.lead_time_units <= stock.total_units


def test_a_more_erratic_supplier_gets_a_larger_buffer() -> None:
    """The point of the change, at equal demand dispersion."""

    steady = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=(1.0 / 7.0) ** 2,
    )
    erratic = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=(9.5 / 7.0) ** 2,
    )
    assert erratic.total_units > steady.total_units
    assert erratic.demand_units == pytest.approx(steady.demand_units)


def test_absent_variability_is_reason_coded_not_treated_as_zero() -> None:
    """Policy v2 `zeroVarianceBehavior: reason_code_not_zero_buffer`.

    The buffer falls back to the demand driver alone, and the row says why rather
    than implying a supplier with perfectly steady lead times.
    """

    stock = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=None,
        lead_time_reason_code="LEAD_TIME_VARIABILITY_UNAVAILABLE",
    )
    assert stock.lead_time_reason_code == "LEAD_TIME_VARIABILITY_UNAVAILABLE"
    assert stock.lead_time_units == 0.0
    assert stock.total_units == pytest.approx(_demand_only().total_units)


def test_a_real_lead_time_term_clears_the_reason_code() -> None:
    """A reason and a contribution are mutually exclusive claims.

    Migration 0020 enforces the same thing as a check constraint: the reason exists
    precisely because the contribution is zero.
    """

    stock = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=P50,
        lead_time_variance_weeks=(2.0 / 7.0) ** 2,
        lead_time_reason_code="LEAD_TIME_VARIABILITY_UNAVAILABLE",
    )
    assert stock.lead_time_reason_code is None
    assert stock.lead_time_units > 0


def test_a_negative_variance_is_refused() -> None:
    """A variance is a square. A negative one is upstream corruption."""

    with pytest.raises(ValueError, match="variance cannot be negative"):
        safety_stock_units(
            weekly_spreads=SPREADS,
            protection_days=14,
            service_level=LEVEL,
            weekly_p50=P50,
            lead_time_variance_weeks=-0.01,
        )


def test_no_demand_forecast_leaves_the_lead_time_term_at_zero() -> None:
    """mean_weekly_demand multiplies the lead-time sigma.

    With no P50 series there is no mean to multiply, so the term is zero rather
    than an exception -- the demand driver already carries the interval, and a
    buffer is still owed.
    """

    stock = safety_stock_units(
        weekly_spreads=SPREADS,
        protection_days=14,
        service_level=LEVEL,
        weekly_p50=(),
        lead_time_variance_weeks=(2.0 / 7.0) ** 2,
    )
    assert stock.lead_time_units == 0.0
    assert stock.total_units == pytest.approx(_demand_only().total_units)
