from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, BriefScript, EditorialCalendarEntry, EditorialTopic, FinalVideo, PlatformPackage, RenderPackage


class StatusTimelineBuilder:
    def brief_timeline(self, db: Session, brief: BriefScript) -> list[dict[str, Any]]:
        events = [self._state_event("brief_current_status", brief.status, None, brief.title, None)]
        for log in self._brief_logs(db, brief):
            events.append(self._audit_event(log, self._artifact_links(log)))
        return sorted(events, key=lambda item: item["timestamp"] or "")

    def topic_timeline(self, db: Session, topic: EditorialTopic) -> list[dict[str, Any]]:
        events = [self._state_event("topic_current_status", topic.status, None, topic.editor_note, None)]
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "editorial_topic", AuditLog.entity_id == topic.id)
                .order_by(AuditLog.id.asc())
            ).all()
        )
        calendar_entries = list(db.scalars(select(EditorialCalendarEntry).where(EditorialCalendarEntry.topic_id == topic.id)).all())
        for entry in calendar_entries:
            logs.extend(
                db.scalars(
                    select(AuditLog)
                    .where(AuditLog.entity_type == "editorial_calendar_entry", AuditLog.entity_id == entry.id)
                    .order_by(AuditLog.id.asc())
                ).all()
            )
        for log in logs:
            events.append(self._audit_event(log, self._artifact_links(log)))
        return sorted(events, key=lambda item: item["timestamp"] or "")

    def _brief_logs(self, db: Session, brief: BriefScript) -> list[AuditLog]:
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.entity_type == "brief", AuditLog.entity_id == brief.id)
                .order_by(AuditLog.id.asc())
            ).all()
        )
        for model, entity_type in [
            (RenderPackage, "render_package"),
            (FinalVideo, "final_video"),
            (PlatformPackage, "platform_package"),
        ]:
            ids = [item.id for item in db.scalars(select(model).where(model.brief_id == brief.id)).all()]
            if ids:
                logs.extend(
                    db.scalars(
                        select(AuditLog)
                        .where(AuditLog.entity_type == entity_type, AuditLog.entity_id.in_(ids))
                        .order_by(AuditLog.id.asc())
                    ).all()
                )
        topic_id = (brief.metadata_json or {}).get("topic_id")
        if topic_id:
            logs.extend(
                db.scalars(
                    select(AuditLog)
                    .where(AuditLog.entity_type == "editorial_topic", AuditLog.entity_id == topic_id)
                    .order_by(AuditLog.id.asc())
                ).all()
            )
        return logs

    def _audit_event(self, log: AuditLog, artifact_links: dict[str, str]) -> dict[str, Any]:
        return {
            "event_type": log.action,
            "status": log.action,
            "actor": log.actor,
            "note": log.note,
            "timestamp": log.created_at.isoformat() if log.created_at else None,
            "artifact_links": artifact_links,
        }

    def _state_event(self, event_type: str, status: str, actor: str | None, note: str | None, timestamp: str | None) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "status": status,
            "actor": actor,
            "note": note,
            "timestamp": timestamp,
            "artifact_links": {},
        }

    def _artifact_links(self, log: AuditLog) -> dict[str, str]:
        if log.entity_type == "brief":
            return {"brief": f"/briefs/{log.entity_id}", "production_console": f"/editorial/briefs/{log.entity_id}/production-console"}
        if log.entity_type == "render_package":
            return {"render_package": f"/briefs/render-package-record/{log.entity_id}"}
        if log.entity_type == "final_video":
            return {"final_video_record": f"/briefs/final-video-record/{log.entity_id}"}
        if log.entity_type == "platform_package":
            return {"platform_package_record": f"/briefs/platform-package-record/{log.entity_id}"}
        if log.entity_type == "editorial_topic":
            return {"topic": f"/editorial/topics/{log.entity_id}"}
        if log.entity_type == "editorial_calendar_entry":
            return {"calendar": "/editorial/calendar"}
        return {}
