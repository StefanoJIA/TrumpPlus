from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class EvidenceProvider(ABC):
    provider_name: str

    @abstractmethod
    def search_evidence(self, claim: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def validate_provider_policy(self, environment: str = "production") -> None:
        raise NotImplementedError

    @abstractmethod
    def normalize_evidence(self, raw: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
