from __future__ import annotations

from app.external_search.controlled_search_provider import ControlledSearchProvider
from app.external_search.fake_search_provider import FakeSearchProvider


class ExternalSearchProviderRegistry:
    def __init__(self, production: bool = True):
        self.production = production
        self._providers = {
            "controlled_search": ControlledSearchProvider(),
            "fake_search": FakeSearchProvider(),
        }

    def get_provider(self, name: str):
        if name not in self._providers:
            raise KeyError(f"Unknown external search provider: {name}")
        provider = self._providers[name]
        provider.validate_provider_policy(production=self.production)
        return provider

    def list_providers(self) -> list[str]:
        return sorted(self._providers)
