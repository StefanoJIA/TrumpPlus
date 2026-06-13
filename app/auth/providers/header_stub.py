from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.context import CurrentUserContext, VALID_ROLES
from app.auth.providers.base import AuthProvider
from app.core.environment import load_environment
from app.core.request_context import get_request_id
from app.models import Workspace
from app.services.workspace_service import WorkspaceService


class HeaderStubAuthProvider(AuthProvider):
    def validate_environment(self) -> None:
        config = load_environment()
        if config.app_env not in {"local", "test"}:
            raise RuntimeError("header_stub auth is only allowed in local/test")

    def authenticate(self, request: Request, db: Session) -> CurrentUserContext:
        self.validate_environment()
        role = (request.headers.get("X-User-Role") or "viewer").strip().lower()
        if role not in VALID_ROLES:
            role = "viewer"
        username = (request.headers.get("X-User-Name") or "anonymous_viewer").strip() or "anonymous_viewer"
        service = WorkspaceService()
        workspace_id_header = request.headers.get("X-Workspace-ID")
        if workspace_id_header and workspace_id_header.isdigit():
            workspace = db.get(Workspace, int(workspace_id_header))
            if workspace is None:
                raise HTTPException(status_code=404, detail="Workspace not found")
        else:
            workspace = service.get_workspace(db, None)
        user = service.ensure_user_and_membership(db, username, role, workspace)
        db.commit()
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or get_request_id()
        return CurrentUserContext(
            user_id=user.id,
            user_name=username,
            role=role,
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            auth_mode="header_stub",
            is_authenticated=True,
            is_stub=True,
            request_id=request_id,
            display_name=user.display_name,
        )
