from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class SourcePolicyResult:
    allowed: bool
    requires_human_source_review: bool
    reasons: list[str]
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "requires_human_source_review": self.requires_human_source_review,
            "reasons": self.reasons,
            "evidence": self.evidence,
        }


class SourcePolicy:
    def __init__(self, path: Path | None = None):
        self.path = path or Path("app/config/source_policy.yaml")
        self.config = yaml.safe_load(self.path.read_text(encoding="utf-8"))

    def validate_source(self, post: dict[str, Any], source: dict[str, Any] | None = None) -> SourcePolicyResult:
        source = source or post.get("source", {})
        source_name = source.get("name", "")
        source_url = post.get("source_url")
        manual_input = bool(source.get("manual_input") or source.get("sample_data"))
        parsed_domain = urlparse(source_url or "").netloc.lower()
        allowed_names = {item["name"] for item in self.config.get("allowed_sources", [])}
        manual_review_names = set(self.config.get("manual_review_required_sources", []))
        blocked_domains = set(self.config.get("blocked_domains", self.config.get("blocked_sources", [])))
        max_excerpt_chars = int(self.config.get("max_excerpt_chars", 500))
        sample_data = bool(source.get("sample_data"))

        reasons: list[str] = []
        if self.config.get("require_source_url", True) and not source_url:
            reasons.append("source_url_missing")
        if parsed_domain in blocked_domains:
            reasons.append("blocked_source_domain")
        if len(post.get("short_excerpt") or post.get("text") or "") > max_excerpt_chars:
            reasons.append("excerpt_too_long")
        if source_name not in allowed_names and not manual_input:
            reasons.append("unknown_source_not_manual_input")
        if (
            self.config.get("require_archive_url_when_available", True)
            and source.get("archive_url_available")
            and not source.get("public_archive_url")
        ):
            reasons.append("archive_url_missing")

        requires_review = manual_input or source_name in manual_review_names
        return SourcePolicyResult(
            allowed=not reasons or (manual_input and reasons == ["excerpt_too_long"]),
            requires_human_source_review=requires_review,
            reasons=reasons,
            evidence={
                "source_name": source_name,
                "source_url": source_url,
                "domain": parsed_domain,
                "manual_input": manual_input,
                "sample_data": sample_data,
                "max_excerpt_chars": max_excerpt_chars,
            },
        )
