"""Closed adapter registry with explicit source-system dispatch."""

from __future__ import annotations

from typing import TypeVar

from .base import SourceAdapter

_ADAPTERS: dict[str, type[SourceAdapter]] = {}
_AdapterType = TypeVar("_AdapterType", bound=type[SourceAdapter])


def register_adapter(adapter: _AdapterType) -> _AdapterType:
    source_system = adapter.source_system
    if source_system in _ADAPTERS:
        raise RuntimeError(f"adapter already registered: {source_system}")
    _ADAPTERS[source_system] = adapter
    return adapter


def adapter_for(source_system: str) -> SourceAdapter:
    try:
        adapter = _ADAPTERS[source_system]
    except KeyError as exc:
        raise KeyError(f"no adapter registered for {source_system!r}") from exc
    return adapter()


def registered_adapters() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


# Import registration modules only. They cannot import canonical transforms.
from . import business_central as _business_central  # noqa: E402,F401
from . import companion as _companion  # noqa: E402,F401
from . import shopify as _shopify  # noqa: E402,F401


__all__ = ["adapter_for", "register_adapter", "registered_adapters"]
