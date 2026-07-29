"""Integer minor-unit money (decision #4)."""

from decimal import Decimal

import pytest
from retail_contracts.money import (
    MAX_MONEY_MINOR,
    MIN_MONEY_MINOR,
    MoneyPrecisionError,
    UnknownCurrencyError,
    allocate_minor_units,
    minor_exponent,
    to_major_units,
    to_minor_units,
)


class TestExponents:
    def test_initial_locale_packs_all_use_two_minor_digits(self) -> None:
        assert [minor_exponent(c) for c in ("INR", "USD", "EUR", "GBP")] == [2, 2, 2, 2]

    def test_unknown_currency_fails_closed(self) -> None:
        # Guessing 2 would silently mis-scale a zero- or three-decimal currency.
        with pytest.raises(UnknownCurrencyError):
            minor_exponent("JPY")


class TestToMinorUnits:
    @pytest.mark.parametrize(
        ("amount", "currency", "expected"),
        [
            ("1099.00", "INR", 109900),
            ("0.01", "USD", 1),
            ("0", "GBP", 0),
            ("132658398158.34", "INR", 13265839815834),
        ],
    )
    def test_exact_conversions(self, amount: str, currency: str, expected: int) -> None:
        assert to_minor_units(amount, currency) == expected

    def test_excess_precision_raises_rather_than_rounding(self) -> None:
        # Rounding here would break the per-currency source reconciliation.
        with pytest.raises(MoneyPrecisionError, match="more precision"):
            to_minor_units("1.005", "USD")

    def test_binary_float_is_rejected(self) -> None:
        with pytest.raises(MoneyPrecisionError, match="binary float"):
            to_minor_units(1.10, "USD")  # type: ignore[arg-type]

    def test_bool_and_nonfinite_values_are_rejected(self) -> None:
        for value in (True, "NaN", "Infinity", Decimal("-Infinity")):
            with pytest.raises(MoneyPrecisionError):
                to_minor_units(value, "USD")  # type: ignore[arg-type]

    def test_non_numeric_is_rejected(self) -> None:
        with pytest.raises(MoneyPrecisionError):
            to_minor_units("not-a-number", "INR")

    def test_round_trips_through_major_units(self) -> None:
        assert to_major_units(109900, "INR") == Decimal("1099.00")

    def test_signed_int64_domain_matches_the_canonical_and_go_types(self) -> None:
        assert to_minor_units("92233720368547758.07", "USD") == MAX_MONEY_MINOR
        assert to_minor_units("-92233720368547758.08", "USD") == MIN_MONEY_MINOR
        for value in ("92233720368547758.08", "-92233720368547758.09"):
            with pytest.raises(MoneyPrecisionError, match="signed-int64"):
                to_minor_units(value, "USD")


class TestAllocation:
    def test_allocation_sums_exactly_to_the_source_total(self) -> None:
        parts = allocate_minor_units(1000, [1, 1, 1])
        assert sum(parts) == 1000
        assert parts == [334, 333, 333]

    def test_largest_remainder_favours_the_larger_share(self) -> None:
        parts = allocate_minor_units(100, [70, 30])
        assert parts == [70, 30]
        assert sum(parts) == 100

    def test_indivisible_remainder_is_distributed_not_dropped(self) -> None:
        parts = allocate_minor_units(10, [1, 1, 1, 1, 1, 1, 1])
        assert sum(parts) == 10

    def test_tie_breaks_on_earlier_index_so_results_are_reproducible(self) -> None:
        # Callers must pass weights ordered by a stable business key; given that,
        # repeated allocation is identical.
        first = allocate_minor_units(7, [1, 1, 1])
        second = allocate_minor_units(7, [1, 1, 1])
        assert first == second == [3, 2, 2]

    def test_zero_total_weight_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="zero total weight"):
            allocate_minor_units(100, [0, 0])

    def test_negative_weight_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            allocate_minor_units(100, [5, -1])

    def test_negative_total_is_sign_symmetric(self) -> None:
        positive = allocate_minor_units(10, [1, 1, 1])
        negative = allocate_minor_units(-10, [1, 1, 1])
        assert negative == [-value for value in positive] == [-4, -3, -3]

    def test_bool_non_integer_and_empty_weights_fail(self) -> None:
        for total, weights in (
            (True, [1]),
            (10, []),
            (10, [True]),
            (10, [1.5]),
        ):
            with pytest.raises(ValueError):
                allocate_minor_units(total, weights)  # type: ignore[arg-type]
