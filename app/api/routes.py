from io import BytesIO
from datetime import date as dt_date, datetime, timedelta, timezone
import hashlib
import csv
import json
import secrets
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.auth.current_user import CurrentUser, get_current_user
from app.core.environment import security_health
from app.core.request_context import get_current_user_context, get_request_id
from app.models import (
    ApprovalRecord,
    ApiToken,
    AuditLog,
    BriefScript,
    Claim,
    ClaimEvidenceLink,
    EvidenceItem,
    EvidencePack,
    EvidenceCandidate,
    EvidenceSource,
    EditorialCalendarEntry,
    EditorialTopic,
    FactCheck,
    FinalVideo,
    Invite,
    PlatformPackage,
    Post,
    RenderPackage,
    SafetyReview,
    Source,
    SourceReviewItem,
    TeamMember,
    UserAccount,
    Workspace,
    VideoAsset,
)
from app.renderers.ffmpeg_renderer import FFMpegRenderer
from app.sources.manual_archive import ManualArchiveAdapter
from app.services.claim_extractor import ClaimExtractor
from app.services.daily_run_index import DailyRunIndexService
from app.services.dedup import DedupService
from app.services.evidence_pack_service import EvidencePackService
from app.services.evidence_link_suggester import EvidenceLinkSuggester
from app.services.editorial_qa_reporter import EditorialQAReporter
from app.services.fact_check_quality_gate import FactCheckQualityGate
from app.services.feed_readiness_validator import FeedReadinessValidator
from app.services.evidence_query_builder import EvidenceQueryBuilder
from app.services.evidence_report_builder import EvidenceReportBuilder
from app.services.platform_package_builder import PlatformPackageBuilder
from app.services.invariant_checker import InvariantChecker
from app.services.next_action_service import NextActionService
from app.services.ops_dashboard import OpsDashboardService
from app.services.permission_service import PermissionService
from app.services.ranker import Ranker
from app.services.render_package_builder import RenderPackageBuilder
from app.services.safety_checker import SafetyChecker
from app.services.script_writer import ScriptWriter
from app.services.source_policy import SourcePolicy
from app.services.tts_policy import TTSPolicy
from app.services.topic_selector import TopicSelector
from app.services.status_timeline_builder import StatusTimelineBuilder
from app.services.visual_planner import VisualPlanner
from app.services.voice_qa import VoiceQA
from app.services.workspace_service import WorkspaceService
from app.sources.manual_url import ManualUrlAdapter
from app.sources.public_archive_json import PublicArchiveJsonAdapter
from app.sources.daily_feed_json import DailyFeedJsonAdapter
from app.sources.remote_feed import RemoteFeedAdapter
from app.sources.registry import SourceAdapterRegistry
from app.evidence.registry import default_registry
from app.external_search.registry import ExternalSearchProviderRegistry
from app.tts.local_stub import LocalStubTTSProvider
from app.tts.openai_provider import OpenAITTSProvider

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


class ManualIngestRequest(BaseModel):
    path: str = Field(default="data/sample_posts.json")


class GenerateBriefRequest(BaseModel):
    limit: int = Field(default=4, ge=2, le=4)
    production_only: bool = False
    post_ids: list[int] | None = None
    topic_metadata: dict[str, Any] | None = None


class ReviewRequest(BaseModel):
    human_approved: bool
    reviewer_name: str | None = None
    reviewer_notes: str | None = None


class ApprovalRequest(BaseModel):
    reviewer_name: str | None = None
    reviewer_note: str | None = None


class BlockRequest(BaseModel):
    reviewer_name: str | None = None
    reviewer_note: str = Field(min_length=1)


class RequestChangesRequest(BaseModel):
    reviewer_name: str | None = None
    reviewer_note: str = Field(min_length=1)


class ManualUrlIngestRequest(BaseModel):
    source_url: str
    short_excerpt: str = Field(min_length=1)
    source_name: str
    archive_url: str | None = None
    media_refs: list = Field(default_factory=list)


class PublicArchiveJsonIngestRequest(BaseModel):
    path: str = Field(default="data/public_archive_sample.json")


class DailyFeedJsonIngestRequest(BaseModel):
    path: str = Field(default="data/feeds/daily_truth_feed.json")


class RemoteFeedIngestRequest(BaseModel):
    config_path: str = Field(default="app/config/remote_source_feeds.yaml")
    run_date: str | None = None


class SourceReviewActionRequest(BaseModel):
    reviewer_name: str | None = None
    reviewer_note: str = Field(min_length=1)


class ManualEvidenceRequest(BaseModel):
    source_name: str
    source_url: str
    archive_url: str | None = None
    publisher_type: str = Field(default="manual")
    reliability_tier: str = Field(default="unknown")
    retrieved_at: str | None = None
    terms_status: str = Field(default="manual_review_required")
    excerpt: str = Field(min_length=1)
    summary: str | None = None
    supports_claim: str = Field(default="unclear")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reviewer_note: str | None = None


class JsonEvidenceRequest(BaseModel):
    path: str = Field(default="data/sample_evidence.json")


class EvidencePackReviewRequest(BaseModel):
    reviewer_name: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)
    review_status: str = Field(default="reviewed")


class EvidenceScoreRequest(BaseModel):
    reliability_score: int = Field(ge=0, le=100)
    reviewer_note: str | None = None


class ClaimEvidenceLinkRequest(BaseModel):
    evidence_item_id: int
    support_type: str = Field(default="supports")
    confidence: str = Field(default="medium")
    note: str | None = None


class TTSGenerateRequest(BaseModel):
    provider: str | None = None
    voice: str = Field(default="neutral_zh")


class VoiceQARequest(BaseModel):
    reviewer_name: str | None = None
    reviewer_note: str | None = None


class EvidenceSearchRequest(BaseModel):
    provider: str = Field(default="controlled_search")
    query: str | None = None


class CandidateReviewRequest(BaseModel):
    reviewer_name: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)
    supports_claim: str = Field(default="contextual")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class EditorialActionRequest(BaseModel):
    reviewer_name: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)


class EditorialCalendarScheduleRequest(BaseModel):
    topic_id: int
    date: dt_date | None = None
    slot_name: str = Field(default="daily_brief", min_length=1)
    target_platforms: list[str] = Field(default_factory=lambda: ["bilibili", "xiaohongshu", "douyin", "youtube_shorts"])
    planned_duration: int = Field(default=60, ge=45, le=90)
    assigned_editor: str | None = None
    publish_window_note: str | None = None
    reviewer_name: str = Field(min_length=1)
    reviewer_note: str = Field(min_length=1)


class RunNextStepRequest(BaseModel):
    reviewer_name: str | None = None
    reviewer_note: str | None = None


class InviteCreateRequest(BaseModel):
    email_or_name: str = Field(min_length=1)
    role: str = Field(default="viewer")


class ApiTokenCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    scopes: list[str] = Field(default_factory=list)


def _workspace_id(current_user: CurrentUser) -> int:
    if current_user.workspace_id is None:
        raise HTTPException(status_code=403, detail="Current workspace is required")
    return current_user.workspace_id


def _workspace_slug(db: Session, current_user: CurrentUser) -> str | None:
    if current_user.workspace_slug:
        return current_user.workspace_slug
    workspace = db.get(Workspace, current_user.workspace_id) if current_user.workspace_id else None
    return workspace.slug if workspace else None


def _same_workspace(item: Any, current_user: CurrentUser) -> bool:
    item_workspace_id = getattr(item, "workspace_id", None)
    return item_workspace_id is None or item_workspace_id == current_user.workspace_id


def _assert_same_workspace(item: Any, current_user: CurrentUser, detail: str = "Resource not found") -> None:
    if not _same_workspace(item, current_user):
        raise HTTPException(status_code=404, detail=detail)


def _audit_payload(log: AuditLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "workspace_id": log.workspace_id,
        "entity_type": log.entity_type,
        "entity_id": log.entity_id,
        "action": log.action,
        "actor": log.actor,
        "request_id": log.request_id,
        "actor_name": log.actor_name,
        "actor_role": log.actor_role,
        "before_state_hash": log.before_state_hash,
        "after_state_hash": log.after_state_hash,
        "immutable": log.immutable,
        "note": log.note,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _post_payload(post: Post) -> dict[str, Any]:
    return {
        "id": post.id,
        "workspace_id": post.workspace_id,
        "post_id": post.post_id,
        "published_at": post.published_at.isoformat(),
        "source_url": post.source_url,
        "short_excerpt": post.short_excerpt,
        "summary": post.summary,
        "topic": post.topic,
        "fact_check_status": post.fact_check_status,
        "source_review_required": post.source_review_required,
        "source_policy": post.source_policy,
        "ranking_score": post.ranking_score,
        "ranking_breakdown": post.ranking_breakdown,
    }


def _source_review_payload(item: SourceReviewItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "adapter_name": item.adapter_name,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "archive_url": item.archive_url,
        "retrieved_at": item.retrieved_at.isoformat(),
        "raw_excerpt": item.raw_excerpt,
        "normalized_summary": item.normalized_summary,
        "media_refs": item.media_refs,
        "terms_status": item.terms_status,
        "human_status": item.human_status,
        "reviewer_name": item.reviewer_name,
        "reviewer_note": item.reviewer_note,
        "rejection_reason": item.rejection_reason,
        "metadata_json": item.metadata_json,
        "warnings": item.metadata_json.get("warnings", []),
    }


def _editorial_topic_payload(topic: EditorialTopic) -> dict[str, Any]:
    return TopicSelector().topic_payload(topic)


def _calendar_entry_payload(entry: EditorialCalendarEntry, topic: EditorialTopic | None = None) -> dict[str, Any]:
    return {
        "id": entry.id,
        "date": entry.date.isoformat(),
        "topic_id": entry.topic_id,
        "topic": None if topic is None else _editorial_topic_payload(topic),
        "slot_name": entry.slot_name,
        "target_platforms": entry.target_platforms,
        "planned_duration": entry.planned_duration,
        "status": entry.status,
        "assigned_editor": entry.assigned_editor,
        "publish_window_note": entry.publish_window_note,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _claim_evidence_pack_payload(db: Session, claim_id: int) -> dict[str, Any] | None:
    pack = db.scalars(select(EvidencePack).where(EvidencePack.claim_id == claim_id).order_by(EvidencePack.id.desc())).first()
    if pack is None:
        return None
    items = list(db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id == claim_id).order_by(EvidenceItem.id.asc())).all())
    return EvidencePackService().pack_payload(pack, items)


def _candidate_payload(candidate: EvidenceCandidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "claim_id": candidate.claim_id,
        "provider_name": candidate.provider_name,
        "title": candidate.title,
        "source_name": candidate.source_name,
        "source_url": candidate.source_url,
        "archive_url": candidate.archive_url,
        "excerpt": candidate.excerpt,
        "publisher_type": candidate.publisher_type,
        "reliability_tier": candidate.reliability_tier,
        "search_query": candidate.search_query,
        "status": candidate.status,
        "reviewer_name": candidate.reviewer_name,
        "reviewer_note": candidate.reviewer_note,
        "metadata_json": candidate.metadata_json,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
    }


def _evidence_item_payload(item: EvidenceItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "workspace_id": item.workspace_id,
        "source_review_item_id": item.source_review_item_id,
        "post_id": item.post_id,
        "claim_id": item.claim_id,
        "evidence_type": item.evidence_type,
        "title": item.title,
        "source_name": item.source_name,
        "source_url": item.source_url,
        "archive_url": item.archive_url,
        "excerpt": item.excerpt,
        "summary": item.summary,
        "retrieved_at": item.retrieved_at.isoformat() if item.retrieved_at else None,
        "reliability_score": item.reliability_score,
        "terms_status": item.terms_status,
        "human_status": item.human_status,
        "created_by": item.created_by,
        "reviewed_by": item.reviewed_by,
        "supports_claim": item.supports_claim,
        "confidence": item.confidence,
        "reviewer_note": item.reviewer_note,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _claim_evidence_link_payload(link: ClaimEvidenceLink) -> dict[str, Any]:
    return {
        "id": link.id,
        "workspace_id": link.workspace_id,
        "claim_id": link.claim_id,
        "evidence_item_id": link.evidence_item_id,
        "support_type": link.support_type,
        "confidence": link.confidence,
        "note": link.note,
        "created_at": link.created_at.isoformat() if link.created_at else None,
        "evidence_item": _evidence_item_payload(link.evidence_item) if link.evidence_item else None,
    }


def _tts_dir(brief_id: int) -> Path:
    return Path("exports/tts") / f"brief_{brief_id}"


def _tts_status_payload(brief_id: int) -> dict[str, Any]:
    output_dir = _tts_dir(brief_id)
    metadata_path = output_dir / "tts_metadata.json"
    qa_path = output_dir / "voice_qa_report.json"
    audio_path = output_dir / "audio.wav"
    if not audio_path.exists():
        audio_path = output_dir / "audio.mp3"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else None
    qa = json.loads(qa_path.read_text(encoding="utf-8")) if qa_path.exists() else None
    return {
        "brief_id": brief_id,
        "status": "ready" if metadata and qa and qa.get("status") != "blocked" else "blocked" if qa and qa.get("status") == "blocked" else "missing",
        "output_dir": str(output_dir),
        "audio_path": str(audio_path) if audio_path.exists() else None,
        "metadata_path": str(metadata_path) if metadata_path.exists() else None,
        "voice_qa_path": str(qa_path) if qa_path.exists() else None,
        "metadata": metadata,
        "voice_qa": qa,
    }


def _evidence_items_for_claim(db: Session, claim_id: int) -> list[EvidenceItem]:
    return EvidencePackService().evidence_items_for_claim(db, claim_id)


def _attach_normalized_evidence(db: Session, claim: Claim, normalized: dict[str, Any]) -> dict[str, Any]:
    source_payload = normalized["source"]
    if source_payload.get("terms_status") == "blocked":
        raise HTTPException(status_code=409, detail="Blocked evidence source cannot be attached")
    evidence_source = EvidenceSource(**source_payload)
    db.add(evidence_source)
    db.flush()
    item = EvidenceItem(
        workspace_id=claim.post.workspace_id,
        claim_id=claim.id,
        post_id=claim.post_id,
        evidence_source_id=evidence_source.id,
        evidence_type=source_payload.get("publisher_type") or "manual_note",
        title=source_payload.get("source_name"),
        source_name=source_payload.get("source_name"),
        source_url=source_payload.get("source_url"),
        archive_url=source_payload.get("archive_url"),
        retrieved_at=source_payload.get("retrieved_at"),
        reliability_score=80 if source_payload.get("reliability_tier") == "high" else 60 if source_payload.get("reliability_tier") == "medium" else 50,
        terms_status=source_payload.get("terms_status", "manual_review_required"),
        human_status="approved",
        **normalized["item"],
    )
    db.add(item)
    db.flush()
    pack = EvidencePackService().build_or_update_pack(db, claim)
    evidence_items = _evidence_items_for_claim(db, claim.id)
    latest_check = db.scalars(select(FactCheck).where(FactCheck.claim_id == claim.id).order_by(FactCheck.id.desc())).first()
    fact_payload = EvidencePackService().fact_check_payload(claim, pack, evidence_items)
    if latest_check is None:
        latest_check = FactCheck(claim_id=claim.id, **fact_payload)
        db.add(latest_check)
    else:
        latest_check.verdict = fact_payload["verdict"]
        latest_check.rationale = fact_payload["rationale"]
        latest_check.sources = fact_payload["sources"]
        latest_check.provider = fact_payload["provider"]
    return EvidencePackService().pack_payload(pack, evidence_items)


def _ensure_post_evidence_for_claim(db: Session, post: Post, claim: Claim, current_user: CurrentUser) -> EvidenceItem:
    source_review_item_id = (post.source_policy or {}).get("source_review_item_id")
    existing = db.scalar(
        select(EvidenceItem).where(
            EvidenceItem.workspace_id == _workspace_id(current_user),
            EvidenceItem.post_id == post.id,
            EvidenceItem.source_review_item_id == source_review_item_id,
        )
    )
    if existing is None:
        evidence_source = EvidenceSource(
            source_name=post.source.name if post.source else "post source",
            source_url=post.source_url,
            archive_url=post.source_url,
            publisher_type="public_archive" if source_review_item_id else "sample",
            reliability_tier="medium",
            retrieved_at=post.published_at,
            terms_status=(post.source_policy or {}).get("terms_status", "allowed"),
            metadata_json={
                "post_id": post.id,
                "source_review_item_id": source_review_item_id,
                "sample_data": (post.source_policy or {}).get("evidence", {}).get("sample_data") is True,
            },
        )
        db.add(evidence_source)
        db.flush()
        existing = EvidenceItem(
            workspace_id=_workspace_id(current_user),
            source_review_item_id=source_review_item_id,
            post_id=post.id,
            evidence_source_id=evidence_source.id,
            evidence_type="public_archive" if source_review_item_id else "original_link",
            title=f"Source evidence for post {post.post_id}",
            source_name=evidence_source.source_name,
            source_url=post.source_url,
            archive_url=post.source_url,
            excerpt=post.short_excerpt[:500],
            summary=post.summary[:1000],
            retrieved_at=post.published_at,
            reliability_score=70 if source_review_item_id else 55,
            terms_status=evidence_source.terms_status,
            human_status="approved",
            created_by=current_user.username,
            reviewed_by=current_user.username,
            supports_claim="unclear",
            confidence=0.5,
        )
        db.add(existing)
        db.flush()
        _audit(db, "evidence_item", existing.id, "evidence_created_from_post_source", current_user, f"post:{post.id}")
    support_type = "contextualizes" if claim.claim_type == "opinion" else "supports"
    link = db.scalar(
        select(ClaimEvidenceLink).where(
            ClaimEvidenceLink.claim_id == claim.id,
            ClaimEvidenceLink.evidence_item_id == existing.id,
        )
    )
    if link is None:
        link = ClaimEvidenceLink(
            workspace_id=_workspace_id(current_user),
            claim_id=claim.id,
            evidence_item_id=existing.id,
            support_type=support_type,
            confidence="medium",
            note="Auto-linked to reviewed/source-safe post evidence for quality gate coverage.",
        )
        db.add(link)
        existing.claim_id = claim.id
        existing.supports_claim = "supports" if support_type == "supports" else "contextual"
        existing.confidence = 0.65
        db.flush()
        _audit(db, "claim_evidence_link", link.id, "claim_evidence_link_auto_created", current_user, f"claim:{claim.id}")
    return existing


def _refresh_brief_evidence_state(db: Session, brief: BriefScript) -> dict[str, Any]:
    claim_ids = [claim["id"] for claim in brief.claims]
    claims = list(db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()) if claim_ids else []
    service = EvidencePackService()
    for claim in claims:
        pack = service.build_or_update_pack(db, claim)
        evidence_items = _evidence_items_for_claim(db, claim.id)
        fact_payload = service.fact_check_payload(claim, pack, evidence_items)
        latest_check = db.scalars(select(FactCheck).where(FactCheck.claim_id == claim.id).order_by(FactCheck.id.desc())).first()
        if latest_check is None:
            latest_check = FactCheck(claim_id=claim.id, **fact_payload)
            db.add(latest_check)
            db.flush()
        else:
            latest_check.verdict = fact_payload["verdict"]
            latest_check.rationale = fact_payload["rationale"]
            latest_check.sources = fact_payload["sources"]
            latest_check.provider = fact_payload["provider"]
    db.flush()
    fact_checks = list(
        db.scalars(select(FactCheck).where(FactCheck.claim_id.in_(claim_ids)).order_by(FactCheck.id.asc())).all()
    ) if claim_ids else []
    latest_by_claim: dict[int, FactCheck] = {}
    for check in fact_checks:
        latest_by_claim[check.claim_id] = check
    brief.fact_checks = [
        {
            "id": check.id,
            "claim_id": check.claim_id,
            "claim_type": check.claim.claim_type,
            "verdict": check.verdict,
            "rationale": check.rationale,
            "sources": check.sources,
            "provider": check.provider,
        }
        for check in latest_by_claim.values()
    ]
    payload = _brief_payload(brief, db)
    safety_payload = SafetyChecker().review(
        ranked_posts=payload["ranked_posts"],
        script=payload["script"],
        visual_plan=payload["visual_plan"],
        fact_checks=brief.fact_checks,
        claims=payload["claims"],
        evidence_packs=payload["evidence_packs"],
    )
    safety = db.scalars(
        select(SafetyReview).where(SafetyReview.brief_script_id == brief.id).order_by(SafetyReview.id.desc())
    ).first()
    if safety is not None:
        safety.status = safety_payload["overall_status"]
        safety.checks = safety_payload
        safety.notes = safety_payload["blocking_reasons"] + safety_payload["warnings"]
    if brief.status != "approved":
        brief.status = "blocked" if safety_payload["overall_status"] == "blocked" else "needs_review"
    return _brief_payload(brief, db)


def _state_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _entity_workspace_id(db: Session, entity_type: str, entity_id: int) -> int | None:
    model_by_entity = {
        "source_review_item": SourceReviewItem,
        "post": Post,
        "brief": BriefScript,
        "evidence_item": EvidenceItem,
        "claim_evidence_link": ClaimEvidenceLink,
        "editorial_topic": EditorialTopic,
        "editorial_calendar_entry": EditorialCalendarEntry,
        "render_package": RenderPackage,
        "final_video": FinalVideo,
        "platform_package": PlatformPackage,
        "invite": Invite,
        "api_token": ApiToken,
        "admin": Workspace,
    }
    model = model_by_entity.get(entity_type)
    item = db.get(model, entity_id) if model is not None and entity_id else None
    return getattr(item, "workspace_id", None) or (item.id if entity_type == "admin" and item else None)


def _audit(db: Session, entity_type: str, entity_id: int, action: str, actor: str | CurrentUser | None, note: str | None) -> None:
    context_user = get_current_user_context()
    explicit_user = actor if hasattr(actor, "username") and hasattr(actor, "role") else None
    actor_name = (
        explicit_user.username
        if explicit_user is not None
        else actor
        if isinstance(actor, str)
        else context_user.username
        if context_user
        else "system"
    )
    actor_role = explicit_user.role if explicit_user is not None else context_user.role if context_user and actor_name == context_user.username else None
    workspace_id = (
        explicit_user.workspace_id
        if explicit_user is not None
        else context_user.workspace_id
        if context_user
        else _entity_workspace_id(db, entity_type, entity_id)
    )
    request_id = explicit_user.request_id if explicit_user is not None else context_user.request_id if context_user else get_request_id()
    after_hash = _state_hash(
        {
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor": actor_name,
            "actor_role": actor_role,
            "note": note,
            "request_id": request_id,
        }
    )
    db.add(
        AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            workspace_id=workspace_id,
            action=action,
            actor=actor_name,
            actor_name=actor_name,
            actor_role=actor_role,
            request_id=request_id,
            before_state_hash=None,
            after_state_hash=after_hash,
            immutable=True,
            note=note,
        )
    )


def _record_approval(
    db: Session,
    entity_type: str,
    entity_id: int,
    action: str,
    user: CurrentUser,
    decision: str,
    note: str | None,
) -> None:
    PermissionService().record_approval(
        db,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        user=user,
        decision=decision,
        note=note,
    )


def _user_payload(user: CurrentUser) -> dict[str, Any]:
    return {
        "user_id": user.user_id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "workspace_id": user.workspace_id,
        "workspace_slug": user.workspace_slug,
        "auth_mode": user.auth_mode,
        "is_authenticated": user.is_authenticated,
        "is_stub": user.is_stub,
        "request_id": user.request_id,
        "is_active": user.is_active,
    }


def _approval_records_payload(db: Session, entity_type: str, entity_id: int) -> list[dict[str, Any]]:
    records = list(
        db.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.entity_type == entity_type, ApprovalRecord.entity_id == entity_id)
            .order_by(ApprovalRecord.id.asc())
        ).all()
    )
    return [
        {
            "id": record.id,
            "workspace_id": record.workspace_id,
            "entity_type": record.entity_type,
            "entity_id": record.entity_id,
            "action": record.action,
            "actor": record.actor,
            "actor_role": record.actor_role,
            "decision": record.decision,
            "request_id": record.request_id,
            "note": record.note,
            "created_at": record.created_at.isoformat() if record.created_at else None,
        }
        for record in records
    ]


def _source_registry() -> SourceAdapterRegistry:
    registry = SourceAdapterRegistry()
    registry.register_adapter("manual_url", ManualUrlAdapter())
    registry.register_adapter("public_archive_json", PublicArchiveJsonAdapter)
    return registry


def _brief_payload(brief: BriefScript, db: Session) -> dict[str, Any]:
    safety = db.scalars(
        select(SafetyReview)
        .where(SafetyReview.brief_script_id == brief.id)
        .order_by(SafetyReview.id.desc())
    ).first()
    video_asset = db.scalars(
        select(VideoAsset).where(VideoAsset.brief_script_id == brief.id).order_by(VideoAsset.id.desc())
    ).first()
    render_package = db.scalars(
        select(RenderPackage).where(RenderPackage.brief_id == brief.id).order_by(RenderPackage.id.desc())
    ).first()
    final_video = db.scalars(
        select(FinalVideo).where(FinalVideo.brief_id == brief.id).order_by(FinalVideo.id.desc())
    ).first()
    platform_package = db.scalars(
        select(PlatformPackage).where(PlatformPackage.brief_id == brief.id).order_by(PlatformPackage.id.desc())
    ).first()
    gate_report = FactCheckQualityGate().evaluate(db, brief)
    return {
        "id": brief.id,
        "status": brief.status,
        "title": brief.title,
        "metadata_json": brief.metadata_json,
        "ranked_posts": brief.ranked_posts,
        "claims": brief.claims,
        "evidence_packs": [
            pack
            for pack in (_claim_evidence_pack_payload(db, claim.get("id")) for claim in brief.claims)
            if pack is not None
        ],
        "fact_checks": brief.fact_checks,
        "script": {
            "text": brief.script_text,
            "subtitle_draft": brief.subtitle_draft,
            "sources": brief.sources,
        },
        "visual_plan": brief.visual_plan,
        "safety_review": None
        if safety is None
        else {
            "id": safety.id,
            "status": safety.status,
            "overall_status": safety.status,
            "checks": safety.checks,
            "notes": safety.notes,
            "blocking_reasons": safety.checks.get("blocking_reasons", []),
            "warnings": safety.checks.get("warnings", []),
            "rules": safety.checks.get("rules", []),
            "human_review_required": safety.human_review_required,
            "human_approved": safety.human_approved,
            "reviewer_name": safety.reviewer_name,
            "reviewer_notes": safety.reviewer_notes,
        },
        "video_asset": None
        if video_asset is None
        else {
            "id": video_asset.id,
            "status": video_asset.status,
            "export_allowed": video_asset.export_allowed,
            "asset_json": video_asset.asset_json,
        },
        "render_package": None
        if render_package is None
        else {
            "id": render_package.id,
            "brief_id": render_package.brief_id,
            "status": render_package.status,
            "output_dir": render_package.output_dir,
            "manifest_path": render_package.manifest_path,
            "error_message": render_package.error_message,
        },
        "final_video": None
        if final_video is None
        else {
            "id": final_video.id,
            "brief_id": final_video.brief_id,
            "render_package_id": final_video.render_package_id,
            "status": final_video.status,
            "video_path": final_video.video_path,
            "report_path": final_video.report_path,
            "tts_provider": final_video.tts_provider,
            "duration_seconds": final_video.duration_seconds,
            "error_message": final_video.error_message,
        },
        "platform_package": None
        if platform_package is None
        else {
            "id": platform_package.id,
            "brief_id": platform_package.brief_id,
            "final_video_id": platform_package.final_video_id,
            "platform": platform_package.platform,
            "status": platform_package.status,
            "output_dir": platform_package.output_dir,
            "package_path": platform_package.package_path,
            "qa_report_path": platform_package.qa_report_path,
            "error_message": platform_package.error_message,
        },
        "fact_check_quality_gate": gate_report,
    }


def _build_export_payload(brief_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "brief_id": brief_payload["id"],
        "status": brief_payload["status"],
        "title_options": [
            brief_payload["title"],
            brief_payload["visual_plan"].get("cover_title", brief_payload["title"]),
            "公开信息整理：特朗普发帖重点速读",
        ],
        "script": brief_payload["script"],
        "visual_plan": brief_payload["visual_plan"],
        "video_asset": brief_payload["video_asset"],
        "sources": brief_payload["script"]["sources"],
        "fact_checks": brief_payload["fact_checks"],
        "safety_review": brief_payload["safety_review"],
        "ranked_posts": brief_payload["ranked_posts"],
        "claims": brief_payload["claims"],
        "export_notes": {
            "mp4_rendered": False,
            "automatic_publishing": False,
            "ai_visuals_label_required": "AI 生成示意图",
        },
    }


def _trace_manifest(db: Session, brief: BriefScript, package_type: str, generated_by: CurrentUser) -> dict[str, Any]:
    claim_ids = [claim.get("id") for claim in brief.claims if claim.get("id")]
    evidence_ids = []
    claim_evidence_link_ids = []
    if claim_ids:
        evidence_ids = [
            item.id
            for item in db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id.in_(claim_ids))).all()
        ]
        links = list(db.scalars(select(ClaimEvidenceLink).where(ClaimEvidenceLink.claim_id.in_(claim_ids))).all())
        evidence_ids = sorted(set(evidence_ids + [link.evidence_item_id for link in links]))
        claim_evidence_link_ids = [link.id for link in links]
    safety = db.scalars(select(SafetyReview).where(SafetyReview.brief_script_id == brief.id).order_by(SafetyReview.id.desc())).first()
    approval_records = list(
        db.scalars(
            select(ApprovalRecord)
            .where(ApprovalRecord.entity_type == "brief", ApprovalRecord.entity_id == brief.id)
            .order_by(ApprovalRecord.id.asc())
        ).all()
    )
    source_review_item_ids = sorted(
        {
            post.get("source_policy", {}).get("source_review_item_id")
            for post in brief.ranked_posts
            if post.get("source_policy", {}).get("source_review_item_id") is not None
        }
    )
    return {
        "package_type": package_type,
        "workspace_id": brief.workspace_id,
        "workspace_slug": _workspace_slug(db, generated_by),
        "brief_id": brief.id,
        "source_review_item_ids": source_review_item_ids,
        "post_ids": [post.get("id") for post in brief.ranked_posts if post.get("id")],
        "evidence_ids": evidence_ids,
        "evidence_item_ids": evidence_ids,
        "claim_evidence_link_ids": claim_evidence_link_ids,
        "approval_record_ids": [record.id for record in approval_records],
        "safety_review_id": safety.id if safety else None,
        "producer": generated_by.username if generated_by.role in {"producer", "admin"} else None,
        "reviewer": next((record.actor for record in reversed(approval_records) if record.action == "brief_approved"), None),
        "generated_by": generated_by.username,
        "generated_by_role": generated_by.role,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "request_id": get_request_id(),
        "compliance_status": "blocked" if safety and safety.status == "blocked" else "ready",
        "fact_check_quality_gate_status": FactCheckQualityGate().evaluate(db, brief)["status"],
        "manual_publish_only": True,
    }


def _write_trace_manifest(output_dir: Path, trace: dict[str, Any]) -> Path:
    path = output_dir / "trace_manifest.json"
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _export_readme(brief_payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Daily Truth Brief Export Package",
            "",
            "This package contains review-approved material assets only. It does not contain rendered MP4 output and must not be automatically published.",
            "",
            "Required boundaries:",
            "- Keep source links with the published description.",
            "- Label AI illustrative visuals as `AI 生成示意图`.",
            "- Do not create fake Truth Social screenshots, voice impersonation, or lip-sync video.",
            "- Use this package for neutral public-information analysis, not political mobilization.",
            "",
            f"Brief ID: {brief_payload['id']}",
            f"Status at export: {brief_payload['status']}",
        ]
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/security")
def health_security() -> dict[str, Any]:
    return security_health()


@router.get("/health/truth-monitor")
async def health_truth_monitor() -> dict[str, Any]:
    import os
    import sqlite3

    import redis.asyncio as redis

    from app.jobs import truth_scheduler
    from storage import db as truth_storage

    redis_status = "error"
    client = redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
        decode_responses=True,
    )
    try:
        await client.ping()
        redis_status = "ok"
    except Exception:  # noqa: BLE001
        redis_status = "error"
    finally:
        await client.aclose()

    db_status = "error"
    total_count = 0
    injected_count = 0
    try:
        if truth_storage.DB_PATH.exists():
            connection = sqlite3.connect(truth_storage.DB_PATH)
            try:
                total_count = int(connection.execute("SELECT COUNT(*) FROM truth_posts").fetchone()[0])
                injected_count = int(connection.execute("SELECT COUNT(*) FROM truth_posts WHERE injected = 1").fetchone()[0])
                db_status = "ok"
            finally:
                connection.close()
    except Exception:  # noqa: BLE001
        db_status = "error"

    active_scheduler = truth_scheduler.scheduler
    scheduler_running = bool(
        active_scheduler is not None
        and active_scheduler.running
        and active_scheduler.get_job("truth_monitor") is not None
    )
    return {
        "redis": redis_status,
        "db_table": db_status,
        "last_fetched_count": total_count,
        "last_injected_count": injected_count,
        "scheduler_running": scheduler_running,
    }


def _daily_run_dir(run_date: str) -> Path:
    resolved = dt_date.today().isoformat() if run_date == "today" else run_date
    return Path("exports/daily_runs") / resolved


def _daily_run_report_payload(run_date: str) -> dict[str, Any] | None:
    path = _daily_run_dir(run_date) / "daily_run_report.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("/daily-runs/{run_date}/summary")
def daily_run_summary(
    run_date: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    report = _daily_run_report_payload(run_date)
    if report is None:
        raise HTTPException(status_code=404, detail="Daily run report not found")
    return {"date": report.get("date", run_date), "report": report, "manual_publish_only": True}


@router.get("/daily-runs")
def daily_runs_index(
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    runs = DailyRunIndexService().load_runs(limit=max(1, min(limit, 50)))
    return {
        "runs": runs,
        "latest": runs[0] if runs else None,
        "manual_publish_only": True,
        "platform_publish_api_called": False,
        "truth_social_direct_scraper_used": False,
    }


@router.get("/daily-runs/latest")
def daily_run_latest(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    latest = DailyRunIndexService().latest()
    if latest is None:
        raise HTTPException(status_code=404, detail="Daily run report not found")
    return {
        "latest": latest,
        "manual_publish_only": True,
        "platform_publish_api_called": False,
        "truth_social_direct_scraper_used": False,
    }


@router.get("/daily-runs/{run_date}/manual-actions")
def daily_run_manual_actions(
    run_date: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    workspace_id = _workspace_id(current_user)
    report = _daily_run_report_payload(run_date) or {}
    sources = list(
        db.scalars(
            select(SourceReviewItem)
            .where(SourceReviewItem.workspace_id == workspace_id, SourceReviewItem.human_status == "pending")
            .order_by(SourceReviewItem.id.desc())
        ).all()
    )
    evidence = list(
        db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.workspace_id == workspace_id, EvidenceItem.human_status == "pending")
            .order_by(EvidenceItem.id.desc())
        ).all()
    )
    briefs = list(
        db.scalars(
            select(BriefScript)
            .where(BriefScript.workspace_id == workspace_id, BriefScript.status.in_(["needs_review", "pending_human_review"]))
            .order_by(BriefScript.id.desc())
        ).all()
    )
    claims_needing_evidence = []
    for brief in briefs:
        gate = FactCheckQualityGate().evaluate(db, brief)
        claims_needing_evidence.extend(gate.get("missing_evidence_claims") or [])
        claims_needing_evidence.extend(gate.get("weak_evidence_claims") or [])
    return {
        "date": report.get("date", dt_date.today().isoformat() if run_date == "today" else run_date),
        "sources_needing_review": [_source_review_payload(item) for item in sources],
        "evidence_needing_review": [_evidence_item_payload(item) for item in evidence],
        "claims_needing_evidence": claims_needing_evidence,
        "briefs_needing_approval": [_brief_payload(brief, db) for brief in briefs],
        "final_packages_needing_human_publish_decision": report.get("final_packages_needing_human_publish_decision", []),
        "manual_actions_required": report.get("manual_actions_required", []),
        "manual_publish_only": True,
    }


@router.get("/daily-runs/{run_date}/page", response_class=HTMLResponse)
def daily_run_page(
    request: Request,
    run_date: str,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> HTMLResponse:
    report = _daily_run_report_payload(run_date)
    actions = daily_run_manual_actions(run_date, db, current_user)
    return templates.TemplateResponse(
        request,
        "daily_run.html",
        {
            "run_date": actions["date"],
            "report": report,
            "actions": actions,
            "manual_publish_only": True,
            "current_user": _user_payload(current_user),
        },
    )


@router.get("/workspaces/current")
def get_current_workspace(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    workspace = WorkspaceService().get_workspace(db, current_user.workspace_id)
    return {"workspace": WorkspaceService().workspace_payload(workspace), "current_user": _user_payload(current_user)}


@router.get("/workspaces/current/team")
def get_current_workspace_team(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "workspace_team_read")
    members = list(
        db.scalars(
            select(TeamMember)
            .where(TeamMember.workspace_id == _workspace_id(current_user))
            .order_by(TeamMember.id.asc())
        ).all()
    )
    users = {user.id: user for user in db.scalars(select(UserAccount).where(UserAccount.id.in_([m.user_account_id for m in members]))).all()} if members else {}
    return {
        "workspace_id": current_user.workspace_id,
        "members": [
            {
                "id": member.id,
                "user_account_id": member.user_account_id,
                "username": users[member.user_account_id].username if member.user_account_id in users else None,
                "role": member.role,
                "status": member.status,
                "created_at": member.created_at.isoformat() if member.created_at else None,
            }
            for member in members
        ],
    }


@router.post("/workspaces/current/invites")
def create_workspace_invite(
    request: InviteCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "workspace_invite_create")
    role = request.role.strip().lower()
    if role not in {"viewer", "editor", "producer", "reviewer", "admin"}:
        raise HTTPException(status_code=400, detail="Invalid invite role")
    invite, token = WorkspaceService().create_invite(
        db,
        workspace_id=_workspace_id(current_user),
        email_or_name=request.email_or_name,
        role=role,
        created_by=current_user.username,
    )
    _audit(db, "invite", invite.id, "workspace_invite_created", current_user, f"role={role}")
    db.commit()
    db.refresh(invite)
    return {
        "id": invite.id,
        "workspace_id": invite.workspace_id,
        "email_or_name": invite.email_or_name,
        "role": invite.role,
        "status": invite.status,
        "token_preview": token[:8],
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
    }


@router.post("/workspaces/current/invites/{invite_id}/revoke")
def revoke_workspace_invite(
    invite_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "workspace_invite_revoke", entity_type="invite", entity_id=invite_id)
    invite = db.get(Invite, invite_id)
    if invite is None or invite.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=404, detail="Invite not found")
    invite.status = "revoked"
    _audit(db, "invite", invite.id, "workspace_invite_revoked", current_user, None)
    db.commit()
    return {"id": invite.id, "workspace_id": invite.workspace_id, "status": invite.status}


@router.get("/workspaces/current/audit-summary")
def workspace_audit_summary(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "workspace_audit_summary")
    logs = list(db.scalars(select(AuditLog).where(AuditLog.workspace_id == _workspace_id(current_user))).all())
    by_action: dict[str, int] = {}
    for log in logs:
        by_action[log.action] = by_action.get(log.action, 0) + 1
    return {"workspace_id": current_user.workspace_id, "audit_count": len(logs), "by_action": by_action}


@router.post("/workspaces/current/api-tokens")
def create_workspace_api_token(
    request: ApiTokenCreateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "api_token_create")
    token_record, token = WorkspaceService().create_api_token(
        db,
        workspace_id=_workspace_id(current_user),
        name=request.name,
        scopes=request.scopes,
        created_by=current_user.username,
    )
    _audit(db, "api_token", token_record.id, "api_token_created", current_user, request.name)
    db.commit()
    db.refresh(token_record)
    return {
        "id": token_record.id,
        "workspace_id": token_record.workspace_id,
        "name": token_record.name,
        "scopes": token_record.scopes,
        "status": token_record.status,
        "token_preview": token[:8],
        "token_auth_active": False,
    }


@router.post("/workspaces/current/api-tokens/{token_id}/revoke")
def revoke_workspace_api_token(
    token_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "api_token_revoke", entity_type="api_token", entity_id=token_id)
    token = db.get(ApiToken, token_id)
    if token is None or token.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=404, detail="API token not found")
    token.status = "revoked"
    token.revoked_at = datetime.now(timezone.utc)
    _audit(db, "api_token", token.id, "api_token_revoked", current_user, token.name)
    db.commit()
    return {"id": token.id, "workspace_id": token.workspace_id, "status": token.status}


@router.get("/admin/permissions/matrix")
def admin_permissions_matrix(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "permissions_matrix_export")
    path = PermissionService().write_matrix_doc()
    _audit(db, "admin", 0, "permissions_matrix_exported", current_user, str(path))
    db.commit()
    return {"matrix": PermissionService().matrix(), "docs_path": str(path)}


@router.get("/admin/audit/{audit_id}")
def admin_get_audit(audit_id: int, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_export_audit(current_user), "audit_read", entity_type="audit_log", entity_id=audit_id)
    log = db.get(AuditLog, audit_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Audit log not found")
    _assert_same_workspace(log, current_user, "Audit log not found")
    return _audit_payload(log)


@router.get("/admin/invariants")
def admin_invariants(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, current_user.role == "admin", "invariants_check")
    result = InvariantChecker().check(db)
    _audit(db, "admin", 0, "invariants_checked", current_user, result["overall_status"])
    db.commit()
    return result


@router.get("/ops/summary")
def ops_summary(db: Session = Depends(get_db)) -> dict[str, int]:
    return OpsDashboardService().summary(db)


@router.get("/ops/queue-status")
def ops_queue_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    return OpsDashboardService().queue_status(db)


@router.get("/ops/blocking-reasons")
def ops_blocking_reasons(db: Session = Depends(get_db)) -> dict[str, Any]:
    return OpsDashboardService().blocking_reasons(db)


@router.get("/ops/daily-runs")
def ops_daily_runs() -> dict[str, Any]:
    return {"runs": OpsDashboardService().daily_runs()}


@router.get("/ops/daily-runs/{run_date}")
def ops_daily_run(run_date: str) -> dict[str, Any]:
    report_path = Path("exports/production_runs") / run_date / "run_report.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Daily run report not found")
    return json.loads(report_path.read_text(encoding="utf-8"))


@router.get("/ops/audit-log/export")
def ops_audit_log_export(
    format: str = "json",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
):
    PermissionService().assert_allowed(db, current_user, PermissionService().can_export_audit(current_user), "audit_export")
    logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.workspace_id == _workspace_id(current_user))
            .order_by(AuditLog.id.asc())
        ).all()
    )
    payload = [_audit_payload(log) for log in logs]
    if format == "json":
        return {"audit_logs": payload}
    if format == "csv":
        buffer = BytesIO()
        text = "id,entity_type,entity_id,action,actor,note,created_at\n"
        text_buffer = []
        output = BytesIO()
        import io

        string_buffer = io.StringIO()
        writer = csv.DictWriter(
            string_buffer,
            fieldnames=[
                "id",
                "workspace_id",
                "entity_type",
                "entity_id",
                "action",
                "actor",
                "request_id",
                "actor_name",
                "actor_role",
                "before_state_hash",
                "after_state_hash",
                "immutable",
                "note",
                "created_at",
            ],
        )
        writer.writeheader()
        writer.writerows(payload)
        output.write(string_buffer.getvalue().encode("utf-8"))
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="daily_truth_audit_log.csv"'},
        )
    raise HTTPException(status_code=400, detail="format must be json or csv")


@router.get("/ops/dashboard", response_class=HTMLResponse)
def ops_dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    service = OpsDashboardService()
    return templates.TemplateResponse(
        request,
        "ops_dashboard.html",
        {
            "summary": service.summary(db),
            "queues": service.queue_status(db),
            "blocking": service.blocking_reasons(db),
            "daily_runs": service.daily_runs(),
        },
    )


def _editorial_console_payload(db: Session, current_user: CurrentUser) -> dict[str, Any]:
    ops = OpsDashboardService()
    queues = ops.queue_status(db)
    briefs = list(db.scalars(select(BriefScript).order_by(BriefScript.id.desc())).all())
    next_actions = {}
    for brief in briefs[:25]:
        next_actions[str(brief.id)] = NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))
    return {
        "summary": ops.summary(db),
        "queues": queues,
        "blocking": ops.blocking_reasons(db),
        "brief_next_actions": next_actions,
        "manual_publish_only": True,
        "current_user": _user_payload(current_user),
    }


@router.get("/editorial/console/summary")
def editorial_console_summary(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    return _editorial_console_payload(db, current_user)


@router.get("/editorial/console", response_class=HTMLResponse)
def editorial_console(request: Request, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "editorial_console.html",
        _editorial_console_payload(db, current_user),
    )


@router.get("/editorial/briefs/{brief_id}/next-action")
def get_brief_next_action(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))


@router.get("/editorial/briefs/{brief_id}/timeline")
def get_brief_timeline(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return {"brief_id": brief.id, "timeline": StatusTimelineBuilder().brief_timeline(db, brief)}


@router.get("/editorial/topics/{topic_id}/timeline")
def get_topic_timeline(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    _assert_same_workspace(topic, current_user, "Editorial topic not found")
    return {"topic_id": topic.id, "timeline": StatusTimelineBuilder().topic_timeline(db, topic)}


@router.get("/editorial/briefs/{brief_id}/production-console", response_class=HTMLResponse)
def brief_production_console(
    request: Request,
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> HTMLResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    next_action = NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))
    timeline = StatusTimelineBuilder().brief_timeline(db, brief)
    source_status = "promoted" if all((post.get("source_policy") or {}).get("human_source_review_status") == "promoted" for post in brief.ranked_posts) else "sample_or_unpromoted"
    steps = [
        {"name": "source_review", "status": source_status},
        {"name": "topic_selected", "status": "linked" if brief.metadata_json.get("topic_id") else "not_linked"},
        {"name": "evidence_pack", "status": "ready" if payload["evidence_packs"] else "missing"},
        {"name": "safety_review", "status": payload["safety_review"]["overall_status"] if payload["safety_review"] else "missing"},
        {"name": "human_approval", "status": brief.status},
        {"name": "render_package", "status": payload["render_package"]["status"] if payload["render_package"] else "missing"},
        {"name": "tts", "status": _tts_status_payload(brief.id)["status"]},
        {"name": "voice_qa", "status": (_tts_status_payload(brief.id).get("voice_qa") or {}).get("status", "missing")},
        {"name": "final_video", "status": payload["final_video"]["status"] if payload["final_video"] else "missing"},
        {"name": "platform_package", "status": payload["platform_package"]["status"] if payload["platform_package"] else "missing"},
    ]
    return templates.TemplateResponse(
        request,
        "production_console.html",
        {
            "brief": payload,
            "steps": steps,
            "next_action": next_action,
            "timeline": timeline,
            "manual_publish_only": True,
            "current_user": _user_payload(current_user),
            "permission_status": {
                "can_render": PermissionService().can_render(current_user),
                "can_generate_tts": PermissionService().can_generate_tts(current_user),
                "can_generate_platform_package": PermissionService().can_generate_platform_package(current_user),
                "can_approve_brief": PermissionService().can_approve_brief(current_user),
            },
            "approval_history": _approval_records_payload(db, "brief", brief.id),
        },
    )


@router.post("/editorial/topics/generate")
def generate_editorial_topics(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_select_topic(current_user), "topic_generate")
    result = TopicSelector().generate_topics(db, workspace_id=_workspace_id(current_user))
    for topic in result["topics"]:
        _audit(db, "editorial_topic", topic.id, "topic_generated", None, "generated from promoted posts; manual selection required")
    db.commit()
    return {
        "created_count": len(result["topics"]),
        "topics": [_editorial_topic_payload(topic) for topic in result["topics"]],
        "report": result["report"],
        "report_path": result["report_path"],
    }


@router.get("/editorial/topics")
def list_editorial_topics(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    topics = list(
        db.scalars(
            select(EditorialTopic)
            .where(EditorialTopic.workspace_id == _workspace_id(current_user))
            .order_by(EditorialTopic.id.desc())
        ).all()
    )
    return {"topics": [_editorial_topic_payload(topic) for topic in topics]}


@router.get("/editorial/topics/{topic_id}")
def get_editorial_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    _assert_same_workspace(topic, current_user, "Editorial topic not found")
    _assert_same_workspace(topic, current_user, "Editorial topic not found")
    _assert_same_workspace(topic, current_user, "Editorial topic not found")
    return _editorial_topic_payload(topic)


@router.post("/editorial/topics/{topic_id}/select")
def select_editorial_topic(
    topic_id: int,
    request: EditorialActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_select_topic(current_user), "topic_select", entity_type="editorial_topic", entity_id=topic_id)
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    _assert_same_workspace(topic, current_user, "Editorial topic not found")
    topic.status = "selected"
    topic.editor_note = request.reviewer_note
    _audit(db, "editorial_topic", topic.id, "topic_selected", current_user, request.reviewer_note)
    _record_approval(db, "editorial_topic", topic.id, "topic_selected", current_user, "selected", request.reviewer_note)
    db.commit()
    db.refresh(topic)
    return _editorial_topic_payload(topic)


@router.post("/editorial/topics/{topic_id}/reject")
def reject_editorial_topic(
    topic_id: int,
    request: EditorialActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_select_topic(current_user), "topic_reject", entity_type="editorial_topic", entity_id=topic_id)
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    topic.status = "rejected"
    topic.editor_note = request.reviewer_note
    _audit(db, "editorial_topic", topic.id, "topic_rejected", current_user, request.reviewer_note)
    _record_approval(db, "editorial_topic", topic.id, "topic_rejected", current_user, "rejected", request.reviewer_note)
    db.commit()
    db.refresh(topic)
    return _editorial_topic_payload(topic)


@router.post("/editorial/topics/{topic_id}/needs-more-evidence")
def mark_editorial_topic_needs_more_evidence(
    topic_id: int,
    request: EditorialActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_select_topic(current_user), "topic_needs_more_evidence", entity_type="editorial_topic", entity_id=topic_id)
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    topic.status = "needs_more_evidence"
    topic.editor_note = request.reviewer_note
    _audit(db, "editorial_topic", topic.id, "topic_needs_more_evidence", current_user, request.reviewer_note)
    _record_approval(db, "editorial_topic", topic.id, "topic_needs_more_evidence", current_user, "needs_more_evidence", request.reviewer_note)
    db.commit()
    db.refresh(topic)
    return _editorial_topic_payload(topic)


@router.post("/editorial/calendar/schedule")
def schedule_editorial_topic(
    request: EditorialCalendarScheduleRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_schedule_topic(current_user), "calendar_schedule")
    topic = db.get(EditorialTopic, request.topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    _assert_same_workspace(topic, current_user, "Editorial topic not found")
    if topic.status not in {"selected", "scheduled"}:
        raise HTTPException(status_code=409, detail=f"Topic status {topic.status} cannot be scheduled")
    entry = EditorialCalendarEntry(
        workspace_id=_workspace_id(current_user),
        date=request.date or dt_date.today(),
        topic_id=topic.id,
        slot_name=request.slot_name,
        target_platforms=request.target_platforms,
        planned_duration=request.planned_duration,
        status="ready_for_brief",
        assigned_editor=request.assigned_editor,
        publish_window_note=request.publish_window_note,
    )
    topic.status = "scheduled"
    topic.editor_note = request.reviewer_note
    db.add(entry)
    db.flush()
    _audit(db, "editorial_calendar_entry", entry.id, "calendar_scheduled", current_user, request.reviewer_note)
    _record_approval(db, "editorial_calendar_entry", entry.id, "calendar_scheduled", current_user, "scheduled", request.reviewer_note)
    db.commit()
    db.refresh(entry)
    return _calendar_entry_payload(entry, topic)


@router.get("/editorial/calendar")
def list_editorial_calendar(
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    entries = list(
        db.scalars(
            select(EditorialCalendarEntry)
            .where(EditorialCalendarEntry.workspace_id == _workspace_id(current_user))
            .order_by(EditorialCalendarEntry.date.desc(), EditorialCalendarEntry.id.desc())
        ).all()
    )
    return {"entries": [_calendar_entry_payload(entry, db.get(EditorialTopic, entry.topic_id)) for entry in entries]}


@router.get("/editorial/calendar/{calendar_date}")
def get_editorial_calendar_date(
    calendar_date: dt_date,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    entries = list(
        db.scalars(
            select(EditorialCalendarEntry)
            .where(EditorialCalendarEntry.workspace_id == _workspace_id(current_user), EditorialCalendarEntry.date == calendar_date)
            .order_by(EditorialCalendarEntry.id.desc())
        ).all()
    )
    return {"date": calendar_date.isoformat(), "entries": [_calendar_entry_payload(entry, db.get(EditorialTopic, entry.topic_id)) for entry in entries]}


@router.post("/editorial/topics/{topic_id}/generate-brief")
def generate_brief_from_topic(
    topic_id: int,
    request: EditorialActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "topic_generate_brief", entity_type="editorial_topic", entity_id=topic_id)
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    if topic.status not in {"selected", "scheduled"}:
        raise HTTPException(status_code=409, detail=f"Topic status {topic.status} cannot generate a brief")
    if not topic.selected_post_ids:
        raise HTTPException(status_code=409, detail="Topic has no selected promoted posts")
    calendar_entry = db.scalars(
        select(EditorialCalendarEntry)
        .where(EditorialCalendarEntry.topic_id == topic.id)
        .order_by(EditorialCalendarEntry.id.desc())
    ).first()
    metadata = {
        "topic_id": topic.id,
        "calendar_entry_id": calendar_entry.id if calendar_entry else None,
        "generated_from_editorial_calendar": True,
        "editor_note": request.reviewer_note,
        "created_by": current_user.username,
        "created_by_role": current_user.role,
    }
    payload = generate_brief(
        GenerateBriefRequest(
            limit=min(4, max(2, len(topic.selected_post_ids))),
            production_only=True,
            post_ids=topic.selected_post_ids,
            topic_metadata=metadata,
        ),
        db,
        current_user,
    )
    if calendar_entry is not None:
        calendar_entry.status = "in_production"
    topic.status = "used"
    _audit(db, "editorial_topic", topic.id, "brief_generated_from_topic", current_user, request.reviewer_note)
    _record_approval(db, "brief", payload["id"], "brief_generated_from_topic", current_user, "created", request.reviewer_note)
    db.commit()
    return payload


@router.post("/editorial/topics/{topic_id}/start-production")
def start_topic_production(
    topic_id: int,
    request: EditorialActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "topic_start_production", entity_type="editorial_topic", entity_id=topic_id)
    topic = db.get(EditorialTopic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Editorial topic not found")
    if topic.status not in {"selected", "scheduled"}:
        raise HTTPException(status_code=409, detail=f"Topic status {topic.status} cannot start production")
    return generate_brief_from_topic(topic_id, request, db, current_user)


@router.post("/editorial/briefs/{brief_id}/run-next-step")
def run_brief_next_step(
    brief_id: int,
    request: RunNextStepRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    decision = NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))
    action = decision["next_action"]
    if action == "generate_evidence_pack":
        PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "run_next_evidence", entity_type="brief", entity_id=brief_id)
        result = generate_brief_evidence_pack(brief_id, db=db, current_user=current_user)
        return {"executed_action": action, "result": result, "next_action": NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))}
    if action == "await_human_approval":
        raise HTTPException(status_code=409, detail={"message": "Human approval is required; run-next-step cannot auto approve", "next_action": decision})
    if action == "generate_render_package":
        PermissionService().assert_allowed(db, current_user, PermissionService().can_render(current_user), "run_next_render", entity_type="brief", entity_id=brief_id)
        result = generate_render_package(brief_id, db, current_user)
        return {"executed_action": action, "result": result, "next_action": NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))}
    if action == "generate_tts":
        PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_tts(current_user), "run_next_tts", entity_type="brief", entity_id=brief_id)
        result = generate_tts(brief_id, TTSGenerateRequest(provider="local_stub", voice="neutral_zh"), db, current_user)
        return {"executed_action": action, "result": result, "next_action": NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))}
    if action == "generate_final_video":
        PermissionService().assert_allowed(db, current_user, PermissionService().can_render(current_user), "run_next_final_video", entity_type="brief", entity_id=brief_id)
        result = generate_final_video(brief_id, db, current_user)
        return {"executed_action": action, "result": result, "next_action": NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))}
    if action == "generate_platform_package":
        PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_platform_package(current_user), "run_next_platform_package", entity_type="brief", entity_id=brief_id)
        result = generate_platform_package(brief_id, db, current_user)
        return {"executed_action": action, "result": result, "next_action": NextActionService().brief_next_action(db, brief, _tts_status_payload(brief.id))}
    if action == "manual_publish_review":
        raise HTTPException(status_code=409, detail={"message": "Manual publish only; no platform publishing API is available", "next_action": decision})
    raise HTTPException(status_code=409, detail={"message": "No runnable next step", "next_action": decision})


@router.post("/sources/ingest/manual-url")
def ingest_manual_url(
    request: ManualUrlIngestRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "source_ingest_manual_url")
    adapter = ManualUrlAdapter()
    adapter.validate_terms_safety()
    payload = adapter.create_review_item(
        source_url=request.source_url,
        short_excerpt=request.short_excerpt,
        source_name=request.source_name,
        archive_url=request.archive_url,
        media_refs=request.media_refs,
    )
    item = SourceReviewItem(workspace_id=_workspace_id(current_user), **payload)
    db.add(item)
    db.flush()
    _audit(db, "source_review_item", item.id, "ingest_manual_url", current_user, "Manual URL source entered review queue")
    db.commit()
    db.refresh(item)
    return _source_review_payload(item)


@router.post("/sources/ingest/public-archive-json")
def ingest_public_archive_json(
    request: PublicArchiveJsonIngestRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "source_ingest_public_archive_json")
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {request.path}")
    adapter = PublicArchiveJsonAdapter(path)
    adapter.validate_terms_safety()
    items = []
    for payload in adapter.fetch_review_items():
        item = SourceReviewItem(workspace_id=_workspace_id(current_user), **payload)
        db.add(item)
        db.flush()
        _audit(db, "source_review_item", item.id, "ingest_public_archive_json", None, f"Imported from {request.path}")
        items.append(item)
    db.commit()
    return {"created_count": len(items), "items": [_source_review_payload(item) for item in items]}


@router.post("/sources/ingest/daily-feed-json")
def ingest_daily_feed_json(
    request: DailyFeedJsonIngestRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "source_ingest_daily_feed_json")
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {request.path}")
    adapter = DailyFeedJsonAdapter(path)
    adapter.validate_terms_safety()
    items = []
    skipped = []
    for payload in adapter.fetch_review_items():
        existing = db.scalars(
            select(SourceReviewItem).where(
                SourceReviewItem.workspace_id == _workspace_id(current_user),
                SourceReviewItem.source_url == payload["source_url"],
            )
        ).first()
        if existing:
            skipped.append(_source_review_payload(existing))
            continue
        item = SourceReviewItem(workspace_id=_workspace_id(current_user), **payload)
        db.add(item)
        db.flush()
        _audit(db, "source_review_item", item.id, "ingest_daily_feed_json", current_user, f"Imported from {request.path}")
        items.append(item)
    db.commit()
    return {
        "created_count": len(items),
        "skipped_count": len(skipped),
        "items": [_source_review_payload(item) for item in items],
        "skipped_items": skipped,
        "manual_review_required": True,
    }


@router.post("/sources/ingest/remote-feed")
def ingest_remote_feed(
    request: RemoteFeedIngestRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "source_ingest_remote_feed")
    path = Path(request.config_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Remote feed config not found: {request.config_path}")
    adapter = RemoteFeedAdapter(path)
    try:
        adapter.validate_terms_safety()
        payloads, filter_report = adapter.fetch_review_items_with_filter_report(target_date=request.run_date)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    items = []
    skipped = []
    for payload in payloads:
        existing = db.scalars(
            select(SourceReviewItem).where(
                SourceReviewItem.workspace_id == _workspace_id(current_user),
                SourceReviewItem.source_url == payload["source_url"],
            )
        ).first()
        if existing:
            skipped.append(_source_review_payload(existing))
            continue
        item = SourceReviewItem(workspace_id=_workspace_id(current_user), **payload)
        db.add(item)
        db.flush()
        _audit(db, "source_review_item", item.id, "ingest_remote_feed", current_user, f"Imported from {request.config_path}")
        items.append(item)
    db.commit()
    return {
        "created_count": len(items),
        "skipped_count": len(skipped),
        "items": [_source_review_payload(item) for item in items],
        "skipped_items": skipped,
        "filter_report": filter_report,
        "manual_review_required": True,
    }


@router.post("/sources/remote-feed/readiness")
def remote_feed_readiness(
    request: RemoteFeedIngestRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "remote_feed_readiness")
    return FeedReadinessValidator().validate_remote_feed_config(request.config_path, target_date=request.run_date)


@router.get("/sources/review-queue")
def source_review_queue(
    status: str | None = None,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    statement = (
        select(SourceReviewItem)
        .where(SourceReviewItem.workspace_id == _workspace_id(current_user))
        .order_by(SourceReviewItem.id.desc())
    )
    if status:
        statement = (
            select(SourceReviewItem)
            .where(SourceReviewItem.workspace_id == _workspace_id(current_user), SourceReviewItem.human_status == status)
            .order_by(SourceReviewItem.id.desc())
        )
    items = list(db.scalars(statement).all())
    return {"count": len(items), "items": [_source_review_payload(item) for item in items]}


@router.get("/sources/review-queue/{item_id}")
def get_source_review_item(
    item_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    item = db.get(SourceReviewItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source review item not found")
    _assert_same_workspace(item, current_user, "Source review item not found")
    logs = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "source_review_item", AuditLog.entity_id == item.id)
        .order_by(AuditLog.id.asc())
    ).all()
    payload = _source_review_payload(item)
    payload["audit_logs"] = [
        {
            "id": log.id,
            "action": log.action,
            "actor": log.actor,
            "note": log.note,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
    return payload


def _review_action(item_id: int, request: SourceReviewActionRequest, status: str, db: Session, current_user: CurrentUser) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_source(current_user), f"source_{status}", entity_type="source_review_item", entity_id=item_id)
    item = db.get(SourceReviewItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source review item not found")
    _assert_same_workspace(item, current_user, "Source review item not found")
    item.human_status = status
    item.reviewer_name = current_user.username
    item.reviewer_note = request.reviewer_note
    if status == "rejected":
        item.rejection_reason = request.reviewer_note
    _audit(db, "source_review_item", item.id, f"source_{status}", current_user, request.reviewer_note)
    _record_approval(db, "source_review_item", item.id, f"source_{status}", current_user, status, request.reviewer_note)
    db.commit()
    db.refresh(item)
    return _source_review_payload(item)


def _assert_source_can_promote(item: SourceReviewItem, current_user: CurrentUser) -> None:
    _assert_same_workspace(item, current_user, "Source review item not found")
    if item.human_status != "approved":
        raise HTTPException(status_code=409, detail="Only approved source review items can be promoted")
    if item.terms_status == "blocked":
        raise HTTPException(status_code=409, detail="Blocked source review item cannot be promoted")


def _promote_source_review_to_evidence(
    db: Session,
    item: SourceReviewItem,
    current_user: CurrentUser,
    note: str | None,
    post_id: int | None = None,
) -> EvidenceItem:
    existing = db.scalar(
        select(EvidenceItem).where(
            EvidenceItem.workspace_id == _workspace_id(current_user),
            EvidenceItem.source_review_item_id == item.id,
        )
    )
    if existing is not None:
        return existing
    evidence_source = EvidenceSource(
        source_name=item.source_name,
        source_url=item.source_url,
        archive_url=item.archive_url,
        publisher_type="public_archive" if item.archive_url else "manual",
        reliability_tier="medium",
        retrieved_at=item.retrieved_at,
        terms_status=item.terms_status,
        metadata_json={"source_review_item_id": item.id, "adapter_name": item.adapter_name},
    )
    db.add(evidence_source)
    db.flush()
    evidence = EvidenceItem(
        workspace_id=_workspace_id(current_user),
        source_review_item_id=item.id,
        post_id=post_id,
        evidence_source_id=evidence_source.id,
        evidence_type="public_archive" if item.archive_url else "manual_note",
        title=item.normalized_summary[:300],
        source_name=item.source_name,
        source_url=item.source_url,
        archive_url=item.archive_url,
        excerpt=item.raw_excerpt[:500],
        summary=item.normalized_summary[:1000],
        retrieved_at=item.retrieved_at,
        reliability_score=70 if item.terms_status == "allowed" else 60,
        terms_status=item.terms_status,
        human_status="approved",
        created_by=current_user.username,
        reviewed_by=item.reviewer_name or current_user.username,
        supports_claim="unclear",
        confidence=0.5,
        reviewer_note=note,
    )
    db.add(evidence)
    db.flush()
    _audit(db, "evidence_item", evidence.id, "evidence_promoted_from_source_review", current_user, note)
    return evidence


@router.post("/sources/review-queue/{item_id}/approve")
def approve_source_review_item(
    item_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _review_action(item_id, request, "approved", db, current_user)


@router.post("/sources/review-queue/{item_id}/reject")
def reject_source_review_item(
    item_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _review_action(item_id, request, "rejected", db, current_user)


@router.post("/sources/review-queue/{item_id}/needs-changes")
def source_review_needs_changes(
    item_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _review_action(item_id, request, "needs_changes", db, current_user)


@router.post("/sources/review-queue/{item_id}/promote-to-post")
def promote_source_review_item(
    item_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_source(current_user), "source_promote_to_post", entity_type="source_review_item", entity_id=item_id)
    item = db.get(SourceReviewItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source review item not found")
    _assert_source_can_promote(item, current_user)

    source = db.scalar(select(Source).where(Source.name == item.source_name))
    if source is None:
        source = Source(
            name=item.source_name,
            kind=item.adapter_name,
            base_url=item.archive_url or item.source_url,
            terms_safe=item.terms_status != "blocked",
            metadata_json={
                "adapter_name": item.adapter_name,
                "manual_input": item.adapter_name == "manual_url",
                "sample_data": False,
                "direct_truth_social_scrape": False,
            },
        )
        db.add(source)
        db.flush()

    existing = db.scalar(
        select(Post).where(Post.source_url == item.source_url, Post.workspace_id == _workspace_id(current_user))
    )
    if existing is not None:
        _audit(db, "source_review_item", item.id, "promote_to_post_duplicate", current_user, request.reviewer_note)
        db.commit()
        return {"post": _post_payload(existing), "source_review_item": _source_review_payload(item), "duplicate": True}

    text_for_hash = f"{item.source_url}\n{item.raw_excerpt}\n{item.normalized_summary}"
    text_hash = hashlib.sha256(text_for_hash.encode("utf-8")).hexdigest()
    post = Post(
        workspace_id=_workspace_id(current_user),
        source_id=source.id,
        post_id=f"source-review-{item.id}",
        published_at=item.retrieved_at or datetime.now(timezone.utc),
        source_url=item.source_url,
        short_excerpt=item.raw_excerpt[:500],
        summary=item.normalized_summary[:1000],
        topic=item.metadata_json.get("topic", "source-reviewed public item"),
        text_hash=text_hash,
        fact_check_status="pending",
        source_review_required=False,
        source_policy={
            "allowed": True,
            "requires_human_source_review": False,
            "human_source_review_status": "promoted",
            "source_review_item_id": item.id,
            "terms_status": item.terms_status,
            "adapter_name": item.adapter_name,
            "source_name": item.source_name,
        },
    )
    db.add(post)
    db.flush()
    _audit(db, "source_review_item", item.id, "promote_to_post", current_user, request.reviewer_note)
    _audit(db, "post", post.id, "created_from_source_review", current_user, f"source_review_item:{item.id}")
    _record_approval(db, "source_review_item", item.id, "promote_to_post", current_user, "promoted", request.reviewer_note)
    db.commit()
    db.refresh(post)
    db.refresh(item)
    return {"post": _post_payload(post), "source_review_item": _source_review_payload(item), "duplicate": False}


@router.post("/sources/review-queue/{item_id}/promote-to-evidence")
def promote_source_review_item_to_evidence(
    item_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_source(current_user), "source_promote_to_evidence", entity_type="source_review_item", entity_id=item_id)
    item = db.get(SourceReviewItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Source review item not found")
    _assert_source_can_promote(item, current_user)
    evidence = _promote_source_review_to_evidence(db, item, current_user, request.reviewer_note)
    _record_approval(db, "source_review_item", item.id, "promote_to_evidence", current_user, "promoted", request.reviewer_note)
    db.commit()
    db.refresh(evidence)
    return {"evidence_item": _evidence_item_payload(evidence), "source_review_item": _source_review_payload(item)}


@router.post("/sources/review-queue/{item_id}/promote-to-post-and-evidence")
def promote_source_review_item_to_post_and_evidence(
    item_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    post_payload = promote_source_review_item(item_id, request, db, current_user)
    item = db.get(SourceReviewItem, item_id)
    post = db.get(Post, post_payload["post"]["id"])
    evidence = _promote_source_review_to_evidence(db, item, current_user, request.reviewer_note, post_id=post.id if post else None)
    _record_approval(db, "source_review_item", item_id, "promote_to_post_and_evidence", current_user, "promoted", request.reviewer_note)
    db.commit()
    db.refresh(evidence)
    return {**post_payload, "evidence_item": _evidence_item_payload(evidence)}


@router.get("/sources/review-page", response_class=HTMLResponse)
def source_review_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> HTMLResponse:
    items = list(
        db.scalars(
            select(SourceReviewItem)
            .where(
                SourceReviewItem.workspace_id == _workspace_id(current_user),
                SourceReviewItem.human_status.in_(["pending", "needs_changes", "approved"]),
            )
            .order_by(SourceReviewItem.id.desc())
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "source_review.html",
        {
            "items": [_source_review_payload(item) for item in items],
        },
    )


@router.get("/evidence")
def list_evidence(db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    items = list(
        db.scalars(
            select(EvidenceItem)
            .where(EvidenceItem.workspace_id == _workspace_id(current_user))
            .order_by(EvidenceItem.id.desc())
        ).all()
    )
    return {"count": len(items), "items": [_evidence_item_payload(item) for item in items]}


@router.get("/evidence/{evidence_id}")
def get_evidence(evidence_id: int, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    _assert_same_workspace(item, current_user, "Evidence item not found")
    return _evidence_item_payload(item)


@router.post("/evidence/{evidence_id}/approve")
def approve_evidence(
    evidence_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "evidence_approve", entity_type="evidence_item", entity_id=evidence_id)
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    _assert_same_workspace(item, current_user, "Evidence item not found")
    if item.created_by and item.created_by == current_user.username and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="same_user_cannot_create_and_approve_evidence")
    item.human_status = "approved"
    item.reviewed_by = current_user.username
    item.reviewer_note = request.reviewer_note
    _audit(db, "evidence_item", item.id, "evidence_approved", current_user, request.reviewer_note)
    _record_approval(db, "evidence_item", item.id, "evidence_approved", current_user, "approved", request.reviewer_note)
    db.commit()
    return _evidence_item_payload(item)


@router.post("/evidence/{evidence_id}/reject")
def reject_evidence(
    evidence_id: int,
    request: SourceReviewActionRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "evidence_reject", entity_type="evidence_item", entity_id=evidence_id)
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    _assert_same_workspace(item, current_user, "Evidence item not found")
    item.human_status = "rejected"
    item.reviewed_by = current_user.username
    item.reviewer_note = request.reviewer_note
    _audit(db, "evidence_item", item.id, "evidence_rejected", current_user, request.reviewer_note)
    _record_approval(db, "evidence_item", item.id, "evidence_rejected", current_user, "rejected", request.reviewer_note)
    db.commit()
    return _evidence_item_payload(item)


@router.post("/evidence/{evidence_id}/score")
def score_evidence(
    evidence_id: int,
    request: EvidenceScoreRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "evidence_score", entity_type="evidence_item", entity_id=evidence_id)
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    _assert_same_workspace(item, current_user, "Evidence item not found")
    item.reliability_score = request.reliability_score
    item.reviewer_note = request.reviewer_note
    _audit(db, "evidence_item", item.id, "evidence_scored", current_user, str(request.reliability_score))
    db.commit()
    return _evidence_item_payload(item)


@router.get("/evidence/{evidence_id}/audit")
def evidence_audit(evidence_id: int, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    item = db.get(EvidenceItem, evidence_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    _assert_same_workspace(item, current_user, "Evidence item not found")
    logs = list(
        db.scalars(
            select(AuditLog)
            .where(AuditLog.workspace_id == _workspace_id(current_user), AuditLog.entity_type == "evidence_item", AuditLog.entity_id == evidence_id)
            .order_by(AuditLog.id.asc())
        ).all()
    )
    return {"evidence_item_id": evidence_id, "audit_logs": [_audit_payload(log) for log in logs]}


def _assert_claim_workspace(claim: Claim, current_user: CurrentUser) -> None:
    if claim.post.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=404, detail="Claim not found")


@router.post("/claims/{claim_id}/evidence-links")
def create_claim_evidence_link(
    claim_id: int,
    request: ClaimEvidenceLinkRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user) or PermissionService().can_review_evidence(current_user), "claim_evidence_link_create", entity_type="claim", entity_id=claim_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    _assert_claim_workspace(claim, current_user)
    evidence = db.get(EvidenceItem, request.evidence_item_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Evidence item not found")
    _assert_same_workspace(evidence, current_user, "Evidence item not found")
    if evidence.human_status != "approved":
        raise HTTPException(status_code=409, detail="Only approved evidence can be linked to claims")
    support_type = request.support_type.strip().lower()
    if support_type not in {"supports", "disputes", "contextualizes", "source_only"}:
        raise HTTPException(status_code=400, detail="Invalid support_type")
    confidence = request.confidence.strip().lower()
    if confidence not in {"low", "medium", "high"}:
        raise HTTPException(status_code=400, detail="Invalid confidence")
    existing = db.scalar(
        select(ClaimEvidenceLink).where(
            ClaimEvidenceLink.claim_id == claim.id,
            ClaimEvidenceLink.evidence_item_id == evidence.id,
        )
    )
    if existing is not None:
        return _claim_evidence_link_payload(existing)
    link = ClaimEvidenceLink(
        workspace_id=_workspace_id(current_user),
        claim_id=claim.id,
        evidence_item_id=evidence.id,
        support_type=support_type,
        confidence=confidence,
        note=request.note,
    )
    evidence.claim_id = claim.id
    evidence.supports_claim = "supports" if support_type == "supports" else "contradicts" if support_type == "disputes" else "contextual"
    evidence.confidence = {"low": 0.35, "medium": 0.65, "high": 0.9}[confidence]
    db.add(link)
    db.flush()
    EvidencePackService().build_or_update_pack(db, claim)
    _audit(db, "claim_evidence_link", link.id, "claim_evidence_link_created", current_user, request.note)
    db.commit()
    return _claim_evidence_link_payload(link)


@router.get("/claims/{claim_id}/evidence-links")
def get_claim_evidence_links(claim_id: int, db: Session = Depends(get_db), current_user: CurrentUser = Depends(get_current_user)) -> dict[str, Any]:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    _assert_claim_workspace(claim, current_user)
    links = list(db.scalars(select(ClaimEvidenceLink).where(ClaimEvidenceLink.claim_id == claim.id).order_by(ClaimEvidenceLink.id.asc())).all())
    return {"claim_id": claim.id, "links": [_claim_evidence_link_payload(link) for link in links]}


@router.delete("/claims/{claim_id}/evidence-links/{link_id}")
def delete_claim_evidence_link(
    claim_id: int,
    link_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user) or PermissionService().can_review_evidence(current_user), "claim_evidence_link_delete", entity_type="claim", entity_id=claim_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    _assert_claim_workspace(claim, current_user)
    link = db.get(ClaimEvidenceLink, link_id)
    if link is None or link.claim_id != claim.id or link.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=404, detail="Claim evidence link not found")
    _audit(db, "claim_evidence_link", link.id, "claim_evidence_link_deleted", current_user, None)
    db.delete(link)
    EvidencePackService().build_or_update_pack(db, claim)
    db.commit()
    return {"deleted": True, "id": link_id}


@router.post("/claims/{claim_id}/evidence/manual")
def attach_manual_evidence(
    claim_id: int,
    request: ManualEvidenceRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "evidence_manual_attach", entity_type="claim", entity_id=claim_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    provider = default_registry(environment="production").get_provider("manual")
    try:
        normalized = provider.normalize_evidence(request.model_dump())
        pack_payload = _attach_normalized_evidence(db, claim, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(db, "claim", claim.id, "manual_evidence_attached", current_user, request.reviewer_note)
    _record_approval(db, "claim", claim.id, "manual_evidence_attached", current_user, "attached", request.reviewer_note)
    db.commit()
    return pack_payload


@router.post("/claims/{claim_id}/evidence/from-json")
def attach_json_evidence(
    claim_id: int,
    request: JsonEvidenceRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "evidence_json_attach", entity_type="claim", entity_id=claim_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Evidence JSON not found: {request.path}")
    provider = default_registry(environment="production").get_provider("local_json")
    try:
        normalized_items = provider.search_evidence(claim, path=str(path), claim_id=claim.id)
        pack_payload = None
        for normalized in normalized_items:
            pack_payload = _attach_normalized_evidence(db, claim, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(db, "claim", claim.id, "local_json_evidence_attached", current_user, request.path)
    _record_approval(db, "claim", claim.id, "local_json_evidence_attached", current_user, "attached", request.path)
    db.commit()
    return pack_payload or _claim_evidence_pack_payload(db, claim.id) or {}


@router.post("/claims/{claim_id}/evidence/search")
def search_evidence_candidates(
    claim_id: int,
    request: EvidenceSearchRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "evidence_search", entity_type="claim", entity_id=claim_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    try:
        provider = ExternalSearchProviderRegistry(production=True).get_provider(request.provider)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    query = request.query or EvidenceQueryBuilder().build(claim)[0]
    _audit(db, "claim", claim.id, "evidence_search_requested", current_user, f"{request.provider}:{query}")
    created = []
    try:
        for raw in provider.search(query=query, claim=claim):
            normalized = provider.normalize_result(raw, query)
            candidate = EvidenceCandidate(claim_id=claim.id, **normalized)
            db.add(candidate)
            db.flush()
            _audit(db, "evidence_candidate", candidate.id, "candidate_created", None, query)
            created.append(candidate)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"claim_id": claim.id, "query": query, "created_count": len(created), "candidates": [_candidate_payload(item) for item in created]}


@router.get("/claims/{claim_id}/evidence/candidates")
def get_evidence_candidates(claim_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    candidates = list(
        db.scalars(select(EvidenceCandidate).where(EvidenceCandidate.claim_id == claim.id).order_by(EvidenceCandidate.id.desc())).all()
    )
    return {"claim_id": claim.id, "count": len(candidates), "candidates": [_candidate_payload(item) for item in candidates]}


def _review_candidate(candidate_id: int, request: CandidateReviewRequest, status: str, db: Session, current_user: CurrentUser) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), f"candidate_{status}", entity_type="evidence_candidate", entity_id=candidate_id)
    candidate = db.get(EvidenceCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Evidence candidate not found")
    candidate.status = status
    candidate.reviewer_name = current_user.username
    candidate.reviewer_note = request.reviewer_note
    _audit(db, "evidence_candidate", candidate.id, f"candidate_{status}", current_user, request.reviewer_note)
    _record_approval(db, "evidence_candidate", candidate.id, f"candidate_{status}", current_user, status, request.reviewer_note)
    db.commit()
    db.refresh(candidate)
    return _candidate_payload(candidate)


@router.post("/evidence/candidates/{candidate_id}/accept")
def accept_evidence_candidate(
    candidate_id: int,
    request: CandidateReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "candidate_accept", entity_type="evidence_candidate", entity_id=candidate_id)
    candidate = db.get(EvidenceCandidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Evidence candidate not found")
    if candidate.status == "blocked":
        raise HTTPException(status_code=409, detail="Blocked evidence candidate cannot be accepted")
    if "domain_not_allowlisted" in candidate.metadata_json.get("warnings", []):
        raise HTTPException(status_code=409, detail="Candidate domain is not allowlisted")
    claim = db.get(Claim, candidate.claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    normalized = {
        "source": {
            "source_name": candidate.source_name,
            "source_url": candidate.source_url,
            "archive_url": candidate.archive_url,
            "publisher_type": candidate.publisher_type,
            "reliability_tier": candidate.reliability_tier,
            "retrieved_at": datetime.now(timezone.utc),
            "terms_status": "manual_review_required",
            "metadata_json": {"provider": candidate.provider_name, "candidate_id": candidate.id},
        },
        "item": {
            "excerpt": candidate.excerpt,
            "summary": candidate.excerpt[:1000],
            "supports_claim": request.supports_claim,
            "confidence": request.confidence,
            "reviewer_note": request.reviewer_note,
        },
    }
    pack_payload = _attach_normalized_evidence(db, claim, normalized)
    candidate.status = "accepted"
    candidate.reviewer_name = current_user.username
    candidate.reviewer_note = request.reviewer_note
    _audit(db, "evidence_candidate", candidate.id, "candidate_accepted", current_user, request.reviewer_note)
    _record_approval(db, "evidence_candidate", candidate.id, "candidate_accepted", current_user, "accepted", request.reviewer_note)
    db.commit()
    db.refresh(candidate)
    return {"candidate": _candidate_payload(candidate), "evidence_pack": pack_payload}


@router.post("/evidence/candidates/{candidate_id}/reject")
def reject_evidence_candidate(
    candidate_id: int,
    request: CandidateReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _review_candidate(candidate_id, request, "rejected", db, current_user)


@router.post("/evidence/candidates/{candidate_id}/block")
def block_evidence_candidate(
    candidate_id: int,
    request: CandidateReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    return _review_candidate(candidate_id, request, "blocked", db, current_user)


@router.get("/claims/{claim_id}/evidence-pack")
def get_claim_evidence_pack(claim_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    pack_payload = _claim_evidence_pack_payload(db, claim.id)
    if pack_payload is None:
        pack = EvidencePackService().build_or_update_pack(db, claim)
        db.commit()
        pack_payload = EvidencePackService().pack_payload(pack, _evidence_items_for_claim(db, claim.id))
    return pack_payload


@router.post("/claims/{claim_id}/evidence-pack/review")
def review_claim_evidence_pack(
    claim_id: int,
    request: EvidencePackReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "evidence_pack_review", entity_type="claim", entity_id=claim_id)
    claim = db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    pack = db.scalars(select(EvidencePack).where(EvidencePack.claim_id == claim.id).order_by(EvidencePack.id.desc())).first()
    if pack is None:
        pack = EvidencePackService().build_or_update_pack(db, claim)
    pack.reviewer_name = current_user.username
    pack.reviewer_note = request.reviewer_note
    pack.review_status = request.review_status
    _audit(db, "claim", claim.id, "evidence_pack_review", current_user, request.reviewer_note)
    _record_approval(db, "claim", claim.id, "evidence_pack_review", current_user, request.review_status, request.reviewer_note)
    db.commit()
    return EvidencePackService().pack_payload(pack, _evidence_items_for_claim(db, claim.id))


@router.post("/ingest/manual")
def ingest_manual(
    request: ManualIngestRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "manual_ingest")
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {request.path}")

    adapter = ManualArchiveAdapter(path)
    adapter.validate_terms_safety()
    source_payload = adapter.source_payload()
    source = db.scalar(select(Source).where(Source.name == source_payload["name"]))
    if source is None:
        source = Source(**source_payload)
        db.add(source)
        db.flush()

    dedup = DedupService(db)
    source_policy = SourcePolicy()
    created: list[Post] = []
    skipped: list[dict[str, str]] = []
    for raw in adapter.fetch_latest_posts():
        normalized = adapter.normalize_post(raw)
        policy_result = source_policy.validate_source(
            normalized,
            {
                "name": source.name,
                "sample_data": source.metadata_json.get("sample_data"),
                "manual_input": source.metadata_json.get("manual_input"),
            },
        )
        if not policy_result.allowed:
            skipped.append(
                {
                    "post_id": normalized["post_id"],
                    "reason": "source_policy_blocked",
                    "details": ",".join(policy_result.reasons),
                }
            )
            continue
        duplicate_reason = dedup.find_duplicate(normalized)
        if duplicate_reason:
            skipped.append({"post_id": normalized["post_id"], "reason": duplicate_reason})
            continue
        post = Post(
            workspace_id=_workspace_id(current_user),
            source_id=source.id,
            source_review_required=policy_result.requires_human_source_review,
            source_policy=policy_result.as_dict(),
            **normalized,
        )
        db.add(post)
        created.append(post)
    db.commit()
    for post in created:
        db.refresh(post)

    return {
        "source": source.name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created_posts": [_post_payload(post) for post in created],
        "skipped": skipped,
    }


@router.post("/briefs/generate")
def generate_brief(
    request: GenerateBriefRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_brief(current_user), "brief_generate")
    all_posts = list(
        db.scalars(
            select(Post)
            .where(Post.workspace_id == _workspace_id(current_user))
            .order_by(Post.published_at.desc())
        ).all()
    )
    posts = [
        post
        for post in all_posts
        if post.source_policy.get("human_source_review_status") == "promoted"
        or (not request.production_only and post.source_policy.get("evidence", {}).get("sample_data") is True)
    ]
    if request.post_ids is not None:
        allowed_ids = set(request.post_ids)
        posts = [post for post in posts if post.id in allowed_ids]
    if not posts:
        raise HTTPException(status_code=400, detail="No promoted or sample posts available. Complete source review and promote first.")

    ranked_posts = Ranker().rank(posts, top_n=request.limit)
    extractor = ClaimExtractor()
    evidence_service = EvidencePackService()
    all_claims: list[Claim] = []
    all_fact_checks: list[FactCheck] = []

    for post in ranked_posts:
        post.ranking_score = post.ranking_breakdown["total"]
        claim_payloads = extractor.extract(post)
        post_fact_status = "opinion"
        for payload in claim_payloads:
            claim = Claim(post_id=post.id, **payload)
            db.add(claim)
            db.flush()
            all_claims.append(claim)
            pack = evidence_service.build_or_update_pack(db, claim)
            evidence_items = list(db.scalars(select(EvidenceItem).where(EvidenceItem.claim_id == claim.id)).all())
            check_payload = evidence_service.fact_check_payload(claim, pack, evidence_items)
            fact_check = FactCheck(claim_id=claim.id, **check_payload)
            db.add(fact_check)
            db.flush()
            all_fact_checks.append(fact_check)
            if fact_check.verdict in {"confirmed", "disputed", "unsupported", "unclear"}:
                post_fact_status = fact_check.verdict
        post.fact_check_status = post_fact_status

    ranked_payload = [_post_payload(post) for post in ranked_posts]
    claims_payload = [
        {
            "id": claim.id,
            "post_id": claim.post_id,
            "claim_text": claim.claim_text,
            "claim_type": claim.claim_type,
            "requires_fact_check": claim.requires_fact_check,
        }
        for claim in all_claims
    ]
    fact_checks_payload = [
        {
            "id": check.id,
            "claim_id": check.claim_id,
            "claim_type": check.claim.claim_type,
            "verdict": check.verdict,
            "rationale": check.rationale,
            "sources": check.sources,
            "provider": check.provider,
        }
        for check in all_fact_checks
    ]
    evidence_packs_payload = [
        pack
        for pack in (_claim_evidence_pack_payload(db, claim.id) for claim in all_claims)
        if pack is not None
    ]
    visual_plan = VisualPlanner().plan(ranked_payload, fact_checks_payload)
    script_payload = ScriptWriter().write(ranked_payload, fact_checks_payload)
    safety_payload = SafetyChecker().review(
        ranked_posts=ranked_payload,
        script=script_payload,
        visual_plan=visual_plan,
        fact_checks=fact_checks_payload,
        claims=claims_payload,
        evidence_packs=evidence_packs_payload,
    )

    metadata = request.topic_metadata or {}
    metadata.setdefault("created_by", current_user.username)
    metadata.setdefault("created_by_role", current_user.role)
    metadata.setdefault("workspace_id", current_user.workspace_id)
    brief = BriefScript(
        workspace_id=_workspace_id(current_user),
        status="blocked" if safety_payload["overall_status"] == "blocked" else "needs_review",
        title=script_payload["title"],
        script_text=script_payload["text"],
        subtitle_draft=script_payload["subtitle_draft"],
        sources=script_payload["sources"],
        ranked_posts=ranked_payload,
        claims=claims_payload,
        fact_checks=fact_checks_payload,
        visual_plan=visual_plan,
        metadata_json=metadata,
    )
    db.add(brief)
    db.flush()

    safety = SafetyReview(
        brief_script_id=brief.id,
        status=safety_payload["overall_status"],
        checks=safety_payload,
        notes=safety_payload["blocking_reasons"] + safety_payload["warnings"],
        human_review_required=True,
        human_approved=False,
    )
    db.add(safety)

    blocked = safety.status == "blocked"
    video_asset_payload = {
        "brief_id": brief.id,
        "title": brief.title,
        "script": script_payload,
        "visual_plan": visual_plan,
        "safety_review": safety_payload,
        "sources": script_payload["sources"],
        "fact_checks": fact_checks_payload,
        "rendering": {
            "mp4_rendered": False,
            "next_step": "Connect Remotion or ffmpeg renderer after human approval.",
        },
    }
    video_asset = VideoAsset(
        brief_script_id=brief.id,
        status="blocked" if blocked else "pending_human_review",
        export_allowed=False,
        asset_json=video_asset_payload,
    )
    db.add(video_asset)
    _audit(db, "brief", brief.id, "brief_generated", current_user, "brief generated from workspace-scoped posts")
    db.commit()
    db.refresh(brief)
    return _brief_payload(brief, db)


@router.get("/briefs/{brief_id}")
def get_brief(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return _brief_payload(brief, db)


@router.get("/briefs/{brief_id}/review-page", response_class=HTMLResponse)
def review_page(
    request: Request,
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> HTMLResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return templates.TemplateResponse(
        request,
        "review.html",
        {
            "brief": _brief_payload(brief, db),
            "pilot_qa": _pilot_qa_payload(db, brief),
        },
    )


def _pilot_qa_payload(db: Session, brief: BriefScript) -> dict[str, Any]:
    brief_payload = _brief_payload(brief, db)
    platform_package = db.scalars(
        select(PlatformPackage).where(PlatformPackage.brief_id == brief.id).order_by(PlatformPackage.id.desc())
    ).first()
    platform_payload = _platform_package_payload(platform_package) if platform_package else None
    return EditorialQAReporter().build(brief_payload, platform_payload)


@router.post("/briefs/{brief_id}/review")
def review_brief(
    brief_id: int,
    request: ReviewRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    if request.human_approved:
        return approve_brief(
            brief_id,
            ApprovalRequest(reviewer_name=request.reviewer_name, reviewer_note=request.reviewer_notes),
            db,
            current_user,
        )
    return request_changes(
        brief_id,
        RequestChangesRequest(reviewer_name=request.reviewer_name, reviewer_note=request.reviewer_notes or "Review not approved."),
        db,
        current_user,
    )


@router.post("/briefs/{brief_id}/approve")
def approve_brief(
    brief_id: int,
    request: ApprovalRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_approve_brief(current_user), "brief_approve", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    if not (request.reviewer_name or request.reviewer_note):
        raise HTTPException(status_code=422, detail="Approval requires reviewer_name or reviewer_note")
    PermissionService().assert_not_same_creator(current_user, brief)
    safety = db.scalars(
        select(SafetyReview)
        .where(SafetyReview.brief_script_id == brief.id)
        .order_by(SafetyReview.id.desc())
    ).first()
    video_asset = db.scalars(
        select(VideoAsset).where(VideoAsset.brief_script_id == brief.id).order_by(VideoAsset.id.desc())
    ).first()
    if safety is None or video_asset is None:
        raise HTTPException(status_code=409, detail="Brief is missing safety review or video asset")
    if safety.status == "blocked" or brief.status == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot be approved for export")
    claim_ids = [claim.get("id") for claim in brief.claims if claim.get("id")]
    if claim_ids:
        packs = list(db.scalars(select(EvidencePack).where(EvidencePack.claim_id.in_(claim_ids))).all())
        if not packs:
            raise HTTPException(status_code=409, detail="EvidencePack is required before brief approval")
    gate_report = FactCheckQualityGate().evaluate(db, brief)
    if gate_report["status"] == "blocked":
        raise HTTPException(status_code=409, detail={"message": "Fact-check quality gate blocked approval", "fact_check_quality_gate": gate_report})

    safety.human_approved = True
    safety.reviewer_name = current_user.username
    safety.reviewer_notes = request.reviewer_note
    brief.status = "approved"
    video_asset.status = "approved_for_export"
    video_asset.export_allowed = True
    video_asset.asset_json = {**video_asset.asset_json, "human_approved": True, "reviewer_name": current_user.username}
    _audit(db, "brief", brief.id, "brief_approved", current_user, request.reviewer_note)
    approval_note = f"{request.reviewer_note or ''}\nfact_check_quality_gate={gate_report['status']}".strip()
    _record_approval(db, "brief", brief.id, "brief_approved", current_user, "approved", approval_note)
    db.commit()
    db.refresh(brief)
    return _brief_payload(brief, db)


@router.post("/briefs/{brief_id}/block")
def block_brief(
    brief_id: int,
    request: BlockRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_approve_brief(current_user), "brief_block", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    safety = db.scalars(
        select(SafetyReview)
        .where(SafetyReview.brief_script_id == brief.id)
        .order_by(SafetyReview.id.desc())
    ).first()
    video_asset = db.scalars(
        select(VideoAsset).where(VideoAsset.brief_script_id == brief.id).order_by(VideoAsset.id.desc())
    ).first()
    if safety is None or video_asset is None:
        raise HTTPException(status_code=409, detail="Brief is missing safety review or video asset")
    brief.status = "blocked"
    safety.status = "blocked"
    safety.human_approved = False
    safety.reviewer_name = current_user.username
    safety.reviewer_notes = request.reviewer_note
    safety.notes = list(safety.notes or []) + [request.reviewer_note]
    video_asset.status = "blocked"
    video_asset.export_allowed = False
    _audit(db, "brief", brief.id, "brief_blocked", current_user, request.reviewer_note)
    _record_approval(db, "brief", brief.id, "brief_blocked", current_user, "blocked", request.reviewer_note)
    db.commit()
    db.refresh(brief)
    return _brief_payload(brief, db)


@router.post("/briefs/{brief_id}/request-changes")
def request_changes(
    brief_id: int,
    request: RequestChangesRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_select_topic(current_user), "brief_request_changes", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    safety = db.scalars(
        select(SafetyReview)
        .where(SafetyReview.brief_script_id == brief.id)
        .order_by(SafetyReview.id.desc())
    ).first()
    video_asset = db.scalars(
        select(VideoAsset).where(VideoAsset.brief_script_id == brief.id).order_by(VideoAsset.id.desc())
    ).first()
    if safety is None or video_asset is None:
        raise HTTPException(status_code=409, detail="Brief is missing safety review or video asset")
    if brief.status != "blocked":
        brief.status = "needs_review"
    safety.human_approved = False
    safety.reviewer_name = current_user.username
    safety.reviewer_notes = request.reviewer_note
    safety.notes = list(safety.notes or []) + [request.reviewer_note]
    video_asset.export_allowed = False
    video_asset.status = "blocked" if brief.status == "blocked" else "pending_human_review"
    _audit(db, "brief", brief.id, "brief_changes_requested", current_user, request.reviewer_note)
    _record_approval(db, "brief", brief.id, "brief_changes_requested", current_user, "changes_requested", request.reviewer_note)
    db.commit()
    db.refresh(brief)
    return _brief_payload(brief, db)


@router.get("/briefs/{brief_id}/review-report")
def review_report(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    return {
        "brief_id": brief.id,
        "status": brief.status,
        "ranked_posts": payload["ranked_posts"],
        "claims": payload["claims"],
        "fact_checks": payload["fact_checks"],
        "safety_review": payload["safety_review"],
        "video_asset_status": payload["video_asset"]["status"] if payload["video_asset"] else None,
    }


@router.get("/briefs/{brief_id}/evidence-link-suggestions")
def get_evidence_link_suggestions(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return EvidenceLinkSuggester().suggest_for_brief(db, brief)


@router.get("/briefs/{brief_id}/pilot-qa")
def get_pilot_qa_report(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return _pilot_qa_payload(db, brief)


@router.post("/briefs/{brief_id}/evidence-pack/generate")
def generate_brief_evidence_pack(
    brief_id: int,
    allow_search: bool = False,
    provider: str = "controlled_search",
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_review_evidence(current_user), "brief_evidence_pack_generate", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _refresh_brief_evidence_state(db, brief)
    report = EvidenceReportBuilder().build(payload)
    claim_ids = [claim["id"] for claim in payload["claims"]]
    claims = list(db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()) if claim_ids else []
    claims_needing_search = [
        claim
        for claim in claims
        if (_claim_evidence_pack_payload(db, claim.id) or {}).get("evidence_count", 0) == 0 and claim.claim_type != "opinion"
    ]
    search_queries_path = EvidenceQueryBuilder().write_queries(claims_needing_search, Path(report["output_dir"]))
    candidates_created = []
    if allow_search and claims_needing_search:
        try:
            search_provider = ExternalSearchProviderRegistry(production=True).get_provider(provider)
            for claim in claims_needing_search:
                query = EvidenceQueryBuilder().build(claim)[0]
                _audit(db, "claim", claim.id, "evidence_search_requested", current_user, f"{provider}:{query}")
                for raw in search_provider.search(query=query, claim=claim):
                    candidate = EvidenceCandidate(claim_id=claim.id, **search_provider.normalize_result(raw, query))
                    db.add(candidate)
                    db.flush()
                    _audit(db, "evidence_candidate", candidate.id, "candidate_created", None, query)
                    candidates_created.append(candidate)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(db, "brief", brief.id, "evidence_report_generated", current_user, report["evidence_report_path"])
    db.commit()
    return {
        "brief_id": brief.id,
        "evidence_packs": payload["evidence_packs"],
        "safety_review": payload["safety_review"],
        "search_queries_path": str(search_queries_path),
        "claims_needing_search": [claim.id for claim in claims_needing_search],
        "candidates_created": [_candidate_payload(candidate) for candidate in candidates_created],
        "report": report,
    }


@router.get("/briefs/{brief_id}/evidence-pack/report")
def get_brief_evidence_report(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    report_path = Path("exports/evidence_reports") / f"brief_{brief.id}" / "evidence_report.json"
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Evidence report not found. Generate evidence pack first.")
    return json.loads(report_path.read_text(encoding="utf-8"))


def _assert_tts_allowed(brief: BriefScript, payload: dict[str, Any]) -> None:
    if brief.status != "approved":
        raise HTTPException(status_code=409, detail="Brief must be approved before TTS generation")
    safety = payload["safety_review"]
    if safety is None or safety["overall_status"] == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot generate TTS")


@router.post("/briefs/{brief_id}/tts/generate")
def generate_tts(
    brief_id: int,
    request: TTSGenerateRequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_tts(current_user), "tts_generate", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    _assert_tts_allowed(brief, payload)

    policy = TTSPolicy()
    provider_name = request.provider or policy.default_provider
    script_text = payload["script"]["text"]
    try:
        policy.validate_request(provider_name, request.voice, script_text, production=True)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    output_dir = _tts_dir(brief.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "narration.txt").write_text(script_text, encoding="utf-8")
    provider = LocalStubTTSProvider() if provider_name == "local_stub" else OpenAITTSProvider()
    audio_path = output_dir / ("audio.wav" if provider_name == "local_stub" else "audio.mp3")
    try:
        metadata = provider.synthesize(script_text, audio_path, voice=request.voice)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    qa = VoiceQA().review(audio_path, metadata)
    (output_dir / "voice_qa_report.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    _audit(db, "brief", brief.id, "tts_generated", current_user, f"{provider_name}:{request.voice}:{qa['status']}")
    db.commit()
    return _tts_status_payload(brief.id)


@router.get("/briefs/{brief_id}/tts/status")
def get_tts_status(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    return _tts_status_payload(brief_id)


@router.get("/briefs/{brief_id}/tts/download")
def download_tts_audio(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    status = _tts_status_payload(brief_id)
    if not status["audio_path"]:
        raise HTTPException(status_code=404, detail="TTS audio not found")
    media_type = "audio/mpeg" if status["audio_path"].endswith(".mp3") else "audio/wav"
    return FileResponse(Path(status["audio_path"]), media_type=media_type, filename=Path(status["audio_path"]).name)


@router.post("/briefs/{brief_id}/tts/voice-qa")
def run_voice_qa(
    brief_id: int,
    request: VoiceQARequest,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_tts(current_user), "voice_qa_review", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    status = _tts_status_payload(brief_id)
    if not status["audio_path"] or not status["metadata"]:
        raise HTTPException(status_code=404, detail="TTS audio or metadata not found")
    qa = VoiceQA().review(status["audio_path"], status["metadata"])
    qa["reviewer_name"] = current_user.username
    qa["reviewer_note"] = request.reviewer_note
    qa_path = _tts_dir(brief_id) / "voice_qa_report.json"
    qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    _audit(db, "brief", brief.id, "voice_qa_reviewed", current_user, request.reviewer_note)
    db.commit()
    return _tts_status_payload(brief_id)


@router.get("/briefs/{brief_id}/export-package")
def export_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    safety = payload["safety_review"]
    video_asset = db.scalars(
        select(VideoAsset).where(VideoAsset.brief_script_id == brief.id).order_by(VideoAsset.id.desc())
    ).first()
    if safety is None or video_asset is None:
        raise HTTPException(status_code=409, detail="Brief is missing safety review or video asset")
    if brief.status != "approved":
        raise HTTPException(status_code=409, detail="Brief must be approved before export")
    if safety["overall_status"] == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot be exported")

    package = _build_export_payload(payload)
    trace = _trace_manifest(db, brief, "export_package", current_user)
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("script.txt", brief.script_text)
        archive.writestr("script.json", json.dumps(package["script"], ensure_ascii=False, indent=2))
        archive.writestr("title_options.json", json.dumps(package["title_options"], ensure_ascii=False, indent=2))
        archive.writestr("visual_plan.json", json.dumps(package["visual_plan"], ensure_ascii=False, indent=2))
        archive.writestr("video_asset.json", json.dumps(package["video_asset"], ensure_ascii=False, indent=2))
        archive.writestr("sources.json", json.dumps(package["sources"], ensure_ascii=False, indent=2))
        archive.writestr("fact_checks.json", json.dumps(package["fact_checks"], ensure_ascii=False, indent=2))
        archive.writestr("safety_review.json", json.dumps(package["safety_review"], ensure_ascii=False, indent=2))
        archive.writestr("trace_manifest.json", json.dumps(trace, ensure_ascii=False, indent=2))
        archive.writestr("README_EXPORT.md", _export_readme(payload))
    buffer.seek(0)
    brief.status = "exported"
    video_asset.status = "exported"
    video_asset.export_allowed = True
    db.commit()
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="daily_truth_brief_{brief_id}.zip"'},
    )


def _latest_render_package(db: Session, brief_id: int, workspace_id: int | None = None) -> RenderPackage | None:
    filters = [RenderPackage.brief_id == brief_id]
    if workspace_id is not None:
        filters.append(RenderPackage.workspace_id == workspace_id)
    return db.scalars(
        select(RenderPackage).where(*filters).order_by(RenderPackage.id.desc())
    ).first()


def _assert_render_allowed(brief: BriefScript, payload: dict[str, Any]) -> None:
    safety = payload["safety_review"]
    if brief.status != "approved":
        raise HTTPException(status_code=409, detail="Brief must be approved before render package generation")
    if safety is None or safety["overall_status"] == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot be rendered")


@router.post("/briefs/{brief_id}/render-package")
def generate_render_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_render(current_user), "render_package_generate", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    _assert_render_allowed(brief, payload)

    render_package = RenderPackage(workspace_id=_workspace_id(current_user), brief_id=brief.id, status="pending")
    db.add(render_package)
    db.flush()
    try:
        result = RenderPackageBuilder().build(payload)
        render_package.status = "generated"
        render_package.output_dir = result["output_dir"]
        render_package.manifest_path = result["manifest_path"]
        render_package.error_message = None
        _write_trace_manifest(Path(result["output_dir"]), _trace_manifest(db, brief, "render_package", current_user))
        _audit(db, "render_package", render_package.id, "render_package_generated", current_user, render_package.output_dir)
    except Exception as exc:
        render_package.status = "failed"
        render_package.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail={"message": "Render package generation failed", "error_message": str(exc)}) from exc
    db.commit()
    db.refresh(render_package)
    return {
        "id": render_package.id,
        "brief_id": render_package.brief_id,
        "status": render_package.status,
        "output_dir": render_package.output_dir,
        "manifest_path": render_package.manifest_path,
        "error_message": render_package.error_message,
        "manifest": result["manifest"],
        "readiness_report": result["readiness_report"],
    }


@router.get("/briefs/{brief_id}/render-package")
def get_render_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    render_package = _latest_render_package(db, brief_id, current_user.workspace_id)
    if render_package is None:
        raise HTTPException(status_code=404, detail="Render package not found")
    manifest = None
    if render_package.manifest_path and Path(render_package.manifest_path).exists():
        manifest = json.loads(Path(render_package.manifest_path).read_text(encoding="utf-8"))
    return {
        "id": render_package.id,
        "brief_id": render_package.brief_id,
        "status": render_package.status,
        "output_dir": render_package.output_dir,
        "manifest_path": render_package.manifest_path,
        "error_message": render_package.error_message,
        "manifest": manifest,
    }


@router.get("/briefs/{brief_id}/render-package/download")
def download_render_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> StreamingResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    _assert_render_allowed(brief, payload)
    render_package = _latest_render_package(db, brief_id, current_user.workspace_id)
    if render_package is None or render_package.status != "generated" or not render_package.output_dir:
        raise HTTPException(status_code=404, detail="Generated render package not found")
    output_dir = Path(render_package.output_dir)
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="Render package directory not found")
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for path in output_dir.iterdir():
            if path.is_file():
                archive.write(path, path.name)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="daily_truth_render_package_{brief_id}.zip"'},
    )


def _latest_final_video(db: Session, brief_id: int, workspace_id: int | None = None) -> FinalVideo | None:
    filters = [FinalVideo.brief_id == brief_id]
    if workspace_id is not None:
        filters.append(FinalVideo.workspace_id == workspace_id)
    return db.scalars(
        select(FinalVideo).where(*filters).order_by(FinalVideo.id.desc())
    ).first()


def _assert_final_video_allowed(brief: BriefScript, payload: dict[str, Any]) -> None:
    safety = payload["safety_review"]
    if brief.status != "approved":
        raise HTTPException(status_code=409, detail="Brief must be approved before final video rendering")
    if safety is None or safety["overall_status"] == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot be rendered")
    tts_status = _tts_status_payload(brief.id)
    if tts_status["status"] == "blocked":
        raise HTTPException(status_code=409, detail="Voice QA is blocked; final video cannot be rendered")


@router.post("/briefs/{brief_id}/final-video")
def generate_final_video(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_render(current_user), "final_video_generate", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    _assert_final_video_allowed(brief, payload)

    render_package = _latest_render_package(db, brief_id, current_user.workspace_id)
    if render_package is None or render_package.status != "generated" or not render_package.output_dir:
        raise HTTPException(status_code=409, detail="Generate render package before final video rendering")
    render_dir = Path(render_package.output_dir)
    if not render_dir.exists():
        raise HTTPException(status_code=409, detail="Render package directory is missing")

    final_video = FinalVideo(
        workspace_id=_workspace_id(current_user),
        brief_id=brief.id,
        render_package_id=render_package.id,
        status="pending",
        tts_provider="local_stub",
    )
    db.add(final_video)
    db.flush()
    output_dir = Path("exports/final_videos") / f"brief_{brief.id}"
    try:
        tts_status = _tts_status_payload(brief.id)
        tts_dir = _tts_dir(brief.id) if tts_status["status"] == "ready" else None
        report = FFMpegRenderer().render(render_dir, output_dir, voice="neutral_zh", tts_dir=tts_dir)
        final_video.status = "rendered"
        final_video.video_path = report["files"]["final_video"]
        final_video.report_path = report["files"]["render_report"]
        final_video.tts_provider = report["tts_provider"]
        final_video.duration_seconds = float(report["duration_seconds"])
        final_video.error_message = None
        _write_trace_manifest(output_dir, _trace_manifest(db, brief, "final_video", current_user))
        _audit(db, "final_video", final_video.id, "final_video_rendered", current_user, final_video.video_path)
    except Exception as exc:
        final_video.status = "failed"
        final_video.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail={"message": "Final video rendering failed", "error_message": str(exc)}) from exc
    db.commit()
    db.refresh(final_video)
    return {
        "id": final_video.id,
        "brief_id": final_video.brief_id,
        "render_package_id": final_video.render_package_id,
        "status": final_video.status,
        "video_path": final_video.video_path,
        "report_path": final_video.report_path,
        "tts_provider": final_video.tts_provider,
        "duration_seconds": final_video.duration_seconds,
        "error_message": final_video.error_message,
        "render_report": report,
    }


@router.get("/briefs/{brief_id}/final-video")
def get_final_video(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    final_video = _latest_final_video(db, brief_id, current_user.workspace_id)
    if final_video is None:
        raise HTTPException(status_code=404, detail="Final video not found")
    report = None
    if final_video.report_path and Path(final_video.report_path).exists():
        report = json.loads(Path(final_video.report_path).read_text(encoding="utf-8"))
    return {
        "id": final_video.id,
        "brief_id": final_video.brief_id,
        "render_package_id": final_video.render_package_id,
        "status": final_video.status,
        "video_path": final_video.video_path,
        "report_path": final_video.report_path,
        "tts_provider": final_video.tts_provider,
        "duration_seconds": final_video.duration_seconds,
        "error_message": final_video.error_message,
        "render_report": report,
    }


@router.get("/briefs/{brief_id}/final-video/download")
def download_final_video(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    _assert_final_video_allowed(brief, payload)
    final_video = _latest_final_video(db, brief_id, current_user.workspace_id)
    if final_video is None or final_video.status != "rendered" or not final_video.video_path:
        raise HTTPException(status_code=404, detail="Rendered final video not found")
    video_path = Path(final_video.video_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Final video file is missing")
    return FileResponse(video_path, media_type="video/mp4", filename=f"daily_truth_final_video_{brief_id}.mp4")


def _latest_platform_package(db: Session, brief_id: int, workspace_id: int | None = None) -> PlatformPackage | None:
    filters = [PlatformPackage.brief_id == brief_id]
    if workspace_id is not None:
        filters.append(PlatformPackage.workspace_id == workspace_id)
    return db.scalars(
        select(PlatformPackage).where(*filters).order_by(PlatformPackage.id.desc())
    ).first()


def _get_usable_final_video(db: Session, brief_id: int, workspace_id: int | None = None) -> FinalVideo:
    final_video = _latest_final_video(db, brief_id, workspace_id)
    if final_video is None or final_video.status != "rendered" or not final_video.video_path:
        raise HTTPException(status_code=409, detail="Generate final video before platform package generation")
    if not Path(final_video.video_path).exists():
        raise HTTPException(status_code=409, detail="Rendered final_video.mp4 is missing")
    return final_video


def _platform_package_payload(platform_package: PlatformPackage) -> dict[str, Any]:
    qa_report = None
    copy_report = None
    evidence_summary = None
    gate_report = None
    platform_copies = {}
    output_dir = Path(platform_package.output_dir) if platform_package.output_dir else None
    if platform_package.qa_report_path and Path(platform_package.qa_report_path).exists():
        qa_report = json.loads(Path(platform_package.qa_report_path).read_text(encoding="utf-8"))
    if output_dir and output_dir.exists():
        copy_path = output_dir / "copy_compliance_report.json"
        if copy_path.exists():
            copy_report = json.loads(copy_path.read_text(encoding="utf-8"))
        evidence_summary_path = output_dir / "evidence_summary.json"
        if evidence_summary_path.exists():
            evidence_summary = json.loads(evidence_summary_path.read_text(encoding="utf-8"))
        gate_path = output_dir / "fact_check_quality_gate.json"
        if gate_path.exists():
            gate_report = json.loads(gate_path.read_text(encoding="utf-8"))
        for platform in ["bilibili", "xiaohongshu", "douyin", "youtube_shorts"]:
            path = output_dir / f"{platform}.json"
            if path.exists():
                platform_copies[platform] = json.loads(path.read_text(encoding="utf-8"))
    return {
        "id": platform_package.id,
        "workspace_id": platform_package.workspace_id,
        "brief_id": platform_package.brief_id,
        "final_video_id": platform_package.final_video_id,
        "platform": platform_package.platform,
        "status": platform_package.status,
        "output_dir": platform_package.output_dir,
        "package_path": platform_package.package_path,
        "qa_report_path": platform_package.qa_report_path,
        "error_message": platform_package.error_message,
        "qa_report": qa_report,
        "copy_compliance_report": copy_report,
        "evidence_summary": evidence_summary,
        "fact_check_quality_gate": gate_report,
        "platform_copies": platform_copies,
        "manual_publish_only": True,
    }


@router.post("/briefs/{brief_id}/platform-package")
def generate_platform_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    PermissionService().assert_allowed(db, current_user, PermissionService().can_generate_platform_package(current_user), "platform_package_generate", entity_type="brief", entity_id=brief_id)
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    safety = payload["safety_review"]
    if brief.status != "approved":
        raise HTTPException(status_code=409, detail="Brief must be approved before platform package generation")
    if safety is None or safety["overall_status"] == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot generate platform package")
    final_video = _get_usable_final_video(db, brief_id, current_user.workspace_id)

    platform_package = PlatformPackage(
        workspace_id=_workspace_id(current_user),
        brief_id=brief.id,
        final_video_id=final_video.id,
        platform="all",
        status="pending",
    )
    db.add(platform_package)
    db.flush()
    try:
        result = PlatformPackageBuilder().build(
            payload,
            {
                "id": final_video.id,
                "video_path": final_video.video_path,
                "duration_seconds": final_video.duration_seconds,
                "tts_provider": final_video.tts_provider,
            },
        )
        blocking = result["qa_report"]["blocking_errors"] or result["copy_compliance_report"]["blocking_errors"]
        platform_package.status = "blocked" if blocking else "generated"
        platform_package.output_dir = result["output_dir"]
        platform_package.package_path = result["package_path"]
        platform_package.qa_report_path = result["qa_report_path"]
        platform_package.error_message = "; ".join(blocking) if blocking else None
        trace_path = _write_trace_manifest(Path(result["output_dir"]), _trace_manifest(db, brief, "platform_package", current_user))
        with ZipFile(result["package_path"], "a", ZIP_DEFLATED) as archive:
            archive.write(trace_path, "trace_manifest.json")
        _audit(db, "platform_package", platform_package.id, "platform_package_generated", current_user, platform_package.package_path)
    except Exception as exc:
        platform_package.status = "failed"
        platform_package.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=500, detail={"message": "Platform package generation failed", "error_message": str(exc)}) from exc
    db.commit()
    db.refresh(platform_package)
    return {
        **_platform_package_payload(platform_package),
        "qa_report": result["qa_report"],
        "copy_compliance_report": result["copy_compliance_report"],
        "evidence_summary": result["evidence_summary"],
        "fact_check_quality_gate": result["fact_check_quality_gate"],
        "platform_copies": result["platform_copies"],
    }


@router.get("/briefs/{brief_id}/platform-package")
def get_platform_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    platform_package = _latest_platform_package(db, brief_id, current_user.workspace_id)
    if platform_package is None:
        raise HTTPException(status_code=404, detail="Platform package not found")
    return _platform_package_payload(platform_package)


@router.get("/briefs/{brief_id}/platform-package/download")
def download_platform_package(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> FileResponse:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    payload = _brief_payload(brief, db)
    safety = payload["safety_review"]
    if brief.status != "approved":
        raise HTTPException(status_code=409, detail="Brief must be approved before platform package download")
    if safety is None or safety["overall_status"] == "blocked":
        raise HTTPException(status_code=409, detail="Blocked safety review cannot download platform package")
    platform_package = _latest_platform_package(db, brief_id, current_user.workspace_id)
    if platform_package is None or platform_package.status != "generated" or not platform_package.package_path:
        raise HTTPException(status_code=404, detail="Generated platform package not found")
    package_path = Path(platform_package.package_path)
    if not package_path.exists():
        raise HTTPException(status_code=404, detail="Platform package zip is missing")
    return FileResponse(package_path, media_type="application/zip", filename=f"daily_truth_platform_package_{brief_id}.zip")


@router.get("/briefs/{brief_id}/video-asset")
def get_video_asset(
    brief_id: int,
    db: Session = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    brief = db.get(BriefScript, brief_id)
    if brief is None:
        raise HTTPException(status_code=404, detail="Brief not found")
    _assert_same_workspace(brief, current_user, "Brief not found")
    video_asset = db.scalars(
        select(VideoAsset).where(VideoAsset.brief_script_id == brief_id).order_by(VideoAsset.id.desc())
    ).first()
    if video_asset is None:
        raise HTTPException(status_code=404, detail="Video asset not found")
    return {
        "id": video_asset.id,
        "brief_id": video_asset.brief_script_id,
        "status": video_asset.status,
        "export_allowed": video_asset.export_allowed,
        "asset_json": video_asset.asset_json,
    }
