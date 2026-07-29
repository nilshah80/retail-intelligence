"""Reporting-currency FX conversion (decision #44, spec §2.4).

Direction is fixed: `base_ccy` is the fact's local currency, `quote_ccy` is the
tenant reporting currency, and `rate` is quote major units per one base major unit,
stored as an exact `DECIMAL(38,18)`.

Conversion is per fact, then aggregated — never aggregate-then-convert, which would
produce a different total. Reporting amounts are derived; they never replace the
local-currency fact or participate in its source reconciliation.

Go must produce identical results on the shared vectors, so nothing here may depend
on binary floating point.
"""

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Final

from .money import MAX_MONEY_MINOR, MIN_MONEY_MINOR, minor_exponent

#: `DECIMAL(38,18)` — 38 significant digits, 18 fractional.
FX_RATE_SCALE: Final[int] = 18
FX_RATE_PRECISION: Final[int] = 38


class FxRateError(ValueError):
    """The rate is missing, inexact, or not representable under the contract."""


class FxConversionUnavailable(FxRateError):
    """No eligible rate at the cutoff.

    Absence fails the reporting conversion. It never falls back to a future rate or
    to an identity rate for differing currencies.
    """


def parse_rate(rate: str | Decimal) -> Decimal:
    """Validate and normalize an FX rate to the contract's exact representation."""
    if isinstance(rate, float):
        raise FxRateError(
            f"FX rate was passed a binary float ({rate!r}); rates are exact decimals"
        )
    try:
        value = rate if isinstance(rate, Decimal) else Decimal(rate)
    except (InvalidOperation, TypeError) as exc:
        raise FxRateError(f"FX rate is not an exact decimal: {rate!r}") from exc

    # Reject NaN/sNaN/Infinity before any comparison or exponent access: NaN makes
    # `<=` raise, and Infinity would otherwise reach the scale check with a
    # non-numeric exponent.
    if not value.is_finite():
        raise FxRateError(f"FX rate must be a finite decimal, got {value}")
    if value <= 0:
        raise FxRateError(f"FX rate must be positive, got {value}")

    exponent = value.as_tuple().exponent
    assert isinstance(exponent, int)  # guaranteed finite by the check above
    scale = max(-exponent, 0)
    integer_digits = max(len(value.as_tuple().digits) + exponent, 0)
    if scale > FX_RATE_SCALE:
        raise FxRateError(
            f"FX rate {value} exceeds the contract scale of {FX_RATE_SCALE} fractional digits"
        )
    if integer_digits > FX_RATE_PRECISION - FX_RATE_SCALE:
        raise FxRateError(
            f"FX rate {value} exceeds DECIMAL({FX_RATE_PRECISION},{FX_RATE_SCALE}) "
            "integer precision"
        )
    return value


def convert_minor(
    amount_minor: int,
    *,
    rate: str | Decimal,
    base_ccy: str,
    quote_ccy: str,
) -> int:
    """Convert one canonical money fact into the reporting currency.

    `round(amount_minor x rate x 10^(q-b))` with `ROUND_HALF_EVEN`, where `b` and
    `q` are the base and quote minor-unit exponents. Identity conversion
    (`base_ccy == quote_ccy`) requires `rate == 1`.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise FxRateError(
            f"minor-unit amounts must be int, got {type(amount_minor).__name__}"
        )
    if not MIN_MONEY_MINOR <= amount_minor <= MAX_MONEY_MINOR:
        raise FxRateError("source minor-unit amount exceeds signed-int64")
    parsed = parse_rate(rate)
    if base_ccy == quote_ccy and parsed != Decimal(1):
        raise FxRateError(
            f"identity conversion {base_ccy}->{quote_ccy} requires rate 1, got {parsed}"
        )

    exponent_shift = minor_exponent(quote_ccy) - minor_exponent(base_ccy)
    with localcontext() as ctx:
        # Exact multiply for any Python integer amount; only the final integral
        # conversion rounds. A fixed headroom would silently round very large
        # amounts before ROUND_HALF_EVEN is applied.
        amount_digits = len(str(abs(amount_minor))) if amount_minor else 1
        ctx.prec = amount_digits + FX_RATE_PRECISION + abs(exponent_shift) + 4
        scaled = Decimal(amount_minor) * parsed
        scaled = scaled.scaleb(exponent_shift)
        result = int(scaled.to_integral_value(rounding=ROUND_HALF_EVEN))
    if not MIN_MONEY_MINOR <= result <= MAX_MONEY_MINOR:
        raise FxRateError("converted minor-unit amount exceeds signed-int64")
    return result


def convert_and_sum(
    facts: list[tuple[int, str | Decimal, str]],
    *,
    quote_ccy: str,
) -> int:
    """Convert each `(amount_minor, rate, base_ccy)` fact, then sum.

    Exists to make the ordering explicit and hard to get wrong: rounding happens
    per fact, and only the rounded results are added.
    """
    result = sum(
        convert_minor(amount, rate=rate, base_ccy=base, quote_ccy=quote_ccy)
        for amount, rate, base in facts
    )
    if not MIN_MONEY_MINOR <= result <= MAX_MONEY_MINOR:
        raise FxRateError("converted aggregate exceeds signed-int64")
    return result


__all__ = [
    "FX_RATE_PRECISION",
    "FX_RATE_SCALE",
    "FxConversionUnavailable",
    "FxRateError",
    "convert_and_sum",
    "convert_minor",
    "parse_rate",
]
