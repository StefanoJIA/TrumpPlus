from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefScript, Claim, ClaimEvidenceLink, EvidenceItem


class FactCheckQualityGate:
    HIGH_RISK_TYPES = {"accusation", "legal", "election", "economy"}
    HIGH_RISK_TERMS = {"accusation", "accuse", "fraud", "illegal", "crime", "court", "election", "jobs", "spending", "economy"}

    def evaluate(self, db: Session, brief: BriefScript) -> dict[str, Any]:
        sample_mode = any((post.get("source_policy") or {}).get("evidence", {}).get("sample_data") is True for post in (brief.ranked_posts or []))
        claim_ids = [claim.get("id") for claim in brief.claims if claim.get("id")]
        claims = list(db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()) if claim_ids else []
        links = list(db.scalars(select(ClaimEvidenceLink).where(ClaimEvidenceLink.claim_id.in_(claim_ids))).all()) if claim_ids else []
        links_by_claim: dict[int, list[ClaimEvidenceLink]] = {}
        for link in links:
            links_by_claim.setdefault(link.claim_id, []).append(link)

        claim_coverage = []
        missing = []
        weak = []
        high_risk = []
        warnings = []

        for claim in claims:
            evidence_links = [link for link in links_by_claim.get(claim.id, []) if link.evidence_item and link.evidence_item.human_status == "approved"]
            direct_items = list(db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id == claim.id, EvidenceItem.human_status == "approved")).all())
            evidence_items = {item.id: item for item in direct_items + [link.evidence_item for link in evidence_links if link.evidence_item]}.values()
            support_types = {link.support_type for link in evidence_links}
            if direct_items:
                support_types.update(item.supports_claim for item in direct_items)
            evidence_count = len(list(evidence_items))
            max_reliability = max([item.reliability_score for item in evidence_items], default=0)
            risk = self._is_high_risk(claim)
            row = {
                "claim_id": claim.id,
                "claim_type": claim.claim_type,
                "requires_fact_check": claim.requires_fact_check,
                "evidence_count": evidence_count,
                "support_types": sorted(support_types),
                "max_reliability_score": max_reliability,
                "high_risk": risk,
            }
            claim_coverage.append(row)

            if claim.claim_type == "opinion":
                continue
            if evidence_count == 0:
                missing.append(row)
                continue
            if claim.claim_type == "fact" and not (support_types & {"supports", "disputes"}):
                weak.append({**row, "reason": "fact_claim_requires_supports_or_disputes_evidence"})
            if risk:
                high_risk.append(row)
                if evidence_count < 2 or max_reliability < 70:
                    weak.append({**row, "reason": "high_risk_claim_requires_two_evidence_and_one_reliability_70"})
            for item in evidence_items:
                if item.evidence_type == "manual_note" and not (item.source_url or item.archive_url):
                    target = weak if risk else warnings
                    target.append({**row, "reason": "manual_note_without_external_link"})

        blocked = False if sample_mode else bool(missing or [item for item in weak if item.get("reason") != "manual_note_without_external_link" or item.get("high_risk")])
        status = "blocked" if blocked else "warning" if warnings or weak else "passed"
        return {
            "status": status,
            "sample_data_compatibility_mode": sample_mode,
            "claim_coverage": claim_coverage,
            "missing_evidence_claims": missing,
            "weak_evidence_claims": weak,
            "high_risk_claims": high_risk,
            "warnings": warnings,
            "recommendations": self._recommendations(missing, weak, warnings),
        }

    def _is_high_risk(self, claim: Claim) -> bool:
        text = (claim.claim_text or "").lower()
        return claim.claim_type in self.HIGH_RISK_TYPES or any(term in text for term in self.HIGH_RISK_TERMS)

    def _recommendations(self, missing: list[dict], weak: list[dict], warnings: list[dict]) -> list[str]:
        recommendations = []
        if missing:
            recommendations.append("Attach approved evidence before approving the brief.")
        if weak:
            recommendations.append("Strengthen high-risk or factual claims with reliable public sources.")
        if warnings:
            recommendations.append("Replace manual-note-only evidence with source links where possible.")
        if not recommendations:
            recommendations.append("Evidence coverage is sufficient for human review.")
        return recommendations
