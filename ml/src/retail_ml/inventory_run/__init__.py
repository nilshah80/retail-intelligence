"""Build the Phase 4 inventory/replenishment artifacts from canonical inputs.

`build` is pure: frames in, frames out, no storage. `load` is the only module here
that opens the curated publication, and it scopes and aggregates in SQL rather
than pulling entities into pandas to filter -- 2.5 million stock rows and 15.8
million fulfillment rows do not belong in memory to keep a few thousand.
"""

from retail_ml.inventory_run.build import (
    InventoryBuildError,
    InventoryInputs,
    build_artifacts,
    coverage_summary,
)
from retail_ml.inventory_run.load import (
    InventoryLoadError,
    lane_coverage_pct,
    load_inventory_inputs,
)

__all__ = [
    "InventoryBuildError",
    "InventoryInputs",
    "InventoryLoadError",
    "build_artifacts",
    "coverage_summary",
    "lane_coverage_pct",
    "load_inventory_inputs",
]
