from __future__ import annotations

from typing import Any

from app.external_search.base import ExternalSearchPolicy, ExternalSearchProvider


class FakeSearchProvider(ExternalSearchProvider):
    provider_name = "fake_search"

    def search(self, query: str, claim: Any | None = None) -> list[dict[str, Any]]:
        return [
            {
                "title": "Fake search result for tests",
                "source_name": "Fake Search Fixture",
                "source_url": "https://example.org/fake-search-result",
                "archive_url": "https://example.org/archive/fake-search-result",
                "excerpt": f"Fixture excerpt related to: {query}",
                "publisher_type": "archive",
                "reliability_tier": "medium",
            }
        ]

    def validate_provider_policy(self, production: bool = True) -> None:
        ExternalSearchPolicy().validate_provider(self.provider_name, production=production)

    def normalize_result(self, raw: dict[str, Any], query: str) -> dict[str, Any]:
        policy = ExternalSearchPolicy()
        domain, warnings = policy.validate_domain(raw["source_url"])
        return {
            "provider_name": self.provider_name,
            "title": raw.get("title") or "Untitled result",
            "source_name": raw.get("source_name") or domain,
            "source_url": raw["source_url"],
            "archive_url": raw.get("archive_url"),
            "excerpt": self.truncate_excerpt(raw.get("excerpt") or ""),
            "publisher_type": raw.get("publisher_type") or "other",
            "reliability_tier": raw.get("reliability_tier") or "unknown",
            "search_query": query,
            "status": "pending",
            "metadata_json": {"warnings": warnings},
        }
