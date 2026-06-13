from __future__ import annotations

from typing import Any

from app.evidence.base import EvidenceProvider


class MockEvidenceProvider(EvidenceProvider):
    provider_name = "mock"

    def search_evidence(self, claim: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    def validate_provider_policy(self, environment: str = "production") -> None:
        if environment == "production":
            raise ValueError("Mock evidence provider is blocked in production")

    def normalize_evidence(self, raw: dict[str, Any]) -> dict[str, Any]:
        return raw
