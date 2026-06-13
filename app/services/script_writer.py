from typing import Any


class ScriptWriter:
    def write(self, ranked_posts: list[dict[str, Any]], fact_checks: list[dict[str, Any]]) -> dict[str, Any]:
        sources = [{"url": post["source_url"], "post_id": post["post_id"], "type": "post_or_archive"} for post in ranked_posts]
        verdicts = sorted({item["verdict"] for item in fact_checks}) or ["unclear"]
        lines = [f"今天特朗普公开发帖重点有 {len(ranked_posts)} 个。"]
        subtitles = []
        cursor = 0
        for index, post in enumerate(ranked_posts, start=1):
            verdict_phrase = self._verdict_phrase(verdicts)
            line = (
                f"第 {index} 条，主题是 {post['topic']}。他说到：{post['summary']} "
                f"目前核验状态为 {', '.join(verdicts)}。{verdict_phrase}。"
                "这条内容值得关注，是因为它涉及公共议题表达，但仍需要结合原始来源和独立资料理解。"
            )
            lines.append(line)
            subtitles.append({"start_seconds": cursor, "end_seconds": cursor + 12, "text": line[:90]})
            cursor += 12
        closing = "以上为公开信息整理，来源与证据见说明区。本素材包只供人工审核，不自动发布。"
        lines.append(closing)
        subtitles.append({"start_seconds": cursor, "end_seconds": cursor + 8, "text": closing})
        return {
            "title": "特朗普公开发帖重点速读",
            "text": "\n".join(lines),
            "subtitle_draft": subtitles,
            "sources": sources,
        }

    def _verdict_phrase(self, verdicts: list[str]) -> str:
        verdict_set = set(verdicts)
        if "unsupported" in verdict_set or "unclear" in verdict_set:
            return "目前缺乏足够公开证据，不能写作已经证实的事实"
        if "disputed" in verdict_set:
            return "相关说法存在争议，需要并列呈现不同来源"
        if verdict_set == {"opinion"} or "opinion" in verdict_set:
            return "这属于政治表态或观点，不作为事实结论呈现"
        if "confirmed" in verdict_set:
            return "公开资料显示，该说法有来源支持"
        return "仍需结合来源和证据谨慎理解"
