from __future__ import annotations

from dataclasses import dataclass


VALID_ROLES = {"admin", "editor", "reviewer", "producer", "viewer"}


@dataclass(frozen=True)
class CurrentUserContext:
    user_id: int | None
    user_name: str
    role: str
    workspace_id: int | None
    auth_mode: str
    is_authenticated: bool
    is_stub: bool
    request_id: str | None
    display_name: str | None = None
    workspace_slug: str | None = None

    @property
    def username(self) -> str:
        return self.user_name

    @property
    def is_active(self) -> bool:
        return self.is_authenticated

    def with_workspace(self, workspace_id: int, workspace_slug: str | None = None) -> "CurrentUserContext":
        return CurrentUserContext(
            user_id=self.user_id,
            user_name=self.user_name,
            role=self.role,
            workspace_id=workspace_id,
            auth_mode=self.auth_mode,
            is_authenticated=self.is_authenticated,
            is_stub=self.is_stub,
            request_id=self.request_id,
            display_name=self.display_name or self.user_name,
            workspace_slug=workspace_slug,
        )
