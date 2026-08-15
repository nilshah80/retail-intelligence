"""Per-base-unit pricing normalisation (§6.0 P4).

The datagen carries a sellable pack's content in a fine sub-unit (`ml`, `g`) or a
count (`count`/`EA`). Price Simulation shows Current/Proposed price on a sensible
base selling unit (`₹278.30 / L`, not `/ml`), with the commercial pack shown
secondarily (`5 L`). This maps the sub-unit to the governed display unit and the
pack content into that unit, so a per-unit price is `price_minor / base_unit_quantity`
and a proposed per-unit price converts back exactly as `per_unit * base_unit_quantity`.

Returns (None, None, None) for an unrecognised unit so the simulation falls back to
the aggregate price without fabricating a per-unit basis.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

# Governed sub-unit -> (display label, divisor into the display unit).
_UNIT_MAP: dict[str, tuple[str, Decimal]] = {
    "ml": ("L", Decimal(1000)),
    "milliliter": ("L", Decimal(1000)),
    "millilitre": ("L", Decimal(1000)),
    "l": ("L", Decimal(1)),
    "litre": ("L", Decimal(1)),
    "liter": ("L", Decimal(1)),
    "g": ("kg", Decimal(1000)),
    "gram": ("kg", Decimal(1000)),
    "grams": ("kg", Decimal(1000)),
    "kg": ("kg", Decimal(1)),
    "count": ("unit", Decimal(1)),
    "ea": ("unit", Decimal(1)),
    "each": ("unit", Decimal(1)),
    "unit": ("unit", Decimal(1)),
}


def _trim(value: Decimal) -> str:
    """Render a quantity without trailing zeros (5.0000 -> '5', 0.5000 -> '0.5')."""
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def resolve_pricing_unit(
    measurement_unit: Any, pack_content: Any
) -> tuple[str | None, Decimal | None, str | None]:
    """Map (sub-unit, pack content) -> (pricing_unit_label, base_unit_quantity, pack_label)."""
    if measurement_unit is None or pack_content is None:
        return (None, None, None)
    unit = str(measurement_unit).strip().lower()
    mapping = _UNIT_MAP.get(unit)
    if mapping is None:
        return (None, None, None)
    label, divisor = mapping
    try:
        content = Decimal(str(pack_content))
    except (ValueError, ArithmeticError):
        return (None, None, None)
    if content <= 0:
        return (None, None, None)
    quantity = (content / divisor).quantize(Decimal("0.0001"))
    if quantity <= 0:
        return (None, None, None)
    return (label, quantity, f"{_trim(quantity)} {label}")


__all__ = ["resolve_pricing_unit"]
