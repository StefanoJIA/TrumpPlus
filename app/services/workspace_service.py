from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApiToken, Invite, TeamMember, UserAccount, Workspace


DEFAULT_WORKSPACE_SLUG = "daily-truth-brief-dev"


class WorkspaceService:
    def ensure_default_workspace(self, db: Session) -> Workspace:
        workspace = db.scalar(select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG))
        if workspace is not None:
            return workspace
        workspace = Workspace(name="Daily Truth Brief Dev", slug=DEFAULT_WORKSPACE_SLUG, status="active")
        db.add(workspace)
        db.flush()
        return workspace

    def get_workspace(self, db: Session, workspace_id: int | None) -> Workspace:
        workspace = db.get(Workspace, workspace_id) if workspace_id else self.ensure_default_workspace(db)
        if workspace is None:
            workspace = self.ensure_default_workspace(db)
        return workspace

    def ensure_user_and_membership(self, db: Session, username: str, role: str, workspace: Workspace) -> UserAccount:
        user = db.scalar(select(UserAccount).where(UserAccount.username == username))
        if user is None:
            user = UserAccount(username=username, display_name=username, role=role, is_active=True)
            db.add(user)
            db.flush()
        elif user.role != role:
            user.role = role
        member = db.scalar(
            select(TeamMember).where(
                TeamMember.workspace_id == workspace.id,
                TeamMember.user_account_id == user.id,
            )
        )
        if member is None:
            db.add(TeamMember(workspace_id=workspace.id, user_account_id=user.id, role=role, status="active"))
        elif member.role != role:
            member.role = role
            member.status = "active"
        db.flush()
        return user

    def workspace_payload(self, workspace: Workspace) -> dict[str, Any]:
        return {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "status": workspace.status,
            "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
            "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
        }

    def create_invite(self, db: Session, *, workspace_id: int, email_or_name: str, role: str, created_by: str) -> tuple[Invite, str]:
        token = secrets.token_urlsafe(24)
        invite = Invite(
            workspace_id=workspace_id,
            email_or_name=email_or_name,
            role=role,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            status="pending",
            created_by=created_by,
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        )
        db.add(invite)
        db.flush()
        return invite, token

    def create_api_token(self, db: Session, *, workspace_id: int, name: str, scopes: list[str], created_by: str) -> tuple[ApiToken, str]:
        token = "dtb_" + secrets.token_urlsafe(24)
        api_token = ApiToken(
            workspace_id=workspace_id,
            name=name,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            scopes=scopes,
            status="active",
            created_by=created_by,
        )
        db.add(api_token)
        db.flush()
        return api_token, token
