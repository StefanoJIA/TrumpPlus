from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefScript, EvidencePack, PlatformPackage, SafetyReview, SourceReviewItem


class BlockingReasonAggregator:
    def aggregate(self, db: Session) -> dict[str, Any]:
        reasons: list[dict[str, Any]] = []

        for item in db.scalars(select(SourceReviewItem)).all():
            if item.terms_status == "blocked" or item.human_status == "rejected":
                reasons.append(
                    {
                        "category": "source blocked",
                        "entity_type": "source_review_item",
                        "entity_id": item.id,
                        "reason": item.rejection_reason or item.reviewer_note or item.terms_status,
                    }
                )

        for pack in db.scalars(select(EvidencePack)).all():
            if pack.status in {"insufficient", "blocked"}:
                reasons.append(
                    {
                        "category": "evidence insufficient",
                        "entity_type": "evidence_pack",
                        "entity_id": pack.id,
                        "reason": pack.rationale,
                    }
                )
            if pack.verdict == "unsupported":
                reasons.append(
                    {
                        "category": "unsupported accusation",
                        "entity_type": "evidence_pack",
                        "entity_id": pack.id,
                        "reason": pack.rationale,
                    }
                )

        for safety in db.scalars(select(SafetyReview).where(SafetyReview.status == "blocked")).all():
            for reason in safety.checks.get("blocking_reasons", []):
                reasons.append(
                    {
                        "category": "safety blocked",
                        "entity_type": "safety_review",
                        "entity_id": safety.id,
                        "reason": reason,
                    }
                )

        for package in db.scalars(select(PlatformPackage).where(PlatformPackage.status.in_(["blocked", "failed"]))).all():
            category = "copy compliance failed" if package.status == "blocked" else "QA failed"
            reasons.append(
                {
                    "category": category,
                    "entity_type": "platform_package",
                    "entity_id": package.id,
                    "reason": package.error_message or package.status,
                }
            )

        blocked_briefs = db.scalars(select(BriefScript).where(BriefScript.status == "blocked")).all()
        counter = Counter(reason["category"] for reason in reasons)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for reason in reasons:
            grouped[reason["category"]].append(reason)
        return {
            "total_blocking_reasons": len(reasons),
            "blocked_brief_count": len(list(blocked_briefs)),
            "by_category": dict(counter),
            "items": reasons,
            "groups": dict(grouped),
        }
