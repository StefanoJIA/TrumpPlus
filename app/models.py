from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500))
    terms_safe: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    posts: Mapped[list["Post"]] = relationship(back_populates="source")


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    user_account_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="viewer")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    workspace: Mapped[Workspace] = relationship()
    user_account: Mapped["UserAccount"] = relationship()


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    email_or_name: Mapped[str] = mapped_column(String(180), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="viewer")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    workspace: Mapped[Workspace] = relationship()


class ApiToken(Base):
    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped[Workspace] = relationship()


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    post_id: Mapped[str] = mapped_column(String(180), nullable=False, unique=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False, unique=True)
    short_excerpt: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    fact_check_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    source_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ranking_score: Mapped[float | None] = mapped_column(Float)
    ranking_breakdown: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source: Mapped[Source] = relationship(back_populates="posts")
    claims: Mapped[list["Claim"]] = relationship(back_populates="post")


class SourceReviewItem(Base):
    __tablename__ = "source_review_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    adapter_name: Mapped[str] = mapped_column(String(120), nullable=False)
    source_name: Mapped[str] = mapped_column(String(180), nullable=False)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False)
    archive_url: Mapped[str | None] = mapped_column(String(800))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_excerpt: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    media_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    terms_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    human_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(120))
    request_id: Mapped[str | None] = mapped_column(String(120))
    actor_name: Mapped[str | None] = mapped_column(String(120))
    actor_role: Mapped[str | None] = mapped_column(String(40))
    before_state_hash: Mapped[str | None] = mapped_column(String(64))
    after_state_hash: Mapped[str | None] = mapped_column(String(64))
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserAccount(Base):
    __tablename__ = "user_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(180), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False)
    claim_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(40), nullable=False)
    requires_fact_check: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="claims")
    fact_checks: Mapped[list["FactCheck"]] = relationship(back_populates="claim")
    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="claim")
    evidence_links: Mapped[list["ClaimEvidenceLink"]] = relationship(back_populates="claim")
    evidence_packs: Mapped[list["EvidencePack"]] = relationship(back_populates="claim")


class FactCheck(Base):
    __tablename__ = "fact_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String(40), nullable=False)
    rationale: Mapped[str] = mapped_column(String(1200), nullable=False)
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, default="mock")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped[Claim] = relationship(back_populates="fact_checks")


class EvidenceSource(Base):
    __tablename__ = "evidence_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_name: Mapped[str] = mapped_column(String(180), nullable=False)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False)
    archive_url: Mapped[str | None] = mapped_column(String(800))
    publisher_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    reliability_tier: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    terms_status: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_review_required")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    evidence_items: Mapped[list["EvidenceItem"]] = relationship(back_populates="evidence_source")


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    source_review_item_id: Mapped[int | None] = mapped_column(ForeignKey("source_review_items.id"))
    post_id: Mapped[int | None] = mapped_column(ForeignKey("posts.id"))
    claim_id: Mapped[int | None] = mapped_column(ForeignKey("claims.id"))
    evidence_source_id: Mapped[int | None] = mapped_column(ForeignKey("evidence_sources.id"))
    evidence_type: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_note")
    title: Mapped[str | None] = mapped_column(String(300))
    source_name: Mapped[str | None] = mapped_column(String(180))
    source_url: Mapped[str | None] = mapped_column(String(800))
    archive_url: Mapped[str | None] = mapped_column(String(800))
    excerpt: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reliability_score: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    terms_status: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_review_required")
    human_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    created_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    supports_claim: Mapped[str] = mapped_column(String(40), nullable=False, default="unclear")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    claim: Mapped[Claim] = relationship(back_populates="evidence_items")
    evidence_source: Mapped[EvidenceSource] = relationship(back_populates="evidence_items")
    claim_links: Mapped[list["ClaimEvidenceLink"]] = relationship(back_populates="evidence_item")


class ClaimEvidenceLink(Base):
    __tablename__ = "claim_evidence_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    evidence_item_id: Mapped[int] = mapped_column(ForeignKey("evidence_items.id"), nullable=False)
    support_type: Mapped[str] = mapped_column(String(40), nullable=False, default="contextualizes")
    confidence: Mapped[str] = mapped_column(String(40), nullable=False, default="medium")
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped[Claim] = relationship(back_populates="evidence_links")
    evidence_item: Mapped[EvidenceItem] = relationship(back_populates="claim_links")


class EvidencePack(Base):
    __tablename__ = "evidence_packs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    verdict: Mapped[str] = mapped_column(String(40), nullable=False, default="unclear")
    rationale: Mapped[str] = mapped_column(String(1200), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    claim: Mapped[Claim] = relationship(back_populates="evidence_packs")


class EvidenceCandidate(Base):
    __tablename__ = "evidence_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claims.id"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    source_name: Mapped[str] = mapped_column(String(180), nullable=False)
    source_url: Mapped[str] = mapped_column(String(800), nullable=False)
    archive_url: Mapped[str | None] = mapped_column(String(800))
    excerpt: Mapped[str] = mapped_column(String(500), nullable=False)
    publisher_type: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    reliability_tier: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
    search_query: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    reviewer_note: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    claim: Mapped[Claim] = relationship()


class BriefScript(Base):
    __tablename__ = "brief_scripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    script_text: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_draft: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    sources: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    ranked_posts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    claims: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    fact_checks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    visual_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    safety_reviews: Mapped[list["SafetyReview"]] = relationship(back_populates="brief_script")
    video_assets: Mapped[list["VideoAsset"]] = relationship(back_populates="brief_script")
    render_packages: Mapped[list["RenderPackage"]] = relationship(back_populates="brief_script")
    final_videos: Mapped[list["FinalVideo"]] = relationship(back_populates="brief_script")
    platform_packages: Mapped[list["PlatformPackage"]] = relationship(back_populates="brief_script")


class EditorialTopic(Base):
    __tablename__ = "editorial_topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    summary: Mapped[str] = mapped_column(String(1200), nullable=False)
    topic_type: Mapped[str] = mapped_column(String(60), nullable=False, default="public_post_cluster")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evidence_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    platform_fit_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    selected_post_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_claim_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    rationale: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    editor_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EditorialCalendarEntry(Base):
    __tablename__ = "editorial_calendar_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    date: Mapped[date] = mapped_column(Date, nullable=False)
    topic_id: Mapped[int] = mapped_column(ForeignKey("editorial_topics.id"), nullable=False)
    slot_name: Mapped[str] = mapped_column(String(120), nullable=False)
    target_platforms: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    planned_duration: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    assigned_editor: Mapped[str | None] = mapped_column(String(120))
    publish_window_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    topic: Mapped[EditorialTopic] = relationship()


class SafetyReview(Base):
    __tablename__ = "safety_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brief_script_id: Mapped[int] = mapped_column(ForeignKey("brief_scripts.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    checks: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    human_review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    human_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reviewer_name: Mapped[str | None] = mapped_column(String(120))
    reviewer_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    brief_script: Mapped[BriefScript] = relationship(back_populates="safety_reviews")


class VideoAsset(Base):
    __tablename__ = "video_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    brief_script_id: Mapped[int] = mapped_column(ForeignKey("brief_scripts.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    asset_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    export_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    brief_script: Mapped[BriefScript] = relationship(back_populates="video_assets")


class RenderPackage(Base):
    __tablename__ = "render_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    brief_id: Mapped[int] = mapped_column(ForeignKey("brief_scripts.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    output_dir: Mapped[str | None] = mapped_column(String(1000))
    manifest_path: Mapped[str | None] = mapped_column(String(1000))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    brief_script: Mapped[BriefScript] = relationship(back_populates="render_packages")


class FinalVideo(Base):
    __tablename__ = "final_videos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    brief_id: Mapped[int] = mapped_column(ForeignKey("brief_scripts.id"), nullable=False)
    render_package_id: Mapped[int] = mapped_column(ForeignKey("render_packages.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    video_path: Mapped[str | None] = mapped_column(String(1000))
    report_path: Mapped[str | None] = mapped_column(String(1000))
    tts_provider: Mapped[str | None] = mapped_column(String(80))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    brief_script: Mapped[BriefScript] = relationship(back_populates="final_videos")
    render_package: Mapped[RenderPackage] = relationship()


class PlatformPackage(Base):
    __tablename__ = "platform_packages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"))
    brief_id: Mapped[int] = mapped_column(ForeignKey("brief_scripts.id"), nullable=False)
    final_video_id: Mapped[int] = mapped_column(ForeignKey("final_videos.id"), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), nullable=False, default="all")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    output_dir: Mapped[str | None] = mapped_column(String(1000))
    package_path: Mapped[str | None] = mapped_column(String(1000))
    qa_report_path: Mapped[str | None] = mapped_column(String(1000))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    brief_script: Mapped[BriefScript] = relationship(back_populates="platform_packages")
    final_video: Mapped[FinalVideo] = relationship()
