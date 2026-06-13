# truth-monitor extension
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
from typing import Any

from app.db import SessionLocal
from app.models import AuditLog, SourceReviewItem, Workspace
from storage.db import get_uninjected_posts, mark_injected


async def inject_new_posts_to_intake(workspace_id: str) -> int:
    """Inject uninjected stored Truth Social posts into the existing source review queue."""
    return await asyncio.to_thread(_inject_sync, workspace_id)


def _inject_sync(workspace_id: str) -> int:
    """Synchronous SQLAlchemy bridge, run in a worker thread by the async public function."""
    db = SessionLocal()
    injected = 0
    try:
        resolved_workspace_id = _resolve_workspace_id(db, workspace_id)
        for post in get_uninjected_posts(limit=20):
            existing = (
                db.query(SourceReviewItem)
                .filter(
                    SourceReviewItem.workspace_id == resolved_workspace_id,
                    SourceReviewItem.source_url == post["url"],
                )
                .first()
            )
            if existing is None:
                item = SourceReviewItem(
                    workspace_id=resolved_workspace_id,
                    adapter_name="truth_fetcher",
                    source_name="Truth Social @realDonaldTrump",
                    source_url=post["url"],
                    archive_url="",
                    retrieved_at=_parse_datetime(post.get("created_at")),
                    raw_excerpt=(post.get("text") or "")[:500],
                    normalized_summary=(post.get("text") or "")[:1000],
                    media_refs=post.get("local_media") or post.get("media_urls") or [],
                    terms_status="pending",
                    human_status="pending",
                    metadata_json={
                        "truth_post_id": post["id"],
                        "fetched_at": post.get("fetched_at"),
                        "media_urls": post.get("media_urls", []),
                        "local_media": post.get("local_media", []),
                        "requires_human_source_review": True,
                    },
                )
                db.add(item)
                db.flush()
                _add_audit(db, item, "truth_fetcher_inject_to_source_review", "Injected Truth Social post into source review queue")
                injected += 1
            mark_injected(str(post["id"]))
        db.commit()
        return injected
    finally:
        db.close()


def _resolve_workspace_id(db: Any, workspace_id: str) -> int | None:
    """Resolve a workspace ID from an integer string, slug, name, or the default workspace."""
    if not workspace_id or workspace_id == "default":
        workspace = db.query(Workspace).filter(Workspace.slug == "daily-truth-brief-dev").first()
        if workspace is None:
            workspace = db.query(Workspace).filter(Workspace.status == "active").order_by(Workspace.id.asc()).first()
        return workspace.id if workspace else None
    if str(workspace_id).isdigit():
        return int(workspace_id)
    workspace = (
        db.query(Workspace)
        .filter((Workspace.slug == workspace_id) | (Workspace.name == workspace_id))
        .first()
    )
    return workspace.id if workspace else None


def _parse_datetime(value: str | None) -> datetime:
    """Parse an ISO datetime string, falling back to now."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


def _add_audit(db: Any, item: SourceReviewItem, action: str, note: str) -> None:
    """Record an AuditLog entry for the injected source item."""
    request_id = f"truth-monitor-{datetime.now(timezone.utc).timestamp():.0f}"
    state = {
        "workspace_id": item.workspace_id,
        "entity_type": "source_review_item",
        "entity_id": item.id,
        "action": action,
        "actor": "truth_monitor",
        "actor_role": "system",
        "note": note,
        "request_id": request_id,
    }
    db.add(
        AuditLog(
            workspace_id=item.workspace_id,
            entity_type="source_review_item",
            entity_id=item.id,
            action=action,
            actor="truth_monitor",
            actor_name="truth_monitor",
            actor_role="system",
            request_id=request_id,
            before_state_hash=None,
            after_state_hash=hashlib.sha256(repr(sorted(state.items())).encode("utf-8")).hexdigest(),
            immutable=True,
            note=note,
        )
    )

