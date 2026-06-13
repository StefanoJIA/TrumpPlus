from typing import Any


class VisualPlanner:
    def plan(self, ranked_posts: list[dict[str, Any]], fact_checks: list[dict[str, Any]]) -> dict[str, Any]:
        cards = [
            {
                "type": "cover",
                "text": "特朗普公开发帖重点速读",
                "visual": "抽象新闻时间线背景，不使用 Truth Social 截图。",
                "ai_label": "AI 生成示意图",
            }
        ]
        for index, post in enumerate(ranked_posts[:4], start=1):
            cards.append(
                {
                    "type": "info_card",
                    "text": f"{index}. {post['topic']}：{post['summary'][:80]}",
                    "visual": "关键词卡片、时间轴或事实核验卡；禁止拟真社交媒体截图。",
                    "ai_label": "AI 生成示意图",
                }
            )
        cards.append(
            {
                "type": "fact_check",
                "text": "核验状态：" + " / ".join(sorted({item["verdict"] for item in fact_checks})),
                "visual": "表格化核验卡，列出来源链接类型。",
                "ai_label": "AI 生成示意图",
            }
        )
        return {
            "cover_title": "特朗普公开发帖重点速读",
            "cover_subtitle": "公开信息整理 | 中立解析 | 人工审核后使用",
            "cards": cards[:6],
            "prohibited": ["fake_screenshot", "voice_impersonation", "lip_sync", "misleading_photorealism"],
        }

