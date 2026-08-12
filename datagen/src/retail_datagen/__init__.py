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
#
# 0.17.0: internal partition dates are resolved before private fields are removed,
# status history recognises occurredAt, distributor city/region overrides flow to
# source locations, and the configurable QC hold can preserve a truthful blocked
# position at the inventory origin. These all change immutable source bytes.
#
# 0.18.0: response-rich price-list events use a wider, still bounded and
# mean-reverting historical step profile so the governed estimator has enough
# independent price movement to evaluate every configured department.
#
# 0.18.1: governed category and channel display names travel with the source
# dimensions so downstream screens never need to present native identifiers.
GENERATOR_VERSION = "0.18.1"
SOURCE_SPEC_VERSION = "retail-source-config/v13"

__all__ = ["GENERATOR_VERSION", "SOURCE_SPEC_VERSION"]
