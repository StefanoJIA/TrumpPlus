from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.services.source_policy import SourcePolicy


class DailyFeedJsonAdapter:
    adapter_name = "daily_feed_json"

    def __init__(self, path: Path):
        self.path = path
        self.policy = SourcePolicy()
        self._payload: dict[str, Any] | None = None

    def validate_terms_safety(self) -> None:
        payload = self._load()
        if payload.get("direct_truth_social_scrape"):
            raise ValueError("Direct Truth Social scraping input is not allowed")

    def fetch_review_items(self) -> list[dict[str, Any]]:
        self.validate_terms_safety()
        allowed = set(self.policy.config.get("allowed_public_archives", []))
        items = []
        for raw in self._load().get("items", []):
            source_name = raw.get("source_name", "")
            if source_name not in allowed:
                raise ValueError(f"Daily feed source is not allowlisted: {source_name}")
            items.append(self.normalize_item(raw))
        return items

    def normalize_item(self, raw: dict[str, Any]) -> dict[str, Any]:
        warnings = []
        excerpt = (raw.get("short_excerpt") or "").strip()
        max_chars = int(self.policy.config.get("max_manual_excerpt_chars", 500))
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars]
            warnings.append("excerpt_truncated")
        retrieved_at = raw.get("retrieved_at")
        parsed_retrieved_at = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")) if retrieved_at else datetime.now(timezone.utc)
        if "truthsocial.com" in (raw.get("source_url") or "").lower():
            raise ValueError("Daily feed cannot point directly at Truth Social")
        return {
            "adapter_name": self.adapter_name,
            "source_name": raw["source_name"],
            "source_url": raw["source_url"],
            "archive_url": raw.get("archive_url"),
            "retrieved_at": parsed_retrieved_at,
            "raw_excerpt": excerpt,
            "normalized_summary": (raw.get("summary") or raw.get("why_it_matters") or excerpt)[:1000],
            "media_refs": [],
            "terms_status": "manual_review_required",
            "human_status": "pending",
            "metadata_json": {
                "warnings": warnings,
                "feed_date": self._load().get("feed_date"),
                "source_type": raw.get("source_type"),
                "topic_hint": raw.get("topic_hint"),
                "why_it_matters": raw.get("why_it_matters"),
                "source_confidence": raw.get("source_confidence"),
                "input_file": str(self.path),
                "direct_truth_social_scrape": False,
            },
        }

    def _load(self) -> dict[str, Any]:
        if self._payload is None:
            self._payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        return self._payload
