from datetime import datetime, timezone
import math

import pytest

from retail_ml.pricing.postgres import (
    PricingServingError,
    _details,
    _integer_field,
)


def test_nullable_integer_field_preserves_integral_float_from_pandas() -> None:
    assert _integer_field({"amount": 114_799.0}, "amount") == 114_799
    assert _integer_field({"amount": math.nan}, "amount") is None


def test_nullable_integer_field_refuses_fractional_value() -> None:
    with pytest.raises(PricingServingError, match="amount is not an integer"):
        _integer_field({"amount": 114_799.5}, "amount")


def test_details_are_json_safe_recursively() -> None:
    observed = datetime(2026, 7, 31, 18, 30, tzinfo=timezone.utc)

    assert _details(
        {
            "observed": observed,
            "available": True,
            "nested": {"values": [observed, math.nan, False]},
        }
    ) == {
        "observed": "2026-07-31T18:30:00+00:00",
        "available": True,
        "nested": {"values": ["2026-07-31T18:30:00+00:00", None, False]},
    }
