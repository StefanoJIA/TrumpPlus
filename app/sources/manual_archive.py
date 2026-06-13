from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from app.sources.base import SourceAdapter


class ManualArchiveAdapter(SourceAdapter):
    """Reads human-provided public archive JSON. It never contacts Truth Social."""

    def __init__(self, path: Path):
        self.path = path
        self._payload: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._payload is None:
            self._payload = json.loads(self.path.read_text(encoding="utf-8"))
        return self._payload

    def source_payload(self) -> dict[str, Any]:
        payload = self._load()
        source = payload.get("source", {})
        return {
            "name": source.get("name", "manual-public-archive"),
            "kind": "manual_archive",
            "base_url": source.get("base_url"),
            "terms_safe": True,
            "metadata_json": {
                "input_file": str(self.path),
                "sample_data": bool(payload.get("sample_data", False)),
                "manual_input": True,
                "direct_truth_social_scrape": False,
                "public_archive_url": source.get("public_archive_url"),
            },
        }

    def fetch_latest_posts(self) -> list[dict[str, Any]]:
        return list(self._load().get("posts", []))

    def normalize_post(self, raw: dict[str, Any]) -> dict[str, Any]:
        text = raw.get("text", "").strip()
        if not text:
            raise ValueError("Manual archive post is missing text for local processing")
        excerpt = raw.get("short_excerpt") or text[:240]
        summary = raw.get("summary") or excerpt
        return {
            "post_id": raw["post_id"],
            "published_at": datetime.fromisoformat(raw["published_at"].replace("Z", "+00:00")),
            "source_url": raw["source_url"],
            "short_excerpt": excerpt[:500],
            "summary": summary[:1000],
            "topic": raw.get("topic", "public-post"),
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    def validate_terms_safety(self) -> None:
        payload = self._load()
        source = payload.get("source", {})
        if source.get("direct_truth_social_scrape"):
            raise ValueError("Direct Truth Social scraping input is not allowed")
        if not payload.get("sample_data") and not source.get("public_archive_url"):
            raise ValueError("Manual input must identify a public archive or be marked as sample data")
