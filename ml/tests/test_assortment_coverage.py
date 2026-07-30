from datetime import date

from retail_ml.features.assortment import (
    PARTIAL_BOUNDARY_POLICY,
    week_exposure,
)


def test_partial_boundary_week_is_retained_but_not_trainable() -> None:
    exposure = week_exposure(
        date(2026, 7, 27),
        active_from=date(2026, 7, 30),
        active_to=date(2026, 8, 31),
    )

    assert exposure.active_days == 4
    assert exposure.weight == 4 / 7
    assert not exposure.training_eligible
    assert PARTIAL_BOUNDARY_POLICY == "retain_for_reconciliation_exclude_from_training"


def test_week_outside_assortment_has_no_exposure() -> None:
    exposure = week_exposure(
        date(2026, 7, 20),
        active_from=date(2026, 7, 30),
        active_to=date(2026, 8, 31),
    )
    assert exposure.active_days == 0
    assert exposure.weight == 0
