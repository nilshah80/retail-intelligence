"""Inventory & replenishment engines (P4-5 foundation).

Ported from the M5 PoC where a module survived re-contracting, net-new where none
existed. Nothing here reads Parquet, DuckDB or the network: engines consume
verified inputs handed to them and return deterministic values, because every
tie-break, rounding rule and seed is contractually fixed and covered by golden
vectors (invariant 15).

Import boundary: this package may import from `retail_ml` and
`retail_contracts` only. It must never import serving, publish or IO modules --
an engine that can reach storage is an engine whose determinism cannot be
audited from its inputs.
"""

from retail_ml.engines.primitives import (
    InventoryPosition,
    OrderConstraintError,
    apply_order_constraints,
    fractional_horizon_rss,
    fractional_horizon_sum,
    inventory_position,
    order_up_to_level,
    protection_period_days,
    reorder_point,
    round_up_to_pack,
    safety_stock_units,
    service_level_z,
)
from retail_ml.engines.abc import classify_abc
from retail_ml.engines.cohorts import assign_cohort
from retail_ml.engines.interval_guard import (
    IntervalUnavailable,
    PartialConsumerLedger,
    require_interval_horizon,
)
from retail_ml.engines.resolution import (
    ResolutionError,
    resolve_lane,
    resolve_supply_term,
)
from retail_ml.engines.clock import monday_period_bounds, opening_snapshot_instant

__all__ = [
    "InventoryPosition",
    "IntervalUnavailable",
    "OrderConstraintError",
    "PartialConsumerLedger",
    "ResolutionError",
    "apply_order_constraints",
    "assign_cohort",
    "classify_abc",
    "fractional_horizon_rss",
    "fractional_horizon_sum",
    "inventory_position",
    "monday_period_bounds",
    "opening_snapshot_instant",
    "order_up_to_level",
    "protection_period_days",
    "reorder_point",
    "require_interval_horizon",
    "resolve_lane",
    "resolve_supply_term",
    "round_up_to_pack",
    "safety_stock_units",
    "service_level_z",
]
