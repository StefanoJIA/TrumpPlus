from __future__ import annotations

import re
from typing import Any


class ScriptReadabilityQA:
    CLICKBAIT_TERMS = {"震惊", "疯了", "彻底完了", "全网封杀", "爆炸", "惊天", "翻车"}
    AI_TONE_TERMS = {"作为一个AI", "综上所述", "值得注意的是", "毋庸置疑", "不可否认的是"}
    ASSERTIVE_UNSUPPORTED_TERMS = {"已经证实", "事实证明", "坐实", "确定无疑", "铁证"}

    def review(self, script_text: str, fact_checks: list[dict] | None = None, target_min: int = 45, target_max: int = 90) -> dict[str, Any]:
        script_text = script_text or ""
        fact_checks = fact_checks or []
        warnings: list[str] = []
        suggested_edits: list[str] = []
        blockers: list[str] = []
        sentences = [item.strip() for item in re.split(r"[。！？!?;\n]+", script_text) if item.strip()]
        long_sentences = [sentence for sentence in sentences if len(sentence) > 90]
        if long_sentences:
            warnings.append(f"{len(long_sentences)} sentence(s) exceed 90 characters.")
            suggested_edits.append("Split long narration sentences into shorter spoken lines.")
        if any(term in script_text for term in self.AI_TONE_TERMS):
            warnings.append("Script contains AI-like or formal filler phrasing.")
            suggested_edits.append("Use direct, neutral spoken language.")
        if any(term in script_text for term in self.CLICKBAIT_TERMS):
            warnings.append("Script contains sensational terms.")
            suggested_edits.append("Remove clickbait or emotionally loaded wording.")
        unsupported_present = any(check.get("verdict") in {"unsupported", "unclear"} for check in fact_checks)
        if unsupported_present and any(term in script_text for term in self.ASSERTIVE_UNSUPPORTED_TERMS):
            blockers.append("Unsupported or unclear claim appears to be written as confirmed fact.")
            suggested_edits.append("Replace assertive wording with '目前缺乏足够公开证据' or equivalent caveat.")
        estimated_seconds = max(1, round(len(script_text) / 5.0))
        if estimated_seconds < target_min or estimated_seconds > target_max:
            warnings.append(f"Estimated spoken duration {estimated_seconds}s is outside {target_min}-{target_max}s.")
            suggested_edits.append("Adjust script length for a 45-90 second short video.")
        if not script_text.startswith("今天特朗普公开发帖重点"):
            warnings.append("Opening line is missing or does not match the expected neutral format.")
            suggested_edits.append("Start with: 今天特朗普公开发帖重点有 X 个。")
        if "以上为公开信息整理" not in script_text:
            warnings.append("Closing source reminder is missing.")
            suggested_edits.append("End with a source reminder and neutral framing.")
        score = 100 - len(warnings) * 10 - len(blockers) * 35 - min(len(long_sentences) * 3, 20)
        score = max(0, min(100, score))
        return {
            "readability_score": score,
            "estimated_duration_seconds": estimated_seconds,
            "long_sentence_count": len(long_sentences),
            "warnings": warnings,
            "blocking_errors": blockers,
            "suggested_edits": suggested_edits,
            "qa_status": "blocked" if blockers else "needs_revision" if warnings else "passed",
        }
