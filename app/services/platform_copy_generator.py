from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class PlatformCopyGenerator:
    def __init__(self, profile_path: Path | None = None):
        self.profile_path = profile_path or Path("app/config/platform_profiles.yaml")

    def load_profiles(self) -> dict[str, dict[str, Any]]:
        return yaml.safe_load(self.profile_path.read_text(encoding="utf-8"))

    def generate_all(self, brief_payload: dict[str, Any], final_video: dict[str, Any]) -> dict[str, dict[str, Any]]:
        profiles = self.load_profiles()
        return {
            platform: self.generate(platform, profile, brief_payload, final_video)
            for platform, profile in profiles.items()
        }

    def generate(
        self,
        platform: str,
        profile: dict[str, Any],
        brief_payload: dict[str, Any],
        final_video: dict[str, Any],
    ) -> dict[str, Any]:
        topic = self._topic(brief_payload)
        count = len(brief_payload.get("ranked_posts") or [])
        max_chars = int(profile["title_max_chars"])
        title_options = [
            self._trim(f"特朗普公开发帖重点速读：{topic}", max_chars),
            self._trim(f"今日公开信息整理：{count}个重点", max_chars),
            self._trim(f"公开发帖背景与核验：{topic}", max_chars),
        ]
        source_disclosure = self._source_disclosure(brief_payload.get("script", {}).get("sources") or [])
        ai_disclosure = "AI 辅助整理 / 人工审核；画面为信息整理卡 / AI 生成示意图，不是假截图。"
        description = self._trim(
            "\n".join(
                [
                    "本视频为公开政治社交媒体信息的中立整理与背景说明，不构成投票建议或政治动员。",
                    f"本期关注：{topic}。",
                    "来源与证据见说明/评论区；未获足够证据支持的内容不会写作确认性结论。",
                    source_disclosure,
                    ai_disclosure,
                    "Manual publish only: 平台发布前必须由编辑再次核对来源、字幕、封面和免责声明。",
                ]
            ),
            int(profile["description_max_chars"]),
        )
        checklist = [
            "Manual publish only: 不调用平台自动发布 API。",
            "确认 brief 已 approved，且 safety_review 非 blocked。",
            "确认简介保留来源说明和 AI 辅助整理 / 人工审核提示。",
            "确认标题无夸张误导词，不做支持或反对任何候选人、政党或政治行动的动员。",
            "确认封面为信息整理卡 / AI 生成示意图，不是假 Truth Social 截图。",
            "确认 final_video.mp4 可播放，含画面、字幕和音频轨道。",
        ]
        tags = self._tags(platform, profile)
        return {
            "platform": platform,
            "title_options": title_options,
            "description": description,
            "pinned_comment": f"{source_disclosure}\n{ai_disclosure}\nManual publish only; no automatic posting.",
            "tags": tags,
            "source_disclosure": source_disclosure,
            "ai_disclosure": ai_disclosure,
            "cover_selection": "Use cover.png or card_01_topic.png from the approved render package; do not create fake screenshots.",
            "video_path": final_video.get("video_path"),
            "manual_publish_checklist": checklist,
            "policy_notes": {
                "automatic_publishing": False,
                "neutral_non_persuasive_copy": True,
                "requires_manual_review_before_publish": True,
            },
        }

    def _topic(self, brief_payload: dict[str, Any]) -> str:
        ranked = brief_payload.get("ranked_posts") or []
        if ranked:
            return str(ranked[0].get("topic") or ranked[0].get("summary") or "公开发帖")
        return str(brief_payload.get("title") or "公开发帖")

    def _source_disclosure(self, sources: list[dict[str, Any]]) -> str:
        if not sources:
            return "Sources: missing; package must not be published until sources are restored."
        lines = ["Sources:"]
        for index, source in enumerate(sources, start=1):
            url = source.get("url") or source.get("source_url") or "missing-url"
            source_type = source.get("type") or "public source"
            lines.append(f"S{index}: {source_type} - {url}")
        return "\n".join(lines)

    def _tags(self, platform: str, profile: dict[str, Any]) -> list[str]:
        base = ["公开信息整理", "事实核验", "国际新闻", "政治社交媒体", "AI辅助整理", "人工审核"]
        platform_tag = {
            "bilibili": "B站短视频",
            "xiaohongshu": "小红书笔记",
            "douyin": "短视频资讯",
            "youtube_shorts": "YouTubeShorts",
        }.get(platform)
        if platform_tag:
            base.append(platform_tag)
        return base[: int(profile["tag_max_count"])]

    def _trim(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        return text[: max(0, max_chars - 1)].rstrip() + "…"
