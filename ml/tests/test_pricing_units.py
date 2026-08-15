"""Per-base-unit normalisation for Price Simulation (§6.0 P4)."""

from __future__ import annotations

from decimal import Decimal

from retail_ml.pricing.units import resolve_pricing_unit


def test_litre_pack_normalises_from_millilitres() -> None:
    # A 5 L oil is carried as measurement_unit "ml" with content 5000.
    assert resolve_pricing_unit("ml", 5000) == ("L", Decimal("5.0000"), "5 L")
    assert resolve_pricing_unit("ml", 210000) == ("L", Decimal("210.0000"), "210 L")
    assert resolve_pricing_unit("ml", 3500) == ("L", Decimal("3.5000"), "3.5 L")


def test_grease_normalises_grams_to_kilograms() -> None:
    assert resolve_pricing_unit("g", 500) == ("kg", Decimal("0.5000"), "0.5 kg")


def test_count_stays_a_unit() -> None:
    assert resolve_pricing_unit("count", 1) == ("unit", Decimal("1.0000"), "1 unit")
    assert resolve_pricing_unit("EA", 6) == ("unit", Decimal("6.0000"), "6 unit")


def test_per_unit_price_and_roundtrip_are_exact() -> None:
    # 5 L pack at ₹58,443 pack price -> per-L, and back to the pack minor amount.
    label, qty, _ = resolve_pricing_unit("ml", 5000)
    pack_minor = Decimal(5844300)  # paise
    per_unit = pack_minor / qty
    assert per_unit == Decimal("1168860")  # ₹11,688.60 / L
    assert (per_unit * qty) == pack_minor  # exact conversion back


def test_unknown_or_missing_unit_yields_no_basis() -> None:
    assert resolve_pricing_unit("furlong", 100) == (None, None, None)
    assert resolve_pricing_unit(None, 5000) == (None, None, None)
    assert resolve_pricing_unit("ml", None) == (None, None, None)
    assert resolve_pricing_unit("ml", 0) == (None, None, None)
