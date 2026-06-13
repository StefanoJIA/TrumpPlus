from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.context import CurrentUserContext
from app.auth.providers.base import AuthProvider
from app.core.environment import load_environment


class ExternalPlaceholderAuthProvider(AuthProvider):
    """Placeholder for OAuth/Auth0/Clerk/internal SSO integration.

    This provider intentionally does not authenticate users yet. Staging and
    production should wire a real external provider before enabling write APIs.
    """

    def validate_environment(self) -> None:
        config = load_environment()
        if config.auth_mode != "external":
            raise RuntimeError("ExternalPlaceholderAuthProvider requires AUTH_MODE=external")

    def authenticate(self, request: Request, db: Session) -> CurrentUserContext:
        self.validate_environment()
        raise HTTPException(status_code=501, detail="External auth placeholder is configured but no provider is connected")
