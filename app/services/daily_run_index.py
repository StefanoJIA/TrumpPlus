from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


class DailyRunIndexService:
    def __init__(self, root: Path | str = "exports/daily_runs"):
        self.root = Path(root)

    def load_runs(self, limit: int | None = None) -> list[dict[str, Any]]:
        runs = []
        if not self.root.exists():
            return []
        for report_path in self.root.glob("*/daily_run_report.json"):
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            runs.append(self.summarize_report(report, report_path))
        runs.sort(key=lambda item: item.get("generated_at") or item.get("date") or "", reverse=True)
        return runs[:limit] if limit else runs

    def latest(self) -> dict[str, Any] | None:
        runs = self.load_runs(limit=1)
        return runs[0] if runs else None

    def write_index(self) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True)
        runs = self.load_runs()
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_count": len(runs),
            "runs": runs,
            "latest": runs[0] if runs else None,
            "manual_publish_only": True,
            "platform_publish_api_called": False,
            "truth_social_direct_scraper_used": False,
        }
        (self.root / "index.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.root / "latest.json").write_text(json.dumps(payload["latest"] or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        return payload

    def summarize_report(self, report: dict[str, Any], report_path: Path) -> dict[str, Any]:
        final_video_path = report.get("final_video_path")
        platform_package_path = report.get("platform_package_path")
        manual_actions = report.get("manual_actions_required") or []
        blockers = report.get("blockers") or []
        warnings = report.get("warnings") or []
        return {
            "date": report.get("date"),
            "mode": report.get("mode"),
            "feed_mode": report.get("feed_mode"),
            "generated_at": report.get("generated_at"),
            "report_path": str(report_path),
            "markdown_path": str(report_path.with_name("DAILY_RUN_REPORT.md")),
            "brief_id": report.get("brief_id"),
            "selected_topic": report.get("selected_topic"),
            "fact_check_quality_gate_status": report.get("fact_check_quality_gate_status"),
            "publish_readiness": report.get("publish_readiness"),
            "final_video_path": final_video_path,
            "final_video_exists": bool(final_video_path and Path(final_video_path).exists()),
            "platform_package_path": platform_package_path,
            "platform_package_exists": bool(platform_package_path and Path(platform_package_path).exists()),
            "feed_item_count": report.get("feed_item_count", 0),
            "accepted_source_count": report.get("accepted_source_count", 0),
            "manual_actions_count": len(manual_actions),
            "manual_actions_required": manual_actions,
            "blockers_count": len(blockers),
            "blockers": blockers,
            "warnings_count": len(warnings),
            "warnings": warnings,
            "manual_publish_only": report.get("manual_publish_only") is True,
            "platform_publish_api_called": report.get("platform_publish_api_called") is True,
            "truth_social_direct_scraper_used": report.get("truth_social_direct_scraper_used") is True,
        }
