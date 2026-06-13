from __future__ import annotations

from datetime import date as dt_date, datetime, timezone
from email.utils import parsedate_to_datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import yaml

from app.services.source_policy import SourcePolicy


class RemoteFeedAdapter:
    adapter_name = "remote_feed"

    def __init__(self, config_path: Path = Path("app/config/remote_source_feeds.yaml")):
        self.config_path = config_path
        self.policy = SourcePolicy()
        self._config: dict[str, Any] | None = None

    def validate_terms_safety(self) -> None:
        blocked_domains = set(self.policy.config.get("blocked_domains", []))
        allowed = set(self.policy.config.get("allowed_remote_feeds", []))
        for feed in self._enabled_feeds():
            if feed.get("name") not in allowed:
                raise ValueError(f"Remote feed source is not allowlisted: {feed.get('name')}")
            parsed = urlparse(feed.get("feed_url", ""))
            if parsed.netloc and self._domain_blocked(parsed.netloc, blocked_domains):
                raise ValueError(f"Remote feed domain is blocked: {parsed.netloc}")
            if "truthsocial.com" in (feed.get("feed_url") or "").lower():
                raise ValueError("Remote feed cannot point directly at Truth Social")

    def fetch_review_items(self, target_date: str | dt_date | None = None) -> list[dict[str, Any]]:
        items, _ = self.fetch_review_items_with_filter_report(target_date=target_date)
        return items

    def fetch_review_items_with_filter_report(self, target_date: str | dt_date | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.validate_terms_safety()
        items: list[dict[str, Any]] = []
        max_items = int(self._config_data().get("defaults", {}).get("max_items", 10))
        report = {
            "target_date": self._target_date(target_date).isoformat() if self._target_date(target_date) else None,
            "total_raw_items": 0,
            "kept_item_count": 0,
            "filtered_by_date": 0,
            "filtered_by_topic": 0,
            "filtered_by_exclusion": 0,
            "feeds": [],
        }
        for feed in self._enabled_feeds():
            raw_items = self._fetch_feed_items(feed)
            filtered_items, feed_report = self.filter_feed_items(raw_items, feed, target_date=target_date)
            selected_items = filtered_items[:max_items]
            feed_report["kept_after_max_items"] = len(selected_items)
            report["total_raw_items"] += feed_report["total_raw_items"]
            report["kept_item_count"] += len(selected_items)
            report["filtered_by_date"] += feed_report["filtered_by_date"]
            report["filtered_by_topic"] += feed_report["filtered_by_topic"]
            report["filtered_by_exclusion"] += feed_report["filtered_by_exclusion"]
            report["feeds"].append(feed_report)
            for raw in selected_items:
                items.append(self.normalize_item(raw, feed))
        return items, report

    def preview_feed_items(self, feed: dict[str, Any], limit: int = 3) -> list[dict[str, Any]]:
        return self._fetch_feed_items(feed)[:limit]

    def filter_feed_items(
        self,
        raw_items: list[dict[str, Any]],
        feed: dict[str, Any],
        target_date: str | dt_date | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        defaults = self._config_data().get("defaults", {})
        require_date_match = bool(feed.get("require_item_date_match", defaults.get("require_item_date_match", False)))
        date_window_days = int(feed.get("date_window_days", defaults.get("date_window_days", 0)))
        require_topic_match = bool(feed.get("require_topic_keyword_match", defaults.get("require_topic_keyword_match", False)))
        topic_keywords = [str(item).lower() for item in feed.get("topic_keywords", defaults.get("topic_keywords", []))]
        exclude_keywords = [str(item).lower() for item in feed.get("exclude_keywords", defaults.get("exclude_keywords", []))]
        target = self._target_date(target_date)
        kept: list[dict[str, Any]] = []
        report = {
            "feed_name": feed.get("name"),
            "target_date": target.isoformat() if target else None,
            "require_item_date_match": require_date_match,
            "date_window_days": date_window_days,
            "require_topic_keyword_match": require_topic_match,
            "topic_keywords": topic_keywords,
            "exclude_keywords": exclude_keywords,
            "total_raw_items": len(raw_items),
            "kept_item_count": 0,
            "filtered_by_date": 0,
            "filtered_by_topic": 0,
            "filtered_by_exclusion": 0,
        }
        for item in raw_items:
            text = self._item_search_text(item)
            if exclude_keywords and any(keyword in text for keyword in exclude_keywords):
                report["filtered_by_exclusion"] += 1
                continue
            if require_topic_match and topic_keywords and not any(keyword in text for keyword in topic_keywords):
                report["filtered_by_topic"] += 1
                continue
            if target and require_date_match and not self._item_in_date_window(item, target, date_window_days):
                report["filtered_by_date"] += 1
                continue
            kept.append(item)
        report["kept_item_count"] = len(kept)
        return kept, report

    def normalize_item(self, raw: dict[str, Any], feed: dict[str, Any]) -> dict[str, Any]:
        source_url = raw["source_url"]
        if "truthsocial.com" in source_url.lower():
            raise ValueError("Remote feed item cannot point directly at Truth Social")
        excerpt = (raw.get("short_excerpt") or raw.get("title") or "").strip()
        max_chars = int(self.policy.config.get("max_manual_excerpt_chars", 500))
        warnings = []
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars]
            warnings.append("excerpt_truncated")
        retrieved_at = raw.get("retrieved_at") or datetime.now(timezone.utc)
        archive_url = raw.get("archive_url") or self._archive_url(feed, source_url)
        return {
            "adapter_name": self.adapter_name,
            "source_name": feed["name"],
            "source_url": source_url,
            "archive_url": archive_url,
            "retrieved_at": retrieved_at,
            "raw_excerpt": excerpt,
            "normalized_summary": (raw.get("summary") or feed.get("why_it_matters") or excerpt)[:1000],
            "media_refs": [],
            "terms_status": "manual_review_required",
            "human_status": "pending",
            "metadata_json": {
                "warnings": warnings,
                "feed_url": feed.get("feed_url"),
                "parser": feed.get("parser", "rss"),
                "source_type": feed.get("source_type", "public_archive"),
                "topic_hint": feed.get("topic_hint"),
                "why_it_matters": feed.get("why_it_matters"),
                "source_confidence": feed.get("source_confidence"),
                "direct_truth_social_scrape": False,
                "daily_filter": {
                    "require_item_date_match": feed.get("require_item_date_match", self._config_data().get("defaults", {}).get("require_item_date_match", False)),
                    "require_topic_keyword_match": feed.get("require_topic_keyword_match", self._config_data().get("defaults", {}).get("require_topic_keyword_match", False)),
                },
            },
        }

    def _enabled_feeds(self) -> list[dict[str, Any]]:
        return [feed for feed in self._config_data().get("feeds", []) if feed.get("enabled", True)]

    def _config_data(self) -> dict[str, Any]:
        if self._config is None:
            self._config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return self._config

    def _fetch_feed_items(self, feed: dict[str, Any]) -> list[dict[str, Any]]:
        content = self._read_feed_url(feed["feed_url"])
        parser = feed.get("parser", "rss")
        if parser in {"rss", "atom"}:
            return self._parse_xml_feed(content)
        if parser == "json":
            return self._parse_json_feed(content)
        raise ValueError(f"Unsupported remote feed parser: {parser}")

    def _read_feed_url(self, feed_url: str) -> str:
        parsed = urlparse(feed_url)
        if parsed.scheme in {"http", "https"}:
            defaults = self._config_data().get("defaults", {})
            request = Request(feed_url, headers={"User-Agent": defaults.get("user_agent", "DailyTruthBrief/1.0")})
            with urlopen(request, timeout=int(defaults.get("timeout_seconds", 20))) as response:
                return response.read().decode("utf-8", errors="replace")
        path = Path(feed_url)
        if not path.exists():
            raise FileNotFoundError(f"Remote feed file not found: {feed_url}")
        return path.read_text(encoding="utf-8-sig")

    def _parse_xml_feed(self, content: str) -> list[dict[str, Any]]:
        root = ET.fromstring(content)
        channel_items = root.findall(".//item")
        if channel_items:
            return [self._rss_item(item) for item in channel_items if self._text(item, "link")]
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        atom_items = root.findall(".//atom:entry", ns)
        return [self._atom_item(item, ns) for item in atom_items if self._atom_link(item, ns)]

    def _rss_item(self, item: ET.Element) -> dict[str, Any]:
        pub_date = self._text(item, "pubDate")
        return {
            "title": self._text(item, "title"),
            "source_url": self._text(item, "link"),
            "short_excerpt": self._text(item, "description"),
            "summary": self._text(item, "description"),
            "retrieved_at": self._parse_date(pub_date),
        }

    def _atom_item(self, item: ET.Element, ns: dict[str, str]) -> dict[str, Any]:
        updated = item.findtext("atom:updated", default="", namespaces=ns) or item.findtext("atom:published", default="", namespaces=ns)
        summary = item.findtext("atom:summary", default="", namespaces=ns) or item.findtext("atom:title", default="", namespaces=ns)
        return {
            "title": item.findtext("atom:title", default="", namespaces=ns),
            "source_url": self._atom_link(item, ns),
            "short_excerpt": summary,
            "summary": summary,
            "retrieved_at": self._parse_date(updated),
        }

    def _parse_json_feed(self, content: str) -> list[dict[str, Any]]:
        payload = json.loads(content)
        raw_items = payload.get("items", [])
        items = []
        for item in raw_items:
            source_url = item.get("url") or item.get("external_url") or item.get("source_url")
            if not source_url:
                continue
            items.append(
                {
                    "title": item.get("title", ""),
                    "source_url": source_url,
                    "short_excerpt": item.get("summary") or item.get("content_text") or item.get("short_excerpt", ""),
                    "summary": item.get("summary") or item.get("content_text") or "",
                    "retrieved_at": self._parse_date(item.get("date_published") or item.get("retrieved_at")),
                }
            )
        return items

    def _text(self, item: ET.Element, tag: str) -> str:
        return (item.findtext(tag) or "").strip()

    def _atom_link(self, item: ET.Element, ns: dict[str, str]) -> str:
        link = item.find("atom:link", ns)
        return (link.get("href") if link is not None else "") or ""

    def _parse_date(self, value: str | None) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            normalized = value.strip()
            if len(normalized) >= 10 and normalized[4:5] == "-" and "T" in normalized[:16]:
                parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
            else:
                parsed = parsedate_to_datetime(normalized)
            if parsed is None:
                raise ValueError("date parser returned None")
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)

    def _target_date(self, value: str | dt_date | None) -> dt_date | None:
        if value is None:
            return None
        if isinstance(value, dt_date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        normalized = str(value)
        if normalized == "today":
            return dt_date.today()
        return dt_date.fromisoformat(normalized)

    def _item_in_date_window(self, item: dict[str, Any], target: dt_date, window_days: int) -> bool:
        retrieved_at = item.get("retrieved_at")
        if isinstance(retrieved_at, datetime):
            item_date = retrieved_at.date()
        elif isinstance(retrieved_at, dt_date):
            item_date = retrieved_at
        elif retrieved_at:
            item_date = self._parse_date(str(retrieved_at)).date()
        else:
            return False
        return abs((item_date - target).days) <= window_days

    def _item_search_text(self, item: dict[str, Any]) -> str:
        return " ".join(
            str(item.get(field, ""))
            for field in ("title", "short_excerpt", "summary", "source_url")
        ).lower()

    def _archive_url(self, feed: dict[str, Any], source_url: str) -> str | None:
        prefix = feed.get("archive_url_prefix")
        if not prefix:
            return None
        return prefix + quote_plus(source_url)

    def _domain_blocked(self, domain: str, blocked_domains: set[str]) -> bool:
        normalized = domain.lower()
        return any(normalized == blocked or normalized.endswith("." + blocked) for blocked in blocked_domains)
