"""Independent synthetic retail source generator."""

# The run id is derived from the config AND this version, so a change to what the
# generator EMITS has to move it -- otherwise the output directory already exists,
# `writer.reused` short-circuits, and a regeneration silently returns the old run.
#
# 0.15.0: store_stockout_events is written for the first time (it was computed and
# discarded since v13), and store transfer receipts carry unitCostMinor in minor
# units rather than the major-unit `_baseCost`, which had every store cost a
# hundredfold small.
GENERATOR_VERSION = "0.15.0"
SOURCE_SPEC_VERSION = "retail-source-config/v13"

__all__ = ["GENERATOR_VERSION", "SOURCE_SPEC_VERSION"]
