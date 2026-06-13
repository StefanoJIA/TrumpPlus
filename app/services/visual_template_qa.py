from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image


class VisualTemplateQA:
    REQUIRED_FILES = ["cover.png", "card_01_topic.png", "card_02_fact_check.png", "card_03_timeline.png", "card_04_sources.png"]

    def review(self, render_dir: str | Path | None, template_config: dict[str, Any] | None = None) -> dict[str, Any]:
        template_config = template_config or {}
        expected_width = int((template_config.get("resolution") or {}).get("width", 1080))
        expected_height = int((template_config.get("resolution") or {}).get("height", 1920))
        render_path = Path(render_dir) if render_dir else None
        warnings: list[str] = []
        blockers: list[str] = []
        files: list[dict[str, Any]] = []
        if render_path is None or not render_path.exists():
            return {
                "qa_status": "blocked",
                "files": [],
                "warnings": [],
                "blocking_errors": ["Render package directory is missing."],
                "has_sources_card": False,
                "contains_project_name": False,
                "contains_ai_label": False,
                "contains_source_numbers": False,
            }
        for filename in self.REQUIRED_FILES:
            path = render_path / filename
            if not path.exists():
                blockers.append(f"Missing visual card: {filename}")
                continue
            with Image.open(path) as image:
                width, height = image.size
            if width != expected_width or height != expected_height:
                warnings.append(f"{filename} resolution is {width}x{height}, expected {expected_width}x{expected_height}.")
            files.append({"filename": filename, "width": width, "height": height, "exists": True})
        manifest = self._read_json(render_path / "manifest.json")
        safety_labels = " ".join(manifest.get("safety_labels") or [])
        source_cards = manifest.get("source_cards") or []
        output_files = manifest.get("output_files") or {}
        contains_project_name = (render_path / "cover.png").exists()
        contains_ai_label = bool(safety_labels) or template_config.get("show_ai_label") is True
        contains_source_numbers = bool(source_cards) if template_config.get("show_source_numbers", True) else True
        has_sources_card = bool(output_files.get("sources_card")) and (render_path / output_files.get("sources_card")).exists()
        if template_config.get("show_ai_label", True) and not contains_ai_label:
            blockers.append("AI/information-card label is missing from manifest.")
        if template_config.get("show_source_numbers", True) and not contains_source_numbers:
            warnings.append("Source numbers are missing from manifest source cards.")
        if not has_sources_card:
            blockers.append("Sources card is missing.")
        report = {
            "qa_status": "blocked" if blockers else "needs_revision" if warnings else "passed",
            "files": files,
            "expected_resolution": {"width": expected_width, "height": expected_height},
            "has_sources_card": has_sources_card,
            "contains_project_name": contains_project_name,
            "contains_ai_label": contains_ai_label,
            "contains_source_numbers": contains_source_numbers,
            "warnings": warnings,
            "blocking_errors": blockers,
        }
        return report

    def write_report(self, output_dir: Path, report: dict[str, Any]) -> Path:
        path = output_dir / "visual_template_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _read_json(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
