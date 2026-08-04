"""Independent synthetic retail source generator."""

# The run id is derived from the config AND this version, so a change to what the
# generator EMITS has to move it -- otherwise the output directory already exists,
# `writer.reused` short-circuits, and a regeneration silently returns the old run.
#
# 0.15.0: store_stockout_events is written for the first time (it was computed and
# discarded since v13), and store transfer receipts carry unitCostMinor in minor
# units rather than the major-unit `_baseCost`, which had every store cost a
# hundredfold small.
#
# 0.16.0: replenishment lane transit varies PER LANE instead of taking one of two
# run-wide policy constants. Every rank-1 lane shared a transit time, so every
# recommendation downstream resolved the same lead time -- 2 days on all 720
# orders -- and the planner's Lead Time and Expected Receipt columns were one
# value repeated down the page. The spread is deterministic in the lane's own
# identity and additive on the policy floor, so the declared minimum still holds.
GENERATOR_VERSION = "0.16.0"
SOURCE_SPEC_VERSION = "retail-source-config/v13"

__all__ = ["GENERATOR_VERSION", "SOURCE_SPEC_VERSION"]
