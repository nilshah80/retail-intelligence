"""Reporting-FX conversion (decision #44, spec §2.4).

These are the vectors Go must reproduce byte-for-byte, so every case is stated in
exact decimal text.
"""

from decimal import Decimal

import pytest
from retail_contracts.fx import (
    FX_RATE_SCALE,
    FxRateError,
    convert_and_sum,
    convert_minor,
    parse_rate,
)


class TestParseRate:
    def test_accepts_exact_decimal_text(self) -> None:
        assert parse_rate("83.000000000000000000") == Decimal("83")

    def test_rejects_binary_float(self) -> None:
        with pytest.raises(FxRateError, match="binary float"):
            parse_rate(83.0)  # type: ignore[arg-type]

    def test_rejects_non_positive(self) -> None:
        with pytest.raises(FxRateError, match="must be positive"):
            parse_rate("0")

    @pytest.mark.parametrize("value", ["NaN", "sNaN", "Infinity", "-Infinity"])
    def test_rejects_non_finite(self, value: str) -> None:
        # NaN makes `<=` raise and Infinity has a non-numeric exponent, so both must
        # be rejected before any comparison.
        with pytest.raises(FxRateError, match="finite"):
            parse_rate(value)

    def test_rejects_more_precision_than_the_contract_scale(self) -> None:
        too_precise = "1." + "0" * (FX_RATE_SCALE + 1) + "1"
        with pytest.raises(FxRateError, match="exceeds the contract scale"):
            parse_rate(too_precise)

    def test_rejects_more_than_twenty_integer_digits(self) -> None:
        with pytest.raises(FxRateError, match="integer precision"):
            parse_rate("1" * 21)


class TestConvertMinor:
    def test_usd_cents_to_inr_paise(self) -> None:
        # 100.00 USD at 83 INR/USD -> 8300.00 INR
        assert convert_minor(10_000, rate="83", base_ccy="USD", quote_ccy="INR") == 830_000

    def test_identity_conversion_requires_rate_one(self) -> None:
        assert convert_minor(500, rate="1", base_ccy="INR", quote_ccy="INR") == 500
        with pytest.raises(FxRateError, match="requires rate 1"):
            convert_minor(500, rate="1.5", base_ccy="INR", quote_ccy="INR")

    def test_uses_round_half_even_not_half_up(self) -> None:
        # 0.5 minor units must round to the even neighbour: 2, not 3.
        assert convert_minor(5, rate="0.5", base_ccy="USD", quote_ccy="INR") == 2
        # 1.5 -> 2 (even) as well.
        assert convert_minor(3, rate="0.5", base_ccy="USD", quote_ccy="INR") == 2

    def test_rejects_binary_float_amount(self) -> None:
        with pytest.raises(FxRateError, match="must be int"):
            convert_minor(100.0, rate="83", base_ccy="USD", quote_ccy="INR")  # type: ignore[arg-type]

    def test_rejects_bool_amount(self) -> None:
        # bool is an int subclass; accepting it would silently convert True as 1.
        with pytest.raises(FxRateError, match="must be int"):
            convert_minor(True, rate="83", base_ccy="USD", quote_ccy="INR")

    def test_full_scale_rate_multiplies_exactly_before_rounding(self) -> None:
        """A max-scale rate must multiply exactly, with rounding applied only at the end.

        1_000_000 x 83.123456789012345678 = 83_123_456.789012345678 exactly, which
        rounds to 83_123_457. The intermediate must never be truncated to the rate's
        scale or widened by an inexact binary step — this is a vector Go has to
        reproduce digit for digit.
        """
        result = convert_minor(
            1_000_000,
            rate="83.123456789012345678",
            base_ccy="USD",
            quote_ccy="INR",
        )
        assert result == 83_123_457

    def test_exponent_shift_is_applied_for_differing_minor_units(
        self, monkeypatch
    ) -> None:
        """Exercise the formula even though the four initial packs all use 2."""
        from retail_contracts import money

        monkeypatch.setitem(money.MINOR_UNIT_EXPONENT, "JPY", 0)
        # 100 JPY at 0.55 INR/JPY -> 55 INR -> 5,500 paise.
        assert (
            convert_minor(100, rate="0.55", base_ccy="JPY", quote_ccy="INR")
            == 5_500
        )

    def test_amounts_outside_the_canonical_int64_domain_fail(self) -> None:
        with pytest.raises(FxRateError, match="source.*signed-int64"):
            convert_minor(
                10**40 + 5,
                rate="0.5",
                base_ccy="USD",
                quote_ccy="INR",
            )

    def test_converted_result_outside_int64_fails(self) -> None:
        with pytest.raises(FxRateError, match="converted.*signed-int64"):
            convert_minor(
                2**62,
                rate="3",
                base_ccy="USD",
                quote_ccy="INR",
            )


class TestConvertThenAggregate:
    def test_per_fact_rounding_then_sum(self) -> None:
        # Each fact rounds on its own; only the rounded values are added.
        facts = [(5, "0.5", "USD"), (5, "0.5", "USD"), (5, "0.5", "USD")]
        assert convert_and_sum(facts, quote_ccy="INR") == 6  # 2+2+2

    def test_differs_from_aggregate_then_convert(self) -> None:
        """The ordering is not cosmetic — it changes the total.

        Converting each fact gives 6; summing first (15 x 0.5 = 7.5 -> 8) gives 8.
        The contract mandates the former.
        """
        facts = [(5, "0.5", "USD"), (5, "0.5", "USD"), (5, "0.5", "USD")]
        per_fact = convert_and_sum(facts, quote_ccy="INR")
        aggregate_first = convert_minor(15, rate="0.5", base_ccy="USD", quote_ccy="INR")
        assert per_fact == 6
        assert aggregate_first == 8
        assert per_fact != aggregate_first
