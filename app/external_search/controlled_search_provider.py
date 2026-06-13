from __future__ import annotations

from typing import Any

from app.external_search.base import ExternalSearchPolicy, ExternalSearchProvider


class ControlledSearchProvider(ExternalSearchProvider):
    provider_name = "controlled_search"

    def __init__(self, client=None):
        self.client = client

    def search(self, query: str, claim: Any | None = None) -> list[dict[str, Any]]:
        if self.client is None:
            return [
                {
                    "title": "Controlled search placeholder result",
                    "source_name": "Controlled Search Placeholder",
                    "source_url": "https://example.org/controlled-search-result",
                    "archive_url": "https://example.org/archive/controlled-search-result",
                    "excerpt": f"Controlled placeholder excerpt for editor review: {query}",
                    "publisher_type": "archive",
                    "reliability_tier": "medium",
                }
            ]
        return list(self.client.search(query=query, claim=claim))

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
