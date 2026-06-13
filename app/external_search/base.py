from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import os

import yaml


class ExternalSearchPolicy:
    def __init__(self, path: Path | None = None):
        self.path = path or Path("app/config/external_search_policy.yaml")
        self.config = yaml.safe_load(self.path.read_text(encoding="utf-8"))

    @property
    def allow_external_search(self) -> bool:
        return bool(self.config.get("allow_external_search", False)) or os.getenv("ALLOW_EXTERNAL_SEARCH") == "true"

    def validate_provider(self, provider_name: str, production: bool = True) -> None:
        if provider_name not in set(self.config.get("allowed_providers", [])):
            raise ValueError(f"Unknown or disallowed external search provider: {provider_name}")
        if production and provider_name == "fake_search" and self.config.get("production_disallow_fake_search", True):
            raise ValueError("fake_search provider is blocked in production")
        if production and not self.allow_external_search:
            raise ValueError("External search is disabled by external_search_policy.allow_external_search=false")

    def validate_domain(self, source_url: str) -> tuple[str, list[str]]:
        domain = urlparse(source_url).netloc.lower()
        warnings = []
        if domain in set(self.config.get("blocked_domains", [])):
            raise ValueError("Blocked search result domain")
        allowed = set(self.config.get("allowed_domains", []))
        if allowed and domain not in allowed:
            warnings.append("domain_not_allowlisted")
        return domain, warnings

    def max_results(self) -> int:
        return int(self.config.get("max_results_per_claim", 5))

    def max_excerpt_chars(self) -> int:
        return int(self.config.get("max_excerpt_chars", 500))


class ExternalSearchProvider(ABC):
    provider_name: str

    @abstractmethod
    def search(self, query: str, claim: Any | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def validate_provider_policy(self, production: bool = True) -> None:
        raise NotImplementedError

    @abstractmethod
    def normalize_result(self, raw: dict[str, Any], query: str) -> dict[str, Any]:
        raise NotImplementedError

    def truncate_excerpt(self, excerpt: str) -> str:
        policy = ExternalSearchPolicy()
        return (excerpt or "")[: policy.max_excerpt_chars()]
