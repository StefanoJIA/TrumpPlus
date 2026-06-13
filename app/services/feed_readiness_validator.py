from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from app.services.source_policy import SourcePolicy
from app.sources.remote_feed import RemoteFeedAdapter


class FeedReadinessValidator:
    def __init__(self, policy: SourcePolicy | None = None):
        self.policy = policy or SourcePolicy()

    def validate_remote_feed_config(
        self,
        config_path: str | Path = "app/config/remote_source_feeds.yaml",
        *,
        target_date: str | None = None,
        fetch_preview: bool = True,
        preview_limit: int = 3,
    ) -> dict[str, Any]:
        path = Path(config_path)
        warnings: list[str] = []
        blocking_errors: list[str] = []
        feed_reports: list[dict[str, Any]] = []

        if not path.exists():
            return self._report("blocked", path, [], [], [f"config_not_found:{path}"])

        try:
            config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return self._report("blocked", path, [], [], [f"invalid_yaml:{exc}"])

        feeds = [feed for feed in config.get("feeds", []) if feed.get("enabled", True)]
        if not feeds:
            blocking_errors.append("no_enabled_feeds")

        allowed = set(self.policy.config.get("allowed_remote_feeds", []))
        blocked_domains = set(self.policy.config.get("blocked_domains", []))
        max_excerpt_chars = int(self.policy.config.get("max_manual_excerpt_chars", 500))
        adapter = RemoteFeedAdapter(path)

        for index, feed in enumerate(feeds):
            report = self._validate_feed(index, feed, allowed, blocked_domains)
            if fetch_preview and report["status"] != "blocked":
                try:
                    raw_items = adapter.preview_feed_items(feed, limit=preview_limit)
                    filtered_items, filter_report = adapter.filter_feed_items(raw_items, feed, target_date=target_date)
                    report["preview_item_count"] = len(raw_items)
                    report["preview_kept_item_count"] = len(filtered_items)
                    report["filter_report"] = filter_report
                    if not raw_items:
                        report["warnings"].append("feed_has_no_preview_items")
                    elif not filtered_items:
                        report["warnings"].append("feed_preview_items_filtered_out")
                    for item_index, item in enumerate(raw_items):
                        item_warnings, item_errors = self._validate_preview_item(item, max_excerpt_chars)
                        report["preview_items"].append(
                            {
                                "index": item_index,
                                "source_url": item.get("source_url"),
                                "has_excerpt": bool((item.get("short_excerpt") or item.get("summary") or item.get("title") or "").strip()),
                                "warnings": item_warnings,
                                "blocking_errors": item_errors,
                            }
                        )
                        report["warnings"].extend(item_warnings)
                        report["blocking_errors"].extend(item_errors)
                except (FileNotFoundError, ValueError, OSError) as exc:
                    report["blocking_errors"].append(f"feed_preview_failed:{exc}")
            report["warnings"] = sorted(set(report["warnings"]))
            report["blocking_errors"] = sorted(set(report["blocking_errors"]))
            report["status"] = "blocked" if report["blocking_errors"] else ("warning" if report["warnings"] else "passed")
            warnings.extend([f"{report['name']}:{warning}" for warning in report["warnings"]])
            blocking_errors.extend([f"{report['name']}:{error}" for error in report["blocking_errors"]])
            feed_reports.append(report)

        status = "blocked" if blocking_errors else ("warning" if warnings else "passed")
        return self._report(status, path, feed_reports, sorted(set(warnings)), sorted(set(blocking_errors)))

    def _validate_feed(
        self,
        index: int,
        feed: dict[str, Any],
        allowed: set[str],
        blocked_domains: set[str],
    ) -> dict[str, Any]:
        name = feed.get("name") or f"feed_{index}"
        parser = feed.get("parser", "rss")
        feed_url = feed.get("feed_url", "")
        parsed = urlparse(feed_url)
        warnings: list[str] = []
        blocking_errors: list[str] = []

        if not feed.get("name"):
            blocking_errors.append("feed_name_missing")
        elif feed["name"] not in allowed:
            blocking_errors.append("feed_not_allowlisted")
        if not feed_url:
            blocking_errors.append("feed_url_missing")
        if "truthsocial.com" in feed_url.lower():
            blocking_errors.append("direct_truth_social_feed_forbidden")
        if parsed.netloc and self._domain_blocked(parsed.netloc, blocked_domains):
            blocking_errors.append("feed_domain_blocked")
        if parser not in {"rss", "atom", "json"}:
            blocking_errors.append("unsupported_parser")
        if feed.get("source_type") in {"public_archive", "news_link", "official_doc"} and not feed.get("archive_url_prefix"):
            warnings.append("archive_url_prefix_missing")
        if not parsed.scheme:
            warnings.append("local_file_feed_for_test_only")

        return {
            "index": index,
            "name": name,
            "feed_url": feed_url,
            "parser": parser,
            "source_type": feed.get("source_type"),
            "status": "blocked" if blocking_errors else ("warning" if warnings else "passed"),
            "warnings": warnings,
            "blocking_errors": blocking_errors,
            "preview_item_count": 0,
            "preview_kept_item_count": 0,
            "filter_report": None,
            "preview_items": [],
        }

    def _validate_preview_item(self, item: dict[str, Any], max_excerpt_chars: int) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        blocking_errors: list[str] = []
        source_url = item.get("source_url", "")
        excerpt = (item.get("short_excerpt") or item.get("summary") or item.get("title") or "").strip()
        if not source_url:
            blocking_errors.append("preview_item_source_url_missing")
        if "truthsocial.com" in source_url.lower():
            blocking_errors.append("preview_item_direct_truth_social_forbidden")
        if not excerpt:
            warnings.append("preview_item_excerpt_missing")
        if len(excerpt) > max_excerpt_chars:
            warnings.append("preview_item_excerpt_will_be_truncated")
        return warnings, blocking_errors

    def _report(
        self,
        status: str,
        path: Path,
        feeds: list[dict[str, Any]],
        warnings: list[str],
        blocking_errors: list[str],
    ) -> dict[str, Any]:
        return {
            "status": status,
            "config_path": str(path),
            "feed_count": len(feeds),
            "feeds": feeds,
            "warnings": warnings,
            "blocking_errors": blocking_errors,
            "manual_publish_only": True,
            "direct_truth_social_scraper_used": False,
            "items_enter_source_review_queue": True,
        }

    def _domain_blocked(self, domain: str, blocked_domains: set[str]) -> bool:
        normalized = domain.lower()
        return any(normalized == blocked or normalized.endswith("." + blocked) for blocked in blocked_domains)
