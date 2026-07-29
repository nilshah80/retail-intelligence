"""Curated-data consumers: point-in-time features, models and decision engines.

Reads only capability-complete curated `retail_v2`. No source, retailer, Shopify or
Business Central branching is permitted anywhere in this package (decision #2) — if a
model needs to know where a row came from, the transform boundary has leaked.

Empty in Phase 2 beyond this module: the package exists now so the boundary is real
before Phase 3 starts writing features.
"""

ML_VERSION = "0.1.0"

__all__ = ["ML_VERSION"]
