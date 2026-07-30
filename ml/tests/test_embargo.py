from datetime import date, datetime, timezone

from retail_ml.features.availability import (
    HORIZONS,
    LABEL_EMBARGO_WEEKS,
    TARGET_AVAILABILITY_COLUMNS,
    TARGET_COLUMNS,
    label_is_available,
    latest_training_origin,
    training_origin_is_eligible,
)


def test_horizon_schema_is_26_while_embargo_stays_eight_weeks() -> None:
    assert HORIZONS == tuple(range(1, 27))
    assert len(TARGET_COLUMNS) == 26
    assert len(TARGET_AVAILABILITY_COLUMNS) == 26
    assert LABEL_EMBARGO_WEEKS == 8
    assert latest_training_origin(date(2026, 7, 27)) == date(2026, 6, 1)


def test_embargo_and_per_horizon_availability_are_independent() -> None:
    scored = date(2026, 7, 27)
    assert training_origin_is_eligible(date(2026, 6, 1), scored)
    assert not training_origin_is_eligible(date(2026, 6, 8), scored)
    fit_cutoff = datetime(2026, 7, 27, tzinfo=timezone.utc)
    assert label_is_available(datetime(2026, 7, 27, tzinfo=timezone.utc), fit_cutoff)
    assert not label_is_available(
        datetime(2026, 7, 28, tzinfo=timezone.utc),
        fit_cutoff,
    )
