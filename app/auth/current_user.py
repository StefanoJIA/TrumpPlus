from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.auth.context import CurrentUserContext
from app.auth.providers.external_placeholder import ExternalPlaceholderAuthProvider
from app.auth.providers.header_stub import HeaderStubAuthProvider
from app.core.environment import load_environment
from app.core.request_context import get_request_id
from app.db import get_db
from app.services.workspace_service import WorkspaceService


CurrentUser = CurrentUserContext


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    config = load_environment()
    if config.auth_mode == "external":
        provider = ExternalPlaceholderAuthProvider()
    elif config.auth_mode == "header_stub":
        provider = HeaderStubAuthProvider()
    else:
        workspace = WorkspaceService().ensure_default_workspace(db)
        db.commit()
        user = CurrentUserContext(
            user_id=None,
            user_name="anonymous_viewer",
            display_name="anonymous_viewer",
            role="viewer",
            workspace_id=workspace.id,
            workspace_slug=workspace.slug,
            auth_mode="disabled",
            is_authenticated=False,
            is_stub=False,
            request_id=getattr(request.state, "request_id", None) or get_request_id(),
        )
        from app.core.request_context import set_current_user

        set_current_user(user)
        return user
    user = provider.authenticate(request, db)
    from app.core.request_context import set_current_user

    set_current_user(user)
    return user
