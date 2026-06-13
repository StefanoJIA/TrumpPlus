from __future__ import annotations

from typing import Any


class AutoTopicSelector:
    def select(self, topics: list[dict[str, Any]]) -> dict[str, Any]:
        candidates = [self.score_topic(topic) for topic in topics]
        selectable = [item for item in candidates if item["auto_selection_status"] == "selectable"]
        if not selectable:
            return {
                "selected_topic": None,
                "candidates": candidates,
                "blocking_reason": "No selectable topic. Human review or stronger evidence required.",
            }
        selected = sorted(selectable, key=lambda item: item["auto_score"], reverse=True)[0]
        return {"selected_topic": selected, "candidates": candidates, "blocking_reason": None}

    def score_topic(self, topic: dict[str, Any]) -> dict[str, Any]:
        rationale = topic.get("rationale") or {}
        source_count = len(topic.get("selected_post_ids") or [])
        evidence_strength = float(topic.get("evidence_score") or rationale.get("evidence_readiness") or 0)
        public_importance = float(rationale.get("news_value") or topic.get("priority_score") or 0)
        scriptability = float(topic.get("platform_fit_score") or rationale.get("platform_fit") or 0)
        risk_level = float(topic.get("risk_score") or rationale.get("risk") or 0)
        novelty = float(rationale.get("freshness") or 0.6)
        auto_score = round(
            min(1.0, source_count / 3) * 0.15
            + evidence_strength * 0.25
            + public_importance * 0.20
            + scriptability * 0.20
            + novelty * 0.15
            - risk_level * 0.20,
            4,
        )
        status = "selectable"
        reasons = []
        if risk_level >= 0.65 and evidence_strength < 0.60:
            status = "blocked"
            reasons.append("high_risk_topic_has_weak_evidence")
        if evidence_strength < 0.20 and source_count <= 1:
            status = "deprioritized"
            reasons.append("only_opinion_or_no_evidence")
        if risk_level >= 0.80 and evidence_strength < 0.75:
            status = "blocked"
            reasons.append("overly_disputed_weak_evidence")
        return {
            **topic,
            "auto_score": auto_score,
            "auto_selection_status": status,
            "auto_selection_reasons": reasons,
            "score_breakdown": {
                "source_count": source_count,
                "evidence_strength": evidence_strength,
                "public_importance": public_importance,
                "scriptability": scriptability,
                "risk_level": risk_level,
                "novelty": novelty,
            },
        }
