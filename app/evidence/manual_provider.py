from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import yaml

from app.evidence.base import EvidenceProvider


class ManualEvidenceProvider(EvidenceProvider):
    provider_name = "manual"

    def __init__(self, policy_path: str = "app/config/evidence_policy.yaml"):
        self.policy = yaml.safe_load(open(policy_path, encoding="utf-8"))

    def search_evidence(self, claim: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [self.normalize_evidence(kwargs)]

    def validate_provider_policy(self, environment: str = "production") -> None:
        if self.provider_name not in self.policy.get("allowed_providers", []):
            raise ValueError("Manual evidence provider is not allowlisted")

    def normalize_evidence(self, raw: dict[str, Any]) -> dict[str, Any]:
        source_url = raw["source_url"]
        domain = urlparse(source_url).netloc.lower()
        if domain in set(self.policy.get("blocked_domains", [])):
            raise ValueError("Blocked evidence source domain")
        excerpt = (raw.get("excerpt") or "").strip()
        if not excerpt:
            raise ValueError("Evidence excerpt is required")
        max_chars = int(self.policy.get("max_evidence_excerpt_chars", 500))
        warnings = []
        if len(excerpt) > max_chars:
            excerpt = excerpt[:max_chars]
            warnings.append("evidence_excerpt_truncated")
        retrieved_at = raw.get("retrieved_at")
        parsed_retrieved_at = (
            datetime.fromisoformat(retrieved_at.replace("Z", "+00:00")) if isinstance(retrieved_at, str) else retrieved_at
        ) or datetime.now(timezone.utc)
        return {
            "source": {
                "source_name": raw.get("source_name") or "manual evidence",
                "source_url": source_url,
                "archive_url": raw.get("archive_url"),
                "publisher_type": raw.get("publisher_type") or "manual",
                "reliability_tier": raw.get("reliability_tier") or "unknown",
                "retrieved_at": parsed_retrieved_at,
                "terms_status": raw.get("terms_status") or "manual_review_required",
                "metadata_json": {"provider": self.provider_name, "warnings": warnings},
            },
            "item": {
                "excerpt": excerpt,
                "summary": (raw.get("summary") or excerpt)[:1000],
                "supports_claim": raw.get("supports_claim") or "unclear",
                "confidence": float(raw.get("confidence", 0.0)),
                "reviewer_note": raw.get("reviewer_note"),
            },
        }
