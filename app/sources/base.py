from abc import ABC, abstractmethod
from typing import Any


class SourceAdapter(ABC):
    """Adapter boundary for compliant public archives or manually reviewed inputs."""

    @abstractmethod
    def fetch_latest_posts(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def normalize_post(self, raw: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_terms_safety(self) -> None:
        raise NotImplementedError

