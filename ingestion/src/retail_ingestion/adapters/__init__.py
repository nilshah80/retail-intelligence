"""Registered source-semantic adapters.

Adapters know their source platform and emit standardized staging. They never
import canonical transformations or datagen implementation code.
"""

from .base import AdapterContext, SourceAdapter
from .registry import adapter_for, registered_adapters

__all__ = [
    "AdapterContext",
    "SourceAdapter",
    "adapter_for",
    "registered_adapters",
]
