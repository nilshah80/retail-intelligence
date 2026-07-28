"""Shared deterministic operational timelines.

These helpers keep inventory commitments and Shopify fulfillment projections on
the same clock without making either layer depend on downstream schemas.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .identity import stable_integer


def add_hours(timestamp: str, hours: int) -> str:
    return (datetime.fromisoformat(timestamp) + timedelta(hours=hours)).isoformat()


def fulfillment_timestamps(
    config: dict[str, Any],
    order_key: str,
    warehouse_id: str,
    order_created_at: str,
) -> tuple[str, str]:
    """Return deterministic fulfillment-created and delivered timestamps."""

    master_seed = config["identity"]["masterSeed"]
    processing_hours = config["operations"]["fulfillment"]["processingDelayHours"]
    fulfillment_key = f"{order_key}:{warehouse_id}"
    processing_jitter = stable_integer(
        master_seed,
        "fulfillment-processing-hours",
        fulfillment_key,
        modulo=max(2, processing_hours + 5),
    )
    created_at = add_hours(
        order_created_at,
        max(1, processing_hours - 1 + processing_jitter),
    )
    delivery_hours = 8 + stable_integer(
        master_seed,
        "fulfillment-delivery-hours",
        fulfillment_key,
        modulo=49,
    )
    return created_at, add_hours(created_at, delivery_hours)
