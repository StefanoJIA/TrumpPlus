from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


class ManualUrlAdapter:
    adapter_name = "manual_url"

    BLOCKED_DOMAINS = {"truthsocial.com", "www.truthsocial.com"}
    MAX_EXCERPT_CHARS = 500

    def validate_terms_safety(self) -> None:
        return None

    def create_review_item(
        self,
        source_url: str,
        short_excerpt: str,
        source_name: str,
        archive_url: str | None = None,
        media_refs: list | None = None,
    ) -> dict[str, Any]:
        domain = urlparse(source_url).netloc.lower()
        warnings = []
        terms_status = "manual_review_required"
        if domain in self.BLOCKED_DOMAINS:
            terms_status = "blocked"
            warnings.append("blocked_domain_direct_truth_social")
        if not short_excerpt.strip():
            raise ValueError("short_excerpt is required")
        raw_excerpt = short_excerpt.strip()
        if len(raw_excerpt) > self.MAX_EXCERPT_CHARS:
            raw_excerpt = raw_excerpt[: self.MAX_EXCERPT_CHARS]
            warnings.append("excerpt_truncated")
        return {
            "adapter_name": self.adapter_name,
            "source_name": source_name,
            "source_url": source_url,
            "archive_url": archive_url,
            "retrieved_at": datetime.now(timezone.utc),
            "raw_excerpt": raw_excerpt,
            "normalized_summary": raw_excerpt[:1000],
            "media_refs": media_refs or [],
            "terms_status": terms_status,
            "human_status": "pending",
            "metadata_json": {
                "warnings": warnings,
                "domain": domain,
                "direct_truth_social_scrape": False,
                "manual_input": True,
            },
        }
