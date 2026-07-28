"""Product-launch, substitution, runout, clearance and fire-sale behavior."""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _safe_id(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def lifecycle_offer_id(offer_type: str, product_code: str) -> str:
    """Return the shared source identifier for one lifecycle offer."""

    return f"{offer_type}-{_safe_id(product_code)}"


def lifecycle_adjustment(
    variant: dict[str, Any],
    day: date,
    default_ramp_days: int,
) -> dict[str, Any]:
    """Return independent causal factors for a SKU/day.

    A flagship launches with a short spike which decays to a stable plateau. A
    predecessor remains active through its runout window, with anticipation,
    substitution, markdown, clearance and fire-sale phases.
    """

    launch_day = date.fromisoformat(variant["_launchDate"])
    age_days = max(0, (day - launch_day).days)
    profile = variant["_launchProfile"]
    controls = variant["_lifecycle"]
    if profile == "flagship-spike-decay":
        spike_days = controls["launchSpikeDays"]
        settle_days = controls["launchSettleDays"]
        spike = _decimal(controls["launchSpikeMultiplier"])
        if age_days <= spike_days:
            launch_factor = spike - (
                (spike - Decimal("1.8"))
                * Decimal(age_days)
                / Decimal(max(1, spike_days))
            )
        elif age_days <= spike_days + settle_days:
            progress = Decimal(age_days - spike_days) / Decimal(max(1, settle_days))
            launch_factor = Decimal("1") + Decimal("0.8") * (Decimal("1") - progress)
        else:
            launch_factor = Decimal("1")
    elif profile == "evergreen":
        launch_factor = Decimal("1")
    else:
        launch_factor = Decimal(
            str(min(1.0, max(0.15, age_days / max(1, default_ramp_days))))
        )

    predecessor_factor = Decimal("1")
    substitution_factor = Decimal("1")
    discount = Decimal("0")
    offer_id = ""
    offer_type = ""
    offer_demand_factor = Decimal("1")

    successor_launch_text = variant.get("_successorLaunchDate", "")
    if successor_launch_text:
        successor_launch = date.fromisoformat(successor_launch_text)
        anticipation_days = controls["preLaunchAnticipationDays"]
        if successor_launch - timedelta(days=anticipation_days) <= day < successor_launch:
            progress = Decimal(
                (day - (successor_launch - timedelta(days=anticipation_days))).days
            ) / Decimal(max(1, anticipation_days))
            floor = _decimal(controls["preLaunchDemandMultiplier"])
            predecessor_factor = Decimal("1") - (Decimal("1") - floor) * progress
        elif day >= successor_launch:
            discontinue_day = (
                date.fromisoformat(variant["_discontinueDate"])
                if variant["_discontinueDate"]
                else successor_launch
                + timedelta(days=30 * controls["runoutMonths"])
            )
            total_runout_days = max(1, (discontinue_day - successor_launch).days)
            elapsed = max(0, (day - successor_launch).days)
            progress = min(
                Decimal("1"),
                Decimal(elapsed) / Decimal(total_runout_days),
            )
            initial_tail = _decimal(controls["runoutDemandMultiplier"])
            predecessor_factor = max(
                Decimal("0.04"),
                initial_tail * (Decimal("1") - Decimal("0.85") * progress),
            )
            fire_start = discontinue_day - timedelta(days=controls["fireSaleFinalDays"])
            clearance_start = successor_launch + timedelta(
                days=controls["clearanceStartDaysAfterSuccessor"]
            )
            product_code = variant["_productCode"]
            if day >= fire_start:
                offer_type = "fire-sale"
                offer_id = lifecycle_offer_id(offer_type, product_code)
                discount = _decimal(controls["fireSaleDiscountPct"])
                offer_demand_factor = _decimal(controls["fireSaleDemandMultiplier"])
            elif day >= clearance_start:
                offer_type = "clearance"
                offer_id = lifecycle_offer_id(offer_type, product_code)
                discount = _decimal(controls["clearanceDiscountPct"])
                offer_demand_factor = _decimal(controls["clearanceDemandMultiplier"])
            else:
                offer_type = "runout-markdown"
                offer_id = lifecycle_offer_id(offer_type, product_code)
                discount = _decimal(controls["runoutMarkdownPct"])
                offer_demand_factor = _decimal(controls["runoutMarkdownDemandMultiplier"])

    if variant.get("_predecessorProductCode") and profile == "flagship-spike-decay":
        spike_days = controls["launchSpikeDays"]
        settle_days = controls["launchSettleDays"]
        transfer_days = max(1, spike_days + settle_days)
        remaining_transfer = max(0.0, 1 - age_days / transfer_days)
        substitution_factor += (
            _decimal(controls["substitutionRate"])
            * Decimal(str(remaining_transfer))
        )

    return {
        "launchProfile": profile,
        "launchFactor": launch_factor,
        "predecessorFactor": predecessor_factor,
        "substitutionFactor": substitution_factor,
        "offerId": offer_id,
        "offerType": offer_type,
        "offerDiscountPct": discount,
        "offerDemandFactor": offer_demand_factor,
    }


def lifecycle_promotions(
    config: dict[str, Any],
    variants_by_market: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Materialize automatic lifecycle offers as source promotions."""

    scenario_start = date.fromisoformat(config["time"]["startDate"])
    scenario_end = date.fromisoformat(config["time"]["endDate"])
    rows: list[dict[str, Any]] = []
    seen_products: set[tuple[str, str]] = set()
    for market_id, variants in variants_by_market.items():
        for variant in variants:
            successor_launch_text = variant.get("_successorLaunchDate", "")
            if not successor_launch_text:
                continue
            product_key = (market_id, variant["_productCode"])
            if product_key in seen_products:
                continue
            seen_products.add(product_key)
            controls = variant["_lifecycle"]
            successor_launch = date.fromisoformat(successor_launch_text)
            discontinue_day = (
                date.fromisoformat(variant["_discontinueDate"])
                if variant["_discontinueDate"]
                else successor_launch + timedelta(days=30 * controls["runoutMonths"])
            )
            clearance_start = successor_launch + timedelta(
                days=controls["clearanceStartDaysAfterSuccessor"]
            )
            fire_start = discontinue_day - timedelta(days=controls["fireSaleFinalDays"])
            product_code = variant["_productCode"]
            product_skus = sorted(
                row["sku"]
                for row in variants
                if row["_productCode"] == product_code
            )
            phases = (
                (
                    "runout-markdown",
                    successor_launch,
                    min(clearance_start - timedelta(days=1), discontinue_day),
                    controls["runoutMarkdownPct"],
                    controls["runoutMarkdownDemandMultiplier"],
                ),
                (
                    "clearance",
                    clearance_start,
                    min(fire_start - timedelta(days=1), discontinue_day),
                    controls["clearanceDiscountPct"],
                    controls["clearanceDemandMultiplier"],
                ),
                (
                    "fire-sale",
                    fire_start,
                    discontinue_day,
                    controls["fireSaleDiscountPct"],
                    controls["fireSaleDemandMultiplier"],
                ),
            )
            for offer_type, phase_start, phase_end, discount, demand in phases:
                effective_start = max(scenario_start, phase_start)
                effective_end = min(scenario_end, phase_end)
                if effective_end < effective_start:
                    continue
                rows.append(
                    {
                        "promotionId": lifecycle_offer_id(
                            offer_type,
                            product_code,
                        ),
                        "name": (
                            f"{variant['_productTitle']} "
                            f"{offer_type.replace('-', ' ').title()}"
                        ),
                        "promotionType": offer_type,
                        "marketId": market_id,
                        "startDate": effective_start.isoformat(),
                        "endDate": effective_end.isoformat(),
                        "storeIds": [],
                        "channelIds": [],
                        "departmentIds": [variant["_departmentId"]],
                        "categoryIds": [variant["_categoryId"]],
                        "customerSegmentIds": [],
                        "discountPct": discount,
                        "demandMultiplier": demand,
                        "_skus": product_skus,
                    }
                )
    return sorted(rows, key=lambda row: (row["marketId"], row["startDate"], row["promotionId"]))
