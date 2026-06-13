from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, ClaimEvidenceLink, EvidenceItem, EvidencePack


class EvidencePackService:
    REVIEW_REQUIRED_TYPES = {"fact", "prediction", "accusation", "quote", "number", "legal", "election", "policy"}

    def build_or_update_pack(self, db: Session, claim: Claim) -> EvidencePack:
        evidence_items = self.evidence_items_for_claim(db, claim.id)
        pack = db.scalars(
            select(EvidencePack).where(EvidencePack.claim_id == claim.id).order_by(EvidencePack.id.desc())
        ).first()
        if pack is None:
            pack = EvidencePack(claim_id=claim.id, status="pending", verdict="unclear", rationale="")
            db.add(pack)
            db.flush()
        verdict, status, rationale = self.evaluate(claim, evidence_items)
        pack.verdict = verdict
        pack.status = status
        pack.rationale = rationale
        pack.evidence_count = len(evidence_items)
        pack.required_human_review = claim.claim_type in self.REVIEW_REQUIRED_TYPES
        return pack

    def evidence_items_for_claim(self, db: Session, claim_id: int) -> list[EvidenceItem]:
        direct_items = list(db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id == claim_id)).all())
        linked_items = [
            link.evidence_item
            for link in db.scalars(select(ClaimEvidenceLink).where(ClaimEvidenceLink.claim_id == claim_id)).all()
            if link.evidence_item is not None and link.evidence_item.human_status == "approved"
        ]
        by_id = {item.id: item for item in direct_items + linked_items}
        return list(by_id.values())

    def link_supports_for_claim(self, db: Session, claim_id: int) -> dict[int, str]:
        return {
            link.evidence_item_id: link.support_type
            for link in db.scalars(select(ClaimEvidenceLink).where(ClaimEvidenceLink.claim_id == claim_id)).all()
        }

    def evaluate(self, claim: Claim, evidence_items: list[EvidenceItem]) -> tuple[str, str, str]:
        if claim.claim_type == "opinion":
            return "opinion", "sufficient", "Opinion or commentary claim; evidence is optional and should not be framed as verified fact."
        if not evidence_items:
            if claim.claim_type == "accusation":
                return "unsupported", "insufficient", "Accusation lacks independent evidence and must not be presented as fact."
            return "unclear", "insufficient", "No evidence has been attached yet; claim needs human review before use as factual support."
        supports = {self._normalized_support(item.supports_claim) for item in evidence_items}
        if "contradicts" in supports:
            return "disputed", "needs_review", "Attached evidence contradicts the claim or introduces material dispute."
        if "supports" in supports:
            return "confirmed", "sufficient", "Attached evidence supports the claim at the stated confidence level."
        if supports <= {"contextual", "unclear", "unrelated"}:
            return "unclear", "needs_review", "Attached evidence is contextual or unclear and requires editor review."
        return "unclear", "needs_review", "Evidence relationship is mixed or unresolved."

    def pack_payload(self, pack: EvidencePack, evidence_items: list[EvidenceItem] | None = None) -> dict[str, Any]:
        return {
            "id": pack.id,
            "claim_id": pack.claim_id,
            "status": pack.status,
            "verdict": pack.verdict,
            "rationale": pack.rationale,
            "evidence_count": pack.evidence_count,
            "required_human_review": pack.required_human_review,
            "review_status": pack.review_status,
            "reviewer_name": pack.reviewer_name,
            "reviewer_note": pack.reviewer_note,
            "evidence_items": [] if evidence_items is None else [self.evidence_item_payload(item) for item in evidence_items],
        }

    def evidence_item_payload(self, item: EvidenceItem) -> dict[str, Any]:
        source = item.evidence_source
        return {
            "id": item.id,
            "workspace_id": item.workspace_id,
            "source_review_item_id": item.source_review_item_id,
            "post_id": item.post_id,
            "claim_id": item.claim_id,
            "evidence_source_id": item.evidence_source_id,
            "evidence_type": item.evidence_type,
            "title": item.title,
            "source_name": item.source_name or (source.source_name if source else None),
            "source_url": item.source_url or (source.source_url if source else None),
            "archive_url": item.archive_url or (source.archive_url if source else None),
            "excerpt": item.excerpt,
            "summary": item.summary,
            "retrieved_at": item.retrieved_at.isoformat() if item.retrieved_at else None,
            "reliability_score": item.reliability_score,
            "terms_status": item.terms_status,
            "human_status": item.human_status,
            "supports_claim": item.supports_claim,
            "confidence": item.confidence,
            "reviewer_note": item.reviewer_note,
            "source": None
            if source is None
            else {
                "id": source.id,
                "source_name": source.source_name,
                "source_url": source.source_url,
                "archive_url": source.archive_url,
                "publisher_type": source.publisher_type,
                "reliability_tier": source.reliability_tier,
                "retrieved_at": source.retrieved_at.isoformat(),
                "terms_status": source.terms_status,
                "metadata_json": source.metadata_json,
            },
        }

    def fact_check_payload(self, claim: Claim, pack: EvidencePack, evidence_items: list[EvidenceItem]) -> dict[str, Any]:
        return {
            "verdict": pack.verdict,
            "rationale": pack.rationale,
            "sources": [
                {
                    "type": item.evidence_source.publisher_type,
                    "url": item.source_url or item.evidence_source.source_url,
                    "archive_url": item.archive_url or item.evidence_source.archive_url,
                    "reliability_tier": item.evidence_source.reliability_tier,
                    "reliability_score": item.reliability_score,
                    "supports_claim": item.supports_claim,
                    "confidence": item.confidence,
                    "excerpt": item.excerpt,
                    "note": item.reviewer_note,
                }
                for item in evidence_items
                if item.evidence_source is not None
            ],
            "provider": "evidence_pack",
        }

    def _normalized_support(self, support: str) -> str:
        return {
            "disputes": "contradicts",
            "supports": "supports",
            "contextualizes": "contextual",
            "source_only": "contextual",
        }.get(support, support)
