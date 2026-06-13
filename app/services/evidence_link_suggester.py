from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefScript, Claim, EvidenceItem


@dataclass(frozen=True)
class EvidenceSuggestion:
    claim_id: int
    evidence_item_id: int
    support_type: str
    confidence: str
    score: int
    requires_manual_confirmation: bool
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "evidence_item_id": self.evidence_item_id,
            "support_type": self.support_type,
            "confidence": self.confidence,
            "score": self.score,
            "requires_manual_confirmation": self.requires_manual_confirmation,
            "note": self.note,
        }


class EvidenceLinkSuggester:
    HIGH_RISK_TYPES = {"accusation", "legal", "election", "economy"}
    HIGH_RISK_TERMS = {"accuse", "accusation", "illegal", "fraud", "court", "election", "economy", "spending", "jobs"}

    def suggest_for_brief(self, db: Session, brief: BriefScript, limit_per_claim: int = 3) -> dict[str, Any]:
        claim_ids = [claim.get("id") for claim in brief.claims or [] if claim.get("id")]
        claims = list(db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()) if claim_ids else []
        evidence_items = list(
            db.scalars(
                select(EvidenceItem)
                .where(EvidenceItem.workspace_id == brief.workspace_id, EvidenceItem.human_status == "approved")
                .order_by(EvidenceItem.reliability_score.desc(), EvidenceItem.id.asc())
            ).all()
        )
        suggestions = []
        for claim in claims:
            ranked = self.suggest_for_claim(claim, evidence_items)
            suggestions.extend([item.as_dict() for item in ranked[:limit_per_claim]])
        return {
            "brief_id": brief.id,
            "auto_approved": False,
            "suggestions": suggestions,
            "note": "Suggestions are for editor/reviewer reference only. They do not approve evidence or confirm facts.",
        }

    def suggest_for_claim(self, claim: Claim, evidence_items: list[EvidenceItem]) -> list[EvidenceSuggestion]:
        claim_terms = self._terms(claim.claim_text)
        results: list[EvidenceSuggestion] = []
        for item in evidence_items:
            evidence_terms = self._terms(" ".join([item.title or "", item.excerpt or "", item.summary or "", item.source_name or ""]))
            overlap = len(claim_terms & evidence_terms)
            score = overlap * 20 + min(item.reliability_score, 100) // 5
            if item.post_id and item.post_id == claim.post_id:
                score += 35
            if item.source_review_item_id:
                score += 10
            support_type = "supports" if overlap >= 2 or item.post_id == claim.post_id else "contextualizes"
            confidence = "high" if score >= 70 else "medium" if score >= 40 else "low"
            if score < 25:
                support_type = "source_only"
            results.append(
                EvidenceSuggestion(
                    claim_id=claim.id,
                    evidence_item_id=item.id,
                    support_type=support_type,
                    confidence=confidence,
                    score=score,
                    requires_manual_confirmation=self._is_high_risk(claim),
                    note="High-risk claims require reviewer confirmation." if self._is_high_risk(claim) else "Editor should verify fit before linking.",
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)

    def _terms(self, text: str) -> set[str]:
        return {term for term in re.findall(r"[A-Za-z0-9\u4e00-\u9fff]{2,}", (text or "").lower()) if len(term) >= 2}

    def _is_high_risk(self, claim: Claim) -> bool:
        text = (claim.claim_text or "").lower()
        return claim.claim_type in self.HIGH_RISK_TYPES or any(term in text for term in self.HIGH_RISK_TERMS)
