//! Python `decimal.Decimal` compatibility for the causal simulator.
//!
//! Python v13 uses the default decimal context: 28 significant digits and
//! half-even rounding after every arithmetic operation. `rust_decimal` is ideal
//! for fixed-scale money, but its maximum scale of 28 cannot retain 28
//! significant digits for values below 0.1. Demand factors need arbitrary scale.

use std::cmp::Ordering;
use std::fmt;
use std::hash::{Hash, Hasher};
use std::iter::Sum;
use std::ops::{Add, Div, Mul, Neg, Sub};
use std::str::FromStr;

use bigdecimal::{BigDecimal, One, RoundingMode, Signed, ToPrimitive, Zero};
use num_integer::Integer;

const PYTHON_DECIMAL_PRECISION: u64 = 28;

#[derive(Debug, Clone)]
pub struct PyDecimal {
    value: BigDecimal,
    /// Python Decimal's preferred fractional scale (`-exponent`). BigDecimal
    /// canonicalizes trailing zeroes, particularly for a zero coefficient, so
    /// exact source text needs this independent exponent state.
    scale: i64,
}

impl PyDecimal {
    #[must_use]
    pub fn zero() -> Self {
        Self {
            value: BigDecimal::from(0_i32),
            scale: 0,
        }
    }

    #[must_use]
    pub fn one() -> Self {
        Self {
            value: BigDecimal::from(1_i32),
            scale: 0,
        }
    }

    #[must_use]
    pub fn from_f64_text(value: f64) -> Self {
        // Python's `str(float)` retains the `.0` for an integral float while
        // Rust's `f64::to_string` does not. The exponent is observable in
        // subsequent Decimal arithmetic, especially when a no-op multiplier
        // is shaped over a fractional event window.
        let text = if value.fract() == 0.0 {
            format!("{value:.1}")
        } else {
            value.to_string()
        };
        text.parse().expect("finite Python-compatible float")
    }

    #[must_use]
    pub fn abs(&self) -> Self {
        if self < &Self::zero() {
            -self
        } else {
            self.clone()
        }
    }

    #[must_use]
    pub fn max(self, other: Self) -> Self {
        if self >= other { self } else { other }
    }

    #[must_use]
    pub fn min(self, other: Self) -> Self {
        if self <= other { self } else { other }
    }

    #[must_use]
    pub fn clamp(self, minimum: Self, maximum: Self) -> Self {
        self.max(minimum).min(maximum)
    }

    #[must_use]
    pub fn quantize(&self, scale: i64, rounding: RoundingMode) -> Self {
        Self {
            value: self.value.with_scale_round(scale, rounding),
            scale,
        }
    }

    #[must_use]
    pub fn normalized_string(&self) -> String {
        self.value.normalized().to_plain_string()
    }

    #[must_use]
    pub fn fixed_string(&self, scale: usize) -> String {
        format!("{:.*}", scale, self.value)
    }

    #[must_use]
    pub fn to_f64(&self) -> Option<f64> {
        self.value.to_f64()
    }

    #[must_use]
    pub fn trunc_i64(&self) -> Option<i64> {
        self.value.with_scale_round(0, RoundingMode::Down).to_i64()
    }

    #[must_use]
    pub fn ceil_i64(&self) -> Option<i64> {
        self.value
            .with_scale_round(0, RoundingMode::Ceiling)
            .to_i64()
    }

    fn add(left: &Self, right: &Self) -> Self {
        let scale = left.scale.max(right.scale);
        rounded((&left.value + &right.value).with_scale(scale), scale)
    }

    fn subtract(left: &Self, right: &Self) -> Self {
        let scale = left.scale.max(right.scale);
        rounded((&left.value - &right.value).with_scale(scale), scale)
    }

    fn multiply(left: &Self, right: &Self) -> Self {
        let scale = left.scale + right.scale;
        rounded((&left.value * &right.value).with_scale(scale), scale)
    }

    fn divide(left: &Self, right: &Self) -> Self {
        // Python keeps the preferred operand scale for exact quotients and
        // otherwise rounds directly to the active 28-significant-digit
        // half-even context. BigDecimal's `/` computes 100 digits first, most
        // of which this compatibility layer would immediately discard. Do the
        // same integer long division at Python's actual precision instead.
        //
        // Division by any representation of one is especially common in the
        // channel allocator.  BigDecimal can avoid the long division itself,
        // but the generic path below would still normalize, multiply, and
        // compare large integers to rediscover that the quotient is exact.
        // Preserve Python's preferred-exponent rule directly instead.
        if right.value.is_one() && left.value.digits() <= PYTHON_DECIMAL_PRECISION {
            let normalized = left.value.normalized();
            let preferred_scale = left.scale - right.scale;
            let result_scale = normalized.fractional_digit_count().max(preferred_scale);
            return Self {
                value: normalized.with_scale(result_scale),
                scale: result_scale,
            };
        }

        let (numerator, numerator_scale) = left.value.as_bigint_and_exponent();
        let (denominator, denominator_scale) = right.value.as_bigint_and_exponent();
        assert!(!denominator.is_zero(), "division by zero");

        if numerator.is_zero() {
            return exact_quotient(BigDecimal::zero(), left.scale - right.scale);
        }

        let negative = numerator.sign() != denominator.sign();
        let mut numerator = numerator.abs();
        let denominator = denominator.abs();
        let mut quotient_scale = numerator_scale - denominator_scale;

        while numerator < denominator {
            numerator *= 10_u32;
            quotient_scale += 1;
        }

        let (mut quotient, mut remainder) = numerator.div_rem(&denominator);
        let initial_digits = decimal_digits(&quotient);
        let exact;

        if initial_digits > PYTHON_DECIMAL_PRECISION {
            let dropped_digits = initial_digits - PYTHON_DECIMAL_PRECISION;
            let divisor = bigdecimal::num_bigint::BigInt::from(10_u32)
                .pow(u32::try_from(dropped_digits).expect("decimal precision fits u32"));
            let (kept, dropped) = quotient.div_rem(&divisor);
            exact = dropped.is_zero() && remainder.is_zero();

            let discarded_numerator = dropped * &denominator + remainder;
            let discarded_denominator = divisor * &denominator;
            quotient = kept;
            quotient_scale -= i64::try_from(dropped_digits).expect("decimal scale fits i64");
            round_half_even(&mut quotient, &discarded_numerator, &discarded_denominator);
        } else {
            let mut digits = initial_digits;
            while !remainder.is_zero() && digits < PYTHON_DECIMAL_PRECISION {
                remainder *= 10_u32;
                let (digit, next_remainder) = remainder.div_rem(&denominator);
                quotient = quotient * 10_u32 + digit;
                remainder = next_remainder;
                digits += 1;
                quotient_scale += 1;
            }
            exact = remainder.is_zero();
            if !exact {
                round_half_even(&mut quotient, &remainder, &denominator);
            }
        }

        if decimal_digits(&quotient) > PYTHON_DECIMAL_PRECISION {
            quotient /= 10_u32;
            quotient_scale -= 1;
        }
        if negative {
            quotient = -quotient;
        }

        let rounded_value = BigDecimal::new(quotient, quotient_scale);
        if exact {
            exact_quotient(rounded_value, left.scale - right.scale)
        } else {
            let scale = rounded_value.fractional_digit_count();
            Self {
                value: rounded_value,
                scale,
            }
        }
    }
}

fn exact_quotient(value: BigDecimal, preferred_scale: i64) -> PyDecimal {
    let normalized = value.normalized();
    // Decimal preserves the preferred exponent for an exact zero quotient,
    // including a positive exponent such as 0 / 0.18 -> 0E+2. That exponent
    // is observable in later multiplication/addition and therefore in source
    // strings (1 + (1.22 - 1) * 0E+2 -> 1, not 1.00).
    let result_scale = if normalized.is_zero() {
        preferred_scale
    } else {
        normalized.fractional_digit_count().max(preferred_scale)
    };
    PyDecimal {
        value: normalized.with_scale(result_scale),
        scale: result_scale,
    }
}

fn decimal_digits(value: &bigdecimal::num_bigint::BigInt) -> u64 {
    u64::try_from(value.to_str_radix(10).trim_start_matches('-').len())
        .expect("decimal digit count fits u64")
}

fn round_half_even(
    quotient: &mut bigdecimal::num_bigint::BigInt,
    remainder: &bigdecimal::num_bigint::BigInt,
    denominator: &bigdecimal::num_bigint::BigInt,
) {
    match (remainder * 2_u32).cmp(denominator) {
        Ordering::Greater => *quotient += 1_u32,
        Ordering::Equal if quotient.is_odd() => *quotient += 1_u32,
        Ordering::Less | Ordering::Equal => {}
    }
}

fn rounded(value: BigDecimal, preferred_scale: i64) -> PyDecimal {
    if value.digits() > 28 {
        let value = round_operation(value);
        let scale = value.fractional_digit_count();
        PyDecimal { value, scale }
    } else {
        PyDecimal {
            value,
            scale: preferred_scale,
        }
    }
}

fn round_operation(value: BigDecimal) -> BigDecimal {
    if value.digits() > 28 {
        value.with_precision_round(
            std::num::NonZeroU64::new(28).expect("non-zero precision"),
            RoundingMode::HalfEven,
        )
    } else {
        value
    }
}

impl fmt::Display for PyDecimal {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.scale >= 0 {
            write!(formatter, "{:.*}", self.scale as usize, self.value)
        } else if self.value.is_zero() {
            write!(formatter, "0E+{}", -self.scale)
        } else {
            let scientific = self.value.to_scientific_notation().replace('e', "E");
            let scientific = scientific.split_once('E').map_or_else(
                || scientific.clone(),
                |(coefficient, exponent)| {
                    if exponent.starts_with(['+', '-']) {
                        format!("{coefficient}E{exponent}")
                    } else {
                        format!("{coefficient}E+{exponent}")
                    }
                },
            );
            formatter.write_str(&scientific)
        }
    }
}

impl PartialEq for PyDecimal {
    fn eq(&self, other: &Self) -> bool {
        self.value == other.value
    }
}

impl Eq for PyDecimal {}

impl PartialOrd for PyDecimal {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl Ord for PyDecimal {
    fn cmp(&self, other: &Self) -> Ordering {
        self.value.cmp(&other.value)
    }
}

impl Hash for PyDecimal {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.value.normalized().to_string().hash(state);
    }
}

impl FromStr for PyDecimal {
    type Err = bigdecimal::ParseBigDecimalError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        BigDecimal::from_str(value).map(|decimal| Self {
            value: decimal,
            scale: text_scale(value),
        })
    }
}

macro_rules! impl_from_integer {
    ($($integer:ty),+ $(,)?) => {
        $(impl From<$integer> for PyDecimal {
            fn from(value: $integer) -> Self {
                Self {
                    value: BigDecimal::from(value),
                    scale: 0,
                }
            }
        })+
    };
}

impl_from_integer!(i32, i64, u32, u64);

impl From<usize> for PyDecimal {
    fn from(value: usize) -> Self {
        Self {
            value: BigDecimal::from(value as u64),
            scale: 0,
        }
    }
}

macro_rules! impl_binary_operation {
    ($trait:ident, $method:ident, $implementation:ident) => {
        impl $trait for PyDecimal {
            type Output = PyDecimal;
            fn $method(self, rhs: Self) -> Self::Output {
                PyDecimal::$implementation(&self, &rhs)
            }
        }
        impl<'a> $trait<&'a PyDecimal> for PyDecimal {
            type Output = PyDecimal;
            fn $method(self, rhs: &'a PyDecimal) -> Self::Output {
                PyDecimal::$implementation(&self, rhs)
            }
        }
        impl $trait<PyDecimal> for &PyDecimal {
            type Output = PyDecimal;
            fn $method(self, rhs: PyDecimal) -> Self::Output {
                PyDecimal::$implementation(self, &rhs)
            }
        }
        impl<'a> $trait<&'a PyDecimal> for &PyDecimal {
            type Output = PyDecimal;
            fn $method(self, rhs: &'a PyDecimal) -> Self::Output {
                PyDecimal::$implementation(self, rhs)
            }
        }
    };
}

impl_binary_operation!(Add, add, add);
impl_binary_operation!(Sub, sub, subtract);
impl_binary_operation!(Mul, mul, multiply);
impl_binary_operation!(Div, div, divide);

impl Neg for PyDecimal {
    type Output = Self;

    fn neg(self) -> Self::Output {
        Self {
            value: -self.value,
            scale: self.scale,
        }
    }
}

impl Neg for &PyDecimal {
    type Output = PyDecimal;

    fn neg(self) -> Self::Output {
        PyDecimal {
            value: -&self.value,
            scale: self.scale,
        }
    }
}

impl Sum for PyDecimal {
    fn sum<I: Iterator<Item = Self>>(values: I) -> Self {
        values.fold(Self::zero(), |total, value| total + value)
    }
}

impl<'a> Sum<&'a PyDecimal> for PyDecimal {
    fn sum<I: Iterator<Item = &'a PyDecimal>>(values: I) -> Self {
        values.fold(Self::zero(), |total, value| total + value)
    }
}

fn text_scale(value: &str) -> i64 {
    let (mantissa, exponent) =
        value
            .split_once(['e', 'E'])
            .map_or((value, 0_i64), |(mantissa, exponent)| {
                (
                    mantissa,
                    exponent.parse::<i64>().expect("parsed decimal exponent"),
                )
            });
    let fractional = mantissa
        .split_once('.')
        .map_or(0_i64, |(_, fraction)| fraction.len() as i64);
    fractional - exponent
}

#[cfg(test)]
mod tests {
    use super::PyDecimal;

    #[test]
    fn arithmetic_uses_python_default_context() {
        let one = PyDecimal::one();
        let value = &one / &"128.0".parse::<PyDecimal>().unwrap();
        assert_eq!(value.normalized_string(), "0.0078125");
        let third = &one / &PyDecimal::from(3_u32);
        assert_eq!(third.to_string(), "0.3333333333333333333333333333");
        assert_eq!(
            (&"1.00".parse::<PyDecimal>().unwrap() / &PyDecimal::from(2_u32)).to_string(),
            "0.50"
        );
        assert_eq!(
            (&"1.4988".parse::<PyDecimal>().unwrap() * &"1.000".parse::<PyDecimal>().unwrap())
                .to_string(),
            "1.4988000"
        );
        assert_eq!(
            (&PyDecimal::one()
                + &("0.0".parse::<PyDecimal>().unwrap() * "0.86".parse::<PyDecimal>().unwrap()))
                .to_string(),
            "1.000"
        );
    }

    #[test]
    fn division_matches_python_half_even_and_preferred_exponents() {
        for (numerator, denominator, expected) in [
            ("1", "3", "0.3333333333333333333333333333"),
            ("1.00", "2", "0.50"),
            ("1.00", "2.0", "0.5"),
            ("2", "1.00", "2"),
            ("-1", "7", "-0.1428571428571428571428571429"),
            (
                "123456789012345678901234567890",
                "10",
                "1.234567890123456789012345679E+28",
            ),
            (
                "10000000000000000000000000005",
                "10000000000000000000000000000",
                "1.000000000000000000000000000",
            ),
            (
                "10000000000000000000000000015",
                "10000000000000000000000000000",
                "1.000000000000000000000000002",
            ),
            (
                "99999999999999999999999999995",
                "10000000000000000000000000000",
                "10.00000000000000000000000000",
            ),
            ("0.00", "2.0", "0.0"),
            ("0", "0.18", "0E+2"),
            ("5.00", "2", "2.50"),
        ] {
            let actual =
                numerator.parse::<PyDecimal>().unwrap() / denominator.parse::<PyDecimal>().unwrap();
            assert_eq!(actual.to_string(), expected, "{numerator} / {denominator}");
        }

        let realized_lift = PyDecimal::one()
            + ("1.22".parse::<PyDecimal>().unwrap() - PyDecimal::one())
                * (PyDecimal::zero() / "0.18".parse::<PyDecimal>().unwrap());
        assert_eq!(realized_lift.to_string(), "1");

        let store_target =
            (PyDecimal::from(8_i64) / PyDecimal::from(28_i64)) * PyDecimal::from(21_i64);
        assert_eq!(store_target.to_string(), "6.000000000000000000000000000");
        assert_eq!(store_target.trunc_i64(), Some(6));
    }
}
