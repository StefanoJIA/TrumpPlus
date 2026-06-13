from __future__ import annotations

from pathlib import Path
import json
from typing import Any
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefScript, EditorialCalendarEntry, EditorialTopic, EvidenceCandidate, EvidencePack, FinalVideo, PlatformPackage, Post, SourceReviewItem
from app.services.blocking_reason_aggregator import BlockingReasonAggregator


class OpsDashboardService:
    def summary(self, db: Session) -> dict[str, int]:
        tts = self._tts_summary()
        return {
            "pending_source_reviews": self._count(db, SourceReviewItem, SourceReviewItem.human_status == "pending"),
            "approved_sources": self._count(db, SourceReviewItem, SourceReviewItem.human_status == "approved"),
            "promoted_posts": len(
                [
                    post
                    for post in db.scalars(select(Post)).all()
                    if post.source_policy.get("human_source_review_status") == "promoted"
                ]
            ),
            "briefs_needs_review": self._count(db, BriefScript, BriefScript.status == "needs_review"),
            "blocked_briefs": self._count(db, BriefScript, BriefScript.status == "blocked"),
            "evidence_needs_review": self._count(db, EvidencePack, EvidencePack.status == "needs_review"),
            "approved_briefs": self._count(db, BriefScript, BriefScript.status == "approved"),
            "rendered_videos": self._count(db, FinalVideo, FinalVideo.status == "rendered"),
            "platform_packages": self._count(db, PlatformPackage, PlatformPackage.status == "generated"),
            "tts_pending": tts["pending"],
            "tts_ready": tts["ready"],
            "tts_blocked": tts["blocked"],
            "pending_evidence_candidates": self._count(db, EvidenceCandidate, EvidenceCandidate.status == "pending"),
            "blocked_evidence_candidates": self._count(db, EvidenceCandidate, EvidenceCandidate.status == "blocked"),
            "accepted_evidence_candidates": self._count(db, EvidenceCandidate, EvidenceCandidate.status == "accepted"),
            "claims_needing_search": self._count(db, EvidencePack, EvidencePack.status == "insufficient"),
            "pending_topics": self._count(db, EditorialTopic, EditorialTopic.status == "pending"),
            "topics_needing_evidence": self._count(db, EditorialTopic, EditorialTopic.status == "needs_more_evidence"),
            "scheduled_topics_today": self._count(
                db,
                EditorialCalendarEntry,
                (EditorialCalendarEntry.date == date.today()) & (EditorialCalendarEntry.status.in_(["ready_for_brief", "in_production"])),
            ),
            "briefs_generated_from_calendar": len(
                [
                    brief
                    for brief in db.scalars(select(BriefScript)).all()
                    if brief.metadata_json.get("generated_from_editorial_calendar") is True
                ]
            ),
        }

    def queue_status(self, db: Session) -> dict[str, Any]:
        return {
            "source_review_queue": [
                {"id": item.id, "source_name": item.source_name, "human_status": item.human_status, "terms_status": item.terms_status}
                for item in db.scalars(select(SourceReviewItem).order_by(SourceReviewItem.id.desc())).all()
            ],
            "evidence_review_queue": [
                {"id": pack.id, "claim_id": pack.claim_id, "status": pack.status, "verdict": pack.verdict, "review_status": pack.review_status}
                for pack in db.scalars(select(EvidencePack).order_by(EvidencePack.id.desc())).all()
                if pack.status in {"needs_review", "insufficient", "blocked"} or pack.review_status == "pending"
            ],
            "briefs_awaiting_approval": [
                {"id": brief.id, "title": brief.title, "status": brief.status}
                for brief in db.scalars(select(BriefScript).where(BriefScript.status == "needs_review")).all()
            ],
            "final_videos_ready": [
                {"id": video.id, "brief_id": video.brief_id, "video_path": video.video_path}
                for video in db.scalars(select(FinalVideo).where(FinalVideo.status == "rendered")).all()
            ],
            "platform_packages_ready": [
                {"id": package.id, "brief_id": package.brief_id, "package_path": package.package_path}
                for package in db.scalars(select(PlatformPackage).where(PlatformPackage.status == "generated")).all()
            ],
            "voice_qa_blocked": self._voice_qa_blocked(),
            "evidence_candidates": [
                {"id": item.id, "claim_id": item.claim_id, "status": item.status, "source_url": item.source_url}
                for item in db.scalars(select(EvidenceCandidate).order_by(EvidenceCandidate.id.desc())).all()
            ],
            "editorial_topics": [
                {
                    "id": item.id,
                    "date": item.date.isoformat(),
                    "title": item.title,
                    "status": item.status,
                    "priority_score": item.priority_score,
                    "risk_score": item.risk_score,
                    "editor_note": item.editor_note,
                }
                for item in db.scalars(select(EditorialTopic).order_by(EditorialTopic.id.desc())).all()
            ],
            "editorial_calendar": [
                {
                    "id": item.id,
                    "date": item.date.isoformat(),
                    "topic_id": item.topic_id,
                    "slot_name": item.slot_name,
                    "status": item.status,
                    "target_platforms": item.target_platforms,
                }
                for item in db.scalars(select(EditorialCalendarEntry).order_by(EditorialCalendarEntry.date.desc(), EditorialCalendarEntry.id.desc())).all()
            ],
            "topic_rejection_reasons": [
                {"id": item.id, "title": item.title, "editor_note": item.editor_note}
                for item in db.scalars(select(EditorialTopic).where(EditorialTopic.status == "rejected").order_by(EditorialTopic.id.desc())).all()
            ],
        }

    def blocking_reasons(self, db: Session) -> dict[str, Any]:
        return BlockingReasonAggregator().aggregate(db)

    def daily_runs(self, base_dir: Path | None = None) -> list[dict[str, Any]]:
        root = base_dir or Path("exports/production_runs")
        if not root.exists():
            return []
        runs = []
        for path in sorted(root.iterdir(), reverse=True):
            if path.is_dir():
                report = path / "run_report.json"
                runs.append({"date": path.name, "path": str(report), "exists": report.exists()})
        return runs

    def _count(self, db: Session, model: type, criterion) -> int:
        return len(list(db.scalars(select(model).where(criterion)).all()))

    def _tts_summary(self) -> dict[str, int]:
        root = Path("exports/tts")
        counts = {"pending": 0, "ready": 0, "blocked": 0}
        if not root.exists():
            return counts
        for path in root.glob("brief_*"):
            qa_path = path / "voice_qa_report.json"
            if not qa_path.exists():
                counts["pending"] += 1
                continue
            status = json.loads(qa_path.read_text(encoding="utf-8")).get("status")
            if status == "blocked":
                counts["blocked"] += 1
            elif status in {"passed", "warning"}:
                counts["ready"] += 1
            else:
                counts["pending"] += 1
        return counts

    def _voice_qa_blocked(self) -> list[dict[str, Any]]:
        root = Path("exports/tts")
        blocked = []
        if not root.exists():
            return blocked
        for path in root.glob("brief_*"):
            qa_path = path / "voice_qa_report.json"
            if qa_path.exists():
                qa = json.loads(qa_path.read_text(encoding="utf-8"))
                if qa.get("status") == "blocked":
                    blocked.append({"brief_id": path.name.replace("brief_", ""), "path": str(qa_path), "blocking_reasons": qa.get("blocking_reasons", [])})
        return blocked
