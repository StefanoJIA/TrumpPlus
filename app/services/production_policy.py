from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProductionPolicy:
    def __init__(self, path: Path | None = None):
        self.path = path or Path("app/config/production_policy.yaml")
        self.config: dict[str, Any] = yaml.safe_load(self.path.read_text(encoding="utf-8"))

    @property
    def production_mode(self) -> bool:
        return bool(self.config.get("production_mode", True))

    def sample_data_allowed(self, explicit_test_mode: bool = False) -> bool:
        return bool(self.config.get("allow_sample_data", False)) or explicit_test_mode

    @property
    def max_daily_briefs(self) -> int:
        return int(self.config.get("max_daily_briefs", 1))

    @property
    def max_posts_per_brief(self) -> int:
        return int(self.config.get("max_posts_per_brief", 4))

    @property
    def export_retention_days(self) -> int:
        return int(self.config.get("export_retention_days", 30))
