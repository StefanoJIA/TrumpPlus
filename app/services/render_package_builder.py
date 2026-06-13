from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.renderers.ffmpeg_stub import check_render_readiness
from app.services.card_renderer import CardRenderer
from app.services.subtitle_generator import SubtitleGenerator


class RenderPackageBuilder:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path("exports/render_packages")

    def build(self, brief_payload: dict) -> dict:
        brief_id = brief_payload["id"]
        output_dir = self.base_dir / f"brief_{brief_id}"
        if output_dir.exists():
            shutil.rmtree(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        script_text = brief_payload["script"]["text"]
        (output_dir / "script.txt").write_text(script_text, encoding="utf-8")
        subtitle_result = SubtitleGenerator().generate(script_text, output_dir, duration_target_seconds=60)
        rendered_cards = CardRenderer().render_cards(brief_payload, output_dir)
        sources_path = output_dir / "sources.json"
        safety_path = output_dir / "safety_review.json"
        sources_path.write_text(json.dumps(brief_payload["script"]["sources"], ensure_ascii=False, indent=2), encoding="utf-8")
        safety_path.write_text(json.dumps(brief_payload["safety_review"], ensure_ascii=False, indent=2), encoding="utf-8")

        manifest = self._manifest(brief_payload, subtitle_result["items"], rendered_cards)
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        (output_dir / "README_RENDER.md").write_text(self._readme(brief_payload), encoding="utf-8")
        readiness = check_render_readiness(output_dir)
        manifest["output_files"]["readiness_report"] = "readiness_report.json"
        manifest["ffmpeg_stub_readiness"] = readiness
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "output_dir": str(output_dir),
            "manifest_path": str(manifest_path),
            "manifest": manifest,
            "readiness_report": readiness,
        }

    def _manifest(self, brief_payload: dict, subtitles: list[dict], cards: list[dict]) -> dict:
        visual_cards = []
        card_duration = 60 / max(1, len(cards))
        for index, card in enumerate(cards):
            visual_cards.append(
                {
                    "scene_type": card["scene_type"],
                    "duration_seconds": round(card_duration, 2),
                    "image_path": card["filename"],
                    "subtitle_range": [max(1, index * 2 + 1), min(len(subtitles), index * 2 + 2)],
                }
            )
        script_lines = [line for line in brief_payload["script"]["text"].splitlines() if line.strip()]
        segments = [
            {"index": index, "text": line, "duration_seconds": round(60 / max(1, len(script_lines)), 2)}
            for index, line in enumerate(script_lines, start=1)
        ]
        return {
            "brief_id": brief_payload["id"],
            "title": brief_payload["title"],
            "duration_target_seconds": 60,
            "aspect_ratio": "9:16",
            "script_segments": segments,
            "subtitle_items": subtitles,
            "visual_cards": visual_cards,
            "source_cards": [
                {"source_id": f"S{index}", "url": source.get("url"), "type": source.get("type", "source")}
                for index, source in enumerate(brief_payload["script"]["sources"], start=1)
            ],
            "safety_labels": ["信息整理卡 / AI 生成示意图", "No fake screenshots", "No voice impersonation", "No auto publishing"],
            "output_files": {
                "manifest": "manifest.json",
                "script": "script.txt",
                "subtitles_srt": "subtitles.srt",
                "subtitles_json": "subtitles.json",
                "cover": "cover.png",
                "topic_card": "card_01_topic.png",
                "fact_check_card": "card_02_fact_check.png",
                "timeline_card": "card_03_timeline.png",
                "sources_card": "card_04_sources.png",
                "sources": "sources.json",
                "safety_review": "safety_review.json",
                "readme": "README_RENDER.md",
            },
        }

    def _readme(self, brief_payload: dict) -> str:
        return "\n".join(
            [
                "# Daily Truth Brief Render Package",
                "",
                "This directory contains local production assets only. It does not include generated MP4, TTS, voice cloning, lip sync, or automatic publishing.",
                "",
                "Visual cards are labeled `信息整理卡 / AI 生成示意图` and must not be used as fake social-media screenshots.",
                "",
                f"Brief ID: {brief_payload['id']}",
                f"Title: {brief_payload['title']}",
            ]
        )
