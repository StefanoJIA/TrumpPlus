from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BriefScript, EditorialCalendarEntry, EditorialTopic, EvidencePack, FinalVideo, PlatformPackage, RenderPackage, SafetyReview


class NextActionService:
    def brief_next_action(self, db: Session, brief: BriefScript, tts_status: dict[str, Any] | None = None) -> dict[str, Any]:
        safety = db.scalars(
            select(SafetyReview).where(SafetyReview.brief_script_id == brief.id).order_by(SafetyReview.id.desc())
        ).first()
        render_package = db.scalars(select(RenderPackage).where(RenderPackage.brief_id == brief.id).order_by(RenderPackage.id.desc())).first()
        final_video = db.scalars(select(FinalVideo).where(FinalVideo.brief_id == brief.id).order_by(FinalVideo.id.desc())).first()
        platform_package = db.scalars(select(PlatformPackage).where(PlatformPackage.brief_id == brief.id).order_by(PlatformPackage.id.desc())).first()
        claim_ids = [claim.get("id") for claim in brief.claims if claim.get("id")]
        packs = list(db.scalars(select(EvidencePack).where(EvidencePack.claim_id.in_(claim_ids))).all()) if claim_ids else []
        tts = tts_status or {"status": "missing"}

        links = {
            "brief": f"/briefs/{brief.id}",
            "production_console": f"/editorial/briefs/{brief.id}/production-console",
            "evidence_report": f"/briefs/{brief.id}/evidence-pack/report",
            "render_package": f"/briefs/{brief.id}/render-package",
            "tts_status": f"/briefs/{brief.id}/tts/status",
            "final_video": f"/briefs/{brief.id}/final-video",
            "platform_package": f"/briefs/{brief.id}/platform-package",
        }

        if not packs and claim_ids:
            return self._payload("generate_evidence_pack", ["generate_evidence_pack"], [], ["evidence_pack_missing"], False, links)
        if safety is None:
            return self._payload("generate_evidence_pack", ["generate_evidence_pack"], [], ["safety_review_missing"], False, links)
        if safety.status == "blocked" or brief.status == "blocked":
            return self._payload(
                "blocked",
                [],
                ["approve_brief", "generate_render_package", "generate_final_video", "generate_platform_package"],
                ["safety_review_blocked"],
                True,
                links,
            )
        if brief.status != "approved":
            return self._payload(
                "await_human_approval",
                ["approve_brief", "block_brief", "request_changes"],
                ["generate_render_package", "generate_final_video", "generate_platform_package", "publish"],
                ["human_approval_required"],
                True,
                links,
            )
        if render_package is None or render_package.status != "generated":
            return self._payload("generate_render_package", ["generate_render_package"], ["generate_final_video", "generate_platform_package", "publish"], [], False, links)
        final_video_ready = final_video is not None and final_video.status == "rendered" and final_video.video_path and Path(final_video.video_path).exists()
        if not final_video_ready:
            if tts.get("status") == "blocked":
                return self._payload("blocked", [], ["generate_final_video", "generate_platform_package", "publish"], ["voice_qa_blocked"], True, links)
            if tts.get("status") == "missing":
                return self._payload("generate_tts", ["generate_tts"], ["generate_final_video", "generate_platform_package", "publish"], [], False, links)
            return self._payload("generate_final_video", ["generate_final_video"], ["generate_platform_package", "publish"], [], False, links)
        if platform_package is None or platform_package.status != "generated":
            return self._payload("generate_platform_package", ["generate_platform_package"], ["publish"], [], False, links)
        return self._payload("manual_publish_review", [], ["publish"], ["manual_publish_only"], True, links)

    def topic_next_action(self, db: Session, topic: EditorialTopic) -> dict[str, Any]:
        links = {
            "topic": f"/editorial/topics/{topic.id}",
            "topics": "/editorial/topics",
            "calendar": "/editorial/calendar",
        }
        if topic.status == "pending":
            return self._payload("select_or_reject_topic", ["select_topic", "reject_topic", "needs_more_evidence"], ["generate_brief"], ["human_topic_selection_required"], True, links)
        if topic.status == "needs_more_evidence":
            return self._payload("blocked", [], ["generate_brief"], ["topic_needs_more_evidence"], True, links)
        if topic.status == "rejected":
            return self._payload("blocked", [], ["generate_brief"], ["topic_rejected"], True, links)
        calendar_entry = db.scalars(
            select(EditorialCalendarEntry).where(EditorialCalendarEntry.topic_id == topic.id).order_by(EditorialCalendarEntry.id.desc())
        ).first()
        if topic.status == "selected" and calendar_entry is None:
            return self._payload("schedule_or_start_production", ["schedule_topic", "start_production"], [], [], True, links)
        if topic.status in {"selected", "scheduled"}:
            return self._payload("start_production", ["start_production"], [], [], True, links)
        return self._payload("completed_or_in_production", [], [], [], False, links)

    def _payload(
        self,
        next_action: str,
        allowed_actions: list[str],
        blocked_actions: list[str],
        blocking_reasons: list[str],
        required_reviewer_note: bool,
        related_links: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "next_action": next_action,
            "allowed_actions": allowed_actions,
            "blocked_actions": blocked_actions,
            "blocking_reasons": blocking_reasons,
            "required_reviewer_note": required_reviewer_note,
            "related_links": related_links,
            "manual_publish_only": True,
        }
