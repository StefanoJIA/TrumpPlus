from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.services.source_policy import SourcePolicy


class PublicArchiveJsonAdapter:
    adapter_name = "public_archive_json"

    def __init__(self, path: Path):
        self.path = path
        self.policy = SourcePolicy()
        self._payload: dict[str, Any] | None = None

    def validate_terms_safety(self) -> None:
        payload = self._load()
        if payload.get("direct_truth_social_scrape"):
            raise ValueError("Direct Truth Social scraping input is not allowed")

    def fetch_review_items(self) -> list[dict[str, Any]]:
        payload = self._load()
        source_name = payload.get("source", {}).get("name", "")
        allowed = set(self.policy.config.get("allowed_public_archives", []))
        if source_name not in allowed:
            raise ValueError(f"Public archive source is not allowlisted: {source_name}")
        items = []
        for raw in payload.get("items", []):
            items.append(self.normalize_item(raw, source_name))
        return items

    def normalize_item(self, raw: dict[str, Any], source_name: str) -> dict[str, Any]:
        warnings = []
        excerpt = (raw.get("short_excerpt") or raw.get("excerpt") or "").strip()
        max_chars = int(self.policy.config.get("max_manual_excerpt_chars", 500))
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars]
            warnings.append("excerpt_truncated")
        if not raw.get("archive_url") and self.policy.config.get("require_archive_url_for_archive_adapters", True):
            warnings.append("archive_url_missing")
            terms_status = "manual_review_required"
        else:
            terms_status = "manual_review_required"
        retrieved_at = raw.get("retrieved_at")
        parsed_retrieved_at = (
            datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")) if retrieved_at else datetime.now(timezone.utc)
        )
        return {
            "adapter_name": self.adapter_name,
            "source_name": source_name,
            "source_url": raw["source_url"],
            "archive_url": raw.get("archive_url"),
            "retrieved_at": parsed_retrieved_at,
            "raw_excerpt": excerpt,
            "normalized_summary": (raw.get("summary") or excerpt)[:1000],
            "media_refs": raw.get("media_refs") or [],
            "terms_status": terms_status,
            "human_status": "pending",
            "metadata_json": {
                "warnings": warnings,
                "direct_truth_social_scrape": False,
                "input_file": str(self.path),
            },
        }

    def _load(self) -> dict[str, Any]:
        if self._payload is None:
            self._payload = json.loads(self.path.read_text(encoding="utf-8"))
        return self._payload
