"""Canonical demand-series identity."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True, slots=True)
class SeriesKey:
    sku_id: str
    store_id: str
    channel_id: str

    def __post_init__(self) -> None:
        for field, value in (
            ("sku_id", self.sku_id),
            ("store_id", self.store_id),
            ("channel_id", self.channel_id),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{field} must be a non-empty string")

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.sku_id, self.store_id, self.channel_id)


SERIES_KEY_FIELDS = ("sku_id", "store_id", "channel_id")

__all__ = ["SERIES_KEY_FIELDS", "SeriesKey"]
