from __future__ import annotations

from typing import Any

from app.evidence.base import EvidenceProvider
from app.evidence.local_json_provider import LocalJsonEvidenceProvider
from app.evidence.manual_provider import ManualEvidenceProvider
from app.evidence.mock_provider import MockEvidenceProvider


class EvidenceProviderRegistry:
    def __init__(self, environment: str = "production") -> None:
        self.environment = environment
        self._providers: dict[str, EvidenceProvider] = {}

    def register_provider(self, name: str, provider: EvidenceProvider) -> None:
        if not all(hasattr(provider, method) for method in ["search_evidence", "validate_provider_policy", "normalize_evidence"]):
            raise ValueError("Evidence provider does not implement required interface")
        self._providers[name] = provider

    def get_provider(self, name: str) -> EvidenceProvider:
        if name not in self._providers:
            raise KeyError(f"Unknown evidence provider: {name}")
        provider = self._providers[name]
        provider.validate_provider_policy(environment=self.environment)
        return provider

    def list_providers(self) -> list[str]:
        return sorted(self._providers)


def default_registry(environment: str = "production") -> EvidenceProviderRegistry:
    registry = EvidenceProviderRegistry(environment=environment)
    registry.register_provider("manual", ManualEvidenceProvider())
    registry.register_provider("local_json", LocalJsonEvidenceProvider())
    registry.register_provider("mock", MockEvidenceProvider())
    return registry
