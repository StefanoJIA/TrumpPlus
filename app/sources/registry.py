from __future__ import annotations

from typing import Any


class SourceAdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register_adapter(self, name: str, adapter: Any) -> None:
        if not hasattr(adapter, "validate_terms_safety"):
            raise ValueError("Source adapter must implement validate_terms_safety()")
        self._adapters[name] = adapter

    def get_adapter(self, name: str) -> Any:
        if name not in self._adapters:
            raise KeyError(f"Unknown source adapter: {name}")
        return self._adapters[name]

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters)


registry = SourceAdapterRegistry()


def register_adapter(name: str, adapter: Any) -> None:
    registry.register_adapter(name, adapter)


def get_adapter(name: str) -> Any:
    return registry.get_adapter(name)


def list_adapters() -> list[str]:
    return registry.list_adapters()
