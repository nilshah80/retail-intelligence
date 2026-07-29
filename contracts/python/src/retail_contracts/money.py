"""Integer minor-unit money (decision #4).

Every canonical money fact is an integer count of minor units paired with a
`currency_code`. Source amounts arrive as exact decimal *major* units; conversion
must be exact. When it cannot be, the caller quarantines with
`money_precision_loss` rather than rounding — a silently rounded amount breaks the
per-currency source reconciliation that Gate B B16 depends on.

Binary floats are rejected everywhere in this module. A float has already lost the
exactness the contract promises by the time it reaches us.
"""

from decimal import Decimal, InvalidOperation, localcontext
from typing import Final

#: Minor-unit exponent per currency. INR paise, USD/EUR cents, GBP pence.
#: Adding a currency is a contract change, not a runtime default.
MINOR_UNIT_EXPONENT: Final[dict[str, int]] = {
    "INR": 2,
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
}

QUARANTINE_REASON_PRECISION = "money_precision_loss"
MIN_MONEY_MINOR: Final[int] = -(2**63)
MAX_MONEY_MINOR: Final[int] = 2**63 - 1


class MoneyPrecisionError(ValueError):
    """A source amount cannot be represented exactly in integer minor units."""


class UnknownCurrencyError(ValueError):
    """The currency has no declared minor-unit exponent in the contract."""


def minor_exponent(currency_code: str) -> int:
    """Return the minor-unit exponent for `currency_code`.

    Fails closed on an unknown currency: guessing 2 would silently mis-scale a
    zero-decimal or three-decimal currency.
    """
    try:
        return MINOR_UNIT_EXPONENT[currency_code]
    except KeyError:
        known = ", ".join(sorted(MINOR_UNIT_EXPONENT))
        raise UnknownCurrencyError(
            f"no minor-unit exponent declared for {currency_code!r}; known: {known}"
        ) from None


def _exact_decimal(amount: str | int | Decimal, *, field: str) -> Decimal:
    if isinstance(amount, bool) or isinstance(amount, float):
        raise MoneyPrecisionError(
            f"{field} was passed a bool/binary float ({amount!r}); money must arrive as an "
            "exact decimal string, int or Decimal"
        )
    if isinstance(amount, Decimal):
        value = amount
    else:
        try:
            value = Decimal(amount)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise MoneyPrecisionError(
                f"{field} is not an exact decimal: {amount!r}"
            ) from exc
    if not value.is_finite():
        raise MoneyPrecisionError(f"{field} must be finite, got {value}")
    return value


def to_minor_units(amount: str | int | Decimal, currency_code: str) -> int:
    """Convert an exact decimal major-unit amount to integer minor units.

    Raises `MoneyPrecisionError` when the source carries more precision than the
    currency can hold, so the caller can quarantine instead of rounding.
    """
    exponent = minor_exponent(currency_code)
    major = _exact_decimal(amount, field="amount")
    digits = len(major.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(40, digits + exponent + 2)
        scaled = major.scaleb(exponent)
    if scaled != scaled.to_integral_value():
        raise MoneyPrecisionError(
            f"{amount!r} {currency_code} has more precision than {exponent} minor digits; "
            f"quarantine with reason {QUARANTINE_REASON_PRECISION}"
        )
    result = int(scaled)
    if not MIN_MONEY_MINOR <= result <= MAX_MONEY_MINOR:
        raise MoneyPrecisionError(
            f"{amount!r} {currency_code} exceeds the canonical signed-int64 "
            "minor-unit domain"
        )
    return result


def to_major_units(amount_minor: int, currency_code: str) -> Decimal:
    """Render integer minor units back to an exact decimal major amount.

    Display and reconciliation reporting only — never an intermediate for further
    money arithmetic.
    """
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise MoneyPrecisionError(
            f"minor-unit amounts must be int, got {type(amount_minor).__name__}"
        )
    if not MIN_MONEY_MINOR <= amount_minor <= MAX_MONEY_MINOR:
        raise MoneyPrecisionError(
            "minor-unit amount exceeds the canonical signed-int64 domain"
        )
    exponent = minor_exponent(currency_code)
    with localcontext() as context:
        context.prec = max(40, len(str(abs(amount_minor))) + exponent + 2)
        return Decimal(amount_minor).scaleb(-exponent)


def allocate_minor_units(total_minor: int, weights: list[int]) -> list[int]:
    """Split `total_minor` across `weights` using the largest-remainder method.

    Used when one exact source amount spans several canonical rows (spec §11.0).
    The result sums to `total_minor` exactly. Ties break on the earlier index, so
    the caller must pass weights already ordered by a stable business key —
    otherwise the allocation is not reproducible.
    """
    if isinstance(total_minor, bool) or not isinstance(total_minor, int):
        raise ValueError("allocation total must be an integer minor-unit amount")
    if not MIN_MONEY_MINOR <= total_minor <= MAX_MONEY_MINOR:
        raise ValueError("allocation total exceeds the signed-int64 money domain")
    if not weights:
        raise ValueError("cannot allocate across an empty weight list")
    if any(isinstance(w, bool) or not isinstance(w, int) for w in weights):
        raise ValueError("allocation weights must be integers")
    if any(w < 0 for w in weights):
        raise ValueError("allocation weights must be non-negative")
    weight_total = sum(weights)
    if weight_total == 0:
        raise ValueError("cannot allocate across zero total weight")

    sign = -1 if total_minor < 0 else 1
    magnitude = abs(total_minor)
    quotients: list[int] = []
    remainders: list[int] = []
    for weight in weights:
        quotient, remainder = divmod(magnitude * weight, weight_total)
        quotients.append(quotient)
        remainders.append(remainder)
    units_left = magnitude - sum(quotients)
    order = sorted(
        range(len(weights)),
        key=lambda i: (-remainders[i], i),
    )
    for position in range(units_left):
        quotients[order[position]] += 1
    return [sign * value for value in quotients]


__all__ = [
    "MINOR_UNIT_EXPONENT",
    "MAX_MONEY_MINOR",
    "MIN_MONEY_MINOR",
    "QUARANTINE_REASON_PRECISION",
    "MoneyPrecisionError",
    "UnknownCurrencyError",
    "allocate_minor_units",
    "minor_exponent",
    "to_major_units",
    "to_minor_units",
]
