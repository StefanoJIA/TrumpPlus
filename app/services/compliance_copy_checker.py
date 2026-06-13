from __future__ import annotations

from typing import Any


class ComplianceCopyChecker:
    EXTREME_TERMS = ["震惊", "疯了", "全网封杀", "彻底完了"]
    PERSUASION_TERMS = ["投票给", "支持他", "反对他", "拉票", "助选", "捐款给", "vote for", "donate to"]
    IMPERSONATION_TERMS = ["仿声", "克隆声音", "特朗普原声", "trump voice", "voice clone", "impersonation"]
    UNVERIFIED_ACCUSATION_TERMS = ["已经证实腐败", "确定犯罪", "铁证", "坐实"]
    UNSUPPORTED_CONFIRMATION_TERMS = ["已经证实", "事实证明", "确定无疑", "被证实为真"]

    def check_all(self, platform_copies: dict[str, dict[str, Any]]) -> dict[str, Any]:
        platforms = {}
        blocking_errors = []
        for platform, payload in platform_copies.items():
            result = self.check(platform, payload)
            platforms[platform] = result
            blocking_errors.extend([f"{platform}:{error}" for error in result["blocking_errors"]])
        return {
            "overall_status": "blocked" if blocking_errors else "passed",
            "blocking_errors": blocking_errors,
            "platforms": platforms,
            "manual_publish_only": True,
        }

    def check(self, platform: str, payload: dict[str, Any]) -> dict[str, Any]:
        text = self._all_text(payload)
        rules = []
        rules.append(self._rule("no_targeted_political_persuasion", not self._contains(text, self.PERSUASION_TERMS)))
        rules.append(self._rule("sources_present", bool(payload.get("source_disclosure")) and "source" in text.lower()))
        rules.append(self._rule("ai_disclosure_present", "AI" in text and ("人工审核" in text or "浜哄伐瀹℃牳" in text)))
        rules.append(self._rule("no_clickbait_extreme_terms", not self._contains(text, self.EXTREME_TERMS)))
        rules.append(self._rule("no_unverified_accusation", not self._contains(text, self.UNVERIFIED_ACCUSATION_TERMS)))
        rules.append(self._rule("no_unsupported_confirmation", not self._contains(text, self.UNSUPPORTED_CONFIRMATION_TERMS)))
        rules.append(self._rule("no_impersonation_claim", not self._contains(text.lower(), self.IMPERSONATION_TERMS)))
        checklist = payload.get("manual_publish_checklist") or []
        rules.append(self._rule("manual_publish_required", bool(checklist) and "manual publish only" in text.lower()))
        blocking = [rule["rule_id"] for rule in rules if not rule["passed"]]
        return {
            "platform": platform,
            "status": "blocked" if blocking else "passed",
            "rules": rules,
            "blocking_errors": blocking,
        }

    def _all_text(self, payload: dict[str, Any]) -> str:
        parts = []
        for key in ["description", "pinned_comment", "source_disclosure", "ai_disclosure"]:
            parts.append(str(payload.get(key) or ""))
        parts.extend(str(title) for title in payload.get("title_options") or [])
        parts.extend(str(tag) for tag in payload.get("tags") or [])
        parts.extend(str(item) for item in payload.get("manual_publish_checklist") or [])
        return "\n".join(parts)

    def _contains(self, text: str, terms: list[str]) -> bool:
        lowered = text.lower()
        return any(term.lower() in lowered for term in terms)

    def _rule(self, rule_id: str, passed: bool) -> dict[str, Any]:
        return {"rule_id": rule_id, "passed": passed, "severity": "blocking" if not passed else "info"}
